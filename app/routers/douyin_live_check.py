"""Douyin on-site live-check endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import config
from app.schemas import (
    DouyinLiveCheckAuthUrlResponse,
    DouyinLiveCheckObserveResponse,
    DouyinLiveCheckStatusResponse,
)
from app.services.douyin_live_check_service import (
    build_auth_url,
    fetch_auth_url,
    get_live_check_status,
    record_oauth_callback,
    record_webhook_observe,
)

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


@router.post("/webhook-observe", response_model=DouyinLiveCheckObserveResponse)
async def webhook_observe(request: Request) -> DouyinLiveCheckObserveResponse:
    _ensure_enabled()
    try:
        payload: dict[str, Any] = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    data = record_webhook_observe(dict(request.headers), payload)
    return DouyinLiveCheckObserveResponse(data=data)
