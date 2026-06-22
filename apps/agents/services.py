"""AI小高智能体能力服务业务逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AgentKnowledgeCategory, AiAgent, KnowledgeCategory
from apps.agents.schemas import AiAgentCreate, AiAgentUpdate


ACTIVE_STATUSES = ("active", "disabled")
ACTIVE_STATUS = "active"
BASE_CATEGORY_KEY = "base"
DELETED_STATUS = "deleted"


@dataclass
class TrainingChatResult:
    """训练预览结果。"""

    reply_text: str
    warnings: list[str]
    llm_used: bool
    knowledge_used: bool


def require_context_merchant(context: RequestContext) -> str:
    """读取可信 RequestContext 中的商户 ID。"""
    if not context.merchant_id:
        raise ValueError("MERCHANT_ID_REQUIRED")
    return context.merchant_id


def list_agents(db: Session, context: RequestContext) -> list[AiAgent]:
    """列出当前商户可见的智能体。"""
    merchant_id = require_context_merchant(context)
    return (
        db.query(AiAgent)
        .filter(AiAgent.merchant_id == merchant_id, AiAgent.status.in_(ACTIVE_STATUSES))
        .order_by(AiAgent.id.desc())
        .all()
    )


def create_agent(db: Session, context: RequestContext, payload: AiAgentCreate) -> AiAgent:
    """创建智能体，merchant_id 只取可信上下文。"""
    merchant_id = require_context_merchant(context)
    agent = AiAgent(
        agent_id=f"agent_{uuid4().hex[:16]}",
        merchant_id=merchant_id,
        name=payload.name.strip(),
        avatar_seed=f"{merchant_id}-{uuid4().hex[:12]}",
        avatar_url=payload.avatar_url,
        prompt=payload.prompt or "",
        knowledge_base_text=payload.knowledge_base_text or "",
        status="active",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def get_agent(db: Session, context: RequestContext, agent_id: str) -> AiAgent | None:
    """按当前商户获取未删除智能体。"""
    merchant_id = require_context_merchant(context)
    return (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.merchant_id == merchant_id,
            AiAgent.status != DELETED_STATUS,
        )
        .first()
    )


def update_agent(db: Session, agent: AiAgent, payload: AiAgentUpdate) -> AiAgent:
    """更新智能体配置。"""
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        agent.name = data["name"].strip()
    if "prompt" in data and data["prompt"] is not None:
        agent.prompt = data["prompt"]
    if "knowledge_base_text" in data and data["knowledge_base_text"] is not None:
        agent.knowledge_base_text = data["knowledge_base_text"]
    if "avatar_url" in data:
        agent.avatar_url = data["avatar_url"]
    if "status" in data and data["status"] is not None:
        agent.status = data["status"]
    db.commit()
    db.refresh(agent)
    return agent


def soft_delete_agent(db: Session, agent: AiAgent) -> AiAgent:
    """软删除智能体。"""
    agent.status = DELETED_STATUS
    db.commit()
    db.refresh(agent)
    return agent


def preview_training_chat(agent: AiAgent, message: str) -> TrainingChatResult:
    """生成训练预览回复，不调用 LLM 或外部系统。"""
    text = message.strip()
    if not text:
        raise ValueError("MESSAGE_REQUIRED")

    prompt_hint = agent.prompt.strip() or "暂无提示词"
    knowledge_hint = agent.knowledge_base_text.strip() or "暂无知识库内容"
    reply_text = (
        f"{agent.name}：我会按当前智能体配置回答。"
        f"客户问题是“{text}”。"
        f"当前提示词要求：{prompt_hint}"
        f"。可参考知识库：{knowledge_hint}"
        "。建议先确认车型、预算、看车时间和联系方式，再引导客户留资。"
    )
    return TrainingChatResult(
        reply_text=reply_text,
        warnings=[],
        llm_used=False,
        knowledge_used=True,
    )


def normalize_category_key(category_key: str | None) -> str:
    """规范化分类 key，保留中文和大小写语义。"""
    key = (category_key or "").strip()
    if not key:
        raise ValueError("CATEGORY_KEY_REQUIRED")
    return key


def normalize_category_keys(category_keys: list[str]) -> list[str]:
    """去重并规范化分类 key。"""
    keys: list[str] = []
    for item in category_keys:
        key = normalize_category_key(item)
        if key not in keys:
            keys.append(key)
    return keys


def manual_category_keys(category_keys: list[str]) -> list[str]:
    """过滤 base 分类，base 是默认有效分类，不落手动绑定。"""
    return [key for key in normalize_category_keys(category_keys) if key != BASE_CATEGORY_KEY]


def build_effective_category_keys(category_keys: list[str]) -> list[str]:
    """构造实际可用分类：base 永远默认可见。"""
    keys = [BASE_CATEGORY_KEY]
    for key in category_keys:
        normalized = normalize_category_key(key)
        if normalized != BASE_CATEGORY_KEY and normalized not in keys:
            keys.append(normalized)
    return keys


def ensure_category_usable_for_merchant(
    db: Session,
    *,
    context: RequestContext,
    category_key: str,
) -> str:
    """校验分类是否为 base 或当前商户 active 分类。"""
    merchant_id = require_context_merchant(context)
    key = normalize_category_key(category_key)
    if key == BASE_CATEGORY_KEY:
        return key
    row = (
        db.query(KnowledgeCategory)
        .filter(
            KnowledgeCategory.merchant_id == merchant_id,
            KnowledgeCategory.category_key == key,
            KnowledgeCategory.status == ACTIVE_STATUS,
        )
        .first()
    )
    if row is None:
        raise ValueError("CATEGORY_NOT_USABLE")
    return key


def _get_active_agent(db: Session, *, merchant_id: str, agent_id: str) -> AiAgent:
    agent = (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.merchant_id == merchant_id,
            AiAgent.status != DELETED_STATUS,
        )
        .first()
    )
    if agent is None:
        raise ValueError("AGENT_NOT_FOUND")
    if agent.status != ACTIVE_STATUS:
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
    """为当前商户 Agent 绑定 merchant 分类，重复绑定保持幂等。"""
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
    """替换当前商户 Agent 的手动分类绑定，移除项使用软删除。"""
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
