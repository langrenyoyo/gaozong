"""统一知识库训练服务兼容入口。

Phase 3-C 后真实实现迁入 `apps.knowledge.services`，旧导入路径保留 re-export。
"""

from apps.knowledge.services import (  # noqa: F401
    ACTIVE_STATUS,
    BASE_CATEGORY_KEY,
    BASE_CATEGORY_NAME,
    MERCHANT_SCOPE,
    SYSTEM_SCOPE,
    build_effective_category_keys,
    create_merchant_knowledge_category,
    ensure_category_usable_for_merchant,
    get_active_merchant_category,
    list_visible_knowledge_categories,
    manual_category_keys,
    normalize_category_key,
    normalize_category_keys,
    normalize_category_name,
    require_context_merchant,
)

__all__ = [
    "ACTIVE_STATUS",
    "BASE_CATEGORY_KEY",
    "BASE_CATEGORY_NAME",
    "MERCHANT_SCOPE",
    "SYSTEM_SCOPE",
    "build_effective_category_keys",
    "create_merchant_knowledge_category",
    "ensure_category_usable_for_merchant",
    "get_active_merchant_category",
    "list_visible_knowledge_categories",
    "manual_category_keys",
    "normalize_category_key",
    "normalize_category_keys",
    "normalize_category_name",
    "require_context_merchant",
]
