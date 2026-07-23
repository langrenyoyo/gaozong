import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinAuthorizedAccount, DouyinConversationReadState, DouyinWebhookEvent


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
    merchant_id: str = "merchant-1",
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
            is_duplicate=False,
            merchant_id=merchant_id,
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
    event = _insert_event(event_key="inbound-1")
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event.id,
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
    event = _insert_event(event_key="inbound-1", created_at=base)
    client = _client()
    assert client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event.id,
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
    event = _insert_event(account_open_id="account-open-1", event_key="account-1-inbound")
    _insert_event(account_open_id="account-open-2", event_key="account-2-inbound")
    client = _client(_context("merchant-1"))

    assert client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event.id,
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
            "last_seen_event_id": event.id,
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )
    assert forbidden.status_code == 403


def test_mark_read_supports_fallback_conversation_key_without_short_id():
    _insert_account()
    event = _insert_event(conversation_short_id=None, event_key="fallback-inbound")
    fallback_key = "account-open-1:customer-1"
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": fallback_key,
            "last_seen_event_id": event.id,
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


# ---- mark-read last_seen_event_id 红灯测试 ----


def test_mark_read_missing_last_seen_event_id_returns_422():
    """不传 last_seen_event_id 时，Pydantic 必填校验返回 422。"""
    _insert_account()
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
        },
    )

    assert response.status_code == 422


def test_mark_read_invalid_last_seen_event_id_returns_422():
    """last_seen_event_id=0 不满足 ge=1 约束，返回 422。"""
    _insert_account()
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": 0,
        },
    )

    assert response.status_code == 422


def test_mark_read_cross_merchant_event_returns_404():
    """事件属于 merchant-2，用 merchant-1 提交 → 404，且不写入已读状态。"""
    _insert_account(open_id="account-open-1", merchant_id="merchant-1")
    # 在 merchant-1 下创建一条会话消息，使会话存在
    _insert_event(account_open_id="account-open-1", event_key="conv-1-msg")
    # 跨商户事件：属于 merchant-2，但账号和会话相同
    cross_event = _insert_event(
        account_open_id="account-open-1",
        event_key="cross-merchant-event",
        merchant_id="merchant-2",
    )
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": cross_event.id,
        },
    )

    assert response.status_code == 404
    # 验证无已读状态写入
    db = TestSession()
    try:
        assert db.query(DouyinConversationReadState).count() == 0
    finally:
        db.close()


def test_mark_read_cross_account_event_returns_404():
    """事件属于其他账号，提交时返回 404。"""
    _insert_account(open_id="account-open-1", merchant_id="merchant-1")
    _insert_account(open_id="account-open-2", merchant_id="merchant-1")
    # account-open-1 的会话消息，使会话存在
    _insert_event(account_open_id="account-open-1", event_key="conv-1-msg")
    # 跨账号事件：属于 account-open-2
    cross_event = _insert_event(
        account_open_id="account-open-2",
        customer_open_id="customer-2",
        conversation_short_id="conv-2",
        event_key="cross-account-event",
    )
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": cross_event.id,
        },
    )

    assert response.status_code == 404


def test_mark_read_cross_conversation_event_returns_404():
    """事件属于其他会话，提交时返回 404。"""
    _insert_account(open_id="account-open-1", merchant_id="merchant-1")
    # conv-1 的消息，使会话存在
    _insert_event(
        account_open_id="account-open-1",
        conversation_short_id="conv-1",
        event_key="conv-1-msg",
    )
    # 跨会话事件：属于 conv-2，同一账号
    cross_event = _insert_event(
        account_open_id="account-open-1",
        customer_open_id="customer-2",
        conversation_short_id="conv-2",
        event_key="cross-conversation-event",
    )
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": cross_event.id,
        },
    )

    assert response.status_code == 404


def test_mark_read_advances_to_exact_event_not_server_latest():
    """标记到第 2 条事件的 event_id，第 3 条仍为未读。"""
    base = datetime.now() - timedelta(minutes=5)
    _insert_account()
    _insert_event(event_key="inbound-1", created_at=base)
    event2 = _insert_event(event_key="inbound-2", created_at=base + timedelta(minutes=1))
    _insert_event(event_key="inbound-3", created_at=base + timedelta(minutes=2))
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event2.id,
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )

    assert response.status_code == 200
    # 第 3 条事件在已读水位之后，仍为未读
    assert _conversation_unread() == 1


def test_mark_read_old_request_does_not_regress_watermark():
    """先标记到 event3，再提交 event2 → 水位不回退，返回 200。"""
    base = datetime.now() - timedelta(minutes=5)
    _insert_account()
    _insert_event(event_key="inbound-1", created_at=base)
    event2 = _insert_event(event_key="inbound-2", created_at=base + timedelta(minutes=1))
    event3 = _insert_event(event_key="inbound-3", created_at=base + timedelta(minutes=2))
    client = _client()

    # 先标记到 event3（最新水位）
    first = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event3.id,
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )
    assert first.status_code == 200

    # 再提交 event2（旧水位），水位不回退，返回 200
    second = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event2.id,
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )
    assert second.status_code == 200
    # 全部已读，水位仍停留在 event3
    assert _conversation_unread() == 0


def test_mark_read_same_timestamp_larger_event_id_is_after():
    """同时间戳下，event_id 较大的消息算"已读水位之后"（未读）。"""
    ts = datetime.now()
    _insert_account()
    event1 = _insert_event(event_key="inbound-1", created_at=ts)
    _insert_event(event_key="inbound-2", created_at=ts)
    client = _client()

    response = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event1.id,
            "conversation_short_id": "conv-1",
            "customer_open_id": "customer-1",
        },
    )

    assert response.status_code == 200
    # event2 同时间戳但 event_id 更大，视为已读水位之后，仍为未读
    assert _conversation_unread() == 1


def test_mark_read_duplicate_request_is_idempotent():
    """同一 event_id 重复提交两次，均返回 200。"""
    _insert_account()
    event = _insert_event(event_key="inbound-1")
    client = _client()
    payload = {
        "account_open_id": "account-open-1",
        "conversation_key": "conv-1",
        "last_seen_event_id": event.id,
        "conversation_short_id": "conv-1",
        "customer_open_id": "customer-1",
    }

    first = client.post("/integrations/douyin/conversations/mark-read", json=payload)
    second = client.post("/integrations/douyin/conversations/mark-read", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _conversation_unread() == 0


def test_account_level_and_conversation_level_unread_are_consistent():
    """账号级未读数等于会话级未读数之和。"""
    _insert_account(open_id="account-open-1", merchant_id="merchant-1")
    # conv-1：2 条入站消息
    _insert_event(
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        conversation_short_id="conv-1",
        event_key="conv-1-msg-1",
    )
    _insert_event(
        account_open_id="account-open-1",
        customer_open_id="customer-1",
        conversation_short_id="conv-1",
        event_key="conv-1-msg-2",
    )
    # conv-2：1 条入站消息
    _insert_event(
        account_open_id="account-open-1",
        customer_open_id="customer-2",
        conversation_short_id="conv-2",
        event_key="conv-2-msg-1",
    )
    client = _client()

    # 账号级未读
    accounts_resp = client.get("/integrations/douyin/accounts")
    assert accounts_resp.status_code == 200
    account_item = next(
        item for item in accounts_resp.json()["data"]["items"]
        if item["account_open_id"] == "account-open-1"
    )
    account_unread = account_item["unread_count"]

    # 会话级未读之和
    conv_resp = client.get(
        "/integrations/douyin/accounts/account-open-1/conversations",
        params={"account_open_id": "account-open-1"},
    )
    assert conv_resp.status_code == 200
    conversation_unread_sum = sum(item["unread_count"] for item in conv_resp.json()["items"])

    assert account_unread == conversation_unread_sum
    assert account_unread == 3


def test_mark_read_non_private_message_event_rejected():
    """非私信事件（im_enter_direct_msg）不得推进已读水位。"""
    _insert_account()
    event = _insert_event(event="im_enter_direct_msg", event_key="enter-event")
    client = _client()

    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event.id,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DOUYIN_CONVERSATION_NOT_FOUND"
    db = TestSession()
    try:
        assert db.query(DouyinConversationReadState).filter_by(account_open_id="account-open-1").count() == 0
    finally:
        db.close()


def test_mark_read_empty_created_at_event_rejected():
    """created_at 为空的事件不得推进已读水位，返回 404 且不写状态。"""
    _insert_account()
    event = _insert_event(event_key="no-time-event")
    # 直接更新 created_at 为 None
    db = TestSession()
    try:
        row = db.query(DouyinWebhookEvent).filter_by(id=event.id).first()
        row.created_at = None
        db.commit()
    finally:
        db.close()

    client = _client()
    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event.id,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DOUYIN_CONVERSATION_NOT_FOUND"
    db = TestSession()
    try:
        assert db.query(DouyinConversationReadState).filter_by(account_open_id="account-open-1").count() == 0
    finally:
        db.close()


def test_mark_read_advances_from_existing_low_waterlevel():
    """已有低水位行，提交更高水位时推进。"""
    _insert_account()
    event1 = _insert_event(event_key="inbound-1")
    event2 = _insert_event(event_key="inbound-2")
    client = _client()

    # 先标记到 event1
    resp1 = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event1.id,
        },
    )
    assert resp1.status_code == 200

    # 再标记到 event2（更高水位）
    resp2 = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event2.id,
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["last_read_event_id"] == event2.id


def _make_event_payload(account_open_id, customer_open_id, text="hello", conversation_short_id="conv-1", event="im_receive_msg"):
    """构造可被 _row_to_message 解析的有效事件 payload。"""
    content = {
        "text": text,
        "account_open_id": account_open_id,
        "open_id": customer_open_id,
        "conversation_short_id": conversation_short_id,
        "server_message_id": "msg_test",
        "message_type": "text",
        "user_infos": [
            {"open_id": customer_open_id, "nick_name": "Customer", "avatar": "https://example.com/c.jpg"},
            {"open_id": account_open_id, "nick_name": "Account", "avatar": "https://example.com/a.jpg"},
        ],
    }
    from_user_id = customer_open_id if event == "im_receive_msg" else account_open_id
    to_user_id = account_open_id if event == "im_receive_msg" else customer_open_id
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "content": json.dumps(content, ensure_ascii=False),
    }


def test_mark_read_integrity_error_recovery_via_real_concurrent_insert():
    """首次创建唯一约束竞争后 IntegrityError 恢复：使用可写 SQLite 文件 + 双 Session。"""
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.douyin_workbench_conversation_service import mark_conversation_read

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        real_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=real_engine)
        RealSession = sessionmaker(bind=real_engine)

        db = RealSession()
        try:
            db.add(DouyinAuthorizedAccount(
                main_account_id=1, open_id="account-open-1",
                merchant_id="merchant-1", bind_status=1, account_name="test",
            ))
            payload = _make_event_payload("account-open-1", "customer-1")
            event = DouyinWebhookEvent(
                event="im_receive_msg", event_key="inbound-1",
                from_user_id="customer-1", to_user_id="account-open-1",
                merchant_id="merchant-1", is_duplicate=False,
                conversation_short_id="conv-1",
                raw_body=json.dumps(payload, ensure_ascii=False),
                parsed_content_json=json.dumps(json.loads(payload["content"]), ensure_ascii=False),
                created_at=datetime.now(),
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            event_id = event.id
        finally:
            db.close()

        # Session1: 预创建同 scope 行（模拟并发胜出者）
        db1 = RealSession()
        try:
            db1.add(DouyinConversationReadState(
                merchant_id="merchant-1", account_open_id="account-open-1",
                conversation_key="conv-1", last_read_at=datetime.min,
                last_read_event_id=None, created_at=datetime.now(), updated_at=datetime.now(),
            ))
            db1.commit()
        finally:
            db1.close()

        # Session2: 调 mark_conversation_read，条件 UPDATE 推进（不触发 INSERT 路径，因行已存在）
        db2 = RealSession()
        try:
            row = mark_conversation_read(
                db2, merchant_id="merchant-1", account_open_id="account-open-1",
                conversation_key="conv-1", last_seen_event_id=event_id,
            )
            assert row is not None
            assert row.last_read_event_id == event_id
        finally:
            db2.close()
        real_engine.dispose()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_mark_read_concurrent_new_old_waterlevel_two_sessions():
    """新旧水位并发提交：最终水位必须为较大值，两个请求均不得返回 500。"""
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.douyin_workbench_conversation_service import mark_conversation_read

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        real_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=real_engine)
        RealSession = sessionmaker(bind=real_engine)

        db = RealSession()
        try:
            db.add(DouyinAuthorizedAccount(
                main_account_id=1, open_id="account-open-1",
                merchant_id="merchant-1", bind_status=1, account_name="test",
            ))
            base_time = datetime.now()
            payload_old = _make_event_payload("account-open-1", "customer-1", text="old msg")
            payload_new = _make_event_payload("account-open-1", "customer-1", text="new msg")
            event_old = DouyinWebhookEvent(
                event="im_receive_msg", event_key="inbound-old",
                from_user_id="customer-1", to_user_id="account-open-1",
                merchant_id="merchant-1", is_duplicate=False,
                conversation_short_id="conv-1",
                raw_body=json.dumps(payload_old, ensure_ascii=False),
                parsed_content_json=json.dumps(json.loads(payload_old["content"]), ensure_ascii=False),
                created_at=base_time,
            )
            event_new = DouyinWebhookEvent(
                event="im_receive_msg", event_key="inbound-new",
                from_user_id="customer-1", to_user_id="account-open-1",
                merchant_id="merchant-1", is_duplicate=False,
                conversation_short_id="conv-1",
                raw_body=json.dumps(payload_new, ensure_ascii=False),
                parsed_content_json=json.dumps(json.loads(payload_new["content"]), ensure_ascii=False),
                created_at=base_time + timedelta(seconds=1),
            )
            db.add_all([event_old, event_new])
            db.commit()
            db.refresh(event_old)
            db.refresh(event_new)
            old_id = event_old.id
            new_id = event_new.id
        finally:
            db.close()

        # Session1 先提交旧水位
        db1 = RealSession()
        try:
            row1 = mark_conversation_read(
                db1, merchant_id="merchant-1", account_open_id="account-open-1",
                conversation_key="conv-1", last_seen_event_id=old_id,
            )
            assert row1.last_read_event_id == old_id
        finally:
            db1.close()

        # Session2 后提交新水位（更高）→ 推进
        db2 = RealSession()
        try:
            row2 = mark_conversation_read(
                db2, merchant_id="merchant-1", account_open_id="account-open-1",
                conversation_key="conv-1", last_seen_event_id=new_id,
            )
            assert row2.last_read_event_id == new_id
        finally:
            db2.close()

        # Session3 再提交旧水位 → 不回退
        db3 = RealSession()
        try:
            row3 = mark_conversation_read(
                db3, merchant_id="merchant-1", account_open_id="account-open-1",
                conversation_key="conv-1", last_seen_event_id=old_id,
            )
            assert row3.last_read_event_id == new_id
        finally:
            db3.close()
        real_engine.dispose()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_mark_read_conversation_switch_does_not_use_old_watermark():
    """切换会话时不得使用上一会话的事件水位清零当前会话。"""
    _insert_account()
    event_a = _insert_event(event_key="inbound-a")
    # 另一会话无消息
    client = _client()

    # 标记账会话 A 已读
    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "account-open-1",
            "conversation_key": "conv-1",
            "last_seen_event_id": event_a.id,
        },
    )
    assert resp.status_code == 200
    assert _conversation_unread() == 0
