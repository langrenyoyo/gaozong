import builtins
import importlib
import sys

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


def _context(merchant_id: str | None = "merchant-a") -> RequestContext:
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
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


def _insert_staff(
    *,
    merchant_id: str = "merchant-a",
    status: str = "active",
    wechat_nickname: str | None = "Aw3",
) -> int:
    db = TestSession()
    try:
        staff = SalesStaff(
            name=f"销售-{merchant_id}",
            wechat_nickname=wechat_nickname,
            status=status,
            merchant_id=merchant_id,
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff.id
    finally:
        db.close()


def _insert_lead(
    *,
    merchant_id: str = "merchant-a",
    assigned_staff_id: int | None = None,
    status: str = "assigned",
) -> int:
    db = TestSession()
    try:
        lead = DouyinLead(
            merchant_id=merchant_id,
            customer_name=f"客户-{merchant_id}",
            source="douyin",
            lead_type="私信",
            content="想了解报价",
            customer_contact="13800138000",
            status=status,
            assigned_staff_id=assigned_staff_id,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


def _task_count() -> int:
    db = TestSession()
    try:
        return db.query(WechatTask).count()
    finally:
        db.close()


def test_openapi_contains_send_to_staff_when_windows_routers_unavailable(monkeypatch):
    """Linux 跳过 Windows 专用路由时，任务创建接口仍应注册。"""
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        requested = set(fromlist or [])
        if name == "app.routers" and {"feedback", "lead_notifications"} & requested:
            raise ImportError("simulated windows-only routers unavailable")
        return original_import(name, globals, locals, fromlist, level)

    sys.modules.pop("app.main", None)
    with monkeypatch.context() as ctx:
        ctx.setattr(builtins, "__import__", fake_import)
        main = importlib.import_module("app.main")
        app = main.create_app()
        paths = app.openapi()["paths"]

    sys.modules.pop("app.main", None)
    importlib.import_module("app.main")

    assert "/lead-notifications/send-to-staff" in paths
    assert "post" in paths["/lead-notifications/send-to-staff"]


def test_assigned_lead_creates_notify_sales_task_and_notification_record():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "created"
    assert body["task_id"] is not None
    assert body["notification_id"] is not None

    db = TestSession()
    try:
        task = db.query(WechatTask).filter_by(id=body["task_id"]).one()
        assert task.task_type == "notify_sales"
        assert task.lead_id == lead_id
        assert task.staff_id == staff_id
        assert task.target_nickname == "Aw3"
        assert task.mode == "single_send"
        assert task.status == "pending"
        # Phase 7：派单文本必须包含稳定反馈编号和【线索反馈】填写模板
        assert "反馈编号：XGF-" in task.message
        assert "【线索反馈】" in task.message
        assert "微信：待添加/已发送申请/已通过/客户拒绝/无法添加/联系方式错误" in task.message
        assert "意向：高意向/中意向/低意向/无意向/待判断" in task.message

        notification = db.query(LeadNotification).filter_by(id=body["notification_id"]).one()
        assert notification.lead_id == lead_id
        assert notification.staff_id == staff_id
        assert notification.send_status == "pending"
        assert notification.send_mode == "wechat_task"
        assert "客户-merchant-a" in notification.notification_text
        # Phase 7：WechatTask.message 与 LeadNotification.notification_text 必须一致
        assert task.message == notification.notification_text
    finally:
        db.close()


def test_unassigned_lead_returns_400_and_does_not_create_task():
    lead_id = _insert_lead(assigned_staff_id=None, status="pending")

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "LEAD_NOT_ASSIGNED"
    assert _task_count() == 0


def test_cross_merchant_lead_returns_404():
    staff_id = _insert_staff(merchant_id="merchant-b")
    lead_id = _insert_lead(merchant_id="merchant-b", assigned_staff_id=staff_id)

    response = _client(_context("merchant-a")).post(
        "/lead-notifications/send-to-staff",
        json={"lead_id": lead_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "LEAD_NOT_FOUND"


def test_send_to_staff_requires_both_leads_and_agent_permissions():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    only_leads = _client(
        RequestContext(
            user_id="user-1",
            merchant_id="merchant-a",
            merchant_ids=["merchant-a"],
            permission_codes=["auto_wechat:leads"],
        )
    ).post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})
    only_agent = _client(
        RequestContext(
            user_id="user-1",
            merchant_id="merchant-a",
            merchant_ids=["merchant-a"],
            permission_codes=["auto_wechat:agent"],
        )
    ).post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert only_leads.status_code == 403
    assert only_agent.status_code == 403
    assert _task_count() == 0


def test_send_to_staff_missing_merchant_context_is_rejected_before_creating_task():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    response = _client(
        RequestContext(
            user_id="user-1",
            merchant_id=None,
            merchant_ids=[],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
        )
    ).post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "MERCHANT_CONTEXT_MISSING"
    assert _task_count() == 0


def test_inactive_staff_is_rejected():
    staff_id = _insert_staff(status="inactive")
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "STAFF_NOT_ACTIVE"
    assert _task_count() == 0


def test_staff_without_wechat_nickname_is_rejected_without_creating_task():
    staff_id = _insert_staff(wechat_nickname=" ")
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "STAFF_WECHAT_NICKNAME_MISSING"
    assert _task_count() == 0


def test_contact_missing_is_rejected_without_creating_task():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)
    db = TestSession()
    try:
        lead = db.query(DouyinLead).filter_by(id=lead_id).one()
        lead.customer_contact = None
        lead.raw_data = None
        lead.extracted_phone = None
        lead.extracted_wechat = None
        db.commit()
    finally:
        db.close()

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CONTACT_MISSING"
    assert _task_count() == 0


# ---- Phase 7-FIX1 Task 1 Step 3: 429 限频红灯 ----

def test_send_to_staff_returns_429_with_retry_after_for_rate_limit():
    """同商户同销售存在有效任务时，再次请求返回 429 + Retry-After。"""
    staff_id = _insert_staff()
    first_lead_id = _insert_lead(assigned_staff_id=staff_id)
    second_lead_id = _insert_lead(assigned_staff_id=staff_id)

    # 创建第一条有效 notify_sales 任务
    first_response = _client().post(
        "/lead-notifications/send-to-staff", json={"lead_id": first_lead_id},
    )
    assert first_response.status_code == 200

    # 第二条线索同商户同销售 → 限频
    response = _client().post(
        "/lead-notifications/send-to-staff", json={"lead_id": second_lead_id},
    )

    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 10
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_existing_pending_task_is_reused_without_duplicate_records():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)

    first = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id}).json()
    second = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id}).json()

    assert second["status"] == "existing_pending"
    assert second["task_id"] == first["task_id"]
    assert second["notification_id"] == first["notification_id"]

    db = TestSession()
    try:
        assert db.query(WechatTask).count() == 1
        assert db.query(LeadNotification).count() == 1
    finally:
        db.close()


def test_sent_notification_returns_already_sent_without_new_task():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)
    db = TestSession()
    try:
        notification = LeadNotification(
            lead_id=lead_id,
            staff_id=staff_id,
            notification_text="已通知",
            send_status="sent",
            send_mode="wechat_task",
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        notification_id = notification.id
    finally:
        db.close()

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_sent"
    assert body["notification_id"] == notification_id
    assert body["task_id"] is None
    assert _task_count() == 0


def test_failed_task_allows_retry_for_same_staff():
    staff_id = _insert_staff()
    lead_id = _insert_lead(assigned_staff_id=staff_id)
    db = TestSession()
    try:
        db.add(
            WechatTask(
                task_type="notify_sales",
                lead_id=lead_id,
                staff_id=staff_id,
                target_nickname="Aw3",
                message="旧失败任务",
                mode="single_send",
                status="failed",
            )
        )
        db.commit()
    finally:
        db.close()

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert _task_count() == 2


def test_reassigned_to_new_staff_creates_task_for_new_staff():
    old_staff_id = _insert_staff(wechat_nickname="旧销售")
    new_staff_id = _insert_staff(wechat_nickname="Aw3")
    lead_id = _insert_lead(assigned_staff_id=old_staff_id)
    db = TestSession()
    try:
        db.add(
            WechatTask(
                task_type="notify_sales",
                lead_id=lead_id,
                staff_id=old_staff_id,
                target_nickname="旧销售",
                message="旧任务",
                mode="single_send",
                status="pending",
            )
        )
        lead = db.query(DouyinLead).filter_by(id=lead_id).one()
        lead.assigned_staff_id = new_staff_id
        db.commit()
    finally:
        db.close()

    response = _client().post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["staff_id"] == new_staff_id
    db = TestSession()
    try:
        task = db.query(WechatTask).filter_by(id=body["task_id"]).one()
        assert task.staff_id == new_staff_id
    finally:
        db.close()
