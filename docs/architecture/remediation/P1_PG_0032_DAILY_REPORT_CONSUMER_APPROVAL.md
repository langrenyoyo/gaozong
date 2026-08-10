# P1-PG-0032 — Daily Report Consumer PostgreSQL Verification 独立审批报告

> 窗口：P1-PG-0032 Daily Report Consumer PG 验证 **独立审批窗口**
> 审查对象：`docs/architecture/remediation/P1_PG_0032_DAILY_REPORT_CONSUMER_VERIFICATION.md`（执行窗口候选结论 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`）
> 基线 commit：`dbf8005a444488e2a6457476aed941e3272b2347`（修复：闭环本地PostgreSQL应用角色权限）
> 日期：2026-08-10
> Source of Truth：独立复现的真实 PG runtime 证据 > 冻结文档 > 执行窗口自述 > 推测

---

## Technical Decision

```text
0032 DAILY REPORT CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
daily_report_generation:{generation_id}:summary

Same-event replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct-event separation:
VERIFIED
```

**APPROVED**。全部 0032 核心 Gate 由独立审批窗口复现成立；执行窗口报告措辞有一处需修正（见下"措辞修正"），不影响 0032 结论，故为 `APPROVED`（无 `WITH_CORRECTIONS` 的实质偏差，仅记录修正项）。

---

## Git / Scope

```text
HEAD = dbf8005a444488e2a6457476aed941e3272b2347
git status = 仅审批对象报告未跟踪（执行窗口产物），无业务代码/migration/M07/DB-BL 改动
git diff --stat = 空
```

Scope Gate 确认：
- 业务代码无修改；migration 无修改；M07 Core 无修改；DB-BL 无修改；
- 审批取证脚本写在 worktree 外（`e:/work/tmp/`），经临时容器 stdin/挂载执行，未入 worktree（`git status` 干净）；
- 无凭据/dump/snapshot 入库；未开始 0033 / 0034 / RAG Query 0005；
- 临时取证容器 `--rm` 用后即弃，无残留进程。

---

## Environment / Principal

独立连接 canonical PG 取证（以 `postgres` 做 catalog inspection，以 `auto_wechat` 做 consumer runtime 写入与 fixture）：

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
compute_transactions / compute_accounts / daily_report_generations 对 auto_wechat = INSERT,SELECT,UPDATE,DELETE
sequences granted to auto_wechat = 60
```

9000 启动日志独立确认 `db_schema stage=startup_skip_create_all backend=postgresql`（`ensure_runtime_schema` PG 分支不调 create_all，满足 CLAUDE.md 硬约束 #2）。

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

`/ready`（应用角色）HTTP 200：`backend=postgresql / db_connect=pass / database_name=auto_wechat / alembic_revision=0034 / critical_tables(douyin_leads,sales_staff)=pass`。

---

## Independent Static Call Chain

不复制执行窗口链路，独立定位当前代码（commit `dbf8005`）确认：

```text
9000 generate_one()                         app/services/daily_report_job_service.py:362
  → _claim_generating(db, job)              :374 → 创建 DailyReportGeneration 行（:246-256）→ 返回 generation.id
  → build_daily_report(..., report_generation_id=generation_id)   :379-384
    → app/services/daily_report_service.py:926 build_daily_report()
      → payload["report_generation_id"] = report_generation_id    :560
      → summary_client.summarize_daily_sales_feedback(payload)    :577   [9000→9100]
        → 9100 apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:177 summarize_daily_sales_feedback()
          → :191 OpenAICompatibleClient().chat(messages)          [LLM — 唯一 mock 边界]
          → :207 _report_usage(..., report_generation_id=...)      [计费在 _parse_summary_text 之前，独立于摘要解析]
            → :152-156 idempotency_key = f"daily_report_generation:{report_generation_id}:summary"
            → :159 ComputeUsageClient().report_usage(idempotency_key=...)
              → apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 report_usage()
                → USAGE_PATH="/internal/compute/usage"（:172）+ base_url=os.environ["AUTO_WECHAT_9000_BASE_URL"]（:163）
                → :262-270 POST {base_url}/internal/compute/usage（payload 含 idempotency_key，X-Internal-Token 校验）
                  → app/routers/compute.py:458 internal_router.post("/compute/usage")  [前缀 /internal → /internal/compute/usage]
                    → :467 compute_service.record_usage(idempotency_key=payload.idempotency_key)
                      → apps/compute/services.py:615 record_usage()
                        → :692-713 INSERT ComputeTransaction(idempotency_key, payload_evidence)
                        → :716 flush → :718-725 原子扣费（created，单次 commit）
                        → :728-769 IntegrityError → rollback → :747 相同 payload_evidence → idempotent_replay（不二次扣费）
                        → PostgreSQL compute_transactions / compute_accounts
```

**Business Event Identity** 真实生成位置 [daily_report_summary_service.py:152-156](../../../apps/xg_douyin_ai_cs/services/daily_report_summary_service.py)：

```python
idempotency_key = (
    f"daily_report_generation:{report_generation_id}:summary"
    if report_generation_id is not None
    else None
)
```

- `generation_id` 来源：`DailyReportGeneration.id`（[app/models.py:1337](../../../app/models.py)），由 9000 `_claim_generating` 持久化后透传到 9100；
- `summary` stage 固定；不含随机值；不含时间戳（`datetime.now`/`time.time` 不参与 key 构造，经源码核验）；不含 request attempt / HTTP 重试次数；
- billing truth 归 M07 `ComputeTransaction`（`DailyReportGeneration` 无 `is_billed` 字段，经列定义核验）。

```text
NO CONTRACT_DRIFT — 与冻结 contract 完全一致
```

---

## Mock Boundary

```text
mocked   = OpenAICompatibleClient.chat  （外部非确定性 LLM 边界，唯一 mock）
not_mocked = summarize_daily_sales_feedback orchestration
           / _report_usage
           / Business Event Identity 生成
           / ComputeUsageClient.report_usage
           / 9000 /internal/compute/usage（真实 uvicorn HTTP 服务 + 真实 route）
           / record_usage
           / PostgreSQL unique 约束 / 事务 / 余额逻辑
```

consumer orchestration / identity / HTTP compute / PG 全部真实运行，证据等级为 `PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`（非 unit test）。consumer 与 9000 同容器但经真实 loopback HTTP（urllib → TCP → uvicorn → FastAPI → route → record_usage），非 TestClient 旁路。

---

## Schema Preconditions

canonical PG@0034 独立 catalog inspection：

| 对象 | 核验 |
|---|---|
| `daily_report_generations` 表 | ✅ EXISTS（cols: id, job_id, lifecycle_status, created_at）|
| `daily_report_generations` PK `daily_report_generations_pkey` | ✅ |
| `idx_daily_report_generations_job` 索引 | ✅ |
| `ck_daily_report_generations_status` CHECK | ✅ |
| `daily_report_generations_job_id_fkey` FK→daily_report_jobs | ✅ |
| `daily_report_jobs.current_generation_id` 列 | ✅ EXISTS |
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)` | ✅ EXISTS（驱动 IntegrityError 幂等路径，非 Python try/except）|
| `compute_transactions.idempotency_key` / `payload_evidence` 列 | ✅ |
| `compute_markup_ratios` 行 `wechat-assistant` | ✅ enabled=true / consumption_mode=actual / markup_basis_points=0（→ `calculate_billed_tokens(15,0)=15`，真实代码确认，非假设）|
| `compute_transactions_id_seq` 序列 | ✅ |
| application role 对相关表 INSERT/SELECT/UPDATE/DELETE | ✅ |

---

## G-A First Execution

独立受控 fixture（不复用执行窗口 `m_d32_verify`，审批窗口独立商户 `m_d32_approve`）：

```text
job_id=3 / G_A=5（daily_report_generations.id，真实 PG 序列持久化，非硬编码）
baseline: compute_accounts(m_d32_approve)=0, compute_transactions(m_d32_approve)=0
identity = daily_report_generation:5:summary
```

从真实 consumer 入口 `summarize_daily_sales_feedback(DailySalesSummaryRequest(merchant_id=m_d32_approve, report_day=2026-08-10, summaries=[...], report_generation_id=5))` 执行：

```text
consumer 返回：llm_used=True / model=d32-approve-mock-llm / fallback=None / summary_present=True / daily_summary stage=ok
HTTP：9100 consumer → ComputeUsageClient.report_usage → 9000 /internal/compute/usage（真实 HTTP 200，compute_usage stage=reported tokens=15）
```

PG 直查证据：

```text
transaction count (identity=daily_report_generation:5:summary) = 1   ✓
id=7 | idempotency_key=daily_report_generation:5:summary | transaction_type=consume
delta_tokens=-15 | balance_after_tokens=-15 | capability_key=wechat-assistant
model=d32-approve-mock-llm | llm_call_stage=primary | actual_tokens=15
usage_measurement_method=provider_tokens | payload_evidence IS NOT NULL
```

Balance（compute contract：consume delta 为负，一期不拦截余额允许负；`negative_balance` 为告警非失败）：

```text
balance_before = 0   （account 首次建账）
delta          = -15 （billed_tokens=calculate_billed_tokens(15,0)=15）
balance_after  = -15  ✓
```

---

## G-A Replay

同一 `generation_id=5`、同一 `summary` stage，再次从真实 consumer 入口执行（非人工直接调 `record_usage`，非手工 POST duplicate）：

```text
consumer 返回：llm_used=True（consumer 侧无幂等感知，始终调 _report_usage → 真实 HTTP 9000）
9000 record_usage：INSERT 触发 uk_compute_transactions_merchant_idempotency 唯一冲突 → IntegrityError → rollback → idempotent_replay 分支
运行日志：compute_idempotency stage=replay merchant_id=m_d32_approve key=daily_report_generation:5:summary txn_id=7
```

PG 权威证据（不靠 HTTP 200）：

```text
transaction count (identity=daily_report_generation:5:summary) = 1   （未产生第 2 行）✓
balance_after_replay = -15 = balance_after_first_execution   ✓
```

```text
NO_DOUBLE_CHARGE_VERIFIED
```

---

## G-B Distinct Event

创建不同 `generation_id=6`，同一 `summary` stage，从真实 consumer 入口执行：

```text
identity = daily_report_generation:6:summary
transaction count (identity=daily_report_generation:6:summary) = 1   ✓
id=9 | delta_tokens=-15 | balance_after_tokens=-30 | payload_evidence IS NOT NULL
```

```text
identity(G-A) = daily_report_generation:5:summary  !=  daily_report_generation:6:summary = identity(G-B)
distinct_identities = 2
total_txns = 2
balance 推进：0 →(G-A first)→ -15 →(G-A replay, 不变)→ -15 →(G-B)→ -30 ✓
```

```text
same event → dedupe；different event → independent charge   VERIFIED
```

---

## Transaction / Balance Evidence

PG 直查（auto_wechat 应用角色只读）全部 consume txns for `m_d32_approve`（清理前）：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 7 | `daily_report_generation:5:summary` | consume | -15 | -15 | wechat-assistant | d32-approve-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 9 | `daily_report_generation:6:summary` | consume | -15 | -30 | wechat-assistant | d32-approve-mock-llm | primary | 15 | provider_tokens | NOT NULL |

```text
account: merchant_id=m_d32_approve / balance_tokens=-30
```

---

## Identity Evidence

```text
按 identity 计数：
  daily_report_generation:5:summary → 1
  daily_report_generation:6:summary → 1
G-A replay 未产生第二行；G-B 独立一行；identity 精确匹配冻结 contract。
```

Non-null identity（§十七，本轮 Daily Report charge transaction 范围）：

```text
compute_transactions WHERE merchant_id='m_d32_approve'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0   ✓
全局 daily_report_generation:% identity NULL/EMPTY count = 0   ✓
```

`payload_evidence` 实际存在（NOT NULL），作为辅助审计证据；未升级为未批准 closure requirement（compute contract 未规定其为 0032 硬前提）。

---

## Sequence-gap Evidence Classification

```text
txn_ids = [7, 9]   （id=8 缺失）
```

明确分类：

```text
ID GAP != idempotency proof   （SUPPLEMENTARY ONLY）
```

id=8 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 `idempotent_replay` 分支（`compute_idempotency stage=replay ... txn_id=7` 日志佐证）。

正式判定基于：`same identity row count = 1` + `balance unchanged` + `same consumer-generated identity`。id gap 仅作 `SUPPLEMENTARY_RUNTIME_EVIDENCE`，不列为硬门禁。

---

## Application Role Hard Gate

核心 consumer 写入链全程由 `auto_wechat` Application Principal 执行：

```text
postgres catalog inspection → PASS
auto_wechat consumer runtime 写入 → PASS（record_usage 经 DATABASE_URL=auto_wechat 角色 → PG）
superuser-as-consumer 替代 → 无
```

若 `postgres PASS / auto_wechat FAIL` 则 0032 FAIL。本审批为 `auto_wechat PASS`。

---

## Cleanup

审批 fixture 经 `auto_wechat` 应用角色事务内清理：

```text
DELETE compute_transactions WHERE merchant_id='m_d32_approve'   → 2
DELETE compute_accounts WHERE merchant_id='m_d32_approve'       → 1
DELETE daily_report_generations WHERE job_id=3                  → 2
DELETE daily_report_jobs WHERE id=3                             → 1
```

residual 检查（全 0，clean baseline 恢复）：

```text
compute_txns(m_d32_approve)        = 0
compute_accounts(m_d32_approve)    = 0
daily_report_generations(m_d32_approve) = 0
daily_report_jobs(m_d32_approve)   = 0
total compute_transactions         = 0   （执行窗口 + 审批窗口均已清理）
total compute_accounts            = 0
total daily_report_generations     = 0
total daily_report_jobs            = 0
```

DB-BL 完整性未变：`revision=0034 / tables=61`。临时取证容器 `--rm` 用后即弃，脚本在 worktree 外，`git status` 干净。

```text
residual test data = 0
```

---

## D32-* Verdict

| Gate | 验证内容 | 结论 | 证据等级 |
|---|---|---|---|
| D32-0 | Environment / principal | ✅ PASS | PG_RUNTIME + APPLICATION_ROLE |
| D32-1 | Consumer call chain | ✅ PASS | CODE_VERIFIED（无 CONTRACT_DRIFT）|
| D32-2 | Schema prerequisites | ✅ PASS | STATIC_SCHEMA_VERIFIED |
| D32-3 | Application-role connection | ✅ PASS | APPLICATION_ROLE_RUNTIME_VERIFIED |
| D32-4 | First execution | ✅ PASS | PG_RUNTIME_VERIFIED |
| D32-5 | Same-event replay | ✅ PASS | PG_RUNTIME_VERIFIED（NO_DOUBLE_CHARGE_VERIFIED）|
| D32-6 | Distinct-event separation | ✅ PASS | PG_RUNTIME_VERIFIED |
| D32-7 | Non-null identity | ✅ PASS | PG_RUNTIME_VERIFIED |
| D32-8 | PostgreSQL transaction/balance evidence | ✅ PASS | PG_RUNTIME_VERIFIED |
| D32-9 | Cleanup / residual | ✅ PASS | residual=0 / DB-BL 不变（0034/61）|

`D32-4 / D32-5 / D32-6 / D32-8` 均为真实 `PG_RUNTIME_VERIFIED`（非 unit test）。

---

## Evidence Levels

```text
正式 0032 通过所需：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED  → 均已满足
辅助证据：SUPPLEMENTARY_RUNTIME_EVIDENCE（id gap / payload_evidence NOT NULL）
静态证据：CODE_VERIFIED / STATIC_SCHEMA_VERIFIED
```

---

## 措辞修正（记录，不影响结论）

执行窗口报告 §7 "B. Compute Transaction = exactly 1" 将首个 txn 记为 `id=1`、§10 表记 `id=1,3`，这是执行窗口 fixture 的真实 id（其 fixture 在 daily_report_generations.id=1,2、compute_transactions.id=1,3）。本审批窗口使用独立 fixture（id=5,6 / txn id=7,9），id 不同但幂等契约与行为完全一致。执行窗口报告的 id 值是其自身 fixture 的事实，不构成错误；本审批仅记录"id 值随 fixture 不同而不同，不作为契约结论"。

执行窗口报告结论 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL` 经本审批独立复现后，正式升格为 `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## 0032 Final Status

```text
0032 DAILY REPORT CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
daily_report_generation:{generation_id}:summary

Same-event replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct-event separation:
VERIFIED
```

---

## 0033 Authorization

```text
0033 M05 MATERIAL ANALYSIS:
AUTHORIZED_TO_START_PG_VERIFICATION
```

注意：**不是** `0033 PG_VERIFIED`。0033 须独立完成其 consumer PG verification 后再行审批。

---

## P1 Remaining Work

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

0032 通过不改变 P1 整体状态。至少仍剩：

```text
0033 M05 PG verification（已 AUTHORIZED_TO_START）
0034 Preview PG verification（仍 UNBLOCKED_FOR_PG_VERIFICATION）
RAG Query 0005 PG verification（PENDING_PG_VERIFICATION，BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT）
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
Global Active None Audit
Final PostgreSQL Concurrent Closure Gate
```

既有 OUT_OF_P1 reliability gaps（DAILY_REPORT/TRAINING/RAG_INGEST_RUN/RAG_INGEST_REQUEST/M05_ANALYSIS_USAGE_REPORT/PREVIEW_REQUEST/RAG_QUERY_REQUEST）继续保持原分类。

---

## Bootstrap Drift

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN
```

`docker/postgres/init/001_create_databases.sql` 仍 `OWNER auto_wechat`（本审批未修改该文件）。当前运行库 COMPLIANT（DB owner=postgres），fresh bootstrap NOT YET COMPLIANT。

```text
DOES NOT BLOCK 0032
```

继续要求在 P1 final technical closure 前关闭。

---

## Concurrency / Recovery Boundary

- 本轮 **不是** `Final PostgreSQL Concurrent Closure Gate`；未执行全局高并发 close（`lack of concurrent test` 不阻断 0032）。
- `DAILY_REPORT_REQUEST_RECOVERY_GAP` 保持 `OUT_OF_P1`；本轮未验证 crash/request/worker 重启恢复——除非其直接导致 same business event → duplicate charge，否则保持原分类。本轮范围内未观察到新 reliability 问题。

---

## RB-10

```text
RB-10 CLEANUP = NOT AUTHORIZED
```

legacy backup + dump 保留。

---

## Commit Authorization

0032 审批通过，授权执行窗口：

1. 将 0032 verification report 状态从 `PENDING_APPROVAL` 同步为正式批准状态；
2. 新增本审批报告；
3. 精确同步 current-facing 治理文档（CLAUDE.md 当前治理状态）0032 状态；
4. 提交一个独立 0032 verification checkpoint。

该 commit 不得包含：0033 验证 / bootstrap drift 修复 / consumer 业务修改 / migration / M07 Core。

建议 commit message：`验证：闭环日报0032 PostgreSQL幂等计费`（实际按仓库规范）。

---

## 结论

0032 Daily Report Consumer 在真实 PostgreSQL + `auto_wechat` Application Principal 下：从真实 consumer 入口产生批准的 Business Event Identity `daily_report_generation:{generation_id}:summary`，经真实 9000 Compute Core 持久化；同一 generation 重放不产生第二次扣费，不同 generation 独立计费。全部门限独立复现通过。

**审批完成，停止。不自行开始 0033。**
