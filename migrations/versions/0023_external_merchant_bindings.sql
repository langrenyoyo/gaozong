-- NewCarProject 外部账号到 auto_wechat 本地商户绑定
CREATE TABLE IF NOT EXISTS external_merchant_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system TEXT NOT NULL,
    external_user_id TEXT,
    external_account TEXT,
    merchant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('active', 'disabled', 'deleted')),
    CHECK (
        (external_user_id IS NOT NULL AND external_user_id <> '')
        OR (external_account IS NOT NULL AND external_account <> '')
    )
);

CREATE INDEX IF NOT EXISTS idx_external_merchant_bindings_user
    ON external_merchant_bindings(source_system, external_user_id);

CREATE INDEX IF NOT EXISTS idx_external_merchant_bindings_account
    ON external_merchant_bindings(source_system, external_account);

CREATE INDEX IF NOT EXISTS idx_external_merchant_bindings_merchant
    ON external_merchant_bindings(merchant_id);
