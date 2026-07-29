-- 0038 自动回复设置增加风险转人工黑名单字段
-- 为 douyin_account_autoreply_settings 增加 manual_review_risk_flags_json 列。
-- 语义：转人工黑名单（risk_flags 在此列表中的风险类型转人工，其余发 9100 安全替代回复）。
-- 空列表 = 默认全放行（所有风险都发安全替代回复，简化门禁）。
-- 与 PG 0018 迁移同步，避免 SQLite 过渡库与 PostgreSQL 生产库不一致。

ALTER TABLE douyin_account_autoreply_settings ADD COLUMN manual_review_risk_flags_json TEXT;
