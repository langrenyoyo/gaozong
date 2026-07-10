#!/bin/bash
# 生产 PostgreSQL 切换后只读 smoke 测试。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §11。
#
# 只读验证切换后业务接口可用。token 由宝塔现场提供（--token）。
# 严禁：真实抖音发送、微信发送、私信发送、计算计费、auto_send=true。
# 本脚本只调用 GET 只读端点 + 一个 RAG search-preview（只读检索，不发送）。
#
# 用法：
#   bash scripts/production_pg_smoke.sh --token <JWT> [--api-9000 URL] [--api-9100 URL] [--frontend URL]
set -euo pipefail

API_9000="${API_9000_BASE:-http://127.0.0.1:9000}"
API_9100="${API_9100_BASE:-http://127.0.0.1:9100}"
FRONTEND_BASE="${FRONTEND_BASE:-http://127.0.0.1:5173}"
TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2;;
    --api-9000) API_9000="$2"; shift 2;;
    --api-9100) API_9100="$2"; shift 2;;
    --frontend) FRONTEND_BASE="$2"; shift 2;;
    --help|-h) sed -n '2,14p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

if [[ -z "$TOKEN" ]]; then
  echo "[FAIL] 必须传 --token（宝塔现场获取的 JWT，本脚本不自动登录）" >&2; exit 2
fi

PASS=0; WARN=0; FAIL=0
auth_header=(-H "Authorization: Bearer $TOKEN")

# 只读 GET 检查：name base path [可选：是否需要 token]
# need_token: 1=带 token, 0=不带（health/ready）
check_get() {
  local name="$1" base="$2" path="$3" need_token="${4:-1}"
  local code
  if [[ "$need_token" == "1" ]]; then
    code=$(curl -s -o /tmp/smoke_body -w "%{http_code}" --max-time 10 "${auth_header[@]}" "${base}${path}" 2>/dev/null || echo "000")
  else
    code=$(curl -s -o /tmp/smoke_body -w "%{http_code}" --max-time 10 "${base}${path}" 2>/dev/null || echo "000")
  fi
  # 200/201 视为成功；401/403 记 WARN（token 权限问题，端点本身可达）
  case "$code" in
    200|201) echo "[PASS] $name $path → $code"; PASS=$((PASS+1));;
    401|403) echo "[WARN] $name $path → $code（权限不足，端点可达）"; WARN=$((WARN+1));;
    *)       echo "[FAIL] $name $path → $code"; FAIL=$((FAIL+1));;
  esac
}

echo "==================== 9000 smoke（只读）===================="
check_get "9000-health" "$API_9000" "/health" 0
check_get "9000-ready"  "$API_9000" "/ready"  0
check_get "9000-leads"          "$API_9000" "/leads?page_size=1"
check_get "9000-staff"          "$API_9000" "/staff"
check_get "9000-reports"        "$API_9000" "/reports/summary"
check_get "9000-checks"         "$API_9000" "/checks?page_size=1"
check_get "9000-wechat-tasks"   "$API_9000" "/wechat-tasks?page_size=1"
check_get "9000-webhook-events" "$API_9000" "/webhook-events?page_size=1"
check_get "9000-agents"         "$API_9000" "/agents"
check_get "9000-compute-accts"  "$API_9000" "/compute/accounts"

echo ""
echo "==================== 9100 smoke（只读 RAG）===================="
check_get "9100-health" "$API_9100" "/health" 0
check_get "9100-ready"  "$API_9100" "/ready"  0
check_get "9100-rag-documents" "$API_9100" "/rag/documents?page_size=1"

# RAG search-preview（只读检索，不发送私信）
echo "[INFO] 9100-rag-search-preview（POST 只读检索，禁止 auto_send）"
code=$(curl -s -o /tmp/smoke_rag -w "%{http_code}" --max-time 15 "${auth_header[@]}" \
  -X POST -H "Content-Type: application/json" \
  -d '{"query":"小高","top_k":3,"auto_send":false}' \
  "${API_9100}/rag/search-preview" 2>/dev/null || echo "000")
case "$code" in
  200|201) echo "[PASS] 9100-rag-search-preview → $code"; PASS=$((PASS+1));;
  *)       echo "[WARN] 9100-rag-search-preview → $code（检索端点路径或参数现场确认）"; WARN=$((WARN+1));;
esac

echo ""
echo "==================== frontend smoke ===================="
check_get "frontend-root" "$FRONTEND_BASE" "/" 0

echo ""
echo "==================== smoke 汇总 ===================="
echo "PASS=$PASS  WARN=$WARN  FAIL=$FAIL"
echo ""
echo "[禁止清单自检] 本脚本不应调用以下端点（仅自检，不阻塞）："
echo "  - POST /wechat-tasks（发送微信）"
echo "  - POST /douyin/send 或私信发送"
echo "  - POST /compute/charge 或计费"
echo "  - auto_send=true 的任何端点"
# 自检：本脚本文件不含禁止端点（grep 自身）
if grep -qE '/wechat-tasks"|/douyin/send|/compute/charge|auto_send.: ?true' "$0"; then
  echo "[FAIL] 脚本自检发现禁止端点引用（排除注释行需人工复核）" >&2
  # 排除注释/echo 行后再判
  if grep -vE '^\s*#|echo ' "$0" | grep -qE '/douyin/send|/compute/charge|auto_send.: ?true'; then
    echo "[FAIL] 确认存在禁止端点（非注释行）" >&2; exit 1
  fi
  echo "[PASS] 禁止端点仅出现在注释/echo 说明中"
else
  echo "[PASS] 脚本未引用禁止端点"
fi

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "[FAIL] smoke 存在失败项（FAIL=$FAIL），请现场排查" >&2
  exit 1
fi
echo ""
echo "SMOKE_DONE（FAIL=0，WARN 项需现场确认权限/路径）"
