"""外部系统集成路由"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import SessionLocal, get_db
from app.integrations.douyin_webhook import (
    WebhookSignatureError,
    process_webhook_event,
    verify_signature,
)
from app.models import DouyinMessageResourceDownload, DouyinWebhookEvent
from app.schemas import DouyinSyncRequest, DouyinSyncResponse, WebhookResponse
from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run
from app.services.douyin_resource_download_service import (
    decode_msg_content,
    download_douyin_resource,
)
from app.services.douyin_sync_service import preview_sync_leads
from app.services.douyin_workbench_conversation_service import (
    AccountAccessError,
    AccountMerchantDeniedError,
    ConversationNotFoundError,
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
    last_seen_event_id: int = Field(..., ge=1)
    conversation_short_id: str | None = None
    customer_open_id: str | None = None


def _wake_outbox_scheduler() -> None:
    """低延迟唤醒：立即执行一轮 outbox 处理，不等待 60 秒周期。

    与 scheduler 共用 outbox service 的 cycle 单飞锁（run_outbox_cycle 内部非阻塞获取），
    防止高频 webhook 形成无界并行完整扫描。
    """
    try:
        from app.services.ai_auto_reply_outbox_service import run_outbox_cycle
        run_outbox_cycle()
    except Exception as exc:
        logger.warning("ai_auto_reply_wake_failed error_type=%s", type(exc).__name__)


def _merchant_id_for_douyin_cs(context: RequestContext) -> str:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _workbench_merchant_scope(context: RequestContext) -> str | None:
    """工作台读取的账号归属校验上下文。

    普通商户返回可信 merchant_id，service 层据此校验账号归属与 bind_status==1；
    mock 开发态 / super_admin 返回 None 跳过校验（跨商户只读，保持 dev 兼容）。
    """
    merchant_id = _merchant_id_for_douyin_cs(context)
    if context.is_mock_auth() or context.super_admin:
        return None
    return merchant_id


def _validate_message_cursor_pair(after_event_id: int | None, before_event_id: int | None) -> None:
    if after_event_id is not None and before_event_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"code": "DOUYIN_MESSAGE_CURSOR_CONFLICT", "message": "after_event_id 和 before_event_id 不能同时传入"},
        )


def _message_cursor_options(
    after_event_id: int | None,
    before_event_id: int | None,
    limit: int | None,
) -> dict[str, int]:
    return {
        key: value
        for key, value in {
            "after_event_id": after_event_id,
            "before_event_id": before_event_id,
            "limit": limit,
        }.items()
        if value is not None
    }


def _account_access_http_exception(exc: Exception) -> HTTPException:
    """把账号归属校验异常映射为防枚举的 403/404。"""
    if isinstance(exc, AccountMerchantDeniedError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED",
                "message": "抖音企业号不属于当前商户",
            },
        )
    return HTTPException(
        status_code=404,
        detail={"code": "DOUYIN_ACCOUNT_NOT_FOUND", "message": "抖音企业号不存在"},
    )


def _conversation_not_found_http_exception() -> HTTPException:
    """会话不属于当前账号/商户或不存在，统一防枚举 404。"""
    return HTTPException(
        status_code=404,
        detail={"code": "DOUYIN_CONVERSATION_NOT_FOUND", "message": "抖音会话不存在"},
    )


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


def _try_decode_masked_text(payload: dict, content: dict) -> str | None:
    """对抖音平台掩码私信调 /decode_msg_content 取明文。

    仅 im_receive_msg（客户入站）方向触发：from_user_id=客户(guest_uid)、to_user_id=企业号(open_id)。
    解码失败（接口异常/业务错误/空内容）返回 None，调用方保留原掩码文本不阻断 webhook。
    """
    # 仅对客户入站消息解码；im_send_msg（企业号发出）方向无掩码需求
    if str(payload.get("event") or "") != "im_receive_msg":
        return None
    open_id = str(payload.get("to_user_id") or "").strip()      # 企业号
    guest_uid = str(payload.get("from_user_id") or "").strip()  # 客户
    conversation_id = str(content.get("conversation_short_id") or "").strip()
    msg_id = str(content.get("server_message_id") or "").strip()
    try:
        return decode_msg_content(
            main_account_id=config.DY_MAIN_ACCOUNT_ID,
            open_id=open_id,
            guest_uid=guest_uid,
            conversation_id=conversation_id,
            msg_id=msg_id,
        )
    except Exception as exc:  # noqa: BLE001 —— decode 任何异常都不阻断 webhook
        logger.warning(
            "webhook_decode_unexpected_error event=%s msg_id=%s error=%s",
            payload.get("event"), msg_id, type(exc).__name__,
        )
        return None


def _process_webhook_locally(db: Session, payload: dict) -> dict:
    """使用 9000 本地逻辑处理 webhook（原子占位 → 胜出者副作用）。"""
    try:
        result = process_webhook_event(db, payload)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception(
            "webhook_transaction stage=local_process failure_stage=transaction_failed error_type=%s",
            type(exc).__name__,
        )
        raise
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

    # BackgroundTasks 仅唤醒 outbox claim 流程，不直接执行旧 run_ai_auto_reply_job。
    # 受总开关控制；关闭时不处理任务（由周期调度器在启用时接管）。
    from app import config as _config
    if _config.AI_AUTO_REPLY_OUTBOX_ENABLED:
        background_tasks.add_task(_wake_outbox_scheduler)
    logger.info(
        "ai_auto_reply_enqueued_persistent event_id=%s event=%s source_path=%s account_open_id=%s",
        log_extra["event_id"],
        log_extra["event"],
        log_extra["source_path"],
        log_extra["account_open_id"],
    )


# webhook 自动触发素材下载的 message_type → media_type 映射（任务 5.0）
# emoji 按图片格式回调，映射为 image；image/video 原样
_RESOURCE_MESSAGE_TYPES = {"image": "image", "video": "video", "emoji": "image"}


def maybe_schedule_resource_download(
    *,
    background_tasks: BackgroundTasks | None,
    event_id: int | None,
    payload: dict,
    is_duplicate: bool,
) -> None:
    """webhook 收到 im_receive_msg 且 message_type ∈ {image, video, emoji} 时，
    异步调度素材下载（复用 download_douyin_resource）。失败不阻断 webhook。

    BackgroundTask 在 webhook 响应后执行，事件已落库，download_douyin_resource
    可从持久化事件解析 open_id/url/商户归属。merchant_id 从事件固化值取（webhook
    入库时已解析可信商户）。internal 模式事件在 9202 时本地查不到 → 优雅跳过。
    """
    if payload.get("event") != "im_receive_msg":
        return
    if background_tasks is None or event_id is None or is_duplicate:
        return
    content = payload.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return
    if not isinstance(content, dict):
        return
    message_type = str(content.get("message_type") or "").strip()
    media_type = _RESOURCE_MESSAGE_TYPES.get(message_type)
    if not media_type:
        return
    conversation_short_id = str(content.get("conversation_short_id") or "").strip()
    server_message_id = str(content.get("server_message_id") or "").strip()
    if not conversation_short_id or not server_message_id:
        return
    background_tasks.add_task(
        _run_resource_download_task,
        conversation_short_id=conversation_short_id,
        server_message_id=server_message_id,
        media_type=media_type,
    )
    logger.info(
        "resource_download_scheduled event_id=%s message_type=%s media_type=%s",
        event_id, message_type, media_type,
    )


def _run_resource_download_task(
    *,
    conversation_short_id: str,
    server_message_id: str,
    media_type: str,
) -> None:
    """BackgroundTask：下载抖音素材并存 DouyinMessageResourceDownload 表。

    幂等：同 server_message_id 已有非 failed 记录则跳过。失败不阻断——
    download_douyin_resource 失败已 internally 记 failed 状态并 commit，此处只记日志。
    """
    db = SessionLocal()
    try:
        # 幂等查重：同 server_message_id 已有非 failed 记录则跳过
        existing = db.query(DouyinMessageResourceDownload).filter(
            DouyinMessageResourceDownload.server_message_id == server_message_id,
            DouyinMessageResourceDownload.resource_status != "failed",
        ).first()
        if existing:
            logger.info(
                "resource_download_skip_exists server_message_id=%s status=%s",
                server_message_id, existing.resource_status,
            )
            return
        # merchant_id 从持久化事件取（webhook 入库时已固化可信商户归属）
        event = db.query(DouyinWebhookEvent).filter(
            DouyinWebhookEvent.conversation_short_id == conversation_short_id,
            DouyinWebhookEvent.server_message_id == server_message_id,
            DouyinWebhookEvent.is_duplicate.is_(False),
        ).first()
        merchant_id = str(event.merchant_id) if event and event.merchant_id else None
        download_douyin_resource(
            db,
            merchant_id=merchant_id,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            media_type=media_type,
        )
        logger.info(
            "resource_download_done server_message_id=%s media_type=%s",
            server_message_id, media_type,
        )
    except HTTPException as exc:
        # download_douyin_resource 失败已 internally 记 failed + commit；此处只记日志不阻断
        logger.warning(
            "resource_download_failed server_message_id=%s detail=%s",
            server_message_id, str(exc.detail)[:200],
        )
    except Exception as exc:  # noqa: BLE001 —— 后台任务任何异常都不阻断 webhook
        db.rollback()
        logger.exception(
            "resource_download_unexpected_error server_message_id=%s error=%s",
            server_message_id, type(exc).__name__,
        )
    finally:
        db.close()


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

    # 调试日志：记录抖音回调的原始 text 和 has_encoded（确认脱敏是否来自平台）
    _webhook_content = payload.get("content") or {}
    if isinstance(_webhook_content, str):
        try:
            _webhook_content = json.loads(_webhook_content)
        except (json.JSONDecodeError, ValueError):
            _webhook_content = {}
    _raw_text = _webhook_content.get("text") or ""
    _has_encoded = _webhook_content.get("has_encoded") or ""
    if _raw_text:
        logger.info(
            "webhook_raw_text_debug source_path=%s event=%s text_len=%d has_encoded=%s text_preview=%s",
            source_path,
            payload.get("event"),
            len(_raw_text),
            _has_encoded,
            _raw_text[:80],
        )

    # 抖音平台掩码解码：has_encoded=="true" 时调 /decode_msg_content 拿明文，替换 content.text
    # 供后续 _process_webhook_*/extract_contacts_from_text 用明文。失败保留掩码文本不阻断。
    # ponytail 已知局限：同步调用（decode 结果要替换 text 供后续流程用，不能异步），超时由
    # config.DY_DECODE_MSG_TIMEOUT_SECONDS(5s) 收紧保护（比 webhook 响应超时短）；msg_id 24h 有效期。
    # 开关 DOUYIN_DECODE_MASKED_ENABLED 可一键关闭回退到掩码兜底，无需重新部署。
    if (
        config.DOUYIN_DECODE_MASKED_ENABLED
        and _has_encoded == "true"
        and _raw_text
        and config.DY_MAIN_ACCOUNT_ID
    ):
        _decoded = _try_decode_masked_text(payload, _webhook_content)
        if _decoded:
            _webhook_content["text"] = _decoded
            payload["content"] = _webhook_content
            logger.info(
                "webhook_mask_decoded source_path=%s event=%s msg_id=%s decoded_len=%d",
                source_path, payload.get("event"),
                _webhook_content.get("server_message_id") or "",
                len(_decoded),
            )

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
    maybe_schedule_resource_download(
        background_tasks=background_tasks,
        event_id=result.get("event_id"),
        payload=payload,
        is_duplicate=result.get("is_duplicate") is True,
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
    after_event_id: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Aggregate real private-message webhook events into workbench conversations."""
    merchant_scope = _workbench_merchant_scope(context)
    # after_event_id 与 event_limit 互斥：增量模式禁用旧 event_limit 窗口
    if after_event_id is not None and event_limit is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DOUYIN_CONVERSATION_CURSOR_CONFLICT",
                "message": "after_event_id 和 event_limit 不能同时传入",
            },
        )
    resolved_account_open_id = account_open_id or account_id
    try:
        return list_account_conversations(
            db,
            account_open_id=resolved_account_open_id,
            event_limit=event_limit,
            merchant_id=merchant_scope,
            after_event_id=after_event_id,
            limit=limit,
        )
    except (AccountAccessError, AccountMerchantDeniedError) as exc:
        raise _account_access_http_exception(exc) from exc


@router.get("/conversation-detail")
def get_douyin_conversation_detail(
    conversation_key: str,
    account_open_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """一次返回同一会话的消息和客户画像。"""
    merchant_scope = _workbench_merchant_scope(context)
    try:
        return get_conversation_detail(
            db,
            conversation_key=conversation_key,
            account_open_id=account_open_id,
            merchant_id=merchant_scope,
            require_non_empty=True,
        )
    except ConversationNotFoundError as exc:
        raise _conversation_not_found_http_exception() from exc
    except (AccountAccessError, AccountMerchantDeniedError) as exc:
        raise _account_access_http_exception(exc) from exc


@router.get("/conversations/{conversation_key}/messages")
def get_douyin_conversation_messages(
    conversation_key: str,
    account_open_id: str | None = None,
    after_event_id: int | None = Query(None, ge=0),
    before_event_id: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return real private-message webhook events for one workbench conversation."""
    merchant_scope = _workbench_merchant_scope(context)
    _validate_message_cursor_pair(after_event_id, before_event_id)
    cursor_options = _message_cursor_options(after_event_id, before_event_id, limit)
    try:
        return list_conversation_messages(
            db,
            conversation_key=conversation_key,
            account_open_id=account_open_id,
            merchant_id=merchant_scope,
            **cursor_options,
        )
    except ConversationNotFoundError as exc:
        raise _conversation_not_found_http_exception() from exc
    except (AccountAccessError, AccountMerchantDeniedError) as exc:
        raise _account_access_http_exception(exc) from exc


def _get_douyin_conversation_profile_response(
    account_id: str,
    conversation_key: str,
    account_open_id: str | None = None,
    db: Session | None = None,
    merchant_id: str | None = None,
) -> dict:
    """Return a read-only customer profile aggregated from 9000 local data."""
    if db is None:
        raise HTTPException(status_code=500, detail="db session is required")
    resolved_account_open_id = account_open_id or account_id
    try:
        data = get_conversation_profile(
            db,
            account_open_id=resolved_account_open_id,
            conversation_key=conversation_key,
            merchant_id=merchant_id,
        )
    except (AccountAccessError, AccountMerchantDeniedError) as exc:
        raise _account_access_http_exception(exc) from exc
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
    merchant_scope = _workbench_merchant_scope(context)
    return _get_douyin_conversation_profile_response(
        account_id=account_id,
        conversation_key=conversation_id,
        account_open_id=account_open_id,
        db=db,
        merchant_id=merchant_scope,
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
    merchant_scope = _workbench_merchant_scope(context)
    return _get_douyin_conversation_profile_response(
        account_id=account_id,
        conversation_key=conversation_key,
        account_open_id=account_open_id,
        db=db,
        merchant_id=merchant_scope,
    )


@router.get("/conversation-messages")
def get_douyin_conversation_messages_by_query(
    conversation_key: str,
    account_open_id: str | None = None,
    after_event_id: int | None = Query(None, ge=0),
    before_event_id: int | None = Query(None, ge=0),
    limit: int | None = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
) -> dict:
    """Return real private-message events without putting conversation_key in the path."""
    merchant_scope = _workbench_merchant_scope(context)
    _validate_message_cursor_pair(after_event_id, before_event_id)
    cursor_options = _message_cursor_options(after_event_id, before_event_id, limit)
    try:
        return list_conversation_messages(
            db,
            conversation_key=conversation_key,
            account_open_id=account_open_id,
            merchant_id=merchant_scope,
            **cursor_options,
        )
    except ConversationNotFoundError as exc:
        raise _conversation_not_found_http_exception() from exc
    except (AccountAccessError, AccountMerchantDeniedError) as exc:
        raise _account_access_http_exception(exc) from exc


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
            last_seen_event_id=request.last_seen_event_id,
            conversation_short_id=request.conversation_short_id,
            customer_open_id=request.customer_open_id,
        )
    except ConversationNotFoundError as exc:
        raise _conversation_not_found_http_exception() from exc
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
