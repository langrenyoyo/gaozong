"""Phase 9 Task 6 process_return_visit_run 统一处理入口测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 6。

覆盖：
- 原子 claim：仅 pending_judgement → processing；终态/已被 claim 直接返回。
- 判定终态映射：no_match/ambiguous/suppress_hit → not_needed；below_threshold → confidence_low；
  disabled → prompt_disabled；risk（含拒答）→ blocked。
- G1 config 双开关；G2 global rollout real_send_enabled。
- 发送分类：code=0 → sent；upstream_business_error → failed；网络/非法 → send_unknown（永不重发）。
- 自行创建并关闭 DB Session（SessionLocal 替身）。
- 9100 判定 / 抖音 OpenAPI 全替身，真实网络恒 0。

不验证管理端（Task 8）、不验证崩溃恢复（Task 7）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    ReturnVisitPrompt,
    ReturnVisitRun,
)
from app.services.return_visit_run_service import process_return_visit_run


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
    """默认 config 双开关开 + SessionLocal 替身 + 网络哨兵（未打桩即失败）。"""
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", True)
    monkeypatch.setattr("app.services.return_visit_run_service.SessionLocal", lambda: TestSession())

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵：未打桩 call_douyin_openapi，禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)
    monkeypatch.setattr("app.services.xg_douyin_ai_cs_client.httpx.post", _raise)


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------


def _seed_prompts(db) -> None:
    for key, text, fallback in [
        ("retain_contact_conversion", "模板_留资", "兜底_留资"),
        ("finance_plan_followup", "模板_金融", "兜底_金融"),
        ("silent_customer_wakeup", "模板_沉默", "兜底_沉默"),
    ]:
        db.add(
            ReturnVisitPrompt(
                prompt_key=key,
                name=key,
                template_text=text,
                fallback_message=fallback,
                confidence_threshold=0.90,
                enabled=True,
                scope="global",
                sort_order=0,
            )
        )
    db.flush()


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


def _seed_authorized_account(db, *, merchant_id="merchant-1", open_id="account-open-1", bind_status=1) -> DouyinAuthorizedAccount:
    """G3 授权账号当前归属（阻断 1：account_open_id 绑定 merchant_id 且 bind_status=1）。"""
    account = DouyinAuthorizedAccount(
        merchant_id=merchant_id,
        main_account_id=1,
        open_id=open_id,
        bind_status=bind_status,
    )
    db.add(account)
    db.flush()
    return account


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


def _seed_webhook_event(
    db,
    *,
    conversation_short_id="conv-1",
    account_open_id="account-open-1",
    customer_open_id="customer-open-1",
    server_message_id="server-msg-1",
    minutes_ago=0,
) -> DouyinWebhookEvent:
    event = DouyinWebhookEvent(
        event="im_receive_msg",
        from_user_id=customer_open_id,
        to_user_id=account_open_id,
        conversation_short_id=conversation_short_id,
        server_message_id=server_message_id,
        is_duplicate=0,
        message_create_time=datetime.now() - timedelta(minutes=minutes_ago),
        raw_body="{}",
    )
    db.add(event)
    db.flush()
    return event


_RUN_COUNTER = [0]


def _seed_run(db, **overrides) -> ReturnVisitRun:
    _RUN_COUNTER[0] += 1
    suffix = str(_RUN_COUNTER[0])
    run = ReturnVisitRun(
        merchant_id=overrides.get("merchant_id", "merchant-1"),
        lead_id=overrides.get("lead_id", 10),
        staff_id=overrides.get("staff_id", 1),
        trigger_source="wechat_sales_reply",
        trigger_text=overrides.get("trigger_text", "手机号不对"),
        send_status=overrides.get("send_status", "pending_judgement"),
        attempt_count=overrides.get("attempt_count", 1),
        account_open_id="account-open-1",
        conversation_short_id="conv-1",
        customer_open_id="customer-open-1",
        context_server_message_id=overrides.get("context_server_message_id", "server-msg-1"),
        dispatch_notification_id=overrides.get("dispatch_notification_id", 100),
        idempotency_key=f"key-{suffix}",
        trigger_message_fp=f"fp-{suffix}",
    )
    db.add(run)
    db.flush()
    return run


class _Stub9100:
    """9100 判定替身：judge_return_visit 返回固定 judgment。"""

    def __init__(self, judgment: dict):
        self.judgment = judgment
        self.called = False
        self.request: dict | None = None

    def judge_return_visit(self, request: dict) -> dict:
        self.called = True
        self.request = request
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


# ---------------------------------------------------------------------------
# claim：终态不处理
# ---------------------------------------------------------------------------


def test_terminal_status_not_processed(monkeypatch):
    """终态 run（sent）不 claim，process 直接返回，状态不变。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db, send_status="sent")
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "sent"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 判定终态映射
# ---------------------------------------------------------------------------


def test_judgment_no_match_maps_not_needed(monkeypatch):
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(judgement_result="no_match", prompt_key=None, confidence=0.0, suggested_message=None))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db2.close()


def test_judgment_risk_maps_blocked(monkeypatch):
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(
        monkeypatch,
        _judgment(judgement_result="blocked", prompt_key=None, confidence=0.0, risk_flags=["model_refusal"], suggested_message=None),
    )
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "blocked"
    finally:
        db2.close()


def test_judgment_below_threshold_maps_confidence_low(monkeypatch):
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(judgement_result="below_threshold", confidence=0.3, suggested_message=None))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "confidence_low"
    finally:
        db2.close()


def test_judgment_disabled_maps_prompt_disabled(monkeypatch):
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(judgement_result="prompt_disabled", suggested_message=None))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "prompt_disabled"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# G1 / G2 门禁
# ---------------------------------------------------------------------------


def test_g1_config_disabled_maps_prompt_disabled(monkeypatch):
    monkeypatch.setattr(config, "DOUYIN_AUTO_REPLY_ENABLED", False)
    db = TestSession()
    try:
        _seed_prompts(db)
        _seed_rollout(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "prompt_disabled"
    finally:
        db2.close()


def test_g2_rollout_disabled_maps_prompt_disabled(monkeypatch):
    db = TestSession()
    try:
        _seed_prompts(db)
        _seed_rollout(db, real_send_enabled=False)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "prompt_disabled"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 跨字段合同（阻断 2）
# ---------------------------------------------------------------------------


def test_contract_should_trigger_false_not_needed(monkeypatch):
    """阻断 2：should_trigger=False 不得进入发送（即使 judgement_result 命中 key）。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(should_trigger=False))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db2.close()


def test_contract_ambiguous_true_not_needed(monkeypatch):
    """阻断 2：ambiguous=True（多场景冲突）不得进入发送。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(ambiguous=True))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db2.close()


def test_contract_invalid_source_not_needed(monkeypatch):
    """阻断 2：来源枚举非法不得进入发送。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment(judgement_source="rogue_source"))
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "not_needed"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# G3 跨商户发送绕过（阻断 1）
# ---------------------------------------------------------------------------


def test_g3_unauthorized_account_blocked(monkeypatch):
    """阻断 1：授权账号未绑定 run.merchant_id → lead_attribution_invalid failed，不发送。"""
    db = TestSession()
    try:
        _seed_prompts(db)
        _seed_lead(db)
        _seed_authorized_account(db, merchant_id="merchant-2")  # 绑定到其他商户
        _seed_rollout(db, real_send_enabled=True)
        _seed_webhook_event(db)
        run = _seed_run(db)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        done = db2.get(ReturnVisitRun, run_id)
        assert done.send_status == "failed"
        assert db2.query(DouyinPrivateMessageSend).count() == 0
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 发送三分类
# ---------------------------------------------------------------------------


def _seed_full_gate_pass(db) -> int:
    _seed_prompts(db)
    _seed_lead(db)
    _seed_authorized_account(db)  # G3 授权账号当前归属（阻断 1）
    _seed_rollout(db, real_send_enabled=True)
    _seed_webhook_event(db)  # G5 latest_is_customer + context_not_drifted
    run = _seed_run(db)
    db.flush()
    return run.id


def test_send_success_sent(monkeypatch):
    db = TestSession()
    try:
        run_id = _seed_full_gate_pass(db)
        db.commit()
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "up-1"}}},
    ):
        process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "sent"
        assert db2.query(DouyinPrivateMessageSend).count() == 1
    finally:
        db2.close()


def test_send_upstream_business_error_failed(monkeypatch):
    db = TestSession()
    try:
        run_id = _seed_full_gate_pass(db)
        db.commit()
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        side_effect=HTTPException(status_code=502, detail={"error_code": "upstream_business_error"}),
    ):
        process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "failed"
    finally:
        db2.close()


def test_send_network_error_send_unknown(monkeypatch):
    db = TestSession()
    try:
        run_id = _seed_full_gate_pass(db)
        db.commit()
    finally:
        db.close()

    _patch_9100(monkeypatch, _judgment())
    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        side_effect=HTTPException(status_code=502, detail={"error_code": "invalid_upstream_json"}),
    ):
        process_return_visit_run(run_id)

    db2 = TestSession()
    try:
        assert db2.get(ReturnVisitRun, run_id).send_status == "send_unknown"
    finally:
        db2.close()
