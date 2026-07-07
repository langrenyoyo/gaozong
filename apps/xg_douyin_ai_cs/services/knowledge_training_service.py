"""小高知识库训练问答与反馈素材池。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import time
from uuid import uuid4

from apps.xg_douyin_ai_cs.llm.client import (
    LLMNotConfiguredError,
    LLMRequestError,
    OpenAICompatibleClient,
)
from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate, RagSearchRequest
from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.rag.repository import search

KNOWLEDGE_BASE_NAME = "小高知识库"
_logger = logging.getLogger(__name__)


@dataclass
class KnowledgeTrainingAskInput:
    tenant_id: str
    merchant_id: str
    question: str
    prompt: str | None = None
    use_xiaogao_knowledge_base: bool = True
    douyin_account_id: int | str | None = None


@dataclass
class KnowledgeTrainingFeedbackInput:
    tenant_id: str
    merchant_id: str
    training_id: str
    rating: str
    comment: str | None = None
    corrected_answer: str | None = None
    auto_ingest: bool = True


class TrainingSessionNotFoundError(ValueError):
    """训练会话不存在。"""


class TrainingSessionForbiddenError(ValueError):
    """训练会话不属于当前商户或租户。"""


def ask(payload: KnowledgeTrainingAskInput) -> dict:
    request_id = f"kt-req-{uuid4().hex[:12]}"
    started = time.perf_counter()
    training_id = ""
    account_id = repository.UNIFIED_KB_DOUYIN_ACCOUNT_ID
    source_chunks = []
    active_doc_count: int | None = None
    rag_skipped = False
    rag_skip_reason = ""
    rag_ms = 0
    llm_ms = 0
    db_ms = 0
    fallback = False
    error_type = ""
    rag_query = _rag_query(payload.question)
    try:
        if payload.use_xiaogao_knowledge_base:
            active_doc_count = _active_base_chunk_count(
                tenant_id=payload.tenant_id,
                merchant_id=payload.merchant_id,
                douyin_account_id=account_id,
            )
            if active_doc_count == 0:
                rag_skipped = True
                rag_skip_reason = "no_active_documents"
            else:
                rag_started = time.perf_counter()
                source_chunks = search(
                    RagSearchRequest(
                        tenant_id=payload.tenant_id,
                        merchant_id=payload.merchant_id,
                        douyin_account_id=account_id,
                        query=rag_query,
                        top_k=5,
                        category_keys=["base"],
                    )
                )
                rag_ms = _elapsed_ms(rag_started)

        answer, llm_ms, fallback, llm_error_type = _build_answer(payload, source_chunks)
        if llm_error_type:
            error_type = llm_error_type
        training_id = f"kt-{uuid4().hex[:12]}"
        used_knowledge_base = bool(source_chunks)
        db_started = time.perf_counter()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_training_sessions(
                  training_id, tenant_id, merchant_id, douyin_account_id,
                  question, answer, used_knowledge_base, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    training_id,
                    payload.tenant_id,
                    payload.merchant_id,
                    account_id,
                    payload.question,
                    answer,
                    1 if used_knowledge_base else 0,
                    "answered",
                ),
            )
            conn.commit()
        db_ms = _elapsed_ms(db_started)

        return {
            "training_id": training_id,
            "question": payload.question,
            "answer": answer,
            "used_knowledge_base": used_knowledge_base,
            "knowledge_base_name": KNOWLEDGE_BASE_NAME,
            "status": "answered",
        }
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        _log_ask_timing(
            request_id=request_id,
            training_id=training_id,
            total_ms=_elapsed_ms(started),
            active_doc_count=active_doc_count,
            rag_skipped=rag_skipped,
            rag_skip_reason=rag_skip_reason,
            rag_ms=rag_ms,
            llm_ms=llm_ms,
            db_ms=db_ms,
            match_count=len(source_chunks),
            used_knowledge_base=bool(source_chunks),
            fallback=fallback,
            error_type=error_type,
            rag_query_source="question_only",
            rag_query_chars=len(rag_query),
            prompt_chars=len(str(payload.prompt or "")),
        )


def submit_feedback(payload: KnowledgeTrainingFeedbackInput) -> dict:
    if payload.rating not in {"useful", "normal", "wrong"}:
        raise ValueError("INVALID_RATING")
    status = "pending_review" if payload.rating == "wrong" else "submitted"
    corrected_answer = _clean_text(payload.corrected_answer, limit=3000)
    auto_ingest = bool(payload.auto_ingest)
    with connect() as conn:
        session = conn.execute(
            """
            SELECT tenant_id, merchant_id, question, answer
            FROM knowledge_training_sessions
            WHERE training_id=?
            """,
            (payload.training_id,),
        ).fetchone()
        if session is None:
            raise TrainingSessionNotFoundError("TRAINING_SESSION_NOT_FOUND")
        if session["tenant_id"] != payload.tenant_id or session["merchant_id"] != payload.merchant_id:
            raise TrainingSessionForbiddenError("TRAINING_SESSION_FORBIDDEN")

        selected_answer, answer_source = _selected_ingestion_answer(
            rating=payload.rating,
            original_answer=session["answer"],
            corrected_answer=corrected_answer,
        )
        answer_hash = _answer_hash(selected_answer) if selected_answer else None
        ingestion = _skipped_ingestion("auto_ingest_disabled", enabled=False) if not auto_ingest else None
        if ingestion is None and not selected_answer:
            ingestion = _skipped_ingestion("rating_not_ingestable")

        cur = conn.execute(
            """
            INSERT INTO knowledge_training_feedbacks(
              training_id, tenant_id, merchant_id, rating, comment, status,
              corrected_answer, auto_ingest, ingestion_status, answer_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.training_id,
                payload.tenant_id,
                payload.merchant_id,
                payload.rating,
                payload.comment,
                status,
                corrected_answer or None,
                1 if auto_ingest else 0,
                ingestion["status"] if ingestion else "pending",
                answer_hash,
            ),
        )
        feedback_id = int(cur.lastrowid)
        conn.commit()

    if ingestion is None:
        ingestion = _ingest_feedback_document(
            feedback_id=feedback_id,
            training_id=payload.training_id,
            tenant_id=payload.tenant_id,
            merchant_id=payload.merchant_id,
            question=session["question"],
            selected_answer=selected_answer,
            answer_source=answer_source,
            rating=payload.rating,
            answer_hash=answer_hash,
        )
    else:
        _update_feedback_ingestion(
            feedback_id=feedback_id,
            ingestion=ingestion,
            answer_hash=answer_hash,
        )

    return {
        "training_id": payload.training_id,
        "rating": payload.rating,
        "status": status,
        "knowledge_base_name": KNOWLEDGE_BASE_NAME,
        "rag_ingestion": ingestion,
    }


def _selected_ingestion_answer(*, rating: str, original_answer: str, corrected_answer: str) -> tuple[str, str]:
    original = _clean_text(original_answer, limit=3000)
    corrected = _clean_text(corrected_answer, limit=3000)
    if corrected and corrected != original:
        return corrected, "corrected_answer"
    if rating == "useful" and original:
        return original, "ai_answer"
    return "", ""


def _clean_text(value: str | None, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _answer_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _skipped_ingestion(reason: str, *, enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "triggered": False,
        "status": "skipped",
        "reason": reason,
    }


def _ingest_feedback_document(
    *,
    feedback_id: int,
    training_id: str,
    tenant_id: str,
    merchant_id: str,
    question: str,
    selected_answer: str,
    answer_source: str,
    rating: str,
    answer_hash: str | None,
) -> dict:
    existing = _existing_completed_ingestion(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        training_id=training_id,
        answer_hash=answer_hash,
    )
    if existing:
        ingestion = {
            "enabled": True,
            "triggered": True,
            "status": "completed",
            "document_id": str(existing["ingested_document_id"]),
            "training_run_id": str(existing["ingestion_training_run_id"]),
            "reason": "already_ingested",
            "answer_source": answer_source,
        }
        _update_feedback_ingestion(feedback_id=feedback_id, ingestion=ingestion, answer_hash=answer_hash)
        return ingestion

    document_id = None
    try:
        repository.ensure_base_category(tenant_id)
        document_id = repository.create_document(
            KnowledgeDocumentCreate(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                douyin_account_id=repository.UNIFIED_KB_DOUYIN_ACCOUNT_ID,
                title=_feedback_document_title(question),
                content=_feedback_document_content(question, selected_answer),
                source_type="douyin_cs_training_feedback",
                category_key="base",
                metadata={
                    "source": "douyin_cs_training_feedback",
                    "training_id": training_id,
                    "feedback_id": str(feedback_id),
                    "rating": rating,
                    "answer_source": answer_source,
                    "auto_ingest": True,
                },
            )
        )
        training = repository.train_document(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            document_id=document_id,
        )
        ingestion = {
            "enabled": True,
            "triggered": True,
            "status": "completed",
            "document_id": str(document_id),
            "training_run_id": str(training["training_run_id"] if training else ""),
            "reason": "ingested",
            "answer_source": answer_source,
        }
    except Exception as exc:
        _logger.warning("knowledge_training_feedback_auto_ingest_failed error_type=%s", type(exc).__name__)
        ingestion = {
            "enabled": True,
            "triggered": True,
            "status": "failed",
            "document_id": "" if document_id is None else str(document_id),
            "training_run_id": "",
            "reason": "ingestion_failed",
            "error_type": type(exc).__name__,
            "answer_source": answer_source,
        }
    _update_feedback_ingestion(feedback_id=feedback_id, ingestion=ingestion, answer_hash=answer_hash)
    return ingestion


def _existing_completed_ingestion(
    *,
    tenant_id: str,
    merchant_id: str,
    training_id: str,
    answer_hash: str | None,
) -> dict | None:
    if not answer_hash:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT ingested_document_id, ingestion_training_run_id
            FROM knowledge_training_feedbacks
            WHERE tenant_id=? AND merchant_id=? AND training_id=? AND answer_hash=?
              AND ingestion_status='completed'
              AND ingested_document_id IS NOT NULL
              AND ingestion_training_run_id IS NOT NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (tenant_id, merchant_id, training_id, answer_hash),
        ).fetchone()
    return dict(row) if row else None


def _update_feedback_ingestion(*, feedback_id: int, ingestion: dict, answer_hash: str | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE knowledge_training_feedbacks
            SET ingestion_status=?, ingested_document_id=?, ingestion_training_run_id=?,
                ingestion_error=?, answer_hash=?
            WHERE id=?
            """,
            (
                ingestion.get("status"),
                _optional_int(ingestion.get("document_id")),
                _optional_int(ingestion.get("training_run_id")),
                ingestion.get("error_type") or ingestion.get("reason"),
                answer_hash,
                feedback_id,
            ),
        )
        conn.commit()


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _feedback_document_title(question: str) -> str:
    compact = _clean_text(question, limit=40)
    return f"AI抖音客服训练反馈：{compact or '未命名问题'}"


def _feedback_document_content(question: str, selected_answer: str) -> str:
    return "\n".join(
        [
            "【客户问题】",
            question,
            "",
            "【标准回答】",
            selected_answer,
            "",
            "【来源】",
            "AI 抖音客服自动回复训练反馈",
        ]
    )


def _build_answer(payload: KnowledgeTrainingAskInput, source_chunks: list) -> tuple[str, int, bool, str]:
    messages = [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是小高知识库训练助手。",
                    "你帮助商家把客户问题转成可用的回复建议。",
                    "不能承诺不确定的库存、价格、金融方案。",
                    "不要自动发送任何消息。",
                    "回答要简洁自然，只输出给商家参考的答案。",
                ]
            ),
        },
        {
            "role": "user",
            "content": _build_user_prompt(payload, source_chunks),
        },
    ]
    started = time.perf_counter()
    try:
        result = OpenAICompatibleClient().chat(messages)
    except LLMNotConfiguredError as exc:
        return (
            _fallback_answer(payload, source_chunks, "AI 模型暂未配置"),
            _elapsed_ms(started),
            True,
            type(exc).__name__,
        )
    except LLMRequestError as exc:
        return (
            _fallback_answer(payload, source_chunks, "AI 模型调用失败"),
            _elapsed_ms(started),
            True,
            type(exc).__name__,
        )

    answer = str(result.get("reply_text") or "").strip()
    if answer:
        return answer, _elapsed_ms(started), False, ""
    return (
        _fallback_answer(payload, source_chunks, "AI 未返回有效内容"),
        _elapsed_ms(started),
        True,
        "",
    )


def _build_user_prompt(payload: KnowledgeTrainingAskInput, source_chunks: list) -> str:
    knowledge_text = "\n".join(
        f"- {item.title}: {item.chunk_text}" for item in source_chunks
    )
    prompt_text = str(payload.prompt or "").strip()
    parts = [
        f"商家提示词：{prompt_text or '未配置'}",
        f"客户问题：{payload.question}",
        f"{KNOWLEDGE_BASE_NAME}：{knowledge_text or '未命中可用内容'}",
        "请给出一条可直接用于商家人工参考的回复建议。",
    ]
    return "\n".join(parts)


def _fallback_answer(payload: KnowledgeTrainingAskInput, source_chunks: list, reason: str) -> str:
    if source_chunks:
        first = source_chunks[0]
        return f"{reason}，可先参考{KNOWLEDGE_BASE_NAME}：{first.chunk_text}"
    return f"{reason}，建议先让商家补充{KNOWLEDGE_BASE_NAME}后再训练该问题。"


def _rag_query(question: str) -> str:
    return " ".join(str(question or "").split())


def _active_base_chunk_count(*, tenant_id: str, merchant_id: str, douyin_account_id: int) -> int | None:
    try:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE c.tenant_id=? AND c.merchant_id=? AND c.douyin_account_id=?
                  AND c.category_key='base' AND c.is_active=1 AND d.is_active=1
                """,
                (tenant_id, merchant_id, douyin_account_id),
            ).fetchone()
        return int(row["count"] if row else 0)
    except Exception as exc:
        _logger.warning("knowledge_training_active_doc_count_failed error_type=%s", type(exc).__name__)
        return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _log_ask_timing(
    *,
    request_id: str,
    training_id: str,
    total_ms: int,
    active_doc_count: int | None,
    rag_skipped: bool,
    rag_skip_reason: str,
    rag_ms: int,
    llm_ms: int,
    db_ms: int,
    match_count: int,
    used_knowledge_base: bool,
    fallback: bool,
    error_type: str,
    rag_query_source: str,
    rag_query_chars: int,
    prompt_chars: int,
) -> None:
    _logger.info(
        "knowledge_training_ask_timing request_id=%s training_id=%s total_ms=%d "
        "active_doc_count=%s rag_skipped=%s rag_skip_reason=%s rag_ms=%d "
        "embedding_ms=-1 milvus_ms=-1 llm_ms=%d db_ms=%d match_count=%d "
        "used_knowledge_base=%s fallback=%s error_type=%s rag_query_source=%s "
        "rag_query_chars=%d prompt_chars=%d",
        request_id,
        training_id,
        total_ms,
        "unknown" if active_doc_count is None else active_doc_count,
        rag_skipped,
        rag_skip_reason,
        rag_ms,
        llm_ms,
        db_ms,
        match_count,
        used_knowledge_base,
        fallback,
        error_type,
        rag_query_source,
        rag_query_chars,
        prompt_chars,
    )
