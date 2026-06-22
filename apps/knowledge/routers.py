"""统一知识库训练能力服务业务路由。"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)
from apps.knowledge import services as knowledge_service
from apps.knowledge.dependencies import (
    GatewayContext,
    build_request_context,
    get_gateway_context,
    require_knowledge_context,
    require_rag_context,
)
from apps.knowledge.schemas import (
    KnowledgeCategoryCreate,
    KnowledgeCategoryListResponse,
    RagDocumentProxyRequest,
    RagTrainProxyRequest,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["统一知识库训练"])


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _trusted_tenant_id(context) -> str:
    return context.source_system or "new_car_project"


def _normalize_and_validate_category_key(
    *,
    db: Session,
    context,
    category_key: str | None,
) -> str:
    try:
        return knowledge_service.ensure_category_usable_for_merchant(
            db,
            context=context,
            category_key=category_key,
            default_base=True,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "CATEGORY_KEY_REQUIRED":
            raise _bad_request("CATEGORY_KEY_REQUIRED", "知识分类不能为空") from exc
        raise _bad_request("CATEGORY_KEY_NOT_VISIBLE", "知识分类不存在或不可用") from exc


@router.get("/categories", response_model=KnowledgeCategoryListResponse)
def list_knowledge_categories(
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """列出当前商户可见知识分类。"""
    require_knowledge_context(gateway_context)
    context = build_request_context(gateway_context)
    try:
        categories = knowledge_service.list_visible_knowledge_categories(db, context=context)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": categories, "message": "success"}


@router.post("/categories")
def create_knowledge_category(
    payload: KnowledgeCategoryCreate,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """创建当前商户 merchant 知识分类。"""
    require_knowledge_context(gateway_context)
    context = build_request_context(gateway_context)
    try:
        row = knowledge_service.create_merchant_knowledge_category(
            db,
            context=context,
            category_key=payload.category_key,
            name=payload.name,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "KNOWLEDGE_CATEGORY_CONFLICT":
            raise HTTPException(status_code=409, detail={"code": code, "message": "知识分类已存在"}) from exc
        raise _bad_request(code, "知识分类参数不合法") from exc
    return {
        "success": True,
        "data": {
            "category_key": row.category_key,
            "name": row.name,
            "scope_type": row.scope_type,
            "is_base": bool(row.is_base),
        },
        "message": "success",
    }


@router.post("/rag/documents")
def create_rag_document_proxy(
    request: RagDocumentProxyRequest,
    gateway_context: GatewayContext = Depends(get_gateway_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9206 注入可信 scope 后代理创建 9100 RAG 文档。"""
    context = require_rag_context(gateway_context)
    account_open_id = str(request.account_open_id).strip()
    trusted_account_open_id = knowledge_service.validate_rag_account_scope(
        db=db,
        context=context,
        account_open_id=account_open_id,
    )
    category_key = _normalize_and_validate_category_key(
        db=db,
        context=context,
        category_key=request.category_key,
    )

    payload: dict[str, Any] = {
        "tenant_id": _trusted_tenant_id(context),
        "merchant_id": context.merchant_id,
        "douyin_account_id": trusted_account_open_id,
        "title": request.title,
        "content": request.content,
        "category_key": category_key,
    }
    if request.category is not None:
        payload["category"] = request.category
    if request.brand is not None:
        payload["brand"] = request.brand
    if request.vehicle_name is not None:
        payload["vehicle_name"] = request.vehicle_name

    logger.info(
        "knowledge_rag_document_proxy merchant_id=%s account_open_id=%s category_key=%s",
        context.merchant_id,
        trusted_account_open_id,
        category_key,
    )
    try:
        result = get_xg_douyin_ai_cs_client().create_rag_document(
            context=context,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
        ) from exc
    return {"success": True, "data": result, "message": "success"}


@router.post("/rag/train")
def train_rag_proxy(
    request: RagTrainProxyRequest,
    gateway_context: GatewayContext = Depends(get_gateway_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """由 9206 注入可信 scope 后代理触发 9100 RAG 训练。"""
    context = require_rag_context(gateway_context)
    account_open_id = str(request.account_open_id).strip()
    trusted_account_open_id = knowledge_service.validate_rag_account_scope(
        db=db,
        context=context,
        account_open_id=account_open_id,
    )
    category_key = _normalize_and_validate_category_key(
        db=db,
        context=context,
        category_key=request.category_key,
    )

    payload: dict[str, Any] = {
        "tenant_id": _trusted_tenant_id(context),
        "merchant_id": context.merchant_id,
        "douyin_account_id": trusted_account_open_id,
        "category_key": category_key,
    }
    if request.force_rebuild is not None:
        payload["force_rebuild"] = request.force_rebuild

    logger.info(
        "knowledge_rag_train_proxy merchant_id=%s account_open_id=%s category_key=%s force_rebuild=%s",
        context.merchant_id,
        trusted_account_open_id,
        category_key,
        request.force_rebuild,
    )
    try:
        result = get_xg_douyin_ai_cs_client().train_rag(
            context=context,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
        ) from exc
    return {"success": True, "data": result, "message": "success"}
