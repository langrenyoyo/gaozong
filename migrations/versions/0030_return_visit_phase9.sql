-- 0030 Phase 9 回访数据迁移（微信到抖音回访，设计 FIX4 b077feb）
-- ============================================================================
-- 范围（只重建三张既有表，不建任何新表，F1）：
--   1. return_visit_prompts：加 confidence_threshold(NOT NULL DEFAULT 0.90)
--      + fallback_message(NOT NULL，三键 CASE 无 ELSE 回填已批准文案，F10)。
--   2. return_visit_runs：加设计 §4.2 的 16 列 + UNIQUE(idempotency_key)
--      + 冷却索引(merchant/account/conversation/customer/prompt_key)
--      + dispatch_notification_id 索引。
--   3. douyin_private_message_sends：加 return_visit_run_id + UNIQUE 索引
--      （镜像 auto_reply_run_id，C12）。
--
-- 安全模式（仿 0029）：
--   * return_visit_prompts 前置三键校验：未知 prompt_key 触发 _guard CHECK 违反，
--     整体 ROLLBACK，不登记 0030（F10/FIX4）。
--   * 每张表事务内重建：RENAME 正式→_backup → CREATE _new（全列）
--     → INSERT SELECT → _guard（行数 + max(id) + 双向 GROUP BY 全旧业务列
--     COUNT EXCEPT）→ DROP _backup → RENAME _new→正式 → DROP _guard。
--     任一守卫失败整体 ROLLBACK，原表回到 0030 前状态。
--   * CASE prompt_key 只写三键 WHEN，无 ELSE（前置校验保证仅三键；
--     未匹配则 NULL 触发 fallback_message NOT NULL 约束失败回滚，双保险）。
--   * RENAME 后重建迁移链既有索引（DROP _backup 删除旧索引）+ 新增 Phase 9 索引。
--   * 幂等：CREATE TABLE/INDEX 全部 IF NOT EXISTS；重建/守卫/RENAME 为 other 语句，
--     runner 已登记版本时整体跳过。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. return_visit_prompts（加 2 列 + 三键 CASE 无 ELSE 回填）
-- ---------------------------------------------------------------------------

-- 1.0 前置三键校验：未知 prompt_key 触发整体回滚（F10/FIX4）
CREATE TEMP TABLE _guard_rvp_keys_0030 (ok INTEGER NOT NULL CHECK (ok = 1));
INSERT INTO _guard_rvp_keys_0030 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM return_visit_prompts
    WHERE prompt_key NOT IN (
        'retain_contact_conversion',
        'finance_plan_followup',
        'silent_customer_wakeup'
    )
) = 0 THEN 1 ELSE 0 END;
DROP TABLE _guard_rvp_keys_0030;

-- 1.1 改名旧表为事务内备份
ALTER TABLE return_visit_prompts RENAME TO _return_visit_prompts_backup_0030;

-- 1.2 建中间表（旧 10 列 + Phase 9 新 2 列）
CREATE TABLE _return_visit_prompts_new_0030 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_key VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    scene_type VARCHAR(32),
    template_text TEXT,
    scope VARCHAR(32) NOT NULL DEFAULT 'global',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME,
    confidence_threshold FLOAT NOT NULL DEFAULT 0.90,
    fallback_message TEXT NOT NULL
);

-- 1.3 复制旧数据 + CASE 三键无 ELSE 回填（前置校验保证仅三键，未匹配则 NULL 触发 NOT NULL 失败）
INSERT INTO _return_visit_prompts_new_0030 (
    id, prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
    created_at, updated_at, confidence_threshold, fallback_message
)
SELECT
    id, prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
    created_at, updated_at, 0.90,
    CASE prompt_key
        WHEN 'retain_contact_conversion' THEN '您好，刚才留存的联系方式似乎无法正常联系。麻烦您重新发送一个常用手机号或微信号，方便我们继续为您服务。'
        WHEN 'finance_plan_followup' THEN '您好，关于您关注的金融方案，我们可以继续为您说明。您更想了解首付、月供还是分期期限？'
        WHEN 'silent_customer_wakeup' THEN '您好，之前的咨询还需要我们继续协助吗？方便时告诉我您目前最关心的问题，我们再为您跟进。'
    END
FROM _return_visit_prompts_backup_0030;

-- 1.4 多重集守卫：行数 + max(id) + 双向 GROUP BY 全旧业务列 COUNT EXCEPT
CREATE TEMP TABLE _guard_rvp_0030 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_rvp_0030 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _return_visit_prompts_new_0030) =
    (SELECT count(*) FROM _return_visit_prompts_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_rvp_0030 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _return_visit_prompts_new_0030) IS
    (SELECT max(id) FROM _return_visit_prompts_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_rvp_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
           created_at, updated_at, count(*) AS cnt
    FROM _return_visit_prompts_new_0030
    GROUP BY prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
             created_at, updated_at
    EXCEPT
    SELECT prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
           created_at, updated_at, count(*) AS cnt
    FROM _return_visit_prompts_backup_0030
    GROUP BY prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
             created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_rvp_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
           created_at, updated_at, count(*) AS cnt
    FROM _return_visit_prompts_backup_0030
    GROUP BY prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
             created_at, updated_at
    EXCEPT
    SELECT prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
           created_at, updated_at, count(*) AS cnt
    FROM _return_visit_prompts_new_0030
    GROUP BY prompt_key, name, scene_type, template_text, scope, enabled, sort_order,
             created_at, updated_at
) THEN 1 ELSE 0 END;

-- 1.5 守卫全通过：删备份 + 改名 + 重建唯一索引
DROP TABLE _return_visit_prompts_backup_0030;
ALTER TABLE _return_visit_prompts_new_0030 RENAME TO return_visit_prompts;
DROP TABLE _guard_rvp_0030;

CREATE UNIQUE INDEX IF NOT EXISTS uk_return_visit_prompts_prompt_key
    ON return_visit_prompts(prompt_key);

-- ---------------------------------------------------------------------------
-- 2. return_visit_runs（加 16 列 + UNIQUE idempotency_key + 冷却/dispatch 索引）
-- ---------------------------------------------------------------------------
ALTER TABLE return_visit_runs RENAME TO _return_visit_runs_backup_0030;

CREATE TABLE _return_visit_runs_new_0030 (
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
    updated_at DATETIME,
    dispatch_notification_id INTEGER,
    trigger_message_fp VARCHAR(64),
    idempotency_key VARCHAR(128),
    account_open_id VARCHAR(255),
    conversation_short_id VARCHAR(255),
    customer_open_id VARCHAR(255),
    context_server_message_id VARCHAR(255),
    confidence FLOAT,
    model VARCHAR(128),
    risk_flags_json TEXT,
    gate_results_json TEXT,
    last_failure_stage VARCHAR(100),
    manual_takeover BOOLEAN NOT NULL DEFAULT 0,
    lease_owner VARCHAR(64),
    lease_expires_at DATETIME,
    attempt_count INTEGER NOT NULL DEFAULT 0
);

INSERT INTO _return_visit_runs_new_0030 (
    id, merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
    trigger_text, judgement_source, judgement_result, generated_content, final_content,
    send_status, send_id, error_message, created_at, updated_at
)
SELECT
    id, merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
    trigger_text, judgement_source, judgement_result, generated_content, final_content,
    send_status, send_id, error_message, created_at, updated_at
FROM _return_visit_runs_backup_0030;

CREATE TEMP TABLE _guard_rvr_0030 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_rvr_0030 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _return_visit_runs_new_0030) =
    (SELECT count(*) FROM _return_visit_runs_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_rvr_0030 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _return_visit_runs_new_0030) IS
    (SELECT max(id) FROM _return_visit_runs_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_rvr_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
           trigger_text, judgement_source, judgement_result, generated_content,
           final_content, send_status, send_id, error_message, created_at, updated_at,
           count(*) AS cnt
    FROM _return_visit_runs_new_0030
    GROUP BY merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
             trigger_text, judgement_source, judgement_result, generated_content,
             final_content, send_status, send_id, error_message, created_at, updated_at
    EXCEPT
    SELECT merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
           trigger_text, judgement_source, judgement_result, generated_content,
           final_content, send_status, send_id, error_message, created_at, updated_at,
           count(*) AS cnt
    FROM _return_visit_runs_backup_0030
    GROUP BY merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
             trigger_text, judgement_source, judgement_result, generated_content,
             final_content, send_status, send_id, error_message, created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_rvr_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
           trigger_text, judgement_source, judgement_result, generated_content,
           final_content, send_status, send_id, error_message, created_at, updated_at,
           count(*) AS cnt
    FROM _return_visit_runs_backup_0030
    GROUP BY merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
             trigger_text, judgement_source, judgement_result, generated_content,
             final_content, send_status, send_id, error_message, created_at, updated_at
    EXCEPT
    SELECT merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
           trigger_text, judgement_source, judgement_result, generated_content,
           final_content, send_status, send_id, error_message, created_at, updated_at,
           count(*) AS cnt
    FROM _return_visit_runs_new_0030
    GROUP BY merchant_id, lead_id, staff_id, reply_check_id, prompt_key, trigger_source,
             trigger_text, judgement_source, judgement_result, generated_content,
             final_content, send_status, send_id, error_message, created_at, updated_at
) THEN 1 ELSE 0 END;

DROP TABLE _return_visit_runs_backup_0030;
ALTER TABLE _return_visit_runs_new_0030 RENAME TO return_visit_runs;
DROP TABLE _guard_rvr_0030;

-- 重建既有索引 + Phase 9 新增
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_merchant_created
    ON return_visit_runs(merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_lead
    ON return_visit_runs(lead_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_return_visit_runs_idempotency_key
    ON return_visit_runs(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_cooldown
    ON return_visit_runs(merchant_id, account_open_id, conversation_short_id,
                         customer_open_id, prompt_key);
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_dispatch_notification
    ON return_visit_runs(dispatch_notification_id);

-- ---------------------------------------------------------------------------
-- 3. douyin_private_message_sends（加 return_visit_run_id + UNIQUE 索引）
--    SQLite 迁移体系 0004/0018 已建此表；主线库由 ORM create_all 建。
--    CREATE TABLE IF NOT EXISTS 统一两种场景：存在则 skip，不存在则建壳。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS douyin_private_message_sends (
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

ALTER TABLE douyin_private_message_sends RENAME TO _douyin_private_message_sends_backup_0030;

CREATE TABLE _douyin_private_message_sends_new_0030 (
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
    sent_at DATETIME,
    return_visit_run_id INTEGER
);

INSERT INTO _douyin_private_message_sends_new_0030 (
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
FROM _douyin_private_message_sends_backup_0030;

CREATE TEMP TABLE _guard_dpms_0030 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_dpms_0030 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _douyin_private_message_sends_new_0030) =
    (SELECT count(*) FROM _douyin_private_message_sends_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_dpms_0030 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _douyin_private_message_sends_new_0030) IS
    (SELECT max(id) FROM _douyin_private_message_sends_backup_0030)
THEN 1 ELSE 0 END;

INSERT INTO _guard_dpms_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT main_account_id, conversation_short_id, server_message_id, from_user_id,
           to_user_id, customer_open_id, account_open_id, scene, content,
           request_body_json, response_body_json, upstream_msg_id, status, error_code,
           error_message, manual_confirmed, auto_send, decision_log_id,
           auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at,
           count(*) AS cnt
    FROM _douyin_private_message_sends_new_0030
    GROUP BY main_account_id, conversation_short_id, server_message_id, from_user_id,
             to_user_id, customer_open_id, account_open_id, scene, content,
             request_body_json, response_body_json, upstream_msg_id, status, error_code,
             error_message, manual_confirmed, auto_send, decision_log_id,
             auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at
    EXCEPT
    SELECT main_account_id, conversation_short_id, server_message_id, from_user_id,
           to_user_id, customer_open_id, account_open_id, scene, content,
           request_body_json, response_body_json, upstream_msg_id, status, error_code,
           error_message, manual_confirmed, auto_send, decision_log_id,
           auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at,
           count(*) AS cnt
    FROM _douyin_private_message_sends_backup_0030
    GROUP BY main_account_id, conversation_short_id, server_message_id, from_user_id,
             to_user_id, customer_open_id, account_open_id, scene, content,
             request_body_json, response_body_json, upstream_msg_id, status, error_code,
             error_message, manual_confirmed, auto_send, decision_log_id,
             auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_dpms_0030 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT main_account_id, conversation_short_id, server_message_id, from_user_id,
           to_user_id, customer_open_id, account_open_id, scene, content,
           request_body_json, response_body_json, upstream_msg_id, status, error_code,
           error_message, manual_confirmed, auto_send, decision_log_id,
           auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at,
           count(*) AS cnt
    FROM _douyin_private_message_sends_backup_0030
    GROUP BY main_account_id, conversation_short_id, server_message_id, from_user_id,
             to_user_id, customer_open_id, account_open_id, scene, content,
             request_body_json, response_body_json, upstream_msg_id, status, error_code,
             error_message, manual_confirmed, auto_send, decision_log_id,
             auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at
    EXCEPT
    SELECT main_account_id, conversation_short_id, server_message_id, from_user_id,
           to_user_id, customer_open_id, account_open_id, scene, content,
           request_body_json, response_body_json, upstream_msg_id, status, error_code,
           error_message, manual_confirmed, auto_send, decision_log_id,
           auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at,
           count(*) AS cnt
    FROM _douyin_private_message_sends_new_0030
    GROUP BY main_account_id, conversation_short_id, server_message_id, from_user_id,
             to_user_id, customer_open_id, account_open_id, scene, content,
             request_body_json, response_body_json, upstream_msg_id, status, error_code,
             error_message, manual_confirmed, auto_send, decision_log_id,
             auto_reply_run_id, send_source, operator_id, created_at, updated_at, sent_at
) THEN 1 ELSE 0 END;

DROP TABLE _douyin_private_message_sends_backup_0030;
ALTER TABLE _douyin_private_message_sends_new_0030 RENAME TO douyin_private_message_sends;
DROP TABLE _guard_dpms_0030;

-- 重建迁移链既有索引（0018）+ Phase 9 新增
CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_decision_log
    ON douyin_private_message_sends(decision_log_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_private_message_sends_auto_reply_run
    ON douyin_private_message_sends(auto_reply_run_id);
CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_send_source
    ON douyin_private_message_sends(send_source);
CREATE UNIQUE INDEX IF NOT EXISTS uk_douyin_private_message_sends_return_visit_run
    ON douyin_private_message_sends(return_visit_run_id);
