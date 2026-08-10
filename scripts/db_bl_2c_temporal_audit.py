"""DB-BL-2C 只读全链 temporal drift 审计（Q3 / Q7 工具）。

仅 AST 解析 migration 源文件的 upgrade() 函数体，不连接任何数据库，不修改任何文件。
比 db_bl_2c_chain_audit.py（仅 create-vs-add column）更宽：覆盖
  column / index / unique / FK / CHECK / alter / drop / 二次 create_table
但仍是保守静态下界——不解析 op.execute 原生 SQL（本链 op.execute 仅 UPDATE/DELETE，无 DDL，已核验）。

判定规则（空库自举视角，按链顺序累积 schema 状态）：
  - add_column 命中已存在列            → DuplicateColumn（CONFIRMED，runtime 必失败）
  - create_index 复用已存在 index 名   → DuplicateIndex（CONFIRMED）
  - create_index 同表同列序但不同名     → POTENTIAL（语义重复，名不同不致命但可疑）
  - create_unique_constraint 复用名 / 同表同列序 → CONFIRMED / POTENTIAL
  - create_foreign_key 复用名          → CONFIRMED
  - create_check_constraint 复用名    → CONFIRMED
  - create_table 二次建已存在表        → DuplicateTable（CONFIRMED）
  - drop_* 不存在对象 / alter_column 不存在列 → POTENTIAL（upgrade 路径下可能有意）

只检测 upgrade()：downgrade() 的 drop 不影响正向自举。
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "postgres" / "auto_wechat" / "versions"


def _str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _str_list(node: ast.AST) -> list[str]:
    """从 ast.List/Tuple of str 取字符串列表；含非字面量时该元素记 <expr>。"""
    out: list[str] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for el in node.elts:
            s = _str(el)
            out.append(s if s is not None else "<expr>")
    return out


def _kw(node: ast.Call, name: str) -> ast.AST | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _pos(node: ast.Call, i: int) -> ast.AST | None:
    return node.args[i] if len(node.args) > i else None


def _col_name_from_sa_column(call: ast.Call) -> str | None:
    """sa.Column(name, type, ...) 第一参字符串；也兼容 sa.Column(sa.String, ...) 无名形态。"""
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "Column":
        return None
    if not call.args:
        return None
    name = _str(call.args[0])
    if name:
        return name
    return None  # 无名字面量（类型首位）不纳入审计


def _inline_cols_and_constraints(create_table_args: list[ast.AST]) -> tuple[list[str], list[dict]]:
    """create_table 的位置参里 sa.Column 取列名；sa.UniqueConstraint/CheckConstraint/FK 取约束。"""
    cols: list[str] = []
    constraints: list[dict] = []
    for a in create_table_args[1:]:
        if not isinstance(a, ast.Call) or not isinstance(a.func, ast.Attribute):
            continue
        attr = a.func.attr
        if attr == "Column":
            n = _col_name_from_sa_column(a)
            if n:
                cols.append(n)
        elif attr == "UniqueConstraint":
            # sa.UniqueConstraint("c1","c2", name="uk_..") 或无 name
            ccols = [c for c in (_str(x) for x in a.args) if c]
            name = _str(_kw(a, "name")) if _kw(a, "name") else None
            # name 也可能作为关键字
            constraints.append({"kind": "unique", "name": name, "cols": ccols})
        elif attr == "CheckConstraint":
            cond = _str(a.args[0]) if a.args else None
            name = _str(_kw(a, "name")) if _kw(a, "name") else None
            constraints.append({"kind": "check", "name": name, "cond": cond})
        elif attr == "ForeignKeyConstraint":
            local = _str_list(a.args[0]) if a.args else []
            name = _str(_kw(a, "name")) if _kw(a, "name") else None
            constraints.append({"kind": "fk", "name": name, "cols": local})
    return cols, constraints


def _upgrade_body(mod: ast.Module) -> list[ast.AST]:
    """取 upgrade() 函数体语句；缺失则返回空。"""
    for node in mod.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return list(ast.walk(node))
    return []


def _extract_calls(nodes) -> list[ast.Call]:
    calls = []
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.append(node)
    return calls


def parse_migration(path: Path) -> dict:
    mod = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision = down_revision = None
    for node in mod.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant):
                    if t.id == "revision":
                        revision = node.value.value
                    elif t.id == "down_revision":
                        down_revision = node.value.value if isinstance(node.value, ast.Constant) else None
    body = _upgrade_body(mod)
    calls = _extract_calls(body)
    ops: list[dict] = []
    for c in calls:
        attr = c.func.attr
        if attr == "create_table":
            tname = _str(_pos(c, 0)) if _pos(c, 0) else None
            cols, cons = _inline_cols_and_constraints(c.args) if tname else ([], [])
            ops.append({"op": "create_table", "table": tname, "cols": cols, "constraints": cons})
        elif attr == "add_column":
            tname = _str(_pos(c, 0)) if _pos(c, 0) else None
            col = _col_name_from_sa_column(c.args[1]) if len(c.args) > 1 and isinstance(c.args[1], ast.Call) else None
            ops.append({"op": "add_column", "table": tname, "col": col})
        elif attr == "create_index":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_pos(c, 1)) if _pos(c, 1) else None
            cols = _str_list(_pos(c, 2)) if _pos(c, 2) else []
            ops.append({"op": "create_index", "name": name, "table": tname, "cols": cols})
        elif attr == "create_unique_constraint":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_pos(c, 1)) if _pos(c, 1) else None
            cols = _str_list(_pos(c, 2)) if _pos(c, 2) else []
            ops.append({"op": "create_unique_constraint", "name": name, "table": tname, "cols": cols})
        elif attr == "create_foreign_key":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_pos(c, 1)) if _pos(c, 1) else None
            ref = _str(_pos(c, 2)) if _pos(c, 2) else None
            ops.append({"op": "create_foreign_key", "name": name, "table": tname, "ref": ref})
        elif attr == "create_check_constraint":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_pos(c, 1)) if _pos(c, 1) else None
            cond = _str(_pos(c, 2)) if _pos(c, 2) else None
            ops.append({"op": "create_check_constraint", "name": name, "table": tname, "cond": cond})
        elif attr == "alter_column":
            tname = _str(_pos(c, 0)) if _pos(c, 0) else None
            col = _str(_pos(c, 1)) if _pos(c, 1) else None
            ops.append({"op": "alter_column", "table": tname, "col": col})
        elif attr == "drop_column":
            tname = _str(_pos(c, 0)) if _pos(c, 0) else None
            col = _str(_pos(c, 1)) if _pos(c, 1) else None
            ops.append({"op": "drop_column", "table": tname, "col": col})
        elif attr == "drop_index":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_kw(c, "table_name")) if _kw(c, "table_name") else None
            ops.append({"op": "drop_index", "name": name, "table": tname})
        elif attr == "drop_constraint":
            name = _str(_pos(c, 0)) if _pos(c, 0) else None
            tname = _str(_pos(c, 1)) if _pos(c, 1) else None
            ops.append({"op": "drop_constraint", "name": name, "table": tname})
        elif attr == "drop_table":
            tname = _str(_pos(c, 0)) if _pos(c, 0) else None
            ops.append({"op": "drop_table", "table": tname})
    return {"file": path.name, "revision": revision, "down_revision": down_revision, "ops": ops}


def order_chain(revs: list[dict]) -> list[dict]:
    by_down = {r["revision"]: r for r in revs}
    roots = [r for r in revs if r["down_revision"] is None]
    ordered: list[dict] = []
    visited: set[str] = set()
    cur = roots[0] if roots else (min(revs, key=lambda r: r["file"]))
    while cur is not None:
        ordered.append(cur)
        visited.add(cur["revision"])
        nxt = next((r for r in revs if r["down_revision"] == cur["revision"] and r["revision"] not in visited), None)
        cur = nxt
    for r in revs:
        if r["revision"] not in visited:
            ordered.append(r)
    return ordered


def audit() -> int:
    if not VERSIONS_DIR.is_dir():
        print(f"ERROR: versions dir not found: {VERSIONS_DIR}", file=sys.stderr)
        return 2
    files = sorted(VERSIONS_DIR.glob("*.py"))
    revs = [parse_migration(f) for f in files]
    ordered = order_chain(revs)

    print(f"== temporal audit: {len(ordered)} revisions, {sum(len(r['ops']) for r in ordered)} upgrade ops ==")
    print("chain:", " -> ".join(r["revision"] for r in ordered))
    print()

    # 累积 schema 状态
    tables: set[str] = set()
    table_cols: dict[str, set[str]] = defaultdict(set)
    index_names: dict[str, str] = {}                 # name -> revision(引入)
    index_by_table_cols: dict[str, dict[tuple, str]] = defaultdict(dict)  # table -> (cols) -> name
    uq_names: dict[str, str] = {}                    # unique constraint name -> revision
    uq_by_table_cols: dict[str, dict[tuple, str]] = defaultdict(dict)
    fk_names: dict[str, str] = {}
    check_names: dict[str, str] = {}

    conflicts: list[dict] = []
    potentials: list[dict] = []

    def conflict(kind, rev, file, detail):
        conflicts.append({"kind": kind, "revision": rev, "file": file, "detail": detail})
    def potential(kind, rev, file, detail):
        potentials.append({"kind": kind, "revision": rev, "file": file, "detail": detail})

    for r in ordered:
        rev, file = r["revision"], r["file"]
        for o in r["ops"]:
            op = o["op"]
            if op == "create_table":
                t = o["table"]
                if t and t in tables:
                    conflict("DuplicateTable", rev, file, f"table={t} 已由更早 revision 创建")
                if t:
                    tables.add(t)
                for col in o["cols"]:
                    table_cols[o["table"]].add(col)
                for con in o["constraints"]:
                    if con["kind"] == "unique" and con["name"]:
                        if con["name"] in uq_names:
                            conflict("DuplicateUniqueName", rev, file, f"unique {con['name']} 已存在于 {uq_names[con['name']]}")
                        uq_names[con["name"]] = rev
                    elif con["kind"] == "check" and con["name"]:
                        if con["name"] in check_names:
                            conflict("DuplicateCheckName", rev, file, f"check {con['name']} 已存在于 {check_names[con['name']]}")
                        check_names[con["name"]] = rev
                    elif con["kind"] == "fk" and con["name"]:
                        if con["name"] in fk_names:
                            conflict("DuplicateFKName", rev, file, f"fk {con['name']} 已存在于 {fk_names[con['name']]}")
                        fk_names[con["name"]] = rev
            elif op == "add_column":
                t, c = o["table"], o["col"]
                if t and c and c in table_cols.get(t, set()):
                    conflict("DuplicateColumn", rev, file, f"table={t} column={c} 已由更早 create_table 创建")
                if t and c:
                    table_cols[t].add(c)
            elif op == "create_index":
                name, t, cols = o["name"], o["table"], o["cols"]
                if name and name in index_names:
                    conflict("DuplicateIndexName", rev, file, f"index {name} 已存在于 {index_names[name]}")
                if name:
                    index_names[name] = rev
                if t and cols and "<expr>" not in cols:
                    key = tuple(cols)
                    if key in index_by_table_cols.get(t, {}):
                        existing = index_by_table_cols[t][key]
                        if existing != name:
                            potential("DuplicateIndexSemantics", rev, file, f"table={t} cols={cols} 新名={name} 旧名={existing}")
                    else:
                        index_by_table_cols[t][key] = name
            elif op == "create_unique_constraint":
                name, t, cols = o["name"], o["table"], o["cols"]
                if name and name in uq_names:
                    conflict("DuplicateUniqueName", rev, file, f"unique {name} 已存在于 {uq_names[name]}")
                if name:
                    uq_names[name] = rev
                if t and cols and "<expr>" not in cols:
                    key = tuple(cols)
                    if key in uq_by_table_cols.get(t, {}):
                        existing = uq_by_table_cols[t][key]
                        if existing != name:
                            potential("DuplicateUniqueSemantics", rev, file, f"table={t} cols={cols} 新名={name} 旧名={existing}")
                    else:
                        uq_by_table_cols[t][key] = name
            elif op == "create_foreign_key":
                name = o["name"]
                if name and name in fk_names:
                    conflict("DuplicateFKName", rev, file, f"fk {name} 已存在于 {fk_names[name]}")
                if name:
                    fk_names[name] = rev
            elif op == "create_check_constraint":
                name = o["name"]
                if name and name in check_names:
                    conflict("DuplicateCheckName", rev, file, f"check {name} 已存在于 {check_names[name]}")
                if name:
                    check_names[name] = rev
            elif op == "drop_column":
                t, c = o["table"], o["col"]
                if t and c and c not in table_cols.get(t, set()):
                    potential("DropMissingColumn", rev, file, f"table={t} column={c} 不存在（可能 upgrade 有意清理）")
                if t and c:
                    table_cols[t].discard(c)
            elif op == "drop_index":
                name = o["name"]
                if name and name in index_names:
                    del index_names[name]
                else:
                    potential("DropMissingIndex", rev, file, f"index {name} 不存在")
            elif op == "drop_constraint":
                name = o["name"]
                removed = False
                for store in (uq_names, fk_names, check_names):
                    if name in store:
                        del store[name]
                        removed = True
                        break
                if not removed:
                    potential("DropMissingConstraint", rev, file, f"constraint {name} 不存在")
            elif op == "drop_table":
                t = o["table"]
                if t and t not in tables:
                    potential("DropMissingTable", rev, file, f"table={t} 不存在")
                if t:
                    tables.discard(t)
                    table_cols.pop(t, None)
            elif op == "alter_column":
                t, c = o["table"], o["col"]
                if t and c and c not in table_cols.get(t, set()):
                    potential("AlterMissingColumn", rev, file, f"table={t} column={c} 不存在")

    print(f"== CONFIRMED temporal conflicts: {len(conflicts)} ==")
    for c in conflicts:
        print(f"  [{c['revision']}] {c['file']}: {c['kind']} — {c['detail']}")
    print()
    print(f"== POTENTIAL conflicts: {len(potentials)} ==")
    for p in potentials:
        print(f"  [{p['revision']}] {p['file']}: {p['kind']} — {p['detail']}")
    print()
    print(f"== summary ==")
    print(f"  tables={len(tables)}  total_cols={sum(len(v) for v in table_cols.values())}  indexes={len(index_names)}  uniques={len(uq_names)}  fks={len(fk_names)}  checks={len(check_names)}")
    print(f"  confirmed={len(conflicts)}  potential={len(potentials)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(audit())
