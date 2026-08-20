"""AI 剪辑 LAS 轮询崩溃恢复测试（不触网，mock process_las_job）。

覆盖 M06 轮询恢复机制：
- 启动恢复扫描只重入队 heartbeat 缺失或超时的 processing + las_task_id 任务
- 心跳新鲜 / 非 processing / 无 las_task_id 的任务不恢复
- create_las_job 提交即写初始 heartbeat（避免新任务被误判 stale）
- 全部 mock，不触网
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import AiEditJob
from app.services import ai_edit_las_service as las_svc


@pytest.fixture
def db_session(monkeypatch):
    """内存 SQLite Session；resume 扫描走同一 session。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()

    import app.database as dbmod
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: s)
    yield s
    s.close()


def _mk_job(db, *, status, las_task_id, heartbeat, job_id: str):
    j = AiEditJob(
        merchant_id="merchant-test",
        job_id=job_id,
        status=status,
        source_type="las_speech_auto",
        stage="submitted",
        progress=0,
        attempt_count=1,
        las_task_id=las_task_id,
        heartbeat_at=heartbeat,
        created_at=datetime.now(),
    )
    db.add(j)
    return j


def test_resume_only_stale_processing(monkeypatch, db_session):
    db = db_session
    now = datetime.now()
    old = now - timedelta(seconds=600)
    fresh = now - timedelta(seconds=10)

    a = _mk_job(db, status="processing", las_task_id="t-a", heartbeat=None, job_id="job-a")   # 应恢复
    b = _mk_job(db, status="processing", las_task_id="t-b", heartbeat=old, job_id="job-b")     # 应恢复
    c = _mk_job(db, status="processing", las_task_id="t-c", heartbeat=fresh, job_id="job-c")   # 不恢复（心跳新鲜）
    d = _mk_job(db, status="failed", las_task_id="t-d", heartbeat=None, job_id="job-d")        # 不恢复（非 processing）
    e = _mk_job(db, status="processing", las_task_id=None, heartbeat=None, job_id="job-e")     # 不恢复（无 las_task_id）
    db.commit()

    called: list[int] = []
    monkeypatch.setattr(las_svc, "process_las_job", lambda jid: called.append(jid))

    las_svc.resume_stale_las_jobs()

    assert sorted(called) == sorted([a.id, b.id])


def test_resume_no_stale_is_noop(monkeypatch, db_session):
    db = db_session
    _mk_job(db, status="processing", las_task_id="t-f", heartbeat=datetime.now(), job_id="job-f")
    db.commit()

    called: list[int] = []
    monkeypatch.setattr(las_svc, "process_las_job", lambda jid: called.append(jid))

    las_svc.resume_stale_las_jobs()

    assert called == []


def test_create_las_job_inits_heartbeat(monkeypatch, db_session):
    """create_las_job 提交即写初始 heartbeat，避免启动恢复扫描误判新任务为 stale。"""
    from unittest.mock import MagicMock

    import app.services.ai_edit_las_service as las_svc_mod

    client = MagicMock()
    client.submit.return_value = {
        "metadata": {"task_id": "t-heartbeat", "task_status": "PENDING", "business_code": "0"}
    }
    monkeypatch.setattr(las_svc_mod, "get_las_speech_auto_client", lambda: client)
    job = las_svc_mod.create_las_job(
        db_session,
        merchant_id="merchant-test",
        video_urls=["https://example.com/a.mp4"],
        script="测试脚本",
    )
    assert job.heartbeat_at is not None
