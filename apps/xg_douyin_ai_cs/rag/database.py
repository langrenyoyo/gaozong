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


# 模块级 engine 单例：按当前 rag_database_url 缓存，url 变化时重建。
# settings.rag_database_url 是动态 property（每次读环境变量），单例需感知 url 变化
# 才能支持测试隔离（每个测试 setenv 不同 tmp_path）。生产环境 url 不变，单例稳定。
_rag_engine = None
_rag_engine_url = None


def get_rag_engine():
    """返回 9100 RAG metadata engine 单例（按当前 rag_database_url 缓存，url 变化时重建）。

    P3-D3：repository 与 knowledge_training_service 共用此单例。PG 生产 / SQLite dev
    兜底由 create_rag_engine 按当前 backend 决定。SQLite 路径建表（init_db）对齐原 connect。
    """
    global _rag_engine, _rag_engine_url
    current_url = settings.rag_database_url
    if _rag_engine is None or _rag_engine_url != current_url:
        if _rag_engine is not None:
            _rag_engine.dispose()
        _rag_engine = create_rag_engine(current_url)
        _rag_engine_url = current_url
    return _rag_engine


def create_rag_engine(database_url: str | None = None):
    """创建 9100 RAG metadata SQLAlchemy engine（每次返回新实例）。

    P3-D2：PG backend 使用同步 psycopg + 连接池（对齐 9000），供 alembic / smoke / 测试
    使用。SQLite backend 保留 dev 兜底。业务路径请走 get_rag_engine() 单例，避免连接池膨胀。
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
    engine = create_engine(
        runtime.raw_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    # SQLite 模式建表，对齐原 connect() 的 init_db（PG 路径表由 alembic 管）。
    # 用原生 sqlite3.connect 建表（设 row_factory 让 init_db 的 PRAGMA row["name"] 可用），
    # file-based 下 engine 连接池后续读到同一文件；:memory: 跳过（engine 独立内存库）
    sqlite_path = runtime.sqlite_path
    if sqlite_path:
        path = Path(sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(path))
        raw.row_factory = sqlite3.Row
        init_db(raw)
        raw.close()
    return engine


def connect(database_url: str | None = None) -> sqlite3.Connection:
    runtime = get_database_runtime(database_url)
    if runtime.backend == "postgresql":
        raise RuntimeError(
            "PostgreSQL backend 已识别，connect() 是 SQLite 专属 dev 兜底（PRAGMA / init_db），"
            "PG 不可用；9100 业务路径（repository / knowledge_training_service）走 get_rag_engine()"
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
