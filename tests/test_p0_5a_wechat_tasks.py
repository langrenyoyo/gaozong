"""P0-5A-1 微信任务队列测试

覆盖 WechatTask 的创建、查询、结果回写。
不调用微信自动化，不依赖 Local Agent。
"""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app.main import create_app
from app.models import WechatTask

# 创建测试应用和数据库
app = create_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_db():
    """每个测试前重建所有表，测试后清理。"""
    Base.metadata.create_all(bind=engine)
    yield
    # 清理 wechat_tasks 表，不影响其他表
    db = SessionLocal()
    try:
        db.query(WechatTask).delete()
        db.commit()
    finally:
        db.close()


# ========== 创建任务 ==========

def test_create_wechat_task_success():
    """创建 Aw3 paste_only 任务应成功。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "[TEST] hello Aw3",
        "mode": "paste_only",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["target_nickname"] == "Aw3"
    assert data["mode"] == "paste_only"
    assert data["sent_at"] is None
    assert data["pasted_at"] is None


def test_create_wechat_task_rejects_non_aw3():
    """非 Aw3 昵称应被拒绝。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "啊东、",
        "message": "test",
        "mode": "paste_only",
    })
    assert resp.status_code == 400
    assert "Aw3" in resp.json()["detail"]


def test_create_wechat_task_rejects_non_paste_only():
    """非 paste_only 模式应被拒绝。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "test",
        "mode": "single_send",
    })
    assert resp.status_code == 400
    assert "paste_only" in resp.json()["detail"]


# ========== 查询任务 ==========

def test_get_pending_wechat_tasks():
    """查询 pending 任务列表。"""
    # 创建 2 个任务
    client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "task-a",
        "mode": "paste_only",
    })
    client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "task-b",
        "mode": "paste_only",
    })

    resp = client.get("/wechat-tasks/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # 按 id 升序
    assert data[0]["message"] == "task-a"
    assert data[1]["message"] == "task-b"


def test_get_wechat_task_detail():
    """查询任务详情。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "detail-test",
        "mode": "paste_only",
        "lead_id": 1,
        "staff_id": 2,
    })
    task_id = create_resp.json()["id"]

    resp = client.get(f"/wechat-tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["target_nickname"] == "Aw3"
    assert data["message"] == "detail-test"
    assert data["lead_id"] == 1
    assert data["staff_id"] == 2


# ========== 结果回写 ==========

def test_submit_result_pasted_success():
    """pasted=true + sent=false + verified=true → status=pasted。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "pasted-test",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
        "agent_hostname": "TEST-HOST",
        "agent_pid": 12345,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pasted"
    assert data["pasted_at"] is not None
    assert data["sent_at"] is None
    assert data["agent_hostname"] == "TEST-HOST"
    assert data["agent_pid"] == 12345
    assert data["failure_stage"] is None


def test_submit_result_rejects_sent_true():
    """sent=true 必须被拒绝。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "sent-reject",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "pasted": True,
        "sent": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["failure_stage"] == "sent_not_allowed_for_p0_5a"


def test_submit_result_blocks_verified_false():
    """verified=false → blocked。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "unverified",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": False,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": False,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "verified_false_blocked"


def test_submit_result_blocks_partial_match():
    """partial_match=true → blocked。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "partial",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": True,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "partial_match_blocked"


def test_submit_result_blocks_manual_review_required():
    """manual_review_required=true → blocked。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "manual",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": True,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "manual_review_required_blocked"


def test_submit_result_failed_requires_failure_stage_or_sets_unknown():
    """success=false 时 failure_stage 不能为空，为空则填 unknown_failure。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "fail-test",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    # 不提供 failure_stage
    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": False,
        "pasted": False,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["failure_stage"] == "unknown_failure"

    # 创建另一个任务，提供 failure_stage
    create_resp2 = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "fail-with-stage",
        "mode": "paste_only",
    })
    task_id2 = create_resp2.json()["id"]

    resp2 = client.post(f"/wechat-tasks/{task_id2}/result", json={
        "success": False,
        "failure_stage": "ocr_timeout",
        "pasted": False,
        "sent": False,
    })
    assert resp2.status_code == 200
    assert resp2.json()["failure_stage"] == "ocr_timeout"


def test_submit_result_saves_raw_result():
    """raw_result 必须保存。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "raw-test",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    raw = {"ocr_text": "AW3", "confidence": 0.95, "steps": ["focus", "ocr", "paste"]}
    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
        "raw_result": raw,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_result"] is not None
    import json
    saved = json.loads(data["raw_result"])
    assert saved["ocr_text"] == "AW3"
    assert saved["confidence"] == 0.95


def test_submit_result_keeps_sent_at_none():
    """pasted 成功后 sent_at 必须保持 None。"""
    create_resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "sent-at-none",
        "mode": "paste_only",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pasted"
    assert data["pasted_at"] is not None
    assert data["sent_at"] is None
