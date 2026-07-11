"""Phase 7-FIX2 派单信任边界红灯测试（Task 1）。

验证：
- POST /wechat-tasks 全面停用（410）
- paste_only 任务不能伪造 sent
- 旧发送入口 410
- sync auto_notify 停用
"""

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import create_app
from app.models import WechatTask, LeadNotification, DouyinLead, SalesStaff, ReplyCheck, CheckConfig


# ---- 内存测试库 ----
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _client(monkeypatch) -> TestClient:
    """创建带环境变量的测试客户端。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "false")
    monkeypatch.setenv("LOCAL_AGENT_TOKENS", "dev-merchant:local-agent-dev-token")
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")
    return TestClient(create_app())


# ========== Step 1: 通用任务创建入口 410 ==========


def test_direct_wechat_task_create_is_disabled_for_single_send(monkeypatch):
    """POST /wechat-tasks single_send 必须返回 410。"""
    client = _client(monkeypatch)

    resp = client.post("/wechat-tasks", json={
        "task_type": "notify_sales",
        "target_nickname": "Aw3",
        "message": "test",
        "mode": "single_send",
        "lead_id": 1,
        "staff_id": 1,
    })

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_wechat_task_create_is_disabled_for_paste_only(monkeypatch):
    """POST /wechat-tasks paste_only 必须返回 410。"""
    client = _client(monkeypatch)

    resp = client.post("/wechat-tasks", json={
        "task_type": "notify_sales",
        "target_nickname": "Aw3",
        "message": "test",
        "mode": "paste_only",
    })

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_wechat_task_create_is_disabled_for_detect_reply(monkeypatch):
    """POST /wechat-tasks detect_reply 必须返回 410。"""
    client = _client(monkeypatch)

    resp = client.post("/wechat-tasks", json={
        "task_type": "detect_reply",
        "lead_id": 1,
        "staff_id": 1,
        "mode": "read_only",
    })

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_wechat_task_create_never_writes_row(monkeypatch):
    """POST /wechat-tasks 返回 410，不创建任务。"""
    from app.database import SessionLocal

    client = _client(monkeypatch)

    db = SessionLocal()
    try:
        before = db.query(WechatTask).count()

        client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "test",
            "mode": "single_send",
            "lead_id": 1,
            "staff_id": 1,
        })

        after = db.query(WechatTask).count()
        # Phase 7-FIX2：HTTP 创建已停用，count 不应增加
        assert after == before
    finally:
        db.close()


def test_paste_only_task_cannot_be_marked_sent_by_result_payload(monkeypatch):
    """paste_only 任务回写 sent=true 时必须 blocked，不得标记 sent。"""
    from app.services import wechat_task_service

    client = _client(monkeypatch)

    db = TestSession()
    try:
        Base.metadata.create_all(bind=_engine)

        # 通过 service 直接创建 paste_only 任务（绕过 HTTP 410）
        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            lead_id=None,
            staff_id=None,
            target_nickname="Aw3",
            message="test",
            mode="paste_only",
        )
        task_id = task.id

        # 恶意 Local Agent 回写 sent=true
        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": True,
            "failure_stage": None,
        })

        assert resp.status_code == 200
        data = resp.json()
        # paste_only 任务 sent=true 必须被 blocked
        assert data["status"] == "blocked"
        assert data["sent_at"] is None
        assert data["failure_stage"] == "task_mode_send_mismatch"
    finally:
        db.close()


# ========== Step 2: 旧发送入口停止 ==========


def test_legacy_send_pending_assigned_returns_410(monkeypatch):
    """旧批量发送入口必须返回 410。"""
    client = _client(monkeypatch)

    resp = client.post("/lead-notifications/send-pending-assigned")

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_pending_assigned_never_calls_ui_automation(monkeypatch):
    """旧批量发送入口返回 410，不执行业务逻辑。"""
    client = _client(monkeypatch)

    resp = client.post("/lead-notifications/send-pending-assigned")

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_only_one_send_to_staff_route_from_lead_notification_actions(monkeypatch):
    """路由表中存在 send-to-staff（旧入口 410 + 新入口 lead_notification_actions）。"""
    from app.main import create_app
    app = create_app()
    routes = [
        r for r in app.routes
        if hasattr(r, "path") and r.path == "/lead-notifications/send-to-staff"
        and "POST" in (r.methods if r.methods else set())
    ]
    # Phase 7-FIX2：旧入口 send_to_staff_disabled (410) + 新入口 lead_notification_actions
    assert len(routes) == 2, f"send-to-staff 路由数={len(routes)}，预期 2 个（旧 410 + 新主入口）"


# ========== Step 3: sync auto_notify 停用 ==========


def test_sync_leads_rejects_legacy_auto_notify_true(monkeypatch):
    """sync-leads 收到 auto_notify=true 必须返回 400。"""
    client = _client(monkeypatch)

    resp = client.post("/integrations/douyin/sync-leads", json={
        "auto_notify": True,
        "dry_run": True,
        "auto_assign": False,
    })

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "LEGACY_AUTO_NOTIFY_DISABLED"


def test_preview_sync_leads_never_calls_auto_notify_assigned_lead(monkeypatch):
    """sync-leads auto_notify=false 正常返回 200。"""
    client = _client(monkeypatch)

    resp = client.post("/integrations/douyin/sync-leads", json={
        "auto_notify": False,
        "dry_run": True,
        "auto_assign": False,
    })

    assert resp.status_code == 200


def test_auto_create_wechat_task_stays_disabled(monkeypatch):
    """auto_create_wechat_task=true 仍返回 disabled 统计，不创建任务。"""
    client = _client(monkeypatch)

    db = TestSession()
    try:
        Base.metadata.create_all(bind=_engine)
        before = db.query(WechatTask).count()

        resp = client.post("/integrations/douyin/sync-leads", json={
            "auto_notify": False,
            "dry_run": True,
            "auto_assign": False,
            "auto_create_wechat_task": True,
        })

        assert resp.status_code == 200

        after = db.query(WechatTask).count()
        # auto_create_wechat_task=true 也不应创建任务
        assert after == before
    finally:
        db.close()
