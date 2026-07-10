#!/bin/bash
# 生产 PostgreSQL 切换后 SQLite 冻结校验（元数据不得增长，向量副本允许）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §12。
#
# 两个模式：
#   --snapshot OUT.json   切换前/后各跑一次，记录 SQLite 大小/mtime/关键表行数
#   --compare BEFORE.json AFTER.json  对比：元数据 SQLite 不得增长，向量副本允许增长
#
# 冻结规则（metadata SQLite）：
#   - 9000 SQLite（docker-data/auto_wechat_9000/auto_wechat.db）：切换后冻结，不得增长
#   - 9100 metadata SQLite（docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db）：冻结
#   - 向量副本（RAG_VECTOR_BACKEND=sqlite 时）：允许增长（WARN 不 FAIL）
#
# 用法：
#   bash scripts/production_pg_sqlite_freeze_check.sh --snapshot /tmp/freeze_before.json
#   bash scripts/production_pg_sqlite_freeze_check.sh --compare /tmp/freeze_before.json /tmp/freeze_after.json
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
MODE=""
SNAP_OUT=""
CMP_BEFORE=""; CMP_AFTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --snapshot) MODE="snapshot"; SNAP_OUT="$2"; shift 2;;
    --compare) MODE="compare"; CMP_BEFORE="$2"; CMP_AFTER="$3"; shift 3;;
    --help|-h) sed -n '2,21p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

SQLITE_9000="${SQLITE_9000_PATH:-docker-data/auto_wechat_9000/auto_wechat.db}"
SQLITE_9100="${SQLITE_9100_PATH:-docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db}"
VECTOR_SQLITE="${VECTOR_SQLITE_PATH:-}"

# 用 python 读 sqlite（主机/容器通用，避免依赖 sqlite3 CLI）
# 参数：db_path table1,table2,...
sqlite_info_json() {
  python - "$1" "$2" <<'PYEOF'
import json, os, sys, sqlite3
db_path, tables_arg = sys.argv[1], sys.argv[2]
tables = [t.strip() for t in tables_arg.split(",") if t.strip()]
info = {"path": db_path, "exists": os.path.exists(db_path)}
if info["exists"]:
    st = os.stat(db_path)
    info["size"] = st.st_size
    info["mtime"] = int(st.st_mtime)
    counts = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                counts[t] = cur.fetchone()[0]
            except Exception as e:
                counts[t] = f"ERR:{type(e).__name__}"
        conn.close()
    except Exception as e:
        counts["_open_error"] = f"{type(e).__name__}: {e}"
    info["tables"] = counts
else:
    info["size"] = 0
    info["mtime"] = 0
    info["tables"] = {}
print(json.dumps(info))
PYEOF
}

# 向量副本只记 size/mtime（允许增长，不读表结构——表名不固定）
vector_info_json() {
  python - "$1" <<'PYEOF'
import json, os, sys
p = sys.argv[1]
info = {"path": p, "exists": bool(p) and os.path.exists(p)}
if info["exists"]:
    st = os.stat(p)
    info["size"] = st.st_size
    info["mtime"] = int(st.st_mtime)
else:
    info["size"] = 0; info["mtime"] = 0
print(json.dumps(info))
PYEOF
}

# 关键表清单
CRIT_9000="leads,staff,douyin_webhook_events,wechat_tasks,reply_checks"
CRIT_9100="documents,chunks,feedback,training_run"

if [[ "$MODE" == "snapshot" ]]; then
  [[ -n "$SNAP_OUT" ]] || { echo "[FAIL] --snapshot 需要输出文件参数" >&2; exit 2; }
  echo "==================== SQLite 快照 ===================="
  S9000=$(sqlite_info_json "$SQLITE_9000" "$CRIT_9000")
  S9100=$(sqlite_info_json "$SQLITE_9100" "$CRIT_9100")
  SVEC=$(vector_info_json "$VECTOR_SQLITE")
  python - "$SNAP_OUT" "$S9000" "$S9100" "$SVEC" <<'PYEOF'
import json, sys, datetime
out, s9000, s9100, svec = sys.argv[1:5]
snap = {
  "timestamp": datetime.datetime.now().isoformat(),
  "git": __import__("subprocess").run(
    ["git","rev-parse","--short=12","HEAD"],
    capture_output=True, text=True).stdout.strip(),
  "sqlite_9000": json.loads(s9000),
  "sqlite_9100_metadata": json.loads(s9100),
  "vector_sqlite": json.loads(svec),
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(snap, f, indent=2, ensure_ascii=False)
print(f"[OK] 快照已写入：{out}")
print(json.dumps(snap, indent=2, ensure_ascii=False))
PYEOF
  exit 0

elif [[ "$MODE" == "compare" ]]; then
  [[ -n "$CMP_BEFORE" && -n "$CMP_AFTER" ]] || { echo "[FAIL] --compare 需要 BEFORE AFTER 两文件" >&2; exit 2; }
  [[ -f "$CMP_BEFORE" ]] || { echo "[FAIL] before 文件不存在：$CMP_BEFORE" >&2; exit 1; }
  [[ -f "$CMP_AFTER"  ]] || { echo "[FAIL] after 文件不存在：$CMP_AFTER"  >&2; exit 1; }

  python - "$CMP_BEFORE" "$CMP_AFTER" <<'PYEOF'
import json, sys
before = json.load(open(sys.argv[1], encoding="utf-8"))
after  = json.load(open(sys.argv[2], encoding="utf-8"))
fail = 0; warn = 0; checks = 0

def fmt_delta(b, a):
    d = a - b
    sign = "+" if d >= 0 else ""
    return f"{b} → {a} ({sign}{d})"

print("==================== SQLite 冻结对比 ====================")
# 元数据 SQLite（9000 + 9100）：不得增长
for key, label in [("sqlite_9000","9000-metadata"), ("sqlite_9100_metadata","9100-metadata")]:
    b = before.get(key, {}); a = after.get(key, {})
    if not b.get("exists") or not a.get("exists"):
        print(f"[WARN] {label} 快照缺失（before.exists={b.get('exists')} after.exists={a.get('exists')}）")
        warn += 1; checks += 1; continue
    # size 不得增长（允许等号——无写入）
    bs, az = b["size"], a["size"]
    checks += 1
    if az > bs:
        print(f"[FAIL] {label} size 增长：{fmt_delta(bs, az)}（元数据 SQLite 切换后应冻结）")
        fail += 1
    else:
        print(f"[PASS] {label} size 冻结：{fmt_delta(bs, az)}")
    # 关键表行数不得增长
    bt = b.get("tables", {}); at = a.get("tables", {})
    for tbl in bt:
        if tbl.startswith("_"): continue
        bv = bt[tbl]; av = at.get(tbl, "?")
        checks += 1
        if isinstance(bv, int) and isinstance(av, int):
            if av > bv:
                print(f"  [FAIL] {label}.{tbl} 行数增长：{fmt_delta(bv, av)}")
                fail += 1
            else:
                print(f"  [PASS] {label}.{tbl} 行数冻结：{fmt_delta(bv, av)}")
        else:
            print(f"  [WARN] {label}.{tbl} 无法对比（before={bv} after={av}）")
            warn += 1

# 向量副本：允许增长（WARN 不 FAIL）
bv = before.get("vector_sqlite", {}); av = after.get("vector_sqlite", {})
if bv.get("exists") and av.get("exists"):
    bs, az = bv["size"], av["size"]
    checks += 1
    if az > bs:
        print(f"[INFO] vector-sqlite size 增长：{fmt_delta(bs, az)}（允许，向量副本可写入）")
    else:
        print(f"[PASS] vector-sqlite size 未增长：{fmt_delta(bs, az)}")
elif not bv.get("path"):
    print(f"[INFO] vector-sqlite 未配置路径（跳过）")

print("")
print(f"==================== 冻结校验汇总 ====================")
print(f"checks={checks}  PASS={checks-fail-warn}  WARN={warn}  FAIL={fail}")
if fail > 0:
    print("[FAIL] 元数据 SQLite 在切换后增长——存在未切净的写入路径或回滚未完成" )
    sys.exit(1)
print("FREEZE_CHECK_DONE（元数据冻结，向量副本可增长）")
PYEOF
  exit 0

else
  echo "[FAIL] 必须指定 --snapshot 或 --compare" >&2
  sed -n '2,21p' "$0" >&2
  exit 2
fi
