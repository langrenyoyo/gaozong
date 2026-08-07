# M05 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. 素材上传（TOS）

```
Frontend: MaterialLibrary.tsx:133 uploadMaterialToTos(file)
  → api.ts:49 POST /ai-edit/materials/upload-tos (multipart/form-data, auto_wechat:ai_edit)
Router: ai_edit.py:224 upload_material_to_tos
  → 校验视频扩展名白名单 (:251) + 500MB 上限 (:256-258)
  → 计算 source_sha256 (hashlib.sha256, :260)
  → 写临时文件 (:265) → probe_video (:271)
  → TOSUploader(prefix="ai-edit/{merchant_id}").upload_and_presign(tmp_path) (:273-274)
  → 清理临时文件 (:282)
  → 幂等: 同 merchant_id+source_sha256 命中 → 复活软删+刷新预签名 (:290-312)
  → 否则新建 AiEditMaterial(storage_mode=cloud_available) (:315-334)
  → BackgroundTask 异步分析 (:341-342)
Table: AiEditMaterial
```

## 2. 素材分析（方舟多模态）

```
BackgroundTask: analyze_material_async
  → material_analysis.py: 用方舟多模态模型对视频提问
    → has_speech（是否含人声口播）→ category（口播/高光, :53-55）
    → transcript（口播转写）+ description（画面描述）(:65-69)
    → 写 AiEditMaterialAnalysis (transcript_json, analysis_version=ark_v1, :70-83)
    → scenes_json/tags_json/usable_ranges_json 当前写空数组占位 (:76-78)
    → 算力上报 capability_key=ai_edit (:257)
Table: AiEditMaterialAnalysis
```

## 3. 软删除与引用

```
DELETE /ai-edit/materials/{id}
  → ai_edit.py:389 → soft_delete_material (ai_edit_service.py:191-228)
    → 平台素材只读: scope=="platform" → AiEditPlatformReadOnly (:202-205)
    → 跨商户: 404 不泄露 (:207-208)
    → 同商户已软删: 幂等返回 (:209-211)
    → 活动引用检查: 查 AiEditJobMaterial JOIN AiEditJob 过滤非终态任务 (:214-220)
      → 命中 → AiEditMaterialInUse("MATERIAL_REFERENCED_BY_ACTIVE_JOB") (:222)
    → 通过: deleted_at=now, purge_after=now+7天 (:224-226)
```

## 4. M06 消费素材（SHARED_IMPLEMENTATION）

```
M06 create_job (ai_edit_service.py:241-297)
  → 对每个 materials 项调 get_material_for_merchant (:265)
    → 按 material_id 查, deleted_at 非空→NotFound (:181-183)
    → scope=="platform" 可见; 否则 merchant_id 校验 (:184-187)
  → 钉住哈希防漂移: pinned_sha256 == material.source_sha256 (:266-269)
    → 不匹配 → AiEditStatusConflict("PINNED_SHA256_DRIFT")
  → 写 AiEditJobMaterial (含 pinned_sha256/source_start/source_end) (:270-280)
```

## 5. Local Agent 注册（非 M04 19000）

```
POST /ai-edit/materials (require_local_agent_context, ai_edit.py:192-221)
  → svc.register_material (ai_edit_service.py:108-160)
  → 仅写库不传文件 (storage_mode=local_only, service.py:152)
```

> **术语区分**：M05 的 "Local Agent 注册" 与 M04 的 19000 WeChat Local Agent **不是同一能力**。
> - M05 Local Agent 注册：经 `require_local_agent_context`（X-Local-Agent-Token），用于 Local Agent 上报本机已有的素材文件元数据（不传文件内容，仅写 DB 记录 `storage_mode=local_only`）
> - M04 19000 WeChat Local Agent：微信 UI 自动化执行进程（poll-and-execute/detect-reply）
> - 两者共用 `X-Local-Agent-Token` 认证机制（同一 token→merchant_id 映射），但业务能力完全不同。为避免术语污染，M05 的注册能力命名为 **"AI Edit Local Agent Material Registration"**

## 6. 前端能力

```
MaterialLibrary.tsx (402行):
  → 列表 + 搜索 + 分类(全部/口播/高光) (:220-235)
  → 上传(多文件, 视频过滤) (:133, :202)
  → 分析展示(transcript/description) (:353-356)
  → 分析状态轮询(每5s) (:87-92)
  → 重新分析 (:164-175)
  → 删除(confirm) (:150-162)
  → 预览(video src=tos_presigned_url) (:313-318)
路由: /ai-edit/materials (navId ai-edit-materials, routes.ts:6)
权限: auto_wechat:ai_edit (ai_edit.py:28)
```
