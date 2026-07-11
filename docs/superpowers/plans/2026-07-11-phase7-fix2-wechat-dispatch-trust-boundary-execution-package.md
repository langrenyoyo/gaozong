# Phase 7-FIX2 微信派单信任边界与事务闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 封闭所有绕过微信真实派单 gate 的入口，按 Local Agent token 隔离商户任务，并修复跨商户分配、派单原子事务、PostgreSQL 限频时间和销售反馈异常日志，使 Phase 7 达到可进入 Phase 8 的安全前置条件。

**Architecture:** 继续复用现有 `WechatTask`、`LeadNotification`、`evaluate_lead_wechat_notify_eligibility()` 和 Local Agent token 映射，不新增表、迁移、权限码或依赖。业务任务只能由内部 service 创建，HTTP `POST /wechat-tasks` 全面停用；业务 `single_send` 只能由 `/lead-notifications/send-to-staff` 在同一数据库事务中创建，前端诊断统一复用现有本机 `/agent/wechat/test`；Local Agent 的敏感机器接口强制 token 并按 token 对应商户过滤。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、Python 标准库 `datetime/re`、pytest、React + TypeScript + Vite、PowerShell、现有 SQLite 临时测试库与 PostgreSQL `SMOKE_DATABASE_URL` 安全冒烟机制。

---

## 审批窗口结论

Phase 7-FIX1 审批结论为“不通过”。专项测试虽通过且关联回归零新增失败，但多角色评审确认真实派单仍有未鉴权创建、旧 Windows 直发、跨商户任务、跨商户销售、非原子审计、PostgreSQL 时区和敏感异常日志等阻塞项。

当前窗口只制定执行包，不修改业务代码、不提交、不启动服务、不触发真实微信或生产数据库。执行继续使用 **Subagent-Driven**：每个实现任务由独立 Implementer 完成，再依次经过 Spec Reviewer 和 Code Quality Reviewer。

## 阶段起点

FIX2 必须基于包含以下提交的 HEAD：

```text
d747125 修复：补齐微信派单限频和分配开关
2330717 修复：收紧销售反馈上下文和日期校验
6bc3619 修复：隔离销售反馈解析事务
d670985 修复：补齐 existing_task 幂等查询遗漏 sent 状态
```

当前计划制定时 HEAD 为 `d670985`。执行窗口若发现 HEAD 已前进，只要 `d670985` 仍在祖先链中即可继续，但必须记录新增提交，不能用 `HEAD~N` 猜测阶段范围。

## 根因与裁定

本执行包处理 7 组已确认根因：

1. `POST /wechat-tasks` 无用户鉴权，可创建任意 `single_send` 任务。
2. 旧 `/lead-notifications/send-pending-assigned` 与同步 `auto_notify=true` 仍能让 9000 直接操作微信，绕过统一资格 gate。
3. Local Agent pending、定向任务读取、结果回写和销售回复回写未按 token 商户隔离；当前 Local Agent 客户端也未携带 token。
4. `assign_lead()` 未校验销售与线索同商户。
5. 主派单任务先 commit，通知审计记录后 commit，可能出现真实任务可执行但无审计记录。
6. 限频代码用 naive `datetime.now()` 与 PostgreSQL `TIMESTAMPTZ` 相减，命中时可能 500。
7. 销售反馈 API 的 parser/upsert 位于异常保护之外，回复解析测试未制造数据库异常，日志仍可能输出 SQL 参数、`parse_error` 或客户原文。

以下评审项不升级为 FIX2 P0：

- 不要求本阶段解决三张反馈表所有并发 upsert；保留现有唯一约束与低频顺序语义。
- 不建设 Local Agent 设备证书、自动注册、密钥轮换或设备管理中心。
- 不要求历史派单任务必须 `sent`；已确认业务口径仍是“存在历史 `notify_sales` 任务”。
- 前端限频倒计时属于体验优化，不作为安全验收阻塞。

## 阶段验收口径

### 1. 真实派单唯一入口

1. `/lead-notifications/send-to-staff` 是唯一允许创建业务 `notify_sales + single_send` 的 HTTP 入口。
2. `POST /wechat-tasks` 必须稳定返回 `410 DIRECT_WECHAT_TASK_CREATE_DISABLED`，任何 payload 均不得写任务；内部测试和业务代码直接调用 service。
3. 前端微信诊断统一调用浏览器所在电脑的 `/agent/wechat/test`，不再通过 9000 队列创建孤立或诊断任务。
4. 即使恶意 Local Agent 对内部 `paste_only` 任务回写 `sent=true`，9000 也必须 `blocked`，不得写 `sent_at` 或发送成功状态。
5. 旧 Windows router 的重复 `send-to-staff` 路由必须删除注册，只保留 `lead_notification_actions` 的主入口；`send-pending-assigned` 返回稳定 `410 LEGACY_WECHAT_SEND_DISABLED`，不得调用 UI 自动化。
6. `/integrations/douyin/sync-leads` 收到 `auto_notify=true` 必须返回稳定 400；service 层也不得再调用 `auto_notify_assigned_lead()`。
7. 保留 `notification_service.py` 作为历史实现只读参考，不重构、不删除微信 UI 底层；应用业务调用方必须为零。

### 2. Local Agent 机器信任边界

1. 新增 Local Agent 客户端变量 `LOCAL_AGENT_TOKEN`；只存在于 Local Agent 运行环境，禁止进入任何 `VITE_*`。
2. `app/local_agent_main.py` 的所有到 9000 HTTP 请求在 token 非空时统一携带 `X-Local-Agent-Token`，不改变现有 helper 调用签名。
3. Local Agent 配置了 `server_url` 却缺少 `LOCAL_AGENT_TOKEN` 时必须 fail-fast，不进入后台轮询。
4. `GET /wechat-tasks/pending`、机器定向任务读取、`POST /wechat-tasks/{id}/result`、`POST /replies/agent-write-back` 必须无条件使用 `require_local_agent_context()`；不能再受 `LOCAL_AGENT_AUTH_REQUIRED=false` 的 legacy 放行影响。
5. 新增机器定向读取路径 `GET /wechat-tasks/agent/{task_id}`；浏览器详情继续使用现有 `GET /wechat-tasks/{task_id}`，两类身份不得混用。
6. pending 只返回 lead 和 staff 均属于 token 商户的任务，不返回其他商户、跨商户关联或孤立任务。
7. 结果回写、机器定向读取和 `agent-write-back` 越权时统一返回 404，不泄露任务、线索或销售是否存在。
8. heartbeat 可继续兼容旧模式，但新 Local Agent 客户端会自动携带 token。

### 3. 分配与派单一致性

1. `assign_lead()` 必须拒绝商户为空或 `staff.merchant_id != lead.merchant_id`，错误不得包含其他商户销售姓名。
2. `task_belongs_to_merchant()` 必须要求所有已关联实体均属于同一商户，不能继续使用 lead 或 staff 任一匹配即放行。
3. `LeadNotification.send_status in {sent, replied}` 都必须视为 `ALREADY_SENT`。
4. 同线索存在 `WechatTask.status=sent` 时必须返回 `ALREADY_SENT`，不得返回 `EXISTING_PENDING_TASK`，也不得补建 `pending` 通知。

### 4. 派单原子事务与 PostgreSQL

1. 销售行锁、限频检查、违禁词替换日志、`WechatTask` 和 `LeadNotification` 必须位于同一事务。
2. `create_wechat_task()` 保留默认自提交行为供既有内部调用使用，但主派单入口使用 `commit=False`，只 `flush()` 获取 ID。
3. `_create_notification()` 同样支持 `commit=False`；主派单入口最后只 commit 一次，再 refresh 两条记录。
4. 通知记录创建或最终 commit 失败时必须 rollback；新 session 查不到任务、通知和本次违禁词命中日志。
5. Local Agent 在审计记录提交前看不到 pending 任务。
6. 限频查询先取同商户同销售最新有效任务，再根据 `recent.created_at.tzinfo` 生成同类型当前时间；不得混算 aware/naive，也不得依赖 SQLite 专属 SQL。
7. 单元测试必须覆盖 aware 与 naive 时间；非生产 PostgreSQL 必须完成两个并发事务的行锁/限频冒烟。

### 5. 销售反馈异常与日志

1. API 的 `try` 必须覆盖 `parse_and_persist_sales_feedback()`、状态判断与 commit。
2. API 只捕获 `SQLAlchemyError` 做 rollback，返回 `500 SALES_FEEDBACK_PERSIST_FAILED`；日志只记录异常类型。
3. 回复检测先提交核心 replied 状态；反馈事务 success commit，failed/skipped rollback，异常 rollback。
4. 回复解析异常日志只允许 `task_id/kind/status/error_type`，禁止 `logger.exception`、异常正文、SQL 参数、`raw_text`、`parse_error`。
5. 测试必须在反馈事务 `flush()` 出现半成品后抛 `SQLAlchemyError`，证明核心 replied 已提交、反馈半成品回滚、同一 session 可继续查询。
6. 日期先匹配 `\d{4}-\d{2}-\d{2}`，再 `datetime.strptime()` 校验真实日历日期；`2026-7-1` 必须 failed。

## 允许修改范围

后端与 Local Agent：

- Modify: `app/routers/wechat_tasks.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/lead_notifications.py`
- Modify: `app/routers/integrations.py`
- Modify: `app/services/douyin_sync_service.py`
- Modify: `app/schemas.py`
- Modify: `app/routers/replies.py`
- Modify: `app/local_agent_main.py`
- Modify: `app/services/assign_service.py`
- Modify: `app/services/lead_wechat_notify_eligibility_service.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/routers/sales_feedback.py`
- Modify: `app/services/sales_feedback_parser.py`

客户端配置与文档：

- Modify: `.env.development.example`
- Modify: `.env.lan.example`
- Modify: `scripts/build_local_agent_exe.ps1`
- Modify: `docs/config/ENV_VARIABLE_REFERENCE.md`
- Create: `scripts/smoke_phase7_fix2_postgres_dispatch_gate.py`

前端兼容：

- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Modify: `frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx`

测试允许文件：

- Create: `tests/test_phase7_fix2_dispatch_trust_boundary.py`
- Create: `tests/test_phase7_fix2_postgres_dispatch_smoke.py`
- Modify: `tests/test_p0_5a_wechat_tasks.py`
- Modify: `tests/test_p0_5a_task_creation_flow.py`
- Modify: `tests/test_p1_auto_1.py`
- Modify: `tests/test_p8_3_auto_notify.py`
- Modify: `tests/test_lead_notifications.py`
- Modify: `tests/test_legacy_wechat_debug_lockdown.py`
- Modify: `tests/test_local_agent_auth.py`
- Modify: `tests/test_wechat_task_history_api.py`
- Modify: `tests/test_p0_main_5b_poll_and_execute.py`
- Modify: `tests/test_p0_reply_2_agent_write_back.py`
- Modify: `tests/test_local_agent_heartbeat.py`
- Modify: `tests/test_p0_4a_exe_crash_fix.py`
- Modify: `tests/test_env_profile_templates.py`
- Modify: `tests/test_staff_merchant_crud.py`
- Modify: `tests/test_lead_wechat_notify_eligibility_service.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_sales_feedback_api.py`
- Modify: `tests/test_sales_feedback_parser.py`

只读参考：

- Read-only: `app/models.py`
- Read-only: `app/database.py`
- Read-only: `app/auth/local_agent_auth.py`
- Read-only: `app/services/notification_service.py`
- Read-only: `app/wechat_ui/input_writer.py`
- Read-only: `app/wechat_ui/contact_searcher.py`
- Read-only: `migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py`
- Read-only: `docs/ai/10_local_agent_wechat/P1_LOCAL_AGENT_INTERNAL_AUTH_DESIGN.md`

## 禁止事项

1. 不修改 `app/models.py`，不新增或修改数据库迁移、字段、索引或表。
2. 不新增权限码或 Python/前端依赖。
3. 除 `LOCAL_AGENT_TOKEN` 外不新增环境变量；不得修改用户的 `.env`、`.env.lan.local` 或任何 `*.local`。
4. 不把 token 写入前端、日志、响应、commit message、截图或测试输出。
5. 不修改 `app/wechat_ui/input_writer.py`、`contact_searcher.py`、联系人 OCR、前台焦点和实际按键逻辑。
6. 不启动 9000、9100、19000、前端 dev server，不构建真实 exe，不操作真实微信。
7. 不连接生产 PostgreSQL；PG 冒烟只允许显式 `SMOKE_DATABASE_URL` 指向 `localhost`、`127.0.0.1`、`postgres` 或 `auto-wechat-postgres-dev`，且 database 名必须以 `_staging` 或 `_test` 结尾。
8. 不实现 Phase 8 日报、Excel、LLM 摘要或发送调度。
9. 不处理销售反馈并发 upsert、设备证书和密钥轮换。
10. 不清理、不提交、不回滚执行窗口开始前已有用户修改或计划文档。
11. 不 rebase、squash 或改写已审批提交 `d747125/2330717/6bc3619/d670985`。

## 停止门禁

遇到以下任一情况必须停止回传：

1. `d670985` 不在当前 HEAD 祖先链中。
2. 关闭派单旁路必须修改微信 UI 自动化底层。
3. Local Agent 商户隔离必须新增 `WechatTask.merchant_id` 或数据库迁移。
4. 需要在浏览器或 `VITE_*` 中保存 Local Agent token。
5. 任务与通知原子提交无法在现有 SQLAlchemy Session 中完成。
6. 测试必须触发真实微信、真实抖音、生产数据库或生产 Local Agent 才能验证。
7. 非生产 PostgreSQL 冒烟目标无法证明是安全测试/staging 库。
8. 修改后真实发送可绕过违禁词、联系人验证、前台焦点、人工接管、限频、幂等、失败回写或紧急停止任一 gate。

## 最小设计

### HTTP 入口矩阵

| 入口 | 身份 | 允许行为 |
|---|---|---|
| `POST /lead-notifications/send-to-staff` | NewCar 用户，`leads + agent` | 唯一业务 `single_send` 创建入口 |
| `POST /wechat-tasks` | 任意 | `410 DIRECT_WECHAT_TASK_CREATE_DISABLED`，不创建任务 |
| `GET /wechat-tasks` / `GET /wechat-tasks/{id}` | NewCar 用户，`agent` | 商户任务历史/详情 |
| `GET /wechat-tasks/pending` | Local Agent token | 仅 token 商户 pending |
| `GET /wechat-tasks/agent/{id}` | Local Agent token | 仅 token 商户单任务 |
| `POST /wechat-tasks/{id}/result` | Local Agent token | 仅 token 商户任务回写 |
| `POST /replies/agent-write-back` | Local Agent token | 仅 token 商户 lead/staff/task 回写 |
| 旧 Windows 自动发送入口 | 任意 | `410 LEGACY_WECHAT_SEND_DISABLED` |

### Local Agent token

9000 继续读取现有：

```text
LOCAL_AGENT_TOKENS=merchant_id:token,merchant_id2:token2
```

19000 新增客户端单值：

```text
LOCAL_AGENT_TOKEN=local-agent-dev-token
```

客户端 HTTP helper 自动添加：

```python
headers["X-Local-Agent-Token"] = token
```

不得把整个 `LOCAL_AGENT_TOKENS` 映射复制到客户电脑。

### 商户归属

任务归属判断固定为“所有已关联实体都必须匹配”：

```text
task.lead_id 存在 -> lead 必须存在且 lead.merchant_id == merchant_id
task.staff_id 存在 -> staff 必须存在且 staff.merchant_id == merchant_id
lead_id 和 staff_id 都为空 -> 机器接口拒绝
任一关联不匹配 -> 404
```

### PostgreSQL 时间

限频不再把 naive cutoff 绑定到 `TIMESTAMPTZ`。先查询最新有效任务，再计算：

```python
created_at = recent.created_at
now = datetime.now(tz=created_at.tzinfo) if created_at.tzinfo else datetime.now()
elapsed = (now - created_at).total_seconds()
```

`elapsed >= 10` 返回无限频；否则向上取整并钳制 `1..10`。

---

## Task 0: 阶段起点与边界确认

**Files:**
- Read-only: Git metadata

- [ ] **Step 1: 记录阶段起点**

```powershell
git rev-parse HEAD
git log -1 --oneline
git merge-base --is-ancestor d670985 HEAD
```

Expected: 祖先检查退出码为 0；回传记录完整 hash。

- [ ] **Step 2: 记录已有残留**

```powershell
git status --short --branch
```

Expected: 记录但不处理已有计划文档和用户文件。每个任务提交前都用精确文件清单排除用户残留。

- [ ] **Step 3: 执行顺序**

```text
Task 1 红灯 -> Task 2 实现/双评审/提交
Task 3 红灯 -> Task 4 实现/双评审/提交
Task 5 红灯 -> Task 6 实现/双评审/提交
Task 7 红灯与实现/双评审/提交
Task 8 PG 冒烟、全回归、最终双评审、回传
```

---

## Task 1: 派单入口封闭红灯测试

**Files:**
- Create: `tests/test_phase7_fix2_dispatch_trust_boundary.py`
- Modify: `tests/test_p0_5a_wechat_tasks.py`
- Modify: `tests/test_p0_5a_task_creation_flow.py`
- Modify: `tests/test_p1_auto_1.py`
- Modify: `tests/test_p8_3_auto_notify.py`
- Modify: `tests/test_lead_notifications.py`
- Modify: `tests/test_legacy_wechat_debug_lockdown.py`

- [ ] **Step 1: 固化通用任务创建契约**

新增测试：

- `test_direct_wechat_task_create_is_disabled_for_single_send`
- `test_direct_wechat_task_create_is_disabled_for_paste_only`
- `test_direct_wechat_task_create_is_disabled_for_detect_reply`
- `test_direct_wechat_task_create_never_writes_row`
- `test_paste_only_task_cannot_be_marked_sent_by_result_payload`

所有拒绝场景必须用新 session 断言 `WechatTask.count()` 未增加。

- [ ] **Step 2: 固化旧发送入口停止**

新增测试断言应用路由表中 `POST /lead-notifications/send-to-staff` 恰好一个，endpoint 来自 `lead_notification_actions`。调用唯一旧批量路径时断言：

```text
HTTP 410
detail.code == LEGACY_WECHAT_SEND_DISABLED
open_chat_by_nickname / verify_current_chat_contact / write_text_to_input 调用次数均为 0
```

`tests/test_lead_notifications.py` 中依赖旧 UI 直发成功的测试改为旧入口停用合同，不再保留与新主路由冲突的旧 200/sent 断言。

- [ ] **Step 3: 固化同步 auto_notify 停用**

新增：

- `test_sync_leads_rejects_legacy_auto_notify_true`
- `test_preview_sync_leads_never_calls_auto_notify_assigned_lead`
- `test_auto_create_wechat_task_stays_disabled`

断言无 UI 自动化 mock 被调用、无 `WechatTask(single_send)` 被创建。

- [ ] **Step 4: 运行红灯**

```powershell
python -m pytest tests/test_phase7_fix2_dispatch_trust_boundary.py tests/test_p0_5a_wechat_tasks.py tests/test_p0_5a_task_creation_flow.py tests/test_p1_auto_1.py tests/test_p8_3_auto_notify.py tests/test_lead_notifications.py tests/test_legacy_wechat_debug_lockdown.py -v
```

Expected: 通用创建入口 410、mode 伪造阻断、旧入口 410 和 sync auto_notify 拒绝测试失败；既有 Local Agent 状态机测试不应因红灯准备被删除。

---

## Task 2: 实现真实派单唯一入口

**Files:**
- Modify: `app/routers/wechat_tasks.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/lead_notifications.py`
- Modify: `app/routers/integrations.py`
- Modify: `app/services/douyin_sync_service.py`
- Modify: `app/schemas.py`
- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Modify: `frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx`
- Modify: Task 1 测试文件

- [ ] **Step 1: 停用 POST /wechat-tasks**

保留路由用于兼容旧客户端，但函数不再调用 service，直接返回：

```python
raise HTTPException(
    status_code=410,
    detail={
        "code": "DIRECT_WECHAT_TASK_CREATE_DISABLED",
        "message": "任务由业务流程内部创建，请使用对应业务入口",
    },
)
```

状态机测试需要任务时改为调用 `wechat_task_service.create_wechat_task()` 或直接 seed ORM，不为测试保留 HTTP 后门。

- [ ] **Step 2: 服务层阻止 paste_only 伪造 sent**

在 notify_sales 的 `sent and verified` 分支前增加：

```python
if sent and task.mode != "single_send":
    task.status = "blocked"
    task.failure_stage = "task_mode_send_mismatch"
```

按现有 blocked 回写模式更新关联通知；不得设置 `sent_at`。

- [ ] **Step 3: 删除旧业务调用**

`lead_notifications.py` 删除旧 `send-to-staff` decorator 和函数，避免重复路由；`send-pending-assigned` 函数体替换为稳定 410，删除其 UI 自动化调用。保留其余受开关保护的诊断端点。

`integrations.py` 在调用 service 前拒绝 `request.auto_notify=True`。`douyin_sync_service.py` 删除 `auto_notify_assigned_lead` 延迟导入、`_try_auto_notify()`、未使用的 `_try_create_wechat_task()` 及循环中的旧调用分支；`auto_create_wechat_task` 兼容字段继续返回 disabled 统计，不创建任务。

`schemas.py` 只同步兼容字段说明：`WechatTaskCreateRequest` 标记 HTTP 创建已停用；`DouyinSyncRequest.auto_notify/auto_create_wechat_task` 标记 legacy disabled，不删除字段以避免旧客户端反序列化破坏。

Run:

```powershell
rg -n "auto_notify_assigned_lead\(|batch_notify_pending_assigned\(|_try_create_wechat_task\(" app --glob "*.py" | Where-Object { $_ -notmatch "app[\\/]services[\\/]notification_service.py:" }
```

Expected: 无输出；历史 `notification_service.py` 内部定义和自调用允许保留，但应用其它模块不得调用。

- [ ] **Step 4: 前端改用安全诊断路径**

`WechatAgent.tsx` 和 `WechatTaskPanel.tsx` 的 `createWechatTask + pollAndExecuteWechatTask` 诊断流程都改为复用现有 `startLocalWechatTest()`，不再通过 9000 创建任何测试任务。任务面板继续保留历史列表和详情，不保留创建按钮对应的旧 API 调用。

- [ ] **Step 5: 运行绿灯与构建**

```powershell
python -m pytest tests/test_phase7_fix2_dispatch_trust_boundary.py tests/test_p0_5a_wechat_tasks.py tests/test_p0_5a_task_creation_flow.py tests/test_p1_auto_1.py tests/test_p8_3_auto_notify.py tests/test_lead_notifications.py tests/test_legacy_wechat_debug_lockdown.py -v
Push-Location frontend
npm run build
$buildExit = $LASTEXITCODE
Pop-Location
exit $buildExit
```

Expected: 全部通过；前端无 TypeScript 错误。

- [ ] **Step 6: 双评审与提交**

Spec Reviewer 检查所有任务 HTTP 创建入口，Code Quality Reviewer 检查没有 test-only 后门或前端 token。

```powershell
git add app/routers/wechat_tasks.py app/services/wechat_task_service.py app/routers/lead_notifications.py app/routers/integrations.py app/services/douyin_sync_service.py app/schemas.py frontend/src/features/wechat-assistant/pages/WechatAgent.tsx frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx tests/test_phase7_fix2_dispatch_trust_boundary.py tests/test_p0_5a_wechat_tasks.py tests/test_p0_5a_task_creation_flow.py tests/test_p1_auto_1.py tests/test_p8_3_auto_notify.py tests/test_lead_notifications.py tests/test_legacy_wechat_debug_lockdown.py
git commit -m "修复：封闭微信真实派单旁路"
git rev-parse HEAD
```

---

## Task 3: Local Agent token 与商户隔离红灯测试

**Files:**
- Modify: `tests/test_local_agent_auth.py`
- Modify: `tests/test_wechat_task_history_api.py`
- Modify: `tests/test_p0_main_5b_poll_and_execute.py`
- Modify: `tests/test_p0_reply_2_agent_write_back.py`
- Modify: `tests/test_local_agent_heartbeat.py`
- Modify: `tests/test_p0_4a_exe_crash_fix.py`
- Modify: `tests/test_env_profile_templates.py`

- [ ] **Step 1: 敏感机器接口强制 token**

即使 `LOCAL_AGENT_AUTH_REQUIRED=false`，以下无 token 请求也必须 401：

```text
GET /wechat-tasks/pending
GET /wechat-tasks/agent/{task_id}
POST /wechat-tasks/{task_id}/result
POST /replies/agent-write-back
```

heartbeat 无 token兼容测试继续保留。

- [ ] **Step 2: 商户隔离测试**

构造 merchant-a、merchant-b 和跨商户关联任务，新增：

- `test_agent_pending_only_returns_tasks_wholly_owned_by_token_merchant`
- `test_agent_pending_excludes_orphan_and_cross_linked_tasks`
- `test_agent_detail_returns_404_for_other_merchant_token`
- `test_agent_result_returns_404_and_keeps_state_for_other_merchant_token`
- `test_agent_write_back_returns_404_for_cross_merchant_lead_staff_or_task`
- `test_agent_matching_merchant_can_read_and_write_back`

越权响应不得包含目标商户、销售姓名、昵称或消息。

- [ ] **Step 3: Local Agent 客户端 header 测试**

对 `_http_get()`、`_http_post_json()` 和 heartbeat mock 断言：

```text
LOCAL_AGENT_TOKEN 非空 -> X-Local-Agent-Token header 存在且值正确
LOCAL_AGENT_TOKEN 空 -> create_local_agent_app(server_url="http://127.0.0.1:9000") fail-fast
错误日志和返回结构不包含 token
```

定向任务 URL 必须改为 `/wechat-tasks/agent/{task_id}`。

- [ ] **Step 4: 构建脚本和模板红灯**

测试要求：

```text
build_local_agent_exe.ps1 从进程环境读取 LOCAL_AGENT_TOKEN，空值 fail-fast
写入 dist .env 的键为 LOCAL_AGENT_TOKEN
脚本参数、Write-Host 和错误文本都不包含 token 值
.env.development.example / .env.lan.example 含 LOCAL_AGENT_TOKEN
.env.production.example 不新增客户端 token
ENV_VARIABLE_REFERENCE 标明该变量只属于 19000
```

- [ ] **Step 5: 运行红灯**

```powershell
python -m pytest tests/test_local_agent_auth.py tests/test_wechat_task_history_api.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p0_reply_2_agent_write_back.py tests/test_local_agent_heartbeat.py tests/test_p0_4a_exe_crash_fix.py tests/test_env_profile_templates.py -v
```

Expected: 强制 token、商户过滤、client header 和构建变量测试失败。

---

## Task 4: 实现 Local Agent 商户任务隔离

**Files:**
- Modify: `app/routers/wechat_tasks.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/replies.py`
- Modify: `app/local_agent_main.py`
- Modify: `.env.development.example`
- Modify: `.env.lan.example`
- Modify: `scripts/build_local_agent_exe.ps1`
- Modify: `docs/config/ENV_VARIABLE_REFERENCE.md`
- Modify: Task 3 测试文件

- [ ] **Step 1: 强制机器鉴权并保留浏览器路由**

pending/result 改用 `require_local_agent_context(request)` 并保存返回 context。新增且放在 `/{task_id}` 前：

```python
@router.get("/agent/{task_id}", response_model=WechatTaskResponse)
def get_agent_wechat_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    agent = require_local_agent_context(request)
```

浏览器详情 `GET /wechat-tasks/{task_id}` 继续使用 NewCar context。

- [ ] **Step 2: 收紧任务归属 helper**

`task_belongs_to_merchant()` 改为所有非空关联均匹配。`get_pending_wechat_tasks()` 新增必填 `merchant_id`，通过 `DouyinLead/SalesStaff` 关联过滤，只返回 lead、staff 都属于该商户的 pending。

结果回写和机器详情取到 task 后调用同一 helper；失败统一 404。

- [ ] **Step 3: 收紧 agent-write-back**

`replies.py` 使用 `require_local_agent_context()`。在调用 service 前查询并验证：

```text
lead.merchant_id == agent.merchant_id
staff.merchant_id == agent.merchant_id
若 task_id 存在：task 属于 agent.merchant_id，且 task.lead_id/staff_id 与 payload 一致
```

任一失败返回通用 404。

- [ ] **Step 4: Local Agent 统一添加 header**

在 `local_agent_main.py` 增加读取 `LOCAL_AGENT_TOKEN` 的私有 helper；`_http_get/_http_post_json` 内部自动附加 header，保持函数签名不变。所有错误信息不得包含 token。

所有定向 GET 改用 `/wechat-tasks/agent/{task_id}`。配置 `server_url` 时 token 为空必须在轮询/心跳线程启动前抛出明确配置错误。

- [ ] **Step 5: 配置与打包**

dev/lan 模板 Local Agent 段增加：

```text
LOCAL_AGENT_TOKEN=local-agent-dev-token
```

构建脚本保持现有参数签名，只从 `$env:LOCAL_AGENT_TOKEN` 读取 secret；校验非空和无换行，只写入生成的 `.env`，不输出值。`docs/config/ENV_VARIABLE_REFERENCE.md` 标记该值为 19000 secret；不进入前端和生产服务器模板。

- [ ] **Step 6: 运行绿灯**

```powershell
python -m pytest tests/test_local_agent_auth.py tests/test_wechat_task_history_api.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p0_reply_2_agent_write_back.py tests/test_local_agent_heartbeat.py tests/test_p0_4a_exe_crash_fix.py tests/test_env_profile_templates.py -v
```

Expected: 全部通过。

- [ ] **Step 7: 静态 secret 检查**

```powershell
rg -n "LOCAL_AGENT_TOKEN=" frontend .env.production.example
rg -n "LocalAgentToken|Write-Host.*LOCAL_AGENT_TOKEN|Write-Output.*LOCAL_AGENT_TOKEN|logger\..*LOCAL_AGENT_TOKEN" scripts app
```

Expected: 两条均无敏感值使用；第一条允许前端错误码字符串，但不允许环境变量读取或 token 值。

- [ ] **Step 8: 双评审与提交**

```powershell
git add app/routers/wechat_tasks.py app/services/wechat_task_service.py app/routers/replies.py app/local_agent_main.py .env.development.example .env.lan.example scripts/build_local_agent_exe.ps1 docs/config/ENV_VARIABLE_REFERENCE.md tests/test_local_agent_auth.py tests/test_wechat_task_history_api.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p0_reply_2_agent_write_back.py tests/test_local_agent_heartbeat.py tests/test_p0_4a_exe_crash_fix.py tests/test_env_profile_templates.py
git commit -m "修复：隔离 Local Agent 商户任务"
git rev-parse HEAD
```

---

## Task 5: 分配、幂等、原子事务与时区红灯测试

**Files:**
- Modify: `tests/test_staff_merchant_crud.py`
- Modify: `tests/test_lead_wechat_notify_eligibility_service.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Create: `tests/test_phase7_fix2_postgres_dispatch_smoke.py`

- [ ] **Step 1: 跨商户分配红灯**

新增：

- `test_manual_assign_rejects_staff_from_other_merchant_without_name_leak`
- `test_assign_service_rejects_missing_merchant`

断言线索分配字段、ReplyCheck 和跟进记录均未改变。

- [ ] **Step 2: sent/replied 永久幂等红灯**

新增：

- `test_replied_notification_is_already_sent`
- `test_sent_task_without_notification_is_already_sent`
- `test_sent_task_idempotency_never_creates_pending_notification`

断言 reason/status 为 `ALREADY_SENT/task_done`，不是 `EXISTING_PENDING_TASK/task_pending`。

- [ ] **Step 3: 原子事务红灯**

在主派单请求中 monkeypatch `_create_notification()`：任务已 `flush()` 后抛 `SQLAlchemyError`。断言：

```text
响应为受控 500 DISPATCH_PERSIST_FAILED
新 session 中 WechatTask 为 0
LeadNotification 为 0
本请求 ForbiddenWordHitLog 为 0
session rollback 后仍可查询
```

成功场景通过 commit 计数器断言任务与通知共用一次最终 commit。

- [ ] **Step 4: aware/naive 时间红灯**

新增纯单元测试，分别传：

```text
datetime.now() - 5 秒
datetime.now(timezone.utc) - 5 秒
datetime.now(timezone(timedelta(hours=8))) - 11 秒
```

前两者返回 `1..10`，第三个返回 None；不得抛 TypeError。

- [ ] **Step 5: PG smoke 合同红灯**

`tests/test_phase7_fix2_postgres_dispatch_smoke.py` 只测试 smoke 脚本的安全门与流程编排，不连接网络：

```text
拒绝 SQLite URL
拒绝生产 database 名
拒绝非 allowlist host
URL 输出必须脱敏
两个事务按“B 等待 A -> A 插入任务并 commit -> B 返回幂等/限频”执行
finally 清理本次唯一前缀数据
```

- [ ] **Step 6: 运行红灯**

```powershell
python -m pytest tests/test_staff_merchant_crud.py tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
```

Expected: 跨商户、sent 语义、原子回滚、aware 时间和 smoke 合同新增测试失败。

---

## Task 6: 实现派单租户边界、原子事务和 PG 时区

**Files:**
- Modify: `app/services/assign_service.py`
- Modify: `app/services/lead_wechat_notify_eligibility_service.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/services/wechat_task_service.py`
- Create: `scripts/smoke_phase7_fix2_postgres_dispatch_gate.py`
- Modify: Task 5 测试文件

- [ ] **Step 1: 分配同商户校验**

`assign_lead()` 查询 lead 后先要求非空 `lead.merchant_id`，销售查询同时过滤该 merchant。不存在时统一：

```text
目标销售不存在或不属于当前商户
```

不要在错误中插入销售姓名。

- [ ] **Step 2: 收口 sent/replied 幂等**

通知查询使用 `send_status.in_(["sent", "replied"])`。任务查询对 `status="sent"` 返回 `ALREADY_SENT` 并携带 `existing_task_id`；`pending/running/pasted` 才返回 `EXISTING_PENDING_TASK`。

`_compatible_decision_response()` 对 sent task 返回 already_sent，找不到通知时允许 `notification=None`，禁止调用 `_create_notification()` 补 pending。

- [ ] **Step 3: 创建 helper 支持延迟提交**

`wechat_task_service.create_wechat_task()` 新增仅限关键字参数 `commit: bool = True`：

```text
commit=True -> 保持现有 add/commit/refresh
commit=False -> add/flush，不 commit、不 refresh
```

`lead_notification_actions._create_notification()` 新增相同的仅限关键字参数 `commit: bool = True`。

- [ ] **Step 4: 主派单一次提交**

主路由资格判断后，把违禁词替换、task `commit=False`、notification `commit=False` 和最终 commit 放在同一 try。捕获 `SQLAlchemyError`：

```python
db.rollback()
logger.error("dispatch_persist_failed error_type=%s", type(exc).__name__)
raise HTTPException(
    status_code=500,
    detail={"code": "DISPATCH_PERSIST_FAILED", "message": "微信派单任务创建失败"},
) from None
```

最终 commit 后 refresh task/notification。不得 `logger.exception` 或输出客户消息、SQL 参数。

- [ ] **Step 5: 修复时间计算**

删除 SQL cutoff 过滤，查询最新有效任务后调用小型私有时间 helper。helper 按 `created_at.tzinfo` 生成同类型 now，计算超过 10 秒返回 None。

不修改全局模型时间类型，不新增数据库方言分支。

- [ ] **Step 6: PostgreSQL smoke 脚本**

复用项目既有 smoke URL 解析/脱敏/allowlist 模式。脚本只读取显式 `SMOKE_DATABASE_URL`，要求 `postgresql+psycopg`、host 属于 `localhost/127.0.0.1/postgres/auto-wechat-postgres-dev`，database 名以 `_staging` 或 `_test` 结尾；其它情况 fail-fast。

脚本用 `phase7_fix2_` 加本次 UUID 组成唯一前缀，创建测试 merchant/staff/两条 lead；两个独立 Session 验证销售行锁和第二请求在第一事务提交任务后返回幂等或限频。线程等待和 join 都设置 10 秒上限，超时立即失败。所有测试数据在 finally 按精确 ID 依次删除 `WechatTask -> LeadNotification -> ReplyCheck -> DouyinLead -> SalesStaff`；不调用 HTTP、Local Agent 或微信。

- [ ] **Step 7: 运行绿灯**

```powershell
python -m pytest tests/test_staff_merchant_crud.py tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
```

Expected: 全部通过。

- [ ] **Step 8: 双评审与提交**

Spec Reviewer 检查跨租户、幂等、单事务和 aware 时间；Code Quality Reviewer 检查 commit 所有权、rollback、无方言分支与 smoke 清理。

```powershell
git add app/services/assign_service.py app/services/lead_wechat_notify_eligibility_service.py app/routers/lead_notification_actions.py app/services/wechat_task_service.py scripts/smoke_phase7_fix2_postgres_dispatch_gate.py tests/test_staff_merchant_crud.py tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_phase7_fix2_postgres_dispatch_smoke.py
git commit -m "修复：保证微信派单租户隔离与原子事务"
git rev-parse HEAD
```

---

## Task 7: 销售反馈异常事务与日志收口

**Files:**
- Modify: `app/routers/sales_feedback.py`
- Modify: `app/services/sales_feedback_parser.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `tests/test_sales_feedback_api.py`
- Modify: `tests/test_sales_feedback_parser.py`

- [ ] **Step 1: 写真实数据库异常红灯**

API 测试 monkeypatch parser：先 `db.add()` 一条反馈并 `db.flush()`，再抛 `SQLAlchemyError`。断言受控 500、半成品回滚、同一 session 可查询。

回复检测测试在核心 replied commit 后执行同样的“flush 后异常”，断言：

```text
WechatTask.status == completed
ReplyCheck.check_status == replied
LeadNotification.send_status == replied
SalesLeadFeedback 不存在
同一 session 可继续查询
```

用 `caplog` 断言日志不含手机号、微信号、raw_text、SQL `INSERT`、`parse_error` 或异常消息，只含异常类型。

- [ ] **Step 2: 严格日期红灯**

新增 `2026-7-1`、`2026-07-1`、`2026-7-01` 三组 failed 测试，并确认不落 `SalesDailySummary`。

- [ ] **Step 3: API 事务边界**

一个 try 覆盖 parser 调用、failed/skipped 处理和 commit。`failed/skipped` rollback；只捕获 `SQLAlchemyError`，日志仅异常类型，HTTPException 原样抛出。

- [ ] **Step 4: 回复解析事务**

`_try_parse_sales_feedback_from_reply()` 返回 parse result。外层：success commit，failed/skipped rollback，任意异常 rollback 后只记录 `task_id` 与异常类型。不得记录 `result.parse_error` 或调用 `logger.exception`。

- [ ] **Step 5: 日期宽度校验**

在 `strptime` 前增加：

```python
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", summary_date_text):
    return failed result
```

- [ ] **Step 6: 运行测试**

```powershell
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_manual_notify_sales_task.py -v
```

Expected: 全部通过。

- [ ] **Step 7: 静态日志检查**

```powershell
rg -n "logger\.exception|result\.parse_error|raw_text" app/routers/sales_feedback.py app/services/wechat_task_service.py
```

Expected: 本阶段异常路径无 `logger.exception` 和 `result.parse_error`；`raw_text` 只允许作为 parser 入参，不得进入日志格式串。

- [ ] **Step 8: 双评审与提交**

```powershell
git add app/routers/sales_feedback.py app/services/sales_feedback_parser.py app/services/wechat_task_service.py tests/test_sales_feedback_api.py tests/test_sales_feedback_parser.py tests/test_manual_notify_sales_task.py
git commit -m "修复：收口销售反馈异常事务与脱敏日志"
git rev-parse HEAD
```

---

## Task 8: PostgreSQL 冒烟、全阶段验证与回传

**Files:**
- Verify only: 全部允许文件

- [ ] **Step 1: 四组专项回归**

```powershell
python -m pytest tests/test_phase7_fix2_dispatch_trust_boundary.py tests/test_p0_5a_wechat_tasks.py tests/test_p0_5a_task_creation_flow.py tests/test_p1_auto_1.py tests/test_p8_3_auto_notify.py tests/test_lead_notifications.py tests/test_legacy_wechat_debug_lockdown.py -v
python -m pytest tests/test_local_agent_auth.py tests/test_wechat_task_history_api.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p0_reply_2_agent_write_back.py tests/test_local_agent_heartbeat.py tests/test_p0_4a_exe_crash_fix.py tests/test_env_profile_templates.py -v
python -m pytest tests/test_staff_merchant_crud.py tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_forbidden_word_send_integration.py -v
```

Expected: 全部通过，不接受新增失败标记为 pre-existing。

- [ ] **Step 2: 临时 SQLite 关联回归**

```powershell
$tempDb = Join-Path $env:TEMP "auto_wechat_phase7_fix2_$PID.db"
$tempDbUrl = $tempDb.Replace([char]92, [char]47)
$env:DATABASE_URL = "sqlite:///$tempDbUrl"
$env:NEWCAR_AUTH_ENABLED = "false"
$env:NEWCAR_AUTH_MOCK_ENABLED = "true"
$env:LOCAL_AGENT_TOKENS = "dev-merchant:local-agent-dev-token"
$env:LOCAL_AGENT_TOKEN = "local-agent-dev-token"
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_lead_notifications.py tests/test_local_agent_auth.py tests/test_wechat_task_history_api.py tests/test_forbidden_word_send_integration.py -v
$testExit = $LASTEXITCODE
if (Test-Path -LiteralPath $tempDb) { Remove-Item -LiteralPath $tempDb -Force }
exit $testExit
```

Expected: 全部通过；现有 `data/auto_wechat.db` 未读写。

- [ ] **Step 3: 前端构建**

```powershell
Push-Location frontend
npm run build
$buildExit = $LASTEXITCODE
Pop-Location
exit $buildExit
```

Expected: 构建通过，只允许既有 chunk size 提示。

- [ ] **Step 4: 必做非生产 PostgreSQL 冒烟**

执行窗口必须由审批者提供显式、已确认的非生产 URL：

```powershell
if (-not $env:SMOKE_DATABASE_URL) { throw "审批者尚未提供非生产 SMOKE_DATABASE_URL" }
python scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
```

Expected:

```text
URL 脱敏输出
schema/required rows ready
aware_datetime PASS
staff_row_lock PASS
second_request_after_commit RATE_LIMITED 或 EXISTING_PENDING_TASK
cleanup PASS
PHASE7_FIX2_POSTGRES_SMOKE_PASS
```

如果没有安全非生产 PG，阶段状态必须是 `BLOCKED`，不能用 SQLite 结果替代。

- [ ] **Step 5: 精确提交范围**

从 `d670985..HEAD` 按四个固定中文提交标题解析精确 hash，若同标题命中不为 1 次则用 Task 回传 hash 人工消歧：

```powershell
$subjects = @(
    "修复：封闭微信真实派单旁路",
    "修复：隔离 Local Agent 商户任务",
    "修复：保证微信派单租户隔离与原子事务",
    "修复：收口销售反馈异常事务与脱敏日志"
)
$history = @(git log --format="%H%x09%s" d670985..HEAD)
$phaseCommits = foreach ($subject in $subjects) {
    $matches = @($history | Where-Object { ($_ -split "`t", 2)[1] -eq $subject })
    if ($matches.Count -ne 1) { throw "提交标题 [$subject] 命中 $($matches.Count) 次" }
    ($matches[0] -split "`t", 2)[0]
}
foreach ($commit in $phaseCommits) {
    git show --name-only --format= $commit
    git diff --check "${commit}^..${commit}"
    if ($LASTEXITCODE -ne 0) { throw "提交 $commit 存在空白错误" }
}
$phaseFiles = foreach ($commit in $phaseCommits) {
    git show --name-only --format= $commit
}
$phaseFiles = $phaseFiles | Where-Object { $_ } | Sort-Object -Unique
$forbiddenFiles = @($phaseFiles | Where-Object {
    $_ -match "^(app/models.py|migrations/|app/wechat_ui/(input_writer|contact_searcher)\.py|apps/xg_douyin_ai_cs/|frontend/package|package-lock.json|requirements|pyproject.toml)"
})
if ($forbiddenFiles) { throw "Phase 7-FIX2 越界文件: $($forbiddenFiles -join ', ')" }
$phaseFiles
```

Expected: 仅允许文件，无空白错误。执行窗口期间用户插入提交单独列出，不计入 FIX2。

- [ ] **Step 6: 安全静态检查**

```powershell
rg -n "auto_notify_assigned_lead\(|batch_notify_pending_assigned\(|_try_create_wechat_task\(" app --glob "*.py" | Where-Object { $_ -notmatch "app[\\/]services[\\/]notification_service.py:" }
rg -n "get_optional_local_agent_context\(request\)" app/routers/wechat_tasks.py app/routers/replies.py
rg -n "logger\.exception|result\.parse_error" app/routers/sales_feedback.py app/services/wechat_task_service.py
rg -n "LOCAL_AGENT_TOKEN=" frontend .env.production.example
```

Expected:

- 第一条无输出；历史 service 文件已被命令排除。
- 第二条无输出，敏感接口全部使用强制鉴权。
- 第三条本阶段反馈异常路径无输出。
- 第四条不得出现客户端 secret 读取或值。

- [ ] **Step 7: 最终 Spec Reviewer**

逐项给出 Approved/Rejected 和证据：

1. 业务 single_send 只有主派单入口。
2. 通用任务 HTTP 创建入口已停用，内部 paste_only 的 mode 不能伪造 sent。
3. 旧 Windows 和 sync auto_notify 不再触发 UI 自动化。
4. Local Agent 四个敏感机器入口强制 token 并按商户隔离。
5. 客户端携带单 token，token 不进入前端和日志。
6. 跨商户手动分配被拒绝。
7. sent/replied 永久幂等语义正确。
8. 派单任务、通知、违禁词日志同一事务，失败无孤立任务。
9. aware/naive 单测和非生产 PG 双事务冒烟通过。
10. 销售反馈 parser/upsert/commit 异常受控 rollback。
11. 回复核心状态不受反馈异常影响，半成品回滚。
12. 反馈日志不含 SQL 参数、原文或 parse_error。
13. 无迁移、权限码、依赖和 Phase 8 越界。

任一 Rejected，阶段不得进入质量评审。

- [ ] **Step 8: 最终 Code Quality Reviewer**

检查：

1. 没有新任务框架或重复资格算法。
2. 商户归属 helper 使用全关联匹配，不是 OR 放行。
3. token helper 集中且不改变所有调用方签名。
4. 主派单只有一个最终 commit，rollback 覆盖 flush 半成品。
5. SQLAlchemyError 与业务 HTTPException 边界清楚。
6. PG smoke 有 allowlist、脱敏和 finally 清理。
7. 日志只记录稳定 ID、状态和异常类型。
8. 旧测试不是简单删除断言，而是改成新安全合同。
9. 前端只做必要兼容，无 token、无新状态管理和依赖。

- [ ] **Step 9: 固定格式回传**

```text
阶段：Phase 7-FIX2 微信派单信任边界与事务闭环
状态：DONE / BLOCKED

阶段起点：
- {完整阶段起点 hash，必须包含 d670985}

提交：
- {提交 hash} 修复：封闭微信真实派单旁路
- {提交 hash} 修复：隔离 Local Agent 商户任务
- {提交 hash} 修复：保证微信派单租户隔离与原子事务
- {提交 hash} 修复：收口销售反馈异常事务与脱敏日志

变更文件：
- {逐项列出实际文件}

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：LOCAL_AGENT_TOKEN（仅 19000 客户端）
服务启动 / 真实请求：无
真实微信操作：无
未触碰：models.py、migrations、微信 UI 自动化底层、9100、Phase 8/9

测试命令与结果：
- 派单入口：{实际结果}
- Local Agent 商户隔离：{实际结果}
- 原子事务/分配/限频：{实际结果}
- 销售反馈：{实际结果}
- 临时 SQLite：{实际结果}
- 前端构建：{实际结果}
- 非生产 PostgreSQL smoke：{实际结果}
- git diff --check：{实际结果}

安全验证：
- single_send 唯一入口：{实际证据}
- 旧 Windows/sync auto_notify：{实际证据}
- Local Agent token merchant 隔离：{实际证据}
- 跨商户分配：{实际证据}
- 任务/通知/违禁词日志原子提交：{实际证据}
- PG aware 时间与双事务行锁：{实际证据}
- 反馈异常 rollback 与日志脱敏：{实际证据}

自审结论：
- Spec Reviewer：Approved / Rejected
- Code Quality Reviewer：Approved / Rejected

用户既有残留：
- {列出实际残留并说明未处理}

剩余风险：
- 反馈并发 upsert 留到 PostgreSQL 数据可靠性阶段。
- 完整 Local Agent 设备证书和密钥轮换不在一期最小范围。
- {其他真实风险；无则写无}

需要审批窗口裁定：
- 是否确认 Phase 7-FIX2 通过？
- 是否把 Phase 7 更新为通过？
- 是否进入 Phase 8 执行包制定？
```

---

## 回滚方案

1. 四个提交独立 revert，禁止改写 FIX1 历史。
2. 入口封闭提交回滚会重新暴露真实发送旁路，只允许在非生产且紧急停止开启时临时回滚。
3. Local Agent token 提交回滚时，9000 与 19000 必须同时回滚，不能只回一侧造成任务停摆。
4. 原子事务提交无迁移；revert 后不会删除既有任务或通知。
5. 反馈事务提交无迁移；已成功反馈不删除。
6. PG smoke 数据只按唯一前缀和精确 ID 清理，禁止模糊 DELETE。

## 本窗口审批清单

1. 当前 HEAD 是否包含 d670985 和四个 FIX2 提交。
2. 是否封闭所有真实 single_send 创建旁路。
3. 是否彻底停止 9000 旧 Windows UI 直发业务入口。
4. Local Agent token 是否真正从 19000 发出，并按商户过滤读取/回写。
5. 是否拒绝跨商户销售分配和跨关联任务。
6. 派单任务与审计是否同一事务可见。
7. PostgreSQL aware 时间和双事务 smoke 是否真实通过。
8. 销售反馈数据库异常测试是否真的 flush 后抛错，而非仅返回 failed。
9. 敏感日志是否无 SQL 参数、原文、parse_error 和 token。
10. 专项、临时 SQLite、前端构建和 PG smoke 是否全部通过。
11. Spec Reviewer 与 Code Quality Reviewer 是否均 Approved。
12. 全部满足后：Phase 7-FIX2 通过，Phase 7 更新为通过，方可制定 Phase 8。
