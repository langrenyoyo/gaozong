"""回访沉默扫描调度器。

职责：
- 默认关闭，仅显式配置 RETURN_VISIT_SILENT_SCAN_ENABLED=true 才由 app.main 启动；
- 周期扫描 trigger_source_type=silent_scan 且 enabled 的回访场景，按各场景 silence_hours
  找出"最后一条客户入站消息已超 N 小时"的会话，创建 ReturnVisitRun（trigger_source=silent_scan）；
- 幂等由 trigger_return_visit_from_silent_scan 的 idempotency_key 保证（同会话同场景同窗口只触发一次）；
- 顺带处理 ReturnVisitFollowupTask 超时（pending 且 deadline < now → timeout），避免单独加定时器；
- 单轮扫描有界（batch_size），不阻塞、不轮询全表。
"""

from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime, timedelta

from app import config
from app.database import SessionLocal
from app.models import DouyinLead, ReturnVisitFollowupTask, ReturnVisitPrompt
from app.services.douyin_workbench_conversation_service import get_latest_private_message_state
from app.services.return_visit_run_service import (
    process_return_visit_run,
    trigger_return_visit_from_silent_scan,
)

logger = logging.getLogger(__name__)


class ReturnVisitSilentScanScheduler:
    """回访沉默扫描调度器（后台守护线程）。"""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def start(self) -> None:
        """启动调度器（幂等）。"""
        with self._start_lock:
            if self._running:
                logger.info("回访沉默扫描调度器已在运行，跳过重复启动")
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="return-visit-silent-scan",
            )
            self._thread.start()
            logger.info("回访沉默扫描调度器已启动")

    def stop(self) -> None:
        """停止调度器（幂等）。"""
        self._running = False
        logger.info("回访沉默扫描调度器已停止")

    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        """每 interval 秒执行一轮。"""
        interval = config.RETURN_VISIT_SILENT_SCAN_INTERVAL_SECONDS
        logger.info("return_visit_silent_scan_loop_started interval=%ss", interval)
        # 启动后等一个 interval 再首轮（避免与其它启动任务同时压 DB）
        while self._running:
            try:
                _time.sleep(interval)
                if not self._running:
                    break
                self.run_once()
            except Exception as exc:  # noqa: BLE001 调度循环异常不中断线程
                logger.error("回访沉默扫描调度器外层异常: %s", exc, exc_info=True)

    def run_once(self) -> dict:
        """执行一轮：扫描沉默会话触发回访 + 处理 SLA 超时。"""
        result = {"silent_triggered": 0, "sla_timeout": 0}
        db = None
        try:
            db = SessionLocal()
            self._scan_silent_conversations(db, result)
            self._mark_sla_timeouts(db, result)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            if db is not None:
                db.rollback()
            logger.error("return_visit_silent_scan stage=run_once error_type=%s", type(exc).__name__, exc_info=True)
        finally:
            if db is not None:
                db.close()
        logger.info(
            "return_visit_silent_scan stage=run_once_done silent_triggered=%s sla_timeout=%s",
            result["silent_triggered"], result["sla_timeout"],
        )
        return result

    def _scan_silent_conversations(self, db, result: dict) -> None:
        """扫描 trigger_source_type=silent_scan 的场景，按 silence_hours 找沉默会话触发。"""
        scenes = (
            db.query(ReturnVisitPrompt)
            .filter(ReturnVisitPrompt.enabled.is_(True))
            .filter(ReturnVisitPrompt.trigger_source_type == "silent_scan")
            .filter(ReturnVisitPrompt.silence_hours.isnot(None))
            .all()
        )
        if not scenes:
            return
        batch_size = config.RETURN_VISIT_SILENT_SCAN_BATCH_SIZE
        for scene in scenes:
            silence_hours = int(scene.silence_hours or 0)
            if silence_hours <= 0:
                continue
            # 只扫描已分配销售的线索（无销售无法通知跟进）
            leads = (
                db.query(DouyinLead)
                .filter(DouyinLead.assigned_staff_id.isnot(None))
                .filter(DouyinLead.conversation_short_id.isnot(None))
                .filter(DouyinLead.account_open_id.isnot(None))
                .order_by(DouyinLead.updated_at.desc().nullslast(), DouyinLead.id.desc())
                .limit(batch_size)
                .all()
            )
            for lead in leads:
                if not lead.account_open_id or not lead.conversation_short_id or not lead.source_id:
                    continue
                state = get_latest_private_message_state(
                    db,
                    account_open_id=lead.account_open_id,
                    conversation_short_id=lead.conversation_short_id,
                    customer_open_id=lead.source_id,
                )
                silence = state.get("customer_silence_hours")
                # 仅当最后一条是出站（销售发的，非客户消息）且沉默时长达标才触发
                if state.get("latest_is_customer_message"):
                    continue
                if silence is None or silence < silence_hours:
                    continue
                trigger_text = (lead.content or lead.raw_message_text or "")[:500]
                run = trigger_return_visit_from_silent_scan(
                    db,
                    merchant_id=lead.merchant_id,
                    lead_id=lead.id,
                    staff_id=lead.assigned_staff_id,
                    prompt_key=scene.prompt_key,
                    conversation_short_id=lead.conversation_short_id,
                    account_open_id=lead.account_open_id,
                    customer_open_id=lead.source_id,
                    trigger_text=trigger_text,
                    silence_hours=silence_hours,
                )
                if run is not None and run.send_status == "pending_judgement":
                    db.commit()
                    # 异步处理判定+发送（避免在扫描循环内阻塞）
                    try:
                        process_return_visit_run(run.id)
                    except Exception as exc:  # noqa: BLE001 单条失败不中断本轮
                        logger.warning(
                            "return_visit_silent_scan process_failed run_id=%s error_type=%s",
                            run.id, type(exc).__name__,
                        )
                    result["silent_triggered"] += 1

    def _mark_sla_timeouts(self, db, result: dict) -> None:
        """处理 ReturnVisitFollowupTask 超时：pending 且 deadline < now → timeout。"""
        now = datetime.now()
        stale = (
            db.query(ReturnVisitFollowupTask)
            .filter(ReturnVisitFollowupTask.status == "pending")
            .filter(ReturnVisitFollowupTask.deadline.isnot(None))
            .filter(ReturnVisitFollowupTask.deadline < now)
            .all()
        )
        for task in stale:
            task.status = "timeout"
            result["sla_timeout"] += 1
            logger.warning(
                "return_visit_sla_timeout followup_task_id=%s run_id=%s staff_id=%s deadline=%s",
                task.id, task.return_visit_run_id, task.staff_id, task.deadline,
            )


return_visit_silent_scan_scheduler = ReturnVisitSilentScanScheduler()
