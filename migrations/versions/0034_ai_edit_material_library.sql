-- 0034 AI 素材库真实闭环增强：扩展 ai_edit_materials 12 列 + 新建 ai_edit_material_processes。
-- 执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
-- Task 12-2 Step 2。
--
-- 完全沿用 0033 的 rename+rebuild+双向 EXCEPT 模式，保证旧 17 列数据无损：
-- 1. guard：当前 head==0033、无重复 (merchant_id, source_sha256)、ai_edit_materials 17 普通列无隐藏列、
--    ai_edit_material_analyses 9 普通列不变（防实现窗口擅自扩快照表）。
-- 2. 重建 ai_edit_materials 为 29 列（17 旧 + 12 新），新增 purge 配对 CHECK 与 (merchant_id, source_sha256) 唯一约束。
-- 3. 逐列复制旧 17 列，12 个新列保持 NULL。
-- 4. 双向 EXCEPT + 行数守卫证明无损。
-- 5. 新建 ai_edit_material_processes（五阶段状态机，execution_token_hash 只存 SHA-256）。
-- 6. 重建既有索引 + 新唯一约束。

CREATE TEMP TABLE _guard_0034 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 1.1 无重复 (merchant_id, source_sha256)：有重复时拒绝升级，防静默合并历史行。
INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM ai_edit_materials
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id, source_sha256
    HAVING count(*) > 1
) THEN 1 ELSE 0 END;

-- 1.2 当前 head 必须精确为 0033。
INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0033' THEN 1 ELSE 0 END;

-- 1.3 ai_edit_materials 必须为 0033 的 17 个普通列、无隐藏列。
INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_materials')
) = 17 THEN 1 ELSE 0 END;

INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_materials')
    WHERE name IN (
        'id','material_id','merchant_id','scope','media_type','storage_mode',
        'agent_client_id','source_sha256','parent_material_id','thumbnail_storage_key',
        'cloud_storage_key','analysis_status','stabilization_status','deleted_at',
        'purge_after','created_at','updated_at'
    ) AND hidden = 0
) = 17 THEN 1 ELSE 0 END;

INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM pragma_table_xinfo('ai_edit_materials') WHERE hidden <> 0
) THEN 1 ELSE 0 END;

-- 1.4 ai_edit_material_analyses 必须保持 0032 建立的 9 列不变，防擅自扩快照表。
INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_material_analyses')
    WHERE name IN (
        'id','material_id','source_sha256','analysis_version',
        'transcript_json','scenes_json','tags_json','usable_ranges_json','created_at'
    ) AND hidden = 0
) = 9 THEN 1 ELSE 0 END;

DROP TABLE _guard_0034;

-- 2. 重建 ai_edit_materials 为 29 列。
ALTER TABLE ai_edit_materials RENAME TO _ai_edit_materials_backup_0034;

CREATE TABLE _ai_edit_materials_new_0034 (
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
    -- Task 12 新增 12 列
    display_name VARCHAR(255),
    description TEXT,
    category VARCHAR(32),
    duration_seconds FLOAT,
    width INTEGER,
    height INTEGER,
    fps FLOAT,
    file_size_bytes BIGINT,
    manual_override_json TEXT,
    manual_confirmed_at DATETIME,
    purge_operation_id VARCHAR(64),
    purge_status VARCHAR(16),
    CHECK (scope IN ('merchant', 'platform')),
    CHECK (storage_mode IN ('local_only', 'uploading', 'cloud_available', 'local_missing')),
    CONSTRAINT ck_ai_edit_materials_purge_status
        CHECK (purge_status IS NULL OR purge_status IN ('preparing','completed')),
    CONSTRAINT ck_ai_edit_materials_purge_pair
        CHECK (
            (purge_status IS NULL AND purge_operation_id IS NULL) OR
            (purge_status IS NOT NULL AND purge_operation_id IS NOT NULL)
        )
);

-- 3. 逐列复制旧 17 列，12 个新列保持 NULL。
INSERT INTO _ai_edit_materials_new_0034 (
    id, material_id, merchant_id, scope, media_type, storage_mode,
    agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
    cloud_storage_key, analysis_status, stabilization_status, deleted_at,
    purge_after, created_at, updated_at
)
SELECT
    id, material_id, merchant_id, scope, media_type, storage_mode,
    agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
    cloud_storage_key, analysis_status, stabilization_status, deleted_at,
    purge_after, created_at, updated_at
FROM _ai_edit_materials_backup_0034;

-- 4. 双向 EXCEPT + 行数守卫证明旧 17 列无损。
CREATE TEMP TABLE _guard_am_0034 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_am_0034 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_materials_new_0034) =
    (SELECT count(*) FROM _ai_edit_materials_backup_0034)
THEN 1 ELSE 0 END;

INSERT INTO _guard_am_0034 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_materials_new_0034) IS
    (SELECT max(id) FROM _ai_edit_materials_backup_0034)
THEN 1 ELSE 0 END;

INSERT INTO _guard_am_0034 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_new_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
    EXCEPT
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_backup_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_am_0034 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_backup_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
    EXCEPT
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_new_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_materials_backup_0034;
ALTER TABLE _ai_edit_materials_new_0034 RENAME TO ai_edit_materials;
DROP TABLE _guard_am_0034;

-- 5. 重建既有索引 + 新唯一约束。
CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_materials_material_id
    ON ai_edit_materials(material_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_merchant_scope
    ON ai_edit_materials(merchant_id, scope);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_sha256
    ON ai_edit_materials(source_sha256);
CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_materials_merchant_sha256
    ON ai_edit_materials(merchant_id, source_sha256);

-- 6. 新建素材分阶段处理状态表（五阶段状态机）。
CREATE TABLE IF NOT EXISTS ai_edit_material_processes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id VARCHAR(64) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    execution_token_hash VARCHAR(64) NOT NULL,
    failure_code VARCHAR(64),
    error_summary TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    updated_at DATETIME,
    CHECK (stage IN ('media_probe','transcript','content_analysis','stability','cloud_upload')),
    CHECK (status IN ('queued','running','succeeded','failed','not_required')),
    CHECK (progress BETWEEN 0 AND 100),
    CHECK (attempt_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_material_process_stage
    ON ai_edit_material_processes(material_id, source_sha256, stage);
