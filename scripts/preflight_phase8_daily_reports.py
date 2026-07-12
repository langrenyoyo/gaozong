#!/usr/bin/env python3
"""Phase 8 日报迁移前只读 preflight。

检查 sales_daily_summaries.summary_date 和 daily_report_jobs 的迁移前提条件，
任一阻断计数非 0 时以退出码 1 阻断迁移，不自动删/合并/回填。

用法：
    python scripts/preflight_phase8_daily_reports.py --sqlite-db-path <path>
    python scripts/preflight_phase8_daily_reports.py --postgres-url <url>

输出固定计数（脱敏，不输出销售名/联系方式/原始反馈）：
    summary_non_midnight_count
    summary_date_fold_duplicate_group_count
    daily_report_candidate_duplicate_group_count
    daily_report_existing_non_null_key_duplicate_group_count

退出码：
    0 — 全部计数为 0，可以继续迁移
    1 — 存在阻断计数
    2 — 参数或 URL 不安全
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from migrations import migrate_sqlite  # noqa: E402  自包含，不 import app


_PG_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
_PG_REQUIRED_SCHEME = "postgresql+psycopg"


def _validate_pg_url(url: str) -> dict:
    """复用 Phase 7-FIX2 已验证的 SMOKE_DATABASE_URL 安全规则。"""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or ""
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/")
    if scheme != _PG_REQUIRED_SCHEME:
        return {"valid": False, "reason": f"scheme must be {_PG_REQUIRED_SCHEME}, got {scheme}"}
    if host not in _PG_ALLOWED_HOSTS:
        return {"valid": False, "reason": f"host not allowed: {host}"}
    if not (database.endswith("_test") or database.endswith("_staging")):
        return {"valid": False, "reason": f"database must end with _test/_staging: {database}"}
    if parsed.query or parsed.fragment:
        return {"valid": False, "reason": "query/fragment not allowed (can override host/database)"}
    return {"valid": True, "reason": "ok"}


def _pg_table_exists(conn, table: str) -> bool:
    from sqlalchemy import text
    return bool(conn.execute(
        text("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table},
    ).scalar())


def _pg_column_exists(conn, table: str, column: str) -> bool:
    from sqlalchemy import text
    return bool(conn.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table, "c": column},
    ).scalar())


def preflight_postgres(url: str) -> dict:
    """PG 只读 preflight，返回与 SQLite 等价的 4 个阻断计数。

    summary_date 在 PG 是 TIMESTAMPTZ，按 Asia/Shanghai 转本地后判断零点；
    PG downgrade 后 summary_date 恢复为带时区 DateTime（业务日 00:00:00 Asia/Shanghai 对应瞬间）。
    """
    from sqlalchemy import create_engine, text

    validation = _validate_pg_url(url)
    if not validation["valid"]:
        raise SystemExit(f"PG URL 不安全: {validation['reason']}")

    counts = {
        "summary_non_midnight_count": 0,
        "summary_date_fold_duplicate_group_count": 0,
        "daily_report_candidate_duplicate_group_count": 0,
        "daily_report_existing_non_null_key_duplicate_group_count": 0,
    }
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if _pg_table_exists(conn, "sales_daily_summaries"):
                local_expr = "(summary_date AT TIME ZONE 'Asia/Shanghai')"
                counts["summary_non_midnight_count"] = conn.execute(text(
                    f"SELECT count(*) FROM sales_daily_summaries "
                    f"WHERE EXTRACT(HOUR FROM {local_expr}) <> 0 "
                    f"OR EXTRACT(MINUTE FROM {local_expr}) <> 0 "
                    f"OR EXTRACT(SECOND FROM {local_expr}) <> 0"
                )).scalar() or 0
                counts["summary_date_fold_duplicate_group_count"] = conn.execute(text(
                    f"SELECT count(*) FROM ("
                    f" SELECT merchant_id, staff_id, ({local_expr})::date AS d"
                    f" FROM sales_daily_summaries"
                    f" GROUP BY merchant_id, staff_id, ({local_expr})::date"
                    f" HAVING count(*) > 1) sub"
                )).scalar() or 0
            if _pg_table_exists(conn, "daily_report_jobs"):
                counts["daily_report_candidate_duplicate_group_count"] = conn.execute(text(
                    "SELECT count(*) FROM ("
                    " SELECT merchant_id, (report_date AT TIME ZONE 'Asia/Shanghai')::date AS d, COALESCE(report_type, '')"
                    " FROM daily_report_jobs WHERE report_date IS NOT NULL"
                    " GROUP BY merchant_id, (report_date AT TIME ZONE 'Asia/Shanghai')::date, COALESCE(report_type, '')"
                    " HAVING count(*) > 1) sub"
                )).scalar() or 0
                if _pg_column_exists(conn, "daily_report_jobs", "report_day"):
                    counts["daily_report_existing_non_null_key_duplicate_group_count"] = conn.execute(text(
                        "SELECT count(*) FROM ("
                        " SELECT merchant_id, report_day, COALESCE(report_type, ''), COALESCE(report_variant, 'default')"
                        " FROM daily_report_jobs WHERE report_day IS NOT NULL"
                        " GROUP BY merchant_id, report_day, COALESCE(report_type, ''), COALESCE(report_variant, 'default')"
                        " HAVING count(*) > 1) sub"
                    )).scalar() or 0
    finally:
        engine.dispose()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 8 日报迁移前只读 preflight")
    parser.add_argument("--sqlite-db-path", help="只读 SQLite 数据库路径")
    parser.add_argument("--postgres-url", help="只读 PG 安全非生产 URL（禁止 query/fragment）")
    args = parser.parse_args(argv)

    if not args.sqlite_db_path and not args.postgres_url:
        print("必须提供 --sqlite-db-path 或 --postgres-url", file=sys.stderr)
        return 2
    if args.sqlite_db_path and args.postgres_url:
        print("只能提供其中之一，不要同时提供", file=sys.stderr)
        return 2

    if args.sqlite_db_path:
        conn = migrate_sqlite.connect_readonly(args.sqlite_db_path)
        try:
            counts = migrate_sqlite.phase8_preflight_sqlite(conn)
        finally:
            conn.close()
    else:
        counts = preflight_postgres(args.postgres_url)

    print("Phase 8 preflight 结果：")
    bad = False
    for key in sorted(counts):
        value = counts[key]
        marker = "[FAIL]" if value > 0 else "[OK]"
        print(f"  {marker} {key}: {value}")
        if value > 0:
            bad = True

    if bad:
        print("\npreflight 失败：存在阻断计数，迁移不应继续；请由审批窗口决定数据修复",
              file=sys.stderr)
        return 1
    print("\npreflight 通过：可以继续迁移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
