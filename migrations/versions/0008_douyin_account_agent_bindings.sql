-- 0008 抖音企业号与 AI 智能体绑定
-- 范围：补齐企业号商户归属字段，新增独立绑定表。
-- 注意：历史 douyin_authorized_accounts.merchant_id 为空时，接口层必须保守拒绝。

ALTER TABLE douyin_authorized_accounts ADD COLUMN merchant_id VARCHAR(128);
ALTER TABLE douyin_authorized_accounts ADD COLUMN tenant_id VARCHAR(128);

CREATE TABLE IF NOT EXISTS douyin_account_agent_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    account_open_id VARCHAR(255) NOT NULL,
    douyin_authorized_account_id INTEGER,
    agent_id VARCHAR(64) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME,
    updated_at DATETIME,
    unbound_at DATETIME,
    deleted_at DATETIME,
    created_by VARCHAR(128),
    updated_by VARCHAR(128),
    invalid_reason VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_dy_account_agent_bindings_merchant_account
    ON douyin_account_agent_bindings(merchant_id, account_open_id);

CREATE INDEX IF NOT EXISTS idx_dy_account_agent_bindings_merchant_agent
    ON douyin_account_agent_bindings(merchant_id, agent_id);

CREATE UNIQUE INDEX IF NOT EXISTS uk_dy_account_agent_bindings_active_default
    ON douyin_account_agent_bindings(merchant_id, account_open_id)
    WHERE status = 'active' AND is_default = 1 AND deleted_at IS NULL;
