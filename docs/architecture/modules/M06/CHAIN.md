# M06 AI小高剪辑 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M06 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- AI 剪辑：LAS 云端混剪编排（火山引擎 LAS `las_video_remix` 算子 `speech_auto` 模式）：9000 组装参数 → LAS submit → 后台轮询 → 存产物 → 前端工作台。
- **边界红线**：不负责素材库管理（归 M05）；LAS_API_KEY 环境变量注入，前端不持有；旧 FFmpeg/9100 规划/19000 本地执行面三段架构已放弃。
- 与 M05 在 ai_edit router/feature 共置（BC-02，MIXED）。

## 2. User Entrypoints
- 5173 前端「AI剪辑」工作台：LasRemixWorkbench（M06 剪辑工作台，页面域 M05）。
- 素材选择 → 混剪参数 → 提交 → 轮询结果 → 产物下载/预览。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/ai-edit/`（BC-02 共置；LasRemixWorkbench 为核心剪辑页）。
- 页面：LasRemixWorkbench。
- API clients：ai-edit/api.ts（LAS 工作台）。

## 4. Backend API Entrypoints
- `app/routers/ai_edit.py`：MIXED（BC-02）——M06 剪辑 API 段（LAS submit/query/产物）。
- 产物投递/下载：ai-edit 域（test_ai_edit_download_token、test_ai_edit_result_delivery 覆盖）。

## 5. Core Services
- `app/services/`：ai_edit_las_service（LAS 编排）、las_client（火山 LAS client）、las_tos_uploader（TOS 上传）、media_probe（媒体探测）。
- 脚本：scripts/fix_ai_edit_jobs.py（DEV_ONLY 任务修复）、build_ai_edit_worker_exe.ps1（DEV_ONLY 旧执行面遗留）。

## 6. Data Ownership
- 9000 库表：ai_preview_executions（含 stage，F-1 幂等复用）、ai_edit_jobs（LAS 任务状态）、剪辑产物记录。
- 被其他模块读写：M07 计费（preview/ai_edit usage，0034 PREVIEW PG_RUNTIME_VERIFIED，双 HTTP hop）。

## 7. Async / Worker Chain
- 参数组装 → LAS submit（las_client，TOS 素材上传）→ 后台轮询（ai_edit_las_service）→ 产物落库 → 前端拉取。
- 计费：ai_edit/preview consumer（M07，identity=ai_preview_execution:{id}:{stage}；F-1 Trusted Reply-Suggestion 复用同 identity 家族）。

## 8. External Dependencies
- 火山引擎 LAS：las_video_remix 算子（speech_auto；AUTH：LAS_API_KEY env；FAILURE：任务失败态、轮询超时）。
- TOS：素材/产物对象存储（预签名 URL 含 AK 被 GH Push Protection 拦截，示例须打码）。
- 本地 no-network：test_independent_ai_edit_attack / media_probe 离线探测。

## 9. Cross-Module Calls
- CALLS：M05（素材库读取）、M07（preview/剪辑计费）。
- READS：M05 素材分析结果。
- COMPAT_FOR：无。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:ai_edit`（AI剪辑入口，恢复承载 LAS 混剪工作台 + 素材库）。
- 凭证边界：LAS_API_KEY / TOS AK 仅环境变量注入，前端与前端 token 不持有；日志不落 secrets。

## 11. Compatibility Layer
- ai_edit router 的 M05/M06 共置区：MIXED（BC-02）。
- 旧本地执行面（FFmpeg/9100/19000）：已删除（2026-07-31 甲方授权恢复后弃用）；数据模型 7 表+迁移保留复用。

## 12. Legacy Candidates
- build_ai_edit_worker_exe.ps1：DEV_ONLY/LOW 旧本地执行面遗留（登记 ≠ 可删除）。
- fix_ai_edit_jobs.py：DEV_ONLY 一次性任务修复脚本。

## 13. Known Unknowns
- U-008：LAS `speech_auto` 模式下 Shot.Empty 服务端故障与素材质量判定边界（7/28 成功 8/3 失败同配置=服务端故障，代码已修 4 处，见记忆 las-speech-auto-material-requirements）。
- 生产 LAS 凭证注入与轮询策略未在 staging 复核（生产验证仍需另行审批）。
- **HIGH-03 = OPEN（G1-Delta-1 复核，不得误标关闭）**：LAS long queued video_urls 仍可能过期 >7 天。归属 M06/LAS 长任务链，独立于 M05 历史素材 presign 修复（M05 presign = CLOSED，见 M05 §13）。D1（M05 presign hotfix）不覆盖 LAS 任务产物临时 URL 的长队列过期问题。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：参数组装→LAS submit→轮询→产物→前端工作台全链路（含 TOS 上传）；preview/剪辑计费幂等（0034 NO_DOUBLE_CHARGE）；LAS 故障态（Shot.Empty）正确回写；凭证不落前端/日志；`auto_wechat:ai_edit` 权限门。G1 阶段不展开。
