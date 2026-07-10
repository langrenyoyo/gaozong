#!/bin/bash
# 生产 PostgreSQL 切换前备份（SQLite + PG + .env）。
# P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 / §6。
#
# 备份项：9000 SQLite / 9100 metadata SQLite / 向量副本 / 9000 PG / 9100 PG / .env。
# 记录 MANIFEST（时间/路径/大小/SHA-256/pg_dump 退出码）。关键备份失败返回非零。
# backups/ 已被 .gitignore 排除，禁止提交。
#
# 用法：
#   bash scripts/production_pg_backup.sh [--project-root DIR] [--env-file .env]
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
ENV_FILE=".env"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups/cutover-$TS}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --help|-h) sed -n '2,11p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

cd "$PROJECT_ROOT"

# 加载 .env
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi

MANIFEST="$BACKUP_DIR/MANIFEST.txt"
mkdir -p "$BACKUP_DIR"
{
  echo "cutover backup manifest"
  echo "time     : $(date -Iseconds)"
  echo "host     : $(hostname)"
  echo "git      : $(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  echo "operator : ${PROD_CUTOVER_OPERATOR:-[宝塔现场确认]}"
  echo "ticket   : ${PROD_CUTOVER_TICKET:-[宝塔现场确认]}"
  echo "================================================"
} > "$MANIFEST"

sha256_of() { (command -v sha256sum >/dev/null 2>&1 && sha256sum "$1" || shasum -a 256 "$1") | awk '{print $1}'; }

# 文件备份通用（SQLite/.env）：name path
backup_file() {
  local name="$1" path="$2"
  if [[ -z "$path" ]]; then
    echo "[SKIP] $name（路径为空，跳过）" | tee -a "$MANIFEST"
    return 0
  fi
  if [[ ! -f "$path" ]]; then
    echo "[WARN] $name 源不存在：$path" | tee -a "$MANIFEST"
    # SQLite 源缺失是关键失败（无法回滚）；.env 缺失也是关键失败
    [[ "$name" == "env" || "$name" == *SQLite* ]] && return 1 || return 0
  fi
  local dest="$BACKUP_DIR/$(basename "$path").${name}.bak"
  cp -p "$path" "$dest"
  local size; size=$(wc -c < "$dest")
  local sha; sha=$(sha256_of "$dest")
  printf "%-22s %s\n  dest: %s\n  size: %s bytes\n  sha256: %s\n" "$name" "$path" "$dest" "$size" "$sha" | tee -a "$MANIFEST"
  echo "[OK]   $name → $dest ($size bytes)"
}

echo "==================== cutover 备份 ===================="
echo "BACKUP_DIR: $BACKUP_DIR"
echo ""

# ---------- SQLite 源 ----------
SQLITE_9000="${SQLITE_9000_PATH:-docker-data/auto_wechat_9000/auto_wechat.db}"
SQLITE_9100="${SQLITE_9100_PATH:-docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db}"
VECTOR_SQLITE="${VECTOR_SQLITE_PATH:-}"

backup_file "9000-SQLite-metadata" "$SQLITE_9000"
backup_file "9100-SQLite-metadata" "$SQLITE_9100"
# 向量副本：RAG_VECTOR_BACKEND=sqlite 时向量在 PG metadata（无独立文件）；如有独立向量文件单独备份
backup_file "9100-SQLite-vector"   "$VECTOR_SQLITE"

# ---------- .env ----------
backup_file "env" "$ENV_FILE"
echo "[提示] .env 含真实密码，建议加密后存外部安全存储（如宝塔加密备份/OSS 加密桶）" | tee -a "$MANIFEST"

# ---------- PG database ----------
COMPOSE_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD="docker-compose"; fi
PG_CONTAINER="${PG_CONTAINER:-postgres}"

pg_dump_db() {
  local db="$1" out="$BACKUP_DIR/pg-${db}.dump"
  echo "[INFO] pg_dump database=$db ..."
  local rc=0
  if [[ -n "$COMPOSE_CMD" ]] && $COMPOSE_CMD ps -q "$PG_CONTAINER" >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T "$PG_CONTAINER" pg_dump -U "${PG_USER:-auto_wechat}" -Fc "$db" > "$out" || rc=$?
  else
    PGPASSWORD="${PG_PASSWORD:-}" pg_dump -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "${PG_USER:-auto_wechat}" -Fc "$db" > "$out" || rc=$?
  fi
  local size; size=$(wc -c < "$out" 2>/dev/null || echo 0)
  local sha; sha=$(sha256_of "$out" 2>/dev/null || echo "?")
  printf "%-22s\n  dest: %s\n  size: %s bytes\n  sha256: %s\n  pg_dump rc: %s\n" "PG-$db" "$out" "$size" "$sha" "$rc" | tee -a "$MANIFEST"
  if [[ $rc -ne 0 ]]; then
    echo "[FAIL] pg_dump $db 失败（rc=$rc）"
    return 1
  fi
  echo "[OK]   PG-$db → $out ($size bytes, rc=0)"
}

DB_9000=$(echo "${DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
DB_9100=$(echo "${RAG_DATABASE_URL:-}" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
if [[ -n "$DB_9000" ]]; then pg_dump_db "$DB_9000" || exit 1; else echo "[WARN] DATABASE_URL 为空，跳过 9000 PG 备份" | tee -a "$MANIFEST"; fi
if [[ -n "$DB_9100" ]]; then pg_dump_db "$DB_9100" || exit 1; else echo "[WARN] RAG_DATABASE_URL 为空，跳过 9100 PG 备份" | tee -a "$MANIFEST"; fi

echo ""
echo "==================== 备份汇总 ===================="
echo "MANIFEST: $MANIFEST"
cat "$MANIFEST" | tail -40
echo ""
echo "[提示] 备份目录 $BACKUP_DIR 含敏感数据（.env/PG dump），禁止提交 Git，建议加密外部存储。"
echo "BACKUP_DONE"
