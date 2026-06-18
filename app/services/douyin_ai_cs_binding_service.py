"""抖音 AI 客服账号与智能体绑定校验服务。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import DouyinAuthorizedAccount


SUPER_ADMIN_BYPASS_REQUIRES_AUDIT = "SUPER_ADMIN_BYPASS_REQUIRES_AUDIT"
DOUYIN_ACCOUNT_MERCHANT_BINDING_NOT_ENFORCED = "DOUYIN_ACCOUNT_MERCHANT_BINDING_NOT_ENFORCED"
AGENT_BINDING_NOT_ENFORCED = "AGENT_BINDING_NOT_ENFORCED"


@dataclass
class BindingValidationResult:
    """绑定校验结果。"""

    allowed: bool
    warnings: list[str] = field(default_factory=list)
    reason_code: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)


def validate_douyin_agent_binding(
    *,
    db: Session,
    context: RequestContext,
    douyin_account_id: int | str | None,
    agent_id: str | None,
    conversation_id: str | int | None = None,
) -> BindingValidationResult:
    """校验当前请求是否可使用指定抖音账号和智能体。"""
    audit = {
        "user_id": context.user_id,
        "merchant_id": context.merchant_id,
        "super_admin": context.super_admin,
        "douyin_account_id": douyin_account_id,
        "agent_id": agent_id,
        "conversation_id": conversation_id,
    }

    if _is_blank(douyin_account_id):
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_ID_MISSING",
            audit=audit,
        )
    if _is_blank(conversation_id):
        return BindingValidationResult(
            allowed=False,
            reason_code="CONVERSATION_ID_MISSING",
            audit=audit,
        )

    if context.super_admin:
        return BindingValidationResult(
            allowed=True,
            warnings=[SUPER_ADMIN_BYPASS_REQUIRES_AUDIT],
            audit={**audit, "binding_check": "super_admin_bypass"},
        )

    if not context.merchant_id:
        return BindingValidationResult(
            allowed=False,
            reason_code="MERCHANT_CONTEXT_MISSING",
            audit=audit,
        )

    account, match_type = _find_authorized_account(db, douyin_account_id)
    if account is None:
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_NOT_FOUND",
            audit={**audit, "douyin_account_lookup_match": None},
        )

    warnings: list[str] = []
    if not _account_has_merchant_binding_fields():
        warnings.append(DOUYIN_ACCOUNT_MERCHANT_BINDING_NOT_ENFORCED)
    else:
        owner_merchant_id = getattr(account, "merchant_id", None)
        owner_tenant_id = getattr(account, "tenant_id", None)
        if owner_merchant_id and str(owner_merchant_id) != str(context.merchant_id):
            return BindingValidationResult(
                allowed=False,
                reason_code="DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED",
                audit={
                    **audit,
                    "douyin_account_lookup_match": match_type,
                    "owner_merchant_id": owner_merchant_id,
                    "owner_tenant_id": owner_tenant_id,
                },
            )

    warnings.append(AGENT_BINDING_NOT_ENFORCED)
    return BindingValidationResult(
        allowed=True,
        warnings=warnings,
        audit={
            **audit,
            "douyin_account_lookup_match": match_type,
            "authorized_account_id": account.id,
            "authorized_account_open_id": account.open_id,
            "authorized_account_main_account_id": account.main_account_id,
            "authorized_account_bind_status": account.bind_status,
        },
    )


def _find_authorized_account(
    db: Session,
    douyin_account_id: int | str,
) -> tuple[DouyinAuthorizedAccount | None, str | None]:
    text = str(douyin_account_id).strip()
    numeric = _to_int(text)

    if numeric is not None:
        row = db.query(DouyinAuthorizedAccount).filter(DouyinAuthorizedAccount.id == numeric).first()
        if row is not None:
            return row, "id"
        row = (
            db.query(DouyinAuthorizedAccount)
            .filter(DouyinAuthorizedAccount.main_account_id == numeric)
            .first()
        )
        if row is not None:
            return row, "main_account_id"

    row = db.query(DouyinAuthorizedAccount).filter(DouyinAuthorizedAccount.open_id == text).first()
    if row is not None:
        return row, "open_id"

    for row in db.query(DouyinAuthorizedAccount).all():
        if _stable_numeric_id(row.open_id) == numeric:
            return row, "derived_douyin_account_id"
    return None, None


def _account_has_merchant_binding_fields() -> bool:
    return hasattr(DouyinAuthorizedAccount, "merchant_id") or hasattr(DouyinAuthorizedAccount, "tenant_id")


def _stable_numeric_id(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""
