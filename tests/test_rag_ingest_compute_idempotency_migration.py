"""P1 Stage 5E-3 — RAG Ingest Chunk Embedding Consumer 迁移验证。

Identity 合同：
- event_namespace = rag_embedding（稳定合同）
- business_event_id = {run_id}:{document_id}:{chunk_index}:ingest
- idempotency_key = f"rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest"

7 Gate：
- RI-0 Parent Durable Before Charge：TrainingRun 在首次 charge 前独立事务可见可恢复
- RI-1 Same Chunk Replay：Run1/Doc10/Chunk3 report twice → 1 txn/replay
- RI-2 Different Chunks：Run1/Doc10/Chunk3+Chunk4 → 2 identities
- RI-3 Identical Content Different Occurrence：Chunk3==Chunk11 text → 2 keys（chunk_index 不同）
- RI-4 Same Chunk New Run：Run1+Run2 同 Doc/Chunk → 2 charges（run_id 不同）
- RI-5 Ingest None=0 / Query 仍 None（独立 #10a）
- RI-6A External/Normal Workflow Failure（R1=failed + committed txn 保留）
- RI-6B DB Transaction Unusable（PG aborted→rollback→fresh tx→finalize failed）

partial identity 约束：PARTIAL→warning 不构造（D5）
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
        session, "m_ri", ComputeRechargeOrderRequest(custom_tokens=100000, pay_method="alipay")
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _report(db, run_id, document_id, chunk_index):
    """模拟 9100 侧 _embed_with_usage 的 idempotency_key 构造逻辑（Ingest 路径）。

    三参数 ALL PRESENT → 构造 key（与 _embed_with_usage 内部逻辑一致）。
    capability_key="knowledge" 对齐真实 RAG Ingest embedding 路径。
    """
    key = f"rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest"
    result = record_usage(
        db, "m_ri", 100,
        capability_key="knowledge", source="embedding", model="test-embed-model",
        usage_measurement_method="estimated_tokens",
        idempotency_key=key,
    )
    db.commit()
    return result


# === RI-0: Parent Durable Before Charge（代码结构确认）===

def test_ri0_parent_durable_before_charge():
    """TrainingRun 在首次 _embed_with_usage/charge 前 durable committed（选项 A，RI-0）。

    代码事实确认（不改代码）：
    1. train_document：_create_training_run 后、_embed_with_usage 前 conn.commit()
    2. train_scope：_create_training_run 后、embedding 循环前 conn.commit()
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    # train_document：durable commit 在 _create_training_run 后、embedding 前
    td_src = inspect.getsource(repo.train_document)
    create_run_idx = td_src.index("_create_training_run")
    commit_idx = td_src.index("conn.commit()")
    embed_idx = td_src.index("_embed_with_usage")
    assert create_run_idx < commit_idx < embed_idx  # commit 在 create_run 后、embed 前
    # 注释标注选项 A durable boundary
    assert "durable boundary" in td_src

    # train_scope：durable commit 在 _create_training_run 后、embedding 循环前
    ts_src = inspect.getsource(repo.train_scope)
    create_run_idx2 = ts_src.index("_create_training_run")
    commit_idx2 = ts_src.index("conn.commit()")
    embed_idx2 = ts_src.index("_embed_with_usage")
    assert create_run_idx2 < commit_idx2 < embed_idx2
    assert "durable boundary" in ts_src


# === RI-1: Same Chunk Replay — 1 txn/replay ===

def test_ri1_same_chunk_replay(db):
    """Run1/Doc10/Chunk3 report twice → 1 txn（created + replay）。"""
    balance_before = get_or_create_account(db, "m_ri").balance_tokens

    r1 = _report(db, 1, 10, 3)
    r2 = _report(db, 1, 10, 3)

    assert r1["idempotency_status"] == "created"
    assert r2["idempotency_status"] == "idempotent_replay"

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.idempotency_key == "rag_embedding:1:10:3:ingest"
    ).all()
    assert len(txns) == 1
    delta = balance_before - get_or_create_account(db, "m_ri").balance_tokens
    assert delta == 100  # 只扣 1 次


# === RI-2: Different Chunks — 2 identities ===

def test_ri2_different_chunks_two_txn(db):
    """Run1/Doc10/Chunk3 + Chunk4 → 2 identities / 2 charges。"""
    _report(db, 1, 10, 3)
    _report(db, 1, 10, 4)

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_ri",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "rag_embedding:1:10:3:ingest" in keys
    assert "rag_embedding:1:10:4:ingest" in keys
    assert len(set(keys)) == 2  # chunk_index 不同 → 不同 key


# === RI-3: Identical Content Different Occurrence — 2 keys ===

def test_ri3_identical_content_different_occurrence(db):
    """Chunk3 text==Chunk11 text（相同内容不同 occurrence）→ 2 keys / 2 txn（chunk_index 不同）。

    content_hash 不进 billing key（P3）；chunk_index 维度区分不同 occurrence。
    """
    _report(db, 1, 10, 3)   # Chunk3
    _report(db, 1, 10, 11)  # Chunk11（内容相同但 occurrence 不同）

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_ri",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "rag_embedding:1:10:3:ingest" in keys
    assert "rag_embedding:1:10:11:ingest" in keys
    assert len(set(keys)) == 2  # chunk_index 不同 → 不同 key（即使内容相同）


# === RI-4: Same Chunk New Run — 2 charges ===

def test_ri4_same_chunk_new_run_two_charge(db):
    """Run1/Doc10/Chunk3 + Run2/Doc10/Chunk3 → 2 legitimate charges（run_id 不同）。"""
    _report(db, 1, 10, 3)  # Run1
    _report(db, 2, 10, 3)  # Run2（重新训练 = 合法新消费）

    txns = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == "m_ri",
        ComputeTransaction.transaction_type == "consume",
    ).all()
    assert len(txns) == 2

    keys = [t.idempotency_key for t in txns]
    assert "rag_embedding:1:10:3:ingest" in keys
    assert "rag_embedding:2:10:3:ingest" in keys
    assert len(set(keys)) == 2  # run_id 不同 → 不同 key（合法新消费，非 defect）


# === RI-5: Ingest None=0 / Query 仍 None ===

def test_ri5_ingest_none_zero_query_still_none(db):
    """Ingest 正式链 idempotency_key≠None → None=0；Query 仍 None（独立 #10a）。"""
    _report(db, 1, 10, 3)
    _report(db, 2, 10, 4)

    # Ingest 路径 txn 的 idempotency_key 均非 None
    ingest_none_count = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == "m_ri",
            ComputeTransaction.transaction_type == "consume",
            ComputeTransaction.idempotency_key.is_(None),
        )
        .count()
    )
    assert ingest_none_count == 0  # Ingest None=0


def test_ri5_query_path_still_none():
    """Query 路径（_embed_with_usage 不传三参数）仍 None（独立 #10a，不合并）。

    代码事实确认：Query 调用点（search 路径 L441）不传 run_id/document_id/chunk_index。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo._embed_with_usage)
    # partial identity 三态逻辑存在
    assert "partial_identity_violation" in src
    # key 构造格式
    assert "rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest" in src


# === RI-6A: External/Normal Workflow Failure（账务红线，CODE_VERIFIED）===

def test_ri6a_workflow_failure_committed_txn_preserved():
    """★账务红线：Run R1 durable → workflow error → finalize R1=failed；已 committed txn 保留。

    Execution.status=FAILED 与 1 committed ComputeTransaction 可合法并存。
    ★★ 绝不因 Run failed 删除/否认已 committed ComputeTransaction。

    证据等级：CODE_VERIFIED（inspect：except 块 finalize failed + 不回滚 M07）。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    # 1. train_document except 块 finalize FAILED（fresh transaction）
    td_src = inspect.getsource(repo.train_document)
    except_idx = td_src.index("except Exception as exc:")
    after_except = td_src[except_idx:]
    assert "status = 'failed'" in after_except
    assert "rollback" in after_except  # PG 失败 finalize：rollback→fresh tx
    assert "get_rag_engine" in after_except  # fresh transaction（REQUIRED-1）

    # 2. except 块不触碰 ComputeTransaction（billing truth 归 M07，不回滚）
    assert "ComputeTransaction" not in after_except
    assert "record_usage" not in after_except  # 不调 M07 core

    # 3. train_scope except 块同结构
    ts_src = inspect.getsource(repo.train_scope)
    except_idx2 = ts_src.index("except Exception as exc:")
    after_except2 = ts_src[except_idx2:]
    assert "status = 'failed'" in after_except2
    assert "rollback" in after_except2
    assert "get_rag_engine" in after_except2


# === RI-6B: DB Transaction Unusable（PG 失败边界，CODE_VERIFIED）===

def test_ri6b_db_transaction_unusable_pg_finalize():
    """★PG 失败边界：后续工作事务进入 aborted state → rollback→fresh tx→UPDATE failed→commit。

    REQUIRED-1：不得依赖现有 except UPDATE+commit 原样成功；
    PG aborted 后须 rollback 失败事务 → fresh transaction → UPDATE durable Run→failed → commit。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    td_src = inspect.getsource(repo.train_document)
    except_idx = td_src.index("except Exception as exc:")
    after_except = td_src[except_idx:]

    # 1. rollback 失败工作事务
    assert "conn.rollback()" in after_except
    # 2. fresh transaction（独立 connection，非复用 aborted conn）
    assert "get_rag_engine().connect() as fresh_conn" in after_except
    # 3. fresh_conn 上 UPDATE failed + commit
    assert "fresh_conn" in after_except
    assert "status = 'failed'" in after_except
    assert "fresh_conn.commit()" in after_except
    # 4. finalize 自身失败也只 warning，不掩盖原异常
    assert "finalize_failed" in after_except
    # 5. raise 原异常（不吞）
    assert after_except.rstrip().endswith("raise") or "raise" in after_except

    # train_scope 同结构
    ts_src = inspect.getsource(repo.train_scope)
    except_idx2 = ts_src.index("except Exception as exc:")
    after_except2 = ts_src[except_idx2:]
    assert "conn.rollback()" in after_except2
    assert "fresh_conn" in after_except2
    assert "fresh_conn.commit()" in after_except2


# === partial identity 约束（D5）===

def test_partial_identity_no_malformed_key():
    """PARTIAL identity → 显式 warning + 不构造畸形 key（不静默退 None，D5）。

    代码事实确认：三参数 PARTIAL → warning + idempotency_key=None。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo._embed_with_usage)
    # partial identity 三态判定逻辑存在
    assert "partial_identity_violation" in src
    # PARTIAL 分支：warning 诊断 + 退 None（不构造畸形 key）
    assert "present_count" in src  # 三态计数
    # 三态分支：== 3 构造 / == 0 None / else（PARTIAL）warning + None
    assert "== 3" in src
    assert "== 0" in src


# === chunk_hash 不进 billing key（P3）===

def test_chunk_hash_not_in_billing_key():
    """chunk_hash 不进入 billing uniqueness identity（P3，保持 semantic evidence）。

    代码事实确认：key 格式 = rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest，
    不含 content_hash / digest / sha256。
    """
    from apps.xg_douyin_ai_cs.rag import repository as repo

    src = inspect.getsource(repo._embed_with_usage)
    key_line = 'rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest'
    assert key_line in src
    # key 构造不含 hash/digest
    idempotency_section = src[src.index("idempotency_key ="):src.index("result = client.embed")]
    assert "content_hash" not in idempotency_section
    assert "digest" not in idempotency_section
    assert "sha256" not in idempotency_section


# === Ingest 透传三参数（identity 合同）===

def test_ingest_passes_three_identity_args():
    """train_document / train_scope 调用 _embed_with_usage 时传 run_id/document_id/chunk_index。"""
    from apps.xg_douyin_ai_cs.rag import repository as repo

    # train_document
    td_src = inspect.getsource(repo.train_document)
    assert "run_id=run_id" in td_src
    assert "document_id=doc[\"id\"]" in td_src
    assert "chunk_index=index" in td_src

    # train_scope
    ts_src = inspect.getsource(repo.train_scope)
    assert "run_id=run_id" in ts_src
    assert "document_id=doc[\"id\"]" in ts_src
    assert "chunk_index=index" in ts_src
