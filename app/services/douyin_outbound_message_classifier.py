from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import DouyinWebhookEvent
from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event


SYSTEM_NOTICE_TEXTS = {
    "你收到一条新消息，请打开抖音app查看",
}


def is_effective_human_outbound_message(db: Session, event: DouyinWebhookEvent) -> bool:
    if event.event != "im_send_msg" or event.is_duplicate == 1:
        return False
    if outbound_skip_reason(event) is not None:
        return False
    if is_ai_auto_sent_message_event(db, event=event):
        return False
    return True


def outbound_skip_reason(event: DouyinWebhookEvent) -> str | None:
    message_type = (event.message_type or "").strip().lower()
    if message_type == "notice":
        return "notice_message"
    text = _normalize_message_text(_parsed_event_content(event))
    if not text:
        return "empty_text"
    if is_system_notice_text(text):
        return "system_notice_message"
    return None


def is_system_notice_text(text: str | None) -> bool:
    normalized = str(text or "").strip()
    return normalized in SYSTEM_NOTICE_TEXTS


def im_send_msg_participants(event: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    return _optional_str(event.from_user_id), _optional_str(event.to_user_id)


def _parsed_event_content(event: DouyinWebhookEvent) -> dict[str, Any]:
    if event.parsed_content_json:
        try:
            parsed = json.loads(event.parsed_content_json)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    if event.raw_body:
        try:
            payload = json.loads(event.raw_body)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            raw_content = payload.get("content")
            if isinstance(raw_content, dict):
                return raw_content
            if isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                except (TypeError, ValueError):
                    return {}
                return parsed_content if isinstance(parsed_content, dict) else {}
    return {}


def _normalize_message_text(content: dict[str, Any]) -> str:
    for key in ("text", "content", "title", "message"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
