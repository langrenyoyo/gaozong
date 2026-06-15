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
_WECHAT_ACCOUNT_RE = r"([A-Za-z][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_-])"
_WECHAT_KEYWORD_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?:微信号|微信|wx|vx|加我微信|加我)\s*[：: ]+\s*{_WECHAT_ACCOUNT_RE}",
    re.IGNORECASE,
)
_SINGLE_V_WECHAT_RE = re.compile(
    rf"(?<![A-Za-z0-9_])v[：: ]+\s*{_WECHAT_ACCOUNT_RE}",
    re.IGNORECASE,
)


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
            _append_unique(
                matches,
                seen_values,
                contact_type="wechat",
                value=match.group(1),
                start=match.start(1),
                end=match.end(1),
            )

    matches.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    return matches


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
