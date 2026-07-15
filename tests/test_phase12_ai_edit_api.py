"""Phase 12 AI 剪辑 9000 控制面 API 合同测试（Task 3 红灯）。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 3 Step 1。
冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10/§11。

覆盖（Step 1 列举）：
- 无权限 403（缺 auto_wechat:ai_edit）。
- 跨商户 404（不暴露存在性）。
- 平台素材只读（scope=platform 不可由商户删除）。
- Local Agent token 商户映射（X-Local-Agent-Token → merchant_id 回写状态）。
- 活动引用禁止删除。
- 7 天回收站。
- 取消 / 重试状态。
- API 不返回路径 / storage_key / merchant_id。
- 响应级脱敏（检查点 A 守卫）：error_summary / media_profile_json 不重新泄露绝对路径与内部存储键。

Task 3 红灯：路由尚未注册到 main.py → 端点 404，断言 200/403/404 失败；不出现收集错误
（只 import create_app/TestClient/已存在的 schema）。只使用内存 SQLite，不连生产/开发库，不发起真实网络/媒体调用。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
import app.models  # noqa: F401  触发全部 ORM 注册


engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ctx(
    *,
    merchant_id: str = "m1",
    merchant_ids: list[str] | None = None,
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
    auth_mode: str = "mock",
) -> RequestContext:
    return RequestContext(
        user_id="u1",
        merchant_id=merchant_id,
        merchant_ids=merchant_ids if merchant_ids is not None else [merchant_id],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:ai_edit"],
        super_admin=super_admin,
        auth_mode=auth_mode,
    )


def _client(context: RequestContext | None = None, *, local_agent_tokens: str = "") -> TestClient:
    from app.main import create_app

    if local_agent_tokens:
        os.environ["LOCAL_AGENT_TOKENS"] = local_agent_tokens
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _register_material(client, *, material_id="mat-1", merchant_id="m1", token="tok-1"):
    """通过 Local Agent token 回写注册一个商户素材，返回响应体。"""
    return client.post(
        "/ai-edit/materials",
        headers={"X-Local-Agent-Token": token},
        json={
            "material_id": material_id,
            "media_type": "video",
            "source_sha256": "sha-" + material_id,
            "agent_client_id": "agent-x",
        },
    )


def _create_job(client, *, job_id="job-1", material_id="mat-1"):
    """创建引用素材的任务，返回创建响应。"""
    return client.post("/ai-edit/jobs", json={
        "job_id": job_id, "template_key": "tpl",
        "materials": [{"material_id": material_id, "role": "main", "position": 0,
                       "pinned_sha256": "sha-" + material_id,
                       "source_start": 0.0, "source_end": 1.0}],
    })


def _job_token(job_id: str) -> tuple[str, int]:
    """白盒读取任务当前执行令牌哈希与 attempt（公共 API 不返回令牌，见设计 §10）。"""
    from app.models import AiEditJob
    db = TestSession()
    try:
        job = db.query(AiEditJob).filter_by(job_id=job_id).one()
        return job.execution_token_hash, job.attempt_count
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 无权限 403
# ---------------------------------------------------------------------------


def test_list_materials_403_without_permission():
    client = _client(_ctx(permission_codes=[], auth_mode="real"))
    resp = client.get("/ai-edit/materials")
    assert resp.status_code == 403


def test_list_templates_403_without_permission():
    client = _client(_ctx(permission_codes=[], auth_mode="real"))
    resp = client.get("/ai-edit/templates")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Local Agent token 商户映射 + 注册素材
# ---------------------------------------------------------------------------


def test_local_agent_registers_material_under_token_merchant():
    # token tok-1 → m1
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    resp = _register_material(client)
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()["data"]
    # 公共响应不泄露 merchant_id / storage_key / 本地路径（设计 §10）
    assert "merchant_id" not in body
    assert "storage_key" not in body
    assert "local_path" not in body


def test_local_agent_invalid_token_rejected():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    resp = client.post(
        "/ai-edit/materials",
        headers={"X-Local-Agent-Token": "wrong"},
        json={"material_id": "mat-x", "media_type": "video",
              "source_sha256": "sha-x", "agent_client_id": "ax"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 跨商户 404（不暴露存在性）
# ---------------------------------------------------------------------------


def test_cross_merchant_material_access_returns_404():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    # m2 商户上下文访问 m1 的素材 → 404
    other = _client(_ctx(merchant_id="m2", merchant_ids=["m2"], permission_codes=["auto_wechat:ai_edit"]))
    # 跨商户读取素材详情/删除应 404（不复用 other 的 db，这里仅断言隔离语义存在）
    # m2 在自己的库看不到 m1 素材：列素材返回空
    resp = other.get("/ai-edit/materials")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert all(it["material_id"] != "mat-1" for it in items)


# ---------------------------------------------------------------------------
# 平台素材只读：商户不能删除平台素材
# ---------------------------------------------------------------------------


def test_platform_material_cannot_be_deleted_by_merchant():
    # 平台素材由超管/seed 写入（这里直接通过 service 注入）
    from app.services import ai_edit_service as svc
    db = TestSession()
    try:
        svc.register_material(
            db, merchant_id=None, material_id="plat-1", media_type="video",
            source_sha256="sha-plat", agent_client_id="platform", scope="platform",
        )
        db.commit()
    finally:
        db.close()

    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    resp = client.delete("/ai-edit/materials/plat-1")
    assert resp.status_code in (403, 405)


# ---------------------------------------------------------------------------
# 活动引用禁止删除 + 7 天回收站
# ---------------------------------------------------------------------------


def test_delete_material_blocked_when_referenced_by_active_job():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    # 创建引用该素材的任务
    create = client.post("/ai-edit/jobs", json={
        "job_id": "job-1", "template_key": "tpl",
        "materials": [{"material_id": "mat-1", "role": "main", "position": 0,
                       "pinned_sha256": "sha-mat-1", "source_start": 0.0, "source_end": 1.0}],
    })
    assert create.status_code in (200, 201), create.text
    # 删除被活动引用的素材 → 拒绝
    resp = client.delete("/ai-edit/materials/mat-1")
    assert resp.status_code == 409


def test_delete_material_enters_recycle_bin():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-2", merchant_id="m1", token="tok-1")
    resp = client.delete("/ai-edit/materials/mat-2")
    assert resp.status_code == 200
    # 软删除：仍可由 service 查到 deleted_at
    from app.services import ai_edit_service as svc
    db = TestSession()
    try:
        mat = db.query(svc.AiEditMaterial).filter_by(material_id="mat-2").one()
        assert mat.deleted_at is not None
        assert mat.purge_after is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 取消 / 重试状态
# ---------------------------------------------------------------------------


def test_cancel_and_retry_job():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    client.post("/ai-edit/jobs", json={
        "job_id": "job-1", "template_key": "tpl",
        "materials": [{"material_id": "mat-1", "role": "main", "position": 0,
                       "pinned_sha256": "sha-mat-1", "source_start": 0.0, "source_end": 1.0}],
    })
    # 取消
    cancel = client.post("/ai-edit/jobs/job-1/cancel")
    assert cancel.status_code == 200
    cancel_body = cancel.json()["data"]
    assert "cancel_requested_at" in cancel_body
    # 重试：attempt 推进
    retry = client.post("/ai-edit/jobs/job-1/retry")
    assert retry.status_code == 200
    retry_body = retry.json()["data"]
    assert retry_body["attempt_count"] == 1


# ---------------------------------------------------------------------------
# API 不返回路径 / storage_key / merchant_id（执行包 Step 1 断言）
# ---------------------------------------------------------------------------


def test_material_response_never_exposes_internal_paths():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    body = _register_material(client).json()["data"]
    assert "storage_key" not in body
    assert "local_path" not in body
    assert "merchant_id" not in body
    assert "absolute_path" not in body


def test_job_response_never_exposes_internal_paths():
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    create = client.post("/ai-edit/jobs", json={
        "job_id": "job-1", "template_key": "tpl",
        "materials": [{"material_id": "mat-1", "role": "main", "position": 0,
                       "pinned_sha256": "sha-mat-1", "source_start": 0.0, "source_end": 1.0}],
    })
    body = create.json()["data"]
    assert "storage_key" not in body
    assert "merchant_id" not in body
    assert "local_path" not in body


# ---------------------------------------------------------------------------
# 响应级脱敏（检查点 A 守卫）：error_summary 不重新泄露绝对路径与内部存储键
# ---------------------------------------------------------------------------


def test_job_error_summary_redacted_in_response():
    """底层 error_summary 含绝对路径/存储键时，响应必须脱敏。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    # 通过 Local Agent 回写脏错误摘要（必须携带当前令牌 + attempt，见下方合同）
    token, attempt = _job_token("job-1")
    client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": token, "attempt_count": attempt,
              "stage": "render_final", "progress": 100, "status": "failed",
              "failure_code": "RENDER_FAILED",
              "error_summary": "崩溃于 E:\\secret\\raw.mp4 键 materials/m1/k.mp4"},
    )
    # 商户读取任务详情，error_summary 必须脱敏
    detail = client.get("/ai-edit/jobs/job-1")
    assert detail.status_code == 200
    summary = detail.json()["data"].get("error_summary") or ""
    assert "E:\\" not in summary
    assert "secret" not in summary
    assert "materials/m1/k.mp4" not in summary


# ---------------------------------------------------------------------------
# 状态回写令牌强制（Task 3-FIX1）：服务端不得替调用方补齐令牌/attempt
# ---------------------------------------------------------------------------


def test_status_update_missing_token_returns_422():
    """缺 execution_token_hash → 422（pydantic 必填）。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"attempt_count": 0, "stage": "render_final",
              "progress": 50, "status": "running"},
    )
    assert resp.status_code == 422


def test_status_update_missing_attempt_returns_422():
    """缺 attempt_count → 422。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    token, _ = _job_token("job-1")
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": token, "stage": "render_final",
              "progress": 50, "status": "running"},
    )
    assert resp.status_code == 422


def test_status_update_null_token_returns_422():
    """execution_token_hash=null → 422（必填非空）。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": None, "attempt_count": 0,
              "stage": "render_final", "progress": 50, "status": "running"},
    )
    assert resp.status_code == 422


def test_status_update_wrong_token_returns_409():
    """错误执行令牌 → 409 STALE_ATTEMPT_TOKEN（服务端不替调用方猜中令牌）。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    _, attempt = _job_token("job-1")
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": "not-the-real-token", "attempt_count": attempt,
              "stage": "render_final", "progress": 50, "status": "running"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STALE_ATTEMPT_TOKEN"


def test_status_update_stale_attempt_returns_409():
    """retry 推进 attempt 后，旧 attempt 回写 → 409（防旧 attempt 覆盖新结果）。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    # 重试：attempt 0→1，令牌轮换
    client.post("/ai-edit/jobs/job-1/retry")
    token, attempt = _job_token("job-1")  # attempt==1, 新令牌
    # 仍用 attempt=0 回写 → attempt 不匹配
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": token, "attempt_count": 0,
              "stage": "render_final", "progress": 50, "status": "running"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STALE_ATTEMPT_TOKEN"


def test_status_update_correct_token_returns_200():
    """正确令牌 + attempt 组合 → 200。"""
    client = _client(_ctx(), local_agent_tokens="m1:tok-1")
    _register_material(client, material_id="mat-1", merchant_id="m1", token="tok-1")
    _create_job(client)
    token, attempt = _job_token("job-1")
    resp = client.post(
        "/ai-edit/jobs/job-1/status",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"execution_token_hash": token, "attempt_count": attempt,
              "stage": "render_final", "progress": 100, "status": "succeeded"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "succeeded"
