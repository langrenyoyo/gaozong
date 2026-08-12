# P2-M04 notify_sales Claim-Lease 独立设计审批报告

> 审批窗口：`P2-M04-NOTIFY-SALES-CLAIM-LEASE-DESIGN`（独立设计审批，非设计窗口自述）
> 审查对象：`docs/architecture/remediation/P2_M04_NOTIFY_SALES_CLAIM_LEASE_DESIGN.md`
> 前序：`P2_M04_CLAIM_LEASE_REALITY_EXPLORATION.md`（`P2_RISK_CONFIRMED_DESIGN_REQUIRED`）
> Governance baseline：`1d7f1f5`（P1 COMPUTE-IDEMPOTENCY-001 = CLOSED）
> 审批日期：2026-08-12
> 窗口性质：READ / DESIGN APPROVAL ONLY（未改 M04 业务代码 / migration / Local Agent / DB / commit / push）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS

Preferred Strategy = Candidate C
  Atomic Claim + Lease + Attempt Token + Current-Attempt Callback CAS + Uncertain State

P2-F1 NO DURABLE CLAIM = OPEN（设计已覆盖，待实施）
P2-F2 NO LEASE / CRASH RECOVERY = OPEN（设计已覆盖，待实施）
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = OPEN（设计诚实承认 exactly-once external send = IMPOSSIBLE）
```

Candidate C 核心成立：完整覆盖 P2-F1/F2/F3，复用同仓已验证模式（`claim_delivery_task` 原子 UPDATE + `_const_eq` callback CAS + `secrets.token_hex(32)` 存 hash），保证边界诚实（at-most-one active executor + lease quarantine + NO blind retry after uncertain + 不承诺 exactly-once external send）。

需实施前冻结的 corrections（C1-C14，§46）：策略 1 保证措辞纠正、producer dedup 必须含 uncertain、lease 时长须基于真实上界、lease-expiry vs callback semantics 须冻结、callback idempotency（duplicate same-attempt vs stale）、schema fact 已核对、rollout 须精确、uncertain 须有可操作 resolution、token lifecycle、status contract、claimed_at、claim merchant boundary、claim cardinality。

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（保持）
P2 M04 CLAIM/LEASE = DESIGN_APPROVED_WITH_CORRECTIONS
P2-F1 / P2-F2 / P2-F3 = OPEN（保持，待实施）
```

---

## 2. Baseline

```
HEAD = 1d7f1f5（闭环：完成算力幂等P1技术收口）
worktree = 2 设计文档 untracked（Reality Exploration + Design），无业务代码 diff
```

```
business-code baseline = 1d7f1f5
BASELINE_DRIFT = NO
```

P1 CLOSED 保持不动。P1↔P2 边界：P1 只保证同 Business Event Identity → compute billing 不重复；不解决 M04 任务执行 exactly-once，不解决外部微信副作用重复。P1 不重新打开。

---

## 3. Active Risk Surface

独立确认当前 ACTIVE side-effect surface：

```
notify_sales（mode=single_send）= ACTIVE 真实微信发送
  producer: POST /lead-notifications/send-to-staff → create_wechat_task(status=pending)
  consumer: 19000 GET /wechat-tasks/pending?task_type=notify_sales → UIA Ctrl+V + Enter → POST /result
  risk: 多 Agent 同 task 重复发送（P2-F1）+ crash 后重拉重发（P2-F2）+ 外部不可幂等（P2-F3）

detect_reply = read_only / LOW / NO SEND SIDE EFFECT ✅（OUT OF SCOPE）
send_report_attachment = DORMANT / existing atomic claim reference only ✅
POST /wechat-tasks = disabled 410 ✅
Douyin automatic WeChat-task creation = disabled 410 ✅
```

current facts 未漂移。Scope 裁定正确。

---

## 4. P2-F1/F2/F3 独立确认

### F1 No Durable Claim

独立确认 `get_pending_wechat_tasks`（wechat_task_service.py:100-132）：纯 SELECT `.filter(status=="pending").order_by(id).limit(limit).all()`，**无 FOR UPDATE、无 status 修改、无 commit、无 claim_token**。task 执行期间 status 恒 pending。

```
P2-F1 NO_CLAIM = CONFIRMED ✅
  fetch 期间 pending → payload returned to 19000，无 durable atomic ownership transition
```

### F2 No Lease / Crash Recovery

独立确认：无 `claim_token_hash` / `lease_expires_at` / `attempt_count` / `claimed_by` / `heartbeat` / stale recovery 字段（models.py:295-336）。`agent_hostname`/`agent_pid` 仅回写时填（:351-352），非 claim 时绑定。

```
P2-F2 NO_LEASE = CONFIRMED ✅
  无 claim owner / lease / attempt token / heartbeat / stale recovery
```

### F3 External Side Effect Not Exactly-Once

notify_sales single_send 的 Enter 发送是 UIA fire-and-forget（input_writer.py SendKeys），无 external receipt / message ID。

```
P2-F3 EXTERNAL_NOT_IDEMPOTENT = CONFIRMED ✅
  TRUE EXACTLY-ONCE EXTERNAL WECHAT SEND = NOT GUARANTEED
  Candidate C 不能改变这个事实（设计诚实承认，§11/§24）
```

---

## 5. Candidate A-E 独立比较

| Candidate | Double-Poll | Crash | Late Callback | Send Unknown | API | Migration | Agent Change | Verdict |
|---|---|---|---|---|---|---|---|---|
| A atomic claim only | ✅ 解决 | ❌ running forever | ❌ | ❌ | 小 | 小 | 小 | REJECTED（不解决 P2-F2）|
| B claim + lease | ✅ | ✅ pre-side-effect | ❌ | ❌ blind resend | 中 | 中 | 中 | REJECTED（不解决 P2-F3 uncertainty）|
| **C claim+lease+token+uncertain** | ✅ | ✅ quarantine | ✅ token reject | ✅ uncertain | 中-大 | 中 | 中 | **PREFERRED** |
| D Redis lock | ✅ | ✅ | ✅ | ❌ | 大 | — | 大 | REJECTED（双状态同步风险）|
| E SELECT FOR UPDATE | ✅ | ❌ 长事务 | ❌ | ❌ | 大 | — | 大 | REJECTED（长事务禁止）|

```
PREFERRED = Candidate C ✅（唯一完整覆盖 F1/F2/F3）
```

---

## 6. Guarantee Boundary

设计 §11/§64 保证边界，独立审查后须纠正措辞（C1，§46）：

### 设计当前措辞（须纠正）

```
LEASE: Stale pre-side-effect attempts can be recovered.
```

### 审批冻结的正确保证（C1）

```
SERVER OWNERSHIP: At most one current valid notify_sales attempt.
CLAIM: Task payload handed to agent only after durable claim.
FENCING: Only current attempt may authoritatively transition state.
CALLBACK: Same-attempt duplicate callbacks are idempotent; stale attempts rejected.
STALE EXECUTION: Expired/unresponsive attempts are quarantined (uncertain); NOT blindly resent.
EXTERNAL WECHAT: Exactly-once delivery is NOT guaranteed.
UNCERTAINTY: Potentially executed but unacknowledged sends require explicit resolution before retry.
PRODUCER: running/uncertain outstanding work prevents creation of another normal notify_sales send task.
```

---

## 7. Strategy-1 Recovery Correction（C1）

§4/§5 核心纠正。设计采用策略 1（无 `attempt_started` phase）。因此 server 无法区分：

```
A. claim 后、UIA 尚未开始就 crash
B. UIA 可能已经执行、callback 丢失
```

lease expiry + no callback 的事实只能说明：

```
EXECUTION RESULT UNKNOWN → uncertain
```

**不能**证明 `PRE_SIDE_EFFECT`。

### 设计 §11 当前措辞须纠正

设计 §11 写 `LEASE: Stale pre-side-effect attempts can be recovered` + §15 状态机写 `lease expired, callback 未到, side-effect 未开始 → pending [reclaim]`——这与策略 1 矛盾。策略 1 无 side-effect-start signal，无法识别"未开始"。

### 审批冻结（C1 REQUIRED）

```
Lease detects stale ownership.
Expired running attempts are quarantined as UNCERTAIN.
No automatic resend occurs.
Manual resolution required before retry/cancel/mark-sent.
```

不得写：
- `lease expiry → safe automatic reclaim`（策略 1 无此能力）
- `crash before side effect → automatically retry`（策略 1 无法识别 pre-side-effect）

设计 §15 状态机 `lease expired, side-effect 未开始 → pending [reclaim]` 须删除/纠正为 `lease expired → uncertain`。设计 §39 Recovery A "poll opportunistic reclaim → uncertain"（策略 1）正确，但 §39 标题"opportunistic reclaim"名称过度——实际是 `OPPORTUNISTIC STALE-ATTEMPT QUARANTINE`（非 reclaim for resend）。

---

## 8. Current Producer Dedup（§7 第一 Hard Gate）

独立读取 `lead_wechat_notify_eligibility_service.py:19`：

```python
ACTIVE_NOTIFY_TASK_STATUSES = {"pending", "running", "pasted", "sent"}
```

producer dedup 查询（:152-162）：`WechatTask.status.in_(ACTIVE_NOTIFY_TASK_STATUSES)`。

```
§7 担忧（引入 running 后 producer 不再看到 pending → 创建 Task B）= NOT FOUNDED ✅
  producer dedup 已包含 running（:19）
  running task 存在时普通 POST 会被 EXISTING_PENDING_TASK 阻断
```

设计 §7 的担忧不成立。但 `uncertain` **不在** `ACTIVE_NOTIFY_TASK_STATUSES` 集合中 → §8/§46 担忧成立：

```
uncertain task 存在时普通 POST → 不被 EXISTING_PENDING_TASK 阻断 → 创建新 task → 绕过 claim
```

---

## 9. running/uncertain Outstanding Contract（C2 REQUIRED）

### running（已覆盖）

`ACTIVE_NOTIFY_TASK_STATUSES` 已含 `running`（:19），producer dedup 正常阻断。**无需改动**。

### uncertain（C2 REQUIRED）

Candidate C 引入 `uncertain` 后，必须冻结 producer dedup：

```
normal notify_sales creation blocked when existing task is:
  pending
  running
  uncertain
```

实施须把 `uncertain` 加入 `ACTIVE_NOTIFY_TASK_STATUSES`（或等价查询条件）。

```
不得允许: uncertain task exists → normal POST creates fresh task
否则 NO_BLIND_RESEND 保证失效
```

---

## 10. New State Machine

审批冻结状态机（C1 纠正后）：

```
pending ──(atomic claim)──→ running [claim_token_hash, lease_expires_at, attempt_count+1]
running ──(callback success, token valid)──→ pasted / sent
running ──(callback definite failure, token valid, PRE side-effect)──→ failed [可 manual retry]
running ──(lease expired, callback 未到)──→ uncertain [不 blind resend，不 reclaim]
running ──(late callback, token 不匹配)──→ 拒绝（不改状态）
uncertain ──(manual resolve: sent)──→ sent
uncertain ──(manual resolve: retry)──→ pending [新 attempt，attempt_count+1，新 token]
uncertain ──(manual resolve: cancel)──→ cancelled
```

**删除**设计 §15 的 `lease expired, side-effect 未开始 → pending [reclaim]`（策略 1 无此能力，C1）。

`pasted`/`sent`/`blocked`/`failed` 语义不变。

### `pasted` 审查（§47）

`pasted`（wechat_task_service.py:~440）= UIA 粘贴成功（Ctrl+V）但 single_send 模式下尚未 Enter。当前 `pasted` 是终态（pasted=true, sent=false）。**`pasted` 已产生不可逆副作用**（剪贴板写入 + 输入框粘贴，用户可见）。crash recovery 不得把 `pasted` 当"未执行"重试。

```
pasted = terminal, 不可自动重试 ✅
  若 pasted 已回写则不重发；若 crash 在 pasted 回写前则进 uncertain
```

### `failed` 语义（§48）

当前 `failed` 混合 definite pre-send failure / definite send failure / unknown send result。Candidate C 引入 uncertain 后：

```
unknown send outcome NEVER maps to ordinary auto-retryable failed ✅
  unknown → uncertain（不 retry）
  definite failure → failed（可 manual retry）
```

设计 §15 复用 `failure_stage` 区分，不新增状态列。合理。

---

## 11. Claim Contract（§16）

设计 §16 原子 claim SQL：

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

复用 `claim_delivery_task`（daily_report_delivery_service.py:433-469）模式：`db.query().filter(status==pending).update({...}, synchronize_session=False)` + rowcount + ClaimConflictError。

```
affected rows = 1 → claim winner
affected rows = 0 → claim conflict / no task → ClaimConflictError（409）
不得 SELECT pending → later UPDATE running ✅
```

### Claim 与 Fetch 合同

```
claim commit BEFORE task handed to Local Agent ✅
  poll 端点内部 find + atomic claim → 返回 claimed task（含明文 claim_token）
```

---

## 12. Claim Cardinality（§34/§35 REQUIRED）

独立确认 `get_pending_wechat_tasks`（:132）返回 **list**（`.all()`），`limit=20`（默认）。

```
§34 风险: 一次 claim 多个 task 串行执行 → task B/C 被claim 但长时间未执行
  → lease false expiry → uncertain
```

### 审批冻结（C13 REQUIRED）

```
每次 poll 最多 claim 1 个 notify_sales task（claim exactly one executable task）
  Local Agent 一次只执行一个 → claim exactly one
  保持现有 created_at / id 排序语义（§36 fairness/ordering）
```

实施须把 poll 端点改为 claim-and-return-one（limit=1 claim，非 limit=20 batch）。不得 batch claim。

---

## 13. Merchant Boundary（§32/§53）

独立确认 `get_pending_wechat_tasks` merchant 隔离（:121-130）：INNER JOIN lead+staff 双重过滤 `DouyinLead.merchant_id == merchant_id AND SalesStaff.merchant_id == merchant_id`。

```
claim 查询继续遵守当前 merchant boundary（JOIN lead+staff 双重过滤）✅
不依赖 wechat_tasks.merchant_id（ORM 未映射，P2-F6 FUTURE）
```

### Atomic Claim 不得只凭 task_id（§33）

```
claim 行为对 HTTP caller 可控 → 必须保证 task 属于当前允许 merchant/staff/agent context
  先通过现有授权查询取得 eligible task，再在同 server 内部 CAS
  或安全 subquery（JOIN 条件纳入 UPDATE WHERE）
```

设计须冻结 claim 的 merchant 边界保持方式。

---

## 14. Claim Owner / Attempt Identity

### Claim Owner（§27）

```
owner identity = claimed_by（agent hostname+pid，claim 时填）
  + claim_token（每 attempt 唯一，secrets.token_hex(32)，只存 hash）
正确性权威 = claim_token（非 claimed_by）
  不得信任客户端自由传入的 claimed_by 作为唯一 ownership 凭证
```

`claimed_by` 主要是 observability/attribution，安全 authorization 来自 claim_token。

### Agent Instance Identity（§28）

```
claimed_by = agent hostname + pid（已有 agent_hostname/agent_pid 字段，改为 claim 时填）
```

审批冻结：`claimed_by` 用 hostname+pid（非新 agent_instance_id）。per-process random instance id 属 future（当前 hostname+pid 足够区分旧/新进程）。

### Attempt Identity（§29）

```
attempt identity = task_id + attempt_count + claim_token_hash
  task_id = stable business task（不变）
  attempt_count = 第 N 次执行
  claim_token_hash = 每 attempt 唯一，防 late callback 覆盖
```

---

## 15. Token Security / Lifecycle（C9）

### Token Security（§26）

```
raw token = secrets.token_hex(32)（cryptographically random）
DB = hash only（SHA-256，_hash_token 模式）
logs = never log raw token
callbacks = constant-time hash comparison（_const_eq）
new attempt = new token
old token = permanently fenced（claim_token_hash 已变，旧 token CAS 失败）
```

复用 `_const_eq`（daily_report_delivery_service.py:351）✅。

### Token Hash Terminal Lifecycle（§25 REQUIRED）

设计须冻结 terminal 后 claim_token_hash 保留策略：

```
terminal 后保留 claim_token_hash（不立即清空）
  → 用于识别 duplicate same-attempt callback（C5）
  rotate 时机: 新 attempt claim 时（claim_token_hash 被新值覆盖）
  clear 时机: 不 clear（terminal 保留，新 attempt rotate）
```

若立即清空 → 无法识别 duplicate same-attempt callback（§25）。

---

## 16. Lease（§16/§17）

### Lease Duration（C3 REQUIRED — 第二 Hard Gate）

设计 §22 `LEASE_SECONDS = 120-300 秒`，§17 说"具体默认值由实施窗口基于真实 UIA 耗时数据定"——**这不够**（§17 要求审批冻结）。

独立核验 UIA timeout（local_agent_main.py）：http timeout 10s，`find_message_list` timeout=5s，单次 notify_sales（Ctrl+V + Enter）通常 < 30s，含 foreground guard / search focus / 联系人验证 / OCR 可能 1-2 分钟。

### 审批冻结（C3）

```
Option L1: lease duration > maximum legitimate execution duration + safety margin
  首批 NO HEARTBEAT
  LEASE_SECONDS 默认 300s（5 分钟，> 2 分钟真实上界 + safety margin）
  实施窗口须基于真实 UIA 耗时数据确认 300s 足够
  若无法建立可靠上界 → heartbeat 必须进入设计（L2）
```

不得保留模糊 `120-300 seconds` 让实施窗口猜。审批冻结 300s 默认 + 实施窗口须验证。

### Lease Clock（§18）

```
lease_expires_at 完全由 server/DB time 计算 ✅
19000 只把 token 当 opaque attempt credential
不得由 Windows 本地时间判断 lease ✅
```

---

## 17. Heartbeat Decision（§17/§56）

```
HEARTBEAT = NOT REQUIRED（首批，L1）
  单次 notify_sales 执行 < 5 分钟，lease 300s 足够
  若未来证明执行超 lease（OCR 慢 / 微信卡顿）→ heartbeat 必须进入设计
  false uncertainty（long-but-healthy execution 误判 stale）= 明确 tradeoff
```

无可靠上界时 NO_HEARTBEAT 不能无条件批准——审批冻结 300s 基于独立核验的 UIA timeout 事实（< 2 分钟真实上界）。

---

## 18. Expiry Semantics（C4 REQUIRED — 第三 Hard Gate）

§19 lease-expiry vs callback race。设计未冻结。审批须二选一。

### 审批冻结（C4）：Semantics A

```
Semantics A: lease expiry = eligible for revocation，真正 ownership revocation 发生在 running → uncertain CAS
  只要 status=running AND token=current AND server stale-transition 尚未赢得 CAS
  callback 仍可完成
  lease expiry 只是 eligible，不立即撤销 ownership
```

选择 A 理由：
- 减少刚好超时但真实成功的 false uncertain（§20）
- 策略 1 不会自动发起 new attempt（uncertain 需人工），即使 callback 延迟仍可完成
- Semantics B（lease 过期 callback 立即无效）无 heartbeat 更易制造 false uncertain

### Expiry Transition 必须 Atomic CAS（§21）

```sql
UPDATE wechat_tasks
SET status = 'uncertain'
WHERE id = :id
  AND status = 'running'
  AND lease_expires_at <= db_now
  [AND claim_token_hash = :current_token]
```

检查 affected rows。不得 `SELECT expired → later UPDATE uncertain`。

---

## 19. Expiry/Callback Race（§50/§22）

```
lease time passed but server 尚未把 running → uncertain
old agent callback(sent) arrives

Semantics A: callback CAS WHERE status=running AND claim_token_hash=current
  若 callback 先赢得 CAS → terminal（sent/pasted）
  若 stale-transition 先赢得 CAS → uncertain，callback 0 rows → rejected
  最终只能有一个合法结果 ✅
```

P2-R9（§50）验证此 race。

---

## 20. Callback CAS（§22）

```
notify_sales result callback 校验:
  task_id
  status = 'running'
  current claim_token_hash（_const_eq）

只允许 CURRENT ATTEMPT 写终态 ✅
```

```sql
UPDATE wechat_tasks
SET status = :terminal, ...
WHERE id = :task_id
  AND claim_token_hash = :token_hash
  AND status = 'running'
```

---

## 21. Callback Idempotency（C5 REQUIRED — 第四 Hard Gate）

§23 callback retry idempotency。设计未充分处理。

### 三类 callback（§24）

```
A. First current-attempt callback: running + matching token → apply terminal transition
B. Duplicate same-attempt callback: task 已是相同 terminal result + token 属于该 attempt → idempotent success/replay
C. Stale old-attempt callback: token 不是 current/last valid attempt → STALE_ATTEMPT/conflict
```

不得把 B 和 C 混在一起。

### 审批冻结（C5）

```
same attempt + same terminal result + duplicate callback → idempotent success（不报错）
  需 terminal 后保留 claim_token_hash（§25/C9）
  callback 校验: 若 status 已 terminal AND claim_token_hash 匹配该 attempt → return success（replay）
  若 token 不匹配 → STALE_ATTEMPT（conflict，非 B 类）
```

若第二次因 `status != running` 直接返回 ClaimConflict → 协议自身不是良好幂等的（§23）。实施须区分 B/C。

---

## 22. Late Callback（§29）

```
attempt A lease expired → uncertain（策略 1）
  或 attempt A → manual retry → attempt B（new token）
A late callback arrives（A token）→ WHERE claim_token_hash=A_token → 0 rows → 拒绝
B ownership remains intact ✅
```

P2-R4 验证。P2-R13 验证 manual retry + late old callback。

---

## 23. Manual Resolution（C8 REQUIRED）

### §10 硬要求

设计 §26 说 `uncertain → manual resolve`，但审批须回答：当前 implementation scope 中到底有什么机制让它被 resolve？

### 审批冻结（C8）

```
P2 first implementation includes:
  service: manual resolution actions（mark_sent / retry / cancel）
  API: safe callable API + permission + audit（首批 API-only，UI 可后做）
  UI: P2 first batch API-only（frontend = future，§65）
```

不得让 uncertain 成为永久无解 dead-end，同时宣称"crash recovery 已设计完成"。

### Manual Resolution Actions（§11）

```
MARK_AS_SENT / RESOLVED_SENT: uncertain → sent
RETRY: uncertain → pending（新 attempt，attempt_count+1，新 token，旧 token fenced）
CANCEL / ABANDON: uncertain → cancelled
```

每个动作定义：allowed source state / permission / state transition / attempt-token invalidation / audit。

### Manual Retry Fencing（§12）

```
uncertain → manual retry
  → 旧 attempt 永久失效（claim_token_hash 被 new token 覆盖）
  → same task_id, new attempt_count, new claim_token, new lease
  → 旧 token 任何晚到 callback 都不能修改 task ✅
```

---

## 24. External Send Uncertainty（§24/§27）

```
lease expired ≠ safe to resend ✅
  Agent A claim → UIA actually sends → crash before callback → lease expires
  服务器只知道 lease expired，不知道 message sent?
  → uncertain（不 blind resend）

notify_sales 业务风险: 重复发送 > 漏发（骚扰客户/封禁 > 销售错过线索）
  → at-most-once after uncertainty（避免重复骚扰 > 避免漏发）✅
```

---

## 25. Poll Response-Loss Tradeoff（§55）

```
claim committed → response lost → Agent never executes → lease becomes stale
  策略 1 无法证明未执行 → uncertain（保守）
  false uncertainty = 明确 tradeoff ✅
```

策略 1 下，claim 后未执行就 crash 的 task 也进 uncertain（需人工 resolve）。这是"最安全"的代价（§30/§56）。

---

## 26. pasted/sent/failed Semantics（§47/§48）

```
pasted = terminal，已产生不可逆副作用（剪贴板+输入框粘贴）✅
  不可自动重试；crash 在 pasted 回写前 → uncertain

sent = terminal（single_send 发送成功）✅

failed = definite failure（pre-send / send failure）✅
  unknown send outcome → uncertain（不混入 failed）
  复用 failure_stage 区分
```

---

## 27. Schema Fact Reconciliation（C6 — 第六 Hard Gate）

§30 schema fact conflict。独立直接读取：

### DB migration（0003_create_leads_tasks_core_tables.py:138-155）

```sql
wechat_tasks:
  tenant_id    String(128) nullable  ← DB 有列（:140）
  merchant_id  String(128) nullable  ← DB 有列（:141）
  status       String(20) NOT NULL default 'pending'  ← plain VARCHAR，无 CHECK/ENUM（:144）
  idx_wechat_tasks_merchant_status_created  ← DB 有索引（:155）
```

### ORM model（models.py:295-336）

```
WechatTask ORM 未映射 merchant_id / tenant_id
  → Schema/ORM mapping drift 确认
```

### 审批冻结（C6）

```
P2-F6 事实 = SCHEMA/ORM MAPPING DRIFT
  DB 有 merchant_id/tenant_id 列 + 索引，ORM 未映射
  task 表自身 merchant_id/tenant_id 列恒 NULL
  商户隔离靠 lead.merchant_id + staff.merchant_id INNER JOIN AND 双重过滤
```

设计 §57"P2-F6 merchant_id/tenant_id ORM 漂移 = FUTURE"准确。claim 设计不依赖 merchant_id 列（靠 JOIN），正确。

不得带着冲突进入 implementation——已核对唯一事实。

---

## 28. Migration（§21/§41/§43）

### Additive Migration 逐字段（§41）

| 字段 | 类型 | nullable/default | 必要性 |
|---|---|---|---|
| `claim_token_hash` | String(64) | nullable | ✅ callback ownership CAS（现有无 token）|
| `lease_expires_at` | DateTime | nullable | ✅ lease 过期判定（现有无 lease 时间）|
| `attempt_count` | Integer | nullable default 0 | ✅ 区分第 N 次执行（现有无计数）|
| `claimed_by` | String(100) | nullable | ✅ owner identity（claim 时填，非回写）|

### claimed_at 不一致（C11 REQUIRED）

设计 §51 observability 含 `claimed_at`，但 §41/§43 migration 只有 4 列（无 claimed_at）。

```
C11 审批冻结:
  复用 execution_started_at（已有，models.py:321）作为 claimed_at
  execution_started_at 在 claim 时填（同 claim_delivery_task 模式）
  不新增 claimed_at 列
  §51 observability 措辞纠正: claimed_at = execution_started_at
```

### attempt_count（§43）

```
default = 0, NOT NULL（或 nullable default 0，项目等价安全设计）
claim winner: attempt_count = attempt_count + 1（在 atomic claim 中完成）✅
```

### Index（§44）

```
拟新增 (status, lease_expires_at) — 用于 reclaim 查询 WHERE status='running' AND lease_expires_at < now()
  评估: 若 task_type 过滤也是核心条件，考虑 (task_type, status, lease_expires_at)
  不依赖 merchant_id 索引（ORM 未映射，P2-F6）
  不过度建索引 ✅
```

---

## 29. Status Constraints（§14/§45）

独立确认 `status = Column(String(20), nullable=False, default="pending")`（models.py:307），migration DDL `sa.Column("status", sa.String(length=20)...)`——**plain VARCHAR，无 CHECK/ENUM 约束**。

```
§45 审批冻结:
  status = plain VARCHAR，无 DB CHECK/ENUM
  新增 uncertain → NO DB status migration required ✅
  但应用 schema（Pydantic / 状态机 / producer dedup ACTIVE_NOTIFY_TASK_STATUSES）须同步
```

---

## 30. Status `uncertain` Consumer Audit（§13/§15/§46 REQUIRED）

`uncertain` 不得只在 service 里加字符串。须同步：

```
Pydantic schema ✅（状态校验）
router validation ✅
frontend status rendering（首批 API-only，UI future，§65）
filters ✅
producer dedup: ACTIVE_NOTIFY_TASK_STATUSES 加入 uncertain（C2）✅
reporting ✅
admin UI（future）
tests ✅
migration constraints: 无 DB CHECK（§29），无 migration ✅
```

### `running` 消费者审查（§15）

`running` 已在 `ACTIVE_NOTIFY_TASK_STATUSES`（:19），producer 已认知。但 notify_sales 历史上未真正进入 running（从未写入）。须确认 producer / frontend / filters / result callback / cleanup 看到 notify_sales running 时不会错误处理。

```
C10 REQUIRED: running 引入 notify_sales 后，审查所有 status 消费者
  producer: 已含 running（:19）✅
  其余: 实施窗口须审查
```

---

## 31. detect_reply Boundary（§57）

```
detect_reply = READ ONLY / LOW / NO BEHAVIOR CHANGE ✅
  本首批 NO CHANGE
  若共享 poll endpoint 导致 claim 逻辑影响 detect_reply:
    detect_reply 也走 claim（一致性），但 read_only 无 uncertainty
    detect_reply claim 后 lease expired → safe reclaim（read_only 可 blind retry，无副作用风险）
  不静默改变 ✅
```

---

## 32. send_report_attachment Boundary（§58）

```
DORMANT / FUTURE ✅
现有 claim 实现 = reference
NO BEHAVIOR CHANGE（不激活）✅
不让新通用 callback token 逻辑破坏它 ✅
```

---

## 33. 19000 Protocol（§44/§68）

```
MODIFY（必需）✅:
  app/local_agent_main.py
    agent_poll_and_execute: 拿到 task 后存 claim_token
    POST /result 请求体带 claim_token
  app/routers/wechat_tasks.py（9000 侧协议）
    poll 响应 + result 请求体契约

current code 事实: notify_sales result 请求体不含 claim token → 必需改 ✅
```

### Callback Schema Compatibility（§59）

```
若同一 result endpoint 承载多 task 类型:
  claim_token = optional globally, required conditionally for notify_sales running attempts
  或 mode-specific schema
  设计须冻结（C14 REQUIRED）
```

---

## 34. Backward Compatibility（§39/§46）

设计 §46"不能 backward compatible"（claim_token 是新必需字段）。

### Server-New / Agent-Old Matrix（§38）

| Server | Agent | Expected |
|---|---|---|
| old | old | current |
| new | old | ❌ 旧 agent 不发 token → server 校验失败 → 全部 task 失败 |
| old | new | ❌ 新 agent 发 token → old server 忽略（可能 OK，但未验证）|
| new | new | target |

```
new server + old agent → 不能导致任务全部 uncertain/failed ✅（须 coordinated）
```

---

## 35. Rollout（C7 REQUIRED — 第六 Hard Gate）

§37/§39/§40。设计 §47"coordinated maintenance upgrade"但未落实。

### 审批冻结（C7）：Rollout R2 — Coordinated Maintenance Cutover

```
R2 步骤:
  1. pause notify_sales creation（怎么暂停: producer 临时阻断 / feature flag）
  2. drain/resolve pending/running（确认无 running——历史从未写入，但切换时确认）
  3. DB migration（additive columns）
  4. deploy server（支持新 claim + token 校验）
  5. upgrade 19000（新协议）
  6. validate compatibility（new server + new agent）
  7. resume notify_sales
```

不走 R1（backward-compatible staged）——过渡期 claim_token 可选 = NO_CLAIM 回归窗口。

### Rollback（§40）

```
server rollback: code rollback（migration 列保留，nullable 无破坏）✅
agent rollback: 旧 agent 不发 token → new server 校验失败 → 须同时 rollback server（coordinated）
```

---

## 36. Deployment Matrix

```
old server + old agent = current ✅
new server + old agent = FAIL（token 缺失）→ 必须 coordinated
old server + new agent = UNVERIFIED（token 被忽略）→ 须验证
new server + new agent = target ✅
```

---

## 37. Permissions / Audit（§61）

```
manual mark sent / retry / cancel = 有业务副作用的治理操作
  复用现有权限体系
  最小审计: operator / task / from state / to state / action / timestamp / reason
  不新建大审计平台 ✅
  复用 raw_result（JSON）+ failure_stage 记录
```

---

## 38. Runtime Gates P2-R1~R13（§50-§54/§62）

```
P2-R1 simultaneous duplicate poll → same task claimed ≤ 1
P2-R2 multiple agent instances → only current claim holder executes
P2-R3 stale lease handling → quarantine（uncertain），no blind resend
P2-R4 late callback → rejected, new attempt intact
P2-R5 heartbeat（本设计无）→ N/A
P2-R6 uncertain no blind resend → no auto retry
P2-R7 happy path → single_send 正常完成，不回归
P2-R8 producer dedup → EXISTING_PENDING_TASK 保持 + uncertain 加入
P2-R9 expiry/callback race → 只有一个合法结果（§19）
P2-R10 duplicate callback replay → idempotent success（非 stale，§23/§24）
P2-R11 producer blocked while running → no Task B
P2-R12 producer blocked while uncertain → no blind new send task
P2-R13 retry fences old attempt → late old callback rejected, new unchanged
```

### Runtime 不发真实微信（§63）

```
所有 ownership/lease/uncertainty 验证:
  isolated DB + 9000 + fake/mock Local Agent + two+ HTTP clients
  19000 protocol E2E 用 fake UIA seam
  不自动对真实客户执行微信发送 ✅
```

---

## 39. Implementation Scope（§64）

### MODIFY

```
app/services/wechat_task_service.py
  + claim_notify_sales_task（原子 claim + claim_token + lease）
  + get_pending_wechat_tasks 改为 claim-and-return-one（limit=1 claim，C13）
  + submit_wechat_task_result 加 CAS（WHERE id AND claim_token_hash AND status=running）
  + reclaim_expired_claims（poll opportunistic → uncertain，策略 1）
  + manual resolution actions（mark_sent / retry / cancel，C8）
app/routers/wechat_tasks.py
  GET /pending 响应新增 claim_token / attempt_count / lease_expires_at
  POST /result 请求体新增 claim_token；校验失败 → 409
  + manual resolution API（mark_sent / retry / cancel，permission + audit）
app/models.py
  WechatTask 新增 4 字段 ORM 映射
app/local_agent_main.py
  agent_poll_and_execute 存 claim_token；POST /result 带 token
app/services/lead_wechat_notify_eligibility_service.py
  ACTIVE_NOTIFY_TASK_STATUSES 加入 uncertain（C2）
相关 schema/type
```

### CREATE

```
migrations/postgres/auto_wechat/versions/00XX_wechat_task_claim_lease.py（additive columns + index）
focused tests（P2-R1~R13）
implementation report
```

### READ ONLY

```
compute core / 11 consumers（P1 CLOSED，不动）
detect_reply 行为（§57）
send_report_attachment（§58）
merchant_id ORM 漂移（P2-F6，§56）
staging/prod
RB-10
```

### Frontend Scope（§65）

```
P2 first batch = API-only ✅
  uncertain manual resolution via safe callable API + permission + audit
  frontend = future（§65）
```

---

## 40. Corrections C1-C14

| Correction | 裁定 | 理由 |
|---|---|---|
| C1 Strategy-1 guarantee | ✅ REQUIRED | lease expired → uncertain（非 safe pre-side-effect auto-recovery）；删除 §15 reclaim 转换 |
| C2 Producer dedup uncertain | ✅ REQUIRED | uncertain 加入 ACTIVE_NOTIFY_TASK_STATUSES（§9）|
| C3 Lease/heartbeat | ✅ REQUIRED | 冻结 300s 默认 + L1 no-heartbeat，基于 UIA timeout 事实 |
| C4 Lease-expiry vs callback | ✅ REQUIRED | Semantics A（expiry = eligible，CAS 才 revoke）|
| C5 Callback idempotency | ✅ REQUIRED | duplicate same-attempt → idempotent success（非 stale）|
| C6 Schema fact | ✅ APPLIED | DB 有列 ORM 未映射（drift），已核对唯一事实 |
| C7 Rollout | ✅ REQUIRED | R2 coordinated cutover，冻结步骤 |
| C8 Uncertain resolution | ✅ REQUIRED | 首批 API-only（mark_sent/retry/cancel + permission + audit）|
| C9 Token lifecycle | ✅ REQUIRED | terminal 保留 hash，new attempt rotate，old fenced |
| C10 Status contract | ✅ REQUIRED | uncertain/running 消费者审查 + ACTIVE_NOTIFY_TASK_STATUSES |
| C11 claimed_at | ✅ REQUIRED | 复用 execution_started_at，不新增列 |
| C12 Claim merchant boundary | ✅ REQUIRED | JOIN lead+staff 隔离，不依赖 merchant_id 列 |
| C13 Claim cardinality | ✅ REQUIRED | 每次 poll claim exactly one（limit=1，非 batch）|
| C14 Callback schema compat | ✅ REQUIRED | claim_token optional globally / required conditionally，冻结 |

```
ALL C1-C14 = REQUIRED（correctness-critical）✅
  无 NOT_NEEDED
```

---

## 41. Verdict

```
APPROVED_WITH_CORRECTIONS

Preferred Strategy = Candidate C
  Atomic Claim + Lease + Attempt Token + Current-Attempt Callback CAS + Uncertain State
```

### 为什么是 APPROVED_WITH_CORRECTIONS 而非 APPROVED

Candidate C 核心成立（完整覆盖 F1/F2/F3 + 复用同仓模式 + 诚实保证边界），但 14 项 correctness-critical corrections 须实施前冻结。无 correction 则实施窗口会在关键语义上自由发挥（lease 时长 / expiry semantics / callback idempotency / producer uncertain / claim cardinality / rollout）。

### 为什么不是 CHANGES_REQUIRED

逐项核验（§68）：

- producer dedup 无法与 running 共存？❌ `ACTIVE_NOTIFY_TASK_STATUSES` 已含 running（:19）
- manual uncertainty 无可操作 resolution？❌ 可通过 C8 首批 API-only 解决
- lease duration 无法建立且拒绝 heartbeat？❌ 可建立 300s 基于 UIA timeout 事实（L1）
- callback fencing 无法兼容 current 19000？❌ coordinated release 可解决（C7）
- merchant isolation claim query 不安全？❌ JOIN 隔离可保持（C12）
- status schema 无法支持 uncertain？❌ plain VARCHAR，无 DB migration（§29）

---

## 42. P1 Status

```
COMPUTE-IDEMPOTENCY-001 = CLOSED（保持）✅
TECHNICAL_CLOSURE = VERIFIED
```

P1 不重新打开。P1↔P2 边界清晰。

---

## 43. P2 Status

```
P2 M04 CLAIM/LEASE = DESIGN_APPROVED_WITH_CORRECTIONS
P2-F1 NO DURABLE CLAIM = OPEN（设计已覆盖，待实施）
P2-F2 NO LEASE / CRASH RECOVERY = OPEN（设计已覆盖，待实施）
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = OPEN（设计诚实承认，待实施）
```

不得写 RESOLVED。设计批准 ≠ 实施。

---

## 44. Implementation Authorization

```
授权下一阶段:
P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION

实施窗口须满足 C1-C14 全部 REQUIRED corrections
```

本设计审批窗口：

```
DO NOT IMPLEMENT
DO NOT COMMIT
DO NOT MODIFY wechat_task_service / wechat_tasks / models / local_agent_main
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

---

## 45. Final Guarantee（§66）

审批通过后冻结：

```
SERVER OWNERSHIP: At most one current valid notify_sales attempt.
CLAIM: Task payload handed to agent only after durable claim.
FENCING: Only current attempt may authoritatively transition state.
CALLBACK: Same-attempt duplicate callbacks are idempotent; stale attempts rejected.
STALE EXECUTION: Expired/unresponsive attempts quarantined (uncertain); NOT blindly resent.
EXTERNAL WECHAT: Exactly-once delivery NOT guaranteed.
UNCERTAINTY: Potentially executed but unacknowledged sends require explicit resolution before retry.
PRODUCER: running/uncertain outstanding work prevents creation of another normal notify_sales send task.
```

不得简写 `Wechat send exactly-once`。

---

## 46. Governance State

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED ✅
P2 M04 CLAIM/LEASE = DESIGN_APPROVED_WITH_CORRECTIONS
P2-F1 / P2-F2 / P2-F3 = OPEN
```

---

## 47. Next Authorization

```
P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION
  须满足 C1-C14 全部 REQUIRED corrections
  coordinated release（server + agent，R2 cutover）
  不借实施窗口处理 detect_reply / send_report_attachment / P2-F6 / Redis / RB-10
```

---

## 48. Git Discipline

```
唯一允许新增: P2_M04_NOTIFY_SALES_CLAIM_LEASE_DESIGN_APPROVAL.md（本报告）
设计 candidate 继续 UNCOMMITTED
DO NOT PUSH
```

---

## 49. 边界遵守确认

- ✅ 未修改 M04 业务代码（wechat_task_service / wechat_tasks / models / local_agent_main）
- ✅ 未创建 migration / 未改 Local Agent / 未写 DB
- ✅ 未 commit / push
- ✅ 未改 detect_reply / send_report_attachment / merchant_id ORM drift
- ✅ 未添加 claim token / lease / uncertain
- ✅ 未添加 manual retry API / 未改 frontend
- ✅ 未 RB-10 / 未 Redis lock

---

## 50. 完成后停止

本审批窗口完成后停止。不得自行：

- 创建 migration
- 修改 wechat_task_service / notify_sales producer / 19000
- 添加 uncertain / claim token / manual retry API
- 修改 frontend
- 修 detect_reply / 激活 send_report_attachment / 修 P2-F6
- RB-10
- push

---

## 附录：审批纪律确认

- READ / DESIGN APPROVAL ONLY：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push。
- 独立核验：读设计文档 + Reality Exploration + 直接 Read `lead_wechat_notify_eligibility_service.py:19`（ACTIVE_NOTIFY_TASK_STATUSES）/ `wechat_task_service.py:100-132`（poll）/ `:302-378`（submit_result 无 CAS）/ `models.py:295-336`（WechatTask schema）/ `daily_report_delivery_service.py:433-469`（claim_delivery_task 模式）/ `0003_create_leads_tasks_core_tables.py:138-155`（DB DDL）/ `_const_eq` helper / UIA timeout。
- 未采信设计窗口自述：producer dedup（§7）、schema fact（§30）、status 约束（§14）、poll cardinality（§34）、submit_result CAS 现状（§5）均经独立代码审查。
```
