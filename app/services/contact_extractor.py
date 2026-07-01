"""联系方式提取纯 service。"""

import re
from dataclasses import dataclass
from typing import Literal


ContactExtractStatus = Literal["matched", "not_matched", "empty_text", "parse_failed"]


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


_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_WECHAT_ACCOUNT_RE = r"([A-Za-z_][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_-])"
_WECHAT_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9_-]){_WECHAT_ACCOUNT_RE}")
_WECHAT_KEYWORD_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])(?:微信号|微信|微|wx|vx|加我微信|加我|➕我|\+我|加一下|联系方式|联系我)\s*[：:\s]*\s*{_WECHAT_ACCOUNT_RE}",
    re.IGNORECASE,
)
_SINGLE_V_WECHAT_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])v\s*(?:我)?\s*[：:\s]*\s*{_WECHAT_ACCOUNT_RE}",
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

    return ContactExtractResult(
        phone=phones[0] if phones else None,
        wechat=wechats[0] if wechats else None,
        phones=phones,
        wechats=wechats,
        all_contacts=matches,
        status=status,
        failure_reason=None if matches else "contact_not_found",
        raw_text=text,
    )


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
