"""AI小高智能体能力服务业务逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AgentKnowledgeCategory, AiAgent, DouyinAccountAgentBinding, KnowledgeCategory
from apps.agents.schemas import AiAgentCreate, AiAgentUpdate


ACTIVE_STATUSES = ("active", "disabled")
ACTIVE_STATUS = "active"
BASE_CATEGORY_KEY = "base"
DELETED_STATUS = "deleted"
ACTIVE_ACCOUNT_BINDING_STATUS = "active"
ACTIVE_BINDING_BLOCK_DELETE_ERROR = "AI_AGENT_ACTIVE_BINDING_EXISTS"


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
    """创建智能体，merchant_id 只取可信上下文。

    store_name 服务端校验：trim 后必须非空、长度 ≤255（P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1）。
    prompt/knowledge_base_text/store_phone/store_wechat 已完整退出，不再写入。
    """
    merchant_id = require_context_merchant(context)
    store_name = _validate_store_name(payload.store_name)
    agent = AiAgent(
        agent_id=f"agent_{uuid4().hex[:16]}",
        merchant_id=merchant_id,
        name=payload.name.strip(),
        store_name=store_name,
        avatar_seed=f"{merchant_id}-{uuid4().hex[:12]}",
        avatar_url=payload.avatar_url,
        status="active",
        # 商家可配置变量（固定提示词模板 V2.0 注入）
        store_address=payload.store_address,
        business_hours=payload.business_hours,
        sales_cities=payload.sales_cities,
        sales_brands=payload.sales_brands,
        purchase_cities=payload.purchase_cities,
        purchase_brands=payload.purchase_brands,
        after_hours_reply=payload.after_hours_reply,
        vehicle_condition_reply=payload.vehicle_condition_reply,
        appraiser_off_hours_reply=payload.appraiser_off_hours_reply,
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
    """更新智能体配置。

    store_name 更新执行同校验（trim 后非空、≤255）；
    prompt/knowledge_base_text/store_phone/store_wechat 已完整退出，不再更新。
    """
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        agent.name = data["name"].strip()
    if "store_name" in data and data["store_name"] is not None:
        agent.store_name = _validate_store_name(data["store_name"])
    if "avatar_url" in data:
        agent.avatar_url = data["avatar_url"]
    if "status" in data and data["status"] is not None:
        agent.status = data["status"]
    # 商家可配置变量（固定提示词模板 V2.0 注入）
    _STORE_CONFIG_FIELDS = (
        "store_address", "business_hours",
        "sales_cities", "sales_brands", "purchase_cities", "purchase_brands",
        "after_hours_reply", "vehicle_condition_reply", "appraiser_off_hours_reply",
    )
    for field in _STORE_CONFIG_FIELDS:
        if field in data:
            setattr(agent, field, data[field])
    db.commit()
    db.refresh(agent)
    return agent


def _validate_store_name(store_name: str) -> str:
    """store_name 服务端校验：trim 后必须非空、长度 ≤255。返回 trim 后的值。"""
    value = (store_name or "").strip()
    if not value:
        raise ValueError("store_name 不能为空")
    if len(value) > 255:
        raise ValueError("store_name 长度不能超过 255")
    return value


def build_agent_config(agent: AiAgent, *, category_keys: list[str]) -> dict:
    """唯一服务端白名单构造器：从可信 AiAgent ORM + 服务端知识绑定读取。

    P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1：三个场景（Agent Preview / 会话 Preview / 自动回复）
    必须调用同一实现。前端或调用方不得提交 agent_config 覆盖以下可信数据：
    agent_id / agent_name / store_name / 门店普通事实字段 / status / allowed_category_keys / rag_enabled。

    store_name 运行时兜底（混合版本/异常数据防御）：trim(store_name) or trim(agent.name) or "未命名门店"。
    不包含四旧字段（prompt/knowledge_base_text/store_phone/store_wechat）与运行态字段
    （conversation_history/known_customer/contact_state/customer_memory/run_id/attempt_count/发送策略）。
    """
    keys = list(category_keys or [])
    store_name = (agent.store_name or "").strip() or (agent.name or "").strip() or "未命名门店"
    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.name or "",
        "store_name": store_name,
        "status": agent.status,
        "allowed_category_keys": keys,
        "rag_enabled": bool(keys),
        # 门店普通事实字段（固定提示词模板 V2.0 注入）
        "store_address": agent.store_address or "",
        "business_hours": agent.business_hours or "",
        "sales_cities": agent.sales_cities or "",
        "sales_brands": agent.sales_brands or "",
        "purchase_cities": agent.purchase_cities or "",
        "purchase_brands": agent.purchase_brands or "",
        "after_hours_reply": agent.after_hours_reply or "",
        "vehicle_condition_reply": agent.vehicle_condition_reply or "",
        "appraiser_off_hours_reply": agent.appraiser_off_hours_reply or "",
    }


def has_active_douyin_account_binding(db: Session, *, merchant_id: str, agent_id: str) -> bool:
    """判断智能体是否仍被抖音企业号 active 绑定。"""
    return (
        db.query(DouyinAccountAgentBinding.id)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.agent_id == agent_id,
            DouyinAccountAgentBinding.status == ACTIVE_ACCOUNT_BINDING_STATUS,
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def hard_delete_agent(db: Session, agent: AiAgent) -> dict[str, Any]:
    """硬删除未被企业号 active 绑定的智能体。"""
    if has_active_douyin_account_binding(db, merchant_id=agent.merchant_id, agent_id=agent.agent_id):
        raise ValueError(ACTIVE_BINDING_BLOCK_DELETE_ERROR)

    payload = {column.name: getattr(agent, column.name) for column in AiAgent.__table__.columns}
    db.query(AgentKnowledgeCategory).filter(
        AgentKnowledgeCategory.merchant_id == agent.merchant_id,
        AgentKnowledgeCategory.agent_id == agent.agent_id,
    ).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()
    return payload


def soft_delete_agent(db: Session, agent: AiAgent) -> dict[str, Any]:
    """兼容旧导出；一期智能体删除已改为硬删除。"""
    return hard_delete_agent(db, agent)


def preview_training_chat(agent: AiAgent, message: str) -> TrainingChatResult:
    """生成训练预览回复，不调用 LLM 或外部系统。

    P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1：prompt/knowledge_base_text 已完整退出，
    训练预览仅使用 store_name（门店名称）等可信字段。
    """
    text = message.strip()
    if not text:
        raise ValueError("MESSAGE_REQUIRED")

    store_name = (agent.store_name or "").strip() or (agent.name or "").strip() or "未命名门店"
    reply_text = (
        f"{agent.name}：我会按当前智能体配置回答。"
        f"客户问题是“{text}”。"
        f"门店名称：{store_name}"
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
    """返回用户显式选择的分类，base 也按真实绑定保存。"""
    return normalize_category_keys(category_keys)


def build_effective_category_keys(category_keys: list[str]) -> list[str]:
    """构造实际可用分类；base 只有被显式选择时才生效。"""
    keys: list[str] = []
    for key in category_keys:
        normalized = normalize_category_key(key)
        if normalized not in keys:
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
    """为当前商户 Agent 绑定知识分类，重复绑定保持幂等。"""
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
                scope_type="system" if key == BASE_CATEGORY_KEY else "merchant",
                is_base=1 if key == BASE_CATEGORY_KEY else 0,
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
