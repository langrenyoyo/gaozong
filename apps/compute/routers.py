"""小高算力能力服务业务路由。"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import is_production_env
from app.database import get_db
from apps.compute.dependencies import (
    GatewayContext,
    get_gateway_context,
    require_compute_config_admin,
    require_merchant_context,
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

logger = logging.getLogger(__name__)


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def _safe_log_value(value: object) -> str:
    """日志安全值：折叠空白、限长，避免注入与超长目标摘要。"""
    return " ".join(str(value).split())[:128] or "-"


@contextmanager
def _admin_compute_action(
    context: GatewayContext,
    *,
    operation: str,
    target: str,
) -> Iterator[None]:
    """管理员算力写操作结构化日志：成功/失败双态，固定字段，不记录内部令牌或 remark 全文。

    ponytail: 独立服务自行实现，不与 9000 共抽模块；操作人取 gateway 注入的 user_id。
    """
    operator_id = _safe_log_value(context.get("user_id"))
    safe_target = _safe_log_value(target)
    try:
        yield
    except Exception as exc:
        logger.warning(
            "compute_admin_action operation=%s operator_id=%s target=%s "
            "status=failed failure_stage=%s error_type=%s",
            operation,
            operator_id,
            safe_target,
            operation,
            type(exc).__name__,
        )
        raise
    logger.info(
        "compute_admin_action operation=%s operator_id=%s target=%s "
        "status=success failure_stage=none error_type=none",
        operation,
        operator_id,
        safe_target,
    )


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
    """商户算力点数流水分页。"""
    merchant_id = require_merchant_context(context)
    data = compute_service.list_merchant_transactions(
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
    require_compute_config_admin(context)
    packages = compute_service.list_admin_packages(db)
    return {"success": True, "data": packages, "message": "success"}


@router.post("/admin/packages", response_model=ComputePackageResponse)
def admin_create_package(
    payload: ComputePackageCreate,
    db: Session = Depends(get_db),
    context: GatewayContext = Depends(get_gateway_context),
):
    """管理员创建套餐。"""
    with _admin_compute_action(
        context, operation="create_package", target=f"package_name={payload.name}"
    ):
        require_compute_config_admin(context)
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
    fields = ",".join(sorted(payload.model_dump(exclude_unset=True).keys())) or "-"
    with _admin_compute_action(
        context, operation="update_package", target=f"package_id={package_id},fields={fields}"
    ):
        require_compute_config_admin(context)
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
    with _admin_compute_action(
        context, operation="disable_package", target=f"package_id={package_id}"
    ):
        require_compute_config_admin(context)
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
    with _admin_compute_action(
        context,
        operation="recharge_merchant",
        target=f"merchant_id={merchant_id},points={payload.tokens}",
    ):
        require_compute_config_admin(context)
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
    with _admin_compute_action(
        context,
        operation="grant_package",
        target=f"merchant_id={merchant_id},package_id={payload.package_id}",
    ):
        require_compute_config_admin(context)
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
    with _admin_compute_action(
        context, operation="update_markup_ratio", target=f"capability={capability_key}"
    ):
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
    """读取内部调用令牌；为空表示未配置。"""
    return os.getenv("COMPUTE_INTERNAL_TOKEN", "").strip()


def _require_internal(request: Request) -> None:
    """内部接口保护：配置 COMPUTE_INTERNAL_TOKEN 时校验 X-Internal-Token。

    生产环境（APP_ENV=production）缺配置即拒绝（fail-closed）；开发环境未配置则放行。
    9205 默认仅本机/LAN 暴露，生产前仍必须由 gateway 或服务间鉴权收口。
    """
    expected = _get_internal_token()
    if not expected:
        if is_production_env():
            raise HTTPException(
                status_code=500,
                detail={"code": "INTERNAL_TOKEN_NOT_CONFIGURED", "message": "生产环境必须配置 COMPUTE_INTERNAL_TOKEN"},
            )
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
            usage_measurement_method=payload.usage_measurement_method,
            prompt_tokens=payload.prompt_tokens,
            completion_tokens=payload.completion_tokens,
            cached_tokens=payload.cached_tokens,
            llm_call_stage=payload.llm_call_stage,
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
            "USAGE_MEASUREMENT_METHOD_INVALID": "无效的用量计量方式",
            "TOKEN_DETAIL_OUT_OF_RANGE": "模型用量明细超出范围",
            "LLM_CALL_STAGE_INVALID": "无效的模型调用阶段",
        }
        raise _bad_request(code, message_map.get(code, code)) from exc
    summary = compute_service.get_summary(db, payload.merchant_id)
    return {"success": True, "data": summary, "message": "success"}
