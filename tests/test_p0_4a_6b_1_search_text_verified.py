"""P0-4A-6B-1 修复搜索关键词已在搜索框中但 search_text_verified=false 的误判

验证：
1. _normalize_text 归一化去空格
2. 策略 A1 UIA 命中时返回 search_text_debug.method = uia_focused_control_text
3. 策略 A2 扩大裁剪 + 归一化匹配命中时 method = ocr_expanded_search_box_normalized
4. 策略 A2 原始匹配兜底命中时 method = ocr_expanded_search_box
5. 策略 B 组合证据通过时 method = focused_search_box_with_result_aw3
6. 所有策略失败时 search_text_verified=false 且 search_text_debug.reason 非空
7. 焦点在聊天输入框时 text_leaked_to_chat_input=true 且立即返回
8. search_text_debug 包含 ocr_items 详细列表
9. search_text_debug 包含 crop_rect 裁剪区域
10. React 类型定义包含 search_text_debug 字段
"""

from unittest.mock import MagicMock, patch

import pytest

# easyocr 是可选依赖，测试环境可能未安装；模块内部局部 import easyocr，
# 所以通过 sys.modules 注入 mock 模块，避免 ModuleNotFoundError
import sys

if "easyocr" not in sys.modules:
    sys.modules["easyocr"] = MagicMock()


def _easyocr():
    """获取 sys.modules 中唯一的 easyocr mock，避免跨文件隔离问题。"""
    return sys.modules["easyocr"]


@pytest.fixture(autouse=True)
def _reset_easyocr_mock():
    """每个测试前后重置 easyocr mock，防止 side_effect 跨测试泄漏。"""
    _easyocr().reset_mock()
    _easyocr().Reader = MagicMock()
    yield
    _easyocr().Reader = MagicMock()


# =====================================================
# 1. _normalize_text 归一化去空格
# =====================================================


def test_normalize_text_removes_spaces_and_lowercases():
    from app.wechat_ui.contact_searcher import _normalize_text

    assert _normalize_text("A w3") == "aw3"
    assert _normalize_text("AW3") == "aw3"
    assert _normalize_text("  Aw 3  ") == "aw3"
    assert _normalize_text("") == ""
    assert _normalize_text(None) == ""


# =====================================================
# 2. 策略 A1 UIA 命中
# =====================================================


def test_strategy_a1_uia_hit():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = "Aw3"
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is True
    assert result["success"] is True
    assert result["reason"] == "uia_focused_control_contains_search_text"
    assert result["search_text_debug"]["verified"] is True
    assert result["search_text_debug"]["method"] == "uia_focused_control_text"


# =====================================================
# 3. 策略 A2 扩大裁剪 + 归一化匹配命中
# =====================================================


def test_strategy_a2_expanded_ocr_normalized_hit():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # OCR 返回 "A w3"，归一化后为 "aw3" 能匹配 "aw3"
    mock_reader.readtext.return_value = [
        ([[10, 10], [50, 10], [50, 30], [10, 30]], "A w3", 0.85),
    ]
    # 通过 sys.modules 注入的 easyocr mock 设置 Reader 返回值
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is True
    assert result["success"] is True
    assert result["reason"] == "ocr_expanded_search_box_normalized"
    assert result["search_text_debug"]["verified"] is True
    assert result["search_text_debug"]["method"] == "ocr_expanded_search_box_normalized"
    assert result["search_text_debug"]["normalized_ocr_text"] == "aw3"


# =====================================================
# 4. 策略 A2 原始匹配兜底命中
# =====================================================


def test_strategy_a2_raw_match_fallback_hit():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    # OCR 返回 "Aw3test"，归一化后 "aw3test" 含 "aw3" 但 expected="Xyz" 不含
    # 但 match_ocr_text_to_nickname 返回 matched=True（原始匹配兜底）
    mock_reader.readtext.return_value = [
        ([[10, 10], [50, 10], [50, 30], [10, 30]], "Aw3test", 0.85),
    ]
    mock_match_result = {"matched": True, "confidence": 0.85}
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname", return_value=mock_match_result):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Xyz",
            click_point=click_point,
        )

    # 归一化不匹配（"aw3test" 不含 "xyz"），但 match_ocr_text_to_nickname 返回 matched=True
    assert result["search_text_verified"] is True
    assert result["reason"] == "ocr_expanded_search_box"
    assert result["search_text_debug"]["method"] == "ocr_expanded_search_box"


# =====================================================
# 5. 策略 B 组合证据通过
# =====================================================


def test_strategy_b_combined_evidence_pass():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    # Reader 每次调用返回同一个 reader 实例，
    # readtext 通过 side_effect 依次返回：搜索框（空）→ 结果区域（含 Aw3）
    mock_reader = MagicMock()
    mock_reader.readtext.side_effect = [
        # 第一次调用（策略 A2：搜索框区域 OCR）→ 空结果
        [],
        # 第二次调用（策略 B：结果区域 OCR）→ 包含 Aw3
        [([[10, 10], [50, 10], [50, 30], [10, 30]], "Aw3", 0.9)],
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"), \
         patch("app.wechat_ui.contact_searcher._search_result_region",
               return_value={"left": 50, "top": 120, "right": 500, "bottom": 500}), \
         patch("app.wechat_ui.ocr_matcher.match_ocr_text_to_nickname",
               return_value={"matched": False}):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is True
    assert result["success"] is True
    assert result["reason"] == "focused_search_box_with_result_aw3"
    assert result["search_text_debug"]["method"] == "focused_search_box_with_result_aw3"
    assert result["search_text_debug"]["verified"] is True


# =====================================================
# 6. 所有策略失败
# =====================================================


def test_all_strategies_failed():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([[10, 10], [50, 10], [50, 30], [10, 30]], "SomethingElse", 0.8),
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
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
    assert result["success"] is False
    assert result["search_text_debug"]["verified"] is False
    assert result["search_text_debug"]["reason"] is not None
    assert result["search_text_debug"]["reason"] != ""


# =====================================================
# 7. 焦点泄漏到聊天输入框
# =====================================================


def test_text_leaked_to_chat_input():
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
    assert result["reason"] == "focused_control_in_chat_input_region"
    assert result["search_text_debug"]["reason"] == "focused_control_in_chat_input_region"


# =====================================================
# 8. search_text_debug 包含 ocr_items
# =====================================================


def test_search_text_debug_contains_ocr_items():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([[10, 10], [50, 10], [50, 30], [10, 30]], "Aw3", 0.92),
        ([[60, 10], [100, 10], [100, 30], [60, 30]], "extra", 0.70),
    ]
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
         patch("app.wechat_ui.contact_searcher.grab_screen", return_value=MagicMock()), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_crop", return_value="crop.png"), \
         patch("app.wechat_ui.contact_searcher._save_search_text_debug_overlay", return_value="overlay.png"):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    assert result["search_text_verified"] is True
    items = result["search_text_debug"]["ocr_items"]
    assert len(items) == 2
    assert items[0]["text"] == "Aw3"
    assert items[0]["confidence"] == 0.92
    assert items[1]["text"] == "extra"


# =====================================================
# 9. search_text_debug 包含 crop_rect
# =====================================================


def test_search_text_debug_contains_crop_rect():
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = []
    _easyocr().Reader.return_value = mock_reader

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95, "search_box_rect": {
        "left": 100, "top": 85, "right": 300, "bottom": 110,
    }}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False), \
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

    crop_rect = result["search_text_debug"]["crop_rect"]
    assert crop_rect is not None
    # 扩大后：left - 10, top - 8, right + 10, bottom + 8
    assert crop_rect["left"] == 90
    assert crop_rect["top"] == 77
    assert crop_rect["right"] == 310
    assert crop_rect["bottom"] == 118


# =====================================================
# 10. React 类型定义包含 search_text_debug
# =====================================================


def test_react_types_contain_search_text_debug():
    from pathlib import Path

    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")
    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    # 类型定义
    assert "search_text_debug" in api
    assert "search_box_crop_path" in api
    assert "ocr_items" in api
    assert "normalized_expected" in api
    assert "normalized_ocr_text" in api
    assert "crop_rect" in api

    # React 面板展示
    assert "search_text_debug" in panel
    assert "搜索关键词验证诊断" in panel
    assert "OCR 条目" in panel
    assert "裁剪区域" in panel
