"""Local Agent heartbeat reporting tests."""

import logging
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_heartbeat_payload_reports_idle_without_wechat_probe():
    from app import local_agent_main

    with patch("app.local_agent_main.check_wechat_ready_for_automation") as mock_ready:
        payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_client_id"] == "local-agent-default"
    assert payload["agent_name"] == "小高AI微信助手"
    assert payload["host_name"]
    assert payload["agent_status"] == "idle"
    assert payload["wechat_status"] == "unknown"
    assert payload["current_task_id"] is None
    assert payload["current_task_type"] is None
    assert payload["version"]
    mock_ready.assert_not_called()


def test_heartbeat_payload_reads_agent_identity_from_environment(monkeypatch):
    from app import local_agent_main

    monkeypatch.setenv("AUTO_WECHAT_AGENT_CLIENT_ID", "agent-from-env")
    monkeypatch.setenv("AUTO_WECHAT_AGENT_NAME", "小高AI微信助手")

    payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_client_id"] == "agent-from-env"
    assert payload["agent_name"] == "小高AI微信助手"


def test_heartbeat_payload_reports_busy_when_task_lock_is_held():
    from app import local_agent_main

    local_agent_main._wechat_task_lock = local_agent_main.threading.Lock()
    assert local_agent_main._wechat_task_lock.acquire(blocking=False) is True
    try:
        payload = local_agent_main._build_agent_heartbeat_payload()
    finally:
        local_agent_main._wechat_task_lock.release()

    assert payload["agent_status"] == "busy"
    assert payload["wechat_status"] == "unknown"


@patch("app.local_agent_main._http_post_json")
def test_send_agent_heartbeat_once_posts_to_server(mock_post):
    from app import local_agent_main

    mock_post.return_value = {
        "ok": True,
        "status": 200,
        "json": {"success": True},
        "error": None,
    }

    result = local_agent_main._send_agent_heartbeat_once("http://127.0.0.1:9000")

    assert result["ok"] is True
    mock_post.assert_called_once()
    url, payload = mock_post.call_args.args[:2]
    assert url == "http://127.0.0.1:9000/agent/heartbeat"
    assert payload["agent_client_id"] == "local-agent-default"
    assert payload["agent_status"] in {"idle", "busy"}
    assert payload["wechat_status"] == "unknown"


@patch("app.local_agent_main._http_post_json")
def test_send_agent_heartbeat_failure_only_logs_warning(mock_post, caplog):
    from app import local_agent_main

    mock_post.return_value = {
        "ok": False,
        "status": None,
        "json": None,
        "error": "connection refused",
    }

    with caplog.at_level(logging.WARNING):
        result = local_agent_main._send_agent_heartbeat_once("http://127.0.0.1:9000")

    assert result["ok"] is False
    assert "heartbeat" in caplog.text
    assert "connection refused" in caplog.text


@patch("app.local_agent_main._http_post_json")
def test_start_heartbeat_loop_skips_when_server_url_missing(mock_post, caplog):
    from app import local_agent_main

    with caplog.at_level(logging.WARNING):
        started = local_agent_main.start_heartbeat_loop("")

    assert started is None
    mock_post.assert_not_called()
    assert "server_url" in caplog.text


def test_create_local_agent_app_starts_heartbeat_loop_when_server_url_configured():
    from app.local_agent_main import create_local_agent_app

    with patch("app.local_agent_main.start_heartbeat_loop") as mock_start:
        app = create_local_agent_app(
            host="127.0.0.1",
            port=19000,
            server_url="http://127.0.0.1:9000",
        )

    TestClient(app).get("/health")
    mock_start.assert_called_once_with("http://127.0.0.1:9000")


def test_create_local_agent_app_does_not_start_heartbeat_without_server_url():
    from app.local_agent_main import create_local_agent_app

    with patch("app.local_agent_main.start_heartbeat_loop") as mock_start:
        app = create_local_agent_app(host="127.0.0.1", port=19000, server_url=None)

    TestClient(app).get("/health")
    mock_start.assert_not_called()
