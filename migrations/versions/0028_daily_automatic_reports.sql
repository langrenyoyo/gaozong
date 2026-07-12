-- 0028 每日自动报表数据迁移
-- ============================================================================
-- 范围：Phase 8-A 数据层结构，只做数据层，不接 service/router/前端/发送链路。
--   1. daily_report_jobs 增量字段（report_day/report_variant/diagnostics_json/
--      content_sha256/file_size_bytes/generation_version/generation_token/
--      generation_started_at/artifact_status）+ 新唯一约束 + report_day 索引。
--   2. 新增 3 张数据源表：lead_report_attributions、daily_ad_metrics、merchant_report_profiles。
--   3. sales_daily_summaries.summary_date 收敛 DATETIME -> DATE（重建表 + 多重集守卫）。
--   4. 不回填旧 daily_report_jobs.report_date；旧骨架行 report_day=NULL 不进入新 API。
--   5. seed 为零，不伪造广告/展厅数据。
-- 幂等：
--   - CREATE TABLE/INDEX 全部 IF NOT EXISTS。
--   - ALTER TABLE ADD COLUMN 由 runner 列存在检查跳过。
--   - 重建/守卫/RENAME 为 other 语句，runner 已登记版本时整体跳过。
-- 安全：
--   - runner 在 BEGIN 后、本文件第一条 DDL/DML 前调用 Phase 8 preflight，
--     非零点/折叠重复/业务键重复任一非 0 触发 ROLLBACK，不登记 0028。
--   - sales_daily_summaries 重建在单事务内完成：改名备份 -> 建 DATE 版 -> 复制 ->
--     多重集守卫（行数 + 双向 GROUP BY 全列 COUNT EXCEPT）-> 删备份；任一守卫失败
--     触发 _guard 表 CHECK 违反，整体 ROLLBACK，原表回到 0028 前状态。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. daily_report_jobs 增量字段（旧字段保留兼容，不删）
-- ---------------------------------------------------------------------------
ALTER TABLE daily_report_jobs ADD COLUMN report_day DATE;
ALTER TABLE daily_report_jobs ADD COLUMN report_variant VARCHAR(32) DEFAULT 'default';
ALTER TABLE daily_report_jobs ADD COLUMN diagnostics_json TEXT;
ALTER TABLE daily_report_jobs ADD COLUMN content_sha256 VARCHAR(64);
ALTER TABLE daily_report_jobs ADD COLUMN file_size_bytes BIGINT;
ALTER TABLE daily_report_jobs ADD COLUMN generation_version VARCHAR(32);
ALTER TABLE daily_report_jobs ADD COLUMN generation_token VARCHAR(64);
ALTER TABLE daily_report_jobs ADD COLUMN generation_started_at DATETIME;
ALTER TABLE daily_report_jobs ADD COLUMN artifact_status VARCHAR(16) NOT NULL DEFAULT 'none';

-- ---------------------------------------------------------------------------
-- 2. lead_report_attributions（线索报表归因）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lead_report_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    lead_id INTEGER NOT NULL,
    traffic_type VARCHAR(16) NOT NULL,
    content_type VARCHAR(16) NOT NULL,
    ad_id VARCHAR(128),
    material_id VARCHAR(128),
    trace_url VARCHAR(1000),
    source_system VARCHAR(32) NOT NULL,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY (lead_id) REFERENCES douyin_leads(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_lead_report_attributions_merchant_lead
    ON lead_report_attributions(merchant_id, lead_id);

-- ---------------------------------------------------------------------------
-- 3. daily_ad_metrics（付费投流聚合事实，不接受广告明细）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_ad_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    metric_day DATE NOT NULL,
    channel VARCHAR(32) NOT NULL,
    content_type VARCHAR(16) NOT NULL,
    spend_amount NUMERIC(14, 2) NOT NULL,
    private_message_count INTEGER NOT NULL,
    source_system VARCHAR(32) NOT NULL,
    created_at DATETIME,
    updated_at DATETIME,
    CHECK (channel = 'douyin'),
    CHECK (content_type IN ('short_video', 'live')),
    CHECK (spend_amount >= 0),
    CHECK (private_message_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_daily_ad_metrics_merchant_day_channel_content
    ON daily_ad_metrics(merchant_id, metric_day, channel, content_type);

-- ---------------------------------------------------------------------------
-- 4. merchant_report_profiles（展厅价位区间，两值同时空或同存在且 min<=max）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS merchant_report_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    showroom_price_min_yuan NUMERIC(14, 2),
    showroom_price_max_yuan NUMERIC(14, 2),
    created_at DATETIME,
    updated_at DATETIME,
    CHECK (
        (showroom_price_min_yuan IS NULL AND showroom_price_max_yuan IS NULL)
        OR
        (showroom_price_min_yuan IS NOT NULL AND showroom_price_max_yuan IS NOT NULL
         AND showroom_price_min_yuan >= 0
         AND showroom_price_max_yuan >= 0
         AND showroom_price_min_yuan <= showroom_price_max_yuan)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_merchant_report_profiles_merchant
    ON merchant_report_profiles(merchant_id);

-- ---------------------------------------------------------------------------
-- 5. daily_report_jobs 新唯一约束 + report_day 索引
--    旧 report_date 索引保留（Phase 1 已建，IF NOT EXISTS 不重复建）
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uk_daily_report_jobs_merchant_day_type_variant
    ON daily_report_jobs(merchant_id, report_day, report_type, report_variant);

CREATE INDEX IF NOT EXISTS idx_daily_report_jobs_merchant_status_day
    ON daily_report_jobs(merchant_id, status, report_day);

-- ---------------------------------------------------------------------------
-- 6. sales_daily_summaries.summary_date 收敛 DATETIME -> DATE（事务内重建）
-- ============================================================================
-- 用 _new 中间表避开 runner plan 的 table_exists 提前规划：
-- plan 在 apply 前一次性评估，此时 sales_daily_summaries 还存在（DATETIME 版），
-- 若直接 CREATE sales_daily_summaries（DATE）会被规划为 skipped(table_exists)。
-- 因此先建 _new（plan 时不存在），复制+守卫通过后 RENAME _new 为正式名。
-- ---------------------------------------------------------------------------
-- 6.1 改名旧表为事务内备份（事务回滚则改名也撤销）
ALTER TABLE sales_daily_summaries RENAME TO _sales_daily_summaries_backup_0028;

-- 6.2 建 DATE 版中间表（plan 时不存在 → will_run）
CREATE TABLE _sales_daily_summaries_new_0028 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    staff_id INTEGER NOT NULL,
    summary_date DATE NOT NULL,
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

-- 6.3 复制数据（summary_date 用 date() 折叠到业务日；preflight 已确认全部零点）
INSERT INTO _sales_daily_summaries_new_0028 (
    id, merchant_id, staff_id, summary_date, sales_name, raw_text,
    overall_quality, main_problem, car_model_summary, budget_summary,
    cooperation_level, today_suggestion, extra_feedback,
    parse_status, parse_error, created_at, updated_at
)
SELECT
    id, merchant_id, staff_id, date(summary_date), sales_name, raw_text,
    overall_quality, main_problem, car_model_summary, budget_summary,
    cooperation_level, today_suggestion, extra_feedback,
    parse_status, parse_error, created_at, updated_at
FROM _sales_daily_summaries_backup_0028;

-- ---------------------------------------------------------------------------
-- 6.4 事务内多重集守卫：行数 + max(id) + 双向 GROUP BY 全列 COUNT EXCEPT。
--     守卫表 _guard_summary_0028 只接受 ok=1；任一比较返回 0 触发 CHECK 违反，
--     整体 ROLLBACK，原表回到 0028 前状态（改名也撤销）。
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _guard_summary_0028 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 行数守卫
INSERT INTO _guard_summary_0028 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _sales_daily_summaries_new_0028) =
    (SELECT count(*) FROM _sales_daily_summaries_backup_0028)
THEN 1 ELSE 0 END;

-- max(id) 守卫（确保 id 范围一致，复制未丢行或串行）
INSERT INTO _guard_summary_0028 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _sales_daily_summaries_new_0028) IS
    (SELECT max(id) FROM _sales_daily_summaries_backup_0028)
THEN 1 ELSE 0 END;

-- 正向多重集守卫：新表 EXCEPT 备份投影（GROUP BY 全迁移列 + COUNT）
INSERT INTO _guard_summary_0028 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT merchant_id, staff_id, summary_date, sales_name, raw_text,
           overall_quality, main_problem, car_model_summary, budget_summary,
           cooperation_level, today_suggestion, extra_feedback,
           parse_status, parse_error, created_at, updated_at, count(*) AS cnt
    FROM _sales_daily_summaries_new_0028
    GROUP BY merchant_id, staff_id, summary_date, sales_name, raw_text,
             overall_quality, main_problem, car_model_summary, budget_summary,
             cooperation_level, today_suggestion, extra_feedback,
             parse_status, parse_error, created_at, updated_at
    EXCEPT
    SELECT merchant_id, staff_id, date(summary_date) AS summary_date, sales_name, raw_text,
           overall_quality, main_problem, car_model_summary, budget_summary,
           cooperation_level, today_suggestion, extra_feedback,
           parse_status, parse_error, created_at, updated_at, count(*) AS cnt
    FROM _sales_daily_summaries_backup_0028
    GROUP BY merchant_id, staff_id, date(summary_date), sales_name, raw_text,
             overall_quality, main_problem, car_model_summary, budget_summary,
             cooperation_level, today_suggestion, extra_feedback,
             parse_status, parse_error, created_at, updated_at
) THEN 1 ELSE 0 END;

-- 反向多重集守卫：备份投影 EXCEPT 新表
INSERT INTO _guard_summary_0028 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT merchant_id, staff_id, date(summary_date) AS summary_date, sales_name, raw_text,
           overall_quality, main_problem, car_model_summary, budget_summary,
           cooperation_level, today_suggestion, extra_feedback,
           parse_status, parse_error, created_at, updated_at, count(*) AS cnt
    FROM _sales_daily_summaries_backup_0028
    GROUP BY merchant_id, staff_id, date(summary_date), sales_name, raw_text,
             overall_quality, main_problem, car_model_summary, budget_summary,
             cooperation_level, today_suggestion, extra_feedback,
             parse_status, parse_error, created_at, updated_at
    EXCEPT
    SELECT merchant_id, staff_id, summary_date, sales_name, raw_text,
           overall_quality, main_problem, car_model_summary, budget_summary,
           cooperation_level, today_suggestion, extra_feedback,
           parse_status, parse_error, created_at, updated_at, count(*) AS cnt
    FROM _sales_daily_summaries_new_0028
    GROUP BY merchant_id, staff_id, summary_date, sales_name, raw_text,
             overall_quality, main_problem, car_model_summary, budget_summary,
             cooperation_level, today_suggestion, extra_feedback,
             parse_status, parse_error, created_at, updated_at
) THEN 1 ELSE 0 END;

-- ---------------------------------------------------------------------------
-- 6.5 守卫全部通过：删备份，改名新表为正式名，重建索引
-- ---------------------------------------------------------------------------
DROP TABLE _sales_daily_summaries_backup_0028;
ALTER TABLE _sales_daily_summaries_new_0028 RENAME TO sales_daily_summaries;

CREATE UNIQUE INDEX IF NOT EXISTS uk_sales_daily_summaries_merchant_staff_date
    ON sales_daily_summaries(merchant_id, staff_id, summary_date);
CREATE INDEX IF NOT EXISTS idx_sales_daily_summaries_merchant_date
    ON sales_daily_summaries(merchant_id, summary_date);

-- 6.6 清理守卫表
DROP TABLE _guard_summary_0028;
