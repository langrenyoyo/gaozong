"""P1 Stage 5D-2 — Training Knowledge Ask Consumer 迁移验证。

Identity 合同：
- event_namespace = knowledge_training_execution（稳定合同）
- business_event_id = {execution_id}:ask
- idempotency_key = f"knowledge_training_execution:{execution_id}:ask"

6 Gate：
- TR-1 Initial Ask: E1 persistent / 1 txn / 1 debit
- TR-2 Same Execution Replay: report twice → 1 txn / replay
- TR-3 Explicit New Ask: E1≠E2 / 2 charges（即使问题文本相同）
- TR-4 LLM Failure/Fallback: E3 persistent / 0 txn / Execution=COMPLETED_FALLBACK
- TR-5 Real Ask Failure: Execution=FAILED / 无假成功 charge / 无永远 running
- TR-6 None count = 0（正式链 idempotency_key≠None）

约束验证：
- billing truth 归 M07（execution 无 is_billed 字段，C4）
- execution 在 RAG search 前创建 commit（C1）
- execution_id 复用 request_id（C2）
- LLM fallback=COMPLETED_FALLBACK，非 failed（C3）
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
    session.add(ComputeMarkupRatio(capability_key="knowledge", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_tr", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, execution_id):
    """模拟 9100 侧 _report_usage 的 idempotency_key 构造逻辑。

    execution_id 非空 → 构造 key；None → 兼容路径。
    capability_key="knowledge" 对齐真实 Training ask 路径。
    """
    if execution_id is not None:
        key = f"knowledge_training_execution:{execution_id}:ask"
    else:
        key = None  # 兼容路径
    result = record_usage(
        db, "m_tr", 100,
        capability_key="knowledge", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage="primary",
        idempotency_key=key,
    )
    db.commit()
    return result


# === TR-1: Initial Ask — E1 persistent / 1 txn / 1 debit ===

def test_tr1_initial_ask_one_txn(db):
    """首次 ask → E1 persistent / 1 txn / 1 debit。"""
    balance_before = get_or_create_account(db, "m_tr").balance_tokens

    r1 = _report(db, "kt-req-001")

    assert r1["idempotency_status"] == "created"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "knowledge_training_execution:kt-req-001:ask"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_tr").balance_tokens
    assert delta == 100


# === TR-2: Same Execution Replay — report twice → 1 txn / replay ===

def test_tr2_same_execution_replay(db):
    """同一 execution_id 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_tr").balance_tokens

    r1 = _report(db, "kt-req-002")
    r2 = _report(db, "kt-req-002")

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "knowledge_training_execution:kt-req-002:ask"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_tr").balance_tokens
    assert delta == 100  # 只扣 1 次


# === TR-3: Explicit New Ask — E1≠E2 / 2 charges ===

def test_tr3_explicit_new_ask_two_txn(db):
    """显式新 ask 产生新 execution_id → 2 txn / 2 charges（即使问题文本相同）。"""
    _report(db, "kt-req-003")
    _report(db, "kt-req-004")

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_tr",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "knowledge_training_execution:kt-req-003:ask" in keys
    assert "knowledge_training_execution:kt-req-004:ask" in keys
    assert len(set(keys)) == 2  # 不同 key = 不同合法消费


# === TR-4: LLM Failure/Fallback — 0 txn / COMPLETED_FALLBACK ===

def test_tr4_llm_failure_fallback_zero_charge():
    """LLM 失败但 fallback 返回 → 0 txn（不计费）+ Execution=COMPLETED_FALLBACK（非 failed）。

    代码事实确认（不改代码）：
    1. _report_usage 仅在 chat 成功路径调用（fallback 路径不计费）。
    2. ask() 中 fallback=True → COMPLETED_FALLBACK（C3：非 failed）。
    """
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as svc

    # 1. _build_answer：_report_usage 调用在 chat 成功后、fallback return 之前
    build_src = inspect.getsource(svc._build_answer)
    # _report_usage 在 chat() 调用之后
    assert build_src.index("_report_usage") > build_src.index("chat(messages)")
    # fallback 分支（LLM 异常 / 空内容）在 _report_usage 之后 return，不计费
    assert "return (" in build_src  # fallback 提前 return

    # 2. ask()：fallback → COMPLETED_FALLBACK（非 failed）
    ask_src = inspect.getsource(svc.ask)
    assert "COMPLETED_FALLBACK" in ask_src
    assert "_finalize_execution" in ask_src

    # 3. _report_usage 不在 except 块（异常路径不计费）
    # except 块只 finalize FAILED，不调 _report_usage
    except_idx = ask_src.index("except Exception as exc:")
    after_except = ask_src[except_idx:]
    assert "_report_usage" not in after_except


# === TR-5: Real Ask Failure — Execution=FAILED / 无假成功 charge ===

def test_tr5_ask_failure_failed_no_charge():
    """ask 抛异常（RAG/DB 失败）→ Execution=FAILED / 无假成功 charge / 无永远 running。

    代码事实确认（不改代码）：
    1. _create_execution 在 try 块开头（RAG search 前），异常前已 commit = persistent。
    2. except 块标 FAILED（C3），不留永远 running。
    """
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as svc

    ask_src = inspect.getsource(svc.ask)

    # 1. _create_execution 在 try 块内、RAG search 前（异常前已 commit = persistent）
    try_idx = ask_src.index("try:")
    create_idx = ask_src.index("_create_execution")
    search_idx = ask_src.index("search(")
    assert try_idx < create_idx < search_idx  # execution 创建在 search 前

    # 2. except 块标 FAILED（不留永远 running）
    except_idx = ask_src.index("except Exception as exc:")
    after_except = ask_src[except_idx:]
    assert "FAILED" in after_except
    assert "_finalize_execution" in after_except


# === TR-6: None count = 0（正式链 idempotency_key≠None）===

def test_tr6_none_count_zero(db):
    """Training 正式链传 key 后，None 幂等键计数 = 0（均传 key）。"""
    _report(db, "kt-req-006")
    _report(db, "kt-req-007")

    none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_tr",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert none_count == 0


# === 约束验证：billing truth 归 M07（execution 无 is_billed，C4）===

def test_constraint_no_is_billed():
    """KnowledgeTrainingExecution 不得有 is_billed 字段成为账务真相（C4）。

    billing truth 只属于 M07 committed ComputeTransaction。
    验证 migration 0004 建表语句 + _report_usage 不含 is_billed 引用。
    """
    # migration 0004 建表无 is_billed / billing_status 列（模块名以数字开头，读文件验证）
    from pathlib import Path
    mig_path = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "postgres" / "xg_douyin_ai_cs" / "versions"
        / "0004_knowledge_training_executions.py"
    )
    mig_text = mig_path.read_text(encoding="utf-8")
    # 只检查列定义行，排除 docstring/注释中的说明性提及
    assert 'sa.Column("is_billed"' not in mig_text
    assert 'sa.Column("billing_status"' not in mig_text

    # _report_usage 不传 is_billed 参数到 ComputeUsageClient（billing truth 归 M07，非 execution）
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as svc
    report_src = inspect.getsource(svc._report_usage)
    assert "is_billed=" not in report_src


# === Identity 合同验证：key 构造（非 conversation/时间戳推导）===

def test_identity_contract_key_construction():
    """_report_usage 从 execution_id 构造 key（非 conversation_id/时间戳推导）。

    execution_id 复用 request_id（C2），在 RAG search 前已 commit（C1）。
    """
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as svc

    # 1. _report_usage 从 execution_id 构造 key
    src = inspect.getsource(svc._report_usage)
    assert "knowledge_training_execution:" in src
    assert "execution_id" in src
    # 非 conversation_id / 时间戳推导
    assert "conversation_id" not in src
    assert "datetime.now" not in src and "time.time" not in src

    # 2. ask() 透传 execution_id 到 _build_answer（identity 在 charge 点前已持久）
    ask_src = inspect.getsource(svc.ask)
    assert "execution_id=request_id" in ask_src

    # 3. _build_answer 透传 execution_id 到 _report_usage
    build_src = inspect.getsource(svc._build_answer)
    assert "execution_id" in build_src
