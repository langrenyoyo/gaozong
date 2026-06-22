"""统一知识库训练能力服务 DTO。

Phase 3-C 仍与 9000 共享接口契约，旧 `app.schemas` 保留兼容定义。
"""

from pydantic import BaseModel

from app.schemas import (
    KnowledgeCategoryCreate,
    KnowledgeCategoryListResponse,
    KnowledgeCategoryOut,
)


class RagDocumentProxyRequest(BaseModel):
    """9206 RAG 文档可信代理允许浏览器提交的字段。"""

    account_open_id: str
    title: str
    content: str
    category_key: str | None = None
    category: str | None = None
    brand: str | None = None
    vehicle_name: str | None = None


class RagTrainProxyRequest(BaseModel):
    """9206 RAG 训练可信代理允许浏览器提交的字段。"""

    account_open_id: str
    category_key: str | None = None
    force_rebuild: bool | None = None


__all__ = [
    "KnowledgeCategoryCreate",
    "KnowledgeCategoryListResponse",
    "KnowledgeCategoryOut",
    "RagDocumentProxyRequest",
    "RagTrainProxyRequest",
]
