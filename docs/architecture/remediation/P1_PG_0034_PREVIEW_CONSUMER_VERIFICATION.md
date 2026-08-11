# P1-PG-0034 — Preview Consumer PostgreSQL 验证报告

> 任务：`P1-PG-0034 — AI Preview Consumer PostgreSQL Verification`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 consumer-level PG verification
> 基线 commit：`da3d605`（验证：闭环M05素材分析0033 PostgreSQL幂等计费）
> 日期：2026-08-11
> 窗口：P1-PG-0034 AI Preview Consumer PG 验证执行/验证窗口
> Source of Truth：真实 PG runtime 证据（canonical PG@0034，应用角色 `auto_wechat`，真实 consumer HTTP 路径） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| D34-0 Git / environment | ✅ PASS |
| D34-1 Application principal | ✅ PASS |
| D34-2 Static consumer chain | ✅ PASS（无 CONTRACT_DRIFT）|
| D34-3 Business Event Identity | ✅ PASS |
| D34-4 Schema prerequisites | ✅ PASS |
| D34-5 Mock boundary | ✅ PASS |
| D34-6 First execution（P-A）| ✅ PASS |
| D34-7 Same-execution+same-stage replay（NO_DOUBLE_CHARGE）| ✅ PASS |
| D34-8 Distinct-execution separation（P-B）| ✅ PASS |
| D34-9 Stage separation（primary + retry_combined）| ✅ PASS |
| D34-10 Non-null identity | ✅ PASS |
| D34-11 Preview execution persistence | ✅ PASS |
| D34-12 Application Role Hard Gate + PG transaction/balance evidence | ✅ PASS |
| D34-13 Cleanup / residual | ✅ PASS（residual=0）|

**Verdict（候选）**：`0034 AI PREVIEW CONSUMER: PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`
→ **独立审批已通过（2026-08-11）**：正式升格为 `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。详见 `P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md`。

Business Event Identity：`ai_preview_execution:{preview_execution_id}:{llm_call_stage}`（与冻结 contract 一致，当前代码无 drift）。

证据等级：`PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## 1. Baseline / Commit

```text
HEAD = da3d605256923feea201a9a0e41165783c3deeea（验证：闭环M05素材分析0033 PostgreSQL幂等计费）
worktree = clean（验证前无未提交改动）
```

前置状态：

```text
DB-BL                       = REPAIR_VERIFIED / COMPLETE
AUTO_WECHAT_DEV_PG          = CANONICAL_ALEMBIC_BASELINE@0034
APPLICATION_ROLE_PERMISSION_GAP = RESOLVED
LOCAL DEV application-role permission = VERIFIED
0034 = AUTHORIZED_TO_START_PG_VERIFICATION（≠ PG_VERIFIED，本轮验证）
0032 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（独立审批已通过）
0033 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（独立审批已通过）
P1 = COMPUTE-IDEMPOTENCY-001 OPEN / TECHNICAL_CLOSURE=PENDING
```

0033 独立审批 commit 已包含在本基线 `da3d605` 之中。

---

## 2. Environment / Principal（D34-0 / D34-1）

```text
environment        = LOCAL DEVELOPMENT ONLY
container/service  = auto-wechat-postgres-dev (Up 21h, healthy)
database           = auto_wechat
backend            = PostgreSQL 16.x
revision           = 0034
physical tables    = 61
database owner     = postgres
PG network         = 127.0.0.1:5432（宿主机直连，asyncpg+Windows 约束已遵守用 127.0.0.1）
```

**Application Principal 证据（consumer runtime 写入路径）**：

- 9000 HTTP 服务以 `DATABASE_URL=postgresql+psycopg://auto_wechat@127.0.0.1:5432/auto_wechat` 运行（非 superuser，非 SQLite）。
- `/ready`（以应用角色）：HTTP 200 / `backend=postgresql / db_connect=pass / database_name=auto_wechat / alembic_revision=0034 / critical_tables(douyin_leads, sales_staff) pass`。
- runtime principal 直查：`SELECT current_user, current_database()` → `('auto_wechat', 'auto_wechat')`（Python psycopg 应用角色直连）。
- consumer 计费写入路径全程由 `auto_wechat` application principal 执行，未临时切 `postgres` superuser 完成核心写入。`postgres` 仅用于 catalog inspection / schema 前提核验。
- `is_superuser=False / tables owned by auto_wechat=0（61 全归 postgres）/ DML: compute_transactions,compute_accounts,ai_preview_executions = INSERT,SELECT,UPDATE,DELETE / sequences granted=60`。

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

9000 启动日志独立确认 `db_schema stage=startup_skip_create_all backend=postgresql`（`ensure_runtime_schema` PG 分支不调 create_all，满足 CLAUDE.md 硬约束 #2）。

---

## 3. Static Consumer Chain（D34-2）

以当前代码重新建立（非复制旧报告），真实文件/函数。**关键事实：0034 Preview 是 9000→9100→9000 双 HTTP hop**——与 0032（9100 `ComputeUsageClient` → 9000 `/internal/compute/usage` 单 hop HTTP）同模式，但 Preview 入口在 9000 `/agents/preview`（PV-0 execution 在 9000 侧创建），而非 9100 直调。

```text
9000 POST /agents/preview                   app/routers/agents.py:231 preview_agent()
  → :311 _create_preview_execution(db, merchant_id, agent_id)        [PV-0 durable before 9100/LLM]
    → :61-76 AiPreviewExecution(merchant_id, lifecycle_status="running") + :74 db.commit()
    → return execution.id
  → :312 request_payload["preview_execution_id"] = _preview_exec_id   [透传到 9100]
  → :315 get_xg_douyin_ai_cs_client().suggest_reply(...)             [9000→9100 HTTP]
    → 9100 apps/xg_douyin_ai_cs/routers/ai_reply.py:32 POST /douyin/reply-suggestion
      → apps/xg_douyin_ai_cs/services/reply_decision_service.py:628 build_reply_suggestion()
        → :981 _build_llm_reply()
          → :1026 ComputeUsageClient().check_balance(merchant_id)    [9100→9000 余额检查 HTTP，真实余额门禁]
          → :1020 OpenAICompatibleClient().chat(messages)             [★ 唯一 mock 边界]
          → :1160 _report_llm_usage(llm_call_stage="primary")
          → :1223 条件命中（off_platform_promise_violation 等）→ :1234 retry client.chat
          → :1236 _report_llm_usage(llm_call_stage="retry_combined")
            → :3763 _report_llm_usage()
              → :3788 preview_execution_id = getattr(request, "preview_execution_id", None)
              → :3810 idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"
              → :3814 ComputeUsageClient().report_usage(idempotency_key=...)  [9100→9000 HTTP]
                → apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 report_usage()
                  → :163 base_url=os.environ["AUTO_WECHAT_9000_BASE_URL"] / :172 USAGE_PATH="/internal/compute/usage"
                  → POST {base_url}/internal/compute/usage（payload 含 idempotency_key，X-Internal-Token 校验）
                    → app/routers/compute.py:458 internal_router.post("/compute/usage")
                      → :482 compute_service.record_usage(idempotency_key=payload.idempotency_key)
                        → apps/compute/services.py:615 record_usage()
                          → :692-713 INSERT ComputeTransaction(idempotency_key, payload_evidence) :716 db.flush()
                          → :718-727 flush 成功→ get_or_create_account + _write_transaction_balance_only（原子扣费）+ :725 db.commit()
                          → :728-769 IntegrityError→rollback→读已存在行
                            → :747 existing.payload_evidence == payload_evidence → idempotent_replay（不二次扣费，:756 return）
                            → :757 不同 → idempotency_conflict
                          → PostgreSQL compute_transactions / compute_accounts
  → :343 _finalize_preview_execution(db, _preview_exec_id, "completed")  [9100 正常返回→completed；:322 failed]
```

**全程未发现 CONTRACT_DRIFT**：当前代码实际生成的 identity 仍是 `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，与冻结 contract 一致。

### Same Execution 真正含义

正式幂等事件 = `preview_execution_id` + `llm_call_stage`：
- same execution + same stage → dedupe（replay）
- different preview_execution_id → independent charge
- same execution + different legitimate billable stage → independent charge（D34-9）

### Replay 路径合法性

P-A replay 经 9100 `/douyin/reply-suggestion` 直调，传入同一 `preview_execution_id`（P-A 的 execution.id）。9100 内部 `_build_llm_reply` → `_report_llm_usage(primary)` 对同一 identity 再次上报。对应 crash 后 usage report 重试场景（9100 完成 LLM + M07 已 commit，但 HTTP 响应丢失 → client 重试同 execution_id → 同 key → IntegrityError → idempotent_replay）。非手工构造 key，非直接调 `record_usage`，非手工 POST duplicate。

---

## 4. Business Event Identity（D34-3）

真实生成代码 [apps/xg_douyin_ai_cs/services/reply_decision_service.py:3807-3810](../../../apps/xg_douyin_ai_cs/services/reply_decision_service.py)：

```python
elif preview_execution_id is not None:
    # ★ P1 Stage 5G-2：Preview 独立分支（独立 namespace ai_preview_execution，不影响 Auto Reply）
    # cardinality 1:N(2)，key 含 llm_call_stage 区分 primary/retry_combined
    idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"
```

- identity 来源：`AiPreviewExecution.id`（[app/models.py:1344-1374](../../../app/models.py)），由 9000 `_create_preview_execution`（[agents.py:61-76](../../../app/routers/agents.py)）在 9100 HTTP call 前 durable commit（PV-0）。
- 非时间戳推导（`datetime.now`/`time.time` 不参与 key 构造，经源码核验）。
- 非运行时计算序号（`call_count` 不参与，进程重启/重试后稳定复用同一 execution.id）。
- billing truth 归 M07 `ComputeTransaction`（`AiPreviewExecution` 无 `is_billed`/`billing_status` 字段，经列定义核验）。
- C4 mixed identity 防护：`run_id`/`attempt_count` 与 `preview_execution_id` 同时存在 → warning + 退 None（:3792-3798）。

```text
ai_preview_execution:{preview_execution_id}:{llm_call_stage}
```

与 `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #7 冻结 contract 一致，无 drift。

---

## 5. Migration 0034 / Schema Preconditions（D34-4）

canonical PG@0034 中确认 0034 所需对象真实存在（`postgres` catalog inspection）：

| 对象 | 来源 | 核验 |
|---|---|---|
| `ai_preview_executions` 表 | migration 0034 `op.create_table` | ✅ EXISTS（6 列）|
| `id` PK + `ai_preview_executions_pkey` | 0034 sa.Column primary_key | ✅ |
| `merchant_id` varchar(128) NOT NULL | 0034 | ✅ |
| `agent_id` varchar(128) nullable | 0034 | ✅ |
| `lifecycle_status` varchar(20) NOT NULL default 'running' | 0034 server_default | ✅ |
| `created_at` timestamp NOT NULL default now() | 0034 | ✅ |
| `completed_at` timestamp nullable | 0034 | ✅ |
| `ck_ai_preview_executions_status` CHECK | 0034 lifecycle_status ∈ (running/completed/failed) | ✅ |
| `idx_ai_preview_executions_merchant` index | 0034 op.create_index(merchant_id) | ✅ |
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency` | [app/models.py:941](../../../app/models.py) UNIQUE(merchant_id, idempotency_key) | ✅ EXISTS（驱动 IntegrityError）|
| `compute_transactions.idempotency_key` 列 | [app/models.py:997](../../../app/models.py) varchar(255) nullable | ✅ |
| `compute_transactions.payload_evidence` 列 | [app/models.py:998](../../../app/models.py) text nullable | ✅ |
| `compute_transactions.llm_call_stage` 列 | varchar | ✅ |
| `compute_markup_ratios` 行 `douyin-cs` | catalog | ✅ EXISTS（enabled=true / actual / markup=0 / fixed_tokens_per_call=NULL）|
| application role 对 `ai_preview_executions`/`compute_transactions`/`compute_accounts` 的 INSERT/SELECT/UPDATE/DELETE | PR-3 grants | ✅（D34-1 已确认）|

migration 0034：`migrations/postgres/auto_wechat/versions/0034_preview_executions.py`，revision=`0034`，down_revision=`0033`，create_date=2026-08-10。新建对象：`ai_preview_executions` 表（6 列 + PK + CHECK + merchant 索引），不激活 dormant 表，不引入 attempt_count。

revision 仍为 0034（0030→0032→0033→0034 线性单链，0034 是 head）。

**schema 存在 ≠ PG_VERIFIED**（仅 `SCHEMA_PREREQUISITE = PASS`），consumer runtime 仍需真实执行（见 §7-§12）。

---

## 6. Mock Boundary（D34-5）

**允许并仅 mock**：`OpenAICompatibleClient.chat`（9100 最终外部 LLM 调用边界）。mock 返回固定可审计结果：

```text
usage = {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}
model = d34-verify-mock-llm
reply_text 按 D34_LLM_MODE 选择：
  - STAGE_TEST 标记消息（P-R）：primary 返回含 OFF_PLATFORM_PROMISE_KEYWORDS 的违规回复
    → _build_llm_reply post-generation 校验命中 off_platform_promise_violation → 自然进入 retry_combined 分支
    → retry 返回干净合规回复（不触发第三次）
  - 其他消息（P-A/P-B）：恒返回干净合规回复（只产生 primary stage）
```

mock 目的：避免真实 LLM 收费 / 网络不稳定 / 非确定性 usage / stage 不可控，且不调用生产模型 / 不修改实际业务状态 / 不触发真实发送。

**以下链全程真实，未 mock**：

```text
9000 /agents/preview 路由（含 mock auth → RequestContext.merchant_id=dev-merchant）
Preview execution 持久化（AiPreviewExecution durable commit，PV-0）
9000→9100 HTTP（XgDouyinAiCsClient.suggest_reply → /douyin/reply-suggestion）
9100 _build_llm_reply orchestration（含余额检查 check_balance 真实 HTTP）
balance check（9100→9000 /internal/compute/balance 真实查询，余额>0 才放行 LLM）
llm_call_stage selection（primary / retry_combined 由真实 post-generation 校验决定）
_report_llm_usage
Business Event Identity 生成（f-string 构造）
ComputeUsageClient.report_usage（9100→9000 HTTP）
9000 /internal/compute/usage（真实 uvicorn HTTP 服务 + 真实 route）
record_usage INSERT / 原子扣费 / IntegrityError 幂等路径
PostgreSQL uniqueness（uk_compute_transactions_merchant_idempotency）
compute account balance
```

关键 compute 路径未被 mock——本轮不是 unit/integration test，达到 `PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。consumer（9100）与 9000 经真实 loopback HTTP（urllib → TCP → uvicorn → FastAPI → route → record_usage），非 TestClient 旁路。现有 `tests/test_preview_compute_idempotency_migration.py` 为 SQLite + 直接调 record_usage 的 unit test，本轮以 canonical PG + 真实 HTTP consumer 路径 + 应用角色升级证据等级。

---

## 7. Controlled Fixture（D34-6 setup）

完全受控 fixture，以 `auto_wechat` 应用角色写入：

```text
merchant_id       = dev-merchant（mock auth 运行时真实值，NEWCAR_AUTH_ENABLED=false → build_mock_context()）
recharge          = create_mock_recharge_order 等价 SQL，custom_tokens=100000
compute account   = 首次建账 balance=0 → 充值后 balance=100000
```

**预充值目的**：Preview 走 `_build_llm_reply`（[reply_decision_service.py:1026-1033](../../../apps/xg_douyin_ai_cs/services/reply_decision_service.py)），LLM 调用前有真实余额检查 `check_balance`。首次建账 balance=0 会被阻断（`balance <= 0`）。预充值是 fixture 前置条件（模拟真实商户有余额），**非 mock consumer 逻辑、非绕过余额门禁**。余额检查经 9100→9000 真实 HTTP 查询 `/internal/compute/balance`，走真实 `get_summary`→`get_or_create_account`。

baseline（计费前）：

```text
compute_accounts(dev-merchant)        = 0（不存在，充值时建账）
compute_transactions consume(dev-merchant) = 0
balance_before_recharge               = 0
balance_after_recharge                = 100000
```

未使用真实客户数据；未调用真实 LLM / 抖音 / 微信 / 外部 API（LLM 为唯一 mock）。

---

## 8. P-A First Execution（D34-6）

从真实 consumer 入口 `POST /agents/preview`（message="有没有奥迪A6？"，mock auth → merchant_id=dev-merchant）执行一次 primary LLM 计费：

```text
P-A execution_id    = 4（ai_preview_executions.id，真实 PG 序列持久化，非硬编码）
lifecycle_status    = completed
identity            = ai_preview_execution:4:primary（consumer 自然生成，非手工构造 key）
HTTP                = 200
consumer 返回        : reply_text=干净合规回复 / source=llm
```

**A. Consumer 执行成功** ✅（execution COMPLETED，`_report_llm_usage` 被调用，余额检查通过）

**B. Compute Transaction = exactly 1**（PG 查询证据）：

```text
id=20 | idempotency_key=ai_preview_execution:4:primary | transaction_type=consume | delta_tokens=-15
balance_after_tokens=99985 | capability_key=douyin-cs | model=d34-verify-mock-llm
llm_call_stage=primary | actual_tokens=15 | usage_measurement_method=provider_tokens | payload_evidence IS NOT NULL
```

**C. Idempotency Identity 一致** ✅：`ai_preview_execution:4:primary` = `ai_preview_execution:{execution_id=4}:primary`

**D. Balance**（consume `delta_tokens` 为负，markup=0 → billed=actual=15）：

```text
balance_before = 100000   （fixture 充值后）
charge_delta   = -15      （billed_tokens=calculate_billed_tokens(15,0)=15）
balance_after  = 99985    （= 100000 + (-15)）✓
```

**E. Usage Metadata**（当前 compute contract 实际存储字段）：

```text
capability_key=douyin-cs / model=d34-verify-mock-llm / llm_call_stage=primary
actual_tokens=15 / usage_measurement_method=provider_tokens / payload_evidence IS NOT NULL
```

---

## 9. P-A Replay（D34-7）

对同一个 `execution_id=4`、同一 `primary` stage，经 9100 `/douyin/reply-suggestion` 直调传入同一 `preview_execution_id=4`（same identity，模拟 usage report 重试 / crash 后恢复重报场景）：

```text
调用：9100 /douyin/reply-suggestion（preview_execution_id=4）[same identity]
identity 自然重新生成：ai_preview_execution:4:primary
HTTP：9100→9000 /internal/compute/usage 200
```

**PostgreSQL 权威证据**（不靠 HTTP 200）：

```text
compute_transactions WHERE idempotency_key='ai_preview_execution:4:primary' count = 1（未产生第 2 行）✓
account balance 仍 = 99985（replay 后未变）✓
balance_after_replay = 99985 = balance_after_first_execution ✓
```

**法证细节**：`compute_transactions.id` 序列为 20, 22, 23, 24（id=21 缺失）。id=21 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 [apps/compute/services.py:728-756](../../../apps/compute/services.py) `idempotent_replay` 分支。该 id gap 印证 IntegrityError 幂等路径真实执行，而非"未尝试 INSERT"。

```text
same event → same idempotency identity → duplicate charge suppressed（replay）✓
NO_DOUBLE_CHARGE_VERIFIED
```

SUPPLEMENTARY_RUNTIME_EVIDENCE：id gap=21（IntegrityError rollback 副证）。sequence id gap 不是幂等硬证据——正式硬证据仍是 same identity + one transaction + balance unchanged（已满足）。

---

## 10. P-B Distinct Execution（D34-8）

创建另一 preview execution（message="你们店有宝马X5吗？"），同一 `primary` stage，从真实 consumer 入口执行：

```text
P-B execution_id    = 5
lifecycle_status    = completed
identity            = ai_preview_execution:5:primary（consumer 自然生成）
预期 transaction count = 1
```

**PostgreSQL 证据**：

```text
compute_transactions WHERE idempotency_key='ai_preview_execution:5:primary' count = 1  ✓
id=22 | idempotency_key=ai_preview_execution:5:primary | delta_tokens=-15 | balance_after_tokens=99970
```

两个不同 execution 合计 **2 个 distinct business-event identities**（`:4:primary` / `:5:primary`），无 collision / 共享 / 互相吞没：

```text
identity(P-A) = ai_preview_execution:4:primary
identity(P-B) = ai_preview_execution:5:primary
identity_distinct = True
same event → dedupe；different event → independent charge  ✓
```

---

## 11. Stage Separation（D34-9）

P-R 用 message="STAGE_TEST 有没有奥迪A6？"（mock 检测 STAGE_TEST 标记 → primary 返回含 `OFF_PLATFORM_PROMISE_KEYWORDS` 的违规回复 "我把报价发您手机上..." → `_build_llm_reply` post-generation 校验命中 `off_platform_promise_violation` → 自然进入 retry_combined 分支 → retry 返回干净回复，不触发第三次）：

```text
P-R execution_id    = 6
lifecycle_status    = completed
consumer warnings   = ['llm_retry_combined']（retry 真实触发，由真实 post-generation 校验决定，非手工构造）
```

同一 `execution_id=6`，两个不同 legitimate billable stage：

**P-R primary**：
```text
identity = ai_preview_execution:6:primary
transaction count = 1  ✓
id=23 | delta_tokens=-15 | balance_after_tokens=99955 | llm_call_stage=primary | payload_evidence IS NOT NULL
```

**P-R retry_combined**：
```text
identity = ai_preview_execution:6:retry_combined
transaction count = 1  ✓
id=24 | delta_tokens=-15 | balance_after_tokens=99940 | llm_call_stage=retry_combined | payload_evidence IS NOT NULL
```

```text
identity(P-R primary)       = ai_preview_execution:6:primary
identity(P-R retry_combined) = ai_preview_execution:6:retry_combined
identity_distinct = True（same execution + different legitimate billable stage）
2 distinct Business Events / 2 legitimate charges / same execution 不互相吞没
```

```text
same execution + different legitimate billable stage → independent billing events  VERIFIED
```

retry_combined 由真实 `_build_llm_reply` post-generation 校验逻辑触发（`off_platform_promise_violation` 命中 → `_build_llm_combined_retry_messages` → 第二次 `client.chat` → `_report_llm_usage(stage="retry_combined")`），**非直接调 `_report_llm_usage("retry_combined")`、非手工构造 retry key、非 monkeypatch stage selector**。

---

## 12. Compute Transactions / Balance（D34-12）

PG 查询（`auto_wechat` 应用角色只读）全部 consume txns for `dev-merchant`：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 20 | `ai_preview_execution:4:primary` | consume | -15 | 99985 | douyin-cs | d34-verify-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 22 | `ai_preview_execution:5:primary` | consume | -15 | 99970 | douyin-cs | d34-verify-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 23 | `ai_preview_execution:6:primary` | consume | -15 | 99955 | douyin-cs | d34-verify-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 24 | `ai_preview_execution:6:retry_combined` | consume | -15 | 99940 | douyin-cs | d34-verify-mock-llm | retry_combined | 15 | provider_tokens | NOT NULL |

按 identity 计数：

| idempotency_key | txn_count |
|---|---|
| `ai_preview_execution:4:primary` | 1 |
| `ai_preview_execution:5:primary` | 1 |
| `ai_preview_execution:6:primary` | 1 |
| `ai_preview_execution:6:retry_combined` | 1 |

账户：

```text
merchant_id=dev-merchant / balance_tokens=99940
```

balance 推进：

```text
100000 →(P-A first)→ 99985 →(P-A replay, 不变)→ 99985 →(P-B)→ 99970 →(P-R primary)→ 99955 →(P-R retry_combined)→ 99940 ✓
final balance = initial(100000) + delta(P-A primary -15) + delta(P-B primary -15) + delta(P-R primary -15) + delta(P-R retry_combined -15)
              = 100000 + (-15)×4 = 99940 ✓
P-A replay does not contribute another delta ✓
```

4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费。id=21 缺失（P-A replay IntegrityError 消耗序列）。

### Application Role Hard Gate

核心 consumer 写入链全程由 `auto_wechat` Application Principal 执行：

```text
postgres catalog inspection → PASS
auto_wechat consumer runtime 写入 → PASS（record_usage 经 DATABASE_URL=auto_wechat 角色 → PG）
superuser-as-consumer 替代 → 无（postgres 仅用于 catalog inspection / schema 前提核验）
```

若 `postgres PASS / auto_wechat FAIL` 则 0034 FAIL。本验证为 `auto_wechat PASS`。

```text
postgres PASS / auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）
```

---

## 13. Non-null Identity（D34-10）

```text
compute_transactions WHERE merchant_id='dev-merchant' AND transaction_type='consume'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0  ✓
全局 ai_preview_execution:% identity NULL/EMPTY count = 0  ✓
全局 consume NULL/EMPTY count = 0  ✓
```

Preview active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，且与冻结 contract 一致。无 `idempotency_key=None` 走旧兼容路径（record_usage 的 idempotency_key=None warning 路径未触发）。

---

## 14. Preview Execution Persistence（D34-11）

本轮 Preview execution 在 PG 中真实持久化并被复用：

| id | merchant_id | agent_id | lifecycle_status | has_created | has_completed |
|----|---|---|---|---|---|
| 4 | dev-merchant | draft-agent | completed | True | False |
| 5 | dev-merchant | draft-agent | completed | True | False |
| 6 | dev-merchant | draft-agent | completed | True | False |

- execution `id` 持久存在，`_report_llm_usage` 复用同一 `execution.id` 作 identity 来源，非每次重放重新产生新 execution。
- merchant/tenant ownership：`ai_preview_executions.merchant_id` = 9000 `RequestContext.merchant_id`（mock auth 运行时真实值 `dev-merchant`），非前端传入。
- 四者一致：recharge merchant_id = Preview RequestContext.merchant_id = 9100 usage report merchant_id = compute transaction merchant_id = `dev-merchant` ✓
- `lifecycle_status=completed` 稳定持久（9100 正常返回 → completed；C1：lifecycle=整次请求结果，非 stage 状态）。
- `created_at` NOT NULL（durable commit 生效，PV-0）；`completed_at` 当前为 NULL——这是 consumer 代码现状（[agents.py:343](../../../app/routers/agents.py) `_finalize_preview_execution` 只设 `lifecycle_status="completed"`，未填充 `completed_at` 列），不影响 Business Event Identity 稳定性（identity 基于稳定 `execution.id`，非 `completed_at`）。本窗口不修此 consumer 代码现状（属范围外，NO BUSINESS CODE CHANGE）。

```text
Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）✓
```

---

## 15. Cleanup（D34-13）

测试完成后以 `auto_wechat` 应用角色清理受控 fixture：

```text
DELETE compute_transactions WHERE merchant_id='dev-merchant'   → 5（4 consume + 1 recharge）
DELETE compute_accounts WHERE merchant_id='dev-merchant'       → 1
DELETE ai_preview_executions WHERE merchant_id='dev-merchant' → 3
COMMIT
```

residual 检查（全部 0，clean baseline 恢复）：

```text
compute_txns(dev-merchant)        = 0
compute_accounts(dev-merchant)    = 0
ai_preview_executions(dev-merchant) = 0
total compute_transactions         = 0
total compute_accounts             = 0
total ai_preview_executions        = 0
```

DB-BL 完整性未变：`revision=0034 / tables=61`。验证脚本经 stdin 管道执行，未写入 worktree（`git status` clean，零业务代码改动）。临时 9000/9100 进程已停止移除。

```text
residual test data = 0
```

---

## 16. D34 Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| D34-0 | Git / environment | ✅ PASS | HEAD=da3d605 / clean；LOCAL DEV，canonical PG@0034，PG 16.x，db_owner=postgres，61 表 |
| D34-1 | Application principal | ✅ PASS | current_user=auto_wechat；DATABASE_URL 应用角色；consumer 写入经 auto_wechat 角色；postgres 仅 catalog |
| D34-2 | Static consumer chain | ✅ PASS | §3 真实文件/函数链；9000→9100→9000 双 HTTP hop；identity 与冻结 contract 一致，无 drift |
| D34-3 | Business Event Identity | ✅ PASS | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，来自稳定 execution.id |
| D34-4 | Schema prerequisites | ✅ PASS | 0034 表/列/约束/索引存在；compute 幂等唯一约束存在；douyin-cs markup ratio 存在；app role 有权限 |
| D34-5 | Mock boundary | ✅ PASS | 仅 mock OpenAICompatibleClient.chat；consumer/identity/usage/compute/PG 幂等/余额检查全真实 |
| D34-6 | First execution（P-A）| ✅ PASS | P-A(id=4) → 1 consume txn(id=20)，identity 一致，balance 100000→99985，payload_evidence NOT NULL |
| D34-7 | Same-execution+same-stage replay | ✅ PASS | P-A replay → txn count 仍 1，balance 不变(99985)；id gap=21 印证 IntegrityError rollback |
| D34-8 | Distinct-execution separation（P-B）| ✅ PASS | P-B(id=5) → 1 独立 txn(id=22)，2 distinct identities，无 collision |
| D34-9 | Stage separation（primary+retry_combined）| ✅ PASS | P-R(id=6) → primary(id=23)+retry_combined(id=24)，2 distinct stage identities，warnings=['llm_retry_combined'] 真实触发 |
| D34-10 | Non-null identity | ✅ PASS | 0 null/empty idempotency_key（本轮 + 全局 ai_preview_execution:%）|
| D34-11 | Preview execution persistence | ✅ PASS | 3 行 PG 持久，lifecycle=completed，identity 基于稳定 execution.id（created_at NOT NULL；completed_at 现状未填，不影响 identity）|
| D34-12 | Application Role Hard Gate + PG transaction/balance evidence | ✅ PASS | 4 consume txns(id 20,22,23,24)，delta=-15 each，balance=99940=100000+(-15)×4，replay 不贡献 delta，app role PASS |
| D34-13 | Cleanup / residual | ✅ PASS | residual=0，DB-BL 不变(0034/61)，临时进程清理，worktree clean |

`D34-6 / D34-7 / D34-8 / D34-9 / D34-12` 均为真实 `PG_RUNTIME_VERIFIED`（非 unit test）。

---

## 17. Evidence Levels

```text
正式 0034 通过所需：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED  → 均已满足
辅助证据：SUPPLEMENTARY_RUNTIME_EVIDENCE（id gap=21 / payload_evidence NOT NULL）
静态证据：CODE_VERIFIED / STATIC_SCHEMA_VERIFIED
```

---

## 18. Out-of-P1 Reliability Findings

```text
NONE OBSERVED（本轮 consumer compute-idempotency + PG persistence + application-role path + HTTP consumer 路径验证范围内）
```

已登记的 `PREVIEW_REQUEST_RECOVERY_GAP` 属此前冻结的 OUT_OF_P1 reliability gap，本轮未触碰、未扩大。本轮**不**验证 request recovery / restart recovery / crash 后任务恢复——这些属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴，不阻断 0034 consumer PG verification。

注：本轮 P-A replay 验证的是 **same execution + same stage 的技术重放幂等**（idempotent replay safety = VERIFIED），不等于 request recovery orchestration = RESOLVED（`PREVIEW_REQUEST_RECOVERY_GAP` 保持原分类）。本轮范围内未观察到新 reliability 问题。

并发边界：本轮未执行全局 concurrent closure（`Final PostgreSQL Concurrent Closure Gate` 后续独立执行）。txn id gap（20,22,23,24）为 replay INSERT-rollback 的法证副证，非正式 concurrent test。`lack of concurrent test` 不阻断 0034。

---

## 19. Verdict

```text
0034 AI PREVIEW CONSUMER:
PG_VERIFICATION_COMPLETE_PENDING_APPROVAL
  → 独立审批通过（2026-08-11）：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
ai_preview_execution:{preview_execution_id}:{llm_call_stage}
APPLICATION_ROLE_RUNTIME_VERIFIED

Same execution + same stage replay:
NO_DOUBLE_CHARGE_VERIFIED（P-A replay → 1 txn / balance 不变）

Distinct execution separation:
VERIFIED（P-B → 独立 charge / 2 distinct identities / 无 collision）

Distinct stage separation:
VERIFIED（P-R primary + retry_combined → 同 execution 不同 stage → 2 独立 charge）
```

**独立审批窗口已裁定 APPROVED**（`P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md`）。0034 正式状态 = `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。auto_wechat canonical PG 侧三条 blocked consumers（0032/0033/0034）全部完成。P1 整体仍 OPEN / TECHNICAL_CLOSURE=PENDING（RAG Query 0005 等仍待）。

---

## 20. P1 Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

本轮完成的是 **0034 AI Preview consumer PostgreSQL verification**（候选 PG_VERIFICATION_COMPLETE_PENDING_APPROVAL），不是整个 P1 closure。仍待：独立审批窗口裁定 0034 → RAG Query 0005 → Global Active None Audit → Final PG Concurrent Closure Gate → LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP。

既有 OUT_OF_P1 reliability gaps（DAILY_REPORT/TRAINING/RAG_INGEST_RUN/RAG_INGEST_REQUEST/M05_ANALYSIS_USAGE_REPORT/PREVIEW_REQUEST/RAG_QUERY_REQUEST）继续保持原分类。

---

## 21. 边界遵守

- ✅ 未修改业务代码（NO BUSINESS CODE CHANGE）——验证脚本经 stdin 管道执行，未入 worktree；
- ✅ 未修改 migration 0034 / 未新增 repair migration / 未 stamp / 未手工 schema 修复（DB-BL 闭环，head=0034 / 61 表不变）；
- ✅ 未开始 RAG Query 0005 / Global Active None Audit / Final Concurrent Closure / RB-10 / bootstrap owner drift 修复；
- ✅ 未用 superuser 替代 app role 完成 consumer 核心写入；
- ✅ 未提交（candidate diff 保持，数据库证据/凭据/dump 未入库）；
- ✅ consumer 验证仅 mock LLM（外部非确定性边界），未 mock consumer orchestration / identity 生成 / compute charge / PG 幂等路径 / 余额检查；
- ✅ 未触碰 `PREVIEW_REQUEST_RECOVERY_GAP`（OUT_OF_P1）；
- ✅ 未真实发送抖音私信 / 微信 / 未修改 lead/customer facts；
- ✅ 未修改 Preview 业务代码 / migration / M07 Core / DB-BL / `_require_internal` / `_build_llm_reply` / 余额门禁。

---

## 22. Git / Commit

按指令：**不自行 commit**。本报告为 candidate diff，供独立审批窗口复核。数据库测试证据已清理（residual=0），无凭据/dump/probe 残留。验证脚本位于 worktree 外（`e:/work/tmp/d34/`），未入 worktree（`git status` clean）。

提交：**P1-PG-0034 独立审批窗口。**

---

## 附：本窗口独立核验证据索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| Git baseline | `git rev-parse HEAD` + `git status` | da3d605 / clean |
| 环境/principal | psql 应用角色 + /ready HTTP | auto_wechat / PG / 0034 / 61 表 / HTTP 200 |
| 静态调用链 | 代码 file:line 核验 | 无 CONTRACT_DRIFT，identity 与冻结一致，9000→9100→9000 双 HTTP hop |
| schema 前提 | catalog inspection | 0034 表/列/约束/索引 + compute 幂等唯一约束存在 |
| fixture | 应用角色 recharge | dev-merchant + 100000 tokens，baseline 0/0 |
| P-A first execution | 真实 /agents/preview（mock LLM）+ PG 查询 | 1 txn(id=20) / identity 一致 / balance 100000→99985 |
| P-A same-stage replay | 9100 同 identity 再次上报 + PG 查询 | txn count 仍 1 / balance 不变(99985) / id gap=21 |
| P-B distinct execution | 真实 /agents/preview + PG 查询 | 1 独立 txn(id=22) / 2 distinct identities / 无 collision |
| P-R stage separation | 真实 /agents/preview（offending reply 触发 retry）+ PG 查询 | primary(id=23)+retry_combined(id=24) / 2 distinct stage identities / warnings=['llm_retry_combined'] |
| non-null identity | PG count | 0 null/empty（本轮 + 全局）|
| execution persistence | PG 查询 | 3 行持久 / lifecycle=completed / identity 基于稳定 execution.id |
| application role | PG current_user + /ready | auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）|
| balance 闭合 | PG 查询 + 公式 | 99940 = 100000 + (-15)×4 ✓ |
| cleanup | 应用角色 DELETE + residual count | residual=0 / DB-BL 不变(0034/61) / worktree clean |
