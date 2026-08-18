"""违禁词只检测/审计服务单元测试（G1-DELTA 后冻结方案）。

方案：违禁词只检测不替换（final_content == original_content），命中写 ForbiddenWordHitLog 审计。
覆盖：单词命中、长短词重叠、英文大小写、重复命中累计、禁用词库/词条、
safe_word 为空词条仍进入检测、摘要脱敏、空内容 no-op。
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
    check_forbidden_words,
    load_forbidden_words_for_llm,
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


def test_check_forbidden_words_detects_and_logs_hit():
    db = _session()
    _seed(db, words=[("现车很多", "可到店详询"), ("微信13800138000", "联系方式")])

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="我们现车很多，微信13800138000可以聊",
    )
    assert result.changed is True
    # 只检测不替换：final_content 恒等于原文
    assert result.final_content == "我们现车很多，微信13800138000可以聊"
    assert [hit.word for hit in result.hits] == ["现车很多", "微信13800138000"]
    assert result.hits[0].count == 1
    assert result.hits[1].count == 1
    assert db.query(ForbiddenWordHitLog).count() == 2
    first_log = db.query(ForbiddenWordHitLog).first()
    assert "13800138000" not in first_log.before_text_summary
    assert result.audit_ids is not None
    assert len(result.audit_ids) == 2


def test_check_forbidden_words_prefers_longest_word():
    db = _session()
    _seed(db, words=[("现车", "可到店"), ("现车很多", "可到店详询")])

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车很多",
    )
    # 长词优先命中：只命中"现车很多"一次
    assert result.changed is True
    assert result.final_content == "现车很多"
    assert [hit.word for hit in result.hits] == ["现车很多"]


def test_check_forbidden_words_is_case_insensitive_for_latin_text():
    db = _session()
    _seed(db, words=[("loan", "financing")])

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="Loan is not financing",
    )
    assert result.changed is True
    assert "Loan" in result.final_content  # 不替换
    assert result.hits[0].word == "loan"


def test_check_forbidden_words_counts_repeated_hits_once_per_log_row():
    db = _session()
    _seed(db, words=[("现车", "可到店")])

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车 现车 现车",
    )
    assert len(result.hits) == 1
    assert result.hits[0].count == 3
    assert db.query(ForbiddenWordHitLog).count() == 1

    word_row = db.query(ForbiddenWord).one()
    assert word_row.hit_count == 3


def test_check_forbidden_words_ignores_disabled_library_and_word():
    db = _session()
    _seed(db, library_enabled=False, words=[("现车", "可到店")])
    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车",
    )
    assert result.changed is False
    assert result.final_content == "现车"
    assert db.query(ForbiddenWordHitLog).count() == 0

    _reset_db()
    db2 = _session()
    _seed(db2, words=[("现车", "可到店", False)])
    result2 = check_forbidden_words(
        db2,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车",
    )
    assert result2.changed is False
    assert result2.final_content == "现车"
    assert db2.query(ForbiddenWordHitLog).count() == 0


def test_check_forbidden_words_includes_blank_safe_word_words():
    """safe_word 为空的词条仍进入检测（验收 9：safe_word 为空也能进入 LLM 检查与检测）。"""
    db = _session()
    _seed(db, words=[("现车", None), ("可到店", "可到店详询")])

    # LLM 检查词列表包含 safe_word 为空的词条
    llm_words = load_forbidden_words_for_llm(db)
    assert "现车" in llm_words
    assert "可到店" in llm_words

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车 现货",
    )
    assert result.changed is True
    assert result.final_content == "现车 现货"  # 不替换
    assert [hit.word for hit in result.hits] == ["现车"]


def test_check_forbidden_words_masks_summary_sensitive_values():
    db = _session()
    _seed(db, words=[("现车", "可到店"), ("微信13800138000", "联系方式")])

    result = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="现车 微信13800138000 wxid_abc123456",
    )
    assert result.changed is True
    assert len(result.hits) == 2
    logs = db.query(ForbiddenWordHitLog).all()
    assert len(logs) == 2
    for log in logs:
        # 完整手机号/微信号账号值不得进入摘要；掩码标记必须存在
        assert "13800138000" not in log.before_text_summary
        assert "wxid_abc123456" not in log.before_text_summary
        assert "微信号[masked]" in log.before_text_summary


def test_check_forbidden_words_empty_content_is_noop():
    db = _session()
    _seed(db, words=[("现车", "可到店")])

    # 空内容
    r1 = check_forbidden_words(
        db,
        merchant_id="merchant-1",
        source="douyin_ai_auto",
        content="",
    )
    assert r1.changed is False
    assert r1.final_content == ""
    assert r1.hits == []

    # 纯空白内容
    r2 = check_forbidden_words(
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
    r3 = check_forbidden_words(
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
