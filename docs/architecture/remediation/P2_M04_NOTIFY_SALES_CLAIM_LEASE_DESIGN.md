# P2-M04 notify_sales 执行所有权 / Claim-Lease / Crash Recovery 技术设计

> 任务：`P2-M04-NOTIFY-SALES-CLAIM-LEASE-DESIGN`
> 前序：`P2_M04_CLAIM_LEASE_REALITY_EXPLORATION.md`（`P2_RISK_CONFIRMED_DESIGN_REQUIRED`）
> Governance baseline：`1d7f1f5`（P1 COMPUTE-IDEMPOTENCY-001 = CLOSED）
> 日期：2026-08-12
> 窗口性质：**DESIGN ONLY**（不实施业务代码、不执行 migration、不写 DB、不改 Local Agent、不 commit、不 push）
> Source of Truth：本窗口独立只读代码事实（notify_sales 链 / submit_result / 同仓 claim 模式 / 19000 协议）> 探索报告 > 推测

---

## 0. Verdict 速览

| 维度 | 结论 |
|---|---|
| 活跃风险面 | notify_sales single_send（真实微信发送，UIA fire-and-forget 无 receipt）|
| P2-F1 NO_CLAIM | `get_pending_wechat_tasks` 纯 SELECT，task 执行期间恒 pending，多 Agent 可同时拉同 task |
| P2-F2 无 lease/crash recovery | 无 lease 字段、无 timeout reset、crash 后隐式重拉重发 |
| P2-F3 外部副作用不可幂等 | 微信 UIA 无 receipt/message ID，exactly-once external send = IMPOSSIBLE |
| Preferred Strategy | **Candidate C — Claim + Lease + Attempt Token + Uncertainty State** |
| 保证边界 | At-most-one active executor + leased pre-side-effect recovery + NO blind retry after uncertain side effect |
| 新状态 | 复用 `running`（赋 durable owner 语义）+ 新增 `uncertain`（副作用结果未知）|
| 新字段/migration | 最小 additive migration（claim_token_hash / lease_expires_at / attempt_count / claimed_by）|
| 19000 协议改动 | 必需（poll 返回 claim_token + result 回写带 token）；需协调发布 |
| 本窗口实施 | NO |

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

---

## 1. Governance Baseline

```text
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（commit 1d7f1f5，保持不动）
TECHNICAL_CLOSURE = VERIFIED
P2 M04 CLAIM/LEASE = DESIGN_IN_PROGRESS
P2-F1 / P2-F2 / P2-F3 = OPEN
```

P1↔P2 边界（§27）：P1 只保证同 Business Event Identity → compute billing 不重复；不解决 M04 任务执行 exactly-once，不解决外部微信副作用重复。P1 不重新打开。

---

## 2. Reality Exploration Findings（冻结，§1）

探索 verdict `P2_RISK_CONFIRMED_DESIGN_REQUIRED`。冻结事实：

- **ACTIVE 路径**：`notify_sales`（mode=single_send）是唯一 ACTIVE 真实微信发送 WechatTask 路径。
- **detect_reply**：read_only，无外部副作用。本轮 OUT OF SCOPE（§58）。
- **send_report_attachment**：已有 ATOMIC_CLAIM（`claim_delivery_task`），但整条链 DORMANT（retry_delivery/reclaim_stale_leases 生产 caller=0）。本轮 REFERENCE ONLY（§59）。
- **Generic WechatTask creation**：`POST /wechat-tasks` = 410，抖音自动创建 = disabled。不重新作为 P2 入口。

---

## 3. Scope

```text
IN SCOPE:  notify_sales single_send 的 execution ownership / claim / lease / attempt / crash recovery / uncertainty
OUT OF SCOPE: detect_reply 行为变更（§58）、send_report_attachment 激活（§59）、merchant_id ORM 漂移修复（§57/P2-F6）、Redis lock、RB-10
```

---

## 4. Active Risk Surface

```text
notify_sales single_send:
  producer: POST /lead-notifications/send-to-staff → create_wechat_task(status=pending, mode=single_send)
  consumer: 19000 GET /wechat-tasks/pending?task_type=notify_sales → 拿 task（无 claim）→ UIA Ctrl+V + Enter → POST /result
  risk: 多 Agent 同 task 重复发送（P2-F1）+ crash 后重拉重发（P2-F2）+ 外部不可幂等（P2-F3）
```

---

## 5. Current notify_sales Flow（独立重建，§5）

```text
[producer] app/routers/lead_notification_actions.py:42 POST /lead-notifications/send-to-staff
  → 鉴权（RequestContext）+ evaluate_lead_wechat_notify_eligibility（前置去重）
  → create_wechat_task(task_type=notify_sales, mode=single_send, status=pending)
    wechat_task_service.py:74-97: db.add + db.commit（durable，初始 pending）
    ★ 不填 merchant_id/tenant_id（P2-F6 漂移，§57）
          ↓

[fetch] 19000 GET /wechat-tasks/pending?task_type=notify_sales&limit=1
  → wechat_tasks.py 路由（token 鉴权 + merchant 隔离）
  → get_pending_wechat_tasks（wechat_task_service.py:100-132）
    ★ 纯 SELECT: query.filter(status=="pending").order_by(id).limit(limit).all()
    ★ 无 FOR UPDATE、无 status 修改、无 commit、无 claim_token
    ★ merchant 隔离: JOIN lead+staff 双重过滤（:122-130）
  → 返回 task（status 仍 pending，任何其他 Agent 仍可拉到）
    status before: pending | status after: pending（无转换）
          ↓

[execute] 19000 Local Agent UIA
  → _wechat_task_lock.acquire(blocking=False)（local_agent_main.py:1898，PROCESS_LOCAL_GUARD）
  → input_writer.py:423 SendKeys("{Ctrl}v") + :477 SendKeys("{Enter}")
  ★ fire-and-forget，无 external receipt / message ID
  ★ 跨进程 _wechat_task_lock 无效
    transaction boundary: 无 DB 事务（UIA 自动化，可耗时数分钟）
          ↓

[callback] 19000 POST /wechat-tasks/{task_id}/result
  → wechat_tasks.py 路由（token 鉴权）
  → submit_wechat_task_result（wechat_task_service.py:302-474）
    ★ db.query(WechatTask).filter(id==task_id)（无 status 当前值校验，无 CAS）
    ★ 直接赋值 status（pasted/sent/blocked/failed）
    ★ agent_hostname/agent_pid 回写时填（:351-352，事后审计）
    ★ 无 ownership/claim_token 校验
    → db.commit()（:373/454/...，commit AFTER 外部执行）
    status before: pending | status after: pasted/sent/blocked/failed
```

**durable DB commit 发生在**：producer create（初始 pending）+ callback submit_result（终态）。**执行期间无任何 commit**（task 恒 pending）。

---

## 6. Current State Machine（§7）

notify_sales（wechat_task_service.py:370-474）：
```text
pending ──(pasted=true,sent=false,verified=true)──→ pasted         [:~440]
pending ──(sent=true,verified=true,single_send)──→ sent            [:~454]
pending ──(verified=false)──→ blocked [verified_false_blocked]
pending ──(partial_match)──→ blocked [partial_match_blocked]         [:384]
pending ──(manual_review_required)──→ blocked                        [:394]
pending ──(paste_only+sent=true)──→ blocked [task_mode_send_mismatch]
pending ──(success=false)──→ failed [failure_stage]                   [:370]
pending ──(unhandled)──→ blocked [unhandled_result_combination]
```

- `running` 状态：models.py:307 注释列出，**全代码库无任何位置写入**（create_wechat_task 直接 pending，submit_wechat_task_result 一次性写终态）。从未使用。
- **无 pending→running 转换**：执行期间 status 恒 pending。

---

## 7. Current Transaction Boundaries（§5 详）

```text
1. create_wechat_task: db.add + db.commit（producer，durable，BEFORE 任何执行）
2. get_pending_wechat_tasks: 纯 SELECT（无事务、无 commit、status 不变）
3. UIA execute: 无 DB 事务（task 恒 pending）
4. submit_wechat_task_result: db.commit AFTER 外部执行（终态）
```

**★ DB commit AFTER external execution。无 claim 事务 BEFORE 外部执行。** Agent 在外部执行后、回写前崩溃 → task 卡 pending → 被另一 Agent 重拉重发（P2-F2/R3）。

---

## 8-10. P2-F1 / P2-F2 / P2-F3（冻结）

**P2-F1 No Durable Claim**：`get_pending_wechat_tasks` 纯 SELECT，无 pending→running，服务端并发 GET 可获同一 task。task 执行期间 status 恒 pending。

**P2-F2 No Lease / Crash Recovery**：无 claim owner / lease expiry / heartbeat / attempt ownership / stale claim recovery。无法区分 still executing / crashed / partition / agent restart / old worker alive。

**P2-F3 External Side Effect Not Exactly-Once**：notify_sales single_send 的 Enter 发送是 UIA fire-and-forget，无 external receipt / message ID。冻结：
```text
TRUE EXACTLY-ONCE EXTERNAL WECHAT SEND = NOT ACHIEVABLE WITH CURRENT EXTERNAL CONTRACT
```
不得虚假承诺 exactly-once 微信发送。

---

## 11. Exact Guarantee Boundary（§4/§64）

区分（§4）：
- A. Exactly-once task claim — **可达成**（原子 CAS）
- B. At-most-one active executor — **可达成**（claim + lease）
- C. At-most-once external send — **部分可达成**（claim 防并发同 task，但 crash 后不确定性残留）
- D. Exactly-once external send — **IMPOSSIBLE**（UIA 无 receipt）
- E. Recoverable task execution — **部分可达成**（crash before side effect 可恢复；crash after side effect 进 uncertain）

**Preferred 提供保证**（§64）：
```text
SERVER-SIDE: At most one valid active attempt per notify_sales task.
LEASE: Stale pre-side-effect attempts can be recovered.
CALLBACK: Only current attempt may transition task terminal state.
EXTERNAL WECHAT: Exactly-once delivery is NOT guaranteed.
UNCERTAINTY: Potentially executed but unacknowledged send is not blindly auto-retried.
```

---

## 12-16. Candidate A-E

### Candidate A — Minimal Atomic Claim Only（§35）

```text
pending → atomic CAS running → execute → terminal
无 lease。
```

- 优势：最小，解决并发 poll 同 task。
- 缺点：**crash → running forever**（无 lease expiry，task 永远 running，无法恢复）。
- 不解决 P2-F2。

**REJECTED**（不完整解决 P2-F2）。

### Candidate B — Atomic Claim + Lease（§36）

```text
pending → atomic claim → running + lease → execute → terminal
lease expired → reclaim
```

- 优势：解决 P2-F1 + P2-F2（crash before side effect 可 lease 恢复）。
- 缺点：**crash after external side effect → lease expired → blind reclaim → resend → 重复发送**（P2-F3 未解决）。

**REJECTED**（不解决 P2-F3 uncertainty）。

### Candidate C — Claim + Lease + Attempt Token + Uncertainty State（§37，PREFERRED）

```text
pending → atomic claim（claim_token_hash + lease_expires_at + attempt_count）→ running
  → execute
  → terminal（callback 校验 claim_token）

lease expired + 未达 side-effect phase → reclaim（safe retry）
lease expired + 可能已达 side-effect → uncertain（不 blind resend）
late callback（旧 attempt）→ 拒绝（claim_token 不匹配）
```

- 优势：完整覆盖 F1/F2/F3。
- 风险：schema/API 变化更大。
- **PREFERRED**（§17 详）。

### Candidate D — Redis / Distributed Lock（§38）

- 无强理由：DB 已有 durable task state，Redis 引入双状态同步风险。
- **REJECTED**。

### Candidate E — SELECT FOR UPDATE / SKIP LOCKED（§39）

- DB 事务不能跨外部微信执行保持。只能用于 claim 瞬间。
- 不能持锁直到 UIA 完成（长事务禁止）。
- **REJECTED**（作为 claim 机制；claim 用原子 UPDATE 更优，§34 参考）。

---

## 13. Candidate Matrix（§40/§71）

| Candidate | Double-Poll | Crash Recovery | Late Callback | External Uncertainty | API Change | Migration | Complexity | Verdict |
|---|---|---|---|---|---|---|---|---|
| A atomic claim only | ✅ 解决 | ❌ running forever | ❌ | ❌ | 小 | 小 | 低 | REJECTED |
| B claim + lease | ✅ | ✅ pre-side-effect | ❌ | ❌ blind resend | 中 | 中 | 中 | REJECTED |
| **C claim+lease+token+uncertain** | ✅ | ✅ pre-side-effect | ✅ token reject | ✅ uncertain | 中-大 | 中 | 中-高 | **PREFERRED** |
| D Redis lock | ✅ | ✅ | ✅ | ❌ | 大 | — | 高 | REJECTED |
| E SELECT FOR UPDATE | ✅ | ❌ 长事务 | ❌ | ❌ | 大 | — | 高 | REJECTED |

---

## 14. Preferred Strategy（§41）

```text
PREFERRED = Candidate C
  atomic claim（UPDATE WHERE status=pending + claim_token_hash + lease_expires_at + attempt_count）
  + lease expiry recovery（pre-side-effect → safe reclaim；post-side-effect → uncertain）
  + attempt token（callback CAS：WHERE id AND claim_token_hash AND status=running）
  + uncertainty state（不 blind resend）
```

复用同仓已验证模式（§34）：
- `claim_delivery_task`（daily_report_delivery_service.py:433-469）的原子 UPDATE + rowcount + ClaimConflictError + `secrets.token_hex(32)` 存 hash。
- `authorize_send_intent`（:504-552）的 `_const_eq(token_hash, token)` callback 校验。
- ReturnVisitRun/AiAutoReplyRun 的 `lease_owner`/`lease_expires_at`/`attempt_count` 字段语义。

---

## 15. New State Machine（§7/§8）

### 复用 `running`（§7/§8）

```text
running = 不是"正在执行"模糊展示状态，而是有 durable owner + active lease 的 in-flight execution。
```

严格定义（§8）：`running` 状态行必须满足 `claim_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL AND attempt_count >= 1`。

### 新增 `uncertain`（§21）

```text
uncertain = lease expired 且副作用可能已发生但结果未知（无 receipt）。
不自动 resend，surface 人工确认。
```

### 状态机

```text
pending ──(atomic claim)──→ running [claim_token_hash, lease_expires_at, attempt_count+1]
running ──(callback success, token valid)──→ pasted / sent
running ──(callback definite failure, token valid, PRE side-effect)──→ failed [可 manual retry]
running ──(lease expired, callback 未到, side-effect 未开始)──→ pending [reclaim, attempt_count 保留, 新 attempt]
running ──(lease expired, callback 未到, side-effect 可能已开始)──→ uncertain [不 blind resend]
running ──(late callback, token 不匹配)──→ 拒绝（不改状态）
uncertain ──(manual resolve: sent)──→ sent
uncertain ──(manual resolve: not sent / retry)──→ pending [新 attempt]
```

`pasted`/`sent`/`blocked`/`failed` 语义不变（§24/§25）。

### `pasted` 特别审查（§24）

`pasted`（:440）= UIA 粘贴成功（Ctrl+V）但 single_send 模式下尚未 Enter。当前 `pasted` 是终态（pasted=true, sent=false）。**`pasted` 已产生不可逆副作用**（剪贴板写入 + 输入框粘贴，用户可见）。crash recovery 不得把 `pasted` 当"未执行"重试——若 `pasted` 已回写则不重发；若 crash 在 `pasted` 回写前则进 uncertain。

### `failed` 语义拆分（§25）

当前 `failed` 混合 definite pre-send failure / definite send failure / unknown send result。设计建议在 `failure_stage`（:309 已有字段）层区分：
- `claim_failed` / `pre_side_effect_failure`（可 auto/manual retry）
- `side_effect_unknown`（= uncertain 状态，不 retry）
- `definite_send_failure`（可 manual retry）

不新增状态列，复用 `failure_stage` + `uncertain` 状态。

---

## 16. Claim Contract（§9/§10）

### 原子 claim（§9）

```sql
UPDATE wechat_tasks
SET status = 'running',
    claim_token_hash = :token_hash,
    lease_expires_at = :now + :lease_seconds,
    attempt_count = attempt_count + 1,
    claimed_by = :agent_identity,
    execution_started_at = :now
WHERE id = :task_id
  AND status = 'pending'
RETURNING id, attempt_count, ...
```

- `affected rows = 1` → claim winner
- `affected rows = 0` → claim conflict / no task → ClaimConflictError（409）

不得 `SELECT pending → later UPDATE running`（§9 禁止）。

### Claim 与 Fetch 合同（§10）

```text
claim commit BEFORE task is handed to Local Agent for execution.
```

Preferred 方案：poll 端点内部 `find + atomic claim` → 返回 claimed task（含明文 claim_token）。19000 拿到 task 时，ownership 已 durable committed（§11 API-A）。

---

## 17. Claim Owner（§12）

```text
owner identity = claimed_by（agent_instance_id / device_id）
+ claim_token（每 attempt 唯一，不可预测）
```

不得仅用 `merchant_id`（不能区分旧 agent 实例与新实例）。`claimed_by` = agent hostname + pid（已有 `agent_hostname`/`agent_pid` 字段，但改为 claim 时填而非回写时）。`claim_token` = `secrets.token_hex(32)`（同仓模式，只存 hash）。

---

## 18. Attempt Identity（§13）

```text
task_id = stable business task（WechatTask.id，不变）
attempt_id = claim_token_hash + attempt_count（每次 claim/reclaim 新 attempt）
```

retry/reclaim → same task_id → new attempt_id（new claim_token, attempt_count+1）。必要：区分"第 N 次执行"，防 late callback 覆盖新 attempt（§14/§23）。

---

## 19. Claim Token（§14）

```text
claim_token = secrets.token_hex(32)（随机、不可预测、每 attempt 唯一）
存储 = claim_token_hash（SHA-256，只存 hash，同仓 _hash_token 模式）
```

terminal callback 必须带 `task_id + claim_token`。服务端校验：
```sql
WHERE id = :task_id AND claim_token_hash = :token_hash AND status = 'running'
```
防旧 worker late callback 覆盖新 attempt（§23/§48）。

---

## 20. Lease Fields（§15）

现有字段（models.py:290-336）：`agent_hostname`/`agent_pid`（事后审计）、`execution_started_at`（:321，附件专用但可复用语义）、`raw_result`（:310）。

**拟新增字段**（每字段回答"为何不可由现有表达"）：

| 字段 | 为何需要 | 为何现有不足 |
|---|---|---|
| `claim_token_hash` String(64) | callback ownership CAS | 现有无任何 token；`agent_hostname`/`agent_pid` 不可预测性不足，不可作 CAS 凭证 |
| `lease_expires_at` DateTime | lease 过期判定 | 现有无任何 lease 时间；`execution_started_at` 是开始时间非过期时间 |
| `attempt_count` Integer default 0 | 区分第 N 次执行，防 max_attempts 无限 | 现有无 attempt 计数（detect_reply 存 JSON 非原子）|
| `claimed_by` String(100) | owner identity（审计+reclaim 判定）| `agent_hostname`/`agent_pid` 当前回写时填，非 claim 时绑定 |

**不新增** `heartbeat` 字段（§18：单次 notify_sales 执行时间有上限，不需 heartbeat）。

---

## 21. Migration Decision（§16）

```text
MIGRATION = REQUIRED（additive，最小）
```

新增 4 列（§20）+ 复用 `execution_started_at`（已有）：
- `claim_token_hash` String(64) nullable
- `lease_expires_at` DateTime nullable
- `attempt_count` Integer nullable default 0
- `claimed_by` String(100) nullable

特性：
- **additive**（全 nullable/default，不破坏现有行）
- **index**：`(status, lease_expires_at)` 用于 reclaim 查询（§36/§61）；复用 DB 层已有 `idx_wechat_tasks_merchant_status_created`（但 ORM merchant_id 未映射，§57）
- **backfill**：现有 pending 行 `attempt_count=0`，`claim_token_hash=NULL`，`lease_expires_at=NULL`——兼容（首次 claim 时填）
- **existing pending rows compatibility**：现有 pending task 可被新 claim 逻辑认领（attempt 1）
- **rollback**：additive migration，code rollback 后列保留（nullable，无破坏）

本设计不实施 migration。

---

## 22. Lease Duration（§17）

```text
LEASE_SECONDS = 可配置（config 项，如 LOCAL_AGENT_NOTIFY_SALES_LEASE_SECONDS）
默认范围建议：120-300 秒
```

基于：
- 正常 UIA notify_sales 执行：Ctrl+V + Enter，通常 < 30 秒。
- 但含 foreground guard / search focus / 联系人验证 / OCR，可能 1-2 分钟。
- network round trip + machine lag：数十秒。
- 保守上限 120-300 秒，避免健康 worker 被误 reclaim。

不随意 30 秒（§17）。具体默认值由实施窗口基于真实 UIA 耗时数据定。

---

## 23. Lease Renewal / Heartbeat（§18）

```text
HEARTBEAT = NOT REQUIRED（默认）
```

判断：单次 notify_sales 执行时间有明确短上限（UIA 粘贴+发送 < 5 分钟）。若 LEASE_SECONDS 设为 300（5 分钟），健康 worker 不会超 lease。

若未来证明执行可能超 lease（如 OCR 慢 / 微信卡顿），再加 heartbeat。当前 YAGNI（§18）。

`receive_agent_heartbeat`（agent.py:23）当前不回写 wechat_tasks——保持不变（不扩 scope）。

---

## 24. Lease Expiry ≠ Safe Retry（§19，P2-F3 核心）

```text
lease expired ≠ safe to resend
```

场景：
```text
Agent A claim → UIA actually sends → crash before callback → lease expires
服务器只知道 lease expired，不知道 message sent?
```

不得 `lease expired → pending → resend`（可能重复发微信）。

**Preferred**：lease expired 时，若无法证明 side-effect 未开始 → `uncertain`（不 blind resend，§21/§29）。

---

## 25. External Side-Effect Phase Model（§20/§52/§53）

### 最小 phase 判断（不新增完整 phase callback）

利用现有 callback + lease 事实判断 4 类（§20）：

| 场景 | 判定 | 处理 |
|---|---|---|
| A. claim 后、执行前 crash | lease expired，无 callback，`execution_started_at` 后无 side-effect 信号 | safe reclaim → pending（新 attempt）|
| B. side effect 明确失败 | callback `success=false`（definite pre-send / send failure）| failed [可 retry] |
| C. side effect 明确成功 | callback `pasted/sent` | pasted/sent |
| D. side effect 可能已发生，结果未知 | lease expired，无 callback，可能已执行 | uncertain [不 resend] |

### 区分 A vs D 的挑战（§52）

若无 side-effect-start signal，无法区分 A（claim 后未执行）与 D（执行后 crash）。两种策略：

**策略 1（Preferred，最小）**：lease expired 且无 callback → 一律 `uncertain`（保守，不 blind resend）。
- 优点：最安全（绝不 blind resend）。
- 缺点：claim 后未执行就 crash 的 task 也进 uncertain（需人工 resolve 才能 retry），恢复延迟。

**策略 2（需协议改）**：19000 在 UIA 执行前 `POST attempt_started` → 服务端记录 side-effect phase。lease expired 时若 `attempt_started=false` → safe reclaim；若 `attempt_started=true` → uncertain。
- 优点：精确区分 A vs D。
- 缺点：增加协议复杂度（§52）。

**设计裁定**：**策略 1（Preferred）**——最小、最安全。策略 2 登记为 OPTIONAL HARDENING（§52 评估后若 uncertain 太频繁再考虑）。

### §52 side-effect start signal

```text
SIDE_EFFECT_START_SIGNAL = OPTIONAL HARDENING（策略 2）
```

本首批不实现。若 uncertain 积压过多，未来加 `POST attempt_started` phase callback。

---

## 26. Uncertain State（§21）

```text
uncertain = external side effect may have succeeded but system lacks receipt
→ DO NOT AUTOMATICALLY RESEND
→ surface for manual resolution
```

状态名暂定 `uncertain`（最终术语由审批裁定，§21 不预设）。manual resolution（§54）：
- `manual resolve as sent` → sent
- `manual retry`（确认未发送）→ pending（新 attempt）
- `manual cancel` → cancelled

---

## 27. At-Most-Once vs At-Least-Once（§22）

notify_sales 业务风险判断：
- **重复发送微信消息给客户**：骚扰客户，可能触发微信封禁，不可撤回。**高危害**。
- **漏发一条通知消息**：销售错过线索通知，可人工补发。**中危害，可恢复**。

→ notify_sales 更适合 **at-most-once after uncertainty**（避免重复骚扰 > 避免漏发）。

Preferred：crash after possible side effect → uncertain（不 resend）→ 人工确认是否补发。

---

## 28. Terminal Callback Ownership（§23/§47）

callback 必须属于 current attempt：
```sql
UPDATE wechat_tasks
SET status = :terminal, ...
WHERE id = :task_id
  AND claim_token_hash = :token_hash
  AND status = 'running'
```

- `affected rows = 1` → callback 属于 current attempt，接受。
- `affected rows = 0` → late callback（旧 attempt）或状态已变 → 拒绝/忽略（§48）。

---

## 29. Late Callback（§48）

```text
attempt A lease expired → attempt B reclaimed（新 token）
A late callback arrives（A token）→ WHERE claim_token_hash=A_token → 0 rows → 拒绝
B ownership remains intact.
```

P2-R4 验证（§65）。

---

## 30. Crash Before Side Effect（§50）

```text
claim acquired → crash before UIA starts → lease expired
Preferred（策略 1）：→ uncertain（保守，不假定未执行）
策略 2（OPTIONAL）：→ 若 attempt_started=false → safe reclaim
```

策略 1 下，crash-before-side-effect 也进 uncertain（人工 resolve retry）。这是"最安全"的代价。

---

## 31. Crash During/After Side Effect（§51）

```text
UIA action invoked → process disappears → 无 receipt
状态 = uncertain（不自动当 definite failure，不 blind resend）
```

人工确认是否已发送。

---

## 32. Retry Contract（§26）

| 失败类型 | 可 auto retry? | 处理 |
|---|---|---|
| PRE_SIDE_EFFECT（claim 后未执行 crash，策略 2 才能识别）| 策略 1 下 uncertain；策略 2 下 manual retry | — |
| DEFINITE_FAILURE（callback success=false, failure_stage）| manual retry（建新 attempt）| failed → manual → pending |
| SIDE_EFFECT_UNKNOWN（lease expired 无 callback）| **NO auto retry** | uncertain → manual |
| SUCCESS | — | pasted/sent |

不 auto retry 任何 uncertain 场景（§19/§26）。

---

## 33. Retry Attempt（§27）

```text
retry: same task_id, new attempt
→ attempt_count + 1, new claim_token, new lease
旧 attempt 不能改 current task（claim_token_hash 已变，旧 token CAS 失败）
```

---

## 34. Max Attempts（§28）

```text
MAX_ATTEMPTS = 可配置（如 LOCAL_AGENT_NOTIFY_SALES_MAX_ATTEMPTS，默认 3-5）
```

防 crash / definite failure → infinite reclaim。复用 `attempt_count`（§20 新增）。不新增两套计数。

---

## 35. Process-Local Guard（§29）

```text
PROCESS_LOCAL_GUARD = 保留为 defense-in-depth
```

durable DB claim = correctness；process-local guard = optional optimization。`_wechat_task_lock` 保留（同进程防重入），但不作为跨进程正确性依赖。

---

## 36. 多 Agent / 重启场景（§30/§62）

```text
Agent A old process alive + Agent B new process starts
both poll same merchant → 仅 current valid claim holder 可执行（claim_token CAS）
```

不依赖"部署约定只有一台 Agent"（§30）。claim 原子 CAS + token 校验保证多实例安全（§62）。

---

## 37. Poll Semantics（§31）

```text
poll 无可 claim 任务 → 返回空（或 204）
同一 agent 一次只 claim 一个任务（limit=1，保持当前行为）
```

不重做整套 queue 协议（§31）。

---

## 38. Scheduler（§32）

```text
UNKNOWN CONSUMER = 0（探索确认）
不新增 server worker（除非 lease recovery 需 reaper，§39）
```

---

## 39. Lease Recovery Mechanism（§33）

### Recovery A — poll 时 opportunistic reclaim（PREFERRED）

```text
每次 poll 顺便识别 expired claim：
  SELECT ... WHERE status='running' AND lease_expires_at < now() AND task_type='notify_sales'
  → 原子 CAS → uncertain（策略 1，不 blind resend）
```

- 优势：无新增运行组件（YAGNI）。
- 恢复延迟 ≤ poll interval（5s）。
- 多实例安全：原子 CAS 保证只一者 reclaim。

### Recovery B — 独立 server reaper

- 新增运行组件，复杂度高。
- REJECTED（YAGNI，Recovery A 足够）。

### Recovery C — manual only

- 恢复延迟高。
- REJECTED（自动 reclaim 更优）。

**PREFERRED = Recovery A**（poll opportunistic reclaim）。reclaim 后进 `uncertain`（策略 1），不 blind resend。

---

## 40. 同仓 Pattern 复用（§34）

| 模式 | 来源 | 复用点 |
|---|---|---|
| 原子 UPDATE WHERE status=pending + rowcount + ClaimConflictError | `claim_delivery_task`（daily_report_delivery_service.py:433-469）| claim 合同 |
| `secrets.token_hex(32)` + 存 hash | `claim_delivery_task:442-450` | claim_token 生成 |
| `_const_eq(token_hash, token)` callback 校验 | `authorize_send_intent:511` | late callback 拒绝 |
| `lease_owner`/`lease_expires_at`/`attempt_count`/`next_attempt_at` | ReturnVisitRun/AiAutoReplyRun（models.py:567-571）| lease 字段语义 |

**不复用**：notify_sales 有外部 UIA uncertainty（P2-F3），send_report_attachment 无此问题（dry_run=true 强制）。不能直接 copy claim_delivery_task 而忽略 uncertainty（§34 警告）。

---

## 41. Schema（§36）

```text
wechat_tasks 新增列（additive migration）：
  claim_token_hash    String(64) nullable
  lease_expires_at    DateTime nullable
  attempt_count       Integer nullable default 0
  claimed_by          String(100) nullable
复用已有：execution_started_at（:321）、agent_hostname/agent_pid（:311-312，改为 claim 时填）
```

---

## 42. Index（§61）

```text
现有：idx_wechat_tasks_merchant_status_created（DB 层，但 ORM merchant_id 未映射，§57）
拟新增：(status, lease_expires_at) — 用于 reclaim 查询 WHERE status='running' AND lease_expires_at < now()
```

若复用 merchant_id 索引需 ORM 映射修复（P2-F6，§57 OUT_OF SCOPE）。claim 查询用 `(status, lease_expires_at)` 不依赖 merchant_id（merchant 隔离仍靠 JOIN）。

---

## 43. Migration（§38）

```text
additive migration（4 列 + 1 索引），nullable/default
existing pending rows: attempt_count=0, claim_token_hash=NULL, lease_expires_at=NULL（兼容）
rollback: code rollback + 列保留（nullable 无破坏）
```

本设计不实施。

---

## 44. 9000 Changes（§39）

```text
MODIFY:
  app/services/wechat_task_service.py
    + claim_notify_sales_task(db, merchant_id, task_id) → 原子 claim + claim_token + lease
    + get_pending_wechat_tasks 改为 claim-and-return（或新增 claim_pending_task）
    + submit_wechat_task_result 加 CAS（WHERE id AND claim_token_hash AND status=running）
    + reclaim_expired_claims（poll opportunistic，→ uncertain）
  app/routers/wechat_tasks.py
    GET /pending 响应新增 claim_token / attempt_count / lease_expires_at
    POST /result 请求体新增 claim_token；校验失败 → 409
  app/models.py
    + WechatTask 新增 4 字段 ORM 映射
  migrations/postgres/auto_wechat/versions/00XX_wechat_task_claim_lease.py
    + additive columns + index
```

---

## 45. 19000 Changes（§68）

```text
MODIFY（必需）:
  app/local_agent_main.py
    agent_poll_and_execute: 拿到 task 后存 claim_token
    POST /result 请求体带 claim_token
  app/routers/wechat_tasks.py（9000 侧协议）
    poll 响应 + result 请求体契约
```

**必须改 19000**（§68）：callback 需 attempt token → 大概率需 agent 协议修改。current code 事实证明：notify_sales result 请求体不含 claim token（Agent B 确认）。

---

## 46. Backward Compatibility（§43）

```text
新 server 上线 + 旧 19000 仍运行 → 旧 agent 不发 claim_token
→ server 校验失败 → 全部 task 失败
```

**不能 backward compatible**（claim_token 是新必需字段）。选择：
```text
B. coordinated server+agent release required
```

---

## 47. Rollout Strategy（§44/§69）

```text
1. DB migration（additive columns，兼容现有行）
2. server supports old+new（过渡期：claim_token 可选，旧 agent 无 token 走兼容路径？不——兼容路径会回归 NO_CLAIM）
   → 不走兼容路径。必须 coordinated。
3. deployment order:
   a. DB migration
   b. server rollout（支持新 claim + token 校验，但暂不强拒绝旧 token？——若不强拒绝则 NO_CLAIM 回归）
   → 必须同时：server enforce token + agent rollout
4. coordinated maintenance window: server + agent 同步发布
5. enforcement switch: server 上线即 enforce claim_token
6. rollback: code rollback（migration 列保留）
```

**设计裁定**：coordinated maintenance upgrade（server + agent 同步）。无过渡兼容期（过渡期 = NO_CLAIM 回归窗口）。具体部署顺序由实施审批定。

---

## 48. Existing Pending Tasks（§45）

```text
migration 时已有 pending notify_sales:
  attempt_count=0, claim_token_hash=NULL, lease_expires_at=NULL
  → 兼容（首次 claim 时填，attempt 1）
不会丢（pending 保留）、不会自动重复（无 claim 不执行）
```

无历史 `running` 状态（从未写入，探索确认）。

---

## 49. Lease Clock（§46）

```text
lease 时间 = server/DB time（datetime.now()，services.py 已用）
不依赖 Windows Agent local clock
```

避免时钟漂移（§46）。

---

## 50. Lease Ownership Validation（§47）

每个 renew / callback / terminal write 校验：
```text
task_id + claim_token_hash + current lease ownership（status=running）
```

---

## 51. Observability（§55）

```text
task_id / attempt_count / claim_token_hash / claimed_by / lease_expires_at / terminal result / uncertain reason
```

复用现有日志（`wechat_task_service.py` logger）。不新建 telemetry。

---

## 52. Audit Trail（§56）

claim / reclaim / late callback rejection / manual resolution → 复用 `raw_result`（:310 JSON）+ `failure_stage`（:309）记录。不新建审计系统（§56）。

---

## 53. Merchant Isolation（§57）

```text
claim 查询继续遵守当前 merchant boundary（JOIN lead+staff 双重过滤）
不依赖 wechat_tasks.merchant_id（ORM 未映射，P2-F6）
P2-F6 = FUTURE（不纳入 P2 首批，§57）
```

claim query 若需 `WHERE merchant_id=...` → SCOPE EXPANSION（需单独批准）。Preferred 不依赖 merchant_id 列。

---

## 54. detect_reply Boundary（§58）

```text
detect_reply = READ ONLY / LOW
本首批：NO CHANGE（§58）
```

若共享 poll endpoint 导致 claim 逻辑影响 detect_reply：detect_reply 也走 claim（一致性），但 read_only 无外部副作用，uncertainty 不适用。设计明确兼容行为：detect_reply claim 后 lease expired → safe reclaim（read_only 可 blind retry，无副作用风险）。不静默改变。

---

## 55. send_report_attachment Boundary（§59）

```text
DORMANT / FUTURE
现有 claim 实现 = reference
NO BEHAVIOR CHANGE（不激活，§59）
```

---

## 56. P2-F6 Schema Drift（§60）

```text
merchant_id / tenant_id ORM mapping gap = FUTURE（§60）
```

除非 Preferred 无法在 JOIN 隔离下实现——可以（claim 用 id+status，merchant 靠 JOIN）。不纳入 P2 首批。

---

## 57. Transaction Duration（§63）

```text
claim transaction = 短（select/CAS/state update/commit）
不包 HTTP 到 19000 / UIA / 微信发送
```

---

## 58. Runtime Verification Plan（§65/§66）

| Gate | 验证 | 期望 |
|---|---|---|
| P2-R1 Duplicate Poll | 2+ clients simultaneous poll | same task claimed ≤ 1 |
| P2-R2 Multi-Agent | 不同 agent instance 同时 poll | only current claim holder executes |
| P2-R3 Crash Before Side Effect | lease expiration → reclaim（策略 1：uncertain；策略 2：safe reclaim）| no blind resend |
| P2-R4 Late Callback | old attempt callback | rejected，new attempt intact |
| P2-R5 Lease Renewal | 若有 heartbeat（本设计无）| N/A |
| P2-R6 Side-Effect Unknown | uncertain 不 blind resend | no auto retry |
| P2-R7 Normal Happy Path | single_send 正常完成 | 不回归 |
| P2-R8 Producer Dedup | EXISTING_PENDING_TASK/ALREADY_SENT/RATE_LIMITED | 保持 |

**§66 不用真实微信发送验证**：并发 ownership 用 isolated DB + two HTTP clients + mock Local Agent 证明。真实 19000 E2E 补充。不自动发真实微信给客户。

---

## 59. Scope Freeze（§67）

### MODIFY

| 文件 | 改动 |
|---|---|
| `app/services/wechat_task_service.py` | + claim_notify_sales_task / claim_pending_task；submit_wechat_task_result 加 CAS；reclaim_expired_claims |
| `app/routers/wechat_tasks.py` | poll 响应 + result 请求体契约（claim_token）|
| `app/models.py` | WechatTask +4 字段 ORM 映射 |
| `app/local_agent_main.py` | agent_poll_and_execute 存 claim_token；POST /result 带 token |

### CREATE

| 文件 | 内容 |
|---|---|
| `migrations/postgres/auto_wechat/versions/00XX_wechat_task_claim_lease.py` | additive columns + index |
| focused tests | P2-R1~R8（§65）|
| implementation report | `P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_REPORT.md` |

### READ ONLY

- compute core / 11 consumers（P1 CLOSED，不动）
- detect_reply 行为（§58）
- send_report_attachment（§59）
- merchant_id ORM 漂移（§57）
- staging/prod
- RB-10

---

## 60. Risks / Tradeoffs（§47/§70）

| 风险 | 影响 | 缓解 |
|---|---|---|
| coordinated release 部署复杂 | server+agent 同步 | maintenance window，无过渡兼容期 |
| uncertain 积压（策略 1 保守）| claim 后未执行 crash 也进 uncertain，需人工 | 策略 2（OPTIONAL）加 attempt_started phase |
| lease 时长不当 | 过短误 reclaim，过长 crash 恢复延迟 | 可配置 + 真实 UIA 耗时数据 |
| 19000 协议 breaking | 旧 agent 不兼容 | coordinated release（§47）|
| migration 影响 | additive，低 | nullable/default，rollback 安全 |

---

## 61. Future Findings（§49）

```text
P2-F4 detect_reply 双写覆盖 = LOW（read_only，可未来加 CAS）
P2-F5 send_report_attachment DORMANT = FUTURE（启用时 claim 已就绪，需接 reclaim 调度）
P2-F6 merchant_id ORM 漂移 = FUTURE（claim 设计依赖）
SIDE_EFFECT_START_SIGNAL = OPTIONAL HARDENING（策略 2）
HEARTBEAT = FUTURE（若执行超 lease）
```

---

## 62. 20 Required Questions（§72）

**Q1. 当前 P2 真正 ACTIVE 风险面？**
notify_sales single_send（真实微信发送，UIA fire-and-forget 无 receipt）。P2-F1（NO_CLAIM）+ P2-F2（无 lease/crash recovery）+ P2-F3（外部不可幂等）共因。

**Q2. 什么时刻算"task 已被一个执行者拥有"？**
原子 claim commit 后（`UPDATE WHERE status=pending → running + claim_token_hash + lease_expires_at`，affected rows=1）。

**Q3. ownership 如何原子获得？**
`UPDATE wechat_tasks SET status=running, claim_token_hash=:hash, lease_expires_at=:now+lease, attempt_count=attempt_count+1 WHERE id=:task_id AND status=pending RETURNING ...`（rowcount=1 winner，0 conflict，复用 claim_delivery_task 模式）。

**Q4. owner identity？**
`claimed_by`（agent hostname+pid，claim 时填）+ `claim_token`（secrets.token_hex(32)，只存 hash）。不仅用 merchant_id。

**Q5. attempt identity？**
`task_id`（stable）+ `claim_token_hash`/`attempt_count`（每 attempt 新）。retry/reclaim → same task_id, new attempt。

**Q6. lease 何时过期？**
`lease_expires_at = claimed_at + LEASE_SECONDS`（可配置，默认 120-300s）。用 server/DB time。

**Q7. 是否需要 heartbeat？**
默认不需要（单次 notify_sales 执行 < 5 分钟，lease 300s 足够）。YAGNI。未来若超 lease 再加。

**Q8. crash before side effect 如何恢复？**
策略 1（Preferred）：lease expired 无 callback → uncertain（保守，不 blind resend）→ 人工 resolve retry。策略 2（OPTIONAL）：若 attempt_started=false → safe reclaim。

**Q9. crash after possible side effect 如何处理？**
→ uncertain（不自动当 definite failure，不 blind resend）→ 人工确认是否已发送。

**Q10. 为什么不能承诺 external exactly-once？**
微信 UIA fire-and-forget，无 external receipt/message ID（§17）。无法证明消息是否已发。EXACTLY_ONCE = IMPOSSIBLE。

**Q11. late callback 如何拒绝？**
callback CAS `WHERE id AND claim_token_hash=:token AND status=running`。旧 attempt token → 0 rows → 拒绝（§48）。

**Q12. manual retry 如何避免与旧 attempt 重叠？**
retry → new claim（new token, attempt_count+1）。旧 attempt token CAS 必失败（claim_token_hash 已变）。

**Q13. 是否新增状态？**
复用 `running`（赋 durable owner 语义）+ 新增 `uncertain`（副作用结果未知）。不新增其他。

**Q14. 是否新增字段/migration？**
是。additive migration：`claim_token_hash`/`lease_expires_at`/`attempt_count`/`claimed_by` + `(status, lease_expires_at)` index。nullable/default，兼容现有行。

**Q15. 是否修改 19000 协议？**
是（§68）。poll 响应含 claim_token；result 请求体带 claim_token。current code 无 token → 必需改。

**Q16. rollout 如何兼容旧 agent？**
不兼容（coordinated release，§47）。过渡期 = NO_CLAIM 回归窗口。maintenance window server+agent 同步发布。

**Q17. detect_reply 如何保持不变？**
本首批 NO CHANGE（§58）。若共享 poll 导致 claim 影响 detect_reply：detect_reply 也走 claim（一致性），但 read_only 无 uncertainty。明确兼容行为，不静默改变。

**Q18. dormant send_report_attachment 如何保持不变？**
NO BEHAVIOR CHANGE（§59）。现有 claim = reference。不激活。

**Q19. merchant isolation 如何保持？**
claim 查询继续 JOIN lead+staff 双重过滤（§57）。不依赖 wechat_tasks.merchant_id（P2-F6 FUTURE）。

**Q20. 实施后 runtime Gate？**
P2-R1~R8（§65）：duplicate poll / multi-agent / crash before / late callback / side-effect unknown / happy path / producer dedup。不用真实微信发送（§66）。

---

## 63. Verdict

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

### 设计结论

1. **Preferred = Candidate C**（claim + lease + attempt token + uncertainty state）。
2. **保证边界**：at-most-one active executor + leased pre-side-effect recovery + NO blind retry after uncertain side effect。不承诺 exactly-once external send。
3. **复用 `running`**（durable owner 语义）+ **新增 `uncertain`**。
4. **additive migration**（4 列 + 1 索引）。
5. **19000 协议必需改**（claim_token），coordinated release。
6. **策略 1（最小保守）**：lease expired 无 callback → uncertain（不 blind resend）。
7. **detect_reply / send_report_attachment 不变**（§58/§59）。
8. **复用同仓模式**：claim_delivery_task / authorize_send_intent / ReturnVisitRun lease 字段。

### 不实施

```text
DO NOT COMMIT
DO NOT MODIFY wechat_task_service.py / wechat_tasks.py / models.py / local_agent_main.py
DO NOT CREATE migration
DO NOT ADD claim/lease/token fields
DO NOT MODIFY 19000
DO NOT MODIFY retry 逻辑
DO NOT ACTIVATE send_report_attachment
DO NOT MODIFY detect_reply
DO NOT FIX merchant_id ORM drift
DO NOT ADD Redis lock
DO NOT RE-RUN runtime gates
```

### P2 状态（继续冻结）

```text
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（保持）
P2 M04 CLAIM/LEASE = DESIGN_READY_FOR_APPROVAL
P2-F1 / P2-F2 / P2-F3 = OPEN
```

### 下一步

```text
本设计交独立设计审批窗口。
审批通过后，由独立实施窗口：
  1. additive migration（4 列 + 索引）
  2. wechat_task_service claim/CAS/reclaim
  3. wechat_tasks router 协议
  4. models ORM 映射
  5. local_agent_main 协议适配
  6. focused tests（P2-R1~R8）
  7. coordinated release（server+agent）
不得借实施窗口处理 detect_reply / send_report_attachment / P2-F6 / Redis / RB-10。
```

---

## 64. 设计窗口停止点

```text
P2-M04-NOTIFY-SALES-CLAIM-LEASE-DESIGN:
VERDICT = DESIGN_READY_FOR_APPROVAL
  Preferred = Candidate C（claim + lease + attempt token + uncertainty）
  保证 = at-most-one active executor + leased recovery + NO blind retry after uncertainty
  不承诺 exactly-once external send（UIA 无 receipt）
  running 复用（durable owner）+ uncertain 新增
  additive migration（4 列 + 索引）
  19000 协议必需改（coordinated release）
  策略 1（最小保守，lease expired 无 callback → uncertain）
本窗口不实施，停止。
```

未自行：修改 M04 业务代码 / 创建 migration / 添加 claim/lease/token 字段 / 修改 19000 / 修改 retry 逻辑 / 激活 send_report_attachment / 修改 detect_reply / 修 merchant_id ORM drift / Redis lock / RB-10 / push。
