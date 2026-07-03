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


def _db_rows(query, params=()):
    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        return conn.execute(query, params).fetchall()


def _seed_chunks(document_payload, chunks):
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_document

    document_id = create_document(KnowledgeDocumentCreate(**document_payload))
    with connect() as conn:
        for index, chunk_data in enumerate(chunks, start=1):
            if len(chunk_data) == 2:
                chunk_text, embedding_json = chunk_data
                category_id = None
                category_key = None
            else:
                chunk_text, embedding_json, category_id, category_key = chunk_data
            conn.execute(
                """
                INSERT INTO knowledge_chunks(
                  document_id, tenant_id, merchant_id, douyin_account_id,
                  chunk_text, chunk_index, embedding_json, embedding_model,
                  category_id, category_key, content_hash, is_active
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
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
                    category_id,
                    category_key,
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


def test_can_create_system_base_category(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeCategoryCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_category, list_categories

    category = create_category(
        KnowledgeCategoryCreate(
            tenant_id="demo_tenant",
            merchant_id=None,
            category_key="base",
            name="基础知识",
            scope_type="system",
            is_base=True,
            sort_order=1,
        )
    )

    assert category.category_key == "base"
    assert category.scope_type == "system"
    assert category.merchant_id is None
    assert category.is_base is True

    categories = list_categories(tenant_id="demo_tenant", merchant_id="merchant_a")
    assert [item.category_key for item in categories] == ["base"]


def test_can_create_merchant_category_and_isolate_merchants(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeCategoryCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_category, list_categories

    create_category(
        KnowledgeCategoryCreate(
            tenant_id="demo_tenant",
            merchant_id=None,
            category_key="base",
            name="基础知识",
            scope_type="system",
            is_base=True,
        )
    )
    create_category(
        KnowledgeCategoryCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            category_key="bba",
            name="精品BBA",
            scope_type="merchant",
            is_base=False,
        )
    )
    create_category(
        KnowledgeCategoryCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_b",
            category_key="finance",
            name="金融方案",
            scope_type="merchant",
            is_base=False,
        )
    )

    merchant_a_keys = [item.category_key for item in list_categories("demo_tenant", "merchant_a")]
    merchant_b_keys = [item.category_key for item in list_categories("demo_tenant", "merchant_b")]

    assert merchant_a_keys == ["base", "bba"]
    assert merchant_b_keys == ["base", "finance"]


def test_create_category_rejects_invalid_scope_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeCategoryCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_category

    with pytest.raises(ValueError, match="system category merchant_id must be empty"):
        create_category(
            KnowledgeCategoryCreate(
                tenant_id="demo_tenant",
                merchant_id="merchant_a",
                category_key="base",
                name="基础知识",
                scope_type="system",
                is_base=True,
            )
        )

    with pytest.raises(ValueError, match="merchant category merchant_id is required"):
        create_category(
            KnowledgeCategoryCreate(
                tenant_id="demo_tenant",
                merchant_id=None,
                category_key="bba",
                name="精品BBA",
                scope_type="merchant",
            )
        )


def test_train_syncs_document_category_fields_to_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest
    from apps.xg_douyin_ai_cs.rag.repository import create_document, train_scope

    document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
            title="精品BBA话术",
            content="宝马5系客户询价时，先确认预算和到店时间。",
            category="旧分类文本",
            category_id=7,
            category_key="bba",
        )
    )

    result = train_scope(
        RagTrainRequest(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
        ),
        llm_client=_StaticEmbeddingClient({"宝马5系客户询价时，先确认预算和到店时间。": [1.0, 0.0]}),
    )

    assert result["status"] == "completed"
    rows = _db_rows(
        """
        SELECT category_id, category_key
        FROM knowledge_chunks
        WHERE document_id=?
        """,
        (document_id,),
    )
    assert [(row["category_id"], row["category_key"]) for row in rows] == [(7, "bba")]


def test_rag_documents_api_accepts_category_id_and_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/rag/documents",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "merchant_a",
            "douyin_account_id": 1,
            "title": "新能源话术",
            "content": "新能源客户关注电池和金融方案。",
            "category": "旧分类文本",
            "category_id": 9,
            "category_key": "new_energy",
        },
    )

    assert response.status_code == 200
    rows = _db_rows(
        """
        SELECT category, category_id, category_key
        FROM knowledge_documents
        WHERE id=?
        """,
        (response.json()["document_id"],),
    )
    assert [(row["category"], row["category_id"], row["category_key"]) for row in rows] == [
        ("旧分类文本", 9, "new_energy")
    ]


def test_document_without_category_still_trains_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest
    from apps.xg_douyin_ai_cs.rag.repository import create_document, train_scope

    document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
            title="无分类旧文档",
            content="旧文档不传分类字段也必须可以训练。",
        )
    )

    result = train_scope(
        RagTrainRequest(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
        ),
        llm_client=_StaticEmbeddingClient({"旧文档不传分类字段也必须可以训练。": [1.0, 0.0]}),
    )

    assert result["status"] == "completed"
    rows = _db_rows(
        """
        SELECT category_id, category_key
        FROM knowledge_chunks
        WHERE document_id=?
        """,
        (document_id,),
    )
    assert [(row["category_id"], row["category_key"]) for row in rows] == [(None, None)]


def test_train_sqlite_backend_does_not_touch_milvus(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.delenv("RAG_VECTOR_BACKEND", raising=False)

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest
    from apps.xg_douyin_ai_cs.rag import repository

    repository.create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
            title="sqlite only",
            content="sqlite backend should not touch milvus",
            category_key="base",
        )
    )
    monkeypatch.setattr(
        repository,
        "get_vector_store",
        lambda: (_ for _ in ()).throw(AssertionError("milvus should not be touched")),
    )

    result = repository.train_scope(
        RagTrainRequest(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
        ),
        llm_client=_StaticEmbeddingClient({"sqlite backend should not touch milvus": [1.0, 0.0]}),
    )

    assert result["status"] == "completed"


def test_train_milvus_backend_deletes_and_upserts_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest
    from apps.xg_douyin_ai_cs.rag import repository

    document_id = repository.create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id="account-open-id",
            title="milvus sync",
            content="milvus backend should upsert synthetic chunk",
            source_type="manual",
            category_id=7,
            category_key="base",
        )
    )
    fake_store = _FakeVectorStore()
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)

    result = repository.train_scope(
        RagTrainRequest(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id="account-open-id",
        ),
        llm_client=_StaticEmbeddingClient({"milvus backend should upsert synthetic chunk": [1.0, 0.0]}),
    )

    assert result["status"] == "completed"
    assert fake_store.deleted_documents == [
        {
            "document_id": str(document_id),
            "tenant_id": "demo_tenant",
            "merchant_id": "merchant_a",
        }
    ]
    assert fake_store.upserted_chunks[0]["document_id"] == str(document_id)
    assert fake_store.upserted_chunks[0]["tenant_id"] == "demo_tenant"
    assert fake_store.upserted_chunks[0]["merchant_id"] == "merchant_a"
    assert fake_store.upserted_chunks[0]["douyin_account_id"] == "account-open-id"
    assert fake_store.upserted_chunks[0]["category_key"] == "base"
    assert fake_store.upserted_chunks[0]["category_id"] == "7"
    assert fake_store.upserted_chunks[0]["embedding"] == [1.0, 0.0]


def test_train_milvus_backend_marks_run_failed_when_upsert_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagTrainRequest
    from apps.xg_douyin_ai_cs.rag import repository
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreError

    repository.create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
            title="milvus fail",
            content="milvus upsert failure should fail training",
            category_key="base",
        )
    )
    monkeypatch.setattr(
        repository,
        "get_vector_store",
        lambda: _FakeVectorStore(upsert_error=VectorStoreError("MILVUS_UPSERT_FAILED", "details redacted")),
    )

    with pytest.raises(VectorStoreError):
        repository.train_scope(
            RagTrainRequest(
                tenant_id="demo_tenant",
                merchant_id="merchant_a",
                douyin_account_id=1,
            ),
            llm_client=_StaticEmbeddingClient({"milvus upsert failure should fail training": [1.0, 0.0]}),
        )

    rows = _db_rows("SELECT status, chunk_count, error FROM rag_training_runs")
    assert [(row["status"], row["chunk_count"]) for row in rows] == [("failed", 1)]
    assert "MILVUS_UPSERT_FAILED" in rows[0]["error"]


class _FakeVectorStore:
    def __init__(self, upsert_error=None, search_error=None, search_results=None):
        self.upsert_error = upsert_error
        self.search_error = search_error
        self.search_results = search_results or []
        self.deleted_documents = []
        self.upserted_chunks = []
        self.search_calls = []

    def delete_document(self, *, document_id, tenant_id, merchant_id):
        self.deleted_documents.append(
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
            }
        )

    def upsert_chunks(self, chunks):
        if self.upsert_error is not None:
            raise self.upsert_error
        self.upserted_chunks.extend(chunks)

    def search(self, payload, *, query_embedding):
        self.search_calls.append(
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "category_keys": payload.category_keys,
                "query_embedding": query_embedding,
            }
        )
        if self.search_error is not None:
            raise self.search_error
        return self.search_results


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


def test_rag_documents_train_search_accepts_account_open_id_string(tmp_path, monkeypatch):
    """9000 可信代理会把 account_open_id 字符串传给 9100 的 douyin_account_id。"""
    client = _client(tmp_path, monkeypatch)

    created = client.post(
        "/rag/documents",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "dev-merchant",
            "douyin_account_id": "dev-merchant-p5-account",
            "title": "P5验收知识文档",
            "content": "P5专属验收答案是：蓝色星河套餐适合预算20万以内客户。",
            "category_key": "p5_acceptance_test",
        },
    )

    assert created.status_code == 200
    document_id = created.json()["document_id"]

    trained = client.post(
        "/rag/train",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "dev-merchant",
            "douyin_account_id": "dev-merchant-p5-account",
        },
    )

    assert trained.status_code == 200
    assert trained.json()["status"] == "completed"
    assert trained.json()["document_count"] == 1
    assert trained.json()["chunk_count"] >= 1

    search = client.post(
        "/rag/search",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "dev-merchant",
            "douyin_account_id": "dev-merchant-p5-account",
            "query": "预算20万以内蓝色星河套餐",
            "top_k": 5,
            "category_keys": ["p5_acceptance_test"],
        },
    )

    assert search.status_code == 200
    items = search.json()["items"]
    assert items
    assert items[0]["document_id"] == document_id


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


def test_search_without_category_filter_keeps_existing_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "未过滤分类知识",
            "content": "宝马金融方案\n宝马置换方案",
        },
        [
            ("宝马金融方案", "[1.0, 0.0]", 1, "finance"),
            ("宝马置换方案", "[0.8, 0.2]", 2, "trade_in"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="宝马方案",
            top_k=5,
        ),
        llm_client=_StaticEmbeddingClient({"宝马方案": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["宝马金融方案", "宝马置换方案"]


def test_search_filters_by_category_id_in_sql_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "分类ID过滤知识",
            "content": "新能源电池质保\n精品BBA保养政策",
        },
        [
            ("新能源电池质保", "[1.0, 0.0]", 11, "new_energy"),
            ("精品BBA保养政策", "[0.9, 0.1]", 22, "bba"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="保养政策",
            top_k=5,
            category_ids=["22"],
        ),
        llm_client=_StaticEmbeddingClient({"保养政策": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["精品BBA保养政策"]


def test_search_filters_by_category_key_in_sql_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "分类Key过滤知识",
            "content": "金融方案首付比例\n精品代步车保养",
        },
        [
            ("金融方案首付比例", "[1.0, 0.0]", 31, "finance"),
            ("精品代步车保养", "[0.9, 0.1]", 32, "commuter"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="保养",
            top_k=5,
            category_keys=["commuter"],
        ),
        llm_client=_StaticEmbeddingClient({"保养": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["精品代步车保养"]


def test_search_same_category_key_does_not_cross_merchant_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant_a",
            "douyin_account_id": 1,
            "title": "商户A知识",
            "content": "商户A的精品BBA政策",
        },
        [("商户A的精品BBA政策", "[1.0, 0.0]", 41, "bba")],
    )
    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant_b",
            "douyin_account_id": 1,
            "title": "商户B知识",
            "content": "商户B的精品BBA政策",
        },
        [("商户B的精品BBA政策", "[1.0, 0.0]", 42, "bba")],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant_a",
            douyin_account_id=1,
            query="精品BBA",
            top_k=5,
            category_keys=["bba"],
        ),
        llm_client=_StaticEmbeddingClient({"精品BBA": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["商户A的精品BBA政策"]


def test_search_category_filter_applies_to_lexical_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "文本兜底分类知识",
            "content": "宝马金融方案\n宝马保养方案",
        },
        [
            ("宝马金融方案", "[1.0, 0.0]", 51, "finance"),
            ("宝马保养方案", "[0.0, 1.0]", 52, "maintenance"),
        ],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="宝马方案",
            top_k=5,
            category_keys=["maintenance"],
        ),
        llm_client=_StaticEmbeddingClient({"宝马方案": RuntimeError("embedding down")}),
    )

    assert [item.chunk_text for item in results] == ["宝马保养方案"]


def test_search_unknown_category_returns_empty_results(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag.repository import search

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "未知分类过滤知识",
            "content": "宝马金融方案",
        },
        [("宝马金融方案", "[1.0, 0.0]", 61, "finance")],
    )

    results = search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="宝马金融",
            top_k=5,
            category_keys=["not_exists"],
        ),
        llm_client=_StaticEmbeddingClient({"宝马金融": [1.0, 0.0]}),
    )

    assert results == []


def test_search_milvus_backend_uses_vector_store(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import RagSearchItem, RagSearchRequest
    from apps.xg_douyin_ai_cs.rag import repository

    fake_store = _FakeVectorStore(
        search_results=[
            RagSearchItem(
                chunk_id=101,
                document_id=201,
                title="milvus title",
                chunk_text="milvus chunk",
                score=0.91,
            )
        ]
    )
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)

    results = repository.search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="milvus query",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient({"milvus query": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["milvus chunk"]
    assert fake_store.search_calls == [
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "category_keys": ["base"],
            "query_embedding": [1.0, 0.0],
        }
    ]


def test_search_milvus_backend_empty_category_keys_does_not_touch_store(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(
        repository,
        "get_vector_store",
        lambda: (_ for _ in ()).throw(AssertionError("milvus should not be touched")),
    )

    results = repository.search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="query",
            top_k=5,
            category_keys=[],
        ),
        llm_client=_StaticEmbeddingClient({"query": [1.0, 0.0]}),
    )

    assert results == []


def test_search_milvus_backend_missing_scope_does_not_touch_store(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(
        repository,
        "get_vector_store",
        lambda: (_ for _ in ()).throw(AssertionError("milvus should not be touched")),
    )

    results = repository.search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="",
            douyin_account_id=1,
            query="query",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient({"query": [1.0, 0.0]}),
    )

    assert results == []


def test_search_milvus_backend_falls_back_to_sqlite_when_store_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")

    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
    from apps.xg_douyin_ai_cs.rag import repository
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreError

    _seed_chunks(
        {
            "tenant_id": "tenant",
            "merchant_id": "merchant",
            "douyin_account_id": 1,
            "title": "sqlite fallback title",
            "content": "sqlite fallback chunk",
        },
        [("sqlite fallback chunk", "[1.0, 0.0]", 1, "base")],
    )
    fake_store = _FakeVectorStore(search_error=VectorStoreError("MILVUS_SEARCH_FAILED", "details redacted"))
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)

    results = repository.search(
        RagSearchRequest(
            tenant_id="tenant",
            merchant_id="merchant",
            douyin_account_id=1,
            query="sqlite fallback",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient({"sqlite fallback": [1.0, 0.0]}),
    )

    assert [item.chunk_text for item in results] == ["sqlite fallback chunk"]
