"""knowledge_categories SQLite -> PostgreSQL 迁移脚本。

默认 dry-run。P3-C5 只开放受控 dev apply，用 synthetic / 本地测试数据验证闭环。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


EXPECTED_REVISION = "0002_create_knowledge_categories"
TARGET_TABLE = "knowledge_categories"
ALLOWED_POSTGRES_SCHEMES = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
ALLOWED_APPLY_HOSTS = {"localhost", "127.0.0.1", "postgres"}
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
    """迁移脚本运行参数缺失或越过 P3-C5 安全边界。"""


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


@dataclass(frozen=True)
class ApplyResult:
    planned_insert_count: int
    planned_update_count: int
    planned_skip_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    error_count: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="dry-run 检查 knowledge_categories 从 SQLite 迁移到 PostgreSQL 的计划。"
    )
    parser.add_argument("--sqlite-db-path", help="SQLite 源库路径；必须显式传入，不猜测宝塔路径。")
    parser.add_argument("--postgres-url", help="PostgreSQL 目标 URL；未传时读取 SMOKE_DATABASE_URL 或 DATABASE_URL。")
    parser.add_argument("--merchant-id", help="可选，仅 dry-run 指定 merchant_id 的源行。")
    parser.add_argument("--limit", type=int, help="可选，仅 dry-run 前 N 行。")
    parser.add_argument("--dry-run", action="store_true", default=True, help="默认启用；不传 --apply 不会写 PostgreSQL。")
    parser.add_argument("--apply", action="store_true", help="受控 dev apply；必须同时传 --yes。")
    parser.add_argument("--yes", action="store_true", help="确认执行受控 dev apply；必须和 --apply 一起使用。")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> None:
    if not (args.sqlite_db_path or "").strip():
        raise MigrationConfigurationError("缺少 --sqlite-db-path；脚本不猜测宝塔或生产 SQLite 路径")
    if args.limit is not None and args.limit < 1:
        raise MigrationConfigurationError("--limit 必须是正整数")
    if args.apply and not args.yes:
        raise MigrationConfigurationError("--apply 必须同时传入 --yes")
    if args.yes and not args.apply:
        raise MigrationConfigurationError("--yes 只能和 --apply 一起使用")

    postgres_url, source = resolve_postgres_url_with_source(args, env)
    if args.apply:
        validate_apply_target(postgres_url, source)


def resolve_postgres_url(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> str:
    return resolve_postgres_url_with_source(args, env)[0]


def resolve_postgres_url_with_source(
    args: argparse.Namespace, env: Mapping[str, str] | None = None
) -> tuple[str, str]:
    values = env if env is not None else os.environ
    if args.postgres_url:
        url = args.postgres_url.strip()
        source = "--postgres-url"
    elif values.get("SMOKE_DATABASE_URL"):
        url = values["SMOKE_DATABASE_URL"].strip()
        source = "SMOKE_DATABASE_URL"
    elif values.get("DATABASE_URL"):
        url = values["DATABASE_URL"].strip()
        source = "DATABASE_URL"
    else:
        url = ""
        source = ""
    if not url:
        raise MigrationConfigurationError("缺少 --postgres-url、SMOKE_DATABASE_URL 或 DATABASE_URL")

    parsed = parse_database_url(url)
    if parsed.backend != "postgresql":
        raise MigrationConfigurationError("PostgreSQL 目标 URL 只允许 postgresql / postgresql+asyncpg / postgresql+psycopg")

    scheme = url.split("://", 1)[0]
    if scheme not in ALLOWED_POSTGRES_SCHEMES:
        raise MigrationConfigurationError(f"不支持的 PostgreSQL URL scheme: {scheme}")
    return url, source


def validate_apply_target(database_url: str, source: str) -> None:
    if source == "DATABASE_URL":
        raise MigrationConfigurationError("apply 不允许使用 DATABASE_URL 隐式来源；请使用 --postgres-url 或 SMOKE_DATABASE_URL")
    parsed = urlparse(database_url)
    if (parsed.hostname or "").lower() not in ALLOWED_APPLY_HOSTS:
        raise MigrationConfigurationError("apply 只允许 dev host: localhost / 127.0.0.1 / postgres")
    if (parsed.path or "").lstrip("/") != "auto_wechat":
        raise MigrationConfigurationError("目标 database 必须是 auto_wechat")


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


def build_apply_plan(
    source_rows: Sequence[Mapping[str, object]],
    target_snapshot: TargetSnapshot,
    *,
    merchant_id: str | None = None,
    limit: int | None = None,
) -> DryRunPlan:
    plan = build_dry_run_plan(source_rows, target_snapshot, merchant_id=merchant_id, limit=limit)
    return DryRunPlan(
        source_count=plan.source_count,
        filtered_count=plan.filtered_count,
        insert_count=plan.insert_count,
        update_count=plan.update_count,
        skip_count=plan.skip_count,
        anomaly_count=plan.anomaly_count,
        target_table_exists=plan.target_table_exists,
        alembic_revision=plan.alembic_revision,
        alembic_revision_ok=plan.alembic_revision_ok,
        field_mapping_preview=plan.field_mapping_preview,
        anomalies=plan.anomalies,
        will_write_postgres=True,
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


def build_synthetic_source_rows(*, merchant_id: str = "p3_c5_smoke_merchant") -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "tenant_id": "p3_c5_smoke_tenant",
            "merchant_id": merchant_id,
            "category_key": "active_smoke",
            "name": "P3-C5 active smoke",
            "description": "synthetic active row",
            "scope_type": "merchant",
            "is_base": 0,
            "status": "active",
            "sort_order": 10,
            "created_at": "2026-07-08 10:00:00+00",
            "updated_at": "2026-07-08 10:00:00+00",
            "deleted_at": None,
            "created_by": "p3_c5_smoke",
            "updated_by": "p3_c5_smoke",
        },
        {
            "id": 2,
            "tenant_id": "p3_c5_smoke_tenant",
            "merchant_id": merchant_id,
            "category_key": "disabled_smoke",
            "name": "P3-C5 disabled smoke",
            "description": "synthetic disabled row",
            "scope_type": "merchant",
            "is_base": 0,
            "status": "disabled",
            "sort_order": 20,
            "created_at": "2026-07-08 10:01:00+00",
            "updated_at": "2026-07-08 10:01:00+00",
            "deleted_at": None,
            "created_by": "p3_c5_smoke",
            "updated_by": "p3_c5_smoke",
        },
        {
            "id": 3,
            "tenant_id": "p3_c5_smoke_tenant",
            "merchant_id": merchant_id,
            "category_key": "deleted_smoke",
            "name": "P3-C5 deleted smoke",
            "description": "synthetic deleted row",
            "scope_type": "merchant",
            "is_base": 0,
            "status": "deleted",
            "sort_order": 30,
            "created_at": "2026-07-08 10:02:00+00",
            "updated_at": "2026-07-08 10:02:00+00",
            "deleted_at": "2026-07-08 10:03:00+00",
            "created_by": "p3_c5_smoke",
            "updated_by": "p3_c5_smoke",
        },
        {
            "id": 4,
            "tenant_id": "p3_c5_smoke_tenant",
            "merchant_id": merchant_id,
            "category_key": "base",
            "name": "P3-C5 real base smoke",
            "description": "synthetic real base row",
            "scope_type": "system",
            "is_base": 1,
            "status": "active",
            "sort_order": 0,
            "created_at": "2026-07-08 10:04:00+00",
            "updated_at": "2026-07-08 10:04:00+00",
            "deleted_at": None,
            "created_by": "p3_c5_smoke",
            "updated_by": "p3_c5_smoke",
        },
    ]


def write_synthetic_sqlite_database(sqlite_db_path: str, *, merchant_id: str = "p3_c5_smoke_merchant") -> Path:
    path = Path(sqlite_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_synthetic_source_rows(merchant_id=merchant_id)
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS knowledge_categories"))
            conn.execute(
                text(
                    """
                    CREATE TABLE knowledge_categories (
                        id INTEGER PRIMARY KEY,
                        tenant_id VARCHAR(128),
                        merchant_id VARCHAR(128),
                        category_key VARCHAR(128) NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        description TEXT,
                        scope_type VARCHAR(20) NOT NULL DEFAULT 'merchant',
                        is_base INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME,
                        updated_at DATETIME,
                        deleted_at DATETIME,
                        created_by VARCHAR(128),
                        updated_by VARCHAR(128)
                    )
                    """
                )
            )
            for row in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO knowledge_categories (
                            id, tenant_id, merchant_id, category_key, name, description, scope_type,
                            is_base, status, sort_order, created_at, updated_at, deleted_at,
                            created_by, updated_by
                        )
                        VALUES (
                            :id, :tenant_id, :merchant_id, :category_key, :name, :description, :scope_type,
                            :is_base, :status, :sort_order, :created_at, :updated_at, :deleted_at,
                            :created_by, :updated_by
                        )
                        """
                    ),
                    row,
                )
    finally:
        engine.dispose()
    return path


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


def build_upsert_sql() -> str:
    return """
    INSERT INTO knowledge_categories (
        tenant_id,
        merchant_id,
        "key",
        category_key,
        name,
        description,
        scope_type,
        is_base,
        status,
        sort_order,
        created_at,
        updated_at,
        deleted_at,
        created_by,
        updated_by
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
        COALESCE($11::timestamptz, now()),
        COALESCE($12::timestamptz, now()),
        $13::timestamptz,
        $14, $15
    )
    ON CONFLICT (scope_type, merchant_id, "key") DO UPDATE
    SET
        category_key = excluded.category_key,
        name = excluded.name,
        description = excluded.description,
        is_base = excluded.is_base,
        status = excluded.status,
        sort_order = excluded.sort_order,
        updated_at = excluded.updated_at,
        deleted_at = excluded.deleted_at,
        updated_by = excluded.updated_by
    RETURNING (xmax = 0) AS inserted
    """


def row_to_upsert_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("tenant_id"),
        row.get("merchant_id"),
        row["key"],
        row["category_key"],
        row["name"],
        row.get("description"),
        row["scope_type"],
        row["is_base"],
        row["status"],
        row["sort_order"],
        _pg_timestamp(row.get("created_at")),
        _pg_timestamp(row.get("updated_at")),
        _pg_timestamp(row.get("deleted_at")),
        row.get("created_by"),
        row.get("updated_by"),
    )


async def apply_postgres_rows(database_url: str, rows: Sequence[Mapping[str, object]], plan: DryRunPlan) -> ApplyResult:
    if not plan.target_table_exists or not plan.alembic_revision_ok:
        raise MigrationConfigurationError(f"schema 检查未通过，alembic revision 必须至少为 {EXPECTED_REVISION}")
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - 由运行环境依赖决定
        raise MigrationConfigurationError("缺少 asyncpg，无法执行 PostgreSQL apply") from exc

    upsert_sql = build_upsert_sql()
    dsn = to_asyncpg_dsn(database_url)
    prepared = prepare_source_rows(rows)
    seen_keys: set[tuple[str, str | None, str]] = set()
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = len(prepared.anomalies)
    if error_count:
        return ApplyResult(
            planned_insert_count=plan.insert_count,
            planned_update_count=plan.update_count,
            planned_skip_count=plan.skip_count,
            inserted_count=0,
            updated_count=0,
            skipped_count=0,
            error_count=error_count,
        )

    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for row in prepared.valid_rows:
                key = unique_key(row)
                if key in seen_keys:
                    skipped_count += 1
                    continue
                seen_keys.add(key)
                inserted = await conn.fetchval(upsert_sql, *row_to_upsert_params(row))
                if inserted:
                    inserted_count += 1
                else:
                    updated_count += 1
        return ApplyResult(
            planned_insert_count=plan.insert_count,
            planned_update_count=plan.update_count,
            planned_skip_count=plan.skip_count,
            inserted_count=inserted_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            error_count=error_count,
        )
    finally:
        await conn.close()


def assert_readonly_sql(query: str) -> None:
    normalized = re.sub(r"\s+", " ", query).strip().lower()
    forbidden = r"\b(insert|update|delete|create|drop|alter|truncate|grant|revoke)\b"
    if not normalized.startswith("select ") or re.search(forbidden, normalized):
        raise ValueError("PostgreSQL 快照检查只允许执行只读 SELECT")


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


def _pg_timestamp(value: object) -> datetime | date | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    normalized = text_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.fromisoformat(normalized.replace(" ", "T", 1))


def print_dry_run_plan(plan: DryRunPlan, *, safe_postgres_url: str) -> None:
    print("dry-run：不会写 PostgreSQL，不会修改 SQLite，不会修改 .env。")
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
    print("PostgreSQL 写入: disabled")


def print_apply_plan(plan: DryRunPlan, *, safe_postgres_url: str) -> None:
    print("P3-C5 dev apply：只允许写 PostgreSQL knowledge_categories，不修改 SQLite，不修改 .env。")
    print(f"PostgreSQL URL: {safe_postgres_url}")
    print(f"SQLite 源行数: {plan.source_count}")
    print(f"过滤后待处理行数: {plan.filtered_count}")
    print(f"Alembic revision: {plan.alembic_revision or '<missing>'}")
    print(f"计划 insert: {plan.insert_count}")
    print(f"计划 update: {plan.update_count}")
    print(f"计划 skip: {plan.skip_count}")
    print(f"异常行数量: {plan.anomaly_count}")
    print(f"字段映射预览: {plan.field_mapping_preview}")


def print_apply_result(result: ApplyResult) -> None:
    print(f"实际 insert: {result.inserted_count}")
    print(f"实际 update: {result.updated_count}")
    print(f"实际 skip: {result.skipped_count}")
    print(f"实际 error: {result.error_count}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        postgres_url = resolve_postgres_url(args)
        sqlite_rows = read_sqlite_rows(args.sqlite_db_path)
        target_snapshot = asyncio.run(read_postgres_snapshot(postgres_url))
        if args.apply:
            plan = build_apply_plan(sqlite_rows, target_snapshot, merchant_id=args.merchant_id, limit=args.limit)
            filtered_rows = filter_source_rows(sqlite_rows, merchant_id=args.merchant_id, limit=args.limit)
            print_apply_plan(plan, safe_postgres_url=mask_database_url(postgres_url))
            result = asyncio.run(apply_postgres_rows(postgres_url, filtered_rows, plan))
            print_apply_result(result)
            if result.error_count:
                print("APPLY_FAIL: knowledge_categories dev apply 存在错误行")
                return 3
            print("APPLY_PASS: knowledge_categories dev apply 已完成")
            return 0

        plan = build_dry_run_plan(sqlite_rows, target_snapshot, merchant_id=args.merchant_id, limit=args.limit)
        print_dry_run_plan(plan, safe_postgres_url=mask_database_url(postgres_url))
    except (MigrationConfigurationError, MigrationReadError, ValueError) as exc:
        print(f"MIGRATION_FAIL: {exc}")
        return 2

    print("DRY_RUN_PASS: knowledge_categories 迁移计划已生成；未写 PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
