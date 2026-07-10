#!/bin/bash
# 生产 cutover apply（写操作，默认拒绝，需显式审批参数 + 前置标记）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §9。
#
# 安全门（全部必须通过才执行）：
#   1. 默认拒绝（无参数只打印计划，退出 2 = 拒绝/未执行）
#   2. 显式 --approver/--operator/--ticket 三参数齐全 + 审批人 ≠ 执行人
#   3. APP_ENV 必须是 production（拒绝 development/staging 绕过）
#   4. 备份标记存在（--backup-dir 指向 backup.sh 产出目录，含 MANIFEST.txt）
#   5. dry-run 标记存在（--dry-run-log 含 DRY_RUN_PASS）
#   6. 目标库名校验（MAIN_TARGET_DATABASE_NAME / RAG_TARGET_DATABASE_NAME）
#   7. 执行后立即 unset 临时放行变量
#   8. 审计日志记录时间/执行人/库名/结果（不记录密码）
#
# 用法（生产执行）：
#   bash scripts/production_pg_cutover_apply.sh \
#     --approver Waston --operator VHwwsf --ticket PROD-001 \
#     --backup-dir backups/cutover-YYYYMMDD-HHMMSS \
#     --dry-run-log /tmp/dry_run.log [--service 9000|9100|both]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env.production.local"
SERVICE="both"
APPROVER=""; OPERATOR=""; TICKET=""; BACKUP_DIR=""; DRY_RUN_LOG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --approver) APPROVER="$2"; shift 2;;
    --operator) OPERATOR="$2"; shift 2;;
    --ticket) TICKET="$2"; shift 2;;
    --backup-dir) BACKUP_DIR="$2"; shift 2;;
    --dry-run-log) DRY_RUN_LOG="$2"; shift 2;;
    --help|-h) sed -n '2,22p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

# ---------- 1. 默认拒绝（无审批参数只打印计划）----------
if [[ -z "$APPROVER" && -z "$OPERATOR" && -z "$TICKET" ]]; then
  cat <<EOF
==================== cutover apply 计划（未执行）=====================
默认拒绝写操作。生产执行必须显式传：
  --approver <审批人>      （≠ 执行人，本任务固定 Waston）
  --operator <执行人>      （本任务固定 VHwwsf）
  --ticket   <变更单号>    （如 PROD-2026-07-10-001）
  --backup-dir <dir>       （backup.sh 产出目录，含 MANIFEST.txt）
  --dry-run-log <file>     （dry_run.sh 日志，须含 DRY_RUN_PASS）
  [--service 9000|9100|both]

前置条件：
  1. preflight PASS
  2. backup.sh 已执行且 BACKUP_DIR 存在
  3. dry_run.sh 已执行且日志含 DRY_RUN_PASS
4. production env APP_ENV=production（拒绝 development/staging 绕过）

未传审批参数，不执行任何写操作（退出码 2 = 拒绝/未执行，非成功）。
EOF
  exit 2
fi

# ---------- 2. 校验审批三参数 ----------
MISSING=""
[[ -z "$APPROVER" ]] && MISSING="$MISSING --approver"
[[ -z "$OPERATOR" ]] && MISSING="$MISSING --operator"
[[ -z "$TICKET"   ]] && MISSING="$MISSING --ticket"
if [[ -n "$MISSING" ]]; then
  echo "[FAIL] 缺少审批参数：$MISSING" >&2
  exit 2
fi
if [[ "$APPROVER" == "$OPERATOR" ]]; then
  echo "[FAIL] 审批人不得与执行人相同（--approver != --operator）" >&2
  exit 2
fi

# ---------- 3. APP_ENV=production 强制 ----------
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }
if [[ "${APP_ENV:-}" != "production" ]]; then
  echo "[FAIL] APP_ENV 必须是 production（当前=${APP_ENV:-空}）；禁止修改 APP_ENV=development 绕过" >&2
  exit 2
fi

# ---------- 4. 备份标记 ----------
if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" || ! -f "$BACKUP_DIR/MANIFEST.txt" ]]; then
  echo "[FAIL] 备份标记缺失：--backup-dir 必须指向 backup.sh 产出目录（含 MANIFEST.txt）" >&2
  exit 2
fi
echo "[PASS] 备份标记存在：$BACKUP_DIR/MANIFEST.txt"

# ---------- 5. dry-run 标记 ----------
if [[ -z "$DRY_RUN_LOG" || ! -f "$DRY_RUN_LOG" ]]; then
  echo "[FAIL] dry-run 标记缺失：--dry-run-log 必须指向 dry_run.sh 日志文件" >&2
  exit 2
fi
if ! grep -q "DRY_RUN_PASS" "$DRY_RUN_LOG" 2>/dev/null; then
  echo "[FAIL] dry-run 日志未含 DRY_RUN_PASS（$DRY_RUN_LOG）" >&2
  exit 2
fi
echo "[PASS] dry-run 标记存在：$DRY_RUN_LOG"

# ---------- 6. 目标库名 ----------
SQLITE_9000="${SQLITE_9000_PATH:-docker-data/auto_wechat_9000/auto_wechat.db}"
SQLITE_9100="${SQLITE_9100_PATH:-docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db}"
DB_9000=$(echo "${DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
DB_9100=$(echo "${RAG_DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')

AUDIT_LOG="$PROJECT_ROOT/markers/cutover_apply_audit_$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$PROJECT_ROOT/markers"

run_apply() {
  local svc="$1" script="$2" sqlite="$3" url="$4" db="$5" target_var="$6"
  echo "==================== $svc cutover apply ===================="
  echo "[INFO] 执行人=$OPERATOR 审批人=$APPROVER 单号=$TICKET"
  echo "[INFO] 目标库=$db（URL 不打印）"
  {
    echo "[$(date -Iseconds)] svc=$svc db=$db approver=$APPROVER operator=$OPERATOR ticket=$TICKET git=$(git rev-parse --short=12 HEAD 2>/dev/null)"
  } >> "$AUDIT_LOG"

  # export 临时放行变量（python production 门校验）
  export PROD_CUTOVER_APPROVER="$APPROVER" PROD_CUTOVER_OPERATOR="$OPERATOR" PROD_CUTOVER_TICKET="$TICKET"

  local rc=0
  if env "$target_var=$db" python "$script" --sqlite-db-path "$sqlite" --postgres-url "$url" --apply --yes 2>&1 | tee -a "$AUDIT_LOG"; then
    if grep -q "APPLY_PASS" "$AUDIT_LOG"; then
      echo "[PASS] $svc apply 成功"
      echo "[$(date -Iseconds)] svc=$svc result=APPLY_PASS" >> "$AUDIT_LOG"
    else
      echo "[FAIL] $svc apply 未输出 APPLY_PASS" >&2
      echo "[$(date -Iseconds)] svc=$svc result=NO_PASS_MARKER" >> "$AUDIT_LOG"
      unset PROD_CUTOVER_APPROVER PROD_CUTOVER_OPERATOR PROD_CUTOVER_TICKET
      return 1
    fi
  else
    rc=$?
    echo "[FAIL] $svc apply 执行失败（rc=$rc）" >&2
    echo "[$(date -Iseconds)] svc=$svc result=FAIL rc=$rc" >> "$AUDIT_LOG"
    unset PROD_CUTOVER_APPROVER PROD_CUTOVER_OPERATOR PROD_CUTOVER_TICKET
    return 1
  fi
  # ---------- 7. 立即清理临时放行变量 ----------
  unset PROD_CUTOVER_APPROVER PROD_CUTOVER_OPERATOR PROD_CUTOVER_TICKET
  echo "[INFO] 已清理临时放行变量 PROD_CUTOVER_*"
  echo ""
}

case "$SERVICE" in
  9000) run_apply 9000 scripts/migrate_9000_sqlite_to_postgres_cutover.py "$SQLITE_9000" "$DATABASE_URL" "$DB_9000" MAIN_TARGET_DATABASE_NAME || exit 1;;
  9100) run_apply 9100 scripts/migrate_9100_sqlite_to_postgres_cutover.py "$SQLITE_9100" "$RAG_DATABASE_URL" "$DB_9100" RAG_TARGET_DATABASE_NAME || exit 1;;
  both)
    run_apply 9000 scripts/migrate_9000_sqlite_to_postgres_cutover.py "$SQLITE_9000" "$DATABASE_URL" "$DB_9000" MAIN_TARGET_DATABASE_NAME || exit 1
    run_apply 9100 scripts/migrate_9100_sqlite_to_postgres_cutover.py "$SQLITE_9100" "$RAG_DATABASE_URL" "$DB_9100" RAG_TARGET_DATABASE_NAME || exit 1
    ;;
  *) echo "[FAIL] --service 仅支持 9000/9100/both" >&2; exit 2;;
esac

echo "==================== apply 审计摘要 ===================="
echo "审计日志：$AUDIT_LOG（不含密码，仅时间/执行人/库名/结果）"
grep -E "svc=|result=" "$AUDIT_LOG" | sed 's/^/  /'
echo ""
echo "APPLY_ALL_DONE"
