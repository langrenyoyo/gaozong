"""Local Agent runtime polling switch tests."""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/health", "/runtime/status"])
def test_customer_frontend_private_network_preflight_is_allowed(monkeypatch, path):
    from app.local_agent_main import create_local_agent_app

    origin = "https://merchant.xiaogaoai.cn"
    monkeypatch.setenv("AI_EDIT_TEST_FRONTEND_URL", f"{origin}/")
    client = TestClient(create_local_agent_app())

    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-local-agent-token",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-private-network"] == "true"


def test_customer_frontend_delete_preflight_is_allowed(monkeypatch):
    """素材删除必须先通过浏览器 DELETE 私网预检。"""
    from app.local_agent_main import create_local_agent_app

    origin = "https://merchant.xiaogaoai.cn"
    monkeypatch.setenv("AI_EDIT_TEST_FRONTEND_URL", f"{origin}/")
    client = TestClient(create_local_agent_app())

    response = client.options(
        "/agent/ai-edit/materials/mat-1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "x-local-agent-token",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-private-network"] == "true"


def test_runtime_status_defaults_to_polling_disabled():
    from app.local_agent_main import create_local_agent_app

    app = create_local_agent_app(host="127.0.0.1", port=19000, server_url="http://127.0.0.1:9000")
    client = TestClient(app)

    data = client.get("/runtime/status").json()

    assert data["online"] is True
    assert data["task_polling_enabled"] is False
    assert data["server_url"] == "http://127.0.0.1:9000"
    assert data["last_poll_at"] is None
    assert data["last_execute_poll_at"] is None
    assert data["last_detect_poll_at"] is None
    assert data["last_task_result"] is None
    assert data["last_error"] is None
    assert data["version"]
    assert data["mode"] in {"dev", "exe"}


def test_runtime_enable_and_disable_updates_status():
    from app.local_agent_main import create_local_agent_app

    app = create_local_agent_app(host="127.0.0.1", port=19000, server_url="http://127.0.0.1:9000")
    client = TestClient(app)

    enabled = client.post("/runtime/enable-task-polling").json()
    assert enabled["task_polling_enabled"] is True

    status = client.get("/runtime/status").json()
    assert status["task_polling_enabled"] is True

    disabled = client.post("/runtime/disable-task-polling").json()
    assert disabled["task_polling_enabled"] is False

    status = client.get("/runtime/status").json()
    assert status["task_polling_enabled"] is False


def test_runtime_enable_multiple_times_starts_single_loop(monkeypatch):
    from app import local_agent_main

    starts = []

    class FakeThread:
        def __init__(self, *args, **kwargs):
            starts.append(kwargs.get("name"))
            self._alive = False

        def start(self):
            self._alive = True

        def is_alive(self):
            return self._alive

    monkeypatch.setattr(local_agent_main.threading, "Thread", FakeThread)

    app = local_agent_main.create_local_agent_app(
        host="127.0.0.1",
        port=19000,
        server_url="http://127.0.0.1:9000",
    )
    client = TestClient(app)

    first = client.post("/runtime/enable-task-polling").json()
    second = client.post("/runtime/enable-task-polling").json()

    assert first["task_polling_enabled"] is True
    assert second["task_polling_enabled"] is True
    assert starts.count("local-agent-task-polling") == 1


def test_runtime_polling_reuses_existing_poll_handlers(monkeypatch):
    from app.local_agent_main import create_local_agent_app

    app = create_local_agent_app(host="127.0.0.1", port=19000, server_url="http://127.0.0.1:9000")
    calls = {"execute": 0, "detect": 0}

    def fake_execute():
        calls["execute"] += 1
        return {"success": True, "message": "execute-ok"}

    def fake_detect():
        calls["detect"] += 1
        return {"success": True, "message": "detect-ok"}

    app.state.runtime_poll_once = lambda: (fake_execute(), fake_detect())
    app.state.runtime_poll_interval_seconds = 0.01
    client = TestClient(app)

    client.post("/runtime/enable-task-polling")
    deadline = time.time() + 1
    while time.time() < deadline and (calls["execute"] == 0 or calls["detect"] == 0):
        time.sleep(0.02)

    assert calls["execute"] >= 1
    assert calls["detect"] >= 1

    client.post("/runtime/disable-task-polling")
    after_disable = dict(calls)
    time.sleep(0.05)
    assert calls == after_disable

    status = client.get("/runtime/status").json()
    assert status["last_poll_at"] is not None
    assert status["last_execute_poll_at"] is not None
    assert status["last_detect_poll_at"] is not None
    assert status["last_task_result"]["execute"]["message"] == "execute-ok"
    assert status["last_task_result"]["detect"]["message"] == "detect-ok"
