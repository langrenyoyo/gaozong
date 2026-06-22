"""AI小高线索能力服务 DTO。

本阶段保持与 9000 旧接口响应兼容，直接复用现有只读 DTO。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import LeadAssign, LeadCreate, LeadListData, LeadListResponse, LeadOut, ReportSummary, StaffStatItem


class InternalWebhookEventRequest(BaseModel):
    """9202 internal webhook-events 请求。"""

    source_path: str = Field(..., description="9000 已验签 webhook 来源路径")
    payload: dict[str, Any] = Field(default_factory=dict, description="已 JSON decode 的 webhook payload")
    received_at: datetime | None = Field(None, description="9000 接收时间")
    signature_verified: bool = Field(False, description="9000 是否已完成验签")
    gateway_request_id: str | None = Field(None, description="网关请求追踪 ID")
    gateway_app_env: str | None = Field(None, description="网关运行环境")


class InternalWebhookEventResponse(BaseModel):
    """兼容旧 WebhookResponse 关键字段的 internal 响应。"""

    code: int = 0
    msg: str = "success"
    event_id: int | None = None
    lead_id: int | None = None
    is_new_lead: bool = False
    is_duplicate: bool = False
    lead_action: str = "not_lead_event"

__all__ = [
    "LeadAssign",
    "LeadCreate",
    "InternalWebhookEventRequest",
    "InternalWebhookEventResponse",
    "LeadListData",
    "LeadListResponse",
    "LeadOut",
    "ReportSummary",
    "StaffStatItem",
]
