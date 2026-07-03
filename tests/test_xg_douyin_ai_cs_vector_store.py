import sys
from types import SimpleNamespace

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


def _set_valid_milvus_env(monkeypatch):
    _clear_milvus_env(monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.setenv("MILVUS_USERNAME", "readonly_user")
    monkeypatch.setenv("MILVUS_PASSWORD", "secret-password-should-not-leak")
    monkeypatch.setenv("MILVUS_COLLECTION", "xg_douyin_ai_cs_chunks")
    monkeypatch.setenv("MILVUS_DIMENSION", "1536")


def test_milvus_backend_invalid_dimension_is_rejected(monkeypatch):
    _set_valid_milvus_env(monkeypatch)
    monkeypatch.setenv("MILVUS_DIMENSION", "0")

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreConfigError, get_vector_store

    with pytest.raises(VectorStoreConfigError) as exc_info:
        get_vector_store(Settings())

    assert exc_info.value.code == "MILVUS_CONFIG_MISSING"
    assert "MILVUS_DIMENSION" in str(exc_info.value)
    assert "secret-password-should-not-leak" not in str(exc_info.value)


def test_milvus_build_schema_contains_required_fields_and_dimension(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: _fake_pymilvus())

    store = vector_store.MilvusVectorStore(Settings())
    schema = store.build_schema()
    fields = {field.name: field for field in schema.fields}

    for field_name in (
        "chunk_id",
        "embedding",
        "chunk_text",
        "document_id",
        "chunk_index",
        "tenant_id",
        "merchant_id",
        "douyin_account_id",
        "category_key",
        "status",
        "created_at",
        "updated_at",
    ):
        assert field_name in fields
    assert fields["embedding"].kwargs["dim"] == 1536


def test_milvus_ensure_collection_missing_without_init_returns_not_found(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(collection_exists=False)
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    store = vector_store.MilvusVectorStore(Settings())

    with pytest.raises(vector_store.VectorStoreConfigError) as exc_info:
        store.ensure_collection(create_if_missing=False)

    assert exc_info.value.code == "MILVUS_COLLECTION_NOT_FOUND"
    assert fake.utility.created_collections == []


def test_milvus_connect_failure_reports_phase_and_sanitized_message(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(
        connect_error=RuntimeError(
            "connect failed uri=https://milvus.example.test user=readonly_user "
            "password=secret-password-should-not-leak"
        )
    )
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    store = vector_store.MilvusVectorStore(Settings())

    with pytest.raises(vector_store.VectorStoreError) as exc_info:
        store.ensure_collection(create_if_missing=False)

    exc = exc_info.value
    assert exc.code == "MILVUS_CONNECT_FAILED"
    assert exc.phase == "connect"
    assert "secret-password-should-not-leak" not in str(exc)
    assert "https://milvus.example.test" not in str(exc)
    assert "readonly_user" not in str(exc)


def test_milvus_has_collection_failure_reports_phase(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(
        has_collection_error=RuntimeError(
            "has collection failed uri=https://milvus.example.test user=readonly_user"
        )
    )
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    store = vector_store.MilvusVectorStore(Settings())

    with pytest.raises(vector_store.VectorStoreError) as exc_info:
        store.ensure_collection(create_if_missing=False)

    exc = exc_info.value
    assert exc.code == "MILVUS_COLLECTION_CHECK_FAILED"
    assert exc.phase == "has_collection"
    assert "https://milvus.example.test" not in str(exc)
    assert "readonly_user" not in str(exc)


def test_milvus_ensure_collection_missing_with_init_creates_collection(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(collection_exists=False)
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    store = vector_store.MilvusVectorStore(Settings())
    result = store.ensure_collection(create_if_missing=True)

    assert result["collection_exists"] is True
    assert result["created"] is True
    assert fake.utility.created_collections == ["xg_douyin_ai_cs_chunks"]
    assert fake.utility.loaded_collections == ["xg_douyin_ai_cs_chunks"]
    assert fake.utility.index_created is True


def test_milvus_ensure_collection_dimension_mismatch_is_rejected(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(collection_exists=True, existing_dimension=768)
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    store = vector_store.MilvusVectorStore(Settings())

    with pytest.raises(vector_store.VectorStoreConfigError) as exc_info:
        store.ensure_collection(create_if_missing=False)

    assert exc_info.value.code == "MILVUS_SCHEMA_MISMATCH"
    assert exc_info.value.phase == "schema_check"
    assert "secret-password-should-not-leak" not in str(exc_info.value)


def test_milvus_health_check_reports_sanitized_status(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.config import Settings
    from apps.xg_douyin_ai_cs.services import vector_store

    fake = _fake_pymilvus(collection_exists=True, existing_dimension=1536)
    monkeypatch.setattr(vector_store, "_load_pymilvus", lambda: fake)

    result = vector_store.MilvusVectorStore(Settings()).health_check()

    assert result["backend"] == "milvus"
    assert result["connected"] is True
    assert result["collection_exists"] is True
    assert result["dimension"] == 1536
    assert result["metric_type"] == "COSINE"
    assert "secret-password-should-not-leak" not in repr(result)


def test_milvus_collection_check_cli_skips_sqlite_backend(monkeypatch, capsys):
    _clear_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.scripts import milvus_collection_check

    exit_code = milvus_collection_check.main(["--check"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Milvus 未启用" in output


def test_milvus_collection_check_cli_init_uses_explicit_create(monkeypatch):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.scripts import milvus_collection_check

    calls = []

    class FakeStore:
        def ensure_collection(self, create_if_missing=False):
            calls.append(create_if_missing)
            return {
                "backend": "milvus",
                "collection_exists": True,
                "created": True,
                "schema_match": True,
            }

    monkeypatch.setattr(milvus_collection_check, "get_vector_store", lambda config: FakeStore())

    exit_code = milvus_collection_check.main(["--init"])

    assert exit_code == 0
    assert calls == [True]


def test_milvus_collection_check_cli_prints_sanitized_diagnostics(monkeypatch, capsys):
    _set_valid_milvus_env(monkeypatch)

    from apps.xg_douyin_ai_cs.scripts import milvus_collection_check
    from apps.xg_douyin_ai_cs.services import vector_store

    class FakeStore:
        def ensure_collection(self, create_if_missing=False):
            raise vector_store.VectorStoreError(
                "MILVUS_CONNECT_FAILED",
                "connect failed uri=https://milvus.example.test user=readonly_user "
                "password=secret-password-should-not-leak",
                phase="connect",
                connected=False,
            )

    monkeypatch.setattr(milvus_collection_check, "get_vector_store", lambda config: FakeStore())

    exit_code = milvus_collection_check.main(["--check"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "phase=connect" in output
    assert "error_code=MILVUS_CONNECT_FAILED" in output
    assert "secret-password-should-not-leak" not in output
    assert "https://milvus.example.test" not in output
    assert "readonly_user" not in output


def _fake_pymilvus(
    collection_exists=True,
    existing_dimension=1536,
    connect_error=None,
    has_collection_error=None,
):
    class DataType:
        VARCHAR = "VarChar"
        FLOAT_VECTOR = "FloatVector"
        INT64 = "Int64"

    class FieldSchema:
        def __init__(self, name, dtype, **kwargs):
            self.name = name
            self.dtype = dtype
            self.kwargs = kwargs

    class CollectionSchema:
        def __init__(self, fields, description=""):
            self.fields = fields
            self.description = description

    class FakeCollection:
        def __init__(self, name, schema=None, using=None):
            self.name = name
            self.schema = schema or _existing_schema(existing_dimension, FieldSchema, CollectionSchema, DataType)
            self.indexes = []

        def create_index(self, field_name, index_params):
            fake.utility.index_created = True
            self.indexes.append(SimpleNamespace(field_name=field_name, params=index_params))

        def load(self):
            fake.utility.loaded_collections.append(self.name)

    class FakeUtility:
        def __init__(self):
            self.created_collections = []
            self.loaded_collections = []
            self.index_created = False

        def has_collection(self, name, using=None):
            if has_collection_error is not None:
                raise has_collection_error
            return collection_exists or name in self.created_collections

    def collection_factory(name, schema=None, using=None):
        if schema is not None:
            fake.utility.created_collections.append(name)
        return FakeCollection(name, schema=schema, using=using)

    def connect(**kwargs):
        if connect_error is not None:
            raise connect_error

    fake = SimpleNamespace(
        connections=SimpleNamespace(connect=connect),
        utility=FakeUtility(),
        DataType=DataType,
        FieldSchema=FieldSchema,
        CollectionSchema=CollectionSchema,
    )
    fake.Collection = collection_factory
    return fake


def _existing_schema(dimension, field_schema, collection_schema, data_type):
    return collection_schema(
        [
            field_schema("chunk_id", data_type.VARCHAR, is_primary=True, max_length=128),
            field_schema("embedding", data_type.FLOAT_VECTOR, dim=dimension),
            field_schema("chunk_text", data_type.VARCHAR, max_length=4096),
            field_schema("document_id", data_type.VARCHAR, max_length=128),
            field_schema("chunk_index", data_type.INT64),
            field_schema("tenant_id", data_type.VARCHAR, max_length=128),
            field_schema("merchant_id", data_type.VARCHAR, max_length=128),
            field_schema("douyin_account_id", data_type.VARCHAR, max_length=128),
            field_schema("category_key", data_type.VARCHAR, max_length=128),
            field_schema("status", data_type.VARCHAR, max_length=32),
            field_schema("created_at", data_type.INT64),
            field_schema("updated_at", data_type.INT64),
        ]
    )
