-- 0001 PRD 基础字段迁移
-- ============================================================================
-- 范围：schema_migrations 基础设施 + douyin_leads 9 列 + sales_staff 2 列
-- 字段口径（已锁定，见 docs/ai/14_DB_MIGRATION_PLAN.md Q11）：
--   - douyin_leads.status 已存在，本批不新增、不改动（取值域扩展属 P5 状态机阶段）
--   - 全部新增列允许 NULL，唯一例外 reassign_count NOT NULL DEFAULT 0
--   - 联系方式 / 原始文本 / 备注类列统一用 TEXT
-- 幂等：
--   - CREATE TABLE 用 IF NOT EXISTS（SQLite 原生支持）
--   - ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，由 migrate_sqlite.py
--     做列存在性检查（双重保护：版本表 + 列检查）
-- ============================================================================

-- 1. 迁移版本表（基础设施，不进入 app/models.py，仅由迁移 runner 维护）
CREATE TABLE IF NOT EXISTS schema_migrations (
    version_num  VARCHAR(32) PRIMARY KEY,
    applied_at   DATETIME NOT NULL,
    description  VARCHAR(200)
);

-- 2. douyin_leads 新增 9 列
ALTER TABLE douyin_leads ADD COLUMN raw_message_text TEXT;
ALTER TABLE douyin_leads ADD COLUMN extracted_phone TEXT;
ALTER TABLE douyin_leads ADD COLUMN extracted_wechat TEXT;
ALTER TABLE douyin_leads ADD COLUMN all_extracted_contacts TEXT;
ALTER TABLE douyin_leads ADD COLUMN contact_extract_status TEXT;
ALTER TABLE douyin_leads ADD COLUMN contact_extract_reason TEXT;
ALTER TABLE douyin_leads ADD COLUMN reassign_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE douyin_leads ADD COLUMN customer_id TEXT;
ALTER TABLE douyin_leads ADD COLUMN external_customer_id TEXT;

-- 3. sales_staff 新增 2 列
ALTER TABLE sales_staff ADD COLUMN sort_order INTEGER;
ALTER TABLE sales_staff ADD COLUMN remark TEXT;
