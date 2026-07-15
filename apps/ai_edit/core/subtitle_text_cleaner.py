"""字幕/展示文本清理（通用骨架）。

来源注记：迁自 auto_edit@develop d0c8189 src/auto_edit/subtitle_text_cleaner.py，
改包路径为 apps.ai_edit.core。删除样片专用硬编码台词修正（具体 raw→display 品牌映射，
审计报告 §7.15 禁止样片规则作为全局策略），保留通用清理骨架与审计报告结构。
后续按版本化商户模板注入人工确认修正项。

本模块只做当前阶段人工确认的白名单展示修正：
- 不改写 speech_text；
- 不改 source 时间；
- 不泛化修正退赔/价格/质保等敏感内容。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_subtitle_text_cleanup(
    segments: list[dict[str, Any]],
    corrections: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """给片段补充 display/subtitle 字段，并返回审计报告。

    corrections 为版本化商户模板注入的人工确认修正项列表，每项形如：
      {"raw_text": "...", "display_text": "...", "risk_level": "low|medium|high",
       "requires_text_review": bool, "notes": [...], "source": "..."}
    无匹配修正项时透传 speech_text 到 display/subtitle。
    """
    correction_map: dict[str, dict[str, Any]] = {}
    for c in corrections or []:
        raw_key = str(c.get("raw_text", "")).strip()
        if raw_key:
            correction_map[raw_key] = c

    cleaned: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    raw_display_pairs: list[dict[str, Any]] = []
    warnings: list[str] = []

    for segment in segments:
        new_segment = deepcopy(segment)
        raw_text = str(new_segment.get("speech_text", "") or "")
        correction = correction_map.get(raw_text)

        display_text = correction["display_text"] if correction else raw_text
        subtitle_text = correction["subtitle_text"] if correction and "subtitle_text" in correction else display_text

        new_segment["raw_speech_text"] = raw_text
        new_segment["display_text"] = display_text
        new_segment["subtitle_text"] = subtitle_text
        new_segment["text_correction_status"] = (
            correction.get("status", "manual_confirmed") if correction else "none"
        )
        new_segment["text_correction_source"] = (
            correction.get("source", "manual_review") if correction else "none"
        )
        new_segment["text_correction_notes"] = (
            list(correction.get("notes", [])) if correction else []
        )
        new_segment["requires_text_review"] = bool(
            correction.get("requires_text_review", False) if correction else False
        )
        new_segment["text_correction_risk_level"] = (
            correction.get("risk_level", "low") if correction else "low"
        )

        if correction:
            record = _correction_record(new_segment, raw_text, display_text, subtitle_text)
            applied.append(record)
            if correction.get("risk_level") == "high":
                warnings.append("high_risk_text_correction_requires_manual_audit")

        raw_display_pairs.append(
            {
                "order": new_segment.get("order"),
                "asset_id": new_segment.get("asset_id"),
                "raw_speech_text": raw_text,
                "display_text": display_text,
                "subtitle_text": subtitle_text,
                "text_correction_status": new_segment["text_correction_status"],
            }
        )
        cleaned.append(new_segment)

    return cleaned, {
        "text_cleanup_enabled": True,
        "text_cleanup_corrections": applied,
        "text_cleanup_corrections_count": len(applied),
        "manual_confirmed_corrections_count": sum(
            1 for c in applied if c["correction_status"] == "manual_confirmed"
        ),
        "high_risk_corrections_count": sum(
            1 for c in applied if c["risk_level"] == "high"
        ),
        "needs_review_corrections_count": sum(
            1 for c in applied if c["correction_status"] == "needs_review"
        ),
        "raw_display_text_pairs": raw_display_pairs,
        "subtitle_text_available": True,
        "subtitle_uses_display_text": True,
        "text_cleanup_warnings": _dedupe_preserve_order(warnings),
    }


def _correction_record(
    segment: dict[str, Any],
    raw_text: str,
    display_text: str,
    subtitle_text: str,
) -> dict[str, Any]:
    return {
        "order": segment.get("order"),
        "clip_index": segment.get("order"),
        "asset_id": segment.get("asset_id"),
        "source_start": segment.get("source_start", segment.get("start")),
        "source_end": segment.get("source_end", segment.get("end")),
        "raw_text": raw_text,
        "display_text": display_text,
        "subtitle_text": subtitle_text,
        "correction_source": segment["text_correction_source"],
        "correction_status": segment["text_correction_status"],
        "risk_level": segment["text_correction_risk_level"],
        "requires_text_review": segment["requires_text_review"],
        "notes": segment["text_correction_notes"],
    }


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
