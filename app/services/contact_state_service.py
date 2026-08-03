"""联系方式状态公共只读服务（P0-B）。

自动回复与会话预览共同调用，单一可信源。
不导入 ai_auto_reply_dry_run_service（无循环依赖）。
不执行 add/flush/commit。
customer_memory 由调用方传入。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.services.contact_completion_resolver import resolve_contact_with_completion
from app.services.contact_extractor import analyze_contact_state

_logger = logging.getLogger(__name__)

# contact_state → contact_action 旧映射（仅用于 Legacy Payload 兼容，不代表 P0-B Kernel 已启用 policy）
_CONTACT_ACTION_BY_STATE = {
    "VALID": "ACK_CONTACT_RECEIVED",
    "PARTIAL": "ASK_CONTACT_COMPLETION",
    "INVALID": "REQUEST_RECHECK",
    "AMBIGUOUS": "REQUEST_CLARIFY",
    "NONE": "NONE",
}


def build_request_contact_state(
    db,
    *,
    latest_message: str,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    from_user_id: str,
    customer_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    """9000 用共享状态机计算 ContactState，注入 9100 作为单一可信源。

    综合跨 AI 回复补全（事件溯源）与客户记忆已有的联系方式，仅输出脱敏值。
    异常时不伪装为可信 request：返回空 dict 省略全部 contact 字段，
    由 9100 用共享状态机执行 local_fallback；异常不阻断回复主链路。
    不导入 ai_auto_reply_dry_run_service；不执行 add/flush/commit。
    """
    try:
        if not merchant_id or not account_open_id or not conversation_short_id or not from_user_id:
            state = analyze_contact_state(latest_message)
        else:
            _combined, state = resolve_contact_with_completion(
                db,
                current_text=latest_message,
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                conversation_short_id=conversation_short_id,
                from_user_id=from_user_id,
            )
        status = state.status
        # 客户记忆已有有效联系方式 → 视为 VALID（单一可信源，与 9100 本地推断一致）
        if status == "NONE":
            memory = customer_memory or {}
            mem_contact = memory.get("contact") if isinstance(memory, dict) else None
            if isinstance(mem_contact, dict) and mem_contact.get("has_contact"):
                status = "VALID"
        masked = state.masked_value
        if status == "VALID" and not masked and (customer_memory or {}).get("contact", {}).get("masked_values"):
            masked = (customer_memory or {}).get("contact", {}).get("masked_values", [None])[0]
        return {
            "contact_state": {
                "status": status,
                "type": state.type,
                "masked_value": masked,
                "fragment_count": state.fragment_count,
                "reason_code": state.reason_code,
            },
            "contact_action": _CONTACT_ACTION_BY_STATE.get(status, "NONE"),
            "contact_state_source": "request",
        }
    except Exception:
        # 异常降级：不伪装为可信 request，省略全部 contact 字段，由 9100 local_fallback
        import sys as _sys
        exc_type = _sys.exc_info()[0] or RuntimeError
        _logger.warning(
            "contact_state_failed stage=build_request_contact_state fallback=local "
            "merchant_id=%s account_open_id=%s conversation_id=%s error_type=%s",
            merchant_id,
            _short(account_open_id),
            conversation_short_id,
            exc_type.__name__,
        )
        return {}


def _short(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"
