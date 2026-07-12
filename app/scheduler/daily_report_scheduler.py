"""Phase 8 Task 9：上一自然日自动报表调度器。

职责（执行包 Task 9）：
- 默认关闭，仅显式配置 DAILY_REPORT_SCHEDULER_ENABLED=true 才由 app.main 启动；
- 到达 DAILY_REPORT_SCHEDULE_LOCAL_TIME（业务时区 Asia/Shanghai）后生成上一自然日，不生成当天；
- 同业务键已有任意状态任务均不自动重跑（pending/generating/generated/partial/failed/none）；
- 跨进程并发由数据库唯一约束 + generation token claim 保证一个生成者，不依赖进程内锁；
- 单商户失败隔离，每轮每个目标使用独立 Session 并 finally 关闭；
- 只生成报表，不创建 WechatTask、不发送微信附件、不调用 Local Agent / 微信 UI。

复用：app.services.daily_report_job_service.generate_one（不复制聚合/Excel/存储逻辑）。
"""

from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime, timedelta

from sqlalchemy import or_

from app.config import DAILY_REPORT_SCHEDULE_LOCAL_TIME, DAILY_REPORT_TIMEZONE
from app.database import SessionLocal
from app.models import DailyReportJob, SalesStaff
from app.services.daily_report_job_service import (
    ARTIFACT_NONE,
    ClaimConflictError,
    STATUS_GENERATED,
    STATUS_PARTIAL,
    generate_one,
)
from app.services.daily_report_service import (
    REPORT_DAILY_SALES_FEEDBACK,
    REPORT_LEAD_TRACE,
    REPORT_SALES_UNIT_COST,
    REPORT_SHORT_VIDEO_LIVE_LEAD,
)

logger = logging.getLogger(__name__)

SCHEDULER_OPERATOR_ID = "daily-report-scheduler"
SCHEDULER_OPERATOR_NAME = "定时生成"


def _parse_schedule_hhmm() -> tuple[int, int]:
    hour_str, minute_str = DAILY_REPORT_SCHEDULE_LOCAL_TIME.split(":")
    return int(hour_str), int(minute_str)


def _new_summary_client():
    """构造 9100 摘要客户端；run_once 也接受注入便于测试不触网。"""
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClient
    return XgDouyinAiCsClient.from_env()


class DailyReportScheduler:
    """上一自然日自动报表调度器（后台守护线程）。

    线程安全：_start_lock 防重复启动；_running 控制循环退出；
    _last_run_date 避免同进程同业务日重复整轮（跨进程幂等仍由数据库保证）。
    """

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._last_run_date: str | None = None

    def start(self) -> None:
        """启动调度器（幂等：多次调用只启动一个守护线程）。"""
        with self._start_lock:
            if self._running:
                logger.info("日报调度器已在运行，跳过重复启动")
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="daily-report-scheduler",
            )
            self._thread.start()
            logger.info("日报调度器已启动")

    def stop(self) -> None:
        """停止调度器（幂等）。"""
        self._running = False
        logger.info("日报调度器已停止")

    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        """每 60 秒检查一次是否到达计划时间。"""
        while self._running:
            try:
                _time.sleep(60)
                if not self._running:
                    break
                self._tick()
            except Exception as exc:  # noqa: BLE001  调度循环异常不中断线程
                logger.error("日报调度器外层异常: %s", exc, exc_info=True)

    def _tick(self, now: datetime | None = None) -> dict | None:
        """到计划时间则补生成上一自然日；同进程同业务日只执行一次。"""
        now_tz = now or datetime.now(DAILY_REPORT_TIMEZONE)
        hour, minute = _parse_schedule_hhmm()
        scheduled_today = now_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_tz < scheduled_today:
            # 未到计划时间，不提前生成
            return None
        today_key = now_tz.date().isoformat()
        if self._last_run_date == today_key:
            # 同进程同业务日已执行过本轮；跨进程重复由数据库唯一键兜底
            return None
        self._last_run_date = today_key
        return self.run_once(now_tz, summary_client=_new_summary_client())

    def _collect_targets(self, db) -> set[tuple[str, str, str]]:
        """收集需生成的 (merchant_id, report_type, variant) 集合。

        选取 status=active、merchant_id 非空且至少启用一个报表开关的销售；
        同一商户多人启用同一报表只产出一份（set 去重）。
        """
        rows = db.query(SalesStaff).filter(
            SalesStaff.status == "active",
            SalesStaff.merchant_id.isnot(None),
            SalesStaff.merchant_id != "",
            or_(
                SalesStaff.enable_short_video_live_lead_report.is_(True),
                SalesStaff.enable_daily_sales_feedback_report.is_(True),
                SalesStaff.enable_lead_trace_report.is_(True),
                SalesStaff.enable_sales_unit_cost_report.is_(True),
            ),
        ).all()
        targets: set[tuple[str, str, str]] = set()
        for s in rows:
            if s.enable_short_video_live_lead_report:
                targets.add((s.merchant_id, REPORT_SHORT_VIDEO_LIVE_LEAD, "default"))
            if s.enable_daily_sales_feedback_report:
                targets.add((s.merchant_id, REPORT_DAILY_SALES_FEEDBACK, "default"))
            if s.enable_sales_unit_cost_report:
                targets.add((s.merchant_id, REPORT_SALES_UNIT_COST, "default"))
            if s.enable_lead_trace_report:
                targets.add((s.merchant_id, REPORT_LEAD_TRACE, "created"))
        return targets

    def run_once(
        self,
        now: datetime | None = None,
        *,
        summary_client=None,
    ) -> dict:
        """生成上一自然日（Asia/Shanghai）。已有任意状态任务跳过；单商户失败隔离。

        返回结构化结果（便于观测与测试），不抛业务异常。
        """
        now_tz = now or datetime.now(DAILY_REPORT_TIMEZONE)
        yesterday = (now_tz - timedelta(days=1)).date()
        report_day_str = yesterday.isoformat()  # 传给生成的固定 YYYY-MM-DD
        results: dict = {
            "report_day": report_day_str,
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        # 查询目标集合（独立 Session，查完即关）
        plan_db = SessionLocal()
        try:
            targets = self._collect_targets(plan_db)
        except Exception as exc:  # noqa: BLE001  查询失败不阻断
            results["errors"].append({"stage": "collect_targets", "error": type(exc).__name__})
            logger.error("日报调度收集目标失败: %s", exc, exc_info=True)
            return results
        finally:
            plan_db.close()

        for merchant_id, report_type, report_variant in sorted(targets):
            gen_db = SessionLocal()
            try:
                # 门禁 5：已有任意状态同业务键任务一律跳过，不自动重跑
                existing = gen_db.query(DailyReportJob).filter(
                    DailyReportJob.merchant_id == merchant_id,
                    DailyReportJob.report_day == yesterday,
                    DailyReportJob.report_type == report_type,
                    DailyReportJob.report_variant == report_variant,
                ).first()
                if existing is not None:
                    results["skipped"] += 1
                    continue
                # 首次生成；跨进程并发由数据库唯一键 + token claim 保证一个生成者
                job = generate_one(
                    gen_db,
                    merchant_id=merchant_id,
                    report_day=yesterday,
                    report_type=report_type,
                    report_variant=report_variant,
                    summary_client=summary_client,
                    operator_id=SCHEDULER_OPERATOR_ID,
                    operator_name=SCHEDULER_OPERATOR_NAME,
                )
                if job.status in (STATUS_GENERATED, STATUS_PARTIAL):
                    results["generated"] += 1
                else:
                    results["failed"] += 1
            except ClaimConflictError:
                # 并发已被其他 worker claim，视为跳过
                results["skipped"] += 1
            except Exception as exc:  # noqa: BLE001  单商户失败隔离
                results["failed"] += 1
                results["errors"].append({
                    "merchant_id": merchant_id,
                    "report_type": report_type,
                    "error": type(exc).__name__,
                })
                logger.error(
                    "日报调度生成失败 merchant=%s report_type=%s: %s",
                    merchant_id, report_type, exc, exc_info=True,
                )
                try:
                    gen_db.rollback()
                except Exception:  # noqa: BLE001  rollback 失败不影响关闭
                    pass
            finally:
                gen_db.close()

        logger.info(
            "日报调度完成 report_day=%s generated=%s skipped=%s failed=%s",
            report_day_str, results["generated"], results["skipped"], results["failed"],
        )
        return results


# 全局单例
daily_report_scheduler = DailyReportScheduler()
