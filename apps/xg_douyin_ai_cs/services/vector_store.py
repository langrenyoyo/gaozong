"""9100 RAG 向量库抽象骨架。

当前默认仍走 SQLite；Milvus 只做配置和依赖门禁，不在本轮连接外部服务。
"""

from __future__ import annotations

import importlib.util
import importlib
import re
import sys
from urllib.parse import urlparse
from typing import Any, Protocol

from apps.xg_douyin_ai_cs.config import Settings, settings
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest


class VectorStoreError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        phase: str = "unknown",
        connected: bool | str = "unknown",
        collection_exists: bool | str = "unknown",
        schema_match: bool | str = "unknown",
        error_type: str | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.connected = connected
        self.collection_exists = collection_exists
        self.schema_match = schema_match
        self.error_type = error_type
        super().__init__(_sanitize_text(message))

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "backend": "milvus",
            "connected": self.connected,
            "collection_exists": self.collection_exists,
            "schema_match": self.schema_match,
            "phase": self.phase,
            "error_code": self.code,
            "error_type": self.error_type or self.__class__.__name__,
            "error_message": _sanitize_text(str(self)),
        }


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
            result["phase"] = exc.phase
        except Exception:
            result["error_code"] = "MILVUS_HEALTH_CHECK_FAILED"
            result["phase"] = "unknown"
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
        try:
            self._pymilvus.connections.connect(**kwargs)
        except Exception as exc:
            raise VectorStoreError(
                _classify_connect_error(exc),
                _sanitize_exception(exc, self.config),
                phase="connect",
                connected=False,
                error_type=type(exc).__name__,
            ) from exc
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
        try:
            exists = self._pymilvus.utility.has_collection(collection_name, using=self._alias)
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_COLLECTION_CHECK_FAILED",
                _sanitize_exception(exc, self.config),
                phase="has_collection",
                connected=True,
                error_type=type(exc).__name__,
            ) from exc
        if not exists:
            if not create_if_missing:
                raise VectorStoreCollectionError(
                    "MILVUS_COLLECTION_NOT_FOUND",
                    f"Milvus collection not found: {collection_name}",
                    phase="has_collection",
                    connected=True,
                    collection_exists=False,
                )
            try:
                collection = self._pymilvus.Collection(
                    name=collection_name,
                    schema=self.build_schema(),
                    using=self._alias,
                )
            except Exception as exc:
                raise VectorStoreError(
                    "MILVUS_COLLECTION_CHECK_FAILED",
                    _sanitize_exception(exc, self.config),
                    phase="create_collection",
                    connected=True,
                    collection_exists=False,
                    error_type=type(exc).__name__,
                ) from exc
            try:
                self.create_index_if_needed(collection)
            except Exception as exc:
                raise VectorStoreError(
                    "MILVUS_COLLECTION_CHECK_FAILED",
                    _sanitize_exception(exc, self.config),
                    phase="create_index",
                    connected=True,
                    collection_exists=True,
                    error_type=type(exc).__name__,
                ) from exc
            try:
                collection.load()
            except Exception as exc:
                raise VectorStoreError(
                    "MILVUS_COLLECTION_CHECK_FAILED",
                    _sanitize_exception(exc, self.config),
                    phase="load_collection",
                    connected=True,
                    collection_exists=True,
                    schema_match=True,
                    error_type=type(exc).__name__,
                ) from exc
            return {
                "backend": self.backend,
                "connected": True,
                "collection_exists": True,
                "created": True,
                "schema_match": True,
                "dimension": self.config.milvus_dimension,
                "metric_type": self.config.milvus_metric_type,
            }

        try:
            collection = self._pymilvus.Collection(name=collection_name, using=self._alias)
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_COLLECTION_CHECK_FAILED",
                _sanitize_exception(exc, self.config),
                phase="describe_collection",
                connected=True,
                collection_exists=True,
                error_type=type(exc).__name__,
            ) from exc
        self._validate_collection_schema(collection.schema)
        try:
            self.create_index_if_needed(collection)
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_COLLECTION_CHECK_FAILED",
                _sanitize_exception(exc, self.config),
                phase="index_check",
                connected=True,
                collection_exists=True,
                schema_match=True,
                error_type=type(exc).__name__,
            ) from exc
        return {
            "backend": self.backend,
            "connected": True,
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
                phase="schema_check",
                connected=True,
                collection_exists=True,
                schema_match=False,
            )
        embedding = fields["embedding"]
        dimension = _field_param(embedding, "dim")
        if dimension != self.config.milvus_dimension:
            raise VectorStoreCollectionError(
                "MILVUS_SCHEMA_MISMATCH",
                "Milvus embedding dimension does not match MILVUS_DIMENSION",
                phase="schema_check",
                connected=True,
                collection_exists=True,
                schema_match=False,
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


def probe_milvus_connections(config: Settings = settings) -> list[dict[str, Any]]:
    strategies = ("milvus_client_token", "orm_connections_user_password")
    try:
        _validate_milvus_connection_config(config)
        pymilvus = _load_pymilvus()
    except VectorStoreError as exc:
        diagnostic = _probe_error_diagnostic(exc)
        return [dict(diagnostic, strategy=strategy) for strategy in strategies]

    results = []
    for strategy in strategies:
        try:
            if strategy == "milvus_client_token":
                _probe_milvus_client_token(pymilvus, config)
            else:
                _probe_orm_connections_user_password(pymilvus, config)
        except Exception as exc:
            results.append(
                {
                    "strategy": strategy,
                    "connected": False,
                    "phase": "connect",
                    "error_code": _classify_connect_error(exc),
                    "error_type": type(exc).__name__,
                    "error_message": _sanitize_exception(exc, config),
                }
            )
        else:
            results.append(
                {
                    "strategy": strategy,
                    "connected": True,
                    "phase": "connect",
                    "error_code": "OK",
                    "error_type": "",
                }
            )
    return results


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
    _validate_milvus_uri(config)


def _validate_milvus_connection_config(config: Settings) -> None:
    missing = []
    if not config.milvus_uri:
        missing.append("MILVUS_URI")
    if not config.milvus_username:
        missing.append("MILVUS_USERNAME")
    if not config.milvus_password:
        missing.append("MILVUS_PASSWORD")
    if missing:
        raise VectorStoreConfigError(
            "MILVUS_CONFIG_MISSING",
            f"Missing Milvus config: {', '.join(missing)}",
            phase="config",
        )
    _validate_milvus_uri(config)


def _validate_milvus_uri(config: Settings) -> None:
    parsed = urlparse(config.milvus_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VectorStoreConfigError(
            "MILVUS_URI_INVALID",
            "MILVUS_URI must start with http:// or https://",
            phase="connect",
            connected=False,
        )


def _probe_error_diagnostic(exc: VectorStoreError) -> dict[str, Any]:
    return {
        "connected": False,
        "phase": exc.phase if exc.phase != "unknown" else "connect",
        "error_code": exc.code,
        "error_type": exc.__class__.__name__,
    }


def _probe_milvus_client_token(pymilvus: Any, config: Settings) -> None:
    kwargs = {
        "uri": config.milvus_uri,
        "token": f"{config.milvus_username}:{config.milvus_password}",
        "timeout": config.milvus_timeout_seconds,
    }
    if config.milvus_db_name:
        kwargs["db_name"] = config.milvus_db_name
    else:
        kwargs["db_name"] = None
    pymilvus.MilvusClient(**kwargs)


def _probe_orm_connections_user_password(pymilvus: Any, config: Settings) -> None:
    kwargs = {
        "alias": f"{MilvusVectorStore._alias}_probe",
        "uri": config.milvus_uri,
        "user": config.milvus_username,
        "password": config.milvus_password,
        "timeout": config.milvus_timeout_seconds,
    }
    if config.milvus_db_name:
        kwargs["db_name"] = config.milvus_db_name
    pymilvus.connections.connect(**kwargs)


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


def _classify_connect_error(exc: Exception) -> str:
    text = str(exc).lower()
    if any(word in text for word in ("auth", "credential", "permission", "unauthorized", "forbidden")):
        return "MILVUS_AUTH_FAILED"
    if "uri" in text and "invalid" in text:
        return "MILVUS_URI_INVALID"
    if "database" in text or "db" in text:
        return "MILVUS_DB_NOT_FOUND"
    return "MILVUS_CONNECT_FAILED"


def _sanitize_exception(exc: Exception, config: Settings) -> str:
    text = _sanitize_text(str(exc))
    for value in _milvus_sensitive_values(config):
        if value:
            text = text.replace(value, "<redacted>")
    return text or "details redacted"


def sanitize_milvus_diagnostic(result: dict[str, Any], config: Settings) -> dict[str, Any]:
    sanitized = dict(result)
    for key, value in list(sanitized.items()):
        if isinstance(value, str):
            sanitized[key] = _sanitize_with_config(value, config)
    return sanitized


def _sanitize_with_config(text: str, config: Settings) -> str:
    sanitized = _sanitize_text(text)
    for value in _milvus_sensitive_values(config):
        if value:
            sanitized = sanitized.replace(value, "<redacted>")
    return sanitized


def _milvus_sensitive_values(config: Settings) -> tuple[str, ...]:
    parsed = urlparse(config.milvus_uri)
    token = f"{config.milvus_username}:{config.milvus_password}" if config.milvus_username else ""
    return (
        config.milvus_password,
        config.milvus_username,
        token,
        config.milvus_uri,
        parsed.netloc,
        parsed.hostname or "",
    )


def _sanitize_text(text: str) -> str:
    sanitized = str(text)
    sanitized = re.sub(r"(?i)(password|passwd|pwd)\s*=\s*\S+", r"\1=<redacted>", sanitized)
    sanitized = re.sub(r"(?i)(user|username)\s*=\s*\S+", r"\1=<redacted-user>", sanitized)
    sanitized = re.sub(r"(?i)(uri|url)\s*=\s*\S+", r"\1=<redacted-uri>", sanitized)
    sanitized = re.sub(r"https?://[^\s,;]+", "<redacted-uri>", sanitized)
    return sanitized
