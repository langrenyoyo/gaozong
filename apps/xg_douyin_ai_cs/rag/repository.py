"""Repository and retrieval logic for the SQLite RAG MVP."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass

from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient
from apps.xg_douyin_ai_cs.rag.chunker import chunk_text
from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.rag.models import (
    KnowledgeDocumentCreate,
    RagSearchItem,
    RagSearchRequest,
    RagTrainRequest,
)


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    merchant_id: str
    douyin_account_id: int


def create_document(payload: KnowledgeDocumentCreate) -> int:
    if not payload.content.strip():
        raise ValueError("content must not be empty")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_documents(
              tenant_id, merchant_id, douyin_account_id, title, content,
              source_type, category, brand, vehicle_name
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.tenant_id,
                payload.merchant_id,
                payload.douyin_account_id,
                payload.title,
                payload.content,
                payload.source_type,
                payload.category,
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
                          content_hash, is_active
                        ) VALUES(?,?,?,?,?,?,?,?,?,1)
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
                            digest,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE knowledge_chunks
                        SET is_active=1, embedding_json=?, embedding_model=?, updated_at=CURRENT_TIMESTAMP
                        WHERE document_id=? AND content_hash=?
                        """,
                        (json.dumps(embedding["embedding"]), embedding["model"], doc["id"], digest),
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


def search(payload: RagSearchRequest) -> list[RagSearchItem]:
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
    scored = []
    for row in rows:
        score = _score(query_tokens, str(row["chunk_text"] or ""))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        RagSearchItem(
            chunk_id=int(row["id"]),
            document_id=int(row["document_id"]),
            title=str(row["title"]),
            chunk_text=str(row["chunk_text"]),
            score=round(float(score), 4),
        )
        for score, row in scored[: payload.top_k]
    ]


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
