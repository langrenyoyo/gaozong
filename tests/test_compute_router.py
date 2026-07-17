"""小高算力一期 router 测试（P1-COMPUTE-BE-1）。

覆盖：
- 商户侧 /compute/*：summary（含权限/缺商户/过渡权限）、transactions、packages、recharge-orders
- 管理员侧 /admin/*：套餐 CRUD、给商户充值、发放套餐、非超管 403
- 内部 /internal/compute/usage：记录消耗、余额不拦截、令牌校验
- 商户隔离：merchant-a 看不到 merchant-b 的数据
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  触发 ORM 注册
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
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
    """每个测试前重建表，保证隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_compute_internal_token(monkeypatch):
    """清理环境 COMPUTE_INTERNAL_TOKEN，避免 .env.lan.local 的 token 污染 usage 测试。

    test_internal_token_enforced 自行 setenv 覆盖，不受影响。
    """
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)


def _seed_markup_ratio(capability_key="douyin-cs", basis=0, enabled=True):
    """写入一条上浮比例（默认不上浮），供 /internal/compute/usage 走 record_usage。"""
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


def _context(
    *,
    merchant_id: str = "merchant-a",
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
    user_id: str = "user-1",
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=user_id,
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:compute"],
        super_admin=super_admin,
    )


def _client(context: RequestContext | None = None) -> TestClient:
    """构造测试客户端；context 为 None 时不覆盖鉴权（用于 internal 端点）。"""
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


# ============ 商户侧 ============


def test_summary_returns_zero_for_new_merchant():
    client = _client(_context())
    resp = client.get("/compute/summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["merchant_id"] == "merchant-a"
    assert data["balance_tokens"] == 0


def test_summary_denied_without_permission():
    client = _client(_context(permission_codes=["auto_wechat:leads"]))
    resp = client.get("/compute/summary")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_summary_legacy_agent_permission_allowed():
    """auto_wechat:agent 为过渡兼容权限，应放行。"""
    client = _client(_context(permission_codes=["auto_wechat:agent"]))
    resp = client.get("/compute/summary")
    assert resp.status_code == 200


def test_transactions_after_recharge_and_consume():
    client = _client(_context())  # 商户
    admin = _client(_context(super_admin=True))
    admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 1000})

    # internal 上报消耗（不需要用户上下文）
    _seed_markup_ratio()
    internal = _client()
    internal.post(
        "/internal/compute/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 300,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o-mini",
            "remark": "douyin_ai_reply",
        },
    )

    resp = client.get("/compute/transactions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2  # recharge + consume

    item = data["items"][0]
    assert set(item) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert item["business_scene"] == "抖音自动回复"
    assert item["points_change"] == -300
    assert item["balance_after"] == 700

    summary = client.get("/compute/summary").json()["data"]
    assert summary["balance_tokens"] == 700
    assert summary["today_consume"] == 300
    assert summary["total_consume"] == 300


def test_merchant_packages_only_enabled():
    client = _client(_context())
    admin = _client(_context(super_admin=True))
    admin.post("/admin/compute/packages", json={"name": "启用", "price_yuan": 99, "token_amount": 100000, "enabled": True})
    admin.post("/admin/compute/packages", json={"name": "禁用", "price_yuan": 299, "token_amount": 350000, "enabled": False})

    resp = client.get("/compute/packages")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["data"]]
    assert names == ["启用"]


def test_recharge_order_mock_no_balance_change():
    client = _client(_context())
    admin = _client(_context(super_admin=True))
    admin.post("/admin/compute/packages", json={"name": "基础版", "price_yuan": 99, "token_amount": 100000, "enabled": True})

    resp = client.post("/compute/recharge-orders", json={"package_id": 1, "pay_method": "wechat"})
    assert resp.status_code == 200
    order = resp.json()["data"]
    assert order["tokens"] == 100000
    assert order["price_yuan"] == 99
    assert order["status"] == "mock_pending"
    assert order["order_no"].startswith("CO")

    # mock 不入账，余额仍为 0
    summary = client.get("/compute/summary").json()["data"]
    assert summary["balance_tokens"] == 0


def test_recharge_order_custom_tokens():
    client = _client(_context())
    resp = client.post("/compute/recharge-orders", json={"custom_tokens": 50000, "pay_method": "alipay"})
    assert resp.status_code == 200
    order = resp.json()["data"]
    assert order["tokens"] == 50000
    assert order["price_yuan"] is None


def test_recharge_order_requires_target():
    client = _client(_context())
    resp = client.post("/compute/recharge-orders", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RECHARGE_TARGET_REQUIRED"


def test_merchant_isolation():
    """商户 a 看不到商户 b 的余额与流水。"""
    admin = _client(_context(super_admin=True))
    admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 1000})
    admin.post("/admin/merchants/merchant-b/compute/recharge", json={"tokens": 500})

    client_a = _client(_context(merchant_id="merchant-a"))
    client_b = _client(_context(merchant_id="merchant-b"))

    assert client_a.get("/compute/summary").json()["data"]["balance_tokens"] == 1000
    assert client_b.get("/compute/summary").json()["data"]["balance_tokens"] == 500
    assert client_a.get("/compute/transactions").json()["data"]["total"] == 1
    a_items = client_a.get("/compute/transactions").json()["data"]["items"]
    assert len(a_items) == 1
    assert all(set(item) == {
        "id", "type", "type_label", "business_scene",
        "points_change", "balance_after", "created_at",
    } for item in a_items)


# ============ 管理员侧 ============


def test_admin_requires_super_admin():
    client = _client(_context(super_admin=False, permission_codes=["auto_wechat:compute"]))
    resp = client.get("/admin/compute/packages")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "SUPER_ADMIN_REQUIRED"


def test_admin_package_crud():
    admin = _client(_context(super_admin=True))

    # 创建
    resp = admin.post("/admin/compute/packages", json={"name": "基础版", "price_yuan": 99, "token_amount": 100000})
    assert resp.status_code == 200
    pkg = resp.json()["data"]
    assert pkg["id"] == 1
    assert pkg["enabled"] is True

    # 列表（管理员看全部）
    assert len(admin.get("/admin/compute/packages").json()["data"]) == 1

    # 更新
    resp = admin.put("/admin/compute/packages/1", json={"price_yuan": 199, "enabled": False})
    assert resp.status_code == 200
    updated = resp.json()["data"]
    assert updated["price_yuan"] == 199
    assert updated["enabled"] is False

    # 更新不存在
    resp = admin.put("/admin/compute/packages/9999", json={"price_yuan": 1})
    assert resp.status_code == 404


def test_admin_recharge_merchant():
    admin = _client(_context(super_admin=True))
    resp = admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 1000, "remark": "首次充值"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["balance_tokens"] == 1000
    assert data["merchant_id"] == "merchant-a"


def test_admin_compute_accounts_recharge_alias():
    """Phase 3-B 兼容目标路径 /admin/compute/accounts/{merchant_id}/recharge。"""
    admin = _client(_context(super_admin=True))
    resp = admin.post(
        "/admin/compute/accounts/merchant-a/recharge",
        json={"tokens": 1000, "remark": "路径兼容"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["balance_tokens"] == 1000


def test_admin_recharge_rejects_non_positive():
    """tokens=0 由 Pydantic gt=0 在 schema 阶段拦截（422）；service 层 ValueError 为防御性冗余，由 test_compute_service 直接验证。"""
    admin = _client(_context(super_admin=True))
    resp = admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 0})
    assert resp.status_code == 422


def test_admin_grant_package():
    admin = _client(_context(super_admin=True))
    admin.post("/admin/compute/packages", json={"name": "标准版", "price_yuan": 299, "token_amount": 350000})

    resp = admin.post("/admin/merchants/merchant-a/compute/grant-package", json={"package_id": 1})
    assert resp.status_code == 200
    assert resp.json()["data"]["balance_tokens"] == 350000


def test_admin_compute_accounts_grant_package_alias():
    """Phase 3-B 兼容目标路径 /admin/compute/accounts/{merchant_id}/grant-package。"""
    admin = _client(_context(super_admin=True))
    admin.post("/admin/compute/packages", json={"name": "标准版", "price_yuan": 299, "token_amount": 350000})

    resp = admin.post(
        "/admin/compute/accounts/merchant-a/grant-package",
        json={"package_id": 1},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["balance_tokens"] == 350000


def test_admin_grant_package_unknown():
    admin = _client(_context(super_admin=True))
    resp = admin.post("/admin/merchants/merchant-a/compute/grant-package", json={"package_id": 9999})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "PACKAGE_NOT_FOUND"


# ============ 内部 ============


def test_internal_usage_records_consume():
    admin = _client(_context(super_admin=True))
    admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 1000})

    _seed_markup_ratio()
    internal = _client()
    resp = internal.post(
        "/internal/compute/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 18,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o-mini",
            "usage_measurement_method": "provider_tokens",
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "cached_tokens": 4,
            "llm_call_stage": "primary",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
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


def test_internal_usage_no_balance_block():
    """一期不做余额拦截，余额为负也记录。"""
    _seed_markup_ratio()
    internal = _client()
    resp = internal.post(
        "/internal/compute/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 500,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["balance_tokens"] == -500


def test_internal_usage_rejects_invalid_source():
    """source 受 Literal 约束，非法值由 schema 层 422 拦截（service 的 INVALID_SOURCE 为防御冗余）。"""
    internal = _client()
    resp = internal.post(
        "/internal/compute/usage",
        json={
            "merchant_id": "merchant-a",
            "tokens": 100,
            "capability_key": "douyin-cs",
            "source": "invalid",
            "model": "gpt",
        },
    )
    assert resp.status_code == 422


def test_internal_token_enforced(monkeypatch):
    """配置 COMPUTE_INTERNAL_TOKEN 后，缺失/错误令牌 401，正确令牌放行。"""
    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "secret-token")
    internal = _client()
    payload = {
        "merchant_id": "merchant-a",
        "tokens": 100,
        "capability_key": "douyin-cs",
        "source": "llm",
        "model": "gpt",
    }

    # 无令牌
    resp = internal.post("/internal/compute/usage", json=payload)
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INTERNAL_TOKEN_INVALID"

    # 错误令牌
    resp = internal.post(
        "/internal/compute/usage", json=payload, headers={"X-Internal-Token": "wrong"}
    )
    assert resp.status_code == 401

    # 正确令牌（需比例行存在才能 record_usage 成功）
    _seed_markup_ratio()
    resp = internal.post(
        "/internal/compute/usage", json=payload, headers={"X-Internal-Token": "secret-token"}
    )
    assert resp.status_code == 200


def test_internal_token_production_fail_closed(monkeypatch):
    """生产环境（APP_ENV=production）未配置 COMPUTE_INTERNAL_TOKEN 时，usage 端点 500 fail-closed，
    避免任意 merchant_id 被自动建账扣费（Task 7-FIX1 Must-Fix 1）。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr("app.routers.compute.is_production_env", lambda: True)
    internal = _client()
    payload = {
        "merchant_id": "merchant-evil",
        "tokens": 100,
        "capability_key": "douyin-cs",
        "source": "llm",
        "model": "gpt",
    }
    resp = internal.post("/internal/compute/usage", json=payload)
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "INTERNAL_TOKEN_NOT_CONFIGURED"


def test_compute_transaction_openapi_hides_internal_fields():
    schema = _client(_context()).get("/openapi.json").json()
    transaction_schema = schema["components"]["schemas"]["ComputeTransactionOut"]
    properties = transaction_schema["properties"]
    assert set(properties) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert set(transaction_schema["required"]) == set(properties)
