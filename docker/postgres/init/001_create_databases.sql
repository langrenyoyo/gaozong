-- P2-D 本地开发 PostgreSQL 初始化脚本。
-- 仅创建未来 9000 / 9100 使用的两个 database，不创建业务表，不执行迁移。
--
-- DEV-ONLY 边界证据（P1-PG-BOOTSTRAP-OWNER-DRIFT-2 / C5）：
-- 本脚本仅被 docker-compose.dev.yml:41 挂载到 /docker-entrypoint-initdb.d:ro。
-- production 使用 docker/postgres/init-prod/（docker-compose.yml:19）；
-- staging 使用 docker/postgres/init-staging/（docker-compose.staging.yml:37）。
-- 三个环境用各自独立 init 目录，不共享，不得把本脚本引入 staging/prod。

DO $$
BEGIN
    CREATE ROLE auto_wechat LOGIN PASSWORD 'change_me';
EXCEPTION WHEN duplicate_object THEN
    ALTER ROLE auto_wechat WITH LOGIN PASSWORD 'change_me';
END
$$;

DO $$
BEGIN
    CREATE ROLE xg_douyin_ai_cs LOGIN PASSWORD 'change_me';
EXCEPTION WHEN duplicate_object THEN
    ALTER ROLE xg_douyin_ai_cs WITH LOGIN PASSWORD 'change_me';
END
$$;

-- P1-PG-BOOTSTRAP-OWNER-DRIFT-2 / Gap①：owner 收敛为 migration principal postgres。
-- fresh bootstrap 即 owner=postgres，消除 application principal 持 database ownership
-- 的 blocker（隐式 pg_database_owner 成员 → public schema CREATE 泄漏 + ALTER/DROP DATABASE）。
-- 既存 permission（GRANT/ADP/REVOKE）由 post-Alembic 脚本
-- scripts/pg/bootstrap_app_role_permissions.sql 重建，不在 init 阶段（此时业务表不存在）。
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec

SELECT 'CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'xg_douyin_ai_cs')\gexec
