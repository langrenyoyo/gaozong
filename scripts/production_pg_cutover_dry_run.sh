#!/bin/bash
# 生产 cutover dry-run（只读，不修改数据）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §9。
#
# 校验目标 database 名 + 输出表级 insert/update/skip/error 统计。
# 默认可在 production 执行（dry-run 不走 apply 安全门，不写数据）。
#
# 用法：
#   bash scripts/production_pg_cutover_dry_run.sh [--project-root DIR] [--service 9000|9100|both]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env"
SERVICE="${SERVICE:-both}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --help|-h) sed -n '2,11p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

SQLITE_9000="${SQLITE_9000_PATH:-docker-data/auto_wechat_9000/auto_wechat.db}"
SQLITE_9100="${SQLITE_9100_PATH:-docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db}"
DB_9000=$(echo "${DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
DB_9100=$(echo "${RAG_DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')

# 脱敏 URL（dry-run 输出可能含 URL）
mask_url() { echo "$1" | sed -E 's#://([^:/]+):[^@]+@#://\1:***@#'; }

run_dry_run() {
  local svc="$1" script="$2" sqlite="$3" url="$4" db="$5" target_var="$6"
  echo "==================== $svc cutover dry-run ===================="
  echo "[INFO] SQLite 源 : $sqlite"
  echo "[INFO] 目标 PG    : $(mask_url "$url")"
  echo "[INFO] 目标库名   : $db（$target_var 校验）"
  if [[ -z "$url" || -z "$db" ]]; then echo "[FAIL] $svc URL/库名为空" >&2; return 1; fi
  if [[ ! -f "$sqlite" ]]; then echo "[FAIL] $svc SQLite 源不存在：$sqlite" >&2; return 1; fi
  # dry-run 默认开启（脚本 --dry-run default True）；显式传库名供 apply 校验一致性
  if env "$target_var=$db" python "$script" --sqlite-db-path "$sqlite" --postgres-url "$url" 2>&1 | tee /tmp/dry_run_$svc.log; then
    if grep -q "DRY_RUN_PASS" /tmp/dry_run_$svc.log; then
      echo "[PASS] $svc dry-run 通过"
    else
      echo "[FAIL] $svc dry-run 未输出 DRY_RUN_PASS" >&2; return 1
    fi
  else
    echo "[FAIL] $svc dry-run 执行失败" >&2; return 1
  fi
  echo ""
}

case "$SERVICE" in
  9000) run_dry_run 9000 scripts/migrate_9000_sqlite_to_postgres_cutover.py "$SQLITE_9000" "$DATABASE_URL" "$DB_9000" MAIN_TARGET_DATABASE_NAME || exit 1;;
  9100) run_dry_run 9100 scripts/migrate_9100_sqlite_to_postgres_cutover.py "$SQLITE_9100" "$RAG_DATABASE_URL" "$DB_9100" RAG_TARGET_DATABASE_NAME || exit 1;;
  both)
    run_dry_run 9000 scripts/migrate_9000_sqlite_to_postgres_cutover.py "$SQLITE_9000" "$DATABASE_URL" "$DB_9000" MAIN_TARGET_DATABASE_NAME || exit 1
    run_dry_run 9100 scripts/migrate_9100_sqlite_to_postgres_cutover.py "$SQLITE_9100" "$RAG_DATABASE_URL" "$DB_9100" RAG_TARGET_DATABASE_NAME || exit 1
    ;;
  *) echo "[FAIL] --service 仅支持 9000/9100/both" >&2; exit 2;;
esac

echo "DRY_RUN_ALL_DONE"
