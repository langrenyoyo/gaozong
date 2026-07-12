"""Phase 8-A PostgreSQL 日报冒烟安全合同测试（Task 10 Step 2）。

复用 Phase 7-FIX2 已验证的安全规则，验证：
- SMOKE_DATABASE_URL 安全校验（导入真实 smoke 脚本的 _validate_smoke_url，不复制实现）；
- 脚本包含迁移前 preflight、升级/降级/再升级、唯一业务键并发、残留清理；
- 没有显式 --allow-destructive-migration-cycle 时拒绝破坏性迁移循环；
- downgrade 前必须有空白基线 gate。

不连接真实数据库。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SMOKE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke_phase8_postgres_daily_reports.py"


def _load_smoke_module():
    """通过 importlib 加载真实 smoke 脚本，验证合同对象是其真实实现而非副本。"""
    spec = importlib.util.spec_from_file_location("_smoke_phase8a_real", _SMOKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_smoke = _load_smoke_module()
_validate_smoke_url = _smoke._validate_smoke_url


def _script_source() -> str:
    return _SMOKE_SCRIPT.read_text(encoding="utf-8")


# ========== URL 安全校验（导入真实实现）==========

class TestSmokeDatabaseUrlValidation:

    def test_missing_url_returns_blocked(self, monkeypatch):
        monkeypatch.delenv("SMOKE_DATABASE_URL", raising=False)
        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "missing" in result["reason"].lower()

    def test_non_postgresql_scheme_rejected(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL", "sqlite:///test.db")
        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "scheme" in result["reason"].lower()

    def test_non_whitelist_host_rejected(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@evil.internal:5432/db_test")
        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "host" in result["reason"].lower()

    def test_database_not_test_or_staging_rejected(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost:5432/auto_wechat_prod")
        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "database" in result["reason"].lower()

    def test_database_ending_with_test_accepted(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost:5432/auto_wechat_test")
        assert _validate_smoke_url()["valid"] is True

    def test_database_ending_with_staging_accepted(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_staging")
        assert _validate_smoke_url()["valid"] is True

    def test_docker_service_name_accepted(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@postgres:5432/db_test")
        assert _validate_smoke_url()["valid"] is True

    def test_password_not_leaked_in_result(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:secret123@localhost:5432/db_test")
        result = _validate_smoke_url()
        assert "secret123" not in str(result)

    def test_query_param_overriding_host_rejected(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost/auto_wechat_test?host=prod&dbname=prod")
        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "query" in result["reason"].lower() or "fragment" in result["reason"].lower()

    def test_fragment_rejected(self, monkeypatch):
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost:5432/db_test#frag")
        result = _validate_smoke_url()
        assert result["valid"] is False

    def test_no_real_connection_in_validator(self, monkeypatch):
        """_validate_smoke_url 不创建 engine 或连接。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost:5432/db_test")
        from unittest.mock import patch
        with patch("sqlalchemy.create_engine") as mock_create:
            result = _validate_smoke_url()
            mock_create.assert_not_called()
        assert result["valid"] is True


# ========== 脚本结构合同（读真实源码）==========

class TestSmokeScriptStructure:

    def test_script_contains_preflight(self):
        src = _script_source()
        assert "preflight_postgres" in src, "脚本必须复用迁移前 preflight"

    def test_script_contains_upgrade_downgrade_upgrade_cycle(self):
        src = _script_source()
        assert '"upgrade"' in src or "'upgrade'" in src
        assert '"downgrade"' in src or "'downgrade'" in src
        # 降级目标必须显式
        assert "0008" in src

    def test_script_contains_concurrent_unique_key_check(self):
        src = _script_source()
        assert "Barrier" in src or "ThreadPoolExecutor" in src, "脚本必须含唯一业务键并发检查"
        assert "ClaimConflictError" in src

    def test_script_contains_residue_cleanup_verification(self):
        src = _script_source()
        assert "residue" in src.lower() or "残留" in src, "脚本必须验证清理残留为 0"
        assert "delete" in src.lower()

    def test_script_requires_allow_destructive_flag(self):
        """没有 --allow-destructive-migration-cycle 时拒绝破坏性循环。"""
        src = _script_source()
        assert "--allow-destructive-migration-cycle" in src

    def test_script_has_clean_baseline_gate_before_downgrade(self):
        """downgrade 前必须有空白基线 gate（拒绝 _RUN_ID 之外业务行）。"""
        src = _script_source()
        assert "_business_row_count" in src or "基线" in src, "脚本必须 downgrade 前校验空白基线"

    def test_script_uses_safe_subprocess_for_alembic(self):
        """alembic 通过子进程调用，DATABASE_URL 只在子进程注入。"""
        src = _script_source()
        assert "subprocess" in src
        assert "DATABASE_URL" in src


# ========== 破坏性确认 gate（不连 DB）==========

class TestAllowFlagGate:

    def test_main_without_allow_flag_returns_1(self, monkeypatch):
        """有效 URL 但无 --allow 时返回 1，不执行破坏性迁移循环。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://u:p@localhost:5432/db_test")
        rc = _smoke.main([])
        assert rc == 1

    def test_main_missing_url_returns_1(self, monkeypatch):
        monkeypatch.delenv("SMOKE_DATABASE_URL", raising=False)
        rc = _smoke.main(["--allow-destructive-migration-cycle"])
        assert rc == 1
