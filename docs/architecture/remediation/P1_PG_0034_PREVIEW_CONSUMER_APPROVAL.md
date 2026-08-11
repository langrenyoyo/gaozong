# P1-PG-0034 — AI Preview Consumer PostgreSQL Verification 独立审批报告

> 窗口：P1-PG-0034 AI Preview Consumer PG 验证 **独立审批窗口**
> 审查对象：`docs/architecture/remediation/P1_PG_0034_PREVIEW_CONSUMER_VERIFICATION.md`（执行窗口候选结论 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`）
> 基线 commit：`da3d605256923feea201a9a0e41165783c3deeea`（验证：闭环M05素材分析0033 PostgreSQL幂等计费）
> 日期：2026-08-11
> Source of Truth：独立复现的真实 PG runtime 证据 > 冻结文档 > 执行窗口自述 > 推测

---

## Technical Decision

```text
0034 AI PREVIEW CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
ai_preview_execution:{preview_execution_id}:{llm_call_stage}

Same execution + same stage replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct execution separation:
VERIFIED

Distinct stage separation:
VERIFIED
```

**APPROVED**。全部 D34 核心 Gate 由独立审批窗口复现成立。0034 是三个 consumer 中最复杂的：9000→9100→9000 双 HTTP hop + 真实余额门禁 + primary/retry_combined 两合法 stage。D34-9 的 retry_combined 经真实 post-generation 校验（`off_platform_promise_violation`）触发，非手工调用。

---

## Git / Scope

```text
HEAD = da3d605256923feea201a9a0e41165783c3deeea
git status（审批前）= AGENTS.md(M) + CLAUDE.md(M) + 验证报告(??)，均为执行窗口 candidate
git diff --stat = AGENTS.md 1 行 + CLAUDE.md 1 行（0034 状态同步）
```

Scope Gate 确认：
- 业务代码无修改；migration 无修改；M07 Core 无修改；DB-BL 无修改；
- 审批取证脚本写在 worktree 外（`e:/work/tmp/d34/`），经临时容器 `--rm` 挂载执行，未入 worktree（`git status` 干净）；
- 无凭据/dump/snapshot 入库；未开始 RAG Query 0005 / bootstrap drift 修复；
- 临时取证容器 `--rm` 用后即弃，无残留进程。

---

## memory artifact classification

执行窗口候选新增 `pg-verification-preview-0034-key-config.md`。独立核验结果：

```text
A. 在 worktree / Git diff 中？  否
B. 在外部 memory/工具侧记录？  是（C:\Users\A\.claude\projects\e--work-project-auto-wechat\memory\，type: reference）
C. 实际不存在？  否（文件存在，但在外部 memory 目录，非 worktree）
```

```text
NOT PART OF GIT CANDIDATE
```

该文件是外部 memory 侧的配置发现记录（对未来 consumer PG verification 有复用价值），不属于本轮代码库落地产物，不纳入 Git scope 审查。其记录的配置事实（双 HTTP hop / 余额门禁 / token 非空 / retry 触发 / replay seam）经本审批独立代码核验与 runtime 复现，与当前代码一致。

---

## CLAUDE / AGENTS pre-approval classification

```text
CLAUDE.md (候选 diff)：
  Preview 0034 = PG_VERIFICATION_COMPLETE_PENDING_APPROVAL（执行窗口完成 2026-08-11，未经独立审批，不等于 PG_VERIFIED）

AGENTS.md (候选 diff)：
  Preview 0034 = PG_VERIFICATION_COMPLETE_PENDING_APPROVAL（执行窗口完成 2026-08-11，...全 PASS；未经独立审批，不等于 PG_VERIFIED）
```

两份治理文档均准确记录为 `PENDING_APPROVAL` 候选状态，**未越权**提前宣称 `PG_RUNTIME_VERIFIED` / `APPROVED` / `CLOSED`。属治理文档自治同步（记录执行窗口完成 + 标注未经独立审批），不影响 runtime 审批。本审批通过后同步为正式批准状态。

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
ai_preview_executions / compute_transactions / compute_accounts 对 auto_wechat = INSERT,SELECT,UPDATE,DELETE
```

9000 启动日志独立确认 `db_schema stage=startup_skip_create_all backend=postgresql`（`ensure_runtime_schema` PG 分支不调 create_all，满足 CLAUDE.md 硬约束 #2）。9000 `DATABASE_URL=postgresql+psycopg://auto_wechat@...`（应用角色），consumer 计费写入全程 auto_wechat principal。

```text
NOT SQLite / NOT superuser-as-consumer / NOT staging / NOT production
```

`/ready`（应用角色）HTTP 200：`backend=postgresql / db_connect=pass / database_name=auto_wechat / alembic_revision=0034 / critical_tables(douyin_leads,sales_staff)=pass`。

```text
postgres PASS / auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）
```

---

## Static Preview Chain

**关键架构事实（独立核验）**：0034 是 9000→9100→9000 双 HTTP hop——与 0032（9100 ComputeUsageClient→9000 单 hop）同模式但入口在 9000 `/agents/preview`，PV-0 execution 在 9000 侧创建。与 0033（进程内直接调 record_usage，无 HTTP）不同。

独立定位当前代码（commit `da3d605`）逐节点核验：

```text
9000 POST /agents/preview                   app/routers/agents.py:231 preview_agent()
  → :311 _create_preview_execution(db, context.merchant_id, agent_id)   [PV-0 durable before 9100/LLM]
    → app/routers/agents.py:61-76 AiPreviewExecution(merchant_id, lifecycle_status="running") + :74 db.commit()
    → return execution.id
  → :312 request_payload["preview_execution_id"] = _preview_exec_id       [透传到 9100]
  → :315 get_xg_douyin_ai_cs_client().suggest_reply(...)                  [9000→9100 HTTP，XgDouyinAiCsClient._post_json X-Internal-Service-Token]
    → app/services/xg_douyin_ai_cs_client.py:52 suggest_reply() → /douyin/reply-suggestion
      → 9100 apps/xg_douyin_ai_cs/routers/ai_reply.py:20 create_reply_suggestion_by_body()（require_internal_service_token 守卫）
        → apps/xg_douyin_ai_cs/services/reply_decision_service.py:628 build_reply_suggestion()
          → :981 _build_llm_reply()
            → :1020 OpenAICompatibleClient()  / :1026 ComputeUsageClient().check_balance(merchant_id)  [9100→9000 余额检查 HTTP，真实余额门禁]
            → :1027-1055 balance <= 0 → 阻断 LLM（返回 insufficient_balance，非 mock）
            → :1060 client.chat(messages)                                    [★ 唯一 mock 边界]
            → :1160 _report_llm_usage(llm_call_stage="primary")
            → :1205 off_platform_promise = _off_platform_promise_violation(reply_text)  [真实 post-generation 校验]
            → :1223 条件命中 → :1224 _build_llm_combined_retry_messages / :1234 client.chat(retry_messages)
            → :1236-1242 _report_llm_usage(llm_call_stage="retry_combined")
              → :3763 _report_llm_usage()
                → :3788 preview_execution_id = getattr(request, "preview_execution_id", None)
                → :3807-3810 idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"
                → :3814 ComputeUsageClient().report_usage(idempotency_key=...)  [9100→9000 HTTP]
                  → apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 report_usage()
                    → :163 base_url=os.environ["AUTO_WECHAT_9000_BASE_URL"] / :172 USAGE_PATH="/internal/compute/usage"
                    → POST {base_url}/internal/compute/usage（payload 含 idempotency_key，X-Internal-Token 校验）
                      → app/routers/compute.py:458 internal_router.post("/compute/usage")
                        → :467 compute_service.record_usage(idempotency_key=payload.idempotency_key)
                          → apps/compute/services.py:615 record_usage()
                            → :692-713 INSERT ComputeTransaction(idempotency_key, payload_evidence) :716 flush
                            → :718-727 flush 成功→ get_or_create_account + _write_transaction_balance_only（原子扣费）+ :725 commit
                            → :728-769 IntegrityError → rollback → 读已存在行
                              → :747 相同 payload_evidence → idempotent_replay（不二次扣费，:756 return）
                              → :757 不同 → idempotency_conflict
                            → PostgreSQL compute_transactions / compute_accounts
  → :343 _finalize_preview_execution(db, _preview_exec_id, "completed")  [9100 正常返回→completed；:322 failed]
```

**全程未发现 CONTRACT_DRIFT**。

---

## Preview Durability

[agents.py:61-76](app/routers/agents.py) `_create_preview_execution` 在 9100 HTTP call 前 `db.add + db.commit + db.refresh` 持久化 `AiPreviewExecution`，返回稳定 `execution.id`。PV-0 合同满足：execution_id 在 9100 LLM 计费副作用前已 durable commit。

Business Event Identity 不基于 request attempt / HTTP retry / random per-call UUID / 非持久临时对象——基于稳定 PG 持久化 `execution.id`。

---

## Business Event Identity

真实生成代码 [reply_decision_service.py:3807-3810](apps/xg_douyin_ai_cs/services/reply_decision_service.py)：

```python
elif preview_execution_id is not None:
    # ★ P1 Stage 5G-2：Preview 独立分支（独立 namespace ai_preview_execution，不影响 Auto Reply）
    # cardinality 1:N(2)，key 含 llm_call_stage 区分 primary/retry_combined
    idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"
```

- f-string 位置：`_report_llm_usage` 内部；
- `preview_execution_id` 来源：`AiPreviewExecution.id`（[models.py:1350](app/models.py)），由 9000 `_create_preview_execution` 在 9100 call 前 durable commit（PV-0）；
- stage 固定来源：`llm_call_stage` 参数，合法 billable stage = `primary`（:1166）/ `retry_combined`（:1242）；
- 非时间戳推导、非运行时计算序号（`call_count` 不参与，进程重启/重试后稳定复用同一 execution.id）；
- billing truth 归 M07 `ComputeTransaction`（`AiPreviewExecution` 无 `is_billed`/`billing_status`，经列定义 + migration 0034 核验）；
- C4 mixed identity 防护（:3792-3798）：`run_id`/`attempt_count` 与 `preview_execution_id` 同时存在 → warning + 退 None；
- partial identity 防护（:3801-3806）：一个有一个无 → warning + 不生成错误 key。

```text
ai_preview_execution:{preview_execution_id}:{llm_call_stage}
```

与 `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #7 冻结 contract 一致，无 drift。

---

## Mock Boundary

```text
mocked   = OpenAICompatibleClient.chat  （9100 最终外部 LLM 边界，唯一 mock）
not_mocked = 9000 /agents/preview 路由（含 mock auth → RequestContext.merchant_id=dev-merchant）
           / PV-0 execution 持久化（AiPreviewExecution durable commit）
           / 9000→9100 HTTP（XgDouyinAiCsClient.suggest_reply → /douyin/reply-suggestion，X-Internal-Service-Token）
           / 9100 _build_llm_reply orchestration
           / balance check（9100→9000 /internal/compute/balance 真实 HTTP 查询，余额>0 才放行 LLM）
           / llm_call_stage selection（primary / retry_combined 由真实 post-generation 校验决定）
           / _report_llm_usage
           / Business Event Identity 生成（f-string 构造）
           / ComputeUsageClient.report_usage（9100→9000 HTTP）
           / 9000 /internal/compute/usage（真实 uvicorn HTTP 服务 + 真实 route）
           / record_usage INSERT / 原子扣费 / IntegrityError 幂等路径
           / PostgreSQL uniqueness（uk_compute_transactions_merchant_idempotency）
           / compute account balance
```

关键 compute 路径未被 mock。consumer（9100）与 9000 经真实 loopback HTTP（urllib/httpx → TCP → uvicorn → FastAPI → route → record_usage），非 TestClient 旁路。证据等级 `PG_RUNTIME_VERIFIED` + `APPLICATION_ROLE_RUNTIME_VERIFIED`。

---

## Schema Preconditions

canonical PG@0034 独立 catalog inspection：

| 对象 | 核验 |
|---|---|
| `ai_preview_executions` 表 | ✅ EXISTS（6 列: id, merchant_id, agent_id, lifecycle_status, created_at, completed_at）|
| `id` PK `ai_preview_executions_pkey` | ✅ |
| `idx_ai_preview_executions_merchant` 索引（merchant_id）| ✅ |
| `ck_ai_preview_executions_status` CHECK（lifecycle_status ∈ running/completed/failed）| ✅ |
| NOT NULL 列 | ✅ id, merchant_id, lifecycle_status, created_at（agent_id/completed_at nullable）|
| `compute_transactions` 唯一约束 `uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)` | ✅ EXISTS（驱动 IntegrityError 幂等路径）|
| `compute_transactions.idempotency_key` / `payload_evidence` / `llm_call_stage` 列 | ✅ |
| `compute_markup_ratios` 行 `douyin-cs` | ✅ enabled=true / consumption_mode=actual / markup_basis_points=0（→ `calculate_billed_tokens(total,0)=total`，真实代码确认）|
| `ai_preview_executions_id_seq` / `compute_transactions_id_seq` 序列 | ✅ |
| application role 对 `ai_preview_executions`/`compute_transactions`/`compute_accounts` INSERT/SELECT/UPDATE/DELETE | ✅ |

migration 0034：revision=`0034`，down_revision=`0033`，create_date=2026-08-10。新建 `ai_preview_executions` 表（6 列 + PK + CHECK + merchant 索引），不激活 dormant 表，不引入 attempt_count。0030→0032→0033→0034 线性单链，0034 是 head。

```text
SCHEMA_PREREQUISITE = PASS（≠ PG_VERIFIED，仅 precondition）
```

---

## Merchant Identity

5 层身份一致性独立确认：

```text
Preview RequestContext.merchant_id   = dev-merchant（NEWCAR_AUTH_ENABLED=false → build_mock_context，非前端传入）
9100 balance-check merchant_id        = dev-merchant（_build_llm_reply:1027 check_balance(merchant_id=str(request.merchant_id))）
9100 usage-report merchant_id         = dev-merchant（_report_llm_usage → report_usage(merchant_id=request.merchant_id)）
9000 compute ledger merchant_id       = dev-merchant（compute_transactions.merchant_id）
controlled recharge merchant_id       = dev-merchant（fixture）
all_layers_identical = True
```

```text
NO FIXTURE_IDENTITY_MISMATCH
```

---

## Balance Gate

真实生产路径余额门禁独立确认 [reply_decision_service.py:1026-1055](apps/xg_douyin_ai_cs/services/reply_decision_service.py)：

```python
_balance_client = ComputeUsageClient()
balance = _balance_client.check_balance(merchant_id=str(request.merchant_id or ""))
if balance is not None and balance <= 0:
    return ReplySuggestionResponse(... match_level="insufficient_balance", manual_required=True, ...)
```

- `check_balance` 经 9100→9000 真实 HTTP（`/internal/compute/balance/{merchant_id}`，X-Internal-Token），走真实 `get_summary`→`get_or_create_account`；
- 余额 ≤ 0 阻断 LLM 执行/usage reporting（返回 `insufficient_balance`）；
- **未 mock check_balance、未绕过余额门禁**。

本轮 fixture 预充值 100000 使余额 > 0 放行 LLM——是 fixture 前置条件，非 consumer 逻辑 mock、非绕过门禁。

---

## Controlled Recharge Verification

```text
balance_before_fixture = 0
recharge amount        = 100000
balance_after_recharge = 100000
recharge merchant      = dev-merchant（与 Preview RequestContext 一致）
```

充值经 `auto_wechat` 应用角色写入（等价 `create_mock_recharge_order` 语义：recharge 流水 + 建账），是 TEST FIXTURE PRECONDITION，**非 consumer 业务修改**。

---

## Compute Internal Token prerequisite

独立核验 [compute_usage_client.py:154-157](apps/xg_douyin_ai_cs/services/compute_usage_client.py)：

```python
@property
def enabled(self) -> bool:
    return bool(self.base_url.strip()) and bool(self.internal_token.strip())
```

`ComputeUsageClient.enabled` 要求有效的 9000 base URL（`AUTO_WECHAT_9000_BASE_URL`）和**非空** internal token（`COMPUTE_INTERNAL_TOKEN`）才实际 report usage。dev 环境 token 留空 → enabled=False → 跳过上报（无计费）。本轮设非空受控 token `d34-approve-token`，9000 `_require_internal` 与 9100 `ComputeUsageClient` 一致。

```text
PREVIEW COMPUTE USAGE CONFIG PREREQUISITE:
BASE URL + INTERNAL TOKEN

本轮只证明：LOCAL VERIFICATION CONFIGURED AND WORKING
不推广成：STAGING/PRODUCTION CONFIG VERIFIED（staging/prod = RUNTIME_UNKNOWN）
未因 local empty-token 假设修改代码。
```

---

## A First Execution

独立受控 fixture（before snapshot 区分 fixture 与 existing data：snap_before txn/acct/prev = 0/0/0，cleanup 后 dev-merchant 全清）：

```text
merchant_id = dev-merchant（mock auth 运行时真实值）
recharge    = 100000（fixture 前置）
P-A execution_id = 10（ai_preview_executions.id，真实 PG 序列持久化，非硬编码）
identity = ai_preview_execution:10:primary
```

从真实 consumer 入口 `POST /agents/preview`（message="有没有奥迪A6？"，mock auth → merchant_id=dev-merchant，agent_id=None→draft-agent）：

```text
HTTP 200 / success=True / source=llm / manual_required=False
consumer 返回：reply_text=干净合规回复
9000→9100 HTTP 200（httpx POST /douyin/reply-suggestion）
balance check 通过（100000 > 0）
```

PG 直查证据：

```text
transaction count (identity=ai_preview_execution:10:primary) = 1   ✓
id=36 | idempotency_key=ai_preview_execution:10:primary | transaction_type=consume
delta_tokens=-15 | balance_after_tokens=99985 | capability_key=douyin-cs
model=d34-approve-mock-llm | llm_call_stage=primary | actual_tokens=15
usage_measurement_method=provider_tokens | payload_evidence IS NOT NULL
```

Balance（markup=0 → billed=actual=15）：

```text
balance_before = 100000   （fixture 充值后）
delta          = -15      （billed_tokens=calculate_billed_tokens(15,0)=15，由真实代码推导，非硬编码期望）
balance_after  = 99985    ✓
```

---

## A Same-stage Replay

对**同一 execution_id=10、同一 primary stage**，经 9100 `/douyin/reply-suggestion` 直调传入同一 `preview_execution_id=10`（identity 由 `_report_llm_usage` 内部 f-string 自然重新生成，非手工构造 key，非直接调 `record_usage`，非手工 POST duplicate）：

```text
identity 自然重新生成：ai_preview_execution:10:primary
9000 record_usage：INSERT 触发 uk_compute_transactions_merchant_idempotency 唯一冲突 → IntegrityError → rollback → idempotent_replay 分支
运行日志：compute_idempotency stage=replay merchant_id=dev-merchant key=ai_preview_execution:10:primary txn_id=36
```

PG 权威证据（不靠 HTTP 200）：

```text
transaction count (identity=ai_preview_execution:10:primary) = 1   （未产生第 2 行）✓
balance_after_replay = 99985 = balance_after_first   ✓
replay_reuses_same_execution_id = True   （复用同一持久化 execution.id，非新建 execution）
```

```text
NO_DOUBLE_CHARGE_VERIFIED
```

Replay seam 合法性：`/douyin/reply-suggestion` 是 9100 真实 consumer 端点，传入同一 `preview_execution_id` 对应 crash 后 usage report 重试场景（9100 完成 LLM + M07 已 commit，但 HTTP 响应丢失 → client 重试同 execution_id → 同 key → IntegrityError → idempotent_replay）。**非**重新调 `/agents/preview`（会创建新 execution）。

---

## B Distinct Execution

创建另一 preview execution（message="你们店有宝马X5吗？"），同一 `primary` stage，从真实 consumer 入口执行：

```text
P-B execution_id = 11
identity = ai_preview_execution:11:primary
```

PG 证据：

```text
transaction count (identity=ai_preview_execution:11:primary) = 1   ✓
id=38 | delta_tokens=-15 | balance_after_tokens=99970 | payload_evidence IS NOT NULL
```

```text
identity(A) = ai_preview_execution:10:primary  !=  ai_preview_execution:11:primary = identity(B)
different execution → independent legitimate charge   VERIFIED
```

---

## R Distinct-stage Verification

P-R 用 message="STAGE_TEST 有没有奥迪A6？"（mock 检测 STAGE_TEST 标记 → primary 返回 JSON reply_text 含 `OFF_PLATFORM_PROMISE_KEYWORDS` 违规短语"我把报价发您手机上..."，不含否定语境词 → `off_platform_promise_violation` 命中 → 真实 retry → retry_combined 返回干净合规回复，不触发第三次）：

```text
P-R execution_id = 12
lifecycle_status = completed
warnings = ['llm_retry_combined']（retry 真实触发，由真实 post-generation 校验决定，非手工构造）
```

同一 `execution_id=12`，两个不同 legitimate billable stage：

**P-R primary**：
```text
identity = ai_preview_execution:12:primary
transaction count = 1   ✓
id=39 | delta_tokens=-15 | balance_after_tokens=99955 | llm_call_stage=primary | payload_evidence IS NOT NULL
```

**P-R retry_combined**：
```text
identity = ai_preview_execution:12:retry_combined
transaction count = 1   ✓
id=40 | delta_tokens=-15 | balance_after_tokens=99940 | llm_call_stage=retry_combined | payload_evidence IS NOT NULL
```

```text
identity(primary)       = ai_preview_execution:12:primary
identity(retry_combined) = ai_preview_execution:12:retry_combined
identity_distinct = True（same execution + different legitimate billable stage）
2 distinct Business Events / 2 legitimate charges / same execution 不互相吞没
```

```text
same execution + different legitimate billable stage → independent billing events   VERIFIED
```

### retry_combined 触发真实性

- **trigger condition**：mock primary reply_text 含 `OFF_PLATFORM_PROMISE_KEYWORDS`（"报价发您手机"）且不含 `OFF_PLATFORM_NEGATION_KEYWORDS`；
- **relevant code branch**：[reply_hard_rules.py:99-113](apps/xg_douyin_ai_cs/services/reply_hard_rules.py) `off_platform_promise_violation` → [reply_decision_service.py:1205](apps/xg_douyin_ai_cs/services/reply_decision_service.py) `off_platform_promise` → :1223 命中条件 → :1224 `_build_llm_combined_retry_messages` → :1234 `client.chat(retry_messages)` → :1236-1242 `_report_llm_usage(stage="retry_combined")`；
- **primary warning/violation evidence**：`warnings=['llm_retry_combined']`、日志 `retry_reason_code=llm_retry_combined`、`compute_usage stage=reported ... llm_call_stage=retry_combined`；
- **second LLM invocation**：retry_messages 含 `retry_reason`/`bad_reply`/`请重新生成`，第二次 `client.chat` 真实执行；
- **retry_combined usage reporting**：`_report_llm_usage(stage="retry_combined")` 真实调用，PG txn id=40。

retry_combined 由真实 `_build_llm_reply` post-generation 校验逻辑触发，**非直接调 `_report_llm_usage("retry_combined")`、非手工构造 retry key、非 monkeypatch stage selector、非直接调用 compute**。

---

## Transaction / Balance

PG 直查（auto_wechat 应用角色只读）全部 consume txns for `dev-merchant`：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 36 | `ai_preview_execution:10:primary` | consume | -15 | 99985 | douyin-cs | d34-approve-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 38 | `ai_preview_execution:11:primary` | consume | -15 | 99970 | douyin-cs | d34-approve-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 39 | `ai_preview_execution:12:primary` | consume | -15 | 99955 | douyin-cs | d34-approve-mock-llm | primary | 15 | provider_tokens | NOT NULL |
| 40 | `ai_preview_execution:12:retry_combined` | consume | -15 | 99940 | douyin-cs | d34-approve-mock-llm | retry_combined | 15 | provider_tokens | NOT NULL |

```text
account: merchant_id=dev-merchant / balance_tokens=99940
final balance = recharge(100000) + delta(P-A primary -15) + delta(P-B primary -15) + delta(P-R primary -15) + delta(P-R retry_combined -15)
              = 100000 + (-15)×4 = 99940 ✓
P-A replay does not contribute another delta ✓
4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费
```

---

## Sequence Gap Classification

```text
consume_txn_ids = [36, 38, 39, 40]   （id=37 缺失）
```

明确分类：

```text
SEQUENCE ID GAP = SUPPLEMENTARY ONLY
```

id=37 被 P-A replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退）→ `idempotent_replay` 分支（`compute_idempotency stage=replay txn_id=36` 日志佐证）。

```text
gap != idempotency proof
```

PostgreSQL sequence 正常情况下本就允许 gap。正式证明仍是：`same identity` + `row count remains 1` + `balance unchanged`（均已满足）。

---

## Non-null Identity

```text
compute_transactions WHERE merchant_id='dev-merchant' AND transaction_type='consume'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0   ✓
全局 ai_preview_execution:% identity NULL/EMPTY count = 0   ✓
全局 consume NULL/EMPTY count = 0   ✓
```

Preview active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，无 `idempotency_key=None` 走旧兼容路径。

---

## Preview Persistence

E-A/E-B/E-R 对应 Preview execution 在 PG 中真实持久化并被 replay 复用：

| id | merchant_id | agent_id | lifecycle_status | created_at | completed_at |
|----|---|---|---|---|---|
| 10 | dev-merchant | draft-agent | completed | NOT NULL | NULL |
| 11 | dev-merchant | draft-agent | completed | NOT NULL | NULL |
| 12 | dev-merchant | draft-agent | completed | NOT NULL | NULL |

- execution `id` 持久存在，`_report_llm_usage` 复用同一 `execution.id` 作 identity 来源，`replay_reuses_same_execution_id=True`；
- `lifecycle_status=completed` 稳定持久（C1：整次请求结果，非 stage 状态）；
- `created_at` NOT NULL（PV-0 durable commit 生效）；
- `completed_at` 当前为 NULL（consumer 代码现状，`_finalize_preview_execution` 只设 lifecycle_status，未填 completed_at）。

```text
Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）✓
```

---

## No Real Send Boundary

```text
Preview only
```

- 无 Douyin 发送（preview 仅生成回复建议，`auto_send=False`，不经任何发送 gate）；
- 无微信发送；无自动回复；无 lead status change；无 customer fact persistence outside preview contract；无 managed mode 切换。

Preview 路径未产生真实出站副作用。

---

## Cleanup

审批 fixture 经 `auto_wechat` 应用角色事务内清理（before/after snapshot 区分，仅清 dev-merchant fixture，未误删 existing data）：

```text
DELETE compute_transactions WHERE merchant_id='dev-merchant'   → 5（4 consume + 1 recharge）
DELETE compute_accounts WHERE merchant_id='dev-merchant'       → 1
DELETE ai_preview_executions WHERE merchant_id='dev-merchant'  → 3
```

residual 检查（全 0，clean baseline 恢复）：

```text
compute_txns(dev-merchant)         = 0
compute_accounts(dev-merchant)     = 0
ai_preview_executions(dev-merchant) = 0
total compute_transactions         = 0
total compute_accounts             = 0
total ai_preview_executions         = 0
```

全局确认：`GLOBAL_PREV_TXNS=0`、`GLOBAL_PREV_NULL_EMPTY=0`、`GLOBAL_ALL_TXNS=0`、`RESIDUAL_DEV_MERCHANT=0`。

DB-BL 完整性未变：`revision=0034 / tables=61`。临时 9000/9100 进程随容器 `--rm` 退出，脚本在 worktree 外，`git status` 干净。

```text
residual test data = 0
```

---

## D34-* Verdict

| Gate | 验证内容 | 结论 | 证据等级 |
|---|---|---|---|
| D34-0 | Git / environment | ✅ PASS | HEAD=da3d605 / clean；LOCAL DEV，canonical PG@0034，PG 16.14，db_owner=postgres，61 表 |
| D34-1 | Application principal | ✅ PASS | current_user=auto_wechat；consumer 写入经 auto_wechat 角色；postgres 仅 catalog |
| D34-2 | Static consumer chain | ✅ PASS | CODE_VERIFIED；9000→9100→9000 双 HTTP hop；identity 与冻结 contract 一致，无 drift |
| D34-3 | Business Event Identity | ✅ PASS | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，来自稳定 execution.id，C4 mixed identity + partial identity 防护 |
| D34-4 | Schema prerequisites | ✅ PASS | STATIC_SCHEMA_VERIFIED；0034 表/列/约束/索引 + compute 幂等唯一约束 + douyin-cs markup ratio |
| D34-5 | Mock boundary | ✅ PASS | 仅 mock OpenAICompatibleClient.chat；consumer/identity/usage/compute/PG 幂等/余额检查全真实 |
| D34-6 | First execution（A）| ✅ PASS | PG_RUNTIME_VERIFIED；A(id=10) → 1 consume txn(id=36)，identity 一致，balance 100000→99985，payload_evidence NOT NULL |
| D34-7 | Same-execution+same-stage replay | ✅ PASS | PG_RUNTIME_VERIFIED；A replay → txn count 仍 1，balance 不变(99985)，id gap=37 印证 IntegrityError，replay 复用同一 execution.id |
| D34-8 | Distinct-execution separation（B）| ✅ PASS | PG_RUNTIME_VERIFIED；B(id=11) → 1 独立 txn(id=38)，2 distinct identities，无 collision |
| D34-9 | Distinct stage | ✅ PASS | PG_RUNTIME_VERIFIED；R(id=12) → primary(id=39)+retry_combined(id=40)，2 distinct stage identities，warnings=['llm_retry_combined'] 真实 post-generation 校验触发 |
| D34-10 | Non-null identity | ✅ PASS | 0 null/empty（本轮 + 全局 ai_preview_execution:% + 全局 consume）|
| D34-11 | Preview execution persistence | ✅ PASS | 3 行 PG 持久，lifecycle=completed，replay 复用同一 execution.id（created_at NOT NULL；completed_at 现状未填，不影响 identity）|
| D34-12 | PG transaction / balance | ✅ PASS | PG_RUNTIME_VERIFIED；4 consume txns(id 36,38,39,40)，delta=-15 each，balance=99940=100000+(-15)×4，replay 不贡献 delta，closure_ok=True |
| D34-13 | Cleanup / residual | ✅ PASS | residual=0，DB-BL 不变(0034/61)，临时进程清理，worktree clean |

`D34-6 / D34-7 / D34-8 / D34-9 / D34-12` 均为真实 `PG_RUNTIME_VERIFIED`（非 unit test）。`D34-9 非 N/A`（两个真实 billable stage 均经真实 retry 路径产生）。

---

## Evidence Levels

```text
正式 0034 通过所需：PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED  → 均已满足
辅助证据：SUPPLEMENTARY_RUNTIME_EVIDENCE（id gap=37 / payload_evidence NOT NULL / idempotent replay 日志路径）
静态证据：CODE_VERIFIED / STATIC_SCHEMA_VERIFIED
```

---

## 0034 Final Status

```text
0034 AI PREVIEW CONSUMER:
PG_RUNTIME_VERIFIED
APPLICATION_ROLE_RUNTIME_VERIFIED

Business Event Identity:
ai_preview_execution:{preview_execution_id}:{llm_call_stage}

Same execution + same stage replay:
NO_DOUBLE_CHARGE_VERIFIED

Distinct execution separation:
VERIFIED

Distinct stage separation:
VERIFIED
```

---

## 0032 / 0033 / 0034 Aggregate Status

```text
0032 Daily Report       = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-10 独立审批 APPROVED）
0033 M05 Material Analysis = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-11 独立审批 APPROVED）
0034 AI Preview         = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-11 独立审批 APPROVED）

AUTO_WECHAT 0032/0033/0034 CONSUMER PG VERIFICATION: COMPLETE
```

auto_wechat canonical PG 侧三条 blocked consumers 全部完成。

---

## P1 Remaining Work

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

0034 通过不改变 P1 整体状态。仍待：

```text
RAG Query 0005 PG verification（PENDING_PG_VERIFICATION，BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT）
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
Global Active None Audit
Final PostgreSQL Concurrent Closure Gate
```

既有 OUT_OF_P1 reliability gaps（含 `PREVIEW_REQUEST_RECOVERY_GAP`）继续保持原分类。下一阶段不自动选择。

---

## PREVIEW_REQUEST_RECOVERY_GAP

```text
PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1（保持原分类，未升级）
```

本轮 P-A replay 验证的是 **same execution + same stage 的技术重放幂等**（idempotent replay safety = VERIFIED），不等于 request recovery orchestration = RESOLVED。

```text
Idempotent replay safety: VERIFIED
Recovery orchestration gap: UNCHANGED / OUT_OF_P1
```

本轮未验证 request durable recovery / restart recovery / crash 后任务恢复 / retry orchestration redesign——属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴。本轮范围内未观察到新 reliability 问题。并发边界非 Final Closure，`lack of concurrent test` 不阻断 0034。

---

## RB-10

```text
RB-10 CLEANUP = NOT AUTHORIZED
```

legacy backup + dump 保留。

---

## Commit Authorization

0034 审批通过，授权执行窗口做一次 0034 closure commit。允许纳入：

```text
P1_PG_0034_PREVIEW_CONSUMER_VERIFICATION.md
P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md
CLAUDE.md
AGENTS.md
```

状态从 `PG_VERIFICATION_COMPLETE_PENDING_APPROVAL` 同步为 `PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED`。

该 commit 不得包含：RAG Query 0005 / bootstrap owner drift 修复 / 业务代码 / migration / M07 Core / recovery gap 修复。

建议 commit message：`验证：闭环AI回复预览0034 PostgreSQL幂等计费`（实际按仓库规范）。

---

## 结论

0034 AI Preview Consumer 在真实 PostgreSQL + `auto_wechat` Application Principal 下：从真实 `/agents/preview` 入口产生批准的 Business Event Identity `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，经真实 9000→9100→9000 双 HTTP hop + 真实余额门禁 + 真实 9000 Compute Core 持久化；同一 execution 同 stage 重放不产生第二次扣费，不同 execution 独立计费，同一 execution 不同合法 stage（primary/retry_combined，经真实 post-generation 校验触发 retry）独立计费。5 层 merchant identity 一致。全部门限独立复现通过。

auto_wechat canonical PG 侧三条 blocked consumers（0032/0033/0034）全部完成 PG verification。

**审批完成，停止。不自行开始下一阶段（RAG Query 0005）。**
