"""顾客档案服务（P-0-C）。

职责：
- load_customer_profile：读取持久化档案（只读，商户隔离）
- upsert_customer_profile：upsert 档案（SAVEPOINT 隔离 + 商户归属校验）
- merge_profile_with_memory：DB 档案优先，合并实时派生 customer_memory
- resolve_salutation：根据档案推断称呼

约束：
- merchant_id + account_open_id + customer_open_id 唯一约束，商户隔离硬条件
- 联系方式状态（contact_state）为只读镜像，写入走 P0.2 contact_state 链路
- LLM 推断写 inferred_fields_json；客户明确确认写 confirmed_fields_json
- 写入失败不阻断主流程（档案是辅助上下文，非关键路径）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CustomerProfile

logger = logging.getLogger(__name__)

# 档案业务字段（不含 contact_state，它走 P0.2 链路）
_PROFILE_FIELDS = ("gender", "preferred_salutation", "intent_car", "car_year", "budget", "city")


def load_customer_profile(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
) -> dict[str, Any] | None:
    """读取持久化顾客档案（只读，商户隔离）。无记录返回 None。"""
    if not merchant_id or not account_open_id or not customer_open_id:
        return None
    profile = db.query(CustomerProfile).filter(
        CustomerProfile.merchant_id == merchant_id,
        CustomerProfile.account_open_id == account_open_id,
        CustomerProfile.customer_open_id == customer_open_id,
    ).first()
    if not profile:
        return None
    return {
        "gender": profile.gender,
        "preferred_salutation": profile.preferred_salutation,
        "intent_car": profile.intent_car,
        "car_year": profile.car_year,
        "budget": profile.budget,
        "city": profile.city,
        "contact_state": profile.contact_state,
        "confirmed_fields_json": profile.confirmed_fields_json,
        "inferred_fields_json": profile.inferred_fields_json,
        "source": profile.source,
    }


def upsert_customer_profile(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    customer_open_id: str,
    updates: dict[str, Any],
    source: str = "auto_reply",
    confirmed: bool = False,
) -> dict[str, Any] | None:
    """upsert 顾客档案（SAVEPOINT 隔离 + 商户归属校验）。

    - confirmed=True 写入 confirmed_fields_json（客户明确确认，高可信）
    - confirmed=False 写入 inferred_fields_json（LLM 推断，低可信）
    - 联系方式字段不从此处写入（走 P0.2 contact_state 链路）
    - 顶层业务字段更新：confirmed 覆盖 inferred，inferred 不覆盖 confirmed
    - 写入失败不抛异常（档案是辅助上下文，非关键路径），返回 None
    """
    if not merchant_id or not account_open_id or not customer_open_id:
        return None
    # 过滤只允许的字段 + 去除空值
    filtered = {k: v for k, v in updates.items() if k in _PROFILE_FIELDS and v}
    if not filtered:
        return None

    try:
        with db.begin_nested():  # SAVEPOINT 隔离
            existing = db.query(CustomerProfile).filter(
                CustomerProfile.merchant_id == merchant_id,
                CustomerProfile.account_open_id == account_open_id,
                CustomerProfile.customer_open_id == customer_open_id,
            ).first()
            if existing:
                _apply_updates(existing, filtered, source, confirmed)
            else:
                profile = CustomerProfile(
                    merchant_id=merchant_id,
                    account_open_id=account_open_id,
                    customer_open_id=customer_open_id,
                    source=source,
                )
                _apply_updates(profile, filtered, source, confirmed)
                db.add(profile)
            db.flush()
        return filtered
    except IntegrityError as exc:
        # 唯一约束冲突（并发 upsert）→ 回滚 SAVEPOINT，重新查询已存在记录做幂等更新
        # 对齐 webhook R4-R5 模式：冲突后 no_autoflush 重新查归属，同商户→幂等更新
        logger.warning(
            "customer_profile_upsert_conflict merchant_id=%s account_open_id=%s "
            "customer_open_id=%s error_type=%s",
            merchant_id, account_open_id, customer_open_id, type(exc).__name__,
        )
        try:
            with db.no_autoflush:
                existing = db.query(CustomerProfile).filter(
                    CustomerProfile.merchant_id == merchant_id,
                    CustomerProfile.account_open_id == account_open_id,
                    CustomerProfile.customer_open_id == customer_open_id,
                ).first()
            if existing:
                _apply_updates(existing, filtered, source, confirmed)
                db.flush()
                return filtered
        except Exception as retry_exc:
            logger.warning(
                "customer_profile_upsert_retry_failed merchant_id=%s account_open_id=%s "
                "customer_open_id=%s error_type=%s",
                merchant_id, account_open_id, customer_open_id, type(retry_exc).__name__,
            )
        return None
    except Exception as exc:
        logger.warning(
            "customer_profile_upsert_failed merchant_id=%s account_open_id=%s "
            "customer_open_id=%s error_type=%s error=%s",
            merchant_id, account_open_id, customer_open_id,
            type(exc).__name__, str(exc)[:200],
        )
        return None


def _apply_updates(
    profile: CustomerProfile,
    updates: dict[str, Any],
    source: str,
    confirmed: bool,
) -> None:
    """应用更新到 profile 对象（confirmed 覆盖 inferred，inferred 不覆盖 confirmed）。"""
    # 加载已有字段集（_JSONStringJSONB 从 DB 读回是 JSON 字符串，需 json.loads 解包）
    confirmed_raw = profile.confirmed_fields_json
    inferred_raw = profile.inferred_fields_json
    confirmed_set = json.loads(confirmed_raw) if isinstance(confirmed_raw, str) else (confirmed_raw or {})
    inferred_set = json.loads(inferred_raw) if isinstance(inferred_raw, str) else (inferred_raw or {})

    for field, value in updates.items():
        if field not in _PROFILE_FIELDS:
            continue
        value_str = str(value).strip()[:100] if value else None
        if not value_str:
            continue
        # confirmed 写入 confirmed_fields + 顶层字段；inferred 只在非 confirmed 时覆盖顶层
        if confirmed:
            confirmed_set[field] = value_str
            setattr(profile, field, value_str)
        else:
            inferred_set[field] = value_str
            # inferred 不覆盖已 confirmed 的字段
            if field not in confirmed_set:
                setattr(profile, field, value_str)

    # _JSONStringJSONB 期望 JSON 字符串（str），不是 dict
    profile.confirmed_fields_json = json.dumps(confirmed_set, ensure_ascii=False) if confirmed_set else None
    profile.inferred_fields_json = json.dumps(inferred_set, ensure_ascii=False) if inferred_set else None
    profile.source = source
    profile.updated_at = datetime.now()


def merge_profile_with_memory(
    persisted: dict[str, Any] | None,
    derived_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    """DB 档案优先，合并实时派生 customer_memory，注入 9100 上下文。

    DB 档案（持久化）优先于实时派生（内存态，可能丢失）。
    P-0-C 阶段3：区分 confirmed（客户明确说的）和 inferred（LLM 推断的），
    注入 field_sources 标注每个字段来源，供 LLM 区分可信度。
    """
    if not persisted:
        return derived_memory or {}
    if not derived_memory:
        derived_memory = {}
    # 加载 confirmed/inferred 分层（_JSONStringJSONB 从 DB 读回是 JSON 字符串，需反序列化）
    confirmed = persisted.get("confirmed_fields_json") or {}
    inferred = persisted.get("inferred_fields_json") or {}
    if isinstance(confirmed, str):
        confirmed = json.loads(confirmed) if confirmed else {}
    if isinstance(inferred, str):
        inferred = json.loads(inferred) if inferred else {}

    merged = dict(derived_memory)
    field_sources: dict[str, str] = {}
    for field in _PROFILE_FIELDS:
        # confirmed 优先覆盖顶层字段
        if confirmed.get(field):
            merged[field] = confirmed[field]
            field_sources[field] = "confirmed"
        elif inferred.get(field):
            merged[field] = inferred[field]
            field_sources[field] = "inferred"
        elif merged.get(field):
            field_sources[field] = "derived"
    merged["field_sources"] = field_sources
    # contact 仍以 derived_memory 为准（9000 注入的可信 contact_state）
    if "contact" not in merged and persisted.get("contact_state"):
        merged["contact"] = {"has_contact": persisted.get("contact_state") == "valid"}
    # 称呼
    merged["salutation"] = resolve_salutation(persisted)
    return merged


def resolve_salutation(profile: dict[str, Any] | None) -> str:
    """根据档案推断称呼：客户要求 > 性别 > 默认老板。"""
    if not profile:
        return "老板"
    salutation = profile.get("preferred_salutation")
    if salutation:
        return salutation
    gender = profile.get("gender", "unknown")
    if gender == "female":
        return "女士"
    return "老板"  # unknown/male
