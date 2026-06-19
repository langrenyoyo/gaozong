"""Read-only Douyin private-message conversation aggregation for the workbench."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import normalize_message_text, parse_content
from app.models import DouyinLead, DouyinWebhookEvent
from app.services.contact_extractor import extract_contacts_from_text
from app.services.douyin_live_check_service import (
    list_authorized_accounts,
    list_persisted_authorized_accounts,
)
from app.services.lead_management_service import (
    has_retained_contact as lead_has_retained_contact,
    lead_score as compute_lead_score,
)


PRIVATE_MESSAGE_EVENTS = {"im_receive_msg", "im_send_msg"}
RESOURCE_URL_KEYS = (
    "file_Url",
    "file_url",
    "url",
    "image_url",
    "video_url",
    "resource_url",
    "media_url",
    "download_url",
)
HIGH_INTENT_KEYWORDS = (
    "想看车",
    "到店",
    "试驾",
    "价格能谈吗",
    "今天方便",
    "怎么联系",
    "微信多少",
    "电话多少",
)
MANUAL_REQUIRED_KEYWORDS = ("人工", "客服", "转人工", "真人", "电话联系", "加微信")


@dataclass(frozen=True)
class WorkbenchMessage:
    event_id: int
    event: str
    account_open_id: str
    open_id: str
    conversation_key: str
    conversation_short_id: str | None
    content: str
    message_type: str | None
    media_type: str | None
    resource_url: str | None
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
                "tags": build_conversation_tags(db, ordered),
            }
        )

    items.sort(key=lambda item: item["last_message_at"] or datetime.min, reverse=True)
    return {"items": items}


def get_account_unread_counts(
    db: Session,
    *,
    account_open_ids: list[str],
) -> dict[str, int]:
    """当前未接已读状态前，按企业号聚合入站私信数量作为一期临时未读数。"""
    requested_open_ids = {str(item) for item in account_open_ids if item}
    if not requested_open_ids:
        return {}

    counts = {account_open_id: 0 for account_open_id in requested_open_ids}
    messages = _load_messages(db)
    for message in messages:
        if message.event != "im_receive_msg":
            continue
        if message.account_open_id not in requested_open_ids:
            continue
        counts[message.account_open_id] += 1
    return counts


def build_conversation_tags(db: Session, messages: list[WorkbenchMessage]) -> list[str]:
    """按一期确定性规则生成会话标签，不依赖 LLM 或人工判定。"""
    if not messages:
        return []

    first = messages[0]
    lead = _find_conversation_lead(db, open_id=first.open_id, account_open_id=first.account_open_id)
    message_text = " ".join(item.content for item in messages if item.content)
    inbound_text = " ".join(item.content for item in messages if item.event == "im_receive_msg" and item.content)
    text_blob = " ".join(part for part in [message_text, inbound_text] if part).strip()
    raw_data = _safe_lead_raw_data(lead)
    has_retained_contact = _has_retained_contact(lead, messages, raw_data, text_blob)
    high_intent = _is_high_intent(lead, raw_data, text_blob, has_retained_contact)
    manual_required = _is_manual_required(lead, raw_data, text_blob, first.account_open_id)
    follow_up = _needs_follow_up(lead, messages, has_retained_contact)

    tags: list[str] = []
    if manual_required:
        tags.append("manual_required")
    if high_intent:
        tags.append("high_intent")
    if has_retained_contact:
        tags.append("retained_contact")
    if follow_up:
        tags.append("follow_up")
    return tags


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
                "message_type": message.message_type or "text",
                "media_type": message.media_type,
                "conversation_short_id": message.conversation_short_id,
                "resource_url": message.resource_url,
                "source_url": message.resource_url,
                "downloadable_resource": bool(message.media_type and message.resource_url),
                "resource_missing_reason": None
                if not message.media_type or message.resource_url
                else "resource_url_not_found",
                "created_at": message.created_at,
                "server_message_id": message.server_message_id,
            }
        )
    return {"items": items}


def get_conversation_profile(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
) -> dict[str, Any] | None:
    messages = _sort_messages(
        [
            item
            for item in _load_messages(db, account_open_id=account_open_id)
            if item.conversation_key == conversation_key
        ]
    )
    if not messages:
        return None

    first = messages[0]
    latest = messages[-1]
    lead = _find_conversation_lead(db, open_id=first.open_id, account_open_id=first.account_open_id)
    raw_data = _safe_lead_raw_data(lead)
    trace_message = latest or first

    return {
        "conversation_id": first.conversation_key,
        "conversation_key": first.conversation_key,
        "conversation_short_id": first.conversation_short_id,
        "account_open_id": first.account_open_id,
        "open_id": first.open_id,
        "nickname": first.nick_name or (lead.customer_name if lead else None) or first.open_id,
        "avatar": first.avatar,
        "online_status": "unknown",
        "source_channel": _profile_source_channel(lead, raw_data),
        "intent_car": _first_raw_value(raw_data, ("intent_car", "car_model", "model", "series", "brand_model")),
        "car_year": _first_raw_value(raw_data, ("car_year", "year", "vehicle_year")),
        "budget": _first_raw_value(raw_data, ("budget", "budget_range", "price_range")),
        "city": _first_raw_value(raw_data, ("city", "location_city", "customer_city")),
        "tags": build_conversation_tags(db, messages),
        "lead_score": _profile_lead_score(lead, raw_data),
        "trace": _profile_trace(db, trace_message),
        "lead": _profile_lead_payload(lead),
    }


def get_send_msg_context(
    db: Session,
    *,
    conversation_short_id: str,
    customer_open_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the latest non-duplicate message context needed by later send_msg work."""
    if not conversation_short_id:
        return None

    # 可回复前置事件只允许 im_receive_msg / im_enter_direct_msg；
    # 排除 im_send_msg（企业号自己发出的私信回执），其 server_message_id 不能作为回复 msg_id，
    # 否则上游 /send_msg 会返回 28003082「消息对象不匹配」。
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .filter(DouyinWebhookEvent.event.in_(("im_receive_msg", "im_enter_direct_msg")))
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
            "message_create_time": row.message_create_time,
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
    content = _payload_content(row, payload)
    message_type = _message_type(row, content)
    media_type = _media_type(message_type, content)
    text = normalize_message_text(content) or _media_placeholder(media_type)
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
        message_type=message_type,
        media_type=media_type,
        resource_url=_resource_url_from_content(content),
        created_at=row.created_at,
        server_message_id=_optional_str(content.get("server_message_id") or row.server_message_id),
        nick_name=profile.get("nick_name"),
        avatar=profile.get("avatar"),
        lead_id=row.lead_id,
    )


def _payload_content(row: DouyinWebhookEvent, payload: dict[str, Any]) -> dict[str, Any]:
    if row.parsed_content_json:
        try:
            parsed = json.loads(row.parsed_content_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return parse_content(payload.get("content"))


def _message_type(row: DouyinWebhookEvent, content: dict[str, Any]) -> str | None:
    return _optional_str(content.get("message_type") or row.message_type)


def _media_type(message_type: str | None, content: dict[str, Any]) -> str | None:
    value = _optional_str(content.get("media_type") or message_type)
    if value in {"image", "user_local_image"}:
        return "image"
    if value in {"video", "user_local_video"}:
        return "video"
    return None


def _media_placeholder(media_type: str | None) -> str:
    if media_type == "image":
        return "[图片]"
    if media_type == "video":
        return "[视频]"
    return ""


def _resource_url_from_content(content: dict[str, Any]) -> str | None:
    for key in RESOURCE_URL_KEYS:
        value = _optional_str(content.get(key))
        if value:
            return value
    nested = content.get("resource")
    if isinstance(nested, dict):
        for key in RESOURCE_URL_KEYS:
            value = _optional_str(nested.get(key))
            if value:
                return value
    return None


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


def _find_conversation_lead(db: Session, *, open_id: str, account_open_id: str) -> DouyinLead | None:
    if not open_id:
        return None
    rows = (
        db.query(DouyinLead)
        .filter(DouyinLead.source_id == open_id)
        .order_by(desc(DouyinLead.id))
        .all()
    )
    for row in rows:
        raw_data = _safe_lead_raw_data(row)
        raw_account_open_id = _optional_str(raw_data.get("account_open_id"))
        if raw_account_open_id and raw_account_open_id == account_open_id:
            return row
    if len(rows) == 1 and not _optional_str(_safe_lead_raw_data(rows[0]).get("account_open_id")):
        return rows[0]
    return None


def _safe_lead_raw_data(lead: DouyinLead | None) -> dict[str, Any]:
    if not lead or not lead.raw_data:
        return {}
    try:
        parsed = json.loads(lead.raw_data)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_raw_value(raw_data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw_data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _profile_source_channel(lead: DouyinLead | None, raw_data: dict[str, Any]) -> str:
    if lead and lead.source:
        return lead.source
    return _first_raw_value(raw_data, ("source", "source_channel")) or "douyin"


def _profile_lead_score(lead: DouyinLead | None, raw_data: dict[str, Any]) -> int:
    value: Any = raw_data.get("lead_score")
    if isinstance(value, dict):
        value = value.get("score")
    if value is None:
        value = raw_data.get("score")
    if value is None and lead is not None:
        value = compute_lead_score(lead).get("score")
    if value is None:
        return 0
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(score, 100))


def _profile_trace(db: Session, message: WorkbenchMessage) -> dict[str, Any]:
    row = db.get(DouyinWebhookEvent, message.event_id)
    return {
        "event_key": row.event_key if row else None,
        "conversation_short_id": message.conversation_short_id,
        "server_message_id": message.server_message_id,
        "source": "webhook_events",
        "created_at": message.created_at,
    }


def _profile_lead_payload(lead: DouyinLead | None) -> dict[str, Any] | None:
    if lead is None:
        return None
    return {
        "id": lead.id,
        "status": lead.status,
        "customer_contact": lead.customer_contact,
        "assigned_staff_id": lead.assigned_staff_id,
    }


def _normalized_text(*parts: Any) -> str:
    values = [str(part) for part in parts if isinstance(part, str) and part.strip()]
    return " ".join(values)


def _extract_raw_contact_values(raw_data: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def _append(value: Any) -> None:
        if isinstance(value, str) and value and value not in values:
            values.append(value)

    for key in ("phone", "wechat", "contact", "customer_contact"):
        _append(raw_data.get(key))

    contact_extract = raw_data.get("contact_extract")
    if isinstance(contact_extract, dict):
        for key in ("phone", "wechat", "contact", "customer_contact"):
            _append(contact_extract.get(key))
        all_contacts = contact_extract.get("all_contacts")
        if isinstance(all_contacts, list):
            for item in all_contacts:
                if isinstance(item, dict):
                    _append(item.get("value"))
                else:
                    _append(item)

    return values


def _has_retained_contact(
    lead: DouyinLead | None,
    messages: list[WorkbenchMessage],
    raw_data: dict[str, Any],
    text_blob: str,
) -> bool:
    del text_blob
    if lead and lead_has_retained_contact(lead):
        return True
    if _extract_raw_contact_values(raw_data):
        return True
    for item in messages:
        if extract_contacts_from_text(item.content).status == "matched":
            return True
    return False


def _is_high_intent(
    lead: DouyinLead | None,
    raw_data: dict[str, Any],
    text_blob: str,
    has_retained_contact: bool,
) -> bool:
    if raw_data.get("lead_score") is not None:
        try:
            if int(raw_data.get("lead_score")) >= 80:
                return True
        except (TypeError, ValueError):
            pass
    lead_score_data = raw_data.get("lead_score")
    if isinstance(lead_score_data, dict):
        score_value = lead_score_data.get("score")
        try:
            if score_value is not None and int(score_value) >= 80:
                return True
        except (TypeError, ValueError):
            pass
        level_value = str(lead_score_data.get("level") or "").strip().lower()
        if level_value in {"high", "high_intent", "high-intent", "高", "高意向"}:
            return True

    intent_level = str(raw_data.get("intent_level") or raw_data.get("purchase_intent_level") or "").strip().lower()
    if intent_level in {"high", "high_intent", "high-intent", "高", "高意向"}:
        return True

    if lead is not None:
        lead_score_payload = compute_lead_score(lead)
        try:
            if int(lead_score_payload.get("score") or 0) >= 80:
                return True
        except (TypeError, ValueError):
            pass

    return any(keyword in text_blob for keyword in HIGH_INTENT_KEYWORDS)


def _is_manual_required(
    lead: DouyinLead | None,
    raw_data: dict[str, Any],
    text_blob: str,
    account_open_id: str,
) -> bool:
    del account_open_id
    if any(keyword in text_blob for keyword in MANUAL_REQUIRED_KEYWORDS):
        return True
    if any(keyword in _normalized_text(raw_data.get("manual_required_reason"), raw_data.get("reply_mode")) for keyword in ("manual", "human", "人工")):
        return True
    return bool(lead and str(lead.status or "") == "manual_required")


def _needs_follow_up(
    lead: DouyinLead | None,
    messages: list[WorkbenchMessage],
    has_retained_contact: bool,
) -> bool:
    if not lead or not has_retained_contact:
        return False
    if lead.status not in {"pending", "assigned"}:
        return False
    if any(item.event == "im_send_msg" for item in messages):
        return False
    return True


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
