"""Local Agent heartbeat reporting tests."""

import logging
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_heartbeat_payload_reports_idle_with_wechat_ready_status():
    from app import local_agent_main

    with patch("app.local_agent_main.collect_wechat_window_diagnostics") as mock_diagnostics:
        mock_diagnostics.return_value = {"wechat_detected": True}
        payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_client_id"] == "local-agent-default"
    assert payload["agent_name"] == "小高AI微信助手"
    assert payload["host_name"]
    assert payload["agent_status"] == "idle"
    assert payload["wechat_status"] == "ready"
    assert payload["current_task_id"] is None
    assert payload["current_task_type"] is None
    assert payload["version"]
    mock_diagnostics.assert_called_once()


def test_heartbeat_payload_reports_unavailable_when_wechat_window_missing():
    from app import local_agent_main

    with patch("app.local_agent_main.collect_wechat_window_diagnostics") as mock_diagnostics:
        mock_diagnostics.return_value = {"wechat_detected": False, "wechat_candidates": []}
        payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_status"] == "idle"
    assert payload["wechat_status"] == "unavailable"
    mock_diagnostics.assert_called_once()


def test_heartbeat_payload_reports_unavailable_when_wechat_window_minimized():
    from app import local_agent_main

    with patch("app.local_agent_main.collect_wechat_window_diagnostics") as mock_diagnostics:
        mock_diagnostics.return_value = {
            "wechat_detected": False,
            "wechat_candidates": [
                {
                    "title": "微信",
                    "process_name": "Weixin.exe",
                    "visible": True,
                    "iconic": True,
                }
            ],
            "notes": ["检测到疑似微信窗口处于最小化状态"],
        }
        payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_status"] == "idle"
    assert payload["wechat_status"] == "unavailable"


def test_heartbeat_payload_reports_unknown_when_wechat_probe_errors(caplog):
    from app import local_agent_main

    with patch("app.local_agent_main.collect_wechat_window_diagnostics") as mock_diagnostics:
        mock_diagnostics.side_effect = RuntimeError("uia unavailable")
        with caplog.at_level(logging.WARNING):
            payload = local_agent_main._build_agent_heartbeat_payload()

    assert payload["agent_status"] == "idle"
    assert payload["wechat_status"] == "unknown"
    assert "heartbeat wechat status probe failed" in caplog.text


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
    assert payload["wechat_status"] in {"ready", "unavailable", "unknown"}


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
    assert payload["wechat_status"] in {"ready", "unavailable", "unknown"}


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
