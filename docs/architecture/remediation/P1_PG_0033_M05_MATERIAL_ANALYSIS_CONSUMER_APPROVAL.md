# P1-PG-0033 — M05 Material Analysis Consumer PostgreSQL Verification 独立审批报告

> 窗口：P1-PG-0033 M05 Material Analysis Consumer PG 验证 **独立审批窗口**
> 审查对象：`docs/architecture/remediation/P1_PG_0033_M05_MATERIAL_ANALYSIS_CONSUMER_VERIFICATION.md`（执行窗口候选结论 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`）
> 基线 commit：`b15afacbf284fa656c8ec71c3d6565e970af905e`（验证：闭环日报0032 PostgreSQL幂等计费）
> 日期：2026-08-11
> Source of Truth：独立复现的真实 PG runtime 证据 > 冻结文档 > 执行窗口自述 > 推测

---

## Technical Decision

```text
0033 M05 MATERIAL ANALYSIS CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
material_analysis_execution:{execution_id}:ark_analysis

Same-execution replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct-execution separation:
VERIFIED
```

**APPROVED**。全部 0033 核心 Gate 由独立审批窗口复现成立。M05 架构事实（9000 进程内 consumer，无 HTTP hop，直接 import `record_usage`）经独立核验属实，本轮按实际架构描述与验证，未套用 0032 的 HTTP 模板。

---

## Git / Scope

```text
HEAD = b15afacbf284fa656c8ec71c3d6565e970af905e
git status = 仅审批对象报告未跟踪（执行窗口产物），无业务代码/migration/M07/DB-BL 改动
git diff --stat = 空
```

Scope Gate 确认：
- 业务代码无修改；migration 无修改；M07 Core 无修改；DB-BL 无修改；
- 审批取证脚本写在 worktree 外（`e:/work/tmp/`），经临时容器 `--rm` 挂载执行，未入 worktree（`git status` 干净）；
- 无凭据/dump/snapshot 入库；未开始 0034 / RAG Query 0005 / bootstrap drift 修复；
- 临时取证容器 `--rm` 用后即弃，无残留进程。

---

## Environment / Principal

独立连接 canonical PG 取证（`postgres` 做 catalog inspection，`auto_wechat` 做 consumer runtime 写入与 fixture）：

```text
environment        = LOCAL DEVELOPMENT ONLY
container/service  = auto-wechat-postgres-dev (Up, healthy, 端口 5432)
database           = auto_wechat
backend            = PostgreSQL 16.14
revision           = 0034
physical tables    = 61
database owner     = postgres
current_user(consumer) = auto_wechat  （current_database=auto_wechat）
is_superuser       = False
db CREATE privilege  = False
schema CREATE privilege = False
tables owned by auto_wechat = 0   （61 表全归 postgres）
tables owned by postgres     = 61
alembic_version 对 auto_wechat = SELECT-only
ai_edit_material_analysis_executions / compute_transactions / compute_accounts / ai_edit_materials / ai_edit_material_analyses 对 auto_wechat = INSERT,SELECT,UPDATE,DELETE
```

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

---

## Static Consumer Chain

**关键架构事实（独立核验，非套用 0032 模板）**：M05 是 **9000 进程内 consumer**，不走 9100→9000 HTTP。`_report_analysis_usage` 在 [material_analysis.py:280](../../../app/services/material_analysis.py) `from app.services.compute_service import record_usage` 进程内 import，经 [app/services/compute_service.py](../../../app/services/compute_service.py) 兼容 re-export shim → `apps.compute.services.record_usage`。无 HTTP hop。

这与 0032（9100 `ComputeUsageClient` → 9000 `/internal/compute/usage` HTTP）架构不同。同进程直接服务调用不是证据不足——本轮证明的是真实生产 consumer 路径被执行，而非必须存在 HTTP。

独立定位当前代码（commit `b15afac`）逐节点核验：

```text
Material Analysis execution（BackgroundTask 分析入口）
  → app/services/material_analysis.py:20 analyze_material_async(material_id, presigned_url)
    → :25 from app.database import SessionLocal
    → :36 db.query(AiEditMaterial).filter(id==material_id)
    → :46-51 AiEditMaterialAnalysisExecution(material_id=str(material_id), source_sha256, lifecycle_status="running")
        + :51 db.commit()                        [MA-0 durable before ark：execution_id 先于 Ark 外部副作用持久化]
    → :54 _analyze_via_ark(presigned_url, ark_api_key)   [★ 唯一外部 mock 边界：方舟多模态 Ark SDK]
    → :101 execution.lifecycle_status="completed" + :102 db.commit()   [C1 红线：COMPLETED 先于 usage report]
    → :106-112 _report_analysis_usage(db, merchant_id, prompt_tokens, completion_tokens, execution_id=execution.id)
      → app/services/material_analysis.py:267-271 idempotency_key = f"material_analysis_execution:{execution_id}:ark_analysis"
      → :280 from app.services.compute_service import record_usage   [进程内 import，非 HTTP]
        → app/services/compute_service.py re-export shim → apps.compute.services
          → apps/compute/services.py:615 record_usage()
            → :664-668 查 ComputeMarkupRatio(ai_edit)  → enabled/actual/markup=0
            → :677 calculate_billed_tokens(tokens, 0) = tokens
            → :692-713 INSERT ComputeTransaction(idempotency_key, payload_evidence) + :716 flush
            → :718-727 flush 成功→ get_or_create_account + _write_transaction_balance_only（原子扣费）+ :725 commit
            → :728-769 IntegrityError → rollback → 读已存在行
              → :747 相同 payload_evidence → idempotent_replay（不二次扣费，:756 return）
              → :757 不同 → idempotency_conflict
            → PostgreSQL compute_transactions / compute_accounts
```

**全程未发现 CONTRACT_DRIFT**。

---

## Execution Identity

`execution_id` 来源：`AiEditMaterialAnalysisExecution.id`（[app/models.py:1751](../../../app/models.py)），由 consumer 在 Ark 调用前 durable commit（[material_analysis.py:46-51](../../../app/services/material_analysis.py)）。

- 非时间戳推导（`datetime.now` / `time.time` 不参与 key 构造，经源码核验）；
- 非 request id / retry id / worker attempt——是稳定 PG 持久化业务执行身份；
- billing truth 只归 M07 `ComputeTransaction`（execution 无 `is_billed` / `billing_status` 字段，经列定义核验 + migration 0033 确认）。

---

## Business Event Identity

真实生成代码 [material_analysis.py:267-271](../../../app/services/material_analysis.py)：

```python
idempotency_key = (
    f"material_analysis_execution:{execution_id}:ark_analysis"
    if execution_id is not None
    else None
)
```

- f-string 位置：`_report_analysis_usage` 内部；
- `execution_id` 来源：`execution.id`（前置持久化的 PG 对象）；
- stage 固定：`ark_analysis`；
- `execution_id=None` 走旧兼容路径（`record_usage` idempotency_key=None → warning 裸扣），正式 consumer 路径 `execution_id` 恒非空。

```text
material_analysis_execution:{execution_id}:ark_analysis
```

与 `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #8 冻结 contract 一致，无 drift。

### Same Execution 真正含义

执行窗口报告事实经核验属实：`analyze_material_async` 每次重新分析会创建新 execution。因此 same material + same input 不一定是同一 Business Event。真正幂等命题是：

```text
same execution_id + same stage=ark_analysis → one compute charge
```

replay 场景必须复用同一 `E-A execution.id`，而非重新调用入口创建 `E-A2`。本审批 replay 通过同一 `execution.id` 重进真实 consumer usage-report seam `_report_analysis_usage`，复用同一持久化 row（见下）。

### Replay 路径合法性

`_report_analysis_usage` 是代码中的真实 consumer retry/re-report seam（对应 crash 后 usage report 重试场景，即 `M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP` 关注的恢复路径）。核验：

- identity 仍由该 consumer 函数内部 f-string 自然重新生成（非手工构造 idempotency key）；
- execution 对象/ID 真实来自持久化 PG 对象（同一 `execution.id`）；
- 不直接手工构造 idempotency key；
- 不直接调用 `record_usage` 绕过 M05 consumer 层（经 `_report_analysis_usage` → `record_usage`）。

---

## Mock Boundary

```text
mocked   = _analyze_via_ark  （方舟多模态 Ark SDK 外部边界，唯一 mock）
not_mocked = M05 orchestration（analyze_material_async）
           / execution 持久化（AiEditMaterialAnalysisExecution durable commit）
           / execution.id
           / _report_analysis_usage
           / Business Event Identity 生成
           / usage extraction（prompt_tokens + completion_tokens → total）
           / record_usage（进程内 import，非 mock）
           / 9000 compute service（apps.compute.services.record_usage）
           / PostgreSQL uniqueness（uk_compute_transactions_merchant_idempotency）
           / compute account balance
```

关键 compute 路径未被 mock——本轮不是 unit/integration test，达到 `PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## Schema Preconditions

canonical PG@0034 独立 catalog inspection：

| 对象 | 核验 |
|---|---|
| `ai_edit_material_analysis_executions` 表 | ✅ EXISTS（6 列: id, material_id, source_sha256, lifecycle_status, created_at, completed_at）|
| `id` PK `ai_edit_material_analysis_executions_pkey` | ✅ |
| `idx_ai_edit_material_analysis_executions_material` 索引（material_id）| ✅ |
| `ck_ai_edit_material_analysis_executions_status` CHECK（lifecycle_status ∈ running/completed/failed）| ✅ |
| NOT NULL 列 | ✅ id, material_id, source_sha256, lifecycle_status, created_at（completed_at nullable）|
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)` | ✅ EXISTS（驱动 IntegrityError 幂等路径，非 Python try/except）|
| `compute_transactions.idempotency_key` / `payload_evidence` 列 | ✅ |
| `compute_markup_ratios` 行 `ai_edit` | ✅ enabled=true / consumption_mode=actual / markup_basis_points=0（→ `calculate_billed_tokens(total,0)=total`，真实代码确认）|
| `compute_transactions_id_seq` / `ai_edit_material_analysis_executions_id_seq` 序列 | ✅ |
| application role 对相关表 INSERT/SELECT/UPDATE/DELETE | ✅ |

migration 0033：revision=`0033`，down_revision=`0032`，create_date=2026-08-08。新建 `ai_edit_material_analysis_executions` 表（6 列 + PK + CHECK + material 索引），不激活 dormant `AiEditMaterialProcess` 五阶段表。revision 仍为 0034（0033 在 head 链中，0030→0032→0033→0034 线性单链）。

```text
SCHEMA_PREREQUISITE = PASS（≠ PG_VERIFIED，仅 precondition）
```

---

## E-A First Execution

独立受控 fixture（不复用执行窗口 `m_d33_verify`，审批窗口独立商户 `m_d33_approve`，synthetic material SHA `d33approve_sha_aaa/bbb`）：

```text
matA_id=5 / matB_id=6（synthetic，非真实客户素材）
baseline: ai_edit_material_analysis_executions=0, compute_accounts=0, compute_transactions=0
```

从真实 M05 consumer 入口 `analyze_material_async(matA_id, "https://test.invalid/d33-approve-ea")` 执行（mock Ark 返回 120+80 token）：

```text
E-A execution_id = 4 （ai_edit_material_analysis_executions.id，真实 PG 序列持久化，非硬编码）
lifecycle_status = completed
identity = material_analysis_execution:4:ark_analysis（consumer 自然生成，非手工构造 key）
```

PG 直查证据：

```text
transaction count (identity=material_analysis_execution:4:ark_analysis) = 1   ✓
id=14 | idempotency_key=material_analysis_execution:4:ark_analysis | transaction_type=consume
delta_tokens=-200 | balance_after_tokens=-200 | capability_key=ai_edit
model=d33-approve-mock-ark | llm_call_stage=NULL | actual_tokens=200
prompt_tokens=120 | completion_tokens=80 | usage_measurement_method=provider_tokens | payload_evidence IS NOT NULL
```

Balance（consume delta 为负，markup=0 → billed=actual=200；`negative_balance` 为告警非失败）：

```text
balance_before = 0   （account 首次建账）
delta          = -200 （billed_tokens=calculate_billed_tokens(200, 0)=200，由真实代码推导，非硬编码期望）
balance_after  = -200  ✓
```

---

## E-A Same-Execution Replay

对**同一 execution_id=4、同一 stage=ark_analysis**，再次从真实 consumer usage-report seam `_report_analysis_usage(db, merchant_id, prompt_tokens=120, completion_tokens=80, execution_id=4)` 进入（identity 由函数内部 f-string 自然重新生成，非手工构造 key，非直接调 `record_usage`）：

```text
identity 自然重新生成：material_analysis_execution:4:ark_analysis
9000 record_usage：INSERT 触发 uk_compute_transactions_merchant_idempotency 唯一冲突 → IntegrityError → rollback → idempotent_replay 分支
```

PG 权威证据：

```text
transaction count (identity=material_analysis_execution:4:ark_analysis) = 1   （未产生第 2 行）✓
balance_after_replay = -200 = balance_after_first   ✓
replay_reuses_same_execution_id = True   （复用同一持久化 execution.id，非新建 execution）
```

```text
NO_DOUBLE_CHARGE_VERIFIED
```

---

## E-B Distinct Execution

创建另一 synthetic material `mat-B`，从真实 consumer 入口 `analyze_material_async(matB_id, "https://test.invalid/d33-approve-eb")` 执行（mock Ark 相同 token）：

```text
E-B execution_id = 5 （不同 execution row）
identity = material_analysis_execution:5:ark_analysis
```

PG 证据：

```text
transaction count (identity=material_analysis_execution:5:ark_analysis) = 1   ✓
id=16 | delta_tokens=-200 | balance_after_tokens=-400 | payload_evidence IS NOT NULL
```

```text
identity(E-A) = material_analysis_execution:4:ark_analysis  !=  material_analysis_execution:5:ark_analysis = identity(E-B)
distinct_identities = 2
total_txns = 2
balance 推进：0 →(E-A first)→ -200 →(E-A replay, 不变)→ -200 →(E-B)→ -400 ✓
```

```text
same execution → dedupe；different execution → independent charge   VERIFIED
```

---

## Transaction / Balance Evidence

PG 直查（auto_wechat 应用角色只读）全部 consume txns for `m_d33_approve`（清理前）：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | pt | ct | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|---|---|
| 14 | `material_analysis_execution:4:ark_analysis` | consume | -200 | -200 | ai_edit | d33-approve-mock-ark | NULL | 200 | 120 | 80 | provider_tokens | NOT NULL |
| 16 | `material_analysis_execution:5:ark_analysis` | consume | -200 | -400 | ai_edit | d33-approve-mock-ark | NULL | 200 | 120 | 80 | provider_tokens | NOT NULL |

```text
account: merchant_id=m_d33_approve / balance_tokens=-400
final balance = initial(0) + legitimate E-A delta(-200) + legitimate E-B delta(-200) = -400 ✓
E-A replay does not contribute another delta ✓
2 distinct identities / 2 legitimate compute charges / replay 不二次计费
```

---

## Sequence Gap Classification

```text
txn_ids = [14, 16]   （id=15 缺失）
```

明确分类：

```text
SEQUENCE ID GAP = SUPPLEMENTARY ONLY
```

id=15 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 `idempotent_replay` 分支。

```text
gap != idempotency proof
```

PostgreSQL sequence 正常情况下本就允许 gap。正式证明仍是：`same identity` + `row count remains 1` + `balance unchanged`（均已满足）。

---

## Execution Persistence

E-A/E-B 对应 Material Analysis Execution 在 PG 中真实持久化并被 replay 复用：

| id | material_id | source_sha256 | lifecycle_status | created_at | completed_at | merchant_id |
|----|---|---|---|---|---|---|
| 4 | '5' | d33approve_sha_aaa | completed | NOT NULL | NULL | m_d33_approve |
| 5 | '6' | d33approve_sha_bbb | completed | NOT NULL | NULL | m_d33_approve |

- execution `id` 持久存在，`_report_analysis_usage` 复用同一 `execution.id` 作 identity 来源，`replay_reuses_same_execution_id=True`；
- `lifecycle_status=completed` 稳定持久；
- merchant/tenant ownership：`ai_edit_material_analysis_executions` 表本身无 `merchant_id`/`tenant_id` 列（schema 事实），ownership 通过 `material_id` → `AiEditMaterial.merchant_id` 间接关联（consumer 传入 `material.merchant_id` 给 `_report_analysis_usage`）。

```text
Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）✓
```

---

## completed_at Classification

```text
completed_at currently not populated = OUT_OF_SCOPE OBSERVATION
```

`completed_at` 列当前未被 consumer 填充（[material_analysis.py:101](../../../app/services/material_analysis.py) 只设 `lifecycle_status="completed"`，未填充 `completed_at` 列）。属 M05 consumer 代码现状。

- execution identity 稳定（基于 `execution.id`，非 `completed_at`）；
- lifecycle/status 足以支持本测试（`completed` 持久）；
- compute 幂等不依赖 `completed_at`。

```text
不阻断 0033，不在审批窗口修代码。未发现它破坏业务事件身份或计费 contract。
```

---

## Recovery Gap Classification

```text
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP:
UNCHANGED / OUT_OF_P1 RELIABILITY GAP
```

本轮实际验证说明：usage-report retry 若再次触发同一 execution/stage 的计费上报，compute 幂等层能够抑制 double charge（`NO_DOUBLE_CHARGE_VERIFIED`）。

这不等于证明：crash 后一定会自动恢复 usage report。

```text
Recovery orchestration gap: UNCHANGED / OUT_OF_P1
Idempotent replay safety: VERIFIED
```

`_report_analysis_usage` 内部 `except Exception` catch（[material_analysis.py:295-296](../../../app/services/material_analysis.py)）：usage report 失败不抛出、不降级 execution COMPLETED、不重跑 Ark（C1 红线）。这是设计行为，非 recovery gap 缺陷。本轮未观察到 recovery gap 导致 `same business event → double charge`，故不升级为 P1 blocker。

---

## Concurrency Boundary

```text
本轮不是 Final PostgreSQL Concurrent Closure Gate
```

未执行全局 concurrent closure。txn id gap（14,16，缺 15）为 replay INSERT-rollback 的法证副证，非正式 concurrent test。`lack of concurrent test` 不阻断 0033。consumer-specific concurrency evidence：无额外，`SUPPLEMENTARY` 即可。

---

## Application Role Runtime Evidence

核心 consumer 持久化全程来自 `auto_wechat`：

```text
current_user=auto_wechat（runtime principal 直查）
consumer execution 写入：analyze_material_async 内部 SessionLocal（DATABASE_URL=auto_wechat 角色）→ PG
consumer 计费写入：_report_analysis_usage → record_usage（DATABASE_URL=auto_wechat 角色）→ PG
fixture 写入 + 证据读取：应用角色直连 auto_wechat
superuser-as-consumer 替代：无（postgres 仅用于 catalog inspection）
```

```text
postgres PASS / auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）
```

---

## Cleanup

审批 fixture 经 `auto_wechat` 应用角色事务内清理：

```text
DELETE compute_transactions WHERE merchant_id='m_d33_approve'                    → 2
DELETE compute_accounts WHERE merchant_id='m_d33_approve'                       → 1
DELETE ai_edit_material_analysis_executions WHERE material_id IN (SELECT...)    → 2
DELETE ai_edit_material_analyses WHERE material_id IN (SELECT...)              → 2
DELETE ai_edit_materials WHERE merchant_id='m_d33_approve'                     → 2
```

residual 检查（全 0，clean baseline 恢复）：

```text
compute_txns(m_d33_approve)         = 0
compute_accounts(m_d33_approve)     = 0
ai_edit_material_analysis_executions(m_d33_approve) = 0
ai_edit_materials(m_d33_approve)    = 0
total compute_transactions          = 0
total compute_accounts             = 0
total ai_edit_material_analysis_executions = 0
total ai_edit_materials            = 0
```

全局 M05 identity 完整性：`GLOBAL_M05_TXNS=0`、`GLOBAL_M05_NULL_EMPTY=0`、`GLOBAL_ALL_TXNS=0`、`RESIDUAL_APPROVE_MERCHANT=0`。

DB-BL 完整性未变：`revision=0034 / tables=61`。临时取证容器 `--rm` 用后即弃，脚本在 worktree 外，`git status` 干净。

```text
residual test data = 0
```

---

## D33-* Verdict

| Gate | 验证内容 | 结论 | 证据等级 |
|---|---|---|---|
| D33-0 | Git / environment | ✅ PASS | HEAD=b15afac / clean；LOCAL DEV，canonical PG@0034，PG 16.14，db_owner=postgres，61 表 |
| D33-1 | Application principal | ✅ PASS | current_user=auto_wechat；consumer 写入经 auto_wechat 角色；postgres 仅 catalog |
| D33-2 | Static consumer chain | ✅ PASS | CODE_VERIFIED；M05 进程内调 record_usage（非 HTTP，按实际架构描述，未套用 0032 模板）|
| D33-3 | Business Event Identity | ✅ PASS | `material_analysis_execution:{execution_id}:ark_analysis`，来自稳定 execution.id，无 drift |
| D33-4 | Schema prerequisites | ✅ PASS | STATIC_SCHEMA_VERIFIED；0033 表/列/约束/索引 + compute 幂等唯一约束 + ai_edit markup ratio |
| D33-5 | Mock boundary | ✅ PASS | 仅 mock Ark 外部多模态；consumer/identity/usage/compute/PG 幂等全真实 |
| D33-6 | First execution（E-A）| ✅ PASS | PG_RUNTIME_VERIFIED；E-A(id=4) → 1 txn(id=14)，identity 一致，balance 0→-200，payload_evidence NOT NULL |
| D33-7 | Same-execution replay | ✅ PASS | PG_RUNTIME_VERIFIED；E-A replay → txn count 仍 1，balance 不变(-200)，复用同一 execution.id |
| D33-8 | Distinct-execution separation | ✅ PASS | PG_RUNTIME_VERIFIED；E-B(id=5) → 1 独立 txn(id=16)，2 distinct identities，无 collision |
| D33-9 | Non-null identity | ✅ PASS | 0 null/empty idempotency_key（局部 + 全局 M05）|
| D33-10 | Execution identity persistence | ✅ PASS | 2 行 PG 持久，lifecycle=completed，replay 复用同一 execution.id |
| D33-11 | PG transaction/balance evidence | ✅ PASS | 2 txns(id 14,16)，delta=-200 each，balance=-400=0+(-200)+(-200)，replay 不贡献 delta |
| D33-12 | Cleanup / residual | ✅ PASS | residual=0，DB-BL 不变(0034/61)，worktree clean |

`D33-6 / D33-7 / D33-8 / D33-11` 均为真实 `PG_RUNTIME_VERIFIED`（非 unit test）。

---

## Evidence Levels

```text
正式 0033 通过所需：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED  → 均已满足
辅助证据：SUPPLEMENTARY_RUNTIME_EVIDENCE（id gap / payload_evidence NOT NULL / idempotent replay 日志路径）
静态证据：CODE_VERIFIED / STATIC_SCHEMA_VERIFIED
```

---

## 0033 Final Status

```text
0033 M05 MATERIAL ANALYSIS CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
material_analysis_execution:{execution_id}:ark_analysis

Same-execution replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct-execution separation:
VERIFIED
```

---

## 0034 Authorization

```text
0034 PREVIEW:
AUTHORIZED_TO_START_PG_VERIFICATION
```

注意：**不是** `0034 PG_VERIFIED`。0034 须独立完成其 consumer PG verification 后再行审批。

---

## P1 Remaining

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

0033 通过不改变 P1 整体状态。至少仍剩：

```text
0034 Preview PG verification（已 AUTHORIZED_TO_START）
RAG Query 0005 PG verification（PENDING_PG_VERIFICATION，BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT）
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
Global Active None Audit
Final PostgreSQL Concurrent Closure Gate
```

既有 OUT_OF_P1 reliability gaps（含 `M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP`）继续保持原分类。

---

## RB-10

```text
RB-10 CLEANUP = NOT AUTHORIZED
```

legacy backup + dump 保留。

---

## Commit Authorization

0033 审批通过，授权执行窗口：

1. 将 0033 verification report 状态从 `PENDING_APPROVAL` 同步为正式批准状态；
2. 新增本审批报告；
3. 精确同步 current-facing 治理状态（CLAUDE.md 当前治理状态）0033 状态；
4. 提交一个独立 0033 verification checkpoint。

该 commit 不得包含：0034 验证 / bootstrap owner drift 修复 / M05 业务修复 / completed_at 修复 / migration / M07 Core。

建议 commit message：`验证：闭环M05素材分析0033 PostgreSQL幂等计费`（实际按仓库规范）。

---

## 结论

0033 M05 Material Analysis Consumer 在真实 PostgreSQL + `auto_wechat` Application Principal 下：从真实 consumer 入口产生批准的 Business Event Identity `material_analysis_execution:{execution_id}:ark_analysis`，经真实 9000 进程内 Compute Core（record_usage）持久化；同一 execution 重放不产生第二次扣费，不同 execution 独立计费。M05 进程内 consumer 架构（无 HTTP hop）经独立核验属实。全部门限独立复现通过。

**审批完成，停止。不自行开始 0034。**
