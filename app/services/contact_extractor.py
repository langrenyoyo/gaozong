"""联系方式提取纯 service。"""

import re
from dataclasses import dataclass, field
from typing import Literal


ContactExtractStatus = Literal["matched", "not_matched", "empty_text", "parse_failed"]

# 联系方式确定性状态机五态：9000 判定，9100 消费
ContactStatus = Literal["NONE", "PARTIAL", "VALID", "INVALID", "AMBIGUOUS"]


@dataclass(frozen=True)
class ContactState:
    """联系方式确定性状态。不暴露完整号码，仅保留脱敏值。"""

    status: ContactStatus
    type: str | None = None  # "mobile" | "wechat" | None
    normalized_value: str | None = None
    masked_value: str | None = None
    source_message_ids: list[int] = field(default_factory=list)
    fragment_count: int = 1
    reason_code: str | None = None


@dataclass(frozen=True)
class ContactExtractResult:
    phone: str | None
    wechat: str | None
    phones: list[str]
    wechats: list[str]
    all_contacts: list[dict[str, str | int]]
    status: ContactExtractStatus
    failure_reason: str | None
    raw_text: str | None
    # 疑似不完整手机号（7-10 位纯数字），供 LLM 追问补全
    partial_phone: str | None = None


_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_WECHAT_ACCOUNT_RE = r"([A-Za-z_][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_-])"
_WECHAT_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9_-]){_WECHAT_ACCOUNT_RE}")
_WECHAT_KEYWORD_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])(?:微信号|微信|微|wx|vx|加我微信|加我|➕我|\+我|加一下|联系方式|联系我)\s*[：:\s]*\s*{_WECHAT_ACCOUNT_RE}",
    re.IGNORECASE,
)
_SINGLE_V_WECHAT_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])v(?:我\s*|\s+我?\s*|[：:]\s*){_WECHAT_ACCOUNT_RE}",
    re.IGNORECASE,
)
_WEAK_WECHAT_CONTEXT_KEYWORDS = (
    "买车",
    "买台车",
    "买辆车",
    "看车",
    "车",
    "联系",
    "联系方式",
    "加我",
    "➕我",
    "+我",
)
_WECHAT_NOISE_VALUES = {
    "douyin",
    "open_id",
    "server_message_id",
    "conversation_short_id",
    "http",
    "https",
    "miniapp",
}


def extract_contacts_from_text(text: str | None) -> ContactExtractResult:
    """从私信纯文本中提取手机号和微信号。"""
    if text is None or text.strip() == "":
        return ContactExtractResult(
            phone=None,
            wechat=None,
            phones=[],
            wechats=[],
            all_contacts=[],
            status="empty_text",
            failure_reason="empty_text",
            raw_text=text,
        )

    try:
        matches = _collect_matches(text)
    except Exception:
        return ContactExtractResult(
            phone=None,
            wechat=None,
            phones=[],
            wechats=[],
            all_contacts=[],
            status="parse_failed",
            failure_reason="parse_failed",
            raw_text=text,
        )

    phones = [item["value"] for item in matches if item["type"] == "phone"]
    wechats = [item["value"] for item in matches if item["type"] == "wechat"]
    status: ContactExtractStatus = "matched" if matches else "not_matched"

    # 检测疑似不完整手机号：7-10 位纯数字（非完整 11 位 1[3-9]xxxxxxxxx）
    partial_phone = None
    if not phones:
        partial_phone = _detect_partial_phone(text)

    return ContactExtractResult(
        phone=phones[0] if phones else None,
        wechat=wechats[0] if wechats else None,
        phones=phones,
        wechats=wechats,
        all_contacts=matches,
        status=status,
        failure_reason=None if matches else "contact_not_found",
        raw_text=text,
        partial_phone=partial_phone,
    )


def mask_contact_value(contact_type: str, value: str) -> str:
    """生成可交给大模型的联系方式脱敏值。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if contact_type == "phone" and len(text) >= 7:
        return f"{text[:3]}****{text[-4:]}"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def mask_contacts_in_text(text: str | None) -> str:
    """脱敏文本中的手机号和微信号，保留其余对话语义。"""
    value = str(text or "")
    extracted = extract_contacts_from_text(value)
    if extracted.status == "parse_failed":
        raise ValueError("contact_parse_failed")
    replacements = sorted(
        {
            (str(item["type"]), str(item["value"]))
            for item in extracted.all_contacts
            if item.get("type") and item.get("value")
        },
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for contact_type, raw_value in replacements:
        value = value.replace(raw_value, mask_contact_value(contact_type, raw_value))
    return value


def _collect_matches(text: str) -> list[dict[str, str | int]]:
    matches: list[dict[str, str | int]] = []
    seen_values: set[tuple[str, str]] = set()

    for match in _PHONE_RE.finditer(text):
        _append_unique(
            matches,
            seen_values,
            contact_type="phone",
            value=match.group(1),
            start=match.start(1),
            end=match.end(1),
        )

    for regex in (_WECHAT_KEYWORD_RE, _SINGLE_V_WECHAT_RE):
        for match in regex.finditer(text):
            _append_wechat_candidate(
                matches,
                seen_values,
                value=match.group(1),
                start=match.start(1),
                end=match.end(1),
            )

    if _has_weak_wechat_context(text):
        for match in _WECHAT_TOKEN_RE.finditer(text):
            value = match.group(1)
            # 弱语义场景只收“更像账号”的 token，避免把车型代号/普通英文误作微信号。
            if not any(char.isdigit() or char in "_-" for char in value):
                continue
            _append_wechat_candidate(
                matches,
                seen_values,
                value=value,
                start=match.start(1),
                end=match.end(1),
            )

    matches.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    return matches


def _has_weak_wechat_context(text: str) -> bool:
    return any(keyword in text for keyword in _WEAK_WECHAT_CONTEXT_KEYWORDS)


def _append_wechat_candidate(
    matches: list[dict[str, str | int]],
    seen_values: set[tuple[str, str]],
    *,
    value: str,
    start: int,
    end: int,
) -> None:
    if value.lower() in _WECHAT_NOISE_VALUES:
        return
    _append_unique(
        matches,
        seen_values,
        contact_type="wechat",
        value=value,
        start=start,
        end=end,
    )


def _append_unique(
    matches: list[dict[str, str | int]],
    seen_values: set[tuple[str, str]],
    *,
    contact_type: str,
    value: str,
    start: int,
    end: int,
) -> None:
    key = (contact_type, value)
    if key in seen_values:
        return
    seen_values.add(key)
    matches.append({
        "type": contact_type,
        "value": value,
        "start": start,
        "end": end,
    })


# 疑似不完整手机号：7-10 位纯数字（非完整 11 位 1[3-9]xxxxxxxxx）
_PARTIAL_PHONE_RE = re.compile(r"(?<!\d)(\d{7,10})(?!\d)")


def _detect_partial_phone(text: str) -> str | None:
    """检测疑似不完整手机号（7-10 位纯数字，非完整 11 位）。

    用于 LLM 追问补全：客户发了 1770206（7 位）→ 检测到 partial → LLM 引导补全。
    """
    for match in _PARTIAL_PHONE_RE.finditer(text):
        digits = match.group(1)
        # 排除完整 11 位手机号（已在主提取器处理）
        if len(digits) == 11 and digits[0] == "1" and digits[1] in "3456789":
            continue
        # 排除明显非手机号的数字（如价格"100000"、年份"2024"）
        if len(digits) <= 6:
            continue
        return digits
    return None


# ---- 联系方式确定性状态机（9000 判定，9100 消费） ----
# 手机号常见分隔符：空格、短横、破折号、中划线、点、括号
_PHONE_SEPARATORS = " -—–·.()（）"
# 完整 11 位中国大陆手机号
_FULL_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
# 宽松匹配：允许号码中间夹分隔符，可选区号前缀（+86 / 0086）
_PHONE_LOOSE_RE = re.compile(
    r"(?<!\d)(?:(?:\+|00)?86[\s \-—–·.()（）]*)?(1[3-9][\d \-—–·.()（）]{8,16}\d)(?!\d)"
)
# 歧义片段：数字 + 短非分隔符段（字母/中文）+ 数字，疑似被打断的号码
_AMBIGUOUS_FRAGMENT_RE = re.compile(r"(?<!\d)(\d{3,}[^\d\s\-—–·.()（）]{1,3}\d{3,})")


def normalize_phone_digits(text: str | None) -> str:
    """剥离手机号常见分隔符，返回纯数字串（不去除其他文字）。

    仅用于号码判定；区号前缀（+86/0086）在宽松匹配里作为可选项处理。
    """
    s = str(text or "")
    for ch in _PHONE_SEPARATORS:
        s = s.replace(ch, "")
    return s


def _extract_loose_phone(text: str) -> str | None:
    """从含分隔符/区号前缀的文本中提取规范化后的完整手机号（纯 11 位数字）。"""
    s = str(text or "")
    if not s.strip():
        return None
    for match in _PHONE_LOOSE_RE.finditer(s):
        digits = normalize_phone_digits(match.group(1))
        if _FULL_PHONE_RE.match(digits):
            return digits
    return None


def _mask_partial_phone(digits: str) -> str:
    """对不完整/无效号码片段做脱敏。"""
    if len(digits) >= 7:
        return f"{digits[:3]}***{digits[-2:]}"
    return "***"


def analyze_contact_state(
    text: str | None,
    *,
    fragment_count: int = 1,
    source_message_ids: list[int] | None = None,
) -> ContactState:
    """对单段文本做确定性联系方式状态判定。

    判定顺序：完整手机号（含分隔符/区号）→ 完整微信号 → 整段疑似号码片段 →
    夹在文字中的不完整号码 → 歧义片段 → 无联系方式。
    不把号码是否合法交给 LLM；返回值仅含脱敏号码。
    """
    msg_ids = list(source_message_ids or [])
    raw = str(text or "")

    # 1. 完整手机号（兼容 138-0013-8000 / +86 138 0013 8000）
    loose_phone = _extract_loose_phone(raw)
    if loose_phone:
        return ContactState(
            status="VALID",
            type="mobile",
            normalized_value=loose_phone,
            masked_value=mask_contact_value("phone", loose_phone),
            source_message_ids=msg_ids,
            fragment_count=fragment_count,
            reason_code="valid_mobile",
        )

    extracted = extract_contacts_from_text(raw)
    # 2. 完整微信号
    if extracted.wechat:
        return ContactState(
            status="VALID",
            type="wechat",
            normalized_value=extracted.wechat,
            masked_value=mask_contact_value("wechat", extracted.wechat),
            source_message_ids=msg_ids,
            fragment_count=fragment_count,
            reason_code="valid_wechat",
        )

    # 3. 整段疑似号码（仅分隔符+数字）→ 按位数判 PARTIAL/INVALID
    digits = normalize_phone_digits(raw)
    if digits.isdigit() and len(digits) >= 7:
        if len(digits) == 11:
            return ContactState(
                "INVALID", "mobile", None, _mask_partial_phone(digits),
                msg_ids, fragment_count, "invalid_mobile_prefix",
            )
        if len(digits) > 11:
            return ContactState(
                "INVALID", "mobile", None, _mask_partial_phone(digits),
                msg_ids, fragment_count, "mobile_too_long",
            )
        # 7-10 位
        return ContactState(
            "PARTIAL", "mobile", None, _mask_partial_phone(digits),
            msg_ids, fragment_count, "mobile_too_short",
        )

    # 4. 夹在文字中的 7-10 位不完整号码片段
    partial = _detect_partial_phone(raw)
    if partial:
        return ContactState(
            "PARTIAL", "mobile", None, _mask_partial_phone(partial),
            msg_ids, fragment_count, "mobile_too_short",
        )

    # 5. 歧义片段：数字被单个非分隔符字符打断，疑似号码但不完整
    if _AMBIGUOUS_FRAGMENT_RE.search(raw):
        return ContactState(
            "AMBIGUOUS", "mobile", None, None,
            msg_ids, fragment_count, "ambiguous_fragment",
        )

    # 6. 无联系方式
    return ContactState("NONE", None, None, None, msg_ids, fragment_count, "no_contact")
