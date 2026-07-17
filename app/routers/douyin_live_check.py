"""Douyin on-site live-check endpoints."""

import json
import logging
import ipaddress
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, Field

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import (
    get_request_context_required,
    require_permission,
)
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
    bind_authorized_account_by_open_id,
    build_auth_url,
    consume_oauth_state,
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
AUTH_REDIRECT_DEFAULT_ORIGIN = "https://douyinapi.misanduo.com"
AUTH_REDIRECT_RESULT_PATH = "/douyin-ai-cs"
AUTH_REDIRECT_ALLOWED_PATHS = {
    "/douyin-ai-cs",
    "/douyin-cs/workbench",
    "/settings/douyin",
    "/wechat-assistant",
}
# 抖音 /get_aweme_auth_url 传入的 callback_url 是私信事件回调地址（非 OAuth 回调）。
# 当 DY_CALLBACK_URL 指向本路径时，抖音把 im_receive_msg / im_send_msg /
# im_enter_direct_msg 等私信事件推送到这里，行为与 webhook-observe 一致。
LIVE_CHECK_CALLBACK_PATH = "/integrations/douyin/live-check/callback"

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
def get_auth_url(
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinLiveCheckAuthUrlResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _ensure_enabled()
    data = fetch_auth_url(
        db=db,
        context=context,
        redirect_target=_auth_redirect_frontend_base(),
    )
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


def _auth_redirect_error(code: str, status_code: int = 400) -> HTTPException:
    messages = {
        "DOUYIN_OAUTH_REDIRECT_FORBIDDEN": "抖音授权回跳地址不在可信白名单内",
        "DOUYIN_OAUTH_REDIRECT_CONFIG_INVALID": "抖音授权回跳白名单配置无效",
    }
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": messages.get(code, "抖音授权回跳地址校验失败")},
    )


def _is_local_or_private_host(host: str | None) -> bool:
    if not host:
        return True
    text = host.strip().strip("[]").lower()
    if text in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not ip.is_global


def _normalize_auth_redirect_origin(raw_origin: str) -> str:
    parts = urlsplit(raw_origin.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if parts.username or parts.password:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    path = parts.path or ""
    if path not in {"", "/"}:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if parts.query or parts.fragment:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if config.is_production_env() and _is_local_or_private_host(parts.hostname):
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def _auth_redirect_allowed_origins() -> set[str]:
    raw_items = set(config.DY_AUTH_REDIRECT_ALLOWED_ORIGINS_SET)
    if config.is_production_env() and not raw_items:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_CONFIG_INVALID", status_code=500)
    # 开发环境只保留固定兜底；业务前端地址仍需显式加入白名单。
    if not raw_items:
        raw_items = {AUTH_REDIRECT_DEFAULT_ORIGIN}
    allowed: set[str] = set()
    for item in raw_items:
        allowed.add(_normalize_auth_redirect_origin(item))
    return allowed


def _validate_auth_redirect_target(raw_target: str | None) -> str:
    """校验并归一化 OAuth 前端回跳地址，只返回可信 origin。"""
    if not raw_target:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    parts = urlsplit(raw_target.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if parts.username or parts.password:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if config.is_production_env() and _is_local_or_private_host(parts.hostname):
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    path = parts.path or ""
    if path not in {"", "/"} and path not in AUTH_REDIRECT_ALLOWED_PATHS:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    if parts.query or parts.fragment:
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    origin = f"{parts.scheme}://{parts.netloc}".rstrip("/")
    if origin not in _auth_redirect_allowed_origins():
        raise _auth_redirect_error("DOUYIN_OAUTH_REDIRECT_FORBIDDEN")
    return origin


def _auth_redirect_frontend_base() -> str:
    """授权完成后 302 回前端的可信 origin。"""
    target = config.DY_AUTH_REDIRECT_FRONTEND_URL or AUTH_REDIRECT_DEFAULT_ORIGIN
    return _validate_auth_redirect_target(target)


def _auth_redirect_url(frontend_base: str, query: str) -> str:
    return f"{frontend_base}{AUTH_REDIRECT_RESULT_PATH}?{query}"


def _safe_query_value(value: str | None) -> str:
    """URL 编码 query 值，避免中文/特殊字符破坏重定向 URL。"""
    return quote(str(value), safe="")


def _require_merchant_id(context: RequestContext) -> str:
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


@router.get("/auth-redirect")
def auth_redirect(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """抖音授权成功后 GMP 302 回跳入口：同步企业号后跳回前端。

    GMP /get_aweme_auth_url 的 auth_redirect_url 指向本路由。授权成功后 GMP 302
    到这里，携带 open_id / nick_name / avatar 等。本路由调 /list_bind_info 同步
    账号到 douyin_authorized_accounts，再 302 回前端 /douyin-ai-cs 展示结果。
    与 oauth-callback（仅观察 OAuth 回调摘要，不写库）不同，本路由会真正同步账号。
    """
    _ensure_enabled()
    params = dict(request.query_params)
    frontend_base = _auth_redirect_frontend_base()
    try:
        trusted_context, state_redirect_target = consume_oauth_state(db, params.get("state"))
        if state_redirect_target:
            frontend_base = _validate_auth_redirect_target(state_redirect_target)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code") or "DOUYIN_OAUTH_STATE_INVALID"
        logger.warning(
            "douyin auth-redirect state 校验失败: code=%s, query_keys=%s",
            code,
            sorted(params.keys()),
        )
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, f"auth=failed&reason={_safe_query_value(code)}"),
            status_code=302,
        )
    except Exception:
        logger.exception("douyin auth-redirect redirect target 校验异常")
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, "auth=failed&reason=DOUYIN_OAUTH_REDIRECT_FORBIDDEN"),
            status_code=302,
        )

    error = params.get("error") or params.get("err_msg")
    if error:
        logger.warning(
            "douyin auth-redirect 收到授权失败: error=%s, open_id=%s",
            error,
            params.get("open_id"),
        )
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, f"auth=failed&reason={_safe_query_value(error)}"),
            status_code=302,
        )

    open_id = params.get("open_id")
    nick_name = params.get("nick_name") or params.get("nickname")
    sync_key = open_id or nick_name
    if not sync_key:
        logger.warning(
            "douyin auth-redirect 缺少 open_id 和 nick_name: query_keys=%s",
            sorted(params.keys()),
        )
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, "auth=unknown"),
            status_code=302,
        )

    try:
        sync_result = sync_bind_info_accounts(
            db,
            page_num=1,
            page_size=20,
            name_or_open_id=sync_key,
            context=trusted_context,
        )
    except Exception as exc:
        # 同步失败：仅记录 error 类型与摘要，绝不打印 secret/token/Authorization
        logger.error(
            "douyin auth-redirect 同步失败: sync_key=%s, error_type=%s, open_id=%s",
            sync_key,
            type(exc).__name__,
            open_id,
        )
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, "auth=sync_failed"),
            status_code=302,
        )

    logger.info(
        "douyin auth-redirect 同步完成: sync_key=%s, upserted=%s, active_count=%s",
        sync_key,
        sync_result.get("upserted"),
        sync_result.get("active_count"),
    )
    if open_id:
        return RedirectResponse(
            url=_auth_redirect_url(frontend_base, f"auth=success&open_id={_safe_query_value(open_id)}"),
            status_code=302,
        )
    return RedirectResponse(
        url=_auth_redirect_url(frontend_base, f"auth=success&nick_name={_safe_query_value(nick_name or '')}"),
        status_code=302,
    )


@router.get("/status", response_model=DouyinLiveCheckStatusResponse)
def status(
    state: str | None = None,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinLiveCheckStatusResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _require_merchant_id(context)
    _ensure_enabled()
    return DouyinLiveCheckStatusResponse(
        data=get_live_check_status(db=db, context=context, state=state)
    )


@router.get("/accounts", response_model=DouyinLiveCheckAccountsResponse)
def accounts(
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinLiveCheckAccountsResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _ensure_enabled()
    return DouyinLiveCheckAccountsResponse(
        data=list_douyin_workbench_accounts_with_event_fallback(
            db,
            merchant_id=_require_merchant_id(context),
        )
    )


@router.post("/accounts/sync-bind-info", response_model=DouyinBindInfoSyncResponse)
def sync_accounts_bind_info(
    request: DouyinBindInfoSyncRequest = DouyinBindInfoSyncRequest(),
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinBindInfoSyncResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
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


class _BindAuthorizedOpenIdRequest(BaseModel):
    """授权绑定请求体：只接受 open_id。

    merchant_id 由 RequestContext 提供，请求体传入的 merchant_id 会被忽略
    （Pydantic 默认丢弃额外字段），从根本上杜绝前端伪造商户归属。
    """

    open_id: str = Field(..., min_length=1, description="授权成功的抖音企业号 open_id")


@router.post("/accounts/bind-authorized-open-id")
def bind_authorized_open_id(
    request: _BindAuthorizedOpenIdRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """把授权成功的抖音号绑定到当前登录商户。

    - 必须登录态（get_request_context_required）且具备 auto_wechat:douyin_ai_cs 权限；
    - merchant_id 强制来自 RequestContext（NewCarProject 登录态），不取自请求体；
    - 一个 open_id 只能绑定一个 merchant_id；跨商户重复绑定返回
      DOUYIN_ACCOUNT_ALREADY_BOUND_TO_OTHER_MERCHANT。
    """
    _ensure_enabled()
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    data = bind_authorized_account_by_open_id(
        db,
        open_id=request.open_id,
        context=context,
    )
    return {"success": True, "data": data, "message": "success"}


@router.post("/messages/send", response_model=DouyinPrivateMessageSendResponse)
def send_message(
    request: DouyinPrivateMessageSendRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinPrivateMessageSendResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _ensure_enabled()
    data = send_manual_private_message(
        db,
        merchant_id=_require_merchant_id(context),
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
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinResourceDownloadResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _ensure_enabled()
    data = download_douyin_resource(
        db,
        merchant_id=_require_merchant_id(context),
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
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> DouyinImageUploadResponse:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    _ensure_enabled()
    data = upload_douyin_image(
        db,
        merchant_id=_require_merchant_id(context),
        file_name=request.file_name,
        image_base64=request.image_base64,
        open_id=request.open_id,
    )
    return DouyinImageUploadResponse(data=data)


@router.post("/webhook-observe", response_model=DouyinLiveCheckObserveResponse)
async def webhook_observe(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DouyinLiveCheckObserveResponse:
    _ensure_enabled()
    return await _handle_live_check_event(request, db, LIVE_CHECK_OBSERVE_PATH, background_tasks)


@router.post("/callback", response_model=DouyinLiveCheckObserveResponse)
async def live_check_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DouyinLiveCheckObserveResponse:
    """抖音私信事件回调兼容入口。

    抖音 /get_aweme_auth_url 传入的 callback_url 是私信事件回调地址（非 OAuth 回调）。
    本路由复用 webhook-observe 的私信事件处理逻辑，按配置转发到正式 webhook 管线，
    兼容 im_receive_msg / im_send_msg / im_enter_direct_msg 等回调事件；
    不调用 record_oauth_callback（OAuth 观察另走 oauth-callback）。
    """
    _ensure_enabled()
    return await _handle_live_check_event(request, db, LIVE_CHECK_CALLBACK_PATH, background_tasks)


async def _handle_live_check_event(
    request: Request,
    db: Session,
    source_path: str,
    background_tasks: BackgroundTasks,
) -> DouyinLiveCheckObserveResponse:
    """统一处理抖音私信事件回调（webhook-observe 与 callback 复用）。

    解析请求体 → 记录事件观测摘要 → 按配置转发到正式 webhook 管线。
    非私信事件格式仅记录 warning，不误当成 OAuth callback。
    """
    body = await request.body()
    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    event = payload.get("event")
    if not event:
        # 非私信事件格式：记录 warning，但不误当成 OAuth callback，仍按事件观测流程处理
        logger.warning(
            "live-check callback 收到非私信事件格式: source_path=%s, event=%s",
            source_path,
            event,
        )

    data = record_webhook_observe(dict(request.headers), payload)
    forward_result = await _maybe_forward_to_formal(
        request, body, payload, db, source_path=source_path, background_tasks=background_tasks
    )
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
    *,
    source_path: str = LIVE_CHECK_OBSERVE_PATH,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    if not config.DY_LIVE_CHECK_FORWARD_TO_FORMAL:
        logger.info(
            "live-check webhook observe: source_path=%s, forward_to_formal_enabled=false, event=%s, forward_result=disabled",
            source_path,
            payload.get("event"),
        )
        return _forward_disabled_result()

    try:
        formal = await _handle_douyin_webhook(
            body=body,
            x_auth_timestamp=request.headers.get("X-Auth-Timestamp"),
            authorization=request.headers.get("Authorization"),
            db=db,
            source_path=source_path,
            background_tasks=background_tasks,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.warning(
            "live-check webhook observe: source_path=%s, forward_to_formal_enabled=true, event=%s, forward_result=error, error_type=%s",
            source_path,
            payload.get("event"),
            type(exc).__name__,
        )
        return _forward_error_result(exc)

    logger.info(
        "live-check webhook observe: source_path=%s, forward_to_formal_enabled=true, event=%s, forward_result=success, event_id=%s, lead_id=%s, lead_action=%s",
        source_path,
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
