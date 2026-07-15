-- 0032 Phase 12 AI 剪辑本地 MVP 数据合同（设计 §10）
-- ============================================================================
-- 范围（只安全重建两张既有 AI 剪辑壳表 + 新建四张 Phase 12 表，不重写 seed）：
--   1. ai_edit_jobs：加 13 列任务壳扩展（stage/progress/agent_client_id/attempt_count/
--      execution_token_hash/cancel_requested_at/heartbeat_at/input_fingerprint/
--      engine_version/template_version/model_version/failure_code/error_summary）
--      + 两个 CHECK（progress 0..100 / attempt_count 非负，均可空）。
--   2. ai_edit_job_artifacts：加 6 列产物壳扩展（location_type/agent_client_id/
--      content_sha256/media_profile_json/integrity_status/source_artifact_id）。
--   3. 新建 ai_edit_materials / ai_edit_material_analyses / ai_edit_templates /
--      ai_edit_job_materials 四张表（唯一约束与 CHECK 与 ORM/PG 0013 三方一致）。
--
-- 安全模式（仿 0029/0030/0031）：
--   * 前置守卫：ai_edit_jobs(11 列)/ai_edit_job_artifacts(10 列)精确列集匹配 0027 基线
--     （pragma_table_xinfo 覆盖生成列，拒绝额外/缺失/部分升级列），max(version_num)='0031'
--     拒绝越序升级。任一失败触发 _guard CHECK 违反，runner 整体 ROLLBACK，不登记 0032。
--   * 每张壳表事务内重建（runner 已包裹 BEGIN/COMMIT，脚本不重复声明事务）：
--     RENAME 正式→_backup → CREATE _new（全列 + CHECK）
--     → INSERT SELECT（旧列复制，新列 NULL）→ _guard（行数 + max(id) + 双向 EXCEPT）
--     → DROP _backup → RENAME _new→正式 → 重建既有索引/唯一约束。
--   * 幂等：CREATE TABLE/INDEX 全部 IF NOT EXISTS；重建/守卫/RENAME 为 other 语句，
--     runner 已登记版本时整体跳过。
--
-- 边界：不兜底创建 0027 已有表；不写入设计 §10 禁止的本地路径列（仅 storage_key 相对键）；
--       JSON 列（transcript/scenes/tags/usable_ranges/rules/media_profile）由 service 层
--       经 Pydantic 严格 schema 序列化后写入，迁移不回填任意自由原文。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. 前置守卫（任一失败触发 _guard CHECK 违反，runner 整体 ROLLBACK，不登记 0032）
--    精确校验两壳表列集 == 0027 基线（拒绝额外/缺失/部分升级/生成列漂移）
--    + max(version_num)='0031' 拒绝越序升级（存在 0032+ 不可能，防跳级 0030 等基线）
-- ---------------------------------------------------------------------------

CREATE TEMP TABLE _guard_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 0.1 ai_edit_jobs 列数精确为 11（pragma_table_xinfo 覆盖生成列）
INSERT INTO _guard_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_jobs')
) = 11 THEN 1 ELSE 0 END;

-- 0.2 ai_edit_jobs 11 基线列名都在且 hidden=0（普通列，拒绝生成/隐藏列同名）
INSERT INTO _guard_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_jobs')
    WHERE name IN ('id','merchant_id','job_id','status','source_type',
                   'input_json','result_json','error_message',
                   'created_at','updated_at','completed_at')
                   AND hidden = 0
) = 11 THEN 1 ELSE 0 END;

-- 0.3 ai_edit_job_artifacts 列数精确为 10
INSERT INTO _guard_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_job_artifacts')
) = 10 THEN 1 ELSE 0 END;

-- 0.4 ai_edit_job_artifacts 10 基线列名都在且 hidden=0
INSERT INTO _guard_0032 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_job_artifacts')
    WHERE name IN ('id','merchant_id','job_id','artifact_id','artifact_type',
                   'storage_key','file_name','mime_type','file_size_bytes','created_at')
                   AND hidden = 0
) = 10 THEN 1 ELSE 0 END;

-- 0.5 head 精确为 0031（拒绝越序升级：未到 0031 或已存在 0032+ 都阻断）
INSERT INTO _guard_0032 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0031' THEN 1 ELSE 0 END;

DROP TABLE _guard_0032;

-- ---------------------------------------------------------------------------
-- 1. ai_edit_jobs（加 13 列 + 2 CHECK，旧行新列保持 NULL）
-- ---------------------------------------------------------------------------
ALTER TABLE ai_edit_jobs RENAME TO _ai_edit_jobs_backup_0032;

CREATE TABLE _ai_edit_jobs_new_0032 (
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
    completed_at DATETIME,
    stage VARCHAR(32),
    progress INTEGER,
    agent_client_id VARCHAR(128),
    attempt_count INTEGER,
    execution_token_hash VARCHAR(128),
    cancel_requested_at DATETIME,
    heartbeat_at DATETIME,
    input_fingerprint VARCHAR(128),
    engine_version VARCHAR(64),
    template_version VARCHAR(64),
    model_version VARCHAR(64),
    failure_code VARCHAR(64),
    error_summary TEXT,
    CHECK (progress IS NULL OR (progress BETWEEN 0 AND 100)),
    CHECK (attempt_count IS NULL OR attempt_count >= 0)
);

INSERT INTO _ai_edit_jobs_new_0032 (
    id, merchant_id, job_id, status, source_type,
    input_json, result_json, error_message,
    created_at, updated_at, completed_at,
    stage, progress, agent_client_id, attempt_count, execution_token_hash,
    cancel_requested_at, heartbeat_at, input_fingerprint,
    engine_version, template_version, model_version,
    failure_code, error_summary
)
SELECT
    id, merchant_id, job_id, status, source_type,
    input_json, result_json, error_message,
    created_at, updated_at, completed_at,
    NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL,
    NULL, NULL, NULL,
    NULL, NULL
FROM _ai_edit_jobs_backup_0032;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 旧 11 列 COUNT EXCEPT
CREATE TEMP TABLE _guard_jobs_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_jobs_0032 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_jobs_new_0032) =
    (SELECT count(*) FROM _ai_edit_jobs_backup_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_0032 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_jobs_new_0032) IS
    (SELECT max(id) FROM _ai_edit_jobs_backup_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_new_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
    EXCEPT
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_backup_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_jobs_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_backup_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
    EXCEPT
    SELECT id, merchant_id, job_id, status, source_type, input_json, result_json,
           error_message, created_at, updated_at, completed_at, count(*) AS cnt
    FROM _ai_edit_jobs_new_0032
    GROUP BY id, merchant_id, job_id, status, source_type, input_json, result_json,
             error_message, created_at, updated_at, completed_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_jobs_backup_0032;
ALTER TABLE _ai_edit_jobs_new_0032 RENAME TO ai_edit_jobs;
DROP TABLE _guard_jobs_0032;

-- 重建既有索引/唯一约束（RENAME 后旧索引随 _backup 删除）
CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_jobs_job_id
    ON ai_edit_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_jobs_merchant_status
    ON ai_edit_jobs(merchant_id, status);

-- ---------------------------------------------------------------------------
-- 2. ai_edit_job_artifacts（加 6 列产物壳扩展，旧行新列保持 NULL）
-- ---------------------------------------------------------------------------
ALTER TABLE ai_edit_job_artifacts RENAME TO _ai_edit_job_artifacts_backup_0032;

CREATE TABLE _ai_edit_job_artifacts_new_0032 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    job_id VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(64) NOT NULL,
    artifact_type VARCHAR(32),
    storage_key VARCHAR(255),
    file_name VARCHAR(255),
    mime_type VARCHAR(64),
    file_size_bytes INTEGER,
    created_at DATETIME,
    location_type VARCHAR(16),
    agent_client_id VARCHAR(128),
    content_sha256 VARCHAR(64),
    media_profile_json TEXT,
    integrity_status VARCHAR(32),
    source_artifact_id VARCHAR(64)
);

INSERT INTO _ai_edit_job_artifacts_new_0032 (
    id, merchant_id, job_id, artifact_id, artifact_type,
    storage_key, file_name, mime_type, file_size_bytes, created_at,
    location_type, agent_client_id, content_sha256,
    media_profile_json, integrity_status, source_artifact_id
)
SELECT
    id, merchant_id, job_id, artifact_id, artifact_type,
    storage_key, file_name, mime_type, file_size_bytes, created_at,
    NULL, NULL, NULL,
    NULL, NULL, NULL
FROM _ai_edit_job_artifacts_backup_0032;

-- 多重集守卫：行数 + max(id) + 双向 GROUP BY 旧 10 列 COUNT EXCEPT
CREATE TEMP TABLE _guard_arts_0032 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_arts_0032 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_job_artifacts_new_0032) =
    (SELECT count(*) FROM _ai_edit_job_artifacts_backup_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_0032 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_job_artifacts_new_0032) IS
    (SELECT max(id) FROM _ai_edit_job_artifacts_backup_0032)
THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_new_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
    EXCEPT
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_backup_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_arts_0032 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_backup_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
    EXCEPT
    SELECT id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
           file_name, mime_type, file_size_bytes, created_at, count(*) AS cnt
    FROM _ai_edit_job_artifacts_new_0032
    GROUP BY id, merchant_id, job_id, artifact_id, artifact_type, storage_key,
             file_name, mime_type, file_size_bytes, created_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_job_artifacts_backup_0032;
ALTER TABLE _ai_edit_job_artifacts_new_0032 RENAME TO ai_edit_job_artifacts;
DROP TABLE _guard_arts_0032;

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_job_artifacts_artifact_id
    ON ai_edit_job_artifacts(artifact_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_job_artifacts_merchant_job
    ON ai_edit_job_artifacts(merchant_id, job_id);

-- ---------------------------------------------------------------------------
-- 3. 新建四张 Phase 12 表（列/约束与 ORM app.models / PG 0013 三方一致）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai_edit_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id VARCHAR(64) NOT NULL,
    merchant_id VARCHAR(128),
    scope VARCHAR(16) NOT NULL,
    media_type VARCHAR(16) NOT NULL,
    storage_mode VARCHAR(32) NOT NULL,
    agent_client_id VARCHAR(128),
    source_sha256 VARCHAR(64) NOT NULL,
    parent_material_id VARCHAR(64),
    thumbnail_storage_key VARCHAR(255),
    cloud_storage_key VARCHAR(255),
    analysis_status VARCHAR(32) NOT NULL,
    stabilization_status VARCHAR(32) NOT NULL,
    deleted_at DATETIME,
    purge_after DATETIME,
    created_at DATETIME,
    updated_at DATETIME,
    CHECK (scope IN ('merchant', 'platform')),
    CHECK (storage_mode IN ('local_only', 'uploading', 'cloud_available', 'local_missing'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_materials_material_id
    ON ai_edit_materials(material_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_merchant_scope
    ON ai_edit_materials(merchant_id, scope);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_sha256
    ON ai_edit_materials(source_sha256);

CREATE TABLE IF NOT EXISTS ai_edit_material_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id VARCHAR(64) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    analysis_version VARCHAR(64) NOT NULL,
    transcript_json TEXT NOT NULL,
    scenes_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    usable_ranges_json TEXT NOT NULL,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_ai_edit_material_analyses_material
    ON ai_edit_material_analyses(material_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_material_analyses_sha256_version
    ON ai_edit_material_analyses(source_sha256, analysis_version);

CREATE TABLE IF NOT EXISTS ai_edit_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_key VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    rules_json TEXT NOT NULL,
    prompt_version VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_templates_template_key
    ON ai_edit_templates(template_key);

CREATE TABLE IF NOT EXISTS ai_edit_job_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id VARCHAR(64) NOT NULL,
    material_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    position INTEGER NOT NULL,
    pinned_sha256 VARCHAR(64) NOT NULL,
    source_start REAL,
    source_end REAL,
    created_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_job_materials_job_material_role_pos
    ON ai_edit_job_materials(job_id, material_id, role, position);
CREATE INDEX IF NOT EXISTS idx_ai_edit_job_materials_material
    ON ai_edit_job_materials(material_id);
