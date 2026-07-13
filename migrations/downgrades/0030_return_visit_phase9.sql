-- 0030 Phase 9 回访迁移降级脚本（独立，不被 migrate_sqlite runner 自动发现）
-- ============================================================================
-- 目的：精确恢复 0027 原列集，删除 Phase 9 全部新增列/索引/约束，删除 0030 登记。
-- 执行方式：人工显式 executescript，不经过 runner（runner 仅升级）。
-- 数据安全：RENAME→CREATE 旧列集→INSERT 旧列→DROP backup→RENAME，旧数据不丢。
-- 验证：downgrade 后可再次 apply 0030（往返一致性，test_sqlite_0030_downgrade_*）。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. douyin_private_message_sends：删 return_visit_run_id + 删 uk return_visit_run
-- ---------------------------------------------------------------------------
ALTER TABLE douyin_private_message_sends RENAME TO _dpms_down_0030;

CREATE TABLE douyin_private_message_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    main_account_id INTEGER NOT NULL,
    conversation_short_id VARCHAR(255) NOT NULL,
    server_message_id VARCHAR(255) NOT NULL,
    from_user_id VARCHAR(255) NOT NULL,
    to_user_id VARCHAR(255) NOT NULL,
    customer_open_id VARCHAR(255),
    account_open_id VARCHAR(255),
    scene VARCHAR(64) NOT NULL DEFAULT 'im_reply_msg',
    content TEXT NOT NULL,
    request_body_json TEXT,
    response_body_json TEXT,
    upstream_msg_id VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_code VARCHAR(64),
    error_message VARCHAR(500),
    manual_confirmed INTEGER NOT NULL DEFAULT 1,
    auto_send INTEGER NOT NULL DEFAULT 0,
    decision_log_id INTEGER,
    auto_reply_run_id INTEGER,
    send_source VARCHAR(32) NOT NULL DEFAULT 'manual',
    operator_id VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME,
    sent_at DATETIME
);

INSERT INTO douyin_private_message_sends (
    id, main_account_id, conversation_short_id, server_message_id, from_user_id,
    to_user_id, customer_open_id, account_open_id, scene, content, request_body_json,
    response_body_json, upstream_msg_id, status, error_code, error_message,
    manual_confirmed, auto_send, decision_log_id, auto_reply_run_id, send_source,
    operator_id, created_at, updated_at, sent_at
)
SELECT
    id, main_account_id, conversation_short_id, server_message_id, from_user_id,
    to_user_id, customer_open_id, account_open_id, scene, content, request_body_json,
    response_body_json, upstream_msg_id, status, error_code, error_message,
    manual_confirmed, auto_send, decision_log_id, auto_reply_run_id, send_source,
    operator_id, created_at, updated_at, sent_at
FROM _dpms_down_0030;

DROP TABLE _dpms_down_0030;

CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_decision_log
    ON douyin_private_message_sends(decision_log_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_private_message_sends_auto_reply_run
    ON douyin_private_message_sends(auto_reply_run_id);
CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_send_source
    ON douyin_private_message_sends(send_source);

-- ---------------------------------------------------------------------------
-- 2. return_visit_runs：删 16 列 + 删 uk idempotency_key/cooldown/dispatch 索引
-- ---------------------------------------------------------------------------
ALTER TABLE return_visit_runs RENAME TO _rvr_down_0030;

CREATE TABLE return_visit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    lead_id INTEGER,
    staff_id INTEGER,
    reply_check_id INTEGER,
    prompt_key VARCHAR(64),
    trigger_source VARCHAR(32),
    trigger_text TEXT,
    judgement_source VARCHAR(32),
    judgement_result VARCHAR(32),
    generated_content TEXT,
    final_content TEXT,
    send_status VARCHAR(32),
    send_id VARCHAR(64),
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

INSERT INTO return_visit_runs (
    id, merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
    trigger_text, judgement_source, judgement_result, generated_content, final_content,
    send_status, send_id, error_message, created_at, updated_at
)
SELECT
    id, merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
    trigger_text, judgement_source, judgement_result, generated_content, final_content,
    send_status, send_id, error_message, created_at, updated_at
FROM _rvr_down_0030;

DROP TABLE _rvr_down_0030;

CREATE INDEX IF NOT EXISTS idx_return_visit_runs_merchant_created
    ON return_visit_runs(merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_lead
    ON return_visit_runs(lead_id);

-- ---------------------------------------------------------------------------
-- 3. return_visit_prompts：删 confidence_threshold + fallback_message
-- ---------------------------------------------------------------------------
ALTER TABLE return_visit_prompts RENAME TO _rvp_down_0030;

CREATE TABLE return_visit_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_key VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    scene_type VARCHAR(32),
    template_text TEXT,
    scope VARCHAR(32) NOT NULL DEFAULT 'global',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

INSERT INTO return_visit_prompts (
    id, prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
    created_at, updated_at
)
SELECT
    id, prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
    created_at, updated_at
FROM _rvp_down_0030;

DROP TABLE _rvp_down_0030;

CREATE UNIQUE INDEX IF NOT EXISTS uk_return_visit_prompts_prompt_key
    ON return_visit_prompts(prompt_key);

-- ---------------------------------------------------------------------------
-- 4. 删除 0030 登记（恢复 0029 前状态，runner 后续可再次 apply 0030）
-- ---------------------------------------------------------------------------
DELETE FROM schema_migrations WHERE version_num = '0030';
