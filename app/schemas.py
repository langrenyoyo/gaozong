"""Pydantic 请求/响应模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ========== 销售人员 ==========

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
    content: Optional[str] = None
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    assigned_staff_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    status: str
    raw_data: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
