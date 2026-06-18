"""AI小高智能体最小管理服务。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import AiAgent
from app.schemas import AiAgentCreate, AiAgentUpdate


ACTIVE_STATUSES = ("active", "disabled")


@dataclass
class TrainingChatResult:
    """训练预览结果。"""

    reply_text: str
    warnings: list[str]
    llm_used: bool
    knowledge_used: bool


def _require_context_merchant(context: RequestContext) -> str:
    if not context.merchant_id:
        raise ValueError("MERCHANT_ID_REQUIRED")
    return context.merchant_id


def list_agents(db: Session, context: RequestContext) -> list[AiAgent]:
    """列出当前商户可见的智能体。"""
    merchant_id = _require_context_merchant(context)
    return (
        db.query(AiAgent)
        .filter(AiAgent.merchant_id == merchant_id, AiAgent.status.in_(ACTIVE_STATUSES))
        .order_by(AiAgent.id.desc())
        .all()
    )


def create_agent(db: Session, context: RequestContext, payload: AiAgentCreate) -> AiAgent:
    """创建智能体，merchant_id 只取可信上下文。"""
    merchant_id = _require_context_merchant(context)
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
    merchant_id = _require_context_merchant(context)
    return (
        db.query(AiAgent)
        .filter(
            AiAgent.agent_id == agent_id,
            AiAgent.merchant_id == merchant_id,
            AiAgent.status != "deleted",
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
    agent.status = "deleted"
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
