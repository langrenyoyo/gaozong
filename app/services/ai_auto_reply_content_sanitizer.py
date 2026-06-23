"""AI 自动回复候选内容的技术格式清洗。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


TECHNICAL_REPLY_FIELDS = (
    "```json",
    "reply_text",
    "manual_required",
    "risk_flags",
    "confidence",
    "auto_send",
    "lead_level",
)


@dataclass(frozen=True)
class SanitizedAiReplyContent:
    content: str | None
    format_invalid: bool = False
    reason: str | None = None
    extracted_from_structured: bool = False


def sanitize_ai_reply_content(value: object) -> SanitizedAiReplyContent:
    """从 LLM 返回的 JSON/fenced JSON 中提取纯回复文本。

    普通自然语言只做首尾空白清理；明显是技术结构但无法提取 reply_text 时，
    返回 format_invalid，调用方应阻断真实发送。
    """
    text = str(value or "").strip()
    if not text:
        return SanitizedAiReplyContent(content=None)

    candidate = _strip_markdown_json_fence(text)
    is_structured = candidate != text or _looks_like_json(candidate) or '"reply_text"' in candidate
    if not is_structured:
        return SanitizedAiReplyContent(content=text)

    parsed = _load_json_object(candidate)
    if parsed is not None:
        reply_text = _clean_extracted_reply_text(parsed.get("reply_text"))
        if reply_text:
            return SanitizedAiReplyContent(content=reply_text, extracted_from_structured=True)
        return SanitizedAiReplyContent(
            content=None,
            format_invalid=True,
            reason="llm_reply_json_parse_failed",
            extracted_from_structured=True,
        )

    reply_text = _extract_reply_text_loose(candidate)
    if reply_text:
        return SanitizedAiReplyContent(content=reply_text, extracted_from_structured=True)

    return SanitizedAiReplyContent(
        content=None,
        format_invalid=True,
        reason="llm_reply_json_parse_failed",
        extracted_from_structured=True,
    )


def _strip_markdown_json_fence(text: str) -> str:
    match = re.match(r"^```\s*(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def _load_json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _extract_reply_text_loose(text: str) -> str | None:
    match = re.search(r'"reply_text"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(f'"{match.group(1)}"')
    except (TypeError, ValueError):
        value = match.group(1)
    return _clean_extracted_reply_text(value)


def _clean_extracted_reply_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    nested = _strip_markdown_json_fence(text)
    if nested != text or (_looks_like_json(nested) and '"reply_text"' in nested):
        nested_result = sanitize_ai_reply_content(nested)
        return nested_result.content
    if _looks_like_json(text):
        return None
    return text
