"""Manual-only Douyin OpenAPI private-message sending."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import DouyinAuthorizedAccount, DouyinPrivateMessageSend, DouyinWebhookEvent
from app.services.ai_auto_reply_content_sanitizer import sanitize_ai_reply_content
from app.services.conversation_autopilot_state_service import mark_manual_takeover
from app.services.douyin_gmp_authorization_health import (
    GMP_ACCOUNT_SCOPE_MISMATCH_CODE,
    GMP_ACCOUNT_SCOPE_MISMATCH_MESSAGE,
    GMP_AUTH_STATUS_REAUTH_REQUIRED,
    GMP_REAUTH_ERROR_ACTION,
    GMP_REAUTH_ERROR_CODE,
    GMP_REAUTH_ERROR_MESSAGE,
    GMP_SEND_MSG_PATH,
    classify_gmp_reauth_required,
    gmp_authorization_health_enabled,
    mark_reauth_required,
    record_send_success,
)
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
    "contact_invalid_followup": "douyin_contact_invalid_followup",
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
        merchant_id=merchant_id or "",
        content=content_text,
        send_context=context,
        manual_confirmed=True,
        auto_send=False,
        send_source="manual",
        operator_id=operator_id,
    )
    _mark_manual_takeover_after_send(db, context, merchant_id=merchant_id)
    return result


def _send_private_message_with_context(
    db: Session,
    *,
    merchant_id: str,
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
    """基于已校验的 send_msg context 发送私信，并写入统一发送流水。

    P0.5-DOUYIN-GMP-AUTHORIZATION-LIFECYCLE：merchant_id 为必填可信来源
    （RequestContext / 已持久化 run/task 字段），按 merchant_id + main_account_id +
    account_open_id + bind_status=1 定位账号；发送后不再反查商户。
    """
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
    # P0.5：可信账号定位（merchant_id + DY_MAIN_ACCOUNT_ID + account_open_id + bind_status=1）。
    # 定位失败：不建流水、不更新账号、不调 GMP；禁止按 account_open_id 跨商户兜底。
    send_account = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.merchant_id == merchant_id,
            DouyinAuthorizedAccount.main_account_id == config.DY_MAIN_ACCOUNT_ID,
            DouyinAuthorizedAccount.open_id == _optional_str(context.get("account_open_id")),
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .first()
    )
    if send_account is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": GMP_ACCOUNT_SCOPE_MISMATCH_CODE,
                "message": GMP_ACCOUNT_SCOPE_MISMATCH_MESSAGE,
            },
        )
    # P0.5：非 PG（开发 SQLite）禁用授权健康——跳过预阻断与健康写入，其余发送门禁不变。
    health_enabled = gmp_authorization_health_enabled()
    attempt_version = int(send_account.authorization_version or 0) if health_enabled else 0
    auth_status = send_account.authorization_status if health_enabled else None

    # 本地预阻断：REAUTH_REQUIRED 且开关为 true → 写 failed 流水 + 固定 409 合同，不调用 GMP。
    if health_enabled and config.DOUYIN_GMP_AUTH_LOCAL_BLOCK_ENABLED and auth_status == GMP_AUTH_STATUS_REAUTH_REQUIRED:
        _insert_blocked_send_record(
            db,
            context=context,
            manual_confirmed=manual_confirmed,
            auto_send=auto_send,
            send_source=send_source,
            operator_id=operator_id,
            decision_log_id=decision_log_id,
            auto_reply_run_id=auto_reply_run_id,
            return_visit_run_id=return_visit_run_id,
            content_text=content_text,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": GMP_REAUTH_ERROR_CODE,
                "message": GMP_REAUTH_ERROR_MESSAGE,
                "action": GMP_REAUTH_ERROR_ACTION,
            },
        )
    # send_source 固定白名单字典映射；未知 send_source 拒绝发送（不再默认 manual，防误判来源）。
    forbidden_source = _FORBIDDEN_SOURCE_BY_SEND_SOURCE.get(send_source)
    if forbidden_source is None:
        raise HTTPException(status_code=400, detail="unknown_send_source")
    # 违禁词处理方案（G1-DELTA 后冻结）：人工私信保留原文发送，不替换、不阻断；
    # 自动回复（auto_send=True）的违禁词由 9100 生成后确定性检查并阻断转人工。
    # 回访话术的发送前检测由 return_visit_run_service 在调用本函数前完成。
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
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
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
        result = call_douyin_openapi(GMP_SEND_MSG_PATH, request_payload)
    except HTTPException as exc:
        # P0.5：事故精确指纹命中 → 按授权代际条件标记失效（rowcount=0 放弃覆盖新状态），
        # 流水写 failed + 固定安全文案 + response_body_json=NULL，抛 409 固定三键合同。
        if health_enabled and classify_gmp_reauth_required(GMP_SEND_MSG_PATH, exc.detail):
            mark_reauth_required(
                db,
                account_id=send_account.id,
                attempt_version=attempt_version,
                now=datetime.now(timezone.utc),
            )
            record.status = "failed"
            record.error_code = GMP_REAUTH_ERROR_CODE
            record.error_message = GMP_REAUTH_ERROR_MESSAGE
            record.response_body_json = None
            record.updated_at = datetime.now()
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": GMP_REAUTH_ERROR_CODE,
                    "message": GMP_REAUTH_ERROR_MESSAGE,
                    "action": GMP_REAUTH_ERROR_ACTION,
                },
            )
        # 未命中指纹 → 维持现有 upstream_business_error 行为不变，不更新授权状态。
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

    # P0.5：成功发送单调更新（last_success_at 单调取大；仅 UNKNOWN→AUTHORIZED，永不走 REAUTH→AUTHORIZED）。
    if health_enabled:
        record_send_success(db, account_id=send_account.id)
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


def _insert_blocked_send_record(
    db: Session,
    *,
    context: dict[str, Any],
    manual_confirmed: bool,
    auto_send: bool,
    send_source: str,
    operator_id: str | None,
    decision_log_id: int | None,
    auto_reply_run_id: int | None,
    return_visit_run_id: int | None,
    content_text: str,
) -> None:
    """REAUTH_REQUIRED 本地预阻断流水（冻结合同）：status=failed + error_code +
    error_message 固定安全文案 + response_body_json=NULL；不调用 GMP、不重试。"""
    send_scene = _default_scene(context)
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
        status="failed",
        error_code=GMP_REAUTH_ERROR_CODE,
        error_message=GMP_REAUTH_ERROR_MESSAGE,
        response_body_json=None,
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
    db.commit()


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
    # message_create_time 可能是 aware（PostgreSQL DateTime(timezone=True) 列）
    # 或 naive（SQLite / 上游毫秒转本地时间）。datetime.now() 是 naive，
    # naive - aware 会触发 TypeError。按对端时区特性取同基准 now，避免混用。
    if message_create_time.tzinfo:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.now()
    return now - message_create_time > timedelta(hours=24)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _mark_manual_takeover_after_send(db: Session, context: dict[str, Any], *, merchant_id: str | None) -> None:
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

    # P0.5：merchant_id 由调用方可信传入（RequestContext），不再按 account_open_id 发送后反查商户。
    mark_manual_takeover(
        db,
        merchant_id=merchant_id or "unknown_merchant",
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
    )


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
