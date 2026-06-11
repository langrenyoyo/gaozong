"""P0-4A local WeChat Agent tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _client():
    from app.local_agent_main import create_local_agent_app

    return TestClient(create_local_agent_app(host="127.0.0.1", port=19000))


def _window(hwnd=123):
    window = MagicMock()
    window.NativeWindowHandle = hwnd
    return window


def _verified(**overrides):
    data = {
        "verified": True,
        "strategy": "ocr_top_title",
        "ocr_text": "AW3",
        "confidence": 0.9016,
        "partial_match": False,
        "manual_review_required": False,
        "failure_stage": None,
        "evidence": {"cropped_path": "crop.png"},
    }
    data.update(overrides)
    return data


def _open_chat(**overrides):
    data = {
        "success": True,
        "nickname": "Aw3",
        "failure_stage": None,
        "chat_verified": True,
        "confidence": 0.6,
        "evidence": {"screenshot": "open.png"},
        "search_keyword": "Aw3",
        "opened_by": "search",
        "search_action_completed": True,
        "search_keyword_pasted": True,
        "maybe_chat_opened": True,
        "notes": [],
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _default_ocr_ready():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": True,
                             "model_ready": True, "initializing": False, "engine": "easyocr"}):
        yield


def test_local_agent_health():
    response = _client().get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["service"] == "auto_wechat_local_agent"
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 19000
    assert data["wechat_agent"] is True


def test_local_agent_rejects_non_aw3():
    with patch("app.local_agent_main.write_text_to_input") as mock_write:
        response = _client().post("/agent/wechat/test", json={
            "nickname": "NotAw3",
            "message": "should not send",
        })

    data = response.json()
    assert data["success"] is False
    assert data["failure_stage"] == "only_aw3_allowed_for_p0_4a"
    assert data["action"]["pasted"] is False
    assert data["action"]["sent"] is False
    mock_write.assert_not_called()


def test_local_agent_default_paste_only():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True, "visible": True, "iconic": False}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False, "debug_screenshots": []}) as mock_write:
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "[AUTO_WECHAT_TEST] P0-4A",
        })

    data = response.json()
    assert data["success"] is True
    assert data["request"]["mode"] == "paste_only"
    assert data["open_chat"]["success"] is True
    assert data["open_chat"]["chat_verified"] is True
    assert data["verify"]["verified"] is True
    assert data["action"]["pasted"] is True
    assert data["action"]["sent"] is False
    mock_write.assert_called_once()
    assert mock_write.call_args.kwargs["require_confirm"] is True


def test_local_agent_requires_verified_true():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified(verified=False, failure_stage="contact_not_verified")), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        })

    data = response.json()
    assert data["success"] is False
    assert data["failure_stage"] == "contact_not_verified"
    mock_write.assert_not_called()


def test_local_agent_blocks_partial_match():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified(verified=True, partial_match=True)), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        })

    data = response.json()
    assert data["success"] is False
    assert data["failure_stage"] == "partial_match_blocked"
    mock_write.assert_not_called()


def test_local_agent_blocks_hidden_wechat():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation",
               return_value={"success": False, "visible": False, "iconic": False}), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        })

    data = response.json()
    assert data["success"] is False
    assert data["failure_stage"] == "wechat_not_ready"
    mock_write.assert_not_called()


def test_local_agent_does_not_send_by_default():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False, "debug_screenshots": []}):
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
            "mode": "paste_only",
        })

    data = response.json()
    assert data["action"]["pasted"] is True
    assert data["action"]["sent"] is False


def test_local_agent_returns_machine_identity():
    response = _client().get("/health")

    data = response.json()
    assert data["agent_machine"]["hostname"]
    assert data["agent_machine"]["platform"]
    assert isinstance(data["agent_machine"]["pid"], int)


def test_local_agent_cors_allows_react_lan_origin():
    response = _client().options(
        "/agent/wechat/test",
        headers={
            "Origin": "http://192.168.110.113:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.110.113:5173"


def test_local_agent_exe_entry_defaults_to_loopback_agent():
    from app import local_agent_exe_entry

    assert local_agent_exe_entry.DEFAULT_EXE_HOST == "127.0.0.1"
    assert local_agent_exe_entry.DEFAULT_EXE_PORT == 19000
    assert local_agent_exe_entry.EXE_DISPLAY_NAME == "小高AI微信助手"

    with patch("app.local_agent_exe_entry._port_is_available", return_value=True), \
         patch("app.local_agent_exe_entry.uvicorn.run") as mock_run:
        exit_code = local_agent_exe_entry.main([])

    assert exit_code == 0
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 19000


def test_build_local_agent_exe_script_targets_named_onedir():
    from pathlib import Path

    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "小高AI微信助手" in script
    assert "app\\local_agent_exe_entry.py" in script
    assert "--onedir" in script
    assert "--console" in script
    assert "dist\\小高AI微信助手\\小高AI微信助手.exe" in script
    assert "pip install pyinstaller" in script
    assert "PythonExe" in script


def test_local_agent_windows_endpoint_exists():
    with patch("app.local_agent_main.collect_wechat_window_diagnostics", return_value={
        "wechat_detected": False,
        "wechat_candidates": [],
        "all_windows_sample": [],
        "notes": ["鏈娴嬪埌鐤戜技寰俊绐楀彛"],
    }):
        response = _client().get("/agent/wechat/windows")

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_windows_endpoint_returns_agent_machine():
    with patch("app.local_agent_main.collect_wechat_window_diagnostics", return_value={
        "wechat_detected": False,
        "wechat_candidates": [],
        "all_windows_sample": [],
        "notes": [],
    }):
        data = _client().get("/agent/wechat/windows").json()

    assert data["agent_machine"]["hostname"]
    assert data["agent_machine"]["platform"]
    assert isinstance(data["agent_machine"]["pid"], int)


def test_windows_endpoint_returns_wechat_candidates_schema():
    candidate = {
        "hwnd": 123456,
        "title": "寰俊",
        "class_name": "Qt51514QWindowIcon",
        "visible": True,
        "iconic": False,
        "rect": {"left": 0, "top": 0, "right": 900, "bottom": 700},
        "process_id": 9999,
        "process_name": "WeChat.exe",
    }
    with patch("app.local_agent_main.collect_wechat_window_diagnostics", return_value={
        "wechat_detected": True,
        "wechat_candidates": [candidate],
        "all_windows_sample": [candidate],
        "notes": [],
    }):
        data = _client().get("/agent/wechat/windows").json()

    assert data["wechat_detected"] is True
    assert data["wechat_candidates"][0]["title"] == "寰俊"
    assert data["wechat_candidates"][0]["process_name"] == "WeChat.exe"
    assert data["all_windows_sample"][0]["rect"]["right"] == 900


def test_foreground_debug_endpoint_exists():
    foreground_guard = {
        "success": True,
        "foreground_debug": {
            "stage": "foreground_debug",
            "wechat_hwnd": 123,
            "wechat_title": "寰俊",
            "wechat_process_name": "WeChat.exe",
            "attempts": [],
            "is_wechat_foreground": True,
        },
    }
    with patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation",
               return_value={"success": True, "visible": True, "iconic": False}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value=foreground_guard):
        response = _client().post("/agent/wechat/foreground-debug", json={"position": "right"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["foreground_success"] is True


def test_foreground_debug_returns_foreground_details():
    foreground_guard = {
        "success": False,
        "foreground_debug": {
            "stage": "foreground_debug",
            "wechat_hwnd": 123,
            "wechat_title": "寰俊",
            "wechat_class": "Qt51514QWindowIcon",
            "wechat_process_name": "WeChat.exe",
            "foreground_before_title": "React App",
            "foreground_before_process_name": "msedge.exe",
            "foreground_after_title": "React App",
            "foreground_after_process_name": "msedge.exe",
            "attempts": [{"method": "set_foreground", "success": False}],
            "is_wechat_foreground": False,
            "reason": "foreground_guard_failed",
        },
    }
    with patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation",
               return_value={"success": True, "visible": True, "iconic": False}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value=foreground_guard):
        data = _client().post("/agent/wechat/foreground-debug", json={"position": "right"}).json()

    assert data["success"] is False
    assert data["failure_stage"] == "foreground_guard_failed"
    assert data["foreground_debug"]["foreground_before_process_name"] == "msedge.exe"
    assert data["foreground_debug"]["attempts"][0]["method"] == "set_foreground"


def test_foreground_debug_does_not_paste_or_send():
    with patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation",
               return_value={"success": True, "visible": True, "iconic": False}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.write_text_to_input") as mock_write, \
         patch("app.local_agent_main.verify_current_chat_contact") as mock_verify:
        response = _client().post("/agent/wechat/foreground-debug", json={"position": "right"})

    assert response.status_code == 200
    mock_write.assert_not_called()
    mock_verify.assert_not_called()


def test_agent_test_returns_foreground_debug_on_paste_failure():
    foreground_guard = {
        "success": False,
        "message": "寰俊鍓嶅彴鐒︾偣鎭㈠澶辫触",
        "foreground_debug": {
            "stage": "before_paste",
            "wechat_hwnd": 123,
            "foreground_before_process_name": "msedge.exe",
            "foreground_after_process_name": "msedge.exe",
            "attempts": [{"method": "attach_thread_input", "success": False}],
            "is_wechat_foreground": False,
            "reason": "foreground_lost_before_paste",
        },
    }
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", side_effect=[{"success": True}, foreground_guard]), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "foreground_lost_before_paste"
    assert data["foreground_debug"]["attempts"][0]["method"] == "attach_thread_input"
    mock_write.assert_not_called()


def test_local_agent_test_calls_open_chat_before_verify():
    calls = []

    def _record_open(_nickname):
        calls.append("open_chat")
        return _open_chat()

    def _record_verify(_nickname):
        calls.append("verify")
        return _verified()

    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", side_effect=_record_open), \
         patch("app.local_agent_main.verify_current_chat_contact", side_effect=_record_verify), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False}):
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
        }).json()

    assert data["success"] is True
    assert calls == ["open_chat", "verify"]


def test_local_agent_test_blocks_when_open_chat_failed():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname",
               return_value=_open_chat(success=False, failure_stage="nickname_input", chat_verified=False)), \
         patch("app.local_agent_main.verify_current_chat_contact") as mock_verify, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "open_chat_failed"
    assert data["open_chat"]["success"] is False
    assert data["open_chat"]["failure_stage"] == "nickname_input"
    assert data["action"]["pasted"] is False
    mock_verify.assert_not_called()
    mock_write.assert_not_called()


def test_local_agent_test_blocks_when_verify_after_open_failed():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified(verified=False, manual_review_required=True, failure_stage="wrong_chat")), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "manual_review_required_blocked"
    assert data["open_chat"]["success"] is True
    assert data["verify"]["verified"] is False
    assert data["action"]["pasted"] is False
    mock_write.assert_not_called()


def test_local_agent_test_pastes_only_after_open_chat_and_verify():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}) as mock_ready, \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}) as mock_foreground, \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False}) as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
        }).json()

    assert data["success"] is True
    assert data["open_chat"]["chat_verified"] is True
    assert data["verify"]["verified"] is True
    assert data["action"] == {"pasted": True, "sent": False}
    assert mock_ready.call_count >= 2
    assert mock_foreground.call_count >= 2
    mock_write.assert_called_once()


def test_local_agent_test_does_not_send_enter():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": True}) as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
        }).json()

    assert data["action"]["sent"] is False
    mock_write.assert_called_once()


def test_local_agent_test_rejects_adong_even_with_open_chat():
    with patch("app.local_agent_main.open_chat_by_nickname") as mock_open, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "NotAw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "only_aw3_allowed_for_p0_4a"
    mock_open.assert_not_called()
    mock_write.assert_not_called()


def test_local_agent_test_returns_open_chat_result_schema():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False}):
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
        }).json()

    assert data["open_chat"]["nickname"] == "Aw3"
    assert data["open_chat"]["success"] is True
    assert data["open_chat"]["failure_stage"] is None
    assert data["open_chat"]["chat_verified"] is True
    assert data["open_chat"]["confidence"] == 0.6
    assert data["open_chat"]["evidence"] == {"screenshot": "open.png"}


def test_search_debug_endpoint_exists():
    search_debug = {
        "success": True,
        "click_point": {"x": 120, "y": 88, "strategy": "adaptive_left_panel_top_search"},
        "screenshots": {"before": "before.png", "after_click": "click.png", "after_paste": "paste.png"},
        "notes": [],
        "failure_stage": None,
        "message": "search debug completed",
    }
    with patch("app.local_agent_main.run_search_box_debug", return_value=search_debug):
        response = _client().post("/agent/wechat/search-debug", json={"nickname": "Aw3", "position": "right"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["click_point"]["strategy"] == "adaptive_left_panel_top_search"


def test_search_debug_does_not_press_enter():
    with patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.run_search_box_debug",
               return_value={"success": True, "click_point": {}, "screenshots": {}, "notes": []}) as mock_debug, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys:
        _client().post("/agent/wechat/search-debug", json={"nickname": "Aw3", "position": "right"})

    mock_debug.assert_called_once()
    sent_keys = [str(call.args[0]) for call in mock_keys.call_args_list if call.args]
    assert "{Enter}" not in sent_keys
    assert "{Down}" not in sent_keys


def test_search_debug_does_not_paste_message():
    with patch("app.local_agent_main.run_search_box_debug",
               return_value={"success": True, "click_point": {}, "screenshots": {}, "notes": []}), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        _client().post("/agent/wechat/search-debug", json={"nickname": "Aw3", "position": "right"})

    mock_write.assert_not_called()


def test_search_debug_returns_click_point():
    search_debug = {
        "success": True,
        "click_point": {"x": 120, "y": 88, "strategy": "adaptive_left_panel_top_search"},
        "screenshots": {"after_paste": "paste.png"},
        "notes": [],
    }
    with patch("app.local_agent_main.run_search_box_debug", return_value=search_debug):
        data = _client().post("/agent/wechat/search-debug", json={"nickname": "Aw3", "position": "right"}).json()

    assert data["click_point"]["x"] == 120
    assert data["click_point"]["y"] == 88
    assert data["screenshots"]["after_paste"] == "paste.png"


def test_locate_search_box_click_point_uses_manual_calibration_after_visual_failures():
    from app.wechat_ui import contact_searcher

    rect = {"left": 100, "top": 200, "right": 1100, "bottom": 900}
    with patch("app.wechat_ui.contact_searcher._get_window_rect_dict", return_value=rect), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_uia", return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_vision", return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_ocr", return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._load_search_box_calibration",
               return_value={"relative_x": 145, "relative_y": 55, "source": "manual"}):
        result = contact_searcher.locate_search_box_click_point(123, position="right")

    assert result["success"] is True
    assert result["strategy"] == "manual_calibration"
    assert result["x"] == 245
    assert result["y"] == 255


def test_locate_search_box_click_point_prefers_uia_search_edit():
    from app.wechat_ui import contact_searcher

    uia_result = {
        "success": True,
        "x": 111,
        "y": 88,
        "strategy": "uia_search_edit",
        "confidence": 0.9,
        "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
        "evidence": {},
    }
    with patch("app.wechat_ui.contact_searcher._get_window_rect_dict",
               return_value={"left": 0, "top": 0, "right": 880, "bottom": 700}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_uia", return_value=uia_result) as mock_uia, \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_ocr") as mock_ocr:
        result = contact_searcher.locate_search_box_click_point(123, position="right")

    assert result["success"] is True
    assert result["strategy"] == "uia_search_edit"
    mock_uia.assert_called_once()
    mock_ocr.assert_not_called()


def test_locate_search_box_uses_vision_rect_before_fixed_fallback():
    from app.wechat_ui import contact_searcher

    rect = {"left": 100, "top": 200, "right": 1100, "bottom": 900}
    vision_result = {
        "success": True,
        "search_box_rect": {"left": 170, "top": 238, "right": 325, "bottom": 270},
        "center_x": 247,
        "center_y": 254,
        "strategy": "vision_search_box_rect",
        "confidence": 0.82,
    }
    with patch("app.wechat_ui.contact_searcher._get_window_rect_dict", return_value=rect), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_uia",
               return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_vision",
               return_value=vision_result) as mock_vision, \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_ocr") as mock_ocr, \
         patch("app.wechat_ui.contact_searcher._load_search_box_calibration") as mock_calibration:
        result = contact_searcher.locate_search_box_click_point(123, position="right")

    assert result["success"] is True
    assert result["strategy"] == "vision_search_box_rect"
    assert result["search_box_rect"] == vision_result["search_box_rect"]
    assert result["x"] == 247
    assert result["y"] == 257
    mock_vision.assert_called_once()
    mock_ocr.assert_not_called()
    mock_calibration.assert_not_called()


def test_locate_search_box_returns_failure_when_no_rect_and_no_calibration():
    from app.wechat_ui import contact_searcher

    with patch("app.wechat_ui.contact_searcher._get_window_rect_dict",
               return_value={"left": 100, "top": 200, "right": 1100, "bottom": 900}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_uia",
               return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_vision",
               return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._locate_search_box_by_ocr",
               return_value={"success": False}), \
         patch("app.wechat_ui.contact_searcher._load_search_box_calibration", return_value=None):
        result = contact_searcher.locate_search_box_click_point(123, position="right")

    assert result["success"] is False
    assert result["failure_stage"] == "search_box_locate_failed"
    assert result["strategy"] == "no_search_box_locator_available"


def test_open_chat_does_not_mark_verified_without_final_ocr():
    from app.wechat_ui import contact_searcher

    result = contact_searcher.build_search_action_completed_result(
        nickname="Aw3",
        window_rect={"left": 0, "top": 0, "right": 1000, "bottom": 800},
        screenshots=["after_enter.png", "after_wait.png"],
    )

    assert result["success"] is True
    assert result["search_action_completed"] is True
    assert result["maybe_chat_opened"] is True
    assert result["chat_verified"] is False
    assert result["confidence"] <= 0.3


def test_search_debug_returns_overlay_screenshot():
    search_debug = {
        "success": True,
        "click_point": {"x": 120, "y": 88, "strategy": "vision_search_box_rect"},
        "screenshots": {
            "before": "before.png",
            "overlay": "overlay.png",
            "after_click": "click.png",
            "after_paste": "paste.png",
        },
        "search_focus": {"search_text_verified": True},
        "notes": [],
    }
    with patch("app.local_agent_main.run_search_box_debug", return_value=search_debug):
        data = _client().post("/agent/wechat/search-debug", json={"nickname": "Aw3", "position": "right"}).json()

    assert data["screenshots"]["overlay"] == "overlay.png"


def test_search_calibration_endpoint_exists():
    with patch("app.local_agent_main.calibrate_search_box",
               return_value={"success": True, "relative_x": 145, "relative_y": 55}):
        response = _client().post("/agent/wechat/search-calibration/start")

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_search_calibration_saves_relative_coordinate():
    from app.wechat_ui import contact_searcher

    rect = {"left": 100, "top": 200, "right": 900, "bottom": 800}
    with patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_window()), \
         patch("app.wechat_ui.contact_searcher._get_window_rect_dict", return_value=rect), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.time.sleep"), \
         patch("app.wechat_ui.contact_searcher.ctypes") as mock_ctypes, \
         patch("app.wechat_ui.contact_searcher._save_search_box_calibration") as mock_save:
        point = MagicMock()
        point.x = 245
        point.y = 255
        mock_ctypes.wintypes.POINT.return_value = point
        mock_ctypes.windll.user32.GetCursorPos.return_value = 1
        result = contact_searcher.calibrate_search_box(countdown_seconds=0)

    assert result["success"] is True
    assert result["relative_x"] == 145
    assert result["relative_y"] == 55
    mock_save.assert_called_once()


def test_open_chat_requires_search_text_verified_before_enter():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "vision_search_box_rect", "confidence": 0.8}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True, "text_leaked_to_chat_input": False}) as mock_verify_text, \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is True
    assert result["search_focus"]["search_text_verified"] is True
    mock_verify_text.assert_called_once()


def test_open_chat_blocks_enter_when_search_text_not_verified():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "vision_search_box_rect", "confidence": 0.8}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": False, "text_pasted_into_search_box": False, "text_leaked_to_chat_input": False, "reason": "ocr_not_matched"}), \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "search_text_not_verified"
    assert result["manual"] is True
    assert result["sent"] is False
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Enter}" not in sent_keys
    assert "{Down}" not in sent_keys


def test_open_chat_reports_text_leaked_to_chat_input():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "vision_search_box_rect", "confidence": 0.8}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": False, "text_pasted_into_search_box": False, "text_leaked_to_chat_input": True}), \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["failure_stage"] == "search_text_not_verified"
    assert result["search_focus"]["text_leaked_to_chat_input"] is True
    assert result["sent"] is False


def test_local_agent_does_not_paste_when_verify_false_even_if_open_chat_success():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname",
               return_value=_open_chat(success=True, chat_verified=False, confidence=0.3)), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified(verified=False, manual_review_required=True)), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["success"] is False
    assert data["verify"]["verified"] is False
    assert data["action"]["pasted"] is False
    mock_write.assert_not_called()


def test_search_box_low_click_refuses_keyword_paste():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 168, "strategy": "coordinate_fallback"}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": False, "focused": False, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "search_focus_not_verified"
    assert result["manual_review_required"] is True
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Enter}" not in sent_keys
    assert "{Ctrl}v" not in sent_keys


def test_search_box_unfocused_does_not_press_enter():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit"}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": False, "focused": False, "clicked": True}), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["failure_stage"] == "search_focus_not_verified"
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Enter}" not in sent_keys
    assert "{Down}" not in sent_keys


def test_search_stage_refuses_when_focus_is_chat_input():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "coordinate_fallback"}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": False, "focused": False, "clicked": True, "text_leaked_to_chat_input": True}), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["failure_stage"] == "search_focus_not_verified"
    assert result["manual_review_required"] is True
    assert result["pasted"] is False
    assert result["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys


def test_search_debug_clicked_but_unfocused_is_not_success():
    from app.wechat_ui.contact_searcher import run_search_box_debug

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "coordinate_fallback"}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": False, "focused": False, "clicked": True, "text_pasted_into_search_box": False}), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = run_search_box_debug("Aw3")

    assert result["clicked"] is True
    assert result["focused"] is False
    assert result["verified"] is False
    assert result["success"] is False
    assert result["failure_stage"] == "search_focus_not_verified"
    mock_clipboard.assert_not_called()


def test_ocr_not_verified_keeps_local_agent_unpasted_and_unsent():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname",
               return_value=_open_chat(success=True, chat_verified=False, confidence=0.3)), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified(verified=False, manual_review_required=True, failure_stage="ocr_title_not_matched")), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["success"] is False
    assert data["verify"]["verified"] is False
    assert data["action"]["pasted"] is False
    assert data["action"]["sent"] is False
    mock_write.assert_not_called()


def test_react_has_foreground_debug_button():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "diagnoseLocalWechatForeground" in api
    assert "diagnoseLocalWechatForeground" in api
    assert "/agent/wechat/foreground-debug" in api


def test_react_displays_foreground_debug_result():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "foreground_before_process_name" in panel
    assert "foreground_after_process_name" in panel
    assert "foregroundDebug" in panel


def test_react_displays_open_chat_result():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "open_chat" in api
    assert "open_chat" in panel
    assert "chat_verified" in panel


def test_react_message_for_open_chat_failed():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "openChatFailed" in panel


def test_react_message_for_verify_failed_after_open():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "verifyFailedAfterOpen" in panel


def test_react_displays_search_debug_button():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "handleDiagnoseSearch" in panel
    assert "diagnoseLocalWechatSearch" in api
    assert "/agent/wechat/search-debug" in api


def test_react_displays_search_focus_diagnostic_fields():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "clicked?: boolean" in api
    assert "focused?: boolean" in api
    assert "text_pasted_into_search_box?: boolean" in api
    assert "text_leaked_to_chat_input?: boolean" in api
    assert "label=\"clicked\"" in panel
    assert "label=\"focused\"" in panel
    assert "text_pasted_into_search_box" in panel
    assert "text_leaked_to_chat_input" in panel


def test_react_search_debug_clicked_unfocused_is_manual_failure():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "next.success && next.verified" in panel
    assert "clicked && !searchDiagnostic.focused" in panel


def test_react_has_search_calibration_button():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "handleCalibrateSearch" in panel
    assert "startLocalWechatSearchCalibration" in api
    assert "/agent/wechat/search-calibration/start" in api


def test_react_displays_search_overlay():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "overlay?: string" in api
    assert "overlay" in panel
    assert "search_box_rect" in panel
    assert "search_text_verified" in panel
    assert "search_text_verified" in panel


def test_react_labels_open_chat_as_not_final_verification():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "open_chat" in panel
    assert "verifyFailedAfterOpen" in panel


def test_ocr_status_endpoint_exists():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": False, "engine": "easyocr"}):
        response = _client().get("/agent/ocr/status")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["engine"] == "easyocr"


def test_ocr_warmup_endpoint_returns_immediately():
    with patch("app.local_agent_main.start_ocr_warmup",
               return_value={"success": True, "started": True, "initializing": True,
                             "ocr_initialized": False}):
        data = _client().post("/agent/ocr/warmup").json()

    assert data["success"] is True
    assert data["started"] is True
    assert data["initializing"] is True


def test_ocr_warmup_prevents_duplicate_initialization():
    from app.wechat_ui import ocr_runtime

    with patch("app.wechat_ui.ocr_runtime.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": True}):
        result = ocr_runtime.start_ocr_warmup()

    assert result["success"] is True
    assert result["started"] is False
    assert result["initializing"] is True


def test_agent_test_blocks_when_ocr_not_ready():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": False}), \
         patch("app.local_agent_main.open_chat_by_nickname") as mock_open, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["success"] is False
    assert data["failure_stage"] == "ocr_not_ready"
    assert data["action"]["pasted"] is False
    assert data["action"]["sent"] is False
    mock_open.assert_not_called()
    mock_write.assert_not_called()


def test_agent_test_blocks_when_ocr_initializing():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": True}), \
         patch("app.local_agent_main.open_chat_by_nickname") as mock_open:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["success"] is False
    assert data["failure_stage"] == "ocr_initializing"
    mock_open.assert_not_called()


def test_agent_test_does_not_block_for_ocr_download():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": False}), \
         patch("app.local_agent_main.verify_current_chat_contact") as mock_verify:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["failure_stage"] == "ocr_not_ready"
    mock_verify.assert_not_called()


def test_react_displays_ocr_status():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "LocalWechatOcrStatus" in api
    assert "ocr_initialized" in panel
    assert "model_ready" in panel


def test_react_has_ocr_warmup_button():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "OCR 预热" in panel
    assert "warmupLocalWechatOcr" in api
    assert "/agent/ocr/warmup" in api


def test_react_shows_agent_test_pending_message():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "正在执行本机微信测试，请勿操作鼠标键盘" in panel
    assert "本机 Agent 仍在处理，请稍候" in panel


def test_react_shows_ocr_download_hint_after_60s():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "本机 Agent 仍在初始化 OCR" in panel
    assert "不要只复制 exe" in panel
    assert "60000" in panel


def test_react_aborts_agent_test_after_timeout():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "AbortController" in panel
    assert "180000" in panel
    assert "本机微信测试超时" in panel


def test_prepare_easyocr_models_script_exists():
    from pathlib import Path

    script = Path("scripts/prepare_easyocr_models.py")

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "easyocr.Reader" in text
    assert "resources" in text
    assert "easyocr_models" in text


def test_build_script_requires_easyocr_models():
    from pathlib import Path

    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "resources\\easyocr_models" in script
    assert "prepare_easyocr_models.py" in script
    assert "请先运行" in script


def test_build_script_copies_easyocr_models_to_dist():
    from pathlib import Path

    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "models\\easyocr" in script
    assert "Copy-Item" in script
    assert "不要只复制 exe" in script


def test_get_easyocr_model_dir_exe_mode_requires_bundled_models(tmp_path):
    from app.wechat_ui import ocr_runtime

    missing_exe = tmp_path / "agent" / "小高AI微信助手.exe"
    missing_exe.parent.mkdir()
    missing_exe.write_text("fake", encoding="utf-8")

    with patch.object(ocr_runtime, "_is_exe_mode", return_value=True), \
         patch.object(ocr_runtime, "_executable_path", return_value=missing_exe):
        result = ocr_runtime.get_easyocr_model_dir()

    assert result["success"] is False
    assert result["failure_stage"] == "ocr_model_missing"
    assert result["model_source"] == "missing"
    assert result["download_enabled"] is False


def test_ocr_status_reports_bundled_model_source(tmp_path):
    from app.wechat_ui import ocr_runtime

    model_dir = tmp_path / "resources" / "easyocr_models"
    model_dir.mkdir(parents=True)
    (model_dir / "craft_mlt_25k.pth").write_bytes(b"1")
    (model_dir / "zh_sim_g2.pth").write_bytes(b"2")

    with patch.object(ocr_runtime, "_is_exe_mode", return_value=False), \
         patch.object(ocr_runtime, "_project_model_dir", return_value=model_dir), \
         patch.object(ocr_runtime, "_easyocr_available", return_value=True):
        status = ocr_runtime.get_ocr_status()

    assert status["success"] is True
    assert status["model_source"] == "bundled"
    assert status["model_dir"] == str(model_dir)
    assert status["download_enabled"] is False
    assert status["model_files_count"] >= 2


def test_ocr_status_reports_model_missing(tmp_path):
    from app.wechat_ui import ocr_runtime

    with patch.object(ocr_runtime, "_is_exe_mode", return_value=True), \
         patch.object(ocr_runtime, "_executable_path", return_value=tmp_path / "agent.exe"), \
         patch.object(ocr_runtime, "_easyocr_available", return_value=True):
        status = ocr_runtime.get_ocr_status()

    assert status["success"] is False
    assert status["failure_stage"] == "ocr_model_missing"
    assert status["model_ready"] is False
    assert status["model_source"] == "missing"
    assert "不要只复制 exe" in status["message"]


def test_ocr_warmup_uses_bundled_model(tmp_path):
    from app.wechat_ui import ocr_runtime

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "craft_mlt_25k.pth").write_bytes(b"1")
    (model_dir / "zh_sim_g2.pth").write_bytes(b"2")

    with patch.object(ocr_runtime, "get_easyocr_model_dir",
                      return_value={"success": True, "model_dir": str(model_dir),
                                    "model_source": "bundled", "download_enabled": False,
                                    "model_files_count": 2, "model_total_size_mb": 0.0}), \
         patch.object(ocr_runtime, "_easyocr_available", return_value=True), \
         patch.object(ocr_runtime, "_start_background_initialization") as mock_start:
        result = ocr_runtime.start_ocr_warmup()

    assert result["model_source"] == "bundled"
    assert result["download_enabled"] is False
    mock_start.assert_called_once()


def test_ocr_warmup_does_not_enable_download():
    from pathlib import Path

    text = Path("app/wechat_ui/ocr_runtime.py").read_text(encoding="utf-8")

    assert "download_enabled=False" in text
    assert "model_storage_directory" in text


def test_agent_test_blocks_when_ocr_model_missing():
    with patch("app.local_agent_main.get_ocr_status",
               return_value={"success": False, "failure_stage": "ocr_model_missing",
                             "ocr_available": True, "ocr_initialized": False,
                             "model_ready": False, "initializing": False,
                             "message": "missing bundled model"}), \
         patch("app.local_agent_main.open_chat_by_nickname") as mock_open, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"}).json()

    assert data["success"] is False
    assert data["failure_stage"] == "ocr_model_missing"
    assert data["action"]["pasted"] is False
    assert data["action"]["sent"] is False
    mock_open.assert_not_called()
    mock_write.assert_not_called()


def test_react_displays_ocr_model_source():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "model_source" in api
    assert "model_dir" in api
    assert "download_enabled" in api
    assert "model_files_count" in api
    assert "model_total_size_mb" in api
    assert "model_source" in panel
    assert "download_enabled" in panel


def test_react_warns_copy_full_dist_not_only_exe():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "缺少 OCR 模型文件" in panel
    assert "不要只复制 exe" in panel
    assert "OCR 不会在测试机联网下载模型" in panel

