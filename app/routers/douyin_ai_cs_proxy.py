"""抖音AI客服 9100 可信代理接口。"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.services.agent_knowledge_category_service import (
    list_agent_category_keys,
)
from app.services.knowledge_category_service import ensure_category_usable_for_merchant
from app.services.ai_agent_service import get_agent
from app.services.douyin_ai_cs_binding_service import validate_douyin_agent_binding
from app.services.douyin_account_agent_binding_service import (
    list_account_agents_for_merchant_account,
)
from app.services.douyin_conversation_history_service import build_conversation_history
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)
from app.services.ai_reply_decision_log_service import record_ai_reply_decision


router = APIRouter(prefix="/integrations/douyin-ai-cs", tags=["抖音AI客服可信代理"])

logger = logging.getLogger(__name__)


def _trusted_tenant_id(context: RequestContext) -> str:
    return context.source_system or "new_car_project"


def _validate_rag_account_scope(
    *,
    db: Session,
    context: RequestContext,
    account_open_id: str,
) -> None:
    result = list_account_agents_for_merchant_account(
        db=db,
        context=context,
        account_open_id=account_open_id,
    )
    if result.allowed:
        return

    status_code = 404 if result.reason_code == "DOUYIN_ACCOUNT_NOT_FOUND" else 403
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": result.reason_code or "DOUYIN_ACCOUNT_SCOPE_DENIED",
            "message": "抖音企业号不属于当前商户或不可用",
            "audit": result.audit,
        },
    )


def _normalize_and_validate_category_key(
    *,
    db: Session,
    context: RequestContext,
    category_key: str | None,
) -> str:
    try:
        return ensure_category_usable_for_merchant(
            db,
            context=context,
            category_key=category_key,
            default_base=True,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "CATEGORY_KEY_REQUIRED":
            raise HTTPException(
                status_code=400,
                detail={"code": "CATEGORY_KEY_REQUIRED", "message": "知识分类不能为空"},
            ) from exc
        raise HTTPException(
            status_code=400,
            detail={"code": "CATEGORY_KEY_NOT_VISIBLE", "message": "知识分类不存在或不可用"},
        ) from exc

def _build_allowed_category_keys(
    *,
    db: Session,
    context: RequestContext,
    agent_id: str,
) -> list[str]:
    """构造 9000 可信注入的 Agent 可用知识分类，读取失败时保底使用 base。"""
    keys: list[str] = ["base"]
    try:
        keys.extend(list_agent_category_keys(db, context=context, agent_id=agent_id))
    except Exception as exc:
        logger.warning(
            "douyin_ai_cs_allowed_categories_fallback agent_id=%s merchant_id=%s error=%s",
            agent_id,
            context.merchant_id,
            exc,
        )

    result: list[str] = []
    seen: set[str] = set()
    for raw_key in keys:
        key = str(raw_key).strip() if raw_key is not None else ""
        if not key or key in seen:
            continue
        result.append(key)
        seen.add(key)
    return result or ["base"]


def _normalize_risk_flags(raw_flags: Any) -> list[Any]:
    """兼容 9100 返回的非标准 risk_flags，避免代理层兜底时 500。"""
    if raw_flags is None:
        return []
    if isinstance(raw_flags, str):
        return [raw_flags]
    if isinstance(raw_flags, list):
        return raw_flags
    return []


def _trusted_account_open_id_from_binding(
    *,
    binding_audit: dict[str, Any],
    fallback: int | str,
) -> str:
    """从绑定校验结果读取可信企业号 open_id，兼容历史审计字段缺失。"""
    value = (
        binding_audit.get("authorized_account_open_id")
        or binding_audit.get("account_open_id")
        or fallback
    )
    return str(value).strip()


class ReplySuggestionProxyRequest(BaseModel):
    """9000 代理层允许浏览器提交的回复建议参数。"""

    douyin_account_id: int | str
    agent_id: str | None = None
    latest_message: str
    max_history_messages: int = Field(default=20, ge=1, le=100)


class RagDocumentProxyRequest(BaseModel):
    """9000 RAG 文档可信代理允许浏览器提交的字段。"""

    account_open_id: str
    title: str
    content: str
    category_key: str | None = None
    category: str | None = None
    brand: str | None = None
    vehicle_name: str | None = None


class RagTrainProxyRequest(BaseModel):
    """9000 RAG 训练可信代理允许浏览器提交的字段。"""

    account_open_id: str
    category_key: str | None = None
    force_rebuild: bool | None = None


@router.post("/conversations/{conversation_id}/reply-suggestion")
async def create_reply_suggestion_proxy(
    conversation_id: str,
    request: ReplySuggestionProxyRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9000 注入可信商户上下文后调用 9100 生成回复建议。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )

    binding_result = validate_douyin_agent_binding(
        db=db,
        context=context,
        douyin_account_id=request.douyin_account_id,
        agent_id=request.agent_id,
        conversation_id=conversation_id,
    )
    if not binding_result.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": binding_result.reason_code or "DOUYIN_AGENT_BINDING_DENIED",
                "message": "抖音账号或智能体不属于当前商户",
                "audit": binding_result.audit,
            },
        )

    agent = get_agent(db, context, request.agent_id or "")
    if agent is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "AGENT_NOT_FOUND", "message": "智能体不存在或不属于当前商户"},
        )
    if agent.status != "active":
        raise HTTPException(
            status_code=403,
            detail={"code": "AGENT_NOT_ACTIVE", "message": "智能体未启用"},
        )

    allowed_category_keys = _build_allowed_category_keys(
        db=db,
        context=context,
        agent_id=agent.agent_id,
    )
    account_open_id = _trusted_account_open_id_from_binding(
        binding_audit=binding_result.audit,
        fallback=request.douyin_account_id,
    )
    try:
        conversation_history = build_conversation_history(
            db,
            account_open_id=account_open_id,
            conversation_key=conversation_id,
            latest_message=request.latest_message,
            limit=10,
        )
    except Exception as exc:
        logger.warning(
            "douyin_ai_cs_conversation_history_fallback merchant_id=%s account_open_id=%s conversation_id=%s error=%s",
            context.merchant_id,
            account_open_id,
            conversation_id,
            exc,
        )
        conversation_history = []

    payload = {
        "tenant_id": context.source_system,
        "account_id": request.douyin_account_id,
        "douyin_account_id": request.douyin_account_id,
        "merchant_id": context.merchant_id,
        "agent_id": request.agent_id,
        "agent_config": {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "system_prompt": agent.prompt or "",
            "knowledge_base_text": agent.knowledge_base_text or "",
            "status": agent.status,
            "allowed_category_keys": allowed_category_keys,
        },
        "latest_message": request.latest_message,
        "max_history_messages": request.max_history_messages,
        "conversation_history": conversation_history,
    }

    try:
        result = get_xg_douyin_ai_cs_client().suggest_reply(
            context=context,
            conversation_id=conversation_id,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
        ) from exc

    upstream_raw_result = deepcopy(result)
    upstream_requested_auto_send = result.get("auto_send") is True
    result["auto_send"] = False
    if upstream_requested_auto_send:
        risk_flags = _normalize_risk_flags(result.get("risk_flags"))
        if "proxy_forced_auto_send_false" not in risk_flags:
            risk_flags.append("proxy_forced_auto_send_false")
        result["risk_flags"] = risk_flags
    existing_warnings = result.get("warnings")
    warnings = existing_warnings if isinstance(existing_warnings, list) else []
    result["warnings"] = [*warnings, *binding_result.warnings]
    record_ai_reply_decision(
        db,
        context=context,
        conversation_id=conversation_id,
        account_open_id=account_open_id,
        latest_message=request.latest_message,
        agent_id=agent.agent_id,
        agent_name=agent.name,
        allowed_category_keys=allowed_category_keys,
        upstream_raw_result=upstream_raw_result,
        final_result=result,
        upstream_auto_send=upstream_requested_auto_send,
    )
    return result


@router.post("/rag/documents")
def create_rag_document_proxy(
    request: RagDocumentProxyRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9000 注入可信 scope 后代理创建 9100 RAG 文档。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )

    account_open_id = str(request.account_open_id).strip()
    _validate_rag_account_scope(db=db, context=context, account_open_id=account_open_id)
    category_key = _normalize_and_validate_category_key(
        db=db,
        context=context,
        category_key=request.category_key,
    )

    payload: dict[str, Any] = {
        "tenant_id": _trusted_tenant_id(context),
        "merchant_id": context.merchant_id,
        "douyin_account_id": account_open_id,
        "title": request.title,
        "content": request.content,
        "category_key": category_key,
    }
    if request.category is not None:
        payload["category"] = request.category
    if request.brand is not None:
        payload["brand"] = request.brand
    if request.vehicle_name is not None:
        payload["vehicle_name"] = request.vehicle_name

    logger.info(
        "douyin_ai_cs_rag_document_proxy merchant_id=%s account_open_id=%s category_key=%s",
        context.merchant_id,
        account_open_id,
        category_key,
    )

    try:
        result = get_xg_douyin_ai_cs_client().create_rag_document(
            context=context,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
        ) from exc

    return {"success": True, "data": result, "message": "success"}


@router.post("/rag/train")
def train_rag_proxy(
    request: RagTrainProxyRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9000 注入可信 scope 后代理触发 9100 RAG 训练。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )

    account_open_id = str(request.account_open_id).strip()
    _validate_rag_account_scope(db=db, context=context, account_open_id=account_open_id)
    category_key = _normalize_and_validate_category_key(
        db=db,
        context=context,
        category_key=request.category_key,
    )

    payload: dict[str, Any] = {
        "tenant_id": _trusted_tenant_id(context),
        "merchant_id": context.merchant_id,
        "douyin_account_id": account_open_id,
        "category_key": category_key,
    }
    if request.force_rebuild is not None:
        payload["force_rebuild"] = request.force_rebuild

    logger.info(
        "douyin_ai_cs_rag_train_proxy merchant_id=%s account_open_id=%s category_key=%s force_rebuild=%s",
        context.merchant_id,
        account_open_id,
        category_key,
        request.force_rebuild,
    )

    try:
        result = get_xg_douyin_ai_cs_client().train_rag(
            context=context,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
        ) from exc

    return {"success": True, "data": result, "message": "success"}


@router.get("/accounts/{account_open_id}/agents")
def list_account_agents_proxy(
    account_open_id: str,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9000 注入可信商户上下文后返回企业号可选智能体列表。

    取代前端直连 9100 /douyin/accounts/{id}/agents 的 demo 链路：
    智能体来源为当前商户真实 AiAgent 与 douyin_account_agent_bindings，
    merchant_id 强制取自 RequestContext，不接受前端传值，不调用 9100 mock。
    """
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )

    result = list_account_agents_for_merchant_account(
        db=db,
        context=context,
        account_open_id=account_open_id,
    )
    if not result.allowed:
        # 账号不存在统一 404，其余归属/授权问题统一 403，与 douyin_accounts 路由风格一致
        status_code = 404 if result.reason_code == "DOUYIN_ACCOUNT_NOT_FOUND" else 403
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": result.reason_code or "DOUYIN_AGENT_BINDING_DENIED",
                "message": "抖音企业号或智能体不属于当前商户",
                "audit": result.audit,
            },
        )

    logger.info(
        "douyin_ai_cs_agents_proxy account_open_id=%s merchant_id=%s default_agent_id=%s agent_count=%d",
        account_open_id,
        context.merchant_id,
        result.default_agent_id,
        len(result.agents),
    )
    return {
        "success": True,
        "data": {
            "items": [asdict(agent) for agent in result.agents],
            "default_agent_id": result.default_agent_id,
        },
        "message": "success",
    }
