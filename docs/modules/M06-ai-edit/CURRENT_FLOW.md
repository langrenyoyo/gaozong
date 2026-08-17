# M06 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. LAS 混剪全链路

```
Frontend: LasRemixWorkbench.tsx NewTaskModal createLasJob({video_urls(对象数组), script, mode, template:"automotive_headtalk", target_duration_sec?})
  → 模式选择（口播营销/长实拍纪实/实拍+口播）+ PDF 4.7 脚本示例自动填充/防覆盖 + 按 mode 动态角色/section/时长控件
  → api.ts POST /ai-edit/las/jobs
Router: ai_edit.py create_las_job_route
  → _require_ai_edit (auto_wechat:ai_edit)
  → las_svc.create_las_job(db, merchant_id, video_urls, script, template, mode, target_duration_sec, video_edit_mode, render_video, smart_packaging, output_tos_path, idempotent_id)
  → background_tasks.add_task(las_svc.process_las_job, job.id)

Service create_las_job (ai_edit_las_service.py):
  → validate_las_request：mode 规范化（speech_auto→marketing_headtalk，缺失→marketing_headtalk）
    + template 规范化（automotive_headtalk→automotive）+ render_video 缺省 true
    + 分模式规则校验 fail-closed（marketing ≤30 禁 target_duration_sec/section；long_real 目录前缀或 ≤100
    支持 10~3600 禁 broll/section；real_shot_headtalk 显式/自动分段二选一 显式两段非空+实拍禁 broll+全禁 voiceover+≤100/≤30 自动 ≥2speech+≤130）
  → 构造 las_idempotent_id
  → client = get_las_speech_auto_client()
  → client.submit(video_urls, script, template, mode, render_video, output_tos_path, idempotent_id, target_duration_sec, video_edit_mode, smart_packaging)
  → LAS API: POST /api/v1/submit (las_client.py)
    operator_id="las_video_remix", operator_version="v1", mode=三模式之一
  → 取 las_task_id
  → 写 AiEditJob(status="processing", stage="submitted", progress=0, las_task_id, las_idempotent_id, input_json=完整规范化请求) （无 DB 迁移）

Service process_las_job (ai_edit_las_service.py:119-194) [BackgroundTask]:
  → SessionLocal() (:123), 取 job (:125)
  → client.wait_for_terminal(job.las_task_id, on_progress=_on_progress) (:141)
    → 循环 poll (POST /api/v1/poll, las_client.py:104-118)
    → on_progress 回写 job.stage + las_metadata_json (:132-138)
    → 终态 {COMPLETED, FAILED, TIMEOUT, EXPIRED, CANCELLED} (las_client.py:27)
  → 超时: status="failed", failure_code="las_wait_timeout" (:143-144)
  → 非终态非COMPLETED: status="failed", failure_code="las_{task_status}" (:159-160)
  → COMPLETED:
    → _persist_artifacts(db, job, artifacts) (:166) — storage_key=tos_path(stable,非临时URL) (:219)
    → archive_final_video(db, job, artifacts) (:167)
      → 下载 LAS 临时https到临时文件 (:290)
      → 流式上传自有TOS ai-edit/{merchant_id}/{job_id}/final.mp4 (:286,293)
      → 回写 archive_object_key/delivery_status="archived" (:297-302)
    → compute_video_tags (:168)
    → _fill_job_title (:169) — ASR→script→filename→fallback
    → archived成功: status="succeeded", stage="completed", progress=100 (:178-181)
    → archived失败: status="failed", failure_code="archive_failed" (:178,181)
  → 归档成功: _report_las_compute_usage(db, job) (:185-186)

Table: AiEditJob + AiEditJobArtifact
```

## 2. 软删除

```
DELETE /ai-edit/las/jobs/{id}
  → ai_edit_las_service.py:608-660 delete_las_job
    → 幂等: 已删除返回 "already_deleted" (:625-626)
    → 软删四件套: deleted_at (:629), deleted_by (:630), delete_status="deleting" (:631)
    → 清理自有TOS对象 (:635-648)
    → TOS删除成功: delete_status="deleted" (:651)
    → TOS删除失败: delete_status="delete_failed" + delete_error (:653) — 不回滚软删
```

## 3. M05 消费边界

```
Manual 链路 create_job (ai_edit_service.py:241-297):
  → get_material_for_merchant(db, material_id, merchant_id) (:265)
    → 商户隔离(scope/merchant_id校验) + 软删视为不存在
  → pinned_sha256 != material.source_sha256 → AiEditStatusConflict("PINNED_SHA256_DRIFT") (:266-269)
  → 写 AiEditJobMaterial(role/position/pinned_sha256/source_start/source_end) (:270-280)

LAS 链路 create_las_job:
  → 不写 AiEditJobMaterial（直接用 video_urls 预签名URL）
  → 对 M05 素材无强引用
  → soft_delete_material 的活动引用检查不影响 LAS 任务
```

## 4. TOS 归档

```
LAS 返回 artifacts (tos_path + 临时https URL)
  → _persist_artifacts: storage_key=tos_path(stable,非临时URL) (ai_edit_las_service.py:219)
    → 测试覆盖: test_temp_url_not_in_storage_key (:331)
  → archive_final_video: 下载临时https → 上传自有TOS stable key (:286-302)
    → archive_object_key = ai-edit/{merchant_id}/{job_id}/final.mp4 (stable)
  → 播放/下载: generate_playback_url 基于 archive_object_key 预签名 (:569-581)
  → 下载token fail-closed: _download_signing_secret 缺失→RuntimeError (:681)
    → verify_download_token: secret缺失→False (安全拒绝, :719)
    → 路由: token无效/缺失→403/401 (ai_edit.py:803-806)
```

## 5. 算力消费

```
_report_las_compute_usage (ai_edit_las_service.py:723-748):
  → tokens = max(1, len(script)//2) (估算口径, :733)
  → record_usage(db, merchant_id, tokens, capability_key="ai_edit", source="other",
      model="las-speech-auto", usage_measurement_method="estimated_tokens") (:737-746)
  → 失败catch不阻断主流程 (:747-748)
  → 仅归档成功后调用一次 (:185-186)
  → 无job级幂等键(与ISSUE-M04-002同源)
```
