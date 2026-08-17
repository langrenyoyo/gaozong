# M06 AI小高剪辑

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-08

## M06 是什么

M06 是 LAS 云端混剪模块，承担 9000 组装参数→LAS submit→后台轮询→TOS 归档→交付闭环的完整链路。使用火山引擎 LAS `las_video_remix` 算子三模式（`marketing_headtalk` 口播营销 / `long_real_shot` 长实拍纪实 / `real_shot_headtalk` 实拍+口播复合；旧名 `speech_auto` 等价 `marketing_headtalk`）。接口合同 `docs/ai/13_ai_edit/contracts/LAS视频混剪_las_video_remix_接口调用说明_for小高.pdf`（2026-08-17 M06-LAS-REMIX-MODES-20260817-1 三模式升级）。

## 正式用户能力

| 能力 | 入口 | 状态 |
|---|---|---|
| 创建 LAS 混剪任务（三模式 + 兼容别名 + 规则 fail-closed） | POST /ai-edit/las/jobs | ACTIVE |
| 任务列表+状态轮询 | GET /ai-edit/las/jobs + 前端 15s 轮询 | ACTIVE |
| 预览结果 | GET /ai-edit/las/jobs/{id}/playback-url → video 弹窗 | ACTIVE |
| 下载 | GET /ai-edit/las/jobs/{id}/download-link → a href 下载 | ACTIVE（download token fail-closed） |
| 软删除 | DELETE /ai-edit/las/jobs/{id} | ACTIVE（四件套 deleted_at/deleted_by/delete_status/delete_error） |

## Data Owner

| 表 | OWNER | 说明 |
|---|---|---|
| AiEditJob | M06 | LAS 任务主体（status/stage/progress/LAS 字段/交付闭环字段/软删除四件套） |
| AiEditJobArtifact | M06 | 任务产物（storage_key=stable tos_path, content_sha256, 归档字段） |

## 主要依赖

- → M05（data CONTRACT）：manual 链路消费素材（get_material_for_merchant + pinned_sha256）；LAS 链路用预签名 URL 不写 AiEditJobMaterial
- ↔ M05（shared implementation）：共用 ai_edit.py router + features/ai-edit/ 目录
- → LAS（external）：submit/poll/wait_for_terminal/download_artifacts
- → TOS（external）：自有 TOS 归档（stable object key）
- → M07（data）：算力上报 capability_key=ai_edit（仅归档成功后）

## 当前状态

ACTIVE。LAS 全链路完整（三模式规范化+规则校验→submit→poll→archive→deliver→delete）。TOS 归档用 stable object key（非临时 URL）。下载 token fail-closed。**关键缺口**：无 status CHECK 约束、算力上报无幂等键、process_las_job 单点轮询无恢复、LAS 任务对素材无强引用（均不属本任务范围）。
