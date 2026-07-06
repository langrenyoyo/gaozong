from __future__ import annotations

import httpx
from fastapi.testclient import TestClient


def _client(*, client_host: str = "127.0.0.1") -> TestClient:
    from app.main import create_app

    return TestClient(create_app(), client=(client_host, 50000))


def test_ask_allows_whitelisted_ip_without_auth_and_uses_system_context(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "training_id": "kt-1",
                    "question": json["question"],
                    "answer": "可以先介绍小高知识库中的门店优势。",
                    "used_knowledge_base": True,
                    "knowledge_base_name": "小高知识库",
                    "status": "answered",
                    "rag": {"should": "hide"},
                    "category_key": "base",
                    "chunks": [1],
                    "embedding": [0.1],
                }

        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client().post(
        "/knowledge-training/ask",
        json={
            "question": "客户问门店优势怎么答？",
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "training_id": "kt-1",
        "question": "客户问门店优势怎么答？",
        "answer": "可以先介绍小高知识库中的门店优势。",
        "used_knowledge_base": True,
        "knowledge_base_name": "小高知识库",
        "status": "answered",
    }
    assert seen["json"]["merchant_id"] == "xiaogao_base"
    assert seen["json"]["tenant_id"] == "xiaogao_system"
    assert seen["headers"]["X-Internal-Service-Token"] == "internal-secret"
    assert "forged-merchant" not in seen["json"].values()
    assert "rag" not in response.json()
    assert "category_key" not in response.json()
    assert "chunks" not in response.json()
    assert "embedding" not in response.json()


def test_ask_rejects_non_whitelisted_ip(monkeypatch):
    response = _client(client_host="203.0.113.10").post(
        "/knowledge-training/ask",
        json={"question": "怎么回复？"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_PERMISSION_DENIED"


def test_ask_rejects_non_whitelisted_ip_with_invalid_internal_token(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "valid-internal-token")

    response = _client(client_host="203.0.113.10").post(
        "/knowledge-training/ask",
        json={"question": "怎么回复？"},
        headers={"Authorization": "Bearer merchant-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_PERMISSION_DENIED"


def test_ask_allows_internal_token_from_non_whitelisted_ip_and_uses_system_context(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "valid-internal-token")
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "training_id": "kt-token",
                    "question": json["question"],
                    "answer": "这是 internal token 放行后的训练建议回答。",
                    "used_knowledge_base": True,
                    "knowledge_base_name": "小高知识库",
                    "status": "answered",
                }

        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client(client_host="203.0.113.10").post(
        "/knowledge-training/ask",
        headers={"Authorization": "Bearer valid-internal-token"},
        json={
            "question": "客户问价格还能不能便宜一点，该怎么回复？",
            "prompt": "保持礼貌",
            "douyin_account_id": "1",
            "use_xiaogao_knowledge_base": True,
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
        },
    )

    assert response.status_code == 200
    assert response.json()["training_id"] == "kt-token"
    assert response.json()["answer"]
    assert seen["json"]["tenant_id"] == "xiaogao_system"
    assert seen["json"]["merchant_id"] == "xiaogao_base"
    assert seen["json"]["question"] == "客户问价格还能不能便宜一点，该怎么回复？"
    assert seen["json"]["prompt"] == "保持礼貌"
    assert seen["json"]["douyin_account_id"] == "1"
    assert seen["json"]["use_xiaogao_knowledge_base"] is True
    assert "forged-merchant" not in seen["json"].values()
    assert "forged-tenant" not in seen["json"].values()


def test_ask_rejects_when_production_whitelist_is_not_explicit(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("KNOWLEDGE_TRAINING_IP_WHITELIST", raising=False)

    response = _client().post(
        "/knowledge-training/ask",
        json={"question": "怎么回复？"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_PERMISSION_DENIED"


def test_ask_allows_production_explicit_whitelist(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1/32")
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")

    def fake_post(url, *, json, headers, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "training_id": "kt-prod",
                    "question": json["question"],
                    "answer": "生产白名单已命中。",
                    "used_knowledge_base": True,
                    "knowledge_base_name": "小高知识库",
                    "status": "answered",
                }

        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client().post(
        "/knowledge-training/ask",
        json={"question": "怎么回复？"},
    )

    assert response.status_code == 200
    assert response.json()["training_id"] == "kt-prod"


def test_feedback_rejects_non_whitelisted_ip(monkeypatch):
    response = _client(client_host="203.0.113.10").post(
        "/knowledge-training/kt-1/feedback",
        json={"rating": "wrong"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_PERMISSION_DENIED"


def test_feedback_allows_internal_token_from_non_whitelisted_ip(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "valid-internal-token")
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "training_id": "kt-1",
                    "rating": json["rating"],
                    "status": "submitted",
                    "knowledge_base_name": "小高知识库",
                    "raw_detail": "should-hide",
                }

        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client(client_host="203.0.113.10").post(
        "/knowledge-training/kt-1/feedback",
        headers={"Authorization": "Bearer valid-internal-token"},
        json={"rating": "useful", "comment": "SMOKE feedback only"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "training_id": "kt-1",
        "rating": "useful",
        "status": "submitted",
        "knowledge_base_name": "小高知识库",
    }
    assert seen["json"]["tenant_id"] == "xiaogao_system"
    assert seen["json"]["merchant_id"] == "xiaogao_base"
    assert seen["json"]["rating"] == "useful"
    assert seen["json"]["comment"] == "SMOKE feedback only"


def test_feedback_allows_whitelisted_ip_without_auth_and_uses_system_context(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "training_id": "kt-1",
                    "rating": json["rating"],
                    "status": "pending_review",
                    "knowledge_base_name": "小高知识库",
                    "category_key": "base",
                    "chunk_count": 0,
                }

        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client().post(
        "/knowledge-training/kt-1/feedback",
        json={
            "rating": "wrong",
            "comment": "这条回答不准",
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "training_id": "kt-1",
        "rating": "wrong",
        "status": "pending_review",
        "knowledge_base_name": "小高知识库",
    }
    assert seen["json"]["merchant_id"] == "xiaogao_base"
    assert seen["json"]["tenant_id"] == "xiaogao_system"
    assert seen["json"]["rating"] == "wrong"
    assert seen["headers"]["X-Internal-Service-Token"] == "internal-secret"


def test_feedback_preserves_training_session_not_found(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        request = httpx.Request("POST", url)
        response = httpx.Response(
            404,
            request=request,
            json={"detail": {"code": "TRAINING_SESSION_NOT_FOUND", "message": "训练会话不存在"}},
        )

        class WrappedResponse:
            def raise_for_status(self):
                raise httpx.HTTPStatusError("not found", request=request, response=response)

            def json(self):
                return response.json()

        return WrappedResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client().post(
        "/knowledge-training/kt-missing/feedback",
        json={"rating": "useful"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TRAINING_SESSION_NOT_FOUND"


def test_feedback_preserves_training_session_forbidden(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        request = httpx.Request("POST", url)
        response = httpx.Response(
            403,
            request=request,
            json={"detail": {"code": "TRAINING_SESSION_FORBIDDEN", "message": "无权反馈该训练会话"}},
        )

        class WrappedResponse:
            def raise_for_status(self):
                raise httpx.HTTPStatusError("forbidden", request=request, response=response)

            def json(self):
                return response.json()

        return WrappedResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    response = _client().post(
        "/knowledge-training/kt-other/feedback",
        json={"rating": "normal"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TRAINING_SESSION_FORBIDDEN"


def test_non_training_endpoint_still_requires_newcar_auth(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")

    response = _client().get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_MISSING"
