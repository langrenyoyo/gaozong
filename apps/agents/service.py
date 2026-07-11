"""AI小高智能体能力服务元数据与兼容导出。"""

from apps.agents.services import (
    ACTIVE_BINDING_BLOCK_DELETE_ERROR,
    ACTIVE_STATUSES,
    ACTIVE_STATUS,
    BASE_CATEGORY_KEY,
    DELETED_STATUS,
    TrainingChatResult,
    bind_agent_categories,
    build_effective_category_keys,
    create_agent,
    ensure_category_usable_for_merchant,
    get_agent,
    hard_delete_agent,
    has_active_douyin_account_binding,
    list_agent_category_keys,
    list_agents,
    manual_category_keys,
    normalize_category_key,
    normalize_category_keys,
    preview_training_chat,
    replace_agent_categories,
    require_context_merchant,
    soft_delete_agent,
    unbind_agent_category,
    update_agent,
)
from packages.common.capability import CapabilityMeta


META = CapabilityMeta(
    service="agents",
    name="AI小高智能体",
    description="AI小高智能体能力服务边界。",
)


__all__ = [
    "ACTIVE_BINDING_BLOCK_DELETE_ERROR",
    "ACTIVE_STATUSES",
    "ACTIVE_STATUS",
    "BASE_CATEGORY_KEY",
    "DELETED_STATUS",
    "META",
    "TrainingChatResult",
    "bind_agent_categories",
    "build_effective_category_keys",
    "create_agent",
    "ensure_category_usable_for_merchant",
    "get_agent",
    "hard_delete_agent",
    "has_active_douyin_account_binding",
    "list_agent_category_keys",
    "list_agents",
    "manual_category_keys",
    "normalize_category_key",
    "normalize_category_keys",
    "preview_training_chat",
    "replace_agent_categories",
    "require_context_merchant",
    "soft_delete_agent",
    "unbind_agent_category",
    "update_agent",
]
