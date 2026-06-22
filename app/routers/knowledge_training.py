"""小高知识库训练可信代理接口。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)

router = APIRouter(prefix="/knowledge-training", tags=["小高知识库训练"])


class KnowledgeTrainingAskRequest(BaseModel):
    """浏览器允许提交的训练问答字段，商户身份一律来自 RequestContext。"""

    question: str = Field(..., min_length=1, max_length=1000)
    prompt: str | None = Field(default=None, max_length=4000)
    use_xiaogao_knowledge_base: bool = True
    douyin_account_id: int | str | None = None


class KnowledgeTrainingFeedbackRequest(BaseModel):
    """训练反馈，wrong 仅进入待审核素材池。"""

    rating: Literal["useful", "normal", "wrong"]
    comment: str | None = Field(default=None, max_length=2000)


ASK_PUBLIC_FIELDS = {
    "training_id",
    "question",
    "answer",
    "used_knowledge_base",
    "knowledge_base_name",
    "status",
}

FEEDBACK_PUBLIC_FIELDS = {
    "training_id",
    "rating",
    "status",
    "knowledge_base_name",
}


def _require_context(context: RequestContext) -> RequestContext:
    require_permission("auto_wechat:knowledge_training")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context


def _public_payload(raw: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    payload = {key: raw.get(key) for key in fields if key in raw}
    payload["knowledge_base_name"] = "小高知识库"
    return payload


def _raise_upstream_error(exc: XgDouyinAiCsClientError) -> None:
    if exc.status_code and exc.detail:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    raise HTTPException(
        status_code=502,
        detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
    ) from exc


@router.post("/ask")
def ask(
    request: KnowledgeTrainingAskRequest,
    context: RequestContext = Depends(get_request_context_required),
) -> dict[str, Any]:
    """使用当前商户上下文调用小高知识库训练问答。"""
    context = _require_context(context)
    payload: dict[str, Any] = {
        "question": request.question,
        "prompt": request.prompt,
        "use_xiaogao_knowledge_base": request.use_xiaogao_knowledge_base,
    }
    if request.douyin_account_id is not None:
        payload["douyin_account_id"] = request.douyin_account_id

    try:
        result = get_xg_douyin_ai_cs_client().knowledge_training_ask(
            context=context,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_upstream_error(exc)

    return _public_payload(result, ASK_PUBLIC_FIELDS)


@router.post("/{training_id}/feedback")
def feedback(
    training_id: str,
    request: KnowledgeTrainingFeedbackRequest,
    context: RequestContext = Depends(get_request_context_required),
) -> dict[str, Any]:
    """提交训练反馈到素材池，不直接污染可检索知识库。"""
    context = _require_context(context)
    try:
        result = get_xg_douyin_ai_cs_client().knowledge_training_feedback(
            context=context,
            training_id=training_id,
            request={"rating": request.rating, "comment": request.comment},
        )
    except XgDouyinAiCsClientError as exc:
        _raise_upstream_error(exc)

    return _public_payload(result, FEEDBACK_PUBLIC_FIELDS)
