"""9000 知识分类主数据服务。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import KnowledgeCategory


ACTIVE_STATUS = "active"
BASE_CATEGORY_KEY = "base"
BASE_CATEGORY_NAME = "基础知识"
MERCHANT_SCOPE = "merchant"
SYSTEM_SCOPE = "system"


def require_context_merchant(context: RequestContext) -> str:
    if not context.merchant_id:
        raise ValueError("MERCHANT_ID_REQUIRED")
    return context.merchant_id


def normalize_category_key(category_key: str | None, *, default_base: bool = False) -> str:
    if category_key is None:
        if default_base:
            return BASE_CATEGORY_KEY
        raise ValueError("CATEGORY_KEY_REQUIRED")
    key = str(category_key).strip()
    if not key:
        raise ValueError("CATEGORY_KEY_REQUIRED")
    return key


def normalize_category_name(name: str | None) -> str:
    value = str(name).strip() if name is not None else ""
    if not value:
        raise ValueError("CATEGORY_NAME_REQUIRED")
    return value


def normalize_category_keys(category_keys: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_key in category_keys:
        key = normalize_category_key(raw_key)
        if key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def manual_category_keys(category_keys: list[str]) -> list[str]:
    return [key for key in normalize_category_keys(category_keys) if key != BASE_CATEGORY_KEY]


def build_effective_category_keys(category_keys: list[str]) -> list[str]:
    effective = [BASE_CATEGORY_KEY]
    for key in normalize_category_keys(category_keys):
        if key == BASE_CATEGORY_KEY or key in effective:
            continue
        effective.append(key)
    return effective


def _base_category_dict() -> dict:
    return {
        "category_key": BASE_CATEGORY_KEY,
        "name": BASE_CATEGORY_NAME,
        "scope_type": SYSTEM_SCOPE,
        "is_base": True,
    }


def list_visible_knowledge_categories(db: Session, *, context: RequestContext) -> list[dict]:
    """列出当前商户可见分类：逻辑 base + 当前商户 active merchant 主表分类。"""
    merchant_id = require_context_merchant(context)
    rows = (
        db.query(KnowledgeCategory)
        .filter(
            KnowledgeCategory.merchant_id == merchant_id,
            KnowledgeCategory.scope_type == MERCHANT_SCOPE,
            KnowledgeCategory.status == ACTIVE_STATUS,
            KnowledgeCategory.deleted_at.is_(None),
        )
        .order_by(KnowledgeCategory.sort_order.asc(), KnowledgeCategory.id.asc())
        .all()
    )
    categories = [_base_category_dict()]
    for row in rows:
        categories.append(
            {
                "category_key": row.category_key,
                "name": row.name,
                "scope_type": row.scope_type,
                "is_base": bool(row.is_base),
            }
        )
    return categories


def get_active_merchant_category(
    db: Session,
    *,
    merchant_id: str,
    category_key: str,
) -> KnowledgeCategory | None:
    return (
        db.query(KnowledgeCategory)
        .filter(
            KnowledgeCategory.merchant_id == merchant_id,
            KnowledgeCategory.category_key == category_key,
            KnowledgeCategory.scope_type == MERCHANT_SCOPE,
            KnowledgeCategory.status == ACTIVE_STATUS,
            KnowledgeCategory.deleted_at.is_(None),
        )
        .first()
    )


def ensure_category_usable_for_merchant(
    db: Session,
    *,
    context: RequestContext,
    category_key: str | None,
    default_base: bool = False,
) -> str:
    """校验分类是否可被当前商户使用；base 允许但不要求主表落行。"""
    merchant_id = require_context_merchant(context)
    key = normalize_category_key(category_key, default_base=default_base)
    if key == BASE_CATEGORY_KEY:
        return key
    if get_active_merchant_category(db, merchant_id=merchant_id, category_key=key) is None:
        raise ValueError("CATEGORY_NOT_USABLE")
    return key


def create_merchant_knowledge_category(
    db: Session,
    *,
    context: RequestContext,
    category_key: str,
    name: str,
) -> KnowledgeCategory:
    """创建当前商户 merchant 分类；重复 key 返回冲突错误。"""
    merchant_id = require_context_merchant(context)
    key = normalize_category_key(category_key)
    display_name = normalize_category_name(name)
    if key == BASE_CATEGORY_KEY:
        raise ValueError("BASE_CATEGORY_READONLY")

    existing = (
        db.query(KnowledgeCategory)
        .filter(
            KnowledgeCategory.merchant_id == merchant_id,
            KnowledgeCategory.category_key == key,
        )
        .first()
    )
    if existing is not None:
        raise ValueError("KNOWLEDGE_CATEGORY_CONFLICT")

    now = datetime.now()
    row = KnowledgeCategory(
        tenant_id=None,
        merchant_id=merchant_id,
        category_key=key,
        name=display_name,
        scope_type=MERCHANT_SCOPE,
        is_base=0,
        status=ACTIVE_STATUS,
        sort_order=100,
        created_at=now,
        updated_at=now,
        created_by=context.user_id,
        updated_by=context.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
