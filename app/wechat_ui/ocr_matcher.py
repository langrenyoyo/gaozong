"""OCR 文本与微信昵称匹配规则。"""

from __future__ import annotations

import unicodedata


SPECIAL_SYMBOLS = set("、，,。.!！？?;；:：-—_()（）[]【】《》〈〉“”\"'·")
CONTACT_NAME_DROP_CHARS = set("、，,。 .丶·　\t\r\n")


def normalize_wechat_contact_name(name: str) -> str:
    """联系人昵称标准化：只去掉安全标点，不做包含匹配。"""
    normalized = unicodedata.normalize("NFKC", (name or "").strip())
    return "".join(ch for ch in normalized if ch not in CONTACT_NAME_DROP_CHARS)


def build_contact_aliases(
    target_nickname: str,
    wechat_id: str | None = None,
    remark: str | None = None,
    search_keyword_used: str | None = None,
) -> list[str]:
    """构建联系人验证别名列表，保持顺序并去重。"""
    aliases: list[str] = []
    for value in (target_nickname, normalize_wechat_contact_name(target_nickname),
                  search_keyword_used, normalize_wechat_contact_name(search_keyword_used or ""),
                  wechat_id, remark):
        value = (value or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    return aliases


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
        "match_method": None,
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

    matched = False
    match_method = None

    if expected == text:
        matched = True
        match_method = "exact_match"
    elif expected.isascii() and expected.lower() == text.lower():
        matched = True
        match_method = "exact_case_insensitive_match"
    elif normalize_wechat_contact_name(expected) and (
        normalize_wechat_contact_name(expected) == normalize_wechat_contact_name(text)
    ):
        matched = True
        match_method = "exact_normalized_match"

    if matched:
        result.update({
            "matched": True,
            "matched_text": text,
            "match_method": match_method,
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

    has_special = contains_special_symbol(expected)
    if has_special and strip_special_symbols(expected) and strip_special_symbols(expected) in text:
        result.update({
            "partial_match": True,
            "matched_text": strip_special_symbols(expected),
            "manual_review_required": True,
            "failure_stage": "partial_match_special_symbol_missing",
        })
        return result

    result["failure_stage"] = "ocr_text_wrong"
    return result
