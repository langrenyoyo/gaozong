"""leads/tasks PostgreSQL shadow read 运行态脚手架。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import text

from app import config
from app.database_url import parse_database_url
from app.services.leads_tasks_shadow_compare import compare_shadow_rows

logger = logging.getLogger(__name__)

READ_ONLY_SQL_TEMPLATES = (
    "SELECT id FROM sales_staff WHERE merchant_id = :merchant_id ORDER BY id ASC",
    "SELECT id FROM wechat_tasks ORDER BY id DESC LIMIT :limit",
)

_shadow_engine = None


@dataclass(frozen=True)
class LeadsTasksPgShadowSettings:
    pilot_enabled: bool = config.LEADS_TASKS_PG_PILOT_ENABLED
    read_shadow_enabled: bool = config.LEADS_TASKS_PG_READ_SHADOW_ENABLED
    write_enabled: bool = config.LEADS_TASKS_PG_WRITE_ENABLED
    strict_contrast: bool = config.LEADS_TASKS_PG_STRICT_CONTRAST
    database_url: str = config.LEADS_TASKS_PG_DATABASE_URL
    pool_size: int = config.LEADS_TASKS_PG_POOL_SIZE
    max_overflow: int = config.LEADS_TASKS_PG_MAX_OVERFLOW
    pool_timeout: int = config.LEADS_TASKS_PG_POOL_TIMEOUT
    statement_timeout_ms: int = config.LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS
    shadow_timeout_ms: int = config.LEADS_TASKS_PG_SHADOW_TIMEOUT_MS


@dataclass(frozen=True)
class ShadowReadResult:
    enabled: bool
    table: str
    operation: str
    sqlite_count: int = 0
    pg_count: int = 0
    count_match: bool = True
    key_match: bool = True
    mismatch_count: int = 0
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def get_shadow_engine_for_test():
    """测试观察点：默认配置下应保持 None，证明没有初始化 PG engine。"""
    return _shadow_engine


def is_shadow_configured(settings: LeadsTasksPgShadowSettings | None = None) -> bool:
    return should_shadow_read(settings or LeadsTasksPgShadowSettings())


def should_shadow_read(settings: LeadsTasksPgShadowSettings) -> bool:
    """判断是否允许 shadow read；任何条件不满足都安静关闭。"""
    if not settings.pilot_enabled or not settings.read_shadow_enabled:
        return False
    if not settings.database_url.strip():
        return False
    try:
        parsed = parse_database_url(settings.database_url)
    except ValueError as exc:
        logger.warning("leads_tasks_pg_shadow stage=config invalid_url=%s", exc)
        return False
    if parsed.backend != "postgresql":
        logger.warning("leads_tasks_pg_shadow stage=config rejected SQLite URL")
        return False
    if urlsplit(parsed.raw_url).scheme != "postgresql+asyncpg":
        logger.warning("leads_tasks_pg_shadow stage=config rejected non_asyncpg_url=%s", parsed.safe_url)
        return False
    return True


def run_sales_staff_list_shadow_read(
    *,
    sqlite_rows: Sequence[Mapping[str, object] | object],
    merchant_id: str,
    status: str | None = None,
    keyword: str | None = None,
    include_deleted: bool = False,
    settings: LeadsTasksPgShadowSettings | None = None,
) -> ShadowReadResult:
    settings = settings or LeadsTasksPgShadowSettings()
    return _run_shadow_read_sync(
        table="sales_staff",
        operation="list",
        sqlite_rows=_normalize_rows(sqlite_rows),
        key_columns=("id",),
        filters={
            "merchant_id": merchant_id,
            "status": status,
            "keyword": keyword,
            "include_deleted": include_deleted,
        },
        settings=settings,
    )


def run_wechat_tasks_history_shadow_read(
    *,
    sqlite_rows: Sequence[Mapping[str, object] | object],
    merchant_id: str,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    task_type: str | None = None,
    mode: str | None = None,
    keyword: str | None = None,
    failure_stage: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    settings: LeadsTasksPgShadowSettings | None = None,
) -> ShadowReadResult:
    settings = settings or LeadsTasksPgShadowSettings()
    return _run_shadow_read_sync(
        table="wechat_tasks",
        operation="history",
        sqlite_rows=_normalize_rows(sqlite_rows),
        key_columns=("id",),
        filters={
            "merchant_id": merchant_id,
            "page": page,
            "page_size": page_size,
            "status": status,
            "task_type": task_type,
            "mode": mode,
            "keyword": keyword,
            "failure_stage": failure_stage,
            "date_from": date_from,
            "date_to": date_to,
        },
        settings=settings,
    )


def _run_shadow_read_sync(
    *,
    table: str,
    operation: str,
    sqlite_rows: list[dict[str, object]],
    key_columns: Sequence[str],
    filters: Mapping[str, object],
    settings: LeadsTasksPgShadowSettings,
) -> ShadowReadResult:
    if not should_shadow_read(settings):
        return ShadowReadResult(enabled=False, table=table, operation=operation, sqlite_count=len(sqlite_rows))

    started = time.perf_counter()
    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_shadow_read_async(
                    table=table,
                    operation=operation,
                    sqlite_rows=sqlite_rows,
                    key_columns=key_columns,
                    filters=filters,
                    settings=settings,
                ),
                timeout=settings.shadow_timeout_ms / 1000,
            )
        )
    except TimeoutError:
        result = ShadowReadResult(
            enabled=True,
            table=table,
            operation=operation,
            sqlite_count=len(sqlite_rows),
            warnings=[f"{table}.{operation} shadow read 超时"],
        )
    except Exception as exc:
        result = ShadowReadResult(
            enabled=True,
            table=table,
            operation=operation,
            sqlite_count=len(sqlite_rows),
            warnings=[f"{table}.{operation} shadow read 异常: {type(exc).__name__}: {exc}"],
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.warning(
        "leads_tasks_pg_shadow table=%s operation=%s sqlite_count=%s pg_count=%s count_match=%s key_match=%s mismatch_count=%s duration_ms=%s warnings=%s",
        result.table,
        result.operation,
        result.sqlite_count,
        result.pg_count,
        result.count_match,
        result.key_match,
        result.mismatch_count,
        duration_ms,
        result.warnings,
    )
    return ShadowReadResult(**{**result.__dict__, "duration_ms": duration_ms})


async def _run_shadow_read_async(
    *,
    table: str,
    operation: str,
    sqlite_rows: list[dict[str, object]],
    key_columns: Sequence[str],
    filters: Mapping[str, object],
    settings: LeadsTasksPgShadowSettings,
) -> ShadowReadResult:
    pg_rows = await _select_pg_rows(table=table, filters=filters, settings=settings)
    compare = compare_shadow_rows(
        table=table,
        key_columns=key_columns,
        sqlite_rows=sqlite_rows,
        pg_rows=pg_rows,
    )
    return ShadowReadResult(
        enabled=True,
        table=table,
        operation=operation,
        sqlite_count=compare.sqlite_count,
        pg_count=compare.pg_count,
        count_match=compare.count_match,
        key_match=compare.key_match,
        mismatch_count=compare.mismatch_count,
        warnings=compare.warnings,
    )


async def _select_pg_rows(
    *,
    table: str,
    filters: Mapping[str, object],
    settings: LeadsTasksPgShadowSettings,
) -> list[dict[str, object]]:
    engine = _get_or_create_shadow_engine(settings)
    statement, params = _build_select(table, filters)
    async with engine.connect() as conn:
        if settings.statement_timeout_ms > 0:
            await conn.execute(text("SET statement_timeout = :timeout_ms"), {"timeout_ms": settings.statement_timeout_ms})
        result = await conn.execute(statement, params)
        return [dict(row._mapping) for row in result.fetchall()]


def _get_or_create_shadow_engine(settings: LeadsTasksPgShadowSettings):
    global _shadow_engine
    if _shadow_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        parsed = parse_database_url(settings.database_url)
        _shadow_engine = create_async_engine(
            parsed.raw_url,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout,
            pool_pre_ping=True,
        )
        logger.info("leads_tasks_pg_shadow stage=engine_init url=%s", parsed.safe_url)
    return _shadow_engine


def _build_select(table: str, filters: Mapping[str, object]):
    if table == "sales_staff":
        clauses = ["merchant_id = :merchant_id"]
        params: dict[str, object] = {"merchant_id": filters["merchant_id"]}
        status = (filters.get("status") or "all").strip().lower() if isinstance(filters.get("status"), str) else "all"
        if status == "active":
            clauses.append("status = 'active'")
        elif status == "disabled":
            clauses.append("status IN ('disabled', 'inactive')")
        elif status == "deleted":
            clauses.append("status = 'deleted'")
        elif status == "all" and not filters.get("include_deleted"):
            clauses.append("status <> 'deleted'")
        elif status not in {"all", ""}:
            clauses.append("status = :status")
            params["status"] = status
        keyword = (filters.get("keyword") or "").strip() if isinstance(filters.get("keyword"), str) else ""
        if keyword:
            params["keyword"] = f"%{keyword}%"
            clauses.append("(name LIKE :keyword OR wechat_nickname LIKE :keyword OR wechat_id LIKE :keyword OR phone LIKE :keyword)")
        return text(f"SELECT id FROM sales_staff WHERE {' AND '.join(clauses)} ORDER BY id ASC"), params

    if table == "wechat_tasks":
        clauses = ["(douyin_leads.merchant_id = :merchant_id OR sales_staff.merchant_id = :merchant_id)"]
        params = {
            "merchant_id": filters["merchant_id"],
            "limit": min(max(int(filters.get("page_size") or 20), 1), 100),
            "offset": (max(int(filters.get("page") or 1), 1) - 1) * min(max(int(filters.get("page_size") or 20), 1), 100),
        }
        for name, column in (("status", "wechat_tasks.status"), ("task_type", "wechat_tasks.task_type"), ("mode", "wechat_tasks.mode")):
            value = (filters.get(name) or "").strip() if isinstance(filters.get(name), str) else ""
            if value and value != "all":
                clauses.append(f"{column} = :{name}")
                params[name] = value
        failure_stage = (filters.get("failure_stage") or "").strip() if isinstance(filters.get("failure_stage"), str) else ""
        if failure_stage:
            clauses.append("wechat_tasks.failure_stage = :failure_stage")
            params["failure_stage"] = failure_stage
        if filters.get("date_from"):
            clauses.append("wechat_tasks.created_at >= :date_from")
            params["date_from"] = filters["date_from"]
        if filters.get("date_to"):
            clauses.append("wechat_tasks.created_at <= :date_to")
            params["date_to"] = filters["date_to"]
        keyword = (filters.get("keyword") or "").strip() if isinstance(filters.get("keyword"), str) else ""
        if keyword:
            params["keyword"] = f"%{keyword}%"
            clauses.append(
                "(wechat_tasks.target_nickname LIKE :keyword OR sales_staff.name LIKE :keyword "
                "OR sales_staff.wechat_nickname LIKE :keyword OR douyin_leads.customer_contact LIKE :keyword)"
            )
        sql = f"""
            SELECT wechat_tasks.id
            FROM wechat_tasks
            LEFT JOIN douyin_leads ON wechat_tasks.lead_id = douyin_leads.id
            LEFT JOIN sales_staff ON wechat_tasks.staff_id = sales_staff.id
            WHERE {' AND '.join(clauses)}
            ORDER BY wechat_tasks.id DESC
            LIMIT :limit OFFSET :offset
        """
        return text(sql), params

    raise ValueError(f"不支持的 shadow read 表: {table}")


def _normalize_rows(rows: Sequence[Mapping[str, object] | object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, Mapping):
            normalized.append(dict(row))
            continue
        data = getattr(row, "__dict__", {})
        normalized.append({key: value for key, value in data.items() if not key.startswith("_")})
    return normalized
