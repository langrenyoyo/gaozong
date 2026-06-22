-- 0020 抖音 Direct LLM 企业号自动回复策略
-- 范围：复用 douyin_account_autoreply_settings，空值按系统默认保守策略解析。
ALTER TABLE douyin_account_autoreply_settings
    ADD COLUMN direct_llm_policy_json TEXT;
