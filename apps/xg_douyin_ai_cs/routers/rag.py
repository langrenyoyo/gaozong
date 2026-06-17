"""RAG training and search endpoints for the 9100 service."""

from fastapi import APIRouter, HTTPException

from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.rag.models import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentCreated,
    RagSearchRequest,
    RagSearchResponse,
    RagTrainRequest,
    RagTrainResponse,
)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/documents", response_model=KnowledgeDocumentCreated)
def create_document(payload: KnowledgeDocumentCreate) -> KnowledgeDocumentCreated:
    try:
        document_id = repository.create_document(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentCreated(document_id=document_id, status="created")


@router.post("/train", response_model=RagTrainResponse)
def train(payload: RagTrainRequest) -> RagTrainResponse:
    data = repository.train_scope(payload)
    return RagTrainResponse(**data)


@router.post("/search", response_model=RagSearchResponse)
def search(payload: RagSearchRequest) -> RagSearchResponse:
    return RagSearchResponse(items=repository.search(payload))
