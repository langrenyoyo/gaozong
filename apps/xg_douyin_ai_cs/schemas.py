"""抖音AI小高客服 API schema。"""

from typing import Literal

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
    allowed_category_keys: list[str] | None = None
    allowed_category_ids: list[str] | None = None
    rag_enabled: bool | None = None


class ConversationHistoryItem(BaseModel):
    role: str
    content: str
    created_at: str | None = None
    message_id: str | None = None


class ReplySuggestionRequest(BaseModel):
    tenant_id: str
    account_id: int | str
    latest_message: str
    merchant_id: str = "demo_bba"
    douyin_account_id: int | str | None = None
    agent_id: str | None = None
    agent_config: AgentConfig | None = None
    max_history_messages: int = Field(default=20, ge=1, le=100)
    conversation_history: list[ConversationHistoryItem] | None = None
    conversation_short_id: str | None = None
    customer_open_id: str | None = None
    account_open_id: str | None = None
    direct_llm_policy: dict | None = None


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
    intent: str | None = None
    lead_level: str | None = None
    tags: list[str] = Field(default_factory=list)
    detected_vehicle: str | None = None
    detected_contacts: dict | None = None
    manual_required_reason: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    rag_sources: list[dict] = Field(default_factory=list)
    decision_version: str | None = None
    error_code: str | None = None
    timeout_layer: str | None = None
    elapsed_ms: int | None = None
    timeout_seconds: float | None = None
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None


# ========== Phase 8 Task 4：每日销售总结摘要 ==========

DAILY_SUMMARY_FIELD_MAX = 2000
DAILY_SUMMARY_NAME_MAX = 200
DAILY_SUMMARY_MAX_ITEMS = 100


class DailySalesSummaryItem(BaseModel):
    """单条销售总结输入。

    只允许 8 个结构化字段；extra=forbid 拒绝 raw_text/parse_error/手机号/微信号等
    不应进入 LLM 的字段。手机号/微信号在服务层发给 LLM 前再次脱敏。
    """

    model_config = {"extra": "forbid"}
    sales_name: str | None = Field(default=None, max_length=DAILY_SUMMARY_NAME_MAX)
    overall_quality: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)
    main_problem: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)
    car_model_summary: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)
    budget_summary: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)
    cooperation_level: str | None = Field(default=None, max_length=DAILY_SUMMARY_NAME_MAX)
    today_suggestion: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)
    extra_feedback: str | None = Field(default=None, max_length=DAILY_SUMMARY_FIELD_MAX)


class DailySalesSummaryRequest(BaseModel):
    """9000 → 9100 每日销售总结摘要请求。

    9100 不信任 merchant_id 以外的租户字段，不访问 9000 数据库；
    merchant_id 仅用于算力上报，report_day 仅用于日志，均不参与 LLM prompt。
    """

    model_config = {"extra": "forbid"}
    merchant_id: str = Field(..., min_length=1, max_length=128)
    report_day: str = Field(..., min_length=1, max_length=10)
    summaries: list[DailySalesSummaryItem] = Field(..., min_length=1, max_length=DAILY_SUMMARY_MAX_ITEMS)


class DailySalesSummaryResponse(BaseModel):
    """摘要响应：llm_used=false 时 summary_text=None + fallback_reason 稳定诊断码。"""

    summary_text: str | None = None
    llm_used: bool = False
    model: str | None = None
    prompt_version: str
    fallback_reason: str | None = None
