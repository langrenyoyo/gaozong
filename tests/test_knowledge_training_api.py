from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required


def _context(
    *,
    merchant_id: str | None = "merchant-real",
    permission_codes: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        username="user-1",
        display_name="商家用户",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:knowledge_training"],
        session_id="session-1",
    )


def _client(context: RequestContext) -> TestClient:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def test_ask_uses_request_context_and_returns_business_fields(monkeypatch):
    seen: dict = {}

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        seen["timeout"] = timeout

        class Response:
            status_code = 200

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

    response = _client(_context()).post(
        "/knowledge-training/ask",
        json={
            "question": "客户问门店优势怎么答？",
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "training_id": "kt-1",
        "question": "客户问门店优势怎么答？",
        "answer": "可以先介绍小高知识库中的门店优势。",
        "used_knowledge_base": True,
        "knowledge_base_name": "小高知识库",
        "status": "answered",
    }
    assert seen["json"]["merchant_id"] == "merchant-real"
    assert seen["json"]["tenant_id"] == "new_car_project"
    assert "forged-merchant" not in seen["json"].values()
    assert "rag" not in data
    assert "category_key" not in data
    assert "chunks" not in data
    assert "embedding" not in data


def test_ask_requires_knowledge_training_permission():
    response = _client(_context(permission_codes=["auto_wechat:leads"])).post(
        "/knowledge-training/ask",
        json={"question": "怎么回复？"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_feedback_submits_wrong_rating_for_review(monkeypatch):
    seen: dict = {}

    def fake_post(url, *, json, headers, timeout):
        seen["url"] = url
        seen["json"] = json

        class Response:
            status_code = 200

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

    response = _client(_context()).post(
        "/knowledge-training/kt-1/feedback",
        json={
            "rating": "wrong",
            "comment": "这条回答不准",
            "merchant_id": "forged-merchant",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "training_id": "kt-1",
        "rating": "wrong",
        "status": "pending_review",
        "knowledge_base_name": "小高知识库",
    }
    assert seen["json"]["merchant_id"] == "merchant-real"
    assert seen["json"]["rating"] == "wrong"
