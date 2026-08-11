# P1-F1 Trusted Reply-Suggestion Business Event Identity 技术设计

> 任务：`P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-DESIGN`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`BLOCKED_BY_F1`）
> 前序审计：`P1_GLOBAL_ACTIVE_NONE_AUDIT.md`（`FAILED`）+ `P1_GLOBAL_ACTIVE_NONE_AUDIT_APPROVAL.md`（`APPROVED_FAILED_FINDING`）
> Governance checkpoint：`8e59fc0`（`审计：确认Trusted Reply-Suggestion缺失幂等身份`）
> 日期：2026-08-11
> 窗口性质：**DESIGN / AUDIT ONLY**（不实施业务代码、不创建 migration、不修改 proxy/9100、不写 canonical DB）
> Source of Truth：本窗口独立只读代码事实（router/handler/payload/9100 identity 解析/models/既有 Preview 设计）> 审计报告 > 推测

---

## 0. Verdict 速览

| 维度 | 结论 |
|---|---|
| F-1 根因 | Trusted Proxy payload 不含 durable billing identity → 9100 全 None → core legacy 裸扣 |
| Business Event 定义 | 一次"工作台人工触发为会话生成建议回复"（1:N(2) primary+retry_combined）|
| Preferred Strategy | **Candidate A — 复用 AiPreviewExecution + `ai_preview_execution:{id}:{stage}` namespace** |
| 9100 侧改动 | **零改**（ReplySuggestionRequest 已有 `preview_execution_id`，`_report_llm_usage` 已有 Preview 分支）|
| 新 migration | **不需要**（复用 0034 `ai_preview_executions` 表）|
| API contract breaking | **无**（identity 由 9000 服务端创建，非 caller 传入）|
| HTTP response-lost retry | **不承诺**（与 Preview 同口径 `PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1`）|
| F-1 bar | "ACTIVE consumer become identity-bearing"（消除 None），不扩大为 full request recovery |
| 本窗口实施 | **NO**（设计/审计，交独立设计审批）|

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

---

## 1. Baseline / Governance

```text
Git baseline                = 8e59fc0
GLOBAL_ACTIVE_NONE_AUDIT    = FAILED
F-1: TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = OPEN / P1 BLOCKER
COMPUTE-IDEMPOTENCY-001     = OPEN
TECHNICAL_CLOSURE           = BLOCKED_BY_F1
Final PG Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

F-1 独立确认（审计 + 审批，`APPROVED_FAILED_FINDING`）：

```text
9000 Trusted Reply-Suggestion Proxy
  → ACTIVE authenticated business API（main.py:139 挂载 + require_permission("auto_wechat:douyin_ai_cs")）
  → payload 无 durable billing identity
  → 9100 _report_llm_usage 全 None
  → idempotency_key=None
  → record_usage(None) legacy 裸扣
  → PostgreSQL idempotency_key=NULL ComputeTransaction（NULL 不参与唯一约束，retry 重复扣费）
```

既有基线不受影响：11/11 Consumer Migration COMPLETE；0032/0033/0034/0005 PG_RUNTIME_VERIFIED；APPLICATION_ROLE_PERMISSION_GAP RESOLVED；FRESH_BOOTSTRAP_PRINCIPAL_REPRODUCIBILITY VERIFIED。

---

## 2. Current F-1 Chain（独立重建）

本窗口独立从代码重建调用链（不依赖审计报告自述）：

```text
[1] 9000 Trusted Reply-Suggestion Proxy
    app/routers/douyin_ai_cs_proxy.py:230 @router.post("/conversations/{conversation_id}/reply-suggestion")
    handler create_reply_suggestion_proxy (:231)
    app/main.py:139 app.include_router(douyin_ai_cs_proxy.router)  ← 主 9000 生产 app 挂载
    prefix /integrations/douyin-ai-cs (:40)
    鉴权：Depends(get_request_context_required) (:234)
          require_permission("auto_wechat:douyin_ai_cs")(context) (:238)
          context.merchant_id 必须存在 (:239-243)
          ↓

[2] merchant / agent / binding 校验（服务端，可信上下文）
    validate_douyin_agent_binding (:245-251) — douyin_account_id + agent_id + conversation_id 绑定校验
    get_agent (:262) — agent 存在 + active
    _build_allowed_category_keys (:274-278)
    account_open_id 从 binding audit 推导 (:279-282)
          ↓

[3] payload 构造（:316-362）— ★ 无 durable billing identity
    字段来源：
      RequestContext（服务端）：tenant_id (:317)、merchant_id (:320)
      前端 request body：douyin_account_id、agent_id、latest_message、max_history_messages
      DB 查询：agent_config (:322-343)、conversation_history (:346)、customer_memory (:347)、
              direct_llm_policy (:348)、forbidden_words (:350)、contact_state (:352-361)
    ★ 不含 run_id / attempt_count / preview_execution_id / request_id / idempotency_token
          ↓

[4] 9000→9100 suggest_reply（:364-369）
    get_xg_douyin_ai_cs_client().suggest_reply(context, conversation_id, request=payload)
    app/services/xg_douyin_ai_cs_client.py:52 def suggest_reply
      → _post_json("/douyin/reply-suggestion", payload) (:65)
      → client 覆盖注入 merchant_id (:62) + conversation_short_id (:63)，不注入 identity
          ↓

[5] 9100 路由入口
    apps/xg_douyin_ai_cs/routers/ai_reply.py:21 POST /douyin/reply-suggestion
    → build_reply_suggestion(conversation_id, request) (:29)
    reply_decision_service.py:628 def build_reply_suggestion
    → _dispatch_reply_with_kernel_mode (:692/:707)
    → _build_llm_reply (:567/:588/:613)
          ↓

[6] LLM billable call
    _build_llm_reply (:981) → client.chat(messages) (:1060)  ← LLM 计费调用
          ↓

[7] usage report + identity resolution = None  ★ F-1 根因
    _report_llm_usage(request=request, llm_call_stage="primary") (:1160)
    _report_llm_usage(request=request, llm_call_stage="retry_combined") (:1236)
    _report_llm_usage (:3763):
      :3786-3788 getattr(request, "run_id"/"attempt_count"/"preview_execution_id", None) 全 None
        （ReplySuggestionRequest schemas.py:178/179/184 默认 None；proxy payload 不设）
      :3811 legacy 兼容路径 → idempotency_key 保持 None (:3789)
          ↓

[8] ComputeUsageClient.report_usage(idempotency_key=None)
    :3814 → compute_usage_client.py:260 payload["idempotency_key"]=None
    → HTTP body "idempotency_key": null
          ↓

[9] 9000 /internal/compute/usage → record_usage(idempotency_key=None)
    app/routers/compute.py:482 透传 None
    apps/compute/services.py:631 签名允许 None
    :681 if idempotency_key: None falsy → 跳过幂等块
    :772 if idempotency_key is None: → warning
    :777-800 legacy 裸扣 → ComputeTransaction(idempotency_key=NULL) commit
          ↓

[10] PostgreSQL ComputeTransaction(idempotency_key=NULL)
     app/models.py:997 nullable=True
     app/models.py:941 UniqueConstraint(merchant_id, idempotency_key) — 复合 UNIQUE 非 partial
     PostgreSQL: NULL 不参与唯一约束 → 多行 NULL 可并存 → retry 重复扣费
```

完整链成立，与审计/审批独立复核一致。

---

## 3. Trusted Proxy Business Semantics

### 3.1 业务定位

基于代码事实（非文档断言）：

- **路由**：`POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`
- **path 参数**：`conversation_id`（真实会话键，透传为 `conversation_short_id`）
- **handler 行为**：9000 注入可信商户上下文 → 读 DB（agent_config / conversation_history / customer_memory / lead / autoreply settings / forbidden_words / contact_state）→ 调 9100 生成建议 → 强制 `auto_send=False`（:377-378）→ 返回建议文本
- **不发送**：`auto_send` 被代理层强制 False，不进 outbox，不触发真实抖音发送
- **读真实客户会话数据**：`conversation_history`（DB 查询）、`customer_memory`、`lead`、`contact_state`——非草稿输入
- **鉴权**：`auto_wechat:douyin_ai_cs`（商户侧工作台权限）
- **in-repo caller = 0**（前端 wrapper 已定义+re-export，无组件实际调用；`generateReply` 不存在）

### 3.2 业务事件定义（§1 核心问题）

> Trusted Reply-Suggestion 的一个"可计费业务事件"是什么？

**一次"商户侧工作台人工触发为某个真实客户会话生成一条建议回复"= 1 个 business event。**

该 event 的计费 cardinality = 1:N(2)：
- primary LLM 调用（:1160）= 1 charge
- retry_combined LLM 调用（:1236，留资合规纠正触发）= 1 charge（同 execution 不同 stage）

### 3.3 四种场景裁定（§1 A/B/C/D）

| 场景 | 是否同 business event | 计费 | identity 要求 |
|---|---|---|---|
| A. 同一请求的 HTTP 技术重试/重放 | SAME | 只扣一次 | retry 必须复用 same execution |
| B. 用户明确再次点击"重新生成" | **NEW** | 独立计费 | 新 execution |
| C. 同会话收到新客户消息后再次生成 | **NEW**（不同 latest_message）| 独立计费 | 新 execution |
| D. retry_combined（留资合规纠正）| SAME execution, **不同 stage** | 独立 stage 计费 | `{execution}:{stage}` |

**关键约束**：
- identity 不能是 `conversation_id` alone（C 会合并不同消息的生成）
- identity 不能是 `message_id` alone（B 会合并用户两次主动生成）
- identity 不能是 random UUID per request / timestamp / hash(payload)（A 的 HTTP retry 会产生新 key → 双扣）
- identity 必须是 **durable execution id**，9000 在 LLM 前 commit，same business action 的 HTTP retry 复用

### 3.4 业务语义未阻塞

```text
BUSINESS_EVENT_SEMANTICS = RESOLVED
```

业务事件定义清晰（§3.2/§3.3），可继续设计 identity。

---

## 4. Current Client/API Reality（§5）

### 4.1 前端 wrapper

- `frontend/src/api/douyinAiCsClient.ts:766` `getTrustedReplySuggestion(conversationId, payload)` 定义
- `frontend/src/features/douyin-cs/api.ts:17` re-export
- `TrustedReplySuggestionRequest`（:260-266）：`account_id` / `douyin_account_id?` / `agent_id?` / `latest_message` / `max_history_messages?`
- 注释（:259）：tenant_id/merchant_id 由 9000 从 RequestContext 注入，前端不传

### 4.2 in-repo caller 数量

```text
IN-REPO CALLER COUNT = 0
```

- `getTrustedReplySuggestion`（标识符）：3 处（:757 注释、:766 定义、api.ts:17 re-export）
- `getTrustedReplySuggestion(`（带括号调用）：仅 :766 定义本身
- `generateReply`（文档 P1_FE_E2E_ACCEPTANCE.md 声称的调用方）：`frontend/` 内 0 匹配（不存在）

### 4.3 为何仍 ACTIVE

依冻结 ACTIVE 定义（"当前正式部署中可在正常运行条件下到达并产生 compute charge"）：

| 维度 | 证据 |
|---|---|
| REGISTERED | main.py:139 挂载 |
| EXTERNALLY REACHABLE | HTTP POST route |
| AUTHENTICATED | get_request_context_required + require_permission("auto_wechat:douyin_ai_cs") |
| CHARGE-CAPABLE | suggest_reply → 9100 LLM → _report_llm_usage → record_usage |
| 无禁用门禁 | 无 env/feature flag hard-coded fail closed |
| 文档正式用途 | 4 份当前正式文档（09_INTERFACE_CONTRACT §16.3 / P1_RAG_PRODUCTIZATION_GAP_REVIEW / PHASE_3F / P6_DY_AI_CS_STRUCTURED_REPLY）标注为正式工作台主链路 |

"无当前 repo frontend caller"不证明 inactive（外部客户端/桌面端/历史版本/直接 HTTP 均可能）。**ACTIVE 分类维持**，不因无 caller 删 route。

---

## 5. Preview Comparison（§7）

| 维度 | Trusted Proxy | Preview |
|---|---|---|
| 使用者 | 商户侧工作台（真实会话建议）| 草稿智能体预览（draft-agent）|
| 是否真实客户会话 | **是**（conversation_id 真实会话键，读 DB conversation_history）| **否**（conversation_id="agent-preview" 硬编码 :317）|
| 是否读 DB 客户事实 | 是（customer_memory / lead / contact_state）| 否（account_open_id="agent-preview" 硬编码 :275）|
| 是否用于人工工作台 | 是 | 是（草稿调试）|
| execution 生命周期 | **当前无** | 有（AiPreviewExecution running/completed/failed）|
| 是否持久化结果 | record_ai_reply_decision 决策日志（非 lifecycle identity）| _finalize_preview_execution lifecycle |
| 是否允许重新生成 | 是（用户主动 = NEW event）| 是（每次 preview_agent 新建 execution）|
| billing semantics | **当前 None** ★ | 已冻结 `ai_preview_execution:{id}:{stage}` |
| API response | dict[str, Any]（无 response_model）| AiAgentPreviewResponse |
| 9100 入口 | suggest_reply（同一入口）| suggest_reply（同一入口）|
| auto_send | 强制 False（:377）| 不发送（preview 语义）|
| stage cardinality | 1:N(2) primary+retry_combined | 1:N(2) primary+retry_combined |

**计费语义核心结论**：两者都是"9000 工作台人工触发 → suggest_reply → 9100 LLM → primary + 可能 retry_combined → 不发送"的 1:N(2) 计费模型。差异在输入数据层（草稿 vs 真实会话），**不影响计费幂等语义**。

---

## 6. Intentional Regeneration Semantics（§12）

### Case R1 — 用户点一次生成，成功

```text
execution A (9000 创建 + commit)
  → primary charge A:primary
  → （若触发纠正）retry_combined charge A:retry_combined
  → finalize A = completed
```

### Case R2 — 同一请求网络超时客户端自动 retry

**预期**：still execution A → no second primary charge。

**本设计承诺范围**（§8 详述）：same execution + same stage replay → REPLAY（9100 内部 primary/retry_combined 复用同一 request 对象，已由 `_report_llm_usage` 同 request 透传保证）。

**HTTP response-lost retry**（9000 未收到 9100 响应 → 客户端重发 POST）：当前**不承诺**复用 same execution——与 Preview 同口径（`PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1`，§8/§35）。

### Case R3 — 用户过 10 秒主动点击"重新生成"

```text
NEW execution B (≠ A) → 独立合法 charge
```

用户意图明确再次生成 = NEW business event。execution 每次 9000 调用新建（与 Preview `_create_preview_execution` 每次新建同模式）。这是**正确行为**，不是 double charge。

### Case R4 — retry_combined（同 execution 不同 stage）

```text
A:primary + A:retry_combined → 2 个不同 key → 2 次独立合法计费
```

同一 request 对象复用（:1160/:1236 传同一 `request`），`llm_call_stage` 区分。namespace `{execution_id}:{stage}` 正确支持。

---

## 7. HTTP Retry Semantics（§13/§34/§35）

### 7.1 不承诺 HTTP-level response-lost replay

本设计采用 §35 路径（非 §34）：

```text
Idempotency guarantee starts after durable execution has been created.
  same execution + same stage replay → REPLAY（P1 保护）
  full HTTP request response-lost → 新 execution → 新 charge（OUT_OF_P1）
```

### 7.2 为什么满足当前 business contract

1. **既有先例**：Preview 路径（0034 PG_RUNTIME_VERIFIED）已确立同口径——`PREVIEW_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1`。Trusted Proxy 与 Preview 走同一 9100 `suggest_reply` 入口、同一 `_build_llm_reply`、同一 `_report_llm_usage`，计费语义同构。若 Preview 的 HTTP retry gap 可接受为 OUT_OF_P1，Trusted Proxy 同理。
2. **审批 §19 约束**：F-1 修复目标首先是"same Business Event → stable identity → no double charge"，不自动扩大为 full request recovery orchestration。
3. **当前无自动 retry 客户端**：in-repo caller=0，无 `generateReply`，无客户端自动 retry 逻辑证据。未知外部 caller 的 retry 行为属未证实的假设，不据此扩大 scope。
4. **F-1 bar = become identity-bearing**：消除 None，使 ACTIVE 路径产生稳定非空 identity。same execution + same stage replay 的 P1 保护已成立（9100 内部同 request 复用）。HTTP response-lost 的 full request recovery 是独立的 RELIABILITY GAP，与 Preview / DailyReport / Training / RAG Ingest / RAG Query 的 REQUEST_RECOVERY_GAP 同口径。

### 7.3 若未来需 HTTP-level replay

属 future governance（`TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP`），需 Caller Idempotency Token + get-or-create 机制（Candidate D）。本设计登记为 OUT_OF_P1（§25），不实施。

---

## 8. Candidate A-E（§43 Comparison Matrix）

### Candidate A — 复用 AiPreviewExecution

**方案**：Trusted Proxy handler 在 suggest_reply 前调 `_create_preview_execution`（durable commit）+ 透传 `preview_execution_id` 到 payload + finalize lifecycle。namespace `ai_preview_execution:{id}:{stage}`。

| 评价维度 | 评分 |
|---|---|
| semantic correctness | ✅ 计费业务事件同构（工作台 LLM 建议生成，1:N(2)，不发送）|
| retry stability | ✅ same execution + same stage replay → REPLAY（9100 同 request 复用）|
| intentional regeneration | ✅ 每次 9000 调用新建 execution = NEW event |
| migration need | ✅ **无新 migration**（复用 0034 ai_preview_executions 表）|
| API impact | ✅ **无 breaking**（identity 9000 服务端创建，非 caller 传入）|
| compatibility | ✅ 9100 侧零改（ReplySuggestionRequest 已有 preview_execution_id，_report_llm_usage 已有 Preview 分支 :3807）|
| tenant isolation | ✅ merchant_id 来自 RequestContext，execution.merchant_id 服务端设 |
| complexity | ✅ 最小（proxy handler ~5 行 + finalize）|
| observability | ✅ execution_id 可追溯 |
| failure recovery | ✅ finalize failed lifecycle |

### Candidate B — 新建 Durable Trusted Suggestion Execution

**方案**：新建 `TrustedReplySuggestionExecution` 表，绑定 conversation_id/message，独立 namespace。

| 评价维度 | 评分 |
|---|---|
| semantic correctness | ✅ 独立语义清晰 |
| migration need | ❌ **新表 + migration**（违反 YAGNI，AiPreviewExecution 已满足计费容器需求）|
| API impact | 中（可独立设计字段）|
| complexity | ❌ 高（新模型 + migration + 9100 新 identity 分支）|
| 9100 改动 | ❌ 需 _report_llm_usage 新增分支 |

**裁定**：过度工程。Trusted Proxy 与 Preview 计费语义同构，无独立表必要。ponytail 原则：不新建不需要的表。

### Candidate C — 复用 Conversation/Message Identity

**方案**：用 webhook event_id / server_message_id / conversation_short_id 作 identity。

| 评价维度 | 评分 |
|---|---|
| semantic correctness | ❌ message_id alone 会合并 Case R3（用户主动重新生成）→ 错误 |
| retry stability | ❌ conversation_id alone 会合并 Case C（不同消息）|

**裁定**：**REJECTED**。§3.3 已证 message_id/conversation_id alone 不能作 identity（会错误合并合法独立生成事件）。且 Trusted Proxy payload 不含 webhook event_id / server_message_id（`from_user_id=""` 硬编码 :358）。

### Candidate D — Caller Idempotency Token + Durable Execution

**方案**：caller 生成 stable request token，9000 get-or-create execution by token。

| 评价维度 | 评分 |
|---|---|
| HTTP retry protection | ✅ 解决 HTTP response-lost retry |
| semantic correctness | ✅ |
| API impact | ❌ 需 caller 提供 token（breaking，in-repo caller=0 但未知外部 caller）|
| migration need | 中（execution 表加 token unique 约束）|
| F-1 bar | ❌ **超出 F-1 scope**（审批 §19：不扩大为 full request recovery）|

**裁定**：**OUT_OF_P1**（future hardening，§7.3）。F-1 bar = become identity-bearing，不要求 full request recovery。Candidate A 已满足 F-1 bar。若未来需 HTTP-level replay，再评估 Candidate D。

### Candidate E — 9100 Fail-Closed Hardening（§30/§32）

**方案**：9100 `_report_llm_usage` 检测 active context 无 identity 时 fail closed（不 report / 不 LLM）。

| 评价维度 | 评分 |
|---|---|
| defense-in-depth | ✅ 防止未来漏传 identity |
| F-1 直接修复 | ❌ 不消除根因（proxy 仍不传 identity）|
| compatibility risk | ❌ 可能影响 legacy/dev 路径（§31）|

**裁定**：**OPTIONAL HARDENING**（§25），非 F-1 REQUIRED。Candidate A 已让 Trusted Proxy become identity-bearing。9100 fail-closed 属额外防御层，需独立评估兼容影响（§32）。

### Candidate Matrix 汇总

| Candidate | 语义正确 | retry 稳定 | 新 migration | API breaking | 9100 改动 | F-1 满足 | 裁定 |
|---|---|---|---|---|---|---|---|
| A 复用 AiPreviewExecution | ✅ | ✅ | 无 | 无 | 零 | ✅ | **PREFERRED** |
| B 新建独立 execution | ✅ | ✅ | 新表 | 中 | 需 | ✅ | REJECTED（YAGNI）|
| C message identity | ❌ | ❌ | — | — | — | ❌ | REJECTED |
| D caller token + get-or-create | ✅ | ✅+HTTP | 可能 | 有 | 可能 | 超出 | OUT_OF_P1 |
| E 9100 fail-closed | — | — | 无 | 风险 | 需 | 防御非根因 | OPTIONAL |

---

## 9. Preferred Strategy

```text
PREFERRED STRATEGY = Candidate A
  复用 AiPreviewExecution + ai_preview_execution:{id}:{stage} namespace
  proxy handler: _create_preview_execution (durable commit before suggest_reply)
              + payload["preview_execution_id"] = execution.id
              + _finalize_preview_execution (completed/failed)
  9100 侧: 零改
  migration: 无（复用 0034 表）
  API contract: 无 breaking
```

### 为什么 same event stable

- execution.id 是 DB PK（Integer autoincrement），durable commit 后不可变。
- same execution + same stage replay → same key `ai_preview_execution:{id}:{stage}` → M07 IDEMPOTENT_REPLAY。
- primary / retry_combined 同 request 对象复用 execution_id，`llm_call_stage` 区分。

### 为什么 intentional new generation independent

- 每次 9000 handler 调用 `_create_preview_execution` 新建一行 → 新 execution.id → 新 key → 独立合法计费。
- 用户主动"重新生成"（Case R3）= 新 HTTP 请求 = 新 handler 调用 = 新 execution = NEW event。

### 为什么 stage separation 正确

- retry_combined（:1236）与 primary（:1160）传同一 `request` 对象 → 同一 `preview_execution_id` → 同 execution。
- `llm_call_stage` 不同（primary / retry_combined）→ 不同 key → 独立合法计费。
- 不为 retry_combined 创建新顶层 execution（§22）。

### 为什么可复用 AiPreviewExecution（§26 语义证明）

| 维度 | Trusted Proxy | AiPreviewExecution | 一致 |
|---|---|---|---|
| same domain | M01/M03 AI 客服建议生成计费 | M01 Preview 计费 | ✅ |
| same lifecycle | running→completed/failed | running→completed/failed | ✅ |
| same source | 9000 工作台人工触发 | 9000 工作台人工触发 | ✅（区别于 AutoReply webhook 自动触发）|
| same semantics | 一次建议生成 1:N(2) | 一次建议生成 1:N(2) | ✅ |
| same retention | 持久不可清空 | 持久不可清空 | ✅ |
| same reporting | ai_preview_execution namespace | ai_preview_execution namespace | ✅ |

复用基于**计费业务事件语义同构**，非"因为有 id 字段"（§26 警告）。两者都是"9000 工作台人工触发 LLM 建议生成，不发送，1:N(2) stage"。差异在输入数据层（草稿 vs 真实会话），不影响计费幂等。

---

## 10. Durable Execution Model（§9/§10）

### 10.1 复用既有 AiPreviewExecution（models.py:1344-1374）

```text
表：ai_preview_executions（0034 已建，无新 migration）
字段：
  id              = billing identity PK
  merchant_id     = RequestContext.merchant_id（服务端）
  agent_id        = request.agent_id
  lifecycle_status = running → completed/failed
  created_at / completed_at
```

### 10.2 不绑定会话字段（YAGNI）

AiPreviewExecution 当前不绑 conversation/message。Trusted Proxy 的会话定位由 `record_ai_reply_decision`（:387-399，决策日志）+ 9100 返回的 `conversation_id` 承担，非 billing identity 职责。F-1 bar 是计费幂等，非会话报表。若未来需按会话计费报表，可加可选 `conversation_short_id` 字段（future，OUT_OF_P1）。

### 10.3 不需要新表（§25）

Candidate A 无需新 durable execution schema——复用 0034 `ai_preview_executions`。

---

## 11. Business Event Identity（§27）

```text
event_namespace    = ai_preview_execution
business_event_id  = {preview_execution_id}:{llm_call_stage}
idempotency_key    = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"

llm_call_stage = primary / retry_combined
cardinality    = 1 execution : up to 2 charge events
```

与 Preview 完全同 namespace（因计费业务事件同构，§9）。

---

## 12. Creation / Commit Timing（§18）

冻结顺序：

```text
auth / merchant validation (:234-243)
  → agent binding validation (:245-260)
  → agent active check (:262-272)
  → ★ create AiPreviewExecution + db.commit() (durable, before 9100 call)
  → payload["preview_execution_id"] = execution.id
  → suggest_reply → 9100 LLM (计费源)
  → usage report (_report_llm_usage 读 preview_execution_id 构造 key)
  → finalize lifecycle (completed/failed)
```

**不是** LLM → usage → later create execution。execution 在 LLM 前 durable commit，保证计费身份先于计费发生。

---

## 13. Stage Contract（§21/§22）

### 13.1 Trusted Proxy 可达 stage 集合

Trusted Proxy 走 `suggest_reply` → `build_reply_suggestion` → `_dispatch_reply_with_kernel_mode` → `_build_llm_reply`（:981）。与 Preview 完全同一 `_build_llm_reply`，故 stage 集合相同：

```text
primary (:1160)         — 总是触发（主 chat）
retry_combined (:1236)  — 条件触发（6 个留资合规纠正器之一命中，:1184-1223）
```

max 2 charge per execution（1:N(2)）。

### 13.2 retry_combined 不创建新 execution（§22）

primary 与 retry_combined 传同一 `request` 对象（:1160/:1236），同一 `preview_execution_id` → 同 execution。`llm_call_stage` 区分 → 不同 key → 独立合法 stage 计费。不为 retry_combined 创建新顶层 execution。

---

## 14. API Contract（§15）

### 14.1 9000 proxy request model

`ReplySuggestionProxyRequest`（:164-170）：无需新增字段。identity 由 9000 服务端创建（`_create_preview_execution`），非 caller 传入。

### 14.2 9100 ReplySuggestionRequest

`schemas.py:154-184`：**已有** `preview_execution_id: int | None = None`（:184）。无需改 schema。9000 透传 `preview_execution_id` 到 payload，9100 反序列化后 `_report_llm_usage` 读 `getattr(request, "preview_execution_id", None)`（:3788）。

### 14.3 前端 TrustedReplySuggestionRequest

`:260-266`：无需改。identity 不由前端提供。

### 14.4 是否新增 execution_id 到 response

**不新增**（§37）。execution_id 是内部计费 identity，当前 in-repo caller=0，无 follow-up 需求。未来若需 retry/observability/follow-up，再评估（OUT_OF_P1）。

```text
API CONTRACT BREAKING CHANGE = NONE
```

---

## 15. Compatibility Strategy（§16）

### 15.1 旧 caller 处理

无需旧 caller 兼容策略——identity 由 9000 服务端在 handler 内部创建，对 caller 透明。无论 caller 是前端 wrapper、外部 HTTP 客户端、还是历史版本，只要调用 `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`，9000 都会创建 execution + 透传 identity。

### 15.2 不继续 ACTIVE None billing

Candidate A 后，Trusted Proxy 不再可能产生 `idempotency_key=None`（execution 创建成功即透传非空 id；创建失败 fail-closed，§17）。

---

## 16. Merchant Isolation（§19/§39）

- `execution.merchant_id` = `context.merchant_id`（RequestContext，服务端可信），非前端传入。
- execution lookup 不由 client 提供 execution_id（§39），client 无法引用其他 merchant execution。
- `_create_preview_execution(db, context.merchant_id, agent_id)`（agents.py:61-76 同模式）。
- 9100 `_report_llm_usage` 用 `request.merchant_id`（payload :320，9000 注入）。

---

## 17. Failure Persistence（§23/§17 Fail-Closed）

### 17.1 Fail-Closed（§17）

如果 `_create_preview_execution` 失败（DB 异常 / commit 失败），handler 必须 **fail closed**：

```text
execution 创建失败 → 不调 suggest_reply（不调 LLM）→ 返回 502/500
```

不得在无 identity 时继续 LLM 计费。具体 HTTP 语义由实施窗口提出（建议 502 `PREVIEW_EXECUTION_CREATE_FAILED` 或 500）。

### 17.2 failed request 保留 execution（§23）

```text
execution A created (running)
  → suggest_reply 失败（9100 异常 / LLM 异常）
  → finalize A = failed
  → execution A 保留（stable identity）
```

failed execution 保留对审计 / billing reconciliation / 诊断有价值。lifecycle 三态 running/completed/failed（与 Preview 同）。

### 17.3 不设计复杂状态机（§23）

running/completed/failed 三态足够。不引入 partial/billing 状态（billing truth 只归 M07 ComputeTransaction）。

---

## 18. 9100 Propagation（§28/§29）

### 18.1 9000→9100 透传

`xg_douyin_ai_cs_client.py:52 suggest_reply`：`payload = {**request, "merchant_id":..., "conversation_short_id":...}`（:60-64）。9000 handler 在 payload 设 `preview_execution_id`（:316-362 构造时），client 整 dict 透传，9100 收到 `preview_execution_id`。

### 18.2 9100 identity 解析

`_report_llm_usage`（:3786-3811）：
- `preview_execution_id` 非空 + run_id/attempt_count 均 None → 走 Preview 分支（:3807）→ `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`。
- Trusted Proxy 不设 run_id/attempt_count → 不触发 mixed guard（:3792）。

### 18.3 Namespace Collision（§29）

Trusted Proxy 透传 `preview_execution_id`（非 run_id/attempt_count）→ 走 Preview 分支，不与 Auto Reply 混。**exactly one top-level execution identity source**。mixed guard（run_id + preview_execution_id 同时）→ warning 退 None，但 Trusted Proxy 不设 run_id，故不 mixed。

### 18.4 9100 侧零改

ReplySuggestionRequest 已有 `preview_execution_id`（:184），`_report_llm_usage` 已有 Preview 分支（:3807）。9100 无需任何代码改动。

---

## 19. Guard / Fail-Closed Strategy（§30/§31/§32）

### 19.1 Consumer-specific fix（REQUIRED FOR F-1）

Trusted Proxy 总能提供合法 identity（Candidate A）。这是 F-1 核心修复。

### 19.2 9100 fail-closed hardening（OPTIONAL，§32）

评估：若 Trusted Proxy 未来代码意外漏传 identity，是否应 9100 检测 active context 无 identity 时 fail closed？

- **可行性**：需精准限定 Trusted/Preview/AutoReply 场景（不能误伤 legacy/dev）。
- **兼容影响**：当前 `_report_llm_usage` 全 None 分支（:3811）是 legacy 兼容路径，可能有未知 legacy caller。9100 fail-closed 会 break 这些 caller。
- **裁定**：**OPTIONAL HARDENING**（defense-in-depth），非 F-1 REQUIRED。Candidate A 已消除 Trusted Proxy 的 None。9100 fail-closed 需独立评估兼容影响，不纳入 F-1 scope（§32）。

### 19.3 Core hardening（OUT_OF_P1，§31）

`record_usage(None)` globally forbidden → **不纳入 F-1**。core None 兼容是 COMPATIBILITY CONTRACT，可能服务 legacy/dev/未知 caller。F-1 目标是 ACTIVE consumer become identity-bearing，非 core API 全局 reject None。future hardening opportunity。

---

## 20. Migration Need（§25）

```text
MIGRATION REQUIRED = NO
```

Candidate A 复用 0034 `ai_preview_executions` 表（已 PG_RUNTIME_VERIFIED）。无新表、无新列、无新约束。

---

## 21. Concurrency Semantics（§36）

Candidate A 每次 handler 调用新建 execution（`_create_preview_execution`），无 get-or-create 并发竞争（每请求独立 execution.id）。无 `(merchant, client_token) UNIQUE` 约束需求。

**concurrency 风险**：若两个并发 HTTP 请求为同一 business action（Case R2 HTTP retry 并发），会产生两个 execution → 两次 charge。但这属 HTTP response-lost replay 范畴（OUT_OF_P1，§7），Candidate A 不承诺解决。

实施后可做 focused F1 concurrency 验证，但 Final PostgreSQL Concurrent Closure 保持后续独立 Gate（§36）。

---

## 22. Runtime Verification Contract（§33）

实施后 E2E（隔离 PG + mock LLM provider）：

### F1-PG-1 First Event

```text
Trusted suggestion execution A
  stage primary
  → exactly one ComputeTransaction(idempotency_key=ai_preview_execution:{A}:primary)
```

### F1-PG-2 Same Event Replay

```text
same A, same primary
  → replay（同 key → IDEMPOTENT_REPLAY）
  → transaction remains 1
  → balance unchanged
```

### F1-PG-3 Intentional New Generation

```text
new HTTP request (用户主动重新生成)
  → execution B != A
  → independent legitimate charge
```

### F1-PG-4 Stage Separation

```text
A primary + A retry_combined (触发留资合规纠正)
  → 2 个不同 key
  → 2 次独立合法计费
```

### F1-PG-5 None Elimination

```text
Trusted Proxy active path
  → idempotency_key ≠ None（execution.id 非空）
  → 0 NULL ComputeTransaction from Trusted Proxy
```

### F1-PG-6 Fail-Closed

```text
_create_preview_execution 失败 → 不调 LLM → 无 charge
```

---

## 23. Global Re-Audit Contract（§41）

F-1 implementation 通过后**必须重跑** Global Active None Audit：

```text
F-1 design → approval → implementation → PG verification → implementation approval
  → Global Active None Audit RE-RUN
  → ACTIVE NONE = 0
  → Final Concurrent Closure
```

不能仅凭 F-1 测试通过直接进入 Final Concurrent Closure。

---

## 24. 10 Required Questions（§42）

**Q1. Trusted Reply-Suggestion 的业务事件是什么？**

一次"商户侧工作台人工触发为某个真实客户会话生成一条建议回复"。1:N(2) primary + retry_combined。不发送（auto_send 强制 False）。

**Q2. durable identity 在哪里创建？**

9000 proxy handler 内，`_create_preview_execution(db, context.merchant_id, agent_id)`（复用 agents.py:61-76）。AiPreviewExecution 行，id = billing identity。

**Q3. 创建时点在 LLM 前还是后？**

**LLM 前**。durable commit（db.commit + refresh）在 suggest_reply（:364-369）之前。保证计费身份先于计费发生（§12）。

**Q4. retry 如何复用同一 identity？**

9100 `_build_llm_reply` 内 primary（:1160）/ retry_combined（:1236）传同一 `request` 对象 → 同一 `preview_execution_id` → 同 execution → same key for same stage → REPLAY。HTTP response-lost retry（新 POST）不承诺复用（OUT_OF_P1，§7）。

**Q5. 是否需要新 execution table？**

**不需要**。复用 0034 `ai_preview_executions`（§20）。Candidate B 过度工程（YAGNI）。

**Q6. 是否可安全复用现有 Preview execution 模型？**

**可以**。计费业务事件同构（§9/§26）：同为 9000 工作台人工触发 LLM 建议生成、1:N(2)、不发送。差异在输入数据层（草稿 vs 真实会话），不影响计费幂等。复用基于语义同构，非"因为有 id 字段"。

**Q7. 前端/API contract 是否需要新增 execution/request id？**

**不需要**。identity 由 9000 服务端创建，非 caller 传入。9000 ReplySuggestionProxyRequest / 9100 ReplySuggestionRequest（已有 preview_execution_id）/ 前端 TrustedReplySuggestionRequest 均无需改。无 breaking change（§14）。

**Q8. compatibility caller 怎么办？**

无需特殊兼容策略。identity 对 caller 透明，9000 handler 内部创建。任何 caller（前端/外部/历史版本）调用该 route 都自动获得 identity（§15）。

**Q9. failed request 是否仍保留 execution？**

**是**。execution lifecycle running→failed（9100 异常 / LLM 失败）。failed execution 保留 stable identity，供审计/billing reconciliation/诊断（§17）。

**Q10. same event replay 如何验证只扣一次？**

F1-PG-2（§22）：same execution A + same stage primary → 同 key `ai_preview_execution:{A}:primary` → M07 IDEMPOTENT_REPLAY → transaction remains 1 / balance unchanged。不能用 directly replay usage reporter 替代——F-1 位于 HTTP business API，须验证 9100 同 request 复用 identity（§34）。

---

## 25. Required / Optional / Out-of-P1（§44）

### REQUIRED FOR F-1

- Candidate A：proxy handler 加 `_create_preview_execution`（durable commit before suggest_reply）+ payload 透传 `preview_execution_id` + `_finalize_preview_execution`（completed/failed）。
- Fail-closed：execution 创建失败 → 不调 LLM（§17）。
- F1-PG-1~F1-PG-6 验证（§22）。

### OPTIONAL HARDENING

- 9100 fail-closed hardening（§19.2/§32）：detect active context without identity → fail closed。需独立评估兼容影响，非 F-1 REQUIRED。
- AiPreviewExecution 加可选 `conversation_short_id` 字段（§10.2）：未来按会话计费报表。OUT_OF_P1。
- response 返回 execution_id（§14.4/§37）：未来 retry/observability/follow-up。OUT_OF_P1。

### OUT_OF_P1

- HTTP response-lost replay（Candidate D，§7.3）：`TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP`，与 Preview/DailyReport/Training/RAG REQUEST_RECOVERY_GAP 同口径。
- Core `record_usage(None)` globally forbidden（§19.3）：COMPATIBILITY CONTRACT，future hardening。
- F-2 dev_only `/api/compute/internal/usage` 丢 key（DORMANT，future governance）。
- 9100 `xg_douyin_ai_cs` least privilege（future governance）。

---

## 26. Implementation File Scope（§45/§35）

### MODIFY（9000）

| 文件 | 改动 |
|---|---|
| `app/routers/douyin_ai_cs_proxy.py` | handler `create_reply_suggestion_proxy`：suggest_reply 前 `_create_preview_execution(db, context.merchant_id, request.agent_id)` + payload 设 `preview_execution_id`；9100 成功 → finalize "completed"；9100 异常 → finalize "failed"；execution 创建失败 → fail closed（不调 LLM）。复用 agents.py 的 `_create_preview_execution` / `_finalize_preview_execution`（可能需 import 或抽到共享 helper）。 |

### MODIFY（9100）

**无**。`ReplySuggestionRequest` 已有 `preview_execution_id`（schemas.py:184），`_report_llm_usage` 已有 Preview 分支（reply_decision_service.py:3807）。9100 侧零改。

### CREATE

| 文件 | 内容 |
|---|---|
| tests（focused）| F1-PG-1~F1-PG-6 验证（§22）：first event / same replay / new generation / stage separation / none elimination / fail-closed |
| implementation report | `P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md` |

### NO migration

复用 0034 `ai_preview_executions`（§20）。

### READ ONLY / DO NOT MODIFY

- compute core（`apps/compute/services.py` record_usage）
- 其他 11 consumers
- staging/prod
- 9100 unrelated paths（`_build_llm_reply` / `_report_llm_usage` / `build_reply_suggestion`）
- migration / DB-BL
- F-2 dev_only route
- RB-10

### 范围精度

scope 足够精确：核心改动集中在 `douyin_ai_cs_proxy.py` handler（~5-10 行 + finalize + fail-closed guard）。9100 零改。无 migration。下一独立审批可据此裁。

---

## 27. Risks / Rollback（§27）

### 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| execution 创建失败导致 503/502 | 工作台建议生成不可用 | fail-closed 是正确行为（不计费优先于可用性）；finalize failed 保留 identity |
| AiPreviewExecution 表无会话绑定 | 无法按会话计费报表 | OUT_OF_P1（§10.2）；当前 F-1 bar 是幂等非报表 |
| namespace 与 Preview 共享 | 无法区分"草稿预览"与"真实会话建议"计费 | 计费语义同构（§9）；POLICY_PENDING；未来加 source 字段（OUT_OF_P1）|
| HTTP response-lost 双扣 | retry 产生新 execution → 新 charge | 与 Preview 同口径 OUT_OF_P1（§7）；登记 `TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP` |

### Rollback

```text
rollback = git revert proxy handler 改动
```

- proxy handler 改动：新增 `_create_preview_execution` + 透传 + finalize。回滚 = revert 该 handler 改动。无 schema 变更，无 data migration，无破坏性。
- 不触碰 canonical DB（验证在隔离 PG，§22）。
- 不触碰 9100（零改）。
- 不触碰 migration（无新 migration）。

---

## 28. Verdict

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

### 设计结论

1. **Business Event 定义清晰**（§3）：一次工作台人工触发建议生成，1:N(2) primary+retry_combined。
2. **Preferred Strategy = Candidate A**（§9）：复用 AiPreviewExecution + `ai_preview_execution:{id}:{stage}` namespace。
3. **9100 侧零改**（§18）：ReplySuggestionRequest 已有 preview_execution_id，_report_llm_usage 已有 Preview 分支。
4. **无新 migration**（§20）：复用 0034 表。
5. **无 API breaking**（§14）：identity 9000 服务端创建，对 caller 透明。
6. **HTTP response-lost 不承诺**（§7）：与 Preview 同口径 OUT_OF_P1。
7. **Fail-closed**（§17）：execution 创建失败不调 LLM。
8. **F-1 bar 满足**：ACTIVE Trusted Proxy become identity-bearing，消除 None。
9. **Global Re-Audit Required**（§23）：F-1 实施后重跑 Global Active None Audit。

### 不实施

本窗口为 DESIGN/AUDIT ONLY：

```text
DO NOT COMMIT
DO NOT MODIFY proxy handler
DO NOT MODIFY 9100
DO NOT CREATE migration
DO NOT MODIFY canonical DB
DO NOT RE-RUN Global Audit
DO NOT START Final Concurrent Closure
```

设计 candidate 不提交（§49），交独立设计审批窗口。

### P1 状态（继续冻结）

```text
GLOBAL_ACTIVE_NONE_AUDIT = FAILED
F-1 = OPEN / DESIGN_READY_FOR_APPROVAL
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_F1
Final PG Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

### 下一步

```text
本设计交独立设计审批窗口。
审批通过后，由独立实施窗口：
  1. 修改 app/routers/douyin_ai_cs_proxy.py handler（Candidate A）
  2. 新增 focused tests（F1-PG-1~F1-PG-6）
  3. 隔离 PG E2E 验证
  4. 实施审批
  5. 重跑 Global Active None Audit（ACTIVE None = 0）
  6. 方可进入 Final Concurrent Closure
不得借实施窗口处理 F-2 / core None hardening / HTTP request recovery / 9100 least privilege / RB-10。
```

---

## 设计窗口停止点

```text
P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-DESIGN:
VERDICT = DESIGN_READY_FOR_APPROVAL
  Business Event = 一次工作台人工建议生成（1:N(2)）
  Preferred = Candidate A（复用 AiPreviewExecution + ai_preview_execution:{id}:{stage}）
  9100 侧 = 零改
  migration = 无
  API breaking = 无
  HTTP response-lost = OUT_OF_P1（与 Preview 同口径）
  F-1 bar = become identity-bearing（消除 None）
本窗口不实施，停止。
```

未自行：实现 F-1 / 创建 migration / 修改 proxy / 修改 9100 / 重新跑 Global Audit / 开始 Final Concurrent Closure / 修改 compute core / 处理 F-2 / RB-10。
