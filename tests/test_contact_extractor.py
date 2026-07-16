"""联系方式提取 service 单元测试。"""

from app.services.contact_extractor import extract_contacts_from_text, mask_contacts_in_text


def _values(result):
    return [(item["type"], item["value"]) for item in result.all_contacts]


def test_extract_phone_from_common_text():
    result = extract_contacts_from_text("我的手机号是13812345678")

    assert result.phone == "13812345678"
    assert result.phones == ["13812345678"]
    assert result.wechat is None
    assert result.wechats == []
    assert result.status == "matched"
    assert result.failure_reason is None


def test_extract_phone_after_label():
    result = extract_contacts_from_text("电话 13812345678")

    assert result.phone == "13812345678"
    assert result.phones == ["13812345678"]


def test_extract_phone_only_text():
    result = extract_contacts_from_text("13812345678")

    assert result.phone == "13812345678"
    assert result.phones == ["13812345678"]


def test_extract_multiple_phones_keeps_order():
    result = extract_contacts_from_text("电话13812345678，备用13912345678")

    assert result.phone == "13812345678"
    assert result.phones == ["13812345678", "13912345678"]
    assert _values(result) == [
        ("phone", "13812345678"),
        ("phone", "13912345678"),
    ]


def test_extract_duplicate_phones_deduplicates_by_first_seen():
    result = extract_contacts_from_text("13812345678 再说一次 13812345678")

    assert result.phones == ["13812345678"]
    assert _values(result) == [("phone", "13812345678")]


def test_non_11_digit_number_is_not_phone():
    result = extract_contacts_from_text("号码 138123456789")

    assert result.phone is None
    assert result.phones == []
    assert result.status == "not_matched"
    assert result.failure_reason == "contact_not_found"


def test_invalid_phone_prefix_is_not_matched():
    result = extract_contacts_from_text("号码 12812345678")

    assert result.phone is None
    assert result.phones == []
    assert result.status == "not_matched"


def test_empty_text_returns_empty_text_status():
    result = extract_contacts_from_text("")

    assert result.phone is None
    assert result.wechat is None
    assert result.phones == []
    assert result.wechats == []
    assert result.all_contacts == []
    assert result.status == "empty_text"
    assert result.failure_reason == "empty_text"
    assert result.raw_text == ""


def test_mask_contacts_in_text_keeps_message_meaning_without_plain_contact_values():
    masked = mask_contacts_in_text("预算30万，电话13812345678，微信wx_customer_88")

    assert masked == "预算30万，电话138****5678，微信wx***88"
    assert "13812345678" not in masked
    assert "wx_customer_88" not in masked


def test_extract_wechat_after_chinese_keyword():
    result = extract_contacts_from_text("微信 abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]
    assert result.phone is None
    assert result.status == "matched"


def test_extract_wechat_after_chinese_keyword_with_colon():
    result = extract_contacts_from_text("微信号：abc_123")

    assert result.wechat == "abc_123"
    assert result.wechats == ["abc_123"]


def test_extract_wechat_after_lower_wx():
    result = extract_contacts_from_text("wx abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_upper_wx():
    result = extract_contacts_from_text("WX abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_lower_vx():
    result = extract_contacts_from_text("vx abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_upper_vx():
    result = extract_contacts_from_text("VX abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_single_v_with_space_separator():
    result = extract_contacts_from_text("v abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_single_v_with_colon_separator():
    result = extract_contacts_from_text("v:abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_add_me_keyword():
    result = extract_contacts_from_text("加我 abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_extract_wechat_after_add_me_without_separator():
    result = extract_contacts_from_text("我想买辆车，➕我qazwkp152")

    assert result.wechat == "qazwkp152"
    assert result.wechats == ["qazwkp152"]


def test_extract_wechat_from_weak_car_buying_context():
    result = extract_contacts_from_text("你好 我想买台车 dhff98475")

    assert result.wechat == "dhff98475"
    assert result.wechats == ["dhff98475"]


def test_extract_wechat_positive_variants_from_task_examples():
    cases = [
        ("加我qazwkp152", "qazwkp152"),
        ("微信qazwkp152", "qazwkp152"),
        ("微qazwkp152", "qazwkp152"),
        ("V我 qAz_wkp-152", "qAz_wkp-152"),
        ("vx qazwkp152", "qazwkp152"),
        ("v: qazwkp152", "qazwkp152"),
        ("微信号：qazwkp152", "qazwkp152"),
    ]

    for text, expected in cases:
        result = extract_contacts_from_text(text)
        assert result.wechat == expected
        assert result.wechats == [expected]


def test_extract_wechat_after_add_my_wechat_keyword():
    result = extract_contacts_from_text("加我微信 abc123")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123"]


def test_plain_account_without_keyword_is_not_wechat():
    result = extract_contacts_from_text("abc123")

    assert result.wechat is None
    assert result.wechats == []
    assert result.status == "not_matched"


def test_short_wechat_is_not_matched():
    result = extract_contacts_from_text("微信 abc12")

    assert result.wechat is None
    assert result.wechats == []
    assert result.status == "not_matched"


def test_chinese_wechat_is_not_matched():
    result = extract_contacts_from_text("微信 张三abc123")

    assert result.wechat is None
    assert result.wechats == []
    assert result.status == "not_matched"


def test_extract_multiple_wechats_keeps_order():
    result = extract_contacts_from_text("微信 abc123，wx def_456")

    assert result.wechat == "abc123"
    assert result.wechats == ["abc123", "def_456"]
    assert _values(result) == [
        ("wechat", "abc123"),
        ("wechat", "def_456"),
    ]


def test_extract_duplicate_wechats_deduplicates_by_first_seen():
    result = extract_contacts_from_text("微信 abc123，wx abc123")

    assert result.wechats == ["abc123"]
    assert _values(result) == [("wechat", "abc123")]


def test_single_v_does_not_match_inside_english_word():
    result = extract_contacts_from_text("love abc123")

    assert result.wechat is None
    assert result.wechats == []


def test_single_v_does_not_match_plain_english_word_prefix():
    result = extract_contacts_from_text("conversation is visible")

    assert result.wechat is None
    assert result.wechats == []


def test_plain_english_token_without_car_context_is_not_wechat():
    result = extract_contacts_from_text("douyin open_id server_message_id conversation_short_id https miniapp")

    assert result.wechat is None
    assert result.wechats == []


def test_phone_number_is_not_wechat_when_car_context_exists():
    result = extract_contacts_from_text("我想买车 15057903797")

    assert result.phone == "15057903797"
    assert result.wechat is None
    assert result.wechats == []


def test_extract_phone_and_wechat_together():
    result = extract_contacts_from_text("手机号13812345678 微信 abc123")

    assert result.phone == "13812345678"
    assert result.wechat == "abc123"
    assert result.phones == ["13812345678"]
    assert result.wechats == ["abc123"]
    assert result.status == "matched"


def test_extract_phone_first_wechat_later_keeps_all_contact_order():
    result = extract_contacts_from_text("电话13812345678，微信 abc123")

    assert _values(result) == [
        ("phone", "13812345678"),
        ("wechat", "abc123"),
    ]


def test_extract_wechat_first_phone_later_keeps_all_contact_order():
    result = extract_contacts_from_text("微信 abc123 电话13812345678")

    assert result.phone == "13812345678"
    assert result.wechat == "abc123"
    assert _values(result) == [
        ("wechat", "abc123"),
        ("phone", "13812345678"),
    ]


def test_extract_many_contacts_together():
    result = extract_contacts_from_text("wx abc123 电话13812345678 vx def-456 13912345678")

    assert result.phone == "13812345678"
    assert result.wechat == "abc123"
    assert result.phones == ["13812345678", "13912345678"]
    assert result.wechats == ["abc123", "def-456"]
    assert _values(result) == [
        ("wechat", "abc123"),
        ("phone", "13812345678"),
        ("wechat", "def-456"),
        ("phone", "13912345678"),
    ]


def test_no_contact_returns_not_matched():
    result = extract_contacts_from_text("你好，我想了解一下")

    assert result.phone is None
    assert result.wechat is None
    assert result.phones == []
    assert result.wechats == []
    assert result.all_contacts == []
    assert result.status == "not_matched"
    assert result.failure_reason == "contact_not_found"


def test_none_text_returns_empty_text_status():
    result = extract_contacts_from_text(None)

    assert result.phone is None
    assert result.wechat is None
    assert result.phones == []
    assert result.wechats == []
    assert result.all_contacts == []
    assert result.status == "empty_text"
    assert result.failure_reason == "empty_text"
    assert result.raw_text is None
