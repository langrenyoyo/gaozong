"""GET /checks 权限门禁测试。"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.main import create_app
from app.models import DouyinLead, ReplyCheck


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _client(permissions: list[str]) -> TestClient:
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id="merchant-1",
        merchant_ids=["merchant-1"],
        permission_codes=permissions,
    )
    return TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


def test_list_checks_requires_leads_permission():
    client = _client([])
    with patch("app.routers.checks.reply_checker.list_checks") as mock_list:
        resp = client.get("/checks")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PERMISSION_DENIED"
    mock_list.assert_not_called()


def test_list_checks_with_leads_permission_enters_original_logic():
    client = _client(["auto_wechat:leads"])
    with patch("app.routers.checks.reply_checker.list_checks", return_value=[]) as mock_list:
        resp = client.get("/checks", params={"status": "pending"})
    assert resp.status_code == 200
    assert resp.json() == []
    mock_list.assert_called_once()


def test_list_checks_uses_context_merchant_and_ignores_forged_query_merchant_id():
    db = TestSession()
    try:
        lead_a = DouyinLead(customer_name="客户A", content="a", source_id="a", merchant_id="merchant-1")
        lead_b = DouyinLead(customer_name="客户B", content="b", source_id="b", merchant_id="merchant-other")
        db.add_all([lead_a, lead_b])
        db.flush()
        lead_a_id = lead_a.id
        db.add_all([
            ReplyCheck(lead_id=lead_a.id, staff_id=1, check_status="replied"),
            ReplyCheck(lead_id=lead_b.id, staff_id=2, check_status="replied"),
        ])
        db.commit()
    finally:
        db.close()

    resp = _client(["auto_wechat:leads"]).get(
        "/checks",
        params={"status": "replied", "merchant_id": "merchant-other"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["lead_id"] == lead_a_id
