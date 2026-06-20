"""Webhook 自动回复 dry-run 服务测试。"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AiAgent,
    AiAutoReplyRun,
    AiReplyDecisionLog,
    DouyinAccountAgentBinding,
    DouyinAuthorizedAccount,
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


def _insert_event(
    *,
    event: str = "im_receive_msg",
    account_open_id: str = "account-open-1",
    customer_open_id: str = "customer-open-1",
    conversation_short_id: str = "conv-1",
    text: str = "你好，想了解一下A6",
    event_key: str = "event-key-1",
    server_message_id: str = "server-msg-1",
    is_duplicate: int = 0,
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        from_user_id = customer_open_id if event == "im_receive_msg" else account_open_id
        to_user_id = account_open_id if event == "im_receive_msg" else customer_open_id
        content = {
            "create_time": 1710000000000,
            "conversation_short_id": conversation_short_id,
            "server_message_id": server_message_id,
            "message_type": "text",
            "text": text,
        }
        row = DouyinWebhookEvent(
            event=event,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            message_type="text",
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            event_key=event_key,
            is_duplicate=is_duplicate,
            raw_body=json.dumps(
                {"event": event, "from_user_id": from_user_id, "to_user_id": to_user_id, "content": content},
                ensure_ascii=False,
            ),
            created_at=created_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _insert_account_agent_binding(
    *,
    account_open_id: str = "account-open-1",
    merchant_id: str = "merchant-1",
    tenant_id: str = "tenant-1",
    agent_id: str = "agent-1",
    bind_status: int = 1,
    binding_status: str = "active",
    agent_status: str = "active",
) -> None:
    db = TestSession()
    try:
        account = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=account_open_id,
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            bind_status=bind_status,
            account_name="测试企业号",
        )
        db.add(account)
        db.flush()
        db.add(
            AiAgent(
                agent_id=agent_id,
                merchant_id=merchant_id,
                name="测试智能体",
                avatar_seed="seed",
                prompt="只按知识库回答，不承诺价格。",
                knowledge_base_text="A6 可介绍配置和到店咨询。",
                status=agent_status,
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                tenant_id=tenant_id,
                account_open_id=account_open_id,
                douyin_authorized_account_id=account.id,
                agent_id=agent_id,
                is_default=True,
                status=binding_status,
            )
        )
        db.commit()
    finally:
        db.close()


def _latest_run():
    db = TestSession()
    try:
        return db.query(AiAutoReplyRun).order_by(AiAutoReplyRun.id.desc()).first()
    finally:
        db.close()


class FakeAiCsClient:
    def __init__(self, result=None, error: Exception | None = None):
        self.calls = []
        self.result = result or {
            "reply_text": "您好，可以先介绍一下您的预算和关注车型。",
            "manual_required": False,
            "risk_flags": [],
            "rag_used": True,
            "rag_sources": [{"chunk_id": "c1"}],
            "confidence": 0.91,
            "auto_send": False,
            "llm_used": True,
        }
        self.error = error

    def suggest_reply(self, *, context, conversation_id, request):
        self.calls.append({"context": context, "conversation_id": conversation_id, "request": request})
        if self.error:
            raise self.error
        return dict(self.result)


def test_non_receive_event_is_skipped():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event="im_send_msg", event_key="event-send")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "not_im_receive_msg"


def test_duplicate_event_is_skipped():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(is_duplicate=1, event_key="event-dup")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "duplicate_event"


def test_existing_trigger_event_key_does_not_run_twice():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-existing")
    db = TestSession()
    try:
        db.add(
            AiAutoReplyRun(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                trigger_event_id=event_id,
                trigger_event_key="event-existing",
                mode="dry_run",
                status="decided",
            )
        )
        db.commit()
    finally:
        db.close()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    db = TestSession()
    try:
        assert db.query(AiAutoReplyRun).count() == 1
    finally:
        db.close()


def test_empty_latest_message_is_skipped():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(text="   ", event_key="event-empty")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "empty_message"


def test_unauthorized_account_is_skipped():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-account")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "account_not_authorized"


def test_unbound_agent_is_skipped():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-binding")
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id="account-open-1",
                merchant_id="merchant-1",
                tenant_id="tenant-1",
                bind_status=1,
            )
        )
        db.commit()
    finally:
        db.close()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "agent_binding_not_found"


def test_active_binding_calls_9100_with_history_and_records_decision_log():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    base_time = datetime.now() - timedelta(minutes=10)
    _insert_event(
        text="之前问过配置",
        event_key="history-customer",
        server_message_id="history-customer-msg",
        created_at=base_time,
    )
    _insert_event(
        event="im_send_msg",
        text="您好，我是小高客服",
        event_key="history-agent",
        server_message_id="history-agent-msg",
        created_at=base_time + timedelta(minutes=1),
    )
    event_id = _insert_event(
        text="现在想了解A6",
        event_key="event-active",
        server_message_id="latest-msg",
        created_at=base_time + timedelta(minutes=2),
    )
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    assert len(fake_client.calls) == 1
    payload = fake_client.calls[0]["request"]
    assert payload["latest_message"] == "现在想了解A6"
    assert payload["conversation_history"] == [
        {
            "role": "customer",
            "content": "之前问过配置",
            "created_at": payload["conversation_history"][0]["created_at"],
            "message_id": "history-customer-msg",
        },
        {
            "role": "agent",
            "content": "您好，我是小高客服",
            "created_at": payload["conversation_history"][1]["created_at"],
            "message_id": "history-agent-msg",
        },
    ]
    assert payload["agent_config"]["agent_id"] == "agent-1"
    assert payload["agent_config"]["allowed_category_keys"] == ["base"]

    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).one()
        assert run.status == "decided"
        assert run.would_send_content == "您好，可以先介绍一下您的预算和关注车型。"
        assert run.decision_log_id is not None
        log = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).one()
        assert log.final_auto_send == 0
    finally:
        db.close()


def test_9100_manual_required_blocks_run():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-manual")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient(result={
        "reply_text": "请人工处理",
        "manual_required": True,
        "risk_flags": [],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "auto_send": False,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "manual_required"


def test_9100_risk_flags_block_run():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-risk")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient(result={
        "reply_text": "风险回复",
        "manual_required": False,
        "risk_flags": ["price_commitment"],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "auto_send": False,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "risk_flags"


def test_9100_rag_and_confidence_gates_block_run():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    cases = [
        ("account-rag-used", "event-rag-used", {"rag_used": False, "rag_sources": [{"chunk_id": "c1"}], "confidence": 0.99}, "rag_not_used"),
        ("account-rag-sources", "event-rag-sources", {"rag_used": True, "rag_sources": [], "confidence": 0.99}, "rag_sources_empty"),
        ("account-confidence", "event-confidence", {"rag_used": True, "rag_sources": [{"chunk_id": "c1"}], "confidence": 0.3}, "confidence_low"),
    ]
    for account_open_id, event_key, overrides, expected_reason in cases:
        event_id = _insert_event(
            account_open_id=account_open_id,
            event_key=event_key,
            server_message_id=f"{event_key}-msg",
        )
        _insert_account_agent_binding(account_open_id=account_open_id, agent_id=f"agent-{event_key}")
        result = {
            "reply_text": "测试",
            "manual_required": False,
            "risk_flags": [],
            "auto_send": False,
            **overrides,
        }
        fake_client = FakeAiCsClient(result=result)

        with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
             patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
            run_ai_auto_reply_dry_run(event_id)

        run = _latest_run()
        assert run.status == "blocked"
        assert run.block_reason == expected_reason


def test_9100_auto_send_true_is_forced_false_and_blocked():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-autosend")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient(result={
        "reply_text": "上游想自动发",
        "manual_required": False,
        "risk_flags": [],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "auto_send": True,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).one()
        assert run.status == "blocked"
        assert run.block_reason == "upstream_auto_send_requested"
        assert run.would_send_content is None
        log = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).one()
        assert log.upstream_auto_send == 1
        assert log.final_auto_send == 0
    finally:
        db.close()


def test_9100_exception_records_failed_run():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    event_id = _insert_event(event_key="event-failed")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient(error=XgDouyinAiCsClientError("xg_douyin_ai_cs_timeout"))

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "failed"
    assert "xg_douyin_ai_cs_timeout" in run.error_message


def test_dry_run_never_calls_send_msg():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-send")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.douyin_private_message_send_service.send_manual_private_message") as send_mock:
        run_ai_auto_reply_dry_run(event_id)

    send_mock.assert_not_called()
