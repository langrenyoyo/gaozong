-- 0029 日报附件投递数据迁移（Phase 8-B）
-- ============================================================================
-- 范围：
--   1. 新增 daily_report_deliveries（artifact 快照 + 状态/attempt + 唯一约束/索引/size>0）。
--   2. wechat_tasks 事务内重建：加 14 个 Phase 8-B 扩展列（delivery 关联 + 四类令牌 hash
--      + attempt 文件元数据）+ FK(report_delivery_id) + UNIQUE(delivery_attempt)。
--      SQLite ALTER TABLE 不能加 FK/多列 UNIQUE，必须重建表。
--   3. wechat_tasks 历史遗留：SQLite 迁移体系（0001-0028）从未建此表，主线库由 ORM
--      create_all 建。本迁移用 CREATE TABLE IF NOT EXISTS 壳统一两种场景：
--      - 主线库（ORM 建的 wechat_tasks 存在）：CREATE IF NOT EXISTS skip → 重建加列。
--      - 纯迁移测试库（wechat_tasks 不存在）：CREATE IF NOT EXISTS 建旧版壳 → 重建加列。
-- 守卫：复用 0028 _guard 表 CHECK 模式（行数 + max(id) + 双向 GROUP BY 全旧业务列
--       COUNT EXCEPT），任一失败触发 CHECK 违反，整体 ROLLBACK，原表回 0029 前状态，
--       不登记 0029。
-- 幂等：CREATE TABLE/INDEX 全部 IF NOT EXISTS；重建/守卫/RENAME 为 other 语句，
--       runner 已登记版本时整体跳过。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. daily_report_deliveries（日报附件投递）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_report_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    report_job_id INTEGER NOT NULL,
    receiver_staff_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'held',
    artifact_storage_key VARCHAR(255),
    artifact_file_name VARCHAR(255),
    artifact_sha256 VARCHAR(64),
    artifact_size_bytes BIGINT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_failure_stage VARCHAR(100),
    delivered_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY (report_job_id) REFERENCES daily_report_jobs(id),
    FOREIGN KEY (receiver_staff_id) REFERENCES sales_staff(id),
    CHECK (artifact_size_bytes > 0),
    UNIQUE (report_job_id, receiver_staff_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_report_deliveries_merchant_status
    ON daily_report_deliveries(merchant_id, status);
CREATE INDEX IF NOT EXISTS idx_daily_report_deliveries_staff_status
    ON daily_report_deliveries(receiver_staff_id, status);

-- ---------------------------------------------------------------------------
-- 2. wechat_tasks 历史遗留壳（仅在表不存在时建旧版，统一后续重建入口）
--    SQLite 迁移体系从未建 wechat_tasks；主线库由 ORM create_all 建。
--    CREATE TABLE IF NOT EXISTS：存在则 skip（主线库），不存在则建壳（测试库）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wechat_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type VARCHAR(30) NOT NULL DEFAULT 'notify_sales',
    lead_id INTEGER REFERENCES douyin_leads(id),
    staff_id INTEGER REFERENCES sales_staff(id),
    reply_check_id INTEGER REFERENCES reply_checks(id),
    target_nickname VARCHAR(100),
    message TEXT,
    mode VARCHAR(20) NOT NULL DEFAULT 'paste_only',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_stage VARCHAR(100),
    raw_result TEXT,
    agent_hostname VARCHAR(100),
    agent_pid INTEGER,
    pasted_at DATETIME,
    sent_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);

-- ---------------------------------------------------------------------------
-- 3. wechat_tasks 事务内重建（加 Phase 8-B 扩展列 + FK + UNIQUE）
--    用 _new 中间表避开 runner plan 的 table_exists 提前规划（同 0028 模式）。
-- ---------------------------------------------------------------------------
-- 3.1 改名旧表为事务内备份（事务回滚则改名也撤销）
ALTER TABLE wechat_tasks RENAME TO _wechat_tasks_backup_0029;

-- 3.2 建中间表（完整 schema：旧 17 列 + Phase 8-B 14 新列 + FK + UNIQUE）
CREATE TABLE _wechat_tasks_new_0029 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type VARCHAR(30) NOT NULL DEFAULT 'notify_sales',
    lead_id INTEGER REFERENCES douyin_leads(id),
    staff_id INTEGER REFERENCES sales_staff(id),
    reply_check_id INTEGER REFERENCES reply_checks(id),
    target_nickname VARCHAR(100),
    message TEXT,
    mode VARCHAR(20) NOT NULL DEFAULT 'paste_only',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_stage VARCHAR(100),
    raw_result TEXT,
    agent_hostname VARCHAR(100),
    agent_pid INTEGER,
    pasted_at DATETIME,
    sent_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME,
    report_delivery_id INTEGER REFERENCES daily_report_deliveries(id),
    delivery_attempt_no INTEGER,
    execution_token_hash VARCHAR(64),
    execution_started_at DATETIME,
    download_ticket_hash VARCHAR(64),
    download_ticket_expires_at DATETIME,
    downloaded_at DATETIME,
    send_nonce_hash VARCHAR(64),
    send_nonce_expires_at DATETIME,
    send_authorized_at DATETIME,
    attachment_verified_at DATETIME,
    attachment_file_name VARCHAR(255),
    attachment_sha256 VARCHAR(64),
    attachment_size_bytes BIGINT,
    UNIQUE (report_delivery_id, delivery_attempt_no)
);

-- 3.3 复制旧数据（仅旧 17 列，新列默认 NULL）
INSERT INTO _wechat_tasks_new_0029 (
    id, task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
    mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
    pasted_at, sent_at, created_at, updated_at
)
SELECT
    id, task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
    mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
    pasted_at, sent_at, created_at, updated_at
FROM _wechat_tasks_backup_0029;

-- ---------------------------------------------------------------------------
-- 3.4 事务内多重集守卫：行数 + max(id) + 双向 GROUP BY 全旧业务列 COUNT EXCEPT。
--     任一比较返回 0 触发 _guard CHECK 违反，整体 ROLLBACK，原表回到 0029 前状态。
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _guard_wt_0029 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 行数守卫
INSERT INTO _guard_wt_0029 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _wechat_tasks_new_0029) =
    (SELECT count(*) FROM _wechat_tasks_backup_0029)
THEN 1 ELSE 0 END;

-- max(id) 守卫（确保 id 范围一致，复制未丢行或串行）
INSERT INTO _guard_wt_0029 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _wechat_tasks_new_0029) IS
    (SELECT max(id) FROM _wechat_tasks_backup_0029)
THEN 1 ELSE 0 END;

-- 正向多重集守卫：新表 EXCEPT 备份（GROUP BY 全旧业务列 + COUNT）
INSERT INTO _guard_wt_0029 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
           mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
           pasted_at, sent_at, created_at, updated_at, count(*) AS cnt
    FROM _wechat_tasks_new_0029
    GROUP BY task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
             mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
             pasted_at, sent_at, created_at, updated_at
    EXCEPT
    SELECT task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
           mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
           pasted_at, sent_at, created_at, updated_at, count(*) AS cnt
    FROM _wechat_tasks_backup_0029
    GROUP BY task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
             mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
             pasted_at, sent_at, created_at, updated_at
) THEN 1 ELSE 0 END;

-- 反向多重集守卫：备份 EXCEPT 新表
INSERT INTO _guard_wt_0029 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
           mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
           pasted_at, sent_at, created_at, updated_at, count(*) AS cnt
    FROM _wechat_tasks_backup_0029
    GROUP BY task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
             mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
             pasted_at, sent_at, created_at, updated_at
    EXCEPT
    SELECT task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
           mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
           pasted_at, sent_at, created_at, updated_at, count(*) AS cnt
    FROM _wechat_tasks_new_0029
    GROUP BY task_type, lead_id, staff_id, reply_check_id, target_nickname, message,
             mode, status, failure_stage, raw_result, agent_hostname, agent_pid,
             pasted_at, sent_at, created_at, updated_at
) THEN 1 ELSE 0 END;

-- 3.5 守卫全通过：删备份，改名新表为正式名
DROP TABLE _wechat_tasks_backup_0029;
ALTER TABLE _wechat_tasks_new_0029 RENAME TO wechat_tasks;

-- 3.6 清理守卫表
DROP TABLE _guard_wt_0029;
