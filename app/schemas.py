"""Pydantic 请求/响应模型"""

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


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
    if not isinstance(all_contacts, list):
        return values
    for item in all_contacts:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    return values


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


class StaffUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    wechat_id: Optional[str] = None
    wechat_nickname: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")


class StaffOut(BaseModel):
    id: int
    name: str
    wechat_id: Optional[str] = None
    wechat_nickname: Optional[str] = None
    phone: Optional[str] = None
    status: str
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


class LeadOut(BaseModel):
    id: int
    source: str
    lead_type: Optional[str] = None
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    all_extracted_contacts: list[str] = Field(default_factory=list)
    contact_extract_status: Optional[str] = None
    original_message_text: Optional[str] = None
    content: Optional[str] = None
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    assigned_staff_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    status: str
    raw_data: Optional[str] = None
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
                "content": getattr(value, "content", None),
                "source_url": getattr(value, "source_url", None),
                "source_id": getattr(value, "source_id", None),
                "assigned_staff_id": getattr(value, "assigned_staff_id", None),
                "assigned_at": getattr(value, "assigned_at", None),
                "status": getattr(value, "status", None),
                "raw_data": getattr(value, "raw_data", None),
                "created_at": getattr(value, "created_at", None),
                "updated_at": getattr(value, "updated_at", None),
            }

        raw_data = _safe_load_json_object(data.get("raw_data"))
        contact_extract = raw_data.get("contact_extract")
        if not isinstance(contact_extract, dict):
            contact_extract = {}

        data.setdefault("phone", contact_extract.get("phone"))
        data.setdefault("wechat", contact_extract.get("wechat"))
        data.setdefault("contact_extract_status", contact_extract.get("status"))
        data.setdefault(
            "original_message_text",
            raw_data.get("raw_message_text") or data.get("content"),
        )

        contact_values = _extract_contact_values(contact_extract.get("all_contacts"))
        if not contact_values and data.get("customer_contact"):
            contact_values = [data["customer_contact"]]
        data.setdefault("all_extracted_contacts", contact_values)
        return data

    model_config = {"from_attributes": True}


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
    auto_send: bool = Field(True, description="是否自动发送（Demo 默认 True）")


class SendToStaffResponse(BaseModel):
    """发送线索给销售响应"""
    success: bool = True
    message: str = ""
    notification_id: Optional[int] = Field(None, description="通知记录 ID")
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
    mode: str = Field("paste_only", description="执行模式: paste_only")


class WechatTaskResultRequest(BaseModel):
    """回写微信任务结果请求"""
    success: bool = Field(..., description="Agent 执行是否成功")
    verified: bool = Field(False, description="OCR 是否验证通过")
    partial_match: bool = Field(False, description="是否部分匹配")
    manual_review_required: bool = Field(False, description="是否需要人工复核")
    pasted: bool = Field(False, description="是否已粘贴到输入框")
    sent: bool = Field(False, description="是否已发送（P0-5A 期间必须为 false）")
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
