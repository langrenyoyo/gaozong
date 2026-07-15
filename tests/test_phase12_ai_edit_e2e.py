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


def _build_9000(merchant_id: str = "m1", token: str = "tok-1", tokens: str | None = None) -> TestClient:
    from app.main import create_app

    os.environ["LOCAL_AGENT_TOKENS"] = tokens or f"{merchant_id}:{token}"
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


def _build_19000(tmp_path, c9, *, merchant="m1", token="tok-1",
                  failing_methods: set[str] | None = None) -> tuple[TestClient, AiEditSupervisor]:
    """19000 路由 + 监管器；executor 调真实 pipeline（替身 deps）经过 Worker 边界。

    nine000_client 为直调 9000 TestClient 的替身（§5 下发/回写通道）；
    on_job_terminal 用令牌回写 9000 status。
    failing_methods：注入指定方法抛错（FIX3-4 测同步失败路径），如 {"register_material"}。
    """
    os.environ["LOCAL_AGENT_TOKENS"] = f"{merchant}:{token}"
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"
    storage_root = tmp_path / "managed"
    work_root = tmp_path / "work"
    deps = _stub_pipeline_deps()

    class _DirectNine000Client:
        """替身 9000 client, 直调 9000 TestClient (无 HTTP, 不算外部网络).

        真实前端调用顺序: 19000 导入->register_material; 19000 创建->agent_create_job;
        19000 重试->agent_retry_job; 终态->update_job_status; 19000 删除->delete_material.
        failing: 注入指定方法名抛 RuntimeError (FIX3-4 测失败路径).
        """

        _failing = failing_methods or set()

        @staticmethod
        def _maybe_fail(name: str) -> None:
            if name in _DirectNine000Client._failing:
                raise RuntimeError(f"injected_failure:{name}")
        def agent_create_job(self, *, merchant_id, job_id, template_key, materials):
            resp = c9.post(
                "/ai-edit/jobs/agent-create",
                headers={"X-Local-Agent-Token": token},
                json={"job_id": job_id, "template_key": template_key, "materials": materials},
            )
            assert resp.status_code in (200, 201), f"agent-create: {resp.status_code} {resp.text}"
            return resp.json()["data"]

        def agent_retry_job(self, *, merchant_id, job_id):
            resp = c9.post(
                f"/ai-edit/jobs/{job_id}/agent-retry",
                headers={"X-Local-Agent-Token": token}, json={},
            )
            assert resp.status_code in (200, 201), f"agent-retry: {resp.status_code} {resp.text}"
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

        def register_material(self, *, merchant_id, material_id, media_type,
                              source_sha256, agent_client_id=None):
            _DirectNine000Client._maybe_fail("register_material")
            resp = c9.post(
                "/ai-edit/materials",
                headers={"X-Local-Agent-Token": token},
                json={"material_id": material_id, "media_type": media_type,
                      "source_sha256": source_sha256,
                      "agent_client_id": agent_client_id or "local-agent"},
            )
            assert resp.status_code in (200, 201), f"register_material: {resp.status_code} {resp.text}"
            return resp.json()["data"]

        def delete_material(self, *, merchant_id, material_id):
            _DirectNine000Client._maybe_fail("delete_material")
            resp = c9.delete(
                f"/ai-edit/materials/agent/{material_id}",
                headers={"X-Local-Agent-Token": token},
            )
            assert resp.status_code in (200, 204), f"delete_material: {resp.status_code} {resp.text}"
            return resp.json().get("data", {}) if resp.status_code == 200 else {}

    nine000_client = _DirectNine000Client()

    def _executor(job):
        from apps.ai_edit.worker_main import load_manifest

        manifest = load_manifest(Path(job.manifest_path))
        result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
        return {"status": result.status, "failure_code": getattr(result, "failure_code", None)}

    def _on_terminal(job, status):
        # §5：用 agent-create 下发的令牌回写 9000 终态；成功后清除待回写标记
        if job.execution_token_hash:
            nine000_client.update_job_status(
                merchant_id=job.merchant_id, job_id=job.job_id,
                execution_token_hash=job.execution_token_hash,
                attempt_count=job.attempt_count, status=status,
                stage="completed" if status == "succeeded" else status,
                progress=100 if status == "succeeded" else None,
            )
            sup.clear_pending_writeback(merchant_id=job.merchant_id, job_id=job.job_id)

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
    """真实前端顺序：19000 导入(同步 9000 元数据) -> 19000 创建(经 9000 agent-create 领令牌)
    -> Worker(pipeline+9100替身) -> 19000 终态回写 9000 -> 9000 GET 状态 = succeeded。

    绿线条件：19000 on_job_terminal 用 agent-create 下发的令牌回写 9000 status；
    且 19000 导入同步 9000 元数据（9000 列表出现素材）。
    """
    sha = _synthetic_sha()
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    # 1. 19000 导入素材（内部调 9000 register_material 同步元数据；前端顺序唯一入口）
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)

    # 2. 9000 列表已出现该素材（导入同步 9000 元数据，工作台可选）
    mats = c9.get("/ai-edit/materials").json()["data"]["items"]
    assert any(m["material_id"] == "mat-1" and m["source_sha256"] == sha for m in mats), (
        "19000 导入未同步 9000 元数据，工作台无法选择素材"
    )

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
    """取消链路：19000 导入 -> 创建 -> cancel -> drain -> 9000 状态回写为 cancelled。"""
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

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
    """旧 attempt 回写被拒：9000 agent-retry 推进令牌后，19000 用旧令牌回写 -> 409 STALE_ATTEMPT_TOKEN。"""
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)

    # 9000 agent-retry：attempt 0→1，令牌轮换；旧令牌回写必须 409
    old_token, old_attempt = _job_token("job-1")
    retry_resp = c9.post("/ai-edit/jobs/job-1/agent-retry",
                         headers={"X-Local-Agent-Token": "tok-1"}, json={})
    assert retry_resp.status_code == 200
    resp = c9.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": old_token, "attempt_count": old_attempt,
              "status": "succeeded", "stage": "completed", "progress": 100},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STALE_ATTEMPT_TOKEN"


def test_e2e_retry_via_19000_requeues_with_new_token(tmp_path):
    """重试真实流程：19000 retry 调 9000 agent-retry 推进 attempt + 重新入队 + 用新令牌回写。"""
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)

    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)
    sup.drain()
    assert c9.get("/ai-edit/jobs/job-1").json()["data"]["status"] == "succeeded"

    # 重试：19000 调 9000 agent-retry（attempt 0→1，令牌轮换）+ 重新入队
    retry = c19.post("/agent/ai-edit/jobs/job-1/retry",
                     headers={"X-Local-Agent-Token": "tok-1"})
    assert retry.status_code == 200, retry.text
    assert retry.json()["data"]["attempt_count"] == 1
    # 重新入队后 drain，用新令牌回写 succeeded（attempt=1）
    sup.drain()
    detail = c9.get("/ai-edit/jobs/job-1").json()["data"]
    assert detail["status"] == "succeeded"
    assert detail["attempt_count"] == 1


def test_e2e_restart_recovers_writeback_token(tmp_path):
    """重启恢复：终态任务持久化了令牌，重启后 recover 恢复令牌（不丢失回写凭证）。"""
    from app.local_agent_ai_edit_supervisor import AiEditSupervisor

    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)
    sup.drain()

    # 模拟重启：新建 supervisor 复用同一 work_root（jobs.json 已持久化令牌）
    sup2 = AiEditSupervisor(
        work_root=sup.work_root, executor=lambda j: {"status": "succeeded"},
        on_job_terminal=lambda j, s: None,
    )
    state = sup2.get_job_state(merchant_id="m1", job_id="job-1")
    assert state is not None, "重启后应恢复任务状态"
    assert state["execution_token_hash"], "重启后应恢复执行令牌（FIX1-3）"
    assert state["attempt_count"] == 0


def test_e2e_writeback_failure_recover_compensates(tmp_path):
    """Must-Fix 4：终态回写失败（9000 不可用）→ 本地已终态 → 重启 recover 补偿重试回写。"""
    from app.local_agent_ai_edit_supervisor import AiEditSupervisor

    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)

    sup.drain()
    state = sup.get_job_state(merchant_id="m1", job_id="job-1")
    assert state["status"] == "succeeded"
    assert state["pending_writeback"] is False, "回写成功后应清除 pending（FIX1-4）"

    key = "m1/job-1"
    token = state["execution_token_hash"]
    attempt = state["attempt_count"]
    sup._persist_job_state(
        key, status="failed", attempt_id=state["attempt_id"],
        manifest_path=state["manifest_path"], merchant_id="m1", job_id="job-1",
        execution_token_hash=token, attempt_count=attempt,
        pending_writeback=True, writeback_attempts=0,
    )

    call_log: list[str] = []

    def _compensate(job, status):
        call_log.append(status)
        c9.post(
            "/ai-edit/jobs/job-1/status",
            headers={"X-Local-Agent-Token": "tok-1"},
            json={"execution_token_hash": job.execution_token_hash,
                  "attempt_count": job.attempt_count, "status": status},
        )

    sup2 = AiEditSupervisor(
        work_root=sup.work_root, executor=lambda j: {"status": "succeeded"},
        on_job_terminal=_compensate,
    )
    sup2.recover()
    assert call_log == ["failed"], f"recover 应补偿触发 on_job_terminal，实际 {call_log}"
    assert c9.get("/ai-edit/jobs/job-1").json()["data"]["status"] == "failed"


def test_e2e_cross_merchant_material_conflict(tmp_path):
    """FIX2-2：素材 ID 冲突不暴露归属——m2 用 m1 已占用的 material_id 注册 → 409，非幂等返回。"""
    sha = _synthetic_sha()
    c9 = _build_9000(tokens="m1:tok-1,m2:tok-2")
    # m1 注册素材
    assert c9.post(
        "/ai-edit/materials",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"material_id": "mat-1", "media_type": "video",
              "source_sha256": sha, "agent_client_id": "x"},
    ).status_code in (200, 201)

    # m2 用同 material_id（不同商户）注册 → 冲突，不暴露归属
    resp = c9.post(
        "/ai-edit/materials",
        headers={"X-Local-Agent-Token": "tok-2"},
        json={"material_id": "mat-1", "media_type": "video",
              "source_sha256": sha, "agent_client_id": "x"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MATERIAL_ID_CONFLICT"
    assert "m1" not in resp.text


def test_e2e_import_meta_sync_failure_returns_502(tmp_path):
    """FIX3-4：9000 同步失败明确 502（不静默吞），本地素材已写但 9000 列表不出现。"""
    c9 = _build_9000()
    # 注入 register_material 抛错
    c19, _ = _build_19000(tmp_path, c9, failing_methods={"register_material"})
    resp = _import_19000(c19, content=_SYNTHETIC_BYTES)
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["code"] == "MATERIAL_META_SYNC_FAILED"
    # 9000 列表不出现该素材（同步失败）
    mats = c9.get("/ai-edit/materials").json()["data"]["items"]
    assert all(m["material_id"] != "mat-1" for m in mats)
    # 重试导入（幂等本地文件 + 9000 同步成功）→ 200，素材出现
    c19_ok, _ = _build_19000(tmp_path, c9)
    assert _import_19000(c19_ok, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    mats2 = c9.get("/ai-edit/materials").json()["data"]["items"]
    assert any(m["material_id"] == "mat-1" for m in mats2)


def test_e2e_delete_idempotent_and_response_lost(tmp_path):
    """FIX3-4：9000 删除幂等 + 远端已执行但响应丢失时重试不分裂。

    19000 delete 同步 9000 成功；模拟响应丢失（第二次删除）→ 9000 幂等返回 200，
    本地不回滚（已软删），状态一致。
    """
    c9 = _build_9000()
    c19, _ = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    # 第一次删除：本地软删 + 9000 软删 → 200
    assert c19.delete("/agent/ai-edit/materials/mat-1",
                       headers={"X-Local-Agent-Token": "tok-1"}).status_code == 200
    # 9000 已软删（幂等：再次 agent 软删返回 200，不 404）
    again = c9.delete("/ai-edit/materials/agent/mat-1",
                      headers={"X-Local-Agent-Token": "tok-1"})
    assert again.status_code == 200, again.text


def test_e2e_delete_sync_failure_rolls_back_local(tmp_path):
    """FIX3-4：19000 delete 同步 9000 失败 → 回滚本地软删 + 502，状态不分裂。"""
    c9 = _build_9000()
    c19, _ = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    # 注入 delete_material 失败
    c19_fail, _ = _build_19000(tmp_path, c9, failing_methods={"delete_material"})
    # c19_fail 共享同一 storage_root（tmp_path 相同？不——_build_19000 每次新建 storage_root）
    # 用 c19_fail 的 storage：先在 c19_fail 导入再删
    assert _import_19000(c19_fail, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    resp = c19_fail.delete("/agent/ai-edit/materials/mat-1",
                           headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "MATERIAL_DELETE_SYNC_FAILED"
    # 本地已回滚：素材可再次列出（未软删）
    lst = c19_fail.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    items = lst.json()["data"]["items"]
    mat = next((i for i in items if i["material_id"] == "mat-1"), None)
    assert mat is not None and mat["deleted_at"] is None, "本地应回滚软删"


def test_e2e_cancel_requested_recovers_to_cancelled(tmp_path):
    """FIX2-4：cancel_requested 后进程退出 → 重启 recover 重新入队 → drain 归一 cancelled + 回写。"""
    from app.local_agent_ai_edit_supervisor import AiEditSupervisor

    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)
    # 取消（持久化为 cancel_requested，未 drain）
    assert c19.post("/agent/ai-edit/jobs/job-1/cancel",
                    headers={"X-Local-Agent-Token": "tok-1"}).status_code == 200
    state = sup.get_job_state(merchant_id="m1", job_id="job-1")
    assert state["status"] == "cancel_requested"

    # 重启：新 supervisor 复用 work_root + on_job_terminal 回写
    def _on_terminal(job, status):
        c9.post(
            "/ai-edit/jobs/job-1/status",
            headers={"X-Local-Agent-Token": "tok-1"},
            json={"execution_token_hash": job.execution_token_hash,
                  "attempt_count": job.attempt_count, "status": status},
        )

    sup2 = AiEditSupervisor(
        work_root=sup.work_root, executor=lambda j: {"status": "succeeded"},
        on_job_terminal=_on_terminal,
    )
    sup2.recover()
    sup2.drain()
    assert c9.get("/ai-edit/jobs/job-1").json()["data"]["status"] == "cancelled"


def test_e2e_retry_checks_can_retry_before_9000(tmp_path):
    """FIX2-5/FIX3-3：重试远端推进前先 claim_retry——运行中任务重试 → 409（不推进 9000）。"""
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)
    # 模拟运行中：直接持久化状态为 running
    key = "m1/job-1"
    state = sup.get_job_state(merchant_id="m1", job_id="job-1")
    sup._persist_job_state(
        key, status="running", attempt_id=state["attempt_id"],
        manifest_path=state["manifest_path"], merchant_id="m1", job_id="job-1",
        execution_token_hash=state["execution_token_hash"],
        attempt_count=state["attempt_count"],
    )
    # 重试运行中任务 → 409（claim_retry 拒，远端未推进）
    retry = c19.post("/agent/ai-edit/jobs/job-1/retry",
                     headers={"X-Local-Agent-Token": "tok-1"})
    assert retry.status_code == 409
    # 9000 attempt 未变（远端未推进）
    assert c9.get("/ai-edit/jobs/job-1").json()["data"]["attempt_count"] == 0


def test_e2e_browser_agent_token_issued_and_valid(tmp_path):
    """FIX2-1：9000 向已登录商户下发 Local Agent token，19000 验证通过。"""
    c9 = _build_9000()
    c19, _ = _build_19000(tmp_path, c9)
    token_resp = c9.get("/ai-edit/agent-token")
    assert token_resp.status_code == 200, token_resp.text
    token = token_resp.json()["data"]["token"]
    assert token == "tok-1"
    # 用该 token 调 19000（auth_required=true）→ 200
    lst = c19.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": token})
    assert lst.status_code == 200


def test_e2e_19000_rejects_request_without_token(tmp_path):
    """FIX2-1：19000 auth_required=true 时，无 token 请求 → 401（不关鉴权）。"""
    c9 = _build_9000()
    c19, _ = _build_19000(tmp_path, c9)
    lst = c19.get("/agent/ai-edit/materials")
    assert lst.status_code == 401


def test_e2e_agent_token_isolated_per_merchant(tmp_path):
    """FIX3-1：A 退出 B 登录不复用 A 的 token——9000 下发各商户独立 token，跨商户隔离。"""
    c9 = _build_9000(tokens="m1:tok-1,m2:tok-2")
    # m1 获取 token
    t1 = c9.get("/ai-edit/agent-token").json()["data"]["token"]
    assert t1 == "tok-1"
    # m2 用 m1 的 token 调 19000（若复用会误识别为 m1）→ 19000 验证 tok-1→m1，
    # 但 m2 请求带 tok-1 会被识别为 m1（token 映射固有）。正确性在于前端不为 m2 复用 tok-1：
    # 模拟 B 登录后前端调 agent-token 拿 tok-2（不同商户不同 token）
    # 这里验证 9000 对 m2 上下文下发 tok-2（通过 mock context 切换）
    c9_m2 = _build_9000(merchant_id="m2", token="tok-2", tokens="m1:tok-1,m2:tok-2")
    t2 = c9_m2.get("/ai-edit/agent-token").json()["data"]["token"]
    assert t2 == "tok-2"
    assert t1 != t2, "不同商户应下发不同 token"


def test_e2e_retry_concurrent_claim_prevents_double(tmp_path):
    """FIX3-3：并发重试只允许一次——第一个 claim_retry 置 retry_preparing，第二个 → 409。"""
    c9 = _build_9000()
    c19, sup = _build_19000(tmp_path, c9)
    assert _import_19000(c19, content=_SYNTHETIC_BYTES).status_code in (200, 201)
    assert c19.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    ).status_code in (200, 201)
    sup.drain()  # succeeded（终态可重试）
    # 第一个 claim 成功（置 retry_preparing），但人为停在 retry_preparing（不调 9000）
    snapshot = sup.claim_retry(merchant_id="m1", job_id="job-1")
    assert snapshot is not None
    # 第二个 claim → None（retry_preparing）
    assert sup.claim_retry(merchant_id="m1", job_id="job-1") is None
    # 路由层重试也 409
    retry = c19.post("/agent/ai-edit/jobs/job-1/retry",
                     headers={"X-Local-Agent-Token": "tok-1"})
    assert retry.status_code == 409
    # 回退后可再次 claim
    sup.revert_retry_claim(merchant_id="m1", job_id="job-1", snapshot=snapshot)
    assert sup.claim_retry(merchant_id="m1", job_id="job-1") is not None
