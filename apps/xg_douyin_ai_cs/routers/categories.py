"""分类路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.schemas import CategoryListResponse
from apps.xg_douyin_ai_cs.services.category_service import list_categories

router = APIRouter(tags=["分类配置"])


@router.get("/categories", response_model=CategoryListResponse)
def get_categories() -> CategoryListResponse:
    return CategoryListResponse(items=list_categories())
