"""9000 PostgreSQL JSONB / ORM 一致性首批返修测试。"""

import importlib.util
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

from app.models import (
    AiAutoReplyRun,
    AiReplyDecisionLog,
    DouyinAuthorizedAccount,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    _JSONStringJSONB,
)
from app.services.ai_reply_decision_log_query_service import (
    AiReplyDecisionLogQuery,
    list_ai_reply_decision_logs,
)
from app.services.douyin_merchant_isolation import require_customer_open_id_for_merchant
from app.services.douyin_webhook_idempotency_service import claim_webhook_event
from app.services.douyin_workbench_conversation_service import list_conversation_messages
from app.services.webhook_event_service import WebhookEventFilters, list_webhook_events


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tests" / "helpers" / "outbox_restart_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("jsonb_parity_worker_contract", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pg_url() -> str:
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    # 测试自身必须额外限制 URL 边界，不复用 worker 的宽松校验器
    parsed = make_url(raw)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail(f"SMOKE_DATABASE_URL 必须使用 postgresql+psycopg，实际: {parsed.drivername}")
    if parsed.host not in ("127.0.0.1", "localhost"):
        pytest.fail(f"SMOKE_DATABASE_URL host 必须为 127.0.0.1 或 localhost，实际: {parsed.host}")
    if parsed.port != 5432:
        pytest.fail(f"SMOKE_DATABASE_URL port 必须为 5432，实际: {parsed.port}")
    if parsed.database != "auto_wechat_outbox_test":
        pytest.fail(f"SMOKE_DATABASE_URL database 必须为 auto_wechat_outbox_test，实际: {parsed.database}")
    if parsed.query:
        pytest.fail("SMOKE_DATABASE_URL 禁止 query")
    if "#" in raw:
        pytest.fail("SMOKE_DATABASE_URL 禁止 fragment")
    return raw


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_pg_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
    yield engine
    engine.dispose()


def _namespace() -> str:
    return f"jsonb_parity_{uuid.uuid4().hex}"


def _cleanup_namespace(engine, namespace: str) -> None:
    prefix = f"{namespace}%"
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM douyin_private_message_sends "
                "WHERE conversation_short_id LIKE :prefix OR decision_log_id IN "
                "(SELECT id FROM ai_reply_decision_logs WHERE merchant_id = :namespace)"
            ),
            {"prefix": prefix, "namespace": namespace},
        )
        conn.execute(
            text("DELETE FROM ai_reply_decision_logs WHERE merchant_id = :namespace"),
            {"namespace": namespace},
        )
        conn.execute(
            text("DELETE FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
            {"prefix": prefix},
        )
        conn.execute(
            text("DELETE FROM douyin_authorized_accounts WHERE open_id LIKE :prefix"),
            {"prefix": prefix},
        )


@pytest.fixture
def pg_case(pg_engine):
    namespace = _namespace()
    session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    db = session_factory()
    try:
        yield db, namespace, session_factory
    finally:
        db.rollback()
        db.close()
        _cleanup_namespace(pg_engine, namespace)
        with pg_engine.connect() as conn:
            remaining = conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM douyin_private_message_sends "
                    " WHERE conversation_short_id LIKE :prefix), "
                    "(SELECT count(*) FROM ai_reply_decision_logs "
                    " WHERE merchant_id = :namespace), "
                    "(SELECT count(*) FROM douyin_webhook_events "
                    " WHERE event_key LIKE :prefix), "
                    "(SELECT count(*) FROM douyin_authorized_accounts "
                    " WHERE open_id LIKE :prefix)"
                ),
                {"prefix": f"{namespace}%", "namespace": namespace},
            ).one()
        assert tuple(remaining) == (0, 0, 0, 0)


def _claim_values(namespace: str, suffix: str = "event") -> dict:
    content = {
        "conversation_short_id": f"{namespace}_conversation",
        "server_message_id": f"{namespace}_message",
        "message_type": "text",
        "text": "JSONB 一致性测试",
    }
    payload = {
        "event": "im_receive_msg",
        "from_user_id": f"{namespace}_customer",
        "to_user_id": f"{namespace}_account",
        "content": json.dumps(content, ensure_ascii=False),
    }
    return {
        "event": payload["event"],
        "from_user_id": payload["from_user_id"],
        "to_user_id": payload["to_user_id"],
        "conversation_short_id": content["conversation_short_id"],
        "server_message_id": content["server_message_id"],
        "parsed_content_json": json.dumps(content, ensure_ascii=False),
        "event_key": f"{namespace}_{suffix}",
        "is_duplicate": False,
        "merchant_id": namespace,
        "tenant_id": f"{namespace}_tenant",
        "raw_body": json.dumps(payload, ensure_ascii=False),
    }


def test_j4_postgres_orm_writes_and_reads_webhook_json_strings(pg_case, pg_engine):
    db, namespace, _ = pg_case
    raw_body = json.dumps({"event": "im_receive_msg", "source": "orm"}, ensure_ascii=False)
    parsed_content = json.dumps({"message_type": "text", "text": "ORM 写入"}, ensure_ascii=False)
    event = DouyinWebhookEvent(
        event="im_receive_msg",
        event_key=f"{namespace}_orm",
        is_duplicate=False,
        raw_body=raw_body,
        parsed_content_json=parsed_content,
        merchant_id=namespace,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    assert json.loads(event.raw_body)["source"] == "orm"
    assert json.loads(event.parsed_content_json)["text"] == "ORM 写入"
    with pg_engine.connect() as conn:
        types = conn.execute(
            text(
                "SELECT jsonb_typeof(raw_body), jsonb_typeof(parsed_content_json) "
                "FROM douyin_webhook_events WHERE id = :event_id"
            ),
            {"event_id": event.id},
        ).one()
    assert tuple(types) == ("object", "object")


def test_j5_j6_postgres_webhook_claim_stores_objects_not_string_scalars(pg_case, pg_engine):
    db, namespace, _ = pg_case
    claim = claim_webhook_event(db, values=_claim_values(namespace))
    assert claim.won is True
    db.commit()

    assert isinstance(claim.event.raw_body, str)
    assert isinstance(claim.event.parsed_content_json, str)
    assert json.loads(claim.event.raw_body)["event"] == "im_receive_msg"
    assert json.loads(claim.event.parsed_content_json)["message_type"] == "text"

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT jsonb_typeof(raw_body), jsonb_typeof(parsed_content_json) "
                "FROM douyin_webhook_events WHERE event_key = :event_key"
            ),
            {"event_key": f"{namespace}_event"},
        ).one()
    assert tuple(row) == ("object", "object")


def test_j7_postgres_twenty_way_claim_has_one_winner_for_ten_rounds(pg_case):
    _, namespace, session_factory = pg_case

    for round_no in range(10):
        values = _claim_values(namespace, suffix=f"race_{round_no}")
        barrier = Barrier(20)

        def worker() -> bool:
            db = session_factory()
            try:
                barrier.wait(timeout=10)
                claim = claim_webhook_event(db, values=values)
                db.commit()
                return claim.won
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=20) as executor:
            winners = list(executor.map(lambda _: worker(), range(20)))

        assert sum(winners) == 1
        verify_db = session_factory()
        try:
            assert (
                verify_db.query(DouyinWebhookEvent)
                .filter(DouyinWebhookEvent.event_key == values["event_key"])
                .count()
            ) == 1
        finally:
            verify_db.close()


JSON_STRING_COLUMNS = (
    (AiAutoReplyRun, "gate_results_json"),
    (DouyinWebhookEvent, "raw_body"),
    (DouyinWebhookEvent, "parsed_content_json"),
    (DouyinPrivateMessageSend, "request_body_json"),
    (DouyinPrivateMessageSend, "response_body_json"),
    (AiReplyDecisionLog, "risk_flags_json"),
    (AiReplyDecisionLog, "tags_json"),
    (AiReplyDecisionLog, "rag_sources_json"),
    (AiReplyDecisionLog, "source_chunks_json"),
    (AiReplyDecisionLog, "allowed_category_keys_json"),
    (AiReplyDecisionLog, "raw_response_json"),
)


@pytest.mark.parametrize(("model", "column_name"), JSON_STRING_COLUMNS)
def test_j1_j2_shared_type_compiles_to_jsonb_and_text(model, column_name):
    column_type = model.__table__.c[column_name].type
    assert isinstance(column_type, _JSONStringJSONB)
    assert str(column_type.compile(dialect=postgresql.dialect())).upper() == "JSONB"
    assert str(column_type.compile(dialect=sqlite.dialect())).upper() == "TEXT"


def test_j3_shared_type_preserves_string_json_contract():
    column_type = _JSONStringJSONB()
    pg = postgresql.dialect()
    sq = sqlite.dialect()

    assert column_type.process_bind_param(None, pg) is None
    assert column_type.process_bind_param(None, sq) is None
    assert column_type.process_bind_param('{"a":1}', pg) == {"a": 1}
    assert column_type.process_bind_param('["x"]', pg) == ["x"]
    assert column_type.process_bind_param('"scalar"', pg) == "scalar"
    assert column_type.process_bind_param('{"a":1}', sq) == '{"a":1}'
    assert json.loads(column_type.process_result_value({"a": 1}, pg)) == {"a": 1}
    assert column_type.process_result_value('{"a":1}', sq) == '{"a":1}'

    with pytest.raises(json.JSONDecodeError):
        column_type.process_bind_param("{bad", pg)

    # JSON 文本 "null"（含前后空白）跨方言统一映射为 SQL NULL（Python None），
    # 消除 PostgreSQL 静默转 NULL 而 SQLite 保留字符串标量的不一致
    for null_text in ("null", "  null  ", "\tnull\n"):
        assert column_type.process_bind_param(null_text, pg) is None
        assert column_type.process_bind_param(null_text, sq) is None


def _seed_account(db, namespace: str) -> None:
    db.add(
        DouyinAuthorizedAccount(
            merchant_id=namespace,
            main_account_id=1,
            open_id=f"{namespace}_account",
            bind_status=1,
            raw_body_json={"source": "jsonb_parity"},
        )
    )
    db.commit()


def test_j11_webhook_and_merchant_filters_cast_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    values = _claim_values(namespace, suffix="filter")
    hidden_customer = f"{namespace}_hidden_customer"
    payload = json.loads(values["raw_body"])
    payload["open_id"] = hidden_customer
    payload["account_open_id"] = f"{namespace}_account"
    values["raw_body"] = json.dumps(payload, ensure_ascii=False)
    values["from_user_id"] = f"{namespace}_other_from"
    values["to_user_id"] = f"{namespace}_other_to"
    claim_webhook_event(db, values=values)
    db.commit()

    result = list_webhook_events(
        db,
        WebhookEventFilters(keyword=hidden_customer),
        super_admin=True,
    )
    assert result["total"] == 1

    require_customer_open_id_for_merchant(
        db,
        merchant_id=namespace,
        customer_open_id=hidden_customer,
    )


def test_j11_workbench_conversation_filter_casts_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    values = _claim_values(namespace, suffix="workbench")
    conversation_key = f"{namespace}_raw_only_conversation"
    parsed = json.loads(values["parsed_content_json"])
    parsed["conversation_short_id"] = conversation_key
    payload = json.loads(values["raw_body"])
    payload["content"] = json.dumps(parsed, ensure_ascii=False)
    values["conversation_short_id"] = None
    values["parsed_content_json"] = json.dumps(parsed, ensure_ascii=False)
    values["raw_body"] = json.dumps(payload, ensure_ascii=False)
    claim_webhook_event(db, values=values)
    db.commit()

    result = list_conversation_messages(
        db,
        conversation_key=conversation_key,
        account_open_id=f"{namespace}_account",
        merchant_id=namespace,
    )
    assert len(result["items"]) == 1


def test_j10_decision_risk_filter_casts_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    decision = AiReplyDecisionLog(
        merchant_id=namespace,
        conversation_id=f"{namespace}_conversation",
        manual_required=1,
        risk_flags_json='["jsonb_risk"]',
    )
    db.add(decision)
    db.flush()
    db.add(
        DouyinPrivateMessageSend(
            main_account_id=1,
            conversation_short_id=f"{namespace}_conversation",
            server_message_id=f"{namespace}_server_message",
            from_user_id=f"{namespace}_account",
            to_user_id=f"{namespace}_customer",
            content="测试",
            status="sent",
            send_source="ai_auto",
            decision_log_id=decision.id,
        )
    )
    db.commit()

    result = list_ai_reply_decision_logs(
        db,
        AiReplyDecisionLogQuery(merchant_id=namespace, risk_flag="jsonb_risk"),
    )
    assert result["total"] == 1


# ========== B1-B8 _IntegerBoolean 合同与真实写入 ==========


INTEGER_BOOLEAN_COLUMNS = (
    (DouyinPrivateMessageSend, "manual_confirmed"),
    (DouyinPrivateMessageSend, "auto_send"),
    (AiReplyDecisionLog, "manual_required"),
    (AiReplyDecisionLog, "llm_used"),
    (AiReplyDecisionLog, "rag_used"),
    (AiReplyDecisionLog, "upstream_auto_send"),
    (AiReplyDecisionLog, "final_auto_send"),
)


@pytest.mark.parametrize(("model", "column_name"), INTEGER_BOOLEAN_COLUMNS)
def test_b1_b4_integer_boolean_compiles_and_attached(model, column_name):
    from app.models import _IntegerBoolean
    column_type = model.__table__.c[column_name].type
    assert isinstance(column_type, _IntegerBoolean)
    assert str(column_type.compile(dialect=postgresql.dialect())).upper() == "BOOLEAN"
    assert str(column_type.compile(dialect=sqlite.dialect())).upper() == "INTEGER"


def test_b2_b3_integer_boolean_bind_contract():
    from app.models import _IntegerBoolean
    col = _IntegerBoolean()
    pg = postgresql.dialect()
    sq = sqlite.dialect()
    # None 保持 NULL
    assert col.process_bind_param(None, pg) is None
    assert col.process_bind_param(None, sq) is None
    # 0/1 双方言
    assert col.process_bind_param(0, pg) is False
    assert col.process_bind_param(1, pg) is True
    assert col.process_bind_param(0, sq) == 0
    assert col.process_bind_param(1, sq) == 1
    # bool 双方言
    assert col.process_bind_param(False, pg) is False
    assert col.process_bind_param(True, pg) is True
    assert col.process_bind_param(False, sq) == 0
    assert col.process_bind_param(True, sq) == 1
    # 读回仍为 0/1
    assert col.process_result_value(True, pg) == 1
    assert col.process_result_value(False, pg) == 0
    assert col.process_result_value(1, sq) == 1
    assert col.process_result_value(0, sq) == 0
    # 非法值明确失败
    for bad in (2, "1", -1):
        with pytest.raises(ValueError):
            col.process_bind_param(bad, pg)
        with pytest.raises(ValueError):
            col.process_bind_param(bad, sq)
    # 读回损坏值（"0"、2、字符串）明确失败，不静默归一
    for bad in ("0", 2, "1", -1, "true"):
        with pytest.raises(ValueError):
            col.process_result_value(bad, pg)
        with pytest.raises(ValueError):
            col.process_result_value(bad, sq)


# ========== Task 5: 真实写入路径与失败边界 ==========


def test_j9_send_service_writes_native_jsonb_without_real_network(pg_case, pg_engine, monkeypatch):
    from datetime import datetime
    from unittest.mock import patch

    from app.services.douyin_private_message_send_service import _send_private_message_with_context

    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    monkeypatch.setattr(
        "app.services.douyin_private_message_send_service.config.DY_MAIN_ACCOUNT_ID",
        1,
    )
    send_context = {
        "conversation_short_id": f"{namespace}_send_conversation",
        "conversation_id": f"{namespace}_send_conversation",
        "server_message_id": f"{namespace}_incoming_message",
        "msg_id": f"{namespace}_incoming_message",
        "account_open_id": f"{namespace}_account",
        "customer_open_id": f"{namespace}_customer",
        "message_create_time": datetime.now(),
        "scene": "im_receive_msg",
    }
    fake_result = {
        "payload": {"code": 0, "data": {"msg_id": f"{namespace}_upstream"}}
    }

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value=fake_result,
    ) as fake_call:
        result = _send_private_message_with_context(
            db,
            content="JSONB 测试回复",
            send_context=send_context,
            manual_confirmed=True,
            auto_send=False,
            send_source="manual",
            operator_id="jsonb_parity_test",
        )

    assert fake_call.call_count == 1
    record = db.get(DouyinPrivateMessageSend, result["record_id"])
    assert json.loads(record.request_body_json)["content"] == "JSONB 测试回复"
    assert json.loads(record.response_body_json)["code"] == 0

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT jsonb_typeof(request_body_json), jsonb_typeof(response_body_json) "
                "FROM douyin_private_message_sends WHERE id = :record_id"
            ),
            {"record_id": record.id},
        ).one()
    assert tuple(row) == ("object", "object")

    # B5/B6：发送流水两列 ORM 读回为严格整数 0/1，PG 列为 BOOLEAN
    assert record.manual_confirmed == 1
    assert record.auto_send == 0
    assert isinstance(record.manual_confirmed, int)
    assert isinstance(record.auto_send, int)
    with pg_engine.connect() as conn:
        types = conn.execute(
            text(
                "SELECT pg_typeof(manual_confirmed)::text, pg_typeof(auto_send)::text "
                "FROM douyin_private_message_sends WHERE id = :record_id"
            ),
            {"record_id": record.id},
        ).one()
    assert tuple(types) == ("boolean", "boolean")


def test_j10_decision_service_preserves_six_string_json_fields(pg_case, pg_engine):
    from app.auth.context import RequestContext
    from app.services.ai_reply_decision_log_service import record_ai_reply_decision

    db, namespace, _ = pg_case
    log_id = record_ai_reply_decision(
        db,
        context=RequestContext(user_id="jsonb-test", merchant_id=namespace),
        conversation_id=f"{namespace}_decision_conversation",
        account_open_id=f"{namespace}_account",
        latest_message="测试消息",
        agent_id="jsonb-agent",
        agent_name="JSONB 智能体",
        allowed_category_keys=["base"],
        upstream_raw_result={"reply_text": "回复", "source": "test"},
        final_result={
            "reply_text": "回复",
            "manual_required": True,
            "risk_flags": ["jsonb_risk"],
            "tags": ["jsonb_tag"],
            "rag_sources": [{"id": "source-1"}],
            "source_chunks": [{"id": "chunk-1"}],
        },
        upstream_auto_send=False,
    )
    assert log_id is not None

    row = db.get(AiReplyDecisionLog, log_id)
    assert json.loads(row.risk_flags_json) == ["jsonb_risk"]
    assert json.loads(row.tags_json) == ["jsonb_tag"]
    assert json.loads(row.rag_sources_json) == [{"id": "source-1"}]
    assert json.loads(row.source_chunks_json) == [{"id": "chunk-1"}]
    assert json.loads(row.allowed_category_keys_json) == ["base"]
    assert json.loads(row.raw_response_json)["source"] == "test"

    with pg_engine.connect() as conn:
        types = conn.execute(
            text(
                "SELECT jsonb_typeof(risk_flags_json), jsonb_typeof(tags_json), "
                "jsonb_typeof(rag_sources_json), jsonb_typeof(source_chunks_json), "
                "jsonb_typeof(allowed_category_keys_json), jsonb_typeof(raw_response_json) "
                "FROM ai_reply_decision_logs WHERE id = :log_id"
            ),
            {"log_id": log_id},
        ).one()
    assert tuple(types) == ("array", "array", "array", "array", "array", "object")

    # B5/B6：决策日志五列 ORM 读回为严格整数 0/1，PG 列为 BOOLEAN
    assert row.manual_required == 1
    assert row.llm_used == 0
    assert row.rag_used == 0
    assert row.upstream_auto_send == 0
    assert row.final_auto_send == 0
    for field in ("manual_required", "llm_used", "rag_used", "upstream_auto_send", "final_auto_send"):
        value = getattr(row, field)
        assert value in (0, 1), f"{field} 应为 0/1，实际: {value!r}"
        assert isinstance(value, int), f"{field} 应为 int，实际: {type(value)}"
    with pg_engine.connect() as conn:
        bool_types = conn.execute(
            text(
                "SELECT pg_typeof(manual_required)::text, pg_typeof(llm_used)::text, "
                "pg_typeof(rag_used)::text, pg_typeof(upstream_auto_send)::text, "
                "pg_typeof(final_auto_send)::text FROM ai_reply_decision_logs WHERE id = :log_id"
            ),
            {"log_id": log_id},
        ).one()
    assert tuple(bool_types) == ("boolean", "boolean", "boolean", "boolean", "boolean")

    # B7：manual_required/llm_used/rag_used 查询筛选准确命中
    from app.models import AiReplyDecisionLog as _Log
    assert db.query(_Log).filter(_Log.manual_required == 1).count() == 1
    assert db.query(_Log).filter(_Log.llm_used == 0).count() == 1
    assert db.query(_Log).filter(_Log.rag_used == 0).count() == 1
    assert db.query(_Log).filter(_Log.manual_required == 0).count() == 0
    assert db.query(_Log).filter(_Log.llm_used == 1).count() == 0


def test_j3_postgres_invalid_json_fails_and_none_stays_sql_null(pg_case, pg_engine):
    from sqlalchemy.exc import StatementError

    db, namespace, _ = pg_case
    invalid = DouyinPrivateMessageSend(
        main_account_id=1,
        conversation_short_id=f"{namespace}_invalid",
        server_message_id=f"{namespace}_invalid_message",
        from_user_id=f"{namespace}_account",
        to_user_id=f"{namespace}_customer",
        content="测试",
        request_body_json="{bad",
    )
    db.add(invalid)
    with pytest.raises(StatementError) as exc_info:
        db.commit()
    assert isinstance(exc_info.value.orig, json.JSONDecodeError)
    db.rollback()

    valid = DouyinPrivateMessageSend(
        main_account_id=1,
        conversation_short_id=f"{namespace}_null",
        server_message_id=f"{namespace}_null_message",
        from_user_id=f"{namespace}_account",
        to_user_id=f"{namespace}_customer",
        content="测试",
        request_body_json=None,
        response_body_json=None,
    )
    db.add(valid)
    db.commit()

    with pg_engine.connect() as conn:
        values = conn.execute(
            text(
                "SELECT request_body_json IS NULL, response_body_json IS NULL "
                "FROM douyin_private_message_sends WHERE id = :record_id"
            ),
            {"record_id": valid.id},
        ).one()
    assert tuple(values) == (True, True)
