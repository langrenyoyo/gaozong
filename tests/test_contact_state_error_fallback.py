"""9000 ContactState 异常降级语义测试（R2）。

异常时不伪装为可信 request，由 9100 local_fallback 恢复。
"""

from unittest.mock import patch

from app.services.ai_auto_reply_dry_run_service import _build_request_contact_state
from apps.xg_douyin_ai_cs.schemas import ReplySuggestionRequest
from apps.xg_douyin_ai_cs.services.reply_decision_service import _resolve_contact_state_with_source


def _resolve(payload_contact_state, latest_message, contacts=None):
    """模拟 9100 消费：用 9000 注入的 contact 字段构造 request。"""
    req = ReplySuggestionRequest(
        tenant_id="t1", account_id="acc1", merchant_id="m1", latest_message=latest_message,
        contact_state=payload_contact_state.get("contact_state"),
        contact_action=payload_contact_state.get("contact_action"),
        contact_state_source=payload_contact_state.get("contact_state_source"),
    )
    return _resolve_contact_state_with_source(
        request=req, contacts=contacts or {"has_contact": False, "partial_phone": None},
    )


def test_resolver_exception_omits_trustworthy_request(monkeypatch):
    # 规格 6.1：异常时 payload 不含可信 contact_state_source=request
    def _boom(*args, **kwargs):
        raise RuntimeError("resolver boom")

    with patch(
        "app.services.ai_auto_reply_dry_run_service.resolve_contact_with_completion", _boom
    ):
        payload = _build_request_contact_state(
            db=None, latest_message="13800138000", merchant_id="m1",
            account_open_id="acc1", conversation_short_id="conv1",
            from_user_id="cust1", customer_memory=None,
        )
    # 异常降级：不伪装为可信 request
    assert payload.get("contact_state_source") != "request"
    # 不把 status=NONE 作为成功判断传入
    cs = payload.get("contact_state")
    if cs and cs.get("status") == "NONE":
        assert payload.get("contact_state_source") != "request"
    # 主链路不抛异常，payload 仍可构造
    assert isinstance(payload, dict)


def test_valid_phone_recovers_via_local_fallback_on_exception(monkeypatch):
    # 规格 6.2：有效手机号 + 9000 异常 → 9100 local_fallback → VALID
    def _boom(*args, **kwargs):
        raise RuntimeError("resolver boom")

    with patch(
        "app.services.ai_auto_reply_dry_run_service.resolve_contact_with_completion", _boom
    ):
        payload = _build_request_contact_state(
            db=None, latest_message="13800138000", merchant_id="m1",
            account_open_id="acc1", conversation_short_id="conv1",
            from_user_id="cust1", customer_memory=None,
        )
    state, action, source = _resolve(payload, "13800138000")
    assert state == "VALID"
    assert source == "local_fallback"


def test_partial_phone_recovers_via_local_fallback_on_exception(monkeypatch):
    # 规格 6.3：不完整号码 + 9000 异常 → 9100 local_fallback → PARTIAL
    def _boom(*args, **kwargs):
        raise RuntimeError("resolver boom")

    with patch(
        "app.services.ai_auto_reply_dry_run_service.resolve_contact_with_completion", _boom
    ):
        payload = _build_request_contact_state(
            db=None, latest_message="1770206", merchant_id="m1",
            account_open_id="acc1", conversation_short_id="conv1",
            from_user_id="cust1", customer_memory=None,
        )
    state, action, source = _resolve(
        payload, "1770206", contacts={"has_contact": False, "partial_phone": "1770206"},
    )
    assert state == "PARTIAL"
    assert source == "local_fallback"


def test_normal_request_priority_unchanged():
    # 规格 6.4：正常 request 优先级不受影响
    payload = {
        "contact_state": {
            "status": "VALID", "type": "mobile", "masked_value": "138****8000",
            "reason_code": "valid_mobile",
        },
        "contact_action": "CONFIRM_AND_CONVERT",
        "contact_state_source": "request",
    }
    state, action, source = _resolve(payload, "在吗", contacts={"has_contact": False, "partial_phone": None})
    assert state == "VALID"
    assert action == "CONFIRM_AND_CONVERT"
    assert source == "request"


def test_training_default_unchanged():
    # 规格 6.5：训练端默认不受影响
    payload = {
        "contact_state": {"status": "NONE"},
        "contact_action": "NONE",
        "contact_state_source": "training_default",
    }
    state, action, source = _resolve(payload, "你好")
    assert state == "NONE"
    assert source == "training_default"


def test_exception_path_no_plain_contact_in_payload(monkeypatch, caplog):
    # 规格 6.6：异常路径 payload/日志不含完整号码
    import logging

    def _boom(*args, **kwargs):
        raise RuntimeError("resolver boom with 13800138000")

    with patch(
        "app.services.ai_auto_reply_dry_run_service.resolve_contact_with_completion", _boom
    ):
        with caplog.at_level(logging.ERROR):
            payload = _build_request_contact_state(
                db=None, latest_message="我的号码13800138000", merchant_id="m1",
                account_open_id="acc1", conversation_short_id="conv1",
                from_user_id="cust1", customer_memory=None,
            )
    serialized = str(payload)
    assert "13800138000" not in serialized
    # 异常日志不含完整手机号（latest_message 含号码不应被记录）
    for record in caplog.records:
        assert "13800138000" not in record.getMessage()


def test_exception_does_not_block_payload_construction(monkeypatch):
    # 主链路不抛异常，payload 仍可继续构造
    def _boom(*args, **kwargs):
        raise RuntimeError("resolver boom")

    with patch(
        "app.services.ai_auto_reply_dry_run_service.resolve_contact_with_completion", _boom
    ):
        payload = _build_request_contact_state(
            db=None, latest_message="你好", merchant_id="m1",
            account_open_id="acc1", conversation_short_id="conv1",
            from_user_id="cust1", customer_memory=None,
        )
    assert isinstance(payload, dict)
