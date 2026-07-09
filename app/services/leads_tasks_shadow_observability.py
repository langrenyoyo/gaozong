"""leads/tasks PG shadow read 轻量观测。"""

from __future__ import annotations

import logging
import threading
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_METRICS: dict[str, Any] = {}


def reset_shadow_metrics_for_tests() -> None:
    """重置内存指标，仅供测试使用。"""
    with _LOCK:
        _METRICS.clear()
        _METRICS.update(_empty_metrics())


def get_shadow_metrics_snapshot() -> dict[str, Any]:
    """返回当前内存指标快照，不包含 PII。"""
    with _LOCK:
        if not _METRICS:
            _METRICS.update(_empty_metrics())
        return deepcopy(_METRICS)


def record_shadow_result(result) -> None:
    """记录 shadow read 结果；日志只记录结构化摘要，不记录原始行或 PII。"""
    if not getattr(result, "enabled", False):
        return

    status = getattr(result, "status", "") or _derive_status(result)
    operation_key = f"{result.table}.{result.operation}"
    mismatch_count = int(getattr(result, "mismatch_count", 0) or 0)
    warnings_count = len(getattr(result, "warnings", []) or [])

    with _LOCK:
        if not _METRICS:
            _METRICS.update(_empty_metrics())
        _METRICS["total_shadow_reads"] += 1
        _METRICS["total_mismatch_count"] += mismatch_count
        if status == "pass":
            _METRICS["total_shadow_pass"] += 1
        elif status == "timeout":
            _METRICS["total_shadow_timeout"] += 1
        elif status == "error":
            _METRICS["total_shadow_error"] += 1
        elif status == "failed":
            _METRICS["total_shadow_failed"] += 1
        else:
            _METRICS["total_shadow_warn"] += 1

        by_operation = _METRICS["by_operation"].setdefault(operation_key, _empty_operation_metrics())
        by_operation["total"] += 1
        by_operation[status if status in by_operation else "warn"] += 1
        by_operation["mismatch_count"] += mismatch_count

    logger.warning(
        "component=leads_tasks_pg_shadow table=%s operation=%s status=%s count_match=%s "
        "key_match=%s mismatch_count=%s duration_ms=%s warnings_count=%s strict=%s "
        "request_scope=%s merchant_id_present=%s pii_redacted=True",
        result.table,
        result.operation,
        status,
        getattr(result, "count_match", True),
        getattr(result, "key_match", True),
        mismatch_count,
        getattr(result, "duration_ms", 0),
        warnings_count,
        getattr(result, "strict", False),
        getattr(result, "request_scope", None),
        getattr(result, "merchant_id_present", False),
    )


def _derive_status(result) -> str:
    if getattr(result, "warnings", None) or getattr(result, "mismatch_count", 0):
        return "warn"
    return "pass"


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_shadow_reads": 0,
        "total_shadow_pass": 0,
        "total_shadow_warn": 0,
        "total_shadow_failed": 0,
        "total_shadow_timeout": 0,
        "total_shadow_error": 0,
        "total_mismatch_count": 0,
        "by_operation": {},
    }


def _empty_operation_metrics() -> dict[str, int]:
    return {
        "total": 0,
        "pass": 0,
        "warn": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
        "mismatch_count": 0,
    }


reset_shadow_metrics_for_tests()
