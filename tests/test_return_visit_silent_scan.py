"""回访沉默扫描调度器测试。

覆盖：
- _mark_sla_timeouts：pending 且 deadline < now → timeout；未到期保持 pending。
- trigger_return_visit_from_silent_scan 幂等：同会话同场景同窗口第二次返回既有 run。
不验证 9100 判定/发送（已由 run_service 测试覆盖），真实网络恒 0。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import app.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    DouyinLead,
    ReturnVisitFollowupTask,
)
from app.scheduler.return_visit_silent_scan_scheduler import ReturnVisitSilentScanScheduler
from app.services.return_visit_run_service import trigger_return_visit_from_silent_scan


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _db():
    return TestSession()


def _seed_lead(db, *, conversation_short_id="conv-scan-1", source_id="customer-scan-1"):
    lead = DouyinLead(
        source="douyin",
        lead_type="chat",
        customer_name="扫描客户",
        merchant_id="merchant-scan",
        account_open_id="account-scan-1",
        conversation_short_id=conversation_short_id,
        source_id=source_id,
        status="assigned",
        assigned_staff_id=None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_mark_sla_timeouts_marks_overdue_pending_as_timeout():
    db = _db()
    try:
        # 已超期 pending → 应标 timeout
        db.add(ReturnVisitFollowupTask(
            return_visit_run_id=999,
            lead_id=None,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            sla_minutes=10,
            deadline=datetime.now() - timedelta(minutes=5),
            status="pending",
        ))
        # 未到期 pending → 保持 pending
        db.add(ReturnVisitFollowupTask(
            return_visit_run_id=998,
            lead_id=None,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            sla_minutes=60,
            deadline=datetime.now() + timedelta(minutes=30),
            status="pending",
        ))
        # 已 followed → 不动
        db.add(ReturnVisitFollowupTask(
            return_visit_run_id=997,
            lead_id=None,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            sla_minutes=10,
            deadline=datetime.now() - timedelta(minutes=5),
            status="followed",
        ))
        db.commit()

        sched = ReturnVisitSilentScanScheduler()
        result = {"silent_triggered": 0, "sla_timeout": 0}
        sched._mark_sla_timeouts(db, result)
        db.commit()

        tasks = db.query(ReturnVisitFollowupTask).order_by(ReturnVisitFollowupTask.return_visit_run_id).all()
        statuses = {t.return_visit_run_id: t.status for t in tasks}
        assert statuses[999] == "timeout"  # 超期 pending → timeout
        assert statuses[998] == "pending"   # 未到期保持
        assert statuses[997] == "followed"  # 已 followed 不动
        assert result["sla_timeout"] == 1
    finally:
        db.close()


def test_silent_trigger_idempotent_returns_existing_run():
    db = _db()
    try:
        lead = _seed_lead(db)
        # get_send_msg_context 在无 webhook event 时返回 None → 触发函数返回 None。
        # 为测幂等，先 mock 它返回有效上下文。
        import app.services.return_visit_run_service as rvs
        orig = rvs.get_send_msg_context
        rvs.get_send_msg_context = lambda *a, **k: {"server_message_id": "srv-1"}

        run1 = trigger_return_visit_from_silent_scan(
            db,
            merchant_id=lead.merchant_id,
            lead_id=lead.id,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            conversation_short_id=lead.conversation_short_id,
            account_open_id=lead.account_open_id,
            customer_open_id=lead.source_id,
            trigger_text="客户上次问价格",
            silence_hours=24,
        )
        assert run1 is not None
        assert run1.trigger_source == "silent_scan"
        assert run1.send_status == "pending_judgement"

        # 第二次同窗口触发 → 返回既有 run（幂等）
        run2 = trigger_return_visit_from_silent_scan(
            db,
            merchant_id=lead.merchant_id,
            lead_id=lead.id,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            conversation_short_id=lead.conversation_short_id,
            account_open_id=lead.account_open_id,
            customer_open_id=lead.source_id,
            trigger_text="客户上次问价格",
            silence_hours=24,
        )
        assert run2.id == run1.id

        # 不同窗口（silence_hours 变更）→ 新建 run
        run3 = trigger_return_visit_from_silent_scan(
            db,
            merchant_id=lead.merchant_id,
            lead_id=lead.id,
            staff_id=None,
            prompt_key="silent_customer_wakeup",
            conversation_short_id=lead.conversation_short_id,
            account_open_id=lead.account_open_id,
            customer_open_id=lead.source_id,
            trigger_text="客户上次问价格",
            silence_hours=48,
        )
        assert run3.id != run1.id

        rvs.get_send_msg_context = orig
    finally:
        db.close()
