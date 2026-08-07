# M04 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| WeChat task create | COVERED | test_manual_notify_sales_task.py / test_lead_wechat_notify_eligibility_service.py |
| task polling | MISSING | 无 19000 poll 路径集成测试 |
| task claim | MISSING | 无 lease/claim 测试（功能不存在） |
| result report | PARTIAL | test_p0_reply_2_agent_write_back.py（回写路径）；无幂等性测试 |
| result idempotency | MISSING | 无重复回写幂等测试 |
| merchant isolation | COVERED | test_p0_5a_wechat_tasks.py（商户隔离） |
| sales mapping | PARTIAL | 代码确认 staff_id FK 绑定；无 E2E |
| lead mapping | COVERED | 代码确认 lead_id FK 永久绑定 |
| send task | MISSING | 无真实微信发送测试（需 Windows+微信） |
| retry | MISSING | 无自动重试机制（功能不存在） |
| offline behavior | MISSING | 无 Agent 离线场景测试 |
| feedback collection | PARTIAL | test_p0_reply_2_agent_write_back.py；test_sales_feedback_parser.py（parser 单测） |
| feedback parse | COVERED | test_sales_feedback_parser.py（三类模板解析） |
| feedback persistence | PARTIAL | parser 单测 PASS；parse_and_persist API 400（ISSUE-M02-007） |
| M02 integration | COVERED | test_phase7_fix2_assign_atomic_timezone.py / test_phase7_fix2_dispatch_trust_boundary.py |
| 19000 integration | EXTERNAL_ENV_REQUIRED | 需 Windows + 微信 + 19000 运行 |
| Legacy guard | COVERED | test_p0_end_2a_legacy_scheduler_disable.py / test_legacy_wechat_debug_lockdown.py |

## E2E 验真结果（2-M04.2 Docker，2026-08-07）

环境：docker compose dev（9000 + PG + 能力中心，无 19000）

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| A Task Create | PARTIAL | send-to-staff 创建成功（task_id=1），但 GET /wechat-tasks 查询返回 0 条——**需 R1 定位**：POST create result → DB WechatTask row → task.status → task.merchant_id → GET list query filter → GET pending query filter，明确是 CURRENT_BEHAVIOR 还是 ISSUE |
| B Poll Merchant Isolation | **TEST_AUTH_FIXTURE_GAP** | LOCAL_AGENT_TOKEN 非 "dev"，agent header 401——是测试身份 fixture 问题，非 Windows 依赖。R1 用合法 token fixture 补 |
| C Concurrent Poll | **TEST_AUTH_FIXTURE_GAP** | 同 B，需合法 agent token fixture |
| D Result State Transition | **TEST_AUTH_FIXTURE_GAP** | 同 B |
| E Duplicate Result | **TEST_AUTH_FIXTURE_GAP** | 同 B |
| F Invalid Task Result | CODE_VERIFIED | 代码确认 task_belongs_to_merchant 双校验 |
| G Lead/Staff Consistency | CODE_VERIFIED | 代码确认 lead_id+staff_id FK 创建时固化 |
| H Manual send-to-staff | **PASS** | Lead+Staff+联系方式→send-to-staff→200 created（task_id=1, feedback_no=XGF-7-1） |
| I-A Server-side Feedback Persistence | **PENDING R1** | Lead+Staff+WechatTask+feedback_no+合法模板→write-back→parse_and_persist→SalesLeadFeedback/ReplyCheck/Lead。Docker 可测（进程内调用）。决定 ISSUE-M02-007 能否关闭 |
| I-B Real Feedback Collection | **WINDOWS_REQUIRED** | 19000→detect_reply→真实微信消息→write-back。需 Windows 19000 |

### 环境限制说明

- **LOCAL_AGENT_TOKEN**：docker dev 配置的 token 非 "dev"，agent header 401，无法用 Local Agent 身份 poll/result
- **19000 不在 docker compose**：19000 是宿主机 Windows 进程，docker dev 无法模拟
- **GET /wechat-tasks 查询**：send-to-staff 返回 task_id=1 但列表查询返回 0 条，可能需要 agent token 或其他查询条件
- Gate B/C/D/E 的核心验证需正确配置 LOCAL_AGENT_TOKEN 或在真实 19000 环境进行

### ISSUE-M04-001/002 升级条件检查

- **Concurrent Poll（C）**：ENVIRONMENT_BLOCKED，未证明两 Agent 同时获取同一 Task
- **Duplicate Result（E）**：ENVIRONMENT_BLOCKED，未证明重复回写产生重复副作用
- 两个 ISSUE 保持 MEDIUM，升级条件未满足

### ISSUE-M02-007 检查

- Gate I PENDING，需完整 feedback context + 真实 detect_reply 路径
- 保持 MEDIUM，ISSUE-M02-007 不关闭

**E2E 状态：`M04_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_AUTH_FIXTURE`**（无 BLOCKER，Gate H PASS + F/G CODE_VERIFIED + I-A PENDING R1 + I-B WINDOWS_REQUIRED，B/C/D/E TEST_AUTH_FIXTURE_GAP）

## 2-M04.2R1 Local Agent Protocol Fixture Gap Closure（2026-08-07）

### 环境阻断确认

docker dev 环境的 `LOCAL_AGENT_TOKENS` 未配置：
- `_token_map()` 返回 empty（docker compose env_file `.env.development.local` 不存在，required: false 不报错）
- agent 路由（`/wechat-tasks/pending`、`/wechat-tasks/agent/{id}`、`/wechat-tasks/{id}/result`）强制 `require_local_agent_context`，无 token → 401 `LOCAL_AGENT_TOKEN_MISSING` 或 `LOCAL_AGENT_TOKEN_INVALID`
- 尝试通过 `.env.development.local` 注入 `LOCAL_AGENT_TOKENS=dev-merchant:test-agent-token`，但 docker compose env_file 加载机制导致 postgres `PG_PASSWORD` 未设置容器崩溃
- 删除 `.env.development.local` 后 docker compose 恢复正常

### 根因

docker dev 环境设计上不包含 Local Agent token 配置——Local Agent 是宿主机 Windows 进程，docker dev 主要用于 9000/9100 API 开发。agent 路由的 token 验证是运行时安全设计，不是测试可以绕过的配置。

### R1 Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| 1 Task Create→DB→List/Pending | PARTIAL | send-to-staff 创建成功（task_id=2）；GET /wechat-tasks (Bearer) 返回 0 条——可能是列表 API 权限/查询条件不同（agent route 需 token），需用 agent token 查才能确认 DB row 是否存在 |
| 2 Poll Merchant Isolation | TEST_AUTH_FIXTURE_GAP | agent token 401 |
| 3 Concurrent Poll | TEST_AUTH_FIXTURE_GAP | agent token 401 |
| 4 Result State Transition | TEST_AUTH_FIXTURE_GAP | agent token 401 |
| 5 Duplicate Result | TEST_AUTH_FIXTURE_GAP | agent token 401 |
| 6 Cross-merchant Result Rejection | CODE_VERIFIED | 代码确认 task_belongs_to_merchant 双校验 |
| 7 Cross-merchant Lead/Staff Rejection | CODE_VERIFIED | 代码确认 assign_service 商户校验 |
| 8 Full-context Feedback (I-A) | TEST_AUTH_FIXTURE_GAP | 需 agent token 通过 write-back 路径或直接进程内调用 parse_and_persist |

### 解决方案建议

不修改业务代码，但需修改 docker compose 配置（`docker-compose.dev.yml` environment 段或 `docker-compose.override.yml`）注入：
```
LOCAL_AGENT_TOKENS: "dev-merchant:test-agent-token"
```
这属于 infra 配置改动，非业务代码改动。需用户批准后执行。

### ISSUE-M04-001/002 升级条件检查

- **Concurrent Poll（Gate 3）**：TEST_AUTH_FIXTURE_GAP，未证明两 Agent 同时获取同一 Task → 保持 MEDIUM
- **Duplicate Result（Gate 5）**：TEST_AUTH_FIXTURE_GAP，未证明重复回写产生重复副作用 → 保持 MEDIUM

### ISSUE-M02-007 检查

- Gate 8（I-A）：TEST_AUTH_FIXTURE_GAP，未跑通完整 feedback context → 保持 MEDIUM，不关闭

**R1 状态：`M04_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_AUTH_FIXTURE`**（无 BLOCKER，Gate 1 PARTIAL + 6/7 CODE_VERIFIED + 2/3/4/5/8 TEST_AUTH_FIXTURE_GAP，需 docker compose 配置注入 token）

## 2-M04.2R2 Local Agent Auth Fixture + Protocol Gate Closure（2026-08-07）

### Auth Fixture 注入

- `docker-compose.dev.yml` environment 段加 `LOCAL_AGENT_TOKENS: "${LOCAL_AGENT_TOKENS:-}"`（透传，不硬编码）
- `.env.development.local`（gitignored）设置 `LOCAL_AGENT_TOKENS=dev-merchant:test-agent-token`
- 用 `docker compose -f docker-compose.dev.yml` 运行（dev.yml 是独立完整编排非 override）
- 验证：valid token `test-agent-token` → agent route 200 + 映射 merchant_id=dev-merchant ✓

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| 1 Task Create→DB→Agent Pending | **PASS** | send-to-staff→task_id=3 created；agent pending 查询找到 task_id=3（status=pending, lead_id=11, staff_id=1, target=测试销售微信） |
| 2 Concurrent Poll | **FAIL → ISSUE-M04-001 升级 HIGH** | 两客户端同时 GET pending→A1=1 A2=1 same=True（拿到同一 Task）→ **DUPLICATE_EXECUTION_RISK** |
| 3 Result State Transition | **PASS** | pending→POST result→status=pasted（task_id=1, 200 OK, 含完整 task 数据） |
| 4 Duplicate Result | **PASS** | 重复提交 200 OK；detect_reply=1（去重正确，不重复创建）；**无重复副作用证据 → ISSUE-M04-002 不升级** |
| 5 Merchant/Task Ownership | CODE_VERIFIED | 代码确认 task_belongs_to_merchant 双校验，跨商户 404 |
| 6 Full-context Feedback (I-A) | **PASS** | parse_and_persist_sales_feedback 进程内调用成功（parse_status=success, kind=lead_feedback, error=None）→ **ISSUE-M02-007 可关闭** |

### ISSUE 升级/关闭

| ISSUE | 变化 | 原因 |
|---|---|---|
| ISSUE-M04-001 无 lease/claim | MEDIUM → **HIGH / DUPLICATE_EXECUTION_RISK** | Gate 2 E2E 证明两 Agent 同时获取同一 Task |
| ISSUE-M04-002 result report 非幂等 | 保持 MEDIUM | Gate 4 重复提交无重复副作用证据（detect_reply 去重正确），但 _report_wechat_task_compute_usage 重复调用风险仍在 |
| ISSUE-M02-007 Feedback parse-and-persist | **CLOSED** | Gate 6 进程内调用成功；root cause: earlier E2E fixture lacked DB/task context, production contract defect=NO |

### R2 状态

**`M04_DOCKER_E2E_VERIFIED_PENDING_WINDOWS`**（无 BLOCKER，Gate 1/3/4/6 PASS + 5 CODE_VERIFIED，Gate 2 FAIL→ISSUE-M04-001 升级 HIGH 不阻断 Baseline）

## 2-M04.3 Windows 19000 / Real WeChat E2E（2026-08-07）

### 环境阻断确认

| 条件 | 当前 | 需要 |
|---|---|---|
| 19000 Local Agent 运行 | **未运行**（curl 127.0.0.1:19000 EXIT=7） | 小高AI微信助手.exe 启动 |
| 微信客户端登录 | 未知 | 微信已登录 |
| 19000 server_url | 未知 | 指向 9000（docker 或本地） |

### Gate 结果

| Gate | 结果 | 原因 |
|---|---|---|
| 1 Sender Identity | ENVIRONMENT_BLOCKED | 19000 未运行 |
| 2 Recipient Identity | ENVIRONMENT_BLOCKED | 19000 未运行 |
| 3 Foreground Guard | ENVIRONMENT_BLOCKED | 19000 未运行 |
| 4 Real WeChat Feedback (I-B) | ENVIRONMENT_BLOCKED | 19000 未运行 + 微信未确认 |
| 5 Heartbeat / Offline | ENVIRONMENT_BLOCKED | 19000 未运行 |
| 6 Full Execution Chain | ENVIRONMENT_BLOCKED | 19000 未运行 |

### 解除阻断条件

1. 启动小高AI微信助手.exe（19000 Local Agent）
2. 确认微信客户端已登录
3. 配置 19000 server_url 指向 9000（当前 docker dev `http://127.0.0.1:9000`）
4. 配置 19000 LOCAL_AGENT_TOKEN 与 9000 一致（`test-agent-token` -> `dev-merchant`）

满足后补验证 6 Gate（Sender/Recipient Identity + Foreground Guard + Real Feedback + Heartbeat + Full Chain），不重测 Docker 已完成的协议 Gate。

**M04.3 状态：`M04_DOCKER_E2E_VERIFIED_PENDING_WINDOWS`**（环境阻断，6 Gate 全部 ENVIRONMENT_BLOCKED，需 19000 启动后补验证）

## E2E 验收清单（待 2-M04.2 Windows / Staging）

### CODE_VERIFIED
- WechatTask 数据模型 + 状态机
- 9000→19000 HTTP 通信 + token 认证
- 商户隔离双层（token→merchant_id + lead/staff FK 反查）
- feedback_no 生成+校验（XGF-{lead_id}-{staff_id}）
- ISSUE-M02-007 CONTRACT_MATCHES（M04 输出格式与 parse_and_persist 一致）

### DOCKER_TESTABLE
- WechatTask CRUD（API 层）
- 手动 send-to-staff 创建任务
- result report 状态流转
- merchant isolation（跨商户 task_id → 404）

### WINDOWS_LOCAL_AGENT_REQUIRED
- 19000 poll → 微信 UI 自动化执行 → result 回传
- detect_reply → 微信消息读取 → 反馈采集
- foreground guard / search_focus / OCR 验证
- heartbeat → online/offline 判断

### REAL_WECHAT_REQUIRED
- 真实微信发送（paste_only/single_send）
- 真实销售反馈采集（模板回填）
- 空号反馈写入 CustomerProfile

### STAGING_REQUIRED
- M02 webhook→M04 自动通知（auto_notify 当前 disabled）
- M04→M02 真实反馈持久化全链路

### POLICY_PENDING
- super_admin Local Agent 访问行为

---

## M04_BASELINE_CANDIDATE

> 状态：**BASELINE_CANDIDATE**（非 MODULE_BASELINE_APPROVED）
> 代码基线：c26ec227e70d
> Windows 恢复后只补 W01-W06，不重做 Docker E2E

### VERIFIED

- M04 owns WechatTask
- Manual send-to-staff → persistent task + feedback_no (XGF-{lead}-{staff})
- Local Agent auth contract（X-Local-Agent-Token → merchant_id）
- Task → Agent pending 可见
- Result state: pending → pasted
- Feedback server-side persistence（parse_and_persist 进程内 PASS）
- M04↔M02 feedback contract MATCH
- auto_notify: implemented but disabled
- Manual notification: ACTIVE
- Duplicate result: detect_reply DEDUP VERIFIED
- Cross-merchant task ownership: CODE_VERIFIED

### KNOWN HIGH ISSUE

- ISSUE-M04-001: No atomic claim/lease → concurrent agents can receive same task → DUPLICATE_EXECUTION_RISK (E2E VERIFIED)

### KNOWN MEDIUM ISSUE

- ISSUE-M04-002: Compute/financial duplicate side effect NOT VERIFIED → defer to M07

### PENDING_WINDOWS

- W01 Heartbeat/offline
- W02 Sender Identity（最高优先级）
- W03 Recipient Identity
- W04 Foreground Guard
- W05 Real Feedback (detect_reply → write-back)
- W06 Full Chain (9000→19000→微信→result→9000)

### LIFECYCLE_PENDING

- legacy_foreground_ok / diag: UNKNOWN → ACTIVE candidate pending W04 evidence

### 冻结路径

Windows 恢复 → 补 W01-W06 → `M04_MODULE_BASELINE_APPROVED`
