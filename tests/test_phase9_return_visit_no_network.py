"""Phase 9 Task 10 全阶段网络零调用证明。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 10。

4 哨兵默认抛错：
  - app.services.douyin_openapi_client.requests.post
  - app.services.xg_douyin_ai_cs_client.httpx.post
  - app.services.douyin_private_message_send_service.call_douyin_openapi
  - apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat

原则：终态用例在哨兵抛错下完成 process 且不触发任何哨兵 = 不触网；
      sent 用例仅用 call_douyin_openapi 局部受控替身，并断言恰好调用一次、其余三者零调用。
9100 判定经 get_xg_douyin_ai_cs_client 替身（不打网），真实网络恒 0。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
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
    DouyinWebhookEvent,
    LeadNotification,
    ReturnVisitPrompt,
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


def _network_guard(monkeypatch):
    """安装 4 哨兵（默认抛错）+ config 双开关 + SessionLocal 替身。"""

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵：禁止真实网络调用")

    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", True)
    monkeypatch.setattr("app.services.return_visit_run_service.SessionLocal", lambda: TestSession())
    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)
    monkeypatch.setattr("app.services.xg_douyin_ai_cs_client.httpx.post", _raise)
    monkeypatch.setattr("app.services.douyin_private_message_send_service.call_douyin_openapi", _raise)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", _raise)


# ---------------------------------------------------------------------------
# seed helpers（与 e2e 一致的最小子集）
# ---------------------------------------------------------------------------


def _seed_prompts(db) -> None:
    for key, text, fallback in [
        ("retain_contact_conversion", "模板_留资", "兜底_留资"),
        ("finance_plan_followup", "模板_金融", "兜底_金融"),
        ("silent_customer_wakeup", "模板_沉默", "兜底_沉默"),
    ]:
        db.add(
            ReturnVisitPrompt(
                prompt_key=key, name=key, template_text=text, fallback_message=fallback,
                confidence_threshold=0.90, enabled=True, scope="global", sort_order=0,
            )
        )
    db.flush()


def _seed_baseline(db) -> None:
    db.add(DouyinLead(id=10, merchant_id="merchant-1", account_open_id="account-open-1",
                     conversation_short_id="conv-1", source_id="customer-open-1"))
    db.add(DouyinAuthorizedAccount(merchant_id="merchant-1", main_account_id=1,
                                   open_id="account-open-1", bind_status=1))
    db.add(LeadNotification(id=100, lead_id=10, staff_id=1,
                           notification_text="新线索", send_status="sent", sent_at=datetime.now()))
    db.add(DouyinWebhookEvent(
        event="im_receive_msg", from_user_id="customer-open-1", to_user_id="account-open-1",
        conversation_short_id="conv-1", server_message_id="server-msg-1", is_duplicate=0,
        message_create_time=datetime.now(), raw_body="{}",
    ))
    db.add(AutoReplyRolloutConfig(scope="global", merchant_id=None, auto_reply_enabled=True,
                                  real_send_enabled=True, allow_full_rollout=True))
    db.flush()


_MESSAGES = [
    {"sender": "self", "content": "新线索", "index": 0},
    {"sender": "friend", "content": "手机号不对", "index": 1},
]


def _trigger() -> int:
    """建基线 + trigger，返回 run_id（trigger 不触网）。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        _seed_baseline(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        run = trigger_return_visit_from_writeback(
            db2, merchant_id="merchant-1", lead_id=10, staff_id=1,
            reply_check_id=None, messages=_MESSAGES,
        )
        assert run is not None
        run_id = run.id
        db2.commit()
    finally:
        db2.close()
    return run_id


class _Stub9100:
    def __init__(self, judgment: dict):
        self.judgment = judgment

    def judge_return_visit(self, request: dict) -> dict:
        return self.judgment


def _patch_9100(monkeypatch, judgment: dict) -> _Stub9100:
    stub = _Stub9100(judgment)
    monkeypatch.setattr("app.services.return_visit_run_service.get_xg_douyin_ai_cs_client", lambda: stub)
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


# ---------------------------------------------------------------------------
# 触发不触网
# ---------------------------------------------------------------------------


def test_trigger_return_visit_no_network(monkeypatch):
    """trigger 仅写 DB，4 哨兵抛错下仍成功建 run。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    assert run_id > 0


# ---------------------------------------------------------------------------
# 终态用例：哨兵抛错下完成 process 且不触发 = 不触网
# ---------------------------------------------------------------------------


def test_terminal_blocked_no_network(monkeypatch):
    """注入/拒答 → blocked，不兜底、不触网（不调 OpenAPI）。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    _patch_9100(monkeypatch, _judgment(
        judgement_result="blocked", prompt_key=None, confidence=0.0,
        risk_flags=["prompt_injection", "model_refusal"], should_trigger=False, suggested_message=None,
    ))
    process_return_visit_run(run_id)  # 哨兵抛错下完成 = 不触网

    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "blocked"
    finally:
        db.close()


def test_terminal_not_needed_no_network(monkeypatch):
    """已联系上 → suppress_hit/not_needed，不触网。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    _patch_9100(monkeypatch, _judgment(
        judgement_result="suppress_hit", prompt_key=None, confidence=0.0, suggested_message=None,
    ))
    process_return_visit_run(run_id)

    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db.close()


def test_terminal_confidence_low_no_network(monkeypatch):
    """低置信 → confidence_low，不触网。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    _patch_9100(monkeypatch, _judgment(confidence=0.30, suggested_message="低置信话术"))
    process_return_visit_run(run_id)

    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "confidence_low"
    finally:
        db.close()


def test_keyword_fallback_no_network(monkeypatch):
    """9100 技术故障降级为关键词兜底但未命中 → not_needed，不触网（不进发送）。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    _patch_9100(monkeypatch, _judgment(
        judgement_source="keyword_fallback", prompt_key=None,
        judgement_result="no_match", confidence=0.0, should_trigger=False, suggested_message=None,
    ))
    process_return_visit_run(run_id)

    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# sent 用例：仅 call_douyin_openapi 局部替身，断言恰好一次、其余零调用
# ---------------------------------------------------------------------------


def test_sent_uses_only_local_openapi_stub(monkeypatch):
    """sent 仅经 call_douyin_openapi 局部替身一次；requests/httpx/OpenAICompatibleClient 零调用。"""
    _network_guard(monkeypatch)
    run_id = _trigger()
    _patch_9100(monkeypatch, _judgment())

    call_count = {"n": 0}

    def _openapi_stub(*args, **kwargs):
        call_count["n"] += 1
        return {"payload": {"data": {"msg_id": "up-net-sent-1"}}}

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        side_effect=_openapi_stub,
    ):
        process_return_visit_run(run_id)

    # 其余 3 哨兵仍抛错（_network_guard），若被调用测试早已失败
    assert call_count["n"] == 1

    db = TestSession()
    try:
        assert db.get(ReturnVisitRun, run_id).send_status == "sent"
    finally:
        db.close()
