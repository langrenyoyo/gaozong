-- 0033 回滚：删除真实 Token 计量明细，恢复 0032 的 15 列流水表。

BEGIN;

CREATE TEMP TABLE _guard_down_0033 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_down_0033 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_transactions')
) = 20 THEN 1 ELSE 0 END;

INSERT INTO _guard_down_0033 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('compute_transactions')
    WHERE name IN (
        'id','merchant_id','tenant_id','transaction_type','delta_tokens',
        'balance_after_tokens','source','remark','model','agent_id',
        'conversation_id','created_at','actual_tokens','capability_key',
        'markup_basis_points','usage_measurement_method','prompt_tokens',
        'completion_tokens','cached_tokens','llm_call_stage'
    ) AND hidden = 0
) = 20 THEN 1 ELSE 0 END;

INSERT INTO _guard_down_0033 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0033' THEN 1 ELSE 0 END;

DROP TABLE _guard_down_0033;

ALTER TABLE compute_transactions RENAME TO _compute_transactions_down_0033;

CREATE TABLE _compute_transactions_new_down_0033 (
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

INSERT INTO _compute_transactions_new_down_0033 (
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at,
    actual_tokens, capability_key, markup_basis_points
)
SELECT
    id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
    source, remark, model, agent_id, conversation_id, created_at,
    actual_tokens, capability_key, markup_basis_points
FROM _compute_transactions_down_0033;

CREATE TEMP TABLE _guard_ct_down_0033 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_ct_down_0033 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _compute_transactions_new_down_0033) =
    (SELECT count(*) FROM _compute_transactions_down_0033)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0033 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _compute_transactions_new_down_0033) IS
    (SELECT max(id) FROM _compute_transactions_down_0033)
THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0033 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at,
           actual_tokens, capability_key, markup_basis_points, count(*) AS cnt
    FROM _compute_transactions_new_down_0033
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at,
             actual_tokens, capability_key, markup_basis_points
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at,
           actual_tokens, capability_key, markup_basis_points, count(*) AS cnt
    FROM _compute_transactions_down_0033
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at,
             actual_tokens, capability_key, markup_basis_points
) THEN 1 ELSE 0 END;

INSERT INTO _guard_ct_down_0033 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at,
           actual_tokens, capability_key, markup_basis_points, count(*) AS cnt
    FROM _compute_transactions_down_0033
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at,
             actual_tokens, capability_key, markup_basis_points
    EXCEPT
    SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
           source, remark, model, agent_id, conversation_id, created_at,
           actual_tokens, capability_key, markup_basis_points, count(*) AS cnt
    FROM _compute_transactions_new_down_0033
    GROUP BY id, merchant_id, tenant_id, transaction_type, delta_tokens, balance_after_tokens,
             source, remark, model, agent_id, conversation_id, created_at,
             actual_tokens, capability_key, markup_basis_points
) THEN 1 ELSE 0 END;

DROP TABLE _compute_transactions_down_0033;
ALTER TABLE _compute_transactions_new_down_0033 RENAME TO compute_transactions;
DROP TABLE _guard_ct_down_0033;

CREATE INDEX IF NOT EXISTS idx_compute_transactions_merchant_created
    ON compute_transactions(merchant_id, created_at);

DELETE FROM schema_migrations WHERE version_num = '0033';

COMMIT;
