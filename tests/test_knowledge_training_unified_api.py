from __future__ import annotations

from fastapi.testclient import TestClient


def _client(*, client_host: str = "203.0.113.10") -> TestClient:
    from app.main import create_app

    return TestClient(create_app(), client=(client_host, 50000))


class FakeKnowledgeTrainingClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def list_knowledge_training_categories(self, *, tenant_id: str, merchant_id: str) -> dict:
        self.calls.append(("categories", {"tenant_id": tenant_id, "merchant_id": merchant_id}))
        return {"categories": [{"key": "base", "name": "小高知识库", "description": "", "document_count": 0}]}

    def list_knowledge_training_documents(self, *, tenant_id: str, merchant_id: str, params: dict) -> dict:
        self.calls.append(("documents", {"tenant_id": tenant_id, "merchant_id": merchant_id, **params}))
        return {"items": [], "total": 0, "page": params["page"], "page_size": params["page_size"]}

    def get_knowledge_training_document(self, *, tenant_id: str, merchant_id: str, document_id: str) -> dict:
        self.calls.append(("document_detail", {"tenant_id": tenant_id, "merchant_id": merchant_id, "document_id": document_id}))
        if document_id == "missing":
            from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

            raise XgDouyinAiCsClientError(
                "not_found",
                status_code=404,
                detail={"code": "KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND", "message": "文档不存在"},
            )
        return {
            "document_id": document_id,
            "title": "基础接待规则",
            "content": "统一知识正文",
            "category_key": "base",
            "status": "draft",
            "chunk_count": 0,
        }

    def create_knowledge_training_document(self, *, tenant_id: str, merchant_id: str, request: dict) -> dict:
        self.calls.append(("create_document", {"tenant_id": tenant_id, "merchant_id": merchant_id, **request}))
        return {"document_id": "doc_1", "status": "draft", "category_key": request["category_key"]}

    def update_knowledge_training_document(self, *, tenant_id: str, merchant_id: str, document_id: str, request: dict) -> dict:
        self.calls.append(("update_document", {"tenant_id": tenant_id, "merchant_id": merchant_id, "document_id": document_id, **request}))
        return {"document_id": document_id, "status": "draft", "category_key": request["category_key"]}

    def train_knowledge_training_document(self, *, tenant_id: str, merchant_id: str, document_id: str, request: dict) -> dict:
        self.calls.append(("train_document", {"tenant_id": tenant_id, "merchant_id": merchant_id, "document_id": document_id, **request}))
        return {"training_run_id": "run_1", "document_id": document_id, "status": "queued"}

    def get_knowledge_training_run(self, *, tenant_id: str, merchant_id: str, run_id: str) -> dict:
        self.calls.append(("run_detail", {"tenant_id": tenant_id, "merchant_id": merchant_id, "run_id": run_id}))
        return {"training_run_id": run_id, "document_id": "doc_1", "status": "completed", "chunk_count": 1}

    def list_knowledge_training_runs(self, *, tenant_id: str, merchant_id: str, params: dict) -> dict:
        self.calls.append(("runs", {"tenant_id": tenant_id, "merchant_id": merchant_id, **params}))
        return {"items": [], "total": 0, "page": params["page"], "page_size": params["page_size"]}

    def delete_knowledge_training_document(self, *, tenant_id: str, merchant_id: str, document_id: str, request: dict) -> dict:
        self.calls.append(("delete_document", {"tenant_id": tenant_id, "merchant_id": merchant_id, "document_id": document_id, **request}))
        return {"document_id": document_id, "status": "deleted"}

    def search_knowledge_training_preview(self, *, tenant_id: str, merchant_id: str, request: dict) -> dict:
        self.calls.append(("search_preview", {"tenant_id": tenant_id, "merchant_id": merchant_id, **request}))
        return {
            "query": request["query"],
            "matches": [
                {
                    "document_id": "doc_1",
                    "title": "基础接待规则",
                    "category_key": "base",
                    "chunk_text": "命中的知识片段",
                    "score": 0.82,
                    "collection": "should-hide",
                    "vector_id": "should-hide",
                }
            ],
        }


def _patch_fake_client(monkeypatch, fake: FakeKnowledgeTrainingClient):
    import app.routers.knowledge_training as router

    monkeypatch.setattr(router, "get_xg_douyin_ai_cs_client", lambda: fake)


def _auth_headers(token: str = "secret") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Operator-Id": "operator-1",
        "X-Operator-Account": "trainer@example.invalid",
        "X-Request-Id": "req-1",
        "X-Operator-Source": "car-project-main",
    }


def test_unified_categories_rejects_non_whitelisted_request_without_internal_token(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.delenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", raising=False)

    response = _client().get("/knowledge-training/categories")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_PERMISSION_DENIED"


def test_unified_categories_allows_internal_token_and_uses_fixed_context(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().get("/knowledge-training/categories", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["categories"][0]["key"] == "base"
    assert fake.calls == [("categories", {"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"})]


def test_unified_categories_allows_x_internal_token_with_trimmed_csv(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", " old-token , dev_knowledge_training_token ")

    response = _client().get(
        "/knowledge-training/categories",
        headers={"X-Internal-Token": "dev_knowledge_training_token"},
    )

    assert response.status_code == 200
    assert fake.calls == [("categories", {"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"})]


def test_unified_categories_allows_case_insensitive_bearer_scheme(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_IP_WHITELIST", "127.0.0.1")
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "dev_knowledge_training_token")

    response = _client().get(
        "/knowledge-training/categories",
        headers={"Authorization": "bEaReR dev_knowledge_training_token"},
    )

    assert response.status_code == 200
    assert fake.calls == [("categories", {"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"})]


def test_create_document_rejects_context_fields(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().post(
        "/knowledge-training/documents",
        headers=_auth_headers(),
        json={
            "title": "标题",
            "content": "正文",
            "tenant_id": "forged",
            "category_key": "base",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN"
    assert fake.calls == []


def test_create_document_uses_fixed_context_and_default_base(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().post(
        "/knowledge-training/documents",
        headers=_auth_headers(),
        json={"title": "基础接待规则", "content": "统一知识正文", "source_type": "manual_text"},
    )

    assert response.status_code == 200
    assert response.json() == {"document_id": "doc_1", "status": "draft", "category_key": "base"}
    assert fake.calls[0][0] == "create_document"
    assert fake.calls[0][1]["tenant_id"] == "xiaogao_system"
    assert fake.calls[0][1]["merchant_id"] == "xiaogao_base"
    assert fake.calls[0][1]["category_key"] == "base"


def test_empty_content_returns_invalid_document(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().post(
        "/knowledge-training/documents",
        headers=_auth_headers(),
        json={"title": "基础接待规则", "content": " "},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_INVALID_DOCUMENT"


def test_document_list_detail_update_delete_and_runs_proxy_to_9100(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")
    client = _client()

    assert client.get("/knowledge-training/documents", headers=_auth_headers()).status_code == 200
    assert client.get("/knowledge-training/documents/doc_1", headers=_auth_headers()).status_code == 200
    assert client.put(
        "/knowledge-training/documents/doc_1",
        headers=_auth_headers(),
        json={"title": "新标题", "content": "新正文"},
    ).status_code == 200
    assert client.delete("/knowledge-training/documents/doc_1", headers=_auth_headers()).json()["status"] == "deleted"
    assert client.get("/knowledge-training/training-runs/run_1", headers=_auth_headers()).status_code == 200
    assert client.get("/knowledge-training/training-runs", headers=_auth_headers()).status_code == 200

    assert [name for name, _ in fake.calls] == [
        "documents",
        "document_detail",
        "update_document",
        "delete_document",
        "run_detail",
        "runs",
    ]


def test_document_detail_not_found_maps_to_404(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().get("/knowledge-training/documents/missing", headers=_auth_headers())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND"


def test_train_rejects_rebuild_all_and_accepts_rebuild_document(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")
    client = _client()

    denied = client.post(
        "/knowledge-training/documents/doc_1/train",
        headers=_auth_headers(),
        json={"mode": "rebuild_all"},
    )
    allowed = client.post(
        "/knowledge-training/documents/doc_1/train",
        headers=_auth_headers(),
        json={"mode": "rebuild_document"},
    )

    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_INVALID_DOCUMENT"
    assert allowed.status_code == 200
    assert allowed.json()["training_run_id"] == "run_1"


def test_search_preview_defaults_base_hides_vector_fields_and_limits_top_k(monkeypatch):
    fake = FakeKnowledgeTrainingClient()
    _patch_fake_client(monkeypatch, fake)
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().post(
        "/knowledge-training/search-preview",
        headers=_auth_headers(),
        json={"query": "客户问：这台车还有吗？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"][0]["document_id"] == "doc_1"
    assert "collection" not in payload["matches"][0]
    assert "vector_id" not in payload["matches"][0]
    assert fake.calls[0][1]["category_keys"] == ["base"]
    assert fake.calls[0][1]["top_k"] == 5

    too_large = _client().post(
        "/knowledge-training/search-preview",
        headers=_auth_headers(),
        json={"query": "客户问：这台车还有吗？", "top_k": 11},
    )
    assert too_large.status_code == 422

    not_number = _client().post(
        "/knowledge-training/search-preview",
        headers=_auth_headers(),
        json={"query": "客户问：这台车还有吗？", "top_k": "many"},
    )
    assert not_number.status_code == 422


def test_upstream_error_is_sanitized(monkeypatch):
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    class BrokenClient(FakeKnowledgeTrainingClient):
        def search_knowledge_training_preview(self, *, tenant_id: str, merchant_id: str, request: dict) -> dict:
            raise XgDouyinAiCsClientError(
                "trace token=secret host=milvus.internal",
                status_code=500,
                detail={"code": "RAW", "message": "stack token=secret host=milvus.internal"},
            )

    _patch_fake_client(monkeypatch, BrokenClient())
    monkeypatch.setenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "secret")

    response = _client().post(
        "/knowledge-training/search-preview",
        headers=_auth_headers(),
        json={"query": "客户问：这台车还有吗？"},
    )

    assert response.status_code == 502
    text = str(response.json())
    assert "secret" not in text
    assert "milvus.internal" not in text
    assert response.json()["detail"]["code"] == "KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE"


def test_no_forbidden_rag_routes_are_registered(monkeypatch):
    from app.main import create_app

    paths = {route.path for route in create_app().routes}

    assert not any(path.startswith("/merchant/rag") for path in paths)
    assert not any(path.startswith("/admin/rag") for path in paths)
