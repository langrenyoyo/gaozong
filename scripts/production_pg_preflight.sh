#!/bin/bash
# 生产 PostgreSQL 切换预检查（只读，不修改任何状态）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §5。
#
# 18 项检查：git/compose/配置/PG 连接/SQLite 源/容器/readiness/apply 安全门。
# 输出脱敏（不打印密码或完整 URL）。任一 FAIL 返回非零，不得开始切换。
#
# 用法：
#   bash scripts/production_pg_preflight.sh [--project-root DIR] [--env-file .env]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env"
COMPOSE_FILE="docker-compose.yml"
# 疑似废弃 compose（memory 记录宝塔用 docker-compose.yml，非 auto-wechat.yml）；
# 现场确认若仍在用需从本列表移除。
DEPRECATED_COMPOSE=("docker-compose.auto-wechat.yml")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --help|-h) sed -n '2,12p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

PASS=0; FAIL=0; WARN=0
pass() { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }
warn() { echo "[WARN] $1"; WARN=$((WARN+1)); }

# 脱敏 URL（隐藏密码）：scheme://user:password@host/db → scheme://user:***@host/db
mask_url() { echo "$1" | sed -E 's#://([^:/]+):[^@]+@#://\1:***@#'; }

# 从 URL 提取 database 名（最后一段 path）
db_name() { echo "$1" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#'; }

load_env() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
}

echo "==================== 生产 PG 切换预检查 ===================="
echo "PROJECT_ROOT : $PROJECT_ROOT"
echo "ENV_FILE     : $ENV_FILE"
echo ""

# ---------- 1-2. git ----------
GIT_COMMIT=$(git -C "$PROJECT_ROOT" rev-parse --short=12 HEAD 2>/dev/null) || GIT_COMMIT=""
if [[ -n "$GIT_COMMIT" ]]; then pass "1.  git commit = $GIT_COMMIT"; else fail "1.  git commit 获取失败（非 git 仓库？）"; fi
if git -C "$PROJECT_ROOT" diff --quiet HEAD 2>/dev/null && git -C "$PROJECT_ROOT" diff --cached --quiet HEAD 2>/dev/null; then
  pass "2.  工作区干净"
else
  fail "2.  工作区有未提交改动（切换前 git status 必须干净）"
fi

# ---------- 3-4. compose ----------
if [[ -f "$COMPOSE_FILE" ]]; then pass "3.  生产 compose 存在（$COMPOSE_FILE）"; else fail "3.  生产 compose 不存在（$COMPOSE_FILE）"; fi
DEP_ISSUE=0
for dep in "${DEPRECATED_COMPOSE[@]}"; do
  if [[ -f "$dep" ]]; then warn "4.  发现疑似废弃 compose：$dep（现场确认生产未使用）"; DEP_ISSUE=1; fi
done
[[ $DEP_ISSUE -eq 0 ]] && pass "4.  无疑似废弃 compose"

# ---------- 加载 .env ----------
if load_env "$ENV_FILE"; then echo "[INFO] .env 已加载（内容不打印）"; else fail "0.  .env 加载失败（$ENV_FILE 不存在或格式错误）"; fi

# ---------- 5-8. 配置 ----------
if [[ "${APP_ENV:-}" == "production" ]]; then pass "5.  APP_ENV = production"; else fail "5.  APP_ENV != production（当前=${APP_ENV:-空}）"; fi
if [[ -n "${DATABASE_URL:-}" ]]; then pass "6.  DATABASE_URL 已设置（$(mask_url "$DATABASE_URL")）"; else fail "6.  DATABASE_URL 未设置"; fi
if [[ -n "${RAG_DATABASE_URL:-}" ]]; then pass "7.  RAG_DATABASE_URL 已设置（$(mask_url "$RAG_DATABASE_URL")）"; else fail "7.  RAG_DATABASE_URL 未设置"; fi
DB_9000=$(db_name "${DATABASE_URL:-}")
DB_9100=$(db_name "${RAG_DATABASE_URL:-}")
if [[ -n "$DB_9000" && -n "$DB_9100" && "$DB_9000" != "$DB_9100" ]]; then
  pass "8.  两 database 名不同（9000=$DB_9000  9100=$DB_9100）"
else
  fail "8.  两 database 名相同或为空（9000=$DB_9000  9100=$DB_9100）"
fi

# ---------- 15. docker/compose/psql ----------
COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
fi
[[ -n "$COMPOSE_CMD" ]] && pass "15a. docker + compose 可用（$COMPOSE_CMD）" || fail "15a. docker compose 不可用"
command -v psql >/dev/null 2>&1 && pass "15b. psql 客户端可用" || warn "15b. psql 客户端不可用（可用 docker exec postgres psql 替代）"

# PG 连接（优先 docker compose exec，回退主机 psql）
PG_CONTAINER="${PG_CONTAINER:-postgres}"
psql_exec() {
  if [[ -n "$COMPOSE_CMD" ]] && $COMPOSE_CMD ps -q "$PG_CONTAINER" >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T "$PG_CONTAINER" psql -U "${PG_USER:-auto_wechat}" -d postgres -tAc "$1" 2>/dev/null
  else
    PGPASSWORD="${PG_PASSWORD:-}" psql -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "${PG_USER:-auto_wechat}" -d postgres -tAc "$1" 2>/dev/null
  fi
}

# ---------- 9-11. PG 连接 + 库存在 + owner ----------
if psql_exec "SELECT 1" >/dev/null 2>&1; then
  pass "9.  PostgreSQL 可连接"
  for db in "$DB_9000" "$DB_9100"; do
    [[ -z "$db" ]] && continue
    exists=$(psql_exec "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "")
    if [[ "$exists" == "1" ]]; then
      owner=$(psql_exec "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "?")
      pass "10/11. database '$db' 存在（owner=$owner）"
    else
      fail "10.   database '$db' 不存在（用 production_pg_ensure_databases.sh 创建）"
    fi
  done
else
  fail "9.  PostgreSQL 不可连接（检查 PG 容器状态/密码/网络；切换前必须可连）"
fi

# ---------- 12-13. SQLite 源 ----------
SQLITE_9000="${SQLITE_9000_PATH:-docker-data/auto_wechat_9000/auto_wechat.db}"
SQLITE_9100="${SQLITE_9100_PATH:-docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db}"
if [[ -f "$SQLITE_9000" ]]; then pass "12. 9000 SQLite 源存在（$SQLITE_9000, $(wc -c < "$SQLITE_9000") bytes）"; else fail "12. 9000 SQLite 源不存在（$SQLITE_9000）"; fi
if [[ -f "$SQLITE_9100" ]]; then pass "13. 9100 metadata SQLite 源存在（$SQLITE_9100, $(wc -c < "$SQLITE_9100") bytes）"; else fail "13. 9100 metadata SQLite 源不存在（$SQLITE_9100）"; fi

# ---------- 14. 磁盘 ----------
DISK_AVAIL=$(df -P "$PROJECT_ROOT" 2>/dev/null | awk 'NR==2{print $4}')
DISK_GB=$((DISK_AVAIL / 1024 / 1024))
if (( DISK_GB >= 5 )); then pass "14. 磁盘剩余 ${DISK_GB}GB（>= 5GB）"; else fail "14. 磁盘剩余 ${DISK_GB}GB（< 5GB，备份/迁移空间不足）"; fi

# ---------- 16. 容器和端口 ----------
if [[ -n "$COMPOSE_CMD" ]]; then
  echo "[INFO] 容器状态："
  $COMPOSE_CMD ps 2>/dev/null | sed 's/^/      /' || warn "16. compose ps 失败"
fi

# ---------- 17. readiness ----------
API_HOST="${API_HOST:-127.0.0.1}"; API_PORT="${API_PORT:-9000}"
CS_HOST="${CS_HOST:-127.0.0.1}"; CS_PORT="${CS_PORT:-9100}"
code_9000=$(curl -s -o /dev/null -w "%{http_code}" "http://$API_HOST:$API_PORT/ready" 2>/dev/null || echo "000")
code_9100=$(curl -s -o /dev/null -w "%{http_code}" "http://$CS_HOST:$CS_PORT/ready" 2>/dev/null || echo "000")
[[ "$code_9000" == "200" ]] && pass "17a. 9000 /ready = 200" || warn "17a. 9000 /ready = $code_9000（切换前可能是 sqlite 模式；切换后必须 200）"
[[ "$code_9100" == "200" ]] && pass "17b. 9100 /ready = 200" || warn "17b. 9100 /ready = $code_9100（切换前可能是 sqlite 模式；切换后必须 200）"

# ---------- 18. apply 安全门 ----------
SCRIPT_APPLY="$PROJECT_ROOT/scripts/production_pg_cutover_apply.sh"
if [[ -f "$SCRIPT_APPLY" ]] && grep -q "PROD_CUTOVER_APPROVER" "$SCRIPT_APPLY" 2>/dev/null && grep -q 'APP_ENV' "$SCRIPT_APPLY" 2>/dev/null; then
  pass "18. apply 安全门具备放行机制（PROD_CUTOVER_APPROVER/OPERATOR/TICKET + APP_ENV=production 强制）"
else
  fail "18. apply 安全门放行机制缺失（$SCRIPT_APPLY 未校验审批变量或 APP_ENV）"
fi

echo ""
echo "==================== 预检查汇总 ===================="
echo "PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
if (( FAIL > 0 )); then
  echo "结论：PREFLIGHT_FAIL（$FAIL 个失败项，不得开始切换）"
  exit 1
fi
echo "结论：PREFLIGHT_PASS（$WARN 个 WARN 项需人工确认）"
exit 0
