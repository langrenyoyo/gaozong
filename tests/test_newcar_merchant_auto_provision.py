"""NewCar 商户首次登录自动开通本地 merchant_id 测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import app.models  # noqa: F401  注册 ORM 模型
from app.database import Base, get_db
from app.models import ExternalMerchantBinding


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client_with_newcar_me(monkeypatch, payload: dict) -> TestClient:
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    app = create_app()

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _newcar_payload(
    *,
    user_id="u-merchant-1",
    account="merchant-phone-like-13800000000",
    permissions=None,
    source_system="new_car_project",
):
    return {
        "ok": True,
        "account_scope": "external",
        "user": {"id": user_id, "account": account, "status": "active"},
        "permissions": permissions or ["auto_wechat:use", "auto_wechat:leads"],
        "merchant_id": None,
        "merchant_ids": [],
        "source_system": source_system,
    }


def _bindings():
    db = TestSession()
    try:
        return db.query(ExternalMerchantBinding).order_by(ExternalMerchantBinding.id.asc()).all()
    finally:
        db.close()


def test_merchant_permission_without_binding_auto_provisions_merchant(monkeypatch):
    client = _client_with_newcar_me(monkeypatch, _newcar_payload())

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["merchant_id"].startswith("m_nc_")
    assert data["merchant_ids"] == [data["merchant_id"]]
    assert data["merchant_id"] != "merchant-phone-like-13800000000"
    bindings = _bindings()
    assert len(bindings) == 1
    assert bindings[0].source_system == "new_car_project"
    assert bindings[0].external_user_id == "u-merchant-1"
    assert bindings[0].external_account == "merchant-phone-like-13800000000"
    assert bindings[0].merchant_id == data["merchant_id"]
    assert bindings[0].status == "active"


def test_existing_binding_is_reused_without_duplicate(monkeypatch):
    db = TestSession()
    try:
        db.add(
            ExternalMerchantBinding(
                source_system="new_car_project",
                external_user_id="u-merchant-1",
                external_account="old-name",
                merchant_id="merchant-existing",
                status="active",
            )
        )
        db.commit()
    finally:
        db.close()
    client = _client_with_newcar_me(monkeypatch, _newcar_payload(account="new-name"))

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 200
    assert resp.json()["data"]["merchant_id"] == "merchant-existing"
    bindings = _bindings()
    assert len(bindings) == 1
    assert bindings[0].external_account == "old-name"


def test_same_external_user_id_with_username_changed_keeps_merchant_id(monkeypatch):
    first = _client_with_newcar_me(monkeypatch, _newcar_payload(account="first-name"))
    first_resp = first.get("/auth/me", headers={"Authorization": "Bearer fake-token"})
    first_merchant_id = first_resp.json()["data"]["merchant_id"]

    second = _client_with_newcar_me(monkeypatch, _newcar_payload(account="second-name"))
    second_resp = second.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert second_resp.status_code == 200
    assert second_resp.json()["data"]["merchant_id"] == first_merchant_id
    assert len(_bindings()) == 1


def test_admin_only_does_not_create_merchant(monkeypatch):
    client = _client_with_newcar_me(
        monkeypatch,
        _newcar_payload(
            user_id="admin-1",
            account="admin-user",
            permissions=["auto_wechat:use", "auto_wechat:admin:autoreply"],
        ),
    )

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 200
    assert resp.json()["data"]["merchant_id"] is None
    assert _bindings() == []


def test_admin_and_merchant_permission_auto_provisions_merchant(monkeypatch):
    client = _client_with_newcar_me(
        monkeypatch,
        _newcar_payload(permissions=["auto_wechat:use", "auto_wechat:admin:autoreply", "auto_wechat:compute"]),
    )

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 200
    assert resp.json()["data"]["merchant_id"].startswith("m_nc_")
    assert len(_bindings()) == 1


def test_disabled_binding_with_merchant_permission_is_not_reactivated(monkeypatch):
    db = TestSession()
    try:
        db.add(
            ExternalMerchantBinding(
                source_system="new_car_project",
                external_user_id="u-merchant-1",
                external_account="old-name",
                merchant_id="merchant-disabled",
                status="disabled",
            )
        )
        db.commit()
    finally:
        db.close()
    client = _client_with_newcar_me(monkeypatch, _newcar_payload())

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "EXTERNAL_MERCHANT_NOT_BOUND"
    bindings = _bindings()
    assert len(bindings) == 1
    assert bindings[0].merchant_id == "merchant-disabled"
    assert bindings[0].status == "disabled"


def test_only_use_permission_does_not_create_merchant(monkeypatch):
    client = _client_with_newcar_me(monkeypatch, _newcar_payload(permissions=["auto_wechat:use"]))

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "EXTERNAL_MERCHANT_NOT_BOUND"
    assert _bindings() == []


def test_non_newcar_source_does_not_auto_provision_merchant(monkeypatch):
    client = _client_with_newcar_me(monkeypatch, _newcar_payload(source_system="other_system"))

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "EXTERNAL_MERCHANT_NOT_BOUND"
    assert _bindings() == []


def test_missing_external_user_id_with_merchant_permission_is_rejected(monkeypatch):
    client = _client_with_newcar_me(monkeypatch, _newcar_payload(user_id="", account="merchant-account"))

    resp = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "NEWCAR_AUTH_INVALID_RESPONSE"
    assert _bindings() == []


def test_generated_merchant_id_is_deterministic_and_does_not_leak_raw_values():
    from app.auth.external_merchant_binding_service import generate_newcar_merchant_id

    merchant_id = generate_newcar_merchant_id("external-user-123")

    assert merchant_id == generate_newcar_merchant_id("external-user-123")
    assert merchant_id.startswith("m_nc_")
    assert "external-user-123" not in merchant_id
    assert "merchant" not in merchant_id
    assert len(merchant_id) == len("m_nc_") + 16
