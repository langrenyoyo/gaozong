"""P0-4A local WeChat Agent tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.encoders import jsonable_encoder
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


def _window_with_rect(hwnd=123):
    window = _window(hwnd)
    rect = MagicMock()
    rect.left = 0
    rect.top = 0
    rect.right = 880
    rect.bottom = 700
    window.BoundingRectangle = rect
    return window


def _focus_control(name="", class_name="", control_type="WindowControl",
                   rect=None):
    control = MagicMock()
    control.Name = name
    control.ClassName = class_name
    control.ControlTypeName = control_type
    bounds = MagicMock()
    rect = rect or {"left": 0, "top": 0, "right": 880, "bottom": 700}
    bounds.left = rect["left"]
    bounds.top = rect["top"]
    bounds.right = rect["right"]
    bounds.bottom = rect["bottom"]
    control.BoundingRectangle = bounds
    return control


def test_check_preconditions_uses_public_foreground_guard_success():
    from app.wechat_ui import contact_searcher

    with patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_window_with_rect()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_workspace_layout",
               return_value={"layout_ok": True}), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "legacy")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground",
               return_value={"success": True}) as mock_guard, \
         patch("app.wechat_ui.contact_searcher.set_action_in_progress"):
        ok, msg, ctx = contact_searcher._check_preconditions()

    assert ok is True
    assert ctx["hwnd"] == 123
    assert ctx["win_rect"] == {"left": 0, "top": 0, "right": 880, "bottom": 700}
    mock_guard.assert_called_once_with(123, reason="open_chat_preconditions")


def test_check_preconditions_public_foreground_guard_failure_has_diagnostics():
    from app.wechat_ui import contact_searcher

    foreground_guard = {
        "success": False,
        "message": "微信前台焦点恢复失败",
        "foreground_debug": {"reason": "open_chat_preconditions", "attempts": []},
    }

    with patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_window_with_rect()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_workspace_layout",
               return_value={"layout_ok": True}), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "legacy")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground",
               return_value=foreground_guard), \
         patch("app.wechat_ui.contact_searcher.set_action_in_progress") as mock_in_progress:
        ok, msg, ctx = contact_searcher._check_preconditions()

    assert ok is False
    assert msg == "微信前台焦点恢复失败"
    assert ctx["failure_stage"] == "foreground_lost_preconditions"
    assert ctx["foreground_guard"] == foreground_guard
    assert ctx["foreground_debug"] == foreground_guard["foreground_debug"]
    assert ctx["window"].NativeWindowHandle == 123
    mock_in_progress.assert_not_called()


def test_do_search_once_passes_precondition_foreground_diagnostics():
    from app.wechat_ui import contact_searcher

    foreground_guard = {
        "success": False,
        "message": "微信前台焦点恢复失败",
        "foreground_debug": {"reason": "open_chat_preconditions"},
    }
    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(False, "微信前台焦点恢复失败", {
                   "failure_stage": "foreground_lost_preconditions",
                   "foreground_guard": foreground_guard,
                   "foreground_debug": foreground_guard["foreground_debug"],
               })), \
         patch("app.wechat_ui.contact_searcher._save_failure_screenshot"):
        result = contact_searcher._do_search_once("Aw3", attempt=1, safe_nick="Aw3")

    assert result["success"] is False
    assert result["failure_stage"] == "foreground_lost_preconditions"
    assert result["foreground_guard"] == foreground_guard
    assert result["foreground_debug"] == foreground_guard["foreground_debug"]


def test_open_chat_foreground_lost_preconditions_does_not_click_paste_or_send():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    foreground_guard = {"success": False, "foreground_debug": {"reason": "open_chat_preconditions"}}
    with patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(False, "微信前台焦点恢复失败", {
                   "failure_stage": "foreground_lost_preconditions",
                   "foreground_guard": foreground_guard,
                   "foreground_debug": foreground_guard["foreground_debug"],
               })), \
         patch("app.wechat_ui.contact_searcher._save_failure_screenshot"), \
         patch("app.wechat_ui.contact_searcher._click_left_button") as mock_click, \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys:
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "foreground_lost_preconditions"
    assert result["sent"] is False
    assert result["pasted"] is False
    mock_click.assert_not_called()
    mock_clipboard.assert_not_called()
    mock_keys.assert_not_called()


def test_local_agent_test_passes_open_chat_foreground_lost_preconditions():
    open_result = _open_chat(
        success=False,
        failure_stage="foreground_lost_preconditions",
        sent=False,
        pasted=False,
    )
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=open_result), \
         patch("app.local_agent_main.verify_current_chat_contact") as mock_verify, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "open_chat_failed"
    assert data["open_chat"]["failure_stage"] == "foreground_lost_preconditions"
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False
    mock_verify.assert_not_called()
    mock_write.assert_not_called()


def test_verify_search_box_focus_chat_input_region_reports_diagnostics():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "manual_calibration",
        "confidence": 0.7,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
        "evidence": {"source": "manual"},
    }
    chat_control = _focus_control(
        name="",
        class_name="",
        control_type="EditControl",
        rect={"left": 320, "top": 520, "right": 850, "bottom": 680},
    )

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=chat_control), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        focus = contact_searcher.verify_search_box_focus(123, win_rect, click_point)

    assert focus["verified"] is False
    assert focus["text_leaked_to_chat_input"] is True
    assert focus["focus_control_rect_in_chat_input_region"] is True
    assert focus["focus_control_rect_in_search_region"] is False
    assert focus["click_point_inside_search_box"] is True
    assert focus["search_box_rect"] == click_point["search_box_rect"]
    assert focus["focus_control_type"] == "EditControl"


def test_verify_search_box_focus_window_control_never_passes():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    window_control = _focus_control(
        name="微信",
        class_name="Qt51514QWindowIcon",
        control_type="WindowControl",
        rect=win_rect,
    )

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=window_control), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        focus = contact_searcher.verify_search_box_focus(123, win_rect, {
            "success": True,
            "x": 120,
            "y": 95,
            "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        })

    assert focus["verified"] is False
    assert focus["success"] is False
    assert focus["reason"] == "focused_control_not_search_box"
    assert focus["focus_control_type"] == "WindowControl"
    assert all(not item["looks_like_search"] for item in focus["focus_poll_attempts"])


def test_verify_search_box_focus_poll_succeeds_only_for_search_control():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    window_control = _focus_control(
        name="微信",
        class_name="Qt51514QWindowIcon",
        control_type="WindowControl",
        rect=win_rect,
    )
    search_control = _focus_control(
        name="Search",
        class_name="",
        control_type="EditControl",
        rect={"left": 80, "top": 75, "right": 250, "bottom": 115},
    )

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=[window_control, search_control]), \
         patch("app.wechat_ui.contact_searcher.time.sleep") as mock_sleep:
        focus = contact_searcher.verify_search_box_focus(123, win_rect, {
            "success": True,
            "x": 120,
            "y": 95,
            "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        })

    assert focus["verified"] is True
    assert focus["success"] is True
    assert focus["focused"] is True
    assert focus["reason"] == "focused_control_matches_search_region"
    assert len(focus["focus_poll_attempts"]) == 2
    mock_sleep.assert_called()


def test_verify_search_box_focus_poll_all_failures_keeps_guard():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    window_control = _focus_control(
        name="微信",
        class_name="Qt51514QWindowIcon",
        control_type="WindowControl",
        rect=win_rect,
    )

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=window_control), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        focus = contact_searcher.verify_search_box_focus(123, win_rect, {
            "success": True,
            "x": 120,
            "y": 95,
            "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        })

    assert focus["verified"] is False
    assert focus["failure_stage"] == "search_focus_not_verified"
    assert focus["manual_review_required"] is True
    assert len(focus["focus_poll_attempts"]) == 4


def test_open_chat_focus_failure_returns_click_point_diagnostics_without_paste_or_send():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "manual_calibration",
        "confidence": 0.7,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
        "evidence": {"source": "manual"},
    }
    focus = {
        "verified": False,
        "focused": False,
        "clicked": True,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "reason": "focused_control_not_search_box",
        "focus_control": {
            "name": "微信",
            "class_name": "Qt51514QWindowIcon",
            "control_type": "WindowControl",
            "rect": win_rect,
        },
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": win_rect, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point", return_value=click_point), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus", return_value=focus), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["failure_stage"] == "search_focus_not_verified"
    assert result["search_focus"]["click_point"]["x"] == click_point["x"]
    assert result["search_focus"]["click_point"]["y"] == click_point["y"]
    assert result["search_focus"]["click_point"]["strategy"] == click_point["strategy"]
    assert result["search_focus"]["click_point"]["confidence"] == click_point["confidence"]
    assert result["search_focus"]["click_point"]["source"] == "manual"
    assert result["search_focus"]["search_box_rect"] == click_point["search_box_rect"]
    assert result["search_focus"]["click_point_inside_search_box"] is True
    assert result["search_focus"]["focus_control_type"] == "WindowControl"
    assert result["pasted"] is False
    assert result["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys
    assert "{Enter}" not in sent_keys


def test_open_chat_focus_failure_sanitizes_recursive_locator_attempts():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "uia_search_edit",
        "confidence": 0.9,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
        "evidence": {"source": "uia"},
    }
    click_point["locator_attempts"] = {"uia_attempt": click_point}
    focus = {
        "verified": False,
        "focused": False,
        "clicked": True,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "reason": "focused_control_not_search_box",
        "focus_control": {
            "name": "微信",
            "class_name": "Qt51514QWindowIcon",
            "control_type": "WindowControl",
            "rect": win_rect,
        },
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": win_rect, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point", return_value=click_point), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus", return_value=focus), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    encoded = jsonable_encoder(result)
    sanitized = encoded["search_focus"]["click_point"]
    assert sanitized["strategy"] == "uia_search_edit"
    assert sanitized["confidence"] == 0.9
    assert sanitized["search_box_rect"] == click_point["search_box_rect"]
    assert sanitized["locator_attempts"]["uia_attempt"]["strategy"] == "uia_search_edit"
    assert "locator_attempts" not in sanitized["locator_attempts"]["uia_attempt"]
    assert result["pasted"] is False
    assert result["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys
    assert "{Enter}" not in sent_keys


def test_open_chat_focus_failure_returns_non_uia_focus_diagnostics():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "manual_calibration",
        "confidence": 0.7,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
        "evidence": {"source": "manual"},
    }
    focus = {
        "verified": False,
        "focused": False,
        "clicked": True,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "reason": "focused_control_not_search_box",
        "focus_control": {
            "name": "微信",
            "class_name": "Qt51514QWindowIcon",
            "control_type": "WindowControl",
            "rect": win_rect,
        },
        "focus_poll_search_box_crop_paths": ["poll0.png", "poll200.png"],
        "focus_poll_image_diffs": [0.0, 1.2],
    }
    caret_debug = {
        "caret_available": False,
        "caret_unavailable_reason": "GetGUIThreadInfo unavailable",
        "caret_hwnd": None,
        "caret_rect": None,
        "caret_in_search_box": False,
        "caret_in_chat_input": False,
    }
    uia_tree_summary = {
        "root_name": "微信",
        "root_class_name": "Qt51514QWindowIcon",
        "root_control_type": "WindowControl",
        "root_rect": win_rect,
        "uia_tree_child_count": 0,
        "matched_edit_count": 0,
        "matched_search_count": 0,
        "matched_controls": [],
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": win_rect, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point", return_value=click_point), \
         patch("app.wechat_ui.contact_searcher._save_search_box_focus_crop",
               side_effect=["before_crop.png", "after_crop.png"]), \
         patch("app.wechat_ui.contact_searcher._compare_image_paths", return_value=7.5), \
         patch("app.wechat_ui.contact_searcher._search_box_visual_state",
               return_value={"placeholder_visible": True, "border_active_hint": False,
                             "caret_visual_hint": False, "search_panel_expanded_hint": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus", return_value=focus), \
         patch("app.wechat_ui.contact_searcher._get_gui_thread_caret_debug", return_value=caret_debug), \
         patch("app.wechat_ui.contact_searcher._collect_uia_tree_summary", return_value=uia_tree_summary), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    focus_result = result["search_focus"]
    assert focus_result["before_search_box_crop_path"] == "before_crop.png"
    assert focus_result["after_search_box_crop_path"] == "after_crop.png"
    assert focus_result["focus_poll_search_box_crop_paths"] == ["poll0.png", "poll200.png"]
    assert focus_result["crop_rect"]["left"] <= click_point["search_box_rect"]["left"]
    assert focus_result["crop_rect"]["top"] <= click_point["search_box_rect"]["top"]
    assert focus_result["crop_rect"]["right"] >= click_point["search_box_rect"]["right"]
    assert focus_result["crop_rect"]["bottom"] >= click_point["search_box_rect"]["bottom"]
    assert focus_result["click_point"]["x"] == 120
    assert focus_result["search_box_rect"] == click_point["search_box_rect"]
    assert focus_result["image_diff_score"] == 7.5
    assert focus_result["focus_poll_image_diffs"] == [0.0, 1.2]
    assert focus_result["placeholder_visible"] is True
    assert focus_result["border_active_hint"] is False
    assert focus_result["caret_visual_hint"] is False
    assert focus_result["search_panel_expanded_hint"] is False
    assert focus_result["caret_available"] is False
    assert focus_result["caret_unavailable_reason"] == "GetGUIThreadInfo unavailable"
    assert focus_result["uia_tree_summary"]["uia_tree_child_count"] == 0
    jsonable_encoder(focus_result)
    assert result["pasted"] is False
    assert result["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys
    assert "{Enter}" not in sent_keys


def test_click_left_button_returns_click_debug():
    from app.wechat_ui import contact_searcher

    positions = [
        (10, 20),
        (120, 95),
        (120, 95),
        (120, 95),
    ]
    foregrounds = [321, 321, 321, 321, 321]
    rects = [
        {"left": 0, "top": 0, "right": 880, "bottom": 700},
        {"left": 0, "top": 0, "right": 880, "bottom": 700},
    ]

    with patch("app.wechat_ui.contact_searcher._get_cursor_pos_debug", side_effect=positions), \
         patch("app.wechat_ui.contact_searcher._foreground_window_debug", side_effect=[
             {"hwnd": hwnd, "title": "微信", "class": "Qt51514QWindowIcon", "process_name": "WeChat.exe"}
             for hwnd in foregrounds
         ]), \
         patch("app.wechat_ui.contact_searcher._safe_window_rect_debug", side_effect=rects), \
         patch("app.wechat_ui.contact_searcher._click_integrity_debug", return_value={
             "agent_integrity_level": "medium",
             "wechat_integrity_level": "medium",
             "integrity_level_mismatch": False,
             "integrity_unavailable_reason": None,
         }), \
         patch("app.wechat_ui.contact_searcher.ctypes") as mock_ctypes, \
         patch("app.wechat_ui.contact_searcher.time.time", side_effect=[100.0, 100.02, 100.05]):
        mock_ctypes.windll.user32.SetCursorPos.return_value = 1

        debug = contact_searcher._click_left_button(120, 95, hwnd=321)

    assert debug["click_method"] == "SetCursorPos+mouse_event"
    assert debug["target_x"] == 120
    assert debug["target_y"] == 95
    assert debug["set_cursor_pos_ok"] is True
    assert debug["cursor_before"] == {"x": 10, "y": 20}
    assert debug["cursor_after_set"] == {"x": 120, "y": 95}
    assert debug["cursor_after_down"] == {"x": 120, "y": 95}
    assert debug["cursor_after_up"] == {"x": 120, "y": 95}
    assert debug["foreground_before_click"]["hwnd"] == 321
    assert debug["foreground_after_click"]["hwnd"] == 321
    assert debug["window_rect_before_click"] == rects[0]
    assert debug["window_rect_after_click"] == rects[1]
    assert debug["agent_integrity_level"] == "medium"
    assert debug["wechat_integrity_level"] == "medium"
    assert debug["integrity_level_mismatch"] is False
    assert debug["click_exception"] is None
    assert debug["click_duration_ms"] == 50
    assert debug["down_up_interval_ms"] == 30
    jsonable_encoder(debug)


def test_click_left_button_reports_set_cursor_pos_failure_and_integrity_unavailable():
    from app.wechat_ui import contact_searcher

    with patch("app.wechat_ui.contact_searcher._get_cursor_pos_debug", return_value={"x": 1, "y": 2}), \
         patch("app.wechat_ui.contact_searcher._foreground_window_debug", return_value={
             "hwnd": 999,
             "title": "Code",
             "class": "Chrome_WidgetWin_1",
             "process_name": "Code.exe",
         }), \
         patch("app.wechat_ui.contact_searcher._safe_window_rect_debug", return_value=None), \
         patch("app.wechat_ui.contact_searcher._click_integrity_debug", return_value={
             "agent_integrity_level": None,
             "wechat_integrity_level": None,
             "integrity_level_mismatch": None,
             "integrity_unavailable_reason": "OpenProcessToken failed",
         }), \
         patch("app.wechat_ui.contact_searcher.ctypes") as mock_ctypes, \
         patch("app.wechat_ui.contact_searcher.time.time", side_effect=[1.0, 1.0, 1.0]):
        mock_ctypes.windll.user32.SetCursorPos.return_value = 0
        mock_ctypes.get_last_error.return_value = 5

        debug = contact_searcher._click_left_button(120, 95, hwnd=321)

    assert debug["set_cursor_pos_ok"] is False
    assert debug["set_cursor_pos_last_error"] == 5
    assert debug["integrity_unavailable_reason"] == "OpenProcessToken failed"
    jsonable_encoder(debug)


def test_open_chat_focus_failure_includes_click_debug_without_paste_or_send():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "manual_calibration",
        "confidence": 0.7,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
    }
    focus = {
        "verified": False,
        "focused": False,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "reason": "focused_control_not_search_box",
        "focus_control": {"rect": win_rect, "control_type": "WindowControl"},
    }
    click_debug = {
        "click_method": "SetCursorPos+mouse_event",
        "target_x": 120,
        "target_y": 95,
        "set_cursor_pos_ok": True,
        "cursor_after_set": {"x": 120, "y": 95},
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": win_rect, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground",
               return_value=(False, "foreground is Code")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point", return_value=click_point), \
         patch("app.wechat_ui.contact_searcher._click_left_button", return_value=click_debug), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus", return_value=focus), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    focus_result = result["search_focus"]
    assert focus_result["click_debug"]["click_method"] == "SetCursorPos+mouse_event"
    assert focus_result["click_debug"]["target_x"] == 120
    assert focus_result["click_debug"]["target_y"] == 95
    assert focus_result["click_debug"]["legacy_foreground_ok"] is False
    assert focus_result["click_debug"]["legacy_foreground_diag"] == "foreground is Code"
    jsonable_encoder(focus_result["click_debug"])
    assert result["search_keyword_pasted"] is False
    assert result["pasted"] is False
    assert result["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys
    assert "{Enter}" not in sent_keys


def test_caret_in_search_box_is_diagnostic_only_for_focus_failure():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    focus = {
        "verified": False,
        "success": False,
        "focus_control": {"rect": win_rect, "control_type": "WindowControl"},
    }
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
    }
    caret_debug = {
        "caret_available": True,
        "caret_unavailable_reason": None,
        "caret_hwnd": 456,
        "caret_rect": {"left": 100, "top": 80, "right": 102, "bottom": 98},
        "caret_in_search_box": True,
        "caret_in_chat_input": False,
    }

    enriched = contact_searcher._augment_focus_failure_evidence(
        focus,
        hwnd=123,
        win_rect=win_rect,
        click_point=click_point,
        safe_nick="Aw3",
        before_crop_path=None,
        after_crop_path=None,
        image_diff_score=None,
        caret_debug=caret_debug,
        uia_tree_summary={"uia_tree_child_count": 0, "matched_controls": []},
    )

    assert enriched["verified"] is False
    assert enriched["success"] is False
    assert enriched["caret_in_search_box"] is True
    assert enriched["caret_in_chat_input"] is False


def test_caret_in_chat_input_is_reported_as_diagnostic():
    from app.wechat_ui import contact_searcher

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    search_box_rect = {"left": 80, "top": 75, "right": 250, "bottom": 115}
    caret_debug = contact_searcher._caret_debug_from_rect(
        {"left": 400, "top": 610, "right": 402, "bottom": 630},
        caret_hwnd=456,
        win_rect=win_rect,
        search_box_rect=search_box_rect,
    )

    assert caret_debug["caret_available"] is True
    assert caret_debug["caret_in_search_box"] is False
    assert caret_debug["caret_in_chat_input"] is True


def test_uia_tree_summary_is_json_safe_without_raw_controls():
    from app.wechat_ui import contact_searcher

    root_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    edit_rect = {"left": 80, "top": 75, "right": 250, "bottom": 115}
    root = _focus_control(name="微信", class_name="Qt51514QWindowIcon",
                          control_type="WindowControl", rect=root_rect)
    edit = _focus_control(name="搜索", class_name="", control_type="EditControl", rect=edit_rect)
    root.GetChildren.return_value = [edit]
    edit.GetChildren.return_value = []

    with patch("app.wechat_ui.contact_searcher.uia.ControlFromHandle", return_value=root):
        summary = contact_searcher._collect_uia_tree_summary(123, root_rect)

    assert summary["root_control_type"] == "WindowControl"
    assert summary["uia_tree_child_count"] == 1
    assert summary["matched_edit_count"] == 1
    assert summary["matched_search_count"] == 1
    assert summary["matched_controls"][0]["control_type"] == "EditControl"
    assert "GetChildren" not in jsonable_encoder(summary)["matched_controls"][0]


def test_vision_failure_returns_candidate_diagnostics():
    from app.wechat_ui import contact_searcher

    class _FakeGrayImage:
        size = (180, 40)

        def load(self):
            return self

        def __getitem__(self, point):
            x, y = point
            if 5 <= x <= 124 and 8 <= y <= 29:
                return 240
            return 0

    class _FakeImage:
        def convert(self, mode):
            return _FakeGrayImage()

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    with patch("app.wechat_ui.contact_searcher.grab_screen", return_value=_FakeImage()):
        result = contact_searcher._locate_search_box_by_vision(123, win_rect)

    assert result["success"] is False
    assert result["reason"] == "search_box_size_not_matched"
    assert result["candidate_count"] >= 1
    assert result["candidate_rects"]
    assert result["candidate_sizes"][0]["width"] == 120
    assert result["expected_width_range"] == [130, 200]
    assert result["expected_height_range"] == [20, 42]
    assert result["rejected_reasons"]
    assert result["closest_candidate"] is not None


def test_agent_wechat_test_returns_json_when_search_focus_diagnostics_are_recursive():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname
    from app.local_agent_main import create_local_agent_app

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {
        "success": True,
        "x": 120,
        "y": 95,
        "strategy": "uia_search_edit",
        "confidence": 0.9,
        "search_box_rect": {"left": 80, "top": 75, "right": 250, "bottom": 115},
        "candidate_region": {"left": 0, "top": 40, "right": 260, "bottom": 135},
        "window_rect": win_rect,
        "evidence": {"source": "uia"},
    }
    click_point["locator_attempts"] = {"uia_attempt": click_point}
    focus = {
        "verified": False,
        "focused": False,
        "clicked": True,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "reason": "focused_control_not_search_box",
        "focus_control": {
            "name": "微信",
            "class_name": "Qt51514QWindowIcon",
            "control_type": "WindowControl",
            "rect": win_rect,
        },
    }
    app = create_local_agent_app(host="127.0.0.1", port=19000)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("app.local_agent_main.get_ocr_status",
               return_value={"ocr_available": True, "model_ready": True, "ocr_initialized": True}), \
         patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": win_rect, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.save_search_box_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point", return_value=click_point), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus", return_value=focus), \
         patch("app.wechat_ui.contact_searcher._set_clipboard") as mock_clipboard, \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        response = client.post("/agent/wechat/test", json={"nickname": "Aw3", "message": "blocked"})

    assert response.status_code == 200
    data = response.json()
    assert data["failure_stage"] == "open_chat_failed"
    assert data["open_chat"]["failure_stage"] == "search_focus_not_verified"
    assert data["open_chat"]["search_focus"]["click_point"]["locator_attempts"]["uia_attempt"]["success"] is True
    assert "locator_attempts" not in data["open_chat"]["search_focus"]["click_point"]["locator_attempts"]["uia_attempt"]
    assert data["open_chat"]["search_keyword_pasted"] is False
    assert data["action"]["pasted"] is False
    assert data["action"]["sent"] is False
    mock_clipboard.assert_not_called()
    sent_keys = [call.args[0] for call in mock_keys.call_args_list if call.args]
    assert "{Ctrl}v" not in sent_keys
    assert "{Enter}" not in sent_keys


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
         patch("app.wechat_ui.contact_searcher.detect_search_result",
               return_value={"success": True, "search_result_detected": True,
                             "method": "ocr_result_area",
                             "click_point": {"x": 180, "y": 155},
                             "confidence": 0.85, "screenshots": {}}), \
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

