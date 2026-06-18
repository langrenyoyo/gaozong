"""抖音 AI 客服账号与智能体绑定校验兼容入口。"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import DouyinAuthorizedAccount
from app.services.douyin_account_agent_binding_service import (
    BindingValidationResult,
    validate_douyin_agent_binding as validate_account_agent_binding,
)


SUPER_ADMIN_BYPASS_REQUIRES_AUDIT = "SUPER_ADMIN_BYPASS_REQUIRES_AUDIT"


def validate_douyin_agent_binding(
    *,
    db: Session,
    context: RequestContext,
    douyin_account_id: int | str | None,
    agent_id: str | None,
    conversation_id: str | int | None = None,
) -> BindingValidationResult:
    """校验回复建议请求是否使用已绑定的抖音企业号和智能体。"""
    audit = {
        "user_id": context.user_id,
        "merchant_id": context.merchant_id,
        "super_admin": context.super_admin,
        "douyin_account_id": douyin_account_id,
        "agent_id": agent_id,
        "conversation_id": conversation_id,
    }
    if _is_blank(douyin_account_id):
        return BindingValidationResult(allowed=False, reason_code="DOUYIN_ACCOUNT_ID_MISSING", audit=audit)
    if _is_blank(conversation_id):
        return BindingValidationResult(allowed=False, reason_code="CONVERSATION_ID_MISSING", audit=audit)
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

    result = validate_account_agent_binding(
        db=db,
        context=context,
        account_open_id=account.open_id,
        agent_id=agent_id,
        require_existing_binding=True,
    )
    result.audit = {
        **result.audit,
        **audit,
        "douyin_account_lookup_match": match_type,
        "authorized_account_id": account.id,
        "authorized_account_open_id": account.open_id,
        "authorized_account_main_account_id": account.main_account_id,
        "authorized_account_bind_status": account.bind_status,
    }
    return result


def _find_authorized_account(
    db: Session,
    douyin_account_id: int | str,
) -> tuple[DouyinAuthorizedAccount | None, str | None]:
    text = str(douyin_account_id).strip()
    numeric = _to_int(text)

    row = db.query(DouyinAuthorizedAccount).filter(DouyinAuthorizedAccount.open_id == text).first()
    if row is not None:
        return row, "open_id"

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

    for row in db.query(DouyinAuthorizedAccount).all():
        if _stable_numeric_id(row.open_id) == numeric:
            return row, "derived_douyin_account_id"
    return None, None


def _stable_numeric_id(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""
