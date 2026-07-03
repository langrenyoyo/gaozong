import sys

import pytest


def _clear_milvus_env(monkeypatch):
    for key in (
        "RAG_VECTOR_BACKEND",
        "MILVUS_URI",
        "MILVUS_USERNAME",
        "MILVUS_PASSWORD",
        "MILVUS_DB_NAME",
        "MILVUS_COLLECTION",
        "MILVUS_DIMENSION",
        "MILVUS_TIMEOUT_SECONDS",
        "MILVUS_INDEX_TYPE",
        "MILVUS_METRIC_TYPE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_vector_store_default_backend_is_sqlite(monkeypatch):
    _clear_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import SQLiteVectorStore, get_vector_store

    store = get_vector_store(Settings())

    assert isinstance(store, SQLiteVectorStore)


def test_sqlite_backend_does_not_require_milvus_credentials_or_dependency(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setitem(sys.modules, "pymilvus", None)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import SQLiteVectorStore, get_vector_store

    store = get_vector_store(Settings())

    assert isinstance(store, SQLiteVectorStore)
    assert store.health_check()["backend"] == "sqlite"


def test_unknown_vector_backend_is_rejected(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "unknown")

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreConfigError, get_vector_store

    with pytest.raises(VectorStoreConfigError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "RAG_VECTOR_BACKEND_INVALID"


def test_milvus_backend_missing_required_config_is_rejected(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreConfigError, get_vector_store

    with pytest.raises(VectorStoreConfigError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "MILVUS_CONFIG_MISSING"
    assert "MILVUS_URI" in str(exc_info.value)
    assert "MILVUS_USERNAME" in str(exc_info.value)
    assert "MILVUS_COLLECTION" in str(exc_info.value)
    assert "MILVUS_DIMENSION" in str(exc_info.value)
    assert "secret-password-should-not-leak" not in str(exc_info.value)


def test_milvus_backend_missing_username_is_rejected(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "1536")

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreConfigError, get_vector_store

    with pytest.raises(VectorStoreConfigError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "MILVUS_CONFIG_MISSING"
    assert "MILVUS_USERNAME" in str(exc_info.value)
    assert "secret-password-should-not-leak" not in str(exc_info.value)


def test_milvus_backend_missing_password_is_rejected(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "1536")

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreConfigError, get_vector_store

    with pytest.raises(VectorStoreConfigError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "MILVUS_CONFIG_MISSING"
    assert "MILVUS_PASSWORD" in str(exc_info.value)


def test_milvus_backend_missing_dependency_is_rejected_without_password_leak(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "1536")
    monkeypatch.setitem(sys.modules, "pymilvus", None)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreDependencyError, get_vector_store

    with pytest.raises(VectorStoreDependencyError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "MILVUS_DEPENDENCY_MISSING"
    assert "secret-password-should-not-leak" not in str(exc_info.value)
