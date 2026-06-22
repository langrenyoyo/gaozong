"""AI小高智能体能力服务 schema 兼容导出。"""

from apps.agents.schemas import (
    AgentKnowledgeCategoriesOut,
    AgentKnowledgeCategoriesResponse,
    AgentKnowledgeCategoriesUpdate,
    AiAgentCreate,
    AiAgentListResponse,
    AiAgentOut,
    AiAgentResponse,
    AiAgentTrainingChatRequest,
    AiAgentTrainingChatResponse,
    AiAgentTrainingChatResponseData,
    AiAgentUpdate,
)
from packages.common.capability import CapabilityRoot, CapabilityStatus


__all__ = [
    "AgentKnowledgeCategoriesOut",
    "AgentKnowledgeCategoriesResponse",
    "AgentKnowledgeCategoriesUpdate",
    "AiAgentCreate",
    "AiAgentListResponse",
    "AiAgentOut",
    "AiAgentResponse",
    "AiAgentTrainingChatRequest",
    "AiAgentTrainingChatResponse",
    "AiAgentTrainingChatResponseData",
    "AiAgentUpdate",
    "CapabilityRoot",
    "CapabilityStatus",
]
