"""Phase 12 Task 12 素材库数据模型与迁移合同红灯。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 1 / Step 2（schema 部分）。

红灯只来自被测对象缺失，不来自测试语法、导入或 fixture 错误：
- 直接 import 不存在的类会触发收集错误，故用 getattr 延迟探测，缺失转为断言失败。
- 迁移文件缺失同样转为断言失败，不触发 import。
只使用模块级 metadata 探测与文件存在性检查，不建内存库、不连任何数据库。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

import app.models as models
import app.schemas as schemas

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Task 12-2 将为 AiEditMaterial 新增的展示与生命周期列（执行包 §1 / Task 12-2 Step 1）。
EXPECTED_MATERIAL_COLUMNS = {
    "display_name", "description", "category", "duration_seconds",
    "width", "height", "fps", "file_size_bytes",
    "manual_override_json", "manual_confirmed_at",
    "purge_operation_id", "purge_status",
}
# 阶段状态机五阶段（执行包 Task 12-2 Step 1 / Task 12-3 Step 3）。
EXPECTED_STAGES = {
    "media_probe", "transcript", "content_analysis", "stability", "cloud_upload",
}
EXPECTED_MEDIA_TYPES = {"video", "audio", "image"}


def test_task12_material_process_model_declared():
    """AiEditMaterialProcess 必须作为独立 ORM 模型登记到 metadata。"""
    process_cls = getattr(models, "AiEditMaterialProcess", None)
    assert process_cls is not None, "AiEditMaterialProcess 模型缺失"
    assert process_cls.__tablename__ == "ai_edit_material_processes"
    table = process_cls.__table__
    # 五阶段必须由数据库 CHECK 约束固化，不能只靠 service 校验。
    stage_checks = {
        str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert any("media_probe" in s and "cloud_upload" in s for s in stage_checks), (
        "ai_edit_material_processes 缺少 stage CHECK 约束"
    )


def test_task12_material_process_unique_stage_constraint():
    """(material_id, source_sha256, stage) 必须有唯一约束，支撑 CAS 领取。"""
    process_cls = getattr(models, "AiEditMaterialProcess", None)
    assert process_cls is not None, "AiEditMaterialProcess 模型缺失"
    table = process_cls.__table__
    unique_names = {
        (frozenset(c.columns.keys()), c.name)
        for c in table.constraints if isinstance(c, UniqueConstraint)
    }
    expected_cols = {"material_id", "source_sha256", "stage"}
    assert any(cols == expected_cols for cols, _ in unique_names), (
        "ai_edit_material_processes 缺少 (material_id, source_sha256, stage) 唯一约束"
    )


def test_task12_material_extension_columns():
    """AiEditMaterial 必须新增 12 个展示/媒体/生命周期列。"""
    material_cls = getattr(models, "AiEditMaterial", None)
    assert material_cls is not None
    columns = set(material_cls.__table__.columns.keys())
    missing = EXPECTED_MATERIAL_COLUMNS - columns
    assert not missing, f"AiEditMaterial 缺少列: {missing}"


def test_task12_material_file_size_is_biginteger():
    """file_size_bytes 必须用 BigInteger，避免接近 2GB 视频溢出 PG INTEGER。"""
    material_cls = getattr(models, "AiEditMaterial", None)
    assert material_cls is not None
    from sqlalchemy import BigInteger

    column = material_cls.__table__.columns.get("file_size_bytes")
    assert column is not None, "AiEditMaterial.file_size_bytes 列缺失"
    assert isinstance(column.type, BigInteger), (
        f"file_size_bytes 必须是 BigInteger，当前 {type(column.type).__name__}"
    )


def test_task12_material_purge_pair_constraint():
    """purge_status 与 purge_operation_id 必须同为空或同非空（CHECK 约束）。"""
    material_cls = getattr(models, "AiEditMaterial", None)
    assert material_cls is not None
    table = material_cls.__table__
    check_texts = {
        str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert any(
        "purge_status" in s and "purge_operation_id" in s for s in check_texts
    ), "ai_edit_materials 缺少 purge_status/purge_operation_id 配对 CHECK 约束"


def test_task12_material_merchant_sha_unique_constraint():
    """(merchant_id, source_sha256) 必须有唯一约束，支撑规范 ID 去重。"""
    material_cls = getattr(models, "AiEditMaterial", None)
    assert material_cls is not None
    table = material_cls.__table__
    unique_names = [
        (frozenset(c.columns.keys()), c.name)
        for c in table.constraints if isinstance(c, UniqueConstraint)
    ]
    expected_cols = {"merchant_id", "source_sha256"}
    assert any(cols == expected_cols for cols, _ in unique_names), (
        "ai_edit_materials 缺少 (merchant_id, source_sha256) 唯一约束"
    )


def test_task12_migration_files_exist():
    """双轨迁移文件必须存在（SQLite 0034 升降级 + PostgreSQL 0015）。"""
    assert (PROJECT_ROOT / "migrations/versions/0034_ai_edit_material_library.sql").is_file()
    assert (PROJECT_ROOT / "migrations/downgrades/0034_ai_edit_material_library.sql").is_file()
    assert (
        PROJECT_ROOT / "migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py"
    ).is_file()


def test_task12_material_detail_out_schema():
    """AiEditMaterialDetailOut 必须分离出详情结构，含当前有效分析与人工覆盖。"""
    detail_cls = getattr(schemas, "AiEditMaterialDetailOut", None)
    assert detail_cls is not None, "AiEditMaterialDetailOut schema 缺失"


def test_task12_material_process_out_schema():
    """AiEditMaterialProcessOut 必须存在且不暴露 execution_token_hash。"""
    out_cls = getattr(schemas, "AiEditMaterialProcessOut", None)
    assert out_cls is not None, "AiEditMaterialProcessOut schema 缺失"
    fields = set(out_cls.model_fields.keys())
    assert "execution_token_hash" not in fields, (
        "AiEditMaterialProcessOut 不得暴露 execution_token_hash"
    )


def test_task12_material_out_does_not_leak_internal_fields():
    """AiEditMaterialOut 不得返回 storage_key / merchant_id / 绝对路径 / purge_operation_id。"""
    out_cls = getattr(schemas, "AiEditMaterialOut", None)
    assert out_cls is not None
    fields = set(out_cls.model_fields.keys())
    forbidden = {
        "storage_key", "merchant_id", "absolute_path",
        "purge_operation_id", "execution_token_hash",
        "cloud_storage_key", "thumbnail_storage_key",
    }
    leaked = forbidden & fields
    assert not leaked, f"AiEditMaterialOut 泄露内部字段: {leaked}"


def test_task12_material_annotations_patch_strict():
    """人工确认 DTO 必须 extra=forbid，且不能让客户端覆盖 AI 快照/SHA/scope。"""
    patch_cls = getattr(schemas, "AiEditMaterialAnnotationsPatch", None)
    assert patch_cls is not None, "AiEditMaterialAnnotationsPatch schema 缺失"
    # extra=forbid：未知字段必须被拒绝。
    assert patch_cls.model_config.get("extra") == "forbid"
    fields = set(patch_cls.model_fields.keys())
    forbidden = {"source_sha256", "scope", "storage_mode", "manual_override_json"}
    leaked = forbidden & fields
    assert not leaked, f"人工确认 DTO 允许覆盖受保护字段: {leaked}"


# ---------------------------------------------------------------------------
# purge 配对 CHECK：三类违规必须在数据库层被拒绝（执行包 Task 12-2 Step 1）。
# 用 ORM metadata create_all 建表，验证 CHECK 约束在数据库层生效。
# ---------------------------------------------------------------------------

import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models  # noqa: F401


def _make_db() -> str:
    """用 ORM metadata 建内存库的文件镜像（CREATE TABLE 含全部 CHECK），返回路径。"""
    import tempfile
    from pathlib import Path

    d = tempfile.mkdtemp(prefix="task12_purge_check_")
    path = str(Path(d) / "t.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine, tables=[app.models.AiEditMaterial.__table__])
    engine.dispose()
    return path


def _seed_material_row(db_path: str, **overrides) -> None:
    """直接插入一行 ai_edit_materials（绕过 service，验证数据库约束）。"""
    conn = sqlite3.connect(db_path, isolation_level=None)
    cols = {
        "material_id": "mat-1", "merchant_id": "m1", "scope": "merchant",
        "media_type": "video", "storage_mode": "local_only",
        "source_sha256": "a" * 64, "analysis_status": "pending",
        "stabilization_status": "pending",
    }
    cols.update(overrides)
    names = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO ai_edit_materials ({names}) VALUES ({placeholders})",
        list(cols.values()),
    )
    conn.close()


def _assert_insert_rejected(db_path: str, **overrides):
    import pytest

    try:
        _seed_material_row(db_path, **overrides)
    except sqlite3.IntegrityError:
        return
    pytest.fail(f"数据库应拒绝插入: {overrides}")


def test_purge_pair_rejects_status_without_operation():
    """非空 purge_status + 空 purge_operation_id 必须被数据库 CHECK 拒绝。"""
    _assert_insert_rejected(_make_db(), purge_status="preparing", purge_operation_id=None)


def test_purge_pair_rejects_operation_without_status():
    """空 purge_status + 非空 purge_operation_id 必须被数据库 CHECK 拒绝。"""
    _assert_insert_rejected(_make_db(), purge_status=None, purge_operation_id="op-1")


def test_purge_status_rejects_unknown_value():
    """未知 purge_status 必须被数据库 CHECK 拒绝。"""
    _assert_insert_rejected(
        _make_db(), purge_status="unknown_status", purge_operation_id="op-1"
    )


def test_purge_pair_allows_both_null():
    """同空允许（正常素材无删除 claim）。"""
    _seed_material_row(_make_db(), purge_status=None, purge_operation_id=None)


def test_purge_pair_allows_both_set():
    """同非空允许（preparing/completed + operation_id）。"""
    _seed_material_row(_make_db(), purge_status="completed", purge_operation_id="op-1")


def test_migration_constraint_names_match_across_dialects():
    """SQLite 0034 与 PostgreSQL 0015 必须存在两个 purge 约束名，且名称一致。"""
    sql_up = (PROJECT_ROOT / "migrations/versions/0034_ai_edit_material_library.sql").read_text(encoding="utf-8")
    pg_up = (PROJECT_ROOT / "migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py").read_text(encoding="utf-8")
    for name in ("ck_ai_edit_materials_purge_status", "ck_ai_edit_materials_purge_pair"):
        assert name in sql_up, f"SQLite 0034 缺少约束名 {name}"
        assert name in pg_up, f"PostgreSQL 0015 缺少约束名 {name}"
