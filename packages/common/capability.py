"""能力服务最小公共骨架。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


@dataclass(frozen=True)
class CapabilityMeta:
    """能力服务元信息。"""

    service: str
    name: str
    description: str
    version: str = "0.1.0"


class CapabilityStatus(BaseModel):
    """能力服务健康状态。"""

    service: str
    name: str
    status: str


class CapabilityRoot(BaseModel):
    """能力服务根路径响应。"""

    service: str
    name: str
    version: str
    docs: str


def create_capability_router(meta: CapabilityMeta) -> APIRouter:
    """创建能力服务基础路由。"""
    router = APIRouter(tags=["健康检查"])

    @router.get("/", response_model=CapabilityRoot)
    def root() -> CapabilityRoot:
        return CapabilityRoot(
            service=meta.service,
            name=meta.name,
            version=meta.version,
            docs="/docs",
        )

    @router.get("/health", response_model=CapabilityStatus)
    def health() -> CapabilityStatus:
        return CapabilityStatus(service=meta.service, name=meta.name, status="ok")

    return router


def create_capability_app(meta: CapabilityMeta, router: APIRouter | None = None) -> FastAPI:
    """创建可独立启动的能力服务应用。"""
    app = FastAPI(
        title=meta.name,
        version=meta.version,
        description=meta.description,
    )
    app.include_router(router or create_capability_router(meta))
    return app
