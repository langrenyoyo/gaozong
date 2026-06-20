"""抖音 AI 自动回复真实发送服务测试。"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AiAutoReplyRun,
    ConversationAutopilotState,
    DouyinAccountAutoreplySetting,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _insert_settings(*, send_enabled: bool = True) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                enabled=True,
                dry_run_enabled=True,
                send_enabled=send_enabled,
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_run(
    *,
    status: str = "decided",
    content: str | None = "您好，可以介绍一下您的预算和关注车型。",
    trigger_server_message_id: str = "server-msg-1",
    decision_log_id: int | None = 101,
) -> int:
    db = TestSession()
    try:
        run = AiAutoReplyRun(
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-open-1",
            trigger_event_id=1,
            trigger_event_key="event-key-1",
            trigger_server_message_id=trigger_server_message_id,
            latest_message="想了解 A6",
            agent_id="agent-1",
            mode="dry_run",
            status=status,
            decision_log_id=decision_log_id,
            would_send_content=content,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _insert_event(
    *,
    event: str = "im_receive_msg",
    server_message_id: str = "server-msg-1",
    created_at: datetime | None = None,
    message_create_time: datetime | None = None,
    event_key: str | None = None,
) -> None:
    db = TestSession()
    try:
        from_user_id = "customer-open-1" if event == "im_receive_msg" else "account-open-1"
        to_user_id = "account-open-1" if event == "im_receive_msg" else "customer-open-1"
        content = {
            "conversation_short_id": "conv-1",
            "server_message_id": server_message_id,
            "message_type": "text",
            "text": "想了解 A6",
        }
        db.add(
            DouyinWebhookEvent(
                event=event,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                conversation_short_id="conv-1",
                server_message_id=server_message_id,
                message_type="text",
                parsed_content_json=json.dumps(content, ensure_ascii=False),
                event_key=event_key or f"event-{server_message_id}-{event}",
                is_duplicate=0,
                raw_body=json.dumps(
                    {
                        "event": event,
                        "from_user_id": from_user_id,
                        "to_user_id": to_user_id,
                        "content": content,
                    },
                    ensure_ascii=False,
                ),
                created_at=created_at or datetime.now(),
                message_create_time=message_create_time or created_at or datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_manual_takeover() -> None:
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                customer_open_id="customer-open-1",
                mode="manual",
            )
        )
        db.commit()
    finally:
        db.close()


def _get_run(run_id: int) -> AiAutoReplyRun:
    db = TestSession()
    try:
        return db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).one()
    finally:
        db.close()


def _send(run_id: int):
    from app.services.ai_auto_reply_send_service import send_ai_auto_reply_for_run

    db = TestSession()
    try:
        return send_ai_auto_reply_for_run(db, run_id=run_id)
    finally:
        db.close()


def test_send_enabled_false_does_not_send():
    run_id = _insert_run()
    _insert_settings(send_enabled=False)
    _insert_event()

    with patch("app.services.douyin_private_message_send_service.call_douyin_openapi") as openapi_mock:
        result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "send_disabled"
    assert _get_run(run_id).status == "send_skipped"
    openapi_mock.assert_not_called()


def test_non_decided_run_does_not_send():
    run_id = _insert_run(status="blocked")
    _insert_settings()
    _insert_event()

    result = _send(run_id)

    assert result["status"] == "skipped"
    assert result["reason"] == "run_not_decided"


def test_empty_content_is_send_skipped():
    run_id = _insert_run(content="   ")
    _insert_settings()
    _insert_event()

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "empty_content"
    assert _get_run(run_id).status == "send_skipped"


def test_manual_takeover_is_send_skipped():
    run_id = _insert_run()
    _insert_settings()
    _insert_event()
    _insert_manual_takeover()

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "manual_takeover"


def test_latest_message_not_customer_is_send_skipped():
    run_id = _insert_run()
    _insert_settings()

    with patch(
        "app.services.ai_auto_reply_send_service.get_latest_private_message_state",
        return_value={
            "latest_is_customer_message": False,
            "latest_server_message_id": "server-msg-1",
            "has_outbound_after_trigger": False,
        },
    ):
        result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "latest_message_not_customer"


def test_latest_server_message_id_mismatch_is_send_skipped():
    run_id = _insert_run(trigger_server_message_id="server-msg-old")
    _insert_settings()
    _insert_event(server_message_id="server-msg-new")

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "latest_message_changed"


def test_outbound_after_trigger_is_send_skipped():
    base_time = datetime.now() - timedelta(minutes=3)
    run_id = _insert_run()
    _insert_settings()
    _insert_event(server_message_id="server-msg-1", created_at=base_time)
    _insert_event(event="im_send_msg", server_message_id="server-msg-2", created_at=base_time + timedelta(minutes=1))
    _insert_event(
        server_message_id="server-msg-1",
        created_at=base_time + timedelta(minutes=2),
        event_key="event-server-msg-1-latest-repeat",
    )

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "outbound_after_trigger"


def test_send_context_unavailable_is_send_skipped():
    run_id = _insert_run()
    _insert_settings()

    with patch(
        "app.services.ai_auto_reply_send_service.get_latest_private_message_state",
        return_value={
            "latest_is_customer_message": True,
            "latest_server_message_id": "server-msg-1",
            "has_outbound_after_trigger": False,
        },
    ):
        result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "send_context_unavailable"


def test_send_context_message_id_mismatch_is_send_skipped():
    run_id = _insert_run(trigger_server_message_id="server-msg-1")
    _insert_settings()
    _insert_event(server_message_id="server-msg-2")

    with patch(
        "app.services.ai_auto_reply_send_service.get_latest_private_message_state",
        return_value={
            "latest_is_customer_message": True,
            "latest_server_message_id": "server-msg-1",
            "has_outbound_after_trigger": False,
        },
    ):
        result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "send_context_message_changed"


def test_expired_context_is_send_skipped():
    run_id = _insert_run()
    _insert_settings()
    _insert_event(message_create_time=datetime.now() - timedelta(hours=25))

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "context_expired"


def test_openapi_success_marks_sent_and_writes_ai_auto_send_record():
    run_id = _insert_run(decision_log_id=202)
    _insert_settings()
    _insert_event()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"code": 0, "data": {"msg_id": "upstream-msg-1"}}},
    ):
        result = _send(run_id)

    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).one()
        record = db.query(DouyinPrivateMessageSend).one()
        state = db.query(ConversationAutopilotState).one()
        assert result["status"] == "sent"
        assert run.status == "sent"
        assert record.manual_confirmed == 0
        assert record.auto_send == 1
        assert record.send_source == "ai_auto"
        assert record.auto_reply_run_id == run_id
        assert record.decision_log_id == 202
        assert state.last_ai_reply_at is not None
        assert state.mode == "ai"
    finally:
        db.close()


def test_openapi_failure_marks_send_failed_without_retry():
    run_id = _insert_run()
    _insert_settings()
    _insert_event()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        side_effect=HTTPException(status_code=502, detail={"upstream_code": "500", "upstream_msg": "failed"}),
    ) as openapi_mock:
        result = _send(run_id)

    assert result["status"] == "send_failed"
    assert _get_run(run_id).status == "send_failed"
    assert openapi_mock.call_count == 1


def test_existing_send_record_is_send_skipped_without_duplicate_send():
    run_id = _insert_run()
    _insert_settings()
    _insert_event()
    db = TestSession()
    try:
        db.add(
            DouyinPrivateMessageSend(
                main_account_id=123,
                conversation_short_id="conv-1",
                server_message_id="server-msg-1",
                from_user_id="account-open-1",
                to_user_id="customer-open-1",
                content="已发过",
                scene="im_reply_msg",
                status="sent",
                manual_confirmed=0,
                auto_send=1,
                send_source="ai_auto",
                auto_reply_run_id=run_id,
            )
        )
        db.commit()
    finally:
        db.close()

    with patch("app.services.douyin_private_message_send_service.call_douyin_openapi") as openapi_mock:
        result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == "already_sent"
    openapi_mock.assert_not_called()


def test_auto_send_service_does_not_call_manual_send_entry():
    run_id = _insert_run()
    _insert_settings()
    _insert_event()

    with patch("app.services.douyin_private_message_send_service.send_manual_private_message") as manual_mock, \
         patch(
             "app.services.douyin_private_message_send_service.call_douyin_openapi",
             return_value={"payload": {"code": 0, "data": {"msg_id": "upstream-msg-1"}}},
         ):
        _send(run_id)

    manual_mock.assert_not_called()


def test_run_missing_returns_skipped():
    result = _send(999)

    assert result["status"] == "skipped"
    assert result["reason"] == "run_not_found"


@pytest.mark.parametrize("enabled,dry_run_enabled,reason", [(False, True, "autoreply_disabled"), (True, False, "dry_run_disabled")])
def test_disabled_settings_are_send_skipped(enabled, dry_run_enabled, reason):
    run_id = _insert_run()
    _insert_event()
    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                enabled=enabled,
                dry_run_enabled=dry_run_enabled,
                send_enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()

    result = _send(run_id)

    assert result["status"] == "send_skipped"
    assert result["reason"] == reason
