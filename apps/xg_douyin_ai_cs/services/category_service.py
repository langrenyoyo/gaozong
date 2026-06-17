"""分类服务。"""

from apps.xg_douyin_ai_cs.constants import CATEGORY_NAMES
from apps.xg_douyin_ai_cs.schemas import CategoryItem


def list_categories() -> list[CategoryItem]:
    """返回 P0 固定分类。"""
    return [
        CategoryItem(
            id=index,
            name=name,
            sort_order=index,
            is_active=True,
        )
        for index, name in enumerate(CATEGORY_NAMES, start=1)
    ]
