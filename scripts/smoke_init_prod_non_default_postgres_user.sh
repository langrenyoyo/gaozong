#!/bin/bash
# init-prod/010 非默认 POSTGRES_USER 可重复 smoke。
# P3-E-9100-STAGING-DRILL-FASTTRACK-1 / 4.1。
#
# 用临时 PG 容器（POSTGRES_USER=mytestuser，非默认 postgres）挂载 init-prod 脚本，
# 验证第二 database xg_douyin_ai_cs 被正确创建 + 无 role postgres FATAL（静默失败）。
# 可重复：--rm 容器，每次干净起停；不触碰 dev/staging/production 任何现有 PG。
#
# 用法：bash scripts/smoke_init_prod_non_default_postgres_user.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INIT_DIR="$SCRIPT_DIR/docker/postgres/init-prod"
# Windows Git Bash 下转 Windows 路径（正斜杠），避免 -v 的 host 路径被 MSYS 误转
# 导致挂载空目录（entrypoint "ignoring /docker-entrypoint-initdb.d/*"，init 脚本不执行）；
# Linux/CI 无 cygpath 时用原路径。
if command -v cygpath >/dev/null 2>&1; then
  INIT_DIR_MOUNT=$(cygpath -m "$INIT_DIR")
else
  INIT_DIR_MOUNT="$INIT_DIR"
fi
CONTAINER="init-prod-smoke-$$"
POSTGRES_USER="mytestuser"   # 故意非默认 postgres，复现 role postgres FATAL 场景
POSTGRES_PASSWORD="smoke_pw_2026"
POSTGRES_DB="mytestdb"

echo "[smoke] 启动临时 PG 容器（POSTGRES_USER=$POSTGRES_USER，非默认 postgres）..."
docker run -d --rm --name "$CONTAINER" \
  -e POSTGRES_USER="$POSTGRES_USER" \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -e POSTGRES_DB="$POSTGRES_DB" \
  --health-cmd "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB" \
  --health-interval=3s \
  --health-timeout=3s \
  --health-start-period=10s \
  --health-retries=30 \
  -v "$INIT_DIR_MOUNT:/docker-entrypoint-initdb.d:ro" \
  postgres:16-alpine >/dev/null

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[smoke] 等 postgres healthy..."
status=""
for i in $(seq 1 30); do
  status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "")
  if [ "$status" = "healthy" ]; then
    echo "[smoke] healthy (loop $i)"
    break
  fi
  sleep 2
done

if [ "$status" != "healthy" ]; then
  echo "[smoke FAIL] postgres 未 healthy，init 脚本可能失败"
  docker logs "$CONTAINER" 2>&1 | tail -25
  exit 1
fi

echo "[smoke] 验证第二库 xg_douyin_ai_cs 由 $POSTGRES_USER 创建..."
if docker exec "$CONTAINER" psql -U "$POSTGRES_USER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='xg_douyin_ai_cs'" | grep -q 1; then
  echo "[smoke OK] 第二库 xg_douyin_ai_cs 存在"
else
  echo "[smoke FAIL] 第二库未创建（静默失败）"
  docker logs "$CONTAINER" 2>&1 | grep -iE "FATAL|init-prod|createdb|error" | head -15
  exit 1
fi

echo "[smoke] 确认无 role postgres FATAL（旧 bug 复现判据）..."
if docker logs "$CONTAINER" 2>&1 | grep -q 'role "postgres" does not exist'; then
  echo "[smoke FAIL] 仍有 role postgres FATAL（脚本未显式 --username）"
  docker logs "$CONTAINER" 2>&1 | grep 'role "postgres"' | head -3
  exit 1
fi
echo "[smoke OK] 无 role postgres FATAL"

echo "[smoke] 确认第二库 owner = $POSTGRES_USER..."
owner=$(docker exec "$CONTAINER" psql -U "$POSTGRES_USER" -d postgres -tAc \
  "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datname='xg_douyin_ai_cs';")
echo "[smoke] owner=$owner"
[ "$owner" = "$POSTGRES_USER" ] || { echo "[smoke FAIL] owner 不符"; exit 1; }

echo ""
echo "[smoke PASS] init-prod/010 非默认 POSTGRES_USER 验证通过（$POSTGRES_USER 成功创建第二库，无静默失败）"
