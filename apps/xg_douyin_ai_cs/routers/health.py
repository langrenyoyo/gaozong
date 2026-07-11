"""9100 RAG 服务健康检查路由：分离 liveness (/health) 与 readiness (/ready)。

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A1。

/health：进程存活（liveness），不查数据库。
/ready：就绪度（readiness），验证 RAG 服务具备接收业务流量的条件——
        PostgreSQL 可连、连到预期 database（xg_douyin_ai_cs）、
        alembic_version 等于代码 migration head、关键 RAG 表存在并可查；
        当 RAG_VECTOR_BACKEND=milvus 时追加纯只读 Milvus readiness
        （配置/认证/collection/dimension/轻量探测），不可达即 not_ready。
        任一失败返回 503 + 结构化 error_code。

硬性约束：只读，不执行 alembic，不创建表/collection/索引，不写数据/向量；
          不调用 SQLite fallback（backend 由当前 rag_database_url 决定，
          PG 模式下 PG 不可用即 not_ready，绝不回退 SQLite）；
          Milvus 模式下 Milvus 不可达即 not_ready，绝不回退 SQLite 向量后端；
          不输出数据库或 Milvus 密码/完整 connection URL。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db_readiness import run_db_readiness
from apps.xg_douyin_ai_cs.config import settings
from apps.xg_douyin_ai_cs.rag.database import get_database_runtime, get_rag_engine
from apps.xg_douyin_ai_cs.schemas import ServiceStatusResponse, VersionResponse
from apps.xg_douyin_ai_cs.services.vector_store import run_milvus_readiness

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
# 方案 A：9100 RAG metadata database 名。
# 默认 xg_douyin_ai_cs（dev / 生产）；staging 等隔离环境通过 RAG_EXPECTED_DATABASE_NAME 覆盖
# （如 xg_douyin_ai_cs_staging），避免 readiness 永远返回 WRONG_DATABASE。
_EXPECTED_DATABASE = os.environ.get("RAG_EXPECTED_DATABASE_NAME", "xg_douyin_ai_cs")
# 关键 RAG metadata 表：alembic head 建好后必须存在（文档 + 切片两主线）
_CRITICAL_TABLES = ("knowledge_documents", "knowledge_chunks")


@router.get("/health", response_model=ServiceStatusResponse)
def health() -> ServiceStatusResponse:
    """liveness：进程存活即可，不查数据库。"""
    return ServiceStatusResponse(service=settings.service_name, status="ok")


@router.get("/ready")
def ready():
    """readiness：验证 RAG 服务具备接收业务流量的条件。

    PG 连接 + database 名（xg_douyin_ai_cs）+ alembic head + 关键表；
    当 RAG_VECTOR_BACKEND=milvus 时，追加纯只读 Milvus readiness
    （配置/认证/collection/dimension/轻量探测），失败即 not_ready，不回退 SQLite。
    只读，不执行 alembic，不创建表/collection/索引，不写入/删除向量；
    失败返回 503 + 结构化 error_code。不输出数据库或 Milvus 密码/完整 URI。
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

    # 向量后端为 milvus 时，追加纯只读 Milvus readiness；不可达即 not_ready，不回退 SQLite
    if settings.rag_vector_backend == "milvus":
        milvus_result = run_milvus_readiness(settings)
        body["milvus"] = milvus_result
        if not milvus_result.get("query_ok"):
            body["status"] = "not_ready"
            body["error_code"] = milvus_result.get("error_code", "MILVUS_NOT_READY")
            return JSONResponse(status_code=503, content=body)

    return body


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        service=settings.service_name,
        version=settings.version,
        port=settings.port,
    )
