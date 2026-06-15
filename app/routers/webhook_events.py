"""Raw webhook event read-only API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import WebhookEventDetailResponse, WebhookEventListResponse
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
    db: Session = Depends(get_db),
):
    """List raw webhook events without changing business state."""
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
        ),
    )
    return {"success": True, "data": data, "message": "success"}


@router.get("/{event_id}", response_model=WebhookEventDetailResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    """Get raw webhook event detail."""
    data = get_webhook_event_detail(db, event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="webhook event not found")
    return {"success": True, "data": data, "message": "success"}
