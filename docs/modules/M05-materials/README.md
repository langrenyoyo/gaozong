# M05 小高素材库

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-07

## M05 是什么

M05 是 AI 剪辑素材管理模块，承担素材上传→TOS 存储→元数据分析→软删除→M06 剪辑消费的完整生命周期。与 M06 共用 router 和 feature 目录（SHARED_IMPLEMENTATION）。

## 正式用户能力

| 能力 | 入口 | 状态 |
|---|---|---|
| 素材列表 | GET /ai-edit/materials | ACTIVE |
| 上传素材（TOS） | POST /ai-edit/materials/upload-tos | ACTIVE |
| 素材分析 | BackgroundTask 异步（方舟多模态） | ACTIVE |
| 重新分析 | POST /ai-edit/materials/{id}/analyze | ACTIVE |
| 软删除 | DELETE /ai-edit/materials/{id} | ACTIVE（被活动 job 引用时 409 阻断） |
| 预览 | 前端 video src=tos_presigned_url | ACTIVE |
| Local Agent 注册 | POST /ai-edit/materials（agent token） | ACTIVE |

## Data Owner

| 表 | OWNER | 说明 |
|---|---|---|
| AiEditMaterial | M05 | 素材主表（sha256 幂等/软删除/TOS 预签名） |
| AiEditMaterialAnalysis | M05 | 分层分析快照（transcript/scenes/tags） |
| AiEditMaterialProcess | M05 | 分阶段处理状态 |
| AiEditTemplate | M05 | 平台级只读剪辑模板 |
| AiEditJobMaterial | M05/M06 共享 | 跨域关联表（M06 写入/M05 删除时反向读） |

## 主要依赖

- → M06（shared_implementation）：共用 ai_edit.py router + features/ai-edit/ 目录
- → TOS（火山引擎对象存储）：素材存储 + 预签名 URL
- → LAS（火山引擎）：TOS 预签名 URL 喂给 LAS（M06 剪辑消费）
- → M07（data）：素材分析算力上报 capability_key=ai_edit

## 当前状态

ACTIVE。上传→TOS→分析→删除链路完整。SHA-256 幂等去重 + pinned_sha256 防漂移 + 软删除引用拦截。**缺口**：TOS 上传端点/分析/删除端点无测试覆盖；purge 字段已建表但无执行代码；scenes/tags/usable_ranges 当前为空占位。
