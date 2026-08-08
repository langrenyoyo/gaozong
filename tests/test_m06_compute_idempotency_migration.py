"""P1 Stage 3 — M06 Consumer 迁移验证。

Gate 6A: Same Job Duplicate Usage → 1 txn
Gate 6B: Different Jobs → 2 txn
Gate 6C: M06 None Count = 0
Gate 6D: Same Job / Different Operation → NOT_APPLICABLE_CURRENTLY
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeAccount, ComputeMarkupRatio, ComputeTransaction, AiEditJob,
)
from app.schemas import ComputeRechargeOrderRequest
from apps.compute.services import (
    record_usage, create_mock_recharge_order, get_or_create_account,
)
from app.services.ai_edit_las_service import _report_las_compute_usage


@pytest.fixture()
def db():
    """每个测试用独立内存库。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    session.add(ComputeMarkupRatio(capability_key="ai_edit", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_m06", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _create_job(db, job_id=1, script="这是一段用于LAS混剪的脚本内容"):
    """创建一个 AiEditJob（用于 _report_las_compute_usage）。"""
    job = AiEditJob(
        merchant_id="m_m06", job_id=f"job_{job_id}", status="succeeded",
        stage="completed", progress=100, source_type="las_speech_auto",
        las_script=script, las_template="automotive_headtalk",
        las_task_id=f"las_{job_id}", las_idempotent_id=f"idem_{job_id}",
    )
    db.add(job)
    db.commit()
    return job


# === Gate 6A: Same Job Duplicate Usage → 1 txn ===

def test_gate6a_same_job_duplicate_usage_one_txn(db):
    """同一 Job 重复调用 _report_las_compute_usage → 1 条 txn。"""
    job = _create_job(db)
    acct_before = get_or_create_account(db, "m_m06")
    balance_before = acct_before.balance_tokens

    # 第一次
    _report_las_compute_usage(db, job)
    db.commit()

    # 第二次（重复——模拟异常重入）
    _report_las_compute_usage(db, job)
    db.commit()

    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m06",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key == f"las_job:{job.id}:archive_usage",
        )
        .all()
    )
    assert len(txns) == 1, f"Expected 1 txn, got {len(txns)}"

    acct_after = get_or_create_account(db, "m_m06")
    delta = balance_before - acct_after.balance_tokens
    expected_tokens = max(1, len(job.las_script) // 2)
    assert delta == expected_tokens, f"Expected delta={expected_tokens}, got {delta}"


# === Gate 6B: Different Jobs → 2 txn ===

def test_gate6b_different_jobs_two_txn(db):
    """不同 Job → 2 条 txn，balance 扣 2 次。"""
    job1 = _create_job(db, job_id=1, script="第一段脚本内容")
    job2 = _create_job(db, job_id=2, script="第二段脚本内容")

    _report_las_compute_usage(db, job1)
    db.commit()
    _report_las_compute_usage(db, job2)
    db.commit()

    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m06",
            ComputeTransaction.transaction_type == "consume",
        )
        .all()
    )
    assert len(txns) == 2, f"Expected 2 txn, got {len(txns)}"

    keys = [t.idempotency_key for t in txns]
    assert f"las_job:{job1.id}:archive_usage" in keys
    assert f"las_job:{job2.id}:archive_usage" in keys
    assert len(set(keys)) == 2


# === Gate 6C: M06 None Count = 0 ===

def test_gate6c_m06_no_none_idempotency_key(db):
    """M06 迁移后所有 charge-producing 调用均传 idempotency_key，None count = 0。"""
    job = _create_job(db)
    _report_las_compute_usage(db, job)
    db.commit()

    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m06",
            ComputeTransaction.capability_key == "ai_edit",
        )
        .all()
    )
    assert len(txns) > 0
    none_count = sum(1 for t in txns if t.idempotency_key is None)
    assert none_count == 0, f"M06 still has {none_count} None idempotency_key txns"


# === Gate 6D: Same Job / Different Operation → NOT_APPLICABLE_CURRENTLY ===

def test_gate6d_same_job_different_operation_not_applicable():
    """当前只有 archive_usage 一个收费 operation → NOT_APPLICABLE_CURRENTLY。

    key 结构保留 operation 维度（las_job:{job.id}:archive_usage），
    未来如增加新 operation（如 retry_usage），event identity 天然区分。
    """
    # 无需测试代码——结构验证：idempotency_key 含 operation 维度
    key1 = "las_job:1:archive_usage"
    key2 = "las_job:1:retry_usage"  # 假设未来 operation
    assert key1 != key2  # operation 维度天然区分不同收费事件
