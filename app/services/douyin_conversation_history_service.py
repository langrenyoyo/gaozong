"""抖音私信会话历史上下文组装服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.douyin_workbench_conversation_service import list_conversation_messages


def build_conversation_history(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
    latest_message: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    """为 9100 reply-suggestion 组装可信 conversation_history。"""
    if not account_open_id or not conversation_key:
        return []

    data = list_conversation_messages(
        db,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
    )
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    history_items = [_to_history_item(item) for item in items if isinstance(item, dict)]
    history_items = [item for item in history_items if item is not None]
    history_items = _drop_latest_customer_message(history_items, latest_message)
    if limit <= 0:
        return []
    return history_items[-limit:]


def _to_history_item(item: dict[str, Any]) -> dict[str, str] | None:
    role = _role_for_message(item)
    if role is None:
        return None

    content = str(item.get("content") or "").strip()
    if not content:
        return None

    message_id = str(item.get("server_message_id") or item.get("raw_event_id") or item.get("id") or "").strip()
    result = {
        "role": role,
        "content": content,
        "created_at": _format_created_at(item.get("created_at")),
        "message_id": message_id,
    }
    return result


def _role_for_message(item: dict[str, Any]) -> str | None:
    sender_type = str(item.get("sender_type") or "").strip()
    direction = str(item.get("direction") or "").strip()
    if sender_type == "customer" or direction == "inbound":
        return "customer"
    if sender_type == "staff" or direction == "outbound":
        return "agent"
    return None


def _drop_latest_customer_message(
    history_items: list[dict[str, str]],
    latest_message: str,
) -> list[dict[str, str]]:
    latest_text = str(latest_message or "").strip()
    if not latest_text:
        return history_items

    for index in range(len(history_items) - 1, -1, -1):
        item = history_items[index]
        if item.get("role") == "customer" and item.get("content", "").strip() == latest_text:
            return history_items[:index] + history_items[index + 1 :]
    return history_items


def _format_created_at(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)
