"""AI剪辑 LAS 视频混剪编排服务（三模式）。

职责（纯 LAS 云端方案）：
- create_las_job：创建 AiEditJob + 调 LAS submit + 写 las_task_id，入轮询队列。
- process_las_job：轮询 LAS wait_for_terminal + 终态写库 + COMPLETED 时存产物到 artifacts。
- get_las_job_status：查任务状态 + 产物（脱敏，不返回 tos_path 原始）。
- normalize_las_mode / normalize_las_template / validate_las_request：三模式规范化与
  规则校验（对齐接口文档 §3/§5/§6，fail-closed）。

不做本地 FFmpeg/9100 规划（纯 LAS 云端，能力迁移自 demo）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import requests
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import config
from app.models import AiEditJob, AiEditJobArtifact
from app.services.las_client import DOWNLOAD_FIELDS, LASError, get_las_speech_auto_client
from app.services.las_tos_uploader import TOSUploader, UploadError

logger = logging.getLogger(__name__)

# 行业模板：接受旧名 automotive_headtalk，发往 LAS 时规范化为 automotive（接口文档 §5.1）
LAS_TEMPLATE = "automotive_headtalk"
LAS_TEMPLATE_SEND = "automotive"
LAS_MAX_VIDEOS = 30
LAS_SCRIPT_MAX_LEN = 4000

# 三模式（接口文档 §3，旧名 speech_auto 仍可传，等价 marketing_headtalk）
MODE_MARKETING = "marketing_headtalk"      # 口播营销混剪
MODE_LONG_REAL = "long_real_shot"          # 长实拍流水
MODE_REAL_HEAD = "real_shot_headtalk"      # 实拍 + 口播复合成片
MODE_ALIAS_SPEECH_AUTO = "speech_auto"
LAS_MODES = {MODE_MARKETING, MODE_LONG_REAL, MODE_REAL_HEAD}

# 素材角色与分段（接口文档 §3/§5）
ROLE_SPEECH = "speech"
ROLE_VOICEOVER = "voiceover"
ROLE_BROLL = "broll"
SECTION_REAL_SHOT = "real_shot"
SECTION_HEADTALK = "headtalk"

# 各模式数量/时长限额（接口文档 §3/§6）
MARKETING_MAX_VIDEOS = 30
LONG_REAL_MAX_VIDEOS = 100
REAL_HEAD_TOTAL_MAX = 130       # 自动分段合计上限
REAL_HEAD_REAL_SHOT_MAX = 100   # 显式分段：实拍段上限
REAL_HEAD_HEADTALK_MAX = 30     # 显式分段：口播段上限
TARGET_DURATION_MIN = 10
TARGET_DURATION_MAX = 3600

# 最终视频选择顺序：subtitled 优先，clean 回退
FINAL_VIDEO_FIELDS = ("video_subtitled_url", "video_clean_url")


# ---------------------------------------------------------------------------
# 模式规范化与规则校验（接口文档 §3/§5/§6，fail-closed）
# ---------------------------------------------------------------------------


def normalize_las_mode(mode: str | None) -> str:
    """规范化 LAS mode：speech_auto→marketing_headtalk，缺失→marketing_headtalk。

    只做别名映射，不校验业务规则（业务规则在 validate_las_request）。
    非法 mode 抛 ValueError（信任边界输入校验）。
    """
    if not mode:
        return MODE_MARKETING
    m = mode.strip()
    if m == MODE_ALIAS_SPEECH_AUTO:
        return MODE_MARKETING
    if m not in LAS_MODES:
        raise ValueError(f"不支持的 mode：{mode}")
    return m


def normalize_las_template(template: str | None) -> str:
    """规范化 LAS template：automotive_headtalk→automotive（接口文档 §5.1）。"""
    t = (template or "").strip() or LAS_TEMPLATE
    if t == LAS_TEMPLATE:
        return LAS_TEMPLATE_SEND
    return t


# 素材地址协议白名单（接口文档 §5/§6：具体地址为 tos:// 或 HTTP(S)）
_URL_PROTOCOLS = ("tos://", "http://", "https://")


def _validate_url(url) -> str:
    """校验素材地址：非空、协议为 tos:// 或 http(s)://，返回 strip 后地址。

    fail-closed（信任边界输入校验）：空字符串、非白名单协议一律拒绝。
    """
    if not isinstance(url, str):
        raise ValueError("素材地址必须是字符串")
    url = url.strip()
    if not url:
        raise ValueError("素材地址不能为空")
    if not url.startswith(_URL_PROTOCOLS):
        raise ValueError("素材地址必须以 tos:// 或 http(s):// 开头")
    return url


def _normalize_video_item(item) -> dict:
    """把 video_urls 数组元素规范化为 {url, role, section}；裸 URL 等价 role=speech。

    fail-closed：空 URL / 非法协议 / 未知 role / 未知 section 一律拒绝
    （未知 role/section 在任何模式下都不接受，见接口文档 §3/§5）。
    """
    if isinstance(item, str):
        url = _validate_url(item)
        return {"url": url, "role": ROLE_SPEECH}
    if isinstance(item, dict):
        url = _validate_url(item.get("url"))
        out: dict = {"url": url}
        role = item.get("role")
        if role is not None:
            if role not in (ROLE_SPEECH, ROLE_VOICEOVER, ROLE_BROLL):
                raise ValueError(f"不支持的 role：{role}")
            out["role"] = role
        section = item.get("section")
        if section is not None:
            if section not in (SECTION_REAL_SHOT, SECTION_HEADTALK):
                raise ValueError(f"不支持的 section：{section}")
            out["section"] = section
        return out
    raise ValueError("video_urls 元素必须是字符串或 {url, role, section} 对象")


def validate_las_request(
    *,
    mode: str | None,
    video_urls,
    script: str,
    template: str | None,
    target_duration_sec: int | None,
    render_video: bool | None,
    video_edit_mode: str | None,
    smart_packaging: dict | None,
) -> dict:
    """校验并规范化 LAS 请求，返回可发送/持久化的 payload。

    规则（对齐接口文档 §3/§5/§6）：
    - mode：speech_auto→marketing_headtalk，缺失→marketing_headtalk。
    - template：automotive_headtalk→automotive。
    - render_video：缺失→true。
    - marketing_headtalk：≤30 条，禁 target_duration_sec，禁 section；
      role 取 speech/voiceover/broll。
    - long_real_shot：单字符串=TOS 目录前缀；数组 ≤100 条；支持
      target_duration_sec(10~3600)；role 取 speech/voiceover；禁 section/broll。
    - real_shot_headtalk：显式/自动分段二选一（section 要么全带要么全不带）；
      显式需两段非空 + 实拍段禁 broll + 全模式禁 voiceover + 分别 ≤100/≤30；
      自动需 ≥2 条 speech + 总数 ≤130；支持 target_duration_sec(10~3600)。
    - smart_packaging 只允许对象（子字段透传，不猜测）。
    违规抛 ValueError（router 转 HTTP 400）。
    """
    norm_mode = normalize_las_mode(mode)
    norm_template = normalize_las_template(template)

    if not script or not script.strip():
        raise ValueError("script（创作指令）不能为空")
    if len(script) > LAS_SCRIPT_MAX_LEN:
        raise ValueError(f"script 不能超过 {LAS_SCRIPT_MAX_LEN} 字")

    if isinstance(video_urls, str):
        # 单字符串（long_real_shot 的 TOS 目录前缀）也须通过地址校验
        items = [{"url": _validate_url(video_urls), "role": ROLE_SPEECH}]
        is_prefix_string = True
    elif isinstance(video_urls, list):
        if not video_urls:
            raise ValueError("video_urls 不能为空")
        items = [_normalize_video_item(i) for i in video_urls]
        is_prefix_string = False
    else:
        raise ValueError("video_urls 必须是字符串（TOS 目录前缀）或数组")

    if target_duration_sec is not None and not (
        TARGET_DURATION_MIN <= target_duration_sec <= TARGET_DURATION_MAX
    ):
        raise ValueError(
            f"target_duration_sec 必须在 {TARGET_DURATION_MIN}~{TARGET_DURATION_MAX} 秒之间"
        )

    if norm_mode == MODE_MARKETING:
        if len(items) > MARKETING_MAX_VIDEOS:
            raise ValueError(f"口播营销模式最多 {MARKETING_MAX_VIDEOS} 条素材")
        if target_duration_sec is not None:
            raise ValueError("口播营销模式不支持 target_duration_sec")
        for it in items:
            role = it.get("role", ROLE_SPEECH)
            if role not in (ROLE_SPEECH, ROLE_VOICEOVER, ROLE_BROLL):
                raise ValueError(f"不支持的 role：{role}")
            if "section" in it:
                raise ValueError("口播营销模式不支持 section")

    elif norm_mode == MODE_LONG_REAL:
        # 单字符串 = TOS 目录前缀（由服务列举），不限制条数
        if not is_prefix_string and len(items) > LONG_REAL_MAX_VIDEOS:
            raise ValueError(f"长实拍模式最多 {LONG_REAL_MAX_VIDEOS} 条素材")
        for it in items:
            role = it.get("role", ROLE_SPEECH)
            if role not in (ROLE_SPEECH, ROLE_VOICEOVER):
                raise ValueError("长实拍模式不接受 role=broll")
            if "section" in it:
                raise ValueError("长实拍模式不支持 section")

    else:  # real_shot_headtalk
        sections = [it.get("section") for it in items]
        has_section = [s for s in sections if s is not None]
        if has_section and len(has_section) != len(items):
            raise ValueError("section 必须全部素材都带或全部都不带，不能只标一部分")
        if has_section:
            # 显式分段
            for it in items:
                s = it.get("section")
                if s not in (SECTION_REAL_SHOT, SECTION_HEADTALK):
                    raise ValueError(f"不支持的 section：{s}")
            real_shot = [it for it in items if it.get("section") == SECTION_REAL_SHOT]
            headtalk = [it for it in items if it.get("section") == SECTION_HEADTALK]
            if not real_shot:
                raise ValueError("实拍+口播模式至少需要一条 section=real_shot 素材")
            if not any(
                it.get("section") == SECTION_HEADTALK
                and it.get("role", ROLE_SPEECH) == ROLE_SPEECH
                for it in headtalk
            ):
                raise ValueError("实拍+口播模式至少需要一条 section=headtalk 且 role=speech 素材")
            if len(real_shot) > REAL_HEAD_REAL_SHOT_MAX:
                raise ValueError(f"实拍段最多 {REAL_HEAD_REAL_SHOT_MAX} 条素材")
            if len(headtalk) > REAL_HEAD_HEADTALK_MAX:
                raise ValueError(f"口播段最多 {REAL_HEAD_HEADTALK_MAX} 条素材")
            for it in items:
                role = it.get("role", ROLE_SPEECH)
                if role == ROLE_VOICEOVER:
                    raise ValueError("实拍+口播模式不支持 role=voiceover")
                if it.get("section") == SECTION_REAL_SHOT and role == ROLE_BROLL:
                    raise ValueError("实拍段（section=real_shot）不接受 role=broll")
        else:
            # 自动分段
            if len(items) > REAL_HEAD_TOTAL_MAX:
                raise ValueError(f"自动分段素材总数不能超过 {REAL_HEAD_TOTAL_MAX} 条")
            speech_count = sum(1 for it in items if it.get("role", ROLE_SPEECH) == ROLE_SPEECH)
            if speech_count < 2:
                raise ValueError("自动分段至少需要 2 条 role=speech 素材")
            for it in items:
                if it.get("role", ROLE_SPEECH) == ROLE_VOICEOVER:
                    raise ValueError("实拍+口播模式不支持 role=voiceover")

    if video_edit_mode is not None and video_edit_mode not in ("lite", "pro"):
        raise ValueError("video_edit_mode 只能是 lite 或 pro")
    if smart_packaging is not None and not isinstance(smart_packaging, dict):
        raise ValueError("smart_packaging 必须是对象")

    render = True if render_video is None else bool(render_video)

    # 发送给 LAS 的 video_urls：字符串（TOS 目录前缀）原样透传，数组用规范化对象
    las_video_urls = video_urls if isinstance(video_urls, str) else items

    return {
        "mode": norm_mode,
        "template": norm_template,
        "script": script,
        "video_urls": las_video_urls,
        "items": items,
        "render_video": render,
        "target_duration_sec": target_duration_sec,
        "video_edit_mode": video_edit_mode,
        "smart_packaging": smart_packaging,
    }


def create_las_job(
    db: Session,
    *,
    merchant_id: str,
    video_urls,
    script: str,
    template: str = LAS_TEMPLATE,
    mode: str | None = None,
    target_duration_sec: int | None = None,
    video_edit_mode: str | None = None,
    render_video: bool | None = None,
    smart_packaging: dict | None = None,
    output_tos_path: str | None = None,
    idempotent_id: str | None = None,
) -> AiEditJob:
    """创建 LAS 混剪任务：规范化校验 → 组装参数 → 调 LAS submit → 写库 las_task_id。

    幂等：复用传入 idempotent_id（持久化 las_idempotent_id），网络重试用同 id 不重复创建。
    三模式规范化（speech_auto→marketing_headtalk 等）与规则校验见
    normalize_las_mode / normalize_las_template / validate_las_request。
    """
    # 规范化 + 规则校验（对齐接口文档 §3/§5/§6，fail-closed；违规抛 ValueError）
    payload = validate_las_request(
        mode=mode,
        video_urls=video_urls,
        script=script,
        template=template,
        target_duration_sec=target_duration_sec,
        render_video=render_video,
        video_edit_mode=video_edit_mode,
        smart_packaging=smart_packaging,
    )

    las_idempotent_id = idempotent_id or f"las-{uuid.uuid4().hex[:16]}"
    job_id = f"las-{uuid.uuid4().hex[:16]}"

    # 调 LAS 提交
    client = get_las_speech_auto_client()
    try:
        resp = client.submit(
            video_urls=payload["video_urls"],
            script=payload["script"],
            template=payload["template"],
            mode=payload["mode"],
            render_video=payload["render_video"],
            output_tos_path=output_tos_path,
            idempotent_id=las_idempotent_id,
            target_duration_sec=payload["target_duration_sec"],
            video_edit_mode=payload["video_edit_mode"],
            smart_packaging=payload["smart_packaging"],
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
        # 提交即写心跳：启动恢复扫描只重入队心跳超时/缺失的任务，避免把刚提交的新任务误判为 stale
        heartbeat_at=datetime.now(),
        # 持久化完整规范化请求，失败后可回溯（input_json 为 jsonb 列）。
        # idempotent_id 继续用专用字段 las_idempotent_id，不重复写入 input_json。
        input_json=json.dumps(
            {
                "mode": payload["mode"],
                "template": payload["template"],
                "script": payload["script"],
                "video_urls": payload["video_urls"],
                "render_video": payload["render_video"],
                "target_duration_sec": payload["target_duration_sec"],
                "video_edit_mode": payload["video_edit_mode"],
                "smart_packaging": payload["smart_packaging"],
                "output_tos_path": output_tos_path,
            },
            ensure_ascii=False,
        ),
        las_task_id=las_task_id,
        las_idempotent_id=las_idempotent_id,
        las_script=script,
        las_template=payload["template"],
        las_metadata_json=str(resp.get("metadata", {})),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "ai_edit_las_job_created job_id=%s las_task_id=%s merchant_id=%s mode=%s",
        job.id, las_task_id, merchant_id, payload["mode"],
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
        # 进度回写（非终态时更新 stage + 心跳）
        def _on_progress(status: str) -> None:
            try:
                job.stage = status.lower() if status else "running"
                job.las_metadata_json = str({"task_status": status})
                # 心跳证明轮询线程存活；启动恢复扫描据此区分“线程已死”与“LAS 仍在生成”
                job.heartbeat_at = datetime.now()
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
        # render_video=false（接口文档 §5：只出剪辑方案不渲染，用于快速验证 script）：
        # 方案型成功，不触发视频归档，也不因无最终视频而失败。
        render_video = _job_render_video(db, job)
        deliverable = True
        if render_video:
            # 结果交付闭环：归档最终视频到自有 TOS（subtitled 优先 clean 回退）
            deliverable = archive_final_video(db, job, artifacts)
        # 视频能力标签（基于真实处理模式，不依赖完成状态）
        job.video_tags = json.dumps(compute_video_tags(job, artifacts), ensure_ascii=False)
        # 标题生成（确定性规则 + 兜底，失败不影响完成）
        if not job.title:
            _fill_job_title(db, job, artifacts)
        # 归档成功（或 render_video=false 方案型成功）才标 succeeded；
        # 仅 render_video=true 且归档失败时 delivery_status=failed，任务不可交付
        job.status = "succeeded" if deliverable else "failed"
        job.stage = "completed"
        job.progress = 100
        job.failure_code = None if deliverable else "archive_failed"
        job.completed_at = datetime.now()
        job.las_metadata_json = str(metadata)
        db.commit()
        if deliverable:
            _report_las_compute_usage(db, job)
            logger.info(
                "ai_edit_las_succeeded job_id=%s artifacts=%s render_video=%s archived=%s",
                job_id, len(artifacts), render_video, render_video and deliverable,
            )
        else:
            logger.warning("ai_edit_las_completed_but_not_archived job_id=%s", job_id)
    except Exception as exc:  # noqa: BLE001 后台任务异常不向上抛
        db.rollback()
        logger.error("ai_edit_las_process_error job_id=%s error_type=%s", job_id, type(exc).__name__, exc_info=True)
    finally:
        db.close()


# 模块级非阻塞锁：保证 LAS 恢复扫描单飞（启动线程 + 手动调用互斥）
_RESUME_LOCK = threading.Lock()


def resume_stale_las_jobs() -> None:
    """启动一次性恢复：重新轮询因进程重启而中断的 LAS 任务（单飞，不阻塞调用方）。

    背景：LAS 轮询用进程内 BackgroundTasks 线程，进程重启（部署 recreate/崩溃）会丢失在途
    轮询线程，任务永久停在 processing 且不会超时失败。本函数在服务启动时扫描
    status=processing 且 las_task_id 存在、且心跳缺失或超时（thread 已死）的任务，串行重新
    process_las_job——wait_for_terminal 首次 poll 即读到 LAS 终态并正确落库（COMPLETED 存产物 /
    FAILED 写失败码），从而自愈“生成中卡死”。

    复用 return_visit_reconcile 模式：模块级锁单飞、自管 Session、只处理启动时存在的快照；
    不建周期线程、不 sleep、不轮询。阈值 LAS_RESUME_STALE_SECONDS（默认 120s）远大于轮询
    间隔（15s），正常心跳不会误判。
    """
    if not _RESUME_LOCK.acquire(blocking=False):
        logger.info("ai_edit_las_resume stage=single_flight_skip")
        return
    try:
        from app.database import SessionLocal

        cutoff = datetime.now() - timedelta(seconds=config.LAS_RESUME_STALE_SECONDS)
        db = SessionLocal()
        try:
            stale = (
                db.query(AiEditJob)
                .filter(
                    AiEditJob.status == "processing",
                    AiEditJob.las_task_id.isnot(None),
                    or_(
                        AiEditJob.heartbeat_at.is_(None),
                        AiEditJob.heartbeat_at < cutoff,
                    ),
                )
                .order_by(AiEditJob.id.asc())
                .all()
            )
            job_ids = [j.id for j in stale]
        finally:
            db.close()

        if not job_ids:
            logger.info("ai_edit_las_resume stage=no_stale")
            return
        logger.warning("ai_edit_las_resume stage=resuming count=%s job_ids=%s", len(job_ids), job_ids)
        # 串行恢复：wait_for_terminal 阻塞本 daemon 线程直至终态/超时；stale 任务通常极少
        for job_id in job_ids:
            try:
                process_las_job(job_id)
            except Exception:  # noqa: BLE001 单个任务恢复失败不阻断其余
                logger.exception("ai_edit_las_resume job_id=%s error_type=unexpected", job_id)
    finally:
        _RESUME_LOCK.release()


def _job_render_video(db: Session, job: AiEditJob) -> bool:
    """从 input_json 读取 render_video，缺失按 True（默认渲染）。

    render_video=false（只出剪辑方案不渲染）时，COMPLETED 任务为方案型成功，
    不触发视频归档，也不因无最终视频而失败（接口文档 §5）。
    """
    try:
        input_data = json.loads(job.input_json) if job.input_json else {}
        rv = input_data.get("render_video")
        if isinstance(rv, bool):
            return rv
    except (TypeError, ValueError):
        pass
    return True


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

    当前 las_video_remix v1 三模式链路（marketing_headtalk 等）：
    - script_driven：有创作指令（las_script 非空）→ 口播文案驱动
    - ai_subtitle：生成字幕产物（subtitle_srt_url 非空）→ AI智能字幕
    - ai_clip_matching：空镜匹配（template=automotive/automotive_headtalk）→ AI片段拼接
    没有执行的能力不返回对应标签。
    """
    tags: list[str] = []
    if job.las_script and job.las_script.strip():
        tags.append("script_driven")
    if artifacts.get("subtitle_srt_url"):
        tags.append("ai_subtitle")
    # 兼容规范化后的 automotive 与历史 automotive_headtalk（新请求存 automotive）
    if job.las_template in (LAS_TEMPLATE, LAS_TEMPLATE_SEND):
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
            # 兼容规范化对象 {url, role, section} 与裸地址字符串
            first_item = video_urls[0]
            first_url = first_item.get("url") if isinstance(first_item, dict) else str(first_item)
            fname = os.path.basename(str(first_url).split("?")[0])
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

