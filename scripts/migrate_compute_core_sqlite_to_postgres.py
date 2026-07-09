"""compute 两表 SQLite -> PostgreSQL 迁移脚本。

默认 dry-run。P3-F2 只允许本地/dev PostgreSQL 受控 apply smoke，不碰宝塔生产。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


EXPECTED_REVISION = "0005_compute_core"
POSTGRES_WRITE_MODE_DISABLED = "disabled"
DEFAULT_TABLES = ["compute_accounts", "compute_transactions"]
ALLOWED_POSTGRES_SCHEMES = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
ALLOWED_APPLY_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}


class MigrationConfigurationError(RuntimeError):
    """迁移配置缺失或越过安全边界。"""


class MigrationReadError(RuntimeError):
    """读取 SQLite 或 PostgreSQL 快照失败。"""


@dataclass(frozen=True)
class TableConfig:
    columns: tuple[str, ...]
    upsert_key: tuple[str, ...]
    datetime_fields: tuple[str, ...] = ()
    int_fields: tuple[str, ...] = ()
    defaults: Mapping[str, object] | None = None
    required_fields: tuple[str, ...] = ()
    update_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetSnapshot:
    alembic_revision: str
    table_exists: dict[str, bool]
    existing_keys: dict[str, set[tuple[object, ...]]]
    existing_counts: dict[str, int]


@dataclass(frozen=True)
class MappedRow:
    row: dict[str, object]
    ignored_fields: list[str]
    defaulted_fields: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class RowError:
    source_id: object
    reason: str


@dataclass(frozen=True)
class TablePlan:
    table: str
    sqlite_source_rows: int
    rows_after_filter: int
    estimated_insert: int
    estimated_update: int
    estimated_skip: int
    error_rows: int
    ignored_fields: list[str]
    defaulted_fields: list[str]
    upsert_key: tuple[str, ...]
    mapping_preview: list[dict[str, object]]
    warnings: list[str]
    errors: list[RowError]


@dataclass(frozen=True)
class MigrationPlan:
    tables: dict[str, TablePlan]
    total_source_rows: int
    total_insert: int
    total_update: int
    total_skip: int
    total_errors: int
    status: str


@dataclass(frozen=True)
class ApplyTableResult:
    table: str
    inserted: int
    updated: int
    skipped: int
    errors: int
    before_count: int
    after_count: int


@dataclass(frozen=True)
class ApplyResult:
    tables: dict[str, ApplyTableResult]

    @property
    def inserted(self) -> int:
        return sum(item.inserted for item in self.tables.values())

    @property
    def updated(self) -> int:
        return sum(item.updated for item in self.tables.values())

    @property
    def skipped(self) -> int:
        return sum(item.skipped for item in self.tables.values())

    @property
    def errors(self) -> int:
        return sum(item.errors for item in self.tables.values())


TABLE_CONFIGS: dict[str, TableConfig] = {
    "compute_accounts": TableConfig(
        columns=(
            "id",
            "merchant_id",
            "tenant_id",
            "balance_tokens",
            "created_at",
            "updated_at",
        ),
        upsert_key=("merchant_id",),
        datetime_fields=("created_at", "updated_at"),
        int_fields=("id", "balance_tokens"),
        defaults={"balance_tokens": 0},
        required_fields=("merchant_id", "balance_tokens"),
        update_columns=("tenant_id", "balance_tokens", "updated_at"),
    ),
    "compute_transactions": TableConfig(
        columns=(
            "id",
            "merchant_id",
            "tenant_id",
            "transaction_type",
            "delta_tokens",
            "balance_after_tokens",
            "source",
            "remark",
            "model",
            "agent_id",
            "conversation_id",
            "created_at",
        ),
        upsert_key=("id",),
        datetime_fields=("created_at",),
        int_fields=("id", "delta_tokens", "balance_after_tokens", "conversation_id"),
        required_fields=("id", "merchant_id", "transaction_type", "delta_tokens", "balance_after_tokens", "source"),
        update_columns=(
            "merchant_id",
            "tenant_id",
            "transaction_type",
            "delta_tokens",
            "balance_after_tokens",
            "source",
            "remark",
            "model",
            "agent_id",
            "conversation_id",
            "created_at",
        ),
    ),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dry-run/apply 迁移 compute 两表。")
    parser.add_argument("--sqlite-db-path", required=True, help="SQLite 源库路径；必须显式传入。")
    parser.add_argument("--postgres-url", help="PostgreSQL 目标 URL；未传时读取 SMOKE_DATABASE_URL 或 DATABASE_URL。")
    parser.add_argument("--dry-run", action="store_true", default=True, help="默认启用；不写 PostgreSQL。")
    parser.add_argument("--apply", action="store_true", help="仅允许本地/dev，且必须同时传 --yes。")
    parser.add_argument("--yes", action="store_true", help="确认受控 apply。")
    parser.add_argument("--tables", default=",".join(DEFAULT_TABLES), help="逗号分隔表名，默认两表全部。")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> None:
    values = env if env is not None else os.environ
    if args.apply and not args.yes:
        raise MigrationConfigurationError("--apply 必须同时传入 --yes")
    if args.yes and not args.apply:
        raise MigrationConfigurationError("--yes 只能和 --apply 一起使用")
    if args.apply and values.get("APP_ENV", "").lower() == "production":
        raise MigrationConfigurationError("APP_ENV=production 时拒绝 --apply")
    parse_tables(args.tables)
    postgres_url, source = resolve_postgres_url_with_source(args, values)
    if args.apply:
        validate_apply_target(postgres_url, source)


def parse_tables(raw_tables: str | Sequence[str]) -> list[str]:
    if isinstance(raw_tables, str):
        tables = [item.strip() for item in raw_tables.split(",") if item.strip()]
    else:
        tables = list(raw_tables)
    unknown = [table for table in tables if table not in TABLE_CONFIGS]
    if unknown:
        raise MigrationConfigurationError(f"不支持的表: {unknown}")
    return tables or list(DEFAULT_TABLES)


def resolve_postgres_url(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> str:
    return resolve_postgres_url_with_source(args, env)[0]


def resolve_postgres_url_with_source(
    args: argparse.Namespace,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    values = env if env is not None else os.environ
    if getattr(args, "postgres_url", None):
        database_url = args.postgres_url.strip()
        source = "--postgres-url"
    elif values.get("SMOKE_DATABASE_URL"):
        database_url = values["SMOKE_DATABASE_URL"].strip()
        source = "SMOKE_DATABASE_URL"
    elif values.get("DATABASE_URL"):
        database_url = values["DATABASE_URL"].strip()
        source = "DATABASE_URL"
    else:
        raise MigrationConfigurationError("缺少 --postgres-url、SMOKE_DATABASE_URL 或 DATABASE_URL")

    try:
        parsed = parse_database_url(database_url)
    except ValueError as exc:
        raise MigrationConfigurationError(str(exc)) from exc
    if parsed.backend != "postgresql":
        raise MigrationConfigurationError("postgres-url 只允许 PostgreSQL，拒绝 SQLite URL")
    scheme = database_url.split("://", 1)[0]
    if scheme not in ALLOWED_POSTGRES_SCHEMES:
        raise MigrationConfigurationError(f"不支持的 PostgreSQL URL scheme: {scheme}")
    return database_url, source


def validate_apply_target(database_url: str, source: str) -> None:
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/")
    if host not in ALLOWED_APPLY_HOSTS:
        raise MigrationConfigurationError("apply 只允许 dev host: localhost / 127.0.0.1 / postgres / auto-wechat-postgres-dev")
    if database != "auto_wechat":
        raise MigrationConfigurationError("postgres database 必须是 auto_wechat")
    if source == "DATABASE_URL":
        raise MigrationConfigurationError("apply 不允许隐式使用 DATABASE_URL；请显式传 --postgres-url 或 SMOKE_DATABASE_URL")


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def read_sqlite_tables(sqlite_db_path: str, tables: Sequence[str]) -> dict[str, list[dict[str, object]]]:
    path = Path(sqlite_db_path)
    if not path.is_file():
        raise MigrationConfigurationError(f"SQLite 源库不存在: {sqlite_db_path}")
    engine = create_engine(f"sqlite:///{path}")
    try:
        result: dict[str, list[dict[str, object]]] = {}
        with engine.connect() as conn:
            existing_tables = {
                row._mapping["name"]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            for table in tables:
                if table not in existing_tables:
                    raise MigrationReadError(f"SQLite 表不存在: {table}")
                rows = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY id ASC')).fetchall()
                result[table] = [dict(row._mapping) for row in rows]
        return result
    finally:
        engine.dispose()


def map_source_row(table: str, source_row: Mapping[str, object]) -> MappedRow:
    config = TABLE_CONFIGS[table]
    defaults = dict(config.defaults or {})
    row: dict[str, object] = {}
    ignored_fields = sorted(set(source_row) - set(config.columns))
    defaulted_fields: list[str] = []
    warnings: list[str] = []
    for column in config.columns:
        raw_value = source_row.get(column)
        if raw_value is None and column in defaults:
            raw_value = defaults[column]
            defaulted_fields.append(column)
        elif column not in source_row:
            defaulted_fields.append(column)

        value = raw_value
        if column in config.datetime_fields:
            value = _coerce_datetime(column, raw_value)
        elif column in config.int_fields:
            value = _coerce_int(column, raw_value)
        row[column] = value
    _validate_compute_semantics(table, row)
    return MappedRow(row=row, ignored_fields=ignored_fields, defaulted_fields=sorted(set(defaulted_fields)), warnings=warnings)


def build_table_plan(table: str, rows: Sequence[Mapping[str, object]], snapshot: TargetSnapshot) -> TablePlan:
    ignored_fields: set[str] = set()
    defaulted_fields: set[str] = set()
    warnings: list[str] = []
    errors: list[RowError] = []
    preview: list[dict[str, object]] = []
    seen_keys: set[tuple[object, ...]] = set()
    insert_count = 0
    update_count = 0
    skip_count = 0
    existing_keys = snapshot.existing_keys.get(table, set())

    for source_row in rows:
        try:
            mapped = map_source_row(table, source_row)
            _validate_required_fields(table, mapped.row)
            key = unique_key(table, mapped.row)
            ignored_fields.update(mapped.ignored_fields)
            defaulted_fields.update(mapped.defaulted_fields)
            warnings.extend(mapped.warnings)
            if key in seen_keys:
                skip_count += 1
                continue
            seen_keys.add(key)
            if key in existing_keys:
                update_count += 1
            else:
                insert_count += 1
            if len(preview) < 3:
                preview.append(mask_preview_row(mapped.row))
        except Exception as exc:
            errors.append(RowError(source_id=source_row.get("id"), reason=str(exc)))

    return TablePlan(
        table=table,
        sqlite_source_rows=len(rows),
        rows_after_filter=len(rows),
        estimated_insert=insert_count,
        estimated_update=update_count,
        estimated_skip=skip_count,
        error_rows=len(errors),
        ignored_fields=sorted(ignored_fields),
        defaulted_fields=sorted(defaulted_fields),
        upsert_key=TABLE_CONFIGS[table].upsert_key,
        mapping_preview=preview,
        warnings=warnings,
        errors=errors,
    )


def build_migration_plan(
    source_rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
    snapshot: TargetSnapshot,
    tables: Sequence[str],
) -> MigrationPlan:
    summaries = {
        table: build_table_plan(table, source_rows_by_table.get(table, []), snapshot)
        for table in tables
    }
    total_errors = sum(summary.error_rows for summary in summaries.values())
    return MigrationPlan(
        tables=summaries,
        total_source_rows=sum(summary.sqlite_source_rows for summary in summaries.values()),
        total_insert=sum(summary.estimated_insert for summary in summaries.values()),
        total_update=sum(summary.estimated_update for summary in summaries.values()),
        total_skip=sum(summary.estimated_skip for summary in summaries.values()),
        total_errors=total_errors,
        status="DRY_RUN_FAILED" if total_errors else "DRY_RUN_PASS",
    )


def unique_key(table: str, row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row.get(column) for column in TABLE_CONFIGS[table].upsert_key)


def mask_preview_row(row: Mapping[str, object]) -> dict[str, object]:
    masked = dict(row)
    if "remark" in masked and masked["remark"] is not None:
        masked["remark"] = "<redacted_remark>"
    if "agent_id" in masked and masked["agent_id"] is not None:
        masked["agent_id"] = mask_identifier(str(masked["agent_id"]))
    if "conversation_id" in masked and masked["conversation_id"] is not None:
        masked["conversation_id"] = "<redacted_context_id>"
    return masked


def mask_identifier(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def is_revision_at_least(actual: str, expected: str) -> bool:
    actual_num = _leading_revision_number(actual)
    expected_num = _leading_revision_number(expected)
    if actual_num is not None and expected_num is not None:
        return actual_num >= expected_num
    return actual == expected


def _leading_revision_number(value: str) -> int | None:
    match = re.match(r"^0*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _coerce_datetime(column: str, value: object) -> datetime | date | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, int):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, float):
        raise ValueError(f"{column} datetime 不接受 float: {value}")
    text_value = str(value).strip().replace("Z", "+00:00")
    if text_value.isdigit():
        return _coerce_datetime(column, int(text_value))
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        try:
            return datetime.fromisoformat(text_value.replace(" ", "T", 1))
        except ValueError as exc:
            raise ValueError(f"{column} datetime 解析失败: {value}") from exc


def _coerce_int(column: str, value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{column} int 解析失败: {value}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError(f"{column} int 解析失败: {value}")
    text_value = str(value).strip()
    if not re.fullmatch(r"-?\d+", text_value):
        raise ValueError(f"{column} int 解析失败: {value}")
    return int(text_value)


def _validate_required_fields(table: str, row: Mapping[str, object]) -> None:
    for field in TABLE_CONFIGS[table].required_fields:
        if row.get(field) is None or row.get(field) == "":
            raise ValueError(f"{field} 缺失")


def _validate_compute_semantics(table: str, row: Mapping[str, object]) -> None:
    if table == "compute_transactions" and row.get("delta_tokens") == 0:
        raise ValueError("delta_tokens 不能为 0，避免违反 PostgreSQL check constraint")


def build_upsert_sql(table: str, row: Mapping[str, object] | None = None) -> str:
    del row
    config = TABLE_CONFIGS[table]
    columns = list(config.columns)
    quoted_columns = ", ".join(_quote_column(column) for column in columns)
    placeholders = ", ".join(f"${index}" for index, _ in enumerate(columns, start=1))
    conflict_columns = ", ".join(_quote_column(column) for column in config.upsert_key)
    update_columns = [column for column in config.update_columns if column not in config.upsert_key and column != "id"]
    update_clause = ", ".join(f"{_quote_column(column)} = EXCLUDED.{_quote_column(column)}" for column in update_columns)
    return (
        f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_columns}) DO UPDATE SET {update_clause} "
        "RETURNING (xmax = 0) AS inserted"
    )


def _quote_column(column: str) -> str:
    return f'"{column}"'


def row_to_params(table: str, row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row.get(column) for column in TABLE_CONFIGS[table].columns)


def to_asyncpg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


async def read_postgres_snapshot(database_url: str, tables: Sequence[str]) -> TargetSnapshot:
    import asyncpg

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    try:
        revision = str(await conn.fetchval("SELECT version_num FROM alembic_version") or "")
        table_exists: dict[str, bool] = {}
        existing_keys: dict[str, set[tuple[object, ...]]] = {}
        existing_counts: dict[str, int] = {}
        for table in tables:
            exists = bool(
                await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = $1
                    )
                    """,
                    table,
                )
            )
            table_exists[table] = exists
            existing_keys[table] = set()
            existing_counts[table] = 0
            if not exists:
                continue
            existing_counts[table] = int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
            key_columns = TABLE_CONFIGS[table].upsert_key
            select_columns = ", ".join(_quote_column(column) for column in key_columns)
            rows = await conn.fetch(f'SELECT {select_columns} FROM "{table}"')
            existing_keys[table] = {tuple(row[column] for column in key_columns) for row in rows}
        return TargetSnapshot(
            alembic_revision=revision,
            table_exists=table_exists,
            existing_keys=existing_keys,
            existing_counts=existing_counts,
        )
    finally:
        await conn.close()


async def apply_postgres_rows(
    database_url: str,
    source_rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
    snapshot: TargetSnapshot,
    tables: Sequence[str],
) -> ApplyResult:
    if not is_revision_at_least(snapshot.alembic_revision, EXPECTED_REVISION):
        raise MigrationConfigurationError(f"alembic revision 必须至少为 {EXPECTED_REVISION}")
    plan = build_migration_plan(source_rows_by_table, snapshot, tables)
    if plan.total_errors:
        raise MigrationConfigurationError("存在异常行，拒绝部分成功")

    import asyncpg

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    results: dict[str, ApplyTableResult] = {}
    try:
        async with conn.transaction():
            for table in tables:
                seen_keys: set[tuple[object, ...]] = set()
                inserted = 0
                updated = 0
                skipped = 0
                for source_row in source_rows_by_table.get(table, []):
                    mapped = map_source_row(table, source_row)
                    _validate_required_fields(table, mapped.row)
                    key = unique_key(table, mapped.row)
                    if key in seen_keys:
                        skipped += 1
                        continue
                    seen_keys.add(key)
                    was_inserted = await conn.fetchval(
                        build_upsert_sql(table, mapped.row),
                        *row_to_params(table, mapped.row),
                    )
                    if was_inserted:
                        inserted += 1
                    else:
                        updated += 1
                after_count = int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
                results[table] = ApplyTableResult(
                    table=table,
                    inserted=inserted,
                    updated=updated,
                    skipped=skipped,
                    errors=0,
                    before_count=snapshot.existing_counts.get(table, 0),
                    after_count=after_count,
                )
    finally:
        await conn.close()
    return ApplyResult(tables=results)


def print_dry_run_plan(plan: MigrationPlan, safe_postgres_url: str) -> None:
    print("dry-run：不会写 PostgreSQL，不会修改 SQLite，不会修改 .env。")
    print(f"PostgreSQL URL: {safe_postgres_url}")
    for table, summary in plan.tables.items():
        print(f"[{table}] sqlite_source_rows={summary.sqlite_source_rows}")
        print(f"[{table}] rows_after_filter={summary.rows_after_filter}")
        print(f"[{table}] estimated_insert={summary.estimated_insert}")
        print(f"[{table}] estimated_update={summary.estimated_update}")
        print(f"[{table}] estimated_skip={summary.estimated_skip}")
        print(f"[{table}] error_rows={summary.error_rows}")
        print(f"[{table}] ignored_fields={summary.ignored_fields}")
        print(f"[{table}] defaulted_fields={summary.defaulted_fields}")
        print(f"[{table}] upsert_key={summary.upsert_key}")
        print(f"[{table}] mapping_preview={summary.mapping_preview}")
        print(f"[{table}] warnings={summary.warnings}")
    print(f"total_source_rows={plan.total_source_rows}")
    print(f"total_insert={plan.total_insert}")
    print(f"total_update={plan.total_update}")
    print(f"total_skip={plan.total_skip}")
    print(f"total_errors={plan.total_errors}")
    print(f"PostgreSQL 写入: {POSTGRES_WRITE_MODE_DISABLED}")
    print(plan.status)


def print_apply_result(result: ApplyResult) -> None:
    for table, item in result.tables.items():
        print(
            f"[{table}] inserted={item.inserted} updated={item.updated} skipped={item.skipped} "
            f"errors={item.errors} before_count={item.before_count} after_count={item.after_count}"
        )
    print(f"total_inserted={result.inserted}")
    print(f"total_updated={result.updated}")
    print(f"total_skipped={result.skipped}")
    print(f"total_errors={result.errors}")
    print("APPLY_PASS" if result.errors == 0 else "APPLY_FAILED")


def _validate_target_snapshot(snapshot: TargetSnapshot, tables: Sequence[str]) -> None:
    if not is_revision_at_least(snapshot.alembic_revision, EXPECTED_REVISION):
        raise MigrationConfigurationError(f"alembic revision 必须至少为 {EXPECTED_REVISION}")
    missing = [table for table in tables if not snapshot.table_exists.get(table)]
    if missing:
        raise MigrationReadError(f"PostgreSQL 目标表不存在: {missing}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        tables = parse_tables(args.tables)
        postgres_url = resolve_postgres_url(args)
        source_rows = read_sqlite_tables(args.sqlite_db_path, tables)
        snapshot = asyncio.run(read_postgres_snapshot(postgres_url, tables))
        _validate_target_snapshot(snapshot, tables)
        plan = build_migration_plan(source_rows, snapshot, tables)
        if args.apply:
            print("写入前计划摘要:")
            print_dry_run_plan(plan, mask_database_url(postgres_url))
            if plan.total_errors:
                print("APPLY_FAILED: 存在异常行，拒绝部分成功")
                return 3
            result = asyncio.run(apply_postgres_rows(postgres_url, source_rows, snapshot, tables))
            print_apply_result(result)
            return 0 if result.errors == 0 else 3
        print_dry_run_plan(plan, mask_database_url(postgres_url))
        return 0 if plan.total_errors == 0 else 3
    except (MigrationConfigurationError, MigrationReadError, ValueError) as exc:
        print(f"MIGRATION_FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
