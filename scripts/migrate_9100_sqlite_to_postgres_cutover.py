"""9100 RAG metadata SQLite -> PostgreSQL cutover 一次性迁移脚本。

类比 9000 `migrate_9000_sqlite_to_postgres_cutover.py`，覆盖 9100 alembic 0002 的 7 张
RAG metadata 表。默认 dry-run；apply 只允许 dev/staging 显式确认，不允许隐式使用
RAG_DATABASE_URL，APP_ENV=production 时拒绝 apply。

P3-E-9100。Milvus 是向量检索副本，embedding_json 已存 metadata DB，本脚本只迁 metadata。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


EXPECTED_REVISION = "0002_create_rag_metadata"
POSTGRES_WRITE_MODE_DISABLED = "disabled"
ALLOWED_POSTGRES_SCHEMES = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
ALLOWED_APPLY_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
# 默认 xg_douyin_ai_cs（dev/生产）；staging 等隔离环境通过 RAG_TARGET_DATABASE_NAME 覆盖
# （如 xg_douyin_ai_cs_staging），避免 validate_apply_target 库名校验拒绝 staging 演练。
# 生产安全不受影响：APP_ENV=production 仍拒绝 apply，host 仍校验 ALLOWED_APPLY_HOSTS。
TARGET_DATABASE_NAME = os.environ.get("RAG_TARGET_DATABASE_NAME", "xg_douyin_ai_cs")

# 9100 RAG metadata 7 张表（alembic 0002）。SQLite 列名与 PG 完全一致，无 synthetic 映射。
CUTOVER_TABLES = [
    "knowledge_categories",
    "knowledge_documents",
    "knowledge_chunks",
    "rag_training_runs",
    "llm_call_logs",
    "knowledge_training_sessions",
    "knowledge_training_feedbacks",
]

# 幂等冲突列：sessions 主键是 training_id（业务生成），其余表是自增 id。
CONFLICT_COLUMNS: dict[str, str] = {
    "knowledge_categories": "id",
    "knowledge_documents": "id",
    "knowledge_chunks": "id",
    "rag_training_runs": "id",
    "llm_call_logs": "id",
    "knowledge_training_sessions": "training_id",
    "knowledge_training_feedbacks": "id",
}

# 布尔列：SQLite init_db 是 INTEGER 0/1，PG alembic 0002 是 BOOLEAN。coerce_bool 转换。
# is_ 前缀自动识别；used_knowledge_base / auto_ingest 不符合前缀规则，显式声明。
BOOL_COLUMNS = {"used_knowledge_base", "auto_ingest"}


class MigrationConfigurationError(RuntimeError):
    """迁移配置缺失或越过安全边界。"""


class MigrationReadError(RuntimeError):
    """读取 SQLite 或 PostgreSQL 快照失败。"""


@dataclass(frozen=True)
class ColumnMapping:
    copy_columns: list[str]
    ignored_source_columns: list[str]
    defaulted_target_columns: list[str]


@dataclass(frozen=True)
class TargetSnapshot:
    alembic_revision: str
    table_exists: dict[str, bool]
    columns: dict[str, set[str]]
    # 按 conflict_column 已字符串化的现有主键集合（sessions 是 training_id 字符串，其余 id 字符串）
    existing_keys: dict[str, set[str]]
    existing_counts: dict[str, int]


@dataclass
class RowError:
    source_key: object
    reason: str


@dataclass
class TablePlan:
    table: str
    sqlite_source_rows: int = 0
    estimated_insert: int = 0
    estimated_update: int = 0
    estimated_skip: int = 0
    error_rows: int = 0
    ignored_fields: list[str] = field(default_factory=list)
    defaulted_fields: list[str] = field(default_factory=list)
    mapping_preview: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


@dataclass
class MigrationPlan:
    tables: dict[str, TablePlan]
    total_source_rows: int = 0
    total_insert: int = 0
    total_update: int = 0
    total_skip: int = 0
    total_errors: int = 0
    status: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dry-run/apply 迁移 9100 RAG metadata 表。")
    parser.add_argument("--sqlite-db-path", required=True, help="9100 SQLite 源库路径，必须显式传入。")
    parser.add_argument("--postgres-url", help="PostgreSQL 目标 URL；未传时读取 SMOKE_DATABASE_URL 或 RAG_DATABASE_URL。")
    parser.add_argument("--dry-run", action="store_true", default=True, help="默认启用，不写 PostgreSQL。")
    parser.add_argument("--apply", action="store_true", help="受控 apply，必须同时传 --yes。")
    parser.add_argument("--yes", action="store_true", help="确认受控 apply，只能和 --apply 一起使用。")
    parser.add_argument("--tables", default=",".join(CUTOVER_TABLES), help="逗号分隔表名，默认 7 张表。")
    return parser.parse_args(argv)


def parse_tables(raw_tables: str | Sequence[str]) -> list[str]:
    tables = [item.strip() for item in raw_tables.split(",") if item.strip()] if isinstance(raw_tables, str) else list(raw_tables)
    unknown = [table for table in tables if table not in CUTOVER_TABLES]
    if unknown:
        raise MigrationConfigurationError(f"不支持的表: {unknown}")
    return tables or list(CUTOVER_TABLES)


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
    elif values.get("RAG_DATABASE_URL"):
        database_url = values["RAG_DATABASE_URL"].strip()
        source = "RAG_DATABASE_URL"
    else:
        raise MigrationConfigurationError("缺少 --postgres-url、SMOKE_DATABASE_URL 或 RAG_DATABASE_URL")

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
    if source == "RAG_DATABASE_URL":
        raise MigrationConfigurationError("apply 不允许隐式使用 RAG_DATABASE_URL；请显式传 --postgres-url 或 SMOKE_DATABASE_URL")
    if (parsed.hostname or "").lower() not in ALLOWED_APPLY_HOSTS:
        raise MigrationConfigurationError("apply 只允许 dev/staging host: localhost / 127.0.0.1 / postgres / auto-wechat-postgres-dev")
    if (parsed.path or "").lstrip("/") != TARGET_DATABASE_NAME:
        raise MigrationConfigurationError(f"postgres database 必须是 {TARGET_DATABASE_NAME}")


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def build_column_mapping(table: str, sqlite_columns: set[str], pg_columns: set[str]) -> ColumnMapping:
    # 9100 列名 SQLite 与 PG 完全一致，直接取交集 copy
    shared = sqlite_columns & pg_columns
    copy_columns = (["id"] if "id" in shared else []) + [column for column in sorted(shared) if column != "id"]
    ignored = sorted(sqlite_columns - pg_columns)
    defaulted = sorted(pg_columns - sqlite_columns)
    return ColumnMapping(copy_columns=copy_columns, ignored_source_columns=ignored, defaulted_target_columns=defaulted)


def read_sqlite_tables(sqlite_db_path: str, tables: Sequence[str]) -> dict[str, list[dict[str, object]]]:
    path = Path(sqlite_db_path)
    if not path.is_file():
        raise MigrationConfigurationError(f"SQLite 源库不存在: {sqlite_db_path}")

    engine = create_engine(f"sqlite:///{path}")
    try:
        result: dict[str, list[dict[str, object]]] = {}
        with engine.connect() as conn:
            existing_tables = {row._mapping["name"] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            for table in tables:
                if table not in existing_tables:
                    raise MigrationReadError(f"SQLite 表不存在: {table}")
                # 按 conflict_column 排序（sessions 用 training_id，其余 id）；无 conflict 列时不排序
                conflict_col = CONFLICT_COLUMNS.get(table)
                order_clause = f' ORDER BY "{conflict_col}" ASC' if conflict_col else ""
                rows = conn.execute(text(f'SELECT * FROM "{table}"{order_clause}')).fetchall()
                result[table] = [dict(row._mapping) for row in rows]
        return result
    finally:
        engine.dispose()


def build_table_plan(
    table: str,
    rows: Sequence[Mapping[str, object]],
    mapping: ColumnMapping,
    snapshot: TargetSnapshot,
) -> TablePlan:
    existing_keys = snapshot.existing_keys.get(table, set())
    conflict_col = CONFLICT_COLUMNS.get(table)
    seen_keys: set[str] = set()
    insert_count = 0
    update_count = 0
    skip_count = 0
    errors: list[RowError] = []
    warnings: list[str] = []
    preview: list[dict[str, object]] = []

    for source_row in rows:
        try:
            mapped, row_warnings = map_row(source_row, mapping)
            warnings.extend(row_warnings)
            if not conflict_col:
                raise ValueError(f"表 {table} 缺 conflict_column 配置")
            row_key = mapped.get(conflict_col)
            if row_key is None:
                raise ValueError(f"{conflict_col} 缺失")
            key_str = str(row_key)
            if key_str in seen_keys:
                skip_count += 1
                continue
            seen_keys.add(key_str)
            if key_str in existing_keys:
                update_count += 1
            else:
                insert_count += 1
            if len(preview) < 3:
                preview.append(mask_preview_row(mapped))
        except Exception as exc:
            errors.append(RowError(source_key=source_row.get(conflict_col) if conflict_col else source_row.get("id"), reason=str(exc)))

    return TablePlan(
        table=table,
        sqlite_source_rows=len(rows),
        estimated_insert=insert_count,
        estimated_update=update_count,
        estimated_skip=skip_count,
        error_rows=len(errors),
        ignored_fields=mapping.ignored_source_columns,
        defaulted_fields=mapping.defaulted_target_columns,
        mapping_preview=preview,
        warnings=warnings,
        errors=errors,
    )


def map_row(source_row: Mapping[str, object], mapping: ColumnMapping) -> tuple[dict[str, object], list[str]]:
    result: dict[str, object] = {}
    warnings: list[str] = []
    for column in mapping.copy_columns:
        value = source_row.get(column)
        value, warning = coerce_value(column, value)
        if warning:
            warnings.append(warning)
        result[column] = value
    return result, warnings


def coerce_value(column: str, value: object) -> tuple[object, str | None]:
    # SQLite 空字符串 '' 语义是空字符串而非 NULL。PG NOT NULL DEFAULT '' 列
    # 显式 INSERT NULL 仍违反约束（DEFAULT 只对省略该列生效，不兜底显式 NULL）。
    # 保留 '' 让 INSERT 合法且忠实源数据；真 NULL 才归一为 None。
    if value is None:
        return None, None
    name = column.lower()
    if name.endswith("_at") or name.endswith("_time") or name.endswith("_deadline"):
        return coerce_datetime(column, value), None
    if name.endswith("_json") or name.startswith("raw_") or name in {"raw_body", "raw_data", "raw_result"}:
        parsed, warning = coerce_json(column, value)
        return parsed, warning
    if name in BOOL_COLUMNS or name.startswith("is_") or name.endswith("_enabled") or name in {"enabled"}:
        return coerce_bool(value), None
    return value, None


def coerce_json(column: str, value: object) -> tuple[object, str | None]:
    if isinstance(value, (dict, list)):
        return value, None
    try:
        return json.loads(str(value)), None
    except (TypeError, json.JSONDecodeError):
        return value, f"{column} JSON 解析失败，保留原始字符串"


def coerce_datetime(column: str, value: object) -> datetime | date:
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text_value = str(value).strip().replace("Z", "+00:00")
    if text_value.isdigit():
        return coerce_datetime(column, int(text_value))
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        try:
            return datetime.fromisoformat(text_value.replace(" ", "T", 1))
        except ValueError as exc:
            raise ValueError(f"{column} datetime 解析失败: {value}") from exc


def coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def mask_preview_row(row: Mapping[str, object]) -> dict[str, object]:
    masked = dict(row)
    for field_name, value in list(masked.items()):
        if value is None:
            continue
        name = field_name.lower()
        if "phone" in name or "contact" in name:
            masked[field_name] = mask_contact(str(value))
        elif "token" in name or "secret" in name or name.endswith("open_id") or name in {"user_id", "union_id"}:
            masked[field_name] = mask_identifier(str(value))
        elif name.startswith("raw_") or name.endswith("_json"):
            masked[field_name] = "<redacted_json>"
    return masked


def mask_contact(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(value) > 4:
        return value[:2] + "***" + value[-2:]
    return "***"


def mask_identifier(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def build_migration_plan(
    source_rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
    snapshot: TargetSnapshot,
    tables: Sequence[str],
) -> MigrationPlan:
    plans: dict[str, TablePlan] = {}
    for table in tables:
        mapping = build_column_mapping(
            table,
            set(source_rows_by_table.get(table, [{}])[0].keys()) if source_rows_by_table.get(table) else {"id"},
            snapshot.columns.get(table, set()),
        )
        plans[table] = build_table_plan(table, source_rows_by_table.get(table, []), mapping, snapshot)
    total_errors = sum(item.error_rows for item in plans.values())
    return MigrationPlan(
        tables=plans,
        total_source_rows=sum(item.sqlite_source_rows for item in plans.values()),
        total_insert=sum(item.estimated_insert for item in plans.values()),
        total_update=sum(item.estimated_update for item in plans.values()),
        total_skip=sum(item.estimated_skip for item in plans.values()),
        total_errors=total_errors,
        status="DRY_RUN_FAILED" if total_errors else "DRY_RUN_PASS",
    )


def ensure_plan_can_apply(plan: MigrationPlan) -> None:
    if plan.total_errors:
        raise MigrationConfigurationError("存在异常行，拒绝部分成功")


def is_revision_at_least(actual: str, expected: str) -> bool:
    actual_num = leading_revision_number(actual)
    expected_num = leading_revision_number(expected)
    if actual_num is not None and expected_num is not None:
        return actual_num >= expected_num
    return actual == expected


def leading_revision_number(value: str) -> int | None:
    match = re.match(r"^0*(\d+)", value or "")
    return int(match.group(1)) if match else None


def validate_snapshot(snapshot: TargetSnapshot, tables: Sequence[str]) -> None:
    if not is_revision_at_least(snapshot.alembic_revision, EXPECTED_REVISION):
        raise MigrationConfigurationError(f"alembic revision 必须至少为 {EXPECTED_REVISION}")
    missing = [table for table in tables if not snapshot.table_exists.get(table)]
    if missing:
        raise MigrationReadError(f"PostgreSQL 目标表不存在: {missing}")


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
        columns: dict[str, set[str]] = {}
        existing_keys: dict[str, set[str]] = {}
        counts: dict[str, int] = {}
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
            columns[table] = set()
            existing_keys[table] = set()
            counts[table] = 0
            if not exists:
                continue
            columns[table] = {
                row["column_name"]
                for row in await conn.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = $1
                    """,
                    table,
                )
            }
            counts[table] = int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
            conflict_col = CONFLICT_COLUMNS.get(table)
            if conflict_col and conflict_col in columns[table]:
                # 按 conflict_column 读现有主键，统一字符串化（sessions 是 training_id 字符串，其余 id 数字字符串）
                existing_keys[table] = {str(row[conflict_col]) for row in await conn.fetch(f'SELECT "{conflict_col}" FROM "{table}"')}
        return TargetSnapshot(revision, table_exists, columns, existing_keys, counts)
    finally:
        await conn.close()


def build_upsert_sql(table: str, columns: Sequence[str]) -> str:
    conflict_col = CONFLICT_COLUMNS[table]
    quoted_columns = ", ".join(quote_ident(column) for column in columns)
    placeholders = ", ".join(f"${index}" for index, _ in enumerate(columns, start=1))
    update_columns = [column for column in columns if column != conflict_col]
    update_clause = ", ".join(f"{quote_ident(column)} = EXCLUDED.{quote_ident(column)}" for column in update_columns) or f"{quote_ident(conflict_col)} = EXCLUDED.{quote_ident(conflict_col)}"
    return (
        f"INSERT INTO {quote_ident(table)} ({quoted_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({quote_ident(conflict_col)}) DO UPDATE SET {update_clause} "
        "RETURNING (xmax = 0) AS inserted"
    )


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def apply_postgres_rows(
    database_url: str,
    source_rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
    snapshot: TargetSnapshot,
    tables: Sequence[str],
) -> MigrationPlan:
    validate_snapshot(snapshot, tables)
    plan = build_migration_plan(source_rows_by_table, snapshot, tables)
    ensure_plan_can_apply(plan)

    import asyncpg

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    try:
        async with conn.transaction():
            for table, table_plan in plan.tables.items():
                mapping = build_column_mapping(
                    table,
                    set(source_rows_by_table.get(table, [{}])[0].keys()) if source_rows_by_table.get(table) else {"id"},
                    snapshot.columns.get(table, set()),
                )
                columns = mapping.copy_columns
                sql = build_upsert_sql(table, columns)
                conflict_col = CONFLICT_COLUMNS[table]
                seen_keys: set[str] = set()
                for source_row in source_rows_by_table.get(table, []):
                    mapped, _warnings = map_row(source_row, mapping)
                    key_str = str(mapped[conflict_col])
                    if key_str in seen_keys:
                        continue
                    seen_keys.add(key_str)
                    await conn.fetchval(sql, *[prepare_param(mapped[column]) for column in columns])
                print(f"[{table}] applied insert={table_plan.estimated_insert} update={table_plan.estimated_update}")
        return plan
    finally:
        await conn.close()


def prepare_param(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def print_dry_run_plan(plan: MigrationPlan, safe_url: str) -> None:
    print("dry-run：不会写 PostgreSQL，不会修改 SQLite，不会修改 .env。")
    print(f"PostgreSQL URL: {safe_url}")
    for table, item in plan.tables.items():
        print(
            f"[{table}] source={item.sqlite_source_rows} insert={item.estimated_insert} "
            f"update={item.estimated_update} skip={item.estimated_skip} error={item.error_rows}"
        )
        print(f"[{table}] ignored_fields={item.ignored_fields}")
        print(f"[{table}] defaulted_fields={item.defaulted_fields}")
        print(f"[{table}] mapping_preview={item.mapping_preview}")
        print(f"[{table}] warnings={item.warnings}")
    print(f"total_source_rows={plan.total_source_rows}")
    print(f"insert/update/skip/error = {plan.total_insert}/{plan.total_update}/{plan.total_skip}/{plan.total_errors}")
    print(f"PostgreSQL 写入: {POSTGRES_WRITE_MODE_DISABLED}")
    print(plan.status)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        tables = parse_tables(args.tables)
        postgres_url = resolve_postgres_url(args)
        source_rows = read_sqlite_tables(args.sqlite_db_path, tables)
        snapshot = asyncio.run(read_postgres_snapshot(postgres_url, tables))
        validate_snapshot(snapshot, tables)
        plan = build_migration_plan(source_rows, snapshot, tables)
        if args.apply:
            print("写入前计划摘要:")
            print_dry_run_plan(plan, mask_database_url(postgres_url))
            ensure_plan_can_apply(plan)
            asyncio.run(apply_postgres_rows(postgres_url, source_rows, snapshot, tables))
            print("APPLY_PASS")
            return 0
        print_dry_run_plan(plan, mask_database_url(postgres_url))
        return 0 if plan.total_errors == 0 else 3
    except (MigrationConfigurationError, MigrationReadError, ValueError) as exc:
        print(f"MIGRATION_FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
