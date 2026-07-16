"""外部系统集成路由"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.integrations.douyin_webhook import (
    WebhookSignatureError,
    process_webhook_event,
    verify_signature,
)
from app.schemas import DouyinSyncRequest, DouyinSyncResponse, WebhookResponse
from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run
from app.services.douyin_sync_service import preview_sync_leads
from app.services.douyin_workbench_conversation_service import (
    get_conversation_detail,
    get_conversation_profile,
    list_account_conversations,
    list_conversation_messages,
    mark_conversation_read,
)
from packages.clients.leads_client import LeadsClient, LeadsClientError

logger = logging.getLogger("integrations_router")

router = APIRouter(prefix="/integrations/douyin", tags=["外部系统集成"])

# 兼容旧路径 /webhook/douyin（GMP 已配置的回调地址，保持不变）
legacy_webhook_router = APIRouter(prefix="/webhook", tags=["抖音Webhook兼容路径"])

class DouyinConversationMarkReadRequest(BaseModel):
    account_open_id: str = Field(..., min_length=1)
    conversation_key: str = Field(..., min_length=1)
    conversation_short_id: str | None = None
    customer_open_id: str | None = None


def _merchant_id_for_douyin_cs(context: RequestContext) -> str:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


_WEBHOOK_RESULT_FIELDS = {
    "event_id",
    "lead_id",
    "is_new_lead",
    "is_duplicate",
    "lead_action",
}


def _normalize_webhook_result(result: dict) -> dict:
    """归一化 webhook 处理结果，保证可映射到 WebhookResponse。"""
    missing = [field for field in _WEBHOOK_RESULT_FIELDS if field not in result]
    if missing:
        raise LeadsClientError("leads_invalid_response", f"internal webhook 响应缺少字段: {','.join(sorted(missing))}")
    return {
        "code": int(result.get("code", 0) or 0),
        "msg": str(result.get("msg") or "success"),
        "event_id": result.get("event_id"),
        "lead_id": result.get("lead_id"),
        "is_new_lead": bool(result.get("is_new_lead")),
        "is_duplicate": bool(result.get("is_duplicate")),
        "lead_action": str(result.get("lead_action") or "not_lead_event"),
    }


def _process_webhook_locally(db: Session, payload: dict) -> dict:
    """使用 9000 本地旧逻辑处理 webhook。"""
    result = process_webhook_event(db, payload)
    db.commit()
    return _normalize_webhook_result(result)


def _process_webhook_with_internal(
    db: Session,
    payload: dict,
    *,
    source_path: str,
) -> dict:
    """按配置调用 9202 internal webhook，失败时可回退本地旧逻辑。"""
    try:
        result = LeadsClient.from_env().create_internal_webhook_event(
            payload=payload,
            source_path=source_path,
            signature_verified=True,
            received_at=datetime.now().isoformat(),
            gateway_app_env=config.APP_ENV,
        )
        normalized = _normalize_webhook_result(result)
        logger.info(
            "leads_internal_webhook_forward stage=leads_internal_webhook_forward "
            "source_path=%s event=%s event_id=%s lead_id=%s lead_action=%s is_duplicate=%s",
            source_path,
            payload.get("event"),
            normalized.get("event_id"),
            normalized.get("lead_id"),
            normalized.get("lead_action"),
            normalized.get("is_duplicate"),
        )
        return normalized
    except LeadsClientError as exc:
        if config.LEADS_WEBHOOK_FALLBACK_LOCAL:
            logger.warning(
                "leads_internal_webhook_fallback stage=leads_internal_webhook_fallback "
                "failure_stage=%s source_path=%s event=%s error=%s",
                exc.code,
                source_path,
                payload.get("event"),
                exc.message,
            )
            return _process_webhook_locally(db, payload)
        logger.error(
            "leads_internal_webhook_failed stage=leads_internal_webhook_failed "
            "failure_stage=%s source_path=%s event=%s error=%s",
            exc.code,
            source_path,
            payload.get("event"),
            exc.message,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LEADS_INTERNAL_WEBHOOK_UNAVAILABLE",
                "message": "线索 internal webhook 服务不可用",
                "failure_stage": exc.code,
            },
        ) from exc


def _extract_auto_reply_account_open_id(payload: dict) -> str | None:
    event = payload.get("event")
    if event in {"im_receive_msg", "im_enter_direct_msg"}:
        return payload.get("to_user_id")
    if event == "im_send_msg":
        return payload.get("from_user_id")
    return payload.get("to_user_id")


def maybe_schedule_ai_auto_reply(
    *,
    background_tasks: BackgroundTasks | None,
    event_id: int | None,
    payload: dict,
    is_duplicate: bool,
    source_path: str,
) -> None:
    """按 webhook 事件结果统一调度自动回复任务。

    调度阶段只判断事件是否适合作为触发源；账号授权、Agent 绑定、
    自动回复配置和真实发送门禁都交给 run_ai_auto_reply_job 记录 run 与 gate。
    """
    event = payload.get("event")
    account_open_id = _extract_auto_reply_account_open_id(payload)
    log_extra = {
        "event_id": event_id,
        "event": event,
        "source_path": source_path,
        "account_open_id": account_open_id,
    }
    if background_tasks is None:
        logger.info(
            "ai_auto_reply_schedule_skipped reason=background_tasks_missing "
            "event_id=%s event=%s source_path=%s account_open_id=%s",
            log_extra["event_id"],
            log_extra["event"],
            log_extra["source_path"],
            log_extra["account_open_id"],
        )
        return
    if event_id is None:
        logger.info(
            "ai_auto_reply_schedule_skipped reason=event_id_missing "
            "event_id=%s event=%s source_path=%s account_open_id=%s",
            log_extra["event_id"],
            log_extra["event"],
            log_extra["source_path"],
            log_extra["account_open_id"],
        )
        return
    if is_duplicate:
        logger.info(
            "ai_auto_reply_schedule_skipped reason=duplicate_event "
            "event_id=%s event=%s source_path=%s account_open_id=%s",
            log_extra["event_id"],
            log_extra["event"],
            log_extra["source_path"],
            log_extra["account_open_id"],
        )
        return
    if event not in {"im_receive_msg", "im_enter_direct_msg"}:
        reason = "send_message_event" if event == "im_send_msg" else "unsupported_event"
        logger.info(
            "ai_auto_reply_schedule_skipped reason=%s "
            "event_id=%s event=%s source_path=%s account_open_id=%s",
            reason,
            log_extra["event_id"],
            log_extra["event"],
            log_extra["source_path"],
            log_extra["account_open_id"],
        )
        return

    background_tasks.add_task(run_ai_auto_reply_dry_run, event_id)
    logger.info(
        "ai_auto_reply_schedule_added event_id=%s event=%s source_path=%s account_open_id=%s",
        log_extra["event_id"],
        log_extra["event"],
        log_extra["source_path"],
        log_extra["account_open_id"],
    )


async def _handle_douyin_webhook(
    body: bytes,
    x_auth_timestamp: str | None,
    authorization: str | None,
    db: Session,
    source_path: str,
    background_tasks: BackgroundTasks | None = None,
    skip_signature_verification: bool = False,
) -> WebhookResponse:
    """抖音 GMP Webhook 共享处理逻辑

    被 /integrations/douyin/webhook 和 /webhook/douyin 两个入口复用，
    确保验签/解析、幂等、线索写入行为完全一致。

    鉴权开关：
    - development + DOUYIN_WEBHOOK_AUTH_REQUIRED=false：允许本地开发 / 联调免验签
    - production：强制 X-Auth-Timestamp + Authorization 签名校验

    Args:
        body: 原始请求体字节流（用于验签）
        x_auth_timestamp: X-Auth-Timestamp 请求头
        authorization: Authorization 请求头（签名值）
        db: 数据库会话
        source_path: 入口路径，用于日志区分（不参与业务逻辑）
    """
    auth_required = config.is_douyin_webhook_auth_required() and not skip_signature_verification
    if auth_required:
        try:
            verify_signature(body, x_auth_timestamp, authorization)
        except WebhookSignatureError as exc:
            logger.warning(
                "webhook 验签失败: source_path=%s, app_env=%s, webhook_auth_required=true, status=%d, message=%s",
                source_path,
                config.APP_ENV,
                exc.status_code,
                exc.message,
            )
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
    else:
        logger.info(
            "webhook 鉴权已关闭: source_path=%s, app_env=%s, webhook_auth_required=false",
            source_path,
            config.APP_ENV,
        )

    # 解析 payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "webhook payload 解析失败: source_path=%s, webhook_auth_required=%s, %s",
            source_path,
            auth_required,
            exc,
        )
        raise HTTPException(status_code=400, detail=f"无效的 JSON payload: {exc}")

    logger.info(
        "webhook 接收成功: source_path=%s, webhook_auth_required=%s, event=%s, from=%s",
        source_path,
        auth_required,
        payload.get("event"),
        (payload.get("from_user_id") or "")[:8] + "...",
    )

    # 处理事件（幂等、解析、线索写入）
    if config.LEADS_WEBHOOK_INTERNAL_ENABLED:
        result = _process_webhook_with_internal(db, payload, source_path=source_path)
    else:
        result = _process_webhook_locally(db, payload)
    maybe_schedule_ai_auto_reply(
        background_tasks=background_tasks,
        event_id=result.get("event_id"),
        payload=payload,
        is_duplicate=result.get("is_duplicate") is True,
        source_path=source_path,
    )

    return WebhookResponse(
        code=result["code"],
        msg=result["msg"],
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
    context: RequestContext = Depends(get_request_context_required),
) -> DouyinSyncResponse:
    """从 douyinAPI 拉取线索并预览同步结果

    默认 dry_run=true（只预览，不写库）。

    Phase 7-FIX2：auto_notify=true 已停用，旧链路直接调用微信 UI 自动化绕过所有安全 gate。
    """
    require_permission("auto_wechat:leads")(context)

    # Phase 7-FIX2：禁止旧 auto_notify 链路
    if request.auto_notify:
        raise HTTPException(400, detail={
            "code": "LEGACY_AUTO_NOTIFY_DISABLED",
            "message": "旧 auto_notify 链路已停用。请通过微信任务队列受控链路发送。",
        })

    return preview_sync_leads(db, request)


@router.get("/accounts/{account_id}/conversations")
def get_douyin_account_conversations(
    account_id: str,
    account_open_id: str | None = None,
    event_limit: int | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Aggregate real private-message webhook events into workbench conversations."""
    _merchant_id_for_douyin_cs(context)
    resolved_account_open_id = account_open_id or account_id
    return list_account_conversations(
        db,
        account_open_id=resolved_account_open_id,
        event_limit=event_limit,
    )


@router.get("/conversation-detail")
def get_douyin_conversation_detail(
    conversation_key: str,
    account_open_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """一次返回同一会话的消息和客户画像。"""
    _merchant_id_for_douyin_cs(context)
    return get_conversation_detail(
        db,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
    )


@router.get("/conversations/{conversation_key}/messages")
def get_douyin_conversation_messages(
    conversation_key: str,
    account_open_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return real private-message webhook events for one workbench conversation."""
    _merchant_id_for_douyin_cs(context)
    return list_conversation_messages(
        db,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
    )


def _get_douyin_conversation_profile_response(
    account_id: str,
    conversation_key: str,
    account_open_id: str | None = None,
    db: Session | None = None,
) -> dict:
    """Return a read-only customer profile aggregated from 9000 local data."""
    if db is None:
        raise HTTPException(status_code=500, detail="db session is required")
    resolved_account_open_id = account_open_id or account_id
    data = get_conversation_profile(
        db,
        account_open_id=resolved_account_open_id,
        conversation_key=conversation_key,
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DOUYIN_CONVERSATION_PROFILE_NOT_FOUND",
                "message": "抖音会话客户画像不存在",
            },
        )
    return {"success": True, "data": data, "message": "success"}


@router.get("/accounts/{account_id}/conversation-profile")
def get_douyin_conversation_profile_by_query(
    account_id: str,
    conversation_id: str,
    account_open_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return customer profile without putting conversation_id in the path."""
    _merchant_id_for_douyin_cs(context)
    return _get_douyin_conversation_profile_response(
        account_id=account_id,
        conversation_key=conversation_id,
        account_open_id=account_open_id,
        db=db,
    )


@router.get("/accounts/{account_id}/conversations/{conversation_key}/profile")
def get_douyin_conversation_profile(
    account_id: str,
    conversation_key: str,
    account_open_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return a read-only customer profile aggregated from 9000 local data."""
    _merchant_id_for_douyin_cs(context)
    return _get_douyin_conversation_profile_response(
        account_id=account_id,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
        db=db,
    )


@router.get("/conversation-messages")
def get_douyin_conversation_messages_by_query(
    conversation_key: str,
    account_open_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return real private-message events without putting conversation_key in the path."""
    _merchant_id_for_douyin_cs(context)
    return list_conversation_messages(
        db,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
    )


@router.post("/conversations/mark-read")
def post_douyin_conversation_mark_read(
    request: DouyinConversationMarkReadRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    merchant_id = _merchant_id_for_douyin_cs(context)
    try:
        row = mark_conversation_read(
            db,
            merchant_id=merchant_id,
            account_open_id=request.account_open_id,
            conversation_key=request.conversation_key,
            conversation_short_id=request.conversation_short_id,
            customer_open_id=request.customer_open_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOUYIN_ACCOUNT_NOT_FOUND", "message": "抖音企业号不存在"},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED", "message": "抖音企业号不属于当前商户"},
        ) from exc
    return {
        "success": True,
        "data": {
            "account_open_id": row.account_open_id,
            "conversation_key": row.conversation_key,
            "conversation_short_id": row.conversation_short_id,
            "customer_open_id": row.customer_open_id,
            "last_read_at": row.last_read_at,
            "last_read_event_id": row.last_read_event_id,
        },
        "message": "success",
    }


@router.post("/webhook", response_model=WebhookResponse)
async def douyin_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_auth_timestamp: str | None = Header(None, alias="X-Auth-Timestamp"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> WebhookResponse:
    """接收抖音 GMP 私信 Webhook（主路径）

    鉴权由 DOUYIN_WEBHOOK_AUTH_REQUIRED 控制：
    - false（默认）：不鉴权，GMP 推送直接处理
    - true：要求 X-Auth-Timestamp + Authorization 签名
    """
    body = await request.body()
    return await _handle_douyin_webhook(
        body, x_auth_timestamp, authorization, db,
        source_path="/integrations/douyin/webhook",
        background_tasks=background_tasks,
    )


@legacy_webhook_router.post("/douyin", response_model=WebhookResponse)
async def douyin_webhook_legacy(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_auth_timestamp: str | None = Header(None, alias="X-Auth-Timestamp"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> WebhookResponse:
    """接收抖音 GMP 私信 Webhook（兼容旧路径）

    GMP 已配置的回调地址 https://callback.misanduo.com/webhook/douyin 保持不变，
    宝塔整站反代到 9000 后由此路径处理。与 /integrations/douyin/webhook 行为完全一致。
    鉴权由 DOUYIN_WEBHOOK_AUTH_REQUIRED 控制。
    """
    body = await request.body()
    return await _handle_douyin_webhook(
        body, x_auth_timestamp, authorization, db,
        source_path="/webhook/douyin",
        background_tasks=background_tasks,
    )
