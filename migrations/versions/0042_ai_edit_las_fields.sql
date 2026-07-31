-- 0042 AI剪辑 LAS speech_auto 字段
-- 1. ai_edit_jobs 加 LAS 任务字段，默认空保持既有行行为
-- 2. ai_edit_materials 加 TOS 预签名字段
-- 与 PG 0022 迁移同步。

ALTER TABLE ai_edit_jobs ADD COLUMN las_task_id VARCHAR(128);
ALTER TABLE ai_edit_jobs ADD COLUMN las_idempotent_id VARCHAR(128);
ALTER TABLE ai_edit_jobs ADD COLUMN las_script TEXT;
ALTER TABLE ai_edit_jobs ADD COLUMN las_template VARCHAR(64);
ALTER TABLE ai_edit_jobs ADD COLUMN las_business_code VARCHAR(64);
ALTER TABLE ai_edit_jobs ADD COLUMN las_error_msg TEXT;
ALTER TABLE ai_edit_jobs ADD COLUMN las_metadata_json TEXT;

ALTER TABLE ai_edit_materials ADD COLUMN tos_presigned_url TEXT;
ALTER TABLE ai_edit_materials ADD COLUMN tos_presigned_expires_at DATETIME;
