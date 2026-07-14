"""Phase 10 Task 4：六能力上浮管理 API 与精确权限红灯。

覆盖四条路由：
- GET/PUT /admin/compute/markup-ratios（9000）
- GET/PUT /api/compute/admin/markup-ratios（9205）

权限矩阵：精确权限 auto_wechat:admin:compute_config / super_admin / mock 可读写；
仅 auto_wechat:compute、其他 admin 权限或无权限均 403。
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  触发 ORM 注册
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import ComputeMarkupRatio
from apps.compute.services import COMPUTE_CAPABILITY_KEYS

CONFIG_PERMISSION = "auto_wechat:admin:compute_config"

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_internal_token(monkeypatch):
    """清理 .env.lan.local 的 COMPUTE_INTERNAL_TOKEN 噪声。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)


def _seed_six_ratios(basis_map=None):
    """按冻结六能力顺序写入比例行（默认全 0/enabled）；basis_map 可覆盖特定键。"""
    db = TestSession()
    for key in COMPUTE_CAPABILITY_KEYS:
        basis = (basis_map or {}).get(key, 0)
        db.add(
            ComputeMarkupRatio(
                capability_key=key,
                markup_basis_points=basis,
                enabled=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
    db.commit()
    db.close()


def _client_9000(
    *,
    permission_codes=None,
    super_admin=False,
    mock=False,
    no_context=False,
    merchant_id="merchant-a",
) -> TestClient:
    """9000 主服务客户端；no_context=True 时跳过鉴权覆盖（供 internal 端点）。"""
    from app.main import create_app

    app = create_app()

    def _db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    if not no_context:
        ctx = RequestContext(
            user_id="u1",
            username="u1",
            merchant_id=merchant_id,
            merchant_ids=[merchant_id],
            permission_codes=permission_codes or [],
            super_admin=super_admin,
            auth_mode="mock" if mock else None,
        )
        app.dependency_overrides[get_request_context_required] = lambda: ctx
    return TestClient(app)


def _client_9205(*, permission_codes=None, super_admin=False, merchant_id="merchant-a") -> TestClient:
    """9205 能力服务客户端（gateway 注入上下文）。"""
    from apps.compute.dependencies import get_gateway_context
    from apps.compute.main import create_app

    app = create_app()

    def _db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": merchant_id,
        "tenant_id": "t",
        "user_id": "u",
        "super_admin": super_admin,
        "permission_codes": permission_codes or [],
    }
    return TestClient(app)


# ============ 9000 GET /admin/compute/markup-ratios ============


def test_9000_list_returns_six_in_frozen_order():
    _seed_six_ratios(basis_map={"douyin-cs": 3300})
    client = _client_9000(super_admin=True)
    resp = client.get("/admin/compute/markup-ratios")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert [i["capability_key"] for i in items] == list(COMPUTE_CAPABILITY_KEYS)
    douyin = next(i for i in items if i["capability_key"] == "douyin-cs")
    assert douyin["markup_basis_points"] == 3300


def test_9000_list_permission_matrix():
    _seed_six_ratios()
    # 放行：精确权限 / super_admin / mock
    assert _client_9000(permission_codes=[CONFIG_PERMISSION]).get("/admin/compute/markup-ratios").status_code == 200
    assert _client_9000(super_admin=True).get("/admin/compute/markup-ratios").status_code == 200
    assert _client_9000(mock=True).get("/admin/compute/markup-ratios").status_code == 200
    # 拒绝：仅 compute / 其他 admin / 无权限
    assert _client_9000(permission_codes=["auto_wechat:compute"]).get("/admin/compute/markup-ratios").status_code == 403
    assert _client_9000(permission_codes=["auto_wechat:admin:other"]).get("/admin/compute/markup-ratios").status_code == 403
    assert _client_9000().get("/admin/compute/markup-ratios").status_code == 403


# ============ 9000 PUT /admin/compute/markup-ratios/{capability_key} ============


def test_9000_update_accepts_valid_basis():
    _seed_six_ratios()
    admin = _client_9000(super_admin=True)
    for basis in (0, 3300, 2_147_483_647):
        resp = admin.put(
            "/admin/compute/markup-ratios/douyin-cs",
            json={"markup_basis_points": basis, "enabled": True},
        )
        assert resp.status_code == 200, (basis, resp.text)
        assert resp.json()["data"]["markup_basis_points"] == basis


def test_9000_update_rejects_negative_and_overflow():
    _seed_six_ratios()
    admin = _client_9000(super_admin=True)
    resp = admin.put(
        "/admin/compute/markup-ratios/douyin-cs",
        json={"markup_basis_points": -1, "enabled": True},
    )
    assert resp.status_code == 422
    resp = admin.put(
        "/admin/compute/markup-ratios/douyin-cs",
        json={"markup_basis_points": 2_147_483_648, "enabled": True},
    )
    assert resp.status_code == 422


def test_9000_update_rejects_unknown_capability():
    _seed_six_ratios()
    admin = _client_9000(super_admin=True)
    resp = admin.put(
        "/admin/compute/markup-ratios/unknown",
        json={"markup_basis_points": 100, "enabled": True},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_CAPABILITY"


def test_9000_update_rejects_extra_field():
    """extra=forbid：不允许通过 body 改 capability_key 或塞额外字段。"""
    _seed_six_ratios()
    admin = _client_9000(super_admin=True)
    resp = admin.put(
        "/admin/compute/markup-ratios/douyin-cs",
        json={"markup_basis_points": 100, "enabled": True, "capability_key": "leads"},
    )
    assert resp.status_code == 422


def test_9000_update_requires_permission():
    _seed_six_ratios()
    resp = _client_9000(permission_codes=["auto_wechat:compute"]).put(
        "/admin/compute/markup-ratios/douyin-cs",
        json={"markup_basis_points": 100, "enabled": True},
    )
    assert resp.status_code == 403


def test_9000_update_affects_new_usage_not_old_snapshot():
    """更新比例后新 consume 用新比例，旧流水快照保持不变。"""
    _seed_six_ratios(basis_map={"douyin-cs": 0})
    admin = _client_9000(super_admin=True)
    admin.post("/admin/merchants/merchant-a/compute/recharge", json={"tokens": 100000})

    internal = _client_9000(no_context=True)
    # 旧 usage：basis=0，billed=tokens
    internal.post(
        "/internal/compute/usage",
        json={"merchant_id": "merchant-a", "tokens": 1000, "capability_key": "douyin-cs", "source": "llm", "model": "gpt"},
    )
    # 更新 douyin-cs 为 3300
    admin.put(
        "/admin/compute/markup-ratios/douyin-cs",
        json={"markup_basis_points": 3300, "enabled": True},
    )
    # 新 usage：basis=3300，billed=1330
    internal.post(
        "/internal/compute/usage",
        json={"merchant_id": "merchant-a", "tokens": 1000, "capability_key": "douyin-cs", "source": "llm", "model": "gpt"},
    )

    txs = admin.get("/compute/transactions?transaction_type=consume").json()["data"]["items"]
    assert len(txs) == 2
    # id 倒序：最新在前（markup=3300/delta=-1330），旧（markup=0/delta=-1000）
    assert txs[0]["markup_basis_points"] == 3300
    assert txs[0]["delta_tokens"] == -1330
    assert txs[0]["actual_tokens"] == 1000
    assert txs[1]["markup_basis_points"] == 0
    assert txs[1]["delta_tokens"] == -1000


# ============ 9205 GET/PUT /api/compute/admin/markup-ratios ============


def test_9205_list_returns_six():
    _seed_six_ratios()
    client = _client_9205(super_admin=True)
    resp = client.get("/api/compute/admin/markup-ratios")
    assert resp.status_code == 200
    assert [i["capability_key"] for i in resp.json()["data"]] == list(COMPUTE_CAPABILITY_KEYS)


def test_9205_update_and_permission():
    _seed_six_ratios()
    admin = _client_9205(super_admin=True)
    resp = admin.put(
        "/api/compute/admin/markup-ratios/leads",
        json={"markup_basis_points": 500, "enabled": False},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["markup_basis_points"] == 500
    assert data["enabled"] is False

    # 精确权限放行
    assert _client_9205(permission_codes=[CONFIG_PERMISSION]).get("/api/compute/admin/markup-ratios").status_code == 200
    # 仅 compute 拒绝
    assert _client_9205(permission_codes=["auto_wechat:compute"]).get("/api/compute/admin/markup-ratios").status_code == 403


def test_list_drift_when_rows_missing():
    """缺行视为配置漂移，返回稳定错误（不自动补写）。"""
    client = _client_9000(super_admin=True)
    resp = client.get("/admin/compute/markup-ratios")
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "MARKUP_RATIO_DRIFT"
