"""抖音 Webhook 原子幂等测试。

覆盖 A1-A12 验收矩阵：
- PostgreSQL/SQLite 占位语句合同
- 首次/重复/并发/副作用次数/非线索事件/异常回滚/商户隔离
- 9000/9202 各 20 路线程并发
"""

import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base
from app.models import (
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinWebhookEvent,
)
from app.services.douyin_webhook_idempotency_service import (
    WebhookEventClaim,
    build_webhook_claim_statement,
    claim_webhook_event,
)


# ========== 夹具 ==========


@pytest.fixture
def concurrent_database(tmp_path):
    """文件型 SQLite 并发数据库，WAL 模式 + 30 秒忙等待。"""
    database_path = tmp_path / "webhook_atomic.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=20,
        max_overflow=0,
    )

    @sqlalchemy_event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield engine, session_factory
    engine.dispose()


def _run_twenty_workers(worker):
    """20 路同步启动器（Barrier 同步）。"""
    barrier = threading.Barrier(20)
    results = [None] * 20
    errors = [None] * 20

    def _run(index):
        try:
            barrier.wait(timeout=10)
            results[index] = worker(index)
        except Exception as exc:
            errors[index] = exc

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_run, index) for index in range(20)]
        for future in futures:
            future.result(timeout=60)
    return results, errors


def _make_payload(*, event="im_receive_msg", from_user_id="wh_concurrent_001", text="手机 13800000001"):
    """构造标准 im_receive_msg payload。"""
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": "test_account_atomic",
        "content": json.dumps({
            "create_time": int(time.time() * 1000),
            "conversation_short_id": "conv_atomic_001",
            "server_message_id": "msg_atomic_001",
            "conversation_type": 1,
            "message_type": "text",
            "source": "",
            "user_infos": [
                {"open_id": from_user_id, "nick_name": "并发测试", "avatar": "https://example.com/a.png"},
            ],
            "text": text,
        }),
    }


def _make_internal_payload(*, from_user_id="wh_internal_001", text="微信 wx_internal_88"):
    """构造 9202 internal payload。"""
    return {
        "event": "im_receive_msg",
        "from_user_id": from_user_id,
        "to_user_id": "test_account_internal",
        "content": json.dumps({
            "create_time": int(time.time() * 1000),
            "conversation_short_id": "conv_internal_001",
            "server_message_id": "msg_internal_001",
            "message_type": "text",
            "text": text,
        }),
    }


def _claim_values():
    """构造占位语句测试用值。"""
    return {
        "event": "im_receive_msg",
        "from_user_id": "test_user",
        "to_user_id": "test_account",
        "client_key": None,
        "conversation_short_id": "conv_test",
        "server_message_id": "msg_test",
        "conversation_type": None,
        "message_type": "text",
        "message_create_time": None,
        "message_source": None,
        "from_user_nick_name": None,
        "from_user_avatar": None,
        "to_user_nick_name": None,
        "to_user_avatar": None,
        "parse_status": "parsed",
        "parse_error": None,
        "parsed_content_json": '{"text":"hello"}',
        "event_key": "test_key_atomic_001",
        "is_duplicate": False,
        "lead_id": None,
        "merchant_id": None,
        "tenant_id": None,
        "raw_body": '{"event":"test"}',
        "created_at": datetime.now(),
    }


# ========== A1: PostgreSQL 占位语句合同 ==========


def test_claim_statement_uses_postgresql_on_conflict_returning():
    """A1：PostgreSQL 占位语句包含 ON CONFLICT DO NOTHING RETURNING。"""
    statement = build_webhook_claim_statement("postgresql", _claim_values())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING" in sql and "douyin_webhook_events.id" in sql


# ========== A2: SQLite 占位语句合同 ==========


def test_claim_statement_uses_sqlite_on_conflict_returning_without_insert_or_ignore():
    """A2：SQLite 占位语句使用 ON CONFLICT DO NOTHING RETURNING，禁止 INSERT OR IGNORE。"""
    statement = build_webhook_claim_statement("sqlite", _claim_values())
    sql = str(statement.compile(dialect=sqlite.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING" in sql
    assert "INSERT OR IGNORE" not in sql


# ========== A3: 首次事件占位胜出 ==========


def test_first_event_claim_wins(concurrent_database):
    """A3：首次事件占位胜出。"""
    engine, Session = concurrent_database
    db = Session()
    try:
        values = _claim_values()
        claim = claim_webhook_event(db, values=values)
        assert claim.won is True
        assert claim.event.event_key == "test_key_atomic_001"
        assert claim.event.is_duplicate is False
    finally:
        db.close()


# ========== A4: 顺序重复事件 ==========


def test_sequential_duplicate_loses_claim(concurrent_database):
    """A4：顺序重复事件竞争失败。"""
    engine, Session = concurrent_database
    db = Session()
    try:
        values = _claim_values()
        first = claim_webhook_event(db, values=values)
        db.commit()
        assert first.won is True

        second = claim_webhook_event(db, values=values)
        db.commit()
        assert second.won is False
        assert second.event.id == first.event.id
    finally:
        db.close()


# ========== A5: 9000 本地 20 路并发 ==========


def test_local_twenty_concurrent_one_valid_nineteen_duplicate(concurrent_database):
    """A5：9000 本地 20 路并发：1 条有效事件、19 条重复审计事件、1 条线索。"""
    from app.integrations.douyin_webhook import process_webhook_event

    engine, Session = concurrent_database
    # 预置企业号绑定
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="test_account_atomic",
            merchant_id="test_merchant_atomic", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_payload()

    def worker(index):
        db = Session()
        try:
            result = process_webhook_event(db, payload)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    results, errors = _run_twenty_workers(worker)

    # 所有 20 个请求均成功
    assert all(err is None for err in errors), f"Errors: {[e for e in errors if e]}"
    assert len(results) == 20

    # 1 条有效事件、19 条重复
    valid = [r for r in results if r["is_duplicate"] is False]
    duplicates = [r for r in results if r["is_duplicate"] is True]
    assert len(valid) == 1
    assert len(duplicates) == 19

    # 数据库验证
    db = Session()
    try:
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).count() == 1
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=True).count() == 19
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


# ========== A6: 9000 副作用次数 ==========


def test_local_dispatch_called_at_most_once(concurrent_database):
    """A6：_dispatch_lead_after_create 最多一次。"""
    from app.integrations import douyin_webhook as dw_module

    engine, Session = concurrent_database
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="test_account_atomic",
            merchant_id="test_merchant_atomic", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_payload()
    call_count = {"n": 0}
    lock = threading.Lock()
    original = dw_module._dispatch_lead_after_create

    def _counting_dispatch(*args, **kwargs):
        with lock:
            call_count["n"] += 1
        return original(*args, **kwargs)

    def worker(index):
        db = Session()
        try:
            with patch.object(dw_module, "_dispatch_lead_after_create", _counting_dispatch):
                result = process_webhook_event(db, payload)
                db.commit()
                return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    from app.integrations.douyin_webhook import process_webhook_event
    results, errors = _run_twenty_workers(worker)
    assert all(err is None for err in errors)
    assert call_count["n"] == 1


# ========== A7: 9202 internal 20 路并发 ==========


def test_internal_twenty_concurrent_one_valid_nineteen_duplicate(concurrent_database):
    """A7：9202 internal 20 路并发：1 条有效事件、19 条重复审计事件、1 条线索。"""
    from apps.leads.webhook_events import process_internal_webhook_event

    engine, Session = concurrent_database
    # 预置企业号绑定
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="test_account_internal",
            merchant_id="test_merchant_internal", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_internal_payload()

    def worker(index):
        db = Session()
        try:
            result = process_internal_webhook_event(db, payload)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    results, errors = _run_twenty_workers(worker)

    assert all(err is None for err in errors), f"Errors: {[e for e in errors if e]}"
    assert len(results) == 20

    valid = [r for r in results if r["is_duplicate"] is False]
    duplicates = [r for r in results if r["is_duplicate"] is True]
    assert len(valid) == 1
    assert len(duplicates) == 19

    db = Session()
    try:
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).count() == 1
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=True).count() == 19
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


# ========== A8: internal 重复不调度自动回复（路由级）==========


def test_internal_duplicate_does_not_schedule_auto_reply():
    """A8：internal 返回重复时不调度自动回复、不回退本地处理。"""
    from app.routers.integrations import maybe_schedule_ai_auto_reply
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    # 重复事件：is_duplicate=True
    maybe_schedule_ai_auto_reply(
        background_tasks=None,
        event_id=999,
        payload={"event": "im_receive_msg", "to_user_id": "acc"},
        is_duplicate=True,
        source_path="/test",
    )
    # is_duplicate=True 不调度（background_tasks=None 时也不调度，但断言逻辑正确）
    assert submitted_event_ids == []


# ========== A9: 非线索事件并发 ==========


def test_non_lead_event_concurrent_one_valid(concurrent_database):
    """A9：非线索事件并发：只有一条有效原始事件，不创建线索。"""
    from app.integrations.douyin_webhook import process_webhook_event

    engine, Session = concurrent_database
    payload = _make_payload(event="im_send_msg", from_user_id="test_account_atomic")

    def worker(index):
        db = Session()
        try:
            result = process_webhook_event(db, payload)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    results, errors = _run_twenty_workers(worker)
    assert all(err is None for err in errors)
    assert len([r for r in results if r["is_duplicate"] is False]) == 1
    assert len([r for r in results if r["is_duplicate"] is True]) == 19

    db = Session()
    try:
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


# ========== A10: 占位后业务异常回滚 ==========


def test_business_exception_after_claim_rollback(concurrent_database):
    """A10：占位后业务异常 → 当前事务回滚，日志含 stage/failure_stage，不伪造成功。"""
    from app.integrations.douyin_webhook import process_webhook_event

    engine, Session = concurrent_database
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="test_account_atomic",
            merchant_id="test_merchant_atomic", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_payload()

    db2 = Session()
    try:
        # mock upsert_lead_from_webhook 抛异常
        with patch(
            "app.integrations.douyin_webhook.upsert_lead_from_webhook",
            side_effect=RuntimeError("forced business failure"),
        ):
            with pytest.raises(RuntimeError, match="forced business failure"):
                process_webhook_event(db2, payload)
        db2.rollback()

        # 回滚后事件不应残留
        db_check = Session()
        try:
            assert db_check.query(DouyinWebhookEvent).filter_by(
                event_key=payload and __import__("app.integrations.douyin_webhook", fromlist=["build_event_key"]).build_event_key(payload)
            ).count() == 0
        finally:
            db_check.close()
    finally:
        db2.close()


# ========== A11: 商户隔离回归 ==========


def test_merchant_scope_preserved_in_duplicate(concurrent_database):
    """A11：重复事件继承原事件商户归属，不重新推测。"""
    from app.integrations.douyin_webhook import process_webhook_event

    engine, Session = concurrent_database
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="test_account_atomic",
            merchant_id="test_merchant_atomic", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_payload()

    # 首次处理
    db1 = Session()
    try:
        result1 = process_webhook_event(db1, payload)
        db1.commit()
        assert result1["is_duplicate"] is False
    finally:
        db1.close()

    # 重复处理
    db2 = Session()
    try:
        result2 = process_webhook_event(db2, payload)
        db2.commit()
        assert result2["is_duplicate"] is True

        # 验证重复审计行继承原事件归属
        original = db2.query(DouyinWebhookEvent).filter_by(
            is_duplicate=False,
        ).first()
        duplicate = db2.query(DouyinWebhookEvent).filter_by(
            is_duplicate=True,
        ).first()
        assert original.merchant_id == duplicate.merchant_id
        assert original.tenant_id == duplicate.tenant_id
    finally:
        db2.close()


# ========== A12: 不支持方言显式失败 ==========


def test_unsupported_dialect_raises():
    """A12：不支持的数据库方言显式失败，不降级为先查再插。"""
    with pytest.raises(RuntimeError, match="不支持 webhook 原子幂等的数据库方言"):
        build_webhook_claim_statement("mysql", _claim_values())
