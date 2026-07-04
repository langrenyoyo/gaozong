import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  注册 ORM 模型到 Base.metadata
from app.database import Base, get_db


auth_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AuthTestSession = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)


def _reset_auth_db():
    Base.metadata.drop_all(bind=auth_engine)
    Base.metadata.create_all(bind=auth_engine)


def _override_auth_db(app):
    def _get_db():
        db = AuthTestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    return app


def _insert_external_binding(
    *,
    source_system: str = "new_car_project",
    external_user_id: str | None = "u-code",
    external_account: str | None = "code-user",
    merchant_id: str = "merchant-bound",
    status: str = "active",
):
    db = AuthTestSession()
    try:
        db.execute(
            text(
                "INSERT INTO external_merchant_bindings "
                "(source_system, external_user_id, external_account, merchant_id, status, created_at, updated_at) "
                "VALUES (:source_system, :external_user_id, :external_account, :merchant_id, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "source_system": source_system,
                "external_user_id": external_user_id,
                "external_account": external_account,
                "merchant_id": merchant_id,
                "status": status,
            },
        )
        db.commit()
    finally:
        db.close()


def test_request_context_can_be_created():
    from app.auth.context import RequestContext

    context = RequestContext(
        user_id="u_1",
        username="zhangsan",
        display_name="张三",
        merchant_id="m_1",
        merchant_ids=["m_1"],
        role_codes=["merchant_admin"],
        permission_codes=["auto_wechat:use"],
        super_admin=False,
        merchant_status="active",
        session_id="sess_1",
        request_id="req_1",
    )

    assert context.user_id == "u_1"
    assert context.source_system == "new_car_project"
    assert context.has_permission("auto_wechat:use") is True


def test_permission_codes_and_super_admin():
    from app.auth.context import RequestContext

    user = RequestContext(
        user_id="u_1",
        permission_codes=["auto_wechat:leads"],
        merchant_ids=["m_1"],
    )
    admin = RequestContext(
        user_id="admin",
        super_admin=True,
        merchant_ids=[],
    )

    assert user.has_permission("auto_wechat:leads") is True
    assert user.has_permission("auto_wechat:compute") is False
    assert admin.has_permission("auto_wechat:compute") is True
    assert admin.has_merchant_access("any-merchant") is True


def test_auth_config_defaults_do_not_block_dev(monkeypatch):
    for key in [
        "NEWCAR_AUTH_ENABLED",
        "NEWCAR_AUTH_MOCK_ENABLED",
        "NEWCAR_AUTH_BASE_URL",
        "CORS_ORIGINS",
        "NEWCAR_AUTH_EXCHANGE_CODE_URL",
        "NEWCAR_AUTH_ME_URL",
        "NEWCAR_AUTH_LOGIN_URL",
        "NEWCAR_AUTH_SERVICE_TOKEN",
        "NEWCAR_AUTH_TIMEOUT_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")

    import app.config as config

    reloaded = importlib.reload(config)
    assert reloaded.NEWCAR_AUTH_ENABLED is False
    assert reloaded.NEWCAR_AUTH_MOCK_ENABLED is True
    assert reloaded.NEWCAR_AUTH_TIMEOUT_SECONDS == 5


def test_cors_origins_can_be_overridden_and_allow_newcar_login_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://192.168.110.19:5174")

    import app.config as config

    reloaded_config = importlib.reload(config)
    assert reloaded_config.CORS_ORIGINS == ("http://192.168.110.19:5174",)

    import app.main as main

    reloaded_main = importlib.reload(main)
    client = TestClient(reloaded_main.create_app())
    response = client.options(
        "/auth/me",
        headers={
            "Origin": "http://192.168.110.19:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.110.19:5174"


def test_default_cors_origins_keep_lan_newcar_and_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    import app.config as config

    reloaded_config = importlib.reload(config)
    assert set(reloaded_config.CORS_ORIGINS) >= {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://192.168.110.113:5173",
        "http://192.168.110.113:9000",
        "http://192.168.110.19:5174",
    }


def test_mock_newcar_client_returns_context():
    from app.auth.newcar_client import NewCarProjectAuthClient

    client = NewCarProjectAuthClient(auth_enabled=False, mock_enabled=True)
    context = client.build_mock_context(merchant_id="m_2", permission_codes=["auto_wechat:agent"])

    assert context.user_id == "dev-user"
    assert context.merchant_id == "m_2"
    assert context.has_permission("auto_wechat:agent") is True


def test_mock_newcar_client_default_permissions_cover_current_features():
    from app.auth.newcar_client import NewCarProjectAuthClient

    client = NewCarProjectAuthClient(auth_enabled=False, mock_enabled=True)
    context = client.build_mock_context()

    assert set(context.permission_codes) >= {
        "auto_wechat:use",
        "auto_wechat:leads",
        "auto_wechat:douyin_ai_cs",
        "auto_wechat:wechat_assistant",
        "auto_wechat:agent",
        "auto_wechat:ai_agents",
        "auto_wechat:compute",
        "auto_wechat:admin:compute_config",
    }
    assert "auto_wechat:knowledge_training" not in context.permission_codes
    assert "auto_wechat:knowledge" not in context.permission_codes


def test_required_context_missing_token_returns_401(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")

    from app.auth.dependencies import get_request_context_required

    app = FastAPI()

    @app.get("/probe")
    def probe(context=Depends(get_request_context_required)):
        return {"user_id": context.user_id}

    response = TestClient(app).get("/probe")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_MISSING"


def test_require_permission_denies_missing_permission():
    from app.auth.context import RequestContext
    from app.auth.dependencies import require_permission

    checker = require_permission("auto_wechat:douyin_ai_cs")
    context = RequestContext(user_id="u_1", permission_codes=["auto_wechat:leads"])

    with pytest.raises(Exception) as exc_info:
        checker(context)

    assert getattr(exc_info.value, "status_code") == 403
    assert exc_info.value.detail["code"] == "PERMISSION_DENIED"


def test_require_any_permission_allows_one_matching_permission():
    from app.auth.context import RequestContext
    from app.auth.dependencies import require_any_permission

    checker = require_any_permission(["auto_wechat:compute", "auto_wechat:agent"])
    context = RequestContext(user_id="u_1", permission_codes=["auto_wechat:agent"])

    assert checker(context) is context


def test_require_merchant_access_denies_outside_merchant():
    from app.auth.context import RequestContext
    from app.auth.dependencies import require_merchant_access

    context = RequestContext(user_id="u_1", merchant_id="m_1", merchant_ids=["m_1"])

    with pytest.raises(Exception) as exc_info:
        require_merchant_access("m_2", context)

    assert getattr(exc_info.value, "status_code") == 403
    assert exc_info.value.detail["code"] == "PERMISSION_DENIED"


def test_auth_me_returns_mock_context_in_dev_mode(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "dev-user"
    assert data["merchant_id"] == "dev-merchant"


def test_auth_me_required_mode_accepts_bearer_token(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")

    from app.main import create_app

    response = TestClient(create_app()).get(
        "/auth/me",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["session_id"] == "token:test-token"


def test_external_auth_token_me_builds_trusted_context(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="100",
        external_account="merchant-user",
        merchant_id="merchant-local",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "expires_at": "2026-06-29T10:00:00+08:00",
                "user": {
                    "id": 100,
                    "account": "merchant-user",
                    "name": "商户用户",
                    "status": "active",
                    "account_scope": "external",
                },
                "permissions": ["auto_wechat:use", "auto_wechat:leads"],
                "permission_items": [],
                "merchant_id": "merchant-real",
                "merchant_ids": ["merchant-real"],
            }

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", fake_get)

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        params={"merchant_id": "forged-merchant"},
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "100"
    assert data["merchant_id"] == "merchant-local"
    assert data["merchant_ids"] == ["merchant-local", "merchant-real"]
    assert data["source_system"] == "new_car_project"
    assert data["permission_codes"] == ["auto_wechat:use", "auto_wechat:leads"]
    assert calls == [
        {
            "url": "https://newcar.example.test/api/external-auth/me",
            "headers": {"Authorization": "Bearer real-token"},
            "timeout": 5,
        }
    ]


def test_external_auth_cookie_uses_me_endpoint(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="u-cookie",
        external_account="cookie-user",
        merchant_id="merchant-local-cookie",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")
    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "user": {"id": "u-cookie", "account": "cookie-user", "name": "Cookie 用户", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:compute"],
                "merchant_id": "merchant-cookie",
                "merchant_ids": ["merchant-cookie", "merchant-extra"],
            }

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers})
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", fake_get)

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        cookies={"newcar_session": "cookie-value"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "u-cookie"
    assert data["merchant_id"] == "merchant-local-cookie"
    assert data["merchant_ids"] == ["merchant-local-cookie", "merchant-cookie", "merchant-extra"]
    assert data["permission_codes"] == ["auto_wechat:use", "auto_wechat:compute"]
    assert calls == [
        {
            "url": "https://newcar.example.test/api/external-auth/me",
            "headers": {"Authorization": "Bearer cookie-value"},
        }
    ]


def test_external_auth_code_exchanges_token_then_loads_me(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="u-code",
        external_account="code-user",
        merchant_id="merchant-code-local",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    calls = []

    class FakeExchangeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "token": "exchanged-token",
                "token_type": "Bearer",
                "user": {"id": "u-code", "account": "code-user", "name": "Code 用户", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:leads"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    class FakeMeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "name": "Code 用户", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:leads"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    def fake_post(url, *, json, headers, timeout):
        calls.append({"method": "POST", "url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeExchangeResponse()

    def fake_get(url, *, headers, timeout):
        calls.append({"method": "GET", "url": url, "headers": headers, "timeout": timeout})
        return FakeMeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)
    monkeypatch.setattr("app.auth.newcar_client.httpx.get", fake_get)

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get("/auth/me", params={"code": "login-code"})

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == "u-code"
    assert response.json()["data"]["merchant_id"] == "merchant-code-local"
    assert calls == [
        {
            "method": "POST",
            "url": "https://newcar.example.test/api/external-auth/exchange-code",
            "json": {"code": "login-code", "platform": "auto_wechat", "device_name": "auto_wechat_backend"},
            "headers": {},
            "timeout": 5,
        },
        {
            "method": "GET",
            "url": "https://newcar.example.test/api/external-auth/me",
            "headers": {"Authorization": "Bearer exchanged-token"},
            "timeout": 5,
        },
    ]


def test_auth_me_uses_local_binding_by_external_user_id(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="u-code",
        external_account="code-user",
        merchant_id="merchant-local",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:leads"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
        params={"merchant_id": "forged-merchant"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["merchant_id"] == "merchant-local"
    assert data["merchant_ids"] == ["merchant-local"]


def test_auth_me_falls_back_to_external_account_binding(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="another-user",
        external_account="code-user",
        merchant_id="merchant-by-account",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:use"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["merchant_id"] == "merchant-by-account"


@pytest.mark.parametrize("status", ["disabled", "deleted"])
def test_auth_me_rejects_inactive_local_binding(monkeypatch, status):
    _reset_auth_db()
    _insert_external_binding(status=status)
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:use"],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "EXTERNAL_MERCHANT_NOT_BOUND",
        "message": "账号未绑定商户，请联系管理员。",
    }


def test_auth_me_rejects_missing_local_binding(monkeypatch):
    _reset_auth_db()
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:use"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "EXTERNAL_MERCHANT_NOT_BOUND"


def test_auth_me_allows_admin_permission_without_local_merchant_binding(monkeypatch):
    _reset_auth_db()
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "admin-autoreply", "account": "admin-user", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:admin:autoreply"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "admin-autoreply"
    assert data["merchant_id"] is None
    assert data["permission_codes"] == ["auto_wechat:use", "auto_wechat:admin:autoreply"]


def test_auth_me_missing_use_permission_wins_before_binding(monkeypatch):
    _reset_auth_db()
    _insert_external_binding()
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:leads"],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_auth_callback_returns_exchanged_token_for_frontend_storage(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeExchangeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "token": "frontend-token"}

    class FakeMeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "account_scope": "external",
                "user": {"id": "u-code", "account": "code-user", "status": "active"},
                "permissions": ["auto_wechat:use", "auto_wechat:leads"],
                "merchant_id": None,
                "merchant_ids": [],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", lambda *args, **kwargs: FakeExchangeResponse())
    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeMeResponse())

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/callback", params={"code": "login-code"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["token"] == "frontend-token"
    assert data["user_id"] == "u-code"
    assert data["permission_codes"] == ["auto_wechat:use", "auto_wechat:leads"]


def test_external_auth_plain_authorization_is_token(monkeypatch):
    _reset_auth_db()
    _insert_external_binding(
        external_user_id="u-token",
        external_account="token-user",
        merchant_id="merchant-token-local",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    seen = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "user": {"id": "u-token", "account": "token-user", "status": "active"},
                "permissions": ["auto_wechat:use"],
                "merchant_id": "merchant-token",
            }

    def fake_get(url, *, headers, timeout):
        seen["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", fake_get)

    from app.main import create_app

    response = TestClient(_override_auth_db(create_app())).get("/auth/me", headers={"Authorization": "plain-token"})

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == "u-token"
    assert seen["headers"] == {"Authorization": "Bearer plain-token"}


def test_external_auth_me_timeout_returns_unavailable(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    import httpx

    def fake_get(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", fake_get)

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me", headers={"Authorization": "Bearer real-token"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "NEWCAR_AUTH_UNAVAILABLE"


def test_external_auth_me_rejects_missing_user_id(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "permissions": ["auto_wechat:use"], "merchant_id": "merchant-real"}

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(create_app()).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "NEWCAR_AUTH_INVALID_RESPONSE"


def test_external_auth_rejects_missing_use_permission(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "user": {"id": "u-no-use", "account": "no-use", "status": "active"},
                "permissions": ["auto_wechat:leads"],
            }

    monkeypatch.setattr("app.auth.newcar_client.httpx.get", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me", headers={"Authorization": "Bearer real-token"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
