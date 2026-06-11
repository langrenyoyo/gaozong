"""P0-3I Aw3 单条发送复测脚本测试。"""

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch


def _args(**overrides):
    data = {
        "nickname": "Aw3",
        "message": "[AUTO_WECHAT_TEST] P0-3I",
        "position": "right",
        "engine": "easyocr",
        "confirm_before_send": "true",
        "send_enter": "false",
        "output_dir": "data/debug_screenshots/aw3_single_send",
    }
    data.update(overrides)
    return Namespace(**data)


def _verified(**overrides):
    data = {
        "verified": True,
        "strategy": "ocr_top_title",
        "matched_text": "AW3",
        "ocr_text": "AW3",
        "confidence": 0.9016,
        "partial_match": False,
        "manual_review_required": False,
        "failure_stage": None,
        "evidence": {"cropped_path": "crop.png"},
    }
    data.update(overrides)
    return data


def _window(hwnd=123):
    window = MagicMock()
    window.NativeWindowHandle = hwnd
    return window


def test_debug_aw3_single_send_rejects_non_aw3(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(nickname="啊东、", output_dir=str(tmp_path)))

    assert result["success"] is False
    assert result["failure_stage"] == "only_aw3_allowed_for_p0_3i"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_requires_verified_true(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact",
               return_value=_verified(verified=False, failure_stage="contact_not_verified")), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), confirm_before_send="false"))

    assert result["success"] is False
    assert result["failure_stage"] == "contact_not_verified"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_blocks_partial_match(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact",
               return_value=_verified(verified=True, partial_match=True)), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), confirm_before_send="false"))

    assert result["success"] is False
    assert result["failure_stage"] == "partial_match_blocked"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_blocks_manual_review_required(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact",
               return_value=_verified(verified=True, manual_review_required=True)), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), confirm_before_send="false"))

    assert result["success"] is False
    assert result["failure_stage"] == "manual_review_required_blocked"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_checks_readiness_before_paste(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation",
               return_value={"success": False, "visible": False}), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), confirm_before_send="false"))

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready_before_paste"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_checks_foreground_before_enter(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground",
               side_effect=[{"success": True}, {"success": False, "message": "lost"}]), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact", return_value=_verified()), \
         patch("scripts.debug_aw3_single_send.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False, "debug_screenshots": []}), \
         patch("scripts.debug_aw3_single_send.input", return_value="SEND"), \
         patch("scripts.debug_aw3_single_send.uia.SendKeys") as mock_keys:
        result = run_debug(_args(output_dir=str(tmp_path), send_enter="true"))

    assert result["success"] is False
    assert result["failure_stage"] == "foreground_lost_before_enter"
    mock_keys.assert_not_called()


def test_debug_aw3_single_send_requires_send_confirmation(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact", return_value=_verified()), \
         patch("scripts.debug_aw3_single_send.input", return_value="NO"), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), send_enter="true"))

    assert result["success"] is False
    assert result["failure_stage"] == "send_confirmation_rejected"
    mock_write.assert_not_called()


def test_debug_aw3_single_send_default_is_paste_only(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact", return_value=_verified()), \
         patch("scripts.debug_aw3_single_send.input", return_value="SEND"), \
         patch("scripts.debug_aw3_single_send.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False, "debug_screenshots": []}) as mock_write, \
         patch("scripts.debug_aw3_single_send.uia.SendKeys") as mock_keys:
        result = run_debug(_args(output_dir=str(tmp_path)))

    assert result["success"] is True
    assert result["pasted"] is True
    assert result["sent"] is False
    assert result["mode"] == "paste_only"
    mock_write.assert_called_once()
    assert mock_write.call_args.kwargs["require_confirm"] is True
    mock_keys.assert_not_called()


def test_debug_aw3_single_send_does_not_call_write_text_when_not_verified(tmp_path):
    from scripts.debug_aw3_single_send import run_debug

    with patch("scripts.debug_aw3_single_send.is_automation_allowed", return_value=True), \
         patch("scripts.debug_aw3_single_send.find_wechat_window", return_value=_window()), \
         patch("scripts.debug_aw3_single_send.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.ensure_wechat_foreground", return_value={"success": True}), \
         patch("scripts.debug_aw3_single_send.verify_current_chat_contact",
               return_value=_verified(verified=False, partial_match=True)), \
         patch("scripts.debug_aw3_single_send.write_text_to_input") as mock_write:
        result = run_debug(_args(output_dir=str(tmp_path), confirm_before_send="false"))

    assert result["success"] is False
    assert result["verified_before_paste"] is False
    assert mock_write.call_count == 0
