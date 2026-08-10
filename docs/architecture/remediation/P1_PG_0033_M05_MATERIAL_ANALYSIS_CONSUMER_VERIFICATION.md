# P1-PG-0033 — M05 Material Analysis Consumer PostgreSQL 验证报告

> 任务：`P1-PG-0033 — M05 Material Analysis Consumer PostgreSQL Verification`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 consumer-level PG verification
> 基线 commit：`b15afac`（验证：闭环日报0032 PostgreSQL幂等计费）
> 日期：2026-08-11
> 窗口：P1-PG-0033 M05 Material Analysis Consumer PG 验证执行/验证窗口
> Source of Truth：真实 PG runtime 证据（canonical PG@0034，应用角色 `auto_wechat`，真实 consumer 路径） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| D33-0 Git / environment | ✅ PASS |
| D33-1 Application principal | ✅ PASS |
| D33-2 Static consumer chain | ✅ PASS（无 CONTRACT_DRIFT）|
| D33-3 Business Event Identity | ✅ PASS |
| D33-4 Schema prerequisites | ✅ PASS |
| D33-5 Mock boundary | ✅ PASS |
| D33-6 First execution（E-A）| ✅ PASS |
| D33-7 Same-execution replay（NO_DOUBLE_CHARGE）| ✅ PASS |
| D33-8 Distinct-execution separation（E-B）| ✅ PASS |
| D33-9 Non-null identity | ✅ PASS |
| D33-10 Execution identity persistence | ✅ PASS |
| D33-11 PG transaction/balance evidence | ✅ PASS |
| D33-12 Cleanup / residual | ✅ PASS（residual=0）|

**Verdict（候选）**：`0033 M05 MATERIAL ANALYSIS CONSUMER: PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`
→ **独立审批已通过（2026-08-11）**：正式升格为 `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。详见 `P1_PG_0033_M05_MATERIAL_ANALYSIS_CONSUMER_APPROVAL.md`。

Business Event Identity：`material_analysis_execution:{execution_id}:ark_analysis`（与冻结 contract 一致，当前代码无 drift）。

证据等级：`PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## 1. Baseline / Commit

```text
HEAD = b15afacbf284fa656c8ec71c3d6565e970af905e（验证：闭环日报0032 PostgreSQL幂等计费）
worktree = clean（验证前无未提交改动）
```

前置状态：

```text
DB-BL                       = REPAIR_VERIFIED / COMPLETE
AUTO_WECHAT_DEV_PG          = CANONICAL_ALEMBIC_BASELINE@0034
APPLICATION_ROLE_PERMISSION_GAP = RESOLVED
LOCAL DEV application-role permission = VERIFIED
0033 = AUTHORIZED_TO_START_PG_VERIFICATION（≠ PG_VERIFIED，本轮验证）
0032 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（独立审批已通过）
P1 = COMPUTE-IDEMPOTENCY-001 OPEN / TECHNICAL_CLOSURE=PENDING
```

0032 独立审批 commit（`dbf8005` 修复应用角色权限）已包含在本基线 `b15afac` 之中；本轮基线无 0033 之后的额外 commit，HEAD 未因 0033 治理证据变化。

---

## 2. Environment / Principal（D33-0 / D33-1）

```text
environment        = LOCAL DEVELOPMENT ONLY
container/service  = auto-wechat-postgres-dev (Up 12h, healthy)
database           = auto_wechat
backend            = PostgreSQL 16.14
revision           = 0034
physical tables    = 61
database owner     = postgres
PG network         = auto_wechat_default
```

**Application Principal 证据（consumer runtime 写入路径）**：

- 验证脚本以 `DATABASE_URL=postgresql+psycopg://auto_wechat:change_me@localhost:5432/auto_wechat` 注入 env（`app/config.py:38` `os.environ.setdefault` 不覆盖已设 env），`app.database.SessionLocal` bind 到该 engine。
- `analyze_material_async` 内部 `from app.database import SessionLocal`（[app/services/material_analysis.py:25](../../../app/services/material_analysis.py)），与 record_usage 共用同一 `auto_wechat` 角色连接。
- runtime principal 直查：`SELECT current_user, current_database()` → `('auto_wechat', 'auto_wechat')`（Python psycopg 应用角色直连）。
- consumer 计费写入路径全程由 `auto_wechat` application principal 执行，未临时切 `postgres` superuser 完成核心写入。`postgres` 仅用于 catalog inspection / schema 前提核验。

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

---

## 3. Static Consumer Chain（D33-2）

以当前代码重新建立（非复制旧报告），真实文件/函数。**关键事实：M05 是 9000 进程内 consumer，不走 9100→9000 HTTP**——与 0032（9100 `ComputeUsageClient` → 9000 `/internal/compute/usage` HTTP）不同，M05 consumer 在 9000 进程内直接 import 调用 `record_usage`。

```text
Material Analysis execution（BackgroundTask）
  → app/services/material_analysis.py:20 analyze_material_async(material_id, presigned_url)
    → :25 from app.database import SessionLocal
    → :36 db.query(AiEditMaterial).filter(id==material_id)
    → :46-51 AiEditMaterialAnalysisExecution(material_id=str(material_id), source_sha256, lifecycle_status="running")
        + :51 db.commit()                        [MA-0 durable before ark：execution_id 持久化先于外部 Ark 副作用]
    → :54 _analyze_via_ark(presigned_url, ark_api_key)   [★ 唯一外部 mock 边界：方舟多模态 Ark SDK]
        → :154 from volcenginesdkarkruntime import Ark   [外部 Ark，本轮 mock]
    → :101 execution.lifecycle_status="completed" + :102 db.commit()   [C1 红线：COMPLETED 先于 usage report]
    → :106-112 _report_analysis_usage(db, merchant_id, prompt_tokens, completion_tokens, execution_id=execution.id)
      → app/services/material_analysis.py:267-268 idempotency_key = f"material_analysis_execution:{execution_id}:ark_analysis"
      → :280 from app.services.compute_service import record_usage   [进程内 import，非 HTTP]
        → app/services/compute_service.py:7-31 re-export shim → apps.compute.services
        → apps/compute/services.py:615 record_usage()
          → :664-668 查 ComputeMarkupRatio(ai_edit)  → enabled/actual/markup=0
          → :677 calculate_billed_tokens(tokens, 0) = tokens
          → :692-713 INSERT ComputeTransaction(idempotency_key=...) + :716 db.flush()
          → :718-727 flush 成功→ get_or_create_account + _write_transaction_balance_only（原子扣费）+ :725 db.commit()
          → :728-769 IntegrityError → db.rollback() → 读已存在行
            → :747 existing.payload_evidence == payload_evidence → idempotent_replay（不二次扣费，:756 return）
            → :757 不同 → idempotency_conflict
          → PostgreSQL compute_transactions / compute_accounts
```

**全程未发现 CONTRACT_DRIFT**：当前代码实际生成的 identity 仍是 `material_analysis_execution:{execution_id}:ark_analysis`（[material_analysis.py:267-268](../../../app/services/material_analysis.py)），与冻结 contract 一致。

execution_id 来源：`AiEditMaterialAnalysisExecution.id`（[app/models.py:1751](../../../app/models.py)），由 consumer 在 Ark 调用前 durable commit（[material_analysis.py:46-51](../../../app/services/material_analysis.py)）。非 request id / random UUID per retry / HTTP attempt id / worker attempt——是稳定 PG 持久化业务执行身份。billing truth 只归 M07 `ComputeTransaction`（execution 无 `is_billed` / `billing_status` 字段，经 [models.py:1732-1757](../../../app/models.py) 列定义核验 + unit test `test_constraint_no_is_billed` 约束）。

---

## 4. Business Event Identity（D33-3）

真实生成代码 [app/services/material_analysis.py:247-271](../../../app/services/material_analysis.py)：

```python
def _report_analysis_usage(db, *, merchant_id, prompt_tokens, completion_tokens, execution_id=None):
    ...
    # P1 Stage 5F-3：execution_id 非空 → 构造幂等键（非 conversation/时间戳推导）
    idempotency_key = (
        f"material_analysis_execution:{execution_id}:ark_analysis"
        if execution_id is not None
        else None
    )
```

- identity 来源：`AiEditMaterialAnalysisExecution.id`，由 consumer 前置持久化后透传。
- 非时间戳推导（`datetime.now` / `time.time` 不参与 key 构造，经源码核验 + unit test `test_identity_contract_key_construction` 约束）。
- `execution_id=None` 走旧兼容路径（`record_usage` idempotency_key=None → warning 裸扣），正式 consumer 路径 `execution_id` 恒非空。

```text
material_analysis_execution:{execution_id}:ark_analysis
```

与 `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #8 冻结 contract 一致，无 drift。

---

## 5. Migration 0033 / Schema Preconditions（D33-4）

canonical PG@0034 中确认 0033 所需对象真实存在（`postgres` catalog inspection）：

| 对象 | 来源 | 核验 |
|---|---|---|
| `ai_edit_material_analysis_executions` 表 | migration 0033 `op.create_table` | ✅ EXISTS（6 列）|
| `id` PK + `ai_edit_material_analysis_executions_pkey` | 0033 sa.Column primary_key | ✅ |
| `material_id` varchar(64) NOT NULL | 0033 | ✅ |
| `source_sha256` varchar(64) NOT NULL | 0033 | ✅ |
| `lifecycle_status` varchar(20) NOT NULL default 'running' | 0033 server_default | ✅ |
| `created_at` timestamp NOT NULL default now() | 0033 | ✅ |
| `completed_at` timestamp nullable | 0033 | ✅ |
| `ck_ai_edit_material_analysis_executions_status` CHECK | 0033 lifecycle_status ∈ (running/completed/failed) | ✅ |
| `idx_ai_edit_material_analysis_executions_material` index | 0033 op.create_index(material_id) | ✅ |
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency` | [app/models.py:941](../../../app/models.py) UNIQUE(merchant_id, idempotency_key) | ✅ EXISTS（驱动 IntegrityError）|
| `compute_transactions.idempotency_key` 列 | [app/models.py:997](../../../app/models.py) | ✅ |
| `compute_transactions.payload_evidence` 列 | [app/models.py:998](../../../app/models.py) | ✅ |
| `compute_markup_ratios` 行 `ai_edit` | migration 0023 | ✅ EXISTS（enabled=true / actual / markup=0 / fixed_tokens_per_call=NULL）|
| application role 对 `ai_edit_material_analysis_executions`/`compute_transactions`/`compute_accounts` 的 INSERT/SELECT | PR-3 grants（app-role permission VERIFIED）| ✅ |

migration 0033：`migrations/postgres/auto_wechat/versions/0033_material_analysis_executions.py`，revision=`0033`，down_revision=`0032`，create_date=2026-08-08。新建对象：`ai_edit_material_analysis_executions` 表（6 列 + PK + CHECK + material 索引），不激活 dormant `AiEditMaterialProcess` 五阶段表。

revision 仍为 0034（0033 已包含在 head 链中，0030→0032→0033→0034 线性单链）。

**schema 存在 ≠ PG_VERIFIED**（仅 `SCHEMA_PREREQUISITE = PASS`），consumer runtime 仍需真实执行（见 §6-§11）。

---

## 6. Mock Boundary（D33-5）

**允许并仅 mock**：`_analyze_via_ark`（方舟多模态 Ark SDK 外部调用）。mock 返回确定性受控结果：

```text
{has_speech: True, transcript: "受控测试口播内容", description: "受控画面",
 _prompt_tokens: 120, _completion_tokens: 80}
```

mock 目的：避免真实方舟 API 收费 / 网络不稳定 / 非确定性模型结果，且不调用生产 TOS / 不产生真实付费 Ark 调用 / 不修改实际素材库业务状态 / 不触发后续正式发布生成流程。

**以下链全程真实，未 mock**：

```text
M05 consumer orchestration（analyze_material_async）
execution_id 持久化（AiEditMaterialAnalysisExecution durable commit）
Business Event Identity 生成（_report_analysis_usage 内 f-string 构造）
usage extraction（prompt_tokens + completion_tokens → total）
compute client（进程内 record_usage，非 mock）
record_usage INSERT / 原子扣费 / IntegrityError 幂等路径
9000 compute service（apps.compute.services.record_usage，进程内真实调用）
PostgreSQL uniqueness（uk_compute_transactions_merchant_idempotency）
compute account balance
```

关键 compute 路径未被 mock——本轮不是 unit/integration test，达到 `PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## 7. Controlled Fixture（D33-6 setup）

完全受控 fixture，以 `auto_wechat` 应用角色写入：

```text
merchant_id          = m_d33_verify（受控测试商户，非真实客户）
AiEditMaterial mat-A = material_id=d33-mat-A, source_sha256=d33sha256aaa, scope=merchant, media_type=video
AiEditMaterial mat-B = material_id=d33-mat-B, source_sha256=d33sha256bbb, scope=merchant, media_type=video
compute account      = 不存在（get_or_create_account 首次计费建账，balance=0）
```

baseline（计费前）：

```text
ai_edit_material_analysis_executions(total) = 0
compute_accounts(m_d33_verify)              = 0
compute_transactions(m_d33_verify)          = 0
balance_before                              = 0
```

未使用真实客户素材；未调用真实方舟 / TOS / 微信 / 抖音 / 外部 API（Ark 为唯一 mock）。

---

## 8. E-A First Execution（D33-6）

从真实 M05 consumer 入口 `analyze_material_async(matA.id, "https://test.invalid/ea")` 执行一次 `ark_analysis` 阶段（mock Ark 返回 120+80 token）：

```text
E-A execution_id    = 1
lifecycle_status   = completed
identity            = material_analysis_execution:1:ark_analysis（consumer 自然生成，非手工构造 key）
```

**A. Consumer 执行成功** ✅（execution COMPLETED，`_report_analysis_usage` 被调用，C1 红线：COMPLETED commit 先于 usage report）

**B. Compute Transaction = exactly 1**（PG 查询证据）：

```text
id=10 | idempotency_key=material_analysis_execution:1:ark_analysis | transaction_type=consume | delta_tokens=-200 | balance_after_tokens=-200
capability_key=ai_edit | model=d33-verify-mock-ark | usage_measurement_method=provider_tokens
actual_tokens=200 | prompt_tokens=120 | completion_tokens=80 | payload_evidence IS NOT NULL
```

**C. Idempotency Identity 一致** ✅：`material_analysis_execution:1:ark_analysis` = `material_analysis_execution:{execution_id=1}:ark_analysis`

**D. Balance**（consume `delta_tokens` 为负，markup=0 → billed=actual=200）：

```text
balance_before = 0   （account 首次建账）
charge_delta   = -200（billed_tokens=calculate_billed_tokens(200, 0)=200）
balance_after  = -200（= balance_before + delta = 0 + (-200)）✓
```

**E. Usage Metadata**（当前 compute contract 实际存储字段）：

```text
capability_key=ai_edit / model=d33-verify-mock-ark / usage_measurement_method=provider_tokens
actual_tokens=200 / payload_evidence IS NOT NULL / llm_call_stage=NULL（M05 未传 stage，payload_evidence 不含 stage）
```

---

## 9. E-A Replay（D33-7）

对同一个 `execution_id=1`，再次从真实 consumer **usage-report 路径** `_report_analysis_usage(db, merchant_id, prompt_tokens=120, completion_tokens=80, execution_id=1)` 进入（identity 由函数内部 f-string 自然重新生成，非手工构造 key，非直接调 `record_usage`）：

```text
调用：_report_analysis_usage(..., execution_id=1)  [same identity，模拟 usage report 重试 / crash 后恢复重报]
identity 自然重新生成：material_analysis_execution:1:ark_analysis
```

> 说明：`analyze_material_async` 每次新建 execution（re-analysis = 新 execution = 新合法消费），无法通过对同一 material 再次调 `analyze_material_async` 复用同一 execution_id。M05 的 same-execution replay 触发点是 consumer 侧 usage-report 路径 `_report_analysis_usage` 对同一 `execution_id` 再次调用（对应 crash 后 usage report 重试场景，即 `M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP` 关注的恢复路径）。

**PostgreSQL 权威证据**（不靠返回值；`_report_analysis_usage` 无 return 语句，恒返回 None）：

```text
compute_transactions WHERE idempotency_key='material_analysis_execution:1:ark_analysis' count = 1（未产生第 2 行）✓
account balance 仍 = -200（replay 后未变）✓
```

**法证细节**：`compute_transactions.id` 序列为 10, 12（id=11 缺失）。id=11 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 [apps/compute/services.py:728-756](../../../apps/compute/services.py) `idempotent_replay` 分支。该 id gap 印证 IntegrityError 幂等路径真实执行，而非"未尝试 INSERT"。

```text
same event → same idempotency identity → duplicate charge suppressed（replay）✓
NO_DOUBLE_CHARGE_VERIFIED
```

SUPPLEMENTARY_RUNTIME_EVIDENCE：id gap=11（IntegrityError rollback 副证）。sequence id gap 不是幂等硬证据——正式硬证据仍是 same identity + one transaction + balance unchanged（已满足）。

---

## 10. E-B Distinct Execution（D33-8）

创建另一 material `mat-B`，再从真实 consumer 入口 `analyze_material_async(matB.id, "https://test.invalid/eb")` 执行 `ark_analysis` 阶段（mock Ark 相同 token）：

```text
E-B execution_id    = 2
lifecycle_status    = completed
identity            = material_analysis_execution:2:ark_analysis（consumer 自然生成）
预期 transaction count = 1
```

**PostgreSQL 证据**：

```text
compute_transactions WHERE idempotency_key='material_analysis_execution:2:ark_analysis' count = 1  ✓
id=12 | idempotency_key=material_analysis_execution:2:ark_analysis | delta_tokens=-200 | balance_after_tokens=-400
```

两个不同 execution 合计 **2 个 distinct business-event identities**（`:1:ark_analysis` / `:2:ark_analysis`），无 collision / 共享 / 互相吞没：

```text
identity(E-A) = material_analysis_execution:1:ark_analysis
identity(E-B) = material_analysis_execution:2:ark_analysis
identity_distinct = True
same event → dedupe；different event → independent charge  ✓
```

---

## 11. Compute Transactions / Balance（D33-11）

PG 查询（`auto_wechat` 应用角色只读）全部 consume txns for `m_d33_verify`：

| id | idempotency_key | type | delta | balance_after | actual | payload_evidence |
|----|---|---|---|---|---|---|
| 10 | `material_analysis_execution:1:ark_analysis` | consume | -200 | -200 | 200 | NOT NULL |
| 12 | `material_analysis_execution:2:ark_analysis` | consume | -200 | -400 | 200 | NOT NULL |

按 identity 计数：

| idempotency_key | txn_count |
|---|---|
| `material_analysis_execution:1:ark_analysis` | 1 |
| `material_analysis_execution:2:ark_analysis` | 1 |

账户：

```text
merchant_id=m_d33_verify / balance_tokens=-400
```

balance 推进：

```text
0 →(E-A first)→ -200 →(E-A replay, 不变)→ -200 →(E-B)→ -400 ✓
final balance = initial(0) + legitimate E-A delta(-200) + legitimate E-B delta(-200) = -400 ✓
E-A replay does not contribute another delta ✓
```

2 distinct identities / 2 legitimate compute charges / replay 不二次计费。

---

## 12. Execution Identity Persistence（D33-10）

本轮 Material Analysis execution 在 PG 中真实持久化并被复用：

| id | material_id | source_sha256 | lifecycle_status | created_at | completed_at |
|----|---|---|---|---|---|
| 1 | '1' | d33sha256aaa | completed | NOT NULL | NULL |
| 2 | '2' | d33sha256bbb | completed | NOT NULL | NULL |

- execution `id` 持久存在，`_report_analysis_usage` 复用同一 `execution.id` 作 identity 来源，非每次重放重新产生新 execution。
- merchant/tenant ownership：`ai_edit_material_analysis_executions` 表本身无 `merchant_id`/`tenant_id` 列（schema 事实，见 §5），ownership 通过 `material_id` → `AiEditMaterial.merchant_id` 间接关联（consumer 传入 `material.merchant_id` 给 `_report_analysis_usage`）。
- `lifecycle_status=completed` 稳定持久。
- timestamps：`created_at` NOT NULL（durable commit 生效）；`completed_at` 当前为 NULL——这是 consumer 代码现状（[material_analysis.py:101](../../../app/services/material_analysis.py) 只设 `lifecycle_status="completed"`，未填充 `completed_at` 列），不影响 Business Event Identity 稳定性（identity 基于稳定 `execution.id`，非 `completed_at`）。本窗口不修此 consumer 代码现状（属范围外，见 §17/§18）。

```text
Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）✓
```

---

## 13. Non-null Identity（D33-9）

```text
compute_transactions WHERE merchant_id='m_d33_verify'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0  ✓
```

M05 active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，且与冻结 contract 一致。无 `idempotency_key=None` 走旧兼容路径（`record_usage` 的 idempotency_key=None warning 路径未触发）。

---

## 14. Application Role Evidence（D33-1）

| 证据 | 结论 |
|---|---|
| 验证脚本 DATABASE_URL principal | `auto_wechat`（非 superuser）|
| runtime principal 直查 | `current_user=auto_wechat / current_database=auto_wechat` |
| consumer execution 写入 | `analyze_material_async` 内部 SessionLocal（DATABASE_URL=`auto_wechat` 角色）→ PG |
| consumer 计费写入 | 经 `_report_analysis_usage` → `record_usage`，DATABASE_URL=`auto_wechat` 角色 → PG |
| fixture 写入 + 证据读取 | Python psycopg 应用角色直连 `auto_wechat` |
| superuser-as-consumer 替代 | 无（`postgres` 仅用于 catalog inspection / schema 前提核验）|

→ `APPLICATION_ROLE_RUNTIME_VERIFIED` + `PG_RUNTIME_VERIFIED`（非仅 unit test；现有 `tests/test_material_analysis_compute_idempotency_migration.py` 为 SQLite + 直接调 record_usage 的 unit test，本轮以 canonical PG + 真实 consumer 路径 + 应用角色升级证据等级）。

---

## 15. Cleanup（D33-12）

测试完成后以 `auto_wechat` 应用角色清理受控 fixture：

```text
DELETE compute_transactions WHERE merchant_id='m_d33_verify'                 → 2
DELETE compute_accounts WHERE merchant_id='m_d33_verify'                     → 1
DELETE ai_edit_material_analysis_executions WHERE material_id IN ('1','2')   → 2
DELETE ai_edit_material_analyses WHERE source_sha256 IN ('d33sha256aaa','d33sha256bbb') → 2
DELETE ai_edit_materials WHERE merchant_id='m_d33_verify'                    → 2
COMMIT
```

residual 检查（全部 0，clean baseline 恢复）：

```text
compute_txns(m_d33_verify)        = 0
compute_accounts(m_d33_verify)    = 0
ai_edit_material_analysis_executions(material_id 1,2) = 0
ai_edit_material_analyses(sha)    = 0
ai_edit_materials(m_d33_verify)   = 0
total compute_transactions        = 0
total compute_accounts           = 0
total ai_edit_material_analysis_executions = 0
total ai_edit_materials           = 0
```

DB-BL 完整性未变：`head=0034 / tables=61`。验证脚本经 stdin 管道执行，未写入 worktree（`git status` clean，零业务代码改动）。

```text
residual test data = 0
```

---

## 16. D33 Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| D33-0 | Git / environment | ✅ PASS | HEAD=b15afac / clean；LOCAL DEV，canonical PG@0034，PG 16.14，db_owner=postgres，61 表 |
| D33-1 | Application principal | ✅ PASS | current_user=auto_wechat；DATABASE_URL 应用角色；consumer 写入经 auto_wechat 角色；postgres 仅 catalog |
| D33-2 | Static consumer chain | ✅ PASS | §3 真实文件/函数链；identity 与冻结 contract 一致，无 drift；M05 进程内调 record_usage |
| D33-3 | Business Event Identity | ✅ PASS | `material_analysis_execution:{execution_id}:ark_analysis`，来自稳定 execution.id |
| D33-4 | Schema prerequisites | ✅ PASS | 0033 表/列/约束/索引存在；compute 幂等唯一约束存在；ai_edit markup ratio 存在；app role 有权限 |
| D33-5 | Mock boundary | ✅ PASS | 仅 mock Ark 外部多模态；consumer/identity/usage/compute/PG 幂等全真实 |
| D33-6 | First execution（E-A）| ✅ PASS | E-A(id=1) → 1 consume txn(id=10)，identity 一致，balance 0→-200，payload_evidence NOT NULL |
| D33-7 | Same-execution replay | ✅ PASS | E-A replay → txn count 仍 1，balance 不变(-200)；id gap=11 印证 IntegrityError rollback |
| D33-8 | Distinct-execution separation | ✅ PASS | E-B(id=2) → 1 独立 txn(id=12)，2 distinct identities，无 collision |
| D33-9 | Non-null identity | ✅ PASS | 0 null/empty idempotency_key |
| D33-10 | Execution identity persistence | ✅ PASS | 2 行 PG 持久，lifecycle=completed，identity 基于稳定 execution.id（created_at NOT NULL；completed_at 现状未填，不影响 identity）|
| D33-11 | PG transaction/balance evidence | ✅ PASS | 2 txns(id 10,12)，delta=-200 each，balance=-400=0+(-200)+(-200)，replay 不贡献 delta |
| D33-12 | Cleanup / residual | ✅ PASS | residual=0，DB-BL 不变(0034/61)，worktree clean |

---

## 17. Out-of-P1 Findings

```text
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP
分类：OUT_OF_P1 RELIABILITY GAP（保持原分类，未升级）
```

本轮观察：

- `_report_analysis_usage` 内部 `except Exception` catch（[material_analysis.py:295-296](../../../app/services/material_analysis.py)），usage report 失败不抛出、不降级 execution COMPLETED、不重跑 Ark（C1 红线，CODE_VERIFIED by unit test MA-5）。这是设计行为，非 recovery gap 缺陷。
- 本轮 same-execution replay（§9）正是模拟 crash 后 usage report 重试路径——证明同一 execution_id 重报不会 double charge（`NO_DOUBLE_CHARGE_VERIFIED`），即 recovery 路径的幂等性已满足。
- 本轮**未观察到** recovery gap 导致 `same business event → double charge`——故不升级为 P1 blocker。
- 仍**不验证** usage report crash 后自动恢复编排 / request durable recovery / worker restart recovery / retry orchestration redesign——这些属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴。

```text
KNOWN OUT_OF_P1 RELIABILITY GAP（保持冻结，本轮未触碰、未扩大、未修）
```

### 范围外观察（不修，仅记录）

- `completed_at` 列当前未被 consumer 填充（§12）。属 M05 consumer 代码现状，不阻断 0033 compute consumer PG verification，本窗口不修。
- temporary URL durability / active reference integrity / material lifecycle-storage 等 M05 独立治理风险：本轮未直接阻止受控 Material Analysis consumer 执行，`OUT_OF_SCOPE`，未顺手修。

### 并发边界

本轮未执行全局 concurrent closure（`Final PostgreSQL Concurrent Closure Gate` 后续独立执行）。txn id gap（10,12，缺 11）为 replay INSERT-rollback 的法证副证，非正式 concurrent test。`lack of concurrent test` 不阻断 0033。

---

## 18. Verdict

```text
0033 M05 MATERIAL ANALYSIS CONSUMER:
PG_VERIFICATION_COMPLETE_PENDING_APPROVAL
  → 独立审批通过（2026-08-11）：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
material_analysis_execution:{execution_id}:ark_analysis

APPLICATION_ROLE_RUNTIME_VERIFIED

Same-event replay:
NO_DOUBLE_CHARGE_VERIFIED（E-A replay → 1 txn / balance 不变 / id gap=11 印证 IntegrityError）

Distinct-event separation:
VERIFIED（E-B → 独立 charge / 2 distinct identities / 无 collision）
```

**独立审批窗口已裁定 APPROVED**（`P1_PG_0033_M05_MATERIAL_ANALYSIS_CONSUMER_APPROVAL.md`）。0033 正式状态 = `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`；0034 Preview 授权 `AUTHORIZED_TO_START_PG_VERIFICATION`。P1 整体仍 OPEN / TECHNICAL_CLOSURE=PENDING。

---

## 19. P1 Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

本轮完成的是 **0033 M05 Material Analysis consumer PostgreSQL verification**（候选 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`），不是整个 P1 closure。仍待：独立审批窗口裁定 0033 → 0034 Preview consumer PG verification → RAG Query 0005 → Global Active None Audit → Final PG Concurrent Closure Gate → LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP。

---

## 20. 边界遵守

- ✅ 未修改业务代码（NO BUSINESS CODE CHANGE）——验证脚本经 stdin 管道执行，未入 worktree；
- ✅ 未修改 migration 0033 / 未新增 repair migration / 未 stamp / 未手工 schema 修复（DB-BL 闭环，head=0034 / 61 表不变）；
- ✅ 未开始 0034 / RAG Query 0005 / Global Active None Audit / Final Concurrent Closure / RB-10 / bootstrap owner drift 修复；
- ✅ 未用 superuser 替代 app role 完成 consumer 核心写入；
- ✅ 未提交（candidate diff 仅本报告文件，数据库证据/凭据/dump 未入库）；
- ✅ consumer 验证仅 mock Ark 外部多模态（外部非确定性边界），未 mock consumer orchestration / identity 生成 / usage extraction / compute charge / PG 幂等路径；
- ✅ 未触碰 `M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP`（OUT_OF_P1）；
- ✅ 未操作真实客户素材 / 生产 TOS / 真实付费 Ark 调用。

---

## 21. Git / Commit

按 §三十四：**不自行 commit**。本报告为 candidate diff（唯一新增文件 `P1_PG_0033_M05_MATERIAL_ANALYSIS_CONSUMER_VERIFICATION.md`），供独立审批窗口复核。数据库测试证据已清理（residual=0），无凭据/dump/probe 残留。

提交：**P1-PG-0033 独立审批窗口。**

---

## 附：本窗口独立核验证据索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| Git baseline | `git rev-parse HEAD` + `git status` | b15afac / clean |
| 环境/principal | Python psycopg 应用角色 + docker exec psql | auto_wechat / PG 16.14 / 0034 / 61 表 / db_owner=postgres |
| 静态调用链 | 代码 file:line 核验 | 无 CONTRACT_DRIFT，identity 与冻结一致；M05 进程内调 record_usage（非 HTTP）|
| schema 前提 | catalog inspection（postgres）| 0033 表/列/约束/索引 + compute 幂等唯一约束 + ai_edit markup ratio 存在 |
| fixture | 应用角色 INSERT | mat-A(id=1) + mat-B(id=2)，baseline 0/0/0 |
| first execution | `analyze_material_async`（Ark mock）+ PG 查询 | 1 txn(id=10) / identity 一致 / balance 0→-200 |
| replay | `_report_analysis_usage`（same execution_id）+ PG 查询 | txn count 仍 1 / balance 不变 / id gap=11 印证 IntegrityError |
| distinct | `analyze_material_async`(mat-B) + PG 查询 | 1 独立 txn(id=12) / 2 distinct identities / 无 collision |
| balance | compute_accounts 查询 | -400（0→-200→-200→-400）|
| non-null identity | count NULL/empty | 0 |
| execution persistence | executions 表查询 | 2 行持久 / lifecycle=completed / created_at NOT NULL |
| cleanup | 应用角色 DELETE + residual 查询 | residual=0 / head=0034 / 61 表不变 |
| worktree | git status | clean（脚本经 stdin，未入 worktree）|

所有核验：真实 canonical PG + 应用角色 + 真实 consumer 路径 + PG 直查证据。零业务污染，零迁移修改，零 DB-BL 重开，零业务代码改动。
