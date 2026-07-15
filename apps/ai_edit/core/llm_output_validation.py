"""LLM 输出校验的最小公共结构与工具。

来源注记：迁自 auto_edit@develop d0c8189 src/auto_edit/llm_output_validation.py，
改包路径为 apps.ai_edit.core。原文件为纯函数、无路径/无密钥/无样片词，原样迁入。

本模块只提供通用 report 结构和纯函数工具，不承载专项业务规则。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


RISK_LEVELS = {"low", "medium", "high"}


def build_validation_result(
    *,
    validator_name: str,
    validator_version: str,
    validator_valid: bool,
    normalized_payload: Any | None = None,
    rejection_reasons: Iterable[Any] | None = None,
    warnings: list[Any] | None = None,
    manual_review_required: bool = False,
    risk_level: str = "low",
    unsafe_field_count: int = 0,
    traceability_errors: list[Any] | None = None,
    candidate_errors: list[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一 validator 结果结构。"""
    normalized_risk_level = risk_level if risk_level in RISK_LEVELS else "low"
    return {
        "validator_name": validator_name,
        "validator_version": validator_version,
        "validated": True,
        "validator_valid": bool(validator_valid),
        "normalized_payload": normalized_payload if normalized_payload is not None else {},
        "rejection_reasons": merge_rejection_reasons(rejection_reasons or []),
        "warnings": list(warnings or []),
        "manual_review_required": bool(manual_review_required),
        "risk_level": normalized_risk_level,
        "unsafe_field_count": int(unsafe_field_count or 0),
        "traceability_errors": list(traceability_errors or []),
        "candidate_errors": list(candidate_errors or []),
        "metadata": dict(metadata or {}),
    }


def merge_rejection_reasons(*reason_groups: Iterable[Any]) -> list[str]:
    """合并拒绝原因，保持首次出现顺序并去重。"""
    merged: list[str] = []
    seen: set[str] = set()
    for reasons in reason_groups:
        for reason in reasons:
            reason_text = str(reason or "")
            if reason_text and reason_text not in seen:
                merged.append(reason_text)
                seen.add(reason_text)
    return merged


def count_unsafe_fields(value: Any, unsafe_fields: set[str] | frozenset[str]) -> int:
    """递归统计命中的危险字段数量。"""
    normalized_fields = {field.lower() for field in unsafe_fields}
    if isinstance(value, Mapping):
        count = 0
        for key, child in value.items():
            if str(key).lower() in normalized_fields:
                count += 1
            count += count_unsafe_fields(child, normalized_fields)
        return count
    if isinstance(value, list):
        return sum(count_unsafe_fields(child, normalized_fields) for child in value)
    return 0


def summarize_batch_validation(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """汇总统一 validator 结果。"""
    reason_counts: Counter[str] = Counter()
    valid_count = 0
    copied_items = [dict(item) for item in items]

    for item in copied_items:
        if bool(item.get("validator_valid")):
            valid_count += 1
        else:
            for reason in item.get("rejection_reasons") or []:
                reason_text = str(reason or "")
                if reason_text:
                    reason_counts[reason_text] += 1

    total_count = len(copied_items)
    return {
        "total_count": total_count,
        "valid_count": valid_count,
        "invalid_count": total_count - valid_count,
        "rejection_reason_counts": dict(reason_counts),
        "items": copied_items,
    }


def adapt_legacy_validator_result(
    legacy_result: Mapping[str, Any],
    *,
    validator_name: str,
    validator_version: str,
    normalized_payload: Any | None = None,
    unsafe_field_count: int = 0,
    traceability_errors: list[Any] | None = None,
    candidate_errors: list[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把现有 validator report 转为统一字段，不修改旧 report。"""
    validator_valid = bool(legacy_result.get("valid"))
    rejection_reason = legacy_result.get("rejection_reason")
    rejection_reasons = [] if validator_valid else [rejection_reason]
    merged_metadata = {
        "legacy_valid": validator_valid,
        "legacy_rejection_reason": rejection_reason,
        "legacy_result": dict(legacy_result),
    }
    merged_metadata.update(dict(metadata or {}))

    return build_validation_result(
        validator_name=validator_name,
        validator_version=validator_version,
        validator_valid=validator_valid,
        normalized_payload=normalized_payload,
        rejection_reasons=rejection_reasons,
        warnings=list(legacy_result.get("warnings") or []),
        manual_review_required=_legacy_manual_review_required(legacy_result),
        risk_level=str(legacy_result.get("risk_level") or "low"),
        unsafe_field_count=unsafe_field_count,
        traceability_errors=traceability_errors,
        candidate_errors=candidate_errors,
        metadata=merged_metadata,
    )


def _legacy_manual_review_required(legacy_result: Mapping[str, Any]) -> bool:
    if "manual_review_required" in legacy_result:
        return bool(legacy_result.get("manual_review_required"))
    return bool(legacy_result.get("manual_review_required_count") or 0)
