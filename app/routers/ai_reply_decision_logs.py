"""AI 回复实发记录查询与有效性标记 API。

Phase 4 起：
- 列表/详情查询源为「AI 实发流水」，商户用户限本商户，超管可跨商户筛选；
- 有效性标记（PATCH）仅允许超管记录权限，且必须存在关联发送流水。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.models import AiReplyDecisionLog, DouyinPrivateMessageSend
from app.schemas import (
    AiReplyDecisionEffectivenessPatch,
    AiReplyDecisionLogDetailResponse,
    AiReplyDecisionLogListResponse,
)
from app.services.ai_reply_decision_log_query_service import (
    AiReplyDecisionLogQuery,
    get_ai_reply_decision_log_detail,
    list_ai_reply_decision_logs,
    mask_ai_reply_sensitive_text,
)
from app.services.autoreply_admin_rollout_service import record_admin_audit


router = APIRouter(prefix="/ai-reply-decision-logs", tags=["AI回复记录"])

ADMIN_AI_REPLY_RECORDS_PERMISSION = "auto_wechat:admin:ai_reply_records"
MERCHANT_DOUYIN_AI_CS_PERMISSION = "auto_wechat:douyin_ai_cs"


def _resolve_read_merchant_scope(
    context: RequestContext,
    requested_merchant_id: str | None,
) -> str | None:
    """返回查询商户范围；None 表示超管查询全部商户。

    超管（持 admin:ai_reply_records）可按 query.merchant_id 筛选，不传则查全部；
    商户用户（持 douyin_ai_cs）只能查自己商户，query.merchant_id 被忽略（防伪造）。
    """
    if context.has_permission(ADMIN_AI_REPLY_RECORDS_PERMISSION):
        return str(requested_merchant_id or "").strip() or None
    if not context.has_permission(MERCHANT_DOUYIN_AI_CS_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少 AI 回复记录查看权限"},
        )
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _require_admin_ai_reply_records(context: RequestContext) -> RequestContext:
    """AI 回复有效性标记仅允许超管记录权限。"""
    if not context.has_permission(ADMIN_AI_REPLY_RECORDS_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "缺少权限 auto_wechat:admin:ai_reply_records",
            },
        )
    return context


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
    send_status: str | None = None,
    is_effective: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    keyword: str | None = None,
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询 AI 回复实发记录列表。

    merchant_id 仅超管可用：超管不传查全部商户，传则按该商户筛选；
    商户用户的 merchant_id 参数被忽略，强制限定为可信商户上下文。
    """
    trusted_merchant_id = _resolve_read_merchant_scope(context, merchant_id)
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
            send_status=send_status,
            is_effective=is_effective,
            date_from=date_from,
            date_to=date_to,
            keyword=keyword,
        ),
    )
    return {"success": True, "data": data, "message": "success"}


@router.get("/{log_id}", response_model=AiReplyDecisionLogDetailResponse)
def get_log_detail(
    log_id: int,
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询单条 AI 回复实发记录详情。"""
    trusted_merchant_id = _resolve_read_merchant_scope(context, merchant_id)
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


@router.patch("/{log_id}/effectiveness", response_model=AiReplyDecisionLogDetailResponse)
def patch_log_effectiveness(
    log_id: int,
    payload: AiReplyDecisionEffectivenessPatch,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """超管人工标记 AI 实发回复是否有效。

    仅允许持有 auto_wechat:admin:ai_reply_records 权限的超管；
    未发送（无关联发送流水）的决策日志不允许标记，返回 404。
    """
    _require_admin_ai_reply_records(context)
    has_is_effective = payload.is_effective is not None
    has_reason = payload.effectiveness_reason is not None
    if not has_is_effective and not has_reason:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NO_FIELDS_TO_UPDATE",
                "message": "至少需要提交 is_effective 或 effectiveness_reason",
            },
        )

    reason = (
        payload.effectiveness_reason.strip()
        if payload.effectiveness_reason is not None
        else None
    )
    if has_reason and not reason:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EFFECTIVENESS_REASON_REQUIRED",
                "message": "有效性原因不能为空",
            },
        )
    if has_is_effective and reason is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EFFECTIVENESS_REASON_REQUIRED",
                "message": "标记有效性必须填写原因",
            },
        )
    if reason is not None and len(reason) > 500:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EFFECTIVENESS_REASON_TOO_LONG",
                "message": "有效性原因不能超过 500 字",
            },
        )
    # 入库与审计统一使用脱敏后的原因，避免手机号/微信号明文落库
    masked_reason = mask_ai_reply_sensitive_text(reason) if reason is not None else None

    # 仅允许标记已实发的记录：必须存在关联发送流水（与查询源口径一致）
    row = (
        db.query(AiReplyDecisionLog)
        .join(
            DouyinPrivateMessageSend,
            DouyinPrivateMessageSend.decision_log_id == AiReplyDecisionLog.id,
        )
        .filter(AiReplyDecisionLog.id == log_id)
        .filter(
            or_(
                DouyinPrivateMessageSend.send_source == "ai_auto",
                DouyinPrivateMessageSend.decision_log_id.isnot(None),
            )
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AI_REPLY_DECISION_LOG_NOT_FOUND",
                "message": "AI 回复记录不存在",
            },
        )

    before = {
        "is_effective": row.is_effective,
        "effectiveness_reason": row.effectiveness_reason,
    }
    if has_is_effective:
        row.is_effective = payload.is_effective
    if has_reason:
        row.effectiveness_reason = masked_reason
    db.flush()
    after = {
        "is_effective": row.is_effective,
        "effectiveness_reason": row.effectiveness_reason,
    }
    record_admin_audit(
        db,
        action="mark_ai_reply_effectiveness",
        merchant_id=row.merchant_id,
        account_open_id=row.account_open_id,
        target_type="ai_reply_decision_log",
        target_id=str(row.id),
        before=before,
        after=after,
        reason=masked_reason,
        operator_id=context.user_id,
        operator_name=context.display_name or context.username,
        commit=False,
    )
    db.commit()

    data = get_ai_reply_decision_log_detail(db, merchant_id=None, log_id=log_id)
    return {"success": True, "data": data, "message": "success"}
