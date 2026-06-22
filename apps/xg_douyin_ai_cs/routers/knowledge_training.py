"""小高知识库训练接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.xg_douyin_ai_cs.services.knowledge_training_service import (
    KnowledgeTrainingAskInput,
    KnowledgeTrainingFeedbackInput,
    TrainingSessionForbiddenError,
    TrainingSessionNotFoundError,
    ask as ask_training,
    submit_feedback,
)

router = APIRouter(prefix="/knowledge-training", tags=["小高知识库训练"])


class KnowledgeTrainingAskRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1, max_length=1000)
    prompt: str | None = Field(default=None, max_length=4000)
    use_xiaogao_knowledge_base: bool = True
    douyin_account_id: int | str | None = None


class KnowledgeTrainingFeedbackRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    rating: Literal["useful", "normal", "wrong"]
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/ask")
def ask(request: KnowledgeTrainingAskRequest) -> dict:
    return ask_training(
        KnowledgeTrainingAskInput(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            question=request.question,
            prompt=request.prompt,
            use_xiaogao_knowledge_base=request.use_xiaogao_knowledge_base,
            douyin_account_id=request.douyin_account_id,
        )
    )


@router.post("/{training_id}/feedback")
def feedback(training_id: str, request: KnowledgeTrainingFeedbackRequest) -> dict:
    try:
        return submit_feedback(
            KnowledgeTrainingFeedbackInput(
                tenant_id=request.tenant_id,
                merchant_id=request.merchant_id,
                training_id=training_id,
                rating=request.rating,
                comment=request.comment,
            )
        )
    except ValueError as exc:
        if isinstance(exc, TrainingSessionNotFoundError):
            raise HTTPException(
                status_code=404,
                detail={"code": "TRAINING_SESSION_NOT_FOUND", "message": "训练会话不存在"},
            ) from exc
        if isinstance(exc, TrainingSessionForbiddenError):
            raise HTTPException(
                status_code=403,
                detail={"code": "TRAINING_SESSION_FORBIDDEN", "message": "无权反馈该训练会话"},
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
