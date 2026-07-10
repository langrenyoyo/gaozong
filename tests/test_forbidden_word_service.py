"""违禁词统一替换服务单元测试。

覆盖 Phase 2 执行包 Task 1 要求的 8 个场景：
单词命中、长短词重叠、英文大小写、重复命中累计、禁用词库/词条、空安全词、
摘要脱敏、空内容 no-op。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.database import Base
from app.models import ForbiddenWord, ForbiddenWordHitLog, ForbiddenWordLibrary
from app.services.forbidden_word_service import (
    ForbiddenWordHit,
    ForbiddenWordReplacementResult,
    replace_forbidden_words,
    summarize_replacement_text,
)


# 模块级内存 SQLite，与 test_admin_autoreply_rollout_api 风格一致
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _fresh_db():
    _reset_db()
    yield


def _session():
    return TestSession()


def _seed(
    db,
    *,
    library_key: str = "used_car_sales_base",
    library_enabled: bool = True,
    scope: str = "global",
    words: list[tuple] | None = None,
) -> ForbiddenWordLibrary:
    """插入一个词库和若干词条。

    words 每项为 (word, safe_word) 或 (word, safe_word, enabled)。
    """
    lib = ForbiddenWordLibrary(
        library_key=library_key,
        name="测试词库",
        scope=scope,
        enabled=library_enabled,
        sort_order=0,
    )
    db.add(lib)
    db.flush()
    for spec in words or []:
        if len(spec) == 2:
            word, safe_word = spec
            enabled = True
        else:
            word, safe_word, enabled = spec
        db.add(
            ForbiddenWord(
                library_id=lib.id,
                word=word,
                safe_word=safe_word,
                enabled=enabled,
                hit_count=0,
            )
        )
    db.commit()
    return lib


def test_replace_forbidden_words_replaces_and_logs_hit():
    db = _session()
    _seed(db, words=[("现车很多", "可到店详询"), ("微信13800138000", "联系方式")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="我们现车很多，微信13800138000可以聊",
        context={"context_type": "douyin_conversation", "context_id": "conv-1"},
    )
    db.commit()

    assert result.changed is True
    assert result.final_content == "我们可到店详询，联系方式可以聊"
    assert [hit.word for hit in result.hits] == ["现车很多", "微信13800138000"]
    assert result.hits[0].count == 1
    assert result.hits[1].count == 1
    assert db.query(ForbiddenWordHitLog).count() == 2
    first_log = db.query(ForbiddenWordHitLog).first()
    assert "13800138000" not in first_log.before_text_summary
    # 审计 id 已回写
    assert result.audit_ids is not None
    assert len(result.audit_ids) == 2


def test_replace_forbidden_words_prefers_longest_word():
    db = _session()
    _seed(db, words=[("现车", "可咨询"), ("现车很多", "可到店详询")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车很多",
    )

    assert result.final_content == "可到店详询"
    assert [hit.word for hit in result.hits] == ["现车很多"]


def test_replace_forbidden_words_is_case_insensitive_for_latin_text():
    db = _session()
    _seed(db, words=[("loan", "financing")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="We offer Loan now",
    )

    assert result.changed is True
    assert "Loan" not in result.final_content
    assert "financing" in result.final_content
    assert result.hits[0].word == "loan"


def test_replace_forbidden_words_counts_repeated_hits_once_per_log_row():
    db = _session()
    _seed(db, words=[("现车", "现货")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车 现车 现车",
    )
    db.commit()

    # 同词出现 3 次：hits 里该词 count=3，日志只写 1 行，hit_count 累加 3
    assert len(result.hits) == 1
    assert result.hits[0].count == 3
    assert db.query(ForbiddenWordHitLog).count() == 1
    word_row = db.query(ForbiddenWord).filter_by(word="现车").one()
    assert word_row.hit_count == 3


def test_replace_forbidden_words_ignores_disabled_library_and_word():
    # 词库禁用：不替换、不写日志
    db = _session()
    _seed(db, library_enabled=False, words=[("现车", "现货")])
    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车",
    )
    assert result.changed is False
    assert result.final_content == "现车"
    assert db.query(ForbiddenWordHitLog).count() == 0

    # 词条禁用：同样不参与
    _reset_db()
    db2 = _session()
    _seed(db2, words=[("现车", "现货", False)])
    result2 = replace_forbidden_words(
        db2,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车",
    )
    assert result2.changed is False
    assert result2.final_content == "现车"
    assert db2.query(ForbiddenWordHitLog).count() == 0


def test_replace_forbidden_words_skips_blank_safe_word():
    db = _session()
    # safe_word 为空的词条不参与替换
    _seed(db, words=[("现车", ""), ("可到店", "现货")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车 可到店",
    )

    assert result.final_content == "现车 现货"
    assert [hit.word for hit in result.hits] == ["可到店"]


def test_replace_forbidden_words_masks_summary_sensitive_values():
    db = _session()
    _seed(db, words=[("现车很多", "可到店详询")])

    result = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车很多，手机13800138000，微信wxid_abc123456联系",
    )
    db.commit()

    assert result.changed is True
    log = db.query(ForbiddenWordHitLog).one()
    # 摘要不得出现明文手机号、明文微信号账号
    assert "13800138000" not in log.before_text_summary
    assert "wxid_abc123456" not in log.before_text_summary
    assert "138****8000" in log.before_text_summary
    assert "微信号[masked]" in log.before_text_summary


def test_replace_forbidden_words_empty_content_is_noop():
    db = _session()
    _seed(db, words=[("现车", "现货")])

    # 空内容
    r1 = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="",
    )
    assert r1.changed is False
    assert r1.final_content == ""
    assert r1.hits == []

    # 纯空白内容
    r2 = replace_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="   ",
    )
    assert r2.changed is False
    assert r2.hits == []

    # 无启用词：原文返回，不写日志
    _reset_db()
    db2 = _session()
    r3 = replace_forbidden_words(
        db2,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="普通内容没有违禁词",
    )
    assert r3.changed is False
    assert r3.final_content == "普通内容没有违禁词"
    assert r3.hits == []
    assert db2.query(ForbiddenWordHitLog).count() == 0


def test_summarize_replacement_text_folds_whitespace_and_truncates():
    # 折叠连续空白
    assert summarize_replacement_text("a   b\n\nc") == "a b c"
    # 超长截断追加 ...
    long_text = "x" * 200
    summary = summarize_replacement_text(long_text, max_len=160)
    assert summary.endswith("...")
    assert len(summary) == 160 + 3
