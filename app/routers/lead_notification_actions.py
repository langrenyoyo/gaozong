"""跨平台线索通知动作接口。

该路由只在 9000 创建微信任务，不直接操作微信 UI。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permissions
from app.database import get_db
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask
from app.schemas import SendToStaffRequest, SendToStaffResponse
from app.services.forbidden_word_service import replace_forbidden_words
from app.services.lead_wechat_notify_eligibility_service import (
    NOTIFY_SALES_RATE_LIMIT_SECONDS,
    LeadWechatNotifyDecision,
    LeadWechatNotifyReason,
    evaluate_lead_wechat_notify_eligibility,
)
from app.services.notification_template import build_feedback_no, compose_notification_text
from app.services.wechat_task_service import create_wechat_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lead-notifications", tags=["线索通知"])


def _require_merchant_id(context: RequestContext) -> str:
    """返回可信商户 ID；缺失时拒绝访问。"""
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


@router.post("/send-to-staff", response_model=SendToStaffResponse)
def create_notify_sales_task(
    request: SendToStaffRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """为已分配线索创建通知销售的微信任务。"""
    require_permissions(["auto_wechat:leads", "auto_wechat:agent"])(context)
    merchant_id = _require_merchant_id(context)
    decision = evaluate_lead_wechat_notify_eligibility(
        db=db,
        context=context,
        lead_id=request.lead_id,
        staff_id=request.staff_id,
        lock_staff=True,  # Phase 7-FIX1：POST 路径对销售行加锁，防并发绕过限频
    )
    if not decision.allowed:
        # Phase 7-FIX1：限频返回 429 + Retry-After
        if decision.reason == LeadWechatNotifyReason.RATE_LIMITED:
            retry_after = decision.retry_after_seconds or NOTIFY_SALES_RATE_LIMIT_SECONDS
            logger.info(
                "manual_notify_sales stage=rate_limited lead_id=%s staff_id=%s retry_after=%s",
                request.lead_id,
                decision.staff_id,
                retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "detail": {
                        "code": "RATE_LIMITED",
                        "message": decision.message,
                        "retry_after_seconds": retry_after,
                    },
                },
                headers={"Retry-After": str(retry_after)},
            )
        compatible = _compatible_decision_response(db, decision)
        if compatible:
            return compatible
        _raise_decision_error(decision)

    lead = db.query(DouyinLead).filter(
        DouyinLead.id == request.lead_id,
        DouyinLead.merchant_id == merchant_id,
    ).first()
    staff = db.query(SalesStaff).filter(
        SalesStaff.id == lead.assigned_staff_id,
        SalesStaff.merchant_id == merchant_id,
    ).first()

    feedback_no = build_feedback_no(lead.id, staff.id)
    notification_text = (request.message or "").strip() or compose_notification_text(
        lead, feedback_no=feedback_no,
    )

    # Phase 7-FIX2 Task 8 续修：违禁词替换（命中写 ForbiddenWordHitLog）+ task + notification
    # 必须在同一原子事务内。旧实现违禁词 flush 在 try 外，flush 失败无法回滚；
    # commit 成功后的 refresh 也原样放在可回滚块内，refresh 失败时会错误声称"已回滚"。
    from sqlalchemy.exc import SQLAlchemyError

    try:
        # Phase 7：派单文本进入 WechatTask / LeadNotification 前走违禁词替换（命中只替换不拦截）
        replacement = replace_forbidden_words(
            db,
            merchant_id=merchant_id,
            source="wechat_dispatch",
            content=notification_text,
            context={
                "context_type": "lead_notification",
                "context_id": str(lead.id),
                "lead_id": lead.id,
                "staff_id": staff.id,
                "feedback_no": feedback_no,
            },
        )
        notification_text = replacement.final_content
        task = create_wechat_task(
            db,
            task_type="notify_sales",
            lead_id=lead.id,
            staff_id=staff.id,
            target_nickname=staff.wechat_nickname,
            message=notification_text,
            mode="single_send",
            commit=False,
        )
        notification = _create_notification(
            db,
            lead_id=lead.id,
            staff_id=staff.id,
            notification_text=notification_text,
            commit=False,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "DISPATCH_PERSIST_FAILED", "message": "派单持久化失败，已回滚"},
        )

    # Phase 7-FIX2 Task 8：commit 已成功后 refresh 失败不再回滚（数据已持久化），
    # 单独保护并告警，避免对客户端谎报"已回滚"。
    try:
        db.refresh(task)
        db.refresh(notification)
    except SQLAlchemyError as exc:
        logger.warning(
            "manual_notify_sales stage=refresh_failed_after_commit lead_id=%s task_id=%s err=%s",
            lead.id, task.id, type(exc).__name__,
        )
    logger.info(
        "manual_notify_sales stage=created lead_id=%s staff_id=%s task_id=%s notification_id=%s",
        lead.id,
        staff.id,
        task.id,
        notification.id,
    )
    return _response(
        status="created",
        message="已创建微信通知任务，Local Agent 在线后将自动执行",
        lead=lead,
        staff=staff,
        task=task,
        notification=notification,
    )


def _compatible_decision_response(db: Session, decision: LeadWechatNotifyDecision) -> SendToStaffResponse | None:
    if decision.reason == LeadWechatNotifyReason.ALREADY_SENT and decision.existing_notification_id:
        notification = db.get(LeadNotification, decision.existing_notification_id)
        if notification and notification.lead and notification.staff:
            logger.info(
                "manual_notify_sales stage=already_sent lead_id=%s staff_id=%s notification_id=%s",
                notification.lead_id,
                notification.staff_id,
                notification.id,
            )
            return _response(
                status="already_sent",
                message="该销售已通知，无需重复发送",
                lead=notification.lead,
                staff=notification.staff,
                task=None,
                notification=notification,
            )

    if decision.reason == LeadWechatNotifyReason.EXISTING_PENDING_TASK and decision.existing_task_id:
        task = db.get(WechatTask, decision.existing_task_id)
        if task and task.lead and task.staff:
            notification = _latest_notification(db, task.lead_id, task.staff_id)
            if not notification:
                notification = _create_notification(
                    db,
                    lead_id=task.lead_id,
                    staff_id=task.staff_id,
                    notification_text=task.message or compose_notification_text(task.lead),
                )
            logger.info(
                "manual_notify_sales stage=existing_pending lead_id=%s staff_id=%s task_id=%s notification_id=%s",
                task.lead_id,
                task.staff_id,
                task.id,
                notification.id,
            )
            return _response(
                status="existing_pending",
                message="该销售已有待执行通知任务",
                lead=task.lead,
                staff=task.staff,
                task=task,
                notification=notification,
            )

    return None


def _raise_decision_error(decision: LeadWechatNotifyDecision) -> None:
    status_code = 400
    if decision.reason in {LeadWechatNotifyReason.PERMISSION_DENIED, LeadWechatNotifyReason.MERCHANT_REQUIRED}:
        status_code = 403
    elif decision.reason == LeadWechatNotifyReason.LEAD_NOT_FOUND:
        status_code = 404
    raise HTTPException(
        status_code=status_code,
        detail={"code": _route_error_code(decision.reason), "message": decision.message},
    )


def _route_error_code(reason: str) -> str:
    if reason == LeadWechatNotifyReason.MERCHANT_REQUIRED:
        return "MERCHANT_CONTEXT_MISSING"
    if reason == LeadWechatNotifyReason.STAFF_WECHAT_NOT_CONFIGURED:
        return "STAFF_WECHAT_NICKNAME_MISSING"
    return reason


def _latest_notification(db: Session, lead_id: int, staff_id: int) -> LeadNotification | None:
    return db.query(LeadNotification).filter(
        LeadNotification.lead_id == lead_id,
        LeadNotification.staff_id == staff_id,
    ).order_by(LeadNotification.id.desc()).first()


def _create_notification(
    db: Session,
    *,
    lead_id: int,
    staff_id: int,
    notification_text: str,
    commit: bool = True,
) -> LeadNotification:
    """创建通知记录。Phase 7-FIX2：commit=False 支持外部原子事务。"""
    record = LeadNotification(
        lead_id=lead_id,
        staff_id=staff_id,
        notification_text=notification_text,
        send_status="pending",
        send_mode="wechat_task",
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    else:
        db.flush()
    return record


def _response(
    *,
    status: str,
    message: str,
    lead: DouyinLead,
    staff: SalesStaff,
    task: WechatTask | None,
    notification: LeadNotification | None,
) -> SendToStaffResponse:
    return SendToStaffResponse(
        success=True,
        status=status,
        message=message,
        lead_id=lead.id,
        staff_id=staff.id,
        staff_name=staff.name,
        wechat_nickname=staff.wechat_nickname,
        task_id=task.id if task else None,
        notification_id=notification.id if notification else None,
        notification_text=notification.notification_text if notification else None,
        send_status=notification.send_status if notification else None,
    )
