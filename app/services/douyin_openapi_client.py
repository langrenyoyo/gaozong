"""抖音 OpenAPI 统一签名、调用与安全错误封装。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import requests
from fastapi import HTTPException

from app import config

logger = logging.getLogger(__name__)


SAFE_MESSAGE = "抖音上游接口调用失败，请检查配置或稍后重试。"
SENSITIVE_PAYLOAD_KEYS = {
    "access_token",
    "authorization",
    "client_secret",
    "image_base64",
    "refresh_token",
    "secret",
    "token",
}


class DouyinOpenAPIError(Exception):
    """抖音 OpenAPI 调用错误基类。"""


class DouyinOpenAPIHTTPError(DouyinOpenAPIError):
    """抖音 OpenAPI HTTP 层错误。"""


class DouyinOpenAPIUpstreamError(DouyinOpenAPIError):
    """抖音 OpenAPI 业务层错误。"""


class DouyinOpenAPIResponseError(DouyinOpenAPIError):
    """抖音 OpenAPI 响应结构错误。"""


def preview(value: str | None, head: int = 6, tail: int = 4) -> str | None:
    """返回脱敏预览值。"""
    if not value:
        return None
    if len(value) <= head + tail:
        return value
    return f"{value[:head]}...{value[-tail:]}"


def openapi_endpoint_config() -> dict[str, Any]:
    """读取 OpenAPI base/prefix 配置，兼容旧 DY_BASE_URL 降级。"""
    openapi_base_url = (getattr(config, "DY_OPENAPI_BASE_URL", "") or "").rstrip("/")
    openapi_prefix = (getattr(config, "DY_OPENAPI_PREFIX", "") or "").strip()
    legacy_base_url = (getattr(config, "DY_BASE_URL_LEGACY", "") or "").rstrip("/")
    fallback_legacy_base_url = (getattr(config, "DY_BASE_URL", "") or "").rstrip("/")

    if openapi_base_url and openapi_prefix:
        return {
            "base_url": openapi_base_url,
            "prefix": openapi_prefix,
            "upstream_base_url": f"{openapi_base_url}/{openapi_prefix.strip('/')}",
            "legacy_base_url_used": False,
            "legacy_base_url_present": bool(legacy_base_url),
            "source": "openapi_base_url_prefix",
        }

    legacy_candidate = legacy_base_url or fallback_legacy_base_url
    if legacy_candidate:
        return {
            "base_url": openapi_base_url,
            "prefix": openapi_prefix,
            "upstream_base_url": legacy_candidate,
            "legacy_base_url_used": True,
            "legacy_base_url_present": True,
            "source": "legacy_dy_base_url",
        }

    return {
        "base_url": openapi_base_url,
        "prefix": openapi_prefix,
        "upstream_base_url": "",
        "legacy_base_url_used": False,
        "legacy_base_url_present": False,
        "source": "missing",
    }


def build_signed_openapi_request_body_and_headers(
    payload: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """构造与实际上游请求完全一致的 body、签名 header 和脱敏 debug。"""
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


def call_douyin_openapi(
    path: str,
    payload: dict[str, Any],
    timeout: float | None = None,
) -> dict[str, Any]:
    """调用抖音 OpenAPI，并返回原始 payload 与脱敏 debug。"""
    endpoint = openapi_endpoint_config()
    upstream_url = f"{endpoint['upstream_base_url']}/{path.strip('/')}"
    body_text, headers, debug = build_signed_openapi_request_body_and_headers(payload)
    debug.update(_request_debug(endpoint, upstream_url))
    started = time.perf_counter()
    resp: requests.Response | None = None

    try:
        resp = requests.post(
            upstream_url,
            data=body_text.encode("utf-8"),
            headers=headers,
            timeout=timeout or config.DY_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        upstream_payload = resp.json()
    except requests.RequestException as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        detail = build_safe_openapi_error_detail(
            resp=resp,
            payload=payload,
            headers=headers,
            debug=debug,
            error_code=_http_error_code(resp),
            error_type=type(exc).__name__,
            duration_ms=duration_ms,
        )
        _log_openapi_result(path, detail, success=False, duration_ms=duration_ms)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        detail = build_safe_openapi_error_detail(
            resp=resp,
            payload=payload,
            headers=headers,
            debug=debug,
            error_code="invalid_upstream_json",
            error_type=type(exc).__name__,
            duration_ms=duration_ms,
        )
        _log_openapi_result(path, detail, success=False, duration_ms=duration_ms)
        raise HTTPException(status_code=502, detail=detail) from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    if not isinstance(upstream_payload, dict):
        detail = build_safe_openapi_error_detail(
            resp=resp,
            payload=payload,
            headers=headers,
            debug=debug,
            error_code="invalid_upstream_response",
            error_type="InvalidUpstreamResponse",
            duration_ms=duration_ms,
        )
        detail["upstream_msg"] = "invalid upstream response"
        _log_openapi_result(path, detail, success=False, duration_ms=duration_ms)
        raise HTTPException(status_code=502, detail=detail)

    code = upstream_payload.get("code")
    if code != 0:
        detail = build_safe_openapi_error_detail(
            resp=resp,
            payload=payload,
            headers=headers,
            debug=debug,
            error_code="upstream_business_error",
            error_type="UpstreamBusinessError",
            upstream_payload=upstream_payload,
            duration_ms=duration_ms,
        )
        _log_openapi_result(path, detail, success=False, duration_ms=duration_ms)
        raise HTTPException(status_code=502, detail=detail)

    success_detail = {
        **debug,
        "error_code": None,
        "upstream_status": resp.status_code if resp is not None else None,
        "upstream_code": code,
        "upstream_msg": upstream_payload.get("msg") or upstream_payload.get("message"),
        "body_keys": _safe_body_keys(payload),
        "duration_ms": duration_ms,
    }
    _log_openapi_result(path, success_detail, success=True, duration_ms=duration_ms)
    return {"payload": upstream_payload, "debug": debug}


def build_safe_openapi_error_detail(
    *,
    resp: requests.Response | None,
    payload: dict[str, Any] | None,
    headers: dict[str, str] | None,
    debug: dict[str, Any] | None,
    error_code: str,
    error_type: str | None = None,
    upstream_payload: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    safe_message: str = SAFE_MESSAGE,
) -> dict[str, Any]:
    """生成不包含 secret、完整签名、完整 body/base64 的错误 detail。"""
    body = upstream_payload
    if body is None and resp is not None:
        try:
            parsed = resp.json()
        except ValueError:
            parsed = {}
        body = parsed if isinstance(parsed, dict) else {}

    upstream_status = resp.status_code if resp is not None else None
    signature = headers.get("Authorization") if headers else None
    timestamp = headers.get("X-Auth-Timestamp") if headers else None
    detail = {
        "safe_message": safe_message,
        "error_code": error_code,
        "error_type": error_type,
        "upstream_status": upstream_status,
        "upstream_code": body.get("code") if isinstance(body, dict) else None,
        "upstream_msg": (body.get("msg") or body.get("message")) if isinstance(body, dict) else None,
        "body_keys": _safe_body_keys(payload or {}),
        "timestamp_format": "unix_seconds" if timestamp and timestamp.isdigit() else "unknown",
        "authorization_preview": preview(signature),
        "signing_secret_config": "DY_GMP_SECRET_KEY",
        "signing_secret_configured": bool(config.DY_GMP_SECRET_KEY),
    }
    if duration_ms is not None:
        detail["duration_ms"] = duration_ms
    if debug:
        detail.update(
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
    return detail


def normalize_openapi_response(response_json: dict[str, Any]) -> dict[str, Any]:
    """保留给后续业务复用的响应规范化入口。"""
    if not isinstance(response_json, dict):
        raise DouyinOpenAPIResponseError("invalid_upstream_response")
    if response_json.get("code") != 0:
        raise DouyinOpenAPIUpstreamError("upstream_business_error")
    return response_json


def _request_debug(endpoint: dict[str, Any], upstream_url: str) -> dict[str, Any]:
    return {
        "upstream_url": upstream_url,
        "upstream_base_url": endpoint["upstream_base_url"],
        "openapi_base_url": endpoint["base_url"],
        "openapi_prefix": endpoint["prefix"],
        "legacy_base_url_used": endpoint["legacy_base_url_used"],
        "legacy_base_url_present": endpoint["legacy_base_url_present"],
        "openapi_config_source": endpoint["source"],
    }


def _safe_body_keys(payload: dict[str, Any]) -> list[str]:
    return sorted(key for key in payload.keys() if key.lower() not in SENSITIVE_PAYLOAD_KEYS)


def _http_error_code(resp: requests.Response | None) -> str:
    if resp is None:
        return "network_error"
    if resp.status_code == 403:
        return "auth_failed"
    if 500 <= resp.status_code:
        return "upstream_server_error"
    if 400 <= resp.status_code:
        return "upstream_http_error"
    return "network_error"


def _log_openapi_result(
    path: str,
    detail: dict[str, Any],
    *,
    success: bool,
    duration_ms: int,
) -> None:
    logger.info(
        "douyin_openapi_call path=%s upstream_url=%s success=%s status=%s upstream_code=%s duration_ms=%s body_keys=%s body_sha256=%s error_code=%s",
        path,
        detail.get("upstream_url"),
        success,
        detail.get("upstream_status"),
        detail.get("upstream_code"),
        duration_ms,
        detail.get("body_keys"),
        detail.get("body_sha256"),
        detail.get("error_code"),
    )
