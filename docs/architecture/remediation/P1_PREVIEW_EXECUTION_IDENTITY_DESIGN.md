# P1 M01 Preview Execution Identity 技术设计（Stage 5G-1）

> 状态：TECHNICAL_DESIGN_IN_PROGRESS（只设计，不实施）
> 前置：Register #7 M01 Preview 当前 = CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #7；边界涉及 #3 M01 Auto Reply（共用 `_report_llm_usage`）
> 范围：设计 Preview 路径计费点的稳定幂等身份，回答"什么构成一次 Preview LLM 调用的独立计费身份"
> 下一步：审查通过后决定方案 A/B，再授权实施（不在本 Stage 实施）

## 硬需求（开篇）

**P1 需要在 Preview 路径计费点构造稳定幂等身份。**

- 当前 `run_id=None` → `idempotency_key=None`（兼容路径，无 M07 保护）。
- Preview 是 **CHARGEABLE**（当前行为：真实 LLM 调用 + 真实计费）。
- **POLICY_PENDING 不阻塞 identity 设计**：无论 Preview 未来免费/收费的产品决策如何，identity 设计现在就应完成（若将来 policy 决定免费 → 移除 charge-producing call，identity 设计仍有效）。
- billing truth 仍只归 M07 committed ComputeTransaction；Execution 无 is_billed。

## 当前事实（已验证，file:line）

### 9000 Preview 链路（`app/routers/agents.py::preview_agent` L194）
```
preview_agent(payload, db, context) L194
  context.merchant_id 来自 RequestContext L198/239（可信商户上下文）
  request_payload = {tenant_id, merchant_id, agent_id, agent_config, ...} L235-269（内存构造）
  result = get_xg_douyin_ai_cs_client().suggest_reply(
      context, conversation_id="agent-preview", request=request_payload) L272-276
      # ★ 9000 调用 9100 前不创建任何持久状态（纯内存 request_payload + HTTP）
```
- merchant_id 来自 `context.merchant_id`（L239），9000 是可信上下文 owner
- `conversation_id="agent-preview"` 共用（L274），不是持久化实体 ID
- 9000 调用 9100 前无任何 DB INSERT（内存）

### 9100 计费链路（`reply_decision_service.py`）
```
suggest_reply → ... → build_reply_suggestion
  client.chat(messages) L1159（primary LLM 调用）
  _report_llm_usage(request, agent, conversation_id, messages, result, llm_call_stage="primary") L1160-1167  # ★ 计费点 1
  # 条件触发：解析决策后若命中纠正条件
  client.chat(retry_messages) L1235（retry_combined LLM 调用）
  _report_llm_usage(request, ..., llm_call_stage="retry_combined") L1236-1242  # ★ 计费点 2
```

### _report_llm_usage（L3763）已有 getattr 透传模式
```python
run_id = getattr(request, "run_id", None)         # L3786
attempt_count = getattr(request, "attempt_count", None)  # L3787
if run_id is not None and attempt_count is not None:
    idempotency_key = f"ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}"  # L3791 Auto Reply
elif run_id is not None or attempt_count is not None:
    # partial → warning，不构造 key  # L3792-3797
# run_id=None AND attempt_count=None → Preview 兼容路径，不传 key  # L3798
```

关键事实：

| 事实 | 证据 | 设计含义 |
|---|---|---|
| Preview 无持久状态 | 9000 纯内存 request_payload（L235）+ HTTP | identity 需新增持久实体 |
| 1 请求最多 2 次 charge | primary（L1160）+ retry_combined（L1236） | cardinality = 1:N(2)，key 需含 llm_call_stage |
| 两计费点共享 request 对象 | 同一 `request` 传给两次 `_report_llm_usage` | execution_id 可在 request 上共享 |
| Auto Reply 用 run_id+attempt_count+stage | L3791 `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}` | Preview 须用独立 namespace，不污染 Auto Reply 合同 |
| Preview 当前 key=None | L3798 兼容路径 | 待迁移 |

---

## Q1. PreviewExecution 放在哪里？9000 or 9100？

### 方案 A — 9000 创建 PreviewExecution（auto_wechat 库）→ 透传 execution_id 到 9100

```
9000 preview_agent L194
  execution = AiPreviewExecution(merchant_id=context.merchant_id, ...)   # ★ 9000 创建
  db.add(execution); db.commit()                                          # durable before 9100 call
  request_payload["preview_execution_id"] = execution.id                   # 透传到 9100
  result = suggest_reply(conversation_id="agent-preview", request=request_payload) L272
    → 9100 _report_llm_usage 从 request.preview_execution_id 构造 key
```

**与已迁移路径一致**：
- Daily Report：9000 创建 DailyReportGeneration → 透传 generation_id 到 9100
- Return Visit：9000 创建 ReturnVisitRun → 透传 run_id 到 9100
- Training：9100 本地创建 KnowledgeTrainingExecution（9100 自有 DB）

模式：**请求归属方创建 Execution + 透传到计费方**。Preview 的请求归属方是 9000（merchant_id 来自 RequestContext）。

**收益**：
- 模式一致性强（与 Daily Report / Return Visit 同构）
- 9000 是可信上下文 owner（merchant_id 已校验）
- 9100 通过 `ReplySuggestionRequest` 加 `preview_execution_id` 字段透传（复用现有 getattr 模式）

### 方案 B — 9100 创建 PreviewExecution（xg_douyin_ai_cs 库）at reply-suggestion 入口

```
9100 reply-suggestion 入口
  execution = KnowledgePreviewExecution(merchant_id=request.merchant_id, ...)  # 9100 创建
  db.add(execution); db.commit()                                                 # durable before LLM
  ... → _report_llm_usage(execution_id=execution.id)
```

**问题**：
- 9100 拥有 LLM 调用 + 计费点，但**不拥有 Preview 业务请求**（merchant_id 从 9000 传入，非 9100 自有可信上下文）
- 与已迁移的 9100-local 模式（Training）不同：Training 是 9100 自有业务（ask 入口在 9100），Preview 请求归属 9000
- 跨进程 identity 创建在 9100 但请求上下文在 9000 → 职责错位

### 倾向：方案 A

理由：与 Daily Report / Return Visit 同模式（请求归属方 9000 创建 Execution + 透传到计费方 9100），模式一致性强。**但这是技术设计阶段的决策，本轮只钉死事实 + 比较方案，不冻结。**

---

## Q2. 哪个数据库拥有它？

| 方案 | 库 | 理由 |
|---|---|---|
| 方案 A | `auto_wechat`（9000 库） | 9000 创建，与 DailyReportGeneration（auto_wechat 库）同库 |
| 方案 B | `xg_douyin_ai_cs`（9100 库） | 9100 创建，与 KnowledgeTrainingExecution（xg_douyin_ai_cs 库）同库 |

**方案 A → auto_wechat 库**：PreviewExecution 在 9000 创建，归 auto_wechat 库。9100 只接收透传的 execution_id（非自有），不持有该表。

---

## Q3. PreviewExecution 在首次 LLM 前如何 durable commit？

方案 A 时序：
```
9000 preview_agent L194
  execution = AiPreviewExecution(merchant_id, agent_id, ...)        # ★ 创建
  db.add(execution); db.commit()                                     # ★ durable commit（before 9100 HTTP call）
  request_payload["preview_execution_id"] = execution.id
  result = suggest_reply(...) L272                                    # → 9100 LLM（计费源）
    → 9100 _report_llm_usage(request, ..., llm_call_stage="primary")   # ★ 计费点 1（identity 已透传）
    → 9100 _report_llm_usage(request, ..., llm_call_stage="retry_combined")  # ★ 计费点 2（同 identity）
```

**C 答**：execution 在 9000 `suggest_reply` HTTP 调用（L272，触发 9100 LLM）前已 `db.commit()` 持久化。9100 两次计费点均从 `request.preview_execution_id` 取同一 identity。

---

## Q4. primary / retry_combined 如何共享同一个 execution_id？

**1:N(2) cardinality，key 含 llm_call_stage**。

两次 `_report_llm_usage` 共享同一 `request` 对象（L1160 + L1236 都传 `request=request`），故 `request.preview_execution_id` 在两次调用中相同。

```
primary 计费：     ai_preview_execution:{execution_id}:primary
retry_combined：   ai_preview_execution:{execution_id}:retry_combined
```

- 同一 execution_id + 不同 llm_call_stage → 不同 key → 2 条独立合法 ComputeTransaction
- 同一 execution_id + 同一 stage replay → 同 key → M07 IDEMPOTENT_REPLAY

---

## Q5. 如何避免影响 Auto Reply 已有 run_id + attempt_count + stage 合同？

**用独立 namespace `ai_preview_execution`，不与 `ai_auto_reply_run` 混淆。**

`_report_llm_usage`（L3763）当前三分支：
- `run_id is not None and attempt_count is not None` → Auto Reply key（`ai_auto_reply_run:...`）
- partial → warning
- `run_id=None AND attempt_count=None` → Preview 兼容路径（None）

**实施方向（不冻结字段名）**：在第三分支（Preview 路径）新增 `preview_execution_id` 维度：
```python
preview_execution_id = getattr(request, "preview_execution_id", None)
if run_id is not None and attempt_count is not None:
    idempotency_key = f"ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}"  # Auto Reply 不变
elif preview_execution_id is not None:
    idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"  # ★ Preview 新分支
else:
    idempotency_key = None  # 旧兼容
```

**Q5 答**：Preview 用独立 namespace + 独立字段 `preview_execution_id`，不触碰 `run_id`/`attempt_count`。Auto Reply 合同（`ai_auto_reply_run:{run_id}:{attempt_count}:{stage}`）零变化。两路径在 `_report_llm_usage` 内按字段存在性分流，互不污染。

> **实施约束**：`preview_execution_id` 与 `run_id`/`attempt_count` 互斥（Auto Reply 请求不带 preview_execution_id，Preview 请求不带 run_id）。实施时若两者同时存在应记 warning（不构造畸形 key），与现有 partial identity 治理一致。

---

## Q6. Preview 失败/成功 lifecycle 是什么？

| 场景 | lifecycle | 计费 |
|---|---|---|
| primary 成功，无 retry | completed | 1 charge（primary） |
| primary 成功 + retry_combined 成功 | completed | 2 charges（primary + retry_combined） |
| primary 失败 | failed | 0 charge（不计费） |
| primary 成功 + retry_combined 失败 | completed（primary 已计费） | 1 charge（primary） |

**Q6 答**：lifecycle 三态 running/completed/failed。primary 失败 → failed（不计费）；primary 成功 → completed（无论 retry 是否触发，primary 已计费）。retry_combined 失败不影响 execution completed（primary 已成功计费，类比 M05 C1 红线：已成功的计费不因后续失败回滚）。**Execution status ≠ billing truth**，committed ComputeTransaction 是唯一账本。

---

## Q7. Preview 仍按当前 CHARGEABLE 行为设计；POLICY_PENDING 不阻塞

**Q7 答**：Preview 当前 CHARGEABLE（真实 LLM + 真实计费），identity 设计基于此当前行为。POLICY_PENDING（免费/收费产品决策）不阻塞 identity 设计——若将来 policy 决定 Preview 免费，则移除 charge-producing call（PG Closure Gate 三态的 B 路径：formally approved non-chargeable policy → charge-producing call removed），identity 设计仍有效（只是不再产生 charge）。

---

## 候选 identity（设计阶段，不登记最终 contract）

```
event_namespace = ai_preview_execution
business_event_id = {preview_execution_id}:{llm_call_stage}
idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"

llm_call_stage = primary / retry_combined
cardinality = 1 execution : up to 2 charge events
```

---

## 不变式（3 条）

1. **same execution + same stage billing replay → same key → REPLAY**：execution_id + stage 不变 → 同 key → M07 IDEMPOTENT_REPLAY
2. **same execution + different stage（primary vs retry_combined）→ different key → 2 charges**：llm_call_stage 维度区分，同一 preview 请求最多 2 次合法计费
3. **explicit new preview request → NEW execution → NEW key（合法新消费）**：每次 9000 preview_agent 调用新建 execution → 新 execution_id → 新合法消费

---

## 边界注明

### 不影响 Auto Reply 合同（#3 Charge Path）
- Preview 用独立 namespace `ai_preview_execution` + 独立字段 `preview_execution_id`，不触碰 `run_id`/`attempt_count`。
- Auto Reply key（`ai_auto_reply_run:{run_id}:{attempt_count}:{stage}`）零变化。
- 两路径在 `_report_llm_usage` 内按字段存在性分流，互不污染。

### billing truth 归 M07
- 本设计只构造 idempotency_key，不改 M07 core / `record_usage`。
- committed ComputeTransaction 是唯一 billing truth；Execution 不持有 billing 状态。

### 不宣称跨进程请求级幂等
- Preview 是 9000→9100 跨进程（HTTP），execution 在 9000 创建 + 透传到 9100。
- **PREVIEW_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1**：full 9000→9100 request response-lost（9100 已完成 LLM + M07 已 commit，但 9000 未收到 HTTP 响应 → 重发 preview → 新 execution → 新 charge；无 durable client request identity 证明 E1==E2）。与 DAILY_REPORT/TRAINING/RAG_INGEST_REQUEST_RECOVERY_GAP 同口径。
- ★ same Execution + same stage replay → P1 保护；full request retry after response-lost → 未保证复用 same Execution → P1 不解决。

---

## 硬约束（冻结）

1. **execution durable commit before first LLM call**（identity 先于计费副作用持久化）
2. **execution_id finalize 后不清空（永久保留）**（支持 replay）
3. **explicit new preview request → NEW execution**
4. **same execution + same stage → REUSE same key**；**same execution + different stage → different key**
5. **billing truth = committed ComputeTransaction**；Execution 无 is_billed
6. **不引入 attempt_count**（YAGNI，当前无跨请求 retry，1:N(2) 用 stage 区分）
7. **用独立 namespace `ai_preview_execution`**，不污染 Auto Reply `ai_auto_reply_run` 合同
8. **POLICY_PENDING 不阻塞 identity 设计**（保持 CHARGEABLE 当前行为）

---

## 待审批决策点

1. ~~方案 A vs 方案 B~~ → **方案 A 已冻结 APPROVED**（Stage 5G-2 已实施；9000 创建 + 透传，与 Daily Report / Return Visit 同模式）
2. ~~库归属~~ → **auto_wechat 库**（方案 A，AiPreviewExecution 在 9000 创建）
3. ~~`preview_execution_id` 字段透传方式~~ → **ReplySuggestionRequest 加 `preview_execution_id: int | None = None` 字段 + getattr 透传**（已实施）
4. ~~candidate key `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`~~ → **冻结为最终 contract**（Stage 5G-2 已实施）
5. ~~审查通过后授权实施~~ → **Stage 5G-2 已实施**（migration 0034 + model + preview_agent 改造 + ReplySuggestionRequest 加字段 + _report_llm_usage 三分支 + 7 Gate PASS）

## Stage 5G-2 实施落记

- **方案 A 已实施**：migration `0034_preview_executions.py` + ORM model `AiPreviewExecution`（auto_wechat 库）
- **execution 在 9100 HTTP call 前 durable commit**（PV-0）：`_create_preview_execution` + commit + 透传 `request_payload["preview_execution_id"]`
- **C1 lifecycle 红线落地**：lifecycle_status = 整次 Preview 请求结果（非 stage 状态）；9100 正常返回→completed；整次 9100 失败→failed
- **C2 DB ownership**：9100 不回连 auto_wechat DB（`_report_llm_usage` 只读 `request.preview_execution_id` 构造 key，不查/写 AiPreviewExecution 表）
- **C4 Auto Reply contract 不变**：独立 namespace `ai_preview_execution` + 独立字段；三分支（Auto Reply / Preview / legacy）；mixed identity（run_id+preview_execution_id）→ warning 不构造畸形 key
- **PREVIEW_REQUEST_RECOVERY_GAP 登记**：full 9000→9100 request response-lost → 重发 preview → 新 execution → 新 charge（OUT_OF_P1，与其他 REQUEST_RECOVERY_GAP 同口径）。★ same Execution + same stage replay→P1 保护 / full request retry→未保证→P1 不解决。
- **7 Gate PASS**：PV-0~PV-6（`tests/test_preview_compute_idempotency_migration.py`），含 PV-5 request lifecycle boundary + PV-6 mixed identity isolation
- **None count**：Preview 正式链 idempotency_key≠None = 0
- **0034 PG = PENDING_PG_VERIFICATION / BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（未验证不得 deploy）
- **COMPUTE-IDEMPOTENCY-001 仍 OPEN**（1/11 剩余：RAG Query #10a）
