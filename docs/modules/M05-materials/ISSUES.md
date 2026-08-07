# M05 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## HIGH

### ISSUE-M05-005 soft_delete_material 活动引用检查类型不匹配

- **位置**：app/services/ai_edit_service.py:214-220
- **事实**：`soft_delete_material` 传参 `material_id` 是字符串（如 `"mat_g1"`），但查询 `AiEditJobMaterial.material_id` 是 Integer FK→`AiEditMaterial.id`；类型不匹配导致查询不命中，活动引用检查失效
- **E2E 证据**：2-M05.2 Gate G——active job 引用素材时 `soft_delete_material` 未抛 `AiEditMaterialInUse`，直接执行了软删除
- **影响**：被活动 job 引用的素材可能被误删，导致 M06 剪辑任务引用失效
- **根因**：`soft_delete_material` 用 `material_id`（字符串）查 `AiEditJobMaterial.material_id`（Integer），应先查 `AiEditMaterial.id` 再用 id 查引用
- **建议**：修复查询为先 `material = get_material_for_merchant(...)` 再用 `material.id` 查 `AiEditJobMaterial.material_id`

### ISSUE-M05-004 预签名 URL 持久化到 DB（非 stable key）

- **位置**：app/routers/ai_edit.py:301,326（tos_presigned_url 直接存 presigned HTTPS URL）；app/models.py:1644-1645
- **事实**：上传端点将 TOS 预签名 HTTPS URL 直接持久化到 `AiEditMaterial.tos_presigned_url` 列；`cloud_storage_key`（stable TOS object key）字段存在但上传链路未写入
- **影响**：预签名 URL 有过期时间（tos_presigned_expires_at），过期后 DB 中的 URL 失效，M06 LAS 消费时可能拿到过期 URL 导致失败；同素材复活时刷新预签名（:301）但两次上传之间窗口内 URL 可能过期
- **根因**：上传链路设计为"存 presigned URL 喂 LAS"而非"存 stable key + 按需生成 presigned URL"
- **建议**：改为存 `cloud_storage_key`（stable TOS path），按需动态生成 presigned URL（不在本轮修复）

## LOW

### ISSUE-M05-001 M05/M06 共用 router + feature 目录（SHARED_IMPLEMENTATION）

- **位置**：app/routers/ai_edit.py（素材 + 任务 + LAS 同文件）；frontend/src/features/ai-edit/（MaterialLibrary + LasRemixWorkbench 同目录）
- **事实**：M05 素材端点（/materials*）与 M06 任务端点（/jobs*、/las/jobs*）共用单一 router + 权限码 auto_wechat:ai_edit
- **影响**：任一端点变更需在同文件修改，无服务/路由层隔离边界
- **建议**：解耦候选，拆分 router/feature 为 M05/materials 和 M06/editor（不阻断功能）

### ISSUE-M05-002 purge 字段已建表但无执行代码

- **位置**：AiEditMaterial.purge_operation_id/purge_status（models.py:1641-1642, CHECK 1601）
- **事实**：字段 + 约束已建表，但未见实际 purge 执行代码
- **影响**：软删除后 purge_after=now+7天但无自动物理清除
- **建议**：如需 purge 需补执行逻辑；当前软删除已满足功能需求

### ISSUE-M05-003 scenes/tags/usable_ranges 当前为空占位

- **位置**：material_analysis.py:76-78
- **事实**：AiEditMaterialAnalysis 的 scenes_json/tags_json/usable_ranges_json 当前写空数组
- **影响**：分镜/标签/可用区间未真正填充，分析能力部分实现
- **建议**：PLANNED_NOT_IMPLEMENTED（需产品确认是否需要）

## TEST_GAP

### TEST_GAP-M05-001 TOS 上传/分析/删除端点无测试

- **位置**：ai_edit.py upload-tos(:224)/analyze(:364)/delete(:389)
- **事实**：仅 schema/合同层测试覆盖，端点级 E2E 全部 MISSING
- **影响**：上传→TOS→预签名→分析→删除完整链路无集成测试
- **建议**：Docker E2E 补（TOS 需 mock 或真实凭证）

## ARCHITECTURE_OBSERVATION

### ARCH-M05-001 AiEditJobMaterial 跨域耦合点

- **位置**：models.py:1726-1745
- **事实**：M06 create_job 写入（ai_edit_service.py:270-280），M05 删除时反向读（soft_delete_material :214-220）
- **影响**：M05 删除依赖 M06 任务状态（跨域读），无独立 OWNER
- **处理**：登记 DATA_COUPLING，不重构（天然业务依赖）

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 2（预签名 URL 持久化 / soft_delete 引用检查类型不匹配） |
| MEDIUM | 0 |
| LOW | 3（共用 router/feature / purge 无执行 / scenes 空） |
| TEST_GAP | 1（端点级 E2E 全 MISSING） |
| ARCHITECTURE_OBSERVATION | 1（AiEditJobMaterial 跨域耦合） |
