"""G0 P0-1：生产环境鉴权配置 fail-closed 测试（T1~T7）。

验收（G0-A1~A3）：
  G0-A1 production + NEWCAR_AUTH_ENABLED missing/false → FAIL CLOSED
  G0-A2 production + NEWCAR_AUTH_MOCK_ENABLED=true     → FAIL CLOSED
  G0-A3 development + mock                             → PASS（原行为保持）

C1 双防线（APPROVED_WITH_4_CONSTRAINTS）：
  防线1 = config.validate_production_auth_config()（app/main.py on_startup 调用，配置非法则服务拒绝启动）
  防线2 = NewCarProjectAuthClient.from_env()（dependencies._client() 每次请求都调用 → 请求路径 fail-closed）
  兜底   = build_mock_context() 内 production 拒绝（production 永远不能构造 mock 上下文）

实现约束：不做 import-time raise（避免阻断 alembic / 维护 / 诊断脚本），
因此本文件全部显式调用 validator / from_env，不依赖 import 副作用。

T7（development + mock → /auth/me 200 mock）语义由 test_t5_development_mock_preserved 覆盖：
development 下 from_env 返回 auth_enabled=False + build_mock_context() 为 mock 上下文，
即 /auth/me 依赖链（get_request_context_* → build_mock_context）在 development 保持 200 mock。
"""

from __future__ import annotations

import pytest

from app import config
from app.auth.newcar_client import NewCarProjectAuthClient


def _set_prod(monkeypatch, *, enabled: bool, mock: bool) -> None:
    """把 config 模块切到 production + 指定 auth 配置（只 monkeypatch 模块属性，不污染 os.environ）。"""
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "NEWCAR_AUTH_ENABLED", enabled)
    monkeypatch.setattr(config, "NEWCAR_AUTH_MOCK_ENABLED", mock)


# ---------- 防线1：validate_production_auth_config（startup 调用） ----------


def test_t1_production_auth_missing_fail_closed(monkeypatch):
    """G0-A1：production + NEWCAR_AUTH_ENABLED 缺省(false) → FAIL CLOSED。"""
    _set_prod(monkeypatch, enabled=False, mock=True)
    with pytest.raises(RuntimeError, match="NEWCAR_AUTH_ENABLED 必须为 true"):
        config.validate_production_auth_config()


def test_t2_production_mock_true_fail_closed(monkeypatch):
    """G0-A2：production + NEWCAR_AUTH_MOCK_ENABLED=true → FAIL CLOSED。"""
    _set_prod(monkeypatch, enabled=True, mock=True)
    with pytest.raises(RuntimeError, match="NEWCAR_AUTH_MOCK_ENABLED 必须为 false"):
        config.validate_production_auth_config()


def test_t2b_production_defaults_both_reported(monkeypatch):
    """production + 缺省默认组合（enabled=false + mock=true）→ 同时报两项。"""
    _set_prod(monkeypatch, enabled=False, mock=True)
    with pytest.raises(RuntimeError) as excinfo:
        config.validate_production_auth_config()
    msg = str(excinfo.value)
    assert "NEWCAR_AUTH_ENABLED 必须为 true" in msg
    assert "NEWCAR_AUTH_MOCK_ENABLED 必须为 false" in msg


def test_t3_production_correct_config_pass(monkeypatch):
    """production + enabled=true + mock=false → PASS（合法生产配置不拦截）。"""
    _set_prod(monkeypatch, enabled=True, mock=False)
    config.validate_production_auth_config()  # 不抛即 PASS


# ---------- G0-A3：development 行为保持 ----------


def test_t5_development_mock_preserved(monkeypatch):
    """development + 缺省(mock 开发态) → PASS，mock 行为保持（T7 语义）。"""
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "NEWCAR_AUTH_ENABLED", False)
    monkeypatch.setattr(config, "NEWCAR_AUTH_MOCK_ENABLED", True)
    config.validate_production_auth_config()  # 不抛
    client = NewCarProjectAuthClient.from_env()
    assert client.auth_enabled is False
    assert client.mock_enabled is True
    # /auth/me 依赖链在 development 下返回 mock 上下文（is_mock_auth=True）
    assert client.build_mock_context().is_mock_auth() is True


# ---------- 防线2：from_env（请求路径 fail-closed） ----------


def test_t6_from_env_production_invalid_fail_closed(monkeypatch):
    """production + 非法 → from_env() raise；dependencies._client() 每次请求都调 from_env，
    因此请求路径（含 /auth/me）fail-closed，绝不返回 HTTP200 mock。"""
    _set_prod(monkeypatch, enabled=False, mock=True)
    with pytest.raises(RuntimeError, match="生产环境鉴权配置非法"):
        NewCarProjectAuthClient.from_env()


def test_t6b_from_env_production_correct_config_pass(monkeypatch):
    """production + 合法 → from_env() 正常构造客户端。

    validate 读 config 模块属性（setattr），from_env 构造读 os.environ（os.getenv），
    两者需同步为合法值。
    """
    _set_prod(monkeypatch, enabled=True, mock=False)
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    client = NewCarProjectAuthClient.from_env()
    assert client.auth_enabled is True
    assert client.mock_enabled is False


# ---------- 兜底：build_mock_context production 拒绝 ----------


def test_t6c_build_mock_context_production_rejected(monkeypatch):
    """production 下即使绕过 from_env 手工构造 client，build_mock_context 也拒绝
    （production 永远不能构造 mock 上下文）。"""
    _set_prod(monkeypatch, enabled=False, mock=True)
    client = NewCarProjectAuthClient(auth_enabled=False, mock_enabled=True)
    with pytest.raises(RuntimeError, match="生产环境禁止构造 mock"):
        client.build_mock_context()
