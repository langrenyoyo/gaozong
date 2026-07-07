"""小高知识库训练接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
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
    corrected_answer: str | None = Field(default=None, max_length=3000)
    auto_ingest: bool = True


class UnifiedDocumentCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=200000)
    category_key: str = Field(default="base", min_length=1, max_length=100)
    source_type: str = Field(default="manual_text", max_length=50)
    metadata: dict | None = None


class UnifiedDocumentUpdateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=200000)
    category_key: str = Field(default="base", min_length=1, max_length=100)
    metadata: dict | None = None


class UnifiedDocumentDeleteRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    mode: str = Field(default="soft_delete")
    reason: str | None = Field(default=None, max_length=500)


class UnifiedDocumentTrainRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    mode: str = Field(default="rebuild_document")
    dry_run: bool = False


class UnifiedSearchPreviewRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, max_length=1000)
    category_keys: list[str] = Field(default_factory=lambda: ["base"])
    top_k: int = Field(default=5, ge=1, le=10)


@router.get("/categories", dependencies=[Depends(require_internal_service_token)])
def list_unified_categories(tenant_id: str = Query(..., min_length=1), merchant_id: str = Query(..., min_length=1)) -> dict:
    base = repository.ensure_base_category(tenant_id)
    documents = repository.list_unified_documents(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        category_key=base.category_key,
        page=1,
        page_size=1,
    )
    return {
        "categories": [
            {
                "key": base.category_key,
                "name": base.name,
                "description": "统一知识库默认分类",
                "is_system": True,
                "document_count": documents["total"],
                "updated_at": None,
            }
        ]
    }


@router.get("/documents", dependencies=[Depends(require_internal_service_token)])
def list_unified_documents(
    tenant_id: str = Query(..., min_length=1),
    merchant_id: str = Query(..., min_length=1),
    category_key: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return repository.list_unified_documents(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        category_key=category_key,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.post("/documents", dependencies=[Depends(require_internal_service_token)])
def create_unified_document(request: UnifiedDocumentCreateRequest) -> dict:
    _validate_manual_text_document(request.source_type, request.content)
    repository.ensure_base_category(request.tenant_id)
    document_id = repository.create_document(
        KnowledgeDocumentCreate(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            douyin_account_id=repository.UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            title=request.title,
            content=request.content,
            source_type="manual_text",
            category_key=request.category_key or "base",
        )
    )
    return {"document_id": str(document_id), "status": "draft", "category_key": request.category_key or "base"}


@router.get("/documents/{document_id}", dependencies=[Depends(require_internal_service_token)])
def get_unified_document(
    document_id: str,
    tenant_id: str = Query(..., min_length=1),
    merchant_id: str = Query(..., min_length=1),
) -> dict:
    data = repository.get_unified_document(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        document_id=_document_id(document_id),
    )
    if data is None:
        raise _not_found("RAG_DOCUMENT_NOT_FOUND", "统一知识库文档不存在")
    return data


@router.put("/documents/{document_id}", dependencies=[Depends(require_internal_service_token)])
def update_unified_document(document_id: str, request: UnifiedDocumentUpdateRequest) -> dict:
    _validate_manual_text_document("manual_text", request.content)
    data = repository.update_unified_document(
        tenant_id=request.tenant_id,
        merchant_id=request.merchant_id,
        document_id=_document_id(document_id),
        title=request.title,
        content=request.content,
        category_key=request.category_key or "base",
    )
    if data is None:
        raise _not_found("RAG_DOCUMENT_NOT_FOUND", "统一知识库文档不存在")
    return {
        "document_id": data["document_id"],
        "status": data["status"],
        "category_key": data["category_key"],
        "updated_at": data["updated_at"],
    }


@router.delete("/documents/{document_id}", dependencies=[Depends(require_internal_service_token)])
def delete_unified_document(
    document_id: str,
    request: UnifiedDocumentDeleteRequest = Body(...),
) -> dict:
    if request.mode != "soft_delete":
        raise _invalid("RAG_UNSUPPORTED_OPERATION", "P1 仅支持 soft_delete")
    try:
        data = repository.soft_delete_unified_document(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            document_id=_document_id(document_id),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "RAG_VECTOR_DELETE_FAILED", "message": "向量删除失败，详情已脱敏"},
        ) from exc
    if data is None:
        raise _not_found("RAG_DOCUMENT_NOT_FOUND", "统一知识库文档不存在")
    return data


@router.post("/documents/{document_id}/train", dependencies=[Depends(require_internal_service_token)])
def train_unified_document(document_id: str, request: UnifiedDocumentTrainRequest) -> dict:
    if request.mode != "rebuild_document":
        raise _invalid("RAG_UNSUPPORTED_OPERATION", "P1 仅支持 rebuild_document")
    try:
        data = repository.train_document(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            document_id=_document_id(document_id),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "RAG_TRAINING_FAILED", "message": "训练失败，详情已脱敏"},
        ) from exc
    if data is None:
        raise _not_found("RAG_DOCUMENT_NOT_FOUND", "统一知识库文档不存在")
    return data


@router.get("/training-runs/{run_id}", dependencies=[Depends(require_internal_service_token)])
def get_unified_training_run(
    run_id: str,
    tenant_id: str = Query(..., min_length=1),
    merchant_id: str = Query(..., min_length=1),
) -> dict:
    data = repository.get_training_run(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        run_id=_document_id(run_id),
    )
    if data is None:
        raise _not_found("RAG_RUN_NOT_FOUND", "训练记录不存在")
    return data


@router.get("/training-runs", dependencies=[Depends(require_internal_service_token)])
def list_unified_training_runs(
    tenant_id: str = Query(..., min_length=1),
    merchant_id: str = Query(..., min_length=1),
    document_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return repository.list_training_runs(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        document_id=None if document_id is None else _document_id(document_id),
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/search-preview", dependencies=[Depends(require_internal_service_token)])
def search_unified_preview(request: UnifiedSearchPreviewRequest) -> dict:
    if not request.category_keys:
        return {"matches": []}
    try:
        return repository.search_unified_preview(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            query=request.query,
            category_keys=[item for item in request.category_keys if item.strip()],
            top_k=request.top_k,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "RAG_SEARCH_FAILED", "message": "检索预览失败，详情已脱敏"},
        ) from exc


@router.post("/ask", dependencies=[Depends(require_internal_service_token)])
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


@router.post("/{training_id}/feedback", dependencies=[Depends(require_internal_service_token)])
def feedback(training_id: str, request: KnowledgeTrainingFeedbackRequest) -> dict:
    try:
        return submit_feedback(
            KnowledgeTrainingFeedbackInput(
                tenant_id=request.tenant_id,
                merchant_id=request.merchant_id,
                training_id=training_id,
                rating=request.rating,
                comment=request.comment,
                corrected_answer=request.corrected_answer,
                auto_ingest=request.auto_ingest,
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


def _document_id(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _not_found("RAG_DOCUMENT_NOT_FOUND", "统一知识库文档不存在") from exc


def _validate_manual_text_document(source_type: str, content: str) -> None:
    if source_type != "manual_text":
        raise _invalid("RAG_UNSUPPORTED_OPERATION", "P1 仅支持 manual_text")
    if not content.strip():
        raise _invalid("RAG_INVALID_DOCUMENT", "文档正文不能为空")


def _invalid(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})
