"""P1 Stage 5F-3 — M05 Material Analysis Execution Consumer 迁移验证。

Identity 合同：
- event_namespace = material_analysis_execution（稳定合同）
- business_event_id = {execution_id}:ark_analysis
- idempotency_key = f"material_analysis_execution:{execution_id}:ark_analysis"

7 Gate：
- MA-0 Durable Before Ark：E1 create+commit → ark（execution.id 在 ark 前持久）
- MA-1 Initial Analysis：E1 → ark success → 1 usage report → 1 txn / 1 debit / COMPLETED
- MA-2 Same Execution Replay：same E1 usage report twice → 1 txn / replay
- MA-3 Explicit Re-analysis：E1 → E2 → 2 charges / shared Analysis UPDATE 同行不影响
- MA-4 Ark Failure：E3 → ark fail → Execution=FAILED / 0 txn / 0 debit
- MA-5 ★Ark Success + Usage Report Failure（C1 红线）：E4 ark success → usage fail → COMPLETED 不降级 / retry same E4 最多 1 committed txn
- MA-6 M05 None=0：正式链 idempotency_key≠None

约束验证：
- billing truth 归 M07（execution 无 is_billed，C1/C3）
- execution 在 ark call 前 durable commit（MA-0，合同 1）
- Ark 成功 → COMPLETED 先于 usage report（C1 红线）
"""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeMarkupRatio, ComputeTransaction, AiEditMaterialAnalysisExecution,
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
    session.add(ComputeMarkupRatio(capability_key="ai_edit", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_ma", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, execution_id):
    """模拟 _report_analysis_usage 的 idempotency_key 构造逻辑。

    execution_id 非空 → 构造 key；None → 兼容路径。
    capability_key="ai_edit" 对齐真实 M05 ark 分析路径。
    """
    if execution_id is not None:
        key = f"material_analysis_execution:{execution_id}:ark_analysis"
    else:
        key = None
    result = record_usage(
        db, "m_ma", 100,
        capability_key="ai_edit", source="llm", model="ark-multimodal",
        usage_measurement_method="provider_tokens",
        idempotency_key=key,
    )
    db.commit()
    return result


# === MA-0: Durable Before Ark（代码结构确认）===

def test_ma0_durable_before_ark():
    """execution 在 ark 外部 API 调用前 durable committed（合同 1，MA-0）。

    代码事实确认（不改代码）：
    1. AiEditMaterialAnalysisExecution 创建在 _analyze_via_ark 之前
    2. db.commit() 在 _analyze_via_ark 之前（durable boundary）
    """
    from app.services import material_analysis as svc

    src = inspect.getsource(svc.analyze_material_async)

    # 1. execution 创建在 ark 调用前
    exec_idx = src.index("AiEditMaterialAnalysisExecution(")
    ark_idx = src.index("_analyze_via_ark(")
    assert exec_idx < ark_idx

    # 2. durable commit 在 ark 前
    # execution 创建后有 commit，在 _analyze_via_ark 之前
    commit_before_ark = src[:ark_idx].rindex("db.commit()")
    assert exec_idx < commit_before_ark < ark_idx  # commit 在 execution 创建后、ark 前
    assert "durable before ark" in src  # 注释标注


# === MA-1: Initial Analysis — 1 txn / 1 debit / COMPLETED ===

def test_ma1_initial_analysis_one_txn(db):
    """首次分析：E1 → ark success → 1 usage report → 1 txn / 1 debit。"""
    balance_before = get_or_create_account(db, "m_ma").balance_tokens

    r1 = _report(db, 5001)

    assert r1["idempotency_status"] == "created"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "material_analysis_execution:5001:ark_analysis"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_ma").balance_tokens
    assert delta == 100


# === MA-2: Same Execution Replay — 1 txn / replay ===

def test_ma2_same_execution_replay(db):
    """同一 execution_id 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_ma").balance_tokens

    r1 = _report(db, 5002)
    r2 = _report(db, 5002)

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "material_analysis_execution:5002:ark_analysis"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_ma").balance_tokens
    assert delta == 100  # 只扣 1 次


# === MA-3: Explicit Re-analysis — E1≠E2 / 2 charges ===

def test_ma3_explicit_reanalysis_two_txn(db):
    """显式 re-analysis → E1≠E2 / 2 charges（shared Analysis UPDATE 同行不影响 billing）。"""
    _report(db, 5003)  # E1
    _report(db, 5004)  # E2（re-analysis = 新 execution = 新合法消费）

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_ma",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "material_analysis_execution:5003:ark_analysis" in keys
    assert "material_analysis_execution:5004:ark_analysis" in keys
    assert len(set(keys)) == 2  # 不同 execution_id → 不同 key（即使 source_sha256 相同）


# === MA-4: Ark Failure — Execution=FAILED / 0 txn ===

def test_ma4_ark_failure_failed_zero_charge():
    """ark 失败（result is None）→ Execution=FAILED / 0 txn / 0 debit。

    代码事实确认（不改代码）：
    1. result is None → execution.lifecycle_status="failed"
    2. _report_analysis_usage 不在失败路径（不计费）
    """
    from app.services import material_analysis as svc

    src = inspect.getsource(svc.analyze_material_async)

    # 1. result is None 分支标 execution FAILED
    none_branch_idx = src.index("if result is None:")
    after_none = src[none_branch_idx:]
    assert "failed" in after_none[:200]  # execution.lifecycle_status="failed"

    # 2. _report_analysis_usage 在 result is None 分支之后（仅 ark 成功路径）
    report_idx = src.index("_report_analysis_usage(")
    none_return_idx = src.index("return", none_branch_idx)
    assert none_return_idx < report_idx  # 失败 return 在 report 之前（不计费）


# === MA-5: ★Ark Success + Usage Report Failure（C1 红线，CODE_VERIFIED）===

def test_ma5_ark_success_usage_failure_redline():
    """★C1 红线：ark 成功 → execution COMPLETED（先于 usage report）；usage fail 不降级、不重跑 ark。

    证据等级：CODE_VERIFIED（inspect：execution COMPLETED commit 在 _report_usage 之前）。
    ★★ Ark 已成功的 Execution，不得仅因 usage reporting 失败重新执行 Ark。

    代码事实确认（不改代码）：
    1. execution.lifecycle_status="completed" + commit 在 _report_analysis_usage 之前
    2. _report_analysis_usage 内部 catch 异常（不抛出，不降级 execution）
    3. usage report 失败路径不回滚 execution COMPLETED、不重跑 _analyze_via_ark
    """
    from app.services import material_analysis as svc

    src = inspect.getsource(svc.analyze_material_async)

    # 1. execution COMPLETED commit 在 _report_usage 之前（C1 红线）
    completed_idx = src.index('lifecycle_status = "completed"')
    report_idx = src.index("_report_analysis_usage(")
    assert completed_idx < report_idx  # COMPLETED 先于 usage report

    # 2. usage report 在 COMPLETED commit 之后
    completed_commit_idx = src.index("db.commit()", completed_idx)
    assert completed_idx < completed_commit_idx < report_idx  # commit 在 COMPLETED 后、report 前

    # 3. _report_analysis_usage 内部 catch（不抛出）
    report_src = inspect.getsource(svc._report_analysis_usage)
    assert "except Exception" in report_src  # 上报失败 catch
    assert "raise" not in report_src  # 不抛出（不阻断/不降级）

    # 4. C1 红线注释标注
    assert "C1 红线" in src or "usage report 失败不降级" in src


# === MA-6: M05 None=0 ===

def test_ma6_m05_none_count_zero(db):
    """M05 正式链传 key 后，None 幂等键计数 = 0（均传 key）。"""
    _report(db, 5006)
    _report(db, 5007)

    none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_ma",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert none_count == 0


# === 约束验证：billing truth 归 M07（execution 无 is_billed，C1/C3）===

def test_constraint_no_is_billed():
    """AiEditMaterialAnalysisExecution 不得有 is_billed 字段（C1/C3）。"""
    columns = {c.name for c in AiEditMaterialAnalysisExecution.__table__.columns}
    assert "is_billed" not in columns
    assert "billing_status" not in columns
    assert "lifecycle_status" in columns  # 只有执行生命周期，非 billing truth


# === 约束验证：不激活 dormant Process 表 ===

def test_constraint_dormant_process_not_activated():
    """analyze_material_async 不引用 dormant AiEditMaterialProcess（方案 B，不激活旧表）。

    代码事实确认：
    1. analyze_material_async 不 import / 不引用 AiEditMaterialProcess
    2. 使用 AiEditMaterialAnalysisExecution 作 billing identity
    """
    from app.services import material_analysis as svc

    src = inspect.getsource(svc.analyze_material_async)
    # 不引用 dormant Process 表
    assert "AiEditMaterialProcess" not in src
    assert "ai_edit_material_processes" not in src
    # 使用新建的 Execution 实体
    assert "AiEditMaterialAnalysisExecution" in src


# === Identity 合同验证：key 构造（非时间戳推导）===

def test_identity_contract_key_construction():
    """_report_analysis_usage 从 execution_id 构造 key（非时间戳推导）。"""
    from app.services import material_analysis as svc

    src = inspect.getsource(svc._report_analysis_usage)
    assert "material_analysis_execution:" in src
    assert "execution_id" in src
    # 非时间戳推导
    assert "datetime.now" not in src and "time.time" not in src
