-- 0019 抖音 AI 自动回复账号级白名单与频控字段
-- 范围：扩展 douyin_account_autoreply_settings，复用既有自动回复配置表。
-- 回滚：SQLite 环境如需回滚，按项目迁移规范备份恢复；不在生产库直接 DROP COLUMN。
ALTER TABLE douyin_account_autoreply_settings
    ADD COLUMN customer_whitelist_open_ids TEXT;

ALTER TABLE douyin_account_autoreply_settings
    ADD COLUMN conversation_whitelist_ids TEXT;

ALTER TABLE douyin_account_autoreply_settings
    ADD COLUMN min_interval_seconds INTEGER NOT NULL DEFAULT 60;

ALTER TABLE douyin_account_autoreply_settings
    ADD COLUMN max_auto_replies_per_conversation_per_day INTEGER NOT NULL DEFAULT 20;
