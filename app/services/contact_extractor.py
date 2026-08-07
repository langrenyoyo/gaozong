"""联系方式提取纯 service。"""

import re
import unicodedata
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
    all_contacts: list[dict[str, str | int | float]]
    status: ContactExtractStatus
    failure_reason: str | None
    raw_text: str | None
    # 疑似不完整手机号（7-10 位纯数字），供 LLM 追问补全
    partial_phone: str | None = None
    # 任务 2.3 置信度（规则文档 4.1）：1.0 标准+白名单 / 0.8 清洗S0-S4 / 0.7 清洗S5 /
    # 0.95 微信关键词 / 0.85 微信全文本 / 0.4 非白名单降级 / 0.0 无匹配。与五态并存，辅助可信度。
    confidence: float = 0.0


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


def extract_contacts_from_text(text: str | None, *, context_boost: bool = False) -> ContactExtractResult:
    """从私信纯文本中提取手机号和微信号。

    context_boost（任务 2.4/2.5）：LEAD_REQUEST 上下文时干扰词降权幅度小（-0.05 vs -0.2），
    且 confidence +0.05 封顶 1.0。默认 False 不影响现有行为。
    """
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

    # 兜底：标准匹配未命中手机号时，走独立式清洗管道（只兜底手机号，不做微信号混淆）。
    # ponytail 已知局限：兜底号码在原文中常是散落形态（如 138a1234b5678），
    # 后续 mask_contacts_in_text 用 value.replace 脱敏可能替换不到，原文片段保留；
    # 这是既有脱敏策略局限，本任务只增强提取，不改脱敏逻辑。升级路径：脱敏改为基于 start/end 区间。
    if not phones:
        pipeline_result = _extract_phone_with_pipeline(text)
        if pipeline_result:
            pipeline_phone, pipeline_confidence = pipeline_result
            matches.append({"type": "phone", "value": pipeline_phone, "start": -1, "end": -1, "confidence": pipeline_confidence})
            phones = [pipeline_phone]

    # 号段白名单：1[3-9]xxxxxxxxx 格式但号段不在白名单的，降级为 partial_phone（供 LLM 追问核实）。
    # 规则文档 1.2：非合法号段仍识别为线索但可信度低；本实现不进 phones，降级 partial_phone。
    if phones:
        invalid_phones = [p for p in phones if not _is_operator_phone(p)]
        if invalid_phones:
            # 若存在白名单号码，只剔除非白名单的；全不合法时 phones 清空触发 partial_phone
            valid_phones = [p for p in phones if _is_operator_phone(p)]
            if valid_phones:
                valid_set = set(valid_phones)
                matches = [m for m in matches if not (m["type"] == "phone" and m["value"] not in valid_set)]
                phones = valid_phones
                invalid_phones = []  # 有有效号，无效号静默丢弃（不覆盖 partial_phone）
            # 全部非白名单：phones 清空，降级第一个为 partial_phone
            if not valid_phones:
                phones = []
                matches = [m for m in matches if m["type"] != "phone"]
                # 取第一个非白名单 11 位号作为 partial_phone，供 LLM 追问
                partial_phone_fallback = invalid_phones[0] if invalid_phones else None
            else:
                partial_phone_fallback = None
        else:
            partial_phone_fallback = None
    else:
        partial_phone_fallback = None

    status: ContactExtractStatus = "matched" if matches else "not_matched"

    # 检测疑似不完整手机号：7-10 位纯数字（非完整 11 位 1[3-9]xxxxxxxxx）
    # 优先用号段白名单降级值，其次检测原文 7-10 位片段
    partial_phone = partial_phone_fallback
    if not phones and partial_phone is None:
        partial_phone = _detect_partial_phone(text)

    # 任务 2.3 置信度（规则文档 4.1）：取所有匹配项的最高 confidence。
    # 非白名单降级为 partial_phone 时 confidence=0.4（规则文档 4.1：待确认线索）；
    # 无匹配 0.0。
    if matches:
        best_confidence = max(float(m.get("confidence", 0.0) or 0.0) for m in matches)
    else:
        best_confidence = 0.0
    if partial_phone_fallback and not phones:
        # 全部非白名单降级：confidence=0.4（待确认线索）
        best_confidence = 0.4

    # 任务 2.5 干扰词上下文降权（规则文档 8.1）：phone 紧邻干扰词（公里/万/元/年等）降 confidence。
    # 有 LEAD_REQUEST 上下文（context_boost=True）降 0.05（客户回复留资引导不太可能发里程/价格）；
    # 无上下文降 0.2（严格过滤）。配套 2.4 context_boost + 2.3 confidence。
    if phones and best_confidence > 0:
        phone_match = next((m for m in matches if m["type"] == "phone" and m["value"] == phones[0]), None)
        if phone_match and _has_nearby_interference(text, str(phones[0]), int(phone_match.get("start", -1)), int(phone_match.get("end", -1))):
            penalty = 0.05 if context_boost else 0.2
            best_confidence = max(0.0, best_confidence - penalty)

    # 任务 2.4/2.5：context_boost 置信度加成（规则文档 0.3 第②项），+0.05 封顶 1.0
    if context_boost and best_confidence > 0:
        best_confidence = min(1.0, best_confidence + 0.05)

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
        confidence=best_confidence,
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


def _collect_matches(text: str) -> list[dict[str, str | int | float]]:
    matches: list[dict[str, str | int | float]] = []
    seen_values: set[tuple[str, str]] = set()

    for match in _PHONE_RE.finditer(text):
        _append_unique(
            matches,
            seen_values,
            contact_type="phone",
            value=match.group(1),
            start=match.start(1),
            end=match.end(1),
            confidence=1.0,
        )

    for regex in (_WECHAT_KEYWORD_RE, _SINGLE_V_WECHAT_RE):
        for match in regex.finditer(text):
            _append_wechat_candidate(
                matches,
                seen_values,
                value=match.group(1),
                start=match.start(1),
                end=match.end(1),
                confidence=0.95,
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
                confidence=0.85,
            )

    matches.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    return matches


# ---- 清洗管道：独立式手机号兜底提取（任务 2.1） ----
# 独立式策略：每步从原文独立清洗，不基于上一步结果，避免错误累积。
# 只兜底手机号，不做微信号混淆；不做置信度（2.3）、不做号段白名单（2.2）。

# 中文数字（含大写与电话读号谐音）→ 阿拉伯数字映射（规则文档 1.3 表格 + 伪代码）
CN_DIGIT_MAP = {
    "零": "0", "洞": "0",
    "一": "1", "壹": "1", "幺": "1", "妖": "1",
    "二": "2", "贰": "2", "两": "2", "俩": "2",
    "三": "3", "叁": "3", "仨": "3",
    "四": "4", "肆": "4",
    "五": "5", "伍": "5",
    "六": "6", "陆": "6",
    "七": "7", "柒": "7", "拐": "7",
    "八": "8", "捌": "8", "吧": "8",
    "九": "9", "玖": "9", "勾": "9",
}


def _fullwidth_to_halfwidth(text: str) -> str:
    """S1：全角数字→半角，用 NFKC 归一化（同时转换全角字母/符号，对号码提取无害）。"""
    return unicodedata.normalize("NFKC", str(text or ""))


def _strip_letters(text: str) -> str:
    """S2：剔除半角字母 [a-zA-Z]，保留其余字符。"""
    return re.sub(r"[A-Za-z]", "", str(text or ""))


def _strip_chinese(text: str) -> str:
    """S3：剔除 CJK 统一汉字 [\\u4e00-\\u9fff]。"""
    return re.sub(r"[一-鿿]", "", str(text or ""))


def _strip_all_non_digits(text: str) -> str:
    """S4：剔除所有非数字字符（含 emoji、标点、空白），只保留 Unicode 数字。"""
    # re.UNICODE 使 \d 覆盖全角数字等 Unicode 数字类别；emoji 等非数字被剔除。
    return re.sub(r"[^\d]", "", str(text or ""), flags=re.UNICODE)


def _cn_digit_to_arabic(text: str) -> str:
    """中文数字（含大写与电话读号谐音）映射为阿拉伯数字，非数字字符原样保留。"""
    s = str(text or "")
    return "".join(CN_DIGIT_MAP.get(ch, ch) for ch in s)


def _cn_digit_then_strip(text: str) -> str:
    """S5：先中文数字映射，再全剔非数字。"""
    return _strip_all_non_digits(_cn_digit_to_arabic(text))


# S0：剥离国际区号前缀（+86 / 0086 / 86 + 可选分隔符），独立式从原文清洗。
# 规则文档 1.1 表格第 2 行要求支持区号前缀；S4 全剔后 86 前缀残留会触发 _PHONE_RE 的 (?<!\d) 断言失败。
# 前瞻 (?=[\s\-]*1[3-9]) 确保只剥后跟合法手机号开头的区号，避免误伤号码内 86 子串。
_COUNTRY_CODE_RE = re.compile(r"(?:\+|00)?86(?=[\s\-]*1[3-9])")


def _strip_country_code(text: str) -> str:
    """S0：剥离 +86/0086/86 区号前缀（允许区号前有中文/字母等非数字字符）。"""
    return _COUNTRY_CODE_RE.sub("", str(text or ""), count=1)


# 独立式清洗步骤序列：每步从原文独立清洗，互不依赖
_PHONE_CLEAN_STEPS = (
    _strip_country_code,      # S0 剥离区号前缀
    _fullwidth_to_halfwidth,  # S1 全角→半角
    _strip_letters,            # S2 剔字母
    _strip_chinese,            # S3 剔中文
    _strip_all_non_digits,     # S4 全剔非数字
    _cn_digit_then_strip,      # S5 中文数字映射+全剔
)


def _extract_phone_with_pipeline(text: str) -> tuple[str, float] | None:
    """清洗管道兜底提取手机号，返回 (phone, confidence)。

    独立式策略：每步从原文独立清洗，清洗结果用 _PHONE_RE 重试，命中即返回 11 位号码。
    标准格式已在 _collect_matches 命中，进此函数说明标准匹配失败。
    全不命中返回 None。只兜底手机号，不做微信号混淆。
    平台脱敏（138****8002）清洗后不足 11 位，不会被误判。

    confidence（规则文档 4.1）：标准直接匹配 1.0 / S0-S4 清洗 0.8 / S5 中文数字映射 0.7。
    S0-S4 是符号/字母/中文剔除，可信度较高；S5 中文数字映射有谐音歧义风险，可信度略低。
    """
    s = str(text or "")
    # 先用 _PHONE_RE 直接匹配（标准格式不走清洗，confidence=1.0）
    m = _PHONE_RE.search(s)
    if m:
        return (m.group(1), 1.0)
    # 独立式依次清洗：每步从原文独立清洗，命中即返回
    for index, cleaner in enumerate(_PHONE_CLEAN_STEPS):
        cleaned = cleaner(s)
        m = _PHONE_RE.search(cleaned)
        if m:
            # S5（index=5）是中文数字映射+全剔，confidence=0.7；S0-S4 confidence=0.8
            confidence = 0.7 if index == 5 else 0.8
            return (m.group(1), confidence)
    return None


# ---- 运营商号段白名单（任务 2.2） ----
# 防止把普通数字串误判为手机号：1[3-9]xxxxxxxxx 格式但号段不在白名单 → 降级为 partial_phone。
# 号段表来源：docs/ai/01_product_prd/线索识别AI技能规则.md 1.2 节 + 伪代码 VALID_PREFIXES。
# ponytail 已知局限：号段表随工信部发放更新，新号段会漏判为 partial_phone；升级路径：定期同步工信部号段表。
_OPERATOR_PREFIXES = frozenset({
    # 中国移动
    "134", "135", "136", "137", "138", "139",
    "147", "148", "150", "151", "152", "157", "158", "159",
    "165", "172", "178", "182", "183", "184", "187", "188",
    "195", "197", "198",
    # 中国联通
    "130", "131", "132", "145", "146", "155", "156",
    "166", "167", "171", "175", "176", "185", "186", "196",
    # 中国电信
    "133", "149", "153", "173", "174", "177", "180", "181", "189",
    "190", "191", "193", "199",
    # 中国广电
    "192",
})


def _is_operator_phone(phone: str) -> bool:
    """判断 11 位号码是否属于三大运营商有效号段。

    phone 必须是 11 位纯数字且以 1[3-9] 开头。取前 3 位查白名单。
    非白名单号段返回 False，调用方据此降级为 partial_phone。
    """
    if len(phone) != 11 or not phone.isdigit():
        return False
    if phone[0] != "1" or phone[1] not in "3456789":
        return False
    return phone[:3] in _OPERATOR_PREFIXES


def _has_weak_wechat_context(text: str) -> bool:
    return any(keyword in text for keyword in _WEAK_WECHAT_CONTEXT_KEYWORDS)


def _append_wechat_candidate(
    matches: list[dict[str, str | int | float]],
    seen_values: set[tuple[str, str]],
    *,
    value: str,
    start: int,
    end: int,
    confidence: float = 0.85,
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
        confidence=confidence,
    )


def _append_unique(
    matches: list[dict[str, str | int | float]],
    seen_values: set[tuple[str, str]],
    *,
    contact_type: str,
    value: str,
    start: int,
    end: int,
    confidence: float = 1.0,
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
        "confidence": confidence,
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


# ---- LEAD_REQUEST 上下文检测（任务 2.4） ----
# 规则文档 0.3：AI 出站消息含留资引导关键词 → 标记 LEAD_REQUEST，
# 客户紧随其后的回复消息在联系方式识别时降权干扰词 + 拼接窗口扩展。
# 词表来源：规则文档 0.3 + 9100 PHONE_LEAD_CAPTURE_KEYWORDS 语义对齐（本地定义避免跨 9100 import）。
_LEAD_REQUEST_KEYWORDS = (
    "联系方式", "手机号", "电话", "微信号", "微信", "留个", "留一下", "留资",
    "发我", "发给您", "加我", "加您", "怎么联系", "方便", "号码",
)


def is_lead_request_message(text: str | None) -> bool:
    """检测文本是否含留资引导关键词（AI 出站消息标记 LEAD_REQUEST 用）。

    纯函数，不访问 DB。命中任一关键词即返回 True。
    """
    if not text:
        return False
    s = str(text)
    return any(keyword in s for keyword in _LEAD_REQUEST_KEYWORDS)


# ---- 干扰词上下文降权（任务 2.5，规则文档 8.1） ----
# 二手车场景：数字紧邻里程/价格/年份/排量等干扰词时，大概率不是手机号。
# 规则文档 8.1 关键干扰词：公里/km/迈/万/元/块/价格/年/款/排量。
# ponytail 已知局限：窗口固定 6 字符（经验值），极少数长句中干扰词可能落在窗口外；
# 升级路径：按句号/逗号切分后只看同句干扰词。
_INTERFERENCE_KEYWORDS = ("公里", "km", "迈", "万", "元", "块", "价格", "年", "款", "排量")
_INTERFERENCE_WINDOW = 6


def _has_nearby_interference(text: str, phone_value: str, start: int, end: int) -> bool:
    """检测 phone 在原文中是否紧邻干扰词（前后 _INTERFERENCE_WINDOW 字符内有干扰词）。

    标准匹配用 start/end 精确定位；管道兜底（start=-1）用 text.find 兜底定位。
    返回 True 表示数字紧邻干扰词，应降 confidence。
    """
    s = str(text or "")
    if not phone_value:
        return False
    # 定位 phone 在原文中的位置
    pos = start if start >= 0 else s.find(phone_value)
    if pos < 0:
        return False
    phone_len = (end - start) if (start >= 0 and end > start) else len(phone_value)
    # 前后 window 字符窗口
    before = s[max(0, pos - _INTERFERENCE_WINDOW):pos]
    after = s[pos + phone_len:pos + phone_len + _INTERFERENCE_WINDOW]
    window_text = before + after
    lower_window = window_text.lower()
    for keyword in _INTERFERENCE_KEYWORDS:
        if keyword == "km":
            if "km" in lower_window:
                return True
        elif keyword in window_text:
            return True
    return False


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
    # step 1 未命中（含字母/中文等 _PHONE_LOOSE_RE 无法处理的形态）→ 走清洗管道兜底，与 extract 对齐
    if not loose_phone:
        pipeline_result = _extract_phone_with_pipeline(raw)
        if pipeline_result:
            loose_phone = pipeline_result[0]
    if loose_phone:
        # 号段白名单校验：1[3-9]xxxxxxxxx 格式但号段不在白名单 → 降级 PARTIAL（与 extract_contacts_from_text 一致）
        if not _is_operator_phone(loose_phone):
            return ContactState(
                "PARTIAL", "mobile", None, _mask_partial_phone(loose_phone),
                msg_ids, fragment_count, "invalid_operator_prefix",
            )
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
