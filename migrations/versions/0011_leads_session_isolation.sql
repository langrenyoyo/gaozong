-- 0011 抖音线索按商户 + 会话隔离
-- ============================================================================
-- 范围：给 douyin_leads 增加 merchant_id / account_open_id / conversation_short_id
--       三列，并建立会话维度唯一约束。
-- 背景（P1-DY-LEAD-SESSION-1）：
--   - 线索聚合键从"客户 open_id (source_id)"改为"(account_open_id, conversation_short_id)"
--   - merchant_id 来自 RequestContext（NewCarProject 登录态），不来自 GMP / 前端
--   - account_open_id = 私信事件 to_user_id（企业号 open_id）
--   - source_id 保留，继续表示客户 open_id（from_user_id），不再作聚合主键
-- 历史数据策略（D3）：
--   - 不回填 merchant_id / account_open_id / conversation_short_id
--   - 历史 NULL 数据对商户 /leads 与 /reports/summary 不可见（WHERE merchant_id = ?）
--   - SQLite 唯一索引中 NULL 允许多条，历史 NULL 数据不会阻塞新数据写入
-- 幂等：
--   - ADD COLUMN 靠列存在性检查跳过（migrate_sqlite plan_migration）
--   - CREATE INDEX / CREATE UNIQUE INDEX 全部使用 IF NOT EXISTS
-- ============================================================================

ALTER TABLE douyin_leads ADD COLUMN merchant_id VARCHAR(128);
ALTER TABLE douyin_leads ADD COLUMN account_open_id VARCHAR(255);
ALTER TABLE douyin_leads ADD COLUMN conversation_short_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_douyin_leads_merchant
    ON douyin_leads(merchant_id);
CREATE INDEX IF NOT EXISTS idx_douyin_leads_account_open
    ON douyin_leads(account_open_id);
CREATE INDEX IF NOT EXISTS idx_douyin_leads_conv
    ON douyin_leads(conversation_short_id);
CREATE INDEX IF NOT EXISTS idx_douyin_leads_merchant_account
    ON douyin_leads(merchant_id, account_open_id);

-- 会话维度唯一：一个企业号 + 一个会话 = 一条线索
-- SQLite 唯一索引允许多条 NULL，历史 NULL 数据不阻塞新写入
CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_leads_account_conv
    ON douyin_leads(account_open_id, conversation_short_id);
