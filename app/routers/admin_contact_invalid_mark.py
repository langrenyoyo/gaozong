"""管理员手动标记联系方式失效 API（任务 1.4）。

替代已删除的 Task2A，作为空号追问链路的触发源。
- POST /admin/contact-invalid/mark — 标记线索联系方式为空号/打不通/号码错误

安全限制：管理员权限（auto_wechat:admin:autoreply）+ lead_id 强锚定。
块3触发：mark_contact_invalid 状态迁移（new_version 非 None）时创建追问任务。
失败不阻断——标记/追问任务创建失败返回结构化错误但不崩。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import SessionLocal
from app.models import DouyinLead
from app.services.contact_invalid_followup_service import create_followup_task
from app.services.customer_profile_service import mark_contact_invalid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/contact-invalid", tags=["管理员-联系方式失效标记"])

# 允许的失效原因白名单
_ALLOWED_REASONS = {"空号", "打不通", "号码错误", "停机", "其他"}


class MarkInvalidRequest(BaseModel):
    """手动标记联系方式失效请求。lead_id 强锚定，不靠会话匹配猜客户。"""

    model_config = {"extra": "forbid"}

    lead_id: int = Field(..., description="线索 ID，强锚定")
    merchant_id: str = Field(..., min_length=1)
    account_open_id: str = Field(..., min_length=1)
    customer_open_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, description="失效原因：空号/打不通/号码错误/停机/其他")


@router.post("/mark")
def mark_contact_invalid_endpoint(
    body: MarkInvalidRequest,
    context: RequestContext = Depends(get_request_context_required),
):
    """标记线索联系方式失效 → 触发块3追问任务（状态迁移时）。

    流程：① 权限校验 ② lead_id 锚定校验（lead 存在 + merchant/account/customer 匹配）
    ③ mark_contact_invalid 状态迁移 ④ new_version 非 None 时创建 ContactInvalidFollowupTask
    """
    if not context.has_permission("auto_wechat:admin:autoreply"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:autoreply"},
        )
    if body.reason not in _ALLOWED_REASONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REASON",
                "message": f"reason 必须为 {sorted(_ALLOWED_REASONS)} 之一",
            },
        )

    db = SessionLocal()
    try:
        # lead_id 强锚定：校验 lead 存在且 merchant/account/customer 三字段匹配
        lead = db.get(DouyinLead, body.lead_id)
        if lead is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "LEAD_NOT_FOUND", "message": f"线索 {body.lead_id} 不存在"},
            )
        if str(lead.merchant_id or "") != str(body.merchant_id):
            raise HTTPException(
                status_code=403,
                detail={"code": "LEAD_MERCHANT_MISMATCH", "message": "线索不属于该商户"},
            )
        if str(lead.account_open_id or "") != str(body.account_open_id):
            raise HTTPException(
                status_code=403,
                detail={"code": "LEAD_ACCOUNT_MISMATCH", "message": "线索不属于该企业号"},
            )
        if str(lead.source_id or "") != str(body.customer_open_id):
            raise HTTPException(
                status_code=403,
                detail={"code": "LEAD_CUSTOMER_MISMATCH", "message": "线索客户标识不匹配"},
            )

        # 状态迁移 VALID→INVALID，返回 new_version（int）或 None（已失效或无档案）
        new_version = mark_contact_invalid(
            db,
            merchant_id=body.merchant_id,
            account_open_id=body.account_open_id,
            customer_open_id=body.customer_open_id,
            reason=body.reason,
            source="admin_manual_mark",
            source_message_id=None,
        )

        followup_task_id: int | None = None
        if new_version is not None and lead.conversation_short_id:
            # 块3触发：状态迁移时创建追问任务（幂等，唯一约束防重）
            task = create_followup_task(
                db,
                merchant_id=body.merchant_id,
                lead_id=body.lead_id,
                account_open_id=body.account_open_id,
                conversation_short_id=lead.conversation_short_id,
                customer_open_id=body.customer_open_id,
                invalid_version=new_version,
                trigger_source="admin_manual_mark",
                trigger_message_id=None,
                invalid_reason=body.reason,
            )
            followup_task_id = task.id if task else None
        db.commit()

        logger.info(
            "admin_mark_contact_invalid lead_id=%s merchant_id=%s version=%s reason=%s followup_task=%s",
            body.lead_id, body.merchant_id, new_version, body.reason, followup_task_id,
        )
        return {
            "success": True,
            "data": {
                "lead_id": body.lead_id,
                "invalid_version": new_version,
                "already_invalid": new_version is None,
                "followup_task_id": followup_task_id,
                "followup_triggered": followup_task_id is not None,
            },
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "admin_mark_contact_invalid_error lead_id=%s error=%s",
            body.lead_id, type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "MARK_INVALID_FAILED", "message": "标记失败，请稍后重试"},
        ) from exc
    finally:
        db.close()
