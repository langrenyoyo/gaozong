"""Phase 12 Task 12 素材分析与人工覆盖合同红灯。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 3（分析部分）。

冻结 Task 12-3/12-4/12-5 才实现的行为：
- 重新分析可更新 AI 基线但不得修改人工字段；详情合并时人工覆盖优先。
- 人工覆盖 > 当前 AI 快照 > 空值。

红灯策略：get_effective_material_detail / save_ai_analysis 当前不存在 → getattr 返回 None → 断言失败。
不出现收集错误。只用内存 SQLite。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiEditMaterial, AiEditMaterialAnalysis
from app.services import ai_edit_service as svc
import app.models  # noqa: F401

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_reanalysis_preserves_manual_override():
    """重新分析后人工标签仍优先于 AI 标签。"""
    db = TestSession()
    try:
        material = AiEditMaterial(
            material_id="mat-1", merchant_id="m1", scope="merchant",
            media_type="video", storage_mode="local_only",
            source_sha256="a" * 64, analysis_status="pending",
            stabilization_status="pending",
            # 人工覆盖（Task 12-2 列）
            manual_override_json='{"tags":["人工标签"]}',
        )
        db.add(material)
        db.flush()
        # 保存一次 AI 分析（AI 标签不同）
        save_ai_analysis = getattr(svc, "save_ai_analysis", None)
        assert save_ai_analysis is not None, "save_ai_analysis 缺失（Task 12-3/12-5 实现）"
        save_ai_analysis(db, material, ai_tags=["AI 新标签"])
        get_detail = getattr(svc, "get_effective_material_detail", None)
        assert get_detail is not None, "get_effective_material_detail 缺失"
        detail = get_detail(db, material.material_id)
        # 人工标签必须优先
        tags = getattr(detail, "tags", None) or detail.get("tags")
        assert tags and tags[0] == "人工标签", "重新分析后人工覆盖必须优先"
    finally:
        db.close()


def test_ai_analysis_snapshot_is_immutable():
    """旧分析快照不可变，详情只使用当前 SHA 的最新快照。"""
    db = TestSession()
    try:
        material = AiEditMaterial(
            material_id="mat-1", merchant_id="m1", scope="merchant",
            media_type="video", storage_mode="local_only",
            source_sha256="a" * 64, analysis_status="pending",
            stabilization_status="pending",
        )
        db.add(material)
        db.flush()
        # 旧快照
        old = AiEditMaterialAnalysis(
            material_id="mat-1", source_sha256="a" * 64,
            analysis_version="v1",
            transcript_json="[]", scenes_json="[]",
            tags_json='["旧标签"]', usable_ranges_json="[]",
        )
        db.add(old)
        db.flush()
        # 写一个更新的快照
        save_ai_analysis = getattr(svc, "save_ai_analysis", None)
        assert save_ai_analysis is not None, "save_ai_analysis 缺失"
        save_ai_analysis(db, material, ai_tags=["新标签"])
        get_detail = getattr(svc, "get_effective_material_detail", None)
        assert get_detail is not None, "get_effective_material_detail 缺失"
        detail = get_detail(db, material.material_id)
        tags = getattr(detail, "tags", None) or detail.get("tags")
        assert tags == ["新标签"], "详情必须使用最新快照，旧快照不可参与"
    finally:
        db.close()


def test_ai_edit_material_analysis_table_columns_frozen():
    """快照表保持 9 列，不得为 description/category/highlights 擅自扩列。"""
    columns = set(AiEditMaterialAnalysis.__table__.columns.keys())
    expected = {
        "id", "material_id", "source_sha256", "analysis_version",
        "transcript_json", "scenes_json", "tags_json", "usable_ranges_json",
        "created_at",
    }
    assert columns == expected, f"ai_edit_material_analyses 列集漂移: {columns ^ expected}"
