"""Phase 8 Task 9：上一自然日自动报表调度器专项测试。

覆盖执行包 Task 9 Step 1：
- 默认关闭；启动/停止幂等；
- 只生成 Asia/Shanghai 上一自然日，不生成当天；
- 已有任意状态同业务键不重跑；
- 同商户多人启用同一报表只一份；
- 单商户失败隔离 + Session 关闭；
- 不创建 WechatTask；
- 计划时间前不提前生成，同业务日同进程去重；
- 跨进程并发 claim 视为跳过。

全部用临时内存库 + 临时存储目录 + summary_client=None（不触网、不启动服务）。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.config as app_config
from app.database import Base
from app.models import DailyReportJob, SalesStaff, WechatTask
from app.scheduler import daily_report_scheduler as sched_mod
from app.scheduler.daily_report_scheduler import DailyReportScheduler
from app.services import daily_report_storage as storage

SHANGHAI = ZoneInfo("Asia/Shanghai")

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每测试隔离存储目录 + 让调度器使用测试 Session。"""
    monkeypatch.setattr(storage, "DAILY_REPORT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(sched_mod, "SessionLocal", TestSession)
    yield


def _insert_staff(
    merchant_id: str | None,
    *,
    sv: bool = False,
    fb: bool = False,
    cost: bool = False,
    trace: bool = False,
    status: str = "active",
    name: str = "s",
) -> None:
    db = TestSession()
    try:
        db.add(SalesStaff(
            name=name, merchant_id=merchant_id, status=status,
            enable_short_video_live_lead_report=sv,
            enable_daily_sales_feedback_report=fb,
            enable_sales_unit_cost_report=cost,
            enable_lead_trace_report=trace,
        ))
        db.commit()
    finally:
        db.close()


def _job_count(**filters) -> int:
    db = TestSession()
    try:
        return db.query(DailyReportJob).filter_by(**filters).count()
    finally:
        db.close()


_NOW = datetime(2026, 7, 12, 2, 0, tzinfo=SHANGHAI)
_YESTERDAY = date(2026, 7, 11)


# ============================================================================
# 默认关闭 + 启动停止幂等
# ============================================================================

def test_scheduler_disabled_by_default(monkeypatch):
    """config 默认 DAILY_REPORT_SCHEDULER_ENABLED=false（执行包 Step 3）。"""
    monkeypatch.delenv("DAILY_REPORT_SCHEDULER_ENABLED", raising=False)
    assert app_config.DAILY_REPORT_SCHEDULER_ENABLED is False


def test_start_stop_idempotent(monkeypatch):
    """start 两次只有一个线程；stop 可重复调用。"""
    s = DailyReportScheduler()
    monkeypatch.setattr(s, "_tick", lambda now=None: None)  # 避免 _loop 副作用
    assert not s.is_running()
    s.start()
    assert s.is_running()
    t1 = s._thread
    assert t1 is not None and t1.is_alive()
    s.start()  # 幂等：不新增线程
    assert s._thread is t1
    s.stop()
    s.stop()  # 幂等：再 stop 不报错
    assert not s.is_running()


# ============================================================================
# 上一自然日 + 不生成当天
# ============================================================================

def test_run_once_generates_previous_day_not_today():
    _insert_staff("merchant-a", sv=True)
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["report_day"] == "2026-07-11"
    assert results["generated"] == 1
    assert _job_count(merchant_id="merchant-a", report_type="short_video_live_lead") == 1
    # 不生成当天
    assert _job_count(report_day=date(2026, 7, 12)) == 0


def test_run_once_uses_shanghai_timezone_boundary():
    """Asia/Shanghai 边界：02:00 昨日为 07-11。"""
    _insert_staff("merchant-a", cost=True)
    s = DailyReportScheduler()
    results = s.run_once(datetime(2026, 7, 12, 0, 30, tzinfo=SHANGHAI), summary_client=None)
    assert results["report_day"] == "2026-07-11"


# ============================================================================
# 已有任意状态不重跑 + 同商户多人一份
# ============================================================================

@pytest.mark.parametrize("status", ["none", "generating", "generated", "partial", "failed"])
def test_run_once_skips_existing_any_status(status):
    _insert_staff("merchant-a", sv=True)
    db = TestSession()
    try:
        db.add(DailyReportJob(
            merchant_id="merchant-a", report_day=_YESTERDAY,
            report_type="short_video_live_lead", report_variant="default",
            status=status, artifact_status="available" if status != "none" else "none",
        ))
        db.commit()
    finally:
        db.close()
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["skipped"] == 1
    assert results["generated"] == 0


def test_same_merchant_multiple_staff_produces_one_job():
    _insert_staff("merchant-a", sv=True, name="s1")
    _insert_staff("merchant-a", sv=True, name="s2")
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["generated"] == 1
    assert _job_count(merchant_id="merchant-a", report_type="short_video_live_lead") == 1


def test_trace_uses_created_variant():
    _insert_staff("merchant-a", trace=True)
    s = DailyReportScheduler()
    s.run_once(_NOW, summary_client=None)
    db = TestSession()
    try:
        job = db.query(DailyReportJob).first()
        assert job.report_type == "lead_trace"
        assert job.report_variant == "created"
    finally:
        db.close()


# ============================================================================
# 单商户失败隔离 + Session 关闭
# ============================================================================

def test_run_once_isolates_merchant_failure(monkeypatch):
    _insert_staff("merchant-a", sv=True)
    _insert_staff("merchant-b", sv=True)
    original = sched_mod.generate_one

    def flaky(db, **kw):
        if kw.get("merchant_id") == "merchant-a":
            raise RuntimeError("simulated failure")
        return original(db, **kw)

    monkeypatch.setattr(sched_mod, "generate_one", flaky)
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["failed"] == 1
    assert results["generated"] == 1  # merchant-b 不受影响
    assert any(e.get("merchant_id") == "merchant-a" for e in results["errors"])


def test_run_once_closes_every_session(monkeypatch):
    """每个目标使用独立 Session 并 finally 关闭。"""
    _insert_staff("merchant-a", sv=True)
    closed: list[int] = []

    def factory():
        db = TestSession()
        original_close = db.close

        def spy_close():
            closed.append(1)
            return original_close()

        db.close = spy_close
        return db

    monkeypatch.setattr(sched_mod, "SessionLocal", factory)
    s = DailyReportScheduler()
    s.run_once(_NOW, summary_client=None)
    # plan_db + 至少一个 gen_db
    assert len(closed) >= 2


# ============================================================================
# 筛选：inactive / 无商户 排除
# ============================================================================

def test_inactive_staff_excluded():
    _insert_staff("merchant-a", sv=True, status="inactive")
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["generated"] == 0
    assert results["skipped"] == 0


def test_staff_without_merchant_excluded():
    db = TestSession()
    try:
        db.add(SalesStaff(
            name="x", merchant_id=None, status="active",
            enable_short_video_live_lead_report=True,
        ))
        db.commit()
    finally:
        db.close()
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["generated"] == 0


# ============================================================================
# 计划时间 + 同业务日去重
# ============================================================================

def test_tick_before_schedule_time_returns_none(monkeypatch):
    monkeypatch.setattr(sched_mod, "_new_summary_client", lambda: None)
    _insert_staff("merchant-a", sv=True)
    s = DailyReportScheduler()
    # 01:10 前不提前生成
    assert s._tick(datetime(2026, 7, 12, 0, 30, tzinfo=SHANGHAI)) is None
    assert _job_count() == 0


def test_tick_after_schedule_time_runs(monkeypatch):
    monkeypatch.setattr(sched_mod, "_new_summary_client", lambda: None)
    _insert_staff("merchant-a", sv=True)
    s = DailyReportScheduler()
    r = s._tick(datetime(2026, 7, 12, 1, 30, tzinfo=SHANGHAI))
    assert r is not None
    assert r["report_day"] == "2026-07-11"


def test_tick_same_business_day_dedup(monkeypatch):
    """同进程同业务日只执行一轮；跨进程重复由数据库唯一键兜底。"""
    monkeypatch.setattr(sched_mod, "_new_summary_client", lambda: None)
    _insert_staff("merchant-a", sv=True)
    s = DailyReportScheduler()
    assert s._tick(datetime(2026, 7, 12, 2, 0, tzinfo=SHANGHAI)) is not None
    assert s._tick(datetime(2026, 7, 12, 2, 1, tzinfo=SHANGHAI)) is None
    assert s._tick(datetime(2026, 7, 12, 3, 0, tzinfo=SHANGHAI)) is None
    assert _job_count() == 1


# ============================================================================
# 并发 claim + 不创建 WechatTask
# ============================================================================

def test_run_once_concurrent_generating_skipped():
    """已有 generating（另一进程 claim）按"已有任意状态"跳过，不抢占。"""
    _insert_staff("merchant-a", sv=True)
    db = TestSession()
    try:
        db.add(DailyReportJob(
            merchant_id="merchant-a", report_day=_YESTERDAY,
            report_type="short_video_live_lead", report_variant="default",
            status="generating", artifact_status="none",
            generation_token="other-process", generation_started_at=datetime.now(),
        ))
        db.commit()
    finally:
        db.close()
    s = DailyReportScheduler()
    results = s.run_once(_NOW, summary_client=None)
    assert results["skipped"] == 1
    assert results["generated"] == 0


def test_run_once_does_not_create_wechat_task():
    _insert_staff("merchant-a", sv=True)
    _insert_staff("merchant-a", cost=True, name="s2")
    s = DailyReportScheduler()
    s.run_once(_NOW, summary_client=None)
    db = TestSession()
    try:
        assert db.query(WechatTask).count() == 0
    finally:
        db.close()
