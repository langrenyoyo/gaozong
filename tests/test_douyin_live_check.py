"""Douyin live-check preparation endpoints.

These endpoints are for on-site observation only. They must not call Douyin,
write tokens, or change the production webhook path.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib
import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.main import create_app
from app.services.douyin_live_check_service import reset_live_check_state


class FakeUpstreamResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error", response=self)


def _client():
    reset_live_check_state()
    return TestClient(create_app())


def test_live_check_disabled_returns_clear_error():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", False):
        resp = client.get("/integrations/douyin/live-check/status")

    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_auth_url_missing_config_returns_clear_error():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", ""), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 0), \
         patch("app.config.PUBLIC_BASE_URL", ""):
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 400
    assert "missing" in resp.json()["detail"].lower()


def test_auth_url_configured_returns_final_scan_url_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.PUBLIC_BASE_URL", "https://callback.example.com"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg", "im_send_msg"]), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"auth_url": "https://open.douyin.com/auth/scan?ticket=abc"}},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["configured"] is True
    assert data["auth_url"] == "https://open.douyin.com/auth/scan?ticket=abc"
    assert "/get_aweme_auth_url" not in data["auth_url"]
    assert data["auth_redirect_url"] == "https://callback.example.com/integrations/douyin/live-check/oauth-callback"
    assert data["callback_url"] == "https://callback.example.com/integrations/douyin/live-check/webhook-observe"
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["headers"]["Content-Type"] == "application/json"
    assert mock_post.call_args.kwargs["headers"]["X-Auth-Timestamp"]
    assert mock_post.call_args.kwargs["headers"]["Authorization"]
    assert json.loads(mock_post.call_args.kwargs["data"].decode("utf-8"))["main_account_id"] == 123
    assert "super-secret" not in json.dumps(resp.json(), ensure_ascii=False)


def test_auth_url_signature_matches_douyinapi_with_gmp_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.PUBLIC_BASE_URL", "https://callback.example.com"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg", "im_send_msg"]), \
         patch("app.config.DY_SECRET_KEY", "webhook-secret"), \
         patch("app.config.DY_GMP_SECRET_KEY", "gmp-secret"), \
         patch("app.services.douyin_live_check_service.time.time", return_value=1700000000), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"auth_url": "https://open.douyin.com/auth/scan?ticket=abc"}},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 200
    expected_payload = {
        "main_account_id": 123,
        "account_name": "demo-account",
        "auth_redirect_url": "https://callback.example.com/integrations/douyin/live-check/oauth-callback",
        "callback_url": "https://callback.example.com/integrations/douyin/live-check/webhook-observe",
        "callback_event": ["im_receive_msg", "im_send_msg"],
    }
    expected_body = json.dumps(expected_payload, ensure_ascii=False, separators=(",", ":"))
    expected_signature = hashlib.sha256(
        ("gmp-secret" + expected_body + "-1700000000").encode("utf-8")
    ).hexdigest()
    wrong_webhook_signature = hashlib.sha256(
        ("webhook-secret" + expected_body + "-1700000000").encode("utf-8")
    ).hexdigest()

    assert mock_post.call_args.kwargs["data"] == expected_body.encode("utf-8")
    assert mock_post.call_args.kwargs["headers"] == {
        "Content-Type": "application/json",
        "X-Auth-Timestamp": "1700000000",
        "Authorization": expected_signature,
    }
    assert mock_post.call_args.kwargs["headers"]["Authorization"] != wrong_webhook_signature


def test_auth_url_upstream_403_returns_safe_error_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.PUBLIC_BASE_URL", "https://callback.example.com"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg"]), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            403,
            {"code": 403, "msg": "Invalid request headers", "access_token": "token-should-not-leak"},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["upstream_status"] == 403
    assert detail["upstream_code"] == 403
    assert detail["upstream_msg"] == "Invalid request headers"
    assert detail["signing_secret_config"] == "DY_GMP_SECRET_KEY"
    assert detail["signing_secret_configured"] is True
    assert detail["body_keys"] == [
        "account_name",
        "auth_redirect_url",
        "callback_event",
        "callback_url",
        "main_account_id",
    ]
    assert detail["timestamp_format"] == "unix_seconds"
    assert "..." in detail["authorization_preview"]
    assert "授权链接获取失败" in detail["safe_message"]
    assert "super-secret" not in json.dumps(resp.json(), ensure_ascii=False)
    assert "token-should-not-leak" not in json.dumps(resp.json(), ensure_ascii=False)


def test_oauth_callback_records_summary_without_sensitive_values():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        resp = client.get(
            "/integrations/douyin/live-check/oauth-callback",
            params={
                "code": "code-1234567890",
                "state": "state-abc",
                "open_id": "open-user-001",
                "access_token": "token-should-not-leak",
            },
        )
        status_resp = client.get("/integrations/douyin/live-check/status")

    assert resp.status_code == 200
    callback = status_resp.json()["data"]["last_oauth_callback"]
    assert callback["has_code"] is True
    assert callback["code_preview"] == "code...7890"
    assert callback["state"] == "state-abc"
    assert callback["open_id"] == "open-user-001"
    assert "token-should-not-leak" not in json.dumps(status_resp.json(), ensure_ascii=False)


def test_webhook_observe_records_headers_and_body_keys_without_token_leak():
    client = _client()
    payload = {
        "event": "im_receive_msg",
        "from_user_id": "from-1",
        "account_open_id": "account-1",
        "content": {
            "text": "phone 13812345678",
            "conversation_short_id": "conv-1",
            "server_message_id": "msg-1",
            "access_token": "body-token-should-not-leak",
        },
    }

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        resp = client.post(
            "/integrations/douyin/live-check/webhook-observe",
            json=payload,
            headers={
                "Authorization": "signature-or-token",
                "X-Auth-Timestamp": "123456",
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["has_authorization"] is True
    assert data["has_x_auth_timestamp"] is True
    assert data["body_has_event"] is True
    assert data["body_has_content"] is True
    assert data["body_has_account_open_id"] is True
    assert data["body_has_conversation_short_id"] is True
    assert data["body_has_server_message_id"] is True
    assert "body-token-should-not-leak" not in json.dumps(resp.json(), ensure_ascii=False)


def test_config_loads_env_file_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
            ]
        ),
        encoding="utf-8",
    )
    for key in ["DY_LIVE_CHECK_ENABLED", "DY_MAIN_ACCOUNT_ID", "PUBLIC_BASE_URL"]:
        monkeypatch.delenv(key, raising=False)

    config._load_env_file(env_file)

    assert os.environ["DY_LIVE_CHECK_ENABLED"] == "true"
    assert os.environ["DY_MAIN_ACCOUNT_ID"] == "2124269908"
    assert os.environ["PUBLIC_BASE_URL"] == "https://callback.misanduo.com"


def test_config_env_file_does_not_override_explicit_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DY_LIVE_CHECK_ENABLED", "false")
    monkeypatch.setenv("DY_MAIN_ACCOUNT_ID", "999")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://env.example.com")

    config._load_env_file(env_file)

    assert os.environ["DY_LIVE_CHECK_ENABLED"] == "false"
    assert os.environ["DY_MAIN_ACCOUNT_ID"] == "999"
    assert os.environ["PUBLIC_BASE_URL"] == "https://env.example.com"


def test_config_constants_reflect_loaded_env_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
            ]
        ),
        encoding="utf-8",
    )
    for key in ["DY_LIVE_CHECK_ENABLED", "DY_MAIN_ACCOUNT_ID", "PUBLIC_BASE_URL"]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(config, "ENV_FILE", env_file)
    config._load_env_file(config.ENV_FILE)
    reloaded = importlib.reload(config)

    assert reloaded.DY_LIVE_CHECK_ENABLED is True
    assert reloaded.DY_MAIN_ACCOUNT_ID == 2124269908
    assert reloaded.PUBLIC_BASE_URL == "https://callback.misanduo.com"
