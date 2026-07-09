"""leads/tasks PG shadow read 的异步 engine 生命周期管理。"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from app import config
from app.database_url import parse_database_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeadsTasksPgEngineSettings:
    pilot_enabled: bool = config.LEADS_TASKS_PG_PILOT_ENABLED
    read_shadow_enabled: bool = config.LEADS_TASKS_PG_READ_SHADOW_ENABLED
    database_url: str = config.LEADS_TASKS_PG_DATABASE_URL
    pool_size: int = config.LEADS_TASKS_PG_POOL_SIZE
    max_overflow: int = config.LEADS_TASKS_PG_MAX_OVERFLOW
    pool_timeout: int = config.LEADS_TASKS_PG_POOL_TIMEOUT


@dataclass(frozen=True)
class _EngineSignature:
    raw_url: str
    safe_url: str
    pool_size: int
    max_overflow: int
    pool_timeout: int


@dataclass
class _EngineRecord:
    engine: Any
    loop: asyncio.AbstractEventLoop
    loop_id: int
    signature: _EngineSignature


_LOCK = threading.RLock()
_ENGINES_BY_LOOP_ID: dict[int, _EngineRecord] = {}
_STATS = {
    "created_count": 0,
    "disposed_count": 0,
    "cache_hit_count": 0,
    "cache_miss_count": 0,
}


async def get_shadow_engine(settings: Any | None = None):
    """按当前 event loop 缓存 engine；默认关闭或未配置 URL 时不创建。"""
    engine_settings = _coerce_settings(settings)
    signature = _build_signature(engine_settings)
    if signature is None:
        return None

    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    stale_record: _EngineRecord | None = None

    with _LOCK:
        record = _ENGINES_BY_LOOP_ID.get(loop_id)
        if record and record.loop is loop and not loop.is_closed() and record.signature == signature:
            _STATS["cache_hit_count"] += 1
            return record.engine

        if record:
            stale_record = record

        _STATS["cache_miss_count"] += 1
        engine = _create_async_engine(
            signature.raw_url,
            pool_size=signature.pool_size,
            max_overflow=signature.max_overflow,
            pool_timeout=signature.pool_timeout,
            pool_pre_ping=True,
        )
        _ENGINES_BY_LOOP_ID[loop_id] = _EngineRecord(
            engine=engine,
            loop=loop,
            loop_id=loop_id,
            signature=signature,
        )
        _STATS["created_count"] += 1

    logger.info("leads_tasks_pg_engine stage=engine_ready url=%s loop_id=%s", signature.safe_url, loop_id)
    if stale_record is not None:
        await _dispose_record_async(stale_record)
    return engine


def dispose_shadow_engines() -> None:
    """显式释放所有已缓存 engine；供 benchmark / smoke 收尾调用。"""
    with _LOCK:
        records = list(_ENGINES_BY_LOOP_ID.values())
        _ENGINES_BY_LOOP_ID.clear()

    for record in records:
        _dispose_record_sync(record)


def get_engine_manager_snapshot() -> dict[str, Any]:
    with _LOCK:
        records = list(_ENGINES_BY_LOOP_ID.values())
        return {
            "engine_count": len(records),
            "loop_count": len({record.loop_id for record in records}),
            "created_count": _STATS["created_count"],
            "disposed_count": _STATS["disposed_count"],
            "cache_hit_count": _STATS["cache_hit_count"],
            "cache_miss_count": _STATS["cache_miss_count"],
            "engines": [
                {
                    "loop_id": record.loop_id,
                    "database_url": record.signature.safe_url,
                    "pool_size": record.signature.pool_size,
                    "max_overflow": record.signature.max_overflow,
                    "pool_timeout": record.signature.pool_timeout,
                }
                for record in records
            ],
        }


def reset_shadow_engines_for_tests() -> None:
    """测试专用重置；生产运行只应使用 dispose_shadow_engines。"""
    dispose_shadow_engines()
    with _LOCK:
        _STATS.update(
            {
                "created_count": 0,
                "disposed_count": 0,
                "cache_hit_count": 0,
                "cache_miss_count": 0,
            }
        )


def _coerce_settings(settings: Any | None) -> LeadsTasksPgEngineSettings:
    if settings is None:
        return LeadsTasksPgEngineSettings()
    return LeadsTasksPgEngineSettings(
        pilot_enabled=bool(getattr(settings, "pilot_enabled", False)),
        read_shadow_enabled=bool(getattr(settings, "read_shadow_enabled", False)),
        database_url=str(getattr(settings, "database_url", "") or ""),
        pool_size=int(getattr(settings, "pool_size", config.LEADS_TASKS_PG_POOL_SIZE) or config.LEADS_TASKS_PG_POOL_SIZE),
        max_overflow=int(
            getattr(settings, "max_overflow", config.LEADS_TASKS_PG_MAX_OVERFLOW) or config.LEADS_TASKS_PG_MAX_OVERFLOW
        ),
        pool_timeout=int(
            getattr(settings, "pool_timeout", config.LEADS_TASKS_PG_POOL_TIMEOUT) or config.LEADS_TASKS_PG_POOL_TIMEOUT
        ),
    )


def _build_signature(settings: LeadsTasksPgEngineSettings) -> _EngineSignature | None:
    if not settings.pilot_enabled or not settings.read_shadow_enabled:
        return None
    if not settings.database_url.strip():
        return None

    parsed = parse_database_url(settings.database_url)
    if parsed.backend != "postgresql":
        raise ValueError("leads/tasks PG shadow engine 拒绝 SQLite URL")
    if not parsed.raw_url.startswith("postgresql+asyncpg://"):
        raise ValueError("leads/tasks PG shadow engine 仅允许 postgresql+asyncpg://")

    return _EngineSignature(
        raw_url=parsed.raw_url,
        safe_url=parsed.safe_url,
        pool_size=max(int(settings.pool_size), 1),
        max_overflow=max(int(settings.max_overflow), 0),
        pool_timeout=max(int(settings.pool_timeout), 1),
    )


async def _dispose_record_async(record: _EngineRecord) -> None:
    try:
        await record.engine.dispose()
    except Exception as exc:  # pragma: no cover - 真实 PG 收尾诊断
        logger.warning("leads_tasks_pg_engine stage=dispose_failed error=%s", type(exc).__name__)
    finally:
        with _LOCK:
            _STATS["disposed_count"] += 1


def _dispose_record_sync(record: _EngineRecord) -> None:
    async def _dispose():
        await record.engine.dispose()

    try:
        loop = record.loop
        if loop.is_closed():
            asyncio.run(_dispose())
        elif loop.is_running():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                loop.create_task(_dispose())
            else:
                asyncio.run_coroutine_threadsafe(_dispose(), loop).result(timeout=5)
        else:
            loop.run_until_complete(_dispose())
    except Exception as exc:  # pragma: no cover - 真实 PG 收尾诊断
        logger.warning("leads_tasks_pg_engine stage=dispose_failed error=%s", type(exc).__name__)
    finally:
        with _LOCK:
            _STATS["disposed_count"] += 1


def _create_async_engine(database_url: str, **kwargs):
    return create_async_engine(database_url, **kwargs)
