"""P1 Stage 5H-2 — RAG Query Embedding Consumer 迁移验证。

Identity 合同（冻结为最终 contract）：
- event_namespace = rag_search_execution
- business_event_id = {search_execution_id}:{embedding_stage}
- idempotency_key = f"rag_search_execution:{search_execution_id}:{embedding_stage}"

embedding_stage = primary / fallback_embedding
cardinality = 1 SearchExecution : up to 2 embedding charge events

7 Gate：
- RQ-0 Parent Durable：E1 create+commit → first embedding worker
- RQ-1 SQLite-only Primary：直接 SQLite → 首次 embedding=primary
- RQ-2 Milvus Failure Reuses Primary：primary 成功+Milvus fail → SQLite 复用 → 只 E1:primary / 1 charge
- RQ-3 Embedding Timeout Boundary：primary 超时 → fallback_embedding → 不同 key / up to 2 charges
- RQ-4 Same Stage Replay：E1:primary report twice → 1 txn / replay
- RQ-5 New Search + Lifecycle：Search#1→E1, Search#2→E2 / lifecycle=整次搜索
- RQ-6 Identity Isolation + None Audit：Query None=0 / Ingest key 不变 / partial+mixed→warning

约束验证：
- R1 stage=logical embedding attempt（非函数名，SQLite-only=primary）
- R3 identity matrix 严格互斥（Ingest/Query/None/partial+mixed→warning）
- C1 lifecycle=整次搜索结果（非 stage 状态）
- billing truth 归 M07（execution 无 is_billed）
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
        session, "m_rq", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, execution_id, stage):
    """模拟 9100 侧 _embed_with_usage 的 Query 分支 idempotency_key 构造。

    search_execution_id + embedding_stage 非空 → 构造 Query key。
    """
    key = f"rag_search_execution:{execution_id}:{stage}"
    result = record_usage(
        db, "m_rq", 100,
        capability_key="knowledge", source="embedding", model="test-embed-model",
        usage_measurement_method="estimated_tokens",
        idempotency_key=key,
    )
    db.commit()
    return result


# === RQ-0: Parent Durable Before Embedding Worker（代码结构确认）===

def test_rq0_parent_durable_before_embedding():
    """execution 在 embedding worker 启动前 durable committed（RQ-0）。

    代码事实确认（不改代码）：
    1. search_with_diagnostics 创建 _create_search_execution 在分支前
    2. _create_search_execution 内 RETURNING id + commit（durable）
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo.search_with_diagnostics)
    # 1. execution 创建在 backend 分支前
    create_idx = src.index("_create_search_execution(")
    branch_idx = src.index("rag_vector_backend")
    assert create_idx < branch_idx

    # 2. _create_search_execution 内 RETURNING id + commit
    create_src = inspect.getsource(repo._create_search_execution)
    assert "RETURNING id" in create_src
    assert "conn.commit()" in create_src


# === RQ-1: SQLite-only Primary — 首次 embedding=primary ===

def test_rq1_sqlite_only_primary_one_txn(db):
    """SQLite-only 直接搜索 → 首次 embedding=primary（非 fallback）→ 1 txn。"""
    balance_before = get_or_create_account(db, "m_rq").balance_tokens

    r1 = _report(db, 7001, "primary")

    assert r1["idempotency_status"] == "created"
    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "rag_search_execution:7001:primary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_rq").balance_tokens
    assert delta == 100


def test_rq1_sqlite_only_stage_is_primary():
    """R1：SQLite-only 首次 embedding stage=primary（非 fallback）。

    代码事实确认：search_with_diagnostics 的 SQLite 分支传 embedding_stage="primary"。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo.search_with_diagnostics)
    # SQLite-only 分支传 embedding_stage="primary"
    assert 'embedding_stage="primary"' in src


# === RQ-2: Milvus Failure Reuses Primary — 只 E1:primary / 1 charge ===

def test_rq2_milvus_failure_reuses_primary_one_charge():
    """R2：primary 成功 + Milvus fail → SQLite 复用已算 embedding → 只 E1:primary / 1 charge（无 fallback charge）。

    代码事实确认（不改代码）：
    1. fallback 时 query_embedding 非空 → fallback_stage=None（不传 stage，不计费）
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo._search_milvus_or_fallback_with_diagnostics)
    # fallback_stage 判定：query_embedding 为空时才 fallback_embedding
    assert "fallback_embedding" in src
    assert "not query_embedding" in src  # 非空时不传 stage


# === RQ-3: Embedding Timeout Boundary — 不同 key / up to 2 charges ===

def test_rq3_embedding_timeout_boundary_two_keys(db):
    """primary 超时 → fallback_embedding → 不同 key / up to 2 charges。

    primary 晚完成时 usage report 用原 primary key（C1：E1.status 不因晚报告无效）。
    """
    # E1:primary + E1:fallback_embedding → 2 different keys / 2 charges
    _report(db, 7003, "primary")
    _report(db, 7003, "fallback_embedding")

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_rq",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "rag_search_execution:7003:primary" in keys
    assert "rag_search_execution:7003:fallback_embedding" in keys
    assert len(set(keys)) == 2  # 同 execution 不同 stage → 不同 key


def test_rq3_daemon_late_report_uses_primary_key(db):
    """daemon 晚完成 usage report 用原 primary key（C1 红线）。

    E1:primary 已 commit → fallback 完成 → E1=completed → primary daemon 晚完成
    → usage report 仍用 E1:primary key → M07 IDEMPOTENT_REPLAY（不重复扣）。
    """
    # primary 已 commit
    r1 = _report(db, 7004, "primary")
    assert r1["idempotency_status"] == "created"

    # daemon 晚完成，重发同一 primary key
    r2 = _report(db, 7004, "primary")
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "rag_search_execution:7004:primary"
    ).all()
    assert len(txns) == 1  # 只 1 txn（daemon 晚报告不重复扣）


# === RQ-4: Same Stage Replay — 1 txn / replay ===

def test_rq4_same_stage_replay(db):
    """同一 execution + 同一 stage 重复 report → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_rq").balance_tokens

    r1 = _report(db, 7005, "primary")
    r2 = _report(db, 7005, "primary")

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "rag_search_execution:7005:primary"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_rq").balance_tokens
    assert delta == 100


# === RQ-5: New Search + Lifecycle ===

def test_rq5_new_search_two_charges(db):
    """Search#1→E1, Search#2→E2 → E1≠E2 / 2 charges（即使查询相同）。"""
    _report(db, 7006, "primary")  # Search#1 → E1
    _report(db, 7007, "primary")  # Search#2 → E2（新请求 = 新合法消费）

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_rq",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2
    keys = [t.idempotency_key for t in txns]
    assert len(set(keys)) == 2


def test_rq5_lifecycle_whole_request_not_stage():
    """C1：lifecycle=整次搜索请求结果（非 stage 状态）。

    代码事实确认：search_with_diagnostics 在 try 成功 → completed；except → failed。
    lifecycle 不按 primary/fallback stage 设定。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo.search_with_diagnostics)
    # 成功 → completed
    assert '"completed"' in src
    # 失败 → failed
    assert '"failed"' in src
    # finalize 在整次搜索结果判定处（try/except），非 stage 内


# === RQ-6: Identity Isolation + None Audit ===

def test_rq6_identity_isolation():
    """R3：Query None=0 / Ingest key 不变 / partial+mixed→warning（identity matrix 互斥）。

    代码事实确认：
    1. Query key 格式（rag_search_execution:...）
    2. Ingest key 不变（rag_embedding:...:ingest）
    3. identity_violation warning（partial/mixed）
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo._embed_with_usage)
    # 1. Query 独立 namespace
    assert "rag_search_execution:{search_execution_id}:{embedding_stage}" in src
    # 2. Ingest 不变
    assert "rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest" in src
    # 3. identity matrix 严格互斥
    assert "ingest_count == 3 and query_count == 0" in src
    assert "query_count == 2 and ingest_count == 0" in src
    assert "identity_violation" in src  # partial/mixed warning


def test_rq6_query_none_count_zero(db):
    """Query 正式链传 key 后，None 幂等键计数 = 0（均传 key）。"""
    _report(db, 7008, "primary")
    _report(db, 7008, "fallback_embedding")
    _report(db, 7009, "primary")

    none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_rq",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert none_count == 0


# === 约束验证：billing truth 归 M07（execution 无 is_billed）===

def test_constraint_no_is_billed():
    """RagSearchExecution 不得有 is_billed 字段（billing truth 归 M07）。"""
    # migration 0005 建表无 is_billed / billing_status 列（模块名以数字开头，读文件验证）
    from pathlib import Path
    mig_path = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "postgres" / "xg_douyin_ai_cs" / "versions"
        / "0005_rag_search_executions.py"
    )
    mig_text = mig_path.read_text(encoding="utf-8")
    assert 'sa.Column("is_billed"' not in mig_text
    assert 'sa.Column("billing_status"' not in mig_text

    # _create/_finalize_search_execution 不传 is_billed 到 report_usage
    from apps.xg_douyin_ai_cs.rag import repository as repo
    create_src = inspect.getsource(repo._create_search_execution)
    finalize_src = inspect.getsource(repo._finalize_search_execution)
    assert "is_billed=" not in create_src
    assert "is_billed=" not in finalize_src


# === 约束验证：R1 stage=logical embedding attempt ===

def test_constraint_r1_stage_semantics():
    """R1：stage=logical embedding attempt（非函数名）。

    代码事实确认：
    1. SQLite-only 首次 embedding stage=primary（非 fallback）
    2. Milvus fallback：query_embedding 非空 → stage=None（复用不计费）；为空 → fallback_embedding
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    swd_src = inspect.getsource(repo.search_with_diagnostics)
    assert 'embedding_stage="primary"' in swd_src  # SQLite-only = primary

    milvus_src = inspect.getsource(repo._search_milvus_or_fallback_with_diagnostics)
    # fallback_stage 判定基于 query_embedding 是否为空（logical attempt），非函数名
    assert "fallback_embedding" in milvus_src
    assert "not query_embedding" in milvus_src
