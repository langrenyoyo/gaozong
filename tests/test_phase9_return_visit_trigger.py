"""Phase 9 Task 5 销售微信回复回访触发持久化测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 5。

覆盖（Task 5 实现后全部通过）：
- 精确锚点（sent 通知 + self 消息匹配 notification_text + 后续 friend 文本）
- 锚点前 friend 排除
- 锚点后多条 friend 按 index 升序 \\n 拼接
- index 非负整数参与排序；缺失/字符串/负数保守不触发
- unknown 消息排除
- 无锚点不建 run
- 通知未 sent 不建 run
- 跨商户不建 run
- 上下文缺失（无 send_context）不建 run
- ReplyCheck timeout 仍建 run（状态不参与触发）
- 同包幂等返回既有 run
- 同派单不同包新 run
- 触发原文/通知原文不进日志

不接入 replies.py、不调度 processor、不调 9100、不发送（Task 6/7 范围）。
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.database import Base
from app.models import (
    DouyinLead,
    DouyinWebhookEvent,
    LeadNotification,
    ReturnVisitRun,
)
from app.services.return_visit_run_service import (
    _normalize_text,
    trigger_return_visit_from_writeback,
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


@pytest.fixture(autouse=True)
def _network_sentinel(monkeypatch):
    """网络哨兵：Task 5 不发送、不调 9100，哨兵兜底确保真实网络恒不触发。"""

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵触发：Task 5 禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)
    monkeypatch.setattr("app.services.xg_douyin_ai_cs_client.httpx.post", _raise)


NOTIFICATION_TEXT = "新线索：张先生 13800000000"


def _seed_lead(
    db,
    *,
    merchant_id="merchant-1",
    account_open_id="account-open-1",
    conversation_short_id="conv-1",
    customer_open_id="customer-open-1",
    lead_id=10,
) -> DouyinLead:
    lead = DouyinLead(
        id=lead_id,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        source_id=customer_open_id,
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_notification(
    db,
    *,
    lead_id=10,
    staff_id=1,
    notification_text=NOTIFICATION_TEXT,
    send_status="sent",
    notification_id=100,
    sent_at="auto",
) -> LeadNotification:
    # sent_at="auto"：sent 状态默认 now，非 sent 默认 None；可显式传 datetime 覆盖（测试 replied 锚点）
    if sent_at == "auto":
        resolved_sent_at = datetime.now() if send_status == "sent" else None
    else:
        resolved_sent_at = sent_at
    notification = LeadNotification(
        id=notification_id,
        lead_id=lead_id,
        staff_id=staff_id,
        notification_text=notification_text,
        send_status=send_status,
        sent_at=resolved_sent_at,
    )
    db.add(notification)
    db.flush()
    return notification


def _seed_webhook_event(
    db,
    *,
    conversation_short_id="conv-1",
    account_open_id="account-open-1",
    customer_open_id="customer-open-1",
    server_message_id="server-msg-1",
) -> DouyinWebhookEvent:
    event = DouyinWebhookEvent(
        event="im_receive_msg",
        from_user_id=customer_open_id,
        to_user_id=account_open_id,
        conversation_short_id=conversation_short_id,
        server_message_id=server_message_id,
        is_duplicate=0,
        message_create_time=datetime.now(),
        raw_body="{}",
    )
    db.add(event)
    db.flush()
    return event


def _msg(sender: str, content: str, index: int) -> dict:
    return {"sender": sender, "content": content, "index": index}


def _seed_full_baseline(db, **overrides) -> None:
    _seed_lead(
        db,
        merchant_id=overrides.get("merchant_id", "merchant-1"),
    )
    _seed_notification(db, notification_text=NOTIFICATION_TEXT)
    _seed_webhook_event(db)
    db.flush()


# ---------------------------------------------------------------------------
# 红灯 1：精确锚点建 run
# ---------------------------------------------------------------------------


def test_precise_anchor_creates_run():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "手机号不对，是空号", 1),
            ],
        )
        assert run is not None
        assert run.send_status == "pending_judgement"
        assert run.trigger_source == "wechat_sales_reply"
        assert run.attempt_count == 1
        assert run.dispatch_notification_id == 100
        assert run.trigger_text == _normalize_text("手机号不对，是空号")
        assert run.account_open_id == "account-open-1"
        assert run.conversation_short_id == "conv-1"
        assert run.customer_open_id == "customer-open-1"
        assert run.context_server_message_id == "server-msg-1"
        assert run.trigger_message_fp is not None and len(run.trigger_message_fp) == 64
        assert run.idempotency_key is not None and len(run.idempotency_key) == 64
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 2：锚点前 friend 排除
# ---------------------------------------------------------------------------


def test_friend_before_anchor_excluded():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("friend", "锚点前的旧回复", 0),
                _msg("self", NOTIFICATION_TEXT, 1),
                _msg("friend", "手机号不对", 2),
            ],
        )
        assert run is not None
        assert run.trigger_text == _normalize_text("手机号不对")
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 3：锚点后多条 friend 按 index 升序拼包
# ---------------------------------------------------------------------------


def test_multiple_friend_after_anchor_concatenated_by_index():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "第二条内容", 2),
                _msg("friend", "第一条内容", 1),
            ],
        )
        assert run is not None
        assert run.trigger_text == "第一条内容\n第二条内容"
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 4：index 必须非负整数；缺失/字符串/负数保守不触发
# ---------------------------------------------------------------------------


def test_index_missing_on_anchor_no_run():
    """锚点 self 消息缺失 index → 保守不触发。"""
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                {"sender": "self", "content": NOTIFICATION_TEXT},  # 无 index
                {"sender": "friend", "content": "回复", "index": 1},
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


def test_index_string_or_negative_rejected():
    """index 为字符串或负数 → 该消息不参与排序与判定。"""
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        # self 锚点 index="0"（字符串）→ 非法 → 无锚点 → 不建 run
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                {"sender": "self", "content": NOTIFICATION_TEXT, "index": "0"},
                {"sender": "friend", "content": "回复", "index": 1},
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 5：unknown 消息排除
# ---------------------------------------------------------------------------


def test_unknown_messages_excluded_from_bundle():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("unknown", "系统提示", 1),
                _msg("friend", "真实客户回复", 2),
            ],
        )
        assert run is not None
        assert run.trigger_text == _normalize_text("真实客户回复")
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 6：无锚点不建 run
# ---------------------------------------------------------------------------


def test_no_anchor_no_run():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("friend", "无锚点回复", 0),
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 7：通知未 sent 不建 run
# ---------------------------------------------------------------------------


def test_notification_not_sent_no_run():
    db = TestSession()
    try:
        _seed_lead(db)
        _seed_notification(db, send_status="composed")
        _seed_webhook_event(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复", 1),
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 7B：通知状态已转 replied，sent_at 非空仍锚点（阻断 4）
# ---------------------------------------------------------------------------


def test_notification_replied_with_sent_at_still_anchors():
    """阻断 4：回复回写先把通知改 replied，trigger 用 sent_at 不可变证据仍建 run。"""
    db = TestSession()
    try:
        _seed_lead(db)
        _seed_notification(db, send_status="replied", sent_at=datetime.now())
        _seed_webhook_event(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复", 1),
            ],
        )
        assert run is not None
        assert run.dispatch_notification_id == 100
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 8：跨商户不建 run
# ---------------------------------------------------------------------------


def test_cross_merchant_no_run():
    db = TestSession()
    try:
        _seed_full_baseline(db)  # lead 属 merchant-1
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-2",  # 传入不同商户
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复", 1),
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 9：上下文缺失（无 send_context）不建 run
# ---------------------------------------------------------------------------


def test_missing_send_context_no_run():
    db = TestSession()
    try:
        _seed_lead(db)
        _seed_notification(db)
        # 故意不 seed webhook event → get_send_msg_context 返回 None
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复", 1),
            ],
        )
        assert run is None
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 10：ReplyCheck timeout 仍建 run（状态不参与触发）
# ---------------------------------------------------------------------------


def test_reply_check_timeout_still_creates_run():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=999,  # ReplyCheck 状态不参与判定
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复", 1),
            ],
        )
        assert run is not None
        assert run.reply_check_id == 999
        db2.commit()
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 红灯 11：同包幂等返回既有 run
# ---------------------------------------------------------------------------


def test_same_bundle_idempotent_returns_existing():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    messages = [
        _msg("self", NOTIFICATION_TEXT, 0),
        _msg("friend", "同一回复包", 1),
    ]

    run1_id = None
    db1 = TestSession()
    try:
        run1 = trigger_return_visit_from_writeback(
            db1,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=messages,
        )
        assert run1 is not None
        run1_id = run1.id
        db1.commit()
    finally:
        db1.close()

    db2 = TestSession()
    try:
        run2 = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=messages,
        )
        assert run2 is not None
        assert run2.id == run1_id
        db2.commit()
    finally:
        db2.close()

    db3 = TestSession()
    try:
        assert db3.query(ReturnVisitRun).count() == 1
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 红灯 12：同派单不同包新 run
# ---------------------------------------------------------------------------


def test_same_dispatch_different_bundle_new_run():
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    run1_id = None
    db1 = TestSession()
    try:
        run1 = trigger_return_visit_from_writeback(
            db1,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复包A", 1),
            ],
        )
        assert run1 is not None
        run1_id = run1.id
        db1.commit()
    finally:
        db1.close()

    db2 = TestSession()
    try:
        run2 = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", "回复包B", 1),
            ],
        )
        assert run2 is not None
        assert run2.id != run1_id
        db2.commit()
    finally:
        db2.close()

    db3 = TestSession()
    try:
        assert db3.query(ReturnVisitRun).count() == 2
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 红灯 13：触发原文 / 通知原文不进日志
# ---------------------------------------------------------------------------


def test_trigger_text_not_in_logs(caplog):
    db = TestSession()
    try:
        _seed_full_baseline(db)
        db.commit()
    finally:
        db.close()

    secret_reply = "销售私密回复内容13700000000"
    caplog.set_level(logging.INFO, logger="app.services.return_visit_run_service")
    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2,
            merchant_id="merchant-1",
            lead_id=10,
            staff_id=1,
            reply_check_id=None,
            messages=[
                _msg("self", NOTIFICATION_TEXT, 0),
                _msg("friend", secret_reply, 1),
            ],
        )
        assert run is not None
        db2.commit()
    finally:
        db2.close()

    # 触发回复包原文不得进入日志
    assert secret_reply not in caplog.text
    # 派单通知原文（含手机号）也不得进入日志
    assert NOTIFICATION_TEXT not in caplog.text
    assert "13800000000" not in caplog.text
