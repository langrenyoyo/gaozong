# P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE — Final PostgreSQL Concurrent Closure 验证报告

> 任务：`P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-1`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE`）
> 前序：`F-1 = RESOLVED` + `GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED`（closure commit `4a5cd15`）
> 基线 commit：`4a5cd15`（审计：闭环全局Active算力幂等身份）
> 日期：2026-08-11
> 窗口性质：隔离 PG 并发验证（candidate，未 commit，未 push）
> Source of Truth：隔离 PG 真实并发 runtime 证据 > 代码分析 > 推测

---

## 结论速览

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= FAILED

FC-F1: CONCURRENT LOST UPDATE
  record_usage 幂等路径在多 worker 并发 distinct identity 扣费时，
  balance 更新出现 lost update（部分扣费被覆盖）
```

| Gate | 结论 |
|---|---|
| FC-0 Isolated PG / principal / revision | ✅ PASS |
| FC-1 Two-way same identity race | ✅ PASS |
| FC-2 N-way same identity repeated race | ✅ PASS |
| FC-3 Concurrent distinct identities / lost-update | ❌ **FAIL** |
| FC-4 Merchant-scoped identity isolation | ✅ PASS |
| FC-5 Competing payload behavior | ✅ PASS（SUPPLEMENTARY，first-write-wins + replay）|
| FC-6 Post-race sequential replay | ✅ PASS |
| FC-7 Error / deadlock / integrity audit | ✅ PASS（exception_count=0，无 raw 500）|
| FC-8 Ledger reconciliation | ❌ **FAIL**（txn 全存在但 balance 不闭合）|
| FC-9 Global balance closure | ❌ **FAIL** |
| FC-10 Application-role runtime | ✅ PASS |
| FC-11 Cleanup | ✅ PASS |
| FC-12 Canonical no-drift | ✅ PASS |

核心 PASS（same-identity exactly-once）：FC-1/FC-2/FC-6/FC-7 证明同 identity 并发下 exactly-once（1 txn / replay convergence / 无 raw IntegrityError 500）。**幂等唯一约束 + IntegrityError catch 路径正确**。

核心 FAIL（concurrent distinct identity lost update）：FC-3/FC-8/FC-9 证明同 merchant 不同 identity 并发扣费时 **balance 出现 lost update**（部分扣费被覆盖，最终余额不闭合）。

---

## 1. Governance Baseline

```text
HEAD = 4a5cd15（审计：闭环全局Active算力幂等身份）
worktree = clean
```

正式状态（§0 已确认）：

```text
F-1 = RESOLVED
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
TECHNICAL_CLOSURE = PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE
Final PostgreSQL Concurrent Closure = AUTHORIZED_TO_START
```

§0 提到的 AGENTS.md / CROSS_MODULE_RISK_REGISTER.md modified 已在上一轮 commit `4a5cd15` 中处理（属已批准 F-1/Audit-2 治理状态同步），worktree clean，无可疑改动。

---

## 2. Scope

本轮验证 PostgreSQL concurrent exactly-once billing。不重新验证 identity / Global Audit / recovery / F-2 / 9100 / RB-10。

```text
NO BUSINESS CODE CHANGE
NO MIGRATION CHANGE
NO COMPUTE CORE CHANGE
```

发现并发 bug 后按 §35：STOP，不修 compute core，进入独立返工设计。

---

## 3. PostgreSQL Environment

```text
isolated container = au-fc-iso（postgres:16，端口 5434，独立 volume）
database = auto_wechat（isolated，非 canonical 5432）
database owner = postgres
application principal = auto_wechat（非 superuser）
revision = 0034（alembic upgrade head，postgres 跑 alembic，auto_wechat GRANT DML）
table count = 61
transaction isolation = read committed（PG 默认，生产代码不改）
unique constraint = uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
compute_accounts unique = uk_compute_accounts_merchant UNIQUE(merchant_id)
```

bootstrap 符合已批准 principal contract（database owner=postgres 跑 alembic，app principal=auto_wechat 运行时 DML）。

---

## 4. Application Principal

```text
current_user = auto_wechat
is_superuser = False
database owner = postgres
```

所有并发扣费经 `auto_wechat` 应用角色，非 postgres superuser（FC-10 PASS）。

---

## 5. Transaction Isolation

```text
SHOW transaction_isolation = read committed
```

PG 默认，生产代码不改（§6）。未临时切 SERIALIZABLE。

---

## 6. Compute Core Current Concurrency Mechanism

### 6.1 record_usage 幂等路径（apps/compute/services.py:679-769）

```python
db.add(tx_candidate)
try:
    db.flush()  # INSERT txn（未 commit）
    # flush 成功 → 获得 ownership
    account = get_or_create_account(db, merchant_id, autocommit=False)  # ★ 普通SELECT，加载account到identity map
    _write_transaction_balance_only(db, account, delta_tokens=-billed_tokens, ...)  # ★ SELECT FOR UPDATE + balance update
    tx_candidate.balance_after_tokens = account.balance_tokens
    db.commit()  # 单次 commit：transaction + balance 原子
except IntegrityError:
    db.rollback()  # UNIQUE 冲突 → 查已存在行 → replay/conflict
    ...
```

### 6.2 _write_transaction_balance_only（:150-184）

```python
locked = db.query(ComputeAccount).filter(...).with_for_update().first()  # SELECT FOR UPDATE
new_balance = locked.balance_tokens + delta_tokens  # ★ 基于 locked.balance_tokens 计算
locked.balance_tokens = new_balance
db.flush()
```

### 6.3 get_or_create_account（:110-124）

```python
account = db.query(ComputeAccount).filter(...).first()  # ★ 普通SELECT，无FOR UPDATE
```

### 6.4 幂等唯一约束路径（正确）

- same identity 并发：`db.flush()` INSERT → UNIQUE 冲突 → `IntegrityError` catch → rollback → 查已存在行 → `idempotent_replay`（不扣费）。**无 raw 500，replay convergence 正确**（FC-1/FC-2/FC-6 PASS）。

### 6.5 余额更新路径（★ lost update 根因）

- distinct identity 并发：多个 worker 同时 `get_or_create_account`（普通 SELECT，加载 account 到各自 session identity map）→ `_write_transaction_balance_only` 的 `with_for_update()` 获取行锁串行化，但 **SQLAlchemy ORM identity map 可能返回已缓存对象，不重新 hydrate `balance_tokens` 属性** → `locked.balance_tokens` 是 `get_or_create_account` 时刻的旧值 → `new_balance = 旧值 + delta` → commit 覆盖其他 worker 的更新 → lost update。

详见 §13 根因分析。

---

## 7. Unique Constraint

```text
conname = uk_compute_transactions_merchant_idempotency
definition = UNIQUE (merchant_id, idempotency_key)
scope = merchant-scoped（merchant_id + idempotency_key 复合）
idempotency_key = varchar, nullable=YES（NULL 不参与唯一约束，但 ACTIVE None=0 已由 Audit-2 确认）
```

FC-4 硬 Gate：merchant-scoped ✓（不同 merchant 同 key 不互相 dedupe）。

---

## 8. Concurrency Harness

```text
worker model = ThreadPoolExecutor + threading.Barrier
barrier = threading.Barrier(N) → barrier.wait() 同步起跑
per-worker = 独立 SQLAlchemy Session（独立 connection/transaction）
N = 2（FC-1）/ 8（FC-2/FC-3）
repeated rounds = 5（FC-2，每轮新 key）
distinct keys = 8（FC-3，每 worker 不同 key）
```

§28：每个 worker 独立 Session（非共享），代表真实 PostgreSQL 事务竞争。§8：未在 record_usage 内部加 sleep/lock/debug barrier。

---

## 9. Barrier / Worker Model

```text
N workers prepared → threading.Barrier(N).wait() → requests launched concurrently
record start timestamps = time.perf_counter() per worker
finish results = {status, elapsed_ms} per worker
```

---

## 10. FC-1 Two-Way Same Identity Race

```text
K1 = "fc-k1-race", M1, 2 workers, barrier release
results = [{created, 32ms}, {idempotent_replay, ...}]
txn_count(M1, K1) = 1 ✓
balance_delta = -100 ✓（exactly one charge）
exception_count = 0 ✓
```

**PASS** — same identity 并发 → exactly one transaction + one balance delta + replay convergence + 无 raw 500。

---

## 11. FC-2 N-Way Repeated Race

5 轮，每轮 8 workers，新 key：

| round | key | txn_count | created | replay | exception | balance_delta | pass |
|---|---|---|---|---|---|---|---|
| 0 | fc-k2-r0 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 1 | fc-k2-r1 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 2 | fc-k2-r2 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 3 | fc-k2-r3 | 1 | 1 | 7 | 0 | -100 | ✅ |
| 4 | fc-k2-r4 | 1 | 1 | 7 | 0 | -100 | ✅ |

**PASS** — N-way fresh-key race 稳定 exactly-once（1 created + 7 replay / 无 exception）。

---

## 12. FC-3 Concurrent Distinct Events

```text
K3-A ~ K3-H（8 distinct keys）, M1, 8 workers, barrier release
results = 8 × created（全部首次创建成功）
per_key_txn_count = [1,1,1,1,1,1,1,1] ✓（每 key exactly 1 txn）
total_distinct_txn = 8 ✓
balance_before = 999400
balance_after = 999200
balance_delta = -200  ← ★ 应为 -800
expected_delta = -800
exception_count = 0
```

**FAIL** — 8 个 distinct identity 各 1 txn（txn 层正确），但 balance 只扣了 200（应扣 800）→ **lost update 600**。

### 精确复现（独立诊断，3 轮）

```text
trial 0: 8 created, txn_sum=-800, bal=999800 (expected 999200, lost 600)
trial 1: 8 created, txn_sum=-1600, bal=999600 (expected 998400, lost 600)
trial 2: 8 created, txn_sum=-2400, bal=999400 (expected 997600, lost 600)
```

稳定复现：每轮 8 worker 只扣 200（2×100），丢失 600（6×100）。2-worker 不暴露（时序窗口小，step 2 get_or_create_account 可能在第一个 commit 后才执行，读到新值）。

---

## 13. Lost-Update Verification + 根因分析

### 13.1 现象

- 8 个 distinct identity 并发，全部 `created`（txn INSERT 全成功，无 UNIQUE 冲突）
- txn_sum = -800（8 × -100，txn 表 delta 正确）
- 但 final balance 只扣了 200（应扣 800）→ 600 的扣费被覆盖（lost update）

### 13.2 根因（代码分析，非修复）

record_usage 幂等路径余额更新序列：

```python
# step 1: INSERT txn（flush，未 commit）
db.add(tx_candidate)
db.flush()

# step 2: ★ get_or_create_account — 普通SELECT，加载account到session identity map
account = get_or_create_account(db, merchant_id, autocommit=False)
#   → db.query(ComputeAccount).filter(...).first()  无 FOR UPDATE
#   → account.balance_tokens = 旧值（此时刻的 DB 值）
#   → account 对象进入 SQLAlchemy identity map

# step 3: _write_transaction_balance_only — SELECT FOR UPDATE + balance update
locked = db.query(ComputeAccount).filter(...).with_for_update().first()
#   → 发 SELECT ... FOR UPDATE SQL（获取行锁，串行化）
#   → 但 SQLAlchemy ORM identity map 返回 step 2 已加载的同一对象
#   → locked.balance_tokens = 旧值（未从 FOR UPDATE 结果重新 hydrate）
new_balance = locked.balance_tokens + delta_tokens  # ★ 旧值 + delta
locked.balance_tokens = new_balance
db.flush()
db.commit()  # ★ 写入旧值+delta，覆盖其他 worker 的更新
```

**核心问题**：`get_or_create_account`（step 2，普通 SELECT）先加载 account 到 identity map，`_write_transaction_balance_only`（step 3）的 `with_for_update()` 虽然获取行锁，但 SQLAlchemy ORM 的 identity map 机制**默认不重新 hydrate 已加载对象的属性**。`locked` 指向 identity map 里的旧对象，`locked.balance_tokens` 是 step 2 时刻的旧值，而非 FOR UPDATE 后的 DB 最新值。

### 13.3 时序分析

8-worker 并发：
1. 多个 worker 同时执行 step 2（get_or_create_account），读到相同旧值 B（如 999400），各自缓存到自己的 session identity map
2. step 3 FOR UPDATE 串行化：Worker 1 获得锁 → identity map 里 balance=B=999400 → 写 999400-100=999300 → commit
3. Worker 2 等待锁 → 获得后 FOR UPDATE 返回 identity map 里的对象（balance 仍=999400，未刷新）→ 写 999400-100=999300 → commit → **覆盖 Worker 1 的 999300**（lost update）
4. 依此类推，只有最后少数 worker 的更新生效

2-worker 不暴露的原因：时序窗口小，Worker 2 的 step 2 可能在 Worker 1 commit 之后执行（读到新值 999300），所以 2-worker 正常。

### 13.4 修复方向（不在本窗口修，§35）

候选修复（需独立返工设计审批）：
1. `_write_transaction_balance_only` 的 FOR UPDATE 查询加 `.execution_options(populate_existing=True)` 强制刷新 identity map
2. 或在 FOR UPDATE 前 `db.expire(account)` 使其过期
3. 或合并 get_or_create_account + FOR UPDATE 为单步（直接 FOR UPDATE 查询，无前置普通 SELECT）
4. 或用 `db.query(ComputeAccount).with_for_update().populate_existing().first()`

**本窗口不实施任何修复**（§2 NO COMPUTE CORE CHANGE）。

---

## 14. FC-4 Merchant Isolation

```text
K4 = "fc-k4-cross-merchant", M1 + M2, 2 workers, barrier release
M1 txn_count = 1, M1 delta = -100 ✓
M2 txn_count = 1, M2 delta = -100 ✓
```

**PASS** — merchant-scoped identity isolation（同 key 不同 merchant 各 1 独立 charge，互不 dedupe）。UNIQUE(merchant_id, idempotency_key) 正确。

---

## 15. FC-5 Competing Payload

```text
K5 = "fc-k5-competing-payload", M1, 2 workers（payload tokens=100 vs 200）
results = 1 created + 1 replay/idempotent_replay
txn_count = 1 ✓
```

**PASS（SUPPLEMENTARY）** — 同 key 不同 payload → first-write-wins + replay（不产生两次 charge）。

---

## 16. FC-6 Post-Race Replay

```text
K6 = "fc-k6-post-race-replay"（先 4-worker race 创建）
sequential replay → idempotent_replay
txn_count = 1 ✓
balance unchanged ✓
```

**PASS** — 并发竞争后 winner 状态可被后续 replay 正确读取（txn remains 1, balance unchanged）。

---

## 17. FC-7 Error Audit

```text
exception_count = 0（全部 FC-1~FC-6 轮次）
无 raw IntegrityError 500
无 deadlock
无 serialization failure exposed to caller
无 session invalid-state leak
```

**PASS** — IntegrityError 被 record_usage 正确 catch（replay/conflict 路径），不泄漏为未处理异常。same-identity 并发的 response convergence 正确。

但 FC-3 的 lost update 不产生异常（静默覆盖），这是更隐蔽的问题（§22 error audit 不捕获静默 lost update，需 balance closure 才发现）。

---

## 18. Ledger Reconciliation

```text
FC-3 ledger: 8 distinct keys 各 1 txn，txn_sum=-800
但 balance_delta = -200（不闭合，差 600）
```

**FAIL** — txn 表正确（各 key 1 txn）但 balance 不闭合（lost update）。

---

## 19. Global Balance Closure

```text
m1_initial = 1,000,000
m1_consume_sum (all distinct legitimate deltas) = -1,800
m1_final = 998,800
expected_final = 1,000,000 + (-1,800) = 998,200
closure_ok = False（差 600，lost update）
```

**FAIL** — final balance ≠ initial + sum(distinct legitimate deltas)。同 identity replay/loser 贡献 0 extra delta（正确），但 distinct identity 并发的 lost update 导致余额少扣。

---

## 20. Application-Role Evidence

```text
runtime_principal = auto_wechat
is_superuser = False
database owner = postgres
```

**PASS** — 并发扣费经 `auto_wechat` 应用角色，非 postgres superuser。

---

## 21. Cleanup

```text
隔离 DB fixture = 已清理（DELETE compute_transactions + compute_accounts for fc-m1/fc-m2）
隔离 PG 容器 au-fc-iso = 已删除（docker rm -f）
residual verification environment = 0
```

**PASS**。

---

## 22. Canonical No-Drift

```text
canonical revision = 0034
canonical table count = 61
canonical compute_transactions = 0
canonical compute_accounts = 0
```

**PASS** — canonical local DB unchanged（READ ONLY，隔离 PG 已删除）。

---

## 23. FC Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| FC-0 | Isolated PG / principal / revision | ✅ PASS | au-fc-iso@5434, auto_wechat@0034/61, read committed, UNIQUE(merchant_id, idempotency_key) |
| FC-1 | Two-way same identity race | ✅ PASS | K1 2-worker → 1 txn / 1 created + 1 replay / balance -100 / 0 exception |
| FC-2 | N-way same identity repeated race | ✅ PASS | 5 轮 × 8-worker → 每轮 1 txn / 1 created + 7 replay / balance -100 / 0 exception |
| FC-3 | Concurrent distinct identities / lost-update | ❌ **FAIL** | 8 distinct key 各 1 txn（txn 正确）但 balance 只扣 -200（应 -800）→ lost update 600，3 轮稳定复现 |
| FC-4 | Merchant-scoped identity isolation | ✅ PASS | M1+M2 同 K4 → 各 1 独立 txn / 各 -100 |
| FC-5 | Competing payload behavior | ✅ PASS | SUPPLEMENTARY，同 key 不同 payload → 1 txn / first-write-wins + replay |
| FC-6 | Post-race sequential replay | ✅ PASS | K6 race 后 sequential replay → txn 仍 1 / balance unchanged / idempotent_replay |
| FC-7 | Error / deadlock / integrity audit | ✅ PASS | exception_count=0，IntegrityError 正确 catch，无 raw 500 |
| FC-8 | Ledger reconciliation | ❌ **FAIL** | 8 distinct txn 全存在但 balance 不闭合 |
| FC-9 | Global balance closure | ❌ **FAIL** | final≠initial+sum(deltas)，差 600 |
| FC-10 | Application-role runtime | ✅ PASS | auto_wechat 非 superuser |
| FC-11 | Cleanup | ✅ PASS | 隔离容器+fixture 已清理 |
| FC-12 | Canonical no-drift | ✅ PASS | canonical@0034/61/0/0 unchanged |

---

## 24. Findings

### FC-F1: Concurrent Lost Update（BLOCKING）

```text
FC-F1: CONCURRENT LOST UPDATE
  severity = BLOCKING
  affected_gate = FC-3 / FC-8 / FC-9

  route/call site = apps/compute/services.py:679-727 record_usage 幂等路径
  runtime reachability = ACTIVE（所有 idempotency_key 非空的 consume charge 路径）
  identity loss point = 非 identity loss，是 balance lost update
  compute path = get_or_create_account（普通SELECT，加载到identity map）
                 → _write_transaction_balance_only（with_for_update 但identity map不刷新）
                 → new_balance = 旧值 + delta → commit 覆盖其他 worker
  remediation need = 独立返工设计：FOR UPDATE 查询强制 populate_existing / expire / 合并为单步
```

### 非缺陷确认（same-identity exactly-once 正确）

FC-1/FC-2/FC-6 证明：同 identity 并发下 UNIQUE 约束 + IntegrityError catch + replay 路径**正确**。exactly-once 在 same-identity 场景成立（1 txn / 1 balance delta / replay convergence / 无 raw 500）。

lost update 仅在 **同 merchant 不同 identity 并发** 场景暴露（FC-3 distinct identities）。

---

## 25. Remaining OUT_OF_P1 Gaps

不受 FC-F1 影响，继续原状态：

```text
DAILY_REPORT_REQUEST_RECOVERY_GAP = OUT_OF_P1
TRAINING_REQUEST_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_RUN_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_REQUEST_RECOVERY_GAP = OUT_OF_P1
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP = OUT_OF_P1
PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1（含 Trusted Reply-Suggestion）
RAG_QUERY_REQUEST_RECOVERY_GAP = OUT_OF_P1
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
F-2 = DORMANT
```

---

## 26. Verdict

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= FAILED

FC-F1: CONCURRENT LOST UPDATE
  same merchant + distinct identity concurrent charge
  → balance lost update（部分扣费被覆盖）
  → final balance ≠ initial + sum(deltas)

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED（FC-1/FC-2/FC-6）
CONCURRENT_DISTINCT_EVENT_BALANCE_CLOSURE = FAILED（FC-3/FC-8/FC-9）
CONCURRENT_REPLAY_RESPONSE_CONVERGENCE = VERIFIED（FC-7）
```

不得自行 `COMPUTE-IDEMPOTENCY-001 = CLOSED`。

---

## 27. P1 Candidate Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
Final PostgreSQL Concurrent Closure = FAILED
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED（保持）
F-1 = RESOLVED（保持）
```

FC-F1 是新发现的并发缺陷，需独立返工设计 + 修复 + 重跑 Final Concurrent。

---

## 28. Independent Approval Required

本窗口发现并发 bug，按 §35 STOP。提交独立审批窗口裁定：

```text
P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-1 独立审批窗口
  → 裁定 FC-F1 lost update 根因 + 返工方案
  → 返工设计审批 → compute core 修复 → 重跑 Final Concurrent
```

不得本窗口修 compute core（§2/§35）。

---

## 29. Candidate Diff

```text
docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE.md（本报告，FAILED）
```

未修改业务代码 / compute core / migration / 9100 / F-2。未 commit，未 push。验证脚本位于 worktree 外（`e:/work/tmp/fc/`）。

---

## 30. 边界遵守

- ✅ 未修改 compute core / record_usage / _write_transaction_balance_only / migration（§2）
- ✅ 发现 bug 后 STOP，未自行修复后宣布 PASS（§35）
- ✅ 未修改 transaction isolation（read committed，生产默认）
- ✅ 未 start 其他 Phase 3B 任务 / RB-10 / push / 宣布 CLOSED
- ✅ canonical DB 未 mutation（READ ONLY，0034/61/0/0 unchanged）
- ✅ 隔离 PG 已清理（容器删除 + fixture 清理）
- ✅ 使用独立 SQLAlchemy sessions（§28，非共享 Session）
- ✅ §30 fail-closed guard（检查端口非 5432）
- ✅ 未在 record_usage 内部加 sleep/lock/debug barrier（§8）

---

提交：**P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-1 独立审批窗口**（裁定 FC-F1 lost update 返工方案）。

不得自行：
- 修改 compute core
- 修改 migration
- 修改 transaction isolation
- 开始其他 Phase 3B 任务
- RB-10
- push
- 宣布 COMPUTE-IDEMPOTENCY-001 CLOSED
