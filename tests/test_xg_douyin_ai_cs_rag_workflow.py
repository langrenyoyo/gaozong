import json

import pytest


WORKFLOW_TEXT = "RAG_WORKFLOW_CANARY_UNIT：这是非业务测试知识，用于验证 AI 客服 RAG 检索链路。"


class _StaticEmbeddingClient:
    def __init__(self, embedding_by_text):
        self.embedding_by_text = embedding_by_text

    def embed(self, text):
        return {"embedding": self.embedding_by_text[text], "model": "test_embedding_model"}


class _FakeLLMClient:
    chat_calls = []
    embed_calls = []

    def embed(self, text):
        self.__class__.embed_calls.append(text)
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def chat(self, messages):
        self.__class__.chat_calls.append(messages)
        return {
            "reply_text": json.dumps(
                {
                    "reply_text": "已参考 synthetic 知识生成建议，请人工确认后使用。",
                    "intent": "general_inquiry",
                    "lead_level": "medium",
                    "tags": ["rag_workflow"],
                    "manual_required": False,
                    "manual_required_reason": "",
                    "risk_flags": [],
                    "confidence": 0.88,
                    "auto_send": False,
                },
                ensure_ascii=False,
            ),
            "model": "fake-llm",
            "elapsed_ms": 1,
            "usage": {"total_tokens": 0},
        }


class _FakeVectorStore:
    def __init__(self, *, search_error=None):
        self.search_error = search_error
        self.deleted_documents = []
        self.upserted_chunks = []
        self.search_calls = []

    def delete_document(self, *, document_id, tenant_id, merchant_id):
        self.deleted_documents.append(
            {
                "document_id": str(document_id),
                "tenant_id": str(tenant_id),
                "merchant_id": str(merchant_id),
            }
        )

    def upsert_chunks(self, chunks):
        self.upserted_chunks.extend(chunks)

    def search(self, payload, *, query_embedding):
        self.search_calls.append(
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "douyin_account_id": payload.douyin_account_id,
                "category_keys": payload.category_keys,
                "query_embedding": query_embedding,
            }
        )
        if self.search_error is not None:
            raise self.search_error

        from apps.xg_douyin_ai_cs.rag.models import RagSearchItem

        allowed = {str(item) for item in (payload.category_keys or [])}
        results = []
        for chunk in self.upserted_chunks:
            if str(chunk["tenant_id"]) != str(payload.tenant_id):
                continue
            if str(chunk["merchant_id"]) != str(payload.merchant_id):
                continue
            if str(chunk["douyin_account_id"]) != str(payload.douyin_account_id):
                continue
            if str(chunk["category_key"]) not in allowed:
                continue
            if str(chunk.get("status") or "") != "active":
                continue
            results.append(
                RagSearchItem(
                    chunk_id=int(chunk["chunk_id"]),
                    document_id=int(chunk["document_id"]),
                    title=str(chunk["source_title"]),
                    chunk_text=str(chunk["chunk_text"]),
                    score=0.99,
                )
            )
        return results[: int(payload.top_k)]


def _setup_workflow(tmp_path, monkeypatch, *, fake_store=None):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag import repository
    from apps.xg_douyin_ai_cs.services import reply_decision_service

    _FakeLLMClient.chat_calls = []
    _FakeLLMClient.embed_calls = []
    fake_store = fake_store or _FakeVectorStore()
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(repository, "OpenAICompatibleClient", _FakeLLMClient)
    monkeypatch.setattr(reply_decision_service, "OpenAICompatibleClient", _FakeLLMClient)
    return repository, reply_decision_service, fake_store


def _train_synthetic_document(repository):
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest

    document_id = repository.create_document(
        KnowledgeDocumentCreate(
            tenant_id="new_car_project",
            merchant_id="workflow-merchant",
            douyin_account_id="workflow-account",
            title="RAG Workflow Synthetic Knowledge",
            content=WORKFLOW_TEXT,
            source_type="test_canary",
            category_key="base",
        )
    )
    train_result = repository.train_scope(
        RagTrainRequest(
            tenant_id="new_car_project",
            merchant_id="workflow-merchant",
            douyin_account_id="workflow-account",
        ),
        llm_client=_StaticEmbeddingClient({WORKFLOW_TEXT: [1.0, 0.0]}),
    )
    return document_id, train_result


def _reply_request(*, allowed_category_keys, rag_enabled=True, latest_message="请介绍 synthetic 工作流知识"):
    from apps.xg_douyin_ai_cs.schemas import AgentConfig, ReplySuggestionRequest

    return ReplySuggestionRequest(
        tenant_id="new_car_project",
        merchant_id="workflow-merchant",
        account_id="workflow-account",
        douyin_account_id="workflow-account",
        latest_message=latest_message,
        agent_id="workflow-agent",
        agent_config=AgentConfig(
            agent_id="workflow-agent",
            agent_name="Workflow Agent",
            status="active",
            allowed_category_keys=allowed_category_keys,
            rag_enabled=rag_enabled,
        ),
    )


def test_training_to_milvus_then_reply_suggestion_hits_source_chunks_and_keeps_gate(tmp_path, monkeypatch):
    repository, reply_decision_service, fake_store = _setup_workflow(tmp_path, monkeypatch)
    document_id, train_result = _train_synthetic_document(repository)

    response = reply_decision_service.build_reply_suggestion(
        "workflow-conversation",
        _reply_request(allowed_category_keys=["base"]),
    )

    assert train_result["status"] == "completed"
    assert fake_store.upserted_chunks
    assert fake_store.search_calls == [
        {
            "tenant_id": "new_car_project",
            "merchant_id": "workflow-merchant",
            "douyin_account_id": "workflow-account",
            "category_keys": ["base"],
            "query_embedding": [1.0, 0.0],
        }
    ]
    assert response.rag_used is True
    assert response.llm_used is True
    assert response.auto_send is False
    assert response.manual_required is False
    assert response.source_chunks == [
        {
            "chunk_id": int(fake_store.upserted_chunks[0]["chunk_id"]),
            "document_id": document_id,
            "title": "RAG Workflow Synthetic Knowledge",
            "score": 0.99,
        }
    ]
    assert response.rag_sources == response.source_chunks


def test_reply_suggestion_empty_allowed_categories_skips_milvus_and_returns_no_sources(tmp_path, monkeypatch):
    repository, reply_decision_service, fake_store = _setup_workflow(tmp_path, monkeypatch)
    _train_synthetic_document(repository)

    response = reply_decision_service.build_reply_suggestion(
        "workflow-conversation",
        _reply_request(allowed_category_keys=[], latest_message="客户问价格"),
    )

    assert fake_store.search_calls == []
    assert response.rag_used is False
    assert response.source_chunks == []
    assert response.rag_sources == []
    assert response.auto_send is False
    assert response.manual_required is True


def test_reply_suggestion_other_category_does_not_hit_base_knowledge(tmp_path, monkeypatch):
    repository, reply_decision_service, fake_store = _setup_workflow(tmp_path, monkeypatch)
    _train_synthetic_document(repository)

    response = reply_decision_service.build_reply_suggestion(
        "workflow-conversation",
        _reply_request(allowed_category_keys=["other"], latest_message="客户问价格"),
    )

    assert fake_store.search_calls[0]["category_keys"] == ["other"]
    assert response.rag_used is False
    assert response.source_chunks == []
    assert response.rag_sources == []
    assert response.auto_send is False
    assert response.manual_required is True


def test_reply_suggestion_rag_disabled_skips_milvus(tmp_path, monkeypatch):
    repository, reply_decision_service, fake_store = _setup_workflow(tmp_path, monkeypatch)
    _train_synthetic_document(repository)

    response = reply_decision_service.build_reply_suggestion(
        "workflow-conversation",
        _reply_request(allowed_category_keys=["base"], rag_enabled=False, latest_message="客户问价格"),
    )

    assert fake_store.search_calls == []
    assert response.rag_used is False
    assert response.source_chunks == []
    assert response.auto_send is False
    assert response.manual_required is True


def test_milvus_search_failure_falls_back_to_sqlite_without_relaxing_gate(tmp_path, monkeypatch, caplog):
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreError

    fake_store = _FakeVectorStore(search_error=VectorStoreError("MILVUS_SEARCH_FAILED", "details redacted"))
    repository, reply_decision_service, _ = _setup_workflow(tmp_path, monkeypatch, fake_store=fake_store)
    document_id, _ = _train_synthetic_document(repository)

    with caplog.at_level("WARNING"):
        response = reply_decision_service.build_reply_suggestion(
            "workflow-conversation",
            _reply_request(allowed_category_keys=["base"]),
        )

    assert fake_store.search_calls
    assert "fallback_reason=milvus_search_failed" in caplog.text
    assert response.rag_used is True
    assert response.source_chunks[0]["document_id"] == document_id
    assert response.auto_send is False
