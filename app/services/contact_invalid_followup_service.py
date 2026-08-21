"""空号追问主动发送服务（块3）。

职责：
- create_followup_task：状态迁移 VALID→INVALID 时创建追问任务（webhook 事务内调用）
- run_followup_cycle：Worker 调度循环（claim → 新鲜度检查 → 门禁 → 发送 → 回写）
- _check_freshness：专用新鲜度检查（替代无条件豁免）
- _build_followup_text：固定话术（不依赖 LLM）
- cancel_pending_tasks：恢复时取消未发送任务

安全底线（已确认的门禁清单）：
- G3 商户归属：保留
- G4 人工接管：保留（不豁免）
- 专用新鲜度检查替代 E2/E3/E4 无条件豁免
- 24h 窗口/频控/账号开关/总开关/紧急停止/Hard 守卫：全部保留
- 追问计数按 invalid_version，每次失效事件最多 2 条
- 固定话术不依赖 LLM
- send_source=contact_invalid_followup
"""

from __future__ import annotations

import logging
import os
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import (
    ContactInvalidFollowupTask,
    ConversationAutopilotState,
    CustomerProfile,
    DouyinPrivateMessageSend,
)
from app.services.conversation_autopilot_state_service import evaluate_manual_takeover_gate
from app.services.douyin_gmp_authorization_health import (
    GMP_ACCOUNT_SCOPE_MISMATCH_CODE,
    GMP_REAUTH_ERROR_CODE,
)
from app.services.douyin_workbench_conversation_service import get_latest_private_message_state, get_send_msg_context
from app.services.douyin_private_message_send_service import _send_private_message_with_context

logger = logging.getLogger(__name__)

_FOLLOWUP_INTERVAL_SECONDS = int(os.getenv("CONTACT_INVALID_FOLLOWUP_INTERVAL_SECONDS", "30"))
_FOLLOWUP_LEASE_SECONDS = int(os.getenv("CONTACT_INVALID_FOLLOWUP_LEASE_SECONDS", "120"))
_FOLLOWUP_MAX_ATTEMPTS = int(os.getenv("CONTACT_INVALID_FOLLOWUP_MAX_ATTEMPTS", "3"))
_SEQUENCE2_DELAY_SECONDS = int(os.getenv("CONTACT_INVALID_FOLLOWUP_SEQUENCE2_DELAY", "1800"))  # 30 分钟

_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None


def create_followup_task(
    db: Session,
    *,
    merchant_id: str,
    lead_id: int,
    account_open_id: str,
    conversation_short_id: str,
    customer_open_id: str,
    invalid_version: int,
    trigger_source: str,
    trigger_message_id: str | None,
    invalid_reason: str,
    followup_sequence: int = 1,
    scheduled_at: datetime | None = None,
) -> ContactInvalidFollowupTask | None:
    """状态迁移 VALID→INVALID 时创建追问任务（幂等，唯一约束防重）。"""
    try:
        task = ContactInvalidFollowupTask(
            merchant_id=merchant_id,
            lead_id=lead_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            customer_open_id=customer_open_id,
            invalid_version=invalid_version,
            trigger_source=trigger_source,
            trigger_message_id=trigger_message_id,
            invalid_reason=invalid_reason,
            followup_sequence=followup_sequence,
            status="pending",
            scheduled_at=scheduled_at or datetime.now(),
        )
        db.add(task)
        db.flush()
        logger.info(
            "contact_invalid_followup_created lead_id=%s version=%s sequence=%s",
            lead_id, invalid_version, followup_sequence,
        )
        return task
    except Exception as exc:
        # 唯一约束冲突=已存在，幂等跳过
        logger.info(
            "contact_invalid_followup_create_skipped lead_id=%s version=%s sequence=%s reason=%s",
            lead_id, invalid_version, followup_sequence, str(exc)[:100],
        )
        return None


def cancel_pending_tasks(
    db: Session,
    *,
    merchant_id: str,
    lead_id: int,
    invalid_version: int,
    cancel_reason: str,
) -> int:
    """恢复时取消当前 invalid_version 下所有未发送任务。返回取消数。"""
    result = db.query(ContactInvalidFollowupTask).filter(
        ContactInvalidFollowupTask.merchant_id == merchant_id,
        ContactInvalidFollowupTask.lead_id == lead_id,
        ContactInvalidFollowupTask.invalid_version == invalid_version,
        ContactInvalidFollowupTask.status.in_(["pending", "processing", "retry_wait"]),
    ).update({
        "status": "cancelled",
        "cancelled_at": datetime.now(),
        "cancel_reason": cancel_reason,
        "updated_at": datetime.now(),
    }, synchronize_session=False)
    if result:
        logger.info(
            "contact_invalid_followup_cancelled lead_id=%s version=%s count=%s reason=%s",
            lead_id, invalid_version, result, cancel_reason,
        )
    return result


def run_followup_cycle() -> None:
    """Worker 调度一轮：claim → 新鲜度检查 → 门禁 → 发送 → 回写。"""
    db = SessionLocal()
    try:
        _recover_expired_leases(db)
        batch = _claim_tasks(db, batch_size=5)
        for task in batch:
            _process_one(db, task)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("contact_invalid_followup_cycle_error error=%s", str(exc)[:200])
    finally:
        db.close()


def _claim_tasks(db: Session, *, batch_size: int = 5) -> list[ContactInvalidFollowupTask]:
    """原子 claim：pending → processing + 租约。"""
    now = datetime.now()
    lease_owner = f"followup:{os.getpid()}:{threading.get_ident()}"
    lease_expires = now + timedelta(seconds=_FOLLOWUP_LEASE_SECONDS)

    tasks = db.query(ContactInvalidFollowupTask).filter(
        ContactInvalidFollowupTask.status == "pending",
        ContactInvalidFollowupTask.scheduled_at <= now,
    ).order_by(ContactInvalidFollowupTask.scheduled_at.asc()).limit(batch_size).all()

    claimed = []
    for task in tasks:
        rowcount = db.query(ContactInvalidFollowupTask).filter(
            ContactInvalidFollowupTask.id == task.id,
            ContactInvalidFollowupTask.status == "pending",
        ).update({
            "status": "processing",
            "lease_owner": lease_owner,
            "lease_expires_at": lease_expires,
            "attempt_count": ContactInvalidFollowupTask.attempt_count + 1,
            "updated_at": now,
        }, synchronize_session=False)
        if rowcount:
            claimed.append(task)
    db.flush()
    return claimed


def _recover_expired_leases(db: Session) -> None:
    """恢复租约过期的 processing 任务 → retry_wait。"""
    now = datetime.now()
    db.query(ContactInvalidFollowupTask).filter(
        ContactInvalidFollowupTask.status == "processing",
        ContactInvalidFollowupTask.lease_expires_at < now,
    ).update({
        "status": "retry_wait",
        "scheduled_at": now + timedelta(seconds=60),
        "lease_owner": None,
        "lease_expires_at": None,
        "updated_at": now,
    }, synchronize_session=False)


def _process_one(db: Session, task: ContactInvalidFollowupTask) -> None:
    """处理单个追问任务：新鲜度检查 → 门禁 → 发送 → 回写。"""
    # 超过最大重试次数 → dead
    if task.attempt_count > _FOLLOWUP_MAX_ATTEMPTS:
        task.status = "dead"
        task.last_error = "max_attempts_exceeded"
        task.updated_at = datetime.now()
        logger.warning("contact_invalid_followup_dead task_id=%s attempts=%s", task.id, task.attempt_count)
        return

    # 1. 专用新鲜度检查（替代无条件豁免）
    freshness = _check_freshness(db, task)
    if not freshness["passed"]:
        task.status = "cancelled"
        task.cancelled_at = datetime.now()
        task.cancel_reason = freshness["reason"]
        task.updated_at = datetime.now()
        logger.info("contact_invalid_followup_cancelled task_id=%s reason=%s", task.id, freshness["reason"])
        return

    # 2. 门禁检查（保留的，不豁免）
    gate = _check_gates(db, task)
    if not gate["passed"]:
        task.status = "cancelled"
        task.cancelled_at = datetime.now()
        task.cancel_reason = gate["reason"]
        task.updated_at = datetime.now()
        logger.info("contact_invalid_followup_gate_blocked task_id=%s reason=%s", task.id, gate["reason"])
        return

    # 3. 固定话术（不依赖 LLM）
    profile = db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == task.merchant_id,
        CustomerProfile.account_open_id == task.account_open_id,
        CustomerProfile.customer_open_id == task.customer_open_id,
    ).first()
    salutation = profile.preferred_salutation if profile and profile.preferred_salutation else "老板"
    text = _build_followup_text(task.invalid_reason, salutation)

    # 4. 发送（复用 _send_private_message_with_context，4层串号防护）
    try:
        send_context = get_send_msg_context(
            db,
            conversation_short_id=task.conversation_short_id,
            customer_open_id=task.customer_open_id,
        )
        if send_context is None:
            task.status = "retry_wait"
            task.scheduled_at = datetime.now() + timedelta(seconds=60)
            task.last_error = "send_context_unavailable"
            task.updated_at = datetime.now()
            return

        send_result = _send_private_message_with_context(
            db,
            merchant_id=task.merchant_id or "",
            content=text,
            send_context=send_context,
            manual_confirmed=False,
            auto_send=True,
            send_source="contact_invalid_followup",
        )

        if send_result.get("status") == "sent":
            task.status = "sent"
            task.sent_at = datetime.now()
            task.sent_message_id = send_result.get("upstream_msg_id")
            task.updated_at = datetime.now()
            logger.info(
                "contact_invalid_followup_sent task_id=%s sequence=%s reason=%s",
                task.id, task.followup_sequence, task.invalid_reason,
            )
            # sequence=1 发送成功后创建 sequence=2（间隔 30 分钟）
            if task.followup_sequence == 1:
                create_followup_task(
                    db,
                    merchant_id=task.merchant_id,
                    lead_id=task.lead_id,
                    account_open_id=task.account_open_id,
                    conversation_short_id=task.conversation_short_id,
                    customer_open_id=task.customer_open_id,
                    invalid_version=task.invalid_version,
                    trigger_source=task.trigger_source,
                    trigger_message_id=task.trigger_message_id,
                    invalid_reason=task.invalid_reason,
                    followup_sequence=2,
                    scheduled_at=datetime.now() + timedelta(seconds=_SEQUENCE2_DELAY_SECONDS),
                )
        else:
            task.status = "retry_wait"
            task.scheduled_at = datetime.now() + timedelta(seconds=60)
            task.last_error = str(send_result.get("reason") or send_result.get("error") or "send_failed")
            task.updated_at = datetime.now()
            logger.warning(
                "contact_invalid_followup_send_failed task_id=%s reason=%s",
                task.id, task.last_error[:100],
            )
    except Exception as exc:
        # P0.5：授权健康错误（REAUTH_REQUIRED 本地阻断 / 账号归属失败）→ 任务终态 failed，
        # 不进 60 秒重试（重复调用无意义且不解决授权问题）；其余异常维持既有 60 秒重试。
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            code = str(exc.detail.get("code") or "")
            if code in (GMP_REAUTH_ERROR_CODE, GMP_ACCOUNT_SCOPE_MISMATCH_CODE):
                task.status = "failed"
                task.last_error = code
                task.updated_at = datetime.now()
                logger.warning(
                    "contact_invalid_followup_failed task_id=%s code=%s（授权健康终态，不进 60s 重试）",
                    task.id, code,
                )
                return
        task.status = "retry_wait"
        task.scheduled_at = datetime.now() + timedelta(seconds=60)
        task.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        task.updated_at = datetime.now()
        logger.warning("contact_invalid_followup_error task_id=%s error=%s", task.id, str(exc)[:200])


def _check_freshness(db: Session, task: ContactInvalidFollowupTask) -> dict[str, Any]:
    """专用新鲜度检查（替代无条件豁免）。

    - contact_state 仍为 INVALID？
    - invalid_version 匹配？
    - 客户在任务创建后发了新消息？→ 取消走被动兜底
    - trigger 之后有新人工出站？→ 取消
    """
    # 1. 当前 contact_state 是否仍为 INVALID
    profile = db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == task.merchant_id,
        CustomerProfile.account_open_id == task.account_open_id,
        CustomerProfile.customer_open_id == task.customer_open_id,
    ).first()
    if not profile or profile.contact_state != "invalid":
        return {"passed": False, "reason": "contact_already_recovered"}

    # 2. invalid_version 是否匹配
    if profile.contact_invalid_version != task.invalid_version:
        return {"passed": False, "reason": "invalid_episode_changed"}

    # 3. 客户是否在任务创建后发了新消息
    latest = get_latest_private_message_state(
        db,
        account_open_id=task.account_open_id,
        conversation_short_id=task.conversation_short_id,
        customer_open_id=task.customer_open_id,
    )
    if latest:
        latest_created = latest.get("last_customer_message_at")
        if latest_created and isinstance(latest_created, datetime):
            if latest_created > task.created_at:
                return {"passed": False, "reason": "customer_message_received_use_passive_fallback"}

    # 4. trigger 之后是否有新的人工出站消息
    #    （trigger 本身的出站消息允许，新的人工出站说明已接管）
    if task.trigger_message_id:
        has_new_outbound = _has_human_outbound_after_trigger(
            db, task.account_open_id, task.conversation_short_id, task.trigger_message_id
        )
        if has_new_outbound:
            return {"passed": False, "reason": "human_handled_after_trigger"}

    return {"passed": True, "reason": None}


def _check_gates(db: Session, task: ContactInvalidFollowupTask) -> dict[str, Any]:
    """门禁检查（保留的，不豁免）。

    - G3 商户归属：保留
    - G4 人工接管：保留（不豁免）
    - 24h 窗口/频控/账号开关/总开关/紧急停止/Hard 守卫：保留
    """
    # G4: 人工接管
    takeover = evaluate_manual_takeover_gate(
        db,
        merchant_id=task.merchant_id,
        account_open_id=task.account_open_id,
        conversation_short_id=task.conversation_short_id,
    )
    if takeover.get("blocked"):
        return {"passed": False, "reason": "manual_takeover_blocked"}

    # 24h 窗口：get_send_msg_context 内部查最新 im_receive_msg 并校验 24h
    send_context = get_send_msg_context(
        db,
        conversation_short_id=task.conversation_short_id,
        customer_open_id=task.customer_open_id,
    )
    if send_context is None:
        return {"passed": False, "reason": "send_context_expired_or_unavailable"}

    return {"passed": True, "reason": None}


def _has_human_outbound_after_trigger(
    db: Session,
    account_open_id: str,
    conversation_short_id: str,
    trigger_message_id: str,
) -> bool:
    """检查 trigger_message_id 之后是否有新的人工出站消息。"""
    # 查 trigger 之后的所有出站消息，排除 AI 自动回复
    sends = db.query(DouyinPrivateMessageSend).filter(
        DouyinPrivateMessageSend.account_open_id == account_open_id,
        DouyinPrivateMessageSend.conversation_short_id == conversation_short_id,
    ).order_by(DouyinPrivateMessageSend.id.desc()).limit(10).all()

    found_trigger = False
    for send in sends:
        if str(send.id) == trigger_message_id or send.server_message_id == trigger_message_id:
            found_trigger = True
            continue
        if found_trigger:
            # trigger 之后的出站消息
            if send.send_source not in ("ai_auto", "return_visit_auto", "contact_invalid_followup"):
                return True
    return False


def _build_followup_text(invalid_reason: str, salutation: str) -> str:
    """固定话术（不依赖 LLM）。按 invalid_reason 两模板。"""
    name = salutation or "老板"
    if invalid_reason in ("empty_number", "wrong_number"):
        return f"{name}，您之前发的联系方式好像不太对，麻烦重新发一遍。"
    if invalid_reason in ("unreachable", "wechat_add_failed"):
        return f"{name}，之前的联系方式暂时联系不上，麻烦重新发一遍。"
    return f"{name}，您之前发的联系方式好像不太对，麻烦重新发一遍。"


def start_followup_scheduler() -> None:
    """启动追问 Worker 调度线程。"""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="contact_invalid_followup")
    _scheduler_thread.start()
    logger.info("contact_invalid_followup_scheduler_started interval=%ss", _FOLLOWUP_INTERVAL_SECONDS)


def stop_followup_scheduler() -> None:
    """停止追问 Worker。"""
    _scheduler_stop.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("contact_invalid_followup_scheduler_stopped")


def _scheduler_loop() -> None:
    """调度循环：每 interval 秒执行一轮。"""
    while not _scheduler_stop.wait(timeout=_FOLLOWUP_INTERVAL_SECONDS):
        try:
            run_followup_cycle()
        except Exception as exc:
            logger.exception("contact_invalid_followup_loop_error error=%s", str(exc)[:200])
