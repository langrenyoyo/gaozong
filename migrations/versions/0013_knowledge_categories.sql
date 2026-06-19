-- 0013 知识分类主表
-- 范围：仅在 9000 主后端新增知识分类主数据表，不执行数据迁移。
-- 说明：base 分类本阶段由服务层逻辑内置，不在本表强制落 system 行。

CREATE TABLE IF NOT EXISTS knowledge_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id VARCHAR(128),
    merchant_id VARCHAR(128),
    category_key VARCHAR(128) NOT NULL,
    name VARCHAR(100) NOT NULL,
    scope_type VARCHAR(20) NOT NULL DEFAULT 'merchant',
    is_base INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    created_by VARCHAR(128),
    updated_by VARCHAR(128)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_knowledge_categories_merchant_key
    ON knowledge_categories(merchant_id, category_key);

CREATE INDEX IF NOT EXISTS idx_knowledge_categories_merchant_status_sort
    ON knowledge_categories(merchant_id, status, sort_order);

CREATE INDEX IF NOT EXISTS idx_knowledge_categories_merchant_key_status
    ON knowledge_categories(merchant_id, category_key, status);
