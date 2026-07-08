from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
REVISION = AUTO_WECHAT_VERSIONS / "0003_create_leads_tasks_core_tables.py"

TARGET_TABLES = {
    "douyin_leads",
    "douyin_webhook_events",
    "sales_staff",
    "wechat_tasks",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_id_and_down_revision_are_correct():
    content = _read(REVISION)

    assert 'revision = "0003_leads_tasks_core"' in content
    assert 'down_revision = "0002_create_knowledge_categories"' in content


def test_revision_creates_only_leads_tasks_core_tables():
    content = _read(REVISION)

    assert content.count("op.create_table(") == 4
    for table in TARGET_TABLES:
        assert f'"{table}"' in content

    forbidden_tables = {
        "knowledge_categories",
        "reply_checks",
        "lead_notifications",
        "lead_followup_records",
        "ai_agents",
        "compute_accounts",
        "compute_transactions",
        "douyin_authorized_accounts",
        "agent_knowledge_categories",
    }
    for table in forbidden_tables:
        assert f'op.create_table("{table}"' not in content


def test_revision_uses_postgresql_types():
    content = _read(REVISION)

    assert content.count("sa.BigInteger()") >= 4
    assert "autoincrement=True" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "postgresql.JSONB" in content
    assert "sa.Boolean()" in content
    assert "sa.Integer()" in content


def test_douyin_leads_columns_indexes_and_unique_constraint():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"source"',
        '"lead_type"',
        '"customer_name"',
        '"customer_contact"',
        '"content"',
        '"source_url"',
        '"source_id"',
        '"tenant_id"',
        '"merchant_id"',
        '"account_open_id"',
        '"conversation_short_id"',
        '"assigned_staff_id"',
        '"assigned_at"',
        '"status"',
        '"raw_data"',
        '"raw_message_text"',
        '"extracted_phone"',
        '"extracted_wechat"',
        '"all_extracted_contacts"',
        '"contact_extract_status"',
        '"contact_extract_reason"',
        '"reassign_count"',
        '"customer_id"',
        '"external_customer_id"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "uk_douyin_leads_account_conv" in content
    assert '"account_open_id", "conversation_short_id"' in content
    assert "idx_douyin_leads_merchant_updated" in content
    assert "idx_douyin_leads_merchant_status_updated" in content
    assert "idx_douyin_leads_merchant_account_conversation" in content
    assert "idx_douyin_leads_assigned_staff_status" in content


def test_douyin_webhook_events_columns_indexes_and_unique_constraint():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"tenant_id"',
        '"merchant_id"',
        '"event"',
        '"event_key"',
        '"from_user_id"',
        '"to_user_id"',
        '"client_key"',
        '"conversation_short_id"',
        '"server_message_id"',
        '"conversation_type"',
        '"message_type"',
        '"message_create_time"',
        '"message_source"',
        '"parse_status"',
        '"parsed_content_json"',
        '"is_duplicate"',
        '"lead_id"',
        '"raw_body"',
        '"created_at"',
    ]:
        assert column in content

    assert "uk_douyin_webhook_events_event_key" in content
    assert "idx_douyin_webhook_events_merchant_created" in content
    assert "idx_douyin_webhook_events_event_created" in content
    assert "idx_douyin_webhook_events_account_conversation" in content
    assert "idx_douyin_webhook_events_open_id_created" in content


def test_sales_staff_columns_and_indexes():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"tenant_id"',
        '"merchant_id"',
        '"name"',
        '"wechat_id"',
        '"wechat_nickname"',
        '"phone"',
        '"status"',
        '"sort_order"',
        '"remark"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "idx_sales_staff_merchant_status" in content
    assert "idx_sales_staff_merchant_wechat_nickname" in content
    assert "idx_sales_staff_merchant_wechat_id" in content


def test_wechat_tasks_columns_indexes_and_no_fake_idempotency_key():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"tenant_id"',
        '"merchant_id"',
        '"task_type"',
        '"lead_id"',
        '"staff_id"',
        '"reply_check_id"',
        '"target_nickname"',
        '"message"',
        '"mode"',
        '"status"',
        '"failure_stage"',
        '"raw_result"',
        '"agent_hostname"',
        '"agent_pid"',
        '"pasted_at"',
        '"sent_at"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "idx_wechat_tasks_merchant_status_created" in content
    assert "idx_wechat_tasks_type_status_created" in content
    assert "idx_wechat_tasks_lead_type" in content
    assert "idx_wechat_tasks_staff_status" in content
    assert "idempotency_key" not in content
    assert "external_key" not in content


def test_downgrade_drops_only_batch_tables_in_dependency_order():
    content = _read(REVISION)
    downgrade = content.split("def downgrade() -> None:", 1)[1]

    for table in ["wechat_tasks", "douyin_webhook_events", "douyin_leads", "sales_staff"]:
        assert f'op.drop_table("{table}")' in downgrade

    assert 'op.drop_table("knowledge_categories")' not in downgrade


def test_revision_has_no_sqlite_specific_syntax_or_if_not_exists():
    lowered = _read(REVISION).lower()

    forbidden = [
        "sqlite",
        "if not exists",
        "sqlite_autoincrement",
        "datetime('now')",
        "json_extract",
        "pragma",
    ]
    for item in forbidden:
        assert item not in lowered


def test_revision_does_not_contain_real_secrets_or_fixed_database_uri():
    content = _read(REVISION)
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "postgresql://",
        "postgresql+asyncpg://",
        "mysql://",
        "mongodb://",
        "password=",
        "token=",
    ]
    for item in forbidden:
        assert item not in content
