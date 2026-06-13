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

# 兼容旧路径 /webhook/douyin（GMP 已配置的回调地址，保持不变）
legacy_webhook_router = APIRouter(prefix="/webhook", tags=["抖音Webhook兼容路径"])


async def _handle_douyin_webhook(
    body: bytes,
    x_auth_timestamp: str | None,
    authorization: str | None,
    db: Session,
    source_path: str,
) -> WebhookResponse:
    """抖音 GMP Webhook 共享处理逻辑

    被 /integrations/douyin/webhook 和 /webhook/douyin 两个入口复用，
    确保验签、解析、幂等、线索写入行为完全一致。

    Args:
        body: 原始请求体字节流（用于验签）
        x_auth_timestamp: X-Auth-Timestamp 请求头
        authorization: Authorization 请求头（签名值）
        db: 数据库会话
        source_path: 入口路径，用于日志区分（不参与业务逻辑）
    """
    # 验签（缺少签名头或签名错误均拒绝）
    try:
        verify_signature(body, x_auth_timestamp, authorization)
    except WebhookSignatureError as exc:
        logger.warning(
            "webhook 验签失败: source_path=%s, status=%d, message=%s",
            source_path,
            exc.status_code,
            exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # 解析 payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "webhook payload 解析失败: source_path=%s, %s",
            source_path,
            exc,
        )
        raise HTTPException(status_code=400, detail=f"无效的 JSON payload: {exc}")

    logger.info(
        "webhook 接收成功: source_path=%s, event=%s, from=%s",
        source_path,
        payload.get("event"),
        (payload.get("from_user_id") or "")[:8] + "...",
    )

    # 处理事件（幂等、解析、线索写入）
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
    """接收抖音 GMP 私信 Webhook（主路径）

    签名校验规则：SHA256(SECRET_KEY + body + "-" + timestamp)
    必须携带 X-Auth-Timestamp 和 Authorization 头，否则 401。
    """
    body = await request.body()
    return await _handle_douyin_webhook(
        body, x_auth_timestamp, authorization, db,
        source_path="/integrations/douyin/webhook",
    )


@legacy_webhook_router.post("/douyin", response_model=WebhookResponse)
async def douyin_webhook_legacy(
    request: Request,
    db: Session = Depends(get_db),
    x_auth_timestamp: str | None = Header(None, alias="X-Auth-Timestamp"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> WebhookResponse:
    """接收抖音 GMP 私信 Webhook（兼容旧路径）

    GMP 已配置的回调地址 https://callback.misanduo.com/webhook/douyin 保持不变，
    宝塔整站反代到 9000 后由此路径处理。与 /integrations/douyin/webhook 行为完全一致。
    """
    body = await request.body()
    return await _handle_douyin_webhook(
        body, x_auth_timestamp, authorization, db,
        source_path="/webhook/douyin",
    )
