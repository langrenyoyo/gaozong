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


@router.post("/{run_id}/retry")
def retry_run(
    run_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """人工重试失败的自动回复运行记录。

    只允许可信当前商户、明确未发送且失败阶段在白名单内的 failed run；
    条件更新到 retry_wait，不在请求内发送。
    """
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    from app.services.ai_auto_reply_outbox_service import manual_retry_run
    try:
        run = manual_retry_run(db, run_id=run_id, merchant_id=trusted_merchant_id)
    except ValueError as exc:
        reason = str(exc)
        if reason.startswith("run_not_found"):
            raise HTTPException(404, detail={"code": "AI_AUTO_REPLY_RUN_NOT_FOUND", "message": "运行记录不存在"})
        if "already_sent" in reason:
            raise HTTPException(409, detail={"code": "AI_AUTO_REPLY_RUN_ALREADY_SENT", "message": "该运行记录已发送，不可重试"})
        if "failure_stage_not_whitelisted" in reason:
            raise HTTPException(403, detail={"code": "AI_AUTO_REPLY_RUN_RETRY_NOT_ALLOWED", "message": "该失败阶段不在人工重试白名单内"})
        raise HTTPException(400, detail={"code": "AI_AUTO_REPLY_RUN_RETRY_INVALID", "message": reason})
    except PermissionError:
        raise HTTPException(403, detail={"code": "PERMISSION_DENIED", "message": "无权操作他商户运行记录"})
    return {
        "success": True,
        "data": {
            "run_id": run.id,
            "status": run.status,
            "next_attempt_at": run.next_attempt_at.isoformat() if run.next_attempt_at else None,
        },
        "message": "已加入重试队列",
    }


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
