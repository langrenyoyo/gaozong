-- 0035 抖音 webhook 事件商户隔离归属字段
-- ============================================================================
-- 范围：为 douyin_webhook_events 补齐 merchant_id / tenant_id 可空列与索引。
--   * 历史事件保持 NULL，禁止回填猜测归属；归属在入库时按事件方向解析企业号
--     绑定固化，归属不明保存空归属（DY-CS-TENANT-ISOLATION-READ-1/R2）。
--   * PostgreSQL douyin_webhook_events 已有可空 tenant_id、merchant_id，
--     本迁移仅对齐 SQLite 开发/过渡库 schema 与 ORM 写入契约。
--
-- 安全模式：
--   * 前置 head 精确为 0034，否则 _guard CHECK 违反，整体 ROLLBACK 不登记 0035。
--   * runner 的 add_column 解析在列已存在时自动跳过（幂等补偿历史库漂移）。
--   * 索引 CREATE INDEX IF NOT EXISTS，幂等。
-- ============================================================================

CREATE TEMP TABLE _guard_0035 (ok INTEGER NOT NULL CHECK (ok = 1));

-- head 必须精确为 0034，防止跳过前置迁移直接执行。
INSERT INTO _guard_0035 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0034' THEN 1 ELSE 0 END;

DROP TABLE _guard_0035;

ALTER TABLE douyin_webhook_events ADD COLUMN merchant_id VARCHAR(128);
ALTER TABLE douyin_webhook_events ADD COLUMN tenant_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_merchant
    ON douyin_webhook_events(merchant_id);
CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_tenant
    ON douyin_webhook_events(tenant_id);
