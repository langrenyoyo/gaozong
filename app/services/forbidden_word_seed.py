"""prohibited_auto_reply 词库幂等 seed（P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1）。

Owner 批准的 seed-only 交付（DB_DELTA=SEED_ONLY，SCHEMA=NO，MIGRATION=NO）：
- 复用既有 forbidden_word_libraries / forbidden_words 表，不新增字段/表/migration；
- 幂等：词库按 library_key 唯一、词条按 (library_id, word) 唯一，可重复执行不重复插入；
- 不覆盖已有词库配置与词条运营状态（只插入缺失项）；
- 仅包含 Owner 批准四词：黑户 / 老赖 / 我黑了 / 征信花了；
- 排除：贷款 / 金融 / 分期 / 征信（单词）不得进入本库。

交付入口：scripts/seed_forbidden_words_prohibited_auto_reply.py（CLI）；测试直接调用本函数。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ForbiddenWord, ForbiddenWordLibrary

LIBRARY_KEY = "prohibited_auto_reply"
LIBRARY_NAME = "禁止自动回复"
LIBRARY_DESC = "命中后阻断当前客户消息进入 AI 自动回复（仅当前消息，不改变会话状态）"
WORDS = ["黑户", "老赖", "我黑了", "征信花了"]
SEVERITY = "critical"


def seed_prohibited_auto_reply(db: Session) -> dict:
    """幂等插入 prohibited_auto_reply 词库与 4 词条，返回统计。"""
    lib = db.query(ForbiddenWordLibrary).filter_by(library_key=LIBRARY_KEY).first()
    if lib is None:
        lib = ForbiddenWordLibrary(
            library_key=LIBRARY_KEY,
            name=LIBRARY_NAME,
            description=LIBRARY_DESC,
            scope="global",
            enabled=True,
            sort_order=0,
        )
        db.add(lib)
        db.flush()

    inserted = 0
    for word in WORDS:
        exists = db.query(ForbiddenWord).filter_by(library_id=lib.id, word=word).first()
        if exists is None:
            db.add(
                ForbiddenWord(
                    library_id=lib.id,
                    word=word,
                    safe_word=None,
                    severity=SEVERITY,
                    enabled=True,
                    hit_count=0,
                )
            )
            inserted += 1
    db.commit()
    return {
        "library_key": LIBRARY_KEY,
        "words_total": len(WORDS),
        "inserted": inserted,
    }
