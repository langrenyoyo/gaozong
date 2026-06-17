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
        CREATE TABLE IF NOT EXISTS knowledge_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          merchant_id TEXT NOT NULL,
          douyin_account_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT 'manual',
          category TEXT,
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

        CREATE INDEX IF NOT EXISTS idx_documents_scope
        ON knowledge_documents(tenant_id, merchant_id, douyin_account_id, is_active);

        CREATE INDEX IF NOT EXISTS idx_chunks_scope
        ON knowledge_chunks(tenant_id, merchant_id, douyin_account_id, is_active);
        """
    )
    conn.commit()
