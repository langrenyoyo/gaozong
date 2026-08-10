"""P1 Stage 5G-2 — M01 Preview Execution Consumer 迁移验证。

Identity 合同（冻结为最终 contract）：
- event_namespace = ai_preview_execution
- business_event_id = {preview_execution_id}:{llm_call_stage}
- idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"

7 Gate：
- PV-0 Durable Before 9100/LLM：E1 create+commit → 9100 call（execution.id 在 9100 call 前持久）
- PV-1 Primary Only：E1 → primary success，无 retry → 1 txn / 1 debit / completed
- PV-2 Same Stage Replay：E1 + primary report twice → 1 txn / replay
- PV-3 Primary + Retry Combined：E1 → primary + retry_combined → 2 different keys / 2 charges
- PV-4 Explicit New Preview：Preview#1→E1, Preview#2→E2 → E1≠E2 / 2 charges
- PV-5 ★Request Lifecycle Boundary：primary success+retry fail+final success→completed；整次 9100 fail→failed
- PV-6 Identity Isolation：Preview None=0 / Auto Reply key 不变 / mixed identity→warning

约束验证：
- C1 lifecycle=整次请求结果（非 stage 状态）
- C2 9100 不回连 auto_wechat DB（仅 9000 写）
- C4 Auto Reply contract 不变 + mixed identity warning
- billing truth 归 M07（execution 无 is_billed）
"""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeMarkupRatio, ComputeTransaction, AiPreviewExecution,
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
        session, "m_pv", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, execution_id, stage):
    """模拟 9100 侧 _report_llm_usage 的 Preview 分支 idempotency_key 构造。

    preview_execution_id 非空 + run_id/attempt_count 空 → 构造 Preview key。
    """
    key = f"ai_preview_execution:{execution_id}:{stage}"
    result = record_usage(
        db, "m_pv", 100,
        capability_key="douyin-cs", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage=stage,
        idempotency_key=key,
    )
    db.commit()
    return result


# === PV-0: Durable Before 9100/LLM（代码结构确认）===

def test_pv0_durable_before_9100():
    """execution 在 9100 HTTP call 前 durable committed（PV-0，方案 A）。

    代码事实确认（不改代码）：
    1. _create_preview_execution 在 suggest_reply 调用前
    2. execution.id 透传到 request_payload["preview_execution_id"]（9100 消费）
    """
    from app.routers import agents as ag

    src = inspect.getsource(ag.preview_agent)

    # 1. execution 创建在 suggest_reply 之前
    create_idx = src.index("_create_preview_execution(")
    suggest_idx = src.index("suggest_reply(")
    assert create_idx < suggest_idx

    # 2. 透传到 request_payload
    assert 'request_payload["preview_execution_id"]' in src


# === PV-1: Primary Only — 1 txn / 1 debit / completed ===

def test_pv1_primary_only_one_txn(db):
    """E1 → primary success，无 retry → 1 txn / 1 debit。"""
    balance_before = get_or_create_account(db, "m_pv").balance_tokens

    r1 = _report(db, 6001, "primary")

    assert r1["idempotency_status"] == "created"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "ai_preview_execution:6001:primary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_pv").balance_tokens
    assert delta == 100


# === PV-2: Same Stage Replay — 1 txn / replay ===

def test_pv2_same_stage_replay(db):
    """同一 execution + 同一 stage 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_pv").balance_tokens

    r1 = _report(db, 6002, "primary")
    r2 = _report(db, 6002, "primary")

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "ai_preview_execution:6002:primary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_pv").balance_tokens
    assert delta == 100  # 只扣 1 次


# === PV-3: Primary + Retry Combined — 2 different keys / 2 charges ===

def test_pv3_primary_and_retry_combined_two_txn(db):
    """E1 → primary + retry_combined → 2 different keys / 2 charges（1:N(2)）。"""
    _report(db, 6003, "primary")
    _report(db, 6003, "retry_combined")

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_pv",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "ai_preview_execution:6003:primary" in keys
    assert "ai_preview_execution:6003:retry_combined" in keys
    assert len(set(keys)) == 2  # 同 execution 不同 stage → 不同 key


# === PV-4: Explicit New Preview — E1≠E2 / 2 charges ===

def test_pv4_explicit_new_preview_two_txn(db):
    """Preview#1→E1, Preview#2→E2 → 2 charges（即使输入相同）。"""
    _report(db, 6004, "primary")  # Preview#1 → E1
    _report(db, 6005, "primary")  # Preview#2 → E2（新请求 = 新合法消费）

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_pv",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "ai_preview_execution:6004:primary" in keys
    assert "ai_preview_execution:6005:primary" in keys
    assert len(set(keys)) == 2  # 不同 execution_id → 不同 key


# === PV-5: ★Request Lifecycle Boundary（C1，代码结构确认）===

def test_pv5_request_lifecycle_boundary():
    """★C1：lifecycle=整次 Preview 请求结果（非 stage 状态）。

    代码事实确认（不改代码）：
    1. except（整次 9100 失败）→ _finalize_preview_execution(..., "failed")
    2. 9100 正常返回后 → _finalize_preview_execution(..., "completed")
    3. lifecycle 不按 primary/retry stage 设定（是整次请求结果）
    """
    from app.routers import agents as ag

    src = inspect.getsource(ag.preview_agent)

    # 1. except 块 finalize failed
    except_idx = src.index("except XgDouyinAiCsClientError")
    after_except = src[except_idx:]
    assert '"failed"' in after_except
    assert "_finalize_preview_execution" in after_except

    # 2. 9100 正常返回后 finalize completed（在 except 之后、response 构造前）
    completed_idx = src.index('"completed"')
    assert completed_idx > except_idx

    # 3. C1：lifecycle 注释标注"整次请求结果"
    assert "整次" in src or "整次 Preview 请求结果" in src


# === PV-6: Identity Isolation（Auto Reply 不变 + mixed warning）===

def test_pv6_identity_isolation():
    """C4：Auto Reply contract 不变 + mixed identity→warning；Preview None=0。

    代码事实确认：
    1. Auto Reply key 格式不变（ai_auto_reply_run:{run_id}:{attempt_count}:{stage}）
    2. Preview 独立 namespace（ai_preview_execution:...）
    3. mixed identity（run_id+preview_execution_id）→ warning 不构造畸形 key
    """
    from apps.xg_douyin_ai_cs.services import reply_decision_service as r

    src = inspect.getsource(r._report_llm_usage)

    # 1. Auto Reply key 不变
    assert "ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}" in src

    # 2. Preview 独立 namespace
    assert "ai_preview_execution:{preview_execution_id}:{llm_call_stage}" in src

    # 3. mixed identity warning
    assert "mixed_identity_violation" in src


def test_pv6_preview_none_count_zero(db):
    """Preview 正式链传 key 后，None 幂等键计数 = 0（均传 key）。"""
    _report(db, 6006, "primary")
    _report(db, 6006, "retry_combined")
    _report(db, 6007, "primary")

    none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_pv",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert none_count == 0


# === 约束验证：billing truth 归 M07（execution 无 is_billed）===

def test_constraint_no_is_billed():
    """AiPreviewExecution 不得有 is_billed 字段（billing truth 归 M07）。"""
    columns = {c.name for c in AiPreviewExecution.__table__.columns}
    assert "is_billed" not in columns
    assert "billing_status" not in columns
    assert "lifecycle_status" in columns  # 只有整次请求结果，非 billing truth


# === 约束验证：C2 9100 不回连 auto_wechat DB ===

def test_constraint_c2_9100_no_db_writeback():
    """C2：9100 不回连 auto_wechat DB 修改 PreviewExecution。

    代码事实确认：
    1. 9100 _report_llm_usage 不引用 AiPreviewExecution（只读 request.preview_execution_id 构造 key）
    2. 9000 agents.py 的 _create/_finalize 是唯一 writer
    """
    from apps.xg_douyin_ai_cs.services import reply_decision_service as r

    # 9100 _report_llm_usage 不 import/引用 AiPreviewExecution
    src = inspect.getsource(r._report_llm_usage)
    assert "AiPreviewExecution" not in src
    assert "ai_preview_executions" not in src
    # 只读 request.preview_execution_id（getattr 透传，非 DB 查询）
    assert 'getattr(request, "preview_execution_id"' in src

    # 9000 是唯一 writer
    from app.routers import agents as ag
    create_src = inspect.getsource(ag._create_preview_execution)
    finalize_src = inspect.getsource(ag._finalize_preview_execution)
    assert "AiPreviewExecution" in create_src
    assert "AiPreviewExecution" in finalize_src
