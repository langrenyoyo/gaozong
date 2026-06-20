"""抖音企业号与 AI 智能体绑定权威服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount


ACTIVE_BINDING_STATUS = "active"
DELETED_ACCOUNT_BIND_STATUS = 4


@dataclass
class BindingValidationResult:
    """绑定校验结果。"""

    allowed: bool
    warnings: list[str] = field(default_factory=list)
    reason_code: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass
class BindingSummary:
    """企业号绑定摘要。"""

    account_open_id: str
    bind_status: str
    authorization_status: str
    bound_agent_id: str | None = None
    bound_agent_name: str | None = None
    bound_agent_status: str | None = None
    binding_status: str | None = None
    binding_id: int | None = None


@dataclass
class AccountAgentView:
    """工作台智能体列表项，兼容前端 DouyinAgentItem 契约。"""

    agent_id: str
    agent_name: str
    # AiAgent 模型暂无分类 / 回复风格 / 业务范围维度，预留空串保持前端契约兼容
    agent_category: str
    reply_style: str
    business_scope: str
    is_default: bool
    is_active: bool


@dataclass
class MerchantAccountAgentsResult:
    """企业号可选智能体列表读取结果（只读，供 9000 可信代理使用）。"""

    allowed: bool
    agents: list[AccountAgentView] = field(default_factory=list)
    default_agent_id: str | None = None
    reason_code: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookBoundAgentResult:
    """Webhook 场景下的企业号默认智能体解析结果。"""

    allowed: bool
    reason_code: str | None = None
    account: DouyinAuthorizedAccount | None = None
    binding: DouyinAccountAgentBinding | None = None
    agent: AiAgent | None = None
    merchant_id: str | None = None
    tenant_id: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)


def get_binding_summary(db: Session, *, account_open_id: str, merchant_id: str) -> BindingSummary:
    """读取当前商户下企业号的 active 默认绑定摘要。"""
    account = _find_account_by_open_id(db, account_open_id)
    authorization_status = _authorization_status(account)
    row = _find_active_binding(db, merchant_id=merchant_id, account_open_id=account_open_id)
    if row is None:
        return BindingSummary(
            account_open_id=account_open_id,
            bind_status=str(account.bind_status) if account else "unknown",
            authorization_status=authorization_status,
            binding_status="unbound",
        )

    agent = _find_agent_any_status(db, merchant_id=merchant_id, agent_id=row.agent_id)
    return BindingSummary(
        account_open_id=account_open_id,
        bind_status=str(account.bind_status) if account else "unknown",
        authorization_status=authorization_status,
        bound_agent_id=row.agent_id,
        bound_agent_name=agent.name if agent else None,
        bound_agent_status=agent.status if agent else "missing",
        binding_status=row.status,
        binding_id=row.id,
    )


def list_account_agents_for_merchant_account(
    db: Session,
    *,
    context: RequestContext,
    account_open_id: str,
) -> MerchantAccountAgentsResult:
    """返回当前商户可选 active 智能体，以及该企业号当前绑定的智能体 ID。

    仅供 9000 可信代理读取工作台智能体列表，替代前端直连 9100 mock 链路；
    智能体来源为真实 AiAgent（当前商户）与 douyin_account_agent_bindings，
    merchant_id 强制取自 RequestContext，不读取请求体。
    """
    base = _validate_account_context(db=db, context=context, account_open_id=account_open_id)
    if not base.allowed:
        return MerchantAccountAgentsResult(
            allowed=False,
            reason_code=base.reason_code,
            audit=base.audit,
        )

    merchant_id = context.merchant_id or ""
    agent_rows = (
        db.query(AiAgent)
        .filter(
            AiAgent.merchant_id == merchant_id,
            AiAgent.status == "active",
        )
        .order_by(AiAgent.id.desc())
        .all()
    )
    binding = _find_active_binding(db, merchant_id=merchant_id, account_open_id=account_open_id)
    default_agent_id = binding.agent_id if binding else None
    agents = [
        AccountAgentView(
            agent_id=row.agent_id,
            agent_name=row.name,
            agent_category="",
            reply_style="",
            business_scope="",
            is_default=default_agent_id is not None and row.agent_id == default_agent_id,
            is_active=True,
        )
        for row in agent_rows
    ]
    return MerchantAccountAgentsResult(
        allowed=True,
        agents=agents,
        default_agent_id=default_agent_id,
        audit=base.audit,
    )


def bind_agent_to_account(
    db: Session,
    *,
    account_open_id: str,
    agent_id: str,
    context: RequestContext,
) -> DouyinAccountAgentBinding | BindingValidationResult:
    """绑定企业号到智能体，保证一期只有一个 active 默认绑定。"""
    validation = validate_douyin_agent_binding(
        db=db,
        context=context,
        account_open_id=account_open_id,
        agent_id=agent_id,
        require_existing_binding=False,
    )
    if not validation.allowed:
        return validation

    merchant_id = context.merchant_id or ""
    account = _find_account_by_open_id(db, account_open_id)
    now = datetime.now()

    active_rows = (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.status == ACTIVE_BINDING_STATUS,
            DouyinAccountAgentBinding.is_default.is_(True),
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .all()
    )
    for row in active_rows:
        row.status = "unbound"
        row.is_default = False
        row.unbound_at = now
        row.updated_at = now
        row.updated_by = context.user_id
    if active_rows:
        db.flush()

    binding = _find_historical_binding(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        agent_id=agent_id,
    )
    if binding is not None:
        binding.tenant_id = getattr(account, "tenant_id", None)
        binding.douyin_authorized_account_id = account.id if account else None
        binding.status = ACTIVE_BINDING_STATUS
        binding.is_default = True
        binding.unbound_at = None
        binding.deleted_at = None
        binding.invalid_reason = None
        binding.updated_at = now
        binding.updated_by = context.user_id
        db.commit()
        db.refresh(binding)
        return binding

    binding = DouyinAccountAgentBinding(
        merchant_id=merchant_id,
        tenant_id=getattr(account, "tenant_id", None),
        account_open_id=account_open_id,
        douyin_authorized_account_id=account.id if account else None,
        agent_id=agent_id,
        is_default=True,
        status=ACTIVE_BINDING_STATUS,
        created_at=now,
        updated_at=now,
        created_by=context.user_id,
        updated_by=context.user_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def unbind_agent_from_account(
    db: Session,
    *,
    account_open_id: str,
    context: RequestContext,
) -> DouyinAccountAgentBinding | BindingValidationResult:
    """解绑企业号 active 默认绑定，不物理删除。"""
    base = _validate_account_context(db=db, context=context, account_open_id=account_open_id)
    if not base.allowed:
        return base

    merchant_id = context.merchant_id or ""
    row = _find_active_binding(db, merchant_id=merchant_id, account_open_id=account_open_id)
    if row is None:
        return BindingValidationResult(
            allowed=False,
            reason_code="AGENT_BINDING_NOT_FOUND",
            audit={**base.audit, "account_open_id": account_open_id},
        )

    now = datetime.now()
    row.status = "unbound"
    row.is_default = False
    row.unbound_at = now
    row.updated_at = now
    row.updated_by = context.user_id
    db.commit()
    db.refresh(row)
    return row


def invalidate_bindings_for_account(
    db: Session,
    *,
    account_open_id: str,
    reason: str,
    context: RequestContext,
) -> int:
    """取消授权或删除企业号后，将 active 绑定置为 invalid。"""
    if not context.merchant_id:
        return 0
    now = datetime.now()
    rows = (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == context.merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.status == ACTIVE_BINDING_STATUS,
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.status = "invalid"
        row.invalid_reason = reason
        row.updated_at = now
        row.updated_by = context.user_id
    db.commit()
    return len(rows)


def delete_bindings_for_account(
    db: Session,
    *,
    account_open_id: str,
    reason: str,
    context: RequestContext,
) -> int:
    """删除企业号后，将 active 绑定置为 deleted，保留审计痕迹。"""
    if not context.merchant_id:
        return 0
    now = datetime.now()
    rows = (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == context.merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.status == ACTIVE_BINDING_STATUS,
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.status = "deleted"
        row.deleted_at = now
        row.invalid_reason = reason
        row.updated_at = now
        row.updated_by = context.user_id
    db.commit()
    return len(rows)


def validate_douyin_agent_binding(
    *,
    db: Session,
    context: RequestContext,
    account_open_id: str,
    agent_id: str | None,
    require_existing_binding: bool = True,
) -> BindingValidationResult:
    """校验当前商户是否可让指定企业号使用指定智能体。"""
    base = _validate_account_context(db=db, context=context, account_open_id=account_open_id)
    if not base.allowed:
        return base
    if not agent_id:
        return BindingValidationResult(
            allowed=False,
            reason_code="AGENT_NOT_FOUND",
            audit={**base.audit, "agent_id": agent_id},
        )

    agent = _find_agent_by_agent_id(db, agent_id=agent_id)
    if agent is None:
        return BindingValidationResult(
            allowed=False,
            reason_code="AGENT_NOT_FOUND",
            audit={**base.audit, "agent_id": agent_id},
        )
    if agent.merchant_id != context.merchant_id:
        return BindingValidationResult(
            allowed=False,
            reason_code="AGENT_MERCHANT_DENIED",
            audit={**base.audit, "agent_id": agent_id, "agent_merchant_id": agent.merchant_id},
        )
    if agent.status != "active":
        return BindingValidationResult(
            allowed=False,
            reason_code="AGENT_NOT_ACTIVE",
            audit={**base.audit, "agent_id": agent_id, "agent_status": agent.status},
        )

    if require_existing_binding:
        binding = _find_active_binding(
            db,
            merchant_id=context.merchant_id or "",
            account_open_id=account_open_id,
        )
        if binding is None:
            return BindingValidationResult(
                allowed=False,
                reason_code="AGENT_BINDING_NOT_FOUND",
                audit={**base.audit, "agent_id": agent_id},
            )
        if binding.agent_id != agent_id or binding.status != ACTIVE_BINDING_STATUS:
            return BindingValidationResult(
                allowed=False,
                reason_code="AGENT_BINDING_INVALID",
                audit={
                    **base.audit,
                    "agent_id": agent_id,
                    "bound_agent_id": binding.agent_id,
                    "binding_status": binding.status,
                },
            )

    return BindingValidationResult(
        allowed=True,
        audit={**base.audit, "agent_id": agent_id, "agent_status": agent.status},
    )


def resolve_webhook_bound_agent(
    db: Session,
    *,
    account_open_id: str,
) -> WebhookBoundAgentResult:
    """解析 webhook 企业号绑定的 active 默认智能体，不依赖前端 RequestContext。"""
    normalized_account_open_id = str(account_open_id or "").strip()
    audit: dict[str, Any] = {"account_open_id": normalized_account_open_id}
    if not normalized_account_open_id:
        return WebhookBoundAgentResult(
            allowed=False,
            reason_code="account_open_id_missing",
            audit=audit,
        )

    account = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.open_id == normalized_account_open_id,
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .first()
    )
    if account is None:
        return WebhookBoundAgentResult(
            allowed=False,
            reason_code="account_not_authorized",
            audit=audit,
        )
    merchant_id = str(account.merchant_id or "").strip()
    tenant_id = str(account.tenant_id or "").strip() or None
    audit = {
        **audit,
        "authorized_account_id": account.id,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "bind_status": account.bind_status,
    }
    if not merchant_id:
        return WebhookBoundAgentResult(
            allowed=False,
            reason_code="merchant_context_missing",
            account=account,
            audit=audit,
        )

    binding = _find_active_binding(
        db,
        merchant_id=merchant_id,
        account_open_id=normalized_account_open_id,
    )
    if binding is None:
        return WebhookBoundAgentResult(
            allowed=False,
            reason_code="agent_binding_not_found",
            account=account,
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            audit=audit,
        )

    agent = _find_agent_any_status(db, merchant_id=merchant_id, agent_id=binding.agent_id)
    if agent is None or agent.status != "active":
        return WebhookBoundAgentResult(
            allowed=False,
            reason_code="agent_inactive",
            account=account,
            binding=binding,
            agent=agent,
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            audit={
                **audit,
                "binding_id": binding.id,
                "agent_id": binding.agent_id,
                "agent_status": getattr(agent, "status", None),
            },
        )

    return WebhookBoundAgentResult(
        allowed=True,
        account=account,
        binding=binding,
        agent=agent,
        merchant_id=merchant_id,
        tenant_id=tenant_id,
        audit={
            **audit,
            "binding_id": binding.id,
            "agent_id": agent.agent_id,
            "agent_status": agent.status,
        },
    )


def _validate_account_context(
    *,
    db: Session,
    context: RequestContext,
    account_open_id: str,
) -> BindingValidationResult:
    audit = {
        "user_id": context.user_id,
        "merchant_id": context.merchant_id,
        "account_open_id": account_open_id,
        "super_admin": context.super_admin,
    }
    if not context.merchant_id:
        return BindingValidationResult(
            allowed=False,
            reason_code="MERCHANT_CONTEXT_MISSING",
            audit=audit,
        )

    account = _find_account_by_open_id(db, account_open_id)
    if account is None:
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_NOT_FOUND",
            audit=audit,
        )

    owner_merchant_id = getattr(account, "merchant_id", None)
    if not owner_merchant_id or str(owner_merchant_id) != str(context.merchant_id):
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED",
            audit={
                **audit,
                "authorized_account_id": account.id,
                "owner_merchant_id": owner_merchant_id,
                "owner_tenant_id": getattr(account, "tenant_id", None),
            },
        )
    if account.bind_status == DELETED_ACCOUNT_BIND_STATUS:
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_DELETED",
            audit={**audit, "authorized_account_id": account.id, "bind_status": account.bind_status},
        )
    if account.bind_status != 1:
        return BindingValidationResult(
            allowed=False,
            reason_code="DOUYIN_ACCOUNT_NOT_AUTHORIZED",
            audit={**audit, "authorized_account_id": account.id, "bind_status": account.bind_status},
        )
    return BindingValidationResult(
        allowed=True,
        audit={
            **audit,
            "authorized_account_id": account.id,
            "authorized_account_open_id": account.open_id,
            "bind_status": account.bind_status,
        },
    )


def _find_account_by_open_id(db: Session, account_open_id: str) -> DouyinAuthorizedAccount | None:
    return (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == str(account_open_id).strip())
        .first()
    )


def _find_agent_any_status(db: Session, *, merchant_id: str, agent_id: str) -> AiAgent | None:
    return (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.merchant_id == merchant_id,
            AiAgent.status != "deleted",
        )
        .first()
    )


def _find_agent_by_agent_id(db: Session, *, agent_id: str) -> AiAgent | None:
    return (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.status != "deleted",
        )
        .first()
    )


def _find_active_binding(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> DouyinAccountAgentBinding | None:
    return (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.status == ACTIVE_BINDING_STATUS,
            DouyinAccountAgentBinding.is_default.is_(True),
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .order_by(DouyinAccountAgentBinding.id.desc())
        .first()
    )


def _find_historical_binding(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    agent_id: str,
) -> DouyinAccountAgentBinding | None:
    return (
        db.query(DouyinAccountAgentBinding)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.account_open_id == account_open_id,
            DouyinAccountAgentBinding.agent_id == agent_id,
            DouyinAccountAgentBinding.status != ACTIVE_BINDING_STATUS,
        )
        .order_by(DouyinAccountAgentBinding.id.desc())
        .first()
    )


def _authorization_status(account: DouyinAuthorizedAccount | None) -> str:
    if account is None:
        return "not_found"
    return "authorized" if account.bind_status == 1 else "unauthorized"
