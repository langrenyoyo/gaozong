"""AI 回复实发记录查询服务。

Phase 4-FIX1：列表/详情/有效性标记统一为「决策日志粒度」——
每个 AiReplyDecisionLog 只展示其最新一条关联发送流水（按发送流水自增 id 取最新），
避免同一决策多条发送时列表行与详情内容错配。
有效性字段仍存储在 AiReplyDecisionLog，因此查询必须与决策日志粒度一致。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.models import AiReplyDecisionLog, DouyinPrivateMessageSend


SUMMARY_LIMIT = 120
PAGE_SIZE_LIMIT = 100


@dataclass
class AiReplyDecisionLogQuery:
    """AI 回复实发记录查询条件。

    merchant_id 为 None 时代表超管跨商户查询；普通商户调用必须传可信商户 ID。
    """

    merchant_id: str | None = None
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
    send_status: str | None = None
    is_effective: bool | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    keyword: str | None = None


def _sent_records_query(db: Session) -> Query:
    """基础联表查询：每条 AI 决策只取最新一条关联发送流水。

    有效性字段存储在 AiReplyDecisionLog 上，列表/详情必须与决策日志粒度一致，
    因此用子查询按 decision_log_id 分组取 max(send.id)，再回连主表。
    普通人工发送 send_source="manual" 且 decision_log_id 为空不会进入子查询。
    """
    latest_send_ids = (
        db.query(
            DouyinPrivateMessageSend.decision_log_id.label("decision_log_id"),
            func.max(DouyinPrivateMessageSend.id).label("send_record_id"),
        )
        .filter(DouyinPrivateMessageSend.decision_log_id.isnot(None))
        .filter(
            or_(
                DouyinPrivateMessageSend.send_source == "ai_auto",
                DouyinPrivateMessageSend.decision_log_id.isnot(None),
            )
        )
        .group_by(DouyinPrivateMessageSend.decision_log_id)
        .subquery()
    )
    return (
        db.query(DouyinPrivateMessageSend, AiReplyDecisionLog)
        .join(latest_send_ids, DouyinPrivateMessageSend.id == latest_send_ids.c.send_record_id)
        .join(
            AiReplyDecisionLog,
            DouyinPrivateMessageSend.decision_log_id == AiReplyDecisionLog.id,
        )
    )


def list_ai_reply_decision_logs(db: Session, query: AiReplyDecisionLogQuery) -> dict[str, Any]:
    """查询 AI 回复实发记录列表（决策日志粒度）。"""
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), PAGE_SIZE_LIMIT)
    base_query = _apply_filters(_sent_records_query(db), query)

    total = base_query.count()
    rows = (
        base_query.order_by(
            DouyinPrivateMessageSend.sent_at.desc().nullslast(),
            DouyinPrivateMessageSend.created_at.desc(),
            DouyinPrivateMessageSend.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_build_list_item(send, decision) for send, decision in rows],
    }


def get_ai_reply_decision_log_detail(
    db: Session,
    *,
    merchant_id: str | None,
    log_id: int,
) -> dict[str, Any] | None:
    """查询单条 AI 回复实发记录详情。

    merchant_id 为 None 时代表超管跨商户查询；普通商户调用必须传可信商户 ID。
    必须存在关联发送流水，否则返回 None（即未发送的纯决策日志不计入实发记录）。
    """
    row = (
        _apply_filters(
            _sent_records_query(db),
            AiReplyDecisionLogQuery(merchant_id=merchant_id),
        )
        .filter(AiReplyDecisionLog.id == log_id)
        .order_by(
            DouyinPrivateMessageSend.sent_at.desc().nullslast(),
            DouyinPrivateMessageSend.created_at.desc(),
            DouyinPrivateMessageSend.id.desc(),
        )
        .first()
    )
    if row is None:
        return None
    send, decision = row
    data = _build_list_item(send, decision)
    data.update(
        {
            "latest_message": _mask_sensitive_text(decision.latest_message),
            "reply_text": _mask_sensitive_text(decision.reply_text),
            "rag_sources": _json_list(decision.rag_sources_json),
            "source_chunks": _json_list(decision.source_chunks_json),
            "allowed_category_keys": _json_list(decision.allowed_category_keys_json),
            "sent_content": _mask_sensitive_text(send.content),
        }
    )
    return data


def _apply_filters(query: Query, params: AiReplyDecisionLogQuery) -> Query:
    if params.merchant_id:
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
    if params.send_status:
        query = query.filter(DouyinPrivateMessageSend.status == params.send_status)
    if params.is_effective is not None:
        query = query.filter(AiReplyDecisionLog.is_effective.is_(params.is_effective))
    if params.date_from is not None:
        query = query.filter(DouyinPrivateMessageSend.created_at >= params.date_from)
    if params.date_to is not None:
        query = query.filter(DouyinPrivateMessageSend.created_at <= params.date_to)
    if params.keyword:
        keyword = params.keyword.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                AiReplyDecisionLog.latest_message.like(pattern, escape="\\"),
                AiReplyDecisionLog.reply_text.like(pattern, escape="\\"),
                DouyinPrivateMessageSend.content.like(pattern, escape="\\"),
            )
        )
    return query


def _build_list_item(
    send: DouyinPrivateMessageSend,
    decision: AiReplyDecisionLog,
) -> dict[str, Any]:
    return {
        "id": decision.id,
        "send_record_id": send.id,
        "merchant_id": decision.merchant_id,
        "account_open_id": decision.account_open_id,
        "conversation_id": decision.conversation_id,
        "agent_id": decision.agent_id,
        "agent_name": decision.agent_name,
        "latest_message_summary": _summary(decision.latest_message),
        "reply_text_summary": _summary(decision.reply_text),
        "sent_content_summary": _summary(send.content),
        "send_status": send.status,
        "send_source": send.send_source,
        "auto_send": bool(send.auto_send),
        "manual_confirmed": bool(send.manual_confirmed),
        "upstream_msg_id": send.upstream_msg_id,
        "sent_at": send.sent_at,
        "send_created_at": send.created_at,
        "intent": decision.intent,
        "lead_level": decision.lead_level,
        "confidence": decision.confidence,
        "manual_required": bool(decision.manual_required),
        "manual_required_reason": decision.manual_required_reason,
        "risk_flags": _json_list(decision.risk_flags_json),
        "tags": _json_list(decision.tags_json),
        "rag_used": bool(decision.rag_used),
        "llm_used": bool(decision.llm_used),
        "upstream_auto_send": bool(decision.upstream_auto_send),
        "final_auto_send": bool(decision.final_auto_send),
        "decision_version": decision.decision_version,
        "model": decision.model,
        "is_effective": decision.is_effective,
        # 有效性原因属自由文本，展示前统一脱敏手机号与微信号
        "effectiveness_reason": _mask_sensitive_text(decision.effectiveness_reason),
        "created_at": decision.created_at,
    }


def mask_ai_reply_sensitive_text(value: str | None) -> str | None:
    """脱敏 AI 回复记录中允许展示或审计的自由文本（供路由复用同一规则）。"""
    return _mask_sensitive_text(value)


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
    """脱敏手机号与微信号。

    微信号前缀可能紧贴中文（如「微信wxid_xxx」），用负回顾断言 (?<![A-Za-z0-9_])
    代替 \\b，避免中文（Python re 默认属 \\w）与前缀字母之间不构成词边界而漏匹配。
    """
    if value is None:
        return None
    text = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
    return re.sub(
        r"(?<![A-Za-z0-9_])(wxid|wx|wechat)[A-Za-z0-9_\-]{4,}",
        r"\1***",
        text,
        flags=re.IGNORECASE,
    )


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0
