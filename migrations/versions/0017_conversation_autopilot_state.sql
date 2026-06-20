-- Phase 8-E-B：抖音私信会话托管状态表

CREATE TABLE IF NOT EXISTS conversation_autopilot_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    account_open_id VARCHAR(255) NOT NULL,
    conversation_short_id VARCHAR(255) NOT NULL,
    customer_open_id VARCHAR(255),
    mode VARCHAR(32) NOT NULL DEFAULT 'ai',
    manual_takeover_until DATETIME,
    last_human_message_at DATETIME,
    last_ai_reply_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_conversation_autopilot_states_scope
    ON conversation_autopilot_states(merchant_id, account_open_id, conversation_short_id);

CREATE INDEX IF NOT EXISTS idx_conversation_autopilot_states_merchant_account
    ON conversation_autopilot_states(merchant_id, account_open_id);

CREATE INDEX IF NOT EXISTS idx_conversation_autopilot_states_mode
    ON conversation_autopilot_states(mode);

CREATE INDEX IF NOT EXISTS idx_conversation_autopilot_states_takeover_until
    ON conversation_autopilot_states(manual_takeover_until);
