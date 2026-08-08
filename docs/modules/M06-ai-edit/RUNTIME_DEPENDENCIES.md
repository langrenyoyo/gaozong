# M06 运行时依赖

> source_baseline: c26ec227e70d

## M06 → M05（data CONTRACT + shared implementation）

| 层 | 边 | 类型 | mechanism | 证据 |
|---|---|---|---|---|
| Business/data | M06→M05 | D | direct DB | manual 链路 create_job 校验素材 get_material_for_merchant + pinned_sha256（ai_edit_service.py:256-269） |
| Implementation | M05↔M06 | S | shared code | 共用 ai_edit.py router + features/ai-edit/ 目录 + auto_wechat:ai_edit（ai_edit.py:28） |

> LAS 链路对 M05 素材无强引用——create_las_job 用预签名 URL 不写 AiEditJobMaterial。
> soft_delete_material 的活动引用检查（ISSUE-M05-005）不影响 LAS 任务。

## M06 → LAS（external）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M06→LAS | X | HTTP | submit POST /api/v1/submit（las_client.py:65-102）; poll POST /api/v1/poll（:104-118）; wait_for_terminal 循环（:120-154） |

> 依赖：LAS_API_KEY / LAS_BASE_URL（config.py:392-393）; LAS_POLL_INTERVAL_SECONDS / LAS_MAX_WAIT_SECONDS

## M06 → TOS（external）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M06→TOS | X | TOS upload | archive_final_video 下载临时https→上传自有TOS stable key（ai_edit_las_service.py:286-302）; TOSUploader.upload_file_stream（las_tos_uploader.py:139-156） |

> storage_key = stable tos_path（非临时URL）; archive_object_key = ai-edit/{merchant_id}/{job_id}/final.mp4

## M06 → M07（data，算力上报）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M06→M07 | D | service call | _report_las_compute_usage → record_usage（ai_edit_las_service.py:737-746）; capability_key=ai_edit; 仅归档成功后调用 |

> 与 ISSUE-M04-002 同源：record_usage 无幂等键，异常重入可能重复上报（正常路径 archived 幂等 gate 避免重复）

## M06 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth/RBAC | auto_wechat:ai_edit（ai_edit.py:28-37） |
| 数据库 | AiEditJob + AiEditJobArtifact ORM |

## Legacy 引用

无。M06 LAS 链路无 legacy/compat/deprecated/FROZEN 标记。与 LEGACY_REGISTER 无交叉。一键过审 CANCELLED_BY_CUSTOMER AdReview 三表与 M06 无关。
