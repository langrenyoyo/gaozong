from datetime import datetime
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
from app.models import DouyinLead, LeadNotification, SalesStaff


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
        permission_codes=["auto_wechat:leads"],
    )


def _client(context: RequestContext | None = None):
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


def _insert_lead_with_staff(
    *,
    merchant_id: str = "merchant-a",
    staff_name: str = "Aw3",
    staff_wechat_nickname: str = "Aw3",
) -> tuple[int, int]:
    db = TestSession()
    try:
        staff = SalesStaff(
            name=staff_name,
            wechat_nickname=staff_wechat_nickname,
            status="active",
            merchant_id=merchant_id,
        )
        db.add(staff)
        db.flush()
        lead = DouyinLead(
            merchant_id=merchant_id,
            customer_name=f"客户-{merchant_id}",
            source="douyin",
            status="assigned",
            assigned_staff_id=staff.id,
            content="测试线索",
            customer_contact="13800138000",
        )
        db.add(lead)
        db.flush()
        db.commit()
        return lead.id, staff.id
    finally:
        db.close()


def _insert_notification(
    *,
    lead_id: int,
    staff_id: int,
    send_status: str = "sent",
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        row = LeadNotification(
            lead_id=lead_id,
            staff_id=staff_id,
            notification_text="通知内容",
            send_status=send_status,
            send_mode="wechat_task",
            sent_at=created_at,
            created_at=created_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_openapi_contains_records_route_when_windows_routers_unavailable(monkeypatch):
    """Linux 跳过 Windows 专用路由时，records 只读接口仍应注册。"""
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

    assert "/lead-notifications/records" in paths
    assert "get" in paths["/lead-notifications/records"]


def test_current_merchant_can_query_own_lead_notification_records():
    lead_id, staff_id = _insert_lead_with_staff(
        merchant_id="merchant-a",
        staff_name="销售A",
        staff_wechat_nickname="Aw3",
    )
    _insert_notification(lead_id=lead_id, staff_id=staff_id)

    response = _client().get(
        "/lead-notifications/records",
        params={"lead_id": lead_id, "limit": 20},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["records"]) == 1
    item = data["records"][0]
    assert item["lead_id"] == lead_id
    assert item["staff_id"] == staff_id
    assert item["staff_name"] == "销售A"
    assert item["staff_wechat_nickname"] == "Aw3"


def test_cross_merchant_lead_id_returns_404():
    lead_id, staff_id = _insert_lead_with_staff(merchant_id="merchant-b")
    _insert_notification(lead_id=lead_id, staff_id=staff_id)

    response = _client(_context("merchant-a")).get(
        "/lead-notifications/records",
        params={"lead_id": lead_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "LEAD_NOT_FOUND"


def test_missing_lead_id_returns_404():
    response = _client().get(
        "/lead-notifications/records",
        params={"lead_id": 999999},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "LEAD_NOT_FOUND"


def test_limit_is_capped_at_100():
    lead_id, staff_id = _insert_lead_with_staff(merchant_id="merchant-a")
    for index in range(105):
        _insert_notification(
            lead_id=lead_id,
            staff_id=staff_id,
            created_at=datetime(2026, 6, 30, 10, index % 60, 0),
        )

    response = _client().get(
        "/lead-notifications/records",
        params={"lead_id": lead_id, "limit": 500},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 105
    assert len(data["records"]) == 100


def test_no_notification_records_returns_empty_records():
    lead_id, _staff_id = _insert_lead_with_staff(merchant_id="merchant-a")

    response = _client().get(
        "/lead-notifications/records",
        params={"lead_id": lead_id},
    )

    assert response.status_code == 200
    assert response.json() == {"total": 0, "records": []}


def test_list_without_lead_id_is_limited_to_current_merchant_leads():
    lead_a, staff_a = _insert_lead_with_staff(merchant_id="merchant-a")
    lead_b, staff_b = _insert_lead_with_staff(merchant_id="merchant-b")
    _insert_notification(lead_id=lead_a, staff_id=staff_a)
    _insert_notification(lead_id=lead_b, staff_id=staff_b)

    response = _client(_context("merchant-a")).get("/lead-notifications/records")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["records"][0]["lead_id"] == lead_a
