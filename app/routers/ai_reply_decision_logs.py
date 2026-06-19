"""商户侧 AI 回复决策日志查询 API。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import (
    AiReplyDecisionLogDetailResponse,
    AiReplyDecisionLogListResponse,
)
from app.services.ai_reply_decision_log_query_service import (
    AiReplyDecisionLogQuery,
    get_ai_reply_decision_log_detail,
    list_ai_reply_decision_logs,
)


router = APIRouter(prefix="/ai-reply-decision-logs", tags=["AI回复记录"])


def _require_douyin_ai_cs_merchant(context: RequestContext) -> str:
    """校验抖音 AI 客服权限，并返回可信商户 ID。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


@router.get("", response_model=AiReplyDecisionLogListResponse)
def list_logs(
    page: int = 1,
    page_size: int = 20,
    account_open_id: str | None = None,
    conversation_id: str | None = None,
    agent_id: str | None = None,
    manual_required: bool | None = None,
    intent: str | None = None,
    lead_level: str | None = None,
    risk_flag: str | None = None,
    rag_used: bool | None = None,
    llm_used: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    keyword: str | None = None,
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户 AI 回复决策日志列表。

    merchant_id 只取 RequestContext，query 中同名参数会被忽略。
    """
    del merchant_id
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    data = list_ai_reply_decision_logs(
        db,
        AiReplyDecisionLogQuery(
            merchant_id=trusted_merchant_id,
            page=page,
            page_size=page_size,
            account_open_id=account_open_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            manual_required=manual_required,
            intent=intent,
            lead_level=lead_level,
            risk_flag=risk_flag,
            rag_used=rag_used,
            llm_used=llm_used,
            date_from=date_from,
            date_to=date_to,
            keyword=keyword,
        ),
    )
    return {"success": True, "data": data, "message": "success"}


@router.get("/{log_id}", response_model=AiReplyDecisionLogDetailResponse)
def get_log_detail(
    log_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户单条 AI 回复决策日志详情。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    data = get_ai_reply_decision_log_detail(
        db,
        merchant_id=trusted_merchant_id,
        log_id=log_id,
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AI_REPLY_DECISION_LOG_NOT_FOUND", "message": "AI 回复记录不存在"},
        )
    return {"success": True, "data": data, "message": "success"}
