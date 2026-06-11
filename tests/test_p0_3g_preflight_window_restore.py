"""P0-3G ESC / hidden / minimized / restore preflight tests."""

import inspect
from argparse import Namespace
from unittest.mock import MagicMock, patch


def _mock_window(hwnd: int = 123):
    window = MagicMock()
    window.NativeWindowHandle = hwnd
    return window


def _not_ready(**overrides):
    data = {
        "success": False,
        "automation_allowed": False,
        "visible": False,
        "iconic": False,
        "restored_from_hidden_or_minimized": False,
        "requires_manual_open": True,
        "message": "微信窗口当前隐藏或最小化，请手动打开微信并确认内容正常后重试",
    }
    data.update(overrides)
    return data


def test_business_open_chat_refuses_hidden_wechat():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_window()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation",
               return_value=_not_ready(visible=False)), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_workspace_layout") as mock_layout, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.window_locator.activate_wechat_window") as mock_activate:
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    mock_layout.assert_not_called()
    mock_activate.assert_not_called()
    mock_keys.assert_not_called()


def test_business_open_chat_refuses_minimized_wechat():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_window()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation",
               return_value=_not_ready(visible=True, iconic=True)), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_workspace_layout") as mock_layout, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys:
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    mock_layout.assert_not_called()
    mock_keys.assert_not_called()


def test_input_writer_refuses_hidden_wechat():
    from app.wechat_ui.input_writer import write_text_to_input

    with patch("app.wechat_ui.input_writer.check_wechat_ready_for_automation",
               return_value=_not_ready(visible=False)), \
         patch("app.wechat_ui.input_writer.find_input_box") as mock_input, \
         patch("app.wechat_ui.input_writer.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.window_locator.ensure_wechat_workspace_layout") as mock_layout:
        result = write_text_to_input(_mock_window(), "hello", require_confirm=False)

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    mock_input.assert_not_called()
    mock_keys.assert_not_called()
    mock_layout.assert_not_called()


def test_contact_ocr_refuses_hidden_wechat_in_business_mode(tmp_path):
    from scripts import debug_contact_ocr

    args = Namespace(
        nickname="Aw3",
        region="top_title",
        position="right",
        engine="none",
        output_dir=str(tmp_path),
        mode="business",
    )

    with patch("scripts.debug_contact_ocr.check_ocr_window_readiness",
               return_value=_not_ready(visible=False)), \
         patch("scripts.debug_contact_ocr.get_wechat_rect") as mock_rect, \
         patch("scripts.debug_contact_ocr.capture_region") as mock_capture:
        result = debug_contact_ocr.run_debug(args)

    assert result["matched"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    assert result["debug_only"] is False
    mock_rect.assert_not_called()
    mock_capture.assert_not_called()


def test_esc_not_used_in_business_paths():
    from app.wechat_ui import contact_searcher, input_writer
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    assert 'SendKeys("{Esc}")' not in inspect.getsource(contact_searcher.open_chat_by_nickname)
    assert 'SendKeys("{Esc}")' not in inspect.getsource(contact_searcher._do_search_once)
    assert 'SendKeys("{Esc}")' not in inspect.getsource(input_writer.write_text_to_input)
    assert 'SendKeys("{Esc}")' not in inspect.getsource(input_writer._do_write_once)
    assert 'SendKeys("{Esc}")' not in inspect.getsource(verify_current_chat_contact)


def test_close_profile_card_does_not_hide_wechat_by_default():
    from app.wechat_ui.contact_verifier import _close_profile_card_safe

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}

    with patch("app.wechat_ui.contact_verifier.find_wechat_window",
               side_effect=Exception("not found")), \
         patch("app.wechat_ui.contact_verifier.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_verifier.ensure_wechat_visible") as mock_visible:
        result = _close_profile_card_safe(win_rect)

    assert result["esc_used"] is False
    assert result["method"] == "click_blank_unverified"
    assert result["automation_allowed"] is False
    mock_keys.assert_not_called()
    mock_visible.assert_not_called()


def test_restore_after_hidden_marks_not_ready():
    from app.wechat_ui.window_locator import readiness_from_activation_result

    readiness = readiness_from_activation_result({
        "success": True,
        "hwnd": 123,
        "was_visible": False,
        "was_minimized": False,
        "activate_steps": ["SW_SHOW", "SetForegroundWindow"],
    })

    assert readiness.restored_from_hidden_or_minimized is True
    assert readiness.automation_allowed is False
    assert readiness.requires_manual_open is True


def test_business_workspace_layout_refuses_hidden_before_activate():
    from app.wechat_ui.window_locator import ensure_wechat_workspace_layout

    with patch("app.wechat_ui.window_locator.check_wechat_ready_for_automation",
               return_value=_not_ready(visible=False, hwnd=123)), \
         patch("app.wechat_ui.window_locator.activate_wechat_window") as mock_activate:
        result = ensure_wechat_workspace_layout(allow_restore=False)

    assert result["layout_ok"] is False
    assert result["automation_allowed"] is False
    mock_activate.assert_not_called()


def test_business_workspace_layout_rejects_activation_that_restored_window():
    from app.wechat_ui.window_locator import ensure_wechat_workspace_layout

    with patch("app.wechat_ui.window_locator.check_wechat_ready_for_automation",
               return_value={"success": True, "hwnd": 123}), \
         patch("app.wechat_ui.window_locator.activate_wechat_window",
               return_value={
                   "success": True,
                   "hwnd": 123,
                   "actual_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
                   "was_visible": False,
                   "was_minimized": False,
               }):
        result = ensure_wechat_workspace_layout(allow_restore=False)

    assert result["layout_ok"] is False
    assert result["restored_from_hidden_or_minimized"] is True
    assert result["automation_allowed"] is False
