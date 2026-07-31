# AI剪辑重做：LAS speech_auto 云端混剪 设计文档

创建时间：2026-07-31
状态：待审批
授权：甲方已书面授权恢复 AI剪辑（此前 FROZEN_BY_CUSTOMER，2026-07-18 冻结）

## 1. 背景与决策

### 1.1 甲方需求
放弃原有所有一键剪辑设计，前后端重做。后端能力迁移自甲方已验证的 demo `E:\work\demo\las_speech_auto`（调火山引擎 LAS `las_video_remix` 算子，`speech_auto` 模式，`automotive_headtalk` 模板），接口文档 `E:\work\project\project_info\LAS 视频混剪（speech_auto）接口调用说明.md`。

### 1.2 探索结论
- **demo**：纯 Python 脚本，无 Web/无前端/无存储。`las_client.py`（submit/poll/wait/download + 鉴权 + 终态集合 + 5 产物字段）、`file_uploader.py`（本地→TOS 直传→预签名 URL，用火山 TOS SDK）。无任务持久化、无幂等复用。
- **auto_wechat 既有冻结代码**（Phase 12，FROZEN_BY_CUSTOMER）：9000+19000+9100 三段架构已落地（7 表 + 2 迁移 + 控制面/执行面/规划面 + 前端骨架 + Task 11 测试包），但**未接 LAS**，媒体处理是本地 FFmpeg trim+concat + 占位 ASR/规划。

### 1.3 架构决策（甲方确认）
- **纯 LAS 云端**：auto_wechat 只做"提交 LAS + 轮询 + 存产物"，不做本地 FFmpeg/9100 规划/analyze/plan。worker 退化为"调 LAS + 下载产物"。放弃既有三段架构的本地智能规划能力（LAS 已全包：理解素材+识别口播+删口误+匹配空镜+字幕+渲染）。
- **新工作台**：前端新做上传素材 + 填 script + 提交 + 轮询进度 + 下载/预览成片，丢弃旧 AiVideoEditor 的本地渲染 9 阶段进度。
- **TOS 存储**：素材上传 TOS 生成预签名 URL 喂给 LAS；产物用 tos_path 长期保存。需配 TOS 凭证。

## 2. 能力边界（对齐接口文档 §4）
- 视频数量 ≤30；单视频 ≤10 分钟且可识别时长；素材总时长 ≤30 分钟。
- 每次任务输出一条最佳成片。
- 口播用素材原声，不新增 TTS。
- 只依据素材重组，不生成素材中不存在的事实/画面。
- script ≤4000 字符；template 固定 `automotive_headtalk`。
- 产物 5 项：video_subtitled（带字幕成片，推荐）、video_clean（无字幕）、subtitle_srt、match_scheme、result_json。`*_url` 预签名约 3 天有效，`*_tos_path` 长期。

## 3. 设计目标
1. 9000 新增 LAS 剪辑链路：素材上传 TOS → 提交 LAS（speech_auto）→ 轮询 → 存产物。
2. 任务持久化（复用既有 ai_edit_jobs/artifacts/materials 表，新增 LAS 专属字段）。
3. 前端新工作台：素材上传 + script 编辑 + 提交 + 进度 + 产物预览下载。
4. 算力上报（新增 `ai_edit` capability_key，需审批）。
5. 既有冻结代码：数据模型/控制面/supervisor 骨架可复用，FFmpeg/9100规划/analyze/plan 阶段废弃。

## 4. 数据模型变更
### 4.1 复用既有表
- `ai_edit_jobs`：存 LAS 任务（status 映射 LAS task_status）。
- `ai_edit_job_artifacts`：存 5 个产物（artifact_type 对应 5 字段，storage_key 存 tos_path）。
- `ai_edit_materials`：存素材（cloud_storage_key 存 tos:// 路径）。
### 4.2 新增字段（迁移）
- `ai_edit_jobs` 加：`las_task_id`（LAS 返回的 task_id）、`las_idempotent_id`、`las_script`、`las_template`、`las_business_code`、`las_error_msg`、`las_metadata_json`（轮询元数据）。
- `ai_edit_materials` 加：`tos_presigned_url`（喂给 LAS 的预签名地址）、`tos_presigned_expires_at`。
- 迁移：PG `0022` + SQLite `0042`。

## 5. 调用链
### 5.1 提交
1. 前端选素材（已上传 TOS 或现成 tos:// 地址）+ 填 script → `POST /ai-edit/jobs`（新 LAS 模式）。
2. 9000 service：组装 video_urls（预签名 + 现成地址）+ script + template + idempotent_id（持久化复用，幂等重试）。
3. 调 `las_client.submit()` → 拿 `las_task_id`，写库 status=processing。
4. 入 outbox 队列或 BackgroundTask 轮询。

### 5.2 轮询
1. `las_client.wait_for_terminal(las_task_id)`：固定间隔（默认 15s，可配）轮询 `/api/v1/poll`。
2. 终态（COMPLETED/FAILED/TIMEOUT/EXPIRED/CANCELLED）→ 写库。
3. COMPLETED → `las_client.download_artifacts()` 下载 5 产物到 TOS（用 tos_path 长期保存）→ 写 artifacts 表。
4. 失败 → status=failed + las_error_msg。

### 5.3 产物
- 前端 `GET /ai-edit/jobs/{id}` 拉状态 + artifacts（预签名 URL 或直链）。
- 预览 video_subtitled_url / 下载各产物。

## 6. 后端新增
- `app/services/las_client.py`（迁移自 demo `las_client.py`）：submit/poll/wait_for_terminal/download_artifacts，鉴权 LAS_API_KEY/LAS_BASE_URL。
- `app/services/las_tos_uploader.py`（迁移自 demo `file_uploader.py`）：本地→TOS 直传→预签名 URL。
- `app/services/ai_edit_las_service.py`：编排（素材组装→提交→轮询→存产物→算力上报）。
- `app/routers/ai_edit.py`：新增 LAS 模式路由（或新 `/ai-edit/las/*`），保留旧路由兼容。
- config：`LAS_API_KEY`/`LAS_BASE_URL`/`LAS_POLL_INTERVAL`/`LAS_MAX_WAIT`/TOS 凭证（`TOS_ACCESS_KEY`/`TOS_SECRET_KEY`/`TOS_BUCKET`/`TOS_REGION`/`TOS_ENDPOINT`）。

## 7. 前端
- 新页面 `frontend/src/features/ai-edit/pages/LasRemixWorkbench.tsx`：素材选择/上传 + script 编辑（带示例）+ 提交 + 进度轮询 + 产物预览/下载。
- API client 加 LAS 提交/状态接口。
- 旧 AiVideoEditor 保留但路由不暴露（或标记废弃）。

## 8. 算力上报（方案 A：新增专属 capability_key="ai_edit"）
- 在 `COMPUTE_CAPABILITY_KEYS` 加 `"ai_edit"`，AI剪辑消耗单独成项，与抖音客服/线索/微信助手/知识库/通用算力分开统计，便于按业务计费/限额。
- LAS 任务提交成功 + 产物完成时上报 `capability_key="ai_edit"`。
- 前端算力 tab 加"AI剪辑"展示档。
- 上报失败不影响主流程。

## 9. 安全边界
- TOS 凭证最小权限、短有效期 STS（不日志长期密钥）。
- LAS_API_KEY 不回显前端。
- 预签名 URL 有效期 > LAS max_wait。
- 产物 tos_path 长期保存，url 仅预览。
- 商户隔离 + 权限 `auto_wechat:ai_edit`（恢复入口需审批）。

## 10. 风险
- 高风险区：AI剪辑恢复（FROZEN→active）、新增 TOS/LAS 外部凭证、外部服务调用、新增迁移。
- LAS 是外部服务，需网络可用 + 凭证有效。
- 权限恢复需与 NewCarProject 同步。

## 11. 任务分解
1. Task 1：数据层 + 迁移（ai_edit_jobs/materials 加 LAS 字段）。
2. Task 2：LAS client（submit/poll/wait/download，迁移自 demo）。
3. Task 3：TOS uploader（迁移自 demo）+ config。
4. Task 4：9000 LAS 编排服务 + 路由。
5. Task 5：算力上报（capability_key=ai_edit，需审批）。
6. Task 6：前端新工作台。
7. Task 7：验证（tsc + 测试 + demo 链路核对）。

## 12. 允许范围 / 禁止事项
- 允许：新增 LAS client/TOS uploader/LAS 编排服务/路由/迁移/前端工作台/算力上报（capability_key=ai_edit）；复用既有 ai_edit 表与 9000 控制面骨架。
- 删除：纯 LAS 方案下废弃既有 FFmpeg worker/pipeline/stabilizer/media_tools/core、9100 规划器、19000 本地执行面（routes/supervisor/storage）、旧 AiVideoEditor 前端、Task 11 测试包。删除前做引用检查防 import 断裂。
- 禁止：恢复旧 FFmpeg worker/9100 规划接入（纯 LAS 云端）；绕过 TOS/LAS 凭证安全；前端持有 LAS_API_KEY；新增 auto_wechat:ai_video/ad_review 权限（CLAUDE.md §3）。

## 13. 文档影响
任务结束检查 `docs/ai` AI剪辑冻结状态（FROZEN→恢复 active）、05_PROJECT_CONTEXT、权限矩阵、算力 capability_key 清单。
