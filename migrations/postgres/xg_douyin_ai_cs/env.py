"""9100 xg_douyin_ai_cs PostgreSQL Alembic 环境。

P3-B 只建立骨架。RAG metadata 正式 schema 留到后续 P3-D。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database_url import parse_database_url


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    raw_url = os.getenv("RAG_DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("RAG_DATABASE_URL 未配置，无法执行 xg_douyin_ai_cs PostgreSQL migration")

    parsed = parse_database_url(raw_url)
    if parsed.backend != "postgresql":
        raise RuntimeError("PostgreSQL migration 目标必须使用 PostgreSQL URL，不能使用 SQLite")
    return parsed.raw_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
