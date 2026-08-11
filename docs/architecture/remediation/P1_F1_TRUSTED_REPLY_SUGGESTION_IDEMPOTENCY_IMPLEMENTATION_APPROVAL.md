# P1-F1 Trusted Reply-Suggestion Idempotency — 独立实施审批

> 审批窗口：`P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-IMPLEMENTATION`（独立实施审批，非执行窗口自述）
> 审查对象：`P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md` + candidate diff
> 前序设计审批：`P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，Candidate A）
> Governance checkpoint：`7ef246e`
> 审批日期：2026-08-11
> 窗口性质：READ ONLY 实施审批（未 commit、未 push、未改 canonical DB）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS

F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY
= RESOLVED

TRUSTED REPLY-SUGGESTION BUSINESS EVENT IDENTITY
= ai_preview_execution:{preview_execution_id}:{llm_call_stage}

SAME EXECUTION + SAME STAGE = NO_DOUBLE_CHARGE_VERIFIED
INTENTIONAL NEW GENERATION = DISTINCT_EVENT_VERIFIED
DISTINCT LEGITIMATE STAGE = VERIFIED
IDENTITY CREATION FAIL-CLOSED = VERIFIED
TRUSTED PROXY ACTIVE NONE REGRESSION = 0
```

核心 F-1 修复独立成立。candidate diff、focused tests（7 passed 独立复现）、调用链、fail-closed、async→sync 修复、9100 零改、external API 兼容、scope 合规均经独立验证。残留 correction 为非阻断的描述/分类精度修正：runtime 环境"canonical"描述需准确分类为 Case B、async→sync 补正式说明、pre-existing test 分类措辞。

```
GLOBAL_ACTIVE_NONE_AUDIT = FAILED（保持，须 F-1 审批后重跑）
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

---

## 2. Git / Scope

```
HEAD = 7ef246e（预期治理 checkpoint，设计审批 commit）

candidate diff（未 commit implementation）:
  MODIFY app/routers/douyin_ai_cs_proxy.py
  CREATE tests/test_trusted_reply_suggestion_compute_idempotency.py
  CREATE docs/architecture/remediation/P1_F1_..._IMPLEMENTATION_REPORT.md
  MODIFY CLAUDE.md
  MODIFY docs/ai/05_PROJECT_CONTEXT.md
  MODIFY docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

独立确认 scope 无越界：

| 范围 | 状态 |
|---|---|
| 9100 code | ❌ 零改（`git diff --stat -- apps/xg_douyin_ai_cs/` 空）✅ |
| migration | ❌ 无（复用 0034 `ai_preview_executions`）✅ |
| compute core / record_usage | ❌ 零改 ✅ |
| 其他 11 consumers | ❌ 零改 ✅ |
| database models | ❌ 零改 ✅ |
| frontend request contract | ❌ 零改 ✅ |
| staging/prod config | ❌ 零改 ✅ |
| F-2 dev-only route | ❌ 未碰 ✅ |
| RB-10 | ❌ 未碰 ✅ |

```
SCOPE_VIOLATION = NONE
```

candidate diff 精确集中在 proxy handler + focused tests + 治理文档状态同步，与设计审批 §27 授权范围一致。

---

## 3. Baseline F-1

独立确认修改前的问题确实存在（前一审计/审批窗口已验证，本轮 git 无业务代码改动影响 baseline）：

```
Trusted Proxy
  → no durable billing identity（payload :316-362 不含 run_id/attempt_count/preview_execution_id）
  → 9100 _report_llm_usage 全 None（reply_decision_service.py:3786-3811）
  → idempotency_key=None
  → record_usage(None) legacy 裸扣（services.py:777-800）
  → PostgreSQL idempotency_key=NULL ComputeTransaction
```

candidate 确实移除这条 ACTIVE 路径：handler 在 suggest_reply 前 `_create_preview_execution` durable commit + 透传 `preview_execution_id`，9100 `_report_llm_usage` 走 Preview 分支构造非空 identity。非仅看新增测试——代码 diff 确认根因消除。

---

## 4. Candidate A Implementation

独立代码审查（`git diff app/routers/douyin_ai_cs_proxy.py`）：

- **import**（:38-41）：`from app.routers.agents import _create_preview_execution, _finalize_preview_execution`（C1 直接 import，符合 `douyin_live_check` 先例）✅
- **identity 创建**（:368-388）：`try: preview_exec_id = _create_preview_execution(db, context.merchant_id, agent.agent_id)` → except `db.rollback()` + `raise HTTPException(502, PREVIEW_EXECUTION_CREATE_FAILED)`（fail-closed，不 fall through）✅
- **payload 透传**（:389）：`payload["preview_execution_id"] = preview_exec_id`（exactly one top-level identity source）✅
- **success finalize**（:403）：`_finalize_preview_execution(db, preview_exec_id, "completed")` ✅
- **failure finalize**（:399）：`except XgDouyinAiCsClientError: _finalize_preview_execution(db, preview_exec_id, "failed")` ✅

domain contract 未偷改：identity = `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，未变成 random UUID / timestamp / message hash / transient request id。durable AiPreviewExecution.id 是 DB PK。

---

## 5. Durable Commit Timing

独立确认真实顺序（代码 diff + agents.py:61-76）：

```
auth / merchant context（:234-243）
  → agent binding validation（:245-260）
  → agent active check（:262-272）
  → ★ _create_preview_execution(db, context.merchant_id, agent.agent_id)
      agents.py:73 db.add → :74 db.commit → :75 db.refresh
  → payload["preview_execution_id"] = preview_exec_id（:389）
  → suggest_reply → 9100 LLM（计费源）
```

```
COMMIT BEFORE BILLABLE LLM CALL = TRUE
  非 flush only / 非 LLM first / 非 commit later
```

focused test T-F1-1 验证：execution 在 suggest_reply 前已 durable 持久化（AiPreviewExecution 行存在，merchant_id/agent_id 正确）。

---

## 6. Merchant / Agent Ownership

独立核验（代码 diff）：

```
execution.merchant_id = _create_preview_execution(db, context.merchant_id, ...)
  context.merchant_id = RequestContext（服务端可信，非 proxy request body）
execution.agent_id = agent.agent_id
  agent = get_agent(db, context, request.agent_id)（已校验属于当前商户 + active）

9100 usage merchant_id = request.merchant_id = payload["merchant_id"]（:320，9000 注入）
compute ledger merchant_id = record_usage(merchant_id=request.merchant_id)
```

无 dummy id / cross-merchant agent / 客户端 merchant override。`ReplySuggestionProxyRequest`（:168-174）无 merchant_id 字段，merchant_id 由 9000 从 RequestContext 注入 payload。

实施报告 §8 runtime 证据：5 层 merchant identity 一致（recharge/proxy_request/balance_check/usage_report/compute_ledger 均为 dev-merchant）。

```
MERCHANT_AGENT_OWNERSHIP = VERIFIED
```

---

## 7. Identity Propagation

独立确认 payload（diff :389）：

```
payload["preview_execution_id"] = preview_exec_id  ← valid durable id（int PK）
payload 不含 run_id
payload 不含 attempt_count
```

```
EXACTLY ONE TOP-LEVEL IDENTITY SOURCE = preview_execution_id
MIXED GUARD TRIGGER = NO
```

9100 `_report_llm_usage`（reply_decision_service.py:3786-3811）：run_id=None + attempt_count=None + preview_execution_id 非空 → 走 :3807 Preview 分支 → `ai_preview_execution:{id}:{stage}`。focused test T-F1-2 验证 payload 不含 mixed identity。

---

## 8. 9100 Zero-Change

独立确认：

```
9100 CODE DIFF = NONE
  git diff --stat -- apps/xg_douyin_ai_cs/  →  空
```

重新核验 9100 已有支撑：

- `ReplySuggestionRequest.preview_execution_id: int | None = None`（schemas.py:184）✅ 已存在
- `_report_llm_usage` Preview 分支（reply_decision_service.py:3807-3810）：`elif preview_execution_id is not None: idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"` ✅ 已存在
- primary（:1160）/ retry_combined（:1236）传同一 request 对象 → 同一 preview_execution_id → 同 execution，llm_call_stage 区分 ✅

本轮不依赖任何未批准的 9100 行为变更。

---

## 9. Success Lifecycle

成功时（9100 正常返回有效 response）：

```
same execution → _finalize_preview_execution(db, preview_exec_id, "completed")
```

不新增生命周期状态（running/completed/failed 三态，与 Preview `preview_agent` 先例 agents.py:343 一致）。lifecycle_status = 整次 9100 请求结果（非 stage 影子状态）。billing truth 只归 M07 ComputeTransaction。

focused test T-F1-4 验证：success → lifecycle=completed。

---

## 10. Failure Lifecycle

execution 已 durable 创建后，9100 失败（timeout / upstream failure / exception）：

```
same execution retained → _finalize_preview_execution(db, preview_exec_id, "failed")
  不 delete execution
  不创建第二个 replacement execution
  不 fall back 到无 identity 调用
```

`_finalize_preview_execution`（agents.py:79-95）只更新 `lifecycle_status`，不删行。failed execution 保留 stable identity 供审计/billing reconciliation。

focused test T-F1-5 验证：upstream failure → same execution finalized failed，`db.query(AiPreviewExecution).count() == 1`（未新建另一 execution）。

---

## 11. Identity Creation Fail-Closed

C2 硬要求。独立代码审查（diff :368-388）：

```python
try:
    preview_exec_id = _create_preview_execution(db, context.merchant_id, agent.agent_id)
except Exception as exc:
    db.rollback()
    logger.exception(...)
    raise HTTPException(status_code=502, detail={"code": "PREVIEW_EXECUTION_CREATE_FAILED", ...})
# execution 创建失败 → raise 502，不 fall through 到 suggest_reply
payload["preview_execution_id"] = preview_exec_id
try:
    result = ...suggest_reply(...)
```

```
CREATE_FAILURE → suggest_reply NOT CALLED = TRUE
  不 except → continue old proxy path
HTTP 错误 = 502 PREVIEW_EXECUTION_CREATE_FAILED
  不泄露内部敏感异常（detail 仅 code+message，exc_info 仅 logger.exception）
```

focused test T-F1-3 验证：create 失败 → 502 + suggest_reply call count = 0。runtime F1-PG-5 进一步验证（§22）。

---

## 12. Async→Sync Change Review

§12-15 第一项额外重点。执行窗口将 handler 从 `async def` 改为 `def`。独立审查：

### A. handler 内部是否全部同步调用？

独立确认：
- `validate_douyin_agent_binding` — 同步 SQLAlchemy service ✅
- `get_agent` — 同步 ✅
- `build_reply_conversation_context` — 同步 ✅
- `_create_preview_execution` / `_finalize_preview_execution` — 同步 SQLAlchemy（agents.py:61/79）✅
- `get_xg_douyin_ai_cs_client().suggest_reply`（xg_douyin_ai_cs_client.py:52）— `def`（同步），内部 `httpx.post`（:225，同步阻塞）✅

handler 内部全部同步调用。原 `async def` + 同步阻塞 `httpx.post` 会阻塞 uvicorn event loop。

### B. 是否存在原本需要 await 的逻辑？

独立确认：handler 内无 `await`（suggest_reply 同步，无 coroutine）。改 `def` 后无 coroutine 未 await / async dependency 错误调用 / background task 语义变化。`_build_preview_contact_state`、`load_forbidden_words_for_llm` 等均同步。

### C. FastAPI dependency injection 是否仍正确？

独立确认：`get_request_context_required` / `get_db` / `require_permission` 对 sync route 仍正确工作（FastAPI sync route 在 anyio thread pool 执行，dependency injection 不受 async/sync 影响）。focused tests 7 passed 证明 dependency injection 正常。

### D. response schema / exception 语义是否改变？

独立确认：handler 返回 `dict[str, Any]`（无 response_model，:236 不变），HTTPException 语义不变（502/403/503 与原一致）。external API contract 不变（§26）。

### 双 hop HTTP 死锁机理

实施报告 §4 说明：`async def` + 同步 `httpx.post` → 9000 event loop 阻塞 → 9100 `_report_llm_usage` 调 9000 `/internal/compute/usage` 无法被 event loop accept → 9100 report_usage 超时 → 双 hop HTTP 死锁。改 `def` 后 FastAPI 用 anyio thread pool 处理，不阻塞 event loop。这是 F1 runtime 验证可行的必要最小修复。

---

## 13. Async→Sync 裁定

```
async def → def
= MINIMAL NECESSARY IMPLEMENTATION CORRECTION

SYNC_HANDLER_CORRECTION
= REQUIRED FOR CURRENT CALLING MODEL
```

理由：真实双 HTTP 链（9000→9100→9000）在现有 `async + sync httpx` 下必然阻塞 event loop（死锁），改 sync handler 正好恢复已有同步调用模型（与 `preview_agent` 同步 `def` 先例 agents.py:232 一致）。这是 pre-existing bug 修复（in-repo caller=0 未触发双 hop 死锁），非行为回归。

不构成 UNAPPROVED BEHAVIORAL SCOPE EXPANSION：
- 与已批准 `preview_agent` sync 先例一致。
- response/exception 语义不变。
- 无更小且已批准范围内的替代方案（保留 async 会死锁）。

不扩大为异步架构治理：不要求全项目改 async httpx / AsyncSession / 重构 HTTP client / 重写 router。系统性 async/sync debt 登记为 future debt 即可（本审批不顺手要求）。

---

## 14. Focused Tests

独立运行 `tests/test_trusted_reply_suggestion_compute_idempotency.py`（非采信执行窗口"7 passed"）：

```
======================= 7 passed, 29 warnings in 2.52s ========================
```

| Test | 验证 | 独立结果 |
|---|---|---|
| T-F1-1 | execution 在 suggest_reply 前 durable 创建（payload 含 preview_execution_id + AiPreviewExecution 行持久化）| ✅ PASS |
| T-F1-2 | payload 含 preview_execution_id 且不含 mixed identity（run_id/attempt_count 均 None）| ✅ PASS |
| T-F1-3 | create 失败 → suggest_reply not invoked（fail-closed, C2）| ✅ PASS |
| T-F1-4 | success → execution finalize completed | ✅ PASS |
| T-F1-5 | upstream failure → 同 execution finalize failed（不新建 execution）| ✅ PASS |
| T-F1-6a | external request schema 无 breaking change（无 preview_execution_id required field）| ✅ PASS |
| T-F1-6b | two intentional generations 产生 distinct executions | ✅ PASS |

覆盖：create-before-suggest ✅ / preview_execution_id propagation ✅ / fail-closed ✅ / success finalize ✅ / failure finalize ✅ / API compatibility ✅ / identity behavior ✅。

---

## 15. Pre-existing Regression Classification

执行窗口报告：`test_douyin_ai_cs_proxy.py` 59 passed + 1 pre-existing 基线失败 `test_proxy_injects_merged_customer_memory_and_masks_contacts`。

独立 stash 对比确认：

```
candidate applied → 1 failed (test_proxy_injects_merged_customer_memory_and_masks_contacts)
candidate stashed (reverted) → SAME failure (1 failed)
```

baseline（candidate reverted，HEAD=7ef246e 无 candidate diff）下同样 FAILED → 真正 pre-existing，非本轮引入。

```
PRE_EXISTING / NON_BLOCKING
  与 F-1 实施无因果关联（stash 对比证明）
```

---

## 16. Runtime Environment Classification

§18-19 第二项额外重点。执行窗口描述："真实9000 + 9100 / canonical PG / auto_wechat@0034 / xg_douyin_ai_cs@0005"，同时"canonical DB unchanged / residual=0"。

审批必须查清"canonical PG"准确含义。实施报告 §16 明确：

```
PG（DB-B compute ledger）:
  container = auto-wechat-postgres-dev (canonical local dev PG)
  database = auto_wechat（canonical@0034, 61 表）
  application principal = auto_wechat
PG（DB-A RAG execution，9100 启动依赖）:
  database = xg_douyin_ai_cs（@0005）
```

```
Database Isolation Classification = Case B
  CANONICAL_DB_WAS_USED_FOR_RUNTIME_FIXTURE
```

这是 Case B（实际连接当前 canonical local dev PG），非 Case A（isolated temporary PG）。与"NO CANONICAL DB MUTATION"不是同一事实——但 cleanup 后 residual=0（实施报告 §28）。

**为何 Case B 可接受**：F-1 验证性质上需要真实双库 PG（`auto_wechat` compute ledger + `xg_douyin_ai_cs` RAG execution，9100 启动依赖），用临时隔离 PG 无法真实复现 9100 RAG 依赖链 + 9000→9100→9000 双 hop HTTP。canonical local dev PG 是唯一能真实承载双库 + 双服务的环境。

**风险控制**：
- runtime fixture 在验证后 cleanup（residual=0）。
- 审批窗口 READ ONLY，未执行 runtime probe（双服务启动超出审批窗口能力）。
- canonical DB no-drift 只读确认（§20）。

**Correction（C-RUNTIME）**：实施报告 §16 措辞"canonical PG + cleanup"应更准确分类为 Case B（CANONICAL_DB_WAS_USED_FOR_RUNTIME_FIXTURE），而非暗示 isolated。这是描述精度修正，非 scope violation——cleanup 后 residual=0，且 Case B 是 F-1 双库验证的必要环境。

---

## 17. Mock Boundary

实施报告 §16/§34 确认 mock 边界：

```
mock = OpenAICompatibleClient.chat（9100 最终外部 LLM 边界，类属性 monkeypatch）
```

真实未 mock：
- Trusted Proxy route ✅
- execution persistence（AiPreviewExecution）✅
- 9000→9100 HTTP（suggest_reply）✅
- balance gate（9100→9000 /internal/compute/balance）✅
- LLM orchestration（_build_llm_reply + post-generation 校验）✅
- usage reporting（_report_llm_usage）✅
- 9100→9000 HTTP（/internal/compute/usage）✅
- record_usage ✅
- PostgreSQL ledger（ComputeTransaction）✅

```
MOCK_BOUNDARY_COMPLIANCE = PASS
  仅 mock 最终外部 LLM client.chat，compute path 全真实
```

---

## 18. F1-PG-1 First Event

本审批窗口为 READ ONLY，未独立执行双 uvicorn + 真实 LLM mock runtime（超出审批窗口能力，需启动双服务进程）。F1-PG-1~6 runtime 证据依据实施报告 + 代码 diff 事实支撑 + focused 静态测试覆盖判定。

实施报告 §17 F1-PG-1（execution A=19）：

```
execution A = 19（ai_preview_executions.id，真实 PG 序列持久化）
lifecycle = completed
identity = ai_preview_execution:19:primary（9100 _report_llm_usage 真实构造）
transaction count = 1
txn: id=73 | delta=-15 | balance_after=99985
     capability_key=douyin-cs | model=f1-verify-mock-llm | llm_call_stage=primary
     actual_tokens=15 | payload_evidence NOT NULL
balance: 100000 → 99985
```

代码事实支撑：handler diff 确认 `_create_preview_execution` durable commit before suggest_reply + payload 透传 + finalize completed。focused test T-F1-1 验证 execution 在 suggest_reply 前持久化。

```
F1-PG-1 evidence level = REPORT_VERIFIED + CODE_VERIFIED + STATIC_TEST_VERIFIED
  （非审批窗口独立 runtime 复现）
```

---

## 19. F1-PG-2 Same Execution + Same Stage

实施报告 §18 F1-PG-2（same execution_id=19, same stage=primary）：

```
9100 /douyin/reply-suggestion（preview_execution_id=19, stage=primary）[same identity]
identity 自然重新生成：ai_preview_execution:19:primary

compute_transactions WHERE idempotency_key='ai_preview_execution:19:primary' count = 1（未产生第 2 行）✓
account balance 仍 = 99985（replay 后未变）✓
balance_after_replay = 99985 = balance_after_first ✓
```

```
SAME_EXECUTION_SAME_STAGE_REPLAY_VERIFIED
NO_DOUBLE_CHARGE_VERIFIED
```

**C3 证据名称精度**：实施报告 §18 明确这是 `SAME_EXECUTION_SAME_STAGE_USAGE_REPLAY`（9100 同 request 复用 identity 的 usage replay，对应 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试），**非 HTTP_REQUEST_REPLAY**（重发 proxy POST 会新建 execution）。证据名称准确 ✅。

replay seam 合法性：9100 `/douyin/reply-suggestion` 传入同一 `preview_execution_id` 对应 crash 后 usage report 重试场景（与 0034 `P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md:385` 同口径），非重新调 proxy POST。

```
F1-PG-2 evidence level = REPORT_VERIFIED + CODE_VERIFIED
  NOT HTTP_REQUEST_REPLAY_VERIFIED（证据名称准确，未偷换命题）
```

---

## 20. F1-PG-3 Intentional New Generation

实施报告 §19 F1-PG-3（new POST, message="宝马X5多少钱"）：

```
execution B = 20（≠ 19）
identity = ai_preview_execution:20:primary
transaction count = 1
txn: id=75 | delta=-15 | balance_after=99970
identity_A_ne_B = True
```

```
INTENTIONAL_NEW_GENERATION = DISTINCT_EVENT_VERIFIED
```

focused test T-F1-6b 验证：两次 intentional POST → 两个不同 execution（A != B）。非 HTTP replay（separate intentional POST = separate handler 调用 = separate execution）。

---

## 21. F1-PG-4 Stage Separation

实施报告 §20 F1-PG-4（execution R=21, message 含 OFF_PLATFORM_PROMISE_KEYWORDS）：

```
mock primary 返回含"把报价发您手机上"违规回复
  → _build_llm_reply post-generation 校验命中 off_platform_promise_violation（reply_hard_rules.py:99-113）
  → 真实 retry 分支（:1223-1234）
  → _report_llm_usage(stage="retry_combined")（:1242）
  → retry 返回干净合规回复

execution R = 21
warnings = ["llm_retry_combined"]（retry 真实触发，由真实 post-generation 校验决定）

R primary:          ai_preview_execution:21:primary          txn(id=76) delta=-15 balance_after=99955
R retry_combined:   ai_preview_execution:21:retry_combined   txn(id=77) delta=-15 balance_after=99940
identity_primary_ne_retry = True
```

```
DISTINCT_LEGITIMATE_STAGE = VERIFIED
```

retry_combined 由真实 `_build_llm_reply` post-generation 校验触发，**非直接调 `_report_llm_usage("retry_combined")`、非手工构造 retry key**。代码事实支撑：retry 分支（:1236）与 primary（:1160）传同一 request 对象 → 同一 preview_execution_id → 同 execution，`llm_call_stage` 区分 → 不同 key。

---

## 22. F1-PG-5 Fail-Closed Runtime

C2 硬 Gate。实施报告 §21：

```
runtime request-level failure injection:
  monkeypatch _create_preview_execution 抛 RuntimeError("injected_execution_create_failure")
  + get_xg_douyin_ai_cs_client 替换为 _CountingClient（计数 suggest_reply 调用）

HTTP = 502
error_code = PREVIEW_EXECUTION_CREATE_FAILED
suggest_reply_call_count = 0     （★ 9100 NOT CALLED / LLM NOT CALLED）
balance_before = 99940
balance_after = 99940             （★ compute NOT CALLED，无 charge）
balance_delta = 0
identity_creation_fail_closed = True
```

```
IDENTITY_CREATION_FAIL_CLOSED = VERIFIED
```

非仅静态测试——runtime request-level failure injection。代码 diff 事实支撑：try/except 包裹 `_create_preview_execution`，except 内 raise 502 不 fall through（§11）。focused test T-F1-3 静态验证同不变式。

```
F1-PG-5 evidence level = REPORT_VERIFIED + CODE_VERIFIED + STATIC_TEST_VERIFIED
```

---

## 23. F1-PG-6 None Regression

C3 硬 Gate。实施报告 §22：

```
runtime 检查本轮所有 Trusted Proxy charge rows:
  idempotency_key IS NOT NULL AND != '' AND trim != '' ✓
  无 :None: / :null: / :: / :unknown: / :missing: 畸形 key ✓
  null_or_empty_count = 0
  malformed_count = 0
```

```
TRUSTED_PROXY_ACTIVE_NONE_REGRESSION = 0
```

代码 diff 事实支撑：handler 必经 `_create_preview_execution`（fail-closed 不 fall through）→ payload 必含 `preview_execution_id`（非空 int PK）→ 9100 必走 Preview 分支构造非空 identity → record_usage 收到非空 idempotency_key → 走幂等路径（非 legacy 裸扣）。Trusted Proxy active charge path 不再可能产生 `idempotency_key=None`。

Global Active None Audit 仍保持 FAILED（须 F-1 审批后重新完整跑，非仅查 F-1 route，§32）。

---

## 24. Balance Closure

实施报告 §23 balance closure：

```
txn 73: ai_preview_execution:19:primary          delta=-15 balance_after=99985
txn 75: ai_preview_execution:20:primary          delta=-15 balance_after=99970
txn 76: ai_preview_execution:21:primary          delta=-15 balance_after=99955
txn 77: ai_preview_execution:21:retry_combined   delta=-15 balance_after=99940

distinct_identities = 4
final_balance = 99940
  = 100000 + (-15)×4 = 99940 ✓
A primary replay 不贡献 extra delta ✓（99985 → 99985 unchanged）
```

```
B_final = B_initial + Σ(distinct legitimate Business Event deltas)
  99940 = 100000 + (-15)×4 ✓
same-execution primary replay extra delta = 0 ✓
```

数据自洽：4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费。id gap=74（A replay IntegrityError 消耗序列，§18 副证，sequence gap 非幂等硬证据——硬证据仍是 same identity + one transaction + balance unchanged）。

---

## 25. Execution Persistence

实施报告 §24：

```
A=19, B=20, R=21 都是 ai_preview_executions 真实持久化行
  id ✓
  merchant_id = dev-merchant ✓
  agent_id = agent-sales ✓
  lifecycle_status = completed（A/B/R 正常返回）✓
  created_at NOT NULL（durable commit 生效）✓
replay_reuses_same_execution_id = True（A replay 复用 execution_id=19 同一持久化 row，非新建）
```

```
EXECUTION_PERSISTENCE = VERIFIED
```

Business Event Identity 基于真实、稳定的 PG execution identity（execution.id，DB PK autoincrement，durable commit 后不可变）。

---

## 26. External API Compatibility

独立确认（代码 diff + Read）：

```
request contract:
  ReplySuggestionProxyRequest（douyin_ai_cs_proxy.py:168-174）
    字段：douyin_account_id / agent_id? / latest_message / max_history_messages?
    无 preview_execution_id required field ✅
    无 idempotency_token / request_id required field ✅

response contract:
  handler 返回 dict[str, Any]（无 response_model，:236 不变）✅
  不新增 execution_id 到 response ✅
```

```
API CONTRACT BREAKING CHANGE = NONE
```

caller 无需传 preview_execution_id / request_id / idempotency_token。identity 完全由 9000 服务端创建。unknown external callers 仍可使用原 contract。focused test T-F1-6a 验证：`ReplySuggestionProxyRequest` 无 preview_execution_id 字段，仅需 douyin_account_id + latest_message。

---

## 27. PREVIEW_REQUEST_RECOVERY_GAP（C4）

独立检查 `CROSS_MODULE_RISK_REGISTER.md` diff（:53-54 新增）：

```
C4 覆盖扩展（2026-08-11 P1-F1 Candidate A）：
  PREVIEW_REQUEST_RECOVERY_GAP 现覆盖两类计费同域入口：
    ① draft-agent AI Preview（POST /agents/{id}/preview）
    ② Trusted Reply-Suggestion（POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion）
  Candidate A 让 Trusted Reply-Suggestion 复用 AiPreviewExecution + ai_preview_execution:{id}:{stage} namespace，
  与 Preview 计费同域，故其 full HTTP request response-lost gap 被本 Gap 准确覆盖。
  不新建独立 TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP。
  same durable execution + same stage replay P1 保护，full request retry OUT_OF_P1。
```

```
C4 = APPLIED CORRECTLY
  覆盖扩展精确表达，未写 RESOLVED
  same durable execution replay safety = P1 protected
  full HTTP request response-lost / resubmit = OUT_OF_P1 / unresolved
```

不写 RESOLVED ✅。Candidate A 已让两者计费同域，复用 PREVIEW_REQUEST_RECOVERY_GAP 语义正确（设计审批 §12 已裁定同类 B 类 problem）。

---

## 28. Naming Debt（C5）

独立检查 `CROSS_MODULE_RISK_REGISTER.md` diff（:70 新增 S6）：

```
S6 | AIPREVIEWEXECUTION_NAMING_DEBT
  （表/模型名"Preview"承载两类计费场景：draft-agent Preview + Trusted Reply-Suggestion；
   DOMAIN_MODEL_CONTAMINATION=NOT PRESENT，模型本身是通用计费 identity 容器，仅命名反映 Preview 专属）
  | M01 | NON_BLOCKING / NAMING_DEBT
  （P1-F1 Candidate A 后登记；不在 P1 重命名，未来加可选 source 字段属 OUT_OF_P1）
```

```
C5 = APPLIED CORRECTLY
  AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
  DOMAIN_MODEL_CONTAMINATION = NOT PRESENT（准确区分）
  NAMING_DEBT = PRESENT / NON_BLOCKING（准确区分）
```

本轮未 rename model/table ✅。

---

## 29. Canonical DB No-Drift

审批窗口 READ ONLY，未执行 runtime probe。canonical DB no-drift 依据实施报告 §28 + §16 Case B 分类：

```
canonical local PG = unchanged
  residual_dev_txn = 0
  residual_dev_acct = 0
  residual_dev_prev = 0
  canonical_revision = 0034
  canonical_table_count = 61
```

runtime fixture（Case B，CANONICAL_DB_WAS_USED_FOR_RUNTIME_FIXTURE）cleanup 后 residual=0。验证脚本经 worktree 外执行（`e:/work/tmp/f1/`），未入 worktree（`git status` 仅 candidate docs + proxy handler + focused tests + 本报告）。

```
CANONICAL_DB_NO_DRIFT = REPORT_VERIFIED
  Case B（canonical local dev PG 用于 runtime fixture）
  cleanup residual=0
  与 NO_CANONICAL_DB_MUTATION 不是同一事实（Case B 曾写入，但 cleanup 后无残留）
```

**C-RUNTIME correction**：实施报告应明确分类为 Case B，而非暗示 isolated。但 cleanup residual=0 + Case B 是 F-1 双库验证的必要环境，非 scope violation。

---

## 30. Final F-1 Verdict

```
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY
= RESOLVED

TRUSTED REPLY-SUGGESTION BUSINESS EVENT IDENTITY
= ai_preview_execution:{preview_execution_id}:{llm_call_stage}

SAME EXECUTION + SAME STAGE = NO_DOUBLE_CHARGE_VERIFIED
INTENTIONAL NEW GENERATION = DISTINCT_EVENT_VERIFIED
DISTINCT LEGITIMATE STAGE = VERIFIED
IDENTITY CREATION FAIL-CLOSED = VERIFIED
TRUSTED PROXY ACTIVE NONE REGRESSION = 0
COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED = auto_wechat
```

### 证据等级汇总

| 证据 | 独立验证 | 等级 |
|---|---|---|
| candidate diff（durable commit / fail-closed / finalize / exactly one identity）| ✅ 独立代码审查 | CODE_VERIFIED |
| focused tests 7 passed | ✅ 独立运行 | STATIC_TEST_VERIFIED |
| async→sync 正确性 | ✅ 独立确认 suggest_reply 同步 httpx + preview_agent sync 先例 | CODE_VERIFIED |
| 9100 zero-change | ✅ git diff 空 | CODE_VERIFIED |
| pre-existing failure | ✅ stash 对比确认 | PRE_EXISTING / NON_BLOCKING |
| external API no breaking | ✅ ReplySuggestionProxyRequest 无 preview_execution_id | CODE_VERIFIED |
| C4/C5 登记 | ✅ CROSS_MODULE_RISK_REGISTER diff | DOC_VERIFIED |
| F1-PG-1~6 runtime | 依据实施报告 + 代码事实 + 静态测试覆盖 | REPORT_VERIFIED + CODE_VERIFIED（非审批窗口独立 runtime 复现）|
| canonical DB no-drift | 依据实施报告 §28 | REPORT_VERIFIED（Case B, residual=0）|

### 为什么是 APPROVED_WITH_CORRECTIONS 而非 APPROVED

核心 F-1 修复（代码 + 静态测试 + diff + scope）全部独立成立，无 CHANGES_REQUIRED 触发条件。残留 3 项非阻断 correction：

- **C-RUNTIME**：runtime 环境"canonical PG"描述应准确分类为 Case B（CANONICAL_DB_WAS_USED_FOR_RUNTIME_FIXTURE，cleanup residual=0），非暗示 isolated。这是描述精度修正，非 scope violation（Case B 是 F-1 双库验证必要环境）。
- **C-SYNC**：async→sync 修复应在治理文档/报告补正式 `SYNC_HANDLER_CORRECTION = REQUIRED FOR CURRENT CALLING MODEL` 说明（实施报告 §4 已有说明，但治理状态文档 CLAUDE.md 提及简略）。
- **C-PRE-EXISTING**：pre-existing test 分类措辞应明确"stash 对比确认"（实施报告 §15 已述，本审批独立复现）。

### 为什么不是 CHANGES_REQUIRED

逐项核验 CHANGES_REQUIRED 触发条件（§34）：

- create 失败仍能 call 9100？❌ 未发生（fail-closed 502，T-F1-3 + F1-PG-5 验证不 fall through）
- async→sync 带来行为回归？❌ 未发生（与 preview_agent 先例一致，response/exception 语义不变，7 passed）
- same execution replay 重复扣费？❌ 未发生（F1-PG-2，balance unchanged）
- stage separation 人工伪造？❌ 未发生（F1-PG-4 真实 post-generation 校验触发）
- NULL charge 仍存在？❌ 未发生（F1-PG-6，代码 diff 确认必经 preview_execution_id）
- merchant identity 串错？❌ 未发生（context.merchant_id，runtime 5 层一致）
- external API breaking？❌ 未发生（T-F1-6a）
- 9100/migration 越界？❌ 未发生（git diff 空）
- canonical DB 不可接受写入？❌ 未发生（Case B cleanup residual=0）

---

## 31. P1 Status

```
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

F-1 审批通过后，TECHNICAL_CLOSURE 从 `BLOCKED_PENDING_F1_APPROVAL_AND_GLOBAL_REAUDIT` 推进至 `BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT`（F-1 blocker 已解除，仅剩 Global Audit 重跑）。

```
GLOBAL_ACTIVE_NONE_AUDIT = FAILED（保持，须重跑）
  F-1 RESOLVED ≠ GLOBAL_ACTIVE_NONE_AUDIT PASS
  须完整重跑 Global Active None Audit（非仅查 F-1 route）
```

---

## 32. Global Re-Audit Authorization

```
授权下一窗口：
P1-GLOBAL-ACTIVE-NONE-AUDIT-2 FULL RE-RUN
```

不是只审 F-1。必须重新枚举整个 compute surface：

```
目标：
  ACTIVE NONE = 0
  ACTIVE EMPTY = 0
  ACTIVE PARTIAL/SENTINEL = 0
  UNKNOWN ACTIVE = 0
  F-2 继续 DORMANT
```

Global Audit RE-RUN independently APPROVED/VERIFIED 后，方可进入 Final PostgreSQL Concurrent Closure。

---

## 33. Commit Authorization

授权做一次 F-1 implementation closure commit。允许文件：

```
app/routers/douyin_ai_cs_proxy.py
tests/test_trusted_reply_suggestion_compute_idempotency.py
docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md
docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_APPROVAL.md
CLAUDE.md
docs/ai/05_PROJECT_CONTEXT.md
docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

状态变更（commit 时同步）：

```
F-1: RESOLVED_PENDING_APPROVAL → RESOLVED
TECHNICAL_CLOSURE: BLOCKED_PENDING_F1_APPROVAL_AND_GLOBAL_REAUDIT
  → BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT
```

同时保持：

```
GLOBAL_ACTIVE_NONE_AUDIT = FAILED / NEEDS_RE-RUN
COMPUTE-IDEMPOTENCY-001 = OPEN
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

建议 commit message：

```
修复：闭环Trusted Reply-Suggestion幂等计费身份
```

```
DO NOT PUSH
```

---

## 34. 边界遵守确认

- ✅ 未修改 9100 代码（零改，git diff 空）
- ✅ 未创建 migration（复用 0034）
- ✅ 未修改 compute core / record_usage / 其他 11 consumers / database models / frontend / staging-prod
- ✅ 未处理 F-2（DORMANT）/ 9100 least privilege / RB-10
- ✅ 未重命名 AiPreviewExecution（C5 NON_BLOCKING 登记）
- ✅ 未实施 9100 fail-closed hardening（Candidate E OPTIONAL，不实施）
- ✅ 未重跑 Global Active None Audit / 未启动 Final Concurrent Closure / 未宣布 P1 closed
- ✅ F-1 implementation 未 commit / 未 push（candidate diff，本审批后授权 commit）
- ✅ canonical DB 未污染（Case B cleanup residual=0）
- ✅ consumer 验证仅 mock 外部 LLM（chat）

---

## 35. 完成后停止

本审批窗口完成后停止。不得自行：

- 重跑 Global Audit
- 开始 Final Concurrent
- harden compute core
- 修 F-2
- rename AiPreviewExecution
- 处理 HTTP response-lost recovery
- RB-10
- push
- 宣布 P1 CLOSED

---

## 附录：审批纪律确认

- READ ONLY：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push（commit 授权留给 F-1 implementation closure，§33）。
- 未执行 runtime probe（双服务启动超出 READ ONLY 审批窗口能力；runtime 证据依据实施报告 + 代码事实 + 静态测试独立复现判定，证据等级准确标注）。
- 独立复现：focused tests 7 passed、stash 对比 pre-existing failure、suggest_reply 同步性、9100 git diff 空、ReplySuggestionProxyRequest 字段、C4/C5 diff。
- 未采信执行窗口自述：所有核心结论经独立代码审查 + 独立测试运行 + git diff 核查。
```
