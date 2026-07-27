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
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    _JSONStringJSONB,
)
from app.services.douyin_webhook_idempotency_service import claim_webhook_event


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
