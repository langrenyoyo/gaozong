"""P0-2G 微信窗口隐藏与白屏误判修复测试

验证：
  1. 白屏检测在窗口不可见时跳过（不误判桌面背景为白屏）
  2. 白屏检测在窗口最小化时跳过
  3. 白屏检测在窗口可见时正常执行
  4. ensure_wechat_visible 能恢复被隐藏的窗口
  5. 搜索流程不再发送 Esc
  6. 资料卡关闭使用安全方法
  7. contact_verifier 不直接调用 Esc
"""

import ctypes
import pytest
from unittest.mock import patch, MagicMock

from app.services.automation_control import resume_automation, set_action_in_progress


@pytest.fixture(autouse=True)
def _reset_automation():
    resume_automation()
    set_action_in_progress(False)
    yield
    resume_automation()
    set_action_in_progress(False)


# ========== 测试 1：白屏检测在窗口不可见时跳过 ==========

class TestWhiteScreenSkipsNotVisible:
    """窗口不可见 → 不做白屏检测"""

    @patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=0)
    @patch.object(ctypes.windll.user32, "IsWindow", return_value=1)
    def test_not_visible_returns_false(self, mock_is_win, mock_is_vis):
        """IsWindowVisible=False → 不截桌面、不误判白屏"""
        from app.wechat_ui.window_locator import _check_white_screen

        is_white, detail = _check_white_screen(12345)

        assert is_white is False
        assert "不可见" in detail

    @patch.object(ctypes.windll.user32, "IsWindow", return_value=0)
    def test_invalid_hwnd_returns_false(self, mock_is_win):
        """IsWindow=False → 直接返回非白屏"""
        from app.wechat_ui.window_locator import _check_white_screen

        is_white, detail = _check_white_screen(12345)

        assert is_white is False
        assert "无效" in detail


# ========== 测试 2：白屏检测在窗口最小化时跳过 ==========

class TestWhiteScreenSkipsMinimized:
    """窗口最小化 → 不做白屏检测"""

    @patch.object(ctypes.windll.user32, "IsIconic", return_value=1)
    @patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=1)
    @patch.object(ctypes.windll.user32, "IsWindow", return_value=1)
    def test_minimized_returns_false(self, mock_is_win, mock_is_vis, mock_iconic):
        """IsIconic=True → 跳过白屏检测"""
        from app.wechat_ui.window_locator import _check_white_screen

        is_white, detail = _check_white_screen(12345)

        assert is_white is False
        assert "最小化" in detail


# ========== 测试 3：白屏检测在窗口可见时正常执行 ==========

class TestWhiteScreenExecutesWhenVisible:
    """窗口可见且未最小化 → 正常执行白屏检测"""

    @patch("app.wechat_ui.screenshot_debug.grab_screen")
    @patch.object(ctypes.windll.user32, "IsIconic", return_value=0)
    @patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=1)
    @patch.object(ctypes.windll.user32, "IsWindow", return_value=1)
    def test_visible_window_does_check(self, mock_is_win, mock_is_vis, mock_iconic, mock_grab):
        """visible + not iconic → 执行像素检测"""
        from app.wechat_ui.window_locator import _check_white_screen

        white_img = MagicMock()
        white_img.convert.return_value = white_img
        white_img.tobytes.return_value = bytes([255, 255, 255] * 100)
        mock_grab.return_value = white_img

        is_white, detail = _check_white_screen(12345)

        assert is_white is True
        assert "100%" in detail


# ========== 测试 4：ensure_wechat_visible 恢复隐藏窗口 ==========

class TestEnsureWechatVisible:
    """ensure_wechat_visible 恢复被隐藏的窗口"""

    @patch("app.wechat_ui.window_locator.find_wechat_window")
    def test_already_visible_returns_ok(self, mock_find):
        """窗口已可见 → 直接返回成功"""
        from app.wechat_ui.window_locator import ensure_wechat_visible

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        with patch("app.wechat_ui.window_locator.ctypes") as mock_ctypes:
            mock_ctypes.windll.user32.IsWindowVisible.return_value = 1
            mock_ctypes.windll.user32.IsIconic.return_value = 0

            result = ensure_wechat_visible(12345)

        assert result["success"] is True
        assert result["was_visible"] is True
        assert result["recovered"] is False
        assert "already_visible" in result["steps"]

    @patch("app.wechat_ui.window_locator.find_wechat_window")
    def test_hidden_window_restored(self, mock_find):
        """窗口不可见 → SW_SHOW 恢复 → 成功"""
        from app.wechat_ui.window_locator import ensure_wechat_visible

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        with patch("app.wechat_ui.window_locator.ctypes") as mock_ctypes:
            # 初始不可见
            mock_ctypes.windll.user32.IsWindowVisible.side_effect = [0, 1]
            mock_ctypes.windll.user32.IsIconic.return_value = 0

            result = ensure_wechat_visible(12345)

        assert result["success"] is True
        assert result["was_visible"] is False
        assert result["recovered"] is True
        assert "SW_SHOW" in result["steps"]

    @patch("app.wechat_ui.window_locator.find_wechat_window")
    def test_minimized_window_restored(self, mock_find):
        """窗口最小化 → SW_RESTORE 恢复 → 成功"""
        from app.wechat_ui.window_locator import ensure_wechat_visible

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        with patch("app.wechat_ui.window_locator.ctypes") as mock_ctypes:
            # 初始最小化
            mock_ctypes.windll.user32.IsWindowVisible.side_effect = [1, 1]
            mock_ctypes.windll.user32.IsIconic.side_effect = [1, 0]

            result = ensure_wechat_visible(12345)

        assert result["success"] is True
        assert result["was_iconic"] is True
        assert result["recovered"] is True
        assert "SW_RESTORE" in result["steps"]

    @patch("app.wechat_ui.window_locator.find_wechat_window")
    def test_restore_failure(self, mock_find):
        """窗口不可见 → 恢复后仍不可见 → success=False"""
        from app.wechat_ui.window_locator import ensure_wechat_visible

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        with patch("app.wechat_ui.window_locator.ctypes") as mock_ctypes:
            # 恢复后仍不可见
            mock_ctypes.windll.user32.IsWindowVisible.side_effect = [0, 0]
            mock_ctypes.windll.user32.IsIconic.side_effect = [0, 0]

            result = ensure_wechat_visible(12345)

        assert result["success"] is False
        assert result["recovered"] is False


# ========== 测试 5：搜索流程不发送 Esc ==========

class TestSearchFlowNoEsc:
    """搜索流程不再发送 Esc 键"""

    def test_search_flow_no_esc_in_code(self):
        """contact_searcher.py 的 _do_search_once 中不再包含 Esc 调用"""
        import inspect
        from app.wechat_ui.contact_searcher import _do_search_once

        source = inspect.getsource(_do_search_once)

        # 搜索流程中不应包含 Esc 调用
        assert 'SendKeys("{Esc}")' not in source, (
            "搜索流程 _do_search_once 中仍包含 Esc 调用，"
            "P0-2G 要求移除搜索流程中的 Esc"
        )


# ========== 测试 6：资料卡关闭使用安全方法 ==========

class TestProfileCardSafeClose:
    """资料卡关闭使用 _close_profile_card_safe"""

    def test_close_card_function_exists(self):
        """_close_profile_card_safe 函数存在"""
        from app.wechat_ui.contact_verifier import _close_profile_card_safe
        assert callable(_close_profile_card_safe)

    @patch("app.wechat_ui.contact_verifier.find_wechat_window")
    def test_close_card_clicks_blank_first(self, mock_find):
        """_close_profile_card_safe 优先点击空白区域"""
        from app.wechat_ui.contact_verifier import _close_profile_card_safe

        ctrl = MagicMock()
        ctrl.NativeWindowHandle = 12345
        mock_find.return_value = ctrl

        win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}

        with patch("app.wechat_ui.contact_verifier.ctypes") as mock_ctypes:
            mock_ctypes.windll.user32.IsWindowVisible.return_value = 1

            result = _close_profile_card_safe(win_rect)

        # 应该通过点击空白区域关闭，不使用 Esc
        assert result["esc_used"] is False
        assert result["method"] == "click_blank"

    @patch("app.wechat_ui.contact_verifier.ensure_wechat_visible")
    @patch("app.wechat_ui.contact_verifier.find_wechat_window")
    def test_close_card_esc_fallback_with_recovery(self, mock_find, mock_ensure):
        """_close_profile_card_safe Esc 回退时调用 ensure_wechat_visible"""
        from app.wechat_ui.contact_verifier import _close_profile_card_safe

        # find_wechat_window 在点击空白后抛异常（触发回退到 Esc）
        mock_find.side_effect = [Exception("not found")]

        mock_ensure.return_value = {
            "success": True, "was_visible": False, "recovered": True,
            "message": "已恢复",
        }

        win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}

        result = _close_profile_card_safe(win_rect)

        # 应该回退到 Esc 并调用恢复
        assert result["esc_used"] is True
        mock_ensure.assert_called_once()


# ========== 测试 7：contact_verifier 不直接调用 Esc ==========

class TestVerifierNoDirectEsc:
    """contact_verifier 策略 B/C 不直接调用 Esc"""

    def test_verify_function_no_direct_esc(self):
        """verify_current_chat_contact 中不再有直接的 Esc 调用"""
        import inspect
        from app.wechat_ui.contact_verifier import verify_current_chat_contact

        source = inspect.getsource(verify_current_chat_contact)

        # 不应包含直接 Esc 调用（应通过 _close_profile_card_safe 间接使用）
        assert 'SendKeys("{Esc}")' not in source, (
            "verify_current_chat_contact 中存在直接 Esc 调用，"
            "应通过 _close_profile_card_safe 间接使用"
        )
