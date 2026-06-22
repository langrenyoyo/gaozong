"""SQLite database bootstrap for the 9100 RAG MVP."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.xg_douyin_ai_cs.config import settings


def database_path() -> Path:
    return settings.rag_db_path


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn)
    return conn


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
    _ensure_column(conn, "knowledge_chunks", "category_id", "INTEGER")
    _ensure_column(conn, "knowledge_chunks", "category_key", "TEXT")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_category
        ON knowledge_documents(tenant_id, merchant_id, category_id, category_key, is_active);

        CREATE INDEX IF NOT EXISTS idx_chunks_category
        ON knowledge_chunks(tenant_id, merchant_id, category_id, category_key, is_active);
        """
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
