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
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import Base, get_db
from app.main import create_app
from app.models import (
    DouyinAuthorizedAccount,
    DouyinImageUpload,
    DouyinLead,
    DouyinMessageResourceDownload,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
)
from app.services.douyin_live_check_service import (
    _openapi_endpoint_config,
    build_signed_openapi_request_body_and_headers,
    reset_live_check_state,
)
from app.services.douyin_openapi_client import call_douyin_openapi


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


class FakeNonJsonUpstreamResponse:
    def __init__(self, status_code: int, text: str = "<html>error</html>"):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("not json")

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
    text: str = "test lead wx_test_0616 phone 13633624849",
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


def _insert_event_for_live_check_account(account_open_id: str) -> None:
    db = TestSession()
    try:
        payload = {
            "event": "im_receive_msg",
            "from_user_id": "customer_for_" + account_open_id,
            "to_user_id": account_open_id,
            "account_open_id": account_open_id,
            "content": json.dumps(
                {
                    "message_type": "text",
                    "text": "hello",
                    "open_id": "customer_for_" + account_open_id,
                    "account_open_id": account_open_id,
                    "server_message_id": "msg_" + account_open_id,
                },
                ensure_ascii=False,
            ),
        }
        db.add(
            DouyinWebhookEvent(
                event="im_receive_msg",
                from_user_id=payload["from_user_id"],
                to_user_id=account_open_id,
                event_key="event_" + account_open_id,
                is_duplicate=0,
                raw_body=json.dumps(payload, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_send_context_event(
    *,
    event: str = "im_receive_msg",
    conversation_short_id: str = "send_conv_001",
    server_message_id: str = "send_msg_001",
    from_user_id: str = "send_customer_001",
    to_user_id: str = "send_account_001",
    message_create_time=None,
) -> None:
    db = TestSession()
    try:
        payload = {
            "event": event,
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "content": json.dumps(
                {
                    "create_time": 1710000000000,
                    "conversation_short_id": conversation_short_id,
                    "server_message_id": server_message_id,
                    "message_type": "text",
                    "text": "hello",
                },
                ensure_ascii=False,
            ),
        }
        db.add(
            DouyinWebhookEvent(
                event=event,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                conversation_short_id=conversation_short_id,
                server_message_id=server_message_id,
                message_type="text",
                message_create_time=message_create_time,
                parse_status="parsed",
                event_key=f"send_context_{conversation_short_id}_{server_message_id}",
                is_duplicate=0,
                raw_body=json.dumps(payload, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_resource_event(
    *,
    event_id_suffix: str = "001",
    conversation_short_id: str = "resource_conv_001",
    server_message_id: str = "resource_msg_001",
    from_user_id: str = "resource_customer_001",
    to_user_id: str = "resource_account_001",
    message_type: str = "image",
    resource_url: str | None = "https://api-normal.amemv.com/im_open/media?resource=image001",
) -> None:
    db = TestSession()
    try:
        content = {
            "create_time": 1710000000000,
            "conversation_short_id": conversation_short_id,
            "server_message_id": server_message_id,
            "message_type": message_type,
            "media_type": message_type,
        }
        if resource_url is not None:
            content["url"] = resource_url
        payload = {
            "event": "im_receive_msg",
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "content": json.dumps(content, ensure_ascii=False),
        }
        db.add(
            DouyinWebhookEvent(
                event="im_receive_msg",
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                conversation_short_id=conversation_short_id,
                server_message_id=server_message_id,
                message_type=message_type,
                parsed_content_json=json.dumps(content, ensure_ascii=False, separators=(",", ":")),
                parse_status="parsed",
                event_key=f"resource_event_{event_id_suffix}",
                is_duplicate=0,
                raw_body=json.dumps(payload, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()


def _image_base64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")


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
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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
         patch("app.services.douyin_openapi_client.time.time", return_value=1700000000), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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
         patch("app.services.douyin_openapi_client.time.time", return_value=1700000000):
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


def test_unified_openapi_client_classifies_non_json_and_keeps_request_body_canonical():
    payload = {"main_account_id": 123, "image_base64": _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)}

    with patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeNonJsonUpstreamResponse(200)
        try:
            call_douyin_openapi("/upload_image_file", payload)
        except Exception as exc:
            detail = exc.detail
        else:
            raise AssertionError("call_douyin_openapi should reject non-json upstream response")

    assert detail["error_code"] == "invalid_upstream_json"
    assert payload["image_base64"] not in json.dumps(detail, ensure_ascii=False)
    assert mock_post.call_args.kwargs["data"] == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert "json" not in mock_post.call_args.kwargs


def test_unified_openapi_client_classifies_http_500_and_masks_authorization():
    with patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(500, {"code": 5000, "msg": "server failed"})
        try:
            call_douyin_openapi("/send_msg", {"main_account_id": 123, "content": "hello"})
        except Exception as exc:
            detail = exc.detail
        else:
            raise AssertionError("call_douyin_openapi should reject HTTP 500")

    assert detail["error_code"] == "upstream_server_error"
    assert detail["upstream_status"] == 500
    assert detail["upstream_code"] == 5000
    assert detail["upstream_msg"] == "server failed"
    assert "..." in detail["authorization_preview"]
    assert "Authorization" not in json.dumps(detail, ensure_ascii=False)
    assert "super-secret" not in json.dumps(detail, ensure_ascii=False)


def test_unified_openapi_client_classifies_business_error():
    with patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(200, {"code": 1001, "msg": "business failed"})
        try:
            call_douyin_openapi("/list_bind_info", {"main_account_id": 123})
        except Exception as exc:
            detail = exc.detail
        else:
            raise AssertionError("call_douyin_openapi should reject business error")

    assert detail["error_code"] == "upstream_business_error"
    assert detail["upstream_status"] == 200
    assert detail["upstream_code"] == 1001
    assert detail["upstream_msg"] == "business failed"


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
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
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


def test_sync_bind_info_posts_signed_body_and_upserts_accounts():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.time.time", return_value=1700000000), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "bind_list": [
                        {
                            "user_id": "2106745398",
                            "open_id": "account_bind_open_1",
                            "account_name": "Bound Account",
                            "avatar_url": "https://avatar.example.com/a.png",
                            "union_id": "union-1",
                            "bind_status": 1,
                            "account_type": 1,
                            "bind_time": "2025-12-15 16:12:46",
                            "unbind_time": None,
                            "created_at": "2025-12-15 14:17:43",
                        }
                    ]
                },
            },
        )
        resp = client.post(
            "/integrations/douyin/live-check/accounts/sync-bind-info",
            json={"page_num": 1, "page_size": 50},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["fetched"] == 1
    assert data["upserted"] == 1
    assert data["active_count"] == 1
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/list_bind_info"
    )
    sent_body = mock_post.call_args.kwargs["data"]
    assert isinstance(sent_body, bytes)
    assert "json" not in mock_post.call_args.kwargs
    assert json.loads(sent_body.decode("utf-8")) == {
        "main_account_id": 123,
        "page_num": 1,
        "page_size": 50,
    }

    db = TestSession()
    try:
        row = db.query(DouyinAuthorizedAccount).filter_by(open_id="account_bind_open_1").one()
        assert row.main_account_id == 123
        assert row.account_name == "Bound Account"
        assert row.bind_status == 1
    finally:
        db.close()


def test_sync_bind_info_updates_existing_account_without_duplicate():
    client = _client()

    def upstream(payload_name: str) -> FakeUpstreamResponse:
        return FakeUpstreamResponse(
            200,
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "bind_list": [
                        {
                            "user_id": "user-1",
                            "open_id": "account_same_open",
                            "account_name": payload_name,
                            "bind_status": 1,
                        }
                    ]
                },
            },
        )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.side_effect = [upstream("First Name"), upstream("Updated Name")]
        first = client.post("/integrations/douyin/live-check/accounts/sync-bind-info", json={})
        second = client.post("/integrations/douyin/live-check/accounts/sync-bind-info", json={})

    assert first.status_code == 200
    assert second.status_code == 200
    db = TestSession()
    try:
        rows = db.query(DouyinAuthorizedAccount).filter_by(open_id="account_same_open").all()
        assert len(rows) == 1
        assert rows[0].account_name == "Updated Name"
    finally:
        db.close()


def test_accounts_prefers_persisted_bind_info_and_keeps_webhook_fallback():
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id="account_persisted",
                account_name="Persisted Account",
                bind_status=1,
                raw_body_json="{}",
            )
        )
        db.commit()
    finally:
        db.close()
    _insert_event_for_live_check_account(account_open_id="account_from_event")

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        data = _client().get("/integrations/douyin/live-check/accounts").json()["data"]

    assert data["items"][0]["account_open_id"] == "account_persisted"
    assert data["items"][0]["source"] == "persisted_bind_info"
    assert {item["account_open_id"] for item in data["items"]} == {
        "account_persisted",
        "account_from_event",
    }


def test_sync_bind_info_persists_inactive_but_accounts_hides_it_by_default():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "bind_list": [
                        {"user_id": "user-3", "open_id": "account_unbound", "account_name": "Unbound", "bind_status": 3}
                    ]
                },
            },
        )
        sync_resp = client.post("/integrations/douyin/live-check/accounts/sync-bind-info", json={})
        accounts_resp = client.get("/integrations/douyin/live-check/accounts")

    assert sync_resp.status_code == 200
    assert accounts_resp.status_code == 200
    db = TestSession()
    try:
        assert db.query(DouyinAuthorizedAccount).filter_by(open_id="account_unbound").count() == 1
    finally:
        db.close()
    assert all(item["account_open_id"] != "account_unbound" for item in accounts_resp.json()["data"]["items"])


def test_sync_bind_info_upstream_business_error_does_not_write_db_or_leak_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(200, {"code": 1001, "msg": "business failed", "data": {}})
        resp = client.post("/integrations/douyin/live-check/accounts/sync-bind-info", json={})

    assert resp.status_code == 502
    assert "business failed" in json.dumps(resp.json(), ensure_ascii=False)
    assert "super-secret" not in json.dumps(resp.json(), ensure_ascii=False)
    db = TestSession()
    try:
        assert db.query(DouyinAuthorizedAccount).count() == 0
    finally:
        db.close()


def test_send_message_rejects_without_manual_confirmation_and_does_not_call_upstream():
    _insert_send_context_event()
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "send_conv_001",
                "customer_open_id": "send_customer_001",
                "content": "hello",
                "manual_confirmed": False,
            },
        )

    assert resp.status_code == 400
    assert "manual_confirmed" in json.dumps(resp.json(), ensure_ascii=False)
    mock_post.assert_not_called()
    db = TestSession()
    try:
        assert db.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db.close()


def test_send_message_rejects_empty_content_and_does_not_call_upstream():
    _insert_send_context_event()
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "send_conv_001",
                "customer_open_id": "send_customer_001",
                "content": "   ",
                "manual_confirmed": True,
            },
        )

    assert resp.status_code == 400
    assert "content" in json.dumps(resp.json(), ensure_ascii=False)
    mock_post.assert_not_called()


def test_send_message_rejects_missing_context_and_does_not_call_upstream():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "missing_conv",
                "content": "hello",
                "manual_confirmed": True,
            },
        )

    assert resp.status_code == 404
    assert "context" in json.dumps(resp.json(), ensure_ascii=False).lower()
    mock_post.assert_not_called()


def test_send_message_success_uses_signed_openapi_body_and_persists_sent_record():
    _insert_send_context_event()
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"msg_id": "upstream_sent_msg_001"}},
        )
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "send_conv_001",
                "customer_open_id": "send_customer_001",
                "content": "人工确认后的回复",
                "scene": "im_reply_msg",
                "manual_confirmed": True,
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "sent"
    assert data["upstream_msg_id"] == "upstream_sent_msg_001"
    assert data["conversation_short_id"] == "send_conv_001"
    assert data["to_user_id"] == "send_customer_001"
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/send_msg"
    )
    assert "json" not in mock_post.call_args.kwargs
    sent_body = json.loads(mock_post.call_args.kwargs["data"].decode("utf-8"))
    assert sent_body == {
        "main_account_id": 123,
        "scene": "im_reply_msg",
        "content": "人工确认后的回复",
        "msg_id": "send_msg_001",
        "conversation_id": "send_conv_001",
        "to_user_id": "send_customer_001",
        "from_user_id": "send_account_001",
    }
    assert mock_post.call_args.kwargs["headers"]["Authorization"]

    db = TestSession()
    try:
        record = db.query(DouyinPrivateMessageSend).one()
        assert record.status == "sent"
        assert record.manual_confirmed == 1
        assert record.auto_send == 0
        assert record.main_account_id == 123
        assert record.upstream_msg_id == "upstream_sent_msg_001"
        assert record.content == "人工确认后的回复"
    finally:
        db.close()


def test_send_message_rejects_context_older_than_24_hours_and_does_not_call_upstream():
    _insert_send_context_event(message_create_time=datetime.now() - timedelta(hours=25))
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "send_conv_001",
                "customer_open_id": "send_customer_001",
                "content": "人工确认后的回复",
                "manual_confirmed": True,
            },
        )

    assert resp.status_code == 400
    assert "24" in json.dumps(resp.json(), ensure_ascii=False)
    mock_post.assert_not_called()
    db = TestSession()
    try:
        assert db.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db.close()


def test_send_message_upstream_business_error_persists_failed_record_without_secret():
    _insert_send_context_event()
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 1001, "msg": "send failed"},
        )
        resp = client.post(
            "/integrations/douyin/live-check/messages/send",
            json={
                "conversation_short_id": "send_conv_001",
                "customer_open_id": "send_customer_001",
                "content": "人工确认后的回复",
                "manual_confirmed": True,
            },
        )

    assert resp.status_code == 502
    body_text = json.dumps(resp.json(), ensure_ascii=False)
    assert "send failed" in body_text
    assert "super-secret" not in body_text
    db = TestSession()
    try:
        record = db.query(DouyinPrivateMessageSend).one()
        assert record.status == "failed"
        assert record.error_code == "1001"
        assert record.error_message == "send failed"
        assert record.manual_confirmed == 1
        assert record.auto_send == 0
    finally:
        db.close()


def test_download_resource_rejects_non_media_types_without_calling_upstream():
    _insert_resource_event(message_type="text", resource_url=None)
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
                "media_type": "text",
            },
        )

    assert resp.status_code == 400
    assert "media_type" in json.dumps(resp.json(), ensure_ascii=False)
    mock_post.assert_not_called()
    db = TestSession()
    try:
        assert db.query(DouyinMessageResourceDownload).count() == 0
    finally:
        db.close()


def test_download_resource_rejects_missing_url_without_calling_upstream():
    _insert_resource_event(resource_url=None)
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
                "media_type": "image",
            },
        )

    assert resp.status_code == 400
    assert "resource_url_not_found" in json.dumps(resp.json(), ensure_ascii=False)
    mock_post.assert_not_called()


def test_download_resource_success_uses_signed_openapi_body_and_persists_record():
    _insert_resource_event(message_type="image")
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "err_no": 0,
                    "err_msg": "",
                    "log_id": "log-001",
                    "data": {
                        "media_type": "image",
                        "url": "https://download.example.com/resource.png",
                    },
                },
            },
        )
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
                "media_type": "image",
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["resource_status"] == "success"
    assert data["download_url"] == "https://download.example.com/resource.png"
    assert data["conversation_short_id"] == "resource_conv_001"
    assert data["server_message_id"] == "resource_msg_001"
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/download_resource"
    )
    assert "json" not in mock_post.call_args.kwargs
    sent_body = json.loads(mock_post.call_args.kwargs["data"].decode("utf-8"))
    assert sent_body == {
        "main_account_id": 123,
        "conversation_id": "resource_conv_001",
        "message_id": "resource_msg_001",
        "open_id": "resource_customer_001",
        "media_type": "image",
        "url": "https://api-normal.amemv.com/im_open/media?resource=image001",
    }
    db = TestSession()
    try:
        record = db.query(DouyinMessageResourceDownload).one()
        assert record.resource_status == "success"
        assert record.media_type == "image"
        assert record.download_url == "https://download.example.com/resource.png"
        assert record.request_body_json
        assert record.response_body_json
    finally:
        db.close()


def test_download_resource_supports_user_local_media_and_data_url_response():
    _insert_resource_event(message_type="user_local_image", resource_url="https://api-normal.amemv.com/local-image")
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"url": "https://download.example.com/local-image.png"}},
        )
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["media_type"] == "image"
    assert resp.json()["data"]["download_url"] == "https://download.example.com/local-image.png"


def test_download_resource_supports_top_level_url_response_for_video():
    _insert_resource_event(message_type="user_local_video", resource_url="https://api-normal.amemv.com/local-video")
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "url": "https://download.example.com/local-video.mp4"},
        )
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["media_type"] == "video"
    assert resp.json()["data"]["download_url"] == "https://download.example.com/local-video.mp4"


def test_download_resource_upstream_business_error_persists_failed_record_without_secret():
    _insert_resource_event(message_type="video")
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(200, {"code": 1001, "msg": "download failed"})
        resp = client.post(
            "/integrations/douyin/live-check/resources/download",
            json={
                "conversation_short_id": "resource_conv_001",
                "server_message_id": "resource_msg_001",
                "media_type": "video",
            },
        )

    assert resp.status_code == 502
    assert "download failed" in json.dumps(resp.json(), ensure_ascii=False)
    assert "super-secret" not in json.dumps(resp.json(), ensure_ascii=False)
    db = TestSession()
    try:
        record = db.query(DouyinMessageResourceDownload).one()
        assert record.resource_status == "failed"
        assert record.error_message == "download failed"
    finally:
        db.close()


def test_upload_image_success_uses_signed_openapi_body_and_persists_sanitized_record():
    client = _client()
    png_base64 = _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.config.DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com"), \
         patch("app.config.DY_OPENAPI_PREFIX", "/ai_chat_agent_test_api/v1/openapi"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "image_id": "@image_id_001==",
                    "width": 111,
                    "height": 222,
                    "md5": "upstream-md5",
                },
            },
        )
        resp = client.post(
            "/integrations/douyin/live-check/resources/upload-image",
            json={
                "file_name": "test.png",
                "image_base64": f"data:image/png;base64,{png_base64}",
                "open_id": "customer_open_001",
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["upload_status"] == "success"
    assert data["image_id"] == "@image_id_001=="
    assert data["width"] == 111
    assert data["height"] == 222
    assert data["md5"] == "upstream-md5"
    assert mock_post.call_args.args[0] == (
        "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi/upload_image_file"
    )
    assert "json" not in mock_post.call_args.kwargs
    sent_body = json.loads(mock_post.call_args.kwargs["data"].decode("utf-8"))
    assert sent_body == {
        "main_account_id": 123,
        "image_base64": png_base64,
        "file_name": "test.png",
        "open_id": "customer_open_001",
    }
    assert mock_post.call_args.kwargs["headers"]["Authorization"]

    db = TestSession()
    try:
        record = db.query(DouyinImageUpload).one()
        assert record.upload_status == "success"
        assert record.main_account_id == 123
        assert record.open_id == "customer_open_001"
        assert record.file_name == "test.png"
        assert record.file_ext == "png"
        assert record.mime_type == "image/png"
        assert record.upstream_image_id == "@image_id_001=="
        assert record.upstream_width == 111
        assert record.upstream_height == 222
        assert record.upstream_md5 == "upstream-md5"
        assert png_base64 not in record.request_body_json
        assert "image_base64_sha256" in record.request_body_json
    finally:
        db.close()


def test_upload_image_accepts_jpeg_bmp_and_webp_headers():
    cases = [
        ("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 12, "image/jpeg"),
        ("photo.jpeg", b"\xff\xd8\xff\xe1" + b"\x00" * 12, "image/jpeg"),
        ("bitmap.bmp", b"BM" + b"\x00" * 14, "image/bmp"),
        ("asset.webp", b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8, "image/webp"),
    ]
    for index, (file_name, raw, mime_type) in enumerate(cases):
        setup_function()
        client = _client()
        with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
             patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
             patch("app.services.douyin_openapi_client.requests.post") as mock_post:
            mock_post.return_value = FakeUpstreamResponse(
                200,
                {"code": 0, "msg": "success", "data": {"image_id": f"img-{index}"}},
            )
            resp = client.post(
                "/integrations/douyin/live-check/resources/upload-image",
                json={"file_name": file_name, "image_base64": _image_base64(raw)},
            )
        assert resp.status_code == 200
        db = TestSession()
        try:
            record = db.query(DouyinImageUpload).one()
            assert record.mime_type == mime_type
        finally:
            db.close()


def test_upload_image_rejects_invalid_inputs_without_calling_upstream():
    invalid_cases = [
        {"file_name": "", "image_base64": _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)},
        {"file_name": "test.png", "image_base64": ""},
        {"file_name": "test.png", "image_base64": "not-valid-base64!"},
        {"file_name": "test.svg", "image_base64": _image_base64(b"<svg></svg>")},
        {"file_name": "fake.png", "image_base64": _image_base64(b"not-a-png")},
        {"file_name": "fake.jpg", "image_base64": _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)},
        {"file_name": "huge.png", "image_base64": _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 + 1))},
    ]
    for payload in invalid_cases:
        setup_function()
        client = _client()
        with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
             patch("app.services.douyin_openapi_client.requests.post") as mock_post:
            resp = client.post(
                "/integrations/douyin/live-check/resources/upload-image",
                json=payload,
            )
        assert resp.status_code == 400
        mock_post.assert_not_called()
        db = TestSession()
        try:
            assert db.query(DouyinImageUpload).count() == 0
        finally:
            db.close()


def test_upload_image_missing_image_id_persists_failed_record():
    client = _client()
    png_base64 = _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(
            200,
            {"code": 0, "msg": "success", "data": {"width": 1, "height": 1}},
        )
        resp = client.post(
            "/integrations/douyin/live-check/resources/upload-image",
            json={"file_name": "test.png", "image_base64": png_base64},
        )

    assert resp.status_code == 502
    assert "image_id" in json.dumps(resp.json(), ensure_ascii=False)
    db = TestSession()
    try:
        record = db.query(DouyinImageUpload).one()
        assert record.upload_status == "failed"
        assert record.error_message
        assert png_base64 not in record.request_body_json
    finally:
        db.close()


def test_upload_image_upstream_error_persists_failed_record_without_secret_or_base64():
    client = _client()
    png_base64 = _image_base64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 123), \
         patch("app.config.DY_GMP_SECRET_KEY", "super-secret"), \
         patch("app.services.douyin_openapi_client.requests.post") as mock_post:
        mock_post.return_value = FakeUpstreamResponse(403, {"code": 1001, "msg": "sign failed"})
        resp = client.post(
            "/integrations/douyin/live-check/resources/upload-image",
            json={"file_name": "test.png", "image_base64": png_base64},
        )

    assert resp.status_code == 502
    body_text = json.dumps(resp.json(), ensure_ascii=False)
    assert "super-secret" not in body_text
    assert png_base64 not in body_text
    db = TestSession()
    try:
        record = db.query(DouyinImageUpload).one()
        assert record.upload_status == "failed"
        assert record.error_message
        assert "super-secret" not in (record.response_body_json or "")
        assert png_base64 not in (record.request_body_json or "")
        assert png_base64 not in (record.response_body_json or "")
    finally:
        db.close()


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
    assert data["source"] == "persisted_bind_info_with_live_check_memory_and_webhook_events_fallback"


def test_authorized_accounts_returns_oauth_callback_account_without_secret():
    client = _client()

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        client.get(
            "/integrations/douyin/live-check/oauth-callback",
            params={
                "code": "code-1234567890",
                "state": "state-abc",
                "open_id": "open-account-001",
                "nick_name": "Authorized Account",
                "avatar": "https://avatar.example.com/a.png",
                "access_token": "token-should-not-leak",
            },
        )
        resp = client.get("/integrations/douyin/live-check/accounts")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["source"] == "persisted_bind_info_with_live_check_memory_and_webhook_events_fallback"
    account = data["items"][0]
    assert account["account_open_id"] == "open-account-001"
    assert account["open_id"] == "open-account-001"
    assert account["account_name"] == "Authorized Account"
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
    payload = _live_receive_payload(text="token-secret-value phone 13633624849")

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
