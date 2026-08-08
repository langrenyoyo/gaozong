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
