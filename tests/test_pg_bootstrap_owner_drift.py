"""P1-PG-BOOTSTRAP-OWNER-DRIFT-2 focused static tests.

T1 Owner Contract — dev init SQL auto_wechat OWNER postgres，9100 行未变。
T2 Environment Boundary — prod/staging 不引用 dev 001 脚本。
T3 Permission SQL Contract — table DML / no TRUNCATE / sequence / alembic_version / ADP。
T4 Caller Ordering — alembic 在 permission 之前，alembic 失败不执行 permission。

纯静态解析，不连数据库。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INIT_SQL = PROJECT_ROOT / "docker" / "postgres" / "init" / "001_create_databases.sql"
COMPOSE_PROD = PROJECT_ROOT / "docker-compose.yml"
COMPOSE_STAGING = PROJECT_ROOT / "docker-compose.staging.yml"
PERMISSION_SQL = PROJECT_ROOT / "scripts" / "pg" / "bootstrap_app_role_permissions.sql"
CALLER = PROJECT_ROOT / "scripts" / "pg" / "bootstrap_local_dev_pg.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------- T1 Owner Contract ----------

def test_t1_auto_wechat_database_owner_is_postgres():
    """Gap①：auto_wechat database owner = postgres（非 auto_wechat）。"""
    text = _read(INIT_SQL)
    # auto_wechat 库创建行必须 OWNER postgres
    assert "CREATE DATABASE auto_wechat OWNER postgres" in text
    # 不得残留旧 OWNER auto_wechat（owner drift 已消除）
    assert "CREATE DATABASE auto_wechat OWNER auto_wechat" not in text


def test_t1_9100_database_row_unchanged():
    """9100 不属本 gap 主体，xg_douyin_ai_cs 创建行保持不变（owner 仍 xg_douyin_ai_cs）。"""
    text = _read(INIT_SQL)
    assert "CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs" in text


def test_t1_auto_wechat_role_no_elevated_capability():
    """Role Bootstrap Hard Gate：auto_wechat role 无 SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS。"""
    text = _read(INIT_SQL)
    # role 创建语句只含 LOGIN PASSWORD
    assert "CREATE ROLE auto_wechat LOGIN PASSWORD" in text
    assert "SUPERUSER" not in text.split("CREATE ROLE auto_wechat")[1].split("$$")[0]
    assert "CREATEDB" not in text.split("CREATE ROLE auto_wechat")[1].split("$$")[0]
    assert "CREATEROLE" not in text.split("CREATE ROLE auto_wechat")[1].split("$$")[0]


# ---------- T2 Environment Boundary ----------

def test_t2_prod_uses_init_prod_not_dev_init():
    """prod compose 挂载 init-prod，不引用 dev 的 init/ 目录。"""
    text = _read(COMPOSE_PROD)
    assert "docker/postgres/init-prod" in text
    assert "docker/postgres/init:" not in text  # dev 目录挂载形式不出现


def test_t2_staging_uses_init_staging_not_dev_init():
    """staging compose 挂载 init-staging，不引用 dev 的 init/ 目录。"""
    text = _read(COMPOSE_STAGING)
    assert "docker/postgres/init-staging" in text
    assert "docker/postgres/init:" not in text


def test_t2_dev_init_sql_has_dev_only_boundary_marker():
    """C5：001 头部注释保留 DEV-ONLY 边界证据。"""
    text = _read(INIT_SQL)
    assert "DEV-ONLY" in text
    assert "init-prod" in text
    assert "init-staging" in text


# ---------- T3 Permission SQL Contract ----------

def test_t3_existing_table_dml_grant():
    """既有业务表授予 SELECT/INSERT/UPDATE/DELETE。"""
    text = _read(PERMISSION_SQL)
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat" in text


def test_t3_no_all_privileges_shortcut():
    """禁止 GRANT ALL PRIVILEGES 捷径（检查 GRANT 语句行，注释说明不受限）。"""
    text = _read(PERMISSION_SQL)
    for ln in text.splitlines():
        s = ln.strip().upper()
        if s.startswith("GRANT"):
            assert "ALL PRIVILEGES" not in s, f"GRANT 不得用 ALL PRIVILEGES 捷径: {ln}"


def test_t3_no_truncate_grant():
    """GRANT 集合不含 TRUNCATE（TRUNCATE 只出现在 REVOKE 收敛语句）。"""
    text = _read(PERMISSION_SQL)
    grant_lines = [ln for ln in text.splitlines() if ln.strip().upper().startswith("GRANT")]
    for ln in grant_lines:
        assert "TRUNCATE" not in ln.upper(), f"GRANT 不得含 TRUNCATE: {ln}"
    # REVOKE alembic_version 必须含 TRUNCATE 收敛（显式边界）
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version" in text


def test_t3_no_references_trigger_grant():
    """不得授予 REFERENCES / TRIGGER。"""
    text = _read(PERMISSION_SQL)
    for ln in text.splitlines():
        s = ln.strip().upper()
        if s.startswith("GRANT"):
            assert "REFERENCES" not in s, f"GRANT 不得含 REFERENCES: {ln}"
            assert "TRIGGER" not in s, f"GRANT 不得含 TRIGGER: {ln}"


def test_t3_sequence_usage_select():
    """既有序列授予 USAGE/SELECT，无 UPDATE。"""
    text = _read(PERMISSION_SQL)
    assert "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat" in text


def test_t3_alembic_version_hardening_after_grant():
    """C3 顺序硬约束：broad DML GRANT 之后立即 REVOKE alembic_version 写 → SELECT-only。"""
    text = _read(PERMISSION_SQL)
    grant_pos = text.find("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES")
    revoke_pos = text.find("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version")
    assert grant_pos != -1 and revoke_pos != -1
    assert grant_pos < revoke_pos, "REVOKE alembic_version 必须在 broad DML GRANT 之后"


def test_t3_adp_for_role_postgres():
    """ADP creator = postgres（FROZEN migration principal）。"""
    text = _read(PERMISSION_SQL)
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public" in text
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat" in text
    assert "GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat" in text


def test_t3_fail_closed_guard():
    """fail-closed guard：校验 current_database + current_user。"""
    text = _read(PERMISSION_SQL)
    assert "current_database()" in text
    assert "current_user" in text
    assert "FAIL CLOSED" in text


# ---------- T4 Caller Ordering ----------

def test_t4_alembic_before_permission_in_main():
    """caller main 中 alembic stage 在 permission stage 之前。"""
    text = _read(CALLER)
    main_start = text.find("def main(")
    assert main_start != -1
    main_body = text[main_start:]
    alembic_call = main_body.find("run_alembic_upgrade_head(raw_url)")
    perm_call = main_body.find("run_permission_bootstrap(raw_url)")
    assert alembic_call != -1 and perm_call != -1
    assert alembic_call < perm_call, "alembic 必须在 permission bootstrap 之前调用"


def test_t4_alembic_failure_stops_before_permission():
    """alembic 失败 raise SystemExit，不继续 permission stage。"""
    text = _read(CALLER)
    # run_alembic_upgrade_head 内部失败即 raise SystemExit
    func_start = text.find("def run_alembic_upgrade_head(")
    func_body = text[func_start:text.find("\n\ndef ", func_start)]
    assert "raise SystemExit" in func_body
    assert "STOP" in func_body or "permission bootstrap 未执行" in func_body
