# P1-FC-F1 Concurrent Balance Lost Update — 实施报告

> 任务：`P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-IMPLEMENTATION`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION`）
> 前序设计审批：`P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_DESIGN_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，Candidate B）
> Governance checkpoint：`04f3fc9`（设计：批准算力余额原子并发更新方案）
> 基线 commit：`04f3fc9`
> 日期：2026-08-11
> 窗口性质：实施 + 隔离 PG runtime 验证（candidate，未 commit，未 push）
> Source of Truth：隔离 PG runtime 证据 + 代码事实 > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| §0 Governance checkpoint | ✅ PASS（commit `04f3fc9`）|
| Candidate B 实施 | ✅ PASS（atomic UPDATE RETURNING + B-Order-1）|
| C1 provisional balance_after | ✅ APPLIED（占位 0 → RETURNING 覆盖 → commit）|
| C2 禁止读 stale account | ✅ APPLIED（step4 用 RETURNING 值 + synchronize_session=False）|
| C3 FC-R1 命名 | ✅ APPLIED（CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC）|
| C4 deadlock 论证 | ✅ APPLIED（CROSS_PATH_LOCK_ORDER_GAP 登记）|
| C5 SQLite S1 | ✅ APPLIED（Core update().returning() 跨方言，runtime 3.50.4）|
| C6 性能表征 | ✅ APPLIED（short row-level serialization，非 lock-free）|
| C7 post-UPDATE range guard | ✅ APPLIED（RETURNING new_balance 范围校验）|
| C8 0-rows 检测 | ✅ APPLIED（scalar_one_or_none + COMPUTE_ACCOUNT_MISSING）|
| T1-T10 focused tests | ✅ PASS（5 passed + 4 skipped on SQLite，PG runtime 覆盖并发）|
| FC-1 same-key 2-way | ✅ PASS（no-regression）|
| FC-2 same-key N-way ×5 | ✅ PASS（no-regression）|
| FC-3 distinct-key N-way | ✅ **PASS**（lost update 已消除！）|
| FC-4 merchant-scoped | ✅ PASS |
| FC-5 competing payload | ✅ PASS（SUPPLEMENTARY）|
| FC-6 post-race replay | ✅ PASS |
| FC-7 error audit | ✅ PASS（exception=0）|
| FC-8/9 balance closure | ✅ **PASS**（closure_ok=True）|
| FC-R1 negative balance | ✅ PASS（B0=100, 2×(-80), final=-60）|
| FC-R2 mixed workload | ✅ PASS（4 distinct, final=99600）|
| FC-10/11/12 | ✅ PASS |

**Verdict（候选）**：

```text
FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= RESOLVED_PENDING_APPROVAL

ATOMIC_BALANCE_UPDATE_RETURNING
= VERIFIED_PENDING_APPROVAL

DISTINCT_IDENTITY_LOST_UPDATE
= REMEDIATED_PENDING_APPROVAL

SAME_IDENTITY_EXACTLY_ONCE
= NO_REGRESSION_VERIFIED

FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= FAILED / RE-RUN_REQUIRED（保持，须独立审批后重跑完整 Final Gate）
```

---

## 1. Governance Checkpoint

```text
commit = 04f3fc9（设计：批准算力余额原子并发更新方案，未 push）
worktree（checkpoint 时）= 仅 design + design approval，无业务代码
```

---

## 2. Approved Candidate B

```text
PREFERRED = Candidate B — PostgreSQL/SQLite atomic UPDATE compute_accounts
            SET balance_tokens = balance_tokens + :delta, updated_at = :now
            WHERE merchant_id = :merchant_id
            RETURNING balance_tokens
            + B-Order-1（txn unique flush-first）
```

余额正确性从「ORM identity-map 读-改-写」转为「DB 单语句行级原子算术」。`balance_after_tokens` 来自 RETURNING 标量值，不经 ORM identity-map 对象。

---

## 3. Corrections C1-C8

| Correction | 状态 | 应用 |
|---|---|---|
| C1 provisional balance_after | ✅ | `balance_after_tokens=0` 占位（:696 已有）→ step4 RETURNING `new_balance` 覆盖 → step5 commit；占位 0 永不作为终值 commit（step3/4 异常 → 同事务 rollback）|
| C2 禁止读 stale account | ✅ | step4 `tx_candidate.balance_after_tokens = new_balance`（RETURNING 值，非 `account.balance_tokens`）；`.execution_options(synchronize_session=False)`；保留 `db.refresh(account)` |
| C3 FC-R1 命名 | ✅ | `CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC`；按允许负 contract 验证（B0=100, 2×(-80), final=-60）|
| C4 deadlock 论证 | ✅ | `CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE`（_write_transaction 反向锁序但 idempotency_key 恒 NULL 不竞争 unique → 不可达）|
| C5 SQLite S1 | ✅ | Core `update().returning()` 跨方言；runtime 3.50.4 ≥ 3.35，无需 fallback |
| C6 性能表征 | ✅ | short row-level serialization（非 lock-free），与当前 FOR UPDATE 持锁窗口相当 |
| C7 post-UPDATE range guard | ✅ | RETURNING `new_balance` 做 `_balance_within_bigint_range` 校验；溢出 → DataError（非 IntegrityError，不被 replay catch 误判）|
| C8 0-rows 检测 | ✅ | `result.scalar_one_or_none()`；None → `COMPUTE_ACCOUNT_MISSING` ValueError（非 IntegrityError）|

---

## 4. Changed Files

### MODIFY

| 文件 | 改动 |
|---|---|
| `apps/compute/services.py` | ① import `update`（:21）；② `_write_transaction_balance_only` 改为 atomic UPDATE RETURNING（:150-198）；③ `record_usage` 幂等路径调用方用 RETURNING 值（:730-739）。+36/-21 行。|

### CREATE

| 文件 | 内容 |
|---|---|
| `tests/test_compute_concurrent_balance_atomic_update.py` | T1-T10 focused 测试（5 passed + 4 skipped on SQLite，并发测试 PG runtime 覆盖）|
| `docs/architecture/remediation/P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_REPORT.md` | 本报告 |

### NO migration / NO models / NO 9100 / NO _write_transaction change

`_write_transaction`（:187-）未碰（READ ONLY / FUTURE GAP）。models / schemas / migration / 9100 / consumer identity / F-2 / transaction isolation 全未碰。

---

## 5. Before Flow

```text
step 1  db.add(tx_candidate) + db.flush()           ← INSERT txn，unique gate
step 2  get_or_create_account(...)                    ← 普通 SELECT，account 进 identity map
step 3  _write_transaction_balance_only(...)         ← SELECT FOR UPDATE 不刷新 identity map
        → locked.balance_tokens = stale 旧值
        → new_balance = 旧值 + delta
        → locked.balance_tokens = new_balance        ← ORM dirty
        → db.flush()                                   ← UPDATE balance=旧值+delta（覆盖）
step 4  tx_candidate.balance_after_tokens = account.balance_tokens  ← 读 stale 对象
step 5  db.commit()
```

**根因**：FOR UPDATE 取行锁但不刷新 identity map，`locked.balance_tokens` 是 step 2 stale 值。

---

## 6. After Flow

```text
step 1  db.add(tx_candidate) + db.flush()           ← INSERT txn，unique gate（B-Order-1 保留）
step 2  get_or_create_account(...)                   ← existence only（不再读 balance_tokens）
step 3  _write_transaction_balance_only(...)         ← atomic UPDATE RETURNING
        → update(ComputeAccount).where(merchant_id)
          .values(balance_tokens = balance_tokens + delta)
          .returning(balance_tokens)
        → execution_options(synchronize_session=False)
        → result.scalar_one_or_none()
        → new_balance = RETURNING authoritative 值
        → post-UPDATE range guard（C7）
        → return new_balance
step 4  tx_candidate.balance_after_tokens = new_balance  ← RETURNING 值（C2：不读 stale）
step 5  db.commit()                                  ← txn INSERT + account UPDATE 原子
step 6  IntegrityError catch → rollback → replay（unchanged）
```

---

## 7. B-Order-1

```text
UNIQUE transaction flush（step 1）
BEFORE
account balance mutation（step 3）
```

same-key concurrent loser → blocked/conflicts at UNIQUE gate（step 1）→ rollback/replay → MUST NOT reach account UPDATE（step 3）。**保留**。

---

## 8. Provisional balance_after Lifecycle（C1）

```text
construct tx_candidate
balance_after_tokens = 0（provisional 占位，满足 NOT NULL）
        ↓
INSERT + flush（step 1）
        ↓
atomic account UPDATE RETURNING（step 3）
        ↓
returned new_balance
        ↓
tx_candidate.balance_after_tokens = new_balance（step 4）
        ↓
commit（step 5）
```

```text
PROVISIONAL 0 NEVER COMMITS AS FINAL VALUE
  step3/4 失败 → 同事务 rollback 撤销 account UPDATE + txn INSERT
```

---

## 9. Atomic UPDATE RETURNING

```python
stmt = (
    update(ComputeAccount)
    .where(ComputeAccount.merchant_id == account.merchant_id)
    .values(
        balance_tokens=ComputeAccount.balance_tokens + delta_tokens,
        updated_at=_now(),
    )
    .returning(ComputeAccount.balance_tokens)
)
result = db.execute(stmt.execution_options(synchronize_session=False))
new_balance = result.scalar_one_or_none()
```

SQLAlchemy 2.0.51 Core API。`balance_tokens = balance_tokens + delta` 是 DB 行级原子算术（非 ORM read-modify-write）。

---

## 10. synchronize_session（C2）

```text
.execution_options(synchronize_session=False)
```

显式避免 SQLAlchemy 同步已缓存 ORM 对象。DB row arithmetic，非 ORM cached state。

---

## 11. Authoritative new_balance

```text
new_balance 只来自 UPDATE ... RETURNING
不得重新计算 old_balance + delta
```

`tx_candidate.balance_after_tokens = new_balance`（step 4）。

---

## 12. Stale ORM Read Elimination（C2）

step3→step5 间无任何 `account.balance_tokens` 读取。已审计 record_usage 幂等路径：仅原 :724 `account.balance_tokens` 一处，已改为 `new_balance`。`db.refresh(account)`（commit 后）保留，回填 caller 正确 account。

---

## 13. Account Existence（C10）

```text
get_or_create_account = existence responsibility（step 2，不再读 balance_tokens）
atomic UPDATE RETURNING = balance serialization responsibility（step 3）
```

---

## 14. Same-Key Unique Gate（B-Order-1）

```text
step 1 db.flush() → INSERT txn → UNIQUE(merchant_id, idempotency_key) gate
same-key loser → IntegrityError → rollback → replay
MUST NOT reach step 3 account UPDATE
```

---

## 15. IntegrityError Behavior

```text
IntegrityError catch scope unchanged（:728-769）
atomic UPDATE 不新增预期 IntegrityError
overflow → DataError（非 IntegrityError，不被 replay catch 误判）
```

---

## 16. Transaction Atomicity

```text
tx_candidate INSERT + account atomic UPDATE + tx_candidate balance_after UPDATE
全部在 same SQLAlchemy Session / same DB transaction / same commit
任何一步异常 → ROLLBACK ALL
committed transaction row iff committed account delta
```

---

## 17. Negative Balance Contract（C3）

```text
CURRENT CONTRACT = negative balance allowed
本轮未新增 WHERE balance + delta >= 0 / insufficient balance rejection
FC-R1 验证：B0=100, K-A=-80, K-B=-80 → 2 txn, final=-60（arithmetic closure）
INSUFFICIENT_BALANCE_REJECTION = OUT_OF_P1 保持
```

---

## 18. Cross-Path Lock Order Gap（C4）

```text
record_usage idempotent: transaction unique → account（txn→account）
_write_transaction: account → transaction（account→txn，反向）

CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE
  deadlock 实践不可达：_write_transaction idempotency_key 恒 NULL，
  NULL 不参与 idempotency UNIQUE 约束，故跨路径无 wait-cycle。

_write_transaction = READ ONLY（未碰）
```

---

## 19. SQLite S1（C5）

```text
Core update().returning() 跨 PG/SQLite 方言
SQLite runtime 3.50.4 ≥ 3.35，支持 UPDATE RETURNING
无需 dialect-specific fallback
T10 SQLite S1 测试 PASS
```

---

## 20. Focused Tests

`tests/test_compute_concurrent_balance_atomic_update.py`（5 passed + 4 skipped on SQLite）：

| Test | 验证 | 结果 |
|---|---|---|
| T1 | 单笔扣费行为不变（balance_after 来自 RETURNING）| ✅ PASS |
| T2 | sequential replay（1 txn / 1 delta）| ✅ PASS |
| T3 | same-key concurrency N-way | ⏭️ SKIP（PG runtime 覆盖）|
| T4 | distinct-key concurrency | ⏭️ SKIP（PG runtime 覆盖）|
| T5 | mixed workload | ⏭️ SKIP（PG runtime 覆盖）|
| T6 | merchant isolation | ✅ PASS |
| T7 | rollback（无半成品）| ✅ PASS |
| T8 | balance_after serial ordering | ⏭️ SKIP（PG runtime 覆盖）|
| T10 | SQLite S1 update().returning() | ✅ PASS |

现有 compute idempotency 测试 38 passed（no-regression）。

---

## 21. PostgreSQL Environment

```text
isolated container = au-fc-iso2（postgres:16，端口 5435，已删）
database = auto_wechat（isolated）
database owner = postgres
application principal = auto_wechat（非 superuser）
revision = 0034
transaction isolation = read committed
unique constraint = uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
```

---

## 22. Same-Key Runtime（R-F1 / FC-1/2）

```text
FC-1 two-way: 1 created + 1 replay / txn=1 / balance -100 / 0 exception ✅
FC-2 N-way ×5: 每轮 1 created + 7 replay / txn=1 / balance -100 / 0 exception ✅
```

**SAME_IDENTITY_EXACTLY_ONCE = NO_REGRESSION_VERIFIED**

---

## 23. Distinct-Key Runtime（R-F2 / FC-3）

```text
FC-3: 8 distinct key, 8 workers, barrier release
  results = 8 × created
  per_key_txn_count = [1,1,1,1,1,1,1,1]
  total_distinct_txn = 8
  balance_delta = -800  ← ★ 修复前 -200（lost 600），修复后 -800（完全正确）
  exception_count = 0
```

**DISTINCT_IDENTITY_LOST_UPDATE = REMEDIATED**

---

## 24. FC-R1 Negative Balance Arithmetic

```text
B0 = 100, K-A = -80, K-B = -80, 2 workers concurrent
results = 2 × created
txn_count = 2
final_balance = -60  ← ★ arithmetic closure（100 - 80 - 80 = -60）
pass = True
```

**CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED**

---

## 25. FC-R2 Mixed Workload

```text
K-A ×4 + K-B/C/D 各1 = 7 workers, 4 unique identities
results = 1 created(K-A) + 3 replay(K-A) + 3 created(K-B/C/D)
distinct_keys = 4
final_balance = 99600 = 100000 - 400  ← ★ one delta per unique identity
pass = True
```

**MIXED_WORKLOAD_BALANCE_CLOSURE = VERIFIED**

---

## 26. balance_after Audit

```text
FC-3: 8 distinct key, balance_after 形成合法 serial progression
FC-8 ledger: 各 key 1 txn, txn_sum 正确
balance_after_tokens 来自 RETURNING（非 stale ORM）
```

---

## 27. Application Role

```text
runtime_principal = auto_wechat
is_superuser = False
```

所有并发扣费经 `auto_wechat` 应用角色。

---

## 28. Canonical No-Drift

```text
canonical revision = 0034
canonical table count = 61
canonical compute_transactions = 0
canonical compute_accounts = 0
```

**CANONICAL DB = UNCHANGED**。隔离容器已删，fixture 已清理。

---

## 29. `_write_transaction` Boundary

```text
_write_transaction = READ ONLY（未碰）
CROSS_PATH_LOCK_ORDER_GAP = FUTURE GOVERNANCE
LEGACY/ADMIN BALANCE ORM STALE-STATE RISK = OUT_OF_FC-F1
```

`_write_transaction`（recharge/grant/None/mock_recharge 路径）同脆弱模式（ORM read-modify-write），但非 FC-F1 并发面（idempotency_key 恒 NULL，不参与幂等并发竞争）。不在本窗口修。

---

## 30. Scope Compliance

| 范围 | 状态 |
|---|---|
| MODIFY apps/compute/services.py | ✅（_write_transaction_balance_only + record_usage 幂等路径）|
| CREATE focused tests | ✅ |
| CREATE implementation report | ✅ |
| `_write_transaction` | ❌ 零改（READ ONLY）|
| models / migration / schemas | ❌ 零改 |
| 9100 / consumer identity | ❌ 零改 |
| transaction isolation | ❌ 零改（read committed）|
| F-2 | ❌ 未碰 |

无 STOP 触发条件（§40）。

---

## 31. Verdict

```text
FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= RESOLVED_PENDING_APPROVAL

ATOMIC_BALANCE_UPDATE_RETURNING
= VERIFIED_PENDING_APPROVAL

DISTINCT_IDENTITY_LOST_UPDATE
= REMEDIATED_PENDING_APPROVAL

SAME_IDENTITY_EXACTLY_ONCE
= NO_REGRESSION_VERIFIED

CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE
= VERIFIED_PENDING_APPROVAL

FINAL_POSTGRESQL_CONCURRENT_CLOSURE
= FAILED / RE-RUN_REQUIRED（保持）
```

---

## 32. Next Step

```text
P1-FC-F1 Implementation Independent Approval
  → APPROVED
  → 重跑完整 Final PostgreSQL Concurrent Closure Gate（FC-0~FC-12 + FC-R1 + FC-R2）
  → 方可推进 TECHNICAL_CLOSURE
```

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_PENDING_FC_F1_APPROVAL_AND_FINAL_CONCURRENT_RERUN
```

---

## 33. Git Discipline

- §0 设计审批 checkpoint = commit `04f3fc9`（已 commit，未 push）
- implementation candidate = **DO NOT COMMIT**（candidate diff 交独立实施审批）
- 未 push

candidate diff scope：

```text
MODIFY apps/compute/services.py
CREATE tests/test_compute_concurrent_balance_atomic_update.py
CREATE docs/architecture/remediation/P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_REPORT.md
```

---

提交：**P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-IMPLEMENTATION 独立实施审批窗口。**
