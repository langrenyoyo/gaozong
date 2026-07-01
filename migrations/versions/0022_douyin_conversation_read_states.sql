-- 抖音客服工作台会话已读状态水位

CREATE TABLE IF NOT EXISTS douyin_conversation_read_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    account_open_id VARCHAR(255) NOT NULL,
    conversation_key VARCHAR(255) NOT NULL,
    conversation_short_id VARCHAR(255),
    customer_open_id VARCHAR(255),
    last_read_at DATETIME NOT NULL,
    last_read_event_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_dy_conversation_read_states_scope
    ON douyin_conversation_read_states(merchant_id, account_open_id, conversation_key);

CREATE INDEX IF NOT EXISTS idx_dy_conversation_read_states_merchant_account
    ON douyin_conversation_read_states(merchant_id, account_open_id);

CREATE INDEX IF NOT EXISTS idx_dy_conversation_read_states_customer
    ON douyin_conversation_read_states(customer_open_id);
