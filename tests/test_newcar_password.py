"""9000 商户改密门面与 NewCarProject 改密代理合同回归。

覆盖：
- NewCarProjectAuthClient.change_external_password() 真实模式只发两个密码字段、Bearer + 服务头、
  现有超时；401/403/400/5xx 转为无敏感明文的 NewCarAuthError；mock 模式不访问网络。
- 9000 POST /auth/password 上游成功返回 ok/relogin_required/revoked_session_scope；
  各约定错误码映射到 400/401/403；上游 5xx 映射 502；
  响应字符串不得出现 old/new password 或 Bearer token；请求体中伪造 user_id/merchant_id 不得被转发。
"""

import importlib

import httpx
from fastapi.testclient import TestClient


def _client(monkeypatch, *, mock_enabled: str = "false", password_url: str | None = None) -> TestClient:
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", mock_enabled)
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")
    if password_url is None:
        monkeypatch.delenv("NEWCAR_AUTH_PASSWORD_URL", raising=False)
    else:
        monkeypatch.setenv("NEWCAR_AUTH_PASSWORD_URL", password_url)

    import app.config as config

    importlib.reload(config)

    from app.main import create_app

    return TestClient(create_app())


def _reload_client(monkeypatch):
    """设置真实模式默认 env 后返回客户端实例。"""
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")
    import app.auth.newcar_client as newcar_client

    return newcar_client.NewCarProjectAuthClient.from_env()


def _newcar_auth_error_class():
    """返回 NewCarAuthError 类，便于断言异常类型。"""
    import app.auth.newcar_client as newcar_client

    return newcar_client.NewCarAuthError


# ---------------------------------------------------------------------------
# NewCarProjectAuthClient.change_external_password()
# ---------------------------------------------------------------------------


def test_change_external_password_real_mode_sends_only_two_fields_with_bearer(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    result = client.change_external_password("pwd-token", "OldPass1", "NewPass2")

    assert result == {"ok": True}
    assert calls == [
        {
            "url": "https://newcar.example.test/api/external-auth/password",
            "json": {"old_password": "OldPass1", "new_password": "NewPass2"},
            "headers": {"Authorization": "Bearer pwd-token"},
            "timeout": 5,
        }
    ]


def test_change_external_password_uses_explicit_password_url(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(url)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("NEWCAR_AUTH_PASSWORD_URL", "https://auth.example.test/custom/password")
    client = _reload_client(monkeypatch)

    result = client.change_external_password("pwd-token", "OldPass1", "NewPass2")

    assert result == {"ok": True}
    assert calls == ["https://auth.example.test/custom/password"]


def test_change_external_password_401_maps_to_sanitized_error(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(401, json={"detail": "expired token"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    raised = None
    try:
        client.change_external_password("very-sensitive-token", "OldPass1", "NewPass2")
    except Exception as exc:
        raised = exc

    assert raised is not None
    assert isinstance(raised, _newcar_auth_error_class())
    # 异常消息不得回显密码或 token
    assert "very-sensitive-token" not in str(raised)
    assert "OldPass1" not in str(raised)
    assert "NewPass2" not in str(raised)


def test_change_external_password_400_maps_to_sanitized_error(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(400, json={"detail": {"code": "OLD_PASSWORD_INVALID", "message": "旧密码错误"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    raised = None
    try:
        client.change_external_password("pwd-token", "OldPass1", "NewPass2")
    except Exception as exc:
        raised = exc

    assert raised is not None
    assert isinstance(raised, _newcar_auth_error_class())
    assert "OldPass1" not in str(raised)
    assert "NewPass2" not in str(raised)


def test_change_external_password_5xx_maps_to_unavailable(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(502, json={"message": "bad gateway"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    raised = None
    try:
        client.change_external_password("pwd-token", "OldPass1", "NewPass2")
    except Exception as exc:
        raised = exc

    assert raised is not None
    assert isinstance(raised, _newcar_auth_error_class())
    assert "pwd-token" not in str(raised)


def test_change_external_password_timeout_maps_to_unavailable(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    raised = None
    try:
        client.change_external_password("pwd-token", "OldPass1", "NewPass2")
    except Exception as exc:
        raised = exc

    assert raised is not None
    assert isinstance(raised, _newcar_auth_error_class())


def test_change_external_password_mock_mode_does_not_call_upstream(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("mock 模式不应调用 NewCarProject password")

    monkeypatch.setattr(httpx, "post", fail_post)
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")
    import app.auth.newcar_client as newcar_client

    client = newcar_client.NewCarProjectAuthClient.from_env()

    result = client.change_external_password("any-token", "OldPass1", "NewPass2")

    assert result == {"ok": True, "mock": True}


def test_change_external_password_without_token_is_safe(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _reload_client(monkeypatch)

    result = client.change_external_password("", "OldPass1", "NewPass2")

    assert result == {"ok": True, "token_present": False}
    assert calls == []


# ---------------------------------------------------------------------------
# 9000 POST /auth/password 门面
# ---------------------------------------------------------------------------


def test_password_facade_success_returns_upstream_payload(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(
            200,
            json={"ok": True, "relogin_required": True, "revoked_session_scope": "all_external"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["relogin_required"] is True
    assert body["revoked_session_scope"] == "all_external"
    # 响应不得回显密码或 token
    serialized = str(body)
    assert "OldPass1" not in serialized
    assert "NewPass2" not in serialized
    assert "pwd-token" not in serialized


def test_password_facade_does_not_forward_user_id_or_merchant_id(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured["json"] = json
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={
            "old_password": "OldPass1",
            "new_password": "NewPass2",
            "user_id": "attacker-user-id",
            "merchant_id": "attacker-merchant-id",
        },
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 200
    # 转发给上游的请求体只允许两个密码字段
    assert captured["json"] == {"old_password": "OldPass1", "new_password": "NewPass2"}


def test_password_facade_missing_token_returns_401(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("缺 token 不应调用上游")

    monkeypatch.setattr(httpx, "post", fail_post)
    client = _client(monkeypatch)

    response = client.post("/auth/password", json={"old_password": "OldPass1", "new_password": "NewPass2"})

    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["code"] in {"TOKEN_MISSING", "TOKEN_EXPIRED", "TOKEN_INVALID", "PERMISSION_DENIED"}


def test_password_facade_old_password_invalid_maps_400(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(400, json={"detail": {"code": "OLD_PASSWORD_INVALID", "message": "旧密码错误"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "OLD_PASSWORD_INVALID"
    serialized = str(body)
    assert "OldPass1" not in serialized
    assert "NewPass2" not in serialized
    assert "pwd-token" not in serialized


def test_password_facade_password_too_short_maps_400(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(400, json={"detail": {"code": "PASSWORD_TOO_SHORT", "message": "密码过短"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PASSWORD_TOO_SHORT"


def test_password_facade_password_unchanged_maps_400(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(400, json={"detail": {"code": "PASSWORD_UNCHANGED", "message": "新旧密码相同"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PASSWORD_UNCHANGED"


def test_password_facade_account_disabled_maps_403(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(403, json={"detail": {"code": "ACCOUNT_DISABLED", "message": "账号已停用"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_DISABLED"


def test_password_facade_account_type_not_allowed_maps_403(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(403, json={"detail": {"code": "ACCOUNT_TYPE_NOT_ALLOWED", "message": "账号类型不允许"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_TYPE_NOT_ALLOWED"


def test_password_facade_token_invalid_maps_401(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(401, json={"detail": {"code": "TOKEN_INVALID", "message": "token 失效"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer pwd-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_INVALID"


def test_password_facade_upstream_5xx_maps_502(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(503, json={"message": "unavailable"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer very-sensitive-token"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "NEWCAR_PASSWORD_UNAVAILABLE"
    serialized = str(body)
    assert "very-sensitive-token" not in serialized
    assert "OldPass1" not in serialized
    assert "NewPass2" not in serialized


def test_password_facade_mock_mode_returns_success(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("mock 模式不应调用上游")

    monkeypatch.setattr(httpx, "post", fail_post)
    client = _client(monkeypatch, mock_enabled="true")

    response = client.post(
        "/auth/password",
        json={"old_password": "OldPass1", "new_password": "NewPass2"},
        headers={"Authorization": "Bearer any-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body.get("mock") is True
    serialized = str(body)
    assert "OldPass1" not in serialized
    assert "NewPass2" not in serialized
