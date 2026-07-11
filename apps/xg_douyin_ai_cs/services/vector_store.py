"""9100 RAG 向量库抽象骨架。

支持两种 backend：sqlite（dev 轻量开发）/ milvus（LAN + production 外部服务）。
production 固定使用外部 Milvus，不得回退 SQLite 向量后端。
"""

from __future__ import annotations

import importlib.util
import importlib
import math
import os
import re
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlparse
from typing import Any, Protocol

from apps.xg_douyin_ai_cs.config import Settings, settings
from apps.xg_douyin_ai_cs.rag.models import RagSearchItem, RagSearchRequest


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

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        if not chunks:
            return {"backend": self.backend, "upserted": 0}
        self.ensure_collection(create_if_missing=False)
        rows = [self._normalize_chunk(chunk) for chunk in chunks]
        try:
            collection = self._pymilvus.Collection(name=self.config.milvus_collection, using=self._alias)
            collection.upsert(rows)
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_UPSERT_FAILED",
                _sanitize_exception(exc, self.config),
                phase="upsert",
                connected=True,
                collection_exists=True,
                schema_match=True,
                error_type=type(exc).__name__,
            ) from exc
        return {"backend": self.backend, "upserted": len(rows)}

    def search(
        self,
        payload: RagSearchRequest,
        *,
        query_embedding: object,
        preserve_raw_ids: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        category_keys = _normalize_required_filter_values(payload.category_keys)
        if not category_keys or not str(payload.tenant_id or "").strip() or not str(payload.merchant_id or "").strip():
            return []
        embedding = _coerce_vector(query_embedding)
        if len(embedding) != self.config.milvus_dimension:
            raise VectorStoreConfigError(
                "MILVUS_VECTOR_DIMENSION_MISMATCH",
                "Milvus query embedding dimension does not match MILVUS_DIMENSION",
                phase="search",
                connected=True,
                collection_exists=True,
                schema_match=True,
            )
        self.ensure_collection(create_if_missing=False)
        expr = _build_milvus_search_expr(
            tenant_id=payload.tenant_id,
            merchant_id=payload.merchant_id,
            douyin_account_id=payload.douyin_account_id,
            category_keys=category_keys,
        )
        try:
            collection = self._pymilvus.Collection(name=self.config.milvus_collection, using=self._alias)
            result = collection.search(
                data=[embedding],
                anns_field="embedding",
                param={"metric_type": self.config.milvus_metric_type, "params": {}},
                limit=int(payload.top_k),
                expr=expr,
                output_fields=[
                    "chunk_id",
                    "chunk_text",
                    "document_id",
                    "category_key",
                    "source_title",
                ],
            )
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_SEARCH_FAILED",
                _sanitize_exception(exc, self.config),
                phase="search",
                connected=True,
                collection_exists=True,
                schema_match=True,
                error_type=type(exc).__name__,
            ) from exc
        mapper = _hit_to_raw_search_item if preserve_raw_ids else _hit_to_search_item
        return [mapper(hit) for hits in result for hit in hits][: int(payload.top_k)]

    def flush(self) -> None:
        try:
            collection = self._pymilvus.Collection(name=self.config.milvus_collection, using=self._alias)
            flush = getattr(collection, "flush", None)
            if callable(flush):
                flush()
            load = getattr(collection, "load", None)
            if callable(load):
                load()
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_FLUSH_FAILED",
                _sanitize_exception(exc, self.config),
                phase="flush",
                connected=True,
                collection_exists=True,
                schema_match=True,
                error_type=type(exc).__name__,
            ) from exc

    def delete_document(self, *, document_id: str, tenant_id: str, merchant_id: str) -> dict[str, Any]:
        required = {"document_id": document_id, "tenant_id": tenant_id, "merchant_id": merchant_id}
        missing = [key for key, value in required.items() if not str(value or "").strip()]
        if missing:
            raise VectorStoreConfigError(
                "MILVUS_DELETE_SCOPE_MISSING",
                f"Missing Milvus delete scope: {', '.join(missing)}",
                phase="delete",
                connected=self._connected,
            )
        self.ensure_collection(create_if_missing=False)
        expr = (
            f'document_id == "{_expr_quote(document_id)}" '
            f'and tenant_id == "{_expr_quote(tenant_id)}" '
            f'and merchant_id == "{_expr_quote(merchant_id)}"'
        )
        try:
            collection = self._pymilvus.Collection(name=self.config.milvus_collection, using=self._alias)
            collection.delete(expr)
        except Exception as exc:
            raise VectorStoreError(
                "MILVUS_DELETE_FAILED",
                _sanitize_exception(exc, self.config),
                phase="delete",
                connected=True,
                collection_exists=True,
                schema_match=True,
                error_type=type(exc).__name__,
            ) from exc
        return {"backend": self.backend, "deleted": True}

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

    def readiness_check(self) -> dict[str, Any]:
        """纯只读 Milvus readiness 实例检查（connect → collection → schema → 探测）。

        P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1。
        前置：pymilvus 依赖 + 配置完整性 + embedding/milvus 维度一致性已由
        run_milvus_readiness 校验（__init__ 也做了配置校验）。

        硬性约束：只读，不创建 collection、不修改索引、不写入/删除向量、不 load。
        全程脱敏：异常经 _sanitize_exception 去除密码/完整 URI。
        """
        result: dict[str, Any] = {
            "backend": self.backend,
            "connected": False,
            "collection_exists": False,
            "schema_match": False,
            "query_ok": False,
        }
        # 认证 + 连接（database 不存在在此阶段暴露 → MILVUS_DB_NOT_FOUND）
        try:
            self.connect()
        except VectorStoreError as exc:
            result["error_code"] = exc.code
            result["phase"] = exc.phase
            return result
        result["connected"] = True
        # collection 存在（纯只读 has_collection）
        try:
            exists = self._pymilvus.utility.has_collection(
                self.config.milvus_collection, using=self._alias
            )
        except Exception as exc:
            result["error_code"] = "MILVUS_COLLECTION_CHECK_FAILED"
            result["phase"] = "has_collection"
            result["error_type"] = type(exc).__name__
            return result
        if not exists:
            result["error_code"] = "MILVUS_COLLECTION_NOT_FOUND"
            result["phase"] = "has_collection"
            return result
        result["collection_exists"] = True
        # collection schema 维度一致（collection 实际 dim vs MILVUS_DIMENSION）
        try:
            collection = self._pymilvus.Collection(
                name=self.config.milvus_collection, using=self._alias
            )
            self._validate_collection_schema(collection.schema)
        except VectorStoreCollectionError:
            # _validate_collection_schema 抛 MILVUS_SCHEMA_MISMATCH；readiness 统一映射为 DIMENSION_MISMATCH
            result["error_code"] = "MILVUS_DIMENSION_MISMATCH"
            result["phase"] = "schema_check"
            return result
        except Exception as exc:
            result["error_code"] = "MILVUS_COLLECTION_CHECK_FAILED"
            result["phase"] = "describe_collection"
            result["error_type"] = type(exc).__name__
            return result
        result["schema_match"] = True
        # 轻量只读探测（num_entities 只读统计，不修改数据、不需 load）
        try:
            _ = collection.num_entities
        except Exception as exc:
            result["error_code"] = "MILVUS_QUERY_FAILED"
            result["phase"] = "query"
            result["error_type"] = type(exc).__name__
            return result
        result["query_ok"] = True
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

    def _normalize_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        required = ("chunk_id", "document_id", "tenant_id", "merchant_id", "category_key")
        missing = [key for key in required if not str(chunk.get(key) or "").strip()]
        if missing:
            raise VectorStoreConfigError(
                "MILVUS_CHUNK_METADATA_MISSING",
                f"Missing Milvus chunk metadata: {', '.join(missing)}",
                phase="upsert",
                connected=True,
                collection_exists=True,
                schema_match=True,
            )
        embedding = _coerce_vector(chunk.get("embedding"))
        if len(embedding) != self.config.milvus_dimension:
            raise VectorStoreConfigError(
                "MILVUS_VECTOR_DIMENSION_MISMATCH",
                "Milvus embedding dimension does not match MILVUS_DIMENSION",
                phase="upsert",
                connected=True,
                collection_exists=True,
                schema_match=True,
            )
        return {
            "chunk_id": str(chunk["chunk_id"]),
            "embedding": embedding,
            "chunk_text": str(chunk.get("chunk_text") or ""),
            "document_id": str(chunk["document_id"]),
            "chunk_index": int(chunk.get("chunk_index") or 0),
            "tenant_id": str(chunk["tenant_id"]),
            "merchant_id": str(chunk["merchant_id"]),
            "douyin_account_id": str(chunk.get("douyin_account_id") or ""),
            "category_key": str(chunk["category_key"]),
            "category_id": str(chunk.get("category_id") or ""),
            "source_type": str(chunk.get("source_type") or ""),
            "source_title": str(chunk.get("source_title") or ""),
            "source_hash": str(chunk.get("source_hash") or ""),
            "content_hash": str(chunk.get("content_hash") or ""),
            "status": str(chunk.get("status") or "active"),
            "created_at": _coerce_unix_timestamp(chunk.get("created_at")),
            "updated_at": _coerce_unix_timestamp(chunk.get("updated_at")),
        }

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


def run_milvus_readiness(config: Settings = settings) -> dict[str, Any]:
    """纯只读 Milvus readiness 完整检查链（P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1）。

    检查链：pymilvus 依赖 → 配置完整 → embedding/milvus 维度一致 →
    认证连接 → collection 存在 → collection schema 维度一致 → 轻量只读探测。
    任一失败返回结构化 error_code（不抛异常），全程脱敏不输出密码或完整 URI。

    硬性约束：只读，不创建 collection、不修改索引、不写入/删除向量、不 load。
    """
    result: dict[str, Any] = {
        "backend": "milvus",
        "connected": False,
        "collection_exists": False,
        "schema_match": False,
        "query_ok": False,
    }
    # pymilvus 依赖
    try:
        _load_pymilvus()
    except VectorStoreError as exc:
        result["error_code"] = exc.code
        result["phase"] = "dependency"
        return result
    # 配置完整性 + URI 合法性
    try:
        _validate_milvus_config(config)
    except VectorStoreError as exc:
        result["error_code"] = exc.code
        result["phase"] = exc.phase
        return result
    # embedding/milvus 维度一致（配置层）
    try:
        _validate_embedding_milvus_dimension_consistency(config)
    except VectorStoreError as exc:
        result["error_code"] = exc.code
        result["phase"] = exc.phase
        return result
    # 委托实例做 connect → collection → schema → 探测（此时 __init__ 校验必通过）
    store = MilvusVectorStore(config)
    return store.readiness_check()


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


def _validate_embedding_milvus_dimension_consistency(config: Settings) -> None:
    """当 RAG_VECTOR_BACKEND=milvus 时，校验 EMBEDDING_DIMENSIONS 与 MILVUS_DIMENSION 一致。

    三层校验：两者都必须存在且为正整数，且数值相等。
    不一致或缺失抛 MILVUS_DIMENSION_MISMATCH；collection 实际维度由
    _validate_collection_schema 在 readiness 连接阶段校验。
    """
    embedding_dim_raw = os.environ.get("XG_DOUYIN_AI_EMBEDDING_DIMENSIONS", "").strip()
    milvus_dim = config.milvus_dimension
    if not embedding_dim_raw:
        raise VectorStoreConfigError(
            "MILVUS_DIMENSION_MISMATCH",
            "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS 未设置；backend=milvus 时必须与 MILVUS_DIMENSION 一致",
            phase="config",
        )
    if milvus_dim is None:
        raise VectorStoreConfigError(
            "MILVUS_DIMENSION_MISMATCH",
            "MILVUS_DIMENSION 未设置；backend=milvus 时必须与 XG_DOUYIN_AI_EMBEDDING_DIMENSIONS 一致",
            phase="config",
        )
    try:
        embedding_dim = int(embedding_dim_raw)
    except ValueError:
        raise VectorStoreConfigError(
            "MILVUS_DIMENSION_MISMATCH",
            f"XG_DOUYIN_AI_EMBEDDING_DIMENSIONS 非整数：{embedding_dim_raw}",
            phase="config",
        )
    if embedding_dim != milvus_dim:
        raise VectorStoreConfigError(
            "MILVUS_DIMENSION_MISMATCH",
            f"维度不一致：EMBEDDING_DIMENSIONS={embedding_dim} != MILVUS_DIMENSION={milvus_dim}",
            phase="config",
        )


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


def _coerce_vector(value: object) -> list[float]:
    if value is None or isinstance(value, (str, bytes)):
        return []
    try:
        vector = [float(item) for item in value]  # type: ignore[operator]
    except (TypeError, ValueError):
        return []
    if any(not math.isfinite(item) for item in vector):
        return []
    return vector


def _coerce_unix_timestamp(value: object) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _expr_quote(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _normalize_required_filter_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized = []
    for value in values:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _build_milvus_search_expr(
    *,
    tenant_id: object,
    merchant_id: object,
    douyin_account_id: object,
    category_keys: list[str],
) -> str:
    quoted_categories = ", ".join(f'"{_expr_quote(item)}"' for item in category_keys)
    return (
        f'tenant_id == "{_expr_quote(tenant_id)}" '
        f'and merchant_id == "{_expr_quote(merchant_id)}" '
        f'and douyin_account_id == "{_expr_quote(douyin_account_id)}" '
        f'and status == "active" '
        f"and category_key in [{quoted_categories}]"
    )


def _hit_to_search_item(hit: object) -> RagSearchItem:
    entity = getattr(hit, "entity", None)
    score = getattr(hit, "score", getattr(hit, "distance", 0.0))
    return RagSearchItem(
        chunk_id=_safe_int(_entity_value(entity, "chunk_id")),
        document_id=_safe_int(_entity_value(entity, "document_id")),
        title=str(_entity_value(entity, "source_title") or ""),
        chunk_text=str(_entity_value(entity, "chunk_text") or "")[:1000],
        score=round(float(score or 0.0), 4),
    )


def _hit_to_raw_search_item(hit: object) -> Any:
    entity = getattr(hit, "entity", None)
    score = getattr(hit, "score", getattr(hit, "distance", 0.0))
    return SimpleNamespace(
        chunk_id=str(_entity_value(entity, "chunk_id") or ""),
        document_id=str(_entity_value(entity, "document_id") or ""),
        category_key=str(_entity_value(entity, "category_key") or ""),
        title=str(_entity_value(entity, "source_title") or ""),
        chunk_text=str(_entity_value(entity, "chunk_text") or "")[:1000],
        score=round(float(score or 0.0), 4),
    )


def _entity_value(entity: object, key: str) -> object:
    if isinstance(entity, dict):
        return entity.get(key)
    getter = getattr(entity, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(entity, key, None)


def _safe_int(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


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
