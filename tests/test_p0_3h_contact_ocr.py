"""P0-3H OCR 联系人验证接入测试。"""

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_ocr_matcher_aw3_case_insensitive_verified():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("AW3", "Aw3", confidence=0.91)

    assert result["matched"] is True
    assert result["verified"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None


def test_ocr_matcher_chinese_special_symbol_partial_not_verified():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("啊东 {ItH,", "啊东、", confidence=0.94)

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["partial_match"] is True
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "partial_match_special_symbol_missing"


def test_ocr_matcher_empty_text_failure():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("", "Aw3", confidence=0.9)

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["failure_stage"] == "ocr_text_empty"


def test_ocr_matcher_low_confidence_requires_manual_review():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("Aw3", "Aw3", confidence=0.5, min_confidence=0.75)

    assert result["matched"] is True
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "low_confidence"


def test_contact_verifier_uses_ocr_after_uia_title_failed():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": True,
        "strategy": "ocr_top_title",
        "expected_nickname": "Aw3",
        "ocr_text": "AW3",
        "matched": True,
        "matched_text": "AW3",
        "partial_match": False,
        "confidence": 0.91,
        "manual_review_required": False,
        "failure_stage": None,
        "screenshot_path": "full.png",
        "cropped_path": "crop.png",
        "preprocessed_path": "pre.png",
        "engine": "easyocr",
    }

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value=None), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr",
               return_value=ocr_result) as mock_ocr:
        result = verify_current_chat_contact("Aw3", win_rect={"left": 0, "top": 0, "right": 100, "bottom": 100})

    assert result["verified"] is True
    assert result["strategy"] == "ocr_top_title"
    assert result["matched_text"] == "AW3"
    assert result["ocr_text"] == "AW3"
    assert result["evidence"]["cropped_path"] == "crop.png"
    mock_ocr.assert_called_once()


def test_contact_verifier_does_not_verify_partial_match():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": False,
        "strategy": "ocr_top_title",
        "expected_nickname": "啊东、",
        "ocr_text": "啊东 {ItH,",
        "matched": False,
        "matched_text": "啊东 {ItH,",
        "partial_match": True,
        "confidence": 0.94,
        "manual_review_required": True,
        "failure_stage": "partial_match_special_symbol_missing",
        "screenshot_path": "full.png",
        "cropped_path": "crop.png",
        "preprocessed_path": "pre.png",
        "engine": "easyocr",
    }

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value=None), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr",
               return_value=ocr_result), \
         patch("app.wechat_ui.contact_verifier._close_profile_card_safe") as mock_close:
        result = verify_current_chat_contact("啊东、", win_rect={"left": 0, "top": 0, "right": 100, "bottom": 100})

    assert result["verified"] is False
    assert result["strategy"] == "ocr_top_title"
    assert result["partial_match"] is True
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "partial_match_special_symbol_missing"
    mock_close.assert_not_called()


def test_contact_verifier_refuses_hidden_wechat_before_ocr():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": False, "visible": False, "message": "hidden"}), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr") as mock_ocr:
        result = verify_current_chat_contact("Aw3")

    assert result["verified"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    mock_ocr.assert_not_called()


def test_debug_contact_ocr_uses_shared_matcher():
    import scripts.debug_contact_ocr as debug_contact_ocr
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    assert debug_contact_ocr.evaluate_ocr_match("Aw3", "AW3", 0.91)["matched"] is True
    assert debug_contact_ocr.match_ocr_text_to_nickname is match_ocr_text_to_nickname


def test_debug_contact_verify_with_ocr_report_schema(tmp_path):
    from scripts.debug_contact_verify_with_ocr import build_verify_ocr_report

    entries = [
        {
            "verified": True,
            "strategy": "ocr_top_title",
            "ocr_text": "AW3",
            "confidence": 0.91,
            "failure_stage": None,
            "manual_review_required": False,
            "partial_match": False,
            "evidence": {"cropped_path": "crop.png"},
        },
        {
            "verified": False,
            "strategy": "ocr_top_title",
            "ocr_text": "啊东",
            "confidence": 0.94,
            "failure_stage": "partial_match_special_symbol_missing",
            "manual_review_required": True,
            "partial_match": True,
            "evidence": {"cropped_path": "crop2.png"},
        },
    ]

    report = build_verify_ocr_report(
        run_id="unit",
        nickname="Aw3",
        repeat=2,
        output_dir=tmp_path,
        entries=entries,
    )

    assert report["nickname"] == "Aw3"
    assert report["verified_count"] == 1
    assert report["partial_match_count"] == 1
    assert report["manual_review_required_count"] == 1
    assert Path(report["json_path"]).name == "contact_verify_ocr_report.json"
    assert Path(report["markdown_path"]).name == "contact_verify_ocr_summary.md"
