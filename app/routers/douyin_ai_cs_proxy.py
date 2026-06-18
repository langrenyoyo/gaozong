"""抖音AI客服 9100 可信代理接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.services.douyin_ai_cs_binding_service import validate_douyin_agent_binding
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)


router = APIRouter(prefix="/integrations/douyin-ai-cs", tags=["抖音AI客服可信代理"])


class ReplySuggestionProxyRequest(BaseModel):
    """9000 代理层允许浏览器提交的回复建议参数。"""

    douyin_account_id: int | str
    agent_id: str | None = None
    latest_message: str
    max_history_messages: int = Field(default=20, ge=1, le=100)


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

    payload = {
        "tenant_id": context.source_system,
        "account_id": request.douyin_account_id,
        "douyin_account_id": request.douyin_account_id,
        "merchant_id": context.merchant_id,
        "agent_id": request.agent_id,
        "latest_message": request.latest_message,
        "max_history_messages": request.max_history_messages,
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

    result["auto_send"] = False
    existing_warnings = result.get("warnings")
    warnings = existing_warnings if isinstance(existing_warnings, list) else []
    result["warnings"] = [*warnings, *binding_result.warnings]
    return result
