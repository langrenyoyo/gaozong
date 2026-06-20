-- Phase 8-E-B：抖音企业号自动回复配置表

CREATE TABLE IF NOT EXISTS douyin_account_autoreply_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    account_open_id VARCHAR(255) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 0,
    dry_run_enabled BOOLEAN NOT NULL DEFAULT 0,
    send_enabled BOOLEAN NOT NULL DEFAULT 0,
    min_confidence FLOAT NOT NULL DEFAULT 0.85,
    require_rag BOOLEAN NOT NULL DEFAULT 1,
    require_rag_sources BOOLEAN NOT NULL DEFAULT 1,
    allowed_intents_json TEXT,
    blocked_risk_flags_json TEXT,
    max_replies_per_conversation_per_hour INTEGER NOT NULL DEFAULT 3,
    max_replies_per_account_per_hour INTEGER NOT NULL DEFAULT 30,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_autoreply_settings_merchant_account
    ON douyin_account_autoreply_settings(merchant_id, account_open_id);

CREATE INDEX IF NOT EXISTS idx_douyin_autoreply_settings_account
    ON douyin_account_autoreply_settings(account_open_id);

CREATE INDEX IF NOT EXISTS idx_douyin_autoreply_settings_switches
    ON douyin_account_autoreply_settings(enabled, dry_run_enabled, send_enabled);
