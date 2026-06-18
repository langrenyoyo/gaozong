import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount, DouyinWebhookEvent


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(merchant_id="merchant-1"):
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=["auto_wechat:douyin_ai_cs"],
    )


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: context or _context()
    return TestClient(app)


def _insert_account(open_id="account-open-1", merchant_id="merchant-1", bind_status=1):
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=open_id,
            merchant_id=merchant_id,
            bind_status=bind_status,
            account_name=f"account {open_id}",
            avatar_url="https://example.test/avatar.png",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _insert_agent(agent_id="agent-1", merchant_id="merchant-1", status="active"):
    db = TestSession()
    try:
        row = AiAgent(
            agent_id=agent_id,
            merchant_id=merchant_id,
            name=f"agent {agent_id}",
            avatar_seed="seed",
            prompt="",
            knowledge_base_text="",
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def test_list_accounts_returns_binding_summary():
    _insert_account()
    _insert_agent()
    client = _client()

    bind_response = client.put(
        "/integrations/douyin/accounts/account-open-1/agent-binding",
        json={"agent_id": "agent-1"},
    )
    list_response = client.get("/integrations/douyin/accounts")

    assert bind_response.status_code == 200
    assert list_response.status_code == 200
    item = list_response.json()["data"]["items"][0]
    assert item["account_open_id"] == "account-open-1"
    assert item["authorization_status"] == "authorized"
    assert item["bound_agent_id"] == "agent-1"
    assert item["bound_agent_name"] == "agent agent-1"
    assert item["bound_agent_status"] == "active"
    assert item["binding_status"] == "active"


def test_put_rebinding_keeps_single_active_binding():
    _insert_account()
    _insert_agent("agent-1")
    _insert_agent("agent-2")
    client = _client()

    first = client.put("/integrations/douyin/accounts/account-open-1/agent-binding", json={"agent_id": "agent-1"})
    second = client.put("/integrations/douyin/accounts/account-open-1/agent-binding", json={"agent_id": "agent-2"})

    db = TestSession()
    try:
        active_rows = (
            db.query(DouyinAccountAgentBinding)
            .filter_by(merchant_id="merchant-1", account_open_id="account-open-1", status="active", is_default=True)
            .all()
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(active_rows) == 1
        assert active_rows[0].agent_id == "agent-2"
    finally:
        db.close()


def test_delete_binding_marks_unbound():
    _insert_account()
    _insert_agent()
    client = _client()
    client.put("/integrations/douyin/accounts/account-open-1/agent-binding", json={"agent_id": "agent-1"})

    response = client.delete("/integrations/douyin/accounts/account-open-1/agent-binding")

    assert response.status_code == 200
    assert response.json()["data"]["binding_status"] == "unbound"


def test_history_account_without_merchant_id_is_not_visible_or_bindable():
    _insert_account(merchant_id=None)
    _insert_agent()
    client = _client()

    list_response = client.get("/integrations/douyin/accounts")
    bind_response = client.put(
        "/integrations/douyin/accounts/account-open-1/agent-binding",
        json={"agent_id": "agent-1"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == []
    assert bind_response.status_code == 403
    assert bind_response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"


def test_list_accounts_only_returns_current_merchant_accounts():
    _insert_account(open_id="account-current", merchant_id="merchant-1")
    _insert_account(open_id="account-other", merchant_id="merchant-2")
    _insert_account(open_id="account-empty", merchant_id=None)
    client = _client(_context("merchant-1"))

    response = client.get("/integrations/douyin/accounts")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["account_open_id"] for item in items] == ["account-current"]


def test_webhook_event_fallback_account_cannot_bypass_formal_binding():
    payload = {
        "account_open_id": "account_from_event_only",
        "content": {"text": "hello", "account_open_id": "account_from_event_only"},
    }
    db = TestSession()
    try:
        db.add(
            DouyinWebhookEvent(
                event="im_receive_msg",
                event_key="event-fallback-account",
                from_user_id="customer-1",
                to_user_id="account_from_event_only",
                raw_body=json.dumps(payload, ensure_ascii=False),
                parsed_content_json=json.dumps(payload["content"], ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()
    _insert_agent()
    client = _client()

    list_response = client.get("/integrations/douyin/accounts")
    bind_response = client.put(
        "/integrations/douyin/accounts/account_from_event_only/agent-binding",
        json={"agent_id": "agent-1"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == []
    assert bind_response.status_code == 403
    assert bind_response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_NOT_FOUND"
