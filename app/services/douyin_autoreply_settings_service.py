"""抖音自动回复配置服务。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    DouyinAccountAgentBinding,
    DouyinAccountAutoreplySetting,
    DouyinAuthorizedAccount,
    AiAgent,
)


DEFAULT_MIN_INTERVAL_SECONDS = 10
DEFAULT_MAX_AUTO_REPLIES_PER_CONVERSATION_PER_DAY = 80
DEFAULT_MAX_REPLIES_PER_CONVERSATION_PER_HOUR = 20
DEFAULT_MAX_REPLIES_PER_ACCOUNT_PER_HOUR = 300

DEFAULT_DIRECT_LLM_POLICY: dict[str, Any] = {
    "direct_llm_auto_send_enabled": False,
    "policy_level": "conservative",
    "allow_greeting_auto_send": False,
    "allow_general_intro_auto_send": False,
    "allow_need_clarification_auto_send": False,
    "allow_brand_general_intro_auto_send": False,
    "specific_model_strategy": "manual_confirm",
    "contact_guidance_level": "none",
    "require_rag_for_specific_inventory": True,
    "forbid_inventory_claim": True,
    "forbid_price_claim": True,
    "forbid_finance_claim": True,
    "forbid_vehicle_condition_claim": True,
    "min_confidence_for_direct_send": 0.85,
}

DEFAULT_AUTOREPLY_SETTINGS = {
    "mode": "manual_takeover",
    "enabled": False,
    "dry_run_enabled": False,
    "send_enabled": False,
    "min_confidence": 0.85,
    "require_rag": True,
    "require_rag_sources": True,
    "allowed_intents": [],
    "blocked_risk_flags": [],
    "customer_whitelist_open_ids": [],
    "conversation_whitelist_ids": [],
    "min_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS,
    "max_auto_replies_per_conversation_per_day": DEFAULT_MAX_AUTO_REPLIES_PER_CONVERSATION_PER_DAY,
    "max_replies_per_conversation_per_hour": DEFAULT_MAX_REPLIES_PER_CONVERSATION_PER_HOUR,
    "max_replies_per_account_per_hour": DEFAULT_MAX_REPLIES_PER_ACCOUNT_PER_HOUR,
    "direct_llm_policy": dict(DEFAULT_DIRECT_LLM_POLICY),
}

AUTOREPLY_MODE_AI_AUTO = "ai_auto"
AUTOREPLY_MODE_MANUAL_TAKEOVER = "manual_takeover"


def get_account_autoreply_settings(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> DouyinAccountAutoreplySetting | None:
    """按可信商户和企业号读取自动回复配置，不自动创建默认配置。"""
    if not merchant_id or not account_open_id:
        return None
    return (
        db.query(DouyinAccountAutoreplySetting)
        .filter(DouyinAccountAutoreplySetting.merchant_id == merchant_id)
        .filter(DouyinAccountAutoreplySetting.account_open_id == account_open_id)
        .first()
    )


def list_account_autoreply_settings_views(
    db: Session,
    *,
    merchant_id: str,
) -> list[dict[str, Any]]:
    """返回当前商户所有授权企业号的自动回复配置视图，不自动创建配置。"""
    accounts = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.merchant_id == merchant_id)
        .filter(DouyinAuthorizedAccount.bind_status == 1)
        .order_by(DouyinAuthorizedAccount.last_synced_at.desc(), DouyinAuthorizedAccount.id.desc())
        .all()
    )
    return [
        build_account_autoreply_settings_view(
            db,
            merchant_id=merchant_id,
            account_open_id=account.open_id,
            account=account,
        )
        for account in accounts
    ]


def get_owned_account_or_none(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> DouyinAuthorizedAccount | None:
    """按可信商户读取企业号，调用方负责转成 HTTP 错误。"""
    if not merchant_id or not account_open_id:
        return None
    return (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id)
        .first()
    )


def build_account_autoreply_settings_view(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    account: DouyinAuthorizedAccount | None = None,
) -> dict[str, Any]:
    """构造单个企业号配置视图，缺失配置时返回默认值。"""
    account = account or get_owned_account_or_none(db, merchant_id=merchant_id, account_open_id=account_open_id)
    settings = get_account_autoreply_settings(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
    )
    default_binding = _get_default_binding(db, merchant_id=merchant_id, account_open_id=account_open_id)
    agent = None
    if default_binding and default_binding.agent_id:
        agent = (
            db.query(AiAgent)
            .filter(AiAgent.merchant_id == merchant_id)
            .filter(AiAgent.agent_id == default_binding.agent_id)
            .first()
        )

    data = {
        "account_open_id": account_open_id,
        "account_name": account.account_name if account is not None else account_open_id,
        "bind_status": account.bind_status if account is not None else None,
        "bound_agent_id": default_binding.agent_id if default_binding is not None else None,
        "bound_agent_name": agent.name if agent is not None else None,
        **DEFAULT_AUTOREPLY_SETTINGS,
        "created_at": None,
        "updated_at": None,
    }
    if settings is None:
        return data

    data.update(
        {
            "mode": mode_from_settings(settings),
            "enabled": bool(settings.enabled),
            "dry_run_enabled": bool(settings.dry_run_enabled),
            "send_enabled": bool(settings.send_enabled),
            "min_confidence": settings.min_confidence,
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
            "created_at": settings.created_at,
            "updated_at": settings.updated_at,
        }
    )
    return data


def upsert_account_autoreply_settings(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    values: dict[str, Any],
) -> DouyinAccountAutoreplySetting:
    """新增或更新企业号自动回复配置；只保存配置，不触发任何自动回复动作。"""
    settings = get_account_autoreply_settings(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
    )
    if settings is None:
        settings = DouyinAccountAutoreplySetting(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
        )
        db.add(settings)

    simple_fields = [
        "enabled",
        "dry_run_enabled",
        "send_enabled",
        "min_confidence",
        "require_rag",
        "require_rag_sources",
        "min_interval_seconds",
        "max_auto_replies_per_conversation_per_day",
        "max_replies_per_conversation_per_hour",
        "max_replies_per_account_per_hour",
    ]
    for field in simple_fields:
        if field in values and values[field] is not None:
            setattr(settings, field, values[field])
    if "allowed_intents" in values and values["allowed_intents"] is not None:
        settings.allowed_intents_json = json.dumps(_unique_strings(values["allowed_intents"]), ensure_ascii=False)
    if "blocked_risk_flags" in values and values["blocked_risk_flags"] is not None:
        settings.blocked_risk_flags_json = json.dumps(_unique_strings(values["blocked_risk_flags"]), ensure_ascii=False)
    if "customer_whitelist_open_ids" in values and values["customer_whitelist_open_ids"] is not None:
        settings.customer_whitelist_open_ids = json.dumps(
            _unique_strings(values["customer_whitelist_open_ids"]),
            ensure_ascii=False,
        )
    if "conversation_whitelist_ids" in values and values["conversation_whitelist_ids"] is not None:
        settings.conversation_whitelist_ids = json.dumps(
            _unique_strings(values["conversation_whitelist_ids"]),
            ensure_ascii=False,
        )
    if "direct_llm_policy" in values and values["direct_llm_policy"] is not None:
        settings.direct_llm_policy_json = json.dumps(
            normalize_direct_llm_policy(values["direct_llm_policy"]),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    db.commit()
    db.refresh(settings)
    return settings


def mode_from_settings(settings: DouyinAccountAutoreplySetting | None) -> str:
    """按现有配置派生企业号托管模式。"""
    if settings is not None and settings.enabled is True and settings.send_enabled is True:
        return AUTOREPLY_MODE_AI_AUTO
    return AUTOREPLY_MODE_MANUAL_TAKEOVER


def values_for_mode(mode: str) -> dict[str, bool]:
    """把企业号托管模式映射到现有自动回复配置字段。"""
    if mode == AUTOREPLY_MODE_AI_AUTO:
        return {"enabled": True, "send_enabled": True}
    if mode == AUTOREPLY_MODE_MANUAL_TAKEOVER:
        return {"enabled": True, "send_enabled": False}
    raise ValueError(f"unsupported autoreply mode: {mode}")


def parse_allowed_intents(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析允许自动决策的低风险意图列表。"""
    if settings is None:
        return []
    return _parse_string_list(settings.allowed_intents_json)


def parse_blocked_risk_flags(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析明确阻断的风险标记列表。"""
    if settings is None:
        return []
    return _parse_string_list(settings.blocked_risk_flags_json)


def parse_customer_whitelist_open_ids(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析账号级客户 open_id 白名单。"""
    if settings is None:
        return []
    return _parse_string_list(settings.customer_whitelist_open_ids)


def parse_conversation_whitelist_ids(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析账号级会话白名单。"""
    if settings is None:
        return []
    return _parse_string_list(settings.conversation_whitelist_ids)


def parse_direct_llm_policy(settings: DouyinAccountAutoreplySetting | None) -> dict[str, Any]:
    if settings is None:
        return dict(DEFAULT_DIRECT_LLM_POLICY)
    raw_value = getattr(settings, "direct_llm_policy_json", None)
    try:
        parsed = json.loads(raw_value) if raw_value else {}
    except (TypeError, ValueError):
        parsed = {}
    return normalize_direct_llm_policy(parsed)


def normalize_direct_llm_policy(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        value = {}
    policy = dict(DEFAULT_DIRECT_LLM_POLICY)
    bool_fields = {
        "direct_llm_auto_send_enabled",
        "allow_greeting_auto_send",
        "allow_general_intro_auto_send",
        "allow_need_clarification_auto_send",
        "allow_brand_general_intro_auto_send",
        "require_rag_for_specific_inventory",
        "forbid_inventory_claim",
        "forbid_price_claim",
        "forbid_finance_claim",
        "forbid_vehicle_condition_claim",
    }
    for field in bool_fields:
        if field in value:
            policy[field] = bool(value[field])
    if value.get("policy_level") in {"conservative", "standard", "aggressive"}:
        policy["policy_level"] = value["policy_level"]
    if value.get("specific_model_strategy") in {"manual_confirm", "safe_clarify"}:
        policy["specific_model_strategy"] = value["specific_model_strategy"]
    if value.get("contact_guidance_level") in {"none", "customer_initiated_only", "soft_guidance"}:
        policy["contact_guidance_level"] = value["contact_guidance_level"]
    try:
        confidence = float(value.get("min_confidence_for_direct_send", policy["min_confidence_for_direct_send"]))
    except (TypeError, ValueError):
        confidence = float(policy["min_confidence_for_direct_send"])
    policy["min_confidence_for_direct_send"] = min(1.0, max(0.0, confidence))
    return policy


def _parse_string_list(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _get_default_binding(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> DouyinAccountAgentBinding | None:
    return (
        db.query(DouyinAccountAgentBinding)
        .filter(DouyinAccountAgentBinding.merchant_id == merchant_id)
        .filter(DouyinAccountAgentBinding.account_open_id == account_open_id)
        .filter(DouyinAccountAgentBinding.status == "active")
        .order_by(DouyinAccountAgentBinding.is_default.desc(), DouyinAccountAgentBinding.id.desc())
        .first()
    )
