"""Repository and retrieval logic for the RAG metadata（PostgreSQL / SQLite via SQLAlchemy）。

P3-D3：repository 由原生 sqlite3 切换到 SQLAlchemy engine + text()，SQL 用命名占位符、
ON CONFLICT DO NOTHING、RETURNING、BOOLEAN true/false，跨 PG / SQLite 方言。
PG / SQLite 均走 get_rag_engine() 单例（database.py），共用连接池。
公共 API 签名不变，调用方零改动。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from apps.xg_douyin_ai_cs.config import settings
from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient
from apps.xg_douyin_ai_cs.services.compute_usage_client import (
    ComputeUsageClient,
    count_embedding_characters,
)
from apps.xg_douyin_ai_cs.rag.chunker import chunk_text
from apps.xg_douyin_ai_cs.rag.database import get_rag_engine
from apps.xg_douyin_ai_cs.rag.models import (
    KnowledgeCategoryCreate,
    KnowledgeCategoryItem,
    KnowledgeDocumentCreate,
    RagSearchItem,
    RagSearchRequest,
    RagTrainRequest,
)
from apps.xg_douyin_ai_cs.services.vector_store import get_vector_store


TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z0-9]+")
FEEDBACK_RATING_PRIORITY = {
    "有用": 3,
    "一般": 2,
    "不准": 1,
}
FEEDBACK_RATING_RE = re.compile(r"【人工反馈】\s*(有用|一般|不准)")

_logger = logging.getLogger(__name__)
UNIFIED_KB_DOUYIN_ACCOUNT_ID = 0

# engine 走 database.get_rag_engine() 单例（按 rag_database_url 变化重建），
# 不在模块级缓存 _engine，保证测试 setenv 切换 tmp_path 时隔离成立


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    merchant_id: str
    douyin_account_id: int


def create_category(payload: KnowledgeCategoryCreate) -> KnowledgeCategoryItem:
    _validate_category_scope(payload)
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO knowledge_categories(
                  tenant_id, merchant_id, category_key, name, scope_type,
                  is_base, is_active, sort_order
                ) VALUES (:tenant_id, :merchant_id, :category_key, :name, :scope_type,
                          :is_base, :is_active, :sort_order)
                RETURNING *
                """
            ),
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "category_key": payload.category_key,
                "name": payload.name,
                "scope_type": payload.scope_type,
                "is_base": bool(payload.is_base),
                "is_active": bool(payload.is_active),
                "sort_order": payload.sort_order,
            },
        ).mappings().fetchone()
        conn.commit()
        return _to_category_item(row)


def list_categories(tenant_id: str, merchant_id: str) -> list[KnowledgeCategoryItem]:
    with get_rag_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT *
                FROM knowledge_categories
                WHERE tenant_id = :tenant_id AND is_active = true
                  AND (
                    scope_type = 'system'
                    OR (scope_type = 'merchant' AND merchant_id = :merchant_id)
                  )
                ORDER BY sort_order ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "merchant_id": merchant_id},
        ).mappings().fetchall()
    return [_to_category_item(row) for row in rows]


def ensure_base_category(tenant_id: str) -> KnowledgeCategoryItem:
    """确保统一知识库默认 base 分类可见。"""
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM knowledge_categories
                WHERE tenant_id = :tenant_id AND category_key = 'base' AND scope_type = 'system'
                ORDER BY id ASC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().fetchone()
        if row is None:
            row = conn.execute(
                text(
                    """
                    INSERT INTO knowledge_categories(
                      tenant_id, merchant_id, category_key, name, scope_type,
                      is_base, is_active, sort_order
                    ) VALUES (:tenant_id, NULL, 'base', '小高知识库', 'system', true, true, 1)
                    RETURNING *
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().fetchone()
            conn.commit()
    return _to_category_item(row)


def list_unified_documents(
    *,
    tenant_id: str,
    merchant_id: str,
    category_key: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    where, params = _document_filters(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        category_key=category_key,
        status=status,
        keyword=keyword,
    )
    offset = (max(page, 1) - 1) * page_size
    limit_params = {**params, "_limit": page_size, "_offset": offset}
    with get_rag_engine().connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) AS total FROM knowledge_documents d WHERE {where}"), params
        ).mappings().fetchone()
        rows = conn.execute(
            text(
                f"""
                SELECT d.*,
                  (
                    SELECT COUNT(*)
                    FROM knowledge_chunks c
                    WHERE c.document_id = d.id AND c.is_active = true
                  ) AS chunk_count,
                  (
                    SELECT r.id
                    FROM rag_training_runs r
                    WHERE r.document_id = d.id
                    ORDER BY r.id DESC
                    LIMIT 1
                  ) AS last_training_run_id,
                  (
                    SELECT r.status
                    FROM rag_training_runs r
                    WHERE r.document_id = d.id
                    ORDER BY r.id DESC
                    LIMIT 1
                  ) AS last_training_status
                FROM knowledge_documents d
                WHERE {where}
                ORDER BY d.updated_at DESC, d.id DESC
                LIMIT :_limit OFFSET :_offset
                """
            ),
            limit_params,
        ).mappings().fetchall()
    return {
        "items": [_document_summary(row) for row in rows],
        "total": int(total["total"] if total else 0),
        "page": page,
        "page_size": page_size,
    }


def get_unified_document(*, tenant_id: str, merchant_id: str, document_id: int) -> dict | None:
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT d.*,
                  (
                    SELECT COUNT(*)
                    FROM knowledge_chunks c
                    WHERE c.document_id = d.id AND c.is_active = true
                  ) AS chunk_count,
                  (
                    SELECT r.id
                    FROM rag_training_runs r
                    WHERE r.document_id = d.id
                    ORDER BY r.id DESC
                    LIMIT 1
                  ) AS last_training_run_id,
                  (
                    SELECT r.status
                    FROM rag_training_runs r
                    WHERE r.document_id = d.id
                    ORDER BY r.id DESC
                    LIMIT 1
                  ) AS last_training_status,
                  (
                    SELECT r.chunk_count
                    FROM rag_training_runs r
                    WHERE r.document_id = d.id
                    ORDER BY r.id DESC
                    LIMIT 1
                  ) AS last_training_chunk_count
                FROM knowledge_documents d
                WHERE d.id = :document_id AND d.tenant_id = :tenant_id
                  AND d.merchant_id = :merchant_id AND d.douyin_account_id = :douyin_account_id
                """
            ),
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            },
        ).mappings().fetchone()
    if row is None:
        return None
    data = _document_summary(row)
    data["content"] = str(row["content"])
    if row["last_training_run_id"] is not None:
        data["last_training_run"] = {
            "training_run_id": str(row["last_training_run_id"]),
            "status": row["last_training_status"],
            "chunk_count": int(row["last_training_chunk_count"] or 0),
        }
    else:
        data["last_training_run"] = None
    return data


def create_document(payload: KnowledgeDocumentCreate) -> int:
    if not payload.content.strip():
        raise ValueError("content must not be empty")
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO knowledge_documents(
                  tenant_id, merchant_id, douyin_account_id, title, content,
                  source_type, category, category_id, category_key, brand, vehicle_name,
                  metadata_json
                ) VALUES (:tenant_id, :merchant_id, :douyin_account_id, :title, :content,
                          :source_type, :category, :category_id, :category_key, :brand,
                          :vehicle_name, :metadata_json)
                RETURNING id
                """
            ),
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "douyin_account_id": payload.douyin_account_id,
                "title": payload.title,
                "content": payload.content,
                "source_type": payload.source_type,
                "category": payload.category,
                "category_id": payload.category_id,
                "category_key": payload.category_key,
                "brand": payload.brand,
                "vehicle_name": payload.vehicle_name,
                "metadata_json": json.dumps(payload.metadata or {}, ensure_ascii=False) if payload.metadata else None,
            },
        ).mappings().fetchone()
        conn.commit()
        return int(row["id"])


def update_unified_document(
    *,
    tenant_id: str,
    merchant_id: str,
    document_id: int,
    title: str,
    content: str,
    category_key: str,
) -> dict | None:
    if not content.strip():
        raise ValueError("content must not be empty")
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM knowledge_documents
                WHERE id = :document_id AND tenant_id = :tenant_id
                  AND merchant_id = :merchant_id AND douyin_account_id = :douyin_account_id
                """
            ),
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            },
        ).mappings().fetchone()
        if row is None:
            return None
        conn.execute(
            text(
                """
                UPDATE knowledge_documents
                SET title = :title, content = :content, category_key = :category_key,
                    source_type = 'manual_text', is_active = true, updated_at = CURRENT_TIMESTAMP
                WHERE id = :document_id
                """
            ),
            {"title": title, "content": content, "category_key": category_key, "document_id": document_id},
        )
        conn.execute(
            text(
                """
                UPDATE knowledge_chunks
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE document_id = :document_id
                """
            ),
            {"document_id": document_id},
        )
        conn.commit()
    return get_unified_document(tenant_id=tenant_id, merchant_id=merchant_id, document_id=document_id)


def soft_delete_unified_document(*, tenant_id: str, merchant_id: str, document_id: int) -> dict | None:
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM knowledge_documents
                WHERE id = :document_id AND tenant_id = :tenant_id
                  AND merchant_id = :merchant_id AND douyin_account_id = :douyin_account_id
                """
            ),
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            },
        ).mappings().fetchone()
        if row is None:
            return None
        conn.execute(
            text(
                """
                UPDATE knowledge_documents
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE id = :document_id
                """
            ),
            {"document_id": document_id},
        )
        conn.execute(
            text(
                """
                UPDATE knowledge_chunks
                SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE document_id = :document_id
                """
            ),
            {"document_id": document_id},
        )
        conn.commit()
    if settings.rag_vector_backend == "milvus":
        store = get_vector_store()
        store.delete_document(
            document_id=str(document_id),
            tenant_id=tenant_id,
            merchant_id=merchant_id,
        )
        store.flush()
    return {"document_id": str(document_id), "status": "deleted"}


def _embed_with_usage(
    *,
    client: OpenAICompatibleClient,
    text: str,
    merchant_id: str | None,
    remark: str | None = None,
) -> dict:
    """Phase 10 §0.2：统一 embedding 调用 + 字符计量上报；mock_for_test_only 跳过上报。

    所有训练 ingest 与查询 embedding 必须经此 helper；返回 embed 原始 payload，兼容既有读取。
    真实 embedding 按 count_embedding_characters 计量、capability=knowledge、source=embedding；
    mock 分支（model=mock_for_test_only，未配置真实 Ark）不计费。
    """
    result = client.embed(text)
    model = str(result.get("model") or result.get("embedding_provider") or "")
    if model and model != "mock_for_test_only" and merchant_id:
        tokens = count_embedding_characters(text)
        try:
            ComputeUsageClient().report_usage(
                merchant_id=merchant_id,
                tokens=tokens,
                source="embedding",
                capability_key="knowledge",
                model=model,
                remark=remark,
            )
        except Exception as exc:  # noqa: BLE001  上报失败绝不影响 RAG 主流程
            _logger.warning("rag_embed stage=compute_report_error error=%s", exc)
    return result


def train_document(
    *,
    tenant_id: str,
    merchant_id: str,
    document_id: int,
    llm_client: OpenAICompatibleClient | None = None,
) -> dict | None:
    client = llm_client or OpenAICompatibleClient()
    with get_rag_engine().connect() as conn:
        doc = conn.execute(
            text(
                """
                SELECT * FROM knowledge_documents
                WHERE id = :document_id AND tenant_id = :tenant_id AND merchant_id = :merchant_id
                  AND douyin_account_id = :douyin_account_id AND is_active = true
                """
            ),
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            },
        ).mappings().fetchone()
        if doc is None:
            return None
        run_id = _create_training_run(
            conn,
            RagTrainRequest(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                douyin_account_id=UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            ),
            document_id=document_id,
        )
        chunk_count = 0
        milvus_chunks: list[dict] = []
        try:
            conn.execute(
                text(
                    """
                    UPDATE knowledge_chunks
                    SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            for index, chunk in enumerate(chunk_text(doc["content"]), start=1):
                digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                embedding = _embed_with_usage(
                    client=client, text=chunk, merchant_id=merchant_id,
                    remark="knowledge_training_ingest",
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO knowledge_chunks(
                          document_id, tenant_id, merchant_id, douyin_account_id,
                          chunk_text, chunk_index, embedding_json, embedding_model,
                          category_id, category_key, content_hash, is_active
                        ) VALUES (:document_id, :tenant_id, :merchant_id, :douyin_account_id,
                                  :chunk_text, :chunk_index, :embedding_json, :embedding_model,
                                  :category_id, :category_key, :content_hash, true)
                        ON CONFLICT (document_id, content_hash) DO NOTHING
                        """
                    ),
                    {
                        "document_id": doc["id"],
                        "tenant_id": doc["tenant_id"],
                        "merchant_id": doc["merchant_id"],
                        "douyin_account_id": doc["douyin_account_id"],
                        "chunk_text": chunk,
                        "chunk_index": index,
                        "embedding_json": json.dumps(embedding["embedding"]),
                        "embedding_model": embedding["model"],
                        "category_id": doc["category_id"],
                        "category_key": doc["category_key"],
                        "content_hash": digest,
                    },
                )
                conn.execute(
                    text(
                        """
                        UPDATE knowledge_chunks
                        SET is_active = true, embedding_json = :embedding_json,
                            embedding_model = :embedding_model, category_id = :category_id,
                            category_key = :category_key, updated_at = CURRENT_TIMESTAMP
                        WHERE document_id = :document_id AND content_hash = :content_hash
                        """
                    ),
                    {
                        "embedding_json": json.dumps(embedding["embedding"]),
                        "embedding_model": embedding["model"],
                        "category_id": doc["category_id"],
                        "category_key": doc["category_key"],
                        "document_id": doc["id"],
                        "content_hash": digest,
                    },
                )
                row = conn.execute(
                    text(
                        """
                        SELECT c.*, d.title, d.source_type, d.content AS document_content
                        FROM knowledge_chunks c
                        JOIN knowledge_documents d ON d.id = c.document_id
                        WHERE c.document_id = :document_id AND c.content_hash = :content_hash
                        """
                    ),
                    {"document_id": doc["id"], "content_hash": digest},
                ).mappings().fetchone()
                if row is not None:
                    milvus_chunks.append(_to_milvus_chunk(row, embedding["embedding"]))
                chunk_count += 1
            if settings.rag_vector_backend == "milvus":
                store = get_vector_store()
                store.delete_document(
                    document_id=str(document_id),
                    tenant_id=tenant_id,
                    merchant_id=merchant_id,
                )
                store.upsert_chunks(milvus_chunks)
                store.flush()
            conn.execute(
                text(
                    """
                    UPDATE rag_training_runs
                    SET status = 'completed', document_count = 1, chunk_count = :chunk_count,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id
                    """
                ),
                {"chunk_count": chunk_count, "run_id": run_id},
            )
            conn.commit()
            return {
                "training_run_id": str(run_id),
                "document_id": str(document_id),
                "status": "completed",
                "chunk_count": chunk_count,
            }
        except Exception as exc:
            conn.execute(
                text(
                    """
                    UPDATE rag_training_runs
                    SET status = 'failed', document_count = 1, chunk_count = :chunk_count,
                        error = :error, finished_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id
                    """
                ),
                {"chunk_count": chunk_count, "error": _error_summary(exc), "run_id": run_id},
            )
            conn.commit()
            raise


def train_scope(payload: RagTrainRequest, llm_client: OpenAICompatibleClient | None = None) -> dict:
    client = llm_client or OpenAICompatibleClient()
    with get_rag_engine().connect() as conn:
        run_id = _create_training_run(conn, payload)
        docs = conn.execute(
            text(
                """
                SELECT * FROM knowledge_documents
                WHERE tenant_id = :tenant_id AND merchant_id = :merchant_id
                  AND douyin_account_id = :douyin_account_id AND is_active = true
                ORDER BY id
                """
            ),
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "douyin_account_id": payload.douyin_account_id,
            },
        ).mappings().fetchall()
        chunk_count = 0
        milvus_chunks: list[dict] = []
        try:
            conn.execute(
                text(
                    """
                    UPDATE knowledge_chunks SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = :tenant_id AND merchant_id = :merchant_id
                      AND douyin_account_id = :douyin_account_id
                    """
                ),
                {
                    "tenant_id": payload.tenant_id,
                    "merchant_id": payload.merchant_id,
                    "douyin_account_id": payload.douyin_account_id,
                },
            )
            for doc in docs:
                for index, chunk in enumerate(chunk_text(doc["content"]), start=1):
                    digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    embedding = _embed_with_usage(
                        client=client, text=chunk, merchant_id=payload.merchant_id,
                        remark="knowledge_training_ingest",
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO knowledge_chunks(
                              document_id, tenant_id, merchant_id, douyin_account_id,
                              chunk_text, chunk_index, embedding_json, embedding_model,
                              category_id, category_key, content_hash, is_active
                            ) VALUES (:document_id, :tenant_id, :merchant_id, :douyin_account_id,
                                      :chunk_text, :chunk_index, :embedding_json, :embedding_model,
                                      :category_id, :category_key, :content_hash, true)
                            ON CONFLICT (document_id, content_hash) DO NOTHING
                            """
                        ),
                        {
                            "document_id": doc["id"],
                            "tenant_id": doc["tenant_id"],
                            "merchant_id": doc["merchant_id"],
                            "douyin_account_id": doc["douyin_account_id"],
                            "chunk_text": chunk,
                            "chunk_index": index,
                            "embedding_json": json.dumps(embedding["embedding"]),
                            "embedding_model": embedding["model"],
                            "category_id": doc["category_id"],
                            "category_key": doc["category_key"],
                            "content_hash": digest,
                        },
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE knowledge_chunks
                            SET is_active = true, embedding_json = :embedding_json,
                                embedding_model = :embedding_model, category_id = :category_id,
                                category_key = :category_key, updated_at = CURRENT_TIMESTAMP
                            WHERE document_id = :document_id AND content_hash = :content_hash
                            """
                        ),
                        {
                            "embedding_json": json.dumps(embedding["embedding"]),
                            "embedding_model": embedding["model"],
                            "category_id": doc["category_id"],
                            "category_key": doc["category_key"],
                            "document_id": doc["id"],
                            "content_hash": digest,
                        },
                    )
                    row = conn.execute(
                        text(
                            """
                            SELECT c.*, d.title, d.source_type, d.content AS document_content
                            FROM knowledge_chunks c
                            JOIN knowledge_documents d ON d.id = c.document_id
                            WHERE c.document_id = :document_id AND c.content_hash = :content_hash
                            """
                        ),
                        {"document_id": doc["id"], "content_hash": digest},
                    ).mappings().fetchone()
                    if row is not None:
                        milvus_chunks.append(_to_milvus_chunk(row, embedding["embedding"]))
                    chunk_count += 1
            if settings.rag_vector_backend == "milvus":
                _sync_milvus_chunks(docs, milvus_chunks)
            conn.execute(
                text(
                    """
                    UPDATE rag_training_runs
                    SET status = 'completed', document_count = :document_count,
                        chunk_count = :chunk_count, finished_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id
                    """
                ),
                {"document_count": len(docs), "chunk_count": chunk_count, "run_id": run_id},
            )
            conn.commit()
            return {
                "training_run_id": run_id,
                "status": "completed",
                "document_count": len(docs),
                "chunk_count": chunk_count,
            }
        except Exception as exc:
            conn.execute(
                text(
                    """
                    UPDATE rag_training_runs
                    SET status = 'failed', document_count = :document_count,
                        chunk_count = :chunk_count, error = :error, finished_at = CURRENT_TIMESTAMP
                    WHERE id = :run_id
                    """
                ),
                {
                    "document_count": len(docs),
                    "chunk_count": chunk_count,
                    "error": _error_summary(exc),
                    "run_id": run_id,
                },
            )
            conn.commit()
            raise


def _sync_milvus_chunks(docs: Sequence[Row], chunks: list[dict]) -> None:
    store = get_vector_store()
    for doc in docs:
        store.delete_document(
            document_id=str(doc["id"]),
            tenant_id=str(doc["tenant_id"]),
            merchant_id=str(doc["merchant_id"]),
        )
    store.upsert_chunks(chunks)
    store.flush()


def _to_milvus_chunk(row: Row, embedding: object) -> dict:
    now = int(time.time())
    return {
        "chunk_id": str(row["id"]),
        "embedding": embedding,
        "chunk_text": str(row["chunk_text"] or ""),
        "document_id": str(row["document_id"]),
        "chunk_index": int(row["chunk_index"]),
        "tenant_id": str(row["tenant_id"]),
        "merchant_id": str(row["merchant_id"]),
        "douyin_account_id": "" if row["douyin_account_id"] is None else str(row["douyin_account_id"]),
        "category_key": str(row["category_key"] or ""),
        "category_id": "" if row["category_id"] is None else str(row["category_id"]),
        "source_type": str(row["source_type"] or ""),
        "source_title": str(row["title"] or ""),
        "source_hash": hashlib.sha256(str(row["document_content"] or "").encode("utf-8")).hexdigest(),
        "content_hash": str(row["content_hash"] or ""),
        "status": "active" if bool(row["is_active"]) else "inactive",
        "created_at": now,
        "updated_at": now,
    }


def _error_summary(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    message = str(exc)
    return f"{code}: {message}"[:500] if code else message[:500]


@dataclass(frozen=True)
class RagSearchDiagnostics:
    vector_backend: str
    fallback_reason: str | None = None


@dataclass(frozen=True)
class RagSearchResult:
    items: list[RagSearchItem]
    diagnostics: RagSearchDiagnostics


def search_with_diagnostics(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> RagSearchResult:
    if settings.rag_vector_backend == "milvus":
        return _search_milvus_or_fallback_with_diagnostics(payload, llm_client=llm_client)
    return RagSearchResult(
        items=_search_sqlite(payload, llm_client=llm_client),
        diagnostics=RagSearchDiagnostics(vector_backend="sqlite"),
    )


def search(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> list[RagSearchItem]:
    return search_with_diagnostics(payload, llm_client=llm_client).items


def search_unified_preview(*, tenant_id: str, merchant_id: str, query: str, category_keys: list[str], top_k: int) -> dict:
    if not category_keys:
        return {"matches": []}
    results = search(
        RagSearchRequest(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            douyin_account_id=UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            query=query,
            top_k=top_k,
            category_keys=category_keys,
        )
    )
    matches = []
    for item in results:
        doc = get_unified_document(tenant_id=tenant_id, merchant_id=merchant_id, document_id=int(item.document_id))
        matches.append(
            {
                "document_id": str(item.document_id),
                "title": item.title,
                "category_key": (doc or {}).get("category_key") or "",
                "chunk_text": item.chunk_text[:500],
                "score": item.score,
            }
        )
    return {"matches": matches}


def get_training_run(*, tenant_id: str, merchant_id: str, run_id: int) -> dict | None:
    with get_rag_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT *
                FROM rag_training_runs
                WHERE id = :run_id AND tenant_id = :tenant_id AND merchant_id = :merchant_id
                  AND douyin_account_id = :douyin_account_id
                """
            ),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            },
        ).mappings().fetchone()
    if row is None:
        return None
    return _training_run_item(row)


def list_training_runs(
    *,
    tenant_id: str,
    merchant_id: str,
    document_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    clauses = [
        "tenant_id = :tenant_id",
        "merchant_id = :merchant_id",
        "douyin_account_id = :douyin_account_id",
    ]
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "merchant_id": merchant_id,
        "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
    }
    if document_id is not None:
        clauses.append("document_id = :document_id")
        params["document_id"] = document_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)
    offset = (max(page, 1) - 1) * page_size
    limit_params = {**params, "_limit": page_size, "_offset": offset}
    with get_rag_engine().connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) AS total FROM rag_training_runs WHERE {where}"), params
        ).mappings().fetchone()
        rows = conn.execute(
            text(
                f"""
                SELECT *
                FROM rag_training_runs
                WHERE {where}
                ORDER BY id DESC
                LIMIT :_limit OFFSET :_offset
                """
            ),
            limit_params,
        ).mappings().fetchall()
    return {
        "items": [_training_run_item(row) for row in rows],
        "total": int(total["total"] if total else 0),
        "page": page,
        "page_size": page_size,
    }


def _search_milvus_or_fallback(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> list[RagSearchItem]:
    return _search_milvus_or_fallback_with_diagnostics(payload, llm_client=llm_client).items


def _search_milvus_or_fallback_with_diagnostics(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> RagSearchResult:
    category_keys = _normalize_filter_values(payload.category_keys)
    if not category_keys:
        _logger.info(
            "rag_search vector_backend=milvus fallback_reason=category_keys_empty "
            "tenant_id=%s merchant_id=%s top_k=%d",
            payload.tenant_id,
            payload.merchant_id,
            payload.top_k,
        )
        return RagSearchResult(
            items=[],
            diagnostics=RagSearchDiagnostics(vector_backend="milvus"),
        )
    if not str(payload.tenant_id or "").strip() or not str(payload.merchant_id or "").strip():
        _logger.warning(
            "rag_search vector_backend=milvus fallback_reason=merchant_context_missing "
            "tenant_id_present=%s merchant_id_present=%s top_k=%d",
            bool(str(payload.tenant_id or "").strip()),
            bool(str(payload.merchant_id or "").strip()),
            payload.top_k,
        )
        return RagSearchResult(
            items=[],
            diagnostics=RagSearchDiagnostics(
                vector_backend="milvus", fallback_reason="merchant_context_missing"
            ),
        )
    try:
        client = llm_client or OpenAICompatibleClient()
        query_embedding_payload = _embed_with_usage(
            client=client, text=payload.query, merchant_id=payload.merchant_id,
            remark="knowledge_search",
        )
        query_embedding = _coerce_embedding(query_embedding_payload.get("embedding"))
        if not query_embedding:
            raise ValueError("query embedding is empty")
        candidate_top_k = min(20, max(payload.top_k, payload.top_k * 3))
        search_payload = _copy_search_request(payload, top_k=candidate_top_k)
        result = get_vector_store().search(search_payload, query_embedding=query_embedding)
        ranked_result = _rerank_search_items(result)[: payload.top_k]
        _logger.info(
            "rag_search vector_backend=milvus fallback_reason=none tenant_id=%s "
            "merchant_id=%s top_k=%d candidate_top_k=%d result_count=%d category_key_count=%d",
            payload.tenant_id,
            payload.merchant_id,
            payload.top_k,
            candidate_top_k,
            len(ranked_result),
            len(category_keys),
        )
        return RagSearchResult(
            items=ranked_result,
            diagnostics=RagSearchDiagnostics(vector_backend="milvus"),
        )
    except Exception as exc:
        _logger.warning(
            "rag_search vector_backend=milvus fallback_reason=milvus_search_failed "
            "tenant_id=%s merchant_id=%s top_k=%d category_key_count=%d error_type=%s",
            payload.tenant_id,
            payload.merchant_id,
            payload.top_k,
            len(category_keys),
            type(exc).__name__,
        )
        return RagSearchResult(
            items=_search_sqlite(payload, llm_client=llm_client),
            diagnostics=RagSearchDiagnostics(
                vector_backend="milvus", fallback_reason="milvus_search_failed"
            ),
        )


def _search_sqlite(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> list[RagSearchItem]:
    query_tokens = set(_tokens(payload.query))
    category_ids = _normalize_filter_values(payload.category_ids)
    category_keys = _normalize_filter_values(payload.category_keys)
    category_filter_sql, category_filter_params = _build_category_filter(category_ids, category_keys)
    with get_rag_engine().connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT c.*, d.title
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE c.tenant_id = :tenant_id AND c.merchant_id = :merchant_id
                  AND c.douyin_account_id = :douyin_account_id
                  AND c.is_active = true AND d.is_active = true
                  {category_filter_sql}
                ORDER BY c.id DESC
                """
            ),
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "douyin_account_id": payload.douyin_account_id,
                **category_filter_params,
            },
        ).mappings().fetchall()

    category_filter_enabled = bool(category_ids or category_keys)

    skipped_invalid_embedding = 0
    vector_scored = []
    try:
        client = llm_client or OpenAICompatibleClient()
        query_embedding_payload = _embed_with_usage(
            client=client, text=payload.query, merchant_id=payload.merchant_id,
            remark="knowledge_search",
        )
        query_embedding = _coerce_embedding(query_embedding_payload.get("embedding"))
    except Exception as exc:
        query_embedding = None
        _logger.warning(
            "rag_search strategy=lexical_fallback stage=query_embedding_failed "
            "tenant_id=%s merchant_id=%s douyin_account_id=%s top_k=%d "
            "category_filter_enabled=%s category_id_count=%d category_key_count=%d "
            "candidate_count=%d skipped_invalid_embedding=%d error_type=%s",
            payload.tenant_id,
            payload.merchant_id,
            payload.douyin_account_id,
            payload.top_k,
            category_filter_enabled,
            len(category_ids),
            len(category_keys),
            len(rows),
            skipped_invalid_embedding,
            type(exc).__name__,
        )

    if query_embedding:
        for row in rows:
            chunk_embedding = _parse_embedding_json(row["embedding_json"])
            if not chunk_embedding or len(chunk_embedding) != len(query_embedding):
                skipped_invalid_embedding += 1
                continue
            score = cosine_similarity(query_embedding, chunk_embedding)
            vector_scored.append((score, row))
        if vector_scored:
            vector_scored.sort(key=_scored_row_sort_key, reverse=True)
            _logger.info(
                "rag_search strategy=vector tenant_id=%s merchant_id=%s "
                "douyin_account_id=%s top_k=%d candidate_count=%d "
                "category_filter_enabled=%s category_id_count=%d category_key_count=%d "
                "vector_result_count=%d skipped_invalid_embedding=%d",
                payload.tenant_id,
                payload.merchant_id,
                payload.douyin_account_id,
                payload.top_k,
                len(rows),
                category_filter_enabled,
                len(category_ids),
                len(category_keys),
                len(vector_scored[: payload.top_k]),
                skipped_invalid_embedding,
            )
            return _to_search_items(vector_scored[: payload.top_k])

    if query_embedding is not None:
        _logger.info(
            "rag_search strategy=lexical_fallback stage=no_valid_vector_result "
            "tenant_id=%s merchant_id=%s douyin_account_id=%s top_k=%d "
            "category_filter_enabled=%s category_id_count=%d category_key_count=%d "
            "candidate_count=%d skipped_invalid_embedding=%d",
            payload.tenant_id,
            payload.merchant_id,
            payload.douyin_account_id,
            payload.top_k,
            category_filter_enabled,
            len(category_ids),
            len(category_keys),
            len(rows),
            skipped_invalid_embedding,
        )

    return _lexical_search(
        rows,
        query_tokens,
        payload.top_k,
        category_filter_enabled=category_filter_enabled,
        category_id_count=len(category_ids),
        category_key_count=len(category_keys),
    )


def cosine_similarity(
    query_embedding: Sequence[float] | None,
    chunk_embedding: Sequence[float] | None,
) -> float:
    query_vector = _coerce_embedding(query_embedding)
    chunk_vector = _coerce_embedding(chunk_embedding)
    if not query_vector or not chunk_vector or len(query_vector) != len(chunk_vector):
        return 0.0
    query_norm = math.sqrt(sum(item * item for item in query_vector))
    chunk_norm = math.sqrt(sum(item * item for item in chunk_vector))
    if query_norm <= 0 or chunk_norm <= 0:
        return 0.0
    return float(sum(a * b for a, b in zip(query_vector, chunk_vector)) / (query_norm * chunk_norm))


def _lexical_search(
    rows: list[Row],
    query_tokens: set[str],
    top_k: int,
    *,
    category_filter_enabled: bool = False,
    category_id_count: int = 0,
    category_key_count: int = 0,
) -> list[RagSearchItem]:
    scored = []
    for row in rows:
        score = _score(query_tokens, str(row["chunk_text"] or ""))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=_scored_row_sort_key, reverse=True)
    _logger.info(
        "rag_search strategy=lexical_fallback top_k=%d "
        "category_filter_enabled=%s category_id_count=%d category_key_count=%d "
        "candidate_count=%d result_count=%d",
        top_k,
        category_filter_enabled,
        category_id_count,
        category_key_count,
        len(rows),
        len(scored[:top_k]),
    )
    return _to_search_items(scored[:top_k])


def _normalize_filter_values(values: Sequence[object] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)
    return normalized


def _build_category_filter(category_ids: list[str], category_keys: list[str]) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict[str, str] = {}
    if category_ids:
        placeholders = ",".join(f":cat_id_{i}" for i in range(len(category_ids)))
        clauses.append(f"CAST(c.category_id AS TEXT) IN ({placeholders})")
        for i, value in enumerate(category_ids):
            params[f"cat_id_{i}"] = value
    if category_keys:
        placeholders = ",".join(f":cat_key_{i}" for i in range(len(category_keys)))
        clauses.append(f"c.category_key IN ({placeholders})")
        for i, value in enumerate(category_keys):
            params[f"cat_key_{i}"] = value
    if not clauses:
        return "", {}
    return f"AND ({' OR '.join(clauses)})", params


def _to_search_items(scored_rows: list[tuple[float, Row]]) -> list[RagSearchItem]:
    return [
        RagSearchItem(
            chunk_id=int(row["id"]),
            document_id=int(row["document_id"]),
            title=str(row["title"]),
            chunk_text=str(row["chunk_text"]),
            score=round(float(score), 4),
        )
        for score, row in scored_rows
    ]


def _scored_row_sort_key(scored_row: tuple[float, Row]) -> tuple[float, int, float]:
    score, row = scored_row
    return (round(float(score), 2), _feedback_priority_from_text(str(row["chunk_text"] or "")), float(score))


def _rerank_search_items(items: Sequence[RagSearchItem]) -> list[RagSearchItem]:
    return sorted(
        items,
        key=lambda item: (
            round(float(item.score), 2),
            _feedback_priority_from_text(item.chunk_text),
            float(item.score),
        ),
        reverse=True,
    )


def _feedback_priority_from_text(text: str) -> int:
    match = FEEDBACK_RATING_RE.search(str(text or ""))
    if not match:
        return 0
    return FEEDBACK_RATING_PRIORITY.get(match.group(1), 0)


def _copy_search_request(payload: RagSearchRequest, *, top_k: int) -> RagSearchRequest:
    model_copy = getattr(payload, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"top_k": top_k})
    return payload.copy(update={"top_k": top_k})


def _parse_embedding_json(value: object) -> list[float] | None:
    if value is None:
        return None
    try:
        raw = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return _coerce_embedding(raw)


def _coerce_embedding(value: object) -> list[float] | None:
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        vector = [float(item) for item in value]  # type: ignore[operator]
    except (TypeError, ValueError):
        return None
    if not vector or any(not math.isfinite(item) for item in vector):
        return None
    return vector


def log_llm_call(
    *,
    tenant_id: str,
    merchant_id: str,
    conversation_id: int,
    model: str,
    status: str,
    elapsed_ms: int = 0,
    error_summary: str = "",
) -> None:
    with get_rag_engine().connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO llm_call_logs(
                  tenant_id, merchant_id, conversation_id, model, status, elapsed_ms, error_summary
                ) VALUES (:tenant_id, :merchant_id, :conversation_id, :model, :status,
                          :elapsed_ms, :error_summary)
                """
            ),
            {
                "tenant_id": tenant_id,
                "merchant_id": merchant_id,
                "conversation_id": conversation_id,
                "model": model,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "error_summary": error_summary[:500],
            },
        )
        conn.commit()


def _document_filters(
    *,
    tenant_id: str,
    merchant_id: str,
    category_key: str | None,
    status: str | None,
    keyword: str | None,
) -> tuple[str, dict[str, object]]:
    clauses = [
        "d.tenant_id = :tenant_id",
        "d.merchant_id = :merchant_id",
        "d.douyin_account_id = :douyin_account_id",
    ]
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "merchant_id": merchant_id,
        "douyin_account_id": UNIFIED_KB_DOUYIN_ACCOUNT_ID,
    }
    if category_key:
        clauses.append("d.category_key = :category_key")
        params["category_key"] = category_key
    if keyword:
        clauses.append("(d.title LIKE :kw_title OR d.content LIKE :kw_content)")
        params["kw_title"] = f"%{keyword}%"
        params["kw_content"] = f"%{keyword}%"
    if status in {"deleted", "disabled"}:
        clauses.append("d.is_active = false")
    elif status in {"draft", "active"}:
        clauses.append("d.is_active = true")
        if status == "active":
            clauses.append("EXISTS(SELECT 1 FROM knowledge_chunks c WHERE c.document_id = d.id AND c.is_active = true)")
        else:
            clauses.append("NOT EXISTS(SELECT 1 FROM knowledge_chunks c WHERE c.document_id = d.id AND c.is_active = true)")
    elif status:
        clauses.append("1=0")
    return " AND ".join(clauses), params


def _document_summary(row: Row) -> dict:
    chunk_count = int(row["chunk_count"] or 0)
    return {
        "document_id": str(row["id"]),
        "title": str(row["title"]),
        "category_key": str(row["category_key"] or "base"),
        "status": _document_status(row, chunk_count),
        "chunk_count": chunk_count,
        "last_training_run_id": None if row["last_training_run_id"] is None else str(row["last_training_run_id"]),
        "last_training_status": row["last_training_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _document_status(row: Row, chunk_count: int) -> str:
    if not bool(row["is_active"]):
        return "deleted"
    return "active" if chunk_count > 0 else "draft"


def _training_run_item(row: Row) -> dict:
    return {
        "training_run_id": str(row["id"]),
        "document_id": None if row["document_id"] is None else str(row["document_id"]),
        "status": str(row["status"]),
        "chunk_count": int(row["chunk_count"] or 0),
        "error_code": None if not row["error"] else "RAG_TRAINING_FAILED",
        "error_message": _sanitize_error_message(row["error"]),
        "started_at": row["created_at"],
        "completed_at": row["finished_at"],
    }


def _sanitize_error_message(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    for marker in ("token", "secret", "password", "cookie", "milvus", "qdrant", "http://", "https://"):
        text = re.sub(marker, "<redacted>", text, flags=re.IGNORECASE)
    return text[:300]


def _create_training_run(conn: Connection, payload: RagTrainRequest, document_id: int | None = None) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO rag_training_runs(tenant_id, merchant_id, douyin_account_id, document_id, status)
            VALUES (:tenant_id, :merchant_id, :douyin_account_id, :document_id, 'running')
            RETURNING id
            """
        ),
        {
            "tenant_id": payload.tenant_id,
            "merchant_id": payload.merchant_id,
            "douyin_account_id": payload.douyin_account_id,
            "document_id": document_id,
        },
    ).mappings().fetchone()
    return int(row["id"])


def _validate_category_scope(payload: KnowledgeCategoryCreate) -> None:
    if payload.scope_type == "system" and payload.merchant_id is not None:
        raise ValueError("system category merchant_id must be empty")
    if payload.scope_type == "merchant" and not payload.merchant_id:
        raise ValueError("merchant category merchant_id is required")


def _to_category_item(row: Row) -> KnowledgeCategoryItem:
    return KnowledgeCategoryItem(
        id=int(row["id"]),
        tenant_id=str(row["tenant_id"]),
        merchant_id=row["merchant_id"],
        category_key=str(row["category_key"]),
        name=str(row["name"]),
        scope_type=str(row["scope_type"]),
        is_base=bool(row["is_base"]),
        is_active=bool(row["is_active"]),
        sort_order=int(row["sort_order"]),
    )


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(str(text or "").lower()):
        part = match.group(0)
        if re.fullmatch(r"[一-鿿]+", part):
            tokens.extend(part[i : i + 2] for i in range(max(1, len(part) - 1)))
            tokens.extend(part[i : i + 3] for i in range(max(1, len(part) - 2)))
        else:
            tokens.append(part)
    return [item for item in tokens if item.strip()]


def _score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = set(_tokens(content))
    overlap = len(query_tokens & content_tokens)
    if overlap:
        return overlap / math.sqrt(max(1, len(query_tokens) * len(content_tokens)))
    compact_query = "".join(query_tokens)
    compact_content = re.sub(r"\s+", "", content.lower())
    return 0.1 if compact_query and compact_query in compact_content else 0.0
