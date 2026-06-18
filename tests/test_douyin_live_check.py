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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import Base, get_db
from app.main import create_app
from app.models import DouyinLead, DouyinWebhookEvent
from app.services.douyin_live_check_service import (
    _openapi_endpoint_config,
    build_signed_openapi_request_body_and_headers,
    reset_live_check_state,
)


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


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
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


def _live_receive_payload(
    *,
    from_user_id: str = "live_forward_user_001",
    server_message_id: str = "live_forward_msg_001",
    conversation_short_id: str = "live_forward_conv_001",
    text: str = "测试线索0616，我的微信 wx_test_0616，手机号 13633624849",
) -> dict:
    return {
        "event": "im_receive_msg",
        "from_user_id": from_user_id,
        "to_user_id": "live_forward_account_001",
        "content": json.dumps(
            {
                "create_time": 1710000000000,
                "conversation_short_id": conversation_short_id,
                "server_message_id": server_message_id,
                "message_type": "text",
                "text": text,
                "user_infos": [
                    {"open_id": from_user_id, "nick_name": "live用户", "avatar": ""},
                ],
            },
            ensure_ascii=False,
        ),
    }


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
         patch("app.config.DY_AUTH_REDIRECT_URL", None), \
         patch("app.config.DY_CALLBACK_URL", None):
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Missing Douyin live-check config" in detail
    assert "DY_AUTH_REDIRECT_URL" in detail
    assert "DY_CALLBACK_URL" in detail


def test_auth_url_configured_returns_final_scan_url_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_BASE_URL_LEGACY", "https://example.test/openapi"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
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
    assert data["auth_redirect_url"] == "https://callback.example.com/oauth-callback"
    assert data["callback_url"] == "https://callback.example.com/webhook-observe"
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["headers"]["Content-Type"] == "application/json"
    assert mock_post.call_args.kwargs["headers"]["X-Auth-Timestamp"]
    assert mock_post.call_args.kwargs["headers"]["Authorization"]
    assert json.loads(mock_post.call_args.kwargs["data"].decode("utf-8"))["main_account_id"] == 123
    assert "super-secret" not in json.dumps(resp.json(), ensure_ascii=False)


def test_auth_url_accepts_upstream_redirect_url_compatibility_field():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_BASE_URL_LEGACY", "https://example.test/openapi"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg"]), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"redirect_url": "https://open.douyin.com/auth/scan?ticket=redirect"}},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 200
    assert resp.json()["data"]["auth_url"] == "https://open.douyin.com/auth/scan?ticket=redirect"


def test_auth_url_signature_matches_douyinapi_with_gmp_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
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
        "auth_redirect_url": "https://callback.example.com/oauth-callback",
        "callback_url": "https://callback.example.com/webhook-observe",
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


def test_signed_openapi_request_uses_body_dash_timestamp_and_hex_authorization():
    payload = {
        "main_account_id": 123,
        "account_name": "demo-account",
        "auth_redirect_url": "https://callback.example.com/oauth-callback",
        "callback_url": "https://callback.example.com/webhook-observe",
        "callback_event": ["im_receive_msg"],
    }

    with patch("app.config.DY_GMP_SECRET_KEY", "gmp-secret"), \
         patch("app.services.douyin_live_check_service.time.time", return_value=1700000000):
        body_text, headers, debug = build_signed_openapi_request_body_and_headers(payload)

    expected_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    expected_signature = hashlib.sha256(
        ("gmp-secret" + expected_body + "-1700000000").encode("utf-8")
    ).hexdigest()

    assert body_text == expected_body
    assert headers == {
        "Content-Type": "application/json",
        "X-Auth-Timestamp": "1700000000",
        "Authorization": expected_signature,
    }
    assert len(headers["Authorization"]) == 64
    assert all(ch in "0123456789abcdef" for ch in headers["Authorization"])
    assert debug["body_sha256"] == hashlib.sha256(expected_body.encode("utf-8")).hexdigest()
    assert debug["canonical_string_sha256"] == hashlib.sha256(
        (expected_body + "-1700000000").encode("utf-8")
    ).hexdigest()
    assert debug["secret_len"] == len("gmp-secret")
    assert debug["secret_has_space"] is False
    assert "gmp-secret" not in json.dumps(debug, ensure_ascii=False)
    assert expected_signature not in json.dumps(debug, ensure_ascii=False)


def test_auth_url_uses_openapi_base_url_and_prefix_when_legacy_base_url_absent():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", ""), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com/"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg"]), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"auth_url": "https://open.douyin.com/auth/scan?ticket=abc"}},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 200
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi/get_aweme_auth_url"
    )


def test_auth_url_prefers_openapi_base_and_prefix_when_legacy_base_url_also_exists():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi"), \
         patch("app.config.DY_BASE_URL_LEGACY", "https://gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
         patch("app.config.DY_CALLBACK_EVENTS", ["im_receive_msg"]), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_live_check_service.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"auth_url": "https://open.douyin.com/auth/scan?ticket=abc"}},
        )
        resp = client.get("/integrations/douyin/live-check/auth-url")

    assert resp.status_code == 200
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/get_aweme_auth_url"
    )


def test_openapi_endpoint_config_falls_back_to_legacy_base_url_when_new_config_missing():
    with patch("app.config.DY_BASE_URL", "https://legacy.example.com/openapi"), \
         patch("app.config.DY_BASE_URL_LEGACY", "https://legacy.example.com/openapi"), \
         patch("app.config.DY_OPENAPI_BASE_URL", ""), \
         patch("app.config.DY_OPENAPI_PREFIX", ""):
        endpoint = _openapi_endpoint_config()

    assert endpoint == {
        "base_url": "",
        "prefix": "",
        "upstream_base_url": "https://legacy.example.com/openapi",
        "legacy_base_url_used": True,
        "legacy_base_url_present": True,
        "source": "legacy_dy_base_url",
    }


def test_auth_url_upstream_403_returns_safe_error_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_BASE_URL", "https://example.test/openapi"), \
         patch("app.config.DY_BASE_URL_LEGACY", "https://example.test/openapi"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_ACCOUNT_NAME", "demo-account"), \
         patch("app.config.DY_AUTH_REDIRECT_URL", "https://callback.example.com/oauth-callback"), \
         patch("app.config.DY_CALLBACK_URL", "https://callback.example.com/webhook-observe"), \
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
    assert detail["body_sha256"]
    assert detail["canonical_string_sha256"]
    assert detail["secret_len"] == len("super-secret")
    assert detail["secret_has_space"] is False
    assert detail["upstream_url"] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/get_aweme_auth_url"
    )
    assert detail["upstream_base_url"] == "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi"
    assert detail["openapi_base_url"] == "https://gmp.bytedanceapi.com"
    assert detail["openapi_prefix"] == "/ai_chat_agent_test_api/v1/openapi"
    assert detail["legacy_base_url_used"] is False
    assert detail["legacy_base_url_present"] is True
    assert detail["openapi_config_source"] == "openapi_base_url_prefix"
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


def test_authorized_accounts_empty_before_oauth_callback():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        resp = client.get("/integrations/douyin/live-check/accounts")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0
    assert data["source"] == "live_check_memory_with_webhook_events_fallback"


def test_authorized_accounts_returns_oauth_callback_account_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        client.get(
            "/integrations/douyin/live-check/oauth-callback",
            params={
                "code": "code-1234567890",
                "state": "state-abc",
                "open_id": "open-account-001",
                "nick_name": "授权抖音号",
                "avatar": "https://avatar.example.com/a.png",
                "access_token": "token-should-not-leak",
            },
        )
        resp = client.get("/integrations/douyin/live-check/accounts")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["source"] == "live_check_memory_with_webhook_events_fallback"
    account = data["items"][0]
    assert account["account_open_id"] == "open-account-001"
    assert account["open_id"] == "open-account-001"
    assert account["account_name"] == "授权抖音号"
    assert account["avatar_url"] == "https://avatar.example.com/a.png"
    assert account["status"] == "active"
    assert account["is_active"] is True
    assert account["unread_count"] == 0
    assert "token-should-not-leak" not in json.dumps(resp.json(), ensure_ascii=False)


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
    assert data["from_user_id"] == "from-1"
    assert data["to_user_id"] is None
    assert data["body_open_id"] is None
    assert data["body_account_open_id"] == "account-1"
    assert data["content_open_id"] is None
    assert data["content_account_open_id"] is None
    assert data["body_has_conversation_short_id"] is True
    assert data["body_has_server_message_id"] is True
    assert "body-token-should-not-leak" not in json.dumps(resp.json(), ensure_ascii=False)


def test_webhook_observe_parses_stringified_json_content():
    client = _client()
    payload = {
        "event": "im_receive_msg",
        "from_user_id": "from-open-1",
        "to_user_id": "to-open-1",
        "open_id": "open-1",
        "account_open_id": "account-1",
        "content": json.dumps(
            {
                "open_id": "content-open-1",
                "account_open_id": "content-account-1",
                "conversation_short_id": "conv-1",
                "server_message_id": "msg-1",
                "message_type": "text",
                "access_token": "content-token-should-not-leak",
            },
            ensure_ascii=False,
        ),
    }

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        resp = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)
        status_resp = client.get("/integrations/douyin/live-check/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["body_has_event"] is True
    assert data["body_has_content"] is True
    assert data["body_has_open_id"] is True
    assert data["body_has_account_open_id"] is True
    assert data["from_user_id"] == "from-open-1"
    assert data["to_user_id"] == "to-open-1"
    assert data["body_open_id"] == "open-1"
    assert data["body_account_open_id"] == "account-1"
    assert data["content_open_id"] == "content-open-1"
    assert data["content_account_open_id"] == "content-account-1"
    assert data["body_has_conversation_short_id"] is True
    assert data["body_has_server_message_id"] is True
    assert data["content_parse_success"] is True
    assert data["content_parse_error"] is None
    assert data["content_has_conversation_short_id"] is True
    assert data["content_has_server_message_id"] is True
    assert data["content_has_message_type"] is True
    assert data["content_message_type"] == "text"
    assert data["content_keys"] == [
        "account_open_id",
        "conversation_short_id",
        "message_type",
        "open_id",
        "server_message_id",
    ]
    assert status_resp.json()["data"]["last_webhook_observe"]["content_parse_success"] is True
    assert status_resp.json()["data"]["last_webhook_observe"]["content_open_id"] == "content-open-1"
    assert "content-token-should-not-leak" not in json.dumps(resp.json(), ensure_ascii=False)


def test_webhook_observe_handles_non_json_content_without_leaking_text():
    client = _client()
    payload = {
        "event": "im_receive_msg",
        "content": "not-json phone 13812345678 token-secret-value",
    }

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        resp = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["body_has_event"] is True
    assert data["body_has_content"] is True
    assert data["body_has_conversation_short_id"] is False
    assert data["body_has_server_message_id"] is False
    assert data["content_parse_success"] is False
    assert data["content_parse_error"] == "content is not valid JSON"
    assert data["content_keys"] == []
    assert "13812345678" not in json.dumps(resp.json(), ensure_ascii=False)
    assert "token-secret-value" not in json.dumps(resp.json(), ensure_ascii=False)


def test_webhook_observe_forward_disabled_does_not_write_formal_event():
    client = _client()
    payload = _live_receive_payload()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_LIVE_CHECK_FORWARD_TO_FORMAL", False):
        resp = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["forward_to_formal_enabled"] is False
    assert data["forward_to_formal_success"] is None

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 0
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_webhook_observe_forward_enabled_reuses_formal_pipeline_and_creates_lead():
    client = _client()
    payload = _live_receive_payload(from_user_id="live_forward_create_001")

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_LIVE_CHECK_FORWARD_TO_FORMAL", True), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.config.APP_ENV", "production"):
        resp = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["forward_to_formal_enabled"] is True
    assert data["forward_to_formal_success"] is True
    assert data["forward_to_formal_event_id"] is not None
    assert data["forward_to_formal_lead_id"] is not None
    assert data["forward_to_formal_lead_action"] == "created"
    assert data["forward_to_formal_error"] is None

    db = TestSession()
    try:
        event = db.query(DouyinWebhookEvent).filter_by(id=data["forward_to_formal_event_id"]).first()
        lead = db.query(DouyinLead).filter_by(id=data["forward_to_formal_lead_id"]).first()
        assert event is not None
        assert event.event == "im_receive_msg"
        assert lead is not None
        assert lead.source_id == "live_forward_create_001"
        assert lead.customer_contact == "13633624849"
    finally:
        db.close()


def test_webhook_observe_forward_enabled_duplicate_uses_formal_idempotency():
    client = _client()
    payload = _live_receive_payload(from_user_id="live_forward_dup_001")

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_LIVE_CHECK_FORWARD_TO_FORMAL", True):
        first = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)
        second = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["forward_to_formal_lead_action"] == "created"
    assert second_data["forward_to_formal_success"] is True
    assert second_data["forward_to_formal_lead_action"] == "duplicate_event"
    assert second_data["forward_to_formal_lead_id"] == first_data["forward_to_formal_lead_id"]
    assert second_data["forward_to_formal_event_id"] != first_data["forward_to_formal_event_id"]

    db = TestSession()
    try:
        assert db.query(DouyinLead).filter_by(source_id="live_forward_dup_001").count() == 1
        assert db.query(DouyinWebhookEvent).filter_by(from_user_id="live_forward_dup_001").count() == 2
    finally:
        db.close()


def test_webhook_observe_forward_failure_keeps_200_and_masks_error():
    client = _client()
    payload = _live_receive_payload(text="token-secret-value 手机号 13633624849")

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_LIVE_CHECK_FORWARD_TO_FORMAL", True), \
         patch(
             "app.routers.douyin_live_check._handle_douyin_webhook",
             side_effect=RuntimeError("boom token-secret-value"),
         ):
        resp = client.post("/integrations/douyin/live-check/webhook-observe", json=payload)

    assert resp.status_code == 200
    body = json.dumps(resp.json(), ensure_ascii=False)
    data = resp.json()["data"]
    assert data["forward_to_formal_enabled"] is True
    assert data["forward_to_formal_success"] is False
    assert data["forward_to_formal_event_id"] is None
    assert data["forward_to_formal_lead_id"] is None
    assert data["forward_to_formal_lead_action"] is None
    assert data["forward_to_formal_error"] == "RuntimeError"
    assert "token-secret-value" not in body
    assert "13633624849" not in body


def test_config_loads_env_file_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_LIVE_CHECK_FORWARD_TO_FORMAL=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
                "DY_AUTH_REDIRECT_URL=https://callback.misanduo.com/oauth-callback",
                "DY_CALLBACK_URL=https://callback.misanduo.com/webhook-observe",
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "DY_LIVE_CHECK_ENABLED",
        "DY_LIVE_CHECK_FORWARD_TO_FORMAL",
        "DY_MAIN_ACCOUNT_ID",
        "PUBLIC_BASE_URL",
        "DY_AUTH_REDIRECT_URL",
        "DY_CALLBACK_URL",
    ]:
        monkeypatch.delenv(key, raising=False)

    config._load_env_file(env_file)

    assert os.environ["DY_LIVE_CHECK_ENABLED"] == "true"
    assert os.environ["DY_LIVE_CHECK_FORWARD_TO_FORMAL"] == "true"
    assert os.environ["DY_MAIN_ACCOUNT_ID"] == "2124269908"
    assert os.environ["PUBLIC_BASE_URL"] == "https://callback.misanduo.com"
    assert os.environ["DY_AUTH_REDIRECT_URL"] == "https://callback.misanduo.com/oauth-callback"
    assert os.environ["DY_CALLBACK_URL"] == "https://callback.misanduo.com/webhook-observe"


def test_config_env_file_does_not_override_explicit_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_LIVE_CHECK_FORWARD_TO_FORMAL=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
                "DY_AUTH_REDIRECT_URL=https://callback.misanduo.com/oauth-callback",
                "DY_CALLBACK_URL=https://callback.misanduo.com/webhook-observe",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DY_LIVE_CHECK_ENABLED", "false")
    monkeypatch.setenv("DY_LIVE_CHECK_FORWARD_TO_FORMAL", "false")
    monkeypatch.setenv("DY_MAIN_ACCOUNT_ID", "999")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("DY_AUTH_REDIRECT_URL", "https://env.example.com/oauth")
    monkeypatch.setenv("DY_CALLBACK_URL", "https://env.example.com/callback")

    config._load_env_file(env_file)

    assert os.environ["DY_LIVE_CHECK_ENABLED"] == "false"
    assert os.environ["DY_LIVE_CHECK_FORWARD_TO_FORMAL"] == "false"
    assert os.environ["DY_MAIN_ACCOUNT_ID"] == "999"
    assert os.environ["PUBLIC_BASE_URL"] == "https://env.example.com"
    assert os.environ["DY_AUTH_REDIRECT_URL"] == "https://env.example.com/oauth"
    assert os.environ["DY_CALLBACK_URL"] == "https://env.example.com/callback"


def test_config_constants_reflect_loaded_env_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DY_LIVE_CHECK_ENABLED=true",
                "DY_LIVE_CHECK_FORWARD_TO_FORMAL=true",
                "DY_MAIN_ACCOUNT_ID=2124269908",
                "PUBLIC_BASE_URL=https://callback.misanduo.com",
                "DY_AUTH_REDIRECT_URL=https://callback.misanduo.com/oauth-callback",
                "DY_CALLBACK_URL=https://callback.misanduo.com/webhook-observe",
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "DY_LIVE_CHECK_ENABLED",
        "DY_LIVE_CHECK_FORWARD_TO_FORMAL",
        "DY_MAIN_ACCOUNT_ID",
        "PUBLIC_BASE_URL",
        "DY_AUTH_REDIRECT_URL",
        "DY_CALLBACK_URL",
    ]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(config, "ENV_FILE", env_file)
    config._load_env_file(config.ENV_FILE)
    reloaded = importlib.reload(config)

    assert reloaded.DY_LIVE_CHECK_ENABLED is True
    assert reloaded.DY_LIVE_CHECK_FORWARD_TO_FORMAL is True
    assert reloaded.DY_MAIN_ACCOUNT_ID == 2124269908
    assert reloaded.PUBLIC_BASE_URL == "https://callback.misanduo.com"
    assert reloaded.DY_AUTH_REDIRECT_URL == "https://callback.misanduo.com/oauth-callback"
    assert reloaded.DY_CALLBACK_URL == "https://callback.misanduo.com/webhook-observe"


def test_config_openapi_base_and_prefix_fall_back_when_environment_values_are_blank(monkeypatch):
    monkeypatch.setenv("DY_OPENAPI_BASE_URL", "")
    monkeypatch.setenv("DY_OPENAPI_PREFIX", "")
    monkeypatch.delenv("DY_BASE_URL", raising=False)

    reloaded = importlib.reload(config)

    assert reloaded.DY_OPENAPI_BASE_URL == "https://gmp.bytedanceapi.com"
    assert reloaded.DY_OPENAPI_PREFIX == "/ai_chat_agent_api/v1/openapi"
    assert reloaded.DY_BASE_URL == "https://gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi"
