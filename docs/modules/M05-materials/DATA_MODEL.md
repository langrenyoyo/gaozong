# M05 数据模型

> source_baseline: c26ec227e70d

## M05 拥有的表

### AiEditMaterial（OWNER: M05）
定义：`app/models.py:1586-1645`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| material_id | String, 唯一 | 幂等 ID |
| merchant_id | String(128) | 平台素材为空 |
| scope | String | merchant/platform（CHECK 约束） |
| media_type | String | |
| storage_mode | String | 四态 CHECK（local_only/cloud_available/cloud_only/cloud_purged） |
| source_sha256 | String, 非空 | SHA-256 幂等去重键 |
| parent_material_id | String | |
| thumbnail_storage_key / cloud_storage_key | String | |
| analysis_status / stabilization_status | String | |
| deleted_at / purge_after | DateTime | 软删除 + 7天回收 |
| display_name / description / category / duration_seconds / width / height / fps / file_size_bytes | Task12 扩展 | |
| manual_override_json / manual_confirmed_at | JSON/DateTime | 人工覆盖优先 |
| purge_operation_id / purge_status | String | purge 字段已建表但无执行代码 |
| tos_presigned_url / tos_presigned_expires_at | String/DateTime | LAS 消费 |

**唯一约束**：同商户同 SHA 唯一（models.py:1593）

### AiEditMaterialAnalysis（OWNER: M05）
定义：`models.py:1648-1661`。按 source_sha256 聚合一条，存 transcript_json/scenes_json/tags_json/usable_ranges_json + analysis_version

### AiEditMaterialProcess（OWNER: M05）
定义：`models.py:1664-1705`。分阶段处理状态（stage 五态 CHECK / status 五态 CHECK / progress 0-100）

### AiEditTemplate（OWNER: M05）
定义：`models.py:1708-1723`。平台级只读剪辑模板（template_key 唯一/rules_json/prompt_version）

### AiEditJobMaterial（M05/M06 共享耦合）
定义：`models.py:1726-1745`。跨域关联表（job_id + material_id + role + pinned_sha256）

## 商户隔离

- AiEditMaterial.merchant_id（平台素材为空，scope=platform 可跨商户只读）
- AiEditMaterialAnalysis/Process/JobMaterial/Template 无 merchant_id（靠 material_id 间接隔离）
- get_material_for_merchant 校验 scope/merchant_id（ai_edit_service.py:177-188）

## M06 的表（非 M05）

- AiEditJob（models.py:1497）：剪辑任务主体（merchant_id/status/stage/LAS 字段/交付闭环）
- AiEditJobArtifact（models.py:1554）：任务产物（merchant_id/storage_key/content_sha256/归档字段）
