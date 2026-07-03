"""抖音 OpenAPI 图片上传服务。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from pathlib import PurePath
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import DouyinImageUpload
from app.services.douyin_merchant_isolation import require_customer_open_id_for_merchant
from app.services.douyin_openapi_client import call_douyin_openapi


MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
}


def upload_douyin_image(
    db: Session,
    *,
    merchant_id: str | None = None,
    file_name: str,
    image_base64: str,
    open_id: str | None = None,
) -> dict[str, Any]:
    """上传单张图片到抖音 OpenAPI，只持久化脱敏元数据。"""
    normalized = _validate_image(file_name=file_name, image_base64=image_base64)
    request_payload: dict[str, Any] = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "image_base64": normalized["image_base64"],
        "file_name": normalized["file_name"],
    }
    normalized_open_id = _optional_str(open_id)
    if normalized_open_id:
        require_customer_open_id_for_merchant(
            db,
            merchant_id=merchant_id,
            customer_open_id=normalized_open_id,
            code="DOUYIN_RESOURCE_FORBIDDEN",
        )
    if normalized_open_id:
        request_payload["open_id"] = normalized_open_id

    record = DouyinImageUpload(
        main_account_id=config.DY_MAIN_ACCOUNT_ID,
        open_id=normalized_open_id,
        file_name=normalized["file_name"],
        file_ext=normalized["file_ext"],
        mime_type=normalized["mime_type"],
        file_size_bytes=normalized["file_size_bytes"],
        local_md5=normalized["local_md5"],
        image_base64_sha256=normalized["image_base64_sha256"],
        upload_status="pending",
        request_body_json=json.dumps(
            _sanitized_request_body(request_payload, normalized),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(record)
    db.flush()

    try:
        result = call_douyin_openapi("/upload_image_file", request_payload)
    except HTTPException as exc:
        _mark_failed(record, _safe_detail(exc.detail), _safe_message(exc.detail))
        db.commit()
        raise

    upstream_payload = result["payload"]
    data = upstream_payload.get("data") if isinstance(upstream_payload.get("data"), dict) else {}
    image_id = _optional_str(data.get("image_id"))
    record.upstream_code = _optional_str(upstream_payload.get("code"))
    record.upstream_msg = _optional_str(upstream_payload.get("msg") or upstream_payload.get("message"))
    record.response_body_json = json.dumps(upstream_payload, ensure_ascii=False, separators=(",", ":"))

    if not image_id:
        record.upload_status = "failed"
        record.error_message = "missing data.image_id"
        record.updated_at = datetime.now()
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "upstream_status": 200,
                "upstream_code": upstream_payload.get("code"),
                "upstream_msg": upstream_payload.get("msg") or upstream_payload.get("message"),
                "safe_message": "图片上传失败，上游响应中没有 image_id",
                "error_type": "MissingImageId",
            },
        )

    record.upload_status = "success"
    record.upstream_image_id = image_id
    record.upstream_width = _int_or_none(data.get("width"))
    record.upstream_height = _int_or_none(data.get("height"))
    record.upstream_md5 = _optional_str(data.get("md5"))
    record.uploaded_at = datetime.now()
    record.updated_at = datetime.now()
    db.commit()

    return {
        "record_id": record.id,
        "upload_status": "success",
        "image_id": image_id,
        "width": record.upstream_width,
        "height": record.upstream_height,
        "md5": record.upstream_md5,
        "file_name": record.file_name,
        "file_ext": record.file_ext,
        "mime_type": record.mime_type,
        "file_size_bytes": record.file_size_bytes,
    }


def _validate_image(*, file_name: str, image_base64: str) -> dict[str, Any]:
    normalized_file_name = _safe_file_name(file_name)
    raw_base64 = _strip_data_url_prefix(image_base64)
    if not raw_base64:
        raise HTTPException(status_code=400, detail="image_base64 must not be empty")

    file_ext = _file_ext(normalized_file_name)
    if file_ext not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="invalid_image_type")

    try:
        image_bytes = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="image_base64 is not valid base64") from exc

    if not image_bytes:
        raise HTTPException(status_code=400, detail="image bytes must not be empty")
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="image file must be <= 10MB")

    detected_ext = _detect_image_ext(image_bytes)
    if detected_ext is None:
        raise HTTPException(status_code=400, detail="invalid_image_type")
    if not _extension_matches(file_ext, detected_ext):
        raise HTTPException(status_code=400, detail="image extension does not match file header")

    local_md5 = hashlib.md5(image_bytes).hexdigest()
    return {
        "file_name": normalized_file_name,
        "file_ext": file_ext,
        "mime_type": ALLOWED_IMAGE_TYPES[file_ext],
        "file_size_bytes": len(image_bytes),
        "local_md5": local_md5,
        "image_base64_sha256": hashlib.sha256(raw_base64.encode("utf-8")).hexdigest(),
        "image_base64": raw_base64,
    }


def _safe_file_name(file_name: str) -> str:
    text = (file_name or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="file_name must not be empty")
    name = PurePath(text).name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="file_name must be a file name")
    return name


def _strip_data_url_prefix(image_base64: str) -> str:
    text = (image_base64 or "").strip()
    if "," in text and text.lower().startswith("data:"):
        return text.split(",", 1)[1].strip()
    return text


def _file_ext(file_name: str) -> str:
    suffix = PurePath(file_name).suffix.lower().lstrip(".")
    return "jpg" if suffix == "jpe" else suffix


def _detect_image_ext(image_bytes: bytes) -> str | None:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if image_bytes.startswith(b"\x89PNG"):
        return "png"
    if image_bytes.startswith(b"BM"):
        return "bmp"
    if len(image_bytes) >= 12 and image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "webp"
    return None


def _extension_matches(file_ext: str, detected_ext: str) -> bool:
    if detected_ext == "jpg":
        return file_ext in {"jpg", "jpeg"}
    return file_ext == detected_ext


def _sanitized_request_body(
    request_payload: dict[str, Any],
    normalized: dict[str, Any],
) -> dict[str, Any]:
    return {
        "main_account_id": request_payload.get("main_account_id"),
        "file_name": normalized["file_name"],
        "open_id": request_payload.get("open_id"),
        "file_ext": normalized["file_ext"],
        "mime_type": normalized["mime_type"],
        "file_size_bytes": normalized["file_size_bytes"],
        "local_md5": normalized["local_md5"],
        "image_base64_sha256": normalized["image_base64_sha256"],
    }


def _mark_failed(record: DouyinImageUpload, detail: dict[str, Any], message: str) -> None:
    record.upload_status = "failed"
    record.upstream_code = _optional_str(detail.get("upstream_code"))
    record.upstream_msg = _optional_str(detail.get("upstream_msg"))
    record.error_message = message
    record.response_body_json = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    record.updated_at = datetime.now()


def _safe_detail(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    return {"detail": str(detail)}


def _safe_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return _optional_str(detail.get("upstream_msg") or detail.get("safe_message") or detail.get("detail")) or "image upload failed"
    return str(detail)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
