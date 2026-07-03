"""9100 RAG 向量库抽象骨架。

当前默认仍走 SQLite；Milvus 只做配置和依赖门禁，不在本轮连接外部服务。
"""

from __future__ import annotations

import importlib.util
import importlib
import sys
from typing import Any, Protocol

from apps.xg_douyin_ai_cs.config import Settings, settings
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest


class VectorStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class VectorStoreConfigError(VectorStoreError):
    pass


class VectorStoreDependencyError(VectorStoreError):
    pass


class VectorStoreCollectionError(VectorStoreConfigError):
    pass


class VectorStore(Protocol):
    def upsert_chunks(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def search(self, payload: RagSearchRequest, *args: Any, **kwargs: Any) -> Any:
        ...

    def delete_document(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


class SQLiteVectorStore:
    backend = "sqlite"

    def upsert_chunks(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("SQLite upsert 仍由 rag.repository.train_scope 负责")

    def search(self, payload: RagSearchRequest, *args: Any, **kwargs: Any) -> Any:
        from apps.xg_douyin_ai_cs.rag.repository import search

        return search(payload, *args, **kwargs)

    def delete_document(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("SQLite 删除文档尚未在当前产品入口开放")

    def health_check(self) -> dict[str, Any]:
        return {"backend": self.backend, "ok": True}


class MilvusVectorStore:
    backend = "milvus"
    _alias = "xg_douyin_ai_cs_milvus"

    def __init__(self, config: Settings = settings) -> None:
        _validate_milvus_config(config)
        self._pymilvus = _load_pymilvus()
        self.config = config
        self._connected = False

    def upsert_chunks(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_UPSERT_NOT_IMPLEMENTED")

    def search(self, payload: RagSearchRequest, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_SEARCH_NOT_IMPLEMENTED")

    def delete_document(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_DELETE_NOT_IMPLEMENTED")

    def health_check(self) -> dict[str, Any]:
        result = {
            "backend": self.backend,
            "connected": False,
            "collection_exists": False,
            "dimension": self.config.milvus_dimension,
            "metric_type": self.config.milvus_metric_type,
        }
        try:
            self.connect()
            result["connected"] = True
            result["collection_exists"] = bool(
                self._pymilvus.utility.has_collection(
                    self.config.milvus_collection,
                    using=self._alias,
                )
            )
        except VectorStoreError as exc:
            result["error_code"] = exc.code
        except Exception:
            result["error_code"] = "MILVUS_HEALTH_CHECK_FAILED"
        return result

    def connect(self) -> None:
        if self._connected:
            return
        kwargs = {
            "alias": self._alias,
            "uri": self.config.milvus_uri,
            "user": self.config.milvus_username,
            "password": self.config.milvus_password,
            "timeout": self.config.milvus_timeout_seconds,
        }
        if self.config.milvus_db_name:
            kwargs["db_name"] = self.config.milvus_db_name
        self._pymilvus.connections.connect(**kwargs)
        self._connected = True

    def build_schema(self) -> Any:
        fields = [
            self._varchar("chunk_id", max_length=128, is_primary=True),
            self._pymilvus.FieldSchema(
                name="embedding",
                dtype=self._pymilvus.DataType.FLOAT_VECTOR,
                dim=self.config.milvus_dimension,
            ),
            self._varchar("chunk_text", max_length=4096),
            self._varchar("document_id", max_length=128),
            self._pymilvus.FieldSchema(name="chunk_index", dtype=self._pymilvus.DataType.INT64),
            self._varchar("tenant_id", max_length=128),
            self._varchar("merchant_id", max_length=128),
            self._varchar("douyin_account_id", max_length=128),
            self._varchar("category_key", max_length=128),
            self._varchar("category_id", max_length=128),
            self._varchar("source_type", max_length=64),
            self._varchar("source_title", max_length=512),
            self._varchar("source_hash", max_length=128),
            self._varchar("content_hash", max_length=128),
            self._varchar("status", max_length=32),
            self._pymilvus.FieldSchema(name="created_at", dtype=self._pymilvus.DataType.INT64),
            self._pymilvus.FieldSchema(name="updated_at", dtype=self._pymilvus.DataType.INT64),
        ]
        return self._pymilvus.CollectionSchema(
            fields=fields,
            description="xg_douyin_ai_cs RAG chunks",
        )

    def ensure_collection(self, create_if_missing: bool = False) -> dict[str, Any]:
        self.connect()
        collection_name = self.config.milvus_collection
        exists = self._pymilvus.utility.has_collection(collection_name, using=self._alias)
        if not exists:
            if not create_if_missing:
                raise VectorStoreCollectionError(
                    "MILVUS_COLLECTION_NOT_FOUND",
                    f"Milvus collection not found: {collection_name}",
                )
            collection = self._pymilvus.Collection(
                name=collection_name,
                schema=self.build_schema(),
                using=self._alias,
            )
            self.create_index_if_needed(collection)
            collection.load()
            return {
                "backend": self.backend,
                "collection_exists": True,
                "created": True,
                "schema_match": True,
                "dimension": self.config.milvus_dimension,
                "metric_type": self.config.milvus_metric_type,
            }

        collection = self._pymilvus.Collection(name=collection_name, using=self._alias)
        self._validate_collection_schema(collection.schema)
        self.create_index_if_needed(collection)
        return {
            "backend": self.backend,
            "collection_exists": True,
            "created": False,
            "schema_match": True,
            "dimension": self.config.milvus_dimension,
            "metric_type": self.config.milvus_metric_type,
        }

    def create_index_if_needed(self, collection: Any) -> None:
        if getattr(collection, "indexes", None):
            return
        index_params = {
            "index_type": self.config.milvus_index_type,
            "metric_type": self.config.milvus_metric_type,
            "params": {},
        }
        collection.create_index(field_name="embedding", index_params=index_params)

    def _varchar(self, name: str, max_length: int, **kwargs: Any) -> Any:
        return self._pymilvus.FieldSchema(
            name=name,
            dtype=self._pymilvus.DataType.VARCHAR,
            max_length=max_length,
            **kwargs,
        )

    def _validate_collection_schema(self, schema: Any) -> None:
        fields = {field.name: field for field in getattr(schema, "fields", [])}
        required_fields = {
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
        }
        missing = sorted(required_fields - set(fields))
        if missing:
            raise VectorStoreCollectionError(
                "MILVUS_SCHEMA_MISMATCH",
                f"Milvus schema missing fields: {', '.join(missing)}",
            )
        embedding = fields["embedding"]
        dimension = _field_param(embedding, "dim")
        if dimension != self.config.milvus_dimension:
            raise VectorStoreCollectionError(
                "MILVUS_SCHEMA_MISMATCH",
                "Milvus embedding dimension does not match MILVUS_DIMENSION",
            )


def get_vector_store(config: Settings = settings) -> VectorStore:
    backend = config.rag_vector_backend
    if backend == "sqlite":
        return SQLiteVectorStore()
    if backend == "milvus":
        return MilvusVectorStore(config)
    raise VectorStoreConfigError(
        "RAG_VECTOR_BACKEND_INVALID",
        "RAG_VECTOR_BACKEND must be one of: sqlite, milvus",
    )


def _validate_milvus_config(config: Settings) -> None:
    missing = []
    if not config.milvus_uri:
        missing.append("MILVUS_URI")
    if not config.milvus_username:
        missing.append("MILVUS_USERNAME")
    if not config.milvus_password:
        missing.append("MILVUS_PASSWORD")
    if not config.milvus_collection:
        missing.append("MILVUS_COLLECTION")
    if config.milvus_dimension is None:
        missing.append("MILVUS_DIMENSION")
    if missing:
        raise VectorStoreConfigError(
            "MILVUS_CONFIG_MISSING",
            f"Missing Milvus config: {', '.join(missing)}",
        )


def _ensure_pymilvus_available() -> None:
    _load_pymilvus()


def _load_pymilvus() -> Any:
    if sys.modules.get("pymilvus") is None and "pymilvus" in sys.modules:
        raise VectorStoreDependencyError(
            "MILVUS_DEPENDENCY_MISSING",
            "pymilvus is required when RAG_VECTOR_BACKEND=milvus",
        )
    if importlib.util.find_spec("pymilvus") is None:
        raise VectorStoreDependencyError(
            "MILVUS_DEPENDENCY_MISSING",
            "pymilvus is required when RAG_VECTOR_BACKEND=milvus",
        )
    return importlib.import_module("pymilvus")


def _field_param(field: Any, name: str) -> Any:
    if hasattr(field, "params") and name in field.params:
        return field.params[name]
    if hasattr(field, "kwargs") and name in field.kwargs:
        return field.kwargs[name]
    return getattr(field, name, None)
