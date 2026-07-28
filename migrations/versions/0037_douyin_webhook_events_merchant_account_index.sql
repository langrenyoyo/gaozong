-- 抖音 webhook 事件商户账号索引（SQLite 方言）
-- 为 douyin_webhook_events 增加两个组合索引，支撑增量游标查询
-- (merchant_id + to_user_id/from_user_id + id > cursor)，消除全表扫描。
-- SQLite 不支持 CONCURRENTLY，用 IF NOT EXISTS 幂等。

CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_merchant_to_id
    ON douyin_webhook_events (merchant_id, to_user_id, id);

CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_merchant_from_id
    ON douyin_webhook_events (merchant_id, from_user_id, id);
