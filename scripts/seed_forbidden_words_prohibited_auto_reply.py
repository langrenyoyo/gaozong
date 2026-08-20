#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""幂等交付 prohibited_auto_reply 词库（P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1）。

本地测试库/服务器部署前 seed 入口。可重复执行，不重复插入，不新增 migration。
用法：python scripts/seed_forbidden_words_prohibited_auto_reply.py
"""

from __future__ import annotations

from app.database import SessionLocal
from app.services.forbidden_word_seed import seed_prohibited_auto_reply


def main() -> None:
    db = SessionLocal()
    try:
        result = seed_prohibited_auto_reply(db)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
