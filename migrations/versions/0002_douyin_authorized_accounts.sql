-- 0002 Douyin OpenAPI authorized accounts
-- Scope: persist /list_bind_info account bindings without changing webhook event tables.

CREATE TABLE IF NOT EXISTS douyin_authorized_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    main_account_id INTEGER NOT NULL,
    open_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255),
    union_id VARCHAR(255),
    account_name VARCHAR(255),
    avatar_url VARCHAR(1000),
    bind_status INTEGER NOT NULL DEFAULT 0,
    account_type INTEGER,
    bind_time VARCHAR(64),
    unbind_time VARCHAR(64),
    source_created_at VARCHAR(64),
    last_synced_at DATETIME,
    raw_body_json TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uk_douyin_authorized_account_main_open UNIQUE (main_account_id, open_id)
);
