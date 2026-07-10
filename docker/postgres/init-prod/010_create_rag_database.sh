#!/bin/bash
# 生产 postgres 初始化：创建 9100 RAG metadata 第二个 database（方案 A：一个 PG 实例两个 database）。
#
# docker-entrypoint-initdb.d 只在数据卷为空（首次启动）时执行；已有数据卷时此脚本不运行，
# 需在 Runbook 手动 createdb 或重建数据卷。幂等：库已存在则跳过，重复执行安全。
#
# 生产策略：单应用 role（${POSTGRES_USER}，即 compose POSTGRES_USER）同时 owner 两个 database，
# 不为 9100 单独建 role（与 dev 的 001_create_databases.sql 独立 role 策略不同）。
#
# 重要：psql/createdb 必须显式 --username "$POSTGRES_USER"，
# 否则默认用 OS user（postgres），而 POSTGRES_USER 非 postgres 时会 FATAL: role "postgres" does not exist，
# 且部分 entrypoint 版本对 init 脚本失败容错，会出现「postgres healthy 但第二 database 静默未建」。
# entrypoint 保证 POSTGRES_USER 已设置；--dbname postgres 连系统库做存在性检查。
# createdb 失败时 set -e 让脚本退出非零，entrypoint 终止启动，避免静默失败。
set -e

DB_NAME="xg_douyin_ai_cs"
DB_USER="${POSTGRES_USER:-${PGUSER:-auto_wechat}}"

if psql --username "$DB_USER" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
  echo "[init-prod] database ${DB_NAME} 已存在，跳过创建"
else
  echo "[init-prod] 创建 database ${DB_NAME}（owner=${DB_USER}）"
  createdb --username "$DB_USER" --owner "$DB_USER" "$DB_NAME"
fi
