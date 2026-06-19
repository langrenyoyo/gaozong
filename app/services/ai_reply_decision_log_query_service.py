"""AI 回复决策日志查询服务。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models import AiReplyDecisionLog


SUMMARY_LIMIT = 120
PAGE_SIZE_LIMIT = 100


@dataclass
class AiReplyDecisionLogQuery:
    """AI 回复决策日志查询条件。"""

    merchant_id: str
    page: int = 1
    page_size: int = 20
    account_open_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    manual_required: bool | None = None
    intent: str | None = None
    lead_level: str | None = None
    risk_flag: str | None = None
    rag_used: bool | None = None
    llm_used: bool | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    keyword: str | None = None


def list_ai_reply_decision_logs(db: Session, query: AiReplyDecisionLogQuery) -> dict[str, Any]:
    """查询当前商户 AI 回复决策日志列表。"""
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), PAGE_SIZE_LIMIT)
    base_query = _apply_filters(db.query(AiReplyDecisionLog), query)

    total = base_query.count()
    rows = (
        base_query.order_by(AiReplyDecisionLog.created_at.desc(), AiReplyDecisionLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_build_list_item(row) for row in rows],
    }


def get_ai_reply_decision_log_detail(
    db: Session,
    *,
    merchant_id: str,
    log_id: int,
) -> dict[str, Any] | None:
    """查询当前商户单条 AI 回复决策日志详情。"""
    row = (
        db.query(AiReplyDecisionLog)
        .filter(
            AiReplyDecisionLog.id == log_id,
            AiReplyDecisionLog.merchant_id == merchant_id,
        )
        .first()
    )
    if row is None:
        return None

    data = _build_list_item(row)
    data.update(
        {
            "latest_message": _mask_sensitive_text(row.latest_message),
            "reply_text": _mask_sensitive_text(row.reply_text),
            "rag_sources": _json_list(row.rag_sources_json),
            "source_chunks": _json_list(row.source_chunks_json),
            "allowed_category_keys": _json_list(row.allowed_category_keys_json),
        }
    )
    return data


def _apply_filters(query: Query, params: AiReplyDecisionLogQuery) -> Query:
    query = query.filter(AiReplyDecisionLog.merchant_id == params.merchant_id)

    if params.account_open_id:
        query = query.filter(AiReplyDecisionLog.account_open_id == params.account_open_id)
    if params.conversation_id:
        query = query.filter(AiReplyDecisionLog.conversation_id == params.conversation_id)
    if params.agent_id:
        query = query.filter(AiReplyDecisionLog.agent_id == params.agent_id)
    if params.manual_required is not None:
        query = query.filter(AiReplyDecisionLog.manual_required == _bool_to_int(params.manual_required))
    if params.intent:
        query = query.filter(AiReplyDecisionLog.intent == params.intent)
    if params.lead_level:
        query = query.filter(AiReplyDecisionLog.lead_level == params.lead_level)
    if params.risk_flag:
        escaped = params.risk_flag.replace("%", r"\%").replace("_", r"\_")
        query = query.filter(AiReplyDecisionLog.risk_flags_json.like(f'%"{escaped}"%', escape="\\"))
    if params.rag_used is not None:
        query = query.filter(AiReplyDecisionLog.rag_used == _bool_to_int(params.rag_used))
    if params.llm_used is not None:
        query = query.filter(AiReplyDecisionLog.llm_used == _bool_to_int(params.llm_used))
    if params.date_from is not None:
        query = query.filter(AiReplyDecisionLog.created_at >= params.date_from)
    if params.date_to is not None:
        query = query.filter(AiReplyDecisionLog.created_at <= params.date_to)
    if params.keyword:
        keyword = params.keyword.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                AiReplyDecisionLog.latest_message.like(pattern, escape="\\"),
                AiReplyDecisionLog.reply_text.like(pattern, escape="\\"),
            )
        )
    return query


def _build_list_item(row: AiReplyDecisionLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "merchant_id": row.merchant_id,
        "account_open_id": row.account_open_id,
        "conversation_id": row.conversation_id,
        "agent_id": row.agent_id,
        "agent_name": row.agent_name,
        "latest_message_summary": _summary(row.latest_message),
        "reply_text_summary": _summary(row.reply_text),
        "intent": row.intent,
        "lead_level": row.lead_level,
        "confidence": row.confidence,
        "manual_required": bool(row.manual_required),
        "manual_required_reason": row.manual_required_reason,
        "risk_flags": _json_list(row.risk_flags_json),
        "tags": _json_list(row.tags_json),
        "rag_used": bool(row.rag_used),
        "llm_used": bool(row.llm_used),
        "upstream_auto_send": bool(row.upstream_auto_send),
        "final_auto_send": bool(row.final_auto_send),
        "decision_version": row.decision_version,
        "created_at": row.created_at,
    }


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


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0
