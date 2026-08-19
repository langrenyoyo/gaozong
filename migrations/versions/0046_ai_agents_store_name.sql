-- 0046 ai_agents 增加 store_name（门店名称）字段
-- P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1：store_name 仅归属 AiAgent。
-- 类型 VARCHAR(255)，NOT NULL（加列用 DEFAULT '' 兼容历史数据）。
-- 历史回填：优先 TRIM(name)；name 为空用明确安全占位 "未命名门店"。
-- 与 PG 0036 迁移同步，避免 SQLite 过渡库与 PostgreSQL 生产库不一致。

ALTER TABLE ai_agents ADD COLUMN store_name VARCHAR(255) NOT NULL DEFAULT '';

-- 历史回填：优先 TRIM(name)（name 非空时）
UPDATE ai_agents SET store_name = TRIM(name)
WHERE store_name = '' AND TRIM(name) <> '';

-- 历史回填：name 为空/空白时使用明确安全占位
UPDATE ai_agents SET store_name = '未命名门店'
WHERE store_name = '' OR store_name IS NULL;
