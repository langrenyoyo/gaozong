"""知识分类 async PostgreSQL 试点 repository。"""

from __future__ import annotations

from sqlalchemy import text

from app.auth.context import RequestContext
from apps.knowledge.services import (
    ACTIVE_STATUS,
    MERCHANT_SCOPE,
    _base_category_dict,
    require_context_merchant,
)


async def list_visible_knowledge_categories_async(session, *, context: RequestContext) -> list[dict]:
    """列出当前商户可见分类；仅覆盖 GET /knowledge-categories 试点查询。"""
    merchant_id = require_context_merchant(context)
    result = await session.execute(
        text(
            """
            SELECT category_key, name, scope_type, is_base
            FROM knowledge_categories
            WHERE merchant_id = :merchant_id
              AND scope_type = :scope_type
              AND status = :status
              AND deleted_at IS NULL
            ORDER BY sort_order ASC, id ASC
            """
        ),
        {
            "merchant_id": merchant_id,
            "scope_type": MERCHANT_SCOPE,
            "status": ACTIVE_STATUS,
        },
    )
    categories = [_base_category_dict()]
    for row in result.mappings().all():
        categories.append(
            {
                "category_key": row["category_key"],
                "name": row["name"],
                "scope_type": row["scope_type"],
                "is_base": bool(row["is_base"]),
            }
        )
    return categories
