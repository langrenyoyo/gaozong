-- 0032 downgrade：回退 Phase 12 AI 剪辑本地 MVP（恢复 0031 列集与四新表清理）
-- ============================================================================
-- 由 downgrade runner 以 executescript 直执（不经 apply_migration），脚本自带事务。
-- 安全模式（仿 0031 upgrade/downgrade，对称）：
--   * 前置守卫：ai_edit_jobs(24 列)/ai_edit_job_artifacts(16 列)精确列集匹配 0032 升级态
--     （pragma_table_xinfo 覆盖生成列，拒绝未升级/部分升级/列漂移），
--     max(version_num)='0032' 拒绝越序降级（存在 0033+ 时阻断）。
--   * 单事务安全重建两壳表：RENAME 正式→_down 备份 → CREATE _new_down（0031 形态，
--     无 Phase 12 列/CHECK）→ INSERT SELECT → 多重集守卫 → DROP 备份 →
--     RENAME _new_down→正式 → 重建索引/唯一约束。
--   * DROP 四张 Phase 12 新表；删除 schema_migrations 中 0032 登记。
-- ============================================================================

BEGIN;

-- 0. 前置守卫：已完整升级 + head 精确为 0032
CREATE TEMP TABLE _guard_down_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 0.1 ai_edit_jobs 列数精确为 24（11 基线 + 13 新列，确认已完整升级）
INSERT INTO _guard_down_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_jobs')
) = 24 THEN 1 ELSE 0 END;

-- 0.2 ai_edit_jobs 24 列名都在且 hidden=0
INSERT INTO _guard_down_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_jobs')
    WHERE name IN ('id','merchant_id','job_id','status','source_type',
                   'input_json','result_json','error_message',
                   'created_at','updated_at','completed_at',
                   'stage','progress','agent_client_id','attempt_count',
                   'execution_token_hash','cancel_requested_at','heartbeat_at',
                   'input_fingerprint','engine_version','template_version',
                   'model_version','failure_code','error_summary')
                   AND hidden = 0
) = 24 THEN 1 ELSE 0 END;

-- 0.3 ai_edit_job_artifacts 列数精确为 16（10 基线 + 6 新列）
INSERT INTO _guard_down_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_job_artifacts')
) = 16 THEN 1 ELSE 0 END;

-- 0.4 ai_edit_job_artifacts 16 列名都在且 hidden=0
INSERT INTO _guard_down_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_job_artifacts')
    WHERE name IN ('id','merchant_id','job_id','artifact_id','artifact_type',
                   'storage_key','file_name','mime_type','file_size_bytes','created_at',
                   'location_type','agent_client_id','content_sha256',
                   'media_profile_json','integrity_status','source_artifact_id')
                   AND hidden = 0
) = 16 THEN 1 ELSE 0 END;

-- 0.5 head 精确为 0032（拒绝越序降级：存在 0033+ 时阻断）
INSERT INTO _guard_down_0032 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0032' THEN 1 ELSE 0 END;

DROP TABLE _guard_down_0032;

-- ---------------------------------------------------------------------------
-- 1. ai_edit_jobs（恢复 0031 形态：11 列，无 Phase 12 列/CHECK，数据不丢）
-- ---------------------------------------------------------------------------
ALTER TABLE ai_edit_jobs RENAME TO _ai_edit_jobs_down_0032;

CREATE TABLE _ai_edit_jobs_new_down_0032 (
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

INSERT INTO _ai_edit_jobs_new_down_0032 (
    id, merchant_id, job_id, status, source_type,
    input_json, result_json, error_message,
    created_at, updated_at, completed_at
)
SELECT
    id, merchant_id, job_id, status, source_type,
    input_json, result_json, error_message,
    created_at, updated_at, completed_at
FROM _ai_edit_jobs_down_0032;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 旧 11 列 COUNT EXCEPT
CREATE TEMP TABLE _guard_jobs_down_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_jobs_down_0032 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_jobs_new_down_0032) =
    (SELECT count(*) FROM _ai_edit_jobs_down_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_down_0032 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_jobs_new_down_0032) IS
    (SELECT max(id) FROM _ai_edit_jobs_down_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_down_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_new_down_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
    EXCEPT
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_down_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_down_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_down_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
    EXCEPT
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_new_down_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_jobs_down_0032;
ALTER TABLE _ai_edit_jobs_new_down_0032 RENAME TO ai_edit_jobs;
DROP TABLE _guard_jobs_down_0032;

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_jobs_job_id
    ON ai_edit_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_jobs_merchant_status
    ON ai_edit_jobs(merchant_id, status);

-- ---------------------------------------------------------------------------
-- 2. ai_edit_job_artifacts（恢复 0031 形态：10 列，数据不丢）
-- ---------------------------------------------------------------------------
ALTER TABLE ai_edit_job_artifacts RENAME TO _ai_edit_job_artifacts_down_0032;

CREATE TABLE _ai_edit_job_artifacts_new_down_0032 (
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

INSERT INTO _ai_edit_job_artifacts_new_down_0032 (
    id, merchant_id, job_id, artifact_id, artifact_type,
    storage_key, file_name, mime_type, file_size_bytes, created_at
)
SELECT
    id, merchant_id, job_id, artifact_id, artifact_type,
    storage_key, file_name, mime_type, file_size_bytes, created_at
FROM _ai_edit_job_artifacts_down_0032;

CREATE TEMP TABLE _guard_arts_down_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_arts_down_0032 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_job_artifacts_new_down_0032) =
    (SELECT count(*) FROM _ai_edit_job_artifacts_down_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_down_0032 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_job_artifacts_new_down_0032) IS
    (SELECT max(id) FROM _ai_edit_job_artifacts_down_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_down_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_new_down_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
    EXCEPT
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_down_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_down_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_down_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
    EXCEPT
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_new_down_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_job_artifacts_down_0032;
ALTER TABLE _ai_edit_job_artifacts_new_down_0032 RENAME TO ai_edit_job_artifacts;
DROP TABLE _guard_arts_down_0032;

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_job_artifacts_artifact_id
    ON ai_edit_job_artifacts(artifact_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_job_artifacts_merchant_job
    ON ai_edit_job_artifacts(merchant_id, job_id);

-- ---------------------------------------------------------------------------
-- 3. 删除四张 Phase 12 新表（先删带索引的依赖表，再删主表）
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS ai_edit_job_materials;
DROP TABLE IF EXISTS ai_edit_material_analyses;
DROP TABLE IF EXISTS ai_edit_templates;
DROP TABLE IF EXISTS ai_edit_materials;

-- ---------------------------------------------------------------------------
-- 4. 删除 0032 版本登记
-- ---------------------------------------------------------------------------
DELETE FROM schema_migrations WHERE version_num = '0032';

COMMIT;
