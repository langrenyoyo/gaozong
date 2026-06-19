"""Manual-only Douyin OpenAPI private-message sending."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import DouyinPrivateMessageSend, DouyinWebhookEvent
from app.services.douyin_openapi_client import call_douyin_openapi
from app.services.douyin_workbench_conversation_service import get_send_msg_context


logger = logging.getLogger(__name__)

DEFAULT_SEND_SCENE = "im_reply_msg"


def send_manual_private_message(
    db: Session,
    *,
    conversation_short_id: str,
    content: str,
    customer_open_id: str | None = None,
    scene: str | None = None,
    manual_confirmed: bool,
    operator_id: str | None = None,
) -> dict[str, Any]:
    """Send one text private message only after explicit manual confirmation."""
    if manual_confirmed is not True:
        raise HTTPException(status_code=400, detail="manual_confirmed must be true before sending")

    content_text = (content or "").strip()
    if not content_text:
        raise HTTPException(status_code=400, detail="content must not be empty")

    context = get_send_msg_context(
        db,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
    )
    if context is None:
        # 缺少可回复前置事件（如该会话只剩 im_send_msg 企业号发出消息）：不调用上游，
        # 返回稳定错误码，便于前端识别为「缺少可回复上下文，勿重试」。
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "send_context_unavailable",
                "message": "send_msg context not found：缺少可回复的前置私信上下文，请引导客户重新发消息",
            },
        )
    if not context.get("conversation_id") or not context.get("msg_id"):
        raise HTTPException(status_code=400, detail="send_msg context missing conversation_id or msg_id")
    if _is_context_expired(context.get("message_create_time")):
        raise HTTPException(status_code=400, detail="send_msg context msg_id is older than 24 hours")

    # scene 由后端根据命中事件类型严格推导，不信任前端传入的 scene：
    # im_receive_msg → im_reply_msg；im_enter_direct_msg → im_enter_direct_msg。
    send_scene = _default_scene(context)
    request_payload = {
        "main_account_id": config.DY_MAIN_ACCOUNT_ID,
        "scene": send_scene,
        "content": content_text,
        "msg_id": context["msg_id"],
        "conversation_id": context["conversation_id"],
        "to_user_id": context["customer_open_id"],
        "from_user_id": context["account_open_id"],
    }

    # 脱敏诊断日志：调用上游前记录命中事件类型与派生 scene；禁止记录明文 open_id /
    # message_id / conversation_id / secret / 完整 body / Authorization。
    excluded_im_send_msg_count = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.conversation_short_id == context["conversation_short_id"])
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .filter(DouyinWebhookEvent.event == "im_send_msg")
        .count()
    )
    logger.info(
        "send_msg 准备调用上游: event_type=%s, scene=%s, conversation_short_id_sha8=%s, "
        "server_message_id_sha8=%s, participants_same_event=True, excluded_im_send_msg=%s",
        context.get("scene"),
        send_scene,
        _hash_prefix(context.get("conversation_short_id")),
        _hash_prefix(context.get("server_message_id")),
        excluded_im_send_msg_count,
    )

    record = DouyinPrivateMessageSend(
        main_account_id=config.DY_MAIN_ACCOUNT_ID,
        conversation_short_id=context["conversation_short_id"],
        server_message_id=context["server_message_id"],
        from_user_id=context["account_open_id"],
        to_user_id=context["customer_open_id"],
        customer_open_id=context["customer_open_id"],
        account_open_id=context["account_open_id"],
        scene=send_scene,
        content=content_text,
        request_body_json=json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
        status="pending",
        manual_confirmed=1,
        auto_send=0,
        operator_id=operator_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(record)
    db.flush()

    try:
        result = call_douyin_openapi("/send_msg", request_payload)
    except HTTPException as exc:
        record.status = "failed"
        record.error_code = _error_code(exc.detail)
        record.error_message = _error_message(exc.detail)
        record.response_body_json = json.dumps(_safe_detail(exc.detail), ensure_ascii=False, separators=(",", ":"))
        record.updated_at = datetime.now()
        db.commit()
        raise

    upstream_payload = result["payload"]
    data = upstream_payload.get("data") if isinstance(upstream_payload.get("data"), dict) else {}
    upstream_msg_id = _optional_str(data.get("msg_id") or data.get("server_message_id"))

    record.status = "sent"
    record.response_body_json = json.dumps(upstream_payload, ensure_ascii=False, separators=(",", ":"))
    record.upstream_msg_id = upstream_msg_id
    record.sent_at = datetime.now()
    record.updated_at = datetime.now()
    db.commit()

    return {
        "record_id": record.id,
        "status": record.status,
        "upstream_msg_id": upstream_msg_id,
        "conversation_short_id": context["conversation_short_id"],
        "to_user_id": context["customer_open_id"],
        "from_user_id": context["account_open_id"],
        "scene": send_scene,
        "auto_send": False,
        "manual_confirmed": True,
    }


def _default_scene(context: dict[str, Any]) -> str:
    if context.get("scene") == "im_enter_direct_msg":
        return "im_enter_direct_msg"
    return DEFAULT_SEND_SCENE


def _hash_prefix(value: Any) -> str:
    """记录字段 sha256 前 8 位用于脱敏诊断；禁止记录明文 open_id / message_id / conversation_id。"""
    if value is None:
        return "none"
    text = str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8] if text else "none"


def _is_context_expired(message_create_time: Any) -> bool:
    if not isinstance(message_create_time, datetime):
        return False
    return datetime.now() - message_create_time > timedelta(hours=24)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _safe_detail(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    return {"detail": str(detail)}


def _error_code(detail: Any) -> str | None:
    if isinstance(detail, dict):
        code = detail.get("upstream_code") or detail.get("error_type")
        return _optional_str(code)
    return None


def _error_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return _optional_str(detail.get("upstream_msg") or detail.get("safe_message")) or "send failed"
    return str(detail)
