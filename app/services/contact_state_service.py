"""联系方式状态公共只读服务（P0-B + P0.2-B）。

自动回复与会话预览共同调用，单一可信源。
不导入 ai_auto_reply_dry_run_service（无循环依赖）。
不执行 add/flush/commit。
customer_memory 由调用方传入。

P0.2-B 关键变更：
- 禁止 customer_memory.contact.has_contact 直接把 NONE 升级为 VALID。
- has_contact 只表示"发现过候选或存在历史字段"，不表示已验证有效。
- 历史/Lead 联系方式必须经严格验证（完整手机号或严格微信号）才形成 known_valid_contact。
- current_contact_state（当前消息状态）与 known_valid_contact（历史有效事实）分离。
- effective contact_state = VALID 当 current==VALID 或 known_valid；否则保持 current。
- 冲突（current=NONE + has_contact候选但无known_valid）设 has_contact_conflict，不升级 VALID。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from app.services.contact_completion_resolver import resolve_contact_with_completion
from app.services.contact_extractor import (
    analyze_contact_state,
    mask_contact_value,
    normalize_phone_digits,
)

_logger = logging.getLogger(__name__)

# contact_state → contact_action 旧映射（仅用于 Legacy Payload 兼容，不代表 P0-B Kernel 已启用 policy）
_CONTACT_ACTION_BY_STATE = {
    "VALID": "ACK_CONTACT_RECEIVED",
    "PARTIAL": "ASK_CONTACT_COMPLETION",
    "INVALID": "REQUEST_RECHECK",
    "AMBIGUOUS": "REQUEST_CLARIFY",
    "NONE": "NONE",
}

# 严格微信号验证：与 contact_extractor 的消息级提取正则一致，但不依赖上下文关键词。
# 微信号账号格式：字母/下划线开头，6-20 位，含字母数字下划线连字符。
# 必须排除噪声值、纯字母 token（需含数字或 _- 才像账号）、车型/价格等。
_STRICT_WECHAT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{5,19}$")
_WECHAT_NOISE_VALUES = {
    "douyin", "open_id", "server_message_id", "conversation_short_id",
    "http", "https", "miniapp",
}

# 证据来源类型
_EVIDENCE_SOURCE_TYPES = {
    "CURRENT_CUSTOMER_MESSAGE",
    "HISTORICAL_CUSTOMER_MESSAGE",
    "LEAD_PHONE",
    "LEAD_WECHAT",
    "LEAD_CONTACT_LIST",
}

# 验证器版本（用于观测与回溯）
_VALIDATOR_VERSION = "p0_2_b_strict_v1"


def _validate_strict_phone(value: Any) -> str | None:
    """严格手机号验证：规范化分隔符后必须完整匹配 11 位 1[3-9]xxxxxxxxx。

    不接受 7-10 位片段、价格数字、年份、任意非空字符串。
    仅返回规范化纯数字（用于脱敏），无效返回 None。
    """
    if value is None:
        return None
    digits = normalize_phone_digits(str(value))
    if not digits.isdigit():
        return None
    # 完整 11 位中国大陆手机号
    if len(digits) == 11 and digits[0] == "1" and digits[1] in "3456789":
        return digits
    return None


def _validate_strict_wechat(value: Any) -> str:
    """R1-5：微信号值受控验证契约，返回 VALID/AMBIGUOUS/INVALID 三态。

    与 contact_extractor 的消息级提取不同，此处用于 Lead 持久化字段校验，
    不依赖上下文关键词。项目既有正式微信号格式规则（contact_extractor
    _WECHAT_ACCOUNT_RE）：字母或下划线开头，6-20 位字母数字下划线连字符。

    契约：
    - INVALID：None/空/格式不符/噪声黑名单值（douyin/open_id 等）。
    - AMBIGUOUS：符合格式但无法确认为微信号（如纯字母值 "abcdef"——格式合法但
      缺数字或 _-，可能是微信号也可能是普通英文词/车型代号，不直接拒绝也不直接采信）。
    - VALID：符合格式且含数字或 _-（更像微信号账号形态，可形成 known_valid）。

    R1-5：不得为排除普通英文词而未经证据拒绝所有纯字母值——纯字母值归 AMBIGUOUS
    而非 INVALID，不确定 Token 不直接成为 known_valid_contact。
    """
    if value is None:
        return "INVALID"
    text = str(value).strip()
    if not text or not _STRICT_WECHAT_RE.match(text):
        return "INVALID"
    if text.lower() in _WECHAT_NOISE_VALUES:
        return "INVALID"
    # 含数字或 _- → 更像微信号账号形态，可采信
    if any(ch.isdigit() or ch in "_-" for ch in text):
        return "VALID"
    # 纯字母且符合格式 → 不确定，归 AMBIGUOUS（不直接拒绝，也不形成 known_valid）
    return "AMBIGUOUS"


def _validate_lead_contact_list(raw_value: Any) -> tuple[list[tuple[str, str]], int]:
    """R1-6：解析 all_extracted_contacts 的真实存储格式并逐个严格验证。

    标准写入格式（webhook upsert_lead_from_webhook）：
      {"phones": [...], "wechats": [...], "all": [{"type":"phone","value":"...","start":..,"end":..}]}
    历史遗留格式：裸字符串（非 JSON）。
    未知格式：无法解析的 JSON 结构外内容。

    返回 (verified_list, unknown_format_count)：
    - 已知标准格式 → 按 type 严格验证（phone 过严格手机号，wechat 过三态契约仅 VALID）；
    - 已知历史格式（裸字符串）→ 按明确兼容规则验证（仅完整手机号采用）；
    - 未知格式 → 不形成有效事实，只记 unknown_format_count（不记录原始字段值）。
    部分无效/歧义值不进入 verified_list。
    """
    if not raw_value:
        return [], 0
    unknown_format_count = 0
    try:
        parsed = json.loads(str(raw_value))
    except (TypeError, ValueError):
        # 历史/未知格式：保守按字符串重新分析，仅完整手机号才采用；记未知格式计数
        unknown_format_count += 1
        parsed = str(raw_value)

    verified: list[tuple[str, str]] = []

    def visit(value: Any, contact_type: str | None = None) -> None:
        nonlocal unknown_format_count
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
        if contact_type == "phone":
            phone = _validate_strict_phone(text)
            if phone and ("phone", phone) not in verified:
                verified.append(("phone", phone))
            return
        if contact_type == "wechat":
            # R1-5：仅 VALID 才形成 known_valid；AMBIGUOUS/INVALID 不进入
            if _validate_strict_wechat(text) == "VALID" and ("wechat", text) not in verified:
                verified.append(("wechat", text))
            return
        # 无类型：保守重新分析，仅能证明 VALID 的才采用；无法判定记未知格式
        phone = _validate_strict_phone(text)
        if phone:
            if ("phone", phone) not in verified:
                verified.append(("phone", phone))
            return
        if _validate_strict_wechat(text) == "VALID" and ("wechat", text) not in verified:
            verified.append(("wechat", text))
            return
        # 无类型且无法证明 VALID：记未知格式计数（不记录原始值）
        unknown_format_count += 1

    visit(parsed)
    return verified, unknown_format_count


def _derive_known_valid_from_memory(
    customer_memory: dict[str, Any] | None,
) -> tuple[bool, str | None, str | None, str | None]:
    """从 customer_memory 严格验证历史/Lead 联系方式，派生 known_valid_contact。

    返回 (known_valid, source_type, evidence_kind, evidence_ref)。
    has_contact=true 只表示发现过候选，必须经严格验证才形成 known_valid。
    不校验完整号码合法性时 known_valid=False，但保留 has_contact 候选信号供冲突检测。
    """
    memory = customer_memory or {}
    if not isinstance(memory, dict):
        return False, None, None, None
    mem_contact = memory.get("contact") if isinstance(memory.get("contact"), dict) else None
    if not mem_contact:
        return False, None, None, None

    # customer_memory.masked_values 是脱敏值，无法反推完整号码校验；
    # 但 customer_memory 不直接携带原始 Lead 字段，故此处只能基于 has_contact 标记候选，
    # 真正的 Lead 严格验证在调用方注入 lead 上下文时完成（见 build_request_contact_state 的 lead 参数）。
    # 当仅有 customer_memory（无 lead）时，known_valid 无法确认，保持 False，避免误升级。
    return False, None, None, None


def build_request_contact_state(
    db,
    *,
    latest_message: str,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    from_user_id: str,
    customer_memory: dict[str, Any] | None,
    lead: Any | None = None,
) -> dict[str, Any]:
    """9000 用共享状态机计算 ContactState，注入 9100 作为单一可信源。

    P0.2-B：禁止 has_contact 直接升级 VALID。
    - current_contact_state：来自当前客户消息 + 确定性客户消息序列（analyze_contact_state/补全）。
    - known_valid_contact：历史客户消息或 Lead 中严格验证通过的完整联系方式。
    - effective contact_state = VALID 当 current==VALID 或 known_valid；否则保持 current。
    - 冲突（current=NONE + has_contact候选但无known_valid）设 has_contact_conflict，不升级 VALID。

    lead 参数（P0.2-B 新增可选）：传入 DouyinLead 对象时，对其 extracted_phone/wechat/
    all_extracted_contacts 做严格验证，形成 known_valid_contact。不传 lead 时
    known_valid 无法确认（customer_memory.masked_values 是脱敏值无法反推校验）。

    综合跨 AI 回复补全（事件溯源），仅输出脱敏值。
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
        current_status = state.status

        # P0.2-B：has_contact 只表示候选，不直接升级 VALID。
        memory = customer_memory or {}
        mem_contact = memory.get("contact") if isinstance(memory, dict) else None
        has_contact_candidate = bool(
            isinstance(mem_contact, dict) and mem_contact.get("has_contact")
        )

        # P0.2-B：从 Lead 严格验证派生 known_valid_contact。
        known_valid, kv_source_type, kv_evidence_kind, kv_evidence_ref, lead_unknown_format_count = _derive_known_valid_from_lead(lead)

        # effective 状态合并：
        # current==VALID → VALID（当前消息已含完整联系方式）
        # current!=VALID 且 known_valid → VALID（历史已有有效联系方式，避免重复索要）
        # 否则 → current（不因 has_contact 候选升级）
        if current_status == "VALID":
            effective_status = "VALID"
            effective_source_type = "CURRENT_CUSTOMER_MESSAGE"
            effective_evidence_kind = "FULL_PHONE" if state.type == "mobile" else "VERIFIED_WECHAT"
        elif known_valid:
            effective_status = "VALID"
            effective_source_type = kv_source_type
            effective_evidence_kind = kv_evidence_kind
        else:
            effective_status = current_status
            effective_source_type = None
            effective_evidence_kind = None

        # 冲突检测：current=NONE/PARTIAL/INVALID/AMBIGUOUS 但 has_contact候选且无 known_valid
        has_contact_conflict = (
            has_contact_candidate
            and not known_valid
            and current_status != "VALID"
        )

        # 脱敏值：优先当前 state.masked_value；known_valid 升级时用 Lead 严格验证值的脱敏
        masked = state.masked_value
        if effective_status == "VALID" and not masked and known_valid and kv_evidence_ref:
            # kv_evidence_ref 在 _derive_known_valid_from_lead 中存放脱敏值（非完整号码）
            masked = kv_evidence_ref

        result_contact_state = {
            "status": effective_status,
            "type": state.type,
            "masked_value": masked,
            "fragment_count": state.fragment_count,
            "reason_code": state.reason_code,
            # P0.2-B：分离 current 与 known_valid，供 9100 Prompt 区分"当前收到"与"历史已有"
            "current_contact_state": current_status,
            "known_valid_contact": known_valid,
            "known_valid_contact_source": kv_source_type,
            "known_valid_contact_evidence_kind": kv_evidence_kind,
            "has_contact_candidate": has_contact_candidate,
            "has_contact_conflict": has_contact_conflict,
            "validator_version": _VALIDATOR_VERSION,
            "lead_unknown_format_count": lead_unknown_format_count,
        }
        return {
            "contact_state": result_contact_state,
            "contact_action": _CONTACT_ACTION_BY_STATE.get(effective_status, "NONE"),
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


def _derive_known_valid_from_lead(
    lead: Any | None,
) -> tuple[bool, str | None, str | None, str | None, int]:
    """从 DouyinLead 严格验证 extracted_phone/wechat/all_extracted_contacts。

    返回 (known_valid, source_type, evidence_kind, evidence_ref, unknown_format_count)。
    evidence_ref 为脱敏值（非完整号码），用于注入 9100 上下文。
    unknown_format_count 为 all_extracted_contacts 中无法识别格式的条目数（R1-6 观测，不记录原始值）。
    部分/无效/歧义值不形成 known_valid。
    """
    if lead is None:
        return False, None, None, None, 0

    # 1. extracted_phone：严格手机号验证
    phone = _validate_strict_phone(getattr(lead, "extracted_phone", None))
    if phone:
        return True, "LEAD_PHONE", "FULL_PHONE", mask_contact_value("phone", phone), 0

    # 2. extracted_wechat：严格微信号验证（R1-5 三态契约，仅 VALID 形成 known_valid）
    wechat_raw = getattr(lead, "extracted_wechat", None)
    if _validate_strict_wechat(wechat_raw) == "VALID":
        wechat = str(wechat_raw).strip()
        return True, "LEAD_WECHAT", "VERIFIED_WECHAT", mask_contact_value("wechat", wechat), 0

    # 3. all_extracted_contacts：逐个解析严格验证（R1-6 返回 verified + unknown_format_count）
    verified, unknown_count = _validate_lead_contact_list(getattr(lead, "all_extracted_contacts", None))
    if verified:
        first_type, first_value = verified[0]
        kind = "FULL_PHONE" if first_type == "phone" else "VERIFIED_WECHAT"
        return True, "LEAD_CONTACT_LIST", kind, mask_contact_value(first_type, first_value), unknown_count

    return False, None, None, None, unknown_count


def _short(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"
