-- 0007 AI小高智能体最小持久化表
-- 范围：一期智能体名称、提示词、普通文本知识库和软删除状态。
-- 不包含 LangChain、Agent tools、复杂 RAG 训练流水线或 fine-tune 配置。
CREATE TABLE IF NOT EXISTS ai_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id VARCHAR(64) NOT NULL,
    merchant_id VARCHAR(128) NOT NULL,
    name VARCHAR(100) NOT NULL,
    avatar_seed VARCHAR(128) NOT NULL,
    avatar_url VARCHAR(1000),
    prompt TEXT NOT NULL DEFAULT '',
    knowledge_base_text TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_agents_agent_id
    ON ai_agents(agent_id);

CREATE INDEX IF NOT EXISTS idx_ai_agents_merchant_status
    ON ai_agents(merchant_id, status);
