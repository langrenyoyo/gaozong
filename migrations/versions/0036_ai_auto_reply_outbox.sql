-- 0036 AI 自动回复 outbox 持久化任务字段
-- ============================================================================
-- 范围：为 ai_auto_reply_runs 补齐 outbox 调度/租约字段。
--   * lease_owner / lease_expires_at：进程租约
--   * attempt_count：累计尝试次数
--   * next_attempt_at：下次可处理时间（retry_wait 退避）
--   * last_failure_stage：最后失败阶段
-- 复用现有表，不新增独立 outbox 表。
--
-- 安全模式：
--   * 前置 head 精确为 0035。
--   * runner add_column 在列已存在时跳过（幂等补偿）。
-- ============================================================================

CREATE TEMP TABLE _guard_0036 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_0036 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0035' THEN 1 ELSE 0 END;

DROP TABLE _guard_0036;

ALTER TABLE ai_auto_reply_runs ADD COLUMN lease_owner VARCHAR(128);
ALTER TABLE ai_auto_reply_runs ADD COLUMN lease_expires_at DATETIME;
ALTER TABLE ai_auto_reply_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_auto_reply_runs ADD COLUMN next_attempt_at DATETIME;
ALTER TABLE ai_auto_reply_runs ADD COLUMN last_failure_stage VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_status_next_attempt
    ON ai_auto_reply_runs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_ai_auto_reply_runs_lease
    ON ai_auto_reply_runs(lease_owner, lease_expires_at);
