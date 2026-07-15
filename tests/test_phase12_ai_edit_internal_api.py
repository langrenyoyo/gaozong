"""Phase 12 Task 4 9100 AI 剪辑规划内部 API 红灯/绿灯测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §9/§11。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 4 Step 3。

覆盖：
- 内部鉴权三态：正确 token 200 / 缺失 token 401 / 错误 token 401。
- 请求严格性：AiEditPlanRequest / TranscriptSegment / SceneSummary extra=forbid 拒绝未知字段（422）。
- 必填字段缺失 422；target_duration_seconds 越界 422。
- 响应结构：返回 AiEditPlan 全字段。
- 鉴权复用既有 require_internal_service_token 链，不新增令牌配置。

规划替身：monkeypatch router.plan_ai_edit 返回固定 AiEditPlan，不触发 LLM 网络。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.xg_douyin_ai_cs.main import app
from apps.xg_douyin_ai_cs.schemas import AiEditPlan, PlanOperation


def _stub_plan(request) -> AiEditPlan:
    """绕过 LLM 的固定规划替身（本测试只验证鉴权与协议结构，不验证规划逻辑）。"""
    return AiEditPlan(
        status="ok",
        plan_version="phase12_ai_edit_plan_v1",
        operations=[
            PlanOperation(material_id="mat-1", start_seconds=0, end_seconds=10,
                          action="keep", reason=None),
        ],
        failure_code=None,
        model="stub-model",
    )


def _valid_payload() -> dict:
    return {
        "merchant_id": "m1",
        "job_id": "job-1",
        "template_key": "tpl",
        "template_version": "v1",
        "target_duration_seconds": 30,
        "transcript_segments": [
            {"material_id": "mat-1", "start_seconds": 0, "end_seconds": 10,
             "text": "大家好今天介绍这款车"},
        ],
        "scenes": [
            {"material_id": "mat-1", "start_seconds": 0, "end_seconds": 10,
             "scene_label": "外观", "stability_score": 0.9},
        ],
    }


@pytest.fixture(autouse=True)
def _stub_plan_fn(monkeypatch):
    """所有 internal_api 测试统一替身规划函数，真实 LLM 网络恒为 0。"""
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.routers.ai_edit.plan_ai_edit",
        _stub_plan,
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
        "/internal/ai-edit/plan",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["plan_version"] == "phase12_ai_edit_plan_v1"
    assert data["operations"][0]["action"] == "keep"
    assert data["model"] == "stub-model"


def test_missing_token_returns_401(prod_token_client):
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=_valid_payload(),
    )
    assert resp.status_code == 401


def test_wrong_token_returns_401(prod_token_client):
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 请求严格性（extra=forbid）
# ---------------------------------------------------------------------------


def test_request_extra_forbid_rejected(prod_token_client):
    payload = _valid_payload()
    payload["unknown_extra_field"] = "should-be-rejected"
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_transcript_segment_extra_forbid_rejected(prod_token_client):
    payload = _valid_payload()
    payload["transcript_segments"][0]["unknown_sub_field"] = "x"
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_scene_summary_extra_forbid_rejected(prod_token_client):
    payload = _valid_payload()
    payload["scenes"][0]["unknown_sub_field"] = "x"
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 必填字段缺失 / 越界 → 422
# ---------------------------------------------------------------------------


def test_request_missing_required_field_rejected(prod_token_client):
    payload = _valid_payload()
    del payload["merchant_id"]
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_target_duration_below_range_rejected(prod_token_client):
    payload = _valid_payload()
    payload["target_duration_seconds"] = 14  # < 15
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


def test_target_duration_above_range_rejected(prod_token_client):
    payload = _valid_payload()
    payload["target_duration_seconds"] = 61  # > 60
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=payload,
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 响应结构（AiEditPlan 全字段）
# ---------------------------------------------------------------------------


def test_response_has_all_plan_fields(prod_token_client):
    resp = prod_token_client.post(
        "/internal/ai-edit/plan",
        json=_valid_payload(),
        headers={"X-Internal-Service-Token": "test-token-xyz"},
    )
    assert resp.status_code == 200
    expected = {"status", "plan_version", "operations", "failure_code", "model"}
    assert expected.issubset(resp.json().keys())


# ---------------------------------------------------------------------------
# 开发环境未配置 token：放行（require_internal_service_token 既有契约）
# ---------------------------------------------------------------------------


def test_dev_no_token_configured_passes(monkeypatch):
    monkeypatch.delenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    client = TestClient(app)
    resp = client.post("/internal/ai-edit/plan", json=_valid_payload())
    assert resp.status_code == 200
