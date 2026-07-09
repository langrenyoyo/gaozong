"""agents/accounts 四表数据迁移 dev apply smoke。"""

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

from scripts import migrate_agents_accounts_core_sqlite_to_postgres as migration


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
SYNTHETIC_MERCHANT_ID = "p3_e2_smoke"
SYNTHETIC_ID_MIN = 9101000
SYNTHETIC_ID_MAX = 9104999


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
            for table in [
                "agent_knowledge_categories",
                "douyin_account_agent_bindings",
                "douyin_authorized_accounts",
                "ai_agents",
            ]:
                await conn.execute(
                    f'DELETE FROM "{table}" '
                    "WHERE (id BETWEEN $1 AND $2) OR merchant_id = $3",
                    SYNTHETIC_ID_MIN,
                    SYNTHETIC_ID_MAX,
                    SYNTHETIC_MERCHANT_ID,
                )
    finally:
        await conn.close()


def create_fixture_sqlite(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
            CREATE TABLE ai_agents (
                id INTEGER PRIMARY KEY,
                agent_id TEXT,
                merchant_id TEXT,
                name TEXT,
                avatar_seed TEXT,
                avatar_url TEXT,
                prompt TEXT,
                knowledge_base_text TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE douyin_authorized_accounts (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                tenant_id TEXT,
                main_account_id INTEGER,
                open_id TEXT,
                user_id TEXT,
                union_id TEXT,
                account_name TEXT,
                avatar_url TEXT,
                bind_status INTEGER,
                account_type INTEGER,
                bind_time TEXT,
                unbind_time TEXT,
                source_created_at TEXT,
                last_synced_at TEXT,
                raw_body_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE douyin_account_agent_bindings (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                tenant_id TEXT,
                account_open_id TEXT,
                douyin_authorized_account_id INTEGER,
                agent_id TEXT,
                is_default INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                unbound_at TEXT,
                deleted_at TEXT,
                created_by TEXT,
                updated_by TEXT,
                invalid_reason TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE agent_knowledge_categories (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                tenant_id TEXT,
                agent_id TEXT,
                category_key TEXT,
                scope_type TEXT,
                is_base INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                deleted_at TEXT,
                created_by TEXT,
                updated_by TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO ai_agents (
                    id, agent_id, merchant_id, name, avatar_seed, avatar_url, prompt,
                    knowledge_base_text, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9101001,
                        "p3e2-agent-a",
                        SYNTHETIC_MERCHANT_ID,
                        "Synthetic Agent A",
                        "seed-a",
                        None,
                        "prompt a",
                        "kb a",
                        "active",
                        "2026-07-09T10:00:00",
                        "2026-07-09T10:00:00",
                    ),
                    (
                        9101002,
                        "p3e2-agent-b",
                        SYNTHETIC_MERCHANT_ID,
                        "Synthetic Agent B",
                        "seed-b",
                        None,
                        "prompt b",
                        "kb b",
                        "disabled",
                        "2026-07-09T10:00:00",
                        "2026-07-09T10:01:00",
                    ),
                ],
            )
            conn.exec_driver_sql(
                """
                INSERT INTO douyin_authorized_accounts (
                    id, merchant_id, tenant_id, main_account_id, open_id, user_id,
                    union_id, account_name, avatar_url, bind_status, account_type,
                    bind_time, unbind_time, source_created_at, last_synced_at,
                    raw_body_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9102001,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        20001,
                        "p3e2-open-a",
                        "p3e2-user-a",
                        "p3e2-union-a",
                        "Synthetic Account A",
                        None,
                        1,
                        2,
                        "2026-07-09T10:00:00",
                        None,
                        "2026-07-09T09:59:00",
                        "2026-07-09T10:02:00",
                        "{\"source\":\"smoke-a\"}",
                        "2026-07-09T10:00:00",
                        "2026-07-09T10:02:00",
                    ),
                    (
                        9102002,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        20002,
                        "p3e2-open-b",
                        "p3e2-user-b",
                        "p3e2-union-b",
                        "Synthetic Account B",
                        None,
                        1,
                        2,
                        "2026-07-09T10:03:00",
                        None,
                        "2026-07-09T09:59:00",
                        "2026-07-09T10:04:00",
                        "{\"source\":\"smoke-b\"}",
                        "2026-07-09T10:03:00",
                        "2026-07-09T10:04:00",
                    ),
                ],
            )
            conn.exec_driver_sql(
                """
                INSERT INTO douyin_account_agent_bindings (
                    id, merchant_id, tenant_id, account_open_id, douyin_authorized_account_id,
                    agent_id, is_default, status, created_at, updated_at, unbound_at,
                    deleted_at, created_by, updated_by, invalid_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9103001,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        "p3e2-open-a",
                        9102001,
                        "p3e2-agent-a",
                        1,
                        "active",
                        "2026-07-09T10:05:00",
                        "2026-07-09T10:05:00",
                        None,
                        None,
                        "smoke",
                        "smoke",
                        None,
                    ),
                    (
                        9103002,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        "p3e2-open-b",
                        9102002,
                        "p3e2-agent-b",
                        1,
                        "active",
                        "2026-07-09T10:06:00",
                        "2026-07-09T10:06:00",
                        None,
                        None,
                        "smoke",
                        "smoke",
                        None,
                    ),
                ],
            )
            conn.exec_driver_sql(
                """
                INSERT INTO agent_knowledge_categories (
                    id, merchant_id, tenant_id, agent_id, category_key, scope_type,
                    is_base, status, created_at, updated_at, deleted_at, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        9104001,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        "p3e2-agent-a",
                        "smoke-base",
                        "merchant",
                        1,
                        "active",
                        "2026-07-09T10:07:00",
                        "2026-07-09T10:07:00",
                        None,
                        "smoke",
                        "smoke",
                    ),
                    (
                        9104002,
                        SYNTHETIC_MERCHANT_ID,
                        "tenant-smoke",
                        "p3e2-agent-b",
                        "smoke-sales",
                        "merchant",
                        0,
                        "active",
                        "2026-07-09T10:08:00",
                        "2026-07-09T10:08:00",
                        None,
                        "smoke",
                        "smoke",
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
                    f'SELECT count(*) FROM "{table}" WHERE merchant_id = $1',
                    SYNTHETIC_MERCHANT_ID,
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
        with tempfile.TemporaryDirectory(prefix="p3_e2_agents_accounts_") as tmpdir:
            sqlite_path = Path(tmpdir) / "fixture.db"
            create_fixture_sqlite(sqlite_path)
            tables = migration.DEFAULT_TABLES
            source_rows = migration.read_sqlite_tables(str(sqlite_path), tables)
            snapshot = asyncio.run(migration.read_postgres_snapshot(database_url, tables))
            first_plan = migration.build_migration_plan(source_rows, snapshot, tables)
            migration.print_dry_run_plan(first_plan, migration.mask_database_url(database_url))
            if first_plan.total_insert < 8 or first_plan.total_errors:
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
    print("SMOKE_PASS: agents/accounts core data migration dev apply ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
