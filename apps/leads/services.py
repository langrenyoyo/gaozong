"""AI小高线索能力服务只读业务逻辑。

本阶段复用 9000 既有只读 service，保持响应结构兼容；不迁移 webhook、同步、创建、分配或微信任务联动。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.schemas import LeadAssign, LeadCreate, LeadListResponse
from app.services import assign_service, lead_management_service, lead_service, report_service
from app.services.lead_management_service import LeadListQuery


def _merchant_scope(context: RequestContext) -> str | None:
    """返回只读查询使用的可信商户范围。"""
    return None if context.super_admin else context.merchant_id


def list_leads(
    db: Session,
    context: RequestContext,
    *,
    status: str | None = None,
    keyword: str | None = None,
    source: str | None = None,
    assigned_staff_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    response_format: str | None = None,
):
    """复用旧线索列表查询，保持分页与数组响应兼容。"""
    query = LeadListQuery(
        keyword=keyword,
        source=source,
        status=status,
        assigned_staff_id=int(assigned_staff_id) if assigned_staff_id else None,
        merchant_id=_merchant_scope(context),
        page=page,
        page_size=page_size,
    )
    leads = lead_management_service.list_leads(db, query)
    items = [lead_management_service.build_lead_payload(db, lead) for lead in leads]
    if response_format == "page":
        normalized_page = max(page, 1)
        normalized_page_size = min(max(page_size, 1), 200)
        return LeadListResponse(
            data={
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": lead_management_service.count_leads(db, query),
                "items": items,
            }
        )
    return items


def create_lead(db: Session, context: RequestContext, data: LeadCreate):
    """创建有效线索，商户归属只取可信 gateway 上下文。"""
    payload = data.model_dump()
    payload["merchant_id"] = context.merchant_id
    lead = lead_service.create_lead(db, **payload)
    return lead_management_service.build_lead_payload(db, lead)


def get_lead(db: Session, context: RequestContext, lead_id: int):
    """复用旧详情查询，并保持商户归属校验。"""
    lead = lead_service.get_lead(db, lead_id)
    lead_management_service.require_lead_ownership(lead, context)
    return lead_management_service.build_lead_payload(db, lead, include_detail=True)


def assign_lead(db: Session, context: RequestContext, lead_id: int, data: LeadAssign):
    """分配当前商户有效线索，保持旧服务的 ReplyCheck 与跟进记录行为。"""
    existing = lead_service.get_lead(db, lead_id)
    lead_management_service.require_lead_ownership(existing, context)
    lead = assign_service.assign_lead(
        db,
        lead_id,
        data.staff_id,
        remark=data.remark,
        operator_id=context.user_id,
    )
    return lead_management_service.build_lead_payload(db, lead, include_detail=True)


def get_summary(db: Session, context: RequestContext):
    """复用旧报表统计，按可信商户上下文过滤。"""
    return report_service.get_summary(db, merchant_id=_merchant_scope(context))
