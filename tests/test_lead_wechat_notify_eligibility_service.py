import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.database import Base
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask
from app.services.lead_wechat_notify_eligibility_service import (
    LeadWechatNotifyReason,
    evaluate_lead_wechat_notify_eligibility,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permissions: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permissions if permissions is not None else ["auto_wechat:leads", "auto_wechat:agent"],
    )


def _seed_staff(
    db,
    *,
    merchant_id: str = "merchant-a",
    status: str = "active",
    wechat_nickname: str | None = "Aw3",
    enable_lead_assignment: bool = True,
) -> SalesStaff:
    staff = SalesStaff(
        name=f"销售-{merchant_id}",
        status=status,
        wechat_nickname=wechat_nickname,
        merchant_id=merchant_id,
        enable_lead_assignment=enable_lead_assignment,
    )
    db.add(staff)
    db.flush()
    return staff


def _contact_raw(status: str = "matched") -> str:
    return json.dumps(
        {
            "contact_extract": {
                "status": status,
                "phone": "13800138000",
                "all_contacts": [{"type": "phone", "value": "13800138000"}],
            }
        },
        ensure_ascii=False,
    )


def _seed_lead(
    db,
    *,
    merchant_id: str = "merchant-a",
    assigned_staff_id: int | None,
    customer_contact: str | None = "13800138000",
    raw_data: str | None = None,
    extracted_phone: str | None = None,
    extracted_wechat: str | None = None,
    contact_extract_status: str | None = None,
) -> DouyinLead:
    lead = DouyinLead(
        source="douyin",
        lead_type="私信",
        customer_name="客户",
        content="想看车",
        merchant_id=merchant_id,
        assigned_staff_id=assigned_staff_id,
        status="assigned" if assigned_staff_id else "pending",
        customer_contact=customer_contact,
        raw_data=raw_data,
        extracted_phone=extracted_phone,
        extracted_wechat=extracted_wechat,
        contact_extract_status=contact_extract_status,
    )
    db.add(lead)
    db.flush()
    return lead


def _decision(db, lead_id: int, context: RequestContext | None = None, staff_id: int | None = None):
    return evaluate_lead_wechat_notify_eligibility(
        db=db,
        context=context or _context(),
        lead_id=lead_id,
        staff_id=staff_id,
    )


def test_no_merchant_returns_merchant_required():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        lead = _seed_lead(db, assigned_staff_id=staff.id)

        decision = _decision(db, lead.id, _context(merchant_id=None))

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.MERCHANT_REQUIRED
    finally:
        db.close()


def test_missing_permission_returns_permission_denied():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        lead = _seed_lead(db, assigned_staff_id=staff.id)

        decision = _decision(db, lead.id, _context(permissions=["auto_wechat:leads"]))

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.PERMISSION_DENIED
    finally:
        db.close()


def test_lead_not_found_and_cross_merchant_return_lead_not_found():
    db = TestSession()
    try:
        staff = _seed_staff(db, merchant_id="merchant-b")
        lead = _seed_lead(db, merchant_id="merchant-b", assigned_staff_id=staff.id)

        missing = _decision(db, 999)
        cross = _decision(db, lead.id, _context(merchant_id="merchant-a"))

        assert missing.reason == LeadWechatNotifyReason.LEAD_NOT_FOUND
        assert cross.reason == LeadWechatNotifyReason.LEAD_NOT_FOUND
    finally:
        db.close()


def test_unassigned_and_staff_mismatch_are_blocked():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        other = _seed_staff(db, wechat_nickname="Other")
        unassigned = _seed_lead(db, assigned_staff_id=None)
        assigned = _seed_lead(db, assigned_staff_id=staff.id)

        assert _decision(db, unassigned.id).reason == LeadWechatNotifyReason.LEAD_NOT_ASSIGNED
        assert _decision(db, assigned.id, staff_id=other.id).reason == LeadWechatNotifyReason.STAFF_MISMATCH
    finally:
        db.close()


def test_staff_inactive_and_no_wechat_are_blocked():
    db = TestSession()
    try:
        inactive = _seed_staff(db, status="inactive")
        no_wechat = _seed_staff(db, wechat_nickname=" ")
        inactive_lead = _seed_lead(db, assigned_staff_id=inactive.id)
        no_wechat_lead = _seed_lead(db, assigned_staff_id=no_wechat.id)

        assert _decision(db, inactive_lead.id).reason == LeadWechatNotifyReason.STAFF_NOT_ACTIVE
        assert _decision(db, no_wechat_lead.id).reason == LeadWechatNotifyReason.STAFF_WECHAT_NOT_CONFIGURED
    finally:
        db.close()


def test_contact_missing_and_invalid_are_blocked():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        missing = _seed_lead(db, assigned_staff_id=staff.id, customer_contact=None)
        invalid = _seed_lead(
            db,
            assigned_staff_id=staff.id,
            customer_contact="13800138000",
            raw_data=_contact_raw(status="parse_failed"),
        )

        assert _decision(db, missing.id).reason == LeadWechatNotifyReason.CONTACT_MISSING
        assert _decision(db, invalid.id).reason == LeadWechatNotifyReason.CONTACT_INVALID
    finally:
        db.close()


def test_extracted_contact_and_raw_contact_are_accepted():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        extracted = _seed_lead(db, assigned_staff_id=staff.id, customer_contact=None, extracted_wechat="wx_123456")
        raw = _seed_lead(db, assigned_staff_id=staff.id, customer_contact=None, raw_data=_contact_raw())

        assert _decision(db, extracted.id).reason == LeadWechatNotifyReason.OK
        assert _decision(db, raw.id).reason == LeadWechatNotifyReason.OK
    finally:
        db.close()


def test_already_sent_and_existing_pending_are_reported_without_allowing_create():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        sent_lead = _seed_lead(db, assigned_staff_id=staff.id)
        pending_lead = _seed_lead(db, assigned_staff_id=staff.id)
        sent = LeadNotification(
            lead_id=sent_lead.id,
            staff_id=staff.id,
            notification_text="已通知",
            send_status="sent",
            send_mode="wechat_task",
        )
        pending = WechatTask(
            task_type="notify_sales",
            lead_id=pending_lead.id,
            staff_id=staff.id,
            target_nickname="Aw3",
            message="待执行",
            mode="single_send",
            status="pending",
        )
        db.add_all([sent, pending])
        db.flush()

        sent_decision = _decision(db, sent_lead.id)
        pending_decision = _decision(db, pending_lead.id)

        assert sent_decision.reason == LeadWechatNotifyReason.ALREADY_SENT
        assert sent_decision.existing_notification_id == sent.id
        assert pending_decision.reason == LeadWechatNotifyReason.EXISTING_PENDING_TASK
        assert pending_decision.existing_task_id == pending.id
    finally:
        db.close()


# ---- Phase 7-FIX1 Task 1: 开关 + 限频 + 幂等优先级红灯 ----

def test_eligibility_rejects_staff_with_lead_assignment_disabled():
    db = TestSession()
    try:
        staff = _seed_staff(db, enable_lead_assignment=False)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.commit()

        decision = _decision(db, lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.STAFF_LEAD_ASSIGNMENT_DISABLED
    finally:
        db.close()


def test_eligibility_rate_limits_same_merchant_and_staff():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        first_lead = _seed_lead(db, assigned_staff_id=staff.id)
        second_lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.add(WechatTask(
            task_type="notify_sales",
            lead_id=first_lead.id,
            staff_id=staff.id,
            status="pending",
            mode="single_send",
        ))
        db.commit()

        decision = _decision(db, second_lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.RATE_LIMITED
        assert 1 <= decision.retry_after_seconds <= 10
    finally:
        db.close()


def test_eligibility_rate_limit_skips_failed_blocked_cancelled_statuses():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        for status in ("failed", "blocked", "cancelled"):
            db.add(WechatTask(
                task_type="notify_sales",
                lead_id=lead.id,
                staff_id=staff.id,
                status=status,
                mode="single_send",
            ))
        db.commit()

        decision = _decision(db, lead.id)

        assert decision.allowed is True
        assert decision.reason == LeadWechatNotifyReason.OK
    finally:
        db.close()


def test_eligibility_rate_limit_isolates_by_staff():
    db = TestSession()
    try:
        staff_a = _seed_staff(db, wechat_nickname="StaffA")
        staff_b = _seed_staff(db, wechat_nickname="StaffB")
        lead_a = _seed_lead(db, assigned_staff_id=staff_a.id)
        lead_b = _seed_lead(db, assigned_staff_id=staff_b.id)
        db.add(WechatTask(
            task_type="notify_sales",
            lead_id=lead_a.id,
            staff_id=staff_a.id,
            status="pending",
            mode="single_send",
        ))
        db.commit()

        decision = _decision(db, lead_b.id)

        assert decision.allowed is True
        assert decision.reason == LeadWechatNotifyReason.OK
    finally:
        db.close()


def test_eligibility_rate_limit_isolates_by_merchant():
    db = TestSession()
    try:
        staff_a = _seed_staff(db, merchant_id="merchant-a")
        staff_b = _seed_staff(db, merchant_id="merchant-b")
        lead_a = _seed_lead(db, merchant_id="merchant-a", assigned_staff_id=staff_a.id)
        lead_b = _seed_lead(db, merchant_id="merchant-b", assigned_staff_id=staff_b.id)
        db.add(WechatTask(
            task_type="notify_sales",
            lead_id=lead_a.id,
            staff_id=staff_a.id,
            status="pending",
            mode="single_send",
        ))
        db.commit()

        decision = _decision(
            db, lead_b.id,
            context=_context(merchant_id="merchant-b"),
        )

        assert decision.allowed is True
        assert decision.reason == LeadWechatNotifyReason.OK
    finally:
        db.close()


def test_eligibility_rate_limit_allows_after_window_expires():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        first_lead = _seed_lead(db, assigned_staff_id=staff.id)
        second_lead = _seed_lead(db, assigned_staff_id=staff.id)
        old_task = WechatTask(
            task_type="notify_sales",
            lead_id=first_lead.id,
            staff_id=staff.id,
            status="pending",
            mode="single_send",
            created_at=datetime.now() - timedelta(seconds=11),
        )
        db.add(old_task)
        db.commit()

        decision = _decision(db, second_lead.id)

        assert decision.allowed is True
        assert decision.reason == LeadWechatNotifyReason.OK
    finally:
        db.close()


def test_eligibility_idempotency_priority_over_switch_and_rate_limit():
    """同线索已有 pending/running/pasted 任务时，优先返回幂等原因，
    不被 enable_lead_assignment 或限频覆盖。"""
    db = TestSession()
    try:
        staff = _seed_staff(db, enable_lead_assignment=False)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.add(WechatTask(
            task_type="notify_sales",
            lead_id=lead.id,
            staff_id=staff.id,
            status="pending",
            mode="single_send",
        ))
        db.commit()

        decision = _decision(db, lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.EXISTING_PENDING_TASK
        assert decision.existing_task_id is not None
    finally:
        db.close()


def test_eligibility_already_sent_priority_over_disabled_switch():
    """同线索已有 sent 通知时，即使销售关闭分配开关也返回幂等原因。"""
    db = TestSession()
    try:
        staff = _seed_staff(db, enable_lead_assignment=False)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        sent = LeadNotification(
            lead_id=lead.id,
            staff_id=staff.id,
            notification_text="已通知",
            send_status="sent",
            send_mode="wechat_task",
        )
        db.add(sent)
        db.commit()

        decision = _decision(db, lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.ALREADY_SENT
    finally:
        db.close()
