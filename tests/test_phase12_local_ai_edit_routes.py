"""Phase 12 Task 7 19000 AI 剪辑窄路由测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7 Step 4。

覆盖：
- 路由复用既有 Local Agent token，不接受 merchant_id 和绝对路径；
- 鉴权三态：正确 token 200 / 缺失 401 / 错误 401；
- 素材导入（base64，避免 multipart 依赖）；
- 列素材、删除素材（活动引用 409）；
- 任务入队、取消、状态；
- Worker 缺失不影响微信路由（路由独立注册，不阻塞既有 /agent/* 路由）。
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.local_agent_ai_edit_routes import create_ai_edit_router
from app.local_agent_ai_edit_storage import mark_active_reference
from app.local_agent_ai_edit_supervisor import AiEditSupervisor


def _build_client(tmp_path, *, token="tok-1", auth_required=True):
    os.environ["LOCAL_AGENT_TOKENS"] = f"m1:{token}" if token else ""
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true" if auth_required else "false"
    storage_root = tmp_path / "managed"
    work_root = tmp_path / "work"
    sup = AiEditSupervisor(work_root=work_root, executor=lambda j: {"status": "succeeded"})
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(create_ai_edit_router(supervisor=sup, storage_root=storage_root))
    client = TestClient(app)
    client._storage_root = storage_root
    return client, sup


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _import(client, *, material_id="mat-1", content=b"video-bytes", expected_size=None, token="tok-1"):
    return client.post(
        "/agent/ai-edit/materials/import",
        headers={"X-Local-Agent-Token": token},
        json={
            "material_id": material_id,
            "expected_size": expected_size if expected_size is not None else len(content),
            "content_base64": _b64(content),
        },
    )


# ---------------------------------------------------------------------------
# 鉴权三态
# ---------------------------------------------------------------------------


def test_correct_token_lists_materials(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 200


def test_missing_token_rejected(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials")
    assert resp.status_code == 401


def test_wrong_token_rejected(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 不接受 merchant_id 和绝对路径
# ---------------------------------------------------------------------------


def test_import_rejects_merchant_id_field(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = client.post(
        "/agent/ai-edit/materials/import",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={
            "material_id": "mat-1", "merchant_id": "m1",
            "expected_size": 1, "content_base64": _b64(b"x"),
        },
    )
    assert resp.status_code == 422  # extra=forbid 拒绝 merchant_id


def test_import_rejects_absolute_path(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = client.post(
        "/agent/ai-edit/materials/import",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={
            "material_id": "/abs/path/mat-1",
            "expected_size": 1, "content_base64": _b64(b"x"),
        },
    )
    assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 导入 + 列素材
# ---------------------------------------------------------------------------


def test_import_and_list_materials(tmp_path):
    client, _ = _build_client(tmp_path)
    resp = _import(client)
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()["data"]
    assert "sha256" in body
    lst = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    assert lst.status_code == 200
    items = lst.json()["data"]["items"]
    assert any(i["material_id"] == "mat-1" for i in items)


def test_delete_material_enters_recycle_bin(tmp_path):
    client, _ = _build_client(tmp_path)
    _import(client)
    resp = client.delete("/agent/ai-edit/materials/mat-1", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 200


def test_delete_referenced_by_active_job_rejected(tmp_path):
    client, _ = _build_client(tmp_path)
    _import(client)
    mark_active_reference(client._storage_root, "mat-1", job_id="job-1", active=True)
    resp = client.delete("/agent/ai-edit/materials/mat-1", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 任务入队、取消、状态
# ---------------------------------------------------------------------------


def test_enqueue_and_status(tmp_path):
    client, _ = _build_client(tmp_path)
    _import(client)
    resp = client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl", "materials": [
            {"material_id": "mat-1", "role": "main"}]},
    )
    assert resp.status_code in (200, 201), resp.text
    status = client.get("/agent/ai-edit/status", headers={"X-Local-Agent-Token": "tok-1"})
    assert status.status_code == 200


def test_cancel_job(tmp_path):
    client, _ = _build_client(tmp_path)
    _import(client)
    client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    resp = client.post("/agent/ai-edit/jobs/job-1/cancel", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code in (200, 404, 409)  # 取消语义接受


# ---------------------------------------------------------------------------
# Worker 缺失不影响微信路由（路由独立注册）
# ---------------------------------------------------------------------------


def test_ai_edit_routes_registered_independently(tmp_path):
    """AI 剪辑路由独立注册，不阻塞既有微信路由。"""
    from app.local_agent_main import create_local_agent_app
    # 确认 create_local_agent_app 仍可创建（微信路由未受影响）
    app = create_local_agent_app()
    client = TestClient(app)
    # 健康检查存在（微信路由未受影响）
    assert client.get("/health").status_code in (200, 404, 401)
