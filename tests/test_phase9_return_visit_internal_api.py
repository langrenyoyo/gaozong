"""Phase 9 Task 4 9100 回访判定内部 API 红灯/绿灯测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 4。

覆盖：
- 内部鉴权三态：正确 token 200 / 缺失 token 401 / 错误 token 401。
- 请求严格性：extra=forbid 拒绝未知字段（422）。
- 响应结构：返回 ReturnVisitJudgment 全字段。
- 鉴权复用既有 require_internal_service_token 链（F15），不新增令牌配置。

判定逻辑替身：monkeypatch router.judge_return_visit 返回固定 Judgment，不触发 LLM 网络。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.xg_douyin_ai_cs.main import app
from apps.xg_douyin_ai_cs.schemas import ReturnVisitJudgment


def _stub_judgment(request) -> ReturnVisitJudgment:
    """绕过 LLM 的固定判定替身（本测试只验证鉴权与协议结构，不验证判定逻辑）。"""
    return ReturnVisitJudgment(
        prompt_key="retain_contact_conversion",
        confidence=0.92,
        should_trigger=True,
        suggested_message="stub-message",
        judgement_source="llm",
        judgement_result="retain_contact_conversion",
        model="stub-model",
        risk_flags=[],
        ambiguous=False,
    )


def _valid_payload() -> dict:
    return {
        "merchant_id": "merchant-1",
        "lead_id": 1,
        "prompts": {
            "retain_contact_conversion": {
                "template_text": "留资模板",
                "fallback_message": "留资兜底",
                "confidence_threshold": 0.90,
                "enabled": True,
            },
            "finance_plan_followup": {
                "template_text": "金融模板",
                "fallback_message": "金融兜底",
                "confidence_threshold": 0.90,
                "enabled": True,
            },
            "silent_customer_wakeup": {
                "template_text": "沉默模板",
                "fallback_message": "沉默兜底",
                "confidence_threshold": 0.90,
                "enabled": True,
            },
        },
        "sales_reply_text": "客户回复内容",
        "dispatch_context": {},
    }


@pytest.fixture(autouse=True)
def _stub_judge(monkeypatch):
    """所有 internal_api 测试统一替身判定函数，真实 LLM 网络恒为 0。"""
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.routers.return_visits.judge_return_visit",
        _stub_judgment,
    )


@pytest.fixture
def prod_token_client(monkeypatch):
    """配置内部 token + production 环境（强制鉴权）。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "test-token-xyz")
    monkeypatch.setenv("APP_ENV", "production")
    return TestClient(app)


# ---------------------------------------------------------------------------
# 鉴权三态
# ---------------------------------------------------------------------------


def test_correct_token_returns_200(prod_token_client):
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["should_trigger"] is True
    assert data["prompt_key"] == "retain_contact_conversion"
    assert data["judgement_source"] == "llm"
    assert data["model"] == "stub-model"


def test_missing_token_returns_401(prod_token_client):
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=_valid_payload(),
        # 故意不带 X-Internal-Service-Token
    )
    assert resp.status_code == 401


def test_wrong_token_returns_401(prod_token_client):
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 请求严格性（extra=forbid）
# ---------------------------------------------------------------------------


def test_request_extra_forbid_rejected(prod_token_client):
    """ReturnVisitJudgeRequest extra=forbid：未知字段 → 422。"""
    payload = _valid_payload()
    payload["unknown_extra_field"] = "should-be-rejected"
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_prompt_input_extra_forbid_rejected(prod_token_client):
    """ReturnVisitPromptInput extra=forbid：prompt 内未知字段 → 422。"""
    payload = _valid_payload()
    payload["prompts"]["retain_contact_conversion"]["unknown_sub_field"] = "x"
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_request_missing_required_field_rejected(prod_token_client):
    """缺少必填字段 merchant_id → 422。"""
    payload = _valid_payload()
    del payload["merchant_id"]
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 响应结构（ReturnVisitJudgment 全字段）
# ---------------------------------------------------------------------------


def test_response_has_all_judgment_fields(prod_token_client):
    resp = prod_token_client.post(
        "/internal/return-visits/decide-and-generate",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 200
    data = resp.json()
    expected_fields = {
        "prompt_key", "confidence", "should_trigger", "suggested_message",
        "judgement_source", "judgement_result", "model", "risk_flags", "ambiguous",
    }
    assert expected_fields.issubset(data.keys()), f"响应缺少字段: {expected_fields - set(data.keys())}"


# ---------------------------------------------------------------------------
# 开发环境未配置 token：放行（require_internal_service_token 既有契约）
# ---------------------------------------------------------------------------


def test_dev_no_token_configured_passes(monkeypatch):
    """development 环境 + 未配置 token → 鉴权放行（既有 require_internal_service_token 契约）。"""
    monkeypatch.delenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    client = TestClient(app)
    resp = client.post(
        "/internal/return-visits/decide-and-generate",
        json=_valid_payload(),
    )
    assert resp.status_code == 200
