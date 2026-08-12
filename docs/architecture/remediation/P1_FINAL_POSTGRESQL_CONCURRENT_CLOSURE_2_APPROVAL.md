# P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2 — 独立最终审批报告

> 审批窗口：`P1-FINAL-POSTGRESQL-CONCURRENT-CLOSURE-2`（独立最终审批，非执行窗口自述）
> 审查对象：`docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2.md`
> 前序：`FC-F1 = RESOLVED`（closure commit `eb9f182`）+ `GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED` + `F-1 = RESOLVED`
> 基线 commit：`eb9f182`
> 审批日期：2026-08-12
> 窗口性质：READ / VERIFY ONLY + 独立隔离 PG runtime（未改 compute core / migration / isolation / commit / push）
> 裁定：`APPROVED`

---

## 1. Technical Decision

```
VERDICT: APPROVED

COMPUTE-IDEMPOTENCY-001 = CLOSED
TECHNICAL_CLOSURE = VERIFIED
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = VERIFIED

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = INDEPENDENTLY_VERIFIED
DISTINCT_IDENTITY_CONCURRENT_BALANCE_CLOSURE = INDEPENDENTLY_VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = INDEPENDENTLY_VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = INDEPENDENTLY_VERIFIED
LEDGER_ACCOUNT_GLOBAL_CLOSURE = INDEPENDENTLY_VERIFIED
APPLICATION_ROLE_RUNTIME = INDEPENDENTLY_VERIFIED
CANONICAL_NO_DRIFT = VERIFIED
```

P1 Technical Closure 最终 Gate 独立成立。本审批建立全新隔离 PostgreSQL（au-final-iso@5437，owner=postgres，principal=auto_wechat，READ COMMITTED，alembic head=0034），独立复现 5 项最低 runtime 证明集（IA-FC-1~5），全部 PASS。原 FC-F1 lost update 故障（8 txn / -200 lost 600）在独立隔离 PG 上未再现——修复后 8 distinct key 全部计入 balance（-800）。

candidate FC-0~FC-12 + FC-R1/R2 报告 + 本审批独立 runtime 共同构成正式关闭 P1 的强证据。

---

## 2. Baseline

```
HEAD = eb9f182（修复：闭环算力余额并发丢失更新，FC-F1 closure commit）
business-code baseline = eb9f182
worktree candidate = 4 治理文档 modified（6 insertions 6 deletions）+ 1 报告 untracked
```

```
business-code baseline = eb9f182
BASELINE_DRIFT = NO
```

候选 diff 仅治理文档状态同步（AGENTS.md / CLAUDE.md / 05_PROJECT_CONTEXT.md / CROSS_MODULE_RISK_REGISTER.md），**无 apps/compute/services.py / models / schemas / migration / 9100 / consumer identity / transaction isolation 业务代码 diff**。

---

## 3. Candidate Diff

```
git diff --stat:
  AGENTS.md / CLAUDE.md / docs/ai/05_PROJECT_CONTEXT.md / docs/architecture/CROSS_MODULE_RISK_REGISTER.md
  4 files changed, 6 insertions(+), 6 deletions(-)
  + P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2.md（untracked）
```

```
BUSINESS CODE DIFF = NONE ✅
  无 apps/compute/services.py / models / schemas / migration / 9100 / transaction isolation 改动
  candidate diff 仅治理状态同步
```

---

## 4. Business-Code No-Drift

独立确认 `eb9f182` 后 compute core 未再变化：

```
git diff apps/compute/services.py = NONE（worktree 无业务代码 diff）
```

Candidate B（atomic UPDATE RETURNING）保持，未漂移。`eb9f182` 的 FC-F1 修复仍是当前 baseline。

---

## 5. Current Atomic Compute Mechanism

独立读取 `apps/compute/services.py:150-198`（`_write_transaction_balance_only`）+ `:679-769`（`record_usage` 幂等路径）：

```
record_usage 幂等路径：
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

确认：

```
✅ UPDATE compute_accounts SET balance_tokens = balance_tokens + delta RETURNING balance_tokens
   （ComputeAccount.balance_tokens + delta_tokens 是 SQL 列表达式，DB 行级原子算术）
✅ synchronize_session=False（显式，不同步已缓存 ORM 对象）
✅ tx.balance_after_tokens = returned new_balance（非 account.balance_tokens stale）
```

不存在重新引入 `account.balance_tokens + delta` / `locked.balance_tokens + delta` 作为 idempotent path 余额 source。

---

## 6. `_write_transaction` Boundary

```
_write_transaction = UNCHANGED（READ ONLY）✅
  仍用 with_for_update() + ORM read-modify-write（services.py:231-251）
  locked.balance_tokens + delta_tokens → locked.balance_tokens = new_balance
```

```
CROSS_PATH_LOCK_ORDER_GAP = FUTURE GOVERNANCE ✅
_write_transaction ORM stale-state risk = OUT_OF_FC-F1 ✅
  idempotency_key 恒 NULL，不竞争 non-NULL idempotency unique entry → 跨路径无 wait-cycle
```

Final Closure 通过 ≠ 该 future gap 被解决。`_write_transaction`（recharge/grant/None/mock_recharge）同 ORM stale-state 模式继续属于 future governance。

---

## 7. Candidate FC-0~FC-12 Review

逐项审核 candidate 报告（§10-§22）：

| Gate | candidate 结论 | 审核 |
|---|---|---|
| FC-0 Environment | ✅ PASS | au-fc2-iso@5436, owner=postgres, auto_wechat@0034/61, read committed |
| FC-1 Two-way same identity | ✅ PASS | K1 2-worker → 1 txn / 1 created + 1 replay / -100 / 0 exception |
| FC-2 N-way same identity ×5 | ✅ PASS | 每轮 1 txn / 1 created + 7 replay / -100 / 0 exception |
| FC-3 N-way distinct identity | ✅ PASS | 8 distinct key 各 1 txn / balance_delta=-800（修复前 -200）/ 0 exception |
| FC-4 Merchant-scoped | ✅ PASS | M1+M2 同 K4 → 各 1 txn / 各 -100 |
| FC-5 Competing payload | ✅ PASS | SUPPLEMENTARY，1 txn / first-write-wins + replay |
| FC-6 Post-race replay | ✅ PASS | K6 race 后 replay → txn 仍 1 / balance unchanged |
| FC-7 Error/integrity audit | ✅ PASS | exception=0，IntegrityError 正确 catch |
| FC-8 Ledger reconciliation | ✅ PASS | 每 unique identity ≤ 1 txn |
| FC-9 Global balance closure | ✅ PASS | 998200 = 1000000 + (-1800) |
| FC-10 Application-role | ✅ PASS | auto_wechat 非 superuser |
| FC-11 Cleanup | ✅ PASS | 隔离容器+fixture 已清理 |
| FC-12 Canonical no-drift | ✅ PASS | 0034/61/0/0 unchanged |
| FC-R1 Negative balance | ✅ PASS | B0=100, 2×(-80), final=-60 |
| FC-R2 Mixed workload ×3 | ✅ PASS | 每轮 4 distinct, final=99600 |

无 SKIPPED core gate / N/A used to hide failure / old fixture reused / sequential called concurrent / shared Session / canonical DB write。

---

## 8. Candidate FC-R1/R2 Review

```
FC-R1: B0=100, K-A=-80, K-B=-80, 2 workers concurrent
  → 2 created / 2 txn / final=-60 / balance_after=[20,-60]
  → CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC（非 INSUFFICIENT_BALANCE_REJECTION）

FC-R2 ×3 rounds（fresh keys each）:
  round 0: K-A×4 + K-B/C/D → 4 distinct / 4 txn / final=99600
  round 1: fresh keys → 4 distinct / 4 txn / final=99600
  round 2: fresh keys → 4 distinct / 4 txn / final=99600
  → same-key dedupe + distinct-key preservation 共存
```

每轮 fresh keys，pre-existing txn count=0，非 already committed replay 误当 fresh race。

---

## 9. Independent PostgreSQL Environment

本审批建立全新隔离 PG（非复用 candidate / FC-F1 / Closure-1 / canonical）：

```
container = au-final-iso（postgres:16，端口 5437，独立）
database = auto_wechat（isolated，非 canonical 5432，非 candidate 5436）
database owner = postgres
application principal = auto_wechat（非 superuser）
Alembic revision = 0034（alembic upgrade head via bootstrap_local_dev_pg.py）
physical tables = 61
transaction isolation = read committed（PG 默认，未临时切 SERIALIZABLE）
unique constraint = uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
```

bootstrap 符合已批准 principal contract（owner=postgres 跑 alembic，app principal=auto_wechat GRANT DML via bootstrap_app_role_permissions.sql）。

---

## 10. Independent Same-Key Runtime（IA-FC-1）

```
IA-FC-1 Same-Key Concurrent（N=8）
  merchant=m_ia1, key=ia1-key, 8 workers, barrier release
  
  created=1, replay=7, exc=0
  txn_count(m_ia1, ia1-key)=1
  balance=99900（100000 - 100，exactly one charge）
  
  PASS=True
```

```
SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = INDEPENDENTLY_VERIFIED ✅
  transaction count = 1
  balance delta = exactly one legitimate charge
  all loser requests = valid replay/success contract
  raw DB race exception = 0
```

---

## 11. Independent Distinct-Key Runtime（IA-FC-2）

原 FC-F1 故障点。3 fresh-key rounds，每轮 8 distinct keys：

```
IA-FC-2 Distinct-Key Concurrent（3 rounds, N=8）
  round0: 8 distinct key → created=8, exc=0, per_key_txn=[1,1,1,1,1,1,1,1], balance=99200 (expected 99200) PASS=True
  round1: 8 fresh distinct key → created=8, exc=0, per_key_txn=[1,1,1,1,1,1,1,1], balance=98400 (expected 98400) PASS=True
  round2: 8 fresh distinct key → created=8, exc=0, per_key_txn=[1,1,1,1,1,1,1,1], balance=97600 (expected 97600) PASS=True
```

```
DISTINCT_IDENTITY_LOST_UPDATE = INDEPENDENTLY_NOT_REPRODUCED_AFTER_FIX ✅
DISTINCT_IDENTITY_BALANCE_CLOSURE = INDEPENDENTLY_VERIFIED ✅
  transaction count = N（每轮 8）
  each identity exactly once
  final balance = initial + sum(N committed deltas)
  不再现 Closure-1 旧故障（ledger N rows / account only subset）
```

原 lost update（8 txn / -200 lost 600）在独立隔离 PG 上未再现——修复后 8 distinct key 全部计入 balance（-800/round）。

---

## 12. Independent Negative-Balance Runtime（IA-FC-3）

```
IA-FC-3 Negative Balance（B0=100, K-A=-80, K-B=-80, 2 workers concurrent）
  created=2, exc=0
  txn_count=2
  final_balance=-60（100 - 80 - 80 = -60，arithmetic closure）
  
  PASS=True
```

```
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = INDEPENDENTLY_VERIFIED ✅
CURRENT NEGATIVE-BALANCE BUSINESS SEMANTICS = PRESERVED ✅
  2 committed transactions
  final balance = -60
  无 insufficient balance rejection
  negative balance allowed contract 保持
```

---

## 13. Independent Mixed Workload Runtime（IA-FC-4）

```
IA-FC-4 Mixed Workload（K-A×4 + K-B/C/D，7 workers, 4 unique identities）
  created=4, exc=0
  per_key_txn=[1,1,1,1]（每 unique identity exactly 1 txn）
  balance=99600（100000 - 400，one delta per unique identity）
  
  PASS=True
```

```
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = INDEPENDENTLY_VERIFIED ✅
  committed transaction count = number of unique Business Event Identities（4）
  account delta = sum(one delta per unique identity)（-400）
  same-key dedupe + distinct-key preservation 在同一并发工作负载共存
```

---

## 14. balance_after Audit

独立 runtime 中所有 balance_after_tokens 来自 RETURNING authoritative 值（C2 不读 stale ORM）。distinct identity 并发结果形成合法 serial progression（每个 worker 串行化后的真实余额）。

```
不出现 multiple committed distinct transactions using same stale balance_after ✅
  来自 UPDATE RETURNING 的权威值，非 ORM cached state
```

不要求 transaction ID order = serialization order，但无 stale balance_after 迹象。

---

## 15. Ledger Reconciliation（IA-FC-5）

独立 global reconciliation，所有 fixture merchant：

```
m_ia1: balance=99900, txn_sum=-100, txn_count=1  （same-key，1 legitimate charge）
m_ia2: balance=97600, txn_sum=-2400, txn_count=24 （3 rounds × 8 distinct，24 legitimate charges）
m_ia3: balance=-60, txn_sum=-160, txn_count=2    （negative balance，2 legitimate charges）
m_ia4: balance=99600, txn_sum=-400, txn_count=4   （mixed，4 unique identities）
```

```
LEDGER_ACCOUNT_GLOBAL_CLOSURE = INDEPENDENTLY_VERIFIED ✅
  每 merchant: FINAL_BALANCE = INITIAL_BALANCE + SUM(delta_tokens of all committed legitimate transactions)
  same-key duplicate requests: extra contribution = 0
```

ledger correctness + account correctness 同时成立（非只数 transaction rows，Closure-1 已证明 ledger 可正确 account 错误）。

---

## 16. Global Balance Equation

```
m_ia1: 100000 + (-100) = 99900 ✓
m_ia2: 100000 + (-2400) = 97600 ✓
m_ia3: 100 + (-160) = -60 ✓
m_ia4: 100000 + (-400) = 99600 ✓

same-key replay/loser extra contribution = 0 ✓
```

---

## 17. Error Audit

独立 runtime 收集：

```
unexpected exception = 0
raw DB race error leak = 0
IntegrityError = 被 record_usage 正确 catch（replay/conflict）
DataError = 0（无 overflow）
deadlock = 0
serialization failure = 0
connection errors = 0
session state errors = 0
```

```
NO EXCEPTION != CONCURRENCY CORRECT
  但结合 balance closure（IA-FC-5）共同确认
  same-key UNIQUE 竞争内部受控 IntegrityError 不向 caller 泄漏 raw failure
```

---

## 18. Application Principal

```
runtime principal: current_user=auto_wechat, db=auto_wechat ✅
  is_superuser = False
  database owner = postgres
```

所有正式并发 charge 经 `auto_wechat` 应用角色执行 INSERT compute_transactions + UPDATE compute_accounts。无 owner/superuser/DDL 依赖。非用 postgres 执行业务计费。

```
APPLICATION_ROLE_RUNTIME = INDEPENDENTLY_VERIFIED ✅
```

---

## 19. Transaction Isolation

```
SHOW transaction_isolation = read committed ✅
```

未临时切 SERIALIZABLE。READ COMMITTED 是 PG 默认，生产代码不改。atomic UPDATE 在 READ COMMITTED 下通过 DB 行级原子算术保证 correctness（非靠 isolation level）。

---

## 20. Merchant Isolation（FC-4）

静态 + candidate runtime 确认：

```
uk_compute_transactions_merchant_idempotency UNIQUE(merchant_id, idempotency_key)
  → same key / different merchants 相互独立
  → M1+K / M2+K 各 1 独立 transaction
```

candidate FC-4 PASS（M1+M2 同 K4 → 各 1 txn / 各 -100）。current schema 无漂移，采用 focused 验证。

---

## 21. Post-Race Replay（FC-6）

candidate FC-6 PASS（K6 race 后 sequential replay → txn 仍 1 / balance unchanged / idempotent_replay）。winner 状态可被后续 replay 正确读取。

---

## 22. Canonical No-Drift

审批前后只读检查 canonical（auto-wechat-postgres-dev@5432）：

```
canonical revision = 0034
canonical table count = 61
canonical compute_transactions = 0
canonical compute_accounts = 0
```

```
CANONICAL DB = UNCHANGED ✅
  审批 runtime 在独立隔离 PG（au-final-iso@5437），未触碰 canonical
```

---

## 23. Approval Runtime Cleanup

```
隔离 PG 容器 au-final-iso = 已删除（docker rm -f）
residual approval runtime environment = 0
  容器列表无 au-final-iso
```

验证脚本位于 worktree 外（`e:\work\tmp\fc2_final_verify.py`），未入 worktree。

---

## 24. Evidence Classification

```
FINAL CONCURRENT CORE CLAIMS = INDEPENDENT PG_RUNTIME_VERIFIED ✅
  本审批建立全新隔离 PG，独立复现 IA-FC-1~5 全部 PASS

candidate FC-0~FC-12 + FC-R1/R2 报告 = REPORT_VERIFIED + INDEPENDENT_CRITICAL_RUNTIME_REPRODUCTION ✅
  candidate 报告 + 本审批独立 runtime 共同构成强证据
```

证据等级：本审批独立 runtime（非仅依赖 candidate report），满足 §31 最终审批优先要求。

---

## 25. Global Active None Status

```
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED（保持，不重新打开）✅
```

本审批未重新枚举 compute surface（§26）。current baseline 无新 business code 变化（business-code baseline=eb9f182，Candidate B 保持），无需 STOP 重跑 Global Audit。

---

## 26. F-1 / FC-F1 Status

```
F-1 = RESOLVED（保持）✅
FC-F1 = RESOLVED（保持）✅
```

未发现真实 current regression。独立 runtime（IA-FC-2 distinct-key）确认 FC-F1 修复有效，lost update 未再现。

---

## 27. Recovery Gaps

继续全部保留 OUT_OF_P1（未解决）：

```
DAILY_REPORT_REQUEST_RECOVERY_GAP = OUT_OF_P1
TRAINING_REQUEST_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_RUN_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_REQUEST_RECOVERY_GAP = OUT_OF_P1
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP = OUT_OF_P1
PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1（含 Trusted Reply-Suggestion）
RAG_QUERY_REQUEST_RECOVERY_GAP = OUT_OF_P1
```

Final Closure 通过 ≠ these gaps resolved。

---

## 28. Future Governance Gaps

```
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
CROSS_PATH_LOCK_ORDER_GAP = FUTURE GOVERNANCE
  （_write_transaction 反向锁序，idempotency_key 恒 NULL 不竞争 unique → 不可达）
F-2 = DORMANT / NON-BLOCKING
9100 least-privilege = future governance
_write_transaction ORM stale-state risk = OUT_OF_FC-F1
```

不因 P1 关闭改成 RESOLVED。

---

## 29. RB-10

```
RB-10 CLEANUP = NOT AUTHORIZED
```

Final 审批未顺手 cleanup。

---

## 30. Final Verdict

```
APPROVED

COMPUTE-IDEMPOTENCY-001 = CLOSED
TECHNICAL_CLOSURE = VERIFIED
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = VERIFIED
```

### 为什么是 APPROVED 而非 APPROVED_WITH_CORRECTIONS

本审批建立全新隔离 PG，独立复现 IA-FC-1~5 全部 PASS（非仅依赖 candidate report）。所有 P1 closing claims 独立成立：

- same-key exactly-once：独立验证 1 txn / 1 delta / replay convergence
- distinct-key balance closure：独立验证 3 rounds × 8 distinct key 全部 -800，lost update 未再现
- negative-balance arithmetic：独立验证 final=-60，contract 保持
- mixed workload：独立验证 4 unique / 4 txn / -400，dedupe + preservation 共存
- global reconciliation：独立验证所有 merchant balance = txn_sum 闭合

无并发 correctness 疑点。runtime principal=auto_wechat，isolation=read committed，canonical no-drift。无 CHANGES_REQUIRED 触发条件。

### 为什么不是 FAILED / CHANGES_REQUIRED

逐项核验（§32）：

- same-key duplicate charge？❌ 未发生（IA-FC-1 txn=1）
- distinct-key lost update 再次出现？❌ 未发生（IA-FC-2 3 rounds 全 -800）
- mixed workload 余额不闭合？❌ 未发生（IA-FC-4 99600）
- negative-balance 合同回归？❌ 未发生（IA-FC-3 final=-60，无 rejection）
- balance_after 不合法？❌ 未发生（RETURNING authoritative）
- raw race exception leak？❌ 未发生（exception=0）
- app role 错误？❌ 未发生（auto_wechat）
- canonical DB 污染？❌ 未发生（0034/61/0/0 unchanged）
- business baseline drift？❌ 未发生（business-code=eb9f182，Candidate B 保持）

---

## 31. COMPUTE-IDEMPOTENCY-001 Final State

```
COMPUTE-IDEMPOTENCY-001 = CLOSED ✅
```

---

## 32. Technical Closure Final State

```
TECHNICAL_CLOSURE = VERIFIED ✅
FINAL_POSTGRESQL_CONCURRENT_CLOSURE = VERIFIED ✅

SAME_IDENTITY_CONCURRENT_EXACTLY_ONCE = VERIFIED
DISTINCT_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
MIXED_IDENTITY_CONCURRENT_BALANCE_CLOSURE = VERIFIED
CONCURRENT_NEGATIVE_BALANCE_ARITHMETIC = VERIFIED
LEDGER_ACCOUNT_GLOBAL_CLOSURE = VERIFIED
APPLICATION_ROLE_RUNTIME = VERIFIED
CANONICAL_NO_DRIFT = VERIFIED
```

---

## 33. Closing Guarantee

P1 正式关闭保证（§34）：

```
Every ACTIVE compute charge path carries a stable Business Event Identity.

Same Business Event concurrent/replayed charging
→ at most one committed ledger transaction
→ at most one balance delta.

Distinct legitimate Business Events concurrent against the same merchant account
→ each committed event contributes exactly one delta
→ no lost update.

Ledger and account balance close exactly under PostgreSQL READ COMMITTED.
```

---

## 34. Explicit Non-Guarantees

P1 CLOSED 不保证（§35）：

```
P1 CLOSED
≠ full request recovery（7 个 REQUEST_RECOVERY_GAP 仍 OUT_OF_P1）
≠ HTTP response-loss dedupe（PREVIEW_REQUEST_RECOVERY_GAP 含 Trusted Reply-Suggestion，OUT_OF_P1）
≠ all dormant/legacy None paths removed（core None compatibility 仍 present，但 ACTIVE caller transmitting None = 0；F-2 DORMANT）
≠ all future lock-order debt removed（CROSS_PATH_LOCK_ORDER_GAP = FUTURE GOVERNANCE；_write_transaction ORM stale-state = OUT_OF_FC-F1）
≠ RB-10 cleanup done（RB-10 = NOT AUTHORIZED）
```

防止未来把 Technical Closure 解释过头。

---

## 35. Commit Authorization

授权一次最终 P1 Technical Closure commit。允许文件：

```
docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2.md
docs/architecture/remediation/P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2_APPROVAL.md
CLAUDE.md
AGENTS.md
docs/ai/05_PROJECT_CONTEXT.md
docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

状态变更（commit 时同步）：

```
COMPUTE-IDEMPOTENCY-001: OPEN_PENDING_FINAL_CONCURRENT_APPROVAL → CLOSED
TECHNICAL_CLOSURE: PENDING_FINAL_CONCURRENT_APPROVAL → VERIFIED
FINAL_POSTGRESQL_CONCURRENT_CLOSURE: VERIFIED_PENDING_APPROVAL → VERIFIED
```

保留所有 OUT_OF_P1 / FUTURE / DORMANT 状态。不得包含新的业务代码。

建议 commit message：

```
闭环：完成算力幂等P1技术收口
```

```
DO NOT PUSH
```

---

## 36. Next Governance Step

```
COMPUTE-IDEMPOTENCY-001 = CLOSED
TECHNICAL_CLOSURE = VERIFIED
```

P1 修复主线停止。下一阶段回到 `Cross-Module Risk Register`，按优先级选择下一个 Phase 3A/3B 风险项（P2 M04 Claim/Lease / P3a M05 Reference / P3b M05 URL / S1-S5 结构风险）。

不得自动选择 RB-10，除非另行授权。

---

## 37. 边界遵守确认

- ✅ 未修改 compute core / record_usage / _write_transaction_balance_only / _write_transaction
- ✅ 未修改 migration / models / schemas / 9100 / consumer identity / transaction isolation
- ✅ 未 commit / push（commit 授权留给最终 P1 closure，§35）
- ✅ canonical DB 未 mutation（READ ONLY，0034/61/0/0 unchanged）
- ✅ 全新隔离 PG（au-final-iso@5437，非 canonical / 非此前 candidate DB）
- ✅ 独立 SQLAlchemy sessions（每 worker 独立 Session）
- ✅ fail-closed guard（端口 5437 非 5432 canonical）
- ✅ 隔离 PG 已清理（容器删除，residual=0）
- ✅ 未修 F-2 / recovery gaps / RB-10 / `_write_transaction` / future lock-order gap
- ✅ 未宣布下一 Phase 自动选择

---

## 38. 完成后停止

本审批窗口完成后停止。P1 修复主线 CLOSED。不得自行：

- 修改 compute core / migration / isolation
- 修 `_write_transaction` / F-2 / recovery gaps
- RB-10
- push
- 开始下一 Phase（须回到 Cross-Module Risk Register 重新按优先级选择）

---

## 附录：审批纪律确认

- READ / VERIFY ONLY + 独立隔离 PG runtime：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push（commit 授权留给最终 P1 closure，§35）。
- 独立 runtime：建立全新隔离 PG（au-final-iso@5437），独立复现 IA-FC-1~5 全部 PASS（非仅依赖 candidate report）。证据等级 INDEPENDENT PG_RUNTIME_VERIFIED。
- 独立复现：current compute mechanism 代码审查 + `_write_transaction` 未改确认 + 独立并发验证脚本（barrier + 独立 Session + fresh keys）+ canonical no-drift 只读检查 + 隔离 PG cleanup。
- 未采信执行窗口自述：所有 P1 closing claims 经独立隔离 PG runtime 验证。
```
