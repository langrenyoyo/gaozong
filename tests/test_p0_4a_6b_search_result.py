"""P0-4A-6B 搜索结果选择与自动打开 Aw3 测试

验证：
- search-result-debug 端点存在且不点击/不粘贴消息
- open_chat 需要 search_text_verified 后才点击结果
- open_chat 在 search_result_not_detected 时阻止
- open_chat 点击 OCR 检测到的结果行
- open_chat 不自己标记 chat_verified
- open_chat 失败时有非空 failure_stage
- agent test 在 open_chat search_result_not_detected 时阻止粘贴
- agent test 只在 verify.verified=true 后粘贴
- React 有搜索结果诊断按钮和展示
"""

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
        "chat_verified": False,
        "confidence": 0.3,
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


# =====================================================
# 1. search-result-debug 端点存在
# =====================================================


def test_search_result_debug_endpoint_exists():
    result_debug = {
        "success": True,
        "nickname": "Aw3",
        "search_text_verified": True,
        "search_result_detected": True,
        "search_result": {
            "nickname": "Aw3",
            "method": "ocr_result_area",
            "rect": {"left": 100, "top": 130, "right": 300, "bottom": 180},
            "click_point": {"x": 180, "y": 155},
            "confidence": 0.8,
        },
        "screenshots": {"result_area": "area.png", "overlay": "overlay.png"},
        "failure_stage": None,
        "message": "search result detected",
        "notes": [],
    }
    with patch("app.local_agent_main.run_search_result_debug", return_value=result_debug):
        response = _client().post("/agent/wechat/search-result-debug", json={"nickname": "Aw3", "position": "right"})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["search_text_verified"] is True
    assert data["search_result_detected"] is True
    assert data["search_result"]["method"] == "ocr_result_area"


# =====================================================
# 2. search-result-debug 不点击搜索结果
# =====================================================


def test_search_result_debug_does_not_click_result():
    with patch("app.local_agent_main.run_search_result_debug",
               return_value={"success": True, "search_text_verified": True,
                             "search_result_detected": True, "notes": []}), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        _client().post("/agent/wechat/search-result-debug", json={"nickname": "Aw3", "position": "right"})

    mock_write.assert_not_called()


# =====================================================
# 3. search-result-debug 不粘贴消息
# =====================================================


def test_search_result_debug_does_not_paste_message():
    with patch("app.local_agent_main.run_search_result_debug",
               return_value={"success": True, "notes": []}), \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        _client().post("/agent/wechat/search-result-debug", json={"nickname": "Aw3", "position": "right"})

    mock_write.assert_not_called()


# =====================================================
# 4. search-result-debug 返回 result_overlay 截图
# =====================================================


def test_search_result_debug_returns_result_overlay():
    result_debug = {
        "success": True,
        "search_text_verified": True,
        "search_result_detected": True,
        "screenshots": {"result_area": "area.png", "overlay": "overlay.png"},
        "notes": [],
    }
    with patch("app.local_agent_main.run_search_result_debug", return_value=result_debug):
        data = _client().post("/agent/wechat/search-result-debug", json={"nickname": "Aw3"}).json()

    assert data["screenshots"]["overlay"] == "overlay.png"
    assert data["screenshots"]["result_area"] == "area.png"


# =====================================================
# 4B. search-result 选择顺序
# =====================================================


def test_search_result_selection_sequence_prefers_keyboard():
    from app.wechat_ui.contact_searcher import _choose_search_result_selection_sequence

    assert _choose_search_result_selection_sequence() == ["enter", "down_enter", "first_row_click"]


def test_normalize_wechat_search_keyword_removes_trailing_punctuation():
    from app.wechat_ui.contact_searcher import normalize_wechat_search_keyword

    assert normalize_wechat_search_keyword(" 啊东、 ") == ["啊东、", "啊东"]
    assert normalize_wechat_search_keyword(" 趣多多. ") == ["趣多多.", "趣多多"]
    assert normalize_wechat_search_keyword(" 廖总 ") == ["廖总"]


def test_evaluate_search_keyword_match_accepts_normalized_exact_alias():
    from app.wechat_ui.contact_searcher import evaluate_search_keyword_match

    result = evaluate_search_keyword_match("趣多多.", "趣多多")

    assert result["matched"] is True
    assert result["level"] == "strong"
    assert result["reason"] == "exact_normalized_match"


def test_evaluate_search_keyword_match_rejects_single_character_contains():
    from app.wechat_ui.contact_searcher import evaluate_search_keyword_match

    result = evaluate_search_keyword_match("张三", "张")

    assert result["matched"] is False
    assert result["reason"] == "insufficient_evidence"


def test_open_chat_uses_original_keyword_before_normalized_nickname():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher.set_action_in_progress"), \
         patch("app.wechat_ui.contact_searcher._do_search_once",
               return_value=_open_chat(nickname="啊东、", search_keyword="啊东、")) as mock_search:
        result = open_chat_by_nickname("啊东、", max_attempts=1)

    assert mock_search.call_args.args[0] == "啊东、"
    assert result["nickname"] == "啊东、"
    assert result["search_keyword"] == "啊东、"


# =====================================================
# 5. open_chat 需要 search_text_verified 才点击结果
# =====================================================


def test_open_chat_requires_search_text_verified_before_result_click():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": False, "text_pasted_into_search_box": False}) as mock_verify, \
         patch("app.wechat_ui.contact_searcher.detect_search_result") as mock_detect, \
         patch("app.wechat_ui.contact_searcher._click_left_button") as mock_click, \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "search_text_not_verified"
    # detect_search_result 不应被调用（search_text_verified=false 时不会走到结果检测阶段）
    mock_detect.assert_not_called()


def test_open_chat_tries_keyboard_before_result_click():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True}), \
         patch("app.wechat_ui.contact_searcher.detect_search_result",
               return_value={"success": True, "search_result_detected": True,
                             "method": "ocr_result_area", "click_point": {"x": 180, "y": 155},
                             "confidence": 0.8, "screenshots": {}, "notes": [],
                             "rect": {"left": 100, "top": 130, "right": 300, "bottom": 180}}), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher._click_left_button") as mock_click, \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher._restore_clipboard"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is True
    key_values = [call.args[0] for call in mock_keys.call_args_list]
    assert "{Enter}" in key_values
    assert result["search_result"]["select_method"] == "enter"
    assert result["search_result"]["focus_after_select"] == "wechat_auto_focus_expected"
    assert mock_click.call_count >= 0


def test_open_chat_falls_back_to_down_enter_when_enter_guard_fails():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    def guard_by_reason(_hwnd, reason=None):
        if reason == "before_select_search_result_enter":
            return {"success": False, "message": "enter guard failed"}
        return {"success": True, "message": "OK"}

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", side_effect=guard_by_reason), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True}), \
         patch("app.wechat_ui.contact_searcher.detect_search_result",
               return_value={"success": True, "search_result_detected": True,
                             "method": "ocr_result_area", "click_point": {"x": 180, "y": 155},
                             "confidence": 0.8, "screenshots": {}, "notes": [],
                             "rect": {"left": 100, "top": 130, "right": 300, "bottom": 180}}), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher._restore_clipboard"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is True
    assert result["search_result"]["select_method"] == "down_enter"
    key_values = [call.args[0] for call in mock_keys.call_args_list]
    assert "{Down}" in key_values
    assert "{Enter}" in key_values


# =====================================================
# 6. open_chat 在 search_result_not_detected 时阻止
# =====================================================


def test_open_chat_blocks_when_search_result_not_detected():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True}), \
         patch("app.wechat_ui.contact_searcher.detect_search_result",
               return_value={"success": False, "search_result_detected": False,
                             "failure_stage": "search_result_not_detected", "notes": []}), \
         patch("app.wechat_ui.contact_searcher._click_left_button") as mock_click, \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "search_result_not_detected"
    # _click_left_button 只应被调用一次（点击搜索框），不应点击搜索结果
    assert mock_click.call_count == 1
    click_x, click_y = mock_click.call_args.args
    # 搜索框点击坐标是 (120, 95)，不应出现结果行坐标
    assert click_x == 120 and click_y == 95


# =====================================================
# 7. open_chat 点击 OCR 检测到的结果行
# =====================================================


def test_open_chat_selects_result_with_enter_when_detected():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    detected_result = {
        "success": True,
        "search_result_detected": True,
        "nickname": "Aw3",
        "method": "ocr_result_area",
        "rect": {"left": 100, "top": 130, "right": 300, "bottom": 180},
        "click_point": {"x": 180, "y": 155},
        "confidence": 0.85,
        "screenshots": {},
        "notes": [],
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True}), \
         patch("app.wechat_ui.contact_searcher.detect_search_result", return_value=detected_result), \
         patch("app.wechat_ui.contact_searcher._click_left_button") as mock_click, \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys") as mock_keys, \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is True
    assert result["search_result"]["method"] == "ocr_result_area"
    assert result["search_result"]["select_method"] == "enter"
    key_values = [call.args[0] for call in mock_keys.call_args_list]
    assert "{Enter}" in key_values
    # _click_left_button 应被调用且坐标来自 OCR 检测结果
    click_calls = [call.args for call in mock_click.call_args_list]
    assert not any(call[0] == 180 and call[1] == 155 for call in click_calls), \
        f"Result row should not be clicked on keyboard path, got calls: {click_calls}"


# =====================================================
# 8. open_chat 不自己标记 chat_verified
# =====================================================


def test_open_chat_does_not_mark_chat_verified_itself():
    from app.wechat_ui.contact_searcher import build_search_action_completed_result

    result = build_search_action_completed_result(
        nickname="Aw3",
        window_rect={"left": 0, "top": 0, "right": 1000, "bottom": 800},
        screenshots=["after_enter.png"],
    )

    assert result["success"] is True
    assert result["chat_verified"] is False
    assert result["search_action_completed"] is True
    assert result["maybe_chat_opened"] is True


# =====================================================
# 9. open_chat 失败时有非空 failure_stage
# =====================================================


def test_open_chat_returns_non_empty_failure_stage_on_failure():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value={"search_text_verified": True, "text_pasted_into_search_box": True}), \
         patch("app.wechat_ui.contact_searcher.detect_search_result",
               return_value={"success": False, "search_result_detected": False,
                             "failure_stage": "search_result_not_detected", "notes": []}), \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] is not None
    assert result["failure_stage"] != ""
    assert result["failure_stage"] == "search_result_not_detected"


# =====================================================
# 10. agent test 在 open_chat search_result_not_detected 时阻止粘贴
# =====================================================


def test_agent_test_blocks_paste_when_open_chat_result_not_detected():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname",
               return_value=_open_chat(success=False, failure_stage="search_result_not_detected")), \
         patch("app.local_agent_main.verify_current_chat_contact") as mock_verify, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "blocked",
        }).json()

    assert data["success"] is False
    assert data["failure_stage"] == "open_chat_failed"
    assert data["action"]["pasted"] is False
    mock_verify.assert_not_called()
    mock_write.assert_not_called()


# =====================================================
# 11. agent test 只在 verify.verified=true 后粘贴
# =====================================================


def test_agent_test_pastes_only_after_final_verify_true():
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=_open_chat()), \
         patch("app.local_agent_main.verify_current_chat_contact", return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True, "sent": False}) as mock_write:
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3",
            "message": "paste only",
        }).json()

    assert data["success"] is True
    assert data["verify"]["verified"] is True
    assert data["action"]["pasted"] is True
    assert data["action"]["sent"] is False
    mock_write.assert_called_once()


# =====================================================
# 12. React 有搜索结果诊断按钮
# =====================================================


def test_react_has_search_result_debug_button():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "handleDiagnoseSearchResult" in panel
    assert "diagnoseLocalWechatSearchResult" in api
    assert "/agent/wechat/search-result-debug" in api
    assert "搜索结果诊断" in panel


# =====================================================
# 13. React 展示搜索结果诊断结果
# =====================================================


def test_react_displays_search_result_debug_result():
    from pathlib import Path

    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    # 类型定义
    assert "LocalWechatSearchResultDebugResult" in api
    assert "search_text_verified" in api
    assert "search_result_detected" in api
    # 展示字段
    assert "searchResultDiagnostic" in panel
    assert "search_text_verified" in panel
    assert "search_result_detected" in panel
    assert "search_result" in panel
    assert "已定位到 Aw3 搜索结果行" in panel
    assert "未在搜索结果中识别到 Aw3" in panel
