-- 0040 自动回复设置增加放行 manual_required 开关
-- 为 douyin_account_autoreply_settings 增加 allow_release_manual_required 列。
-- 语义：账号级开关，开启后豁免 manual_required 阻断（让需人工确认的回复也发送），
-- 但仍走完整发送 gate，不豁免 prompt_injection 等风险阻断。默认关闭（0）。
-- 与 PG 0020 迁移同步，避免 SQLite 过渡库与 PostgreSQL 生产库不一致。

ALTER TABLE douyin_account_autoreply_settings ADD COLUMN allow_release_manual_required INTEGER NOT NULL DEFAULT 0;
