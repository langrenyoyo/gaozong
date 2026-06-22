"""自动回复运行记录查询服务。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models import AiAutoReplyRun, AiReplyDecisionLog, DouyinPrivateMessageSend


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
    status: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    keyword: str | None = None


def list_ai_auto_reply_runs(db: Session, query: AiAutoReplyRunQuery) -> dict[str, Any]:
    """查询当前商户自动回复运行记录列表。"""
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), PAGE_SIZE_LIMIT)
    base_query = _apply_filters(db.query(AiAutoReplyRun), query)
    total = base_query.count()
    rows = (
        base_query.order_by(AiAutoReplyRun.created_at.desc(), AiAutoReplyRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    decision_logs = _load_decision_logs(db, rows, merchant_id=query.merchant_id)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_build_list_item(row, decision_logs.get(row.decision_log_id)) for row in rows],
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

    decision = _load_decision_logs(db, [row], merchant_id=merchant_id).get(row.decision_log_id)
    data = _build_list_item(row, decision)
    data.update(
        {
            "latest_message": _mask_sensitive_text(row.latest_message),
            "would_send_content": _mask_sensitive_text(row.would_send_content),
            "gate_results": _json_object(row.gate_results_json),
            "send_record": _build_send_record(db, row.id),
        }
    )
    return data


def _apply_filters(query: Query, params: AiAutoReplyRunQuery) -> Query:
    query = query.filter(AiAutoReplyRun.merchant_id == params.merchant_id)
    if params.account_open_id:
        query = query.filter(AiAutoReplyRun.account_open_id == params.account_open_id)
    if params.conversation_short_id:
        query = query.filter(AiAutoReplyRun.conversation_short_id == params.conversation_short_id)
    if params.customer_open_id:
        query = query.filter(AiAutoReplyRun.customer_open_id == params.customer_open_id)
    if params.agent_id:
        query = query.filter(AiAutoReplyRun.agent_id == params.agent_id)
    if params.status:
        query = query.filter(AiAutoReplyRun.status == params.status)
    if params.created_from is not None:
        query = query.filter(AiAutoReplyRun.created_at >= params.created_from)
    if params.created_to is not None:
        query = query.filter(AiAutoReplyRun.created_at <= params.created_to)
    if params.keyword:
        keyword = params.keyword.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                AiAutoReplyRun.latest_message.like(pattern, escape="\\"),
                AiAutoReplyRun.would_send_content.like(pattern, escape="\\"),
                AiAutoReplyRun.error_message.like(pattern, escape="\\"),
            )
        )
    return query


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


def _build_list_item(row: AiAutoReplyRun, decision: AiReplyDecisionLog | None = None) -> dict[str, Any]:
    data = {
        "id": row.id,
        "merchant_id": row.merchant_id,
        "account_open_id": row.account_open_id,
        "conversation_short_id": row.conversation_short_id,
        "customer_open_id": row.customer_open_id,
        "trigger_event_id": row.trigger_event_id,
        "trigger_event_key": row.trigger_event_key,
        "trigger_server_message_id": row.trigger_server_message_id,
        "latest_message_summary": _summary(row.latest_message),
        "agent_id": row.agent_id,
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
