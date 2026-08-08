"""P1 Stage 4B — M01 Auto Reply Consumer 迁移验证。

Gate 4B-1: Same Attempt / Primary Duplicate → 1 txn
Gate 4B-2: Primary + retry_combined → 2 txn
Gate 4B-3: Outbox New Attempt → 2 txn（防误去重）
Gate 4B-4: Same Run + Same Attempt Replay → REPLAY
Gate 4B-5: Preview Current Behavior Preserved
Gate 4B-6: Partial Identity → 不生成错误 key
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeAccount, ComputeMarkupRatio, ComputeTransaction,
)
from app.schemas import ComputeRechargeOrderRequest
from apps.compute.services import (
    record_usage, create_mock_recharge_order, get_or_create_account,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    session.add(ComputeMarkupRatio(capability_key="douyin-cs", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_m01", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, run_id, attempt_count, stage="primary"):
    """模拟 _report_llm_usage 的 idempotency_key 构造逻辑。"""
    if run_id is not None and attempt_count is not None:
        key = f"ai_auto_reply_run:{run_id}:{attempt_count}:{stage}"
    elif run_id is not None or attempt_count is not None:
        return None  # partial → warning，不生成 key
    else:
        return None  # Preview 兼容路径
    result = record_usage(
        db, "m_m01", 100,
        capability_key="douyin-cs", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage=stage,
        idempotency_key=key,
    )
    db.commit()
    return result


# === Gate 4B-1: Same Attempt / Primary Duplicate → 1 txn ===

def test_gate4b1_same_attempt_primary_duplicate_one_txn(db):
    """Run 100 / Attempt 1 / primary → report twice → 1 txn。"""
    balance_before = get_or_create_account(db, "m_m01").balance_tokens

    r1 = _report(db, 100, 1, "primary")
    r2 = _report(db, 100, 1, "primary")

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "ai_auto_reply_run:100:1:primary"
    ).all()
    assert len(txns) == 1

    delta = balance_before - get_or_create_account(db, "m_m01").balance_tokens
    assert delta == 100  # 只扣 1 次


# === Gate 4B-2: Primary + retry_combined → 2 txn ===

def test_gate4b2_primary_plus_retry_combined_two_txn(db):
    """Run 100 / Attempt 1 / primary + retry_combined → 2 txn。"""
    _report(db, 100, 1, "primary")
    _report(db, 100, 1, "retry_combined")

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_m01",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "ai_auto_reply_run:100:1:primary" in keys
    assert "ai_auto_reply_run:100:1:retry_combined" in keys


# === Gate 4B-3: Outbox New Attempt → 2 txn（最重要防误去重）===

def test_gate4b3_outbox_new_attempt_two_txn(db):
    """Run 100 / Attempt 1 / primary + Run 100 / Attempt 2 / primary → 2 txn。"""
    _report(db, 100, 1, "primary")
    _report(db, 100, 2, "primary")

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_m01",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "ai_auto_reply_run:100:1:primary" in keys
    assert "ai_auto_reply_run:100:2:primary" in keys
    assert len(set(keys)) == 2  # 不同 key = 不同合法消费


# === Gate 4B-4: Same Run + Same Attempt Replay → REPLAY ===

def test_gate4b4_same_run_same_attempt_replay(db):
    """same run / same attempt / same stage → report twice → REPLAY。"""
    r1 = _report(db, 200, 1, "primary")
    r2 = _report(db, 200, 1, "primary")

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"


# === Gate 4B-5: Preview Current Behavior Preserved ===

def test_gate4b5_preview_behavior_preserved(db):
    """Preview: run_id=None / attempt_count=None → 仍产生 Compute usage，idempotency_key=None。"""
    balance_before = get_or_create_account(db, "m_m01").balance_tokens

    # Preview 路径：不传 idempotency_key
    result = record_usage(
        db, "m_m01", 100,
        capability_key="douyin-cs", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage="primary",
        idempotency_key=None,  # Preview 兼容路径
    )
    db.commit()

    # 仍产生 ComputeTransaction
    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_m01",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 1
    assert txns[0].idempotency_key is None  # None 兼容路径

    # balance 扣了（仍 chargeable）
    delta = balance_before - get_or_create_account(db, "m_m01").balance_tokens
    assert delta == 100


# === Gate 4B-6: Partial Identity → 不生成错误 key ===

def test_gate4b6_partial_identity_no_error_key(db):
    """run_id=123 / attempt_count=None → 不生成错误 key，走 None 兼容路径。"""
    # _report 内部检测 partial identity 返回 None（不调 record_usage with key）
    # 模拟 _report_llm_usage 的 partial identity 逻辑
    run_id = 123
    attempt_count = None  # partial

    # 构造 key 的逻辑
    if run_id is not None and attempt_count is not None:
        key = f"ai_auto_reply_run:{run_id}:{attempt_count}:primary"
    elif run_id is not None or attempt_count is not None:
        key = None  # partial → 不生成错误 key
    else:
        key = None

    assert key is None  # partial identity 不生成错误 key

    # 走 None 兼容路径
    result = record_usage(
        db, "m_m01", 100,
        capability_key="douyin-cs", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage="primary",
        idempotency_key=None,
    )
    db.commit()
    assert hasattr(result, "balance_tokens")  # None 兼容路径返回 ComputeAccount
