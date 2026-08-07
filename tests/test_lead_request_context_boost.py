"""LEAD_REQUEST 上下文增强（任务 2.4）单元测试。

验证：① is_lead_request_message 关键词检测；② _has_recent_lead_request 紧前 AI 出站消息查询；
③ context_boost 默认 False 不影响现有；④ 窗口扩展（5→10 分钟）；⑤ 失败降级 False。
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.contact_extractor import is_lead_request_message


# ---- is_lead_request_message ----

@pytest.mark.parametrize("text,expected", [
    ("方便留个手机号吗", True),
    ("留个联系方式吧", True),
    ("加我微信", True),
    ("怎么联系您", True),
    ("发我您的电话", True),
    ("老板您看的是奥迪A6", False),  # 需求确认，非留资引导
    ("", False),
    (None, False),
])
def test_is_lead_request_message(text, expected):
    assert is_lead_request_message(text) is expected


# ---- _has_recent_lead_request ----

def test_has_recent_lead_request_true_when_ai_message_has_keyword():
    """紧前 AI 出站消息含留资关键词 → True。用真实 in-memory SQLite。"""
    from app.database import SessionLocal
    from app.models import DouyinPrivateMessageSend
    from app.integrations.douyin_webhook import _has_recent_lead_request

    db = SessionLocal()
    try:
        now = datetime.now()
        ai_time = now - timedelta(minutes=2)
        row = DouyinPrivateMessageSend(
            main_account_id=1, conversation_short_id="conv", server_message_id="msg1",
            from_user_id="acc", to_user_id="cust", customer_open_id="cust", account_open_id="acc",
            scene="im_reply_msg", content="方便留个手机号吗", status="sent",
            send_source="ai_auto", created_at=ai_time,
        )
        db.add(row)
        db.commit()
        result = _has_recent_lead_request(
            db, account_open_id="acc", conversation_short_id="conv",
            customer_open_id="cust", customer_message_time=now,
        )
        assert result is True
    finally:
        db.query(DouyinPrivateMessageSend).delete()
        db.commit()
        db.close()


def test_has_recent_lead_request_false_when_no_ai_message():
    """无 AI 出站消息 → False。"""
    from app.database import SessionLocal
    from app.models import DouyinPrivateMessageSend
    from app.integrations.douyin_webhook import _has_recent_lead_request

    db = SessionLocal()
    try:
        result = _has_recent_lead_request(
            db, account_open_id="acc", conversation_short_id="conv_none",
            customer_open_id="cust", customer_message_time=datetime.now(),
        )
        assert result is False
    finally:
        db.close()


def test_has_recent_lead_request_false_when_ai_message_no_keyword():
    """紧前 AI 出站消息不含留资关键词 → False。"""
    from app.database import SessionLocal
    from app.models import DouyinPrivateMessageSend
    from app.integrations.douyin_webhook import _has_recent_lead_request

    db = SessionLocal()
    try:
        now = datetime.now()
        ai_time = now - timedelta(minutes=2)
        row = DouyinPrivateMessageSend(
            main_account_id=1, conversation_short_id="conv2", server_message_id="msg2",
            from_user_id="acc", to_user_id="cust", customer_open_id="cust", account_open_id="acc",
            scene="im_reply_msg", content="奥迪A6比较受欢迎", status="sent",
            send_source="ai_auto", created_at=ai_time,
        )
        db.add(row)
        db.commit()
        result = _has_recent_lead_request(
            db, account_open_id="acc", conversation_short_id="conv2",
            customer_open_id="cust", customer_message_time=now,
        )
        assert result is False
    finally:
        db.query(DouyinPrivateMessageSend).filter(DouyinPrivateMessageSend.conversation_short_id == "conv2").delete()
        db.commit()
        db.close()


def test_has_recent_lead_request_false_when_outside_window():
    """AI 出站消息超过 5 分钟窗口 → False。"""
    from app.database import SessionLocal
    from app.models import DouyinPrivateMessageSend
    from app.integrations.douyin_webhook import _has_recent_lead_request

    db = SessionLocal()
    try:
        now = datetime.now()
        ai_time = now - timedelta(minutes=7)
        row = DouyinPrivateMessageSend(
            main_account_id=1, conversation_short_id="conv3", server_message_id="msg3",
            from_user_id="acc", to_user_id="cust", customer_open_id="cust", account_open_id="acc",
            scene="im_reply_msg", content="方便留个手机号吗", status="sent",
            send_source="ai_auto", created_at=ai_time,
        )
        db.add(row)
        db.commit()
        result = _has_recent_lead_request(
            db, account_open_id="acc", conversation_short_id="conv3",
            customer_open_id="cust", customer_message_time=now,
        )
        assert result is False
    finally:
        db.query(DouyinPrivateMessageSend).filter(DouyinPrivateMessageSend.conversation_short_id == "conv3").delete()
        db.commit()
        db.close()


def test_has_recent_lead_request_degrades_to_false_on_exception():
    """查询异常 → 保守返回 False。"""
    from app.integrations.douyin_webhook import _has_recent_lead_request

    mock_db = MagicMock()
    mock_db.query.side_effect = RuntimeError("db error")
    result = _has_recent_lead_request(
        mock_db, account_open_id="acc", conversation_short_id="conv",
        customer_open_id="cust", customer_message_time=datetime.now(),
    )
    assert result is False


def test_has_recent_lead_request_false_when_missing_params():
    """缺 account_open_id/conversation_short_id/customer_open_id/time → False。"""
    from app.integrations.douyin_webhook import _has_recent_lead_request

    mock_db = MagicMock()
    assert _has_recent_lead_request(mock_db, account_open_id="", conversation_short_id="c",
                                     customer_open_id="x", customer_message_time=datetime.now()) is False
    assert _has_recent_lead_request(mock_db, account_open_id="a", conversation_short_id="",
                                     customer_open_id="x", customer_message_time=datetime.now()) is False


# ---- context_boost 窗口扩展 ----

def test_combine_recent_customer_text_context_boost_doubles_window():
    """context_boost=True 时拼接窗口翻倍（300→600 秒）。"""
    invalid_state = MagicMock()
    invalid_state.status = "NONE"
    invalid_state.normalized_value = None
    with patch("app.integrations.douyin_webhook._env_int") as mock_env, \
         patch("app.integrations.douyin_webhook.analyze_contact_state") as mock_analyze, \
         patch("app.integrations.douyin_webhook._collect_recent_customer_fragments", return_value=[]) as mock_collect, \
         patch("app.services.contact_completion_resolver.resolve_contact_with_completion",
               return_value=("", invalid_state)):
        # _env_int 第一次返回 300（window），第二次返回 3（max_messages）
        mock_env.side_effect = [300, 3]
        mock_state = MagicMock()
        mock_state.status = "PARTIAL"
        mock_analyze.return_value = mock_state
        from app.integrations.douyin_webhook import _combine_recent_customer_text
        _combine_recent_customer_text(
            MagicMock(), "1770206", "acc", "conv", "cust", merchant_id="m1",
            context_boost=True,
        )
    # 验证传给 _collect_recent_customer_fragments 的 window_seconds=600（翻倍）
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["window_seconds"] == 600


def test_combine_recent_customer_text_default_window_not_doubled():
    """context_boost=False（默认）时窗口=300 不翻倍。"""
    invalid_state = MagicMock()
    invalid_state.status = "NONE"
    invalid_state.normalized_value = None
    with patch("app.integrations.douyin_webhook._env_int") as mock_env, \
         patch("app.integrations.douyin_webhook.analyze_contact_state") as mock_analyze, \
         patch("app.integrations.douyin_webhook._collect_recent_customer_fragments", return_value=[]) as mock_collect, \
         patch("app.services.contact_completion_resolver.resolve_contact_with_completion",
               return_value=("", invalid_state)):
        mock_env.side_effect = [300, 3]
        mock_state = MagicMock()
        mock_state.status = "PARTIAL"
        mock_analyze.return_value = mock_state
        from app.integrations.douyin_webhook import _combine_recent_customer_text
        _combine_recent_customer_text(
            MagicMock(), "1770206", "acc", "conv", "cust", merchant_id="m1",
        )
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["window_seconds"] == 300
