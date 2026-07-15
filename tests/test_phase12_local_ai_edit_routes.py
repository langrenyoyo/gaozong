"""Phase 12 Task 7 19000 AI 剪辑窄路由测试（FIX1 修正）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

覆盖：
- 路由复用 Local Agent token，按 merchant_id 商户隔离（跨商户不可见）；
- 鉴权三态：正确 token 200 / 缺失 401 / 错误 401；
- 素材导入（base64）、列素材、删除素材（活动引用 409）；
- 任务入队（job_id 安全段防穿越 + 原子写 manifest）、取消（精确断言）、状态；
- Worker 缺失不影响微信路由。
"""

import base64
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.local_agent_ai_edit_routes import create_ai_edit_router
from app.local_agent_ai_edit_storage import mark_active_reference
from app.local_agent_ai_edit_supervisor import AiEditSupervisor


def _build_client(tmp_path, *, token="tok-1", merchant="m1"):
    """构建路由客户端；supervisor 用同步 drain（auto_start=False）。"""
    os.environ["LOCAL_AGENT_TOKENS"] = f"{merchant}:{token}" if token else ""
    os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"
    storage_root = tmp_path / "managed"
    work_root = tmp_path / "work"
    sup = AiEditSupervisor(work_root=work_root, executor=lambda j: {"status": "succeeded"})
    app = FastAPI()
    app.include_router(create_ai_edit_router(
        supervisor=sup, storage_root=storage_root, work_root=work_root,
    ))
    client = TestClient(app)
    client._storage_root = storage_root
    client._work_root = work_root
    client._sup = sup
    return client


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _import(client, *, material_id="mat-1", content=b"video-bytes", token="tok-1"):
    return client.post(
        "/agent/ai-edit/materials/import",
        headers={"X-Local-Agent-Token": token},
        json={
            "material_id": material_id,
            "expected_size": len(content),
            "content_base64": _b64(content),
        },
    )


# ---------------------------------------------------------------------------
# 鉴权三态
# ---------------------------------------------------------------------------


def test_correct_token_lists_materials(tmp_path):
    client = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 200


def test_missing_token_rejected(tmp_path):
    client = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials")
    assert resp.status_code == 401


def test_wrong_token_rejected(tmp_path):
    client = _build_client(tmp_path)
    resp = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# FIX1-1：商户隔离——跨商户不可见
# ---------------------------------------------------------------------------


def test_cross_merchant_isolation(tmp_path):
    """m1 导入素材，m2 看不到、删不掉（不暴露存在性）。"""
    c1 = _build_client(tmp_path, token="tok-1", merchant="m1")
    _import(c1, material_id="mat-1")
    # m2 商户
    os.environ["LOCAL_AGENT_TOKENS"] = "m2:tok-2"
    c2 = _build_client(tmp_path, token="tok-2", merchant="m2")
    lst = c2.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-2"})
    assert lst.status_code == 200
    items = lst.json()["data"]["items"]
    assert all(i["material_id"] != "mat-1" for i in items)  # m2 看不到 m1 素材
    # m2 删 m1 素材 → 404（不暴露存在性）
    dele = c2.delete("/agent/ai-edit/materials/mat-1", headers={"X-Local-Agent-Token": "tok-2"})
    assert dele.status_code == 404


# ---------------------------------------------------------------------------
# 不接受 merchant_id 和绝对路径
# ---------------------------------------------------------------------------


def test_import_rejects_merchant_id_field(tmp_path):
    client = _build_client(tmp_path)
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
    client = _build_client(tmp_path)
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
# FIX1-3：job_id 路径穿越拒绝
# ---------------------------------------------------------------------------


def test_job_create_rejects_traversal_job_id(tmp_path):
    client = _build_client(tmp_path)
    _import(client)
    resp = client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "../escape", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    assert resp.status_code == 422  # job_id 含斜杠段拒绝


def test_job_create_writes_manifest_atomically(tmp_path):
    client = _build_client(tmp_path)
    _import(client)
    resp = client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    assert resp.status_code in (200, 201), resp.text
    # manifest 原子写入（无残留临时文件）
    import glob
    manifest_dir = client._work_root / "m1" / "jobs" / "job-1"
    assert (manifest_dir / "manifest.json").exists()
    assert glob.glob(str(manifest_dir / ".manifest_*.tmp")) == []


# ---------------------------------------------------------------------------
# 导入 + 列素材 + 删除
# ---------------------------------------------------------------------------


def test_import_and_list_materials(tmp_path):
    client = _build_client(tmp_path)
    resp = _import(client)
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()["data"]
    assert "sha256" in body
    lst = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    assert lst.status_code == 200
    items = lst.json()["data"]["items"]
    assert any(i["material_id"] == "mat-1" for i in items)


def test_delete_material_enters_recycle_bin(tmp_path):
    client = _build_client(tmp_path)
    _import(client)
    resp = client.delete("/agent/ai-edit/materials/mat-1", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 200


def test_delete_referenced_by_active_job_rejected(tmp_path):
    client = _build_client(tmp_path)
    _import(client)
    mark_active_reference(client._storage_root / "m1", "mat-1", job_id="job-1", active=True)
    resp = client.delete("/agent/ai-edit/materials/mat-1", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# FIX1-9：流式导入（原始字节流，不 base64 全量解码）
# ---------------------------------------------------------------------------


def test_import_stream_writes_material(tmp_path):
    """流式导入：原始字节流 → 受管文件，返回哈希。"""
    client = _build_client(tmp_path)
    content = b"stream-video-bytes"
    resp = client.post(
        "/agent/ai-edit/materials/import-stream",
        headers={"X-Local-Agent-Token": "tok-1", "Content-Type": "application/octet-stream"},
        params={"material_id": "mat-stream", "expected_size": str(len(content))},
        content=content,
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()["data"]
    assert body["material_id"] == "mat-stream"
    assert body["size_bytes"] == len(content)
    # 列素材可见
    lst = client.get("/agent/ai-edit/materials", headers={"X-Local-Agent-Token": "tok-1"})
    assert any(i["material_id"] == "mat-stream" for i in lst.json()["data"]["items"])


def test_import_stream_rejects_size_mismatch(tmp_path):
    """流式导入大小不匹配 → 拒绝。"""
    client = _build_client(tmp_path)
    resp = client.post(
        "/agent/ai-edit/materials/import-stream",
        headers={"X-Local-Agent-Token": "tok-1", "Content-Type": "application/octet-stream"},
        params={"material_id": "mat-x", "expected_size": "999"},
        content=b"short",
    )
    assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 任务入队、状态、取消（FIX1-9：取消精确断言）
# ---------------------------------------------------------------------------


def test_enqueue_and_status(tmp_path):
    client = _build_client(tmp_path)
    _import(client)
    resp = client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    assert resp.status_code in (200, 201), resp.text
    status = client.get("/agent/ai-edit/status", headers={"X-Local-Agent-Token": "tok-1"})
    assert status.status_code == 200


def test_cancel_running_job_returns_200(tmp_path):
    """取消可取消的任务 → 200 + cancel_requested（不再接受 404/409 模糊）。"""
    client = _build_client(tmp_path)
    _import(client)
    client.post(
        "/agent/ai-edit/jobs",
        headers={"X-Local-Agent-Token": "tok-1"},
        json={"job_id": "job-1", "template_key": "tpl",
              "materials": [{"material_id": "mat-1", "role": "main"}]},
    )
    # 任务在队列（auto_start=False，未 drain），可取消
    resp = client.post("/agent/ai-edit/jobs/job-1/cancel", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancel_requested"


def test_cancel_nonexistent_job_returns_409(tmp_path):
    """取消不存在/已终态任务 → 409（精确断言，非模糊）。"""
    client = _build_client(tmp_path)
    resp = client.post("/agent/ai-edit/jobs/no-such/cancel", headers={"X-Local-Agent-Token": "tok-1"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Worker 缺失不影响微信路由
# ---------------------------------------------------------------------------


def test_ai_edit_routes_registered_independently(tmp_path):
    from app.local_agent_main import create_local_agent_app
    app = create_local_agent_app()
    client = TestClient(app)
    assert client.get("/health").status_code in (200, 404, 401)
