"""Phase 9 Task 7 分层崩溃恢复测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 7。

覆盖：
- 过期 processing（lease 过期）→ pending + attempt_count += 1（再被 process 调度）。
- 未过期 processing 不动。
- send_authorized 有 sent 流水 → 对账 sent。
- send_authorized 无 sent 流水 → 对账 send_unknown（崩溃在发送后、回写前）。
- 8 终态不动。
- pending 被 process_return_visit_run 调度。
- 模块级非阻塞 Lock 单飞：第二次获取失败立即返回。

不验证启动线程本身（main.py on_startup 接入靠 AST + 既有生命周期测试回归）。
processor 全替身，真实 9100/抖音网络恒 0。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.services.return_visit_run_service as rvrs
from app.database import Base
from app.models import (
    DouyinPrivateMessageSend,
    ReturnVisitRun,
)
from app.services.return_visit_run_service import (
    reconcile_return_visit_runs_on_startup,
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


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    """SessionLocal 替身 + 网络哨兵（recovery 不发送、不调 9100）。"""
    monkeypatch.setattr(rvrs, "SessionLocal", lambda: TestSession())

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵：recovery 禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)


_RUN_COUNTER = [0]


def _seed_run(
    db,
    *,
    send_status: str,
    attempt_count: int = 1,
    lease_expires_at: datetime | None = None,
    lease_owner: str | None = None,
) -> ReturnVisitRun:
    _RUN_COUNTER[0] += 1
    suffix = str(_RUN_COUNTER[0])
    run = ReturnVisitRun(
        merchant_id="merchant-1",
        lead_id=10,
        staff_id=1,
        trigger_source="wechat_sales_reply",
        trigger_text="测试触发",
        send_status=send_status,
        attempt_count=attempt_count,
        account_open_id="account-open-1",
        conversation_short_id="conv-1",
        customer_open_id="customer-open-1",
        context_server_message_id="server-msg-1",
        dispatch_notification_id=100,
        lease_expires_at=lease_expires_at,
        lease_owner=lease_owner,
        idempotency_key=f"key-{suffix}",
        trigger_message_fp=f"fp-{suffix}",
    )
    db.add(run)
    db.flush()
    return run


def _seed_sent_flow(db, *, run_id: int, suffix: str) -> DouyinPrivateMessageSend:
    send = DouyinPrivateMessageSend(
        main_account_id="main-1",
        conversation_short_id="conv-1",
        server_message_id=f"server-seed-{suffix}",
        from_user_id="account-open-1",
        to_user_id="customer-open-1",
        customer_open_id="customer-open-1",
        account_open_id="account-open-1",
        scene="im_receive_msg",
        content="回访话术",
        request_body_json="{}",
        status="sent",
        manual_confirmed=0,
        auto_send=1,
        send_source="return_visit_auto",
        return_visit_run_id=run_id,
        sent_at=datetime.now(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(send)
    db.flush()
    return send


def _stub_processor(monkeypatch) -> list[int]:
    """替换 process_return_visit_run 为记录调用的 noop。"""
    called: list[int] = []

    def _noop(run_id: int) -> None:
        called.append(run_id)

    monkeypatch.setattr(rvrs, "process_return_visit_run", _noop)
    return called


# ---------------------------------------------------------------------------
# 过期 processing 回收
# ---------------------------------------------------------------------------


def test_expired_processing_recovered_to_pending(monkeypatch):
    called = _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(
            db,
            send_status="processing",
            attempt_count=1,
            lease_expires_at=datetime.now() - timedelta(seconds=10),
            lease_owner="dead-proc",
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    db2 = TestSession()
    try:
        done = db2.get(ReturnVisitRun, run_id)
        assert done.send_status == "pending_judgement"
        assert done.attempt_count == 2
        assert run_id in called  # 回收后作为 pending 被调度
    finally:
        db2.close()


def test_unexpired_processing_not_recovered(monkeypatch):
    called = _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(
            db,
            send_status="processing",
            attempt_count=1,
            lease_expires_at=datetime.now() + timedelta(seconds=60),
            lease_owner="live-proc",
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    db2 = TestSession()
    try:
        done = db2.get(ReturnVisitRun, run_id)
        assert done.send_status == "processing"
        assert done.attempt_count == 1
        assert run_id not in called  # 未过期不回收、不调度
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# send_authorized 对账
# ---------------------------------------------------------------------------


def test_send_authorized_with_sent_flow_to_sent(monkeypatch):
    _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(db, send_status="send_authorized", attempt_count=1)
        db.flush()
        _seed_sent_flow(db, run_id=run.id, suffix="auth1")
        db.commit()
        run_id = run.id
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "sent"
    finally:
        db2.close()


def test_send_authorized_without_sent_flow_to_send_unknown(monkeypatch):
    _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(db, send_status="send_authorized", attempt_count=1)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "send_unknown"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 终态不动
# ---------------------------------------------------------------------------


def test_terminal_statuses_untouched(monkeypatch):
    _stub_processor(monkeypatch)
    terminal_ids: list[int] = []
    db = TestSession()
    try:
        for status in [
            "not_needed", "confidence_low", "prompt_disabled", "rate_limited",
            "blocked", "sent", "send_unknown", "failed",
        ]:
            run = _seed_run(db, send_status=status, attempt_count=1)
            terminal_ids.append((run.id, status))
        db.commit()
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    db2 = TestSession()
    try:
        for run_id, status in terminal_ids:
            assert db2.get(ReturnVisitRun, run_id).send_status == status
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# pending 被调度
# ---------------------------------------------------------------------------


def test_pending_dispatched_to_processor(monkeypatch):
    called = _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(db, send_status="pending_judgement", attempt_count=1)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    reconcile_return_visit_runs_on_startup()

    assert run_id in called


# ---------------------------------------------------------------------------
# 单飞锁
# ---------------------------------------------------------------------------


def test_single_flight_skip(monkeypatch):
    called = _stub_processor(monkeypatch)
    db = TestSession()
    try:
        run = _seed_run(db, send_status="pending_judgement", attempt_count=1)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    # 持有模块级锁，模拟并发第二次 reconcile
    acquired = rvrs._RECONCILE_LOCK.acquire(blocking=False)
    assert acquired
    try:
        reconcile_return_visit_runs_on_startup()
    finally:
        rvrs._RECONCILE_LOCK.release()

    assert run_id not in called  # 锁占用，直接跳过，不调度
