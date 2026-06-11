"""OCR 文本与微信昵称匹配规则。"""

from __future__ import annotations


SPECIAL_SYMBOLS = set("、，,。.!！？?;；:：-—_()（）[]【】《》〈〉“”\"'·")


def contains_special_symbol(value: str) -> bool:
    """判断昵称是否包含需要严格保留的特殊符号。"""
    return any(ch in SPECIAL_SYMBOLS for ch in value or "")


def strip_special_symbols(value: str) -> str:
    """移除特殊符号，用于识别 partial_match。"""
    return "".join(ch for ch in value or "" if ch not in SPECIAL_SYMBOLS)


def match_ocr_text_to_nickname(
    ocr_text: str,
    expected_nickname: str,
    confidence: float | None = None,
    min_confidence: float = 0.75,
) -> dict:
    """判断 OCR 文本是否足以确认当前聊天联系人。"""
    expected = (expected_nickname or "").strip()
    text = (ocr_text or "").strip()
    conf = float(confidence or 0)

    result = {
        "verified": False,
        "matched": False,
        "matched_text": None,
        "partial_match": False,
        "manual_review_required": True,
        "failure_stage": None,
    }

    if not expected:
        result["failure_stage"] = "empty_nickname"
        return result

    if not text:
        result["failure_stage"] = "ocr_text_empty"
        return result

    has_special = contains_special_symbol(expected)
    matched = False
    partial = False

    if expected in text:
        matched = True
    elif expected.isascii() and expected.lower() in text.lower():
        matched = True
    elif has_special:
        stripped_expected = strip_special_symbols(expected)
        if stripped_expected and stripped_expected in text:
            partial = True
    elif expected in text:
        matched = True

    if matched:
        result.update({
            "matched": True,
            "matched_text": expected,
            "manual_review_required": False,
            "failure_stage": None,
        })
        if conf < float(min_confidence):
            result.update({
                "verified": False,
                "manual_review_required": True,
                "failure_stage": "low_confidence",
            })
        else:
            result["verified"] = True
        return result

    if partial:
        result.update({
            "partial_match": True,
            "matched_text": strip_special_symbols(expected),
            "manual_review_required": True,
            "failure_stage": "partial_match_special_symbol_missing",
        })
        return result

    result["failure_stage"] = "ocr_text_wrong"
    return result
