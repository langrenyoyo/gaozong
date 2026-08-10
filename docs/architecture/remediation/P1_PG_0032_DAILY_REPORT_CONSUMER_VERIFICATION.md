# P1-PG-0032 — Daily Report Consumer PostgreSQL 验证报告

> 任务：`P1-PG-0032 — Daily Report Consumer PostgreSQL Verification`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 consumer-level PG verification
> 基线 commit：`dbf8005`（修复：闭环本地PostgreSQL应用角色权限）
> 日期：2026-08-10
> 窗口：P1-PG-0032 Daily Report Consumer PG 验证执行/验证窗口
> Source of Truth：真实 PG runtime 证据（canonical PG@0034，应用角色 `auto_wechat`，真实 HTTP consumer 路径） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| D32-0 Environment / principal | ✅ PASS |
| D32-1 Consumer call chain | ✅ PASS（无 CONTRACT_DRIFT）|
| D32-2 Schema prerequisites | ✅ PASS |
| D32-3 Application-role connection | ✅ PASS |
| D32-4 First execution | ✅ PASS |
| D32-5 Same-event replay（NO_DOUBLE_CHARGE）| ✅ PASS |
| D32-6 Distinct-event separation | ✅ PASS |
| D32-7 Non-null identity | ✅ PASS |
| D32-8 PostgreSQL transaction/balance evidence | ✅ PASS |
| D32-9 Cleanup / residual | ✅ PASS（residual=0）|

**Verdict（候选）**：`0032 DAILY REPORT CONSUMER: PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`
→ **独立审批已通过（2026-08-10）**：正式升格为 `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。详见 `P1_PG_0032_DAILY_REPORT_CONSUMER_APPROVAL.md`。

Business Event Identity：`daily_report_generation:{generation_id}:summary`（与冻结 contract 一致，当前代码无 drift）。

---

## 1. Baseline / Commit

```text
HEAD = dbf8005a444488e2a6457476aed941e3272b2347（修复：闭环本地PostgreSQL应用角色权限）
worktree = clean（验证前无未提交改动）
```

前置状态：

```text
DB-BL                       = REPAIR_VERIFIED / COMPLETE
AUTO_WECHAT_DEV_PG          = CANONICAL_ALEMBIC_BASELINE@0034
APPLICATION_ROLE_PERMISSION_GAP = RESOLVED
LOCAL DEV application-role permission = VERIFIED
0032 = UNBLOCKED_FOR_PG_VERIFICATION / APPLICATION_ROLE_PREREQUISITE = VERIFIED（≠ PG_VERIFIED，本轮验证）
```

---

## 2. Environment / Principal（D32-0 / D32-3）

```text
environment        = LOCAL DEVELOPMENT ONLY
container/service  = auto-wechat-postgres-dev (Up, healthy)
database           = auto_wechat
backend            = PostgreSQL 16.14
revision           = 0034
physical tables    = 61
database owner     = postgres
```

**Application Principal 证据（consumer runtime 写入路径）**：

- 9000 HTTP 服务以 `DATABASE_URL=postgresql+psycopg://auto_wechat@auto-wechat-postgres-dev:5432/auto_wechat` 运行（非 superuser，非 SQLite）。
- `/ready`（以应用角色）：HTTP 200 / backend=postgresql / database=auto_wechat / alembic_revision=0034 / critical_tables(douyin_leads, sales_staff) pass。
- fixture 写入 + 证据读取均以 `auto_wechat` 应用角色直连：`current_user=auto_wechat / current_database=auto_wechat`。
- consumer 实际计费写入路径全程由 `auto_wechat` application principal 执行，未临时切 `postgres` superuser 完成核心写入。

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

---

## 3. Static Call Chain（D32-1）

以当前代码重新建立（非复制旧报告），真实文件/函数：

```text
9000 Daily Report generation request
  → app/services/daily_report_job_service.py:362 generate_one()
    → :374 _claim_generating(db, job)                       [创建 DailyReportGeneration 行 = billing identity 来源]
      → :246 DailyReportGeneration(job_id, lifecycle_status="running") + :255 commit
      → return (token, generation_id)
    → :383 build_daily_report(..., report_generation_id=generation_id)
      → app/services/daily_report_service.py:926 build_daily_report()
        → :956 透传 report_generation_id 给 summary 分支
          → :560 payload["report_generation_id"] = report_generation_id
          → :577 summary_client.summarize_daily_sales_feedback(payload)   [9000→9100 HTTP]
            → 9100 apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:177 summarize_daily_sales_feedback()
              → :191 OpenAICompatibleClient().chat(messages)               [LLM — 唯一 mock 边界]
              → :207 _report_usage(merchant_id, messages, result, report_generation_id=...)
                → :152-153 idempotency_key = f"daily_report_generation:{report_generation_id}:summary"
                → :159 ComputeUsageClient().report_usage(..., idempotency_key=idempotency_key)
                  → apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 report_usage()
                    → :262 POST {base_url}/internal/compute/usage  (9100→9000 HTTP，payload 含 idempotency_key)
                      → app/routers/compute.py:458 report_usage()  [9000 /internal/compute/usage]
                        → :467 compute_service.record_usage(..., idempotency_key=payload.idempotency_key)
                          → apps/compute/services.py:615 record_usage()
                            → :692-713 INSERT ComputeTransaction(idempotency_key=...) :716 flush
                              → :718-727 成功→原子扣费（created）：account.balance_tokens += -billed_tokens，单次 commit
                              → :728-769 IntegrityError→rollback→读已存在行
                                → :747 payload_evidence 相同 → idempotent_replay（不二次扣费）
                                → :757 不同 → idempotency_conflict
                            → PostgreSQL compute_transactions / compute_accounts
```

**全程未发现 CONTRACT_DRIFT**：当前代码实际生成的 identity 仍是 `daily_report_generation:{generation_id}:summary`，与冻结 contract 一致。

---

## 4. Business Event Identity（D32-1）

真实生成代码 [apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:140-156](../../../apps/xg_douyin_ai_cs/services/daily_report_summary_service.py)：

```python
def _report_usage(merchant_id, messages, result, report_generation_id=None):
    ...
    idempotency_key = (
        f"daily_report_generation:{report_generation_id}:summary"
        if report_generation_id is not None
        else None
    )
```

- identity 来源：`DailyReportGeneration.id`（[app/models.py:1316-1341](../../../app/models.py)），由 9000 `_claim_generating` 持久化后透传到 9100。
- 非时间戳推导（`datetime.now`/`time.time` 不参与 key 构造，经源码核验）。
- billing truth 归 M07 `ComputeTransaction`（Generation 无 `is_billed` 字段，经列定义核验）。

---

## 5. Schema Preconditions（D32-2）

canonical PG@0034 中确认 0032 所需对象真实存在：

| 对象 | 来源 | 核验 |
|---|---|---|
| `daily_report_generations` 表 | migration 0032 `op.create_table` | ✅ EXISTS |
| `daily_report_generations.id` PK | 0032 sa.PrimaryKeyConstraint | ✅ |
| `idx_daily_report_generations_job` 索引 | 0032 op.create_index | ✅ |
| `ck_daily_report_generations_status` CHECK | 0032 sa.CheckConstraint | ✅ |
| `daily_report_jobs.current_generation_id` 列 | 0032 op.add_column | ✅ |
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency` | [app/models.py:941](../../../app/models.py) | ✅ EXISTS（驱动 IntegrityError）|
| `compute_transactions.idempotency_key` 列 | [app/models.py:997](../../../app/models.py) | ✅ |
| `compute_transactions.payload_evidence` 列 | [app/models.py:998](../../../app/models.py) | ✅ |
| `compute_markup_ratios` 行 `wechat-assistant` | catalog | ✅ EXISTS（enabled / actual / markup=0）|
| application role 对 `daily_report_generations`/`compute_transactions`/`compute_accounts` 的 INSERT/SELECT | PR-3 grants | ✅（P1-PG-APP-ROLE-2 VERIFIED）|

migration 0032：`migrations/postgres/auto_wechat/versions/0032_daily_report_generations.py`，revision=`0032`，down_revision=`0030`，create_date=2026-08-08。新增对象：`daily_report_generations` 表 + `daily_report_jobs.current_generation_id` 列。

revision 仍为 0034（0032 已包含在 head 链中）。schema 存在 ≠ PG_VERIFIED（仅 precondition）。

---

## 6. Controlled Fixture（D32-4 setup）

完全受控 fixture，以 `auto_wechat` 应用角色写入：

```text
merchant_id       = m_d32_verify（受控测试商户，非真实客户）
DailyReportJob     = 1 行（merchant=m_d32_verify, report_day=2026-08-10, type=daily_sales_feedback, variant=default）
DailyReportGeneration = 2 行（job_id=1, lifecycle_status=succeeded）
  G1 = daily_report_generations.id = 1   → identity: daily_report_generation:1:summary
  G2 = daily_report_generations.id = 2   → identity: daily_report_generation:2:summary
compute account    = 不存在（get_or_create_account 将在首次计费时建账，balance=0）
```

baseline（计费前）：

```text
compute_accounts(m_d32_verify)        = 0
compute_transactions consume(m_d32_verify) = 0
```

未使用真实客户数据；未调用真实销售发送 / 真实日报发送 / 微信 / 抖音 / 外部 API（LLM 为唯一 mock）。

---

## 7. First Execution Evidence（D32-4）

以 9100 consumer 真实路径执行一次 summary usage / charge（G1）：

```text
调用：summarize_daily_sales_feedback(DailySalesSummaryRequest(
        merchant_id="m_d32_verify", report_day="2026-08-10",
        summaries=[DailySalesSummaryItem(sales_name="测试销售", overall_quality="良好", main_problem="无")],
        report_generation_id=1))
LLM mock 返回：usage.total_tokens=15（provider_tokens），reply_text={"summary_text":"受控测试摘要…"}
consumer 返回：llm_used=True / model=d32-verify-mock-llm / fallback=None / summary_present=True
```

**A. Consumer 执行成功** ✅（llm_used=True，summary 生成，_report_usage 被调用）

**B. Compute Transaction = exactly 1**（PG 查询证据，见 §10）：

```text
id=1 | idempotency_key=daily_report_generation:1:summary | transaction_type=consume | delta_tokens=-15
```

**C. Idempotency Identity 一致** ✅：`daily_report_generation:1:summary` = `daily_report_generation:{G1}:summary`

**D. Balance**（项目正负号 contract：consume `delta_tokens` 为负，[app/models.py:979](../../../app/models.py) "消耗为负"）：

```text
balance_before = 0   （account 首次建账）
charge_delta   = -15 （billed_tokens=15，markup=0，calculate_billed_tokens(15,0)=15）
balance_after  = -15  （= balance_before + delta = 0 + (-15)）✓
```

**E. Usage Metadata**（当前 compute contract 实际存储字段）：

```text
capability_key=wechat-assistant / model=d32-verify-mock-llm / llm_call_stage=primary
actual_tokens=15 / usage_measurement_method=provider_tokens / payload_evidence IS NOT NULL
```

---

## 8. Replay Evidence（D32-5）

**同一 generation_id=1、同一 summary stage** 再次进入真实 consumer 路径（非人工直接调 compute core）：

```text
调用：summarize_daily_sales_feedback(..., report_generation_id=1)  [第二次，same identity]
consumer 返回：llm_used=True（consumer 侧无幂等感知，始终调 _report_usage）
HTTP：9100→9000 /internal/compute/usage 200（HTTP 成功 ≠ 幂等证据，§15）
```

**PostgreSQL 权威证据**（不靠 HTTP 200）：

```text
compute_transactions WHERE idempotency_key='daily_report_generation:1:summary' count = 1  （未产生第 2 行）✓
account balance 仍 = -15  （replay 后未变）✓
```

**法证细节**：`compute_transactions.id` 序列为 1, 3（id=2 缺失）。id=2 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（序列不回退，故 id 被消耗但无行）→ 进入 [apps/compute/services.py:728-756](../../../apps/compute/services.py) `idempotent_replay` 分支。该 id gap 印证 IntegrityError 幂等路径真实执行，而非"未尝试 INSERT"。

```text
same event → same idempotency identity → duplicate charge suppressed（replay）✓
```

---

## 9. Distinct Event Evidence（D32-6）

再创建另一 generation_id=2（不同受控 id），同一 summary stage：

```text
调用：summarize_daily_sales_feedback(..., report_generation_id=2)  [different identity]
预期 identity：daily_report_generation:2:summary
```

**PostgreSQL 证据**：

```text
compute_transactions WHERE idempotency_key='daily_report_generation:2:summary' count = 1  ✓
id=3 | idempotency_key=daily_report_generation:2:summary | delta_tokens=-15 | balance_after_tokens=-30
```

两个不同 generation 合计 **2 个 distinct business-event identities**（`:1:summary` / `:2:summary`），无 collision / 共享 / 互相吞没：

```text
same event → dedupe；different event → independent charge  ✓
```

---

## 10. Account / Transaction Evidence（D32-8）

PG 查询（`auto_wechat` 应用角色只读）全部 consume txns for `m_d32_verify`：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 1 | `daily_report_generation:1:summary` | consume | -15 | -15 | wechat-assistant | d32-verify-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 3 | `daily_report_generation:2:summary` | consume | -15 | -30 | wechat-assistant | d32-verify-mock-llm | primary | 15 | provider_tokens | NOT NULL |

按 identity 计数：

| idempotency_key | txn_count |
|---|---|
| `daily_report_generation:1:summary` | 1 |
| `daily_report_generation:2:summary` | 1 |

账户：

```text
merchant_id=m_d32_verify / balance_tokens=-30
```

balance 推进：0 →(G1 first)→ -15 →(G1 replay, 不变)→ -15 →(G2)→ -30 ✓

---

## 11. None / Empty Identity Check（D32-7）

```text
compute_transactions WHERE merchant_id='m_d32_verify'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0  ✓
```

Daily Report active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，且与冻结 contract 一致。无 `idempotency_key=None` 走旧兼容路径（record_usage 的 idempotency_key=None 警告路径未触发）。

---

## 12. Application Role Evidence（D32-3）

| 证据 | 结论 |
|---|---|
| 9000 DATABASE_URL principal | `auto_wechat`（非 superuser）|
| `/ready` backend | postgresql / database=auto_wechat / 0034（HTTP 200）|
| fixture 写入连接 | `current_user=auto_wechat`（psql 应用角色直连）|
| 证据读取连接 | `current_user=auto_wechat`（应用角色只读）|
| consumer 计费写入 | 经 9000 `record_usage`，DATABASE_URL=`auto_wechat` 角色 → PG |
| superuser-as-consumer 替代 | 无（未用 postgres 完成 consumer 核心写入）|

→ `APPLICATION_ROLE_RUNTIME_VERIFIED` + `PG_RUNTIME_VERIFIED`（非仅 unit test；现有 `tests/test_daily_report_compute_idempotency_migration.py` 为 SQLite + 直接调 record_usage 的 unit test，本轮以 canonical PG + 真实 HTTP consumer 路径 + 应用角色升级证据等级）。

---

## 13. Cleanup（D32-9）

测试完成后以 `auto_wechat` 应用角色清理受控 fixture（事务内）：

```text
DELETE compute_transactions WHERE merchant_id='m_d32_verify'   → 2
DELETE compute_accounts WHERE merchant_id='m_d32_verify'       → 1
DELETE daily_report_generations WHERE job_id=1                 → 2
DELETE daily_report_jobs WHERE id=1                            → 1
COMMIT
```

residual 检查（全部 0，clean baseline 恢复）：

```text
compute_txns(m_d32_verify)        = 0
compute_accounts(m_d32_verify)    = 0
daily_report_generations(job_id=1)= 0
daily_report_jobs(m_d32_verify)   = 0
total compute_transactions        = 0
total compute_accounts           = 0
total daily_report_generations   = 0
total daily_report_jobs          = 0
```

DB-BL 完整性未变：`head=0034 / tables=61`。9000 探测容器已停止移除（`docker stop au-pg0032-api`，`--rm`）。验证脚本经 stdin 管道执行，未写入 worktree（`git status` clean，零业务代码改动）。

```text
residual test data = 0
```

---

## 14. D32-* Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| D32-0 | Environment / principal | ✅ PASS | LOCAL DEV，canonical PG@0034，db_owner=postgres，app role CREATE=false |
| D32-1 | Consumer call chain | ✅ PASS | §3 真实文件/函数链；identity 与冻结 contract 一致，无 drift |
| D32-2 | Schema prerequisites | ✅ PASS | 0032 表/列/约束/索引存在；compute 幂等唯一约束存在；app role 有权限 |
| D32-3 | Application-role connection | ✅ PASS | current_user=auto_wechat；/ready 应用角色 HTTP 200；consumer 写入经 auto_wechat 角色 |
| D32-4 | First execution | ✅ PASS | G1 → 1 consume txn，identity=daily_report_generation:1:summary，balance 0→-15 |
| D32-5 | Same-event replay | ✅ PASS | G1 replay → txn count 仍 1，balance 不变（-15），id gap=2 印证 IntegrityError rollback |
| D32-6 | Distinct-event separation | ✅ PASS | G2 → 1 独立 txn，2 distinct identities，无 collision |
| D32-7 | Non-null identity | ✅ PASS | 0 null/empty idempotency_key |
| D32-8 | PostgreSQL transaction/balance evidence | ✅ PASS | 2 txns（id 1,3），delta=-15 each，balance=-30，payload_evidence NOT NULL |
| D32-9 | Cleanup / residual | ✅ PASS | residual=0，DB-BL 不变（0034/61），容器清理，worktree clean |

---

## 15. Out-of-P1 Reliability Findings

```text
NONE OBSERVED（本轮 consumer compute-idempotency + PG persistence + application-role path 验证范围内）
```

已登记的 `DAILY_REPORT_REQUEST_RECOVERY_GAP` 属此前冻结的 OUT_OF_P1 reliability gap，本轮未触碰、未扩大。本轮**不**验证 request recovery / restart recovery / crash 后任务恢复——这些属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴，不阻断 0032 consumer PG verification。

注：不声称"不存在所有潜在 recovery gap"——仅声明本轮批准的 consumer PG verification criteria 范围内未观察到新问题。

并发边界（§十九）：本轮未执行全局 concurrent closure（`Final PostgreSQL Concurrent Closure Gate` 后续独立执行）。txn id gap（1,3）为 replay INSERT-rollback 的法证副证，非正式 concurrent test。`lack of concurrent test` 不阻断 0032。

---

## 16. Verdict

```text
0032 DAILY REPORT CONSUMER:
PG_VERIFICATION_COMPLETE_PENDING_APPROVAL
  → 独立审批通过（2026-08-10）：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
daily_report_generation:{generation_id}:summary
APPLICATION_ROLE_RUNTIME_VERIFIED

Same-event replay:
NO_DOUBLE_CHARGE_VERIFIED（G1 replay → 1 txn / balance 不变）

Distinct-event separation:
VERIFIED（G2 → 独立 charge / 2 distinct identities / 无 collision）
```

**独立审批窗口已裁定 APPROVED**（`P1_PG_0032_DAILY_REPORT_CONSUMER_APPROVAL.md`）。0032 正式状态 = `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`；0033 授权 `AUTHORIZED_TO_START_PG_VERIFICATION`。P1 整体仍 OPEN / TECHNICAL_CLOSURE=PENDING。

---

## 17. P1 Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

本轮完成的是 **0032 Daily Report consumer PostgreSQL verification**（候选 PG_VERIFICATION_COMPLETE_PENDING_APPROVAL），不是整个 P1 closure。仍待：独立审批窗口裁定 0032 → 0033 / 0034 consumer PG verification → RAG Query 0005 → Global Active None Audit → Final PG Concurrent Closure Gate → LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP。

---

## 18. 边界遵守

- ✅ 未修改业务代码（NO BUSINESS CODE CHANGE）——验证脚本经 stdin 管道执行，未入 worktree；
- ✅ 未修改 migration 0032 / 未新增 repair migration / 未 stamp / 未手工 schema 修复（DB-BL 闭环，head=0034 / 61 表不变）；
- ✅ 未开始 0033 / 0034 / RAG Query 0005 / Global Active None Audit / Final Concurrent Closure / RB-10 / bootstrap owner drift 修复；
- ✅ 未用 superuser 替代 app role 完成 consumer 核心写入；
- ✅ 未提交（candidate diff 保持，数据库证据/凭据/dump 未入库）；
- ✅ consumer 验证仅 mock LLM（外部非确定性边界），未 mock consumer orchestration / identity 生成 / compute charge / PG 幂等路径；
- ✅ 未触碰 `DAILY_REPORT_REQUEST_RECOVERY_GAP`（OUT_OF_P1）。

---

## 19. Git / Commit

按 §三十：**不自行 commit**。本报告为 candidate diff，供独立审批窗口复核。数据库测试证据已清理（residual=0），无凭据/dump/probe 残留。

提交：**P1-PG-0032 独立审批窗口。**

---

## 附：本窗口独立核验证据索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| Git baseline | `git rev-parse HEAD` + `git status` | dbf8005 / clean |
| 环境/principal | psql 应用角色 + /ready HTTP | auto_wechat / PG 16.14 / 0034 / 61 表 / HTTP 200 |
| 静态调用链 | 代码 file:line 核验 | 无 CONTRACT_DRIFT，identity 与冻结一致 |
| schema 前提 | catalog inspection | 0032 表/列/约束/索引 + compute 幂等唯一约束存在 |
| fixture | 应用角色 INSERT | job=1 + G1=1 + G2=2，baseline 0/0 |
| first execution | 9100 真实 consumer（LLM mock）+ PG 查询 | 1 txn / identity 一致 / balance 0→-15 |
| replay | 同 G1 再调 consumer + PG 查询 | txn count 仍 1 / balance 不变 / id gap=2 印证 IntegrityError |
| distinct | G2 调 consumer + PG 查询 | 1 独立 txn / 2 distinct identities / 无 collision |
| balance | compute_accounts 查询 | -30（0→-15→-15→-30）|
| non-null identity | count NULL/empty | 0 |
| cleanup | 应用角色 DELETE + residual 查询 | residual=0 / head=0034 / 61 表不变 |
| worktree | git status | clean（脚本经 stdin，未入 worktree）|

所有核验：真实 canonical PG + 应用角色 + 真实 HTTP consumer 路径 + PG 直查证据。零业务污染，零迁移修改，零 DB-BL 重开，零业务代码改动。
