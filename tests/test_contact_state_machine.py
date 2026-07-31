"""联系方式确定性状态机单元测试（A2）。

覆盖规格测试 1-3、6-10；分段合并边界测试见 test_contact_fragment_merge.py。
"""

from app.services.contact_extractor import (
    ContactState,
    analyze_contact_state,
    mask_contact_value,
)


def test_partial_short_digits_is_partial():
    # 规格 1：1770206 → PARTIAL，不构成有效联系方式
    state = analyze_contact_state("1770206")
    assert state.status == "PARTIAL"
    assert state.type == "mobile"
    assert state.normalized_value is None
    assert state.reason_code == "mobile_too_short"


def test_short_fragment_alone_is_not_valid():
    # 规格 2：5816 单独出现 → 不得为 VALID
    state = analyze_contact_state("5816")
    assert state.status == "NONE"
    assert state.normalized_value is None


def test_merged_fragments_become_valid():
    # 规格 3：1770206 + 5816 在窗口内合并后 → VALID
    state = analyze_contact_state("1770206 5816")
    assert state.status == "VALID"
    assert state.normalized_value == "17702065816"
    assert state.reason_code == "valid_mobile"


def test_phone_with_separators_is_valid():
    # 规格 6：138-0013-8000 → VALID
    state = analyze_contact_state("138-0013-8000")
    assert state.status == "VALID"
    assert state.normalized_value == "13800138000"


def test_phone_with_country_prefix_is_valid():
    # 规格 7：+86 138 0013 8000 → VALID
    state = analyze_contact_state("+86 138 0013 8000")
    assert state.status == "VALID"
    assert state.normalized_value == "13800138000"


def test_invalid_prefix_is_invalid():
    # 规格 8：非法号段 → INVALID
    state = analyze_contact_state("12012345678")
    assert state.status == "INVALID"
    assert state.reason_code == "invalid_mobile_prefix"


def test_too_long_digits_is_invalid():
    state = analyze_contact_state("13800138000111")
    assert state.status == "INVALID"
    assert state.reason_code == "mobile_too_long"


def test_budget_year_price_verification_code_not_treated_as_phone():
    # 规格 9：预算/年份/价格/验证码不得被当作号码
    for text in ("预算30万", "今年2024年", "优惠100000", "验证码5816"):
        state = analyze_contact_state(text)
        assert state.status != "VALID", text
    # 验证码 4 位单独不构成 partial
    assert analyze_contact_state("验证码5816").status in ("NONE",)


def test_valid_wechat_is_valid():
    state = analyze_contact_state("微信 abc123")
    assert state.status == "VALID"
    assert state.type == "wechat"


def test_no_contact_is_none():
    state = analyze_contact_state("你好，我想了解一下奔驰")
    assert state.status == "NONE"
    assert state.reason_code == "no_contact"


def test_masked_value_never_exposes_full_number():
    # 规格 10：状态/脱敏值不得暴露完整号码
    state = analyze_contact_state("我的手机号是13800138000")
    assert state.status == "VALID"
    assert state.masked_value == "138****8000"
    assert "13800138000" not in (state.masked_value or "")
    assert state.normalized_value == "13800138000"  # 规范化值用于落库判定，不进 LLM

    partial = analyze_contact_state("1770206")
    assert "1770206" not in (partial.masked_value or "")


def test_source_message_ids_and_fragment_count_carried():
    state = analyze_contact_state(
        "1770206", fragment_count=2, source_message_ids=[11, 22]
    )
    assert state.fragment_count == 2
    assert state.source_message_ids == [11, 22]


def test_ambiguous_fragment_when_digits_broken_by_letter():
    state = analyze_contact_state("138abc5678")
    assert state.status == "AMBIGUOUS"
    assert state.reason_code == "ambiguous_fragment"


def test_isinstance_is_contact_state():
    assert isinstance(analyze_contact_state("13800138000"), ContactState)
    assert isinstance(mask_contact_value("phone", "13800138000"), str)
