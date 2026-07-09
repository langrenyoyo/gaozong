"""agents/accounts 四表 dev SQLite / PostgreSQL contrast smoke。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import contrast_agents_accounts_core_sqlite_vs_postgres as contrast
from scripts import migrate_agents_accounts_core_sqlite_to_postgres as migration
from scripts import smoke_migrate_agents_accounts_core_dev_apply as apply_smoke


class SmokeError(RuntimeError):
    """dev contrast smoke 失败。"""


def main() -> int:
    database_url = ""
    try:
        database_url = apply_smoke.require_smoke_url()
        print(f"PostgreSQL URL: {migration.mask_database_url(database_url)}")
        apply_smoke.run_alembic_upgrade(database_url)
        asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))

        with tempfile.TemporaryDirectory(prefix="p3_e3_agents_accounts_contrast_") as tmpdir:
            sqlite_path = Path(tmpdir) / "fixture.db"
            apply_smoke.create_fixture_sqlite(sqlite_path)

            tables = migration.DEFAULT_TABLES
            source_rows = migration.read_sqlite_tables(str(sqlite_path), tables)
            snapshot = asyncio.run(migration.read_postgres_snapshot(database_url, tables))
            plan = migration.build_migration_plan(source_rows, snapshot, tables)
            if plan.total_insert < 8 or plan.total_errors:
                raise SmokeError("synthetic dry-run 计划不符合预期")

            apply_result = asyncio.run(migration.apply_postgres_rows(database_url, source_rows, snapshot, tables))
            if apply_result.errors:
                raise SmokeError("synthetic apply 存在错误")

            sqlite_snapshot = contrast.read_sqlite_snapshot(str(sqlite_path), tables)
            postgres_snapshot = asyncio.run(contrast.read_postgres_snapshot(database_url, tables))
            contrast_result = contrast.build_snapshot_contrast(
                sqlite_snapshot,
                postgres_snapshot,
                tables,
                strict=True,
                safe_postgres_url=migration.mask_database_url(database_url),
            )
            contrast.print_result(contrast_result)
            if contrast_result.status != "CONTRAST_PASS":
                raise SmokeError(f"contrast 未通过: {contrast_result.status}")

            for table, item in contrast_result.tables.items():
                if not item.count_match or not item.sample_key_match or item.mismatch_count != 0:
                    raise SmokeError(f"{table} contrast 结果不符合预期")
    except Exception as exc:
        safe_message = str(exc)
        if database_url:
            safe_message = safe_message.replace(database_url, migration.mask_database_url(database_url))
        print(f"SMOKE_FAIL: {safe_message}")
        return 1
    finally:
        if database_url:
            try:
                asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))
                print("synthetic PG cleanup: done")
            except Exception as cleanup_exc:  # pragma: no cover - 仅用于真实 smoke 收尾诊断
                print(f"synthetic PG cleanup failed: {cleanup_exc}")

    print("SMOKE_PASS: agents/accounts core SQLite vs PostgreSQL contrast ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
