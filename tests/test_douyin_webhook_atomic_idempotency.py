"""抖音 Webhook 原子幂等测试（R3-R1）。

冻结 R3 A1-A14 验收映射：
- A1  SQL 合同（PostgreSQL ON CONFLICT DO NOTHING RETURNING + JSONB CAST）
- A2  派单事务（commit=True 默认提交；commit=False 已 flush 未 commit）
- A3  人工接管事务（commit=True 默认提交；commit=False 已 flush 未 commit）
- A4  派单后回滚（事件+线索+ReplyCheck+LeadFollowupRecord 整体回滚；监视 rollback）
- A5  人工接管后回滚（事件+接管状态整体回滚；监视 rollback）
- A6  9000 20路并发（1 有效、19 重复、1 线索）
- A7  9202 20路并发（同上；有效+重复 merchant_id/tenant_id 与 9000 一致）
- A8  混合 9000/9202 20路竞争（胜负无关；全局 patch 在线程池外）
- A9  重复继承（19 重复返回+审计行全部继承胜出者非空 lead_id 和可信归属）
- A10 调度（BackgroundTasks：首次一次、重复零次）
- A11 两入口日志（9000+9202 外层 rollback 实际调用 + stage/failure_stage）
- A12 归属矩阵（唯一/全空/歧义/无绑定；每项处理两次并断言原事件+重复返回+审计行+线索数）
- A13 顺序重复/非线索事件/入口胜负顺序
- A14 范围检查与完整回归（由全量回归 0 failed 证明）
"""

import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base
from app.models import (
    ConversationAutopilotState,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinWebhookEvent,
    LeadFollowupRecord,
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


@pytest.fixture
def memory_database():
    """内存数据库，用于事务行为测试。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
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


def _spy_rollback(db):
    """为 Session 安装 rollback 计数器，返回 (spy, counter_dict)。"""
    original_rollback = db.rollback
    counter = {"n": 0}

    def _counting_rollback():
        counter["n"] += 1
        return original_rollback()

    db.rollback = _counting_rollback
    return _counting_rollback, counter


# ========== A1: SQL 合同（PostgreSQL）==========


def test_a1_claim_statement_uses_postgresql_on_conflict_returning_with_jsonb_cast():
    """A1：PostgreSQL 占位语句包含 ON CONFLICT DO NOTHING RETURNING，raw_body/parsed_content_json 显式 CAST AS JSONB。"""
    statement = build_webhook_claim_statement("postgresql", _claim_values())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING" in sql and "douyin_webhook_events.id" in sql
    assert "CAST(" in sql and "AS JSONB" in sql


def test_a1_sqlite_no_insert_or_ignore():
    """A1 补充：SQLite 占位语句使用 ON CONFLICT DO NOTHING RETURNING，禁止 INSERT OR IGNORE。"""
    statement = build_webhook_claim_statement("sqlite", _claim_values())
    sql = str(statement.compile(dialect=sqlite.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING" in sql
    assert "INSERT OR IGNORE" not in sql


def test_a1_unsupported_dialect_raises():
    """A1 边界：不支持的方言显式失败。"""
    with pytest.raises(RuntimeError, match="不支持 webhook 原子幂等的数据库方言"):
        build_webhook_claim_statement("mysql", _claim_values())


# ========== A2: 派单事务（commit 参数）==========


def test_a2_assign_default_commit_persists(memory_database):
    """A2：assign_lead 默认 commit=True 直接提交到数据库。"""
    from app.services.assign_service import assign_lead
    engine, Session = memory_database
    db = Session()
    try:
        lead = DouyinLead(
            source="douyin", source_id="a2_test", merchant_id="m_a2",
            status="pending",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        staff = SalesStaff(name="销售a2", status="active", merchant_id="m_a2",
                           enable_lead_assignment=True)
        db.add(staff)
        db.commit()
        db.refresh(staff)
        result = assign_lead(db, lead.id, staff.id)
        assert result.assigned_staff_id == staff.id
        # 默认 commit 后用新 Session 可读
        db2 = Session()
        try:
            assert db2.query(DouyinLead).filter_by(id=lead.id).one().assigned_staff_id == staff.id
        finally:
            db2.close()
    finally:
        db.close()


def test_a2_assign_commit_false_flushes_without_commit(memory_database):
    """A2：auto_assign_next(commit=False) flush 后 lead 在同 Session 可见，但未提交（新 Session 不可见）。"""
    from app.services.assign_service import auto_assign_next
    engine, Session = memory_database
    db = Session()
    try:
        lead = DouyinLead(
            source="douyin", source_id="a2_nocommit", merchant_id="m_a2b",
            status="pending",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        staff = SalesStaff(name="销售a2b", status="active", merchant_id="m_a2b",
                           enable_lead_assignment=True)
        db.add(staff)
        db.commit()
        db.refresh(staff)
        result = auto_assign_next(db, lead.id, commit=False)
        assert result.assigned_staff_id == staff.id
        # flush 后同 Session 可见
        assert db.query(DouyinLead).filter_by(id=lead.id).one().assigned_staff_id == staff.id
        # 未 commit，新 Session 不可见
        db.rollback()
        db2 = Session()
        try:
            assert db2.query(DouyinLead).filter_by(id=lead.id).one().assigned_staff_id is None
        finally:
            db2.close()
    finally:
        db.close()


# ========== A3: 人工接管事务（commit 参数）==========


def test_a3_takeover_default_commit_persists(memory_database):
    """A3：mark_manual_takeover 默认 commit=True 直接提交。"""
    from app.services.conversation_autopilot_state_service import mark_manual_takeover
    engine, Session = memory_database
    db = Session()
    try:
        state = mark_manual_takeover(
            db, merchant_id="m_a3", account_open_id="acc_a3",
            conversation_short_id="conv_a3", customer_open_id="cust_a3",
        )
        assert state.mode == "manual"
        db2 = Session()
        try:
            assert db2.query(ConversationAutopilotState).filter_by(
                merchant_id="m_a3", account_open_id="acc_a3"
            ).one().mode == "manual"
        finally:
            db2.close()
    finally:
        db.close()


def test_a3_takeover_commit_false_flushes_without_commit(memory_database):
    """A3：mark_manual_takeover(commit=False) flush 后同 Session 可见，但未提交。"""
    from app.services.conversation_autopilot_state_service import mark_manual_takeover
    engine, Session = memory_database
    db = Session()
    try:
        state = mark_manual_takeover(
            db, merchant_id="m_a3b", account_open_id="acc_a3b",
            conversation_short_id="conv_a3b", commit=False,
        )
        assert state.mode == "manual"
        # flush 后同 Session 可见
        assert db.query(ConversationAutopilotState).filter_by(
            merchant_id="m_a3b"
        ).one().mode == "manual"
        # 未 commit
        db.rollback()
        db2 = Session()
        try:
            assert db2.query(ConversationAutopilotState).filter_by(
                merchant_id="m_a3b"
            ).count() == 0
        finally:
            db2.close()
    finally:
        db.close()


# ========== A4: 派单后回滚 ==========


def test_a4_dispatch_rolls_back_event_lead_replycheck_followup(concurrent_database):
    """A4：派单后异常 → 外层 rollback 实际调用；新 Session 断言事件/线索/ReplyCheck/
    LeadFollowupRecord 均不存在。"""
    from app.routers.integrations import _process_webhook_locally
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    _, rollback_spy = _spy_rollback(db)
    try:
        with patch(
            "app.integrations.douyin_webhook._post_process_im_send_msg",
            side_effect=RuntimeError("forced after dispatch"),
        ):
            with pytest.raises(RuntimeError, match="forced after dispatch"):
                _process_webhook_locally(db, payload)
    finally:
        db.close()

    # 外层 rollback 实际调用
    assert rollback_spy["n"] >= 1, "外层 rollback 未被调用"

    db2 = Session()
    try:
        assert db2.query(DouyinWebhookEvent).count() == 0
        assert db2.query(DouyinLead).count() == 0
        assert db2.query(ReplyCheck).count() == 0
        assert db2.query(LeadFollowupRecord).count() == 0
    finally:
        db2.close()


# ========== A5: 人工接管后回滚 ==========


def test_a5_takeover_rolls_back_event_and_state(concurrent_database):
    """A5：人工接管写入后异常 → 外层 rollback 实际调用；事件和接管状态整体回滚。"""
    from app.integrations import douyin_webhook as dw_module
    from app.routers.integrations import _process_webhook_locally

    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload(event="im_send_msg", from_user_id="test_account_atomic")
    original_mark = dw_module.mark_manual_takeover

    def _mark_then_fail(*args, **kwargs):
        original_mark(*args, **kwargs)
        raise RuntimeError("forced after takeover")

    db = Session()
    _, rollback_spy = _spy_rollback(db)
    try:
        with patch.object(dw_module, "mark_manual_takeover", _mark_then_fail):
            with pytest.raises(RuntimeError, match="forced after takeover"):
                _process_webhook_locally(db, payload)
    finally:
        db.close()

    assert rollback_spy["n"] >= 1

    db2 = Session()
    try:
        assert db2.query(DouyinWebhookEvent).count() == 0
        assert db2.query(ConversationAutopilotState).count() == 0
    finally:
        db2.close()


# ========== A6: 9000 20路并发 ==========


def test_a6_local_twenty_concurrent(concurrent_database):
    """A6：9000 本地 20 路并发：1 有效、19 重复、1 线索。"""
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


# ========== A7: 9202 20路并发 ==========


def test_a7_internal_twenty_concurrent_with_scope_inheritance(concurrent_database):
    """A7：9202 20路并发（委托同一核心）；有效+重复事件 merchant_id/tenant_id 与 9000 一致。"""
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
        valid = db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        assert valid.merchant_id == "merchant_atomic"
        assert valid.tenant_id == "tenant_atomic"
        dups = db.query(DouyinWebhookEvent).filter_by(is_duplicate=True).all()
        for dup in dups:
            assert dup.merchant_id == valid.merchant_id
            assert dup.tenant_id == valid.tenant_id
        assert db.query(DouyinLead).count() == 1
    finally:
        db.close()


# ========== A8: 混合 9000/9202 20路竞争 ==========


def test_a8_mixed_twenty_concurrent(concurrent_database):
    """A8：同一事件混合 9000/9202，20 路竞争结果不依赖哪个入口胜出（全局 patch 在线程池外）。"""
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

    with patch.object(dw_module, "_dispatch_lead_after_create", _counting_dispatch):
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            for f in futures:
                f.result(timeout=60)

    assert all(err is None for err in errors)
    assert sum(r["is_duplicate"] is False for r in results) == 1
    assert sum(r["is_duplicate"] is True for r in results) == 19
    assert dispatch_count["n"] == 1

    db = Session()
    try:
        valid = db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        assert valid.merchant_id == "merchant_atomic"
        assert valid.tenant_id == "tenant_atomic"
        assert valid.lead_id is not None
        lead_ids = {r["lead_id"] for r in results}
        assert lead_ids == {valid.lead_id}
    finally:
        db.close()


# ========== A9: 重复继承 ==========


def test_a9_all_duplicates_inherit_nonnull_lead_and_scope(concurrent_database):
    """A9：19 个重复返回和 19 条重复审计行全部继承胜出者非空 lead_id 和可信归属。"""
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
    assert all(err is None for err in errors)

    valid_results = [r for r in results if r["is_duplicate"] is False]
    dup_results = [r for r in results if r["is_duplicate"] is True]
    assert len(valid_results) == 1
    assert len(dup_results) == 19

    winner_lead_id = valid_results[0]["lead_id"]
    assert winner_lead_id is not None

    # 19 个重复返回全部继承非空 lead_id
    for dup in dup_results:
        assert dup["lead_id"] == winner_lead_id

    db = Session()
    try:
        valid_event = db.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup_events = db.query(DouyinWebhookEvent).filter_by(is_duplicate=True).all()
        assert len(dup_events) == 19
        for dup_event in dup_events:
            assert dup_event.lead_id == winner_lead_id
            assert dup_event.merchant_id == valid_event.merchant_id
            assert dup_event.tenant_id == valid_event.tenant_id
    finally:
        db.close()


# ========== A10: 调度（BackgroundTasks）==========


def test_a10_schedule_once_for_winner_zero_for_duplicate():
    """A10：真实 BackgroundTasks 验证首次一次、重复零次。"""
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


def test_a10_internal_duplicate_does_not_fallback():
    """A10 补充：internal 返回重复时不回退本地处理。"""
    from app.routers.integrations import _process_webhook_with_internal
    from app import config as app_config
    from packages.clients.leads_client import LeadsClient

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
         patch("app.routers.integrations._process_webhook_locally", side_effect=AssertionError("不得回退")), \
         patch.object(app_config, "LEADS_WEBHOOK_FALLBACK_LOCAL", True):
        result = _process_webhook_with_internal(
            db=None, payload={"event": "im_receive_msg"},
            source_path="/test",
        )
    assert result["is_duplicate"] is True


# ========== A11: 两入口日志 + rollback 监视 ==========


def test_a11_local_boundary_rollback_logs_and_calls_rollback(concurrent_database, caplog):
    """A11a：9000 外层 rollback 实际调用，日志含 stage=local_process failure_stage=transaction_failed。"""
    from app.routers.integrations import _process_webhook_locally
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    _, rollback_spy = _spy_rollback(db)
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

    assert rollback_spy["n"] >= 1
    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "stage=local_process" in log_text
    assert "failure_stage=transaction_failed" in log_text


def test_a11_internal_boundary_rollback_logs_and_calls_rollback(concurrent_database, caplog):
    """A11b：9202 外层 rollback 实际调用，日志含 stage=internal_process failure_stage=transaction_failed。"""
    from apps.leads.services import create_internal_webhook_event
    from apps.leads.schemas import InternalWebhookEventRequest
    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload()

    db = Session()
    _, rollback_spy = _spy_rollback(db)
    try:
        with patch(
            "app.services.assign_service.auto_assign_next",
            side_effect=RuntimeError("forced"),
        ):
            with caplog.at_level(logging.ERROR, logger="leads_internal_webhook_service"):
                with pytest.raises(RuntimeError):
                    create_internal_webhook_event(db, InternalWebhookEventRequest(
                        payload=payload, signature_verified=True,
                        source_path="/test", gateway_app_env="development",
                    ))
    finally:
        db.close()

    assert rollback_spy["n"] >= 1
    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "stage=internal_process" in log_text
    assert "failure_stage=transaction_failed" in log_text


# ========== A11c: 派单/接管路径无嵌套 commit ==========


def test_a11_dispatch_path_no_nested_commit(concurrent_database):
    """A11c：派单路径在请求边界前不调用 commit。"""
    from app.integrations.douyin_webhook import process_webhook_event
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
        assert commit_count["n"] == 0, f"process_webhook_event 内部调用了 commit {commit_count['n']} 次"
    finally:
        db.commit = original_commit
        db.rollback()


def test_a11_takeover_path_no_nested_commit(concurrent_database):
    """A11d：人工接管路径在请求边界前不调用 commit。"""
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
        assert commit_count["n"] == 0
    finally:
        db.commit = original_commit
        db.rollback()


# ========== A12: 归属矩阵 ==========


def test_a12_unique_merchant_tenant_inherited_by_duplicate(concurrent_database):
    """A12a：唯一 merchant+tenant，处理两次：原事件+重复返回+审计行+线索数一致。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session, account="acc_a12a", merchant="m_a12a", tenant="t_a12a")
    payload = _make_payload(account="acc_a12a", text="scope a12a")

    # 第一次
    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["is_duplicate"] is False and r1["lead_id"] is not None

    # 第二次
    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True and r2["lead_id"] == r1["lead_id"]

    db3 = Session()
    try:
        orig = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert orig.merchant_id == "m_a12a" and orig.tenant_id == "t_a12a"
        assert dup.merchant_id == orig.merchant_id and dup.tenant_id == orig.tenant_id
        assert dup.lead_id == orig.lead_id
        assert db3.query(DouyinLead).count() == 1
    finally:
        db3.close()


def test_a12_same_merchant_all_tenant_null(concurrent_database):
    """A12b：同商户 tenant 全空，处理两次：重复审计行 merchant 继承，tenant None。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    _setup_account_and_staff(Session, account="acc_a12b", merchant="m_a12b", tenant=None)
    payload = _make_payload(account="acc_a12b", text="scope a12b")

    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()

    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True

    db3 = Session()
    try:
        orig = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert orig.merchant_id == "m_a12b" and orig.tenant_id is None
        assert dup.merchant_id == "m_a12b" and dup.tenant_id is None
        assert dup.lead_id == orig.lead_id
        assert db3.query(DouyinLead).count() == 1
    finally:
        db3.close()


def test_a12_empty_and_nonempty_tenant_ambiguous(concurrent_database):
    """A12c：tenant 空/非空混杂，处理两次：merchant 写入，tenant None，重复审计行一致。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="acc_a12c",
            merchant_id="m_a12c", tenant_id=None, bind_status=1,
        ))
        db.add(DouyinAuthorizedAccount(
            main_account_id=2, open_id="acc_a12c",
            merchant_id="m_a12c", tenant_id="t_a12c", bind_status=1,
        ))
        db.add(SalesStaff(name="销售c", status="active", merchant_id="m_a12c",
                          wechat_nickname="微信c", enable_lead_assignment=True))
        db.commit()
    finally:
        db.close()

    payload = _make_payload(account="acc_a12c", text="scope a12c")
    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()

    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True and r2["lead_id"] == r1["lead_id"]

    db3 = Session()
    try:
        orig = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert orig.merchant_id == "m_a12c" and orig.tenant_id is None
        assert dup.merchant_id == "m_a12c" and dup.tenant_id is None
        assert db3.query(DouyinLead).count() == 1
    finally:
        db3.close()


def test_a12_empty_and_nonempty_merchant_ambiguous(concurrent_database):
    """A12d：merchant 空/非空混杂，处理两次：merchant_id=None，不创建线索。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    db = Session()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id="acc_a12d",
            merchant_id=None, bind_status=1,
        ))
        db.add(DouyinAuthorizedAccount(
            main_account_id=2, open_id="acc_a12d",
            merchant_id="m_a12d", bind_status=1,
        ))
        db.commit()
    finally:
        db.close()

    payload = _make_payload(account="acc_a12d", text="scope a12d")
    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["lead_id"] is None

    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True and r2["lead_id"] is None

    db3 = Session()
    try:
        orig = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert orig.merchant_id is None and orig.tenant_id is None
        assert dup.merchant_id is None and dup.tenant_id is None
        assert db3.query(DouyinLead).count() == 0
    finally:
        db3.close()


def test_a12_unbound_account_stays_null(concurrent_database):
    """A12e：无有效绑定，处理两次：merchant_id=None，不创建线索。"""
    from app.integrations.douyin_webhook import process_webhook_event
    engine, Session = concurrent_database
    payload = _make_payload(account="acc_a12e_unbound", text="scope a12e")

    db1 = Session()
    try:
        r1 = process_webhook_event(db1, payload)
        db1.commit()
    finally:
        db1.close()
    assert r1["lead_id"] is None

    db2 = Session()
    try:
        r2 = process_webhook_event(db2, payload)
        db2.commit()
    finally:
        db2.close()
    assert r2["is_duplicate"] is True and r2["lead_id"] is None

    db3 = Session()
    try:
        orig = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=False).one()
        dup = db3.query(DouyinWebhookEvent).filter_by(is_duplicate=True).first()
        assert orig.merchant_id is None and orig.tenant_id is None
        assert dup.merchant_id is None and dup.tenant_id is None
        assert db3.query(DouyinLead).count() == 0
    finally:
        db3.close()


# ========== A13: 顺序/非线索/入口胜负 ==========


def test_a13_sequential_duplicate():
    """A13a：顺序重复占位竞争失败。"""
    import tempfile
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        S = sessionmaker(bind=engine)
        db = S()
        try:
            first = claim_webhook_event(db, values=_claim_values())
            db.commit()
            assert first.won is True
            second = claim_webhook_event(db, values=_claim_values())
            db.commit()
            assert second.won is False
        finally:
            db.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_a13_non_lead_event_concurrent(concurrent_database):
    """A13b：非线索事件并发：0 线索。"""
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


def test_a13_internal_winner_then_local_duplicate(concurrent_database):
    """A13c：9202 先胜出，9000 重复，结果一致。"""
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
    assert r2["is_duplicate"] is True and r2["lead_id"] == r1["lead_id"]


def test_a13_local_winner_then_internal_duplicate(concurrent_database):
    """A13d：9000 先胜出，9202 重复，结果一致。"""
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
    assert r2["is_duplicate"] is True and r2["lead_id"] == r1["lead_id"]
