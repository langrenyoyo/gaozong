# P1 Training Ask Execution Identity 生命周期技术设计（Stage 5D-1）

> 状态：TECHNICAL_DESIGN_IN_PROGRESS（只设计，不实施）
> 前置：Register #9 Training Knowledge 当前 = CANDIDATE_EXECUTION_IDENTITY_MODEL_VERIFIED
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #9；边界涉及 #10a RAG Query Embedding
> 范围：设计 Training Ask Execution Identity 的生命周期，回答"什么动作创造一个新的、应单独计费的 Training ask execution"
> 下一步：审查通过后决定方案 A/B，再授权实施（不在本 Stage 实施）

## 硬需求（开篇声明）

**P1 需要一个在收费前稳定存在的 Training Ask Execution Identity。**

- 当前 `training_id` 在 charge **之后**才生成（`ask` L120），不可作 billing identity。
- 本设计不预设具体方案，以硬需求为起点比较方案 A/B。
- identity 必须在 RAG search / LLM 调用 / `_report_usage` 之前已生成并 commit。
- billing truth 仍只归 M07 committed ComputeTransaction；execution 不得成为第二账本。

---

## 当前事实（已验证，file:line）

追踪 `apps/xg_douyin_ai_cs/services/knowledge_training_service.py::ask`（L75-181）完整顺序：

```
ask(payload) L75
  training_id = ""                                   # L78（初始空）
  RAG search(source_chunks)                           # L105（可能触发 #10a Query Embedding charge）
  _build_answer(payload, source_chunks) L117          # 事务外
    → OpenAICompatibleClient().chat(messages) L522   # LLM 调用
    → _report_usage(...) L539                         # ★ 计费点（仅 chat 成功后）
  training_id = f"kt-{uuid4().hex[:12]}" L120         # ★ charge 之后才生成
  INSERT knowledge_training_sessions(... status="answered") L127-145  # ★ Session 行才创建
  conn.commit() L146
```

关键事实：

| 事实 | 证据 | 设计含义 |
|---|---|---|
| training_id 后置 | L120 在 L539（charge）之后 | training_id 不可作 billing identity |
| charge 只在 chat 成功路径 | `_report_usage` L539 在 `chat()` L522 成功后；LLM 异常 L523-536 提前 return fallback，不计费 | identity 必须在 L539 前已持久 |
| LLM 失败折叠为 fallback answered | L523-536 / L548-553 返回 `_fallback_answer`；Session 仍以 status="answered" INSERT | 当前无显式失败生命周期（LLM_FAILURE_COLLAPSED_TO_FALLBACK_ANSWERED_STATE） |
| 无 technical retry | `_build_answer` 调 `chat()` 一次，异常即 fallback | 1 explicit ask = 1 charge 候选 |
| 每次 ask 新 training_id | L120 `uuid4()` | explicit new ask = new execution |
| Session 表 answer NOT NULL | INSERT L127-145 始终提供 answer（fallback 或真实） | 方案 A 改 answer nullable 会破坏现有约束 |

charge 点 = `_report_usage`（L475 def / L539 call），`capability_key="knowledge"`、`llm_call_stage="primary"`、`remark="knowledge_training_ask"`，当前无 `idempotency_key`。

---

## A. 方案 A vs 方案 B 完整流程 + 优劣

### 方案 A — 提前创建现有 knowledge_training_sessions

```
generate training_id
→ INSERT knowledge_training_sessions status="running"（answer=null）
→ commit
→ RAG search / LLM
→ _report_usage using training_id
→ UPDATE session status="answered" / "failed"
```

用现有 `training_id` 既是 Session 主键又是 billing identity。提前 INSERT 一行 status="running"，answer=null，LLM 完成后 UPDATE 为 answered/failed。

**代价：**
- `answer NOT NULL → nullable`（破坏现有约束，0002 迁移定义）
- 新增 lifecycle statuses（`running` / `failed`）
- **LLM 失败留下显式 failed 记录**（当前不存在）——改变 Session 业务模型，用户查询列表会看到 failed 行
- `status="answered"` 现有语义被稀释（多出 running/failed 中间态）
- 查询/列表可见性变化（需过滤 running/failed）

### 方案 B — 新增独立持久 Ask Execution 实体（倾向方案）

```
create KnowledgeTrainingExecution（identity 层，lifecycle="running"）
→ commit
→ RAG search / LLM
→ _report_usage using execution.id
→ 现有 knowledge_training_sessions 保持不变（answer 产生后再 INSERT status="answered"）
→ update execution lifecycle="succeeded"/"failed"
```

新建独立持久实体 `KnowledgeTrainingExecution`（类比 DailyReportGeneration），作 billing identity 层；现有 `knowledge_training_sessions` 保持不变。

**identity 形态（方案 B）：**
```
event_namespace = knowledge_training_execution（稳定合同）
business_event_id = {execution_id}:ask
idempotency_key = f"knowledge_training_execution:{execution_id}:ask"
```

**收益：**
- `answer NOT NULL` 保持（Session 仍在 answer 产生后 INSERT）
- `status="answered"` 现有语义保持（Session 无中间态）
- **LLM 失败是否生成用户可见 Session 无需在 P1 改变**（Execution failed，Session 不创建）
- billing identity 在 LLM 前已持久存在
- 与 DailyReportGeneration 同构（Job=parent/Generation=billing/token=lease 三层分离模式可复用）

---

## B. 哪个方案最小化业务行为变化（Q2）

**答：方案 B。** 四维对比：

| 维度 | 方案 A | 方案 B |
|---|---|---|
| answer nullable | ❌ 需改 NOT NULL→nullable | ✅ 保持 NOT NULL |
| status="answered" 语义 | ❌ 引入 running/failed 中间态 | ✅ 保持（Session 仍只在 answer 产生后 INSERT） |
| LLM 失败可见性 | ❌ 留下显式 failed Session 行（用户列表可见） | ✅ Execution failed，Session 不创建，用户可见行为不变 |
| 查询/列表 | ❌ 需过滤 running/failed | ✅ 无变化 |

方案 A 把 billing identity 职责强加到现有 Session 业务模型上，引入 4 处行为变化；方案 B 用独立 identity 层叠加，Session 业务模型零变化。**倾向方案 B。**

---

## C. persistent identity 在 RAG/LLM/计费前如何 commit（Q3 时序图）

方案 B 时序（identity 生成→commit→_build_answer→_report_usage）：

```
ask(payload) L75
  # ★ 新增：identity 层
  execution = KnowledgeTrainingExecution(
      tenant_id, merchant_id, douyin_account_id, question=payload.question,
      lifecycle_status="running",
  )
  db.add(execution)
  db.commit()              # ★ execution.id 已持久化（charge 点之前）
  
  RAG search(source_chunks)                # L105（#10a Query Embedding；execution.id 可作父级上下文传下）
  _build_answer(payload, source_chunks)   # L117
    → chat(messages) L522                   # LLM 调用
    → _report_usage(execution_id=execution.id, ...) L539   # ★ 计费点（identity 已存在）
  
  training_id = f"kt-..." L120             # 业务 training_id 仍后置（不影响 billing）
  INSERT knowledge_training_sessions(... status="answered") L127  # Session 不变
  db.commit()
  
  update execution.lifecycle_status = "succeeded" / "failed"
```

**C 答：** execution 在 RAG search（L105）之前创建并 commit；charge 点（L539）时 identity 已持久。满足"identity 必须在计费副作用前已稳定存在"硬规则。

> **ordering 选择注记**：execution 创建在 RAG search 前（覆盖 #10a 父级上下文）还是 RAG search 后、LLM 前（仅覆盖 #9）——是实施期决策，不冻结。若希望 execution 同时作 #10a 父级上下文，须在 L105 前创建；但这不改变 #10a 自身仍需独立 per-query identity 的事实（见边界注明）。

---

## D. LLM fallback 时 execution 如何结束 / 原有 Session 行为是否保持（Q4）

**方案 A：** 引入显式 `failed` 生命周期。LLM 失败 → Session 行 UPDATE status="failed"（answer=null 或 fallback）。**原有"失败折叠为 answered"行为改变**——用户列表会出现 failed 行。

**方案 B（倾向）：** execution 可独立标记 `failed`，**Session 不创建**（或按现有逻辑仍可 INSERT fallback answered——由实施期决定，P1 不强制改变）。
- LLM 失败 → 不计费（`_report_usage` 不在异常路径）→ execution lifecycle="failed"（未计费）
- LLM 成功 + `_report_usage` 成功 → execution lifecycle="succeeded"（billed，账务真相以 M07 ComputeTransaction 为准）
- LLM 成功 + `_report_usage` 失败 → execution 仍 running/unbilled → retry 复用同一 execution identity

**D 答：** 方案 B 可保持原有 Session 行为不变（Session 仍只在 answer 产生后 INSERT status="answered"）；失败状态由 execution 层承载，不污染 Session 业务模型。

---

## E. explicit new ask 是否必然 new execution（Q5）

**答：是。** 当前每次 `ask` 新 `training_id`（L120 `uuid4()`），execution 应同语义——每次 explicit ask 创建新 execution。1 explicit ask = 1 new execution。

---

## F. 当前无 technical retry 前提下，是否保持 1 execution : 1 ask charge（Q6）

**答：是（YAGNI）。** 当前 `_build_answer` 调 `chat()` 一次，无自动 retry；`_report_usage` 一次。
- **不提前引入 `attempt_count`**：当前无 retry/recovery 机制，1 execution : 1 ask charge 成立。
- 未来若新增 LLM retry / process recovery，再判断 REUSE（同 execution）或 NEW（新 execution）——届时类比 DailyReportGeneration 的 NEW/REUSE 规则。
- 不为本 Stage 引入未需要的维度。

---

## G. billing truth 仍归 M07，execution 不得成为第二账本（Q7）

**答：确认。**
- execution 可有执行生命周期（running/succeeded/failed）用于执行编排。
- **但不得新增 `execution.is_billed` 成为账务真相。**
- **committed ComputeTransaction 仍是唯一 billing truth。**
- execution 上的 billing-related 状态只能是派生/缓存/可恢复辅助状态，用于恢复决策，不作为账务权威。
- 类比 DailyReportGeneration 实施约束 3。

---

## 边界注明

### RAG Query Embedding（#10a）不合并

- Training 在 `_build_answer` 前会 `search` RAG（L105），RAG Search 可能触发 #10a Query Embedding charge。
- 若采用方案 B 的 `TrainingAskExecution.id`，它**可**作为本次 Training ask 的父级上下文传下去（RAG query embedding 可携带 execution_id 作 parent scope）。
- **但不得宣称它解决了所有 RAG Query Embedding identity**：Query Embedding 有非 Training 搜索调用场景（如独立检索调试 / 其他 RAG 入口）。
- #9 Training 与 #10a Query Embedding 是两个独立 Charge Path，**不合并**。execution 作 #10a 父级上下文只是未来复用机会，记录于此，不在本设计实施。

### 跨进程请求级幂等不宣称

- 本设计解决 #9 Training 的 **billing identity 前置持久化**（财务幂等职责）。
- **不宣称**解决了 full 9000→9100 跨进程请求级响应丢失恢复（类比 DailyReport `DAILY_REPORT_REQUEST_RECOVERY_GAP`）。
- 若未来 Training 也引入跨进程请求级 response-lost 场景，登记为独立 Reliability Gap（OUT_OF_P1），不并入 #9 迁移状态。

---

## 硬约束（冻结）

1. **identity 必须在 charge 点（`_report_usage` L539）前已生成并 commit**
2. **identity finalize 后不清空（永久保留）**（类比 DailyReportGeneration，支持 response-lost replay）
3. **explicit new ask → new execution**（每次 ask 新 execution）
4. **technical retry / process recovery → REUSE 同一 execution identity**（未来若引入 retry；当前无 retry，1:1 成立）
5. **billing truth = committed ComputeTransaction**；execution 无 `is_billed`，不成为第二账本
6. **不引入 `attempt_count`**（YAGNI，当前无 retry）
7. **不合并 #9 与 #10a Charge Path**
8. **execution 作 #10a 父级上下文仅为未来复用机会，不实施**

---

## 待审批决策点

1. ~~方案 A vs 方案 B~~ → **方案 B 已冻结 APPROVED**（Stage 5D-2 已实施）
2. execution 创建 ordering（RAG search 前覆盖 #10a 父级 / RAG search 后仅覆盖 #9）→ **实施决策：RAG search 前创建**（C1，覆盖 #9；#10a 父级上下文仅记录不实施）
3. LLM 失败时 Session 是否仍 INSERT fallback answered → **实施决策：Session 行为不变**（P1 不改变现有行为）
4. ~~审查通过后授权实施~~ → **Stage 5D-2 已实施**（migration 0004 + model 原生 SQL + ask 改造 + _report_usage 传 execution_id + 6 Gate PASS）

## Stage 5D-2 实施落记

- **方案 B 已实施**：migration `0004_knowledge_training_executions.py` + SQLite `init_db` 兜底建表
- **execution_id 复用 request_id**（C2），在 RAG search 前 commit（C1）
- **lifecycle 四态**：running / COMPLETED / COMPLETED_FALLBACK（C3）/ FAILED（C3）
- **TRAINING_REQUEST_RECOVERY_GAP 登记（C5）**：full 9000→9100 request response-lost（E1 LLM 成功 + charge commit，但 Session INSERT / HTTP response 失败 → client 重调 ask → new E2 → new charge；无 durable client request identity 证明 E1==E2）。= OPEN / RELIABILITY / OUT_OF_P1，与 DAILY_REPORT_REQUEST_RECOVERY_GAP 同口径，不并入 #9 迁移状态。
- **6 Gate PASS**：TR-1~TR-6（`tests/test_training_compute_idempotency_migration.py`）
- **None count**：Training 正式链 idempotency_key≠None = 0
- **COMPUTE-IDEMPOTENCY-001 仍 OPEN**（4/11 剩余：Preview / M05 / RAG Query / RAG Ingest）
