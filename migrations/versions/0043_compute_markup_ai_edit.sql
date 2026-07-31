-- 0043 算力上浮能力补 ai_edit 行（AI剪辑 LAS 重做新增能力）
-- COMPUTE_CAPABILITY_KEYS 加 ai_edit 后，compute_markup_ratios 需补对应行，
-- 否则 list_markup_ratios 校验 DB 行数 != 代码键数 → MARKUP_RATIO_DRIFT 500。
-- 与 PG 0023 迁移同步。

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'ai_edit', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'ai_edit');
