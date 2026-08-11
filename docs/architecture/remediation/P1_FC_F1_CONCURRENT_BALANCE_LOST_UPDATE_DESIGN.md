# P1-FC-F1 Concurrent Balance Lost Update 技术设计

> 任务：`P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION`）
> 前序：`P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE.md`（`FAILED`）+ `..._APPROVAL.md`（`APPROVED_FAILED_FINDING`，ROOT_CAUSE VERIFIED）
> Governance checkpoint：`ef0897e`（`审计：确认算力余额并发丢失更新`）
> 日期：2026-08-11
> 窗口性质：**DESIGN ONLY**（不实施 compute core、不创建 migration、不写 DB、不改 isolation）
> Source of Truth：本窗口独立只读代码事实（record_usage / _write_transaction_balance_only / get_or_create_account / models / SQLAlchemy 版本）> 审计报告 > 推测

---

## 0. Verdict 速览

| 维度 | 结论 |
|---|---|
| FC-F1 根因 | `get_or_create_account` 普通 SELECT 加载 ComputeAccount 到 identity map → `_write_transaction_balance_only` `with_for_update()` 不重新 hydrate → `locked.balance_tokens` 旧值 → 旧值+delta 覆盖 |
| Preferred Strategy | **Candidate B — Atomic UPDATE...RETURNING（B-Order-1，txn-flush-first）** |
| same-key regression | 无（保留 flush-first unique gate，loser 在 flush 处 IntegrityError，不触 balance mutation）|
| distinct-key lost update | 消除（DB 原子 `balance = balance + delta`，无 ORM read-modify-write）|
| balance_after_tokens | RETURNING 返回真实 new_balance，填入 txn |
| 余额不足语义 | **保持当前 contract（允许负余额，warning）**——B2 的 `WHERE balance+delta>=0` 拒绝是**新业务语义**，本设计标记为 OUT_OF_P1，默认不引入 |
| migration | **不需要** |
| isolation | **READ COMMITTED 不变** |
| SQLite | `with_for_update` 已是 no-op；UPDATE...RETURNING SQLite 3.35+ 支持；需 dialect 分支评估 |
| 本窗口实施 | **NO** |

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

---

## 1. Governance Baseline

```text
Git baseline = ef0897e
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
FC-F1 CONCURRENT_DISTINCT_IDENTITY_BALANCE_LOST_UPDATE = OPEN / P1 BLOCKER
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION

保持（不重新打开）：
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = RESOLVED
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_TRANSACTION_INSERT = VERIFIED
CONCURRENT_DISTINCT_IDENTITY_BALANCE_CLOSURE = FAILED
```

---

## 2. FC-F1 Frozen Finding

审批 `APPROVED_FAILED_FINDING`，根因 `VERIFIED / CODE + DIAGNOSTIC_VERIFIED`：

```text
record_usage 幂等路径（apps/compute/services.py:679-727）：
  get_or_create_account() → 普通 SELECT loads ComputeAccount into Session identity map
  _write_transaction_balance_only() → SELECT FOR UPDATE
    → database row lock succeeds
    → but ORM returns already-loaded ComputeAccount instance
    → balance_tokens remains stale
    → stale read-modify-write overwrites another committed balance
    → concurrent distinct identities lose balance updates
```

FC-3 稳定复现：8 worker distinct key 各 1 txn（txn 层正确），但 balance 只扣 -200（应 -800）→ lost update 600。2-worker 不暴露（时序窗口小）。

---

## 3. Current Transaction Flow（独立重建，§3）

本窗口从当前代码独立重建（非复制审计摘要）：

```text
record_usage（apps/compute/services.py:615-800）幂等路径（idempotency_key 非空，:681-769）：

  [validate] merchant_id / capability / model / source / stage / tokens（:641-660）
  [load ratio] db.query(ComputeMarkupRatio)（:664-668）→ billed_tokens（:677）
  [build evidence] _compute_payload_evidence（:683-689）

  step 1 — INSERT txn candidate（:692-716）
    tx_candidate = ComputeTransaction(delta=-billed, balance_after=0 占位, idempotency_key, ...)
    db.add(tx_candidate)                          (:714)
    db.flush()                                    (:716)  ← INSERT 到事务内（未 commit）
      ★ flush 成功 → 获得 ownership（unique 未冲突）
      ★ 同一 DB transaction 内后续操作

  step 2 — get_or_create_account（:718，autocommit=False）
    → get_or_create_account(db, merchant_id, autocommit=False)
      → db.query(ComputeAccount).filter(merchant_id).first()  (services.py:120-124)  ★ 普通 SELECT，无 FOR UPDATE
      → account 对象进入 SQLAlchemy Session identity map
      → account.balance_tokens = 此时刻 DB 值（可能 stale，若其他 worker 已 commit 新值但本 session 未刷新）
      （若 account 不存在：begin_nested SAVEPOINT + INSERT + IntegrityError 恢复，:127-143）

  step 3 — _write_transaction_balance_only（:719-722，services.py:150-184）
    locked = db.query(ComputeAccount).filter(merchant_id).with_for_update().first()  (:162-167)
      ★ SELECT ... FOR UPDATE SQL 发出，获取行锁（串行化）
      ★ 但 SQLAlchemy identity map 默认 populate_existing=False
      → locked 指向 identity map 里 step 2 已加载的同一对象
      → locked.balance_tokens = step 2 时刻的旧值（FOR UPDATE 结果不重新 hydrate 属性）
    new_balance = locked.balance_tokens + delta_tokens  (:170)  ★ 旧值 + delta
    if new_balance < 0: warning（不阻断，:173-181）  ← 当前允许负余额
    locked.balance_tokens = new_balance  (:182)  ★ ORM 标记 dirty
    locked.updated_at = _now()  (:183)
    db.flush()  (:184)  ★ UPDATE balance_tokens=旧值+delta（覆盖其他 worker 的 commit）

  step 4 — balance_after_tokens（:724）
    tx_candidate.balance_after_tokens = account.balance_tokens  ★ 用 account（=locked，identity map 同一对象）的 new_balance
    → account.balance_tokens 此时是 step 3 写入的 new_balance（旧值+delta）

  step 5 — commit（:725）
    db.commit()  ★ 单次 commit：txn INSERT + balance UPDATE 原子
    db.refresh(account)  (:726)
    return {"account": account, "idempotency_status": "created"}  (:727)

  step 6 — IntegrityError（:728-769）
    except IntegrityError:
      db.rollback()  (:731)  ★ 全事务回滚（txn + balance 均未 commit，无半成品）
      existing = db.query(ComputeTransaction).filter(merchant_id, idempotency_key).first()  (:733-740)
      if existing.payload_evidence == payload_evidence:  (:747)
        idempotent_replay → get_or_create_account + commit + return replay  (:749-756)
      else:
        idempotency_conflict → return conflict  (:758-769)
```

### SQL 时序标记

| step | SQL | 同事务 | flush | lock | 读 balance | 写 balance_after |
|---|---|---|---|---|---|---|
| 1 | INSERT compute_transactions | ✓ | ✓(flush) | — | — | —（占位 0）|
| 2 | SELECT compute_accounts | ✓ | — | —（普通 SELECT）| ✓（stale 入 identity map）| — |
| 3 | SELECT FOR UPDATE compute_accounts | ✓ | — | ✓（行锁）| ✗（identity map 不刷新）| — |
| 3 | UPDATE compute_accounts SET balance | ✓ | ✓(flush) | — | — | — |
| 4 | （内存）tx.balance_after = account.balance | ✓ | — | — | — | ✓（用 step3 new_balance）|
| 5 | COMMIT | ✓ | — | 释放 | — | — |

### 根因定位（精确）

**step 3 的 `with_for_update()` 获取了 DB 行锁（串行化），但 `locked.balance_tokens` 读的是 identity map 里 step 2 加载的旧值**。FOR UPDATE 的 SELECT 结果被 SQLAlchemy 默认丢弃（不重新 hydrate 已 identity-map 对象的属性）。故 `new_balance = 旧值 + delta`，commit 后覆盖其他 worker 的更新。

---

## 4. No-Regression Contract（§4，冻结现有正确行为）

| ID | 场景 | 期望 | 当前状态 |
|---|---|---|---|
| R1 | same identity sequential replay | 1 txn / no second delta | ✅ VERIFIED（FC-6）|
| R2 | same identity concurrent race（N workers）| 1 txn / 1 delta / losers replay | ✅ VERIFIED（FC-1/FC-2）|
| R3 | different merchants same key | M1+K / M2+K 独立 | ✅ VERIFIED（FC-4）|
| R4 | distinct identities same merchant | 全部合法事件计费 / final balance exact | ❌ FAILED（FC-3）← FC-F1 修复目标 |
| R5 | positive/negative delta 语义 | recharge 正 / consume 负 不破坏 | 当前正常（需修复不回归）|

修复 R4 不得回归 R1/R2/R3/R5。

---

## 5. Balance Insufficiency Semantics（§5/§20/§21）

### 5.1 当前 contract（代码事实）

**当前允许负余额**：
- `balance_tokens = Column(Integer, nullable=False, default=0)`（models.py:922）无 CHECK 约束禁止负数。
- `_write_transaction_balance_only:173` `if new_balance < 0:` 仅 `warning`，**不阻断**。
- `_write_transaction:228` 同。
- docstring（services.py:214）："负余额写结构化 warning（不阻断，作为持久化风险证据，§0.2）"。

### 5.2 §5 场景在当前 contract 下的实际行为

```text
B0 = 100, A=-80, B=-80 并发：
  当前（允许负）：两笔都成功，final = -60（或 lost update 后 = 20 但 2 txn）
  §5 要求（拒绝）：一笔成功一笔 insufficient，final = 20，1 txn
```

§5 的"余额不足拒绝"是**新业务语义**（当前不拒绝）。本设计**不擅自引入**该语义变更。

### 5.3 设计决策

```text
INSUFFICIENT_BALANCE_REJECTION = OUT_OF_P1（新业务语义，需独立审批）
```

Preferred Strategy（Candidate B）**默认不**加 `WHERE balance_tokens + delta >= 0`。仅修复 lost update（R4），不改变负余额 contract。若未来需余额不足拒绝，独立审批后再加 WHERE 子句（设计预留升级路径，§6.2）。

### 5.4 transaction types（§5/R5）

代码事实（services.py:27）：`TRANSACTION_TYPES = ("recharge", "grant_package", "consume")`。
- recharge：正 delta（充值）
- grant_package：正 delta（套餐发放）
- consume：负 delta（AI 消耗）

record_usage 幂等路径只产生 consume（:694 `transaction_type=CONSUME_TYPE`）。recharge/grant 走 `_write_transaction`（非幂等路径，admin 低频）。

---

## 6. Candidate A — Lock + Fresh ORM State（§6）

```text
_write_transaction_balance_only 的 FOR UPDATE 查询加 .execution_options(populate_existing=True)
或在 FOR UPDATE 前 db.expire(account) 使其过期
或合并 get_or_create_account + FOR UPDATE 为单步
```

### 6.1 优势

- 最接近现有结构，diff 最小（`_write_transaction_balance_only` 改 ~1-3 行）。
- 保留 ORM read-modify-write 流程。
- 无 SQL 语义变化。
- 保留 SQLite 兼容（`with_for_update` SQLite no-op，`populate_existing` 跨方言）。

### 6.2 风险

- **依赖 SQLAlchemy identity-map 隐含语义**：`populate_existing=True` 强制刷新，但 future refactor 若再次先读 account（如 step 2 get_or_create_account）仍可能回归。这是"正确性依赖开发者记住加 flag"的脆弱模式。
- **step 2 get_or_create_account 仍加载 stale account**：即使 step 3 `populate_existing` 刷新，step 2 的普通 SELECT 仍是无锁读，account 对象进 identity map。若有人后续在 step 3 前读 `account.balance_tokens`（如加日志/校验），仍是 stale。
- **refresh 时点必须严格正确**：`populate_existing` 必须在 FOR UPDATE 查询上，不能早不能晚。
- **balance 不足并发**：当前允许负，故无 "0 rows" 问题；但若未来加 `WHERE balance+delta>=0`，`populate_existing` + FOR UPDATE 仍是 read-modify-write，不原子（check 与 update 分两步）。
- **same-key IntegrityError replay interaction**：step 2/3 在 flush 之后，loser 在 flush 处 rollback，不触 step 2/3——A 不影响 same-key。
- **`_write_transaction`（旧路径/recharge）同样有 lost update**：A 若只改 `_write_transaction_balance_only`，recharge/grant 仍脆弱。但 FC-F1 scope 限定 record_usage 幂等路径（§44），recharge 低频 admin。

### 6.3 裁定

A 可行但**脆弱**——正确性依赖 ORM identity-map 细节 + 开发者纪律。§6 警告"不得因为改一行自动选 A"。A 是最小 diff，但非最健壮。

---

## 7. Candidate B — Atomic UPDATE ... RETURNING（§7/§8/§9）

### 7.1 核心 SQL

```sql
UPDATE compute_accounts
SET balance_tokens = balance_tokens + :delta,
    updated_at = :now
WHERE merchant_id = :merchant_id
RETURNING balance_tokens
```

返回 new_balance（DB 原子计算后），填入 `tx_candidate.balance_after_tokens`。

### 7.2 B-Order 选择（§9，核心）

#### B-Order-1（PREFERRED）：txn-flush-first（保留当前顺序）

```text
step 1: db.add(tx_candidate) + db.flush()         ← INSERT txn（unique gate）
step 2: ensure account exists（get_or_create_account，existence-only，不依赖 balance）
step 3: atomic UPDATE compute_accounts SET balance=balance+delta RETURNING balance
step 4: tx_candidate.balance_after_tokens = returned new_balance
step 5: db.commit()
step 6: IntegrityError → rollback → replay（同当前）
```

**same-key race（B6）分析**：
- same-key winner：step 1 flush 成功 → step 3 UPDATE → commit。
- same-key loser：step 1 flush → **UNIQUE 冲突 IntegrityError**（在 step 3 之前）→ rollback → 不执行 step 3 balance mutation → replay。
- **loser 不会先扣余额**：balance mutation（step 3）严格在 unique gate（step 1）之后。loser 在 step 1 即被拦截。

→ B-Order-1 保留 same-key exactly-once 机制。**PREFERRED**。

#### B-Order-2（REJECTED）：balance-update-first

```text
step 1: atomic UPDATE balance RETURNING
step 2: INSERT txn
```

**风险**：same-key loser 先扣余额（step 1 成功），再 INSERT txn（step 2 UNIQUE 冲突）→ rollback 恢复余额。虽然 rollback 可恢复，但：
- 若 rollback 失败 / 进程崩溃 → 余额已扣但无 txn（Bad B）。
- 并发窗口内余额短暂错误。
- 证明复杂度高。

→ **REJECTED**（§9 警告"不得凭直觉"，B-Order-2 需严谨证明而 B-Order-1 无此风险）。

### 7.3 B 必答问题（§8）

#### B1 Lost Update

```text
PostgreSQL UPDATE 是行级原子操作。
concurrent distinct delta → 行锁串行化 UPDATE → 无 lost update。
DB 自身保证 balance = balance + delta 的原子 read-modify-write。
```
✅ 天然消除 lost update。

#### B2 Insufficient Balance

§5 决定：**默认不引入余额不足拒绝**（OUT_OF_P1，保持当前允许负余额）。
- 当前 B：`UPDATE SET balance=balance+delta WHERE merchant_id=:m RETURNING balance`（无 balance 约束）。
- 升级路径（OUT_OF_P1）：`UPDATE SET balance=balance+delta WHERE merchant_id=:m AND balance_tokens+:delta >= 0 RETURNING balance` → 0 rows = insufficient。
- 本设计不实施升级路径，但在报告中标记。

#### B3 Positive Delta

```text
recharge/grant（正 delta）：balance = balance + delta 同样正确。
但 recharge 走 _write_transaction（非幂等路径），非 Candidate B scope。
若未来统一，B 对正 delta 同样正确。
```
✅。

#### B4 balance_after_tokens

```text
UPDATE ... RETURNING balance_tokens → DB 返回该 UPDATE 实际写入的新 balance。
该值即为该 worker 在串行化顺序下完成后的真实余额。
填入 tx_candidate.balance_after_tokens → commit。
```
✅ RETURNING 保证 balance_after_tokens = 实际 UPDATE 结果。

#### B5 Transaction Atomicity

```text
step 1（INSERT txn flush）+ step 3（UPDATE account）+ step 5（commit）同一 DB transaction。
若 step 3 UPDATE 失败 → 整事务 rollback → txn 也回滚（Bad A 不发生）。
若 step 1 flush 失败（UNIQUE）→ IntegrityError → rollback → balance 未触（Bad B 不发生）。
commit 原子：txn + balance 同 commit 或同 rollback。
```
✅。

#### B6 Same-Key Race

B-Order-1 下：
```text
same-key loser: step 1 flush → UNIQUE 冲突 → IntegrityError → rollback → replay
  → 不执行 step 3 UPDATE → balance 未变
same-key winner: step 1 flush 成功 → step 3 UPDATE → commit
  → balance 扣一次
```
✅ loser 不会先扣余额。

### 7.4 Candidate B 风险

- **identity map stale（§35）**：即使 atomic UPDATE，Session 内仍持有 step 2 加载的 ComputeAccount 对象（若 get_or_create_account 加载了它）。后续代码若读 `account.balance_tokens` 仍 stale。**解决**：step 3 不再依赖 `account.balance_tokens`，直接用 RETURNING 值；step 2 get_or_create_account 降级为 existence-only（或 `db.expire(account)` 后不读 balance）。
- **SQLAlchemy 2.0 UPDATE RETURNING API**：需选 Core `update().returning()` 还是 ORM-enabled update（§34）。
- **SQLite RETURNING**：SQLite 3.35+ 支持 UPDATE RETURNING（§33），但 SQLite `with_for_update` 已 no-op，并发语义本就不同。

### 7.5 裁定

B-Order-1 **PREFERRED**：消除 lost update（DB 原子）、保留 same-key exactly-once（flush-first unique gate）、balance_after_tokens 正确（RETURNING）、无 migration、无 isolation 变化。比 A 更健壮（不依赖 ORM identity-map 纪律）。

---

## 8. Candidate C — Lock Account Before Any Balance Read（§10）

```text
step 1: idempotency precheck（INSERT txn flush，unique gate）
step 2: SELECT account FOR UPDATE（fresh balance，populate_existing）
step 3: validate balance
step 4: transaction insert（已在 step 1）
step 5: account update（balance = locked.balance + delta）
step 6: commit
```

### 8.1 与 A 的区别

- A = 保留现有流程（get_or_create_account 普通 SELECT + FOR UPDATE + populate_existing）。
- C = **重排**：让 FOR UPDATE 成为余额读取的**唯一入口**，无前置普通 SELECT。

### 8.2 评估

- ✅ 彻底消除 stale read（无前置普通 SELECT 加载 balance）。
- ✅ get_or_create_account 降级为 existence-only（不读 balance）或合并入 FOR UPDATE。
- ❌ **lock duration 比 B 长**：FOR UPDATE 持锁从 step 2 到 step 6 commit，覆盖 txn insert + balance compute + commit。B 的 atomic UPDATE 持锁仅覆盖 UPDATE 本身（更短）。
- ❌ same-key competitors 全部先竞争 account lock（而非 txn unique index）——改变竞争面，可能影响 same-key replay 性能。
- ❌ 仍是 ORM read-modify-write，未来加 `WHERE balance+delta>=0` 不原子。
- deadlock 风险：若 C 持 account lock 跨 txn insert，与反向锁序 worker 可能死锁（§17）。

### 8.3 裁定

C 比 A 强（消除前置 stale read），但比 B 弱（lock duration 长 + 仍 read-modify-write + 余额不足不原子）。**REJECTED**（B 优于 C）。

---

## 9. Candidate D — Optimistic Versioning / CAS（§11）

```text
加 version column
UPDATE ... WHERE merchant_id=:m AND version=:old_version
retry on conflict（rowcount=0）
```

### 9.1 评估

- ❌ **migration required**（加 version column）——违反 §30 默认 NO MIGRATION。
- ❌ retry loop 复杂度。
- ❌ same-key interaction：loser 在 unique flush 拦截，不触 version retry——但 distinct-key 并发 retry 可能 starvation。
- ❌ 所有 balance mutation path（_write_transaction_balance_only + _write_transaction + recharge + grant）都需改。
- ❌ 更重 than B。

### 9.2 裁定

**REJECTED**（migration + 复杂度 + 影响面大，B 无 migration 更优）。

---

## 10. Candidate E — SERIALIZABLE（§12）

```text
transaction isolation = SERIALIZABLE
```

### 10.1 评估

- ❌ serialization failures → 应用层 retry 必需（复杂度）。
- ❌ 吞吐下降。
- ❌ **所有 9000 DB workload 影响**（不只 compute）——blast radius 大。
- ❌ connection/session 配置变更。
- §12 警告：不得作为"最省代码"的逃避方案。

### 10.2 裁定

**REJECTED**（blast radius + 复杂度，B 在 READ COMMITTED 下正确）。

---

## 11. Candidate Matrix（§27）

| Candidate | Correctness | Lost Update | Insufficient Race | Same-Key Regression Risk | Deadlock Risk | Migration | Isolation Change | Complexity | Performance | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| A Lock + populate_existing | ✅ | ✅ 消除 | ✗ 不原子 | 低（flush-first 保留）| 低 | 无 | 无 | 低 | 中（FOR UPDATE 持锁到 commit）| 可行但脆弱 |
| **B Atomic UPDATE RETURNING** | ✅ | ✅ 消除 | ✗（默认不拒绝，OUT_OF_P1）| 低（flush-first 保留）| 低 | **无** | **无** | 低-中 | **高**（持锁仅 UPDATE）| **PREFERRED** |
| C Lock-before-read reorder | ✅ | ✅ 消除 | ✗ 不原子 | 中（改竞争面）| 中（持锁跨 insert）| 无 | 无 | 中 | 低（lock 长）| REJECTED |
| D Optimistic version | ✅ | ✅ 消除 | ✅ 原子 CAS | 中（retry）| 低 | **需** | 无 | 高 | 中（retry）| REJECTED（migration）|
| E SERIALIZABLE | ✅ | ✅ 消除 | ✅ | 中（retry）| 中 | 无 | **需** | 高 | 低（全局）| REJECTED（blast radius）|

---

## 12. Preferred Strategy

```text
PREFERRED = Candidate B — Atomic UPDATE ... RETURNING（B-Order-1，txn-flush-first）

step 1: db.add(tx_candidate) + db.flush()        ← INSERT txn（unique gate，保留 same-key exactly-once）
step 2: ensure account exists（get_or_create_account，existence-only，不依赖返回的 balance）
step 3: UPDATE compute_accounts
          SET balance_tokens = balance_tokens + :delta, updated_at = :now
          WHERE merchant_id = :merchant_id
          RETURNING balance_tokens                ← DB 原子，消除 lost update
step 4: tx_candidate.balance_after_tokens = RETURNED new_balance
step 5: db.commit()                               ← txn + balance 原子
step 6: IntegrityError → rollback → replay（同当前）
```

### 为什么满足全部 contract

1. **same identity exactly-once 不回归**：step 1 flush-first 保留 unique gate，loser 在 step 1 IntegrityError，不触 step 3。
2. **distinct identities 不 lost update**：step 3 atomic `balance = balance + delta`，DB 行锁串行化，无 ORM read-modify-write。
3. **balance check 与 deduction 原子**：当前无 balance check（允许负），故 N/A；未来加 `WHERE balance+delta>=0` 则 check+update 原子（升级路径）。
4. **transaction row 与 account balance 同事务**：step 1 + step 3 + step 5 同 DB transaction。
5. **balance_after_tokens 正确**：RETURNING 返回真实 new_balance。
6. **不依赖 SERIALIZABLE**：READ COMMITTED 下 atomic UPDATE 正确。
7. **无 migration**：复用现有 balance_tokens 列 + uk_compute_accounts_merchant。

---

## 13. SQL / ORM Semantics（§34/§13）

### 13.1 SQLAlchemy 版本

```text
SQLAlchemy 2.0.51（支持 update().returning()）
```

### 13.2 实现方式选择（§34）

候选：
- (a) SQLAlchemy Core `update(compute_accounts).where(...).values(balance=...).returning(balance_tokens)`
- (b) ORM-enabled `db.query(ComputeAccount).filter(...).update({balance: ...})`（不支持 RETURNING 填回 ORM 对象）
- (c) text SQL `UPDATE ... RETURNING`

**推荐 (a) Core `update().returning()`**：
- RETURNING 支持明确。
- 可直接 `db.session.execute(stmt)` 拿返回值。
- 不污染 identity map（不返回 ORM 对象，§35 风险低）。
- rowcount 语义清晰（1 = updated，0 = account 不存在，映射 COMPUTE_ACCOUNT_MISSING）。
- PostgreSQL 正确。

**不选 (b)**：ORM `.update()` 批量更新不返回 RETURNING 值给调用方，需二次查询。
**不选 (c)**：text SQL 绕过类型转换，不如 Core。

### 13.3 identity map 处理（§35）

- step 3 Core UPDATE 不返回 ORM 对象，不污染 identity map。
- 但 step 2 get_or_create_account 可能已加载 ComputeAccount 到 identity map（stale balance）。
- **后续代码不得再读 `account.balance_tokens`**——所有余额信息来自 step 3 RETURNING。
- 可选 `db.expire(account)` 使其过期（防止误读），但若代码不再读 account.balance 则非必需。
- `tx_candidate.balance_after_tokens` 直接用 RETURNING 值，不经 account 对象。

---

## 14. Transaction Ordering（§15）

### 14.1 当前 tx_candidate flush-first 保留

```text
db.add(tx_candidate) + db.flush()  ← 必须在 balance mutation 之前
```

保留——它是 same-key exactly-once 的 gate。

### 14.2 flush-first 的性质

```text
same identity concurrent loser → duplicate unique conflict → no second committed transaction
```

Candidate B 保留此性质（B-Order-1）。若调整顺序（B-Order-2）需重新证明 same-key——本设计选 B-Order-1，无需重新证明。

---

## 15. Same-Key Race（§16）

### 15.1 IntegrityError catch（services.py:728-769）

当前 catch 宽度：`except IntegrityError`（:728）。

**风险（§16）**：若 Candidate B 的 atomic UPDATE 因 balance 相关 SQL error 失败（如 CHECK 约束 / COMPUTE_BALANCE_OUT_OF_RANGE ValueError），是否被误识别为 idempotency replay？

分析：
- `IntegrityError` 是 SQLAlchemy 对 PostgreSQL 唯一约束/外键/CHECK 约束异常的封装。
- step 3 atomic UPDATE 若触发 CHECK 约束（当前 compute_accounts 无 CHECK），会抛 IntegrityError。
- 但 step 3 在 step 1 flush **之后**——若 step 3 抛 IntegrityError，当前 catch 会 rollback + 查 existing txn → 可能误判为 replay。

**设计要求（§16）**：新方案不得把 balance-related SQL error 错误识别为 idempotency replay。

**解决**：
- step 3 的 `COMPUTE_BALANCE_OUT_OF_RANGE`（:171）当前是 `ValueError`（非 IntegrityError），不会被 `except IntegrityError` 捕获——保持。
- step 3 atomic UPDATE 若返回 0 rows（account 不存在）→ 映射 `COMPUTE_ACCOUNT_MISSING` ValueError（非 IntegrityError）。
- **IntegrityError catch 范围不变**：仅 step 1 flush 的 UNIQUE 冲突触发。step 3 在 flush 之后，其异常类型应保持 ValueError（业务错误）而非 IntegrityError（除非 DB CHECK 约束，当前无）。
- 若未来加 `WHERE balance+delta>=0`，0 rows 应映射为 `INSUFFICIENT_BALANCE` ValueError，不进 IntegrityError catch。

### 15.2 replay 逻辑保留

```text
IntegrityError → rollback → load existing txn → payload_evidence match → replay / conflict
```

不变（Candidate B 不改 step 6）。

---

## 16. Distinct-Key Race（§17/§22）

B-Order-1 下 distinct-key：
```text
8 workers, 8 distinct keys, same merchant:
  each worker: step 1 flush（distinct key，无 UNIQUE 冲突）→ step 3 atomic UPDATE
  step 3: DB 行锁串行化（同一 account row）→ balance = balance + delta 依次累加
  → 8 txn（各 key 1）+ balance 扣 800（8×100）
  → final balance = initial - 800 ✓
```

无 lost update（atomic UPDATE），无 double charge（distinct key 各 1 txn）。

---

## 17. Insufficient Balance Race（§25）

### 17.1 当前 contract（允许负）

```text
B0=100, A=-80, B=-80 concurrent:
  当前（Candidate B 默认无 WHERE 约束）：两笔都成功，final = 100-80-80 = -60
  2 txn（各 1 key），balance_after_tokens 正确串行化
```

§5 的"一笔成功一笔 insufficient"是**新业务语义**（OUT_OF_P1，§5.3）。Candidate B 默认不引入。

### 17.2 升级路径（OUT_OF_P1）

若未来需 insufficient rejection：
```sql
UPDATE compute_accounts
SET balance_tokens = balance_tokens + :delta
WHERE merchant_id = :merchant_id AND balance_tokens + :delta >= 0
RETURNING balance_tokens
```
- 0 rows → insufficient balance → rollback txn（不 commit tx_candidate）→ 返回 insufficient。
- 本设计**不实施**，但报告预留。

### 17.3 FC-R1 验证（§25/§42）

实施后验证：
```text
B0=100, K-A delta=-80, K-B delta=-80 concurrent:
  默认 contract：success=2, final=-60, txn=2（允许负）
  若未来引入 rejection：success=1, insufficient=1, final=20, txn=1
```

设计阶段标记，实施窗口按当前 contract（允许负）验证。若审批决定引入 rejection，按升级路径验证 §5 结果。

---

## 18. Account Creation（§14/§38/§39）

### 18.1 get_or_create_account 当前并发行为

services.py:110-147：
- 普通 SELECT（:120-124），无 FOR UPDATE。
- 若 None：`begin_nested`（SAVEPOINT）+ INSERT + `IntegrityError` 恢复（:127-143）→ 并发首次创建安全。
- `uk_compute_accounts_merchant` UNIQUE 约束（models.py:916）保证一商户一行。

### 18.2 account 不存在 + 两 distinct event 并发

```text
merchant 无 account, 2 distinct events concurrent:
  both: get_or_create_account → SELECT None → begin_nested INSERT
  winner: SAVEPOINT INSERT 成功
  loser: SAVEPOINT INSERT → UNIQUE 冲突 → rollback SAVEPOINT → 复用（re-SELECT）
```
当前正确处理。Candidate B 不影响此流程。

### 18.3 Candidate B 下 get_or_create_account 的职责

**存在性职责与余额串行化职责分开**（§39）：
- get_or_create_account = **existence-only**（确保 account 行存在）。
- step 3 atomic UPDATE = **balance serialization**（不依赖 get_or_create_account 返回的 balance）。
- get_or_create_account 返回的 account 对象**不参与余额计算**——其 balance_tokens 可能 stale，但 step 3 不读它。

### 18.4 仍需提前调用

```text
ensure account exists（get_or_create_account）→ 必须在 step 3 atomic UPDATE 之前
  否则 step 3 UPDATE 0 rows（account 不存在）→ COMPUTE_ACCOUNT_MISSING
```

保留 get_or_create_account 调用，但**不再依赖其 balance**（§38）。

---

## 19. Transaction Atomicity（§19）

### 19.1 同事务保证

```text
step 1 INSERT txn flush + step 3 UPDATE account + step 5 commit → 同一 DB transaction
commit 原子：txn + balance 同 commit 或同 rollback
```

### 19.2 Bad A / Bad B 不发生

- **Bad A（txn exists, balance unchanged）**：step 1 flush + step 3 UPDATE 同事务，若 step 3 失败 → rollback → txn 也回滚。不发生。
- **Bad B（balance changed, txn missing）**：step 3 在 step 1 之后，若 step 1 失败（UNIQUE）→ 不执行 step 3。若 step 3 成功 step 1 已 flush → commit 同提交。不发生。

---

## 20. balance_after_tokens（§18）

### 20.1 contract

```text
每个成功 txn 的 balance_after_tokens = 该 txn 在其串行化顺序下完成后账户余额。
```

### 20.2 Candidate B 实现

```text
step 3: UPDATE ... RETURNING balance_tokens → new_balance
step 4: tx_candidate.balance_after_tokens = new_balance
```

RETURNING 返回的是该 UPDATE 实际写入的值 = 该 worker 串行化后的真实余额。✅

### 20.3 并发下不要求 txn id 顺序 = balance 顺序

只要求存在合法 serialized ordering。Candidate B 的 atomic UPDATE 天然满足（DB 行锁决定串行顺序，RETURNING 反映该顺序结果）。

### 20.4 final balance closure

```text
final = initial + sum(committed deltas)
```

Candidate B：每个 delta 经 atomic UPDATE 累加，final = initial + sum(deltas)。✅（FC-9 修复）。

---

## 21. Deadlock / Lock Ordering（§17）

### 21.1 核心资源

- `compute_transactions` unique index（uk_compute_transactions_merchant_idempotency）
- `compute_accounts` merchant row（uk_compute_accounts_merchant）

### 21.2 锁顺序分析

B-Order-1 下：
```text
所有 worker:
  step 1: INSERT compute_transactions（unique index 冲突检测）
  step 3: UPDATE compute_accounts（account 行锁）
锁顺序 = txn unique index → account row lock（单一方向）
```

- **same-key workers**：winner step 1 成功 → step 3 account lock；loser step 1 UNIQUE 冲突 → rollback，不触 account lock。无反向锁序。
- **distinct-key same merchant workers**：各 step 1 成功（不同 key）→ step 3 竞争同一 account row lock，串行化。无反向锁序。
- **different merchant**：不同 account row，无竞争。
- **deadlock 风险**：无（单一锁序 txn→account）。

### 21.3 反向锁序不存在

B-Order-1 不会出现 "account lock → txn unique" 反向（account lock 在 txn flush 之后）。✅

---

## 22. IntegrityError / Replay（§16 详）

### 22.1 catch 逻辑保留

```python
except IntegrityError:  # :728
    db.rollback()
    existing = db.query(ComputeTransaction).filter(merchant_id, idempotency_key).first()
    if existing.payload_evidence == payload_evidence:
        idempotent_replay
    else:
        idempotency_conflict
```

### 22.2 不误识别 balance error

- step 3 `COMPUTE_BALANCE_OUT_OF_RANGE`（:171）= ValueError → 不被 `except IntegrityError` 捕获。
- step 3 UPDATE 0 rows（account missing）= 映射 ValueError `COMPUTE_ACCOUNT_MISSING` → 不被捕获。
- IntegrityError catch 仅覆盖 step 1 flush 的 UNIQUE 冲突。

### 22.3 rollback / retry 语义（§40）

| 场景 | 行为 |
|---|---|
| Duplicate key（same-key loser）| IntegrityError → rollback → load existing → replay |
| Insufficient balance（未来）| 0 rows → rollback txn → business error（当前 OUT_OF_P1）|
| DB failure | 整事务 rollback（txn + balance）|
| Deadlock / serialization error | 当前无（B-Order-1 单一锁序）；PostgreSQL deadlock 抛 DBAPIError，需评估是否加 retry（当前 record_usage 无 retry loop，保持）|

---

## 23. PostgreSQL READ COMMITTED（§24/§31）

```text
isolation = READ COMMITTED（PG 默认，冻结）
```

Candidate B 在 READ COMMITTED 下正确：
- atomic UPDATE 是单语句，行级原子，不依赖 isolation level。
- SELECT FOR UPDATE 的"读到 committed 值"语义在 READ COMMITTED 下成立。
- 不需 SERIALIZABLE。

---

## 24. SQLite Compatibility（§33）

### 24.1 SQLite 是否仍支持

代码事实（services.py:213 注释）："PostgreSQL 防并发丢失更新；SQLite 为 no-op，靠本地写事务隔离"。

当前 compute service 同时支持 PG（生产）+ SQLite（dev/test）。`with_for_update()` 在 SQLite 是 no-op。

### 24.2 UPDATE ... RETURNING SQLite 支持

- SQLite 3.35+（2021-03）支持 UPDATE RETURNING。
- Python 内置 sqlite3 通常 ≥ 3.35（需确认运行时版本）。

### 24.3 设计决策

```text
PostgreSQL authoritative implementation + SQLite compatible
```

Candidate B 的 `UPDATE ... RETURNING` 在 SQLite 3.35+ 可用。但 SQLite 无并发（单写者），故 lost update 在 SQLite 本就不暴露（靠写事务隔离）。

**dialect 分支评估**：
- 若 SQLAlchemy Core `update().returning()` 跨方言透明 → 无需分支。
- 若 SQLite 版本 < 3.35 → 需 fallback（UPDATE + 二次 SELECT，非原子但 SQLite 无并发）。
- **本设计建议**：用 Core `update().returning()`（跨方言），若 SQLite 运行时 < 3.35 则测试标记 skip 或 fallback。实施窗口验证 SQLite 版本。

### 24.4 不突然破坏 SQLite

本设计不破坏 SQLite 路径（Core update().returning 跨方言）。若需 dialect 分支，纳入 scope 评审（§44）。

---

## 25. Migration Decision（§30）

```text
MIGRATION = NO
```

- `balance_tokens` 列已存在（models.py:922）。
- `uk_compute_accounts_merchant` UNIQUE 已存在（:916）。
- Candidate B 不需 version column（D 才需要）。
- 不需新约束（余额不足 rejection 是 OUT_OF_P1）。

---

## 26. Application Role（§32）

```text
新 SQL 由 auto_wechat application principal 执行
```

- `UPDATE compute_accounts SET balance_tokens = ...` 是 DML，app role 有 DML 权限（60 业务表 DML，PR-3 VERIFIED）。
- 不需 superuser / table ownership / DDL / elevated lock privilege。
- Fresh Bootstrap permission contract 不变。

---

## 27. Focused Tests（§41）

| T | 验证 | Gate |
|---|---|---|
| T1 | single charge behavior unchanged | 基线 |
| T2 | sequential replay unchanged（same key）| R1 |
| T3 | same-key concurrent exactly-once（N≥8）| R2 / FC-1/FC-2 |
| T4 | distinct-key concurrent exact balance（N≥8, ≥5 rounds）| R4 / FC-3 |
| T5 | insufficient-balance concurrent race（B0=100, 两 -80）| §5/§17（按当前 contract 验证）|
| T6 | merchant isolation（同 key 不同 merchant）| R3 / FC-4 |
| T7 | transaction + account rollback atomicity（step 3 失败 → txn 回滚）| §19 |
| T8 | balance_after_tokens correctness（RETURNING = 串行化真实值）| §18/§20 |
| T9 | positive delta（recharge 路径，若 Candidate B 扩展到 _write_transaction）| R5/§26 |
| T10 | SQLite compatibility（Core update().returning 跨方言）| §24 |

---

## 28. Runtime Re-Verification（§42）

修复实施审批通过后，**完整重跑** Final PostgreSQL Concurrent Closure（非只 FC-3）：

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
FC-R1 concurrent insufficient balance（按当前 contract：允许负 → 两笔都成功 final=-60；若引入 rejection → 1 success 1 insufficient final=20）
FC-R2 mixed same-key + distinct-key workload（§24，由设计裁定为补强 Gate）
```

---

## 29. Success Criteria After Remediation（§43）

```text
same identity concurrency → exactly one txn → exactly one delta
distinct identity concurrency → one txn per identity → all deltas preserved
insufficient balance concurrency → 按当前 contract（允许负，均 commit）；升级路径 OUT_OF_P1
transaction.balance_after_tokens → serialized-consistent（RETURNING）
final account balance = initial + sum(committed distinct transaction deltas)
no raw IntegrityError/500
no deadlock leak
no lost update
```

---

## 30. Implementation Scope（§44）

### MODIFY

| 文件 | 改动 |
|---|---|
| `apps/compute/services.py` | `record_usage` 幂等路径（:718-727）：step 2 get_or_create_account 降为 existence-only（不依赖 balance）；step 3 用 Core `update(ComputeAccount).where(merchant_id).values(balance=balance+delta, updated_at=now).returning(balance_tokens)` 执行 + 取 RETURNING；step 4 `tx_candidate.balance_after_tokens = returned`；保留 step 1 flush + step 6 IntegrityError catch。`_write_transaction_balance_only`（:150-184）若被 Candidate B 取代则重构或废弃（仅 record_usage 调用，§37）。 |

### CREATE/MODIFY

| 文件 | 内容 |
|---|---|
| focused compute concurrency tests | T1-T10（§27），含 FC-3 distinct-key 8-worker 5-round + FC-R1 insufficient + FC-R2 mixed |

### CREATE

| 文件 | 内容 |
|---|---|
| `P1_FC_F1_CONCURRENT_BALANCE_LOST_UPDATE_IMPLEMENTATION_REPORT.md` | 实施报告 |

### READ ONLY / DO NOT MODIFY

- compute core `record_usage` 签名 / 返回值（§36 API contract 保持）
- `_write_transaction`（旧路径/recharge/grant）——若 Candidate B 仅修 `_write_transaction_balance_only`，`_write_transaction` 不动（recharge 低频 admin，FC-F1 scope 限定 record_usage 幂等路径）
- migration / DB-BL
- 9100 / staging-prod
- F-2 / RB-10 / Global None / F-1

### scope 精度

核心改动集中在 `record_usage` 幂等路径的 step 2/3/4（~10-20 行）。若 `_write_transaction_balance_only` 被 Core update().returning 取代，则该函数重构或废弃（仅 1 caller：record_usage :719）。`_write_transaction`（recharge/grant/None-path）不在 FC-F1 scope，但其 lost-update 模式相同——登记为 future governance（§45 OUT_OF_P1 之外的非 P1 事项）。

---

## 31. Rollback（§46）

```text
CODE-ONLY ROLLBACK
```

- 无 migration → git revert `apps/compute/services.py` 改动即可。
- 无 schema 变更 → 无 data migration / backfill。
- 不触碰 canonical DB（验证在隔离 PG）。
- 不触碰 9100 / migration。

---

## 32. Risks / Tradeoffs（§47/§48）

### 32.1 性能（§47）

```text
same merchant high concurrency → 单 account row serialization point（不可避免，余额正确性代价）
```

Candidate B 的 lock duration = atomic UPDATE 持锁时长（短于 Candidate C 的"FOR UPDATE 到 commit"）。性能优于 A/C。

### 32.2 可观测性（§48）

- 复用现有日志（`compute_idempotency stage=...`）。
- 错误区分：insufficient balance（未来）/ duplicate replay / database failure。
- 不新建 telemetry 系统。
- 可选记录 `balance_before` / `balance_after`（RETURNING 已提供 after；before 可从 after-delta 推算）。

### 32.3 `_write_transaction_balance_only` 影响面（§37）

代码事实：`_write_transaction_balance_only`（:150）**仅** `record_usage` 幂等路径调用（:719）。无 recharge/grant/其他 caller。修改/重构它影响面 = record_usage 一处。scope 小。

### 32.4 `_write_transaction` 同样脆弱（非 scope）

`_write_transaction`（:187，recharge/grant/None-path）有相同 lost-update 模式。但：
- FC-F1 审批 scope = record_usage 幂等路径。
- recharge/grant 是 admin 低频操作，并发概率低。
- 登记为 future governance gap（非 P1 blocker）。

---

## 33. 14 Required Questions（§49）

**Q1. Preferred concurrency mechanism？**
Candidate B — PostgreSQL atomic `UPDATE compute_accounts SET balance_tokens = balance_tokens + :delta RETURNING balance_tokens`（B-Order-1，txn-flush-first）。

**Q2. 为什么不再受 SQLAlchemy stale identity-map 影响？**
Candidate B 不依赖 ORM read-modify-write。step 3 Core UPDATE 不返回 ORM 对象，不污染 identity map。`balance_after_tokens` 来自 RETURNING 值，不经 account 对象。step 2 get_or_create_account 降为 existence-only，其返回的 account.balance_tokens 不再被读。

**Q3. same-key concurrent replay 为什么不回归？**
B-Order-1 保留 step 1 `db.add(tx_candidate) + db.flush()`（unique gate）。same-key loser 在 step 1 即 UNIQUE 冲突 IntegrityError → rollback → 不执行 step 3 balance mutation → replay。flush-first 在 balance mutation 之前，loser 被拦截。

**Q4. distinct-key concurrent 为什么不 lost update？**
step 3 atomic `balance = balance + delta` 是 DB 单语句行级原子。concurrent distinct delta → 行锁串行化 → 依次累加。无 ORM read-modify-write，无 stale 覆盖。

**Q5. B0=100，两笔 -80 并发结果？**
当前 contract（允许负余额，§5.3）：两笔都成功，final = 100-80-80 = -60，2 txn，balance_after_tokens 正确串行化。§5 的"一笔 insufficient"是新业务语义（OUT_OF_P1，默认不引入；升级路径 `WHERE balance+delta>=0` 预留）。

**Q6. transaction row 与 account mutation 如何原子？**
step 1（INSERT txn flush）+ step 3（UPDATE account）+ step 5（commit）同一 DB transaction。commit 原子：同 commit 或同 rollback。Bad A/B 不发生（§19）。

**Q7. balance_after_tokens 如何得到正确值？**
step 3 `UPDATE ... RETURNING balance_tokens` 返回该 UPDATE 实际写入的新 balance = 该 worker 串行化后的真实余额。填入 `tx_candidate.balance_after_tokens`（step 4）。

**Q8. account 不存在时如何处理？**
step 2 get_or_create_account（existence-only，SAVEPOINT + IntegrityError 恢复）确保 account 行存在。若不存在则创建（balance=0）。step 3 atomic UPDATE 在 account 存在后执行。若 step 3 UPDATE 0 rows（理论不应，因 step 2 已 ensure）→ COMPUTE_ACCOUNT_MISSING ValueError。

**Q9. deadlock 风险与锁顺序？**
B-Order-1 单一锁序：txn unique index（step 1）→ account row lock（step 3）。无反向锁序。same-key loser 在 step 1 拦截不触 account lock。distinct-key 竞争同一 account row lock 串行化。无 deadlock（§21）。

**Q10. 是否需要 migration？**
不需要（§25）。balance_tokens 列 + uk_compute_accounts_merchant 已存在。Candidate B 不加 version column / 新约束。

**Q11. 是否改变 READ COMMITTED？**
不改变（§23）。Candidate B 在 READ COMMITTED 下正确（atomic UPDATE 不依赖 isolation level）。

**Q12. SQLite 是否受影响？**
SQLite `with_for_update` 已是 no-op；UPDATE RETURNING SQLite 3.35+ 支持。Candidate B 用 Core `update().returning()`（跨方言）。SQLite 无并发，lost update 本不暴露。若 SQLite < 3.35 需 fallback（实施窗口验证版本）。

**Q13. 预计改哪些文件？**
`apps/compute/services.py`（record_usage 幂等路径 step 2/3/4 + 可能重构 `_write_transaction_balance_only`）。+ focused tests + 实施报告。无 migration / 9100 / schema。

**Q14. 如何完整重跑 Final Concurrent Gate？**
修复实施审批通过后，完整重跑 FC-1~FC-12 + 新增 FC-R1（insufficient）+ FC-R2（mixed），非只 FC-3（§28）。验证 same-key（FC-1/2/6 no regression）+ distinct-key（FC-3/8/9 fixed）+ insufficient（FC-R1）+ mixed（FC-R2）。

---

## 34. Verdict

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

### 设计结论

1. **Preferred = Candidate B**（atomic UPDATE...RETURNING，B-Order-1 txn-flush-first）。
2. **消除 lost update**：DB 原子 read-modify-write，不依赖 ORM identity map。
3. **same-key no regression**：flush-first unique gate 保留，loser 在 step 1 拦截。
4. **balance_after_tokens 正确**：RETURNING 返回串行化真实值。
5. **无 migration / 无 isolation 变化 / READ COMMITTED**。
6. **余额不足**：保持当前 contract（允许负），rejection 是 OUT_OF_P1 升级路径。
7. **API contract 不变**：record_usage 返回值不变。
8. **scope 小**：仅 record_usage 幂等路径 step 2/3/4 + `_write_transaction_balance_only`（仅 1 caller）。
9. **完整重跑 Final Concurrent Gate** required（§28）。

### 不实施

```text
DO NOT COMMIT
DO NOT MODIFY apps/compute/services.py
DO NOT ADD populate_existing / session.refresh
DO NOT ADD atomic UPDATE
DO NOT CHANGE lock order
DO NOT ADD version column
DO NOT CHANGE isolation
DO NOT CREATE migration
DO NOT RE-RUN Final Concurrent Gate
```

设计 candidate 不提交（§52），交独立设计审批。

### P1 状态（继续冻结）

```text
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = FAILED
FC-F1 = OPEN / DESIGN_READY_FOR_APPROVAL
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_CONCURRENT_LOST_UPDATE_REMEDIATION
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED（保持）
F-1 = RESOLVED（保持）
```

### 下一步

```text
本设计交独立设计审批窗口。
审批通过后，由独立实施窗口：
  1. 修改 apps/compute/services.py record_usage 幂等路径（Candidate B-Order-1）
  2. 新增 focused tests（T1-T10 + FC-R1 + FC-R2）
  3. 隔离 PG E2E 验证
  4. 实施审批
  5. 完整重跑 Final Concurrent Closure（FC-1~FC-12 + FC-R1 + FC-R2）
不得借实施窗口处理 _write_transaction（recharge）/ migration / isolation / F-2 / RB-10 / Global None / F-1。
```

---

## 设计窗口停止点

```text
P1-FC-F1-CONCURRENT-BALANCE-LOST-UPDATE-DESIGN:
VERDICT = DESIGN_READY_FOR_APPROVAL
  Preferred = Candidate B（atomic UPDATE...RETURNING，B-Order-1 txn-flush-first）
  same-key no regression（flush-first 保留）
  distinct-key no lost update（DB 原子）
  balance_after_tokens = RETURNING 真实值
  无 migration / READ COMMITTED / 余额不足保持允许负（rejection OUT_OF_P1）
本窗口不实施，停止。
```

未自行：修改 `apps/compute/services.py` / 加 `populate_existing` / 加 `session.refresh` / 改 atomic UPDATE / 调整锁顺序 / 加 version column / 修改 isolation / 创建 migration / 重跑修复后 Final Concurrent Gate / RB-10 / 宣布 P1 CLOSED。
