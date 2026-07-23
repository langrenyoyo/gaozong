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


def _bind_account(open_id="account-open-1", agent_id="agent-1", merchant_id="merchant-1"):
    db = TestSession()
    try:
        row = DouyinAccountAgentBinding(
            merchant_id=merchant_id,
            account_open_id=open_id,
            agent_id=agent_id,
            is_default=True,
            status="active",
            created_by="user-1",
            updated_by="user-1",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _insert_webhook_event(
    *,
    event: str,
    account_open_id: str,
    customer_open_id: str,
    event_key: str,
    is_duplicate: bool = False,
    merchant_id: str | None = None,
):
    db = TestSession()
    try:
        content = {
            "text": f"{event} from {customer_open_id}",
            "account_open_id": account_open_id,
            "open_id": customer_open_id,
        }
        row = DouyinWebhookEvent(
            event=event,
            event_key=event_key,
            from_user_id=customer_open_id if event == "im_receive_msg" else account_open_id,
            to_user_id=account_open_id if event == "im_receive_msg" else customer_open_id,
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=is_duplicate,
            merchant_id=merchant_id,
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


def test_list_accounts_unread_count_is_zero_before_read_state_when_no_webhook_messages():
    _insert_account()
    client = _client()

    response = client.get("/integrations/douyin/accounts")

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["unread_count"] == 0


def test_list_accounts_unread_count_before_read_state_counts_inbound_messages_only():
    _insert_account()
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="inbound-1",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-2",
        event_key="inbound-2",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_send_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="outbound-1",
        merchant_id="merchant-1",
    )
    client = _client()

    response = client.get("/integrations/douyin/accounts")

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["unread_count"] == 2


def test_list_accounts_unread_count_before_read_state_isolated_by_account_open_id():
    _insert_account(open_id="account-open-1")
    _insert_account(open_id="account-open-2")
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="account-1-inbound-1",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-2",
        customer_open_id="customer-2",
        event_key="account-2-inbound-1",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-2",
        customer_open_id="customer-3",
        event_key="account-2-inbound-2",
        merchant_id="merchant-1",
    )
    client = _client()

    response = client.get("/integrations/douyin/accounts")

    assert response.status_code == 200
    items = {
        item["account_open_id"]: item["unread_count"]
        for item in response.json()["data"]["items"]
    }
    assert items == {"account-open-2": 2, "account-open-1": 1}


def test_list_accounts_unread_count_before_read_state_uses_current_merchant_authorized_accounts_only():
    _insert_account(open_id="account-current", merchant_id="merchant-1")
    _insert_account(open_id="account-other", merchant_id="merchant-2")
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-current",
        customer_open_id="customer-1",
        event_key="current-inbound-1",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-other",
        customer_open_id="customer-2",
        event_key="other-inbound-1",
        merchant_id="merchant-2",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="event-only-account",
        customer_open_id="customer-3",
        event_key="event-only-inbound-1",
        merchant_id="merchant-1",
    )
    client = _client(_context("merchant-1"))

    response = client.get("/integrations/douyin/accounts")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["account_open_id"] == "account-current"
    assert items[0]["unread_count"] == 1


def test_list_accounts_unread_count_after_read_state_sums_only_new_inbound_messages():
    _insert_account(open_id="account-open-1")
    event = _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="read-state-inbound-1",
        merchant_id="merchant-1",
    )
    client = _client()
    mark_read = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "account-open-1:customer-1",
            "last_seen_event_id": event.id,
            "customer_open_id": "customer-1",
        },
    )
    _insert_webhook_event(
        event="im_send_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="read-state-outbound-after-read",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        event_key="read-state-inbound-after-read",
        merchant_id="merchant-1",
    )

    response = client.get("/integrations/douyin/accounts")

    assert mark_read.status_code == 200
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["unread_count"] == 1


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


def test_delete_then_rebind_same_agent_revives_existing_binding():
    _insert_account()
    _insert_agent()
    client = _client()

    first = client.put("/integrations/douyin/accounts/account-open-1/agent-binding", json={"agent_id": "agent-1"})
    delete_response = client.delete("/integrations/douyin/accounts/account-open-1/agent-binding")
    rebound = client.put("/integrations/douyin/accounts/account-open-1/agent-binding", json={"agent_id": "agent-1"})

    db = TestSession()
    try:
        rows = (
            db.query(DouyinAccountAgentBinding)
            .filter_by(merchant_id="merchant-1", account_open_id="account-open-1", agent_id="agent-1")
            .all()
        )
        assert first.status_code == 200
        assert delete_response.status_code == 200
        assert rebound.status_code == 200
        assert len(rows) == 1
        assert rows[0].status == "active"
        assert rows[0].is_default is True
        assert rows[0].unbound_at is None
        assert rows[0].deleted_at is None
    finally:
        db.close()


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


def test_cancel_authorization_marks_account_unauthorized_and_binding_invalid():
    _insert_account()
    _insert_agent()
    _bind_account()
    client = _client()

    response = client.post("/integrations/douyin/accounts/account-open-1/cancel-authorization")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_open_id"] == "account-open-1"
    assert data["authorization_status"] == "unauthorized"
    assert data["binding_status"] == "invalid"
    assert data["upstream_cancel_supported"] is False
    db = TestSession()
    try:
        account = db.query(DouyinAuthorizedAccount).filter_by(open_id="account-open-1").one()
        binding = db.query(DouyinAccountAgentBinding).filter_by(account_open_id="account-open-1").one()
        assert account.bind_status == 0
        assert account.unbind_time is not None
        assert binding.status == "invalid"
        assert binding.invalid_reason == "account_unauthorized"
    finally:
        db.close()


def test_cancel_authorization_is_idempotent():
    _insert_account(bind_status=0)
    _insert_agent()
    client = _client()

    first = client.post("/integrations/douyin/accounts/account-open-1/cancel-authorization")
    second = client.post("/integrations/douyin/accounts/account-open-1/cancel-authorization")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["authorization_status"] == "unauthorized"


def test_cancel_authorization_rejects_other_merchant_and_empty_owner_account():
    _insert_account(open_id="account-other", merchant_id="merchant-2")
    _insert_account(open_id="account-empty", merchant_id=None)
    client = _client(_context("merchant-1"))

    other = client.post("/integrations/douyin/accounts/account-other/cancel-authorization")
    empty = client.post("/integrations/douyin/accounts/account-empty/cancel-authorization")

    assert other.status_code == 403
    assert other.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"
    assert empty.status_code == 403
    assert empty.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"


def test_delete_account_marks_account_deleted_and_binding_deleted():
    _insert_account()
    _insert_agent()
    _bind_account()
    client = _client()

    response = client.delete("/integrations/douyin/accounts/account-open-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_open_id"] == "account-open-1"
    assert data["account_status"] == "deleted"
    assert data["binding_status"] == "deleted"
    db = TestSession()
    try:
        account = db.query(DouyinAuthorizedAccount).filter_by(open_id="account-open-1").one()
        binding = db.query(DouyinAccountAgentBinding).filter_by(account_open_id="account-open-1").one()
        assert account.bind_status == 4
        assert account.unbind_time is not None
        assert binding.status == "deleted"
        assert binding.deleted_at is not None
        assert binding.invalid_reason == "account_deleted"
    finally:
        db.close()


def test_delete_account_hides_account_and_blocks_new_binding():
    _insert_account()
    _insert_agent()
    client = _client()

    delete_response = client.delete("/integrations/douyin/accounts/account-open-1")
    list_response = client.get("/integrations/douyin/accounts")
    bind_response = client.put(
        "/integrations/douyin/accounts/account-open-1/agent-binding",
        json={"agent_id": "agent-1"},
    )

    assert delete_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == []
    assert bind_response.status_code == 403
    assert bind_response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_DELETED"


def test_delete_account_is_idempotent():
    _insert_account(bind_status=4)
    client = _client()

    first = client.delete("/integrations/douyin/accounts/account-open-1")
    second = client.delete("/integrations/douyin/accounts/account-open-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["account_status"] == "deleted"


def test_delete_account_rejects_other_merchant_and_empty_owner_account():
    _insert_account(open_id="account-other", merchant_id="merchant-2")
    _insert_account(open_id="account-empty", merchant_id=None)
    client = _client(_context("merchant-1"))

    other = client.delete("/integrations/douyin/accounts/account-other")
    empty = client.delete("/integrations/douyin/accounts/account-empty")

    assert other.status_code == 403
    assert other.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"
    assert empty.status_code == 403
    assert empty.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"
