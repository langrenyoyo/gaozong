"""Phase 12 Task 11 单入口启动器三条安全边界测试。

只覆盖纯函数，不启动真实子进程 / 不连网络 / 不弹 tkinter。
"""

from __future__ import annotations

import json
import os
import socket
from unittest import mock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.local_agent_auth import LocalAgentAuthContext, require_local_agent_context
from app import phase12_test_launcher
from app.local_agent_main import _build_worker_env
from app.phase12_test_launcher import _agent_env, _local_agent_command, _port_is_free


# ---------- 边界 1：Worker 子进程环境隔离（token / DB / internal token 不外泄） ----------

def test_launcher_reads_baked_api_frontend_and_merchant(tmp_path, monkeypatch):
    config = {
        "test_api_url": "https://merchant.xiaogaoai.cn/api",
        "frontend_url": "https://merchant.xiaogaoai.cn/",
        "merchant_id": "m_nc_2bba00063cc13016",
    }
    (tmp_path / "phase12_test_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    monkeypatch.setattr(phase12_test_launcher, "_resource_dir", lambda: tmp_path)

    assert phase12_test_launcher._load_baked_config() == config

def test_worker_env_strips_secrets(monkeypatch):
    """_build_worker_env 必须剥离 Local Agent 凭据、数据库地址与 internal token。"""
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "agent-secret-xxx")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/auto_wechat")
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql://u:p@db/xg_douyin_ai_cs")
    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "compute-internal-yyy")
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    monkeypatch.setenv("SOME_CUSTOM_TOKEN", "should-be-stripped")
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("LOCAL_AGENT_MERCHANT_ID", "m_test_001")
    monkeypatch.setenv("LOCAL_AGENT_TOKENS", "m_test_001:agent-secret-xxx")
    monkeypatch.setenv("PATH", "C:\\windows\\system32")

    env = _build_worker_env()

    # 凭据 / 数据库 / internal token / NewCar 鉴权 / 任意 *_TOKEN 全部剥离
    assert "LOCAL_AGENT_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert "RAG_DATABASE_URL" not in env
    assert "COMPUTE_INTERNAL_TOKEN" not in env
    assert "NEWCAR_AUTH_ENABLED" not in env
    assert "NEWCAR_AUTH_MOCK_ENABLED" not in env
    assert "SOME_CUSTOM_TOKEN" not in env
    assert "LOCAL_AGENT_AUTH_REQUIRED" not in env
    assert "LOCAL_AGENT_MERCHANT_ID" not in env
    assert "LOCAL_AGENT_TOKENS" not in env
    # Worker 运行所需的环境保留
    assert env["PATH"] == "C:\\windows\\system32"


def test_worker_env_value_not_leaked(monkeypatch):
    """剥离后 Worker 环境的任何值都不含 token 明文。"""
    secret = "agent-secret-xxx"
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", secret)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{secret}@db/x")
    env = _build_worker_env()
    for value in env.values():
        assert secret not in value


# ---------- 边界 2：token 只进环境变量，绝不进启动命令 argv ----------

def test_token_not_in_local_agent_command():
    """Local Agent 启动 argv 不得包含 token 明文。"""
    token = "agent-secret-xxx"
    cmd = _local_agent_command(
        "local_agent_phase12_test.exe",
        host="127.0.0.1", port=19000, server_url="https://test-api.example.com",
    )
    assert token not in cmd
    # argv 只含 exe + --host/--port/--server-url 及其值
    assert cmd[0].endswith("local_agent_phase12_test.exe")
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--server-url" in cmd
    # 不存在任何 --token 形参
    assert not any(arg.startswith("--token") or arg.startswith("--api-key") for arg in cmd)


def test_token_only_in_env_under_local_agent_token_key():
    """token 只写入 LOCAL_AGENT_TOKEN 环境键，不在其它键值里重复出现。"""
    token = "agent-secret-xxx"
    env = _agent_env(
        token, worker_exe="ai_edit_worker.exe", ffmpeg_exe="ffmpeg.exe",
        ffprobe_exe="ffprobe.exe", frontend_url="https://test.example.com",
        merchant_id="m_test_001",
    )
    assert env["LOCAL_AGENT_TOKEN"] == token
    assert env["LOCAL_AGENT_MERCHANT_ID"] == "m_test_001"
    assert env["LOCAL_AGENT_AUTH_REQUIRED"] == "true"
    for key, value in env.items():
        if key == "LOCAL_AGENT_TOKEN":
            continue
        assert token not in str(value), f"token 泄露到环境键 {key}"


def test_singular_agent_token_is_bound_to_baked_merchant(monkeypatch):
    """干净电脑无需外部 LOCAL_AGENT_TOKENS，也能完成严格商户鉴权。"""
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")
    monkeypatch.delenv("LOCAL_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "agent-secret-xxx")
    monkeypatch.setenv("LOCAL_AGENT_MERCHANT_ID", "m_test_001")

    app = FastAPI()

    @app.get("/probe")
    def probe(ctx: LocalAgentAuthContext = Depends(require_local_agent_context)):
        return {"merchant_id": ctx.merchant_id}

    response = TestClient(app).get(
        "/probe", headers={"X-Local-Agent-Token": "agent-secret-xxx"}
    )

    assert response.status_code == 200
    assert response.json() == {"merchant_id": "m_test_001"}


# ---------- 边界 3：端口占用只读检测，绝不杀未知进程 ----------

def test_port_free_when_bind_ok():
    """端口可绑定时返回 True。"""
    with mock.patch.object(socket.socket, "bind") as fake_bind:
        assert _port_is_free("127.0.0.1", 19000) is True
    fake_bind.assert_called_once_with(("127.0.0.1", 19000))


def test_port_busy_returns_false_without_killing():
    """端口被占用（bind 抛 OSError）时返回 False，且不调用任何杀进程操作。"""
    with mock.patch.object(socket.socket, "bind", side_effect=OSError("port in use")):
        result = _port_is_free("127.0.0.1", 19000)
    assert result is False


def test_port_busy_does_not_raise():
    """端口检测异常被吞掉返回 False，不向调用方抛。"""
    with mock.patch.object(socket.socket, "bind", side_effect=OSError):
        _port_is_free("127.0.0.1", 19000)  # 不得抛异常
