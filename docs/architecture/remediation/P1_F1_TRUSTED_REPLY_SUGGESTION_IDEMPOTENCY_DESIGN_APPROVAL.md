# P1-F1 Trusted Reply-Suggestion Idempotency — 独立设计审批

> 审批窗口：`P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-DESIGN`（独立设计审批，非设计窗口自述）
> 审查对象：`docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN.md`
> 前序治理：`P1_GLOBAL_ACTIVE_NONE_AUDIT.md`（FAILED）+ `P1_GLOBAL_ACTIVE_NONE_AUDIT_APPROVAL.md`（APPROVED_FAILED_FINDING）
> Governance checkpoint：`8e59fc0`
> 审批日期：2026-08-11
> 窗口性质：READ ONLY 设计审批（未改业务代码、未改 migration、未写 canonical DB、未 commit）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS
Preferred Strategy = Candidate A（复用 AiPreviewExecution + ai_preview_execution:{id}:{stage} namespace）
```

独立裁定：Candidate A 在**领域语义**与**P1 retry 边界**两个硬门槛上均成立。理由：

- **领域语义**：AiPreviewExecution 作为**计费 identity 容器**是通用的（仅 merchant_id/agent_id/lifecycle_status，无 source/type 字段），且**无任何统计/历史/审计/前端展示消费面**会将其限定为"Preview 专用"→ 无当前 domain semantic contamination。billing semantics compatibility 与 domain model compatibility（计费容器层）均成立。命名"Preview"承载两类场景属 NON_BLOCKING NAMING DEBT，非 domain mismatch。
- **P1 retry 边界**：原始合同（APPROVED `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md:29-30`）要求"identity 在计费副作用前持久化"+"retry/process restart/duplicate delivery 复用同一 ID"。所有 11 consumer 实际合同把"same event replay"钉死在"same durable execution + same stage"层。**"full HTTP request response-lost → 重发 → 新 execution → 新 charge"在全部 7 个 Reliability Gap 中统一冻结为 OUT_OF_P1**。Candidate A 不承诺 HTTP response-lost replay 与此治理边界一致。

需实施前应用的 corrections（C1-C5，§29 详述）：runtime fail-closed gate 精度、None regression runtime gate、HTTP replay gap 显式登记、命名债登记。

本窗口未采信设计窗口自述，已独立复核业务语义、代码语义、持久化语义、retry 边界、implementation scope。

---

## 2. Baseline

```
Git baseline = 8e59fc0
git status   = 仅 P1_F1_..._DESIGN.md untracked，无业务代码/migration/DB 改动
F-1 链       = 仍存在（未漂移）
```

F-1 baseline 独立确认（前一审批窗口已验证，本轮 git 无业务代码改动，链未漂移）：

```
9000 Trusted Reply-Suggestion Proxy（main.py:139 挂载 + require_permission）
  → payload 无 durable billing identity（douyin_ai_cs_proxy.py:316-362）
  → 9100 _report_llm_usage 全 None（reply_decision_service.py:3786-3811）
  → idempotency_key=None
  → record_usage(None) legacy 裸扣（services.py:777-800）
  → PostgreSQL idempotency_key=NULL ComputeTransaction
```

```
BASELINE_DRIFT = NO
```

---

## 3. Business Event Semantics

独立裁定设计 §3.2 定义正确：

> 一次"商户侧工作台人工触发、针对真实客户会话生成一条建议回复" = 一个独立可计费 Business Event。

四种场景独立验证（设计 §3.3）：

| 场景 | 是否同 business event | 计费 | identity 要求 | 独立裁定 |
|---|---|---|---|---|
| A. HTTP 技术重试/重放 | SAME | 只扣一次 | retry 必须复用 same execution | ✅ 正确 |
| B. 用户主动"重新生成" | NEW | 独立计费 | 新 execution | ✅ 正确 |
| C. 同会话新客户消息后生成 | NEW（不同 latest_message）| 独立计费 | 新 execution | ✅ 正确 |
| D. retry_combined | SAME execution, 不同 stage | 独立 stage 计费 | `{execution}:{stage}` | ✅ 正确 |

关键约束独立验证：identity 不能是 conversation_id alone（C 会合并）、不能是 message_id alone（B 会合并）、不能是 random UUID/timestamp/hash（A 的 HTTP retry 产生新 key → 双扣）。identity 必须是 durable execution id，9000 在 LLM 前 commit。

```
BUSINESS_EVENT_SEMANTICS = RESOLVED
```

当前产品/API 事实支持该定义。可继续审 identity 格式。

---

## 4. AiPreviewExecution Full Usage Audit

独立审计 `AiPreviewExecution` / `ai_preview_executions` / `preview_execution_id` / `_create_preview_execution` / `_finalize_preview_execution` 全仓使用面：

| 使用面 | 位置 | 类型 | "Preview 专用"解释？ |
|---|---|---|---|
| Model | `app/models.py:1344-1374` | model 定义 | docstring "M01 Preview billing identity 实体"；但字段通用 |
| 建表 migration | `migrations/postgres/auto_wechat/versions/0034_preview_executions.py:32-52` | migration | 表名 + comment "Preview" |
| 创建 helper | `app/routers/agents.py:61` `_create_preview_execution`（module-level private `_`）| router/service | 名为 preview，仅被 preview_agent 调用（:311）|
| finalize helper | `app/routers/agents.py:79` `_finalize_preview_execution`（module-level private `_`）| router/service | 名为 preview |
| 唯一 SELECT | `agents.py:90` `_finalize_preview_execution` 内按 id 取行写回 lifecycle_status | service | 不输出/不展示 |
| 9100 幂等键构造 | `reply_decision_service.py:3807-3810` | service | namespace 前缀硬编码 `ai_preview_execution:`；**不 import/query 表** |
| 9100 schema | `schemas.py:184` `preview_execution_id: int \| None = None` | schema | 注释 "Preview 幂等 identity 透传" |
| Preview handler | `agents.py:311-312, :322, :343` | router | preview_agent 专用 |
| Tests | `tests/test_preview_compute_idempotency_migration.py`（PV-1~PV-6 + None count + C2）| tests | 围绕 Preview 语义 |
| Docs | `P1_PREVIEW_EXECUTION_IDENTITY_DESIGN.md` 等 | docs | 全部 Preview 定位 |
| 前端 | — | — | `frontend/` 搜索 0 匹配 |
| 统计/历史/审计/报表 | — | — | **无任何消费面** |

---

## 5. Domain Compatibility

### 5.1 字段层

AiPreviewExecution 字段（models.py:1368-1374）：`id` / `merchant_id` / `agent_id` / `lifecycle_status` / `created_at` / `completed_at`。

**无** `source` / `execution_type` / `scenario` / `mode` / `purpose` 字段。`agent_id`（comment "draft-agent 等"）无约束/无枚举/可空，不能可靠区分 Preview vs Trusted Reply-Suggestion。

### 5.2 消费面层

**不存在** Preview 次数统计、Preview 历史列表、Preview 成功率报表、Preview 审计查询、admin 端点、前端列表展示。唯一读取是 `_finalize_preview_execution`（agents.py:90）按 id 取行写回 lifecycle_status，不返回前端、不进 API response、不写报表。9100 侧不 import/query 该表（tests:262-267 断言约束 C2）。

### 5.3 当前污染判定

```
DOMAIN_SEMANTIC_CONTAMINATION (current) = NONE
```

插入 Trusted Reply-Suggestion execution 在当前代码中**不会**造成展示/统计/审计污染——因为不存在读取该表行用于展示的代码。

### 5.4 未来报表风险

唯一"Preview 专用"语义锚点：(a) 命名/docstring；(b) `ai_preview_execution:` 幂等键前缀（reply_decision_service.py:3810，写入 M07 ComputeTransaction.idempotency_key）。若将来出现按 `ai_preview_execution:` 前缀分组的计费报表，Trusted Proxy 与 Preview 计费在 M07 层面不可区分。此为**未来报表混淆风险**，当前无消费面，登记为 NON_BLOCKING NAMING DEBT（§28/§33）。

---

## 6. Preview vs Trusted Proxy

独立确认两者在当前系统中的真实边界（设计 §5 表）：

| 维度 | Trusted Proxy | Preview |
|---|---|---|
| 输入数据 | 真实客户会话（conversation_id 真实键，读 DB conversation_history/customer_memory/lead/contact_state）| 草稿（conversation_id="agent-preview" 硬编码 agents.py:317）|
| 使用者 | 商户工作台（真实会话建议）| 草稿智能体调试 |
| 9100 入口 | suggest_reply（同一入口）| suggest_reply（同一入口）|
| 计费模型 | 1:N(2) primary+retry_combined，不发送 | 1:N(2) primary+retry_combined，不发送 |
| auto_send | 强制 False（douyin_ai_cs_proxy.py:377）| 不发送（preview 语义）|

两者都是"9000 工作台人工触发 → suggest_reply → 9100 LLM → primary + 可能 retry_combined → 不发送"的 1:N(2) 计费模型。差异在输入数据层（草稿 vs 真实会话），**不影响计费幂等语义**。

Trusted Reply-Suggestion 是"真实客户会话上的人工客服建议回复"，非"Preview 的一个入口"。但其在**计费 domain**与 Preview 同构（同一 9100 入口/同一 _build_llm_reply/同一 _report_llm_usage/同 stage 集合/都不发送），故可共享 AiPreviewExecution 作为**计费 identity 容器**。

---

## 7. Source/Type Requirement

§6 问题：AiPreviewExecution 是否需要 source/type 字段区分 Preview vs Trusted Reply-Suggestion？

独立裁定：**A — 无需区分**。理由：

1. AiPreviewExecution 作为**计费 identity 容器**实际就是通用 reply-suggestion execution（merchant_id + agent_id + lifecycle_status 足够承载两者计费生命周期）。
2. 无任何消费面需要区分两者（§5.2 无统计/报表/审计读取该表行）。
3. agent_id 对两者都适用（draft-agent 和真实 agent 都是 AiAgent）。
4. billing identity 的职责是"这一笔只扣一次"的业务事件唯一标识，非场景分类。M07 ComputeTransaction 是唯一 billing truth。

若未来需按场景计费报表，加可选 `source` 字段属 OUT_OF_P1（设计 §10.2 已登记）。不为未发生的需求加字段（YAGNI）。

```
SOURCE_TYPE_FIELD = NOT_REQUIRED_FOR_F1
```

非 B（无需区分而 schema 做不到 → REJECTED）。Candidate A 不因缺 source/type 字段被否决。

---

## 8. Billing vs Domain Compatibility

显式裁定两件事：

```
Billing semantics compatibility = TRUE
  （同为 9000 工作台人工触发 LLM 建议生成，1:N(2)，不发送，同 suggest_reply 入口）

Domain model compatibility (billing identity container) = TRUE
  （AiPreviewExecution 作为计费 identity 容器通用：merchant_id/agent_id/lifecycle_status
   无 source/type 字段限定；无消费面将其锁定为 Preview 专用）
```

二者均成立 → Candidate A APPROVABLE。

明确：只有 billing 同构而 domain 不同构时，应选 Candidate B（typed execution model）。本案例 domain model（计费容器层）亦同构，故 Candidate A 成立，非错误复用。命名"Preview"承载两类场景是 NON_BLOCKING NAMING DEBT（§33），非 domain mismatch——名字不反映真实专属语义，模型本身是通用的计费 identity 容器。

---

## 9. Candidate A-E

### Candidate A — 复用 AiPreviewExecution

| 维度 | 裁定 |
|---|---|
| 语义正确 | ✅ 计费业务事件同构（§6/§8）|
| retry 稳定 | ✅ same execution + same stage → REPLAY（9100 同 request 复用）|
| 新生成独立 | ✅ 每次 9000 调用新建 execution = NEW event |
| migration | ✅ 无（复用 0034 表）|
| API | ✅ 无 breaking（identity 服务端创建）|
| 9100 | ✅ 零改（schemas.py:184 已有字段，reply_decision_service.py:3807 已有分支）|
| 复杂度 | ✅ 最小（handler ~5-10 行 + finalize + fail-closed guard）|

裁定：**APPROVED**（Preferred）。

### Candidate B — 新建 Dedicated Execution

裁定：**REJECTED**（YAGNI）。独立验证：Candidate A 无领域污染风险（§5.3 当前 NONE），故"多一张表"不因语义正确性而必要。migration complexity vs semantic correctness 比较：领域正确性已由 Candidate A 满足，无需新表。Candidate B 的独立语义清晰优势不抵消新表+migration+9100 新分支的成本。

### Candidate C — Message/Conversation Identity

裁定：**REJECTED**。独立确认：同一客户消息下用户主动点击两次生成（Case B）应允许两次合法计费 → message_id alone 不足以区分 → identity 不充分。设计拒绝正确。

### Candidate D — Caller Token + Durable Execution

裁定：**OUT_OF_P1**（future hardening）。

§11 关键问题：当前 Trusted Reply-Suggestion API 是否存在可能自动重试 POST 的客户端？独立检查：
- frontend HTTP wrapper：`getTrustedReplySuggestion`（douyinAiCsClient.ts:766）用 `apiClient.post`，未发现 retry interceptor 配置。
- in-repo caller = 0（无组件实际调用）。
- 无 desktop client / SDK / reverse proxy 自动 retry 证据。
- 未知外部 caller 的 retry 行为属未证实假设。

Candidate D 解决 HTTP response-lost retry，但：(a) 需 caller 提供 token（breaking，未知外部 caller）；(b) 超出 F-1 scope（审批 §19：不扩大为 full request recovery）；(c) F-1 bar = become identity-bearing，Candidate A 已满足。裁定 OUT_OF_P1 与已冻结治理一致（§10 详述）。

### Candidate E — 9100 Fail-Closed Hardening

裁定：**OPTIONAL HARDENING**（defense-in-depth）。不消除根因（proxy 仍不传 identity 时 9100 fail-closed 只是额外防线），且可能影响 legacy/dev 路径（_report_llm_usage :3811 全 None 分支是 legacy 兼容）。非 F-1 REQUIRED。Candidate A 已让 Trusted Proxy become identity-bearing。

---

## 10. HTTP Retry Contract

### 10.1 Candidate A 承诺范围

```
same durable execution + same stage replay → REPLAY（P1 保护）
  （9100 _build_llm_reply 内 primary:1160 / retry_combined:1236 传同一 request 对象
   → 同一 preview_execution_id → 同 key → M07 IDEMPOTENT_REPLAY）

full HTTP request response-lost → 新 execution → 新 charge（不承诺，OUT_OF_P1）
```

### 10.2 是否满足 F-1 closure bar

独立裁定：**满足**。F-1 closure bar = "ACTIVE consumer become identity-bearing"（消除 None），非"end-to-end business idempotency under HTTP retry"。区分两个命题：

- **F-1 None Closure**：ACTIVE route 不再发送 None key。Candidate A 满足。
- **End-to-End Business Idempotency**：same user action under HTTP retry → same execution → one charge。Candidate A 不承诺。

本审批依据正式治理文档（非临时选择容易通过的解释）裁定哪个命题属 P1（§11）。

---

## 11. COMPUTE-IDEMPOTENCY-001 Original Boundary

独立读取原始合同（APPROVED `P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md`）：

- `:29` "Business Event ID 必须在计费副作用发生之前已经稳定存在。"
- `:30` "retry / process restart / duplicate delivery 必须复用同一个 ID。"
- `:73` "每个 consumer 传入一个 business_event_id，代表'这一笔只允许扣一次'的业务事件唯一标识。"
- `:197-205, :248-251` replay 定义为"同一 idempotency_key 的重复调用"，含"commit 成功 + response 丢失 + consumer retry"场景。

所有 11 consumer 实际 identity 合同把"same event replay"钉死在"same durable execution + same stage"层：
- `P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md:111` "★ same execution replay → P1 保护；full request retry → 未保证 → P1 不解决。"
- `P1_PREVIEW_EXECUTION_IDENTITY_DESIGN.md:213-217` Preview 不变式同此。
- `P1_PG_0034_PREVIEW_CONSUMER_VERIFICATION.md:135-138` 正式幂等事件 = preview_execution_id + llm_call_stage。

```
COMPUTE-IDEMPOTENCY-001 P1 boundary:
  = identity 在计费副作用前持久化（durable commit before charge）
  + same durable execution + same stage replay → REPLAY（P1 保护）
  + full HTTP request response-lost → OUT_OF_P1（统一冻结）
```

**idempotency guarantee begins after durable execution establishment**：原始合同用中文表述为"identity 必须在计费副作用前已稳定存在"（建立条件）。设计文档 §7.1 的英文重述是该原则的推论，与原始合同一致。

Candidate A 满足 P1 原始合同：identity（execution.id）在 LLM 计费前 durable commit（§13），same execution + same stage replay 复用同一 key，HTTP response-lost 属 OUT_OF_P1。

---

## 12. PREVIEW_REQUEST_RECOVERY_GAP Comparison

§14 关键边界判断：设计引用 `PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1` 作为 HTTP response-lost 不处理的依据。审批必须检查这两个问题是否真的同类。

PREVIEW_REQUEST_RECOVERY_GAP 定义（`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md:659`，`CROSS_MODULE_RISK_REGISTER.md:46-55`）：

> "full 9000→9100 request response-lost（9100 已完成 LLM + M07 已 commit，但 9000 未收到 HTTP 响应 → 重发 preview → 新 execution → 新 charge；无 durable client request identity 证明 E1==E2）= OPEN / RELIABILITY / OUT_OF_P1"

分类针对 **B 类**（same billable business action HTTP replay idempotency），非 A 类（crash/orchestration recovery；A 类单独登记为 RAG_INGEST_RUN_RECOVERY_GAP，文档明确 `RUN_RECOVERY ≠ REQUEST_RECOVERY` 不合并）。

Trusted Proxy 的 HTTP response-lost 场景：full 9000→9100 request response-lost（9100 已完成 LLM + M07 已 commit，9000 未收到响应 → 重发 → 新 execution → 新 charge）。**与 PREVIEW_REQUEST_RECOVERY_GAP 同类（B 类），同口径**。

裁定：Candidate A 批准后，Trusted Proxy 在计费 domain 正式复用 AiPreviewExecution + `ai_preview_execution:` namespace，故其 HTTP response-lost gap **被 PREVIEW_REQUEST_RECOVERY_GAP 准确覆盖**——两者都是"9000 工作台人工触发 suggest_reply → 9100 response-lost → 重发 → 新 execution → 新 charge"。

但需显式登记覆盖范围扩展（C4，§29）：PREVIEW_REQUEST_RECOVERY_GAP 现覆盖两类入口（draft-agent preview + trusted reply-suggestion），不让风险消失在文字里。不新建独立 `TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP`，因 Candidate A 已让两者计费同域；但 PREVIEW_REQUEST_RECOVERY_GAP 的登记须注明扩展覆盖。

---

## 13. Durable Timing

§18 独立确认可复用 `_create_preview_execution`（agents.py:61-76）。真实顺序（agents.py:308-312 先例）：

```
auth / merchant validation (douyin_ai_cs_proxy.py:234-243)
  → agent binding validation (:245-260)
  → agent active check (:262-272)
  → ★ create AiPreviewExecution + db.commit() + db.refresh()（durable，before 9100 call）
  → payload["preview_execution_id"] = execution.id
  → suggest_reply → 9100 LLM（计费源）
  → usage report（_report_llm_usage 读 preview_execution_id 构造 key）
  → finalize lifecycle（completed/failed）
```

`_create_preview_execution`（agents.py:73-75）`db.add` → `db.commit` → `db.refresh`。**非 flush only / 非 LLM first / 非 commit later**。execution.id 在 LLM 前已 durable commit，满足"identity 先于计费副作用持久化"硬规则（`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md:29`）。

---

## 14. Merchant Boundary

§19 确认：`execution.merchant_id` = `context.merchant_id`（RequestContext，服务端可信）。`_create_preview_execution(db, merchant_id, agent_id)`（agents.py:61）merchant_id 由 9000 注入，非 proxy request 指定。proxy request body 不含 merchant_id（前端 TrustedReplySuggestionRequest 无 merchant_id 字段，由 9000 从 RequestContext 注入 payload :320）。

```
MERCHANT_BOUNDARY = SERVER_SIDE_TRUSTED
```

client 无法指定其他 merchant_id 创建跨商户 execution。execution lookup 不由 client 提供 execution_id（无 follow-up API）。9100 `_report_llm_usage` 用 `request.merchant_id`（payload :320，9000 注入）。

---

## 15. Finalize Lifecycle

§20 独立检查 `_finalize_preview_execution`（agents.py:79-95）：

- `completed`（9100 正常返回有效 response）：agents.py:343 先例。
- `failed`（9100 异常 / LLM 异常）：agents.py:322 先例。
- `exception`：`_finalize_preview_execution` 自身 `except Exception: db.rollback()`（agents.py:94-95），finalize 失败绝不阻断响应返回（C3）。
- `upstream timeout`：归 failed（XgDouyinAiCsClientError 捕获 :370）。

failed execution 保留：`_finalize_preview_execution` 只更新 `lifecycle_status`，**不删行**（models.py:1349 "持久不可清空，finalize 只更新 lifecycle 不删行"）。failed execution 保留 stable identity，供审计/billing reconciliation/诊断。

与 Trusted Proxy 语义兼容：proxy 的 9100 异常（:370-374 `XgDouyinAiCsClientError`）→ finalize failed；9100 正常 → finalize completed。lifecycle 三态 running/completed/failed 足够，不引入复杂状态机（billing truth 只归 M07 ComputeTransaction）。

---

## 16. Fail-Closed

§21 具体化。设计 §17 声称 fail-closed，审批要求明确：

```
identity creation failure（_create_preview_execution 抛异常 / commit 失败）
  → 不调 suggest_reply（不调 LLM）
  → 无 billable LLM
  → 无 compute charge
  → 返回 502/500
```

**关键**：若 `create execution failed → 仍调 suggest_reply without preview_execution_id`，则 F-1 仍存在。设计 §17.1 明确"execution 创建失败 → 不调 suggest_reply → 返回 502/500"，正确。但须 F1-PG-5 runtime gate 验证（§24/§29 C2），不能只靠静态断言。

fail-closed 必须在 handler 实现为：`_create_preview_execution` 调用不在 try 块内吞异常（或 try 块 except 直接 return 502，不 fall through 到 suggest_reply）。具体 HTTP 语义由实施窗口提出（建议 502 `PREVIEW_EXECUTION_CREATE_FAILED` 或 500）。

---

## 17. 9100 Zero-Change Verification

§22 独立验证：

- `ReplySuggestionRequest.preview_execution_id: int | None = None`（schemas.py:184）✅ 已存在。
- `_report_llm_usage`（reply_decision_service.py:3786-3811）已有 Preview 分支：`:3807 elif preview_execution_id is not None: → idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"` ✅。
- primary（:1160）/ retry_combined（:1236）传同一 request 对象 → 同一 preview_execution_id → 同 execution，`llm_call_stage` 区分 → 不同 key ✅。
- partial/mixed guard（:3792-3806）：Trusted Proxy 只设 preview_execution_id，不设 run_id/attempt_count → 不触发 mixed guard ✅。

```
9100 CHANGE REQUIRED = NONE
```

若需任何 9100 改动，设计 scope 必须修正。独立确认：无需 9100 改动。

---

## 18. Mixed Identity Safety

§23 独立确认：Trusted Proxy payload（:316-362）新增 `preview_execution_id` 后，是否可能同时存在 run_id/attempt_count？

- Trusted Proxy 不设 `run_id`（payload :316-362 无此字段）。
- Trusted Proxy 不设 `attempt_count`。
- `xg_douyin_ai_cs_client.suggest_reply`（:52/:60-64）整 dict 透传，不注入 run_id/attempt_count（只注入 merchant_id :62 + conversation_short_id :63）。

```
EXACTLY ONE TOP-LEVEL EXECUTION IDENTITY SOURCE = preview_execution_id
MIXED GUARD TRIGGER = NO
```

9100 `_report_llm_usage`：run_id=None + attempt_count=None + preview_execution_id 非空 → 走 :3807 Preview 分支，不触发 :3792 mixed guard。

---

## 19. API Compatibility

§24 独立确认：

- **9000 proxy request model** `ReplySuggestionProxyRequest`（douyin_ai_cs_proxy.py:164-170）：无需新增 required field。identity 由 9000 服务端创建。
- **9100 ReplySuggestionRequest**（schemas.py:154-184）：已有 `preview_execution_id`，无需改 schema。
- **前端 TrustedReplySuggestionRequest**（douyinAiCsClient.ts:260-266）：无需改。identity 不由前端提供。
- **response model**：proxy handler 返回 `dict[str, Any]`（无 response_model，:236），不新增 execution_id 到 response（设计 §14.4）。

```
API CONTRACT BREAKING CHANGE = NONE
```

外部 request model 不新增 required field；external response model 不变；caller 无需传 execution id；current unknown external caller 仍可调用。identity 对 caller 透明（§20）。

---

## 20. Unknown External Caller Compatibility

§25/§26 独立验证 Candidate A 优势：server-side transparent identity creation。

- in-repo caller = 0（前一审批窗口确认：`getTrustedReplySuggestion(` 调用点 0，`generateReply` 不存在）。
- 但 route ACTIVE（main.py:139 挂载 + 鉴权 + 文档正式用途）。
- 未知外部 caller 可能存在（外部客户端/桌面端/历史版本/直接 HTTP）。

Candidate A：identity 由 9000 handler 内部创建，对 caller 透明。任何 caller（前端/外部/历史版本）调用 `POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion` 都自动获得 identity，无需提供必填字段。**不要求未知旧 caller 突然提供必填字段**，无版本迁移方案需求。

```
UNKNOWN_CALLER_COMPATIBILITY = TRANSPARENT
```

---

## 21. Intentional Regeneration

§26 独立确认 Candidate A 支持：

```
POST intentional generation #1 → execution A（9000 新建 + commit）→ charge A:primary
POST intentional generation #2 → execution B（≠ A，9000 新建）→ charge B:primary（独立合法）
```

当前 API 无显式"regenerate"字段，但仍成立：separate intentional POST = separate handler 调用 = separate `_create_preview_execution` = separate execution.id = NEW business event。与 Preview `_create_preview_execution` 每次新建同模式（agents.py:311）。

结合 HTTP retry 边界（§10/§12）：separate intentional POST 的新建是正确行为；HTTP response-lost 的重发新建属 OUT_OF_P1。

---

## 22. Stage Contract

§27 独立确认 Trusted Proxy 可达 stage 集合：

```
primary（:1160）— 总是触发（主 chat）
retry_combined（:1236）— 条件触发（6 个留资合规纠正器之一命中，:1184-1223）
```

max 2 charge per execution（1:N(2)）。与 Preview 完全同一 `_build_llm_reply`（:981），故 stage 集合相同。

Business Event Identity 语义：
- `ai_preview_execution:{execution_id}:primary`
- `ai_preview_execution:{execution_id}:retry_combined`

```
same execution + same stage → replay（same key → IDEMPOTENT_REPLAY）
same execution + different legitimate stage → independent（different key → 2 charges）
different execution → independent（NEW event）
```

retry_combined 不创建新顶层 execution（primary:1160 / retry_combined:1236 传同一 request 对象 → 同一 preview_execution_id）。

---

## 23. Shared Helper / Router Coupling

§37 核心代码结构点。独立确认：

- `_create_preview_execution`（agents.py:61）和 `_finalize_preview_execution`（agents.py:79）是 `app/routers/agents.py` 的 module-level **private**（`_` 前缀）helper。
- 设计 §26 拟由 `douyin_ai_cs_proxy.py` 直接复用 → 形成 router→router private import。

独立检查项目先例：
- `app/routers/douyin_live_check.py:21 from app.routers.integrations import _handle_douyin_webhook` — **项目已有 router→router private import 先例**。

裁定：**允许直接 import**（符合 `douyin_live_check` 先例，不强制抽取）。`_create_preview_execution` / `_finalize_preview_execution` 行为通用（merchant_id + agent_id → create；execution_id + lifecycle → finalize），不绑定 preview 专属逻辑。

```
C1 = OPTIONAL（非阻断）
  允许 douyin_ai_cs_proxy.py 直接 from app.routers.agents import _create_preview_execution, _finalize_preview_execution
  行为不变，符合项目先例，不强制抽到 shared service
  若实施窗口选择抽到 app/services/preview_execution_service.py 也可，行为不变，不算 scope 扩散
```

审批明确裁定，不留实施窗口自由发挥：直接 import 可接受。若未来出现第三个 caller 再评估抽取。

---

## 24. F1-PG-1~F1-PG-6

§28 独立审批实施覆盖要求。设计 §22 已列出 6 个 Gate，但部分描述精度不足，需 correction 强化：

| Gate | 设计描述 | 审批要求 | correction |
|---|---|---|---|
| F1-PG-1 First | execution A + primary → 1 txn | 真实 proxy path → exactly one ComputeTransaction | 满足 |
| F1-PG-2 Same Event Replay | same A + same primary → 1 txn, balance unchanged | **必须明确**：这是 9100 同 request 复用 identity 的 usage replay（same execution_id + same stage），**非** HTTP request replay。证据名称准确（C3）| 强化描述精度 |
| F1-PG-3 Intentional New | execution B ≠ A → 2nd legitimate txn | new HTTP request → new execution → independent charge | 满足 |
| F1-PG-4 Stage Separation | A primary + A retry_combined → 2 不同 key | 真实触发留资合规纠正路径 | 满足 |
| F1-PG-5 Fail-Closed | create 失败 → 不调 LLM → 无 charge | **runtime gate**：模拟/触发 durable execution creation failure，验证 9100 NOT CALLED / LLM NOT CALLED / compute NOT CALLED，**不能只靠静态测试**（C2）| 强化必须 |
| F1-PG-6 None Regression | active path → idempotency_key ≠ None | **runtime gate**：真实 proxy route 执行成功后，检查本轮所有 charge rows `idempotency_key IS NOT NULL` / `≠ ''` / 无 `:None:` / `::` / `:null:`（C3）| 强化必须 |

replay seam 合法性（参考 0034 `P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md:385`）：F1-PG-2 的 replay seam 是 9100 内部 same execution_id 重报 usage（对应 crash 后 usage report 重试 / 9100 同 request 复用），**非**重新调 proxy POST（会创建新 execution）。

---

## 25. Required / Optional / Out-of-P1

### REQUIRED FOR F-1

- Candidate A：proxy handler 加 `_create_preview_execution`（durable commit before suggest_reply）+ payload 透传 `preview_execution_id` + `_finalize_preview_execution`（completed/failed）。
- Fail-closed：execution 创建失败 → 不调 LLM（§16）。
- F1-PG-1~F1-PG-6 验证（§24，F1-PG-5/F1-PG-6 须 runtime gate）。
- 隔离 PG E2E（mock 仅限最终外部 LLM provider，不得 mock proxy handler / identity resolver / usage reporting / compute client / record_usage / PG ledger）。

### OPTIONAL HARDENING

- 9100 fail-closed hardening（Candidate E，§19.2）：detect active context without identity → fail closed。需独立评估兼容影响（可能 break legacy/dev `_report_llm_usage` :3811 全 None 分支），非 F-1 REQUIRED。
- AiPreviewExecution 加可选 `source` / `conversation_short_id` 字段（§5.4/§7）：未来按场景/会话计费报表。OUT_OF_P1。
- response 返回 execution_id（§14.4）：未来 retry/observability/follow-up。OUT_OF_P1。
- C1 shared helper 抽取（§23）：可选，直接 import 可接受。

### OUT_OF_P1

- HTTP response-lost replay（Candidate D）：被 PREVIEW_REQUEST_RECOVERY_GAP 覆盖（§12），OPEN / RELIABILITY / OUT_OF_P1。
- Core `record_usage(None)` globally forbidden（§19.3）：COMPATIBILITY CONTRACT，future hardening。
- F-2 dev_only `/api/compute/internal/usage` 丢 key：DORMANT，future governance。
- 9100 `xg_douyin_ai_cs` least privilege：future governance。

---

## 26. Global Re-Audit Contract

§40 独立确认。F-1 implementation 通过后**必须重跑**完整 Global Active None Audit，非仅查 F-1 route：

```
F-1 design approval → implementation → PG verification → implementation approval
  → Global Active None Audit RE-RUN
  → ACTIVE NONE = 0
  → ACTIVE EMPTY = 0
  → ACTIVE PARTIAL = 0
  → UNKNOWN ACTIVE = 0
  → F-2 继续 DORMANT
  → 方可进入 Final Concurrent Closure
```

不能仅凭 F-1 测试通过直接进入 Final Concurrent Closure。

---

## 27. Implementation File Scope

§36 独立审批确认：

### MODIFY（9000）

| 文件 | 改动 |
|---|---|
| `app/routers/douyin_ai_cs_proxy.py` | handler `create_reply_suggestion_proxy`：suggest_reply 前 `_create_preview_execution(db, context.merchant_id, request.agent_id)` + payload 设 `preview_execution_id`；9100 成功 → finalize "completed"；9100 异常 → finalize "failed"；execution 创建失败 → fail closed（不调 LLM，返回 502/500）。复用 agents.py 的 `_create_preview_execution` / `_finalize_preview_execution`（直接 import，§23）。|

### MODIFY（9100）

**无**（§17 零改验证完成）。

### CREATE

| 文件 | 内容 |
|---|---|
| tests（focused）| F1-PG-1~F1-PG-6 验证（§24）|
| implementation report | `P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_REPORT.md` |

### NO migration

复用 0034 `ai_preview_executions`（§28）。

### READ ONLY / DO NOT MODIFY

compute core（record_usage）/ 其他 11 consumers / staging/prod / 9100 unrelated paths / migration / DB-BL / F-2 dev_only route / RB-10。

```
SCOPE = SUFFICIENT
  核心改动集中 douyin_ai_cs_proxy.py handler（~5-10 行 + finalize + fail-closed guard）
  9100 零改，无 migration，无 schema 变更
  不需修改 models / schemas / frontend / shared helper（直接 import 符合先例）
```

scope 足够精确，不需在实施阶段扩散到 models/schemas/frontend/migration。

---

## 28. Risks / Future Gaps

### Corrections（实施前应用）

```
C1 = OPTIONAL — shared helper 抽取（§23）
  允许直接 from app.routers.agents import _create_preview_execution, _finalize_preview_execution
  符合 douyin_live_check 先例，不强制抽到 shared service
  若抽到 app/services/preview_execution_service.py 也可，行为不变，不算 scope 扩散

C2 = REQUIRED — F1-PG-5 fail-closed runtime gate（§24）
  模拟/触发 _create_preview_execution 失败，runtime 验证 9100 NOT CALLED / LLM NOT CALLED / compute NOT CALLED
  不能只靠静态测试

C3 = REQUIRED — F1-PG-2 / F1-PG-6 证据名称精度（§24）
  F1-PG-2 须明确为 "same execution + same stage 的 usage replay"（非 HTTP request replay）
  F1-PG-6 须为 runtime None regression gate（真实 proxy route 执行后检查 charge rows NOT NULL/NOT EMPTY）

C4 = REQUIRED — HTTP replay gap 显式登记（§12）
  PREVIEW_REQUEST_RECOVERY_GAP 现覆盖两类入口（draft-agent preview + trusted reply-suggestion）
  须在 PREVIEW_REQUEST_RECOVERY_GAP 登记处注明扩展覆盖
  不新建独立 TRUSTED_REPLY_SUGGESTION_REQUEST_RECOVERY_GAP（Candidate A 已让两者计费同域）
  不让风险消失在文字里

C5 = REQUIRED — 模型命名债登记（§5.4/§33）
  AiPreviewExecution 名字反映 Preview 专属，但 Candidate A 后承载两类场景（draft preview + trusted reply-suggestion）
  登记为 NON_BLOCKING NAMING DEBT，不扩大 P1 重命名
  名字不反映真实专属语义（模型本身是通用计费 identity 容器），故是命名债非 domain mismatch
```

### Risks

| 风险 | 影响 | 缓解 |
|---|---|---|
| execution 创建失败导致 502/503 | 工作台建议生成不可用 | fail-closed 是正确行为（不计费优先于可用性）；finalize failed 保留 identity |
| AiPreviewExecution 无会话绑定 | 无法按会话计费报表 | OUT_OF_P1（§7）；F-1 bar 是幂等非报表 |
| namespace 与 Preview 共享 | 无法按 execution 类型区分计费 | 当前无消费面需区分（§5.2）；C5 命名债登记；未来加 source 字段（OUT_OF_P1）|
| HTTP response-lost 双扣 | retry 产生新 execution → 新 charge | 与 Preview 同口径 OUT_OF_P1（§12）；C4 gap 登记 |

### Rollback

```
rollback = git revert proxy handler 改动
  无 schema 变更，无 data migration，无破坏性
  不触碰 canonical DB（验证在隔离 PG）
  不触碰 9100（零改）
  不触碰 migration（无新 migration）
```

---

## 29. Correction 汇总与裁定

### 为什么是 APPROVED_WITH_CORRECTIONS 而非 APPROVED

Candidate A 在领域语义（§3-§8）和 P1 retry 边界（§10-§12）两个硬门槛上均独立成立，核心方案正确。但存在 5 项 correction（C1-C5），其中 C2/C3/C4/C5 为 REQUIRED，须实施前应用或实施窗口遵守：

- C2（fail-closed runtime gate）：设计 §22 F1-PG-5 描述过简，须明确为 runtime gate 而非静态测试。
- C3（证据名称精度）：F1-PG-2 须区分 usage replay vs HTTP request replay；F1-PG-6 须 runtime。
- C4（HTTP replay gap 登记）：须显式登记 PREVIEW_REQUEST_RECOVERY_GAP 扩展覆盖，不让风险消失在文字里。
- C5（命名债登记）：须登记 NON_BLOCKING NAMING DEBT。

C1（shared helper）为 OPTIONAL，非阻断。

### 为什么不是 CHANGES_REQUIRED

- AiPreviewExecution 领域语义兼容（§5/§8）：作为计费 identity 容器通用，无当前污染，命名债非 domain mismatch。
- HTTP-level same-business-event replay 属 OUT_OF_P1（§11/§12）：被 7 个已冻结 gap + 原始合同 + 0034 验证范围共同确立，Candidate A 不承诺与此治理边界一致。
- 0034 schema 足够（§28）：6 列承载 merchant/agent/lifecycle/时间戳，proxy 使用不缺必要字段。
- proxy 可 fail closed（§16）：handler 结构允许 create 失败时不 fall through 到 suggest_reply。
- 无未批准 migration / API breaking change（§19/§27）。

---

## 30. Implementation Authorization

```
VERDICT: APPROVED_WITH_CORRECTIONS
  Candidate A 在领域语义和 P1 retry 边界上均独立成立
  实施前须应用 C2/C3/C4/C5（REQUIRED），C1 可选

正式冻结业务身份：
  Trusted Reply-Suggestion Business Event
    = one server-created durable AiPreviewExecution

  Business Event Identity:
    ai_preview_execution:{preview_execution_id}:{llm_call_stage}

  语义:
    same durable execution + same stage → same billable event（REPLAY）
    new intentional generation → new execution → new billable event
    retry_combined → same execution → different legitimate stage（独立计费）

  HTTP response-lost replay:
    OUT_OF_P1（被 PREVIEW_REQUEST_RECOVERY_GAP 覆盖，C4 显式登记扩展覆盖）
```

授权下一阶段：

```
P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-IMPLEMENTATION
```

实施窗口须：
1. 修改 `app/routers/douyin_ai_cs_proxy.py` handler（Candidate A + fail-closed）。
2. 新增 focused tests（F1-PG-1~F1-PG-6，C2/C3 runtime gate）。
3. 隔离 PG E2E 验证（mock 仅限最终外部 LLM provider）。
4. C4 登记 PREVIEW_REQUEST_RECOVERY_GAP 扩展覆盖。
5. C5 登记 NON_BLOCKING NAMING DEBT。
6. 实施审批。
7. 重跑 Global Active None Audit（ACTIVE None = 0）。
8. 方可进入 Final Concurrent Closure。

本设计审批窗口：

```
DO NOT IMPLEMENT
DO NOT COMMIT
DO NOT MODIFY proxy handler
DO NOT MODIFY 9100
DO NOT CREATE migration
DO NOT MODIFY canonical DB
DO NOT RE-RUN Global Audit
DO NOT START Final Concurrent Closure
DO NOT PROCESS F-2
DO NOT MODIFY compute core
DO NOT RB-10
```

---

## 附录：审批纪律确认

- NO BUSINESS CODE CHANGE：未改任何业务代码。
- NO MIGRATION：未改迁移。
- READ ONLY：未写 canonical DB，未执行 runtime probe。
- 未 commit、未 push、未宣布 P1 Closed、未启动 RB-10、未启动 Final Concurrent Closure。
- 本窗口唯一新增产物：`docs/architecture/remediation/P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN_APPROVAL.md`。
- 设计文档 `P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_DESIGN.md` 未被修改（核心结论正确，corrections 在本审批报告登记）。
```
