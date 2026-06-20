"""抖音自动回复配置服务。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import DouyinAccountAutoreplySetting


def get_account_autoreply_settings(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
) -> DouyinAccountAutoreplySetting | None:
    """按可信商户和企业号读取自动回复配置，不自动创建默认配置。"""
    if not merchant_id or not account_open_id:
        return None
    return (
        db.query(DouyinAccountAutoreplySetting)
        .filter(DouyinAccountAutoreplySetting.merchant_id == merchant_id)
        .filter(DouyinAccountAutoreplySetting.account_open_id == account_open_id)
        .first()
    )


def parse_allowed_intents(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析允许自动决策的低风险意图列表。"""
    if settings is None:
        return []
    return _parse_string_list(settings.allowed_intents_json)


def parse_blocked_risk_flags(settings: DouyinAccountAutoreplySetting | None) -> list[str]:
    """解析明确阻断的风险标记列表。"""
    if settings is None:
        return []
    return _parse_string_list(settings.blocked_risk_flags_json)


def _parse_string_list(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result
