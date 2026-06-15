"""Read-only Agent status aggregation for merchant UI guards."""

from datetime import datetime

from app.services import automation_control


DISABLED_REASON = "Local Agent heartbeat is not available yet"


def get_agent_status() -> dict:
    """Return conservative server-only Agent status without probing Local Agent."""
    automation_status = automation_control.get_automation_status()

    return {
        "agent_online": False,
        "agent_status": "offline",
        "wechat_available": "unknown",
        "wechat_status": "unknown",
        "automation_enabled": automation_status["automation_enabled"],
        "emergency_stopped": automation_status["emergency_stopped"],
        "action_in_progress": automation_status.get("action_in_progress", False),
        "current_task_id": None,
        "current_task_type": None,
        "last_heartbeat_at": None,
        "last_checked_at": datetime.now(),
        "can_run_wechat_action": False,
        "disabled_reason": DISABLED_REASON,
        "status_source": "server_only",
    }
