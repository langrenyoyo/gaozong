"""知识分类查询接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_any_permission
from app.database import get_db
from app.schemas import KnowledgeCategoryListResponse
from app.services.agent_knowledge_category_service import list_visible_knowledge_categories


router = APIRouter(prefix="/knowledge-categories", tags=["知识分类"])


def _auth(context: RequestContext) -> RequestContext:
    """复用智能体权限，分类当前只服务于 Agent 配置。"""
    return require_any_permission(["auto_wechat:ai_agents", "auto_wechat:agent"])(context)


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


@router.get("", response_model=KnowledgeCategoryListResponse)
def list_knowledge_categories(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    context = _auth(context)
    try:
        categories = list_visible_knowledge_categories(db, context=context)
    except ValueError as exc:
        raise _bad_request(str(exc), "缺少可信商户上下文") from exc
    return {"success": True, "data": categories, "message": "success"}
