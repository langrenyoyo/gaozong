"""Phase 12 Task 5 AI 剪辑纯逻辑内核测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.2。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 5 Step 2。

迁入的纯逻辑内核（来源 auto_edit@develop d0c8189，改包路径 + 删样片品牌/路径/raw 响应写盘）：
- core/edit_grammar.py：通用二手车信任型营销语法（6 beats，无样片专用词）；
- core/llm_output_validation.py：LLM 输出校验统一 report 结构 + 纯函数工具；
- core/subtitle_text_cleaner.py：字幕清理骨架（透传 + 审计报告，无样片硬编码台词）；
- core/edit_quality_filter.py：质量过滤通用骨架（文本归一 + claim 分类，无样片词）；
- core/models.py：数据模型（移除绝对路径字段，改 storage_key 相对键）。

边界：不实现媒体工具、不调用真实 LLM、不读外部仓库路径。
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# edit_grammar
# ---------------------------------------------------------------------------


def test_grammar_profile_loads_default():
    from apps.ai_edit.core import edit_grammar as eg

    profile = eg.load_grammar_profile()
    assert profile.key == "used_car_trust_building_short_video"
    keys = eg.grammar_beat_keys(profile)
    # 6 个通用 beats
    assert len(keys) == 6
    assert "service_or_risk_reversal" in keys
    assert "cta" in keys


def test_grammar_beat_validity():
    from apps.ai_edit.core import edit_grammar as eg

    assert eg.is_valid_grammar_beat("cta")
    assert eg.is_valid_grammar_beat("credibility_opening")
    assert not eg.is_valid_grammar_beat("路虎开场")  # 样片专用词不是合法 beat
    assert not eg.is_valid_grammar_beat("")


def test_grammar_infer_service_strong_signal():
    from apps.ai_edit.core import edit_grammar as eg

    # service 强信号优先（risk_sensitive）
    assert eg.infer_grammar_beat_from_text("我们有质保和联保") == "service_or_risk_reversal"


def test_grammar_infer_cta_strong_signal():
    from apps.ai_edit.core import edit_grammar as eg

    # cta 强导流信号
    assert eg.infer_grammar_beat_from_text("欢迎私信我了解详情") == "cta"


def test_grammar_infer_empty_returns_empty():
    from apps.ai_edit.core import edit_grammar as eg

    assert eg.infer_grammar_beat_from_text("") == ""


def test_grammar_no_sample_brand_words():
    """审计 §7.15：通用语法不得写死路虎/揽胜/车雷达等样片专用词。"""
    from apps.ai_edit.core import edit_grammar as eg

    profile = eg.load_grammar_profile()
    blob = repr(profile)
    for forbidden in ("路虎", "揽胜", "车雷达", "川虎", "退一赔三"):
        assert forbidden not in blob, f"通用语法残留样片词: {forbidden}"


# ---------------------------------------------------------------------------
# llm_output_validation
# ---------------------------------------------------------------------------


def test_build_validation_result_defaults():
    from apps.ai_edit.core import llm_output_validation as lv

    result = lv.build_validation_result(
        validator_name="test", validator_version="v1", validator_valid=True
    )
    assert result["validator_name"] == "test"
    assert result["validator_valid"] is True
    assert result["risk_level"] == "low"
    assert result["rejection_reasons"] == []
    assert result["manual_review_required"] is False


def test_build_validation_result_normalizes_risk_level():
    from apps.ai_edit.core import llm_output_validation as lv

    result = lv.build_validation_result(
        validator_name="t", validator_version="v1", validator_valid=False,
        risk_level="bogus",
    )
    assert result["risk_level"] == "low"  # 非法归一 low


def test_merge_rejection_reasons_dedup():
    from apps.ai_edit.core import llm_output_validation as lv

    merged = lv.merge_rejection_reasons(["a", "b"], ["b", "c"], [None, ""])
    assert merged == ["a", "b", "c"]


def test_count_unsafe_fields_recursive():
    from apps.ai_edit.core import llm_output_validation as lv

    payload = {
        "safe": 1,
        "token": "secret",          # 命中
        "children": [
            {"path": "/x", "ok": 1},  # path 命中
            {"authorization": "x"},     # 命中
        ],
    }
    assert lv.count_unsafe_fields(payload, {"token", "path", "authorization"}) == 3


# ---------------------------------------------------------------------------
# subtitle_text_cleaner（通用骨架：无样片硬编码 → 透传 + 审计报告）
# ---------------------------------------------------------------------------


def test_subtitle_cleaner_passthrough_when_no_correction():
    from apps.ai_edit.core import subtitle_text_cleaner as sc

    segments = [{"order": 1, "asset_id": "mat-1", "speech_text": "正常的口播文本"}]
    cleaned, report = sc.apply_subtitle_text_cleanup(segments)
    assert cleaned[0]["display_text"] == "正常的口播文本"
    assert cleaned[0]["subtitle_text"] == "正常的口播文本"
    assert cleaned[0]["text_correction_status"] == "none"
    assert report["text_cleanup_corrections_count"] == 0
    assert report["subtitle_text_available"] is True


def test_subtitle_cleaner_no_sample_brand_words():
    """审计 §7.15：清理器不得残留路虎/揽胜/车雷达等样片台词硬编码。"""
    import inspect

    from apps.ai_edit.core import subtitle_text_cleaner as sc

    source = inspect.getsource(sc)
    for forbidden in ("路虎", "揽胜", "车雷达", "川虎之家", "退一赔三", "三年九万公里"):
        assert forbidden not in source, f"清理器残留样片词: {forbidden}"


# ---------------------------------------------------------------------------
# edit_quality_filter（通用骨架：文本归一 + claim 分类，无样片词）
# ---------------------------------------------------------------------------


def test_quality_filter_normalize_speech():
    from apps.ai_edit.core import edit_quality_filter as qf

    # 去标点 + 去连续重复字（但但→但），"是"保留
    assert qf.normalize_speech("但但是，最大的车商。") == "但是最大的车商"


def test_quality_filter_no_sample_brand_words():
    """审计 §7.15：质量过滤 claim 关键词不得写死样片专用词。"""
    import inspect

    from apps.ai_edit.core import edit_quality_filter as qf

    source = inspect.getsource(qf)
    # 样片 ASR 误识专有词，通用骨架不得保留
    for forbidden in ("路虎", "路费", "川虎之家", "车雷达", "三年九万公里"):
        assert forbidden not in source, f"质量过滤残留样片词: {forbidden}"


def test_quality_filter_claim_classification_generic():
    """通用 claim 分类：质保类关键词命中 warranty_claim，不依赖样片词。"""
    from apps.ai_edit.core import edit_quality_filter as qf

    claim = qf.classify_claim("这台车有质保和全国联保")
    assert claim == "warranty_claim"
