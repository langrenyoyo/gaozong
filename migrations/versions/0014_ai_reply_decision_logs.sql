-- 0014 AI 回复决策日志
-- 范围：仅记录 9000 reply-suggestion 可信代理中的结构化建议与安全后处理结果。
-- 边界：不做自动发送，不做托管开关，不新增查询 API。

CREATE TABLE IF NOT EXISTS ai_reply_decision_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    account_open_id VARCHAR(255),
    conversation_id VARCHAR(255),
    conversation_short_id VARCHAR(255),
    open_id VARCHAR(255),
    customer_open_id VARCHAR(255),
    agent_id VARCHAR(64),
    agent_name VARCHAR(100),
    latest_message TEXT,
    reply_text TEXT,
    intent VARCHAR(64),
    lead_level VARCHAR(32),
    confidence REAL,
    manual_required INTEGER NOT NULL DEFAULT 1,
    manual_required_reason TEXT,
    risk_flags_json TEXT,
    tags_json TEXT,
    rag_sources_json TEXT,
    source_chunks_json TEXT,
    allowed_category_keys_json TEXT,
    llm_used INTEGER NOT NULL DEFAULT 0,
    rag_used INTEGER NOT NULL DEFAULT 0,
    upstream_auto_send INTEGER NOT NULL DEFAULT 0,
    final_auto_send INTEGER NOT NULL DEFAULT 0,
    decision_version VARCHAR(64),
    raw_response_json TEXT,
    error_message TEXT,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_ai_reply_decision_logs_merchant_created
    ON ai_reply_decision_logs(merchant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_reply_decision_logs_account_created
    ON ai_reply_decision_logs(account_open_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_reply_decision_logs_conversation_created
    ON ai_reply_decision_logs(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_reply_decision_logs_agent_created
    ON ai_reply_decision_logs(agent_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_reply_decision_logs_manual_created
    ON ai_reply_decision_logs(manual_required, created_at);
