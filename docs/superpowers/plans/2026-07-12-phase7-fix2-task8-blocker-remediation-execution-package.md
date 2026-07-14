# Phase 7-FIX2 Task 8 阻塞修复执行包

> **文档状态（2026-07-14 审查）：历史执行包，非当前阶段指令。** Phase 7-FIX2 Task 8 已完成并进入后续阶段，落地提交包括 `a29564d`、`02d25fb`、`13e5ff6`。下文“当前”均指计划制定时快照，未勾选项不得作为重复执行依据；当前项目事实以 `docs/ai/05_PROJECT_CONTEXT.md` 为准。
>
> **执行窗口要求：** 必须按任务顺序执行。每个实现任务由独立 Implementer 完成，再依次经过 Spec Reviewer 与 Code Quality Reviewer。当前审批窗口只制定计划，不参与编码。

**目标：** 修复 Phase 7-FIX2 Task 8 验证发现的全部阻塞，补齐微信真实派单唯一入口、Local Agent 机器鉴权闭环、跨商户隔离、原子事务、PostgreSQL 时区兼容、销售反馈脱敏日志和真实非生产 PostgreSQL 冒烟证据，使 Phase 7-FIX2 具备重新审批条件。

**原则：** 删除优先、复用优先、根因优先。不新增表、迁移、权限码、依赖或环境变量；不改微信 UI 自动化底层；不触发真实微信、抖音、生产数据库或生产 Local Agent 请求。

---

## 一、制定时阶段现状

### 1. 已完成提交

以下四个 Phase 7-FIX2 提交已经存在，执行窗口不得 rebase、amend、fixup、squash 或重写：

```text
0c8bbd8 修复：封闭微信真实派单旁路
ae59d59 修复：隔离 Local Agent 商户任务
7acedf4 修复：保证微信派单租户隔离与原子事务
a62d5cb 修复：收口销售反馈异常事务与脱敏日志
```

本执行包只允许在其后追加新提交。

### 2. 当前未提交修改

计划制定时工作区已有下列 11 个未提交文件：

```text
app/auth/local_agent_auth.py
app/routers/lead_notifications.py
app/services/wechat_task_service.py
docs/待确认事项.md
tests/test_lead_notifications.py
tests/test_p0_5a_task_creation_flow.py
tests/test_p0_5a_wechat_tasks.py
tests/test_phase7_fix2_assign_atomic_timezone.py
tests/test_phase7_fix2_dispatch_trust_boundary.py
tests/test_phase7_fix2_local_agent_auth.py
tests/test_phase7_fix2_sales_feedback.py
```

这些修改视为用户既有工作。执行窗口必须先逐文件审计归属，不得 reset、checkout、stash、覆盖或删除。若文件中的既有修改与本执行包目标一致，可以在理解后继续编辑，但提交前必须用精确 diff 说明哪些行属于本阶段。

`docs/待确认事项.md` 明确排除在本阶段提交范围外。

### 3. 已确认阻塞

1. `app/services/douyin_sync_service.py` 仍保留无调用方的 `_try_create_wechat_task()`，违反真实派单唯一入口要求。
2. `app/routers/wechat_tasks.py` 仍导入未使用的 `get_optional_local_agent_context`。
3. `app/routers/replies.py` 的 `agent-write-back` 仍使用 optional 鉴权，机器写接口未强制 token。
4. `app/local_agent_main.py` 的 `_http_get/_http_post_json` 未统一携带 `X-Local-Agent-Token`。
5. 缺少 `GET /wechat-tasks/agent/{task_id}` 机器详情接口。
6. `wechat_task_service.py` 商户过滤使用 OR，存在跨关联或孤立任务被错误放行的风险。
7. `assign_service.py` 缺少 lead 与 staff 同商户验证。
8. `lead_notification_actions.py` 创建任务与通知记录分两次提交，不满足原子性。
9. 限频路径使用 naive `datetime.now()`，与 PostgreSQL `TIMESTAMPTZ` 比较存在运行时错误风险。
10. 销售反馈异常日志仍可能通过 `logger.exception` 或 `parse_error` 泄露 SQL 参数、客户原文或异常正文。
11. 缺少 PostgreSQL 冒烟契约测试和执行脚本。
12. 部分测试在模块导入阶段修改 `os.environ`，存在顺序依赖和测试污染。

---

## 二、允许范围

### 业务实现允许文件

```text
app/services/douyin_sync_service.py
app/routers/wechat_tasks.py
app/routers/replies.py
app/local_agent_main.py
app/auth/local_agent_auth.py
app/services/wechat_task_service.py
app/services/assign_service.py
app/routers/lead_notification_actions.py
app/routers/lead_notifications.py
app/services/sales_feedback_parser.py
app/routers/sales_feedback.py
```

### 测试与脚本允许文件

```text
tests/test_p0_5a_task_creation_flow.py
tests/test_p0_5a_wechat_tasks.py
tests/test_p0_reply_2_agent_write_back.py
tests/test_phase7_fix2_dispatch_trust_boundary.py
tests/test_phase7_fix2_local_agent_auth.py
tests/test_phase7_fix2_assign_atomic_timezone.py
tests/test_phase7_fix2_sales_feedback.py
tests/test_lead_notifications.py
tests/test_phase7_fix2_postgres_dispatch_smoke.py
scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
```

若执行窗口证明某个关联测试必须调整，须先停止并向审批窗口说明文件、原因和最小修改，不得自行扩大业务文件范围。

### 只读参考

```text
app/models.py
app/database.py
app/services/notification_service.py
app/wechat_ui/input_writer.py
app/wechat_ui/contact_searcher.py
migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py
docs/ai/10_local_agent_wechat/P1_LOCAL_AGENT_INTERNAL_AUTH_DESIGN.md
```

---

## 三、禁止事项

1. 不修改 `app/models.py`、任何 migration、表、字段、索引或约束。
2. 不新增权限码、依赖、前端状态、前端 token 或环境变量。
3. 不修改用户的 `.env`、`.env.*.local`、真实 token 或连接串。
4. 不修改 `input_writer.py`、`contact_searcher.py`、OCR、前台焦点、键鼠发送或微信窗口逻辑。
5. 不启动 9000、9100、19000、前端开发服务，不构建 exe，不操作真实微信。
6. 不访问生产 PostgreSQL、生产 Local Agent、生产抖音接口或生产 NewCar。
7. 不用 SQLite 冒充 PostgreSQL 冒烟通过。
8. 不提前实现 Phase 8 日报、Excel、LLM 摘要、发送调度，或 Phase 9 以后功能。
9. 不处理销售反馈并发 upsert、设备证书、密钥轮换等非本阶段内容。
10. 不删除、清理、提交或回滚 `docs/待确认事项.md`。
11. 不以“测试看起来是 pre-existing”为由跳过根因验证。

---

## 四、停止门禁

遇到下列任一情况立即停止并回传，不得自行绕过：

1. 四个已审批 FIX2 提交不在当前 HEAD 祖先链中。
2. 需要修改微信 UI 自动化底层才能完成任务。
3. 需要新增 `WechatTask.merchant_id`、数据库迁移或模型字段。
4. 需要把 Local Agent token 写入浏览器、`VITE_*`、日志、响应或仓库真实配置。
5. 现有 SQLAlchemy Session 无法完成任务与通知记录的单事务提交。
6. 测试必须发送真实微信、访问生产接口或连接生产数据库才能通过。
7. PostgreSQL 目标无法证明为安全非生产测试库。
8. 需要改写原四个 FIX2 提交。
9. 用户既有未提交修改与本阶段目标冲突，且无法在不覆盖用户工作的前提下继续。

---

## 五、统一验收口径

### 1. 真实派单唯一入口

业务 `single_send` 任务只能由：

```text
POST /lead-notifications/send-to-staff
```

在完整 gate 后创建。同步服务、批量入口、通用任务创建接口和其他路由不得创建或发送业务 `single_send`。

### 2. Local Agent 机器接口

以下机器接口必须强制 `X-Local-Agent-Token`，并按 token 对应商户隔离：

```text
GET  /wechat-tasks/pending
GET  /wechat-tasks/agent/{task_id}
POST /wechat-tasks/{task_id}/result
POST /replies/agent-write-back
```

只读人工/用户查询接口继续使用 NewCar 用户上下文，不得混用 Local Agent token。

### 3. 商户隔离

机器任务必须同时满足：

```text
task.lead_id -> lead.merchant_id == token.merchant_id
task.staff_id -> staff.merchant_id == token.merchant_id
```

不得使用 OR。关联缺失、任一侧跨商户、payload ID 与 task 不一致均拒绝。

### 4. 原子事务

主派单持久化顺序统一为：

```text
违禁词替换
-> 创建/flush WechatTask
-> 创建/flush LeadNotification
-> 单次 commit
```

任一步数据库失败必须 rollback，不能留下“可执行任务但无审计通知”或“有通知但无任务”的半状态。

### 5. PostgreSQL 冒烟

`SMOKE_DATABASE_URL` 必须同时满足：

```text
scheme == postgresql+psycopg
host in {localhost, 127.0.0.1, postgres, auto-wechat-postgres-dev}
database 以 _test 或 _staging 结尾
```

不满足时脚本拒绝运行。未提供安全连接串时，代码和契约测试可以完成，但整个阶段状态必须回传 `BLOCKED`，不得回传 DONE，不得进入 Phase 8。

---

## 六、执行任务

### Task 0：基线、祖先链与未提交修改归属审计

**目的：** 在任何编辑前冻结真实基线，避免覆盖用户工作或用错误的 `HEAD~N` 计算阶段范围。

1. 记录当前分支、HEAD、祖先链和工作区。
2. 四个已审批提交必须都在当前 HEAD 祖先链中。
3. 保存完整阶段起点 hash；后续 diff 不使用 `HEAD~N`。
4. 对 11 个未提交文件逐个审计，形成归属清单。
5. `docs/待确认事项.md` 必须排除提交。

执行命令：

```powershell
git status --short --branch
git log --oneline -12
git merge-base --is-ancestor 0c8bbd8 HEAD
git merge-base --is-ancestor ae59d59 HEAD
git merge-base --is-ancestor 7acedf4 HEAD
git merge-base --is-ancestor a62d5cb HEAD
$env:PHASE7_FIX2_TASK8_BASE = (git rev-parse HEAD)
```

基线测试：

```powershell
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_p0_5a_task_creation_flow.py tests/test_lead_notifications.py -v
python -m pytest tests/test_phase7_fix2_dispatch_trust_boundary.py tests/test_phase7_fix2_local_agent_auth.py tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_phase7_fix2_sales_feedback.py -v
```

静态确认 `_try_create_wechat_task`、optional 鉴权、机器 HTTP helper、naive 时间和敏感日志阻塞，并确认两个 PG smoke 文件当前是否缺失。

**停止条件：** 祖先链不满足、未提交修改无法区分归属、或必须覆盖用户修改才能继续。

**本 Task 不提交。**

#### 已报告的 3 个失败如何处理

1. `test_get_pending_wechat_tasks`：不豁免。测试必须携带有效 Local Agent token，并建立 token 商户一致的 lead、staff、task 数据。
2. `test_lead_notification_route_replaces_forbidden_words_before_write_text`：不豁免。修复失效 import 或测试入口，使其通过正式 `/send-to-staff` 路径验证违禁词替换；不得绕开或弱化违禁词 gate。
3. `test_pending_endpoint_requires_local_agent_token_and_keeps_agent_contract_with_token`：不接受把“期望 2、实际 0”直接标为 pre-existing。应修正 fixture 的商户关联，并同时断言同商户任务可见、跨商户和孤立任务不可见。

这三个节点必须在 Task 2/3 后全绿；若确有与本阶段无关的环境失败，必须提供固定起点同节点、同环境、同数据库的对照证据。

---

### Task 1：恢复微信真实派单唯一入口合同

**修改文件：**

```text
app/services/douyin_sync_service.py
tests/test_p0_5a_task_creation_flow.py
tests/test_phase7_fix2_dispatch_trust_boundary.py
```

**红灯测试：**

1. `douyin_sync_service.py` 不得定义 `_try_create_wechat_task`。
2. 同步流程即使 `auto_notify=true`，也不能直接创建 `single_send` 或调用 Local Agent 发送。
3. 业务 `single_send` 仍只允许 `/lead-notifications/send-to-staff` 创建。
4. 同步、入库、分配等非发送行为保持正常。

```powershell
python -m pytest tests/test_p0_5a_task_creation_flow.py tests/test_phase7_fix2_dispatch_trust_boundary.py -v
```

**最小实现：**

1. 删除 `_try_create_wechat_task()` 及仅供其使用的 import、常量和注释。
2. 搜索所有调用方；确认零调用后不新增替代 helper。
3. 不把死逻辑移动到其他同步函数，不形成新旁路。

**绿灯与静态检查：**

```powershell
python -m pytest tests/test_p0_5a_task_creation_flow.py tests/test_phase7_fix2_dispatch_trust_boundary.py -v
rg -n _try_create_wechat_task app tests
```

期望：测试全绿，`_try_create_wechat_task` 零命中。

**提交：**

```powershell
git add app/services/douyin_sync_service.py tests/test_p0_5a_task_creation_flow.py tests/test_phase7_fix2_dispatch_trust_boundary.py
git commit -m '修复：清理微信真实派单残留旁路'
```

---

### Task 2：补齐 Local Agent token 与机器接口闭环

**修改文件：**

```text
app/routers/wechat_tasks.py
app/routers/replies.py
app/local_agent_main.py
app/auth/local_agent_auth.py
app/services/wechat_task_service.py
tests/test_p0_5a_wechat_tasks.py
tests/test_p0_reply_2_agent_write_back.py
tests/test_phase7_fix2_local_agent_auth.py
```

**红灯测试：**

1. pending、机器详情、任务结果回写、销售回复回写无 token、空 token、错误 token 均为 401。
2. 正确 token 只能读取和回写对应商户任务。
3. 新增 `GET /wechat-tasks/agent/{task_id}`；跨商户或关联缺失返回 404。
4. 路由声明位于通用 `/{task_id}` 之前。
5. `agent-write-back` 校验 task、lead、staff 都属于 token 商户，且 payload ID 与 task 关联一致。
6. Local Agent 的 GET/POST helper统一携带 `X-Local-Agent-Token`。
7. 测试不在模块导入阶段修改 `os.environ`，改用 `monkeypatch` 或局部 fixture。

```powershell
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_p0_reply_2_agent_write_back.py tests/test_phase7_fix2_local_agent_auth.py -v
```

**最小实现：**

1. 删除 `wechat_tasks.py` 中 optional 鉴权死 import。
2. 所有机器写入口使用 `require_local_agent_context()`。
3. pending 和机器详情使用 INNER JOIN，同时按 lead、staff 的 merchant_id 过滤，禁止 OR。
4. 关联缺失、任一侧跨商户、payload ID 不一致均拒绝。
5. Local Agent helper从 `LOCAL_AGENT_TOKEN` 构造统一请求头；未配置时明确失败，不匿名请求。
6. token 不得进入 URL、日志、响应、前端或 `VITE_*`。

商户任务查询必须使用两个 INNER JOIN，并以 AND 同时过滤 lead 与 staff 的 `merchant_id`。

完成实现后重新运行本 Task 测试，必须全绿。

静态验收：optional 鉴权只允许保留在只读检测入口，`wechat_tasks.py` 必须零命中。token 只可出现在 Local Agent 后端配置与请求头，不得出现在前端和真实配置值中。

提交信息：`修复：补齐 Local Agent 机器鉴权闭环`。

---

### Task 3：修复跨商户分配、主派单原子事务与 PostgreSQL 时区

**修改文件：**

```text
app/services/assign_service.py
app/routers/lead_notification_actions.py
app/routers/lead_notifications.py
app/services/wechat_task_service.py
tests/test_phase7_fix2_assign_atomic_timezone.py
tests/test_lead_notifications.py
```

**红灯测试：**

1. 跨商户 staff 分配被拒绝，不修改 lead，不产生任务或通知。
2. staff 查询同时按 `staff_id` 与 `lead.merchant_id` 过滤。
3. 任务或通知任一 flush 失败时全部 rollback。
4. 成功路径只 commit 一次，任务和通知同时存在且关联一致。
5. PostgreSQL aware 时间与限频阈值比较不抛 `TypeError`；SQLite naive 时间兼容但不扩散 SQLite 专属 SQL。

```powershell
python -m pytest tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_lead_notifications.py -v
```

**最小实现：**

1. `assign_lead()` 用 lead 的 `merchant_id` 限定 staff 查询。
2. 主派单复用现有违禁词和资格 gate。
3. 任务 `flush`、通知 `flush` 后只做一次 `commit`。
4. 捕获 `SQLAlchemyError` 后 `rollback`，返回稳定错误 `DISPATCH_PERSIST_FAILED`，不泄露异常正文或 SQL 参数。
5. 限频时间统一为 UTC aware；数据库返回 naive 时按既有数据库约定规范化后比较。

**绿灯：**

```powershell
python -m pytest tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_lead_notifications.py -v
```

若仍有失败，必须在固定阶段起点或隔离数据库运行同一节点，给出可复现的前后对照；本 Task 触达的失败必须修复，不能仅标记为 pre-existing。

提交信息：`修复：保证微信派单跨租户原子事务`。

---

### Task 4：收口销售反馈异常事务与脱敏日志

**修改文件：**

```text
app/services/sales_feedback_parser.py
app/routers/sales_feedback.py
tests/test_phase7_fix2_sales_feedback.py
```

**红灯测试：**

1. parser、upsert、commit 数据库异常均被隔离，不破坏回复检测核心状态。
2. 失败路径 rollback，且不覆盖已有成功反馈。
3. `caplog` 中不含手机号、微信号、客户原文、SQL 参数、异常正文和 `parse_error` 内容。
4. 正常解析与三类模板持久化行为保持不变。

```powershell
python -m pytest tests/test_phase7_fix2_sales_feedback.py -v
```

**最小实现：**

1. 删除销售反馈路径中的 `logger.exception`。
2. 不记录 `str(exc)`、`repr(exc)`、SQL 参数、输入原文或 `result.parse_error`。
3. 日志只允许稳定事件名、merchant_id、task_id、lead_id、feedback_no、处理状态和 `type(exc).__name__`。
4. 解析失败回写稳定业务状态，不把解析详情写日志。
5. 保持解析事务与回复检测核心事务隔离。

**绿灯：**

```powershell
python -m pytest tests/test_phase7_fix2_sales_feedback.py -v
```

再静态检查 `logger.exception`、异常正文序列化和 `parse_error` 日志调用；业务对象字段可以存在，敏感内容不得进入日志参数。

提交信息：`修复：收口销售反馈异常事务和日志`。

---

### Task 5：补齐 PostgreSQL 冒烟合同测试与安全脚本

**新建文件：**

```text
tests/test_phase7_fix2_postgres_dispatch_smoke.py
scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
```

**红灯合同测试：**

1. 缺少 `SMOKE_DATABASE_URL` 时脚本明确退出，不回退 SQLite 或默认库。
2. 拒绝非 `postgresql+psycopg` scheme。
3. 拒绝非白名单 host。
4. 拒绝 database 名不以 `_test` 或 `_staging` 结尾。
5. URL、密码和 token 不输出到日志或测试失败信息。
6. 合法 URL 才进入建连与 smoke 流程；单元测试通过 monkeypatch 阻断真实连接。
7. 测试环境修改使用 `monkeypatch`，不得模块级污染 `os.environ`。

```powershell
python -m pytest tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
```

**脚本最小职责：**

1. 使用结构化 URL 解析，不用字符串包含判断。
2. 校验 scheme、host、database 后再创建 engine。
3. 只操作安全测试库，测试结束回滚或清理本次生成数据。
4. 验证跨商户分配拒绝、同商户派单成功、任务通知原子持久化、10 秒限频及 aware 时间比较。
5. 不启动服务，不发 HTTP 到 9000/19000，不触发微信，只直接调用 service/router 所依赖的数据层逻辑。
6. 失败返回非零退出码，成功输出不含连接串。

**绿灯：**

```powershell
python -m pytest tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
python scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
```

第二条在未配置安全 URL 时预期为明确拒绝，不算真实 PG smoke 通过。

提交信息：`测试：补齐微信派单 PostgreSQL 冒烟`。

---

### Task 6：执行真实非生产 PostgreSQL 冒烟

**前置条件：** 执行窗口必须获得显式 `SMOKE_DATABASE_URL`，并证明它符合本执行包白名单。不得读取或复用 `DATABASE_URL`、生产 `.env` 或线上凭据。

1. 只显示脱敏后的 scheme、host 和 database 名，不显示用户名、密码或完整 URL。
2. 先运行安全拒绝测试，再运行真实脚本：

```powershell
python -m pytest tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
python scripts/smoke_phase7_fix2_postgres_dispatch_gate.py
```

3. 实跑必须验证：

- 跨商户 staff 分配被拒绝；
- 同商户任务与通知同时成功；
- 模拟通知持久化失败后任务和通知都不存在；
- 同商户同销售 10 秒内命中限频，`retry_after_seconds` 为 1..10；
- 不同商户或不同销售不互相限频；
- PostgreSQL `TIMESTAMPTZ` 路径无 naive/aware 比较异常；
- 并发事务下不能同时绕过派单限频 gate。

4. 冒烟数据必须带唯一测试前缀，并在 finally 中清理。清理失败时回传残留 ID，不得执行无条件全表删除。

**硬门禁：**

- 有安全 URL 且真实 PG smoke 全绿：Task 6 通过。
- 无安全 URL：状态为 `BLOCKED`，可以回传前五个 Task 已完成，但 Phase 7-FIX2 不得宣布 DONE。
- URL 不安全：拒绝执行并回传 `BLOCKED`。
- 不允许用 SQLite、mock engine 或仅合同测试替代本 Task。

**本 Task 默认不提交；只有 smoke 脚本本身发现缺陷并修正时，才追加 `测试：修正微信派单 PostgreSQL 冒烟`。**

---

### Task 7：全阶段回归与精确提交审计

依次运行：

```powershell
python -m pytest tests/test_p0_5a_task_creation_flow.py tests/test_phase7_fix2_dispatch_trust_boundary.py -v
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_p0_reply_2_agent_write_back.py tests/test_phase7_fix2_local_agent_auth.py -v
python -m pytest tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_lead_notifications.py -v
python -m pytest tests/test_phase7_fix2_sales_feedback.py -v
python -m pytest tests/test_phase7_fix2_postgres_dispatch_smoke.py -v
```

然后运行原 Phase 7 关联回归：

```powershell
python -m pytest tests/test_manual_notify_sales_task.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_staff_merchant_crud.py tests/test_forbidden_word_send_integration.py -v
```

任何失败都要给出测试节点、起点对照、当前结果和是否由阶段文件触达。不能仅汇总失败数量。

静态与边界检查：

```powershell
git diff --check $env:PHASE7_FIX2_TASK8_BASE..HEAD
git diff --name-only $env:PHASE7_FIX2_TASK8_BASE..HEAD
git status --short --branch
```

还必须检查：

1. `_try_create_wechat_task` 和 `wechat_tasks.py` optional 鉴权零命中。
2. 销售反馈日志无 `logger.exception` 和敏感异常正文。
3. 阶段 diff 只包含允许文件。
4. `docs/待确认事项.md` 未进入任何新增提交。
5. `app/models.py`、migrations、微信 UI 底层、9100、前端、Phase 8/9 文件零触碰。
6. 未新增权限码、依赖、环境变量或真实 secret。
7. 原四个 FIX2 提交 hash 未改变。
8. 用户提交若穿插，使用精确 hash 审计，不使用 `HEAD~N`。
9. 工作区剩余用户修改逐项如实列出，不清理、不回滚。

---

### Task 8：双评审与固定格式回传

#### Spec Reviewer 清单

1. 死派单 helper 已删除，业务 `single_send` 仅有正式主入口。
2. Local Agent 四个机器接口全部强制 token。
3. 机器详情路由存在且未被动态路由遮蔽。
4. 任务读取和回写按 lead、staff 双重商户归属隔离。
5. 跨商户分配被拒绝。
6. 任务与通知单事务、单 commit，失败完整 rollback。
7. aware 时间和限频通过真实非生产 PostgreSQL 验证。
8. 销售反馈日志不泄露客户原文、联系方式、SQL 参数和异常正文。
9. 测试无模块级环境污染。
10. PG smoke 测试与脚本存在，安全 URL 校验完整。
11. 无迁移、权限码、依赖、环境变量和越界功能。
12. 用户既有工作未被覆盖或误提交。

#### Code Quality Reviewer 清单

1. 删除死代码，没有新增替代抽象。
2. token header 在 Local Agent HTTP helper 中集中处理。
3. 商户隔离使用 JOIN + AND，不在 Python 侧事后过滤。
4. 事务边界清晰，无内部 helper 偷偷 commit。
5. UTC aware 规范化集中且有 SQLite/PG 两侧测试。
6. 日志使用稳定事件与异常类型，不使用异常正文。
7. smoke 使用结构化 URL 解析，拒绝默认库和危险 host。
8. 新测试可独立、乱序运行，不依赖模块导入顺序。
9. 修改保持最小，无无关重构。

任一 Reviewer 给出 Must Fix，执行窗口必须追加修复提交并重新测试、重新评审，不得自行宣布通过。

---

## 七、阶段结果判定

| 条件 | 状态 |
|---|---|
| 所有专项与关联回归通过，真实安全 PG smoke 通过，双评审 Approved | `DONE` |
| 代码与合同测试完成，但无安全 `SMOKE_DATABASE_URL` 或真实 PG smoke 未执行 | `BLOCKED` |
| 发现必须迁移、修改微信底层、使用生产资源或覆盖用户工作 | `BLOCKED` |
| 有本阶段新增失败、越界修改、敏感日志或鉴权旁路 | `FAILED` |

`BLOCKED` 不能被表述为 `DONE_WITH_CONCERNS`，也不能进入 Phase 8。

---

## 八、固定回传模板

```text
阶段：Phase 7-FIX2 Task 8 阻塞修复
状态：DONE / BLOCKED / FAILED

阶段起点：
- <完整 hash>

原 FIX2 提交祖先链：
- 0c8bbd8：是/否
- ae59d59：是/否
- 7acedf4：是/否
- a62d5cb：是/否

新增提交：
- <hash> 修复：清理微信真实派单残留旁路
- <hash> 修复：补齐 Local Agent 机器鉴权闭环
- <hash> 修复：保证微信派单跨租户原子事务
- <hash> 修复：收口销售反馈异常事务和日志
- <hash> 测试：补齐微信派单 PostgreSQL 冒烟

变更文件：
- <逐项列出>

用户既有修改处理：
- <逐文件说明保留、继续编辑或排除提交>

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：models.py、migrations、微信 UI 自动化底层、9100、前端、Phase 8/9

测试命令与结果：
- <命令>：<结果>

PostgreSQL smoke：
- scheme/host/database 脱敏信息：<只写安全非敏感部分>
- 安全校验：PASS/FAIL
- 真实连接执行：PASS/未执行
- 跨商户、原子事务、限频、时区、并发结果：<逐项>

静态检查：
- 死派单 helper：零命中/失败
- optional 机器鉴权：零越界/失败
- 敏感异常日志：零命中/失败
- git diff --check：PASS/FAIL
- 阶段文件范围：PASS/FAIL

自审结论：
- Spec Reviewer：Approved / Must Fix
- Code Quality Reviewer：Approved / Must Fix

剩余失败：
- <每个测试节点给出起点对照和当前结果，不得只写 pre-existing>

剩余风险：
- <如实列出>

需要审批窗口裁定：
- 是否确认 Phase 7-FIX2 通过？
- 是否可以进入 Phase 8 执行包制定？
```

当状态为 `BLOCKED` 时，最后两个审批问题必须替换为“需要提供安全非生产 PostgreSQL 连接串并重新执行 Task 6”，不得请求进入 Phase 8。
