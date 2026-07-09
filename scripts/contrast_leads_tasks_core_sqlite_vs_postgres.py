"""四张 leads/tasks core 表的 SQLite / PostgreSQL 只读对照工具。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url
from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration


READ_ONLY_MODE = True
POSTGRES_WRITE_MODE = "disabled"
READ_ONLY_SQL_TEMPLATES = (
    "SELECT version_num FROM alembic_version",
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = $1",
    "SELECT count(*) FROM {table}",
    "SELECT * FROM {table} ORDER BY id ASC",
)


class ContrastConfigurationError(RuntimeError):
    """contrast 参数缺失或越过安全边界。"""


class ContrastReadError(RuntimeError):
    """contrast 只读读取失败。"""


@dataclass(frozen=True)
class SourceSnapshot:
    rows: dict[str, list[dict[str, object]]]
    columns: dict[str, set[str]]


@dataclass(frozen=True)
class TableContrastResult:
    table: str
    sqlite_count: int
    postgres_count: int
    count_match: bool
    sample_key_match: bool
    required_columns_match: bool
    nullable_default_compatibility: bool
    json_field_parseability: bool
    datetime_field_parseability: bool
    mismatch_count: int
    warnings: list[str]


@dataclass(frozen=True)
class ContrastResult:
    tables: dict[str, TableContrastResult]
    status: str
    safe_postgres_url: str = ""
    strict: bool = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读对照 leads/tasks core 四表的 SQLite 与 PostgreSQL 数据。")
    parser.add_argument("--sqlite-db-path", required=True, help="SQLite 源库路径，必须显式传入。")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL URL，输出时会脱敏。")
    parser.add_argument("--tables", default=",".join(migration.DEFAULT_TABLES), help="逗号分隔表名，默认四表全量。")
    parser.add_argument("--output-json", help="可选：写出结构化 contrast 结果。")
    parser.add_argument("--strict", action="store_true", help="开启后 warning 也返回失败。")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    migration.parse_tables(args.tables)
    parsed = parse_database_url(args.postgres_url)
    if parsed.backend != "postgresql":
        raise ContrastConfigurationError("postgres-url 只允许 PostgreSQL，拒绝 SQLite URL")


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def table_key_columns(table: str) -> tuple[str, ...]:
    return migration.TABLE_CONFIGS[table].upsert_key


def read_sqlite_snapshot(sqlite_db_path: str, tables: Sequence[str]) -> SourceSnapshot:
    path = Path(sqlite_db_path)
    if not path.is_file():
        raise ContrastConfigurationError(f"SQLite 源库不存在: {sqlite_db_path}")
    engine = create_engine(f"sqlite:///{path}")
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        rows_by_table: dict[str, list[dict[str, object]]] = {}
        columns_by_table: dict[str, set[str]] = {}
        with engine.connect() as conn:
            for table in tables:
                if table not in existing_tables:
                    raise ContrastReadError(f"SQLite 表不存在: {table}")
                columns_by_table[table] = {column["name"] for column in inspector.get_columns(table)}
                result = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY id ASC')).fetchall()
                rows_by_table[table] = [dict(row._mapping) for row in result]
        return SourceSnapshot(rows=rows_by_table, columns=columns_by_table)
    finally:
        engine.dispose()


async def read_postgres_snapshot(database_url: str, tables: Sequence[str]) -> SourceSnapshot:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - 由运行环境依赖决定
        raise ContrastConfigurationError("缺少 asyncpg 依赖，无法执行 PostgreSQL contrast") from exc

    conn = await asyncpg.connect(migration.to_asyncpg_dsn(database_url))
    try:
        rows_by_table: dict[str, list[dict[str, object]]] = {}
        columns_by_table: dict[str, set[str]] = {}
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
            if not exists:
                raise ContrastReadError(f"PostgreSQL 表不存在: {table}")
            column_rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                """,
                table,
            )
            columns_by_table[table] = {row["column_name"] for row in column_rows}
            result = await conn.fetch(f'SELECT * FROM "{table}" ORDER BY id ASC')
            rows_by_table[table] = [dict(row) for row in result]
        return SourceSnapshot(rows=rows_by_table, columns=columns_by_table)
    finally:
        await conn.close()


def build_table_contrast(
    table: str,
    *,
    sqlite_rows: Sequence[Mapping[str, object]],
    postgres_rows: Sequence[Mapping[str, object]],
    sqlite_columns: set[str],
    postgres_columns: set[str],
) -> TableContrastResult:
    warnings: list[str] = []
    required_columns_match = _required_columns_match(table, sqlite_columns, postgres_columns, warnings)
    json_ok = _json_parseability(table, "SQLite", sqlite_rows, warnings)
    json_ok = _json_parseability(table, "PostgreSQL", postgres_rows, warnings) and json_ok
    datetime_ok = _datetime_parseability(table, "SQLite", sqlite_rows, warnings)
    datetime_ok = _datetime_parseability(table, "PostgreSQL", postgres_rows, warnings) and datetime_ok

    sqlite_by_key = _rows_by_key(table, sqlite_rows, "SQLite", warnings)
    postgres_by_key = _rows_by_key(table, postgres_rows, "PostgreSQL", warnings)
    sqlite_keys = set(sqlite_by_key)
    postgres_keys = set(postgres_by_key)
    missing_in_pg = sqlite_keys - postgres_keys
    extra_in_pg = postgres_keys - sqlite_keys
    mismatch_count = len(missing_in_pg) + len(extra_in_pg)
    if missing_in_pg:
        warnings.append(f"{table} PostgreSQL 缺少 key: {_format_keys(missing_in_pg)}")
    if extra_in_pg:
        warnings.append(f"{table} PostgreSQL 额外 key: {_format_keys(extra_in_pg)}")
    sqlite_count = len(sqlite_rows)
    postgres_count = len(postgres_rows)
    return TableContrastResult(
        table=table,
        sqlite_count=sqlite_count,
        postgres_count=postgres_count,
        count_match=sqlite_count == postgres_count,
        sample_key_match=not missing_in_pg and not extra_in_pg,
        required_columns_match=required_columns_match,
        nullable_default_compatibility=required_columns_match,
        json_field_parseability=json_ok,
        datetime_field_parseability=datetime_ok,
        mismatch_count=mismatch_count if mismatch_count else abs(sqlite_count - postgres_count),
        warnings=warnings,
    )


def build_contrast_result(
    tables: Mapping[str, TableContrastResult],
    *,
    strict: bool,
    safe_postgres_url: str = "",
) -> ContrastResult:
    has_failed = any(
        not item.count_match
        or not item.sample_key_match
        or not item.required_columns_match
        or item.mismatch_count > 0
        for item in tables.values()
    )
    has_warning = any(
        item.warnings
        or not item.nullable_default_compatibility
        or not item.json_field_parseability
        or not item.datetime_field_parseability
        for item in tables.values()
    )
    if has_failed or (strict and has_warning):
        status = "CONTRAST_FAILED"
    elif has_warning:
        status = "CONTRAST_WARN"
    else:
        status = "CONTRAST_PASS"
    return ContrastResult(
        tables=dict(tables),
        status=status,
        safe_postgres_url=safe_postgres_url,
        strict=strict,
    )


def build_snapshot_contrast(
    sqlite_snapshot: SourceSnapshot,
    postgres_snapshot: SourceSnapshot,
    tables: Sequence[str],
    *,
    strict: bool,
    safe_postgres_url: str,
) -> ContrastResult:
    table_results = {
        table: build_table_contrast(
            table,
            sqlite_rows=sqlite_snapshot.rows.get(table, []),
            postgres_rows=postgres_snapshot.rows.get(table, []),
            sqlite_columns=sqlite_snapshot.columns.get(table, set()),
            postgres_columns=postgres_snapshot.columns.get(table, set()),
        )
        for table in tables
    }
    return build_contrast_result(table_results, strict=strict, safe_postgres_url=safe_postgres_url)


def write_output_json(result: ContrastResult, output_path: str | Path) -> None:
    path = Path(output_path)
    path.write_text(json.dumps(_result_to_dict(result), ensure_ascii=False, indent=2), encoding="utf-8")


def exit_code_for_result(result: ContrastResult) -> int:
    return 1 if result.status == "CONTRAST_FAILED" else 0


def print_result(result: ContrastResult) -> None:
    print(f"PostgreSQL URL: {result.safe_postgres_url}")
    print(f"PostgreSQL 写入: {POSTGRES_WRITE_MODE}")
    for table, item in result.tables.items():
        print(f"[{table}] sqlite_count={item.sqlite_count}")
        print(f"[{table}] postgres_count={item.postgres_count}")
        print(f"[{table}] count_match={item.count_match}")
        print(f"[{table}] sample_key_match={item.sample_key_match}")
        print(f"[{table}] required_columns_match={item.required_columns_match}")
        print(f"[{table}] nullable_default_compatibility={item.nullable_default_compatibility}")
        print(f"[{table}] json_field_parseability={item.json_field_parseability}")
        print(f"[{table}] datetime_field_parseability={item.datetime_field_parseability}")
        print(f"[{table}] mismatch_count={item.mismatch_count}")
        print(f"[{table}] warnings={item.warnings}")
    print(result.status)


def _required_columns_match(
    table: str,
    sqlite_columns: set[str],
    postgres_columns: set[str],
    warnings: list[str],
) -> bool:
    config = migration.TABLE_CONFIGS[table]
    required_columns = set(config.required_fields) | set(config.upsert_key)
    missing_sqlite = sorted(required_columns - sqlite_columns)
    missing_postgres = sorted(required_columns - postgres_columns)
    if missing_sqlite:
        warnings.append(f"{table} SQLite 缺少必要列: {missing_sqlite}")
    if missing_postgres:
        warnings.append(f"{table} PostgreSQL 缺少必要列: {missing_postgres}")
    return not missing_sqlite and not missing_postgres


def _json_parseability(
    table: str,
    source_name: str,
    rows: Sequence[Mapping[str, object]],
    warnings: list[str],
) -> bool:
    ok = True
    for index, row in enumerate(rows, start=1):
        for column in migration.TABLE_CONFIGS[table].json_fields:
            value = row.get(column)
            if value is None or value == "" or isinstance(value, (dict, list)):
                continue
            try:
                json.loads(str(value))
            except (TypeError, json.JSONDecodeError):
                ok = False
                warnings.append(f"{table} {source_name} 第 {index} 行 {column} JSON 解析失败")
    return ok


def _datetime_parseability(
    table: str,
    source_name: str,
    rows: Sequence[Mapping[str, object]],
    warnings: list[str],
) -> bool:
    ok = True
    for index, row in enumerate(rows, start=1):
        for column in migration.TABLE_CONFIGS[table].datetime_fields:
            value = row.get(column)
            if value is None or value == "":
                continue
            try:
                migration._coerce_datetime(column, value)
            except ValueError:
                ok = False
                warnings.append(f"{table} {source_name} 第 {index} 行 {column} datetime 解析失败")
    return ok


def _rows_by_key(
    table: str,
    rows: Sequence[Mapping[str, object]],
    source_name: str,
    warnings: list[str],
) -> dict[tuple[object, ...], Mapping[str, object]]:
    by_key: dict[tuple[object, ...], Mapping[str, object]] = {}
    for index, row in enumerate(rows, start=1):
        key = tuple(row.get(column) for column in table_key_columns(table))
        if any(value is None or value == "" for value in key):
            warnings.append(f"{table} {source_name} 第 {index} 行 key 缺失: {key}")
            continue
        if key in by_key:
            warnings.append(f"{table} {source_name} key 重复: {key}")
            continue
        by_key[key] = row
    return by_key


def _format_keys(keys: set[tuple[object, ...]]) -> str:
    return ", ".join(str(key) for key in sorted(keys, key=str)[:3])


def _result_to_dict(result: ContrastResult) -> dict[str, object]:
    payload = asdict(result)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        tables = migration.parse_tables(args.tables)
        safe_url = mask_database_url(args.postgres_url)
        sqlite_snapshot = read_sqlite_snapshot(args.sqlite_db_path, tables)
        postgres_snapshot = asyncio.run(read_postgres_snapshot(args.postgres_url, tables))
        result = build_snapshot_contrast(
            sqlite_snapshot,
            postgres_snapshot,
            tables,
            strict=args.strict,
            safe_postgres_url=safe_url,
        )
        print_result(result)
        if args.output_json:
            write_output_json(result, args.output_json)
        return exit_code_for_result(result)
    except (ContrastConfigurationError, ContrastReadError, ValueError) as exc:
        print(f"CONTRAST_FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
