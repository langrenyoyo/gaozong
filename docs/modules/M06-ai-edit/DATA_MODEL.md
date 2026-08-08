# M06 数据模型

> source_baseline: c26ec227e70d

## AiEditJob（OWNER: M06）

定义：`app/models.py:1497-1551`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| job_id | String(64), 唯一 | 业务 ID |
| merchant_id | String(128) | 商户隔离 |
| status | String(32) | processing/succeeded/failed（**无 CHECK 约束**） |
| source_type | String(32) | las_speech_auto/manual |
| stage | String(32) | submitted/processing/completed（无 CHECK） |
| progress | Integer | 0-100（CHECK 约束 models.py:1503） |
| attempt_count | Integer | >=0（CHECK models.py:1504） |
| execution_token_hash | String(128) | 防 attempt 回写 |
| las_task_id / las_idempotent_id | String | LAS 侧标识 |
| las_script / las_template / las_metadata_json | Text/JSON | LAS 参数 |
| input_json | _JSONStringJSONB | 持久化 video_urls/script/template |
| failure_code | String(64) | |
| delivery_status | String(32) | pending/archived/failed（无 CHECK） |
| video_tags | Text | JSON 数组 |
| title / title_source / title_generated_at | String/DateTime | 标题三件套 |
| deleted_at / deleted_by / delete_status / delete_error | DateTime/String/Text | 软删除四件套 |

**CHECK 约束**：progress 0-100 + attempt_count>=0。**无 status/stage/delivery_status/delete_status CHECK**。

## AiEditJobArtifact（OWNER: M06）

定义：`app/models.py:1554-1583`

| 字段 | 类型 | 说明 |
|---|---|---|
| artifact_id | String, 唯一 | 幂等 ID |
| job_id | String(64) | 关联 AiEditJob.job_id |
| merchant_id | String(128) | 商户隔离 |
| artifact_type | String | video_subtitled/video_clean/subtitle_srt/match_scheme/result_json |
| storage_key | String(255) | **stable tos_path（非临时 URL）** |
| content_sha256 | String | |
| is_final_video | Boolean | |
| delivery_status | String | pending/archived/failed |
| archive_object_key | String | 自有 TOS stable key |
| archive_error / file_size_bytes | String/BigInteger | |

## 状态流转

```
LAS 链路:
  processing(submitted) → processing(processing_result) → succeeded(completed, progress=100)
                                              → failed(las_timeout/las_failed/archive_failed)
  软删除: delete_status: deleting → deleted / delete_failed
  交付: delivery_status: pending → archived / failed

终态: succeeded/failed（任务）, archived/failed（交付）, deleted（删除）
回退: 无自动回退（failed 需人工重新提交 LAS）
```

## 商户隔离

- AiEditJob.merchant_id（models.py:1508）
- AiEditJobArtifact.merchant_id（models.py:1563）
- _require_ai_edit 校验权限 auto_wechat:ai_edit
- 所有端点按 merchant_id 过滤
- 跨商户 404 不泄露存在性（test_independent_ai_edit_attack.py 覆盖）
