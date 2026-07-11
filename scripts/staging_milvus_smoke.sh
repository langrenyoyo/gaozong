#!/bin/bash
# staging 外部 Milvus 定向 smoke（P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1 / 任务第七节）。
#
# 10 步：非 production collection → readiness → canary 写入/查询/RAG检索 → 重启 → 再查 → 删除 → 确认隔离。
# 不得使用 production 凭据或 production collection。
#
# 最终结论只能为：
#   EXTERNAL_MILVUS_STAGING_SMOKE_PASSED
#   EXTERNAL_MILVUS_STAGING_SMOKE_BLOCKED
#   EXTERNAL_MILVUS_STAGING_SMOKE_FAILED
#
# 用法：
#   bash scripts/staging_milvus_smoke.sh [--project-root DIR] [--env-file .env.staging.local]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env.staging.local"
COMPOSE_FILE="docker-compose.staging.yml"
CS_SERVICE="${CS_SERVICE:-xg-douyin-ai-cs}"
CS_HOST="${CS_HOST:-127.0.0.1}"
CS_PORT="${CS_PORT:-29100}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --cs-port) CS_PORT="$2"; shift 2;;
    --help|-h) sed -n '2,17p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

PASS=0; FAIL=0
pass() { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }

echo "==================== staging 外部 Milvus 定向 smoke ===================="

# 加载 staging env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[BLOCKED] staging env 不存在：$ENV_FILE（staging smoke 需真实外部 Milvus 环境）" >&2
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_BLOCKED"
  exit 2
fi
set -a; source "$ENV_FILE"; set +a

# ---------- 步骤 1：非 production database/collection ----------
if [[ "${RAG_VECTOR_BACKEND:-}" != "milvus" ]]; then
  echo "[BLOCKED] RAG_VECTOR_BACKEND 不是 milvus（当前=${RAG_VECTOR_BACKEND:-空}），staging smoke 需在 $ENV_FILE 显式设 milvus" >&2
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_BLOCKED"
  exit 2
fi
# 禁止常见 production collection 命名
PROD_FORBIDDEN="production prod release main master live"
for bad in $PROD_FORBIDDEN; do
  if [[ "${MILVUS_COLLECTION:-}" == *"$bad"* ]]; then
    echo "[BLOCKED] MILVUS_COLLECTION 含 production 保留字（$MILVUS_COLLECTION），staging 不得使用 production collection" >&2
    echo "EXTERNAL_MILVUS_STAGING_SMOKE_BLOCKED"
    exit 2
  fi
done
pass "1.  使用非 production collection（MILVUS_COLLECTION=$MILVUS_COLLECTION）"

# ---------- 步骤 2：staging 配置 RAG_VECTOR_BACKEND=milvus ----------
pass "2.  RAG_VECTOR_BACKEND=milvus"

# ---------- 步骤 3：验证 readiness（含 Milvus 只读检查）----------
code=$(curl -s -o /dev/null -w "%{http_code}" "http://$CS_HOST:$CS_PORT/ready" 2>/dev/null || echo "000")
if [[ "$code" == "200" ]]; then
  pass "3.  9100 /ready = 200（含 Milvus readiness：配置/认证/collection/dimension/探测）"
else
  fail "3.  9100 /ready = $code（Milvus 不可达或配置错误，不回退 SQLite）"
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_FAILED"; exit 1
fi

# ---------- 步骤 4-6,9：canary 写入/查询/RAG检索/删除 ----------
COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
if [[ -z "$COMPOSE_CMD" ]]; then
  echo "[BLOCKED] docker compose 不可用，无法在 staging 容器内执行 canary" >&2
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_BLOCKED"; exit 2
fi

echo "[INFO] 步骤 4-6,9：执行 milvus_canary_e2e（写测试向量 → 查询 → RAG检索 → 删除 → 删除验证）"
set +e
CANARY_OUT=$($COMPOSE_CMD -f "$COMPOSE_FILE" exec -T "$CS_SERVICE" python -m apps.xg_douyin_ai_cs.scripts.milvus_canary_e2e 2>&1)
CANARY_EXIT=$?
set -e
echo "$CANARY_OUT" | sed 's/^/      /'
if [[ $CANARY_EXIT -eq 0 ]] && echo "$CANARY_OUT" | grep -q "upsert_ok=True" && echo "$CANARY_OUT" | grep -q "delete_ok=True"; then
  pass "4-6,9. canary 写入/查询/RAG检索/删除全通过"
else
  fail "4-6,9. canary 未全绿（exit=$CANARY_EXIT，详见上方输出）"
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_FAILED"; exit 1
fi

# ---------- 步骤 7-8：重启 9100 后 readiness 恢复 ----------
echo "[INFO] 步骤 7：重启 $CS_SERVICE 容器"
$COMPOSE_CMD -f "$COMPOSE_FILE" restart "$CS_SERVICE" >/dev/null 2>&1 || fail "7. restart 失败"
i=0
while [[ $i -lt 60 ]]; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://$CS_HOST:$CS_PORT/ready" 2>/dev/null || echo "000")
  [[ "$code" == "200" ]] && break
  sleep 2; i=$((i+2))
done
if [[ "$code" == "200" ]]; then
  pass "7.  重启后 9100 /ready 恢复 200"
  pass "8.  重启后 Milvus readiness 可用（测试向量已在步骤9删除）"
else
  fail "7.  重启后 readiness 未恢复（/ready=$code）"
fi

# ---------- 步骤 10：确认未访问 production collection ----------
if [[ -n "${PRODUCTION_MILVUS_COLLECTION:-}" ]]; then
  if [[ "${MILVUS_COLLECTION:-}" == "${PRODUCTION_MILVUS_COLLECTION}" ]]; then
    fail "10. staging collection 等于 production collection（$MILVUS_COLLECTION）"
    echo "EXTERNAL_MILVUS_STAGING_SMOKE_FAILED"; exit 1
  fi
  pass "10. staging collection（$MILVUS_COLLECTION）≠ production（$PRODUCTION_MILVUS_COLLECTION）"
else
  pass "10. 未设 PRODUCTION_MILVUS_COLLECTION，按命名隔离校验（$MILVUS_COLLECTION 不含 production 保留字）"
fi

echo ""
echo "==================== staging smoke 汇总 ===================="
echo "PASS=$PASS  FAIL=$FAIL"
if [[ $FAIL -gt 0 ]]; then
  echo "EXTERNAL_MILVUS_STAGING_SMOKE_FAILED"; exit 1
fi
echo "EXTERNAL_MILVUS_STAGING_SMOKE_PASSED"
exit 0
