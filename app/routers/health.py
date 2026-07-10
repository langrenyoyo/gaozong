"""9000 主服务健康检查路由：分离 liveness (/health) 与 readiness (/ready)。

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A1。

/health：进程存活（liveness），不查数据库，进程能响应即 ok。
/ready：就绪度（readiness），验证服务具备接收业务流量的条件——
        PostgreSQL 可连、连到预期 database（auto_wechat）、
        alembic_version 等于代码 migration head、关键业务表存在并可查。
        任一失败返回 503 + 结构化 error_code。

硬性约束：只读，不执行 alembic，不创建表，不写数据；
          不输出数据库密码或完整 connection URL。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import engine, get_database_runtime
from app.db_readiness import run_db_readiness

router = APIRouter(tags=["健康检查"])

# 9000 alembic 双链独立目录（migrations/postgres/auto_wechat/）
_ALEMBIC_INI = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "postgres"
    / "auto_wechat"
    / "alembic.ini"
)
# 方案 A：9000 主业务 database 名
_EXPECTED_DATABASE = "auto_wechat"
# 关键业务表：alembic head 建好后必须存在并可查（覆盖线索 + 销售两条主线）
_CRITICAL_TABLES = ("douyin_leads", "sales_staff")


@router.get("/health")
def health() -> dict:
    """liveness：进程存活即可，不查数据库。"""
    return {"service": "auto_wechat", "status": "ok"}


@router.get("/ready")
def ready():
    """readiness：验证主服务具备接收业务流量的条件。

    PG 连接 + database 名（auto_wechat）+ alembic head + 关键表。
    只读，不执行 alembic，不创建表；失败返回 503 + 结构化 error_code。
    不输出数据库密码或完整 connection URL。
    """
    runtime = get_database_runtime()
    ok, checks, error_code = run_db_readiness(
        engine=engine,
        backend=runtime.backend,
        alembic_ini_path=_ALEMBIC_INI,
        expected_database=_EXPECTED_DATABASE,
        critical_tables=_CRITICAL_TABLES,
    )
    body: dict = {
        "service": "auto_wechat",
        "status": "ok" if ok else "not_ready",
        "checks": checks,
    }
    if error_code:
        body["error_code"] = error_code
        return JSONResponse(status_code=503, content=body)
    return body
