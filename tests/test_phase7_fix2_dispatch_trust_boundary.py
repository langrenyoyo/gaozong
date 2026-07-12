"""Phase 7-FIX2 派单信任边界测试（Task 1）。

验证：
- POST /wechat-tasks 全面停用（410）
- paste_only 任务不能伪造 sent
- 旧发送入口 410
- sync auto_notify 停用
"""
import os

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

# 在导入 app 之前设置环境变量（直接赋值，覆盖 .env 已有值）
os.environ["APP_ENV"] = "development"
os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "false"
os.environ["LOCAL_AGENT_TOKENS"] = "dev-merchant:local-agent-dev-token,merchant-a:token-a-xxx,merchant-b:token-b-yyy"
os.environ["NEWCAR_AUTH_ENABLED"] = "false"
os.environ["NEWCAR_AUTH_MOCK_ENABLED"] = "true"

from app.main import app  # 复用模块级已创建的 app 实例
from app.database import SessionLocal
from app.models import WechatTask, LeadNotification, DouyinLead, SalesStaff, ReplyCheck, CheckConfig


def _client() -> TestClient:
    """创建测试客户端，复用同一个 app 实例。"""
    return TestClient(app)


# ========== Step 1: 通用任务创建入口 410 ==========


def test_direct_wechat_task_create_is_disabled_for_single_send():
    """POST /wechat-tasks single_send 必须返回 410。"""
    client = _client()

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


def test_direct_wechat_task_create_is_disabled_for_paste_only():
    """POST /wechat-tasks paste_only 必须返回 410。"""
    client = _client()

    resp = client.post("/wechat-tasks", json={
        "task_type": "notify_sales",
        "target_nickname": "Aw3",
        "message": "test",
        "mode": "paste_only",
    })

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_wechat_task_create_is_disabled_for_detect_reply():
    """POST /wechat-tasks detect_reply 必须返回 410。"""
    client = _client()

    resp = client.post("/wechat-tasks", json={
        "task_type": "detect_reply",
        "lead_id": 1,
        "staff_id": 1,
        "mode": "read_only",
    })

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_wechat_task_create_never_writes_row():
    """POST /wechat-tasks 返回 410，不创建任务。"""
    client = _client()

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


def test_paste_only_task_cannot_be_marked_sent_by_result_payload():
    """paste_only 任务回写 sent=true 时必须 blocked，不得标记 sent。"""
    from app.services import wechat_task_service

    db = SessionLocal()
    try:
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

        # 恶意 Local Agent 回写 sent=true（直接测试 service 层）
        result = wechat_task_service.submit_wechat_task_result(
            db, task, success=True, verified=True,
            pasted=True, sent=True,
        )

        # paste_only 任务 sent=true 必须被 blocked
        assert result.status == "blocked"
        assert result.sent_at is None
        assert result.failure_stage == "task_mode_send_mismatch"
    finally:
        db.close()


# ========== Step 2: 旧发送入口停止 ==========


def test_legacy_send_pending_assigned_returns_410():
    """旧批量发送入口必须返回 410。"""
    client = _client()

    resp = client.post("/lead-notifications/send-pending-assigned")

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_pending_assigned_never_calls_ui_automation():
    """旧批量发送入口返回 410，不执行业务逻辑。"""
    client = _client()

    resp = client.post("/lead-notifications/send-pending-assigned")

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_only_one_send_to_staff_route_from_lead_notification_actions():
    """路由表中存在 send-to-staff（旧入口 410 + 新入口 lead_notification_actions）。"""
    routes = [
        r for r in app.routes
        if hasattr(r, "path") and r.path == "/lead-notifications/send-to-staff"
        and "POST" in (r.methods if r.methods else set())
    ]
    # Phase 7-FIX2：旧入口已删除，仅保留 lead_notification_actions 新主入口
    assert len(routes) == 1, f"send-to-staff 路由数={len(routes)}，预期 1 个（仅 lead_notification_actions 主入口）"


# ========== Step 3: sync auto_notify 停用 ==========


def test_sync_leads_rejects_legacy_auto_notify_true():
    """sync-leads 收到 auto_notify=true 必须返回 400。"""
    client = _client()

    resp = client.post("/integrations/douyin/sync-leads", json={
        "auto_notify": True,
        "dry_run": True,
        "auto_assign": False,
    })

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "LEGACY_AUTO_NOTIFY_DISABLED"


def test_preview_sync_leads_never_calls_auto_notify_assigned_lead():
    """sync-leads auto_notify=false 正常返回 200。"""
    client = _client()

    resp = client.post("/integrations/douyin/sync-leads", json={
        "auto_notify": False,
        "dry_run": True,
        "auto_assign": False,
    })

    assert resp.status_code == 200


def test_auto_create_wechat_task_stays_disabled():
    """auto_create_wechat_task=true 仍返回 disabled 统计，不创建任务。"""
    client = _client()

    db = SessionLocal()
    try:
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
