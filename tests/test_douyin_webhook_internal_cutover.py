"""9000 webhook 可配置转发 9202 internal 的切流测试。"""

import hashlib
import json
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DEFAULT_CONFIGS
from app.database import Base, get_db
from app.models import (
    CheckConfig,
    ConversationAutopilotState,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
)
from packages.clients.leads_client import LeadsClientError


TEST_SECRET = "test-secret-key-for-webhook-internal"

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_module(module):
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    try:
        for key, value in DEFAULT_CONFIGS.items():
            db.add(CheckConfig(config_key=key, config_value=value, description=f"测试配置: {key}"))
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=1,
                open_id="test_account_001",
                merchant_id="test_merchant_001",
                bind_status=1,
            )
        )
        db.commit()
    finally:
        db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)


def setup_function(function):
    db = TestSession()
    try:
        db.query(ConversationAutopilotState).delete()
        db.query(DouyinPrivateMessageSend).delete()
        db.query(DouyinLead).delete()
        db.query(DouyinWebhookEvent).delete()
        db.commit()
    finally:
        db.close()


def _db_session():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def _client() -> TestClient:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _db_session
    return TestClient(app)


def _payload(
    *,
    event: str = "im_receive_msg",
    from_user_id: str | None = None,
    conversation_short_id: str = "conv_test_001",
    server_message_id: str | None = None,
    text: str = "电话 13812345678",
) -> dict:
    suffix = str(int(time.time() * 1000000))
    from_user_id = from_user_id or f"user_{suffix}"
    server_message_id = server_message_id or f"msg_{suffix}"
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": "test_account_001",
        "content": json.dumps(
            {
                "create_time": int(time.time() * 1000),
                "conversation_short_id": conversation_short_id,
                "server_message_id": server_message_id,
                "conversation_type": 1,
                "message_type": "text",
                "source": "",
                "user_infos": [
                    {"open_id": from_user_id, "nick_name": "测试客户", "avatar": "https://example.com/a.png"}
                ],
                "text": text,
            },
            ensure_ascii=False,
        ),
    }


def _body(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _signed_body(payload: dict, secret: str = TEST_SECRET) -> tuple[str, str, str]:
    body_text = _body(payload)
    timestamp = str(int(time.time()))
    signature = hashlib.sha256((secret + body_text + "-" + timestamp).encode("utf-8")).hexdigest()
    return body_text, timestamp, signature


def _post(path: str, payload: dict, *, headers: dict | None = None):
    client = _client()
    merged_headers = {"Content-Type": "application/json"}
    if headers:
        merged_headers.update(headers)
    return client.post(path, data=_body(payload).encode("utf-8"), headers=merged_headers)


def _patch_common_config(*, internal_enabled: bool, fallback_local: bool = True):
    return patch.multiple(
        "app.config",
        APP_ENV="development",
        DOUYIN_WEBHOOK_AUTH_REQUIRED=False,
        LEADS_WEBHOOK_INTERNAL_ENABLED=internal_enabled,
        LEADS_WEBHOOK_FALLBACK_LOCAL=fallback_local,
    )


def test_internal_default_disabled_uses_local_processing_and_does_not_call_client():
    payload = _payload(text="默认关闭本地处理 13812345678")

    with _patch_common_config(internal_enabled=False), patch("app.routers.integrations.LeadsClient") as client_cls:
        resp = _post("/webhook/douyin", payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["lead_action"] == "created"
    assert data["lead_id"] is not None
    client_cls.from_env.assert_not_called()

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 1
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


def test_internal_enabled_success_maps_response_and_schedules_dry_run():
    from app.routers import integrations

    payload = _payload(text="internal 成功转发")
    submitted_event_ids: list[int] = []

    class FakeLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            assert kwargs["source_path"] == "/webhook/douyin"
            assert kwargs["payload"] == payload
            assert kwargs["signature_verified"] is True
            assert kwargs["gateway_app_env"] == "development"
            return {
                "code": 0,
                "msg": "success",
                "event_id": 901,
                "lead_id": 902,
                "is_new_lead": True,
                "is_duplicate": False,
                "lead_action": "created",
            }

    def fake_run(event_id: int):
        submitted_event_ids.append(event_id)

    with _patch_common_config(internal_enabled=True), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FakeLeadsClient()) as from_env, \
        patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp = _post("/webhook/douyin", payload)

    assert resp.status_code == 200
    assert resp.json() == {
        "code": 0,
        "msg": "success",
        "event_id": 901,
        "lead_id": 902,
        "is_new_lead": True,
        "is_duplicate": False,
        "lead_action": "created",
    }
    from_env.assert_called_once()
    assert submitted_event_ids == [901]

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 0
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_internal_enabled_duplicate_does_not_schedule_dry_run_or_fallback():
    from app.routers import integrations

    payload = _payload(text="internal duplicate")
    submitted_event_ids: list[int] = []

    class FakeLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            return {
                "code": 0,
                "msg": "success",
                "event_id": 911,
                "lead_id": 912,
                "is_new_lead": False,
                "is_duplicate": True,
                "lead_action": "duplicate_event",
            }

    def fake_run(event_id: int):
        submitted_event_ids.append(event_id)

    with _patch_common_config(internal_enabled=True), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FakeLeadsClient()), \
        patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run), \
        patch.object(integrations, "process_webhook_event") as local_process:
        resp = _post("/webhook/douyin", payload)

    assert resp.status_code == 200
    assert resp.json()["is_duplicate"] is True
    assert resp.json()["lead_action"] == "duplicate_event"
    assert submitted_event_ids == []
    local_process.assert_not_called()


def test_internal_enabled_client_error_fallbacks_to_local_when_enabled():
    payload = _payload(text="fallback 本地处理 13812345678")

    class FailingLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            raise LeadsClientError("leads_unavailable", "timeout")

    with _patch_common_config(internal_enabled=True, fallback_local=True), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FailingLeadsClient()):
        resp = _post("/webhook/douyin", payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["lead_action"] == "created"
    assert data["lead_id"] is not None

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 1
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


def test_internal_enabled_client_error_returns_502_when_fallback_disabled_and_does_not_write_local():
    payload = _payload(text="fallback 关闭")

    class FailingLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            raise LeadsClientError("leads_unavailable", "timeout")

    with _patch_common_config(internal_enabled=True, fallback_local=False), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FailingLeadsClient()):
        resp = _post("/webhook/douyin", payload)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "LEADS_INTERNAL_WEBHOOK_UNAVAILABLE"

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 0
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_production_wrong_signature_does_not_call_internal_or_fallback():
    payload = _payload(text="验签失败不转发")
    body_text = _body(payload)

    with patch("app.config.APP_ENV", "production"), \
        patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
        patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET), \
        patch("app.config.LEADS_WEBHOOK_INTERNAL_ENABLED", True), \
        patch("app.config.LEADS_WEBHOOK_FALLBACK_LOCAL", True), \
        patch("app.routers.integrations.LeadsClient") as client_cls:
        client = _client()
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-Timestamp": str(int(time.time())),
                "Authorization": "wrong",
            },
        )

    assert resp.status_code == 401
    client_cls.from_env.assert_not_called()

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 0
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_invalid_json_does_not_call_internal_or_fallback():
    with _patch_common_config(internal_enabled=True), patch("app.routers.integrations.LeadsClient") as client_cls:
        client = _client()
        resp = client.post(
            "/webhook/douyin",
            data=b"{bad json",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 400
    client_cls.from_env.assert_not_called()

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 0
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_both_webhook_paths_use_internal_success_consistently():
    payload1 = _payload(from_user_id="path_success_1", server_message_id="msg_path_1")
    payload2 = _payload(from_user_id="path_success_2", server_message_id="msg_path_2")
    calls: list[str] = []

    class FakeLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            calls.append(kwargs["source_path"])
            index = len(calls)
            return {
                "code": 0,
                "msg": "success",
                "event_id": 930 + index,
                "lead_id": 940 + index,
                "is_new_lead": True,
                "is_duplicate": False,
                "lead_action": "created",
            }

    with _patch_common_config(internal_enabled=True), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FakeLeadsClient()):
        legacy = _post("/webhook/douyin", payload1)
        main = _post("/integrations/douyin/webhook", payload2)

    assert legacy.status_code == 200
    assert main.status_code == 200
    assert legacy.json()["lead_action"] == main.json()["lead_action"] == "created"
    assert calls == ["/webhook/douyin", "/integrations/douyin/webhook"]


def test_both_webhook_paths_use_local_fallback_consistently():
    from app.routers import integrations

    payload1 = _payload(
        from_user_id="path_fallback_1",
        conversation_short_id="conv_fallback_1",
        server_message_id="msg_fallback_1",
    )
    payload2 = _payload(
        from_user_id="path_fallback_2",
        conversation_short_id="conv_fallback_2",
        server_message_id="msg_fallback_2",
    )

    class FailingLeadsClient:
        def create_internal_webhook_event(self, **kwargs):
            raise LeadsClientError("leads_unavailable", "timeout")

    with _patch_common_config(internal_enabled=True, fallback_local=True), \
        patch("app.routers.integrations.LeadsClient.from_env", return_value=FailingLeadsClient()), \
        patch.object(integrations, "run_ai_auto_reply_dry_run", lambda event_id: None):
        legacy = _post("/webhook/douyin", payload1)
        main = _post("/integrations/douyin/webhook", payload2)

    assert legacy.status_code == 200
    assert main.status_code == 200
    assert legacy.json()["lead_action"] == main.json()["lead_action"] == "created"

    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 2
        assert db.query(DouyinLead).count() == 2
    finally:
        db.close()
