"""AI小高线索独立只读能力服务测试（Phase 3-E1）。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 触发 ORM 注册
from app.database import Base, get_db
from app.models import DouyinLead, SalesStaff


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    """每个测试前重建表，保证 9202 能力服务测试隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(*, merchant_id: str | None = "merchant-a", permissions: list[str] | None = None) -> TestClient:
    from apps.leads.dependencies import get_gateway_context
    from apps.leads.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": merchant_id,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "super_admin": False,
        "permission_codes": permissions or ["auto_wechat:leads"],
        "source_system": "new_car_project",
    }
    return TestClient(app)


def _seed_leads() -> dict[str, int]:
    db = TestSession()
    try:
        staff = SalesStaff(name="销售A", wechat_id="wx_a", wechat_nickname="Aw3", status="active")
        db.add(staff)
        db.flush()
        lead_a = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="客户A",
            customer_contact="13800000000",
            content="想看车，预算多少",
            source_id="source-a",
            merchant_id="merchant-a",
            assigned_staff_id=staff.id,
            status="replied",
            raw_data='{"contact_extract": {"phone": "13800000000", "all_contacts": ["13800000000"]}}',
        )
        lead_b = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="客户B",
            customer_contact="wx_b",
            content="咨询车型",
            source_id="source-b",
            merchant_id="merchant-b",
            status="pending",
        )
        db.add_all([lead_a, lead_b])
        db.commit()
        return {"lead_a": lead_a.id, "lead_b": lead_b.id}
    finally:
        db.close()


def test_leads_app_root_health_openapi_and_read_only_routes():
    ids = _seed_leads()
    client = _client()

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "leads"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "AI小高线索"

    listed = client.get("/api/leads", params={"response_format": "page", "merchant_id": "forged"})
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [ids["lead_a"]]
    assert data["items"][0]["merchant_id"] == "merchant-a"

    detail = client.get(f"/api/leads/{ids['lead_a']}", params={"merchant_id": "forged"})
    assert detail.status_code == 200
    assert detail.json()["id"] == ids["lead_a"]
    assert detail.json()["assigned_staff"]["name"] == "销售A"

    summary = client.get("/api/leads/reports/summary", params={"merchant_id": "forged"})
    assert summary.status_code == 200
    assert summary.json()["total_leads"] == 1
    assert summary.json()["replied_count"] == 1


def test_leads_app_blocks_cross_merchant_detail_and_requires_permission():
    ids = _seed_leads()

    client_a = _client(merchant_id="merchant-a")
    cross_detail = client_a.get(f"/api/leads/{ids['lead_b']}")
    assert cross_detail.status_code == 404
    assert cross_detail.json()["detail"]["code"] == "LEAD_NOT_FOUND"

    denied = _client(permissions=["auto_wechat:ai_agents"]).get("/api/leads")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_leads_app_rejects_missing_gateway_context_for_non_super_admin():
    response = _client(merchant_id=None).get("/api/leads")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "MERCHANT_CONTEXT_MISSING"


def test_leads_app_super_admin_can_read_all_leads():
    from apps.leads.dependencies import get_gateway_context
    from apps.leads.main import create_app

    _seed_leads()
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": None,
        "tenant_id": "tenant-a",
        "user_id": "admin",
        "super_admin": True,
        "permission_codes": ["auto_wechat:leads"],
        "source_system": "new_car_project",
    }
    response = TestClient(app).get("/api/leads", params={"response_format": "page"})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 2
