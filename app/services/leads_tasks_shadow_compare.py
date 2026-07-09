"""leads/tasks 运行态 shadow read 对照工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


PII_FIELDS = {"phone", "wechat", "wechat_id", "wechat_nickname", "customer_contact", "target_nickname", "name"}


@dataclass(frozen=True)
class ShadowCompareResult:
    sqlite_count: int = 0
    pg_count: int = 0
    count_match: bool = True
    key_match: bool = True
    mismatch_count: int = 0
    warnings: list[str] = field(default_factory=list)


def compare_shadow_rows(
    *,
    table: str,
    key_columns: Sequence[str],
    sqlite_rows: Sequence[Mapping[str, object]],
    pg_rows: Sequence[Mapping[str, object]],
) -> ShadowCompareResult:
    """只做轻量 count/key 对照，不做全字段 diff。"""
    warnings: list[str] = []
    sqlite_by_key = _rows_by_key(table, key_columns, sqlite_rows, "SQLite", warnings)
    pg_by_key = _rows_by_key(table, key_columns, pg_rows, "PostgreSQL", warnings)
    sqlite_keys = set(sqlite_by_key)
    pg_keys = set(pg_by_key)
    missing = sqlite_keys - pg_keys
    extra = pg_keys - sqlite_keys
    if missing:
        warnings.append(f"{table} PostgreSQL 缺少 key: {_format_keys(missing)}")
    if extra:
        warnings.append(f"{table} PostgreSQL 额外 key: {_format_keys(extra)}")

    mismatch_count = len(missing) + len(extra)
    return ShadowCompareResult(
        sqlite_count=len(sqlite_rows),
        pg_count=len(pg_rows),
        count_match=len(sqlite_rows) == len(pg_rows),
        key_match=not missing and not extra,
        mismatch_count=mismatch_count if mismatch_count else abs(len(sqlite_rows) - len(pg_rows)),
        warnings=warnings,
    )


def redact_row(row: Mapping[str, object]) -> dict[str, object]:
    """脱敏行摘要，避免 shadow 日志暴露手机号、微信号或昵称。"""
    result: dict[str, object] = {}
    for key, value in row.items():
        if key in PII_FIELDS and value not in (None, ""):
            result[key] = _mask_text(str(value))
        else:
            result[key] = value
    return result


def _rows_by_key(
    table: str,
    key_columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
    source: str,
    warnings: list[str],
) -> dict[tuple[object, ...], Mapping[str, object]]:
    result: dict[tuple[object, ...], Mapping[str, object]] = {}
    for row in rows:
        key = tuple(row.get(column) for column in key_columns)
        if any(value is None for value in key):
            warnings.append(f"{table} {source} 存在缺失 key 的行: {redact_row(row)}")
            continue
        result[key] = row
    return result


def _format_keys(keys: set[tuple[object, ...]]) -> str:
    sample = sorted(str(key) for key in keys)[:5]
    return ", ".join(sample)


def _mask_text(value: str) -> str:
    if len(value) <= 2:
        return "***"
    return f"{value[:1]}***{value[-1:]}"
