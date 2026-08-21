"""Emergency Hotfix：forbidden_word_hit_logs.context_id 超长审计保护 PG 回归测试。

根因（生产事故 2026-08-21）：check_forbidden_words 写审计日志时 context_id 传
base64 conversation_short_id（72 字符），列 VARCHAR(64) → StringDataRightTruncation
→ session pending rollback → outbox 崩溃 → 自动回复全挂。

修复：服务层 _normalize_context_id_for_log 长度收敛（≤64 原样；>64 用"可读前缀 +
SHA-256 截段"编码到 64，零 migration），仅审计路径降级、绝不阻断业务。

本文件使用本地 PostgreSQL（auto_wechat_outbox_test）验证：
1. 超长 context_id 命中违禁词 → 不抛异常、业务正常返回 hits；
2. ForbiddenWordHitLog.context_id 被收敛 ≤64（含前缀 + SHA 截段）；
3. WARNING 日志含 original_length / context_id_hash；
4. 正常 context_id（≤64）保持原样；
5. 审计降级不影响门禁判定（changed/hits 完整）。
"""

from __future__ import annotations

import hashlib
import logging
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ForbiddenWord, ForbiddenWordHitLog, ForbiddenWordLibrary

PG_URL = "postgresql+psycopg://postgres:change_me@127.0.0.1:5432/auto_wechat_outbox_test"


def _pg_available() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(
            "host=127.0.0.1 port=5432 user=postgres password=change_me dbname=auto_wechat_outbox_test",
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.fixture()
def pg_case():
    """PG 会话 + 唯一 merchant 命名空间（测试后清理）。"""
    engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    namespace = f"fw_audit_{uuid.uuid4().hex}"
    try:
        yield db, namespace
    finally:
        try:
            db.query(ForbiddenWordHitLog).filter(
                ForbiddenWordHitLog.merchant_id == namespace
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()
        engine.dispose()


def _seed_finance_library(db, merchant: str) -> None:
    """幂等插入 finance_compliance 词库 + '首付' 词条（命中即触发审计）。"""
    lib = (
        db.query(ForbiddenWordLibrary)
        .filter(ForbiddenWordLibrary.library_key == "finance_compliance")
        .first()
    )
    if lib is None:
        lib = ForbiddenWordLibrary(
            library_key="finance_compliance",
            name="金融合规",
            scope="global",
            enabled=True,
            sort_order=0,
        )
        db.add(lib)
        db.flush()
    if not db.query(ForbiddenWord).filter_by(library_id=lib.id, word="首付").first():
        db.add(
            ForbiddenWord(
                library_id=lib.id,
                word="首付",
                severity="high",
                enabled=True,
                hit_count=0,
            )
        )
    db.commit()


LONG_CONTEXT_ID = "@9VxWzqPHW8E4PX2vc4woV87902DrPvyDPp1zrAuvL1gSaff960zdRmYqig357zEBSv8+UZgSU1E4RlkHQS3tJA=="  # 72 字符


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_audit_long_context_id_does_not_break_business(pg_case, caplog):
    """超长 context_id 命中违禁词：不抛异常、业务 hits 完整、审计截断落库、warning 可观测。"""
    from app.services.forbidden_word_service import check_forbidden_words

    db, namespace = pg_case
    _seed_finance_library(db, namespace)

    with caplog.at_level(logging.WARNING, logger="app.services.forbidden_word_service"):
        result = check_forbidden_words(
            db,
            merchant_id=namespace,
            source="douyin_ai_auto_reply_pre_llm",
            content="你们有什么首付分期方案吗",
            context={"context_type": "conversation", "context_id": LONG_CONTEXT_ID},
        )
        db.commit()

    # 业务不中断：命中完整返回（changed=True + hits 含首付）
    assert result.changed is True
    assert [h.word for h in result.hits] == ["首付"]

    # 审计落库：context_id 收敛 ≤64（可读前缀 + SHA 截段编码）
    log = (
        db.query(ForbiddenWordHitLog)
        .filter(ForbiddenWordHitLog.merchant_id == namespace)
        .order_by(ForbiddenWordHitLog.id.desc())
        .first()
    )
    assert log is not None, "审计日志应落库"
    assert len(log.context_id) <= 64, f"context_id 必须收敛 ≤64: {len(log.context_id)}"
    assert log.context_id.startswith(LONG_CONTEXT_ID[:40]), "应保留可读前缀"
    assert log.context_id.endswith(hashlib.sha256(LONG_CONTEXT_ID.encode("utf-8")).hexdigest()[:23])

    # warning 可观测：original_length + context_id_hash
    assert any("context_id_truncated" in r.message for r in caplog.records)
    assert any(f"original_length={len(LONG_CONTEXT_ID)}" in r.message for r in caplog.records)
    assert any(
        f"context_id_hash={hashlib.sha256(LONG_CONTEXT_ID.encode('utf-8')).hexdigest()}" in r.message
        for r in caplog.records
    )


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_audit_short_context_id_kept_unchanged(pg_case):
    """正常 context_id（≤64）保持原样，不触发 warning。"""
    from app.services.forbidden_word_service import check_forbidden_words

    db, namespace = pg_case
    _seed_finance_library(db, namespace)

    short_id = "conv-12345"
    result = check_forbidden_words(
        db,
        merchant_id=namespace,
        source="return_visit_send",
        content="这个首付方案怎么样",
        context={"context_type": "return_visit_run", "context_id": short_id},
    )
    db.commit()

    assert result.changed is True
    log = (
        db.query(ForbiddenWordHitLog)
        .filter(ForbiddenWordHitLog.merchant_id == namespace)
        .order_by(ForbiddenWordHitLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.context_id == short_id, "短 context_id 应原样保留"


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_audit_normalize_keeps_64_boundary():
    """归一化函数边界：≤64 原样；>64 收敛到 64。"""
    from app.services.forbidden_word_service import _normalize_context_id_for_log

    assert _normalize_context_id_for_log("conv-12345") == "conv-12345"
    normalized = _normalize_context_id_for_log(LONG_CONTEXT_ID)
    assert len(normalized) == 64, f"超长收敛应精确 64: {len(normalized)}"
