"""init-prod/010 非默认 POSTGRES_USER 修复的 focused test。

P3-E-9100-STAGING-DRILL-FASTTRACK-1 / 4.1。

背景：init-prod/010 初版 psql/createdb 未显式 --username，默认用 OS user postgres，
而 POSTGRES_USER 非 postgres 时会 FATAL: role "postgres" does not exist，
且部分 entrypoint 版本对 init 脚本失败容错，会出现「postgres healthy 但第二 database 静默未建」。

修复要求：
1. psql/createdb 显式 --username "$POSTGRES_USER"（不依赖 OS user postgres）；
2. createdb 失败 set -e 退出非零，避免静默失败。

运行时真实验证见 scripts/smoke_init_prod_non_default_postgres_user.sh（临时 PG 容器）。
"""

from __future__ import annotations

from pathlib import Path

INIT_PROD_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docker"
    / "postgres"
    / "init-prod"
    / "010_create_rag_database.sh"
)
INIT_STAGING_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docker"
    / "postgres"
    / "init-staging"
    / "010_create_rag_database.sh"
)


def test_init_prod_script_exists() -> None:
    """脚本存在，供后续断言读取。"""
    assert INIT_PROD_SCRIPT.is_file()


def test_init_prod_uses_explicit_postgres_user_not_os_user() -> None:
    """psql/createdb 必须显式 --username，不依赖 OS user postgres。"""
    content = INIT_PROD_SCRIPT.read_text(encoding="utf-8")
    # DB_USER 解析 POSTGRES_USER（entrypoint 保证），fallback PGUSER
    assert "POSTGRES_USER" in content
    # psql 和 createdb 都要显式 --username "$DB_USER"
    assert 'psql --username "$DB_USER" --dbname postgres' in content
    assert 'createdb --username "$DB_USER" --owner "$DB_USER"' in content
    # 不应残留旧版裸调用（无 --username → 默认 OS user postgres）
    assert "psql -tAc" not in content
    assert 'createdb --owner "${DB_OWNER}"' not in content


def test_init_prod_has_set_e_to_avoid_silent_failure() -> None:
    """createdb 失败时 set -e 让脚本退出非零，避免静默失败。"""
    content = INIT_PROD_SCRIPT.read_text(encoding="utf-8")
    assert "set -e" in content


def test_init_prod_pattern_matches_staging_verified_version() -> None:
    """init-prod 与 init-staging（已在 staging bootstrap 实测通过）使用相同 --username 模式。

    init-staging 的修复在 P3-E-9100-STAGING-ENV-BOOTSTRAP-1 已 down -v 重建实测：
    role postgres FATAL 消失，双库创建成功。init-prod 同款修复，保证一致性。
    """
    prod = INIT_PROD_SCRIPT.read_text(encoding="utf-8")
    staging = INIT_STAGING_SCRIPT.read_text(encoding="utf-8")
    assert '--username "$DB_USER" --dbname postgres' in prod
    assert '--username "$DB_USER" --dbname postgres' in staging
    assert 'createdb --username "$DB_USER" --owner "$DB_USER"' in prod
    assert 'createdb --username "$DB_USER" --owner "$DB_USER"' in staging
