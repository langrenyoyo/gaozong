import json
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app
from app.models import DouyinWebhookEvent
from app.models import DouyinLead
from app.services.douyin_live_check_service import record_oauth_callback, reset_live_check_state


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    reset_live_check_state()


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


def _media_payload(
    *,
    event: str = "im_receive_msg",
    open_id: str = "customer_media",
    account_open_id: str = "account_media",
    message_type: str = "image",
    conversation_short_id: str = "media_conv_001",
    server_message_id: str = "media_msg_001",
    resource_url: str | None = "https://example.com/media.png",
    resource_key: str = "url",
) -> dict:
    from_user_id = open_id if event == "im_receive_msg" else account_open_id
    to_user_id = account_open_id if event == "im_receive_msg" else open_id
    content = {
        "create_time": 1710000000000,
        "server_message_id": server_message_id,
        "message_type": message_type,
        "media_type": message_type,
        "conversation_short_id": conversation_short_id,
        "open_id": open_id,
        "account_open_id": account_open_id,
        "user_infos": [
            {"open_id": open_id, "nick_name": "Media Customer"},
            {"open_id": account_open_id, "nick_name": "Media Account"},
        ],
    }
    content[resource_key] = resource_url
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


def _insert_lead(
    *,
    open_id: str = "customer_001",
    account_open_id: str = "account_001",
    customer_contact: str | None = None,
    lead_score: int | None = None,
    raw_data: dict | None = None,
    status: str = "pending",
):
    db = TestSession()
    try:
        raw_payload = dict(raw_data or {})
        raw_payload.setdefault("account_open_id", account_open_id)
        if lead_score is not None:
            raw_payload["lead_score"] = lead_score
        row = DouyinLead(
            source="douyin",
            source_id=open_id,
            customer_name=f"Customer {open_id[-3:]}",
            customer_contact=customer_contact,
            raw_data=json.dumps(raw_payload, ensure_ascii=False),
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _insert_media_event(
    *,
    event_key: str = "media_event_001",
    message_type: str = "image",
    conversation_short_id: str = "media_conv_001",
    server_message_id: str = "media_msg_001",
    resource_url: str | None = "https://example.com/media.png",
    resource_key: str = "url",
) -> int:
    db = TestSession()
    try:
        payload = _media_payload(
            message_type=message_type,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            resource_url=resource_url,
            resource_key=resource_key,
        )
        content = json.loads(payload["content"])
        item = DouyinWebhookEvent(
            event=payload["event"],
            from_user_id=payload["from_user_id"],
            to_user_id=payload["to_user_id"],
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            message_type=message_type,
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            event_key=event_key,
            is_duplicate=0,
            raw_body=json.dumps(payload, ensure_ascii=False),
            created_at=datetime.now(),
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


def test_conversation_tags_are_empty_when_no_deterministic_signal_exists():
    _insert_event(
        open_id="customer_no_tags",
        account_open_id="account_no_tags",
        text="hello",
        event_key="no_tags",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_no_tags/conversations",
        params={"account_open_id": "account_no_tags"},
    ).json()

    assert data["items"][0]["tags"] == []
    assert data["items"][0]["lead_status"] == "contact_not_found"


def test_conversation_tags_generate_retained_contact_from_lead_contact():
    _insert_event(
        open_id="customer_contact",
        account_open_id="account_contact",
        text="hello",
        event_key="contact_event",
    )
    _insert_lead(
        open_id="customer_contact",
        account_open_id="account_contact",
        customer_contact="13800000000",
        status="pending",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_contact/conversations",
        params={"account_open_id": "account_contact"},
    ).json()

    assert "retained_contact" in data["items"][0]["tags"]


def test_conversation_tags_generate_high_intent_from_lead_score():
    _insert_event(
        open_id="customer_high_intent",
        account_open_id="account_high_intent",
        text="hello",
        event_key="high_intent_event",
    )
    _insert_lead(
        open_id="customer_high_intent",
        account_open_id="account_high_intent",
        lead_score=85,
        status="pending",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_high_intent/conversations",
        params={"account_open_id": "account_high_intent"},
    ).json()

    assert "high_intent" in data["items"][0]["tags"]


def test_conversation_tags_high_intent_keywords_do_not_imply_retained_contact():
    _insert_event(
        open_id="customer_high_intent_text",
        account_open_id="account_high_intent_text",
        text="这台车价格能谈吗，怎么联系",
        event_key="high_intent_text_event",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_high_intent_text/conversations",
        params={"account_open_id": "account_high_intent_text"},
    ).json()

    assert "high_intent" in data["items"][0]["tags"]
    assert "retained_contact" not in data["items"][0]["tags"]


def test_conversation_tags_generate_manual_required_from_text_hint():
    _insert_event(
        open_id="customer_manual",
        account_open_id="account_manual",
        text="麻烦转人工客服联系我",
        event_key="manual_event",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_manual/conversations",
        params={"account_open_id": "account_manual"},
    ).json()

    assert "manual_required" in data["items"][0]["tags"]


def test_conversation_tags_generate_follow_up_when_retained_contact_has_no_outbound_reply():
    _insert_event(
        open_id="customer_follow_up",
        account_open_id="account_follow_up",
        text="hello",
        event_key="follow_up_event",
    )
    _insert_lead(
        open_id="customer_follow_up",
        account_open_id="account_follow_up",
        customer_contact="wechat_001",
        status="assigned",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_follow_up/conversations",
        params={"account_open_id": "account_follow_up"},
    ).json()

    assert "retained_contact" in data["items"][0]["tags"]
    assert "follow_up" in data["items"][0]["tags"]


def test_conversation_tags_do_not_mark_follow_up_after_outbound_message():
    _insert_event(
        open_id="customer_follow_up_sent",
        account_open_id="account_follow_up_sent",
        text="hello",
        event_key="follow_up_sent_inbound",
    )
    _insert_event(
        event="im_send_msg",
        open_id="customer_follow_up_sent",
        account_open_id="account_follow_up_sent",
        text="已收到",
        event_key="follow_up_sent_outbound",
    )
    _insert_lead(
        open_id="customer_follow_up_sent",
        account_open_id="account_follow_up_sent",
        customer_contact="wechat_002",
        status="assigned",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_follow_up_sent/conversations",
        params={"account_open_id": "account_follow_up_sent"},
    ).json()

    assert "retained_contact" in data["items"][0]["tags"]
    assert "follow_up" not in data["items"][0]["tags"]


def test_conversation_tags_remain_isolated_between_multiple_conversations():
    _insert_event(
        open_id="customer_tag_a",
        account_open_id="account_tag_isolation",
        text="麻烦转人工",
        event_key="tag_a_event",
    )
    _insert_event(
        open_id="customer_tag_b",
        account_open_id="account_tag_isolation",
        text="hello",
        event_key="tag_b_event",
    )
    _insert_lead(
        open_id="customer_tag_b",
        account_open_id="account_tag_isolation",
        customer_contact="13811112222",
        lead_score=90,
        status="pending",
    )

    items = _client().get(
        "/integrations/douyin/accounts/account_tag_isolation/conversations",
        params={"account_open_id": "account_tag_isolation"},
    ).json()["items"]

    tags_by_customer = {item["open_id"]: item["tags"] for item in items}
    assert "manual_required" in tags_by_customer["customer_tag_a"]
    assert "manual_required" not in tags_by_customer["customer_tag_b"]
    assert "retained_contact" in tags_by_customer["customer_tag_b"]
    assert "high_intent" in tags_by_customer["customer_tag_b"]


def test_conversation_tags_prefer_lead_raw_account_open_id_when_same_open_id_exists_on_multiple_accounts():
    _insert_event(
        open_id="customer_shared_open_id",
        account_open_id="account_shared_a",
        text="hello from a",
        event_key="shared_account_a_event",
    )
    _insert_event(
        open_id="customer_shared_open_id",
        account_open_id="account_shared_b",
        text="hello from b",
        event_key="shared_account_b_event",
    )
    _insert_lead(
        open_id="customer_shared_open_id",
        account_open_id="account_shared_b",
        customer_contact="13822223333",
        status="assigned",
    )

    account_a_items = _client().get(
        "/integrations/douyin/accounts/account_shared_a/conversations",
        params={"account_open_id": "account_shared_a"},
    ).json()["items"]
    account_b_items = _client().get(
        "/integrations/douyin/accounts/account_shared_b/conversations",
        params={"account_open_id": "account_shared_b"},
    ).json()["items"]

    assert account_a_items[0]["tags"] == []
    assert "retained_contact" in account_b_items[0]["tags"]


def test_conversation_profile_returns_customer_fields_from_webhook_and_lead_raw_data():
    lead = _insert_lead(
        open_id="customer_profile",
        account_open_id="account_profile",
        customer_contact="13800001111",
        lead_score=120,
        status="assigned",
        raw_data={
            "account_open_id": "account_profile",
            "intent_car": "奥迪A6",
            "car_year": "2022",
            "budget_range": "20-30万",
            "city": "杭州",
        },
    )
    _insert_event(
        open_id="customer_profile",
        account_open_id="account_profile",
        text="想看车，怎么联系",
        conversation_short_id="profile_conv",
        event_key="profile_event",
        server_message_id="profile_msg",
        lead_id=lead.id,
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile/conversations/profile_conv/profile"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation_id"] == "profile_conv"
    assert data["account_open_id"] == "account_profile"
    assert data["open_id"] == "customer_profile"
    assert data["nickname"] == "Customer ile"
    assert data["avatar"] == "https://example.com/customer_profile.jpg"
    assert data["online_status"] == "unknown"
    assert data["source_channel"] == "douyin"
    assert data["intent_car"] == "奥迪A6"
    assert data["car_year"] == "2022"
    assert data["budget"] == "20-30万"
    assert data["city"] == "杭州"
    assert data["lead_score"] == 100
    assert "retained_contact" in data["tags"]
    assert "high_intent" in data["tags"]
    assert data["trace"] == {
        "event_key": "profile_event",
        "conversation_short_id": "profile_conv",
        "server_message_id": "profile_msg",
        "source": "webhook_events",
        "created_at": data["trace"]["created_at"],
    }
    assert "raw_body" not in data["trace"]
    assert data["lead"]["id"] == lead.id
    assert data["lead"]["status"] == "assigned"
    assert data["lead"]["customer_contact"] == "13800001111"


def test_conversation_profile_returns_404_when_conversation_not_found_in_account_scope():
    _insert_event(
        open_id="customer_profile_scope",
        account_open_id="account_profile_scope_a",
        text="hello",
        conversation_short_id="profile_scope_conv",
        event_key="profile_scope_event",
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile_scope_b/conversations/profile_scope_conv/profile"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DOUYIN_CONVERSATION_PROFILE_NOT_FOUND"


def test_conversation_profile_keeps_same_conversation_key_isolated_by_account():
    _insert_event(
        open_id="customer_profile_a",
        account_open_id="account_profile_a",
        text="account a",
        conversation_short_id="shared_profile_conv",
        event_key="profile_account_a",
    )
    _insert_event(
        open_id="customer_profile_b",
        account_open_id="account_profile_b",
        text="account b",
        conversation_short_id="shared_profile_conv",
        event_key="profile_account_b",
    )
    _insert_lead(
        open_id="customer_profile_b",
        account_open_id="account_profile_b",
        customer_contact="wechat_b",
        raw_data={"account_open_id": "account_profile_b", "lead_score": 88},
        status="assigned",
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile_b/conversations/shared_profile_conv/profile"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_open_id"] == "account_profile_b"
    assert data["open_id"] == "customer_profile_b"
    assert "retained_contact" in data["tags"]
    assert data["trace"]["event_key"] == "profile_account_b"


def test_conversation_profile_returns_safe_empty_values_without_optional_profile_fields():
    _insert_event(
        open_id="customer_empty_profile",
        account_open_id="account_empty_profile",
        text="hello",
        conversation_short_id="empty_profile_conv",
        event_key="empty_profile_event",
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_empty_profile/conversations/empty_profile_conv/profile"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["nickname"] == "Customer ile"
    assert data["avatar"] == "https://example.com/customer_empty_profile.jpg"
    assert data["intent_car"] is None
    assert data["car_year"] is None
    assert data["budget"] is None
    assert data["city"] is None
    assert data["lead_score"] == 0
    assert data["lead"] is None


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


def test_query_conversation_messages_supports_key_with_slash_plus_and_equals():
    conversation_key = "@9VxWzqPHW8E4PX2vc4woV87902DrPv+GO5ByqQylLFgQZvX+60zdRmYqig357zEB/x3+IH10/OLr3uaiHvEJUA=="
    _insert_event(
        open_id="customer_special_key",
        account_open_id="account_special_key",
        text="special key message",
        conversation_short_id=conversation_key,
        event_key="special_key_event",
    )

    messages = _client().get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation_key,
            "account_open_id": "account_special_key",
        },
    ).json()["items"]

    assert [item["content"] for item in messages] == ["special key message"]


def test_query_conversation_messages_keeps_account_open_id_isolation():
    conversation_key = "shared_special_key"
    _insert_event(
        open_id="customer_isolated_a",
        account_open_id="account_query_a",
        text="account a query message",
        conversation_short_id=conversation_key,
        event_key="query_account_a",
    )
    _insert_event(
        open_id="customer_isolated_b",
        account_open_id="account_query_b",
        text="account b query message",
        conversation_short_id=conversation_key,
        event_key="query_account_b",
    )

    messages = _client().get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation_key,
            "account_open_id": "account_query_b",
        },
    ).json()["items"]

    assert [item["content"] for item in messages] == ["account b query message"]


def test_query_conversation_messages_does_not_parse_unrelated_events():
    conversation_key = "target_perf_conv"
    target_id = _insert_event(
        open_id="customer_perf_target",
        account_open_id="account_perf_target",
        text="target message",
        conversation_short_id=conversation_key,
        event_key="perf_target",
    )
    unrelated_ids = [
        _insert_event(
            open_id=f"customer_perf_other_{index}",
            account_open_id="account_perf_other",
            text=f"other message {index}",
            conversation_short_id=f"other_perf_conv_{index}",
            event_key=f"perf_other_{index}",
        )
        for index in range(8)
    ]

    parsed_event_ids: list[int] = []

    from app.services import douyin_workbench_conversation_service as service

    original = service._row_to_message

    def _tracking_row_to_message(row):
        parsed_event_ids.append(row.id)
        return original(row)

    with patch.object(service, "_row_to_message", side_effect=_tracking_row_to_message):
        messages = _client().get(
            "/integrations/douyin/conversation-messages",
            params={
                "conversation_key": conversation_key,
                "account_open_id": "account_perf_target",
            },
        ).json()["items"]

    assert [item["content"] for item in messages] == ["target message"]
    assert parsed_event_ids == [target_id]
    assert not set(parsed_event_ids).intersection(unrelated_ids)


def test_account_conversations_does_not_parse_unrelated_account_events():
    target_id = _insert_event(
        open_id="customer_account_perf_target",
        account_open_id="account_conversation_perf_target",
        text="target account message",
        conversation_short_id="account_perf_conv",
        event_key="account_perf_target",
    )
    unrelated_ids = [
        _insert_event(
            open_id=f"customer_account_perf_other_{index}",
            account_open_id="account_conversation_perf_other",
            text=f"other account message {index}",
            conversation_short_id=f"account_other_perf_conv_{index}",
            event_key=f"account_perf_other_{index}",
        )
        for index in range(8)
    ]

    parsed_event_ids: list[int] = []

    from app.services import douyin_workbench_conversation_service as service

    original = service._row_to_message

    def _tracking_row_to_message(row):
        parsed_event_ids.append(row.id)
        return original(row)

    with patch.object(service, "_row_to_message", side_effect=_tracking_row_to_message):
        items = _client().get(
            "/integrations/douyin/accounts/account_conversation_perf_target/conversations",
            params={"account_open_id": "account_conversation_perf_target"},
        ).json()["items"]

    assert [item["last_message"] for item in items] == ["target account message"]
    assert parsed_event_ids == [target_id]
    assert not set(parsed_event_ids).intersection(unrelated_ids)


def test_query_conversation_messages_keeps_contact_not_found_message_visible():
    _insert_event(
        open_id="customer_query_no_contact",
        account_open_id="account_query_no_contact",
        text="hello no contact",
        conversation_short_id="query_no_contact_conv",
        event_key="query_no_contact",
    )

    client = _client()
    conversation = client.get(
        "/integrations/douyin/accounts/account_query_no_contact/conversations",
        params={"account_open_id": "account_query_no_contact"},
    ).json()["items"][0]
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation["id"],
            "account_open_id": "account_query_no_contact",
        },
    ).json()["items"]

    assert conversation["lead_status"] == "contact_not_found"
    assert messages[0]["content"] == "hello no contact"


def test_query_conversation_messages_exposes_media_fields_without_text():
    _insert_media_event(
        message_type="user_local_image",
        conversation_short_id="media_conv_001",
        server_message_id="media_msg_001",
    )

    client = _client()
    conversation = client.get(
        "/integrations/douyin/accounts/account_media/conversations",
        params={"account_open_id": "account_media"},
    ).json()["items"][0]
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation["id"],
            "account_open_id": "account_media",
        },
    ).json()["items"]

    assert conversation["conversation_short_id"] == "media_conv_001"
    assert conversation["last_message"] == "[图片]"
    assert messages[0]["conversation_short_id"] == "media_conv_001"
    assert messages[0]["server_message_id"] == "media_msg_001"
    assert messages[0]["message_type"] == "user_local_image"
    assert messages[0]["media_type"] == "image"
    assert messages[0]["resource_url"] == "https://example.com/media.png"
    assert messages[0]["source_url"] == "https://example.com/media.png"
    assert messages[0]["downloadable_resource"] is True
    assert messages[0]["resource_missing_reason"] is None
    assert messages[0]["content"] == "[图片]"


def test_query_conversation_messages_marks_media_without_url_not_downloadable():
    _insert_media_event(
        message_type="user_local_image",
        conversation_short_id="media_missing_url_conv",
        server_message_id="media_missing_url_msg",
        resource_url=None,
        resource_key="file_Url",
    )

    messages = _client().get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": "media_missing_url_conv",
            "account_open_id": "account_media",
        },
    ).json()["items"]

    assert messages[0]["message_type"] == "user_local_image"
    assert messages[0]["media_type"] == "image"
    assert messages[0]["resource_url"] is None
    assert messages[0]["source_url"] is None
    assert messages[0]["downloadable_resource"] is False
    assert messages[0]["resource_missing_reason"] == "resource_url_not_found"


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


def test_accounts_fallback_returns_event_derived_account_when_live_check_memory_empty():
    _insert_event(
        open_id="customer_account_fallback",
        account_open_id="account_from_events",
        text="hello from history",
        event_key="account_fallback_1",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        data = _client().get("/integrations/douyin/live-check/accounts").json()["data"]

    assert data["total"] == 1
    assert data["source"] == "persisted_bind_info_with_live_check_memory_and_webhook_events_fallback"
    assert data["items"][0]["account_open_id"] == "account_from_events"
    assert data["items"][0]["source"] == "webhook_events"
    assert data["items"][0]["is_authorized"] is False
    assert data["items"][0]["has_events"] is True


def test_accounts_fallback_does_not_duplicate_authorized_account():
    record_oauth_callback({"open_id": "account_dup", "nick_name": "Authorized Account"})
    _insert_event(
        open_id="customer_dup",
        account_open_id="account_dup",
        text="same account event",
        event_key="account_dup_event",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        data = _client().get("/integrations/douyin/live-check/accounts").json()["data"]

    assert data["total"] == 1
    assert data["items"][0]["account_open_id"] == "account_dup"
    assert data["items"][0]["source"] == "live_check_oauth_callback"


def test_accounts_fallback_groups_different_account_open_ids():
    _insert_event(
        open_id="customer_multi_1",
        account_open_id="account_multi_a",
        text="message a",
        event_key="account_multi_a_event",
    )
    _insert_event(
        open_id="customer_multi_2",
        account_open_id="account_multi_b",
        text="message b",
        event_key="account_multi_b_event",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        items = _client().get("/integrations/douyin/live-check/accounts").json()["data"]["items"]

    assert {item["account_open_id"] for item in items} == {"account_multi_a", "account_multi_b"}


def test_event_derived_account_can_load_real_conversations():
    _insert_event(
        open_id="customer_from_event_account",
        account_open_id="account_event_loads_conversations",
        text="conversation is visible",
        event_key="event_account_conversation",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        account = _client().get("/integrations/douyin/live-check/accounts").json()["data"]["items"][0]
    conversations = _client().get(
        f"/integrations/douyin/accounts/{account['account_id']}/conversations",
        params={"account_open_id": account["account_open_id"]},
    ).json()["items"]

    assert conversations[0]["last_message"] == "conversation is visible"
    assert conversations[0]["lead_status"] == "contact_not_found"


def test_accounts_fallback_keeps_webhook_events_api_unchanged():
    _insert_event(
        open_id="customer_raw_unchanged",
        account_open_id="account_raw_unchanged",
        text="raw event still visible",
        event_key="raw_unchanged",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        _client().get("/integrations/douyin/live-check/accounts")
    data = _client().get("/webhook-events?page=1&page_size=5").json()["data"]

    assert data["total"] == 1
    assert data["items"][0]["event_key"] == "raw_unchanged"
    assert data["items"][0]["message_text"] == "raw event still visible"
