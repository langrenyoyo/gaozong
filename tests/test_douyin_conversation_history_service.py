"""抖音私信会话历史上下文服务测试（R2）。

覆盖 build_reply_conversation_context 的 LLM 上下文独立脱敏与商户隔离：
- LLM 上下文（conversation_history/latest_message/customer_memory）不含原始手机号/微信号；
- 脱敏异常时阻断，不把原文返回给模型；
- 回复链路传可信 merchant_id，账号不属于当前商户时阻断。
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinAuthorizedAccount, DouyinWebhookEvent
from app.services.douyin_conversation_history_service import (
    build_conversation_history,
    build_reply_conversation_context,
)
from app.services.douyin_workbench_conversation_service import (
    AccountAccessError,
    AccountMerchantDeniedError,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _db():
    return TestSession()


def _insert_account(open_id, merchant_id, bind_status=1):
    db = _db()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=1, open_id=open_id, merchant_id=merchant_id,
            bind_status=bind_status, account_name=open_id,
        ))
        db.commit()
    finally:
        db.close()


def _insert_event(*, account_open_id, customer_open_id, text, conversation_short_id, merchant_id, event_key, event="im_receive_msg"):
    db = _db()
    try:
        content = {"text": text, "conversation_short_id": conversation_short_id, "server_message_id": f"msg_{event_key}", "message_type": "text", "open_id": customer_open_id, "account_open_id": account_open_id}
        db.add(DouyinWebhookEvent(
            event=event,
            event_key=event_key,
            from_user_id=customer_open_id if event == "im_receive_msg" else account_open_id,
            to_user_id=account_open_id if event == "im_receive_msg" else customer_open_id,
            merchant_id=merchant_id,
            raw_body=json.dumps({"event": event, "content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()


def test_llm_context_masks_contacts_and_excludes_raw_values():
    """LLM 回复上下文不含原始手机号/微信号，只含脱敏值。"""
    _insert_account("acc_llm", "merchant-1")
    _insert_event(
        account_open_id="acc_llm", customer_open_id="cust_llm",
        text="我的手机号是13812345678 加微信 wx_llm_88",
        conversation_short_id="conv_llm", merchant_id="merchant-1", event_key="llm_evt",
    )
    db = _db()
    try:
        ctx = build_reply_conversation_context(
            db, merchant_id="merchant-1", account_open_id="acc_llm",
            conversation_key="conv_llm",
            latest_message="我的手机号是13812345678 加微信 wx_llm_88",
        )
    finally:
        db.close()
    blob = json.dumps(ctx.conversation_history, ensure_ascii=False) + (ctx.latest_message or "")
    assert "13812345678" not in blob
    assert "wx_llm_88" not in blob
    # customer_memory 只含脱敏值
    mem_blob = json.dumps(ctx.customer_memory, ensure_ascii=False)
    assert "13812345678" not in mem_blob
    assert "wx_llm_88" not in mem_blob


def test_llm_context_blocks_when_mask_fails():
    """脱敏异常时阻断，不向模型返回原文。"""
    from unittest.mock import patch
    _insert_account("acc_llm_fail", "merchant-1")
    _insert_event(
        account_open_id="acc_llm_fail", customer_open_id="cust_llm_fail",
        text="我的手机号是13812345678",
        conversation_short_id="conv_llm_fail", merchant_id="merchant-1", event_key="llm_fail_evt",
    )
    db = _db()
    try:
        with patch(
            "app.services.douyin_conversation_history_service.mask_contacts_in_text",
            side_effect=ValueError("forced"),
        ):
            with pytest.raises(Exception):
                build_reply_conversation_context(
                    db, merchant_id="merchant-1", account_open_id="acc_llm_fail",
                    conversation_key="conv_llm_fail",
                    latest_message="我的手机号是13812345678",
                )
    finally:
        db.close()


def test_reply_context_blocks_account_owned_by_other_merchant():
    """回复链路账号属于他商户 → 阻断。"""
    _insert_account("acc_other", "merchant-2")
    _insert_event(
        account_open_id="acc_other", customer_open_id="cust_other", text="hello",
        conversation_short_id="conv_other", merchant_id="merchant-2", event_key="other_evt",
    )
    db = _db()
    try:
        with pytest.raises(AccountMerchantDeniedError):
            build_reply_conversation_context(
                db, merchant_id="merchant-1", account_open_id="acc_other",
                conversation_key="conv_other", latest_message="你好",
            )
    finally:
        db.close()


def test_reply_context_blocks_unbound_account():
    """回复链路账号 bind_status!=1 → 阻断。"""
    _insert_account("acc_unbound", "merchant-1", bind_status=0)
    db = _db()
    try:
        with pytest.raises(AccountAccessError):
            build_reply_conversation_context(
                db, merchant_id="merchant-1", account_open_id="acc_unbound",
                conversation_key="conv_unbound", latest_message="你好",
            )
    finally:
        db.close()


def test_build_conversation_history_legacy_empty_merchant_blocks():
    """兼容旧入口缺少 merchant_id 时显式阻断，不读取任何事件/不跨商户查询。"""
    _insert_account("acc_legacy", "merchant-1")
    _insert_event(
        account_open_id="acc_legacy", customer_open_id="cust_legacy", text="hello history",
        conversation_short_id="conv_legacy", merchant_id="merchant-1", event_key="legacy_evt",
    )
    db = _db()
    try:
        # 缺少 merchant_id 必须阻断，不得执行跨商户查询
        with pytest.raises(ValueError):
            build_conversation_history(
                db, merchant_id="", account_open_id="acc_legacy",
                conversation_key="conv_legacy", latest_message="你好",
            )
        # 缺少 merchant_id 参数同样阻断
        with pytest.raises(TypeError):
            build_conversation_history(
                db, account_open_id="acc_legacy",
                conversation_key="conv_legacy", latest_message="你好",
            )
    finally:
        db.close()


def test_build_conversation_history_legacy_cannot_read_other_merchant_session():
    """兼容入口使用商户 A 时不能读取商户 B 会话（归属校验阻断）。"""
    _insert_account("acc_cross", "merchant-2")
    _insert_event(
        account_open_id="acc_cross", customer_open_id="cust_cross", text="hello cross",
        conversation_short_id="conv_cross", merchant_id="merchant-2", event_key="cross_evt",
    )
    db = _db()
    try:
        # 商户 A 读取商户 B 账号 → 归属校验阻断
        with pytest.raises(Exception):
            build_conversation_history(
                db, merchant_id="merchant-1", account_open_id="acc_cross",
                conversation_key="conv_cross", latest_message="你好",
            )
    finally:
        db.close()
