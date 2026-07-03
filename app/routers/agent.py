"""Read-only Agent status API."""

from fastapi import APIRouter, Request

from app.auth.local_agent_auth import get_optional_local_agent_context
from app.schemas import (
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentStatusResponse,
)
from app.services.agent_status_service import get_agent_status, record_agent_heartbeat


router = APIRouter(prefix="/agent", tags=["Agent status"])


@router.get("/status", response_model=AgentStatusResponse)
def read_agent_status():
    """Return conservative server-side Agent status for UI action guards."""
    return AgentStatusResponse(data=get_agent_status())


@router.post("/heartbeat", response_model=AgentHeartbeatResponse)
def receive_agent_heartbeat(payload: AgentHeartbeatRequest, request: Request):
    """Record the latest Local Agent heartbeat without running automation."""
    get_optional_local_agent_context(request)
    return AgentHeartbeatResponse(data=record_agent_heartbeat(payload))
