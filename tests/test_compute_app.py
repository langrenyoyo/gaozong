"""小高算力独立能力服务测试（Phase 3-B）。

覆盖 9205 compute 服务的健康检查、新能力路径、mock 充值边界和 usage 扣费语义。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base, get_db
from app.models import ComputeMarkupRatio, ComputeTransaction
from datetime import datetime


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


@pytest.fixture(autouse=True)
def _isolate_compute_internal_token(monkeypatch):
    """清理环境 COMPUTE_INTERNAL_TOKEN，避免 .env.lan.local 的 token 污染 usage 测试。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)


def _seed_markup_ratio(capability_key="douyin-cs", basis=0, enabled=True):
    """写入一条上浮比例（默认不上浮），供 /api/compute/internal/usage 走 record_usage。"""
    db = TestSession()
    db.add(
        ComputeMarkupRatio(
            capability_key=capability_key,
            markup_basis_points=basis,
            enabled=enabled,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    )
    db.commit()
    db.close()


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

    _seed_markup_ratio()
    client = _client()
    usage = client.post(
        "/api/compute/internal/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 18,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o",
            "usage_measurement_method": "provider_tokens",
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "cached_tokens": 4,
            "llm_call_stage": "primary",
        },
    )
    assert usage.status_code == 200
    data = usage.json()["data"]
    assert data["balance_tokens"] == 982
    assert data["today_consume"] == 18
    db = TestSession()
    tx = db.query(ComputeTransaction).filter_by(transaction_type="consume").one()
    assert tx.usage_measurement_method == "provider_tokens"
    assert tx.prompt_tokens == 12
    assert tx.completion_tokens == 6
    assert tx.cached_tokens == 4
    assert tx.llm_call_stage == "primary"
    db.close()


def test_internal_usage_production_fail_closed(monkeypatch):
    """9205 生产环境未配置 COMPUTE_INTERNAL_TOKEN 时，usage 端点 500 fail-closed（Task 7-FIX1 Must-Fix 1）。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr("apps.compute.routers.is_production_env", lambda: True)
    _seed_markup_ratio()
    client = _client()
    resp = client.post(
        "/api/compute/internal/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 100,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o",
        },
    )
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "INTERNAL_TOKEN_NOT_CONFIGURED"
