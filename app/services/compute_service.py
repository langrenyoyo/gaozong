"""小高算力 9000 兼容服务入口。

Phase 3-B 起，compute 业务实现收敛到 `apps.compute.services`。
旧导入路径继续保留，避免 9000 旧接口和既有测试失效。
"""

from apps.compute.services import (  # noqa: F401
    BASIS_POINT_DENOMINATOR,
    COMPUTE_CAPABILITY_KEYS,
    CONSUME_TYPE,
    POSTGRES_BIGINT_MAX,
    POSTGRES_INTEGER_MAX,
    TRANSACTION_TYPES,
    USAGE_SOURCES,
    calculate_billed_tokens,
    create_mock_recharge_order,
    create_package,
    get_or_create_account,
    get_package,
    get_summary,
    grant_package_to_merchant,
    list_admin_packages,
    list_enabled_packages,
    list_markup_ratios,
    list_transactions,
    list_merchant_transactions,
    recharge_merchant,
    record_usage,
    update_markup_ratio,
    update_package,
)

__all__ = [
    "BASIS_POINT_DENOMINATOR",
    "COMPUTE_CAPABILITY_KEYS",
    "CONSUME_TYPE",
    "POSTGRES_BIGINT_MAX",
    "POSTGRES_INTEGER_MAX",
    "TRANSACTION_TYPES",
    "USAGE_SOURCES",
    "calculate_billed_tokens",
    "create_mock_recharge_order",
    "create_package",
    "get_or_create_account",
    "get_package",
    "get_summary",
    "grant_package_to_merchant",
    "list_admin_packages",
    "list_enabled_packages",
    "list_markup_ratios",
    "list_transactions",
    "list_merchant_transactions",
    "recharge_merchant",
    "record_usage",
    "update_markup_ratio",
    "update_package",
]
