"""抖音原始 webhook 事件的只读服务"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import is_text_message, normalize_message_text, parse_content
from app.models import DouyinWebhookEvent
from app.services.contact_extractor import extract_contacts_from_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookEventFilters:
    page: int = 1
    page_size: int = 20
    event: str | None = None
    lead_action: str | None = None
    is_duplicate: bool | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    keyword: str | None = None
    open_id: str | None = None
    conversation_short_id: str | None = None
    lead_id: int | None = None


def list_webhook_events(
    db: Session,
    filters: WebhookEventFilters,
    *,
    merchant_id: str | None = None,
    super_admin: bool = False,
) -> dict[str, Any]:
    """List raw webhook events with compatibility inference.

    普通商户只返回 event.merchant_id 匹配当前商户的已确认归属事件；
    merchant_id IS NULL 的历史事件对普通商户不可见。super_admin/mock 看全部。
    普通商户只隐藏 raw_body，已授权解析字段（message_text/customer_contact 等）
    完整展示，不做脱敏；只有发送给 LLM 的回复上下文才脱敏。
    """
    start = time.perf_counter()
    page = max(filters.page, 1)
    page_size = min(max(filters.page_size, 1), 100)

    if not super_admin and not merchant_id:
        # 无可信商户上下文：不返回任何事件，防跨商户泄露。
        return {"page": page, "page_size": page_size, "total": 0, "items": []}

    query = db.query(DouyinWebhookEvent)
    query = _apply_db_filters(query, filters)
    if not super_admin:
        query = query.filter(DouyinWebhookEvent.merchant_id == merchant_id)
    requires_post_filter = bool(filters.lead_action or filters.open_id)

    if not requires_post_filter:
        total = query.count()
        rows = (
            query.order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        enriched = [_to_event_dict(row, include_raw_body=False, super_admin=super_admin) for row in rows]
        logger.info(
            "webhook_events_query stage=finish mode=db_page page=%s page_size=%s total=%s result_count=%s elapsed_ms=%s",
            page,
            page_size,
            total,
            len(enriched),
            _elapsed_ms(start),
        )
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": enriched,
        }

    rows = query.order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc()).limit(1000).all()
    if filters.open_id:
        rows = [row for row in rows if _row_matches_open_id(row, filters.open_id)]
    enriched = [_to_event_dict(row, include_raw_body=False, super_admin=super_admin) for row in rows]

    if filters.lead_action:
        enriched = [item for item in enriched if item["lead_action"] == filters.lead_action]
    if filters.conversation_short_id:
        enriched = [
            item
            for item in enriched
            if item["conversation_short_id"] == filters.conversation_short_id
        ]

    total = len(enriched)
    page_start = (page - 1) * page_size
    page_end = page_start + page_size
    logger.info(
        "webhook_events_query stage=finish mode=post_filter page=%s page_size=%s total=%s result_count=%s elapsed_ms=%s",
        page,
        page_size,
        total,
        len(enriched[page_start:page_end]),
        _elapsed_ms(start),
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": enriched[page_start:page_end],
    }


def get_webhook_event_detail(
    db: Session,
    event_id: int,
    *,
    merchant_id: str | None = None,
    super_admin: bool = False,
) -> dict[str, Any] | None:
    """Get one raw webhook event with parsed summary and raw payload.

    普通商户只能查看自己商户已确认归属的事件；他商户事件或 merchant_id 为空的历史
    事件统一返回 None，由路由映射防枚举 404。super_admin/mock 可查看任意事件。
    普通商户只隐藏 raw_body，已授权解析字段完整展示，不脱敏。
    """
    row = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == event_id).first()
    if row is None:
        return None
    if not super_admin:
        if not merchant_id or not row.merchant_id or str(row.merchant_id) != str(merchant_id):
            return None
    return _to_event_dict(row, include_raw_body=True, super_admin=super_admin)


def _apply_db_filters(query, filters: WebhookEventFilters):
    if filters.event:
        query = query.filter(DouyinWebhookEvent.event == filters.event)
    if filters.is_duplicate is not None:
        query = query.filter(DouyinWebhookEvent.is_duplicate.is_(bool(filters.is_duplicate)))
    if filters.start_time:
        query = query.filter(DouyinWebhookEvent.created_at >= filters.start_time)
    if filters.end_time:
        query = query.filter(DouyinWebhookEvent.created_at <= filters.end_time)
    if filters.keyword:
        like = f"%{filters.keyword}%"
        query = query.filter(or_(DouyinWebhookEvent.event_key.like(like), DouyinWebhookEvent.raw_body.like(like)))
    if filters.lead_id is not None:
        query = query.filter(DouyinWebhookEvent.lead_id == filters.lead_id)
    if filters.conversation_short_id:
        like = f"%{filters.conversation_short_id}%"
        query = query.filter(
            or_(
                DouyinWebhookEvent.conversation_short_id == filters.conversation_short_id,
                DouyinWebhookEvent.raw_body.like(like),
            )
        )
    if filters.open_id:
        like = f"%{filters.open_id}%"
        query = query.filter(
            or_(
                DouyinWebhookEvent.from_user_id == filters.open_id,
                DouyinWebhookEvent.to_user_id == filters.open_id,
                DouyinWebhookEvent.raw_body.like(like),
            )
        )
    return query


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _to_event_dict(
    row: DouyinWebhookEvent,
    *,
    include_raw_body: bool,
    super_admin: bool = False,
) -> dict[str, Any]:
    raw_payload, raw_error = _parse_raw_body(row.raw_body)
    summary = _summarize_payload(row, raw_payload, raw_error)
    open_id_fields = _extract_open_id_fields(raw_payload)
    profile_fields = _extract_profile_fields(row, raw_payload)
    # 已授权解析字段（message_text/customer_contact 等）对所属商户完整展示，不脱敏；
    # 只有发送给 LLM 的回复上下文才脱敏。非管理员 raw_body 始终为 null。
    data = {
        "id": row.id,
        "event": row.event,
        "from_user_id": row.from_user_id,
        "to_user_id": row.to_user_id,
        **open_id_fields,
        **profile_fields,
        "event_key": row.event_key,
        "is_duplicate": bool(row.is_duplicate),
        "lead_id": row.lead_id,
        "lead_action": summary["lead_action"],
        "created_at": row.created_at,
        "server_message_id": summary["server_message_id"],
        "conversation_short_id": summary["conversation_short_id"],
        "message_text": summary["message_text"],
        "contact_extract_status": summary["contact_extract_status"],
        "customer_contact": summary["customer_contact"],
        "failure_reason": summary["failure_reason"],
    }
    if include_raw_body:
        # 普通商户不返回完整 raw_body（含原始 payload）；super_admin 保留。
        data["raw_body"] = raw_payload if super_admin else None
    return data


def _parse_raw_body(raw_body: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not raw_body:
        return None, "invalid_raw_body"
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None, "invalid_raw_body"
    if not isinstance(payload, dict):
        return None, "invalid_raw_body"
    return payload, None


def _summarize_payload(
    row: DouyinWebhookEvent,
    payload: dict[str, Any] | None,
    raw_error: str | None,
) -> dict[str, Any]:
    if raw_error or payload is None:
        return _summary(
            lead_action="invalid_content",
            contact_extract_status="parse_failed",
            failure_reason=raw_error or "invalid_raw_body",
        )

    content = parse_content(payload.get("content"))
    content_invalid = bool(payload.get("content")) and not content
    message_text = normalize_message_text(content)
    server_message_id = _optional_str(content.get("server_message_id"))
    conversation_short_id = _optional_str(content.get("conversation_short_id"))

    # First-version compatibility inference from existing columns/raw_body.
    # Future structured DB fields can replace this query-time derivation.
    if row.is_duplicate:
        return _summary("duplicate_event", message_text, server_message_id, conversation_short_id)
    if row.lead_id is not None:
        contact = extract_contacts_from_text(message_text)
        return _summary(
            "valid_lead",
            message_text,
            server_message_id,
            conversation_short_id,
            contact_extract_status=contact.status,
            customer_contact=contact.phone or contact.wechat,
            failure_reason=contact.failure_reason,
        )
    if row.event != "im_receive_msg":
        return _summary("non_lead_event", message_text, server_message_id, conversation_short_id)
    if content_invalid:
        return _summary(
            "invalid_content",
            message_text,
            server_message_id,
            conversation_short_id,
            contact_extract_status="parse_failed",
            failure_reason="invalid_content",
        )
    if not is_text_message(content):
        return _summary(
            "non_text_message",
            message_text,
            server_message_id,
            conversation_short_id,
            contact_extract_status="not_matched",
            failure_reason="non_text_message",
        )

    contact = extract_contacts_from_text(message_text)
    if contact.status == "matched" and (contact.phone or contact.wechat):
        return _summary(
            "unknown",
            message_text,
            server_message_id,
            conversation_short_id,
            contact_extract_status=contact.status,
            customer_contact=contact.phone or contact.wechat,
            failure_reason=None,
        )
    return _summary(
        "invalid_contact",
        message_text,
        server_message_id,
        conversation_short_id,
        contact_extract_status=contact.status,
        failure_reason=contact.failure_reason,
    )


def _summary(
    lead_action: str,
    message_text: str | None = None,
    server_message_id: str | None = None,
    conversation_short_id: str | None = None,
    *,
    contact_extract_status: str | None = None,
    customer_contact: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "lead_action": lead_action,
        "message_text": message_text,
        "server_message_id": server_message_id,
        "conversation_short_id": conversation_short_id,
        "contact_extract_status": contact_extract_status,
        "customer_contact": customer_contact,
        "failure_reason": failure_reason,
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _extract_open_id_fields(payload: dict[str, Any] | None) -> dict[str, str | None]:
    if payload is None:
        content: dict[str, Any] = {}
    else:
        content = parse_content(payload.get("content"))
    return {
        "body_open_id": _optional_str(payload.get("open_id")) if payload else None,
        "body_account_open_id": _optional_str(payload.get("account_open_id")) if payload else None,
        "content_open_id": _optional_str(content.get("open_id")),
        "content_account_open_id": _optional_str(content.get("account_open_id")),
    }


def _profile_from_record(record: Any) -> dict[str, str | None]:
    if not isinstance(record, dict):
        return {"nick_name": None, "avatar": None}
    return {
        "nick_name": _optional_str(record.get("nick_name") or record.get("nickname")),
        "avatar": _optional_str(record.get("avatar") or record.get("avatar_url")),
    }


def _merge_profile(
    profiles: dict[str, dict[str, str | None]],
    open_id: Any,
    profile: dict[str, str | None],
) -> None:
    open_id_text = _optional_str(open_id)
    if not open_id_text or not (profile.get("nick_name") or profile.get("avatar")):
        return
    current = profiles.get(open_id_text, {"nick_name": None, "avatar": None})
    profiles[open_id_text] = {
        "nick_name": current.get("nick_name") or profile.get("nick_name"),
        "avatar": current.get("avatar") or profile.get("avatar"),
    }


def _profile_for_open_id(
    profiles: dict[str, dict[str, str | None]],
    open_id: Any,
) -> dict[str, str | None]:
    open_id_text = _optional_str(open_id)
    if open_id_text and open_id_text in profiles:
        return profiles[open_id_text]
    return {"nick_name": None, "avatar": None}


def _customer_open_id(row: DouyinWebhookEvent, payload: dict[str, Any] | None, content: dict[str, Any]) -> str | None:
    if row.event == "im_receive_msg" and row.from_user_id:
        return row.from_user_id
    if row.event == "im_send_msg" and row.to_user_id:
        return row.to_user_id
    return (
        _optional_str(content.get("open_id"))
        or (_optional_str(payload.get("open_id")) if payload else None)
        or row.from_user_id
    )


def _extract_profile_fields(
    row: DouyinWebhookEvent,
    payload: dict[str, Any] | None,
) -> dict[str, str | None]:
    content = parse_content(payload.get("content")) if payload else {}
    profiles: dict[str, dict[str, str | None]] = {}

    if payload:
        _merge_profile(
            profiles,
            payload.get("open_id") or row.from_user_id,
            _profile_from_record(payload),
        )
    _merge_profile(
        profiles,
        content.get("open_id") or row.from_user_id,
        _profile_from_record(content),
    )

    user_infos = content.get("user_infos")
    if not isinstance(user_infos, list) and payload:
        user_infos = payload.get("user_infos")
    if isinstance(user_infos, list):
        for user in user_infos:
            if isinstance(user, dict):
                _merge_profile(profiles, user.get("open_id"), _profile_from_record(user))

    customer_profile = _profile_for_open_id(profiles, _customer_open_id(row, payload, content))
    from_profile = _profile_for_open_id(profiles, row.from_user_id)
    to_profile = _profile_for_open_id(profiles, row.to_user_id)
    return {
        "nick_name": customer_profile.get("nick_name"),
        "avatar": customer_profile.get("avatar"),
        "from_user_nick_name": from_profile.get("nick_name"),
        "from_user_avatar": from_profile.get("avatar"),
        "to_user_nick_name": to_profile.get("nick_name"),
        "to_user_avatar": to_profile.get("avatar"),
    }


def _value_matches_open_id(value: Any, open_id: str) -> bool:
    return value is not None and str(value) == open_id


def _row_matches_open_id(row: DouyinWebhookEvent, open_id: str) -> bool:
    if _value_matches_open_id(row.from_user_id, open_id):
        return True
    if _value_matches_open_id(row.to_user_id, open_id):
        return True

    payload, raw_error = _parse_raw_body(row.raw_body)
    if raw_error or payload is None:
        return False
    if _value_matches_open_id(payload.get("open_id"), open_id):
        return True
    if _value_matches_open_id(payload.get("account_open_id"), open_id):
        return True

    content = parse_content(payload.get("content"))
    return (
        _value_matches_open_id(content.get("open_id"), open_id)
        or _value_matches_open_id(content.get("account_open_id"), open_id)
    )
