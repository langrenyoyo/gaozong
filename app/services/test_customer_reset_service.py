"""测试客户档案重置服务。

三级重置，严格限制为测试能力：
- A. 重置当前会话上下文（清除 pending/retry_wait run + 重置 autopilot 状态，保留客户档案+联系方式）
- B. 重置客户需求事实（清除 intent_car/budget/car_year/city，保留联系方式+称呼+性别）
- C. 完全重置测试客户（删除 customer_profiles 行 + 重置 lead 联系方式字段）

安全限制：
- TEST_CUSTOMER_RESET_ENABLED env 开关（生产默认关）
- 需管理员权限
- 审计日志记录
- 不删原始 webhook 消息
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import config
from app.models import (
    AiAutoReplyRun,
    AutoReplyAdminAuditLog,
    ConversationAutopilotState,
    CustomerProfile,
    DouyinLead,
)

logger = logging.getLogger(__name__)

RESET_LEVEL_SESSION = "session"
RESET_LEVEL_REQUIREMENTS = "requirements"
RESET_LEVEL_FULL = "full"

_VALID_LEVELS = {RESET_LEVEL_SESSION, RESET_LEVEL_REQUIREMENTS, RESET_LEVEL_FULL}


def is_reset_enabled() -> bool:
    """测试客户重置开关——生产默认关闭。"""
    return os.environ.get("TEST_CUSTOMER_RESET_ENABLED", "false").strip().lower() == "true"


def reset_test_customer(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
    conversation_short_id: str | None,
    level: str,
    operator_id: str,
    operator_name: str,
    reason: str,
) -> dict[str, Any]:
    """重置测试客户数据，返回清理摘要。"""
    if not is_reset_enabled():
        raise PermissionError("test_customer_reset_disabled")
    if level not in _VALID_LEVELS:
        raise ValueError(f"invalid_reset_level: {level}")
    if not merchant_id or not account_open_id or not customer_open_id:
        raise ValueError("merchant_id/account_open_id/customer_open_id required")

    before_summary = _snapshot(db, merchant_id, account_open_id, customer_open_id, conversation_short_id)
    cleaned: dict[str, Any] = {"level": level, "before": before_summary}

    if level == RESET_LEVEL_SESSION:
        _reset_session_context(db, merchant_id, account_open_id, conversation_short_id)
    elif level == RESET_LEVEL_REQUIREMENTS:
        _reset_requirements(db, merchant_id, account_open_id, customer_open_id)
    elif level == RESET_LEVEL_FULL:
        _reset_full(db, merchant_id, account_open_id, customer_open_id)

    after_summary = _snapshot(db, merchant_id, account_open_id, customer_open_id, conversation_short_id)
    cleaned["after"] = after_summary

    _record_audit(
        db,
        action=f"test_customer_reset_{level}",
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        target_type="customer",
        target_id=customer_open_id,
        before_json=before_summary,
        after_json=after_summary,
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
    )
    db.commit()
    logger.info(
        "test_customer_reset_done level=%s merchant_id=%s account_open_id=%s customer_open_id=%s operator=%s",
        level, merchant_id, account_open_id, customer_open_id, operator_id,
    )
    return cleaned


def _reset_session_context(
    db: Session,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str | None,
) -> None:
    """A. 重置当前会话上下文：清除未完成的 run + 重置 autopilot。"""
    if conversation_short_id:
        db.query(AiAutoReplyRun).filter(
            AiAutoReplyRun.merchant_id == merchant_id,
            AiAutoReplyRun.account_open_id == account_open_id,
            AiAutoReplyRun.conversation_short_id == conversation_short_id,
            AiAutoReplyRun.status.in_(["pending", "retry_wait", "processing", "send_processing"]),
        ).delete(synchronize_session=False)

        db.query(ConversationAutopilotState).filter(
            ConversationAutopilotState.merchant_id == merchant_id,
            ConversationAutopilotState.account_open_id == account_open_id,
            ConversationAutopilotState.conversation_short_id == conversation_short_id,
        ).update({
            "mode": "ai",
            "manual_takeover_until": None,
        }, synchronize_session=False)


def _reset_requirements(
    db: Session,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
) -> None:
    """B. 重置客户需求事实：清除 intent_car/budget/car_year/city，保留联系方式+称呼+性别。"""
    profile = db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == merchant_id,
        CustomerProfile.account_open_id == account_open_id,
        CustomerProfile.customer_open_id == customer_open_id,
    ).first()
    if profile:
        profile.intent_car = None
        profile.car_year = None
        profile.budget = None
        profile.city = None
        profile.inferred_fields_json = None
        profile.confirmed_fields_json = None
        profile.updated_at = datetime.now()


def _reset_full(
    db: Session,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
) -> None:
    """C. 完全重置：删除 customer_profiles + 重置 lead 联系方式字段。"""
    db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == merchant_id,
        CustomerProfile.account_open_id == account_open_id,
        CustomerProfile.customer_open_id == customer_open_id,
    ).delete(synchronize_session=False)

    db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.account_open_id == account_open_id,
        DouyinLead.source_id == customer_open_id,
    ).update({
        "extracted_phone": None,
        "extracted_wechat": None,
        "all_extracted_contacts": None,
        "contact_extract_status": None,
        "contact_extract_reason": None,
    }, synchronize_session=False)


def _snapshot(
    db: Session,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
    conversation_short_id: str | None,
) -> dict[str, Any]:
    """清理前后的数据快照（审计用，不含明文联系方式）。"""
    snapshot: dict[str, Any] = {}
    profile = db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == merchant_id,
        CustomerProfile.account_open_id == account_open_id,
        CustomerProfile.customer_open_id == customer_open_id,
    ).first()
    if profile:
        snapshot["profile_exists"] = True
        snapshot["has_intent_car"] = bool(profile.intent_car)
        snapshot["has_budget"] = bool(profile.budget)
        snapshot["has_city"] = bool(profile.city)
        snapshot["contact_state"] = profile.contact_state
        snapshot["preferred_salutation"] = profile.preferred_salutation
    else:
        snapshot["profile_exists"] = False

    if conversation_short_id:
        run_count = db.query(AiAutoReplyRun).filter(
            AiAutoReplyRun.merchant_id == merchant_id,
            AiAutoReplyRun.account_open_id == account_open_id,
            AiAutoReplyRun.conversation_short_id == conversation_short_id,
            AiAutoReplyRun.status.in_(["pending", "retry_wait", "processing", "send_processing"]),
        ).count()
        snapshot["pending_run_count"] = run_count

    lead = db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.account_open_id == account_open_id,
        DouyinLead.source_id == customer_open_id,
    ).first()
    snapshot["lead_has_contact"] = bool(lead and (lead.extracted_phone or lead.extracted_wechat))
    return snapshot


def _record_audit(
    db: Session,
    *,
    action: str,
    merchant_id: str,
    account_open_id: str,
    target_type: str,
    target_id: str,
    before_json: dict | None,
    after_json: dict | None,
    reason: str,
    operator_id: str,
    operator_name: str,
) -> None:
    """记录审计日志（复用 autoreply_admin_audit_logs 表）。"""
    log = AutoReplyAdminAuditLog(
        action=action,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        target_type=target_type,
        target_id=target_id,
        before_json=before_json,
        after_json=after_json,
        reason=reason,
        operator_id=operator_id,
        operator_name=operator_name,
        created_at=datetime.now(),
    )
    db.add(log)
