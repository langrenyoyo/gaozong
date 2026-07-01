import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask


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


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: context or _context()
    return TestClient(app)


def _seed_staff(
    db,
    *,
    merchant_id: str = "merchant-a",
    status: str = "active",
    wechat_nickname: str | None = "Aw3",
) -> SalesStaff:
    staff = SalesStaff(
        name=f"销售-{merchant_id}",
        merchant_id=merchant_id,
        status=status,
        wechat_nickname=wechat_nickname,
    )
    db.add(staff)
    db.flush()
    return staff


def _seed_lead(
    db,
    *,
    merchant_id: str = "merchant-a",
    assigned_staff_id: int | None,
    customer_contact: str | None = "13800138000",
    raw_data: str | None = None,
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
    )
    db.add(lead)
    db.flush()
    return lead


def _status(lead_id: int, context: RequestContext | None = None):
    return _client(context).get(f"/leads/{lead_id}/wechat-notify-status")


def _counts() -> tuple[int, int]:
    db = TestSession()
    try:
        return db.query(WechatTask).count(), db.query(LeadNotification).count()
    finally:
        db.close()


def test_status_ready_and_read_only_when_user_has_leads_and_agent():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.commit()
        lead_id = lead.id
        staff_id = staff.id
    finally:
        db.close()

    response = _status(lead_id)

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["reason"] == "OK"
    assert body["status"] == "ready"
    assert body["message"] == "可通知销售"
    assert body["lead_id"] == lead_id
    assert body["staff_id"] == staff_id
    assert _counts() == (0, 0)


def test_status_not_opened_when_user_only_has_leads_permission():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    response = _status(lead_id, _context(permissions=["auto_wechat:leads"]))

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["reason"] == "PERMISSION_DENIED"
    assert body["status"] == "not_opened"
    assert body["message"] == "当前套餐未开通小高 AI 微信助手"
    assert _counts() == (0, 0)


def test_status_maps_common_block_reasons():
    db = TestSession()
    try:
        staff = _seed_staff(db, wechat_nickname=" ")
        no_contact_staff = _seed_staff(db, wechat_nickname="Aw3")
        unassigned = _seed_lead(db, assigned_staff_id=None)
        no_wechat = _seed_lead(db, assigned_staff_id=staff.id)
        no_contact = _seed_lead(db, assigned_staff_id=no_contact_staff.id, customer_contact=None)
        invalid = _seed_lead(
            db,
            assigned_staff_id=no_contact_staff.id,
            raw_data=json.dumps({"contact_extract": {"status": "parse_failed"}}, ensure_ascii=False),
        )
        pending = _seed_lead(db, assigned_staff_id=no_contact_staff.id)
        done = _seed_lead(db, assigned_staff_id=no_contact_staff.id)
        task = WechatTask(
            task_type="notify_sales",
            lead_id=pending.id,
            staff_id=no_contact_staff.id,
            target_nickname="Aw3",
            message="待执行",
            mode="single_send",
            status="pending",
        )
        notification = LeadNotification(
            lead_id=done.id,
            staff_id=no_contact_staff.id,
            notification_text="已通知",
            send_status="sent",
            send_mode="wechat_task",
        )
        db.add_all([task, notification])
        db.commit()
        ids = {
            "unassigned": unassigned.id,
            "no_wechat": no_wechat.id,
            "no_contact": no_contact.id,
            "invalid": invalid.id,
            "pending": pending.id,
            "done": done.id,
        }
    finally:
        db.close()

    expected = {
        "unassigned": "not_assigned",
        "no_wechat": "staff_wechat_missing",
        "no_contact": "not_ready_no_contact",
        "invalid": "contact_invalid",
        "pending": "task_pending",
        "done": "task_done",
    }
    for key, status in expected.items():
        response = _status(ids[key])
        assert response.status_code == 200
        assert response.json()["status"] == status


def test_cross_merchant_status_does_not_leak_resource_and_does_not_create_records():
    db = TestSession()
    try:
        staff = _seed_staff(db, merchant_id="merchant-b")
        lead = _seed_lead(db, merchant_id="merchant-b", assigned_staff_id=staff.id)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    response = _status(lead_id, _context(merchant_id="merchant-a"))

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "LEAD_NOT_FOUND"
    assert _counts() == (0, 0)
