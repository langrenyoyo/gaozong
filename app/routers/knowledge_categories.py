"""知识分类接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_async_sessionmaker, get_db
from app.repositories.knowledge_categories_async_repository import list_visible_knowledge_categories_async
from app.schemas import KnowledgeCategoryCreate, KnowledgeCategoryListResponse
from app.services.knowledge_category_service import (
    create_merchant_knowledge_category,
    list_visible_knowledge_categories,
)


router = APIRouter(prefix="/knowledge-categories", tags=["知识分类"])


def _auth(context: RequestContext) -> RequestContext:
    """知识分类当前服务于 AI小高智能体配置，跟随抖音 AI 客服权限。"""
    return require_permission("auto_wechat:douyin_ai_cs")(context)


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _deny_category_management() -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "code": "KNOWLEDGE_CATEGORY_CREATE_DISABLED",
            "message": "当前阶段不开放商户知识分类管理入口，请由管理员统一维护小高知识库。",
        },
    )


@router.get("", response_model=KnowledgeCategoryListResponse)
async def list_knowledge_categories(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        if config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED:
            try:
                session_factory = get_async_sessionmaker()
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "KNOWLEDGE_CATEGORIES_ASYNC_PG_RUNTIME_UNAVAILABLE",
                        "message": "知识分类 async PostgreSQL 试点未初始化",
                    },
                ) from exc
            async with session_factory() as session:
                categories = await list_visible_knowledge_categories_async(session, context=context)
        else:
            categories = list_visible_knowledge_categories(db, context=context)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": categories, "message": "success"}


@router.post("")
def create_knowledge_category(
    payload: KnowledgeCategoryCreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _deny_category_management()
    context = _auth(context)
    try:
        row = create_merchant_knowledge_category(
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
