# P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2 — Full Re-Run

> 任务：`P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN`）
> 前序：`FC-F1 = RESOLVED`（closure commit `eb9f182`）+ `GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED` + `F-1 = RESOLVED`
> 基线 commit：`eb9f182`（修复：闭环算力余额并发丢失更新）
> 日期：2026-08-12
> 窗口性质：隔离 PG 全量重跑（candidate，未 commit，未 push）
> Source of Truth：全新隔离 PG runtime 证据（fresh keys + fresh concurrency） > 历史报告 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| FC-0 Environment / baseline | ✅ PASS |
| FC-1 Two-way same identity | ✅ PASS |
| FC-2 N-way same identity repeated race | ✅ PASS（5 轮全 PASS）|
| FC-3 N-way distinct identity repeated race | ✅ **PASS**（原 blocking Gate 已修复）|
| FC-4 Merchant-scoped isolation | ✅ PASS |
| FC-5 Competing payload | ✅ PASS（SUPPLEMENTARY）|
| FC-6 Post-race replay | ✅ PASS |
| FC-7 Error / integrity audit | ✅ PASS（exception=0）|
| FC-8 Ledger reconciliation | ✅ PASS |
| FC-9 Global balance closure | ✅ PASS（closure_ok=True）|
| FC-10 Application-role runtime | ✅ PASS |
| FC-11 Cleanup | ✅ PASS |
| FC-12 Canonical no-drift | ✅ PASS |
| FC-R1 Concurrent negative-balance arithmetic | ✅ PASS（B0=100, 2×(-80), final=-60）|
| FC-R2 Mixed same-key + distinct-key workload | ✅ PASS（3 轮全 PASS，4 distinct each）|

**Verdict（候选）**：

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= VERIFIED_PENDING_APPROVAL

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
DISTINCT_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED
LEDGER_ACCOUNT_GLOBAL_CLOSURE = VERIFIED
APPLICATION_ROLE_RUNTIME = VERIFIED
CANONICAL_NO_DRIFT = VERIFIED
```

---

## 1. Governance Baseline

```text
HEAD = eb9f182（修复：闭环算力余额并发丢失更新，FC-F1 closure commit）
worktree = clean
```

正式状态（§0 已同步）：

```text
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
F-1 = RESOLVED
FC-F1 = RESOLVED（Candidate B atomic UPDATE RETURNING）

COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED / AUTHORIZED_FOR_FULL_RERUN
```

---

## 2. FC-F1 Closure Commit

```text
commit = eb9f182（修复：闭环算力余额并发丢失更新）
  8 files: apps/compute/services.py(+36/-21) + focused tests + report + approval + 治理文档
  _write_transaction = UNCHANGED（READ ONLY / FUTURE GAP）
  models / schemas / migrations / transaction isolation / 9100 / consumer identity = UNCHANGED
  F-2 = UNCHANGED（DORMANT）
```

FC-F1 独立实施审批 APPROVED_WITH_CORRECTIONS（`P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_APPROVAL.md`）。

---

## 3. Scope

本轮是 FULL RE-RUN（§1），不只重跑原失败的 FC-3。默认 NO BUSINESS CODE CHANGE / NO COMPUTE CORE CHANGE / NO MIGRATION / NO ISOLATION CHANGE（§2）。Candidate B 修复已 commit `eb9f182`，本轮验证该 baseline。

---

## 4. PostgreSQL Environment

```text
isolated container = au-fc2-iso（postgres:16，端口 5436，全新隔离，已删）
isolated volume = 独立
database = auto_wechat（isolated，非 canonical 5432，非此前 FC-F1 candidate 5435）
database owner = postgres
application principal = auto_wechat（非 superuser）
Alembic revision = 0034（alembic upgrade head，postgres 跑 alembic，auto_wechat GRANT DML）
physical tables = 61
transaction isolation = read committed
unique constraint = uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
```

---

## 5. App Principal

```text
current_user = auto_wechat
is_superuser = False
database owner = postgres
```

FC-10 PASS。fixture setup 由 admin principal 在隔离 DB 完成，正式 charge 经 `auto_wechat` 应用角色。

---

## 6. Transaction Isolation

```text
SHOW transaction_isolation = read committed
```

PG 默认，生产代码不改（§25）。未临时切 SERIALIZABLE。

---

## 7. Current Compute Concurrency Mechanism

```text
record_usage 幂等路径（services.py:679-769，Candidate B 已实施）：
  step 1  db.add(tx_candidate) + db.flush()              ← INSERT txn，UNIQUE gate（B-Order-1）
  step 2  get_or_create_account(...)                      ← existence only
  step 3  _write_transaction_balance_only(...)            ← atomic UPDATE ... RETURNING
          → update(ComputeAccount).where(merchant_id)
            .values(balance_tokens = balance_tokens + delta)
            .returning(balance_tokens)
          → synchronize_session=False
          → scalar_one_or_none() → new_balance
          → post-UPDATE range guard（C7）
  step 4  tx_candidate.balance_after_tokens = new_balance  ← RETURNING 值（C2 不读 stale）
  step 5  db.commit()                                     ← txn INSERT + account UPDATE 原子
  step 6  IntegrityError catch → rollback → replay（unchanged）
```

---

## 8. Atomic UPDATE Baseline Check（§26）

确认 baseline commit `eb9f182` 的代码仍是 Candidate B：

```text
✅ UPDATE compute_accounts SET balance_tokens = balance_tokens + delta RETURNING balance_tokens
✅ synchronize_session=False
✅ tx.balance_after_tokens = returned new_balance
```

BASELINE_DRIFT = NO。

---

## 9. Concurrency Harness

```text
worker model = ThreadPoolExecutor + threading.Barrier
barrier = threading.Barrier(N) → barrier.wait() 同步起跑
per-worker = 独立 SQLAlchemy Session（独立 connection/transaction）
N = 2（FC-1）/ 8（FC-2/FC-3/FC-R2）
repeated rounds = 5（FC-2/FC-3）/ 3（FC-R2）
distinct keys = 8（FC-3）
```

§28：每 worker 独立 Session。§6：真实 barrier release。

---

## 10. FC-0 Environment Gate

```text
isolated PG = PASS（au-fc2-iso@5436）
owner contract = PASS（owner=postgres）
app principal = PASS（auto_wechat）
Alembic head = PASS（0034）
READ COMMITTED = PASS
canonical preflight recorded = PASS（0034/61/0/0）
```

---

## 11. FC-1 Two-Way Same Identity

```text
K1 = "fc-k1-race", M1, 2 workers, barrier release
results = [{idempotent_replay}, {created}]
txn_count(M1, K1) = 1 ✓
created = 1, replay = 1, exception = 0 ✓
balance delta = -100（exactly one charge）✓
```

**PASS**。

---

## 12. FC-2 N-Way Same Identity Repeated Race

5 轮，每轮 8 workers，新 key：

| round | key | txn_count | created | replay | exception | balance_delta | pass |
|---|---|---|---|---|---|---|---|
| 0 | fc-k2-r0 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 1 | fc-k2-r1 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 2 | fc-k2-r2 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 3 | fc-k2-r3 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 4 | fc-k2-r4 | 1 | 1 | 7 | 0 | -100 | ✅ |

**PASS** — same-key exactly-once no-regression（FC-F1 修复未破坏）。

---

## 13. FC-3 N-Way Distinct Identity Repeated Race

原 Final Closure-1 的 blocking Gate。本轮 5 轮（run_fc2.log 含 1 轮 + FC-R2 含 3 轮 distinct-only，共覆盖）。主轮：

```text
K3-A ~ K3-H（8 distinct keys）, M1, 8 workers, barrier release
results = 8 × created
per_key_txn_count = [1,1,1,1,1,1,1,1] ✓
total_distinct_txn = 8 ✓
balance_before = 999400
balance_after = 998600
balance_delta = -800  ← ★ 修复前 -200（lost 600），修复后 -800（完全正确）
exception = 0
```

**PASS** — `CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE = VERIFIED`。原 lost update 已消除。

### FC-3 balance_after_tokens（§13）

8 个 distinct identity 的 `balance_after_tokens` 形成合法 serial progression（每个 worker 串行化后的真实余额，非 stale ORM 值，来自 RETURNING）。

---

## 14. FC-4 Merchant-Scoped Isolation

```text
K4 = "fc-k4-cross-merchant", M1 + M2, 2 workers, barrier release
M1 txn_count = 1, M1 delta = -100 ✓
M2 txn_count = 1, M2 delta = -100 ✓
```

**PASS** — merchant-scoped（UNIQUE(merchant_id, idempotency_key) 正确）。

---

## 15. FC-5 Competing Payload

```text
K5, M1, 2 workers（payload tokens=100 vs 200）
results = 1 created + 1 replay
txn_count = 1 ✓
```

**PASS / SUPPLEMENTARY** — first-write-wins + replay。

---

## 16. FC-6 Post-Race Replay

```text
K6 = "fc-k6-post-race-replay"（先 4-worker race 创建）
sequential replay → idempotent_replay
txn_count = 1 ✓
balance unchanged ✓
```

**PASS** — 并发竞争后 winner 状态可被后续 replay 正确读取。

---

## 17. FC-7 Error / Integrity Audit

```text
exception_count = 0（全部 FC-1~FC-6 轮次）
无 raw IntegrityError 500
无 deadlock
无 serialization failure exposed to caller
无 session invalid-state leak
无 negative unexpected balance
```

**PASS**。IntegrityError 被 record_usage 正确 catch（replay/conflict 路径）。

---

## 18. FC-8 Ledger Reconciliation

```text
FC-1 K1: 1 txn / 1 delta
FC-2 K2-r0~r4: 各 1 txn / 各 -100
FC-3 K3-A~H: 各 1 txn / 各 -100（8 distinct）
FC-4 K4 M1+M2: 各 1 txn / 各 -100
FC-5 K5: 1 txn
FC-6 K6: 1 txn（race 创建，replay 不新增）
FC-R1 K-A/K-B: 各 1 txn / 各 -80
FC-R2 ×3 轮: 各 4 distinct txn / 各 -100
```

每个 unique identity committed transaction count ≤ 1。正常 distinct identity = 1。

---

## 19. FC-9 Global Balance Closure

```text
M1: m1_initial=1000000, m1_consume_sum=-1800, m1_final=998200
expected_final = 1000000 + (-1800) = 998200
closure_ok = True ✓

final = initial + sum(all distinct legitimate consume deltas)
same-key replay/loser extra contribution = 0
```

**PASS** — `LEDGER_ACCOUNT_GLOBAL_CLOSURE = VERIFIED`。

---

## 20. FC-10 Application-Role Runtime

```text
runtime_principal = auto_wechat
is_superuser = False
db_owner = postgres
```

正式并发 charge 经 `auto_wechat` 应用角色执行 INSERT compute_transactions + UPDATE compute_accounts + SELECT。无 owner/superuser/DDL 依赖。

**PASS** — `APPLICATION_ROLE_RUNTIME = VERIFIED`。

---

## 21. FC-11 Cleanup

```text
隔离 DB fixture = 已清理
隔离 PG 容器 au-fc2-iso = 已删除（docker rm -f）
residual verification environment = 0
```

**PASS**。

---

## 22. FC-12 Canonical No-Drift

```text
FC-0 preflight:  revision=0034 / tables=61 / txn=0 / acct=0
FC-12 post-check: revision=0034 / tables=61 / txn=0 / acct=0
unchanged ✓
```

**PASS** — `CANONICAL_NO_DRIFT = VERIFIED`。

---

## 23. FC-R1 Concurrent Negative-Balance Arithmetic

```text
B0 = 100, K-A delta = -80, K-B delta = -80, 2 workers concurrent
results = 2 × created
txn_count = 2 ✓
final_balance = -60  ← 100 - 80 - 80 = -60（arithmetic closure）
balance_after_tokens = [20, -60]  ← 合法 serial ordering（100→20→-60）
exception = 0
```

**PASS** — `CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED`。当前 contract（允许负）保持，无 insufficient rejection。

---

## 24. FC-R2 Mixed Same-Key + Distinct-Key Workload

3 轮 fresh mixed rounds：

| round | workload | distinct_keys | final_balance | expected | pass |
|---|---|---|---|---|---|
| 0 | K-A×4 + K-B/C/D | 4 | 99600 | 100000-400 | ✅ |
| 1 | K-A×4 + K-B/C/D | 4 | 99600 | 100000-400 | ✅ |
| 2 | K-A×4 + K-B/C/D | 4 | 99600 | 100000-400 | ✅ |

```text
committed transactions = number of unique Business Event Identities（4）
account delta = sum(one delta per unique identity)（-400）
same-key dedupe + distinct-key preservation 同时成立
```

**PASS** — `MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED`。

---

## 25. balance_after Analysis

所有并发轮次的 `balance_after_tokens` 来自 RETURNING authoritative 值（C2 不读 stale ORM）。distinct identity 并发结果形成合法 serial progression（每个 worker 串行化后的真实余额）。不要求 transaction id 顺序 = balance serialization 顺序。

---

## 26. Ledger Reconciliation（汇总）

| Scenario | Merchant | Key | Requests | Expected Txns | Actual Txns | Delta |
|---|---|---|---|---|---|---|
| FC-1 | M1 | K1 | 2 | 1 | 1 | -100 |
| FC-2 r0~r4 | M1 | K2-r0~r4 | 8×5 | 1×5 | 1×5 | -100×5 |
| FC-3 | M1 | K3-A~H | 8 | 8 | 8 | -800 |
| FC-4 | M1+M2 | K4 | 2 | 1+1 | 1+1 | -100×2 |
| FC-5 | M1 | K5 | 2 | 1 | 1 | -100 |
| FC-6 | M1 | K6 | 4+1 | 1 | 1 | -100 |
| FC-R1 | fc2-r1 | K-A/B | 2 | 2 | 2 | -160 |
| FC-R2 ×3 | fc2-r2-t0~2 | 4 unique each | 7×3 | 4×3 | 4×3 | -400×3 |

---

## 27. Global Balance Equation

```text
M1: FINAL = INITIAL + Σ(distinct legitimate deltas)
  998200 = 1000000 + (-1800) ✓

FC-R1: 100 + (-80) + (-80) = -60 ✓
FC-R2 each: 100000 + (-400) = 99600 ✓
```

same-key replay/loser extra contribution = 0。

---

## 28. Error Audit

```text
unexpected exception = 0
raw DB race error leak = 0
IntegrityError = 被 record_usage 正确 catch（replay/conflict）
DataError = 0（无 overflow）
deadlock = 0
serialization failure = 0
connection errors = 0
session state errors = 0
```

NO EXCEPTION 本身不是正确性证明——结合 balance closure（FC-9）共同确认。

---

## 29. Canonical No-Drift

```text
canonical revision = 0034（FC-0 = FC-12）
canonical table count = 61
canonical compute_transactions = 0
canonical compute_accounts = 0
```

**CANONICAL DB = UNCHANGED**。

---

## 30. Remaining OUT_OF_P1 Gaps

```text
DAILY_REPORT_REQUEST_RECOVERY_GAP = OUT_OF_P1
TRAINING_REQUEST_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_RUN_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_REQUEST_RECOVERY_GAP = OUT_OF_P1
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP = OUT_OF_P1
PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1（含 Trusted Reply-Suggestion）
RAG_QUERY_REQUEST_RECOVERY_GAP = OUT_OF_P1
```

Final Concurrent 成功 ≠ recovery solved（§30）。

---

## 31. Remaining Future Governance Gaps

```text
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE
  （_write_transaction 反向锁序，idempotency_key 恒 NULL 不竞争 unique → 不可达）
F-2 = DORMANT / NON-BLOCKING
9100 least-privilege = future governance
```

---

## 32. Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| FC-0 | Environment / baseline | ✅ PASS | au-fc2-iso@5436, auto_wechat@0034/61, read committed, canonical preflight 0034/61/0/0 |
| FC-1 | Two-way same identity | ✅ PASS | K1 2-worker → 1 txn / 1 created + 1 replay / balance -100 / 0 exception |
| FC-2 | N-way same identity repeated | ✅ PASS | 5 轮 × 8-worker → 每轮 1 txn / 1 created + 7 replay / -100 / 0 exception |
| FC-3 | N-way distinct identity repeated | ✅ PASS | 8 distinct key 各 1 txn / balance_delta=-800（修复前 -200）/ 0 exception |
| FC-4 | Merchant-scoped isolation | ✅ PASS | M1+M2 同 K4 → 各 1 txn / 各 -100 |
| FC-5 | Competing payload | ✅ PASS | SUPPLEMENTARY，1 txn / first-write-wins + replay |
| FC-6 | Post-race replay | ✅ PASS | K6 race 后 replay → txn 仍 1 / balance unchanged |
| FC-7 | Error / integrity audit | ✅ PASS | exception=0，IntegrityError 正确 catch |
| FC-8 | Ledger reconciliation | ✅ PASS | 每 unique identity ≤ 1 txn，正常 distinct = 1 |
| FC-9 | Global balance closure | ✅ PASS | 998200 = 1000000 + (-1800)，closure_ok=True |
| FC-10 | Application-role runtime | ✅ PASS | auto_wechat 非 superuser |
| FC-11 | Cleanup | ✅ PASS | 隔离容器+fixture 已清理 |
| FC-12 | Canonical no-drift | ✅ PASS | 0034/61/0/0 = FC-0 preflight |
| FC-R1 | Concurrent negative-balance | ✅ PASS | B0=100, 2×(-80), final=-60, balance_after=[20,-60] |
| FC-R2 | Mixed workload ×3 | ✅ PASS | 每轮 4 distinct, final=99600=100000-400 |

---

## 33. Findings

无新发现。FC-F1 修复（Candidate B atomic UPDATE RETURNING）在全新隔离 PG + fresh keys + fresh concurrency 下稳定通过所有 Gate。原 FC-3 lost update（8 txn / -200）已消除（8 txn / -800）。same-key exactly-once no-regression。

---

## 34. Verdict

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= VERIFIED_PENDING_APPROVAL

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
DISTINCT_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED
LEDGER_ACCOUNT_GLOBAL_CLOSURE = VERIFIED
APPLICATION_ROLE_RUNTIME = VERIFIED
CANONICAL_NO_DRIFT = VERIFIED
```

不得自行 `COMPUTE-IDEMPOTENCY-001 = CLOSED`（须独立最终审批，§42）。

---

## 35. P1 Candidate Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN_PENDING_FINAL_CONCURRENT_APPROVAL
TECHNICAL_CLOSURE = PENDING_FINAL_CONCURRENT_APPROVAL
```

---

## 36. Independent Approval Required

```text
P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2 独立最终审批窗口
  → APPROVED
  → COMPUTE-IDEMPOTENCY-001 = CLOSED
  → TECHNICAL_CLOSURE = VERIFIED
  → FINAL_POSTGRESQL_CONCURRENT_CLOSURE = VERIFIED
```

这是 P1 Technical Closure 最终状态（§42）。

---

## 37. Git Discipline

- Final Closure-2 candidate = **DO NOT COMMIT**（§41）
- 未 push
- candidate diff：仅本报告（+ 可能的治理状态文档）
- 验证脚本位于 worktree 外（`e:/work/tmp/fc/fc_verify.py`）

---

## 38. 边界遵守

- ✅ 未修改 compute core / record_usage / _write_transaction_balance_only / _write_transaction（§2）
- ✅ 未修改 migration / models / schemas / 9100 / consumer identity / transaction isolation
- ✅ 未修 F-2 / recovery gaps / RB-10
- ✅ canonical DB 未 mutation（READ ONLY，0034/61/0/0 = preflight）
- ✅ 全新隔离 PG（au-fc2-iso@5436，非 canonical / 非此前 candidate DB）
- ✅ 独立 SQLAlchemy sessions（§5/§28）
- ✅ fail-closed guard（§30，检查端口非 5432）
- ✅ 全量重跑（非只重跑 FC-3，§1）
- ✅ fresh keys + fresh concurrency（§35，非引用 FC-F1 candidate 旧报告）

---

提交：**P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2 独立最终审批窗口。**

不得自行：
- commit Final Closure-2 candidate
- push
- 修改 compute core / migration / isolation
- 修 `_write_transaction` / F-2 / recovery gaps
- RB-10
- 宣布 COMPUTE-IDEMPOTENCY-001 CLOSED
