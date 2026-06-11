"""P0-4A-6B-3 search_text_not_verified 本地复现修复测试

验证：
1. /agent/wechat/test open_chat 失败时包含 search_text_debug
2. open_chat search_text_not_verified 保留 search_text_debug
3. search_text_debug 包含 result_area_ocr_text
4. search_text_debug 包含 result_area_contains_expected
5. 策略 B 使用结果区证据通过 search_text_verified
6. 结果区不包含 expected 时阻止
7. text_leaked_to_chat_input 时阻止
8. keyword_pasted + result_area_contains_aw3 时 open_chat 通过
9. 无结果区证据时 open_chat 仍阻止
10. React 展示 open_chat search_text_debug
11. React 有复制 open_chat debug JSON 按钮
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# easyocr 是可选依赖，测试环境可能未安装
import sys

if "easyocr" not in sys.modules:
    sys.modules["easyocr"] = MagicMock()


def _easyocr():
    """获取 sys.modules 中唯一的 easyocr mock，避免跨文件隔离问题。"""
    return sys.modules["easyocr"]


def _client():
    from app.local_agent_main import create_local_agent_app
    return TestClient(create_local_agent_app(host="127.0.0.1", port=19000))


def _window(hwnd=123):
    window = MagicMock()
    window.NativeWindowHandle = hwnd
    return window


def _verified(**overrides):
    data = {
        "verified": True, "strategy": "ocr_top_title", "ocr_text": "AW3",
        "confidence": 0.9016, "partial_match": False, "manual_review_required": False,
        "failure_stage": None, "evidence": {"cropped_path": "crop.png"},
    }
    data.update(overrides)
    return data


def _open_chat(**overrides):
    data = {
        "success": True, "nickname": "Aw3", "failure_stage": None,
        "chat_verified": False, "confidence": 0.3,
        "evidence": {"screenshot": "open.png"}, "search_keyword": "Aw3",
        "opened_by": "search", "search_action_completed": True,
        "search_keyword_pasted": True, "maybe_chat_opened": True, "notes": [],
        "search_focus": None,
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _reset_easyocr():
    _easyocr().reset_mock()
    _easyocr().Reader = MagicMock()
    yield
    _easyocr().Reader = MagicMock()


# =====================================================
# 1. /agent/wechat/test open_chat 失败时包含 search_text_debug
# =====================================================


def test_agent_test_open_chat_failure_includes_search_text_debug():
    open_chat_result = _open_chat(
        success=False,
        failure_stage="search_text_not_verified",
        search_focus={
            "search_text_verified": False,
            "text_pasted_into_search_box": False,
            "search_text_debug": {
                "expected": "Aw3",
                "verified": False,
                "method": None,
                "ocr_text": "",
                "result_area_ocr_text": "Aw3",
                "result_area_contains_expected": True,
                "reason": "all_strategies_failed",
            },
        },
    )
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=open_chat_result), \
         patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": True,
                             "model_ready": True, "initializing": False, "engine": "easyocr"}), \
         patch("app.local_agent_main._check_ocr_ready_for_agent_test", return_value=None):
        data = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3", "message": "test",
        }).json()

    assert data["success"] is False
    assert data["open_chat"]["failure_stage"] == "search_text_not_verified"
    debug = data["open_chat"]["search_focus"]["search_text_debug"]
    assert debug is not None
    assert debug["expected"] == "Aw3"
    assert debug["verified"] is False


# =====================================================
# 2. open_chat search_text_not_verified 保留 search_text_debug
# =====================================================


def test_open_chat_search_text_not_verified_keeps_debug_payload():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = []  # 搜索框 OCR 空
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        # readtext 通过 side_effect 依次返回：搜索框（空） → 结果区（空）
        mock_reader.readtext.side_effect = [[], []]
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is False
    debug = result["search_text_debug"]
    assert debug is not None
    assert debug["expected"] == "Aw3"
    assert debug["verified"] is False
    assert debug["reason"] is not None


# =====================================================
# 3. search_text_debug 包含 result_area_ocr_text
# =====================================================


def test_search_text_debug_includes_result_area_ocr_text():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # 搜索框 OCR 空 → A2 失败，然后结果区 OCR 返回 "SomeOtherName"
    mock_reader.readtext.side_effect = [
        [],
        [([[10, 10], [50, 10], [50, 30], [10, 30]], "SomeOtherName", 0.8)],
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    debug = result["search_text_debug"]
    assert "result_area_ocr_text" in debug
    assert debug["result_area_ocr_text"] == "SomeOtherName"


# =====================================================
# 4. search_text_debug 包含 result_area_contains_expected
# =====================================================


def test_search_text_debug_includes_result_area_contains_expected():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # 搜索框空，结果区包含 Aw3
    mock_reader.readtext.side_effect = [
        [],
        [([[10, 10], [50, 10], [50, 30], [10, 30]], "Aw3", 0.9)],
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    debug = result["search_text_debug"]
    assert debug["result_area_contains_expected"] is True


# =====================================================
# 5. 策略 B 使用结果区证据通过 search_text_verified（UIA 失败时）
# =====================================================


def test_search_text_verified_uses_result_area_evidence_in_do_search_once():
    """P0-4A-6B-3 核心：UIA 失败 + 搜索框 OCR 失败，但结果区有 Aw3 → 组合证据通过。"""
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # 搜索框 OCR 返回空（策略 A2 失败）
    # 结果区 OCR 返回 "Aw3"（策略 B 组合证据通过）
    mock_reader.readtext.side_effect = [
        [],
        [([[10, 10], [50, 10], [50, 30], [10, 30]], "Aw3", 0.9)],
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is True
    assert result["success"] is True
    assert result["reason"] == "focused_search_box_with_result_aw3"
    assert result["search_text_debug"]["method"] == "focused_search_box_with_result_aw3"
    assert result["search_text_debug"]["verified"] is True
    assert result["search_text_debug"]["result_area_contains_expected"] is True


# =====================================================
# 6. 结果区不包含 expected 时阻止
# =====================================================


def test_search_text_verified_blocks_when_result_area_missing_expected():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # 搜索框空，结果区返回 "Xyz"（不包含 Aw3）
    mock_reader.readtext.side_effect = [
        [],
        [([[10, 10], [50, 10], [50, 30], [10, 30]], "Xyz", 0.8)],
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is False
    assert result["search_text_debug"]["result_area_contains_expected"] is False
    assert "result_area_ocr" in result["search_text_debug"]["reason"]


# =====================================================
# 7. text_leaked_to_chat_input 时阻止
# =====================================================


def test_search_text_verified_blocks_when_text_leaked_to_chat_input():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 300, "top": 600, "right": 800, "bottom": 680}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=False), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=True):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["text_leaked_to_chat_input"] is True
    assert result["search_text_verified"] is False
    # 泄漏时应直接返回，不执行策略 B
    assert result["search_text_debug"]["text_leaked_to_chat_input"] is True


# =====================================================
# 8. keyword_pasted + result_area_contains_aw3 时 open_chat 通过
# =====================================================


def test_open_chat_passes_when_keyword_pasted_and_result_area_contains_aw3():
    """P0-4A-6B-3 端到端：搜索框 OCR 失败 + 结果区有 Aw3 → open_chat 成功。"""
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    detected_result = {
        "success": True, "search_result_detected": True,
        "nickname": "Aw3", "method": "ocr_result_area",
        "rect": {"left": 100, "top": 130, "right": 300, "bottom": 180},
        "click_point": {"x": 180, "y": 155}, "confidence": 0.85,
        "screenshots": {}, "notes": [],
    }

    # verify_search_text_in_search_box 返回组合证据通过
    verify_text_result = {
        "search_text_verified": True, "text_pasted_into_search_box": True,
        "verified": True, "success": True, "failure_stage": None,
        "manual": False, "manual_review_required": False,
        "reason": "focused_search_box_with_result_aw3",
        "search_text_debug": {
            "expected": "Aw3", "verified": True,
            "method": "focused_search_box_with_result_aw3",
            "result_area_contains_expected": True,
            "result_area_ocr_text": "Aw3",
        },
    }

    with patch("app.wechat_ui.contact_searcher._check_preconditions",
               return_value=(True, "OK", {"hwnd": 123, "win_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700}, "window": _window()})), \
         patch("app.wechat_ui.contact_searcher.save_debug_screenshot", return_value="shot.png"), \
         patch("app.wechat_ui.contact_searcher.capture_wechat_region"), \
         patch("app.wechat_ui.contact_searcher.is_automation_allowed", return_value=True), \
         patch("app.wechat_ui.contact_searcher._ensure_wechat_foreground", return_value=(True, "OK")), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.wechat_ui.contact_searcher.locate_search_box_click_point",
               return_value={"success": True, "x": 120, "y": 95, "strategy": "uia_search_edit", "confidence": 0.9,
                             "search_box_rect": {"left": 100, "top": 85, "right": 300, "bottom": 110}}), \
         patch("app.wechat_ui.contact_searcher.verify_search_box_focus",
               return_value={"verified": True, "focused": True, "clicked": True, "text_leaked_to_chat_input": False}), \
         patch("app.wechat_ui.contact_searcher.verify_search_text_in_search_box",
               return_value=verify_text_result), \
         patch("app.wechat_ui.contact_searcher.detect_search_result", return_value=detected_result), \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is True
    assert result["search_keyword_pasted"] is True
    assert result["failure_stage"] is None
    # search_focus 包含 search_text_debug
    assert result["search_focus"]["search_text_debug"]["verified"] is True


# =====================================================
# 9. 无结果区证据时 open_chat 仍阻止
# =====================================================


def test_open_chat_still_blocks_without_result_evidence():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    verify_text_result = {
        "search_text_verified": False, "text_pasted_into_search_box": False,
        "verified": False, "success": False, "failure_stage": "search_text_not_verified",
        "search_text_debug": {
            "expected": "Aw3", "verified": False, "method": None,
            "result_area_contains_expected": False,
            "reason": "all_strategies_failed",
        },
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
               return_value=verify_text_result), \
         patch("app.wechat_ui.contact_searcher.detect_search_result") as mock_detect, \
         patch("app.wechat_ui.contact_searcher._click_left_button"), \
         patch("app.wechat_ui.contact_searcher._set_clipboard"), \
         patch("app.wechat_ui.contact_searcher.uia.SendKeys"), \
         patch("app.wechat_ui.contact_searcher.ctypes"), \
         patch("app.wechat_ui.contact_searcher.time.sleep"):
        result = open_chat_by_nickname("Aw3", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "search_text_not_verified"
    # detect_search_result 不应被调用
    mock_detect.assert_not_called()


# =====================================================
# 10. React 展示 open_chat search_text_debug
# =====================================================


def test_react_displays_open_chat_search_text_debug():
    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "search_text_debug" in panel
    assert "P0-4A-6B-3" in panel
    assert "result_area_ocr_text" in panel
    assert "result_area_contains_expected" in panel
    assert "text_leaked_to_chat_input" in panel
    assert "click_in_box" in panel or "click_point_inside_search_box" in panel


# =====================================================
# 11. React 有复制 open_chat debug JSON 按钮
# =====================================================


def test_react_has_copy_open_chat_debug_json():
    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    assert "复制 open_chat debug JSON" in panel
    assert "clipboard.writeText" in panel
    assert "JSON.stringify(result.open_chat" in panel
