-- 0031 Phase 10 算力计费快照（§0.2 甲方已批准合同）
-- ============================================================================
-- 范围（只安全重建两张既有算力表，不建新表、不重写 seed）：
--   1. compute_transactions：加 actual_tokens(BIGINT NULL) /
--      capability_key(VARCHAR(64) NULL) / markup_basis_points(INTEGER NULL)
--      + 两个 CHECK（actual 正数或空 / markup 非负或空）。
--      历史 consume 回填 actual_tokens=abs(delta_tokens)、markup_basis_points=0、
--      capability_key=NULL（历史能力无法证明，禁止伪造）；充值/套餐三字段保持空。
--   2. compute_markup_ratios：无新列，仅落 DB 级 CHECK
--      ck_compute_markup_ratios_basis_points_nonnegative（与 PG 0008、ORM 对齐）。
--
-- 安全模式（仿 0029/0030）：
--   * 前置守卫：compute_transactions 未被升级（无 actual_tokens），
--     compute_markup_ratios 六键精确存在、无未知键。任一失败触发 _guard CHECK 违反，
--     runner 整体 ROLLBACK，不登记 0031。
--   * 每张表事务内重建（runner 已包裹 BEGIN/COMMIT，脚本不重复声明事务）：
--     RENAME 正式→_backup → CREATE _new（全列 + CHECK）
--     → INSERT SELECT → _guard（行数 + max(id) + 双向 GROUP BY 全旧业务列 COUNT EXCEPT）
--     → DROP _backup → RENAME _new→正式 → 重建既有索引/唯一约束。
--   * 幂等：CREATE TABLE/INDEX 全部 IF NOT EXISTS；重建/守卫/RENAME 为 other 语句，
--     runner 已登记版本时整体跳过。
--
-- 边界：consume 行 delta_tokens=0 会触发 actual_tokens CHECK 失败（abs(0)=0 非正数），
-- 这会暴露违反"消耗禁止 0"业务规则的脏数据，由审批窗口处理，不自动兜底。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. 前置守卫（任一失败触发 _guard CHECK 违反，runner 整体 ROLLBACK，不登记 0031）
--    精确校验两表列集 == 0030 基线（拒绝额外列/缺失列/部分升级列，防止安全重建静默丢列）
--    + markup_ratios 六键数据精确（拒绝未知/缺失键）
-- ---------------------------------------------------------------------------

CREATE TEMP TABLE _guard_0031 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 0.1 compute_transactions 列数精确为 12
-- pragma_table_xinfo 覆盖生成列（hidden!=0），额外列/生成列超标即拒（pragma_table_info 会漏生成列）
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_transactions')
) = 12 THEN 1 ELSE 0 END;

-- 0.2 compute_transactions 12 基线列名都在且 hidden=0（普通列，拒绝生成/隐藏列同名）
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_transactions')
    WHERE name IN ('id','merchant_id','tenant_id','transaction_type','delta_tokens',
                   'balance_after_tokens','source','remark','model','agent_id',
                   'conversation_id','created_at')
                   AND hidden = 0
) = 12 THEN 1 ELSE 0 END;

-- 0.3 compute_markup_ratios 列数精确为 6（pragma_table_xinfo 含生成列）
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_markup_ratios')
) = 6 THEN 1 ELSE 0 END;

-- 0.4 compute_markup_ratios 6 基线列名都在且 hidden=0
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_markup_ratios')
    WHERE name IN ('id','capability_key','markup_basis_points','enabled','created_at','updated_at')
                   AND hidden = 0
) = 6 THEN 1 ELSE 0 END;

-- 0.5 compute_markup_ratios 无未知键
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM compute_markup_ratios
    WHERE capability_key NOT IN (
        'douyin-cs', 'leads', 'agents', 'wechat-assistant', 'compute', 'knowledge'
    )
) = 0 THEN 1 ELSE 0 END;

-- 0.6 compute_markup_ratios 六键精确存在（DISTINCT = 6，拒绝缺失键）
INSERT INTO _guard_0031 (ok)
SELECT CASE WHEN (
    SELECT count(DISTINCT capability_key) FROM compute_markup_ratios
    WHERE capability_key IN (
        'douyin-cs', 'leads', 'agents', 'wechat-assistant', 'compute', 'knowledge'
    )
) = 6 THEN 1 ELSE 0 END;

DROP TABLE _guard_0031;

-- ---------------------------------------------------------------------------
-- 1. compute_transactions（加 3 列 + 2 CHECK，历史 consume 回填）
-- ---------------------------------------------------------------------------
ALTER TABLE compute_transactions RENAME TO _compute_transactions_backup_0031;

CREATE TABLE _compute_transactions_new_0031 (
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
    created_at DATETIME,
    actual_tokens BIGINT,
    capability_key VARCHAR(64),
    markup_basis_points INTEGER,
    CHECK (actual_tokens IS NULL OR actual_tokens > 0),
    CHECK (markup_basis_points IS NULL OR markup_basis_points >= 0)
);

-- 前置守卫：delta_tokens = BIGINT_MIN（-2^63）的历史行 abs 会溢出（actual_tokens 是 BIGINT，
-- abs(-2^63)=2^63 超出 BIGINT_MAX）。运行时 _balance_within_bigint_range 已禁止产生该边界；
-- 历史行若存在则迁移阻断，要求人工清理后再迁移。用 < -9223372036854775807 跨方言安全匹配。
CREATE TEMP TABLE _guard_ct_0031 (ok INTEGER NOT NULL CHECK (ok = 1));
INSERT INTO _guard_ct_0031 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_transactions_backup_0031 WHERE delta_tokens < -9223372036854775807) = 0
THEN 1 ELSE 0 END;

-- 复制旧 12 列 + 历史 consume 回填快照（actual=abs(delta)、markup=0、capability=NULL）；
-- 充值/套餐三字段保持 NULL。历史能力无法证明，禁止伪造。
INSERT INTO _compute_transactions_new_0031 (
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at,
    actual_tokens, capability_key, markup_basis_points
)
SELECT
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at,
    CASE WHEN transaction_type='consume' THEN abs(delta_tokens) ELSE NULL END,
    NULL,
    CASE WHEN transaction_type='consume' THEN 0 ELSE NULL END
FROM _compute_transactions_backup_0031;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 全旧 12 业务列 COUNT EXCEPT
-- 注：_guard_ct_0031 已在前置 BIGINT_MIN 守卫时创建，此处直接复用追加守卫。

INSERT INTO _guard_ct_0031 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_transactions_new_0031) =
    (SELECT count(*) FROM _compute_transactions_backup_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_0031 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _compute_transactions_new_0031) IS
    (SELECT max(id) FROM _compute_transactions_backup_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_new_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_backup_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_backup_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at, count(*) AS cnt
    FROM _compute_transactions_new_0031
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at
) THEN 1 ELSE 0 END;

DROP TABLE _compute_transactions_backup_0031;
ALTER TABLE _compute_transactions_new_0031 RENAME TO compute_transactions;
DROP TABLE _guard_ct_0031;

-- 重建既有索引（RENAME 后旧索引随 _backup 删除）
CREATE INDEX IF NOT EXISTS idx_compute_transactions_merchant_created
    ON compute_transactions(merchant_id, created_at);

-- ---------------------------------------------------------------------------
-- 2. compute_markup_ratios（无新列，落 DB 级 CHECK 与 PG 0008 / ORM 对齐）
-- ---------------------------------------------------------------------------
ALTER TABLE compute_markup_ratios RENAME TO _compute_markup_ratios_backup_0031;

CREATE TABLE _compute_markup_ratios_new_0031 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_key VARCHAR(64) NOT NULL,
    markup_basis_points INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME,
    CHECK (markup_basis_points >= 0)
);

INSERT INTO _compute_markup_ratios_new_0031 (
    id, capability_key, markup_basis_points, enabled, created_at, updated_at
)
SELECT
    id, capability_key, markup_basis_points, enabled, created_at, updated_at
FROM _compute_markup_ratios_backup_0031;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 全 6 列 COUNT EXCEPT
CREATE TEMP TABLE _guard_cmr_0031 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_cmr_0031 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_markup_ratios_new_0031) =
    (SELECT count(*) FROM _compute_markup_ratios_backup_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_0031 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _compute_markup_ratios_new_0031) IS
    (SELECT max(id) FROM _compute_markup_ratios_backup_0031)
THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_new_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
    EXCEPT
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_backup_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_cmr_0031 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_backup_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
    EXCEPT
    SELECT id, capability_key, markup_basis_points, enabled, created_at, updated_at, count(*) AS cnt
    FROM _compute_markup_ratios_new_0031
    GROUP BY id, capability_key, markup_basis_points, enabled, created_at, updated_at
) THEN 1 ELSE 0 END;

DROP TABLE _compute_markup_ratios_backup_0031;
ALTER TABLE _compute_markup_ratios_new_0031 RENAME TO compute_markup_ratios;
DROP TABLE _guard_cmr_0031;

-- 重建既有唯一约束（RENAME 后随 _backup 删除）
CREATE UNIQUE INDEX IF NOT EXISTS uk_compute_markup_ratios_capability_key
    ON compute_markup_ratios(capability_key);
