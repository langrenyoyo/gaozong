"""能力中心网关前缀。"""

from fastapi import APIRouter

from apps.agents.service import META as AGENTS_META
from apps.compute.service import META as COMPUTE_META
from apps.douyin_cs.service import META as DOUYIN_CS_META
from apps.knowledge.service import META as KNOWLEDGE_META
from apps.leads.service import META as LEADS_META
from apps.wechat_assistant.service import META as WECHAT_ASSISTANT_META
from packages.common.capability import CapabilityMeta, CapabilityStatus

router = APIRouter(prefix="/api", tags=["能力中心网关"])

_CAPABILITY_BY_PREFIX: dict[str, CapabilityMeta] = {
    "douyin-cs": DOUYIN_CS_META,
    "leads": LEADS_META,
    "agents": AGENTS_META,
    "wechat-assistant": WECHAT_ASSISTANT_META,
    "compute": COMPUTE_META,
    "knowledge": KNOWLEDGE_META,
}


@router.get("/{capability}/health", response_model=CapabilityStatus)
def capability_health(capability: str) -> CapabilityStatus:
    """返回 gateway 视角下的能力中心健康状态。"""
    meta = _CAPABILITY_BY_PREFIX[capability]
    return CapabilityStatus(service=meta.service, name=meta.name, status="ok")
