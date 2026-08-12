"""P1-FC-F1 Concurrent Balance Atomic Update — focused 测试。

设计审批 APPROVED_WITH_CORRECTIONS，Candidate B：atomic UPDATE ... RETURNING。
验证 record_usage 幂等路径余额更新从 ORM 读-改-写转为 DB 原子算术后：
- T1 单笔扣费行为不变
- T2 sequential replay（same key → 1 txn / 1 delta）
- T3 same-key concurrency（N-way → 1 txn / replay convergence / no 500）— PostgreSQL only
- T4 distinct-key concurrency（同 merchant 多 key → 各 1 txn / balance closure）— PostgreSQL only
- T5 mixed workload（duplicate + distinct → one delta per unique identity）— PostgreSQL only
- T6 merchant isolation（同 key 不同 merchant 独立）
- T7 rollback（失败不留半成品）
- T8 balance_after 合法 serial ordering — PostgreSQL only
- T10 SQLite S1（update().returning() 跨方言）

§32：PostgreSQL 是并发 correctness 权威。SQLite 只验证 S1 syntax/behavior 兼容。
并发测试（T3/T4/T5/T8）skip on SQLite，由隔离 PG runtime script 验证。
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, ComputeAccount, ComputeMarkupRatio
from app.schemas import ComputeRechargeOrderRequest
from apps.compute.services import (
    create_mock_recharge_order,
    get_or_create_account,
    record_usage,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    session.add(ComputeMarkupRatio(capability_key="knowledge", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(session, "m_fc", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _charge(db, merchant, key, tokens=100):
    """单笔 record_usage 幂等扣费。"""
    result = record_usage(
        db, merchant, tokens,
        capability_key="knowledge", source="embedding", model="fc-test-model",
        usage_measurement_method="estimated_tokens",
        idempotency_key=key,
    )
    db.commit()
    return result


# === T1 Single usage ===

def test_t1_single_charge_balance_after_correct(db):
    """单笔扣费行为不变：balance 100000→99900，balance_after=99900。"""
    bal_before = get_or_create_account(db, "m_fc").balance_tokens
    r = _charge(db, "m_fc", "k-t1")
    assert r["idempotency_status"] == "created"
    bal_after = get_or_create_account(db, "m_fc").balance_tokens
    assert bal_after == bal_before - 100
    # balance_after_tokens 来自 RETURNING（非 stale ORM）
    from app.models import ComputeTransaction
    tx = db.query(ComputeTransaction).filter(ComputeTransaction.idempotency_key == "k-t1").one()
    assert tx.balance_after_tokens == bal_after


# === T2 Sequential replay ===

def test_t2_sequential_replay_one_txn_one_delta(db):
    """same key sequential → 1 txn / 1 delta / replay。"""
    bal_before = get_or_create_account(db, "m_fc").balance_tokens
    r1 = _charge(db, "m_fc", "k-t2")
    r2 = _charge(db, "m_fc", "k-t2")
    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"
    bal_after = get_or_create_account(db, "m_fc").balance_tokens
    assert bal_after == bal_before - 100  # 只扣一次


# === T3 Same-key concurrency ===

@pytest.mark.skipif(True, reason="§32 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_t3_same_key_concurrency_one_txn_no_500(db):
    """N-way 同 key 并发 → 1 txn / replay convergence / 无 exception。"""
    from sqlalchemy import create_engine as ce
    # 用独立 session per worker（SQLite StaticPool 共享底层 DB）
    engine = db.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def worker(barrier, results, idx):
        barrier.wait()
        s = Session()
        try:
            r = record_usage(s, "m_fc", 100, capability_key="knowledge", source="embedding",
                             model="fc-test-model", usage_measurement_method="estimated_tokens",
                             idempotency_key="k-t3")
            s.commit()
            s.close()
            results[idx] = r["idempotency_status"]
        except Exception as e:
            s.close()
            results[idx] = f"EXC:{type(e).__name__}"

    N = 8
    barrier = threading.Barrier(N)
    results = [None] * N
    with ThreadPoolExecutor(max_workers=N) as pool:
        for i in range(N):
            pool.submit(worker, barrier, results, i)
        pool.shutdown(wait=True)

    bal_after = get_or_create_account(db, "m_fc").balance_tokens
    created = sum(1 for r in results if r == "created")
    replay = sum(1 for r in results if r == "idempotent_replay")
    exc = sum(1 for r in results if isinstance(r, str) and r.startswith("EXC"))
    from app.models import ComputeTransaction
    tx_count = db.query(ComputeTransaction).filter(ComputeTransaction.idempotency_key == "k-t3").count()

    assert tx_count == 1
    assert created == 1
    assert replay == 7
    assert exc == 0
    assert bal_after == 100000 - 100


# === T4 Distinct-key concurrency ===

@pytest.mark.skipif(True, reason="§32 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_t4_distinct_key_concurrency_balance_closure(db):
    """同 merchant 8 distinct key 并发 → 各 1 txn / balance closure。"""
    engine = db.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def worker(key, barrier, results, idx):
        barrier.wait()
        s = Session()
        try:
            r = record_usage(s, "m_fc", 100, capability_key="knowledge", source="embedding",
                             model="fc-test-model", usage_measurement_method="estimated_tokens",
                             idempotency_key=key)
            s.commit()
            s.close()
            results[idx] = r["idempotency_status"]
        except Exception as e:
            s.close()
            results[idx] = f"EXC:{type(e).__name__}"

    keys = [f"k-t4-{chr(65+i)}" for i in range(8)]
    N = len(keys)
    barrier = threading.Barrier(N)
    results = [None] * N
    with ThreadPoolExecutor(max_workers=N) as pool:
        for i in range(N):
            pool.submit(worker, keys[i], barrier, results, i)
        pool.shutdown(wait=True)

    bal_after = get_or_create_account(db, "m_fc").balance_tokens
    exc = sum(1 for r in results if isinstance(r, str) and r.startswith("EXC"))
    from app.models import ComputeTransaction
    tx_counts = [db.query(ComputeTransaction).filter(ComputeTransaction.idempotency_key == k).count() for k in keys]

    # ★ 核心修复验证：8 distinct key 各 1 txn + balance closure
    assert all(c == 1 for c in tx_counts), f"per-key txn count: {tx_counts}"
    assert exc == 0
    assert bal_after == 100000 - 100 * 8  # ★ lost update 已消除


# === T5 Mixed workload ===

@pytest.mark.skipif(True, reason="§32 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_t5_mixed_workload_one_delta_per_unique_identity(db):
    """duplicate + distinct 混合并发 → one delta per unique identity。"""
    engine = db.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def worker(key, barrier, results, idx):
        barrier.wait()
        s = Session()
        try:
            r = record_usage(s, "m_fc", 100, capability_key="knowledge", source="embedding",
                             model="fc-test-model", usage_measurement_method="estimated_tokens",
                             idempotency_key=key)
            s.commit()
            s.close()
            results[idx] = r["idempotency_status"]
        except Exception as e:
            s.close()
            results[idx] = f"EXC:{type(e).__name__}"

    # K-A 重复 4 次 + K-B/C/D 各 1 次 = 4 unique identities
    tasks = ["k-t5-A"] * 4 + ["k-t5-B", "k-t5-C", "k-t5-D"]
    N = len(tasks)
    barrier = threading.Barrier(N)
    results = [None] * N
    with ThreadPoolExecutor(max_workers=N) as pool:
        for i in range(N):
            pool.submit(worker, tasks[i], barrier, results, i)
        pool.shutdown(wait=True)

    bal_after = get_or_create_account(db, "m_fc").balance_tokens
    exc = sum(1 for r in results if isinstance(r, str) and r.startswith("EXC"))
    # 4 unique identities × 100 = -400
    assert exc == 0
    assert bal_after == 100000 - 400


# === T6 Merchant isolation ===

def test_t6_merchant_isolation_same_key_independent(db):
    """同 key 不同 merchant → 各独立扣费。"""
    from app.models import ComputeMarkupRatio as R
    # M2 fixture
    db.add(ComputeAccount(merchant_id="m_fc2", balance_tokens=100000))
    db.commit()

    r1 = _charge(db, "m_fc", "k-t6")
    r2 = _charge(db, "m_fc2", "k-t6")
    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "created"
    assert get_or_create_account(db, "m_fc").balance_tokens == 100000 - 100
    assert get_or_create_account(db, "m_fc2").balance_tokens == 100000 - 100


# === T7 Rollback ===

def test_t7_no_half_committed_on_failure(db):
    """原子性：account UPDATE + txn INSERT 同事务，失败不留半成品。
    通过构造无效 capability_key 触发 ValueError（在 flush 前），确认无副作用。
    """
    bal_before = get_or_create_account(db, "m_fc").balance_tokens
    with pytest.raises(ValueError):
        record_usage(db, "m_fc", 100, capability_key="INVALID_CAP",
                     source="embedding", model="m", usage_measurement_method="estimated_tokens",
                     idempotency_key="k-t7")
    db.rollback()
    # 无 txn / 无 balance 变化
    assert get_or_create_account(db, "m_fc").balance_tokens == bal_before


# === T8 balance_after serial ordering ===

@pytest.mark.skipif(True, reason="§32 concurrency test needs PostgreSQL, validated via isolated PG script")
def test_t8_balance_after_forms_valid_serial_progression(db):
    """并发后 balance_after_tokens 能构成合法 serial progression。"""
    engine = db.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def worker(key, barrier, results, idx):
        barrier.wait()
        s = Session()
        try:
            record_usage(s, "m_fc", 100, capability_key="knowledge", source="embedding",
                         model="fc-test-model", usage_measurement_method="estimated_tokens",
                         idempotency_key=key)
            s.commit()
            s.close()
            results[idx] = "ok"
        except Exception as e:
            s.close()
            results[idx] = f"EXC:{type(e).__name__}"

    keys = [f"k-t8-{i}" for i in range(5)]
    N = len(keys)
    barrier = threading.Barrier(N)
    results = [None] * N
    with ThreadPoolExecutor(max_workers=N) as pool:
        for i in range(N):
            pool.submit(worker, keys[i], barrier, results, i)
        pool.shutdown(wait=True)

    from app.models import ComputeTransaction
    txns = db.query(ComputeTransaction).filter(ComputeTransaction.idempotency_key.like("k-t8-%")).all()
    bal_values = sorted([t.balance_after_tokens for t in txns])
    # 合法 serial progression：100000, 99900, 99800, 99700, 99600
    expected = sorted([100000 - 100 * (i + 1) for i in range(N)])
    assert bal_values == expected
    assert get_or_create_account(db, "m_fc").balance_tokens == 100000 - 100 * N


# === T10 SQLite S1 ===

def test_t10_sqlite_s1_update_returning_works(db):
    """SQLite runtime 3.50.4 支持 UPDATE ... RETURNING（S1 跨方言）。"""
    import sqlite3
    version = sqlite3.sqlite_version_info
    assert version >= (3, 35), f"SQLite {version} < 3.35，UPDATE RETURNING 不支持"
    # 实际验证：record_usage 经 atomic UPDATE RETURNING 正常工作
    r = _charge(db, "m_fc", "k-t10")
    assert r["idempotency_status"] == "created"
    assert get_or_create_account(db, "m_fc").balance_tokens == 100000 - 100
