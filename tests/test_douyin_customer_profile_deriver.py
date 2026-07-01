from app.services.douyin_customer_profile_deriver import (
    derive_profile_fields_from_messages,
    derive_profile_fields_from_raw_data,
    merge_profile_fields,
)


def test_raw_data_profile_deriver_supports_shared_key_aliases():
    fields = derive_profile_fields_from_raw_data(
        {
            "source_channel": "抖音私信",
            "brand_model": "宝马5系",
            "model_year": "2021",
            "price_range": "20-30万",
            "location_city": "广州",
        }
    )

    assert fields == {
        "source_channel": "抖音私信",
        "intent_car": "宝马5系",
        "car_year": "2021",
        "budget": "20-30万",
        "city": "广州",
    }


def test_message_profile_deriver_uses_customer_text_only():
    fields = derive_profile_fields_from_messages(
        [
            "系统提示：你收到一条新消息，请打开抖音app查看",
            "我预算差不多10万，在广州，想看20年宝马5系。",
        ]
    )

    assert fields["source_channel"] is None
    assert fields["intent_car"] in {"宝马5系", "宝马"}
    assert fields["car_year"] == "20款"
    assert fields["budget"] == "10万"
    assert fields["city"] == "广州"


def test_merge_profile_fields_prefers_raw_data_over_message_guess():
    merged = merge_profile_fields(
        {
            "source_channel": "douyin",
            "intent_car": "奥迪A6",
            "car_year": None,
            "budget": "30万以内",
            "city": None,
        },
        {
            "source_channel": None,
            "intent_car": "宝马5系",
            "car_year": "21款",
            "budget": "20万",
            "city": "深圳",
        },
    )

    assert merged == {
        "source_channel": "douyin",
        "intent_car": "奥迪A6",
        "car_year": "21款",
        "budget": "30万以内",
        "city": "深圳",
    }

