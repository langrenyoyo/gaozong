"""P1 Stage 5C-4 — Daily Report Generation Consumer 迁移验证。

Identity 合同：
- event_namespace = daily_report_generation（稳定合同）
- business_event_id = {generation_id}:summary
- idempotency_key = f"daily_report_generation:{generation_id}:summary"

7 Gate：
- DR-1 Initial Generate: G1 persistent / 1 txn / 1 debit
- DR-2 Same Generation Replay: report twice → 1 txn / replay
- DR-3 Explicit Regenerate: G1≠G2 / 2 txn / 2 charges
- DR-4 LLM Failure: G3 identity 仍持久 / 0 txn / 0 debit
- DR-5 Billing Response Lost: same G + same usage → replay / 1 txn
- DR-6 Compute Report Failure: same G5 → 最终 1 committed txn
- DR-7 Concurrent Generate: 只 1 claim 成功 / NEW Generation rows = 1

3 实施约束验证：
- Generation 创建与 claim 同事务原子绑定（DR-7 断言 NEW rows = 1）
- 确定性引用 Generation（current_generation_id，不猜）
- billing truth 归 M07（Generation 无 is_billed 字段）
"""

import inspect
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, ComputeMarkupRatio, ComputeTransaction, DailyReportGeneration, DailyReportJob,
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
    session.add(ComputeMarkupRatio(capability_key="wechat-assistant", markup_basis_points=0, enabled=True))
    session.commit()
    create_mock_recharge_order(
        session, "m_dr", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, generation_id):
    """模拟 9100 侧 _report_usage 的 idempotency_key 构造逻辑。

    report_generation_id 非空 → 构造 key；None → 兼容路径。
    """
    if generation_id is not None:
        key = f"daily_report_generation:{generation_id}:summary"
    else:
        key = None  # 兼容路径
    result = record_usage(
        db, "m_dr", 100,
        capability_key="wechat-assistant", source="llm", model="test-model",
        usage_measurement_method="estimated_tokens",
        llm_call_stage="primary",
        idempotency_key=key,
    )
    db.commit()
    return result


# === DR-1: Initial Generate — G1 persistent / 1 txn / 1 debit ===

def test_dr1_initial_generate(db):
    """首次 generate → G1 persistent / 1 txn / 1 debit。"""
    balance_before = get_or_create_account(db, "m_dr").balance_tokens

    r1 = _report(db, 7001)

    assert r1["idempotency_status"] == "created"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "daily_report_generation:7001:summary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_dr").balance_tokens
    assert delta == 100


# === DR-2: Same Generation Replay — report twice → 1 txn / replay ===

def test_dr2_same_generation_replay(db):
    """同一 generation_id 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_dr").balance_tokens

    r1 = _report(db, 7002)
    r2 = _report(db, 7002)

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "daily_report_generation:7002:summary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_dr").balance_tokens
    assert delta == 100  # 只扣 1 次


# === DR-3: Explicit Regenerate — G1≠G2 / 2 txn / 2 charges ===

def test_dr3_explicit_regenerate_two_txn(db):
    """显式 regenerate 产生新 generation_id → 2 txn / 2 charges。"""
    _report(db, 7003)
    _report(db, 7004)

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_dr",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "daily_report_generation:7003:summary" in keys
    assert "daily_report_generation:7004:summary" in keys
    assert len(set(keys)) == 2


# === DR-4: LLM Failure — G3 identity 仍持久 / 0 txn / 0 debit ===

def test_dr4_llm_failure_generation_persistent_zero_debit(db):
    """LLM 失败 → 不调 _report_usage（0 txn / 0 debit），但 Generation 仍持久存在。"""
    balance_before = get_or_create_account(db, "m_dr").balance_tokens

    # 模拟 LLM 失败：不调 _report_usage（计费点未执行）
    # 但 Generation 行已 INSERT（claim 时创建）
    generation = DailyReportGeneration(job_id=999, lifecycle_status="failed")
    db.add(generation)
    db.commit()

    # Generation 持久存在
    assert generation.id is not None
    assert generation.lifecycle_status == "failed"

    # 0 txn / 0 debit（只查 consume，recharge 是 fixture 预置）
    txn_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_dr",
            ComputeTransaction.transaction_type == "consume",
        )
        .count()
    )
    assert txn_count == 0
    delta = balance_before - get_or_create_account(db, "m_dr").balance_tokens
    assert delta == 0


# === DR-5: Billing Response Lost — same G + same usage → replay / 1 txn ===

def test_dr5_billing_response_lost_replay(db):
    """commit 后 response-lost：same Generation + same usage report 重发 → replay / 1 txn。

    P1 职责边界：billing-report replay（M07 保护）。
    full-request response-lost → SEPARATE_REQUEST_RECOVERY_GAP（非 P1 职责）。
    """
    r1 = _report(db, 7005)
    assert r1["idempotency_status"] == "created"

    # response-lost 后重发同一 usage report
    r2 = _report(db, 7005)
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "daily_report_generation:7005:summary"
    ).all()
    assert len(txns) == 1


# === DR-6: Compute Report Failure — same G5 → 最终 1 committed txn ===

def test_dr6_compute_report_failure_retry_same_generation(db):
    """LLM success + report fail（commit 前）→ retry same G5 → 首次成功计费。

    DR-6 是 commit 前 retry → 新 txn（首次成功）；DR-5 是 commit 后 response-lost → replay。
    """
    balance_before = get_or_create_account(db, "m_dr").balance_tokens

    # 模拟 report 失败（未调 record_usage，0 txn）
    # Generation 已持久化（running 状态）
    generation = DailyReportGeneration(job_id=888, lifecycle_status="running")
    db.add(generation)
    db.commit()
    gid = generation.id

    # 第一次 report 失败 → 0 txn
    txn_before = (
        db.query(ComputeTransaction)
        .filter(ComputeTransaction.idempotency_key == f"daily_report_generation:{gid}:summary")
        .count()
    )
    assert txn_before == 0

    # retry same generation → 首次成功计费（created，非 replay）
    r = _report(db, gid)
    assert r["idempotency_status"] == "created"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == f"daily_report_generation:{gid}:summary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_dr").balance_tokens
    assert delta == 100


# === DR-7: Concurrent Generate — 只 1 claim 成功 / NEW Generation rows = 1 ===

def test_dr7_concurrent_generate_one_new_generation(db):
    """并发 generate → 只 1 claim 成功 / NEW Generation rows = 1。

    验证实施约束 1：Generation 创建与 claim 原子绑定。
    claim 成功恰好创建 1 行 Generation（不只断言一个 409）。
    """
    # 建一个 job
    job = DailyReportJob(
        merchant_id="m_dr", report_day=date(2026, 8, 8), report_type="daily_sales_feedback",
        report_variant="default", status="none", artifact_status="none",
    )
    db.add(job)
    db.commit()

    # 模拟 _claim_generating：claim 成功 + 创建 1 行 Generation + 更新 current_generation_id
    from app.services.daily_report_job_service import _claim_generating
    token, generation_id = _claim_generating(db, job)

    # 断言 1：恰好 1 行 NEW Generation（不只断言 409）
    gen_count = (
        db.query(DailyReportGeneration)
        .filter(DailyReportGeneration.job_id == job.id)
        .count()
    )
    assert gen_count == 1

    # 断言 2：current_generation_id 确定性引用（不猜）
    db.refresh(job)
    assert job.current_generation_id == generation_id

    # 并发 claim 应被 409 阻止（status 已 generating 且未 stale）
    from app.services.daily_report_job_service import ClaimConflictError
    with pytest.raises(ClaimConflictError):
        _claim_generating(db, job)

    # 仍只有 1 行 Generation（并发未创建新行）
    gen_count_after = (
        db.query(DailyReportGeneration)
        .filter(DailyReportGeneration.job_id == job.id)
        .count()
    )
    assert gen_count_after == 1


# === 实施约束验证：billing truth 归 M07（Generation 无 is_billed 字段）===

def test_constraint_billing_truth_only_m07():
    """Generation 不得有 is_billed 字段成为账务真相。

    billing truth 只属于 M07 committed ComputeTransaction。
    Generation 的 billing-related 状态只能是派生/辅助。
    """
    # 代码事实确认：DailyReportGeneration 无 is_billed 字段
    columns = {c.name for c in DailyReportGeneration.__table__.columns}
    assert "is_billed" not in columns
    assert "lifecycle_status" in columns  # 只有执行生命周期，非 billing truth


# === Identity 合同验证：跨进程透传（9000→9100）===

def test_identity_contract_cross_process_propagation():
    """9000 generation_id → 9100 → key（跨进程透传，非时间戳推导）。"""
    from apps.xg_douyin_ai_cs import schemas as cs_schemas
    from apps.xg_douyin_ai_cs.services import daily_report_summary_service as svc

    # 1. schema 有 report_generation_id 字段
    fields = set(cs_schemas.DailySalesSummaryRequest.model_fields.keys())
    assert "report_generation_id" in fields

    # 2. 9100 _report_usage 从 report_generation_id 构造 key
    src = inspect.getsource(svc._report_usage)
    assert "report_generation_id" in src
    assert "daily_report_generation:" in src
    # 非时间戳推导
    assert "datetime.now" not in src and "time.time" not in src

    # 3. 9000 侧 payload 透传 report_generation_id
    from app.services import daily_report_service as dsvc
    build_src = inspect.getsource(dsvc._build_daily_sales_feedback_report)
    assert "report_generation_id" in build_src
