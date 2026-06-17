"""Pydantic schemas for the 9100 RAG MVP."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeDocumentCreate(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int
    title: str
    content: str
    source_type: str = "manual"
    category: str | None = None
    brand: str | None = None
    vehicle_name: str | None = None


class KnowledgeDocumentCreated(BaseModel):
    document_id: int
    status: str


class RagTrainRequest(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int


class RagTrainResponse(BaseModel):
    training_run_id: int
    status: str
    document_count: int
    chunk_count: int


class RagSearchRequest(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class RagSearchItem(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    chunk_text: str
    score: float


class RagSearchResponse(BaseModel):
    items: list[RagSearchItem]
