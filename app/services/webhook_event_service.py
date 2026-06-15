"""Read-only service for raw Douyin webhook events."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import is_text_message, normalize_message_text, parse_content
from app.models import DouyinWebhookEvent
from app.services.contact_extractor import extract_contacts_from_text


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


def list_webhook_events(db: Session, filters: WebhookEventFilters) -> dict[str, Any]:
    """List raw webhook events with compatibility inference."""
    page = max(filters.page, 1)
    page_size = min(max(filters.page_size, 1), 100)

    query = db.query(DouyinWebhookEvent)
    query = _apply_db_filters(query, filters)

    rows = query.order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc()).all()
    enriched = [_to_event_dict(row, include_raw_body=False) for row in rows]

    if filters.lead_action:
        enriched = [item for item in enriched if item["lead_action"] == filters.lead_action]

    total = len(enriched)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": enriched[start:end],
    }


def get_webhook_event_detail(db: Session, event_id: int) -> dict[str, Any] | None:
    """Get one raw webhook event with parsed summary and raw payload."""
    row = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == event_id).first()
    if row is None:
        return None
    return _to_event_dict(row, include_raw_body=True)


def _apply_db_filters(query, filters: WebhookEventFilters):
    if filters.event:
        query = query.filter(DouyinWebhookEvent.event == filters.event)
    if filters.is_duplicate is not None:
        query = query.filter(DouyinWebhookEvent.is_duplicate == (1 if filters.is_duplicate else 0))
    if filters.start_time:
        query = query.filter(DouyinWebhookEvent.created_at >= filters.start_time)
    if filters.end_time:
        query = query.filter(DouyinWebhookEvent.created_at <= filters.end_time)
    if filters.keyword:
        like = f"%{filters.keyword}%"
        query = query.filter(or_(DouyinWebhookEvent.event_key.like(like), DouyinWebhookEvent.raw_body.like(like)))
    return query


def _to_event_dict(row: DouyinWebhookEvent, *, include_raw_body: bool) -> dict[str, Any]:
    raw_payload, raw_error = _parse_raw_body(row.raw_body)
    summary = _summarize_payload(row, raw_payload, raw_error)
    data = {
        "id": row.id,
        "event": row.event,
        "from_user_id": row.from_user_id,
        "to_user_id": row.to_user_id,
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
        data["raw_body"] = raw_payload
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
