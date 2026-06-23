import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AiAutoReplyRun, AiReplyDecisionLog, DouyinPrivateMessageSend


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
):
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:douyin_ai_cs"],
    )


def _client(context: RequestContext | None = None):
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


def _insert_run(
    *,
    merchant_id: str = "merchant-a",
    account_open_id: str = "account-1",
    conversation_short_id: str = "conv-1",
    customer_open_id: str = "customer-1",
    trigger_event_key: str = "event-1",
    trigger_event_id: int = 1,
    trigger_server_message_id: str = "server-1",
    latest_message: str = "客户手机号13812345678，想了解A6",
    agent_id: str = "agent-1",
    mode: str = "dry_run",
    status: str = "decided",
    skip_reason: str | None = None,
    block_reason: str | None = None,
    gate_results_json: str | None = None,
    decision_log_id: int | None = 10,
    would_send_content: str | None = "您好，13812345678 这个手机号我不会原样展示。",
    error_message: str | None = None,
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        row = AiAutoReplyRun(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            customer_open_id=customer_open_id,
            trigger_event_id=trigger_event_id,
            trigger_event_key=trigger_event_key,
            trigger_server_message_id=trigger_server_message_id,
            latest_message=latest_message,
            agent_id=agent_id,
            mode=mode,
            status=status,
            skip_reason=skip_reason,
            block_reason=block_reason,
            gate_results_json=gate_results_json
            if gate_results_json is not None
            else json.dumps({"post_llm": {"send_disabled": True}}, ensure_ascii=False),
            decision_log_id=decision_log_id,
            would_send_content=would_send_content,
            error_message=error_message,
            created_at=created_at or datetime.now(),
            updated_at=created_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _insert_send_record(*, run_id: int, decision_log_id: int | None = 10):
    db = TestSession()
    try:
        row = DouyinPrivateMessageSend(
            main_account_id=123,
            conversation_short_id="conv-1",
            server_message_id="server-send",
            from_user_id="account-1",
            to_user_id="customer-1",
            customer_open_id="customer-1",
            account_open_id="account-1",
            content="自动回复内容",
            status="sent",
            upstream_msg_id="upstream-1",
            manual_confirmed=0,
            auto_send=1,
            send_source="ai_auto",
            auto_reply_run_id=run_id,
            decision_log_id=decision_log_id,
            sent_at=datetime.now(),
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _insert_decision_log(
    *,
    log_id: int = 10,
    merchant_id: str = "merchant-a",
    final_auto_send: int = 0,
    risk_flags_json: str = '["no_rag_risky_question"]',
):
    db = TestSession()
    try:
        row = AiReplyDecisionLog(
            id=log_id,
            merchant_id=merchant_id,
            tenant_id="tenant-a",
            account_open_id="account-1",
            conversation_id="conv-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-1",
            agent_id="agent-1",
            agent_name="销售智能体",
            latest_message="客户想了解主营车型",
            reply_text="您好！我们主营奔驰、宝马、奥迪等精品二手车。",
            manual_required=0,
            manual_required_reason=None,
            risk_flags_json=risk_flags_json,
            tags_json='["intro"]',
            llm_used=1,
            rag_used=0,
            upstream_auto_send=0,
            final_auto_send=final_auto_send,
            decision_version="direct_llm_structured_v1",
            created_at=datetime.now(),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def test_runs_api_requires_permission_and_merchant_context():
    denied = _client(_context(permission_codes=["auto_wechat:leads"])).get("/ai-auto-reply-runs")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    missing_merchant = _client(_context(merchant_id=None)).get("/ai-auto-reply-runs")
    assert missing_merchant.status_code == 403
    assert missing_merchant.json()["detail"]["code"] == "MERCHANT_CONTEXT_MISSING"


def test_list_runs_returns_only_current_merchant_and_ignores_forged_merchant_id():
    _insert_run(merchant_id="merchant-a", trigger_event_key="event-a")
    _insert_run(merchant_id="merchant-b", trigger_event_key="event-b")

    response = _client().get("/ai-auto-reply-runs", params={"merchant_id": "merchant-b"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["merchant_id"] == "merchant-a"
    assert item["trigger_event_key"] == "event-a"
    assert "gate_results_json" not in item
    assert "gate_results" not in item
    assert "138****5678" in item["latest_message_summary"]
    assert "138****5678" in item["would_send_content_summary"]


def test_list_runs_filters_and_limits_page_size():
    now = datetime(2026, 6, 21, 10, 0, 0)
    _insert_run(
        account_open_id="account-match",
        conversation_short_id="conv-match",
        customer_open_id="customer-match",
        agent_id="agent-match",
        status="sent",
        latest_message="低风险咨询",
        trigger_event_key="match",
        created_at=now,
    )
    _insert_run(
        account_open_id="account-miss",
        conversation_short_id="conv-miss",
        customer_open_id="customer-miss",
        agent_id="agent-miss",
        status="blocked",
        latest_message="其他内容",
        trigger_event_key="miss",
        created_at=now - timedelta(days=2),
    )

    response = _client().get(
        "/ai-auto-reply-runs",
        params={
            "account_open_id": "account-match",
            "conversation_short_id": "conv-match",
            "customer_open_id": "customer-match",
            "agent_id": "agent-match",
            "status": "sent",
            "keyword": "低风险",
            "created_from": "2026-06-21T00:00:00",
            "created_to": "2026-06-22T00:00:00",
            "page_size": 500,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page_size"] == 100
    assert data["total"] == 1
    assert data["items"][0]["trigger_event_key"] == "match"


def test_list_runs_includes_decision_summary_for_workbench_visibility():
    _insert_decision_log()
    _insert_run(
        status="send_skipped",
        block_reason="auto_send_disabled_by_decision",
        decision_log_id=10,
        would_send_content="您好！我们主营奔驰、宝马、奥迪等精品二手车。",
    )

    response = _client().get(
        "/ai-auto-reply-runs",
        params={
            "account_open_id": "account-1",
            "conversation_short_id": "conv-1",
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["status"] == "send_skipped"
    assert item["block_reason"] == "auto_send_disabled_by_decision"
    assert item["reply_text"] == "您好！我们主营奔驰、宝马、奥迪等精品二手车。"
    assert item["manual_required"] is False
    assert item["risk_flags"] == ["no_rag_risky_question"]
    assert item["llm_used"] is True
    assert item["rag_used"] is False
    assert item["upstream_auto_send"] is False
    assert item["final_auto_send"] is False
    assert item["decision_version"] == "direct_llm_structured_v1"


def test_list_runs_returns_latest_run_for_current_workbench_conversation():
    older_time = datetime(2026, 6, 22, 10, 0, 0)
    newer_time = datetime(2026, 6, 22, 10, 1, 0)
    _insert_run(
        trigger_event_key="older-run",
        conversation_short_id="conv-1",
        status="blocked",
        block_reason="manual_takeover",
        decision_log_id=None,
        would_send_content=None,
        created_at=older_time,
    )
    _insert_run(
        trigger_event_key="newer-run",
        conversation_short_id="conv-1",
        status="send_skipped",
        block_reason="auto_send_disabled_by_decision",
        created_at=newer_time,
    )
    _insert_run(
        trigger_event_key="other-conversation",
        conversation_short_id="conv-2",
        created_at=datetime(2026, 6, 22, 10, 2, 0),
    )

    response = _client().get(
        "/ai-auto-reply-runs",
        params={
            "account_open_id": "account-1",
            "conversation_short_id": "conv-1",
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["trigger_event_key"] == "newer-run"
    assert item["status"] == "send_skipped"
    assert item["block_reason"] == "auto_send_disabled_by_decision"


def test_list_runs_does_not_expose_other_merchant_decision_log():
    _insert_decision_log(log_id=88, merchant_id="merchant-b")
    _insert_run(
        merchant_id="merchant-a",
        trigger_event_key="event-cross-merchant-decision",
        decision_log_id=88,
    )

    response = _client().get("/ai-auto-reply-runs", params={"page_size": 1})

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["merchant_id"] == "merchant-a"
    assert item["decision_log_id"] == 88
    assert item["reply_text"] is None
    assert item["risk_flags"] == []
    assert item["final_auto_send"] is None


def test_detail_returns_gate_results_and_send_record_without_raw_response_or_plain_phone():
    run_id = _insert_run()
    _insert_send_record(run_id=run_id)

    response = _client().get(f"/ai-auto-reply-runs/{run_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == run_id
    assert data["latest_message"] == "客户手机号138****5678，想了解A6"
    assert data["would_send_content"] == "您好，138****5678 这个手机号我不会原样展示。"
    assert data["gate_results"] == {"post_llm": {"send_disabled": True}}
    assert data["send_record"]["send_status"] == "sent"
    assert data["send_record"]["send_source"] == "ai_auto"
    assert data["send_record"]["auto_send"] is True
    assert data["send_record"]["manual_confirmed"] is False
    assert "raw_response_json" not in data
    assert "raw_response" not in data
    assert "13812345678" not in json.dumps(data, ensure_ascii=False)


def test_sent_run_returns_auto_replied_state_without_content_gate_blocking():
    _insert_decision_log(
        log_id=90,
        final_auto_send=1,
        risk_flags_json='["price_or_discount"]',
    )
    run_id = _insert_run(
        status="sent",
        block_reason=None,
        decision_log_id=90,
        gate_results_json=json.dumps(
            {"post_llm": {"final_auto_send": True, "risk_flags": ["price_or_discount"]}},
            ensure_ascii=False,
        ),
        would_send_content="auto reply content",
    )
    _insert_send_record(run_id=run_id, decision_log_id=90)

    list_response = _client().get("/ai-auto-reply-runs", params={"status": "sent", "page_size": 1})
    detail_response = _client().get(f"/ai-auto-reply-runs/{run_id}")

    assert list_response.status_code == 200
    item = list_response.json()["data"]["items"][0]
    assert item["status"] == "sent"
    assert item["block_reason"] is None
    assert item["risk_flags"] == ["price_or_discount"]
    assert item["final_auto_send"] is True
    assert detail_response.status_code == 200
    send_record = detail_response.json()["data"]["send_record"]
    assert send_record["send_status"] == "sent"
    assert send_record["send_source"] == "ai_auto"
    assert send_record["auto_send"] is True


def test_detail_cannot_read_other_merchant_run():
    run_id = _insert_run(merchant_id="merchant-b")

    response = _client().get(f"/ai-auto-reply-runs/{run_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AI_AUTO_REPLY_RUN_NOT_FOUND"


def test_bad_gate_results_json_does_not_500():
    run_id = _insert_run(gate_results_json="{bad")

    detail = _client().get(f"/ai-auto-reply-runs/{run_id}")

    assert detail.status_code == 200
    assert detail.json()["data"]["gate_results"] == {}
