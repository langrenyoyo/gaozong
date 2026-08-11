# P1-GLOBAL-ACTIVE-NONE-AUDIT-2 — Full Re-Run After F-1 Closure

> 任务：`P1-GLOBAL-ACTIVE-NONE-AUDIT-2`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`（`BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT`）
> 前序：`GLOBAL_ACTIVE_NONE_AUDIT-1 = FAILED` + `F-1 = RESOLVED`（closure commit `cab2e96`）
> 基线 commit：`cab2e96`（修复：闭环Trusted Reply-Suggestion幂等计费身份）
> 日期：2026-08-11
> 窗口性质：READ ONLY 全局审计重跑（从零重新枚举整个 ACTIVE compute charge surface，未 commit、未 push、未改 canonical DB）
> Source of Truth：当前代码事实（3 个 Explore agent 多模态 sweep 交叉验证 + 直接 Read 核验） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| GN2-0 Git / baseline | ✅ PASS |
| GN2-1 Global discovery completeness | ✅ PASS |
| GN2-2 ACTIVE classification | ✅ PASS |
| GN2-3 11 consumer reconciliation | ✅ PASS |
| GN2-4 Trusted Proxy closure | ✅ PASS |
| GN2-5 Identity component validity | ✅ PASS |
| GN2-6 Partial/sentinel audit | ✅ PASS |
| GN2-7 Wrapper propagation | ✅ PASS |
| GN2-8 Error/retry branches | ✅ PASS |
| GN2-9 Internal compute caller inventory | ✅ PASS |
| GN2-10 F-2 classification | ✅ PASS（DORMANT）|
| GN2-11 Core None compatibility | ✅ PASS（compatibility present，ACTIVE caller transmitting None = 0）|
| GN2-12 PostgreSQL ledger audit | ✅ PASS（NO HISTORICAL RUNTIME EVIDENCE，code surface 为主证据）|
| GN2-13 Historical/runtime evidence | ✅ PASS |
| GN2-14 UNKNOWN = 0 | ✅ PASS |
| GN2-15 Canonical DB no mutation | ✅ PASS |

**Verdict（候选）**：

```text
GLOBAL_ACTIVE_NONE_AUDIT
= COMPLETE_PENDING_APPROVAL

ACTIVE NONE = 0
ACTIVE EMPTY = 0
ACTIVE WHITESPACE = 0
ACTIVE PARTIAL/SENTINEL = 0
UNKNOWN ACTIVE = 0
UNKNOWN suspicious ledger rows = 0
```

---

## 1. Baseline

```text
HEAD = cab2e96（修复：闭环Trusted Reply-Suggestion幂等计费身份）
worktree = clean
```

正式状态（§0 已同步）：

```text
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = RESOLVED
GLOBAL_ACTIVE_NONE_AUDIT = FAILED / RE-RUN_REQUIRED（本轮重跑）
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = BLOCKED_BY_GLOBAL_ACTIVE_NONE_REAUDIT
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED

P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE（0032/0033/0034/RAG Query 0005 全 PG_RUNTIME_VERIFIED）
FRESH BOOTSTRAP PRINCIPAL REPRODUCIBILITY = VERIFIED
```

F-1 closure commit `cab2e96`（7 files，含 proxy handler + focused tests + implementation report + approval + 治理文档），未 push。本轮以 `cab2e96` 为 baseline。

---

## 2. F-1 Closure Checkpoint

```text
F-1 = RESOLVED（2026-08-11 独立实施审批 APPROVED_WITH_CORRECTIONS，closure commit cab2e96）

candidate scope（已 commit）:
  MODIFY app/routers/douyin_ai_cs_proxy.py（identity + finalize + fail-closed + async→def）
  CREATE tests/test_trusted_reply_suggestion_compute_idempotency.py（7 passed）
  CREATE docs/architecture/remediation/P1_F1_..._IMPLEMENTATION_REPORT.md
  CREATE docs/architecture/remediation/P1_F1_..._IMPLEMENTATION_APPROVAL.md
  MODIFY CLAUDE.md / docs/ai/05_PROJECT_CONTEXT.md / docs/architecture/CROSS_MODULE_RISK_REGISTER.md
```

9100 零改（git diff 空）；无 migration（复用 0034）；compute core 零改；external API 无 breaking。详见 `P1_F1_TRUSTED_REPLY_SUGGESTION_IDEMPOTENCY_IMPLEMENTATION_APPROVAL.md`。

---

## 3. Audit Definition

本轮**不是**"确认 F-1 修好了"，而是：

> 从零重新枚举整个 current ACTIVE compute charge surface，并证明不存在新的、遗漏的或退化的 None / Empty / Partial / Sentinel Business Event Identity 路径。

不得复用 Audit-1 inventory（15 call sites）作为答案——本轮从 compute core 向外反向发现所有 caller，按当前代码实际结果处理（§2）。

---

## 4. Discovery Method

多模态 sweep（3 个 Explore agent 并行，从不同搜索角度发现 compute charge call site）：

1. **Agent 1 — `record_usage(` call site 枚举**：从 compute core 入口（`apps/compute/services.py:615` + `app/services/compute_service.py` re-export shim）反向发现所有直接/间接 caller，含 identity builder + idempotency_key 传参表达式。
2. **Agent 2 — `ComputeUsageClient` + HTTP compute 端点枚举**：从 9100→9000 HTTP 上报层发现所有 `ComputeUsageClient.report_usage` / `check_balance` 调用点 + 两个 `/internal/compute/usage` 端点（ACTIVE A vs DORMANT F-2）+ `ComputeClient`（packages/clients）。
3. **Agent 3 — identity builder + error/retry 分支枚举**：逐个确认 11 identity family 构造点 + 搜索 error/retry/fallback/except 分支中 identity 丢失点 + sentinel/畸形 key 扫描。

3 个 agent 结果交叉验证一致（call site 清单、identity 构造点、None 路径分类均一致）。本报告综合三份结果。

搜索范围：`app/`、`apps/`、`packages/`（排除 `tests/`、`docs/`、`dist/`、`frontend/`）。

---

## 5. Complete Call-Site Inventory

### 5.1 Compute core 入口

```text
M07 core: apps/compute/services.py:615 record_usage(db, merchant_id, tokens, *, ..., idempotency_key: str | None = None)
  - idempotency_key 非空 → 幂等路径（ON CONFLICT 原子，:681-769）
  - idempotency_key is None → 旧兼容裸扣（:771-800，warning record_usage_no_idempotency_key）

re-export shim: app/services/compute_service.py:7-31
  from apps.compute.services import (... record_usage ...)  ← 同一函数对象，无包装/无分支/无 drop
```

### 5.2 完整 call site 表（N=15）

| # | Call Site | Module | Runtime Reachability | Identity | Classification |
|---|---|---|---|---|---|
| 1 | `app/integrations/douyin_webhook.py:1251` | M02 | ACTIVE（webhook im_receive_msg 入站）| `webhook_event:{event.id}:lead_usage`（f-string 恒非空，event PK）| ACTIVE identity-bearing |
| 2 | `app/services/wechat_task_service.py:512` | M04 | ACTIVE（微信任务完成回调）| `wechat_task:{task.id}:result_usage`（f-string 恒非空，task PK）| ACTIVE identity-bearing |
| 3 | `app/services/ai_edit_las_service.py:749` | M06 | ACTIVE（LAS 混剪成功）| `las_job:{job.id}:archive_usage`（f-string 恒非空，job PK）| ACTIVE identity-bearing |
| 4 | `app/services/material_analysis.py:268` | M05 | ACTIVE（素材分析 ark 成功）| `material_analysis_execution:{execution_id}:ark_analysis`（ternary，execution_id 恒非空，caller :106 传 execution.id）| ACTIVE identity-bearing |
| 5 | `app/routers/compute.py:482` | M07 endpoint | ACTIVE（主 9000 挂载 :155，9100 HTTP 落地点）| `payload.idempotency_key`（透传，上游 9100 builder 构造非空）| ACTIVE identity-bearing |
| 6 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py:3814`（builder :3800）| M01 Auto Reply | ACTIVE（suggest_reply primary :1160）| `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}`（run_id+attempt_count 恒非空，9000 ai_auto_reply_dry_run_service:359-360 设置）| ACTIVE identity-bearing |
| 7 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py:3814`（builder :3810）| M01 Preview + Trusted | ACTIVE（suggest_reply primary :1160 / retry_combined :1236）| `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`（preview_execution_id 恒非空；**2 个 ACTIVE entry points**：Preview agents.py:311 + Trusted Proxy douyin_ai_cs_proxy.py:374）| ACTIVE identity-bearing |
| 8 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py:3814`（builder :3811 legacy）| M01 legacy | **无 ACTIVE caller 触发**（Auto Reply 设 run_id+attempt_count / Preview+Trusted 设 preview_execution_id）| `None`（legacy 兼容，保持 None）| COMPATIBILITY（legacy None 路径，无 ACTIVE 触发）|
| 9 | `apps/xg_douyin_ai_cs/rag/repository.py:523`（builder :504）| M03 RAG Query | ACTIVE（search embedding primary :1155 / fallback_embedding :1219）| `rag_search_execution:{search_execution_id}:{embedding_stage}`（search_execution_id 恒非空，_create_search_execution durable commit）| ACTIVE identity-bearing |
| 10 | `apps/xg_douyin_ai_cs/rag/repository.py:523`（builder :501）| M03 RAG Ingest | ACTIVE（train_document :592 / train_scope :753）| `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`（三参恒非空，identity matrix :499 严格互斥）| ACTIVE identity-bearing |
| 11 | `apps/xg_douyin_ai_cs/rag/repository.py:523`（builder :507 legacy / :516 violation）| M03 legacy | **无 ACTIVE caller 触发**（Ingest 三参全有 / Query 两参全有）| `None`（legacy / violation guard）| COMPATIBILITY |
| 12 | `apps/xg_douyin_ai_cs/services/knowledge_training_service.py:562`（builder :555）| M03 Training | ACTIVE（ask 知识问答）| `knowledge_training_execution:{execution_id}:ask`（ternary，execution_id 恒非空，caller :621 传 request_id）| ACTIVE identity-bearing |
| 13 | `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:159`（builder :152）| M01 Daily Report | ACTIVE（日报摘要 LLM）| `daily_report_generation:{generation_id}:summary`（ternary，generation_id 恒非空，9000 daily_report_job_service:383 设置）| ACTIVE identity-bearing |
| 14 | `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py:288`（builder :281）| M01 Return Visit | ACTIVE（回访判定 LLM）| `return_visit_run:{return_visit_run_id}:judge`（ternary，return_visit_run_id 恒非空，9000 return_visit_run_service:576 设置）| ACTIVE identity-bearing |
| 15 | `apps/compute/routers.py:362` | F-2 dev_only | **DORMANT**（主 9000 未挂载，仅 9205 dev_only）| **未传 idempotency_key= 参数**（latent bug，但无 production caller）| DORMANT / DEV_ONLY |

**附加（非 charge-producing，余额查询）**：
- `apps/xg_douyin_ai_cs/services/compute_usage_client.py:187` `check_balance`（httpx.get，余额查询无幂等键）— ACTIVE 但非 charge。

**附加（DEV_ONLY client，无 production caller）**：
- `packages/clients/compute_client.py:114` `ComputeClient.report_usage`（payload 不含 idempotency_key 字段；仅 tests/test_compute_client.py 调用）— DEV_ONLY。

---

## 6. ACTIVE Entry-Point Inventory

```text
TOTAL call sites = 15
ACTIVE entry points = 12（#1-7,9,10,12,13,14）
ACTIVE identity-bearing = 12
ACTIVE None = 0
ACTIVE empty = 0
ACTIVE whitespace = 0
ACTIVE partial/sentinel = 0
COMPATIBILITY（legacy None 路径，无 ACTIVE 触发）= 2（#8, #11）
DORMANT / DEV_ONLY = 1（#15 F-2）
UNKNOWN = 0
```

ACTIVE entry points = 12（非 11）：因为 Preview identity family（#7）承载 **2 个 ACTIVE entry points**（draft-agent Preview + Trusted Reply-Suggestion），共享同一 identity family。详见 §7。

---

## 7. Trusted Proxy Re-Audit（§7-9）

### 7.1 F-1 Current Chain（§8）

实施后（`cab2e96`）独立确认：

```text
Trusted Proxy（douyin_ai_cs_proxy.py:230）
  → auth / permission / merchant validation（:234-243）
  → agent binding validation（:245-260）
  → agent active check（:262-272）
  → ★ _create_preview_execution(db, context.merchant_id, agent.agent_id) durable commit（:374，agents.py:73-75）
  → payload["preview_execution_id"] = preview_exec_id（:390，exactly one identity source）
  → 9000→9100 suggest_reply（:393，HTTP）
    → 9100 _report_llm_usage（reply_decision_service.py:3807 Preview 分支）
    → ai_preview_execution:{preview_execution_id}:{llm_call_stage}
    → ComputeUsageClient.report_usage → 9000 /internal/compute/usage → record_usage（非空 key，幂等路径）
  → _finalize_preview_execution(completed/failed)
```

```text
old all-None path = NOT REACHABLE from successful ACTIVE proxy path
  handler 必经 _create_preview_execution（fail-closed 不 fall through）
  → payload 必含 preview_execution_id（非空 int PK）
  → 9100 必走 Preview 分支构造非空 identity
  → record_usage 收到非空 idempotency_key → 走幂等路径（非 legacy 裸扣）
```

### 7.2 F-1 Fail-Closed Static Audit（§9）

代码核验（`douyin_ai_cs_proxy.py:373-390`）：

```python
try:
    preview_exec_id = _create_preview_execution(db, context.merchant_id, agent.agent_id)
except Exception as exc:
    db.rollback()
    logger.exception(...)
    raise HTTPException(status_code=502, detail={"code": "PREVIEW_EXECUTION_CREATE_FAILED", ...}) from exc
# execution 创建失败 → raise 502，不 fall through
payload["preview_execution_id"] = preview_exec_id
```

```text
execution creation failure → proxy fails (502) → no suggest_reply
create failed → old identity-less fallback = NOT REACHABLE
```

非仅静态断言——F1-PG-5 runtime injection 已验证（见 `P1_F1_..._IMPLEMENTATION_REPORT.md` §21，suggest_reply call count=0 / balance 不变）。本轮 READ ONLY 不重做 F1-PG-5 完整 runtime injection（§27），代码核验确认不变式保持。

---

## 8. Preview / Trusted Shared Identity Family（§10）

`AiPreviewExecution` 现承载 **2 类 ACTIVE 入口**：

| Entry Point | Route | identity source | durable before LLM |
|---|---|---|---|
| draft-agent AI Preview | `POST /agents/{id}/preview`（agents.py:311）| `_create_preview_execution(db, context.merchant_id, agent_id)`（agents.py:311）| ✅ commit before suggest_reply（agents.py:308-312）|
| Trusted Reply-Suggestion | `POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion`（douyin_ai_cs_proxy.py:374）| `_create_preview_execution(db, context.merchant_id, agent.agent_id)`（douyin_ai_cs_proxy.py:374）| ✅ commit before suggest_reply（:374 → :393）|

两者共享 namespace `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`，**均 always establish preview_execution_id before LLM**（durable commit before suggest_reply）。

```text
both always establish preview_execution_id before LLM = VERIFIED
```

不因共享 namespace 只检查其中一个入口——两个 entry point 分别确认 durable commit timing（§7.1 + agents.py 先例）。

### 分类模型（§7/§30）

```text
11 identity families / 12 active entry points
  （Preview family 承载 2 个 ACTIVE entry points，不强行说"only 11 ACTIVE routes"）
```

不为了维持历史"11/11"数字强行分类。Global Audit 目标是完整，不是数字漂亮。

---

## 9. Identity Component Audit（§11-12）

对所有 ACTIVE identity builder 逐项确认：

| Family | components | stable | deterministic | established before charge |
|---|---|---|---|---|
| Auto Reply | run_id(AiAutoReplyRun.id) + attempt_count(claim 快照) + llm_call_stage | ✅ DB PK | ✅ | ✅ 9000 durable commit before 9100 |
| Preview + Trusted | preview_execution_id(AiPreviewExecution.id) + llm_call_stage | ✅ DB PK | ✅ | ✅ 9000 durable commit before 9100 |
| RAG Query | search_execution_id(rag_search_executions.id) + embedding_stage | ✅ DB PK | ✅ | ✅ 9100 durable commit before embedding daemon |
| RAG Ingest | run_id + document_id + chunk_index | ✅ DB PK | ✅ | ✅ _create_training_run durable commit |
| Training | execution_id(request_id) + "ask" | ✅ | ✅ | ✅ ask() 传入 |
| Daily Report | generation_id(DailyReportGeneration.id) + "summary" | ✅ DB PK | ✅ | ✅ claim 后快照 |
| Return Visit | return_visit_run_id(ReturnVisitRun.id) + "judge" | ✅ DB PK | ✅ | ✅ claim 后快照 |
| M02 Webhook | event.id + "lead_usage" | ✅ DB PK | ✅ | ✅ event insert+refresh |
| M04 WeChat Task | task.id + "result_usage" | ✅ DB PK | ✅ | ✅ task refresh |
| M06 LAS | job.id + "archive_usage" | ✅ DB PK | ✅ | ✅ job 持久化 |
| M05 Material | execution.id + "ark_analysis" | ✅ DB PK | ✅ | ✅ execution commit COMPLETED |

### Partial/Sentinel Audit（§12）

搜索 `:None:` / `:null:` / `::` / `:unknown:` / `:missing:` 字面量 + f-string 插值可能为 None 的变量：

```text
f-string 插值 None 变量 = 0（所有 11 个 identity f-string 前置 None guard）
  - ai_auto_reply_run: 前置 if run_id is not None and attempt_count is not None（:3790）
  - ai_preview_execution: 前置 elif preview_execution_id is not None（:3807）
  - rag_embedding: 前置 if ingest_count == 3（:499，保证三参非 None）
  - rag_search_execution: 前置 elif query_count == 2（:502，保证两参非 None）
  - 其余 7 个 ternary family: if X is not None 前置 guard

sentinel 字面量（:None:/:null:/::/:unknown:/:missing:）= 0
  （:: 匹配均为 SQL 类型转换 ::text / IP ::1 / UI 控件类名，无 idempotency_key 内）
getattr(...) or 'unknown' fallback sentinel = 0
  （匹配均为 UI 属性/配置读取，无 identity 构造）
```

```text
ACTIVE PARTIAL/SENTINEL = 0
```

---

## 10. 11/11 Consumer Reconciliation（§6）

重新从当前代码确认原 11 条 consumer identity contract 未退化（非只引用历史 checkpoint）：

| # | Consumer | identity contract（当前代码） | 退化? |
|---|---|---|---|
| 1 | M04 WeChat Task | `wechat_task:{task.id}:result_usage`（wechat_task_service.py:512）| ❌ 无 |
| 2 | M06 LAS Archive | `las_job:{job.id}:archive_usage`（ai_edit_las_service.py:749）| ❌ 无 |
| 3 | M01 Auto Reply | `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}`（reply_decision_service.py:3800）| ❌ 无 |
| 4 | M02 Webhook Lead | `webhook_event:{event.id}:lead_usage`（douyin_webhook.py:1251）| ❌ 无 |
| 5 | M01 Return Visit | `return_visit_run:{return_visit_run_id}:judge`（return_visit_judge_service.py:282）| ❌ 无 |
| 6 | M01 Daily Report | `daily_report_generation:{generation_id}:summary`（daily_report_summary_service.py:153）| ❌ 无 |
| 7 | M01 AI Preview | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}`（reply_decision_service.py:3810）| ❌ 无 |
| 8 | M05 Material Analysis | `material_analysis_execution:{execution_id}:ark_analysis`（material_analysis.py:268）| ❌ 无 |
| 9 | M03 Training | `knowledge_training_execution:{execution_id}:ask`（knowledge_training_service.py:556）| ❌ 无 |
| 10 | M03 RAG Query | `rag_search_execution:{search_execution_id}:{embedding_stage}`（repository.py:504）| ❌ 无 |
| 11 | M03 RAG Ingest | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`（repository.py:501）| ❌ 无 |

**11/11 identity family 全部存在且 identity contract 未退化。** + Trusted Reply-Suggestion 作为 Preview family 第二 ACTIVE entry（非第 12 family）。

---

## 11. Wrapper Propagation（§19）

确认 consumer identity → wrapper → ComputeUsageClient / record_usage 过程无 drop / rename / default override to None：

```text
app/services/compute_service.py（re-export shim）
  → from apps.compute.services import record_usage（同一函数对象，无包装/无分支/无 drop）✅

ComputeUsageClient.report_usage（compute_usage_client.py:199-309）
  → payload["idempotency_key"] = idempotency_key（:260，原样放入 JSON body，None 显式发送为 null，非省略）✅
  → HTTP POST → 9000 /internal/compute/usage

app/routers/compute.py:482（端点 A，主 9000 挂载）
  → compute_service.record_usage(idempotency_key=payload.idempotency_key)（透传）✅
```

```text
wrapper drop = 0
rename error = 0
default override to None = 0
```

唯一丢 key 点：F-2 端点（`apps/compute/routers.py:362`，未传 idempotency_key= 参数）— DORMANT（§13）。

---

## 12. Error/Retry Branches（§22）

搜索 except / retry / fallback / finally / failed / usage report 分支中"主路径有 key，异常路径用 None"：

```text
reply_decision_service._report_llm_usage:
  except Exception（:3830-3831）→ 上报失败不重试，identity 已在 try 前构造完成，未丢失 ✅
  无 retry/fallback 分支覆盖 key 值 ✅

repository._embed_with_usage:
  except Exception（:534-535）→ 上报失败不影响 RAG 主流程，identity 未丢失 ✅
  _run_embed_with_hard_timeout 超时 → daemon 线程内 _embed_with_usage 用原 search_execution_id + embedding_stage ✅

material_analysis._report_analysis_usage:
  except Exception（:295-296）→ 仅 warning，identity 未丢失 ✅
  except（:117-126）→ rollback + status=failed，不调 _report_analysis_usage（usage 在 try 内 :106）✅

其余 builder: 无 error/retry 分支覆盖 identity 构造后的 key 值 ✅
```

```text
main path has key, error/fallback path uses None = 0
```

---

## 13. Internal Compute Caller Audit + F-2（§20-21）

### 13.1 主 9000 `/internal/compute/usage` callers

唯一 ACTIVE caller：9100 `ComputeUsageClient.report_usage`（compute_usage_client.py:262-272）→ HTTP POST → 9000 端点 A（compute.py:458，透传 idempotency_key）。所有 9100 side builder 构造非空 key → 端点 A 收到非空 idempotency_key → record_usage 幂等路径。

### 13.2 F-2 Reclassification（§21）

`apps/compute/routers.py:353` `/api/compute/internal/usage`：

| 维度 | 结论 | 证据 |
|---|---|---|
| idempotency_key 透传 | **丢失** ❌ | handler `record_usage(...)`（:362-377）未传 `idempotency_key=` 参数 |
| 主 9000 挂载 | **未挂载** | `app/main.py:20-57` 无 `apps.compute` import；:153-155 只挂 `app/routers/compute.py` |
| 唯一挂载点 | 9205 dev_only | `apps/compute/main.py:11` → `apps/compute/router.py:9` |
| production caller | **0** | `packages/clients/compute_client.py`（ComputeClient）仅 tests 调用 |

```text
F-2 = DORMANT（保持）
  main 9000 still does not mount it ✅
  production import count still 0 ✅
  ComputeClient production caller still 0 ✅
```

事实未变化 → F-2 继续 DORMANT / NON-BLOCKING（§21）。未处理（§34）。

---

## 14. Core None Compatibility（§23-24）

```text
CORE NONE COMPATIBILITY = PRESENT
  record_usage(idempotency_key=None) → 旧兼容裸扣路径仍存在（services.py:771-800，warning）
  ComputeUsageRequest.idempotency_key: Optional[str] = Field(None)（schemas.py:1404，无 validator 拒绝 None）
```

这本身不阻断 Audit-2。core None 兼容是 COMPATIBILITY CONTRACT（可能服务 legacy/dev/未知 caller），不得未经批准修改 compute core（§23）。

Hard requirement 仍是：

```text
CURRENT ACTIVE PRODUCTION CALLERS USE NONE = 0
```

所有 ACTIVE caller 构造非空 identity（§5/§6），不触发 core None 路径。若 Audit 通过。

---

## 15. PostgreSQL Ledger Audit（§25）

canonical local 只读查询（`auto_wechat` 库，`auto_wechat` 应用角色）：

```text
total transactions = 0
consume total = 0
consume NULL keys = 0
consume empty keys = 0
consume whitespace-only keys = 0
consume non-null keys = 0
distinct identity keys = 0
malformed key scan（:None:/:null:/::/:unknown:/:missing:）= 0
```

```text
CANONICAL LEDGER = NO HISTORICAL RUNTIME EVIDENCE
  （之前所有 runtime 验证 fixture 已 cleanup，无持久 ledger 数据）
  不把 0 行当成主要 PASS 证据 — 本轮以 current code surface completeness 为主要证据
```

canonical DB 状态：`revision=0034 / tables=61`（unchanged，§28）。

---

## 16. Historical Runtime Evidence（§26）

引用已正式批准/验证的 runtime identity supporting evidence：

| Consumer | PG Verification | Commit |
|---|---|---|
| 0032 Daily Report | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | — |
| 0033 M05 Material Analysis | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | — |
| 0034 AI Preview | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | — |
| RAG Query 0005 | PG_RUNTIME_VERIFIED | `5d8b6ba` |
| F-1 Trusted Reply-Suggestion | RESOLVED（F1-PG-1~6 runtime 全 PASS）| `cab2e96` |

Global Audit 本身仍以 **current code surface completeness** 为主要证据（非仅引用历史 runtime）。

---

## 17. Runtime Spot Check Decision（§27）

本轮不要求机械重跑所有 consumer。检查是否出现 §27 spot check 触发条件：

```text
nullable component ambiguity = NO（所有 ACTIVE identity 前置 None guard，§9）
new wrapper = NO（F-1 是新增 entry，但已有 focused test + F1-PG runtime 覆盖）
new branch = NO（F-1 fail-closed 已代码核验 + F1-PG-5 runtime 覆盖）
classification uncertainty = NO（3 agent 交叉验证一致）
F-1 current behavior cannot be statically determined = NO（代码 diff 明确，fail-closed 可静态确认）
```

静态合同已无歧义 → 不额外跑昂贵 runtime。报告说明原因（§27）。

---

## 18. GN2 Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| GN2-0 | Git / baseline | ✅ PASS | HEAD=cab2e96 / clean；F-1 RESOLVED；P1 ACTIVE CONSUMER PG VERIFICATION COMPLETE |
| GN2-1 | Global discovery completeness | ✅ PASS | 3 agent 多模态 sweep（record_usage / ComputeUsageClient+HTTP / identity builder+error），交叉验证一致 |
| GN2-2 | ACTIVE classification | ✅ PASS | 12 ACTIVE identity-bearing + 2 COMPATIBILITY legacy None（无 ACTIVE 触发）+ 1 DORMANT F-2 |
| GN2-3 | 11 consumer reconciliation | ✅ PASS | 11/11 identity family 全部存在且 contract 未退化（§10）|
| GN2-4 | Trusted Proxy closure | ✅ PASS | F-1 RESOLVED；old all-None path NOT REACHABLE（handler 必经 _create_preview_execution + fail-closed 不 fall through）|
| GN2-5 | Identity component validity | ✅ PASS | 全部 DB PK / durable commit before charge / deterministic / stable（§9）|
| GN2-6 | Partial/sentinel audit | ✅ PASS | f-string 插值 None=0；sentinel 字面量=0；getattr fallback=0 |
| GN2-7 | Wrapper propagation | ✅ PASS | re-export shim 同函数对象；ComputeUsageClient 透传；端点 A 透传；无 drop/rename/override None |
| GN2-8 | Error/retry branches | ✅ PASS | 无"主路径有 key，异常路径用 None"；except 不覆盖已构造 key |
| GN2-9 | Internal compute caller inventory | ✅ PASS | 唯一 ACTIVE caller = 9100 ComputeUsageClient → 端点 A（透传 key）|
| GN2-10 | F-2 classification | ✅ PASS | DORMANT（主 9000 未挂载，production caller=0，丢 key 缺陷仍存在但非 ACTIVE）|
| GN2-11 | Core None compatibility | ✅ PASS | compatibility present（record_usage(None) 旧路径存在）；ACTIVE caller transmitting None = 0 |
| GN2-12 | PostgreSQL ledger audit | ✅ PASS | NO HISTORICAL RUNTIME EVIDENCE（0 行，fixture 已 cleanup）；code surface 为主证据 |
| GN2-13 | Historical/runtime evidence | ✅ PASS | 0032/0033/0034/0005/F-1 全 PG_RUNTIME_VERIFIED/RESOLVED |
| GN2-14 | UNKNOWN = 0 | ✅ PASS | 15 call site 全分类（12 ACTIVE + 2 COMPATIBILITY + 1 DORMANT），无 UNKNOWN |
| GN2-15 | Canonical DB no mutation | ✅ PASS | READ ONLY，revision=0034/tables=61 unchanged |

---

## 19. Global Metrics

```text
TOTAL call sites = 15
ACTIVE entry points = 12
ACTIVE identity-bearing = 12
ACTIVE None = 0
ACTIVE empty = 0
ACTIVE whitespace = 0
ACTIVE partial/sentinel = 0
COMPATIBILITY（legacy None，无 ACTIVE 触发）= 2
DORMANT / DEV_ONLY = 1（F-2）
UNKNOWN active path = 0
UNKNOWN suspicious ledger rows = 0

F-1 old None path unreachable = VERIFIED
F-2 still DORMANT/non-production = VERIFIED
canonical DB unchanged = VERIFIED
```

---

## 20. Remaining Out-of-P1 Gaps（§36）

```text
PREVIEW_REQUEST_RECOVERY_GAP = OUT_OF_P1 / UNRESOLVED
  覆盖：AI Preview + Trusted Reply-Suggestion（C4 扩展覆盖）
  same durable execution + same stage replay = P1 protected
  full HTTP request response-lost / resubmit = OUT_OF_P1

DAILY_REPORT_REQUEST_RECOVERY_GAP = OUT_OF_P1
TRAINING_REQUEST_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_RUN_RECOVERY_GAP = OUT_OF_P1
RAG_INGEST_REQUEST_RECOVERY_GAP = OUT_OF_P1
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP = OUT_OF_P1
RAG_QUERY_REQUEST_RECOVERY_GAP = OUT_OF_P1
```

Global Audit 通过 ≠ recovery gaps resolved（§36）。7 个 Reliability Gap 继续 OUT_OF_P1。

---

## 21. Naming Debt（§37）

```text
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
  AiPreviewExecution 承载：AI Preview + Trusted Reply-Suggestion（2 类 ACTIVE entry）
  DOMAIN_MODEL_CONTAMINATION = NOT PRESENT
  NAMING_DEBT = PRESENT / NON_BLOCKING
```

不处理（§37）。不重命名 table/model。

---

## 22. Verdict

```text
GLOBAL_ACTIVE_NONE_AUDIT
= COMPLETE_PENDING_APPROVAL

ACTIVE NONE = 0
ACTIVE EMPTY = 0
ACTIVE WHITESPACE = 0
ACTIVE PARTIAL/SENTINEL = 0
UNKNOWN ACTIVE = 0
UNKNOWN suspicious ledger rows = 0

F-1 old None path unreachable = VERIFIED
F-2 still DORMANT/non-production = VERIFIED
canonical DB unchanged = VERIFIED
```

不得自行 `GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED`（须独立审批窗口裁定，§34）。

---

## 23. P1 Candidate State（§38）

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING_GLOBAL_AUDIT_APPROVAL
Final PostgreSQL Concurrent Closure = BLOCKED_PENDING_GLOBAL_AUDIT_APPROVAL / NOT AUTHORIZED
```

直到独立审批正式批准 Audit-2，方可进入 Final PostgreSQL Concurrent Closure Gate。

---

## 24. Next Gate

```text
P1-GLOBAL-ACTIVE-NONE-AUDIT-2 独立审批窗口
  → APPROVED
  → Final PostgreSQL Concurrent Closure Gate（NOT AUTHORIZED until then）
```

---

## 25. Governance Docs

本 Audit-2 candidate 报告为唯一新增产物。若 Audit-2 候选通过，独立审批后允许 CLAUDE.md / 05_PROJECT_CONTEXT.md 写 `GLOBAL_ACTIVE_NONE_AUDIT = COMPLETE_PENDING_APPROVAL`（不得写 VERIFIED）。本轮未改治理文档（candidate diff 仅本报告）。

---

## 26. Git / 边界遵守

- Audit-2 **DO NOT COMMIT**（candidate 交独立审批，§41）；
- 未 push；
- READ ONLY：未改业务代码 / migration / canonical DB / compute core / 9100 / F-2 / recovery gaps；
- 未 start Final Concurrent Closure / harden compute core / fix F-2 / rename AiPreviewExecution / RB-10 / declare P1 closed；
- canonical DB 未 mutation（READ ONLY，revision=0034/tables=61 unchanged）；
- 3 agent 多模态 sweep + 直接 Read 核验，未采信 Audit-1 inventory 作为答案（从零重新枚举）。

---

## 27. 完成后停止

提交：

**P1-GLOBAL-ACTIVE-NONE-AUDIT-2 独立审批窗口。**

不得自行：
- start Final Concurrent Closure
- harden compute core
- fix F-2
- fix recovery gaps
- rename AiPreviewExecution
- RB-10
- push
- declare P1 closed
