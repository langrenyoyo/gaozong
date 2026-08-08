"""P1 Stage 2 — M04 Consumer 迁移验证。

Gate 5: M04 Duplicate Result → 1 txn（原失败基线复跑）
Gate 5B: Two Different Tasks → 2 txn（反向场景）
Gate 5C: None Count = 0（M04 迁移后观测）
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeAccount, ComputeMarkupRatio, ComputeTransaction,
    DouyinLead, WechatTask,
)
from app.schemas import ComputeRechargeOrderRequest
from apps.compute.services import (
    record_usage, create_mock_recharge_order, get_or_create_account,
)
from app.services.wechat_task_service import _report_wechat_task_compute_usage


@pytest.fixture()
def db():
    """每个测试用独立内存库。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    # markup ratio
    session.add(ComputeMarkupRatio(capability_key="wechat-assistant", markup_basis_points=0, enabled=True))
    session.commit()
    # 充值
    create_mock_recharge_order(
        session, "m_m04", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _create_task(db, task_id=1, message="这是一条测试消息用于算力消耗估算", suffix=""):
    """创建一个 WechatTask + Lead（用于 _report_wechat_task_compute_usage）。"""
    lead = DouyinLead(
        merchant_id="m_m04",
        account_open_id=f"acc{suffix}", conversation_short_id=f"conv{suffix}",
        source_id=f"cust{suffix}", status="assigned", assigned_staff_id=1,
    )
    db.add(lead)
    db.flush()
    task = WechatTask(
        id=task_id, lead_id=lead.id, staff_id=1, task_type="notify_sales",
        target_nickname="test", message=message, mode="single_send", status="sent",
    )
    db.add(task)
    db.commit()
    return task


# === Gate 5: M04 Duplicate Result → 1 txn ===

def test_gate5_m04_duplicate_result_one_txn(db):
    """同一 WechatTask 重复调用 _report_wechat_task_compute_usage → 1 条 txn。"""
    task = _create_task(db)

    acct_before = get_or_create_account(db, "m_m04")
    balance_before = acct_before.balance_tokens

    # 第一次
    _report_wechat_task_compute_usage(db, task)
    db.commit()

    # 第二次（重复——模拟 result 重复提交）
    _report_wechat_task_compute_usage(db, task)
    db.commit()

    # 验证 1 条 txn
    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m04",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key == f"wechat_task:{task.id}:result_usage",
        )
        .all()
    )
    assert len(txns) == 1, f"Expected 1 txn, got {len(txns)}"

    # balance 只扣 1 次
    acct_after = get_or_create_account(db, "m_m04")
    delta = balance_before - acct_after.balance_tokens
    # tokens = max(1, len(message) // 2), markup=0, billed=tokens
    expected_tokens = max(1, len(task.message) // 2)
    assert delta == expected_tokens, f"Expected delta={expected_tokens}, got {delta}"


# === Gate 5B: Two Different Tasks → 2 txn ===

def test_gate5b_two_different_tasks_two_txn(db):
    """不同 WechatTask → 2 条 txn，balance 扣 2 次。"""
    task1 = _create_task(db, task_id=1, message="第一条消息", suffix="1")
    task2 = _create_task(db, task_id=2, message="第二条消息", suffix="2")

    _report_wechat_task_compute_usage(db, task1)
    db.commit()
    _report_wechat_task_compute_usage(db, task2)
    db.commit()

    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m04",
            ComputeTransaction.transaction_type == "consume",
        )
        .all()
    )
    assert len(txns) == 2, f"Expected 2 txn, got {len(txns)}"

    # 确认不同 idempotency_key
    keys = [t.idempotency_key for t in txns]
    assert f"wechat_task:{task1.id}:result_usage" in keys
    assert f"wechat_task:{task2.id}:result_usage" in keys
    assert len(set(keys)) == 2  # 两个不同的 key


# === Gate 5C: None Count = 0 ===

def test_gate5c_m04_no_none_idempotency_key(db):
    """M04 迁移后所有 charge-producing 调用均传 idempotency_key，None count = 0。"""
    task = _create_task(db)
    _report_wechat_task_compute_usage(db, task)
    db.commit()

    # 查 wechat-assistant capability 的 txn
    txns = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_m04",
            ComputeTransaction.capability_key == "wechat-assistant",
        )
        .all()
    )
    assert len(txns) > 0
    none_count = sum(1 for t in txns if t.idempotency_key is None)
    assert none_count == 0, f"M04 still has {none_count} None idempotency_key txns"
