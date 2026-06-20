-- 0015 Webhook 自动回复 dry-run 运行记录
-- 范围：仅记录 webhook 触发的 AI 回复 dry-run 决策，不做真实发送。
-- 边界：不调用 send_msg，不修改 douyin_private_message_sends，不开启 auto_send。

CREATE TABLE IF NOT EXISTS ai_auto_reply_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    account_open_id VARCHAR(255) NOT NULL,
    conversation_short_id VARCHAR(255),
    customer_open_id VARCHAR(255),
    trigger_event_id INTEGER NOT NULL,
    trigger_event_key VARCHAR(255) NOT NULL,
    trigger_server_message_id VARCHAR(255),
    latest_message TEXT,
    agent_id VARCHAR(64),
    mode VARCHAR(32) NOT NULL DEFAULT 'dry_run',
    status VARCHAR(32) NOT NULL,
    skip_reason VARCHAR(128),
    block_reason VARCHAR(128),
    gate_results_json TEXT,
    decision_log_id INTEGER,
    would_send_content TEXT,
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_auto_reply_runs_trigger_event_key
    ON ai_auto_reply_runs(trigger_event_key);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_merchant
    ON ai_auto_reply_runs(merchant_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_account
    ON ai_auto_reply_runs(account_open_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_conversation
    ON ai_auto_reply_runs(conversation_short_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_customer
    ON ai_auto_reply_runs(customer_open_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_trigger_event
    ON ai_auto_reply_runs(trigger_event_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_agent
    ON ai_auto_reply_runs(agent_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_decision_log
    ON ai_auto_reply_runs(decision_log_id);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_created
    ON ai_auto_reply_runs(created_at);
