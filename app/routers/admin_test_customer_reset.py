"""测试客户档案重置管理 API。

三级重置，严格限制为测试能力：
- POST /admin/test-customer-reset/session — 重置当前会话上下文
- POST /admin/test-customer-reset/requirements — 重置客户需求事实
- POST /admin/test-customer-reset/full — 完全重置测试客户

安全限制：TEST_CUSTOMER_RESET_ENABLED 开关 + 管理员权限 + 二次确认 + 审计日志。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import SessionLocal
from app.services.test_customer_reset_service import (
    is_reset_enabled,
    reset_test_customer,
)

router = APIRouter(prefix="/admin/test-customer-reset", tags=["管理员-测试客户重置"])


class ResetRequest(BaseModel):
    """测试客户重置请求。"""

    model_config = {"extra": "forbid"}

    merchant_id: str = Field(..., min_length=1)
    account_open_id: str = Field(..., min_length=1)
    customer_open_id: str = Field(..., min_length=1)
    conversation_short_id: str | None = None
    reason: str = Field(..., min_length=1)
    confirm: bool = Field(..., description="必须为 true，二次确认")


def _require_enabled_and_admin(context: RequestContext) -> RequestContext:
    """检查重置开关 + 管理员权限。"""
    if not is_reset_enabled():
        raise HTTPException(
            status_code=403,
            detail={"code": "TEST_CUSTOMER_RESET_DISABLED", "message": "测试客户重置未开启（TEST_CUSTOMER_RESET_ENABLED=false）"},
        )
    if not context.has_permission("auto_wechat:admin:autoreply"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:autoreply"},
        )
    return context


@router.post("/session")
def reset_session(
    body: ResetRequest,
    context: RequestContext = Depends(get_request_context_required),
):
    """A. 重置当前会话上下文：清除未完成的 run + 重置 autopilot 状态。保留客户档案+联系方式。"""
    context = _require_enabled_and_admin(context)
    if not body.confirm:
        raise HTTPException(status_code=400, detail={"code": "CONFIRM_REQUIRED", "message": "confirm 必须为 true"})

    db = SessionLocal()
    try:
        result = reset_test_customer(
            db,
            merchant_id=body.merchant_id,
            account_open_id=body.account_open_id,
            customer_open_id=body.customer_open_id,
            conversation_short_id=body.conversation_short_id,
            level="session",
            operator_id=context.user_id or "unknown",
            operator_name=context.user_name or "unknown",
            reason=body.reason,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    finally:
        db.close()


@router.post("/requirements")
def reset_requirements(
    body: ResetRequest,
    context: RequestContext = Depends(get_request_context_required),
):
    """B. 重置客户需求事实：清除 intent_car/budget/car_year/city。保留联系方式+称呼+性别。"""
    context = _require_enabled_and_admin(context)
    if not body.confirm:
        raise HTTPException(status_code=400, detail={"code": "CONFIRM_REQUIRED", "message": "confirm 必须为 true"})

    db = SessionLocal()
    try:
        result = reset_test_customer(
            db,
            merchant_id=body.merchant_id,
            account_open_id=body.account_open_id,
            customer_open_id=body.customer_open_id,
            conversation_short_id=body.conversation_short_id,
            level="requirements",
            operator_id=context.user_id or "unknown",
            operator_name=context.user_name or "unknown",
            reason=body.reason,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    finally:
        db.close()


@router.post("/full")
def reset_full(
    body: ResetRequest,
    context: RequestContext = Depends(get_request_context_required),
):
    """C. 完全重置测试客户：删除 customer_profiles + 重置 lead 联系方式字段。"""
    context = _require_enabled_and_admin(context)
    if not body.confirm:
        raise HTTPException(status_code=400, detail={"code": "CONFIRM_REQUIRED", "message": "confirm 必须为 true"})

    db = SessionLocal()
    try:
        result = reset_test_customer(
            db,
            merchant_id=body.merchant_id,
            account_open_id=body.account_open_id,
            customer_open_id=body.customer_open_id,
            conversation_short_id=body.conversation_short_id,
            level="full",
            operator_id=context.user_id or "unknown",
            operator_name=context.user_name or "unknown",
            reason=body.reason,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    finally:
        db.close()
