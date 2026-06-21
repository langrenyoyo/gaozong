"""AI 自动发送 im_send_msg 回调识别服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import DouyinPrivateMessageSend, DouyinWebhookEvent


MATCH_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class SendMessageEventParticipants:
    account_open_id: str | None
    customer_open_id: str | None


def is_ai_auto_sent_message_event(db: Session, *, event: DouyinWebhookEvent) -> bool:
    """判断 im_send_msg 回调是否来自 AI 自动发送流水。

    匹配策略宁可漏判，不误判：先用上游消息 ID 精确匹配；若平台回调 ID 与
    send_msg 响应 ID 不一致，再要求账号、客户、会话、内容和时间窗口全部匹配。
    """
    if event.event != "im_send_msg":
        return False

    if event.server_message_id:
        exact = (
            db.query(DouyinPrivateMessageSend)
            .filter(DouyinPrivateMessageSend.send_source == "ai_auto")
            .filter(DouyinPrivateMessageSend.upstream_msg_id == event.server_message_id)
            .first()
        )
        if exact is not None:
            return True

    participants = _parse_im_send_msg_participants(event)
    event_content = _event_content(event)
    if (
        not participants.account_open_id
        or not participants.customer_open_id
        or not event.conversation_short_id
        or not event_content
    ):
        return False

    event_time = event.message_create_time or event.created_at
    if not isinstance(event_time, datetime):
        return False

    candidates = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.send_source == "ai_auto")
        .filter(DouyinPrivateMessageSend.account_open_id == participants.account_open_id)
        .filter(DouyinPrivateMessageSend.customer_open_id == participants.customer_open_id)
        .filter(DouyinPrivateMessageSend.conversation_short_id == event.conversation_short_id)
        .filter(DouyinPrivateMessageSend.status == "sent")
        .all()
    )
    for record in candidates:
        if not _content_equal(record.content, event_content):
            continue
        if not isinstance(record.sent_at, datetime):
            continue
        if abs(event_time - record.sent_at) <= MATCH_WINDOW:
            return True
    return False


def _parse_im_send_msg_participants(event: DouyinWebhookEvent) -> SendMessageEventParticipants:
    """按现有工作台规则解析 im_send_msg 方向：企业号 -> 客户。"""
    if event.event != "im_send_msg":
        return SendMessageEventParticipants(account_open_id=None, customer_open_id=None)
    return SendMessageEventParticipants(
        account_open_id=_optional_str(event.from_user_id),
        customer_open_id=_optional_str(event.to_user_id),
    )


def _event_content(event: DouyinWebhookEvent) -> str:
    content = _parsed_content(event)
    for key in ("text", "content", "title", "message"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _parsed_content(event: DouyinWebhookEvent) -> dict[str, Any]:
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
                    parsed = json.loads(raw_content)
                except (TypeError, ValueError):
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    return {}


def _content_equal(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_content(left)
    right_norm = _normalize_content(right)
    return bool(left_norm) and left_norm == right_norm


def _normalize_content(value: str | None) -> str:
    return " ".join((value or "").split())


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
