"""AI小高智能体能力服务业务路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from apps.agents import services as agents_service
from apps.agents.dependencies import GatewayContext, get_gateway_context, require_agents_context
from apps.agents.schemas import (
    AgentKnowledgeCategoriesOut,
    AgentKnowledgeCategoriesResponse,
    AgentKnowledgeCategoriesUpdate,
    AiAgentCreate,
    AiAgentListResponse,
    AiAgentResponse,
    AiAgentTrainingChatRequest,
    AiAgentTrainingChatResponse,
    AiAgentTrainingChatResponseData,
    AiAgentUpdate,
)


router = APIRouter(prefix="/api/agents", tags=["AI小高智能体"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "AI_AGENT_NOT_FOUND", "message": "智能体不存在"})


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _binding_not_found(exc: ValueError) -> HTTPException:
    code = str(exc)
    if code == "CATEGORY_NOT_USABLE":
        return HTTPException(status_code=404, detail={"code": code, "message": "知识分类不存在或不可用"})
    if code in {"AGENT_NOT_FOUND", "AGENT_NOT_ACTIVE"}:
        return _not_found()
    return _bad_request(code, "知识分类绑定参数无效")


@router.get("", response_model=AiAgentListResponse)
def list_agents(
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """列出当前商户智能体。"""
    context = require_agents_context(gateway_context)
    try:
        agents = agents_service.list_agents(db, context)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": agents, "message": "success"}


@router.post("", response_model=AiAgentResponse)
def create_agent(
    payload: AiAgentCreate,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """创建当前商户智能体。"""
    context = require_agents_context(gateway_context)
    try:
        agent = agents_service.create_agent(db, context, payload)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": agent, "message": "success"}


@router.get("/{agent_id}", response_model=AiAgentResponse)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """获取当前商户智能体详情。"""
    context = require_agents_context(gateway_context)
    agent = agents_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    return {"success": True, "data": agent, "message": "success"}


@router.put("/{agent_id}", response_model=AiAgentResponse)
def update_agent(
    agent_id: str,
    payload: AiAgentUpdate,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """更新当前商户智能体。"""
    context = require_agents_context(gateway_context)
    agent = agents_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    agent = agents_service.update_agent(db, agent, payload)
    return {"success": True, "data": agent, "message": "success"}


@router.delete("/{agent_id}", response_model=AiAgentResponse)
def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """软删除当前商户智能体。"""
    context = require_agents_context(gateway_context)
    agent = agents_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    agent = agents_service.soft_delete_agent(db, agent)
    return {"success": True, "data": agent, "message": "success"}


@router.get("/{agent_id}/knowledge-categories", response_model=AgentKnowledgeCategoriesResponse)
def get_agent_knowledge_categories(
    agent_id: str,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """获取当前商户 Agent 的手动知识分类绑定。"""
    context = require_agents_context(gateway_context)
    try:
        category_keys = agents_service.list_agent_category_keys(db, context=context, agent_id=agent_id)
    except ValueError as exc:
        raise _binding_not_found(exc) from exc
    return {
        "success": True,
        "data": AgentKnowledgeCategoriesOut(
            agent_id=agent_id,
            category_keys=category_keys,
            effective_category_keys=agents_service.build_effective_category_keys(category_keys),
        ),
        "message": "success",
    }


@router.put("/{agent_id}/knowledge-categories", response_model=AgentKnowledgeCategoriesResponse)
def update_agent_knowledge_categories(
    agent_id: str,
    payload: AgentKnowledgeCategoriesUpdate,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """替换当前商户 Agent 的手动知识分类绑定。"""
    context = require_agents_context(gateway_context)
    try:
        agents_service.replace_agent_categories(
            db,
            context=context,
            agent_id=agent_id,
            category_keys=payload.category_keys,
        )
        category_keys = agents_service.list_agent_category_keys(db, context=context, agent_id=agent_id)
    except ValueError as exc:
        raise _binding_not_found(exc) from exc
    return {
        "success": True,
        "data": AgentKnowledgeCategoriesOut(
            agent_id=agent_id,
            category_keys=category_keys,
            effective_category_keys=agents_service.build_effective_category_keys(category_keys),
        ),
        "message": "success",
    }


@router.post("/{agent_id}/training-chat", response_model=AiAgentTrainingChatResponse)
def training_chat(
    agent_id: str,
    payload: AiAgentTrainingChatRequest,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """训练对话预览，不调用 LLM。"""
    context = require_agents_context(gateway_context)
    agent = agents_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    try:
        result = agents_service.preview_training_chat(agent, payload.message)
    except ValueError as exc:
        raise _bad_request(str(exc), "训练问题不能为空") from exc
    return {
        "success": True,
        "data": AiAgentTrainingChatResponseData(
            reply_text=result.reply_text,
            warnings=result.warnings,
            llm_used=result.llm_used,
            knowledge_used=result.knowledge_used,
        ),
        "message": "success",
    }
