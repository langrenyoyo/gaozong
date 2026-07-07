"""数据库连接和会话管理。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_DIR, DATABASE_URL
from app.database_url import parse_database_url

logger = logging.getLogger(__name__)

# 确保 data 目录存在。PostgreSQL 接入后该目录只服务 SQLite 兼容路径。
os.makedirs(DATABASE_DIR, exist_ok=True)

SQLALCHEMY_POOL_SIZE = int(os.getenv("SQLALCHEMY_POOL_SIZE", "10"))
SQLALCHEMY_MAX_OVERFLOW = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "20"))
SQLALCHEMY_POOL_TIMEOUT = int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "30"))
SQLALCHEMY_POOL_PRE_PING = os.getenv("SQLALCHEMY_POOL_PRE_PING", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@dataclass(frozen=True)
class DatabaseRuntime:
    backend: str
    raw_url: str
    safe_url: str
    sqlite_path: str | None


def get_database_runtime(database_url: str | None = None) -> DatabaseRuntime:
    """返回 9000 数据库运行时描述，不创建连接。"""
    parsed = parse_database_url(database_url or DATABASE_URL)
    return DatabaseRuntime(
        backend=parsed.backend,
        raw_url=parsed.raw_url,
        safe_url=parsed.safe_url,
        sqlite_path=parsed.sqlite_path,
    )


def get_sqlite_path(database_url: str | None = None) -> str:
    """返回 SQLite 文件路径；PostgreSQL 会在后续阶段接入。"""
    runtime = get_database_runtime(database_url)
    if runtime.backend != "sqlite" or not runtime.sqlite_path:
        raise RuntimeError("当前 9000 database factory 仅允许从 SQLite URL 提取文件路径")
    return runtime.sqlite_path


def create_database_engine(database_url: str | None = None):
    """创建 9000 SQLAlchemy engine；本轮 PostgreSQL 只识别、不连接。"""
    runtime = get_database_runtime(database_url)
    if runtime.backend == "postgresql":
        raise RuntimeError("PostgreSQL backend 已识别但本轮未启用，后续 P2/P3 再接入连接池")
    if runtime.backend != "sqlite":
        raise RuntimeError(f"不支持的数据库后端: {runtime.backend}")

    # SQLite 兼容层：保持当前多线程、写锁等待和 WAL 行为不变。
    return create_engine(
        runtime.raw_url,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
        pool_size=SQLALCHEMY_POOL_SIZE,
        max_overflow=SQLALCHEMY_MAX_OVERFLOW,
        pool_timeout=SQLALCHEMY_POOL_TIMEOUT,
        pool_pre_ping=SQLALCHEMY_POOL_PRE_PING,
    )


# 后续 PostgreSQL 推荐 asyncpg 或 SQLAlchemy async engine，并在 startup/shutdown
# 中初始化和关闭连接池；本轮不在 async 请求链路新增阻塞式数据库访问。
DATABASE_RUNTIME = get_database_runtime()
engine = create_database_engine(DATABASE_URL)

logger.info(
    "db_engine_config stage=create_engine backend=%s url=%s pool_size=%s max_overflow=%s pool_timeout=%s pool_pre_ping=%s",
    DATABASE_RUNTIME.backend,
    DATABASE_RUNTIME.safe_url,
    SQLALCHEMY_POOL_SIZE,
    SQLALCHEMY_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT,
    SQLALCHEMY_POOL_PRE_PING,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """连接创建时设置 WAL 模式。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：获取数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
