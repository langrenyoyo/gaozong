-- 0018 抖音 AI 自动回复发送流水关联字段
-- 范围：仅为 douyin_private_message_sends 增加自动回复审计关联与防重复字段。
-- 边界：本文件只新增迁移脚本；Phase 8-F-B 不执行迁移。

ALTER TABLE douyin_private_message_sends
    ADD COLUMN decision_log_id INTEGER;

ALTER TABLE douyin_private_message_sends
    ADD COLUMN auto_reply_run_id INTEGER;

ALTER TABLE douyin_private_message_sends
    ADD COLUMN send_source VARCHAR(32) DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_decision_log
    ON douyin_private_message_sends(decision_log_id);

CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_private_message_sends_auto_reply_run
    ON douyin_private_message_sends(auto_reply_run_id);

CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_send_source
    ON douyin_private_message_sends(send_source);
