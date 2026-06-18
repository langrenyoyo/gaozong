"""抖音AI小高客服 API schema。"""

from pydantic import BaseModel, Field


class ServiceStatusResponse(BaseModel):
    service: str
    status: str


class VersionResponse(BaseModel):
    service: str
    version: str
    port: int


class CategoryItem(BaseModel):
    id: int
    name: str
    sort_order: int
    is_active: bool = True


class CategoryListResponse(BaseModel):
    items: list[CategoryItem]


class DouyinAccountItem(BaseModel):
    id: int
    tenant_id: str
    account_name: str
    account_open_id: str
    status: str
    avatar: str | None = None
    unread_count: int = 0
    last_active_at: str | None = None


class DouyinAccountListResponse(BaseModel):
    items: list[DouyinAccountItem]


class AgentItem(BaseModel):
    agent_id: str
    agent_name: str
    agent_category: str
    reply_style: str
    business_scope: str
    is_default: bool = False
    is_active: bool = True


class AccountAgentListResponse(BaseModel):
    items: list[AgentItem]
    default_agent_id: str | None = None


class ConversationItem(BaseModel):
    id: int
    account_id: int
    open_id: str
    nickname: str
    last_message: str
    last_message_at: str
    unread_count: int
    lead_status: str | None = None


class ConversationListResponse(BaseModel):
    items: list[ConversationItem]


class MessageItem(BaseModel):
    id: int
    conversation_id: int
    direction: str
    content: str
    created_at: str


class MessageListResponse(BaseModel):
    items: list[MessageItem]


class UserProfileResponse(BaseModel):
    conversation_id: int
    budget_min: int | None = None
    budget_max: int | None = None
    brand_preference: str | None = None
    vehicle_preference: str | None = None
    purchase_intent_level: str
    lead_capture_suggested: bool


class AgentConfig(BaseModel):
    agent_id: str
    agent_name: str | None = None
    system_prompt: str | None = None
    prompt: str | None = None
    knowledge_base_text: str | None = None
    status: str | None = None


class ReplySuggestionRequest(BaseModel):
    tenant_id: str
    account_id: int
    latest_message: str
    merchant_id: str = "demo_bba"
    douyin_account_id: int | None = None
    agent_id: str | None = None
    agent_config: AgentConfig | None = None
    max_history_messages: int = Field(default=20, ge=1, le=100)


class RecommendedVehicle(BaseModel):
    vehicle_name: str
    price: int
    category: str


class ReplySuggestionResponse(BaseModel):
    reply_text: str
    match_level: str
    target_category: str | None = None
    target_vehicle_name: str | None = None
    recommended_vehicles: list[RecommendedVehicle] = Field(default_factory=list)
    lead_capture_required: bool
    confidence: float
    manual_required: bool
    auto_send: bool
    llm_used: bool = False
    rag_used: bool = False
    source_chunks: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    agent_name: str | None = None
    agent_category: str | None = None
