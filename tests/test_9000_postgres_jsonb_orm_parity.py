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
    return _load_worker_module()._validate_smoke_database_url(raw)


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
