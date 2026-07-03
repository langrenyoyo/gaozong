-- 抖音 live-check OAuth state，一次性绑定授权发起时的可信商户上下文。
CREATE TABLE IF NOT EXISTS douyin_oauth_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state VARCHAR(128) NOT NULL,
    merchant_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128),
    source_system VARCHAR(64) NOT NULL DEFAULT 'new_car_project',
    redirect_target VARCHAR(1000),
    created_at DATETIME,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME,
    CONSTRAINT uk_douyin_oauth_states_state UNIQUE (state)
);

CREATE INDEX IF NOT EXISTS idx_douyin_oauth_states_merchant
    ON douyin_oauth_states(merchant_id);

CREATE INDEX IF NOT EXISTS idx_douyin_oauth_states_expires_at
    ON douyin_oauth_states(expires_at);
