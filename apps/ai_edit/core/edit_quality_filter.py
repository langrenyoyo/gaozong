"""轻量剪辑质量过滤（通用骨架）。

来源注记：迁自 auto_edit@develop d0c8189 src/auto_edit/edit_quality_filter.py，
改包路径为 apps.ai_edit.core。删除样片专用词与跨模块依赖（material_semantic_map /
outline_first_planner，审计报告 §7.14/§7.15），保留通用文本归一、claim 分类与去重骨架。
样片专用 ASR 误识词不作为全局规则；后续按版本化商户模板注入领域词。

设计原则（Ponytail）：
- 规则可解释：claim 关键词 + 字符级相似度 + ASR 错误词惩罚
- 最小依赖：仅用标准库 re
- 诚实审计：dropped 段保留 risk_flags audit trail，风险不丢失
- 不为凑时长保留重复：质量优先于时长
"""
from __future__ import annotations

import re
from typing import Any


# 语义 claim 关键词表（通用二手车口播卖点，避免样片专用词）
CLAIM_KEYWORDS: dict[str, list[str]] = {
    "inventory_scale_claim": [
        "认识", "车商", "没见过", "规模",
        "百台", "车场", "现场", "几台", "很多", "大量",
    ],
    "warranty_claim": ["质保", "联保", "保修", "全国联保"],
    "risk_water_depth_claim": ["水深", "二级市场", "水泡", "水淹", "涉水"],
    "guidance_claim": ["左下角", "车单", "喜欢", "车型", "看一下"],
    "trust_compensation_claim": ["退赔", "合同", "赔偿"],
}

# 标点字符集（用 re.escape 安全转义）
_PUNCT_CHARS = "，。！？、；：""''（）()[],.!?;:\"' \t\n\r…"
_PUNCT_RE = re.compile("[" + re.escape(_PUNCT_CHARS) + "]")
_REPEAT_CHAR_RE = re.compile(r"(.)\1+")


def normalize_speech(text: str) -> str:
    """标准化口播文本：去标点 + 去连续重复字（但但→但）。

    不转大小写（中文无大小写），不去口头词（当前场景不需要，YAGNI）。
    """
    if not text:
        return ""
    cleaned = _PUNCT_RE.sub("", text)
    cleaned = _REPEAT_CHAR_RE.sub(r"\1", cleaned)
    return cleaned


def infer_semantic_claim(text: str) -> str | None:
    """按关键词组推断语义 claim（返回首个命中 claim，未命中返回 None）。"""
    if not text:
        return None
    for claim, keywords in CLAIM_KEYWORDS.items():
        if any(k in text for k in keywords):
            return claim
    return None


def classify_claim(text: str) -> str | None:
    """infer_semantic_claim 的语义别名（外部调用统一入口）。"""
    return infer_semantic_claim(text)
