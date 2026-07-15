"""Phase 12 Task 10 端到端红灯。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §5/§9/§11。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 10 Step 1。

链路：9000 创建本地素材 ID -> 19000 导入 -> Worker 合成媒体链（pipeline 替身 ffmpeg/probe）
-> 9100 规划替身（plan_ai_edit + 替身 LLM）-> 720P 预览 -> 1080P 成片 -> 9000 状态回写。
覆盖取消、重启恢复、跨商户、路径逃逸、旧 attempt 回写。

红线（Step 1 Expected）：本探针必须真实经过 9000/19000/Worker/9100 四边界并证伪至少一个
未闭合的集成缺口。当前缺口：19000 executor/on_job_terminal 完成任务后不回写 9000 状态
（设计 §5「19000 与 9000 通信并转发安全进度」未实现），且 9000 create_job 公共响应不返回
执行令牌（§10），19000 无 token 下发通道回写 update_job_status。故 drain 后 9000 任务
仍停在 queued，断言 succeeded 必然失败。

替身：合成媒体字节 + 假 ffmpeg runner（写非空产物）+ 假 ffprobe（返回 1080p has_audio）
+ 9100 plan_ai_edit 注入替身 LLM（不调真实模型）；ComputeUsageClient 上报置 no-op 避免网络。
不连宝塔/生产库/真实 9100/真实付费模型；不执行真实 FFmpeg。
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
import app.models  # noqa: F401  触发全部 ORM 注册
from app.local_agent_ai_edit_routes import create_ai_edit_router
from app.local_agent_ai_edit_supervisor import AiEditSupervisor
from apps.ai_edit.pipeline import PipelineDeps, run_pipeline

# ---------------------------------------------------------------------------
# 9000 控制面脚手架（复用 test_phase12_ai_edit_api 模式）
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ctx(merchant_id: str = "m1") -> RequestContext:
    return RequestContext(
        user_id="u1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=["auto_wechat:ai_edit"],
        super_admin=False,
        auth_mode="mock",
    )


def _build_9000(merchant_id: str = "m1", token: str = "tok-1") -> TestClient:
    from app.main import create_app

    os.environ["LOCAL_AGENT_TOKENS"] = f"{merchant_id}:{token}"
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: _ctx(merchant_id)
    return TestClient(app)


def _job_token(job_id: str) -> tuple[str, int]:
    """白盒读取 9000 任务当前执行令牌哈希与 attempt（公共 API 不返回令牌，§10）。"""
    from app.models import AiEditJob

    db = TestSession()
    try:
        job = db.query(AiEditJob).filter_by(job_id=job_id).one()
        return job.execution_token_hash, job.attempt_count
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 19000 执行面脚手架：替身 pipeline deps + 替身 executor（真实经过 pipeline + 9100）
# ---------------------------------------------------------------------------

_SYNTHETIC_BYTES = b"phase12-e2e-synthetic-video-bytes" * 4


def _synthetic_sha() -> str:
    return hashlib.sha256(_SYNTHETIC_BYTES).hexdigest()


def _stub_pipeline_deps() -> PipelineDeps:
    """替身 deps：假 ffmpeg 写非空产物 + 假 ffprobe 返回 1080p has_audio + plan 调真实 9100。"""
    from apps.xg_douyin_ai_cs.schemas import (
        AiEditPlanRequest,
        SceneSummary,
        TranscriptSegment,
)
    from apps.xg_douyin_ai_cs.services.ai_edit_planner_service import plan_ai_edit

    class _StubLLM:
        """替身 LLM：返回严格合法的 keep operations，不调真实模型。"""

        def chat(self, messages):  # noqa: ANN001
            mid = "mat-1"
            return {
                "reply_text": json_dumps_keep(mid),
                "model": "stub-llm",
            }

    def _runner(cmd, *, timeout_seconds=None, cancel_check=None, cwd=None):
        # 假 ffmpeg：output 是 cmd 最后一个 .mp4 参数（input 在前），写非空字节
        out = next((str(p) for p in reversed(cmd) if str(p).endswith(".mp4")), None)
        if out is not None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"fake-mp4-output-bytes" * 8)
        return 0

    def _probe(path):
        return {"has_audio": True, "duration": 30.0, "width": 1080, "height": 1920}

    def _analyze(manifest, task_root):
        mid = manifest.materials[0].material_id
        end = float(manifest.materials[0].duration_seconds)
        return {
            "transcript_segments": [
                {"material_id": mid, "start_seconds": 0.0, "end_seconds": end,
                 "text": "这是一段汽车口播内容"}
            ]
        }

    def _plan(manifest, analysis, task_root):
        # 真实经过 9100 边界：调 plan_ai_edit（注入替身 LLM，不调真实模型）
        mid = manifest.materials[0].material_id
        end = float(manifest.materials[0].duration_seconds)
        seg = TranscriptSegment(material_id=mid, start_seconds=0.0,
                                end_seconds=end, text="汽车口播")
        scene = SceneSummary(material_id=mid, start_seconds=0.0,
                             end_seconds=end, scene_label="主镜头", stability_score=0.9)
        req = AiEditPlanRequest(
            merchant_id="m1", job_id=manifest.job_id, template_key="tpl",
            template_version="v1", target_duration_seconds=30,
            transcript_segments=[seg], scenes=[scene],
        )
        plan = plan_ai_edit(req, llm_client=_StubLLM())
        assert plan.status == "ok", f"9100 规划应成功，实际 {plan.status}/{plan.failure_code}"
        return {
            "operations": [
                {"material_id": op.material_id, "start_seconds": op.start_seconds,
                 "end_seconds": op.end_seconds, "action": op.action}
                for op in plan.operations
            ]
        }

    def _stabilize(*a, **kw):  # noqa: ANN002  stabilize_enabled=False 不触发
        raise AssertionError("不应触发增稳")

    return PipelineDeps(
        runner=_runner, probe=_probe, analyze=_analyze, plan=_plan,
        stabilize=_stabilize, stabilize_enabled=lambda m: False, ffmpeg_binary="ffmpeg",
    )


def json_dumps_keep(material_id: str) -> str:
    import json as _json
    return _json.dumps({
        "operations": [
            {"material_id": material_id, "start_seconds": 0.0,
             "end_seconds": 10.0, "action": "keep", "reason": None}
        ]
    }, ensure_ascii=False)


def _build_19000(tmp_path, c9, *, merchant="m1", token="tok-1") -> tuple[TestClient, AiEditSupervisor]:
    """19000 路由 + 监管器；executor 调真实 pipeline（替身 deps）经过 Worker 边界。

    nine000_client 为直调 9000 TestClient 的替身（§5 下发/回写通道）；
    on_job_terminal 用令牌回写 9000 status。
    """
    os.environ["LOCAL_AGENT_TOKENS"] = f"{merchant}:{token}"
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"
    storage_root = tmp_path / "managed"
    work_root = tmp_path / "work"
    deps = _stub_pipeline_deps()

    class _DirectNine000Client:
        """替身 9000 client：直调 9000 TestClient（无 HTTP，不算外部网络）。"""

        def agent_create_job(self, *, merchant_id, job_id, template_key, materials):
            resp = c9.post(
                "/ai-edit/jobs/agent-create",
                headers={"X-Local-Agent-Token": token},
                json={"job_id": job_id, "template_key": template_key, "materials": materials},
            )
            assert resp.status_code in (200, 201), f"agent-create: {resp.status_code} {resp.text}"
            return resp.json()["data"]

        def update_job_status(self, *, merchant_id, job_id, execution_token_hash,
                              attempt_count, status, stage=None, progress=None,
                              failure_code=None, error_summary=None):
            payload = {
                "execution_token_hash": execution_token_hash,
                "attempt_count": attempt_count, "status": status,
            }
            if stage is not None:
                payload["stage"] = stage
            if progress is not None:
                payload["progress"] = progress
            if failure_code is not None:
                payload["failure_code"] = failure_code
            if error_summary is not None:
                payload["error_summary"] = error_summary
            resp = c9.post(
                f"/ai-edit/jobs/{job_id}/status",
                headers={"X-Local-Agent-Token": token}, json=payload,
            )
            assert resp.status_code in (200, 201), f"status writeback: {resp.status_code} {resp.text}"
            return resp.json()["data"]

    nine000_client = _DirectNine000Client()

    def _executor(job):
        from apps.ai_edit.worker_main import load_manifest

        manifest = load_manifest(Path(job.manifest_path))
        result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
        return {"status": result.status, "failure_code": getattr(result, "failure_code", None)}

    def _on_terminal(job, status):
        # §5：用 agent-create 下发的令牌回写 9000 终态
        if job.execution_token_hash:
            nine000_client.update_job_status(
                merchant_id=job.merchant_id, job_id=job.job_id,
                execution_token_hash=job.execution_token_hash,
                attempt_count=job.attempt_count, status=status,
                stage="completed" if status == "succeeded" else status,
                progress=100 if status == "succeeded" else None,
            )

    sup = AiEditSupervisor(
        work_root=work_root, executor=_executor, on_job_terminal=_on_terminal,
    )
    app = FastAPI()
    app.include_router(create_ai_edit_router(
        supervisor=sup, storage_root=storage_root, work_root=work_root,
        nine000_client=nine000_client,
    ))
    client = TestClient(app)
    client._storage_root = storage_root
    client._work_root = work_root
    client._sup = sup
    return client, sup


def _import_19000(client, *, material_id="mat-1", content=_SYNTHETIC_BYTES, token="tok-1"):
    return client.post(
        "/agent/ai-edit/materials/import",
        headers={"X-Local-Agent-Token": token},
        json={
            "material_id": material_id,
            "expected_size": len(content),
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    )


def _register_9000(client, *, material_id="mat-1", sha=None, token="tok-1"):
    return client.post(
        "/ai-edit/materials",
        headers={"X-Local-Agent-Token": token},
        json={
            "material_id": material_id, "media_type": "video",
            "source_sha256": sha or _synthetic_sha(), "agent_client_id": "agent-x",
        },
    )


def _create_job_9000(client, *, job_id="job-1", material_id="mat-1", sha=None):
    return client.post("/ai-edit/jobs", json={
        "job_id": job_id, "template_key": "tpl",
        "materials": [{"material_id": material_id, "role": "main", "position": 0,
                       "pinned_sha256": sha or _synthetic_sha(),
                       "source_start": 0.0, "source_end": 10.0}],
    })


@pytest.fixture(autouse=True)
def _silence_compute_report(monkeypatch):
    """9100 plan 成功后 _report_usage 会调 ComputeUsageClient（网络）；替身为 no-op。"""
    from apps.xg_douyin_ai_cs.services import compute_usage_client

    monkeypatch.setattr(
        compute_usage_client.ComputeUsageClient, "report_usage", lambda self, **kw: None
    )


# ---------------------------------------------------------------------------
# 红线：完整链路后 9000 状态必须回写为 succeeded（当前断）
# ---------------------------------------------------------------------------


def test_e2e_full_chain_writes_back_9000_status(tmp_path):
    """9000 注册素材 -> 19000 导入/创建(经 9000 agent-create 领令牌) -> Worker(pipeline+9100替身)
    -> 19000 终态回写 9000 -> 9000 GET 状态 = succeeded。

    绿线条件：19000 on_job_terminal 用 agent-create 下发的令牌回写 9000 status。
    """
    sha = _synthetic_sha()
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    # 1. 9000 注册素材（token→m1，sha=本机哈希）
    assert _register_9000(c9, sha=sha).status_code in (200, 201)

    # 2. 19000 导入同一字节素材（哈希一致）
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)

    # 3. 19000 创建本机任务：内部调 9000 agent-create 领令牌 + 写 manifest + 入队
    resp = c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    assert resp.status_code in (200, 201), resp.text

    # 4. Worker 执行（替身 executor 调真实 pipeline + 真实 9100 plan_ai_edit 替身 LLM）
    sup.drain()

    # 5. 19000 本地状态确已 succeeded（证明经过 Worker + 9100 边界）
    local = c19.get("/agent/ai-edit/jobs/job-1", headers={"X-Local-Agent-Token": "tok-1"})
    assert local.status_code == 200
    assert local.json()["data"]["status"] == "succeeded"

    # 6. 9000 状态由 19000 终态回写为 succeeded（§5 转发进度）
    detail = c9.get("/ai-edit/jobs/job-1")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "succeeded", (
        "19000 on_job_terminal 未回写 9000 状态（§5 转发进度）"
    )


def test_e2e_cancel_writes_back_cancelled(tmp_path):
    """取消链路：19000 create -> cancel -> drain -> 9000 状态回写为 cancelled。"""
    sha = _synthetic_sha()
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    assert _register_9000(c9, sha=sha).status_code in (200, 201)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)

    # 取消（队列中，未 drain）-> drain 归一为 cancelled -> 回写 9000
    cancel = c19.post("/agent/ai-edit/jobs/job-1/cancel",
                      headers={"X-Local-Agent-Token": "tok-1"})
    assert cancel.status_code == 200
    sup.drain()

    detail = c9.get("/ai-edit/jobs/job-1")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "cancelled"


def test_e2e_stale_attempt_writeback_rejected(tmp_path):
    """旧 attempt 回写被拒：9000 retry 推进令牌后，19000 用旧令牌回写 -> 409 STALE_ATTEMPT_TOKEN。"""
    sha = _synthetic_sha()
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    assert _register_9000(c9, sha=sha).status_code in (200, 201)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)

    # 9000 retry：attempt 0→1，令牌轮换；旧令牌回写必须 409
    old_token, old_attempt = _job_token("job-1")
    assert c9.post("/ai-edit/jobs/job-1/retry").status_code == 200
    resp = c9.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": old_token, "attempt_count": old_attempt,
              "status": "succeeded", "stage": "completed", "progress": 100},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STALE_ATTEMPT_TOKEN"
