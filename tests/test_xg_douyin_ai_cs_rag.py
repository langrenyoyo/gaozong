import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


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
