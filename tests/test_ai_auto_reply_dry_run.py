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
    ConversationAutopilotState,
    DouyinAccountAgentBinding,
    DouyinAccountAutoreplySetting,
    DouyinAuthorizedAccount,
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


def _enable_real_send_config(monkeypatch) -> None:
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET", set())
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET", set())
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET", set())


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
    agent_prompt: str = "只按知识库回答，不承诺价格。",
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
                prompt=agent_prompt,
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


def _insert_autoreply_settings(
    *,
    merchant_id: str = "merchant-1",
    account_open_id: str = "account-open-1",
    enabled: bool = True,
    dry_run_enabled: bool = True,
    send_enabled: bool = False,
    min_confidence: float = 0.85,
    require_rag: bool = True,
    require_rag_sources: bool = True,
    allowed_intents_json: str | None = None,
    blocked_risk_flags_json: str | None = None,
    direct_llm_policy: dict | None = None,
    max_replies_per_conversation_per_hour: int = 20,
    max_replies_per_account_per_hour: int = 300,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                enabled=enabled,
                dry_run_enabled=dry_run_enabled,
                send_enabled=send_enabled,
                min_confidence=min_confidence,
                require_rag=require_rag,
                require_rag_sources=require_rag_sources,
                allowed_intents_json=allowed_intents_json,
                blocked_risk_flags_json=blocked_risk_flags_json,
                direct_llm_policy_json=json.dumps(direct_llm_policy or {}, ensure_ascii=False),
                max_replies_per_conversation_per_hour=max_replies_per_conversation_per_hour,
                max_replies_per_account_per_hour=max_replies_per_account_per_hour,
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_manual_takeover(
    *,
    merchant_id: str = "merchant-1",
    account_open_id: str = "account-open-1",
    conversation_short_id: str = "conv-1",
    manual_takeover_until: datetime | None = None,
    customer_open_id: str | None = None,
    last_human_message_at: datetime | None = None,
) -> None:
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                conversation_short_id=conversation_short_id,
                customer_open_id=customer_open_id,
                mode="manual",
                manual_takeover_until=manual_takeover_until,
                last_human_message_at=last_human_message_at,
                updated_at=last_human_message_at,
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


def test_non_receive_event_does_not_create_auto_reply_run():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event="im_send_msg", event_key="event-send")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    db = TestSession()
    try:
        assert db.query(AiAutoReplyRun).count() == 0
    finally:
        db.close()


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


def test_unauthorized_account_is_blocked():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-account")

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "account_not_authorized"


def test_unbound_agent_is_blocked_without_calling_9100():
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

    fake_client = FakeAiCsClient()
    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "agent_not_bound"
    assert fake_client.calls == []


def test_multi_account_webhook_uses_each_account_agent_and_policy():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id_a = _insert_event(
        account_open_id="account-a",
        customer_open_id="customer-a",
        conversation_short_id="conv-a",
        event_key="event-account-a",
        server_message_id="msg-account-a",
        text="你好",
    )
    event_id_b = _insert_event(
        account_open_id="account-b",
        customer_open_id="customer-b",
        conversation_short_id="conv-b",
        event_key="event-account-b",
        server_message_id="msg-account-b",
        text="你好，介绍一下主营",
    )
    _insert_account_agent_binding(
        account_open_id="account-a",
        merchant_id="merchant-same",
        tenant_id="tenant-same",
        agent_id="agent-a",
    )
    _insert_account_agent_binding(
        account_open_id="account-b",
        merchant_id="merchant-same",
        tenant_id="tenant-same",
        agent_id="agent-b",
    )
    _insert_autoreply_settings(
        merchant_id="merchant-same",
        account_open_id="account-a",
        direct_llm_policy={
            "direct_llm_auto_send_enabled": False,
            "policy_level": "conservative",
            "specific_model_strategy": "manual_confirm",
        },
    )
    _insert_autoreply_settings(
        merchant_id="merchant-same",
        account_open_id="account-b",
        direct_llm_policy={
            "direct_llm_auto_send_enabled": True,
            "policy_level": "standard",
            "specific_model_strategy": "safe_clarify",
        },
    )
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id_a)
        run_ai_auto_reply_dry_run(event_id_b)

    assert len(fake_client.calls) == 2
    payloads = {call["request"]["account_id"]: call["request"] for call in fake_client.calls}
    assert payloads["account-a"]["agent_id"] == "agent-a"
    assert payloads["account-a"]["agent_config"]["agent_id"] == "agent-a"
    assert payloads["account-a"]["direct_llm_policy"]["policy_level"] == "conservative"
    assert payloads["account-a"]["direct_llm_policy"]["direct_llm_auto_send_enabled"] is False
    assert payloads["account-b"]["agent_id"] == "agent-b"
    assert payloads["account-b"]["agent_config"]["agent_id"] == "agent-b"
    assert payloads["account-b"]["direct_llm_policy"]["policy_level"] == "standard"
    assert payloads["account-b"]["direct_llm_policy"]["specific_model_strategy"] == "safe_clarify"

    db = TestSession()
    try:
        runs = {run.account_open_id: run for run in db.query(AiAutoReplyRun).all()}
        assert runs["account-a"].merchant_id == "merchant-same"
        assert runs["account-a"].agent_id == "agent-a"
        assert runs["account-a"].customer_open_id == "customer-a"
        assert runs["account-b"].merchant_id == "merchant-same"
        assert runs["account-b"].agent_id == "agent-b"
        assert runs["account-b"].customer_open_id == "customer-b"
    finally:
        db.close()


def test_webhook_for_account_b_ignores_account_a_frontend_context():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _insert_account_agent_binding(
        account_open_id="account-a",
        merchant_id="merchant-same",
        tenant_id="tenant-same",
        agent_id="agent-a",
    )
    _insert_autoreply_settings(
        merchant_id="merchant-same",
        account_open_id="account-a",
        direct_llm_policy={"policy_level": "conservative"},
    )
    _insert_account_agent_binding(
        account_open_id="account-b",
        merchant_id="merchant-same",
        tenant_id="tenant-same",
        agent_id="agent-b",
    )
    _insert_autoreply_settings(
        merchant_id="merchant-same",
        account_open_id="account-b",
        direct_llm_policy={"policy_level": "standard", "specific_model_strategy": "safe_clarify"},
    )
    event_id = _insert_event(
        account_open_id="account-b",
        customer_open_id="customer-b",
        conversation_short_id="conv-b-only",
        event_key="event-b-only",
        server_message_id="msg-b-only",
    )
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    assert len(fake_client.calls) == 1
    payload = fake_client.calls[0]["request"]
    assert payload["account_id"] == "account-b"
    assert payload["agent_id"] == "agent-b"
    assert payload["direct_llm_policy"]["policy_level"] == "standard"

    run = _latest_run()
    assert run.account_open_id == "account-b"
    assert run.agent_id == "agent-b"


def test_autoreply_disabled_does_not_call_9100_and_records_reason():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(account_open_id="account-disabled-only", event_key="event-disabled-only")
    _insert_account_agent_binding(account_open_id="account-disabled-only", agent_id="agent-disabled-only")
    _insert_autoreply_settings(account_open_id="account-disabled-only", enabled=False)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "autoreply_disabled"
    assert fake_client.calls == []


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
    _insert_autoreply_settings(send_enabled=True)
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
    assert payload["agent_config"]["allowed_category_keys"] == []
    assert payload["agent_config"]["rag_enabled"] is False

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


def test_auto_reply_run_injects_bound_agent_prompt_and_records_prompt_digest():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    agent_prompt = "唯一指令：每次回复都要自然引导客户留手机号。"
    event_id = _insert_event(
        text="这俩我都关注。要是有现车，能先把检测报告和最低价发我看看吗？",
        event_key="event-bound-agent-prompt",
        server_message_id="latest-bound-agent-msg",
    )
    _insert_account_agent_binding(agent_prompt=agent_prompt)
    _insert_autoreply_settings(send_enabled=True)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    assert len(fake_client.calls) == 1
    payload = fake_client.calls[0]["request"]
    assert payload["agent_config"]["system_prompt"] == agent_prompt
    assert payload["agent_config"]["prompt"] == agent_prompt

    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).one()
        gate_results = json.loads(run.gate_results_json)
        assert gate_results["agent"]["status"] == "ok"
        assert gate_results["agent"]["agent_id"] == "agent-1"
        assert gate_results["agent"]["agent_name"] == "测试智能体"
        assert gate_results["agent"]["prompt_chars"] == len(agent_prompt)
        assert len(gate_results["agent"]["prompt_sha256"]) == 64
    finally:
        db.close()


def test_9100_manual_required_blocks_real_send_candidate():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-manual")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
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
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "manual_required"
    assert run.would_send_content is None


def test_9100_risk_flags_block_real_send_candidate():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-risk")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
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
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "risk_flags"
    assert run.would_send_content is None


def test_polluted_fenced_json_reply_text_is_cleaned_before_run_content():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-fenced-json")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
    fake_client = FakeAiCsClient(result={
        "reply_text": '```json\n{"reply_text":"你好","manual_required":true,"risk_flags":["llm_json_parse_failed"],"confidence":0,"auto_send":false}\n```',
        "manual_required": True,
        "risk_flags": ["llm_json_parse_failed"],
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
    assert run.would_send_content is None
    db = TestSession()
    try:
        log = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).one()
        assert log.reply_text == "你好"
        assert "```json" not in log.reply_text
        assert "manual_required" not in log.reply_text
    finally:
        db.close()


def test_json_without_reply_text_is_blocked_before_run_content():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-json-without-reply")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
    fake_client = FakeAiCsClient(result={
        "reply_text": '{"manual_required":true,"risk_flags":["llm_json_parse_failed"],"confidence":0,"auto_send":false}',
        "manual_required": True,
        "risk_flags": ["llm_json_parse_failed"],
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
    assert run.block_reason == "format_invalid"
    assert run.error_message == "llm_reply_json_parse_failed"
    assert run.would_send_content is None


def test_9100_rag_and_confidence_gates_block_real_send_candidate():
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
        _insert_autoreply_settings(account_open_id=account_open_id, send_enabled=True, dry_run_enabled=False)
        result = {
            "reply_text": "测试",
            "manual_required": False,
            "risk_flags": [],
            "auto_send": False,
            **overrides,
        }
        fake_client = FakeAiCsClient(result=result)

        with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
             patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
             patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
            run_ai_auto_reply_dry_run(event_id)

        auto_send_mock.assert_not_called()
        run = _latest_run()
        assert run.status == "blocked"
        assert run.block_reason == expected_reason
        assert run.would_send_content is None


def test_9100_fallback_reason_blocks_real_send_candidate():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-fallback-reason")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient(result={
        "reply_text": "fallback 回复不能自动发送",
        "manual_required": False,
        "risk_flags": [],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "fallback_reason": "milvus_search_failed",
        "auto_send": True,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    gate_results = json.loads(run.gate_results_json)
    assert run.status == "blocked"
    assert run.block_reason == "fallback_reason"
    assert run.would_send_content is None
    assert gate_results["post_llm"]["fallback_reason"] == "milvus_search_failed"


def test_9100_auto_send_true_is_blocked_when_account_send_disabled():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-autosend")
    _insert_account_agent_binding()
    _insert_autoreply_settings()
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
        assert run.block_reason == "account_send_disabled"
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
    _insert_autoreply_settings()
    fake_client = FakeAiCsClient(error=XgDouyinAiCsClientError("xg_douyin_ai_cs_timeout"))

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "failed"
    assert "xg_douyin_ai_cs_timeout" in run.error_message


def test_9100_timeout_diagnostics_records_layer_and_does_not_send():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    event_id = _insert_event(event_key="event-timeout-diagnostics")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient(
        error=XgDouyinAiCsClientError(
            "xg_cs_http_timeout",
            detail={
                "error": "xg_cs_http_timeout",
                "timeout_layer": "9000_to_9100",
                "elapsed_ms": 75001,
                "timeout_seconds": 75,
                "upstream_url": "http://xg-ai/douyin/reply-suggestion",
            },
        )
    )

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    gate_results = json.loads(run.gate_results_json)
    assert run.status == "failed"
    assert run.decision_log_id is None
    assert run.would_send_content is None
    assert run.error_message == "xg_cs_http_timeout"
    assert gate_results["llm"]["status"] == "failed"
    assert gate_results["llm"]["error"] == "xg_cs_http_timeout"
    assert gate_results["llm"]["timeout_layer"] == "9000_to_9100"
    assert gate_results["llm"]["elapsed_ms"] == 75001
    assert gate_results["llm"]["timeout_seconds"] == 75


def test_9100_provider_timeout_response_marks_run_failed_and_does_not_send():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-provider-timeout-response")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient(
        result={
            "reply_text": "AI 模型调用失败，请人工确认回复。",
            "manual_required": True,
            "manual_required_reason": "LLM provider 调用超时，需要人工确认",
            "risk_flags": ["llm_provider_timeout"],
            "rag_used": True,
            "rag_sources": [{"chunk_id": "c1"}],
            "confidence": 0.0,
            "auto_send": False,
            "llm_used": False,
            "error_code": "llm_provider_timeout",
            "timeout_layer": "9100_to_llm_provider",
            "elapsed_ms": 60002,
            "timeout_seconds": 60,
            "provider": "api.ofox.io",
            "model": "google/gemini-3-flash-preview",
        }
    )

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    gate_results = json.loads(run.gate_results_json)
    assert run.status == "failed"
    assert run.decision_log_id is None
    assert run.would_send_content is None
    assert run.error_message == "llm_provider_timeout"
    assert gate_results["llm"]["error"] == "llm_provider_timeout"
    assert gate_results["llm"]["timeout_layer"] == "9100_to_llm_provider"
    assert gate_results["llm"]["provider"] == "api.ofox.io"
    assert gate_results["llm"]["model"] == "google/gemini-3-flash-preview"


def test_dry_run_never_calls_send_msg():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-send")
    _insert_account_agent_binding()
    _insert_autoreply_settings()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.douyin_private_message_send_service.send_manual_private_message") as send_mock:
        run_ai_auto_reply_dry_run(event_id)

    send_mock.assert_not_called()


def test_send_enabled_false_does_not_call_auto_send_service():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-send-disabled-no-auto")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=False)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "account_send_disabled"


def test_real_send_mode_requires_upstream_auto_send_true(monkeypatch):
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _enable_real_send_config(monkeypatch)
    event_id = _insert_event(event_key="event-real-send-candidate")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.mode == "real_send_candidate"
    assert run.status == "send_skipped"
    assert run.block_reason == "auto_send_disabled_by_decision"


def test_real_send_mode_all_gates_pass_calls_fake_sender_once(monkeypatch):
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _enable_real_send_config(monkeypatch)
    event_id = _insert_event(event_key="event-real-send-allowed", server_message_id="server-msg-allowed")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient(result={
        "reply_text": "您好，可以先说下预算和关注车型，我帮您整理需求。",
        "manual_required": False,
        "risk_flags": [],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1", "document_id": "d1", "title": "base"}],
        "source_chunks": [{"chunk_id": "c1", "document_id": "d1", "title": "base"}],
        "confidence": 0.99,
        "intent": "vehicle_intro",
        "auto_send": True,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch(
             "app.services.douyin_private_message_send_service.call_douyin_openapi",
             return_value={"payload": {"code": 0, "data": {"msg_id": "fake-upstream-msg"}}},
         ) as fake_sender:
        run_ai_auto_reply_dry_run(event_id)

    fake_sender.assert_called_once()
    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).one()
        log = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id == run.decision_log_id).one()
        send_record = db.query(DouyinPrivateMessageSend).filter(DouyinPrivateMessageSend.auto_reply_run_id == run.id).one()
        gate_results = json.loads(run.gate_results_json)
        assert run.mode == "real_send_candidate"
        assert run.status == "sent"
        assert run.block_reason is None
        assert log.final_auto_send == 1
        assert log.manual_required == 0
        assert log.upstream_auto_send == 1
        assert send_record.auto_send == 1
        assert send_record.manual_confirmed == 0
        assert gate_results["post_llm"]["source_chunks_count"] == 1
        assert gate_results["post_llm"]["final_auto_send"] is True
        assert gate_results["real_send"]["send_gate_passed"] is True
    finally:
        db.close()


def test_dry_run_mode_with_dry_run_enabled_does_not_call_auto_send_service(monkeypatch):
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _enable_real_send_config(monkeypatch)
    event_id = _insert_event(event_key="event-dry-run-mode")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=True)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "decided"
    assert run.mode == "dry_run"


def test_real_send_mode_content_risks_block_auto_send_service(monkeypatch):
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _enable_real_send_config(monkeypatch)
    event_id = _insert_event(event_key="event-blocked-no-auto")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, dry_run_enabled=False)
    fake_client = FakeAiCsClient(result={
        "reply_text": "宝马5系有现车，价格20万，可以加微信聊。",
        "manual_required": True,
        "risk_flags": ["inventory_claim", "price_or_discount", "contact_request"],
        "rag_used": False,
        "rag_sources": [],
        "confidence": 0.1,
        "auto_send": False,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "manual_required"
    assert run.would_send_content is None


def test_9100_auto_send_true_in_dry_run_mode_does_not_call_auto_send_service():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-upstream-auto-no-send")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
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
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run") as auto_send_mock:
        run_ai_auto_reply_dry_run(event_id)

    auto_send_mock.assert_not_called()
    run = _latest_run()
    assert run.status == "decided"
    assert run.block_reason is None


def test_no_autoreply_settings_skips_without_calling_9100():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-no-settings")
    _insert_account_agent_binding()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "skipped"
    assert run.skip_reason == "no_autoreply_settings"
    assert fake_client.calls == []


def test_autoreply_disabled_skips_but_dry_run_disabled_continues_to_decision(monkeypatch):
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    _enable_real_send_config(monkeypatch)
    event_id_1 = _insert_event(account_open_id="account-disabled", event_key="event-disabled")
    _insert_account_agent_binding(account_open_id="account-disabled", agent_id="agent-disabled")
    _insert_autoreply_settings(account_open_id="account-disabled", enabled=False, dry_run_enabled=True)

    event_id_2 = _insert_event(account_open_id="account-dry-disabled", event_key="event-dry-disabled")
    _insert_account_agent_binding(account_open_id="account-dry-disabled", agent_id="agent-dry-disabled")
    _insert_autoreply_settings(
        account_open_id="account-dry-disabled",
        enabled=True,
        send_enabled=True,
        dry_run_enabled=False,
    )
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client), \
         patch("app.services.ai_auto_reply_dry_run_service.send_ai_auto_reply_for_run"):
        run_ai_auto_reply_dry_run(event_id_1)
        run_ai_auto_reply_dry_run(event_id_2)

    db = TestSession()
    try:
        runs = {run.trigger_event_key: run for run in db.query(AiAutoReplyRun).all()}
        assert runs["event-disabled"].status == "skipped"
        assert runs["event-disabled"].skip_reason == "autoreply_disabled"
        assert runs["event-dry-disabled"].status == "send_skipped"
        assert runs["event-dry-disabled"].block_reason == "auto_send_disabled_by_decision"
        assert runs["event-dry-disabled"].skip_reason is None
        assert runs["event-dry-disabled"].mode == "real_send_candidate"
        assert len(fake_client.calls) == 1
    finally:
        db.close()


def test_send_disabled_blocks_auto_reply_candidate():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-send-disabled")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=False)
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    db = TestSession()
    try:
        run = db.query(AiAutoReplyRun).one()
        gate_results = json.loads(run.gate_results_json)
        assert len(fake_client.calls) == 1
        assert run.status == "blocked"
        assert run.block_reason == "account_send_disabled"
        assert run.decision_log_id is not None
        assert gate_results["post_llm"]["send_disabled"] is True
    finally:
        db.close()


def test_allowed_intents_and_blocked_risk_flags_block_reply():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id_1 = _insert_event(account_open_id="account-intent", event_key="event-intent")
    _insert_account_agent_binding(account_open_id="account-intent", agent_id="agent-intent")
    _insert_autoreply_settings(
        account_open_id="account-intent",
        send_enabled=True,
        allowed_intents_json=json.dumps(["vehicle_intro"], ensure_ascii=False),
    )
    fake_client_1 = FakeAiCsClient(result={
        "reply_text": "娴嬭瘯",
        "intent": "price",
        "manual_required": False,
        "risk_flags": [],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "auto_send": True,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client_1):
        run_ai_auto_reply_dry_run(event_id_1)

    event_id_2 = _insert_event(account_open_id="account-risk", event_key="event-risk-blocked")
    _insert_account_agent_binding(account_open_id="account-risk", agent_id="agent-risk-blocked")
    _insert_autoreply_settings(
        account_open_id="account-risk",
        send_enabled=True,
        blocked_risk_flags_json=json.dumps(["price_commitment"], ensure_ascii=False),
    )
    fake_client_2 = FakeAiCsClient(result={
        "reply_text": "娴嬭瘯",
        "intent": "vehicle_intro",
        "manual_required": False,
        "risk_flags": ["price_commitment"],
        "rag_used": True,
        "rag_sources": [{"chunk_id": "c1"}],
        "confidence": 0.99,
        "auto_send": True,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client_2):
        run_ai_auto_reply_dry_run(event_id_2)

    db = TestSession()
    try:
        runs = {run.trigger_event_key: run for run in db.query(AiAutoReplyRun).all()}
        assert runs["event-intent"].status == "blocked"
        assert runs["event-intent"].block_reason == "intent_not_allowed"
        assert runs["event-risk-blocked"].status == "blocked"
        assert runs["event-risk-blocked"].block_reason == "risk_flags"
    finally:
        db.close()


def test_require_rag_flags_can_be_disabled():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-rag-disabled")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True, require_rag=False, require_rag_sources=False)
    fake_client = FakeAiCsClient(result={
        "reply_text": "娴嬭瘯",
        "manual_required": False,
        "risk_flags": [],
        "rag_used": False,
        "rag_sources": [],
        "confidence": 0.99,
        "auto_send": False,
    })

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "decided"
    assert run.block_reason is None


def test_manual_takeover_blocks_before_calling_9100():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-manual-takeover")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
    _insert_manual_takeover()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "manual_takeover"
    assert fake_client.calls == []


def test_resumed_ai_autopilot_allows_next_customer_message_to_pass_manual_gate():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run
    from app.services.conversation_autopilot_state_service import resume_ai_autopilot

    event_id = _insert_event(event_key="event-resumed-autopilot")
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
    _insert_manual_takeover()
    db = TestSession()
    try:
        resume_ai_autopilot(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-open-1",
        )
    finally:
        db.close()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "decided"
    assert run.block_reason is None
    assert fake_client.calls


def test_notice_sourced_manual_takeover_is_ignored_for_next_customer_message():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    notice_time = datetime.now() - timedelta(seconds=30)
    event_id = _insert_event(event_key="event-after-notice-manual")
    _insert_event(
        event="im_send_msg",
        text="你收到一条新消息，请打开抖音app查看",
        event_key="event-system-notice-manual",
        server_message_id="server-msg-system-notice",
        created_at=notice_time,
    )
    _insert_account_agent_binding()
    _insert_autoreply_settings(send_enabled=True)
    _insert_manual_takeover(
        customer_open_id="customer-open-1",
        last_human_message_at=notice_time,
    )
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    gate_results = json.loads(run.gate_results_json)
    assert run.status == "decided"
    assert run.block_reason is None
    assert fake_client.calls
    assert gate_results["pre_llm"]["manual_takeover"]["blocked"] is False
    assert gate_results["pre_llm"]["manual_takeover"]["ignored_reason"] == "notice_or_system_message"


def test_frequency_counts_non_skipped_runs_only():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    event_id = _insert_event(event_key="event-frequency")
    _insert_account_agent_binding()
    _insert_autoreply_settings(max_replies_per_conversation_per_hour=1, max_replies_per_account_per_hour=5)
    db = TestSession()
    try:
        db.add(
            AiAutoReplyRun(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                trigger_event_id=100,
                trigger_event_key="old-skipped",
                mode="dry_run",
                status="skipped",
                created_at=datetime.now() - timedelta(minutes=5),
            )
        )
        db.add(
            AiAutoReplyRun(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                trigger_event_id=101,
                trigger_event_key="old-blocked",
                mode="dry_run",
                status="blocked",
                created_at=datetime.now() - timedelta(minutes=5),
            )
        )
        db.commit()
    finally:
        db.close()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "frequency_conversation_exceeded"
    assert fake_client.calls == []


def test_latest_message_not_customer_blocks_before_calling_9100():
    from app.services.ai_auto_reply_dry_run_service import run_ai_auto_reply_dry_run

    base_time = datetime.now() - timedelta(minutes=2)
    event_id = _insert_event(event_key="event-customer-first", created_at=base_time)
    _insert_event(
        event="im_send_msg",
        text="human replied",
        event_key="event-agent-latest",
        server_message_id="agent-latest",
        created_at=base_time + timedelta(minutes=1),
    )
    _insert_account_agent_binding()
    _insert_autoreply_settings()
    fake_client = FakeAiCsClient()

    with patch("app.services.ai_auto_reply_dry_run_service.SessionLocal", TestSession), \
         patch("app.services.ai_auto_reply_dry_run_service.get_xg_douyin_ai_cs_client", lambda: fake_client):
        run_ai_auto_reply_dry_run(event_id)

    run = _latest_run()
    assert run.status == "blocked"
    assert run.block_reason == "latest_message_not_customer"
    assert fake_client.calls == []
