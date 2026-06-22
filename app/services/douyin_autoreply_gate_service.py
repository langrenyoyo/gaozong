"""抖音自动回复 dry-run 门禁服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import config
from app.models import AiAgent, AiAutoReplyRun, DouyinAccountAgentBinding, DouyinAccountAutoreplySetting
from app.services.conversation_autopilot_state_service import is_conversation_manual_takeover
from app.services.douyin_autoreply_settings_service import (
    parse_allowed_intents,
    parse_blocked_risk_flags,
    parse_conversation_whitelist_ids,
    parse_customer_whitelist_open_ids,
    parse_direct_llm_policy,
)

COUNTED_RUN_STATUSES = ("blocked", "decided", "failed")


@dataclass(frozen=True)
class GateDecision:
    """门禁评估结果。"""

    passed: bool
    status: str | None = None
    reason: str | None = None
    gate_results: dict[str, Any] | None = None


def evaluate_pre_llm_gates(
    db: Session,
    *,
    settings: DouyinAccountAutoreplySetting | None,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str | None,
    latest_message: str | None,
    latest_message_state: dict[str, Any] | None,
    now: datetime | None = None,
) -> GateDecision:
    """评估调用 9100 前的配置、接管、频控和最新消息门禁。"""
    current_time = now or datetime.now()
    gate_results: dict[str, Any] = {
        "settings": _settings_snapshot(settings),
        "latest_message_state": latest_message_state or {},
    }
    if settings is None:
        return GateDecision(False, "skipped", "no_autoreply_settings", gate_results)
    if settings.enabled is not True:
        return GateDecision(False, "skipped", "autoreply_disabled", gate_results)
    if not str(latest_message or "").strip():
        return GateDecision(False, "skipped", "empty_message", gate_results)
    if not conversation_short_id:
        return GateDecision(False, "skipped", "conversation_missing", gate_results)
    if is_conversation_manual_takeover(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        now=current_time,
    ):
        return GateDecision(False, "blocked", "manual_takeover", gate_results)

    if latest_message_state and latest_message_state.get("latest_is_customer_message") is False:
        return GateDecision(False, "blocked", "latest_message_not_customer", gate_results)

    frequency = _frequency_snapshot(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        since=current_time - timedelta(hours=1),
    )
    gate_results["frequency"] = frequency
    if frequency["conversation_count"] >= int(settings.max_replies_per_conversation_per_hour or 0):
        return GateDecision(False, "blocked", "frequency_conversation_exceeded", gate_results)
    if frequency["account_count"] >= int(settings.max_replies_per_account_per_hour or 0):
        return GateDecision(False, "blocked", "frequency_account_exceeded", gate_results)
    return GateDecision(True, gate_results=gate_results)


def evaluate_post_llm_gates(
    *,
    settings: DouyinAccountAutoreplySetting,
    result: dict[str, Any],
    upstream_auto_send: bool,
) -> GateDecision:
    """评估 9100 决策后的安全门禁。"""
    allowed_intents = parse_allowed_intents(settings)
    blocked_risk_flags = parse_blocked_risk_flags(settings)
    risk_flags = _string_list(result.get("risk_flags"))
    rag_sources = result.get("rag_sources") or []
    confidence = _float_or_zero(result.get("confidence"))
    intent = str(result.get("intent") or "").strip()
    gate_results = {
        "send_disabled": settings.send_enabled is not True,
        "manual_required": result.get("manual_required"),
        "risk_flags": risk_flags,
        "blocked_risk_flags": blocked_risk_flags,
        "require_rag": settings.require_rag is True,
        "rag_used": result.get("rag_used"),
        "require_rag_sources": settings.require_rag_sources is True,
        "rag_sources_count": len(rag_sources) if isinstance(rag_sources, list) else 0,
        "confidence": confidence,
        "min_confidence": float(settings.min_confidence or 0),
        "intent": intent,
        "allowed_intents": allowed_intents,
        "upstream_auto_send": upstream_auto_send,
        "final_auto_send": False,
    }

    if not upstream_auto_send:
        return GateDecision(False, "blocked", "upstream_auto_send_disabled", gate_results)
    if result.get("manual_required") is True:
        return GateDecision(False, "blocked", "manual_required", gate_results)
    if risk_flags and (not blocked_risk_flags or any(flag in blocked_risk_flags for flag in risk_flags)):
        return GateDecision(False, "blocked", "risk_flags", gate_results)
    if settings.require_rag is True and result.get("rag_used") is not True and not _allows_direct_llm_without_rag(settings, intent):
        return GateDecision(False, "blocked", "rag_not_used", gate_results)
    if settings.require_rag_sources is True and not rag_sources and not _allows_direct_llm_without_rag(settings, intent):
        return GateDecision(False, "blocked", "rag_sources_empty", gate_results)
    if confidence < float(settings.min_confidence or 0):
        return GateDecision(False, "blocked", "confidence_low", gate_results)
    if allowed_intents and intent not in allowed_intents:
        return GateDecision(False, "blocked", "intent_not_allowed", gate_results)
    return GateDecision(True, "decided", None, gate_results)


def evaluate_real_send_gates(
    db: Session,
    *,
    settings: DouyinAccountAutoreplySetting | None,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str | None,
    conversation_short_id: str | None,
    now: datetime | None = None,
) -> GateDecision:
    """集中评估真实自动发送门禁；任一失败都返回稳定 reason code。"""
    current_time = now or datetime.now()
    allow_full_rollout = config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT is True
    global_account_hit = account_open_id in config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET
    global_customer_hit = bool(
        customer_open_id and customer_open_id in config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET
    )
    global_conversation_hit = bool(
        conversation_short_id
        and conversation_short_id in config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET
    )
    gate_results: dict[str, Any] = {
        "global": {
            "auto_reply_enabled": bool(config.DOUYIN_AUTO_REPLY_ENABLED),
            "real_send_enabled": bool(config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED),
            "allow_full_rollout": allow_full_rollout,
            "mode": "full_rollout" if allow_full_rollout else "whitelist",
            "account_whitelist_required": not allow_full_rollout,
            "customer_or_conversation_whitelist_required": not allow_full_rollout,
            "account_whitelist_hit": global_account_hit,
            "customer_whitelist_hit": global_customer_hit,
            "conversation_whitelist_hit": global_conversation_hit,
        },
        "settings": _settings_snapshot(settings),
    }
    if config.DOUYIN_AUTO_REPLY_ENABLED is not True:
        return GateDecision(False, "blocked", "global_auto_reply_disabled", gate_results)
    if config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED is not True:
        return GateDecision(False, "blocked", "global_real_send_disabled", gate_results)
    if not allow_full_rollout and not global_account_hit:
        return GateDecision(False, "blocked", "global_account_whitelist_missed", gate_results)
    if not allow_full_rollout and not (global_customer_hit or global_conversation_hit):
        return GateDecision(False, "blocked", "global_customer_or_conversation_whitelist_missed", gate_results)
    if settings is None:
        return GateDecision(False, "blocked", "no_autoreply_settings", gate_results)
    if settings.enabled is not True:
        return GateDecision(False, "blocked", "account_settings_disabled", gate_results)
    if settings.send_enabled is not True:
        return GateDecision(False, "blocked", "account_send_disabled", gate_results)

    agent_binding = _agent_binding_snapshot(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
    )
    gate_results["agent_binding"] = agent_binding
    if agent_binding["has_active_agent"] is not True:
        return GateDecision(False, "blocked", "no_bound_agent", gate_results)

    customer_whitelist = parse_customer_whitelist_open_ids(settings)
    conversation_whitelist = parse_conversation_whitelist_ids(settings)
    gate_results["account_level_whitelist"] = {
        "customer_configured": bool(customer_whitelist),
        "conversation_configured": bool(conversation_whitelist),
        "required": bool(customer_whitelist or conversation_whitelist),
        "mode": "optional_narrowing" if allow_full_rollout else "required_narrowing",
        "customer_hit": bool(customer_open_id and customer_open_id in customer_whitelist),
        "conversation_hit": bool(conversation_short_id and conversation_short_id in conversation_whitelist),
    }
    if customer_whitelist and customer_open_id not in customer_whitelist:
        return GateDecision(False, "blocked", "account_level_whitelist_missed", gate_results)
    if conversation_whitelist and conversation_short_id not in conversation_whitelist:
        return GateDecision(False, "blocked", "account_level_whitelist_missed", gate_results)

    limits = _real_send_frequency_snapshot(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        customer_open_id=customer_open_id,
        conversation_short_id=conversation_short_id,
        current_time=current_time,
    )
    min_interval_seconds = max(0, int(settings.min_interval_seconds or 0))
    daily_limit = max(0, int(settings.max_auto_replies_per_conversation_per_day or 0))
    gate_results["real_send_limits"] = {
        **limits,
        "min_interval_seconds": min_interval_seconds,
        "max_auto_replies_per_conversation_per_day": daily_limit,
    }
    last_sent_at = limits.get("last_sent_at")
    if isinstance(last_sent_at, datetime) and min_interval_seconds > 0:
        elapsed = (current_time - last_sent_at).total_seconds()
        if elapsed < min_interval_seconds:
            return GateDecision(False, "blocked", "min_interval_blocked", gate_results)
    if daily_limit > 0 and int(limits["conversation_day_count"]) >= daily_limit:
        return GateDecision(False, "blocked", "daily_conversation_limit_blocked", gate_results)

    return GateDecision(True, "sending", None, gate_results)


def _agent_binding_snapshot(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> dict[str, Any]:
    binding = (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.status == "active",
            DouyinAccountAgentBinding.is_default.is_(True),
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .order_by(DouyinAccountAgentBinding.id.desc())
        .first()
    )
    if binding is None:
        return {"has_binding": False, "has_active_agent": False, "reason": "binding_missing"}

    agent = (
        db.query(AiAgent)
        .filter(
            AiAgent.merchant_id == merchant_id,
            AiAgent.agent_id == binding.agent_id,
            AiAgent.status != "deleted",
        )
        .first()
    )
    return {
        "has_binding": True,
        "binding_status": binding.status,
        "is_default": bool(binding.is_default),
        "agent_status": getattr(agent, "status", None),
        "has_active_agent": agent is not None and agent.status == "active",
    }


def _frequency_snapshot(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    since: datetime,
) -> dict[str, int]:
    query = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.merchant_id == merchant_id)
        .filter(AiAutoReplyRun.account_open_id == account_open_id)
        .filter(AiAutoReplyRun.status.in_(COUNTED_RUN_STATUSES))
        .filter(AiAutoReplyRun.created_at >= since)
    )
    account_count = query.count()
    conversation_count = query.filter(AiAutoReplyRun.conversation_short_id == conversation_short_id).count()
    return {
        "counted_statuses": list(COUNTED_RUN_STATUSES),
        "conversation_count": conversation_count,
        "account_count": account_count,
    }


def _settings_snapshot(settings: DouyinAccountAutoreplySetting | None) -> dict[str, Any]:
    if settings is None:
        return {"exists": False}
    return {
        "exists": True,
        "enabled": bool(settings.enabled),
        "dry_run_enabled": bool(settings.dry_run_enabled),
        "send_enabled": bool(settings.send_enabled),
        "min_confidence": float(settings.min_confidence or 0),
        "require_rag": bool(settings.require_rag),
        "require_rag_sources": bool(settings.require_rag_sources),
        "allowed_intents": parse_allowed_intents(settings),
        "blocked_risk_flags": parse_blocked_risk_flags(settings),
        "customer_whitelist_open_ids": parse_customer_whitelist_open_ids(settings),
        "conversation_whitelist_ids": parse_conversation_whitelist_ids(settings),
        "min_interval_seconds": settings.min_interval_seconds,
        "max_auto_replies_per_conversation_per_day": settings.max_auto_replies_per_conversation_per_day,
        "max_replies_per_conversation_per_hour": settings.max_replies_per_conversation_per_hour,
        "max_replies_per_account_per_hour": settings.max_replies_per_account_per_hour,
        "direct_llm_policy": parse_direct_llm_policy(settings),
    }


def _allows_direct_llm_without_rag(settings: DouyinAccountAutoreplySetting, intent: str) -> bool:
    policy = parse_direct_llm_policy(settings)
    if policy.get("direct_llm_auto_send_enabled") is not True:
        return False
    if policy.get("policy_level") not in {"standard", "aggressive"}:
        return False
    return intent in {
        "greeting",
        "general_inquiry",
        "service_general_intro",
        "need_clarification",
        "brand_general_intro",
        "consult_specific_model",
        "consult_inventory",
    }


def _real_send_frequency_snapshot(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str | None,
    conversation_short_id: str | None,
    current_time: datetime,
) -> dict[str, Any]:
    from app.models import DouyinPrivateMessageSend

    query = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.send_source == "ai_auto")
        .filter(DouyinPrivateMessageSend.status == "sent")
        .filter(DouyinPrivateMessageSend.account_open_id == account_open_id)
    )
    if customer_open_id:
        query = query.filter(DouyinPrivateMessageSend.customer_open_id == customer_open_id)
    if conversation_short_id:
        query = query.filter(DouyinPrivateMessageSend.conversation_short_id == conversation_short_id)

    last = query.order_by(DouyinPrivateMessageSend.sent_at.desc(), DouyinPrivateMessageSend.id.desc()).first()
    day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    conversation_day_count = query.filter(DouyinPrivateMessageSend.sent_at >= day_start).count()
    return {
        "merchant_id": merchant_id,
        "last_sent_at": last.sent_at if last is not None else None,
        "conversation_day_count": conversation_day_count,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
