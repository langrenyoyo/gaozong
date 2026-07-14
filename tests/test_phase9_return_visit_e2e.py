"""Phase 9 Task 6 回访 run 端到端全替身测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 6。

E2E 从 trigger 入口串到 process 终态，验证：
- happy path：sent 派单通知 + UI index 消息 + 9100 判定替身 + OpenAPI 成功桩 → 单行 run + 单行流水 + sent。
- 抑制（suppress_hit）→ not_needed，不发送。
- 低置信（G9 LLM 阈值未过）→ confidence_low，不发送。
- disabled（G1 config 关）→ prompt_disabled。
- rate_limited（G6 超额）→ rate_limited。
- send_unknown（网络/非法错误）→ send_unknown，永不重发。
- 并发幂等：同包两次 trigger → 单 run，process 一次。

全部替身：9100 判定 / 抖音 OpenAPI 成功桩 / 网络哨兵，真实网络恒 0。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app import config
from app.database import Base
from app.models import (
    AutoReplyRolloutConfig,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    LeadNotification,
    ReturnVisitRun,
)
from app.services.return_visit_run_service import (
    process_return_visit_run,
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
def _patch_env(monkeypatch):
    """config 双开关开 + SessionLocal 替身 + 网络哨兵（未打桩即失败）。"""
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", True)
    monkeypatch.setattr("app.services.return_visit_run_service.SessionLocal", lambda: TestSession())

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵：未打桩 call_douyin_openapi，禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)
    monkeypatch.setattr("app.services.xg_douyin_ai_cs_client.httpx.post", _raise)


NOTIFICATION_TEXT = "新线索：张先生 13800000000"


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------


def _seed_lead(db, *, merchant_id="merchant-1", lead_id=10) -> DouyinLead:
    lead = DouyinLead(
        id=lead_id,
        merchant_id=merchant_id,
        account_open_id="account-open-1",
        conversation_short_id="conv-1",
        source_id="customer-open-1",
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_authorized_account(db, *, merchant_id="merchant-1", open_id="account-open-1") -> DouyinAuthorizedAccount:
    """G3 授权账号当前归属（阻断 1）。"""
    account = DouyinAuthorizedAccount(
        merchant_id=merchant_id,
        main_account_id=1,
        open_id=open_id,
        bind_status=1,
    )
    db.add(account)
    db.flush()
    return account


def _seed_notification(db, *, lead_id=10, staff_id=1, notification_id=100) -> LeadNotification:
    notification = LeadNotification(
        id=notification_id,
        lead_id=lead_id,
        staff_id=staff_id,
        notification_text=NOTIFICATION_TEXT,
        send_status="sent",
        sent_at=datetime.now(),
    )
    db.add(notification)
    db.flush()
    return notification


def _seed_rollout(db, *, real_send_enabled=True) -> AutoReplyRolloutConfig:
    row = AutoReplyRolloutConfig(
        scope="global",
        merchant_id=None,
        auto_reply_enabled=True,
        real_send_enabled=real_send_enabled,
        allow_full_rollout=True,
    )
    db.add(row)
    db.flush()
    return row


def _seed_webhook_event(db) -> DouyinWebhookEvent:
    event = DouyinWebhookEvent(
        event="im_receive_msg",
        from_user_id="customer-open-1",
        to_user_id="account-open-1",
        conversation_short_id="conv-1",
        server_message_id="server-msg-1",
        is_duplicate=0,
        message_create_time=datetime.now(),
        raw_body="{}",
    )
    db.add(event)
    db.flush()
    return event


def _seed_baseline(db, *, rollout=True) -> None:
    _seed_lead(db)
    _seed_authorized_account(db)  # G3 授权账号当前归属（阻断 1）
    _seed_notification(db)
    _seed_webhook_event(db)
    if rollout:
        _seed_rollout(db, real_send_enabled=True)
    db.flush()


def _seed_hourly_send(db, suffix: str) -> None:
    """G6 限频计数：1h 内 ai_auto/return_visit_auto 已发送流水（status=sent + sent_at）。"""
    send = DouyinPrivateMessageSend(
        main_account_id="main-1",
        conversation_short_id="conv-1",
        server_message_id=f"server-seed-{suffix}",
        from_user_id="account-open-1",
        to_user_id="customer-open-1",
        customer_open_id="customer-open-1",
        account_open_id="account-open-1",
        scene="im_receive_msg",
        content="历史自动消息",
        request_body_json="{}",
        status="sent",
        manual_confirmed=0,
        auto_send=1,
        send_source="ai_auto",
        sent_at=datetime.now(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(send)
    db.flush()


class _Stub9100:
    def __init__(self, judgment: dict):
        self.judgment = judgment

    def judge_return_visit(self, request: dict) -> dict:
        return self.judgment


def _patch_9100(monkeypatch, judgment: dict) -> _Stub9100:
    stub = _Stub9100(judgment)
    monkeypatch.setattr(
        "app.services.return_visit_run_service.get_xg_douyin_ai_cs_client",
        lambda: stub,
    )
    return stub


def _judgment(**overrides) -> dict:
    base = {
        "prompt_key": "retain_contact_conversion",
        "confidence": 0.95,
        "should_trigger": True,
        "suggested_message": "请重新发送一个常用联系方式",
        "judgement_source": "llm",
        "judgement_result": "retain_contact_conversion",
        "model": "test-model",
        "risk_flags": [],
        "ambiguous": False,
    }
    base.update(overrides)
    return base


_MESSAGES = [
    {"sender": "self", "content": NOTIFICATION_TEXT, "index": 0},
    {"sender": "friend", "content": "手机号不对", "index": 1},
]


def _trigger_and_process(
    monkeypatch,
    *,
    judgment: dict,
    openapi_side_effect=None,
    openapi_return=None,
) -> int:
    """trigger（建 run）+ process（9100 替身 + OpenAPI 桩），返回 run_id。"""
    db = TestSession()
    try:
        _seed_baseline(db)
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
            messages=_MESSAGES,
        )
        assert run is not None
        run_id = run.id
        db2.commit()
    finally:
        db2.close()

    _patch_9100(monkeypatch, judgment)
    patch_target = "app.services.douyin_private_message_send_service.call_douyin_openapi"
    if openapi_side_effect is not None:
        with patch(patch_target, side_effect=openapi_side_effect):
            process_return_visit_run(run_id)
    else:
        ret = openapi_return if openapi_return is not None else {"payload": {"data": {"msg_id": "up-e2e-1"}}}
        with patch(patch_target, return_value=ret):
            process_return_visit_run(run_id)
    return run_id


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_e2e_happy_path_sent(monkeypatch):
    run_id = _trigger_and_process(monkeypatch, judgment=_judgment())

    db = TestSession()
    try:
        assert db.query(ReturnVisitRun).count() == 1
        done = db.get(ReturnVisitRun, run_id)
        assert done.send_status == "sent"
        sends = db.query(DouyinPrivateMessageSend).filter(
            DouyinPrivateMessageSend.return_visit_run_id == run_id
        ).all()
        assert len(sends) == 1
        assert sends[0].status == "sent"
        assert sends[0].send_source == "return_visit_auto"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 抑制
# ---------------------------------------------------------------------------


def test_e2e_suppress_hit_not_needed(monkeypatch):
    run_id = _trigger_and_process(
        monkeypatch,
        judgment=_judgment(
            judgement_result="suppress_hit",
            prompt_key=None,
            confidence=0.0,
            suggested_message=None,
        ),
    )
    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "not_needed"
        assert db.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 低置信（G9）
# ---------------------------------------------------------------------------


def test_e2e_confidence_low(monkeypatch):
    run_id = _trigger_and_process(
        monkeypatch,
        judgment=_judgment(confidence=0.30, suggested_message="低置信话术"),
    )
    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "confidence_low"
        assert db.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# disabled（G1）
# ---------------------------------------------------------------------------


def test_e2e_config_disabled_blocked(monkeypatch):
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_ENABLED", False)
    run_id = _trigger_and_process(monkeypatch, judgment=_judgment())
    db = TestSession()
    try:
        # FIX2：G1 config 熔断落 blocked（设计文档 line 405）
        assert db.get(ReturnVisitRun, run_id).send_status == "blocked"
        assert db.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# rate_limited（G6）
# ---------------------------------------------------------------------------


def test_e2e_rate_limited(monkeypatch):
    # 把 G6 上限压到 2，再 seed 2 行历史 ai_auto 发送 → count(2) >= limit(2)
    monkeypatch.setattr(
        "app.services.return_visit_run_service._hourly_send_limit", lambda *a, **kw: 2
    )

    db = TestSession()
    try:
        _seed_baseline(db)
        _seed_hourly_send(db, "a")
        _seed_hourly_send(db, "b")
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
            messages=_MESSAGES,
        )
        assert run is not None
        run_id = run.id
        db2.commit()
    finally:
        db2.close()

    _patch_9100(monkeypatch, _judgment())
    process_return_visit_run(run_id)

    db3 = TestSession()
    try:
        assert db3.get(ReturnVisitRun, run_id).send_status == "rate_limited"
        # 本 run 不应新建发送流水（seed 的 2 行是历史 ai_auto）
        new_sends = db3.query(DouyinPrivateMessageSend).filter(
            DouyinPrivateMessageSend.send_source == "return_visit_auto"
        ).all()
        assert len(new_sends) == 0
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# send_unknown（网络/非法错误，永不重发）
# ---------------------------------------------------------------------------


def test_e2e_send_unknown(monkeypatch):
    run_id = _trigger_and_process(
        monkeypatch,
        judgment=_judgment(),
        openapi_side_effect=HTTPException(
            status_code=502, detail={"error_code": "invalid_upstream_json"}
        ),
    )
    db = TestSession()
    try:
        done = db.get(ReturnVisitRun, run_id)
        assert done.send_status == "send_unknown"
        sends = db.query(DouyinPrivateMessageSend).filter(
            DouyinPrivateMessageSend.return_visit_run_id == run_id
        ).all()
        assert len(sends) == 1
        assert sends[0].status == "failed"  # 底层 send service 记 failed，run 记 send_unknown
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 并发幂等：同包两次 trigger → 单 run，process 一次
# ---------------------------------------------------------------------------


def test_e2e_trigger_idempotent_single_process(monkeypatch):
    db = TestSession()
    try:
        _seed_baseline(db)
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
            messages=_MESSAGES,
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
            messages=_MESSAGES,
        )
        assert run2 is not None
        assert run2.id == run1_id
        db2.commit()
    finally:
        db2.close()

    _patch_9100(monkeypatch, _judgment())
    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "up-e2e-idem"}}},
    ):
        process_return_visit_run(run1_id)

    db3 = TestSession()
    try:
        assert db3.query(ReturnVisitRun).count() == 1
        assert db3.get(ReturnVisitRun, run1_id).send_status == "sent"
        assert db3.query(DouyinPrivateMessageSend).filter(
            DouyinPrivateMessageSend.return_visit_run_id == run1_id
        ).count() == 1
    finally:
        db3.close()
