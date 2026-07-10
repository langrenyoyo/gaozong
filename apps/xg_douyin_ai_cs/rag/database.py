"""9100 RAG metadata database bootstrap."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, event

from app.database_url import parse_database_url
from apps.xg_douyin_ai_cs.config import settings


@dataclass(frozen=True)
class RagDatabaseRuntime:
    backend: str
    raw_url: str
    safe_url: str
    sqlite_path: str | None


def get_database_runtime(database_url: str | None = None) -> RagDatabaseRuntime:
    """返回 9100 RAG metadata 数据库运行时描述，不创建连接。"""
    parsed = parse_database_url(database_url or settings.rag_database_url)
    return RagDatabaseRuntime(
        backend=parsed.backend,
        raw_url=parsed.raw_url,
        safe_url=parsed.safe_url,
        sqlite_path=parsed.sqlite_path,
    )


def database_path(database_url: str | None = None) -> Path:
    runtime = get_database_runtime(database_url)
    if runtime.backend != "sqlite" or not runtime.sqlite_path:
        raise RuntimeError("当前 9100 database factory 仅允许从 SQLite URL 提取 metadata 文件路径")
    return Path(runtime.sqlite_path)


def _postgres_sync_url(raw_url: str) -> str:
    """把规划中的 asyncpg URL 转成同步 psycopg URL（对齐 9000 create_database_engine）。"""
    parts = urlsplit(raw_url)
    if parts.scheme in {"postgresql", "postgresql+asyncpg"}:
        return parts._replace(scheme="postgresql+psycopg").geturl()
    return raw_url


def create_rag_engine(database_url: str | None = None):
    """创建 9100 RAG metadata SQLAlchemy engine。

    P3-D2：PG backend 使用同步 psycopg + 连接池（对齐 9000），供 alembic / smoke / 后续
    P3-D3 repository 改写使用。SQLite backend 保留 dev 兜底。本函数不替换 connect()——
    repository 仍走 sqlite3 路径，P3-D3 改写后才切换到 engine / Session。
    """
    runtime = get_database_runtime(database_url)
    if runtime.backend == "postgresql":
        engine = create_engine(
            _postgres_sync_url(runtime.raw_url),
            pool_size=settings.rag_db_pool_size,
            max_overflow=settings.rag_db_max_overflow,
            pool_timeout=settings.rag_db_pool_timeout,
            pool_recycle=settings.rag_db_pool_recycle,
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _set_statement_timeout(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET statement_timeout = {settings.rag_db_statement_timeout_ms}")
            cursor.close()

        return engine
    if runtime.backend != "sqlite":
        raise RuntimeError(f"不支持的 9100 RAG 数据库后端: {runtime.backend}")
    # SQLite dev 兜底（不进连接池配置，保持简单）
    return create_engine(
        runtime.raw_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def connect(database_url: str | None = None) -> sqlite3.Connection:
    runtime = get_database_runtime(database_url)
    if runtime.backend == "postgresql":
        raise RuntimeError(
            "PostgreSQL backend 已识别，但 9100 repository 仍使用 SQLite 专属 SQL "
            "（PRAGMA / INSERT OR IGNORE / ? 占位符），P3-D3 改写前 connect() 不可用；"
            "PG schema 由 alembic 管理，engine 走 create_rag_engine()"
        )
    if runtime.backend != "sqlite" or not runtime.sqlite_path:
        raise RuntimeError(f"不支持的 9100 metadata 数据库后端: {runtime.backend}")

    path = Path(runtime.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn)
    return conn


# 后续 PostgreSQL 推荐 asyncpg 或 SQLAlchemy async engine，并在 FastAPI startup/shutdown
# 中初始化和关闭连接池。本轮不创建 RAG PostgreSQL pool，也不新增 async 请求链路阻塞访问。


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT,
          category_key TEXT NOT NULL,
          name TEXT NOT NULL,
          scope_type TEXT NOT NULL,
          is_base INTEGER NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 100,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CHECK(scope_type IN ('system', 'merchant')),
          CHECK(
            (scope_type='system' AND merchant_id IS NULL)
            OR (scope_type='merchant' AND merchant_id IS NOT NULL)
          )
        );

        CREATE TABLE IF NOT EXISTS knowledge_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          douyin_account_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT 'manual',
          category TEXT,
          category_id INTEGER,
          category_key TEXT,
          brand TEXT,
          vehicle_name TEXT,
          metadata_json TEXT,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          douyin_account_id INTEGER NOT NULL,
          chunk_text TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          embedding_json TEXT NOT NULL,
          embedding_model TEXT NOT NULL,
          category_id INTEGER,
          category_key TEXT,
          content_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(document_id, content_hash)
        );

        CREATE TABLE IF NOT EXISTS rag_training_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          douyin_account_id INTEGER NOT NULL,
          status TEXT NOT NULL,
          document_count INTEGER NOT NULL DEFAULT 0,
          chunk_count INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS llm_call_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT,
          merchant_id TEXT,
          conversation_id INTEGER,
          model TEXT,
          status TEXT NOT NULL,
          elapsed_ms INTEGER NOT NULL DEFAULT 0,
          error_summary TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_training_sessions (
          training_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          douyin_account_id INTEGER NOT NULL DEFAULT 0,
          question TEXT NOT NULL,
          answer TEXT NOT NULL,
          used_knowledge_base INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_training_feedbacks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          training_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          rating TEXT NOT NULL,
          comment TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CHECK(rating IN ('useful', 'normal', 'wrong')),
          CHECK(status IN ('submitted', 'pending_review'))
        );

        CREATE INDEX IF NOT EXISTS idx_documents_scope
        ON knowledge_documents(tenant_id, merchant_id, douyin_account_id, is_active);

        CREATE INDEX IF NOT EXISTS idx_chunks_scope
        ON knowledge_chunks(tenant_id, merchant_id, douyin_account_id, is_active);

        CREATE UNIQUE INDEX IF NOT EXISTS uk_categories_system_key
        ON knowledge_categories(tenant_id, category_key, scope_type)
        WHERE scope_type='system';

        CREATE UNIQUE INDEX IF NOT EXISTS uk_categories_merchant_key
        ON knowledge_categories(tenant_id, merchant_id, category_key, scope_type)
        WHERE scope_type='merchant';

        CREATE INDEX IF NOT EXISTS idx_categories_visible
        ON knowledge_categories(tenant_id, merchant_id, scope_type, is_active, sort_order);

        CREATE INDEX IF NOT EXISTS idx_knowledge_training_feedbacks_scope
        ON knowledge_training_feedbacks(tenant_id, merchant_id, training_id, status);

        """
    )
    _ensure_column(conn, "knowledge_documents", "category_id", "INTEGER")
    _ensure_column(conn, "knowledge_documents", "category_key", "TEXT")
    _ensure_column(conn, "knowledge_documents", "metadata_json", "TEXT")
    _ensure_column(conn, "knowledge_chunks", "category_id", "INTEGER")
    _ensure_column(conn, "knowledge_chunks", "category_key", "TEXT")
    _ensure_column(conn, "rag_training_runs", "document_id", "INTEGER")
    _ensure_column(conn, "knowledge_training_feedbacks", "corrected_answer", "TEXT")
    _ensure_column(conn, "knowledge_training_feedbacks", "auto_ingest", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "knowledge_training_feedbacks", "ingestion_status", "TEXT")
    _ensure_column(conn, "knowledge_training_feedbacks", "ingested_document_id", "INTEGER")
    _ensure_column(conn, "knowledge_training_feedbacks", "ingestion_training_run_id", "INTEGER")
    _ensure_column(conn, "knowledge_training_feedbacks", "ingestion_error", "TEXT")
    _ensure_column(conn, "knowledge_training_feedbacks", "answer_hash", "TEXT")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_category
        ON knowledge_documents(tenant_id, merchant_id, category_id, category_key, is_active);

        CREATE INDEX IF NOT EXISTS idx_chunks_category
        ON knowledge_chunks(tenant_id, merchant_id, category_id, category_key, is_active);

        CREATE INDEX IF NOT EXISTS idx_knowledge_training_feedbacks_ingestion
        ON knowledge_training_feedbacks(tenant_id, merchant_id, training_id, answer_hash, ingestion_status);
        """
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
