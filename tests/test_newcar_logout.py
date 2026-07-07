import importlib

import httpx
from fastapi.testclient import TestClient


def _client(monkeypatch, *, mock_enabled: str = "false", logout_url: str | None = None) -> TestClient:
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", mock_enabled)
    monkeypatch.setenv("NEWCAR_AUTH_BASE_URL", "https://newcar.example.test")
    if logout_url is None:
        monkeypatch.delenv("NEWCAR_AUTH_LOGOUT_URL", raising=False)
    else:
        monkeypatch.setenv("NEWCAR_AUTH_LOGOUT_URL", logout_url)

    import app.config as config

    importlib.reload(config)

    from app.main import create_app

    return TestClient(create_app())


def test_newcar_logout_calls_upstream_with_bearer_token(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post("/auth/logout", headers={"Authorization": "Bearer logout-token"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == [
        {
            "url": "https://newcar.example.test/api/external-auth/logout",
            "json": {},
            "headers": {"Authorization": "Bearer logout-token"},
            "timeout": 5,
        }
    ]


def test_newcar_logout_uses_explicit_logout_url(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(url)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch, logout_url="https://auth.example.test/custom/logout")

    response = client.post("/auth/logout", headers={"Authorization": "Bearer logout-token"})

    assert response.status_code == 200
    assert calls == ["https://auth.example.test/custom/logout"]


def test_newcar_logout_treats_401_as_already_logged_out(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(401, json={"detail": "expired"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post("/auth/logout", headers={"Authorization": "Bearer old-token"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "upstream_status": 401}


def test_newcar_logout_mock_mode_does_not_call_upstream(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("mock 模式不应调用 NewCarProject logout")

    monkeypatch.setattr(httpx, "post", fail_post)
    client = _client(monkeypatch, mock_enabled="true")

    response = client.post("/auth/logout", headers={"Authorization": "Bearer any-token"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "mock": True}


def test_newcar_logout_without_token_is_safe(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "token_present": False}
    assert calls == []


def test_newcar_logout_upstream_5xx_returns_sanitized_error(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(502, json={"message": "bad gateway"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _client(monkeypatch)

    response = client.post("/auth/logout", headers={"Authorization": "Bearer very-sensitive-token"})

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "NEWCAR_LOGOUT_UNAVAILABLE"
    assert "very-sensitive-token" not in str(body)
