"""通用二手车信任型营销短视频剪辑语法。

来源注记：迁自 auto_edit@develop d0c8189 src/auto_edit/edit_grammar.py，
改包路径为 apps.ai_edit.core。原文件已是通用语法（无样片专用词），原样迁入。

定位（重要）：
- grammar 是可泛化结构，绝不写死样片专用品牌词与专属话术。
- grammar 只约束"讲述目的、顺序、视觉建议、素材选择偏好"，不生成任何事实。
- speech_text 仍必须来自真实 ASR / clean candidates，grammar 不编造台词。
- risk_sensitive grammar beat（service_or_risk_reversal）中的质保 / 退赔 / 合同 /
  检测类内容必须 requires_human_review=True 并保留 risk_flags。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GrammarBeat:
    """单个通用 grammar beat 定义（讲述目的 + 关键词 + 视觉偏好 + 风险标记）。"""

    key: str
    purpose: str
    generic_keywords: tuple[str, ...]
    preferred_visuals: tuple[str, ...]
    fallback_visuals: tuple[str, ...] = ()
    risk_sensitive: bool = False
    maps_reference_examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditGrammarProfile:
    """剪辑语法 profile：通用营销链路 beats 集合。"""

    key: str
    name: str
    description: str
    beats: tuple[GrammarBeat, ...]


# ---------------------------------------------------------------------------
# 6 个通用 grammar beats（基于甲方样片行为抽象，去除样片专用词）
# ---------------------------------------------------------------------------

GRAMMAR_BEATS: tuple[GrammarBeat, ...] = (
    GrammarBeat(
        key="credibility_opening",
        purpose="开头建立可信度、规模、稀缺资源或专业身份",
        generic_keywords=(
            "最大", "车商", "库存", "车源", "多台", "现车",
            "车单", "门店", "规模",
        ),
        preferred_visuals=(
            "wide_inventory_shot", "car_lot_wide",
            "showroom_wide", "presenter_mid_shot",
        ),
        fallback_visuals=("vehicle_exterior",),
        maps_reference_examples=(
            "我不是说我是最大的车商",
            "认识的车商里车源很多",
            "可以点开车单看库存",
        ),
    ),
    GrammarBeat(
        key="proof_or_inventory_evidence",
        purpose="用库存、车单、现场、案例、数据或展示画面证明前面的可信度",
        generic_keywords=(
            "现场", "库存", "车单", "案例", "客户",
            "看一下", "左下角", "车型",
        ),
        preferred_visuals=(
            "phone_or_listing_screen", "car_rows", "inventory_detail",
        ),
        fallback_visuals=("vehicle_exterior",),
    ),
    GrammarBeat(
        key="expertise_and_painpoint",
        purpose="说明专业经验、垂直领域、用户痛点、市场水深",
        generic_keywords=(
            "只做", "专营", "几年", "经验", "二级市场",
            "水深", "专业", "懂车", "踩坑",
        ),
        preferred_visuals=(
            "presenter_mid_shot", "inspection_scene", "showroom_or_office",
        ),
        fallback_visuals=("vehicle_exterior",),
    ),
    GrammarBeat(
        key="service_or_risk_reversal",
        purpose="说明质保、检测、联保、合同、退赔、车况保障等风险反转",
        generic_keywords=(
            "质保", "联保", "检测", "合同", "退赔",
            "车况", "公里数", "保障", "承诺",
        ),
        preferred_visuals=(
            "contract_detail", "inspection_detail", "vehicle_detail",
        ),
        fallback_visuals=("vehicle_exterior",),
        risk_sensitive=True,
    ),
    GrammarBeat(
        key="product_or_inventory_match",
        purpose="说明可以按预算、需求、车型、配置匹配车源",
        generic_keywords=(
            "预算", "需求", "配置", "车型", "匹配",
            "选择", "喜欢", "价格区间",
        ),
        preferred_visuals=(
            "car_rows", "vehicle_exterior",
            "interior_detail", "listing_screen",
        ),
        fallback_visuals=("vehicle_exterior",),
    ),
    GrammarBeat(
        key="cta",
        purpose="行动引导：点车单、私信、搜索、到店、咨询",
        generic_keywords=(
            "点开", "左下角", "私信", "搜索", "到店",
            "咨询", "看一下", "喜欢的车型",
        ),
        preferred_visuals=(
            "screen_search", "listing_screen",
            "presenter_mid_shot", "closing_visual",
        ),
        fallback_visuals=("vehicle_exterior",),
        risk_sensitive=False,
    ),
)


USED_CAR_TRUST_PROFILE = EditGrammarProfile(
    key="used_car_trust_building_short_video",
    name="二手车信任型营销短视频",
    description=(
        "通用二手车信任型营销短视频剪辑语法：可信度开场 → 库存证据 → "
        "专业痛点 → 风险反转 → 车源匹配 → 行动引导。可泛化到不同车型 / 商家 / 素材。"
    ),
    beats=GRAMMAR_BEATS,
)


# service 强信号（risk_sensitive 最重要，命中优先归 service_or_risk_reversal）
_SERVICE_STRONG_KEYWORDS: tuple[str, ...] = (
    "质保", "退赔", "合同", "检测", "联保",
)
# cta 强导流信号（命中优先归 cta，避免"车单/左下角"把 cta 误判为 credibility）
_CTA_STRONG_KEYWORDS: tuple[str, ...] = (
    "私信", "搜索", "到店", "咨询", "关注", "点开",
)


_PROFILES: dict[str, EditGrammarProfile] = {
    USED_CAR_TRUST_PROFILE.key: USED_CAR_TRUST_PROFILE,
}


def load_grammar_profile(key: str | None = None) -> EditGrammarProfile:
    """加载 grammar profile（默认 used_car_trust_building_short_video）。"""
    profile_key = key or USED_CAR_TRUST_PROFILE.key
    if profile_key not in _PROFILES:
        raise KeyError(f"未知 grammar profile: {profile_key}")
    return _PROFILES[profile_key]


def grammar_beat_keys(profile: EditGrammarProfile | None = None) -> list[str]:
    """返回 profile 的 grammar beat key 列表（保序）。"""
    p = profile or USED_CAR_TRUST_PROFILE
    return [b.key for b in p.beats]


def is_valid_grammar_beat(key: str, profile: EditGrammarProfile | None = None) -> bool:
    """判断 key 是否为该 profile 的合法 grammar beat。"""
    return bool(key) and key in grammar_beat_keys(profile)


def get_grammar_beat(
    key: str, profile: EditGrammarProfile | None = None
) -> GrammarBeat | None:
    """按 key 取 grammar beat 定义，无则返回 None。"""
    p = profile or USED_CAR_TRUST_PROFILE
    for b in p.beats:
        if b.key == key:
            return b
    return None


def infer_grammar_beat_from_text(
    text: str, profile: EditGrammarProfile | None = None
) -> str:
    """从口播文本兜底推断 grammar beat（关键词信号，不凭空生成）。

    优先级（消歧，避免重叠关键词误判）：
    1. service 强信号（质保/退赔/合同/检测/联保）→ service_or_risk_reversal
       （risk_sensitive 最重要，必须优先识别以便标 requires_human_review）
    2. cta 强导流信号（私信/搜索/到店/咨询/关注/点开）→ cta
       （避免"车单/左下角"等重叠词把 cta 误判为 credibility_opening）
    3. 其余按 generic_keywords 命中数取最高
    无任何命中返回空串。
    """
    p = profile or USED_CAR_TRUST_PROFILE
    if not text:
        return ""
    # 1. service 强信号优先（risk_sensitive）
    if any(kw in text for kw in _SERVICE_STRONG_KEYWORDS):
        if get_grammar_beat("service_or_risk_reversal", p):
            return "service_or_risk_reversal"
    # 2. cta 强导流信号次之
    if any(kw in text for kw in _CTA_STRONG_KEYWORDS):
        if get_grammar_beat("cta", p):
            return "cta"
    # 3. 按 generic_keywords 命中数
    best_key, best_hits = "", 0
    for b in p.beats:
        hits = sum(1 for kw in b.generic_keywords if kw in text)
        if hits > best_hits:
            best_hits, best_key = hits, b.key
    return best_key


def build_grammar_prompt_section(profile: EditGrammarProfile | None = None) -> str:
    """构造 prompt 的 grammar section（通用营销链路 + 受控约束 + risk_sensitive）。"""
    p = profile or USED_CAR_TRUST_PROFILE
    chain_desc = "\n".join(
        f"{i + 1}. {b.key}\n"
        f"   purpose: {b.purpose}\n"
        f"   generic_keywords: {'/'.join(b.generic_keywords[:6])}\n"
        f"   preferred_visuals: {', '.join(b.preferred_visuals[:3])}\n"
        f"   risk_sensitive: {b.risk_sensitive}"
        for i, b in enumerate(p.beats)
    )
    allowed = grammar_beat_keys(p)
    risk_sensitive = [b.key for b in p.beats if b.risk_sensitive]
    return (
        f"通用剪辑语法（edit_grammar profile={p.key}，{p.name}）—— "
        f"这是通用营销链路约束，可泛化到不同车型 / 商家 / 素材，不是固定样片剧本：\n"
        f"{chain_desc}\n\n"
        "grammar 约束（必须遵守）：\n"
        "1. 优先遵循 edit_grammar 的通用营销链路讲述目的与顺序，而非照搬某一样片时间轴。\n"
        "2. reference_script（如提供）是当前样片的实例，帮助理解节奏和顺序，"
        "不是固定文案来源，绝不得照抄或改写样片专用台词（如品牌名 / 退赔话术）。\n"
        f"3. 每个 segment 必须输出 grammar_beat，且只能从受控集合选择："
        f"{{{', '.join(allowed)}}}，不得自创 grammar_beat。\n"
        f"6. risk_sensitive grammar beat（{', '.join(risk_sensitive)}）中的质保 / 退赔 / 合同 / "
        "检测类内容，必须 requires_human_review=true 并保留 risk_flags（不得因 grammar 归类而清除风险标记）。\n"
        "7. 缺少某 grammar beat 的素材时，在 missing_or_weak_grammar_beats 标注，不得硬编或自创 beat 顶替。\n"
    )
