-- 0045 AI 剪辑结果交付闭环：标题、最终视频归档、软删除、视频标签
-- ai_edit_jobs + ai_edit_job_artifacts 加字段，与 PG 0025 迁移同步。
-- 所有新列可空，无破坏性变更。

-- ai_edit_jobs 标题三件套
ALTER TABLE ai_edit_jobs ADD COLUMN title VARCHAR(255);
ALTER TABLE ai_edit_jobs ADD COLUMN title_source VARCHAR(32);
ALTER TABLE ai_edit_jobs ADD COLUMN title_generated_at DATETIME;

-- ai_edit_jobs 交付归档状态
ALTER TABLE ai_edit_jobs ADD COLUMN delivery_status VARCHAR(32);

-- ai_edit_jobs 视频标签
ALTER TABLE ai_edit_jobs ADD COLUMN video_tags TEXT;

-- ai_edit_jobs 软删除四件套
ALTER TABLE ai_edit_jobs ADD COLUMN deleted_at DATETIME;
ALTER TABLE ai_edit_jobs ADD COLUMN deleted_by VARCHAR(128);
ALTER TABLE ai_edit_jobs ADD COLUMN delete_status VARCHAR(32);
ALTER TABLE ai_edit_jobs ADD COLUMN delete_error TEXT;

-- ai_edit_job_artifacts 最终视频与归档字段
ALTER TABLE ai_edit_job_artifacts ADD COLUMN is_final_video BOOLEAN;
ALTER TABLE ai_edit_job_artifacts ADD COLUMN delivery_status VARCHAR(32);
ALTER TABLE ai_edit_job_artifacts ADD COLUMN archive_object_key VARCHAR(255);
ALTER TABLE ai_edit_job_artifacts ADD COLUMN archive_error TEXT;
ALTER TABLE ai_edit_job_artifacts ADD COLUMN file_size_bytes BIGINT;

-- 历史任务回填交付状态
UPDATE ai_edit_jobs SET delivery_status = 'pending' WHERE delivery_status IS NULL;

-- 历史任务回填安全默认标题（混剪任务 #id），不覆盖已有标题，不调网络
UPDATE ai_edit_jobs SET title = '混剪任务 #' || id, title_source = 'fallback' WHERE title IS NULL;
