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


def test_search_text_verified_uses_digit_anchor_for_chinese_nickname_result_area():
    """长中文昵称 OCR 漏字时，结果区数字锚点完整命中 + 中文局部证据应可通过。"""
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_reader = MagicMock()
    mock_reader.readtext.side_effect = [
        [],
        [(
            [[10, 10], [460, 10], [460, 40], [10, 40]],
            "A生177020658 搜n网绛结果 4张生177020558 群职 高总内部系巯定制内部群 包含;4张生177020658",
            0.82,
        )],
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
            hwnd=123, win_rect=win_rect, expected_text="A张生177020658", click_point=click_point,
        )

    match = result["search_text_debug"]["result_area_match"]
    assert result["search_text_verified"] is True
    assert result["success"] is True
    assert result["search_text_debug"]["result_area_contains_expected"] is True
    assert match["matched"] is True
    assert match["level"] == "strong"
    assert match["evidence"]["digits_full_match"] is True


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


# =====================================================
# 12. P0-4A-6B-3T-D: 策略 A2 readtext 传入 numpy.ndarray 而非 PIL.Image
# =====================================================


def test_strategy_a2_passes_numpy_ndarray_to_readtext():
    """验证 verify_search_text_in_search_box 策略 A2 调用 readtext 时传入 numpy.ndarray。"""
    import numpy as np
    from unittest.mock import call
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = []  # 搜索框 OCR 空
    _easyocr().Reader.return_value = mock_reader

    # 构造一个真实 PIL.Image 作为 grab_screen 返回值
    from PIL import Image
    fake_image = Image.new("RGB", (200, 30), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    # readtext 至少被调用 2 次（策略 A2 + 策略 B）
    assert mock_reader.readtext.call_count >= 1
    # 第一次调用（策略 A2）的参数必须是 numpy.ndarray
    first_arg = mock_reader.readtext.call_args_list[0][0][0]
    assert isinstance(first_arg, np.ndarray), f"策略 A2 readtext 入参类型={type(first_arg)}，期望 numpy.ndarray"


# =====================================================
# 13. P0-4A-6B-3T-D: 策略 B readtext 传入 numpy.ndarray 而非 PIL.Image
# =====================================================


def test_strategy_b_passes_numpy_ndarray_to_readtext():
    """验证 verify_search_text_in_search_box 策略 B 调用 readtext 时传入 numpy.ndarray。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_reader = MagicMock()
    # 策略 A2 返回空（不匹配）→ 进入策略 B → 策略 B 也返回空
    mock_reader.readtext.side_effect = [
        [],  # 策略 A2：搜索框 OCR 空
        [],  # 策略 B：结果区 OCR 空
    ]
    _easyocr().Reader.return_value = mock_reader

    from PIL import Image
    fake_image = Image.new("RGB", (200, 30), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    # readtext 被调用 2 次（策略 A2 + 策略 B）
    assert mock_reader.readtext.call_count == 2
    # 第二次调用（策略 B）的参数必须是 numpy.ndarray
    second_arg = mock_reader.readtext.call_args_list[1][0][0]
    assert isinstance(second_arg, np.ndarray), f"策略 B readtext 入参类型={type(second_arg)}，期望 numpy.ndarray"
    # 安全失败
    assert result["search_text_verified"] is False


# =====================================================
# 14. P0-4A-6B-3T-D: detect_search_result readtext 传入 numpy.ndarray
# =====================================================


def test_detect_search_result_passes_numpy_ndarray_to_readtext():
    """验证 detect_search_result 调用 readtext 时传入 numpy.ndarray。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import detect_search_result

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = []  # 无 OCR 结果
    _easyocr().Reader.return_value = mock_reader

    from PIL import Image
    fake_image = Image.new("RGB", (400, 300), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}

    with patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
         patch("app.wechat_ui.contact_searcher._save_result_region_screenshot", return_value="result.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_result_overlay", return_value="overlay.png"):
        result = detect_search_result(123, win_rect, "Aw3")

    # readtext 被调用 1 次
    assert mock_reader.readtext.call_count == 1
    first_arg = mock_reader.readtext.call_args_list[0][0][0]
    assert isinstance(first_arg, np.ndarray), f"detect_search_result readtext 入参类型={type(first_arg)}，期望 numpy.ndarray"


# =====================================================
# 15. P0-4A-6B-3T-D: OCR 异常时仍安全失败，不进入成功
# =====================================================


def test_ocr_exception_still_safely_fails():
    """验证 readtext 抛异常时，verify_search_text_in_search_box 安全失败。"""
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_reader = MagicMock()
    # 策略 A2 抛异常
    mock_reader.readtext.side_effect = TypeError("Invalid input type")
    _easyocr().Reader.return_value = mock_reader

    from PIL import Image
    fake_image = Image.new("RGB", (200, 30), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    # 安全失败
    assert result["search_text_verified"] is False
    assert result["verified"] is False
    assert result["success"] is False
    assert result["manual_review_required"] is True
    # search_text_debug.reason 包含 OCR 异常信息（策略 A2 或策略 B 的 except 捕获）
    debug_reason = result["search_text_debug"].get("reason") or ""
    assert "Invalid input type" in debug_reason or "ocr_check_failed" in debug_reason, \
        f"期望包含 OCR 异常信息，实际: {debug_reason}"


# =====================================================
# 16. P0-4A-6B-3T-D: search_text_debug 字段在修复后仍完整
# =====================================================


def test_search_text_debug_fields_still_present_after_fix():
    """修复后 search_text_debug 仍保留所有诊断字段。"""
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_reader = MagicMock()
    mock_reader.readtext.side_effect = [
        [],  # 策略 A2 空
        [],  # 策略 B 空
    ]
    _easyocr().Reader.return_value = mock_reader

    from PIL import Image
    fake_image = Image.new("RGB", (200, 30), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
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
    assert debug["search_box_crop_path"] == "crop.png"
    assert debug["expected"] == "Aw3"
    assert debug["verified"] is False
    assert debug["reason"] is not None
    # 策略 B 也应执行过
    assert "result_area_ocr_text" in debug


# =====================================================
# 17. P0-4A-6B-3T-D: _pil_to_ndarray 对 numpy 输入直接返回
# =====================================================


def test_pil_to_ndarray_passthrough_numpy():
    """验证 _pil_to_ndarray 对已经是 numpy 的输入直接返回。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import _pil_to_ndarray

    arr = np.zeros((30, 200, 3), dtype=np.uint8)
    result = _pil_to_ndarray(arr)
    assert result is arr, "numpy 输入应直接返回原对象"


def test_pil_to_ndarray_converts_pil_image():
    """验证 _pil_to_ndarray 正确转换 PIL.Image 为 numpy。"""
    import numpy as np
    from PIL import Image
    from app.wechat_ui.contact_searcher import _pil_to_ndarray

    img = Image.new("RGBA", (200, 30), color=(255, 0, 0, 255))
    result = _pil_to_ndarray(img)
    assert isinstance(result, np.ndarray)
    assert result.shape == (30, 200, 3), f"形状应为 (30, 200, 3)，实际 {result.shape}"
    assert result.dtype == np.uint8


# =====================================================
# 18. P0-4A-6B-3T-D: _pil_to_ndarray 对 numpy 输入直接返回
# =====================================================
# （注：上面 test 17 已有两个 _pil_to_ndarray 测试，此处接续编号 19）

# =====================================================
# 19. P0-4A-6B-3U-D: ocr_items bbox 坐标为 Python int 而非 numpy.int32
# =====================================================


def test_ocr_items_bbox_is_python_int_not_numpy():
    """验证 EasyOCR 返回 numpy 标量后，ocr_items bbox 全部为 Python int。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    # 模拟 EasyOCR 返回包含 numpy 标量的 bbox
    mock_reader = MagicMock()
    numpy_bbox = [
        np.array([np.int32(10), np.int32(20)]),
        np.array([np.int32(50), np.int32(20)]),
        np.array([np.int32(50), np.int32(40)]),
        np.array([np.int32(10), np.int32(40)]),
    ]
    mock_reader.readtext.side_effect = [
        # 策略 A2：搜索框 OCR 返回含 numpy 标量的结果
        [(numpy_bbox, "Aw3", np.float32(0.91))],
        # 策略 B：结果区 OCR 空（跳过）
        [],
    ]
    _easyocr().Reader.return_value = mock_reader

    from PIL import Image
    fake_image = Image.new("RGB", (200, 30), color=(255, 255, 255))

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl",
               side_effect=Exception("Qt5 UIA fail")), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=fake_image), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    ocr_items = result["search_text_debug"]["ocr_items"]
    assert len(ocr_items) >= 1, "ocr_items 应至少有 1 条 OCR 结果"

    for i, item in enumerate(ocr_items):
        # text 必须是 str
        assert isinstance(item["text"], str), f"ocr_items[{i}].text 类型={type(item['text'])}，期望 str"
        # confidence 必须是 float
        assert isinstance(item["confidence"], float), f"ocr_items[{i}].confidence 类型={type(item['confidence'])}，期望 float"
        # bbox 必须是嵌套 list，内部全部是 Python int
        assert isinstance(item["bbox"], list), f"ocr_items[{i}].bbox 类型={type(item['bbox'])}，期望 list"
        for j, point in enumerate(item["bbox"]):
            assert isinstance(point, list), f"ocr_items[{i}].bbox[{j}] 类型={type(point)}，期望 list"
            for k, coord in enumerate(point):
                assert isinstance(coord, int), \
                    f"ocr_items[{i}].bbox[{j}][{k}] 类型={type(coord).__name__}（值={coord}），期望 Python int"
                assert not isinstance(coord, np.integer), \
                    f"ocr_items[{i}].bbox[{j}][{k}] 仍是 numpy 类型 {type(coord).__name__}"


# =====================================================
# 20. P0-4A-6B-3U-D: _json_safe_debug_value 处理 numpy 标量
# =====================================================


def test_evaluate_search_keyword_match_handles_chinese_digit_ocr_confusion():
    """长中文昵称在结果区 OCR 出现漏字和 A/4 混淆时，数字锚点 + 中文部分证据应可通过。"""
    from app.wechat_ui.contact_searcher import evaluate_search_keyword_match

    result = evaluate_search_keyword_match(
        expected_text="A张生177020658",
        ocr_text="A生177020658 搜n网绛结果 4张生177020558 群职 高总内部系巯定制内部群 包含;4张生177020658",
    )

    assert result["matched"] is True
    assert result["level"] == "strong"
    assert result["evidence"]["digits_full_match"] is True
    assert result["evidence"]["chinese_core_match_count"] >= 1
    assert result["evidence"]["prefix_confusable_match"] is True


def test_evaluate_search_keyword_match_rejects_wrong_digit_anchor():
    """数字锚点不一致时，即使中文局部相似也不能强行通过。"""
    from app.wechat_ui.contact_searcher import evaluate_search_keyword_match

    result = evaluate_search_keyword_match(
        expected_text="A张生177020658",
        ocr_text="A张生177020558 搜索结果",
    )

    assert result["matched"] is False
    assert result["level"] in {"weak", "none"}


def test_json_safe_debug_value_handles_numpy_scalars():
    """验证 _json_safe_debug_value 将 numpy 标量转为 Python 原生类型。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import _json_safe_debug_value

    # numpy.int32 → Python int
    result_int = _json_safe_debug_value(np.int32(42))
    assert isinstance(result_int, int), f"期望 int，实际 {type(result_int)}"
    assert result_int == 42
    assert not isinstance(result_int, np.integer)

    # numpy.float32 → Python float
    result_float = _json_safe_debug_value(np.float32(3.14))
    assert isinstance(result_float, float), f"期望 float，实际 {type(result_float)}"
    assert abs(result_float - 3.14) < 0.01

    # numpy.float64 → Python float
    result_f64 = _json_safe_debug_value(np.float64(2.718))
    assert isinstance(result_f64, float)
    assert abs(result_f64 - 2.718) < 0.001

    # numpy.bool_ → Python bool
    result_bool = _json_safe_debug_value(np.bool_(True))
    assert isinstance(result_bool, bool), f"期望 bool，实际 {type(result_bool)}"
    assert result_bool is True


# =====================================================
# 21. P0-4A-6B-3U-D: _json_safe_debug_value 处理 numpy ndarray
# =====================================================


def test_json_safe_debug_value_handles_numpy_ndarray():
    """验证 _json_safe_debug_value 将 numpy ndarray 转为嵌套 Python list。"""
    import numpy as np
    from app.wechat_ui.contact_searcher import _json_safe_debug_value

    arr = np.array([[np.int32(10), np.int32(20)], [np.int32(30), np.int32(40)]])
    result = _json_safe_debug_value(arr)

    assert isinstance(result, list)
    assert len(result) == 2
    # 内部元素也应被转为 Python int
    for row in result:
        assert isinstance(row, list)
        for val in row:
            assert isinstance(val, int), f"期望 Python int，实际 {type(val).__name__}"
            assert not isinstance(val, np.integer)


# =====================================================
# 22. P0-4A-6B-3U-D: 含 numpy 标量的完整响应 JSON 序列化不抛 500
# =====================================================


def test_full_response_json_serializable_with_numpy_scalars():
    """验证含 numpy 标量的完整 /agent/wechat/test 响应可以被 JSON 序列化。"""
    import json
    import numpy as np
    from app.wechat_ui.contact_searcher import _json_safe_debug_value

    # 模拟 verify_search_text_in_search_box 返回含 numpy 标量的 ocr_items
    numpy_bbox = [
        np.array([np.int32(10), np.int32(20)]),
        np.array([np.int32(50), np.int32(20)]),
        np.array([np.int32(50), np.int32(40)]),
        np.array([np.int32(10), np.int32(40)]),
    ]
    ocr_items = [{
        "text": "Aw3",
        "confidence": float(np.float32(0.91)),
        "bbox": [[int(v) for v in p] for p in numpy_bbox],
    }]

    search_focus = {
        "search_text_verified": True,
        "text_pasted_into_search_box": True,
        "search_text_debug": {
            "expected": "Aw3",
            "verified": True,
            "ocr_items": ocr_items,
        },
    }

    open_result = {
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
        "search_focus": search_focus,
        "notes": [],
    }

    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main.find_wechat_window", return_value=_window()), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname", return_value=open_result), \
         patch("app.local_agent_main.verify_current_chat_contact",
               return_value=_verified()), \
         patch("app.local_agent_main.write_text_to_input",
               return_value={"success": True, "pasted": True}), \
         patch("app.local_agent_main.get_ocr_status",
               return_value={"success": True, "ocr_available": True, "ocr_initialized": True,
                             "model_ready": True, "initializing": False, "engine": "easyocr"}), \
         patch("app.local_agent_main._check_ocr_ready_for_agent_test", return_value=None), \
         patch("app.local_agent_main._safe_screenshot", return_value=None):
        response = _client().post("/agent/wechat/test", json={
            "nickname": "Aw3", "message": "test",
        })

    # 不应返回 500
    assert response.status_code == 200, f"状态码={response.status_code}，响应={response.text[:500]}"
    data = response.json()
    assert data["success"] is True
    assert data["action"]["pasted"] is True
    assert data["action"]["sent"] is False
    # 验证 JSON 可以被二次序列化（不含 numpy 残留）
    json_str = json.dumps(data)
    reloaded = json.loads(json_str)
    assert reloaded["success"] is True


# =====================================================
# 23. P0-4A-6B-3U-D: _json_safe_debug_value 不改变 Python 原生值
# =====================================================


def test_json_safe_debug_value_preserves_native_types():
    """验证 _json_safe_debug_value 不改变已有的 Python 原生类型值。"""
    from app.wechat_ui.contact_searcher import _json_safe_debug_value

    # Python 原生类型应原样返回
    assert _json_safe_debug_value(42) == 42
    assert isinstance(_json_safe_debug_value(42), int)
    assert _json_safe_debug_value(3.14) == 3.14
    assert isinstance(_json_safe_debug_value(3.14), float)
    assert _json_safe_debug_value("hello") == "hello"
    assert _json_safe_debug_value(True) is True
    assert _json_safe_debug_value(None) is None

    # dict 应递归处理
    d = {"a": 1, "b": "two", "c": None}
    result = _json_safe_debug_value(d)
    assert result == d

    # list 应递归处理
    lst = [1, "two", None, True]
    result = _json_safe_debug_value(lst)
    assert result == lst
