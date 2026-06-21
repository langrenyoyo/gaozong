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


DEFAULT_AUTOREPLY_SETTINGS = {
    "enabled": False,
    "dry_run_enabled": False,
    "send_enabled": False,
    "min_confidence": 0.85,
    "require_rag": True,
    "require_rag_sources": True,
    "allowed_intents": [],
    "blocked_risk_flags": [],
    "max_replies_per_conversation_per_hour": 3,
    "max_replies_per_account_per_hour": 30,
}


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
            "enabled": bool(settings.enabled),
            "dry_run_enabled": bool(settings.dry_run_enabled),
            "send_enabled": bool(settings.send_enabled),
            "min_confidence": settings.min_confidence,
            "require_rag": bool(settings.require_rag),
            "require_rag_sources": bool(settings.require_rag_sources),
            "allowed_intents": parse_allowed_intents(settings),
            "blocked_risk_flags": parse_blocked_risk_flags(settings),
            "max_replies_per_conversation_per_hour": settings.max_replies_per_conversation_per_hour,
            "max_replies_per_account_per_hour": settings.max_replies_per_account_per_hour,
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
    db.commit()
    db.refresh(settings)
    return settings


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
