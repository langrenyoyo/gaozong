"""P0-3B 前台焦点守卫测试"""

import inspect
import ctypes
from contextlib import ExitStack
from unittest.mock import MagicMock, patch


def _ok_guard(reason="ok"):
    return {"success": True, "reason": reason, "foreground_hwnd": 123}


def _fail_guard(reason="lost"):
    return {
        "success": False,
        "reason": reason,
        "foreground_hwnd": 999,
        "foreground_title": "Other",
        "foreground_class": "OtherWindow",
    }


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
    ctx = {
        "hwnd": 123,
        "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        "window": ctrl,
    }
    return patch(
        "app.wechat_ui.contact_searcher._check_preconditions",
        return_value=(True, "OK", ctx),
    )


def _search_patches():
    return [
        patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="test.png"),
        patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"),
        patch("app.wechat_ui.contact_searcher.capture_wechat_region", return_value=MagicMock()),
        patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
              return_value={"success": True, "x": 120, "y": 88, "strategy": "manual_calibration", "confidence": 0.7}),
        patch("app.wechat_ui.contact_searcher.uia.SendKeys"),
        patch("app.wechat_ui.contact_searcher._save_clipboard", return_value=""),
        patch("app.wechat_ui.contact_searcher._set_clipboard"),
        patch("app.wechat_ui.contact_searcher._restore_clipboard"),
        patch("app.wechat_ui.contact_searcher._is_wechat_foreground", return_value=True),
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
        patch("app.wechat_ui.contact_searcher.ctypes"),
        patch("app.wechat_ui.contact_searcher.time.sleep"),
        patch("app.wechat_ui.contact_searcher._trigger_emergency_stop"),
        patch("app.wechat_ui.window_locator.find_current_chat_title", return_value=None),
        patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_ctrl()),
    ]


def test_ensure_wechat_foreground_success_when_already_foreground():
    from app.wechat_ui.window_locator import ensure_wechat_foreground

    with patch.object(ctypes.windll.user32, "IsWindow", return_value=1), \
         patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=1), \
         patch.object(ctypes.windll.user32, "IsIconic", return_value=0), \
         patch.object(ctypes.windll.user32, "GetForegroundWindow", return_value=123):
        result = ensure_wechat_foreground(123, reason="before_ctrl_a")

    assert result["success"] is True
    assert result["already_foreground"] is True
    assert result["reason"] == "before_ctrl_a"


def test_ensure_wechat_foreground_restores_when_lost():
    from app.wechat_ui.window_locator import ensure_wechat_foreground

    with patch.object(ctypes.windll.user32, "IsWindow", return_value=1), \
         patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=1), \
         patch.object(ctypes.windll.user32, "IsIconic", return_value=0), \
         patch.object(ctypes.windll.user32, "GetForegroundWindow", side_effect=[999, 123]), \
         patch.object(ctypes.windll.user32, "SetForegroundWindow") as mock_set, \
         patch("app.wechat_ui.window_locator._push_overlay_back") as mock_overlay, \
         patch("app.wechat_ui.window_locator.time.sleep"):
        result = ensure_wechat_foreground(123, reason="before_paste")

    assert result["success"] is True
    assert result["recovered"] is True
    mock_overlay.assert_called()
    mock_set.assert_called_with(123)


def test_ensure_wechat_foreground_fails_after_retries():
    from app.wechat_ui.window_locator import ensure_wechat_foreground

    with patch.object(ctypes.windll.user32, "IsWindow", return_value=1), \
         patch.object(ctypes.windll.user32, "IsWindowVisible", return_value=1), \
         patch.object(ctypes.windll.user32, "IsIconic", return_value=0), \
         patch.object(ctypes.windll.user32, "GetForegroundWindow", return_value=999), \
         patch.object(ctypes.windll.user32, "SetForegroundWindow") as mock_set, \
         patch("app.wechat_ui.window_locator._push_overlay_back"), \
         patch("app.wechat_ui.window_locator.time.sleep"):
        result = ensure_wechat_foreground(123, reason="before_enter", max_attempts=3)

    assert result["success"] is False
    assert result["reason"] == "before_enter"
    assert result["foreground_hwnd"] == 999
    assert mock_set.call_count >= 3


def test_contact_searcher_checks_foreground_before_ctrl_a():
    import app.wechat_ui.contact_searcher as contact_searcher

    source = inspect.getsource(contact_searcher._do_search_once)

    assert 'reason="before_ctrl_a"' in source
    assert source.index('reason="before_ctrl_a"') < source.index('SendKeys("{Ctrl}a"')


def test_contact_searcher_stops_when_foreground_lost_before_paste():
    from app.wechat_ui.contact_searcher import _do_search_once

    guard_results = [
        _ok_guard("before_ctrl_a"),
        _ok_guard("before_backspace"),
        _fail_guard("before_paste_nickname"),
    ]

    with ExitStack() as stack:
        stack.enter_context(_mock_precond_ok())
        for p in _search_patches():
            stack.enter_context(p)
        mock_guard = stack.enter_context(
            patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", side_effect=guard_results)
        )
        mock_send = stack.enter_context(patch("app.wechat_ui.contact_searcher.uia.SendKeys"))

        result = _do_search_once("文件传输助手", 1, "filehelper")

    assert result["success"] is False
    assert result["failure_stage"] == "foreground_lost_before_paste_nickname"
    assert mock_guard.call_count == 3
    sent_keys = [call.args[0] for call in mock_send.call_args_list]
    assert "{Ctrl}v" not in sent_keys


def test_input_writer_checks_foreground_before_enter():
    import app.wechat_ui.input_writer as input_writer

    source = inspect.getsource(input_writer._do_write_once)

    assert 'reason="before_paste_content"' in source
    assert source.index('reason="before_paste_content"') < source.index('SendKeys("{Ctrl}v"')
    assert 'reason="before_enter_send"' in source
    assert source.index('reason="before_enter_send"') < source.index('SendKeys("{Enter}"')


def test_debug_script_records_guard_result():
    import scripts.debug_wechat_render_state as render_state

    records = []
    notes = render_state.append_guard_result(
        records,
        "step_04_ctrl_a",
        {"success": True, "reason": "before_ctrl_a"},
    )

    assert records[0]["step"] == "step_04_ctrl_a"
    assert records[0]["guard_result"]["success"] is True
    assert "foreground_guard" in notes[0]
