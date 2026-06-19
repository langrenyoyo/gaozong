"""AI小高智能体管理接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_any_permission
from app.database import get_db
from app.schemas import (
    AgentKnowledgeCategoriesResponse,
    AgentKnowledgeCategoriesOut,
    AgentKnowledgeCategoriesUpdate,
    AiAgentCreate,
    AiAgentListResponse,
    AiAgentOut,
    AiAgentResponse,
    AiAgentTrainingChatRequest,
    AiAgentTrainingChatResponse,
    AiAgentTrainingChatResponseData,
    AiAgentUpdate,
)
from app.services import ai_agent_service
from app.services.agent_knowledge_category_service import (
    build_effective_category_keys,
    list_agent_category_keys,
    replace_agent_categories,
)


router = APIRouter(prefix="/agents", tags=["AI小高智能体"])


def _auth(context: RequestContext) -> RequestContext:
    """校验 AI小高智能体权限。

    auto_wechat:agent 是历史/过渡兼容权限；正式 NewCarProject 权限字典应补
    auto_wechat:ai_agents。AI小高助手/微信代理后续应使用独立权限，例如
    auto_wechat:wechat_agent。
    """
    return require_any_permission(["auto_wechat:ai_agents", "auto_wechat:agent"])(context)


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
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        agents = ai_agent_service.list_agents(db, context)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": agents, "message": "success"}


@router.post("", response_model=AiAgentResponse)
def create_agent(
    payload: AiAgentCreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        agent = ai_agent_service.create_agent(db, context, payload)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": agent, "message": "success"}


@router.get("/{agent_id}", response_model=AiAgentResponse)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    agent = ai_agent_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    return {"success": True, "data": agent, "message": "success"}


@router.put("/{agent_id}", response_model=AiAgentResponse)
def update_agent(
    agent_id: str,
    payload: AiAgentUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    agent = ai_agent_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    agent = ai_agent_service.update_agent(db, agent, payload)
    return {"success": True, "data": agent, "message": "success"}


@router.delete("/{agent_id}", response_model=AiAgentResponse)
def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    agent = ai_agent_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    agent = ai_agent_service.soft_delete_agent(db, agent)
    return {"success": True, "data": agent, "message": "success"}


@router.get("/{agent_id}/knowledge-categories", response_model=AgentKnowledgeCategoriesResponse)
def get_agent_knowledge_categories(
    agent_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        category_keys = list_agent_category_keys(db, context=context, agent_id=agent_id)
    except ValueError as exc:
        raise _binding_not_found(exc) from exc
    return {
        "success": True,
        "data": AgentKnowledgeCategoriesOut(
            agent_id=agent_id,
            category_keys=category_keys,
            effective_category_keys=build_effective_category_keys(category_keys),
        ),
        "message": "success",
    }


@router.put("/{agent_id}/knowledge-categories", response_model=AgentKnowledgeCategoriesResponse)
def update_agent_knowledge_categories(
    agent_id: str,
    payload: AgentKnowledgeCategoriesUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        replace_agent_categories(db, context=context, agent_id=agent_id, category_keys=payload.category_keys)
        category_keys = list_agent_category_keys(db, context=context, agent_id=agent_id)
    except ValueError as exc:
        raise _binding_not_found(exc) from exc
    return {
        "success": True,
        "data": AgentKnowledgeCategoriesOut(
            agent_id=agent_id,
            category_keys=category_keys,
            effective_category_keys=build_effective_category_keys(category_keys),
        ),
        "message": "success",
    }


@router.post("/{agent_id}/training-chat", response_model=AiAgentTrainingChatResponse)
def training_chat(
    agent_id: str,
    payload: AiAgentTrainingChatRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    agent = ai_agent_service.get_agent(db, context, agent_id)
    if not agent:
        raise _not_found()
    try:
        result = ai_agent_service.preview_training_chat(agent, payload.message)
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
