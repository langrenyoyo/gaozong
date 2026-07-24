"""AI 自动回复 outbox 持久化任务测试。

覆盖核心合同：enqueue/flush、claim/lease、recovery、compensation、
manual retry、backlog alert 和双迁移验证。
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base
from app.models import AiAutoReplyRun, DouyinWebhookEvent, DouyinAuthorizedAccount
from app.services.ai_auto_reply_outbox_service import (
    enqueue_auto_reply_run,
    claim_next_batch,
    recover_expired_leases,
    compensate_missing_runs,
    manual_retry_run,
    alert_backlog,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_RETRY_WAIT,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SEND_UNKNOWN,
)


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    yield engine, Session
    engine.dispose()


def _make_event(*, event_id=1, event_key="evt_001", to_user_id="acc_001", event_type="im_receive_msg"):
    return DouyinWebhookEvent(
        id=event_id, event=event_type, event_key=event_key,
        from_user_id="cust_001", to_user_id=to_user_id,
        merchant_id="m_001", is_duplicate=False,
        raw_body="{}", created_at=datetime.now(),
    )


# ========== A1: enqueue 仅 flush ==========


def test_a1_enqueue_flushes_without_commit(db_engine, tmp_path):
    """A1：enqueue 仅 flush，rollback 后新 Session 不可见。"""
    engine, Session = db_engine
    db_path = tmp_path / "outbox_flush.db"
    file_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(bind=file_engine)
    FileSession = sessionmaker(bind=file_engine)

    db = FileSession()
    try:
        event = _make_event()
        db.add(event)
        db.commit()

        run = enqueue_auto_reply_run(
            db,
            merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        assert run is not None
        assert run.status == STATUS_PENDING
        # flush 后同 Session 可见
        assert db.query(AiAutoReplyRun).count() == 1
        # rollback
        db.rollback()
    finally:
        db.close()

    db2 = FileSession()
    try:
        assert db2.query(AiAutoReplyRun).count() == 0
    finally:
        db2.close()
    file_engine.dispose()


# ========== A2: enqueue 重复唯一 ==========


def test_a2_enqueue_duplicate_returns_none(db_engine):
    """A2：重复 enqueue 返回 None，不报错。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()

        run1 = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        assert run1 is not None

        run2 = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        assert run2 is None
        assert db.query(AiAutoReplyRun).count() == 1
    finally:
        db.close()


# ========== A3: claim 原子租约 ==========


def test_a3_claim_sets_lease_and_processing(db_engine):
    """A3：claim 设置 status=processing, lease_owner, lease_expires_at, attempt_count+1。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        db.commit()

        claimed = claim_next_batch(db, batch_size=10)
        assert len(claimed) == 1
        run = claimed[0]
        assert run.status == STATUS_PROCESSING
        assert run.lease_owner is not None
        assert run.lease_expires_at is not None
        assert run.attempt_count == 1
    finally:
        db.close()


# ========== A4: claim 空批 ==========


def test_a4_claim_empty_when_no_pending(db_engine):
    """A4：无 pending 任务时返回空列表。"""
    engine, Session = db_engine
    db = Session()
    try:
        claimed = claim_next_batch(db, batch_size=10)
        assert claimed == []
    finally:
        db.close()


# ========== A5: claim 跳过未来 next_attempt_at ==========


def test_a5_claim_skips_future_retry_wait(db_engine):
    """A5：retry_wait 且 next_attempt_at 在未来时不被 claim。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_RETRY_WAIT
        run.next_attempt_at = datetime.now() + timedelta(hours=1)
        db.commit()

        claimed = claim_next_batch(db, batch_size=10)
        assert claimed == []
    finally:
        db.close()


# ========== A6: recover 过期租约 ==========


def test_a6_recover_expired_leases(db_engine):
    """A6：租约过期的 processing 恢复为 pending。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_PROCESSING
        run.lease_owner = "old_host:123"
        run.lease_expires_at = datetime.now() - timedelta(seconds=10)
        db.commit()

        count = recover_expired_leases(db)
        assert count == 1

        db.refresh(run)
        assert run.status == STATUS_PENDING
        assert run.lease_owner is None
        assert run.last_failure_stage == "lease_expired"
    finally:
        db.close()


# ========== A7: manual retry 商户隔离 ==========


def test_a7_manual_retry_merchant_isolation(db_engine):
    """A7：人工重试拒绝他商户 run。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_FAILED
        run.last_failure_stage = "send_network_error"
        db.commit()

        with pytest.raises(Exception):
            manual_retry_run(db, run_id=run.id, merchant_id="m_other")
    finally:
        db.close()


# ========== A8: manual retry 白名单 ==========


def test_a8_manual_retry_whitelist(db_engine):
    """A8：失败阶段不在白名单时拒绝重试。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_FAILED
        run.last_failure_stage = "upstream_business_error"
        db.commit()

        with pytest.raises(ValueError, match="failure_stage_not_whitelisted"):
            manual_retry_run(db, run_id=run.id, merchant_id="m_001")
    finally:
        db.close()


# ========== A9: manual retry 成功 ==========


def test_a9_manual_retry_success(db_engine):
    """A9：白名单内 failed run 重试成功，状态变为 retry_wait。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_FAILED
        run.last_failure_stage = "send_timeout"
        run.attempt_count = 3
        db.commit()

        result = manual_retry_run(db, run_id=run.id, merchant_id="m_001")
        assert result.status == STATUS_RETRY_WAIT
        assert result.attempt_count == 0
        assert result.last_failure_stage is None
    finally:
        db.close()


# ========== A10: manual retry 拒绝非 failed ==========


def test_a10_manual_retry_rejects_non_failed(db_engine):
    """A10：非 failed 状态拒绝重试。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        db.commit()

        with pytest.raises(ValueError, match="run_not_failed"):
            manual_retry_run(db, run_id=run.id, merchant_id="m_001")
    finally:
        db.close()


# ========== A11: compensate 创建缺失 run ==========


def test_a11_compensate_creates_missing_run(db_engine):
    """A11：补偿扫描为缺失事件创建 pending run。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        event.merchant_id = "m_comp"
        db.add(event)
        db.commit()

        count = compensate_missing_runs(db)
        assert count == 1
        run = db.query(AiAutoReplyRun).first()
        assert run is not None
        assert run.status == STATUS_PENDING
        assert run.trigger_event_key == event.event_key
    finally:
        db.close()


# ========== A12: compensate 跳过无商户事件 ==========


def test_a12_compensate_skips_no_merchant(db_engine):
    """A12：补偿扫描跳过 merchant_id 为空的事件。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        event.merchant_id = None
        db.add(event)
        db.commit()

        count = compensate_missing_runs(db)
        assert count == 0
    finally:
        db.close()


# ========== A13: compensate 跳过已有 run ==========


def test_a13_compensate_skips_existing_run(db_engine):
    """A13：补偿扫描跳过已有 run 的事件。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        db.commit()

        count = compensate_missing_runs(db)
        assert count == 0
    finally:
        db.close()


# ========== A14: backlog alert 不崩溃 ==========


def test_a14_backlog_alert_runs_without_error(db_engine):
    """A14：积压告警空库执行不崩溃。"""
    engine, Session = db_engine
    db = Session()
    try:
        alert_backlog(db)  # 不抛异常
    finally:
        db.close()


# ========== A15: claim 批量限制 ==========


def test_a15_claim_respects_batch_size(db_engine):
    """A15：claim 尊重 batch_size 限制。"""
    engine, Session = db_engine
    db = Session()
    try:
        for i in range(5):
            event = _make_event(event_id=i + 1, event_key=f"evt_{i:03d}")
            db.add(event)
            db.commit()
            enqueue_auto_reply_run(
                db, merchant_id="m_001", account_open_id="acc_001",
                trigger_event_id=event.id, trigger_event_key=event.event_key,
            )
            db.commit()

        claimed = claim_next_batch(db, batch_size=3)
        assert len(claimed) == 3
    finally:
        db.close()


# ========== A16: claim 不重复领取已 claim 的 ==========


def test_a16_claim_does_not_reclaim(db_engine):
    """A16：已 claim 的任务不会被第二次 claim 领取。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        db.commit()

        first = claim_next_batch(db, batch_size=10)
        assert len(first) == 1
        second = claim_next_batch(db, batch_size=10)
        assert second == []
    finally:
        db.close()


# ========== A17: claim 20 路并发 ==========


def test_a17_claim_twenty_concurrent_single_winner(db_engine, tmp_path):
    """A17：20 路并发 claim 同一任务，只有 1 个成功。"""
    from concurrent.futures import ThreadPoolExecutor
    db_path = tmp_path / "outbox_concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=20,
    )

    from sqlalchemy import event as sa_event
    @sa_event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        db.commit()
    finally:
        db.close()

    barrier = threading.Barrier(20)
    results = []

    def worker():
        barrier.wait(timeout=10)
        db = Session()
        try:
            claimed = claim_next_batch(db, batch_size=1)
            results.extend(claimed)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker) for _ in range(20)]
        for f in futures:
            f.result(timeout=30)

    assert len(results) == 1, f"期望 1 个 claim 成功，实际 {len(results)}"
    engine.dispose()


# ========== A18: 双迁移验证 ==========


def test_a18_sqlite_migration_adds_outbox_columns(tmp_path):
    """A18：SQLite 迁移 0036 添加 outbox 字段。"""
    from migrations.migrate_sqlite import (
        apply_migration, connect_readonly, connect_readwrite,
        get_columns, parse_sql, version_applied,
    )
    from app.database import Base
    from sqlalchemy import create_engine

    db_path = tmp_path / "outbox_migrate.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200))")
    conn.execute("INSERT INTO schema_migrations (version_num, applied_at, description) VALUES ('0035', CURRENT_TIMESTAMP, 'predecessor')")
    conn.close()

    sql_file = "migrations/versions/0036_ai_auto_reply_outbox.sql"
    stmts = parse_sql(open(sql_file, encoding="utf-8").read())
    conn = connect_readwrite(str(db_path))
    apply_migration(conn, stmts, "0036", "AI auto reply outbox")
    conn.close()

    conn = connect_readonly(str(db_path))
    cols = set(get_columns(conn, "ai_auto_reply_runs"))
    conn.close()
    assert "lease_owner" in cols
    assert "lease_expires_at" in cols
    assert "attempt_count" in cols
    assert "next_attempt_at" in cols
    assert "last_failure_stage" in cols


# ========== A19: 终态不重发 ==========


def test_a19_terminal_status_not_claimed(db_engine):
    """A19：sent/send_unknown/send_authorized 不被 claim。"""
    engine, Session = db_engine
    db = Session()
    try:
        for idx, status in enumerate([STATUS_SENT, STATUS_SEND_UNKNOWN, "send_authorized"], start=100):
            event = _make_event(event_id=idx, event_key=f"evt_term_{status}")
            db.add(event)
            db.commit()
            run = enqueue_auto_reply_run(
                db, merchant_id="m_001", account_open_id="acc_001",
                trigger_event_id=event.id, trigger_event_key=event.event_key,
            )
            run.status = status
            db.commit()

        claimed = claim_next_batch(db, batch_size=10)
        assert claimed == []
    finally:
        db.close()


# ========== A20: 退避时间正确设置 ==========


def test_a20_retry_wait_next_attempt_in_future(db_engine):
    """A20：retry_wait 状态的 next_attempt_at 在未来，不被立即 claim。"""
    engine, Session = db_engine
    db = Session()
    try:
        event = _make_event()
        db.add(event)
        db.commit()
        run = enqueue_auto_reply_run(
            db, merchant_id="m_001", account_open_id="acc_001",
            trigger_event_id=event.id, trigger_event_key=event.event_key,
        )
        run.status = STATUS_RETRY_WAIT
        run.next_attempt_at = datetime.now() + timedelta(seconds=60)
        db.commit()

        # 当前不可 claim（next_attempt_at 在未来）
        assert claim_next_batch(db, batch_size=10) == []

        # 模拟退避时间过去
        run.next_attempt_at = datetime.now() - timedelta(seconds=1)
        db.commit()

        claimed = claim_next_batch(db, batch_size=10)
        assert len(claimed) == 1
    finally:
        db.close()
