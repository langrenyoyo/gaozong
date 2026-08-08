"""P1 Stage 5A — M02+M05 Consumer 迁移验证 + Training DESIGN_GAP。

M02: webhook_event:{event.id}:lead_usage
M05: material_analysis:{material_id}:ark_v1
Training: DESIGN_GAP（training_id 在 _report_usage 之后才生成，无前置持久化身份）
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeAccount, ComputeMarkupRatio, ComputeTransaction,
    AiEditMaterial, AiEditMaterialAnalysis,
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
    for key in ("leads", "ai_edit"):
        session.add(ComputeMarkupRatio(capability_key=key, markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_s5", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


# === M02 Gate X-A: Same event duplicate → 1 txn ===

def test_m02_gate_xa_same_event_duplicate_one_txn(db):
    """同一 webhook event.id 重复 report → 1 txn。"""
    balance_before = get_or_create_account(db, "m_s5").balance_tokens

    r1 = record_usage(
        db, "m_s5", 100, capability_key="leads", source="other", model="test",
        usage_measurement_method="estimated_tokens",
        idempotency_key="webhook_event:42:lead_usage",
    )
    db.commit()
    r2 = record_usage(
        db, "m_s5", 100, capability_key="leads", source="other", model="test",
        usage_measurement_method="estimated_tokens",
        idempotency_key="webhook_event:42:lead_usage",
    )
    db.commit()

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "webhook_event:42:lead_usage"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_s5").balance_tokens
    assert delta == 100


# === M02 Gate X-B: Different events → 2 txn ===

def test_m02_gate_xb_different_events_two_txn(db):
    """不同 event.id → 2 txn。"""
    record_usage(db, "m_s5", 50, capability_key="leads", source="other", model="test",
                 usage_measurement_method="estimated_tokens",
                 idempotency_key="webhook_event:42:lead_usage")
    db.commit()
    record_usage(db, "m_s5", 50, capability_key="leads", source="other", model="test",
                 usage_measurement_method="estimated_tokens",
                 idempotency_key="webhook_event:43:lead_usage")
    db.commit()

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_s5",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2


# === M05 Gate X-A: Same material+version duplicate → 1 txn ===

def test_m05_gate_xa_same_material_version_duplicate_one_txn(db):
    """同一 material.id + version 重复 report → 1 txn。"""
    balance_before = get_or_create_account(db, "m_s5").balance_tokens

    r1 = record_usage(
        db, "m_s5", 100, capability_key="ai_edit", source="llm", model="ark-vlm",
        usage_measurement_method="provider_tokens",
        idempotency_key="material_analysis:77:ark_v1",
    )
    db.commit()
    r2 = record_usage(
        db, "m_s5", 100, capability_key="ai_edit", source="llm", model="ark-vlm",
        usage_measurement_method="provider_tokens",
        idempotency_key="material_analysis:77:ark_v1",
    )
    db.commit()

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "material_analysis:77:ark_v1"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_s5").balance_tokens
    assert delta == 100


# === M05 Gate X-B: Different materials → 2 txn ===

def test_m05_gate_xb_different_materials_two_txn(db):
    """不同 material.id → 2 txn。"""
    record_usage(db, "m_s5", 80, capability_key="ai_edit", source="llm", model="ark-vlm",
                 usage_measurement_method="provider_tokens",
                 idempotency_key="material_analysis:77:ark_v1")
    db.commit()
    record_usage(db, "m_s5", 80, capability_key="ai_edit", source="llm", model="ark-vlm",
                 usage_measurement_method="provider_tokens",
                 idempotency_key="material_analysis:78:ark_v1")
    db.commit()

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_s5",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2


# === Training DESIGN_GAP ===

def test_training_design_gap_documented():
    """Training training_id 在 _report_usage 之后才生成（DESIGN_GAP）。

    _build_answer 内部调 _report_usage（knowledge_training_service.py:539），
    training_id 在 _build_answer 返回后才生成（line 120）+ commit（line 144）。
    _report_usage 调用时 training_id 不存在 → 无法构造幂等键。

    DESIGN_GAP：需将 training_id 提前生成（在 _build_answer 前），属于业务逻辑改动，
    本轮不强迁。
    """
    # 代码事实确认（不改代码）
    from apps.xg_douyin_ai_cs.services import knowledge_training_service
    import inspect
    src = inspect.getsource(knowledge_training_service._build_answer)
    assert "_report_usage" in src  # _report_usage 在 _build_answer 内部
    assert "training_id" not in src.split("_report_usage")[0]  # training_id 在 _report_usage 后才生成
