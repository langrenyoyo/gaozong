# P1-F1 Trusted Reply-Suggestion Idempotency — 实施报告

> 任务：`P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-IMPLEMENTATION`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`BLOCKED_BY_F1`）
> 前序设计审批：`P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，Candidate A）
> Governance checkpoint：`7ef246e`（设计：批准Trusted Reply-Suggestion幂等身份方案，未 push）
> 基线 commit：`7ef246e`（实施前 HEAD）
> 日期：2026-08-11
> 窗口性质：实施 + 隔离 PG runtime 验证（candidate diff，未 commit implementation，未 push）
> Source of Truth：真实双库 PG runtime 证据（auto_wechat@0034 + xg_douyin_ai_cs@0005，真实 9000+9100 双 uvicorn + loopback HTTP，应用角色 `auto_wechat`） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| §0 Governance checkpoint | ✅ PASS（commit 7ef246e，F-1=DESIGN_APPROVED/IMPLEMENTATION_PENDING）|
| Candidate A 实施 | ✅ PASS（durable execution + preview_execution_id 透传 + finalize + fail-closed）|
| C1 shared helper 直接 import | ✅ APPLIED（OPTIONAL，未抽 Service 层）|
| C2 fail-closed runtime gate | ✅ PASS（F1-PG-5 IDENTITY_CREATION_FAIL_CLOSED=VERIFIED）|
| C3 证据命名精度 + F1-PG-6 runtime | ✅ PASS（SAME_EXECUTION_SAME_STAGE_REPLAY 非 HTTP_REQUEST_REPLAY；None regression runtime）|
| C4 PREVIEW_REQUEST_RECOVERY_GAP 覆盖 | ✅ APPLIED（扩展覆盖 trusted reply-suggestion）|
| C5 AiPreviewExecution naming debt | ✅ APPLIED（NON_BLOCKING 登记）|
| F1-PG-1 First | ✅ PASS |
| F1-PG-2 Same Execution + Same Stage Replay | ✅ PASS（NO_DOUBLE_CHARGE_VERIFIED）|
| F1-PG-3 Intentional New Generation | ✅ PASS（DISTINCT_EVENT_VERIFIED）|
| F1-PG-4 Stage Separation | ✅ PASS（primary + retry_combined）|
| F1-PG-5 Fail-Closed Runtime | ✅ PASS（IDENTITY_CREATION_FAIL_CLOSED=VERIFIED）|
| F1-PG-6 ACTIVE None Regression | ✅ PASS（TRUSTED_PROXY_ACTIVE_NONE_REGRESSION=0）|

**Verdict（候选）**：

```text
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY
= RESOLVED_PENDING_APPROVAL

TRUSTED REPLY-SUGGESTION BUSINESS EVENT IDENTITY
= ai_preview_execution:{preview_execution_id}:{llm_call_stage}

SAME EXECUTION + SAME STAGE = NO_DOUBLE_CHARGE_VERIFIED
INTENTIONAL NEW GENERATION = DISTINCT_EVENT_VERIFIED
DISTINCT LEGITIMATE STAGE = VERIFIED
IDENTITY CREATION FAIL-CLOSED = VERIFIED
ACTIVE NONE REGRESSION = 0
```

```text
GLOBAL_ACTIVE_NONE_AUDIT = FAILED（保持，须 F-1 审批后重跑）
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_PENDING_F1_APPROVAL_AND_GLOBAL_REAUDIT
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

---

## 1. Governance Checkpoint

§0 设计审批治理 checkpoint：

```text
commit = 7ef246e（设计：批准Trusted Reply-Suggestion幂等身份方案）
未 push
worktree（该 checkpoint 时刻）= 仅 design + design approval 两份文档，无业务代码
```

正式状态同步为：

```text
F-1 = DESIGN_APPROVED / IMPLEMENTATION_PENDING
GLOBAL_ACTIVE_NONE_AUDIT = FAILED
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_F1
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

该 checkpoint 只回答："为什么允许实施 Candidate A"——见 `P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN_APPROVAL.md` §29（为什么 APPROVED_WITH_CORRECTIONS 而非 CHANGES_REQUIRED）+ §30（Implementation Authorization）。

---

## 2. Approved Design

```text
Preferred Strategy = Candidate A
  Trusted Reply-Suggestion
  → server-side durable AiPreviewExecution（复用 0034 表，无新 migration）
  → preview_execution_id
  → 9000→9100 suggest_reply
  → ai_preview_execution:{preview_execution_id}:{llm_call_stage}
  → compute idempotent charge
```

正式采用 Business Event Contract（§2）：

```text
one merchant-side manually triggered trusted reply suggestion
= one durable AiPreviewExecution

same durable execution + same stage → SAME billable event → replay 不重复扣
intentional new generation → NEW AiPreviewExecution → 独立合法计费
new customer message + new generation → NEW AiPreviewExecution
retry_combined → SAME execution → 不同 legitimate stage → 独立合法计费
```

冻结（§0）：

```text
9100 = NO CHANGE
migration = NO CHANGE
external API breaking = NO
compute core = NO CHANGE
```

---

## 3. Applied Corrections C1-C5

| Correction | 状态 | 应用 |
|---|---|---|
| C1 shared helper 直接 import | ✅ APPLIED（OPTIONAL）| `douyin_ai_cs_proxy.py` 直接 `from app.routers.agents import _create_preview_execution, _finalize_preview_execution`，符合 douyin_live_check 先例，未抽 Service 层（行为不变，不算 scope 扩散）|
| C2 fail-closed runtime gate | ✅ REQUIRED MET | F1-PG-5 runtime request-level failure injection（§21），非仅静态测试 |
| C3 证据命名精度 + F1-PG-6 runtime | ✅ REQUIRED MET | F1-PG-2 明确为 SAME_EXECUTION_SAME_STAGE_REPLAY（非 HTTP_REQUEST_REPLAY，§18）；F1-PG-6 runtime None regression gate（§22）|
| C4 PREVIEW_REQUEST_RECOVERY_GAP 覆盖 | ✅ REQUIRED MET | `CROSS_MODULE_RISK_REGISTER.md` 已登记扩展覆盖（§25）|
| C5 AiPreviewExecution naming debt | ✅ REQUIRED MET | `CROSS_MODULE_RISK_REGISTER.md` S6 登记 NON_BLOCKING（§26）|

---

## 4. Changed Files

### MODIFY（9000）

| 文件 | 改动 |
|---|---|
| `app/routers/douyin_ai_cs_proxy.py` | ① import `_create_preview_execution` / `_finalize_preview_execution`（C1）；② handler `create_reply_suggestion_proxy`：suggest_reply 前 `_create_preview_execution(db, context.merchant_id, agent.agent_id)` durable commit + `payload["preview_execution_id"] = preview_exec_id`；9100 成功 → `_finalize_preview_execution("completed")`；9100 异常 → `_finalize_preview_execution("failed")`；execution 创建失败 → fail-closed 502 `PREVIEW_EXECUTION_CREATE_FAILED`（C2）；③ `async def` → `def`（event loop 阻塞修复，见下）|

### async→def 修复说明（必要最小改动）

`create_reply_suggestion_proxy` 原为 `async def`，但内部全同步（`validate_douyin_agent_binding` / `get_agent` / `build_reply_conversation_context` / `get_xg_douyin_ai_cs_client().suggest_reply` 同步 `httpx.post`）。`async def` + 同步阻塞 `httpx.post` 会阻塞 uvicorn event loop，导致 9000→9100→9000 双 hop HTTP 死锁（9100 `_report_llm_usage` 调 9000 `/internal/compute/usage` 无法被 event loop accept → 9100 report_usage 超时）。

改为 `def` 后 FastAPI 用 anyio thread pool 处理（与 `preview_agent` 同步 `def` 先例一致），不阻塞 event loop，双 hop HTTP 链路通畅。这是 F1 runtime 验证可行的必要最小修复（pre-existing bug，in-repo caller=0 未触发）。runtime 实测：async→def 前 `compute_usage stage=request_failed error=timed out`（F1-PG-1 txn_count=0）；async→def 后 F1-PG-1 txn_count=1 正常计费。

### CREATE

| 文件 | 内容 |
|---|---|
| `tests/test_trusted_reply_suggestion_compute_idempotency.py` | F1-PG-1~F1-PG-6 focused 静态测试（7 passed）|
| `docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md` | 本报告 |

### GOVERNANCE DOC UPDATE

| 文件 | 改动 |
|---|---|
| `CLAUDE.md` | F-1 候选状态 + C5 naming debt 指针 |
| `docs/ai/05_PROJECT_CONTEXT.md` | F-1 实施完成候选状态 |
| `docs/architecture/CROSS_MODULE_RISK_REGISTER.md` | C4 PREVIEW_REQUEST_RECOVERY_GAP 扩展覆盖 + C5 S6 naming debt 登记 |

### NO migration / NO 9100 change / NO compute core change

复用 0034 `ai_preview_executions`（§10）。9100 `ReplySuggestionRequest.preview_execution_id` 已存在（schemas.py:184），`_report_llm_usage` 已有 Preview 分支（reply_decision_service.py:3807）。

---

## 5. Current F-1 Before Chain

实施前（`P1_GLOBAL_ACTIVE_NONE_AUDIT.md` FAILED 确认）：

```text
9000 Trusted Reply-Suggestion Proxy（douyin_ai_cs_proxy.py:230，main.py:139 挂载 + 鉴权）
  → payload 无 durable billing identity
  → 9100 _report_llm_usage 全 None（reply_decision_service.py:3786-3811 legacy 兼容路径）
  → idempotency_key=None
  → record_usage(None) legacy 裸扣（services.py:777-800）
  → PostgreSQL idempotency_key=NULL ComputeTransaction（NULL 不参与唯一约束，retry 重复扣费）
```

---

## 6. Implemented After Chain

实施后（F1-PG-1 runtime 实测）：

```text
9000 Trusted Reply-Suggestion Proxy（douyin_ai_cs_proxy.py:230）
  → auth / permission / merchant validation（:234-243）
  → agent binding validation（:245-260）
  → agent active check（:262-272）
  → ★ _create_preview_execution(db, context.merchant_id, agent.agent_id) durable commit（before suggest_reply）
  → payload["preview_execution_id"] = preview_exec_id（exactly one top-level identity source）
  → 9000→9100 suggest_reply（HTTP，XgDouyinAiCsClient.suggest_reply）
    → 9100 build_reply_suggestion → _build_llm_reply
      → check_balance（9100→9000 /internal/compute/balance 真实 HTTP）
      → client.chat（★ 唯一 mock：外部 LLM 边界）
      → _report_llm_usage(llm_call_stage="primary")
        → preview_execution_id 非空 + run_id/attempt_count None → 走 Preview 分支
        → idempotency_key = ai_preview_execution:{preview_execution_id}:primary
        → ComputeUsageClient.report_usage（9100→9000 /internal/compute/usage HTTP）
          → record_usage（idempotency_key 非空 → 幂等路径）
          → PostgreSQL ComputeTransaction(idempotency_key 非空，参与 UNIQUE 约束)
      → （若 off_platform_promise_violation 命中）retry client.chat
      → _report_llm_usage(llm_call_stage="retry_combined") → ai_preview_execution:{id}:retry_combined
  → 9100 成功 → _finalize_preview_execution("completed")
  → 9100 异常 → _finalize_preview_execution("failed")
  → execution 创建失败 → fail-closed 502（不调 9100/LLM/compute）
```

---

## 7. Durable Execution Timing

```text
auth / merchant validation（:234-243）
  → agent binding validation（:245-260）
  → agent active check（:262-272）
  → ★ create AiPreviewExecution + db.commit() + db.refresh()（durable，before 9100 call）
  → payload["preview_execution_id"] = execution.id
  → suggest_reply → 9100 LLM（计费源）
```

`_create_preview_execution`（agents.py:61-76）`db.add` → `db.commit` → `db.refresh`。**非 flush only / 非 LLM first / 非 commit later**。execution.id 在 LLM 前 durable commit，满足"identity 先于计费副作用持久化"硬规则（`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md:29`）。

runtime 证据（F1-PG-1）：execution_id=19 在 suggest_reply 前已持久化（`ai_preview_executions` 行存在，lifecycle=running→completed），primary charge idempotency_key=`ai_preview_execution:19:primary` 复用该 execution.id。

---

## 8. Merchant / Agent Ownership

```text
merchant_id = context.merchant_id（RequestContext，服务端 mock auth → dev-merchant）
agent_id    = agent.agent_id（get_agent 返回的规范化 identity，已校验属于当前商户 + active）
```

- execution.merchant_id = RequestContext.merchant_id（非 proxy request body）。
- agent_id 来自 `agent.agent_id`（get_agent(db, context, request.agent_id) 校验后），非 dummy / 非 cross-merchant / 非 hardcode。

runtime 证据（§22 merchant identity 一致性 5 层）：

```text
recharge_merchant = dev-merchant
proxy_request_merchant = dev-merchant
balance_check_merchant = dev-merchant
usage_report_merchant = dev-merchant
compute_ledger_merchant = dev-merchant
all_layers_identical = True
```

---

## 9. preview_execution_id Propagation

```text
payload["preview_execution_id"] = preview_exec_id
```

- exactly one top-level execution identity source：只设 `preview_execution_id`。
- 不设 `run_id` / `attempt_count`（避免触发 9100 mixed identity guard）。
- 9100 `_report_llm_usage`（reply_decision_service.py:3786-3811）：run_id=None + attempt_count=None + preview_execution_id 非空 → 走 :3807 Preview 分支 → `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`。
- mixed guard（:3792-3798）：Trusted Proxy 不设 run_id/attempt_count → 不触发。

runtime 证据：F1-PG-1 identity=`ai_preview_execution:19:primary`（Preview 分支构造，非 None）。

---

## 10. 9100 Zero-Change Verification

```text
9100 CHANGE REQUIRED = NONE
```

- `ReplySuggestionRequest.preview_execution_id: int | None = None`（schemas.py:184）✅ 已存在。
- `_report_llm_usage` Preview 分支（reply_decision_service.py:3807-3810）✅ 已存在。
- primary（:1166）/ retry_combined（:1242）传同一 `request` 对象 → 同一 `preview_execution_id` → 同 execution，`llm_call_stage` 区分 → 不同 key。
- partial/mixed guard（:3792-3806）：Trusted Proxy 不设 run_id/attempt_count → 不触发 ✅。

9100 无需任何代码改动。runtime 实测 9100 `_report_llm_usage` 真实构造 `ai_preview_execution:{id}:{stage}` identity。

---

## 11. Success Finalization

9100 suggest_reply 成功 → `_finalize_preview_execution(db, preview_exec_id, "completed")`。

runtime 证据（F1-PG-1）：execution 19 lifecycle_status=completed（9100 正常返回 → completed；C1：lifecycle=整次 9100 请求结果，非 stage 状态）。与 Preview `preview_agent` 先例（agents.py:343）一致。

---

## 12. Failure Finalization

execution 已创建但 9100 失败（XgDouyinAiCsClientError）→ `_finalize_preview_execution(db, preview_exec_id, "failed")`。

- failed execution 保留（`_finalize_preview_execution` 只更新 lifecycle_status，不删行）。
- 不重新创建另一个 execution 作为异常重试（runtime F1-PG-5 确认无新 execution）。

focused test T-F1-5 验证：upstream failure → same execution finalized failed，`db.query(AiPreviewExecution).count() == 1`（未新建）。

---

## 13. Fail-Closed

C2 硬要求（§12）。handler 实现：

```python
try:
    preview_exec_id = _create_preview_execution(db, context.merchant_id, agent.agent_id)
except Exception as exc:
    db.rollback()
    raise HTTPException(status_code=502, detail={"code": "PREVIEW_EXECUTION_CREATE_FAILED", ...})
# execution 创建失败 → 不调 suggest_reply（不 fall through）
payload["preview_execution_id"] = preview_exec_id
try:
    result = ...suggest_reply(...)
except XgDouyinAiCsClientError as exc:
    _finalize_preview_execution(db, preview_exec_id, "failed")
    raise HTTPException(...)
```

不得 fallback 旧 proxy 行为（execution 创建失败 → 仍调 9100 without preview_execution_id）。runtime F1-PG-5 验证（§21）。

---

## 14. External API Compatibility

```text
API CONTRACT BREAKING CHANGE = NONE
```

- `ReplySuggestionProxyRequest`（douyin_ai_cs_proxy.py:168-174）：无新 required field。identity 由 9000 服务端创建。
- 9100 `ReplySuggestionRequest`：已有 `preview_execution_id`（schemas.py:184），无需改 schema。
- 前端 `TrustedReplySuggestionRequest`：无需改（identity 不由前端提供）。
- response model：handler 返回 `dict[str, Any]`（无 response_model），不新增 execution_id 到 response。
- caller 无需传 preview_execution_id / request_id / idempotency_token。

focused test T-F1-6 验证：`ReplySuggestionProxyRequest` 无 preview_execution_id 字段（identity 服务端注入 payload，非 request model），仅需 douyin_account_id + latest_message。

---

## 15. Focused Tests

`tests/test_trusted_reply_suggestion_compute_idempotency.py`（7 passed）：

| Test | 验证 | 结果 |
|---|---|---|
| T-F1-1 | execution 在 suggest_reply 前 durable 创建（payload 含 preview_execution_id + AiPreviewExecution 行持久化）| ✅ PASS |
| T-F1-2 | payload 含 preview_execution_id 且不含 mixed identity（run_id/attempt_count 均 None）| ✅ PASS |
| T-F1-3 | create 失败 → suggest_reply not invoked（fail-closed, C2）| ✅ PASS |
| T-F1-4 | success → execution finalize completed | ✅ PASS |
| T-F1-5 | upstream failure → 同 execution finalize failed（不新建 execution）| ✅ PASS |
| T-F1-6 | external request schema 无 breaking change + intentional new generation 产生 distinct executions | ✅ PASS |

回归：`test_douyin_ai_cs_proxy.py`（59 passed + 1 pre-existing 基线失败 `test_proxy_injects_merged_customer_memory_and_masks_contacts`，git stash 对比确认非本轮引入）+ `test_preview_compute_idempotency_migration.py`（全 passed）。0 新增失败。

---

## 16. Runtime Environment

```text
environment = LOCAL DEVELOPMENT ONLY（隔离 fixture，canonical PG + cleanup）
PG（DB-B compute ledger）:
  container = auto-wechat-postgres-dev (Up, healthy)
  database = auto_wechat（canonical@0034, 61 表）
  application principal = auto_wechat（已 PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED）
PG（DB-A RAG execution，9100 启动依赖）:
  database = xg_douyin_ai_cs（@0005）
  principal = xg_douyin_ai_cs

9000 = temporary uvicorn（thread 1，app.main:app，DATABASE_URL=auto_wechat 应用角色）
9100 = temporary uvicorn（thread 2，apps.xg_douyin_ai_cs.main:app，RAG_DATABASE_URL=xg_douyin_ai_cs，RAG_VECTOR_BACKEND=sqlite）
loopback HTTP：9000↔9100 经 127.0.0.1
mock = OpenAICompatibleClient.chat（9100 最终外部 LLM 边界，类属性 monkeypatch）
fixture merchant = dev-merchant（mock auth 运行时真实值）
```

canonical PG 不变（§28）：`residual=0 / revision=0034 / table_count=61`。验证脚本位于 worktree 外（`e:/work/tmp/f1/`）。

---

## 17. F1-PG-1 First

真实 Trusted Proxy POST `/integrations/douyin-ai-cs/conversations/123/reply-suggestion`（message="奥迪A6价格"）：

```text
execution A = 19（ai_preview_executions.id，真实 PG 序列持久化）
lifecycle = completed
identity = ai_preview_execution:19:primary（9100 _report_llm_usage 真实构造）
transaction count = 1
txn: id=73 | idempotency_key=ai_preview_execution:19:primary | delta=-15 | balance_after=99985
     capability_key=douyin-cs | model=f1-verify-mock-llm | llm_call_stage=primary
     actual_tokens=15 | usage_measurement_method=provider_tokens | payload_evidence NOT NULL
balance: 100000 → 99985（delta=-15，billed_tokens=calculate_billed_tokens(15,0)=15）
```

execution 在 LLM 前 durable persist（execution.id=19 在 suggest_reply 前已 commit）。

---

## 18. F1-PG-2 Same Execution Replay

对同一 execution_id=19、同一 stage=primary，经 9100 `/douyin/reply-suggestion` 直调传入同一 `preview_execution_id=19`（same identity，模拟 9100 同 request 复用 / crash 后 usage report 重试场景）：

```text
调用：9100 /douyin/reply-suggestion（preview_execution_id=19，stage=primary）[same identity]
identity 自然重新生成：ai_preview_execution:19:primary
```

**★ 证据名称精度（C3）**：这是 **SAME_EXECUTION_SAME_STAGE_USAGE_REPLAY**（9100 同 request 复用 identity 的 usage replay），**非 HTTP_REQUEST_REPLAY**（重发 proxy POST 会新建 execution）。对应 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试。

PostgreSQL 权威证据：

```text
compute_transactions WHERE idempotency_key='ai_preview_execution:19:primary' count = 1（未产生第 2 行）✓
account balance 仍 = 99985（replay 后未变）✓
balance_after_replay = 99985 = balance_after_first ✓
```

```text
SAME_EXECUTION_SAME_STAGE_REPLAY_VERIFIED
NO_DOUBLE_CHARGE_VERIFIED
```

SUPPLEMENTARY_RUNTIME_EVIDENCE：id gap=74（replay INSERT 占用序列后 IntegrityError rollback 副证）。sequence gap 非幂等硬证据——硬证据仍是 same identity + one transaction + balance unchanged（已满足）。

---

## 19. F1-PG-3 Intentional New Generation

新 POST（message="宝马X5多少钱"）→ 新 execution：

```text
execution B = 20（≠ 19）
identity = ai_preview_execution:20:primary
transaction count = 1
txn: id=75 | delta=-15 | balance_after=99970
identity_A_ne_B = True
```

```text
INTENTIONAL_NEW_GENERATION = DISTINCT_EVENT_VERIFIED
```

两次 intentional generation → 两个不同 execution → 可独立计费。非 HTTP replay（§16）。

---

## 20. F1-PG-4 Stage Separation

POST（message="STAGE_TEST 有没有奥迪A6？"）→ mock primary 返回含 `OFF_PLATFORM_PROMISE_KEYWORDS`（"把报价发您手机上"）违规回复 → `_build_llm_reply` post-generation 校验命中 `off_platform_promise_violation`（reply_hard_rules.py:99-113）→ 真实 retry 分支（:1223-1234）→ `_report_llm_usage(stage="retry_combined")`（:1242）→ retry 返回干净合规回复：

```text
execution R = 21
warnings = ["llm_retry_combined"]（retry 真实触发，由真实 post-generation 校验决定）
```

同一 execution_id=21，两个不同 legitimate billable stage：

```text
R primary:          identity=ai_preview_execution:21:primary          txn(id=76) delta=-15 balance_after=99955
R retry_combined:   identity=ai_preview_execution:21:retry_combined   txn(id=77) delta=-15 balance_after=99940
identity_primary_ne_retry = True
```

```text
DISTINCT_LEGITIMATE_STAGE = VERIFIED
```

retry_combined 由真实 `_build_llm_reply` post-generation 校验触发，**非直接调 `_report_llm_usage("retry_combined")`、非手工构造 retry key**。

---

## 21. F1-PG-5 Fail-Closed Runtime

C2 硬 Gate。runtime request-level failure injection：monkeypatch `_create_preview_execution` 抛 `RuntimeError("injected_execution_create_failure")` + `get_xg_douyin_ai_cs_client` 替换为 `_CountingClient`（计数 suggest_reply 调用）：

```text
HTTP = 502
error_code = PREVIEW_EXECUTION_CREATE_FAILED
suggest_reply_call_count = 0     （★ 9100 NOT CALLED / LLM NOT CALLED）
balance_before = 99940
balance_after = 99940             （★ compute NOT CALLED，无 charge）
balance_delta = 0
identity_creation_fail_closed = True
```

```text
IDENTITY_CREATION_FAIL_CLOSED = VERIFIED
```

仅静态测试不够（C2）——本 Gate 是真实 runtime request-level failure injection，验证 execution 创建失败时不 fall through 到 suggest_reply。

---

## 22. F1-PG-6 None Regression

C3 硬 Gate。runtime 检查本轮所有 Trusted Proxy charge rows：

```text
idempotency_key IS NOT NULL AND != '' AND trim != '' ✓
无 :None: / :null: / :: / :unknown: / :missing: 畸形 key ✓
null_or_empty_count = 0
malformed_count = 0
```

```text
TRUSTED_PROXY_ACTIVE_NONE_REGRESSION = 0
```

Trusted Proxy active charge path 不再产生 `idempotency_key=None`（F-1 根因消除）。Global Active None Audit 仍保持 FAILED（须 F-1 审批后重新完整跑，非仅查 F-1 route）。

---

## 23. Transaction / Balance Closure

PG 查询全部 consume txns for dev-merchant：

| id | idempotency_key | delta | balance_after | stage | actual | payload_evidence |
|----|---|---|---|---|---|---|
| 73 | `ai_preview_execution:19:primary` | -15 | 99985 | primary | 15 | NOT NULL |
| 75 | `ai_preview_execution:20:primary` | -15 | 99970 | primary | 15 | NOT NULL |
| 76 | `ai_preview_execution:21:primary` | -15 | 99955 | primary | 15 | NOT NULL |
| 77 | `ai_preview_execution:21:retry_combined` | -15 | 99940 | retry_combined | 15 | NOT NULL |

```text
distinct_identities = 4
final_balance = 99940
  = 100000 + delta(A primary -15) + delta(B primary -15) + delta(R primary -15) + delta(R retry_combined -15)
  = 100000 + (-15)×4 = 99940 ✓
A primary replay 不贡献 extra delta ✓
```

4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费。id gap=74（A replay IntegrityError 消耗序列，§18 副证）。

### Compute Principal Hard Gate

核心 consumer 写入链全程由 `auto_wechat` Application Principal 执行（DB-B compute ledger）：

```text
COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED: auto_wechat
postgres PASS / auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）
```

---

## 24. Execution Persistence

```text
A=19, B=20, R=21 都是 ai_preview_executions 真实持久化行
replay_reuses_same_execution_id = True（A replay 复用 execution_id=19 同一持久化 row，非新建）
lifecycle_status = completed（A/B/R 正常返回）
created_at NOT NULL（durable commit 生效）
```

Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）。

---

## 25. PREVIEW_REQUEST_RECOVERY_GAP（C4）

`CROSS_MODULE_RISK_REGISTER.md` 已更新（C4 REQUIRED）：

```text
PREVIEW_REQUEST_RECOVERY_GAP 现覆盖两类计费同域入口：
  1. draft-agent AI Preview（POST /agents/{id}/preview）
  2. Trusted Reply-Suggestion（POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion）

Candidate A 让 Trusted Reply-Suggestion 复用 AiPreviewExecution + ai_preview_execution:{id}:{stage} namespace，
与 Preview 计费同域，故其 full HTTP request response-lost gap 被 PREVIEW_REQUEST_RECOVERY_GAP 准确覆盖。
不新建独立 TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP。
```

```text
same durable execution + same stage replay safety = P1 verified
full HTTP request response-lost / re-submit recovery = OUT_OF_P1（保持，不写 resolved）
```

---

## 26. AiPreviewExecution Naming Debt（C5）

`CROSS_MODULE_RISK_REGISTER.md` S6 已登记（C5 REQUIRED）：

```text
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING

DOMAIN_MODEL_CONTAMINATION = NOT PRESENT
  （AiPreviewExecution 作为计费 identity 容器通用：merchant_id/agent_id/lifecycle_status
   无 source/type 字段限定；无统计/历史/审计/前端展示消费面将其锁定为 Preview 专用）

NAMING_DEBT = PRESENT / NON_BLOCKING
  （表/模型名"Preview"承载两类计费场景：draft-agent Preview + Trusted Reply-Suggestion；
   名字不反映真实专属语义，模型本身是通用计费 identity 容器，故是命名债非 domain mismatch）
```

不在 P1 重命名 table/model。

---

## 27. F-2 Boundary

dev-only `/api/compute/internal/usage` 丢 key 问题继续：

```text
F-2 = DORMANT / NON_BLOCKING FUTURE HARDENING
```

本轮不处理（§34）。

---

## 28. Canonical DB No-Drift

```text
canonical local PG = unchanged
  residual_dev_txn = 0
  residual_dev_acct = 0
  residual_dev_prev = 0
  canonical_revision = 0034
  canonical_table_count = 61
```

未在 canonical DB 留下 preview executions / compute transactions / recharge rows / fixture（cleanup 后 residual=0）。验证脚本经 worktree 外执行，未入 worktree（`git status` 仅 candidate docs + proxy handler + focused tests + 本报告）。

---

## 29. Scope Compliance

| 范围 | 状态 |
|---|---|
| MODIFY douyin_ai_cs_proxy.py handler | ✅（identity + finalize + fail-closed + async→def 必要修复）|
| CREATE focused tests | ✅ |
| CREATE implementation report | ✅ |
| MODIFY CLAUDE.md / 05_PROJECT_CONTEXT.md | ✅（C4/C5/F-1 候选状态）|
| MODIFY CROSS_MODULE_RISK_REGISTER.md | ✅（C4 + C5）|
| 9100 code | ❌ 零改（未碰）|
| migration | ❌ 无（复用 0034）|
| compute core / record_usage | ❌ 零改（未碰）|
| other 11 consumers | ❌ 零改（未碰）|
| database models | ❌ 零改（未碰）|
| frontend request contract | ❌ 零改（未碰）|
| staging/prod config | ❌ 零改（未碰）|
| F-2 dev-only route | ❌ 未碰 |

未出现 STOP 触发条件（§42）：helper 满足输入 / 无新 migration / 无 9100 修改 / 无 API breaking / fail-closed 不 fall through / 无 mixed identity / success path 无 NULL key / same execution replay 不重复扣 / intentional new generation 无 collision / retry_combined 真实触发 / canonical DB 未污染。

---

## 30. Verdict

```text
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY
= RESOLVED_PENDING_APPROVAL

TRUSTED REPLY-SUGGESTION BUSINESS EVENT IDENTITY
= ai_preview_execution:{preview_execution_id}:{llm_call_stage}

SAME EXECUTION + SAME STAGE = NO_DOUBLE_CHARGE_VERIFIED
INTENTIONAL NEW GENERATION = DISTINCT_EVENT_VERIFIED
DISTINCT LEGITIMATE STAGE = VERIFIED
IDENTITY CREATION FAIL-CLOSED = VERIFIED
ACTIVE NONE REGRESSION = 0

COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED = auto_wechat
```

不得自行标 F-1 RESOLVED（须独立审批窗口裁定）。

---

## 31. Next Required Step

```text
P1-F1 Implementation Independent Approval
```

F-1 实施审批通过后，才：

```text
Global Active None Audit RE-RUN
  → ACTIVE NONE = 0
  → ACTIVE EMPTY = 0
  → ACTIVE PARTIAL = 0
  → UNKNOWN ACTIVE = 0
  → F-2 继续 DORMANT
  → 方可进入 Final PostgreSQL Concurrent Closure Gate
```

不能仅凭 F-1 测试通过直接进入 Final Concurrent Closure（§23 Global Re-Audit Contract）。

---

## 32. P1 Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_PENDING_F1_APPROVAL_AND_GLOBAL_REAUDIT
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

不得写 P1 CLOSED。RB-10 = NOT AUTHORIZED。

---

## 33. Git Discipline

- §0 设计审批 checkpoint = commit `7ef246e`（已 commit，未 push）。
- F-1 implementation = **DO NOT COMMIT**（candidate diff 给独立实施审批窗口）。
- 未 push。

candidate diff scope：

```text
MODIFY app/routers/douyin_ai_cs_proxy.py
CREATE tests/test_trusted_reply_suggestion_compute_idempotency.py
CREATE docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md
MODIFY CLAUDE.md
MODIFY docs/ai/05_PROJECT_CONTEXT.md
MODIFY docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

---

## 34. 边界遵守

- ✅ 未修改 9100 代码（零改）；
- ✅ 未创建 migration（复用 0034 `ai_preview_executions`）；
- ✅ 未修改 compute core / record_usage / 其他 11 consumers / database models / frontend / staging-prod；
- ✅ 未处理 F-2（DORMANT）/ 9100 least privilege / RB-10 / bootstrap owner drift；
- ✅ 未重命名 AiPreviewExecution（C5 NON_BLOCKING 登记）；
- ✅ 未实施 9100 fail-closed hardening（Candidate E OPTIONAL，§33 不实施）；
- ✅ 未重跑 Global Active None Audit / 未启动 Final Concurrent Closure / 未宣布 P1 closed；
- ✅ F-1 implementation 未 commit / 未 push（candidate diff）；
- ✅ canonical DB 未污染（residual=0，canonical@0034/61 表）；
- ✅ consumer 验证仅 mock 外部 LLM（chat），未 mock proxy handler / identity 生成 / usage reporting / compute / PG 幂等 / 余额检查。

---

提交：**P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-IMPLEMENTATION 独立实施审批窗口。**
