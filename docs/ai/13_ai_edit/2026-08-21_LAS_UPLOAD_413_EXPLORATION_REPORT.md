# P0.5-LAS-UPLOAD-413-EXPLORATION-REPORT

> 状态：EXPLORATION_COMPLETE（仅只读探索，未修改代码/配置/nginx/数据库，未提交未部署）
> 角色：Exploration Authority
> 背景：`POST /api/ai-edit/materials/upload-tos` 生产 HTTP 413
> 探索日期：2026-08-21
> 探索方式：代码核对 + SSH 只读核实生产 nginx（`ssh xg-prod`）

## FACTS

### 1. nginx 实际生效配置（生产服务器实测）

| 层级 | 位置 | client_max_body_size | 说明 |
|---|---|---|---|
| **http 级（全局）** | `/www/server/nginx/conf/nginx.conf`（宝塔面板） | 原 **50m** → 2026-08-21 12:48 用户手动改为 **1000m** | 已生效（nginx worker 今日重建，`nginx -T` 与磁盘配置均为 1000m） |
| server 级 | `merchant.xiaogaoai.cn.conf` | 无覆盖 | 继承 http 级 |
| location 级 `/api/` | `merchant.xiaogaoai.cn.conf:93-111` | **无覆盖** | 继承 http 级；`proxy_read_timeout 600s` / `proxy_send_timeout 600s` 上传转发超时充足；未设 `client_body_timeout`（默认 60s，大文件上传可能触发但非本次根因） |

- 站点配置：`/www/server/panel/vhost/nginx/merchant.xiaogaoai.cn.conf`
  - `location ^~ /api/` → `proxy_pass http://127.0.0.1:9000/`（直连 9000）
  - `location ^~ /` → `proxy_pass http://127.0.0.1:5173`（静态页面 → 前端容器）
- 生产 nginx 由**宝塔面板管理，配置文件不在本仓库**（`docs/ai/11_deployment_ops/P1_LIVE_CHECK_CALLBACK_SAFETY_REVIEW.md:215` 已记录"不修改宝塔/Nginx 反代配置"的既有边界）。

### 2. 上传链路（仅一层 nginx）

```
浏览器 → 宝塔 nginx（merchant.xiaogaoai.cn，http 级 client_max_body_size）
   → location ^~ /api/ → 127.0.0.1:9000（FastAPI，无 body 限制）
   → TOSUploader.put_object（流式上传，无大小限制）
   → TOS
```

- **前端容器不是 nginx**：`xg-auto-wechat-frontend` 为 `npm run preview`（vite preview，仅 127.0.0.1:5173），不参与 `/api/` 上传链路；`nginx -g daemon off` 进程归属 `used-car-frontend-1`（used-car 项目，无关）。
- uvicorn（`python -m uvicorn app.main:app`）无默认 body 限制；FastAPI/Starlette 默认不限制 multipart 大小。
- nginx `proxy_request_buffering` 默认 on：大文件先完整缓冲到临时文件再转发 9000；`client_body_temp_path` 未显式配置（用默认目录），`/` 盘可用 **301G**，无容量问题。
- dev 环境 vite proxy（http-proxy）无 body 限制，仅生产宝塔 nginx 是限制点。

### 3. 后端上传限制（[ai_edit.py:299-333](app/routers/ai_edit.py)）

| 项 | 事实 |
|---|---|
| 最大文件大小 | `max_size = 500MB`（`file.file.read()` **整读后**检查，`:331-333`） |
| 错误返回格式 | 后端 413 JSON：`{"code": "FILE_TOO_LARGE", "message": "文件不能超过 500MB"}` |
| 类型校验 | 仅视频扩展名（mp4/mov/m4v/mkv/avi/flv/webm），`:325-327` |
| **缺陷** | `file.file.read()` 将整个文件读入内存（500MB 文件 ≈ 500MB 内存/请求，非流式）；大小检查在整读**之后**，>500MB 文件会先白传+占内存才 413 |

### 4. 生产事故观测（nginx 访问日志实测）

- **事故时间**：2026-08-21 10:42 ~ 12:26，`POST /api/ai-edit/materials/upload-tos` 连续 **15 次 413**（来源 IP `183.6.57.187`，Edge/Chrome 151，页面 `/ai-edit/materials`）。
- 413 响应体 **578 字节 = nginx 默认 HTML 错误页**（非后端 JSON）。
- 12:14:48 有一条 **200**（≤50MB 小文件上传成功，证明链路本身通）。
- 12:48 用户改 1000m 并 reload 后，**未再出现 413**（12:51:16 有一条 499=客户端中断，非 413）。
- nginx error.log 无 413 记录（413 不写 error log，仅 access log）。

### 5. 前端现状（[MaterialLibrary.tsx:123-139](frontend/src/features/ai-edit/pages/MaterialLibrary.tsx) / [uploadFeedback.ts](frontend/src/features/ai-edit/uploadFeedback.ts)）

| 项 | 事实 |
|---|---|
| 文件大小前端校验 | **无**。`accept="video/*"`（[MaterialLibrary.tsx:192](frontend/src/features/ai-edit/pages/MaterialLibrary.tsx#L192)）仅类型过滤，`multiple` 多选，无 maxSize 校验 |
| 413 处理 | `classifyUploadError`：有 HTTP response → `failed`（`uploadFeedback.ts:23-31`）；413 有 response → 归 failed |
| 用户提示 | 全部 failed → `errorText = "上传失败，请稍后重试"`（`uploadFeedback.ts:80-86`），**无"文件过大/超过限制"友好提示** |
| 错误码提取 | `getApiErrorCode`（`api/client.ts:27-41`）仅能提取后端 JSON 的 `code`；**nginx HTML 413 非 JSON → 无法区分** |

## ROOT_CAUSE

**直接根因**：生产宝塔 nginx http 级 `client_max_body_size 50m` 小于上传视频大小，nginx 在 `/api/` location（无覆盖）直接返回 413 "Request Entity Too Large"，**请求未到达后端**，后端 500MB 限制形同虚设。

**已缓解**：用户 2026-08-21 12:48 手动将 nginx 改为 `1000m` 并 reload 生效；>50MB 且 ≤500MB 上传现可正常到达后端（后端 500MB 兜底），12:26 后无新 413。

**残余不一致**：
1. 后端允许 500MB，但 >500MB 文件被整读进内存后才 413（白传 + 内存峰值）。
2. nginx 1000m 为**手动修改、不在版本控制**，宝塔还原/重装/其他站点复刻时可能回退 50m（无自动化保障）。
3. 前端对 413 无友好提示，用户误以为是上传故障。

## IMPACT_SCOPE

### 当前影响
- 413 事故已缓解（1000m 生效）；>50MB ≤500MB 上传可通，后端 500MB 限制正常兜底。
- **仅影响 `/api/ai-edit/materials/upload-tos`**（唯一需要大 body 的接口）；其它 `/api/*` 接口 body 均远小于限制，不受影响。

### 潜在影响面（未实施，仅评估）
| 影响 | 等级 | 说明 |
|---|---|---|
| 后端整读内存 | 高 | `file.file.read()` 非流式，500MB 文件 ≈ 500MB 内存/请求；多并发上传可能 OOM（现有稳定性风险，非本次 413 根因） |
| >500MB 白传 | 中 | 500MB 限制与 nginx 1000m 不一致：>500MB 文件先完整传到后端、整读内存后才 413 |
| 前端体验 | 中 | 413 只显示"上传失败，请稍后重试"，无"文件过大"引导 |
| nginx 配置漂移 | 中 | 1000m 手动修改未纳入版本控制/部署自动化，存在回退风险 |
| 数据库/模型 | 无 | 无 schema/迁移影响 |

### 禁止修改范围
- **数据库 / 迁移**：无变更需求，禁止。
- **TOS 配置 / 凭证**：无 TOS 侧限制问题，禁止。
- **nginx 生产配置**：已由用户手动调整（1000m）；本探索未改、禁止未经授权再改。
- **其它路由 / 业务逻辑 / 鉴权**：与本问题无关，禁止。

## MINIMAL_FIX_SCOPE

> 以下为探索输出的候选修复边界，**不实施**，等待 Decision Authority 裁决。

### 允许修改（候选）
| # | 修改点 | 内容 | 说明 |
|---|---|---|---|
| F1 | 前端 `uploadFeedback.ts` | 识别 413 / `FILE_TOO_LARGE`，输出"文件超过 500MB 限制"友好提示 | 最小改动，纯前端文案/分类 |
| F2 | 前端 `MaterialLibrary.tsx` | 选择文件后前端校验 `file.size > 500MB` 直接阻止上传并提示 | 在发送前拦截，避免白传 500MB |
| F3 | 后端 `ai_edit.py` | `file.file.read()` 改为流式/边读边限（读满 max_size+1 即 413），消除整读内存峰值 | 稳定性修复，与 413 相关但非根因 |
| F4 | nginx 配置固化 | 将 1000m（或与后端 500MB 对齐的值）纳入可重复部署配置（宝塔手动改无版本控制） | 需运维/部署侧配合，涉及部署文档 |

### 建议优先级
- 最小有效组合：**F1 + F2**（前端友好提示 + 前端拦截），改动面最小、无后端风险。
- F3 为稳定性增强（整读内存），与本次 413 非直接因果，可独立评估。
- F4 属部署治理，需与运维协调（生产 nginx 不在本仓库）。

## RISK

| 风险 | 等级 | 说明 |
|---|---|---|
| 后端整读内存 OOM（多并发 500MB 上传） | 高 | 现有缺陷，1000m 放行后暴露概率上升（更多大文件能到达后端） |
| nginx 1000m 手动配置漂移 | 中 | 不在版本控制，宝塔还原/重装可能回退 50m，事故复发 |
| >500MB 白传浪费带宽/内存 | 中 | 500MB 与 1000m 不一致，大文件先整传再 413 |
| 前端误导用户 | 低 | 413 显示"上传失败，请稍后重试"，用户误判为系统故障 |

## WAITING_FOR_DECISION

1. **是否批准 F1 + F2（前端 500MB 校验 + 413 友好提示）**？——改动面最小，解决用户体验与白传。
2. **是否批准 F3（后端流式读取限制，消除整读内存）**？——与 413 非直接因果，但 1000m 放行后 OOM 风险上升，建议一并评估。
3. **F4（nginx 1000m 固化到部署自动化/文档）** 是否纳入？需确认生产 nginx 管理边界（宝塔手动 vs 部署脚本）。
4. **大小上限口径**：前端/后端/nginx 三层是否统一为 500MB（后端既有限制），还是上调？

---
TASK_STATUS: EXPLORATION_COMPLETE
CODE_CHANGE=0 / DB_CHANGE=0 / MIGRATION=0 / DEPLOYMENT=0 / COMMIT=0
（仅 SSH 只读核实生产 nginx 配置与日志；nginx 1000m 为 2026-08-21 12:48 用户手动修改，非本任务改动）
