"""9202 AI小高线索 internal webhook 事件处理逻辑。"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import DouyinAuthorizedAccount, DouyinLead, DouyinWebhookEvent
from app.services.contact_extractor import ContactExtractResult, extract_contacts_from_text


logger = logging.getLogger("leads_internal_webhook")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def parse_content(raw_content: Any) -> dict[str, Any]:
    """解析 content 字段，兼容 JSON 字符串和 JSON 对象。"""
    if isinstance(raw_content, dict):
        return raw_content
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_content_with_status(raw_content: Any) -> tuple[dict[str, Any], str, str | None]:
    if isinstance(raw_content, dict):
        return raw_content, "parsed", None
    if isinstance(raw_content, str):
        if not raw_content.strip():
            return {}, "empty", None
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return {}, "parse_failed", "invalid_content_json"
        if isinstance(parsed, dict):
            return parsed, "parsed", None
        return {}, "parse_failed", "content_json_not_object"
    if raw_content is None:
        return {}, "empty", None
    return {}, "parse_failed", "content_not_object_or_json_string"


def _message_create_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp)


def _profiles_by_open_id(user_infos: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(user_infos, list):
        return {}
    profiles: dict[str, dict[str, Any]] = {}
    for item in user_infos:
        if not isinstance(item, dict):
            continue
        open_id = _optional_str(item.get("open_id"))
        if open_id:
            profiles[open_id] = item
    return profiles


def _parse_callback_event(payload: dict[str, Any]) -> dict[str, Any]:
    content, parse_status, parse_error = _parse_content_with_status(payload.get("content"))
    from_user_id = _optional_str(payload.get("from_user_id"))
    to_user_id = _optional_str(payload.get("to_user_id"))
    profiles = _profiles_by_open_id(content.get("user_infos"))
    from_profile = profiles.get(from_user_id or "", {})
    to_profile = profiles.get(to_user_id or "", {})
    return {
        "client_key": _optional_str(payload.get("client_key")),
        "conversation_short_id": _optional_str(content.get("conversation_short_id")),
        "server_message_id": _optional_str(content.get("server_message_id")),
        "conversation_type": _optional_str(content.get("conversation_type")),
        "message_type": _optional_str(content.get("message_type")),
        "message_create_time": _message_create_time(content.get("create_time")),
        "message_source": _optional_str(content.get("source")),
        "from_user_nick_name": _optional_str(from_profile.get("nick_name") or from_profile.get("nickname")),
        "from_user_avatar": _optional_str(from_profile.get("avatar") or from_profile.get("avatar_url")),
        "to_user_nick_name": _optional_str(to_profile.get("nick_name") or to_profile.get("nickname")),
        "to_user_avatar": _optional_str(to_profile.get("avatar") or to_profile.get("avatar_url")),
        "parse_status": parse_status,
        "parse_error": parse_error,
        "parsed_content_json": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
    }


def normalize_message_text(content: dict[str, Any]) -> str:
    """从解析后的 content 中提取消息文本。"""
    for key in ("text", "content", "title", "message"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def is_text_message(content: dict[str, Any]) -> bool:
    """判断 content 是否表示纯文本私信消息。"""
    message_type = content.get("message_type")
    if message_type is None:
        return True
    return str(message_type).lower() == "text"


def _extract_user_profile(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    content = parse_content(payload.get("content"))
    from_user_id = payload.get("from_user_id")
    user_infos = content.get("user_infos") or []
    for user in user_infos:
        if isinstance(user, dict) and user.get("open_id") == from_user_id:
            return user.get("nick_name"), user.get("avatar")
    if user_infos and isinstance(user_infos[0], dict):
        return user_infos[0].get("nick_name"), user_infos[0].get("avatar")
    return None, None


def build_event_key(payload: dict[str, Any]) -> str:
    """基于稳定业务字段生成事件幂等键。"""
    content = parse_content(payload.get("content"))
    key_parts = [
        str(payload.get("event") or ""),
        str(payload.get("from_user_id") or ""),
        str(payload.get("to_user_id") or ""),
        str(content.get("conversation_short_id") or ""),
        str(content.get("server_message_id") or ""),
        str(content.get("create_time") or ""),
    ]
    return hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()


def _find_existing_event(db: Session, event_key: str) -> DouyinWebhookEvent | None:
    return (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event_key == event_key, DouyinWebhookEvent.is_duplicate.is_(False))
        .first()
    )


def _duplicate_event_key(original_event_key: str) -> str:
    return f"{original_event_key}:dup:{uuid.uuid4().hex}"


def _build_internal_event_values(
    payload: dict[str, Any],
    event_key: str,
) -> dict[str, Any]:
    """构造 9202 internal 事件完整字段值字典（不写数据库），供原子占位使用。"""
    return {
        "event": payload.get("event"),
        "from_user_id": payload.get("from_user_id"),
        "to_user_id": payload.get("to_user_id"),
        **_parse_callback_event(payload),
        "event_key": event_key,
        "is_duplicate": False,
        "lead_id": None,
        "merchant_id": None,
        "tenant_id": None,
        "raw_body": json.dumps(payload, ensure_ascii=False),
        "created_at": datetime.now(),
    }


def persist_webhook_event(
    db: Session,
    payload: dict[str, Any],
    event_key: str,
    lead_id: int | None = None,
) -> DouyinWebhookEvent:
    """写入首次 webhook 事件日志。"""
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **_parse_callback_event(payload),
        event_key=event_key,
        is_duplicate=False,
        lead_id=lead_id,
        raw_body=json.dumps(payload, ensure_ascii=False),
        created_at=datetime.now(),
    )
    db.add(event)
    db.flush()
    return event


def persist_duplicate_webhook_event(
    db: Session,
    payload: dict[str, Any],
    original_event_key: str,
    lead_id: int | None = None,
    *,
    merchant_id: str | None = None,
    tenant_id: str | None = None,
) -> DouyinWebhookEvent:
    """写入重复 webhook 审计事件，不更新线索，继承原事件归属。"""
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **_parse_callback_event(payload),
        event_key=_duplicate_event_key(original_event_key),
        is_duplicate=True,
        lead_id=lead_id,
        merchant_id=merchant_id,
        tenant_id=tenant_id,
        raw_body=json.dumps(payload, ensure_ascii=False),
        created_at=datetime.now(),
    )
    db.add(event)
    db.flush()
    return event


def _find_lead_by_session(
    db: Session,
    *,
    account_open_id: str,
    conversation_short_id: str,
) -> DouyinLead | None:
    return (
        db.query(DouyinLead)
        .filter(
            DouyinLead.account_open_id == account_open_id,
            DouyinLead.conversation_short_id == conversation_short_id,
        )
        .first()
    )


def upsert_lead_from_webhook(
    db: Session,
    payload: dict[str, Any],
    contact_result: ContactExtractResult,
    *,
    content: dict[str, Any],
    message_text: str,
    account_open_id: str,
    conversation_short_id: str,
    merchant_id: str,
) -> tuple[DouyinLead, str]:
    """按企业号 + 会话维度创建或更新有效线索。"""
    from_user_id = payload.get("from_user_id") or ""
    if not from_user_id:
        raise ValueError("webhook payload 缺少 from_user_id")

    nick_name, _avatar = _extract_user_profile(payload)
    customer_contact = contact_result.phone or contact_result.wechat
    raw_data = {
        "webhook_payload": payload,
        "parsed_content": content,
        "raw_message_text": message_text,
        "contact_extract": {
            "phone": contact_result.phone,
            "wechat": contact_result.wechat,
            "phones": contact_result.phones,
            "wechats": contact_result.wechats,
            "all_contacts": contact_result.all_contacts,
            "status": contact_result.status,
            "failure_reason": contact_result.failure_reason,
        },
    }
    existing = _find_lead_by_session(
        db,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if existing is None:
        lead = DouyinLead(
            source="douyin",
            source_id=from_user_id,
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            customer_name=nick_name or "未命名客户",
            customer_contact=customer_contact,
            content=message_text,
            lead_type="私信",
            raw_data=json.dumps(raw_data, ensure_ascii=False),
            status="pending",
        )
        db.add(lead)
        db.flush()
        return lead, "created"
    if existing.status == "pending":
        existing.customer_name = nick_name or existing.customer_name or "未命名客户"
        existing.customer_contact = customer_contact or existing.customer_contact
        existing.content = message_text or existing.content
        existing.raw_data = json.dumps(raw_data, ensure_ascii=False)
        db.flush()
        return existing, "updated"
    return existing, "skipped"


def _resolve_bound_merchant_id(db: Session, account_open_id: str | None) -> tuple[str | None, str]:
    if not account_open_id:
        return None, "merchant_unresolved"
    account = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id, DouyinAuthorizedAccount.bind_status == 1)
        .first()
    )
    if account is None:
        return None, "unbound_account"
    if not account.merchant_id:
        return None, "merchant_unresolved"
    return account.merchant_id, "bound"


def process_internal_webhook_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """处理 9202 internal webhook 事件。

    委托 9000 共享处理核心，确保两个入口使用一致的原子占位、商户归属解析、
    派单、im_send_msg 后置处理和事件字段合同；结果不依赖哪个入口先胜出。
    """
    from app.integrations.douyin_webhook import process_webhook_event
    return process_webhook_event(db, payload)
