"""自动回复管理员灰度配置服务。

本服务只读写 DB 管理层配置和审计日志，不接入真实发送 gate。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    AutoReplyAdminAuditLog,
    AutoReplyRolloutConfig,
    AutoReplyWhitelistEntry,
)


VALID_WHITELIST_TYPES = {"account", "customer", "conversation"}
SENSITIVE_KEY_PARTS = ("token", "secret", "password", "cookie", "authorization")


@dataclass(frozen=True)
class RolloutConfigView:
    """未落库时也能返回安全默认值。"""

    scope: str
    merchant_id: str | None
    auto_reply_enabled: bool = False
    real_send_enabled: bool = False
    allow_full_rollout: bool = False


@dataclass(frozen=True)
class RolloutGateDecision:
    """DB 管理层灰度门禁结果。"""

    passed: bool
    blocked_reason: str | None
    snapshot: dict[str, Any]


def get_effective_rollout_config(db: Session, *, merchant_id: str | None = None) -> RolloutConfigView:
    """读取 DB 管理层配置；不计算 env 熔断，缺失时返回安全默认值。"""
    row = None
    if merchant_id:
        row = _get_config_row(db, scope="merchant", merchant_id=merchant_id)
    if row is None:
        row = _get_config_row(db, scope="global", merchant_id=None)
    if row is None:
        return RolloutConfigView(scope="merchant" if merchant_id else "global", merchant_id=merchant_id)
    return RolloutConfigView(
        scope=row.scope,
        merchant_id=row.merchant_id,
        auto_reply_enabled=bool(row.auto_reply_enabled),
        real_send_enabled=bool(row.real_send_enabled),
        allow_full_rollout=bool(row.allow_full_rollout),
    )


def evaluate_db_rollout_gate(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str | None,
    conversation_short_id: str | None,
) -> RolloutGateDecision:
    """评估 DB 管理层 rollout；只收紧真实发送，不读取 env 熔断。"""
    config = _get_config_row(db, scope="merchant", merchant_id=merchant_id)
    if config is None:
        config = _get_config_row(db, scope="global", merchant_id=None)
    snapshot = _db_rollout_snapshot(
        config=config,
        account_whitelist_hit=False,
        customer_whitelist_hit=False,
        conversation_whitelist_hit=False,
    )
    if config is None:
        return RolloutGateDecision(False, "no_db_rollout_config", snapshot)
    if config.auto_reply_enabled is not True:
        return RolloutGateDecision(False, "db_auto_reply_disabled", snapshot)
    if config.real_send_enabled is not True:
        return RolloutGateDecision(False, "db_real_send_disabled", snapshot)

    account_hit = _active_whitelist_hit(
        db,
        entry_type="account",
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        value=account_open_id,
    )
    customer_hit = _active_whitelist_hit(
        db,
        entry_type="customer",
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        value=customer_open_id,
    )
    conversation_hit = _active_whitelist_hit(
        db,
        entry_type="conversation",
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        value=conversation_short_id,
    )
    snapshot = _db_rollout_snapshot(
        config=config,
        account_whitelist_hit=account_hit,
        customer_whitelist_hit=customer_hit,
        conversation_whitelist_hit=conversation_hit,
    )
    if config.allow_full_rollout is True:
        return RolloutGateDecision(True, None, snapshot)
    if not account_hit:
        return RolloutGateDecision(False, "db_account_whitelist_missed", snapshot)
    if not (customer_hit or conversation_hit):
        return RolloutGateDecision(False, "db_customer_or_conversation_whitelist_missed", snapshot)
    return RolloutGateDecision(True, None, snapshot)


def update_rollout_config(
    db: Session,
    *,
    merchant_id: str | None = None,
    values: dict[str, Any],
    operator_id: str | None = None,
    operator_name: str | None = None,
    reason: str | None = None,
) -> AutoReplyRolloutConfig:
    """更新 DB 管理层配置并写审计；不触发发送。"""
    scope = "merchant" if merchant_id else "global"
    config = _get_config_row(db, scope=scope, merchant_id=merchant_id)
    before = _config_snapshot(config) if config is not None else None
    if config is None:
        config = AutoReplyRolloutConfig(scope=scope, merchant_id=merchant_id)
        db.add(config)

    for field in ("auto_reply_enabled", "real_send_enabled", "allow_full_rollout"):
        if field in values and values[field] is not None:
            setattr(config, field, bool(values[field]))
    config.updated_by = operator_id
    config.updated_at = datetime.now()
    db.flush()

    record_admin_audit(
        db,
        action="update_global_config",
        merchant_id=merchant_id,
        target_type=scope,
        target_id=merchant_id or "global",
        before=before,
        after=_config_snapshot(config),
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
        commit=False,
    )
    db.commit()
    db.refresh(config)
    return config


def add_whitelist_entry(
    db: Session,
    *,
    entry_type: str,
    merchant_id: str,
    account_open_id: str | None,
    value: str,
    reason: str,
    operator_id: str | None = None,
    operator_name: str | None = None,
) -> AutoReplyWhitelistEntry:
    """幂等添加白名单；已禁用记录会被重新启用。"""
    _validate_whitelist(entry_type=entry_type, merchant_id=merchant_id, value=value, reason=reason)
    entry = _find_whitelist_entry(
        db,
        entry_type=entry_type,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        value=value,
    )
    if entry is not None and entry.enabled is True:
        return entry

    before = _whitelist_snapshot(entry) if entry is not None else None
    if entry is None:
        entry = AutoReplyWhitelistEntry(
            entry_type=entry_type,
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            value=value,
            reason=reason,
            enabled=True,
            created_by=operator_id,
        )
        db.add(entry)
    else:
        entry.enabled = True
        entry.reason = reason
        entry.disabled_by = None
        entry.disabled_at = None
    db.flush()

    record_admin_audit(
        db,
        action="add_whitelist",
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        target_type=entry_type,
        target_id=str(entry.id),
        before=before,
        after=_whitelist_snapshot(entry),
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
        commit=False,
    )
    db.commit()
    db.refresh(entry)
    return entry


def disable_whitelist_entry(
    db: Session,
    *,
    entry_id: int,
    operator_id: str | None = None,
    operator_name: str | None = None,
    reason: str | None = None,
) -> AutoReplyWhitelistEntry:
    """软禁用白名单并写审计。"""
    entry = db.query(AutoReplyWhitelistEntry).filter(AutoReplyWhitelistEntry.id == entry_id).one()
    if entry.enabled is not True:
        return entry
    before = _whitelist_snapshot(entry)
    entry.enabled = False
    entry.disabled_by = operator_id
    entry.disabled_at = datetime.now()
    db.flush()

    record_admin_audit(
        db,
        action="disable_whitelist",
        merchant_id=entry.merchant_id,
        account_open_id=entry.account_open_id,
        target_type=entry.entry_type,
        target_id=str(entry.id),
        before=before,
        after=_whitelist_snapshot(entry),
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
        commit=False,
    )
    db.commit()
    db.refresh(entry)
    return entry


def list_whitelist_entries(
    db: Session,
    *,
    merchant_id: str | None = None,
    account_open_id: str | None = None,
    entry_type: str | None = None,
    enabled: bool | None = None,
) -> list[AutoReplyWhitelistEntry]:
    """按范围查询管理员白名单。"""
    query = db.query(AutoReplyWhitelistEntry)
    if merchant_id:
        query = query.filter(AutoReplyWhitelistEntry.merchant_id == merchant_id)
    if account_open_id:
        query = query.filter(AutoReplyWhitelistEntry.account_open_id == account_open_id)
    if entry_type:
        query = query.filter(AutoReplyWhitelistEntry.entry_type == entry_type)
    if enabled is not None:
        query = query.filter(AutoReplyWhitelistEntry.enabled == enabled)
    return query.order_by(AutoReplyWhitelistEntry.id.asc()).all()


def record_admin_audit(
    db: Session,
    *,
    action: str,
    merchant_id: str | None = None,
    account_open_id: str | None = None,
    target_type: str,
    target_id: str | None = None,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    operator_id: str | None = None,
    operator_name: str | None = None,
    commit: bool = False,
) -> AutoReplyAdminAuditLog:
    """统一写管理员审计日志，写入前剔除敏感键。"""
    audit = AutoReplyAdminAuditLog(
        action=action,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        target_type=target_type,
        target_id=target_id,
        before_json=_safe_json(before),
        after_json=_safe_json(after),
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
    )
    db.add(audit)
    if commit:
        db.commit()
        db.refresh(audit)
    return audit


def _get_config_row(
    db: Session,
    *,
    scope: str,
    merchant_id: str | None,
) -> AutoReplyRolloutConfig | None:
    query = db.query(AutoReplyRolloutConfig).filter(AutoReplyRolloutConfig.scope == scope)
    if merchant_id is None:
        query = query.filter(AutoReplyRolloutConfig.merchant_id.is_(None))
    else:
        query = query.filter(AutoReplyRolloutConfig.merchant_id == merchant_id)
    return query.first()


def _find_whitelist_entry(
    db: Session,
    *,
    entry_type: str,
    merchant_id: str,
    account_open_id: str | None,
    value: str,
) -> AutoReplyWhitelistEntry | None:
    query = (
        db.query(AutoReplyWhitelistEntry)
        .filter(AutoReplyWhitelistEntry.entry_type == entry_type)
        .filter(AutoReplyWhitelistEntry.merchant_id == merchant_id)
        .filter(AutoReplyWhitelistEntry.value == value)
    )
    if account_open_id is None:
        query = query.filter(AutoReplyWhitelistEntry.account_open_id.is_(None))
    else:
        query = query.filter(AutoReplyWhitelistEntry.account_open_id == account_open_id)
    return query.first()


def _active_whitelist_hit(
    db: Session,
    *,
    entry_type: str,
    merchant_id: str,
    account_open_id: str,
    value: str | None,
) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    query = (
        db.query(AutoReplyWhitelistEntry)
        .filter(AutoReplyWhitelistEntry.entry_type == entry_type)
        .filter(AutoReplyWhitelistEntry.merchant_id == merchant_id)
        .filter(AutoReplyWhitelistEntry.value == text)
        .filter(AutoReplyWhitelistEntry.enabled.is_(True))
    )
    if entry_type in {"customer", "conversation"}:
        query = query.filter(
            or_(
                AutoReplyWhitelistEntry.account_open_id == account_open_id,
                AutoReplyWhitelistEntry.account_open_id.is_(None),
            )
        )
    return query.first() is not None


def _validate_whitelist(*, entry_type: str, merchant_id: str, value: str, reason: str) -> None:
    if entry_type not in VALID_WHITELIST_TYPES:
        raise ValueError(f"unsupported whitelist entry_type: {entry_type}")
    if not merchant_id:
        raise ValueError("merchant_id is required")
    if not str(value or "").strip():
        raise ValueError("value is required")
    if not str(reason or "").strip():
        raise ValueError("reason is required")


def _config_snapshot(config: AutoReplyRolloutConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "scope": config.scope,
        "merchant_id": config.merchant_id,
        "auto_reply_enabled": bool(config.auto_reply_enabled),
        "real_send_enabled": bool(config.real_send_enabled),
        "allow_full_rollout": bool(config.allow_full_rollout),
    }


def _whitelist_snapshot(entry: AutoReplyWhitelistEntry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "merchant_id": entry.merchant_id,
        "account_open_id": entry.account_open_id,
        "value": entry.value,
        "enabled": bool(entry.enabled),
    }


def _db_rollout_snapshot(
    *,
    config: AutoReplyRolloutConfig | None,
    account_whitelist_hit: bool,
    customer_whitelist_hit: bool,
    conversation_whitelist_hit: bool,
) -> dict[str, Any]:
    if config is None:
        return {
            "config_exists": False,
            "auto_reply_enabled": False,
            "real_send_enabled": False,
            "allow_full_rollout": False,
            "mode": "whitelist",
            "account_whitelist_required": True,
            "customer_or_conversation_whitelist_required": True,
            "account_whitelist_hit": False,
            "customer_whitelist_hit": False,
            "conversation_whitelist_hit": False,
        }
    allow_full_rollout = bool(config.allow_full_rollout)
    return {
        "config_exists": True,
        "scope": config.scope,
        "merchant_id": config.merchant_id,
        "auto_reply_enabled": bool(config.auto_reply_enabled),
        "real_send_enabled": bool(config.real_send_enabled),
        "allow_full_rollout": allow_full_rollout,
        "mode": "full_rollout" if allow_full_rollout else "whitelist",
        "account_whitelist_required": not allow_full_rollout,
        "customer_or_conversation_whitelist_required": not allow_full_rollout,
        "account_whitelist_hit": bool(account_whitelist_hit),
        "customer_whitelist_hit": bool(customer_whitelist_hit),
        "conversation_whitelist_hit": bool(conversation_whitelist_hit),
    }


def _safe_json(value: Any) -> Any:
    """脱敏后返回结构化值（dict/list/标量），供 ORM JSON 列直接存储；剔除敏感键。

    不返回 json.dumps 字符串——ORM JSON 列在 SQLite 落 TEXT、PG 落 jsonb，
    由 SQLAlchemy 负责编码，避免 String→jsonb 类型不匹配。
    """
    if value is None:
        return None
    return _strip_sensitive(value)


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in SENSITIVE_KEY_PARTS):
                continue
            result[key_text] = _strip_sensitive(item)
        return result
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value
