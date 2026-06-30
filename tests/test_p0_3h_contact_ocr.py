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


def test_normalize_wechat_contact_name_removes_safe_punctuation():
    from app.wechat_ui.ocr_matcher import normalize_wechat_contact_name

    assert normalize_wechat_contact_name("啊东、") == "啊东"
    assert normalize_wechat_contact_name("趣多多.") == "趣多多"
    assert normalize_wechat_contact_name("廖总") == "廖总"
    assert normalize_wechat_contact_name("刘洪林") == "刘洪林"


def test_ocr_matcher_accepts_exact_normalized_alias():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("啊东", "啊东、", confidence=0.94)

    assert result["matched"] is True
    assert result["verified"] is True
    assert result["partial_match"] is False
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None
    assert result["match_method"] == "exact_normalized_match"


def test_ocr_matcher_rejects_single_character_contains_match():
    from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname

    result = match_ocr_text_to_nickname("东", "啊东、", confidence=0.94)

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "ocr_text_wrong"

    result = match_ocr_text_to_nickname("张", "张三", confidence=0.94)

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "ocr_text_wrong"


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


def test_ocr_top_title_exact_match_ignores_low_confidence():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_result

    result = build_ocr_result(
        expected_nickname="A张生177020658",
        region="top_title",
        ocr_text="A张生177020658",
        confidence=0.68,
        screenshot_path="full.png",
        engine="easyocr",
    )

    assert result["matched"] is True
    assert result["verified"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None
    assert result["match_method"] == "exact_match"


def test_ocr_top_title_normalized_exact_match_ignores_low_confidence():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_result

    result = build_ocr_result(
        expected_nickname="啊东、",
        region="top_title",
        ocr_text="啊东",
        confidence=0.68,
        screenshot_path="full.png",
        engine="easyocr",
    )

    assert result["matched"] is True
    assert result["verified"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None
    assert result["match_method"] == "exact_normalized_match"


def test_build_ocr_title_regions_are_narrow():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_title_regions

    rect = {"left": 100, "top": 200, "right": 980, "bottom": 900}
    regions = build_ocr_title_regions(rect)

    tight = regions["title_left_tight"]
    standard = regions["title_left_standard"]
    width = rect["right"] - rect["left"]

    assert tight[2] - tight[0] <= int(width * 0.60)
    assert tight[3] - tight[1] <= 72
    assert tight[0] >= rect["left"] + 320
    assert standard[0] >= rect["left"] + 308
    assert standard[2] - standard[0] <= int(width * 0.60)
    assert standard[3] - standard[1] <= 72


def test_ocr_title_regions_start_after_conversation_list():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_title_regions

    rect = {"left": 0, "top": 0, "right": 886, "bottom": 700}
    regions = build_ocr_title_regions(rect)

    assert regions["title_left_tight"][0] >= 320
    assert regions["title_left_standard"][0] >= 308
    assert regions["title_left_tight"][2] <= 600
    assert regions["title_left_standard"][2] <= 640


def test_ocr_top_title_trims_trailing_symbol_only():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_result

    result = build_ocr_result(
        expected_nickname="A张生177020658",
        region="top_title",
        ocr_text="A张生177020658 [",
        confidence=0.92,
        screenshot_path="full.png",
        engine="easyocr",
    )

    assert result["matched"] is True
    assert result["verified"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None
    assert result["matched_text"] == "A张生177020658"


def test_ocr_top_title_rejects_noise_suffix():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_result

    result = build_ocr_result(
        expected_nickname="黄照",
        region="top_title",
        ocr_text="黄照 01AAAGACAAAVGVI CIAIO",
        confidence=0.96,
        screenshot_path="full.png",
        engine="easyocr",
    )

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "ocr_text_wrong"

    result = build_ocr_result(
        expected_nickname="Aw3",
        region="top_title",
        ocr_text="AW3 UCK 多贝问s",
        confidence=0.96,
        screenshot_path="full.png",
        engine="easyocr",
    )

    assert result["matched"] is False
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "ocr_text_wrong"


def test_ocr_top_title_tracks_region_candidates():
    from app.wechat_ui.contact_ocr_verifier import build_ocr_result

    result = build_ocr_result(
        expected_nickname="A张生177020658",
        region="top_title",
        ocr_text="A张生177020658 [",
        confidence=0.92,
        screenshot_path="full.png",
        engine="easyocr",
        ocr_title_regions_tried=["title_left_tight", "title_left_standard"],
        ocr_title_region="title_left_tight",
        ocr_title_candidates_by_region={
            "title_left_tight": ["A张生177020658"],
            "title_left_standard": ["A张生177020658 ["],
        },
    )

    assert result["ocr_title_regions_tried"] == ["title_left_tight", "title_left_standard"]
    assert result["ocr_title_region"] == "title_left_tight"
    assert result["ocr_title_candidates_by_region"]["title_left_tight"] == ["A张生177020658"]


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


def test_contact_verifier_accepts_uia_title_normalized_exact_match():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="趣多多"), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr") as mock_ocr:
        result = verify_current_chat_contact("趣多多.")

    assert result["verified"] is True
    assert result["strategy"] == "uia_chat_title"
    assert result["matched_text"] == "趣多多"
    assert result["manual_review_required"] is False
    assert result["verify_method"] == "uia_chat_title"
    assert result["verify_result"] == "exact_normalized_match"
    mock_ocr.assert_not_called()


def test_contact_verifier_gets_structured_uia_title_exact_match():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="黄照"), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr") as mock_ocr:
        result = verify_current_chat_contact("黄照", search_keyword_used="黄照")

    assert result["verified"] is True
    assert result["strategy"] == "uia_chat_title"
    assert result["verify_method"] == "uia_chat_title"
    assert result["verify_result"] == "exact_match"
    assert result["uia_title_candidates"] == ["黄照"]
    assert result["normalized_uia_title_candidates"] == ["黄照"]
    assert result["ocr_title_candidates"] == []
    assert result["normalized_ocr_title_candidates"] == []
    mock_ocr.assert_not_called()


def test_contact_verifier_blocks_ambiguous_normalized_fallback_title():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value="趣多多"), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr") as mock_ocr:
        result = verify_current_chat_contact(
            "趣多多.",
            search_keyword_used="趣多多",
            candidate_source="target_normalized",
            candidate_is_normalized_fallback=True,
        )

    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["verify_method"] == "uia_chat_title"
    assert result["manual_review_reason"] == "ambiguous_normalized_fallback_title"
    mock_ocr.assert_not_called()


def test_contact_verifier_accepts_ocr_normalized_exact_match():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": True,
        "strategy": "ocr_top_title",
        "expected_nickname": "啊东、",
        "ocr_text": "啊东",
        "matched": True,
        "matched_text": "啊东",
        "match_method": "exact_normalized_match",
        "partial_match": False,
        "confidence": 0.94,
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
               return_value=ocr_result):
        result = verify_current_chat_contact("啊东、", win_rect={"left": 0, "top": 0, "right": 100, "bottom": 100})

    assert result["verified"] is True
    assert result["partial_match"] is False
    assert result["manual_review_required"] is False
    assert result["verify_method"] == "ocr_title_normalized_exact"
    assert result["verify_result"] == "exact_normalized_match"


def test_contact_verifier_ocr_title_has_structured_candidates():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": True,
        "strategy": "ocr_top_title",
        "expected_nickname": "谭德贤",
        "ocr_text": "谭德贤",
        "matched": True,
        "matched_text": "谭德贤",
        "match_method": "exact_match",
        "partial_match": False,
        "confidence": 0.94,
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
               return_value=ocr_result):
        result = verify_current_chat_contact("谭德贤")

    assert result["verified"] is True
    assert result["verify_method"] == "ocr_title_exact"
    assert result["verify_result"] == "exact_match"
    assert result["ocr_title_candidates"] == ["谭德贤"]
    assert result["normalized_ocr_title_candidates"] == ["谭德贤"]


def test_contact_verifier_accepts_low_confidence_ocr_title_exact_match():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": True,
        "strategy": "ocr_top_title",
        "expected_nickname": "A张生177020658",
        "ocr_text": "A张生177020658",
        "matched": True,
        "matched_text": "A张生177020658",
        "match_method": "exact_match",
        "partial_match": False,
        "confidence": 0.68,
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
               return_value=ocr_result):
        result = verify_current_chat_contact("A张生177020658")

    assert result["verified"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None
    assert result["matched_text"] == "A张生177020658"
    assert result["confidence"] == 0.68
    assert result["verify_method"] == "ocr_title_exact"
    assert result["verify_result"] == "exact_match"


def test_contact_verifier_blocks_ocr_normalized_match_for_normalized_fallback_candidate():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": True,
        "strategy": "ocr_top_title",
        "expected_nickname": "趣多多.",
        "ocr_text": "趣多多",
        "matched": True,
        "matched_text": "趣多多",
        "match_method": "exact_normalized_match",
        "partial_match": False,
        "confidence": 0.94,
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
               return_value=ocr_result):
        result = verify_current_chat_contact(
            "趣多多.",
            search_keyword_used="趣多多",
            candidate_source="target_normalized",
            candidate_is_normalized_fallback=True,
        )

    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "manual_review_required"
    assert result["verify_method"] == "ocr_title_normalized_fallback_ambiguous"
    assert result["manual_review_reason"] == "normalized_fallback_requires_strong_exact_title"
    assert result["matched_text"] == "趣多多"


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


def test_contact_verifier_failure_keeps_diagnostic_alias_payload():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": False,
        "strategy": "ocr_top_title",
        "expected_nickname": "黄照",
        "ocr_text": "其他人",
        "matched": False,
        "matched_text": None,
        "partial_match": False,
        "confidence": 0.94,
        "manual_review_required": True,
        "failure_stage": "ocr_text_wrong",
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
               return_value=ocr_result):
        result = verify_current_chat_contact("黄照", search_keyword_used="黄照")

    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["verify_result"] == "manual_review_required"
    assert result["target_nickname"] == "黄照"
    assert result["search_keyword_used"] == "黄照"
    assert result["expected_aliases"] == ["黄照"]
    assert result["normalized_expected_aliases"] == ["黄照"]
    assert "其他人" in result["observed_contact_texts"]
    assert "其他人" in result["normalized_observed_contact_texts"]


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


def test_contact_verifier_manual_review_when_no_title_evidence():
    from app.wechat_ui.contact_verifier import verify_current_chat_contact

    window = MagicMock()
    window.NativeWindowHandle = 123
    ocr_result = {
        "verified": False,
        "strategy": "ocr_top_title",
        "expected_nickname": "黄照",
        "ocr_text": "",
        "matched": False,
        "matched_text": None,
        "partial_match": False,
        "confidence": 0.0,
        "manual_review_required": True,
        "failure_stage": "ocr_text_empty",
        "screenshot_path": "full.png",
        "cropped_path": "crop.png",
        "preprocessed_path": None,
        "engine": "easyocr",
    }

    with patch("app.wechat_ui.contact_verifier.find_wechat_window", return_value=window), \
         patch("app.wechat_ui.contact_verifier.check_wechat_ready_for_automation",
               return_value={"success": True}), \
         patch("app.wechat_ui.contact_verifier.find_current_chat_title", return_value=None), \
         patch("app.wechat_ui.contact_verifier.verify_contact_by_top_title_ocr",
               return_value=ocr_result):
        result = verify_current_chat_contact("黄照")

    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "ocr_text_empty"
    assert result["manual_review_reason"] == "title_evidence_not_matched"
    assert result["verify_result"] == "manual_review_required"


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
