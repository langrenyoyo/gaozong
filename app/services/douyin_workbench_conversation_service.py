"""Read-only Douyin private-message conversation aggregation for the workbench."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import normalize_message_text, parse_content
from app.models import DouyinWebhookEvent
from app.services.contact_extractor import extract_contacts_from_text
from app.services.douyin_live_check_service import (
    list_authorized_accounts,
    list_persisted_authorized_accounts,
)


PRIVATE_MESSAGE_EVENTS = {"im_receive_msg", "im_send_msg"}


@dataclass(frozen=True)
class WorkbenchMessage:
    event_id: int
    event: str
    account_open_id: str
    open_id: str
    conversation_key: str
    conversation_short_id: str | None
    content: str
    created_at: datetime | None
    server_message_id: str | None
    nick_name: str | None
    avatar: str | None
    lead_id: int | None


def list_account_conversations(db: Session, *, account_open_id: str) -> dict[str, Any]:
    messages = _load_messages(db, account_open_id=account_open_id)
    grouped: dict[str, list[WorkbenchMessage]] = {}
    for message in messages:
        grouped.setdefault(message.conversation_key, []).append(message)

    items = []
    for conversation_key, group in grouped.items():
        ordered = _sort_messages(group)
        first = ordered[0]
        latest = ordered[-1]
        items.append(
            {
                "id": conversation_key,
                "conversation_id": conversation_key,
                "conversation_key": conversation_key,
                "conversation_short_id": first.conversation_short_id,
                "account_id": account_open_id,
                "account_open_id": first.account_open_id,
                "open_id": first.open_id,
                "nickname": first.nick_name or first.open_id,
                "avatar": first.avatar,
                "last_message": latest.content,
                "last_message_at": latest.created_at,
                "unread_count": sum(1 for item in ordered if item.event == "im_receive_msg"),
                "lead_status": _lead_status(ordered),
            }
        )

    items.sort(key=lambda item: item["last_message_at"] or datetime.min, reverse=True)
    return {"items": items}


def list_douyin_workbench_accounts_with_event_fallback(db: Session) -> dict[str, Any]:
    """Return persisted authorized accounts, then live-check memory, then event fallback."""
    persisted = list_persisted_authorized_accounts(db)
    items = list(persisted.get("items") or [])
    existing_open_ids = {
        str(item.get("account_open_id") or item.get("open_id"))
        for item in items
        if item.get("account_open_id") or item.get("open_id")
    }

    authorized = list_authorized_accounts()
    for account in authorized.get("items") or []:
        account_open_id = str(account.get("account_open_id") or account.get("open_id") or "")
        if not account_open_id or account_open_id in existing_open_ids:
            continue
        items.append(account)
        existing_open_ids.add(account_open_id)

    for account in _event_derived_accounts(db):
        if account["account_open_id"] in existing_open_ids:
            continue
        items.append(account)
        existing_open_ids.add(account["account_open_id"])

    return {
        "items": items,
        "total": len(items),
        "source": "persisted_bind_info_with_live_check_memory_and_webhook_events_fallback",
    }


def list_conversation_messages(
    db: Session,
    *,
    conversation_key: str,
    account_open_id: str | None = None,
) -> dict[str, Any]:
    messages = _load_messages(db, account_open_id=account_open_id)
    items = []
    for message in _sort_messages([item for item in messages if item.conversation_key == conversation_key]):
        direction = _direction(message.event)
        items.append(
            {
                "id": message.event_id,
                "raw_event_id": message.event_id,
                "conversation_id": message.conversation_key,
                "conversation_key": message.conversation_key,
                "direction": direction,
                "sender_type": _sender_type(message.event),
                "content": message.content,
                "message_type": "text",
                "created_at": message.created_at,
                "server_message_id": message.server_message_id,
            }
        )
    return {"items": items}


def get_send_msg_context(
    db: Session,
    *,
    conversation_short_id: str,
    customer_open_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the latest non-duplicate message context needed by later send_msg work."""
    if not conversation_short_id:
        return None

    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .order_by(
            DouyinWebhookEvent.message_create_time.desc(),
            DouyinWebhookEvent.created_at.desc(),
            DouyinWebhookEvent.id.desc(),
        )
        .all()
    )
    for row in rows:
        account_open_id, resolved_customer_open_id = _send_msg_participants(row)
        if customer_open_id and resolved_customer_open_id != customer_open_id:
            continue
        if not row.server_message_id or not account_open_id or not resolved_customer_open_id:
            continue
        return {
            "conversation_id": row.conversation_short_id,
            "conversation_short_id": row.conversation_short_id,
            "msg_id": row.server_message_id,
            "server_message_id": row.server_message_id,
            "from_user_id": row.from_user_id,
            "to_user_id": row.to_user_id,
            "customer_open_id": resolved_customer_open_id,
            "account_open_id": account_open_id,
            "scene": row.event,
        }
    return None


def _send_msg_participants(row: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    if row.event == "im_send_msg":
        return row.from_user_id, row.to_user_id
    return row.to_user_id, row.from_user_id


def _load_messages(db: Session, *, account_open_id: str | None = None) -> list[WorkbenchMessage]:
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event.in_(PRIVATE_MESSAGE_EVENTS))
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .order_by(DouyinWebhookEvent.created_at.asc(), DouyinWebhookEvent.id.asc())
        .all()
    )
    messages: list[WorkbenchMessage] = []
    for row in rows:
        message = _row_to_message(row)
        if message is None:
            continue
        if account_open_id and message.account_open_id != account_open_id:
            continue
        messages.append(message)
    return messages


def _event_derived_accounts(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event.in_(PRIVATE_MESSAGE_EVENTS))
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
        .limit(500)
        .all()
    )
    accounts: dict[str, dict[str, Any]] = {}
    last_active_at: dict[str, datetime | None] = {}
    for row in rows:
        payload = _parse_raw_body(row.raw_body)
        if payload is None:
            continue
        content = parse_content(payload.get("content"))
        account_open_id = _account_open_id(row, payload, content)
        if not account_open_id:
            continue
        profile = _profile_for_account(row, payload, content, account_open_id)
        display_name = profile.get("nick_name") or f"抖音号 {account_open_id[-6:]}"
        current = accounts.get(account_open_id)
        if current is None:
            accounts[account_open_id] = {
                "id": _stable_numeric_id(account_open_id),
                "account_id": account_open_id,
                "douyin_account_id": _stable_numeric_id(account_open_id),
                "account_open_id": account_open_id,
                "open_id": account_open_id,
                "account_name": display_name,
                "name": display_name,
                "nickname": display_name,
                "avatar": profile.get("avatar") or "",
                "avatar_url": profile.get("avatar") or "",
                "status": "event_source",
                "is_active": False,
                "is_authorized": False,
                "has_events": True,
                "last_active_at": row.created_at,
                "authorized_at": None,
                "unread_count": 0,
                "source": "webhook_events",
            }
            last_active_at[account_open_id] = row.created_at
            continue
        if not current.get("avatar") and profile.get("avatar"):
            current["avatar"] = profile["avatar"]
            current["avatar_url"] = profile["avatar"]
        if current["account_name"].startswith("抖音号 ") and profile.get("nick_name"):
            current["account_name"] = profile["nick_name"]
            current["name"] = profile["nick_name"]
            current["nickname"] = profile["nick_name"]
        if (row.created_at or datetime.min) > (last_active_at.get(account_open_id) or datetime.min):
            current["last_active_at"] = row.created_at
            last_active_at[account_open_id] = row.created_at

    return sorted(
        accounts.values(),
        key=lambda item: item.get("last_active_at") or datetime.min,
        reverse=True,
    )


def _row_to_message(row: DouyinWebhookEvent) -> WorkbenchMessage | None:
    payload = _parse_raw_body(row.raw_body)
    if payload is None:
        return None
    content = parse_content(payload.get("content"))
    text = normalize_message_text(content)
    if not text:
        return None

    account_open_id = _account_open_id(row, payload, content)
    open_id = _customer_open_id(row, payload, content)
    if not account_open_id or not open_id:
        return None

    conversation_short_id = _optional_str(content.get("conversation_short_id"))
    conversation_key = conversation_short_id or f"{account_open_id}:{open_id}"
    profile = _profile_for_customer(row, payload, content, open_id)
    return WorkbenchMessage(
        event_id=row.id,
        event=row.event or "",
        account_open_id=account_open_id,
        open_id=open_id,
        conversation_key=conversation_key,
        conversation_short_id=conversation_short_id,
        content=text,
        created_at=row.created_at,
        server_message_id=_optional_str(content.get("server_message_id")),
        nick_name=profile.get("nick_name"),
        avatar=profile.get("avatar"),
        lead_id=row.lead_id,
    )


def _parse_raw_body(raw_body: str | None) -> dict[str, Any] | None:
    if not raw_body:
        return None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _account_open_id(row: DouyinWebhookEvent, payload: dict[str, Any], content: dict[str, Any]) -> str | None:
    return (
        _optional_str(content.get("account_open_id"))
        or _optional_str(payload.get("account_open_id"))
        or (row.to_user_id if row.event == "im_receive_msg" else row.from_user_id)
    )


def _customer_open_id(row: DouyinWebhookEvent, payload: dict[str, Any], content: dict[str, Any]) -> str | None:
    return (
        _optional_str(content.get("open_id"))
        or _optional_str(payload.get("open_id"))
        or (row.from_user_id if row.event == "im_receive_msg" else row.to_user_id)
    )


def _profile_for_customer(
    row: DouyinWebhookEvent,
    payload: dict[str, Any],
    content: dict[str, Any],
    open_id: str,
) -> dict[str, str | None]:
    profiles: dict[str, dict[str, str | None]] = {}
    _merge_profile(profiles, payload.get("open_id") or row.from_user_id, payload)
    _merge_profile(profiles, content.get("open_id") or row.from_user_id, content)
    user_infos = content.get("user_infos")
    if not isinstance(user_infos, list):
        user_infos = payload.get("user_infos")
    if isinstance(user_infos, list):
        for item in user_infos:
            if isinstance(item, dict):
                _merge_profile(profiles, item.get("open_id"), item)
    return profiles.get(open_id, {"nick_name": None, "avatar": None})


def _profile_for_account(
    row: DouyinWebhookEvent,
    payload: dict[str, Any],
    content: dict[str, Any],
    account_open_id: str,
) -> dict[str, str | None]:
    profiles: dict[str, dict[str, str | None]] = {}
    _merge_profile(profiles, row.from_user_id, payload)
    _merge_profile(profiles, row.to_user_id, payload)
    _merge_profile(profiles, content.get("account_open_id") or row.to_user_id, content)
    user_infos = content.get("user_infos")
    if not isinstance(user_infos, list):
        user_infos = payload.get("user_infos")
    if isinstance(user_infos, list):
        for item in user_infos:
            if isinstance(item, dict):
                _merge_profile(profiles, item.get("open_id"), item)

    profile = profiles.get(account_open_id, {"nick_name": None, "avatar": None})
    nick_name = (
        _optional_str(payload.get("to_user_nick_name"))
        or _optional_str(payload.get("account_name"))
        or _optional_str(content.get("account_name"))
        or profile.get("nick_name")
    )
    avatar = (
        _optional_str(payload.get("to_user_avatar"))
        or _optional_str(payload.get("account_avatar"))
        or _optional_str(content.get("account_avatar"))
        or profile.get("avatar")
    )
    return {"nick_name": nick_name, "avatar": avatar}


def _merge_profile(
    profiles: dict[str, dict[str, str | None]],
    open_id: Any,
    record: dict[str, Any],
) -> None:
    open_id_text = _optional_str(open_id)
    if not open_id_text:
        return
    nick_name = _optional_str(record.get("nick_name") or record.get("nickname"))
    avatar = _optional_str(record.get("avatar") or record.get("avatar_url"))
    if not nick_name and not avatar:
        return
    current = profiles.get(open_id_text, {"nick_name": None, "avatar": None})
    profiles[open_id_text] = {
        "nick_name": current.get("nick_name") or nick_name,
        "avatar": current.get("avatar") or avatar,
    }


def _lead_status(messages: list[WorkbenchMessage]) -> str:
    if any(item.lead_id is not None for item in messages):
        return "captured"
    if any(extract_contacts_from_text(item.content).status == "matched" for item in messages):
        return "captured"
    return "contact_not_found"


def _direction(event: str) -> str:
    if event == "im_receive_msg":
        return "inbound"
    if event == "im_send_msg":
        return "outbound"
    return "system"


def _sender_type(event: str) -> str:
    if event == "im_receive_msg":
        return "customer"
    if event == "im_send_msg":
        return "staff"
    return "system"


def _sort_messages(messages: list[WorkbenchMessage]) -> list[WorkbenchMessage]:
    return sorted(messages, key=lambda item: (item.created_at or datetime.min, item.event_id))


def _stable_numeric_id(value: str) -> int:
    total = 0
    for char in value:
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    return total or 1


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
