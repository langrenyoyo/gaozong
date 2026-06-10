"""P0-2E 白屏排查 + 联系人二次确认测试

验证：
  1. activate_wechat_window 不在窗口已可见时执行 SW_RESTORE
  2. 白屏检测能正确判定大面积白色
  3. verify_contact_by_top_title 策略 A
  4. send_to_staff 在 contact_verified=false 时拒绝发送
  5. send_to_staff 在 contact_verified=true 时允许发送
  6. 不允许仅靠 input_box_found 就发送
"""

import pytest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock, PropertyMock

from app.services.automation_control import resume_automation, set_action_in_progress


@pytest.fixture(autouse=True)
def _reset_automation():
    resume_automation()
    set_action_in_progress(False)
    yield
    resume_automation()
    set_action_in_progress(False)


# ========== 测试 1：activate 不在窗口已可见时执行 SW_RESTORE ==========

class TestActivateNoRestoreWhenVisible:
    """已可见窗口不应调用 SW_RESTORE"""

    @patch("app.wechat_ui.window_locator.find_wechat_window")
    def test_skip_restore_when_visible(self, mock_find):
        from app.wechat_ui.window_locator import activate_wechat_window

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        with patch("app.wechat_ui.window_locator.ctypes") as mock_ctypes:
            # 模拟 IsIconic=False, IsWindowVisible=True
            mock_ctypes.windll.user32.IsIconic.return_value = 0
            mock_ctypes.windll.user32.IsWindowVisible.return_value = 1

            # mock GetWindowRect
            rect = MagicMock()
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 880, 700
            mock_ctypes.wintypes.RECT.return_value = rect
            mock_ctypes.byref.side_effect = lambda x: x

            # mock SystemParametersInfoW
            work = MagicMock()
            work.left, work.top, work.right, work.bottom = 0, 0, 1920, 1040
            mock_ctypes.wintypes.RECT.return_value = work

            # mock GetWindowTextW, GetClassNameW
            mock_ctypes.windll.user32.GetWindowTextW.return_value = None
            mock_ctypes.windll.user32.GetClassNameW.return_value = None
            mock_ctypes.windll.user32.GetForegroundWindow.return_value = 12345
            mock_ctypes.create_unicode_buffer.return_value = MagicMock(value="test")

            result = activate_wechat_window()

        assert result["success"] is True
        assert result["was_minimized"] is False
        assert result["was_visible"] is True
        assert "already_visible_skip_restore" in result["activate_steps"]
        # 不应包含 SW_RESTORE
        assert "SW_RESTORE" not in result["activate_steps"]


# ========== 测试 2：白屏检测 ==========

class TestWhiteScreenDetection:
    """白屏检测逻辑"""

    def test_white_image_detected(self):
        """大面积白色应检测为白屏"""
        import ctypes as real_ctypes
        from app.wechat_ui.window_locator import _check_white_screen

        # 创建全白图片 mock
        white_img = MagicMock()
        white_img.convert.return_value = white_img
        # 模拟 tobytes 返回全白像素（每像素 RGB 255,255,255）
        white_data = bytes([255, 255, 255] * 100)
        white_img.tobytes.return_value = white_data

        # P0-2G：前置可见性检查使用真实 ctypes，需要 mock user32 方法
        with patch.object(real_ctypes.windll.user32, "IsWindow", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsWindowVisible", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsIconic", return_value=0), \
             patch("app.wechat_ui.screenshot_debug.grab_screen", return_value=white_img):

            is_white, detail = _check_white_screen(12345)

        assert is_white is True
        assert "85%" in detail or "100%" in detail

    def test_normal_image_not_white(self):
        """正常颜色图片不应判定为白屏"""
        import ctypes as real_ctypes
        from app.wechat_ui.window_locator import _check_white_screen

        normal_img = MagicMock()
        normal_img.convert.return_value = normal_img
        # 模拟 tobytes 返回混合颜色（大部分非白色）
        normal_data = bytes([100, 50, 30] * 100)
        normal_img.tobytes.return_value = normal_data

        with patch.object(real_ctypes.windll.user32, "IsWindow", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsWindowVisible", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsIconic", return_value=0), \
             patch("app.wechat_ui.screenshot_debug.grab_screen", return_value=normal_img):

            is_white, detail = _check_white_screen(12345)

        assert is_white is False

    def test_screenshot_failure_not_treated_as_white(self):
        """截图失败不应判定为白屏"""
        import ctypes as real_ctypes
        from app.wechat_ui.window_locator import _check_white_screen

        with patch.object(real_ctypes.windll.user32, "IsWindow", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsWindowVisible", return_value=1), \
             patch.object(real_ctypes.windll.user32, "IsIconic", return_value=0), \
             patch("app.wechat_ui.screenshot_debug.grab_screen", side_effect=Exception("截图失败")):

            is_white, detail = _check_white_screen(12345)

        assert is_white is False


# ========== 测试 3：联系人确认策略 ==========

class TestVerifyContactByTopTitle:
    """策略 A：顶部标题确认"""

    def test_title_matches_returns_verified(self):
        """标题匹配 → verified=True"""
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        with patch("app.wechat_ui.contact_verifier.find_wechat_window"), \
             patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="Aw3"):
            result = verify_current_chat_contact("Aw3")

        assert result["verified"] is True
        assert result["strategy"] == "top_title"
        assert result["matched_text"] == "Aw3"
        assert result["manual_review_required"] is False

    def test_title_not_matches_continues_to_b(self):
        """标题不匹配 → 继续策略 B（无 win_rect 时直接失败）"""
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        with patch("app.wechat_ui.contact_verifier.find_wechat_window"), \
             patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="其他人"), \
             patch("app.wechat_ui.contact_verifier.save_debug_screenshot", return_value=None):
            result = verify_current_chat_contact("Aw3")

        assert result["verified"] is False
        assert result["manual_review_required"] is True
        assert result["failure_stage"] == "contact_not_verified"

    def test_no_title_continues_to_b(self):
        """无法读取标题 → 继续策略 B"""
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        with patch("app.wechat_ui.contact_verifier.find_wechat_window"), \
             patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value=None), \
             patch("app.wechat_ui.contact_verifier.save_debug_screenshot", return_value=None):
            result = verify_current_chat_contact("Aw3")

        assert result["verified"] is False

    def test_empty_nickname_returns_failure(self):
        """空昵称 → 直接失败"""
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        result = verify_current_chat_contact("")
        assert result["verified"] is False
        assert result["failure_stage"] == "empty_nickname"


# ========== 测试 4：send_to_staff 在 contact_verified=false 时拒绝发送 ==========

class TestSendRefusesWhenContactNotVerified:
    """contact_verified=false → 不粘贴、不发送"""

    @patch("app.routers.lead_notifications.write_text_to_input")
    @patch("app.routers.lead_notifications.find_wechat_window")
    @patch("app.routers.lead_notifications.open_chat_by_nickname")
    def test_does_not_send_when_contact_not_verified(
        self, mock_search, mock_win, mock_write,
    ):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models import DouyinLead, SalesStaff, LeadNotification
        from app.database import SessionLocal

        # open_chat 成功 + chat_verified
        mock_search.return_value = {
            "success": True, "chat_title": "其他人", "chat_verified": True,
            "confidence": 0.9, "message": "ok", "warning": None,
            "attempts": 1, "input_box_found": True, "message_list_found": True,
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
            "failure_stage": None, "debug_steps": [], "debug_screenshots": [],
        }
        # verify 失败
        mock_verify_result = {
            "verified": False, "expected_nickname": "Aw3",
            "matched_text": None, "strategy": None,
            "manual_review_required": True,
            "failure_stage": "contact_not_verified",
            "debug_screenshots": [], "warning": "无法确认",
            "message": "三种策略均未匹配",
        }
        mock_write.return_value = {"success": True, "pasted": True, "sent": True}

        client = TestClient(app)
        db = SessionLocal()
        try:
            db.query(LeadNotification).delete()
            staff = db.query(SalesStaff).filter(SalesStaff.name == "P02E测试").first()
            if not staff:
                staff = SalesStaff(name="P02E测试", wechat_nickname="Aw3")
                db.add(staff)
                db.commit()
                db.refresh(staff)
            lead = db.query(DouyinLead).filter(DouyinLead.customer_name == "P02E测试客户").first()
            if not lead:
                lead = DouyinLead(customer_name="P02E测试客户", source="test",
                                  status="assigned", assigned_staff_id=staff.id)
                db.add(lead)
                db.commit()
                db.refresh(lead)

            with patch("app.routers.lead_notifications.verify_current_chat_contact",
                       return_value=mock_verify_result):
                response = client.post("/lead-notifications/send-to-staff", json={
                    "lead_id": lead.id, "auto_send": True,
                })
            data = response.json()

            assert data["send_status"] == "failed", \
                f"contact_verified=False 时 send_status 应为 failed，实际: {data.get('send_status')}"
            # write_text_to_input 不应被调用
            mock_write.assert_not_called()
        finally:
            db.query(LeadNotification).filter(LeadNotification.lead_id == lead.id).delete()
            db.query(DouyinLead).filter(DouyinLead.id == lead.id).delete()
            db.query(SalesStaff).filter(SalesStaff.id == staff.id).delete()
            db.commit()
            db.close()


# ========== 测试 5：send_to_staff 在 contact_verified=true 时允许发送 ==========

class TestSendAllowsWhenContactVerified:
    """contact_verified=true → 正常发送"""

    @patch("app.routers.lead_notifications.write_text_to_input")
    @patch("app.routers.lead_notifications.find_wechat_window")
    @patch("app.routers.lead_notifications.open_chat_by_nickname")
    def test_sends_when_contact_verified(
        self, mock_search, mock_win, mock_write,
    ):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models import DouyinLead, SalesStaff, LeadNotification
        from app.database import SessionLocal

        mock_search.return_value = {
            "success": True, "chat_title": "Aw3", "chat_verified": True,
            "confidence": 0.9, "message": "ok", "warning": None,
            "attempts": 1, "input_box_found": True, "message_list_found": True,
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
            "failure_stage": None, "debug_steps": [], "debug_screenshots": [],
        }
        mock_verify_result = {
            "verified": True, "expected_nickname": "Aw3",
            "matched_text": "Aw3", "strategy": "top_title",
            "manual_review_required": False,
            "failure_stage": None, "debug_screenshots": [],
            "warning": None, "message": "策略A成功",
        }
        mock_win.return_value = MagicMock()
        mock_write.return_value = {"success": True, "pasted": True, "sent": True,
                                    "action": "pasted_and_sent", "attempts": 1}

        client = TestClient(app)
        db = SessionLocal()
        try:
            db.query(LeadNotification).delete()
            staff = db.query(SalesStaff).filter(SalesStaff.name == "P02E发送测试").first()
            if not staff:
                staff = SalesStaff(name="P02E发送测试", wechat_nickname="Aw3")
                db.add(staff)
                db.commit()
                db.refresh(staff)
            lead = db.query(DouyinLead).filter(DouyinLead.customer_name == "P02E发送客户").first()
            if not lead:
                lead = DouyinLead(customer_name="P02E发送客户", source="test",
                                  status="assigned", assigned_staff_id=staff.id)
                db.add(lead)
                db.commit()
                db.refresh(lead)

            with patch("app.routers.lead_notifications.verify_current_chat_contact",
                       return_value=mock_verify_result):
                response = client.post("/lead-notifications/send-to-staff", json={
                    "lead_id": lead.id, "auto_send": True,
                })
            data = response.json()

            assert data["send_status"] == "sent", \
                f"contact_verified=True 时 send_status 应为 sent，实际: {data.get('send_status')}"
            mock_write.assert_called_once()
        finally:
            db.query(LeadNotification).filter(LeadNotification.lead_id == lead.id).delete()
            db.query(DouyinLead).filter(DouyinLead.id == lead.id).delete()
            db.query(SalesStaff).filter(SalesStaff.id == staff.id).delete()
            db.commit()
            db.close()


# ========== 测试 6：不允许仅靠 input_box_found 就发送 ==========

class TestNoSendWithOnlyInputBox:
    """即使 open_chat 成功且 input_box_found，联系人未确认也不能发送"""

    def test_open_chat_success_but_contact_mismatch_blocks_send(self):
        """open_chat success + input_box_found + contact_mismatch → blocked"""
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        # 模拟 open_chat 成功（chat_title 不匹配），但联系人确认失败
        with patch("app.wechat_ui.contact_verifier.find_wechat_window"), \
             patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="张三"), \
             patch("app.wechat_ui.contact_verifier.save_debug_screenshot", return_value=None):
            result = verify_current_chat_contact("Aw3")

        # 即使 chat_title 能读到，但不匹配目标 → verified=False
        assert result["verified"] is False
        assert result["manual_review_required"] is True
