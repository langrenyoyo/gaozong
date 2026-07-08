"""knowledge_categories SQLite -> PostgreSQL dry-run-only 迁移脚本骨架。

P3-C4 只允许读取 SQLite 和只读检查 PostgreSQL，不实现 apply，不写目标库。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


EXPECTED_REVISION = "0002_create_knowledge_categories"
TARGET_TABLE = "knowledge_categories"
ALLOWED_POSTGRES_SCHEMES = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
POSTGRES_READONLY_QUERIES = (
    "SELECT version_num FROM alembic_version",
    """
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = $1
    )
    """,
    'SELECT scope_type, merchant_id, "key" FROM knowledge_categories',
)
SQLITE_SOURCE_QUERY = "SELECT * FROM knowledge_categories"


class MigrationConfigurationError(RuntimeError):
    """迁移脚本运行参数缺失或越过 P3-C4 边界。"""


class MigrationReadError(RuntimeError):
    """只读读取源库或目标库失败。"""


@dataclass(frozen=True)
class TargetSnapshot:
    alembic_revision: str
    table_exists: bool
    existing_keys: set[tuple[str, str | None, str]]


@dataclass(frozen=True)
class RowAnomaly:
    source_id: object
    category_key: object
    reason: str


@dataclass(frozen=True)
class PreparedRows:
    valid_rows: list[dict[str, object]]
    anomalies: list[RowAnomaly]


@dataclass(frozen=True)
class DryRunPlan:
    source_count: int
    filtered_count: int
    insert_count: int
    update_count: int
    skip_count: int
    anomaly_count: int
    target_table_exists: bool
    alembic_revision: str
    alembic_revision_ok: bool
    field_mapping_preview: list[dict[str, object]]
    anomalies: list[RowAnomaly]
    will_write_postgres: bool = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="dry-run 检查 knowledge_categories 从 SQLite 迁移到 PostgreSQL 的计划。"
    )
    parser.add_argument("--sqlite-db-path", help="SQLite 源库路径；必须显式传入，不猜测宝塔路径。")
    parser.add_argument("--postgres-url", help="PostgreSQL 目标 URL；未传时读取 SMOKE_DATABASE_URL 或 DATABASE_URL。")
    parser.add_argument("--merchant-id", help="可选，仅 dry-run 指定 merchant_id 的源行。")
    parser.add_argument("--limit", type=int, help="可选，仅 dry-run 前 N 行。")
    parser.add_argument("--dry-run", action="store_true", default=True, help="默认启用；P3-C4 只支持 dry-run。")
    parser.add_argument("--apply", action="store_true", help="P3-C4 明确拒绝。")
    parser.add_argument("--yes", action="store_true", help="P3-C4 明确拒绝。")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> None:
    if args.apply or args.yes:
        raise MigrationConfigurationError("apply mode is not implemented in P3-C4")
    if not (args.sqlite_db_path or "").strip():
        raise MigrationConfigurationError("缺少 --sqlite-db-path；P3-C4 不猜测宝塔或生产 SQLite 路径")
    if args.limit is not None and args.limit < 1:
        raise MigrationConfigurationError("--limit 必须是正整数")
    resolve_postgres_url(args, env)


def resolve_postgres_url(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    url = (args.postgres_url or values.get("SMOKE_DATABASE_URL") or values.get("DATABASE_URL") or "").strip()
    if not url:
        raise MigrationConfigurationError("缺少 --postgres-url、SMOKE_DATABASE_URL 或 DATABASE_URL")

    parsed = parse_database_url(url)
    if parsed.backend != "postgresql":
        raise MigrationConfigurationError("PostgreSQL 目标 URL 只允许 postgresql / postgresql+asyncpg / postgresql+psycopg")

    scheme = url.split("://", 1)[0]
    if scheme not in ALLOWED_POSTGRES_SCHEMES:
        raise MigrationConfigurationError(f"不支持的 PostgreSQL URL scheme: {scheme}")
    return url


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def map_sqlite_row_to_postgres(row: Mapping[str, object]) -> dict[str, object]:
    category_key = _required_str(row.get("category_key"), "CATEGORY_KEY_REQUIRED")
    name = _required_str(row.get("name"), "CATEGORY_NAME_REQUIRED")
    mapped = {
        "id": row.get("id"),
        "tenant_id": _optional_str(row.get("tenant_id")),
        "merchant_id": _optional_str(row.get("merchant_id")),
        "category_key": category_key,
        "key": category_key,
        "name": name,
        "description": _optional_str(row.get("description")),
        "scope_type": _optional_str(row.get("scope_type")) or "merchant",
        "is_base": _sqlite_bool(row.get("is_base")),
        "status": _optional_str(row.get("status")) or "active",
        "sort_order": _int_or_default(row.get("sort_order"), 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "deleted_at": row.get("deleted_at"),
        "created_by": _optional_str(row.get("created_by")),
        "updated_by": _optional_str(row.get("updated_by")),
    }
    if mapped["key"] != mapped["category_key"]:
        raise ValueError("KEY_CATEGORY_KEY_MISMATCH")
    return mapped


def filter_source_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    merchant_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        if merchant_id is not None and item.get("merchant_id") != merchant_id:
            continue
        filtered.append(item)
        if limit is not None and len(filtered) >= limit:
            break
    return filtered


def prepare_source_rows(rows: Sequence[Mapping[str, object]]) -> PreparedRows:
    valid_rows: list[dict[str, object]] = []
    anomalies: list[RowAnomaly] = []
    for row in rows:
        try:
            valid_rows.append(map_sqlite_row_to_postgres(row))
        except ValueError as exc:
            anomalies.append(RowAnomaly(source_id=row.get("id"), category_key=row.get("category_key"), reason=str(exc)))
    return PreparedRows(valid_rows=valid_rows, anomalies=anomalies)


def build_dry_run_plan(
    source_rows: Sequence[Mapping[str, object]],
    target_snapshot: TargetSnapshot,
    *,
    merchant_id: str | None = None,
    limit: int | None = None,
) -> DryRunPlan:
    filtered_rows = filter_source_rows(source_rows, merchant_id=merchant_id, limit=limit)
    prepared = prepare_source_rows(filtered_rows)
    seen_keys: set[tuple[str, str | None, str]] = set()
    insert_count = 0
    update_count = 0
    skip_count = 0

    for row in prepared.valid_rows:
        key = unique_key(row)
        if key in seen_keys:
            skip_count += 1
            continue
        seen_keys.add(key)
        if key in target_snapshot.existing_keys:
            update_count += 1
        else:
            insert_count += 1

    return DryRunPlan(
        source_count=len(source_rows),
        filtered_count=len(filtered_rows),
        insert_count=insert_count,
        update_count=update_count,
        skip_count=skip_count,
        anomaly_count=len(prepared.anomalies),
        target_table_exists=target_snapshot.table_exists,
        alembic_revision=target_snapshot.alembic_revision,
        alembic_revision_ok=is_revision_at_least(target_snapshot.alembic_revision, EXPECTED_REVISION),
        field_mapping_preview=prepared.valid_rows[:3],
        anomalies=prepared.anomalies,
    )


def unique_key(row: Mapping[str, object]) -> tuple[str, str | None, str]:
    return (str(row["scope_type"]), _optional_str(row.get("merchant_id")), str(row["key"]))


def read_sqlite_rows(sqlite_db_path: str, *, merchant_id: str | None = None, limit: int | None = None) -> list[dict[str, object]]:
    path = Path(sqlite_db_path)
    if not path.is_file():
        raise MigrationConfigurationError(f"SQLite 源库不存在: {sqlite_db_path}")

    engine = create_engine(f"sqlite:///{path}")
    try:
        query = SQLITE_SOURCE_QUERY
        params: dict[str, object] = {}
        if merchant_id is not None:
            query += " WHERE merchant_id = :merchant_id"
            params["merchant_id"] = merchant_id
        query += " ORDER BY id ASC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            return [dict(row._mapping) for row in result]
    except Exception as exc:
        raise MigrationReadError(f"读取 SQLite knowledge_categories 失败: {exc}") from exc
    finally:
        engine.dispose()


async def read_postgres_snapshot(database_url: str) -> TargetSnapshot:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - 由运行环境依赖决定
        raise MigrationConfigurationError("缺少 asyncpg，无法执行 PostgreSQL 只读 dry-run 检查") from exc

    dsn = to_asyncpg_dsn(database_url)
    for query in POSTGRES_READONLY_QUERIES:
        assert_readonly_sql(query)

    conn = await asyncpg.connect(dsn)
    try:
        revision = await conn.fetchval(POSTGRES_READONLY_QUERIES[0])
        table_exists = await conn.fetchval(POSTGRES_READONLY_QUERIES[1], TARGET_TABLE)
        existing_keys: set[tuple[str, str | None, str]] = set()
        if table_exists:
            rows = await conn.fetch(POSTGRES_READONLY_QUERIES[2])
            existing_keys = {(str(row["scope_type"]), row["merchant_id"], str(row["key"])) for row in rows}
        return TargetSnapshot(
            alembic_revision=str(revision or ""),
            table_exists=bool(table_exists),
            existing_keys=existing_keys,
        )
    except Exception as exc:
        raise MigrationReadError(f"PostgreSQL 只读检查失败: {exc}") from exc
    finally:
        await conn.close()


def assert_readonly_sql(query: str) -> None:
    normalized = re.sub(r"\s+", " ", query).strip().lower()
    forbidden = r"\b(insert|update|delete|create|drop|alter|truncate|grant|revoke)\b"
    if not normalized.startswith("select ") or re.search(forbidden, normalized):
        raise ValueError("P3-C4 只允许执行只读 SELECT，不允许写 PostgreSQL")


def to_asyncpg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def is_revision_at_least(actual: str, expected: str) -> bool:
    actual_num = _leading_revision_number(actual)
    expected_num = _leading_revision_number(expected)
    if actual_num is not None and expected_num is not None:
        return actual_num >= expected_num
    return actual == expected


def _leading_revision_number(value: str) -> int | None:
    match = re.match(r"^0*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _required_str(value: object, error_code: str) -> str:
    text_value = _optional_str(value)
    if not text_value:
        raise ValueError(error_code)
    return text_value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _sqlite_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or_default(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def print_dry_run_plan(plan: DryRunPlan, *, safe_postgres_url: str) -> None:
    print("P3-C4 dry-run-only：不会写 PostgreSQL，不会修改 SQLite，不会修改 .env。")
    print(f"PostgreSQL URL: {safe_postgres_url}")
    print(f"SQLite 源行数: {plan.source_count}")
    print(f"过滤后待处理行数: {plan.filtered_count}")
    print(f"PostgreSQL 目标表存在: {plan.target_table_exists}")
    print(f"Alembic revision: {plan.alembic_revision or '<missing>'}")
    print(f"Alembic revision 至少为 {EXPECTED_REVISION}: {plan.alembic_revision_ok}")
    print(f"预计 insert: {plan.insert_count}")
    print(f"预计 update: {plan.update_count}")
    print(f"预计 skip: {plan.skip_count}")
    print(f"异常行数量: {plan.anomaly_count}")
    print(f"字段映射预览: {plan.field_mapping_preview}")
    if plan.anomalies:
        print(f"异常行预览: {plan.anomalies[:5]}")
    print("PostgreSQL 写入: disabled in P3-C4")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        postgres_url = resolve_postgres_url(args)
        sqlite_rows = read_sqlite_rows(args.sqlite_db_path)
        target_snapshot = asyncio.run(read_postgres_snapshot(postgres_url))
        plan = build_dry_run_plan(sqlite_rows, target_snapshot, merchant_id=args.merchant_id, limit=args.limit)
        print_dry_run_plan(plan, safe_postgres_url=mask_database_url(postgres_url))
    except (MigrationConfigurationError, MigrationReadError, ValueError) as exc:
        print(f"DRY_RUN_FAIL: {exc}")
        return 2

    print("DRY_RUN_PASS: knowledge_categories 迁移计划已生成；P3-C4 未写 PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
