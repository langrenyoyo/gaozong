"""AI剪辑 LAS speech_auto 编排服务。

职责（纯 LAS 云端方案）：
- create_las_job：创建 AiEditJob + 调 LAS submit + 写 las_task_id，入轮询队列。
- process_las_job：轮询 LAS wait_for_terminal + 终态写库 + COMPLETED 时存产物到 artifacts。
- get_las_job_status：查任务状态 + 产物（脱敏，不返回 tos_path 原始）。

不做本地 FFmpeg/9100 规划（纯 LAS 云端，能力迁移自 demo）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from app import config
from app.models import AiEditJob, AiEditJobArtifact
from app.services.las_client import DOWNLOAD_FIELDS, LASError, get_las_speech_auto_client
from app.services.las_tos_uploader import TOSUploader, UploadError

logger = logging.getLogger(__name__)

LAS_TEMPLATE = "automotive_headtalk"
LAS_MAX_VIDEOS = 30
LAS_SCRIPT_MAX_LEN = 4000

# 最终视频选择顺序：subtitled 优先，clean 回退
FINAL_VIDEO_FIELDS = ("video_subtitled_url", "video_clean_url")


def create_las_job(
    db: Session,
    *,
    merchant_id: str,
    video_urls: list[str],
    script: str,
    template: str = LAS_TEMPLATE,
    output_tos_path: str | None = None,
    idempotent_id: str | None = None,
) -> AiEditJob:
    """创建 LAS 混剪任务：组装参数 → 调 LAS submit → 写库 las_task_id。

    幂等：复用传入 idempotent_id（持久化 las_idempotent_id），网络重试用同 id 不重复创建。
    """
    # 能力边界校验（对齐接口文档 §4）
    if not video_urls:
        raise ValueError("video_urls 不能为空")
    if len(video_urls) > LAS_MAX_VIDEOS:
        raise ValueError(f"视频数量不能超过 {LAS_MAX_VIDEOS} 个")
    if not script or not script.strip():
        raise ValueError("script（创作指令）不能为空")
    if len(script) > LAS_SCRIPT_MAX_LEN:
        raise ValueError(f"script 不能超过 {LAS_SCRIPT_MAX_LEN} 字")

    las_idempotent_id = idempotent_id or f"las-{uuid.uuid4().hex[:16]}"
    job_id = f"las-{uuid.uuid4().hex[:16]}"

    # 调 LAS 提交
    client = get_las_speech_auto_client()
    try:
        resp = client.submit(
            video_urls=video_urls,
            script=script,
            template=template,
            render_video=True,
            output_tos_path=output_tos_path,
            idempotent_id=las_idempotent_id,
        )
    except LASError as exc:
        logger.warning(
            "ai_edit_las_submit_failed merchant_id=%s error=%s business_code=%s",
            merchant_id, exc, exc.metadata.get("business_code"),
        )
        raise

    las_task_id = resp.get("metadata", {}).get("task_id")
    if not las_task_id:
        raise LASError("LAS 提交响应缺少 task_id", metadata=resp.get("metadata"))

    job = AiEditJob(
        merchant_id=merchant_id,
        job_id=job_id,
        status="processing",
        source_type="las_speech_auto",
        stage="submitted",
        progress=0,
        attempt_count=1,
        # 持久化提交参数，失败后可回溯 video_urls/script/template（input_json 为 jsonb 列）
        input_json=json.dumps(
            {"video_urls": video_urls, "script": script, "template": template},
            ensure_ascii=False,
        ),
        las_task_id=las_task_id,
        las_idempotent_id=las_idempotent_id,
        las_script=script,
        las_template=template,
        las_metadata_json=str(resp.get("metadata", {})),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "ai_edit_las_job_created job_id=%s las_task_id=%s merchant_id=%s",
        job.id, las_task_id, merchant_id,
    )
    return job


def process_las_job(job_id: int) -> None:
    """轮询 LAS 任务到终态，写库 + COMPLETED 时存产物。后台任务调用。"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(AiEditJob).filter(AiEditJob.id == job_id).first()
        if job is None or not job.las_task_id:
            logger.warning("ai_edit_las_process_skip reason=no_job_or_task_id job_id=%s", job_id)
            return

        client = get_las_speech_auto_client()
        # 进度回写（非终态时更新 stage）
        def _on_progress(status: str) -> None:
            try:
                job.stage = status.lower() if status else "running"
                job.las_metadata_json = str({"task_status": status})
                db.commit()
            except Exception:  # noqa: BLE001 进度回写失败不阻断轮询
                db.rollback()

        try:
            result = client.wait_for_terminal(job.las_task_id, on_progress=_on_progress)
        except LASError as exc:
            job.status = "failed"
            job.failure_code = "las_wait_timeout"
            job.las_error_msg = str(exc)
            job.las_metadata_json = str(exc.metadata)
            job.completed_at = datetime.now()
            db.commit()
            logger.warning("ai_edit_las_timeout job_id=%s las_task_id=%s", job_id, job.las_task_id)
            return

        metadata = result.get("metadata", {})
        task_status = metadata.get("task_status")
        job.las_metadata_json = str(metadata)
        job.las_business_code = str(metadata.get("business_code", ""))
        job.las_error_msg = metadata.get("error_msg")

        if task_status != "COMPLETED":
            job.status = "failed"
            job.failure_code = f"las_{str(task_status).lower()}"
            job.completed_at = datetime.now()
            db.commit()
            logger.warning("ai_edit_las_failed job_id=%s task_status=%s", job_id, task_status)
            return

        # COMPLETED：存产物到 artifacts
        data = result.get("data") or {}
        artifacts = data.get("artifacts") or {}
        _persist_artifacts(db, job, artifacts)
        # 结果交付闭环：归档最终视频到自有 TOS（subtitled 优先 clean 回退）
        archived = archive_final_video(db, job, artifacts)
        # 视频能力标签（基于真实处理模式，不依赖完成状态）
        job.video_tags = json.dumps(compute_video_tags(job, artifacts), ensure_ascii=False)
        # 标题生成（确定性规则 + 兜底，失败不影响完成）
        if not job.title:
            _fill_job_title(db, job, artifacts)
        # 归档成功才标 succeeded；归档失败保留 delivery_status=failed，任务不可交付
        job.status = "succeeded" if archived else "failed"
        job.stage = "completed"
        job.progress = 100
        job.failure_code = None if archived else "archive_failed"
        job.completed_at = datetime.now()
        job.las_metadata_json = str(metadata)
        db.commit()
        if archived:
            _report_las_compute_usage(db, job)
            logger.info("ai_edit_las_succeeded job_id=%s artifacts=%s archived=true", job_id, len(artifacts))
        else:
            logger.warning("ai_edit_las_completed_but_not_archived job_id=%s", job_id)
    except Exception as exc:  # noqa: BLE001 后台任务异常不向上抛
        db.rollback()
        logger.error("ai_edit_las_process_error job_id=%s error_type=%s", job_id, type(exc).__name__, exc_info=True)
    finally:
        db.close()


def _persist_artifacts(db: Session, job: AiEditJob, artifacts: dict[str, Any]) -> None:
    """把 LAS 产物元信息存到 AiEditJobArtifact。

    storage_key 契约（R1 修复）：只保存稳定的对象标识（LAS tos_path），
    绝不写入 LAS 临时 HTTPS 签名 URL（3 天过期，不可作永久键）。
    无 tos_path 时 storage_key 留 NULL，临时 URL 仅在归档流程内临时使用。
    """
    # 清理旧产物（重试场景）。job_id 列为 String(64)，存 AiEditJob.job_id 字符串，
    # 不可用 Integer 主键 job.id 比较（PG 下 varchar=integer 报 UndefinedFunction）
    db.query(AiEditJobArtifact).filter(AiEditJobArtifact.job_id == job.job_id).delete()
    for field in DOWNLOAD_FIELDS:
        url = artifacts.get(field)
        tos_path = artifacts.get(field.replace("_url", "_tos_path"))
        if not url and not tos_path:
            continue
        artifact_type = field.replace("_url", "")  # video_subtitled / video_clean / subtitle_srt / match_scheme / result_json
        artifact = AiEditJobArtifact(
            artifact_id=f"{job.job_id}-{artifact_type}",
            job_id=job.job_id,
            merchant_id=job.merchant_id,
            artifact_type=artifact_type,
            # R1：只存 tos_path（稳定对象键），临时 HTTPS url 不入 storage_key
            storage_key=tos_path if tos_path else None,
            file_name=artifact_type,
            location_type="cloud",
        )
        db.add(artifact)


def archive_final_video(db: Session, job: AiEditJob, artifacts: dict[str, Any]) -> bool:
    """把 LAS 最终视频归档到自有 TOS，标记交付状态。幂等。

    选择顺序：video_subtitled_url 优先，video_clean_url 回退。
    用 LAS 临时 https url 下载到受控临时文件，流式上传到自有 TOS，
    对象键 ai-edit/{merchant_id}/{job_id}/final.mp4。
    成功返回 True，失败返回 False（记录 delivery_status=failed，不抛异常阻断主链路）。
    """
    # 幂等：已归档则跳过
    existing = (
        db.query(AiEditJobArtifact)
        .filter(
            AiEditJobArtifact.job_id == job.job_id,
            AiEditJobArtifact.is_final_video.is_(True),
            AiEditJobArtifact.delivery_status == "archived",
        )
        .first()
    )
    if existing is not None:
        logger.info("ai_edit_archive_skip reason=already_archived job_id=%s", job.job_id)
        return True

    # 选择最终视频（subtitled 优先，clean 回退）
    chosen_field = None
    chosen_url = None
    for field in FINAL_VIDEO_FIELDS:
        url = artifacts.get(field)
        if url and str(url).startswith("http"):
            chosen_field = field
            chosen_url = url
            break
    if not chosen_url:
        job.delivery_status = "failed"
        db.commit()
        logger.warning("ai_edit_archive_failed reason=no_final_video job_id=%s", job.job_id)
        return False

    # 标记最终视频 artifact（清理旧标记，重置归档状态）。
    # _persist_artifacts 用 db.add 新建行未 commit，这里先 flush 让新行落库，
    # 避免 session 内 pending 对象与 bulk update 冲突导致后续字段更新丢失。
    chosen_artifact_type = chosen_field.replace("_url", "")
    db.flush()
    db.query(AiEditJobArtifact).filter(
        AiEditJobArtifact.job_id == job.job_id
    ).update(
        {AiEditJobArtifact.is_final_video: False},
        synchronize_session=False,
    )
    db.flush()
    # 查询前 expire_all，确保拿到 DB 真实状态而非 session 缓存的 pending 对象
    db.expire_all()
    final_artifact = (
        db.query(AiEditJobArtifact)
        .filter(
            AiEditJobArtifact.job_id == job.job_id,
            AiEditJobArtifact.artifact_type == chosen_artifact_type,
        )
        .first()
    )

    object_key = f"ai-edit/{job.merchant_id}/{job.job_id}/final.mp4"
    temp_path = None
    try:
        # 流式下载 LAS 临时 https 到受控临时文件
        temp_path, file_size = TOSUploader.download_https_to_temp(chosen_url)
        # 流式上传到自有 TOS
        uploader = TOSUploader()
        uploader.upload_file_stream(temp_path, object_key, content_type="video/mp4")

        # 持久化自有对象键与归档状态
        if final_artifact is not None:
            final_artifact.is_final_video = True
            final_artifact.delivery_status = "archived"
            final_artifact.archive_object_key = object_key
            final_artifact.file_size_bytes = file_size
            final_artifact.archive_error = None
        job.delivery_status = "archived"
        db.commit()
        logger.info(
            "ai_edit_archived job_id=%s object_key=%s size=%s source=%s",
            job.job_id, object_key, file_size, chosen_artifact_type,
        )
        return True
    except (UploadError, Exception) as exc:  # noqa: BLE001 归档失败不阻断 LAS 已完成
        db.rollback()
        # 重新查询后标记失败（rollback 后原对象可能 expired）
        fa = (
            db.query(AiEditJobArtifact)
            .filter(
                AiEditJobArtifact.job_id == job.job_id,
                AiEditJobArtifact.artifact_type == chosen_artifact_type,
            )
            .first()
        )
        if fa is not None:
            fa.is_final_video = True
            fa.delivery_status = "failed"
            fa.archive_error = f"{type(exc).__name__}: {exc}"[:1000]
        job = db.merge(job)  # 重新 attach
        job.delivery_status = "failed"
        db.commit()
        logger.error(
            "ai_edit_archive_error job_id=%s object_key=%s error_type=%s",
            job.job_id, object_key, type(exc).__name__, exc_info=True,
        )
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def compute_video_tags(job: AiEditJob, artifacts: dict[str, Any]) -> list[str]:
    """根据任务真实配置与处理模式计算视频能力标签（不依赖完成状态）。

    当前 las_video_remix v1 speech_auto + automotive_headtalk 链路：
    - script_driven：有创作指令（las_script 非空）→ 口播文案驱动
    - ai_subtitle：生成字幕产物（subtitle_srt_url 非空）→ AI智能字幕
    - ai_clip_matching：speech_auto 空镜匹配（template=automotive_headtalk）→ AI片段拼接
    没有执行的能力不返回对应标签。
    """
    tags: list[str] = []
    if job.las_script and job.las_script.strip():
        tags.append("script_driven")
    if artifacts.get("subtitle_srt_url"):
        tags.append("ai_subtitle")
    if job.las_template == LAS_TEMPLATE:
        tags.append("ai_clip_matching")
    return tags


# 标题生成：确定性规则，无 LLM，不编造信息
_TITLE_MAX = 24
_TITLE_MIN = 8


def _clean_title_text(text: str) -> str:
    """清洗标题文本：去换行/多余空白/句首句尾标点，截断到合理长度。"""
    text = re.sub(r"[\r\n\t]+", " ", text).strip()
    text = re.sub(r"\s+", " ", text)
    # 截断到最后一个完整标点或字数上限
    if len(text) > _TITLE_MAX:
        # 优先在标点处截断
        for sep in ("。", "，", "！", "？", "、", "；", "."):
            idx = text[:_TITLE_MAX].rfind(sep)
            if idx >= _TITLE_MIN:
                text = text[:idx]
                break
        else:
            text = text[:_TITLE_MAX]
    return text.strip(" 。！？，、；.\"" "'")


def _fill_job_title(db: Session, job: AiEditJob, artifacts: dict[str, Any]) -> None:
    """确定性标题生成，失败兜底'混剪任务 #id'，不影响视频完成。

    优先级（R2 复核：ASR 优先，script 是模板指令不适合做标题）：
    车辆结构化信息（暂无）→ ASR（match_scheme.units.text，真实口播内容）
    → 口播文案（las_script，仅作兜底）→ 原始素材文件名 → 兜底。
    """
    # 1. ASR 文本（真实口播内容，优先）—— 下载 result_json 取 match_scheme.units.text
    try:
        result_url = artifacts.get("result_json_url")
        if result_url and str(result_url).startswith("http"):
            resp = requests.get(result_url, timeout=30)
            resp.raise_for_status()
            result_data = resp.json()
            units = (result_data.get("match_scheme") or {}).get("units") or []
            asr_texts = [u.get("text", "") for u in units if u.get("text")]
            if asr_texts:
                asr_text = _clean_title_text(" ".join(asr_texts))
                if len(asr_text) >= _TITLE_MIN:
                    job.title = asr_text
                    job.title_source = "asr"
                    job.title_generated_at = datetime.now()
                    return
    except Exception:  # noqa: BLE001 ASR 提取失败不阻断
        logger.debug("ai_edit_title_asr_failed job_id=%s", job.job_id, exc_info=True)

    # 2. 口播文案（las_script）—— 仅作兜底（script 是模板化指令，所有任务可能相同）
    if job.las_script and job.las_script.strip():
        script_title = _clean_title_text(job.las_script)
        if len(script_title) >= _TITLE_MIN:
            job.title = script_title
            job.title_source = "script"
            job.title_generated_at = datetime.now()
            return

    # 3. 原始素材文件名
    try:
        input_data = json.loads(job.input_json) if job.input_json else {}
        video_urls = input_data.get("video_urls") or []
        if isinstance(video_urls, list) and video_urls:
            first_url = str(video_urls[0])
            fname = os.path.basename(first_url.split("?")[0])
            fname = os.path.splitext(fname)[0]
            # 去掉常见前缀编号如 client_001
            fname = re.sub(r"^(client|second_client|third_client|fourth_client)_\d+", "", fname)
            fname = _clean_title_text(fname)
            if len(fname) >= _TITLE_MIN:
                job.title = fname
                job.title_source = "filename"
                job.title_generated_at = datetime.now()
                return
    except Exception:  # noqa: BLE001
        pass

    # 4. 兜底
    job.title = f"混剪任务 #{job.id}"
    job.title_source = "fallback"
    job.title_generated_at = datetime.now()


def list_las_jobs(
    db: Session,
    *,
    merchant_id: str,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """查 LAS 混剪任务列表（商户隔离，分页 + 状态筛选 + 标题搜索）。

    搜索作用于全部任务（先过滤再分页），排除软删除任务。
    """
    query = (
        db.query(AiEditJob)
        .filter(AiEditJob.merchant_id == merchant_id)
        .filter(AiEditJob.source_type == "las_speech_auto")
        .filter(AiEditJob.deleted_at.is_(None))
    )
    if status:
        query = query.filter(AiEditJob.status == status)
    if keyword and keyword.strip():
        kw = keyword.strip()
        query = query.filter(AiEditJob.title.ilike(f"%{kw}%"))
    total = query.count()
    rows = (
        query.order_by(AiEditJob.created_at.desc(), AiEditJob.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_las_job_summary(db, j) for j in rows],
    }


def _las_job_summary(db: Session, job: AiEditJob) -> dict[str, Any]:
    """单条任务摘要（列表项，不暴露 tos:// 或内部对象键）。

    商户端只看到标题/状态/标签/是否有可交付视频/时间，播放下载走专门接口。
    """
    has_final_video = (
        db.query(AiEditJobArtifact)
        .filter(
            AiEditJobArtifact.job_id == job.job_id,
            AiEditJobArtifact.is_final_video.is_(True),
            AiEditJobArtifact.delivery_status == "archived",
        )
        .count()
        > 0
    )
    # 素材数量 + 预估耗时（按素材数量估算，供前端伪进度条展示）
    material_count = 0
    if job.input_json:
        try:
            input_data = json.loads(job.input_json)
            urls = input_data.get("video_urls") or []
            material_count = len(urls) if isinstance(urls, list) else (1 if isinstance(urls, str) else 0)
        except (TypeError, ValueError):
            pass
    # 预估：LAS speech_auto 实测 5 素材→16分钟，按 N×60s + 180s 基础估算；
    # 最少 180s，区间±50%（前端展示 N~M 分钟）。仅作伪进度参考，不影响实际完成判断。
    base_est = max(180, material_count * 60 + 180)
    return {
        "job_id": job.id,
        "title": job.title or f"混剪任务 #{job.id}",
        "status": job.status,
        "delivery_status": job.delivery_status,
        "stage": job.stage,
        "progress": job.progress,
        "video_tags": _parse_video_tags(job.video_tags),
        "has_final_video": has_final_video,
        "material_count": material_count,
        "estimated_seconds": base_est,
        "error_message": job.las_error_msg,
        "failure_code": job.failure_code,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _parse_video_tags(video_tags_json: str | None) -> list[str]:
    """解析 video_tags JSON 字符串为列表，失败返回空。"""
    if not video_tags_json:
        return []
    try:
        tags = json.loads(video_tags_json)
        return tags if isinstance(tags, list) else []
    except (TypeError, ValueError):
        return []


def get_las_job_status(db: Session, *, merchant_id: str, job_id: int) -> dict[str, Any] | None:
    """查 LAS 任务状态（脱敏：不返回 tos:// 或内部对象键，播放下载走专门接口）。"""
    job = _get_owned_job(db, merchant_id=merchant_id, job_id=job_id)
    if job is None:
        return None
    return _las_job_summary(db, job)


def _get_owned_job(db: Session, *, merchant_id: str, job_id: int) -> AiEditJob | None:
    """取商户归属且未软删除的任务（跨商户返回 None，不暴露存在性）。"""
    return (
        db.query(AiEditJob)
        .filter(AiEditJob.id == job_id)
        .filter(AiEditJob.merchant_id == merchant_id)
        .filter(AiEditJob.source_type == "las_speech_auto")
        .filter(AiEditJob.deleted_at.is_(None))
        .first()
    )


def _get_archived_final_artifact(db: Session, job: AiEditJob) -> AiEditJobArtifact | None:
    """取已归档的最终视频 artifact（未归档或已删除返回 None）。"""
    return (
        db.query(AiEditJobArtifact)
        .filter(
            AiEditJobArtifact.job_id == job.job_id,
            AiEditJobArtifact.is_final_video.is_(True),
            AiEditJobArtifact.delivery_status == "archived",
        )
        .first()
    )


def generate_playback_url(db: Session, *, merchant_id: str, job_id: int) -> str | None:
    """为最终归档视频生成短期预签名 https 播放 URL（不持久化）。

    校验：商户归属、未删除、已完成、最终视频已归档。
    """
    job = _get_owned_job(db, merchant_id=merchant_id, job_id=job_id)
    if job is None or job.status != "succeeded" or job.delivery_status != "archived":
        return None
    artifact = _get_archived_final_artifact(db, job)
    if artifact is None or not artifact.archive_object_key:
        return None
    uploader = TOSUploader()
    return uploader.presign(artifact.archive_object_key)


def safe_filename(title: str, job_id: int) -> str:
    """安全清洗任务标题为下载文件名：去路径分隔符/控制字符，兜底 job_id。"""
    import re as _re

    name = (title or "").strip()
    # 去除路径分隔符、控制字符、Windows 非法字符
    name = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = _re.sub(r"\s+", " ", name).strip()
    if not name:
        name = f"混剪任务 #{job_id}"
    # 限制长度避免文件名过长
    if len(name) > 60:
        name = name[:60]
    return f"{name}.mp4"


def get_job_title(db: Session, *, merchant_id: str, job_id: int) -> str | None:
    """取任务标题（供下载文件名用，商户归属校验）。"""
    job = _get_owned_job(db, merchant_id=merchant_id, job_id=job_id)
    if job is None:
        return None
    return job.title or f"混剪任务 #{job.id}"


def delete_las_job(db: Session, *, merchant_id: str, job_id: int, operator_id: str) -> dict[str, Any]:
    """删除任务：软删除 + 清理自有 TOS 归档视频。幂等。

    返回 {deleted: bool, status: str}。已删除重复调用返回 deleted=True（幂等）。
    删除自有 TOS 失败时标 delete_failed，但已禁用访问（播放下载拒绝）。
    不删除用户原始素材、不操作 LAS 远端 bucket。
    """
    job = (
        db.query(AiEditJob)
        .filter(AiEditJob.id == job_id)
        .filter(AiEditJob.merchant_id == merchant_id)
        .filter(AiEditJob.source_type == "las_speech_auto")
        .first()
    )
    if job is None:
        return {"deleted": False, "status": "not_found"}
    # 幂等：已删除直接返回
    if job.deleted_at is not None and job.delete_status == "deleted":
        return {"deleted": True, "status": "already_deleted"}

    # 先软删除禁用访问（即使物理清理失败，播放下载也会拒绝）
    job.deleted_at = datetime.now()
    job.deleted_by = operator_id
    job.delete_status = "deleting"
    db.commit()

    # 清理自有 TOS 归档视频
    artifact = _get_archived_final_artifact(db, job)
    cleanup_failed = False
    if artifact is not None and artifact.archive_object_key:
        try:
            uploader = TOSUploader()
            uploader.delete_object(artifact.archive_object_key)
        except UploadError as exc:
            cleanup_failed = True
            job.delete_error = f"tos_delete_failed: {exc}"[:1000]
            logger.warning("ai_edit_delete_tos_failed job_id=%s key=%s err=%s", job_id, artifact.archive_object_key, exc)
        except Exception as exc:  # noqa: BLE001
            cleanup_failed = True
            job.delete_error = f"tos_delete_unknown: {type(exc).__name__}: {exc}"[:1000]
            logger.warning("ai_edit_delete_tos_failed job_id=%s err_type=%s", job_id, type(exc).__name__, exc_info=True)

    if cleanup_failed:
        job.delete_status = "delete_failed"
    else:
        job.delete_status = "deleted"
        job.delete_error = None
    db.commit()
    logger.info(
        "ai_edit_deleted job_id=%s operator=%s status=%s tos_cleanup=%s",
        job_id, operator_id, job.delete_status, "failed" if cleanup_failed else "ok",
    )
    return {"deleted": True, "status": job.delete_status}


# 短期下载 token：HMAC 签名 {job_id}:{merchant_id}:{exp}，TTL 内有效。
# 让前端 <a href> 原生下载带进度条，token query 参数鉴权绕过 header 要求
# （浏览器 <a> 无法附加 Authorization header，故用 token query 替代）。
# 注意：token 在 TTL（120s）内可被重放（query 参数会进浏览器历史/访问日志/Referer），
# 这是支持原生下载的已知 tradeoff；如需真一次性消费，升级路径为 payload 加 jti
# 后用 Redis SETNX 一次性标记（当前未引入 Redis 持久化，按 YAGNI 暂不实现）。
_DOWNLOAD_TOKEN_TTL = 120  # 秒


def _download_signing_secret() -> str:
    """下载 token 签名密钥：复用 DY_SECRET_KEY（生产 webhook 验签同源）。

    fail-closed：DY_SECRET_KEY 未配置时抛 RuntimeError 拒绝签发/校验，
    绝不退化为硬编码公开值（否则攻击者可按同款算法自行签发任意商户 token）。
    """
    secret = config.DY_SECRET_KEY
    if not secret:
        logger.error("ai_edit_download_secret_missing DY_SECRET_KEY 未配置，下载 token 不可用")
        raise RuntimeError("DY_SECRET_KEY 未配置，下载 token 不可用")
    return secret


def generate_download_token(job_id: int, merchant_id: str) -> str:
    """生成短期下载 token（绑定 job_id + merchant_id，TTL 内有效）。"""
    import base64

    exp = int(time.time()) + _DOWNLOAD_TOKEN_TTL
    payload = f"{job_id}:{merchant_id}:{exp}"
    sig = hmac.new(_download_signing_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    # token = base64(payload) + "." + sig（用 urlsafe，避免特殊字符）
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def verify_download_token(token: str, job_id: int, merchant_id: str) -> bool:
    """验证短期下载 token：签名匹配 + 未过期 + job/merchant 匹配。

    secret 缺失（配置错误）时 _download_signing_secret 抛 RuntimeError，此处捕获取
    转 False（安全拒绝下载，而非 500）；generate 路径不 catch，让签发接口 500 暴露问题。
    """
    try:
        import base64

        payload_b64, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64).decode()
        expected_sig = hmac.new(_download_signing_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        parts = payload.split(":")
        if len(parts) != 3:
            return False
        t_job_id, t_merchant_id, t_exp = parts
        if int(t_job_id) != job_id or t_merchant_id != merchant_id:
            return False
        if int(t_exp) < int(time.time()):
            return False
        return True
    except (ValueError, IndexError, TypeError, RuntimeError):
        return False


def _report_las_compute_usage(db: Session, job: AiEditJob) -> None:
    """LAS 混剪任务成功后上报算力消耗（capability_key=ai_edit，方案 A 专属）。

    估算口径：按 script 字符数 ÷2 估算 token（视频混剪消耗主要在云端算子，
    此处仅作商户侧配额/展示用，非 LAS 实际计费）。失败/blocked 不扣。
    上报异常不影响主流程。

    P1 Stage 3：传入 idempotency_key=las_job:{job.id}:archive_usage，
    防止异常重入重复扣算力。event_namespace=las_job（稳定合同）。
    """
    script = str(job.las_script or "").strip()
    if not script:
        return
    tokens = max(1, len(script) // 2)
    try:
        from app.services.compute_service import record_usage as _record_usage

        _record_usage(
            db,
            job.merchant_id,
            tokens,
            capability_key="ai_edit",
            source="other",
            model="las-speech-auto",
            remark=f"AI剪辑 LAS 任务 job_id={job.id}",
            usage_measurement_method="estimated_tokens",
            idempotency_key=f"las_job:{job.id}:archive_usage",
        )
    except Exception as exc:  # noqa: BLE001 算力上报失败不阻断任务
        logger.warning("ai_edit_las_compute_usage stage=report_error job_id=%s error=%s", job.id, exc)

