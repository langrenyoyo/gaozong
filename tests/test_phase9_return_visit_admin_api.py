"""Phase 9 Task 8 管理员端回访配置与运行审计 API 测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 8。

覆盖：
- 三条 prompt 列表；逐字 fallback（PUT 原文保存）。
- PUT reason 必填 / 范围校验（template_text 1..500、confidence_threshold 0.50..1.00、enabled bool、未知字段 422）。
- 审计写入；违禁词命中告警（ForbiddenWordHitLog）但数据库保存原文。
- 无权限 403；未知 key 404。
- runs 过滤（send_status/prompt_key/judgement_source）与统计。
- 商户隔离：非 super_admin 看其他商户 run 详情 → 404。
- trigger_text 零回显（列表 + 详情）；列表不回 customer_open_id/generated/final。
- 无写发送端点（POST send/retry/requeue 不存在）。

全替身，真实网络恒 0（本测试不触发发送）。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 SQLAlchemy metadata 注册全部模型
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AutoReplyAdminAuditLog,
    ForbiddenWord,
    ForbiddenWordHitLog,
    ForbiddenWordLibrary,
    ReturnVisitPrompt,
    ReturnVisitRun,
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


_PERMISSION = "auto_wechat:admin:return_visit_prompts"


def _context(
    *,
    super_admin: bool = True,
    user_id: str = "admin-1",
    permission_codes: list[str] | None = None,
    merchant_ids: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=user_id,
        display_name="管理员",
        merchant_id=(merchant_ids or ["admin-merchant"])[0],
        merchant_ids=merchant_ids or ["admin-merchant"],
        permission_codes=permission_codes if permission_codes is not None else [_PERMISSION],
        super_admin=super_admin,
    )


def _client(context: RequestContext | None = None, *, auth_error: HTTPException | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if auth_error is not None:
        app.dependency_overrides[get_request_context_required] = lambda: (_ for _ in ()).throw(auth_error)
    elif context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------


_PROMPT_SEED = [
    ("retain_contact_conversion", "模板_留资", "兜底_留资", 0),
    ("finance_plan_followup", "模板_金融", "兜底_金融", 1),
    ("silent_customer_wakeup", "模板_沉默", "兜底_沉默", 2),
]


def _seed_prompts() -> None:
    db = TestSession()
    try:
        for key, text, fallback, sort in _PROMPT_SEED:
            db.add(
                ReturnVisitPrompt(
                    prompt_key=key,
                    name=key,
                    template_text=text,
                    fallback_message=fallback,
                    confidence_threshold=0.90,
                    enabled=True,
                    scope="global",
                    sort_order=sort,
                )
            )
        db.commit()
    finally:
        db.close()


def _seed_forbidden_word(word: str = "敏感词A", safe: str = "安全词A") -> None:
    """seed 全局违禁词库 + 词条，验证 PUT 命中告警但数据库保存原文。"""
    db = TestSession()
    try:
        db.add(
            ForbiddenWordLibrary(
                id=1,
                library_key="base",
                name="基础词库",
                scope="global",
                enabled=True,
                sort_order=0,
            )
        )
        db.add(
            ForbiddenWord(
                library_id=1,
                word=word,
                safe_word=safe,
                enabled=True,
                hit_count=0,
            )
        )
        db.commit()
    finally:
        db.close()


_RUN_COUNTER = [0]


def _seed_run(
    *,
    merchant_id: str = "admin-merchant",
    send_status: str = "sent",
    prompt_key: str = "retain_contact_conversion",
    judgement_source: str = "llm",
    trigger_text: str = "敏感触发原文13800000000",
) -> int:
    db = TestSession()
    try:
        _RUN_COUNTER[0] += 1
        suffix = str(_RUN_COUNTER[0])
        run = ReturnVisitRun(
            merchant_id=merchant_id,
            lead_id=10,
            staff_id=1,
            trigger_source="wechat_sales_reply",
            trigger_text=trigger_text,
            send_status=send_status,
            attempt_count=1,
            account_open_id="account-open-1234567890",
            conversation_short_id="conv-short-1",
            customer_open_id="customer-open-0987654321",
            context_server_message_id="server-msg-1",
            dispatch_notification_id=100,
            idempotency_key=f"key-{suffix}",
            trigger_message_fp=f"fp-{suffix}",
            prompt_key=prompt_key,
            judgement_source=judgement_source,
            judgement_result=prompt_key,
            generated_content="生成话术含 13900001111",
            final_content="最终话术含敏感词A",
            error_message="原始异常含 token=secret-xyz",
            confidence=0.95,
            model="test-model",
            risk_flags_json=json.dumps(["off_topic"]),
            gate_results_json=json.dumps({"G3": "passed"}),
            manual_takeover=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()
    return run_id


# ---------------------------------------------------------------------------
# prompt 列表与逐字 fallback
# ---------------------------------------------------------------------------


def test_list_prompts_returns_three():
    _seed_prompts()
    resp = _client(_context()).get("/admin/return-visit-prompts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    keys = {item["prompt_key"] for item in body["data"]["items"]}
    assert keys == {"retain_contact_conversion", "finance_plan_followup", "silent_customer_wakeup"}
    assert body["data"]["total"] == 3


def test_update_prompt_preserves_verbatim_text():
    _seed_prompts()
    payload = {
        "template_text": "逐字模板ABC",
        "fallback_message": "逐字兜底XYZ",
        "confidence_threshold": 0.75,
        "enabled": False,
        "reason": "调整话术",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 数据库保存管理员原文（逐字），不被替换或改写
    assert data["template_text"] == "逐字模板ABC"
    assert data["fallback_message"] == "逐字兜底XYZ"
    assert data["confidence_threshold"] == 0.75
    assert data["enabled"] is False

    # 二次查询确认持久化
    db = TestSession()
    try:
        row = db.query(ReturnVisitPrompt).filter(
            ReturnVisitPrompt.prompt_key == "retain_contact_conversion"
        ).first()
        assert row.template_text == "逐字模板ABC"
        assert row.fallback_message == "逐字兜底XYZ"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PUT 校验
# ---------------------------------------------------------------------------


def test_update_prompt_rejects_too_long_template():
    _seed_prompts()
    payload = {
        "template_text": "x" * 501,
        "fallback_message": "兜底",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "测试",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422


def test_update_prompt_rejects_threshold_out_of_range():
    _seed_prompts()
    payload = {
        "template_text": "模板",
        "fallback_message": "兜底",
        "confidence_threshold": 0.49,
        "enabled": True,
        "reason": "测试",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422

    payload["confidence_threshold"] = 1.01
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422


def test_update_prompt_rejects_empty_reason():
    _seed_prompts()
    payload = {
        "template_text": "模板",
        "fallback_message": "兜底",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422


def test_update_prompt_rejects_whitespace_only_reason():
    """reason 纯空白（strip 后为空）→ 422（审计合同：reason 非空，min_length 拦不住纯空白）。"""
    _seed_prompts()
    payload = {
        "template_text": "模板",
        "fallback_message": "兜底",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "   ",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422


def test_update_prompt_rejects_unknown_field():
    _seed_prompts()
    payload = {
        "template_text": "模板",
        "fallback_message": "兜底",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "测试",
        "extra_field": "不应接受",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/retain_contact_conversion", json=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


def test_update_prompt_writes_audit():
    _seed_prompts()
    payload = {
        "template_text": "新模板",
        "fallback_message": "新兜底",
        "confidence_threshold": 0.85,
        "enabled": True,
        "reason": "审计留痕原因",
    }
    resp = _client(_context(user_id="admin-77")).put(
        "/admin/return-visit-prompts/silent_customer_wakeup", json=payload
    )
    assert resp.status_code == 200

    db = TestSession()
    try:
        audits = db.query(AutoReplyAdminAuditLog).all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.action == "return_visit_prompt_update"
        assert audit.target_type == "return_visit_prompt"
        assert audit.target_id == "silent_customer_wakeup"
        assert audit.operator_id == "admin-77"
        assert audit.reason == "审计留痕原因"
        # before_json/after_json 是 ORM JSON 列，读取后即为 dict（_safe_json 不返回字符串）
        before = audit.before_json
        after = audit.after_json
        assert before["template_text"] == "模板_沉默"
        assert after["template_text"] == "新模板"
        assert after["enabled"] is True
    finally:
        db.close()


def test_update_prompt_forbidden_word_alert_preserves_original():
    """违禁词命中写 ForbiddenWordHitLog；数据库仍保存管理员原文（不被安全词替换）。"""
    _seed_prompts()
    _seed_forbidden_word(word="敏感词A", safe="安全词A")
    payload = {
        "template_text": "话术含敏感词A请留意",
        "fallback_message": "兜底无违禁",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "违禁词告警测试",
    }
    resp = _client(_context()).put(
        "/admin/return-visit-prompts/retain_contact_conversion", json=payload
    )
    assert resp.status_code == 200

    db = TestSession()
    try:
        # 命中日志写入
        hits = db.query(ForbiddenWordHitLog).filter(
            ForbiddenWordHitLog.source == "return_visit_prompt_edit"
        ).all()
        assert len(hits) >= 1
        assert any(h.word == "敏感词A" for h in hits)
        # 数据库保存管理员原文，未被安全词替换
        row = db.query(ReturnVisitPrompt).filter(
            ReturnVisitPrompt.prompt_key == "retain_contact_conversion"
        ).first()
        assert row.template_text == "话术含敏感词A请留意"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 权限与未知 key
# ---------------------------------------------------------------------------


def test_no_permission_403():
    _seed_prompts()
    ctx = _context(super_admin=False, permission_codes=["other:permission"])
    resp = _client(ctx).get("/admin/return-visit-prompts")
    assert resp.status_code == 403


def test_unknown_prompt_key_404():
    _seed_prompts()
    payload = {
        "template_text": "模板",
        "fallback_message": "兜底",
        "confidence_threshold": 0.80,
        "enabled": True,
        "reason": "测试",
    }
    resp = _client(_context()).put("/admin/return-visit-prompts/unknown_key", json=payload)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# runs 过滤与统计
# ---------------------------------------------------------------------------


def test_runs_filter_and_stats():
    _seed_run(send_status="sent", prompt_key="retain_contact_conversion", judgement_source="llm")
    _seed_run(send_status="blocked", prompt_key="finance_plan_followup", judgement_source="keyword_fallback")
    _seed_run(send_status="blocked", prompt_key="retain_contact_conversion", judgement_source="llm")

    client = _client(_context())

    # 按 send_status 过滤
    resp = client.get("/admin/return-visit-runs", params={"send_status": "blocked"})
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2

    # 按 prompt_key 过滤
    resp = client.get("/admin/return-visit-runs", params={"prompt_key": "finance_plan_followup"})
    assert resp.json()["data"]["total"] == 1

    # 按 judgement_source 过滤
    resp = client.get("/admin/return-visit-runs", params={"judgement_source": "keyword_fallback"})
    assert resp.json()["data"]["total"] == 1

    # 统计
    resp = client.get("/admin/return-visit-runs/stats")
    assert resp.status_code == 200
    stats = resp.json()["data"]
    assert stats["total"] == 3
    assert stats["by_send_status"]["sent"] == 1
    assert stats["by_send_status"]["blocked"] == 2


def test_runs_stats_path_not_swallowed_by_run_id():
    """/runs/stats 必须在 /runs/{run_id} 前注册，否则 stats 被当 run_id 解析。"""
    _seed_run(send_status="sent")
    resp = _client(_context()).get("/admin/return-visit-runs/stats")
    assert resp.status_code == 200
    assert "by_send_status" in resp.json()["data"]


# ---------------------------------------------------------------------------
# 商户隔离
# ---------------------------------------------------------------------------


def test_run_detail_merchant_isolation_404():
    """非 super_admin 看其他商户 run 详情 → 404（不泄露存在性）。"""
    other_run_id = _seed_run(merchant_id="merchant-other")
    ctx = _context(super_admin=False, merchant_ids=["admin-merchant"])
    resp = _client(ctx).get(f"/admin/return-visit-runs/{other_run_id}")
    assert resp.status_code == 404


def test_run_detail_super_admin_sees_all_merchants():
    other_run_id = _seed_run(merchant_id="merchant-other")
    resp = _client(_context(super_admin=True)).get(f"/admin/return-visit-runs/{other_run_id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 脱敏：trigger_text 零回显 + 列表不回 customer_open_id/generated/final
# ---------------------------------------------------------------------------


def test_trigger_text_never_exposed_in_list_or_detail():
    trigger_secret = "绝密触发原文_不应回显"
    run_id = _seed_run(trigger_text=trigger_secret)
    client = _client(_context())

    # 列表
    resp = client.get("/admin/return-visit-runs")
    assert resp.status_code == 200
    list_body = json.dumps(resp.json(), ensure_ascii=False)
    assert trigger_secret not in list_body
    # 列表项不含这些敏感键
    item = resp.json()["data"]["items"][0]
    for forbidden_key in (
        "trigger_text",
        "customer_open_id",
        "generated_content",
        "final_content",
        "error_message",
    ):
        assert forbidden_key not in item, f"列表响应不应含 {forbidden_key}"

    # 详情
    resp = client.get(f"/admin/return-visit-runs/{run_id}")
    assert resp.status_code == 200
    detail_body = json.dumps(resp.json(), ensure_ascii=False)
    assert trigger_secret not in detail_body
    detail = resp.json()["data"]
    # 详情仍不回显 trigger_text / error_message（原始异常）
    assert "trigger_text" not in detail
    assert "error_message" not in detail
    # customer_open_id 仅以掩码形式
    assert detail["customer_open_id_masked"] is not None
    assert "customer-open-0987654321" not in detail_body


def test_detail_masks_phone_in_generated_final_content():
    """详情返回生成/最终话术摘要，手机号须脱敏。"""
    run_id = _seed_run()
    resp = _client(_context()).get(f"/admin/return-visit-runs/{run_id}")
    detail = resp.json()["data"]
    body = json.dumps(resp.json(), ensure_ascii=False)
    # generated_content 原文含 13900001111，脱敏后不得出现完整手机号
    assert "13900001111" not in body
    assert detail["generated_content_summary"] is not None


def test_list_and_detail_return_trigger_message_fp():
    """F8：列表与详情均返回 trigger_message_fp 指纹（非原文）；trigger_text 原文不回显。"""
    db = TestSession()
    try:
        _RUN_COUNTER[0] += 1
        suffix = str(_RUN_COUNTER[0])
        run = ReturnVisitRun(
            merchant_id="admin-merchant",
            lead_id=10,
            staff_id=1,
            trigger_source="wechat_sales_reply",
            trigger_text="绝密原文不回显",
            send_status="sent",
            attempt_count=1,
            idempotency_key=f"fpkey-{suffix}",
            trigger_message_fp="fp-fixed-abc123",
            prompt_key="retain_contact_conversion",
            judgement_source="llm",
            judgement_result="retain_contact_conversion",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    client = _client(_context())
    # 列表项返回指纹
    resp = client.get("/admin/return-visit-runs")
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["trigger_message_fp"] == "fp-fixed-abc123"
    # 详情返回指纹
    resp = client.get(f"/admin/return-visit-runs/{run_id}")
    assert resp.status_code == 200
    detail = resp.json()["data"]
    assert detail["trigger_message_fp"] == "fp-fixed-abc123"
    # 原文不回显（仅指纹）
    assert "绝密原文不回显" not in json.dumps(resp.json(), ensure_ascii=False)


def test_detail_invalid_json_returns_empty_structures():
    """risk_flags_json / gate_results_json 解析失败返回空列表/空对象，不回显原串。"""
    db = TestSession()
    try:
        _RUN_COUNTER[0] += 1
        run = ReturnVisitRun(
            merchant_id="admin-merchant",
            lead_id=10,
            staff_id=1,
            trigger_source="wechat_sales_reply",
            trigger_text="t",
            send_status="sent",
            attempt_count=1,
            idempotency_key=f"bad-{_RUN_COUNTER[0]}",
            trigger_message_fp=f"badfp-{_RUN_COUNTER[0]}",
            risk_flags_json="not-json",
            gate_results_json="{broken",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    resp = _client(_context()).get(f"/admin/return-visit-runs/{run_id}")
    detail = resp.json()["data"]
    assert detail["risk_flags"] == []
    assert detail["gate_results"] == {}
    body = json.dumps(resp.json(), ensure_ascii=False)
    assert "not-json" not in body
    assert "{broken" not in body


# ---------------------------------------------------------------------------
# 无写发送端点
# ---------------------------------------------------------------------------


def test_no_write_send_endpoints():
    """回访管理 API 不提供 POST send/retry/requeue/立即发送端点。"""
    client = _client(_context())
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths", {})
    return_visit_paths = {p: methods for p, methods in paths.items() if "/admin/return-visit" in p}
    assert return_visit_paths, "应至少注册回访管理路由"

    forbidden_substrings = ("retry", "send", "requeue", "resend", "trigger-now")
    for path, methods in return_visit_paths.items():
        for method in methods:
            assert method.upper() != "POST", f"不应有 POST 端点: {method} {path}"
            lowered = path.lower()
            for bad in forbidden_substrings:
                assert bad not in lowered, f"路径不应含发送类关键字 {bad}: {path}"
