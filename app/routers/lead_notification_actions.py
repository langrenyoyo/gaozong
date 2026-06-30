"""跨平台线索通知动作接口。

该路由只在 9000 创建微信任务，不直接操作微信 UI。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask
from app.schemas import SendToStaffRequest, SendToStaffResponse
from app.services.notification_template import compose_notification_text
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
    merchant_id = _require_merchant_id(context)
    lead = db.query(DouyinLead).filter(
        DouyinLead.id == request.lead_id,
        DouyinLead.merchant_id == merchant_id,
    ).first()
    if not lead:
        raise HTTPException(
            status_code=404,
            detail={"code": "LEAD_NOT_FOUND", "message": "线索不存在"},
        )

    if not lead.assigned_staff_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "LEAD_NOT_ASSIGNED", "message": "线索尚未分配销售"},
        )

    if request.staff_id is not None and request.staff_id != lead.assigned_staff_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "STAFF_MISMATCH", "message": "请先重新分配线索后再通知销售"},
        )

    staff = db.query(SalesStaff).filter(
        SalesStaff.id == lead.assigned_staff_id,
        SalesStaff.merchant_id == merchant_id,
    ).first()
    if not staff:
        raise HTTPException(
            status_code=404,
            detail={"code": "STAFF_NOT_FOUND", "message": "销售不存在"},
        )

    if staff.status != "active":
        raise HTTPException(
            status_code=400,
            detail={"code": "STAFF_NOT_ACTIVE", "message": "销售不是启用状态"},
        )

    if not staff.wechat_nickname or not staff.wechat_nickname.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "STAFF_WECHAT_NICKNAME_MISSING", "message": "销售未设置微信昵称"},
        )

    existing_sent = db.query(LeadNotification).filter(
        LeadNotification.lead_id == lead.id,
        LeadNotification.staff_id == staff.id,
        LeadNotification.send_status == "sent",
    ).order_by(LeadNotification.id.desc()).first()
    if existing_sent:
        logger.info(
            "manual_notify_sales stage=already_sent lead_id=%s staff_id=%s notification_id=%s",
            lead.id,
            staff.id,
            existing_sent.id,
        )
        return _response(
            status="already_sent",
            message="该销售已通知，无需重复发送",
            lead=lead,
            staff=staff,
            task=None,
            notification=existing_sent,
        )

    existing_task = db.query(WechatTask).filter(
        WechatTask.task_type == "notify_sales",
        WechatTask.lead_id == lead.id,
        WechatTask.staff_id == staff.id,
        WechatTask.status.in_(["pending", "running"]),
    ).order_by(WechatTask.id.desc()).first()
    if existing_task:
        notification = _latest_notification(db, lead.id, staff.id)
        if not notification:
            notification = _create_notification(
                db,
                lead_id=lead.id,
                staff_id=staff.id,
                notification_text=existing_task.message or compose_notification_text(lead),
            )
        logger.info(
            "manual_notify_sales stage=existing_pending lead_id=%s staff_id=%s task_id=%s notification_id=%s",
            lead.id,
            staff.id,
            existing_task.id,
            notification.id,
        )
        return _response(
            status="existing_pending",
            message="该销售已有待执行通知任务",
            lead=lead,
            staff=staff,
            task=existing_task,
            notification=notification,
        )

    notification_text = (request.message or "").strip() or compose_notification_text(lead)
    task = create_wechat_task(
        db,
        task_type="notify_sales",
        lead_id=lead.id,
        staff_id=staff.id,
        target_nickname=staff.wechat_nickname,
        message=notification_text,
        mode="single_send",
    )
    notification = _create_notification(
        db,
        lead_id=lead.id,
        staff_id=staff.id,
        notification_text=notification_text,
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
) -> LeadNotification:
    record = LeadNotification(
        lead_id=lead_id,
        staff_id=staff_id,
        notification_text=notification_text,
        send_status="pending",
        send_mode="wechat_task",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
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
