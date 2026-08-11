# P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE — 独立审批报告

> 审批窗口：`P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-1`（独立审批，非执行窗口自述）
> 审查对象：`docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE.md`
> 前序：`F-1 = RESOLVED` + `GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED`（closure commit `4a5cd15`）
> 基线 commit：`4a5cd15`
> 审批日期：2026-08-11
> 窗口性质：READ / VERIFY ONLY（未改 compute core / migration / transaction isolation / commit / push）
> 裁定：`APPROVED_FAILED_FINDING`

---

## 1. Technical Decision

```
VERDICT: APPROVED_FAILED_FINDING

FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED

FC-F1: CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= OPEN / P1 BLOCKER

ROOT_CAUSE = VERIFIED（CODE + DIAGNOSTIC_VERIFIED）
  SQLAlchemy identity-map stale ComputeAccount state
  after SELECT FOR UPDATE on already-loaded ORM instance
```

独立确认：候选报告的 lost update 现象与 SQLAlchemy identity map stale 根因均成立。8 个根因链步骤逐段经当前代码事实复核，9 个替代根因逐项排除。same-identity exactly-once 正确（FC-1/FC-2/FC-6 PASS），distinct-identity balance serialization 失败（FC-3/FC-8/FC-9 FAIL）。这是 silent correctness failure（无异常），必须经 balance closure 才能发现。

```
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_TRANSACTION_INSERT = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE = FAILED
```

---

## 2. Baseline

```
HEAD = 4a5cd15（审计：闭环全局Active算力幂等身份）
worktree = 4 治理文档 modified（AGENTS.md/CLAUDE.md/05_PROJECT_CONTEXT.md/CROSS_MODULE_RISK_REGISTER.md，6 insertions 6 deletions）+ 1 报告 untracked
```

候选 diff 仅治理文档状态同步，**无 compute core / migration / transaction isolation 业务代码改动**。

```
git diff --stat:
  AGENTS.md / CLAUDE.md / docs/ai/05_PROJECT_CONTEXT.md / docs/architecture/CROSS_MODULE_RISK_REGISTER.md
  4 files changed, 6 insertions(+), 6 deletions(-)
```

```
BASELINE_DRIFT = NO
SCOPE_VIOLATION = NONE（无 compute core implementation 修改）
```

前置状态确认（不重新打开）：

```
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = RESOLVED
ACTIVE NONE / EMPTY / PARTIAL / UNKNOWN = 0
```

本审批唯一新问题：FC-F1 CONCURRENT LOST UPDATE。

---

## 3. Candidate Diff

```
docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE.md（FAILED 报告）
+ 治理文档 FAILED 状态同步（AGENTS.md / CLAUDE.md / 05_PROJECT_CONTEXT.md / CROSS_MODULE_RISK_REGISTER.md）
```

确认：无 compute core / record_usage / _write_transaction_balance_only / get_or_create_account / migration / 9100 / F-2 改动。治理文档写 FAILED 状态，无提前写修复方案或 RESOLVED。

---

## 4. PostgreSQL Environment

依据候选报告 §3-5（本审批 READ/VERIFY ONLY，未重建隔离 PG——根因可通过代码静态分析 + 诊断推理验证，无需 runtime 复现）：

```
isolated container = au-fc-iso（postgres:16，端口 5434，独立 volume，非 canonical 5432）
database = auto_wechat（isolated）
database owner = postgres
application principal = auto_wechat（非 superuser）
revision = 0034（alembic upgrade head）
table count = 61
transaction isolation = read committed（PG 默认，生产代码不改）
unique constraint = uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
compute_accounts unique = uk_compute_accounts_merchant UNIQUE(merchant_id)
```

未临时切 SERIALIZABLE。bootstrap 符合已批准 principal contract。

```
ENVIRONMENT_CLASSIFICATION = ISOLATED_RUNTIME_VERIFICATION（candidate 隔离 PG au-fc-iso@5434）
  本审批窗口未重建隔离 PG——根因验证以代码静态分析 + 诊断推理为主
  证据等级 = CODE + DIAGNOSTIC_VERIFIED（非审批窗口独立 runtime 复现）
```

---

## 5. Concurrency Harness

依据候选报告 §8-9：

```
worker model = ThreadPoolExecutor + threading.Barrier
barrier = threading.Barrier(N) → barrier.wait() 同步起跑
per-worker = 独立 SQLAlchemy Session（独立 connection/transaction，非共享）
N = 2（FC-1）/ 8（FC-2/FC-3）
repeated rounds = 5（FC-2，每轮新 key）
distinct keys = 8（FC-3，每 worker 不同 key）
未在 record_usage 内部加 sleep/lock/debug barrier
```

独立确认：每个 worker 独立 Session（`SessionLocal`，database.py:251 `sessionmaker(autocommit=False, autoflush=False, bind=engine)`），代表真实 PostgreSQL 事务竞争。非共享 Session。

---

## 6. Same-Identity Control

依据候选报告 FC-1/FC-2/FC-6（§10/§11/§16）：

```
FC-1: K1, 2 workers, barrier → 1 txn / 1 created + 1 replay / balance -100 / 0 exception
FC-2: 5 轮 × 8-worker fresh key → 每轮 1 txn / 1 created + 7 replay / balance -100 / 0 exception
FC-6: race 后 sequential replay → txn 仍 1 / balance unchanged / idempotent_replay
```

```
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
  UNIQUE 约束 + IntegrityError catch + replay 路径正确
  1 txn / 1 balance delta / replay convergence / 无 raw 500
```

确认当前问题**不是** unique/idempotency race 整体失效，而是 distinct event balance serialization 问题。same-identity exactly-once 正常。

---

## 7. FC-F1 Runtime Reproduction

依据候选报告 §12 FC-3（3 轮稳定复现）：

```
8 distinct keys（K3-A ~ K3-H）, M1, 8 workers, barrier release

trial 0: 8 created, txn_sum=-800, bal=999800 (expected 999200, lost 600)
trial 1: 8 created, txn_sum=-1600, bal=999600 (expected 998400, lost 600)
trial 2: 8 created, txn_sum=-2400, bal=999400 (expected 997600, lost 600)

per_key_txn_count = [1,1,1,1,1,1,1,1] ✓（每 key exactly 1 txn）
total_distinct_txn = 8 ✓
balance_delta = -200 ← 应为 -800
expected_delta = -800
exception_count = 0
lost update = 600
```

稳定复现：每轮 8 worker 只扣 200（2×100），丢失 600（6×100）。2-worker 不暴露（时序窗口小，step 2 get_or_create_account 可能在第一个 commit 后才执行，读到新值）。

```
FC-F1 RUNTIME_REPRODUCED（candidate 隔离 PG，3 轮稳定）
  本审批窗口未独立 runtime 复现——以代码静态分析验证根因（§12-14）
  证据等级 = REPORT_RUNTIME_VERIFIED + CODE_VERIFIED
```

---

## 8. Ledger vs Account Result

候选报告 §18 区分（FC-F1 核心性质）：

```
Ledger:
  8 distinct identities
  8 transaction rows（每 key exactly 1）
  txn_sum = -800（txn 表 delta 正确）
  → LEDGER CORRECT

Account:
  expected final balance = B_initial + Σ(8 deltas) = B_initial - 800
  actual final balance = B_initial - 200
  residual = -600
  → ACCOUNT STALE / LOST UPDATE
```

```
DISTINCT_IDENTITY_LEDGER_INSERTION = VERIFIED（8 txn 全插入，无重复）
DISTINCT_IDENTITY_ACCOUNT_BALANCE_SERIALIZATION = FAILED（balance 少扣 600）
```

不笼统写"compute concurrency completely broken"——txn 层正确，account balance 层失败。

---

## 9. Repeated Rounds

候选报告 §12 3 轮 fresh-key：

```
trial 0: lost 600
trial 1: lost 600
trial 2: lost 600
```

3 轮稳定复现，非偶然调度误判。2-worker 不暴露（时序窗口小），8-worker 稳定暴露。

---

## 10. Transaction balance_after Analysis

候选报告未逐条列 `compute_transactions.balance_after_tokens`。独立分析代码（services.py:724）：

```python
tx_candidate.balance_after_tokens = account.balance_tokens  # :724
```

`account.balance_tokens` 是 `_write_transaction_balance_only` 写入后的值（:182 `locked.balance_tokens = new_balance`）。由于 identity map stale，`account` 与 `locked` 是同一对象，`account.balance_tokens` = `new_balance` = 旧值 + delta。

因此每条 txn 的 `balance_after_tokens` 记录的是"该 worker 读到的旧 balance + 该 worker 的 delta"，**不是**全局串行递减序列。多个 worker 可能记录相同的起始旧值（如都读 999400），各自 balance_after = 999300，但 DB 最终只有最后一个 commit 生效 → 多条 txn 出现相同 `balance_after_tokens`（stale snapshot 迹象），与最终 account 无法形成合理递减序列。

```
TRANSACTION_BALANCE_AFTER_ANALYSIS:
  多条 txn 可能记录相同 stale starting balance（如多个 worker 都读 999400 → 各写 999300）
  non-monotonic sequence（并发下 txn ID 顺序 ≠ lock/commit 顺序）
  与最终 account balance 无法形成严格递减序列
  → stale snapshots 迹象，符合 identity map stale 根因
```

不简单按 txn ID 要求严格递减（并发下顺序不保证），但存在多个 txn 使用同一 stale starting balance 的迹象。

---

## 11. Current Compute Call Chain

独立读取 `record_usage`（apps/compute/services.py:679-769）幂等路径完整链：

```
record_usage(idempotency_key 非空)
  → :681 if idempotency_key: → 幂等路径
  → :683-689 _compute_payload_evidence（stable payload hash）
  → :692-713 构造 tx_candidate（ComputeTransaction，idempotency_key 非空）
  → :714 db.add(tx_candidate)
  → :715 try:
    → :716 db.flush()  ← step 1: INSERT txn（事务内，未 commit）
    → :718 account = get_or_create_account(db, merchant_id, autocommit=False)  ← step 2: 普通 SELECT
      → get_or_create_account :120-124 db.query(ComputeAccount).filter(merchant_id).first()
      → 无 FOR UPDATE
      → account 对象进入 session identity map，balance_tokens = 此时刻 DB 值
    → :719-722 _write_transaction_balance_only(db, account, delta_tokens=-billed_tokens)  ← step 3: FOR UPDATE + balance update
      → :162-167 db.query(ComputeAccount).filter(merchant_id).with_for_update().first()
      → SELECT ... FOR UPDATE（获取行锁，串行化）
      → 但 SQLAlchemy identity map 返回 step 2 已加载的同一对象（同一 PK）
      → locked.balance_tokens = step 2 时刻的旧值（未从 FOR UPDATE 结果重新 hydrate）
      → :170 new_balance = locked.balance_tokens + delta_tokens（旧值 + delta）
      → :182 locked.balance_tokens = new_balance
      → :184 db.flush()
    → :724 tx_candidate.balance_after_tokens = account.balance_tokens（同一对象，旧值+delta）
    → :725 db.commit()  ← 写入旧值+delta，覆盖其他 worker 的更新
    → :726 db.refresh(account)
    → :727 return {"account": account, "idempotency_status": "created"}
  → :728 except IntegrityError:
    → :731 db.rollback()
    → :733-739 查已存在 txn
    → :747-769 replay / conflict（不扣费）
```

```
CALL_CHAIN_VERIFIED = YES（与候选报告 §6 一致）
```

---

## 12. Session Scope

独立确认（database.py:251）：

```
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

- 每个 worker 独立 Session（独立 connection/transaction）✅
- `autoflush=False`：`db.flush()`（:716）是显式 flush，tx_candidate INSERT 在 step 2 之前已 flush 到事务内 ✅
- `expire_on_commit`：sync SessionLocal 未显式设（默认 True），但 `record_usage` 中 `db.commit()`（:725）后 `db.refresh(account)`（:726）显式刷新——这是 commit 后，不影响 commit 前的 lost update 窗口 ✅
- transaction boundary：`db.flush()`（:716）+ `db.commit()`（:725）在同一事务内，step 1/2/3 都在 commit 前同一事务 ✅

---

## 13. SELECT FOR UPDATE SQL Evidence

代码事实（services.py:162-167）：

```python
locked = (
    db.query(ComputeAccount)
    .filter(ComputeAccount.merchant_id == account.merchant_id)
    .with_for_update()
    .first()
)
```

`.with_for_update()` 生成 `SELECT ... FOR UPDATE` SQL。PostgreSQL 执行该语句会获取行锁，串行化并发访问。

```
DATABASE ROW LOCK = EFFECTIVE（FOR UPDATE 生效，串行化）
  但 lock 生效 ≠ ORM 属性刷新——这是两个独立问题
```

```
SELECT FOR UPDATE SQL = PRESENT（with_for_update 生成 FOR UPDATE）
ROW LOCK = EFFECTIVE（PG 行锁串行化）
ORM ATTRIBUTE REFRESH = ABSENT（无 populate_existing / expire，identity map 不刷新）
```

不因 lost update 就误判"FOR UPDATE 没生效"——锁本身生效，但 ORM 对象状态没有 refresh。

---

## 14. SQLAlchemy Identity Map Evidence

根因链 8 步逐段代码事实复核：

```
1. account 已在 Session identity map
   ✅ get_or_create_account（:718，step 2）普通 SELECT 加载 ComputeAccount 到 identity map

2. another transaction updates + commits account balance
   ✅ 并发 worker 执行同一链，commit 写入新 balance

3. current transaction waits for row lock
   ✅ with_for_update（:162-167，step 3）获取行锁，若他事务持锁则等待

4. SELECT FOR UPDATE 获得锁后
   ✅ PG 返回锁定的行

5. ORM 返回同一 identity-map object
   ✅ get_or_create_account（step 2）与 _write_transaction_balance_only（step 3）查询同一 PK（同一 merchant_id）
   SQLAlchemy identity map：同一 PK 对象已在 map 中 → with_for_update 查询返回 identity map 中的对象

6. balance_tokens 属性仍是锁前已加载旧值
   ✅ 无 populate_existing / expire（grep 确认 production compute core 无此操作）
   SQLAlchemy 默认不重新 hydrate 已加载对象的属性

7. subsequent balance calculation 基于旧值
   ✅ :170 new_balance = locked.balance_tokens + delta_tokens（旧值 + delta）

8. UPDATE 覆盖刚刚提交的新 balance
   ✅ :182 locked.balance_tokens = new_balance → :184 flush → :725 commit
   写入"旧值 + delta"，覆盖他事务刚 commit 的新 balance
```

```
STALE_IDENTITY_MAP_HYPOTHESIS = VERIFIED（8 步全部代码事实支撑）
```

### 关键代码证据

- `get_or_create_account`（:120-124）：`db.query(ComputeAccount).filter(...).first()`，无 FOR UPDATE，无 populate_existing ✅
- `_write_transaction_balance_only`（:162-167）：`.with_for_update().first()`，**无 `.populate_existing()` / `.execution_options(populate_existing=True)`** ✅
- 两查询同一 PK（merchant_id 相同）→ identity map 返回同一对象 ✅
- ComputeAccount 无 `version_id_col` / `__mapper_args__` optimistic lock（grep 确认 models.py 无）✅
- UPDATE 是 read-modify-write（:170 计算 → :182 赋值），非原子 `SET balance = balance + delta` ✅

---

## 15. Diagnostic Control Experiment

§13 对照实验逻辑（不实施，仅推理）：

### Experiment A（当前行为）

```
get_or_create_account（普通 SELECT，加载到 identity map）
→ _write_transaction_balance_only（FOR UPDATE 但 identity map 不刷新）
→ new_balance = 旧值 + delta
→ commit 覆盖 → lost update
```

### Experiment B（诊断假设）

若在 `_write_transaction_balance_only` 的 `with_for_update()` 查询加 `.populate_existing(True)` 或在查询前 `db.expire(account)`：

```
FOR UPDATE 查询 → populate_existing 强制重新 hydrate identity map 对象
→ locked.balance_tokens = FOR UPDATE 后的 DB 最新值
→ new_balance = 最新值 + delta
→ commit 写入正确串行值 → balance 闭合
```

逻辑上 Experiment B 让 balance 闭合，加强 STALE_IDENTITY_MAP_HYPOTHESIS 证据。

```
DIAGNOSTIC_CONTROL_EXPERIMENT = LOGICAL_VERIFIED
  Experiment B（populate_existing / expire）理论上闭合 → 加强根因证据
  本审批不实施（§20），仅推理
```

---

## 16. Alternative Root Cause Elimination

逐项排除 9 个替代根因：

### A. Missing row lock
❌ 排除。`with_for_update()`（:162-167）生成 `SELECT ... FOR UPDATE`，lock 生效（行锁串行化）。问题不在 lock 缺失，而在 ORM 属性未刷新。

### B. Lock 在错误 transaction/session 中
❌ 排除。`with_for_update()` 与后续 UPDATE 在同一 Session/transaction 内（同一 `db`，:718→:719 同一 session，未跨 connection）。

### C. Lock 后 commit boundary 提前释放
❌ 排除。`db.commit()`（:725）在 balance update（:719-722）之后。lock 持有至 commit。

### D. ORM autoflush 造成顺序异常
❌ 排除。`SessionLocal` `autoflush=False`（database.py:251）。`db.flush()`（:716）是显式 flush，tx_candidate INSERT 在 step 2 之前已 flush 到事务内，不影响锁顺序。

### E. account object stale identity-map
✅ **PRIMARY ROOT CAUSE**。见 §14，8 步链全部代码事实支撑。

### F. UPDATE 没有 where/version 保护
部分相关（contributing factor）。ComputeAccount 无 `version_id_col` / optimistic lock（grep 确认）。UPDATE 是 read-modify-write（:170 计算 → :182 赋值），非原子 `SET balance = balance + delta`。若用原子 UPDATE，即使 identity map stale 也不会 lost update（DB 自身原子累加）。但这是 contributing factor，非 primary——primary 是 identity map stale 导致 `locked.balance_tokens` 读旧值。原子 UPDATE 是候选修复方向之一（Candidate B），非根因本身。

### G. balance computation 发生在 lock 前
❌ 排除。`new_balance = locked.balance_tokens + delta_tokens`（:170）发生在 `with_for_update()` 查询（:162-167）之后。计算在 lock 后，但 identity map 不刷新使 `locked.balance_tokens` 仍是旧值。

### H. multiple account rows / merchant lookup 错误
❌ 排除。`compute_accounts` 有 `uk_compute_accounts_merchant UNIQUE(merchant_id)`（models.py:916），一行一商户，不会查到多行。

### I. isolation / connection pool 异常
❌ 排除。read committed 是 PG 默认，每个 worker 独立 Session/独立 connection。read committed 下 `SELECT ... FOR UPDATE` 会获取最新已提交版本（若 ORM 刷新），问题不在 isolation level。

---

## 17. Root Cause Verdict

```
PRIMARY ROOT CAUSE = ROOT_CAUSE_VERIFIED

FC-F1 ROOT CAUSE
= SQLAlchemy identity-map stale ComputeAccount state
  after SELECT FOR UPDATE on already-loaded ORM instance

机制：
  get_or_create_account（step 2，普通 SELECT）先加载 account 到 session identity map
  → _write_transaction_balance_only（step 3）with_for_update() 获取行锁
  → 但 identity map 返回 step 2 已缓存对象，不重新 hydrate balance_tokens
  → locked.balance_tokens = 旧值
  → new_balance = 旧值 + delta
  → commit 覆盖其他 worker 的更新 → lost update

CONTRIBUTING FACTOR:
  ComputeAccount 无 version_id_col / optimistic lock
  UPDATE 是 read-modify-write，非原子 SET balance = balance + delta
  若用原子 UPDATE，identity map stale 不会导致 lost update（DB 自身原子累加）
```

```
ROOT_CAUSE_LEVEL = VERIFIED（CODE + DIAGNOSTIC_VERIFIED）
  8 步根因链全部代码事实支撑
  Experiment B 逻辑验证加强证据
  9 个替代根因逐项排除
```

---

## 18. FC-1~FC-12 Review

| Gate | 验证内容 | 候选结论 | 独立裁定 |
|---|---|---|---|
| FC-0 | Isolated PG / principal / revision | ✅ PASS | ✅ 确认（au-fc-iso@5434, auto_wechat@0034/61, read committed）|
| FC-1 | Two-way same identity race | ✅ PASS | ✅ 确认（same-identity exactly-once 正确）|
| FC-2 | N-way same identity repeated race | ✅ PASS | ✅ 确认（5 轮稳定 exactly-once）|
| FC-3 | Concurrent distinct identities / lost-update | ❌ FAIL | ✅ 确认（8 distinct key 各 1 txn 但 balance 少扣 600，3 轮稳定）|
| FC-4 | Merchant-scoped identity isolation | ✅ PASS | ✅ 确认（uk_compute_accounts_merchant + uk_compute_transactions_merchant_idempotency，静态核验）|
| FC-5 | Competing payload behavior | ✅ PASS | ✅ 确认（SUPPLEMENTARY，first-write-wins + replay）|
| FC-6 | Post-race sequential replay | ✅ PASS | ✅ 确认（replay convergence 正确）|
| FC-7 | Error / deadlock / integrity audit | ✅ PASS | ✅ 确认（exception_count=0，IntegrityError 正确 catch）|
| FC-8 | Ledger reconciliation | ❌ FAIL | ✅ 确认（txn 全存在但 balance 不闭合）|
| FC-9 | Global balance closure | ❌ FAIL | ✅ 确认（final≠initial+sum(deltas)，差 600）|
| FC-10 | Application-role runtime | ✅ PASS | ✅ 确认（auto_wechat 非 superuser）|
| FC-11 | Cleanup | ✅ PASS | ✅ 确认（隔离容器+fixture 已清理）|
| FC-12 | Canonical no-drift | ✅ PASS | ✅ 确认（canonical@0034/61/0/0 unchanged）|

---

## 19. Existing Idempotency Safety

```
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED（不回归）
  FC-1/FC-2/FC-6 证明：
  - UNIQUE(merchant_id, idempotency_key) 约束正确
  - IntegrityError catch + rollback + 查已存在行 + replay/conflict 路径正确
  - same identity 并发 → 1 txn / 1 balance delta / replay convergence / 无 raw 500
```

```
CONCURRENT_DISTINCT_IDENTITY_TRANSACTION_INSERT = VERIFIED
  8 distinct key 各 1 txn（txn 层正确，无重复 INSERT）
  UNIQUE 约束不阻止 distinct key（各 key 独立行）
```

```
CONCURRENT_REPLAY_RESPONSE_CONVERGENCE = VERIFIED
  FC-7：IntegrityError 正确 catch，不泄漏为未处理异常
  same-identity replay response 正确（idempotent_replay / idempotency_conflict）
```

FC-F1 修复必须冻结为硬回归 Gate：same-identity exactly-once / UNIQUE replay / IntegrityError convergence / transaction count / balance replay 均 **NO REGRESSION**。

---

## 20. Merchant Isolation

静态 + focused 确认（FC-4）：

```
uk_compute_accounts_merchant UNIQUE(merchant_id)（models.py:916）
  → 一行一商户，不会查到多行

uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)（models.py:941）
  → merchant-scoped，不同 merchant 同 key 不互相 dedupe
```

FC-4 PASS（M1+M2 同 K4 → 各 1 独立 txn / 各 -100）。cross-merchant dedupe 不是 FC-F1 根因。

---

## 21. Error Audit

```
exception_count = 0（全部 FC-1~FC-6 轮次）
无 raw IntegrityError 500
无 deadlock
无 serialization failure exposed to caller
```

```
NO EXCEPTION != CONCURRENCY CORRECT
  lost update 属于 silent correctness failure
  不产生异常，静默覆盖
  必须经 balance closure（FC-8/FC-9）才能发现
  这是本 bug 的重要特征
```

---

## 22. TODO.md Classification

候选报告 §29 提及 `auto_wechat 今日 TODO.md`（.gitignore ignored）。本审批确认该文件不纳入 git commit，不影响 FC-F1 技术裁定。

---

## 23. Governance Status

候选治理文档（CLAUDE.md / AGENTS.md / 05_PROJECT_CONTEXT.md / CROSS_MODULE_RISK_REGISTER.md）写 FAILED 状态：

```
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
FC-F1 = OPEN / P1 BLOCKER
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
```

确认：无提前写修复方案或 RESOLVED。状态准确。

---

## 24. P1 Blocking State

```
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
Final PostgreSQL Concurrent Closure = FAILED
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED（保持）
F-1 = RESOLVED（保持）
```

FC-F1 是新发现的并发缺陷，需独立返工设计 + 修复 + 重跑 Final Concurrent。

---

## 25. Remediation Design Requirements

下一设计窗口必须满足（§22-27）：

### 25.1 修复标准

不能只看"最少改一行"，必须包括：

```
correctness
transaction semantics
same-identity replay interaction（NO REGRESSION）
distinct-event concurrency
balance insufficiency race（B0=100 + two concurrent 80 charges 的正确行为）
deadlock risk
SQLAlchemy identity map behavior
performance
migration impact
compatibility
testability
```

### 25.2 余额不足并发语义

```
B0 = 100
two distinct concurrent charges = 80 each
正确行为：one succeeds / one insufficient balance（不能 both read 100 / both succeed / final impossible）
修复必须同时保持 balance check + deduction 的原子/串行语义
```

注意当前 `_write_transaction_balance_only`（:173-181）对 `new_balance < 0` 只 warning 不阻断（一期不拦截余额）。但并发下"both read 100 / both succeed / final 负"仍是 lost update 问题，修复须保证串行语义。

### 25.3 事务一致性

```
transaction row + account balance mutation 必须同一事务
不得形成"ledger inserted / account update failed"或反之
FC-F1 目前 ledger 正确 / account 错误，修复不能通过牺牲 ledger 原子性解决
```

### 25.4 same-identity replay NO REGRESSION

```
修复 distinct identity lost update 后，必须保持：
- UNIQUE replay
- IntegrityError convergence
- transaction count（same identity → 1 txn）
- balance replay（same identity + same stage → IDEMPOTENT_REPLAY，balance unchanged）
```

### 25.5 PostgreSQL constraint / isolation 默认不改

```
NO MIGRATION（除非设计证明需要）
uk_compute_transactions_merchant_idempotency 已成功防 duplicate transaction
FC-F1 根因不来自 constraint

NO TRANSACTION ISOLATION CHANGE
read committed 是正常运行基线
优先在 locking / atomic update / fresh state 层解决
不得为测试通过直接全局切 SERIALIZABLE
```

---

## 26. Candidate Design Families

下一设计窗口（`P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN`）至少比较：

### Candidate A — Lock-first + fresh ORM state

```
SELECT FOR UPDATE → force fresh row state（populate_existing / refresh / expire-reload）→ calculate → UPDATE
```

评估：populate_existing / refresh / expire 语义；identity map 行为；same-identity replay 交互。

### Candidate B — Atomic Database UPDATE

```sql
UPDATE compute_accounts
SET balance_tokens = balance_tokens + :delta
WHERE merchant_id = :mid
RETURNING balance_tokens
```

以数据库原子操作避免 read-modify-write lost update。评估：RETURNING 拿新值写 txn balance_after；balance 不足原子检查；SQLAlchemy 与 RETURNING 集成。

### Candidate C — Lock account before any balance read

```
lock → read current balance → validate → transaction row → update
```

调整 transaction ordering：合并 get_or_create_account + FOR UPDATE 为单步（直接 FOR UPDATE 查询，无前置普通 SELECT）。

### Candidate D — Optimistic Versioning / CAS

```
version column / compare-and-swap / retry
```

可能过重（需 migration 加 version 列）。

### Candidate E — Higher Isolation

```
SERIALIZABLE
```

默认不应优先，除非设计事实支持。产生更大运行影响。

```
DESIGN WINDOW = DESIGN ONLY
  比较 Candidate A-E，选一个正式方案
  不能直接实施
```

---

## 27. Verdict

```
APPROVED_FAILED_FINDING

FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED

FC-F1: CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE
= OPEN / P1 BLOCKER

ROOT_CAUSE = VERIFIED（CODE + DIAGNOSTIC_VERIFIED）
  SQLAlchemy identity-map stale ComputeAccount state
  after SELECT FOR UPDATE on already-loaded ORM instance

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_TRANSACTION_INSERT = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE = FAILED
CONCURRENT_REPLAY_RESPONSE_CONVERGENCE = VERIFIED
```

### 为什么是 APPROVED_FAILED_FINDING 而非 CHANGES_REQUIRED

- 独立代码核验：record_usage step 顺序（:714→:718→:719→:725）与候选根因一致 ✅
- SQLAlchemy identity map stale：8 步根因链全部代码事实支撑（无 populate_existing / expire，同一 PK，无 version_id_col）✅
- 9 个替代根因逐项排除 ✅
- lost update 现象（txn 正确 / balance 少扣）与 identity map stale 根因逻辑自洽 ✅
- same-identity exactly-once 正确（FC-1/FC-2/FC-6 PASS），不误判为"整体失效" ✅
- 隔离 PG / 独立 Session / barrier 并发模型合理 ✅
- 治理文档仅 FAILED 状态同步，无 compute core 改动 ✅

### 证据等级

```
FC-F1 LOST UPDATE = PG_RUNTIME_VERIFIED（candidate 隔离 PG，3 轮稳定复现）
ROOT_CAUSE = CODE + DIAGNOSTIC_VERIFIED
  本审批窗口未独立 runtime 复现——根因以代码静态分析 + 诊断推理验证
  8 步根因链全部代码事实支撑，9 替代根因排除
  证据等级准确标注，未夸大为审批窗口独立 runtime 复现
```

---

## 28. Next Authorization

```
P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN
  DESIGN ONLY
  比较 Candidate A-E，选一个正式方案
  不能直接实施
```

下一设计窗口必须回答 §25 全部要求（correctness / transaction semantics / same-identity replay NO REGRESSION / distinct-event concurrency / balance insufficiency race / deadlock risk / identity map behavior / migration impact / compatibility / testability）。

本审批窗口不选择实现补丁（§20）：不修改 `_write_transaction_balance_only` / `get_or_create_account` / `record_usage`，不直接加 populate_existing / refresh / expire / atomic UPDATE / version column / advisory lock / SERIALIZABLE。

---

## 29. Final Concurrent Gate Status

```
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
  当前这一轮 Final Gate 已 FAILED
  不是 PARTIAL PASS → continue remaining checks
  修复后必须重新完整执行 Final PostgreSQL Concurrent Closure（FC-0~FC-12 全部）
```

```
COMPUTE-IDEMPOTENCY-001 = OPEN（仍未 CLOSED）
  最后仍需证明：PostgreSQL 真实并发下，同一 Business Event Identity 同时被多个事务竞争时，
  账本与余额仍 exactly-once
```

---

## 30. Commit Authorization

本审批窗口默认不 commit。允许新增：

```
docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_APPROVAL.md（本报告）
```

若审批通过，下一治理窗口可把：

```
FAILED report
approval report
FAILED status sync
```

做一个独立 checkpoint。建议 commit：

```
审计：确认算力余额并发丢失更新
```

```
DO NOT PUSH
```

不得包含任何 compute core 业务代码修改。

---

## 31. 边界遵守确认

- ✅ 未修改 compute core / record_usage / _write_transaction_balance_only / get_or_create_account（§20）
- ✅ 未修改 migration / transaction isolation（read committed 保持）
- ✅ 未直接选择实现补丁（populate_existing / refresh / expire / atomic UPDATE / version / advisory lock / SERIALIZABLE 均未实施）
- ✅ 未 commit / push
- ✅ 未重跑修复后的 Final Gate
- ✅ 未 start 其他 Phase 3B 任务 / RB-10 / 宣布 P1 CLOSED
- ✅ canonical DB 未 mutation（READ/VERIFY ONLY）
- ✅ 未重新打开 F-1 / GLOBAL_ACTIVE_NONE_AUDIT 已关闭结论

---

## 32. 完成后停止

本审批窗口完成后停止。不得自行：

- 修改 compute core
- 加 populate_existing
- 加 refresh
- 改 atomic UPDATE
- 改 locking 顺序
- 加 version 字段
- 改 isolation level
- 创建 migration
- 重跑修复后的 Final Gate
- RB-10
- push
- 宣布 P1 CLOSED

---

## 附录：审批纪律确认

- READ / VERIFY ONLY：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push。
- 未执行独立 runtime 复现——根因以代码静态分析 + 诊断推理验证，证据等级 CODE + DIAGNOSTIC_VERIFIED（准确标注，未夸大为 PG_RUNTIME_VERIFIED 独立复现）。
- 独立核验：Read `record_usage`（:679-769）/ `get_or_create_account`（:110-147）/ `_write_transaction_balance_only`（:150-184）/ `_write_transaction`（:187-267）/ ComputeAccount model（models.py:906-924）/ SessionLocal（database.py:251）/ grep version_id_col + populate_existing + expire。
- 未采信执行窗口自述：根因链 8 步逐段代码事实复核，9 替代根因逐项排除。
```
