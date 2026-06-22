"""小高算力独立能力服务测试（Phase 3-B）。

覆盖 9205 compute 服务的健康检查、新能力路径、mock 充值边界和 usage 扣费语义。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base, get_db


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    """每个测试前重建表，保证独立能力服务测试隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client() -> TestClient:
    from apps.compute.main import create_app
    from apps.compute.dependencies import get_gateway_context

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": "merchant-a",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "super_admin": False,
        "permission_codes": ["auto_wechat:compute"],
    }
    return TestClient(app)


def _admin_client() -> TestClient:
    from apps.compute.main import create_app
    from apps.compute.dependencies import get_gateway_context

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": "admin-merchant",
        "tenant_id": "tenant-a",
        "user_id": "admin-a",
        "super_admin": True,
        "permission_codes": ["auto_wechat:compute"],
    }
    return TestClient(app)


def test_compute_app_root_health_and_openapi():
    client = _client()

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "compute"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "小高算力"


def test_compute_app_packages_and_summary_use_gateway_context():
    client = _client()

    packages = client.get("/api/compute/packages")
    assert packages.status_code == 200
    assert packages.json()["data"] == []

    summary = client.get("/api/compute/summary")
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["merchant_id"] == "merchant-a"
    assert data["balance_tokens"] == 0


def test_compute_app_admin_accounts_paths_and_mock_order_boundary():
    admin = _admin_client()
    package_resp = admin.post(
        "/api/compute/admin/packages",
        json={"name": "基础版", "price_yuan": 99, "token_amount": 100000},
    )
    assert package_resp.status_code == 200
    assert package_resp.json()["data"]["id"] == 1

    recharge = admin.post(
        "/api/compute/admin/accounts/merchant-a/recharge",
        json={"tokens": 1000, "remark": "测试充值"},
    )
    assert recharge.status_code == 200
    assert recharge.json()["data"]["balance_tokens"] == 1000

    client = _client()
    order = client.post(
        "/api/compute/recharge-orders",
        json={"package_id": 1, "pay_method": "wechat"},
    )
    assert order.status_code == 200
    order_data = order.json()["data"]
    assert order_data["status"] == "mock_pending"
    assert order_data["pay_qr_code"].startswith("mock://pay/")
    assert "payment_url" not in order_data
    assert "paid_at" not in order_data

    # mock 订单不真实入账，余额仍保持管理员充值后的 1000。
    summary = client.get("/api/compute/summary").json()["data"]
    assert summary["balance_tokens"] == 1000


def test_compute_app_internal_usage_keeps_existing_deduct_semantics():
    admin = _admin_client()
    admin.post(
        "/api/compute/admin/accounts/merchant-a/recharge",
        json={"tokens": 1000},
    )

    client = _client()
    usage = client.post(
        "/api/compute/internal/usage",
        json={"merchant_id": "merchant-a", "tokens": 300, "source": "llm"},
    )
    assert usage.status_code == 200
    data = usage.json()["data"]
    assert data["balance_tokens"] == 700
    assert data["today_consume"] == 300
