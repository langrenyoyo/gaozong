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


# 算力配置精确权限（与 apps/compute/dependencies.py 保持一致）
CONFIG_PERMISSION = "auto_wechat:admin:compute_config"


def _config_admin_client() -> TestClient:
    """仅持精确权限、无 super_admin、无 merchant_id 的算力配置管理员客户端。"""
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
        "merchant_id": None,
        "tenant_id": "tenant-a",
        "user_id": "config-admin",
        "super_admin": False,
        "permission_codes": [CONFIG_PERMISSION],
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


def test_compute_app_transactions_use_merchant_public_contract():
    admin = _admin_client()
    admin.post(
        "/api/compute/admin/accounts/merchant-a/recharge",
        json={"tokens": 1000, "remark": "internal-secret"},
    )

    response = _client().get("/api/compute/transactions")

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert set(item) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert item["business_scene"] == "算力充值"
    assert "internal-secret" not in repr(item)


# ============ Task 3：精确权限管理员 + 网关上下文解析顺序 ============


def _seed_six_capability_ratios():
    """按冻结六能力顺序写入比例行，供比例接口读取。"""
    from apps.compute.services import COMPUTE_CAPABILITY_KEYS

    db = TestSession()
    for key in COMPUTE_CAPABILITY_KEYS:
        db.add(
            ComputeMarkupRatio(
                capability_key=key,
                markup_basis_points=0,
                enabled=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
    db.commit()
    db.close()


def test_gateway_context_allows_compute_config_admin_without_merchant():
    """仅持精确权限、无商户编号、非超管也能通过网关上下文解析（不被 401 阻断）。"""
    from apps.compute.dependencies import get_gateway_context

    context = get_gateway_context(
        x_gateway_merchant_id=None,
        x_gateway_tenant_id="tenant-a",
        x_gateway_user_id="config-admin",
        x_gateway_permissions="auto_wechat:admin:compute_config",
        x_gateway_super_admin=None,
    )
    assert context["merchant_id"] is None
    assert context["super_admin"] is False
    assert context["permission_codes"] == ["auto_wechat:admin:compute_config"]


def test_gateway_context_rejects_plain_merchant_without_merchant():
    """仅 auto_wechat:compute 且无商户编号仍必须 401 GATEWAY_CONTEXT_REQUIRED。"""
    from apps.compute.dependencies import get_gateway_context
    from fastapi import HTTPException
    import pytest as _pytest

    with _pytest.raises(HTTPException) as exc_info:
        get_gateway_context(
            x_gateway_merchant_id=None,
            x_gateway_tenant_id="tenant-a",
            x_gateway_user_id="u",
            x_gateway_permissions="auto_wechat:compute",
            x_gateway_super_admin=None,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "GATEWAY_CONTEXT_REQUIRED"


def test_compute_config_admin_manages_packages_and_points_without_merchant():
    """仅持精确权限的管理员可创建/查询/更新/禁用套餐，并充值、发放、读写比例。"""
    admin = _config_admin_client()

    # 创建套餐
    created = admin.post(
        "/api/compute/admin/packages",
        json={"name": "标准版", "price_yuan": 299, "token_amount": 350000},
    )
    assert created.status_code == 200
    package_id = created.json()["data"]["id"]

    # 查询
    listed = admin.get("/api/compute/admin/packages")
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    # 更新
    updated = admin.put(
        f"/api/compute/admin/packages/{package_id}",
        json={"price_yuan": 399, "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["price_yuan"] == 399

    # 充值 + 发放
    assert admin.post(
        "/api/compute/admin/accounts/merchant-a/recharge",
        json={"tokens": 1000, "remark": "审批备注"},
    ).status_code == 200
    assert admin.post(
        "/api/compute/admin/accounts/merchant-a/grant-package",
        json={"package_id": package_id},
    ).status_code == 200

    # 禁用套餐
    disabled = admin.delete(f"/api/compute/admin/packages/{package_id}")
    assert disabled.status_code == 200
    assert disabled.json()["data"]["enabled"] is False

    # 比例读写
    _seed_six_capability_ratios()
    assert admin.get("/api/compute/admin/markup-ratios").status_code == 200
    ratio = admin.put(
        "/api/compute/admin/markup-ratios/douyin-cs",
        json={"markup_basis_points": 3300, "enabled": True},
    )
    assert ratio.status_code == 200
    assert ratio.json()["data"]["markup_basis_points"] == 3300


def test_compute_app_disable_package_logs_structured_action(caplog):
    """禁用套餐写结构化日志：operation=disable_package，不泄露请求头或内部令牌。"""
    caplog.set_level("INFO", logger="apps.compute.routers")
    admin = _config_admin_client()
    created = admin.post(
        "/api/compute/admin/packages",
        json={"name": "标准版", "price_yuan": 299, "token_amount": 350000},
    )
    package_id = created.json()["data"]["id"]

    caplog.clear()
    caplog.set_level("INFO", logger="apps.compute.routers")
    resp = admin.delete(f"/api/compute/admin/packages/{package_id}")
    assert resp.status_code == 200
    messages = [record.getMessage() for record in caplog.records]
    assert any("compute_admin_action" in message for message in messages)
    assert any("operation=disable_package" in message for message in messages)
    assert any("status=success" in message for message in messages)
    assert all("X-Internal-Token" not in message for message in messages)
    assert all("Authorization" not in message for message in messages)


def test_compute_app_unauthorized_write_logs_failure_without_token(caplog):
    """无权限写入失败也留失败日志，且不记录请求头或内部令牌。"""
    caplog.set_level("WARNING", logger="apps.compute.routers")
    # 仅商户权限、无商户编号 -> 网关上下文 401，不进路由日志
    # 改用有商户编号但仅 compute 权限的客户端触发 403 失败日志
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
        "user_id": "merchant-user",
        "super_admin": False,
        "permission_codes": ["auto_wechat:compute"],
    }
    client = TestClient(app)
    resp = client.post(
        "/api/compute/admin/packages",
        json={"name": "越权", "price_yuan": 99, "token_amount": 100},
    )
    assert resp.status_code == 403
    messages = [record.getMessage() for record in caplog.records]
    assert any("status=failed" in message for message in messages)
    assert all("X-Internal-Token" not in message for message in messages)
    assert all("Authorization" not in message for message in messages)
