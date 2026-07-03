from types import SimpleNamespace


def test_canary_e2e_upserts_searches_deletes_and_verifies_cleanup():
    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    store = FakeCanaryStore(search_hits=[True, False])

    result = milvus_canary_e2e.run_canary_e2e(
        config=Settings(),
        store=store,
        document_id="1001",
        chunk_id="2001",
        marker="CANARY_MILVUS_E2E_TEST_MARKER",
    )

    assert result["connected"] is True
    assert result["collection_exists"] is True
    assert result["schema_match"] is True
    assert result["upsert_ok"] is True
    assert result["search_hit"] is True
    assert result["delete_ok"] is True
    assert result["search_after_delete_hit"] is False
    assert result["cleanup_ok"] is True
    assert store.upserted_chunks[0]["source_type"] == "test_canary"
    assert store.deleted_documents == [
        {"document_id": "1001", "tenant_id": "xiaogao_system", "merchant_id": "xiaogao_base"}
    ]


def test_canary_e2e_runs_cleanup_when_search_fails():
    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    store = FakeCanaryStore(search_error=RuntimeError("search failed"))

    result = milvus_canary_e2e.run_canary_e2e(
        config=Settings(),
        store=store,
        document_id="1001",
        chunk_id="2001",
        marker="CANARY_MILVUS_E2E_TEST_MARKER",
    )

    assert result["upsert_ok"] is True
    assert result["delete_ok"] is True
    assert result["cleanup_ok"] is True
    assert result["phase"] == "search"
    assert result["error_code"] == "MILVUS_CANARY_SEARCH_FAILED"


def test_canary_cli_output_does_not_leak_sensitive_values(monkeypatch, capsys):
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "4")

    def fake_run_canary_e2e(config):
        return {
            "canary_document_id": "1001",
            "connected": True,
            "collection_exists": True,
            "schema_match": True,
            "upsert_ok": True,
            "search_hit": True,
            "delete_ok": True,
            "search_after_delete_hit": False,
            "cleanup_ok": True,
            "phase": "complete",
            "error_code": "OK",
        }

    monkeypatch.setattr(milvus_canary_e2e, "run_canary_e2e", fake_run_canary_e2e)

    exit_code = milvus_canary_e2e.main(["--run"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "upsert_ok=True" in output
    assert "search_after_delete_hit=False" in output
    assert "milvus.example.test" not in output
    assert "readonly_user" not in output
    assert "secret-password-should-not-leak" not in output
    assert "https://milvus.example.test" not in output
    assert "CANARY_MILVUS_E2E_TEST_MARKER" not in output


class FakeCanaryStore:
    def __init__(self, *, search_hits=None, search_error=None):
        self.search_hits = list(search_hits or [])
        self.search_error = search_error
        self.upserted_chunks = []
        self.deleted_documents = []

    def ensure_collection(self, create_if_missing=False):
        assert create_if_missing is False
        return {
            "connected": True,
            "collection_exists": True,
            "schema_match": True,
            "dimension": 4,
        }

    def upsert_chunks(self, chunks):
        self.upserted_chunks.extend(chunks)
        return {"upserted": len(chunks)}

    def search(self, payload, *, query_embedding):
        if self.search_error is not None:
            raise self.search_error
        hit = self.search_hits.pop(0)
        if not hit:
            return []
        return [
            SimpleNamespace(
                chunk_id=2001,
                document_id=1001,
                chunk_text=self.upserted_chunks[0]["chunk_text"],
                title=self.upserted_chunks[0]["source_title"],
                score=1.0,
            )
        ]

    def delete_document(self, *, document_id, tenant_id, merchant_id):
        self.deleted_documents.append(
            {"document_id": document_id, "tenant_id": tenant_id, "merchant_id": merchant_id}
        )
        return {"deleted": True}
