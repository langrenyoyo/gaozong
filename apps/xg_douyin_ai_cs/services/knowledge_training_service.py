"""小高知识库训练问答与反馈素材池。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from apps.xg_douyin_ai_cs.llm.client import (
    LLMNotConfiguredError,
    LLMRequestError,
    OpenAICompatibleClient,
)
from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
from apps.xg_douyin_ai_cs.rag.repository import search

KNOWLEDGE_BASE_NAME = "小高知识库"


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


def ask(payload: KnowledgeTrainingAskInput) -> dict:
    account_id = _normalize_account_id(payload.douyin_account_id)
    source_chunks = []
    if payload.use_xiaogao_knowledge_base:
        source_chunks = search(
            RagSearchRequest(
                tenant_id=payload.tenant_id,
                merchant_id=payload.merchant_id,
                douyin_account_id=account_id,
                query=payload.question,
                top_k=5,
                category_keys=["base"],
            )
        )

    answer = _build_answer(payload, source_chunks)
    training_id = f"kt-{uuid4().hex[:12]}"
    used_knowledge_base = bool(source_chunks)
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

    return {
        "training_id": training_id,
        "question": payload.question,
        "answer": answer,
        "used_knowledge_base": used_knowledge_base,
        "knowledge_base_name": KNOWLEDGE_BASE_NAME,
        "status": "answered",
    }


def submit_feedback(payload: KnowledgeTrainingFeedbackInput) -> dict:
    if payload.rating not in {"useful", "normal", "wrong"}:
        raise ValueError("INVALID_RATING")
    status = "pending_review" if payload.rating == "wrong" else "submitted"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_training_feedbacks(
              training_id, tenant_id, merchant_id, rating, comment, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.training_id,
                payload.tenant_id,
                payload.merchant_id,
                payload.rating,
                payload.comment,
                status,
            ),
        )
        conn.commit()
    return {
        "training_id": payload.training_id,
        "rating": payload.rating,
        "status": status,
        "knowledge_base_name": KNOWLEDGE_BASE_NAME,
    }


def _build_answer(payload: KnowledgeTrainingAskInput, source_chunks: list) -> str:
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
    try:
        result = OpenAICompatibleClient().chat(messages)
    except LLMNotConfiguredError:
        return _fallback_answer(payload, source_chunks, "AI 模型暂未配置")
    except LLMRequestError:
        return _fallback_answer(payload, source_chunks, "AI 模型调用失败")

    answer = str(result.get("reply_text") or "").strip()
    if answer:
        return answer
    return _fallback_answer(payload, source_chunks, "AI 未返回有效内容")


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


def _normalize_account_id(value: int | str | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
