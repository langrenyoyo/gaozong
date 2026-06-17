"""9100 健康检查路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.config import settings
from apps.xg_douyin_ai_cs.schemas import ServiceStatusResponse, VersionResponse

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=ServiceStatusResponse)
def health() -> ServiceStatusResponse:
    return ServiceStatusResponse(service=settings.service_name, status="ok")


@router.get("/ready", response_model=ServiceStatusResponse)
def ready() -> ServiceStatusResponse:
    return ServiceStatusResponse(service=settings.service_name, status="ok")


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        service=settings.service_name,
        version=settings.version,
        port=settings.port,
    )
