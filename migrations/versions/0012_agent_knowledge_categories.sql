-- 0012 Agent 知识分类绑定表
-- 范围：仅在 9000 主后端新增 Agent 与知识分类的手动绑定数据模型。
-- 注意：本阶段不注入 allowed_category_keys 到 9100，不自动落 base 分类绑定行。

CREATE TABLE IF NOT EXISTS agent_knowledge_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    agent_id VARCHAR(64) NOT NULL,
    category_key VARCHAR(128) NOT NULL,
    scope_type VARCHAR(20) NOT NULL DEFAULT 'merchant',
    is_base INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    created_by VARCHAR(128),
    updated_by VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_agent_knowledge_categories_merchant_agent_status
    ON agent_knowledge_categories(merchant_id, agent_id, status);

CREATE INDEX IF NOT EXISTS idx_agent_knowledge_categories_merchant_key_status
    ON agent_knowledge_categories(merchant_id, category_key, status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_knowledge_categories_active
    ON agent_knowledge_categories(merchant_id, agent_id, category_key)
    WHERE status = 'active' AND deleted_at IS NULL;
