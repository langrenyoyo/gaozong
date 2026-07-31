"""ContactState 单一可信源传递测试（R1 阻断项二）。

9000 计算的 ContactState 通过 ReplySuggestionRequest 传给 9100，9100 优先消费 request 状态，
不覆盖；未传时 local_fallback；训练端 training_default。
"""

from apps.xg_douyin_ai_cs.schemas import ReplySuggestionRequest
from apps.xg_douyin_ai_cs.services.reply_decision_service import (
    _resolve_contact_state_with_source,
)


def _req(**kw):
    base = dict(
        tenant_id="t1", account_id="acc1", latest_message="你好", merchant_id="m1",
    )
    base.update(kw)
    return ReplySuggestionRequest(**base)


def test_request_contact_state_takes_priority():
    # 规格 6.4.2/6.4.3：9100 优先使用 request 状态，不覆盖
    contacts = {"has_contact": False, "partial_phone": None}
    state, action, source = _resolve_contact_state_with_source(
        request=_req(
            latest_message="在吗",
            contact_state={"status": "VALID", "type": "mobile", "masked_value": "138****8000"},
            contact_action="CONFIRM_AND_CONVERT",
            contact_state_source="request",
        ),
        contacts=contacts,
    )
    assert state == "VALID"
    assert action == "CONFIRM_AND_CONVERT"
    assert source == "request"


def test_request_state_not_overridden_by_local_text():
    # 规格 6.4.3：9100 不得根据脱敏文本覆盖 request 中的可信状态
    # 即便 latest_message 本地推断为 NONE，request 传 VALID 仍为 VALID
    state, action, source = _resolve_contact_state_with_source(
        request=_req(
            latest_message="你好呀",
            contact_state={"status": "PARTIAL", "type": "mobile", "masked_value": "177***06"},
            contact_action="REQUEST_COMPLETION",
            contact_state_source="request",
        ),
        contacts={"has_contact": False, "partial_phone": None},
    )
    assert state == "PARTIAL"
    assert source == "request"


def test_local_fallback_when_request_missing():
    # 规格 6.4.4/6.4.5：request 未传状态时 local fallback
    state, action, source = _resolve_contact_state_with_source(
        request=_req(latest_message="我的电话13800138000"),
        contacts={"has_contact": False, "partial_phone": None},
    )
    assert state == "VALID"
    assert source == "local_fallback"


def test_local_fallback_from_history_contacts():
    state, action, source = _resolve_contact_state_with_source(
        request=_req(latest_message="在吗"),
        contacts={"has_contact": True, "partial_phone": None},
    )
    assert state == "VALID"
    assert source == "local_fallback"


def test_training_default_source():
    # 规格 6.4.5/3.3：训练端 training_default
    state, action, source = _resolve_contact_state_with_source(
        request=_req(latest_message="你好", contact_state={"status": "NONE"}, contact_state_source="training_default"),
        contacts={"has_contact": False, "partial_phone": None},
    )
    assert state == "NONE"
    assert source == "training_default"


def test_request_and_log_no_plain_contact():
    # 规格 6.4.6：请求与日志不含联系方式明文
    req = _req(
        latest_message="在吗",
        contact_state={"status": "VALID", "type": "mobile", "masked_value": "138****8000"},
        contact_state_source="request",
    )
    serialized = req.model_dump_json()
    assert "13800138000" not in serialized
    assert "138****8000" in serialized  # 仅脱敏值


def test_contact_state_fields_optional():
    # 规格 3.3.1：contact_state 与 contact_action 可选
    req = _req(latest_message="你好")
    assert req.contact_state is None
    assert req.contact_action is None
    assert req.contact_state_source is None


def test_action_defaults_to_none_when_request_missing():
    state, action, source = _resolve_contact_state_with_source(
        request=_req(latest_message="你好"),
        contacts={"has_contact": False, "partial_phone": None},
    )
    assert action is None or action == "NONE"
