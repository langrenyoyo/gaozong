"""Phase 9 Task 5 XgDouyinAiCsClient.judge_return_visit 窄方法测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 5。

覆盖：
- judge_return_visit 只调 /internal/return-visits/decide-and-generate，payload 透传。
- 复用既有 _post_json，token header X-Internal-Service-Token 自动附加。
- 不复用 ask / reply-suggestion / daily-summary 窄方法。
"""

from __future__ import annotations

from unittest.mock import patch

from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClient


# ---------------------------------------------------------------------------
# 红灯 1：judge_return_visit 调用正确路径并透传 payload
# ---------------------------------------------------------------------------


def test_judge_return_visit_posts_to_decide_and_generate():
    client = XgDouyinAiCsClient(base_url="http://9100-test", service_token="tok-1")
    captured: dict = {}

    def fake_post_json(path: str, payload: dict) -> dict:
        captured["path"] = path
        captured["payload"] = payload
        return {"judgement_result": "no_match", "should_trigger": False}

    request = {
        "merchant_id": "merchant-1",
        "lead_id": 10,
        "prompts": {},
        "sales_reply_text": "手机号不对",
        "dispatch_context": {},
    }
    with patch.object(client, "_post_json", side_effect=fake_post_json):
        result = client.judge_return_visit(request)

    assert captured["path"] == "/internal/return-visits/decide-and-generate"
    assert captured["payload"] == request
    assert result == {"judgement_result": "no_match", "should_trigger": False}


# ---------------------------------------------------------------------------
# 红灯 2：token header 复用（X-Internal-Service-Token 自动附加）
# ---------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"judgement_result": "blocked"}


def test_judge_return_visit_reuses_token_header():
    client = XgDouyinAiCsClient(base_url="http://9100-test", service_token="tok-secret")
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: ARG001
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse()

    with patch("app.services.xg_douyin_ai_cs_client.httpx.post", side_effect=fake_post):
        result = client.judge_return_visit({"merchant_id": "merchant-1"})

    assert captured["url"] == "http://9100-test/internal/return-visits/decide-and-generate"
    assert captured["headers"]["X-Internal-Service-Token"] == "tok-secret"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert result == {"judgement_result": "blocked"}
