#!/bin/bash
# 生产 PostgreSQL 切换回滚（默认只打印计划，显式 --execute 才执行）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §13。
#
# 回滚策略：
#   - 恢复 production env 至 SQLite 配置（注释 DATABASE_URL / RAG_DATABASE_URL）
#   - 重启 9000/9100 容器，使其回退读 SQLite
#   - 不删除 PG 数据（volume 保留，便于事后查切换期间新数据）
#   - 不覆盖原始 SQLite 文件（cutover 只读 SQLite 写 PG，原始 SQLite 未被改）
#   - 切换期间写入 PG 的新数据需人工评估补偿（脚本只提示，不自动同步）
#
# 安全门：
#   1. 默认拒绝（无 --execute 只打印计划，退出 2 = 拒绝/未执行）
#   2. 需要 --approver/--operator/--reason + 审批≠执行
#   3. APP_ENV=production
#   4. 当前 production env 确实是 PG 配置（确认从 PG 回滚）
#   5. production env 改前先备份 .env.production.local.pg-rollback-TS
#   6. 不 touch docker-data/*.db，不删 volume
#
# 用法：
#   bash scripts/production_pg_rollback.sh                                      # 打印计划
#   bash scripts/production_pg_rollback.sh --execute \
#     --approver Waston --operator LNZS --reason "ready check 失败" \
#     [--ticket PROD-001] [--backup-dir backups/cutover-XXX]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env.production.local"
EXECUTE=0
APPROVER=""; OPERATOR=""; REASON=""; TICKET=""; BACKUP_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --execute) EXECUTE=1; shift;;
    --approver) APPROVER="$2"; shift 2;;
    --operator) OPERATOR="$2"; shift 2;;
    --reason) REASON="$2"; shift 2;;
    --ticket) TICKET="$2"; shift 2;;
    --backup-dir) BACKUP_DIR="$2"; shift 2;;
    --help|-h) sed -n '2,27p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

mask_url() { echo "$1" | sed -E 's#://([^:/]+):[^@]+@#://\1:***@#'; }

# ---------- 默认拒绝（无 --execute 只打印计划）----------
if [[ $EXECUTE -eq 0 ]]; then
  cat <<EOF
==================== 回滚计划（未执行）====================
默认拒绝回滚。执行回滚必须显式传：
  --execute               （必须，触发实际回滚）
  --approver <审批人>     （≠ 执行人，本任务固定 Waston）
  --operator <执行人>     （回滚执行人，本任务固定 LNZS）
  --reason   <回滚原因>   （必填，如 ready check 失败）
  [--ticket <单号>]       [--backup-dir <dir>]

回滚操作内容：
  1. 备份当前 production env → .env.production.local.pg-rollback-<TS>
  2. 注释 production env 中 DATABASE_URL / RAG_DATABASE_URL（恢复 SQLite 配置）
  3. docker compose up -d（重启 9000/9100 回退 SQLite）
  4. 健康检查：9000 /ready、9100 /ready

不执行：
  - 不删除 PG volume（切换期间新数据保留，便于事后补偿评估）
  - 不覆盖原始 SQLite 文件（cutover 未改 SQLite，原文件即切换前状态）

⚠️ 数据补偿提示：
  切换期间（cutover apply → 回滚）写入 PG 的新数据（新线索、新会话、新检测记录）
  不会自动同步回 SQLite。回滚后需人工评估：
  - 从 PG 备份（backup.sh 产出 pg-*.dump + 当前 PG 实时数据）导出增量
  - 按 [宝塔现场确认] 的方式补偿到 SQLite 或人工处理

未传 --execute，不执行任何写操作（退出码 2 = 拒绝/未执行，非成功）。
EOF
  exit 2
fi

# ---------- 校验审批参数 ----------
MISSING=""
[[ -z "$APPROVER" ]] && MISSING="$MISSING --approver"
[[ -z "$OPERATOR" ]] && MISSING="$MISSING --operator"
[[ -z "$REASON"   ]] && MISSING="$MISSING --reason"
if [[ -n "$MISSING" ]]; then
  echo "[FAIL] 缺少参数：$MISSING" >&2; exit 2
fi
if [[ "$APPROVER" == "$OPERATOR" ]]; then
  echo "[FAIL] 审批人不得与执行人相同" >&2; exit 2
fi

# ---------- APP_ENV ----------
if [[ ! -f "$ENV_FILE" ]]; then echo "[FAIL] production env 不存在：$ENV_FILE" >&2; exit 1; fi
set -a; source "$ENV_FILE"; set +a
if [[ "${APP_ENV:-}" != "production" ]]; then
  echo "[FAIL] APP_ENV 必须是 production（当前=${APP_ENV:-空}）" >&2; exit 2
fi

# ---------- 确认当前是 PG 配置 ----------
if [[ "${DATABASE_URL:-}" != postgresql* ]]; then
  echo "[FAIL] 当前 DATABASE_URL 不是 PostgreSQL（$(mask_url "${DATABASE_URL:-空}")），无需回滚到 SQLite" >&2; exit 2
fi
echo "[PASS] 当前 production env 确为 PG 配置，确认从 PG 回滚"

# ---------- compose 命令 ----------
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
[[ -n "$COMPOSE_CMD" ]] || { echo "[FAIL] docker compose 不可用" >&2; exit 1; }

# ---------- 审计日志 ----------
TS=$(date +%Y%m%d-%H%M%S)
AUDIT_LOG="$PROJECT_ROOT/markers/rollback_audit_${TS}.log"
mkdir -p "$PROJECT_ROOT/markers"
{
  echo "rollback audit"
  echo "time     : $(date -Iseconds)"
  echo "approver : $APPROVER"
  echo "operator : $OPERATOR"
  echo "reason   : $REASON"
  echo "ticket   : ${TICKET:-[未提供]}"
  echo "git      : $(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  echo "================================================"
} > "$AUDIT_LOG"

echo "==================== 执行回滚 ===================="
echo "[INFO] 执行人=$OPERATOR 审批人=$APPROVER 单号=${TICKET:-无}"
echo "[INFO] 原因=$REASON"

# 1. 备份当前 production env
ENV_BACKUP="${ENV_FILE}.pg-rollback-${TS}"
cp -p "$ENV_FILE" "$ENV_BACKUP"
echo "[PASS] production env 已备份 → $ENV_BACKUP" | tee -a "$AUDIT_LOG"

# 2. 注释 DATABASE_URL / RAG_DATABASE_URL（恢复 SQLite 配置）
# 使用 sed 注释掉 PG URL 行（保留原行作为注释，便于事后追溯）
if grep -qE "^DATABASE_URL=" "$ENV_FILE"; then
  sed -i.bak -E "s#^(DATABASE_URL=.*)#\# [rollback $TS] \1#" "$ENV_FILE"
  echo "[PASS] DATABASE_URL 已注释（恢复 SQLite）" | tee -a "$AUDIT_LOG"
fi
if grep -qE "^RAG_DATABASE_URL=" "$ENV_FILE"; then
  sed -i.bak -E "s#^(RAG_DATABASE_URL=.*)#\# [rollback $TS] \1#" "$ENV_FILE"
  echo "[PASS] RAG_DATABASE_URL 已注释（恢复 SQLite）" | tee -a "$AUDIT_LOG"
fi
rm -f "${ENV_FILE}.bak"

# 3. 重启容器（不删 volume）
echo "[INFO] $COMPOSE_CMD -f $COMPOSE_FILE up -d" | tee -a "$AUDIT_LOG"
$COMPOSE_CMD -f "$COMPOSE_FILE" up -d 2>&1 | tee -a "$AUDIT_LOG"

# 4. 健康检查（轮询 ready）
API_9000="${API_9000_BASE:-http://127.0.0.1:9000}"
API_9100="${API_9100_BASE:-http://127.0.0.1:9100}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"
wait_http() {
  local name="$1" base="$2" path="$3" i=0
  while [[ $i -lt $HEALTH_TIMEOUT ]]; do
    if curl -fsS --max-time 5 "${base}${path}" >/dev/null 2>&1; then
      echo "[PASS] $name ${path}（${i}s）" | tee -a "$AUDIT_LOG"; return 0
    fi
    sleep 2; i=$((i+2))
  done
  echo "[FAIL] $name ${path} 超时（${HEALTH_TIMEOUT}s）" | tee -a "$AUDIT_LOG" >&2; return 1
}

wait_http "9000" "$API_9000" "/ready" || { echo "[FAIL] 回滚后 9000 /ready 未恢复" >&2; exit 1; }
wait_http "9100" "$API_9100" "/ready" || { echo "[FAIL] 回滚后 9100 /ready 未恢复" >&2; exit 1; }

echo ""
echo "==================== 回滚完成 ===================="
echo "审计日志：$AUDIT_LOG"
echo ""
echo "⚠️ 数据补偿提示（必须人工处理）："
echo "  切换期间写入 PG 的新数据未自动同步回 SQLite。"
echo "  - PG 备份：${BACKUP_DIR:+$BACKUP_DIR/}pg-*.dump（切换前快照）"
echo "  - 当前 PG 实时数据：保留在 volume，未删除"
echo "  - 补偿方式：[宝塔现场确认]，建议从 PG 导出 cutover apply 后的增量记录，人工评估"
echo ""
echo "[INFO] SQLite 文件未被覆盖："
ls -la "$PROJECT_ROOT/docker-data/auto_wechat_9000/auto_wechat.db" 2>/dev/null | sed 's/^/  /' || echo "  (9000 SQLite 路径现场确认)"
ls -la "$PROJECT_ROOT/docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db" 2>/dev/null | sed 's/^/  /' || echo "  (9100 SQLite 路径现场确认)"
echo ""
echo "ROLLBACK_DONE（SQLite 已恢复，PG volume 保留待补偿评估）"
