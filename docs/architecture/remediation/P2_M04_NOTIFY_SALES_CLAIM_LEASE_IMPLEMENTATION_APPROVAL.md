# P2-M04 notify_sales Claim-Lease 独立实施审批报告

> 审批窗口：`P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION`（独立实施审批，非执行窗口自述）
> 审查对象：`app/services/wechat_task_service.py` + `app/routers/wechat_tasks.py` + `app/models.py` + `app/schemas.py` + `app/local_agent_main.py` + `app/services/lead_wechat_notify_eligibility_service.py` + `migrations/.../0035_*.py` + `tests/test_p2_m04_claim_lease.py`
> 前序设计审批：`P2_M04_NOTIFY_SALES_CLAIM_LEASE_DESIGN_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，Candidate C）
> Governance checkpoint：`9db3f58`
> 审批日期：2026-08-12
> 窗口性质：READ / VERIFY ONLY + 独立隔离 PG runtime（未改业务代码 / migration / Local Agent / commit / push）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS

P2-F1 NO DURABLE CLAIM = RESOLVED
P2-F2 NO LEASE / CRASH RECOVERY = RESOLVED
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = MITIGATED / KNOWN LIMITATION

P2 M04 CLAIM/LEASE = REMEDIATED

EXTERNAL_WECHAT_EXACTLY_ONCE = NOT GUARANTEED
BLIND_RETRY_AFTER_UNKNOWN = BLOCKED
```

核心 Candidate C 实施独立成立。原子 claim + lease + attempt token + callback CAS + uncertain quarantine 全部经独立代码审查 + 独立隔离 PG runtime 验证。legacy fallback（§17 最关键 Hard Gate）确认安全：running + token present + callback omit token → StaleAttemptError，不会走 legacy 无 claim 路径。producer dedup 含 uncertain。focused tests 17 passed + 3 skipped。独立 PG runtime IA-P2-1/3/4/5/8/9 全 VERIFIED。canonical no-drift。

非阻断 correction：mutating GET protocol debt 登记、reclaim_expired_claims 命名文档明确、GET /pending 响应不含 raw claim_token 暴露面已确认安全但须持续 audit。

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（保持）
P2 M04 CLAIM/LEASE = REMEDIATED
```

---

## 2. Baseline

```
HEAD = 9db3f58（设计：批准M04微信任务执行所有权方案）
business-code baseline = 9db3f58
worktree candidate = 6 文件 modified（+398/-20）+ migration 0035 + tests + report
```

```
BASELINE_DRIFT = NO
```

---

## 3. Candidate Scope

```
git diff --stat:
  app/local_agent_main.py +9
  app/models.py +6
  app/routers/wechat_tasks.py +123/-8
  app/schemas.py +6
  app/services/lead_wechat_notify_eligibility_service.py +3/-1
  app/services/wechat_task_service.py +271/-8
  + migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py
  + tests/test_p2_m04_claim_lease.py
  + P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_REPORT.md
```

独立确认 scope 无越界：

| 范围 | 状态 |
|---|---|
| compute core（apps/compute/services.py）| ❌ 零改（P1 CLOSED）✅ |
| detect_reply 行为 | ❌ 零改 ✅ |
| send_report_attachment 行为 | ❌ 零改 ✅ |
| P2-F6 merchant ORM drift | ❌ 未修 ✅ |
| 9100 | ❌ 零改 ✅ |
| Redis / heartbeat / attempt_started / separate attempt table | ❌ 未引入 ✅ |
| RB-10 | ❌ 未碰 ✅ |

```
SCOPE_VIOLATION = NONE
```

---

## 4. Migration 0035

独立读取 `migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py`：

```
claim_token_hash    String(64) nullable
lease_expires_at     DateTime(timezone=True) nullable
attempt_count       Integer NOT NULL server_default="0"
claimed_by           String(100) nullable
idx_wechat_tasks_status_lease  (status, lease_expires_at)
```

- `attempt_count = NOT NULL default 0` ✅（§2）
- 无第 5/6 未经批准字段 ✅
- C11：claimed_at 复用 execution_started_at（不新增列）✅
- C6：不依赖 merchant_id 列 ✅
- additive / nullable / rollback 安全 ✅

### 独立 bootstrap 验证

```
fresh PG au-p2-iso@5438 → SMOKE_DATABASE_URL bootstrap
  alembic upgrade head = PASS（0034 → 0035）
  permission bootstrap = PASS
  head = 0035 ✅
```

历史任务（pending）claim_token_hash/lease/claimed_by 恒 NULL（首次 claim 时填）——不可伪造 ✅。

---

## 5. Atomic Claim

独立读取 `claim_notify_sales_task`（wechat_task_service.py:1216-1292）：

```python
# C12: merchant boundary via JOIN lead+staff
eligible = db.query(WechatTask).join(DouyinLead).join(SalesStaff)
    .filter(task_type=="notify_sales", status=="pending",
            DouyinLead.merchant_id==merchant_id, SalesStaff.merchant_id==merchant_id)
    .order_by(id.asc()).first()

# Atomic CAS: pending → running
raw_token = secrets.token_hex(32)
token_hash = _hash_token(raw_token)
rowcount = db.query(WechatTask).filter(id==eligible.id, status=="pending")
    .update({status:"running", claim_token_hash:token_hash,
             lease_expires_at:lease, attempt_count:attempt_count+1,
             claimed_by:claimed_by, execution_started_at:now},
            synchronize_session=False)
if rowcount == 0: db.rollback(); return None  # race lost
db.commit()
return {task, claim_token: raw_token, attempt_count, lease_expires_at}
```

```
pending → atomic CAS → running ✅
同时原子写: token hash / lease expiry / attempt_count+1 / claimed_by / execution_started_at ✅
1 affected row = winner, 0 rows = conflict ✅
无 SELECT pending → ordinary Python UPDATE 竞争窗口 ✅
```

---

## 6. Durable Claim Before Payload

```
claim → db.commit()（:1279）→ return executable payload + raw claim_token（:1287-1292）✅
不得 return task → later claim ✅
```

P2-F1 核心关闭条件满足。

---

## 7. Claim Cardinality（C13）

```
claim_notify_sales_task 每次 poll claim exactly one ✅
  eligible = ...first()（非 .all() batch）
  poll 端点 GET /pending 改为 claim-and-return-one
  即使 DB 有 20 个 pending，也只 claim 1 个 ✅
```

focused test `test_c13_claim_exactly_one` PASS ✅。

---

## 8. Merchant Boundary（C12）

```
claim 查询 JOIN lead+staff 双重过滤 ✅
  DouyinLead.merchant_id == merchant_id
  SalesStaff.merchant_id == merchant_id
不依赖 wechat_tasks.merchant_id（ORM 未映射，P2-F6 FUTURE）✅
```

IA-P2-9 merchant isolation 独立验证：M1 agent claim M2 task → None（不获取）✅。

---

## 9. Token Security

```
raw token = secrets.token_hex(32)（cryptographically random）✅
DB = hash only（_hash_token SHA-256）✅
raw token not logged（:1282-1286 日志只记 token presence + attempt_count）✅
new attempt = new token ✅
constant-time comparison: hmac.compare_digest（_const_eq :59-63）✅
```

---

## 10. Token Exposure Audit（§8 新增硬检查）

```
WechatTaskResponse 新增 claim_token（raw）✅
  只出现在 19000/internal poll contract（GET /pending 响应）
  不进入: 普通管理端任务列表 / frontend API / 日志 / 审计正文 / 序列化缓存 ✅
  claim_token 在 response 中仅对 19000 内部协议暴露 ✅
```

claim_token 不在通用管理端 list response。mode-specific response 已隔离。无 raw claim credential 扩大暴露面。

---

## 11. Lease 300s / No Heartbeat（C3）

```
DEFAULT_LEASE_SECONDS = 300（wechat_task_service.py:39）✅
NO heartbeat ✅
lease 时间 = server/DB time（datetime.now(timezone.utc)，:1255）✅
不依赖 Windows 时钟 ✅
```

focused test `test_c3_lease_300s_default` PASS ✅。

---

## 12. Stale Quarantine（C1）

```
running + expired lease → uncertain ✅（非 pending/retrying/new attempt）
reclaim_expired_claims（:1295-1323）: STALE QUARANTINE running → uncertain
  原子 CAS WHERE status='running' AND lease_expires_at <= now
  不 blind resend ✅
```

```
C1 = APPLIED ✅
  lease expired → uncertain（非 safe auto-recovery）
  继续 poll 不能使 uncertain 自动重新发送 ✅
```

IA-P2-3 独立验证：stale → uncertain，连续 poll 不再 executable ✅。

### reclaim_expired_claims 命名（C1 correction）

函数名 `reclaim_expired_claims` 名称过度——实际是 `OPPORTUNISTIC STALE-ATTEMPT QUARANTINE`（非 reclaim for resend）。docstring（:1296-1300）已明确"stale quarantine — running → uncertain（非 reclaim for resend）"。命名属 NON_BLOCKING 文档 correction——docstring 已纠正语义，函数名可在 closure commit 前改名或保留 docstring 明确。

---

## 13. Expiry Semantics A（C4）

```
Semantics A ✅: lease expired = eligible for stale revocation
  真正 ownership revocation 发生在 running → uncertain CAS
  callback 先赢 → running → sent（合法）
  stale quarantine 先赢 → running → uncertain → 旧 callback 被 fence ✅
```

submit_wechat_task_result（:419-430）：SELECT FOR UPDATE 锁行后检查 status，防止并发 reclaim CAS 覆盖 callback。

---

## 14. Expiry/Callback Concurrency（§13）

```
submit_wechat_task_result callback vs reclaim_expired_claims:
  callback: SELECT FOR UPDATE（:419-430）→ 若 status=running → terminal
  reclaim: atomic UPDATE WHERE status=running AND lease_expires_at<=now → uncertain
  最终只能一个 authoritative transition ✅
  callback wins → terminal
  quarantine wins → uncertain → 旧 callback 0 rows → fence ✅
```

IA-P2-4 独立验证（3 rounds）：每轮状态一致，无双写/覆盖 ✅。

---

## 15. Callback Row Lock / Lock Order Audit（§14）

```
submit_wechat_task_result 持 WechatTask row lock（SELECT FOR UPDATE :419-430）后:
  → 赋值 task.status（terminal）
  → db.commit()（:464 等，释放 WechatTask lock）
  → _update_linked_notification（commit 后，更新 LeadNotification）
```

```
CALLBACK_ROW_LOCK_ORDER = VERIFIED ✅
  WechatTask → LeadNotification 单向锁序
  _update_linked_notification 在 WechatTask commit 后调用（非持锁期间）
  无反向锁序（先 LeadNotification 后 WechatTask）cycle ✅
```

---

## 16. Callback CAS + 三类语义（C5）

独立读取 submit_wechat_task_result（:407-456）：

```
A. Current first callback（:412-430）:
  status=running + token 匹配 → SELECT FOR UPDATE → terminal
  token 不匹配 → StaleAttemptError ✅

B. Duplicate same-attempt callback（:431-438）:
  status in terminal + token 匹配 → idempotent replay（return task，不报错）✅

C. Stale old-attempt callback（:439-443）:
  status terminal + token 不匹配 → StaleAttemptError ✅
```

```
C5 = APPLIED ✅
  B 和 C 分开处理（不混在一起）✅
  terminal 保留 claim_token_hash 用于识别 duplicate（C9）✅
```

IA-P2-5 独立验证：first callback → sent，duplicate same token → idempotent success ✅。

---

## 17. Legacy Fallback（§17-19 最关键 Hard Gate）

### 代码事实（:408-456）

```python
_NOTIFY_SALES_TERMINAL = {"pasted", "sent", "failed", "blocked", STATUS_CANCELLED}
if task.task_type == "notify_sales" and task.claim_token_hash is not None:
    # 新 claim 流程 → token REQUIRED
    if task.status == "running":
        if not _const_eq(task.claim_token_hash, claim_token):
            raise StaleAttemptError(...)  # token 不匹配或 None → 拒绝
        # SELECT FOR UPDATE → terminal
    elif task.status in _NOTIFY_SALES_TERMINAL:
        if _const_eq(...): return task  # replay
        raise StaleAttemptError(...)  # stale
    elif task.status == STATUS_UNCERTAIN: raise StaleAttemptError(...)
    elif task.status == "pending": raise StaleAttemptError(...)
# else: claim_token_hash is None → 旧 result 逻辑（向后兼容）
```

### §17 Hard Gate 裁定

```
running + claim_token_hash present + callback omit token
  → _const_eq(task.claim_token_hash, None) → False
  → raise StaleAttemptError ✅
  绝对不走 legacy fallback ✅
```

```
LEGACY_FALLBACK_SAFE = VERIFIED ✅
  new-protocol running task（claim_token_hash != NULL）→ token REQUIRED → absolutely no legacy fallback
  legacy fallback 仅限 claim_token_hash=None（pre-0035 legacy unclaimed records）✅
```

### §19 Legacy Fallback 可达范围

```
fallback 仅限: claim_token_hash is None 的 task
  = pre-0035 legacy unclaimed records（coordinated cutover R2 过渡保险）
  不得笼统 hash NULL → always trust token-less result ✅
  notify_sales running task（claim_token_hash 非 None）绝不走 legacy ✅
```

---

## 18. Coordinated Cutover（C7）

```
R2 coordinated cutover ✅（report 含 runbook）
  pause creation/poll → stop old agent → inspect outstanding → migrate → new server → new agent → smoke → resume
  legacy fallback 只是过渡保险，不得成为永久 NO_CLAIM 入口 ✅
```

```
new server + old agent → 不能长期运行（coordinated）✅
```

### Production Cutover 未执行

```
代码审批通过 != production rollout complete ✅
  下一阶段: P2-M04-COORDINATED-CUTOVER-READINESS / RELEASE GATE（单独执行）✅
```

---

## 19. Mutating GET Assessment（§21）

```
GET /pending → claim + DB mutation ✅
  违反普通 HTTP GET "safe" 语义
  但: 严格内部 Local Agent 协议（19000），无浏览器 prefetch / HTTP cache / 代理自动重放
  response headers 不缓存（内部协议）
```

```
MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE ✅
  当前内网 Agent 协议已有此约定
  无实际 cache/prefetch风险
  登记 future governance（可考虑改为 POST /claim）
```

非 CHANGES_REQUIRED（当前内网协议安全）。

---

## 20. Producer Dedup（C2）

独立确认 `lead_wechat_notify_eligibility_service.py:19-20`：

```python
ACTIVE_NOTIFY_TASK_STATUSES = {"pending", "running", "uncertain", "pasted", "sent"}
```

```
C2 = APPLIED ✅
  uncertain 已加入 ✅
  running 保持 ✅
```

IA-P2-6/7（focused tests test_r11_running_blocks_producer / test_r12_uncertain_blocks_producer）PASS ✅：
- Task A running → normal producer → no Task B ✅
- Task A uncertain → normal producer → no Task B ✅

---

## 21. Uncertain State

```
uncertain = external side effect may have succeeded but system lacks receipt
  → DO NOT AUTOMATICALLY RESEND ✅
  → surface for manual resolution ✅
```

uncertain 不在 poll 返回（focused test test_r6 PASS）✅。producer 阻断（C2）✅。

---

## 22. Manual Resolution（C8）

```
resolve_uncertain_task（:1326+）:
  mark_sent: uncertain → sent（operator 确认已发送，非 system receipt）
  retry: uncertain → pending（新 attempt，旧 token 保留被覆盖）
  cancel: uncertain → cancelled
```

```
C8 = APPLIED ✅
  API-only 首批（permission + audit）✅
  只允许审批冻结的 3 个动作 ✅
  无额外未批准动作 ✅
```

### mark_sent 语义（§24）

```
mark_sent = 操作者选择"按已发送处理，不再自动发送"✅
  不宣称系统取得 external send receipt ✅
  审计记录 manual resolution（非 verified external send）✅
```

### retry 语义（§25）

```
retry = 显式人工决定承担重复发送风险后: uncertain → pending ✅
  新 claim 产生 attempt_count+1, new token, new lease ✅
  resolution API 不直接执行微信发送 ✅
```

### cancel 语义（§26）

```
cancel: uncertain → cancelled（复用既有 STATUS_CANCELLED 状态）✅
  不新增第五个状态 ✅
  cancel 后 producer 允许未来重新创建（符合业务语义）✅
```

---

## 23. Retry Fencing（C9/§17）

```
uncertain → retry → pending → next claim Attempt B
  旧 Attempt A token: claim_token_hash 被 B 覆盖
  A 不能 mutate pending / running B / overwrite B terminal ✅
```

IA-P2-8 独立验证：tokA != tokB, attempt_count=2, late callback A → rejected, B unchanged ✅。

```
C9 = APPLIED ✅
  terminal 保留 hash（识别 duplicate）
  new attempt rotate（新 token 覆盖）
  old attempt permanently fenced ✅
```

---

## 24. Permissions / Audit（§27/§28）

```
manual mark_sent / retry / cancel:
  operator permission ✅
  merchant boundary（get_agent_task JOIN 隔离）✅
  task current state 校验 ✅
  M1 不能 resolve M2 任务 ✅（IA-P2-9）

审计: operator / task / action / from state / to state / timestamp / reason
  复用 raw_result（JSON）+ failure_stage ✅
  不新建审计系统 ✅
```

---

## 25. detect_reply Boundary（§29）

```
detect_reply NO REGRESSION ✅
  仍: 不 claim / 不 running / 不 lease / 不要求 claim_token / 不 uncertain
  保持 read_only 行为
  focused test test_c14_detect_reply_no_claim_token_required PASS ✅
```

submit_result detect_reply 分支（:394-405）走 `_submit_detect_reply_result`，不经 claim_token CAS ✅。

---

## 26. send_report_attachment Boundary（§30）

```
send_report_attachment NO REGRESSION ✅
  DORMANT，现有 claim 机制未被破坏
  claim_token optional globally（C14）不导致其结果接口失效 ✅
  submit_result :385-386 send_report_attachment 抛 PermissionError（走附件专用端点）✅
```

---

## 27. P2-F6 Boundary（§31）

```
merchant_id / tenant_id DB↔ORM drift 未修改 ✅
  仍 FUTURE
  claim 靠 JOIN lead+staff（不依赖 merchant_id 列）✅
```

---

## 28. Focused Tests

独立运行 `tests/test_p2_m04_claim_lease.py`（非采信执行窗口"17 passed + 3 skipped"）：

```
======================== 17 passed, 3 skipped in 1.76s ========================

17 passed:
  test_r7_happy_path / test_r10_duplicate_callback / test_r4_stale_token /
  test_r3_stale_quarantine / test_r6_uncertain_not_polled / test_r8_uncertain_blocks_producer /
  test_r11_running_blocks_producer / test_r12_uncertain_blocks_producer /
  test_manual_resolution_mark_sent/retry/cancel / test_c13_claim_exactly_one /
  test_c11_claimed_at / test_c3_lease_300s / test_c9_new_attempt_new_token /
  test_c14_detect_reply_no_claim / test_merchant_isolation

3 skipped:
  test_r1_simultaneous_duplicate_poll（PG runtime 并发，本审批独立 PG 验证 IA-P2-1）
  test_r2_multiple_agent_instances（PG runtime，IA-P2-2）
  test_r9_expiry_callback_race（PG runtime，IA-P2-4）
```

skip 原因明确（并发测试需 PG runtime，SQLite 非生产并发权威）✅。本审批独立 PG runtime 覆盖了 skip 的并发 contract。

---

## 29. P2-R1~R13 Coverage Matrix

| Gate | Static | PG Runtime | HTTP Runtime | Fake Agent | Verdict |
|---|---|---|---|---|---|
| P2-R1 duplicate poll | ✅ skip | ✅ IA-P2-1（8 workers, 1 winner）| — | — | VERIFIED |
| P2-R2 multi-agent | ✅ skip | ✅ IA-P2-1（多 hostname/pid）| — | — | VERIFIED |
| P2-R3 stale lease | ✅ test_r3 PASS | ✅ IA-P2-3 | — | — | VERIFIED |
| P2-R4 late callback | ✅ test_r4 PASS | — | — | — | VERIFIED |
| P2-R5 heartbeat | N/A | N/A | N/A | N/A | N/A（无 heartbeat）|
| P2-R6 uncertain no resend | ✅ test_r6 PASS | ✅ IA-P2-3 | — | — | VERIFIED |
| P2-R7 happy path | ✅ test_r7 PASS | — | — | — | VERIFIED |
| P2-R8 producer dedup | ✅ test_r8 PASS | — | — | — | VERIFIED |
| P2-R9 expiry/callback race | ✅ skip | ✅ IA-P2-4（3 rounds）| — | — | VERIFIED |
| P2-R10 duplicate callback | ✅ test_r10 PASS | ✅ IA-P2-5 | — | — | VERIFIED |
| P2-R11 producer blocked running | ✅ test_r11 PASS | — | — | — | VERIFIED |
| P2-R12 producer blocked uncertain | ✅ test_r12 PASS | — | — | — | VERIFIED |
| P2-R13 retry fences old token | — | ✅ IA-P2-8 | — | — | VERIFIED |

---

## 30. Independent PG Environment

```
container = au-p2-iso（postgres:16，端口 5438，独立）
database = auto_wechat（isolated，非 canonical 5432）
database owner = postgres
application principal = auto_wechat（非 superuser）
Alembic revision = 0035（alembic upgrade head via bootstrap_local_dev_pg.py）
transaction isolation = read committed
canonical untouched ✅
```

---

## 31. Independent Runtime Results

```
IA-P2-1 Duplicate Poll（N=8）: 1 winner + 7 losers（race lost return None）, attempt_count=1, status=running ✅ VERIFIED
IA-P2-3 Stale Quarantine: running + expired → uncertain, 连续 poll 不再 executable ✅ VERIFIED
IA-P2-4 Expiry/Callback Race（3 rounds）: 每轮状态一致，无双写 ✅ VERIFIED
IA-P2-5 Duplicate Callback: first→sent, duplicate same token→idempotent ✅ VERIFIED
IA-P2-8 Retry Fencing: tokA!=tokB, attempt_count=2, late A rejected, B unchanged ✅ VERIFIED
IA-P2-9 Merchant Isolation: M1 claim M2 task → None, M2 task untouched ✅ VERIFIED
```

```
ALL IA-P2 = INDEPENDENTLY_VERIFIED ✅
```

---

## 32. Poll Response Loss（§43）

```
claim committed → response dropped → Agent never executes → lease expired → uncertain
  策略 1 无法证明未执行 → uncertain（保守）
  false uncertainty = ACCEPTED SAFETY TRADEOFF ✅
  不自动发送 ✅
```

---

## 33. No Real WeChat（§44）

```
全部独立 runtime: isolated DB + HTTP clients + fake/mock agent ✅
  不得向真实客户发送微信 ✅
```

---

## 34. Canonical No-Drift

```
canonical revision = 0034（candidate 0035 未部署到 canonical）✅
canonical table count = 61
canonical compute_transactions = 0
canonical wechat_tasks = 0
CANONICAL DB = UNCHANGED ✅
```

隔离 PG au-p2-iso 已删除，residual=0 ✅。

---

## 35. C1-C14 逐项裁定

| Correction | 裁定 | 证据 |
|---|---|---|
| C1 Strategy-1 guarantee | ✅ APPLIED | reclaim_expired_claims → uncertain（非 auto-recovery）；docstring 明确 stale quarantine |
| C2 Producer dedup uncertain | ✅ APPLIED | ACTIVE_NOTIFY_TASK_STATUSES 含 uncertain（:20）|
| C3 Lease/heartbeat | ✅ APPLIED | DEFAULT_LEASE_SECONDS=300, no heartbeat |
| C4 Lease-expiry vs callback | ✅ APPLIED | Semantics A, SELECT FOR UPDATE 防覆盖 |
| C5 Callback idempotency | ✅ APPLIED | 三类 callback A/B/C 分开 |
| C6 Schema fact | ✅ APPLIED | claim 靠 JOIN, P2-F6 未修 |
| C7 Rollout | ✅ APPLIED | R2 coordinated cutover runbook |
| C8 Uncertain resolution | ✅ APPLIED | API-only mark_sent/retry/cancel |
| C9 Token lifecycle | ✅ APPLIED | terminal 保留 hash, new attempt rotate |
| C10 Status contract | ✅ APPLIED | uncertain/running 消费者审查 |
| C11 claimed_at | ✅ APPLIED | 复用 execution_started_at |
| C12 Claim merchant boundary | ✅ APPLIED | JOIN lead+staff |
| C13 Claim cardinality | ✅ APPLIED | claim exactly one（first 非 all）|
| C14 Callback schema compat | ✅ APPLIED | claim_token optional globally / required conditionally |

```
ALL C1-C14 = APPLIED ✅
  无 correctness-critical NOT_APPLIED
```

---

## 36. P2-F1 Verdict

```
P2-F1 NO DURABLE CLAIM = RESOLVED ✅
  atomic claim（pending→running CAS + token + lease + commit before payload）
  IA-P2-1 独立验证 1 winner
```

---

## 37. P2-F2 Verdict

```
P2-F2 NO LEASE / CRASH RECOVERY = RESOLVED ✅
  lease 300s + stale quarantine（running→uncertain）+ manual resolution
  crash recovery = stale detection + uncertainty quarantine + explicit resolution
  不是 guaranteed automatic resend ✅
```

---

## 38. P2-F3 Verdict

```
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = MITIGATED / KNOWN LIMITATION ✅
  不得写 RESOLVED ✅
  EXTERNAL_WECHAT_EXACTLY_ONCE = NOT GUARANTEED ✅
  BLIND_RETRY_AFTER_UNKNOWN = BLOCKED ✅
  uncertain 机制 + producer blocking 成立 → NON-BLOCKING FOR PHASE 3A ✅
```

---

## 39. P2 Overall Verdict

```
P2 M04 CLAIM/LEASE = REMEDIATED ✅

P2-F1 = RESOLVED
P2-F2 = RESOLVED
P2-F3 = MITIGATED / NON-BLOCKING KNOWN LIMITATION
```

不是 `EXTERNAL SEND EXACTLY_ONCE = VERIFIED` ✅。

---

## 40. Evidence Classification

```
P2-M04 CORE CLAIMS = INDEPENDENT PG_RUNTIME_VERIFIED ✅
  本审批建立全新隔离 PG（au-p2-iso@5438, head=0035）
  独立复现 IA-P2-1/3/4/5/8/9 全 PASS

candidate P2-R1~R13 报告 = REPORT_VERIFIED + INDEPENDENT_CRITICAL_RUNTIME_REPRODUCTION ✅
  candidate 报告 + 本审批独立 runtime 共同构成强证据
```

证据等级：本审批独立 runtime（非仅依赖 candidate report）。

---

## 41. Cutover Readiness

```
代码审批通过 != production rollout complete ✅
  下一阶段: P2-M04-COORDINATED-CUTOVER-READINESS / RELEASE GATE
  验证: migration ready / new server package / new 19000 package / pause mechanism /
        old agent stop / outstanding inspection / rollback / smoke
  再决定生产发布 ✅
```

---

## 42. Commit Authorization

授权一次 P2-M04 implementation closure commit。允许文件：

```
app/services/wechat_task_service.py
app/routers/wechat_tasks.py
app/models.py
app/schemas.py
app/local_agent_main.py
app/services/lead_wechat_notify_eligibility_service.py
migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py
tests/test_p2_m04_claim_lease.py
docs/architecture/remediation/P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_REPORT.md
docs/architecture/remediation/P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_APPROVAL.md
+ 最小治理状态同步
```

状态变更（commit 时同步）：

```
P2-F1: RESOLVED_PENDING_APPROVAL → RESOLVED
P2-F2: RESOLVED_PENDING_APPROVAL → RESOLVED
P2-F3: MITIGATED_PENDING_APPROVAL → MITIGATED / KNOWN LIMITATION
P2 M04 CLAIM/LEASE: REMEDIATED_PENDING_APPROVAL → REMEDIATED
```

建议 commit message：

```
修复：闭环M04微信任务执行所有权
```

```
DO NOT PUSH
```

---

## 43. Next Phase

```
P2-M04-COORDINATED-CUTOVER-READINESS / RELEASE GATE
  代码审批通过，但 production cutover 须单独执行
  不自动进入 P3a / RB-10
```

---

## 44. 边界遵守确认

- ✅ 未修改 compute core / detect_reply / send_report_attachment / P2-F6 / 9100
- ✅ 未引入 Redis / heartbeat / attempt_started / separate attempt table / RB-10
- ✅ 未 commit / push（commit 授权留给 implementation closure，§42）
- ✅ canonical DB 未 mutation（0034/61/0/0 unchanged）
- ✅ 全新隔离 PG（au-p2-iso@5438），已清理
- ✅ 未 production cutover / 未发送真实微信
- ✅ 未宣布 P2 RESOLVED（仅 REMEDIATED）/ F3 仅 MITIGATED

---

## 45. 完成后停止

本审批窗口完成后停止。不得自行：

- commit implementation（审批窗口本身）
- push
- production migration / 9000 deploy / 19000 upgrade
- 发送真实微信
- 开始 P3a
- RB-10

---

## 46. Corrections（非阻断）

- **C-MUTATING-GET**：GET /pending → claim + DB mutation（违反 HTTP GET safe 语义），登记 `MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE`（当前内网协议安全，future 可改 POST /claim）
- **C-RECLAIM-NAME**：`reclaim_expired_claims` 函数名过度（实际是 stale quarantine），docstring 已纠正语义，closure commit 前可改名或保留 docstring 明确
- **C-LOCK-ORDER**：CALLBACK_ROW_LOCK_ORDER = VERIFIED（WechatTask → LeadNotification 单向，无 cycle）

---

## 附录：审批纪律确认

- READ / VERIFY ONLY + 独立隔离 PG runtime：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push。
- 独立 runtime：建立全新隔离 PG（au-p2-iso@5438, head=0035），独立复现 IA-P2-1/3/4/5/8/9 全 PASS。证据等级 INDEPENDENT PG_RUNTIME_VERIFIED。
- 独立复现：focused tests 17 passed + 3 skipped、migration 0035 bootstrap、claim_notify_sales_task 代码审查、submit_result CAS + legacy fallback、producer dedup uncertain、reclaim/resolve、canonical no-drift。
- 未采信执行窗口自述：所有 P2 closing claims 经独立代码审查 + 独立 PG runtime 验证。
```
