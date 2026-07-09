"""四表 read-only PostgreSQL shadow 的 dev/synthetic smoke。

本脚本只用于本地/dev synthetic 验证：SQLite 仍是响应源，PG 只做 shadow read。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url
from app.services import leads_tasks_pg_shadow as shadow
from app.services.leads_tasks_shadow_observability import (
    get_shadow_metrics_snapshot,
    record_shadow_result,
    reset_shadow_metrics_for_tests,
)
from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration
from scripts import smoke_migrate_leads_tasks_core_dev_apply as apply_smoke


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
SMOKE_TABLES = migration.DEFAULT_TABLES
SMOKE_MERCHANT_ID = "p3_d2_smoke"


class SmokeError(RuntimeError):
    """runtime shadow smoke 失败。"""


def require_smoke_url() -> str:
    database_url = (os.getenv(SMOKE_ENV_NAME) or "").strip()
    if not database_url:
        raise SmokeError("缺少 SMOKE_DATABASE_URL")
    try:
        parsed = parse_database_url(database_url)
    except ValueError as exc:
        raise SmokeError(str(exc)) from exc
    if parsed.backend != "postgresql":
        raise SmokeError("SMOKE_DATABASE_URL 拒绝 SQLite URL")
    if not parsed.raw_url.startswith("postgresql+asyncpg://"):
        raise SmokeError("SMOKE_DATABASE_URL 必须使用 postgresql+asyncpg://")
    return database_url


def build_synthetic_sqlite_rows() -> dict[str, list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory(prefix="p3_d7_shadow_fixture_") as tmpdir:
        sqlite_path = Path(tmpdir) / "fixture.db"
        apply_smoke.create_fixture_sqlite(sqlite_path)
        return migration.read_sqlite_tables(str(sqlite_path), SMOKE_TABLES)


def run_default_off_probe() -> dict[str, Any]:
    reset_shadow_metrics_for_tests()
    rows = build_synthetic_sqlite_rows()
    disabled = shadow.LeadsTasksPgShadowSettings()
    shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=rows["sales_staff"],
        merchant_id=SMOKE_MERCHANT_ID,
        settings=disabled,
    )
    return {
        "responses": _response_summary(rows),
        "metrics": get_shadow_metrics_snapshot(),
        "shadow_engine_initialized": shadow.get_shadow_engine_for_test() is not None,
    }


def run_shadow_probe(database_url: str, *, shadow_timeout_ms: int = 800) -> dict[str, Any]:
    reset_shadow_metrics_for_tests()
    rows = build_synthetic_sqlite_rows()
    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        write_enabled=False,
        strict_contrast=False,
        database_url=database_url,
        shadow_timeout_ms=shadow_timeout_ms,
    )
    operations = [
        shadow.run_sales_staff_list_shadow_read(
            sqlite_rows=rows["sales_staff"],
            merchant_id=SMOKE_MERCHANT_ID,
            settings=settings,
        ),
        shadow.run_wechat_tasks_history_shadow_read(
            sqlite_rows=rows["wechat_tasks"],
            merchant_id=SMOKE_MERCHANT_ID,
            settings=settings,
        ),
        shadow.run_douyin_leads_list_shadow_read(
            sqlite_rows=rows["douyin_leads"],
            merchant_id=SMOKE_MERCHANT_ID,
            settings=settings,
        ),
        shadow.run_douyin_leads_detail_shadow_read(
            sqlite_row=rows["douyin_leads"][0],
            merchant_id=SMOKE_MERCHANT_ID,
            lead_id=int(rows["douyin_leads"][0]["id"]),
            settings=settings,
        ),
        shadow.run_douyin_webhook_events_list_shadow_read(
            sqlite_rows=rows["douyin_webhook_events"],
            merchant_id=SMOKE_MERCHANT_ID,
            settings=settings,
        ),
    ]
    for result in operations:
        record_shadow_result(result)
    return {
        "responses": _response_summary(rows),
        "metrics": get_shadow_metrics_snapshot(),
    }


async def _apply_synthetic_rows(database_url: str, rows: dict[str, list[dict[str, Any]]]) -> None:
    snapshot = await migration.read_postgres_snapshot(database_url, SMOKE_TABLES)
    plan = migration.build_migration_plan(rows, snapshot, SMOKE_TABLES)
    if plan.total_errors:
        raise SmokeError("synthetic migration plan 存在异常行")
    result = await migration.apply_postgres_rows(database_url, rows, snapshot, SMOKE_TABLES)
    if result.errors:
        raise SmokeError("synthetic migration apply 存在异常")


def _response_summary(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "staff_count": len(rows["sales_staff"]),
        "task_count": len(rows["wechat_tasks"]),
        "lead_count": len(rows["douyin_leads"]),
        "lead_detail_id": rows["douyin_leads"][0]["id"],
        "webhook_event_count": len(rows["douyin_webhook_events"]),
    }


def _assert_metrics_ready(metrics: dict[str, Any]) -> None:
    expected = {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
    }
    actual = set(metrics.get("by_operation", {}))
    if metrics.get("total_shadow_reads") != len(expected):
        raise SmokeError(f"shadow reads 数量不符合预期: {metrics.get('total_shadow_reads')}")
    if actual != expected:
        raise SmokeError(f"shadow operation 不符合预期: {sorted(actual)}")
    if metrics.get("total_shadow_pass") != len(expected):
        raise SmokeError(f"shadow operation 未全部通过: {metrics}")
    for key in ("total_shadow_warn", "total_shadow_failed", "total_shadow_timeout", "total_shadow_error"):
        if metrics.get(key):
            raise SmokeError(f"shadow operation 出现非 pass 状态: {metrics}")
    text = str(metrics)
    for forbidden in ("13800138000", "13900139000", "wx_a", "wx_b", "客户A", "客户B"):
        if forbidden in text:
            raise SmokeError("metrics 包含疑似 PII")


def main() -> int:
    database_url = ""
    try:
        database_url = require_smoke_url()
        print(f"PostgreSQL URL: {migration.mask_database_url(database_url)}")
        apply_smoke.run_alembic_upgrade(database_url)
        asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))

        rows = build_synthetic_sqlite_rows()
        asyncio.run(_apply_synthetic_rows(database_url, rows))
        default_off = run_default_off_probe()
        if default_off["metrics"]["total_shadow_reads"] != 0:
            raise SmokeError("默认关闭时 metrics 不应增长")

        shadow_on = run_shadow_probe(database_url)
        _assert_metrics_ready(shadow_on["metrics"])
        print(f"default_off_metrics={default_off['metrics']}")
        print(f"shadow_on_metrics={shadow_on['metrics']}")
        print(f"sqlite_response_summary={shadow_on['responses']}")
    except Exception as exc:
        print(f"SMOKE_FAIL: {exc}")
        return 1
    finally:
        if database_url:
            try:
                asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))
                print("synthetic PG cleanup: done")
            except Exception as cleanup_exc:  # pragma: no cover - 仅用于真实 smoke 收尾诊断
                print(f"synthetic PG cleanup failed: {cleanup_exc}")

    print("SMOKE_PASS: leads/tasks runtime shadow read regression ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
