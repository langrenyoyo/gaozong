"""Repository and retrieval logic for the SQLite RAG MVP."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient
from apps.xg_douyin_ai_cs.rag.chunker import chunk_text
from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.rag.models import (
    KnowledgeCategoryCreate,
    KnowledgeCategoryItem,
    KnowledgeDocumentCreate,
    RagSearchItem,
    RagSearchRequest,
    RagTrainRequest,
)


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    merchant_id: str
    douyin_account_id: int


def create_category(payload: KnowledgeCategoryCreate) -> KnowledgeCategoryItem:
    _validate_category_scope(payload)
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_categories(
              tenant_id, merchant_id, category_key, name, scope_type,
              is_base, is_active, sort_order
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                payload.tenant_id,
                payload.merchant_id,
                payload.category_key,
                payload.name,
                payload.scope_type,
                1 if payload.is_base else 0,
                1 if payload.is_active else 0,
                payload.sort_order,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM knowledge_categories WHERE id=?",
            (int(cur.lastrowid),),
        ).fetchone()
        return _to_category_item(row)


def list_categories(tenant_id: str, merchant_id: str) -> list[KnowledgeCategoryItem]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_categories
            WHERE tenant_id=? AND is_active=1
              AND (
                scope_type='system'
                OR (scope_type='merchant' AND merchant_id=?)
              )
            ORDER BY sort_order ASC, id ASC
            """,
            (tenant_id, merchant_id),
        ).fetchall()
    return [_to_category_item(row) for row in rows]


def create_document(payload: KnowledgeDocumentCreate) -> int:
    if not payload.content.strip():
        raise ValueError("content must not be empty")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_documents(
              tenant_id, merchant_id, douyin_account_id, title, content,
              source_type, category, category_id, category_key, brand, vehicle_name
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.tenant_id,
                payload.merchant_id,
                payload.douyin_account_id,
                payload.title,
                payload.content,
                payload.source_type,
                payload.category,
                payload.category_id,
                payload.category_key,
                payload.brand,
                payload.vehicle_name,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def train_scope(payload: RagTrainRequest, llm_client: OpenAICompatibleClient | None = None) -> dict:
    client = llm_client or OpenAICompatibleClient()
    with connect() as conn:
        run_id = _create_training_run(conn, payload)
        docs = conn.execute(
            """
            SELECT * FROM knowledge_documents
            WHERE tenant_id=? AND merchant_id=? AND douyin_account_id=? AND is_active=1
            ORDER BY id
            """,
            (payload.tenant_id, payload.merchant_id, payload.douyin_account_id),
        ).fetchall()
        chunk_count = 0
        try:
            conn.execute(
                """
                UPDATE knowledge_chunks SET is_active=0, updated_at=CURRENT_TIMESTAMP
                WHERE tenant_id=? AND merchant_id=? AND douyin_account_id=?
                """,
                (payload.tenant_id, payload.merchant_id, payload.douyin_account_id),
            )
            for doc in docs:
                for index, chunk in enumerate(chunk_text(doc["content"]), start=1):
                    digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    embedding = client.embed(chunk)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO knowledge_chunks(
                          document_id, tenant_id, merchant_id, douyin_account_id,
                          chunk_text, chunk_index, embedding_json, embedding_model,
                          category_id, category_key, content_hash, is_active
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
                        """,
                        (
                            doc["id"],
                            doc["tenant_id"],
                            doc["merchant_id"],
                            doc["douyin_account_id"],
                            chunk,
                            index,
                            json.dumps(embedding["embedding"]),
                            embedding["model"],
                            doc["category_id"],
                            doc["category_key"],
                            digest,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE knowledge_chunks
                        SET is_active=1, embedding_json=?, embedding_model=?,
                            category_id=?, category_key=?, updated_at=CURRENT_TIMESTAMP
                        WHERE document_id=? AND content_hash=?
                        """,
                        (
                            json.dumps(embedding["embedding"]),
                            embedding["model"],
                            doc["category_id"],
                            doc["category_key"],
                            doc["id"],
                            digest,
                        ),
                    )
                    chunk_count += 1
            conn.execute(
                """
                UPDATE rag_training_runs
                SET status='completed', document_count=?, chunk_count=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (len(docs), chunk_count, run_id),
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
                """
                UPDATE rag_training_runs
                SET status='failed', document_count=?, chunk_count=?, error=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (len(docs), chunk_count, str(exc)[:500], run_id),
            )
            conn.commit()
            raise


def search(
    payload: RagSearchRequest,
    llm_client: OpenAICompatibleClient | None = None,
) -> list[RagSearchItem]:
    query_tokens = set(_tokens(payload.query))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.*, d.title
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id=c.document_id
            WHERE c.tenant_id=? AND c.merchant_id=? AND c.douyin_account_id=?
              AND c.is_active=1 AND d.is_active=1
            ORDER BY c.id DESC
            """,
            (payload.tenant_id, payload.merchant_id, payload.douyin_account_id),
        ).fetchall()

    skipped_invalid_embedding = 0
    vector_scored = []
    try:
        client = llm_client or OpenAICompatibleClient()
        query_embedding_payload = client.embed(payload.query)
        query_embedding = _coerce_embedding(query_embedding_payload.get("embedding"))
    except Exception as exc:
        query_embedding = None
        _logger.warning(
            "rag_search strategy=lexical_fallback stage=query_embedding_failed "
            "tenant_id=%s merchant_id=%s douyin_account_id=%s top_k=%d "
            "candidate_count=%d skipped_invalid_embedding=%d error_type=%s",
            payload.tenant_id,
            payload.merchant_id,
            payload.douyin_account_id,
            payload.top_k,
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
            vector_scored.sort(key=lambda item: item[0], reverse=True)
            _logger.info(
                "rag_search strategy=vector tenant_id=%s merchant_id=%s "
                "douyin_account_id=%s top_k=%d candidate_count=%d "
                "vector_result_count=%d skipped_invalid_embedding=%d",
                payload.tenant_id,
                payload.merchant_id,
                payload.douyin_account_id,
                payload.top_k,
                len(rows),
                len(vector_scored[: payload.top_k]),
                skipped_invalid_embedding,
            )
            return _to_search_items(vector_scored[: payload.top_k])

    if query_embedding is not None:
        _logger.info(
            "rag_search strategy=lexical_fallback stage=no_valid_vector_result "
            "tenant_id=%s merchant_id=%s douyin_account_id=%s top_k=%d "
            "candidate_count=%d skipped_invalid_embedding=%d",
            payload.tenant_id,
            payload.merchant_id,
            payload.douyin_account_id,
            payload.top_k,
            len(rows),
            skipped_invalid_embedding,
        )

    return _lexical_search(rows, query_tokens, payload.top_k)


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


def _lexical_search(rows: list[sqlite3.Row], query_tokens: set[str], top_k: int) -> list[RagSearchItem]:
    scored = []
    for row in rows:
        score = _score(query_tokens, str(row["chunk_text"] or ""))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    _logger.info(
        "rag_search strategy=lexical_fallback top_k=%d candidate_count=%d result_count=%d",
        top_k,
        len(rows),
        len(scored[:top_k]),
    )
    return _to_search_items(scored[:top_k])


def _to_search_items(scored_rows: list[tuple[float, sqlite3.Row]]) -> list[RagSearchItem]:
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
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO llm_call_logs(
              tenant_id, merchant_id, conversation_id, model, status, elapsed_ms, error_summary
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (tenant_id, merchant_id, conversation_id, model, status, elapsed_ms, error_summary[:500]),
        )
        conn.commit()


def _create_training_run(conn: sqlite3.Connection, payload: RagTrainRequest) -> int:
    cur = conn.execute(
        """
        INSERT INTO rag_training_runs(tenant_id, merchant_id, douyin_account_id, status)
        VALUES(?,?,?,'running')
        """,
        (payload.tenant_id, payload.merchant_id, payload.douyin_account_id),
    )
    return int(cur.lastrowid)


def _validate_category_scope(payload: KnowledgeCategoryCreate) -> None:
    if payload.scope_type == "system" and payload.merchant_id is not None:
        raise ValueError("system category merchant_id must be empty")
    if payload.scope_type == "merchant" and not payload.merchant_id:
        raise ValueError("merchant category merchant_id is required")


def _to_category_item(row: sqlite3.Row) -> KnowledgeCategoryItem:
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
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
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
