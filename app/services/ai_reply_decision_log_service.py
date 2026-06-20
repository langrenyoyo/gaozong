"""AI 回复决策日志服务。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AiReplyDecisionLog

logger = logging.getLogger(__name__)


def record_ai_reply_decision(
    db: Session,
    *,
    context: RequestContext,
    conversation_id: str,
    account_open_id: str | int | None,
    latest_message: str,
    agent_id: str | None,
    agent_name: str | None,
    allowed_category_keys: list[str],
    upstream_raw_result: dict[str, Any],
    final_result: dict[str, Any],
    upstream_auto_send: bool,
) -> int | None:
    """记录 AI 回复建议决策日志，成功返回日志 ID，失败不影响主链路。"""
    try:
        log = AiReplyDecisionLog(
            merchant_id=str(context.merchant_id or ""),
            tenant_id=context.source_system,
            account_open_id=_optional_str(account_open_id),
            conversation_id=str(conversation_id),
            conversation_short_id=str(conversation_id),
            open_id=_optional_str(final_result.get("open_id")),
            customer_open_id=_optional_str(final_result.get("customer_open_id")),
            agent_id=_optional_str(final_result.get("agent_id")) or _optional_str(agent_id),
            agent_name=_optional_str(final_result.get("agent_name")) or _optional_str(agent_name),
            latest_message=latest_message,
            reply_text=_optional_str(final_result.get("reply_text")),
            intent=_optional_str(final_result.get("intent")),
            lead_level=_optional_str(final_result.get("lead_level")),
            confidence=final_result.get("confidence"),
            manual_required=_bool_to_int(final_result.get("manual_required"), default=True),
            manual_required_reason=_optional_str(final_result.get("manual_required_reason")),
            risk_flags_json=_json_dumps(final_result.get("risk_flags")),
            tags_json=_json_dumps(final_result.get("tags")),
            rag_sources_json=_json_dumps(final_result.get("rag_sources")),
            source_chunks_json=_json_dumps(final_result.get("source_chunks")),
            allowed_category_keys_json=_json_dumps(allowed_category_keys),
            llm_used=_bool_to_int(final_result.get("llm_used"), default=False),
            rag_used=_bool_to_int(final_result.get("rag_used"), default=False),
            upstream_auto_send=1 if upstream_auto_send else 0,
            final_auto_send=_bool_to_int(final_result.get("auto_send"), default=False),
            decision_version=_optional_str(final_result.get("decision_version")),
            raw_response_json=_json_dumps(upstream_raw_result),
            created_at=datetime.now(),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log.id
    except Exception as exc:
        db.rollback()
        logger.warning(
            "ai_reply_decision_log_failed stage=record_ai_reply_decision merchant_id=%s conversation_id=%s agent_id=%s error_type=%s",
            context.merchant_id,
            conversation_id,
            agent_id,
            type(exc).__name__,
        )
        return None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _bool_to_int(value: Any, *, default: bool) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value is None:
        return 1 if default else 0
    return 1 if bool(value) else 0
