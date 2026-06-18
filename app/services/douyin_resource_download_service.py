"""Manual-only Douyin OpenAPI resource download service."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.integrations.douyin_webhook import parse_content
from app.models import DouyinMessageResourceDownload, DouyinWebhookEvent
from app.services.douyin_live_check_service import call_douyin_openapi


ALLOWED_MEDIA_TYPES = {"image", "video"}


def download_douyin_resource(
    db: Session,
    *,
    conversation_short_id: str,
    server_message_id: str | None = None,
    open_id: str | None = None,
    media_type: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Download a Douyin media resource via signed OpenAPI."""
    conversation_short_id_text = (conversation_short_id or "").strip()
    if not conversation_short_id_text:
        raise HTTPException(status_code=400, detail="conversation_short_id is required")

    resolved = _resolve_context(
        db,
        conversation_short_id=conversation_short_id_text,
        server_message_id=server_message_id,
        open_id=open_id,
        media_type=media_type,
        url=url,
    )

    if resolved["media_type"] not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="media_type must be image or video")
    if not resolved["url"]:
        raise HTTPException(status_code=400, detail="resource_url_not_found")

    request_payload = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "conversation_id": conversation_short_id_text,
        "message_id": resolved["server_message_id"],
        "open_id": resolved["open_id"],
        "media_type": resolved["media_type"],
        "url": resolved["url"],
    }

    record = DouyinMessageResourceDownload(
        webhook_event_id=resolved["webhook_event_id"],
        main_account_id=config.DY_MAIN_ACCOUNT_ID,
        conversation_short_id=conversation_short_id_text,
        server_message_id=resolved["server_message_id"],
        open_id=resolved["open_id"],
        media_type=resolved["media_type"],
        source_url=resolved["url"],
        request_body_json=json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
        resource_status="pending",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(record)
    db.flush()

    try:
        result = call_douyin_openapi("/download_resource", request_payload)
    except HTTPException as exc:
        record.resource_status = "failed"
        record.error_message = _safe_message(exc.detail)
        record.response_body_json = json.dumps(_safe_detail(exc.detail), ensure_ascii=False, separators=(",", ":"))
        record.updated_at = datetime.now()
        db.commit()
        raise

    upstream_payload = result["payload"]
    data = upstream_payload.get("data") if isinstance(upstream_payload.get("data"), dict) else {}
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    download_url = _pick_download_url(upstream_payload, data, nested)
    err_no = _optional_str(data.get("err_no") or upstream_payload.get("err_no"))
    err_msg = _optional_str(data.get("err_msg") or upstream_payload.get("err_msg"))
    log_id = _optional_str(data.get("log_id") or upstream_payload.get("log_id"))

    if upstream_payload.get("code") != 0 or err_no not in (None, "0", 0):
        record.resource_status = "failed"
        record.upstream_err_no = err_no
        record.upstream_err_msg = err_msg
        record.upstream_log_id = log_id
        record.response_body_json = json.dumps(upstream_payload, ensure_ascii=False, separators=(",", ":"))
        record.error_message = err_msg or "resource download failed"
        record.updated_at = datetime.now()
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "upstream_status": 200,
                "upstream_code": upstream_payload.get("code"),
                "upstream_msg": upstream_payload.get("msg") or upstream_payload.get("message"),
                "safe_message": "资源下载失败，请人工处理",
            },
        )

    record.resource_status = "success"
    record.download_url = download_url
    record.upstream_err_no = err_no
    record.upstream_err_msg = err_msg
    record.upstream_log_id = log_id
    record.response_body_json = json.dumps(upstream_payload, ensure_ascii=False, separators=(",", ":"))
    record.downloaded_at = datetime.now()
    record.updated_at = datetime.now()
    db.commit()

    return {
        "resource_status": "success",
        "media_type": resolved["media_type"],
        "download_url": download_url,
        "conversation_short_id": conversation_short_id_text,
        "server_message_id": resolved["server_message_id"],
    }


def _resolve_context(
    db: Session,
    *,
    conversation_short_id: str,
    server_message_id: str | None,
    open_id: str | None,
    media_type: str | None,
    url: str | None,
) -> dict[str, Any]:
    row = None
    if server_message_id:
        row = (
            db.query(DouyinWebhookEvent)
            .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
            .filter(DouyinWebhookEvent.server_message_id == server_message_id)
            .filter(DouyinWebhookEvent.is_duplicate == 0)
            .first()
        )
    if row is None:
        row = (
            db.query(DouyinWebhookEvent)
            .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
            .filter(DouyinWebhookEvent.is_duplicate == 0)
            .order_by(DouyinWebhookEvent.message_create_time.desc(), DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
            .first()
        )
    if row is None:
        raise HTTPException(status_code=404, detail="resource context not found")

    content = _payload_content(row)
    resolved_media_type = _optional_str(media_type) or _media_type_from_content(row, content)
    resolved_url = _optional_str(url) or _resource_url_from_content(content)
    resolved_open_id = _optional_str(open_id) or _resource_open_id(row, content)
    if not resolved_media_type:
        raise HTTPException(status_code=400, detail="media_type is required")

    return {
        "webhook_event_id": row.id,
        "server_message_id": row.server_message_id,
        "open_id": resolved_open_id,
        "media_type": resolved_media_type,
        "url": resolved_url,
    }


def _payload_content(row: DouyinWebhookEvent) -> dict[str, Any]:
    if row.parsed_content_json:
        try:
            parsed = json.loads(row.parsed_content_json)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            return parsed
    try:
        raw = json.loads(row.raw_body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return parse_content(raw.get("content"))


def _media_type_from_content(row: DouyinWebhookEvent, content: dict[str, Any]) -> str | None:
    value = _optional_str(content.get("media_type") or content.get("message_type") or row.message_type)
    if value in ALLOWED_MEDIA_TYPES:
        return value
    if value == "user_local_image":
        return "image"
    if value == "user_local_video":
        return "video"
    return None


def _resource_url_from_content(content: dict[str, Any]) -> str | None:
    for key in ("url", "image_url", "video_url", "resource_url", "download_url"):
        value = _optional_str(content.get(key))
        if value:
            return value
    nested = content.get("resource")
    if isinstance(nested, dict):
        for key in ("url", "image_url", "video_url"):
            value = _optional_str(nested.get(key))
            if value:
                return value
    return None


def _resource_open_id(row: DouyinWebhookEvent, content: dict[str, Any]) -> str | None:
    return (
        _optional_str(content.get("open_id"))
        or _optional_str(content.get("customer_open_id"))
        or row.from_user_id
        or row.to_user_id
    )


def _pick_download_url(*payloads: dict[str, Any]) -> str | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("download_url", "url", "auth_url", "redirect_url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        nested = payload.get("data")
        if isinstance(nested, dict):
            for key in ("download_url", "url", "auth_url", "redirect_url"):
                value = nested.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _safe_detail(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    return {"detail": str(detail)}


def _safe_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return _optional_str(detail.get("safe_message") or detail.get("upstream_msg") or detail.get("detail")) or "resource download failed"
    return str(detail)
