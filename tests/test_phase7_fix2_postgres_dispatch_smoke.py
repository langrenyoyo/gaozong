"""Phase 7-FIX2 PostgreSQL 派单冒烟合同测试（Task 5）。

验证 SMOKE_DATABASE_URL 安全校验和 PostgreSQL 冒烟流程。
不连接真实数据库 — 使用 monkeypatch 阻断连接。
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock


# ========== URL 安全校验 ==========


class TestSmokeDatabaseUrlValidation:
    """SMOKE_DATABASE_URL 安全校验合同测试。"""

    def test_missing_url_returns_blocked(self, monkeypatch):
        """缺少 SMOKE_DATABASE_URL 时脚本拒绝执行。"""
        monkeypatch.delenv("SMOKE_DATABASE_URL", raising=False)

        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "missing" in result["reason"].lower()

    def test_non_postgresql_scheme_rejected(self, monkeypatch):
        """非 postgresql+psycopg scheme 被拒绝。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL", "sqlite:///test.db")

        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "scheme" in result["reason"].lower()

    def test_non_whitelist_host_rejected(self, monkeypatch):
        """非白名单 host 被拒绝。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@evil-host.com:5432/prod_db")

        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "host" in result["reason"].lower()

    def test_database_not_test_or_staging_rejected(self, monkeypatch):
        """database 名不以 _test 或 _staging 结尾被拒绝。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@localhost:5432/production_db")

        result = _validate_smoke_url()
        assert result["valid"] is False
        assert "database" in result["reason"].lower()

    def test_database_ending_with_test_accepted(self, monkeypatch):
        """database 名以 _test 结尾被接受。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@localhost:5432/auto_wechat_test")

        result = _validate_smoke_url()
        assert result["valid"] is True

    def test_database_ending_with_staging_accepted(self, monkeypatch):
        """database 名以 _staging 结尾被接受。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@127.0.0.1:5432/auto_wechat_staging")

        result = _validate_smoke_url()
        assert result["valid"] is True

    def test_localhost_accepted(self, monkeypatch):
        """localhost host 被接受。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@localhost:5432/db_test")

        result = _validate_smoke_url()
        assert result["valid"] is True

    def test_docker_service_name_accepted(self, monkeypatch):
        """Docker service name host 被接受。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@postgres:5432/db_test")

        result = _validate_smoke_url()
        assert result["valid"] is True

    def test_auto_wechat_postgres_dev_accepted(self, monkeypatch):
        """auto-wechat-postgres-dev host 被接受。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@auto-wechat-postgres-dev:5432/db_test")

        result = _validate_smoke_url()
        assert result["valid"] is True

    def test_password_not_leaked_in_result(self, monkeypatch):
        """密码不泄露在校验结果中。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:secret123@localhost:5432/db_test")

        result = _validate_smoke_url()
        assert "secret123" not in str(result)

    def test_no_real_connection_made(self, monkeypatch):
        """单元测试不连接真实数据库。"""
        monkeypatch.setenv("SMOKE_DATABASE_URL",
                           "postgresql+psycopg://user:pass@localhost:5432/db_test")

        # 验证 _validate_smoke_url 不创建 engine 或连接
        with patch("sqlalchemy.create_engine") as mock_create:
            result = _validate_smoke_url()
            mock_create.assert_not_called()

        assert result["valid"] is True

    def test_no_module_level_env_pollution(self):
        """合约测试文件本身不在模块导入阶段修改 os.environ。"""
        # 用 AST 检查模块级赋值，避免字符串自引用误判
        import ast
        import inspect
        own_source = inspect.getsource(sys.modules[__name__])
        tree = ast.parse(own_source)
        violators = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.value, ast.Attribute)
                            and isinstance(target.value.value, ast.Name)
                            and target.value.value.id == "os"
                            and target.value.attr == "environ"):
                        violators.append(ast.dump(target))
        assert violators == [], f"发现模块级 os.environ 赋值: {violators}"


# ========== 导入真实冒烟脚本的 _validate_smoke_url ==========

def _load_real_smoke_validator():
    """Phase 7-FIX2 Task 8：通过 importlib 加载真实冒烟脚本，
    确保合约测试验证的是 scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
    的真实实现，而非本文件内复制的副本。
    """
    import importlib.util
    from pathlib import Path

    smoke_path = Path(__file__).resolve().parent.parent / "scripts" / "smoke_phase7_fix2_postgres_dispatch_gate.py"
    spec = importlib.util.spec_from_file_location("_smoke_phase7_fix2_real", smoke_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._validate_smoke_url


_validate_smoke_url = _load_real_smoke_validator()
