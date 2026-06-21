"""AI 自动发送 im_send_msg 回调识别测试。"""

import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinPrivateMessageSend, DouyinWebhookEvent


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _insert_send_record(
    *,
    send_source: str = "ai_auto",
    upstream_msg_id: str | None = "upstream-msg-1",
    account_open_id: str = "account-open-1",
    customer_open_id: str = "customer-open-1",
    conversation_short_id: str = "conv-1",
    content: str = "hello customer",
    sent_at: datetime | None = None,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinPrivateMessageSend(
                main_account_id=123,
                conversation_short_id=conversation_short_id,
                server_message_id="trigger-msg-1",
                from_user_id=account_open_id,
                to_user_id=customer_open_id,
                customer_open_id=customer_open_id,
                account_open_id=account_open_id,
                scene="im_reply_msg",
                content=content,
                status="sent",
                upstream_msg_id=upstream_msg_id,
                manual_confirmed=0 if send_source == "ai_auto" else 1,
                auto_send=1 if send_source == "ai_auto" else 0,
                send_source=send_source,
                sent_at=sent_at or datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()


def _event(
    *,
    event: str = "im_send_msg",
    server_message_id: str = "upstream-msg-1",
    account_open_id: str = "account-open-1",
    customer_open_id: str = "customer-open-1",
    conversation_short_id: str = "conv-1",
    content: str = "hello customer",
    message_create_time: datetime | None = None,
) -> DouyinWebhookEvent:
    payload_content = {
        "conversation_short_id": conversation_short_id,
        "server_message_id": server_message_id,
        "message_type": "text",
        "text": content,
    }
    from_user_id = account_open_id if event == "im_send_msg" else customer_open_id
    to_user_id = customer_open_id if event == "im_send_msg" else account_open_id
    return DouyinWebhookEvent(
        event=event,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        conversation_short_id=conversation_short_id,
        server_message_id=server_message_id,
        message_type="text",
        message_create_time=message_create_time or datetime.now(),
        parsed_content_json=json.dumps(payload_content, ensure_ascii=False),
        raw_body=json.dumps(
            {
                "event": event,
                "from_user_id": from_user_id,
                "to_user_id": to_user_id,
                "content": payload_content,
            },
            ensure_ascii=False,
        ),
    )


def test_upstream_msg_id_exact_match_returns_true():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    _insert_send_record(upstream_msg_id="upstream-msg-1")
    db = TestSession()
    try:
        assert is_ai_auto_sent_message_event(db, event=_event(server_message_id="upstream-msg-1")) is True
    finally:
        db.close()


def test_manual_send_source_returns_false_even_when_message_id_matches():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    _insert_send_record(send_source="manual", upstream_msg_id="upstream-msg-1")
    db = TestSession()
    try:
        assert is_ai_auto_sent_message_event(db, event=_event(server_message_id="upstream-msg-1")) is False
    finally:
        db.close()


def test_non_im_send_msg_returns_false():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    _insert_send_record(upstream_msg_id="upstream-msg-1")
    db = TestSession()
    try:
        assert is_ai_auto_sent_message_event(db, event=_event(event="im_receive_msg")) is False
    finally:
        db.close()


def test_fallback_full_match_returns_true_when_upstream_id_is_different():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    sent_at = datetime.now()
    _insert_send_record(upstream_msg_id="upstream-msg-from-send-api", sent_at=sent_at)
    db = TestSession()
    try:
        event = _event(server_message_id="callback-msg-1", message_create_time=sent_at + timedelta(minutes=2))
        assert is_ai_auto_sent_message_event(db, event=event) is True
    finally:
        db.close()


def test_fallback_time_window_outside_returns_false():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    sent_at = datetime.now()
    _insert_send_record(upstream_msg_id="upstream-msg-from-send-api", sent_at=sent_at)
    db = TestSession()
    try:
        event = _event(server_message_id="callback-msg-1", message_create_time=sent_at + timedelta(minutes=6))
        assert is_ai_auto_sent_message_event(db, event=event) is False
    finally:
        db.close()


def test_fallback_content_mismatch_returns_false():
    from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event

    sent_at = datetime.now()
    _insert_send_record(upstream_msg_id="upstream-msg-from-send-api", content="hello customer", sent_at=sent_at)
    db = TestSession()
    try:
        event = _event(
            server_message_id="callback-msg-1",
            content="different content",
            message_create_time=sent_at,
        )
        assert is_ai_auto_sent_message_event(db, event=event) is False
    finally:
        db.close()
