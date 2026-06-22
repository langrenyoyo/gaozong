import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


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
        "NEWCAR_AUTH_INTROSPECT_URL",
        "NEWCAR_AUTH_LOGIN_URL",
        "NEWCAR_AUTH_SERVICE_TOKEN",
        "NEWCAR_AUTH_TIMEOUT_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)

    import app.config as config

    reloaded = importlib.reload(config)
    assert reloaded.NEWCAR_AUTH_ENABLED is False
    assert reloaded.NEWCAR_AUTH_MOCK_ENABLED is True
    assert reloaded.NEWCAR_AUTH_TIMEOUT_SECONDS == 5


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
        "auto_wechat:knowledge_training",
        "auto_wechat:knowledge",
        "auto_wechat:compute",
        "auto_wechat:admin:compute_config",
    }


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


def test_real_introspect_token_builds_trusted_context(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")
    monkeypatch.setenv("NEWCAR_AUTH_SERVICE_TOKEN", "svc-token")

    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "data": {
                    "user_id": "u-100",
                    "username": "merchant-user",
                    "display_name": "商户用户",
                    "merchant_id": "merchant-real",
                    "permission_codes": ["auto_wechat:use", "auto_wechat:leads"],
                    "role_codes": ["merchant_admin"],
                    "session_id": "sess-real",
                },
            }

    def fake_post(url, *, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)

    from app.main import create_app

    response = TestClient(create_app()).get(
        "/auth/me",
        params={"merchant_id": "forged-merchant"},
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "u-100"
    assert data["merchant_id"] == "merchant-real"
    assert data["merchant_ids"] == ["merchant-real"]
    assert data["source_system"] == "new_car_project"
    assert data["permission_codes"] == ["auto_wechat:use", "auto_wechat:leads"]
    assert calls == [
        {
            "url": "https://newcar.example.test/auth/introspect",
            "json": {"credential_type": "token", "credential": "real-token"},
            "headers": {"X-NewCar-Service-Token": "svc-token"},
            "timeout": 5,
        }
    ]


def test_real_introspect_cookie_accepts_direct_payload(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "user_id": "u-cookie",
                "merchant_id": "merchant-cookie",
                "merchant_ids": ["merchant-cookie", "merchant-extra"],
                "permission_codes": ["auto_wechat:compute"],
                "source_system": "new_car_project",
            }

    def fake_post(url, *, json, headers, timeout):
        assert json == {"credential_type": "cookie", "credential": "cookie-value"}
        assert headers == {}
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)

    from app.main import create_app

    response = TestClient(create_app()).get(
        "/auth/me",
        cookies={"newcar_session": "cookie-value"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user_id"] == "u-cookie"
    assert data["merchant_id"] == "merchant-cookie"
    assert data["merchant_ids"] == ["merchant-cookie", "merchant-extra"]
    assert data["permission_codes"] == ["auto_wechat:compute"]


def test_real_introspect_code_uses_code_credential(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")

    seen = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"user_id": "u-code", "merchant_id": "merchant-code"}}

    def fake_post(url, *, json, headers, timeout):
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me", params={"code": "login-code"})

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == "u-code"
    assert seen["json"] == {"credential_type": "code", "credential": "login-code"}


def test_real_introspect_plain_authorization_is_token(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")

    seen = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"user_id": "u-token", "merchant_id": "merchant-token"}}

    def fake_post(url, *, json, headers, timeout):
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me", headers={"Authorization": "plain-token"})

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == "u-token"
    assert seen["json"] == {"credential_type": "token", "credential": "plain-token"}


def test_real_introspect_timeout_returns_unavailable(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")

    import httpx

    def fake_post(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", fake_post)

    from app.main import create_app

    response = TestClient(create_app()).get("/auth/me", headers={"Authorization": "Bearer real-token"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "NEWCAR_AUTH_UNAVAILABLE"


def test_real_introspect_rejects_missing_user_id(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_INTROSPECT_URL", "https://newcar.example.test/auth/introspect")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"merchant_id": "merchant-real"}}

    monkeypatch.setattr("app.auth.newcar_client.httpx.post", lambda *args, **kwargs: FakeResponse())

    from app.main import create_app

    response = TestClient(create_app()).get(
        "/auth/me",
        headers={"Authorization": "Bearer real-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "NEWCAR_AUTH_INVALID_RESPONSE"
