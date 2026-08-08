# P1 Stage 4A — M01 Business Event Identity Verification

> 状态：VERIFICATION_COMPLETE
> 代码基线：c26ec227e70d ~ 7845e26
> 不改业务代码，只验真

---

## 最终结论：B（稳定但不唯一 — 1 Run : N charge events）

AiAutoReplyRun.id 是稳定的「1 Run : N charge events」分组键，**不能**直接作为单一 chargeable LLM business event 的唯一标识。要达到 1:1，需在 `_report_llm_usage` 传入基于 `(run_id, llm_call_stage)` 的 `idempotency_key`，并在 9100 侧接收 run_id 透传。

---

## Q1：一个 AiAutoReplyRun 最多调用几次真正收费的 LLM？

**结论：最多 2 次**（primary + retry_combined）

- 主 LLM 成功后调 `_report_llm_usage`（stage=`primary`）：`reply_decision_service.py:1159-1167`
- retry_combined 成功后再次调 `_report_llm_usage`（stage=`retry_combined`）：`reply_decision_service.py:1234-1243`
- 代码注释明确"每次成功调用独立计量"（line 1159），禁止第三次（line 1184）

## Q2：LLM retry 是同一个 charge event 还是新的合法消费？

**结论：新的合法消费**

- 9100 内 retry_combined 是独立的 `client.chat(retry_messages)` 调用（`reply_decision_service.py:1235`），是新的 LLM 供应商请求
- 按真实 token 计量并独立上报（line 1236-1243）
- 9100 内部无第三次 retry（line 1184 禁止，line 1272-1291 不合格后不再调 LLM）

## Q3：AiAutoReplyRun 是否在第一次收费动作前稳定持久化？

**结论：是，但关联是间接的**

- `_add_run`（`ai_auto_reply_dry_run_service.py:376`）在 LLM 调用 `suggest_reply`（line 384）**之前**，且内部 `db.commit()` + `db.refresh(run)`（line 764-765）→ Run.id 在 LLM 调用前已持久化到 DB ✓
- **但**：`_report_llm_usage` 在 9100 内执行，用的是 `conversation_id`（= `conversation_short_id`），**不传 run.id**（`reply_decision_service.py:3790`）。Run.id 与 charge event 的关联是间接的（同一 webhook event → 同一 run → 同一次 suggest_reply → 9100 内 N 次 report_usage）

## Q4：Retry / restart 是否复用同一个 Run？

**结论：所有路径都复用同一 Run.id**

- 9100 内 retry：同一个 `suggest_reply` HTTP 调用内 → 同一 Run
- 9000 outbox retry：`_handle_llm_failure` 将同一 run 置为 `retry_wait`（`ai_auto_reply_dry_run_service.py:944`），不创建新 Run；outbox 重新 claim 后按 `run_id` 加载原 run（line 80），`_add_run` 走 upsert 更新原行 → **复用原 Run.id**
- `recover_expired_leases`（`ai_auto_reply_outbox_service.py:271-351`）：把过期 `processing` 改回 `pending`，不改 run.id → **复用原 Run.id**
- `manual_retry_run`（`ai_auto_reply_outbox_service.py:478-538`）：把 `failed` 改为 `retry_wait`，复用原 run_id（line 500-509）→ **复用原 Run.id**

**但**：每次 outbox retry 会重新执行整个 `_run_with_session` → 再次调 `suggest_reply` → 9100 内最多再 2 次 `_report_llm_usage`。即一个 Run.id 在多次 outbox retry 下可累积 **2 × (retry次数)** 次收费上报。

## Q5：一个 Run 是否存在多个收费 operation？

**结论：2 个 operation（primary + retry_combined）**

`_report_llm_usage` 调用点（`reply_decision_service.py`）：
- line 1160：primary 主 LLM
- line 1236：retry_combined 纠正 LLM

其它 `report_usage` 调用点不属于 auto-reply Run 链路（embedding/RAG 在 `rag/repository.py:481`，return_visit/knowledge_training/daily_report 在各自服务）。

## 额外：Preview 路径

- `app/routers/agents.py:194-276` `preview_agent` 不创建 `AiAutoReplyRun`，直接调 `suggest_reply`，`conversation_id="agent-preview"`（常量字符串）
- 该路径仍进入 9100 `_build_llm_reply` → 同样调 `_report_llm_usage`
- 无 run.id 持久化，`conversation_id="agent-preview"` 所有预览共用，无法代表单次预览事件

## 额外：幂等性关键缺陷

- `_report_llm_usage`（`reply_decision_service.py:3783-3797`）调用 `report_usage` 时**未传 `idempotency_key`**
- outbox retry 重新执行同一 Run 时，9100 内 primary/retry_combined 会**再次**上报，且因无 idempotency_key，compute 侧无法按 Run 维度去重 → 同一 Run.id 会被计费多次

---

## 迁移方案（结论 B → 可迁移）

要达到 1:1 幂等，需要：
1. 9000 → 9100 透传 `run_id`（在 `suggest_reply` HTTP payload 中加 `run_id` 字段）
2. 9100 `_report_llm_usage` 传入 `idempotency_key=f"ai_auto_reply_run:{run_id}:{llm_call_stage}"`
3. Preview 路径需独立的持久化身份（或标注 PREVIEW_NOT_CHARGED 不走计费）

### event_namespace = `ai_auto_reply_run`（稳定合同）
### business_event_id = `{run_id}:{llm_call_stage}`（区分 primary / retry_combined）
### Cardinality: 1:N（一个 Run 最多 2 个合法收费 operation）

### 涉及改动范围
- `apps/xg_douyin_ai_cs/schemas.py`：`ReplySuggestionRequest` 加 `run_id: int | None = None`
- `app/services/ai_auto_reply_dry_run_service.py`：`suggest_reply` 调用时传 `run_id=run.id`
- `app/routers/agents.py`：Preview 路径传 `run_id=None`（标注 PREVIEW_NOT_CHARGED）
- `apps/xg_douyin_ai_cs/services/reply_decision_service.py`：`_report_llm_usage` 传入 `idempotency_key`
- `apps/xg_douyin_ai_cs/services/compute_usage_client.py`：`report_usage` 传 `idempotency_key`

---

## Stage 4A-R1 补充验真（outbox retry cardinality + invocation identity + scene billing）

### R1-Q1：Outbox retry 重新触发的 LLM 调用是合法新消费还是 replay？

**结论：合法新消费（独立 client.chat + 独立 token 计量）**

追踪完整流程：
1. Run 123 → `_run_with_session` → `suggest_reply`（9000→9100 HTTP）→ 9100 `_build_llm_reply` → `client.chat(primary_messages)` → 成功 → `_report_llm_usage(stage=primary)` (#1)
2. Run 123 LLM 失败或 9000 侧异常 → `_handle_llm_failure` → `status=retry_wait`（`dry_run_service.py:944`）
3. outbox 调度器重新 claim（`outbox_service.py:244` `attempt_count+1`）→ `_run_with_session_for_outbox`（`dry_run_service.py:66-89`）→ 重新加载原 run（line 80）→ 重新执行 `_run_with_session` → 再次 `suggest_reply` → 9100 再次 `_build_llm_reply` → 再次 `client.chat(primary_messages)` → 成功 → `_report_llm_usage(stage=primary)` (#2)

**#2 是合法新消费**：
- 独立的 `client.chat()` 调用（新的 HTTP 请求到 LLM 供应商）
- 独立的 token 计量（供应商返回新的 usage）
- 代码注释"每次成功调用独立计量"（`reply_decision_service.py:1159`）
- 不是同一 event 的 replay——是新的 LLM 供应商请求

**含义**：`run_id + stage` **不够**——同一 Run 同一 stage 在 outbox retry 后会产生第二次合法消费，需要 attempt/invocation 维度区分。

### R1-Q2：是否存在持久化 invocation/attempt identity？

**结论：存在——`AiAutoReplyRun.attempt_count`**

| 检查项 | 结果 | 证据 |
|---|---|---|
| 字段存在 | ✓ | `models.py:569` `attempt_count = Column(Integer, nullable=False, default=0)` |
| LLM 调用前持久化 | ✓ | `_add_run` 在 `suggest_reply` 前 commit（`dry_run_service.py:376,764`）；`claim_next_batch` 在原子 UPDATE 中 `attempt_count=attempt_count+1` + commit（`outbox_service.py:244,249`）→ attempt_count 在 LLM 调用前已 commit |
| retry/restart 复用同一值 | ✓ | outbox retry 不创建新 Run，claim 时 `attempt_count+1` 原子递增（`outbox_service.py:244`）；recover 不改 attempt_count；manual_retry 重置为 0（`outbox_service.py:502`） |
| 并发不会两个 attempt 拿同值 | ✓ | claim 用原子条件 UPDATE `WHERE status IN (pending, retry_wait) AND ... SET attempt_count=attempt_count+1 RETURNING`（`outbox_service.py:230-249`），只有一个线程成功 |
| replay 能恢复原值 | ✓ | attempt_count 持久化在 DB，retry 重新加载原 run 时读到的就是已 commit 的值 |

**满足全部 4 个条件**——`attempt_count` 可用作持久化 invocation identity。

**最终 key 结构**：`ai_auto_reply_run:{run.id}:{attempt_count}:{llm_call_stage}`

- `run.id`：稳定持久化分组键
- `attempt_count`：持久化 invocation identity（每次 outbox retry 递增，区分同一 Run 的不同 LLM 调用周期）
- `llm_call_stage`：primary / retry_combined（同一次 suggest_reply 内的 2 个合法收费 operation）

**Cardinality**：1 Run : N attempts × 2 stages = 最多 2N 次合法收费

### R1-Q3：Preview 当前计费行为

**结论：B（当前计费）**

- `app/routers/agents.py:272-276` `preview_agent` 调 `suggest_reply` → 9100 `build_reply_suggestion` → `_build_llm_reply` → `_report_llm_usage`（`reply_decision_service.py:1160,1236`）
- `_report_llm_usage` 调 `ComputeUsageClient().report_usage`（`reply_decision_service.py:3783`）→ HTTP POST 到 9000 `/internal/compute/usage` → `record_usage` 写 ComputeTransaction
- **当前确实产生 ComputeTransaction**（无 run_id 透传，`conversation_id="agent-preview"`，`idempotency_key=None`）
- Preview 路径当前**计费且无幂等**——同一商户多次预览各扣一次

**需要决策**：Preview 是否应免费？如果免费 → 业务变更单独批准；如果计费 → 需稳定 identity（如 timestamp + merchant_id + agent_id 不可靠，需持久化实体或接受 None 不去重）。

### R1-Q4：Training/共享 9100 计费路径

**结论：Training 走独立 `_report_usage`，不共享 `_report_llm_usage`，但同样不传 `idempotency_key`**

- `apps/xg_douyin_ai_cs/services/knowledge_training_service.py:475-485` 独立 `_report_usage` 函数，直接调 `ComputeUsageClient().report_usage`
- capability_key=`knowledge`（不同于 auto-reply 的 `douyin-cs`）
- **不共享** `_report_llm_usage` 路径——Training 有自己的 LLM 调用 + 自己的 report_usage
- **但不传 `idempotency_key`**（`knowledge_training_service.py:481` 无 idempotency_key 参数）
- Training 是独立 consumer（CALL_SITE_IDENTIFIED），M01 迁移不影响 Training

---

## 二维合同表（最终产出）

| Scene | Persistent Parent | Invocation Identity | Stage | Current Charge | Final Identity Status |
|---|---|---|---|---|---|
| Auto Reply（首调） | AiAutoReplyRun.id | attempt_count | primary | chargeable | `ai_auto_reply_run:{run.id}:{attempt_count}:primary` |
| Auto Reply（retry_combined） | AiAutoReplyRun.id | attempt_count | retry_combined | chargeable | `ai_auto_reply_run:{run.id}:{attempt_count}:retry_combined` |
| Outbox retry（重新触发） | same Run | attempt_count+1 | primary/... | 合法新消费 | `ai_auto_reply_run:{run.id}:{attempt_count+1}:primary` |
| Preview | 无 Run | 无 | primary/retry_combined | 当前计费（POLICY_PENDING） | PREVIEW_CHARGED_NO_IDENTITY（需产品决策） |
| Training | 无 Run（独立路径） | 无 | N/A | chargeable（knowledge） | 独立 consumer（Stage 5 迁移） |

### 最终结论

**有持久化 attempt identity → Stage 4B M01 迁移可行**

最终 key：`ai_auto_reply_run:{run.id}:{attempt_count}:{llm_call_stage}`

- `run.id` 稳定持久化（LLM 调用前 commit）
- `attempt_count` 稳定持久化（claim 原子递增，LLM 调用前 commit，满足全部 4 个条件）
- `llm_call_stage` 区分 primary / retry_combined（2 个合法收费 operation）

**Preview 路径**：POLICY_PENDING（当前计费但无 identity，需产品决策是否免费）

**Training 路径**：独立 consumer，Stage 5 迁移
