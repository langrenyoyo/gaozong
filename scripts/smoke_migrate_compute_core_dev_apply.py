"""compute 两表数据迁移 dev apply smoke。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import migrate_compute_core_sqlite_to_postgres as migration


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
SYNTHETIC_MERCHANT_IDS = ("p3_f2_compute_smoke_a", "p3_f2_compute_smoke_b")
SYNTHETIC_ID_MIN = 9201000
SYNTHETIC_ID_MAX = 9202999


class SmokeError(RuntimeError):
    """dev apply smoke 失败。"""


def require_smoke_url() -> str:
    database_url = (os.getenv(SMOKE_ENV_NAME) or "").strip()
    if not database_url:
        raise SmokeError("缺少 SMOKE_DATABASE_URL")
    args = migration.parse_args(
        [
            "--sqlite-db-path",
            "fixture.db",
            "--postgres-url",
            database_url,
            "--apply",
            "--yes",
        ]
    )
    migration.validate_args(args, env=os.environ)
    return database_url


def run_alembic_upgrade(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "upgrade",
            "head",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).replace(database_url, migration.mask_database_url(database_url))
        raise SmokeError("Alembic upgrade head 失败:\n" + output)


async def cleanup_synthetic_rows(database_url: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(migration.to_asyncpg_dsn(database_url))
    try:
        async with conn.transaction():
            for table in ["compute_transactions", "compute_accounts"]:
                await conn.execute(
                    f'DELETE FROM "{table}" '
                    "WHERE (id BETWEEN $1 AND $2) OR merchant_id = ANY($3::text[])",
                    SYNTHETIC_ID_MIN,
                    SYNTHETIC_ID_MAX,
                    list(SYNTHETIC_MERCHANT_IDS),
                )
    finally:
        await conn.close()


def create_fixture_sqlite(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
            CREATE TABLE compute_accounts (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT NOT NULL,
                tenant_id TEXT,
                balance_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE compute_transactions (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT NOT NULL,
                tenant_id TEXT,
                transaction_type TEXT NOT NULL,
                delta_tokens INTEGER NOT NULL,
                balance_after_tokens INTEGER NOT NULL,
                source TEXT NOT NULL,
                remark TEXT,
                model TEXT,
                agent_id TEXT,
                conversation_id INTEGER,
                created_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO compute_accounts (
                    id, merchant_id, tenant_id, balance_tokens, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9201001,
                        SYNTHETIC_MERCHANT_IDS[0],
                        "tenant-smoke",
                        200,
                        "2026-07-09T10:00:00",
                        "2026-07-09T10:00:00",
                    ),
                    (
                        9201002,
                        SYNTHETIC_MERCHANT_IDS[1],
                        "tenant-smoke",
                        150,
                        "2026-07-09T10:01:00",
                        "2026-07-09T10:01:00",
                    ),
                ],
            )
            conn.exec_driver_sql(
                """
                INSERT INTO compute_transactions (
                    id, merchant_id, tenant_id, transaction_type, delta_tokens,
                    balance_after_tokens, source, remark, model, agent_id,
                    conversation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9202001,
                        SYNTHETIC_MERCHANT_IDS[0],
                        "tenant-smoke",
                        "recharge",
                        200,
                        200,
                        "manual_recharge",
                        "P3-F2 synthetic recharge",
                        None,
                        None,
                        None,
                        "2026-07-09T10:02:00",
                    ),
                    (
                        9202002,
                        SYNTHETIC_MERCHANT_IDS[1],
                        "tenant-smoke",
                        "consume",
                        -50,
                        150,
                        "llm",
                        "P3-F2 synthetic consume",
                        "smoke-model",
                        "smoke-agent",
                        92001,
                        "2026-07-09T10:03:00",
                    ),
                ],
            )
    finally:
        engine.dispose()


async def count_rows(database_url: str) -> dict[str, int]:
    import asyncpg

    conn = await asyncpg.connect(migration.to_asyncpg_dsn(database_url))
    try:
        return {
            table: int(
                await conn.fetchval(
                    f'SELECT count(*) FROM "{table}" WHERE merchant_id = ANY($1::text[])',
                    list(SYNTHETIC_MERCHANT_IDS),
                )
            )
            for table in migration.DEFAULT_TABLES
        }
    finally:
        await conn.close()


def main() -> int:
    database_url = ""
    try:
        database_url = require_smoke_url()
        print(f"PostgreSQL URL: {migration.mask_database_url(database_url)}")
        run_alembic_upgrade(database_url)
        asyncio.run(cleanup_synthetic_rows(database_url))
        with tempfile.TemporaryDirectory(prefix="p3_f2_compute_") as tmpdir:
            sqlite_path = Path(tmpdir) / "fixture.db"
            create_fixture_sqlite(sqlite_path)
            tables = migration.DEFAULT_TABLES
            source_rows = migration.read_sqlite_tables(str(sqlite_path), tables)
            snapshot = asyncio.run(migration.read_postgres_snapshot(database_url, tables))
            first_plan = migration.build_migration_plan(source_rows, snapshot, tables)
            migration.print_dry_run_plan(first_plan, migration.mask_database_url(database_url))
            if first_plan.total_insert < 4 or first_plan.total_errors:
                raise SmokeError("第一次 dry-run 计划不符合预期")
            result = asyncio.run(migration.apply_postgres_rows(database_url, source_rows, snapshot, tables))
            migration.print_apply_result(result)
            second_snapshot = asyncio.run(migration.read_postgres_snapshot(database_url, tables))
            second_plan = migration.build_migration_plan(source_rows, second_snapshot, tables)
            migration.print_dry_run_plan(second_plan, migration.mask_database_url(database_url))
            if second_plan.total_insert != 0:
                raise SmokeError("第二次 dry-run 仍计划 insert，幂等失败")
            counts = asyncio.run(count_rows(database_url))
            print(f"smoke row counts: {counts}")
            for table, count in counts.items():
                if count < 2:
                    raise SmokeError(f"{table} 行数不足: {count}")
            asyncio.run(cleanup_synthetic_rows(database_url))
    except Exception as exc:
        safe_message = str(exc)
        if database_url:
            safe_message = safe_message.replace(database_url, migration.mask_database_url(database_url))
        print(f"SMOKE_FAIL: {safe_message}")
        return 1
    print("SMOKE_PASS: compute core data migration dev apply ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
