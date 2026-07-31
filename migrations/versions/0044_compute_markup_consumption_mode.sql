-- 0044 算力上浮加消耗模式与固定单次定额
-- compute_markup_ratios 加两列：consumption_mode（actual/custom，默认 actual）+
-- fixed_tokens_per_call（custom 模式固定 Token 定额）。
-- 与 PG 0024 迁移同步。

ALTER TABLE compute_markup_ratios ADD COLUMN consumption_mode VARCHAR(16) NOT NULL DEFAULT 'actual';
ALTER TABLE compute_markup_ratios ADD COLUMN fixed_tokens_per_call INTEGER;
