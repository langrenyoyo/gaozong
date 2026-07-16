import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinAuthorizedAccount, DouyinWebhookEvent


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(merchant_id="merchant-1", permission_codes: list[str] | None = None):
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes or ["auto_wechat:douyin_ai_cs"],
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


def _insert_account(open_id="account-open-1", merchant_id="merchant-1"):
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=open_id,
            merchant_id=merchant_id,
            bind_status=1,
            account_name=f"account {open_id}",
        )
        db.add(row)
        db.commit()
        return row
    finally:
        db.close()


def _insert_event(
    *,
    event: str = "im_receive_msg",
    account_open_id: str = "account-open-1",
    customer_open_id: str = "customer-1",
    conversation_short_id: str | None = "conv-1",
    event_key: str = "event-1",
    created_at: datetime | None = None,
):
    db = TestSession()
    try:
        content = {
            "text": f"{event} {event_key}",
            "account_open_id": account_open_id,
            "open_id": customer_open_id,
        }
        if conversation_short_id is not None:
            content["conversation_short_id"] = conversation_short_id
        row = DouyinWebhookEvent(
            event=event,
            event_key=event_key,
            from_user_id=customer_open_id if event == "im_receive_msg" else account_open_id,
            to_user_id=account_open_id if event == "im_receive_msg" else customer_open_id,
            conversation_short_id=conversation_short_id,
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=0,
            created_at=created_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _conversation_unread(account_open_id="account-open-1", conversation_id="conv-1") -> int:
    response = _client().get(
        f"/integrations/douyin/accounts/{account_open_id}/conversations",
        params={"account_open_id": account_open_id},
    )
    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == conversation_id)
    return item["unread_count"]


def test_no_read_state_keeps_legacy_unread_count():
    _insert_account()
    _insert_event(event_key="inbound-1")
    _insert_event(event_key="inbound-2")
    _insert_event(event="im_send_msg", event_key="outbound-1")

    assert _conversation_unread() == 2


def test_mark_read_clears_current_conversation_and_persists_after_refresh():
    _insert_account()
    _insert_event(event_key="inbound-1")
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["conversation_key"] == "conv-1"
    assert _conversation_unread() == 0


def test_new_inbound_after_mark_read_restores_unread_count_but_outbound_does_not():
    base = datetime.now() - timedelta(minutes=5)
    _insert_account()
    _insert_event(event_key="inbound-1", created_at=base)
    client = _client()
    assert client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    ).status_code == 200

    _insert_event(event="im_send_msg", event_key="outbound-after-read", created_at=base + timedelta(minutes=1))
    assert _conversation_unread() == 0

    _insert_event(event_key="inbound-after-read", created_at=base + timedelta(minutes=2))
    assert _conversation_unread() == 1


def test_mark_read_is_isolated_by_merchant_and_account_open_id():
    _insert_account(open_id="account-open-1", merchant_id="merchant-1")
    _insert_account(open_id="account-open-2", merchant_id="merchant-1")
    _insert_event(account_open_id="account-open-1", event_key="account-1-inbound")
    _insert_event(account_open_id="account-open-2", event_key="account-2-inbound")
    client = _client(_context("merchant-1"))

    assert client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    ).status_code == 200

    assert _conversation_unread("account-open-1") == 0
    assert _conversation_unread("account-open-2") == 1

    forbidden = _client(_context("merchant-2")).post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )
    assert forbidden.status_code == 403


def test_mark_read_supports_fallback_conversation_key_without_short_id():
    _insert_account()
    _insert_event(conversation_short_id=None, event_key="fallback-inbound")
    fallback_key = "account-open-1:customer-1"
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": fallback_key,
            "customer_open_id": "customer-1",
        },
    )

    assert response.status_code == 200
    assert _conversation_unread("account-open-1", fallback_key) == 0


def test_douyin_workbench_user_conversation_entries_require_douyin_ai_cs_permission():
    _insert_account()
    _insert_event(event_key="inbound-1")
    denied = _client(_context(permission_codes=["auto_wechat:leads"]))

    responses = [
        denied.get("/integrations/douyin/accounts/account-open-1/conversations"),
        denied.get("/integrations/douyin/conversations/conv-1/messages", params={"account_open_id": "account-open-1"}),
        denied.get(
            "/integrations/douyin/accounts/account-open-1/conversation-profile",
            params={"conversation_id": "conv-1"},
        ),
        denied.get("/integrations/douyin/accounts/account-open-1/conversations/conv-1/profile"),
        denied.get(
            "/integrations/douyin/conversation-messages",
            params={"conversation_key": "conv-1", "account_open_id": "account-open-1"},
        ),
        denied.get(
            "/integrations/douyin/conversation-detail",
            params={"conversation_key": "conv-1", "account_open_id": "account-open-1"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]
