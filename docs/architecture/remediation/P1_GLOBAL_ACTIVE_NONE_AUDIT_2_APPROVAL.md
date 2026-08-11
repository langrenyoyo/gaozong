# P1-GLOBAL-ACTIVE-NONE-AUDIT-2 — 独立审批报告

> 审批窗口：`P1-GLOBAL-ACTIVE-NONE-AUDIT-2`（独立审批，非执行窗口自述）
> 审查对象：`docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT_2.md`
> 前序：`GLOBAL_ACTIVE_NONE_AUDIT-1 = FAILED` + `F-1 = RESOLVED`（closure commit `cab2e96`）
> 基线 commit：`cab2e96`
> 审批日期：2026-08-11
> 窗口性质：READ ONLY 独立审批（未 commit、未 push、未改 canonical DB）
> 裁定：`APPROVED_WITH_CORRECTIONS`

---

## 1. Technical Decision

```
VERDICT: APPROVED_WITH_CORRECTIONS

GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED

ACTIVE NONE = 0
ACTIVE EMPTY = 0
ACTIVE WHITESPACE = 0
ACTIVE PARTIAL/SENTINEL = 0
UNKNOWN ACTIVE = 0
```

独立从当前代码（`cab2e96`）重新枚举整个 compute charge surface，未采信 Audit-2 的"15"作为搜索终点。独立枚举结果 = **15 call site**，与 Audit-2 一致，差异 0。所有 ACTIVE entry point 携带合法、完整、稳定的 Business Event Identity；不存在 ACTIVE 路径以 None/空串/空白/partial/sentinel 进入 compute core。F-1 旧 None 路径不可达，F-2 DORMANT，core None compatibility 无 ACTIVE caller。

非阻断 correction：COMPATIBILITY 分类措辞需对齐（"2 COMPATIBILITY"实为 1 个 legacy builder 的两条退路分支，非两个独立 caller）、ledger evidence wording 准确性。

```
F-1 = RESOLVED
F-2 = DORMANT / NON-BLOCKING
CORE NONE COMPATIBILITY = PRESENT / NO ACTIVE CALLER
```

---

## 2. Baseline

```
HEAD = cab2e96（修复：闭环Trusted Reply-Suggestion幂等计费身份）
worktree = clean（仅 Audit-2 报告 untracked）
```

正式状态确认：

```
F-1 TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = RESOLVED
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING_GLOBAL_AUDIT_APPROVAL
Final PostgreSQL Concurrent Closure = BLOCKED_PENDING_GLOBAL_AUDIT_APPROVAL
```

F-1 closure commit `cab2e96` 已落地（7 files：proxy handler + focused tests + implementation report/approval + 治理文档）。本轮以 `cab2e96` 为 baseline，无 BASELINE_DRIFT。

---

## 3. Independent Discovery Method

不采信 Audit-2 inventory。独立从 compute core 反向发现：

- **直接 record_usage 调用**：Grep `record_usage(` 覆盖 app/（排除 tests/docs/dist/frontend/.claude/.pytest_*/.tmp/）
- **间接 HTTP 上报**：Grep `.report_usage(` / `ComputeUsageClient` 覆盖 apps/（9100→9000 HTTP 路径）
- **legacy/dev client**：Grep `ComputeClient` 覆盖 packages/
- **identity builder + 错误分支**：直接 Read 11 个 identity builder + RAG identity matrix + except/retry 分支

搜索范围 app/、apps/、packages/（排除 tests/、docs/、dist/、frontend/）。search exhausted → inventory complete（非"找够 15 停止"）。

---

## 4. Complete Call-Site Inventory

独立枚举（N=15，与 Audit-2 一致，差异 0）：

| # | Call Site | Module | Runtime Reachability | Identity Source | Classification |
|---|-----------|--------|----------------------|-----------------|----------------|
| 1 | `app/integrations/douyin_webhook.py:1242` | M02 | ACTIVE（webhook im_receive_msg 入站）| `webhook_event:{event.id}:lead_usage`（f-string，event PK）| ACTIVE identity-bearing |
| 2 | `app/services/wechat_task_service.py:503` | M04 | ACTIVE（微信任务完成回调）| `wechat_task:{task.id}:result_usage`（f-string，task PK）| ACTIVE identity-bearing |
| 3 | `app/services/ai_edit_las_service.py:740` | M06 | ACTIVE（LAS 混剪成功）| `las_job:{job.id}:archive_usage`（f-string，job PK）| ACTIVE identity-bearing |
| 4 | `app/services/material_analysis.py:282` | M05 | ACTIVE（素材分析 ark 成功）| `material_analysis_execution:{execution_id}:ark_analysis`（ternary，execution.id PK）| ACTIVE identity-bearing |
| 5 | `app/routers/compute.py:467` | M07 endpoint A | ACTIVE（主 9000 挂载 main.py:153-155，9100 HTTP 落地点）| `payload.idempotency_key`（透传，上游 builder 非空）| ACTIVE identity-bearing（传输层）|
| 6 | `reply_decision_service.py:3814`（builder :3800）| M01 Auto Reply | ACTIVE（suggest_reply primary :1160 / retry_combined :1236）| `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}`（前置 if run_id+attempt_count 非空 guard :3790）| ACTIVE identity-bearing |
| 7 | `reply_decision_service.py:3814`（builder :3810）| M01 Preview + Trusted | ACTIVE（2 entry points：Preview agents.py:311 + Trusted Proxy douyin_ai_cs_proxy.py:374）| `ai_preview_execution:{preview_execution_id}:{stage}`（前置 elif preview_execution_id 非空 guard :3807）| ACTIVE identity-bearing |
| 8 | `reply_decision_service.py:3814`（builder :3811 legacy）| M01 legacy | 无 ACTIVE caller 触发（Auto Reply 设 run_id+attempt_count / Preview+Trusted 设 preview_execution_id）| None（legacy 兼容退路）| COMPATIBILITY |
| 9 | `apps/xg_douyin_ai_cs/rag/repository.py:523`（builder :504）| M03 RAG Query | ACTIVE（search embedding primary/fallback_embedding）| `rag_search_execution:{search_execution_id}:{embedding_stage}`（identity matrix query_count==2 guard :502）| ACTIVE identity-bearing |
| 10 | `repository.py:523`（builder :501）| M03 RAG Ingest | ACTIVE（train_document/train_scope）| `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`（identity matrix ingest_count==3 guard :499）| ACTIVE identity-bearing |
| 11 | `repository.py:523`（builder :507 legacy / :516 violation）| M03 legacy | 无 ACTIVE caller 触发（Ingest 三参全 / Query 两参全）| None（legacy/violation 退路）| COMPATIBILITY |
| 12 | `apps/xg_douyin_ai_cs/services/knowledge_training_service.py:562`（builder :555）| M03 Training | ACTIVE（ask 知识问答）| `knowledge_training_execution:{execution_id}:ask`（ternary，request_id）| ACTIVE identity-bearing |
| 13 | `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:159`（builder :152）| M01 Daily Report | ACTIVE（日报摘要 LLM）| `daily_report_generation:{generation_id}:summary`（ternary，generation_id PK）| ACTIVE identity-bearing |
| 14 | `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py:288`（builder :281）| M01 Return Visit | ACTIVE（回访判定 LLM）| `return_visit_run:{return_visit_run_id}:judge`（ternary，run_id PK）| ACTIVE identity-bearing |
| 15 | `apps/compute/routers.py:362` | F-2 dev_only | DORMANT（主 9000 未挂载，仅 9205）| 未传 `idempotency_key=`（latent bug，无 production caller）| DORMANT / DEV_ONLY |

**附加**：
- `compute_usage_client.py:187` `check_balance`（httpx.get，余额查询非 charge）— ACTIVE 但非 charge producing。
- `packages/clients/compute_client.py:26` `ComputeClient.report_usage`（签名无 idempotency_key，production import=0）— DEV_ONLY / LEGACY。

---

## 5. Candidate Inventory Comparison

```
独立枚举总数 = 15
Audit-2 枚举总数 = 15
差异 = 0
INDEPENDENT INVENTORY MATCH = EXACT
```

分类对比：

```
独立: ACTIVE identity-bearing = 12 / COMPATIBILITY = 2 / DORMANT = 1 / UNKNOWN = 0
Audit-2: ACTIVE identity-bearing = 12 / COMPATIBILITY = 2 / DORMANT = 1 / UNKNOWN = 0
```

分类一致。无遗漏的第 16 个 caller。

**C-COMPAT 措辞修正（非阻断）**：Audit-2 将 #8 与 #11 列为"2 COMPATIBILITY"。独立代码审查：#8 是 `_report_llm_usage` builder 的 legacy 退路分支（reply_decision_service.py:3811），#11 是 `_embed_with_usage` builder 的 legacy/violation 退路分支（repository.py:507/:516）。两者是**2 个不同 builder 的 legacy 退路**，非 2 个独立 caller。分类标签"2 COMPATIBILITY"在 inventory 行数上准确（2 行），但措辞应明确"2 个 builder 的 legacy None 退路分支"而非"2 个独立 compatibility caller"。这是描述精度修正，非事实错误。

---

## 6. ACTIVE Classification

冻结 ACTIVE 定义：当前正式部署中的业务 API、worker、scheduler、service 能在正常配置下被调用并产生 compute charge。

综合判定（非仅看 import）：

| 维度 | 应用 |
|------|------|
| router registration | main.py:139（proxy）/ :153-155（compute endpoint A）挂载确认 |
| worker/scheduler registration | webhook 入站 / 微信任务回调 / LAS/素材分析 worker 注册 |
| runtime import | 5 个进程内 record_usage + 5 个 ComputeUsageClient.report_usage |
| environment guard | 无 ACTIVE 路径被 env 关闭 |
| feature flag | 无 ACTIVE 路径被 flag 关闭 |
| auth reachability | proxy require_permission / endpoint A X-Internal-Token |
| normal deployment topology | 主 docker-compose.yml 含 9000+9100+postgres（无 9205 compute-service）|

**无当前前端 caller ≠ automatically DORMANT**（F-1 已证明：in-repo caller=0 但 ACTIVE）。Trusted Proxy ACTIVE 分类维持。

---

## 7. Identity Family Model

```
11 identity families / 12 active entry points

Preview identity family（#7）承载 2 个 ACTIVE entry points：
  A. AI Preview（agents.py:311，POST /agents/{id}/preview）
  B. Trusted Reply-Suggestion（douyin_ai_cs_proxy.py:374，POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion）
```

不把 Trusted Proxy 隐藏进"11/11 已完成"而不单列入口。两者共享 `ai_preview_execution:{id}:{stage}` namespace，但分别确认 durable commit timing（§8/§9）。identity family 数=11，ACTIVE entry point 数=12（因 Preview family 有 2 entry）。

---

## 8. Trusted Proxy Re-Audit

### F-1 current chain（独立确认，代码 `cab2e96`）

```
Trusted Proxy（douyin_ai_cs_proxy.py:230，main.py:139 挂载）
  → auth / permission / merchant validation（:234-243）
  → agent binding validation（:245-260）
  → agent active check（:262-272）
  → ★ _create_preview_execution(db, context.merchant_id, agent.agent_id) durable commit（:374）
  → payload["preview_execution_id"] = preview_exec_id（:390，exactly one identity source）
  → 9000→9100 suggest_reply（:393，HTTP，同步 def）
    → 9100 _report_llm_usage Preview 分支（reply_decision_service.py:3807）
    → ai_preview_execution:{preview_execution_id}:{llm_call_stage}
    → ComputeUsageClient → 9000 /internal/compute/usage → record_usage（非空 key，幂等路径）
  → _finalize_preview_execution(completed/failed)
```

### F-1 fail-closed（独立代码核验 :373-390）

```python
try:
    preview_exec_id = _create_preview_execution(db, context.merchant_id, agent.agent_id)
except Exception as exc:
    db.rollback()
    raise HTTPException(status_code=502, detail={"code": "PREVIEW_EXECUTION_CREATE_FAILED", ...})
# execution 创建失败 → raise 502，不 fall through
payload["preview_execution_id"] = preview_exec_id
```

```
F-1 old all-None path = NOT REACHABLE
  handler 必经 _create_preview_execution（fail-closed 不 fall through）
  → payload 必含 preview_execution_id（非空 int PK）
  → 9100 必走 Preview 分支构造非空 identity
  → record_usage 收到非空 idempotency_key → 幂等路径
```

F-1 = RESOLVED，未退化。本审批不重做 F1-PG-1~6 完整 runtime（前序 F-1 实施审批已 RESOLVED + runtime 全 PASS，§9），仅确认 current ACTIVE static path 不能退化为 None——代码核验确认不变式保持。

---

## 9. Preview Shared Identity Family

两个 ACTIVE entry point 分别确认：

| Entry Point | Route | identity source | durable before LLM |
|---|---|---|---|
| AI Preview | `POST /agents/{id}/preview`（agents.py:311）| `_create_preview_execution(db, context.merchant_id, agent_id)` | ✅ commit before suggest_reply（agents.py:308-312 先例）|
| Trusted Reply-Suggestion | `POST /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion`（douyin_ai_cs_proxy.py:374）| `_create_preview_execution(db, context.merchant_id, agent.agent_id)` | ✅ commit before suggest_reply（:374 → :393）|

```
both always establish preview_execution_id before LLM = VERIFIED
```

不因共享 namespace 只检查其中一个入口——两个 entry point 分别确认 durable commit timing。

---

## 10. 11 Consumer Reconciliation

从当前代码（`cab2e96`）重新确认 11 identity family builder 仍存在且 contract 未退化（非引用历史 11/11 checkpoint）：

| # | Consumer | identity contract（当前代码） | builder 存在 | contract 退化? |
|---|---|---|---|---|
| 1 | M04 WeChat Task | `wechat_task:{task.id}:result_usage`（wechat_task_service.py:512）| ✅ | ❌ 无 |
| 2 | M06 LAS Archive | `las_job:{job.id}:archive_usage`（ai_edit_las_service.py:749）| ✅ | ❌ 无 |
| 3 | M01 Auto Reply | `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}`（reply_decision_service.py:3800）| ✅ | ❌ 无 |
| 4 | M02 Webhook Lead | `webhook_event:{event.id}:lead_usage`（douyin_webhook.py:1251）| ✅ | ❌ 无 |
| 5 | M01 Return Visit | `return_visit_run:{return_visit_run_id}:judge`（return_visit_judge_service.py:282）| ✅ | ❌ 无 |
| 6 | M01 Daily Report | `daily_report_generation:{generation_id}:summary`（daily_report_summary_service.py:153）| ✅ | ❌ 无 |
| 7 | M01 AI Preview + Trusted | `ai_preview_execution:{preview_execution_id}:{stage}`（reply_decision_service.py:3810）| ✅ | ❌ 无 |
| 8 | M05 Material Analysis | `material_analysis_execution:{execution_id}:ark_analysis`（material_analysis.py:268）| ✅ | ❌ 无 |
| 9 | M03 Training | `knowledge_training_execution:{execution_id}:ask`（knowledge_training_service.py:556）| ✅ | ❌ 无 |
| 10 | M03 RAG Query | `rag_search_execution:{search_execution_id}:{embedding_stage}`（repository.py:504）| ✅ | ❌ 无 |
| 11 | M03 RAG Ingest | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`（repository.py:501）| ✅ | ❌ 无 |

11/11 identity family 全部存在且 contract 未退化。wrapper 仍透传（§13），missing behavior 未退化（§11）。

---

## 11. Missing Component Audit

逐 builder 确认 identity 组件缺失时的行为（None/空串/空白/字段缺失）：

| Builder | 组件 | 缺失时行为 | fail-closed / unreachable by guard? |
|---|---|---|---|
| Auto Reply | run_id/attempt_count/stage | 前置 `if run_id is not None and attempt_count is not None`（:3790）→ 不构造 key 退 None | ✅ guard，非 sentinel |
| Preview+Trusted | preview_execution_id/stage | 前置 `elif preview_execution_id is not None`（:3807）→ 不构造 key 退 None | ✅ guard |
| RAG Ingest | run_id/document_id/chunk_index | identity matrix `ingest_count==3`（:499）→ 三参全有才构造 | ✅ guard |
| RAG Query | search_execution_id/embedding_stage | identity matrix `query_count==2`（:502）→ 两参全有才构造 | ✅ guard |
| M02 Webhook | event.id | f-string，event PK 已持久化（commit-before-charge）| ✅ unreachable |
| M04 WeChat Task | task.id | f-string，task PK commit+refresh | ✅ unreachable |
| M06 LAS | job.id | f-string，job PK 持久化 | ✅ unreachable |
| M05 Material | execution.id | ternary，execution COMPLETED commit | ✅ unreachable |
| Training | execution_id | ternary，request_id 前置持久化 | ✅ unreachable |
| Daily Report | generation_id | ternary，9000 设置 | ✅ unreachable |
| Return Visit | return_visit_run_id | ternary，9000 设置 | ✅ unreachable |

```
missing component → f-string silently produces sentinel identity → charge = 0
  所有 11 builder 前置 None guard / PK commit-before-charge
  组件缺失时退 None（走 legacy 兼容）或不可达（PK 持久化保证）
  无 silent sentinel charge
```

---

## 12. Partial/Sentinel Audit

搜索 `:None:` / `:null:` / `::` / `:unknown:` / `:missing:` + f-string 插值可能为 None 的变量：

```
f-string 插值 None 变量 = 0
  - ai_auto_reply_run: 前置 if run_id is not None and attempt_count is not None（:3790）
  - ai_preview_execution: 前置 elif preview_execution_id is not None（:3807）
  - rag_embedding: 前置 if ingest_count == 3（:499，保证三参非 None）
  - rag_search_execution: 前置 elif query_count == 2（:502，保证两参非 None）
  - 其余 7 个 ternary/inline family: if X is not None 前置 guard

sentinel 字面量（:None:/:null:/::/:unknown:/:missing:）= 0
  （:: 匹配均为 SQL 类型转换 ::text / IP ::1 / UI 控件类名，无 idempotency_key 内）
getattr(...) or 'unknown' fallback sentinel = 0
  （匹配均为 UI 属性/配置读取，非 identity 构造）
```

```
ACTIVE PARTIAL/SENTINEL = 0
```

---

## 13. Wrapper Propagation

从 consumer builder → wrapper → record_usage 确认无 drop/rename/default override to None：

```
app/services/compute_service.py（re-export shim）
  → from apps.compute.services import record_usage（同一函数对象，无包装/无分支/无 drop）✅

ComputeUsageClient.report_usage（compute_usage_client.py:199）
  → payload["idempotency_key"] = idempotency_key（:260，原样放入 JSON body，None 显式 null 非省略）✅
  → HTTP POST → 9000 /internal/compute/usage

app/routers/compute.py:482（端点 A，主 9000 挂载 main.py:153-155）
  → compute_service.record_usage(idempotency_key=payload.idempotency_key)（透传）✅
```

```
wrapper drop = 0
rename error = 0
default override to None = 0
```

唯一丢 key 点：F-2 端点（`apps/compute/routers.py:362`，未传 `idempotency_key=`）— DORMANT（§17）。

---

## 14. Error/Retry Branches

搜索 except/retry/fallback/finally/failed 分支中"主路径有 key，异常路径用 None"：

```
reply_decision_service._report_llm_usage:
  except Exception（:3830-3831）→ 上报失败不重试，identity 已在 try 前构造完成，未丢失 ✅
  无 retry/fallback 分支覆盖 key 值 ✅

repository._embed_with_usage:
  except Exception（:534-535）→ 仅 warning，identity 未丢失 ✅
  partial/mixed → warning + None（不构造畸形 key，:508-516）✅

material_analysis._report_analysis_usage:
  except Exception（:295-296）→ 仅 warning，identity 未丢失 ✅
  except（:117-126）→ rollback + status=failed，不调 _report_analysis_usage（usage 在 try 内 :106）✅

其余 builder: 无 error/retry 分支覆盖 identity 构造后的 key 值 ✅
```

```
main path has key, error/fallback path uses None = 0
```

### Auto Reply retry（§12 重点）

`retry_combined`（:1236）与 primary（:1160）传同一 `request` 对象 → 同一 run_id/attempt_count → 同 execution；`llm_call_stage` 区分（primary/retry_combined）→ 不同 key → 独立合法 stage 计费。主路径有 key，retry 路径不丢失（复用同一 request）。

---

## 15. Internal Compute Caller Audit

主 9000 `/internal/compute/usage`（端点 A，compute.py:458）全部 ACTIVE callers：

```
唯一 ACTIVE caller = 9100 ComputeUsageClient.report_usage（compute_usage_client.py:262-272）
  → HTTP POST → 9000 端点 A（透传 idempotency_key）
```

所有 9100 side builder 构造非空 key → 端点 A 收到非空 idempotency_key → record_usage 幂等路径。无未列入 11 family/Trusted 入口的新 production caller。

---

## 16. COMPATIBILITY Paths

2 个 legacy None 退路（无 ACTIVE caller 触发）：

### #8 reply_decision_service.py:3811 legacy

- **技术原因**：`_report_llm_usage` 的全 None 分支（run_id/attempt_count/preview_execution_id 均缺席）→ legacy 兼容退 None。
- **无 ACTIVE caller**：Auto Reply 设 run_id+attempt_count（:3790 命中）/ Preview+Trusted 设 preview_execution_id（:3807 命中）→ 全 None 分支不可达。
- **normal deployment 可达性**：不可达——所有 ACTIVE 9100 suggest_reply caller 必经 9000 注入 identity。
- **wrapper 间接进入**：无——identity 在 builder 构造，非 wrapper。
- **legacy fallback**：是，为兼容未知/legacy caller 保留。

### #11 repository.py:507/:516 legacy/violation

- **技术原因**：`_embed_with_usage` 的全 None（:507）或 partial/mixed violation（:516）退 None。
- **无 ACTIVE caller**：Ingest 三参全有（:499 命中）/ Query 两参全有（:502 命中）→ legacy/violation 不可达。
- **normal deployment 可达性**：不可达。
- **legacy fallback**：是，violation guard 显式 warning 不构造畸形 key。

```
COMPATIBILITY / NON-BLOCKING = 2（legacy 退路，无 ACTIVE 触发）
```

---

## 17. F-2

`apps/compute/routers.py:353` `/api/compute/internal/usage`：

| 维度 | 结论 | 证据 |
|---|---|---|
| idempotency_key 透传 | **丢失** ❌ | handler `record_usage(...)`（:362-377）未传 `idempotency_key=` 参数 |
| 主 9000 挂载 | **未挂载** | `app/main.py:20-57` import 无 `apps.compute`；:153-155 只挂 `app/routers/compute.py` |
| 唯一挂载点 | 9205 dev_only | `apps/compute/main.py` → `apps/compute/router.py` |
| production caller | **0** | `packages/clients/compute_client.py` ComputeClient 仅 tests 调用（独立 grep app/ apps/ scripts/ = 0 production import）|

不因"dev-only"就不审——已检查 compose / router inclusion / package imports。主 `docker-compose.yml` 不含 compute-service（9205）；`app/main.py` import 列表无 `apps.compute`。

```
F-2 = DORMANT / NON-BLOCKING
  main 9000 still does not mount ✅
  production import count still 0 ✅
  ComputeClient production caller still 0 ✅
```

未处理（future hardening）。

---

## 18. Core None Compatibility

```
CORE NONE COMPATIBILITY = PRESENT
  record_usage(idempotency_key=None) → 旧兼容裸扣路径仍存在（services.py:772-800，warning record_usage_no_idempotency_key）
  ComputeUsageRequest.idempotency_key: Optional[str] = Field(None)（schemas.py:1404，无 validator 拒绝 None）
```

这本身不阻断 Audit-2。core None 兼容是 COMPATIBILITY CONTRACT（可能服务 legacy/dev/未知 caller），不得未经批准修改 compute core（§23 约束）。

```
Hard requirement:
CURRENT ACTIVE PRODUCTION CALLERS USE NONE = 0
```

所有 ACTIVE caller 构造非空 identity（§4/§5），不触发 core None 路径。

---

## 19. PostgreSQL Ledger Audit

canonical local 只读查询依据 Audit-2 §15（本审批 READ ONLY，未重复查询避免不必要 canonical 交互）：

```
total transactions = 0
consume total = 0
consume NULL keys = 0
consume empty keys = 0
consume whitespace-only keys = 0
malformed key scan（:None:/:null:/::/:unknown:/:missing:）= 0
```

```
CANONICAL LEDGER = NO HISTORICAL RUNTIME EVIDENCE
  （之前所有 runtime 验证 fixture 已 cleanup，无持久 ledger 数据）
  不把 0 行当成主要 PASS 证据 — 本轮以 current code surface completeness 为主要证据
  0 行 ≠ "DB proves no None bug"
```

canonical DB 状态：`revision=0034 / tables=61`（unchanged，§29）。

---

## 20. Historical Runtime Evidence

引用已正式批准/验证的 runtime identity supporting evidence：

| Consumer | PG Verification | Status |
|---|---|---|
| 0032 Daily Report | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | ✅ |
| 0033 M05 Material Analysis | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | ✅ |
| 0034 AI Preview | PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED | ✅ |
| RAG Query 0005 | PG_RUNTIME_VERIFIED | ✅ |
| F-1 Trusted Reply-Suggestion | RESOLVED（F1-PG-1~6 runtime 全 PASS）| ✅ |

Global Audit 本身仍以 **current code surface completeness** 为主要证据（非仅引用历史 runtime）。历史 runtime 是 supporting evidence，非 global discovery completeness 的替代。

---

## 21. Runtime Spot Check Decision

检查 §27 spot check 触发条件：

```
nullable component ambiguity = NO（所有 ACTIVE identity 前置 None guard，§11）
new wrapper = NO（F-1 是新增 entry，但已有 focused test + F1-PG runtime 覆盖）
new branch = NO（F-1 fail-closed 已代码核验 + F1-PG-5 runtime 覆盖）
classification uncertainty = NO（独立枚举与 Audit-2 一致，3 agent 交叉验证）
F-1 current behavior cannot be statically determined = NO（代码 diff 明确，fail-closed 可静态确认）
```

```
NO ADDITIONAL RUNTIME SPOT CHECK REQUIRED
  静态合同已无歧义
  未因"没跑 runtime"夸大证据等级
```

证据等级准确：core code surface = CODE_VERIFIED（独立 Grep + Read 核验），focused tests = STATIC_TEST_VERIFIED，F1-PG runtime = REPORT_VERIFIED（前序），canonical ledger = NO_HISTORICAL_EVIDENCE（0 行，非 PASS 主证据）。

---

## 22. GN2 Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| GN2-0 | Git / baseline | ✅ PASS | HEAD=cab2e96 / clean；F-1 RESOLVED |
| GN2-1 | Global discovery completeness | ✅ PASS | 独立 Grep record_usage/ComputeUsageClient/ComputeClient 覆盖 app/apps/packages，search exhausted，15 call site |
| GN2-2 | ACTIVE classification | ✅ PASS | 12 ACTIVE identity-bearing + 2 COMPATIBILITY legacy None（无 ACTIVE 触发）+ 1 DORMANT F-2 |
| GN2-3 | 11 consumer reconciliation | ✅ PASS | 11/11 identity family 全部存在且 contract 未退化（§10）|
| GN2-4 | Trusted Proxy closure | ✅ PASS | F-1 RESOLVED；old all-None path NOT REACHABLE（handler 必经 _create_preview_execution + fail-closed）|
| GN2-5 | Identity component validity | ✅ PASS | 全部 DB PK / durable commit before charge / 前置 None guard（§11）|
| GN2-6 | Partial/sentinel audit | ✅ PASS | f-string 插值 None=0；sentinel 字面量=0；getattr fallback=0（§12）|
| GN2-7 | Wrapper propagation | ✅ PASS | re-export shim 同函数对象；ComputeUsageClient 透传；端点 A 透传；无 drop/rename/override None |
| GN2-8 | Error/retry branches | ✅ PASS | 无"主路径有 key，异常路径用 None"；except 不覆盖已构造 key |
| GN2-9 | Internal compute caller inventory | ✅ PASS | 唯一 ACTIVE caller = 9100 ComputeUsageClient → 端点 A（透传 key）|
| GN2-10 | F-2 classification | ✅ PASS | DORMANT（主 9000 未挂载，production import=0，丢 key 缺陷仍存在但非 ACTIVE）|
| GN2-11 | Core None compatibility | ✅ PASS | compatibility present；ACTIVE caller transmitting None = 0 |
| GN2-12 | PostgreSQL ledger audit | ✅ PASS | NO HISTORICAL RUNTIME EVIDENCE（0 行，fixture 已 cleanup）；code surface 为主证据 |
| GN2-13 | Historical/runtime evidence | ✅ PASS | 0032/0033/0034/0005/F-1 全 PG_RUNTIME_VERIFIED/RESOLVED |
| GN2-14 | UNKNOWN = 0 | ✅ PASS | 15 call site 全分类（12 ACTIVE + 2 COMPATIBILITY + 1 DORMANT），无 UNKNOWN |
| GN2-15 | Canonical DB no mutation | ✅ PASS | READ ONLY，revision=0034/tables=61 unchanged |

全部核心 Gate PASS。

---

## 23. Global Metrics

```
TOTAL compute-related call sites = 15
ACTIVE entry points = 12
ACTIVE identity-bearing = 12
ACTIVE None = 0
ACTIVE empty = 0
ACTIVE whitespace = 0
ACTIVE partial/sentinel = 0
COMPATIBILITY（legacy None，无 ACTIVE 触发）= 2（2 builder 的 legacy 退路）
DORMANT / DEV_ONLY = 1（F-2）
UNKNOWN active path = 0
UNKNOWN suspicious ledger rows = 0

F-1 old None path unreachable = VERIFIED
F-2 still DORMANT/non-production = VERIFIED
canonical DB unchanged = VERIFIED
```

全部来自审批独立 inventory（§4）。

---

## 24. Recovery Gaps

继续全部保持原分类 OUT_OF_P1 / UNRESOLVED：

```
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

Global Audit 通过 ≠ recovery gaps resolved。7 个 Reliability Gap 继续 OUT_OF_P1。

---

## 25. Naming Debt

```
AIPREVIEWEXECUTION_NAMING_DEBT = NON_BLOCKING
  AiPreviewExecution 承载：AI Preview + Trusted Reply-Suggestion（2 类 ACTIVE entry）
  DOMAIN_MODEL_CONTAMINATION = NOT PRESENT
  NAMING_DEBT = PRESENT / NON_BLOCKING
```

不处理（§35）。不重命名 table/model。

---

## 26. Final Verdict

```
GLOBAL_ACTIVE_NONE_AUDIT = VERIFIED

ACTIVE NONE = 0
ACTIVE EMPTY = 0
ACTIVE WHITESPACE = 0
ACTIVE PARTIAL/SENTINEL = 0
UNKNOWN ACTIVE = 0

F-1 = RESOLVED
F-2 = DORMANT / NON-BLOCKING
CORE NONE COMPATIBILITY = PRESENT / NO ACTIVE CALLER
```

### 为什么是 APPROVED_WITH_CORRECTIONS 而非 APPROVED

核心 Global Audit 独立成立：15 call site 独立枚举一致（差异 0），12 ACTIVE 全 identity-bearing，0 ACTIVE None/Empty/Whitespace/Partial/Sentinel，0 UNKNOWN，F-1 旧路径不可达，F-2 DORMANT，core None 无 ACTIVE caller。无 CHANGES_REQUIRED/FAILED 触发条件。

残留 1 项非阻断 correction：

- **C-COMPAT**：Audit-2 §6 "2 COMPATIBILITY"措辞应明确为"2 个 builder 的 legacy None 退路分支"（#8 `_report_llm_usage` legacy + #11 `_embed_with_usage` legacy/violation），非"2 个独立 compatibility caller"。inventory 行数准确（2 行），但描述精度可改进。这是措辞修正，非事实错误——分类结论（COMPATIBILITY / 无 ACTIVE 触发）正确。

### 为什么不是 FAILED / CHANGES_REQUIRED

逐项核验（§30）：

- 发现第 16 个 ACTIVE caller？❌ 未发现（独立枚举 15，差异 0）
- 某 ACTIVE exception path 仍传 None？❌ 未发生（§14，except 不覆盖 key）
- F-2 实际 production reachable？❌ 未发生（主 9000 未挂载，import=0）
- partial identity 可达？❌ 未发生（identity matrix guard，§12）
- UNKNOWN > 0？❌ 未发生（15 全分类）
- F-1 regression？❌ 未发生（代码核验 fail-closed 保持）

---

## 27. P1 Status

```
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE
Final PostgreSQL Concurrent Closure = AUTHORIZED_TO_START
```

Audit-2 VERIFIED 后，F-1 blocker 与 Global Audit blocker 均解除。TECHNICAL_CLOSURE 推进至 `PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE`。

```
COMPUTE-IDEMPOTENCY-001 != CLOSED
  最后仍需证明：PostgreSQL 真实并发下，同一 Business Event Identity 同时被多个事务竞争时，
  账本与余额仍 exactly-once。
```

---

## 28. Final Concurrent Authorization

```
Final PostgreSQL Concurrent Closure Gate
= AUTHORIZED_TO_START
```

前置条件全部满足：
- F-1 implementation approved ✅
- Global Active None Audit RE-RUN independently APPROVED/VERIFIED ✅

方可开始 Final PostgreSQL Concurrent Closure（证明并发下 exactly-once）。

---

## 29. Canonical DB No-Drift

```
canonical local PG = unchanged
  revision = 0034
  tables = 61
  本审批 READ ONLY，未 mutation
```

---

## 30. Hard Approval Criteria

逐项核验：

```
all ACTIVE charge entry points discovered         ✅（15 call site，search exhausted）
all ACTIVE paths identity-bearing                 ✅（12/12 ACTIVE）
ACTIVE None = 0                                   ✅
ACTIVE Empty = 0                                  ✅
ACTIVE Whitespace = 0                             ✅
ACTIVE Partial/Sentinel = 0                       ✅
UNKNOWN = 0                                       ✅
F-1 old path unreachable                          ✅（fail-closed 不 fall through）
F-2 DORMANT                                       ✅（主 9000 未挂载，import=0）
core None compatibility has no ACTIVE caller      ✅（12 ACTIVE 全非空 identity）
canonical DB unchanged                            ✅（READ ONLY，0034/61）
```

全部成立 → APPROVED。

---

## 31. Commit Authorization

授权做一次 Global Audit-2 closure governance commit。允许文件：

```
docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT_2.md
docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT_2_APPROVAL.md
CLAUDE.md
docs/ai/05_PROJECT_CONTEXT.md
```

状态变更（commit 时同步）：

```
GLOBAL_ACTIVE_NONE_AUDIT: COMPLETE_PENDING_APPROVAL → VERIFIED
TECHNICAL_CLOSURE: PENDING_GLOBAL_AUDIT_APPROVAL → PENDING_FINAL_POSTGRESQL_CONCURRENT_CLOSURE
Final PostgreSQL Concurrent Closure: BLOCKED_PENDING_GLOBAL_AUDIT_APPROVAL → AUTHORIZED_TO_START
```

不得包含任何业务代码。建议 commit message：

```
审计：闭环全局Active算力幂等身份
```

```
DO NOT PUSH
```

---

## 32. 边界遵守确认

- ✅ 未修改业务代码（本审批唯一新增产物为本 APPROVAL.md）
- ✅ 未 commit、未 push
- ✅ 未改 migration / canonical DB / compute core / 9100 / F-2 / recovery gaps
- ✅ 未 start Final Concurrent Closure / harden compute core / fix F-2 / rename AiPreviewExecution / RB-10 / declare P1 closed
- ✅ 独立从代码重新枚举（Grep + Read），未采信 Audit-2 inventory 作为答案
- ✅ canonical DB 未 mutation（READ ONLY，revision=0034/tables=61）

---

## 33. 完成后停止

本审批窗口完成后停止。不得自行：

- start Final Concurrent Closure
- 修改业务代码
- harden compute core
- 修 F-2
- 处理 recovery gaps
- rename AiPreviewExecution
- RB-10
- push
- 宣布 P1 CLOSED

---

## 附录：审批纪律确认

- READ ONLY：未改业务代码（本审批唯一新增产物为本 APPROVAL.md）。
- 未 commit、未 push（commit 授权留给 Global Audit-2 closure，§31）。
- 未执行 runtime probe（静态合同无歧义，§21；证据等级准确标注，未夸大）。
- 独立复现：Grep `record_usage(`/`ComputeUsageClient`/`ComputeClient` 覆盖 app/apps/packages（15 call site）、Read F-1 closure 代码 / F-2 handler / RAG identity matrix / main.py 挂载 / ComputeClient import / ComputeUsageRequest schema / record_usage legacy 路径。
- 未采信执行窗口自述：所有核心结论经独立 Grep + Read 核验。
```
