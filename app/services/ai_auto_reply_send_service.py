"""抖音 AI 自动回复真实发送服务。"""

from __future__ import annotations

import logging
import hashlib
import json
import time as _time
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app import config
from app.models import AiAutoReplyRun, AiReplyDecisionLog, DouyinPrivateMessageSend
from app.services.ai_auto_reply_outbox_service import (
    _expected_lease_owner,
    _guarded_lease_update,
    _set_outbox_lease_owner,
)
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


def _checkpoint(db: Session, run: AiAutoReplyRun, *, expected_status: str, status: str) -> int:
    """状态机检查点推进：单条原子 guarded UPDATE。

    outbox 路径强制原始 owner + 租约未过期 + expected_status + 检查点续租；
    非 outbox 路径校验 lease_owner == run.lease_owner（兼容无租约直调）。
    返回 rowcount；0 表示未推进（租约丢失/过期/状态不符），调用方必须终止且不得覆盖恢复器或新 Worker 状态。
    """
    now = datetime.now()
    owner = _expected_lease_owner()
    update_values: dict[str, Any] = {"status": status, "updated_at": now}
    if owner:
        return _guarded_lease_update(
            db, run.id, expected_status=expected_status,
            values=update_values, refresh_lease=True,
        )
    # 非 outbox：原条件更新
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id == run.id,
            AiAutoReplyRun.status == expected_status,
            AiAutoReplyRun.lease_owner == run.lease_owner,
        )
        .values(**update_values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount


def _terminal(
    db: Session,
    run: AiAutoReplyRun,
    *,
    expected_status: str,
    status: str,
    block_reason: str | None = None,
    error_message: str | None = None,
    last_failure_stage: str | None = None,
    gate_results_json: str | None = None,
) -> int:
    """终态写入：单条原子 guarded UPDATE，同时写状态、诊断字段并清理租约。

    outbox 路径 WHERE expected_status + 原始 owner + 租约未过期，一次性写入 status/诊断/清租约，
    消除"先续租再 ORM 提交"和 SQLAlchemy auto flush 在 guard 返回 0 前提交脏数据的问题。
    返回 rowcount；0 表示租约已丢失，调用方不得覆盖、不得再触发 mark_ai_replied 等副作用。
    非 outbox 路径走原子条件更新，返回 rowcount（兼容无租约直调，状态不符返回 0）。
    """
    now = datetime.now()
    update_values: dict[str, Any] = {
        "status": status,
        "lease_owner": None,
        "lease_expires_at": None,
        "updated_at": now,
    }
    if block_reason is not None:
        update_values["block_reason"] = block_reason
    if error_message is not None:
        update_values["error_message"] = error_message
    if last_failure_stage is not None:
        update_values["last_failure_stage"] = last_failure_stage
    if gate_results_json is not None:
        update_values["gate_results_json"] = gate_results_json
    owner = _expected_lease_owner()
    if owner:
        return _guarded_lease_update(
            db, run.id, expected_status=expected_status, values=update_values,
        )
    # 非 outbox：原子条件更新（expected_status + lease_owner == run.lease_owner）
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id == run.id,
            AiAutoReplyRun.status == expected_status,
            AiAutoReplyRun.lease_owner == run.lease_owner,
        )
        .values(**update_values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount


def send_ai_auto_reply_for_run(db: Session, *, run_id: int, lease_owner: str = "") -> dict[str, Any]:
    """按 run 执行一次 AI 自动回复真实发送；所有失败路径均不重试。

    lease_owner 为 outbox 原始 owner（显式贯穿，非空时设置线程局部上下文供 guarded 使用）；
    非 outbox 路径传空串，走无租约兼容分支。所有 leased 路径在第一个写库动作前先取得 guarded 检查点，
    检查点前只允许内存计算；终态由单条原子 guarded UPDATE 写入并清租约，guarded 成功后再更新决策日志。
    """
    # 显式 owner 贯穿：非空则写入线程局部上下文，供 _checkpoint/_terminal 的 guarded 使用
    if lease_owner:
        _set_outbox_lease_owner(lease_owner)
    try:
        return _send_ai_auto_reply_for_run_impl(db, run_id=run_id)
    finally:
        if lease_owner:
            _set_outbox_lease_owner("")


def _send_ai_auto_reply_for_run_impl(db: Session, *, run_id: int) -> dict[str, Any]:
    t_send_total = _time.perf_counter()
    send_timing: dict[str, float] = {}
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

    # 第一个 guarded 检查点：decided → send_processing，取得该 run 的写入权并续租。
    # 此后所有 gate_results 合并、内容规范化才允许通过原子 UPDATE 写入 run。
    # 内容规范化（would_send_content）也合并进本检查点的原子 UPDATE，避免检查点前提前提交。
    checkpoint_values: dict[str, Any] = {"status": "send_processing"}
    if content != (run.would_send_content or "").strip():
        checkpoint_values["would_send_content"] = content
    if _checkpoint_with_values(db, run, expected_status="decided", values=checkpoint_values) == 0:
        logger.warning("ai_auto_reply_send_aborted stage=send_processing race_lost run_id=%s", run.id)
        return {"status": "send_skipped", "reason": "send_processing_race_lost"}
    db.refresh(run)

    # 局部累积 gate_results：检查点后从 run 加载一次基线，后续多次合并仅在局部 dict，
    # 由检查点/终态 guarded UPDATE 一次性写入，禁止修改 Session 管理的 ORM 属性（避免脏写）
    gate_acc: dict[str, Any] = _json_object(run.gate_results_json)

    # B1: real_send_gate 计时
    t0 = _time.perf_counter()
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
    send_timing["real_send_gate_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if not real_send_gate.passed:
        gate_json = _merge_gate_results(
            gate_acc, "real_send",
            {**(real_send_gate.gate_results or {}), "send_gate_passed": False, "blocked_reason": real_send_gate.reason},
        )
        _terminal(
            db, run, expected_status="send_processing", status="send_skipped",
            block_reason=real_send_gate.reason or "real_send_gate_blocked", gate_results_json=gate_json,
        )
        logger.info(
            "ai_auto_reply_gate_blocked stage=real_send_gate run_id=%s account_open_id_sha8=%s "
            "blocked_by=%s send_enabled=%s",
            run.id,
            _hash_prefix(run.account_open_id),
            real_send_gate.reason,
            _settings_send_enabled(real_send_gate.gate_results),
        )
        return {"status": "send_skipped", "reason": real_send_gate.reason}

    gate_json = _merge_gate_results(
        gate_acc, "real_send",
        {**(real_send_gate.gate_results or {}), "send_gate_passed": True},
    )

    # B1: manual_takeover 计时
    t0 = _time.perf_counter()
    manual_takeover = evaluate_manual_takeover_gate(
        db,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id,
        conversation_short_id=run.conversation_short_id or "",
    )
    gate_json = _merge_gate_results(gate_acc, "real_send", {"manual_takeover": manual_takeover})
    send_timing["manual_takeover_check_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if manual_takeover.get("blocked") is True:
        _terminal(
            db, run, expected_status="send_processing", status="send_skipped",
            block_reason="manual_takeover_blocked", gate_results_json=gate_json,
        )
        logger.info("ai_auto_reply_send_skipped stage=manual_takeover run_id=%s reason=manual_takeover_blocked", run.id)
        return {"status": "send_skipped", "reason": "manual_takeover_blocked"}

    # B1: latest_message_recheck + send_context 计时
    t0 = _time.perf_counter()
    latest_state = get_latest_private_message_state(
        db,
        account_open_id=run.account_open_id,
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
        trigger_server_message_id=run.trigger_server_message_id,
    )
    if latest_state.get("has_outbound_after_trigger") is True:
        _mark_send_skipped_after_checkpoint(db, run, "outbound_after_trigger", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=outbound_after_trigger", run.id)
        return {"status": "send_skipped", "reason": "outbound_after_trigger"}
    if latest_state.get("latest_is_customer_message") is not True:
        _mark_send_skipped_after_checkpoint(db, run, "latest_message_not_customer", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=latest_message_not_customer", run.id)
        return {"status": "send_skipped", "reason": "latest_message_not_customer"}
    if latest_state.get("latest_server_message_id") != run.trigger_server_message_id:
        _mark_send_skipped_after_checkpoint(db, run, "latest_message_changed", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=latest_message run_id=%s reason=latest_message_changed", run.id)
        return {"status": "send_skipped", "reason": "latest_message_changed"}

    send_context = get_send_msg_context(
        db,
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
    )
    send_timing["latest_message_recheck_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if send_context is None:
        _mark_send_skipped_after_checkpoint(db, run, "send_context_unavailable", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_unavailable", run.id)
        return {"status": "send_skipped", "reason": "send_context_unavailable"}
    if send_context.get("server_message_id") != run.trigger_server_message_id:
        _mark_send_skipped_after_checkpoint(db, run, "send_context_message_changed", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_message_changed", run.id)
        return {"status": "send_skipped", "reason": "send_context_message_changed"}
    if send_context.get("account_open_id") != run.account_open_id:
        _mark_send_skipped_after_checkpoint(db, run, "send_context_account_mismatch", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_account_mismatch", run.id)
        return {"status": "send_skipped", "reason": "send_context_account_mismatch"}
    if send_context.get("customer_open_id") != run.customer_open_id:
        _mark_send_skipped_after_checkpoint(db, run, "send_context_customer_mismatch", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=send_context_customer_mismatch", run.id)
        return {"status": "send_skipped", "reason": "send_context_customer_mismatch"}
    if _is_context_expired(send_context.get("message_create_time")):
        _mark_send_skipped_after_checkpoint(db, run, "context_expired", gate_results_json=gate_json)
        logger.info("ai_auto_reply_send_skipped stage=send_context run_id=%s reason=context_expired", run.id)
        return {"status": "send_skipped", "reason": "context_expired"}

    # 第二个 guarded 检查点：send_processing → send_authorized（门禁全通过，即将调用真实 API；检查点续租）
    # 把累积的 gate_results 与状态一起原子写入，避免在调用上游前留有未持久化的脏数据
    if _checkpoint_with_values(
        db, run, expected_status="send_processing",
        values={"status": "send_authorized", "gate_results_json": gate_json},
    ) == 0:
        logger.warning("ai_auto_reply_send_aborted stage=send_authorized race_lost run_id=%s", run.id)
        return {"status": "send_skipped", "reason": "send_authorized_race_lost"}
    db.refresh(run)

    # B1: douyin_api 计时
    t0 = _time.perf_counter()
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
        send_timing["douyin_api_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    except HTTPException as exc:
        failure_stage = _classify_send_failure(exc)
        terminal_status = "failed" if failure_stage == "upstream_business_error" else "send_unknown"
        written = _terminal(
            db, run, expected_status="send_authorized", status=terminal_status,
            error_message=_safe_error(exc.detail), last_failure_stage=failure_stage,
        )
        if written == 0:
            logger.warning("ai_auto_reply_send_lease_lost stage=send_failure run_id=%s", run.id)
        else:
            logger.warning(
                "ai_auto_reply_send_failed stage=send_msg run_id=%s failure_stage=%s status=%s error_type=%s",
                run.id, failure_stage, terminal_status, type(exc).__name__,
            )
        return {"status": terminal_status, "reason": failure_stage}

    except Exception as exc:
        written = _terminal(
            db, run, expected_status="send_authorized", status="send_unknown",
            error_message=_safe_error(str(exc)), last_failure_stage="send_network_error",
        )
        if written == 0:
            logger.warning("ai_auto_reply_send_lease_lost stage=send_failure run_id=%s", run.id)
        else:
            logger.warning(
                "ai_auto_reply_send_failed stage=send_msg run_id=%s failure_stage=send_network_error status=send_unknown error_type=%s",
                run.id, type(exc).__name__,
            )
        return {"status": "send_unknown", "reason": "send_network_error"}

    # 成功终态：单条原子 guarded UPDATE 写 sent + 清租约（含最终 gate_results）。
    # 仅在 guarded 成功（rowcount==1）后才同步决策日志和 mark_ai_replied；租约丢失则不覆盖、不触发副作用，
    # 由恢复器按 sent 流水 EXISTS 对账为 sent。
    final_gate_json = _build_final_success_gate_json(gate_acc)
    written = _terminal(
        db, run, expected_status="send_authorized", status="sent",
        block_reason=None, error_message=None, gate_results_json=final_gate_json,
    )
    if written == 1:
        _sync_decision_log_final_auto_send(db, run)
        mark_ai_replied(
            db,
            merchant_id=run.merchant_id,
            account_open_id=run.account_open_id,
            conversation_short_id=run.conversation_short_id or "",
            customer_open_id=run.customer_open_id,
        )
        return {"status": "sent", "record_id": send_result.get("record_id")}
    logger.warning("ai_auto_reply_send_lease_lost stage=send_success run_id=%s", run.id)
    # B1 性能基线：发送阶段分阶段耗时日志
    send_timing["send_total_ms"] = round((_time.perf_counter() - t_send_total) * 1000, 1)
    logger.info(
        "ai_auto_reply_send_latency stage=send_done run_id=%s "
        "send_total_ms=%.1f real_send_gate_ms=%.1f manual_takeover_check_ms=%.1f "
        "latest_message_recheck_ms=%.1f douyin_api_ms=%.1f",
        run.id,
        send_timing.get("send_total_ms", 0),
        send_timing.get("real_send_gate_ms", 0),
        send_timing.get("manual_takeover_check_ms", 0),
        send_timing.get("latest_message_recheck_ms", 0),
        send_timing.get("douyin_api_ms", 0),
    )
    return {"status": "sent", "record_id": send_result.get("record_id")}


def _checkpoint_with_values(
    db: Session, run: AiAutoReplyRun, *, expected_status: str, values: dict[str, Any],
) -> int:
    """带额外字段的 guarded 检查点：原子 UPDATE 写 status + 附加 values（如 gate_results_json/
    would_send_content），同时检查点续租。返回 rowcount；0 表示租约丢失，调用方必须终止。"""
    return _guarded_lease_update(
        db, run.id, expected_status=expected_status, values=values, refresh_lease=True,
    ) if _expected_lease_owner() else _non_outbox_checkpoint_with_values(
        db, run, expected_status=expected_status, values=values,
    )


def _non_outbox_checkpoint_with_values(
    db: Session, run: AiAutoReplyRun, *, expected_status: str, values: dict[str, Any],
) -> int:
    now = datetime.now()
    update_values = dict(values)
    update_values["updated_at"] = now
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id == run.id,
            AiAutoReplyRun.status == expected_status,
            AiAutoReplyRun.lease_owner == run.lease_owner,
        )
        .values(**update_values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount


def _mark_send_skipped(db: Session, run: AiAutoReplyRun, reason: str) -> int:
    """跳过终态（检查点前，run 仍为 decided）：decided → send_skipped（guarded + 清租约）。

    返回 rowcount（0=租约丢失未覆盖）；非 outbox 路径直接条件更新。
    """
    return _terminal(db, run, expected_status="decided", status="send_skipped", block_reason=reason)


def _mark_format_invalid(db: Session, run: AiAutoReplyRun, error_message: str) -> int:
    """格式非法终态（检查点前，run 仍为 decided）：decided → send_skipped(format_invalid)（guarded + 清租约）。"""
    return _terminal(
        db, run, expected_status="decided", status="send_skipped",
        block_reason="format_invalid", error_message=error_message,
    )


def _mark_send_skipped_after_checkpoint(
    db: Session, run: AiAutoReplyRun, reason: str, *, gate_results_json: str | None = None,
) -> int:
    """跳过终态（检查点后，run 已 send_processing）：send_processing → send_skipped。

    单条原子 guarded UPDATE 写状态、原因、gate_results 并清租约；gate_results_json 传入
    当前局部累积的 gate_json，保证 send_gate_passed/manual_takeover 等诊断不丢失。
    """
    return _terminal(
        db, run, expected_status="send_processing", status="send_skipped",
        block_reason=reason, gate_results_json=gate_results_json,
    )


def _build_final_success_gate_json(gate_acc: dict[str, Any]) -> str:
    """纯内存构造成功终态的 gate_results JSON（不入库），由终态原子 UPDATE 一次性写入。
    以真实发送结果为准标记 final_auto_send=True。gate_acc 为本流程局部累积的 gate_results dict。"""
    gate_results = dict(gate_acc)
    post_llm = gate_results.get("post_llm")
    if not isinstance(post_llm, dict):
        post_llm = {}
    post_llm["final_auto_send"] = True
    gate_results["post_llm"] = post_llm
    return json.dumps(gate_results, ensure_ascii=False, separators=(",", ":"), default=str)


def _sync_decision_log_final_auto_send(db: Session, run: AiAutoReplyRun) -> None:
    """发送成功终态 guarded 写入后，同步决策日志 final_auto_send=1（仅在租约仍持有时调用）。"""
    if not run.decision_log_id:
        logger.info(
            "ai_auto_reply_send_finalized stage=send_success run_id=%s decision_log_id=None final_auto_send=True",
            run.id,
        )
        return
    decision = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).first()
    if decision is not None:
        decision.final_auto_send = 1
        db.commit()
    logger.info(
        "ai_auto_reply_send_finalized stage=send_success run_id=%s decision_log_id=%s final_auto_send=True",
        run.id,
        run.decision_log_id,
    )


def _merge_gate_results(gate_acc: dict[str, Any], section: str, value: dict[str, Any]) -> str:
    """纯内存累积 gate_results：在局部 dict 上合并 section，返回序列化 JSON 字符串。

    不修改任何 Session 管理的 ORM 属性（不碰 run.gate_results_json），完全避免脏写。
    gate_acc 由调用方在流程开始时从 run.gate_results_json 加载一次，后续多次合并，
    最终由 guarded UPDATE（检查点/终态）一次性写入 run。
    """
    current = gate_acc.get(section)
    if not isinstance(current, dict):
        current = {}
    current.update(value)
    gate_acc[section] = current
    return json.dumps(gate_acc, ensure_ascii=False, separators=(",", ":"), default=str)


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


def _classify_send_failure(exc: HTTPException) -> str:
    """分类 send_msg HTTP 异常：upstream_business_error → failed；其余 → send_unknown。

    优先识别稳定的 error_code=upstream_business_error；不能维护不完整的业务码白名单。
    """
    detail = exc.detail
    if isinstance(detail, dict):
        error_code = str(detail.get("error_code") or "").strip()
        if error_code == "upstream_business_error":
            return "upstream_business_error"
    status_code = getattr(exc, "status_code", 500)
    if status_code in (408, 504):
        return "send_timeout"
    if status_code >= 500:
        return "send_http_error"
    if status_code == 422:
        return "send_invalid_response"
    return "send_network_error"


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
