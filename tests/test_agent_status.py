from fastapi.testclient import TestClient

from app.main import app
from app.services import automation_control


client = TestClient(app)


def _reset_automation_state():
    automation_control._state["automation_enabled"] = True
    automation_control._state["emergency_stopped"] = False
    automation_control._state["stop_reason"] = None
    automation_control._state["stopped_at"] = None
    automation_control._state["action_in_progress"] = False


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
