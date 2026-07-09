"""补齐 9000 PostgreSQL cutover runtime 缺失表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_runtime_cutover_gap"
down_revision = "0005_compute_core"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.create_table(
        "external_merchant_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("external_user_id", sa.String(length=128), nullable=True),
        sa.Column("external_account", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'deleted')",
            name="ck_external_merchant_bindings_status",
        ),
        sa.CheckConstraint(
            "coalesce(external_user_id, '') <> '' OR coalesce(external_account, '') <> ''",
            name="ck_external_merchant_bindings_has_external_identity",
        ),
    )
    op.create_index(
        "idx_external_merchant_bindings_user",
        "external_merchant_bindings",
        ["source_system", "external_user_id"],
    )
    op.create_index(
        "idx_external_merchant_bindings_account",
        "external_merchant_bindings",
        ["source_system", "external_account"],
    )
    op.create_index("idx_external_merchant_bindings_merchant", "external_merchant_bindings", ["merchant_id"])

    op.create_table(
        "reply_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=False),
        sa.Column("reply_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_content", sa.Text(), nullable=True),
        sa.Column("is_effective", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effectiveness_reason", sa.String(length=200), nullable=True),
        sa.Column("check_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_reply_checks_lead_status_created", "reply_checks", ["lead_id", "check_status", "created_at"])
    op.create_index("idx_reply_checks_staff_status_created", "reply_checks", ["staff_id", "check_status", "created_at"])
    op.create_index("idx_reply_checks_deadline_status", "reply_checks", ["reply_deadline", "check_status"])

    op.create_table(
        "check_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("config_key", sa.String(length=100), nullable=False),
        sa.Column("config_value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("config_key", name="uk_check_configs_config_key"),
    )

    op.create_table(
        "lead_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=False),
        sa.Column("check_id", sa.BigInteger(), sa.ForeignKey("reply_checks.id"), nullable=True),
        sa.Column("notification_text", sa.Text(), nullable=True),
        sa.Column("template_name", sa.String(length=50), nullable=True, server_default="default"),
        sa.Column("send_status", sa.String(length=20), nullable=True, server_default="composed"),
        sa.Column("send_mode", sa.String(length=20), nullable=True, server_default="auto_send"),
        sa.Column("chat_title", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_lead_notifications_lead_created", "lead_notifications", ["lead_id", "created_at"])
    op.create_index(
        "idx_lead_notifications_staff_status_created",
        "lead_notifications",
        ["staff_id", "send_status", "created_at"],
    )
    op.create_index("idx_lead_notifications_check", "lead_notifications", ["check_id"])

    op.create_table(
        "lead_followup_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=True),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(length=128), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_lead_followup_records_lead_created", "lead_followup_records", ["lead_id", "created_at"])
    op.create_index("idx_lead_followup_records_staff_created", "lead_followup_records", ["staff_id", "created_at"])

    op.create_table(
        "feedback_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=False),
        sa.Column("check_id", sa.BigInteger(), sa.ForeignKey("reply_checks.id"), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("feedback_status", sa.String(length=20), nullable=True, server_default="composed"),
        sa.Column("send_mode", sa.String(length=20), nullable=True),
        sa.Column("chat_title", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_feedback_records_lead_created", "feedback_records", ["lead_id", "created_at"])
    op.create_index("idx_feedback_records_staff_status_created", "feedback_records", ["staff_id", "feedback_status", "created_at"])
    op.create_index("idx_feedback_records_check", "feedback_records", ["check_id"])

    op.create_table(
        "douyin_oauth_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False, server_default="new_car_project"),
        sa.Column("redirect_target", sa.String(length=1000), nullable=True),
        _created_at_column(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("state", name="uk_douyin_oauth_states_state"),
    )
    op.create_index("idx_douyin_oauth_states_merchant", "douyin_oauth_states", ["merchant_id"])
    op.create_index("idx_douyin_oauth_states_expires_at", "douyin_oauth_states", ["expires_at"])

    op.create_table(
        "douyin_account_autoreply_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dry_run_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("send_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("require_rag", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("require_rag_sources", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allowed_intents_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("blocked_risk_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("direct_llm_policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("customer_whitelist_open_ids", sa.Text(), nullable=True),
        sa.Column("conversation_whitelist_ids", sa.Text(), nullable=True),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_auto_replies_per_conversation_per_day", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("max_replies_per_conversation_per_hour", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("max_replies_per_account_per_hour", sa.Integer(), nullable=False, server_default="300"),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("merchant_id", "account_open_id", name="uk_douyin_autoreply_settings_merchant_account"),
    )
    op.create_index("idx_douyin_autoreply_settings_account", "douyin_account_autoreply_settings", ["account_open_id"])
    op.create_index(
        "idx_douyin_autoreply_settings_switches",
        "douyin_account_autoreply_settings",
        ["enabled", "dry_run_enabled", "send_enabled"],
    )

    op.create_table(
        "conversation_autopilot_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=False),
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="ai"),
        sa.Column("manual_takeover_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_human_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ai_reply_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint(
            "merchant_id",
            "account_open_id",
            "conversation_short_id",
            name="uk_conversation_autopilot_states_scope",
        ),
    )
    op.create_index(
        "idx_conversation_autopilot_states_merchant_account",
        "conversation_autopilot_states",
        ["merchant_id", "account_open_id"],
    )
    op.create_index("idx_conversation_autopilot_states_mode", "conversation_autopilot_states", ["mode"])
    op.create_index(
        "idx_conversation_autopilot_states_takeover_until",
        "conversation_autopilot_states",
        ["manual_takeover_until"],
    )

    op.create_table(
        "douyin_conversation_read_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_key", sa.String(length=255), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_read_event_id", sa.BigInteger(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint(
            "merchant_id",
            "account_open_id",
            "conversation_key",
            name="uk_dy_conversation_read_states_scope",
        ),
    )
    op.create_index(
        "idx_dy_conversation_read_states_merchant_account",
        "douyin_conversation_read_states",
        ["merchant_id", "account_open_id"],
    )
    op.create_index("idx_dy_conversation_read_states_customer", "douyin_conversation_read_states", ["customer_open_id"])

    op.create_table(
        "douyin_private_message_sends",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("main_account_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=False),
        sa.Column("server_message_id", sa.String(length=255), nullable=False),
        sa.Column("from_user_id", sa.String(length=255), nullable=False),
        sa.Column("to_user_id", sa.String(length=255), nullable=False),
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
        sa.Column("scene", sa.String(length=64), nullable=False, server_default="im_reply_msg"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("request_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("upstream_msg_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("manual_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_send", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decision_log_id", sa.BigInteger(), nullable=True),
        sa.Column("auto_reply_run_id", sa.BigInteger(), nullable=True),
        sa.Column("send_source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("operator_id", sa.String(length=255), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("auto_reply_run_id", name="uk_douyin_private_message_sends_auto_reply_run"),
    )
    op.create_index("idx_douyin_private_message_sends_conversation", "douyin_private_message_sends", ["conversation_short_id"])
    op.create_index("idx_douyin_private_message_sends_server_message", "douyin_private_message_sends", ["server_message_id"])
    op.create_index("idx_douyin_private_message_sends_decision_log", "douyin_private_message_sends", ["decision_log_id"])
    op.create_index("idx_douyin_private_message_sends_send_source", "douyin_private_message_sends", ["send_source"])
    op.create_index(
        "idx_douyin_private_message_sends_account_created",
        "douyin_private_message_sends",
        ["account_open_id", "created_at"],
    )

    op.create_table(
        "ai_reply_decision_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
        sa.Column("open_id", sa.String(length=255), nullable=True),
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("agent_name", sa.String(length=100), nullable=True),
        sa.Column("latest_message", sa.Text(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("lead_level", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("manual_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("manual_required_reason", sa.Text(), nullable=True),
        sa.Column("risk_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rag_sources_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_chunks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("allowed_category_keys_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rag_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("upstream_auto_send", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("final_auto_send", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decision_version", sa.String(length=64), nullable=True),
        sa.Column("raw_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_ai_reply_decision_logs_merchant_created", "ai_reply_decision_logs", ["merchant_id", "created_at"])
    op.create_index("idx_ai_reply_decision_logs_account_created", "ai_reply_decision_logs", ["account_open_id", "created_at"])
    op.create_index(
        "idx_ai_reply_decision_logs_conversation_created",
        "ai_reply_decision_logs",
        ["conversation_id", "created_at"],
    )
    op.create_index("idx_ai_reply_decision_logs_agent_created", "ai_reply_decision_logs", ["agent_id", "created_at"])
    op.create_index("idx_ai_reply_decision_logs_manual_created", "ai_reply_decision_logs", ["manual_required", "created_at"])

    op.create_table(
        "ai_auto_reply_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
        sa.Column("trigger_event_id", sa.BigInteger(), sa.ForeignKey("douyin_webhook_events.id"), nullable=False),
        sa.Column("trigger_event_key", sa.String(length=255), nullable=False),
        sa.Column("trigger_server_message_id", sa.String(length=255), nullable=True),
        sa.Column("latest_message", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="dry_run"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=128), nullable=True),
        sa.Column("block_reason", sa.String(length=128), nullable=True),
        sa.Column("gate_results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision_log_id", sa.BigInteger(), nullable=True),
        sa.Column("would_send_content", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("trigger_event_key", name="uk_ai_auto_reply_runs_trigger_event_key"),
    )
    op.create_index("idx_ai_auto_reply_runs_merchant", "ai_auto_reply_runs", ["merchant_id"])
    op.create_index("idx_ai_auto_reply_runs_account", "ai_auto_reply_runs", ["account_open_id"])
    op.create_index("idx_ai_auto_reply_runs_conversation", "ai_auto_reply_runs", ["conversation_short_id"])
    op.create_index("idx_ai_auto_reply_runs_customer", "ai_auto_reply_runs", ["customer_open_id"])
    op.create_index("idx_ai_auto_reply_runs_trigger_event", "ai_auto_reply_runs", ["trigger_event_id"])
    op.create_index("idx_ai_auto_reply_runs_agent", "ai_auto_reply_runs", ["agent_id"])
    op.create_index("idx_ai_auto_reply_runs_decision_log", "ai_auto_reply_runs", ["decision_log_id"])
    op.create_index("idx_ai_auto_reply_runs_created", "ai_auto_reply_runs", ["created_at"])

    op.create_table(
        "douyin_message_resource_downloads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("webhook_event_id", sa.BigInteger(), sa.ForeignKey("douyin_webhook_events.id"), nullable=True),
        sa.Column("main_account_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=False),
        sa.Column("server_message_id", sa.String(length=255), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=True),
        sa.Column("resource_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("upstream_err_no", sa.String(length=64), nullable=True),
        sa.Column("upstream_err_msg", sa.String(length=500), nullable=True),
        sa.Column("upstream_log_id", sa.String(length=255), nullable=True),
        sa.Column("request_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_douyin_message_resource_downloads_message_ids",
        "douyin_message_resource_downloads",
        ["conversation_short_id", "server_message_id"],
    )
    op.create_index(
        "idx_douyin_message_resource_downloads_status_created",
        "douyin_message_resource_downloads",
        ["resource_status", "created_at"],
    )

    op.create_table(
        "douyin_image_uploads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("main_account_id", sa.BigInteger(), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_ext", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_md5", sa.String(length=64), nullable=False),
        sa.Column("image_base64_sha256", sa.String(length=64), nullable=False),
        sa.Column("upstream_image_id", sa.String(length=255), nullable=True),
        sa.Column("upstream_width", sa.Integer(), nullable=True),
        sa.Column("upstream_height", sa.Integer(), nullable=True),
        sa.Column("upstream_md5", sa.String(length=255), nullable=True),
        sa.Column("upload_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("upstream_code", sa.String(length=64), nullable=True),
        sa.Column("upstream_msg", sa.String(length=500), nullable=True),
        sa.Column("request_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_douyin_image_uploads_main_status_created",
        "douyin_image_uploads",
        ["main_account_id", "upload_status", "created_at"],
    )
    op.create_index("idx_douyin_image_uploads_open_created", "douyin_image_uploads", ["open_id", "created_at"])
    op.create_index("idx_douyin_image_uploads_hash", "douyin_image_uploads", ["image_base64_sha256"])

    op.create_table(
        "autoreply_rollout_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="global"),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("auto_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("real_send_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allow_full_rollout", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("scope", "merchant_id", name="uk_autoreply_rollout_configs_scope_merchant"),
    )
    op.create_index("idx_autoreply_rollout_configs_merchant", "autoreply_rollout_configs", ["merchant_id"])

    op.create_table(
        "autoreply_whitelist_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        _created_at_column(),
        sa.Column("disabled_by", sa.String(length=128), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "entry_type",
            "merchant_id",
            "account_open_id",
            "value",
            name="uk_autoreply_whitelist_entries_scope_value",
        ),
    )
    op.create_index(
        "idx_autoreply_whitelist_entries_merchant_type",
        "autoreply_whitelist_entries",
        ["merchant_id", "entry_type", "enabled"],
    )
    op.create_index("idx_autoreply_whitelist_entries_account", "autoreply_whitelist_entries", ["account_open_id", "enabled"])

    op.create_table(
        "autoreply_admin_audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(length=128), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        _created_at_column(),
    )
    op.create_index(
        "idx_autoreply_admin_audit_logs_merchant_created",
        "autoreply_admin_audit_logs",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "idx_autoreply_admin_audit_logs_action_created",
        "autoreply_admin_audit_logs",
        ["action", "created_at"],
    )
    op.create_index(
        "idx_autoreply_admin_audit_logs_account_created",
        "autoreply_admin_audit_logs",
        ["account_open_id", "created_at"],
    )

    op.create_table(
        "compute_packages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("price_yuan", sa.Integer(), nullable=False),
        sa.Column("token_amount", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint("price_yuan >= 0", name="ck_compute_packages_price_nonnegative"),
        sa.CheckConstraint("token_amount > 0", name="ck_compute_packages_token_amount_positive"),
    )
    op.create_index("idx_compute_packages_enabled_price", "compute_packages", ["enabled", "price_yuan"])


def downgrade() -> None:
    op.drop_table("compute_packages")
    op.drop_table("autoreply_admin_audit_logs")
    op.drop_table("autoreply_whitelist_entries")
    op.drop_table("autoreply_rollout_configs")
    op.drop_table("douyin_image_uploads")
    op.drop_table("douyin_message_resource_downloads")
    op.drop_table("ai_auto_reply_runs")
    op.drop_table("ai_reply_decision_logs")
    op.drop_table("douyin_private_message_sends")
    op.drop_table("douyin_conversation_read_states")
    op.drop_table("conversation_autopilot_states")
    op.drop_table("douyin_account_autoreply_settings")
    op.drop_table("douyin_oauth_states")
    op.drop_table("feedback_records")
    op.drop_table("lead_followup_records")
    op.drop_table("lead_notifications")
    op.drop_table("check_configs")
    op.drop_table("reply_checks")
    op.drop_table("external_merchant_bindings")
