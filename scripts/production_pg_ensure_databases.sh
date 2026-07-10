#!/bin/bash
# 生产第二 database 检查与创建（默认只读，显式 --create 才创建）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §7。
#
# 已有 production volume 时 init-prod/010 不会自动重跑，必须用本脚本显式确认/创建第二库。
# 显式使用 POSTGRES_USER，不依赖 OS postgres；库已存在不重建、不清空；不打印密码。
#
# 用法：
#   bash scripts/production_pg_ensure_databases.sh                  # 只读检查
#   bash scripts/production_pg_ensure_databases.sh --create         # 创建缺失的第二库
#   bash scripts/production_pg_ensure_databases.sh --create --yes   # 确认创建
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env.production.local"
CREATE=0; YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --create) CREATE=1; shift;;
    --yes) YES=1; shift;;
    --help|-h) sed -n '2,13p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

if [[ $CREATE -eq 1 && $YES -ne 1 ]]; then
  echo "[FAIL] --create 必须同时传 --yes（避免误创建）" >&2
  exit 2
fi

COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
PG_CONTAINER="${PG_CONTAINER:-postgres}"
PG_USER_VAL="${PG_USER:-auto_wechat}"

# 显式 -U PG_USER，不依赖 OS postgres（init-prod/010 同款修复）
psql_exec() {
  if [[ -n "$COMPOSE_CMD" ]] && $COMPOSE_CMD ps -q "$PG_CONTAINER" >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T "$PG_CONTAINER" psql -U "$PG_USER_VAL" -d postgres -tAc "$1" 2>/dev/null
  else
    PGPASSWORD="${PG_PASSWORD:-}" psql -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "$PG_USER_VAL" -d postgres -tAc "$1" 2>/dev/null
  fi
}
createdb_exec() {
  if [[ -n "$COMPOSE_CMD" ]] && $COMPOSE_CMD ps -q "$PG_CONTAINER" >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T "$PG_CONTAINER" createdb -U "$PG_USER_VAL" --owner "$PG_USER_VAL" "$1"
  else
    PGPASSWORD="${PG_PASSWORD:-}" createdb -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "$PG_USER_VAL" --owner "$PG_USER_VAL" "$1"
  fi
}

DB_9000=$(echo "${DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
DB_9100=$(echo "${RAG_DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
# 默认 9100 第二库名（与 init-prod/010 一致）
[[ -z "$DB_9100" ]] && DB_9100="xg_douyin_ai_cs"

echo "==================== 第二 database 检查 ===================="
echo "PG_USER（显式，不依赖 OS postgres）: $PG_USER_VAL"
echo "9000 database: ${DB_9000:-(未配 DATABASE_URL)}"
echo "9100 database: $DB_9100"
echo "模式: $([[ $CREATE -eq 1 ]] && echo 'CREATE（缺失则创建）' || echo 'READ-ONLY 检查')"
echo ""

# PG 连通性
if ! psql_exec "SELECT 1" >/dev/null 2>&1; then
  echo "[FAIL] PostgreSQL 不可连接" >&2
  exit 1
fi

check_or_create() {
  local db="$1" must_exist="$2"
  local exists owner
  exists=$(psql_exec "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "")
  if [[ "$exists" == "1" ]]; then
    owner=$(psql_exec "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "?")
    echo "[PASS] database '$db' 已存在（owner=$owner）—— 不重建、不清空"
    if [[ "$owner" != "$PG_USER_VAL" ]]; then
      echo "[WARN] owner=$owner 与 POSTGRES_USER=$PG_USER_VAL 不同（现场确认是否符合预期）"
    fi
    return 0
  fi
  echo "[INFO] database '$db' 不存在"
  if [[ $CREATE -eq 0 ]]; then
    if [[ "$must_exist" == "1" ]]; then
      echo "[FAIL] '$db' 缺失且未传 --create（切换前必须存在）" >&2
      return 1
    fi
    echo "[INFO] '$db' 缺失（只读模式，如需创建请加 --create --yes）"
    return 0
  fi
  # CREATE 模式
  echo "[INFO] 创建 database '$db'（owner=$PG_USER_VAL）..."
  if createdb_exec "$db"; then
    local new_owner
    new_owner=$(psql_exec "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "?")
    echo "[OK]   '$db' 创建成功（owner=$new_owner）"
    # 连接权限校验
    if psql_exec "SELECT 1" >/dev/null 2>&1; then
      echo "[PASS] $PG_USER_VAL 可连接 postgres（连接权限正常）"
    fi
  else
    echo "[FAIL] '$db' 创建失败" >&2
    return 1
  fi
}

# 9000 主库（POSTGRES_DB 自动建，通常存在；缺失则失败/创建）
check_or_create "$DB_9000" 1 || exit 1
# 9100 第二库（init-prod/010 首次建；已有 volume 可能缺失，--create 补建）
check_or_create "$DB_9100" 0 || exit 1

echo ""
echo "ENSURE_DATABASES_DONE"
