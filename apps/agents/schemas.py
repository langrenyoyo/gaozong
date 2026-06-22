"""AI小高智能体能力服务 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AiAgentCreate(BaseModel):
    """智能体创建请求。"""

    name: str = Field(..., min_length=1, max_length=100)
    prompt: str = ""
    knowledge_base_text: str = ""
    avatar_url: Optional[str] = None


class AiAgentUpdate(BaseModel):
    """智能体更新请求。"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    prompt: Optional[str] = None
    knowledge_base_text: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|disabled)$")


class AiAgentOut(BaseModel):
    """智能体响应。"""

    id: int
    agent_id: str
    merchant_id: str
    name: str
    avatar_seed: str
    avatar_url: Optional[str] = None
    prompt: str = ""
    knowledge_base_text: str = ""
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AiAgentResponse(BaseModel):
    """智能体单项响应包装。"""

    success: bool = True
    data: AiAgentOut
    message: str = "success"


class AiAgentListResponse(BaseModel):
    """智能体列表响应包装。"""

    success: bool = True
    data: list[AiAgentOut]
    message: str = "success"


class AiAgentTrainingChatRequest(BaseModel):
    """训练对话预览请求。"""

    message: str = Field(..., min_length=1)


class AiAgentTrainingChatResponseData(BaseModel):
    """训练对话预览结果。"""

    reply_text: str
    warnings: list[str] = []
    llm_used: bool = False
    knowledge_used: bool = True


class AiAgentTrainingChatResponse(BaseModel):
    """训练对话预览响应包装。"""

    success: bool = True
    data: AiAgentTrainingChatResponseData
    message: str = "success"


class AgentKnowledgeCategoriesUpdate(BaseModel):
    """Agent 手动知识分类绑定替换请求。"""

    category_keys: list[str] = Field(default_factory=list)


class AgentKnowledgeCategoriesOut(BaseModel):
    """Agent 知识分类绑定输出。"""

    agent_id: str
    category_keys: list[str]
    effective_category_keys: list[str]


class AgentKnowledgeCategoriesResponse(BaseModel):
    """Agent 知识分类绑定响应包装。"""

    success: bool = True
    data: AgentKnowledgeCategoriesOut
    message: str = "success"
