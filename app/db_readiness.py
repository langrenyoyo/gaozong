"""数据库就绪度检查共享逻辑（9000 主服务与 9100 RAG 服务共用）。

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A1：分离 liveness 与 readiness。
/ready 表示服务是否具备接收业务流量的条件，必须验证 PostgreSQL 可用、
连到预期 database、alembic 处于代码 migration head、关键业务表存在并可查。

硬性约束：
- 只读。不执行 alembic upgrade，不创建表，不写任何数据。
- 任一检查失败返回非 2xx（由调用方套 503）+ 结构化 error_code。
- 不输出数据库密码或完整 connection URL（异常信息截断）。
- 非 PG 后端（dev SQLite）简化为连接检查，不强制 alembic / 关键表（dev 容错）；
  生产环境必须 PG，由 compose / .env 保证 backend=postgresql。

alembic head 用 ScriptDirectory.get_heads() 读代码 migration 目录（模块级缓存），
不硬编码 revision id——升级 migration 时 readiness 自动跟上，不会出现硬编码漂移。
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import Any

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 按 alembic_ini_path 缓存 head 列表；部署后 migration 文件不变，进程生命周期内读一次
_alembic_head_cache: dict[str, list[str]] = {}
_alembic_head_lock = Lock()

# 结构化错误码（readiness 失败原因，供运维 / 监控 / Runbook 识别）
ERROR_DB_CONNECT = "DB_CONNECT_FAILED"
ERROR_WRONG_DATABASE = "WRONG_DATABASE"
ERROR_ALEMBIC_REVISION = "ALEMBIC_REVISION_MISMATCH"
ERROR_CRITICAL_TABLE = "CRITICAL_TABLE_MISSING"
ERROR_SQLITE_REVISION = "SQLITE_REVISION_MISMATCH"
ERROR_SQLITE_SCHEMA = "SQLITE_SCHEMA_INCOMPLETE"


def load_alembic_heads(alembic_ini_path: str | Path) -> list[str]:
    """读 alembic script directory 的 head revision 列表（不连 DB）。

    双链时返回多个 head（本项目 9000 / 9100 均为单链，实际单个）。
    alembic.ini 中 script_location = %(here)s，Config 初始化时自动解析为 ini 所在目录。
    """
    key = str(alembic_ini_path)
    cached = _alembic_head_cache.get(key)
    if cached is not None:
        return cached
    with _alembic_head_lock:
        cached = _alembic_head_cache.get(key)
        if cached is None:
            cfg = AlembicConfig(key)
            script = ScriptDirectory.from_config(cfg)
            _alembic_head_cache[key] = sorted(script.get_heads())
    return _alembic_head_cache[key]


def _safe_error(exc: BaseException, limit: int = 200) -> str:
    """截断异常信息，避免泄露完整 connection URL / 密码。

    PG 异常（表不存在 / 认证失败 / 连接拒绝）本身不含密码，但保守截断防意外。
    """
    name = type(exc).__name__
    detail = str(exc).strip()
    msg = f"{name}: {detail}" if detail else name
    return msg if len(msg) <= limit else msg[:limit]


def run_db_readiness(
    *,
    engine: Engine,
    backend: str,
    alembic_ini_path: str | Path,
    expected_database: str,
    critical_tables: tuple[str, ...],
    sqlite_versions_dir: str | Path | None = None,
    sqlite_required_columns: dict[str, set[str]] | None = None,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    """执行数据库就绪检查，返回 (all_pass, checks, error_code)。

    PG backend：验证连接 + current_database() + alembic head + 关键表（4 步）。
    非 PG backend（dev SQLite）：简化为连接检查，不校验 database 名 / alembic / 关键表。
    只读，不执行 alembic，不创建表；失败时 error_code 非空，调用方据此返回 503。
    """
    checks: list[dict[str, Any]] = [
        {"name": "backend", "status": "pass", "backend": backend}
    ]

    # 非 PG backend 默认保持原连接检查；9000 显式传 versions 目录时增加 SQLite
    # revision 与关键字段校验。9100 未传该参数，不受本轮改造影响。
    if backend != "postgresql":
        checks[-1]["mode"] = "dev_non_pg"
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                checks.append({"name": "db_connect", "status": "pass"})
                if backend != "sqlite" or sqlite_versions_dir is None:
                    return True, checks, None

                from migrations.migrate_sqlite import discover_migrations

                migrations = discover_migrations(sqlite_versions_dir)
                known = [item.version for item in migrations]
                expected = known[-1] if known else None
                db_inspector = inspect(conn)
                applied: list[str] = []
                if db_inspector.has_table("schema_migrations"):
                    applied = [
                        row[0]
                        for row in conn.execute(
                            text(
                                "SELECT version_num FROM schema_migrations "
                                "ORDER BY version_num"
                            )
                        )
                    ]
                current = applied[-1] if applied else None
                unknown = [version for version in applied if version not in set(known)]
                revision_ok = bool(known) and applied == known
                checks.append(
                    {
                        "name": "schema_revision",
                        "status": "pass" if revision_ok else "fail",
                        "current": current,
                        "expected": expected,
                        "unknown": unknown,
                    }
                )
                if not revision_ok:
                    return False, checks, ERROR_SQLITE_REVISION

                missing: dict[str, list[str]] = {}
                for table, required in (sqlite_required_columns or {}).items():
                    if not db_inspector.has_table(table):
                        missing[table] = sorted(required)
                        continue
                    actual = {column["name"] for column in db_inspector.get_columns(table)}
                    absent = sorted(required - actual)
                    if absent:
                        missing[table] = absent
                checks.append(
                    {
                        "name": "critical_schema_fields",
                        "status": "fail" if missing else "pass",
                        "missing": missing,
                    }
                )
                if missing:
                    return False, checks, ERROR_SQLITE_SCHEMA
                return True, checks, None
        except Exception as exc:  # noqa: BLE001 — readiness 必须兜底所有连接异常，不能 500
            checks.append({"name": "db_connect", "status": "fail", "error": _safe_error(exc)})
            return False, checks, ERROR_DB_CONNECT

    # PG backend：完整 4 步检查
    # 1. 连接 + current_database() + alembic_version（同一连接内完成，减少握手）
    actual_db: str | None = None
    actual_revs: list[str] = []
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            actual_db = conn.execute(text("SELECT current_database()")).scalar()
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            actual_revs = sorted(r[0] for r in rows)
        checks.append({"name": "db_connect", "status": "pass"})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "db_connect", "status": "fail", "error": _safe_error(exc)})
        return False, checks, ERROR_DB_CONNECT

    # 2. database 名校验（方案 A：9000=auto_wechat，9100=xg_douyin_ai_cs，互不串库）
    db_ok = actual_db == expected_database
    checks.append({
        "name": "database_name",
        "status": "pass" if db_ok else "fail",
        "expected": expected_database,
        "actual": actual_db,
    })

    # 3. alembic head 校验（数据库实际 revision 必须等于代码 migration head）
    expected_heads = load_alembic_heads(alembic_ini_path)
    rev_ok = actual_revs == expected_heads
    checks.append({
        "name": "alembic_revision",
        "status": "pass" if rev_ok else "fail",
        "expected": expected_heads,
        "actual": actual_revs,
    })

    # 4. 关键表（每张单独 try，区分哪张缺失；双引号强制匹配，避免大小写 / 关键字问题）
    table_results: list[dict[str, Any]] = []
    tables_all_ok = True
    try:
        with engine.connect() as conn:
            for tbl in critical_tables:
                try:
                    conn.execute(text(f'SELECT 1 FROM "{tbl}" LIMIT 1'))
                    table_results.append({"table": tbl, "status": "pass"})
                except Exception as texc:  # noqa: BLE001
                    table_results.append({"table": tbl, "status": "fail", "error": _safe_error(texc)})
                    tables_all_ok = False
        checks.append({
            "name": "critical_tables",
            "status": "pass" if tables_all_ok else "fail",
            "tables": table_results,
        })
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "critical_tables", "status": "fail", "error": _safe_error(exc)})
        tables_all_ok = False

    # 汇总：按检查顺序，首个 fail 决定 error_code
    if not db_ok:
        return False, checks, ERROR_WRONG_DATABASE
    if not rev_ok:
        return False, checks, ERROR_ALEMBIC_REVISION
    if not tables_all_ok:
        return False, checks, ERROR_CRITICAL_TABLE
    return True, checks, None
