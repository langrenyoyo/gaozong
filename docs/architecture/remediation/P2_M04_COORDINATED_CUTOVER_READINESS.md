# P2-M04 notify_sales Coordinated Cutover Readiness / Release Gate

> 窗口：`P2-M04-COORDINATED-CUTOVER-READINESS / RELEASE GATE`
> 窗口性质：RELEASE READINESS ONLY — 不改业务代码、不改 migration、不改 Local Agent、不部署、不迁移、不发送真实微信、不 push
> 代码 baseline：`P2_IMPLEMENTATION_CLOSURE_COMMIT = 36fe68a3f5c933d6bc2b50dd7c0bfcacfdb70ce2`（未 push）
> 前序：P2 M04 CLAIM/LEASE = REMEDIATED（独立实施审批 APPROVED_WITH_CORRECTIONS，C1-C14 ALL APPLIED）
> 日期：2026-08-12

---

## 0. Governance Baseline

```text
P2-F1 NO DURABLE CLAIM = RESOLVED
P2-F2 NO LEASE / CRASH RECOVERY = RESOLVED
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = MITIGATED / KNOWN LIMITATION
P2 M04 CLAIM/LEASE = REMEDIATED
EXTERNAL_WECHAT_EXACTLY_ONCE = NOT GUARANTEED
BLIND_RETRY_AFTER_UNKNOWN = BLOCKED
```

代码设计与实施已闭环（closure commit `36fe68a`）。本窗口不再审查代码设计正确性，只回答：
**Migration 0035 + 新 9000 + 新 19000 是否已具备一次安全 coordinated production cutover 的全部条件？**

---

## 1. P2 Implementation Closure Commit

```text
P2_IMPLEMENTATION_CLOSURE_COMMIT = 36fe68a3f5c933d6bc2b50dd7c0bfcacfdb70ce2
message = 修复：闭环M04微信任务执行所有权
parent  = 9db3f58（设计：批准M04微信任务执行所有权方案）
status = COMMITTED / NOT PUSHED
```

候选范围已核实，仅含已批准 P2 范围：

| 类别 | 文件 |
|---|---|
| 9000 server | `app/services/wechat_task_service.py` / `app/routers/wechat_tasks.py` / `app/schemas.py` / `app/models.py` / `app/services/lead_wechat_notify_eligibility_service.py` |
| 19000 协议适配 | `app/local_agent_main.py` |
| producer uncertain dedup | `app/services/lead_wechat_notify_eligibility_service.py`（ACTIVE_NOTIFY_TASK_STATUSES +uncertain）|
| manual uncertain resolution | `wechat_tasks.py` 新增 `/resolve` + `/reclaim-stale` |
| migration | `migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py` |
| focused tests | `tests/test_p2_m04_claim_lease.py` |
| 报告 | 实施报告 + 实施审批报告 |

**明确不存在**：compute core、detect_reply 行为变更、send_report_attachment 行为变更、P2-F6 merchant ORM drift、Redis、heartbeat、attempt_started、9100、RB-10。`SCOPE_VIOLATION = NONE`。

后续 Release Gate 以 `36fe68a` 为唯一代码 baseline。

---

## 2. Release Unit（冻结）

本次发布单元 = **Migration 0035 + 新 9000 server + 新 19000 Local Agent**，三者必须同批次上线。

```text
new server → GET /pending (notify_sales) 返回 claim_token（claim-and-return-one）
new agent → 必须保留 claim_token 并在 callback 回传
server callback fencing → 依赖新协议（claim_token_hash CAS）
```

- SERVER-ONLY RELEASE = NOT AUTHORIZED（新 server + 旧 agent：每次 callback 缺 token → 409 StaleAttemptError → task 卡 running → lease 过期 → uncertain，见 §10）
- AGENT-ONLY RELEASE = NOT AUTHORIZED（旧 server 无 claim_token_hash 列，新 agent 回传 token 被忽略，等于无 claim）

---

## 3. Coordinated Cutover R2（冻结）

```text
R2 = coordinated maintenance cutover（一次性维护窗口切换）
```

不得改为 staged backward compatibility rollout。目标序列见 §19，必须最终冻结成一条可执行 runbook。

---

## 4. Production Current Reality

> 2026-08-12 经只读 HTTP 核实（`GET /ready`，不直连 DB、不写数据）。

### ★ 重大发现：生产存在两套 auto_wechat 9000 实例（双域双后端）

只读核实确认生产有**两个独立 9000 实例**，承载不同后端与不同 alembic head：

| 域 | backend | database | alembic actual | 部署代码 head(expected) | `/wechat-tasks/pending` | `/agent/version` |
|---|---|---|---|---|---|---|
| `callback.misanduo.com` | **sqlite** | (dev_non_pg) | `0033` | `0033` | 401（有 agent 鉴权）| 404 |
| `merchant.xiaogaoai.cn/api` | **postgresql** | `auto_wechat` | `0028` | `0028` | 401（有 agent 鉴权）| 404 |

```text
CALLBACK_INSTANCE  = callback.misanduo.com  → SQLite / dev_non_pg / schema 0033
MERCHANT_INSTANCE  = merchant.xiaogaoai.cn  → PostgreSQL / auto_wechat / schema 0028
```

### 核实详情

**callback.misanduo.com**（build 脚本默认 `AUTO_WECHAT_SERVER_URL`）：
```json
GET /ready → backend=sqlite, mode=dev_non_pg, schema_revision current=0033 expected=0033
GET /health → {"service":"auto_wechat","status":"ok"}
GET /wechat-tasks/pending → 401（Local Agent 鉴权生效，agent poll 端点存在）
GET /agent/version → 404（无该路由）
```

**merchant.xiaogaoai.cn/api**（前端反代入口）：
```json
GET /api/ready → backend=postgresql, database_name actual=auto_wechat(expected match),
                 alembic_revision expected=["0028"] actual=["0028"],
                 critical_tables douyin_leads/sales_staff pass
GET /api/health → {"service":"auto_wechat","status":"ok"}
GET /ready → 前端 HTML "小高AI系统"（/ready 不在反代规则，需走 /api/ready）
GET /api/wechat-tasks/pending → 401（agent 鉴权生效）
GET /api/agent/version → 404
```

### 对 P2 Cutover 的影响

1. **生产 PG 实例 alembic head = 0028，不是预期的 0034**（§6 precondition 是 `=0034`）。
   → `RELEASE_BLOCKED_BY_SCHEMA_BASELINE_DRIFT`（0028 ≠ 0034）。
   生产 PG 远落后于本地 baseline，需先补齐 0028→0034 才能再上 0035。

2. **callback 实例是 SQLite / dev_non_pg**，与 CLAUDE.md 硬约束 #2"PostgreSQL 目标方案已确认…SQLite 只是开发和过渡数据库"冲突。
   callback 实例跑 `schema_revision 0033`，且 `/wechat-tasks/pending` 返回 401（有 agent 鉴权）——
   若有 agent 连 callback 域，它在操作一个 **SQLite 生产实例**。

3. **两个实例哪个承载 notify_sales 业务 / agent 实际连哪个域**，无法从只读 HTTP 推断
   （取决于销售电脑上 exe 的 `AUTO_WECHAT_SERVER_URL`，build 默认值=`callback.misanduo.com`，但生产部署可能覆盖）。
   → **REQUIRES_USER_CONFIRMATION**：必须由用户确认生产 agent 实际 server_url、
   notify_sales 业务承载实例、callback SQLite 实例的角色（webhook 观察服务？旧 dev 残留？独立部署？）。

### 未核实项（需生产侧/现场确认）

| 项 | 状态 |
|---|---|
| production git/commit（两实例各自）| REQUIRES_PRODUCTION_VERIFICATION（`/agent/version` 404 无法远程读）|
| 19000 distributed version | REQUIRES_PRODUCTION_VERIFICATION（旧 exe `GIT_COMMIT=cd09c37`，2026-07-13 构建，见 §22）|
| current Local Agent count | REQUIRES_PRODUCTION_VERIFICATION（远程销售 Windows 机）|
| current Local Agent version | REQUIRES_PRODUCTION_VERIFICATION |
| 两实例关系与流量归属 | **REQUIRES_USER_CONFIRMATION** |

**不基于本地状态猜生产**。双实例现实与 P2 cutover 计划（假设单一生产 PG 9000）不符，必须在 cutover 前由用户厘清生产拓扑。

---

## 5. Migration Readiness

读取 `migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py`（静态 + 实施审批独立 bootstrap 验证）：

```text
revision = 0035
down_revision = 0034
chain: 0032 → 0033 → 0034 → 0035 ✅
```

| 检查 | 结论 |
|---|---|
| 0034 → 0035 upgrade tested | ✅（实施审批独立隔离 PG au-p2-iso@5438 bootstrap PASS）|
| fresh bootstrap tested | ✅（head=0035）|
| additive only | ✅（4 列 + 1 索引，无 DROP/ALTER 破坏）|
| no destructive backfill | ✅（无数据回填）|
| existing pending tasks remain claimable | ✅（新列 nullable / server_default，旧 pending 行不受影响）|
| attempt_count defaults 0 | ✅（`Integer NOT NULL server_default="0"`）|
| claim_token_hash NULL for legacy rows | ✅（nullable，首次 claim 才填）|
| lease_expires_at NULL | ✅（nullable）|
| claimed_by NULL | ✅（nullable）|
| index exists | ✅（`idx_wechat_tasks_status_lease` on (status, lease_expires_at)）|

downgrade / code rollback implications：见 §35-38。

---

## 6. Production Migration Precondition

```text
production alembic current 必须为 0034（预期 pre-0035 baseline）
```

**只读核实结果（2026-08-12）**：

```text
merchant.xiaogaoai.cn/api（生产 PG 实例）:
  alembic_revision expected=["0028"] actual=["0028"]   ← DB 与部署代码 head 均 = 0028
  0028 ≠ 0034（pre-0035 baseline）
  → RELEASE_BLOCKED_BY_SCHEMA_BASELINE_DRIFT（CONFIRMED）
```

生产 PG 实例 schema 落后本地 6 个 revision（0028 vs 0034），且部署代码也停在 0028。cutover 前必须先补齐 `0028 → 0034`（含 0030 compute core / 0032 daily_report / 0033 material / 0034 preview），再上 0035。这已超出 P2-M04 单一 migration 上线范围，需独立的 schema 补齐审批。

```text
callback.misanduo.com（SQLite 实例）:
  schema_revision current=0033 expected=0033
  SQLite 不是 PostgreSQL；P2 0035 migration 仅适用于 PG 链。
  该实例是否需迁移/下线由生产拓扑厘清决定（见 §4 REQUIRES_USER_CONFIRMATION）。
```

不得直接 upgrade 0035。

---

## 7. Pause Mechanism — Hard Gate

coordinated cutover 必须能同时阻断：

- A. new notify_sales 创建
- B. 19000 poll / execution

按 current code/config 核实：

| 阻断目标 | 现有机制 | 评估 |
|---|---|---|
| B. poll/execution | 停止所有 19000 Local Agent 进程（pull-based：agent 不 poll → 9000 不 claim）| ✅ 可执行，需 §10/§11 验证全部停止 |
| A. creation（manual send-to-staff）| `POST /lead-notifications/send-to-staff`（lead_notification_actions.py）**无 automation_control 检查、无 feature flag** | ⚠️ 无代码级开关 |
| A. creation（return-visit auto）| `return_visit_silent_scan_scheduler` 受 `RETURN_VISIT_SILENT_SCAN_ENABLED` env 门控（默认 off），9000 重启时停 | ⚠️ 需确认 prod env + 重启 |
| A. creation（webhook 回访）| `replies.py` 后台 task `process_return_visit_run` → 命中场景 `_orchestrate_post_hit_action` → create notify_sales | ⚠️ webhook 持续到达则可能创建 |

**关键事实**：`automation_control.emergency_stop` 是**进程内内存状态**，9000 与 19000 是独立进程、各自独立状态。`emergency_stop` 仅守在 19000 执行侧（contact_searcher / input_writer / scheduler），**不守 9000 创建路径**，也**不守 9000 GET /pending claim 路径**（get_pending_wechat_tasks 无 is_automation_allowed 检查）。

详见 §8 / §9。

---

## 8. Creation Pause

`POST /lead-notifications/send-to-staff`（lead_notification_actions.py:42）在维护窗口如何停止产生新发送任务？

```text
现状：该路由无 feature_flag / maintenance_switch / automation_control 检查
       operator 点前端按钮 → 直接 create_wechat_task(notify_sales)
```

现有可执行手段（无新开关）：

1. **运维通告** —— 维护窗口内 operator 不点 send-to-staff（弱保证，依赖人）
2. **反向代理 503** —— nginx/宝塔 对 `POST /lead-notifications/send-to-staff` 返回 503（硬保证，需 §30 核实代理可控）
3. **回访 scheduler env off** —— 重启 9000 时 `RETURN_VISIT_SILENT_SCAN_ENABLED` 不设（cutover 期间 9000 本就要重启，scheduler 停）

残留：webhook 触发的回访链路（replies.py）在 9000 up + webhook 持续到达时仍可能创建 notify_sales。该路径无 env 开关，只能通过暂停 webhook 摄入或接受低残留风险。

```text
CREATION_PAUSE_FEATURE_FLAG = NONE
CREATION_PAUSE_PROCEDURE = OPERATIONAL_ONLY（通告 + 反代 503 + scheduler env off + webhook 暂停）
```

按 §8 硬约束"如果当前无安全 pause 机制：RELEASE_BLOCKER"——当前无单一代码级安全开关，且 webhook 回访创建路径无法在不暂停 webhook 摄入的情况下完全阻断。→ **BLOCKER-B1**，除非生产侧确认反代 503 + webhook 摄入可控。

---

## 9. Poll Pause

确保旧 19000 不会在 cutover 期间继续 `GET /pending` 并执行旧协议任务。

```text
机制：停止所有 19000 Local Agent 进程
       notify_sales 为 pull-based（agent 主动 poll）
       无 agent poll → 9000 不 claim → 无新 running
```

```text
POLL_PAUSE_MECHANISM = STOP_ALL_19000_AGENTS（可执行，见 §10/§11）
```

注意：9000 侧 GET /pending 无 automation 门控，即使 emergency_stop 开启，9000 仍会向任何 polling agent claim 并返回 task。**唯一可靠 poll pause = 物理停止所有 agent 进程**。

---

## 10. Old Agent Stop Procedure

19000 = `小高AI微信助手.exe`（entry: `app/local_agent_main.py`，pyinstaller spec: `小高AI微信助手.spec`）。

```text
process name = 小高AI微信助手.exe
stop procedure = 任务管理器结束进程 / UI 退出 / taskkill /F /IM 小高AI微信助手.exe
verification = tasklist | findstr 小高AI微信助手.exe（期望 0）
```

目标：

```text
OLD_AGENT_ACTIVE_COUNT = 0
```

**REQUIRES_PRODUCTION_VERIFICATION** —— 实际 agent 部署在客户/操作员 Windows 机器，本窗口无法核实进程状态。"不能只靠通知用户关闭"——需有可远程确认手段或现场确认流程。

→ **BLOCKER-B2**：无法从本窗口确认所有旧 agent 已停止。

---

## 11. Old Agent Zombie Check

```text
检查项：
  - 旧 19000 进程残留
  - Windows 后台实例
  - 重复启动实例
  - 旧 exe 残留
```

无 19000 可直接查询的 in-flight 状态接口（agent 为 pull 模式，本地无持久化 task 队列）。需人工验证：

- `tasklist | findstr 小高AI微信助手.exe` 期望唯一或 0 实例
- 检查 `dist/` 与部署目录是否有多版本 exe 共存

**REQUIRES_PRODUCTION_VERIFICATION**。→ 贡献 BLOCKER-B2。

---

## 12. Outstanding Task Inspection

暂停 creation + poll 后，查询生产 `wechat_tasks`（task_type=notify_sales）按状态统计：

```sql
SELECT status, COUNT(*) FROM wechat_tasks WHERE task_type='notify_sales' GROUP BY status;
```

预期状态集合：`pending / running / uncertain / pasted / sent / blocked / failed / cancelled`。

重点：`pending count` / `running count` / `uncertain count`。

**REQUIRES_PRODUCTION_VERIFICATION** —— 需生产 DB 只读访问。

---

## 13. Pre-Cutover Running 必须为 0

历史设计事实（实施报告 §5 Before Flow）：旧 notify_sales **从未使用 running 状态**（旧流程 pending → 直接 pasted/sent，无 running 中间态）。

```text
若 cutover 前看到 notify_sales running > 0：
  STOP
  UNEXPECTED_RUNTIME_STATE
  不得猜这些 row 是谁拥有
```

**REQUIRES_PRODUCTION_VERIFICATION**。

---

## 14. Existing Uncertain

0035 上线前理论上不存在新 uncertain 机制（uncertain 是 0035 引入的状态）。

```text
若生产已有 uncertain 行：
  必须查来源（不应存在于 pre-0035）
  不得直接继续 cutover
```

**REQUIRES_PRODUCTION_VERIFICATION**。

---

## 15. Existing Pending Tasks

0035 迁移后，existing pending 行：`claim_token_hash=NULL` / `attempt_count=0` / `lease_expires_at=NULL` / `claimed_by=NULL`。

新 19000 第一次 poll：

```text
→ atomic claim（CAS WHERE status=pending）
→ running
→ attempt_count=1
→ new token（首次填 claim_token_hash）
```

兼容链已在实施审批 §17 验证：legacy fallback 仅限 `claim_token_hash is None` 的 pre-0035 unclaimed records；新 claim 流程一旦写入 hash，callback 必须 token 匹配。**不要求清空 pending**。

```text
EXISTING_PENDING_COMPAT = VERIFIED（代码级）
```

---

## 16. Legacy Callback Window

停旧 agent 前是否存在"已执行外部动作但 callback 尚未回 9000"的旧任务？

旧协议：notify_sales 旧流程 pending → 直接 pasted/sent（callback 即 result 回写），无 running 中间态，无 claim_token。旧 in-flight 风险 = 旧 agent 已粘贴/发送但 result 尚未 POST。

```text
若存在 OLD_IN_FLIGHT_NOTIFY_SALES：
  不得立即升级 server 并改变状态语义
  必须先 drain 或 explicitly resolve
```

旧 in-flight task 若在 new server 上线后 callback：`claim_token_hash is None`（旧 task 未 claim）→ 走 legacy fallback → 旧 result 逻辑（向后兼容，C14）。但语义上 new server 把这些当作 legacy unclaimed 记录处理，安全。

drain 定义见 §17。**REQUIRES_PRODUCTION_VERIFICATION**（需查生产是否有 pending-but-already-acted 旧 task）。

---

## 17. Drain Definition

```text
OLD_AGENT_DRAINED 当且仅当：
  - 旧 Local Agent 无当前执行中 task
  - 无 in-flight notify_sales（已执行外部动作但未 callback）
  - 本地无 pending callback 缓冲
```

19000 无可直接查询的 in-flight 状态接口。人工验证手段：

- 停 agent 前等待一个最长执行周期（≤ lease 上界，旧协议无 lease，按 UIA 最长 ~2min + margin）
- 查 9000 生产 `wechat_tasks`：notify_sales `running` = 0（旧协议无 running，故应为 0）且近期无 pending→pasted/sent 正在写回
- 确认无 agent 本地日志显示"已粘贴未回写"

**REQUIRES_PRODUCTION_VERIFICATION**。

---

## 18. New/Old Compatibility Matrix（冻结）

| Server | Agent | Production Allowed |
|---|---|---|
| old | old | Yes before cutover |
| new | old | **NO** |
| old | new | **NO** |
| new | new | Yes after cutover |

**new server + old agent = NO 的代码依据**：新 server GET /pending 对 notify_sales claim-and-return-one，返回 claim_token；旧 agent 忽略该字段 → 执行真实微信发送 → POST /result 不带 claim_token → `task.claim_token_hash is not None` + status=running + `_const_eq(hash, None)`=False → **StaleAttemptError 409** → task 卡 running → lease 过期 → uncertain。即旧 agent 在新 server 下会"发送了但报不回成功"，全部转 uncertain。这是协议不兼容的硬阻断，正确。

**old server + new agent = NO 的依据**：旧 server 无 claim_token_hash 列 / 无 claim_notify_sales_task；新 agent poll 不到 claim_token，callback 回传 token 被旧 server 忽略，等于无 claim，退化为 fire-and-forget。

Legacy fallback（`claim_token_hash is None`）≠ 允许混版本运行，仅作数据库/过渡容错。

---

## 19. Deployment Sequence（runbook 候选）

```text
 1. announce maintenance（通告维护窗口，operator 停止 send-to-staff）
 2. pause notify_sales creation（反代 503 send-to-staff + webhook 摄入暂停 + scheduler env off）
 3. stop all old 19000 agents（taskkill 小高AI微信助手.exe）
 4. verify OLD_AGENT_ACTIVE_COUNT = 0（tasklist 确认）
 5. inspect outstanding tasks（SELECT status GROUP BY，见 §12）
 6. verify running=0 / no in-flight old execution（§13/§16/§17 drain）
 7. backup / rollback checkpoint（DB 快照 + 代码回滚点）
 8. apply Alembic 0035（0034 → 0035，additive）
 9. deploy new 9000（image/tag = REQUIRES_PRODUCTION_VERIFICATION）
10. health/readiness check（/ready HTTP 200 + alembic current=0035）
11. deploy/start new 19000（新 exe，见 §22）
12. protocol smoke（见 §29）
13. controlled fake/test task validation
14. resume poll（新 agent 开始 claim）
15. resume notify_sales creation（撤反代 503 + webhook 恢复 + scheduler env）
16. post-cutover monitoring（uncertain 计数 / 409 率 / lease 过期率）
```

实际顺序须根据 §4 production reality 最终确认。

---

## 20. Migration vs Server Order

old server against schema 0035 短时间是否兼容？

```text
0035 = additive nullable columns + server_default + 1 index
old server ORM 未映射新 4 列 → SELECT 仅取已映射列 → 新列被忽略（读安全）
old server INSERT notify_sales → 仅写已映射列 → 新列取 default（claim_token_hash NULL / attempt_count 0 / lease NULL / claimed_by NULL）（写安全）
```

```text
BACKWARD_SCHEMA_COMPATIBLE = VERIFIED（代码级静态确认：additive nullable，old ORM 不引用新列）
```

反之 **new server against old schema = NOT compatible**（new server `claim_notify_sales_task` 引用 `claim_token_hash`/`lease_expires_at`/`attempt_count`/`claimed_by` 列，旧 schema 无这些列 → SQL 错误）。因此部署顺序必须为 **先 apply 0035 → 再上 new server**（§19 step 8 → 9）。step 8（migration）与 step 9（new server）之间，old schema 已升 0035 但 old server 仍在跑 = 短暂 backward-compatible 窗口，可接受。

---

## 21. New Server Before New Agent

R2：new server + old agent 不得承载 active traffic。

```text
若 9000 先升级（step 9）：
  必须保证 step 3-4 已完成（all old agents stopped）
  且 poll 仍 paused（无新 agent 接入）
  直到新 19000 ready（step 11）
```

否则触发 §18 new+old 矩阵的 409→uncertain 风暴。

---

## 22. New Agent Package Readiness

19000 构建流程存在且完整：

```text
entry      = app/local_agent_main.py
spec       = 小高AI微信助手.spec（生产 EXE pyinstaller spec）
build ps1  = scripts/build_local_agent_exe.ps1
产物名     = 小高AI微信助手.exe
build_info = app/local_agent_build_info.py（构建时自动写入 BUILD_VERSION/BUILD_TIME/GIT_COMMIT）
checksum   = build 脚本末尾 Get-FileHash SHA256 输出 ✅
smoke      = build 脚本自带 /health + /agent/version smoke ✅
默认 server = https://callback.misanduo.com（build -ServerUrl 默认值，生产可覆盖）
```

**旧产物核实**（`dist/local-agent/小高AI微信助手.exe`，Jul 13 构建）：

```text
app/local_agent_build_info.py:
  BUILD_VERSION = "P0-LOCAL-AGENT-EXE-1"
  BUILD_TIME    = "2026-07-13 18:48:25"
  GIT_COMMIT    = "cd09c37"   ← 旧 commit，不含 P2-M04 claim_token 协议
```

旧 exe `GIT_COMMIT=cd09c37`（2026-07-13）**早于 P2 closure commit `36fe68a`**，poll 时不提取 `claim_token`、callback 不回传 token → 与 new server 不兼容（§18 new+old=NO 的实测依据）。

新 EXE 未构建：

```text
NEW_AGENT_ARTIFACT_BUILT     = NOT DONE
NEW_AGENT_SOURCE_COMMIT      = 36fe68a（待构建）
NEW_AGENT_BUILD_VERSION      = REQUIRES_BUILD
NEW_AGENT_CHECKSUM           = REQUIRES_BUILD（流程支持 SHA256 输出）
```

→ **BLOCKER-B3**：上线前必须先构建并产出对应 `36fe68a` 的新 EXE，记录 BUILD_TIME/GIT_COMMIT/SHA256。

构建流程本身已就绪（spec + ps1 + smoke + checksum 全具备），阻断点只是"执行构建"这一动作未做。

---

## 23. Server Package Readiness

```text
NEW_SERVER_IMAGE_TAG         = REQUIRES_PRODUCTION_VERIFICATION
NEW_SERVER_SOURCE_COMMIT     = 36fe68a
NEW_SERVER_MIGRATION_VERSION = 0035
NEW_SERVER_ENV_CONFIG        = REQUIRES_PRODUCTION_VERIFICATION
```

9000 部署形态（Docker / 直跑）需生产侧确认。

---

## 24. Lease Configuration

```text
DEFAULT_LEASE_SECONDS = 300（app/services/wechat_task_service.py:39，代码常量）
```

`DEFAULT_LEASE_SECONDS` 是**硬编码常量，非 env 可配置**。生产不会意外配置成 30/60/120，除非改代码。

```text
LEASE_CONFIG = VERIFIED = 300s
NO_HEARTBEAT = VERIFIED
LEASE_TIME_SOURCE = DB/server datetime.now(timezone.utc)（不依赖 Windows 时钟）
```

---

## 25. DB Time

lease 正确性依赖 PostgreSQL 时钟（`datetime.now(timezone.utc)` 由 9000 server 进程生成，写入 DB），Agent 本地时间不参与 lease 计算。

```text
验证：SELECT now()（生产 PG）与 9000 服务器时间无重大异常
```

**REQUIRES_PRODUCTION_VERIFICATION**。

---

## 26. Manual Resolution Operational Readiness

Candidate C 引入 uncertain，生产上线前必须确认运维可操作。审批冻结的 3 个动作及 API：

| 动作 | 路由 | 鉴权 | 权限 | 商户隔离 | 审计 |
|---|---|---|---|---|---|
| mark_sent | `POST /wechat-tasks/{task_id}/resolve?action=mark_sent` | human user（`get_request_context_required`）| `auto_wechat:agent` | `get_agent_task` JOIN 隔离 | raw_result + failure_stage |
| retry | `POST /wechat-tasks/{task_id}/resolve?action=retry` | 同上 | 同上 | 同上 | 同上 |
| cancel | `POST /wechat-tasks/{task_id}/resolve?action=cancel` | 同上 | 同上 | 同上 | 同上 |

路由已注册（main.py:133 `wechat_tasks.router`，prefix `/wechat-tasks`）。`POST /reclaim-stale` 不被 `/{task_id}/resolve` 遮蔽（路径段数不同）。

```text
MANUAL_RESOLUTION_API = CODE_VERIFIED
MANUAL_RESOLUTION_ROUTE = /wechat-tasks/{task_id}/resolve（人类用户鉴权，非 Local Agent token）
MANUAL_RESOLUTION_PERMISSION = auto_wechat:agent
MANUAL_RESOLUTION_MERCHANT_ISOLATION = VERIFIED（get_agent_task JOIN）
MANUAL_RESOLUTION_AUDIT = VERIFIED（raw_result JSON + failure_stage）
```

→ 代码级可操作。生产操作可达性（运维是否知道如何调用）见 §27/§28。

---

## 27. Manual Resolution Runbook

**mark_sent**：操作者确认外部已发送（非系统 receipt），uncertain → sent。用于"已确认发送但系统无 receipt"。不宣称系统取得 external send receipt。

**retry**：uncertain → pending，新 claim 产生 attempt_count+1 + 新 token + 新 lease。**可能重复发送**——风险由人工承担。resolution API 不直接执行微信发送，仅重新入队。不得让一线人员随便对 uncertain 点 retry。

**cancel**：uncertain → cancelled。明确放弃该次发送。

```text
RUNBOOK = DEFINED
OPERATOR_TRAINING = REQUIRES_PRODUCTION_CONFIRMATION
```

---

## 28. Operator Authorization

```text
权限 = auto_wechat:agent（复用现有权限体系，C31）
```

按当前权限体系确定角色，不扩大权限。谁有权执行 uncertain resolution 由生产 RBAC 配置决定。**REQUIRES_PRODUCTION_VERIFICATION**（哪些用户/角色实际持有 `auto_wechat:agent`）。

---

## 29. MUTATING_GET_PROTOCOL_DEBT

```text
MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE
```

GET /pending → claim + DB mutation，违反 HTTP GET "safe" 语义。当前内网 Local Agent 协议已有此约定。上线前必须确认该 GET：

- no HTTP cache
- no CDN
- no browser prefetch
- no generic retry proxy causing unexpected claim

若生产链路存在缓存 → RELEASE_BLOCKER。→ 见 §30。future 可改 POST /claim。

---

## 30. Reverse Proxy Review

9000 前的反向代理（Nginx / 宝塔）对 `GET /wechat-tasks/pending`（mutating GET）：

- 是否 cache GET 响应
- 是否 retry upstream
- 是否有奇怪 GET 缓存规则

**只读核实结果（2026-08-12）**：

```text
两实例各有反代：
  callback.misanduo.com → SQLite 实例（/ready /health /wechat-tasks/pending 401 均可达）
  merchant.xiaogaoai.cn/api → PG 实例（/api/ready /api/health /api/wechat-tasks/pending 401 均可达）
```

WebFetch 无法读响应头（Cache-Control / Expires / X-Cache），无法从 body 核实缓存行为。
但能确认：两域的 `/wechat-tasks/pending` 路由均**可达且鉴权生效**（401 非 404），mutating GET 端点暴露在反代后。

**REQUIRES_PRODUCTION_VERIFICATION**（代理配置只读核实）—— 仍需生产侧确认两域反代对 `GET /wechat-tasks/pending` 的 cache/retry 规则。→ **BLOCKER-B4** 保持。

额外风险：**双实例 = 双反代**。cutover 时两域反代规则都需核实，且须确认 agent 实际 poll 的域（§4 REQUIRES_USER_CONFIRMATION）对应的反代规则。

---

## 31. Result Callback Retry Behavior

19000 callback HTTP 失败时：

```text
应：retry same task_id + same claim_token + same result（正确）
不得：重新 poll 并重新执行微信动作作为 callback 失败恢复
```

代码级：`_write_back_task_result`（local_agent_main.py）携带 `claim_token`（C35/C36），callback 重试复用同 token。duplicate same-attempt callback → idempotent replay（C5-B）。✅

需确认 19000 实际 retry 逻辑不会触发"重新 poll + 重新执行"。**REQUIRES_19000_BEHAVIOR_CONFIRMATION**（属 §22 新 EXE 验证范围）。

---

## 32. Smoke Test Plan

production readiness smoke 优先（不真实客户）：

```text
1. protocol/API smoke：新 agent poll → 收到 claim_token → callback 带 token → sent（test/isolated 账号）
2. isolated/test account
3. fake/no-side-effect mode（若生产无完全无副作用测试方式，仅设计 smoke，不在本窗口实发）
```

```text
SMOKE_PLAN = READY（设计级）
SMOKE_EXECUTION = NOT IN THIS WINDOW（不发送真实微信）
```

---

## 33. Post-Cutover First Task

未来真实 cutover 时，首个真实 notify_sales 建议 controlled operator observation。属未来 release execution，不是本窗口执行。记录步骤即可。

---

## 34. Rollback Triggers

明确回滚条件（任一触发即评估回滚）：

```text
- new agent cannot poll
- claim_token missing（协议字段缺失）
- callbacks consistently 409
- unexpected uncertain spike（uncertain 异常激增）
- tasks stuck running（running 长期不流转）
- merchant isolation anomaly
- migration/API startup failure
```

不得用"发现问题就回滚"模糊口径。

---

## 35. Code Rollback

0035 是 additive（nullable 列 + index）。优先方案：

```text
rollback server/agent code → 旧版本
leave 0035 columns in place（不 drop）
```

old server ORM 不引用新列 → 与 0035 schema 兼容（§20 BACKWARD_SCHEMA_COMPATIBLE = VERIFIED）。因此：

```text
CODE_ROLLBACK_WITH_SCHEMA_FORWARD = SAFE（代码级静态确认）
```

通常比即时 Alembic downgrade 安全。

---

## 36. Migration Downgrade

只有确有需要才执行 `alembic downgrade 0034`（drop 4 列 + index）。

```text
不得把生产回滚默认设计为立刻 drop 0035 columns
原因：可能已有新协议产生的运行数据（claim_token_hash / attempt_count / lease）
```

优先 §35 code rollback（保留 schema forward）。

---

## 37. Rollback 时 Running Tasks

新版本已产生 `running` + `claim_token_hash` + `lease` 后决定回滚旧版本 = 危险状态。

```text
必须：
  1. 停止 agent
  2. inspect running（SELECT WHERE task_type=notify_sales AND status=running）
  3. resolve/quarantine（manual mark_sent/retry/cancel，或人工接管）
  4. 然后回滚
不得：让旧 server 直接把 running 当普通任务忽略/误处理（旧协议无 running 中间态，旧 server 不识别 running notify_sales 语义）
```

→ rollback hard gate。

---

## 38. Rollback 时 Uncertain Tasks

```text
uncertain 不能在旧 producer 看不到该状态的情况下直接恢复旧系统正常流量
必须：先人工处理 uncertain 或保持新 dedup 逻辑
```

旧 producer 的 `ACTIVE_NOTIFY_TASK_STATUSES` 不含 uncertain → 旧系统会为同一 lead 重新创建 notify_sales → 可能重复发送。这是 rollback hard gate。

```text
ROLLBACK_UNCERTAIN_SAFETY = REQUIRES_MANUAL_RESOLUTION_BEFORE_ROLLBACK
```

---

## 39. Cutover Preflight Checklist

```text
[~] production baseline verified                                  — ⚠️ 部分核实（§4）：双实例 callback=SQLite/0033 + merchant=PG/0028，0028≠0034
[~] old server version identified                                 — ⚠️ 部分核实（§4/§22）：merchant PG 代码 head=0028；旧 exe GIT_COMMIT=cd09c37
[ ] old agent version identified                                  — REQUIRES_PROD_VERIFICATION（旧 exe cd09c37，但生产部署版本未确认）
[ ] production topology clarified                                — ❌ 双实例归属/agent 实际 server_url 未确认 BLOCKER-B6
[✅] P2 closure commit identified                                  — 36fe68a（§1）
[✅] migration 0035 ready                                           — ✅（§5）
[ ] production schema baseline = 0034                             — ❌ merchant PG=0028 BLOCKER-B7（§6）
[ ] backup/rollback point ready                                   — REQUIRES_PROD_VERIFICATION
[ ] notify_sales creation pause mechanism verified                — ⚠️ 无 feature flag（§8）BLOCKER-B1
[ ] old agent stop procedure verified                             — REQUIRES_PROD_VERIFICATION（§10）BLOCKER-B2
[ ] all old agents stoppable                                      — REQUIRES_PROD_VERIFICATION（§11）
[~] outstanding query prepared                                    — ✅ SQL 就绪（§12），但目标实例待定（PG 还是 SQLite？）
[~] running=0 precondition defined                                — ✅（§13），目标实例待定
[ ] new 9000 artifact ready                                       — ⚠️ commit 36fe68a，image 待构建/确认（§23）
[ ] new 19000 artifact ready                                      — ❌ 未构建（§22）BLOCKER-B3
[✅] lease config verified                                         — ✅ 300s 常量（§24）
[ ] reverse proxy no-cache verified                               — REQUIRES_PROD_VERIFICATION（§30）BLOCKER-B4（双实例双反代）
[✅] manual uncertain resolution operational                      — ✅ 代码级（§26），运维可达性待确认（§27/§28）
[✅] smoke plan ready                                              — ✅ 设计级（§32）
[✅] rollback triggers defined                                     — ✅（§34）
[✅] rollback procedure ready                                      — ✅ 代码级（§35-38），uncertain/running 回滚需人工前置
[✅] schema/code compatibility verified                            — ✅（§20）
[✅] protocol matrix frozen                                        — ✅（§18）
[ ] DB time verified                                              — REQUIRES_PROD_VERIFICATION（§25）
```

---

## 40. Blockers

```text
B1  CREATION_PAUSE_NO_FEATURE_FLAG
    notify_sales 创建路径（send-to-staff / webhook 回访）无代码级 feature flag / maintenance switch；
    emergency_stop 不守创建路径。仅靠运维通告 + 反代 503 + scheduler env off + webhook 摄入暂停。
    需生产侧确认反代可控 send-to-staff 503 且 webhook 摄入可暂停，否则 RELEASE_BLOCKER。

B2  OLD_AGENT_STOP_UNVERIFIABLE
    Local Agent 部署在客户/操作员 Windows 机，本窗口无法核实 OLD_AGENT_ACTIVE_COUNT=0；
    无 19000 可查询 in-flight 状态接口。需生产/现场确认流程。

B3  NEW_AGENT_ARTIFACT_NOT_BUILT
    19000 EXE（小高AI微信助手.exe）对应 36fe68a 的构建未执行，无 artifact identity/version/checksum。
    构建流程存在且就绪（spec + build_local_agent_exe.ps1 + smoke + checksum），但产物未产出。

B4  REVERSE_PROXY_CACHE_UNVERIFIED
    生产 nginx/宝塔 对 GET /wechat-tasks/pending 的 cache/retry 规则未核实（WebFetch 无法读响应头）。
    mutating GET 若被缓存/重试 → 重复 claim 风险。需只读配置核实。双实例 = 双反代，两域都需核实。

B5  PRODUCTION_BASELINE_PARTIALLY_VERIFIED
    经只读 HTTP 核实：merchant PG 实例 alembic=0028（代码 head 与 DB 均 0028），旧 exe=cd09c37。
    待核实：生产 agent 实际连哪个域、agent count、outstanding tasks、in-flight 旧 callback。
    核实手段：/ready 已用（alembic 可读）；outstanding tasks 需 DB 只读访问。

★ B6  PRODUCTION_TOPOLOGY_DUAL_INSTANCE_UNCLARIFIED（新增，最高优先级）
    生产存在两套 9000 实例：
      callback.misanduo.com → SQLite / dev_non_pg / schema 0033（CLAUDE.md 硬约束 #2 禁止 SQLite 生产）
      merchant.xiaogaoai.cn  → PostgreSQL / auto_wechat / schema 0028
    notify_sales 业务承载实例 / agent 实际 server_url / callback SQLite 实例角色 均未确认。
    无法从只读 HTTP 推断 agent 连哪个域（取决于销售电脑 exe 的 AUTO_WECHAT_SERVER_URL）。
    REQUIRES_USER_CONFIRMATION：必须厘清哪个实例是 cutover 目标，另一个如何处置。

★ B7  PRODUCTION_SCHEMA_BEHIND_BASELINE（新增）
    merchant PG 实例 schema=0028，落后本地 P2 pre-0035 baseline（0034）6 个 revision。
    不能直接上 0035；须先独立补齐 0028→0034（含 0030 compute core / 0032 daily_report /
    0033 material / 0034 preview），且生产部署代码也停在 0028（expected=0028），
    意味着 P1 compute idempotency 等已完成的工作生产尚未部署。
    这超出 P2-M04 单一 migration 范围，需独立 schema 补齐审批。
```

---

## 41. Non-Blocking Notes

```text
N1  MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE（§29；当前内网协议安全，future 可改 POST /claim）
    注意：与 B4 交叉——若生产链路存在 cache/prefetch 则升级为 BLOCKER。

N2  C-RECLAIM-NAME：reclaim_expired_claims 函数名过度（实际是 stale quarantine），docstring 已纠正语义；
    保留命名，未来可改名。

N3  CALLBACK_ROW_LOCK_ORDER = VERIFIED（WechatTask → LeadNotification 单向，无 cycle）。

N4  WEBHOOK_RETURN_VISIT_RESIDUAL：replies.py webhook 触发的回访 notify_sales 创建路径无 env 开关，
    cutover 期间需暂停 webhook 摄入或接受低残留风险（与 B1 关联）。

N5  NEW_SERVER_ARTIFACT：9000 image/tag 待生产侧确认（§23），非代码阻断。

N6  B1 OPERATIONAL_PAUSE_FEASIBILITY（裁定）：
    生产不存在代码级 notify_sales creation pause 开关，且 emergency_stop 不守创建路径。
    可行的 operational pause 手段（无新代码）：
      (a) 反代 503 POST /lead-notifications/send-to-staff（硬阻断 manual 创建）
      (b) 9000 重启时 RETURN_VISIT_SILENT_SCAN_ENABLED / AI_AUTO_REPLY_OUTBOX_ENABLED 不设（阻断 scheduler 创建）
      (c) 暂停 webhook 摄入或反代 503 webhook 端点（阻断 replies.py 触发创建）
    残留风险：(c) 之外无单一代码开关覆盖 webhook 回访路径。
    裁定：B1 = FEASIBLE_ONLY_WITH_OPERATIONAL_CONTROLS（反代 503 + webhook 暂停），
          不具备 feature-flag 级安全；须用户确认生产反代/webhook 可控后才算解除。
    与 B6 关联：双实例下 pause 须覆盖承载 notify_sales 的那个实例（及对应反代）。
```

---

## 42. Verdict

```text
CUTOVER_NOT_READY
```

理由：代码与 migration 设计/实施已闭环（P2 M04 CLAIM/LEASE = REMEDIATED），但一次安全 coordinated production cutover 的生产侧前置条件未满足/未核实。

**2026-08-12 只读核实新发现两项最高优先级 blocker**：

- ★ B6 生产双实例拓扑未厘清（callback=SQLite/0033 + merchant=PG/0028，notify_sales 业务归属与 agent 实际 server_url 未确认）
- ★ B7 生产 PG schema 落后 baseline（0028 ≠ 0034，需独立补齐）

加上既有 5 项：

- B1 创建暂停无代码级开关（仅运维手段）
- B2 旧 agent 停止不可从本窗口核实
- B3 新 19000 EXE 未构建
- B4 反向代理 cache 未核实（双实例双反代）
- B5 生产 baseline 部分核实（alembic 可读，outstanding tasks 待 DB 只读访问）

按 §1 硬约束"如果发现 release blocker：RELEASE_NOT_READY，然后停止。不得现场改代码解决后继续自批"——本窗口发现上述 blocker，**停止**，不在本窗口改代码解决。

**解除 B6 需用户确认**（无法从只读 HTTP 推断），解除 B7 需独立 schema 补齐审批——两者均超出本 Release Gate 只读核实窗口能力。

---

## 43. Production Cutover Authorization Required

即使 blocker 全部解除、Verdict 转 `CUTOVER_READY`：

```text
P2 M04 CLAIM/LEASE = REMEDIATED（保持）
P2_M04_PRODUCTION_CUTOVER = READY / NOT_EXECUTED（待 blocker 解除后授予）
```

不得写 `PRODUCTION_VERIFIED`。production coordinated cutover 须由独立 production authorization 批准后执行。

---

## 44. Candidate Diff / Git Discipline

```text
本窗口新增产物 = docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md（仅此一份）
DO NOT COMMIT
DO NOT PUSH
```

未改任何业务代码、migration、Local Agent。closure commit `36fe68a` 为唯一代码 baseline（已 commit，未 push）。

---

## 45. STOP

本窗口完成后停止。不得自行：

- production alembic upgrade 0035
- deploy 9000
- build/替换正式 19000 EXE
- stop 生产 agent
- pause 正式业务
- 发送真实微信
- push
- 进入 P3a
- RB-10
