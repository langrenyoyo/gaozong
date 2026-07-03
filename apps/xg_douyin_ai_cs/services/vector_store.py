"""9100 RAG 向量库抽象骨架。

当前默认仍走 SQLite；Milvus 只做配置和依赖门禁，不在本轮连接外部服务。
"""

from __future__ import annotations

import importlib.util
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

    def __init__(self, config: Settings = settings) -> None:
        _validate_milvus_config(config)
        _ensure_pymilvus_available()
        self.config = config

    def upsert_chunks(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_UPSERT_NOT_IMPLEMENTED")

    def search(self, payload: RagSearchRequest, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_SEARCH_NOT_IMPLEMENTED")

    def delete_document(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("MILVUS_DELETE_NOT_IMPLEMENTED")

    def health_check(self) -> dict[str, Any]:
        return {"backend": self.backend, "ok": False, "status": "skeleton_only"}


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
