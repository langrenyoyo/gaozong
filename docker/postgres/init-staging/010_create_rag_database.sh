#!/bin/bash
# staging postgres 初始化：创建 9100 RAG metadata 第二个 database（带 _staging 后缀，与 dev/生产隔离）。
#
# docker-entrypoint-initdb.d 只在数据卷为空（首次启动）时执行；已有数据卷时此脚本不运行，
# 需在 Runbook 手动 createdb 或重建数据卷。幂等：库已存在则跳过，重复执行安全。
#
# staging 策略：与 init-prod/010 同结构，仅 database 名带 _staging 后缀，
# 配合独立 PG 实例（docker-data-staging/postgres）+ 独立 compose project 实现双重隔离。
# 第一个 database（auto_wechat_staging）由 postgres 镜像 POSTGRES_DB 自动创建，
# 本脚本只建第二个（xg_douyin_ai_cs_staging）。
#
# 重要：psql/createdb 必须显式 --username "$POSTGRES_USER"，
# 否则默认用 OS user（postgres），而 POSTGRES_USER 非 postgres 时会 FATAL: role "postgres" does not exist。
# entrypoint 保证 POSTGRES_USER 已设置；--dbname postgres 连系统库做存在性检查。
set -e

DB_NAME="xg_douyin_ai_cs_staging"
DB_USER="${POSTGRES_USER:-${PGUSER:-auto_wechat_staging}}"

if psql --username "$DB_USER" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
  echo "[init-staging] database ${DB_NAME} 已存在，跳过创建"
else
  echo "[init-staging] 创建 database ${DB_NAME}（owner=${DB_USER}）"
  createdb --username "$DB_USER" --owner "$DB_USER" "$DB_NAME"
fi
