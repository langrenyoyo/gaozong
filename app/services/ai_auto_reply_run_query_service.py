"""自动回复运行记录查询服务。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from app.models import (
    AiAgent,
    AiAutoReplyRun,
    AiReplyDecisionLog,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
)


SUMMARY_LIMIT = 120
PAGE_SIZE_LIMIT = 100


@dataclass
class AiAutoReplyRunQuery:
    """自动回复运行记录查询条件。"""

    merchant_id: str
    page: int = 1
    page_size: int = 20
    account_open_id: str | None = None
    conversation_short_id: str | None = None
    customer_open_id: str | None = None
    agent_id: str | None = None
    account_name: str | None = None
    customer_name: str | None = None
    agent_name: str | None = None
    status: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    keyword: str | None = None


def list_ai_auto_reply_runs(db: Session, query: AiAutoReplyRunQuery) -> dict[str, Any]:
    """查询当前商户自动回复运行记录列表。"""
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), PAGE_SIZE_LIMIT)
    base_query = _apply_filters(db, db.query(AiAutoReplyRun), query)
    total = base_query.count()
    rows = (
        base_query.order_by(AiAutoReplyRun.created_at.desc(), AiAutoReplyRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    decision_logs = _load_decision_logs(db, rows, merchant_id=query.merchant_id)
    display_names = _load_display_names(db, rows, decision_logs, merchant_id=query.merchant_id)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [
            _build_list_item(row, decision_logs.get(row.decision_log_id), display_names.get(row.id))
            for row in rows
        ],
    }


def get_ai_auto_reply_run_detail(
    db: Session,
    *,
    merchant_id: str,
    run_id: int,
) -> dict[str, Any] | None:
    """查询当前商户单条自动回复运行记录详情。"""
    row = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.id == run_id)
        .filter(AiAutoReplyRun.merchant_id == merchant_id)
        .first()
    )
    if row is None:
        return None

    decision_logs = _load_decision_logs(db, [row], merchant_id=merchant_id)
    decision = decision_logs.get(row.decision_log_id)
    display_names = _load_display_names(db, [row], decision_logs, merchant_id=merchant_id)
    data = _build_list_item(row, decision, display_names.get(row.id))
    data.update(
        {
            "latest_message": _mask_sensitive_text(row.latest_message),
            "would_send_content": _mask_sensitive_text(row.would_send_content),
            "gate_results": _json_object(row.gate_results_json),
            "send_record": _build_send_record(db, row.id),
        }
    )
    return data


def _apply_filters(db: Session, query: Query, params: AiAutoReplyRunQuery) -> Query:
    query = query.filter(AiAutoReplyRun.merchant_id == params.merchant_id)
    if params.account_open_id:
        query = query.filter(AiAutoReplyRun.account_open_id == params.account_open_id)
    if params.conversation_short_id:
        query = query.filter(AiAutoReplyRun.conversation_short_id == params.conversation_short_id)
    if params.customer_open_id:
        query = query.filter(AiAutoReplyRun.customer_open_id == params.customer_open_id)
    if params.agent_id:
        query = query.filter(AiAutoReplyRun.agent_id == params.agent_id)
    if params.account_name:
        pattern = _like_pattern(params.account_name)
        account_ids = (
            db.query(DouyinAuthorizedAccount.open_id)
            .filter(DouyinAuthorizedAccount.merchant_id == params.merchant_id)
            .filter(DouyinAuthorizedAccount.account_name.like(pattern, escape="\\"))
            .scalar_subquery()
        )
        event_ids = (
            db.query(DouyinWebhookEvent.id)
            .filter(DouyinWebhookEvent.to_user_nick_name.like(pattern, escape="\\"))
            .scalar_subquery()
        )
        query = query.filter(
            or_(AiAutoReplyRun.account_open_id.in_(account_ids), AiAutoReplyRun.trigger_event_id.in_(event_ids))
        )
    if params.customer_name:
        pattern = _like_pattern(params.customer_name)
        event_ids = (
            db.query(DouyinWebhookEvent.id)
            .outerjoin(DouyinLead, DouyinWebhookEvent.lead_id == DouyinLead.id)
            .filter(
                or_(
                    DouyinWebhookEvent.from_user_nick_name.like(pattern, escape="\\"),
                    and_(DouyinLead.merchant_id == params.merchant_id, DouyinLead.customer_name.like(pattern, escape="\\")),
                )
            )
            .scalar_subquery()
        )
        query = query.filter(AiAutoReplyRun.trigger_event_id.in_(event_ids))
    if params.agent_name:
        pattern = _like_pattern(params.agent_name)
        agent_ids = (
            db.query(AiAgent.agent_id)
            .filter(AiAgent.merchant_id == params.merchant_id)
            .filter(AiAgent.name.like(pattern, escape="\\"))
            .scalar_subquery()
        )
        decision_ids = (
            db.query(AiReplyDecisionLog.id)
            .filter(AiReplyDecisionLog.merchant_id == params.merchant_id)
            .filter(AiReplyDecisionLog.agent_name.like(pattern, escape="\\"))
            .scalar_subquery()
        )
        query = query.filter(
            or_(AiAutoReplyRun.agent_id.in_(agent_ids), AiAutoReplyRun.decision_log_id.in_(decision_ids))
        )
    if params.status:
        query = query.filter(AiAutoReplyRun.status == params.status)
    if params.created_from is not None:
        query = query.filter(AiAutoReplyRun.created_at >= params.created_from)
    if params.created_to is not None:
        query = query.filter(AiAutoReplyRun.created_at <= params.created_to)
    if params.keyword:
        pattern = _like_pattern(params.keyword)
        query = query.filter(
            or_(
                AiAutoReplyRun.latest_message.like(pattern, escape="\\"),
                AiAutoReplyRun.would_send_content.like(pattern, escape="\\"),
                AiAutoReplyRun.error_message.like(pattern, escape="\\"),
            )
        )
    return query


def _like_pattern(value: str) -> str:
    escaped = value.replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _load_decision_logs(
    db: Session,
    rows: list[AiAutoReplyRun],
    *,
    merchant_id: str,
) -> dict[int, AiReplyDecisionLog]:
    decision_ids = sorted({row.decision_log_id for row in rows if row.decision_log_id})
    if not decision_ids:
        return {}
    records = (
        db.query(AiReplyDecisionLog)
        .filter(AiReplyDecisionLog.id.in_(decision_ids))
        .filter(AiReplyDecisionLog.merchant_id == merchant_id)
        .all()
    )
    return {record.id: record for record in records}


def _load_display_names(
    db: Session,
    rows: list[AiAutoReplyRun],
    decision_logs: dict[int, AiReplyDecisionLog],
    *,
    merchant_id: str,
) -> dict[int, dict[str, str | None]]:
    if not rows:
        return {}

    account_ids = {row.account_open_id for row in rows if row.account_open_id}
    accounts = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.merchant_id == merchant_id)
        .filter(DouyinAuthorizedAccount.open_id.in_(account_ids))
        .order_by(DouyinAuthorizedAccount.last_synced_at.desc(), DouyinAuthorizedAccount.id.desc())
        .all()
        if account_ids
        else []
    )
    account_names: dict[str, str] = {}
    for account in accounts:
        name = _optional_text(account.account_name)
        if name and account.open_id not in account_names:
            account_names[account.open_id] = name

    event_ids = {row.trigger_event_id for row in rows if row.trigger_event_id}
    events = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id.in_(event_ids)).all() if event_ids else []
    events_by_id = {event.id: event for event in events}
    lead_ids = {event.lead_id for event in events if event.lead_id}
    leads = (
        db.query(DouyinLead)
        .filter(DouyinLead.merchant_id == merchant_id)
        .filter(DouyinLead.id.in_(lead_ids))
        .all()
        if lead_ids
        else []
    )
    leads_by_id = {lead.id: lead for lead in leads}

    agent_ids = {row.agent_id for row in rows if row.agent_id}
    agents = (
        db.query(AiAgent)
        .filter(AiAgent.merchant_id == merchant_id)
        .filter(AiAgent.agent_id.in_(agent_ids))
        .all()
        if agent_ids
        else []
    )
    agent_names = {agent.agent_id: agent.name for agent in agents if _optional_text(agent.name)}

    result: dict[int, dict[str, str | None]] = {}
    for row in rows:
        event = events_by_id.get(row.trigger_event_id)
        lead = leads_by_id.get(event.lead_id) if event and event.lead_id else None
        decision = decision_logs.get(row.decision_log_id)
        result[row.id] = {
            "account_name": account_names.get(row.account_open_id) or _optional_text(event.to_user_nick_name if event else None),
            "customer_name": _optional_text(event.from_user_nick_name if event else None) or _optional_text(lead.customer_name if lead else None),
            "agent_name": agent_names.get(row.agent_id) or _optional_text(decision.agent_name if decision else None),
        }
    return result


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _build_list_item(
    row: AiAutoReplyRun,
    decision: AiReplyDecisionLog | None = None,
    display_names: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    display_names = display_names or {}
    data = {
        "id": row.id,
        "merchant_id": row.merchant_id,
        "account_open_id": row.account_open_id,
        "account_name": display_names.get("account_name"),
        "conversation_short_id": row.conversation_short_id,
        "customer_open_id": row.customer_open_id,
        "customer_name": display_names.get("customer_name"),
        "trigger_event_id": row.trigger_event_id,
        "trigger_event_key": row.trigger_event_key,
        "trigger_server_message_id": row.trigger_server_message_id,
        "latest_message_summary": _summary(row.latest_message),
        "agent_id": row.agent_id,
        "agent_name": display_names.get("agent_name"),
        "mode": row.mode,
        "status": row.status,
        "skip_reason": row.skip_reason,
        "block_reason": row.block_reason,
        "decision_log_id": row.decision_log_id,
        "would_send_content_summary": _summary(row.would_send_content),
        "error_message": row.error_message,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if decision is None:
        data.update(_empty_decision_fields())
        return data
    data.update(
        {
            "reply_text": _mask_sensitive_text(decision.reply_text),
            "manual_required": bool(decision.manual_required),
            "manual_required_reason": decision.manual_required_reason,
            "risk_flags": _json_list(decision.risk_flags_json),
            "llm_used": bool(decision.llm_used),
            "rag_used": bool(decision.rag_used),
            "upstream_auto_send": bool(decision.upstream_auto_send),
            "final_auto_send": bool(decision.final_auto_send),
            "decision_version": decision.decision_version,
        }
    )
    return data


def _empty_decision_fields() -> dict[str, Any]:
    return {
        "reply_text": None,
        "manual_required": None,
        "manual_required_reason": None,
        "risk_flags": [],
        "llm_used": None,
        "rag_used": None,
        "upstream_auto_send": None,
        "final_auto_send": None,
        "decision_version": None,
    }


def _build_send_record(db: Session, run_id: int) -> dict[str, Any] | None:
    row = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.auto_reply_run_id == run_id)
        .first()
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "send_status": row.status,
        "send_source": row.send_source,
        "auto_send": bool(row.auto_send),
        "manual_confirmed": bool(row.manual_confirmed),
        "upstream_msg_id": row.upstream_msg_id,
        "error_message": row.error_message,
        "sent_at": row.sent_at,
    }


def _json_object(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw_value: str | None) -> list[Any]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _summary(value: str | None) -> str | None:
    masked = _mask_sensitive_text(value)
    if masked is None:
        return None
    return masked if len(masked) <= SUMMARY_LIMIT else f"{masked[:SUMMARY_LIMIT]}..."


def _mask_sensitive_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
