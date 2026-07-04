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
    assert result["cleanup_verified"] is True
    assert result["delete_verify_attempts"] == 1
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
    assert result["cleanup_ok"] is False
    assert result["cleanup_verified"] is False
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

    def fake_run_canary_e2e(config, document_id=None):
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


def test_canary_cli_outputs_full_document_id(monkeypatch, capsys):
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    full_document_id = "canary_doc_1234567890abcdef44d93a"
    result = milvus_canary_e2e._base_result(full_document_id)
    result.update(
        connected=True,
        collection_exists=True,
        schema_match=True,
        upsert_ok=True,
        search_hit=True,
        delete_ok=True,
        search_after_delete_hit=False,
        cleanup_ok=True,
        cleanup_verified=True,
        delete_verify_attempts=2,
        phase="complete",
        error_code="OK",
    )

    output = milvus_canary_e2e._format_result(result)

    assert f"canary_document_id={full_document_id}" in output
    assert "canary_doc_1..." not in output


def test_canary_cli_document_id_reuses_specified_id(monkeypatch):
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "4")
    seen = {}

    def fake_run_canary_e2e(config, document_id=None):
        seen["document_id"] = document_id
        return {
            "canary_document_id": document_id,
            "connected": True,
            "collection_exists": True,
            "schema_match": True,
            "upsert_ok": True,
            "search_hit": True,
            "delete_ok": True,
            "search_after_delete_hit": False,
            "cleanup_ok": True,
            "cleanup_verified": True,
            "delete_verify_attempts": 1,
            "phase": "complete",
            "error_code": "OK",
        }

    monkeypatch.setattr(milvus_canary_e2e, "run_canary_e2e", fake_run_canary_e2e)

    exit_code = milvus_canary_e2e.main(["--run", "--document-id", "canary_doc_fixed_001"])

    assert exit_code == 0
    assert seen["document_id"] == "canary_doc_fixed_001"


def test_cleanup_only_uses_full_document_id(monkeypatch, capsys):
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "4")
    full_document_id = "canary_doc_1234567890abcdef44d93a"
    seen = {}

    def fake_cleanup_only(config, document_id):
        seen["document_id"] = document_id
        return {
            "canary_document_id": document_id,
            "connected": "unknown",
            "collection_exists": "unknown",
            "schema_match": "unknown",
            "upsert_ok": False,
            "search_hit": False,
            "delete_ok": True,
            "search_after_delete_hit": False,
            "cleanup_ok": True,
            "cleanup_verified": True,
            "delete_verify_attempts": 0,
            "phase": "cleanup",
            "error_code": "OK",
        }

    monkeypatch.setattr(milvus_canary_e2e, "cleanup_only", fake_cleanup_only)

    exit_code = milvus_canary_e2e.main(["--cleanup-only", full_document_id])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert seen["document_id"] == full_document_id
    assert f"canary_document_id={full_document_id}" in output


def test_cleanup_only_deletes_full_document_id_and_verifies(monkeypatch):
    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    full_document_id = "canary_doc_1234567890abcdef44d93a"
    store = FakeCanaryStore(search_hits=[False])
    monkeypatch.setattr(milvus_canary_e2e, "get_vector_store", lambda config: store)

    result = milvus_canary_e2e.cleanup_only(config=Settings(), document_id=full_document_id)

    assert result["canary_document_id"] == full_document_id
    assert result["delete_ok"] is True
    assert result["search_after_delete_hit"] is False
    assert result["cleanup_verified"] is True
    assert result["cleanup_ok"] is True
    assert store.deleted_documents == [
        {
            "document_id": full_document_id,
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
        }
    ]


def test_canary_e2e_retries_until_delete_is_visible():
    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    store = FakeCanaryStore(search_hits=[True, True, False])

    result = milvus_canary_e2e.run_canary_e2e(
        config=Settings(),
        store=store,
        document_id="1001",
        chunk_id="2001",
        marker="CANARY_MILVUS_E2E_TEST_MARKER",
        retry_interval_seconds=0,
    )

    assert result["delete_ok"] is True
    assert result["search_after_delete_hit"] is False
    assert result["cleanup_verified"] is True
    assert result["cleanup_ok"] is True
    assert result["delete_verify_attempts"] == 2
    assert store.search_count == 3


def test_canary_e2e_reports_cleanup_unverified_when_delete_remains_visible():
    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    store = FakeCanaryStore(search_hits=[True, True, True, True, True, True])

    result = milvus_canary_e2e.run_canary_e2e(
        config=Settings(),
        store=store,
        document_id="1001",
        chunk_id="2001",
        marker="CANARY_MILVUS_E2E_TEST_MARKER",
        retry_interval_seconds=0,
    )

    assert result["delete_ok"] is True
    assert result["search_after_delete_hit"] is True
    assert result["cleanup_verified"] is False
    assert result["cleanup_ok"] is False
    assert result["phase"] == "verify_delete"
    assert result["error_code"] == "CANARY_DELETE_NOT_VISIBLE"
    assert result["delete_verify_attempts"] == 5


def test_canary_hit_detection_ignores_marker_when_document_and_chunk_do_not_match():
    from apps.xg_douyin_ai_cs.scripts import milvus_canary_e2e

    result = milvus_canary_e2e._contains_canary_hit(
        [
            SimpleNamespace(
                chunk_id="other_chunk",
                document_id="other_doc",
                chunk_text="CANARY_MILVUS_E2E_TEST_MARKER",
            )
        ],
        document_id="1001",
        chunk_id="2001",
    )

    assert result is False


class FakeCanaryStore:
    def __init__(self, *, search_hits=None, search_error=None):
        self.search_hits = list(search_hits or [])
        self.search_error = search_error
        self.upserted_chunks = []
        self.deleted_documents = []
        self.search_count = 0

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
        self.search_count += 1
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
