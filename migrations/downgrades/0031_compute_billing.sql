-- 0031 downgrade：回退 Phase 10 算力计费快照（恢复 0030 列集与约束形态）
-- ============================================================================
-- 由 downgrade runner 以 executescript 直执（不经 apply_migration），脚本自带事务。
-- 安全模式（仿 upgrade，对称）：
--   * 前置守卫：compute_transactions 已被 0031 升级（存在 actual_tokens 列），
--     拒绝在未升级或二次降级状态运行，触发 _guard CHECK 违反整体 ROLLBACK。
--   * 单事务安全重建两表：RENAME 正式→_down 备份 → CREATE _new_down（0030 形态，无 Phase 10 列/CHECK）
--     → INSERT SELECT → 多重集守卫 → DROP 备份 → RENAME _new_down→正式 → 重建索引/唯一约束。
--   * 删除 schema_migrations 中 0031 登记。
-- ============================================================================

BEGIN;

-- 0. 前置守卫：已完整升级 + head 精确为 0031
--    精确校验 transactions 15 列（12 基线 + 3 新列）、markup_ratios 6 列，
--    拒绝未升级/部分升级/列漂移；max(version_num)='0031' 拒绝越序降级（存在 0032+ 时阻断）
CREATE TEMP TABLE _guard_down_0031 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 0.1 compute_transactions 列数精确为 15（12 基线 + 3 新列，确认已完整升级）
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_info('compute_transactions')
) = 15 THEN 1 ELSE 0 END;

-- 0.2 compute_transactions 15 列名都在
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_info('compute_transactions')
    WHERE name IN ('id','merchant_id','tenant_id','transaction_type','delta_tokens',
                   'balance_after_tokens','source','remark','model','agent_id',
                   'conversation_id','created_at',
                   'actual_tokens','capability_key','markup_basis_points')
) = 15 THEN 1 ELSE 0 END;

-- 0.3 compute_markup_ratios 列数精确为 6
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_info('compute_markup_ratios')
) = 6 THEN 1 ELSE 0 END;

-- 0.4 compute_markup_ratios 6 列名都在
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_info('compute_markup_ratios')
    WHERE name IN ('id','capability_key','markup_basis_points','enabled','created_at','updated_at')
) = 6 THEN 1 ELSE 0 END;

-- 0.5 0031 已登记
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM schema_migrations WHERE version_num='0031'
) = 1 THEN 1 ELSE 0 END;

-- 0.6 head 精确为 0031（无更高版本登记，拒绝越序降级）
INSERT INTO _guard_down_0031 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0031' THEN 1 ELSE 0 END;

DROP TABLE _guard_down_0031;

-- ---------------------------------------------------------------------------
-- 1. compute_transactions：去掉 3 个 Phase 10 列与 2 个 CHECK，恢复 0030 形态
-- ---------------------------------------------------------------------------
ALTER TABLE compute_transactions RENAME TO _compute_transactions_down_0031;

CREATE TABLE _compute_transactions_new_down_0031 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    transaction_type VARCHAR(32) NOT NULL,
    delta_tokens INTEGER NOT NULL,
    balance_after_tokens INTEGER NOT NULL,
    source VARCHAR(32) NOT NULL,
    remark TEXT,
    model VARCHAR(128),
    agent_id VARCHAR(64),
    conversation_id INTEGER,
    created_at DATETIME
);

INSERT INTO _compute_transactions_new_down_0031 (
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at
)
SELECT
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at
FROM _compute_transactions_down_0031;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 全 12 旧业务列 COUNT EXCEPT
CREATE TEMP TABLE _guard_ct_down_0031 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_ct_down_0031 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_transactions_new_down_0031) =
    (SELECT count(*) FROM _compute_transactions_down_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0031 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _compute_transactions_new_down_0031) IS
    (SELECT max(id) FROM _compute_transactions_down_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_new_down_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_down_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_down_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_new_down_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
) THEN 1 ELSE 0 END;

DROP TABLE _compute_transactions_down_0031;
ALTER TABLE _compute_transactions_new_down_0031 RENAME TO compute_transactions;
DROP TABLE _guard_ct_down_0031;

CREATE INDEX IF NOT EXISTS idx_compute_transactions_merchant_created
    ON compute_transactions(merchant_id, created_at);

-- ---------------------------------------------------------------------------
-- 2. compute_markup_ratios：去掉 Phase 10 CHECK，恢复 0030 形态（列集不变）
-- ---------------------------------------------------------------------------
ALTER TABLE compute_markup_ratios RENAME TO _compute_markup_ratios_down_0031;

CREATE TABLE _compute_markup_ratios_new_down_0031 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_key VARCHAR(64) NOT NULL,
    markup_basis_points INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

INSERT INTO _compute_markup_ratios_new_down_0031 (
    id, capability_key, markup_basis_points, enabled, created_at, updated_at
)
SELECT
    id, capability_key, markup_basis_points, enabled, created_at, updated_at
FROM _compute_markup_ratios_down_0031;

CREATE TEMP TABLE _guard_cmr_down_0031 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_cmr_down_0031 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_markup_ratios_new_down_0031) =
    (SELECT count(*) FROM _compute_markup_ratios_down_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_down_0031 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _compute_markup_ratios_new_down_0031) IS
    (SELECT max(id) FROM _compute_markup_ratios_down_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_down_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_new_down_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
    EXCEPT
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_down_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_down_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_down_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
    EXCEPT
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_new_down_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
) THEN 1 ELSE 0 END;

DROP TABLE _compute_markup_ratios_down_0031;
ALTER TABLE _compute_markup_ratios_new_down_0031 RENAME TO compute_markup_ratios;
DROP TABLE _guard_cmr_down_0031;

CREATE UNIQUE INDEX IF NOT EXISTS uk_compute_markup_ratios_capability_key
    ON compute_markup_ratios(capability_key);

-- ---------------------------------------------------------------------------
-- 3. 删除 0031 版本登记
-- ---------------------------------------------------------------------------
DELETE FROM schema_migrations WHERE version_num='0031';

COMMIT;
