import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AiReplyDecisionLog,
    AutoReplyAdminAuditLog,
    DouyinPrivateMessageSend,
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


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
):
    return RequestContext(
        user_id="user-1",
        username="admin-user",
        display_name="审核员",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:douyin_ai_cs"],
        super_admin=super_admin,
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


def _insert_log(
    *,
    merchant_id: str = "merchant-a",
    account_open_id: str = "account-1",
    conversation_id: str = "conv-1",
    agent_id: str = "agent-1",
    agent_name: str = "销售智能体",
    latest_message: str = "客户问奥迪A6价格，手机号13812345678",
    reply_text: str = "建议回复：可以先介绍车型亮点",
    intent: str = "price",
    lead_level: str = "high",
    confidence: float = 0.82,
    manual_required: int = 1,
    manual_required_reason: str = "涉及价格，需要人工确认",
    risk_flags=None,
    tags=None,
    rag_sources=None,
    source_chunks=None,
    allowed_category_keys=None,
    llm_used: int = 1,
    rag_used: int = 1,
    upstream_auto_send: int = 0,
    final_auto_send: int = 0,
    decision_version: str = "structured_v1",
    raw_response_json: str = '{"auto_send":true}',
    created_at: datetime | None = None,
):
    db = TestSession()
    try:
        row = AiReplyDecisionLog(
            merchant_id=merchant_id,
            tenant_id="new_car_project",
            account_open_id=account_open_id,
            conversation_id=conversation_id,
            conversation_short_id=conversation_id,
            agent_id=agent_id,
            agent_name=agent_name,
            latest_message=latest_message,
            reply_text=reply_text,
            intent=intent,
            lead_level=lead_level,
            confidence=confidence,
            manual_required=manual_required,
            manual_required_reason=manual_required_reason,
            risk_flags_json=json.dumps(risk_flags if risk_flags is not None else ["price_commitment"], ensure_ascii=False),
            tags_json=json.dumps(tags if tags is not None else ["price", "audi"], ensure_ascii=False),
            rag_sources_json=json.dumps(
                rag_sources if rag_sources is not None else [{"chunk_id": "c1", "document_id": 1, "title": "A6知识", "score": 0.91}],
                ensure_ascii=False,
            ),
            source_chunks_json=json.dumps(
                source_chunks if source_chunks is not None else [{"chunk_id": "c1", "document_id": 1, "title": "A6知识", "score": 0.91}],
                ensure_ascii=False,
            ),
            allowed_category_keys_json=json.dumps(
                allowed_category_keys if allowed_category_keys is not None else ["base", "premium_bba"],
                ensure_ascii=False,
            ),
            llm_used=llm_used,
            rag_used=rag_used,
            upstream_auto_send=upstream_auto_send,
            final_auto_send=final_auto_send,
            decision_version=decision_version,
            raw_response_json=raw_response_json,
            created_at=created_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _insert_send_record(
    *,
    decision_log_id: int | None,
    send_source: str = "ai_auto",
    merchant_account_open_id: str = "account-1",
    conversation_short_id: str = "conv-1",
    customer_open_id: str = "customer-1",
    content: str = "违禁词替换后的最终实发内容 13812345678",
    status: str = "sent",
    auto_send: int = 1,
    manual_confirmed: int = 0,
    auto_reply_run_id: int | None = None,
    sent_at: datetime | None = None,
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        row = DouyinPrivateMessageSend(
            main_account_id=123,
            conversation_short_id=conversation_short_id,
            server_message_id=f"server-send-{datetime.now().timestamp()}",
            from_user_id=merchant_account_open_id,
            to_user_id=customer_open_id,
            customer_open_id=customer_open_id,
            account_open_id=merchant_account_open_id,
            content=content,
            status=status,
            upstream_msg_id="upstream-1" if status == "sent" else None,
            manual_confirmed=manual_confirmed,
            auto_send=auto_send,
            send_source=send_source,
            auto_reply_run_id=auto_reply_run_id,
            decision_log_id=decision_log_id,
            sent_at=sent_at or datetime.now(),
        )
        # created_at 用于对齐 date_from/date_to 筛选（Phase 4 起按发送流水时间过滤）
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_list_logs_returns_only_current_merchant_and_ignores_forged_merchant_id():
    log_a = _insert_log(merchant_id="merchant-a", conversation_id="conv-a")
    log_b = _insert_log(merchant_id="merchant-b", conversation_id="conv-b")
    _insert_send_record(decision_log_id=log_a)
    _insert_send_record(decision_log_id=log_b)

    response = _client().get(
        "/ai-reply-decision-logs",
        params={"merchant_id": "merchant-b"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["items"][0]["merchant_id"] == "merchant-a"
    assert data["items"][0]["conversation_id"] == "conv-a"
    assert "raw_response_json" not in data["items"][0]
    assert "138****5678" in data["items"][0]["latest_message_summary"]


def test_list_logs_requires_permission_and_merchant_context():
    denied = _client(_context(permission_codes=["auto_wechat:leads"])).get("/ai-reply-decision-logs")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    missing_merchant = _client(_context(merchant_id=None)).get("/ai-reply-decision-logs")
    assert missing_merchant.status_code == 403
    assert missing_merchant.json()["detail"]["code"] == "MERCHANT_CONTEXT_MISSING"


def test_list_logs_pagination_and_page_size_limit():
    for index in range(3):
        log_id = _insert_log(
            merchant_id="merchant-a",
            conversation_id=f"conv-{index}",
            created_at=datetime(2026, 6, 20, 10, index, 0),
        )
        _insert_send_record(decision_log_id=log_id)

    response = _client().get("/ai-reply-decision-logs", params={"page": 2, "page_size": 2})
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["total"] == 3
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert len(data["items"]) == 1

    limited = _client().get("/ai-reply-decision-logs", params={"page_size": 500})
    assert limited.status_code == 200
    assert limited.json()["data"]["page_size"] == 100


def test_list_logs_filters_by_structured_fields_and_flags():
    match_log = _insert_log(
        merchant_id="merchant-a",
        conversation_id="match",
        manual_required=1,
        intent="price",
        lead_level="high",
        rag_used=1,
        llm_used=1,
        risk_flags=["price_commitment"],
    )
    _insert_send_record(decision_log_id=match_log)
    miss_log = _insert_log(
        merchant_id="merchant-a",
        conversation_id="miss",
        manual_required=0,
        intent="unknown",
        lead_level="low",
        rag_used=0,
        llm_used=0,
        risk_flags=["no_rag_source"],
    )
    _insert_send_record(decision_log_id=miss_log)

    response = _client().get(
        "/ai-reply-decision-logs",
        params={
            "manual_required": True,
            "intent": "price",
            "lead_level": "high",
            "rag_used": True,
            "llm_used": True,
            "risk_flag": "price_commitment",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["conversation_id"] == "match"
    assert data["items"][0]["risk_flags"] == ["price_commitment"]
    assert data["items"][0]["tags"] == ["price", "audi"]


def test_list_logs_filters_by_keyword_and_date_range():
    old_log = _insert_log(
        merchant_id="merchant-a",
        conversation_id="old",
        latest_message="客户问宝马",
        reply_text="旧回复",
        created_at=datetime(2026, 6, 18, 12, 0, 0),
    )
    _insert_send_record(decision_log_id=old_log, created_at=datetime(2026, 6, 18, 12, 0, 0))
    new_log = _insert_log(
        merchant_id="merchant-a",
        conversation_id="new",
        latest_message="客户问奥迪",
        reply_text="包含关键回复",
        created_at=datetime(2026, 6, 20, 12, 0, 0),
    )
    _insert_send_record(decision_log_id=new_log, created_at=datetime(2026, 6, 20, 12, 0, 0))

    response = _client().get(
        "/ai-reply-decision-logs",
        params={
            "keyword": "关键回复",
            "date_from": "2026-06-19T00:00:00",
            "date_to": "2026-06-21T00:00:00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["conversation_id"] == "new"


def test_detail_returns_current_merchant_log_without_raw_response():
    log_id = _insert_log(
        merchant_id="merchant-a",
        latest_message="客户手机号13812345678，问A6",
        reply_text="回复客户手机号13812345678",
    )
    _insert_send_record(decision_log_id=log_id)

    response = _client().get(f"/ai-reply-decision-logs/{log_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == log_id
    assert data["latest_message"] == "客户手机号138****5678，问A6"
    assert data["reply_text"] == "回复客户手机号138****5678"
    assert data["rag_sources"][0]["title"] == "A6知识"
    assert data["source_chunks"][0]["title"] == "A6知识"
    assert data["allowed_category_keys"] == ["base", "premium_bba"]
    assert "raw_response_json" not in data


def test_detail_cannot_read_other_merchant_log():
    log_id = _insert_log(merchant_id="merchant-b")
    _insert_send_record(decision_log_id=log_id)

    response = _client().get(f"/ai-reply-decision-logs/{log_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AI_REPLY_DECISION_LOG_NOT_FOUND"


def test_bad_json_fields_do_not_return_500():
    log_id = _insert_log(merchant_id="merchant-a")
    _insert_send_record(decision_log_id=log_id)
    db = TestSession()
    try:
        row = db.get(AiReplyDecisionLog, log_id)
        row.risk_flags_json = "{bad"
        row.tags_json = "{bad"
        row.rag_sources_json = "{bad"
        row.source_chunks_json = "{bad"
        row.allowed_category_keys_json = "{bad"
        db.commit()
    finally:
        db.close()

    list_response = _client().get("/ai-reply-decision-logs")
    assert list_response.status_code == 200
    item = list_response.json()["data"]["items"][0]
    assert item["risk_flags"] == []
    assert item["tags"] == []

    detail_response = _client().get(f"/ai-reply-decision-logs/{log_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["risk_flags"] == []
    assert detail["tags"] == []
    assert detail["rag_sources"] == []
    assert detail["source_chunks"] == []
    assert detail["allowed_category_keys"] == []


def test_list_logs_returns_only_ai_sent_records_and_uses_send_content():
    sent_log_id = _insert_log(
        merchant_id="merchant-a",
        conversation_id="conv-sent",
        reply_text="旧建议回复，不应作为实发内容",
        final_auto_send=1,
    )
    _insert_send_record(
        decision_log_id=sent_log_id,
        content="最终实发内容，手机号13812345678已脱敏展示",
        status="sent",
        send_source="ai_auto",
    )
    _insert_log(merchant_id="merchant-a", conversation_id="conv-decision-only")
    _insert_send_record(
        decision_log_id=None,
        content="普通人工发送不应进入 AI 回复记录",
        send_source="manual",
        auto_send=0,
        manual_confirmed=1,
    )

    response = _client().get("/ai-reply-decision-logs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["id"] == sent_log_id
    assert item["send_record_id"] is not None
    assert item["conversation_id"] == "conv-sent"
    assert item["send_status"] == "sent"
    assert item["send_source"] == "ai_auto"
    assert item["sent_content_summary"] == "最终实发内容，手机号138****5678已脱敏展示"
    assert item["reply_text_summary"] != item["sent_content_summary"]


def test_admin_can_filter_by_merchant_but_merchant_user_cannot_forge_scope():
    log_a = _insert_log(merchant_id="merchant-a", conversation_id="conv-a")
    _insert_send_record(decision_log_id=log_a, content="商户A实发")
    log_b = _insert_log(merchant_id="merchant-b", conversation_id="conv-b")
    _insert_send_record(decision_log_id=log_b, content="商户B实发")

    merchant_response = _client().get(
        "/ai-reply-decision-logs",
        params={"merchant_id": "merchant-b"},
    )
    assert merchant_response.status_code == 200
    merchant_data = merchant_response.json()["data"]
    assert merchant_data["total"] == 1
    assert merchant_data["items"][0]["merchant_id"] == "merchant-a"

    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )
    admin_response = _client(admin_context).get(
        "/ai-reply-decision-logs",
        params={"merchant_id": "merchant-b"},
    )
    assert admin_response.status_code == 200
    admin_data = admin_response.json()["data"]
    assert admin_data["total"] == 1
    assert admin_data["items"][0]["merchant_id"] == "merchant-b"


def test_detail_returns_send_content_and_effectiveness_fields():
    log_id = _insert_log(
        merchant_id="merchant-a",
        latest_message="客户手机号13812345678，问A6",
        reply_text="模型原始建议回复",
    )
    send_id = _insert_send_record(
        decision_log_id=log_id,
        content="最终实发内容13812345678",
        status="sent",
    )

    response = _client().get(f"/ai-reply-decision-logs/{log_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == log_id
    assert data["send_record_id"] == send_id
    assert data["sent_content"] == "最终实发内容138****5678"
    assert data["reply_text"] == "模型原始建议回复"
    assert data["is_effective"] is None
    assert data["effectiveness_reason"] is None
    assert "request_body_json" not in data
    assert "response_body_json" not in data


def test_list_and_detail_use_latest_send_record_per_decision_log():
    log_id = _insert_log(
        merchant_id="merchant-a",
        conversation_id="conv-multi-send",
        reply_text="模型原始回复",
    )
    old_send_id = _insert_send_record(
        decision_log_id=log_id,
        content="旧实发内容13812345678",
        status="failed",
        sent_at=datetime(2026, 7, 10, 9, 0, 0),
        created_at=datetime(2026, 7, 10, 9, 0, 0),
    )
    latest_send_id = _insert_send_record(
        decision_log_id=log_id,
        content="最新实发内容wxid_abcd1234",
        status="sent",
        sent_at=datetime(2026, 7, 10, 10, 0, 0),
        created_at=datetime(2026, 7, 10, 10, 0, 0),
    )

    list_response = _client().get("/ai-reply-decision-logs")
    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert list_data["total"] == 1
    item = list_data["items"][0]
    assert item["id"] == log_id
    assert item["send_record_id"] == latest_send_id
    assert item["send_record_id"] != old_send_id
    assert item["send_status"] == "sent"
    assert item["sent_content_summary"] == "最新实发内容wxid***"

    detail_response = _client().get(f"/ai-reply-decision-logs/{log_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["id"] == log_id
    assert detail["send_record_id"] == latest_send_id
    assert detail["sent_content"] == "最新实发内容wxid***"

    # 实发时间字段必须来自发送流水：sent_at 优先，send_created_at 次之
    assert item["sent_at"] == "2026-07-10T10:00:00"
    assert item["send_created_at"] == "2026-07-10T10:00:00"


def test_list_logs_filters_by_send_status_and_effectiveness():
    effective_log = _insert_log(merchant_id="merchant-a", conversation_id="effective")
    pending_log = _insert_log(merchant_id="merchant-a", conversation_id="pending")
    db = TestSession()
    try:
        row = db.get(AiReplyDecisionLog, effective_log)
        row.is_effective = True
        db.commit()
    finally:
        db.close()
    _insert_send_record(decision_log_id=effective_log, status="sent")
    _insert_send_record(decision_log_id=pending_log, status="failed")

    response = _client().get(
        "/ai-reply-decision-logs",
        params={"send_status": "sent", "is_effective": True},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["conversation_id"] == "effective"
    assert data["items"][0]["send_status"] == "sent"
    assert data["items"][0]["is_effective"] is True


def test_patch_effectiveness_requires_admin_and_writes_audit_log():
    log_id = _insert_log(merchant_id="merchant-a")
    _insert_send_record(decision_log_id=log_id)

    denied = _client().patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": "回复促成留资"},
    )
    assert denied.status_code == 403

    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )
    response = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": " 回复促成留资 "},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_effective"] is True
    assert data["effectiveness_reason"] == "回复促成留资"

    db = TestSession()
    try:
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert audit.action == "mark_ai_reply_effectiveness"
        assert audit.target_type == "ai_reply_decision_log"
        assert audit.target_id == str(log_id)
        assert audit.reason == "回复促成留资"
        assert "13812345678" not in json.dumps(audit.after_json or {}, ensure_ascii=False)
    finally:
        db.close()


def test_patch_effectiveness_rejects_empty_payload_and_unsent_decision():
    log_id = _insert_log(merchant_id="merchant-a")
    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )

    empty_payload = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={},
    )
    assert empty_payload.status_code == 400
    assert empty_payload.json()["detail"]["code"] == "NO_FIELDS_TO_UPDATE"

    sent_log_id = _insert_log(merchant_id="merchant-a", conversation_id="sent-log")
    _insert_send_record(decision_log_id=sent_log_id)

    blank_reason = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{sent_log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": "   "},
    )
    assert blank_reason.status_code == 400
    assert blank_reason.json()["detail"]["code"] == "EFFECTIVENESS_REASON_REQUIRED"

    unsent = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": False, "effectiveness_reason": "未发送不能标记"},
    )
    assert unsent.status_code == 404
    assert unsent.json()["detail"]["code"] == "AI_REPLY_DECISION_LOG_NOT_FOUND"


def test_patch_effectiveness_masks_sensitive_reason_in_record_and_audit():
    log_id = _insert_log(merchant_id="merchant-a")
    _insert_send_record(decision_log_id=log_id)
    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )

    response = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={
            "is_effective": False,
            "effectiveness_reason": "客户手机号13812345678，微信wxid_abcd1234，回复偏离需求",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["effectiveness_reason"] == "客户手机号138****5678，微信wxid***，回复偏离需求"

    db = TestSession()
    try:
        row = db.get(AiReplyDecisionLog, log_id)
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert row.effectiveness_reason == "客户手机号138****5678，微信wxid***，回复偏离需求"
        assert audit.reason == "客户手机号138****5678，微信wxid***，回复偏离需求"
        assert "13812345678" not in audit.reason
        assert "wxid_abcd1234" not in audit.reason
        assert "13812345678" not in json.dumps(audit.after_json or {}, ensure_ascii=False)
        assert "wxid_abcd1234" not in json.dumps(audit.after_json or {}, ensure_ascii=False)
    finally:
        db.close()
