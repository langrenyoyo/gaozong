"""抖音 AI 自动回复真实发送服务。"""

from __future__ import annotations

import logging
import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AiAutoReplyRun, AiReplyDecisionLog, DouyinPrivateMessageSend
from app.services.ai_auto_reply_content_sanitizer import sanitize_ai_reply_content
from app.services.conversation_autopilot_state_service import (
    evaluate_manual_takeover_gate,
    mark_ai_replied,
)
from app.services.douyin_autoreply_settings_service import get_account_autoreply_settings
from app.services.douyin_autoreply_gate_service import evaluate_real_send_gates
from app.services.douyin_private_message_send_service import (
    _is_context_expired,
    _send_private_message_with_context,
)
from app.services.douyin_workbench_conversation_service import (
    get_latest_private_message_state,
    get_send_msg_context,
)


logger = logging.getLogger(__name__)


def send_ai_auto_reply_for_run(db: Session, *, run_id: int) -> dict[str, Any]:
    """按 run 执行一次 AI 自动回复真实发送；所有失败路径均不重试。"""
    run = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).first()
    if run is None:
        return {"status": "skipped", "reason": "run_not_found"}
    if run.status != "decided":
        return {"status": "skipped", "reason": "run_not_decided"}
    if run.mode != "real_send_candidate":
        _mark_send_skipped(db, run, "dry_run_mode")
        logger.info(
            "ai_auto_reply_send_skipped stage=mode_check run_id=%s reason=dry_run_mode mode=%s account_open_id_sha8=%s",
            run.id,
            run.mode,
            _hash_prefix(run.account_open_id),
        )
        return {"status": "send_skipped", "reason": "dry_run_mode"}
    if not _decision_allows_auto_send(db, run):
        _mark_send_skipped(db, run, "auto_send_disabled_by_decision")
        logger.info(
            "ai_auto_reply_send_skipped stage=decision_gate run_id=%s reason=auto_send_disabled_by_decision "
            "decision_log_id=%s",
            run.id,
            run.decision_log_id,
        )
        return {"status": "send_skipped", "reason": "auto_send_disabled_by_decision"}

    existing_send = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.auto_reply_run_id == run.id)
        .first()
    )
    if existing_send is not None:
        _mark_send_skipped(db, run, "already_sent")
        logger.info("ai_auto_reply_send_skipped stage=dedupe run_id=%s reason=already_sent", run.id)
        return {"status": "send_skipped", "reason": "already_sent", "record_id": existing_send.id}

    content_check = sanitize_ai_reply_content(run.would_send_content)
    if content_check.format_invalid:
        _mark_format_invalid(db, run, content_check.reason or "llm_reply_json_parse_failed")
        logger.warning(
            "ai_auto_reply_send_skipped stage=content_format run_id=%s reason=format_invalid failure_stage=reply_content_sanitize",
            run.id,
        )
        return {"status": "send_skipped", "reason": "format_invalid"}

    content = (content_check.content or "").strip()
    if not content:
        _mark_send_skipped(db, run, "empty_content")
        logger.info("ai_auto_reply_send_skipped stage=content_check run_id=%s reason=empty_content", run.id)
        return {"status": "send_skipped", "reason": "empty_content"}
    if content != (run.would_send_content or "").strip():
        run.would_send_content = content
        run.updated_at = datetime.now()
        db.commit()

    settings = get_account_autoreply_settings(
        db,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id,
    )
    real_send_gate = evaluate_real_send_gates(
        db,
        settings=settings,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id,
        customer_open_id=run.customer_open_id,
        conversation_short_id=run.conversation_short_id,
    )
    if not real_send_gate.passed:
        _merge_run_gate_results(
            db,
            run,
            "real_send",
            {
                **(real_send_gate.gate_results or {}),
                "send_gate_passed": False,
                "blocked_reason": real_send_gate.reason,
            },
        )
        _mark_send_skipped(db, run, real_send_gate.reason or "real_send_gate_blocked")
        logger.info(
            "ai_auto_reply_gate_blocked stage=real_send_gate run_id=%s account_open_id_sha8=%s "
            "blocked_by=%s send_enabled=%s",
            run.id,
            _hash_prefix(run.account_open_id),
            real_send_gate.reason,
            _settings_send_enabled(real_send_gate.gate_results),
        )
        return {"status": "send_skipped", "reason": real_send_gate.reason}

    _merge_run_gate_results(
        db,
        run,
        "real_send",
        {
            **(real_send_gate.gate_results or {}),
            "send_gate_passed": True,
        },
    )

    manual_takeover = evaluate_manual_takeover_gate(
        db,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id,
        conversation_short_id=run.conversation_short_id or "",
    )
    _merge_run_gate_results(db, run, "real_send", {"manual_takeover": manual_takeover})
    if manual_takeover.get("blocked") is True:
        _mark_send_skipped(db, run, "manual_takeover_blocked")
        logger.info("ai_auto_reply_send_skipped stage=manual_takeover run_id=%s reason=manual_takeover_blocked", run.id)
        return {"status": "send_skipped", "reason": "manual_takeover_blocked"}

    latest_state = get_latest_private_message_state(
        db,
        account_open_id=run.account_open_id,
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
        trigger_server_message_id=run.trigger_server_message_id,
    )
    if latest_state.get("has_outbound_after_trigger") is True:
        _mark_send_skipped(db, run, "outbound_after_trigger")
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=outbound_after_trigger", run.id)
        return {"status": "send_skipped", "reason": "outbound_after_trigger"}
    if latest_state.get("latest_is_customer_message") is not True:
        _mark_send_skipped(db, run, "latest_message_not_customer")
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=latest_message_not_customer", run.id)
        return {"status": "send_skipped", "reason": "latest_message_not_customer"}
    if latest_state.get("latest_server_message_id") != run.trigger_server_message_id:
        _mark_send_skipped(db, run, "latest_message_changed")
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=latest_message_changed", run.id)
        return {"status": "send_skipped", "reason": "latest_message_changed"}

    send_context = get_send_msg_context(
        db,
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
    )
    if send_context is None:
        _mark_send_skipped(db, run, "send_context_unavailable")
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_unavailable", run.id)
        return {"status": "send_skipped", "reason": "send_context_unavailable"}
    if send_context.get("server_message_id") != run.trigger_server_message_id:
        _mark_send_skipped(db, run, "send_context_message_changed")
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_message_changed", run.id)
        return {"status": "send_skipped", "reason": "send_context_message_changed"}
    if send_context.get("account_open_id") != run.account_open_id:
        _mark_send_skipped(db, run, "send_context_account_mismatch")
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_account_mismatch", run.id)
        return {"status": "send_skipped", "reason": "send_context_account_mismatch"}
    if send_context.get("customer_open_id") != run.customer_open_id:
        _mark_send_skipped(db, run, "send_context_customer_mismatch")
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_customer_mismatch", run.id)
        return {"status": "send_skipped", "reason": "send_context_customer_mismatch"}
    if _is_context_expired(send_context.get("message_create_time")):
        _mark_send_skipped(db, run, "context_expired")
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=context_expired", run.id)
        return {"status": "send_skipped", "reason": "context_expired"}

    try:
        send_result = _send_private_message_with_context(
            db,
            content=content,
            send_context=send_context,
            manual_confirmed=False,
            auto_send=True,
            send_source="ai_auto",
            operator_id="ai_auto_reply",
            decision_log_id=run.decision_log_id,
            auto_reply_run_id=run.id,
        )
    except HTTPException as exc:
        run.status = "send_failed"
        run.error_message = _safe_error(exc.detail)
        run.updated_at = datetime.now()
        db.commit()
        logger.warning(
            "ai_auto_reply_send_failed stage=send_msg run_id=%s reason=send_msg_failed error_type=%s",
            run.id,
            type(exc).__name__,
        )
        return {"status": "send_failed", "reason": "send_msg_failed"}

    _sync_final_auto_send_after_success(db, run)
    run.status = "sent"
    run.block_reason = None
    run.skip_reason = None
    run.error_message = None
    run.updated_at = datetime.now()
    db.commit()
    mark_ai_replied(
        db,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id,
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
    )
    return {"status": "sent", "record_id": send_result.get("record_id")}


def _mark_send_skipped(db: Session, run: AiAutoReplyRun, reason: str) -> None:
    run.status = "send_skipped"
    run.block_reason = reason
    run.updated_at = datetime.now()
    db.commit()


def _mark_format_invalid(db: Session, run: AiAutoReplyRun, error_message: str) -> None:
    run.status = "send_skipped"
    run.block_reason = "format_invalid"
    run.error_message = error_message
    run.updated_at = datetime.now()
    db.commit()


def _sync_final_auto_send_after_success(db: Session, run: AiAutoReplyRun) -> None:
    """发送成功后以真实发送结果为准，同步 run 快照和决策日志。"""
    gate_results = _json_object(run.gate_results_json)
    post_llm = gate_results.get("post_llm")
    if not isinstance(post_llm, dict):
        post_llm = {}
    post_llm["final_auto_send"] = True
    gate_results["post_llm"] = post_llm
    run.gate_results_json = json.dumps(gate_results, ensure_ascii=False, separators=(",", ":"))

    if run.decision_log_id:
        decision = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).first()
        if decision is not None:
            decision.final_auto_send = 1

    logger.info(
        "ai_auto_reply_send_finalized stage=send_success run_id=%s decision_log_id=%s final_auto_send=True",
        run.id,
        run.decision_log_id,
    )


def _merge_run_gate_results(db: Session, run: AiAutoReplyRun, section: str, value: dict[str, Any]) -> None:
    gate_results = _json_object(run.gate_results_json)
    current = gate_results.get(section)
    if not isinstance(current, dict):
        current = {}
    current.update(value)
    gate_results[section] = current
    run.gate_results_json = json.dumps(gate_results, ensure_ascii=False, separators=(",", ":"), default=str)
    db.commit()


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _decision_allows_auto_send(db: Session, run: AiAutoReplyRun) -> bool:
    if not run.decision_log_id:
        return False
    decision = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).first()
    return bool(decision is not None and decision.final_auto_send == 1)


def _safe_error(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("upstream_msg") or detail.get("safe_message") or detail.get("detail") or "send failed")
    return str(detail)


def _hash_prefix(value: str | None) -> str:
    """记录字段哈希前 8 位，避免日志输出 open_id 明文。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _settings_send_enabled(gate_results: dict[str, Any] | None) -> bool | None:
    """从门禁结果里提取 send_enabled 摘要，避免记录完整白名单。"""
    if not isinstance(gate_results, dict):
        return None
    settings = gate_results.get("settings")
    if not isinstance(settings, dict) or settings.get("exists") is not True:
        return None
    return bool(settings.get("send_enabled"))
