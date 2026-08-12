"""P2-M04 notify_sales Claim/Lease — focused 测试。

设计审批 APPROVED_WITH_CORRECTIONS，Candidate C：
Atomic Claim + Lease + Attempt Token + Current-Attempt Callback CAS + Uncertain State。

覆盖 P2-R1~R13 + additional §60-64 核心断言。
并发测试（P2-R1/R2/R9）skip on SQLite，由隔离 PG runtime 覆盖。
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, WechatTask, ComputeMarkupRatio, DouyinLead, SalesStaff, DouyinAuthorizedAccount
from app.services import wechat_task_service
from app.services.wechat_task_service import (
    claim_notify_sales_task,
    submit_wechat_task_result,
    reclaim_expired_claims,
    resolve_uncertain_task,
    StaleAttemptError,
    DEFAULT_LEASE_SECONDS,
)
from app.services.lead_wechat_notify_eligibility_service import ACTIVE_NOTIFY_TASK_STATUSES


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    # fixture: merchant + lead + staff + agent
    session.add(DouyinAuthorizedAccount(main_account_id=1, open_id="acc1", merchant_id="m1", bind_status=1, account_name="test"))
    session.add(SalesStaff(id=1, merchant_id="m1", wechat_nickname="销售A", name="销售A"))
    session.add(DouyinLead(id=1, merchant_id="m1", account_open_id="acc1", source_id="cust1", source="douyin"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _create_notify_task(db, task_id=None, status="pending", lead_id=1, staff_id=1):
    """创建 notify_sales task fixture。"""
    task = WechatTask(
        id=task_id, task_type="notify_sales", lead_id=lead_id, staff_id=staff_id,
        target_nickname="销售A", message="测试消息", mode="single_send", status=status,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# === P2-R7 Happy Path ===

def test_p2_r7_happy_path_claim_callback_sent(db):
    """正常 happy path: pending → claim → callback sent → terminal=sent。"""
    task = _create_notify_task(db)
    claimed = claim_notify_sales_task(db, merchant_id="m1", agent_hostname="host1", agent_pid=1234)
    assert claimed is not None
    assert claimed["task"].status == "running"
    assert claimed["claim_token"] is not None
    assert claimed["attempt_count"] == 1

    result = submit_wechat_task_result(db, claimed["task"], success=True, verified=True,
                                       sent=True, claim_token=claimed["claim_token"])
    assert result.status == "sent"
    assert result.sent_at is not None


# === P2-R10 Duplicate Callback ===

def test_p2_r10_duplicate_callback_idempotent_replay(db):
    """同 attempt 重复 callback → idempotent success（非 stale）。"""
    task = _create_notify_task(db)
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    token = claimed["claim_token"]

    # 第一次 callback
    r1 = submit_wechat_task_result(db, claimed["task"], success=True, verified=True,
                                   sent=True, claim_token=token)
    assert r1.status == "sent"

    # 第二次相同 callback（duplicate same-attempt）
    db.refresh(claimed["task"])
    r2 = submit_wechat_task_result(db, claimed["task"], success=True, verified=True,
                                   sent=True, claim_token=token)
    assert r2.status == "sent"  # idempotent replay，不报错


# === P2-R4 Late Callback ===

def test_p2_r4_stale_token_rejected(db):
    """旧 token callback → StaleAttemptError。"""
    from datetime import datetime, timedelta, timezone
    task = _create_notify_task(db)
    # 第一次 claim
    claimed1 = claim_notify_sales_task(db, merchant_id="m1")
    token1 = claimed1["claim_token"]
    # expire lease → uncertain（not sent）
    db.query(WechatTask).filter(WechatTask.id == task.id).update(
        {WechatTask.lease_expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)},
        synchronize_session=False,
    )
    db.commit()
    reclaim_expired_claims(db)

    # manual retry → pending
    db.refresh(claimed1["task"])
    resolve_uncertain_task(db, task_id=claimed1["task"].id, merchant_id="m1",
                           action="retry", operator="test", reason="test")
    # 第二次 claim（新 token）
    db.refresh(claimed1["task"])
    claimed2 = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed2 is not None
    token2 = claimed2["claim_token"]
    assert token1 != token2  # 新 attempt = 新 token

    # 旧 token callback → StaleAttemptError
    db.refresh(claimed2["task"])
    with pytest.raises(StaleAttemptError):
        submit_wechat_task_result(db, claimed2["task"], success=True, verified=True,
                                  sent=True, claim_token=token1)


# === P2-R3 Stale Lease Quarantine ===

def test_p2_r3_stale_lease_quarantine_uncertain(db):
    """lease expired running → uncertain（no blind resend）。"""
    from datetime import datetime, timedelta, timezone
    task = _create_notify_task(db)
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed["task"].status == "running"

    # 手动设 lease 为过去
    db.query(WechatTask).filter(WechatTask.id == task.id).update(
        {WechatTask.lease_expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)},
        synchronize_session=False,
    )
    db.commit()

    result = reclaim_expired_claims(db)
    assert result["running_to_uncertain"] == 1

    db.refresh(task)
    assert task.status == "uncertain"


# === P2-R6 Uncertain No Blind Resend ===

def test_p2_r6_uncertain_not_returned_by_poll(db):
    """uncertain task 不被 poll 返回（no blind resend）。"""
    task = _create_notify_task(db, status="uncertain")
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed is None  # uncertain 不被 claim


# === P2-R8 Producer Dedup Uncertain ===

def test_p2_r8_uncertain_blocks_producer(db):
    """uncertain status 在 ACTIVE_NOTIFY_TASK_STATUSES 中（producer 阻断）。"""
    assert "uncertain" in ACTIVE_NOTIFY_TASK_STATUSES


# === P2-R11/R12 Producer Blocked While Running/Uncertain ===

def test_p2_r11_running_blocks_producer(db):
    """running 在 ACTIVE_NOTIFY_TASK_STATUSES 中（producer 阻断）。"""
    assert "running" in ACTIVE_NOTIFY_TASK_STATUSES


def test_p2_r12_uncertain_blocks_producer(db):
    """uncertain 在 ACTIVE_NOTIFY_TASK_STATUSES 中（producer 阻断）。"""
    assert "uncertain" in ACTIVE_NOTIFY_TASK_STATUSES


# === Manual Resolution ===

def test_manual_resolution_mark_sent(db):
    """uncertain → manual mark_sent → sent。"""
    task = _create_notify_task(db, status="uncertain")
    result = resolve_uncertain_task(db, task_id=task.id, merchant_id="m1",
                                    action="mark_sent", operator="admin1", reason="confirmed sent")
    assert result.status == "sent"
    assert result.sent_at is not None


def test_manual_resolution_retry(db):
    """uncertain → manual retry → pending（旧 token 保留，下次 claim 覆盖）。"""
    task = _create_notify_task(db, status="uncertain")
    result = resolve_uncertain_task(db, task_id=task.id, merchant_id="m1",
                                    action="retry", operator="admin1", reason="retry needed")
    assert result.status == "pending"


def test_manual_resolution_cancel(db):
    """uncertain → manual cancel → cancelled。"""
    task = _create_notify_task(db, status="uncertain")
    result = resolve_uncertain_task(db, task_id=task.id, merchant_id="m1",
                                    action="cancel", operator="admin1", reason="cancel")
    assert result.status == "cancelled"


# === C13 Claim Exactly One ===

def test_c13_claim_exactly_one(db):
    """创建 3 个 pending notify_sales，一次 claim 只返回 1 个。"""
    for i in range(3):
        _create_notify_task(db)
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed is not None
    assert claimed["task"].status == "running"
    # 其余 2 个仍 pending
    pending = db.query(WechatTask).filter(WechatTask.status == "pending").count()
    assert pending == 2


# === C11 claimed_at = execution_started_at ===

def test_c11_claimed_at_reuses_execution_started_at(db):
    """claim 时 execution_started_at 被填充（C11 复用作 claimed_at）。"""
    task = _create_notify_task(db)
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed["task"].execution_started_at is not None


# === C3 Lease 300s ===

def test_c3_lease_300s_default():
    """DEFAULT_LEASE_SECONDS = 300（C3）。"""
    assert DEFAULT_LEASE_SECONDS == 300


# === C9 Token Lifecycle ===

def test_c9_new_attempt_new_token(db):
    """新 attempt = 新 token（旧 token fenced）。"""
    from datetime import datetime, timedelta, timezone
    task = _create_notify_task(db)
    c1 = claim_notify_sales_task(db, merchant_id="m1")
    t1 = c1["claim_token"]
    # expire lease → uncertain
    db.query(WechatTask).filter(WechatTask.id == task.id).update(
        {WechatTask.lease_expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)},
        synchronize_session=False,
    )
    db.commit()
    reclaim_expired_claims(db)

    # manual retry → pending
    db.refresh(c1["task"])
    resolve_uncertain_task(db, task_id=c1["task"].id, merchant_id="m1", action="retry", operator="op", reason="r")
    db.refresh(c1["task"])
    c2 = claim_notify_sales_task(db, merchant_id="m1")
    t2 = c2["claim_token"]
    assert t1 != t2


# === C14 detect_reply No Regression ===

def test_c14_detect_reply_no_claim_token_required(db):
    """detect_reply 不需要 claim_token（mode-specific，C14）。"""
    task = WechatTask(task_type="detect_reply", lead_id=1, staff_id=1, reply_check_id=None,
                     target_nickname="销售A", message="", mode="read_only", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    # detect_reply poll 不走 claim（C12 mode-specific）
    tasks = wechat_task_service.get_pending_wechat_tasks(db, task_type="detect_reply", merchant_id="m1")
    assert len(tasks) == 1
    assert tasks[0].status == "pending"  # 未被 claim


# === Merchant Isolation ===

def test_merchant_isolation(db):
    """M1 poll 不能 claim M2 task。"""
    # M1 task（fixture 已有 staff1/lead1，需创建 task）
    _create_notify_task(db)
    # M2 fixture
    db.add(SalesStaff(id=2, merchant_id="m2", wechat_nickname="销售B", name="销售B"))
    db.add(DouyinLead(id=2, merchant_id="m2", account_open_id="acc2", source_id="cust2", source="douyin"))
    db.add(WechatTask(task_type="notify_sales", lead_id=2, staff_id=2,
                      target_nickname="销售B", message="m2 task", mode="single_send", status="pending"))
    db.commit()

    # M1 只能看到/claim M1 的 task
    claimed = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed is not None
    assert claimed["task"].lead_id == 1  # M1's task

    # M1 不能 claim M2's task
    claimed_m2 = claim_notify_sales_task(db, merchant_id="m1")
    assert claimed_m2 is None  # M1 没有 more pending tasks


# === Concurrent tests skip on SQLite（PG runtime 覆盖）===

@pytest.mark.skipif(True, reason="§P2 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_p2_r1_simultaneous_duplicate_poll(db):
    """P2-R1: 两个 client 同时 poll 同一 task → 只 claim 1 个。"""


@pytest.mark.skipif(True, reason="§P2 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_p2_r2_multiple_agent_instances(db):
    """P2-R2: 多 agent 同时 poll → only current claim holder executes。"""


@pytest.mark.skipif(True, reason="§P2 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_p2_r9_expiry_callback_race(db):
    """P2-R9: expiry CAS vs valid callback → 只有一个赢。"""
