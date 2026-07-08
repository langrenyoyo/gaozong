"""9000 auto_wechat PostgreSQL Alembic 环境。

P3-B 只建立骨架。业务表、索引和正式 schema 留到后续 P3-C。
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from urllib.parse import urlsplit

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.database_url import parse_database_url


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("DATABASE_URL 未配置，无法执行 auto_wechat PostgreSQL migration")

    parsed = parse_database_url(raw_url)
    if parsed.backend != "postgresql":
        raise RuntimeError("PostgreSQL migration 目标必须使用 PostgreSQL URL，不能使用 SQLite")
    return parsed.raw_url


def _is_asyncpg_url(database_url: str) -> bool:
    return urlsplit(database_url).scheme == "postgresql+asyncpg"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_with_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations_online(configuration: dict) -> None:
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations_with_connection)
    await connectable.dispose()


def run_sync_migrations_online(configuration: dict) -> None:
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _run_migrations_with_connection(connection)


def run_migrations_online() -> None:
    database_url = _database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url
    if _is_asyncpg_url(database_url):
        asyncio.run(run_async_migrations_online(configuration))
    else:
        run_sync_migrations_online(configuration)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
