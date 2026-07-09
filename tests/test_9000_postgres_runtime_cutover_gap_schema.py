import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
REVISION = AUTO_WECHAT_VERSIONS / "0006_create_runtime_cutover_gap_tables.py"

TARGET_TABLES = {
    "external_merchant_bindings",
    "reply_checks",
    "check_configs",
    "lead_notifications",
    "lead_followup_records",
    "feedback_records",
    "douyin_oauth_states",
    "douyin_account_autoreply_settings",
    "conversation_autopilot_states",
    "douyin_conversation_read_states",
    "douyin_private_message_sends",
    "ai_reply_decision_logs",
    "ai_auto_reply_runs",
    "douyin_message_resource_downloads",
    "douyin_image_uploads",
    "autoreply_rollout_configs",
    "autoreply_whitelist_entries",
    "autoreply_admin_audit_logs",
    "compute_packages",
}


def _read(path: Path = REVISION) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_id_and_down_revision_are_correct():
    content = _read()

    assert 'revision = "0006_runtime_cutover_gap"' in content
    assert 'down_revision = "0005_compute_core"' in content
    assert len("0006_runtime_cutover_gap") <= 32


def test_revision_creates_only_runtime_gap_tables():
    content = _read()

    assert content.count("op.create_table(") == len(TARGET_TABLES)
    for table in TARGET_TABLES:
        assert re.search(rf'op\.create_table\(\s*"{table}"', content)

    already_covered_tables = {
        "knowledge_categories",
        "sales_staff",
        "douyin_leads",
        "douyin_webhook_events",
        "wechat_tasks",
        "ai_agents",
        "douyin_authorized_accounts",
        "douyin_account_agent_bindings",
        "agent_knowledge_categories",
        "compute_accounts",
        "compute_transactions",
    }
    for table in already_covered_tables:
        assert not re.search(rf'op\.create_table\(\s*"{table}"', content)


def test_core_cutover_columns_exist():
    content = _read()

    required_columns = {
        "external_merchant_bindings": [
            '"source_system"',
            '"external_user_id"',
            '"external_account"',
            '"merchant_id"',
            '"status"',
        ],
        "reply_checks": [
            '"lead_id"',
            '"staff_id"',
            '"reply_deadline"',
            '"check_status"',
            '"is_effective"',
        ],
        "lead_notifications": [
            '"lead_id"',
            '"staff_id"',
            '"check_id"',
            '"send_status"',
            '"send_mode"',
        ],
        "douyin_private_message_sends": [
            '"conversation_short_id"',
            '"server_message_id"',
            '"manual_confirmed"',
            '"auto_send"',
            '"auto_reply_run_id"',
            '"send_source"',
        ],
        "ai_auto_reply_runs": [
            '"trigger_event_key"',
            '"mode"',
            '"status"',
            '"decision_log_id"',
        ],
        "compute_packages": [
            '"name"',
            '"price_yuan"',
            '"token_amount"',
            '"enabled"',
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
        "idx_external_merchant_bindings_user",
        "idx_external_merchant_bindings_account",
        "idx_external_merchant_bindings_merchant",
        "ck_external_merchant_bindings_status",
        "ck_external_merchant_bindings_has_external_identity",
        "idx_reply_checks_lead_status_created",
        "idx_reply_checks_staff_status_created",
        "uk_check_configs_config_key",
        "idx_lead_notifications_lead_created",
        "idx_lead_notifications_staff_status_created",
        "idx_lead_followup_records_lead_created",
        "uk_douyin_oauth_states_state",
        "uk_douyin_autoreply_settings_merchant_account",
        "uk_conversation_autopilot_states_scope",
        "uk_dy_conversation_read_states_scope",
        "uk_douyin_private_message_sends_auto_reply_run",
        "idx_ai_reply_decision_logs_merchant_created",
        "uk_ai_auto_reply_runs_trigger_event_key",
        "idx_douyin_message_resource_downloads_message_ids",
        "idx_douyin_image_uploads_main_status_created",
        "uk_autoreply_rollout_configs_scope_merchant",
        "uk_autoreply_whitelist_entries_scope_value",
        "idx_autoreply_admin_audit_logs_action_created",
        "ck_compute_packages_token_amount_positive",
    ]
    for name in required_names:
        assert name in content


def test_revision_uses_postgresql_safe_types():
    content = _read()

    assert "sa.BigInteger()" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "sa.Boolean()" in content
    assert "postgresql.JSONB" in content
    assert "server_default=sa.text(\"now()\")" in content


def test_downgrade_drops_all_batch_tables_in_reverse_order():
    content = _read()
    downgrade = content.split("def downgrade() -> None:", 1)[1]

    expected_order = [
        "compute_packages",
        "autoreply_admin_audit_logs",
        "autoreply_whitelist_entries",
        "autoreply_rollout_configs",
        "douyin_image_uploads",
        "douyin_message_resource_downloads",
        "ai_auto_reply_runs",
        "ai_reply_decision_logs",
        "douyin_private_message_sends",
        "douyin_conversation_read_states",
        "conversation_autopilot_states",
        "douyin_account_autoreply_settings",
        "douyin_oauth_states",
        "feedback_records",
        "lead_followup_records",
        "lead_notifications",
        "check_configs",
        "reply_checks",
        "external_merchant_bindings",
    ]
    positions = [downgrade.index(f'op.drop_table("{table}")') for table in expected_order]
    assert positions == sorted(positions)


def test_revision_has_no_sqlite_specific_syntax_or_if_not_exists():
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


def test_revision_does_not_contain_real_secrets_or_fixed_database_uri():
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
