-- 0034 回滚：恢复 ai_edit_materials 为 0033 的 17 列，删除 ai_edit_material_processes。
-- 执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
-- Task 12-2 Step 2。
--
-- 安全保护：
-- - head 必须精确为 0034；ai_edit_material_analyses 始终保持 9 列不变。
-- - 在任何 DROP/RENAME 前用 guard 查询 purge_status IS NOT NULL：
--   存在 preparing 或 completed 都让 CHECK 失败并整体回滚，防丢失删除 claim 与 finalize 重放能力。

BEGIN;

CREATE TEMP TABLE _guard_down_0034 (ok INTEGER NOT NULL CHECK (ok = 1));

-- 1.1 当前 head 必须精确为 0034。
INSERT INTO _guard_down_0034 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0034' THEN 1 ELSE 0 END;

-- 1.2 ai_edit_materials 必须为 0034 的 29 个普通列。
INSERT INTO _guard_down_0034 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_materials')
) = 29 THEN 1 ELSE 0 END;

-- 1.3 ai_edit_material_analyses 必须仍为 9 列（降级不动快照表）。
INSERT INTO _guard_down_0034 (ok)
SELECT CASE WHEN (
    SELECT count(*) FROM pragma_table_xinfo('ai_edit_material_analyses')
    WHERE name IN (
        'id','material_id','source_sha256','analysis_version',
        'transcript_json','scenes_json','tags_json','usable_ranges_json','created_at'
    ) AND hidden = 0
) = 9 THEN 1 ELSE 0 END;

-- 1.4 永久删除 claim 保护：存在 preparing/completed tombstone 时拒绝降级。
INSERT INTO _guard_down_0034 (ok)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ai_edit_materials WHERE purge_status IS NOT NULL
) THEN 1 ELSE 0 END;

DROP TABLE _guard_down_0034;

-- 2. 重建 ai_edit_materials 为 0033 的 17 列。
ALTER TABLE ai_edit_materials RENAME TO _ai_edit_materials_down_0034;

CREATE TABLE _ai_edit_materials_new_down_0034 (
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

INSERT INTO _ai_edit_materials_new_down_0034 (
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
FROM _ai_edit_materials_down_0034;

-- 3. 双向 EXCEPT + 行数守卫证明旧 17 列无损。
CREATE TEMP TABLE _guard_am_down_0034 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_am_down_0034 (ok)
SELECT CASE WHEN
    (SELECT count(*) FROM _ai_edit_materials_new_down_0034) =
    (SELECT count(*) FROM _ai_edit_materials_down_0034)
THEN 1 ELSE 0 END;

INSERT INTO _guard_am_down_0034 (ok)
SELECT CASE WHEN
    (SELECT max(id) FROM _ai_edit_materials_new_down_0034) IS
    (SELECT max(id) FROM _ai_edit_materials_down_0034)
THEN 1 ELSE 0 END;

INSERT INTO _guard_am_down_0034 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_new_down_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
    EXCEPT
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_down_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
) THEN 1 ELSE 0 END;

INSERT INTO _guard_am_down_0034 (ok)
SELECT CASE WHEN NOT EXISTS(
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_down_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
    EXCEPT
    SELECT id, material_id, merchant_id, scope, media_type, storage_mode,
           agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
           cloud_storage_key, analysis_status, stabilization_status, deleted_at,
           purge_after, created_at, updated_at, count(*) AS cnt
    FROM _ai_edit_materials_new_down_0034
    GROUP BY id, material_id, merchant_id, scope, media_type, storage_mode,
             agent_client_id, source_sha256, parent_material_id, thumbnail_storage_key,
             cloud_storage_key, analysis_status, stabilization_status, deleted_at,
             purge_after, created_at, updated_at
) THEN 1 ELSE 0 END;

DROP TABLE _ai_edit_materials_down_0034;
ALTER TABLE _ai_edit_materials_new_down_0034 RENAME TO ai_edit_materials;
DROP TABLE _guard_am_down_0034;

-- 4. 重建 0033 既有索引，删除 0034 新增唯一约束与过程表。
CREATE UNIQUE INDEX IF NOT EXISTS uk_ai_edit_materials_material_id
    ON ai_edit_materials(material_id);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_merchant_scope
    ON ai_edit_materials(merchant_id, scope);
CREATE INDEX IF NOT EXISTS idx_ai_edit_materials_sha256
    ON ai_edit_materials(source_sha256);

DROP INDEX IF EXISTS uk_ai_edit_materials_merchant_sha256;
DROP TABLE IF EXISTS ai_edit_material_processes;

DELETE FROM schema_migrations WHERE version_num = '0034';

COMMIT;
