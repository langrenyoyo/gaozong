"""4.0 客户画像三源统—单元测试。

验证：① 工作台/线索列表读 customer_profiles 表，持久化字段优先覆盖消息派生；
② 表为空时消息派生兜底；③ 读表异常降级不阻断；④ 入参正确（merchant_id/account_open_id/customer_open_id）。
"""

from datetime import datetime
from unittest.mock import patch

from app.services.douyin_workbench_conversation_service import (
    WorkbenchMessage,
    _conversation_profile_payload,
)
from app.services.lead_management_service import _derive_lead_profile_fields
from app.models import CustomerProfile, DouyinLead


# ---- 工作台 _conversation_profile_payload ----

def _make_workbench_messages(*, open_id="cust_open_id", account_open_id="acct_open_id"):
    return [
        WorkbenchMessage(
            event_id=1, event="im_receive_msg", account_open_id=account_open_id,
            open_id=open_id, conversation_key="conv_001", conversation_short_id="conv_001",
            content="我想看奥迪A6", message_type="text", media_type=None, resource_url=None,
            created_at=datetime.now(), server_message_id="msg_1", nick_name="客户",
            avatar=None, lead_id=None,
        ),
    ]


# mock 掉依赖 db 的辅助函数，聚焦画像读表逻辑
def _patch_workbench_helpers():
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("app.services.douyin_workbench_conversation_service._find_conversation_lead", return_value=None))
    stack.enter_context(patch("app.services.douyin_workbench_conversation_service.build_conversation_tags", return_value=[]))
    stack.enter_context(patch("app.services.douyin_workbench_conversation_service._profile_trace", return_value={}))
    stack.enter_context(patch("app.services.douyin_workbench_conversation_service._profile_lead_score", return_value=0))
    return stack


def test_workbench_persisted_profile_overrides_derived():
    """持久化档案字段非空 → 覆盖消息派生值。"""
    messages = _make_workbench_messages()
    persisted = {"intent_car": "奔驰E级", "car_year": "2023", "budget": "30万", "city": "广州"}
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
        return_value=persisted,
    ):
        result = _conversation_profile_payload(None, messages, merchant_id="m1")
    assert result is not None
    # 持久化优先
    assert result["intent_car"] == "奔驰E级"
    assert result["car_year"] == "2023"
    assert result["budget"] == "30万"
    assert result["city"] == "广州"


def test_workbench_message_derived_fallback_when_no_profile():
    """表无记录 → 消息派生兜底（不丢失派生能力）。"""
    messages = _make_workbench_messages()
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
        return_value=None,
    ):
        result = _conversation_profile_payload(None, messages, merchant_id="m1")
    assert result is not None
    # 消息派生结果保留（不因表空而丢失）
    assert "intent_car" in result


def test_workbench_partial_persisted_keeps_derived_for_empty_fields():
    """持久化只覆盖非空字段，空字段保留派生值。"""
    messages = _make_workbench_messages()
    persisted = {"intent_car": "奔驰E级", "car_year": None, "budget": None, "city": None}
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
        return_value=persisted,
    ):
        result = _conversation_profile_payload(None, messages, merchant_id="m1")
    assert result is not None
    # intent_car 持久化覆盖
    assert result["intent_car"] == "奔驰E级"


def test_workbench_load_exception_degrades_to_derived():
    """load_customer_profile 抛异常 → 降级到消息派生，不阻断工作台。"""
    messages = _make_workbench_messages()
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
        side_effect=RuntimeError("db_error"),
    ):
        result = _conversation_profile_payload(None, messages, merchant_id="m1")
    # 不抛错，返回正常 payload
    assert result is not None
    assert "intent_car" in result


def test_workbench_load_called_with_correct_params():
    """入参正确：merchant_id/account_open_id(企业号)/customer_open_id(open_id)。"""
    messages = _make_workbench_messages(open_id="cust_001", account_open_id="acct_001")
    captured = {}
    def fake_load(db, *, merchant_id, account_open_id, customer_open_id):
        captured.update(merchant_id=merchant_id, account_open_id=account_open_id, customer_open_id=customer_open_id)
        return None
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
        side_effect=fake_load,
    ):
        _conversation_profile_payload(None, messages, merchant_id="m1")
    assert captured == {"merchant_id": "m1", "account_open_id": "acct_001", "customer_open_id": "cust_001"}


def test_workbench_no_load_when_merchant_id_missing():
    """merchant_id 缺失 → 不调 load_customer_profile（无商户上下文不读表）。"""
    messages = _make_workbench_messages()
    with _patch_workbench_helpers(), patch(
        "app.services.douyin_workbench_conversation_service.load_customer_profile",
    ) as mock_load:
        _conversation_profile_payload(None, messages, merchant_id=None)
    mock_load.assert_not_called()


# ---- 线索列表 _derive_lead_profile_fields ----

def _make_lead(*, merchant_id="m1", account_open_id="acct_001", source_id="cust_001"):
    lead = DouyinLead()
    lead.id = 100
    lead.merchant_id = merchant_id
    lead.account_open_id = account_open_id
    lead.source_id = source_id
    lead.conversation_short_id = "conv_001"
    lead.raw_data = None
    return lead


def test_lead_persisted_profile_overrides_derived():
    """持久化档案字段非空 → 覆盖消息派生值。"""
    lead = _make_lead()
    persisted = {"intent_car": "宝马5系", "car_year": "2022", "budget": "40万", "city": "深圳"}
    with patch(
        "app.services.lead_management_service.load_customer_profile",
        return_value=persisted,
    ), patch(
        "app.services.lead_management_service._lead_customer_message_texts",
        return_value=["随便看看"],
    ):
        result = _derive_lead_profile_fields(None, lead, include_messages=True)
    assert result["intent_car"] == "宝马5系"
    assert result["car_year"] == "2022"
    assert result["budget"] == "40万"
    assert result["city"] == "深圳"


def test_lead_message_derived_fallback_when_no_profile():
    """表无记录 → 消息派生兜底。"""
    lead = _make_lead()
    with patch(
        "app.services.lead_management_service.load_customer_profile",
        return_value=None,
    ), patch(
        "app.services.lead_management_service._lead_customer_message_texts",
        return_value=["我想看奔驰"],
    ):
        result = _derive_lead_profile_fields(None, lead, include_messages=True)
    # 消息派生结果保留
    assert "intent_car" in result


def test_lead_load_exception_degrades_to_derived():
    """load_customer_profile 抛异常 → 降级，不阻断。"""
    lead = _make_lead()
    with patch(
        "app.services.lead_management_service.load_customer_profile",
        side_effect=RuntimeError("db_error"),
    ), patch(
        "app.services.lead_management_service._lead_customer_message_texts",
        return_value=["我想看奥迪"],
    ):
        result = _derive_lead_profile_fields(None, lead, include_messages=True)
    assert "intent_car" in result


def test_lead_load_called_with_correct_params():
    """入参正确：merchant_id/account_open_id/source_id(customer_open_id)。"""
    lead = _make_lead(merchant_id="m1", account_open_id="acct_001", source_id="cust_001")
    captured = {}
    def fake_load(db, *, merchant_id, account_open_id, customer_open_id):
        captured.update(merchant_id=merchant_id, account_open_id=account_open_id, customer_open_id=customer_open_id)
        return None
    with patch(
        "app.services.lead_management_service.load_customer_profile",
        side_effect=fake_load,
    ), patch(
        "app.services.lead_management_service._lead_customer_message_texts",
        return_value=[],
    ):
        _derive_lead_profile_fields(None, lead, include_messages=False)
    assert captured == {"merchant_id": "m1", "account_open_id": "acct_001", "customer_open_id": "cust_001"}


def test_lead_no_load_when_source_id_missing():
    """lead.source_id 缺失 → 不调 load_customer_profile。"""
    lead = _make_lead(source_id=None)
    with patch(
        "app.services.lead_management_service.load_customer_profile",
    ) as mock_load, patch(
        "app.services.lead_management_service._lead_customer_message_texts",
        return_value=[],
    ):
        _derive_lead_profile_fields(None, lead, include_messages=False)
    mock_load.assert_not_called()
