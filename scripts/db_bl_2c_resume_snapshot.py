"""DB-BL-2C-RESUME 只读 schema snapshot / diff helper。

用途：对 Expected@0030 / Expected@0034 / Legacy Actual 三个 PostgreSQL database，
      用【同一套】pg_catalog inspection 逻辑生成标准化 schema 快照（JSON），
      并对两份快照做精确 diff，输出分类差异矩阵。

治理约束（任务 §21 / §7）：
  - 默认无写能力：只执行 SELECT 系统目录查询。
  - legacy 连接强制 read-only：--readonly 时会话先 SET default_transaction_read_only=on。
  - 不含生产凭据：DSN 由调用方传入，密码走 PGPASSWORD 环境变量，不写入脚本/文件。
  - diff 可重复：快照所有键排序输出，diff 确定性。
  - normalization 规则可审计：见下方 _normalize_default 注释。

用法：
  # 1) 生成快照
  PGPASSWORD=xxx python scripts/db_bl_2c_resume_snapshot.py snapshot \
      --dsn "host=127.0.0.1 port=5433 dbname=db_bl_2c_resume_e0030 user=postgres" \
      --label expected_0030 --out snapshots/expected_0030.json

  # 2) 对比
  python scripts/db_bl_2c_resume_snapshot.py diff \
      --left snapshots/legacy_actual.json --right snapshots/expected_0030.json \
      --label "Matrix A: Legacy Actual vs Expected@0030"

说明：本脚本不连业务库写、不 stamp、不 upgrade、不改 schema，仅只读采集 + 文本 diff。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg

# ---- SQL：全部只读 SELECT，来源 pg_catalog ----

# 普通业务表（relkind='r'，public schema），排除 alembic_version 单独记录
SQL_TABLES = """
SELECT c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;
"""

# alembic_version 表状态（存在则取 version_num，否则 null）
SQL_ALEMBIC = """
SELECT EXISTS (
  SELECT 1 FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname='public' AND c.relname='alembic_version'
) AS has_table;
"""
SQL_ALEMBIC_VER = "SELECT version_num FROM public.alembic_version LIMIT 1;"

# 列：format_type 已是 PG canonical 类型；pg_get_expr 已是 normalized default
SQL_COLUMNS = """
SELECT
  c.relname AS table_name,
  a.attname AS column_name,
  a.attnum AS ordinal,
  format_type(a.atttypid, a.atttypmod) AS formatted_type,
  a.attnotnull AS not_null,
  pg_get_expr(d.adbin, d.adrelid) AS default_expr,
  a.attidentity AS identity,
  col_description(c.oid, a.attnum) AS comment
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;
"""

# 约束：pg_get_constraintdef(oid, true) 已是 pretty normalized 定义
SQL_CONSTRAINTS = """
SELECT
  c.conname AS constraint_name,
  rel.relname AS table_name,
  c.contype,
  pg_get_constraintdef(c.oid, true) AS definition,
  COALESCE(
    (SELECT array_agg(att.attname ORDER BY u.ord)
     FROM unnest(c.conkey) WITH ORDINALITY u(attnum, ord)
     JOIN pg_attribute att ON att.attrelid = c.conrelid AND att.attnum = u.attnum),
    ARRAY[]::text[]
  ) AS columns,
  fc.relname AS foreign_table,
  COALESCE(
    (SELECT array_agg(fatt.attname ORDER BY u.ord)
     FROM unnest(c.confkey) WITH ORDINALITY u(attnum, ord)
     JOIN pg_attribute fatt ON fatt.attrelid = c.confrelid AND fatt.attnum = u.attnum),
    ARRAY[]::text[]
  ) AS foreign_columns,
  c.confdeltype AS on_delete_code,
  c.confupdtype AS on_update_code
FROM pg_constraint c
JOIN pg_class rel ON rel.oid = c.conrelid
JOIN pg_namespace n ON n.oid = rel.relnamespace
LEFT JOIN pg_class fc ON fc.oid = c.confrelid
WHERE n.nspname = 'public' AND rel.relkind = 'r'
ORDER BY rel.relname, c.contype, c.conname;
"""

# 索引：pg_get_indexdef(oid,0,true) 已 normalized；区分是否 backing constraint 以免与 PK/unique 重复计
SQL_INDEXES = """
SELECT
  c.relname AS table_name,
  i.relname AS index_name,
  pg_get_indexdef(i.oid, 0, true) AS definition,
  x.indisunique AS is_unique,
  x.indisprimary AS is_primary,
  pg_get_expr(x.indpred, x.indrelid) AS predicate,
  am.amname AS method,
  COALESCE(con.conname, '') AS backing_constraint,
  COALESCE(
    (SELECT array_agg(att.attname ORDER BY u.ord)
     FROM unnest(x.indkey) WITH ORDINALITY u(attnum, ord)
     JOIN pg_attribute att ON att.attrelid = x.indrelid AND att.attnum = u.attnum
     WHERE u.attnum != 0),
    ARRAY[]::text[]
  ) AS columns
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class c ON c.oid = x.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_am am ON am.oid = i.relam
LEFT JOIN pg_constraint con ON con.conindid = i.oid
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname, i.relname;
"""


# ---- normalization 规则（可审计，见任务 §10）----

# nextval('seq'::regclass) → nextval(seq)：序列名与表绑定，仅当表名一致时序列名才一致；
# 此处归一为 nextval 占位以判断"是否为序列默认值"，但保留原值用于 name-only 比对。
_SEQ_RE = re.compile(r"^nextval\('([^']+)'::regclass\)$")

# now() 与 CURRENT_TIMESTAMP 语义等价（均取事务起始时间）
_NOW_FORMS = {"now()", "CURRENT_TIMESTAMP", "current_timestamp"}


def _normalize_default(raw: str | None) -> str:
    """归一化 column default 表达式（保守，不为消除 diff 而掩盖差异）。

    规则：
      - None / NULL → "<no_default>"
      - now() / CURRENT_TIMESTAMP → "<timestamp_now>"（语义等价，文本不同）
      - nextval('...'::regclass) → "<nextval>"（序列默认值；序列名差异归 NAME_ONLY）
      - 其余保留 pg_get_expr 原始输出（已含 PG canonical cast）
    """
    if raw is None:
        return "<no_default>"
    s = raw.strip()
    if s in _NOW_FORMS:
        return "<timestamp_now>"
    m = _SEQ_RE.match(s)
    if m:
        return "<nextval>"
    return s


_FK_DEL = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
_FK_UPD = _FK_DEL  # 同码表


def _snapshot(dsn: str, label: str, readonly: bool) -> dict:
    """连接 PG，只读采集 schema，返回标准化快照 dict。"""
    # autocommit=False，先设 read-only 会话守卫（仅 readonly=True 即 legacy）
    kwargs = {"autocommit": True}
    with psycopg.connect(dsn, **kwargs) as conn:
        if readonly:
            with conn.cursor() as cur:
                cur.execute("SET default_transaction_read_only = on;")
        cur = conn.cursor()

        snap: dict = {"db_label": label, "readonly_guard": readonly}

        # alembic_version 状态
        cur.execute(SQL_ALEMBIC)
        has_alembic = cur.fetchone()[0]
        if has_alembic:
            cur.execute(SQL_ALEMBIC_VER)
            row = cur.fetchone()
            snap["alembic_version"] = row[0] if row else None
        else:
            snap["alembic_version"] = None
        snap["has_alembic_version_table"] = bool(has_alembic)

        # current_database
        cur.execute("SELECT current_database();")
        snap["current_database"] = cur.fetchone()[0]

        # 业务表清单（排除 alembic_version）
        cur.execute(SQL_TABLES)
        tables = [r[0] for r in cur.fetchall() if r[0] != "alembic_version"]
        snap["tables"] = sorted(tables)

        # 列
        cur.execute(SQL_COLUMNS)
        columns = {}
        for table_name, column_name, ordinal, ftype, not_null, default_expr, identity, comment in cur.fetchall():
            columns[f"{table_name}.{column_name}"] = {
                "table": table_name,
                "column": column_name,
                "ordinal": ordinal,
                "type": ftype,                      # canonical format_type
                "not_null": not_null,
                "default_raw": default_expr,        # 原始 pg_get_expr
                "default_norm": _normalize_default(default_expr),
                "identity": identity or "",
                "comment": comment or "",
            }
        snap["columns"] = dict(sorted(columns.items()))

        # 约束
        cur.execute(SQL_CONSTRAINTS)
        pks, fks, uniques, checks = {}, {}, {}, {}
        for (cname, table, contype, definition, cols,
             ftable, fcols, on_del, on_upd) in cur.fetchall():
            entry = {
                "name": cname,
                "table": table,
                "definition": definition,
                "columns": list(cols),
            }
            if contype == "p":
                pks[table] = entry
            elif contype == "f":
                entry.update({
                    "foreign_table": ftable,
                    "foreign_columns": list(fcols),
                    "on_delete": _FK_DEL.get(on_del, str(on_del)),
                    "on_update": _FK_UPD.get(on_upd, str(on_upd)),
                })
                # FK 语义键：表+列+引用表+引用列（同名约束在不同库语义匹配）
                fks[f"{table}|{','.join(cols)}|{ftable}|{','.join(fcols)}"] = entry
            elif contype == "u":
                uniques[f"{table}|{','.join(cols)}"] = entry
            elif contype == "c":
                checks[f"{table}|{definition}"] = entry
        snap["primary_keys"] = dict(sorted(pks.items()))
        snap["foreign_keys"] = dict(sorted(fks.items()))
        snap["unique_constraints"] = dict(sorted(uniques.items()))
        snap["check_constraints"] = dict(sorted(checks.items()))

        # 索引（排除 backing constraint 的索引，避免与 PK/unique 重复计）
        cur.execute(SQL_INDEXES)
        indexes = {}
        for (table, iname, definition, is_unique, is_primary,
             predicate, method, backing, cols) in cur.fetchall():
            if backing:  # backing PK/unique → 已在约束维度覆盖
                continue
            key = f"{table}|{','.join(cols)}|{method}|{is_unique}|{predicate or ''}"
            indexes[key] = {
                "name": iname,
                "table": table,
                "definition": definition,
                "columns": list(cols),
                "is_unique": is_unique,
                "predicate": predicate or "",
                "method": method,
            }
        snap["indexes"] = dict(sorted(indexes.items()))

        # object counts（sanity check，不替代逐对象比较）
        snap["object_counts"] = {
            "tables": len(snap["tables"]),
            "columns": len(snap["columns"]),
            "primary_keys": len(snap["primary_keys"]),
            "foreign_keys": len(snap["foreign_keys"]),
            "unique_constraints": len(snap["unique_constraints"]),
            "check_constraints": len(snap["check_constraints"]),
            "indexes_standalone": len(snap["indexes"]),
        }

    return snap


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---- diff 分类：SEMANTIC_DIFF / NAME_ONLY_DIFF / NORMALIZATION_ONLY ----

def _diff_snapshots(left: dict, right: dict, label: str) -> dict:
    """对比两份快照，返回分类差异矩阵。left/right 语义：left vs right。"""
    sem, name_only, norm_only = [], [], []

    def add(bucket, category, item):
        item["category"] = category
        bucket.append(item)

    # ---- Tables ----
    lt, rt = set(left["tables"]), set(right["tables"])
    for t in sorted(lt - rt):
        add(sem, "missing_table", {"table": t, "side": "left_only"})
    for t in sorted(rt - lt):
        add(sem, "extra_table", {"table": t, "side": "right_only"})

    # ---- Columns（仅比较两库都有的表）----
    common_tables = lt & rt
    lc, rc = left["columns"], right["columns"]
    all_col_keys = sorted(set(lc) | set(rc))
    for k in all_col_keys:
        cl, cr = lc.get(k), rc.get(k)
        if cl and not cr:
            add(sem, "missing_column", {"column": k, "side": "left_only"})
        elif cr and not cl:
            add(sem, "extra_column", {"column": k, "side": "right_only"})
        elif cl and cr:
            # 仅当列所在表是公共表才比对（缺表侧的列已在表级覆盖）
            if cl["table"] not in common_tables or cr["table"] not in common_tables:
                continue
            if cl["type"] != cr["type"]:
                add(sem, "type_diff", {"column": k, "left": cl["type"], "right": cr["type"]})
            if cl["not_null"] != cr["not_null"]:
                add(sem, "nullable_diff", {"column": k, "left": cl["not_null"], "right": cr["not_null"]})
            if cl["identity"] != cr["identity"]:
                add(sem, "identity_diff", {"column": k, "left": cl["identity"], "right": cr["identity"]})
            if cl["comment"] != cr["comment"]:
                add(sem, "comment_diff", {"column": k, "left": cl["comment"], "right": cr["comment"]})
            # default：先看归一化（语义），再看原始（name-only / normalization-only）
            if cl["default_norm"] != cr["default_norm"]:
                add(sem, "default_diff", {"column": k, "left": cl["default_raw"], "right": cr["default_raw"]})
            elif cl["default_raw"] != cr["default_raw"]:
                # 归一相同但文本不同：序列名差异 → NAME_ONLY，now/CURRENT_TIMESTAMP → NORMALIZATION_ONLY
                if cl["default_norm"] == "<nextval>":
                    add(name_only, "default_seq_name_diff",
                        {"column": k, "left": cl["default_raw"], "right": cr["default_raw"]})
                elif cl["default_norm"] == "<timestamp_now>":
                    add(norm_only, "default_timestamp_form_diff",
                        {"column": k, "left": cl["default_raw"], "right": cr["default_raw"]})
                else:
                    add(norm_only, "default_text_diff",
                        {"column": k, "left": cl["default_raw"], "right": cr["default_raw"]})

    # ---- Primary Keys ----
    lpk, rpk = left["primary_keys"], right["primary_keys"]
    for t in sorted(set(lpk) | set(rpk)):
        pl, pr = lpk.get(t), rpk.get(t)
        if pl and not pr:
            add(sem, "missing_pk", {"table": t, "columns": pl["columns"]})
        elif pr and not pl:
            add(sem, "extra_pk", {"table": t, "columns": pr["columns"]})
        elif pl and pr and pl["columns"] != pr["columns"]:
            add(sem, "pk_diff", {"table": t, "left": pl["columns"], "right": pr["columns"]})

    # ---- Foreign Keys（按语义键匹配）----
    lfk, rfk = left["foreign_keys"], right["foreign_keys"]
    for k in sorted(set(lfk) | set(rfk)):
        fl, fr = lfk.get(k), rfk.get(k)
        if fl and not fr:
            add(sem, "missing_fk", {"key": k, "name": fl["name"]})
        elif fr and not fl:
            add(sem, "extra_fk", {"key": k, "name": fr["name"]})
        elif fl and fr:
            diffs = []
            if fl["on_delete"] != fr["on_delete"]:
                diffs.append({"field": "on_delete", "left": fl["on_delete"], "right": fr["on_delete"]})
            if fl["on_update"] != fr["on_update"]:
                diffs.append({"field": "on_update", "left": fl["on_update"], "right": fr["on_update"]})
            if diffs:
                add(sem, "fk_diff", {"key": k, "left_name": fl["name"], "right_name": fr["name"], "diffs": diffs})
            if fl["name"] != fr["name"]:
                add(name_only, "fk_name_diff", {"key": k, "left": fl["name"], "right": fr["name"]})

    # ---- Unique constraints（按语义键匹配）----
    luq, ruq = left["unique_constraints"], right["unique_constraints"]
    for k in sorted(set(luq) | set(ruq)):
        ul, ur = luq.get(k), ruq.get(k)
        if ul and not ur:
            add(sem, "missing_unique", {"key": k, "name": ul["name"]})
        elif ur and not ul:
            add(sem, "extra_unique", {"key": k, "name": ur["name"]})
        elif ul and ur and ul["name"] != ur["name"]:
            add(name_only, "unique_name_diff", {"key": k, "left": ul["name"], "right": ur["name"]})

    # ---- Check constraints（按 table+definition 匹配）----
    lck, rck = left["check_constraints"], right["check_constraints"]
    for k in sorted(set(lck) | set(rck)):
        cl_, cr_ = lck.get(k), rck.get(k)
        if cl_ and not cr_:
            add(sem, "missing_check", {"key": k, "name": cl_["name"]})
        elif cr_ and not cl_:
            add(sem, "extra_check", {"key": k, "name": cr_["name"]})
        elif cl_ and cr_ and cl_["name"] != cr_["name"]:
            add(name_only, "check_name_diff", {"key": k, "left": cl_["name"], "right": cr_["name"]})

    # ---- Indexes（按语义键匹配，排除 backing constraint）----
    lix, rix = left["indexes"], right["indexes"]
    for k in sorted(set(lix) | set(rix)):
        il, ir = lix.get(k), rix.get(k)
        if il and not ir:
            add(sem, "missing_index", {"key": k, "name": il["name"]})
        elif ir and not il:
            add(sem, "extra_index", {"key": k, "name": ir["name"]})
        elif il and ir:
            if il["definition"] != ir["definition"]:
                add(sem, "index_def_diff", {"key": k, "left": il["definition"], "right": ir["definition"]})
            if il["name"] != ir["name"]:
                add(name_only, "index_name_diff", {"key": k, "left": il["name"], "right": ir["name"]})

    return {
        "label": label,
        "left_label": left["db_label"],
        "right_label": right["db_label"],
        "semantic_diffs": sem,
        "name_only_diffs": name_only,
        "normalization_only_diffs": norm_only,
        "counts": {
            "semantic": len(sem),
            "name_only": len(name_only),
            "normalization_only": len(norm_only),
        },
    }


def cmd_snapshot(args) -> int:
    dsn = args.dsn
    snap = _snapshot(dsn, args.label, args.readonly)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = snap["object_counts"]
    print(f"[snapshot] label={args.label} db={snap['current_database']} "
          f"alembic={snap['alembic_version']} readonly_guard={snap['readonly_guard']}")
    print(f"  counts: {counts}")
    print(f"  written: {out}")
    return 0


def cmd_diff(args) -> int:
    left = _load(args.left)
    right = _load(args.right)
    matrix = _diff_snapshots(left, right, args.label)
    text = _format_matrix(matrix)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[diff] written: {out}")
    print(text)
    return 0


def _selfcheck() -> int:
    """无依赖自检：用两个手工 mini 快照验证 diff 分类逻辑（ponytail: 一处可运行 check）。"""
    base = {
        "db_label": "base", "tables": ["t1"], "alembic_version": None, "has_alembic_version_table": False,
        "columns": {"t1.a": {"table": "t1", "column": "a", "ordinal": 1, "type": "bigint",
                             "not_null": True, "default_raw": "nextval('t1_a_seq'::regclass)",
                             "default_norm": "<nextval>", "identity": "", "comment": ""}},
        "primary_keys": {"t1": {"name": "t1_pkey", "table": "t1", "definition": "", "columns": ["a"]}},
        "foreign_keys": {}, "unique_constraints": {}, "check_constraints": {}, "indexes": {},
        "object_counts": {},
    }
    other = json.loads(json.dumps(base))  # 深拷贝
    other["db_label"] = "other"
    # name-only：序列名不同但语义同
    other["columns"]["t1.a"]["default_raw"] = "nextval('t1_a_seq2'::regclass)"
    # semantic：缺表
    base2 = json.loads(json.dumps(base))
    base2["tables"] = ["t1", "t2"]  # left 多一张表 → missing_table(right side)
    m1 = _diff_snapshots(base, other, "selfcheck name-only")
    assert m1["counts"]["semantic"] == 0, m1
    assert m1["counts"]["name_only"] == 1, m1  # 序列名差异
    m2 = _diff_snapshots(base2, base, "selfcheck missing-table")
    assert m2["counts"]["semantic"] == 1, m2  # 缺表
    assert any(d["category"] == "missing_table" for d in m2["semantic_diffs"]), m2
    print("[selfcheck] PASS — diff 分类逻辑正确（name-only / semantic 各按预期）")
    return 0


def _format_matrix(m: dict) -> str:
    lines = []
    lines.append(f"=== {m['label']} ===")
    lines.append(f"left  = {m['left_label']}")
    lines.append(f"right = {m['right_label']}")
    lines.append(f"counts: semantic={m['counts']['semantic']} "
                 f"name_only={m['counts']['name_only']} "
                 f"normalization_only={m['counts']['normalization_only']}")
    lines.append("")
    lines.append(f"--- SEMANTIC_DIFF ({len(m['semantic_diffs'])}) ---")
    for d in m["semantic_diffs"]:
        lines.append(f"  [{d['category']}] " + " ".join(f"{k}={v}" for k, v in d.items() if k != "category"))
    lines.append("")
    lines.append(f"--- NAME_ONLY_DIFF ({len(m['name_only_diffs'])}) ---")
    for d in m["name_only_diffs"]:
        lines.append(f"  [{d['category']}] " + " ".join(f"{k}={v}" for k, v in d.items() if k != "category"))
    lines.append("")
    lines.append(f"--- NORMALIZATION_ONLY ({len(m['normalization_only_diffs'])}) ---")
    for d in m["normalization_only_diffs"]:
        lines.append(f"  [{d['category']}] " + " ".join(f"{k}={v}" for k, v in d.items() if k != "category"))
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="DB-BL-2C-RESUME 只读 schema snapshot/diff helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("snapshot", help="生成只读 schema 快照 JSON")
    ps.add_argument("--dsn", required=True, help="PostgreSQL DSN（不含密码，密码走 PGPASSWORD）")
    ps.add_argument("--label", required=True)
    ps.add_argument("--out", required=True)
    ps.add_argument("--readonly", action="store_true", help="legacy 连接：会话强制 read-only")
    ps.set_defaults(func=cmd_snapshot)

    pd = sub.add_parser("diff", help="对比两份快照，输出分类差异矩阵")
    pd.add_argument("--left", required=True)
    pd.add_argument("--right", required=True)
    pd.add_argument("--label", required=True)
    pd.add_argument("--out")
    pd.set_defaults(func=cmd_diff)

    pc = sub.add_parser("selfcheck", help="无依赖自检 diff 分类逻辑")
    pc.set_defaults(func=lambda a: _selfcheck())

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
