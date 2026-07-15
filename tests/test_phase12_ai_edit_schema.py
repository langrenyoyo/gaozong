"""Phase 12 AI 剪辑本地 MVP 数据合同测试（Task 1 红灯）。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 1。
冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10。

锁定（Task 2 实现后全部通过）：
- 四张新表注册到 Base.metadata：ai_edit_materials / ai_edit_material_analyses /
  ai_edit_templates / ai_edit_job_materials。
- AiEditJob 任务壳扩展 13 列（设计 §10：阶段/进度/设备/attempt/执行令牌/取消/心跳/
  输入指纹/引擎·模板·模型版本/稳定失败码/错误摘要），progress 0..100、attempt_count>=0 CHECK。
- AiEditJobArtifact 产物壳扩展 6 列（设计 §10：位置类型/设备/SHA-256/媒体属性/完整性/来源产物）。
- AiEditMaterial.scope in ('merchant','platform')、storage_mode 四态 CHECK。
- material_id / template_key / (job_id+material_id+role+position) 唯一约束。
- 9000 全表禁止 absolute_path/source_path/local_path 列。
- SQLite 0032 upgrade + 独立 downgrade 文件存在；只安全重建 ai_edit_jobs/artifacts
  两表 + 新建四表，不兜底建其他业务表。
- 升级前后旧列多重集一致、历史行不丢；守卫失败整体回滚不留中间表。
- downgrade 恢复 0031 列集、新表删除、删除 0032 登记，随后可再次 upgrade；
  越序降级（存在 0033+）必须拒绝。

Task 1 红灯：ORM 新表/列/约束及 0032 文件均未实现，合同断言 FAIL；
迁移行为测试在文件存在前 SKIP（避免 ERROR 噪音）。
红灯只来自被测对象缺失，不来自测试语法、导入或 fixture 错误。
只使用 tmp_path 临时 SQLite，不连接任何生产/开发库。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
SQLITE_DOWNGRADES = ROOT / "migrations" / "downgrades"

SQLITE_FILE_PHASE12 = SQLITE_VERSIONS / "0032_ai_edit_local_mvp.sql"
SQLITE_DOWNGRADE_PHASE12 = SQLITE_DOWNGRADES / "0032_ai_edit_local_mvp.sql"

# Phase 12 四张新表
EXPECTED_TABLES = {
    "ai_edit_materials",
    "ai_edit_material_analyses",
    "ai_edit_templates",
    "ai_edit_job_materials",
}

# AiEditJob 任务壳扩展列（执行包 Task 2 Step 1 + 设计 §10）
AI_EDIT_JOB_NEW_COLUMNS = {
    "stage", "progress", "agent_client_id", "attempt_count",
    "execution_token_hash", "cancel_requested_at", "heartbeat_at",
    "input_fingerprint", "engine_version", "template_version",
    "model_version", "failure_code", "error_summary",
}

# AiEditJobArtifact 产物壳扩展列（设计 §10：位置/设备/SHA-256/媒体属性/完整性/来源产物）
AI_EDIT_ARTIFACT_NEW_COLUMNS = {
    "location_type",
    "agent_client_id",
    "content_sha256",
    "media_profile_json",
    "integrity_status",
    "source_artifact_id",
}

# 9000 schema 禁止出现的绝对路径列名
FORBIDDEN_PATH_COLUMNS = {"absolute_path", "source_path", "local_path"}

# 0031 时点 ai_edit_jobs / ai_edit_job_artifacts 精确列集
# （0027 建立，0028-0031 未触动两表，故 0031 head 即 0027 形态）
AI_EDIT_JOBS_BASELINE_0031 = {
    "id", "merchant_id", "job_id", "status", "source_type",
    "input_json", "result_json", "error_message",
    "created_at", "updated_at", "completed_at",
}
AI_EDIT_ARTIFACTS_BASELINE_0031 = {
    "id", "merchant_id", "job_id", "artifact_id", "artifact_type",
    "storage_key", "file_name", "mime_type", "file_size_bytes", "created_at",
}


def _has_check_mentioning(table, *keywords: str) -> bool:
    """表上是否存在 sqltext 同时包含所有关键词（小写）的 CheckConstraint。"""
    for const in table.constraints:
        if isinstance(const, CheckConstraint):
            text = str(const.sqltext).lower()
            if all(k.lower() in text for k in keywords):
                return True
    return False


# ---------------------------------------------------------------------------
# Step 1: ORM 红灯（不 skip；因新表/新列/新约束未实现而 FAIL）
# ---------------------------------------------------------------------------


def test_phase12_new_tables_declared_in_metadata():
    """四张新表必须注册到 Base.metadata。"""
    import app.models as models

    missing = EXPECTED_TABLES - set(models.Base.metadata.tables)
    assert not missing, f"Base.metadata 缺少 Phase 12 新表: {missing}"


def test_ai_edit_job_has_phase12_extension_columns():
    """AiEditJob 任务壳扩展 13 列。"""
    import app.models as models

    cols = set(models.AiEditJob.__table__.columns.keys())
    missing = AI_EDIT_JOB_NEW_COLUMNS - cols
    assert not missing, f"AiEditJob 缺少 Phase 12 扩展列: {missing}"


def test_ai_edit_job_progress_range_check():
    """progress 必须 CHECK 0..100。"""
    import app.models as models

    assert _has_check_mentioning(models.AiEditJob.__table__, "progress", "100"), (
        "AiEditJob 缺少 progress (0..100) CHECK"
    )


def test_ai_edit_job_attempt_count_nonnegative_check():
    """attempt_count 必须 CHECK >= 0。"""
    import app.models as models

    assert _has_check_mentioning(models.AiEditJob.__table__, "attempt_count"), (
        "AiEditJob 缺少 attempt_count 非负 CHECK"
    )


def test_ai_edit_artifact_has_phase12_extension_columns():
    """AiEditJobArtifact 产物壳扩展 6 列。"""
    import app.models as models

    cols = set(models.AiEditJobArtifact.__table__.columns.keys())
    missing = AI_EDIT_ARTIFACT_NEW_COLUMNS - cols
    assert not missing, f"AiEditJobArtifact 缺少 Phase 12 扩展列: {missing}"


def test_ai_edit_material_scope_check():
    """AiEditMaterial.scope 必须 CHECK in ('merchant','platform')。"""
    import app.models as models

    tbl = models.Base.metadata.tables.get("ai_edit_materials")
    assert tbl is not None, "ai_edit_materials 表未声明"
    assert _has_check_mentioning(tbl, "merchant", "platform"), (
        "AiEditMaterial.scope 缺少 merchant/platform CHECK"
    )


def test_ai_edit_material_storage_mode_check():
    """AiEditMaterial.storage_mode 必须 CHECK 四态。"""
    import app.models as models

    tbl = models.Base.metadata.tables.get("ai_edit_materials")
    assert tbl is not None, "ai_edit_materials 表未声明"
    assert _has_check_mentioning(
        tbl, "local_only", "uploading", "cloud_available", "local_missing"
    ), "AiEditMaterial.storage_mode 缺少四态 CHECK"


def test_phase12_unique_constraints_declared():
    """核心唯一约束：material_id / template_key / (job_id+material_id+role+position)。"""
    import app.models as models

    def _unique_groups(table_name: str) -> set[tuple[str, ...]]:
        tbl = models.Base.metadata.tables.get(table_name)
        if tbl is None:
            return set()
        return {
            tuple(sorted(col.name for col in const.columns))
            for const in tbl.constraints
            if isinstance(const, UniqueConstraint)
        }

    assert ("material_id",) in _unique_groups("ai_edit_materials"), (
        "ai_edit_materials 缺少 material_id 唯一约束"
    )
    assert ("template_key",) in _unique_groups("ai_edit_templates"), (
        "ai_edit_templates 缺少 template_key 唯一约束"
    )
    expected_jm = tuple(sorted(("job_id", "material_id", "role", "position")))
    assert expected_jm in _unique_groups("ai_edit_job_materials"), (
        "ai_edit_job_materials 缺少 (job_id,material_id,role,position) 唯一约束"
    )


def test_no_absolute_path_columns_in_9000_schema():
    """9000 所有表不得出现 absolute_path/source_path/local_path 列（设计 §10）。"""
    import app.models as models

    for table_name, table in models.Base.metadata.tables.items():
        bad = set(table.columns.keys()) & FORBIDDEN_PATH_COLUMNS
        assert not bad, f"表 {table_name} 出现禁止的绝对路径列: {bad}"


# ---------------------------------------------------------------------------
# 公共 Out 模型脱敏合同（设计 §10 第 227 行：外部 API 不返回 storage_key/
# merchant_id/执行令牌/绝对路径；检查点 A 安全+规范审查 BLOCKED 要求）
# ---------------------------------------------------------------------------

# 设计 §10：外部 API 不返回绝对路径、storage_key、执行令牌或 merchant_id
SENSITIVE_LEAK_FIELDS = {
    "storage_key",
    "merchant_id",
    "execution_token_hash",
    "absolute_path",
    "source_path",
    "local_path",
}

# Phase 12 对外公共响应模型（内部 ORM 可保留 merchant_id/storage_key，公共 Out 不得泄露）
PUBLIC_AI_EDIT_OUT_MODELS = (
    "AiEditJobOut",
    "AiEditJobArtifactOut",
    "AiEditMaterialOut",
    "AiEditMaterialAnalysisOut",
    "AiEditTemplateOut",
    "AiEditJobMaterialOut",
)


def test_phase12_public_out_models_exclude_sensitive_fields():
    """公共 Out 模型声明字段集不得含 storage_key/merchant_id/执行令牌/绝对路径。"""
    import app.schemas as schemas

    for name in PUBLIC_AI_EDIT_OUT_MODELS:
        Model = getattr(schemas, name)
        leaked = set(Model.model_fields.keys()) & SENSITIVE_LEAK_FIELDS
        assert not leaked, f"公共 Out 模型 {name} 泄露敏感字段: {leaked}"


def test_phase12_public_out_model_dump_excludes_sensitive_keys():
    """model_dump() 键集不得含敏感键（防 alias/序列化机制绕过字段集断言）。"""
    import app.schemas as schemas

    for name in PUBLIC_AI_EDIT_OUT_MODELS:
        Model = getattr(schemas, name)
        # model_construct 跳过类型校验，全字段填 None（兼容所有类型）后 dump，验证序列化键集
        filled = Model.model_construct(
            **{fname: None for fname in Model.model_fields}
        )
        leaked = set(filled.model_dump().keys()) & SENSITIVE_LEAK_FIELDS
        assert not leaked, f"公共 Out 模型 {name}.model_dump() 泄露敏感键: {leaked}"


# ---------------------------------------------------------------------------
# 迁移文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_phase12_sqlite_migration_files_exist():
    assert SQLITE_FILE_PHASE12.is_file(), (
        "SQLite 迁移 0032_ai_edit_local_mvp.sql 必须存在（versions 目录）"
    )
    assert SQLITE_DOWNGRADE_PHASE12.is_file(), (
        "SQLite 回滚 0032_ai_edit_local_mvp.sql 必须存在（downgrades 目录，独立不被 runner 发现）"
    )


# ---------------------------------------------------------------------------
# 0032 静态内容合同（文件存在前 SKIP）
# ---------------------------------------------------------------------------


def _content_0032() -> str:
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    return SQLITE_FILE_PHASE12.read_text(encoding="utf-8")


def test_sqlite_0032_creates_only_expected_new_tables():
    """0032 只建四张新表 + 安全重建中间表，不得兜底建其他业务表。"""
    import re

    content = _content_0032().upper()
    allowed_new = {t.upper() for t in EXPECTED_TABLES}
    created = re.findall(
        r"CREATE\s+(?:TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", content
    )
    for name in created:
        ok = name in allowed_new or "_NEW_0032" in name or "_GUARD" in name
        assert ok, f"0032 出现越界建表: {name.lower()}"


def test_sqlite_0032_no_absolute_path_columns():
    """0032 迁移不得写入绝对路径列。"""
    content = _content_0032().lower()
    for bad in ("absolute_path", "source_path", "local_path"):
        assert bad not in content, f"0032 迁移出现禁止的路径列: {bad}"


# ---------------------------------------------------------------------------
# SQLite apply/downgrade 行为测试（0032 未实现时 SKIP）
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """临时库前置表壳（与 test_phase10/test_phase9 一致）。

    真实迁移链不从空库自洽（0001 假设 douyin_leads 由 ORM create_all 预建），
    故用最小前置表 + 选择性 apply 关键版本构建 0032 前置状态。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, "
        "applied_at DATETIME NOT NULL, description VARCHAR(200));"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales_staff ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_reply_decision_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT);"
    )


def _apply_on_temp(conn, version: str):
    mig = next(m for m in migrate_sqlite.discover_migrations() if m.version == version)
    stmts = migrate_sqlite._load_stmts(mig.path)
    return migrate_sqlite.apply_migration(conn, stmts, mig.version, mig.description)


def _apply_phase12_0031_head(conn):
    """构建 0032 前置：0010（算力三表）→ 0027（ai_edit_jobs/artifacts + seed）→ 0031（算力快照）。

    ponytail: 复用 Phase 10 已验证的最小链；0028-0031 均不触碰 ai_edit_jobs/artifacts，
    此链后两表为精确 0027 列集（11/10 列）= 0031 时点基线，且 max(version_num)='0031'。
    如后续版本改动这两表则此假设失效，需补 apply 对应版本。
    """
    _create_phase1_predecessor_tables(conn)
    _apply_on_temp(conn, "0010")
    _apply_on_temp(conn, "0027")
    _apply_on_temp(conn, "0031")


def _seed_ai_edit_shell_rows(conn):
    """ai_edit_jobs / ai_edit_job_artifacts 各插一行，验证 0032 安全重建后行数不变。"""
    conn.execute(
        "INSERT INTO ai_edit_jobs "
        "(merchant_id, job_id, status, source_type, input_json, result_json, "
        " error_message, created_at, updated_at, completed_at) "
        "VALUES ('m1', 'job-seed-1', 'queued', 'manual', '{}', NULL, NULL, "
        "        '2026-07-15 00:00:00', '2026-07-15 00:00:00', NULL)"
    )
    conn.execute(
        "INSERT INTO ai_edit_job_artifacts "
        "(merchant_id, job_id, artifact_id, artifact_type, storage_key, "
        " file_name, mime_type, file_size_bytes, created_at) "
        "VALUES ('m1', 'job-seed-1', 'art-seed-1', 'preview', 'k1', "
        "        'p.mp4', 'video/mp4', 1024, '2026-07-15 00:00:00')"
    )


def _assert_0032_not_applied_and_clean(db_path):
    """守卫拒绝后的公共断言：0032 未登记、新表不存在、无中间表残留。"""
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0032'"
        ).fetchone()[0] == 0, "守卫失败场景 0032 不应登记"
        for t in EXPECTED_TABLES:
            assert not migrate_sqlite.table_exists(conn, t), (
                f"回滚后不应存在新表 {t}"
            )
        leftovers = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE '%_backup_0032%' OR name LIKE '%_new_0032%' "
                "OR name LIKE '%_down_0032%')"
            )
        ]
        assert not leftovers, f"回滚后残留中间表: {leftovers}"
    finally:
        conn.close()


def test_sqlite_0032_apply_adds_tables_and_columns(tmp_path):
    """apply 0032：四新表建成 + jobs/artifacts 扩展列出现 + 历史行保留 + 登记 0032。"""
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_apply.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        _seed_ai_edit_shell_rows(conn)
        result = _apply_on_temp(conn, "0032")
    finally:
        conn.close()

    assert result.already_applied is False
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        for t in EXPECTED_TABLES:
            assert migrate_sqlite.table_exists(conn, t), f"0032 后缺少新表 {t}"
        cols = migrate_sqlite.get_columns(conn, "ai_edit_jobs")
        assert AI_EDIT_JOB_NEW_COLUMNS <= cols, (
            f"ai_edit_jobs 缺少扩展列: {AI_EDIT_JOB_NEW_COLUMNS - cols}"
        )
        acols = migrate_sqlite.get_columns(conn, "ai_edit_job_artifacts")
        assert AI_EDIT_ARTIFACT_NEW_COLUMNS <= acols, (
            f"ai_edit_job_artifacts 缺少扩展列: {AI_EDIT_ARTIFACT_NEW_COLUMNS - acols}"
        )
        # 安全重建不丢历史行
        assert conn.execute("SELECT count(*) FROM ai_edit_jobs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM ai_edit_job_artifacts"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0032'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_0032_apply_preserves_old_columns_multiset(tmp_path):
    """安全重建后 ai_edit_jobs 旧 11 列多重集不变。"""
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_multiset.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        _seed_ai_edit_shell_rows(conn)
        before = sorted(conn.execute(
            "SELECT id, merchant_id, job_id, status, source_type, input_json, "
            "result_json, error_message, created_at, updated_at, completed_at "
            "FROM ai_edit_jobs"
        ).fetchall())
        _apply_on_temp(conn, "0032")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        after = sorted(conn.execute(
            "SELECT id, merchant_id, job_id, status, source_type, input_json, "
            "result_json, error_message, created_at, updated_at, completed_at "
            "FROM ai_edit_jobs"
        ).fetchall())
        assert after == before, "ai_edit_jobs 旧列多重集不一致（安全重建不得改写旧列）"
    finally:
        conn.close()


def test_sqlite_0032_apply_is_idempotent(tmp_path):
    """0032 apply 两次，第二次 already_applied=True（整体跳过）。"""
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_idem.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        first = _apply_on_temp(conn, "0032")
        second = _apply_on_temp(conn, "0032")
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True


def test_sqlite_0032_rejects_unknown_column_drift(tmp_path):
    """ai_edit_jobs 有额外列（schema 漂移）→ 0032 前置守卫拒绝，整体回滚。"""
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_drift.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        conn.execute("ALTER TABLE ai_edit_jobs ADD COLUMN rogue_col TEXT")
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0032")
    finally:
        conn.close()
    _assert_0032_not_applied_and_clean(db_path)


def test_sqlite_0032_rejects_missing_column(tmp_path):
    """ai_edit_jobs 缺失基线列 → 0032 前置守卫拒绝。"""
    if not SQLITE_FILE_PHASE12.is_file():
        pytest.skip("SQLite 0032 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_missing.db"
    # SQLite 旧版无 DROP COLUMN，用 RENAME+重建模拟缺失 source_type 列
    corrupt = (
        "ALTER TABLE ai_edit_jobs RENAME TO _jobs_missing; "
        "CREATE TABLE ai_edit_jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id VARCHAR(128) NOT NULL, "
        "job_id VARCHAR(64) NOT NULL, status VARCHAR(32), "
        "input_json TEXT, result_json TEXT, error_message TEXT, "
        "created_at DATETIME, updated_at DATETIME, completed_at DATETIME); "
        "INSERT INTO ai_edit_jobs (id, merchant_id, job_id, status, input_json, "
        "result_json, error_message, created_at, updated_at, completed_at) "
        "SELECT id, merchant_id, job_id, status, input_json, result_json, "
        "error_message, created_at, updated_at, completed_at FROM _jobs_missing; "
        "DROP TABLE _jobs_missing;"
    )
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        conn.executescript(corrupt)
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0032")
    finally:
        conn.close()
    _assert_0032_not_applied_and_clean(db_path)


def test_sqlite_0032_downgrade_restores_baseline_and_reupgradable(tmp_path):
    """downgrade 0032：恢复 0031 精确列集 + 新表删除 + 数据不丢 + 可再次 upgrade。"""
    if not SQLITE_FILE_PHASE12.is_file() or not SQLITE_DOWNGRADE_PHASE12.is_file():
        pytest.skip("SQLite 0032 upgrade/downgrade 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_downgrade.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        _seed_ai_edit_shell_rows(conn)
        _apply_on_temp(conn, "0032")
        downgrade_sql = SQLITE_DOWNGRADE_PHASE12.read_text(encoding="utf-8")
        conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert migrate_sqlite.get_columns(conn, "ai_edit_jobs") == AI_EDIT_JOBS_BASELINE_0031, (
            "downgrade 后 ai_edit_jobs 列集不等于 0031 基线"
        )
        assert migrate_sqlite.get_columns(conn, "ai_edit_job_artifacts") == AI_EDIT_ARTIFACTS_BASELINE_0031, (
            "downgrade 后 ai_edit_job_artifacts 列集不等于 0031 基线"
        )
        for t in EXPECTED_TABLES:
            assert not migrate_sqlite.table_exists(conn, t), (
                f"downgrade 后新表 {t} 应删除"
            )
        # 数据不丢
        assert conn.execute("SELECT count(*) FROM ai_edit_jobs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM ai_edit_job_artifacts"
        ).fetchone()[0] == 1
        # 0032 登记删除
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0032'"
        ).fetchone()[0] == 0, "downgrade 后 0032 登记应删除"
    finally:
        conn.close()

    # 可再次 upgrade（往返验证）
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        again = _apply_on_temp(conn, "0032")
    finally:
        conn.close()
    assert again.already_applied is False, "downgrade 后应能再次 apply 0032"


def test_sqlite_0032_downgrade_is_transactional_with_guard():
    """downgrade 必须显式事务（BEGIN/COMMIT）+ 多重集守卫。"""
    if not SQLITE_DOWNGRADE_PHASE12.is_file():
        pytest.skip("downgrade 未实现（Task 2 才建）")
    content = SQLITE_DOWNGRADE_PHASE12.read_text(encoding="utf-8")
    upper = content.upper()
    assert "BEGIN" in upper, "downgrade 必须显式 BEGIN 事务"
    assert "COMMIT" in upper, "downgrade 必须显式 COMMIT 事务"
    assert any(m in upper for m in ("EXCEPT", "MAX(ID)", "COUNT(*)")), (
        "downgrade 必须含多重集守卫（EXCEPT/MAX(ID)/COUNT(*)）"
    )


def test_sqlite_0032_downgrade_rejects_out_of_order(tmp_path):
    """存在更高版本（0033）登记时，0032 downgrade 必须拒绝；版本登记与结构均不变。"""
    if not SQLITE_FILE_PHASE12.is_file() or not SQLITE_DOWNGRADE_PHASE12.is_file():
        pytest.skip("0032 upgrade/downgrade 未实现（Task 2 才建）")
    db_path = tmp_path / "phase12_0032_down_outoforder.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_phase12_0031_head(conn)
        _apply_on_temp(conn, "0032")
        # 模拟后续 0033 已登记（head 不再是 0032）
        conn.execute(
            "INSERT INTO schema_migrations (version_num, applied_at, description) "
            "VALUES ('0033', CURRENT_TIMESTAMP, 'mock_future_version')"
        )
        downgrade_sql = SQLITE_DOWNGRADE_PHASE12.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        versions = sorted(
            r[0] for r in conn.execute(
                "SELECT version_num FROM schema_migrations"
            )
        )
        assert "0032" in versions, "越序降级被拒，0032 登记应保留"
        assert "0033" in versions, "越序降级不应删除任何版本登记"
        assert "stage" in migrate_sqlite.get_columns(conn, "ai_edit_jobs"), (
            "越序降级被拒，升级态结构应保留"
        )
    finally:
        conn.close()
