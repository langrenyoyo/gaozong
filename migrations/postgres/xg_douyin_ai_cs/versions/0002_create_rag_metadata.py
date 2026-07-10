"""9100 xg_douyin_ai_cs RAG metadata PostgreSQL schema。

P3-D：建立 9100 RAG / AI 客服 metadata 8 张业务表，直平移自原 init_db
（rag/database.py:60-217），embedding_json / metadata_json 用 TEXT（最小改动，
用户决定不引入 JSONB）。Milvus 仍是向量检索副本，本 schema 是 metadata 真源。

注意：本 revision 只建 PG schema，不触碰 repository 与 Milvus 逻辑。repository
仍是原生 metadata DB 专属写法，P3-D3 改写前 9100 业务路径在 PG 下不可用；
本 schema 供 alembic / smoke / 后续改写使用。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_create_rag_metadata"
down_revision = "0001_empty_baseline"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # knowledge_categories：知识分类，system / merchant 双 scope
    op.create_table(
        "knowledge_categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("category_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint("scope_type IN ('system', 'merchant')", name="ck_knowledge_categories_scope_type"),
        sa.CheckConstraint(
            "(scope_type = 'system' AND merchant_id IS NULL) OR "
            "(scope_type = 'merchant' AND merchant_id IS NOT NULL)",
            name="ck_knowledge_categories_scope_merchant",
        ),
    )
    op.create_index(
        "uk_categories_system_key",
        "knowledge_categories",
        ["tenant_id", "category_key", "scope_type"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'system'"),
    )
    op.create_index(
        "uk_categories_merchant_key",
        "knowledge_categories",
        ["tenant_id", "merchant_id", "category_key", "scope_type"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'merchant'"),
    )
    op.create_index(
        "idx_categories_visible",
        "knowledge_categories",
        ["tenant_id", "merchant_id", "scope_type", "is_active", "sort_order"],
    )

    # knowledge_documents：知识文档 metadata（Milvus 仅是向量副本）
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("douyin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("category_key", sa.String(length=128), nullable=True),
        sa.Column("brand", sa.String(length=128), nullable=True),
        sa.Column("vehicle_name", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        _updated_at_column(),
    )
    op.create_index(
        "idx_documents_scope",
        "knowledge_documents",
        ["tenant_id", "merchant_id", "douyin_account_id", "is_active"],
    )
    op.create_index(
        "idx_documents_category",
        "knowledge_documents",
        ["tenant_id", "merchant_id", "category_id", "category_key", "is_active"],
    )

    # knowledge_chunks：知识分块，原始 embedding 存 embedding_json（TEXT），Milvus 是检索副本
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("douyin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("category_key", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("document_id", "content_hash", name="uk_knowledge_chunks_document_hash"),
    )
    op.create_index(
        "idx_chunks_scope",
        "knowledge_chunks",
        ["tenant_id", "merchant_id", "douyin_account_id", "is_active"],
    )
    op.create_index(
        "idx_chunks_category",
        "knowledge_chunks",
        ["tenant_id", "merchant_id", "category_id", "category_key", "is_active"],
    )

    # rag_training_runs：训练 run 记录
    op.create_table(
        "rag_training_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("douyin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # llm_call_logs：LLM 调用日志
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        _created_at_column(),
    )

    # knowledge_training_sessions：训练会话（training_id 业务生成，非自增主键）
    op.create_table(
        "knowledge_training_sessions",
        sa.Column("training_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("douyin_account_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("used_knowledge_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False),
        _created_at_column(),
    )

    # knowledge_training_feedbacks：训练反馈 + 自动摄入追踪（含增量字段）
    op.create_table(
        "knowledge_training_feedbacks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("training_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        _created_at_column(),
        sa.Column("corrected_answer", sa.Text(), nullable=True),
        sa.Column("auto_ingest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ingestion_status", sa.String(length=32), nullable=True),
        sa.Column("ingested_document_id", sa.BigInteger(), nullable=True),
        sa.Column("ingestion_training_run_id", sa.BigInteger(), nullable=True),
        sa.Column("ingestion_error", sa.Text(), nullable=True),
        sa.Column("answer_hash", sa.String(length=128), nullable=True),
        sa.CheckConstraint("rating IN ('useful', 'normal', 'wrong')", name="ck_knowledge_training_feedbacks_rating"),
        sa.CheckConstraint("status IN ('submitted', 'pending_review')", name="ck_knowledge_training_feedbacks_status"),
    )
    op.create_index(
        "idx_knowledge_training_feedbacks_scope",
        "knowledge_training_feedbacks",
        ["tenant_id", "merchant_id", "training_id", "status"],
    )
    op.create_index(
        "idx_knowledge_training_feedbacks_ingestion",
        "knowledge_training_feedbacks",
        ["tenant_id", "merchant_id", "training_id", "answer_hash", "ingestion_status"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_training_feedbacks")
    op.drop_table("knowledge_training_sessions")
    op.drop_table("llm_call_logs")
    op.drop_table("rag_training_runs")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_categories")
