"""外部系统集成路由"""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.douyin_webhook import (
    WebhookSignatureError,
    process_webhook_event,
    verify_signature,
)
from app.schemas import DouyinSyncRequest, DouyinSyncResponse, WebhookResponse
from app.services.douyin_sync_service import preview_sync_leads

logger = logging.getLogger("integrations_router")

router = APIRouter(prefix="/integrations/douyin", tags=["外部系统集成"])


@router.post("/sync-leads", response_model=DouyinSyncResponse)
def sync_leads(
    request: DouyinSyncRequest = DouyinSyncRequest(),
    db: Session = Depends(get_db),
) -> DouyinSyncResponse:
    """从 douyinAPI 拉取线索并预览同步结果

    默认 dry_run=true（只预览，不写库）。
    """
    return preview_sync_leads(db, request)


@router.post("/webhook", response_model=WebhookResponse)
async def douyin_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_auth_timestamp: str | None = Header(None, alias="X-Auth-Timestamp"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> WebhookResponse:
    """接收抖音 GMP 私信 Webhook

    签名校验规则：SHA256(SECRET_KEY + body + "-" + timestamp)
    必须携带 X-Auth-Timestamp 和 Authorization 头，否则 401。
    """
    body = await request.body()

    # 验签（缺少签名头或签名错误均拒绝）
    try:
        verify_signature(body, x_auth_timestamp, authorization)
    except WebhookSignatureError as exc:
        logger.warning(
            "webhook 验签失败: status=%d, message=%s",
            exc.status_code,
            exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # 解析 payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"无效的 JSON payload: {exc}")

    logger.info(
        "webhook 接收成功: event=%s, from=%s",
        payload.get("event"),
        (payload.get("from_user_id") or "")[:8] + "...",
    )

    # 处理事件
    result = process_webhook_event(db, payload)
    db.commit()

    return WebhookResponse(
        code=0,
        msg="success",
        event_id=result["event_id"],
        lead_id=result["lead_id"],
        is_new_lead=result["is_new_lead"],
        is_duplicate=result["is_duplicate"],
        lead_action=result["lead_action"],
    )
