"""Raw webhook event read-only API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import WebhookEventDetailResponse, WebhookEventListResponse
from app.services import leads_tasks_pg_shadow
from app.services.leads_tasks_shadow_observability import record_shadow_result
from app.services.webhook_event_service import (
    WebhookEventFilters,
    get_webhook_event_detail,
    list_webhook_events,
)


router = APIRouter(prefix="/webhook-events", tags=["原始Webhook事件"])


@router.get("", response_model=WebhookEventListResponse)
def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event: str | None = None,
    lead_action: str | None = None,
    is_duplicate: bool | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    keyword: str | None = None,
    open_id: str | None = None,
    conversation_short_id: str | None = None,
    lead_id: int | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """List raw webhook events without changing business state."""
    require_permission("auto_wechat:leads")(context)
    super_admin = context.is_mock_auth() or context.super_admin
    data = list_webhook_events(
        db,
        WebhookEventFilters(
            page=page,
            page_size=page_size,
            event=event,
            lead_action=lead_action,
            is_duplicate=is_duplicate,
            start_time=start_time,
            end_time=end_time,
            keyword=keyword,
            open_id=open_id,
            conversation_short_id=conversation_short_id,
            lead_id=lead_id,
        ),
        merchant_id=context.merchant_id,
        super_admin=super_admin,
    )
    if leads_tasks_pg_shadow.is_shadow_configured():
        result = leads_tasks_pg_shadow.run_douyin_webhook_events_list_shadow_read(
            sqlite_rows=data.get("items", []),
            merchant_id=context.merchant_id,
            event=event,
            conversation_short_id=conversation_short_id,
            open_id=open_id,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
        record_shadow_result(result)
    return {"success": True, "data": data, "message": "success"}


@router.get("/{event_id}", response_model=WebhookEventDetailResponse)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """Get raw webhook event detail."""
    require_permission("auto_wechat:leads")(context)
    super_admin = context.is_mock_auth() or context.super_admin
    data = get_webhook_event_detail(
        db,
        event_id,
        merchant_id=context.merchant_id,
        super_admin=super_admin,
    )
    if data is None:
        # 他商户事件或归属未知的历史事件统一防枚举 404。
        raise HTTPException(
            status_code=404,
            detail={"code": "WEBHOOK_EVENT_NOT_FOUND", "message": "webhook 事件不存在"},
        )
    return {"success": True, "data": data, "message": "success"}
