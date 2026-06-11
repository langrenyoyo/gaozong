"""P8-3 自动通知测试

测试 auto_notify 在 sync 后触发、emergency_stopped 时被拦截、批量发送端点。

关键守卫验证：
  - auto_notify 调用前检查 automation_control
  - 发送前双重检查 automation_control
  - batch_notify_pending_assigned 在紧急停止时不执行
  - sync 的 auto_notify=false 时不触发通知
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db, SessionLocal
from app.models import DouyinLead, SalesStaff, ReplyCheck, LeadNotification, Base, CheckConfig
from app.services.automation_control import resume_automation, request_emergency_stop

client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_db():
    """每个测试前清空数据库并确保自动化恢复"""
    db = SessionLocal()
    try:
        # 清空所有表
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()

    # 确保自动化恢复
    resume_automation()

    yield

    # 测试结束后恢复自动化
    resume_automation()


def _create_staff(db, name="测试销售", wechat_nickname="测试微信昵称"):
    """创建销售"""
    staff = SalesStaff(
        name=name,
        wechat_nickname=wechat_nickname,
        status="active",
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def _create_assigned_lead(db, staff):
    """创建已分配线索"""
    lead = DouyinLead(
        source="douyin",
        source_id=f"test_{datetime.now().timestamp()}",
        customer_name="测试客户",
        content="测试内容",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _create_pending_check(db, lead, staff):
    """创建 pending 检测记录"""
    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


# ========== auto_notify_assigned_lead 单元测试 ==========

class TestAutoNotifyAssignedLead:
    """测试 notification_service.auto_notify_assigned_lead"""

    def test_lead_not_found(self):
        """线索不存在 → 返回失败"""
        from app.services.notification_service import auto_notify_assigned_lead
        db = SessionLocal()
        try:
            result = auto_notify_assigned_lead(db, lead_id=99999)
            assert result["success"] is False
            assert "不存在" in result["message"]
        finally:
            db.close()

    def test_lead_not_assigned(self):
        """线索未分配 → 返回失败"""
        from app.services.notification_service import auto_notify_assigned_lead
        db = SessionLocal()
        try:
            lead = DouyinLead(
                source="douyin",
                source_id="test_not_assigned",
                customer_name="未分配客户",
                status="pending",
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)

            result = auto_notify_assigned_lead(db, lead.id)
            assert result["success"] is False
            assert "不是 assigned" in result["message"]
        finally:
            db.close()

    def test_staff_no_wechat_nickname(self):
        """销售无微信昵称 → 返回失败并创建失败记录"""
        from app.services.notification_service import auto_notify_assigned_lead
        db = SessionLocal()
        try:
            staff = _create_staff(db, name="无昵称销售", wechat_nickname=None)
            lead = _create_assigned_lead(db, staff)

            result = auto_notify_assigned_lead(db, lead.id)
            assert result["success"] is False
            assert "未设置微信昵称" in result["message"]

            # 应有失败的通知记录
            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == lead.id
            ).first()
            assert notif is not None
            assert notif.send_status == "failed"
        finally:
            db.close()

    def test_emergency_stop_blocks_notify(self):
        """紧急停止时 → 返回 blocked"""
        from app.services.notification_service import auto_notify_assigned_lead
        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)

            request_emergency_stop("test")

            result = auto_notify_assigned_lead(db, lead.id)
            assert result["success"] is False
            assert result["send_status"] == "blocked"
        finally:
            db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_success_flow(self, mock_window, mock_write, mock_verify, mock_search):
        """正常流程 → 搜索+发送+记录+设置检测目标"""
        from app.services.notification_service import auto_notify_assigned_lead

        mock_search.return_value = {
            "success": True,
            "chat_title": "测试微信昵称",
            "chat_verified": True,
            "message": "已打开",
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        }
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        mock_write.return_value = {"success": True, "message": "已发送"}
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)
            check = _create_pending_check(db, lead, staff)

            result = auto_notify_assigned_lead(db, lead.id)

            assert result["success"] is True
            assert result["send_status"] == "sent"
            assert result["staff_name"] == "测试销售"
            assert result["notification_id"] is not None

            # 验证通知记录
            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == lead.id
            ).first()
            assert notif is not None
            assert notif.send_status == "sent"
            assert notif.send_mode == "auto_notify"
            assert notif.check_id == check.id

            # 验证自动检测目标已设置
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == "wechat_active_check_id"
            ).first()
            assert cfg is not None
            assert cfg.config_value == str(check.id)
        finally:
            db.close()


# ========== sync + auto_notify 集成测试 ==========

class TestSyncAutoNotify:
    """测试 sync_leads 与 auto_notify 的联动"""

    @patch("app.services.douyin_sync_service.fetch_leads")
    def test_sync_auto_notify_false(self, mock_fetch):
        """auto_notify=false → 不触发通知"""
        mock_fetch.return_value = {
            "total": 1,
            "items": [{
                "open_id": "sync_test_001",
                "display_name": "同步客户",
                "lead_status": "pending",
            }],
        }

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            db.close()

            response = client.post("/integrations/douyin/sync-leads", json={
                "dry_run": False,
                "auto_assign": True,
                "auto_notify": False,
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["notified"] == 0
        finally:
            if db:
                db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    @patch("app.services.douyin_sync_service.fetch_leads")
    def test_sync_auto_notify_true_success(self, mock_fetch, mock_window, mock_write, mock_verify, mock_search):
        """auto_notify=true + 搜索发送成功 → notified=1"""
        mock_fetch.return_value = {
            "total": 1,
            "items": [{
                "open_id": "sync_notify_001",
                "display_name": "通知客户",
                "last_interaction_record": "咨询产品",
                "lead_status": "pending",
            }],
        }
        mock_search.return_value = {"success": True, "chat_title": "测试微信昵称", "chat_verified": True, "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}}
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        mock_write.return_value = {"success": True, "message": "已发送"}
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            db.close()

            response = client.post("/integrations/douyin/sync-leads", json={
                "dry_run": False,
                "auto_assign": True,
                "auto_notify": True,
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["created"] == 1
            assert data["assigned"] == 1
            assert data["notified"] == 1
            assert "自动通知 1 条" in data["message"]
        finally:
            if db:
                db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.douyin_sync_service.fetch_leads")
    def test_sync_auto_notify_search_failed(self, mock_fetch, mock_search):
        """auto_notify=true + 搜索失败 → notified=0, assigned=1"""
        mock_fetch.return_value = {
            "total": 1,
            "items": [{
                "open_id": "sync_notify_fail_001",
                "display_name": "搜索失败客户",
                "lead_status": "pending",
            }],
        }
        mock_search.return_value = {"success": False, "message": "搜索超时"}

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            db.close()

            response = client.post("/integrations/douyin/sync-leads", json={
                "dry_run": False,
                "auto_assign": True,
                "auto_notify": True,
            })

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["assigned"] == 1
            assert data["notified"] == 0
            # "通知失败" 在 item 的 reason 字段中，不在顶层 message
            assert any("通知失败" in item["reason"] for item in data["items"])
        finally:
            if db:
                db.close()


# ========== send-pending-assigned 端点测试 ==========

class TestSendPendingAssigned:
    """测试 POST /lead-notifications/send-pending-assigned"""

    def test_no_pending_leads(self):
        """无待通知线索 → total=0, notified=0"""
        response = client.post("/lead-notifications/send-pending-assigned")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["notified"] == 0

    def test_emergency_stop_blocks_batch(self):
        """紧急停止 → 返回 blocked"""
        request_emergency_stop("test batch")

        response = client.post("/lead-notifications/send-pending-assigned")
        assert response.status_code == 200
        data = response.json()
        assert data["blocked"] == 1
        assert data["notified"] == 0

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_batch_sends_pending(self, mock_window, mock_write, mock_verify, mock_search):
        """有待通知线索 → 批量发送"""
        mock_search.return_value = {"success": True, "chat_title": "测试微信昵称", "chat_verified": True, "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}}
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        mock_write.return_value = {"success": True, "message": "已发送"}
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead1 = _create_assigned_lead(db, staff)
            lead2 = _create_assigned_lead(db, staff)
            _create_pending_check(db, lead1, staff)
            _create_pending_check(db, lead2, staff)
            db.close()

            response = client.post("/lead-notifications/send-pending-assigned")
            assert response.status_code == 200
            data = response.json()
            assert data["notified"] == 2
        finally:
            if db:
                db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_batch_skips_already_sent(self, mock_window, mock_write, mock_search):
        """已发送通知的线索 → 跳过"""
        mock_search.return_value = {"success": True, "chat_title": "测试微信昵称", "chat_verified": True}
        mock_write.return_value = {"success": True, "message": "已发送"}
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)

            # 已有一条成功发送的通知记录
            existing_notif = LeadNotification(
                lead_id=lead.id,
                staff_id=staff.id,
                notification_text="已发送",
                send_status="sent",
                send_mode="auto_notify",
                sent_at=datetime.now(),
            )
            db.add(existing_notif)
            db.commit()
            db.close()

            response = client.post("/lead-notifications/send-pending-assigned")
            assert response.status_code == 200
            data = response.json()
            assert data["notified"] == 0  # 已发送，不重复
        finally:
            if db:
                db.close()


# ========== P0-MAIN-2B: paste_only 状态语义修复测试 ==========

class TestPastedOnlyStatus:
    """验证 auto_send=False / require_confirm=True / action="pasted_only" 时 send_status="pasted" 而非 "sent"。"""

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_notification_service_paste_only_records_pasted(self, mock_window, mock_write, mock_verify, mock_search):
        """notification_service: auto_send=False + pasted_only → send_status="pasted", sent_at=None"""
        from app.services.notification_service import auto_notify_assigned_lead

        mock_search.return_value = {
            "success": True,
            "chat_title": "测试微信昵称",
            "chat_verified": True,
            "message": "已打开",
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        }
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        # 关键：action="pasted_only" 表示只粘贴未发送
        mock_write.return_value = {
            "success": True,
            "action": "pasted_only",
            "pasted": True,
            "sent": False,
            "message": "文本已粘贴到输入框（未发送，等待人工确认回车）",
        }
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)
            check = _create_pending_check(db, lead, staff)

            result = auto_notify_assigned_lead(db, lead.id, auto_send=False)

            # result 应为 pasted，非 sent
            assert result["send_status"] == "pasted"
            assert result["success"] is False  # paste_only 不算最终成功

            # 通知记录应记录为 pasted
            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == lead.id
            ).first()
            assert notif is not None
            assert notif.send_status == "pasted"
            assert notif.sent_at is None

            # 自动检测目标不应设置（消息未真正发送）
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == "wechat_active_check_id"
            ).first()
            assert cfg is None or cfg.config_value != str(check.id)
        finally:
            db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_notification_service_auto_send_true_records_sent(self, mock_window, mock_write, mock_verify, mock_search):
        """notification_service: auto_send=True + sent → send_status="sent"（不受修复影响）"""
        from app.services.notification_service import auto_notify_assigned_lead

        mock_search.return_value = {
            "success": True,
            "chat_title": "测试微信昵称",
            "chat_verified": True,
            "message": "已打开",
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        }
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        # auto_send=True → action="pasted_and_sent"
        mock_write.return_value = {
            "success": True,
            "action": "pasted_and_sent",
            "pasted": True,
            "sent": True,
            "message": "文本已粘贴并自动发送",
        }
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)
            check = _create_pending_check(db, lead, staff)

            result = auto_notify_assigned_lead(db, lead.id, auto_send=True)

            assert result["send_status"] == "sent"
            assert result["success"] is True

            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == lead.id
            ).first()
            assert notif is not None
            assert notif.send_status == "sent"
            assert notif.sent_at is not None
        finally:
            db.close()

    @patch("app.routers.lead_notifications.open_chat_by_nickname")
    @patch("app.routers.lead_notifications.verify_current_chat_contact")
    @patch("app.routers.lead_notifications.write_text_to_input")
    @patch("app.routers.lead_notifications.find_wechat_window")
    def test_lead_notifications_route_paste_only_records_pasted(self, mock_window, mock_write, mock_verify, mock_search):
        """POST /lead-notifications/send-to-staff { auto_send: false } + pasted_only → send_status="pasted" """
        mock_search.return_value = {
            "success": True,
            "chat_title": "测试微信昵称",
            "chat_verified": True,
            "message": "已打开",
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        }
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        mock_write.return_value = {
            "success": True,
            "action": "pasted_only",
            "pasted": True,
            "sent": False,
            "message": "文本已粘贴到输入框（未发送，等待人工确认回车）",
        }
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)
            _create_pending_check(db, lead, staff)
            lead_id = lead.id
            db.close()

            response = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead_id,
                "auto_send": False,
            })

            assert response.status_code == 200
            data = response.json()
            assert data["send_status"] == "pasted"
            assert data["success"] is False

            # 用新 session 验证通知记录
            db2 = SessionLocal()
            try:
                notif = db2.query(LeadNotification).filter(
                    LeadNotification.lead_id == lead.id
                ).first()
                assert notif is not None
                assert notif.send_status == "pasted"
                assert notif.sent_at is None
                assert notif.send_mode == "require_confirm"
            finally:
                db2.close()
        finally:
            if db:
                db.close()

    @patch("app.services.notification_service.open_chat_by_nickname")
    @patch("app.services.notification_service.verify_current_chat_contact")
    @patch("app.services.notification_service.write_text_to_input")
    @patch("app.services.notification_service.find_wechat_window")
    def test_notification_service_failed_stays_failed(self, mock_window, mock_write, mock_verify, mock_search):
        """write_result["success"]=False → send_status 保持 "failed"（不受修复影响）"""
        from app.services.notification_service import auto_notify_assigned_lead

        mock_search.return_value = {
            "success": True,
            "chat_title": "测试微信昵称",
            "chat_verified": True,
            "message": "已打开",
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        }
        mock_verify.return_value = {
            "verified": True, "expected_nickname": "测试微信昵称",
            "matched_text": "测试微信昵称", "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }
        mock_write.return_value = {
            "success": False,
            "action": None,
            "pasted": False,
            "sent": False,
            "message": "写入微信输入框失败: 输入框未找到",
        }
        mock_window.return_value = MagicMock()

        db = SessionLocal()
        try:
            staff = _create_staff(db)
            lead = _create_assigned_lead(db, staff)

            result = auto_notify_assigned_lead(db, lead.id, auto_send=False)

            assert result["send_status"] == "failed"
            assert result["success"] is False

            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == lead.id
            ).first()
            assert notif is not None
            assert notif.send_status == "failed"
        finally:
            db.close()
