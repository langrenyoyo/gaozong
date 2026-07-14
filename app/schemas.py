"""Pydantic 请求/响应模型"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

# Phase 8 Task 3：trace_url 安全校验用控制字符集，禁止 \x00-\x1f 与 \x7f
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _safe_load_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_contact_values(all_contacts: Any) -> list[str]:
    values: list[str] = []
    if isinstance(all_contacts, str):
        stripped = all_contacts.strip()
        if not stripped:
            return values
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return [stripped]
        return _extract_contact_values(parsed)
    if isinstance(all_contacts, dict):
        for key in ("all", "phones", "wechats", "values"):
            for item in _extract_contact_values(all_contacts.get(key)):
                if item not in values:
                    values.append(item)
        return values
    if not isinstance(all_contacts, list):
        return values
    for item in all_contacts:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def _extract_first_string(data: dict, keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ========== Raw webhook event read-only query ==========


class WebhookEventOut(BaseModel):
    """Raw webhook event list item."""

    id: int
    event: Optional[str] = None
    from_user_id: Optional[str] = None
    to_user_id: Optional[str] = None
    body_open_id: Optional[str] = None
    body_account_open_id: Optional[str] = None
    content_open_id: Optional[str] = None
    content_account_open_id: Optional[str] = None
    nick_name: Optional[str] = None
    avatar: Optional[str] = None
    from_user_nick_name: Optional[str] = None
    from_user_avatar: Optional[str] = None
    to_user_nick_name: Optional[str] = None
    to_user_avatar: Optional[str] = None
    event_key: Optional[str] = None
    is_duplicate: bool = False
    lead_id: Optional[int] = None
    lead_action: str
    created_at: Optional[datetime] = None
    server_message_id: Optional[str] = None
    conversation_short_id: Optional[str] = None
    message_text: Optional[str] = None
    contact_extract_status: Optional[str] = None
    customer_contact: Optional[str] = None
    failure_reason: Optional[str] = None


class WebhookEventDetailOut(WebhookEventOut):
    """Raw webhook event detail."""

    raw_body: Optional[dict] = None


class WebhookEventListData(BaseModel):
    """Raw webhook event paginated data."""

    page: int
    page_size: int
    total: int
    items: list[WebhookEventOut]


class WebhookEventListResponse(BaseModel):
    """Raw webhook event list response."""

    success: bool = True
    data: WebhookEventListData
    message: str = "success"


class WebhookEventDetailResponse(BaseModel):
    """Raw webhook event detail response."""

    success: bool = True
    data: WebhookEventDetailOut
    message: str = "success"


# ========== AI小高智能体 ==========


class AiAgentCreate(BaseModel):
    """AI小高智能体创建请求。"""

    name: str = Field(..., min_length=1, max_length=100)
    prompt: str = ""
    knowledge_base_text: str = ""
    avatar_url: Optional[str] = None


class AiAgentUpdate(BaseModel):
    """AI小高智能体更新请求。"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    prompt: Optional[str] = None
    knowledge_base_text: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|disabled)$")


class AiAgentOut(BaseModel):
    """AI小高智能体响应。"""

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


class AiAgentTrainingChatRequest(BaseModel):
    """AI小高智能体训练预览请求。"""

    message: str = Field(..., min_length=1)


class AiAgentTrainingChatResponseData(BaseModel):
    """AI小高智能体训练预览结果。"""

    reply_text: str
    warnings: list[str] = []
    llm_used: bool = False
    knowledge_used: bool = True


class AiAgentResponse(BaseModel):
    """AI小高智能体单项响应包装。"""

    success: bool = True
    data: AiAgentOut
    message: str = "success"


class AiAgentListResponse(BaseModel):
    """AI小高智能体列表响应包装。"""

    success: bool = True
    data: list[AiAgentOut]
    message: str = "success"


class AiAgentTrainingChatResponse(BaseModel):
    """AI小高智能体训练预览响应包装。"""

    success: bool = True
    data: AiAgentTrainingChatResponseData
    message: str = "success"


class AiAgentPreviewRequest(BaseModel):
    """AI小高智能体草稿预览请求。"""

    agent_id: Optional[str] = None
    name: str = Field("", max_length=100)
    persona_prompt: str = ""
    knowledge_prompt: str = ""
    knowledge_category_keys: list[str] = Field(default_factory=list)
    message: str = Field(..., min_length=1)


class AiAgentPreviewResponseData(BaseModel):
    """AI小高智能体草稿预览结果。"""

    reply_text: str = ""
    source: str = "llm"
    used_category_keys: list[str] = Field(default_factory=list)
    source_chunks: list[dict] = Field(default_factory=list)
    manual_required: bool = False
    error: Optional[str] = None
    llm_used: bool = False
    rag_used: bool = False
    auto_send: bool = False
    warnings: list[str] = Field(default_factory=list)


class AiAgentPreviewResponse(BaseModel):
    """AI小高智能体草稿预览响应包装。"""

    success: bool = True
    data: AiAgentPreviewResponseData
    message: str = "success"


class KnowledgeCategoryOut(BaseModel):
    """知识分类展示项。"""

    category_key: str
    name: str
    scope_type: str
    is_base: bool = False


class KnowledgeCategoryCreate(BaseModel):
    """知识分类创建请求。"""

    category_key: str
    name: str


class KnowledgeCategoryListResponse(BaseModel):
    """知识分类列表响应包装。"""

    success: bool = True
    data: list[KnowledgeCategoryOut]
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


# ========== Agent status read-only query ==========


class AgentStatusData(BaseModel):
    """Conservative server-side Local Agent status for merchant UI guards."""

    agent_online: bool = False
    agent_status: str = "offline"
    wechat_available: str = "unknown"
    wechat_status: str = "unknown"
    automation_enabled: bool = True
    emergency_stopped: bool = False
    action_in_progress: bool = False
    current_task_id: Optional[int] = None
    current_task_type: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None
    last_checked_at: datetime
    can_run_wechat_action: bool = False
    disabled_reason: str
    status_source: str = "server_only"


class AgentStatusResponse(BaseModel):
    """Agent status response wrapper."""

    success: bool = True
    data: AgentStatusData
    message: str = "success"


# ========== 销售人员 ==========

class AgentHeartbeatRequest(BaseModel):
    """Local Agent heartbeat payload posted to the 9000 server."""

    agent_client_id: str = Field(..., min_length=1)
    agent_name: Optional[str] = None
    host_name: Optional[str] = None
    agent_status: str = Field(..., min_length=1)
    wechat_status: str = Field(..., min_length=1)
    current_task_id: Optional[int] = None
    current_task_type: Optional[str] = None
    version: Optional[str] = None


class AgentHeartbeatData(BaseModel):
    """Local Agent heartbeat acknowledgement data."""

    received: bool = True
    server_time: datetime
    next_heartbeat_seconds: int


class AgentHeartbeatResponse(BaseModel):
    """Local Agent heartbeat response wrapper."""

    success: bool = True
    data: AgentHeartbeatData
    message: str = "success"


class DouyinLiveCheckAuthUrlResponse(BaseModel):
    """Douyin live-check auth URL response wrapper."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinLiveCheckObserveResponse(BaseModel):
    """Douyin live-check observation response wrapper."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinLiveCheckStatusResponse(BaseModel):
    """Douyin live-check status response wrapper."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinLiveCheckAccountsResponse(BaseModel):
    """Douyin live-check authorized account list response wrapper."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinBindInfoSyncRequest(BaseModel):
    """Request for manually syncing Douyin OpenAPI list_bind_info."""

    page_num: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)
    name_or_open_id: Optional[str] = None


class DouyinBindInfoSyncResponse(BaseModel):
    """Douyin list_bind_info sync response wrapper."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinPrivateMessageSendRequest(BaseModel):
    """Manual-only Douyin private message send request."""

    conversation_short_id: str = Field(..., min_length=1)
    customer_open_id: Optional[str] = None
    content: str = Field(..., min_length=1)
    scene: Optional[str] = None
    manual_confirmed: bool = False
    operator_id: Optional[str] = None


class DouyinPrivateMessageSendResponse(BaseModel):
    """Manual-only Douyin private message send response."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinResourceDownloadRequest(BaseModel):
    """Douyin media resource download request."""

    conversation_short_id: str = Field(..., min_length=1)
    server_message_id: Optional[str] = None
    open_id: Optional[str] = None
    media_type: Optional[str] = None
    url: Optional[str] = None


class DouyinResourceDownloadResponse(BaseModel):
    """Douyin media resource download response."""

    success: bool = True
    data: dict
    message: str = "success"


class DouyinImageUploadRequest(BaseModel):
    """抖音图片 base64 上传请求。"""

    file_name: str
    image_base64: str
    open_id: Optional[str] = None


class DouyinImageUploadResponse(BaseModel):
    """抖音图片上传响应。"""

    success: bool = True
    data: dict
    message: str = "success"


class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="销售姓名")
    wechat_id: Optional[str] = Field(None, description="微信号")
    wechat_nickname: Optional[str] = Field(None, description="微信昵称")
    phone: Optional[str] = Field(None, description="手机号")
    # 小高 AI 一期：销售规则布尔字段（5 项）
    enable_lead_assignment: bool = Field(True, description="是否参与线索分配，默认 true")
    enable_short_video_live_lead_report: bool = Field(False, description="是否接收短视频/直播留资管理表")
    enable_daily_sales_feedback_report: bool = Field(False, description="是否接收每日线索销售反馈表")
    enable_lead_trace_report: bool = Field(False, description="是否接收线索溯源表")
    enable_sales_unit_cost_report: bool = Field(False, description="是否接收销售单车成本表")


class StaffUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    wechat_id: Optional[str] = None
    wechat_nickname: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|disabled|deleted)$")
    # 小高 AI 一期：销售规则布尔字段（5 项）
    enable_lead_assignment: Optional[bool] = None
    enable_short_video_live_lead_report: Optional[bool] = None
    enable_daily_sales_feedback_report: Optional[bool] = None
    enable_lead_trace_report: Optional[bool] = None
    enable_sales_unit_cost_report: Optional[bool] = None


class StaffOut(BaseModel):
    id: int
    name: str
    wechat_id: Optional[str] = None
    wechat_nickname: Optional[str] = None
    phone: Optional[str] = None
    status: str
    merchant_id: Optional[str] = None
    # 小高 AI 一期：销售规则布尔字段（5 项）
    enable_lead_assignment: bool = True
    enable_short_video_live_lead_report: bool = False
    enable_daily_sales_feedback_report: bool = False
    enable_lead_trace_report: bool = False
    enable_sales_unit_cost_report: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ========== 抖音线索 ==========

class LeadCreate(BaseModel):
    source: str = Field("douyin", description="来源平台")
    lead_type: Optional[str] = Field(None, description="线索类型")
    customer_name: Optional[str] = Field(None, description="客户名称")
    customer_contact: Optional[str] = Field(None, description="联系方式")
    content: Optional[str] = Field(None, description="线索内容")
    source_url: Optional[str] = Field(None, description="来源链接")
    source_id: Optional[str] = Field(None, description="来源平台ID")
    raw_data: Optional[str] = Field(None, description="原始数据JSON")


class LeadAssign(BaseModel):
    staff_id: int = Field(..., description="分配的销售ID")
    remark: Optional[str] = Field(None, description="分配备注")


class LeadOut(BaseModel):
    id: int
    source: str
    lead_type: Optional[str] = None
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    source_channel: Optional[str] = None
    city: Optional[str] = None
    car_model: Optional[str] = None
    car_year: Optional[str] = None
    budget: Optional[str] = None
    all_extracted_contacts: list[str] = Field(default_factory=list)
    contact_extract_status: Optional[str] = None
    original_message_text: Optional[str] = None
    content: Optional[str] = None
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    merchant_id: Optional[str] = None
    account_open_id: Optional[str] = None
    conversation_short_id: Optional[str] = None
    assigned_staff_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    status: str
    display_status: Optional[str] = None
    status_label: Optional[str] = None
    status_reason: Optional[str] = None
    lead_score: Optional[dict] = None
    # 销售跟进状态（纯派生）：no_feedback 未反馈 / contacted 已联系 / contact_invalid 联系方式错误
    sales_followup_status: Optional[str] = None
    sales_followup_label: Optional[str] = None
    assigned_staff: Optional[dict] = None
    timeline: list[dict] = Field(default_factory=list)
    # PG jsonb 列读出 dict，SQLite Text 读出 str；validator 已用 _safe_load_json_object 统一处理。
    # 声明 Any 避免 Pydantic 在 validator 之后对 PG dict 做类型拒绝（/leads 500）。
    raw_data: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def derive_contact_extract_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": getattr(value, "id", None),
                "source": getattr(value, "source", None),
                "lead_type": getattr(value, "lead_type", None),
                "customer_name": getattr(value, "customer_name", None),
                "customer_contact": getattr(value, "customer_contact", None),
                "phone": getattr(value, "extracted_phone", None),
                "wechat": getattr(value, "extracted_wechat", None),
                "all_extracted_contacts": _extract_contact_values(getattr(value, "all_extracted_contacts", None)),
                "contact_extract_status": getattr(value, "contact_extract_status", None),
                "original_message_text": getattr(value, "raw_message_text", None),
                "content": getattr(value, "content", None),
                "source_url": getattr(value, "source_url", None),
                "source_id": getattr(value, "source_id", None),
                "source_channel": getattr(value, "source_channel", None),
                "merchant_id": getattr(value, "merchant_id", None),
                "account_open_id": getattr(value, "account_open_id", None),
                "conversation_short_id": getattr(value, "conversation_short_id", None),
                "city": getattr(value, "city", None),
                "car_model": getattr(value, "car_model", None),
                "car_year": getattr(value, "car_year", None),
                "budget": getattr(value, "budget", None),
                "assigned_staff_id": getattr(value, "assigned_staff_id", None),
                "assigned_at": getattr(value, "assigned_at", None),
                "status": getattr(value, "status", None),
                "display_status": getattr(value, "display_status", None),
                "status_label": getattr(value, "status_label", None),
                "status_reason": getattr(value, "status_reason", None),
                "lead_score": getattr(value, "lead_score", None),
                "sales_followup_status": getattr(value, "sales_followup_status", None),
                "sales_followup_label": getattr(value, "sales_followup_label", None),
                "assigned_staff": getattr(value, "assigned_staff", None),
                "timeline": getattr(value, "timeline", []),
                "raw_data": getattr(value, "raw_data", None),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
            }

        raw_data = _safe_load_json_object(data.get("raw_data"))
        contact_extract = raw_data.get("contact_extract")
        if not isinstance(contact_extract, dict):
            contact_extract = {}

        data["phone"] = data.get("phone") or contact_extract.get("phone")
        data["wechat"] = data.get("wechat") or contact_extract.get("wechat")
        data.setdefault("source_channel", _extract_first_string(raw_data, ("source_channel", "source")))
        data.setdefault("city", _extract_first_string(raw_data, ("city", "location", "location_city", "customer_city")))
        data.setdefault("car_model", _extract_first_string(raw_data, ("intent_car", "car_model", "vehicle_model", "intent_car_model", "model", "series", "brand_model")))
        data.setdefault("car_year", _extract_first_string(raw_data, ("car_year", "year", "vehicle_year", "model_year", "years")))
        data.setdefault("budget", _extract_first_string(raw_data, ("budget", "intent_budget", "budget_range", "price_range")))
        data.setdefault("contact_extract_status", contact_extract.get("status"))
        data.setdefault(
            "original_message_text",
            raw_data.get("raw_message_text") or data.get("content"),
        )

        contact_values = _extract_contact_values(data.get("all_extracted_contacts"))
        for item in _extract_contact_values(contact_extract.get("all_contacts")):
            if item not in contact_values:
                contact_values.append(item)
        for item in (data.get("phone"), data.get("wechat"), data.get("customer_contact")):
            if isinstance(item, str) and item.strip() and item.strip() not in contact_values:
                contact_values.append(item.strip())
        data["all_extracted_contacts"] = contact_values
        return data

    model_config = {"from_attributes": True}


class LeadListData(BaseModel):
    """线索列表分页数据。"""

    page: int
    page_size: int
    total: int
    items: list[LeadOut]


class LeadListResponse(BaseModel):
    """线索列表分页响应。"""

    success: bool = True
    data: LeadListData
    message: str = "success"


class LeadWechatNotifyStatus(BaseModel):
    """线索微信通知资格只读状态。"""

    allowed: bool
    reason: str
    message: str
    status: str
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    existing_task_id: Optional[int] = None
    existing_notification_id: Optional[int] = None
    # Phase 7-FIX1：限频时返回建议等待秒数，前端据此显示倒计时
    retry_after_seconds: Optional[int] = None


# ========== 手动回复 ==========

class ManualReply(BaseModel):
    lead_id: int = Field(..., description="线索ID")
    staff_id: int = Field(..., description="销售ID")
    reply_content: str = Field(..., min_length=1, description="回复内容")


# ========== 回复检测 ==========

class CheckOut(BaseModel):
    id: int
    lead_id: int
    staff_id: int
    reply_deadline: Optional[datetime] = None
    actual_reply_at: Optional[datetime] = None
    reply_content: Optional[str] = None
    is_effective: int = 0
    effectiveness_reason: Optional[str] = None
    check_status: str = "pending"
    checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ========== 报表 ==========

class ReportSummary(BaseModel):
    total_leads: int = 0
    assigned_count: int = 0
    retained_contact_count: int = 0
    high_intent_count: int = 0
    yesterday_total_leads: int = 0
    today_new_leads: int = 0
    lead_growth_rate: Optional[float] = None
    sales_response_rate: Optional[float] = None
    retained_contact_rate: Optional[float] = None
    # 语义别名（D4）：与 retained_* 数值一致，便于前端语义化展示
    converted_leads: int = 0
    conversion_rate: Optional[float] = None
    high_intent_hint: Optional[str] = None
    replied_count: int = 0
    timeout_count: int = 0
    pending_count: int = 0
    staff_stats: list = []


class StaffStatItem(BaseModel):
    staff_id: int
    staff_name: str
    total_assigned: int = 0
    replied_count: int = 0
    timeout_count: int = 0
    reply_rate: float = 0.0


# ========== 微信 UI 自动化检测 ==========

class WechatDetectRequest(BaseModel):
    lead_id: int = Field(..., description="线索ID")
    staff_id: int = Field(..., description="销售ID")
    max_messages: int = Field(20, ge=5, le=100, description="最多读取的消息条数")
    confirm_current_chat: bool = Field(False, description="调用方确认当前微信窗口已打开目标销售聊天窗口")


class WechatDetectResponse(BaseModel):
    success: bool = False
    message: str = ""
    chat_title: Optional[str] = Field(None, description="当前聊天窗口标题")
    messages_read: int = Field(0, description="读取到的消息总数")
    self_messages_count: int = Field(0, description="销售本人消息数")
    detection_mode: Optional[str] = Field(None, description="检测模式: self_only / fallback_current_window_text")
    warning: Optional[str] = Field(None, description="检测警告信息（兜底模式时提示需人工确认）")
    confirmed_required: bool = Field(False, description="是否需要人工复核（兜底模式时为 true）")
    risk_level: str = Field("none", description="检测结果可信度: low / medium / high / none")
    is_effective: int = Field(0, description="是否有效回复 0/1")
    effectiveness_reason: Optional[str] = Field(None, description="判定原因")
    matched_content: Optional[str] = Field(None, description="匹配到的有效回复内容")
    check_status: str = Field("pending_check", description="检测状态")


# ========== 反馈模块（P3：主机微信 B → 数据源微信 A） ==========


class FeedbackComposeRequest(BaseModel):
    """反馈文本生成请求"""
    lead_id: int = Field(..., description="线索 ID")
    dry_run: bool = Field(True, description="只生成文本，不入库、不写微信（默认 true）")
    require_confirm: bool = Field(True, description="写入输入框后不自动回车（默认 true）")


class FeedbackComposeResponse(BaseModel):
    """反馈文本生成响应"""
    success: bool = False
    message: str = ""
    lead_id: Optional[int] = Field(None, description="线索 ID")
    lead_status: Optional[str] = Field(None, description="线索当前状态")
    staff_name: Optional[str] = Field(None, description="销售姓名")
    customer_name: Optional[str] = Field(None, description="客户名称")
    reply_content: Optional[str] = Field(None, description="销售回复内容")
    actual_reply_at: Optional[datetime] = Field(None, description="实际回复时间")
    feedback_text: Optional[str] = Field(None, description="生成的反馈文本")
    dry_run: bool = Field(True, description="是否 dry_run 模式")
    record_id: Optional[int] = Field(None, description="反馈记录 ID（dry_run 时为 null）")
    feedback_status: Optional[str] = Field(None, description="记录状态（dry_run 时为 null）")


class FeedbackSendRequest(BaseModel):
    """反馈文本发送请求"""
    record_id: int = Field(..., description="反馈记录 ID")
    require_confirm: bool = Field(True, description="写入后不自动回车（默认 true）")
    confirm_chat_title: Optional[str] = Field(None, description="预期聊天窗口标题，不匹配则拒绝写入")


class FeedbackSendResponse(BaseModel):
    """反馈文本发送响应"""
    success: bool = False
    message: str = ""
    record_id: Optional[int] = Field(None, description="反馈记录 ID")
    feedback_text: Optional[str] = Field(None, description="写入的反馈文本")
    chat_title: Optional[str] = Field(None, description="当前聊天窗口标题")
    require_confirm: bool = Field(True, description="是否需要人工确认回车")
    action: Optional[str] = Field(None, description="实际动作: pasted_only / pasted_and_sent")
    warning: Optional[str] = Field(None, description="风险提示")


class FeedbackRecordOut(BaseModel):
    """反馈记录输出"""
    id: int
    lead_id: int
    staff_id: int
    check_id: Optional[int] = None
    feedback_text: Optional[str] = None
    feedback_status: str
    send_mode: Optional[str] = None
    chat_title: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FeedbackRecordsResponse(BaseModel):
    """反馈记录列表响应"""
    total: int = 0
    records: list[FeedbackRecordOut] = []


# ========== P4-1：douyinAPI 线索同步（dry_run 预览） ==========


class DouyinSyncRequest(BaseModel):
    """douyinAPI 线索同步请求"""
    dry_run: bool = Field(True, description="预览模式，不写库（默认 true）")
    limit: int = Field(50, ge=1, le=200, description="拉取数量上限")
    lead_status: str = Field("pending", description="过滤线索状态")
    start_time: Optional[int] = Field(None, description="起始时间（毫秒时间戳）")
    auto_assign: bool = Field(False, description="是否自动分配（仅对新建线索生效，P4-3 已支持）")
    auto_notify: bool = Field(False, description="分配后自动搜索销售微信并发送线索通知（P8-3，旧通知链路）")
    auto_create_wechat_task: bool = Field(
        False,
        description="分配后创建 WechatTask(pending) 任务（P0-5A，新 Local Agent 队列，不执行微信自动化）",
    )


class DouyinSyncItem(BaseModel):
    """单条线索映射结果"""
    source_id: Optional[str] = Field(None, description="来源平台 ID（open_id）")
    customer_name: Optional[str] = Field(None, description="客户名称")
    content: Optional[str] = Field(None, description="线索内容")
    source: Optional[str] = Field(None, description="来源平台")
    lead_type: Optional[str] = Field(None, description="线索类型")
    customer_contact: Optional[str] = Field(None, description="联系方式")
    raw_data: Optional[dict] = Field(None, description="原始数据")
    action: Optional[str] = Field(None, description="预判动作: create / update / skip")
    reason: Optional[str] = Field(None, description="动作原因说明")


class WechatTaskSyncStats(BaseModel):
    """P0-5A：同步过程中 WechatTask 创建统计"""
    auto_create_enabled: bool = Field(False, description="是否启用了 auto_create_wechat_task")
    created_count: int = Field(0, description="成功创建的任务数")
    skipped_count: int = Field(0, description="跳过的任务数（非 Aw3 销售）")
    task_ids: list[int] = Field([], description="成功创建的任务 ID 列表")
    skipped: list[dict] = Field([], description="跳过详情 [{lead_id, reason}]")


class DouyinSyncResponse(BaseModel):
    """douyinAPI 线索同步响应"""
    success: bool = False
    message: str = ""
    fetched: int = Field(0, description="从上游拉取的线索数")
    mapped: int = Field(0, description="映射后的线索数")
    created: int = Field(0, description="新建数（dry_run 时为 0）")
    updated: int = Field(0, description="更新数（dry_run 时为 0）")
    skipped: int = Field(0, description="跳过数")
    assigned: int = Field(0, description="自动分配数（P4-1 为 0）")
    notified: int = Field(0, description="自动通知数（P8-3，auto_notify 成功发送的线索数）")
    dry_run: bool = Field(True, description="是否 dry_run 模式")
    items: list[DouyinSyncItem] = []
    wechat_tasks: Optional[WechatTaskSyncStats] = Field(
        None, description="P0-5A：WechatTask 创建统计（仅 auto_create_wechat_task=true 时出现）",
    )


# ========== 微信自动检测 ==========

class WechatAutoDetectSetTargetRequest(BaseModel):
    """设置自动检测目标请求"""
    check_id: int = Field(..., description="要自动监听的 reply_check ID")


class WechatAutoDetectStatusResponse(BaseModel):
    """自动检测状态响应"""
    success: bool = True
    message: str = ""
    active_check_id: Optional[int] = Field(None, description="当前检测目标的 check ID，无则为 null")
    enabled: bool = Field(True, description="自动检测是否启用")
    interval_seconds: int = Field(10, description="检测间隔（秒）")
    lead_id: Optional[int] = Field(None, description="关联线索 ID")
    staff_id: Optional[int] = Field(None, description="关联销售 ID")
    customer_name: Optional[str] = Field(None, description="客户名称")
    staff_name: Optional[str] = Field(None, description="销售名称")
    check_status: Optional[str] = Field(None, description="检测记录当前状态")
    lead_status: Optional[str] = Field(None, description="线索当前状态")
    reply_deadline: Optional[str] = Field(None, description="回复截止时间")
    last_detect_at: Optional[str] = Field(None, description="上次检测时间")
    last_result: Optional[str] = Field(None, description="上次检测结果摘要")
    warning: Optional[str] = Field(None, description="安全提示")


# ========== 线索通知 ==========

class SendToStaffRequest(BaseModel):
    """发送线索给销售请求"""
    lead_id: int = Field(..., description="线索 ID")
    staff_id: Optional[int] = Field(None, description="可选销售 ID；必须与线索当前分配销售一致")
    message: Optional[str] = Field(None, description="可选通知文本；为空时使用后端模板")
    auto_send: bool = Field(True, description="是否自动发送（Demo 默认 True）")


class SendToStaffResponse(BaseModel):
    """发送线索给销售响应"""
    success: bool = True
    status: Optional[str] = Field(None, description="任务创建状态: created/existing_pending/already_sent")
    message: str = ""
    notification_id: Optional[int] = Field(None, description="通知记录 ID")
    task_id: Optional[int] = Field(None, description="微信通知任务 ID")
    lead_id: int = Field(..., description="线索 ID")
    staff_id: Optional[int] = Field(None, description="销售 ID")
    staff_name: Optional[str] = Field(None, description="销售姓名")
    wechat_nickname: Optional[str] = Field(None, description="销售微信昵称")
    chat_title: Optional[str] = Field(None, description="打开的聊天窗口标题")
    notification_text: Optional[str] = Field(None, description="实际发送的通知文本")
    send_status: Optional[str] = Field(None, description="发送状态")
    auto_detect_set: bool = Field(False, description="是否已设置自动检测目标")
    warning: Optional[str] = Field(None, description="安全提示")
    # P0-2E：联系人确认结果
    contact_verified: Optional[bool] = Field(None, description="联系人是否已确认")
    contact_verified_strategy: Optional[str] = Field(None, description="确认策略: top_title/title_profile_card/avatar_profile_card")


class NotificationRecordOut(BaseModel):
    """通知记录输出"""
    id: int
    lead_id: int
    staff_id: int
    check_id: Optional[int] = None
    notification_text: Optional[str] = None
    send_status: str
    send_mode: Optional[str] = None
    chat_title: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[str] = None
    created_at: Optional[str] = None
    # 关联信息
    customer_name: Optional[str] = None
    staff_name: Optional[str] = None
    staff_wechat_nickname: Optional[str] = None


class NotificationRecordsResponse(BaseModel):
    """通知记录列表响应"""
    total: int
    records: list[NotificationRecordOut]


class OpenChatRequest(BaseModel):
    """打开聊天窗口请求"""
    nickname: str = Field(..., min_length=1, description="销售微信昵称")


# ========== P0-5A：微信任务队列 ==========

class WechatTaskCreateRequest(BaseModel):
    """创建微信任务请求"""
    lead_id: Optional[int] = Field(None, description="关联线索 ID")
    staff_id: Optional[int] = Field(None, description="关联销售 ID")
    reply_check_id: Optional[int] = Field(None, description="关联检测记录 ID")
    task_type: str = Field("notify_sales", description="任务类型: notify_sales / detect_reply")
    target_nickname: str = Field(..., min_length=1, description="目标微信联系人昵称")
    message: str = Field("", description="要粘贴/发送的消息内容")
    mode: str = Field("paste_only", description="执行模式: notify_sales=paste_only/single_send, detect_reply=read_only/paste_only")


class WechatTaskResultRequest(BaseModel):
    """回写微信任务结果请求"""
    success: bool = Field(..., description="Agent 执行是否成功")
    verified: bool = Field(False, description="OCR 是否验证通过")
    partial_match: bool = Field(False, description="是否部分匹配")
    manual_review_required: bool = Field(False, description="是否需要人工复核")
    pasted: bool = Field(False, description="是否已粘贴到输入框")
    sent: bool = Field(False, description="是否已真实发送；notify_sales 在 verified=true 且安全门禁通过时可为 true，detect_reply 必须为 false")
    failure_stage: Optional[str] = Field(None, description="失败阶段标识")
    agent_hostname: Optional[str] = Field(None, description="执行 Agent 的主机名")
    agent_pid: Optional[int] = Field(None, description="执行 Agent 的进程 ID")
    raw_result: Optional[dict] = Field(None, description="Agent 返回的原始结果")
    # P1-AUTO-1：detect_reply 专用字段
    detected_status: Optional[str] = Field(None, description="P1-AUTO-1：检测结果（仅 detect_reply 类型）: replied / pending / manual_review / failed / blocked")
    detect_count: Optional[int] = Field(None, description="P1-AUTO-1：累计检测次数（仅 detect_reply 类型）")


class WechatTaskResponse(BaseModel):
    """微信任务响应"""
    id: int
    task_type: str
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    reply_check_id: Optional[int] = None
    target_nickname: Optional[str] = None
    message: Optional[str] = None
    mode: str
    status: str
    failure_stage: Optional[str] = None
    raw_result: Optional[str] = None
    agent_hostname: Optional[str] = None
    agent_pid: Optional[int] = None
    pasted_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WechatTaskHistoryItem(BaseModel):
    """微信任务历史列表项，不返回完整 raw_result。"""
    id: int
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    staff_name: Optional[str] = None
    staff_wechat_nickname: Optional[str] = None
    task_type: str
    target_nickname: Optional[str] = None
    mode: str
    status: str
    sent_at: Optional[datetime] = None
    failure_stage: Optional[str] = None
    raw_result_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WechatTaskHistoryPage(BaseModel):
    """微信任务历史分页响应。"""
    items: list[WechatTaskHistoryItem]
    total: int
    page: int
    page_size: int


class OpenChatResponse(BaseModel):
    """打开聊天窗口响应"""
    success: bool = True
    message: str = ""
    nickname: str = ""
    chat_title: Optional[str] = None
    chat_verified: bool = Field(False, description="聊天窗口是否已验证（P0-2C）")
    confidence: float = Field(0.0, description="验证置信度（0.0-1.0）")
    warning: Optional[str] = None
    attempts: int = Field(0, description="尝试次数")
    input_box_found: bool = Field(False, description="是否找到输入框")
    message_list_found: bool = Field(False, description="是否找到消息列表")
    failure_stage: Optional[str] = Field(None, description="失败阶段")
    debug_steps: list = Field([], description="详细调试步骤")
    debug_screenshots: list = Field([], description="调试截图路径列表（P0-2C）")


# ========== P0-REPLY-2：Local Agent 回复检测回写 ==========

class AgentMessage(BaseModel):
    """Local Agent 读取的单条微信消息"""
    sender: str = Field("unknown", description="发送方: self / friend / system / unknown")
    content: Optional[str] = Field(None, description="消息文本内容")
    sender_debug: Optional[dict] = Field(None, description="P0-REPLY-3B：发送方识别调试信息")
    index: Optional[int] = Field(None, description="Phase 9：消息 UI 序号，回访触发锚点按 index 升序定位")


class AgentResult(BaseModel):
    """Local Agent 检测执行结果摘要"""
    success: bool = Field(False, description="Agent 检测流程是否成功完成")
    failure_stage: Optional[str] = Field(None, description="失败阶段标识")
    raw_result: Optional[dict] = Field(None, description="原始诊断数据")


class AgentWriteBackRequest(BaseModel):
    """Local Agent 回写请求：将客户电脑 B 微信消息发送给主系统分析"""
    lead_id: int = Field(..., description="线索 ID")
    staff_id: int = Field(..., description="销售 ID")
    task_id: Optional[int] = Field(None, description="关联任务 ID")
    target_nickname: str = Field("Aw3", description="目标联系人昵称")
    messages: list[AgentMessage] = Field(default_factory=list, description="从微信读取的消息列表")
    agent_result: AgentResult = Field(default_factory=AgentResult, description="Agent 执行结果")


class AgentWriteBackResponse(BaseModel):
    """主系统分析回写响应"""
    success: bool = Field(False, description="分析是否成功完成")
    detected_status: str = Field("pending", description="检测结果: replied / pending / manual_review / failed")
    check_id: Optional[int] = Field(None, description="匹配的 reply_check ID")
    matched_reply: Optional[str] = Field(None, description="匹配到的有效回复文本")
    effectiveness_reason: Optional[str] = Field(None, description="判定原因")
    message: str = ""


class ReturnVisitPromptUpdateRequest(BaseModel):
    """管理员更新回访提示词请求（Phase 9 Task 8）。

    严格校验：template_text/fallback_message 1..500；confidence_threshold 0.50..1.00；
    enabled bool；reason 非空；未知字段 422（extra=forbid）。
    """

    model_config = {"extra": "forbid"}

    template_text: str = Field(..., min_length=1, max_length=500)
    fallback_message: str = Field(..., min_length=1, max_length=500)
    confidence_threshold: float = Field(..., ge=0.50, le=1.00)
    enabled: bool
    reason: str = Field(..., min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_non_empty_after_strip(cls, v: str) -> str:
        # 审计合同：reason 非空；min_length 拦不住纯空白（"   " 长度≥1），须 strip 后校验
        if not v.strip():
            raise ValueError("reason 不能为纯空白")
        return v


# ========== 抖音 GMP Webhook ==========


class WebhookResponse(BaseModel):
    """Webhook 接收响应"""
    code: int = Field(0, description="响应码：0=成功")
    msg: str = Field("success", description="响应消息")
    event_id: Optional[int] = Field(None, description="事件记录 ID")
    lead_id: Optional[int] = Field(None, description="线索 ID（仅 im_receive_msg 时有值）")
    is_new_lead: bool = Field(False, description="是否为新创建的线索")
    is_duplicate: bool = Field(False, description="是否为重复事件")
    lead_action: str = Field("not_lead_event", description="线索动作: created/updated/skipped/not_lead_event")


# ========== 小高算力（一期 /compute） ==========


class ComputePackageOut(BaseModel):
    """算力套餐输出。"""

    id: int
    name: str
    price_yuan: int = Field(..., description="价格（整数元）")
    token_amount: int = Field(..., description="Token 数量")
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ComputePackageCreate(BaseModel):
    """算力套餐创建请求（管理员）。"""

    name: str = Field(..., min_length=1, max_length=100, description="套餐名称")
    price_yuan: int = Field(..., ge=0, description="价格（整数元）")
    token_amount: int = Field(..., gt=0, description="Token 数量")
    enabled: bool = Field(True, description="是否启用")


class ComputePackageUpdate(BaseModel):
    """算力套餐更新请求（管理员）。"""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="套餐名称")
    price_yuan: Optional[int] = Field(None, ge=0, description="价格（整数元）")
    token_amount: Optional[int] = Field(None, gt=0, description="Token 数量")
    enabled: Optional[bool] = Field(None, description="是否启用")


class ComputeSummaryOut(BaseModel):
    """算力余额与消耗统计。"""

    merchant_id: str
    balance_tokens: int = Field(0, description="当前算力余额（Token）")
    today_consume: int = Field(0, description="今日消耗（Token）")
    yesterday_consume: int = Field(0, description="昨日消耗（Token）")
    total_consume: int = Field(0, description="累计消耗（Token）")


class ComputeTransactionOut(BaseModel):
    """算力 Token 流水。"""

    id: int
    merchant_id: str
    transaction_type: str = Field(..., description="流水类型: recharge / grant_package / consume")
    delta_tokens: int = Field(..., description="Token 变动（正为增加，负为消耗）")
    balance_after_tokens: int = Field(..., description="变动后余额")
    source: str = Field(..., description="来源: manual_recharge / package_grant / llm / embedding / other")
    remark: Optional[str] = None
    model: Optional[str] = None
    agent_id: Optional[str] = None
    conversation_id: Optional[int] = None
    created_at: Optional[datetime] = None
    # Phase 10 §0.2 计费快照：历史/充值/套餐为 None，consume 保存实际值、能力、比例快照
    actual_tokens: Optional[int] = None
    capability_key: Optional[str] = None
    markup_basis_points: Optional[int] = None

    model_config = {"from_attributes": True}


class ComputeTransactionListData(BaseModel):
    """Token 明细分页数据。"""

    page: int
    page_size: int
    total: int
    items: list[ComputeTransactionOut]


class ComputeRechargeOrderRequest(BaseModel):
    """商户发起充值订单请求（一期 mock，不接真实支付）。"""

    package_id: Optional[int] = Field(None, description="套餐充值时传入套餐 ID")
    custom_tokens: Optional[int] = Field(None, gt=0, description="自定义金额充值 Token 数量（与 package_id 二选一）")
    pay_method: str = Field("wechat", description="支付方式: wechat / alipay")


class ComputeRechargeOrderOut(BaseModel):
    """充值订单输出（一期 mock）。"""

    order_no: str = Field(..., description="mock 订单号")
    pay_method: str = Field(..., description="支付方式")
    tokens: int = Field(..., description="本次充值 Token 数量")
    price_yuan: Optional[int] = Field(None, description="价格（元），套餐充值时有值")
    pay_qr_code: Optional[str] = Field(None, description="mock 付款码占位")
    status: str = Field("mock_pending", description="订单状态: mock_pending（一期不接真实支付）")


class ComputeAdminRechargeRequest(BaseModel):
    """管理员给商户充值 Token 请求。"""

    tokens: int = Field(..., gt=0, description="充值 Token 数量")
    remark: Optional[str] = Field(None, description="备注")


class ComputeGrantPackageRequest(BaseModel):
    """管理员给商户发放套餐请求。"""

    package_id: int = Field(..., description="套餐 ID")


class ComputeUsageRequest(BaseModel):
    """内部 AI 消耗上报请求（供 9100/19000 埋点）。

    Phase 10 §0.2：tokens 语义为实际字符量；capability_key/model 必填，source 受控。
    """

    merchant_id: str = Field(..., description="商户 ID")
    tokens: int = Field(..., gt=0, description="本次实际字符量（按能力上浮后扣费）")
    capability_key: Literal[
        "douyin-cs", "leads", "agents", "wechat-assistant", "compute", "knowledge"
    ] = Field(..., description="算力能力 key（六值之一）")
    source: Literal["llm", "embedding", "other"] = Field("llm", description="消耗来源")
    model: str = Field(..., min_length=1, max_length=128, description="模型标识")
    agent_id: Optional[str] = Field(None, description="智能体 ID")
    conversation_id: Optional[int] = Field(None, description="会话 ID")
    remark: Optional[str] = None

    model_config = {"extra": "forbid", "protected_namespaces": ()}


class ComputeSummaryResponse(BaseModel):
    """算力余额/统计响应（商户侧 summary、管理员充值/发放/usage 后均复用）。"""

    success: bool = True
    data: ComputeSummaryOut
    message: str = "success"


class ComputeTransactionListResponse(BaseModel):
    """Token 明细列表响应。"""

    success: bool = True
    data: ComputeTransactionListData
    message: str = "success"


class ComputePackageListResponse(BaseModel):
    """套餐列表响应。"""

    success: bool = True
    data: list[ComputePackageOut]
    message: str = "success"


class ComputePackageResponse(BaseModel):
    """套餐单项响应。"""

    success: bool = True
    data: ComputePackageOut
    message: str = "success"


class ComputeRechargeOrderResponse(BaseModel):
    """充值订单响应。"""

    success: bool = True
    data: ComputeRechargeOrderOut
    message: str = "success"


# ========== AI 回复决策日志 ==========


class AiReplyDecisionLogListItem(BaseModel):
    """AI 回复决策日志列表项。"""

    id: int
    merchant_id: str
    account_open_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    latest_message_summary: Optional[str] = None
    reply_text_summary: Optional[str] = None
    intent: Optional[str] = None
    lead_level: Optional[str] = None
    confidence: Optional[float] = None
    manual_required: bool
    manual_required_reason: Optional[str] = None
    risk_flags: list = Field(default_factory=list)
    tags: list = Field(default_factory=list)
    rag_used: bool
    llm_used: bool
    upstream_auto_send: bool
    final_auto_send: bool
    decision_version: Optional[str] = None
    # 发送流水字段：列表展示实发内容摘要与发送状态
    send_record_id: Optional[int] = None
    sent_content_summary: Optional[str] = None
    send_status: Optional[str] = None
    send_source: Optional[str] = None
    auto_send: bool = False
    manual_confirmed: bool = False
    upstream_msg_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    # 发送流水创建时间，用于实发时间回退展示（sent_at 优先，其次本字段，最后 created_at）
    send_created_at: Optional[datetime] = None
    model: Optional[str] = None
    is_effective: Optional[bool] = None
    effectiveness_reason: Optional[str] = None
    created_at: Optional[datetime] = None


class AiReplyDecisionLogListData(BaseModel):
    """AI 回复决策日志分页数据。"""

    page: int
    page_size: int
    total: int
    items: list[AiReplyDecisionLogListItem]


class AiReplyDecisionLogListResponse(BaseModel):
    """AI 回复决策日志列表响应。"""

    success: bool = True
    data: AiReplyDecisionLogListData
    message: str = "success"


class AiReplyDecisionLogDetail(AiReplyDecisionLogListItem):
    """AI 回复决策日志详情。"""

    latest_message: Optional[str] = None
    reply_text: Optional[str] = None
    rag_sources: list = Field(default_factory=list)
    source_chunks: list = Field(default_factory=list)
    allowed_category_keys: list = Field(default_factory=list)
    # 详情返回违禁词替换后的最终实发内容（脱敏后完整展示）
    sent_content: Optional[str] = None


class AiReplyDecisionLogDetailResponse(BaseModel):
    """AI 回复决策日志详情响应。"""

    success: bool = True
    data: AiReplyDecisionLogDetail
    message: str = "success"


# ========== 抖音自动回复配置 ==========


class DirectLlmPolicyConfig(BaseModel):
    direct_llm_auto_send_enabled: bool = False
    policy_level: Literal["conservative", "standard", "aggressive"] = "conservative"
    allow_greeting_auto_send: bool = False
    allow_general_intro_auto_send: bool = False
    allow_need_clarification_auto_send: bool = False
    allow_brand_general_intro_auto_send: bool = False
    specific_model_strategy: Literal["manual_confirm", "safe_clarify"] = "manual_confirm"
    contact_guidance_level: Literal["none", "customer_initiated_only", "soft_guidance"] = "none"
    require_rag_for_specific_inventory: bool = True
    forbid_inventory_claim: bool = True
    forbid_price_claim: bool = True
    forbid_finance_claim: bool = True
    forbid_vehicle_condition_claim: bool = True
    min_confidence_for_direct_send: float = Field(0.85, ge=0, le=1)

    model_config = {"extra": "forbid"}


class DouyinAutoreplySettingsUpdate(BaseModel):
    """抖音企业号自动回复配置更新请求。"""

    enabled: Optional[bool] = None
    dry_run_enabled: Optional[bool] = None
    send_enabled: Optional[bool] = None
    min_confidence: Optional[float] = Field(None, ge=0, le=1)
    require_rag: Optional[bool] = None
    require_rag_sources: Optional[bool] = None
    allowed_intents: Optional[list[str]] = None
    blocked_risk_flags: Optional[list[str]] = None
    customer_whitelist_open_ids: Optional[list[str]] = None
    conversation_whitelist_ids: Optional[list[str]] = None
    min_interval_seconds: Optional[int] = Field(None, ge=0, le=86400)
    max_auto_replies_per_conversation_per_day: Optional[int] = Field(None, ge=0, le=1000)
    max_replies_per_conversation_per_hour: Optional[int] = Field(None, ge=0, le=1000)
    max_replies_per_account_per_hour: Optional[int] = Field(None, ge=0, le=1000)
    direct_llm_policy: Optional[DirectLlmPolicyConfig] = None

    model_config = {"extra": "forbid"}


class DouyinAutoreplyModeUpdate(BaseModel):
    """抖音企业号托管模式更新请求。"""

    mode: Literal["ai_auto", "manual_takeover"]

    model_config = {"extra": "forbid"}


class DouyinAutoreplySettingsItem(BaseModel):
    """抖音企业号自动回复配置视图。"""

    account_open_id: str
    mode: Literal["ai_auto", "manual_takeover"] = "manual_takeover"
    account_name: Optional[str] = None
    bind_status: Optional[int] = None
    bound_agent_id: Optional[str] = None
    bound_agent_name: Optional[str] = None
    enabled: bool = False
    dry_run_enabled: bool = False
    send_enabled: bool = False
    min_confidence: float = 0.85
    require_rag: bool = True
    require_rag_sources: bool = True
    allowed_intents: list[str] = Field(default_factory=list)
    blocked_risk_flags: list[str] = Field(default_factory=list)
    customer_whitelist_open_ids: list[str] = Field(default_factory=list)
    conversation_whitelist_ids: list[str] = Field(default_factory=list)
    min_interval_seconds: int = 10
    max_auto_replies_per_conversation_per_day: int = 80
    max_replies_per_conversation_per_hour: int = 20
    max_replies_per_account_per_hour: int = 300
    direct_llm_policy: DirectLlmPolicyConfig = Field(default_factory=DirectLlmPolicyConfig)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DouyinAutoreplySettingsListData(BaseModel):
    """抖音企业号自动回复配置列表数据。"""

    total: int
    items: list[DouyinAutoreplySettingsItem]


class DouyinAutoreplySettingsListResponse(BaseModel):
    """抖音企业号自动回复配置列表响应。"""

    success: bool = True
    data: DouyinAutoreplySettingsListData
    message: str = "success"


class DouyinAutoreplySettingsResponse(BaseModel):
    """抖音企业号自动回复配置详情响应。"""

    success: bool = True
    data: DouyinAutoreplySettingsItem
    message: str = "success"


# ========== 抖音自动回复运行记录 ==========


class DouyinConversationAutopilotResumeRequest(BaseModel):
    """当前会话恢复 AI 托管请求。"""

    customer_open_id: Optional[str] = None

    model_config = {"extra": "forbid"}


class DouyinConversationAutopilotStateItem(BaseModel):
    """当前会话托管状态。"""

    mode: str
    manual_takeover_until: Optional[datetime] = None
    last_human_message_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DouyinConversationAutopilotStateResponse(BaseModel):
    """当前会话托管状态响应。"""

    success: bool = True
    data: DouyinConversationAutopilotStateItem
    message: str = "success"


class AiAutoReplyRunListItem(BaseModel):
    """自动回复运行记录列表项。"""

    id: int
    merchant_id: str
    account_open_id: str
    conversation_short_id: Optional[str] = None
    customer_open_id: Optional[str] = None
    trigger_event_id: int
    trigger_event_key: str
    trigger_server_message_id: Optional[str] = None
    latest_message_summary: Optional[str] = None
    agent_id: Optional[str] = None
    mode: str
    status: str
    skip_reason: Optional[str] = None
    block_reason: Optional[str] = None
    decision_log_id: Optional[int] = None
    would_send_content_summary: Optional[str] = None
    error_message: Optional[str] = None
    reply_text: Optional[str] = None
    manual_required: Optional[bool] = None
    manual_required_reason: Optional[str] = None
    risk_flags: list = Field(default_factory=list)
    llm_used: Optional[bool] = None
    rag_used: Optional[bool] = None
    upstream_auto_send: Optional[bool] = None
    final_auto_send: Optional[bool] = None
    decision_version: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AiAutoReplyRunListData(BaseModel):
    """自动回复运行记录分页数据。"""

    page: int
    page_size: int
    total: int
    items: list[AiAutoReplyRunListItem]


class AiAutoReplyRunListResponse(BaseModel):
    """自动回复运行记录列表响应。"""

    success: bool = True
    data: AiAutoReplyRunListData
    message: str = "success"


class AiAutoReplySendRecord(BaseModel):
    """自动回复关联发送流水摘要。"""

    id: int
    send_status: str
    send_source: str
    auto_send: bool
    manual_confirmed: bool
    upstream_msg_id: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None


class AiAutoReplyRunDetail(AiAutoReplyRunListItem):
    """自动回复运行记录详情。"""

    latest_message: Optional[str] = None
    would_send_content: Optional[str] = None
    gate_results: dict = Field(default_factory=dict)
    send_record: Optional[AiAutoReplySendRecord] = None


class AiAutoReplyRunDetailResponse(BaseModel):
    """自动回复运行记录详情响应。"""

    success: bool = True
    data: AiAutoReplyRunDetail
    message: str = "success"


# ---------------------------------------------------------------------------
# 小高 AI 一期 Phase 1 数据迁移骨架 Pydantic 结构
# 只定义结构，不接 router；使用项目现有 Pydantic 版本兼容写法。
# ---------------------------------------------------------------------------


class ForbiddenWordLibraryOut(BaseModel):
    """违禁词库输出结构。"""

    id: int
    library_key: str
    name: str
    description: Optional[str] = None
    scope: str = "global"
    enabled: bool = True
    sort_order: int = 0


class ForbiddenWordOut(BaseModel):
    """违禁词条目输出结构。"""

    id: int
    library_id: int
    word: str
    safe_word: Optional[str] = None
    severity: Optional[str] = None
    enabled: bool = True
    hit_count: int = 0


class ForbiddenWordHitLogOut(BaseModel):
    """违禁词命中日志输出结构（只暴露摘要）。"""

    id: int
    merchant_id: str
    library_key: Optional[str] = None
    word: Optional[str] = None
    safe_word: Optional[str] = None
    source: Optional[str] = None
    context_type: Optional[str] = None
    context_id: Optional[str] = None
    before_text_summary: Optional[str] = None
    after_text_summary: Optional[str] = None


class ReturnVisitPromptOut(BaseModel):
    """回访提示词输出结构。"""

    id: int
    prompt_key: str
    name: str
    scene_type: Optional[str] = None
    template_text: Optional[str] = None
    scope: str = "global"
    enabled: bool = True
    sort_order: int = 0


class ReturnVisitRunOut(BaseModel):
    """回访运行记录输出结构。"""

    id: int
    merchant_id: str
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    reply_check_id: Optional[int] = None
    prompt_key: Optional[str] = None
    trigger_source: Optional[str] = None
    judgement_source: Optional[str] = None
    judgement_result: Optional[str] = None
    generated_content: Optional[str] = None
    final_content: Optional[str] = None
    send_status: Optional[str] = None
    send_id: Optional[str] = None
    error_message: Optional[str] = None


class SalesLeadFeedbackOut(BaseModel):
    """【线索反馈】输出结构。"""

    id: int
    merchant_id: str
    feedback_no: str
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    wechat_status: Optional[str] = None
    opening_status: Optional[str] = None
    payment_method: Optional[str] = None
    car_model: Optional[str] = None
    match_status: Optional[str] = None
    budget_text: Optional[str] = None
    precision_status: Optional[str] = None
    intention_level: Optional[str] = None
    region_text: Optional[str] = None
    parse_status: Optional[str] = None
    feedback_date: Optional[datetime] = None


class SalesLeadUpdateOut(BaseModel):
    """【线索更新】输出结构。"""

    id: int
    merchant_id: str
    feedback_no: Optional[str] = None
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None
    visit_status: Optional[str] = None
    visit_time_text: Optional[str] = None
    deal_status: Optional[str] = None
    deal_time_text: Optional[str] = None
    parse_status: Optional[str] = None


class SalesDailySummaryOut(BaseModel):
    """【每日线索总结】输出结构。"""

    id: int
    merchant_id: str
    staff_id: int
    summary_date: date
    sales_name: Optional[str] = None
    overall_quality: Optional[str] = None
    main_problem: Optional[str] = None
    car_model_summary: Optional[str] = None
    budget_summary: Optional[str] = None
    cooperation_level: Optional[str] = None
    today_suggestion: Optional[str] = None
    extra_feedback: Optional[str] = None
    parse_status: Optional[str] = None


class DailyReportJobOut(BaseModel):
    """日报任务输出结构（不返回绝对路径，只返回内部存储键与文件名）。"""

    id: int
    merchant_id: str
    report_date: Optional[datetime] = None
    report_type: Optional[str] = None
    receiver_staff_id: Optional[int] = None
    status: Optional[str] = None
    file_storage_key: Optional[str] = None
    file_name: Optional[str] = None
    error_message: Optional[str] = None
    generated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


class DailyReportDiagnostic(BaseModel):
    """日报稳定诊断码：只写计数、稳定码和异常类型名，不写正文/路径/密钥。"""

    code: str
    count: int = Field(default=1, ge=1)
    exception_type: Optional[str] = None


class DailyReportJobItem(BaseModel):
    """Phase 8 日报任务 API 响应项。

    不含 file_storage_key / merchant_id / 绝对路径 / 底层异常正文。
    """

    id: int
    report_day: date
    report_type: str
    report_variant: str
    status: str
    artifact_status: str
    file_name: Optional[str] = None
    download_available: bool = False
    is_previous_artifact: bool = False
    diagnostics: list[DailyReportDiagnostic] = Field(default_factory=list)
    generated_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ========== Phase 8 Task 3：日报权威数据补录 ==========


class LeadReportAttributionUpsert(BaseModel):
    """线索归因补录项。

    不含 merchant_id（商户来自可信 RequestContext）；不含 source_system（服务固定 manual）。
    extra=forbid 拒绝伪造 merchant_id / source_system 等字段。
    """

    model_config = {"extra": "forbid"}
    lead_id: int
    traffic_type: Literal["paid", "organic", "unknown"]
    content_type: Literal["short_video", "live", "other", "unknown"]
    ad_id: Optional[str] = Field(None, max_length=128)
    material_id: Optional[str] = Field(None, max_length=128)
    trace_url: Optional[str] = Field(None, max_length=1000)

    @field_validator("trace_url")
    @classmethod
    def _validate_trace_url(cls, v: str | None) -> str | None:
        """trace_url 仅做格式校验：http/https、无 userinfo、无控制字符；不做 DNS/网络请求。"""
        if not v:
            return None
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError("trace_url 含控制字符")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("trace_url 仅允许 http/https")
        if not parsed.hostname:
            raise ValueError("trace_url 缺少 host")
        if parsed.username or parsed.password:
            raise ValueError("trace_url 不允许 userinfo")
        return v


class LeadAttributionUpsertRequest(BaseModel):
    """归因批量补录请求体（min_length=1 拒绝空数组，max_length=500 拒绝超限）。"""

    model_config = {"extra": "forbid"}
    items: list[LeadReportAttributionUpsert] = Field(..., min_length=1, max_length=500)


class LeadReportAttributionOut(BaseModel):
    """归因响应项（响应可返回完整 trace_url，因为商户有权查看自有数据；审计才脱敏）。"""

    model_config = {"from_attributes": True}
    id: int
    lead_id: int
    traffic_type: str
    content_type: str
    ad_id: Optional[str] = None
    material_id: Optional[str] = None
    trace_url: Optional[str] = None
    source_system: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LeadAttributionUpsertResponse(BaseModel):
    success: bool = True
    count: int
    records: list[LeadReportAttributionOut]


class LeadAttributionItem(BaseModel):
    """GET 归因列表项：线索基本信息 + 当前归因（无归因时 None）；不含 raw_data。"""

    lead_id: int
    customer_name: Optional[str] = None
    lead_type: Optional[str] = None
    created_at: Optional[datetime] = None
    attribution: Optional[LeadReportAttributionOut] = None


class LeadAttributionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    records: list[LeadAttributionItem]


class LeadReportAttributionQuery(BaseModel):
    """归因列表查询参数（service 入参容器）。"""

    report_day: date
    content_type: Optional[Literal["short_video", "live", "other", "unknown"]] = None
    traffic_type: Optional[Literal["paid", "organic", "unknown"]] = None
    missing_only: bool = False
    page: int = 1
    page_size: int = 50


class DailyAdMetricUpsert(BaseModel):
    """广告日指标补录项。

    channel 固定 douyin（服务写入，客户端不传）；不接受广告明细字段
    （metric_key/ad_id/material_id），extra=forbid 拒绝。
    """

    model_config = {"extra": "forbid"}
    metric_day: date
    content_type: Literal["short_video", "live"]
    spend_amount: Decimal = Field(..., ge=0, max_digits=14, decimal_places=2)
    private_message_count: int = Field(..., ge=0)


class DailyAdMetricUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[DailyAdMetricUpsert] = Field(..., min_length=1, max_length=500)


class DailyAdMetricOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    metric_day: date
    channel: str
    content_type: str
    spend_amount: Decimal
    private_message_count: int
    source_system: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DailyAdMetricUpsertResponse(BaseModel):
    success: bool = True
    count: int
    records: list[DailyAdMetricOut]


class DailyAdMetricListResponse(BaseModel):
    metric_day: date
    records: list[DailyAdMetricOut]


class MerchantReportProfileUpsert(BaseModel):
    """展厅价位补录：两个价位必须同时为空或同时存在且 0 <= min <= max。"""

    model_config = {"extra": "forbid"}
    showroom_price_min_yuan: Optional[Decimal] = Field(None, ge=0, max_digits=14, decimal_places=2)
    showroom_price_max_yuan: Optional[Decimal] = Field(None, ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def _check_price_range(self) -> "MerchantReportProfileUpsert":
        mn = self.showroom_price_min_yuan
        mx = self.showroom_price_max_yuan
        if (mn is None) != (mx is None):
            raise ValueError("价位必须同时存在或同时为空")
        if mn is not None and mx is not None and mn > mx:
            raise ValueError("最低价不能大于最高价")
        return self


class MerchantReportProfileOut(BaseModel):
    model_config = {"from_attributes": True}
    showroom_price_min_yuan: Optional[Decimal] = None
    showroom_price_max_yuan: Optional[Decimal] = None
    updated_at: Optional[datetime] = None


class ReportDataCompletenessOut(BaseModel):
    """完整度诊断响应：只列 count>0 的稳定诊断码。"""

    report_day: date
    diagnostics: list[DailyReportDiagnostic]


# ========== Phase 8 Task 7：生成/列表/下载 ==========

DailyReportType = Literal[
    "short_video_live_lead", "daily_sales_feedback", "lead_trace", "sales_unit_cost"
]
DailyReportVariant = Literal["default", "created", "assigned"]


class GenerateDailyReportsRequest(BaseModel):
    """生成请求：report_day 必填；report_type 缺省生成默认集；不接受 merchant_id。"""

    model_config = {"extra": "forbid"}
    report_day: date
    report_type: Optional[DailyReportType] = None
    report_variant: Optional[DailyReportVariant] = None


class SkippedReport(BaseModel):
    report_type: str
    variant: Optional[str] = None
    reason: str


class GenerateDailyReportsResponse(BaseModel):
    success: bool = True
    jobs: list[DailyReportJobItem]
    skipped: list[SkippedReport] = Field(default_factory=list)


class RegenerateDailyReportResponse(BaseModel):
    success: bool = True
    job: DailyReportJobItem


class DailyReportJobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    records: list[DailyReportJobItem]


# ----- Phase 8-B Task 4：Local Agent 附件协议（不含 storage_key/token 原文/绝对路径）-----
class DeliveryAgentTaskItem(BaseModel):
    id: int
    task_type: str
    status: str
    staff_id: int | None = None
    target_nickname: str | None = None
    report_delivery_id: int
    delivery_attempt_no: int | None = None


class DeliveryTaskDetail(BaseModel):
    id: int
    status: str
    delivery_id: int
    attempt_no: int | None = None
    target_nickname: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    size: int | None = None


class DeliveryClaimResponse(BaseModel):
    """claim 响应：一次性返回明文 execution_token/download_ticket（DB 只存 SHA-256 hash）。"""
    task_id: int
    delivery_id: int
    attempt_no: int | None = None
    target_nickname: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    size: int | None = None
    execution_token: str
    download_ticket: str
    expires_at: datetime | None = None


class DeliverySendIntentRequest(BaseModel):
    execution_token: str


class DeliverySendIntentResponse(BaseModel):
    send_nonce: str
    expires_at: datetime | None = None


class DeliveryResultRequest(BaseModel):
    execution_token: str
    send_nonce: str | None = None
    success: bool
    contact_verified: bool = False
    partial_match: bool = False
    manual_review_required: bool = False
    pasted: bool = False
    sent: bool = False
    send_triggered: bool = False
    message_verified: bool = False
    failure_stage: str | None = None
    agent_identity: dict | None = None
    evidence: dict | None = None
    blocked: bool = False
    probe: bool = False


class DeliveryResultResponse(BaseModel):
    task_id: int
    status: str
    delivery_id: int
    delivery_status: str
    attempt_no: int | None = None


class ComputeMarkupRatioOut(BaseModel):
    """算力上浮比例输出结构（基点整数，不浮点）。"""

    id: int
    capability_key: Literal[
        "douyin-cs", "leads", "agents", "wechat-assistant", "compute", "knowledge"
    ]
    markup_basis_points: int
    enabled: bool = True

    model_config = {"from_attributes": True}


class ComputeMarkupRatioUpdate(BaseModel):
    """算力上浮比例更新请求（只允许改 markup/enabled，禁止改 capability_key）。"""

    model_config = {"extra": "forbid"}
    markup_basis_points: int = Field(
        ..., ge=0, le=2_147_483_647, description="上浮基点（非负，≤ PostgreSQL INTEGER 上界）"
    )
    enabled: bool = Field(..., description="是否启用该能力的上浮")


class ComputeMarkupRatioListResponse(BaseModel):
    """算力上浮比例列表响应。"""

    success: bool = True
    data: list[ComputeMarkupRatioOut]
    message: str = "success"


class ComputeMarkupRatioResponse(BaseModel):
    """算力上浮比例单项响应。"""

    success: bool = True
    data: ComputeMarkupRatioOut
    message: str = "success"


class AdReviewOAuthAccountOut(BaseModel):
    """一键过审授权账号输出结构（不暴露 token 密文）。"""

    id: int
    merchant_id: str
    advertiser_id: str
    account_name: Optional[str] = None
    auth_status: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class AdReviewSuggestionOut(BaseModel):
    """一键过审建议输出结构。"""

    id: int
    merchant_id: str
    oauth_account_id: Optional[int] = None
    suggestion_key: str
    advertiser_id: Optional[str] = None
    ad_id: Optional[str] = None
    material_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    suggestion_text: Optional[str] = None
    adopt_status: Optional[str] = None
    pulled_at: Optional[datetime] = None


class AdReviewAdoptTaskOut(BaseModel):
    """一键过审采纳任务输出结构。"""

    id: int
    merchant_id: str
    oauth_account_id: Optional[int] = None
    task_key: str
    status: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None


class AiEditJobOut(BaseModel):
    """AI 剪辑任务输出结构。"""

    id: int
    merchant_id: str
    job_id: str
    status: Optional[str] = None
    source_type: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None


class AiEditJobArtifactOut(BaseModel):
    """AI 剪辑产物输出结构（只返回内部 storage_key，不返回绝对路径）。"""

    id: int
    merchant_id: str
    job_id: str
    artifact_id: str
    artifact_type: Optional[str] = None
    storage_key: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None


class AiReplyDecisionEffectivenessPatch(BaseModel):
    """超管人工标记 AI 回复决策有效性补丁。"""

    is_effective: Optional[bool] = None
    effectiveness_reason: Optional[str] = None


class SalesFeedbackParseRequest(BaseModel):
    """销售反馈解析请求（Phase 7）。"""

    raw_text: str = Field(..., min_length=1, max_length=5000)
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None


class SalesFeedbackParseResponseData(BaseModel):
    """销售反馈解析结果数据。"""

    kind: str
    parse_status: str
    feedback_no: Optional[str] = None
    fields: dict[str, str] = Field(default_factory=dict)
    parse_error: Optional[str] = None


class SalesFeedbackParseResponse(BaseModel):
    """销售反馈解析响应。"""

    success: bool = True
    data: SalesFeedbackParseResponseData
    message: str = "success"
