"""9100 RAG metadata alembic 0002 schema 结构测试（纯文本解析，不依赖真实 PG）。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XG_VERSIONS = ROOT / "migrations" / "postgres" / "xg_douyin_ai_cs" / "versions"
REVISION = XG_VERSIONS / "0002_create_rag_metadata.py"

TARGET_TABLES = {
    "knowledge_categories",
    "knowledge_documents",
    "knowledge_chunks",
    "rag_training_runs",
    "llm_call_logs",
    "knowledge_training_sessions",
    "knowledge_training_feedbacks",
}


def _read(path: Path = REVISION) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_id_and_down_revision_are_correct():
    content = _read()
    assert 'revision = "0002_create_rag_metadata"' in content
    assert 'down_revision = "0001_empty_baseline"' in content
    assert len("0002_create_rag_metadata") <= 32


def test_revision_creates_only_rag_metadata_tables():
    content = _read()
    assert content.count("op.create_table(") == len(TARGET_TABLES)
    for table in TARGET_TABLES:
        assert re.search(rf'op\.create_table\(\s*"{table}"', content)


def test_core_rag_columns_exist():
    content = _read()
    required_columns = {
        "knowledge_categories": [
            '"tenant_id"', '"merchant_id"', '"category_key"', '"scope_type"',
            '"is_base"', '"is_active"', '"sort_order"',
        ],
        "knowledge_documents": [
            '"douyin_account_id"', '"content"', '"source_type"',
            '"category_id"', '"category_key"', '"metadata_json"', '"is_active"',
        ],
        "knowledge_chunks": [
            '"document_id"', '"chunk_text"', '"chunk_index"',
            '"embedding_json"', '"embedding_model"', '"content_hash"', '"is_active"',
        ],
        "rag_training_runs": [
            '"status"', '"document_count"', '"chunk_count"',
            '"document_id"', '"finished_at"',
        ],
        "llm_call_logs": [
            '"conversation_id"', '"model"', '"status"', '"elapsed_ms"',
        ],
        "knowledge_training_sessions": [
            '"training_id"', '"question"', '"answer"', '"used_knowledge_base"',
        ],
        "knowledge_training_feedbacks": [
            '"rating"', '"status"', '"corrected_answer"', '"auto_ingest"',
            '"ingestion_status"', '"ingested_document_id"', '"answer_hash"',
        ],
    }
    for table, columns in required_columns.items():
        match = re.search(rf'op\.create_table\(\s*"{table}"', content)
        assert match is not None
        table_pos = match.start()
        next_table_pos = content.find("op.create_table(", table_pos + 1)
        segment = content[table_pos:] if next_table_pos == -1 else content[table_pos:next_table_pos]
        for column in columns:
            assert column in segment


def test_key_indexes_constraints_and_checks_exist():
    content = _read()
    required_names = [
        "uk_categories_system_key",
        "uk_categories_merchant_key",
        "idx_categories_visible",
        "idx_documents_scope",
        "idx_documents_category",
        "idx_chunks_scope",
        "idx_chunks_category",
        "uk_knowledge_chunks_document_hash",
        "idx_knowledge_training_feedbacks_scope",
        "idx_knowledge_training_feedbacks_ingestion",
        "ck_knowledge_categories_scope_type",
        "ck_knowledge_categories_scope_merchant",
        "ck_knowledge_training_feedbacks_rating",
        "ck_knowledge_training_feedbacks_status",
    ]
    for name in required_names:
        assert name in content


def test_revision_uses_postgresql_safe_types():
    content = _read()
    assert "sa.BigInteger()" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "sa.Boolean()" in content
    assert "server_default=sa.text(\"now()\")" in content


def test_embedding_json_uses_text_not_jsonb():
    """用户决定 embedding_json / metadata_json 用 TEXT 直平移（非 JSONB）。"""
    content = _read()
    assert "postgresql.JSONB" not in content
    assert '"embedding_json", sa.Text()' in content
    assert '"metadata_json", sa.Text()' in content


def test_revision_has_no_sqlite_specific_syntax():
    lowered = _read().lower()
    forbidden = [
        "sqlite",
        "if not exists",
        "sqlite_autoincrement",
        "datetime('now')",
        "pragma",
        "insert or ",
    ]
    for item in forbidden:
        assert item not in lowered


def test_revision_does_not_contain_real_secrets():
    content = _read()
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "postgresql://",
        "postgresql+asyncpg://",
        "password=",
        "token=",
    ]
    for item in forbidden:
        assert item not in content


def test_downgrade_drops_all_tables_in_reverse_order():
    content = _read()
    downgrade = content.split("def downgrade() -> None:", 1)[1]
    expected_order = [
        "knowledge_training_feedbacks",
        "knowledge_training_sessions",
        "llm_call_logs",
        "rag_training_runs",
        "knowledge_chunks",
        "knowledge_documents",
        "knowledge_categories",
    ]
    positions = [downgrade.index(f'op.drop_table("{table}")') for table in expected_order]
    assert positions == sorted(positions)
