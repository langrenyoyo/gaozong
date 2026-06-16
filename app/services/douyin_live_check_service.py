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


def _content_dict(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    return content if isinstance(content, dict) else {}


def _safe_key_list(payload: dict[str, Any]) -> list[str]:
    return sorted(key for key in payload.keys() if key.lower() not in SENSITIVE_KEYS)


def _auth_url_base_data() -> dict[str, Any]:
    missing: list[str] = []
    if not config.DY_BASE_URL:
        missing.append("DY_BASE_URL")
    if not config.DY_GMP_SECRET_KEY:
        missing.append("DY_GMP_SECRET_KEY")
    if not config.DY_MAIN_ACCOUNT_ID:
        missing.append("DY_MAIN_ACCOUNT_ID")
    if not config.PUBLIC_BASE_URL:
        missing.append("PUBLIC_BASE_URL")

    if missing:
        return {
            "configured": False,
            "missing": missing,
            "auth_url": None,
            "auth_redirect_url": None,
            "callback_url": None,
        }

    base = config.PUBLIC_BASE_URL.rstrip("/")
    return {
        "configured": True,
        "missing": [],
        "auth_url": None,
        "auth_redirect_url": f"{base}/integrations/douyin/live-check/oauth-callback",
        "callback_url": f"{base}/integrations/douyin/live-check/webhook-observe",
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


def _extract_upstream_auth_url(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("auth_url"),
        payload.get("url"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("auth_url"), data.get("url")])
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
    return {
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


def fetch_auth_url() -> dict[str, Any]:
    """Fetch the final browser-openable Douyin auth URL via signed upstream POST."""
    base_data = _auth_url_base_data()
    if not base_data["configured"]:
        return base_data

    payload = build_auth_payload()
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    sign_str = body_text + "-" + timestamp
    signature = hashlib.sha256((config.DY_GMP_SECRET_KEY + sign_str).encode("utf-8")).hexdigest()
    resp = None
    try:
        resp = requests.post(
            f"{config.DY_BASE_URL.rstrip('/')}/get_aweme_auth_url",
            data=body_text.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-Timestamp": timestamp,
                "Authorization": signature,
            },
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
    content = _content_dict(payload)
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
        "event": payload.get("event"),
        "body_keys": _safe_key_list(payload),
        "content_keys": _safe_key_list(content),
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
