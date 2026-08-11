# P1-FC-F1 Concurrent Balance Lost Update — 独立设计审批

> 任务：`P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN` 的独立设计审批
> 审查对象：`docs/architecture/remediation/P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_DESIGN.md`（未提交，工作区 untracked）
> 前序 checkpoint：`ef0897e`（`审计：确认算力余额并发丢失更新`）
> 日期：2026-08-11
> 窗口性质：**READ / DESIGN APPROVAL ONLY**（不实施、不提交、不改 compute core、不加 migration、不改 isolation、不重跑 Final Gate）
> Source of Truth：本窗口独立只读代码事实（`apps/compute/services.py` / `app/models.py` / `requirements.txt` + 运行时版本）> 设计报告自述 > 推测

---

## 0. Verdict 速览

| 维度 | 审批结论 |
|---|---|
| Baseline 漂移 | 无（`record_usage` / `_write_transaction_balance_only` / `get_or_create_account` 与设计一致）|
| FC-F1 根因 | 确认（identity-map stale read-modify-write，FOR UPDATE 不重新 hydrate）|
| Preferred Strategy | Candidate B — Atomic `UPDATE ... RETURNING`（B-Order-1 txn-flush-first）成立 |
| 把余额正确性从 ORM object state 转 DB row arithmetic | **成立** |
| same-key no regression | 成立（flush-first unique gate 保留）|
| distinct-key no lost update | 成立（DB 原子 `balance=balance+delta`）|
| balance_after_tokens | RETURNING 值为 authoritative（须绑定 step4 不读 stale account）|
| 负余额 contract | 保持当前（允许负，rejection = OUT_OF_P1）|
| migration | 不需要 |
| isolation | READ COMMITTED 不变 |
| SQLite | S1（Core `update().returning()` 跨方言），runtime 3.50.4 ≥ 3.35，无需 fallback |
| deadlock | 实践不可达，但设计论证"单一锁序"不准确，须修正为准确证明 |
| `_write_transaction` scope | READ ONLY / FUTURE GAP（同脆弱模式，但非 FC-F1 并发面）|

```text
VERDICT: APPROVED_WITH_CORRECTIONS
```

Candidate B 整体成立，但实施前必须冻结 8 项 corrections（C1-C8，见 §35）。本窗口不实施、不提交。

---

## 1. Technical Decision

```text
PREFERRED = Candidate B — PostgreSQL atomic UPDATE compute_accounts
            SET balance_tokens = balance_tokens + :delta, updated_at = :now
            WHERE merchant_id = :merchant_id
            RETURNING balance_tokens
            + B-Order-1（txn unique flush-first）
```

余额正确性从「ORM object 的 `locked.balance_tokens` 读-改-写」转为「PostgreSQL 单语句行级原子算术」。`balance_after_tokens` 来自 RETURNING 标量值，不经 ORM identity-map 对象。

## 2. Baseline

```text
Git baseline = ef0897e
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE = OPEN / P1 BLOCKER
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
```

保持（不重新打开）：

```text
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = RESOLVED
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_TRANSACTION_INSERT = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE = FAILED
```

## 3. Root Cause Recheck

本窗口独立读取 `apps/compute/services.py`，确认根因未变（无 BASELINE_DRIFT）：

```text
record_usage 幂等路径（services.py:681-727）：
  step 1  db.add(tx_candidate) + db.flush()                 (:714-716)  ← INSERT txn，unique gate
  step 2  get_or_create_account(db, merchant_id, autocommit=False) (:718)
          → db.query(ComputeAccount).filter(merchant_id).first()    (:120-124)  ← 普通 SELECT
          → ComputeAccount 进入 Session identity map，balance_tokens = 此刻 DB 值（可能 stale）
  step 3  _write_transaction_balance_only(db, account, delta=-billed) (:719-722)
          → db.query(ComputeAccount).with_for_update().first()       (:162-167)  ← SELECT FOR UPDATE
          → 行锁获取成功，但 SQLAlchemy identity map 默认 populate_existing=False
          → locked 指向 step 2 已加载的同一对象，balance_tokens 不重新 hydrate
          → new_balance = locked.balance_tokens + delta  (:170)  ← 旧值 + delta
          → locked.balance_tokens = new_balance          (:182)  ← ORM dirty
          → db.flush()                                     (:184)  ← UPDATE balance=旧值+delta（覆盖）
  step 4  tx_candidate.balance_after_tokens = account.balance_tokens  (:724)  ← 读 stale 对象
  step 5  db.commit()                                     (:725)
```

FC-3 稳定复现：8 worker distinct key 各 1 txn（txn 层正确），balance 只扣 -200（应 -800），lost update 600。2-worker 时序窗口小不暴露。**根因确认：FOR UPDATE 取行锁但不刷新 identity map，`locked.balance_tokens` 是 step 2 的 stale 值。**

## 4. Current Transaction Flow

见 §3。本窗口独立重建与设计报告 §3 一致，无漂移。SQL 时序标记（INSERT txn flush → 普通 SELECT account → SELECT FOR UPDATE 不刷新 → UPDATE balance 覆盖 → COMMIT）成立。

## 5. Candidate A-E 独立裁定

### A — Lock + Fresh ORM State（`populate_existing=True` / `db.expire`）

- correctness：✅（FOR UPDATE + 强制刷新 identity map 后读最新值）
- stale identity-map dependency：**高**——正确性依赖开发者记得在 FOR UPDATE 查询上加 `populate_existing`，future refactor 若再次前置读 account 即回归
- same-key regression：低（flush-first 保留）
- distinct-key concurrency：✅（FOR UPDATE 串行化）
- lock duration：FOR UPDATE 持锁 step3→commit
- deadlock：低（同当前）
- migration：无
- isolation：不变
- SQLite：`populate_existing` 跨方言，`with_for_update` SQLite no-op
- complexity：最低（~1-3 行）
- rollback：可接受 ValueError
- **裁定：可行但脆弱。最小 diff 但非最健壮，依赖 ORM identity-map 纪律。**

### B — Atomic UPDATE ... RETURNING（B-Order-1）

- correctness：✅（DB 单语句行级原子算术，无 read-modify-write）
- stale identity-map dependency：**无**（step3 不返回 ORM 对象，balance 来自 RETURNING 标量；须绑定 step4 不读 stale account）
- same-key regression：低（flush-first 保留，loser 在 step1 IntegrityError 不触 step3）
- distinct-key concurrency：✅（atomic `balance=balance+delta` 行锁串行化）
- lock duration：account 行锁 step3 UPDATE→step5 commit（PG 行锁持续到事务结束）
- deadlock：实践不可达（见 §18-§19 准确证明，设计原论证须修正）
- migration：无
- isolation：READ COMMITTED 不变
- SQLite：✅（3.50.4 支持 RETURNING，S1 跨方言）
- complexity：低-中（Core `update().returning()` + 标量取值 + step4 改 RETURNING 值）
- rollback：可接受
- **裁定：PREFERRED。最健壮，不依赖 ORM 纪律。**

### C — Lock-before-read reorder

- correctness：✅
- stale identity-map dependency：中（消除前置普通 SELECT，但仍 ORM read-modify-write）
- same-key：中（改竞争面）
- distinct-key：✅
- lock duration：**最长**（FOR UPDATE 持锁 step2→commit，覆盖 txn insert）
- deadlock：中（持锁跨 insert，与反向锁序 worker 理论可死锁）
- migration：无；SQLite：✅
- **裁定：REJECTED（B 优于 C：lock 更短、不依赖 ORM r-m-w、余额不足未来可原子）。**

### D — Optimistic version / CAS

- correctness：✅
- stale identity-map dependency：无
- same-key：✅；distinct-key：✅（CAS retry）
- migration：**需 version column**（违反 NO MIGRATION）
- complexity：高（retry loop + 所有 balance path 都改）
- **裁定：REJECTED（migration + 复杂度 + 影响面）。**

### E — SERIALIZABLE

- correctness：✅
- blast radius：**大**（所有 9000 DB workload 受影响，不只是 compute）
- migration：无但需 isolation 配置变更
- complexity：高（serialization failure retry）
- **裁定：REJECTED（blast radius + 吞吐下降，B 在 READ COMMITTED 下已正确）。**

## 6. Candidate Matrix（本窗口独立产出，非复制设计）

| Candidate | Correctness | ORM 依赖 | Same-Key | Distinct-Key | Deadlock | SQLite | Migration | Verdict |
|---|---|---|---|---|---|---|---|---|
| A Lock+populate_existing | ✅ | 高（identity-map 纪律） | ✅ 保留 | ✅ FOR UPDATE 串行 | 低 | ✅ | 无 | 可行但脆弱 |
| **B Atomic UPDATE RETURNING** | ✅ | 无（标量 RETURNING） | ✅ flush-first | ✅ DB 原子 | 低（跨路径反向序存在但不可达） | ✅ 3.50.4 | **无** | **PREFERRED** |
| C Lock-before-read | ✅ | 中（仍 r-m-w） | ✅ | ✅ | 中（持锁跨 insert） | ✅ | 无 | REJECTED |
| D Optimistic version | ✅ | 无 | ✅ | ✅（retry） | 低 | ✅ | **需 version 列** | REJECTED |
| E SERIALIZABLE | ✅ | 无 | ✅ | ✅ | 中（retry） | N/A | 无（需 isolation） | REJECTED |

## 7. Preferred Strategy

```text
PREFERRED = Candidate B — Atomic UPDATE ... RETURNING（B-Order-1，txn-flush-first）

step 1  db.add(tx_candidate) + db.flush()        ← INSERT txn（unique gate，保留 same-key exactly-once）
step 2  ensure account exists（get_or_create_account，existence-only，不依赖返回 balance）
step 3  UPDATE compute_accounts
          SET balance_tokens = balance_tokens + :delta, updated_at = :now
          WHERE merchant_id = :merchant_id
          RETURNING balance_tokens                ← DB 原子，消除 lost update
step 4  tx_candidate.balance_after_tokens = RETURNED new_balance（不用 account.balance_tokens）
step 5  db.commit()                               ← txn INSERT + account UPDATE + txn balance_after UPDATE 原子
step 6  IntegrityError → rollback → replay（同当前）
```

满足全部 contract：same-key exactly-once 不回归（flush-first）、distinct-key 不 lost update（atomic）、balance_after 正确（RETURNING）、无 migration、READ COMMITTED。

## 8. B-Order-1 安全性（第一硬门槛）

本窗口独立读取 `app/models.py` 确认 B-Order-1 顺序合法：

- `ComputeTransaction.balance_after_tokens = Column(Integer, nullable=False)`（models.py:980）——**NOT NULL，无 default**。
- 故 step 1 的 `tx_candidate` 必须显式给 `balance_after_tokens` 赋值才能 INSERT。当前代码 :696 `balance_after_tokens=0`（占位）。B-Order-1 保留此占位，legal。
- step 1 flush（INSERT）→ step 2 ensure account → step 3 atomic UPDATE → step 4 改 balance_after → step 5 commit。此顺序在 model/schema 层合法：占位 0 通过 NOT NULL，真实值在 commit 前由 step 4 写入。

**B-Order-1 顺序合法。** ✅

## 9. tx_candidate Flush 时的 balance_after_tokens（第二硬门槛 / 硬问题）

**问题**：step 1 `db.flush()` 时，真实 `balance_after_tokens` 尚未从 atomic UPDATE RETURNING 得到。

**独立确认**：
- model nullable：`balance_after_tokens` NOT NULL（models.py:980）。
- DB nullable：NOT NULL。
- default：无。
- candidate 构造逻辑：services.py:696 `balance_after_tokens=0`（显式占位）。
- 当前 record_usage 初始化：同上，`:696`。
- flush 产生的真实 SQL：`INSERT INTO compute_transactions (..., balance_after_tokens=0, ...)`。

**结论**：step 1 flush 时 `balance_after_tokens = 0`（provisional 占位，唯一目的是满足 NOT NULL 让 INSERT 通过）。**无隐藏错误值**——0 是显式占位，且永不作为终值 commit（见 §11）。

## 10. Provisional 占位值的修正生命周期

`balance_after_tokens=0` 占位 → step 3 atomic UPDATE RETURNING `new_balance` → step 4 `tx_candidate.balance_after_tokens = new_balance`（ORM 标记 dirty）→ step 5 `db.commit()`。

**step 4 是否在 commit 前产生第二条 `UPDATE compute_transactions SET balance_after_tokens=...`？**
**是。** `tx_candidate` 在 step 1 已 `db.add` + flush 进入 Session；step 4 修改其属性 → ORM 标记 dirty → step 5 commit 时 SQLAlchemy 发出 `UPDATE compute_transactions SET balance_after_tokens=:new_balance WHERE id=:txn_id`。该 UPDATE 与 step 3 的 account UPDATE 在**同一 DB transaction**内，由 step 5 一次 commit 原子提交。

**占位 0 永不作为终值 commit**：step 4 无条件在 commit 前执行；唯一步 4 被跳过的路径是 step 3 抛异常 → 整事务 rollback → 根本不 commit。故 PG 中不会留下 `balance_after_tokens=0` 的半成品终值。✅

**异常原子性**：若 step 3 atomic UPDATE 成功后、step 4/5 前发生异常 → 同一 DB transaction rollback → step 3 的 account UPDATE 与 step 1 的 txn INSERT **同时撤销**。✅（见 §23）

## 11. 更优顺序是否存在

- **Current Preferred（B-Order-1）**：INSERT txn flush → account atomic UPDATE → UPDATE txn.balance_after。
- **备选（B-Order-2，balance-update-first）**：account UPDATE first → txn INSERT later。

B-Order-2 的 same-key loser 会先扣余额（step1 UPDATE 成功）再 INSERT txn（UNIQUE 冲突）→ rollback 恢复。虽 rollback 可恢复，但：rollback 失败/进程崩溃 → 余额已扣无 txn（Bad B）；并发窗口内余额短暂错误；证明复杂。**B-Order-2 REJECTED**，B-Order-1 的关键优势——**same-key unique gate 发生在 balance mutation 之前**——独立成立，冻结。

## 12. Same-Key Race 硬证明

worker A（merchant M + key K）vs worker B（merchant M + key K），B-Order-1：

```text
winner: step1 flush 成功（获得 (M,K) unique ownership）→ step3 UPDATE → commit
loser : step1 flush → UNIQUE 冲突 IntegrityError（在 step3 之前）→ rollback → 不执行 step3 balance mutation → replay
```

PostgreSQL unique insert 并发语义：两并发 INSERT 同一 (merchant_id, idempotency_key) → 一个成功，另一个在 unique index 上冲突 → `IntegrityError`（23505）。当前 catch（services.py:728 `except IntegrityError`）→ rollback（:731）→ 查 existing txn（:733-740）→ payload_evidence 匹配则 replay（:747-756）。

**证明 loser 不触 balance mutation**：step3（balance mutation）严格在 step1 flush 之后。loser 在 step1 即 IntegrityError → rollback → 控制流跳到 except 块，never reaches step3。**loser 不会先扣余额。** ✅

## 13. IntegrityError Catch 范围

当前 catch：`except IntegrityError:`（:728），覆盖 try 块（:716-727）内所有 DB 操作。

**duplicate idempotency-key unique violation 能否正确进入 replay？** ✅（见 §12）。

**Candidate B 新增的 atomic UPDATE 是否可能产生其他 IntegrityError 被误判为 replay？**
- `compute_accounts` 表约束：仅 `uk_compute_accounts_merchant`（unique merchant_id）。无 CHECK 约束。
- atomic UPDATE `SET balance_tokens = balance_tokens + delta` 不改 merchant_id → 不触 unique。
- 无 CHECK → UPDATE 不产生 IntegrityError。
- 故 step3 atomic UPDATE **不会**抛 IntegrityError。IntegrityError catch 仍仅覆盖 step1 flush 的 UNIQUE 冲突。✅

**catch all IntegrityError → assume replay 的风险**：新方案下 step3 不产生 IntegrityError，故无「非 duplicate DB 问题误判为 replay」风险。✅

**0-rows（account 不存在）**：step2 get_or_create_account 已 ensure account 存在，step3 UPDATE 应返回 1 row。若防御性返回 0 rows → 须映射 `COMPUTE_ACCOUNT_MISSING` ValueError（**非 IntegrityError**，不进 replay catch）。具体检测方式见 C8。

## 14. Atomic UPDATE

```sql
UPDATE compute_accounts
SET balance_tokens = balance_tokens + :delta, updated_at = :now
WHERE merchant_id = :merchant_id
RETURNING balance_tokens
```

PostgreSQL 单语句行级原子：DB 自身完成 read-modify-write，行锁串行化并发 UPDATE。无 ORM identity-map 参与。✅

## 15. ORM Identity Map After UPDATE

Candidate B step3 用 Core `update(ComputeAccount).where(...).values(...).returning(balance_tokens)` + `db.execute()`。此构造不返回 ORM Entity，不 hydrate identity-map 对象。但 **step2 `get_or_create_account` 已把 ComputeAccount 对象放入 identity map**（balance 可能 stale）。

atomic Core UPDATE 不会天然刷新该对象的 `balance_tokens` 属性。故 step3 之后，Session 内的 `account.balance_tokens` 仍是 step2 时刻的 stale 值。

## 16. Downstream Stale Read Audit

本窗口全量搜索 `apps/compute/services.py` 中 `account.balance_tokens` / `db.refresh(account)` 的读取点：

| 行 | 位置 | 在幂等路径 stale 窗口（step3→commit）内？ | 处理 |
|---|---|---|---|
| :724 | `tx_candidate.balance_after_tokens = account.balance_tokens` | **是** ← stale 读，**必须改为 RETURNING 值** | C2 |
| :726 | `db.refresh(account)` | 否（commit 后） | 保留（commit 后回填，返回 caller 正确 account）|
| :146 | get_or_create_account autocommit 分支 `db.refresh` | 否（独立函数）| 不影响 |
| :338 | get_summary 读 balance | 否（独立函数）| 不影响 |
| :874/:886 | create_mock_recharge_order | 否（独立函数，走 _write_transaction）| 不影响 |

**幂等路径内唯一直读 stale `account.balance_tokens` 的点是 :724（step4）。** Candidate B 须将其改为 `tx_candidate.balance_after_tokens = returned_new_balance`。step3 与 step5 之间无其他读 account.balance_tokens 的代码（logging/validation/event hooks 均无）。✅

## 17. Account Creation

`get_or_create_account`（services.py:110-147）并发首次创建：
- 普通 SELECT（:120-124）。
- None → `begin_nested`（SAVEPOINT）+ INSERT + `IntegrityError` 恢复（:127-143）。
- `uk_compute_accounts_merchant`（models.py:916）保证一商户一行。

两 distinct event 首次并发：winner SAVEPOINT INSERT 成功；loser SAVEPOINT INSERT → UNIQUE 冲突 → rollback SAVEPOINT → re-SELECT 复用。**当前正确处理，Candidate B 不影响此流程。** ✅

Candidate B 下 `get_or_create_account` 降为 **existence-only**：确保 account 行存在，其返回的 `account.balance_tokens` **不参与余额计算**（step3 不读它）。职责拆分成立。✅

## 18. All ComputeAccount Mutation Paths（全量枚举）

本窗口 grep `balance_tokens =` / `.balance_tokens =` 的生产写入点（排除 test）：

| 行 | 函数 | 路径 | 锁序 |
|---|---|---|---|
| :131 | `get_or_create_account` | account 创建，balance=0 | — |
| :182 | `_write_transaction_balance_only` | record_usage 幂等（consume 负 delta）| txn flush → account FOR UPDATE |
| :237 | `_write_transaction` | recharge/grant/None-path/mock_recharge | account FOR UPDATE → txn INSERT |

**生产余额变更仅这 2 个函数**（+ get_or_create_account 的 0 值建账）。无 admin router / 其他模块直写 balance_tokens。recharge/grant/mock_recharge 全部经 `_write_transaction`。

`record_usage` 生产 caller（经 `_record_usage`）：`douyin_webhook.py:1242`、`ai_edit_las_service.py:740`、`wechat_task_service.py:503`、`material_analysis.py:282`——全部 ACTIVE consumer，全部产生 consume（负 delta，:695 `delta_tokens=-billed_tokens`）。

`_write_transaction` caller：`:538 recharge_merchant`、`:565 grant_package_to_merchant`、`:778 record_usage None-path`、`:875 create_mock_recharge_order`。

## 19. Cross-Path Lock Ordering（第二硬门槛 / Deadlock）

**关键发现：锁序反向存在。**

| 路径 | 锁序 |
|---|---|
| record_usage 幂等（Candidate B）| step1 INSERT txn unique index → step3 account row（atomic UPDATE）|
| `_write_transaction`（recharge/grant/None/mock_recharge）| step FOR UPDATE account row → step INSERT txn |

`_write_transaction` 先取 account 行锁（:217-222），再 INSERT txn（:260）——与幂等路径**反向**。设计报告 §21 声称「所有 worker 单一锁序 txn→account」**不准确**，只分析了 record_usage 幂等路径，未审计 `_write_transaction`。

## 20. Deadlock 结论（精确）

**deadlock 实践不可达，但论证须修正。** 准确证明：

资源：R1 = account 行（merchant M）；R2 = txn unique index entry (merchant M, idempotency_key K)。

- R2 仅在**相同 (M, K)** 时竞争。`_write_transaction` 产生的 txn `idempotency_key` 恒为 **NULL**（`ComputeTransaction(...)` 构造时不传 idempotency_key → None）。PostgreSQL unique 约束中 NULL ≠ NULL，**NULL 不参与唯一约束**（models.py:940-941 注释确认），多个 NULL 共存。
- 故 `_write_transaction` 的 INSERT 永不在 R2 上等待（NULL entry 不与任何 K 冲突，也不与其他 NULL 冲突）。
- 反向锁序 cycle 需要：幂等 worker 持 R2(K) 等 R1(M)，同时 `_write_transaction` worker 持 R1(M) 等 R2。但后者等的是 R2(NULL)/R2(K')，与前者 R2(K) 不竞争 → 后者不等 → 无 cycle。

枚举所有并发组合均无 deadlock：
- 幂等(K1) vs 幂等(K2) distinct：R2 不竞争，R1 同向串行。✅
- 幂等(K) vs 幂等(K) same：loser 在 R2 flush 处 IntegrityError 早夭，不触 R1。✅
- `_write_transaction` vs `_write_transaction`：都先争 R1，串行；INSERT NULL 不竞争。✅
- 幂等(K) vs `_write_transaction`(NULL)：幂等持 R2(K) 等 R1(M)；`_write_txn` 持 R1(M) 等 R2(NULL)（不等）→ 完成释放 R1 → 幂等获取。单向等待。✅

```text
DEADLOCK RISK = LOW / VERIFIED NONE（实践不可达）
但 CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE（须登记）
```

`_write_transaction` 的反向锁序是预存结构事实，非 Candidate B 引入。若未来统一 `_write_transaction` 到 atomic UPDATE（与 Candidate B 同序），反向锁序消失。当前按 §22 scope 保持 READ ONLY。

## 21. `_write_transaction` 同类脆弱模式

`_write_transaction`（:187-267）有**相同** lost-update 模式：`get_or_create_account`（caller 调用，如 recharge_merchant :534 autocommit=True → commit+refresh）加载 account 入 identity map → `_write_transaction` 内 FOR UPDATE（:217）不重新 hydrate → `locked.balance_tokens` stale → :237 覆盖。

但 runtime classification：
- recharge_merchant / grant_package_to_merchant：admin 操作，低频。
- create_mock_recharge_order：用户充值（mock 到账），中频但非 P1 并发 consume gate。
- record_usage None-path（:778）：legacy bare deduction，Global Audit 判 COMPATIBILITY/DORMANT（F-2 同类，无 ACTIVE 触发）。

**`_write_transaction` 不是 FC-F1 并发 distinct-identity consume 面**。其 lost-update 模式真实存在，但不在 FC-F1 正式并发范围内。

## 22. Scope Boundary

```text
_write_transaction = READ ONLY / FUTURE GAP（非 FC-F1 并发面）
```

理由：FC-F1 = record_usage 幂等路径的 concurrent distinct-identity balance lost update。`_write_transaction` 的 caller 非 ACTIVE 高频并发 consume。Candidate B 只改 `_write_transaction_balance_only`（record_usage 幂等），对 FC-F1 并发 distinct-identity consume 的 balance concurrency 闭环充分。`_write_transaction` 同脆弱模式登记为 future governance（非 P1 blocker）。

## 23. Transaction + Account Atomicity（硬 contract）

```text
transaction exists  iff  account delta committed
```

B-Order-1：step1（INSERT txn flush）+ step3（UPDATE account）+ step4（UPDATE txn balance_after）+ step5（commit）**同一 DB transaction**。
- step3 失败 → rollback → txn INSERT + account UPDATE 均撤销（Bad A 不发生）。
- step1 UNIQUE 失败 → IntegrityError → rollback → balance 未触（Bad B 不发生）。
- commit 原子：txn + balance 同 commit 或同 rollback。✅

## 24. balance_after_tokens Authoritative Source

```text
tx_candidate.balance_after_tokens 的唯一 authoritative source = step3 RETURNING new_balance
```

不得用 `old account.balance + delta` 再次计算（那是 stale read-modify-write 的复现）。step4 直接赋 RETURNING 值。✅

## 25. Concurrent balance_after Semantics

```text
B0=1000, A delta=-100, B delta=-100 并发
合法 serialized 结果：A=900/B=800 或 A=800/B=900（DB 行锁决定顺序）
非法：A=900/B=900 而 final=800（lost update）
```

Candidate B 的 atomic UPDATE + RETURNING 天然满足：每个 worker 的 RETURNING 值 = 该 worker 在串行顺序中完成后的真实余额。测试须允许任意合法串行顺序，不绑定 txn id 顺序。✅

## 26. Negative Balance Contract

独立确认当前 contract（代码事实）：
- `balance_tokens = Column(Integer, nullable=False, default=0)`（models.py:922），**无 CHECK 约束禁止负**。
- `_write_transaction_balance_only:173` `if new_balance < 0:` 仅 `warning`，不阻断。
- `_write_transaction:228` 同。
- docstring（services.py:214）："负余额写结构化 warning（不阻断）"。

```text
B0=100, A=-80, B=-80 并发：
当前正确业务结果 = 两笔均 commit，final = -60，2 txn，各 balance_after 正确串行化
```

**Candidate B 不得在 FC-F1 引入 `WHERE balance_tokens + :delta >= 0`**——那是新业务语义（rejection），非并发 bug 修复。保持允许负余额。✅

## 27. FC-R1 Correction

设计报告 §28/§17.3 的 "FC-R1 insufficient balance" 命名与当前 contract 冲突，须修正：

```text
FC-R1 = CONCURRENT NEGATIVE-BALANCE ARITHMETIC
B0=100, K-A=-80, K-B=-80 并发（当前 contract 允许负）：
  success=2, final=-60, txn=2, 各 delta preserved, 各 balance_after 串行正确
INSUFFICIENT_BALANCE_REJECTION = N/A / OUT_OF_P1（新业务语义，需独立审批）
```

设计 §17.3 已表明"实施窗口按当前 contract（允许负）验证"，方向正确，仅命名/措辞须修正（C3）。

## 28. Positive Delta

`record_usage` 幂等路径**只产生 consume**（:694 `transaction_type=CONSUME_TYPE`，:695 `delta_tokens=-billed_tokens`，billed_tokens>0 故恒负）。Candidate B 的 `balance = balance + delta` 对负 delta 正确。

正 delta（recharge/grant）走 `_write_transaction`，非 Candidate B scope。若未来统一，B 对正 delta 同样正确（`balance + positive_delta`）。T9 仅在"扩展到 _write_transaction"时适用，FC-F1 scope 内 N/A。✅

## 29. READ COMMITTED

```text
isolation = READ COMMITTED（PG 默认，冻结）
```

atomic UPDATE 是单语句行级原子，不依赖 isolation level。READ COMMITTED 下并发 UPDATE 同行由行锁串行化，每个 UPDATE 读到最近 committed 值并累加。不需 SERIALIZABLE。✅ **NO ISOLATION CHANGE。**

## 30. SQLite Strategy（冻结）

本窗口确认运行时 SQLite 版本：

```text
sqlite3.sqlite_version = 3.50.4（≥ 3.35，支持 UPDATE ... RETURNING）
```

**冻结策略 = S1**：同一 SQLAlchemy Core `update(ComputeAccount).where(...).values(...).returning(balance_tokens)` 跨 PG/SQLite 方言透明。当前 SQLite runtime 3.50.4 支持 RETURNING，**无需 fallback**。设计 §24.3「若 SQLite < 3.35 需 fallback / 实施窗口验证版本」须修正为：当前 runtime 已验证 3.50.4，S1 成立，"<3.35 fallback" 列为 future-guard 而非留给实现的决定（C5）。

SQLite 无并发（单写者），lost update 本不暴露；`with_for_update` 已是 no-op；Candidate B 不破坏 SQLite 路径。现有 `tests/test_compute_service.py` 用 `sqlite:///:memory:`（:33），Candidate B 须在该 fixture 下保持 T1-T10 通过。

## 31. Migration Decision

```text
MIGRATION = NO
```

- `balance_tokens` 列已存在（models.py:922）。
- `uk_compute_accounts_merchant` 已存在（:916）。
- `uk_compute_transactions_merchant_idempotency` 已存在（models.py:941）。
- Candidate B 不加 version column（D 才需）、不加新约束、不加 CHECK。
- 余额不足 rejection 是 OUT_OF_P1。✅

## 32. Application Role

```text
新 SQL 由 auto_wechat application principal 执行
```

`UPDATE compute_accounts SET balance_tokens=...` + `INSERT/UPDATE compute_transactions` 均为 DML。app role 非 superuser 有业务表 DML 权限（PR-3 VERIFIED，60 业务表 DML）。不需 owner/superuser/DDL/elevated lock。Fresh Bootstrap permission contract 不变。✅

## 33. Focused Tests

设计 §27 的 T1-T10 覆盖充分，本审批要求至少：

| T | 验证 | Gate |
|---|---|---|
| T1 | single charge behavior unchanged | 基线 |
| T2 | sequential same-key replay | R1 |
| T3 | same-key concurrent N-way（N≥8）| R2 / FC-1/FC-2 |
| T4 | distinct-key concurrent exact balance（N≥8, ≥5 rounds）| R4 / FC-3 |
| T5 | concurrent negative-balance arithmetic（B0=100, 两 -80 → final=-60, 2 txn）| §26/§27（按当前 contract，非 rejection）|
| T6 | merchant isolation（同 key 不同 merchant）| R3 / FC-4 |
| T7 | transaction+account rollback atomicity（step3 失败 → txn 回滚）| §23 |
| T8 | balance_after_tokens serialized correctness（RETURNING = 串行真实值）| §24/§25 |
| T9 | positive delta（仅若扩展到 _write_transaction；FC-F1 scope 内 N/A）| §28 |
| T10 | SQLite compatibility（S1，sqlite:///:memory: 通过）| §30 |

**不**把"insufficient balance rejection"作为 FC-F1 硬 Gate（OUT_OF_P1）。T5 改为"按当前允许负 contract 验证两笔均 commit、final=-60、各 delta preserved"。

## 34. Final Concurrent Re-Run

实施 + 独立实施审批通过后，**完整重跑**（非只 FC-3）：

```text
FC-1 same-key 2-way
FC-2 same-key N-way multi-round
FC-3 distinct-key N-way multi-round ← 修复目标
FC-4 merchant isolation
FC-5 competing payload
FC-6 post-race replay
FC-7 error/deadlock audit
FC-8 ledger reconciliation
FC-9 global balance closure
FC-10 app principal
FC-11 cleanup
FC-12 canonical no-drift
FC-R1 concurrent negative-balance arithmetic（按当前 contract：允许负 → 两笔均 commit final=-60）
FC-R2 mixed same-key + distinct-key workload（补强 Gate）
```

## 35. Corrections（实施前必须冻结）

- **C1 — tx_candidate provisional balance_after 生命周期**：显式冻结 `balance_after_tokens=0` 为 step1 INSERT 占位（满足 NOT NULL，models.py:980 无 default），step4 用 RETURNING `new_balance` 覆盖，step5 commit；占位 0 永不作为终值 commit；step3 成功后 step4/5 前异常 → 同事务 rollback 同时撤销 account UPDATE + txn INSERT。
- **C2 — 禁止 step3 后读 stale account**：step4（:724 当前 `tx_candidate.balance_after_tokens = account.balance_tokens`）**必须**改为 `= returned_new_balance`；step3 Core UPDATE 须带 `.execution_options(synchronize_session=False)`；保留 `db.refresh(account)`（:726，commit 后回填，返回 caller 正确 account）。step3→step5 间不得有任何 `account.balance_tokens` 读取（已审计仅 :724 一处）。
- **C3 — FC-R1 命名/语义修正**：`FC-R1 insufficient balance` → `FC-R1 CONCURRENT NEGATIVE-BALANCE ARITHMETIC`；按当前允许负 contract 验证（两笔均 commit，final=-60，2 txn）；删除"1 success 1 insufficient"误导措辞；`INSUFFICIENT_BALANCE_REJECTION = OUT_OF_P1` 保持。
- **C4 — Deadlock 论证修正**：设计"单一锁序 txn→account"不准确。准确结论：`_write_transaction`（recharge/grant/None/mock_recharge）锁序为 account→txn，与幂等路径反向；但 deadlock 实践不可达，因 txn unique index 仅相同 (M,K) 竞争且 `_write_transaction` 的 idempotency_key 恒为 NULL（NULL 不参与唯一约束），故跨路径无 wait-cycle。登记 `CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE`；若未来统一 `_write_transaction` 到 atomic UPDATE 则反向锁序消失。
- **C5 — SQLite 策略冻结为 S1**：Core `update().returning()` 跨方言；当前 runtime sqlite3 3.50.4（≥3.35）已验证支持 UPDATE RETURNING，无需 fallback；"<3.35 fallback"列为 future-guard，非留给实现的决定。
- **C6 — 性能表征修正（minor）**：Candidate B 的 account 行锁持锁区间为 step3 UPDATE 至 step5 commit（PG 行锁持续到事务结束，非"仅 UPDATE 语句时长"），与当前 FOR UPDATE 持锁窗口相当；B 相对 Candidate C 的优势是更晚获锁（step3 vs step2），非"持锁仅 UPDATE"。不影响正确性。
- **C7 — 范围守卫位置（impl）**：当前 `_balance_within_bigint_range` 预检 `new_balance`。Candidate B 下 balance 由 DB 计算（`balance+delta`），预检需 old_balance（不可无读）。冻结为：**post-UPDATE 对 RETURNING `new_balance` 做范围校验**（超出则 raise `COMPUTE_BALANCE_OUT_OF_RANGE` ValueError，触发 rollback）；极端 `balance+delta` 溢出列域（`balance_tokens` 为 `Integer` 4-byte）时由 PG 抛 `DataError`（非 `IntegrityError`，**不**被 replay catch 误捕）→ rollback 保护一致性 → 500。不回归 IntegrityError replay scope。
- **C8 — 0-rows 检测（impl）**：step3 用 `result.scalar_one_or_none()`；返回 None → raise `COMPUTE_ACCOUNT_MISSING` ValueError（**非** `NoResultFound` 泄漏，**非** `IntegrityError` 误判 replay）。step2 已 ensure account 存在，0-rows 为防御性。

## 36. Verdict

```text
VERDICT: APPROVED_WITH_CORRECTIONS
```

Candidate B（atomic UPDATE...RETURNING，B-Order-1 txn-flush-first）整体成立：
1. 消除 lost update（DB 原子算术，不依赖 ORM identity-map）。
2. same-key no regression（flush-first unique gate 保留，loser 在 step1 IntegrityError 不触 balance mutation）。
3. balance_after_tokens 正确（RETURNING 真实串行值，绑定 C2 不读 stale account）。
4. 无 migration / READ COMMITTED 不变 / 无 isolation 变化。
5. 余额不足保持当前 contract（允许负，rejection = OUT_OF_P1）。
6. API contract 不变（record_usage 返回值不变）。
7. scope 小（仅 record_usage 幂等路径 step2/3/4 + `_write_transaction_balance_only`，1 caller）。
8. deadlock 实践不可达（C4 修正论证后成立）。

但实施前必须冻结 C1-C8。其中 C1/C2/C4 为正确性硬约束，C3/C5 为语义/策略冻结，C6/C7/C8 为实现精度约束。

## 37. Implementation Authorization

授权：

```text
P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-IMPLEMENTATION
```

实施范围（按审批冻结方案）：

```text
MODIFY  apps/compute/services.py
        — record_usage 幂等路径 step2/3/4（C1/C2/C7/C8）
        — _write_transaction_balance_only 重构或废弃（仅 1 caller：record_usage :719）
CREATE/MODIFY  focused compute concurrency tests（T1-T10 + FC-R1 + FC-R2）
CREATE  P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_REPORT.md
```

默认：

```text
NO MODEL          （balance_after_tokens 仍 NOT NULL，占位 0 保留）
NO SCHEMA
NO MIGRATION
NO 9100
NO CONSUMER IDENTITY CHANGE
NO GLOBAL ISOLATION CHANGE
NO _write_transaction 改动（READ ONLY / FUTURE GAP）
```

`_write_transaction`（recharge/grant/None-path/mock_recharge）scope = **READ ONLY**，理由见 §21/§22。其同脆弱模式登记为 future governance gap，非 P1 blocker，不在本实施窗口处理。

```text
ROLLBACK = CODE-ONLY（无 migration，git revert apps/compute/services.py 即可，无 schema 影响）
```

## 38. Governance State（保持，不提前写 RESOLVED）

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
FC-F1 = OPEN / DESIGN_APPROVED_WITH_CORRECTIONS
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED（保持）
F-1 = RESOLVED（保持）
```

## 39. 14 Required Questions

**Q1. Preferred concurrency mechanism？**
Candidate B — PostgreSQL atomic `UPDATE compute_accounts SET balance_tokens = balance_tokens + :delta RETURNING balance_tokens`（B-Order-1 txn-flush-first）。

**Q2. 为什么不再受 stale identity-map 影响？**
step3 Core UPDATE 不返回 ORM 对象，不污染 identity map；`balance_after_tokens` 来自 RETURNING 标量，不经 account 对象。step2 `get_or_create_account` 降为 existence-only，其返回的 `account.balance_tokens` 不再被读（C2 绑定 :724 改 RETURNING 值）。

**Q3. same-key concurrent replay 为什么不回归？**
B-Order-1 保留 step1 `db.add(tx_candidate) + db.flush()`（unique gate）。same-key loser 在 step1 即 UNIQUE 冲突 IntegrityError → rollback → 不执行 step3 balance mutation → replay（:728-756）。flush-first 在 balance mutation 之前。

**Q4. distinct-key concurrent 为什么不 lost update？**
step3 atomic `balance = balance + delta` 是 DB 单语句行级原子。concurrent distinct delta → 行锁串行化 → 依次累加。无 ORM read-modify-write，无 stale 覆盖。

**Q5. B0=100，两笔 -80 并发结果？**
**按当前 contract（允许负余额）**：两笔均 commit，final = 100-80-80 = -60，2 txn，各 balance_after_tokens 正确串行化。§5 的"一笔 insufficient"是新业务语义（OUT_OF_P1，默认不引入）。FC-R1 按此 contract 验证（C3）。

**Q6. transaction row 与 account mutation 如何原子？**
step1（INSERT txn flush）+ step3（UPDATE account）+ step4（UPDATE txn balance_after）+ step5（commit）同一 DB transaction。commit 原子：同 commit 或同 rollback。Bad A/B 不发生（§23）。

**Q7. balance_after_tokens 如何得到正确值？**
step3 `UPDATE ... RETURNING balance_tokens` 返回该 UPDATE 实际写入的新 balance = 该 worker 串行化后的真实余额。step4 填入 `tx_candidate.balance_after_tokens`（C2：不用 account.balance_tokens）。

**Q8. account 不存在时如何处理？**
step2 `get_or_create_account`（existence-only，SAVEPOINT + IntegrityError 恢复）确保 account 行存在。step3 atomic UPDATE 在 account 存在后执行。若防御性 0 rows → `COMPUTE_ACCOUNT_MISSING` ValueError（C8：`scalar_one_or_none()` + None 检测，非 IntegrityError）。

**Q9. deadlock 风险与锁顺序？**
B-Order-1 锁序：txn unique index（step1）→ account row（step3）。`_write_transaction` 反向（account→txn）但 idempotency_key 恒 NULL，不参与唯一约束，故跨路径无 wait-cycle。deadlock 实践不可达（C4 修正论证）。登记 `CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE`。

**Q10. 是否需要 migration？**
不需要（§31）。balance_tokens 列 + uk_compute_accounts_merchant + uk_compute_transactions_merchant_idempotency 均已存在。Candidate B 不加 version column / 新约束 / CHECK。

**Q11. 是否改变 READ COMMITTED？**
不改变（§29）。Candidate B 在 READ COMMITTED 下正确（atomic UPDATE 不依赖 isolation level）。

**Q12. SQLite 是否受影响？**
SQLite `with_for_update` 已 no-op；UPDATE RETURNING SQLite 3.35+ 支持，当前 runtime 3.50.4 已验证。Candidate B 用 Core `update().returning()`（S1 跨方言）。SQLite 无并发，lost update 本不暴露（C5）。

**Q13. 预计改哪些文件？**
`apps/compute/services.py`（record_usage 幂等路径 step2/3/4 + 重构/废弃 `_write_transaction_balance_only`，1 caller）+ focused tests（T1-T10 + FC-R1 + FC-R2）+ 实施报告。无 migration / 9100 / schema / `_write_transaction` 改动。

**Q14. 如何完整重跑 Final Concurrent Gate？**
修复实施审批通过后，完整重跑 FC-1~FC-12 + FC-R1（negative-balance arithmetic）+ FC-R2（mixed workload），非只 FC-3（§34）。验证 same-key（FC-1/2/6 no regression）+ distinct-key（FC-3/8/9 fixed）+ negative-balance（FC-R1）+ mixed（FC-R2）。

---

## 审批窗口停止点

```text
P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN-APPROVAL:
VERDICT = APPROVED_WITH_CORRECTIONS
  Preferred = Candidate B（atomic UPDATE...RETURNING，B-Order-1 txn-flush-first）
  Corrections C1-C8（C1/C2/C4 正确性硬约束，C3/C5 语义冻结，C6/C7/C8 实现精度）
  same-key no regression（flush-first 保留）
  distinct-key no lost update（DB 原子）
  balance_after_tokens = RETURNING 真实值（C2 绑定不读 stale account）
  无 migration / READ COMMITTED / 余额不足保持允许负（rejection OUT_OF_P1）
  _write_transaction = READ ONLY / FUTURE GAP
  CROSS_PATH_LOCK_ORDER_GAP = OUT_OF_FC-F1 / FUTURE GOVERNANCE（登记）
本窗口不实施、不提交，停止。
```

未自行：修改 `apps/compute/services.py` / 加 `populate_existing` / 加 `session.refresh` / 加 atomic UPDATE / 调整锁顺序 / 加 version column / 修改 isolation / 创建 migration / 重跑 Final Concurrent Gate / RB-10 / push / 宣布 P1 CLOSED。
