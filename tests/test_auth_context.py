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
