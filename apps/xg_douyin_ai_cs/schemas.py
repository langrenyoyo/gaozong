"""抖音AI小高客服 API schema。"""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    # 商家可配置变量（固定提示词模板 V2.0）
    store_address: str | None = None
    store_phone: str | None = None
    store_wechat: str | None = None
    business_hours: str | None = None
    sales_cities: str | None = None
    sales_brands: str | None = None
    purchase_cities: str | None = None
    purchase_brands: str | None = None
    after_hours_reply: str | None = None
    vehicle_condition_reply: str | None = None
    appraiser_off_hours_reply: str | None = None


class ConversationHistoryItem(BaseModel):
    role: str
    content: str
    created_at: str | None = None
    message_id: str | None = None
    # P0.2-A 历史来源分层：保留 role 兼容，新增受控可选字段。
    # origin 区分客户/人工客服/AI历史/系统；fact_trust 标注事实可信度。
    # AI 历史（ai_assistant/ai_generated）不得作为客户事实来源。
    origin: str | None = None
    direction: str | None = None
    fact_trust: str | None = None


class CustomerContactMemory(BaseModel):
    has_contact: bool = False
    types: list[Literal["phone", "wechat"]] = Field(default_factory=list, max_length=2)
    masked_values: list[str] = Field(default_factory=list, max_length=10)


class CustomerMemory(BaseModel):
    intent_car: str | None = Field(default=None, max_length=100)
    car_year: str | None = Field(default=None, max_length=100)
    budget: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    contact: CustomerContactMemory = Field(default_factory=CustomerContactMemory)


class ReplySuggestionRequest(BaseModel):
    tenant_id: str
    account_id: int | str
    latest_message: str
    merchant_id: str = Field(..., min_length=1, max_length=128)
    douyin_account_id: int | str | None = None
    agent_id: str | None = None
    agent_config: AgentConfig | None = None
    max_history_messages: int = Field(default=20, ge=1, le=100)
    conversation_history: list[ConversationHistoryItem] | None = None
    customer_memory: CustomerMemory | None = None
    conversation_short_id: str | None = None
    customer_open_id: str | None = None
    account_open_id: str | None = None
    direct_llm_policy: dict | None = None
    forbidden_words: list[str] | None = None
    # ContactState 单一可信源（R1 阻断项二）：9000 计算后注入，9100 优先消费。
    # 仅含脱敏值，不得传输完整手机号/微信号/原始待拼接号码。
    contact_state: dict | None = None
    contact_action: str | None = None
    contact_state_source: str | None = None


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
    # A7：轻量可观测字段（不记录完整 Prompt/手机号/微信号/历史/审核轨迹）
    prompt_version: str | None = None
    prompt_template_hash: str | None = None
    rag_policy_version: str | None = None
    llm_call_count: int | None = None
    llm_primary_ms: int | None = None
    llm_retry_ms: int | None = None
    reply_char_count: int | None = None
    reply_sentence_count: int | None = None
    reply_question_count: int | None = None
    reply_suggestion_total_ms: int | None = None
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


# ========== Phase 9 Task 4：9100 回访判定协议 ==========


class ReturnVisitPromptInput(BaseModel):
    """单条回访提示词输入（9000 从 DB 读 ReturnVisitPrompt 传入，9100 不读 DB）。"""

    model_config = {"extra": "forbid"}
    template_text: str = Field(..., min_length=1, max_length=500)
    fallback_message: str = Field(..., min_length=1, max_length=500)
    confidence_threshold: float = Field(..., ge=0.50, le=1.00)
    enabled: bool
    scene_description: str | None = Field(default=None, max_length=500)


class ReturnVisitJudgeRequest(BaseModel):
    """9000 → 9100 回访判定请求（extra=forbid 拒绝未知字段）。"""

    model_config = {"extra": "forbid"}
    tenant_id: str | None = Field(default=None, max_length=128)
    merchant_id: str = Field(..., min_length=1, max_length=128)
    lead_id: int
    prompts: dict[str, ReturnVisitPromptInput]
    sales_reply_text: str = Field(..., min_length=1)
    dispatch_context: dict


# 判定来源仍为枚举；场景键与判定结果放宽为 str，支持管理员自定义场景。
JudgementSource = Literal["llm", "keyword_fallback", "precheck"]
RiskFlagValue = Literal[
    "prompt_injection",
    "sensitive_info",
    "off_topic",
    "duplicate",
    "policy_violation",
    "model_refusal",
]


class ReturnVisitJudgment(BaseModel):
    """回访判定输出。prompt_key/judgement_result 为 str 支持自定义场景；
    非场景结果（ambiguous/no_match/below_threshold/prompt_disabled/suppress_hit/blocked）仍由代码生成。"""

    prompt_key: str | None
    confidence: float = Field(..., ge=0, le=1)
    should_trigger: bool
    suggested_message: str | None = Field(default=None, max_length=500)
    judgement_source: JudgementSource
    judgement_result: str
    model: str | None = Field(default=None, max_length=128)
    risk_flags: list[RiskFlagValue] = Field(default_factory=list, max_length=8)
    ambiguous: bool = False


# ========== Phase 12 Task 4：9100 AI 剪辑严格规划协议 ==========


class TranscriptSegment(BaseModel):
    """主素材转写段（转写文本 + 时间区间 + 素材 ID）。extra=forbid 拒绝未知字段。"""

    model_config = {"extra": "forbid"}
    material_id: str = Field(..., min_length=1, max_length=64)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    text: str = Field(..., min_length=1, max_length=2000)


class SceneSummary(BaseModel):
    """镜头标签 + 稳定性摘要（不含原媒体/图片）。extra=forbid 拒绝未知字段。"""

    model_config = {"extra": "forbid"}
    material_id: str = Field(..., min_length=1, max_length=64)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    scene_label: str = Field(..., min_length=1, max_length=64)
    stability_score: float | None = Field(default=None, ge=0, le=1)


class AiEditPlanRequest(BaseModel):
    """9000 → 9100 剪辑规划请求（设计 §9：只发转写文本、镜头标签、时长、稳定性摘要）。

    extra=forbid 拒绝原媒体路径、图片、模型原始响应等不应进入规划的字段。
    target_duration_seconds 限定 15-60 秒；transcript_segments/scenes 至少各一段。
    """

    model_config = {"extra": "forbid"}
    merchant_id: str = Field(..., min_length=1, max_length=128)
    job_id: str = Field(..., min_length=1, max_length=64)
    template_key: str = Field(..., min_length=1, max_length=64)
    template_version: str = Field(..., min_length=1, max_length=64)
    target_duration_seconds: int = Field(..., ge=15, le=60)
    transcript_segments: list[TranscriptSegment] = Field(..., min_length=1)
    scenes: list[SceneSummary] = Field(..., min_length=1)


EditAction = Literal["keep", "remove", "broll_replace"]
PlanStatus = Literal["ok", "blocked", "failed"]


class PlanOperation(BaseModel):
    """单条剪辑操作（从 LLM 输出解析，extra=forbid 拒绝未知字段）。

    action 仅 keep/remove/broll_replace；每段引用真实素材 ID 与合法时间区间。
    """

    model_config = {"extra": "forbid"}
    material_id: str = Field(..., min_length=1, max_length=64)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)
    action: EditAction
    reason: str | None = Field(default=None, max_length=128)


class AiEditPlan(BaseModel):
    """剪辑计划输出（版本化；失败返回稳定错误码，不返回伪造操作）。

    - status=ok：operations 经保守校验通过；
    - status=blocked：注入/拒答，不调/不兜底，operations 为空；
    - status=failed：空输出/越界/未知素材/重叠/非法动作/模型异常，operations 为空。
    """

    status: PlanStatus
    plan_version: str
    operations: list[PlanOperation] = Field(default_factory=list)
    failure_code: str | None = None
    model: str | None = Field(default=None, max_length=128)


# ========== P0-B：Schema 2.0 强类型响应模型 ==========


class PrimaryAction(str, Enum):
    ANSWER_QUESTION = "ANSWER_QUESTION"
    OFF_PLATFORM_DETAIL_HANDOFF = "OFF_PLATFORM_DETAIL_HANDOFF"
    ACKNOWLEDGE_INTENT = "ACKNOWLEDGE_INTENT"
    HANDOFF_TO_HUMAN = "HANDOFF_TO_HUMAN"


class ContactAction(str, Enum):
    LEGACY_DELEGATED = "LEGACY_DELEGATED"
    ASK_CONTACT_FIRST_TIME = "ASK_CONTACT_FIRST_TIME"
    ASK_CONTACT_COMPLETION = "ASK_CONTACT_COMPLETION"
    ACK_CONTACT_RECEIVED = "ACK_CONTACT_RECEIVED"
    NO_CONTACT_ACTION = "NO_CONTACT_ACTION"


class ContactClaim(str, Enum):
    NOT_RECEIVED = "NOT_RECEIVED"
    RECEIVED = "RECEIVED"


class DeliveryMode(str, Enum):
    SINGLE_MESSAGE = "SINGLE_MESSAGE"


class ReplyMessagePurpose(str, Enum):
    ANSWER = "answer"
    FOLLOW_UP = "follow_up"
    CONTACT_REQUEST = "contact_request"
    HANDOFF = "handoff"


class ReplyPolicyDecisionData(BaseModel):
    """ReplyPolicyDecision 强类型序列化模型。"""

    primary_action: PrimaryAction
    contact_action: ContactAction
    contact_claim: ContactClaim
    contact_request_policy_enforced: bool
    salutation: str
    must_not_claim_contact_received: bool | None = None
    must_not_repeat_full_contact_request: bool | None = None
    may_request_contact_completion: bool | None = None
    delivery_mode: DeliveryMode = DeliveryMode.SINGLE_MESSAGE
    max_messages: int = Field(default=1, ge=1, le=1)
    policy_reason_codes: list[str] = Field(default_factory=list)


class ReplyMessageData(BaseModel):
    """单条回复消息。P0-B 严格 sequence=1。"""

    sequence: int = Field(ge=1, le=1)
    purpose: ReplyMessagePurpose
    text: str

    @field_validator("text")
    @classmethod
    def text_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text 去除空白后不得为空")
        return v


class ReplySuggestionResponseV2(BaseModel):
    """Schema 2.0 响应。Enabled 模式返回；Legacy/Shadow 返回原 ReplySuggestionResponse。

    约束：
    - output_schema_version 固定 "2.0"，必填
    - decision 必填
    - messages 必填且恰好 1 条
    - reply_text == messages[0].text
    含完整 Legacy 字段，供 9000 兼容消费。
    """

    # Schema 2.0 必填字段
    reply_text: str
    output_schema_version: Literal["2.0"]
    decision: ReplyPolicyDecisionData
    messages: list[ReplyMessageData]

    @field_validator("messages")
    @classmethod
    def messages_exactly_one(cls, v: list[ReplyMessageData]) -> list[ReplyMessageData]:
        if len(v) != 1:
            raise ValueError("P0-B messages 必须恰好 1 条")
        return v

    @model_validator(mode="after")
    def reply_text_equals_messages_0_text(self) -> "ReplySuggestionResponseV2":
        if self.messages and self.reply_text != self.messages[0].text:
            raise ValueError("reply_text 必须等于 messages[0].text")
        return self

    # Legacy 字段（与 ReplySuggestionResponse 一致，供 9000 兼容消费）
    match_level: str = "rag_llm_reply"
    target_category: str | None = None
    target_vehicle_name: str | None = None
    recommended_vehicles: list[RecommendedVehicle] = Field(default_factory=list)
    lead_capture_required: bool = False
    confidence: float = 0.0
    manual_required: bool = False
    auto_send: bool = False
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
    prompt_version: str | None = None
    prompt_template_hash: str | None = None
    rag_policy_version: str | None = None
    llm_call_count: int | None = None
    llm_primary_ms: int | None = None
    llm_retry_ms: int | None = None
    reply_char_count: int | None = None
    reply_sentence_count: int | None = None
    reply_question_count: int | None = None
    reply_suggestion_total_ms: int | None = None
    error_code: str | None = None
    timeout_layer: str | None = None
    elapsed_ms: int | None = None
    timeout_seconds: float | None = None
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None
