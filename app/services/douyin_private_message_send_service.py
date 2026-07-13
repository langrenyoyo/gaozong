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
from app.models import DouyinAuthorizedAccount, DouyinPrivateMessageSend, DouyinWebhookEvent
from app.services.ai_auto_reply_content_sanitizer import sanitize_ai_reply_content
from app.services.conversation_autopilot_state_service import mark_manual_takeover
from app.services.forbidden_word_service import replace_forbidden_words
from app.services.douyin_merchant_isolation import require_douyin_account_for_merchant
from app.services.douyin_openapi_client import call_douyin_openapi
from app.services.douyin_workbench_conversation_service import get_send_msg_context


logger = logging.getLogger(__name__)

DEFAULT_SEND_SCENE = "im_reply_msg"

# send_source → 违禁词命中 source 固定映射；未知 send_source 拒绝发送（不再默认 manual）。
_FORBIDDEN_SOURCE_BY_SEND_SOURCE = {
    "manual": "douyin_manual",
    "ai_auto": "douyin_ai_auto",
    "return_visit_auto": "douyin_return_visit",
}


def send_manual_private_message(
    db: Session,
    *,
    merchant_id: str | None = None,
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
    if context is None and customer_open_id:
        conversation_context = get_send_msg_context(db, conversation_short_id=conversation_short_id)
        if conversation_context is not None:
            raise HTTPException(
                status_code=403,
                detail={"code": "DOUYIN_CONVERSATION_FORBIDDEN", "message": "无权访问该抖音账号、会话或资源"},
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
    require_douyin_account_for_merchant(
        db,
        merchant_id=merchant_id,
        account_open_id=context.get("account_open_id"),
        code="DOUYIN_ACCOUNT_FORBIDDEN",
    )

    result = _send_private_message_with_context(
        db,
        content=content_text,
        send_context=context,
        manual_confirmed=True,
        auto_send=False,
        send_source="manual",
        operator_id=operator_id,
    )
    _mark_manual_takeover_after_send(db, context)
    return result


def _send_private_message_with_context(
    db: Session,
    *,
    content: str,
    send_context: dict[str, Any],
    manual_confirmed: bool,
    auto_send: bool,
    send_source: str,
    operator_id: str | None = None,
    decision_log_id: int | None = None,
    auto_reply_run_id: int | None = None,
    return_visit_run_id: int | None = None,
) -> dict[str, Any]:
    """基于已校验的 send_msg context 发送私信，并写入统一发送流水。"""
    content_check = sanitize_ai_reply_content(content)
    if content_check.format_invalid:
        raise HTTPException(status_code=400, detail="llm_reply_json_parse_failed")
    content_text = (content_check.content or "").strip()
    if not content_text:
        raise HTTPException(status_code=400, detail="content must not be empty")
    if not send_context.get("conversation_id") or not send_context.get("msg_id"):
        raise HTTPException(status_code=400, detail="send_msg context missing conversation_id or msg_id")
    if _is_context_expired(send_context.get("message_create_time")):
        raise HTTPException(status_code=400, detail="send_msg context msg_id is older than 24 hours")

    context = send_context
    # send_source 固定白名单字典映射；未知 send_source 拒绝发送（不再默认 manual，防误判来源）。
    forbidden_source = _FORBIDDEN_SOURCE_BY_SEND_SOURCE.get(send_source)
    if forbidden_source is None:
        raise HTTPException(status_code=400, detail="unknown_send_source")
    # 违禁词替换：在 request_payload 构造前替换 content_text，使上游 payload、
    # 发送流水 content、request_body_json 三处同步为安全词；命中只替换不拦截。
    replacement = replace_forbidden_words(
        db,
        merchant_id=_resolve_merchant_id_for_account(db, context["account_open_id"]) or "unknown_merchant",
        source=forbidden_source,
        content=content_text,
        context={
            "context_type": "douyin_conversation",
            "context_id": context.get("conversation_short_id"),
            "conversation_short_id": context.get("conversation_short_id"),
        },
    )
    content_text = replacement.final_content
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
        manual_confirmed=1 if manual_confirmed else 0,
        auto_send=1 if auto_send else 0,
        decision_log_id=decision_log_id,
        auto_reply_run_id=auto_reply_run_id,
        return_visit_run_id=return_visit_run_id,
        send_source=send_source,
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
        "auto_send": bool(auto_send),
        "manual_confirmed": bool(manual_confirmed),
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


def _mark_manual_takeover_after_send(db: Session, context: dict[str, Any]) -> None:
    account_open_id = _optional_str(context.get("account_open_id"))
    conversation_short_id = _optional_str(context.get("conversation_short_id"))
    customer_open_id = _optional_str(context.get("customer_open_id"))
    if not account_open_id or not conversation_short_id:
        logger.warning(
            "manual_takeover_skip stage=manual_send_success reason=missing_context account_open_id_sha8=%s conversation_sha8=%s",
            _hash_prefix(account_open_id),
            _hash_prefix(conversation_short_id),
        )
        return

    merchant_id = _resolve_merchant_id_for_account(db, account_open_id) or "unknown_merchant"
    mark_manual_takeover(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
    )


def _resolve_merchant_id_for_account(db: Session, account_open_id: str) -> str | None:
    account = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id)
        .filter(DouyinAuthorizedAccount.bind_status == 1)
        .order_by(DouyinAuthorizedAccount.id.desc())
        .first()
    )
    return _optional_str(account.merchant_id) if account is not None else None


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
