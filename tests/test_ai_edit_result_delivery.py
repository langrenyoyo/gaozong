"""AI 剪辑结果交付闭环测试（不触网，mock TOSUploader 与 LAS client）。

覆盖 P0-AI-EDIT-RESULT-DELIVERY-CLOSELOOP-1 的关键点：
- 最终视频选择（subtitled 优先 clean 回退）
- 归档成功才可交付；归档失败不可播放
- 任务列表不返回 tos:// 或内部对象键
- 播放/下载/删除接口商户归属校验
- 删除幂等、删除失败记录状态
- 标题生成兜底
- 标题搜索部分匹配 + 商户隔离 + 排除软删除
- 视频标签来源于能力而非状态
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models import AiEditJob, AiEditJobArtifact
from app.services import ai_edit_las_service as las_svc


# ---------- fixtures ----------

def _make_job(db_session, **kw):
    """创建一个 LAS 任务行（默认 succeeded + 已有 artifact）。"""
    defaults = dict(
        merchant_id="m_test",
        job_id="las-test-1",
        status="succeeded",
        source_type="las_speech_auto",
        stage="completed",
        progress=100,
        las_task_id="task_x",
        las_idempotent_id="idem_1",
        las_script="宝马三系到店讲解短片",
        las_template="automotive_headtalk",
        delivery_status="pending",
        title=None,
        title_source=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(kw)
    job = AiEditJob(**defaults)
    db_session.add(job)
    db_session.commit()
    if not defaults.get("job_id_override"):
        # 让 job_id 字符串含 id 便于关联
        job.job_id = f"las-test-{job.id}"
        db_session.commit()
    return job


def _make_artifact(db_session, job, artifact_type="video_subtitled", storage_key="tos://las-bucket/path.mp4", **kw):
    defaults = dict(
        artifact_id=f"{job.job_id}-{artifact_type}",
        job_id=job.job_id,
        merchant_id=job.merchant_id,
        artifact_type=artifact_type,
        storage_key=storage_key,
        file_name=artifact_type,
        location_type="cloud",
    )
    defaults.update(kw)
    a = AiEditJobArtifact(**defaults)
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """每测试独立内存 SQLite Session，避免 job_id 唯一约束跨测试冲突。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    # 独立内存库 + 共享 cache 让多连接可见
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


# ---------- 最终视频选择与归档 ----------

def test_final_video_prefers_subtitled_over_clean(db_session):
    """subtitled 优先于 clean。"""
    job = _make_job(db_session)
    artifacts = {
        "video_subtitled_url": "https://signed/subtitled.mp4",
        "video_clean_url": "https://signed/clean.mp4",
    }
    with patch.object(las_svc.TOSUploader, "download_https_to_temp", return_value=("/tmp/x.mp4", 100)), \
         patch.object(las_svc.TOSUploader, "upload_file_stream"), \
         patch.object(las_svc.TOSUploader, "presign", return_value="https://play/x"):
        _make_artifact(db_session, job, "video_subtitled")
        _make_artifact(db_session, job, "video_clean")
        ok = las_svc.archive_final_video(db_session, job, artifacts)
    assert ok
    fa = las_svc._get_archived_final_artifact(db_session, job)
    assert fa is not None
    assert fa.artifact_type == "video_subtitled"  # 选了 subtitled
    assert fa.is_final_video is True
    assert fa.delivery_status == "archived"


def test_final_video_falls_back_to_clean_when_no_subtitled(db_session):
    """无字幕成片时回退无字幕成片。"""
    job = _make_job(db_session)
    artifacts = {"video_clean_url": "https://signed/clean.mp4"}
    _make_artifact(db_session, job, "video_clean")
    with patch.object(las_svc.TOSUploader, "download_https_to_temp", return_value=("/tmp/x.mp4", 100)), \
         patch.object(las_svc.TOSUploader, "upload_file_stream"):
        ok = las_svc.archive_final_video(db_session, job, artifacts)
    assert ok
    fa = las_svc._get_archived_final_artifact(db_session, job)
    assert fa.artifact_type == "video_clean"


def test_no_final_video_marks_failed(db_session):
    """两个 MP4 都不存在时归档失败。"""
    job = _make_job(db_session)
    artifacts = {"subtitle_srt_url": "https://signed/sub.srt"}  # 无视频
    ok = las_svc.archive_final_video(db_session, job, artifacts)
    assert ok is False
    assert job.delivery_status == "failed"


def test_archive_idempotent(db_session):
    """重复归档不重复产生对象。"""
    job = _make_job(db_session)
    artifacts = {"video_subtitled_url": "https://signed/sub.mp4"}
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="ai-edit/m_test/las-test-1/final.mp4")
    with patch.object(las_svc.TOSUploader, "upload_file_stream") as mock_up:
        ok = las_svc.archive_final_video(db_session, job, artifacts)
    assert ok
    mock_up.assert_not_called()  # 已归档不再上传


def test_archive_after_persist_artifacts_writes_fields(db_session):
    """R2真实流程：_persist_artifacts 用 db.add 未 commit，紧接着 archive_final_video
    必须正确写入 final_artifact 的 is_final_video/archive_object_key 字段。

    复现生产 bug：首次归档 job.delivery_status=archived 但 artifact 字段全 NULL。
    """
    job = _make_job(db_session)
    artifacts = {"video_subtitled_url": "https://signed/sub.mp4", "video_subtitled_tos_path": "tos://las/x.mp4"}
    # 模拟真实流程：先 _persist_artifacts（db.add 未 commit），再 archive
    las_svc._persist_artifacts(db_session, job, artifacts)
    with patch.object(las_svc.TOSUploader, "download_https_to_temp", return_value=("/tmp/x.mp4", 999)), \
         patch.object(las_svc.TOSUploader, "upload_file_stream"):
        ok = las_svc.archive_final_video(db_session, job, artifacts)
    assert ok
    # 关键断言：artifact 字段必须写入（非 NULL）
    fa = las_svc._get_archived_final_artifact(db_session, job)
    assert fa is not None, "归档后 final artifact 未标记"
    assert fa.is_final_video is True, "is_final_video 未写入"
    assert fa.delivery_status == "archived", "delivery_status 未写入"
    assert fa.archive_object_key == f"ai-edit/{job.merchant_id}/{job.job_id}/final.mp4", "archive_object_key 未写入"
    assert fa.file_size_bytes == 999, "file_size_bytes 未写入"


# ---------- 任务列表不暴露内部地址 ----------

def test_list_summary_no_tos_or_object_key(db_session):
    """列表项不返回 tos:// 或内部对象键。"""
    job = _make_job(db_session, title="测试标题")
    _make_artifact(db_session, job, "video_subtitled", storage_key="tos://internal/x.mp4")
    summary = las_svc._las_job_summary(db_session, job)
    s = str(summary)
    assert "tos://" not in s
    assert "storage_key" not in s
    assert "archive_object_key" not in summary  # 字段层面也不暴露
    assert summary["has_final_video"] is False  # 未归档


# ---------- 播放接口商户归属 ----------

def test_playback_cross_merchant_returns_none(db_session):
    """跨商户播放返回 None（不暴露存在性）。"""
    job = _make_job(db_session, merchant_id="m_A")
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="k")
    job.status = "succeeded"
    job.delivery_status = "archived"
    db_session.commit()
    # 用 m_B 查 m_A 的任务
    url = las_svc.generate_playback_url(db_session, merchant_id="m_B", job_id=job.id)
    assert url is None


def test_playback_deleted_job_returns_none(db_session):
    """已删除任务不能播放。"""
    job = _make_job(db_session, merchant_id="m_A")
    job.deleted_at = datetime.now()
    job.delete_status = "deleted"
    db_session.commit()
    url = las_svc.generate_playback_url(db_session, merchant_id="m_A", job_id=job.id)
    assert url is None


# ---------- 删除闭环 ----------

def test_delete_soft_deletes_and_disables_playback(db_session):
    """删除后软删除，播放下载拒绝。"""
    job = _make_job(db_session, merchant_id="m_A", delivery_status="archived", status="succeeded")
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="ai-edit/m_A/x/final.mp4")
    with patch.object(las_svc.TOSUploader, "delete_object"):
        r = las_svc.delete_las_job(db_session, merchant_id="m_A", job_id=job.id, operator_id="u1")
    assert r["deleted"] is True
    assert r["status"] == "deleted"
    # 播放被禁用
    assert las_svc.generate_playback_url(db_session, merchant_id="m_A", job_id=job.id) is None


def test_delete_idempotent(db_session):
    """已删除任务重复删除不报错。"""
    job = _make_job(db_session, merchant_id="m_A")
    job.deleted_at = datetime.now()
    job.delete_status = "deleted"
    db_session.commit()
    r = las_svc.delete_las_job(db_session, merchant_id="m_A", job_id=job.id, operator_id="u1")
    assert r["status"] == "already_deleted"


def test_delete_tos_failure_records_status(db_session):
    """自有 TOS 删除失败时记录 delete_failed。"""
    job = _make_job(db_session, merchant_id="m_A", delivery_status="archived", status="succeeded")
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="k")
    from app.services.las_tos_uploader import UploadError
    with patch.object(las_svc.TOSUploader, "delete_object", side_effect=UploadError("delete failed")):
        r = las_svc.delete_las_job(db_session, merchant_id="m_A", job_id=job.id, operator_id="u1")
    assert r["status"] == "delete_failed"
    db_session.refresh(job)
    assert job.delete_error is not None


def test_delete_cross_merchant_not_found(db_session):
    """跨商户删除返回 not_found。"""
    job = _make_job(db_session, merchant_id="m_A")
    r = las_svc.delete_las_job(db_session, merchant_id="m_B", job_id=job.id, operator_id="u1")
    assert r["deleted"] is False
    assert r["status"] == "not_found"


# ---------- 标题生成 ----------

def test_title_fallback_when_no_content(db_session):
    """无有效内容时兜底'混剪任务 #id'。"""
    job = _make_job(db_session, las_script=None, input_json=None)
    las_svc._fill_job_title(db_session, job, {})
    assert job.title == f"混剪任务 #{job.id}"
    assert job.title_source == "fallback"


def test_title_from_script(db_session):
    """有口播文案时用 script 生成标题。"""
    job = _make_job(db_session, las_script="宝马三系到店实车讲解，外观内饰配置全面介绍。")
    las_svc._fill_job_title(db_session, job, {})
    assert job.title_source == "script"
    assert "宝马" in job.title


# ---------- 标题搜索 ----------

def test_search_partial_match(db_session):
    """标题搜索支持部分匹配。"""
    _make_job(db_session, job_id="las-s1", title="宝马三系到店讲解", merchant_id="m_A")
    _make_job(db_session, job_id="las-s2", title="奥迪A6L展示", merchant_id="m_A")
    r = las_svc.list_las_jobs(db_session, merchant_id="m_A", keyword="宝马")
    assert r["total"] == 1
    assert "宝马" in r["items"][0]["title"]


def test_search_cross_merchant_isolated(db_session):
    """搜索不跨商户。"""
    _make_job(db_session, job_id="las-s1", title="宝马三系", merchant_id="m_A")
    _make_job(db_session, job_id="las-s2", title="宝马X5", merchant_id="m_B")
    r = las_svc.list_las_jobs(db_session, merchant_id="m_A", keyword="宝马")
    assert r["total"] == 1


def test_search_excludes_deleted(db_session):
    """搜索排除软删除任务。"""
    j1 = _make_job(db_session, job_id="las-s1", title="宝马三系", merchant_id="m_A")
    j2 = _make_job(db_session, job_id="las-s2", title="宝马X5", merchant_id="m_A")
    j2.deleted_at = datetime.now()
    j2.delete_status = "deleted"
    db_session.commit()
    r = las_svc.list_las_jobs(db_session, merchant_id="m_A", keyword="宝马")
    assert r["total"] == 1
    assert r["items"][0]["job_id"] == j1.id


# ---------- 视频标签 ----------

def test_video_tags_from_capabilities(db_session):
    """标签来源于任务能力而非完成状态。"""
    job = _make_job(db_session, las_script="有口播", las_template="automotive_headtalk")
    artifacts = {"subtitle_srt_url": "https://x/sub.srt"}
    tags = las_svc.compute_video_tags(job, artifacts)
    assert "script_driven" in tags  # 有 script
    assert "ai_subtitle" in tags  # 有字幕产物
    assert "ai_clip_matching" in tags  # automotive_headtalk
    # 无 script 时不返回 script_driven
    job2 = _make_job(db_session, job_id="las-t2", las_script=None, las_template="automotive_headtalk")
    tags2 = las_svc.compute_video_tags(job2, {})
    assert "script_driven" not in tags2
    assert "ai_subtitle" not in tags2  # 无字幕产物
    assert "ai_clip_matching" in tags2


# ---------- 下载文件名安全清洗 ----------

def test_safe_filename_strips_path_chars():
    """下载文件名安全清洗：去路径分隔符，无路径穿越，兜底 job_id。"""
    assert las_svc.safe_filename("宝马三系", 1).endswith(".mp4")
    # 路径分隔符 / 已去除，无穿越
    fn = las_svc.safe_filename("../../etc/passwd", 1)
    assert "/" not in fn and "\\" not in fn
    assert fn.endswith(".mp4")
    assert las_svc.safe_filename("", 1) == "混剪任务 #1.mp4"


# ============ R1 返工新增测试 ============


def test_temp_url_not_in_storage_key(db_session):
    """R1: artifact 只有 url 没有 tos_path 时，storage_key 不得保存临时 HTTPS URL。"""
    job = _make_job(db_session)
    artifacts = {"video_subtitled_url": "https://signed.example.com/temp.mp4?sig=abc"}
    # 没有 tos_path
    las_svc._persist_artifacts(db_session, job, artifacts)
    a = db_session.query(AiEditJobArtifact).filter_by(job_id=job.job_id, artifact_type="video_subtitled").first()
    assert a is not None
    # storage_key 不能是该 HTTPS URL，也不能以 http 开头
    assert a.storage_key != "https://signed.example.com/temp.mp4?sig=abc"
    assert not (a.storage_key or "").startswith("http")


def test_summary_no_temp_url_returned(db_session):
    """R1: 商户列表响应不返回临时 URL。"""
    job = _make_job(db_session, title="测试")
    # 故意写一个历史脏数据 storage_key=https
    _make_artifact(db_session, job, "video_subtitled", storage_key="https://dirty.example.com/x.mp4")
    summary = las_svc._las_job_summary(db_session, job)
    s = str(summary)
    assert "https://dirty" not in s
    assert "signed.example.com" not in s


def test_archive_failure_blocks_playback_pending(db_session):
    """R1: delivery_status=pending 时不可播放，不调用 presign。"""
    job = _make_job(db_session, merchant_id="m_A", status="succeeded", delivery_status="pending")
    with patch.object(las_svc.TOSUploader, "presign") as mock_p:
        url = las_svc.generate_playback_url(db_session, merchant_id="m_A", job_id=job.id)
    assert url is None
    mock_p.assert_not_called()


def test_archive_failure_blocks_playback_failed(db_session):
    """R1: delivery_status=failed 时不可播放，不调用 presign。"""
    job = _make_job(db_session, merchant_id="m_A", status="succeeded", delivery_status="failed")
    with patch.object(las_svc.TOSUploader, "presign") as mock_p:
        url = las_svc.generate_playback_url(db_session, merchant_id="m_A", job_id=job.id)
    assert url is None
    mock_p.assert_not_called()


def test_download_title_cross_merchant_returns_none(db_session):
    """R1: 下载跨商户取标题返回 None，不泄露存在性。"""
    job = _make_job(db_session, merchant_id="m_A", title="A的任务")
    # m_B 查 m_A 的标题
    title = las_svc.get_job_title(db_session, merchant_id="m_B", job_id=job.id)
    assert title is None


def test_download_cross_merchant_via_playback(db_session):
    """R1: 下载接口底层 generate_playback_url 跨商户返回 None，不生成签名。"""
    job = _make_job(db_session, merchant_id="m_A", status="succeeded", delivery_status="archived")
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="k")
    with patch.object(las_svc.TOSUploader, "presign") as mock_p:
        url = las_svc.generate_playback_url(db_session, merchant_id="m_B", job_id=job.id)
    assert url is None
    mock_p.assert_not_called()


def test_deleted_job_cannot_download(db_session):
    """R1: 已删除任务下载返回 None，不调用 presign。"""
    job = _make_job(db_session, merchant_id="m_A", status="succeeded", delivery_status="archived")
    _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="k")
    job.deleted_at = datetime.now()
    job.delete_status = "deleted"
    db_session.commit()
    with patch.object(las_svc.TOSUploader, "presign") as mock_p:
        url = las_svc.generate_playback_url(db_session, merchant_id="m_A", job_id=job.id)
    assert url is None
    mock_p.assert_not_called()


def test_delete_does_not_touch_original_material(db_session):
    """R1: 删除任务只删最终归档视频，不删用户原始素材。

    原始素材在本系统中是 AiEditMaterial（独立表），LAS artifact 不属于原始素材。
    删除时只对 archive_object_key 调 delete_object，不碰其它对象键。
    """
    job = _make_job(db_session, merchant_id="m_A", status="succeeded", delivery_status="archived")
    final = _make_artifact(db_session, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="ai-edit/m_A/x/final.mp4")
    # 另一个非最终视频 artifact（内部 LAS 产物，不是原始素材）
    other = _make_artifact(db_session, job, "subtitle_srt", storage_key="tos://las/internal/sub.srt")
    delete_keys = []
    def fake_delete(key):
        delete_keys.append(key)
    with patch.object(las_svc.TOSUploader, "delete_object", side_effect=fake_delete):
        r = las_svc.delete_las_job(db_session, merchant_id="m_A", job_id=job.id, operator_id="u1")
    assert r["status"] == "deleted"
    # 只删了最终视频的归档键，没碰其它对象
    assert delete_keys == ["ai-edit/m_A/x/final.mp4"]
    assert "tos://las/internal/sub.srt" not in delete_keys


def test_title_from_asr_when_no_script(db_session):
    """R1: 无口播文案时用 ASR 生成标题，source=asr，不调 9100。"""
    job = _make_job(db_session, las_script=None)
    artifacts = {"result_json_url": "https://signed.example.com/result.json"}
    asr_data = {"match_scheme": {"units": [{"text": "宝马三系到店实车讲解外观内饰配置"}, {"text": "车况总结"}]}}
    with patch("app.services.ai_edit_las_service.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = asr_data
        mock_get.return_value = mock_resp
        las_svc._fill_job_title(db_session, job, artifacts)
    assert job.title_source == "asr"
    assert "宝马" in job.title


def test_video_tags_independent_of_status(db_session):
    """R1: 相同能力配置下，running/failed/succeeded 状态返回相同标签。"""
    base = dict(las_script="有口播", las_template="automotive_headtalk")
    artifacts = {"subtitle_srt_url": "https://x/sub.srt"}
    tags_running = las_svc.compute_video_tags(
        AiEditJob(**{**base, "merchant_id": "m", "job_id": "j1", "status": "running", "source_type": "las_speech_auto"}),  # noqa
        artifacts,
    )
    tags_failed = las_svc.compute_video_tags(
        AiEditJob(**{**base, "merchant_id": "m", "job_id": "j2", "status": "failed", "source_type": "las_speech_auto"}),  # noqa
        artifacts,
    )
    tags_succeeded = las_svc.compute_video_tags(
        AiEditJob(**{**base, "merchant_id": "m", "job_id": "j3", "status": "succeeded", "source_type": "las_speech_auto"}),  # noqa
        artifacts,
    )
    assert tags_running == tags_failed == tags_succeeded


def test_video_tags_absent_when_no_capability(db_session):
    """R1: 无字幕能力不返回 ai_subtitle；无 template 匹配不返回 ai_clip_matching。"""
    job = AiEditJob(merchant_id="m", job_id="j", status="succeeded", source_type="las_speech_auto", las_script="有口播", las_template="other_template")  # noqa
    tags = las_svc.compute_video_tags(job, {})  # 无字幕产物
    assert "ai_subtitle" not in tags
    assert "ai_clip_matching" not in tags  # template 不匹配
    assert "script_driven" in tags  # 但有 script


def test_title_backfill_protects_manual(db_session):
    """R1/R2: 手工标题保护——脚本 backfill 真实跳过 manual+NULL，不覆盖。

    真正调用脚本 backfill_titles，断言 manual+NULL 的任务标题保持 NULL 未被覆盖。
    """
    import scripts.fix_ai_edit_jobs as fix
    job = _make_job(db_session, title=None, title_source="manual")
    # 用真实脚本函数处理（dry-run 不写库，--execute 才写；这里用 execute 验证不覆盖）
    rc = fix.backfill_titles(job_id=job.id, limit=10, execute=True)
    assert rc == 0
    db_session.refresh(job)
    # manual+NULL 受保护，脚本跳过，title 仍为 NULL
    assert job.title is None, f"manual+NULL 应被跳过保持 NULL，实际被改为 {job.title!r}"
    assert job.title_source == "manual"


# ============ R2 返工新增：删除失败不假装成功（路由直测） ============
# 路由测试用模块级 StaticPool 内存库，确保 app 内部 session 与测试 session 共享同一库

from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
from sqlalchemy.pool import StaticPool as _SP
import app.models  # noqa: F401
from app.database import Base as _Base, get_db as _get_db

_route_engine = _ce("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=_SP)
_RouteSession = _sm(autocommit=False, autoflush=False, bind=_route_engine)


def _setup_route_db():
    _Base.metadata.drop_all(bind=_route_engine)
    _Base.metadata.create_all(bind=_route_engine)


def _route_client(merchant_id: str):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import get_request_context_required
    from app.auth.context import RequestContext
    ctx = RequestContext(user_id="u1", auth_mode="mock", super_admin=False, permission_codes=["auto_wechat:ai_edit"], merchant_id=merchant_id)
    app.dependency_overrides[get_request_context_required] = lambda: ctx
    app.dependency_overrides[_get_db] = lambda: _RouteSession()
    return TestClient(app)


def _route_teardown():
    from app.main import app
    app.dependency_overrides.clear()


def test_delete_failed_returns_non_200_and_keeps_retryable():
    """R2: TOS 删除失败时路由返回 500（DELETE_PARTIALLY_FAILED），任务保留可重试。

    断言：后端不假装成功；HTTP 500；任务仍软删除禁用访问；可再次调用删除（重试）。
    """
    from app.services.las_tos_uploader import UploadError
    _setup_route_db()
    s = _RouteSession()
    try:
        job = _make_job(s, merchant_id="m_A", status="succeeded", delivery_status="archived")
        _make_artifact(s, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="ai-edit/m_A/x/final.mp4")
        job.deleted_at = datetime.now()
        job.delete_status = "delete_failed"
        s.commit()
        job_id = job.id
    finally:
        s.close()

    client = _route_client("m_A")
    try:
        with patch.object(las_svc.TOSUploader, "delete_object", side_effect=UploadError("still failing")):
            resp = client.delete(f"/ai-edit/las/jobs/{job_id}")
        assert resp.status_code == 500, f"TOS 删除失败应返回 500，实际 {resp.status_code}"
        body = resp.json()
        assert body["detail"]["code"] == "DELETE_PARTIALLY_FAILED"
    finally:
        _route_teardown()

    # 任务仍可重试：未进入 deleted 终态
    s2 = _RouteSession()
    try:
        j = s2.query(AiEditJob).get(job_id)
        assert j.delete_status == "delete_failed"
    finally:
        s2.close()


def test_delete_success_returns_200():
    """R2 对照：删除成功返回 200 + deleted。"""
    _setup_route_db()
    s = _RouteSession()
    try:
        job = _make_job(s, merchant_id="m_A", status="succeeded", delivery_status="archived")
        _make_artifact(s, job, "video_subtitled", delivery_status="archived", is_final_video=True, archive_object_key="k")
        job_id = job.id
    finally:
        s.close()

    client = _route_client("m_A")
    try:
        with patch.object(las_svc.TOSUploader, "delete_object"):
            resp = client.delete(f"/ai-edit/las/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "deleted"
    finally:
        _route_teardown()

