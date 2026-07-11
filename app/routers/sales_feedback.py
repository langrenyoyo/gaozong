"""销售反馈解析调试/人工补录接口（Phase 7）。

复用 sales_feedback_parser 的固定模板解析，不新增权限码，
沿用 auto_wechat:agent 权限，便于后台调试和人工补录。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import SalesFeedbackParseRequest, SalesFeedbackParseResponse
from app.services.sales_feedback_parser import parse_and_persist_sales_feedback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales-feedback", tags=["销售反馈"])


@router.post("/parse", response_model=SalesFeedbackParseResponse)
def parse_sales_feedback(
    payload: SalesFeedbackParseRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """解析并持久化销售反馈固定模板。"""
    require_permission("auto_wechat:agent")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id=context.merchant_id,
        raw_text=payload.raw_text,
        lead_id=payload.lead_id,
        staff_id=payload.staff_id,
    )
    # Phase 7-FIX1：failed 回滚并返回 400，不写库
    if result.parse_status == "failed":
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"code": "SALES_FEEDBACK_PARSE_FAILED", "message": "销售反馈格式或上下文无效"},
        )
    # Phase 7-FIX1 Task 5：success 由调用方统一 commit；持久化异常回滚并返回 500
    if result.parse_status == "success":
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            # Phase 7-FIX2：不记录异常正文，只记录异常类型名
            logger.error("sales_feedback_persist_error route=parse error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500,
                detail={"code": "SALES_FEEDBACK_PERSIST_FAILED", "message": "销售反馈持久化失败"},
            ) from exc
    return {
        "success": True,
        "data": {
            "kind": result.kind,
            "parse_status": result.parse_status,
            "feedback_no": result.feedback_no,
            "fields": result.fields,
            "parse_error": result.parse_error,
        },
        "message": "success",
    }
