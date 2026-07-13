"""Phase 8-B Task 3：日报附件投递服务红灯测试。

覆盖执行包 Task 3 合同点（Task 3 实现后全部通过）：
- ensure_deliveries_for_job：仅 generated/partial + artifact 可投递；4 report_type 对应 4 staff 开关；
  同商户 active+昵称销售；幂等；钉住 artifact 快照（storage_key/sha256/size/file_name）；
  昵称缺失不建（后续 blocked 由 retry 体现）；总开关 false → held。
- 灰度：总开关 true + 全量 false → 仅 allowlist 销售 pending；总开关 true + 全量 true → 所有 pending。
- reconcile_job_deliveries：held 随新 artifact 刷新；sent 不刷新（钉住发送版本）。
- retry_delivery：failed/blocked 显式重试递增 attempt + 新 WechatTask；verify_pending 必须
  confirm_not_sent=True；sent/cancelled 终态拒绝；跨商户隔离。
- cancel_delivery：非终态 → cancelled 终态；sent 拒绝。
- artifact_is_pinned：被 delivery 引用 → True；无引用 → False（孤儿文件清理前置检查）。

不触碰附件下载/Local Agent 执行/真实发送（Task 4-7 范围）。全部用临时内存库 + 临时存储目录。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.config as app_config
from app.database import Base
from app.models import DailyReportDelivery, DailyReportJob, SalesStaff, WechatTask
from app.services import daily_report_storage as storage

# Task 3 红灯：delivery_service 未实现时 _require() 触发 pytest.fail（干净 FAIL，非 collection error）
try:
    from app.services import daily_report_delivery_service as _ds
except ImportError:
    _ds = None


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
    """每测试隔离存储目录 + 默认灰度关闭。"""
    monkeypatch.setattr(storage, "DAILY_REPORT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED", False)
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT", False)
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST", set())
    yield


def _require():
    if _ds is None:
        pytest.fail("daily_report_delivery_service 未实现（Task 3 红灯）")
    return _ds


def _insert_staff(merchant_id, *, name="销售A", nick="Aw3", status="active",
                  sv=False, fb=False, trace=False, cost=False) -> SalesStaff:
    db = TestSession()
    try:
        s = SalesStaff(
            name=name, wechat_nickname=nick, merchant_id=merchant_id, status=status,
            enable_short_video_live_lead_report=sv,
            enable_daily_sales_feedback_report=fb,
            enable_lead_trace_report=trace,
            enable_sales_unit_cost_report=cost,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s
    finally:
        db.close()


def _insert_job(merchant_id, *, report_type="short_video_live_lead", status="generated",
                storage_key="k1", sha256="abc123", size=1024) -> DailyReportJob:
    db = TestSession()
    try:
        job = DailyReportJob(
            merchant_id=merchant_id, report_day=date(2026, 7, 12),
            report_type=report_type, report_variant="default", status=status,
            artifact_status="available", file_storage_key=storage_key,
            file_name=f"{report_type}.xlsx", content_sha256=sha256,
            file_size_bytes=size, generated_at=__import__("datetime").datetime.now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ensure_deliveries_for_job
# ---------------------------------------------------------------------------


def test_ensure_creates_held_when_delivery_disabled():
    svc = _require()
    s = _insert_staff("m1", sv=True, nick="Aw3")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        result = svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id, receiver_staff_id=s.id).one()
        # 总开关 false → held
        assert d.status == "held", "总开关关闭时投递应为 held"
        # 钉住 artifact 快照
        assert d.artifact_storage_key == "k1"
        assert d.artifact_sha256 == "abc123"
        assert d.artifact_size_bytes == 1024
        assert d.artifact_file_name == "short_video_live_lead.xlsx"
        assert result["created"] >= 1
    finally:
        db.close()


def test_ensure_only_staff_with_matching_report_toggle():
    svc = _require()
    # 销售 A 开 short_video，销售 B 开 feedback，都不应跨开关
    a = _insert_staff("m1", sv=True, nick="A", name="A")
    _insert_staff("m1", fb=True, nick="B", name="B")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        deliveries = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).all()
        staff_ids = {d.receiver_staff_id for d in deliveries}
        assert staff_ids == {a.id}, "只应为开启对应报表开关的销售建投递"
    finally:
        db.close()


def test_ensure_skips_inactive_and_no_nickname():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A", name="A")
    _insert_staff("m1", sv=True, nick=None, name="无昵称")
    _insert_staff("m1", sv=True, nick="C", name="C", status="inactive")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        deliveries = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).all()
        assert len(deliveries) == 1, "inactive 与无昵称销售不建投递"
    finally:
        db.close()


def test_ensure_idempotent():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        count = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).count()
        assert count == 1, "重复 ensure 不重建（job+staff 唯一）"
    finally:
        db.close()


def test_ensure_rejects_non_generated_job():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead", status="failed")
    db = TestSession()
    try:
        result = svc.ensure_deliveries_for_job(db, job_id=job.id)
        assert result["created"] == 0, "非 generated/partial job 不建投递"
        assert db.query(DailyReportDelivery).filter_by(report_job_id=job.id).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 灰度：allowlist / full rollout
# ---------------------------------------------------------------------------


def test_rollout_disabled_only_allowlist_pending(monkeypatch):
    svc = _require()
    # 总开关 true，全量 false，allowlist=[A]
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED", True)
    a = _insert_staff("m1", sv=True, nick="A", name="A")
    _insert_staff("m1", sv=True, nick="B", name="B")
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST", {a.id})
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d_a = db.query(DailyReportDelivery).filter_by(receiver_staff_id=a.id).one()
        d_b_list = db.query(DailyReportDelivery).filter_by(receiver_staff_id=_staff_b_id()).all()
        assert d_a.status == "pending", "allowlist 销售应进入 pending"
        if d_b_list:
            assert d_b_list[0].status == "held", "非 allowlist 销售保持 held"
    finally:
        db.close()


def test_rollout_full_all_pending(monkeypatch):
    svc = _require()
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED", True)
    monkeypatch.setattr(app_config, "DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT", True)
    _insert_staff("m1", sv=True, nick="A", name="A")
    _insert_staff("m1", sv=True, nick="B", name="B")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        statuses = {d.status for d in db.query(DailyReportDelivery).filter_by(report_job_id=job.id).all()}
        assert statuses == {"pending"}, "全量灰度时所有 active+昵称销售应 pending"
    finally:
        db.close()


def _staff_b_id() -> int:
    db = TestSession()
    try:
        return db.query(SalesStaff).filter_by(name="B").one().id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# reconcile_job_deliveries
# ---------------------------------------------------------------------------


def test_reconcile_refreshes_held_artifact():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead", storage_key="old", sha256="old_h", size=100)
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        # 模拟重生成：job artifact 变更
        db.query(DailyReportJob).filter_by(id=job.id).update({
            DailyReportJob.file_storage_key: "new",
            DailyReportJob.content_sha256: "new_h",
            DailyReportJob.file_size_bytes: 200,
        })
        db.commit()
        svc.reconcile_job_deliveries(db, merchant_id="m1", job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        assert d.artifact_storage_key == "new", "held 投递应随新 artifact 刷新"
        assert d.artifact_sha256 == "new_h"
        assert d.artifact_size_bytes == 200
    finally:
        db.close()


def test_reconcile_preserves_sent_artifact():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead", storage_key="v1", sha256="h1", size=100)
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        # 手动置 sent（钉住 v1）
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        d.status = "sent"
        d.artifact_storage_key = "v1"
        d.artifact_sha256 = "h1"
        d.artifact_size_bytes = 100
        db.commit()
        # job 重生成到 v2
        db.query(DailyReportJob).filter_by(id=job.id).update({
            DailyReportJob.file_storage_key: "v2",
            DailyReportJob.content_sha256: "h2",
            DailyReportJob.file_size_bytes: 200,
        })
        db.commit()
        svc.reconcile_job_deliveries(db, merchant_id="m1", job_id=job.id)
        db.refresh(d)
        assert d.status == "sent", "sent 不被重生成改回"
        assert d.artifact_storage_key == "v1", "sent 钉住发送版本，不漂移到新 artifact"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# retry_delivery / cancel_delivery
# ---------------------------------------------------------------------------


def test_retry_failed_creates_new_attempt():
    svc = _require()
    s = _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        d.status = "failed"
        d.attempt_count = 1
        db.commit()
        svc.retry_delivery(db, merchant_id="m1", delivery_id=d.id, confirm_not_sent=False)
        db.refresh(d)
        assert d.status == "pending", "failed 重试后回到 pending"
        assert d.attempt_count == 2, "attempt 递增"
        tasks = db.query(WechatTask).filter_by(
            report_delivery_id=d.id, delivery_attempt_no=2,
            task_type="send_report_attachment",
        ).all()
        assert len(tasks) == 1, "重试创建唯一新 WechatTask（attempt 号）"
    finally:
        db.close()


def test_retry_verify_pending_requires_confirm():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        d.status = "verify_pending"
        db.commit()
        with pytest.raises(Exception):
            svc.retry_delivery(db, merchant_id="m1", delivery_id=d.id, confirm_not_sent=False)
        # confirm_not_sent=True 才允许
        svc.retry_delivery(db, merchant_id="m1", delivery_id=d.id, confirm_not_sent=True)
    finally:
        db.close()


def test_retry_sent_rejected():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        d.status = "sent"
        db.commit()
        with pytest.raises(Exception):
            svc.retry_delivery(db, merchant_id="m1", delivery_id=d.id, confirm_not_sent=True)
    finally:
        db.close()


def test_retry_cross_merchant_isolated():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        d.status = "failed"
        db.commit()
        # m2 试图重试 m1 的 delivery
        with pytest.raises(Exception):
            svc.retry_delivery(db, merchant_id="m2", delivery_id=d.id, confirm_not_sent=False)
    finally:
        db.close()


def test_cancel_sets_cancelled():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        d = db.query(DailyReportDelivery).filter_by(report_job_id=job.id).one()
        svc.cancel_delivery(db, merchant_id="m1", delivery_id=d.id)
        db.refresh(d)
        assert d.status == "cancelled", "cancel 后进入 cancelled 终态"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# artifact_is_pinned
# ---------------------------------------------------------------------------


def test_artifact_is_pinned_true_when_referenced():
    svc = _require()
    _insert_staff("m1", sv=True, nick="A")
    job = _insert_job("m1", report_type="short_video_live_lead", storage_key="pinned_key")
    db = TestSession()
    try:
        svc.ensure_deliveries_for_job(db, job_id=job.id)
        assert svc.artifact_is_pinned(db, storage_key="pinned_key") is True
    finally:
        db.close()


def test_artifact_is_pinned_false_when_no_reference():
    svc = _require()
    db = TestSession()
    try:
        assert svc.artifact_is_pinned(db, storage_key="orphan_key") is False
    finally:
        db.close()
