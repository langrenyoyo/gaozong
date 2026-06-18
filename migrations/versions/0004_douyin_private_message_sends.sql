-- 0004 Douyin OpenAPI manual private-message send records
-- Scope: persist manual-only /send_msg attempts without enabling auto send.

CREATE TABLE IF NOT EXISTS douyin_private_message_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    main_account_id INTEGER NOT NULL,
    conversation_short_id VARCHAR(255) NOT NULL,
    server_message_id VARCHAR(255) NOT NULL,
    from_user_id VARCHAR(255) NOT NULL,
    to_user_id VARCHAR(255) NOT NULL,
    customer_open_id VARCHAR(255),
    account_open_id VARCHAR(255),
    scene VARCHAR(64) NOT NULL DEFAULT 'im_reply_msg',
    content TEXT NOT NULL,
    request_body_json TEXT,
    response_body_json TEXT,
    upstream_msg_id VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_code VARCHAR(64),
    error_message VARCHAR(500),
    manual_confirmed INTEGER NOT NULL DEFAULT 1,
    auto_send INTEGER NOT NULL DEFAULT 0,
    operator_id VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME,
    sent_at DATETIME
);
