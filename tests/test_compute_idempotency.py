"""P1 COMPUTE-IDEMPOTENCY-001 幂等核心测试。

覆盖 Gate 1（Sequential duplicate→1 txn）+ Gate 9（None 兼容）+
Gate 10（Same Key+Different Payload→CONFLICT）+ Gate 12（Retry After Pricing→REPLAY）。

技术方案：docs/architecture/remediation/P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ComputeTransaction, ComputeMarkupRatio, ComputeAccount
from app.schemas import ComputeRechargeOrderRequest
from apps.compute.services import (
    record_usage,
    create_mock_recharge_order,
    get_or_create_account,
)

# 用内存 SQLite 确保表结构含新列（create_all 含 ORM 新字段）
_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_TestSession = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db():
    """每个测试用独立内存库（不共享 engine，确保事务隔离不影响幂等 commit）。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    # 确保 markup ratio 存在
    for key in ("ai_edit", "wechat-assistant", "douyin-cs", "leads"):
        session.add(ComputeMarkupRatio(capability_key=key, markup_basis_points=0, enabled=True))
    session.commit()
    # 充值
    create_mock_recharge_order(
        session, "m_idem", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _consume_txns(db, merchant_id="m_idem"):
    return (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == merchant_id,
            ComputeTransaction.transaction_type == "consume",
        )
        .all()
    )


# === Gate 1: Sequential Duplicate ===

def test_gate1_sequential_duplicate_one_txn(db):
    """同一 idempotency_key 调用两次 → 1 条 transaction，balance delta = 1 × charge。"""
    acct_before = get_or_create_account(db, "m_idem")
    balance_before = acct_before.balance_tokens

    # 第一次
    r1 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate1:event1",
    )
    db.commit()
    assert r1["idempotency_status"] == "created"

    # 第二次（重复）
    r2 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate1:event1",
    )
    db.commit()
    assert r2["idempotency_status"] == "idempotent_replay"

    # 验证 1 条 txn
    txns = _consume_txns(db)
    idempotent_txns = [t for t in txns if t.idempotency_key == "test:gate1:event1"]
    assert len(idempotent_txns) == 1

    # balance delta = 1 × charge（不是 2 ×）
    acct_after = get_or_create_account(db, "m_idem")
    delta = balance_before - acct_after.balance_tokens
    assert delta == 100  # 只扣一次


# === Gate 9: None 兼容 ===

def test_gate9_none_compatible_old_path(db):
    """idempotency_key=None → 走旧逻辑（裸扣，不报错，返回 ComputeAccount）。"""
    acct_before = get_or_create_account(db, "m_idem")
    balance_before = acct_before.balance_tokens

    result = record_usage(
        db, "m_idem", 50, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key=None,
    )
    db.commit()

    # 旧路径返回 ComputeAccount（向后兼容）
    assert hasattr(result, "balance_tokens")
    acct_after = get_or_create_account(db, "m_idem")
    assert acct_after.balance_tokens == balance_before - 50


# === Gate 10: Same Key + Different Payload ===

def test_gate10_same_key_different_payload_conflict(db):
    """Same Key + Different Stable Payload → IDEMPOTENCY_CONFLICT，不扣费，不覆盖原流水。"""
    # 第一次（payload A）
    r1 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="model_A",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate10:event1",
    )
    db.commit()
    assert r1["idempotency_status"] == "created"
    original_evidence = (
        db.query(ComputeTransaction)
        .filter(ComputeTransaction.idempotency_key == "test:gate10:event1")
        .first()
    ).payload_evidence

    acct_before_conflict = get_or_create_account(db, "m_idem").balance_tokens

    # 第二次（payload B — model 不同）
    r2 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="model_B",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate10:event1",
    )
    db.commit()
    assert r2["idempotency_status"] == "idempotency_conflict"

    # balance 不变
    acct_after = get_or_create_account(db, "m_idem")
    assert acct_after.balance_tokens == acct_before_conflict

    # 原流水 evidence 不被覆盖
    after_evidence = (
        db.query(ComputeTransaction)
        .filter(ComputeTransaction.idempotency_key == "test:gate10:event1")
        .first()
    ).payload_evidence
    assert after_evidence == original_evidence


# === Gate 12: Retry After Pricing Change ===

def test_gate12_retry_after_pricing_change_replay(db):
    """首次 charge 后修改计费比例，同 idempotency_key retry → IDEMPOTENT_REPLAY，不重新定价。"""
    # 确保 ai_edit ratio 存在
    ratio = db.query(ComputeMarkupRatio).filter(ComputeMarkupRatio.capability_key == "ai_edit").first()
    original_basis = ratio.markup_basis_points if ratio else 0

    # 第一次 charge
    r1 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate12:event1",
    )
    db.commit()
    assert r1["idempotency_status"] == "created"

    acct_after_first = get_or_create_account(db, "m_idem").balance_tokens
    original_txn = (
        db.query(ComputeTransaction)
        .filter(ComputeTransaction.idempotency_key == "test:gate12:event1")
        .first()
    )
    original_delta = original_txn.delta_tokens

    # 修改计费比例
    ratio.markup_basis_points = 5000  # 50% 上浮
    db.commit()

    # 同 idempotency_key retry
    r2 = record_usage(
        db, "m_idem", 100, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate12:event1",
    )
    db.commit()
    assert r2["idempotency_status"] == "idempotent_replay"

    # balance 不变（不重新定价）
    acct_after_retry = get_or_create_account(db, "m_idem").balance_tokens
    assert acct_after_retry == acct_after_first

    # 原 txn delta 不变
    after_txn = (
        db.query(ComputeTransaction)
        .filter(ComputeTransaction.idempotency_key == "test:gate12:event1")
        .first()
    )
    assert after_txn.delta_tokens == original_delta

    # 恢复 ratio
    ratio.markup_basis_points = original_basis
    db.commit()


# === Gate 3: Two Legitimate Usages ===

def test_gate3_two_legitimate_usages_two_txns(db):
    """不同 idempotency_key → 2 条 transaction，balance delta = 2 × charge。"""
    acct_before = get_or_create_account(db, "m_idem")
    balance_before = acct_before.balance_tokens

    r1 = record_usage(
        db, "m_idem", 80, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate3:event1",
    )
    db.commit()
    r2 = record_usage(
        db, "m_idem", 80, capability_key="ai_edit", source="other", model="test",
        usage_measurement_method="estimated_tokens", idempotency_key="test:gate3:event2",
    )
    db.commit()

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "created"

    txns = [t for t in _consume_txns(db) if t.idempotency_key and t.idempotency_key.startswith("test:gate3:")]
    assert len(txns) == 2

    acct_after = get_or_create_account(db, "m_idem")
    delta = balance_before - acct_after.balance_tokens
    assert delta == 160  # 2 × 80
