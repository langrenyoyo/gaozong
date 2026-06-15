from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services import agent_status_service, automation_control


client = TestClient(app)


def _reset_automation_state():
    automation_control._state["automation_enabled"] = True
    automation_control._state["emergency_stopped"] = False
    automation_control._state["stop_reason"] = None
    automation_control._state["stopped_at"] = None
    automation_control._state["action_in_progress"] = False
    if hasattr(agent_status_service, "reset_agent_heartbeat_for_tests"):
        agent_status_service.reset_agent_heartbeat_for_tests()


def _heartbeat_payload(**overrides):
    payload = {
        "agent_client_id": "local-agent-default",
        "agent_name": "小高AI微信助手",
        "host_name": "DEV-PC",
        "agent_status": "idle",
        "wechat_status": "ready",
        "current_task_id": None,
        "current_task_type": None,
        "version": "0.1.0",
    }
    payload.update(overrides)
    return payload


def test_agent_status_returns_conservative_server_only_state():
    _reset_automation_state()

    response = client.get("/agent/status")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "success"

    data = body["data"]
    assert data["agent_online"] is False
    assert data["agent_status"] == "offline"
    assert data["wechat_available"] == "unknown"
    assert data["wechat_status"] == "unknown"
    assert data["automation_enabled"] is True
    assert data["emergency_stopped"] is False
    assert data["action_in_progress"] is False
    assert data["current_task_id"] is None
    assert data["current_task_type"] is None
    assert data["last_heartbeat_at"] is None
    assert data["last_checked_at"]
    assert data["can_run_wechat_action"] is False
    assert data["disabled_reason"]
    assert data["status_source"] == "server_only"


def test_agent_heartbeat_makes_status_online_and_action_runnable():
    _reset_automation_state()

    heartbeat = client.post("/agent/heartbeat", json=_heartbeat_payload())

    assert heartbeat.status_code == 200
    heartbeat_body = heartbeat.json()
    assert heartbeat_body["success"] is True
    assert heartbeat_body["message"] == "success"
    assert heartbeat_body["data"]["received"] is True
    assert heartbeat_body["data"]["server_time"]
    assert heartbeat_body["data"]["next_heartbeat_seconds"] == 10

    response = client.get("/agent/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["agent_online"] is True
    assert data["agent_status"] == "idle"
    assert data["wechat_available"] == "available"
    assert data["wechat_status"] == "ready"
    assert data["last_heartbeat_at"]
    assert data["can_run_wechat_action"] is True
    assert data["disabled_reason"] == ""
    assert data["status_source"] == "heartbeat"


def test_busy_agent_heartbeat_preserves_task_and_disables_action():
    _reset_automation_state()

    heartbeat = client.post(
        "/agent/heartbeat",
        json=_heartbeat_payload(
            agent_status="busy",
            current_task_id=123,
            current_task_type="reply_detect",
        ),
    )

    assert heartbeat.status_code == 200
    data = client.get("/agent/status").json()["data"]
    assert data["agent_online"] is True
    assert data["agent_status"] == "busy"
    assert data["current_task_id"] == 123
    assert data["current_task_type"] == "reply_detect"
    assert data["can_run_wechat_action"] is False
    assert data["disabled_reason"] == "Local Agent is busy"
    assert data["status_source"] == "heartbeat"


def test_wechat_unavailable_heartbeat_disables_action():
    _reset_automation_state()

    heartbeat = client.post(
        "/agent/heartbeat",
        json=_heartbeat_payload(wechat_status="unavailable"),
    )

    assert heartbeat.status_code == 200
    data = client.get("/agent/status").json()["data"]
    assert data["agent_online"] is True
    assert data["wechat_available"] == "unavailable"
    assert data["wechat_status"] == "unavailable"
    assert data["can_run_wechat_action"] is False
    assert data["disabled_reason"] == "WeChat is not available"
    assert data["status_source"] == "heartbeat"


def test_expired_heartbeat_returns_offline_expired_status(monkeypatch):
    _reset_automation_state()

    heartbeat = client.post("/agent/heartbeat", json=_heartbeat_payload())

    assert heartbeat.status_code == 200

    def expired_now():
        return agent_status_service._latest_heartbeat["received_at"] + timedelta(seconds=31)

    monkeypatch.setattr(agent_status_service, "_now", expired_now)

    data = client.get("/agent/status").json()["data"]
    assert data["agent_online"] is False
    assert data["agent_status"] == "offline"
    assert data["wechat_available"] == "unknown"
    assert data["can_run_wechat_action"] is False
    assert data["disabled_reason"] == "Local Agent heartbeat expired"
    assert data["status_source"] == "heartbeat_expired"


def test_agent_status_reuses_automation_status_without_changing_existing_endpoint():
    _reset_automation_state()
    automation_control._state["automation_enabled"] = False
    automation_control._state["emergency_stopped"] = True
    automation_control._state["stop_reason"] = "test stop"
    automation_control._state["action_in_progress"] = True

    response = client.get("/agent/status")
    automation_response = client.get("/automation/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["automation_enabled"] is False
    assert data["emergency_stopped"] is True
    assert data["action_in_progress"] is True
    assert data["can_run_wechat_action"] is False

    assert automation_response.status_code == 200
    automation_data = automation_response.json()
    assert automation_data["automation_enabled"] is False
    assert automation_data["emergency_stopped"] is True
    assert automation_data["action_in_progress"] is True

    _reset_automation_state()


def test_agent_status_does_not_trigger_wechat_automation(monkeypatch):
    _reset_automation_state()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("wechat automation must not be called by /agent/status")

    monkeypatch.setattr(
        "app.services.wechat_ui_reply_service.detect_reply_from_wechat",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.wechat_ui.contact_searcher.open_chat_by_nickname",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.wechat_ui.input_writer.write_text_to_input",
        fail_if_called,
    )

    response = client.get("/agent/status")

    assert response.status_code == 200
    assert response.json()["data"]["can_run_wechat_action"] is False


def test_agent_heartbeat_does_not_trigger_wechat_automation(monkeypatch):
    _reset_automation_state()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("wechat automation must not be called by /agent/heartbeat")

    monkeypatch.setattr(
        "app.services.wechat_ui_reply_service.detect_reply_from_wechat",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.wechat_ui.contact_searcher.open_chat_by_nickname",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.wechat_ui.input_writer.write_text_to_input",
        fail_if_called,
    )

    response = client.post("/agent/heartbeat", json=_heartbeat_payload())

    assert response.status_code == 200
    assert response.json()["data"]["received"] is True
