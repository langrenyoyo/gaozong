"""Phase 8-B 检查点 A 前置修复：Local Agent 令牌延迟读取测试。

验证修复点（执行包工作包第 2 项）：
1. 模块导入后再设置环境变量，_http_get/_http_post_json 能携带令牌。
2. 未配置令牌时继续拒绝匿名请求（不发起 HTTP）。
3. 令牌不进入 URL、异常、响应（只进 header）。
4. helper 每次从环境读取，不缓存。

不启动真实微信、不访问真实 9000/9100、不真实发送。
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading

import pytest

from app import local_agent_main as la


# 模块级记录器：handler 写入最近一次请求的 method/path/headers
_record: dict = {}


class _HeaderProbeHandler(http.server.BaseHTTPRequestHandler):
    """替身 HTTP 服务：记录请求首行与头后返回 200 JSON。"""

    def log_message(self, *a):
        pass

    def _respond(self, status=200, payload=None):
        _record["last"] = {
            "method": self.command,
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
        }
        body = json.dumps(payload or {"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._respond()

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self._respond()


@pytest.fixture
def probe_server():
    _record.clear()
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _HeaderProbeHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


# ---------- 模块导入后设置环境变量，调用能携带令牌（核心修复回归） ----------

def test_get_carries_token_set_after_import(probe_server, monkeypatch):
    """模块导入后再设置环境变量，_http_get 携带令牌。

    模拟 exe 入口 import-then-loadenv 时序：模块级缓存为 None（旧实现的 bug），
    环境变量在导入之后才写入。旧实现读模块级缓存 → 恒 None → 拒绝；
    新实现每次读 os.environ → 携带令牌。
    """
    monkeypatch.setattr(la, "_LOCAL_AGENT_TOKEN", None, raising=False)  # 模拟旧导入时缓存为 None
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "lazy-token-xyz")
    result = la._http_get(f"{probe_server}/ping")
    assert result["ok"] is True
    last = _record["last"]
    assert last["headers"].get("X-Local-Agent-Token") == "lazy-token-xyz"
    # 令牌不进 URL
    assert "lazy-token-xyz" not in last["path"]


def test_post_carries_token_set_after_import(probe_server, monkeypatch):
    monkeypatch.setattr(la, "_LOCAL_AGENT_TOKEN", None, raising=False)
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "lazy-token-xyz")
    result = la._http_post_json(f"{probe_server}/ping", data={"k": "v"})
    assert result["ok"] is True
    last = _record["last"]
    assert last["headers"].get("X-Local-Agent-Token") == "lazy-token-xyz"
    assert "lazy-token-xyz" not in last["path"]


# ---------- 未配置令牌时拒绝匿名请求 ----------

def test_no_token_rejects_anonymous_get(monkeypatch):
    monkeypatch.delenv("LOCAL_AGENT_TOKEN", raising=False)
    monkeypatch.setattr(la, "_LOCAL_AGENT_TOKEN", None, raising=False)
    result = la._http_get("http://127.0.0.1:1/ping")
    assert result["ok"] is False
    assert result["status"] is None  # 未到 HTTP 层
    assert "未配置" in result["error"]


def test_no_token_rejects_anonymous_post(monkeypatch):
    monkeypatch.delenv("LOCAL_AGENT_TOKEN", raising=False)
    monkeypatch.setattr(la, "_LOCAL_AGENT_TOKEN", None, raising=False)
    result = la._http_post_json("http://127.0.0.1:1/ping", data={})
    assert result["ok"] is False
    assert result["status"] is None
    assert "未配置" in result["error"]


# ---------- 令牌不进异常（连接失败时 error 字符串不含令牌） ----------

def test_token_not_in_error_when_connection_fails(monkeypatch):
    monkeypatch.setattr(la, "_LOCAL_AGENT_TOKEN", None, raising=False)
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "secret-lazy-token-9999")
    # 指向必然连不上的端口
    result = la._http_get("http://127.0.0.1:1/ping", timeout=0.5)
    assert result["ok"] is False
    assert "secret-lazy-token-9999" not in (result.get("error") or "")


# ---------- helper 单元：从环境读取，不缓存 ----------

def test_get_local_agent_token_reads_env_each_time(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "v1")
    assert la._get_local_agent_token() == "v1"
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "v2")
    assert la._get_local_agent_token() == "v2"
    monkeypatch.delenv("LOCAL_AGENT_TOKEN", raising=False)
    assert la._get_local_agent_token() is None
