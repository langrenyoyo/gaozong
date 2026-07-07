import sqlite3

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def _patch_llm(monkeypatch, *, answer="AI answer"):
    def fake_embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def fake_chat(self, messages):
        return {"reply_text": answer, "model": "mock-chat", "elapsed_ms": 1, "usage": None}

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed", fake_embed)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)


def _ask(client, *, question="客户问价格还能不能优惠？", answer="AI answer"):
    response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "question": question,
            "use_xiaogao_knowledge_base": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["answer"] == answer
    return response.json()


def test_useful_feedback_auto_creates_document_and_trains(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch, answer="先理解客户预算，再说明可以申请专属优惠。")
    ask_data = _ask(client, answer="先理解客户预算，再说明可以申请专属优惠。")

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": "useful",
            "comment": "可用",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "submitted"
    assert data["rag_ingestion"]["status"] == "completed"
    assert data["rag_ingestion"]["document_id"]
    assert data["rag_ingestion"]["training_run_id"]

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        document = conn.execute(
            "SELECT title, content, source_type, category_key FROM knowledge_documents WHERE id=?",
            (int(data["rag_ingestion"]["document_id"]),),
        ).fetchone()
        feedback = conn.execute(
            "SELECT ingestion_status, ingested_document_id, ingestion_training_run_id FROM knowledge_training_feedbacks WHERE training_id=?",
            (ask_data["training_id"],),
        ).fetchone()

    assert document["source_type"] == "douyin_cs_training_feedback"
    assert document["category_key"] == "base"
    assert "客户问价格还能不能优惠？" in document["content"]
    assert "先理解客户预算，再说明可以申请专属优惠。" in document["content"]
    assert feedback["ingestion_status"] == "completed"
    assert str(feedback["ingested_document_id"]) == data["rag_ingestion"]["document_id"]
    assert str(feedback["ingestion_training_run_id"]) == data["rag_ingestion"]["training_run_id"]


def test_ask_uses_unified_account_scope_even_when_payload_has_account_id(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch, answer="hit unified kb")

    from apps.xg_douyin_ai_cs.rag import repository

    monkeypatch.setattr(
        repository,
        "OpenAICompatibleClient",
        lambda: type("Embedder", (), {"embed": lambda self, text: {"embedding": [1.0, 0.0], "model": "test_embedding_model"}})(),
    )
    created = client.post(
        "/knowledge-training/documents",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "title": "scope regression",
            "content": "SMOKE_SCOPE_PRICE_NEGOTIATION answer stored under account zero",
            "category_key": "base",
            "source_type": "manual_text",
        },
    )
    document_id = created.json()["document_id"]
    trained = client.post(
        f"/knowledge-training/documents/{document_id}/train",
        json={"tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base", "mode": "rebuild_document"},
    )
    assert trained.status_code == 200

    response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "douyin_account_id": "1",
            "question": "SMOKE_SCOPE_PRICE_NEGOTIATION",
            "use_xiaogao_knowledge_base": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["used_knowledge_base"] is True

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        session = conn.execute(
            "SELECT douyin_account_id FROM knowledge_training_sessions WHERE training_id=?",
            (response.json()["training_id"],),
        ).fetchone()
    assert int(session["douyin_account_id"]) == 0


@pytest.mark.parametrize("rating", ["useful", "normal", "wrong"])
def test_corrected_answer_auto_creates_document_even_when_rating_is_not_useful(tmp_path, monkeypatch, rating):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch, answer="AI answer")
    ask_data = _ask(client)

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": rating,
            "corrected_answer": "修正后应先共情，再引导留下电话核价。",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rag_ingestion"]["status"] == "completed"
    assert data["rag_ingestion"]["answer_source"] == "corrected_answer"


@pytest.mark.parametrize("rating", ["normal", "wrong"])
def test_normal_or_wrong_without_corrected_answer_only_saves_feedback(tmp_path, monkeypatch, rating):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch)
    ask_data = _ask(client)

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": rating,
        },
    )

    assert response.status_code == 200
    assert response.json()["rag_ingestion"] == {
        "enabled": True,
        "triggered": False,
        "status": "skipped",
        "reason": "rating_not_ingestable",
    }


def test_auto_ingest_false_only_saves_feedback(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch)
    ask_data = _ask(client)

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": "useful",
            "auto_ingest": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["rag_ingestion"] == {
        "enabled": False,
        "triggered": False,
        "status": "skipped",
        "reason": "auto_ingest_disabled",
    }


def test_duplicate_useful_feedback_reuses_existing_ingestion(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch)
    ask_data = _ask(client)
    payload = {
        "tenant_id": "xiaogao_system",
        "merchant_id": "xiaogao_base",
        "rating": "useful",
    }

    first = client.post(f"/knowledge-training/{ask_data['training_id']}/feedback", json=payload)
    second = client.post(f"/knowledge-training/{ask_data['training_id']}/feedback", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["rag_ingestion"]["status"] == "completed"
    assert second.json()["rag_ingestion"]["reason"] == "already_ingested"
    assert second.json()["rag_ingestion"]["document_id"] == first.json()["rag_ingestion"]["document_id"]

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_documents WHERE source_type='douyin_cs_training_feedback'"
        ).fetchone()["count"]
    assert count == 1


def test_ingestion_failure_keeps_feedback(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch)
    ask_data = _ask(client)

    def fail_train_document(**kwargs):
        raise RuntimeError("synthetic train failure")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.rag.repository.train_document", fail_train_document)

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": "useful",
        },
    )

    assert response.status_code == 200
    assert response.json()["rag_ingestion"]["status"] == "failed"
    assert response.json()["rag_ingestion"]["reason"] == "ingestion_failed"

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        feedback = conn.execute(
            "SELECT status, ingestion_status FROM knowledge_training_feedbacks WHERE training_id=?",
            (ask_data["training_id"],),
        ).fetchone()
    assert feedback["status"] == "submitted"
    assert feedback["ingestion_status"] == "failed"


def test_legacy_feedback_table_is_auto_upgraded(tmp_path, monkeypatch):
    db_path = tmp_path / "xg_douyin_ai_cs.db"
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(db_path))
    from apps.xg_douyin_ai_cs.rag.database import connect

    with sqlite3.connect(db_path) as raw:
        raw.execute(
            """
            CREATE TABLE knowledge_training_feedbacks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              training_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              merchant_id TEXT NOT NULL,
              rating TEXT NOT NULL,
              comment TEXT,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        raw.commit()

    with connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(knowledge_training_feedbacks)").fetchall()}

    assert {
        "corrected_answer",
        "auto_ingest",
        "ingestion_status",
        "ingested_document_id",
        "ingestion_training_run_id",
        "ingestion_error",
        "answer_hash",
    }.issubset(columns)
