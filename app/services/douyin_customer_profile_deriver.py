"""抖音客户画像只读派生工具。

本模块只做纯函数派生，不访问外部服务、不写数据库。
"""

from __future__ import annotations

import re
from typing import Any


PROFILE_FIELD_NAMES = ("source_channel", "intent_car", "car_year", "budget", "city")
PROFILE_CITIES = ("广州", "深圳", "上海", "北京", "杭州")
SYSTEM_NOTICE_TEXTS = ("你收到一条新消息，请打开抖音app查看",)

RAW_FIELD_KEYS = {
    "source_channel": ("source_channel", "source"),
    "intent_car": ("intent_car", "car_model", "vehicle_model", "intent_car_model", "model", "series", "brand_model"),
    "car_year": ("car_year", "year", "vehicle_year", "model_year", "years"),
    "budget": ("budget", "intent_budget", "budget_range", "price_range"),
    "city": ("city", "location", "location_city", "customer_city"),
}


def empty_profile_fields() -> dict[str, str | None]:
    return {key: None for key in PROFILE_FIELD_NAMES}


def derive_profile_fields_from_raw_data(raw_data: dict[str, Any] | None) -> dict[str, str | None]:
    """从 raw_data 的兼容 key 中派生画像字段。"""
    data = raw_data if isinstance(raw_data, dict) else {}
    return {
        field: _first_raw_value(data, keys)
        for field, keys in RAW_FIELD_KEYS.items()
    }


def derive_profile_fields_from_messages(messages: list[str]) -> dict[str, str | None]:
    """只从客户入站文本中派生画像字段。调用方负责先过滤消息方向。"""
    result = empty_profile_fields()
    known_brand: str | None = None
    for item in messages:
        text = str(item or "").strip()
        if not text or text in SYSTEM_NOTICE_TEXTS:
            continue
        brand = _extract_profile_brand(text)
        if brand:
            known_brand = brand
        vehicle = _extract_profile_vehicle(text, known_brand)
        if vehicle:
            result["intent_car"] = vehicle
            vehicle_brand = _extract_profile_brand(vehicle)
            if vehicle_brand:
                known_brand = vehicle_brand
        year = _extract_profile_year(text)
        if year:
            result["car_year"] = year
        budget = _extract_profile_budget(text)
        if budget:
            result["budget"] = budget
        city = _extract_profile_city(text)
        if city:
            result["city"] = city
    return result


def merge_profile_fields(
    raw_data_fields: dict[str, Any] | None,
    message_fields: dict[str, Any] | None,
) -> dict[str, str | None]:
    """合并画像字段，raw_data 明确字段优先，消息推断只补空。"""
    raw = raw_data_fields or {}
    message = message_fields or {}
    merged: dict[str, str | None] = {}
    for field in PROFILE_FIELD_NAMES:
        merged[field] = _clean_text(raw.get(field)) or _clean_text(message.get(field))
    return merged


def _first_raw_value(raw_data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw_data.get(key)
        text = _clean_text(value)
        if text:
            return text
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = " / ".join(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    return text or None


def _extract_profile_budget(text: str) -> str | None:
    match = re.search(r"(\d{1,3})\s*万\s*(左右|以内|以上|上下|多)?", text)
    if not match:
        return None
    return f"{match.group(1)}万{match.group(2) or ''}"


def _extract_profile_year(text: str) -> str | None:
    pair = re.search(r"((?:20)?\d{2})\s*(?:年|款)?\s*(?:/|或|或者|、|和)\s*((?:20)?\d{2})\s*(?:年|款)", text)
    if pair:
        return f"{_normalize_profile_year(pair.group(1))} / {_normalize_profile_year(pair.group(2))}"
    values = re.findall(r"((?:20)?\d{2})\s*(?:年|款)", text)
    if len(values) >= 2:
        return f"{_normalize_profile_year(values[-2])} / {_normalize_profile_year(values[-1])}"
    if values:
        return _normalize_profile_year(values[-1])
    return None


def _normalize_profile_year(value: str) -> str:
    text = str(value or "").strip()
    return f"{text}款"


def _extract_profile_vehicle(text: str, known_brand: str | None) -> str | None:
    patterns = (
        r"(宝马)\s*(530Li|525Li|520Li|320Li|325Li|330Li)",
        r"(宝马)\s*(5系|3系|X3|X5)",
        r"(奥迪)\s*(A6L|A6|A4L|Q5L)",
        r"(奔驰)\s*(E级|C级|GLC)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}{match.group(2)}"

    standalone = re.search(
        r"(?<![A-Za-z0-9])(530Li|525Li|520Li|320Li|325Li|330Li|A6L|A6|A4L|Q5L)(?![A-Za-z0-9])",
        text,
        re.IGNORECASE,
    )
    if standalone:
        model = standalone.group(1)
        if (known_brand == "宝马" or "宝马" in text) and model.lower().endswith("li"):
            return f"宝马{model}"
        if (known_brand == "奥迪" or "奥迪" in text) and model.upper().startswith("A"):
            return f"奥迪{model}"
        return model

    brand = _extract_profile_brand(text)
    return brand


def _extract_profile_brand(text: str) -> str | None:
    for brand in ("宝马", "奥迪", "奔驰"):
        if brand in text:
            return brand
    return None


def _extract_profile_city(text: str) -> str | None:
    normalized = re.sub(r"[\s，。！？!?,.]", "", text)
    for city in PROFILE_CITIES:
        if city in normalized:
            return city
    return None

