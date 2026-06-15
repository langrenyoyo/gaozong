"""Read-only Agent status aggregation for merchant UI guards."""

from datetime import datetime
from threading import Lock
from typing import Any

from app.services import automation_control


DISABLED_REASON = "Local Agent heartbeat is not available yet"
HEARTBEAT_TTL_SECONDS = 30
NEXT_HEARTBEAT_SECONDS = 10
AVAILABLE_WECHAT_STATUSES = {"ready", "available"}

_heartbeat_lock = Lock()
_latest_heartbeat: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now()


def reset_agent_heartbeat_for_tests() -> None:
    """Clear in-memory heartbeat state for isolated tests."""
    global _latest_heartbeat
    with _heartbeat_lock:
        _latest_heartbeat = None


def record_agent_heartbeat(payload: Any) -> dict:
    """Store the latest Local Agent heartbeat in memory."""
    global _latest_heartbeat
    server_time = _now()
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)

    with _heartbeat_lock:
        _latest_heartbeat = {
            **data,
            "received_at": server_time,
        }

    return {
        "received": True,
        "server_time": server_time,
        "next_heartbeat_seconds": NEXT_HEARTBEAT_SECONDS,
    }


def get_agent_status() -> dict:
    """Return Agent status without probing Local Agent or WeChat UI."""
    automation_status = automation_control.get_automation_status()
    now = _now()
    with _heartbeat_lock:
        heartbeat = dict(_latest_heartbeat) if _latest_heartbeat else None

    base = {
        "automation_enabled": automation_status["automation_enabled"],
        "emergency_stopped": automation_status["emergency_stopped"],
        "action_in_progress": automation_status.get("action_in_progress", False),
        "last_checked_at": now,
    }

    if heartbeat is None:
        return {
            "agent_online": False,
            "agent_status": "offline",
            "wechat_available": "unknown",
            "wechat_status": "unknown",
            **base,
            "current_task_id": None,
            "current_task_type": None,
            "last_heartbeat_at": None,
            "can_run_wechat_action": False,
            "disabled_reason": DISABLED_REASON,
            "status_source": "server_only",
        }

    received_at = heartbeat["received_at"]
    is_expired = (now - received_at).total_seconds() > HEARTBEAT_TTL_SECONDS
    if is_expired:
        return {
            "agent_online": False,
            "agent_status": "offline",
            "wechat_available": "unknown",
            "wechat_status": heartbeat.get("wechat_status", "unknown"),
            **base,
            "current_task_id": heartbeat.get("current_task_id"),
            "current_task_type": heartbeat.get("current_task_type"),
            "last_heartbeat_at": received_at,
            "can_run_wechat_action": False,
            "disabled_reason": "Local Agent heartbeat expired",
            "status_source": "heartbeat_expired",
        }

    agent_status = heartbeat.get("agent_status", "unknown")
    wechat_status = heartbeat.get("wechat_status", "unknown")
    wechat_available = (
        "available" if wechat_status in AVAILABLE_WECHAT_STATUSES else wechat_status
    )

    can_run = (
        agent_status != "busy"
        and wechat_available == "available"
        and base["automation_enabled"]
        and not base["emergency_stopped"]
        and not base["action_in_progress"]
    )
    disabled_reason = ""
    if not can_run:
        if agent_status == "busy":
            disabled_reason = "Local Agent is busy"
        elif wechat_available != "available":
            disabled_reason = "WeChat is not available"
        elif not base["automation_enabled"]:
            disabled_reason = "Automation is disabled"
        elif base["emergency_stopped"]:
            disabled_reason = "Automation emergency stop is active"
        elif base["action_in_progress"]:
            disabled_reason = "Automation action is in progress"

    return {
        "agent_online": True,
        "agent_status": agent_status,
        "wechat_available": wechat_available,
        "wechat_status": wechat_status,
        **base,
        "current_task_id": heartbeat.get("current_task_id"),
        "current_task_type": heartbeat.get("current_task_type"),
        "last_heartbeat_at": received_at,
        "can_run_wechat_action": can_run,
        "disabled_reason": disabled_reason,
        "status_source": "heartbeat",
    }
