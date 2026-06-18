"""In-memory Douyin live-check state for on-site integration observation."""

import hashlib
import json
import logging
import time
from datetime import datetime
from threading import Lock
from typing import Any

import requests
from fastapi import HTTPException

from app import config

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
    if not value:
        return None
    if len(value) <= head + tail:
        return value
    return f"{value[:head]}...{value[-tail:]}"


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
    upstream_base_url = _openapi_base_url()
    if not upstream_base_url:
        missing.append("DY_BASE_URL")
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


def _openapi_base_url() -> str:
    legacy_base_url = getattr(config, "DY_BASE_URL", "") or ""
    if legacy_base_url:
        return legacy_base_url.rstrip("/")
    base_url = (getattr(config, "DY_OPENAPI_BASE_URL", "") or "").rstrip("/")
    prefix = (getattr(config, "DY_OPENAPI_PREFIX", "") or "").strip()
    if not base_url or not prefix:
        return ""
    return f"{base_url}/{prefix.strip('/')}"


def build_signed_openapi_request_body_and_headers(
    payload: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build canonical JSON body, OpenAPI signing headers, and safe debug fields."""
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    canonical_string = body_text + "-" + timestamp
    secret = config.DY_GMP_SECRET_KEY
    signature = hashlib.sha256((secret + canonical_string).encode("utf-8")).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Timestamp": timestamp,
        "Authorization": signature,
    }
    debug = {
        "secret_len": len(secret),
        "secret_has_space": secret != secret.strip(),
        "body_sha256": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        "canonical_string_sha256": hashlib.sha256(canonical_string.encode("utf-8")).hexdigest(),
    }
    return body_text, headers, debug


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
            }
        )
    return safe_error


def fetch_auth_url() -> dict[str, Any]:
    """Fetch the final browser-openable Douyin auth URL via signed upstream POST."""
    base_data = _auth_url_base_data()
    if not base_data["configured"]:
        return base_data

    payload = build_auth_payload()
    body_text, headers, debug = build_signed_openapi_request_body_and_headers(payload)
    timestamp = headers["X-Auth-Timestamp"]
    signature = headers["Authorization"]
    resp = None
    try:
        resp = requests.post(
            f"{_openapi_base_url()}/get_aweme_auth_url",
            data=body_text.encode("utf-8"),
            headers=headers,
            timeout=config.DY_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        upstream_payload = resp.json()
    except requests.RequestException as exc:
        logger.warning(
            "Douyin live-check auth-url upstream failed: status=%s, error_type=%s",
            resp.status_code if resp is not None else None,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=_safe_upstream_error(
                resp,
                type(exc).__name__,
                payload=payload,
                timestamp=timestamp,
                signature=signature,
                debug=debug,
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "upstream_status": resp.status_code if resp is not None else None,
                "upstream_code": None,
                "upstream_msg": "non-json response",
                "safe_message": "授权链接获取失败，上游返回非 JSON 响应。",
                "error_type": type(exc).__name__,
            },
        ) from exc

    auth_url = _extract_upstream_auth_url(upstream_payload)
    if not auth_url:
        raise HTTPException(
            status_code=502,
            detail={
                "upstream_status": resp.status_code,
                "upstream_code": upstream_payload.get("code") if isinstance(upstream_payload, dict) else None,
                "upstream_msg": upstream_payload.get("msg") if isinstance(upstream_payload, dict) else None,
                "safe_message": "授权链接获取失败，上游响应中没有 auth_url。",
                "error_type": "MissingAuthUrl",
            },
        )
    return {
        **base_data,
        "auth_url": auth_url,
    }


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


def get_live_check_status() -> dict[str, Any]:
    with _state_lock:
        oauth_callback = dict(_last_oauth_callback) if _last_oauth_callback else None
        webhook_observe = dict(_last_webhook_observe) if _last_webhook_observe else None
    auth_url_info = build_auth_url()
    return {
        "enabled": config.DY_LIVE_CHECK_ENABLED,
        "auth_url_configured": auth_url_info["configured"],
        "missing_config": auth_url_info["missing"],
        "auth_redirect_url": auth_url_info["auth_redirect_url"],
        "webhook_observe_url": auth_url_info["callback_url"],
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
