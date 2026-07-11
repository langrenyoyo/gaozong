"""P8-3 自动通知与批量发送测试

Phase 7-FIX2：旧自动通知链路已停用。
- sync auto_notify=true → 400 LEGACY_AUTO_NOTIFY_DISABLED
- send-pending-assigned → 410 LEGACY_WECHAT_SEND_DISABLED
- 旧 notification_service 函数保留独立测试（不依赖 sync 入口）
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ========== sync auto_notify 合同 ==========


class TestSyncAutoNotify:
    """sync-leads 接口 auto_notify 参数行为"""

    def test_sync_auto_notify_false(self):
        """auto_notify=false 正常同步。"""
        resp = client.post("/integrations/douyin/sync-leads", json={
            "auto_notify": False,
            "dry_run": True,
            "auto_assign": False,
        })
        assert resp.status_code == 200

    def test_sync_auto_notify_true_rejected(self):
        """auto_notify=true 返回 400 LEGACY_AUTO_NOTIFY_DISABLED。"""
        resp = client.post("/integrations/douyin/sync-leads", json={
            "auto_notify": True,
            "dry_run": True,
            "auto_assign": False,
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LEGACY_AUTO_NOTIFY_DISABLED"

    def test_sync_auto_notify_true_search_failed_rejected(self):
        """auto_notify=true 无论是否有线索都返回 400。"""
        resp = client.post("/integrations/douyin/sync-leads", json={
            "auto_notify": True,
            "dry_run": True,
            "auto_assign": True,
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LEGACY_AUTO_NOTIFY_DISABLED"


# ========== send-pending-assigned 合同 ==========


class TestSendPendingAssigned:
    """旧批量发送入口已停用"""

    def test_no_pending_leads(self):
        """无论是否有待发送线索，都返回 410。"""
        resp = client.post("/lead-notifications/send-pending-assigned")
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"

    def test_emergency_stop_blocks_batch(self):
        """紧急停止状态也返回 410。"""
        resp = client.post("/lead-notifications/send-pending-assigned")
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"

    def test_batch_sends_pending(self):
        """批量发送入口返回 410。"""
        resp = client.post("/lead-notifications/send-pending-assigned")
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"

    def test_batch_skips_already_sent(self):
        """批量发送入口返回 410。"""
        resp = client.post("/lead-notifications/send-pending-assigned")
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"
