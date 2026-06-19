"""Agent 知识分类绑定服务。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AgentKnowledgeCategory, AiAgent
from app.services.knowledge_category_service import (
    ACTIVE_STATUS,
    BASE_CATEGORY_KEY,
    build_effective_category_keys,
    ensure_category_usable_for_merchant,
    list_visible_knowledge_categories,
    manual_category_keys,
    normalize_category_key,
    normalize_category_keys,
    require_context_merchant,
)


DELETED_STATUS = "deleted"


def _get_active_agent(db: Session, *, merchant_id: str, agent_id: str) -> AiAgent:
    agent = (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.merchant_id == merchant_id,
            AiAgent.status != "deleted",
        )
        .first()
    )
    if agent is None:
        raise ValueError("AGENT_NOT_FOUND")
    if agent.status != "active":
        raise ValueError("AGENT_NOT_ACTIVE")
    return agent


def _query_active_binding(
    db: Session,
    *,
    merchant_id: str,
    agent_id: str,
    category_key: str,
) -> AgentKnowledgeCategory | None:
    return (
        db.query(AgentKnowledgeCategory)
        .filter(
            AgentKnowledgeCategory.merchant_id == merchant_id,
            AgentKnowledgeCategory.agent_id == agent_id,
            AgentKnowledgeCategory.category_key == category_key,
            AgentKnowledgeCategory.status == ACTIVE_STATUS,
            AgentKnowledgeCategory.deleted_at.is_(None),
        )
        .first()
    )


def bind_agent_categories(
    db: Session,
    *,
    context: RequestContext,
    agent_id: str,
    category_keys: list[str],
) -> list[AgentKnowledgeCategory]:
    """为当前商户 Agent 绑定一个或多个 merchant 分类，重复绑定保持幂等。"""
    merchant_id = require_context_merchant(context)
    keys = manual_category_keys(category_keys)
    _get_active_agent(db, merchant_id=merchant_id, agent_id=agent_id)

    now = datetime.now()
    rows: list[AgentKnowledgeCategory] = []
    for key in keys:
        ensure_category_usable_for_merchant(db, context=context, category_key=key)
        row = _query_active_binding(
            db,
            merchant_id=merchant_id,
            agent_id=agent_id,
            category_key=key,
        )
        if row is None:
            row = AgentKnowledgeCategory(
                merchant_id=merchant_id,
                tenant_id=None,
                agent_id=agent_id,
                category_key=key,
                scope_type="merchant",
                is_base=0,
                status=ACTIVE_STATUS,
                created_at=now,
                updated_at=now,
                created_by=context.user_id,
                updated_by=context.user_id,
            )
            db.add(row)
            db.flush()
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def list_agent_category_keys(
    db: Session,
    *,
    context: RequestContext,
    agent_id: str,
) -> list[str]:
    """列出当前商户 Agent 的 active 手动绑定分类，不自动追加 base。"""
    merchant_id = require_context_merchant(context)
    _get_active_agent(db, merchant_id=merchant_id, agent_id=agent_id)
    rows = (
        db.query(AgentKnowledgeCategory)
        .filter(
            AgentKnowledgeCategory.merchant_id == merchant_id,
            AgentKnowledgeCategory.agent_id == agent_id,
            AgentKnowledgeCategory.status == ACTIVE_STATUS,
            AgentKnowledgeCategory.deleted_at.is_(None),
        )
        .order_by(AgentKnowledgeCategory.id.asc())
        .all()
    )
    return [row.category_key for row in rows]


def replace_agent_categories(
    db: Session,
    *,
    context: RequestContext,
    agent_id: str,
    category_keys: list[str],
) -> list[AgentKnowledgeCategory]:
    """替换当前商户 Agent 的手动分类绑定，移除项使用软删。"""
    merchant_id = require_context_merchant(context)
    keys = manual_category_keys(category_keys)
    _get_active_agent(db, merchant_id=merchant_id, agent_id=agent_id)
    for key in keys:
        ensure_category_usable_for_merchant(db, context=context, category_key=key)

    now = datetime.now()
    keep = set(keys)
    active_rows = (
        db.query(AgentKnowledgeCategory)
        .filter(
            AgentKnowledgeCategory.merchant_id == merchant_id,
            AgentKnowledgeCategory.agent_id == agent_id,
            AgentKnowledgeCategory.status == ACTIVE_STATUS,
            AgentKnowledgeCategory.deleted_at.is_(None),
        )
        .all()
    )
    for row in active_rows:
        if row.category_key not in keep:
            row.status = DELETED_STATUS
            row.deleted_at = now
            row.updated_at = now
            row.updated_by = context.user_id
    db.flush()
    return bind_agent_categories(db, context=context, agent_id=agent_id, category_keys=keys)


def unbind_agent_category(
    db: Session,
    *,
    context: RequestContext,
    agent_id: str,
    category_key: str,
) -> AgentKnowledgeCategory:
    """软删当前商户 Agent 的单个分类绑定。"""
    merchant_id = require_context_merchant(context)
    key = normalize_category_key(category_key)
    _get_active_agent(db, merchant_id=merchant_id, agent_id=agent_id)
    row = _query_active_binding(
        db,
        merchant_id=merchant_id,
        agent_id=agent_id,
        category_key=key,
    )
    if row is None:
        raise ValueError("AGENT_CATEGORY_BINDING_NOT_FOUND")

    now = datetime.now()
    row.status = DELETED_STATUS
    row.deleted_at = now
    row.updated_at = now
    row.updated_by = context.user_id
    db.commit()
    db.refresh(row)
    return row
