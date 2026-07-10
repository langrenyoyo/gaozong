-- 0027 小高 AI 一期 Phase 1 数据迁移骨架
-- ============================================================================
-- 范围：只做数据层结构骨架 + 固定 seed，不接 service / router / 前端 / 发送链路。
-- 对齐《小高AI系统一期_需求理解与VibeCoding指令.md》Phase 1 数据迁移骨架执行包：
--   1. sales_staff 增加 5 个规则布尔字段（参与线索分配 + 4 类报表开关）。
--   2. ai_reply_decision_logs 增加有效性（is_effective / effectiveness_reason）和 model。
--   3. 新增 15 张一期后续模块共用表（违禁词、回访、销售日报、算力上浮、一键过审、AI 剪辑）。
--   4. 固定 seed：3 类违禁词库、3 类回访提示词、3 个算力套餐、6 个算力上浮能力。
-- 字段口径：
--   - 布尔字段用 BOOLEAN NOT NULL DEFAULT 1/0（SQLite 整数别名，与 0010 compute_packages 一致）。
--   - markup_basis_points 用基点整数（3300 表示 33%），不用浮点。
--   - access_token / refresh_token 只存密文占位列；本阶段不写入真实凭证。
-- 幂等：
--   - CREATE TABLE / CREATE INDEX 全部 IF NOT EXISTS。
--   - ALTER TABLE ADD COLUMN 列存在则由 runner 跳过。
--   - seed 全部用 INSERT INTO ... SELECT ... WHERE NOT EXISTS，避免重复插入。
-- 前置表：sales_staff、ai_reply_decision_logs、compute_packages（由更早迁移创建）。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. sales_staff 新增 5 个规则布尔字段
-- ---------------------------------------------------------------------------
ALTER TABLE sales_staff ADD COLUMN enable_lead_assignment BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE sales_staff ADD COLUMN enable_short_video_live_lead_report BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE sales_staff ADD COLUMN enable_daily_sales_feedback_report BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE sales_staff ADD COLUMN enable_lead_trace_report BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE sales_staff ADD COLUMN enable_sales_unit_cost_report BOOLEAN NOT NULL DEFAULT 0;

-- ---------------------------------------------------------------------------
-- 2. ai_reply_decision_logs 新增有效性与模型字段
-- ---------------------------------------------------------------------------
ALTER TABLE ai_reply_decision_logs ADD COLUMN is_effective BOOLEAN;
ALTER TABLE ai_reply_decision_logs ADD COLUMN effectiveness_reason TEXT;
ALTER TABLE ai_reply_decision_logs ADD COLUMN model VARCHAR(128);

-- ---------------------------------------------------------------------------
-- 3. 新增全局配置表
-- ---------------------------------------------------------------------------

-- 3.1 违禁词库（全局，按 library_key 唯一）
CREATE TABLE IF NOT EXISTS forbidden_word_libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_key VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    scope VARCHAR(32) NOT NULL DEFAULT 'global',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_forbidden_word_libraries_library_key
    ON forbidden_word_libraries(library_key);

-- 3.2 违禁词条目（归属词库，library_id + word 唯一；本阶段只建表不预置词条）
CREATE TABLE IF NOT EXISTS forbidden_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL,
    word VARCHAR(100) NOT NULL,
    safe_word VARCHAR(100),
    severity VARCHAR(32),
    enabled BOOLEAN NOT NULL DEFAULT 1,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_forbidden_words_library_word
    ON forbidden_words(library_id, word);
CREATE INDEX IF NOT EXISTS idx_forbidden_words_library
    ON forbidden_words(library_id);

-- 3.3 回访提示词（全局，按 prompt_key 唯一）
CREATE TABLE IF NOT EXISTS return_visit_prompts (
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

CREATE UNIQUE INDEX IF NOT EXISTS uk_return_visit_prompts_prompt_key
    ON return_visit_prompts(prompt_key);

-- 3.4 算力上浮比例（全局，按 capability_key 唯一；markup_basis_points 用基点）
CREATE TABLE IF NOT EXISTS compute_markup_ratios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_key VARCHAR(64) NOT NULL,
    markup_basis_points INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_compute_markup_ratios_capability_key
    ON compute_markup_ratios(capability_key);

-- ---------------------------------------------------------------------------
-- 4. 新增商户业务表（均有 merchant_id）
-- ---------------------------------------------------------------------------

-- 4.1 违禁词命中日志（只保存摘要）
CREATE TABLE IF NOT EXISTS forbidden_word_hit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    library_key VARCHAR(64),
    word VARCHAR(100),
    safe_word VARCHAR(100),
    source VARCHAR(32),
    context_type VARCHAR(32),
    context_id VARCHAR(64),
    before_text_summary TEXT,
    after_text_summary TEXT,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_forbidden_word_hit_logs_merchant_created
    ON forbidden_word_hit_logs(merchant_id, created_at);

-- 4.2 回访运行记录
CREATE TABLE IF NOT EXISTS return_visit_runs (
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

CREATE INDEX IF NOT EXISTS idx_return_visit_runs_merchant_created
    ON return_visit_runs(merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_return_visit_runs_lead
    ON return_visit_runs(lead_id);

-- 4.3 【线索反馈】表
CREATE TABLE IF NOT EXISTS sales_lead_feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    feedback_no VARCHAR(64) NOT NULL,
    lead_id INTEGER,
    staff_id INTEGER,
    raw_text TEXT,
    wechat_status VARCHAR(32),
    opening_status VARCHAR(32),
    payment_method VARCHAR(32),
    car_model VARCHAR(100),
    match_status VARCHAR(32),
    budget_text VARCHAR(100),
    precision_status VARCHAR(32),
    imprecision_reason TEXT,
    intention_level VARCHAR(32),
    no_intention_reason TEXT,
    region_text VARCHAR(100),
    remark TEXT,
    parse_status VARCHAR(32),
    parse_error TEXT,
    feedback_date DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_sales_lead_feedbacks_merchant_feedback_no
    ON sales_lead_feedbacks(merchant_id, feedback_no);
CREATE INDEX IF NOT EXISTS idx_sales_lead_feedbacks_merchant_lead
    ON sales_lead_feedbacks(merchant_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_sales_lead_feedbacks_merchant_staff
    ON sales_lead_feedbacks(merchant_id, staff_id);

-- 4.4 【线索更新】表（到店/成交）
CREATE TABLE IF NOT EXISTS sales_lead_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    feedback_no VARCHAR(64),
    lead_id INTEGER,
    staff_id INTEGER,
    raw_text TEXT,
    visit_status VARCHAR(32),
    visit_time_text VARCHAR(64),
    deal_status VARCHAR(32),
    deal_time_text VARCHAR(64),
    remark TEXT,
    parse_status VARCHAR(32),
    parse_error TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_sales_lead_updates_merchant_lead
    ON sales_lead_updates(merchant_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_sales_lead_updates_merchant_feedback
    ON sales_lead_updates(merchant_id, feedback_no);

-- 4.5 【每日线索总结】表（每个销售每天一条）
CREATE TABLE IF NOT EXISTS sales_daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    staff_id INTEGER NOT NULL,
    summary_date DATETIME NOT NULL,
    sales_name VARCHAR(50),
    raw_text TEXT,
    overall_quality VARCHAR(32),
    main_problem TEXT,
    car_model_summary TEXT,
    budget_summary TEXT,
    cooperation_level VARCHAR(32),
    today_suggestion TEXT,
    extra_feedback TEXT,
    parse_status VARCHAR(32),
    parse_error TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_sales_daily_summaries_merchant_staff_date
    ON sales_daily_summaries(merchant_id, staff_id, summary_date);
CREATE INDEX IF NOT EXISTS idx_sales_daily_summaries_merchant_date
    ON sales_daily_summaries(merchant_id, summary_date);

-- 4.6 日报任务（file_storage_key 为内部存储键，不返回绝对路径）
CREATE TABLE IF NOT EXISTS daily_report_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    report_date DATETIME,
    report_type VARCHAR(32),
    receiver_staff_id INTEGER,
    status VARCHAR(32),
    file_storage_key VARCHAR(255),
    file_name VARCHAR(255),
    error_message TEXT,
    generated_at DATETIME,
    sent_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_daily_report_jobs_merchant_status_date
    ON daily_report_jobs(merchant_id, status, report_date);

-- ---------------------------------------------------------------------------
-- 5. 一键过审（独立于抖音企业号授权表，不建强外键）
-- ---------------------------------------------------------------------------

-- 5.1 一键过审授权账号（token 只存密文占位）
CREATE TABLE IF NOT EXISTS ad_review_oauth_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    advertiser_id VARCHAR(128) NOT NULL,
    account_name VARCHAR(128),
    auth_status VARCHAR(32),
    access_token_cipher TEXT,
    refresh_token_cipher TEXT,
    token_expires_at DATETIME,
    raw_body_json TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_ad_review_oauth_accounts_merchant_advertiser
    ON ad_review_oauth_accounts(merchant_id, advertiser_id);

-- 5.2 一键过审建议（按 merchant_id + suggestion_key 幂等）
CREATE TABLE IF NOT EXISTS ad_review_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    oauth_account_id INTEGER,
    suggestion_key VARCHAR(128) NOT NULL,
    advertiser_id VARCHAR(128),
    ad_id VARCHAR(128),
    material_id VARCHAR(128),
    rejection_reason TEXT,
    suggestion_text TEXT,
    adopt_status VARCHAR(32),
    raw_body_json TEXT,
    pulled_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ad_review_suggestions_merchant_suggestion_key
    ON ad_review_suggestions(merchant_id, suggestion_key);
CREATE INDEX IF NOT EXISTS idx_ad_review_suggestions_merchant_oauth
    ON ad_review_suggestions(merchant_id, oauth_account_id);

-- 5.3 一键过审采纳任务（按 merchant_id + task_key 幂等）
CREATE TABLE IF NOT EXISTS ad_review_adopt_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    oauth_account_id INTEGER,
    task_key VARCHAR(128) NOT NULL,
    suggestion_ids_json TEXT,
    status VARCHAR(32),
    request_body_json TEXT,
    response_body_json TEXT,
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    completed_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ad_review_adopt_tasks_merchant_task_key
    ON ad_review_adopt_tasks(merchant_id, task_key);
CREATE INDEX IF NOT EXISTS idx_ad_review_adopt_tasks_merchant_status
    ON ad_review_adopt_tasks(merchant_id, status);

-- ---------------------------------------------------------------------------
-- 6. AI 剪辑（只做迁入后的任务壳与产物映射，不接外部 auto_edit）
-- ---------------------------------------------------------------------------

-- 6.1 AI 剪辑任务（按 job_id 幂等）
CREATE TABLE IF NOT EXISTS ai_edit_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    job_id VARCHAR(64) NOT NULL,
    status VARCHAR(32),
    source_type VARCHAR(32),
    input_json TEXT,
    result_json TEXT,
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    completed_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_jobs_job_id
    ON ai_edit_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_jobs_merchant_status
    ON ai_edit_jobs(merchant_id, status);

-- 6.2 AI 剪辑产物（只存内部 storage_key，禁止保存绝对路径）
CREATE TABLE IF NOT EXISTS ai_edit_job_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    job_id VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(64) NOT NULL,
    artifact_type VARCHAR(32),
    storage_key VARCHAR(255),
    file_name VARCHAR(255),
    mime_type VARCHAR(64),
    file_size_bytes INTEGER,
    created_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_job_artifacts_artifact_id
    ON ai_edit_job_artifacts(artifact_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_job_artifacts_merchant_job
    ON ai_edit_job_artifacts(merchant_id, job_id);

-- ---------------------------------------------------------------------------
-- 7. 固定 seed（全部用 INSERT INTO ... SELECT ... WHERE NOT EXISTS 幂等写入）
-- ---------------------------------------------------------------------------

-- 7.1 违禁词库 3 类
INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order, created_at, updated_at)
SELECT 'used_car_sales_base', '二手车销售基础违禁词', '二手车销售场景通用违禁词库', 'global', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order, created_at, updated_at)
SELECT 'finance_compliance', '金融方案合规词库', '金融方案承诺相关合规词库', 'global', 1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order, created_at, updated_at)
SELECT 'vehicle_condition_risk', '车况承诺风险词', '车况承诺相关风险词库', 'global', 1, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk');

-- 7.2 回访提示词 3 类
INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order, created_at, updated_at)
SELECT 'retain_contact_conversion', '留资转化回访', 'retain_conversion', '留资客户转化回访话术模板', 'global', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'retain_contact_conversion');

INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order, created_at, updated_at)
SELECT 'finance_plan_followup', '金融方案回访', 'finance_followup', '金融方案跟进回访话术模板', 'global', 1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'finance_plan_followup');

INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order, created_at, updated_at)
SELECT 'silent_customer_wakeup', '沉默客户唤醒', 'wakeup', '沉默客户唤醒回访话术模板', 'global', 1, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'silent_customer_wakeup');

-- 7.3 算力套餐 3 个（幂等 seed）
INSERT INTO compute_packages (name, price_yuan, token_amount, enabled, created_at, updated_at)
SELECT '基础版', 99, 100000, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '基础版');

INSERT INTO compute_packages (name, price_yuan, token_amount, enabled, created_at, updated_at)
SELECT '标准版', 299, 350000, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '标准版');

INSERT INTO compute_packages (name, price_yuan, token_amount, enabled, created_at, updated_at)
SELECT '专业版', 699, 900000, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '专业版');

-- 7.4 算力上浮能力 6 个（markup_basis_points 默认 0 基点 = 不上浮，由业务阶段配置）
INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'douyin-cs', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'douyin-cs');

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'leads', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'leads');

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'agents', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'agents');

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'wechat-assistant', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'wechat-assistant');

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'compute', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'compute');

INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at)
SELECT 'knowledge', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'knowledge');
