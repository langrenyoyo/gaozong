"""小高算力 9000 兼容服务入口。

Phase 3-B 起，compute 业务实现收敛到 `apps.compute.services`。
旧导入路径继续保留，避免 9000 旧接口和既有测试失效。
"""

from apps.compute.services import (  # noqa: F401
    CONSUME_TYPE,
    TRANSACTION_TYPES,
    USAGE_SOURCES,
    create_mock_recharge_order,
    create_package,
    get_or_create_account,
    get_package,
    get_summary,
    grant_package_to_merchant,
    list_admin_packages,
    list_enabled_packages,
    list_transactions,
    recharge_merchant,
    record_usage,
    update_package,
)

__all__ = [
    "CONSUME_TYPE",
    "TRANSACTION_TYPES",
    "USAGE_SOURCES",
    "create_mock_recharge_order",
    "create_package",
    "get_or_create_account",
    "get_package",
    "get_summary",
    "grant_package_to_merchant",
    "list_admin_packages",
    "list_enabled_packages",
    "list_transactions",
    "recharge_merchant",
    "record_usage",
    "update_package",
]
