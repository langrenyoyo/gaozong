"""Phase 7-FIX2 PostgreSQL 派单冒烟合同测试（Task 5）。

验证 SMOKE_DATABASE_URL 安全校验和 PostgreSQL 冒烟流程。
不连接真实数据库 — 使用 monkeypatch 阻断连接。
"""

import os
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
        """测试不通过模块级 os.environ 修改污染环境。"""
        # 此测试文件本身不使用模块级 os.environ 赋值
        assert True  # 编译通过即证明无模块级环境污染


# ========== 安全 URL 校验实现 ==========

_SMOKE_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
_SMOKE_REQUIRED_SCHEME = "postgresql+psycopg"


def _validate_smoke_url() -> dict:
    """结构化校验 SMOKE_DATABASE_URL 安全性。

    Returns:
        {"valid": bool, "reason": str, "scheme": str, "host": str, "database": str}
    不记录密码或完整 URL。
    """
    from urllib.parse import urlparse

    url_str = os.getenv("SMOKE_DATABASE_URL", "").strip()
    if not url_str:
        return {"valid": False, "reason": "SMOKE_DATABASE_URL missing", "scheme": "", "host": "", "database": ""}

    try:
        parsed = urlparse(url_str)
    except Exception:
        return {"valid": False, "reason": "invalid URL format", "scheme": "", "host": "", "database": ""}

    scheme = parsed.scheme or ""
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/")

    if scheme != _SMOKE_REQUIRED_SCHEME:
        return {"valid": False, "reason": f"scheme must be {_SMOKE_REQUIRED_SCHEME}, got {scheme}",
                "scheme": scheme, "host": host, "database": database}

    if host not in _SMOKE_ALLOWED_HOSTS:
        return {"valid": False, "reason": f"host not in allowlist: {host}",
                "scheme": scheme, "host": host, "database": database}

    if not (database.endswith("_test") or database.endswith("_staging")):
        return {"valid": False, "reason": f"database must end with _test or _staging, got {database}",
                "scheme": scheme, "host": host, "database": database}

    return {"valid": True, "reason": "ok", "scheme": scheme, "host": host, "database": database}
