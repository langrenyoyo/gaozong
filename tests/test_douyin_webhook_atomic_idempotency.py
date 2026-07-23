"""抖音 Webhook 原子幂等测试（R2）。

覆盖 A1-A14 验收矩阵：
- PostgreSQL/SQLite 占位语句合同
- 首次/重复/并发/副作用次数/非线索事件/异常回滚/商户隔离
- 9000/9202/混合入口各 20 路线程并发
- 嵌套提交消除验证
- 真实 BackgroundTasks 调度
- 外层回滚结构化日志
- 非空 lead_id 继承
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base
from app.models import (
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinWebhookEvent,
    ReplyCheck,
    SalesStaff,
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


def _make_payload(*, event="im_receive_msg", from_user_id="wh_concurrent_001", text="手机 13800000001", account="test_account_atomic"):
    """构造标准 im_receive_msg payload。"""
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": account,
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


def _setup_account_and_staff(session_factory, *, account="test_account_atomic", merchant="merchant_atomic", tenant="tenant_atomic"):
    """预置企业号绑定和活跃销售。"""
    db = session_factory()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id=account,
            merchant_id=merchant, tenant_id=tenant, bind_status=1,
        ))
        db.add(SalesStaff(
            name="测试销售", status="active", merchant_id=merchant,
            wechat_nickname="测试微信", enable_lead_assignment=True,
        ))
        db.commit()
    finally:
        db.close()


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
    finally:
        db.close()


# ========== A4: 顺序重复事件 ==========


def test_sequential_duplicate_loses_claim(concurrent_database):
    """A4：顺序重复事件竞争失败。"""
    engine, Session = concurrent_database
    db = Session()
    try:
        first = claim_webhook_event(db, values=_claim_values())
        db.commit()
        assert first.won is True

        second = claim_webhook_event(db, values=_claim_values())
        db.commit()
        assert second.won is False
    finally:
        db.close()


# ========== A5: 9000 本地 20 路并发 ==========


def test_local_twenty_concurrent_one_valid_nineteen_duplicate(concurrent_database):
    """A5：9000 本地 20 路并发：1 条有效事件、19 条重复审计事件、1 条线索。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
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
    assert all(err is None for err in errors), f"Errors: {[e for e in errors if e]}"
    assert sum(r["is_duplicate"] is False for r in results) == 1
    assert sum(r["is_duplicate"] is True for r in results) == 19

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
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
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

    results, errors = _run_twenty_workers(worker)
    assert all(err is None for err in errors)
    assert call_count["n"] == 1


# ========== A7: 9202 internal 20 路并发 ==========


def test_internal_twenty_concurrent_one_valid_nineteen_duplicate(concurrent_database):
    """A7：9202 internal 20 路并发（委托同一处理核心）。"""
    from apps.leads.webhook_events import process_internal_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

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
    assert all(err is None for err in errors)
    assert sum(r["is_duplicate"] is False for r in results) == 1
    assert sum(r["is_duplicate"] is True for r in results) == 19

    db = Session()
    try:
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).count() == 1
        assert db.query(DouyinWebhookEvent).filter_by(is_duplicate=True).count() == 19
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


# ========== A8: 真实 BackgroundTasks 调度 ==========


def test_auto_reply_schedule_once_for_winner_and_zero_for_duplicate():
    """A8：使用真实 BackgroundTasks 验证首次一次、重复零次。"""
    from app.routers.integrations import maybe_schedule_ai_auto_reply
    winner_tasks = BackgroundTasks()
    maybe_schedule_ai_auto_reply(
        background_tasks=winner_tasks, event_id=101,
        payload={"event": "im_receive_msg", "to_user_id": "account"},
        is_duplicate=False, source_path="/douyin/webhook",
    )
    assert len(winner_tasks.tasks) == 1
    assert winner_tasks.tasks[0].args == (101,)

    duplicate_tasks = BackgroundTasks()
    maybe_schedule_ai_auto_reply(
        background_tasks=duplicate_tasks, event_id=102,
        payload={"event": "im_receive_msg", "to_user_id": "account"},
        is_duplicate=True, source_path="/douyin/webhook",
    )
    assert duplicate_tasks.tasks == []


# ========== A8b: internal 重复不回退本地处理 ==========


def test_internal_duplicate_does_not_fallback_to_local():
    """A8b：internal 返回重复时不回退本地处理。"""
    from app.routers.integrations import _process_webhook_with_internal
    from app import config as app_config
    from packages.clients.leads_client import LeadsClient, LeadsClientError

    fake_result = {
        "code": 0, "msg": "success", "event_id": 999,
        "lead_id": 42, "is_new_lead": False,
        "is_duplicate": True, "lead_action": "duplicate_event",
    }

    class FakeClient:
        @classmethod
        def from_env(cls):
            return cls()
        def create_internal_webhook_event(self, **kwargs):
            return fake_result

    with patch.object(LeadsClient, "from_env", FakeClient.from_env), \
         patch("app.routers.integrations._process_webhook_locally", side_effect=AssertionError("不得回退本地处理")), \
         patch.object(app_config, "LEADS_WEBHOOK_FALLBACK_LOCAL", True):
        result = _process_webhook_with_internal(
            db=None, payload={"event": "im_receive_msg"},
            source_path="/test",
        )
    assert result["is_duplicate"] is True


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
    assert sum(r["is_duplicate"] is False for r in results) == 1

    db = Session()
    try:
        assert db.query(DouyinLead).count() == 0
    finally:
        db.close()


# ========== A10: 占位后业务异常回滚（真实边界）==========


def test_local_boundary_rolls_back_after_dispatch_side_effect_failure(concurrent_database):
    """A10：9000 外层请求边界回滚：派单失败后事件、线索、ReplyCheck 均不存在。"""
    from app.routers.integrations import _process_webhook_locally
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    try:
        with patch(
            "app.services.assign_service.auto_assign_next",
            side_effect=RuntimeError("forced dispatch failure"),
        ):
            with pytest.raises(RuntimeError):
                _process_webhook_locally(db, payload)
    finally:
        db.close()

    # 用新 Session 断言数据库整体回滚
    db2 = Session()
    try:
        assert db2.query(DouyinWebhookEvent).count() == 0
        assert db2.query(DouyinLead).count() == 0
        assert db2.query(ReplyCheck).count() == 0
    finally:
        db2.close()


# ========== A10b: 9202 外层回滚 ==========


def test_internal_boundary_rolls_back_after_business_failure(concurrent_database):
    """A10b：9202 外层请求边界回滚。"""
    from apps.leads.services import create_internal_webhook_event
    from apps.leads.schemas import InternalWebhookEventRequest
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    try:
        with patch(
            "app.services.assign_service.auto_assign_next",
            side_effect=RuntimeError("forced failure"),
        ):
            with pytest.raises(RuntimeError):
                create_internal_webhook_event(db, InternalWebhookEventRequest(
                    payload=payload, signature_verified=True,
                    source_path="/test", gateway_app_env="development",
                ))
    finally:
        db.close()

    db2 = Session()
    try:
        assert db2.query(DouyinWebhookEvent).count() == 0
        assert db2.query(DouyinLead).count() == 0
    finally:
        db2.close()


# ========== A10c: 外层回滚日志 ==========


def test_local_boundary_rollback_logs_stage_and_failure_stage(concurrent_database, caplog):
    """A10c：9000 外层回滚日志含 stage=local_process failure_stage=transaction_failed。"""
    import logging
    from app.routers.integrations import _process_webhook_locally
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    try:
        with patch(
            "app.services.assign_service.auto_assign_next",
            side_effect=RuntimeError("forced"),
        ):
            with caplog.at_level(logging.ERROR, logger="integrations_router"):
                with pytest.raises(RuntimeError):
                    _process_webhook_locally(db, payload)
    finally:
        db.close()

    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "stage=local_process" in log_text
    assert "failure_stage=transaction_failed" in log_text


# ========== A10d: 派单路径不提交（无嵌套 commit）==========


def test_webhook_dispatch_path_does_not_commit_before_request_boundary(concurrent_database):
    """A10d：派单路径在请求边界前不调用 commit。"""
    from app.integrations.douyin_webhook import process_webhook_event
    from unittest.mock import MagicMock
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    commit_count = {"n": 0}
    original_commit = db.commit
    def _counting_commit():
        commit_count["n"] += 1
        return original_commit()
    db.commit = _counting_commit

    try:
        process_webhook_event(db, payload)
        # process_webhook_event 内部不应 commit；commit 由请求边界调用
        assert commit_count["n"] == 0, f"process_webhook_event 内部调用了 commit {commit_count['n']} 次"
    finally:
        db.commit = original_commit
        db.rollback()


# ========== A10e: 人工接管路径不提交 ==========


def test_webhook_takeover_path_does_not_commit_before_request_boundary(concurrent_database):
    """A10e：人工接管路径在请求边界前不调用 commit。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload(event="im_send_msg", from_user_id="test_account_atomic")

    db = Session()
    commit_count = {"n": 0}
    original_commit = db.commit
    def _counting_commit():
        commit_count["n"] += 1
        return original_commit()
    db.commit = _counting_commit

    try:
        process_webhook_event(db, payload)
        assert commit_count["n"] == 0, f"process_webhook_event 内部调用了 commit {commit_count['n']} 次"
    finally:
        db.commit = original_commit
        db.rollback()


# ========== A11: 商户隔离回归 ==========


def test_merchant_scope_preserved_in_duplicate(concurrent_database):
    """A11：重复事件继承原事件商户归属，不重新推测。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db1 = Session()
    try:
        result1 = process_webhook_event(db1, payload)
        db1.commit()
        assert result1["is_duplicate"] is False
    finally:
        db1.close()

    db2 = Session()
    try:
        result2 = process_webhook_event(db2, payload)
        db2.commit()
        assert result2["is_duplicate"] is True
        original = db2.query(DouyinWebhookEvent).filter_by(is_duplicate=False).first()
        duplicate = db2.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert original.merchant_id == duplicate.merchant_id
        assert original.tenant_id == duplicate.tenant_id
    finally:
        db2.close()


# ========== A12: 不支持方言显式失败 ==========


def test_unsupported_dialect_raises():
    """A12：不支持的数据库方言显式失败。"""
    with pytest.raises(RuntimeError, match="不支持 webhook 原子幂等的数据库方言"):
        build_webhook_claim_statement("mysql", _claim_values())


# ========== A13: 混合 9000/9202 入口 20 路并发 ==========


def test_mixed_local_internal_twenty_concurrent_is_winner_independent(concurrent_database):
    """A13：同一事件混合进入 9000/9202，20 路竞争结果不依赖哪个入口胜出。"""
    from app.integrations.douyin_webhook import process_webhook_event
    from apps.leads.webhook_events import process_internal_webhook_event
    from app.integrations import douyin_webhook as dw_module

    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    barrier = threading.Barrier(20)
    results = [None] * 20
    errors = [None] * 20
    dispatch_count = {"n": 0}
    lock = threading.Lock()
    original = dw_module._dispatch_lead_after_create

    def _counting_dispatch(*args, **kwargs):
        with lock:
            dispatch_count["n"] += 1
        return original(*args, **kwargs)

    def worker(index):
        try:
            barrier.wait(timeout=10)
            db = Session()
            try:
                handler = process_webhook_event if index < 10 else process_internal_webhook_event
                with patch.object(dw_module, "_dispatch_lead_after_create", _counting_dispatch):
                    result = handler(db, payload)
                    db.commit()
                    results[index] = result
            except Exception as exc:
                db.rollback()
                errors[index] = exc
            finally:
                db.close()
        except Exception as exc:
            errors[index] = exc

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        for f in futures:
            f.result(timeout=60)

    assert all(err is None for err in errors), f"Errors: {[e for e in errors if e]}"
    assert sum(r["is_duplicate"] is False for r in results) == 1
    assert sum(r["is_duplicate"] is True for r in results) == 19
    assert dispatch_count["n"] == 1

    db = Session()
    try:
        valid_event = db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        assert valid_event.merchant_id == "merchant_atomic"
        assert valid_event.tenant_id == "tenant_atomic"
        assert valid_event.lead_id is not None
        lead_ids = {r["lead_id"] for r in results}
        assert lead_ids == {valid_event.lead_id}
    finally:
        db.close()


# ========== A13b: 入口胜负顺序 ==========


def test_internal_winner_then_local_duplicate_consistent(concurrent_database):
    """A13b：9202 先胜出，9000 重复，结果一致。"""
    from app.integrations.douyin_webhook import process_webhook_event
    from apps.leads.webhook_events import process_internal_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db1 = Session()
    try:
        r1 = process_internal_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["is_duplicate"] is False

    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True
    assert r2["lead_id"] == r1["lead_id"]


def test_local_winner_then_internal_duplicate_consistent(concurrent_database):
    """A13c：9000 先胜出，9202 重复，结果一致。"""
    from app.integrations.douyin_webhook import process_webhook_event
    from apps.leads.webhook_events import process_internal_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["is_duplicate"] is False

    db2 = Session()
    try:
        r2 = process_internal_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True
    assert r2["lead_id"] == r1["lead_id"]


# ========== A14: 重复响应继承非空 lead_id ==========


def test_duplicate_results_inherit_non_null_lead_and_scope(concurrent_database):
    """A14：存在活跃销售时，重复审计响应继承非空 lead_id、merchant_id、tenant_id。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    # 首次处理创建线索
    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["lead_id"] is not None

    # 重复处理继承非空
    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["lead_id"] == r1["lead_id"]
    assert r2["lead_id"] is not None

    # 重复审计行也继承
    db3 = Session()
    try:
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert dup is not None
        assert dup.lead_id == r1["lead_id"]
        assert dup.merchant_id == "merchant_atomic"
        assert dup.tenant_id == "tenant_atomic"
    finally:
        db3.close()
