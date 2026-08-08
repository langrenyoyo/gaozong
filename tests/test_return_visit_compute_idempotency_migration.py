"""P1 Stage 5C-1 — Return Visit Judge Consumer 迁移验证。

Identity 合同：
- event_namespace = return_visit_run（稳定合同）
- business_event_id = {run.id}:judge
- idempotency_key = f"return_visit_run:{run_id}:judge"

Gate 5C-1A: Same Run Duplicate → 1 txn（created + replay）
Gate 5C-1B: Different Runs → 2 txn（2 legitimate charges）
Gate 5C-1C: None count = 0（return_visit_run_id 非空时 key 必非 None）
Gate 5C-1D: Cross-process identity propagation（9000 run_id → 9100 → key，非 conversation/时间戳推导）
"""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ComputeMarkupRatio, ComputeTransaction
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
    session.add(ComputeMarkupRatio(capability_key="wechat-assistant", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_rv", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, run_id):
    """模拟 _report_usage 的 idempotency_key 构造逻辑（9100 侧）。

    return_visit_run_id 非空 → 构造 key；None → 兼容路径。
    """
    if run_id is not None:
        key = f"return_visit_run:{run_id}:judge"
    else:
        key = None  # 兼容路径
    result = record_usage(
        db, "m_rv", 100,
        capability_key="wechat-assistant", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage="primary",
        idempotency_key=key,
    )
    db.commit()
    return result


# === Gate 5C-1A: Same Run Duplicate → 1 txn ===

def test_gate5c1a_same_run_duplicate_one_txn(db):
    """同一 ReturnVisitRun.id 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_rv").balance_tokens

    r1 = _report(db, 500)
    r2 = _report(db, 500)

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "return_visit_run:500:judge"
    ).all()
    assert len(txns) == 1

    delta = balance_before - get_or_create_account(db, "m_rv").balance_tokens
    assert delta == 100  # 只扣 1 次


# === Gate 5C-1B: Different Runs → 2 txn ===

def test_gate5c1b_different_runs_two_txn(db):
    """不同 ReturnVisitRun.id → 2 txn（2 legitimate charges）。"""
    _report(db, 500)
    _report(db, 501)

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_rv",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "return_visit_run:500:judge" in keys
    assert "return_visit_run:501:judge" in keys
    assert len(set(keys)) == 2  # 不同 key = 不同合法消费


# === Gate 5C-1C: None count = 0（return_visit_run_id 非空时 key 必非 None）===

def test_gate5c1c_none_count_zero_when_run_id_present(db):
    """Return Visit 路径传 key 后，None 幂等键计数 = 0（均传 key）。"""
    _report(db, 500)
    _report(db, 501)

    # 所有 Return Visit 路径 txn 的 idempotency_key 均非 None
    none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_rv",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert none_count == 0


# === Gate 5C-1D: Cross-process identity propagation ===

def test_gate5c1d_cross_process_identity_propagation():
    """9000 run_id → 9100 → key（跨进程透传，非 conversation/时间戳推导）。

    代码事实确认（不改代码）：
    1. ReturnVisitJudgeRequest schema 有 return_visit_run_id 字段。
    2. 9100 _report_usage 从 request.return_visit_run_id 构造 key（非 conversation_id/时间戳）。
    3. 9000 _judge_via_9100 传 run.id 作为 return_visit_run_id（持久快照）。
    """
    from apps.xg_douyin_ai_cs import schemas as cs_schemas
    from apps.xg_douyin_ai_cs.services import return_visit_judge_service as judge_svc
    from app.services import return_visit_run_service as run_svc

    # 1. schema 有 return_visit_run_id 字段
    fields = set(cs_schemas.ReturnVisitJudgeRequest.model_fields.keys())
    assert "return_visit_run_id" in fields

    # 2. 9100 _report_usage 从 request.return_visit_run_id 构造 key
    report_src = inspect.getsource(judge_svc._report_usage)
    assert "return_visit_run_id" in report_src
    assert "return_visit_run:" in report_src
    # 非 conversation_id / 时间戳推导
    assert "conversation_id" not in report_src
    assert "datetime.now" not in report_src and "time.time" not in report_src

    # 3. 9000 _judge_via_9100 传 run.id 作为 return_visit_run_id
    judge_src = inspect.getsource(run_svc._judge_via_9100)
    assert "return_visit_run_id" in judge_src
    assert "run.id" in judge_src
