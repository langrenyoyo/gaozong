"""AI 自动回复持久化 outbox 服务。

复用 AiAutoReplyRun 表作为 outbox 任务真源。
职责：
- enqueue：在 webhook 外层事务内 flush pending run，不 commit。
- claim：原子租约，进程内单飞。
- process_one：状态机驱动，调用现有 dry-run/send 流程。
- recover_expired_leases：恢复过期租约的 processing/send_processing 任务。
- compensate_missing_runs：补偿最近窗口内缺失的客户私信事件。
- periodic_scan：60 秒周期扫描，启动立即扫描。
- manual_retry：商户隔离人工重试。
- alert_backlog：积压告警。
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update as sa_update
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import AiAutoReplyRun, DouyinWebhookEvent

logger = logging.getLogger(__name__)

_PROCESS_ID = f"{socket.gethostname()}:{os.getpid()}"


def _thread_unique_lease_owner() -> str:
    """每个线程生成唯一租约标识，避免同进程多线程竞争误读。"""
    return f"{_PROCESS_ID}:{threading.current_thread().ident}"


# ========== 共享并发原语：lease 上下文 + guarded transition + cycle 单飞锁 ==========
# lease 上下文为线程局部：claim 时由 dry-run 入口写入原始 owner，贯穿决策→发送全链路。
# dry-run 与 send service 均从本模块导入这些原语，保证“原始 owner 显式贯穿，禁止重读 DB 当前 owner”。
_outbox_ctx = threading.local()


def _expected_lease_owner() -> str:
    """返回当前线程的 outbox claim 原始 owner；非 outbox 路径返回空串。"""
    return getattr(_outbox_ctx, "lease_owner", "")


def _set_outbox_lease_owner(owner: str) -> None:
    """设置当前线程的原始 lease owner（claim 时调用），贯穿后续 guarded 推进。"""
    _outbox_ctx.lease_owner = owner


def _guarded_lease_update(
    db: Session,
    run_id: int,
    *,
    expected_status: str,
    values: dict[str, Any],
    refresh_lease: bool = False,
) -> int:
    """guarded 状态推进：原子条件 UPDATE，强制校验 expected_status + 原始 lease_owner + 租约未过期。

    - owner 为空（非 outbox 路径）返回 0，调用方走非租约分支。
    - refresh_lease=True 时检查点续租（延长 lease_expires_at）。
    - 返回 rowcount；0 表示租约已丢失/过期/状态不符，调用方必须终止且不得覆盖恢复器或新 Worker 的状态。
    """
    now = datetime.now()
    owner = _expected_lease_owner()
    if not owner:
        return 0
    update_values = dict(values)
    update_values["updated_at"] = now
    if refresh_lease:
        update_values["lease_expires_at"] = now + timedelta(
            seconds=config.AI_AUTO_REPLY_OUTBOX_LEASE_SECONDS
        )
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id == run_id,
            AiAutoReplyRun.status == expected_status,
            AiAutoReplyRun.lease_owner == owner,
            AiAutoReplyRun.lease_expires_at > now,
        )
        .values(**update_values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount


# cycle 单飞锁：scheduler 与 webhook wake 共用，避免并发完整扫描形成无界并行。
_cycle_single_flight_lock = threading.Lock()

# cycle 接力标志：webhook 唤醒撞到正在运行的 cycle 时置位，持锁线程在当前 body
# 结束后同线程再跑一轮，消除"撞锁 skip → 等周期兜底"的 60s 空窗。仅在撞锁时 set，
# 不自发；空 batch + 未置位 → 自然退出，不会死循环。
_cycle_rearm = threading.Event()

# 状态常量
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_RETRY_WAIT = "retry_wait"
STATUS_DECIDED = "decided"
STATUS_SEND_PROCESSING = "send_processing"
STATUS_SEND_AUTHORIZED = "send_authorized"
STATUS_SKIPPED = "skipped"
STATUS_BLOCKED = "blocked"
STATUS_SEND_SKIPPED = "send_skipped"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SEND_UNKNOWN = "send_unknown"

# 可处理状态（扫描目标）
_PROCESSABLE_STATUSES = (STATUS_PENDING, STATUS_RETRY_WAIT)
# 可恢复状态（租约过期后恢复）
_RECOVERABLE_STATUSES = (STATUS_PROCESSING, STATUS_SEND_PROCESSING)
# 永不重发终态
_TERMINAL_NO_RETRY = (STATUS_SENT, STATUS_SEND_UNKNOWN, STATUS_SEND_AUTHORIZED, STATUS_SKIPPED,
                      STATUS_BLOCKED, STATUS_SEND_SKIPPED)
# 人工重试白名单失败阶段（仅发送前临时故障；send_unknown 终态永不重发）
_RETRY_WHITELIST_FAILURE_STAGES = frozenset({
    "pre_send_temporary_failure",
})

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_single_flight_lock = threading.Lock()


# ========== enqueue ==========


def enqueue_auto_reply_run(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    trigger_event_id: int,
    trigger_event_key: str,
    conversation_short_id: str | None = None,
    customer_open_id: str | None = None,
    trigger_server_message_id: str | None = None,
    latest_message: str | None = None,
) -> AiAutoReplyRun | None:
    """在 webhook 外层事务内创建 pending run（仅 flush，不 commit）。

    trigger_event_key 唯一约束保证幂等：重复调用不报错，返回 None。
    """
    existing = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.trigger_event_key == trigger_event_key)
        .first()
    )
    if existing is not None:
        logger.info(
            "ai_outbox_enqueue_skipped reason=duplicate event_id=%s run_id=%s",
            trigger_event_id, existing.id,
        )
        return None

    if not account_open_id:
        logger.info(
            "ai_outbox_enqueue_skipped reason=empty_account_open_id event_id=%s",
            trigger_event_id,
        )
        return None

    run = AiAutoReplyRun(
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
        trigger_event_id=trigger_event_id,
        trigger_event_key=trigger_event_key,
        trigger_server_message_id=trigger_server_message_id,
        latest_message=latest_message,
        status=STATUS_PENDING,
        attempt_count=0,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(run)
    db.flush()
    logger.info(
        "ai_outbox_enqueued stage=enqueue run_id=%s event_id=%s status=pending",
        run.id, trigger_event_id,
    )
    return run


# ========== claim ==========


def claim_next_batch(db: Session, *, batch_size: int = 100) -> list[AiAutoReplyRun]:
    """原子获取一批待处理任务并设置租约。

    使用条件 UPDATE 实现 claim：只更新 status 在可处理列表且 next_attempt_at <= now
    的行，设置线程唯一 lease_owner 和 lease_expires_at。
    claim 后立即 commit，确保租约持久化，竞争失败线程不会读到他人领取的行。
    """
    now = datetime.now()
    lease_expires = now + timedelta(seconds=config.AI_AUTO_REPLY_OUTBOX_LEASE_SECONDS)
    lease_owner = _thread_unique_lease_owner()

    # 条件更新：原子 claim
    candidate_ids = (
        db.query(AiAutoReplyRun.id)
        .filter(
            AiAutoReplyRun.status.in_(_PROCESSABLE_STATUSES),
            or_(
                AiAutoReplyRun.next_attempt_at.is_(None),
                AiAutoReplyRun.next_attempt_at <= now,
            ),
        )
        .order_by(AiAutoReplyRun.created_at)
        .limit(batch_size)
        .all()
    )
    ids = [row[0] for row in candidate_ids]
    if not ids:
        return []

    # 原子条件更新：设置线程唯一租约（含退避时间条件，防并发绕过退避）
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id.in_(ids),
            AiAutoReplyRun.status.in_(_PROCESSABLE_STATUSES),
            or_(
                AiAutoReplyRun.next_attempt_at.is_(None),
                AiAutoReplyRun.next_attempt_at <= now,
            ),
        )
        .values(
            status=STATUS_PROCESSING,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires,
            attempt_count=AiAutoReplyRun.attempt_count + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    # 用线程唯一 lease_owner 读取已 claim 的行（竞争失败线程不会误读）
    claimed = (
        db.query(AiAutoReplyRun)
        .filter(
            AiAutoReplyRun.id.in_(ids),
            AiAutoReplyRun.lease_owner == lease_owner,
            AiAutoReplyRun.status == STATUS_PROCESSING,
        )
        .all()
    )
    logger.info(
        "ai_outbox_claim stage=claim claimed=%s batch_size=%s lease_owner=%s",
        len(claimed), batch_size, lease_owner,
    )
    return claimed


# ========== recover ==========


def recover_expired_leases(db: Session) -> int:
    """恢复租约过期的 processing/send_processing 任务到 pending。

    send_authorized 任务按发送流水对账：存在 sent 流水 → sent，否则 → send_unknown。
    两种情况都禁止自动重发。
    """
    from app.models import DouyinPrivateMessageSend
    now = datetime.now()

    # processing/send_processing → pending
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.status.in_(_RECOVERABLE_STATUSES),
            AiAutoReplyRun.lease_expires_at < now,
        )
        .values(
            status=STATUS_PENDING,
            lease_owner=None,
            lease_expires_at=None,
            last_failure_stage="lease_expired",
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    count = result.rowcount

    # send_authorized → 按发送流水对账（原子 EXISTS/NOT EXISTS 条件更新，防竞争覆盖）
    # sent_exists 以 run.id 为关联，单条 UPDATE 即可对账全部过期 send_authorized 任务
    sent_exists = (
        select(DouyinPrivateMessageSend.id)
        .where(
            DouyinPrivateMessageSend.auto_reply_run_id == AiAutoReplyRun.id,
            DouyinPrivateMessageSend.status == "sent",
        )
    )
    # 存在 sent 流水 → sent（不重发）
    reconciled_sent = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.status == STATUS_SEND_AUTHORIZED,
            AiAutoReplyRun.lease_expires_at < now,
            sent_exists.exists(),
        )
        .values(
            status=STATUS_SENT,
            last_failure_stage=None,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    count += reconciled_sent.rowcount
    # 不存在 sent 流水 → send_unknown（不重发）
    reconciled_unknown = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.status == STATUS_SEND_AUTHORIZED,
            AiAutoReplyRun.lease_expires_at < now,
            ~sent_exists.exists(),
        )
        .values(
            status=STATUS_SEND_UNKNOWN,
            last_failure_stage="send_authorized_crash_unknown",
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    count += reconciled_unknown.rowcount

    if count > 0:
        logger.warning(
            "ai_outbox_recover stage=recover recovered=%s reason=lease_expired_or_authorized", count,
        )
    return count


# ========== compensate ==========


def compensate_missing_runs(db: Session) -> int:
    """补偿最近 15 分钟内缺失 pending run 的客户私信事件。

    原子处理唯一键竞争；跳过无商户或无账号的事件。
    """
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    window = config.AI_AUTO_REPLY_OUTBOX_COMPENSATION_WINDOW_SECONDS
    cutoff = datetime.now() - timedelta(seconds=window)

    recent_events = (
        db.query(DouyinWebhookEvent)
        .filter(
            DouyinWebhookEvent.event.in_(("im_receive_msg", "im_enter_direct_msg")),
            DouyinWebhookEvent.is_duplicate.is_(False),
            DouyinWebhookEvent.created_at >= cutoff,
        )
        .all()
    )

    created = 0
    for event in recent_events:
        merchant_id = event.merchant_id or ""
        account_open_id = event.to_user_id or ""
        if not merchant_id or not account_open_id:
            logger.info(
                "ai_outbox_compensate_skip reason=missing_merchant_or_account event_id=%s event_key=%s",
                event.id, str(event.event_key)[:12],
            )
            continue

        run = AiAutoReplyRun(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            trigger_event_id=event.id,
            trigger_event_key=event.event_key,
            status=STATUS_PENDING,
            attempt_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        # 使用保存点隔离每条插入，冲突只回滚当前条不影响此前成功的补偿
        try:
            sp = db.begin_nested()
            db.add(run)
            db.flush()
            created += 1
        except SAIntegrityError:
            sp.rollback()
            logger.info(
                "ai_outbox_compensate_skip reason=duplicate event_id=%s event_key=%s",
                event.id, str(event.event_key)[:12],
            )

    if created > 0:
        db.commit()
        logger.warning(
            "ai_outbox_compensate stage=compensate created=%s window_seconds=%s", created, window,
        )
    return created


# ========== backlog alert ==========


def alert_backlog(db: Session) -> None:
    """检查积压并输出脱敏结构化告警。"""
    backlog_count = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.status.in_(_PROCESSABLE_STATUSES + _RECOVERABLE_STATUSES))
        .count()
    )

    oldest = (
        db.query(AiAutoReplyRun.created_at)
        .filter(AiAutoReplyRun.status.in_(_PROCESSABLE_STATUSES + _RECOVERABLE_STATUSES))
        .order_by(AiAutoReplyRun.created_at)
        .first()
    )
    oldest_age = 0
    if oldest and oldest[0]:
        # created_at 来自 PostgreSQL DateTime(timezone=True) 可能为 aware，
        # naive - aware 触发 TypeError；按对端时区取同基准 now。
        now_ref = datetime.now(timezone.utc) if oldest[0].tzinfo else datetime.now()
        oldest_age = (now_ref - oldest[0]).total_seconds()

    unknown_count = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.status == STATUS_SEND_UNKNOWN)
        .count()
    )

    if (
        backlog_count >= config.AI_AUTO_REPLY_OUTBOX_BACKLOG_COUNT_THRESHOLD
        or oldest_age >= config.AI_AUTO_REPLY_OUTBOX_BACKLOG_AGE_THRESHOLD
        or unknown_count > 0
    ):
        logger.warning(
            "ai_outbox_backlog_alert stage=backlog_alert backlog_count=%s oldest_age_seconds=%s "
            "unknown_count=%s threshold_count=%s threshold_age=%s",
            backlog_count, int(oldest_age), unknown_count,
            config.AI_AUTO_REPLY_OUTBOX_BACKLOG_COUNT_THRESHOLD,
            config.AI_AUTO_REPLY_OUTBOX_BACKLOG_AGE_THRESHOLD,
        )


# ========== manual retry ==========


RETRY_FAILURE_STAGES = _RETRY_WHITELIST_FAILURE_STAGES


def manual_retry_run(db: Session, *, run_id: int, merchant_id: str) -> AiAutoReplyRun:
    """人工重试：只允许可信当前商户、明确未发送且失败阶段在白名单内的 failed run。

    使用单条原子条件 UPDATE（merchant_id + failed + 白名单阶段 + NOT EXISTS 发送流水），
    消除"先读流水再更新"的 TOCTOU；检查唯一胜出行数，不在请求内发送。
    """
    from app.models import DouyinPrivateMessageSend

    now = datetime.now()
    sent_exists = (
        select(DouyinPrivateMessageSend.id)
        .where(DouyinPrivateMessageSend.auto_reply_run_id == run_id)
    )
    result = db.execute(
        sa_update(AiAutoReplyRun)
        .where(
            AiAutoReplyRun.id == run_id,
            AiAutoReplyRun.merchant_id == merchant_id,
            AiAutoReplyRun.status == STATUS_FAILED,
            AiAutoReplyRun.last_failure_stage.in_(RETRY_FAILURE_STAGES),
            ~sent_exists.exists(),
        )
        .values(
            status=STATUS_RETRY_WAIT,
            attempt_count=0,
            next_attempt_at=now,
            last_failure_stage=None,
            error_message=None,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if result.rowcount == 0:
        # 原子守卫未命中，按只读状态区分原因（不影响并发安全）
        run = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).first()
        if run is None:
            raise ValueError("run_not_found")
        existing_send = (
            db.query(DouyinPrivateMessageSend)
            .filter(DouyinPrivateMessageSend.auto_reply_run_id == run_id)
            .first()
        )
        if existing_send is not None:
            raise ValueError("already_sent")
        if run.merchant_id != merchant_id:
            from app.services.douyin_workbench_conversation_service import AccountMerchantDeniedError
            raise AccountMerchantDeniedError("run_merchant_denied")
        if run.status != STATUS_FAILED:
            raise ValueError(f"run_not_failed:{run.status}")
        raise ValueError(f"failure_stage_not_whitelisted:{run.last_failure_stage}")

    run = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).first()
    logger.info(
        "ai_outbox_manual_retry stage=manual_retry run_id=%s merchant_id=%s status=retry_wait",
        run_id, merchant_id,
    )
    return run


# ========== periodic scheduler ==========


def run_outbox_cycle() -> None:
    """执行一轮 outbox 处理周期：recover → claim → process → compensate → alert。

    scheduler 与 webhook wake 共用本入口；非阻塞单飞锁防止并发完整扫描。
    撞锁时置位 _cycle_rearm，持锁线程在 body 结束后同线程再跑一轮（不变量：
    任意时刻仍只有一个 body 在跑），消除 webhook 唤醒撞锁后的 60s 空窗。
    Session 在取得单飞锁后、try 内创建，确保 Session 构造失败时锁也能释放。
    """
    if not _cycle_single_flight_lock.acquire(blocking=False):
        # cycle 在跑：置位接力，持锁线程会在当前 body 结束后再跑一轮
        _cycle_rearm.set()
        logger.info("ai_outbox_cycle_skipped reason=single_flight_busy rearm=true")
        return
    db = None
    try:
        while True:
            db = SessionLocal()
            recover_expired_leases(db)

            batch = claim_next_batch(db, batch_size=config.AI_AUTO_REPLY_OUTBOX_BATCH_SIZE)
            for run in batch:
                # B1 性能基线：记录排队等待时间（run_created_at → claim 时刻）
                if run.created_at:
                    now_ref = datetime.now(run.created_at.tzinfo) if run.created_at.tzinfo else datetime.now()
                    queue_wait_ms = (now_ref - run.created_at).total_seconds() * 1000
                    # account_open_id 属 PII，不入日志；run_id 已是唯一追踪键
                    logger.info(
                        "ai_outbox_queue_wait stage=claim run_id=%s queue_wait_ms=%.1f status=%s "
                        "single_flight_busy=false",
                        run.id, queue_wait_ms, run.status,
                    )
                try:
                    _process_one(db, run)
                except Exception as exc:
                    db.rollback()
                    logger.exception(
                        "ai_outbox_process_error stage=process_one run_id=%s error_type=%s",
                        run.id, type(exc).__name__,
                    )
                    # 异常后关闭旧 Session 再创建新 Session（修复泄漏）
                    db.close()
                    db = SessionLocal()

            compensate_missing_runs(db)
            alert_backlog(db)

            # 接力检查：本 body 期间若有 webhook 唤醒撞锁置位，则同线程再跑一轮
            if _cycle_rearm.is_set():
                _cycle_rearm.clear()
                logger.info("ai_outbox_cycle_rearm stage=rearm")
                db.close()
                db = None
                continue
            break
    except Exception as exc:
        if db is not None:
            db.rollback()
        logger.exception(
            "ai_outbox_cycle_error stage=cycle error_type=%s", type(exc).__name__,
        )
    finally:
        if db is not None:
            db.close()
        _cycle_single_flight_lock.release()


def _process_one(db: Session, run: AiAutoReplyRun) -> None:
    """处理单个 outbox 任务，传递 claim 时产生的不可替换 lease_owner。

    lease_owner 为空属于非法状态（claim 必然写入线程唯一 owner），必须失败关闭并输出
    stage/failure_stage，不得降级为无租约处理（无租约会绕过 guarded，旧 Worker 可覆盖新 Worker）。
    """
    from app.services.ai_auto_reply_dry_run_service import _run_with_session_for_outbox

    lease_owner = run.lease_owner or ""
    if not lease_owner:
        logger.error(
            "ai_outbox_process_blocked stage=process_one run_id=%s failure_stage=missing_lease_owner "
            "reason=empty_lease_owner_not_allowed",
            run.id,
        )
        raise RuntimeError(f"missing_lease_owner run_id={run.id}")
    _run_with_session_for_outbox(db, run_id=run.id, lease_owner=lease_owner)


def _scheduler_loop() -> None:
    """后台调度循环：每 interval 秒执行一轮。"""
    interval = config.AI_AUTO_REPLY_OUTBOX_INTERVAL_SECONDS
    logger.info("ai_outbox_scheduler_started interval=%ss process_id=%s", interval, _PROCESS_ID)

    # 启动立即扫描
    run_outbox_cycle()

    while not _scheduler_stop.wait(timeout=interval):
        run_outbox_cycle()

    logger.info("ai_outbox_scheduler_stopped process_id=%s", _PROCESS_ID)


def start_outbox_scheduler() -> None:
    """启动 outbox 后台调度线程（daemon，进程内单飞）。"""
    global _scheduler_thread
    if not config.AI_AUTO_REPLY_OUTBOX_ENABLED:
        logger.info("ai_outbox_scheduler_skipped reason=disabled")
        return
    with _single_flight_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            logger.info("ai_outbox_scheduler_already_running")
            return
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="ai-auto-reply-outbox",
            daemon=True,
        )
        _scheduler_thread.start()
    logger.info("ai_outbox_scheduler_thread_started")


def stop_outbox_scheduler() -> None:
    """停止 outbox 后台调度线程。"""
    global _scheduler_thread
    _scheduler_stop.set()
    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=10)
        _scheduler_thread = None
    logger.info("ai_outbox_scheduler_thread_stopped")
