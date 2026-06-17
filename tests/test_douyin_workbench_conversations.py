import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app
from app.models import DouyinWebhookEvent


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


def _client() -> TestClient:
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _payload(
    *,
    event: str = "im_receive_msg",
    open_id: str = "customer_001",
    account_open_id: str = "account_001",
    text: str = "hello",
    conversation_short_id: str | None = None,
    server_message_id: str = "msg_001",
    create_time: int = 1710000000000,
) -> dict:
    from_user_id = open_id if event == "im_receive_msg" else account_open_id
    to_user_id = account_open_id if event == "im_receive_msg" else open_id
    content = {
        "create_time": create_time,
        "server_message_id": server_message_id,
        "message_type": "text",
        "open_id": open_id,
        "account_open_id": account_open_id,
        "text": text,
        "user_infos": [
            {
                "open_id": open_id,
                "nick_name": f"Customer {open_id[-3:]}",
                "avatar": f"https://example.com/{open_id}.jpg",
            },
            {
                "open_id": account_open_id,
                "nick_name": f"Account {account_open_id[-3:]}",
                "avatar": f"https://example.com/{account_open_id}.jpg",
            },
        ],
    }
    if conversation_short_id is not None:
        content["conversation_short_id"] = conversation_short_id
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "content": json.dumps(content, ensure_ascii=False),
    }


def _insert_event(
    *,
    event: str = "im_receive_msg",
    open_id: str = "customer_001",
    account_open_id: str = "account_001",
    text: str = "hello",
    conversation_short_id: str | None = None,
    event_key: str = "event_001",
    server_message_id: str = "msg_001",
    created_at: datetime | None = None,
    lead_id: int | None = None,
) -> int:
    db = TestSession()
    try:
        payload = _payload(
            event=event,
            open_id=open_id,
            account_open_id=account_open_id,
            text=text,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
        )
        item = DouyinWebhookEvent(
            event=event,
            from_user_id=payload["from_user_id"],
            to_user_id=payload["to_user_id"],
            event_key=event_key,
            is_duplicate=0,
            lead_id=lead_id,
            raw_body=json.dumps(payload, ensure_ascii=False),
            created_at=created_at or datetime.now(),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def test_customer_private_message_aggregates_to_conversation_without_contact():
    _insert_event(
        open_id="customer_no_contact",
        account_open_id="account_real",
        text="hello",
        event_key="no_contact",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_real/conversations",
        params={"account_open_id": "account_real"},
    ).json()

    assert data["items"][0]["open_id"] == "customer_no_contact"
    assert data["items"][0]["last_message"] == "hello"
    assert data["items"][0]["lead_status"] == "contact_not_found"


def test_same_customer_and_account_aggregate_to_same_conversation_without_short_id():
    older = datetime.now() - timedelta(minutes=2)
    newer = datetime.now() - timedelta(minutes=1)
    _insert_event(
        open_id="customer_same",
        account_open_id="account_same",
        text="first",
        event_key="same_1",
        server_message_id="same_msg_1",
        created_at=older,
    )
    _insert_event(
        event="im_send_msg",
        open_id="customer_same",
        account_open_id="account_same",
        text="reply",
        event_key="same_2",
        server_message_id="same_msg_2",
        created_at=newer,
    )

    client = _client()
    conversations = client.get(
        "/integrations/douyin/accounts/account_same/conversations",
        params={"account_open_id": "account_same"},
    ).json()["items"]
    messages = client.get(
        f"/integrations/douyin/conversations/{conversations[0]['id']}/messages",
        params={"account_open_id": "account_same"},
    ).json()["items"]

    assert len(conversations) == 1
    assert conversations[0]["last_message"] == "reply"
    assert [item["content"] for item in messages] == ["first", "reply"]
    assert [item["sender_type"] for item in messages] == ["customer", "staff"]


def test_conversation_short_id_has_priority_over_open_id_pair():
    _insert_event(
        open_id="customer_short",
        account_open_id="account_short",
        text="from short id",
        conversation_short_id="short_conv_001",
        event_key="short_1",
    )

    conversation = _client().get(
        "/integrations/douyin/accounts/account_short/conversations",
        params={"account_open_id": "account_short"},
    ).json()["items"][0]

    assert conversation["id"] == "short_conv_001"
    assert conversation["conversation_short_id"] == "short_conv_001"


def test_messages_are_sorted_by_event_time():
    newer = datetime.now()
    older = newer - timedelta(minutes=5)
    _insert_event(
        open_id="customer_sort",
        account_open_id="account_sort",
        text="second in db first by id",
        conversation_short_id="sort_conv",
        event_key="sort_2",
        server_message_id="sort_msg_2",
        created_at=newer,
    )
    _insert_event(
        open_id="customer_sort",
        account_open_id="account_sort",
        text="first by time",
        conversation_short_id="sort_conv",
        event_key="sort_1",
        server_message_id="sort_msg_1",
        created_at=older,
    )

    messages = _client().get(
        "/integrations/douyin/conversations/sort_conv/messages",
        params={"account_open_id": "account_sort"},
    ).json()["items"]

    assert [item["content"] for item in messages] == ["first by time", "second in db first by id"]


def test_different_douyin_accounts_are_isolated():
    _insert_event(
        open_id="same_customer",
        account_open_id="account_a",
        text="account a message",
        event_key="isolated_a",
    )
    _insert_event(
        open_id="same_customer",
        account_open_id="account_b",
        text="account b message",
        event_key="isolated_b",
    )

    items = _client().get(
        "/integrations/douyin/accounts/account_a/conversations",
        params={"account_open_id": "account_a"},
    ).json()["items"]

    assert len(items) == 1
    assert items[0]["account_open_id"] == "account_a"
    assert items[0]["last_message"] == "account a message"
