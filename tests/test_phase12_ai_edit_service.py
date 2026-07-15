"""Phase 12 AI 剪辑业务服务层合同测试（Task 3 红灯）。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 3。
冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10/§11。

覆盖：
- resolve_ai_edit_storage_key 路径穿越/符号链接防护（复用日报存储语义，不复制 .xlsx 限制）。
- 创建任务在 AiEditJobMaterial 钉住素材哈希和区间；生成 execution_token_hash + attempt_count=0。
- 状态更新必须带 job_id + execution_token_hash + attempt_count 条件（防旧 attempt 回写覆盖新结果）。
- 软删除素材：活动引用禁止删除；否则设 deleted_at + purge_after(+7 天)。
- 响应级脱敏：error_summary / media_profile_json 不重新泄露绝对路径和内部 storage_key。

Task 3 红灯：被测模块尚不存在，导入即 ImportError；不出现收集错误（用 importorskip）。
只使用 tmp_path 临时目录与内存 SQLite，不连接任何生产/开发库，不发起真实网络/媒体调用。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _import_service():
    """导入业务服务模块；Task 3 未实现时整体跳过本文件行为测试。"""
    return pytest.importorskip("app.services.ai_edit_service")


# ---------------------------------------------------------------------------
# 存储键解析：路径穿越与符号链接防护（红灯：模块缺失→importorskip 跳过）
# ---------------------------------------------------------------------------


def test_resolve_storage_key_rejects_traversal(tmp_path):
    svc = _import_service()
    with pytest.raises(Exception):
        svc.resolve_ai_edit_storage_key("../escape.mp4", tmp_path)


def test_resolve_storage_key_rejects_absolute_path(tmp_path):
    svc = _import_service()
    with pytest.raises(Exception):
        svc.resolve_ai_edit_storage_key(str(tmp_path / "abs.mp4"), tmp_path)


def test_resolve_storage_key_rejects_backslash_and_drive(tmp_path):
    svc = _import_service()
    with pytest.raises(Exception):
        svc.resolve_ai_edit_storage_key("C:\\windows\\evil.mp4", tmp_path)
    with pytest.raises(Exception):
        svc.resolve_ai_edit_storage_key("a\\b.mp4", tmp_path)


def test_resolve_storage_key_accepts_safe_relative(tmp_path):
    svc = _import_service()
    target = svc.resolve_ai_edit_storage_key("materials/m1/abc.mp4", tmp_path)
    assert tmp_path.resolve() in target.parents or target.parent == tmp_path.resolve()
    # 必须落在受控根内
    target.relative_to(tmp_path.resolve())


def test_resolve_storage_key_rejects_symlink(tmp_path):
    svc = _import_service()
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不支持符号链接")
    # 符号链接 storage_key 解析后路径必须是普通文件，符号链接被拒
    with pytest.raises(Exception):
        svc.resolve_ai_edit_storage_key("link.mp4", tmp_path)


# ---------------------------------------------------------------------------
# 任务创建：钉素材哈希+区间，生成执行令牌与 attempt=0
# ---------------------------------------------------------------------------


def test_create_job_pins_material_hash_and_range(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.models  # noqa: F401  触发 ORM 注册

    svc = _import_service()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # 前置：商户素材
        material = svc.register_material(
            db,
            merchant_id="m1",
            material_id="mat-1",
            media_type="video",
            source_sha256="sha-aaa",
            agent_client_id="agent-x",
        )
        job = svc.create_job(
            db,
            merchant_id="m1",
            job_id="job-1",
            template_key="tpl",
            materials=[
                {"material_id": "mat-1", "role": "main", "position": 0,
                 "pinned_sha256": "sha-aaa", "source_start": 1.0, "source_end": 5.0},
            ],
        )
        # 钉住哈希与区间
        jm = db.query(svc.AiEditJobMaterial).filter_by(job_id="job-1").one()
        assert jm.pinned_sha256 == "sha-aaa"
        assert jm.source_start == 1.0 and jm.source_end == 5.0
        # 执行令牌与 attempt 初始化
        assert job.attempt_count == 0
        assert job.execution_token_hash
        assert material.source_sha256 == "sha-aaa"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 状态更新条件：job_id + execution_token_hash + attempt_count（防旧 attempt 回写）
# ---------------------------------------------------------------------------


def test_update_status_rejects_stale_attempt(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.models  # noqa: F401

    svc = _import_service()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        svc.register_material(db, merchant_id="m1", material_id="mat-1",
                              media_type="video", source_sha256="sha-aaa", agent_client_id="ax")
        job = svc.create_job(
            db, merchant_id="m1", job_id="job-1", template_key="tpl",
            materials=[{"material_id": "mat-1", "role": "main", "position": 0,
                        "pinned_sha256": "sha-aaa", "source_start": 0.0, "source_end": 1.0}],
        )
        # 模拟重试：attempt 推进到 1，令牌轮换
        svc.retry_job(db, job_id="job-1", merchant_id="m1")
        refreshed = db.query(svc.AiEditJob).filter_by(job_id="job-1").one()
        assert refreshed.attempt_count == 1
        # 旧 attempt 的令牌（attempt=0）回写必须被拒
        with pytest.raises(svc.AiEditStatusConflict):
            svc.update_job_status(
                db, job_id="job-1", merchant_id="m1",
                execution_token_hash=job.execution_token_hash,  # 旧令牌
                attempt_count=0,  # 旧 attempt
                stage="analyze", progress=50,
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 软删除素材：活动引用禁止删除；7 天回收站
# ---------------------------------------------------------------------------


def test_soft_delete_material_rejects_when_referenced_by_active_job(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.models  # noqa: F401

    svc = _import_service()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        svc.register_material(db, merchant_id="m1", material_id="mat-1",
                              media_type="video", source_sha256="sha-aaa", agent_client_id="ax")
        svc.create_job(
            db, merchant_id="m1", job_id="job-1", template_key="tpl",
            materials=[{"material_id": "mat-1", "role": "main", "position": 0,
                        "pinned_sha256": "sha-aaa", "source_start": 0.0, "source_end": 1.0}],
        )
        with pytest.raises(svc.AiEditMaterialInUse):
            svc.soft_delete_material(db, material_id="mat-1", merchant_id="m1")
    finally:
        db.close()


def test_soft_delete_material_sets_recycle_bin_window(tmp_path):
    from datetime import datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.models  # noqa: F401

    svc = _import_service()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        svc.register_material(db, merchant_id="m1", material_id="mat-1",
                              media_type="video", source_sha256="sha-aaa", agent_client_id="ax")
        before = datetime.now()
        svc.soft_delete_material(db, material_id="mat-1", merchant_id="m1")
        mat = db.query(svc.AiEditMaterial).filter_by(material_id="mat-1").one()
        assert mat.deleted_at is not None
        assert mat.deleted_at >= before
        # purge_after 约为 deleted_at + 7 天
        assert mat.purge_after is not None
        assert timedelta(days=6, hours=23) <= (mat.purge_after - mat.deleted_at) <= timedelta(days=7, seconds=5)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 响应级脱敏（检查点 A 守卫）：error_summary / media_profile_json 不泄露路径与存储键
# ---------------------------------------------------------------------------


def test_redact_scrubs_absolute_paths_and_storage_keys():
    svc = _import_service()
    dirty = "失败：源文件 E:\\secret\\mat.mp4 读取失败，键 materials/m1/key.mp4"
    cleaned = svc.redact_sensitive_text(dirty)
    assert "E:\\" not in cleaned
    assert "secret" not in cleaned
    assert "materials/m1/key.mp4" not in cleaned


def test_job_response_never_leaks_paths_in_error_or_profile(tmp_path):
    """error_summary / media_profile_json 即便底层含路径/存储键，响应也不得泄露。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.models  # noqa: F401

    svc = _import_service()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        svc.register_material(db, merchant_id="m1", material_id="mat-1",
                              media_type="video", source_sha256="sha-aaa", agent_client_id="ax")
        job = svc.create_job(
            db, merchant_id="m1", job_id="job-1", template_key="tpl",
            materials=[{"material_id": "mat-1", "role": "main", "position": 0,
                        "pinned_sha256": "sha-aaa", "source_start": 0.0, "source_end": 1.0}],
        )
        # 底层写入含绝对路径与存储键的"脏"错误摘要与媒体属性
        job.error_summary = "崩溃于 C:\\data\\raw.mp4 键 materials/m1/x.mp4"
        job.failure_code = "RENDER_FAILED"
        db.flush()
        out = svc.to_job_out(job)
        payload = out.model_dump()
        assert "C:\\" not in payload.get("error_summary", "")
        assert "materials/m1/x.mp4" not in payload.get("error_summary", "")
        # 公共响应不得含 storage_key / merchant_id（设计 §10）
        assert "storage_key" not in payload
        assert "merchant_id" not in payload
    finally:
        db.close()
