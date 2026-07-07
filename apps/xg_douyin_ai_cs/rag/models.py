"""Pydantic schemas for the 9100 RAG MVP."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeCategoryCreate(BaseModel):
    tenant_id: str
    merchant_id: str | None = None
    category_key: str
    name: str
    scope_type: str = Field(pattern="^(system|merchant)$")
    is_base: bool = False
    is_active: bool = True
    sort_order: int = 100


class KnowledgeCategoryItem(BaseModel):
    id: int
    tenant_id: str
    merchant_id: str | None = None
    category_key: str
    name: str
    scope_type: str
    is_base: bool
    is_active: bool
    sort_order: int


class KnowledgeCategoryListResponse(BaseModel):
    items: list[KnowledgeCategoryItem]


class KnowledgeDocumentCreate(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int | str
    title: str
    content: str
    source_type: str = "manual"
    category: str | None = None
    category_id: int | None = None
    category_key: str | None = None
    brand: str | None = None
    vehicle_name: str | None = None
    metadata: dict | None = None


class KnowledgeDocumentCreated(BaseModel):
    document_id: int
    status: str


class RagTrainRequest(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int | str


class RagTrainResponse(BaseModel):
    training_run_id: int
    status: str
    document_count: int
    chunk_count: int


class RagSearchRequest(BaseModel):
    tenant_id: str
    merchant_id: str
    douyin_account_id: int | str
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    category_ids: list[str] | None = None
    category_keys: list[str] | None = None


class RagSearchItem(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    chunk_text: str
    score: float


class RagSearchResponse(BaseModel):
    items: list[RagSearchItem]
