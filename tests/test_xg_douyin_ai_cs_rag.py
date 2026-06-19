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
