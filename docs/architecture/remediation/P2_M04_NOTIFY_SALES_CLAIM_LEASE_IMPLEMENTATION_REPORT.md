# P2-M04 notify_sales Claim-Lease — 实施报告

> 任务：`P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION`
> 所属：P2 M04 CLAIM/LEASE（DESIGN_APPROVED_WITH_CORRECTIONS）
> 前序设计审批：`P2_M04_NOTIFY_SALES_CLAIM_LEASE_DESIGN_APPROVAL.md`（APPROVED_WITH_CORRECTIONS，Candidate C）
> Governance checkpoint：`9db3f58`（设计：批准M04微信任务执行所有权方案）
> 基线 commit：`9db3f58`
> 日期：2026-08-12
> 窗口性质：实施 + 隔离 PG runtime 验证（candidate，未 commit，未 push）

---

## 结论速览

| 维度 | 结论 |
|---|---|
| Candidate C 实施 | ✅ PASS（atomic claim + Lease + Attempt Token + Callback CAS + Uncertain State）|
| C1-C14 Compliance | ✅ ALL APPLIED |
| Migration 0035 | ✅（4 列 + index，fresh bootstrap + upgrade 验证）|
| Focused Tests | ✅ 17 passed + 3 skipped（PG runtime 覆盖并发）|
| P2-R1 simultaneous poll | ✅ PASS（8 workers, 1 winner, attempt=1）|
| P2-R2 multiple agents | ✅ PASS（5 workers, 1 winner）|
| P2-R9 expiry/callback race | ✅ PASS（SELECT FOR UPDATE 修复，reclaim CAS 不被 callback 覆盖）|
| No-regression | ✅（p0_5a 23 passed，eligibility 1 pre-existing failed）|
| Canonical no-drift | ✅（0034/61/0/0 unchanged）|

**Verdict（候选）**：

```text
P2-F1 NO DURABLE CLAIM = RESOLVED_PENDING_APPROVAL
P2-F2 NO LEASE / CRASH RECOVERY = RESOLVED_PENDING_APPROVAL
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = MITIGATED_PENDING_APPROVAL

P2 M04 CLAIM/LEASE = REMEDIATED_PENDING_APPROVAL

EXTERNAL_WECHAT_EXACTLY_ONCE = NOT GUARANTEED
BLIND_RETRY_AFTER_UNKNOWN = BLOCKED
```

---

## 1. Governance Checkpoint

```text
commit = 9db3f58（设计：批准M04微信任务执行所有权方案，未 push）
worktree = 仅 design + design approval + reality exploration，无业务代码
```

---

## 2. Approved Candidate C

```text
Atomic Claim + Lease + Attempt Token + Current-Attempt Callback CAS + Uncertain State
```

---

## 3. C1-C14 Compliance

| Correction | 状态 | 应用 |
|---|---|---|
| C1 Strategy-1 guarantee | ✅ | lease expired → uncertain（非 safe auto-recovery）；STALE ATTEMPT QUARANTINE |
| C2 Producer dedup uncertain | ✅ | `ACTIVE_NOTIFY_TASK_STATUSES` 加入 `uncertain` |
| C3 Lease/heartbeat | ✅ | `DEFAULT_LEASE_SECONDS = 300`，首批 NO HEARTBEAT |
| C4 Lease-expiry vs callback | ✅ | Semantics A：expiry = eligible for CAS；SELECT FOR UPDATE 防止 callback 覆盖 reclaim |
| C5 Callback idempotency | ✅ | 三类 callback（A current / B duplicate replay / C stale reject）|
| C6 Schema fact | ✅ | DB 有 merchant_id 列 ORM 未映射（P2-F6 FUTURE），claim 靠 JOIN |
| C7 Rollout | ✅ | R2 coordinated cutover（report 含 runbook）|
| C8 Uncertain resolution | ✅ | API-only（mark_sent / retry / cancel + permission + audit）|
| C9 Token lifecycle | ✅ | terminal 保留 hash，new attempt rotate，old fenced |
| C10 Status contract | ✅ | uncertain/running 消费者审查 + ACTIVE_NOTIFY_TASK_STATUSES |
| C11 claimed_at | ✅ | 复用 execution_started_at，不新增列 |
| C12 Claim merchant boundary | ✅ | JOIN lead+staff 隔离，不依赖 merchant_id 列 |
| C13 Claim cardinality | ✅ | 每次 poll claim exactly one（limit=1）|
| C14 Callback schema compat | ✅ | claim_token optional globally / required conditionally |

---

## 4. Changed Files

### MODIFY

| 文件 | 改动 |
|---|---|
| `apps/compute/services.py` | ❌ 未碰（P1 CLOSED）|
| `app/services/wechat_task_service.py` | +claim_notify_sales_task / +reclaim_expired_claims / +resolve_uncertain_task / submit_wechat_task_result 加 CAS + SELECT FOR UPDATE |
| `app/routers/wechat_tasks.py` | GET /pending claim-and-return-one (C13) / POST result claim_token + StaleAttemptError 409 / +resolve + +reclaim-stale API |
| `app/schemas.py` | WechatTaskResultRequest +claim_token / WechatTaskResponse +attempt_count/lease_expires_at/claim_token |
| `app/models.py` | WechatTask +4 列 ORM 映射 |
| `app/local_agent_main.py` | _write_back_task_result +claim_token fallback / poll 存 claim_token |
| `app/services/lead_wechat_notify_eligibility_service.py` | ACTIVE_NOTIFY_TASK_STATUSES +uncertain |

### CREATE

| 文件 | 内容 |
|---|---|
| `migrations/postgres/auto_wechat/versions/0035_wechat_task_claim_lease.py` | 4 列 + index |
| `tests/test_p2_m04_claim_lease.py` | P2-R1~R13 focused tests |
| `P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_REPORT.md` | 本报告 |

### READ ONLY

detect_reply 行为 / send_report_attachment / P1 compute core / migration 0001-0034 / 9100 / F-2 / P2-F6 merchant ORM drift

---

## 5. Before Flow

```text
GET /pending → SELECT pending tasks (limit=20) → return list（无 claim）
POST /result → 直接根据 success/verified/pasted/sent 设状态（无 CAS，无 token 校验）
```

P2-F1: 无 durable claim（纯 SELECT，多 Agent 可拿同 task）
P2-F2: 无 lease（crash 后重拉重发）
P2-F3: 外部不可幂等（UIA fire-and-forget）

---

## 6. After Flow

```text
GET /pending (notify_sales) → find eligible (JOIN lead+staff) → atomic CAS claim → return 1 task + claim_token
POST /result (notify_sales) → CAS check (running + token) → SELECT FOR UPDATE → terminal transition
reclaim_expired_claims → CAS (running + lease expired → uncertain)
resolve_uncertain_task → manual mark_sent / retry / cancel
```

---

## 7-14. B-Order-1 / Provisional / Atomic / synchronize_session / Authoritative / Stale Elimination / Account Existence / Same-Key Gate

- B-Order-1：UNIQUE gate（status=pending CAS）在 account mutation 前 ✅
- C1：balance_after provisional 0 → RETURNING/terminal 覆盖（notify_sales 不涉及 account balance）
- Atomic claim：`filter(status=pending).update({status:running, claim_token_hash, lease_expires_at, attempt_count+1, claimed_by, execution_started_at})` + rowcount ✅
- C9：token = secrets.token_hex(32)，DB 只存 hash，log 不记 raw token ✅
- C11：execution_started_at 复用作 claimed_at ✅
- Same-key gate：CAS WHERE status=pending → loser 0 rows → None ✅

---

## 15-21. Callback CAS / Idempotency / Late Fencing / Producer Dedup / Uncertain / Manual Resolution / Retry Fencing

- C5 三类 callback（A current / B duplicate replay / C stale reject）✅
- C4 SELECT FOR UPDATE 防止 callback 覆盖 reclaim CAS ✅
- C9 terminal 保留 hash → duplicate same-attempt replay ✅
- C2 uncertain 加入 ACTIVE_NOTIFY_TASK_STATUSES ✅
- C8 manual resolution API（mark_sent/retry/cancel + permission + audit）✅
- C33 retry：uncertain → pending，旧 token 保留，下次 claim 覆盖 ✅

---

## 25-26. detect_reply / send_report_attachment Boundary

- detect_reply：READ ONLY，无 claim_token，mode-specific behavior ✅
- send_report_attachment：DORMANT，未碰 ✅

---

## 27-28. 19000 Poll/Result Contract

- Poll：notify_sales claim-and-return-one（C13），返回 claim_token / attempt_count / lease_expires_at ✅
- Result：claim_token 在 payload 中（C35/C36），Local Agent 不生成新 token ✅
- local_agent_main.py：result["_claim_token"] 存 token，_write_back_task_result fallback 读取 ✅

---

## 29-30. Coordinated Cutover / Rollback

R2 步骤：
1. pause notify_sales creation
2. drain/resolve pending/running
3. DB migration 0035（additive columns）
4. deploy new 9000
5. upgrade 19000
6. validate new server + new agent
7. resume notify_sales

Rollback：code rollback（migration 列 nullable 无破坏）

---

## 31. Focused Tests

17 passed + 3 skipped（PG runtime 覆盖并发）：

| Test | 结果 |
|---|---|
| P2-R7 happy path | ✅ PASS |
| P2-R10 duplicate callback replay | ✅ PASS |
| P2-R4 stale token rejected | ✅ PASS |
| P2-R3 stale lease quarantine | ✅ PASS |
| P2-R6 uncertain no blind resend | ✅ PASS |
| P2-R8 uncertain blocks producer | ✅ PASS |
| C13 claim exactly one | ✅ PASS |
| C11 claimed_at | ✅ PASS |
| C3 lease 300s | ✅ PASS |
| C9 new attempt new token | ✅ PASS |
| C14 detect_reply no regression | ✅ PASS |
| Merchant isolation | ✅ PASS |
| Manual resolution ×3 | ✅ PASS |
| P2-R1/R2/R9 concurrency | ⏭️ SKIP → PG runtime |

---

## 32-44. P2-R1~R13 + Additional Tests

### 隔离 PG Runtime（au-p2-iso@5437，已删）

```text
P2-R1: 8 workers, 1 winner, status=running, attempt=1 PASS ✅
P2-R2: 5 workers, 1 winner PASS ✅
P2-R9: reclaim won (running→uncertain), callback StaleAttemptError, final=uncertain PASS ✅
  (SELECT FOR UPDATE 修复：callback 不再覆盖 reclaim CAS)
```

Migration 0035 fresh bootstrap 验证：
```text
alembic head = 0035（0034→0035 upgrade 成功）
4 columns: claim_token_hash, lease_expires_at, attempt_count(default 0), claimed_by ✅
index: idx_wechat_tasks_status_lease ✅
```

---

## 47-49. PostgreSQL Environment / Fake Agent / Canonical No-Drift

```text
isolated container = au-p2-iso（postgres:16，端口 5437，已删）
database = auto_wechat（isolated）
owner = postgres / principal = auto_wechat / revision = 0035 / isolation = read committed
canonical = 0034/61/0/0 unchanged ✅
```

---

## 50. Scope Compliance

| 范围 | 状态 |
|---|---|
| MODIFY wechat_task_service / router / schema / model / local_agent / eligibility | ✅ |
| CREATE migration 0035 + focused tests + report | ✅ |
| compute core / P1 identity | ❌ 零改 |
| detect_reply behavior | ❌ 零改 |
| send_report_attachment | ❌ 零改 |
| P2-F6 merchant ORM drift | ❌ 未碰（FUTURE）|
| F-2 / 9100 / migration 0001-0034 | ❌ 零改 |
| heartbeat / attempt_started / separate attempt table / Redis | ❌ 未加 |

---

## 51. Remaining P2-F3 Boundary

```text
P2-F3 EXTERNAL SEND NOT IDEMPOTENT = MITIGATED_PENDING_APPROVAL
EXTERNAL_EXACTLY_ONCE = NOT GUARANTEED
BLIND_RETRY_AFTER_UNKNOWN = BLOCKED（uncertain 不自动重发）
```

---

## 52-53. Future Findings / Verdict

无新 STOP 触发。SELECT FOR UPDATE 修复了 P2-R9 expiry/callback race（原 blind write 可覆盖 reclaim CAS）。

```text
P2 M04 CLAIM/LEASE = REMEDIATED_PENDING_APPROVAL
P2-F1 = RESOLVED_PENDING_APPROVAL
P2-F2 = RESOLVED_PENDING_APPROVAL
P2-F3 = MITIGATED_PENDING_APPROVAL
EXTERNAL_WECHAT_EXACTLY_ONCE = NOT GUARANTEED
```

---

## 54. Next Step

```text
P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION 独立实施审批窗口
```

candidate diff 未 commit，未 push。

---

## Git Discipline

- §0 checkpoint = `9db3f58`（已 commit，未 push）
- implementation candidate = **DO NOT COMMIT**
- 未 push

candidate diff：
```text
MODIFY: wechat_task_service.py / wechat_tasks.py / schemas.py / models.py / local_agent_main.py / lead_wechat_notify_eligibility_service.py
CREATE: 0035_wechat_task_claim_lease.py / test_p2_m04_claim_lease.py / P2_M04_NOTIFY_SALES_CLAIM_LEASE_IMPLEMENTATION_REPORT.md
```

---

提交：**P2-M04-NOTIFY-SALES-CLAIM-LEASE-IMPLEMENTATION 独立实施审批窗口。**
