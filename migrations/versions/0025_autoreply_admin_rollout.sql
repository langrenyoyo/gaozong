-- 0025 自动回复管理员灰度配置、白名单与审计表。
-- 范围：只新增 DB 管理层配置，不接入真实发送 gate。
-- 回滚：SQLite 环境如需回滚，按项目迁移规范从备份恢复；不在生产库直接 DROP TABLE。

CREATE TABLE IF NOT EXISTS autoreply_rollout_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope VARCHAR(32) NOT NULL DEFAULT 'global',
    merchant_id VARCHAR(128),
    auto_reply_enabled BOOLEAN NOT NULL DEFAULT 0,
    real_send_enabled BOOLEAN NOT NULL DEFAULT 0,
    allow_full_rollout BOOLEAN NOT NULL DEFAULT 0,
    updated_by VARCHAR(128),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_autoreply_rollout_configs_scope_merchant UNIQUE (scope, merchant_id)
);

CREATE INDEX IF NOT EXISTS idx_autoreply_rollout_configs_merchant
    ON autoreply_rollout_configs(merchant_id);

CREATE TABLE IF NOT EXISTS autoreply_whitelist_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type VARCHAR(32) NOT NULL,
    merchant_id VARCHAR(128) NOT NULL,
    account_open_id VARCHAR(255),
    value VARCHAR(255) NOT NULL,
    reason TEXT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_by VARCHAR(128),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    disabled_by VARCHAR(128),
    disabled_at DATETIME,
    CONSTRAINT uk_autoreply_whitelist_entries_scope_value
        UNIQUE (entry_type, merchant_id, account_open_id, value)
);

CREATE INDEX IF NOT EXISTS idx_autoreply_whitelist_entries_merchant_type
    ON autoreply_whitelist_entries(merchant_id, entry_type, enabled);

CREATE INDEX IF NOT EXISTS idx_autoreply_whitelist_entries_account
    ON autoreply_whitelist_entries(account_open_id, enabled);

CREATE TABLE IF NOT EXISTS autoreply_admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action VARCHAR(64) NOT NULL,
    merchant_id VARCHAR(128),
    account_open_id VARCHAR(255),
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(255),
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    operator_id VARCHAR(128),
    operator_name VARCHAR(128),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_autoreply_admin_audit_logs_merchant_created
    ON autoreply_admin_audit_logs(merchant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_autoreply_admin_audit_logs_action_created
    ON autoreply_admin_audit_logs(action, created_at);

CREATE INDEX IF NOT EXISTS idx_autoreply_admin_audit_logs_account_created
    ON autoreply_admin_audit_logs(account_open_id, created_at);
