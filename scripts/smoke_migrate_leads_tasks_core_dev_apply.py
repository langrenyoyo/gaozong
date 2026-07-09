"""四张 leads/tasks core 表数据迁移 dev apply smoke。"""

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

from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"


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
            for table in ["wechat_tasks", "douyin_webhook_events", "douyin_leads", "sales_staff"]:
                await conn.execute(
                    f'DELETE FROM "{table}" WHERE id BETWEEN 9001000 AND 9004999'
                )
    finally:
        await conn.close()


def create_fixture_sqlite(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
            CREATE TABLE sales_staff (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                name TEXT,
                wechat_id TEXT,
                wechat_nickname TEXT,
                phone TEXT,
                status TEXT,
                sort_order INTEGER,
                remark TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE douyin_webhook_events (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                event TEXT,
                from_user_id TEXT,
                to_user_id TEXT,
                conversation_short_id TEXT,
                server_message_id TEXT,
                message_type TEXT,
                message_create_time TEXT,
                parsed_content_json TEXT,
                event_key TEXT,
                is_duplicate INTEGER,
                raw_body TEXT,
                created_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE douyin_leads (
                id INTEGER PRIMARY KEY,
                source TEXT,
                lead_type TEXT,
                customer_name TEXT,
                customer_contact TEXT,
                content TEXT,
                source_id TEXT,
                merchant_id TEXT,
                account_open_id TEXT,
                conversation_short_id TEXT,
                assigned_staff_id INTEGER,
                assigned_at TEXT,
                status TEXT,
                raw_data TEXT,
                raw_message_text TEXT,
                extracted_phone TEXT,
                extracted_wechat TEXT,
                all_extracted_contacts TEXT,
                contact_extract_status TEXT,
                contact_extract_reason TEXT,
                reassign_count INTEGER,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            conn.exec_driver_sql(
                """
            CREATE TABLE wechat_tasks (
                id INTEGER PRIMARY KEY,
                merchant_id TEXT,
                task_type TEXT,
                lead_id INTEGER,
                staff_id INTEGER,
                reply_check_id INTEGER,
                target_nickname TEXT,
                message TEXT,
                mode TEXT,
                status TEXT,
                raw_result TEXT,
                agent_hostname TEXT,
                agent_pid INTEGER,
                pasted_at TEXT,
                sent_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
            )
            rows = [
                ("INSERT INTO sales_staff (id, merchant_id, name, wechat_id, wechat_nickname, phone, status, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [(9001001, "p3_d2_smoke", "销售A", "wx_a", "A", "13800138000", "active", 1, "2026-07-09T10:00:00", "2026-07-09T10:00:00"),
                  (9001002, "p3_d2_smoke", "销售B", "wx_b", "B", "13900139000", "inactive", 2, "2026-07-09T10:00:00", "2026-07-09T10:00:00")]),
                ("INSERT INTO douyin_webhook_events (id, merchant_id, event, from_user_id, to_user_id, conversation_short_id, server_message_id, message_type, message_create_time, parsed_content_json, event_key, is_duplicate, raw_body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [(9002001, "p3_d2_smoke", "im_receive_msg", "open_a", "acct_a", "conv_a", "msg_a", "text", "2026-07-09T10:00:00", "{\"text\":\"a\"}", "p3d2:event:a", 0, "{\"event\":\"a\"}", "2026-07-09T10:00:00"),
                  (9002002, "p3_d2_smoke", "im_receive_msg", "open_b", "acct_b", "conv_b", "msg_b", "text", "2026-07-09T10:00:01", "{\"text\":\"b\"}", "p3d2:event:b", 0, "{\"event\":\"b\"}", "2026-07-09T10:00:01")]),
                ("INSERT INTO douyin_leads (id, source, lead_type, customer_name, customer_contact, content, source_id, merchant_id, account_open_id, conversation_short_id, assigned_staff_id, assigned_at, status, raw_data, raw_message_text, extracted_phone, extracted_wechat, all_extracted_contacts, contact_extract_status, reassign_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [(9003001, "douyin", "chat", "客户A", "13800138000", "想看车", "open_a", "p3_d2_smoke", "acct_a", "conv_a", 9001001, "2026-07-09T10:01:00", "assigned", "{\"x\":1}", "手机13800138000", "13800138000", "wx_a", "[\"13800138000\"]", "matched", 0, "2026-07-09T10:00:00", "2026-07-09T10:01:00"),
                  (9003002, "douyin", "chat", "客户B", "13900139000", "想试驾", "open_b", "p3_d2_smoke", "acct_b", "conv_b", 9001002, "2026-07-09T10:02:00", "pending", "{\"x\":2}", "手机13900139000", "13900139000", "wx_b", "[\"13900139000\"]", "matched", 0, "2026-07-09T10:00:00", "2026-07-09T10:02:00")]),
                ("INSERT INTO wechat_tasks (id, merchant_id, task_type, lead_id, staff_id, target_nickname, message, mode, status, raw_result, agent_hostname, agent_pid, pasted_at, sent_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [(9004001, "p3_d2_smoke", "notify_sales", 9003001, 9001001, "A", "通知A", "paste_only", "pasted", "{\"ok\":true}", "host-a", 1, "2026-07-09T10:03:00", None, "2026-07-09T10:00:00", "2026-07-09T10:03:00"),
                  (9004002, "p3_d2_smoke", "detect_reply", 9003002, 9001002, "B", "检测B", "paste_only", "pending", "{\"ok\":true}", "host-b", 2, None, None, "2026-07-09T10:00:00", "2026-07-09T10:04:00")]),
            ]
            for sql, values in rows:
                conn.exec_driver_sql(sql, values)
    finally:
        engine.dispose()


async def count_rows(database_url: str) -> dict[str, int]:
    import asyncpg

    conn = await asyncpg.connect(migration.to_asyncpg_dsn(database_url))
    try:
        return {
            table: int(await conn.fetchval(f'SELECT count(*) FROM "{table}" WHERE id BETWEEN 9001000 AND 9004999'))
            for table in migration.DEFAULT_TABLES
        }
    finally:
        await conn.close()


def main() -> int:
    try:
        database_url = require_smoke_url()
        print(f"PostgreSQL URL: {migration.mask_database_url(database_url)}")
        run_alembic_upgrade(database_url)
        asyncio.run(cleanup_synthetic_rows(database_url))
        with tempfile.TemporaryDirectory(prefix="p3_d2_leads_tasks_") as tmpdir:
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
        print(f"SMOKE_FAIL: {exc}")
        return 1
    print("SMOKE_PASS: leads/tasks core data migration dev apply ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
