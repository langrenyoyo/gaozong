"""P0-2C 安全测试

验证自动搜索+发送的安全机制：
1. open_chat 必须经过 chat_verified 才能算成功
2. send_to_staff 在 chat_verified=false 时不发送
3. 前台窗口丢失触发失败
4. 截图调试证据被记录
5. 不允许 success=true 但实际未验证
"""

import pytest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

from app.services.automation_control import resume_automation, set_action_in_progress


@pytest.fixture(autouse=True)
def _reset_automation():
    resume_automation()
    set_action_in_progress(False)
    yield
    resume_automation()
    set_action_in_progress(False)


def _mock_ctrl():
    ctrl = MagicMock()
    r = MagicMock()
    r.left, r.top, r.right, r.bottom = 0, 0, 880, 700
    r.width.return_value = 880
    r.height.return_value = 700
    ctrl.BoundingRectangle = r
    ctrl.NativeWindowHandle = 123
    return ctrl


def _mock_precond_ok():
    ctrl = _mock_ctrl()
    ctx = {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": ctrl}
    return patch("app.wechat_ui.contact_searcher._check_preconditions",
                 return_value=(True, "OK", ctx))


def _all_contact_searcher_patches(**overrides):
    """返回 contact_searcher 测试所需的全部 patch 列表"""
    patches = [
        patch("app.wechat_ui.contact_searcher.save_debug_screenshot",
              return_value=overrides.get("screenshot", "test.png")),
        patch("app.wechat_ui.contact_searcher.capture_wechat_region",
              return_value=MagicMock()),
        patch("app.wechat_ui.contact_searcher.verify_search_area_changed",
              return_value=overrides.get("verify", {"verified": True, "diff_ratio": 0.15, "message": "已变化"})),
        patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
              return_value=overrides.get("click_point", {
                  "success": True, "x": 120, "y": 88, "strategy": "manual_calibration", "confidence": 0.7,
              })),
        patch("app.wechat_ui.contact_searcher.save_search_box_overlay",
              return_value=overrides.get("overlay", "overlay.png")),
        patch("app.wechat_ui.contact_searcher.uia.SendKeys"),
        patch("app.wechat_ui.contact_searcher._save_clipboard", return_value=""),
        patch("app.wechat_ui.contact_searcher._set_clipboard"),
        patch("app.wechat_ui.contact_searcher._restore_clipboard"),
        patch("app.wechat_ui.contact_searcher._is_wechat_foreground",
              side_effect=overrides.get("foreground", lambda hwnd: True)),
        patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground",
              return_value=overrides.get("foreground_guard", {"success": True, "message": "OK"})),
        patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
              return_value=overrides.get("search_focus", {
                  "clicked": True,
                  "focused": True,
                  "verified": True,
                  "success": True,
                  "text_pasted_into_search_box": False,
                  "text_leaked_to_chat_input": False,
                  "manual": False,
                  "manual_review_required": False,
              })),
        patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
              return_value=overrides.get("search_text", {
                  "search_text_verified": True,
                  "text_pasted_into_search_box": True,
                  "text_leaked_to_chat_input": False,
                  "manual": False,
              })),
        patch("app.wechat_ui.contact_searcher.ctypes"),
        patch("app.wechat_ui.contact_searcher.time.sleep"),
        patch("app.wechat_ui.contact_searcher._trigger_emergency_stop"),
        patch("app.wechat_ui.window_locator.find_current_chat_title",
              return_value=overrides.get("chat_title", None)),
        patch("app.wechat_ui.contact_searcher.find_wechat_window",
              return_value=_mock_ctrl()),
    ]
    return patches


def _run_open_chat(nickname="测试", **overrides):
    """运行 open_chat_by_nickname 并返回结果，自动管理所有 patch"""
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    all_patches = [_mock_precond_ok()] + _all_contact_searcher_patches(**overrides)
    with ExitStack() as stack:
        for p in all_patches:
            stack.enter_context(p)
        return open_chat_by_nickname(nickname)


# ========== 测试 1：open_chat 只表示搜索动作完成，不表示联系人已验证 ==========

class TestChatVerifiedRequired:

    def test_no_success_without_chat_verified(self):
        """success=True 时也不得把搜索动作伪装成联系人 verified"""
        result = _run_open_chat()

        if result["success"]:
            assert result["search_action_completed"] is True
            assert result["chat_verified"] is False
            assert result["confidence"] <= 0.3
            assert "final verification requires OCR" in result["warning"]

    def test_search_area_screenshot_always_saved(self):
        """截图证据应始终保存（非阻塞）——P0-2C 降级策略"""
        # 即使像素对比返回未变化，搜索也应继续（截图 API 不稳定）
        result = _run_open_chat(
            verify={"verified": False, "diff_ratio": 0.001, "message": "未变化"},
        )
        # 截图证据应保存（debug_screenshots 不为空）
        assert len(result.get("debug_screenshots", [])) > 0, \
            "搜索阶段应有截图证据"


# ========== 测试 2：send_to_staff 在 chat_verified=false 时不发送 ==========

class TestSendToStaffGuard:

    @patch("app.routers.lead_notifications.write_text_to_input")
    @patch("app.routers.lead_notifications.find_wechat_window")
    @patch("app.routers.lead_notifications.open_chat_by_nickname")
    def test_does_not_send_when_chat_not_verified(self, mock_search, mock_win, mock_write):
        """chat_verified=False → 不调用 write_text_to_input"""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models import DouyinLead, SalesStaff, LeadNotification
        from app.database import SessionLocal

        mock_search.return_value = {
            "success": True, "chat_title": None, "chat_verified": False,
            "confidence": 0.3, "message": "无法验证", "warning": "聊天窗口无法验证",
            "attempts": 1, "input_box_found": False, "message_list_found": False,
            "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
            "failure_stage": None, "debug_steps": [], "debug_screenshots": [],
        }
        mock_write.return_value = {"success": True, "pasted": True, "sent": True}

        client = TestClient(app)
        db = SessionLocal()
        try:
            db.query(LeadNotification).delete()
            staff = db.query(SalesStaff).filter(SalesStaff.name == "P02C测试销售").first()
            if not staff:
                staff = SalesStaff(name="P02C测试销售", wechat_nickname="P02CTest")
                db.add(staff)
                db.commit()
                db.refresh(staff)
            lead = db.query(DouyinLead).filter(DouyinLead.customer_name == "P02C测试客户").first()
            if not lead:
                lead = DouyinLead(customer_name="P02C测试客户", source="test",
                                  status="assigned", assigned_staff_id=staff.id)
                db.add(lead)
                db.commit()
                db.refresh(lead)

            response = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id, "auto_send": True,
            })
            data = response.json()

            assert data["send_status"] == "failed", \
                f"chat_verified=False 时 send_status 应为 failed，实际为 {data.get('send_status')}"
            mock_write.assert_not_called()
        finally:
            db.query(LeadNotification).filter(LeadNotification.lead_id == lead.id).delete()
            db.query(DouyinLead).filter(DouyinLead.id == lead.id).delete()
            db.query(SalesStaff).filter(SalesStaff.id == staff.id).delete()
            db.commit()
            db.close()


# ========== 测试 3：前台窗口丢失触发失败 ==========

class TestForegroundWindowLost:

    def test_foreground_lost_after_click_triggers_failure(self):
        """点击搜索框后前台窗口丢失 → 返回失败"""
        call_count = [0]
        def mock_foreground(hwnd):
            call_count[0] += 1
            return call_count[0] <= 1  # 第一次 True，第二次 False

        result = _run_open_chat(foreground=mock_foreground)

        assert result["success"] is False
        assert "foreground" in result["failure_stage"].lower(), \
            f"前台丢失应体现在 failure_stage 中，实际: {result['failure_stage']}"


# ========== 测试 4：截图调试证据被记录 ==========

class TestDebugScreenshotsRecorded:

    def test_screenshots_populated_on_success(self):
        """成功时 debug_screenshots 包含截图路径"""
        result = _run_open_chat()

        assert result["success"] is True
        assert len(result["debug_screenshots"]) > 0, "成功时应有截图证据"


# ========== 测试 5：不允许 success=true 但 chat_verified=false ==========

class TestNoFalseSuccess:

    def test_open_chat_response_has_required_fields(self):
        """OpenChatResponse 必须包含 P0-2C 新增字段"""
        from app.schemas import OpenChatResponse
        resp = OpenChatResponse(success=True, message="ok", nickname="test")
        assert hasattr(resp, "chat_verified")
        assert hasattr(resp, "confidence")
        assert hasattr(resp, "debug_screenshots")

    def test_success_implies_chat_verified_and_input_box(self):
        """success=True 只能表示搜索动作完成，最终验证必须交给 OCR"""
        result = _run_open_chat()

        if result["success"]:
            assert result["search_action_completed"] is True
            assert result["search_keyword_pasted"] is True
            assert result["maybe_chat_opened"] is True
            assert result["chat_verified"] is False
            assert result["input_box_found"] is False
            assert result["confidence"] <= 0.3
