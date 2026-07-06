from __future__ import annotations

from fastapi.testclient import TestClient


class _StaticEmbeddingClient:
    def embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.delenv("RAG_VECTOR_BACKEND", raising=False)
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def _create_document(client: TestClient, *, title: str = "基础接待规则", content: str = "客户问车况时先确认预算。"):
    return client.post(
        "/knowledge-training/documents",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "title": title,
            "content": content,
            "category_key": "base",
            "source_type": "manual_text",
        },
    )


def test_unified_categories_returns_base_without_vector_fields(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get(
        "/knowledge-training/categories",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"][0]["key"] == "base"
    text = str(payload).lower()
    assert "collection" not in text
    assert "vector_id" not in text
    assert "milvus" not in text
    assert "qdrant" not in text


def test_unified_document_create_list_detail_update_and_delete(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    created = _create_document(client)
    assert created.status_code == 200
    document_id = created.json()["document_id"]
    assert created.json()["status"] == "draft"
    assert created.json()["category_key"] == "base"

    other = client.post(
        "/knowledge-training/documents",
        json={
            "tenant_id": "other_tenant",
            "merchant_id": "xiaogao_base",
            "title": "其他租户",
            "content": "其他租户内容",
            "category_key": "base",
            "source_type": "manual_text",
        },
    )
    assert other.status_code == 200

    listed = client.get(
        "/knowledge-training/documents",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "category_key": "base"},
    )
    assert listed.status_code == 200
    assert [item["document_id"] for item in listed.json()["items"]] == [document_id]

    detail = client.get(
        f"/knowledge-training/documents/{document_id}",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"},
    )
    assert detail.status_code == 200
    assert detail.json()["content"] == "客户问车况时先确认预算。"

    missing = client.get(
        "/knowledge-training/documents/missing",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "RAG_DOCUMENT_NOT_FOUND"

    updated = client.put(
        f"/knowledge-training/documents/{document_id}",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "title": "基础接待规则更新",
            "content": "更新后需要重新训练。",
            "category_key": "base",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "draft"

    deleted = client.request(
        "DELETE",
        f"/knowledge-training/documents/{document_id}",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "soft_delete"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_unified_document_create_validates_manual_text_and_content(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    empty = client.post(
        "/knowledge-training/documents",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "title": "空正文",
            "content": " ",
            "category_key": "base",
            "source_type": "manual_text",
        },
    )
    unsupported = client.post(
        "/knowledge-training/documents",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "title": "文件",
            "content": "正文",
            "category_key": "base",
            "source_type": "upload_file",
        },
    )

    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "RAG_INVALID_DOCUMENT"
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["code"] == "RAG_UNSUPPORTED_OPERATION"


def test_unified_train_rebuild_document_and_training_runs(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(repository, "OpenAICompatibleClient", _StaticEmbeddingClient)
    document_id = _create_document(client, content="单文档训练 synthetic 内容").json()["document_id"]

    denied = client.post(
        f"/knowledge-training/documents/{document_id}/train",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "rebuild_all"},
    )
    trained = client.post(
        f"/knowledge-training/documents/{document_id}/train",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "rebuild_document"},
    )

    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "RAG_UNSUPPORTED_OPERATION"
    assert trained.status_code == 200
    run_id = trained.json()["training_run_id"]
    assert trained.json()["document_id"] == document_id
    assert trained.json()["status"] == "completed"
    assert trained.json()["chunk_count"] >= 1

    run_detail = client.get(
        f"/knowledge-training/training-runs/{run_id}",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"},
    )
    assert run_detail.status_code == 200
    assert run_detail.json()["training_run_id"] == run_id
    assert run_detail.json()["document_id"] == document_id

    run_list = client.get(
        "/knowledge-training/training-runs",
        params={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "document_id": document_id},
    )
    assert run_list.status_code == 200
    assert [item["training_run_id"] for item in run_list.json()["items"]] == [run_id]


def test_unified_training_error_is_sanitized(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from apps.xg_douyin_ai_cs.rag import repository

    class BrokenEmbeddingClient:
        def embed(self, text):
            raise RuntimeError("credential_marker=TEST_ONLY http://example.invalid")

    monkeypatch.setattr(repository, "OpenAICompatibleClient", BrokenEmbeddingClient)
    document_id = _create_document(client, content="训练失败 synthetic 内容").json()["document_id"]

    response = client.post(
        f"/knowledge-training/documents/{document_id}/train",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "rebuild_document"},
    )

    assert response.status_code == 502
    payload_text = str(response.json())
    assert response.json()["detail"]["code"] == "RAG_TRAINING_FAILED"
    assert "TEST_ONLY" not in payload_text
    assert "example.invalid" not in payload_text


def test_unified_search_preview_returns_sanitized_matches_and_limits_top_k(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(repository, "OpenAICompatibleClient", _StaticEmbeddingClient)
    document_id = _create_document(client, title="检索预览知识", content="客户询问是否还有现车时，先确认车型。").json()[
        "document_id"
    ]
    client.post(
        f"/knowledge-training/documents/{document_id}/train",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "rebuild_document"},
    )

    response = client.post(
        "/knowledge-training/search-preview",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "query": "客户问还有现车吗",
            "category_keys": ["base"],
            "top_k": 5,
        },
    )
    too_large = client.post(
        "/knowledge-training/search-preview",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "query": "客户问还有现车吗",
            "category_keys": ["base"],
            "top_k": 11,
        },
    )

    assert response.status_code == 200
    assert response.json()["matches"]
    assert response.json()["matches"][0]["document_id"] == document_id
    assert set(response.json()["matches"][0]) == {"document_id", "title", "category_key", "chunk_text", "score"}
    assert too_large.status_code == 422


def test_unified_search_preview_empty_categories_does_not_search(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(
        repository,
        "search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("search should not be called")),
    )

    response = client.post(
        "/knowledge-training/search-preview",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "query": "客户问还有现车吗",
            "category_keys": [],
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["matches"] == []


def test_unified_adapter_does_not_register_forbidden_routes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paths = {route.path for route in client.app.routes}

    assert not any(path.startswith("/merchant/rag") for path in paths)
    assert not any(path.startswith("/admin/rag") for path in paths)
