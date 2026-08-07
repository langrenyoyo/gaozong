# 运行入口盘点

> 基于 2026-08-07 代码事实（commit c26ec227e70d，source_baseline）。
> Legacy 只标 `?`（UNKNOWN ≠ LEGACY，正式定性见 1A.5）。
> 模块：M01客服 / M02线索 / M03智能体 / M04微信助手 / M05素材库 / M06剪辑 / M07算力 / PLATFORM。

## 索引语义约定

### 运行状态（Runtime State：现在能不能跑）
- `always` — 定义+注册+默认启用，无条件可达
- `conditional` — 定义+注册，受 env/配置/权限门控，满足条件才可达
- `disabled_by_default` — 定义+注册，但默认关闭（ACTIVE + disabled_by_default 可同时成立）
- `manual_only` — 需人工执行（CLI/脚本），无自动调度
- `dev_only` — 仅开发/本地环境（Windows 专用路由、dev compose）
- `unreachable` — 定义存在但运行时不可达（已废弃 Dockerfile 等）

### 生命周期（Lifecycle：未来还要不要，正式定性见 1A.5）
- `ACTIVE` — 当前主线
- `COMPAT` — 兼容保留
- `LEGACY` — 旧链路已被新主线替代
- `DEAD_CANDIDATE` — 死代码候选
- `UNKNOWN` — 未定性

**关键**：代码存在 ≠ 运行入口。`disabled_by_default` + `ACTIVE` 完全可能成立（如 outbox 是主线但默认关）。

### Worker 分类
- **Persistent/Durable Worker**：独立任务状态表 + claim/lease/retry，进程重启可恢复
- **In-process Background Task**：FastAPI BackgroundTask，HTTP 请求进程内延迟任务，无独立队列消费进程，进程退出可能影响

### 数量与验收
索引正确性 = CODE discovered entrypoints == INDEX registered entrypoints（集合关系），不是数量不变。

### 部署命令优先级
实际部署 compose `command:` > 环境特定 override > Dockerfile CMD。VibeCoding 不能只看 Dockerfile。

### 动态路由结论
在 source_baseline（c26ec227）对应的生产代码扫描范围内，未发现动态 Router 注册（grep importlib/`__import__` 在 app/ 和 apps/ 无动态 router 加载，仅内联 `__import__("json")` 和 pymilvus 可选依赖懒加载）。此结论绑定 source_baseline，不构成永久性绝对结论。

### Scheduler 运行时模型（索引事实）
`scheduler_runtime_model: type=in_process_thread`——全部调度器为 `threading.Thread(daemon=True)` + `time.sleep` 自实现循环（无 APScheduler）。影响：多副本部署会重复调度（需 lease 防重）、重启恢复依赖持久化任务表、扩缩容无原生 leader election。

### Webhook 入口/处理器
`transport_entrypoint=2, business_handler=1`——2 个公开 webhook 入口（主路径 + 兼容路径）共享 1 个业务处理器 `_handle_douyin_webhook`。

---

## 一、Frontend Routes

React Router（`BrowserRouter` + `Routes` + 动态 `Route`），非 createBrowserRouter。路由聚合在 `frontend/src/features/routes.ts:9`（`capabilityRoutes`）+ `App.tsx:40`（`adminRoutes`）+ `routes.ts:18`（legacy 重定向）。

### Capability 路由（用户权限过滤后动态渲染，`App.tsx:719`）

| 路径 | navId | 代码位置 | runtime_state | lifecycle | 模块 |
|---|---|---|---|---|---|
| `/douyin-cs/workbench` | douyin-ai-cs | features/douyin-cs/routes.ts:4 | conditional（权限） | ACTIVE | M01 |
| `/douyin-cs/auto-reply-runs` | douyin-auto-reply-diagnostics | features/douyin-cs/routes.ts:5 | conditional（权限） | ACTIVE | M01 |
| `/leads` | leads | features/leads/routes.ts:4 | conditional（权限） | ACTIVE | M02 |
| `/agents` | ai-agents | features/agents/routes.ts:4 | conditional（权限，复用客服权限） | ACTIVE | M03 |
| `/wechat-assistant` | ai-agent | features/wechat-assistant/routes.ts:4 | conditional（权限） | ACTIVE | M04 |
| `/wechat-assistant/config` | wechat-config | routes.ts:5 | conditional | ACTIVE | M04 |
| `/wechat-assistant/tasks` | wechat-tasks | routes.ts:6 | conditional | ACTIVE | M04 |
| `/wechat-assistant/download-test` | wechat-download-test | routes.ts:7 | conditional | ACTIVE | M04 |
| `/wechat-assistant/daily-reports` | wechat-daily-reports | routes.ts:8 | conditional | ACTIVE | M04 |
| `/compute/center` | compute | features/compute/routes.ts:4 | conditional（权限） | ACTIVE | M07 |
| `/compute/token-transactions` | compute-token-transactions | routes.ts:5 | conditional | ACTIVE | M07 |
| `/compute/recharge-orders` | compute-recharge-orders | routes.ts:6 | conditional | ACTIVE | M07 |
| `/ai-edit/materials` | ai-edit-materials | features/ai-edit/routes.ts:6 | conditional（权限） | ACTIVE | M05 |
| `/ai-edit/editor` | ai-edit-editor | features/ai-edit/routes.ts:7 | conditional | ACTIVE | M06 |

### Admin 路由（`App.tsx:40-48`）

| 路径 | navId | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|---|
| `/admin/autoreply-rollout` | admin-autoreply-rollout | App.tsx:41 | conditional | UNKNOWN | M01 | 入口已隐藏，路由保留 |
| `/admin/return-visits` | admin-return-visits | App.tsx:42 | conditional | ACTIVE | M01 | |
| `/admin/ai-reply-records` | ai-reply-records | App.tsx:43 | conditional | ACTIVE | M01 | |
| `/admin/forbidden-words` | admin-forbidden-words | App.tsx:44 | conditional | ACTIVE | M01 | |
| `/admin/compute-config` | admin-compute-config | App.tsx:45 | conditional | ACTIVE | M07 | |
| `/admin/no-local-feature` | admin-no-local-feature | App.tsx:46 | conditional | ACTIVE | PLATFORM | 兜底 |
| `/admin/newcar-owned` | admin-newcar-owned | App.tsx:47 | conditional | ACTIVE | PLATFORM | 提示去 NewCar |

### Legacy 路由重定向（`routes.ts:18-41`，22 条）

全部 lifecycle=COMPAT（兼容重定向），runtime_state=always（无条件重定向）。代表性：

| from | to |
|---|---|
| `/douyin-ai-cs` | `/douyin-cs/workbench` |
| `/leads/list` `/leads/board` `/leads/detail` | `/leads` |
| `/ai-agent` | `/wechat-assistant` |
| `/agents/new` `/agents/edit` | `/agents` |
| `/compute` `/compute/packages` `/compute/markup-ratios` | `/compute/center` 或 `/admin/compute-config?view=` |
| `/knowledge-base` `/knowledge-categories` 等 | `/douyin-cs/workbench` |

完整 22 条见 `routes.ts:18-41`。

---

## 二、FastAPI Routers

### 9000 主服务（app/main.py:125-169，42 个 router）

条件加载仅 Windows 专用路由（`main.py:60-65` try/except + `main.py:167-169`）。

| router | prefix | 位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|---|
| staff | /staff | main.py:125 | always | ACTIVE | M02 | |
| leads | /leads | main.py:126 | always | ACTIVE | M02 | |
| checks | /checks | main.py:127 | always | ACTIVE | M01 | |
| reports | /reports | main.py:128 | always | ACTIVE | PLATFORM | |
| integrations | /integrations/douyin | main.py:129 | always | ACTIVE | PLATFORM/M02 | 含正式 webhook |
| legacy_webhook_router | /webhook | main.py:130 | always | COMPAT | M02 | 兼容路径 |
| wechat_auto_detect | /wechat-auto-detect | main.py:131 | always | LEGACY | M04 | 旧链路 |
| automation_control | /automation | main.py:132 | always | ACTIVE | M04 | |
| wechat_tasks | /wechat-tasks | main.py:133 | always | ACTIVE | M04 | |
| webhook_events | /webhook-events | main.py:134 | always | ACTIVE | M02 | |
| agent | /agent | main.py:135 | always | ACTIVE | M03 | |
| douyin_live_check | /integrations/douyin/live-check | main.py:136 | always | ACTIVE | PLATFORM | 含 OAuth/callback |
| auth | /auth + /api | main.py:137,138 | always | ACTIVE | PLATFORM | 二次挂载 |
| douyin_ai_cs_proxy | /integrations/douyin-ai-cs | main.py:139 | always | ACTIVE | M01 | |
| ai_reply_decision_logs | /ai-reply-decision-logs | main.py:140 | always | ACTIVE | M01 | |
| douyin_autoreply_settings | /douyin-autoreply/settings | main.py:141 | always | ACTIVE | M01 | |
| ai_auto_reply_runs | /ai-auto-reply-runs | main.py:142 | always | ACTIVE | M01 | |
| admin_autoreply_rollout | /admin/autoreply | main.py:143 | always | UNKNOWN | M01 | 入口隐藏 |
| admin_test_customer_reset | /admin/test-customer-reset | main.py:144 | always | ACTIVE | M01 | |
| admin_contact_invalid_mark | /admin/contact-invalid | main.py:145 | always | ACTIVE | M02 | |
| admin_return_visits | /admin | main.py:146 | always | ACTIVE | M01 | |
| forbidden_words | /admin | main.py:147 | always | ACTIVE | M01 | |
| ai_edit | /ai-edit | main.py:148 | always | ACTIVE | M05/M06 | |
| douyin_accounts | /integrations/douyin/accounts | main.py:149 | always | ACTIVE | M01 | |
| agents | /agents | main.py:150 | always | ACTIVE | M03 | |
| knowledge_categories | /knowledge-categories | main.py:151 | always | ACTIVE | M05 | |
| knowledge_training | /knowledge-training | main.py:152 | always | ACTIVE | M05 | |
| compute | /compute | main.py:153 | always | ACTIVE | M07 | |
| compute.admin_router | /admin | main.py:154 | always | ACTIVE | M07 | |
| compute.internal_router | /internal | main.py:155 | always | ACTIVE | M07 | M01 上报入口 |
| capability_gateway | /api | main.py:156 | always | ACTIVE | PLATFORM | |
| replies | /replies | main.py:157 | always | ACTIVE | M01 | |
| lead_notification_actions | /lead-notifications | main.py:158 | always | ACTIVE | M02 | |
| lead_notification_records | /lead-notifications | main.py:159 | always | ACTIVE | M02 | |
| sales_feedback | /sales-feedback | main.py:160 | always | ACTIVE | M02 | |
| daily_reports | /daily-reports | main.py:161 | always | ACTIVE | PLATFORM | |
| daily_report_deliveries | /daily-report-deliveries | main.py:162 | always | ACTIVE | PLATFORM | |
| admin_debug | /admin/debug | main.py:163 | always | ACTIVE | PLATFORM | |
| health | (无) | main.py:164 | always | ACTIVE | PLATFORM | |
| feedback | /feedback | main.py:168 | dev_only（Windows） | ACTIVE | M04 | Windows 专用 |
| lead_notifications | /lead-notifications | main.py:169 | dev_only（Windows） | ACTIVE | M04 | Windows 专用 |

### 9100 子应用（apps/xg_douyin_ai_cs/main.py:52-60，9 个 router）

全部 runtime_state=always，lifecycle=ACTIVE。

| router | prefix | 位置 | 模块 |
|---|---|---|---|
| health | (无) | main.py:52 | PLATFORM |
| categories | (无) | main.py:53 | M01 |
| accounts | /douyin/accounts | main.py:54 | M01 |
| conversations | (无) | main.py:55 | M01 |
| ai_reply | (无) | main.py:56 | M01 |
| rag | /rag | main.py:57 | M01 |
| knowledge_training | /knowledge-training | main.py:58 | M05 |
| daily_reports | /internal/daily-reports | main.py:59 | PLATFORM |
| return_visits | /internal/return-visits | main.py:60 | M01 |

---

## 三、Webhook

`transport_entrypoint=2, business_handler=1`——2 入口共享 `_handle_douyin_webhook`。

| 路径 | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|
| POST /integrations/douyin/webhook | integrations.py:845 | conditional（DOUYIN_WEBHOOK_AUTH_REQUIRED，生产强制） | ACTIVE | M02 | 正式入口 |
| POST /webhook/douyin | integrations.py:867 | conditional | COMPAT | M02 | GMP 配置 `callback.misanduo.com/webhook/douyin` 宝塔反代到 9000 |

---

## 四、Scheduler

`scheduler_runtime_model: in_process_thread`（无 APScheduler，全 threading+sleep）。在 `app/main.py:171` 的 `@app.on_event("startup")` 拉起（**TECH_DEBT：FastAPI 已废弃的 startup API，应迁移 lifespan，本阶段不改代码**）。

| 标识 | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|
| check_scheduler | main.py:183；scheduler/check_scheduler.py:24 | always | ACTIVE | M04 | 间隔从 DB `check_interval_minutes`（默认 5 分钟） |
| daily_report_scheduler | main.py:188；scheduler/daily_report_scheduler.py:58 | disabled_by_default（DAILY_REPORT_SCHEDULER_ENABLED） | ACTIVE | PLATFORM | |
| wechat_auto_detect_scheduler | main.py:198；scheduler/wechat_auto_detect_scheduler.py:43 | disabled_by_default（AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT） | LEGACY | M04 | 旧链路，新主线走 19000 |
| return_visit_silent_scan_scheduler | main.py:233；scheduler/return_visit_silent_scan_scheduler.py:31 | disabled_by_default（RETURN_VISIT_SILENT_SCAN_ENABLED） | ACTIVE | M01/M02 | 间隔 3600s |
| start_outbox_scheduler | main.py:229；ai_auto_reply_outbox_service.py:643 | disabled_by_default（AI_AUTO_REPLY_OUTBOX_ENABLED） | ACTIVE | M01 | outbox 调度器 |
| start_followup_scheduler | main.py:237；contact_invalid_followup_service.py:404 | disabled_by_default（CONTACT_INVALID_FOLLOWUP_ENABLED） | ACTIVE | M01/M02 | 空号追问，间隔 30s |
| reconcile_return_visit_runs_on_startup | main.py:220 | always（一次性 daemon） | ACTIVE | M01 | 崩溃恢复，非周期 |
| start_hotkey_listener / start_desktop_overlay | main.py:213-214 | always（Windows 专用） | ACTIVE | PLATFORM | P8-4 |

shutdown 钩子在 `main.py:240`（`@app.on_event("shutdown")`，TECH_DEBT 同上）。

---

## 五、Worker

### Persistent/Durable Worker（独立任务状态 + claim/lease/retry，进程重启可恢复）

| 标识 | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|
| run_outbox_cycle | ai_auto_reply_outbox_service.py:544 | conditional（AI_AUTO_REPLY_OUTBOX_ENABLED） | ACTIVE | M01 | outbox claim/lease/处理，被 _scheduler_loop 周期调用；AiAutoReplyRun 表持久化 |
| run_followup_cycle | contact_invalid_followup_service.py:130 | conditional（CONTACT_INVALID_FOLLOWUP_ENABLED） | ACTIVE | M01/M02 | 空号追问 claim→发送→回写；ContactInvalidFollowupTask 表持久化 |

### In-process Background Task（FastAPI BackgroundTask，无独立队列消费进程，进程退出可能影响）

| 标识 | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|
| _wake_outbox_scheduler | integrations.py:340 | conditional（AI_AUTO_REPLY_OUTBOX_ENABLED） | ACTIVE | M01 | webhook 唤醒 outbox（仅唤醒，实际处理由 Persistent Worker） |
| _run_resource_download_task | integrations.py:389 | conditional（webhook message_type ∈ {image,video,emoji}） | ACTIVE | M02 | 素材下载；失败记 DouyinMessageResourceDownload 表 |
| process_las_job | ai_edit.py:713 → ai_edit_las_service.py:119 | conditional（POST /ai-edit/las/jobs 触发） | ACTIVE | M06 | LAS 轮询，非独立 HTTP 端点；进程退出轮询中断 |

---

## 六、Startup Hook

全部在 `app/main.py:171`（`@app.on_event("startup")`，**TECH_DEBT**）。9100 子应用无 startup/shutdown 钩子。

| 启动项 | 代码位置 | runtime_state | lifecycle | 模块 |
|---|---|---|---|---|
| init_async_database_runtime | main.py:173 | conditional（KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED + postgresql） | ACTIVE | M05/PLATFORM |
| scheduler.start()（check） | main.py:183 | always | ACTIVE | M04 |
| daily_report_scheduler.start() | main.py:188 | conditional（DAILY_REPORT_SCHEDULER_ENABLED） | ACTIVE | PLATFORM |
| wechat_auto_detect_scheduler.start() | main.py:198 | conditional（AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT） | LEGACY | M04 |
| start_hotkey_listener() | main.py:213 | always（Windows） | ACTIVE | PLATFORM |
| start_desktop_overlay() | main.py:214 | always（Windows） | ACTIVE | PLATFORM |
| reconcile_return_visit_runs_on_startup | main.py:220 | always（一次性） | ACTIVE | M01 |
| start_outbox_scheduler() | main.py:229 | conditional（AI_AUTO_REPLY_OUTBOX_ENABLED） | ACTIVE | M01 |
| return_visit_silent_scan_scheduler.start() | main.py:233 | conditional（RETURN_VISIT_SILENT_SCAN_ENABLED） | ACTIVE | M01/M02 |
| start_followup_scheduler() | main.py:237 | conditional（CONTACT_INVALID_FOLLOWUP_ENABLED） | ACTIVE | M01/M02 |

---

## 七、CLI

按 `execution_class` 分类。

| 标识 | 代码位置 | execution_class | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|---|
| local_agent_main（19000） | local_agent_main.py:2904；argparse:2881 | production_runtime | manual_only（宿主机运行；LOCAL_AGENT_AUTH_REQUIRED） | ACTIVE | M04 | 新主线，替代旧 wechat_auto_detect_scheduler |
| scripts/init_db.py | scripts/ | maintenance | manual_only | ACTIVE | PLATFORM | DB 初始化 |
| scripts/migrate_*_sqlite_to_postgres*.py（7 个） | scripts/ | migration | manual_only | ACTIVE | PLATFORM | SQLite→PG 一次性迁移 |
| scripts/production_pg_*.sh（10 个 shell） | scripts/ | production_ops | manual_only | ACTIVE | PLATFORM | PG 切换 Runbook（alembic/backup/cutover/smoke） |
| scripts/smoke_*.py / p0_c_deployment_verify.py / verify_phase8*.py / preflight*.py | scripts/ | smoke_test | manual_only | ACTIVE | PLATFORM | 部署验证 |
| scripts/seed_demo_data.py / seed_dev_data.py / run_demo_flow.py / generate_phase8_visual_samples.py | scripts/ | dev_tool | manual_only | ACTIVE | PLATFORM | 开发数据填充 |
| scripts/debug_*.py / probe_*.py | scripts/ | dev_tool | manual_only | UNKNOWN | M04/PLATFORM | 调试探针 |
| scripts/fix_ai_edit_jobs.py / repair_*.py / prepare_easyocr_models.py / check_sqlite_specific_usage.py | scripts/ | maintenance | manual_only | ACTIVE | PLATFORM | 运维修复 |
| scripts/generate_code_index.py | scripts/ | dev_tool | manual_only | ACTIVE | PLATFORM | 文档生成（1A.2） |
| scripts/build_local_agent_exe.ps1 等（4 个 ps1） | scripts/ | production_ops | manual_only | ACTIVE | M04 | PyInstaller 打包 |
| scripts/audit_phase12_task12_duplicate_materials.py | scripts/ | maintenance | manual_only | ACTIVE | M05 | 审计 |

---

## 八、Docker Command

部署命令优先级：实际部署 compose `command:` > 环境特定 override > Dockerfile CMD。

### docker-compose.yml（生产主入口）

| 服务 | command | 位置 | runtime_state | lifecycle | 备注 |
|---|---|---|---|---|---|
| postgres | (无，postgres:16-alpine 默认) | docker-compose.yml:11 | always | ACTIVE | |
| auto-wechat-api | `python -m uvicorn app.main:app --host 0.0.0.0 --port 9000` | docker-compose.yml:49 | always | ACTIVE | 覆盖 Dockerfile CMD |
| xg-douyin-ai-cs | `python -m uvicorn apps.xg_douyin_ai_cs.main:app --host 0.0.0.0 --port 9100` | docker-compose.yml:93 | always | ACTIVE | 覆盖 Dockerfile CMD |
| auto-wechat-frontend | `sh -c 'npm run build && npm run preview --host 0.0.0.0 --port 5173'` | docker-compose.yml:126 | always | ACTIVE | 覆盖 Dockerfile CMD |

### docker-compose.dev.yml（本地开发独立编排，含能力中心 9201-9206）

| 服务 | command | 位置 | runtime_state | 备注 |
|---|---|---|---|---|
| auto-wechat-sqlite-migrate | `python migrations/migrate_sqlite.py --db-path ... --startup` | dev.yml:63 | dev_only | 迁移 |
| auto-wechat-api | uvicorn app.main:app --port 9000 | dev.yml:124 | dev_only | |
| xg-douyin-ai-cs | uvicorn apps.xg_douyin_ai_cs.main:app --port 9100 | dev.yml:188 | dev_only | |
| douyin-cs-service | uvicorn apps.douyin_cs.main:app --port 9201 | dev.yml:208 | dev_only | 能力中心 |
| leads-service | uvicorn apps.leads.main:app --port 9202 | dev.yml:227 | dev_only | 能力中心 |
| agents-service | uvicorn apps.agents.main:app --port 9203 | dev.yml:246 | dev_only | 能力中心 |
| wechat-assistant-service | uvicorn apps.wechat_assistant.main:app --port 9204 | dev.yml:265 | dev_only | 能力中心 |
| compute-service | uvicorn apps.compute.main:app --port 9205 | dev.yml:284 | dev_only | 能力中心 |
| knowledge-service | uvicorn apps.knowledge.main:app --port 9206 | dev.yml:303 | dev_only | 能力中心 |
| auto-wechat-frontend | (用 Dockerfile.frontend.dev CMD) | dev.yml:307 | dev_only | |

### docker-compose.staging.yml
仅覆盖 container_name/image/env_file/ports/volumes/environment，**无 command 字段**——沿用 base docker-compose.yml 的 command。

### Dockerfile

| 文件 | CMD | 位置 | runtime_state | lifecycle | 备注 |
|---|---|---|---|---|---|
| Dockerfile | (废弃) | Dockerfile:54 | unreachable | DEAD_CANDIDATE | DEPRECATED，SQLite-only，APP_ENV=production 拒绝启动 |
| Dockerfile.backend.dev | `uvicorn app.main:app --port 9000` | :38 | always（被 compose 覆盖） | ACTIVE | 9000/9100 共用 |
| Dockerfile.frontend.dev | `npm run dev --host 0.0.0.0 --port 5173` | :23 | always（被 compose 覆盖） | ACTIVE | 生产用 build+preview 覆盖 |

**19000 Local Agent 不进容器**（依赖宿主机 Windows 微信窗口/UIA/OCR）。

---

## 九、Callback

### External Callback（外部系统投递的回调）

| 类型 | 路径 | 代码位置 | runtime_state | lifecycle | 模块 | 备注 |
|---|---|---|---|---|---|---|
| OAuth 回跳（主） | GET /integrations/douyin/live-check/auth-redirect | douyin_live_check.py:231 | conditional（origin 白名单） | ACTIVE | M02 | 真正同步抖音账号，302 跳 `douyinapi.misanduo.com` |
| OAuth 观察回调 | GET /integrations/douyin/live-check/oauth-callback | douyin_live_check.py:125 | conditional | ACTIVE | PLATFORM | 仅观察不写库 |
| 私信事件回调 | POST /integrations/douyin/live-check/webhook-observe | douyin_live_check.py:482 | conditional | ACTIVE | M02 | 与 callback 复用 |
| 私信事件回调 | POST /integrations/douyin/live-check/callback | douyin_live_check.py:492 | conditional（DY_CALLBACK_URL） | ACTIVE | M02 | 抖音 im 事件回调地址 |
| NewCar 登录回调 | GET /auth/callback | auth.py:79 | conditional（带 code 换 token） | ACTIVE | PLATFORM | 二次挂载 /api/auth/callback |
| 外部域名 callback.misanduo.com | integrations.py:877（注释） | always | COMPAT | M02/M04 | 生产 webhook/任务回写域名 |
| 外部域名 douyinapi.misanduo.com | douyin_live_check.py:56 | always | COMPAT | M02 | OAuth 前端回跳默认 origin |

### Local Agent API（19000，M04，`app/local_agent_main.py`，非 APIRouter 直接 @app 挂载）

按功能分类（tag）：

| 路径 | 代码位置 | tag | runtime_state | lifecycle | 备注 |
|---|---|---|---|---|---|
| GET /runtime/status | :1635 | agent_control | always | ACTIVE | 运行时快照 |
| POST /runtime/enable-task-polling | :1639 | agent_control | always | ACTIVE | 启用任务轮询 |
| POST /runtime/disable-task-polling | :1646 | agent_control | always | ACTIVE | 关闭任务轮询 |
| GET /agent/version | :1652 | heartbeat | always | ACTIVE | 版本+路由列表 |
| GET /health | :1671 | heartbeat | always | ACTIVE | 健康检查 |
| GET /agent/ocr/status | :1682 | agent_control | always | ACTIVE | OCR 状态 |
| POST /agent/ocr/warmup | :1686 | agent_control | always | ACTIVE | OCR 预热 |
| POST /agent/wechat/test | :1690 | agent_control | always | ACTIVE | 微信测试 |
| POST /agent/wechat/foreground-debug | :1694 | agent_control | always | ACTIVE | 前台调试 |
| POST /agent/wechat/search-debug | :1698 | agent_control | always | ACTIVE | 搜索调试 |
| POST /agent/wechat/search-calibration/start | :1713 | agent_control | always | ACTIVE | 搜索校准 |
| POST /agent/wechat/search-result-debug | :1717 | agent_control | always | ACTIVE | 搜索结果调试 |
| POST /agent/wechat/mouse-debug | :1732 | agent_control | always | ACTIVE | 鼠标调试 |
| GET /agent/wechat/windows | :1849 | agent_control | always | ACTIVE | 窗口列表 |
| POST /agent/wechat/file-message-probe | :2570 | agent_control | always | ACTIVE | 文件消息探测 |
| POST /agent/replies/detect | :2663 | result_report | always | ACTIVE | 回复检测结果回报 |
| GET /agent/tasks/server-url | :1863 | task_poll | always | ACTIVE | 主系统地址 |
| POST /agent/tasks/poll-and-execute | :1871 | task_poll | always | ACTIVE | 主动轮询执行 |
| POST /agent/tasks/poll-and-detect | :2246 | task_poll | always | ACTIVE | 轮询检测 |
| POST /agent/tasks/poll-and-send-report | :2482 | task_poll | always | ACTIVE | 轮询发报表 |

---

## 环境变量控制的隐藏入口（静态 grep 盲区汇总）

| Env 开关 | 位置 | 默认 | runtime_state | lifecycle | 模块 | 控制的入口 | 备注 |
|---|---|---|---|---|---|---|---|
| LEADS_WEBHOOK_INTERNAL_ENABLED | config.py:316 | false | disabled_by_default | UNKNOWN | M02 | webhook internal 模式 | |
| AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT | config.py:349 | 0 | disabled_by_default | LEGACY | M04 | wechat_auto_detect_scheduler | |
| AI_AUTO_REPLY_OUTBOX_ENABLED | config.py:303 | false | disabled_by_default | ACTIVE | M01 | outbox 调度器 + webhook _wake | |
| CONTACT_INVALID_FOLLOWUP_ENABLED | main.py:236 | false | disabled_by_default | ACTIVE | M01/M02 | 空号追问调度器 | **CONFIG_BYPASS / CONFIG_DRIFT**：直接读 os.environ 未进 config.py，单独治理 |
| LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED | config.py:329 | false | disabled_by_default | LEGACY | M04 | replies.py 调试端点 | |
| DAILY_REPORT_SCHEDULER_ENABLED | config.py:377 | false | disabled_by_default | ACTIVE | PLATFORM | 日报调度器 | |
| RETURN_VISIT_SILENT_SCAN_ENABLED | config.py:381 | false | disabled_by_default | ACTIVE | M01/M02 | 回访沉默扫描 | |
| KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED | config.py:176 | false | disabled_by_default | ACTIVE | M05 | 启动时异步 PG 初始化 | |
| DOUYIN_DECODE_MASKED_ENABLED | config.py:236 | true | conditional | ACTIVE | M01 | webhook 掩码解码 | |
| DOUYIN_WEBHOOK_AUTH_REQUIRED | config.py:244 | false（生产强制 true） | conditional | ACTIVE | PLATFORM | webhook 验签 | |
| DOUYIN_AUTO_REPLY_ENABLED | config.py:295 | false | disabled_by_default | ACTIVE | M01 | 自动回复总开关 | |
| DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED | config.py:296 | false | disabled_by_default | ACTIVE | M01 | 真实发送开关 | |
| LOCAL_AGENT_AUTH_REQUIRED | config.py:324 | false | conditional | ACTIVE | M04 | Local Agent 鉴权 | |
| NEWCAR_AUTH_ENABLED | config.py:260 | false | conditional | ACTIVE | PLATFORM | NewCar 鉴权 | |
| DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED | config.py:412 | false | disabled_by_default | ACTIVE | M04 | 日报附件投递 | |
