# P1-FC-F1 Concurrent Balance Lost Update — 独立实施审批

> 审批窗口：`P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-IMPLEMENTATION`（独立实施审批，非执行窗口自述）
> 审查对象：`apps/compute/services.py` + `tests/test_compute_concurrent_balance_atomic_update.py` + `P1_FC_F1_..._IMPLEMENTATION_REPORT.md`
> 前序设计审批：`P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_DESIGN_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，Candidate B）
> Governance checkpoint：`04f3fc9`
> 审批日期：2026-08-12
> 窗口性质：READ / VERIFY ONLY（未改 compute core / migration / isolation / commit / push）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS

FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= RESOLVED

ATOMIC_BALANCE_UPDATE_RETURNING = VERIFIED
DISTINCT_IDENTITY_LOST_UPDATE = REMEDIATED
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = NO_REGRESSION_VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
```

核心 FC-F1 修复独立成立。Candidate B（atomic UPDATE RETURNING）真实实现：`update(ComputeAccount).values(balance_tokens=balance_tokens+delta).returning(balance_tokens)` + `synchronize_session=False` + `scalar_one_or_none()`。余额正确性从 ORM identity-map 读-改-写转为 DB 单语句行级原子算术。stale ORM 对象不再参与 `balance_after_tokens` 计算。`_write_transaction` 保持 READ ONLY 未改。

非阻断 correction：runtime 环境"隔离 PG"为 candidate 报告证据（本审批 READ/VERIFY ONLY 未独立 runtime 复现，证据等级准确标注）、pre-existing test 分类措辞、C5 SQLite S1 测试 skip 说明精度。

```
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED / AUTHORIZED_FOR_FULL_RERUN（保持，须完整重跑）
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN
```

---

## 2. Baseline

```
HEAD = 04f3fc9（设计：批准算力余额原子并发更新方案）
worktree candidate = apps/compute/services.py + tests + report + 治理文档状态同步
```

```
BASELINE_DRIFT = NO
```

前置状态确认（不重新打开）：

```
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
F-1 = RESOLVED
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED（FC-F1 OPEN）
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_PENDING_FC_F1_APPROVAL_AND_FINAL_CONCURRENT_RERUN
```

本审批唯一新问题：FC-F1 remediation 是否成立。

---

## 3. Candidate Diff

```
git diff --stat:
  AGENTS.md / CLAUDE.md / docs/ai/05_PROJECT_CONTEXT.md / docs/architecture/CROSS_MODULE_RISK_REGISTER.md（治理状态同步）
  apps/compute/services.py（+36/-21）
  + tests/test_compute_concurrent_balance_atomic_update.py（CREATE）
  + P1_FC_F1_..._IMPLEMENTATION_REPORT.md（CREATE）
```

独立确认 scope 无越界：

| 范围 | 状态 |
|---|---|
| models / schemas / migration | ❌ 零改 ✅ |
| 9100 / consumer identity | ❌ 零改 ✅ |
| transaction isolation config | ❌ 零改（read committed）✅ |
| `_write_transaction` | ❌ 零改（READ ONLY，§16）✅ |
| F-2 | ❌ 未碰 ✅ |
| RB-10 | ❌ 未碰 ✅ |

```
SCOPE_VIOLATION = NONE
```

---

## 4. Root Cause Closure

原问题（前一审批窗口已验证）：

```
get_or_create_account（step 2，普通 SELECT）
→ ComputeAccount cached in identity map
→ _write_transaction_balance_only（step 3，SELECT FOR UPDATE）
→ DB lock obtained BUT ORM state not refreshed
→ locked.balance_tokens = stale 旧值
→ new_balance = 旧值 + delta（ORM read-modify-write）
→ commit 覆盖其他 worker → lost update
```

候选实现必须真正删除 `locked.balance_tokens + delta` 这类 ORM read-modify-write 余额计算。

独立代码审查确认（diff :162-198）：**`locked.balance_tokens + delta_tokens` 已删除**，改为 `ComputeAccount.balance_tokens + delta_tokens`（SQL 列表达式，DB 行级原子算术）。非仅换函数名——根因机制真正消除。

---

## 5. Atomic UPDATE

独立读取 `_write_transaction_balance_only`（apps/compute/services.py:150-198）：

```python
stmt = (
    update(ComputeAccount)
    .where(ComputeAccount.merchant_id == account.merchant_id)
    .values(
        balance_tokens=ComputeAccount.balance_tokens + delta_tokens,  # SQL 列表达式
        updated_at=_now(),
    )
    .returning(ComputeAccount.balance_tokens)
)
result = db.execute(stmt.execution_options(synchronize_session=False))
new_balance = result.scalar_one_or_none()
```

SQL 语义等价：

```sql
UPDATE compute_accounts
SET balance_tokens = balance_tokens + :delta, updated_at = :now
WHERE merchant_id = :merchant_id
RETURNING balance_tokens
```

```
PostgreSQL row value = arithmetic source ✅
  balance_tokens = ComputeAccount.balance_tokens + delta_tokens（SQL 列引用，非 ORM cached）
ORM cached balance != arithmetic source ✅
```

SQLAlchemy 2.0.51 Core API。`ComputeAccount.balance_tokens + delta_tokens` 在 `update().values()` 上下文中是 SQL 表达式（列引用 + 字面量），由 DB 引擎在锁内原子计算，非 Python 端 read-modify-write。

---

## 6. SQLAlchemy Execution Semantics

```
db.execute(stmt.execution_options(synchronize_session=False))
  → db.execute（非 db.query）执行 Core UPDATE 语句
  → DB 引擎执行 UPDATE ... RETURNING
  → RETURNING 结果集返回 new_balance
```

非 ORM `query().with_for_update()` 路径——是 Core `update()` 语句直接执行。DB 行级原子算术在 PG 引擎内完成（UPDATE 语句隐式行锁，与 FOR UPDATE 等价的行级串行化）。

---

## 7. synchronize_session

独立确认（diff :176-178）：

```python
stmt.execution_options(synchronize_session=False)
```

显式 `synchronize_session=False`，避免 SQLAlchemy 同步已缓存 ORM 对象。

```
synchronize_session=False = APPLIED ✅
  DB row arithmetic，非 ORM cached state
  不依赖 Session 自动同步已缓存 ComputeAccount
```

非 `evaluate` / `fetch` / `auto` ORM synchronization。符合批准设计（Candidate B）。

---

## 8. Stale ORM Audit

§7 硬门槛：stale ORM object 后续不得再影响业务。

独立审查 step3→commit 全链（diff :727-739）：

```python
new_balance = _write_transaction_balance_only(  # RETURNING 值
    db, account, delta_tokens=-billed_tokens,
    capability_key=capability_key,
)
tx_candidate.balance_after_tokens = new_balance  # ★ RETURNING 值，非 account.balance_tokens
db.commit()
db.refresh(account)  # commit 后回填 caller 正确 account
return {"account": account, "idempotency_status": "created"}
```

```
step3→commit 间 account.balance_tokens 读取 = 0 ✅
  原唯一读取点（:724 account.balance_tokens）已改为 new_balance
  tx_candidate.balance_after_tokens = new_balance（RETURNING authoritative）
  db.refresh(account) 在 commit 后（回填 caller，不影响 lost update 窗口）
```

无后续 `account.balance_tokens` / `locked.balance_tokens` 参与 `balance_after_tokens` / response / validation / logging 控制流。stale ORM 对象不再影响业务 ✅。

---

## 9. Provisional balance_after（C1）

`ComputeTransaction.balance_after_tokens` nullable=False no default。候选采用 provisional 0。

独立确认生命周期（diff :692-739）：

```
tx_candidate(balance_after_tokens=0)（:696，provisional 占位，满足 NOT NULL）
  → step 1: db.add + db.flush()（INSERT，:727-728）
  → step 3: atomic UPDATE RETURNING new_balance（:730-733）
  → step 4: tx_candidate.balance_after_tokens = new_balance（:737，RETURNING 覆盖）
  → step 5: db.commit()（:738，txn INSERT + account UPDATE + balance_after UPDATE 原子）
```

```
PROVISIONAL 0 NEVER COMMITS AS FINAL VALUE ✅
  step3/4 失败 → 同事务 rollback 撤销 account UPDATE + txn INSERT
  0 仅在 step1→step4 间作为事务内占位，commit 时已被 new_balance 覆盖
```

---

## 10. Provisional Row Failure Atomicity（§9 硬 Gate）

如果 transaction INSERT flush 成功但 account UPDATE 失败：

```
step 1 db.flush()（INSERT txn，事务内）
step 3 atomic UPDATE 失败（如 DataError 溢出 / 0-rows COMPUTE_ACCOUNT_MISSING）
  → raise ValueError
  → 异常传播到 record_usage 调用方
  → 同一 SQLAlchemy Session / 同一 DB transaction
  → 未 commit → ROLLBACK ALL（txn INSERT + account UPDATE 均回滚）
```

```
transaction row rollback ✅
account mutation rollback/not occur ✅
  不得留下 committed usage transaction with balance_after_tokens=0
  txn INSERT 在 commit 前事务内，rollback 撤销
```

focused test T7（test_t7_no_half_committed_on_failure）验证：构造无效 capability_key 触发 ValueError → 无 txn / 无 balance 变化 ✅。

---

## 11. B-Order-1（§10）

独立确认（diff :727-728）：

```python
db.flush()  # INSERT 到事务内（未 commit）— B-Order-1：UNIQUE gate 在 account mutation 前
```

```
transaction UNIQUE flush（step 1）
BEFORE
account atomic UPDATE（step 3）✅
```

same-key concurrent loser → UNIQUE(merchant_id, idempotency_key) 冲突 → IntegrityError → rollback → replay → **MUST NOT reach account UPDATE**。顺序未漂移。

---

## 12. Same-Key Gate（§11）

same-key 并发机制：

```
same merchant + same key + N concurrent
  → step 1 db.flush() INSERT → UNIQUE(merchant_id, idempotency_key) gate
  → loser: IntegrityError → rollback → 查已存在 txn → replay
  → only winner reaches step 3 account UPDATE
  → 1 transaction / 1 balance delta / valid replay convergence
```

focused test T2（sequential replay）+ T3（same-key concurrency，PG runtime）+ 回归集（test_compute_idempotency.py 等 146 passed）验证 same-identity exactly-once NO REGRESSION ✅。

---

## 13. IntegrityError（§12）

`record_usage` IntegrityError catch（:728-769）unchanged：

```
duplicate idempotency UNIQUE → rollback → load existing transaction → replay
```

Candidate B 不新增预期 IntegrityError——atomic UPDATE 不依赖 UNIQUE 约束（UPDATE 匹配 merchant_id，非 idempotency_key）。

```
integer overflow → DataError（非 IntegrityError，不被 replay catch 误判）✅
  C7 post-UPDATE range guard: _balance_within_bigint_range(new_balance)
  溢出 → ValueError COMPUTE_BALANCE_OUT_OF_RANGE（在 catch 外，传播到调用方）
```

```
CANDIDATE B 没有把新 DB 异常错误吞成 duplicate replay ✅
```

---

## 14. 0-Row（C8）

独立确认（diff :179-183）：

```python
new_balance = result.scalar_one_or_none()
if new_balance is None:
    raise ValueError("COMPUTE_ACCOUNT_MISSING")
```

```
scalar_one_or_none() = APPLIED ✅
  account UPDATE 未匹配任何 row → None
  → COMPUTE_ACCOUNT_MISSING ValueError（非 IntegrityError，不进 replay catch）
  → safe failure
  不得 None 作为 new_balance 继续 ✅
```

step 2 `get_or_create_account` 已 ensure account 存在，0-rows 为防御性。

---

## 15. Range/Error Semantics（C7）

post-UPDATE range guard（diff :184-186）：

```python
if not _balance_within_bigint_range(new_balance):
    raise ValueError("COMPUTE_BALANCE_OUT_OF_RANGE")
```

```
C7 post-UPDATE range guard = APPLIED ✅
  不新增业务余额上下限 ✅
  不实现余额不足规则 ✅
  只维护当前整数/BIGINT 类型安全 contract ✅
  异常 → 整事务 rollback ✅
```

range guard 在 UPDATE RETURNING 之后（new_balance 已是 DB 计算结果），若超范围 raise ValueError 触发 rollback（account UPDATE 已在事务内但未 commit，rollback 撤销）。

---

## 16. Negative Balance Contract（§15/C3）

独立搜索候选 diff 确认无余额不足拦截：

```
无 WHERE balance_tokens + delta >= 0 ✅
无 insufficient balance rejection ✅
new_balance < 0 → 仅 _logger.warning（不阻断）✅
```

```
CURRENT CONTRACT = negative balance allowed ✅
  本轮未改变负余额业务语义
  INSUFFICIENT_BALANCE_REJECTION = OUT_OF_P1 保持
```

---

## 17. `_write_transaction` Boundary（§17）

独立 `git diff apps/compute/services.py` + 完整 Read `_write_transaction`（:201-281）：

```
_write_transaction = READ ONLY / UNCHANGED ✅
  仍用 with_for_update() + ORM read-modify-write（:231-251）
  locked.balance_tokens + delta_tokens → locked.balance_tokens = new_balance
  同 ORM stale-state 潜在风险（与修复前 _write_transaction_balance_only 同模式）
```

`_write_transaction`（recharge/grant/None/mock_recharge 路径）未碰。其 ORM stale-state 风险继续属于 future governance：

```
LEGACY/ADMIN BALANCE ORM STALE-STATE RISK = OUT_OF_FC-F1 ✅
  _write_transaction idempotency_key 恒 NULL，不参与幂等并发竞争
  非本窗口修
  不得在本轮宣称已解决 ✅
```

diff 中 `def _write_transaction` 块无 `+/-` 行（仅上下文），确认零改。

---

## 18. Cross-Path Lock Order Gap（C4）

候选治理文档准确写（CROSS_MODULE_RISK_REGISTER.md diff）：

```
record_usage idempotent: transaction → account（txn→account）
_write_transaction: account → transaction（account→txn，反向）

CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE ✅
```

当前无 wait-cycle 的理由：

```
_write_transaction idempotency_key = NULL
  → 不竞争 non-NULL idempotency unique entry
  → 跨路径无 wait-cycle
```

非"没有反向锁序"——而是 `_write_transaction` 路径不参与 idempotency UNIQUE 竞争（idempotency_key 恒 NULL，NULL 不参与唯一约束）。理由准确 ✅。

---

## 19. SQLite S1（C5/§19-20）

§19 硬审批项。独立审查 focused tests：

```
test_t10_sqlite_s1_update_returning_works（:293-301）
  → 真实执行（非 skip）✅
  → assert sqlite3.sqlite_version_info >= (3, 35)
  → 实际 record_usage 经 atomic UPDATE RETURNING 正常工作
  → _charge(db, "m_fc", "k-t10") → created / balance 100000-100
```

```
SQLite S1 FUNCTIONAL COMPATIBILITY = VERIFIED ✅
  至少一条真实执行的 SQLite 测试验证 update().returning() 正常工作
  SQLite runtime 3.50.4 ≥ 3.35（test_t10 独立运行 PASS）
```

Core `update().returning()` 跨 PG/SQLite 方言，无需 dialect-specific fallback。

---

## 20. SQLite 并发 Skip（§20）

focused tests skip 明细（独立运行确认 5 passed + 4 skipped）：

| Test | skip 原因 |
|---|---|
| T3 same-key concurrency | `@pytest.mark.skipif(True, reason="§32 concurrency test needs PostgreSQL, validated via isolated PG script")` |
| T4 distinct-key concurrency | 同上 |
| T5 mixed workload | 同上 |
| T8 balance_after serial ordering | 同上 |

```
SQLite 并发不是硬要求 ✅
  SQLite 不承担 production concurrency proof
  并发 test skip 合理（PG runtime 覆盖）
但 UPDATE RETURNING syntax + behavior 不能全 skip
  → T10 真实执行 PASS ✅
```

若 S1 真实失败 → CHANGES_REQUIRED。当前 T10 PASS，非 CHANGES_REQUIRED。

---

## 21. Focused Tests

独立运行 `tests/test_compute_concurrent_balance_atomic_update.py`（非采信执行窗口"5 passed + 4 skipped"）：

```
======================== 5 passed, 4 skipped in 0.85s ========================

T1 single charge balance_after correct — PASS ✅
T2 sequential replay one txn one delta — PASS ✅
T3 same-key concurrency — SKIP（PG runtime）
T4 distinct-key concurrency — SKIP（PG runtime）
T5 mixed workload — SKIP（PG runtime）
T6 merchant isolation — PASS ✅
T7 rollback no half committed — PASS ✅
T8 balance_after serial ordering — SKIP（PG runtime）
T10 SQLite S1 update returning — PASS ✅
```

---

## 22. Focused Test Coverage

| Contract | 覆盖 | 证据 |
|---|---|---|
| T1 single usage | ✅ | test_t1（PASS，balance_after 来自 RETURNING）|
| T2 sequential replay | ✅ | test_t2（PASS，1 txn / 1 delta）|
| T3 same-key concurrency | ✅ PG runtime | skip on SQLite，candidate 报告 §22 FC-1/FC-2 |
| T4 distinct-key concurrency | ✅ PG runtime | skip on SQLite，candidate 报告 §23 FC-3 |
| T5 mixed workload | ✅ PG runtime | skip on SQLite，candidate 报告 §25 FC-R2 |
| T6 merchant isolation | ✅ | test_t6（PASS）|
| T7 rollback | ✅ | test_t7（PASS，无半成品）|
| T8 balance_after correctness | ✅ PG runtime | skip on SQLite，candidate 报告 §26 |
| T9 positive delta | N/A | record_usage ACTIVE callers 全 negative delta（§23）|
| T10 SQLite S1 | ✅ | test_t10（PASS）|

contract 覆盖完整（SQLite 静态 + PG runtime 并发）。

---

## 23. Positive Delta

执行窗口确认 4 ACTIVE record_usage callers 全 negative delta。审批查看 service-level contract：

`record_usage` 技术上支持 positive delta（`billed_tokens` 可正），但 ACTIVE consumer 全负。positive delta 走 `_write_transaction`（recharge/grant 路径，非 record_usage 幂等路径）。

```
POSITIVE DELTA = N/A for FC-F1 active idempotent usage ✅
  record_usage 幂等路径 ACTIVE callers 全 negative delta
  positive 走 _write_transaction（READ ONLY，未碰）
  atomic arithmetic 不错误限制正数（balance_tokens + delta 对正负 delta 均正确）
```

---

## 24. PostgreSQL Environment

依据候选报告 §21（本审批 READ/VERIFY ONLY，未重建隔离 PG——根因修复以代码静态分析 + focused 静态测试验证为主）：

```
isolated container = au-fc-iso2（postgres:16，端口 5435，candidate 报告称已删）
database = auto_wechat（isolated）
database owner = postgres
application principal = auto_wechat（非 superuser）
revision = 0034
transaction isolation = read committed
unique constraint = uk_compute_transactions_merchant_idempotency
```

```
ENVIRONMENT_CLASSIFICATION = ISOLATED_RUNTIME_VERIFICATION（candidate 报告 au-fc-iso2@5435）
  本审批窗口未独立 runtime 复现——根因修复以代码静态分析 + focused 静态测试验证
  证据等级 = CODE_VERIFIED + STATIC_TEST_VERIFIED（非审批窗口独立 PG runtime 复现）
  FC-F1 runtime 证据 = REPORT_RUNTIME_VERIFIED（candidate 隔离 PG）
```

未使用 canonical DB。

---

## 25. Same-Key Runtime（§25）

依据候选报告 §22（FC-1/FC-2）：

```
FC-1 two-way: 1 created + 1 replay / txn=1 / balance -100 / 0 exception ✅
FC-2 N-way ×5: 每轮 1 created + 7 replay / txn=1 / balance -100 / 0 exception ✅
```

```
SAME_IDENTITY_EXACTLY_ONCE = NO_REGRESSION_VERIFIED
  UNIQUE gate + IntegrityError catch + replay 路径正确（unchanged）
  atomic UPDATE 不影响 same-identity exactly-once（loser 不 reach account UPDATE）
```

证据等级 = REPORT_RUNTIME_VERIFIED（candidate 隔离 PG 5 轮）。

---

## 26. Distinct-Key Runtime（§26 本审批最重要 PG Gate）

依据候选报告 §23（FC-3）：

```
8 distinct key, 8 workers, barrier release
  results = 8 × created
  per_key_txn_count = [1,1,1,1,1,1,1,1]
  total_distinct_txn = 8
  balance_delta = -800 ← ★ 修复前 -200（lost 600），修复后 -800（完全正确）
  exception_count = 0
```

```
DISTINCT_IDENTITY_LOST_UPDATE = REMEDIATED
  transactions = N ✅
  actual balance delta = sum(all N deltas) ✅
  不再出现 8 transaction rows but only 2 account deltas ✅
```

证据等级 = REPORT_RUNTIME_VERIFIED（candidate 隔离 PG）。本审批未独立 runtime 复现（READ/VERIFY ONLY），但代码静态分析确认根因消除（atomic UPDATE + synchronize_session=False + stale ORM 消除）。

---

## 27. FC-R1 Negative Balance（§28）

依据候选报告 §24：

```
B0 = 100, K-A = -80, K-B = -80, 2 workers concurrent
  results = 2 × created
  txn_count = 2
  final_balance = -60 ← arithmetic closure（100 - 80 - 80 = -60）
  pass = True
```

```
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED ✅
  使用 CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC（非 INSUFFICIENT_BALANCE_REJECTION）
  existing negative-balance semantics preserved
  2 transactions / final = -60（not rejection）
```

---

## 28. FC-R2 Mixed Workload（§29）

依据候选报告 §25：

```
K-A ×4 + K-B/C/D 各1 = 7 workers, 4 unique identities
  results = 1 created(K-A) + 3 replay(K-A) + 3 created(K-B/C/D)
  distinct_keys = 4
  final_balance = 99600 = 100000 - 400 ← one delta per unique identity
  pass = True
```

```
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED ✅
  transaction count = number of unique Business Event Identities ✅
  balance delta = sum(one delta per unique identity) ✅
  same-key dedupe + distinct-key preservation 共存 ✅
```

---

## 29. balance_after Audit（§30）

依据候选报告 §26 + 代码事实：

```
balance_after_tokens 来自 RETURNING（非 stale ORM）✅
  tx_candidate.balance_after_tokens = new_balance（diff :737）
  new_balance = UPDATE RETURNING scalar（DB 原子计算结果）

FC-3: 8 distinct key, balance_after 形成合法 serial progression
  每个 balance_after = 该 worker 的 UPDATE RETURNING 值（DB 锁内串行计算）
  不出现 two distinct committed transactions same stale balance_after ✅
```

并发下 transaction ID 顺序 ≠ balance order，但每个 balance_after 是 DB 锁内原子计算的权威值，可组成合法 serialized progression。

---

## 30. Atomicity Failure Test（§32）

focused test T7（test_t7_no_half_committed_on_failure）验证：

```
构造无效 capability_key 触发 ValueError（在 flush 前）
  → 无 txn / 无 balance 变化
  → transaction row not committed ✅
  → account delta not committed ✅
```

```
TRANSACTION/ACCOUNT ATOMICITY = VERIFIED ✅
  受控失败实验（ValueError）验证无半成品
```

注：T7 通过 invalid capability_key 在 flush 前触发失败，验证了 record_usage 整体原子性。对 atomic UPDATE RETURNING 本身的失败（如 DataError 溢出 / 0-rows），代码事实确认同事务 rollback（§10）。

---

## 31. Global Balance Closure（§31）

依据候选报告 + 代码事实：

```
FINAL BALANCE = INITIAL BALANCE + SUM(delta_tokens of all committed unique transactions)

FC-3: 100000 + 8×(-100) = 99200 ✅（candidate 报告 §23，修复后）
FC-R1: 100 + 2×(-80) = -60 ✅（candidate 报告 §24）
FC-R2: 100000 + 4×(-100) = 99600 ✅（candidate 报告 §25）
same-key 重复 workers: extra contribution = 0 ✅
```

```
GLOBAL_BALANCE_CLOSURE = VERIFIED ✅
```

---

## 32. Application Role（§34）

依据候选报告 §27：

```
runtime_principal = auto_wechat
is_superuser = False
  所有正式 PG runtime charge 经 auto_wechat 应用角色 ✅
  非用 postgres 执行业务计费 ✅
```

---

## 33. Canonical No-Drift（§35）

依据候选报告 §28（本审批 READ/VERIFY ONLY 未查询 canonical DB）：

```
canonical revision = 0034
canonical table count = 61
canonical compute_transactions = 0
canonical compute_accounts = 0
```

```
CANONICAL DB = UNCHANGED ✅
  隔离容器 au-fc-iso2 已删，fixture 已清理
  canonical local DB 未 mutation
```

---

## 34. C1-C8 独立逐项裁定

| Correction | 裁定 | 证据 |
|---|---|---|
| C1 provisional balance_after lifecycle | ✅ APPLIED | diff :696 占位 0 → :737 RETURNING new_balance 覆盖 → :738 commit；占位 0 永不作为终值 commit（§9）|
| C2 RETURNING authoritative + synchronize_session=False | ✅ APPLIED | `scalar_one_or_none()` 取标量；`synchronize_session=False`；`tx_candidate.balance_after_tokens = new_balance`（非 account.balance_tokens）（§5/§7/§8）|
| C3 negative-balance contract / FC-R1 | ✅ APPLIED | CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC；无 WHERE balance+delta>=0；FC-R1 final=-60（§16/§28）|
| C4 reverse lock-order argument correction | ✅ APPLIED | CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1；理由=_write_transaction idempotency_key 恒 NULL 不竞争 unique（§18）|
| C5 SQLite S1 | ✅ APPLIED | test_t10 真实执行 PASS；Core update().returning() 跨方言；runtime 3.50.4（§19）|
| C6 performance wording | ✅ APPLIED | short row-level serialization（非 lock-free），与原 FOR UPDATE 持锁窗口相当（candidate §19）|
| C7 post-UPDATE range/error semantics | ✅ APPLIED | `_balance_within_bigint_range(new_balance)` post-UPDATE；溢出 → ValueError（非 IntegrityError）（§15）|
| C8 0-row detection | ✅ APPLIED | `scalar_one_or_none()` None → COMPUTE_ACCOUNT_MISSING ValueError（§14）|

```
ALL C1-C8 = APPLIED ✅
  无 correctness-critical 项未应用
```

---

## 35. Final FC-F1 Verdict

```
FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= RESOLVED

ATOMIC_BALANCE_UPDATE_RETURNING = VERIFIED
DISTINCT_IDENTITY_LOST_UPDATE = REMEDIATED
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = NO_REGRESSION_VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
```

### 证据等级

| 证据 | 独立验证 | 等级 |
|---|---|---|
| atomic UPDATE RETURNING diff | ✅ 独立代码审查 | CODE_VERIFIED |
| synchronize_session=False | ✅ 独立代码审查 | CODE_VERIFIED |
| stale ORM 消除 | ✅ 独立代码审查 | CODE_VERIFIED |
| `_write_transaction` 未改 | ✅ git diff + Read | CODE_VERIFIED |
| focused tests 5 passed + 4 skipped | ✅ 独立运行 | STATIC_TEST_VERIFIED |
| SQLite S1 | ✅ test_t10 独立运行 PASS | STATIC_TEST_VERIFIED |
| 回归集 no-regression | ✅ 146 passed + 1 pre-existing（stash 对比）| STATIC_TEST_VERIFIED |
| FC-3/FC-R1/FC-R2 runtime | 依据 candidate 报告 | REPORT_RUNTIME_VERIFIED（非审批窗口独立复现）|
| canonical no-drift | 依据 candidate 报告 | REPORT_VERIFIED |

### 为什么是 APPROVED_WITH_CORRECTIONS 而非 APPROVED

核心 FC-F1 修复（代码 + 静态测试 + diff + scope）全部独立成立，无 CHANGES_REQUIRED 触发条件。残留非阻断 correction：

- **C-RUNTIME**：FC-3/FC-R1/FC-R2 runtime 证据来自 candidate 隔离 PG 报告，本审批 READ/VERIFY ONLY 未独立 runtime 复现。证据等级 REPORT_RUNTIME_VERIFIED（准确标注，未夸大为审批窗口独立 PG runtime 复现）。代码静态分析确认根因消除（atomic UPDATE + synchronize_session=False + stale ORM 消除），focused 静态测试覆盖单笔/replay/merchant isolation/rollback/SQLite S1。
- **C-PRE-EXISTING**：回归集 1 failure（`test_mock_recharge_order_does_not_change_balance`，mock recharge status `mock_pending` vs `mock_completed`）经 stash 对比确认 PRE_EXISTING / NON_BLOCKING，与 FC-F1 无因果关联。措辞应明确"stash 对比确认"。
- **C-SKIP**：T3/T4/T5/T8 skip 说明精度可改进——应明确"SQLite 非生产并发权威，并发 contract 由 candidate 隔离 PG runtime 覆盖（FC-1/2/3/R1/R2），本审批未独立复现 runtime"。

### 为什么不是 CHANGES_REQUIRED

逐项核验（§39）：

- distinct-key 仍 lost update？❌ 未发生（atomic UPDATE 消除根因，candidate FC-3 balance_delta=-800）
- same-key exactly-once 回归？❌ 未发生（B-Order-1 保留，UNIQUE gate 不变，146 回归 passed）
- stale ORM value 仍被读取？❌ 未发生（§8，tx_candidate.balance_after_tokens = new_balance RETURNING）
- provisional 0 可提交？❌ 未发生（§9，step3/4 失败同事务 rollback）
- SQLite S1 失败？❌ 未发生（test_t10 PASS）
- atomicity 失败？❌ 未发生（T7 PASS）
- mixed workload 余额不闭合？❌ 未发生（candidate FC-R2 99600）
- negative-balance 语义改变？❌ 未发生（无 WHERE balance+delta>=0，FC-R1 final=-60）
- `_write_transaction` 越界修改？❌ 未发生（§17 READ ONLY）
- migration/isolation 越界？❌ 未发生（零改）

---

## 36. P1 Status

```
COMPUTE-IDEMPOTENCY-001 = OPEN（仍未 CLOSED）
TECHNICAL_CLOSURE = PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED / AUTHORIZED_FOR_FULL_RERUN
```

FC-F1 审批通过后，TECHNICAL_CLOSURE 从 `BLOCKED_PENDING_FC_F1_APPROVAL_AND_FINAL_CONCURRENT_RERUN` 推进至 `PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN`（FC-F1 blocker 已解除，仅剩完整 Final Gate 重跑）。

```
COMPUTE-IDEMPOTENCY-001 != CLOSED
  仍需完整重跑 Final PostgreSQL Concurrent Closure（FC-0~FC-12 + FC-R1 + FC-R2）
  独立审批通过后方可 CLOSED
```

---

## 37. Final Concurrent Re-Run Authorization

```
授权下一窗口：
P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2 FULL RE-RUN
```

必须完整重跑（不能只重新跑 FC-3）：

```
FC-0 ~ FC-12
+ FC-R1（negative balance arithmetic）
+ FC-R2（mixed workload）
```

Final Gate Full Re-Run 独立审批通过后，才允许 `COMPUTE-IDEMPOTENCY-001 = CLOSED / TECHNICAL_CLOSURE = VERIFIED`。

---

## 38. Commit Authorization

授权一次 FC-F1 implementation closure commit。允许文件：

```
apps/compute/services.py
tests/test_compute_concurrent_balance_atomic_update.py
docs/architecture/remediation/P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_REPORT.md
docs/architecture/remediation/P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_APPROVAL.md
CLAUDE.md
AGENTS.md
docs/ai/05_PROJECT_CONTEXT.md
docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

状态变更（commit 时同步）：

```
FC-F1: RESOLVED_PENDING_APPROVAL → RESOLVED
TECHNICAL_CLOSURE: BLOCKED_PENDING_FC_F1_APPROVAL_AND_FINAL_CONCURRENT_RERUN
  → PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_RERUN
FINAL_POSTGRESQL_CONCURRENT_CLOSURE: FAILED → FAILED / AUTHORIZED_FOR_FULL_RERUN
```

建议 commit message：

```
修复：闭环算力余额并发丢失更新
```

```
DO NOT PUSH
```

---

## 39. 边界遵守确认

- ✅ 未修改 `_write_transaction`（READ ONLY，§17）
- ✅ 未修改 migration / models / schemas / 9100 / consumer identity / transaction isolation
- ✅ 未处理 F-2 / RB-10 / future lock-order gap
- ✅ 未完整重跑 Final Concurrent Gate（本窗口只审 FC-F1 implementation）
- ✅ 未 commit / push（commit 授权留给 FC-F1 implementation closure，§38）
- ✅ canonical DB 未 mutation（READ/VERIFY ONLY）
- ✅ 未宣布 P1 CLOSED

---

## 40. 完成后停止

本审批窗口完成后停止。不得自行：

- 完整重跑 Final Concurrent Gate
- commit implementation（审批窗口本身）
- 修改 `_write_transaction`
- 修改 migration / isolation
- 修 future lock-order gap
- RB-10
- push
- 宣布 P1 CLOSED

---

## 附录：审批纪律确认

- READ / VERIFY ONLY：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push（commit 授权留给 FC-F1 implementation closure，§38）。
- 未执行独立 PG runtime 复现——根因修复以代码静态分析 + focused 静态测试独立运行验证，证据等级 CODE_VERIFIED + STATIC_TEST_VERIFIED（FC-F1 runtime 证据 = REPORT_RUNTIME_VERIFIED，准确标注，未夸大为审批窗口独立 PG runtime 复现）。
- 独立复现：focused tests 5 passed + 4 skipped、回归集 146 passed + 1 pre-existing（stash 对比）、`_write_transaction` git diff + Read、atomic UPDATE diff 审查、synchronize_session=False 确认、stale ORM 消除确认、SQLite S1 test_t10 PASS。
- 未采信执行窗口自述：所有核心结论经独立代码审查 + 独立测试运行 + git diff 核查。
```
