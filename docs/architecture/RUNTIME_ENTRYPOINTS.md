# 运行入口盘点

> 基于 2026-08-07 代码事实（commit c26ec227e70d）。每个入口标：类型 / 路径或标识 / 代码位置 / 启用条件 / 归属模块(M01-M07) / 备注。
> Legacy 只标 `?`（UNKNOWN ≠ LEGACY，正式定性见 1A.5）。
> 模块：M01客服 / M02线索 / M03智能体 / M04微信助手 / M05素材库 / M06剪辑 / M07算力 / PLATFORM 平台公共底座。

---

## 一、Frontend Routes

React Router（`BrowserRouter` + `Routes` + 动态 `Route`），非 createBrowserRouter。路由聚合在 `frontend/src/features/routes.ts:9`（`capabilityRoutes`）+ `App.tsx:40`（`adminRoutes`）+ `routes.ts:18`（legacy 重定向）。

### Capability 路由（用户权限过滤后动态渲染，`App.tsx:719`）

| 路径 | navId | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|---|
| `/douyin-cs/workbench` | douyin-ai-cs | features/douyin-cs/routes.ts:4 | 权限 `auto_wechat:douyin_ai_cs` | M01 | |
| `/douyin-cs/auto-reply-runs` | douyin-auto-reply-diagnostics | features/douyin-cs/routes.ts:5 | 同上 | M01 | |
| `/leads` | leads | features/leads/routes.ts:4 | 权限 `auto_wechat:leads` | M02 | |
| `/agents` | ai-agents | features/agents/routes.ts:4 | 权限 `auto_wechat:douyin_ai_cs`（复用客服权限） | M03 | |
| `/wechat-assistant` | ai-agent | features/wechat-assistant/routes.ts:4 | 权限 `auto_wechat:agent`（含 legacy 别名） | M04 | |
| `/wechat-assistant/config` | wechat-config | features/wechat-assistant/routes.ts:5 | 同上 | M04 | |
| `/wechat-assistant/tasks` | wechat-tasks | features/wechat-assistant/routes.ts:6 | 同上 | M04 | |
| `/wechat-assistant/download-test` | wechat-download-test | features/wechat-assistant/routes.ts:7 | 同上 | M04 | |
| `/wechat-assistant/daily-reports` | wechat-daily-reports | features/wechat-assistant/routes.ts:8 | 同上 | M04 | |
| `/compute/center` | compute | features/compute/routes.ts:4 | 权限 `auto_wechat:compute` | M07 | |
| `/compute/token-transactions` | compute-token-transactions | features/compute/routes.ts:5 | 同上 | M07 | |
| `/compute/recharge-orders` | compute-recharge-orders | features/compute/routes.ts:6 | 同上 | M07 | |
| `/ai-edit/materials` | ai-edit-materials | features/ai-edit/routes.ts:6 | 权限 `auto_wechat:ai_edit` | M05 | |
| `/ai-edit/editor` | ai-edit-editor | features/ai-edit/routes.ts:7 | 同上 | M06 | |

### Admin 路由（`App.tsx:40-48`）

| 路径 | navId | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|---|
| `/admin/autoreply-rollout` | admin-autoreply-rollout | App.tsx:41 | `isAdminLike` + `auto_wechat:admin:autoreply` | M01 | 入口已隐藏，路由保留 (?) |
| `/admin/return-visits` | admin-return-visits | App.tsx:42 | `auto_wechat:admin:return_visit_prompts` | M01 | |
| `/admin/ai-reply-records` | ai-reply-records | App.tsx:43 | `auto_wechat:admin:ai_reply_records` | M01 | |
| `/admin/forbidden-words` | admin-forbidden-words | App.tsx:44 | `auto_wechat:admin:forbidden_words` | M01 | |
| `/admin/compute-config` | admin-compute-config | App.tsx:45 | `auto_wechat:admin:compute_config` | M07 | |
| `/admin/no-local-feature` | admin-no-local-feature | App.tsx:46 | `isAdminLike` | PLATFORM | 兜底提示 |
| `/admin/newcar-owned` | admin-newcar-owned | App.tsx:47 | `isAdminLike` + hasAnyNewCarOwned | PLATFORM | 提示去 NewCarProject |

### Legacy 路由重定向（`routes.ts:18-41`，22 条）

来源 `frontend/src/features/routes.ts:18`。全部 Legacy=是，仅列代表性：

| from | to | 备注 |
|---|---|---|
| `/douyin-ai-cs` | `/douyin-cs/workbench` | 旧路径重定向 |
| `/leads/list` `/leads/board` `/leads/detail` | `/leads` | 旧线索路径 |
| `/ai-agent` | `/wechat-assistant` | 旧微信助手路径 |
| `/agents/new` `/agents/edit` | `/agents` | 旧智能体路径 |
| `/compute` `/compute/packages` `/compute/markup-ratios` | `/compute/center` 或 `/admin/compute-config?view=` | 旧算力路径 |
| `/knowledge-base` `/knowledge-categories` 等 | `/douyin-cs/workbench` | 旧知识库路径并入客服 |

完整 22 条见 `routes.ts:18-41`。

---

## 二、FastAPI Routers

### 9000 主服务（app/main.py 注册，42 个 router）

所有 `include_router` 在 `app/main.py:125-169`。条件加载仅 Windows 专用路由（`main.py:60-65` try/except + `main.py:167-169`）。

| router | prefix | tags | 位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|---|---|
| staff | /staff | 销售人员 | main.py:125 | 无 | M02 | |
| leads | /leads | 线索管理 | main.py:126 | 无 | M02 | |
| checks | /checks | 回复检测 | main.py:127 | 无 | M01 | |
| reports | /reports | 报表统计 | main.py:128 | 无 | PLATFORM | |
| integrations | /integrations/douyin | 外部系统集成 | main.py:129 | 无 | PLATFORM/M02 | 含正式 webhook |
| legacy_webhook_router | /webhook | 抖音Webhook兼容路径 | main.py:130 | 无 | M02 | Legacy 兼容路径 (?) |
| wechat_auto_detect | /wechat-auto-detect | 微信自动检测 | main.py:131 | 无 | M04 | 旧链路 (?) |
| automation_control | /automation | 自动化控制 | main.py:132 | 无 | M04 | |
| wechat_tasks | /wechat-tasks | 微信任务队列 | main.py:133 | 无 | M04 | |
| webhook_events | /webhook-events | 原始Webhook事件 | main.py:134 | 无 | M02 | |
| agent | /agent | Agent status | main.py:135 | 无 | M03 | |
| douyin_live_check | /integrations/douyin/live-check | 抖音现场联调 | main.py:136 | 无 | PLATFORM | 含 OAuth/callback |
| auth | /auth + /api | 登录权限 | main.py:137,138 | 无 | PLATFORM | 二次挂载加 /api |
| douyin_ai_cs_proxy | /integrations/douyin-ai-cs | 抖音AI客服可信代理 | main.py:139 | 无 | M01 | |
| ai_reply_decision_logs | /ai-reply-decision-logs | AI回复记录 | main.py:140 | 无 | M01 | |
| douyin_autoreply_settings | /douyin-autoreply/settings | 抖音自动回复配置 | main.py:141 | 无 | M01 | |
| ai_auto_reply_runs | /ai-auto-reply-runs | 自动回复运行记录 | main.py:142 | 无 | M01 | |
| admin_autoreply_rollout | /admin/autoreply | 自动回复灰度控制 | main.py:143 | 无 | M01 | |
| admin_test_customer_reset | /admin/test-customer-reset | 测试客户重置 | main.py:144 | 无 | M01 | |
| admin_contact_invalid_mark | /admin/contact-invalid | 联系方式失效标记 | main.py:145 | 无 | M02 | |
| admin_return_visits | /admin | 回访配置与审计 | main.py:146 | 无 | M01 | |
| forbidden_words | /admin | 违禁词管理 | main.py:147 | 无 | M01 | |
| ai_edit | /ai-edit | AI剪辑 | main.py:148 | 无 | M05/M06 | |
| douyin_accounts | /integrations/douyin/accounts | 抖音企业号管理 | main.py:149 | 无 | M01 | |
| agents | /agents | AI小高智能体 | main.py:150 | 无 | M03 | |
| knowledge_categories | /knowledge-categories | 知识分类 | main.py:151 | 无 | M05 | |
| knowledge_training | /knowledge-training | 知识库训练 | main.py:152 | 无 | M05 | |
| compute | /compute | 小高算力 | main.py:153 | 无 | M07 | |
| compute.admin_router | /admin | 超管算力配置 | main.py:154 | 无 | M07 | |
| compute.internal_router | /internal | 内部算力消耗 | main.py:155 | 无 | M07 | M01 上报入口 |
| capability_gateway | /api | 能力中心网关 | main.py:156 | 无 | PLATFORM | |
| replies | /replies | 回复管理 | main.py:157 | 无 | M01 | |
| lead_notification_actions | /lead-notifications | 线索通知 | main.py:158 | 无 | M02 | |
| lead_notification_records | /lead-notifications | 线索通知 | main.py:159 | 无 | M02 | |
| sales_feedback | /sales-feedback | 销售反馈 | main.py:160 | 无 | M02 | |
| daily_reports | /daily-reports | 日报数据补录 | main.py:161 | 无 | PLATFORM | |
| daily_report_deliveries | /daily-report-deliveries | 日报投递 | main.py:162 | 无 | PLATFORM | |
| admin_debug | /admin/debug | 管理员调试 | main.py:163 | 无 | PLATFORM | |
| health | (无) | 健康检查 | main.py:164 | 无 | PLATFORM | |
| feedback | /feedback | 反馈管理 | main.py:168 | `_WINDOWS_ROUTERS_AVAILABLE` | M04 | Windows 专用 |
| lead_notifications | /lead-notifications | 线索通知(Win) | main.py:169 | 同上 | M04 | Windows 专用 |

### 9100 子应用（apps/xg_douyin_ai_cs/main.py:52-60，9 个 router）

| router | prefix | tags | 位置 | 模块 |
|---|---|---|---|---|
| health | (无) | 健康检查 | main.py:52 | PLATFORM |
| categories | (无) | 分类配置 | main.py:53 | M01 |
| accounts | /douyin/accounts | 抖音账号 | main.py:54 | M01 |
| conversations | (无) | 抖音私信会话 | main.py:55 | M01 |
| ai_reply | (无) | AI回复建议 | main.py:56 | M01 |
| rag | /rag | rag | main.py:57 | M01 |
| knowledge_training | /knowledge-training | 知识库训练 | main.py:58 | M05 |
| daily_reports | /internal/daily-reports | 每日销售总结 | main.py:59 | PLATFORM |
| return_visits | /internal/return-visits | 回访判定 | main.py:60 | M01 |

**动态导入排查结论**：无动态路由注册（grep importlib/`__import__` 在 app/ 和 apps/ 生产代码无动态 router 加载，仅内联 `__import__("json")` 和 pymilvus 可选依赖懒加载）。router 集合编译期可完全确定。

---

## 三、Webhook

| 类型 | 路径 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|---|
| Webhook 主路径 | POST /integrations/douyin/webhook | integrations.py:845 | `DOUYIN_WEBHOOK_AUTH_REQUIRED`（dev 可免验签，生产强制） | M02 | 正式入口 |
| Webhook 兼容路径 | POST /webhook/douyin | integrations.py:867 | 同上 | M02 | Legacy (?)，GMP 配置 `callback.misanduo.com/webhook/douyin` 宝塔反代到 9000 |
| 共用处理 | _handle_douyin_webhook | integrations.py:459 | — | M02 | 两入口复用，含验签/掩码解码/internal 转发 |

---

## 四、Scheduler

全部为 `threading.Thread(daemon=True)` + `time.sleep` 自实现循环（**无 APScheduler**），在 `app/main.py:171` 的 `@app.on_event("startup")` 拉起。

| 标识 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|
| check_scheduler | main.py:183；scheduler/check_scheduler.py:24 | **默认开**，无条件 | M04 | 间隔从 DB `check_interval_minutes`（默认 5 分钟） |
| daily_report_scheduler | main.py:188；scheduler/daily_report_scheduler.py:58 | `DAILY_REPORT_SCHEDULER_ENABLED=true`（默认关） | PLATFORM | |
| wechat_auto_detect_scheduler | main.py:198；scheduler/wechat_auto_detect_scheduler.py:43 | `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1`（默认关） | M04 | Legacy (?)，旧链路，新主线走 19000 |
| return_visit_silent_scan_scheduler | main.py:233；scheduler/return_visit_silent_scan_scheduler.py:31 | `RETURN_VISIT_SILENT_SCAN_ENABLED=true`（默认关） | M01/M02 | 间隔 3600s |
| start_outbox_scheduler | main.py:229；ai_auto_reply_outbox_service.py:643 | `AI_AUTO_REPLY_OUTBOX_ENABLED=true`（默认关） | M01 | outbox 调度器 |
| start_followup_scheduler | main.py:237；contact_invalid_followup_service.py:404 | `CONTACT_INVALID_FOLLOWUP_ENABLED=true`（默认关，**直接读 os.environ 未进 config.py**） | M01/M02 | 空号追问，间隔 30s |
| reconcile_return_visit_runs_on_startup | main.py:220 | **默认开**（一次性 daemon 线程） | M01 | 崩溃恢复，非周期 |
| start_hotkey_listener / start_desktop_overlay | main.py:213-214 | **默认开**（Windows 专用） | PLATFORM | P8-4 全局热键/桌面提示 |

shutdown 钩子在 `main.py:240`（`@app.on_event("shutdown")`），逐项 stop。

**注意**：代码用旧式 `@app.on_event`（非 lifespan/asynccontextmanager），docs 中误称 lifespan 处需修正。

---

## 五、Worker

| 标识 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|
| run_outbox_cycle | ai_auto_reply_outbox_service.py:544 | `AI_AUTO_REPLY_OUTBOX_ENABLED=true` | M01 | outbox claim/lease/处理，被 _scheduler_loop 周期调用 |
| run_followup_cycle | contact_invalid_followup_service.py:130 | `CONTACT_INVALID_FOLLOWUP_ENABLED=true` | M01/M02 | 空号追问 claim→发送→回写 |
| _wake_outbox_scheduler（BackgroundTask） | integrations.py:340 | webhook 唤醒，仅 `AI_AUTO_REPLY_OUTBOX_ENABLED` | M01 | webhook 触发 |
| _run_resource_download_task（BackgroundTask） | integrations.py:389 | webhook `im_receive_msg` + message_type ∈ {image,video,emoji} | M02 | 素材下载 |
| process_las_job（BackgroundTask） | ai_edit.py:713 → ai_edit_las_service.py:119 | POST /ai-edit/las/jobs 触发 | M06 | LAS 轮询非独立 HTTP 端点 |

---

## 六、Startup Hook

全部在 `app/main.py:171`（`@app.on_event("startup")`）。9100 子应用无 startup/shutdown 钩子。

| 启动项 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|
| init_async_database_runtime | main.py:173 | `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` + postgresql | M05/PLATFORM | 否则 log skip |
| scheduler.start()（check） | main.py:183 | 无条件 | M04 | |
| daily_report_scheduler.start() | main.py:188 | `DAILY_REPORT_SCHEDULER_ENABLED` | PLATFORM | |
| wechat_auto_detect_scheduler.start() | main.py:198 | `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT` | M04 | Legacy (?) |
| start_hotkey_listener() | main.py:213 | 无条件（Windows） | PLATFORM | |
| start_desktop_overlay() | main.py:214 | 无条件（Windows） | PLATFORM | |
| reconcile_return_visit_runs_on_startup | main.py:220 | 无条件（一次性） | M01 | |
| start_outbox_scheduler() | main.py:229 | `AI_AUTO_REPLY_OUTBOX_ENABLED` | M01 | |
| return_visit_silent_scan_scheduler.start() | main.py:233 | `RETURN_VISIT_SILENT_SCAN_ENABLED` | M01/M02 | |
| start_followup_scheduler() | main.py:237 | `CONTACT_INVALID_FOLLOWUP_ENABLED` | M01/M02 | |

---

## 七、CLI

| 标识 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|
| local_agent_main（19000 Local Agent） | local_agent_main.py:2904；argparse:2881 | 宿主机手动运行；`LOCAL_AGENT_AUTH_REQUIRED` | M04 | 新主线，替代旧 wechat_auto_detect_scheduler |
| scripts/ 下 57 个脚本（含 `__main__`） | scripts/*.py | 手动执行 | 多 | DB 迁移/smoke/seed/调试/运维；29 个用 argparse |
| scripts/production_pg_*.sh（10 个 shell） | scripts/ | 手动执行 | PLATFORM | PG 切换 Runbook |
| scripts/build_local_agent_exe.ps1 等 | scripts/*.ps1 | 手动执行 | M04 | PyInstaller 打包 |

---

## 八、Docker Command

启动命令在 compose `command:` 字段（覆盖 Dockerfile CMD）。

### docker-compose.yml（生产主入口）

| 服务 | command | 位置 | 模块 |
|---|---|---|---|
| postgres | (无，用 postgres:16-alpine 默认) | docker-compose.yml:11 | PLATFORM |
| auto-wechat-api | `python -m uvicorn app.main:app --host 0.0.0.0 --port 9000` | docker-compose.yml:49 | 9000 |
| xg-douyin-ai-cs | `python -m uvicorn apps.xg_douyin_ai_cs.main:app --host 0.0.0.0 --port 9100` | docker-compose.yml:93 | 9100 |
| auto-wechat-frontend | `sh -c 'npm run build && npm run preview -- --host 0.0.0.0 --port 5173'` | docker-compose.yml:126 | 5173 |

### docker-compose.dev.yml（本地开发独立编排，含能力中心 9201-9206）

| 服务 | command | 位置 | 备注 |
|---|---|---|---|
| auto-wechat-sqlite-migrate | `python migrations/migrate_sqlite.py --db-path ... --startup` | dev.yml:63 | 迁移 |
| auto-wechat-api | uvicorn app.main:app --port 9000 | dev.yml:124 | |
| xg-douyin-ai-cs | uvicorn apps.xg_douyin_ai_cs.main:app --port 9100 | dev.yml:188 | |
| douyin-cs-service | uvicorn apps.douyin_cs.main:app --port 9201 | dev.yml:208 | 能力中心 |
| leads-service | uvicorn apps.leads.main:app --port 9202 | dev.yml:227 | 能力中心 |
| agents-service | uvicorn apps.agents.main:app --port 9203 | dev.yml:246 | 能力中心 |
| wechat-assistant-service | uvicorn apps.wechat_assistant.main:app --port 9204 | dev.yml:265 | 能力中心 |
| compute-service | uvicorn apps.compute.main:app --port 9205 | dev.yml:284 | 能力中心 |
| knowledge-service | uvicorn apps.knowledge.main:app --port 9206 | dev.yml:303 | 能力中心 |
| auto-wechat-frontend | (用 Dockerfile.frontend.dev CMD) | dev.yml:307 | |

### Dockerfile

| 文件 | CMD | 位置 | 备注 |
|---|---|---|---|
| Dockerfile | (已废弃) | Dockerfile:54 | DEPRECATED，SQLite-only，APP_ENV=production 拒绝启动 (?) |
| Dockerfile.backend.dev | `uvicorn app.main:app --port 9000` | :38 | 9000/9100 共用，compose command 覆盖 |
| Dockerfile.frontend.dev | `npm run dev --host 0.0.0.0 --port 5173` | :23 | 生产用 build+preview 覆盖 |

**19000 Local Agent 不进容器**（依赖宿主机 Windows 微信窗口/UIA/OCR）。

---

## 九、Callback

| 类型 | 路径 | 代码位置 | 启用条件 | 模块 | 备注 |
|---|---|---|---|---|---|
| OAuth 回跳（主） | GET /integrations/douyin/live-check/auth-redirect | douyin_live_check.py:231 | 抖音 GMP `auth_redirect_url` 指向；前端 origin 须在 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS_SET` | M02 | 真正同步抖音账号，302 跳 `douyinapi.misanduo.com` |
| OAuth 观察回调 | GET /integrations/douyin/live-check/oauth-callback | douyin_live_check.py:125 | OAuth 流程触发 | PLATFORM | 仅观察不写库 |
| 私信事件回调 | POST /integrations/douyin/live-check/webhook-observe | douyin_live_check.py:482 | 9000 主服务 | M02 | 与 callback 复用 |
| 私信事件回调 | POST /integrations/douyin/live-check/callback | douyin_live_check.py:492 | `DY_CALLBACK_URL` 指向 | M02 | 抖音 im 事件回调地址 |
| NewCar 登录回调 | GET /auth/callback | auth.py:79 | 带 code 换 token | PLATFORM | 二次挂载 /api/auth/callback |
| LAS 任务轮询 | BackgroundTask process_las_job | ai_edit.py:713 | POST /ai-edit/las/jobs 触发 | M06 | 非独立 HTTP，轮询 LAS wait_for_terminal |
| 外部域名 callback.misanduo.com | integrations.py:877（注释） | GMP 配置 + 宝塔反代到 9000 | M02/M04 | 生产 webhook/任务回写域名 |
| 外部域名 douyinapi.misanduo.com | douyin_live_check.py:56 | 配置未覆盖时默认 | M02 | OAuth 前端回跳默认 origin |

### Local Agent 19000 端点（M04，`app/local_agent_main.py`，非 APIRouter 直接 @app 挂载）

| 类型 | 路径 | 代码位置 | 备注 |
|---|---|---|---|
| GET | /runtime/status | :1635 | 运行时快照 |
| POST | /runtime/enable-task-polling | :1639 | 启用任务轮询 |
| POST | /runtime/disable-task-polling | :1646 | 关闭任务轮询 |
| GET | /agent/version | :1652 | 版本+路由列表 |
| GET | /health | :1671 | 健康检查 |
| GET | /agent/ocr/status | :1682 | OCR 状态 |
| POST | /agent/ocr/warmup | :1686 | OCR 预热 |
| POST | /agent/wechat/test | :1690 | 微信测试 |
| POST | /agent/wechat/foreground-debug | :1694 | 前台调试 |
| POST | /agent/wechat/search-debug | :1698 | 搜索调试 |
| POST | /agent/wechat/search-calibration/start | :1713 | 搜索校准 |
| POST | /agent/wechat/search-result-debug | :1717 | 搜索结果调试 |
| POST | /agent/wechat/mouse-debug | :1732 | 鼠标调试 |
| GET | /agent/wechat/windows | :1849 | 窗口列表 |
| POST | /agent/wechat/file-message-probe | :2570 | 文件消息探测 |
| POST | /agent/replies/detect | :2663 | 回复检测 |
| GET | /agent/tasks/server-url | :1863 | 主系统地址 |
| POST | /agent/tasks/poll-and-execute | :1871 | 主动轮询执行 |
| POST | /agent/tasks/poll-and-detect | :2246 | 轮询检测 |
| POST | /agent/tasks/poll-and-send-report | :2482 | 轮询发报表 |

---

## 环境变量控制的隐藏入口（静态 grep 盲区汇总）

| Env 开关 | 位置 | 默认 | 模块 | 控制的入口 | 备注 |
|---|---|---|---|---|---|
| LEADS_WEBHOOK_INTERNAL_ENABLED | config.py:316 | false | M02 | webhook internal 模式 | |
| AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT | config.py:349 | 0（关） | M04 | wechat_auto_detect_scheduler | Legacy (?) |
| AI_AUTO_REPLY_OUTBOX_ENABLED | config.py:303 | false | M01 | outbox 调度器 + webhook _wake_outbox_scheduler | |
| CONTACT_INVALID_FOLLOWUP_ENABLED | main.py:236（**未进 config.py**） | false | M01/M02 | 空号追问调度器 | 唯一直接读 os.environ 的调度器开关 |
| LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED | config.py:329 | false | M04 | replies.py 调试端点 | Legacy (?) |
| DAILY_REPORT_SCHEDULER_ENABLED | config.py:377 | false | PLATFORM | 日报调度器 | |
| RETURN_VISIT_SILENT_SCAN_ENABLED | config.py:381 | false | M01/M02 | 回访沉默扫描 | |
| KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED | config.py:176 | false | M05 | 启动时异步 PG 初始化 | |
| DOUYIN_DECODE_MASKED_ENABLED | config.py:236 | true | M01 | webhook 掩码解码 | |
| DOUYIN_WEBHOOK_AUTH_REQUIRED | config.py:244 | false（生产强制 true） | PLATFORM | webhook 验签 | |
| DOUYIN_AUTO_REPLY_ENABLED | config.py:295 | false | M01 | 自动回复总开关 | |
| DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED | config.py:296 | false | M01 | 真实发送开关 | |
| LOCAL_AGENT_AUTH_REQUIRED | config.py:324 | false | M04 | Local Agent 鉴权 | |
| NEWCAR_AUTH_ENABLED | config.py:260 | false | PLATFORM | NewCar 鉴权 | |
| DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED | config.py:412 | false | M04 | 日报附件投递 | |
