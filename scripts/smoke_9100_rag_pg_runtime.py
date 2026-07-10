"""验证 9100 RAG metadata 在 PostgreSQL RAG_DATABASE_URL 下 alembic upgrade + engine 连通。

P3-D / P3-D2 smoke：跑 alembic upgrade head 建 7 张 RAG metadata 表，
再用 create_rag_engine() 直连验证表存在。不写业务数据，不触碰 Milvus / 训练 / 回复逻辑。

用法：
  python scripts/smoke_9100_rag_pg_runtime.py \
      --database-url "postgresql://user:pass@127.0.0.1:5432/xg_douyin_ai_cs"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database_url import parse_database_url

ALEMBIC_INI = ROOT / "migrations" / "postgres" / "xg_douyin_ai_cs" / "alembic.ini"

EXPECTED_TABLES = {
    "knowledge_categories",
    "knowledge_documents",
    "knowledge_chunks",
    "rag_training_runs",
    "llm_call_logs",
    "knowledge_training_sessions",
    "knowledge_training_feedbacks",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()

    runtime = parse_database_url(args.database_url)
    if runtime.backend != "postgresql":
        print("SMOKE_FAILED: RAG_DATABASE_URL 必须是 PostgreSQL")
        return 2

    # alembic env.py 读 RAG_DATABASE_URL；PYTHONPATH 让 env.py 能 import app.database_url
    env = {**os.environ, "RAG_DATABASE_URL": args.database_url, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        ["python", "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("SMOKE_FAILED: alembic upgrade head 失败")
        print(result.stdout)
        print(result.stderr)
        return 1

    # create_rag_engine 真连接验证表存在（不写业务数据）
    sys.path.insert(0, str(ROOT))
    os.environ["RAG_DATABASE_URL"] = args.database_url
    from sqlalchemy import inspect

    from apps.xg_douyin_ai_cs.rag.database import create_rag_engine

    engine = create_rag_engine()
    try:
        existing = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    missing = EXPECTED_TABLES - existing
    if missing:
        print(f"SMOKE_FAILED: 缺失表 {sorted(missing)}")
        return 1

    print(f"database_url={runtime.safe_url}")
    print(f"tables={sorted(existing & EXPECTED_TABLES)}")
    print("SMOKE_PASS: 9100 RAG metadata PostgreSQL alembic upgrade + engine 连通就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
