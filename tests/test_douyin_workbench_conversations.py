import json
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app
from app.models import DouyinAuthorizedAccount, DouyinPrivateMessageSend, DouyinWebhookEvent
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
            is_duplicate=False,
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


def _insert_ai_auto_send_record(
    *,
    conversation_short_id: str = "conv_ai_auto",
    account_open_id: str = "account_ai",
    customer_open_id: str = "customer_ai",
    upstream_msg_id: str = "msg_ai_auto",
    content: str = "您好，可以继续沟通。",
    auto_reply_run_id: int = 123,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinPrivateMessageSend(
                main_account_id=1,
                conversation_short_id=conversation_short_id,
                server_message_id="trigger-msg",
                from_user_id=account_open_id,
                to_user_id=customer_open_id,
                customer_open_id=customer_open_id,
                account_open_id=account_open_id,
                scene="im_reply_msg",
                content=content,
                status="sent",
                manual_confirmed=0,
                auto_send=1,
                send_source="ai_auto",
                operator_id="ai_auto_reply",
                auto_reply_run_id=auto_reply_run_id,
                upstream_msg_id=upstream_msg_id,
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_lead(
    *,
    open_id: str = "customer_001",
    account_open_id: str = "account_001",
    customer_contact: str | None = None,
    extracted_phone: str | None = None,
    extracted_wechat: str | None = None,
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
            extracted_phone=extracted_phone,
            extracted_wechat=extracted_wechat,
            raw_data=json.dumps(raw_payload, ensure_ascii=False),
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _insert_authorized_account(
    *,
    open_id: str = "account_001",
    merchant_id: str = "dev-merchant",
    bind_status: int = 1,
    account_name: str | None = None,
):
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=1,
            open_id=open_id,
            merchant_id=merchant_id,
            bind_status=bind_status,
            account_name=account_name or f"Account {open_id[-3:]}",
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
            is_duplicate=False,
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


def test_ai_auto_sent_message_exposes_ai_source_metadata():
    _insert_event(
        event="im_send_msg",
        open_id="customer_ai",
        account_open_id="account_ai",
        text="您好，可以继续沟通。",
        conversation_short_id="conv_ai_auto",
        server_message_id="msg_ai_auto",
        event_key="event_ai_auto_msg",
    )
    _insert_ai_auto_send_record()

    data = _client().get(
        "/integrations/douyin/conversations/conv_ai_auto/messages",
        params={"account_open_id": "account_ai"},
    ).json()

    assert data["items"][0]["send_source"] == "ai_auto"
    assert data["items"][0]["operator_id"] == "ai_auto_reply"
    assert data["items"][0]["auto_send"] is True
    assert data["items"][0]["auto_reply_run_id"] == 123


def test_conversation_send_records_are_loaded_in_one_batch():
    _insert_event(
        event="im_send_msg",
        open_id="customer_batch",
        account_open_id="account_batch",
        text="第一条回复",
        conversation_short_id="conv_batch",
        server_message_id="msg_batch_1",
        event_key="event_batch_1",
    )
    _insert_event(
        event="im_send_msg",
        open_id="customer_batch",
        account_open_id="account_batch",
        text="第二条回复",
        conversation_short_id="conv_batch",
        server_message_id="msg_batch_2",
        event_key="event_batch_2",
    )
    _insert_ai_auto_send_record(
        conversation_short_id="conv_batch",
        account_open_id="account_batch",
        customer_open_id="customer_batch",
        upstream_msg_id="msg_batch_1",
        content="第一条回复",
        auto_reply_run_id=201,
    )
    _insert_ai_auto_send_record(
        conversation_short_id="conv_batch",
        account_open_id="account_batch",
        customer_open_id="customer_batch",
        upstream_msg_id="msg_batch_2",
        content="第二条回复",
        auto_reply_run_id=202,
    )

    statements: list[str] = []

    def _capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    sqlalchemy_event.listen(test_engine, "before_cursor_execute", _capture_statement)
    try:
        response = _client().get(
            "/integrations/douyin/conversation-messages",
            params={"conversation_key": "conv_batch", "account_open_id": "account_batch"},
        )
    finally:
        sqlalchemy_event.remove(test_engine, "before_cursor_execute", _capture_statement)

    assert response.status_code == 200
    send_record_queries = [
        statement
        for statement in statements
        if "FROM douyin_private_message_sends" in statement
    ]
    assert len(send_record_queries) == 1
    assert [item["auto_reply_run_id"] for item in response.json()["items"]] == [201, 202]


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
        extracted_phone="13800000000",
        status="pending",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_contact/conversations",
        params={"account_open_id": "account_contact"},
    ).json()

    assert "retained_contact" in data["items"][0]["tags"]


def test_conversation_tags_do_not_generate_retained_contact_from_customer_contact_only():
    """仅有 customer_contact、三个权威提取字段（extracted_phone/extracted_wechat/
    all_extracted_contacts）均为空时，不得产生 retained_contact 或 follow_up。

    customer_contact 不自动映射为权威留资字段；留资口径以提取后的独立列为准。
    """
    _insert_event(
        open_id="customer_contact_only",
        account_open_id="account_contact_only",
        text="hello",
        event_key="contact_only_event",
    )
    _insert_lead(
        open_id="customer_contact_only",
        account_open_id="account_contact_only",
        customer_contact="13800000000",
        status="assigned",
    )

    data = _client().get(
        "/integrations/douyin/accounts/account_contact_only/conversations",
        params={"account_open_id": "account_contact_only"},
    ).json()

    tags = data["items"][0]["tags"]
    assert "retained_contact" not in tags
    assert "follow_up" not in tags


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
        extracted_wechat="wechat_001",
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
        extracted_wechat="wechat_002",
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
        extracted_phone="13811112222",
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
        extracted_phone="13822223333",
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
        extracted_phone="13800001111",
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


def test_conversation_profile_extracts_vehicle_budget_year_and_city_from_customer_messages_only():
    base_time = datetime.now() - timedelta(minutes=10)
    conversation_id = "profile_fields_from_messages"
    _insert_event(
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="宝马5系",
        conversation_short_id=conversation_id,
        event_key="profile_fields_1",
        server_message_id="profile_fields_msg_1",
        created_at=base_time,
    )
    _insert_event(
        event="im_send_msg",
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="AI 自动回复里提到18万预算、宝马3系、深圳，这些不能写入画像。",
        conversation_short_id=conversation_id,
        event_key="profile_fields_ai",
        server_message_id="profile_fields_ai_msg",
        created_at=base_time + timedelta(minutes=1),
    )
    _insert_event(
        event="im_send_msg",
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="你收到一条新消息，请打开抖音app查看",
        conversation_short_id=conversation_id,
        event_key="profile_fields_notice",
        server_message_id="profile_fields_notice_msg",
        created_at=base_time + timedelta(minutes=2),
    )
    _insert_event(
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="我预算差不多30万左右吧，主要看20款或者21款的530Li。",
        conversation_short_id=conversation_id,
        event_key="profile_fields_2",
        server_message_id="profile_fields_msg_2",
        created_at=base_time + timedelta(minutes=3),
    )
    _insert_event(
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="广州",
        conversation_short_id=conversation_id,
        event_key="profile_fields_3",
        server_message_id="profile_fields_msg_3",
        created_at=base_time + timedelta(minutes=4),
    )
    _insert_event(
        open_id="customer_profile_fields",
        account_open_id="account_profile_fields",
        text="主要商务，但也考虑家用",
        conversation_short_id=conversation_id,
        event_key="profile_fields_4",
        server_message_id="profile_fields_msg_4",
        created_at=base_time + timedelta(minutes=5),
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile_fields/conversations/profile_fields_from_messages/profile"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_channel"] == "douyin"
    assert data["intent_car"] in {"宝马530Li", "530Li"}
    assert data["car_year"] == "20款 / 21款"
    assert data["budget"] == "30万左右"
    assert data["city"] == "广州"
    assert "18万" not in json.dumps(data, ensure_ascii=False)
    assert "深圳" not in json.dumps(data, ensure_ascii=False)
    assert "purpose" not in data
    assert "usage" not in data


def test_conversation_profile_query_route_accepts_slash_in_conversation_id():
    conversation_id = "conv/open/id"
    _insert_event(
        open_id="customer_profile_slash",
        account_open_id="account_profile_slash",
        text="想看车",
        conversation_short_id=conversation_id,
        event_key="profile_slash_event",
        server_message_id="profile_slash_msg",
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile_slash/conversation-profile",
        params={
            "conversation_id": conversation_id,
            "account_open_id": "account_profile_slash",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation_id"] == conversation_id
    assert data["account_open_id"] == "account_profile_slash"


def test_conversation_profile_query_route_accepts_plus_equal_and_at_in_conversation_id():
    conversation_id = "conv+token=@customer"
    _insert_event(
        open_id="customer_profile_symbols",
        account_open_id="account_profile_symbols",
        text="怎么联系",
        conversation_short_id=conversation_id,
        event_key="profile_symbols_event",
        server_message_id="profile_symbols_msg",
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_profile_symbols/conversation-profile",
        params={
            "conversation_id": conversation_id,
            "account_open_id": "account_profile_symbols",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation_id"] == conversation_id
    assert data["account_open_id"] == "account_profile_symbols"


def test_frontend_profile_url_uses_query_route_and_keeps_manual_send_boundary():
    source = "frontend/src/api/douyinAiCsClient.ts"
    content = open(source, encoding="utf-8").read()
    profile_fn = content.split("export async function getDouyinConversationProfileFrom9000", 1)[1].split(
        "export async function sendDouyinManualMessage",
        1,
    )[0]

    assert "/conversation-profile" in profile_fn
    assert "conversation_id: String(conversationKey)" in profile_fn
    assert "/conversations/" not in profile_fn
    assert '"/integrations/douyin/live-check/messages/send"' in content
    assert "manual_confirmed: true" in content


def test_frontend_workbench_filters_duplicate_status_tags_without_hiding_status_badge():
    source = "frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx"
    content = open(source, encoding="utf-8").read()

    assert "STATUS_DUPLICATE_TAG_VALUES" in content
    assert "visibleConversationTags(conversation.tags, leadStatus)" in content
    assert "conversationLeadStatusForList(" in content
    assert "待跟进" in content
    assert "retained_contact" in content


def test_frontend_workbench_restores_cached_data_and_loads_older_conversations():
    client_source = open("frontend/src/api/douyinAiCsClient.ts", encoding="utf-8").read()
    page_source = open(
        "frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx",
        encoding="utf-8",
    ).read()
    app_source = open("frontend/src/App.tsx", encoding="utf-8").read()

    assert "getDouyinConversationDetail" in client_source
    assert '"/integrations/douyin/conversation-detail"' in client_source
    assert "useQueryClient" in page_source
    assert "douyin-workbench" in page_source
    assert "加载更早会话" in page_source
    assert "queryClient.clear()" in app_source


def test_frontend_douyin_authorization_is_scoped_to_current_state_and_verified_account():
    api_source = open("frontend/src/api/douyinLiveCheck.ts", encoding="utf-8").read()
    type_source = open("frontend/src/api/types.ts", encoding="utf-8").read()
    page_source = open(
        "frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx",
        encoding="utf-8",
    ).read()

    assert "state: string | null" in type_source
    assert "state?: string" in api_source
    assert "params: state ? { state } : undefined" in api_source
    assert "refreshAuthStatus(authUrlResult.data.state || undefined)" in page_source
    assert "const accountFound = Boolean(" in page_source
    assert "setAuthAccountRefreshDone(accountFound)" in page_source
    assert "if (!accountFound)" in page_source
    assert "authCallback?.open_id" not in page_source


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
        extracted_wechat="wechat_b",
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

    def _tracking_row_to_message(db, row):
        parsed_event_ids.append(row.id)
        return original(db, row)

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

    def _tracking_row_to_message(db, row):
        parsed_event_ids.append(row.id)
        return original(db, row)

    with patch.object(service, "_row_to_message", side_effect=_tracking_row_to_message):
        items = _client().get(
            "/integrations/douyin/accounts/account_conversation_perf_target/conversations",
            params={"account_open_id": "account_conversation_perf_target"},
        ).json()["items"]

    assert [item["last_message"] for item in items] == ["target account message"]
    assert parsed_event_ids == [target_id]
    assert not set(parsed_event_ids).intersection(unrelated_ids)


def test_account_conversations_include_messages_older_than_seven_days():
    _insert_event(
        open_id="customer_old_history",
        account_open_id="account_old_history",
        text="三十天前的历史消息",
        conversation_short_id="old_history_conv",
        event_key="old_history_event",
        created_at=datetime.now() - timedelta(days=30),
    )

    response = _client().get(
        "/integrations/douyin/accounts/account_old_history/conversations",
        params={"account_open_id": "account_old_history"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["old_history_conv"]


def test_account_conversations_can_expand_event_window_for_older_history():
    for index in range(101):
        _insert_event(
            open_id=f"customer_history_{index}",
            account_open_id="account_history_window",
            text=f"历史消息 {index}",
            conversation_short_id=f"history_conv_{index}",
            event_key=f"history_event_{index}",
            created_at=datetime.now() - timedelta(minutes=index),
        )

    client = _client()
    first = client.get(
        "/integrations/douyin/accounts/account_history_window/conversations",
        params={"account_open_id": "account_history_window", "event_limit": 100},
    ).json()
    expanded = client.get(
        "/integrations/douyin/accounts/account_history_window/conversations",
        params={"account_open_id": "account_history_window", "event_limit": 200},
    ).json()

    assert len(first["items"]) == 100
    assert first["has_more"] is True
    assert len(expanded["items"]) == 101
    assert expanded["has_more"] is False


def test_conversation_detail_loads_messages_once_for_messages_and_profile():
    _insert_event(
        open_id="customer_detail_once",
        account_open_id="account_detail_once",
        text="想看一辆二手车",
        conversation_short_id="detail_once_conv",
        event_key="detail_once_event",
    )

    from app.services import douyin_workbench_conversation_service as service

    with patch.object(service, "_load_messages", wraps=service._load_messages) as load_messages:
        response = _client().get(
            "/integrations/douyin/conversation-detail",
            params={
                "conversation_key": "detail_once_conv",
                "account_open_id": "account_detail_once",
            },
        )

    assert response.status_code == 200
    assert load_messages.call_count == 1
    assert response.json()["messages"]["items"][0]["content"] == "想看一辆二手车"
    assert response.json()["profile"]["conversation_id"] == "detail_once_conv"


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


def test_accounts_list_hides_event_derived_account_without_binding():
    """无有效持久化绑定的事件账号不进入普通商户账号列表（B4）。"""
    _insert_event(
        open_id="customer_account_fallback",
        account_open_id="account_from_events",
        text="hello from history",
        event_key="account_fallback_1",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        data = _client().get("/integrations/douyin/live-check/accounts").json()["data"]

    # 当前商户（dev-merchant）无有效绑定 → 事件派生账号不可见
    assert data["total"] == 0
    assert data["source"] == "persisted_bind_info_current_merchant"
    assert data["items"] == []


def test_accounts_list_returns_single_persisted_binding_for_authorized_account():
    """当前商户有效绑定账号只返回一个持久化授权项，同账号事件不产生重复（B5）。"""
    _insert_authorized_account(open_id="account_dup", account_name="Authorized Account")
    _insert_event(
        open_id="customer_dup",
        account_open_id="account_dup",
        text="same account event",
        event_key="account_dup_event",
    )

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        data = _client().get("/integrations/douyin/live-check/accounts").json()["data"]

    assert data["total"] == 1
    assert data["source"] == "persisted_bind_info_current_merchant"
    assert data["items"][0]["account_open_id"] == "account_dup"
    assert data["items"][0]["source"] == "persisted_bind_info"
    assert data["items"][0]["is_authorized"] is True


def test_accounts_list_groups_different_persisted_account_open_ids():
    """当前商户多个有效绑定账号各自返回一个持久化授权项。"""
    _insert_authorized_account(open_id="account_multi_a")
    _insert_authorized_account(open_id="account_multi_b")

    with patch("app.config.DY_LIVE_CHECK_ENABLED", True):
        items = _client().get("/integrations/douyin/live-check/accounts").json()["data"]["items"]

    assert {item["account_open_id"] for item in items} == {"account_multi_a", "account_multi_b"}


def test_persisted_binding_account_can_load_real_conversations():
    """有效绑定账号仍能加载所属会话（B6）。"""
    _insert_authorized_account(open_id="account_event_loads_conversations")
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


def test_accounts_list_keeps_webhook_events_api_unchanged():
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


def test_frontend_mark_read_request_includes_last_seen_event_id():
    """前端 mark-read 请求类型必须包含必填 last_seen_event_id。"""
    source = open("frontend/src/api/douyinAiCsClient.ts", encoding="utf-8").read()
    mark_read_section = source.split("DouyinConversationMarkReadRequest", 1)[1].split("}")[0]
    assert "last_seen_event_id" in mark_read_section


def test_frontend_workbench_submits_read_after_render_with_event_id():
    """前端工作台仅在详情渲染后提交已读，使用会话级成功凭据。"""
    page = open(
        "frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx",
        encoding="utf-8",
    ).read()
    # 删除点击会话时的本地清零（onClick 不应调用 markConversationReadLocally）
    click_section = page.split("onClick={() => {", 1)[1].split("}", 1)[0]
    assert "markConversationReadLocally" not in click_section
    # 删除乐观清零链路（applyReadWatermarks/readWatermarksRef/markConversationReadLocally 不得存在）
    assert "applyReadWatermarks" not in page
    assert "readWatermarksRef" not in page
    assert "markConversationReadLocally" not in page
    # 会话级成功凭据替代全局裸事件 ID
    assert "detailSuccessCredentialRef" in page
    assert "consumedCredentialKeyRef" in page
    # 凭据包含 account_open_id + conversation_id + request_seq + max_event_id
    credential_section = page.split("detailSuccessCredentialRef.current = {")[1].split("}")[0]
    assert "account_open_id" in credential_section
    assert "conversation_id" in credential_section
    assert "request_seq" in credential_section
    assert "max_event_id" in credential_section
    # 已读 effect 核对当前账号、会话和请求序号
    assert "credential.account_open_id !== selectedAccount.account_open_id" in page
    assert "credential.conversation_id !== selectedConversationId" in page
    assert "credential.request_seq !== detailRequestSeqRef.current" in page
    # mark-read 失败不清零：清除已消费凭据使后续轮询可重试
    assert "consumedCredentialKeyRef.current = null" in page
    # mark-read 成功后刷新服务端权威未读
    assert "loadConversations" in page.split("persistConversationRead = useCallback")[1].split("}, [")[0]
    # 轮询条件显式包含"当前选中会话仍有未读"时重新加载详情并重试
    assert "afterUnread > 0" in page
    # persistConversationRead 接受 lastSeenEventId 参数
    persist_section = page.split("persistConversationRead = useCallback")[1].split("}, [")[0]
    assert "lastSeenEventId" in persist_section
    assert "last_seen_event_id" in persist_section
