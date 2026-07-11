#!/bin/bash
# 生产 PostgreSQL 切换 + 就绪验证（cutover apply 后执行）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §10。
#
# 本脚本不负责 Alembic 和 cutover，只负责：
#   1. 验证 production 环境变量已切至 PostgreSQL（DATABASE_URL / RAG_DATABASE_URL 均为 postgresql）
#   2. 执行 production compose config（校验配置可解析）
#   3. 更新或启动 production 容器（up -d，不删除 volume、不删除 SQLite 文件）
#   4. 检查：PostgreSQL health；9000 /health；9000 /ready；9100 /health；9100 /ready；frontend
#   5. 输出 database 名、alembic revision 和 critical tables 行数
#   6. readiness 失败时返回非零
#
# 不得删除 SQLite 文件或 volume；不得修改 production env。
#
# 用法：
#   bash scripts/production_pg_switch_and_verify.sh [--project-root DIR] [--env-file .env.production.local]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env.production.local"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"   # 单端点最大等待秒数

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2;;
    --help|-h) sed -n '2,19p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

# 加载 production env（只读校验，不修改）
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[FAIL] production env 不存在：$ENV_FILE" >&2; exit 1
fi
set -a; source "$ENV_FILE"; set +a

mask_url() { echo "$1" | sed -E 's#://([^:/]+):[^@]+@#://\1:***@#'; }

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[FAIL] compose 文件不存在：$COMPOSE_FILE" >&2; exit 1
fi
COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
[[ -n "$COMPOSE_CMD" ]] || { echo "[FAIL] docker compose 不可用" >&2; exit 1; }

echo "==================== 1. 环境变量校验（PostgreSQL）===================="
if [[ "${APP_ENV:-}" != "production" ]]; then
  echo "[FAIL] APP_ENV 必须是 production（当前=${APP_ENV:-空}）" >&2; exit 1
fi
echo "[PASS] APP_ENV=production"

URL_9000="${DATABASE_URL:-}"
URL_9100="${RAG_DATABASE_URL:-}"
if [[ "$URL_9000" != postgresql* ]]; then
  echo "[FAIL] DATABASE_URL 未切至 PostgreSQL：$(mask_url "$URL_9000")" >&2; exit 1
fi
if [[ "$URL_9100" != postgresql* ]]; then
  echo "[FAIL] RAG_DATABASE_URL 未切至 PostgreSQL：$(mask_url "$URL_9100")" >&2; exit 1
fi
echo "[PASS] DATABASE_URL      = $(mask_url "$URL_9000")"
echo "[PASS] RAG_DATABASE_URL  = $(mask_url "$URL_9100")"

DB_9000=$(echo "$URL_9000" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
DB_9100=$(echo "$URL_9100" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
if [[ -z "$DB_9000" || -z "$DB_9100" ]]; then
  echo "[FAIL] 无法从 URL 解析库名（9000=$DB_9000 9100=$DB_9100）" >&2; exit 1
fi
if [[ "$DB_9000" == "$DB_9100" ]]; then
  echo "[FAIL] 两个 database 名相同（$DB_9000），违反方案 A（一实例两库）" >&2; exit 1
fi
echo "[PASS] 9000 database = $DB_9000"
echo "[PASS] 9100 database = $DB_9100"
echo "[PASS] 两库不同（方案 A）"

# 向量后端校验（production 固定外部 Milvus，不得回退 SQLite 向量后端）
if [[ "${RAG_VECTOR_BACKEND:-}" != "milvus" ]]; then
  echo "[FAIL] RAG_VECTOR_BACKEND 必须为 milvus（当前=${RAG_VECTOR_BACKEND:-空}），production 不得回退 SQLite 向量后端" >&2
  exit 1
fi
echo "[PASS] RAG_VECTOR_BACKEND=milvus"
MILVUS_MISSING=""
for var in MILVUS_URI MILVUS_USERNAME MILVUS_PASSWORD MILVUS_DB_NAME MILVUS_COLLECTION MILVUS_DIMENSION; do
  if [[ -z "${!var:-}" ]]; then MILVUS_MISSING="$MILVUS_MISSING $var"; fi
done
if [[ -n "$MILVUS_MISSING" ]]; then
  echo "[FAIL] Milvus 配置缺失：$MILVUS_MISSING" >&2; exit 1
fi
echo "[PASS] Milvus 必填配置完整"
if [[ "${MILVUS_DIMENSION:-}" != "${XG_DOUYIN_AI_EMBEDDING_DIMENSIONS:-}" ]]; then
  echo "[FAIL] MILVUS_DIMENSION=$MILVUS_DIMENSION != XG_DOUYIN_AI_EMBEDDING_DIMENSIONS=${XG_DOUYIN_AI_EMBEDDING_DIMENSIONS:-空}" >&2; exit 1
fi
echo "[PASS] MILVUS_DIMENSION=$MILVUS_DIMENSION 与 EMBEDDING_DIMENSIONS 一致（9100 /ready 将验证 Milvus 可连接性）"

echo ""
echo "==================== 2. compose config 校验 ===================="
if ! $COMPOSE_CMD -f "$COMPOSE_FILE" config >/tmp/compose_config.out 2>/tmp/compose_config.err; then
  echo "[FAIL] compose config 解析失败" >&2
  cat /tmp/compose_config.err >&2
  exit 1
fi
echo "[PASS] compose config 可解析"
# 确认 DATABASE_URL 已注入到 9000 容器（compose env 组装）
if grep -q "DATABASE_URL" /tmp/compose_config.out; then
  echo "[PASS] 9000 容器已注入 DATABASE_URL"
else
  echo "[WARN] compose config 未显式出现 DATABASE_URL（现场确认 env_file 注入）"
fi

echo ""
echo "==================== 3. 启动/更新容器（不删 volume）===================="
echo "[INFO] 执行 $COMPOSE_CMD -f $COMPOSE_FILE up -d（不使用 --volumes）"
# 注意：禁止 -v / --volumes，禁止 down --volumes，不删 SQLite
$COMPOSE_CMD -f "$COMPOSE_FILE" up -d
echo "[PASS] compose up -d 完成"

echo ""
echo "==================== 4. 就绪检查 ===================="
# 轮询函数：name url path（最多 HEALTH_TIMEOUT 秒）
wait_http() {
  local name="$1" base="$2" path="$3"
  local i=0
  while [[ $i -lt $HEALTH_TIMEOUT ]]; do
    if curl -fsS --max-time 5 "${base}${path}" >/dev/null 2>&1; then
      echo "[PASS] $name ${path}（${i}s）"
      return 0
    fi
    sleep 2; i=$((i+2))
  done
  echo "[FAIL] $name ${path} 超时（${HEALTH_TIMEOUT}s）" >&2
  return 1
}

# PostgreSQL health（compose healthcheck 状态）
wait_pg() {
  local i=0
  while [[ $i -lt $HEALTH_TIMEOUT ]]; do
    local st
    st=$($COMPOSE_CMD -f "$COMPOSE_FILE" ps postgres 2>/dev/null | grep -oE '(healthy|running)' | head -1 || echo "")
    if [[ "$st" == "healthy" ]]; then
      echo "[PASS] PostgreSQL healthy（${i}s）"; return 0
    fi
    sleep 2; i=$((i+2))
  done
  echo "[FAIL] PostgreSQL 未在 ${HEALTH_TIMEOUT}s 内 healthy" >&2
  return 1
}

wait_pg || exit 1

API_9000="${API_9000_BASE:-http://127.0.0.1:9000}"
API_9100="${API_9100_BASE:-http://127.0.0.1:9100}"
FRONTEND_BASE="${FRONTEND_BASE:-http://127.0.0.1:5173}"

wait_http "9000" "$API_9000" "/health" || exit 1
wait_http "9000" "$API_9000" "/ready"  || exit 1
wait_http "9100" "$API_9100" "/health" || exit 1
wait_http "9100" "$API_9100" "/ready"  || exit 1
# frontend：5173 端口可达即可
wait_http "frontend" "$FRONTEND_BASE" "/" || exit 1

echo ""
echo "==================== 5. database 名 + revision + critical tables ===================="
INI_9000="migrations/postgres/auto_wechat/alembic.ini"
INI_9100="migrations/postgres/xg_douyin_ai_cs/alembic.ini"
SVC_9000="auto-wechat-api"
SVC_9100="xg-douyin-ai-cs"

PG_CONTAINER="${PG_CONTAINER:-postgres}"

echo "----- 9000 ($DB_9000) -----"
echo "[alembic current]"
$COMPOSE_CMD -f "$COMPOSE_FILE" exec -T "$SVC_9000" alembic -c "$INI_9000" current 2>&1 | sed 's/^/  /' || echo "  (alembic current 失败)"
echo "[critical tables 行数]"
CRIT_9000=(leads staff douyin_webhook_events wechat_tasks reply_checks notifications)
for t in "${CRIT_9000[@]}"; do
  cnt=$($COMPOSE_CMD -f "$COMPOSE_FILE" exec -T "$PG_CONTAINER" psql -U "${PG_USER:-auto_wechat}" -d "$DB_9000" -tAc "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo "?")
  printf "  %-28s %s\n" "$t" "$cnt"
done

echo "----- 9100 ($DB_9100) -----"
echo "[alembic current]"
$COMPOSE_CMD -f "$COMPOSE_FILE" exec -T "$SVC_9100" alembic -c "$INI_9100" current 2>&1 | sed 's/^/  /' || echo "  (alembic current 失败)"
echo "[critical tables 行数]"
CRIT_9100=(documents chunks feedback training_run)
for t in "${CRIT_9100[@]}"; do
  cnt=$($COMPOSE_CMD -f "$COMPOSE_FILE" exec -T "${PG_CONTAINER:-postgres}" psql -U "${PG_USER:-auto_wechat}" -d "$DB_9100" -tAc "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo "?")
  printf "  %-28s %s\n" "$t" "$cnt"
done

echo ""
echo "[INFO] SQLite 文件保留（未删除）："
ls -la "$PROJECT_ROOT/docker-data/auto_wechat_9000/auto_wechat.db" 2>/dev/null | sed 's/^/  /' || echo "  (9000 SQLite 不在默认路径，现场确认)"
ls -la "$PROJECT_ROOT/docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db" 2>/dev/null | sed 's/^/  /' || echo "  (9100 SQLite 不在默认路径，现场确认)"

echo ""
echo "SWITCH_AND_VERIFY_DONE"
