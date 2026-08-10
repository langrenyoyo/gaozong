"""DB-BL-2C 只读链审计：静态扫描 migration chain 的 create_table-vs-add_column 重复列缺陷。

仅读取迁移源文件（AST 解析），不连接任何数据库，不修改任何文件。
目的：界定 0025 之外是否存在更多"建表已含某列 + 后续 migration 又 add_column 同一列"
      的同类缺陷，从而判断 alembic upgrade 从空库自举会在哪些点失败（修复范围）。

判定规则（仅静态，CODE 级，不等于 PG runtime 全集）：
  对同一张表 T，若某列 C 同时出现在：
    - 某个 create_table(T, ...) 的列定义中
    - 且该 create_table 之后的某个 add_column(T, C) 中
  则该列在空库自举时会触发 DuplicateColumn（create 已建，add 又加）。

  注意：本脚本只检测 create_table 内显式 sa.Column 字面量；不追踪 op.execute(raw SQL)
  的 ALTER TABLE，也不解析动态构造的列名。属保守下界扫描。
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "postgres" / "auto_wechat" / "versions"


def _str_const(node: ast.AST) -> str | None:
    """取字符串字面量；非字量返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_call(node: ast.AST) -> tuple[str, list[ast.AST]] | None:
    """识别 op.<name>(...) 调用，返回 (name, args)。"""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"create_table", "add_column"}:
            # op.create_table / op.add_column
            return func.attr, node.args
    return None


def _column_name_from_col_call(call: ast.Call) -> str | None:
    """从 sa.Column(name, ...) 调用取列名（第一参字符串）。"""
    if not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr != "Column":
        return None
    if not call.args:
        return None
    return _str_const(call.args[0])


def _columns_in_create_table(args: list[ast.AST]) -> tuple[str | None, list[str]]:
    """create_table(table_name, sa.Column(...), ...) → (table_name, [col_names])。"""
    table_name = _str_const(args[0]) if args else None
    cols: list[str] = []
    for a in args[1:]:
        if isinstance(a, ast.Call):
            name = _column_name_from_col_call(a)
            if name:
                cols.append(name)
        # 列也可能以 sa.Column 形式出现在关键字 args 或嵌套，这里只扫顶层位置参
    return table_name, cols


def _add_column_target(args: list[ast.AST]) -> tuple[str | None, str | None]:
    """add_column(table_name, sa.Column(name, ...)) → (table_name, col_name)。"""
    table_name = _str_const(args[0]) if args else None
    col_name = None
    if len(args) >= 2 and isinstance(args[1], ast.Call):
        col_name = _column_name_from_col_call(args[1])
    return table_name, col_name


def audit() -> int:
    if not VERSIONS_DIR.is_dir():
        print(f"ERROR: versions dir not found: {VERSIONS_DIR}", file=sys.stderr)
        return 2

    files = sorted(VERSIONS_DIR.glob("*.py"))

    # 收集每个 revision 的 (revision, down_revision, creates:{table:set(col)}, adds:[(table,col)])
    revisions: list[dict] = []
    for f in files:
        mod = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        revision = None
        down_revision = None
        creates: dict[str, set[str]] = defaultdict(set)
        adds: list[tuple[str, str]] = []
        for node in ast.walk(mod):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        if tgt.id == "revision" and isinstance(node.value, ast.Constant):
                            revision = node.value.value
                        elif tgt.id == "down_revision":
                            if isinstance(node.value, ast.Constant):
                                down_revision = node.value.value
                            elif node.value is None or isinstance(node.value, ast.Constant):
                                down_revision = None
            call = _extract_call(node) if isinstance(node, ast.Call) else None
            if call:
                name, args = call
                if name == "create_table":
                    t, cols = _columns_in_create_table(args)
                    if t:
                        creates[t].update(cols)
                elif name == "add_column":
                    t, c = _add_column_target(args)
                    if t and c:
                        adds.append((t, c))
        revisions.append({
            "file": f.name,
            "revision": revision,
            "down_revision": down_revision,
            "creates": dict(creates),
            "adds": adds,
        })

    # 按链顺序排序：用 down_revision 拓扑
    by_down = {r["revision"]: r for r in revisions}
    rev_to_r = {r["revision"]: r for r in revisions}
    # 找根（down_revision 为 None）
    ordered: list[dict] = []
    roots = [r for r in revisions if r["down_revision"] is None]
    if len(roots) != 1:
        print(f"WARN: expected 1 root, found {len(roots)}: {[r['revision'] for r in roots]}", file=sys.stderr)
    visited: set[str] = set()
    # 简单线性跟随（链为单链）
    cur = roots[0] if roots else (min(revisions, key=lambda r: r["file"]))
    while cur is not None:
        ordered.append(cur)
        visited.add(cur["revision"])
        # 找 down_revision == cur.revision 的下一个
        nxt = next((r for r in revisions if r["down_revision"] == cur["revision"] and r["revision"] not in visited), None)
        cur = nxt
    # 容错：未排入的 append
    for r in revisions:
        if r["revision"] not in visited:
            ordered.append(r)

    print(f"== chain files: {len(files)}  ordered revisions: {len(ordered)} ==")
    print("ordered:", " -> ".join(r["revision"] for r in ordered))
    print()

    # 建表已含列的累积表：按链顺序累积 create_table 列，检测后续 add_column 是否重复
    # 累积口径：一个列一旦被某 create_table 创建，后续任何 add_column 同表同列都是重复
    created_cols: dict[str, set[str]] = defaultdict(set)
    duplicates: list[dict] = []
    for r in ordered:
        # 先处理本 revision 的 create_table（累积）
        for t, cols in r["creates"].items():
            created_cols[t].update(cols)
        # 再处理本 revision 的 add_column：若目标列已在 created_cols 中 → 重复候选
        for t, c in r["adds"]:
            if c in created_cols.get(t, set()):
                duplicates.append({
                    "revision": r["revision"],
                    "file": r["file"],
                    "table": t,
                    "column": c,
                    "note": "add_column 命中已由更早 create_table 创建的列 → 空库自举 DuplicateColumn",
                })

    print(f"== duplicate add_column (create-already-has) count: {len(duplicates)} ==")
    for d in duplicates:
        print(f"  [{d['revision']}] {d['file']}: table={d['table']} column={d['column']}")
        print(f"      -> {d['note']}")
    print()

    # 反向汇总：哪些表/列受影响
    if duplicates:
        print("== affected (table.column) ==")
        for d in duplicates:
            print(f"  {d['table']}.{d['column']}  (at revision {d['revision']})")
    else:
        print("== no create-vs-add duplicates detected by static scan (conservative) ==")

    return 0


if __name__ == "__main__":
    raise SystemExit(audit())
