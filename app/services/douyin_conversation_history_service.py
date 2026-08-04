"""抖音私信会话历史上下文组装服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import DouyinLead
from app.services.contact_extractor import (
    extract_contacts_from_text,
    mask_contact_value,
    mask_contacts_in_text,
)
from app.services.douyin_customer_profile_deriver import derive_profile_fields_from_messages
from app.services.douyin_workbench_conversation_service import get_conversation_detail


@dataclass(frozen=True)
class ReplyConversationContext:
    latest_message: str
    conversation_history: list[dict[str, str]]
    customer_memory: dict[str, Any]
    # P0.2-B：暴露 lead 供 contact_state_service 严格验证历史联系方式（只读，不进 9100 payload）。
    # lead 本身不传给 9100；build_request_contact_state 只从中提取脱敏 evidence_ref。
    lead: Any = None


def build_reply_conversation_context(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_key: str,
    latest_message: str,
    limit: int = 10,
) -> ReplyConversationContext:
    """组装回复链路共用的脱敏历史与可信客户记忆。

    不得使用空 merchant_id 查询资源：需要读取会话/线索时必须先确认可信商户上下文，
    否则显式阻断，不执行跨商户查询。
    """
    if not account_open_id or not conversation_key:
        return ReplyConversationContext(
            latest_message=mask_contacts_in_text(latest_message),
            conversation_history=[],
            customer_memory=_build_customer_memory(latest_message=latest_message, profile=None, lead=None, items=[]),
            lead=None,
        )
    # 需要查询资源时必须先确认可信商户，禁止空 merchant_id 跨商户查询。
    if not merchant_id:
        raise ValueError("merchant_id_required")

    detail = get_conversation_detail(
        db,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        strict=True,
        merchant_id=merchant_id,
    )
    messages = detail.get("messages") if isinstance(detail, dict) else None
    items = messages.get("items") if isinstance(messages, dict) else []
    if not isinstance(items, list):
        raise ValueError("conversation_items_invalid")
    profile = detail.get("profile") if isinstance(detail.get("profile"), dict) else None
    lead = _load_profile_lead(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        profile=profile,
    )

    history_items = [_to_history_item(item) for item in items if isinstance(item, dict)]
    history_items = [item for item in history_items if item is not None]
    history_items = _drop_latest_customer_message(history_items, latest_message)
    if limit <= 0:
        history_items = []
    else:
        history_items = history_items[-min(limit, 10) :]
    masked_history = [
        {**item, "content": mask_contacts_in_text(item["content"])}
        for item in history_items
    ]
    return ReplyConversationContext(
        latest_message=mask_contacts_in_text(latest_message),
        conversation_history=masked_history,
        customer_memory=_build_customer_memory(
            latest_message=latest_message,
            profile=profile,
            lead=lead,
            items=items,
        ),
        lead=lead,
    )


def build_conversation_history(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_key: str,
    latest_message: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    """兼容旧调用；新回复链路应使用 build_reply_conversation_context。

    不得使用空 merchant_id 查询资源：缺少可信商户时显式阻断，不执行跨商户查询。
    """
    if not merchant_id:
        raise ValueError("merchant_id_required")
    return build_reply_conversation_context(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        latest_message=latest_message,
        limit=limit,
    ).conversation_history


def _load_profile_lead(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    profile: dict[str, Any] | None,
) -> DouyinLead | None:
    lead_data = profile.get("lead") if isinstance(profile, dict) else None
    lead_id = lead_data.get("id") if isinstance(lead_data, dict) else None
    if not lead_id:
        return None
    lead = db.get(DouyinLead, int(lead_id))
    if lead is None:
        raise ValueError("conversation_lead_missing")
    if merchant_id and lead.merchant_id and str(lead.merchant_id) != str(merchant_id):
        raise PermissionError("conversation_lead_merchant_mismatch")
    if lead.account_open_id and str(lead.account_open_id) != str(account_open_id):
        raise PermissionError("conversation_lead_account_mismatch")
    if lead.raw_data:
        parsed = json.loads(lead.raw_data)
        if not isinstance(parsed, dict):
            raise ValueError("conversation_lead_raw_data_invalid")
    return lead


def _build_customer_memory(
    *,
    latest_message: str,
    profile: dict[str, Any] | None,
    lead: DouyinLead | None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    current = derive_profile_fields_from_messages([latest_message])
    saved = profile or {}
    contacts = _customer_contact_memory(latest_message=latest_message, lead=lead, items=items)
    # customer_memory 中所有字符串字段（intent_car/car_year/budget/city 及 contact 内集合）
    # 必须脱敏手机号和微信号；任一脱敏异常上抛阻断上下文构建，不返回部分结果。
    return {
        "intent_car": _masked_memory_text(current.get("intent_car") or saved.get("intent_car")),
        "car_year": _masked_memory_text(current.get("car_year") or saved.get("car_year")),
        "budget": _masked_memory_text(current.get("budget") or saved.get("budget")),
        "city": _masked_memory_text(current.get("city") or saved.get("city")),
        "contact": contacts,
    }


def _masked_memory_text(value: Any) -> str | None:
    """脱敏记忆字段中的手机号/微信号，并截断长度；解析异常抛错以阻断上下文构建。"""
    text = str(value or "").strip()
    if not text:
        return None
    masked = mask_contacts_in_text(text)  # 解析失败抛 ValueError，由调用方阻断
    return masked[:100] if masked else None


def _customer_contact_memory(
    *,
    latest_message: str,
    lead: DouyinLead | None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    contacts: list[tuple[str, str]] = []
    has_persisted_contact = bool(
        lead
        and any(
            str(value or "").strip()
            for value in (lead.extracted_phone, lead.extracted_wechat, lead.all_extracted_contacts)
        )
    )

    def append_from_text(value: Any) -> None:
        extracted = extract_contacts_from_text(str(value or ""))
        if extracted.status == "parse_failed":
            raise ValueError("contact_parse_failed")
        for item in extracted.all_contacts:
            candidate = (str(item["type"]), str(item["value"]))
            if candidate not in contacts:
                contacts.append(candidate)

    append_from_text(latest_message)
    if lead is not None:
        if lead.extracted_phone:
            contacts.append(("phone", str(lead.extracted_phone)))
        if lead.extracted_wechat:
            contacts.append(("wechat", str(lead.extracted_wechat)))
        _append_stored_contacts(contacts, lead.all_extracted_contacts)
    for item in items:
        if item.get("sender_type") == "customer" or item.get("direction") == "inbound":
            append_from_text(item.get("content"))

    unique: list[tuple[str, str]] = []
    for item in contacts:
        if item not in unique:
            unique.append(item)
    return {
        "has_contact": bool(unique) or has_persisted_contact,
        "types": list(dict.fromkeys(item[0] for item in unique)),
        "masked_values": [mask_contact_value(contact_type, value) for contact_type, value in unique[:10]],
    }


def _append_stored_contacts(contacts: list[tuple[str, str]], raw_value: str | None) -> None:
    if not raw_value:
        return
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        parsed = raw_value

    def visit(value: Any, contact_type: str | None = None) -> None:
        if isinstance(value, dict):
            item_type = str(value.get("type") or contact_type or "") or None
            if value.get("value"):
                visit(value["value"], item_type)
            for key, child in value.items():
                if key in {"value", "type"}:
                    continue
                inferred = "phone" if key == "phones" else "wechat" if key == "wechats" else contact_type
                visit(child, inferred)
            return
        if isinstance(value, list):
            for child in value:
                visit(child, contact_type)
            return
        text = str(value or "").strip()
        if not text:
            return
        if contact_type in {"phone", "wechat"}:
            candidate = (contact_type, text)
            if candidate not in contacts:
                contacts.append(candidate)
            return
        extracted = extract_contacts_from_text(text)
        for item in extracted.all_contacts:
            candidate = (str(item["type"]), str(item["value"]))
            if candidate not in contacts:
                contacts.append(candidate)

    visit(parsed)


def _to_history_item(item: dict[str, Any]) -> dict[str, str] | None:
    role = _role_for_message(item)
    if role is None:
        return None

    content = str(item.get("content") or "").strip()
    if not content:
        return None

    message_id = str(item.get("server_message_id") or item.get("raw_event_id") or item.get("id") or "").strip()
    origin, fact_trust, direction = _origin_and_trust_for_message(item)
    result = {
        "role": role,
        "content": content,
        "created_at": _format_created_at(item.get("created_at")),
        "message_id": message_id,
        # P0.2-A 历史来源分层：保留 role 兼容，新增 origin/direction/fact_trust 元数据。
        # operator_id 等敏感字段不传给 9100；send_source 仅用于派生 origin，不原样透传。
        "origin": origin,
        "direction": direction,
        "fact_trust": fact_trust,
    }
    return result


def _role_for_message(item: dict[str, Any]) -> str | None:
    sender_type = str(item.get("sender_type") or "").strip()
    direction = str(item.get("direction") or "").strip()
    if sender_type == "customer" or direction == "inbound":
        return "customer"
    if sender_type == "staff" or direction == "outbound":
        return "agent"
    return None


# R2-3：send_source 明确白名单。不得使用"非 ai_auto 即人工"的过宽推断。
# AI 自动化来源（send_source 白名单 或 auto_reply_run_id/return_visit_run_id 有值）
_AI_SEND_SOURCES = frozenset({"ai_auto", "return_visit_auto"})
# 明确人工来源（send_source 白名单）
_HUMAN_SEND_SOURCES = frozenset({"manual"})


def _origin_and_trust_for_message(item: dict[str, Any]) -> tuple[str, str, str]:
    """P0.2-A + R1-1 + R2-3：派生历史消息来源身份与事实可信度。

    返回 (origin, fact_trust, direction)：
    - 客户入站消息：origin=customer, fact_trust=verified_customer
    - send_source 属 AI 白名单 {ai_auto, return_visit_auto} 或 auto_reply_run_id 有值：
      origin=ai_assistant, fact_trust=ai_generated
    - send_source 属人工白名单 {manual}：origin=human_agent, fact_trust=human_statement
    - send_source 为空且 operator_id 存在：origin=human_agent, fact_trust=human_statement
    - 其他出站（含未知非空 send_source + operator_id，或空 source 无 operator_id）：
      origin=unknown_agent, fact_trust=unverified_agent_output
    - 系统消息：origin=system, fact_trust=system_instruction

    R3 优先级冻结：未知非空 send_source 不得被 operator_id 覆盖成人工来源。
    AI 历史只用于上下文连续性，不得成为客户事实来源（fact_trust=ai_generated）。
    数据来源：DouyinPrivateMessageSend.send_source（经 _conversation_messages_payload 透传）。
    """
    sender_type = str(item.get("sender_type") or "").strip()
    direction = str(item.get("direction") or "").strip()
    send_source = str(item.get("send_source") or "").strip()
    auto_reply_run_id = item.get("auto_reply_run_id")
    operator_id = item.get("operator_id")
    if sender_type == "customer" or direction == "inbound":
        return "customer", "verified_customer", direction or "inbound"
    if sender_type == "staff" or direction == "outbound":
        # R3 优先级冻结：send_source 属 AI 白名单 或 auto_reply_run_id 有值 → ai_assistant
        if send_source in _AI_SEND_SOURCES or auto_reply_run_id:
            return "ai_assistant", "ai_generated", direction or "outbound"
        # send_source 属人工白名单 → human_agent
        if send_source in _HUMAN_SEND_SOURCES:
            return "human_agent", "human_statement", direction or "outbound"
        # R3：send_source 为空且 operator_id 存在 → human_agent（无来源证据时 operator_id 兜底）
        if not send_source and operator_id:
            return "human_agent", "human_statement", direction or "outbound"
        # R3：未知非空 send_source（不在白名单）不得被 operator_id 覆盖成人工 → unknown_agent
        # send_source 为空且无 operator_id → unknown_agent
        return "unknown_agent", "unverified_agent_output", direction or "outbound"
    return "system", "system_instruction", direction or ""


def _drop_latest_customer_message(
    history_items: list[dict[str, str]],
    latest_message: str,
) -> list[dict[str, str]]:
    latest_text = str(latest_message or "").strip()
    if not latest_text:
        return history_items

    for index in range(len(history_items) - 1, -1, -1):
        item = history_items[index]
        if item.get("role") == "customer" and item.get("content", "").strip() == latest_text:
            return history_items[:index] + history_items[index + 1 :]
    return history_items


def _format_created_at(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)
