"""AI小高智能体管理接口。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import (
    AgentKnowledgeCategoriesResponse,
    AgentKnowledgeCategoriesOut,
    AgentKnowledgeCategoriesUpdate,
    AiAgentCreate,
    AiAgentListResponse,
    AiAgentOut,
    AiAgentPreviewRequest,
    AiAgentPreviewResponse,
    AiAgentPreviewResponseData,
    AiAgentResponse,
    AiAgentTrainingChatRequest,
    AiAgentTrainingChatResponse,
    AiAgentTrainingChatResponseData,
    AiAgentUpdate,
)
from app.services import ai_agent_service
from app.services.agent_knowledge_category_service import (
    build_effective_category_keys,
    ensure_category_usable_for_merchant,
    list_agent_category_keys,
    normalize_category_keys,
    replace_agent_categories,
)
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)


router = APIRouter(prefix="/agents", tags=["AI小高智能体"])
logger = logging.getLogger(__name__)


def _auth(context: RequestContext) -> RequestContext:
    """校验 AI小高智能体权限；智能体归属抖音 AI 客服闭环。"""
    return require_permission("auto_wechat:douyin_ai_cs")(context)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "AI_AGENT_NOT_FOUND", "message": "智能体不存在"})


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


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
    try:
        deleted = ai_agent_service.hard_delete_agent(db, agent)
    except ValueError as exc:
        if str(exc) == ai_agent_service.ACTIVE_BINDING_BLOCK_DELETE_ERROR:
            raise _conflict(str(exc), "智能体已绑定抖音企业号，请先解绑后再删除") from exc
        raise _bad_request(str(exc), "智能体删除失败") from exc
    return {"success": True, "data": deleted, "message": "success"}


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


@router.post("/preview", response_model=AiAgentPreviewResponse)
def preview_agent(
    payload: AiAgentPreviewRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    if not context.merchant_id:
        raise _bad_request("MERCHANT_ID_REQUIRED", "缺少可信商户上下文")

    text = payload.message.strip()
    if not text:
        raise _bad_request("MESSAGE_REQUIRED", "预览问题不能为空")

    agent_id = (payload.agent_id or "draft-agent").strip() or "draft-agent"
    if payload.agent_id:
        agent = ai_agent_service.get_agent(db, context, payload.agent_id)
        if not agent:
            raise _not_found()

    try:
        category_keys = normalize_category_keys(payload.knowledge_category_keys)
        for key in category_keys:
            ensure_category_usable_for_merchant(db, context=context, category_key=key)
    except ValueError as exc:
        raise _binding_not_found(exc) from exc

    name = payload.name.strip() or "AI小高智能体"
    request_payload = {
        "tenant_id": context.source_system or "new_car_project",
        "account_id": "agent-preview",
        "douyin_account_id": "agent-preview",
        "merchant_id": context.merchant_id,
        "agent_id": agent_id,
        "agent_config": {
            "agent_id": agent_id,
            "agent_name": name,
            "system_prompt": payload.persona_prompt or "",
            "prompt": payload.persona_prompt or "",
            "knowledge_base_text": payload.knowledge_prompt or "",
            "status": "active",
            "allowed_category_keys": category_keys,
            "rag_enabled": bool(category_keys),
        },
        "latest_message": text,
        "max_history_messages": 1,
        "conversation_history": [],
    }

    try:
        result = get_xg_douyin_ai_cs_client().suggest_reply(
            context=context,
            conversation_id="agent-preview",
            request=request_payload,
        )
    except XgDouyinAiCsClientError as exc:
        logger.warning(
            "agent_preview_llm_failed merchant_id=%s agent_id=%s error=%s",
            context.merchant_id,
            agent_id,
            exc,
        )
        return {
            "success": True,
            "data": AiAgentPreviewResponseData(
                reply_text="",
                source="error",
                used_category_keys=category_keys,
                manual_required=True,
                error="AI 预览暂时不可用，请稍后重试",
                warnings=[str(exc)],
            ),
            "message": "success",
        }

    raw_warnings = result.get("warnings")
    warnings = raw_warnings if isinstance(raw_warnings, list) else []
    source_chunks = result.get("source_chunks")
    return {
        "success": True,
        "data": AiAgentPreviewResponseData(
            reply_text=str(result.get("reply_text") or ""),
            source="llm" if result.get("llm_used") else "direct",
            used_category_keys=category_keys,
            source_chunks=source_chunks if isinstance(source_chunks, list) else [],
            manual_required=bool(result.get("manual_required")),
            error=None,
            llm_used=bool(result.get("llm_used")),
            rag_used=bool(result.get("rag_used")),
            auto_send=False,
            warnings=warnings,
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
