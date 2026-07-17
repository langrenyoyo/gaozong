"""只读盘点 Task 12 重复素材。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 5。

安全约束：
- 不导入 app.database，不读取 DATABASE_URL/SMOKE_DATABASE_URL。
- 必须显式传 --database-url 或 --snapshot-mainline-sqlite（二选一）。
- SQLite 只接受已存在且不是仓库活动库 data/auto_wechat.db 的本地副本。
- PostgreSQL 只接受显式 --allow-local-test-postgres、回环主机、_test/_staging 库名、无 query。
- SQLite 用 migrations.migrate_sqlite.backup_database（backup API，正确处理 WAL）制作副本；
  PostgreSQL 查询前 SET TRANSACTION READ ONLY，结束回滚。
- 输出只含重复组总数与 sha256(merchant_id)[:12] + source_sha256[:12] + count，
  不回显 URL、用户名、密码、原 merchant ID。
"""

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from migrations.migrate_sqlite import MAINLINE_DB, backup_database

ACTIVE_SQLITE = Path(MAINLINE_DB).resolve()
LOCAL_PG_HOSTS = {"127.0.0.1", "localhost", "::1"}


def parse_args(argv: list[str] | None = None):
    parser = ArgumentParser(description="只读盘点 Task 12 重复素材")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database-url")
    source.add_argument("--snapshot-mainline-sqlite", action="store_true")
    parser.add_argument("--allow-local-test-postgres", action="store_true")
    return parser.parse_args(argv)


def snapshot_sqlite(source: str, destination: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path != ACTIVE_SQLITE or not source_path.is_file():
        raise ValueError("只允许从仓库活动 SQLite 制作一致性副本")
    if destination_path == ACTIVE_SQLITE:
        raise ValueError("副本目标不得覆盖活动 SQLite")
    migration_logger = logging.getLogger("migrate_sqlite")
    was_disabled = migration_logger.disabled
    migration_logger.disabled = True
    try:
        backup_database(source_path, destination_path)
    finally:
        migration_logger.disabled = was_disabled
    return destination_path


def validate_database_target(raw: str, *, allow_local_test_postgres: bool) -> URL:
    url = make_url(raw)
    if url.drivername.startswith("sqlite"):
        if not url.database or url.database == ":memory:":
            raise ValueError("盘点必须使用已落盘的 SQLite 数据库副本")
        copy_path = Path(url.database).expanduser().resolve()
        if copy_path == ACTIVE_SQLITE:
            raise ValueError("禁止直接盘点仓库活动 SQLite，必须先制作副本")
        if not copy_path.is_file():
            raise ValueError("SQLite 数据库副本不存在")
        return url
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("只允许 SQLite 副本或本地测试 PostgreSQL")
    if not allow_local_test_postgres:
        raise ValueError("本地测试 PostgreSQL 必须显式批准")
    if (url.host or "").lower() not in LOCAL_PG_HOSTS:
        raise ValueError("拒绝非回环 PostgreSQL 主机")
    database = (url.database or "").lower()
    if not database.endswith(("_test", "_staging")):
        raise ValueError("PostgreSQL 数据库名必须以 _test 或 _staging 结尾")
    if url.query:
        raise ValueError("盘点 URL 禁止 query 参数")
    return url


DUPLICATE_SQL = text("""
    SELECT merchant_id, source_sha256, count(*) AS duplicate_count
    FROM ai_edit_materials
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id, source_sha256
    HAVING count(*) > 1
    ORDER BY source_sha256
""")


def audit_duplicates(url: URL) -> list[dict[str, object]]:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                if url.drivername.startswith("postgresql"):
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                else:
                    conn.exec_driver_sql("PRAGMA query_only = ON")
                return [dict(row) for row in conn.execute(DUPLICATE_SQL).mappings()]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def report_duplicates(database_url: str, *, allow_local_test_postgres: bool) -> int:
    url = validate_database_target(
        database_url,
        allow_local_test_postgres=allow_local_test_postgres,
    )
    rows = audit_duplicates(url)
    for row in rows:
        merchant_fingerprint = sha256(str(row["merchant_id"]).encode("utf-8")).hexdigest()[:12]
        source_fingerprint = str(row["source_sha256"])[:12]
        print(f"merchant={merchant_fingerprint} source={source_fingerprint} count={row['duplicate_count']}")
    print(f"duplicate_groups={len(rows)}")
    return 2 if rows else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.snapshot_mainline_sqlite:
        with TemporaryDirectory(prefix="auto_wechat_task12_audit_") as temp_dir:
            copy_path = snapshot_sqlite(ACTIVE_SQLITE, Path(temp_dir) / "audit.db")
            return report_duplicates(
                f"sqlite+pysqlite:///{copy_path.as_posix()}",
                allow_local_test_postgres=False,
            )
    return report_duplicates(
        args.database_url,
        allow_local_test_postgres=args.allow_local_test_postgres,
    )


if __name__ == "__main__":
    raise SystemExit(main())
