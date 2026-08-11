-- P1-PG-BOOTSTRAP-OWNER-DRIFT-2 / Gap② 应用角色权限 bootstrap（post-Alembic，幂等）
-- 执行身份：postgres（migration/admin principal）
-- 目标库：auto_wechat
-- 目标 app principal：auto_wechat
-- 执行时机：alembic upgrade head 之后、应用启动之前
-- 不是 FastAPI runtime 职责；属 deployment/migration administration。
-- 幂等：GRANT/REVOKE/ALTER DEFAULT PRIVILEGES 可重复执行，无 error，最终 ACL/ADP 等价。
--
-- Contract（与 P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT §6/§7/§9 对齐）：
--   application principal auto_wechat:
--     DATABASE CONNECT = allowed / DATABASE CREATE = denied
--     public USAGE = allowed / public CREATE = denied
--     existing tables: SELECT/INSERT/UPDATE/DELETE（无 TRUNCATE/REFERENCES/TRIGGER）
--     existing sequences: USAGE/SELECT（无 UPDATE/setval）
--     alembic_version: SELECT-only（INSERT/UPDATE/DELETE/TRUNCATE = denied）
--     future tables: SELECT/INSERT/UPDATE/DELETE via ADP（无 TRUNCATE）
--     future sequences: USAGE/SELECT via ADP
--   不授予 database ownership / schema ownership / CREATE / ALL PRIVILEGES。

-- Fail-closed guard：必须在 auto_wechat 库以 postgres 执行。
-- 不满足则 RAISE 中止，事务回滚，无任何授权生效。
-- ponytail: ceiling — 只校验 current_database/current_user 两项，不引入权限框架。
DO $$
DECLARE
  _db text := current_database();
  _user text := current_user;
BEGIN
  IF _db <> 'auto_wechat' THEN
    RAISE EXCEPTION 'FAIL CLOSED: current_database()=%，必须为 auto_wechat', _db;
  END IF;
  IF _user <> 'postgres' THEN
    RAISE EXCEPTION 'FAIL CLOSED: current_user()=%，必须为 postgres（migration/admin principal）', _user;
  END IF;
END
$$;

-- Database / Schema contract
GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;

-- 既有业务表 DML（无 TRUNCATE/REFERENCES/TRIGGER，无 ALL PRIVILEGES）
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;

-- alembic_version 收敛（C3 顺序硬约束：broad DML GRANT 之后立即 REVOKE 写 → SELECT-only）。
-- broad GRANT 会把 alembic_version 也授予 DML，必须随后显式收敛写权限。
-- 若未来 alembic_version 被 DROP/recreate，重跑本脚本即重新收敛（recreation contract）。
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM auto_wechat;

-- 既有序列（USAGE+SELECT，无 UPDATE/setval，无 ALL PRIVILEGES）
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;

-- 未来对象 ADP（creator=postgres，FROZEN migration principal）。
-- ADP 只覆盖"新建"对象，不反向覆盖既有对象（既有对象由上方 ALL TABLES/SEQUENCES 显式 GRANT）。
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
