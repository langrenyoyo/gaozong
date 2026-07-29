-- 0039 ai_agents 增加商家可配置变量字段
-- 为 ai_agents 表增加 11 个商家可配置变量字段，支撑固定提示词模板 V2.0。
-- 商户在智能体配置中填写简单内容，9100 用固定模板注入这些变量生成系统提示词。
-- 与 PG 0019 迁移同步，避免 SQLite 过渡库与 PostgreSQL 生产库不一致。

ALTER TABLE ai_agents ADD COLUMN store_address TEXT;
ALTER TABLE ai_agents ADD COLUMN store_phone VARCHAR(50);
ALTER TABLE ai_agents ADD COLUMN store_wechat VARCHAR(100);
ALTER TABLE ai_agents ADD COLUMN business_hours VARCHAR(100);
ALTER TABLE ai_agents ADD COLUMN sales_cities TEXT;
ALTER TABLE ai_agents ADD COLUMN sales_brands TEXT;
ALTER TABLE ai_agents ADD COLUMN purchase_cities TEXT;
ALTER TABLE ai_agents ADD COLUMN purchase_brands TEXT;
ALTER TABLE ai_agents ADD COLUMN after_hours_reply TEXT;
ALTER TABLE ai_agents ADD COLUMN vehicle_condition_reply TEXT;
ALTER TABLE ai_agents ADD COLUMN appraiser_off_hours_reply TEXT;
