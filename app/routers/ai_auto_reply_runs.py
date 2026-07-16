"""抖音自动回复运行记录查询 API。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import AiAutoReplyRunDetailResponse, AiAutoReplyRunListResponse
from app.services.ai_auto_reply_run_query_service import (
    AiAutoReplyRunQuery,
    get_ai_auto_reply_run_detail,
    list_ai_auto_reply_runs,
)


router = APIRouter(prefix="/ai-auto-reply-runs", tags=["抖音自动回复运行记录"])


def _require_douyin_ai_cs_merchant(context: RequestContext) -> str:
    """校验抖音 AI 客服权限，并返回可信商户 ID。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


@router.get("", response_model=AiAutoReplyRunListResponse)
def list_runs(
    page: int = 1,
    page_size: int = 20,
    account_open_id: str | None = None,
    conversation_short_id: str | None = None,
    customer_open_id: str | None = None,
    agent_id: str | None = None,
    account_name: str | None = None,
    customer_name: str | None = None,
    agent_name: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    keyword: str | None = None,
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户自动回复运行记录列表；query merchant_id 会被忽略。"""
    del merchant_id
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    data = list_ai_auto_reply_runs(
        db,
        AiAutoReplyRunQuery(
            merchant_id=trusted_merchant_id,
            page=page,
            page_size=page_size,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            customer_open_id=customer_open_id,
            agent_id=agent_id,
            account_name=account_name,
            customer_name=customer_name,
            agent_name=agent_name,
            status=status,
            created_from=created_from,
            created_to=created_to,
            keyword=keyword,
        ),
    )
    return {"success": True, "data": data, "message": "success"}


@router.get("/{run_id}", response_model=AiAutoReplyRunDetailResponse)
def get_run_detail(
    run_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户单条自动回复运行记录详情。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    data = get_ai_auto_reply_run_detail(
        db,
        merchant_id=trusted_merchant_id,
        run_id=run_id,
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AI_AUTO_REPLY_RUN_NOT_FOUND", "message": "自动回复运行记录不存在"},
        )
    return {"success": True, "data": data, "message": "success"}
