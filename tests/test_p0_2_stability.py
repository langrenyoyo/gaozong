"""P0-2B/C 微信自动化稳定化测试

测试策略：
  - 使用 ExitStack 动态管理 patch，避免手动索引
  - 直接 mock _check_preconditions 隔离底层 ctypes 依赖
  - 对 input_writer：patch screenshot_debug 源模块
"""

import pytest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

from app.services.automation_control import resume_automation, request_emergency_stop, set_action_in_progress


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


def _all_search_patches():
    """contact_searcher 搜索所需全部 patch"""
    return [
        patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="test.png"),
        patch("app.wechat_ui.contact_searcher.capture_wechat_region", return_value=MagicMock()),
        patch("app.wechat_ui.contact_searcher.verify_search_area_changed",
              return_value={"verified": True, "diff_ratio": 0.15, "message": "已变化"}),
        patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
              return_value={"success": True, "x": 120, "y": 88, "strategy": "manual_calibration", "confidence": 0.7}),
        patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"),
        patch("app.wechat_ui.contact_searcher.uia.SendKeys"),
        patch("app.wechat_ui.contact_searcher._save_clipboard", return_value=""),
        patch("app.wechat_ui.contact_searcher._set_clipboard"),
        patch("app.wechat_ui.contact_searcher._restore_clipboard"),
        patch("app.wechat_ui.contact_searcher._is_wechat_foreground", return_value=True),
        patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground",
              return_value={"success": True, "message": "OK"}),
        patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
              return_value={
                  "clicked": True,
                  "focused": True,
                  "verified": True,
                  "success": True,
                  "text_pasted_into_search_box": False,
                  "text_leaked_to_chat_input": False,
                  "manual": False,
                  "manual_review_required": False,
              }),
        patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
              return_value={
                  "search_text_verified": True,
                  "text_pasted_into_search_box": True,
                  "text_leaked_to_chat_input": False,
                  "manual": False,
              }),
        patch("app.wechat_ui.contact_searcher.detect_search_result",
              return_value={
                  "success": True,
                  "search_result_detected": True,
                  "method": "ocr_result_area",
                  "click_point": {"x": 180, "y": 155},
                  "confidence": 0.85,
                  "screenshots": {},
              }),
        patch("app.wechat_ui.contact_searcher.ctypes"),
        patch("app.wechat_ui.contact_searcher.time.sleep"),
        patch("app.wechat_ui.contact_searcher._trigger_emergency_stop"),
        patch("app.wechat_ui.window_locator.find_current_chat_title", return_value=None),
        patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_ctrl()),
    ]


# ========== contact_searcher 测试 ==========

class TestOpenChatRetry:

    def test_empty_nickname_returns_immediately(self):
        from app.wechat_ui.contact_searcher import open_chat_by_nickname
        result = open_chat_by_nickname("")
        assert result["success"] is False
        assert result["attempts"] == 0
        assert result["failure_stage"] == "validation"
        assert "chat_verified" in result
        assert "debug_screenshots" in result

    def test_emergency_stop_blocks_search(self):
        from app.wechat_ui.contact_searcher import open_chat_by_nickname
        request_emergency_stop("test")
        result = open_chat_by_nickname("测试")
        assert result["success"] is False
        assert result["failure_stage"] == "emergency_stop"

    def test_max_attempts_exhausted(self):
        """前置条件始终失败 → 返回失败"""
        from app.wechat_ui.contact_searcher import open_chat_by_nickname
        with patch("app.wechat_ui.contact_searcher._check_preconditions",
                    return_value=(False, "微信窗口未找到", {})), \
             patch("app.wechat_ui.contact_searcher.save_debug_screenshot"):
            result = open_chat_by_nickname("测试", max_attempts=2)
        assert result["success"] is False
        assert result["attempts"] == 2
        assert result["failure_stage"] == "preconditions"

    def test_success_returns_all_fields(self):
        """成功时返回完整 debug_steps、screenshots，但不再声明联系人已验证"""
        from app.wechat_ui.contact_searcher import open_chat_by_nickname

        with ExitStack() as stack:
            stack.enter_context(_mock_precond_ok())
            for p in _all_search_patches():
                stack.enter_context(p)
            result = open_chat_by_nickname("测试")

        assert result["success"] is True
        assert result["attempts"] == 1
        assert result["failure_stage"] is None
        assert result["search_action_completed"] is True
        assert result["search_keyword_pasted"] is True
        assert result["maybe_chat_opened"] is True
        assert result["chat_verified"] is False
        assert result["input_box_found"] is False
        assert result["confidence"] <= 0.3
        assert len(result["debug_steps"]) > 0
        assert len(result["debug_screenshots"]) > 0
        assert result["window_rect"] is not None
        assert result["warning"] is not None
        assert "final verification requires OCR" in result["warning"]

        stages = [s["stage"] for s in result["debug_steps"]]
        assert "preconditions" in stages
        assert "search_box_clicked" in stages
        assert "search_input_verified" in stages
        assert "search_action_completed" in stages

    def test_retry_on_precond_failure_then_success(self):
        """前置条件失败后重试成功"""
        from app.wechat_ui.contact_searcher import open_chat_by_nickname

        call_count = [0]
        def mock_precond():
            call_count[0] += 1
            if call_count[0] <= 2:
                return (False, "微信不在前台", {})
            ctrl = _mock_ctrl()
            ctx = {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": ctrl}
            return (True, "OK", ctx)

        with ExitStack() as stack:
            for p in _all_search_patches():
                stack.enter_context(p)
            stack.enter_context(
                patch("app.wechat_ui.contact_searcher._check_preconditions", side_effect=mock_precond)
            )
            result = open_chat_by_nickname("测试", max_attempts=3)

        assert result["attempts"] == 3
        assert result["success"] is True


# ========== input_writer 测试 ==========

class TestWriteTextRetry:

    def test_empty_text_returns_immediately(self):
        from app.wechat_ui.input_writer import write_text_to_input
        result = write_text_to_input(MagicMock(), "")
        assert result["success"] is False
        assert result["attempts"] == 0

    def test_fallback_input_click_point_uses_chat_input_safe_area(self):
        from app.wechat_ui.input_writer import _fallback_input_click_point

        rect = MagicMock()
        rect.left = 0
        rect.top = 0
        rect.right = 880
        rect.bottom = 700
        rect.width.return_value = 880
        rect.height.return_value = 700

        x, y = _fallback_input_click_point(rect)

        assert x == 572
        assert y == 630

    def test_retry_on_input_box_not_found(self):
        from app.wechat_ui.input_writer import write_text_to_input
        call_count = [0]
        def mock_find(window):
            call_count[0] += 1
            if call_count[0] == 1:
                from app.wechat_ui.exceptions import WechatUIError
                raise WechatUIError("输入框未找到")
            return MagicMock()

        with patch("app.wechat_ui.window_locator.ensure_wechat_workspace_layout",
                    return_value={"layout_ok": True}), \
             patch("app.wechat_ui.input_writer.find_input_box", side_effect=mock_find), \
             patch("app.wechat_ui.input_writer._save_clipboard", return_value=None), \
             patch("app.wechat_ui.input_writer._set_clipboard"), \
             patch("app.wechat_ui.input_writer._restore_clipboard"), \
             patch("app.wechat_ui.input_writer._is_wechat_foreground", return_value=True), \
             patch("app.wechat_ui.input_writer.ensure_wechat_foreground",
                   return_value={"success": True, "message": "OK"}), \
             patch("app.wechat_ui.input_writer.find_wechat_window_safe", return_value=MagicMock()), \
             patch("app.wechat_ui.screenshot_debug.save_debug_screenshot", return_value="test.png"):
            result = write_text_to_input(MagicMock(), "测试文本")

        assert result["success"] is True
        assert result["attempts"] == 1
        assert result["input_strategy"] == "auto_focused_input"

    def test_write_text_uses_auto_focused_input_before_click_fallback(self):
        from app.wechat_ui.input_writer import write_text_to_input
        from app.wechat_ui.exceptions import WechatUIError

        with patch("app.wechat_ui.window_locator.ensure_wechat_workspace_layout",
                    return_value={"layout_ok": True}), \
             patch("app.wechat_ui.input_writer.find_input_box", side_effect=WechatUIError("no input control")), \
             patch("app.wechat_ui.input_writer._save_clipboard", return_value=None), \
             patch("app.wechat_ui.input_writer._set_clipboard"), \
             patch("app.wechat_ui.input_writer._restore_clipboard"), \
             patch("app.wechat_ui.input_writer._is_wechat_foreground", return_value=True), \
             patch("app.wechat_ui.input_writer.ensure_wechat_foreground",
                   return_value={"success": True, "message": "OK"}), \
             patch("app.wechat_ui.screenshot_debug.save_debug_screenshot", return_value="test.png"), \
             patch("app.wechat_ui.input_writer.uia.SendKeys") as mock_keys:
            result = write_text_to_input(MagicMock(), "测试消息", require_confirm=True, max_attempts=1)

        assert result["success"] is True
        assert result["input_strategy"] == "auto_focused_input"
        assert "{Ctrl}v" in [call.args[0] for call in mock_keys.call_args_list]

    def test_returns_attempts_and_strategy(self):
        from app.wechat_ui.input_writer import write_text_to_input
        with patch("app.wechat_ui.window_locator.ensure_wechat_workspace_layout",
                    return_value={"layout_ok": True}), \
             patch("app.wechat_ui.input_writer.find_input_box", return_value=MagicMock()), \
             patch("app.wechat_ui.input_writer._save_clipboard", return_value=None), \
             patch("app.wechat_ui.input_writer._set_clipboard"), \
             patch("app.wechat_ui.input_writer._restore_clipboard"), \
             patch("app.wechat_ui.input_writer._is_wechat_foreground", return_value=True), \
             patch("app.wechat_ui.input_writer.ensure_wechat_foreground",
                   return_value={"success": True, "message": "OK"}), \
             patch("app.wechat_ui.screenshot_debug.save_debug_screenshot", return_value="test.png"):
            result = write_text_to_input(MagicMock(), "测试")

        assert result["success"] is True
        assert result["attempts"] == 1
        assert result["input_strategy"] == "uia_control"
        assert result["pasted"] is True

    def test_emergency_stop_blocks_enter(self):
        """auto_send=True 时 Enter 前紧急停止 → 只粘贴不发送"""
        from app.wechat_ui.input_writer import write_text_to_input
        call_seq = [0]
        def seq_is_allowed():
            call_seq[0] += 1
            # P0-2C: is_automation_allowed 调用序列：
            #   call 1: write_text_to_input 入口
            #   call 2: for 循环
            #   call 3: _do_write_once 发送前检查
            #   call 4: _do_write_once Enter 前检查 → 在这里触发停止
            if call_seq[0] >= 4:
                request_emergency_stop("test")
                return False
            return True

        with patch("app.wechat_ui.window_locator.ensure_wechat_workspace_layout",
                    return_value={"layout_ok": True}), \
             patch("app.wechat_ui.input_writer.find_input_box", return_value=MagicMock()), \
             patch("app.wechat_ui.input_writer._save_clipboard", return_value=None), \
             patch("app.wechat_ui.input_writer._set_clipboard"), \
             patch("app.wechat_ui.input_writer._restore_clipboard"), \
             patch("app.wechat_ui.input_writer._is_wechat_foreground", return_value=True), \
             patch("app.wechat_ui.input_writer.ensure_wechat_foreground",
                   return_value={"success": True, "message": "OK"}), \
             patch("app.wechat_ui.screenshot_debug.save_debug_screenshot", return_value="test.png"), \
             patch("app.wechat_ui.input_writer.is_automation_allowed", side_effect=seq_is_allowed):
            result = write_text_to_input(MagicMock(), "测试", require_confirm=False)

        assert result["pasted"] is True
        assert result["action"] == "pasted_only"


# ========== ensure_wechat_workspace_layout 测试 ==========

class TestEnsureWorkspaceLayout:

    @patch("app.wechat_ui.window_locator.activate_wechat_window")
    def test_layout_ok(self, mock_activate):
        from app.wechat_ui.window_locator import ensure_wechat_workspace_layout
        mock_activate.return_value = {"success": True,
            "actual_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "hwnd": 12345}
        assert ensure_wechat_workspace_layout()["layout_ok"] is True

    @patch("app.wechat_ui.window_locator.activate_wechat_window")
    def test_reactivates(self, mock_activate):
        from app.wechat_ui.window_locator import ensure_wechat_workspace_layout
        n = [0]
        def fn(**kw):
            n[0] += 1
            if n[0] == 1:
                return {"success": True, "actual_rect": {"left": 100, "top": 200, "right": 980, "bottom": 900}, "hwnd": 1}
            return {"success": True, "actual_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "hwnd": 1}
        mock_activate.side_effect = fn
        r = ensure_wechat_workspace_layout()
        assert r["layout_ok"] is True and r["attempts"] == 2

    @patch("app.wechat_ui.window_locator.activate_wechat_window")
    def test_fails_offset(self, mock_activate):
        from app.wechat_ui.window_locator import ensure_wechat_workspace_layout
        mock_activate.return_value = {"success": True,
            "actual_rect": {"left": 200, "top": 300, "right": 1080, "bottom": 1000}, "hwnd": 1}
        assert ensure_wechat_workspace_layout()["layout_ok"] is False

    @patch("app.wechat_ui.window_locator.activate_wechat_window")
    def test_fails_activate(self, mock_activate):
        from app.wechat_ui.window_locator import ensure_wechat_workspace_layout
        mock_activate.return_value = {"success": False, "message": "未找到"}
        assert ensure_wechat_workspace_layout()["layout_ok"] is False


# ========== action_in_progress 测试 ==========

class TestActionInProgress:

    def test_default_false(self):
        from app.services.automation_control import is_action_in_progress
        assert is_action_in_progress() is False

    def test_set_and_clear(self):
        from app.services.automation_control import set_action_in_progress, is_action_in_progress
        set_action_in_progress(True)
        assert is_action_in_progress() is True
        set_action_in_progress(False)
        assert is_action_in_progress() is False

    def test_status_includes_field(self):
        from app.services.automation_control import get_automation_status, set_action_in_progress
        set_action_in_progress(True)
        assert get_automation_status()["action_in_progress"] is True
        set_action_in_progress(False)
        assert get_automation_status()["action_in_progress"] is False
