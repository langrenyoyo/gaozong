-- 0021 sales_staff 增加商户隔离字段 merchant_id
-- ============================================================================
-- 范围：给 sales_staff 增加 merchant_id 列，作为按商户分配销售的隔离依据。
-- 背景（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1）：
--   - webhook 留资线索按 (account_open_id → merchant_id) 归属商户
--   - auto_assign_next 必须只把线索分配给同 merchant_id 的活跃销售
--   - sales_staff 此前是仓库中唯一缺 merchant_id 的业务表
-- 历史数据策略：
--   - 不回填历史 sales_staff.merchant_id（保持 NULL）
--   - auto_assign_next 过滤条件要求 SalesStaff.merchant_id == lead.merchant_id，
--     历史 NULL 销售不会被任何有 merchant_id 的线索自动选中
-- 幂等：
--   - ADD COLUMN 靠列存在性检查跳过（migrate_sqlite plan_migration）
--   - CREATE INDEX 使用 IF NOT EXISTS
-- ============================================================================

ALTER TABLE sales_staff ADD COLUMN merchant_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_sales_staff_merchant
    ON sales_staff(merchant_id);
