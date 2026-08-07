"""contact_extractor 清洗管道 + 号段白名单单元测试（任务 2.1 + 2.2）。

2.1 独立式清洗策略：每步从原文独立清洗，不基于上一步结果。
2.2 号段白名单：非三大运营商号段降级为 partial_phone。
只兜底手机号，不做微信号混淆；不做置信度（2.3 独立任务）。
"""

import pytest

from app.services.contact_extractor import (
    _extract_phone_with_pipeline,
    _is_operator_phone,
    extract_contacts_from_text,
)


# ---- _extract_phone_with_pipeline 直接测试 ----

@pytest.mark.parametrize(
    "text,expected",
    [
        ("１３８１２３４５６７８", "13812345678"),   # S1 全角→半角
        ("138a1234b5678", "13812345678"),           # S2 剔字母
        ("138哦1234嗯5678", "13812345678"),         # S3 剔中文
        ("138/1234-5678", "13812345678"),           # S4 全剔非数字（符号）
        ("幺叁八一二三四五六七八", "13812345678"),   # S5 中文数字映射+全剔
        ("13812345678", "13812345678"),             # 标准不走清洗
        ("+8613812345678", "13812345678"),          # S0 剥离区号前缀（缺口1修复）
        ("008613812345678", "13812345678"),         # S0 剥离 0086 区号
        ("8613812345678", "13812345678"),           # S0 剥离 86 区号
        ("电话+8613812345678", "13812345678"),       # S0 中文前缀+区号（残留修复）
        ("1-3-8-a-1-2-3-4-b-5-6-7-8", "13812345678"),  # S4 全字符分隔（缺口2修复）
    ],
)
def test_pipeline_extracts_phone(text, expected):
    # _extract_phone_with_pipeline 返回 (phone, confidence) 元组（任务 2.3）
    result = _extract_phone_with_pipeline(text)
    assert result is not None
    assert result[0] == expected


def test_pipeline_no_false_positive_on_plain_text():
    # 无号码文本 → 不误判
    assert _extract_phone_with_pipeline("你好我想买台奥迪A6") is None


def test_pipeline_no_false_positive_on_platform_masked():
    # 平台脱敏：清洗后 1388002 不足 11 位，不误判
    assert _extract_phone_with_pipeline("138****8002") is None


def test_pipeline_no_false_positive_on_short_digits():
    # 短数字串（价格/年份）不足 11 位，不误判
    assert _extract_phone_with_pipeline("预算100000年份2024") is None


def test_pipeline_cn_digit_with_noise():
    # 中文数字夹噪音字符：映射后剔非数字仍命中
    result = _extract_phone_with_pipeline("幺叁八哦一二三四五六七八")
    assert result is not None
    assert result[0] == "13812345678"


def test_pipeline_cn_digit_homophones_complete():
    # 规则文档 1.3 谐音表完整覆盖：妖(1)/俩(2)/仨(3) 不缺漏
    from app.services.contact_extractor import CN_DIGIT_MAP
    assert CN_DIGIT_MAP["妖"] == "1"
    assert CN_DIGIT_MAP["俩"] == "2"
    assert CN_DIGIT_MAP["仨"] == "3"
    # 妖=1 替代幺/一 作为首位，验证映射在完整号码场景可用
    result = _extract_phone_with_pipeline("妖叁八一二三四五六七八")
    assert result is not None
    assert result[0] == "13812345678"


# ---- extract_contacts_from_text 集成测试 ----

@pytest.mark.parametrize(
    "text,expected",
    [
        ("１３８１２３４５６７８", "13812345678"),
        ("138a1234b5678", "13812345678"),
        ("138哦1234嗯5678", "13812345678"),
        ("138/1234-5678", "13812345678"),
        ("幺叁八一二三四五六七八", "13812345678"),
    ],
)
def test_extract_contacts_fallback_integration(text, expected):
    # 标准匹配未命中时，走管道兜底加入 phones/all_contacts
    result = extract_contacts_from_text(text)
    assert result.phone == expected
    assert expected in result.phones
    assert any(c["type"] == "phone" and c["value"] == expected for c in result.all_contacts)
    assert result.status == "matched"


def test_extract_contacts_standard_not_use_pipeline():
    # 标准 11 位直接命中，不走清洗
    result = extract_contacts_from_text("13812345678")
    assert result.phone == "13812345678"
    assert result.phones == ["13812345678"]


def test_extract_contacts_no_false_positive_on_masked():
    # 平台脱敏不误判：phones 为空
    result = extract_contacts_from_text("138****8002")
    assert result.phone is None
    assert result.phones == []
    assert result.status == "not_matched"


def test_extract_contacts_wechat_not_affected_by_pipeline():
    # 兜底只处理手机号，不影响微信号提取
    result = extract_contacts_from_text("微信号：zhangsan123")
    assert result.wechat == "zhangsan123"
    assert result.phone is None


def test_extract_contacts_phone_priority_over_pipeline():
    # 标准匹配命中的手机号优先，兜底管道不重复添加
    result = extract_contacts_from_text("电话13812345678，备用13912345678")
    assert result.phones == ["13812345678", "13912345678"]
    # all_contacts 不应出现兜底重复项
    phone_values = [c["value"] for c in result.all_contacts if c["type"] == "phone"]
    assert phone_values == ["13812345678", "13912345678"]


# ---- 2.2 号段白名单测试 ----

@pytest.mark.parametrize(
    "phone,expected",
    [
        ("13812345678", True),   # 138 移动
        ("13012345678", True),   # 130 联通
        ("13312345678", True),   # 133 电信
        ("19212345678", True),   # 192 广电
        ("14012345678", False),  # 140 非号段
        ("10012345678", False),  # 100 非号段（第二位0）
        ("11012345678", False),  # 110 非号段（第二位1）
        ("12345678901", False),  # 123 非号段
        ("19999999999", True),   # 199 电信（规则文档测试用例13，199合法号段）
        ("1381234567", False),   # 10 位不够
        ("138123456789", False), # 12 位超长
    ],
)
def test_is_operator_phone(phone, expected):
    assert _is_operator_phone(phone) is expected


def test_whitelist_keeps_valid_segment_phone():
    # 138 移动号段保留
    result = extract_contacts_from_text("电话13812345678")
    assert result.phone == "13812345678"
    assert result.phones == ["13812345678"]


def test_whitelist_degrades_invalid_segment_to_partial():
    # 19999999999 规则文档测试用例13：199合法号段仍保留
    result = extract_contacts_from_text("19999999999")
    assert result.phone == "19999999999"
    assert result.phones == ["19999999999"]


def test_whitelist_degrades_non_operator_to_partial():
    # 140 非白名单号段 → 不进 phones，降级 partial_phone
    result = extract_contacts_from_text("电话14012345678")
    assert result.phone is None
    assert result.phones == []
    assert result.partial_phone == "14012345678"


def test_whitelist_all_invalid_degrades_to_partial():
    # 全部非白名单号码 → phones 清空，降级 partial_phone
    result = extract_contacts_from_text("14012345678和14112345678")
    assert result.phones == []
    assert result.partial_phone is not None


def test_whitelist_mixed_keeps_valid_only():
    # 混合：140 非白名单 + 138 白名单 → 保留 138，丢弃 140
    result = extract_contacts_from_text("14012345678和13812345678")
    assert result.phones == ["13812345678"]
    assert result.phone == "13812345678"
    # all_contacts 只保留白名单号码
    phone_values = [c["value"] for c in result.all_contacts if c["type"] == "phone"]
    assert phone_values == ["13812345678"]


def test_whitelist_pipeline_result_also_validated():
    # 兜底管道清洗出的号码也走白名单：140 夹字母清洗后仍非白名单 → 降级
    result = extract_contacts_from_text("140a1234b5678")
    assert result.phones == []
    assert result.partial_phone == "14012345678"


def test_whitelist_masked_phone_not_affected():
    # 平台脱敏 138****8002 不进白名单（2.1 已挡，2.2 自动跳过）
    result = extract_contacts_from_text("138****8002")
    assert result.phone is None
    assert result.phones == []


# ---- 2.3 置信度分级（规则文档 4.1） ----

def test_confidence_standard_match_whitelist_1_0():
    """标准格式直接匹配 + 白名单号段 → confidence=1.0。"""
    result = extract_contacts_from_text("电话13812345678")
    assert result.phone == "13812345678"
    assert result.confidence == 1.0


def test_confidence_pipeline_s0_country_code():
    """S0 区号剥离清洗命中 → confidence=0.8。"""
    result = extract_contacts_from_text("+8613812345678")
    assert result.phone == "13812345678"
    assert result.confidence == 0.8


def test_confidence_pipeline_s4_strip_non_digits():
    """S4 全剔非数字清洗命中 → confidence=0.8。"""
    result = extract_contacts_from_text("1-3-8-a-1-2-3-4-b-5-6-7-8")
    assert result.phone == "13812345678"
    assert result.confidence == 0.8


def test_confidence_pipeline_s5_cn_digit():
    """S5 中文数字映射命中 → confidence=0.7。"""
    result = extract_contacts_from_text("幺叁八一二三四五六七八")
    assert result.phone == "13812345678"
    assert result.confidence == 0.7


def test_confidence_non_whitelist_degraded_0_4():
    """非白名单号段降级 partial_phone → confidence=0.4。"""
    result = extract_contacts_from_text("电话14012345678")
    assert result.phone is None
    assert result.partial_phone == "14012345678"
    assert result.confidence == 0.4


def test_confidence_wechat_keyword_0_95():
    """微信号关键词定位 → confidence=0.95。"""
    result = extract_contacts_from_text("微信：zhangsan123")
    assert result.wechat == "zhangsan123"
    assert result.confidence == 0.95


def test_confidence_no_match_0_0():
    """无匹配 → confidence=0.0。"""
    result = extract_contacts_from_text("老板您看的是奥迪A6")
    assert result.phone is None
    assert result.wechat is None
    assert result.confidence == 0.0


def test_confidence_takes_max_when_multiple_matches():
    """多条匹配取最高 confidence（标准匹配 1.0 > 微信 0.95）。"""
    result = extract_contacts_from_text("13812345678 微信：zhangsan123")
    assert result.confidence == 1.0


def test_confidence_default_in_empty_text():
    """空文本 → confidence=0.0（默认）。"""
    result = extract_contacts_from_text("")
    assert result.confidence == 0.0


# ---- 2.5 干扰词上下文降权 + context_boost 加成 ----

def test_interference_penalty_without_context_boost():
    """干扰词邻近（公里）+ 无 context_boost → confidence 降 0.2（1.0-0.2=0.8）。"""
    # "这台车跑了13800138000公里"——13800138000 是 11 位但前缀 1380 非白名单号段，
    # 会走白名单降级。改用白名单号段 + 干扰词邻近测试降权
    result = extract_contacts_from_text("跑了13812345678公里")
    assert result.phone == "13812345678"
    assert result.confidence == pytest.approx(0.8)


def test_interference_penalty_with_context_boost():
    """干扰词邻近（公里）+ context_boost=True → confidence 降 0.05 + 加 0.05（1.0-0.05+0.05=1.0）。"""
    result = extract_contacts_from_text("跑了13812345678公里", context_boost=True)
    assert result.phone == "13812345678"
    # 1.0 - 0.05(干扰词降权) + 0.05(context_boost加成) = 1.0
    assert result.confidence == pytest.approx(1.0)


def test_interference_penalty_price_without_context_boost():
    """干扰词邻近（万/元价格）+ 无 context_boost → 降 0.2。"""
    result = extract_contacts_from_text("价格13812345678元")
    assert result.phone == "13812345678"
    assert result.confidence == pytest.approx(0.8)


def test_interference_penalty_year_without_context_boost():
    """干扰词邻近（年）+ 无 context_boost → 降 0.2。"""
    result = extract_contacts_from_text("13812345678年上牌")
    assert result.phone == "13812345678"
    assert result.confidence == pytest.approx(0.8)


def test_no_interference_no_penalty():
    """无干扰词邻近 → 不降权（confidence=1.0）。"""
    result = extract_contacts_from_text("我的电话是13812345678")
    assert result.phone == "13812345678"
    assert result.confidence == 1.0


def test_context_boost_bonus_capped_at_1_0():
    """context_boost +0.05 封顶 1.0（标准匹配本就 1.0，+0.05 仍 1.0）。"""
    result = extract_contacts_from_text("我的电话是13812345678", context_boost=True)
    assert result.phone == "13812345678"
    assert result.confidence == 1.0


def test_interference_penalty_not_below_zero():
    """降权不低于 0.0。非白名单降级到 partial_phone 时 confidence 已是 0.4，
    干扰词降权只针对 phone 匹配（partial_phone 不再降权，它本就是低可信待确认）。"""
    # 非白名单降级 partial_phone，confidence=0.4（干扰词降权不作用于 partial_phone）
    result = extract_contacts_from_text("跑了14012345678公里")
    assert result.partial_phone == "14012345678"
    assert result.confidence == pytest.approx(0.4)


def test_interference_window_nearby_only():
    """干扰词超出窗口（6 字符）不降权。"""
    # 干扰词"公里"在 phone 前 8 个字符处，超出窗口
    result = extract_contacts_from_text("公里好远啊电话13812345678")
    assert result.phone == "13812345678"
    assert result.confidence == 1.0


def test_interference_km_case_insensitive():
    """km 大小写不敏感（KM/Km 都降权）。"""
    result = extract_contacts_from_text("13812345678KM")
    assert result.phone == "13812345678"
    assert result.confidence == pytest.approx(0.8)



# ---- analyze_contact_state 号段白名单一致性（审查发现1修复） ----

def test_analyze_state_valid_segment_is_valid():
    # 138 移动号段 → VALID，与 extract 一致
    from app.services.contact_extractor import analyze_contact_state

    state = analyze_contact_state("号码13812345678")
    assert state.status == "VALID"
    assert state.reason_code == "valid_mobile"


def test_analyze_state_non_operator_segment_degrades_to_partial():
    # 140 非白名单号段 → PARTIAL（invalid_operator_prefix），不再判 VALID
    from app.services.contact_extractor import analyze_contact_state

    state = analyze_contact_state("号码14012345678")
    assert state.status == "PARTIAL"
    assert state.reason_code == "invalid_operator_prefix"


def test_analyze_state_consistent_with_extract():
    # 审查发现1核心断言：两函数对同一非白名单号码判定一致
    from app.services.contact_extractor import analyze_contact_state

    text = "号码14012345678"
    extract_result = extract_contacts_from_text(text)
    state = analyze_contact_state(text)
    # extract 判 partial（不进 phones），analyze 判 PARTIAL
    assert extract_result.phone is None
    assert extract_result.partial_phone == "14012345678"
    assert state.status == "PARTIAL"


# ---- 缺口1+2修复：extract vs analyze 全场景一致性 ----

@pytest.mark.parametrize(
    "text",
    [
        "+8613812345678",              # 缺口1：区号前缀
        "008613812345678",
        "电话+8613812345678",          # 残留：中文前缀+区号
        "1-3-8-a-1-2-3-4-b-5-6-7-8",  # 缺口2：全字符分隔
        "138a1234b5678",               # 清洗管道场景
        "幺叁八一二三四五六七八",       # 中文数字
        "14012345678",                 # 非白名单降级
    ],
)
def test_analyze_extract_consistency_all_cases(text):
    # 规则文档 7.1 全用例：extract 与 analyze 判定一致
    from app.services.contact_extractor import analyze_contact_state

    ex = extract_contacts_from_text(text)
    st = analyze_contact_state(text)
    if ex.phone:
        assert st.status == "VALID", f"{text}: extract命中但analyze={st.status}"
    elif ex.partial_phone:
        assert st.status == "PARTIAL", f"{text}: extract降级partial但analyze={st.status}"
    else:
        assert st.status != "VALID", f"{text}: extract未命中但analyze=VALID"


def test_analyze_country_prefix_is_valid():
    # 缺口1：区号前缀 +8613812345678 → analyze 判 VALID（修复前为 VALID 但 extract 不一致）
    from app.services.contact_extractor import analyze_contact_state

    state = analyze_contact_state("+8613812345678")
    assert state.status == "VALID"
    assert state.reason_code == "valid_mobile"


def test_analyze_full_char_separated_is_valid():
    # 缺口2：全字符分隔 1-3-8-a-1-2-3-4-b-5-6-7-8 → analyze 判 VALID（修复前为 NONE）
    from app.services.contact_extractor import analyze_contact_state

    state = analyze_contact_state("1-3-8-a-1-2-3-4-b-5-6-7-8")
    assert state.status == "VALID"
    assert state.reason_code == "valid_mobile"


