-- P2-D 本地开发 PostgreSQL 初始化脚本。
-- 仅创建未来 9000 / 9100 使用的两个 database，不创建业务表，不执行迁移。

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

SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec

SELECT 'CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'xg_douyin_ai_cs')\gexec
