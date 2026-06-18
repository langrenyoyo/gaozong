"""Douyin on-site live-check endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_optional
from app.database import get_db
from app.routers.integrations import _handle_douyin_webhook
from app.schemas import (
    DouyinBindInfoSyncRequest,
    DouyinBindInfoSyncResponse,
    DouyinImageUploadRequest,
    DouyinImageUploadResponse,
    DouyinLiveCheckAccountsResponse,
    DouyinLiveCheckAuthUrlResponse,
    DouyinLiveCheckObserveResponse,
    DouyinLiveCheckStatusResponse,
    DouyinPrivateMessageSendRequest,
    DouyinPrivateMessageSendResponse,
    DouyinResourceDownloadRequest,
    DouyinResourceDownloadResponse,
)
from app.services.douyin_image_upload_service import upload_douyin_image
from app.services.douyin_live_check_service import (
    build_auth_url,
    fetch_auth_url,
    get_live_check_status,
    record_oauth_callback,
    record_webhook_observe,
    sync_bind_info_accounts,
    update_webhook_observe_forward_result,
)
from app.services.douyin_workbench_conversation_service import (
    list_douyin_workbench_accounts_with_event_fallback,
)
from app.services.douyin_private_message_send_service import send_manual_private_message
from app.services.douyin_resource_download_service import download_douyin_resource

logger = logging.getLogger(__name__)
LIVE_CHECK_OBSERVE_PATH = "/integrations/douyin/live-check/webhook-observe"

router = APIRouter(
    prefix="/integrations/douyin/live-check",
    tags=["抖音现场联调"],
)


def _ensure_enabled() -> None:
    if not config.DY_LIVE_CHECK_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Douyin live-check is disabled. Set DY_LIVE_CHECK_ENABLED=true to enable on-site observation.",
        )


@router.get("/auth-url", response_model=DouyinLiveCheckAuthUrlResponse)
def get_auth_url() -> DouyinLiveCheckAuthUrlResponse:
    _ensure_enabled()
    data = fetch_auth_url()
    if not data["configured"]:
        raise HTTPException(
            status_code=400,
            detail=f"Missing Douyin live-check config: {', '.join(data['missing'])}",
        )
    return DouyinLiveCheckAuthUrlResponse(data=data)


@router.get("/oauth-callback", response_model=DouyinLiveCheckObserveResponse)
def oauth_callback(request: Request) -> DouyinLiveCheckObserveResponse:
    _ensure_enabled()
    params = dict(request.query_params)
    return DouyinLiveCheckObserveResponse(data=record_oauth_callback(params))


@router.get("/status", response_model=DouyinLiveCheckStatusResponse)
def status() -> DouyinLiveCheckStatusResponse:
    _ensure_enabled()
    return DouyinLiveCheckStatusResponse(data=get_live_check_status())


@router.get("/accounts", response_model=DouyinLiveCheckAccountsResponse)
def accounts(db: Session = Depends(get_db)) -> DouyinLiveCheckAccountsResponse:
    _ensure_enabled()
    return DouyinLiveCheckAccountsResponse(
        data=list_douyin_workbench_accounts_with_event_fallback(db)
    )


@router.post("/accounts/sync-bind-info", response_model=DouyinBindInfoSyncResponse)
def sync_accounts_bind_info(
    request: DouyinBindInfoSyncRequest = DouyinBindInfoSyncRequest(),
    context: RequestContext | None = Depends(get_request_context_optional),
    db: Session = Depends(get_db),
) -> DouyinBindInfoSyncResponse:
    _ensure_enabled()
    return DouyinBindInfoSyncResponse(
        data=sync_bind_info_accounts(
            db,
            page_num=request.page_num,
            page_size=request.page_size,
            name_or_open_id=request.name_or_open_id,
            context=context,
        )
    )


@router.post("/messages/send", response_model=DouyinPrivateMessageSendResponse)
def send_message(
    request: DouyinPrivateMessageSendRequest,
    db: Session = Depends(get_db),
) -> DouyinPrivateMessageSendResponse:
    _ensure_enabled()
    data = send_manual_private_message(
        db,
        conversation_short_id=request.conversation_short_id,
        customer_open_id=request.customer_open_id,
        content=request.content,
        scene=request.scene,
        manual_confirmed=request.manual_confirmed,
        operator_id=request.operator_id,
    )
    return DouyinPrivateMessageSendResponse(data=data)


@router.post("/resources/download", response_model=DouyinResourceDownloadResponse)
def download_resource(
    request: DouyinResourceDownloadRequest,
    db: Session = Depends(get_db),
) -> DouyinResourceDownloadResponse:
    _ensure_enabled()
    data = download_douyin_resource(
        db,
        conversation_short_id=request.conversation_short_id,
        server_message_id=request.server_message_id,
        open_id=request.open_id,
        media_type=request.media_type,
        url=request.url,
    )
    return DouyinResourceDownloadResponse(data=data)


@router.post("/resources/upload-image", response_model=DouyinImageUploadResponse)
def upload_image(
    request: DouyinImageUploadRequest,
    db: Session = Depends(get_db),
) -> DouyinImageUploadResponse:
    _ensure_enabled()
    data = upload_douyin_image(
        db,
        file_name=request.file_name,
        image_base64=request.image_base64,
        open_id=request.open_id,
    )
    return DouyinImageUploadResponse(data=data)


@router.post("/webhook-observe", response_model=DouyinLiveCheckObserveResponse)
async def webhook_observe(
    request: Request,
    db: Session = Depends(get_db),
) -> DouyinLiveCheckObserveResponse:
    _ensure_enabled()
    body = await request.body()
    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    data = record_webhook_observe(dict(request.headers), payload)
    forward_result = await _maybe_forward_to_formal(request, body, payload, db)
    data.update(forward_result)
    update_webhook_observe_forward_result(forward_result)
    return DouyinLiveCheckObserveResponse(data=data)


def _forward_disabled_result() -> dict[str, Any]:
    return {
        "forward_to_formal_enabled": False,
        "forward_to_formal_success": None,
        "forward_to_formal_event_id": None,
        "forward_to_formal_lead_id": None,
        "forward_to_formal_lead_action": None,
        "forward_to_formal_error": None,
    }


def _forward_error_result(exc: Exception) -> dict[str, Any]:
    return {
        "forward_to_formal_enabled": True,
        "forward_to_formal_success": False,
        "forward_to_formal_event_id": None,
        "forward_to_formal_lead_id": None,
        "forward_to_formal_lead_action": None,
        "forward_to_formal_error": type(exc).__name__,
    }


async def _maybe_forward_to_formal(
    request: Request,
    body: bytes,
    payload: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    if not config.DY_LIVE_CHECK_FORWARD_TO_FORMAL:
        logger.info(
            "live-check webhook observe: source_path=%s, forward_to_formal_enabled=false, event=%s, forward_result=disabled",
            LIVE_CHECK_OBSERVE_PATH,
            payload.get("event"),
        )
        return _forward_disabled_result()

    try:
        formal = await _handle_douyin_webhook(
            body=body,
            x_auth_timestamp=request.headers.get("X-Auth-Timestamp"),
            authorization=request.headers.get("Authorization"),
            db=db,
            source_path=LIVE_CHECK_OBSERVE_PATH,
            skip_signature_verification=True,
        )
    except Exception as exc:
        db.rollback()
        logger.warning(
            "live-check webhook observe: source_path=%s, forward_to_formal_enabled=true, event=%s, forward_result=error, error_type=%s",
            LIVE_CHECK_OBSERVE_PATH,
            payload.get("event"),
            type(exc).__name__,
        )
        return _forward_error_result(exc)

    logger.info(
        "live-check webhook observe: source_path=%s, forward_to_formal_enabled=true, event=%s, forward_result=success, event_id=%s, lead_id=%s, lead_action=%s",
        LIVE_CHECK_OBSERVE_PATH,
        payload.get("event"),
        formal.event_id,
        formal.lead_id,
        formal.lead_action,
    )
    return {
        "forward_to_formal_enabled": True,
        "forward_to_formal_success": True,
        "forward_to_formal_event_id": formal.event_id,
        "forward_to_formal_lead_id": formal.lead_id,
        "forward_to_formal_lead_action": formal.lead_action,
        "forward_to_formal_error": None,
    }
