"""9100 RAG 服务健康检查路由：分离 liveness (/health) 与 readiness (/ready)。

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A1。

/health：进程存活（liveness），不查数据库。
/ready：就绪度（readiness），验证 RAG 服务具备接收业务流量的条件——
        PostgreSQL 可连、连到预期 database（xg_douyin_ai_cs）、
        alembic_version 等于代码 migration head、关键 RAG 表存在并可查。
        任一失败返回 503 + 结构化 error_code。

硬性约束：只读，不执行 alembic，不创建表，不写数据；
          不调用 SQLite fallback（backend 由当前 rag_database_url 决定，
          PG 模式下 PG 不可用即 not_ready，绝不回退 SQLite）；
          不输出数据库密码或完整 connection URL。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db_readiness import run_db_readiness
from apps.xg_douyin_ai_cs.config import settings
from apps.xg_douyin_ai_cs.rag.database import get_database_runtime, get_rag_engine
from apps.xg_douyin_ai_cs.schemas import ServiceStatusResponse, VersionResponse

router = APIRouter(tags=["健康检查"])

# 9100 alembic 独立目录（migrations/postgres/xg_douyin_ai_cs/）
# health.py 位于 apps/xg_douyin_ai_cs/routers/，parents[3] 为 workspace root
_ALEMBIC_INI = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "postgres"
    / "xg_douyin_ai_cs"
    / "alembic.ini"
)
# 方案 A：9100 RAG metadata database 名
_EXPECTED_DATABASE = "xg_douyin_ai_cs"
# 关键 RAG metadata 表：alembic head 建好后必须存在（文档 + 切片两主线）
_CRITICAL_TABLES = ("knowledge_documents", "knowledge_chunks")


@router.get("/health", response_model=ServiceStatusResponse)
def health() -> ServiceStatusResponse:
    """liveness：进程存活即可，不查数据库。"""
    return ServiceStatusResponse(service=settings.service_name, status="ok")


@router.get("/ready")
def ready():
    """readiness：验证 RAG 服务具备接收业务流量的条件。

    PG 连接 + database 名（xg_douyin_ai_cs）+ alembic head + 关键表。
    只读，不执行 alembic，不创建表，不调用 SQLite fallback；
    失败返回 503 + 结构化 error_code。不输出数据库密码或完整 connection URL。
    """
    runtime = get_database_runtime()
    ok, checks, error_code = run_db_readiness(
        engine=get_rag_engine(),
        backend=runtime.backend,
        alembic_ini_path=_ALEMBIC_INI,
        expected_database=_EXPECTED_DATABASE,
        critical_tables=_CRITICAL_TABLES,
    )
    body: dict = {
        "service": settings.service_name,
        "status": "ok" if ok else "not_ready",
        "checks": checks,
    }
    if error_code:
        body["error_code"] = error_code
        return JSONResponse(status_code=503, content=body)
    return body


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        service=settings.service_name,
        version=settings.version,
        port=settings.port,
    )
