"""小高算力一期接口（P1-COMPUTE-BE-1）。

三类端点：
- 商户侧 /compute/*：余额、今日/昨日/累计消耗、Token 明细、套餐、充值订单（mock）。
- 管理员侧 /admin/compute/* + /admin/merchants/{id}/compute/*：套餐 CRUD、给商户充值、发放套餐。
- 内部 /internal/compute/usage：AI 消耗上报（供 9100/19000 埋点预留，一期不拦截余额）。

一期不做：真实支付、支付回调、余额不足拦截、退款、复杂 billing。
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_any_permission
from app.database import get_db
from app.schemas import (
    ComputeAdminRechargeRequest,
    ComputeGrantPackageRequest,
    ComputePackageCreate,
    ComputePackageListResponse,
    ComputePackageResponse,
    ComputePackageUpdate,
    ComputeRechargeOrderRequest,
    ComputeRechargeOrderResponse,
    ComputeSummaryResponse,
    ComputeTransactionListResponse,
    ComputeUsageRequest,
)
from app.services import compute_service


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


# ============ 商户侧 /compute ============

router = APIRouter(prefix="/compute", tags=["小高算力"])


def _merchant_auth(context: RequestContext) -> RequestContext:
    """校验小高算力查看权限。auto_wechat:agent 为过渡兼容，正式权限码为 auto_wechat:compute。"""
    return require_any_permission(["auto_wechat:compute", "auto_wechat:agent"])(context)


def _require_merchant(context: RequestContext) -> str:
    """商户侧统一取可信 merchant_id，缺失则 400。"""
    context = _merchant_auth(context)
    if not context.merchant_id:
        raise _bad_request("MERCHANT_ID_REQUIRED", "缺少可信商户上下文")
    return context.merchant_id


@router.get("/summary", response_model=ComputeSummaryResponse)
def get_summary(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """算力余额 + 今日/昨日/累计消耗（对齐 PRD 2.7.1 / 2.7.2）。"""
    merchant_id = _require_merchant(context)
    summary = compute_service.get_summary(db, merchant_id)
    return {"success": True, "data": summary, "message": "success"}


@router.get("/transactions", response_model=ComputeTransactionListResponse)
def list_transactions(
    transaction_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """Token 明细分页（对齐 PRD 2.7.3）。"""
    merchant_id = _require_merchant(context)
    data = compute_service.list_transactions(
        db,
        merchant_id,
        transaction_type=transaction_type,
        page=page,
        page_size=page_size,
    )
    return {"success": True, "data": data, "message": "success"}


@router.get("/packages", response_model=ComputePackageListResponse)
def list_packages(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """商户充值弹窗套餐列表（仅启用，对齐 PRD 2.7.4）。"""
    _require_merchant(context)
    packages = compute_service.list_enabled_packages(db)
    return {"success": True, "data": packages, "message": "success"}


@router.post("/recharge-orders", response_model=ComputeRechargeOrderResponse)
def create_recharge_order(
    payload: ComputeRechargeOrderRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """商户发起充值订单（一期 mock，不接真实支付，对齐 PRD 2.7.4）。"""
    merchant_id = _require_merchant(context)
    try:
        order = compute_service.create_mock_recharge_order(db, merchant_id, payload)
    except ValueError as exc:
        code = str(exc)
        message_map = {
            "PACKAGE_NOT_FOUND": "套餐不存在",
            "RECHARGE_TARGET_REQUIRED": "必须选择套餐或输入自定义金额",
        }
        raise _bad_request(code, message_map.get(code, code)) from exc
    return {"success": True, "data": order, "message": "success"}


# ============ 管理员侧 /admin ============

admin_router = APIRouter(prefix="/admin", tags=["超管-算力配置"])


def _require_admin(context: RequestContext) -> RequestContext:
    """管理员接口仅允许 super_admin（PRD 第三章为超级管理员专属功能）。"""
    if not (context.is_mock_auth() or context.super_admin):
        raise HTTPException(
            status_code=403,
            detail={"code": "SUPER_ADMIN_REQUIRED", "message": "仅超级管理员可操作"},
        )
    return context


@admin_router.get("/compute/packages", response_model=ComputePackageListResponse)
def admin_list_packages(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员查看全部套餐（含禁用，对齐 PRD 3.5）。"""
    _require_admin(context)
    packages = compute_service.list_admin_packages(db)
    return {"success": True, "data": packages, "message": "success"}


@admin_router.post("/compute/packages", response_model=ComputePackageResponse)
def admin_create_package(
    payload: ComputePackageCreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员创建套餐（对齐 PRD 3.5）。"""
    _require_admin(context)
    pkg = compute_service.create_package(db, payload)
    return {"success": True, "data": pkg, "message": "success"}


@admin_router.put("/compute/packages/{package_id}", response_model=ComputePackageResponse)
def admin_update_package(
    package_id: int,
    payload: ComputePackageUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员更新套餐（对齐 PRD 3.5）。"""
    _require_admin(context)
    pkg = compute_service.get_package(db, package_id)
    if pkg is None:
        raise _not_found("PACKAGE_NOT_FOUND", "套餐不存在")
    pkg = compute_service.update_package(db, pkg, payload)
    return {"success": True, "data": pkg, "message": "success"}


@admin_router.post(
    "/merchants/{merchant_id}/compute/recharge", response_model=ComputeSummaryResponse
)
@admin_router.post(
    "/compute/accounts/{merchant_id}/recharge", response_model=ComputeSummaryResponse
)
def admin_recharge_merchant(
    merchant_id: str,
    payload: ComputeAdminRechargeRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员给商户充值 Token（对齐 PRD 3.1.4 充值）。"""
    _require_admin(context)
    try:
        compute_service.recharge_merchant(
            db,
            merchant_id,
            payload.tokens,
            remark=payload.remark,
            operator_id=context.user_id,
        )
    except ValueError as exc:
        raise _bad_request(str(exc), "充值 Token 数量必须大于 0") from exc
    summary = compute_service.get_summary(db, merchant_id)
    return {"success": True, "data": summary, "message": "success"}


@admin_router.post(
    "/merchants/{merchant_id}/compute/grant-package", response_model=ComputeSummaryResponse
)
@admin_router.post(
    "/compute/accounts/{merchant_id}/grant-package", response_model=ComputeSummaryResponse
)
def admin_grant_package(
    merchant_id: str,
    payload: ComputeGrantPackageRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员给商户发放套餐（对齐 PRD 3.1.4 发放套餐）。"""
    _require_admin(context)
    try:
        compute_service.grant_package_to_merchant(
            db, merchant_id, payload.package_id, operator_id=context.user_id
        )
    except ValueError as exc:
        code = str(exc)
        message_map = {
            "PACKAGE_NOT_FOUND": "套餐不存在",
            "PACKAGE_DISABLED": "套餐已禁用，无法发放",
        }
        raise _bad_request(code, message_map.get(code, code)) from exc
    summary = compute_service.get_summary(db, merchant_id)
    return {"success": True, "data": summary, "message": "success"}


# ============ 内部 AI 消耗 /internal ============

internal_router = APIRouter(prefix="/internal", tags=["内部-算力消耗"])


def _get_internal_token() -> str:
    """读取内部调用令牌；为空表示开发环境未配置（放行）。"""
    return os.getenv("COMPUTE_INTERNAL_TOKEN", "").strip()


def _require_internal(request: Request) -> None:
    """内部接口保护：配置 COMPUTE_INTERNAL_TOKEN 时校验 X-Internal-Token，未配置则开发放行。

    生产环境必须配置 COMPUTE_INTERNAL_TOKEN，避免 usage 端点被外部滥用。
    """
    expected = _get_internal_token()
    if not expected:
        # 开发环境未配置令牌，放行（生产必须配置）
        return
    provided = request.headers.get("X-Internal-Token", "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=401,
            detail={"code": "INTERNAL_TOKEN_INVALID", "message": "内部调用令牌无效"},
        )


@internal_router.post("/compute/usage", response_model=ComputeSummaryResponse)
def report_usage(
    payload: ComputeUsageRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_internal),
):
    """内部 AI 消耗上报（供 9100/19000 埋点，一期不拦截余额）。"""
    try:
        compute_service.record_usage(
            db,
            payload.merchant_id,
            payload.tokens,
            capability_key=payload.capability_key,
            source=payload.source,
            model=payload.model,
            agent_id=payload.agent_id,
            conversation_id=payload.conversation_id,
            remark=payload.remark,
        )
    except ValueError as exc:
        code = str(exc)
        message_map = {
            "TOKENS_MUST_BE_POSITIVE": "消耗字符量必须大于 0",
            "INVALID_SOURCE": "无效的消耗来源",
            "INVALID_CAPABILITY": "无效的算力能力",
            "MODEL_INVALID": "模型标识无效",
            "MARKUP_RATIO_NOT_FOUND": "算力上浮比例未配置",
            "COMPUTE_VALUE_OUT_OF_RANGE": "计费值超出范围",
            "COMPUTE_BALANCE_OUT_OF_RANGE": "账户余额变动超出范围",
            "COMPUTE_ACCOUNT_MISSING": "商户算力账户不存在",
        }
        raise _bad_request(code, message_map.get(code, code)) from exc
    summary = compute_service.get_summary(db, payload.merchant_id)
    return {"success": True, "data": summary, "message": "success"}
