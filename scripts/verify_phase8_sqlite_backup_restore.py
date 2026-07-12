#!/usr/bin/env python3
"""验证 Phase 8 SQLite backup/restore 保真度。

只使用标准库 sqlite3，以只读方式比较 --before 和 --restored 两个库：
- 全部用户表和索引的规范化 sqlite_master.sql
- PRAGMA table_info
- 逐表行数
- 按主键/列顺序流式计算的规范化行摘要

输出只包含表名、计数和 PASS/FAIL，不输出字段值、客户原文或 storage key。
这不是业务代码，也不参与生产回滚；仅用于 Phase 8 迁移前确认 backup API 副本与源库一致。

用法：
    python scripts/verify_phase8_sqlite_backup_restore.py --before <db> --restored <db>

退出码：
    0 — 全部一致
    1 — 存在不一致
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys


def _safe_ident(name: str) -> str:
    if not re.fullmatch(r"\w+", name):
        raise ValueError(f"非法表名标识符: {name!r}")
    return name


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _schema_sql(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type IN ('table','index') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return [r[0].strip() for r in rows if r[0]]


def _table_info(conn: sqlite3.Connection, table: str):
    return conn.execute(f"PRAGMA table_info({_safe_ident(table)})").fetchall()


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {_safe_ident(table)}").fetchone()[0]


def _row_signature(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """按主键（或全部列）顺序流式计算的规范化行摘要（sorted tuple of normalized rows）。"""
    info = _table_info(conn, table)
    col_names = [c[1] for c in info]
    pk_cols = [c[1] for c in info if c[5] > 0]
    order_cols = ",".join(pk_cols) if pk_cols else ",".join(col_names)
    rows = conn.execute(
        f"SELECT * FROM {_safe_ident(table)} ORDER BY {order_cols}"
    ).fetchall()
    normalized = [
        tuple("__NULL__" if v is None else str(v) for v in row)
        for row in rows
    ]
    return sorted(normalized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 Phase 8 SQLite backup/restore 保真度")
    parser.add_argument("--before", required=True, help="源库路径（0028 前）")
    parser.add_argument("--restored", required=True, help="恢复副本路径")
    args = parser.parse_args(argv)

    before = sqlite3.connect(f"file:{args.before}?mode=ro", uri=True)
    restored = sqlite3.connect(f"file:{args.restored}?mode=ro", uri=True)

    all_pass = True

    # 1. 规范化 schema 比较
    before_schema = _schema_sql(before)
    restored_schema = _schema_sql(restored)
    schema_match = before_schema == restored_schema
    print(f"schema_sql: {'PASS' if schema_match else 'FAIL'} "
          f"(before_items={len(before_schema)} restored_items={len(restored_schema)})")
    if not schema_match:
        all_pass = False

    # 2. 逐表比较
    before_tables = set(_user_tables(before))
    restored_tables = set(_user_tables(restored))
    for table in sorted(before_tables | restored_tables):
        if table not in before_tables:
            print(f"{table}: FAIL (只存在于 restored)")
            all_pass = False
            continue
        if table not in restored_tables:
            print(f"{table}: FAIL (只存在于 before)")
            all_pass = False
            continue

        info_match = _table_info(before, table) == _table_info(restored, table)
        bc = _row_count(before, table)
        rc = _row_count(restored, table)
        count_match = bc == rc
        sig_match = _row_signature(before, table) == _row_signature(restored, table)

        status = "PASS" if (info_match and count_match and sig_match) else "FAIL"
        if status == "FAIL":
            all_pass = False
            detail = []
            if not info_match:
                detail.append("table_info mismatch")
            if not count_match:
                detail.append(f"count before={bc} restored={rc}")
            if not sig_match:
                detail.append("row signature mismatch")
            print(f"{table}: {status} (rows={bc}) [{'; '.join(detail)}]")
        else:
            print(f"{table}: {status} (rows={bc})")

    before.close()
    restored.close()

    if all_pass:
        print("\n全部一致：backup/restore 保真")
        return 0
    print("\n存在不一致：backup/restore 有损或基线不同", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
