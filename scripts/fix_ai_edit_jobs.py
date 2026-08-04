"""AI 剪辑历史任务修复脚本：标题补全 + 视频归档。

两个子命令，均默认 dry-run（不写库/不写对象存储），需 --execute 才真正执行。
不在 Alembic 迁移中执行；不默认扫描全部生产任务；不自动访问生产 LAS/TOS。

用法：
    # 标题补全（dry-run，用 las_script/input_json 兜底，不下载 ASR）
    python scripts/fix_ai_edit_jobs.py backfill-titles --limit 50
    python scripts/fix_ai_edit_jobs.py backfill-titles --job-id 1 --execute

    # 视频归档（dry-run 只列计划；--execute 才调 LAS poll 重新取 URL 并归档）
    python scripts/fix_ai_edit_jobs.py archive-videos --limit 10
    python scripts/fix_ai_edit_jobs.py archive-videos --job-id 1 --execute
"""
from __future__ import annotations

import argparse
import sys

# Windows 控制台 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from app.database import SessionLocal
from app.models import AiEditJob
from app.services import ai_edit_las_service as las_svc


def backfill_titles(*, job_id: int | None, limit: int, execute: bool, regenerate: bool = False) -> int:
    """补全无标题任务的标题（不覆盖 manual 来源）。

    regenerate=True 时强制重新生成 script 来源的标题（R2: script 是模板指令不适合做标题），
    仍保护 manual 来源。
    """
    db = SessionLocal()
    try:
        query = db.query(AiEditJob).filter(AiEditJob.source_type == "las_speech_auto")
        if job_id is not None:
            query = query.filter(AiEditJob.id == job_id)
        jobs = query.order_by(AiEditJob.id.asc()).limit(limit).all()
        fixed = 0
        for job in jobs:
            # R1：manual 来源永远保护，即使 title=NULL 也不覆盖
            if job.title_source == "manual":
                print(f"[skip] job_id={job.id} title_source=manual 受保护（title={job.title!r}）")
                continue
            # 已有非 fallback 标题：默认 skip；regenerate 时只对 script 来源重新生成
            if job.title and job.title_source != "fallback":
                if not regenerate or job.title_source != "script":
                    print(f"[skip] job_id={job.id} 已有标题 title={job.title} source={job.title_source}")
                    continue
                print(f"[regen] job_id={job.id} script 来源标题重生成（当前 title={job.title}）")
            # 用 las_script + input_json 文件名兜底生成（不下载 ASR，历史 URL 可能过期）
            title, source = _gen_title_offline(job)
            print(f"[{'exec' if execute else 'dry'}] job_id={job.id} -> title={title!r} source={source}")
            if execute:
                job.title = title
                job.title_source = source
                from datetime import datetime
                job.title_generated_at = datetime.now()
                fixed += 1
        if execute:
            db.commit()
        print(f"\n完成：{'已修改' if execute else 'dry-run(未修改)'} {fixed if execute else len(jobs)} 条")
        return 0
    finally:
        db.close()


def _gen_title_offline(job: AiEditJob) -> tuple[str, str]:
    """离线标题生成（不下载 ASR）：script 优先，文件名次之，兜底。"""
    import json as _json
    import os as _os
    import re as _re

    # 1. script
    if job.las_script and job.las_script.strip():
        t = las_svc._clean_title_text(job.las_script)
        if len(t) >= las_svc._TITLE_MIN:
            return t, "script"
    # 2. 文件名
    try:
        input_data = _json.loads(job.input_json) if job.input_json else {}
        urls = input_data.get("video_urls") or []
        if isinstance(urls, list) and urls:
            fname = _os.path.basename(str(urls[0]).split("?")[0])
            fname = _os.path.splitext(fname)[0]
            fname = _re.sub(r"^(client|second_client|third_client|fourth_client)_\d+", "", fname)
            t = las_svc._clean_title_text(fname)
            if len(t) >= las_svc._TITLE_MIN:
                return t, "filename"
    except Exception:
        pass
    # 3. 兜底
    return f"混剪任务 #{job.id}", "fallback"


def archive_videos(*, job_id: int | None, limit: int, execute: bool) -> int:
    """对已 completed 但未归档的任务，重新查 LAS 取新 URL 并归档到自有 TOS。

    dry-run 只列计划；--execute 才真正调 LAS poll + TOS 上传。
    LAS task 已 EXPIRED/失败则记录失败，不伪造。
    """
    db = SessionLocal()
    try:
        query = (
            db.query(AiEditJob)
            .filter(AiEditJob.source_type == "las_speech_auto")
            .filter(AiEditJob.status == "succeeded")
            .filter(AiEditJob.deleted_at.is_(None))
        )
        if job_id is not None:
            query = query.filter(AiEditJob.id == job_id)
        jobs = query.order_by(AiEditJob.id.asc()).limit(limit).all()
        print(f"待检查任务数：{len(jobs)}")
        for job in jobs:
            already = las_svc._get_archived_final_artifact(db, job)
            if already is not None:
                print(f"[skip] job_id={job.id} 已归档 key={already.archive_object_key}")
                continue
            if not job.las_task_id:
                print(f"[fail] job_id={job.id} 无 las_task_id，无法重新查询")
                continue
            print(f"[{'exec' if execute else 'dry'}] job_id={job.id} las_task_id={job.las_task_id} 待归档")
            if execute:
                _archive_one(db, job)
        return 0
    finally:
        db.close()


def _archive_one(db, job: AiEditJob) -> None:
    """执行单个任务归档：LAS poll 取新 artifacts → archive_final_video。"""
    try:
        client = las_svc.get_las_speech_auto_client()
        result = client.wait_for_terminal(job.las_task_id, max_wait=60)
        metadata = result.get("metadata", {})
        if metadata.get("task_status") != "COMPLETED":
            print(f"  [fail] job_id={job.id} LAS 未完成 status={metadata.get('task_status')}")
            return
        artifacts = (result.get("data") or {}).get("artifacts") or {}
        # 先持久化产物（补全 artifact 行），再归档
        las_svc._persist_artifacts(db, job, artifacts)
        ok = las_svc.archive_final_video(db, job, artifacts)
        print(f"  [{'ok' if ok else 'fail'}] job_id={job.id} 归档{'成功' if ok else '失败'}")
    except las_svc.LASError as exc:
        print(f"  [fail] job_id={job.id} LAS 查询失败: {exc}")
    except Exception as exc:
        print(f"  [fail] job_id={job.id} 异常: {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 剪辑历史任务修复")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_title = sub.add_parser("backfill-titles", help="补全无标题任务")
    p_title.add_argument("--job-id", type=int)
    p_title.add_argument("--limit", type=int, default=50)
    p_title.add_argument("--execute", action="store_true", help="真正执行（默认 dry-run）")
    p_title.add_argument("--regenerate", action="store_true", help="强制重生成 script 来源的标题（保护 manual）")

    p_arch = sub.add_parser("archive-videos", help="归档历史视频到自有 TOS")
    p_arch.add_argument("--job-id", type=int)
    p_arch.add_argument("--limit", type=int, default=10)
    p_arch.add_argument("--execute", action="store_true", help="真正执行（默认 dry-run，不连 LAS/TOS）")

    args = parser.parse_args()
    if args.cmd == "backfill-titles":
        return backfill_titles(job_id=args.job_id, limit=args.limit, execute=args.execute, regenerate=args.regenerate)
    if args.cmd == "archive-videos":
        return archive_videos(job_id=args.job_id, limit=args.limit, execute=args.execute)
    return 1


if __name__ == "__main__":
    sys.exit(main())
