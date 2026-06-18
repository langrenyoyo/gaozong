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


def test_list_webhook_events_exposes_profile_summary_from_user_infos():
    _insert_event(
        event_key="profile_001",
        from_user_id="customer_open_001",
        to_user_id="account_open_001",
        raw_payload=_payload(
            from_user_id="customer_open_001",
            to_user_id="account_open_001",
            content={
                **_content(text="你好，先了解一下", conversation_short_id="profile_conv"),
                "user_infos": [
                    {
                        "open_id": "customer_open_001",
                        "nick_name": "抖音客户小赵",
                        "avatar": "https://example.com/customer.jpg",
                    },
                    {
                        "open_id": "account_open_001",
                        "nick_name": "老高企业号",
                        "avatar": "https://example.com/account.jpg",
                    },
                ],
            },
        ),
    )
    client = _client()

    item = client.get("/webhook-events").json()["data"]["items"][0]

    assert item["nick_name"] == "抖音客户小赵"
    assert item["avatar"] == "https://example.com/customer.jpg"
    assert item["from_user_nick_name"] == "抖音客户小赵"
    assert item["from_user_avatar"] == "https://example.com/customer.jpg"
    assert item["to_user_nick_name"] == "老高企业号"
    assert item["to_user_avatar"] == "https://example.com/account.jpg"


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


def test_list_webhook_events_filters_open_id_across_columns_body_and_content():
    target = "_0002ag2OYRK27wlUoJJb0yVG0CkU_Jn8Eib"
    _insert_event(event_key="match_from", from_user_id=target)
    _insert_event(event_key="match_to", to_user_id=target)
    _insert_event(
        event_key="match_body_open",
        from_user_id="body_open_user",
        raw_payload={
            **_payload(from_user_id="body_open_user"),
            "open_id": target,
        },
    )
    _insert_event(
        event_key="match_body_account",
        from_user_id="body_account_user",
        raw_payload={
            **_payload(from_user_id="body_account_user"),
            "account_open_id": target,
        },
    )
    _insert_event(
        event_key="match_content_open",
        from_user_id="content_open_user",
        raw_payload=_payload(
            from_user_id="content_open_user",
            content={**_content(server_message_id="content_open_msg"), "open_id": target},
        ),
    )
    _insert_event(
        event_key="match_content_account",
        from_user_id="content_account_user",
        raw_payload={
            **_payload(from_user_id="content_account_user"),
            "content": {**_content(server_message_id="content_account_msg"), "account_open_id": target},
        },
    )
    _insert_event(
        event_key="not_match_text_only",
        from_user_id="other_user",
        raw_payload=_payload(
            from_user_id="other_user",
            content=_content(text=f"文本里提到 {target}，但不是 open_id 字段", server_message_id="not_match_msg"),
        ),
    )
    client = _client()

    items = client.get(f"/webhook-events?open_id={target}&page_size=20").json()["data"]["items"]

    assert [item["event_key"] for item in items] == [
        "match_content_account",
        "match_content_open",
        "match_body_account",
        "match_body_open",
        "match_to",
        "match_from",
    ]
    by_key = {item["event_key"]: item for item in items}
    assert by_key["match_body_open"]["body_open_id"] == target
    assert by_key["match_body_account"]["body_account_open_id"] == target
    assert by_key["match_content_open"]["content_open_id"] == target
    assert by_key["match_content_account"]["content_account_open_id"] == target


def test_list_webhook_events_filters_conversation_short_id():
    _insert_event(
        event_key="conv_match_receive",
        raw_payload=_payload(
            event="im_receive_msg",
            content=_content(
                text="wx convmatch",
                server_message_id="conv_match_msg_1",
                conversation_short_id="conv_target",
            ),
        ),
        created_at=datetime.now() - timedelta(minutes=2),
    )
    _insert_event(
        event="im_send_msg",
        event_key="conv_match_send",
        raw_payload=_payload(
            event="im_send_msg",
            content=_content(
                text="您好，已收到",
                server_message_id="conv_match_msg_2",
                conversation_short_id="conv_target",
            ),
        ),
        created_at=datetime.now() - timedelta(minutes=1),
    )
    _insert_event(
        event_key="conv_other",
        raw_payload=_payload(
            content=_content(
                text="wx other",
                server_message_id="conv_other_msg",
                conversation_short_id="conv_other",
            ),
        ),
    )
    client = _client()

    data = client.get("/webhook-events?conversation_short_id=conv_target&page_size=20").json()["data"]

    assert data["total"] == 2
    assert [item["event_key"] for item in data["items"]] == ["conv_match_send", "conv_match_receive"]
    assert {item["conversation_short_id"] for item in data["items"]} == {"conv_target"}


def test_list_webhook_events_filters_lead_id():
    lead_id = _insert_lead()
    _insert_event(event_key="lead_match", lead_id=lead_id)
    _insert_event(event_key="lead_none", lead_id=None)
    _insert_event(event_key="lead_other", lead_id=lead_id + 1)
    client = _client()

    data = client.get(f"/webhook-events?lead_id={lead_id}&page_size=20").json()["data"]

    assert data["total"] == 1
    assert data["items"][0]["event_key"] == "lead_match"
    assert data["items"][0]["lead_id"] == lead_id


def test_list_webhook_events_filters_conversation_empty_result():
    _insert_event(event_key="conv_existing")
    client = _client()

    data = client.get("/webhook-events?conversation_short_id=missing_conv&page_size=20").json()["data"]

    assert data == {"page": 1, "page_size": 20, "total": 0, "items": []}


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


def test_process_webhook_event_persists_normalized_fields_from_json_string_content():
    payload = _payload(
        from_user_id="customer_norm_001",
        to_user_id="account_norm_001",
        content={
            **_content(
                text="wx norm001",
                server_message_id="server_norm_001",
                conversation_short_id="conv_norm_001",
            ),
            "conversation_type": 1,
            "source": "aweme",
            "user_infos": [
                {
                    "open_id": "customer_norm_001",
                    "nick_name": "Customer Norm",
                    "avatar": "https://example.com/customer_norm.png",
                },
                {
                    "open_id": "account_norm_001",
                    "nick_name": "Account Norm",
                    "avatar": "https://example.com/account_norm.png",
                },
            ],
        },
    )
    db = TestSession()
    try:
        result = process_webhook_event(db, payload)
        db.commit()
        event = db.query(DouyinWebhookEvent).filter_by(id=result["event_id"]).first()

        assert event is not None
        assert event.client_key is None
        assert event.conversation_short_id == "conv_norm_001"
        assert event.server_message_id == "server_norm_001"
        assert event.conversation_type == "1"
        assert event.message_type == "text"
        assert event.message_source == "aweme"
        assert event.parse_status == "parsed"
        assert event.parse_error is None
        assert event.from_user_nick_name == "Customer Norm"
        assert event.from_user_avatar == "https://example.com/customer_norm.png"
        assert event.to_user_nick_name == "Account Norm"
        assert event.to_user_avatar == "https://example.com/account_norm.png"
        assert int(event.message_create_time.timestamp() * 1000) == 1710000000000
        assert json.loads(event.parsed_content_json)["server_message_id"] == "server_norm_001"
        assert json.loads(event.raw_body)["content"]
    finally:
        db.close()


def test_process_webhook_event_persists_normalized_fields_from_dict_content():
    payload = {
        "event": "im_send_msg",
        "from_user_id": "account_dict_001",
        "to_user_id": "customer_dict_001",
        "client_key": "client_dict_001",
        "content": {
            **_content(
                text="已收到",
                server_message_id="server_dict_001",
                conversation_short_id="conv_dict_001",
            ),
            "conversation_type": 1,
            "source": "staff_console",
            "user_infos": [
                {"open_id": "account_dict_001", "nick_name": "Account Dict"},
                {"open_id": "customer_dict_001", "nick_name": "Customer Dict"},
            ],
        },
    }
    db = TestSession()
    try:
        result = process_webhook_event(db, payload)
        db.commit()
        event = db.query(DouyinWebhookEvent).filter_by(id=result["event_id"]).first()

        assert event is not None
        assert event.client_key == "client_dict_001"
        assert event.conversation_short_id == "conv_dict_001"
        assert event.server_message_id == "server_dict_001"
        assert event.conversation_type == "1"
        assert event.message_type == "text"
        assert event.message_source == "staff_console"
        assert event.parse_status == "parsed"
        assert event.from_user_nick_name == "Account Dict"
        assert event.to_user_nick_name == "Customer Dict"
    finally:
        db.close()


def test_process_webhook_event_invalid_content_keeps_raw_event_and_marks_parse_failed():
    payload = _payload(
        from_user_id="customer_bad_content",
        to_user_id="account_bad_content",
        content="{bad json",
    )
    db = TestSession()
    try:
        result = process_webhook_event(db, payload)
        db.commit()
        event = db.query(DouyinWebhookEvent).filter_by(id=result["event_id"]).first()

        assert event is not None
        assert event.raw_body
        assert event.parse_status == "parse_failed"
        assert event.parse_error == "invalid_content_json"
        assert event.parsed_content_json == "{}"
        assert event.conversation_short_id is None
        assert event.server_message_id is None
    finally:
        db.close()


def test_duplicate_server_message_id_does_not_create_second_normalized_message():
    payload = _payload(
        from_user_id="customer_dup_norm",
        to_user_id="account_dup_norm",
        content=_content(
            text="wx dupnorm",
            server_message_id="server_dup_norm",
            conversation_short_id="conv_dup_norm",
        ),
    )
    db = TestSession()
    try:
        first = process_webhook_event(db, payload)
        db.commit()
        second = process_webhook_event(db, payload)
        db.commit()

        assert second["is_duplicate"] is True
        normalized_rows = (
            db.query(DouyinWebhookEvent)
            .filter(
                DouyinWebhookEvent.server_message_id == "server_dup_norm",
                DouyinWebhookEvent.is_duplicate == 0,
            )
            .all()
        )
        assert [item.id for item in normalized_rows] == [first["event_id"]]
    finally:
        db.close()


def test_get_send_msg_context_returns_latest_non_duplicate_context():
    from app.services.douyin_workbench_conversation_service import get_send_msg_context

    db = TestSession()
    try:
        process_webhook_event(
            db,
            _payload(
                from_user_id="customer_ctx",
                to_user_id="account_ctx",
                content=_content(
                    text="wx ctx",
                    server_message_id="server_ctx_older",
                    conversation_short_id="conv_ctx",
                ),
            ),
        )
        db.commit()
        process_webhook_event(
            db,
            {
                "event": "im_enter_direct_msg",
                "from_user_id": "customer_ctx",
                "to_user_id": "account_ctx",
                "content": {
                    **_content(
                        text="",
                        server_message_id="server_ctx_latest",
                        conversation_short_id="conv_ctx",
                    ),
                    "conversation_type": 1,
                    "source": "enter_direct",
                },
            },
        )
        db.commit()

        context = get_send_msg_context(db, conversation_short_id="conv_ctx", customer_open_id="customer_ctx")

        assert context == {
            "conversation_id": "conv_ctx",
            "conversation_short_id": "conv_ctx",
            "msg_id": "server_ctx_latest",
            "server_message_id": "server_ctx_latest",
            "from_user_id": "customer_ctx",
            "to_user_id": "account_ctx",
            "customer_open_id": "customer_ctx",
            "account_open_id": "account_ctx",
            "scene": "im_enter_direct_msg",
        }
    finally:
        db.close()
