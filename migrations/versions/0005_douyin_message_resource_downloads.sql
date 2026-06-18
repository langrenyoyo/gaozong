-- 0005 Douyin OpenAPI media resource download records
-- Scope: persist /download_resource attempts and returned resource URLs only.

CREATE TABLE IF NOT EXISTS douyin_message_resource_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_event_id INTEGER,
    main_account_id INTEGER NOT NULL,
    conversation_short_id VARCHAR(255) NOT NULL,
    server_message_id VARCHAR(255) NOT NULL,
    open_id VARCHAR(255) NOT NULL,
    media_type VARCHAR(32) NOT NULL,
    source_url TEXT NOT NULL,
    download_url TEXT,
    resource_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    upstream_err_no VARCHAR(64),
    upstream_err_msg VARCHAR(500),
    upstream_log_id VARCHAR(255),
    request_body_json TEXT,
    response_body_json TEXT,
    error_message VARCHAR(500),
    created_at DATETIME,
    updated_at DATETIME,
    downloaded_at DATETIME
);
