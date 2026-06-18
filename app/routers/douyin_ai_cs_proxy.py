"""抖音AI客服 9100 可信代理接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
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


def validate_douyin_agent_binding(
    *,
    context: RequestContext,
    douyin_account_id: int | str,
    agent_id: str | None,
) -> bool:
    """校验商户、抖音账号和智能体绑定关系。

    P0 阶段先保留集中占位，后续接真实绑定表或 9100 账号查询时只替换这里。
    """
    if context.super_admin:
        return True
    return bool(context.merchant_id and douyin_account_id)


@router.post("/conversations/{conversation_id}/reply-suggestion")
async def create_reply_suggestion_proxy(
    conversation_id: str,
    request: ReplySuggestionProxyRequest,
    context: RequestContext = Depends(get_request_context_required),
) -> dict[str, Any]:
    """由 9000 注入可信商户上下文后调用 9100 生成回复建议。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    if not validate_douyin_agent_binding(
        context=context,
        douyin_account_id=request.douyin_account_id,
        agent_id=request.agent_id,
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "DOUYIN_AGENT_BINDING_DENIED", "message": "抖音账号或智能体不属于当前商户"},
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
    return result
