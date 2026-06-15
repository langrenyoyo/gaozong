"""原始 webhook 事件只读查询接口测试。"""

import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.integrations.douyin_webhook import process_webhook_event
from app.main import create_app
from app.models import DouyinLead, DouyinWebhookEvent


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


def _content(
    *,
    text: str = "我的手机号是13812345678",
    message_type: str = "text",
    server_message_id: str = "msg_001",
    conversation_short_id: str = "conv_001",
) -> dict:
    return {
        "create_time": 1710000000000,
        "conversation_short_id": conversation_short_id,
        "server_message_id": server_message_id,
        "message_type": message_type,
        "text": text,
    }


def _payload(
    *,
    event: str = "im_receive_msg",
    from_user_id: str = "user_001",
    to_user_id: str = "account_001",
    content=None,
) -> dict:
    if content is None:
        content = _content()
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
    }


def _insert_event(
    *,
    event: str = "im_receive_msg",
    from_user_id: str = "user_001",
    to_user_id: str = "account_001",
    event_key: str = "event_key_001",
    lead_id: int | None = None,
    raw_payload: dict | None = None,
    is_duplicate: int = 0,
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        raw_payload = raw_payload or _payload(
            event=event,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )
        item = DouyinWebhookEvent(
            event=event,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            event_key=event_key,
            is_duplicate=is_duplicate,
            lead_id=lead_id,
            raw_body=json.dumps(raw_payload, ensure_ascii=False),
            created_at=created_at or datetime.now(),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def _insert_lead() -> int:
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="测试客户",
            customer_contact="13812345678",
            content="我的手机号是13812345678",
            source_id="lead_user_001",
            status="pending",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


def test_list_webhook_events_empty():
    client = _client()

    resp = client.get("/webhook-events")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"] == {"page": 1, "page_size": 20, "total": 0, "items": []}


def test_list_webhook_events_infers_valid_lead():
    lead_id = _insert_lead()
    event_id = _insert_event(lead_id=lead_id, event_key="valid_001")
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["id"] == event_id
    assert item["lead_action"] == "valid_lead"
    assert item["lead_id"] == lead_id
    assert item["contact_extract_status"] == "matched"
    assert item["customer_contact"] == "13812345678"


def test_list_webhook_events_infers_invalid_contact():
    _insert_event(
        event_key="invalid_contact_001",
        raw_payload=_payload(content=_content(text="你好，我想咨询一下")),
    )
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["lead_action"] == "invalid_contact"
    assert item["contact_extract_status"] == "not_matched"
    assert item["failure_reason"] == "contact_not_found"


def test_list_webhook_events_infers_non_lead_event():
    _insert_event(
        event="im_send_msg",
        event_key="send_001",
        raw_payload=_payload(event="im_send_msg"),
    )
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["lead_action"] == "non_lead_event"


def test_list_webhook_events_infers_invalid_content():
    _insert_event(
        event_key="bad_content_001",
        raw_payload=_payload(content="{bad json"),
    )
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["lead_action"] == "invalid_content"
    assert item["contact_extract_status"] == "parse_failed"
    assert item["failure_reason"] == "invalid_content"


def test_list_webhook_events_infers_non_text_message():
    _insert_event(
        event_key="image_001",
        raw_payload=_payload(content=_content(text="图片里有 13812345678", message_type="image")),
    )
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["lead_action"] == "non_text_message"
    assert item["contact_extract_status"] == "not_matched"
    assert item["failure_reason"] == "non_text_message"


def test_list_webhook_events_infers_duplicate_event():
    _insert_event(event_key="dup_001", is_duplicate=1)
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["lead_action"] == "duplicate_event"
    assert item["is_duplicate"] is True


def test_list_webhook_events_pagination():
    _insert_event(event_key="page_older", from_user_id="older", created_at=datetime.now() - timedelta(days=1))
    _insert_event(event_key="page_newer", from_user_id="newer")
    client = _client()

    data = client.get("/webhook-events?page=1&page_size=1").json()["data"]

    assert data["page"] == 1
    assert data["page_size"] == 1
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["event_key"] == "page_newer"


def test_list_webhook_events_filters_event():
    _insert_event(event_key="receive_001", event="im_receive_msg")
    _insert_event(event_key="send_002", event="im_send_msg", raw_payload=_payload(event="im_send_msg"))
    client = _client()

    items = client.get("/webhook-events?event=im_send_msg").json()["data"]["items"]

    assert [item["event_key"] for item in items] == ["send_002"]


def test_list_webhook_events_filters_lead_action():
    lead_id = _insert_lead()
    _insert_event(event_key="valid_filter", lead_id=lead_id)
    _insert_event(event_key="invalid_filter", raw_payload=_payload(content=_content(text="你好")))
    client = _client()

    items = client.get("/webhook-events?lead_action=invalid_contact").json()["data"]["items"]

    assert [item["event_key"] for item in items] == ["invalid_filter"]


def test_list_webhook_events_filters_is_duplicate():
    _insert_event(event_key="normal_filter", is_duplicate=0)
    _insert_event(event_key="dup_filter", is_duplicate=1)
    client = _client()

    items = client.get("/webhook-events?is_duplicate=true").json()["data"]["items"]

    assert [item["event_key"] for item in items] == ["dup_filter"]


def test_list_webhook_events_shows_real_duplicate_from_webhook_flow():
    payload = _payload(
        from_user_id="real_dup_user",
        content=_content(
            text="wx abc123",
            server_message_id="real_dup_msg",
            conversation_short_id="real_dup_conv",
        ),
    )
    db = TestSession()
    try:
        first = process_webhook_event(db, payload)
        db.commit()
        second = process_webhook_event(db, payload)
        db.commit()
    finally:
        db.close()

    assert first["lead_action"] == "created"
    assert second["lead_action"] == "duplicate_event"
    assert second["is_duplicate"] is True
    assert second["event_id"] != first["event_id"]
    assert second["lead_id"] == first["lead_id"]

    client = _client()

    duplicate_items = client.get("/webhook-events?lead_action=duplicate_event").json()["data"]["items"]
    assert [item["id"] for item in duplicate_items] == [second["event_id"]]
    assert duplicate_items[0]["is_duplicate"] is True

    duplicate_flag_items = client.get("/webhook-events?is_duplicate=true").json()["data"]["items"]
    assert [item["id"] for item in duplicate_flag_items] == [second["event_id"]]

    duplicate_detail = client.get(f"/webhook-events/{second['event_id']}").json()["data"]
    assert duplicate_detail["lead_action"] == "duplicate_event"
    assert duplicate_detail["raw_body"]["from_user_id"] == "real_dup_user"

    original_detail = client.get(f"/webhook-events/{first['event_id']}").json()["data"]
    assert original_detail["lead_action"] == "valid_lead"
    assert original_detail["is_duplicate"] is False


def test_list_webhook_events_filters_keyword_event_key_or_raw_body():
    _insert_event(event_key="keyword_key_001", from_user_id="plain")
    _insert_event(
        event_key="other_key_001",
        from_user_id="raw_user",
        raw_payload=_payload(from_user_id="raw_user", content=_content(text="包含特殊关键词")),
    )
    client = _client()

    key_items = client.get("/webhook-events?keyword=keyword_key").json()["data"]["items"]
    raw_items = client.get("/webhook-events?keyword=特殊关键词").json()["data"]["items"]

    assert [item["event_key"] for item in key_items] == ["keyword_key_001"]
    assert [item["event_key"] for item in raw_items] == ["other_key_001"]


def test_get_webhook_event_detail_exists():
    event_id = _insert_event(event_key="detail_001")
    client = _client()

    resp = client.get(f"/webhook-events/{event_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["id"] == event_id
    assert data["data"]["raw_body"]["event"] == "im_receive_msg"
    assert data["data"]["server_message_id"] == "msg_001"
    assert data["data"]["conversation_short_id"] == "conv_001"
    assert data["data"]["message_text"] == "我的手机号是13812345678"


def test_get_webhook_event_detail_404():
    client = _client()

    resp = client.get("/webhook-events/999")

    assert resp.status_code == 404


def test_get_webhook_event_detail_raw_body_parse_failure_not_500():
    db = TestSession()
    try:
        item = DouyinWebhookEvent(
            event="im_receive_msg",
            from_user_id="bad_raw",
            to_user_id="account",
            event_key="bad_raw_001",
            is_duplicate=0,
            lead_id=None,
            raw_body="{bad raw json",
            created_at=datetime.now(),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        event_id = item.id
    finally:
        db.close()

    client = _client()
    resp = client.get(f"/webhook-events/{event_id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["lead_action"] == "invalid_content"
    assert data["raw_body"] is None
    assert data["failure_reason"] == "invalid_raw_body"
