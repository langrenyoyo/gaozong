import pytest
from fastapi.testclient import TestClient


class _StaticEmbeddingClient:
    def __init__(self, embedding_by_text):
        self.embedding_by_text = embedding_by_text

    def embed(self, text):
        value = self.embedding_by_text[text]
        if isinstance(value, Exception):
            raise value
        return {"embedding": value, "model": "test_embedding_model"}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def _seed_chunks(document_payload, chunks):
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_document

    document_id = create_document(KnowledgeDocumentCreate(**document_payload))
    with connect() as conn:
        for index, (chunk_text, embedding_json) in enumerate(chunks, start=1):
            conn.execute(
                """
                INSERT INTO knowledge_chunks(
                  document_id, tenant_id, merchant_id, douyin_account_id,
                  chunk_text, chunk_index, embedding_json, embedding_model,
                  content_hash, is_active
                ) VALUES(?,?,?,?,?,?,?,?,?,1)
                """,
                (
                    document_id,
                    document_payload["tenant_id"],
                    document_payload["merchant_id"],
                    document_payload["douyin_account_id"],
                    chunk_text,
                    index,
                    embedding_json,
                    "test_embedding_model",
                    f"test-hash-{document_id}-{index}",
                ),
            )
        conn.commit()
    return document_id


def test_chunker_splits_short_long_and_rejects_empty_content():
    from apps.xg_douyin_ai_cs.rag.chunker import chunk_text

    assert chunk_text("短内容", chunk_size=500, overlap=80) == ["短内容"]

    long_text = "奥迪A6客户留资话术。" * 80
    chunks = chunk_text(long_text, chunk_size=120, overlap=20)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)

    with pytest.raises(ValueError, match="content must not be empty"):
        chunk_text("   ")


def test_rag_documents_train_search_and_scope_isolation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    payload = {
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "douyin_account_id": 1,
        "title": "精品BBA主营车型和留资话术",
        "category": "sales_script",
        "brand": "奥迪",
        "vehicle_name": "奥迪A6",
        "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6时，应引导客户留下联系方式。",
    }
    created = client.post("/rag/documents", json=payload)
    assert created.status_code == 200
    assert created.json()["status"] == "created"

    trained = client.post(
        "/rag/train",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
        },
    )
    assert trained.status_code == 200
    train_data = trained.json()
    assert train_data["status"] == "completed"
    assert train_data["document_count"] == 1
    assert train_data["chunk_count"] >= 1

    search = client.post(
        "/rag/search",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
            "query": "客户问奥迪A6怎么回复",
            "top_k": 5,
        },
    )
    assert search.status_code == 200
    items = search.json()["items"]
    assert items
    assert items[0]["document_id"] == created.json()["document_id"]
    assert items[0]["title"] == "精品BBA主营车型和留资话术"

    other_merchant_search = client.post(
        "/rag/search",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "other_merchant",
            "douyin_account_id": 1,
            "query": "奥迪A6",
            "top_k": 5,
        },
    )
    assert other_merchant_search.status_code == 200
    assert other_merchant_search.json()["items"] == []

    other_tenant_search = client.post(
        "/rag/search",
        json={
            "tenant_id": "other_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
            "query": "奥迪A6",
            "top_k": 5,
        },
    )
    assert other_tenant_search.status_code == 200
    assert other_tenant_search.json()["items"] == []

    other_account_search = client.post(
        "/rag/search",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 2,
            "query": "奥迪A6",
            "top_k": 5,
        },
    )
    assert other_account_search.status_code == 200
    assert other_account_search.json()["items"] == []


def test_cosine_similarity_handles_valid_and_invalid_vectors():
    from apps.xg_douyin_ai_cs.rag.repository import cosine_similarity

    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0, 0.0]) == 0.0
    assert cosine_similarity(None, [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_search_uses_embedding_json_vector_order(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "向量排序知识",
            "content": "宝马优惠信息\n奥迪保养政策",
        },
        [
            ("宝马优惠信息", "[0.0, 1.0]"),
            ("奥迪保养政策", "[1.0, 0.0]"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="宝马优惠",
            top_k=2,
        ),
        llm_client=_StaticEmbeddingClient({"宝马优惠": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["奥迪保养政策", "宝马优惠信息"]
    assert results[0].score > results[1].score


def test_search_falls_back_to_lexical_when_query_embedding_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "文本兜底知识",
            "content": "奔驰报价\n奥迪保养",
        },
        [
            ("奔驰报价", "[0.0, 1.0]"),
            ("奥迪保养", "[1.0, 0.0]"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="奔驰报价",
            top_k=2,
        ),
        llm_client=_StaticEmbeddingClient({"奔驰报价": RuntimeError("embedding down")}),
    )

    assert [item.chunk_text for item in results] == ["奔驰报价"]


def test_search_skips_invalid_chunk_embedding_without_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "非法向量知识",
            "content": "有效向量内容\n坏向量内容",
        },
        [
            ("有效向量内容", "[1.0, 0.0]"),
            ("坏向量内容", "not-json"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="有效",
            top_k=5,
        ),
        llm_client=_StaticEmbeddingClient({"有效": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["有效向量内容"]
