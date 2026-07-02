"""跨平台线索通知记录只读接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.models import DouyinLead, LeadNotification, SalesStaff
from app.schemas import NotificationRecordOut, NotificationRecordsResponse


router = APIRouter(prefix="/lead-notifications", tags=["线索通知"])


def _require_merchant_id(context: RequestContext) -> str:
    """返回可信商户 ID；缺失时拒绝访问。"""
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _ensure_lead_visible(db: Session, lead_id: int, merchant_id: str) -> None:
    lead = db.query(DouyinLead.id).filter(
        DouyinLead.id == lead_id,
        DouyinLead.merchant_id == merchant_id,
    ).first()
    if not lead:
        raise HTTPException(
            status_code=404,
            detail={"code": "LEAD_NOT_FOUND", "message": "线索不存在"},
        )


@router.get("/records", response_model=NotificationRecordsResponse)
def list_notification_records(
    lead_id: int | None = Query(None, description="按线索 ID 过滤"),
    staff_id: int | None = Query(None, description="按销售 ID 过滤"),
    send_status: str | None = Query(None, description="按发送状态过滤"),
    limit: int = Query(20, ge=1, description="返回条数上限，最大 100"),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户线索下的通知记录列表。"""
    require_permission("auto_wechat:leads")(context)
    merchant_id = _require_merchant_id(context)
    limit = min(limit, 100)

    if lead_id is not None:
        _ensure_lead_visible(db, lead_id, merchant_id)

    query = (
        db.query(LeadNotification, DouyinLead, SalesStaff)
        .join(DouyinLead, DouyinLead.id == LeadNotification.lead_id)
        .outerjoin(SalesStaff, SalesStaff.id == LeadNotification.staff_id)
        .filter(DouyinLead.merchant_id == merchant_id)
    )

    if lead_id is not None:
        query = query.filter(LeadNotification.lead_id == lead_id)
    if staff_id is not None:
        query = query.filter(LeadNotification.staff_id == staff_id)
    if send_status:
        query = query.filter(LeadNotification.send_status == send_status)

    total = query.count()
    rows = query.order_by(LeadNotification.id.desc()).limit(limit).all()

    records = [
        NotificationRecordOut(
            id=notification.id,
            lead_id=notification.lead_id,
            staff_id=notification.staff_id,
            check_id=notification.check_id,
            notification_text=notification.notification_text,
            send_status=notification.send_status,
            send_mode=notification.send_mode,
            chat_title=notification.chat_title,
            error_message=notification.error_message,
            sent_at=notification.sent_at.isoformat() if notification.sent_at else None,
            created_at=notification.created_at.isoformat() if notification.created_at else None,
            customer_name=lead.customer_name if lead else None,
            staff_name=staff.name if staff else None,
            staff_wechat_nickname=staff.wechat_nickname if staff else None,
        )
        for notification, lead, staff in rows
    ]

    return NotificationRecordsResponse(total=total, records=records)
