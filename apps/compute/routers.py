"""小高算力能力服务业务路由。"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from apps.compute.dependencies import (
    GatewayContext,
    get_gateway_context,
    require_compute_config_admin,
    require_merchant_context,
    require_super_admin,
)
from apps.compute.schemas import (
    ComputeAdminRechargeRequest,
    ComputeGrantPackageRequest,
    ComputeMarkupRatioListResponse,
    ComputeMarkupRatioResponse,
    ComputeMarkupRatioUpdate,
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
from apps.compute import services as compute_service


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


router = APIRouter(prefix="/api/compute", tags=["小高算力"])


@router.get("/summary", response_model=ComputeSummaryResponse)
def get_summary(
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """算力余额 + 今日/昨日/累计消耗。"""
    merchant_id = require_merchant_context(context)
    summary = compute_service.get_summary(db, merchant_id)
    return {"success": True, "data": summary, "message": "success"}


@router.get("/transactions", response_model=ComputeTransactionListResponse)
def list_transactions(
    transaction_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """Token 明细分页。"""
    merchant_id = require_merchant_context(context)
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
    context: GatewayContext = Depends(get_gateway_context),
):
    """商户充值弹窗套餐列表。"""
    require_merchant_context(context)
    packages = compute_service.list_enabled_packages(db)
    return {"success": True, "data": packages, "message": "success"}


@router.post("/recharge-orders", response_model=ComputeRechargeOrderResponse)
def create_recharge_order(
    payload: ComputeRechargeOrderRequest,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """商户发起充值订单。当前仍是 mock，不接真实支付。"""
    merchant_id = require_merchant_context(context)
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


@router.get("/admin/packages", response_model=ComputePackageListResponse)
def admin_list_packages(
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员查看全部套餐。"""
    require_super_admin(context)
    packages = compute_service.list_admin_packages(db)
    return {"success": True, "data": packages, "message": "success"}


@router.post("/admin/packages", response_model=ComputePackageResponse)
def admin_create_package(
    payload: ComputePackageCreate,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员创建套餐。"""
    require_super_admin(context)
    pkg = compute_service.create_package(db, payload)
    return {"success": True, "data": pkg, "message": "success"}


@router.put("/admin/packages/{package_id}", response_model=ComputePackageResponse)
def admin_update_package(
    package_id: int,
    payload: ComputePackageUpdate,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员更新套餐。"""
    require_super_admin(context)
    pkg = compute_service.get_package(db, package_id)
    if pkg is None:
        raise _not_found("PACKAGE_NOT_FOUND", "套餐不存在")
    pkg = compute_service.update_package(db, pkg, payload)
    return {"success": True, "data": pkg, "message": "success"}


@router.delete("/admin/packages/{package_id}", response_model=ComputePackageResponse)
def admin_disable_package(
    package_id: int,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员禁用套餐；不删除历史数据。"""
    require_super_admin(context)
    pkg = compute_service.get_package(db, package_id)
    if pkg is None:
        raise _not_found("PACKAGE_NOT_FOUND", "套餐不存在")
    payload = ComputePackageUpdate(enabled=False)
    pkg = compute_service.update_package(db, pkg, payload)
    return {"success": True, "data": pkg, "message": "success"}


@router.post("/admin/accounts/{merchant_id}/recharge", response_model=ComputeSummaryResponse)
def admin_recharge_merchant(
    merchant_id: str,
    payload: ComputeAdminRechargeRequest,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员给商户充值 Token。"""
    require_super_admin(context)
    try:
        compute_service.recharge_merchant(
            db,
            merchant_id,
            payload.tokens,
            remark=payload.remark,
            operator_id=context.get("user_id"),
        )
    except ValueError as exc:
        raise _bad_request(str(exc), "充值 Token 数量必须大于 0") from exc
    summary = compute_service.get_summary(db, merchant_id)
    return {"success": True, "data": summary, "message": "success"}


@router.post("/admin/accounts/{merchant_id}/grant-package", response_model=ComputeSummaryResponse)
def admin_grant_package(
    merchant_id: str,
    payload: ComputeGrantPackageRequest,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员给商户发放套餐。"""
    require_super_admin(context)
    try:
        compute_service.grant_package_to_merchant(
            db, merchant_id, payload.package_id, operator_id=context.get("user_id")
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


@router.get("/admin/markup-ratios", response_model=ComputeMarkupRatioListResponse)
def admin_list_markup_ratios(
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """查看六能力上浮比例（按冻结顺序，缺行视为漂移）。"""
    require_compute_config_admin(context)
    try:
        ratios = compute_service.list_markup_ratios(db)
    except ValueError as exc:
        code = str(exc)
        if code == "MARKUP_RATIO_DRIFT":
            raise HTTPException(
                status_code=500,
                detail={"code": code, "message": "算力上浮比例配置漂移，请联系管理员"},
            ) from exc
        raise _bad_request(code, code) from exc
    return {"success": True, "data": ratios, "message": "success"}


@router.put(
    "/admin/markup-ratios/{capability_key}",
    response_model=ComputeMarkupRatioResponse,
)
def admin_update_markup_ratio(
    capability_key: str,
    payload: ComputeMarkupRatioUpdate,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """更新指定能力的上浮比例与启用位（不允许改 capability_key）。"""
    require_compute_config_admin(context)
    try:
        ratio = compute_service.update_markup_ratio(
            db, capability_key, payload.markup_basis_points, payload.enabled
        )
    except ValueError as exc:
        code = str(exc)
        if code == "MARKUP_RATIO_DRIFT":
            raise HTTPException(
                status_code=500,
                detail={"code": code, "message": "算力上浮比例配置漂移，请联系管理员"},
            ) from exc
        message_map = {"INVALID_CAPABILITY": "无效的算力能力"}
        raise _bad_request(code, message_map.get(code, code)) from exc
    return {"success": True, "data": ratio, "message": "success"}


def _get_internal_token() -> str:
    """读取内部调用令牌；为空表示开发环境未配置。"""
    return os.getenv("COMPUTE_INTERNAL_TOKEN", "").strip()


def _require_internal(request: Request) -> None:
    """内部接口保护。生产前必须由 gateway 或服务间鉴权收口。"""
    expected = _get_internal_token()
    if not expected:
        return
    provided = request.headers.get("X-Internal-Token", "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=401,
            detail={"code": "INTERNAL_TOKEN_INVALID", "message": "内部调用令牌无效"},
        )


@router.post("/internal/usage", response_model=ComputeSummaryResponse)
def report_usage(
    payload: ComputeUsageRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_internal),
):
    """内部 AI 消耗上报。保持一期扣费语义，不做余额拦截。"""
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
