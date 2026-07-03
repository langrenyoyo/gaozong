"""In-memory Douyin live-check state for on-site integration observation."""

import json
import logging
import hashlib
from datetime import datetime
from threading import Lock
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.models import DouyinAuthorizedAccount
from app.services.douyin_openapi_client import (
    build_safe_openapi_error_detail,
    call_douyin_openapi as _shared_call_douyin_openapi,
    build_signed_openapi_request_body_and_headers,
    openapi_endpoint_config,
    preview,
    requests,
)

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "secret",
    "token",
}

_state_lock = Lock()
_last_oauth_callback: dict[str, Any] | None = None
_last_webhook_observe: dict[str, Any] | None = None


def reset_live_check_state() -> None:
    """Clear in-memory live-check state for isolated tests."""
    global _last_oauth_callback, _last_webhook_observe
    with _state_lock:
        _last_oauth_callback = None
        _last_webhook_observe = None


def _now() -> datetime:
    return datetime.now()


def _preview(value: str | None, head: int = 4, tail: int = 4) -> str | None:
    return preview(value, head=head, tail=tail)


def _content_info(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if isinstance(content, dict):
        return {
            "content": content,
            "parse_success": True,
            "parse_error": None,
        }
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {
                "content": {},
                "parse_success": False,
                "parse_error": "content is not valid JSON",
            }
        if isinstance(parsed, dict):
            return {
                "content": parsed,
                "parse_success": True,
                "parse_error": None,
            }
        return {
            "content": {},
            "parse_success": False,
            "parse_error": "content JSON is not an object",
        }
    return {
        "content": {},
        "parse_success": False,
        "parse_error": "content is missing or unsupported",
    }


def _content_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return _content_info(payload)["content"]


def _safe_key_list(payload: dict[str, Any]) -> list[str]:
    return sorted(key for key in payload.keys() if key.lower() not in SENSITIVE_KEYS)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _auth_url_base_data() -> dict[str, Any]:
    missing: list[str] = []
    endpoint = _openapi_endpoint_config()
    upstream_base_url = endpoint["upstream_base_url"]
    if not upstream_base_url:
        missing.append("DY_OPENAPI_BASE_URL/DY_OPENAPI_PREFIX or DY_BASE_URL")
    if not config.DY_GMP_SECRET_KEY:
        missing.append("DY_GMP_SECRET_KEY")
    if not config.DY_MAIN_ACCOUNT_ID:
        missing.append("DY_MAIN_ACCOUNT_ID")
    if not config.DY_AUTH_REDIRECT_URL:
        missing.append("DY_AUTH_REDIRECT_URL")
    if not config.DY_CALLBACK_URL:
        missing.append("DY_CALLBACK_URL")

    if missing:
        return {
            "configured": False,
            "missing": missing,
            "auth_url": None,
            "auth_redirect_url": None,
            "callback_url": None,
        }

    return {
        "configured": True,
        "missing": [],
        "auth_url": None,
        "auth_redirect_url": config.DY_AUTH_REDIRECT_URL,
        "callback_url": config.DY_CALLBACK_URL,
    }


def build_auth_payload() -> dict[str, Any]:
    """Build upstream get_aweme_auth_url payload."""
    base_data = _auth_url_base_data()
    if not base_data["configured"]:
        return {}
    params = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "account_name": config.DY_ACCOUNT_NAME,
        "auth_redirect_url": base_data["auth_redirect_url"],
        "callback_url": base_data["callback_url"],
    }
    if config.DY_CALLBACK_EVENTS:
        params["callback_event"] = config.DY_CALLBACK_EVENTS
    return params


def _openapi_endpoint_config() -> dict[str, Any]:
    return openapi_endpoint_config()


def _openapi_base_url() -> str:
    return _openapi_endpoint_config()["upstream_base_url"]


def build_signed_openapi_request_body_and_headers(
    payload: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """兼容旧导入路径，实际使用统一 OpenAPI client。"""
    from app.services.douyin_openapi_client import (
        build_signed_openapi_request_body_and_headers as _shared_build,
    )

    return _shared_build(payload)


def _extract_upstream_auth_url(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("auth_url"),
        payload.get("url"),
        payload.get("redirect_url"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("auth_url"), data.get("url"), data.get("redirect_url")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _safe_upstream_error(
    resp: requests.Response | None,
    error_type: str | None = None,
    *,
    payload: dict[str, Any] | None = None,
    timestamp: str | None = None,
    signature: str | None = None,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upstream_status = resp.status_code if resp is not None else None
    upstream_code = None
    upstream_msg = None
    if resp is not None:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            upstream_code = body.get("code")
            upstream_msg = body.get("msg") or body.get("message")
    safe_error = {
        "upstream_status": upstream_status,
        "upstream_code": upstream_code,
        "upstream_msg": upstream_msg,
        "safe_message": "授权链接获取失败，请检查抖音上游接口配置、签名密钥和请求头。",
        "error_type": error_type,
        "signing_secret_config": "DY_GMP_SECRET_KEY",
        "signing_secret_configured": bool(config.DY_GMP_SECRET_KEY),
        "body_keys": sorted(payload.keys()) if payload else [],
        "timestamp_format": "unix_seconds" if timestamp and timestamp.isdigit() else "unknown",
        "authorization_preview": _preview(signature, head=6, tail=4),
    }
    if debug:
        safe_error.update(
            {
                "secret_len": debug.get("secret_len"),
                "secret_has_space": debug.get("secret_has_space"),
                "body_sha256": debug.get("body_sha256"),
                "canonical_string_sha256": debug.get("canonical_string_sha256"),
                "upstream_url": debug.get("upstream_url"),
                "upstream_base_url": debug.get("upstream_base_url"),
                "openapi_base_url": debug.get("openapi_base_url"),
                "openapi_prefix": debug.get("openapi_prefix"),
                "legacy_base_url_used": debug.get("legacy_base_url_used"),
                "legacy_base_url_present": debug.get("legacy_base_url_present"),
                "openapi_config_source": debug.get("openapi_config_source"),
            }
        )
    return safe_error


def fetch_auth_url() -> dict[str, Any]:
    """Fetch the final browser-openable Douyin auth URL via the unified OpenAPI client."""
    base_data = _auth_url_base_data()
    if not base_data["configured"]:
        return base_data

    payload = build_auth_payload()
    try:
        result = _shared_call_douyin_openapi("/get_aweme_auth_url", payload)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
        logger.warning(
            "Douyin live-check auth-url upstream failed: status=%s, error_type=%s",
            detail.get("upstream_status"),
            detail.get("error_type"),
        )
        raise HTTPException(
            status_code=502,
            detail={
                **detail,
                "safe_message": "授权链接获取失败，请检查抖音上游接口配置、签名密钥和请求头。",
            },
        ) from exc

    upstream_payload = result["payload"]
    auth_url = _extract_upstream_auth_url(upstream_payload)
    if not auth_url:
        raise HTTPException(
            status_code=502,
            detail={
                **result["debug"],
                "upstream_status": 200,
                "upstream_code": upstream_payload.get("code") if isinstance(upstream_payload, dict) else None,
                "upstream_msg": upstream_payload.get("msg") if isinstance(upstream_payload, dict) else None,
                "safe_message": "授权链接获取失败，上游响应中没有 auth_url。",
                "error_code": "invalid_upstream_response",
                "error_type": "MissingAuthUrl",
            },
        )
    return {
        **base_data,
        "auth_url": auth_url,
    }

def call_douyin_openapi(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """兼容旧导入路径，实际使用统一 OpenAPI client。"""
    return _shared_call_douyin_openapi(path, payload)


def sync_bind_info_accounts(
    db: Session,
    *,
    page_num: int = 1,
    page_size: int = 50,
    name_or_open_id: str | None = None,
    context: RequestContext | None = None,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "page_num": page_num,
        "page_size": page_size,
    }
    if name_or_open_id:
        request_payload["name_or_open_id"] = name_or_open_id

    result = call_douyin_openapi("/list_bind_info", request_payload)
    upstream_payload = result["payload"]
    data = upstream_payload.get("data")
    bind_list = data.get("bind_list") if isinstance(data, dict) else None
    if not isinstance(bind_list, list):
        raise HTTPException(
            status_code=502,
            detail={
                **result["debug"],
                "upstream_status": 200,
                "upstream_code": upstream_payload.get("code"),
                "upstream_msg": "missing data.bind_list",
                "body_keys": sorted(request_payload.keys()),
                "timestamp_format": "unix_seconds",
                "error_type": "InvalidBindListResponse",
            },
        )

    upserted = 0
    active_count = 0
    inactive_count = 0
    backfilled_owner_count = 0
    skipped_owner_conflict_count = 0
    warnings: list[dict[str, Any]] = []
    merchant_id = context.merchant_id if context and context.merchant_id else None
    tenant_id = getattr(context, "tenant_id", None) if context else None
    for item in bind_list:
        if not isinstance(item, dict):
            continue
        open_id = _optional_str(item.get("open_id"))
        if not open_id:
            continue
        bind_status = _int_or_default(item.get("bind_status"), 0)
        row = (
            db.query(DouyinAuthorizedAccount)
            .filter_by(main_account_id=config.DY_MAIN_ACCOUNT_ID, open_id=open_id)
            .first()
        )
        if row is None:
            row = DouyinAuthorizedAccount(
                main_account_id=config.DY_MAIN_ACCOUNT_ID,
                open_id=open_id,
                merchant_id=merchant_id,
                tenant_id=tenant_id,
                created_at=_now(),
            )
            db.add(row)
        elif merchant_id:
            if not row.merchant_id:
                row.merchant_id = merchant_id
                row.tenant_id = tenant_id
                backfilled_owner_count += 1
            elif str(row.merchant_id) != str(merchant_id):
                skipped_owner_conflict_count += 1
                warning = {
                    "code": "DOUYIN_ACCOUNT_OWNER_CONFLICT",
                    "account_open_id": open_id,
                    "owner_merchant_id": row.merchant_id,
                    "request_merchant_id": merchant_id,
                }
                warnings.append(warning)
                logger.warning(
                    "Douyin bind-info sync skipped owner conflict: account_open_id=%s, owner_merchant_id=%s, request_merchant_id=%s",
                    open_id,
                    row.merchant_id,
                    merchant_id,
                )
                continue
            elif tenant_id and not row.tenant_id:
                row.tenant_id = tenant_id
        row.user_id = _optional_str(item.get("user_id"))
        row.union_id = _optional_str(item.get("union_id"))
        row.account_name = _optional_str(item.get("account_name"))
        row.avatar_url = _optional_str(item.get("avatar_url"))
        row.bind_status = bind_status
        row.account_type = _int_or_none(item.get("account_type"))
        row.bind_time = _optional_str(item.get("bind_time"))
        row.unbind_time = _optional_str(item.get("unbind_time"))
        row.source_created_at = _optional_str(item.get("created_at"))
        row.last_synced_at = _now()
        row.raw_body_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        row.updated_at = _now()
        upserted += 1
        if bind_status == 1:
            active_count += 1
        else:
            inactive_count += 1
    db.commit()
    return {
        "fetched": len(bind_list),
        "upserted": upserted,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "backfilled_owner_count": backfilled_owner_count,
        "skipped_owner_conflict_count": skipped_owner_conflict_count,
        "warnings": warnings,
        "debug": result["debug"],
    }


def bind_authorized_account_by_open_id(
    db: Session,
    *,
    open_id: str,
    context: RequestContext,
) -> dict[str, Any]:
    """把授权成功的单个抖音号绑定到当前登录商户。

    与 sync_bind_info_accounts 的区别：
    - 归属冲突时显式拒绝（DOUYIN_ACCOUNT_ALREADY_BOUND_TO_OTHER_MERCHANT），
      而非静默跳过；
    - 仅处理单个 open_id，要求上游 /list_bind_info 返回 open_id 完全匹配
      且 bind_status=1 的账号。

    merchant_id 必须来自可信 RequestContext，调用方需保证非空。
    """
    merchant_id = context.merchant_id
    tenant_id = getattr(context, "tenant_id", None)

    request_payload: dict[str, Any] = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "page_num": 1,
        "page_size": 50,
        "name_or_open_id": open_id,
    }
    result = call_douyin_openapi("/list_bind_info", request_payload)
    upstream_payload = result["payload"]
    data = upstream_payload.get("data")
    bind_list = data.get("bind_list") if isinstance(data, dict) else None

    # 仅接受上游返回中 open_id 完全匹配的账号
    matched: dict[str, Any] | None = None
    if isinstance(bind_list, list):
        for item in bind_list:
            if isinstance(item, dict) and _optional_str(item.get("open_id")) == open_id:
                matched = item
                break

    if matched is None:
        logger.info(
            "douyin bind-authorized-open-id 未匹配到 open_id: open_id=%s, fetched=%s",
            open_id,
            len(bind_list) if isinstance(bind_list, list) else 0,
        )
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DOUYIN_ACCOUNT_NOT_FOUND",
                "message": "未在上游授权列表中找到匹配的抖音号",
                "account_open_id": open_id,
            },
        )

    bind_status = _int_or_default(matched.get("bind_status"), 0)
    if bind_status != 1:
        logger.info(
            "douyin bind-authorized-open-id 账号未激活: open_id=%s, bind_status=%s",
            open_id,
            bind_status,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOUYIN_ACCOUNT_NOT_ACTIVE",
                "message": f"抖音号未处于激活状态(bind_status={bind_status})",
                "account_open_id": open_id,
                "bind_status": bind_status,
            },
        )

    # 查本地归属：(main_account_id, open_id) 全局唯一
    row = (
        db.query(DouyinAuthorizedAccount)
        .filter_by(main_account_id=config.DY_MAIN_ACCOUNT_ID, open_id=open_id)
        .first()
    )
    now = _now()
    action = "updated"

    if row is None:
        # 未绑定任何商户 → 写入当前商户
        row = DouyinAuthorizedAccount(
            main_account_id=config.DY_MAIN_ACCOUNT_ID,
            open_id=open_id,
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            created_at=now,
        )
        db.add(row)
        action = "created"
    elif row.merchant_id and str(row.merchant_id) != str(merchant_id):
        # 已绑定其他商户 → 显式拒绝，不覆盖
        logger.warning(
            "douyin bind-authorized-open-id 拒绝跨商户绑定: open_id=%s, owner_merchant_id=%s, request_merchant_id=%s",
            open_id,
            row.merchant_id,
            merchant_id,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "DOUYIN_ACCOUNT_ALREADY_BOUND_TO_OTHER_MERCHANT",
                "message": "该抖音号已绑定其他商户，无法重复绑定",
                "account_open_id": open_id,
                "owner_merchant_id": row.merchant_id,
            },
        )
    elif not row.merchant_id:
        # 已存在但未归属 → 回填当前商户
        row.merchant_id = merchant_id
        if tenant_id:
            row.tenant_id = tenant_id
        action = "backfilled"

    # upsert 账号资料（来源：上游 /list_bind_info）
    row.user_id = _optional_str(matched.get("user_id"))
    row.union_id = _optional_str(matched.get("union_id"))
    row.account_name = _optional_str(matched.get("account_name"))
    row.avatar_url = _optional_str(matched.get("avatar_url"))
    row.bind_status = bind_status
    row.account_type = _int_or_none(matched.get("account_type"))
    row.bind_time = _optional_str(matched.get("bind_time"))
    row.unbind_time = _optional_str(matched.get("unbind_time"))
    row.source_created_at = _optional_str(matched.get("created_at"))
    row.raw_body_json = json.dumps(matched, ensure_ascii=False, separators=(",", ":"))
    row.last_synced_at = now
    row.updated_at = now
    db.commit()

    logger.info(
        "douyin bind-authorized-open-id 完成: open_id=%s, action=%s, merchant_id=%s",
        open_id,
        action,
        merchant_id,
    )
    return {
        "action": action,
        "account_open_id": open_id,
        "merchant_id": merchant_id,
        "bind_status": bind_status,
        "account_name": row.account_name,
        "avatar_url": row.avatar_url,
        "updated_at": row.updated_at,
    }


def list_persisted_authorized_accounts(db: Session, *, merchant_id: str | None = None) -> dict[str, Any]:
    query = db.query(DouyinAuthorizedAccount).filter(DouyinAuthorizedAccount.bind_status == 1)
    if merchant_id:
        query = query.filter(DouyinAuthorizedAccount.merchant_id == merchant_id)
    rows = query.order_by(DouyinAuthorizedAccount.last_synced_at.desc(), DouyinAuthorizedAccount.id.desc()).all()
    items = [_persisted_account_item(row) for row in rows]
    return {"items": items, "total": len(items), "source": "persisted_bind_info"}


def _persisted_account_item(row: DouyinAuthorizedAccount) -> dict[str, Any]:
    open_id = row.open_id
    display_name = row.account_name or f"抖音号 {open_id[-6:]}"
    account_id = int(hashlib.sha256(open_id.encode("utf-8")).hexdigest()[:8], 16)
    return {
        "id": account_id,
        "account_id": open_id,
        "douyin_account_id": account_id,
        "account_open_id": open_id,
        "open_id": open_id,
        "account_name": display_name,
        "name": display_name,
        "nickname": display_name,
        "avatar": row.avatar_url or "",
        "avatar_url": row.avatar_url or "",
        "status": "active",
        "is_active": True,
        "is_authorized": True,
        "bind_status": row.bind_status,
        "account_type": row.account_type,
        "last_active_at": row.last_synced_at,
        "authorized_at": row.bind_time or row.created_at,
        "unread_count": 0,
        "source": "persisted_bind_info",
        "has_events": False,
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    parsed = _int_or_none(value)
    return default if parsed is None else parsed


def build_auth_url() -> dict[str, Any]:
    """Return live-check auth URL configuration summary without calling upstream."""
    return _auth_url_base_data()


def record_oauth_callback(params: dict[str, Any]) -> dict[str, Any]:
    """Record an OAuth callback summary without token persistence."""
    global _last_oauth_callback
    summary = {
        "received_at": _now(),
        "has_code": bool(params.get("code")),
        "code_preview": _preview(params.get("code")),
        "state": params.get("state"),
        "open_id": params.get("open_id"),
        "nick_name": params.get("nick_name") or params.get("nickname"),
        "avatar": params.get("avatar") or params.get("avatar_url"),
        "error": params.get("error"),
        "error_description": params.get("error_description"),
        "query_keys": sorted(
            key for key in params.keys() if key.lower() not in SENSITIVE_KEYS
        ),
    }
    with _state_lock:
        _last_oauth_callback = summary
    logger.info(
        "Douyin live-check oauth callback observed: has_code=%s, state=%s, open_id=%s, error=%s",
        summary["has_code"],
        summary["state"],
        summary["open_id"],
        summary["error"],
    )
    return summary


def record_webhook_observe(headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """Record webhook request shape without passing it to production processing."""
    global _last_webhook_observe
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    content_info = _content_info(payload)
    content = content_info["content"]
    summary = {
        "received_at": _now(),
        "has_authorization": bool(normalized_headers.get("authorization")),
        "has_x_auth_timestamp": bool(normalized_headers.get("x-auth-timestamp")),
        "content_type": normalized_headers.get("content-type"),
        "user_agent": normalized_headers.get("user-agent"),
        "body_has_event": "event" in payload,
        "body_has_content": "content" in payload,
        "body_has_open_id": "open_id" in payload,
        "body_has_account_open_id": "account_open_id" in payload,
        "body_has_conversation_short_id": "conversation_short_id" in payload
        or "conversation_short_id" in content,
        "body_has_server_message_id": "server_message_id" in payload
        or "server_message_id" in content,
        "from_user_id": _optional_str(payload.get("from_user_id")),
        "to_user_id": _optional_str(payload.get("to_user_id")),
        "body_open_id": _optional_str(payload.get("open_id")),
        "body_account_open_id": _optional_str(payload.get("account_open_id")),
        "content_open_id": _optional_str(content.get("open_id")),
        "content_account_open_id": _optional_str(content.get("account_open_id")),
        "content_parse_success": content_info["parse_success"],
        "content_parse_error": content_info["parse_error"],
        "content_has_conversation_short_id": "conversation_short_id" in content,
        "content_has_server_message_id": "server_message_id" in content,
        "content_has_message_type": "message_type" in content,
        "content_message_type": content.get("message_type"),
        "event": payload.get("event"),
        "body_keys": _safe_key_list(payload),
        "content_keys": _safe_key_list(content),
        "forward_to_formal_enabled": False,
        "forward_to_formal_success": None,
        "forward_to_formal_event_id": None,
        "forward_to_formal_lead_id": None,
        "forward_to_formal_lead_action": None,
        "forward_to_formal_error": None,
    }
    with _state_lock:
        _last_webhook_observe = summary
    logger.info(
        "Douyin live-check webhook observed: has_auth=%s, has_ts=%s, event=%s, body_keys=%s",
        summary["has_authorization"],
        summary["has_x_auth_timestamp"],
        summary["event"],
        summary["body_keys"],
    )
    return summary


def update_webhook_observe_forward_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Attach formal-forward result fields to the latest observe summary."""
    global _last_webhook_observe
    with _state_lock:
        if _last_webhook_observe is None:
            return None
        _last_webhook_observe.update(result)
        return dict(_last_webhook_observe)


def _datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _pending_auth_polling_status() -> dict[str, Any]:
    return {
        "status": "pending",
        "open_id": None,
        "nickname": None,
        "received_at": None,
    }


def _auth_polling_status(
    db: Session | None,
    context: RequestContext | None,
    oauth_callback: dict[str, Any] | None,
) -> dict[str, Any]:
    if oauth_callback and oauth_callback.get("error"):
        return {
            "status": "failed",
            "open_id": oauth_callback.get("open_id"),
            "nickname": oauth_callback.get("nick_name"),
            "received_at": _datetime_text(oauth_callback.get("received_at")),
        }

    merchant_id = context.merchant_id if context and context.merchant_id else None
    if db is not None and merchant_id:
        row = (
            db.query(DouyinAuthorizedAccount)
            .filter(
                DouyinAuthorizedAccount.merchant_id == merchant_id,
                DouyinAuthorizedAccount.bind_status == 1,
            )
            .order_by(DouyinAuthorizedAccount.last_synced_at.desc(), DouyinAuthorizedAccount.id.desc())
            .first()
        )
        if row is not None:
            return {
                "status": "authorized",
                "open_id": row.open_id,
                "nickname": row.account_name,
                "received_at": _datetime_text(row.last_synced_at or row.updated_at or row.created_at),
            }
        return _pending_auth_polling_status()

    if oauth_callback and oauth_callback.get("open_id"):
        return {
            "status": "authorized",
            "open_id": oauth_callback.get("open_id"),
            "nickname": oauth_callback.get("nick_name"),
            "received_at": _datetime_text(oauth_callback.get("received_at")),
        }

    return _pending_auth_polling_status()


def get_live_check_status(
    db: Session | None = None,
    context: RequestContext | None = None,
) -> dict[str, Any]:
    with _state_lock:
        oauth_callback = dict(_last_oauth_callback) if _last_oauth_callback else None
        webhook_observe = dict(_last_webhook_observe) if _last_webhook_observe else None
    auth_url_info = build_auth_url()
    auth_polling = _auth_polling_status(db, context, oauth_callback)
    return {
        "enabled": config.DY_LIVE_CHECK_ENABLED,
        "auth_url_configured": auth_url_info["configured"],
        "missing_config": auth_url_info["missing"],
        "auth_redirect_url": auth_url_info["auth_redirect_url"],
        "webhook_observe_url": auth_url_info["callback_url"],
        "auth_polling": auth_polling,
        "last_oauth_callback": oauth_callback,
        "last_webhook_observe": webhook_observe,
    }


def list_authorized_accounts() -> dict[str, Any]:
    """Return authorized Douyin accounts observed by live-check OAuth callback."""
    with _state_lock:
        oauth_callback = dict(_last_oauth_callback) if _last_oauth_callback else None

    if not oauth_callback or not oauth_callback.get("open_id") or oauth_callback.get("error"):
        return {"items": [], "total": 0, "source": "live_check_memory"}

    open_id = str(oauth_callback["open_id"])
    account_id = int(hashlib.sha256(open_id.encode("utf-8")).hexdigest()[:8], 16)
    item = {
        "id": account_id,
        "account_id": account_id,
        "douyin_account_id": account_id,
        "account_open_id": open_id,
        "open_id": open_id,
        "account_name": oauth_callback.get("nick_name") or f"已授权抖音号 {open_id[-4:]}",
        "nickname": oauth_callback.get("nick_name"),
        "avatar": oauth_callback.get("avatar"),
        "avatar_url": oauth_callback.get("avatar"),
        "status": "active",
        "is_active": True,
        "last_active_at": oauth_callback.get("received_at"),
        "authorized_at": oauth_callback.get("received_at"),
        "unread_count": 0,
        "source": "live_check_oauth_callback",
    }
    return {"items": [item], "total": 1, "source": "live_check_memory"}
