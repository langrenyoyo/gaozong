#!/bin/bash
# 生产 Alembic upgrade head（9000 → 0007_lead_type_widen，9100 → 0002_create_rag_metadata）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §8。
#
# 两套 Alembic 各自显式 -c 配置；执行前后显示 current；校验目标 revision；任一失败停止。
# 禁止裸 alembic upgrade head（必须 -c 指定配置）。不自动执行 cutover。
#
# 用法：
#   bash scripts/production_pg_alembic_upgrade.sh [--project-root DIR] [--service 9000|9100|both]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
SERVICE="${SERVICE:-both}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --help|-h) sed -n '2,11p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
[[ -n "$COMPOSE_CMD" ]] || { echo "[FAIL] docker compose 不可用" >&2; exit 1; }

TARGET_9000="0007_lead_type_widen"
TARGET_9100="0002_create_rag_metadata"
INI_9000="migrations/postgres/auto_wechat/alembic.ini"
INI_9100="migrations/postgres/xg_douyin_ai_cs/alembic.ini"
SVC_9000="auto-wechat-api"
SVC_9100="xg-douyin-ai-cs"

# alembic 步骤：service ini target
alembic_step() {
  local svc="$1" ini="$2" target="$3"
  echo "==================== $svc Alembic ===================="
  echo "[INFO] 目标 revision: $target"
  echo "[INFO] 配置: $ini（显式 -c，禁止裸 upgrade）"
  echo "[before] heads:"
  $COMPOSE_CMD exec -T "$svc" alembic -c "$ini" heads 2>&1 | sed 's/^/  /'
  echo "[before] current:"
  $COMPOSE_CMD exec -T "$svc" alembic -c "$ini" current 2>&1 | sed 's/^/  /'

  echo "[run]    alembic -c $ini upgrade head"
  if ! $COMPOSE_CMD exec -T "$svc" alembic -c "$ini" upgrade head; then
    echo "[FAIL] $svc alembic upgrade head 失败（停止，不继续）" >&2
    return 1
  fi

  echo "[after]  current:"
  local after
  after=$($COMPOSE_CMD exec -T "$svc" alembic -c "$ini" current 2>&1 | tee /dev/stderr | grep -oE '^[0-9a-f]+_[a-z0-9_]+' | head -1 || echo "")
  if [[ "$after" != "$target" ]]; then
    echo "[FAIL] $svc 未达目标 $target（actual=$after）" >&2
    return 1
  fi
  echo "[PASS] $svc 达 $target"
  echo ""
}

case "$SERVICE" in
  9000) alembic_step "$SVC_9000" "$INI_9000" "$TARGET_9000" || exit 1;;
  9100) alembic_step "$SVC_9100" "$INI_9100" "$TARGET_9100" || exit 1;;
  both)
    alembic_step "$SVC_9000" "$INI_9000" "$TARGET_9000" || exit 1
    alembic_step "$SVC_9100" "$INI_9100" "$TARGET_9100" || exit 1
    ;;
  *) echo "[FAIL] --service 仅支持 9000/9100/both" >&2; exit 2;;
esac

echo "ALEMBIC_UPGRADE_DONE"
