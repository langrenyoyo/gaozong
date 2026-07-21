"""9202 AI小高线索 internal webhook-events 接口测试。"""

import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 触发 ORM 注册
from app.database import Base, get_db
from app.models import DouyinAuthorizedAccount, DouyinLead, DouyinWebhookEvent


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    """每个测试前重建表，保证 internal webhook 测试隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(*, token: str = "secret-token", source_system: str | None = "auto_wechat_gateway") -> TestClient:
    from apps.leads.dependencies import get_leads_internal_token
    from apps.leads.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_leads_internal_token] = lambda: "secret-token"
    client = TestClient(app)
    client.headers.update({"X-Internal-Token": token})
    if source_system is not None:
        client.headers.update({"X-Gateway-Source-System": source_system})
    return client


def _insert_account(*, open_id: str = "account_001", merchant_id: str | None = "merchant-a") -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=1,
                open_id=open_id,
                merchant_id=merchant_id,
                bind_status=1,
            )
        )
        db.commit()
    finally:
        db.close()


def _payload(
    *,
    event: str = "im_receive_msg",
    from_user_id: str = "customer_001",
    to_user_id: str = "account_001",
    conversation_short_id: str | None = "conv_001",
    server_message_id: str = "msg_001",
    message_type: str = "text",
    text: str = "你好，我想看车，电话 13800138000",
) -> dict:
    content = {
        "create_time": int(time.time() * 1000),
        "server_message_id": server_message_id,
        "message_type": message_type,
        "user_infos": [
            {"open_id": from_user_id, "nick_name": "测试客户", "avatar": "https://example.com/a.png"},
            {"open_id": to_user_id, "nick_name": "企业号", "avatar": "https://example.com/b.png"},
        ],
        "text": text,
    }
    if conversation_short_id is not None:
        content["conversation_short_id"] = conversation_short_id
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "content": json.dumps(content, ensure_ascii=False),
    }


def _internal_body(payload: dict, *, signature_verified: bool = True) -> dict:
    return {
        "source_path": "/webhook/douyin",
        "payload": payload,
        "received_at": "2026-06-22T00:00:00",
        "signature_verified": signature_verified,
        "gateway_request_id": "req-001",
        "gateway_app_env": "production",
    }


def test_internal_webhook_creates_lead_for_bound_text_message_and_keeps_merchant_scope():
    _insert_account()
    client = _client()

    response = client.post("/api/leads/internal/webhook-events", json=_internal_body(_payload()))

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] is not None
    assert data["lead_id"] is not None
    assert data["is_new_lead"] is True
    assert data["is_duplicate"] is False
    assert data["lead_action"] == "created"

    db = TestSession()
    try:
        lead = db.query(DouyinLead).filter(DouyinLead.id == data["lead_id"]).one()
        event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == data["event_id"]).one()
        assert lead.merchant_id == "merchant-a"
        assert lead.account_open_id == "account_001"
        assert lead.conversation_short_id == "conv_001"
        assert lead.customer_contact == "13800138000"
        assert event.lead_id == lead.id
        assert event.is_duplicate is False
    finally:
        db.close()

    listed = client.get("/api/leads", params={"response_format": "page"}, headers={"X-Gateway-Permissions": "auto_wechat:leads", "X-Gateway-Merchant-Id": "merchant-a"})
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1


def test_internal_webhook_duplicate_event_writes_audit_event_without_updating_lead():
    _insert_account()
    client = _client()
    body = _internal_body(_payload(text="首次消息 13800138000"))

    first = client.post("/api/leads/internal/webhook-events", json=body).json()
    second = client.post("/api/leads/internal/webhook-events", json=body).json()

    assert second["lead_id"] == first["lead_id"]
    assert second["is_duplicate"] is True
    assert second["lead_action"] == "duplicate_event"
    db = TestSession()
    try:
        events = db.query(DouyinWebhookEvent).order_by(DouyinWebhookEvent.id).all()
        leads = db.query(DouyinLead).all()
        assert len(events) == 2
        assert events[0].is_duplicate is False
        assert events[1].is_duplicate is True
        assert len(leads) == 1
        assert leads[0].content == "首次消息 13800138000"
    finally:
        db.close()


def test_internal_webhook_unbound_account_only_writes_event_and_not_visible_in_leads():
    client = _client()

    response = client.post("/api/leads/internal/webhook-events", json=_internal_body(_payload(to_user_id="unbound_account")))

    assert response.status_code == 200
    data = response.json()
    assert data["lead_id"] is None
    assert data["is_new_lead"] is False
    assert data["lead_action"] == "unbound_account"
    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 1
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()

    listed = client.get("/api/leads", params={"response_format": "page"}, headers={"X-Gateway-Permissions": "auto_wechat:leads", "X-Gateway-Merchant-Id": "merchant-a"})
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 0


def test_internal_webhook_missing_conversation_only_writes_event():
    _insert_account()
    client = _client()

    response = client.post(
        "/api/leads/internal/webhook-events",
        json=_internal_body(_payload(conversation_short_id=None)),
    )

    assert response.status_code == 200
    assert response.json()["lead_id"] is None
    assert response.json()["lead_action"] == "missing_conversation"
    db = TestSession()
    try:
        assert db.query(DouyinWebhookEvent).count() == 1
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


def test_internal_webhook_auth_and_signature_verified_required():
    _insert_account()
    body = _internal_body(_payload())

    missing_token = _client(token="").post("/api/leads/internal/webhook-events", json=body)
    wrong_token = _client(token="wrong").post("/api/leads/internal/webhook-events", json=body)
    missing_source = _client(source_system=None).post("/api/leads/internal/webhook-events", json=body)
    unverified = _client().post(
        "/api/leads/internal/webhook-events",
        json=_internal_body(_payload(server_message_id="msg_unverified"), signature_verified=False),
    )

    assert missing_token.status_code == 401
    assert wrong_token.status_code == 401
    assert missing_source.status_code == 401
    assert unverified.status_code == 400
    assert unverified.json()["detail"]["code"] == "WEBHOOK_SIGNATURE_NOT_VERIFIED"
