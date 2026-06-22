"""AI小高线索能力服务 DTO。

本阶段保持与 9000 旧接口响应兼容，直接复用现有只读 DTO。
"""

from app.schemas import LeadListData, LeadListResponse, LeadOut, ReportSummary, StaffStatItem

__all__ = [
    "LeadListData",
    "LeadListResponse",
    "LeadOut",
    "ReportSummary",
    "StaffStatItem",
]
