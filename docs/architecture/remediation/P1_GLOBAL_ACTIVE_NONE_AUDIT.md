# P1 GLOBAL ACTIVE NONE AUDIT — 全局 ACTIVE Compute Idempotency Identity 审计

> 状态：`FAILED`（发现真正 ACTIVE None 路径，依 §40 停止，不自修，提交独立返工审批）
> 审计窗口：`P1-GLOBAL-ACTIVE-NONE-AUDIT-1`
> Git baseline：`eea9824`
> 审计日期：2026-08-11
> 性质：READ ONLY AUDIT（未改业务代码、未改迁移、未写 canonical DB、未 commit）

---

## 1. Baseline

- Git checkpoint：`eea9824`
- 正式基线：11/11 Consumer Migration = COMPLETE；0032/0033/0034/0005 = PG_RUNTIME_VERIFIED；APPLICATION_ROLE_PERMISSION_GAP = RESOLVED；FRESH_BOOTSTRAP_PRINCIPAL_REPRODUCIBILITY = VERIFIED。
- P1 仍 OPEN：`COMPUTE-IDEMPOTENCY-001 = OPEN`；`TECHNICAL_CLOSURE = PENDING`。
- RB-10：NOT AUTHORIZED。

---

## 2. Audit Definition

证明：所有当前仍可能在正常业务运行中产生 compute charge 的 ACTIVE consumer 路径，都必须生成稳定、非空 Business Event Identity；不存在 ACTIVE 路径以 `None` / 空串 / whitespace / 缺失字段 / 默认 fallback 绕过 idempotency contract。

三层证据：
- Layer A：ACTIVE charge surface 枚举。
- Layer B：code-path identity construction / propagation。
- Layer C：runtime / PostgreSQL ledger evidence。

---

## 3. Global Compute Call-Site Discovery Method

多维度静态搜索（Grep，覆盖 `app/`、`apps/`、`scripts/`、routers、services、clients、worker、scheduler，排除 tests/docs 为 ACTIVE 判定，但参考理解）：
`record_usage(`、`.report_usage(`、`ComputeUsageClient`、`report_usage`、`/compute/usage`、`/internal/compute/usage`、`idempotency_key`、`compute_usage`/`compute_charge`/`charge_usage`、`ComputeUsageRequest`、`idempotency`、`compute_service`。

核心唯一事实源：`apps/compute/services.py:615 def record_usage`。两条汇入路径：
- 路径 A（9100→9000 HTTP）：9100 服务辅助函数 → `ComputeUsageClient().report_usage` → `POST /internal/compute/usage`（`app/routers/compute.py:459`）→ `record_usage`。
- 路径 B（9000 进程内）：`app/*` 服务 `from app.services.compute_service import record_usage as _record_usage`（re-export shim）→ `record_usage`。

---

## 4. Complete Call-Site Inventory

| # | Call Site | Module | Consumer | Runtime Status | Identity Source | None Possible? | Classification |
|---|-----------|--------|----------|----------------|-----------------|----------------|----------------|
| 1 | `app/services/wechat_task_service.py:512` | M04 | WeChat Task | ACTIVE（生产挂载，commit 后调用 :430/:462） | `f"wechat_task:{task.id}:result_usage"` | 否（task.id PK，commit-before-charge） | ACTIVE |
| 2 | `app/services/ai_edit_las_service.py:749` | M06 | LAS Archive | ACTIVE（:186 `if archived:` 后） | `f"las_job:{job.id}:archive_usage"` | 否（job.id PK，commit-before-charge） | ACTIVE |
| 3 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py:3800` | M01 | Auto Reply | ACTIVE（:1160/:1236 primary+retry_combined） | `f"ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}"` | 否（9000 `ai_auto_reply_dry_run_service.py:359-360` 设 run.id+attempt_count，commit-before-9100-call） | ACTIVE |
| 4 | `app/integrations/douyin_webhook.py:1251` | M02 | Webhook Lead | ACTIVE（webhook 处理流） | `f"webhook_event:{event.id}:lead_usage"` | 否（event.id PK，已持久化） | ACTIVE |
| 5 | `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py:281` | Phase9 | Return Visit | ACTIVE（:328） | `f"return_visit_run:{return_visit_run_id}:judge"` | 否（9000 `return_visit_run_service.py:702` 设 run.id，claim 前 commit） | ACTIVE |
| 6 | `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:152` | M03 | Daily Report | ACTIVE（:207-208，0032 PG_RUNTIME_VERIFIED） | `f"daily_report_generation:{report_generation_id}:summary"` | 否（9000 `daily_report_job_service.py:383` 透传 generation_id） | ACTIVE |
| 7 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py:3810` | M01 | AI Preview | ACTIVE（agents.py:315，0034 PG_RUNTIME_VERIFIED） | `f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"` | 否（9000 `app/routers/agents.py:311-312` `_create_preview_execution` durable commit 后透传） | ACTIVE |
| 8 | `app/services/material_analysis.py:267` | M05 | M05 Material Analysis | ACTIVE（:106，0033 PG_RUNTIME_VERIFIED） | `f"material_analysis_execution:{execution_id}:ark_analysis"` | 否（execution.id，C1 commit-before-charge :102→:106） | ACTIVE |
| 9 | `apps/xg_douyin_ai_cs/services/knowledge_training_service.py:555` | M03 | Training | ACTIVE（:621） | `f"knowledge_training_execution:{execution_id}:ask"` | 否（execution_id=request_id，前置持久化） | ACTIVE |
| 10 | `apps/xg_douyin_ai_cs/rag/repository.py:504` | M03 | RAG Query | ACTIVE（:1152 primary / :1275 fallback，0005 PG_RUNTIME_VERIFIED） | `f"rag_search_execution:{search_execution_id}:{embedding_stage}"` | 否（`_create_search_execution` INSERT...RETURNING + commit :1063-1081；primary/fallback_embedding 双 stage 非空） | ACTIVE |
| 11 | `apps/xg_douyin_ai_cs/rag/repository.py:501` | M03 | RAG Ingest | ACTIVE（train_document :592 / train_scope :753） | `f"rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest"` | 否（run_id 透传；document_id=doc["id"] 持久化；chunk_index=enumerate≥1） | ACTIVE |
| **12** | **`app/routers/douyin_ai_cs_proxy.py:365`（→ 9100 `_report_llm_usage` :1160）** | **M03 proxy** | **Trusted Reply-Suggestion Proxy** | **ACTIVE（生产挂载 main.py:139，鉴权+权限门禁）** | **payload 不设 run_id/attempt_count/preview_execution_id → 9100 全 None → `idempotency_key=None`** | **是 ★ FAILED 根因** | **ACTIVE / None-bearing** |
| 13 | `app/routers/compute.py:482`（HTTP 入口 `/internal/compute/usage`） | M07 | ComputeUsageClient 目标 | ACTIVE（9100 HTTP 上报唯一目标） | 透传 `payload.idempotency_key` | 否（透传不丢） | ACTIVE（传输层，非独立 consumer） |
| 14 | `apps/compute/routers.py:362`（`/api/compute/internal/usage`） | M07 dev_only | （无生产 caller） | dev_only（`apps.compute.main:app` @9205，RUNTIME_ENTRYPOINTS 标 `dev_only`） | handler **未透传** idempotency_key | 是（若被调用） | DORMANT（dev_only，主 9000 app 不挂载） |
| 15 | `packages/clients/compute_client.py:114` `ComputeClient.report_usage` | legacy | （无生产 import） | TEST_ONLY（仅 `tests/test_compute_client.py` 引用） | 不支持 idempotency_key 参数 | 是（若被调用） | TEST_ONLY / LEGACY |

> 注：`app/services/return_visit_run_service.py` 的 `idempotency_key`（sha256 指纹）与 `app/routers/health.py:44` 的列名清单，是 ReturnVisitRun **run 级去重键**与 readiness 检查，**非 compute charge identity**，不计入 charge surface。

---

## 5. ACTIVE / Non-ACTIVE Classification

- **ACTIVE（#1–#13）**：当前正式业务入口、worker、scheduler、service 或 API，在正常部署中可达并产生 compute charge。
- **#12 为 None-bearing ACTIVE**：见 §18 Finding F-1。
- **DORMANT（#14）**：`apps/compute/routers.py` 的 `/internal/usage` 路由仅在 dev_only 的 compute-service（9205，"能力中心"）中挂载；主 9000 生产 app（`app/main.py`）挂载的是 `app.routers.compute.{router,admin_router,internal_router}`，其中 `/internal/compute/usage`（#13）正确透传 idempotency_key。#14 的 handler 丢失 idempotency_key 是 latent bug，但无生产 caller。
- **TEST_ONLY / LEGACY（#15）**：`packages/clients/compute_client.py` `ComputeClient` 仅被 `tests/test_compute_client.py` 引用，生产代码无 import，且 `report_usage` 签名不含 idempotency_key。

---

## 6. 11 Consumer Reconciliation

冻结的 11 条 charge path 与当前代码逐一核对，identity 构造点与冻结 contract 一致：

| # | 冻结 identity | 代码位置 | 一致性 |
|---|---------------|----------|--------|
| 1 | `wechat_task:{task.id}:result_usage` | wechat_task_service.py:512 | ✅ |
| 2 | `las_job:{job.id}:archive_usage` | ai_edit_las_service.py:749 | ✅ |
| 3 | `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}` | reply_decision_service.py:3800 | ✅ |
| 4 | `webhook_event:{event.id}:lead_usage` | douyin_webhook.py:1251 | ✅ |
| 5 | `return_visit_run:{run_id}:judge` | return_visit_judge_service.py:281 | ✅ |
| 6 | `daily_report_generation:{generation_id}:summary` | daily_report_summary_service.py:152 | ✅ |
| 7 | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}` | reply_decision_service.py:3810 | ✅ |
| 8 | `material_analysis_execution:{execution_id}:ark_analysis` | material_analysis.py:267 | ✅ |
| 9 | `knowledge_training_execution:{execution_id}:ask` | knowledge_training_service.py:555 | ✅ |
| 10 | `rag_search_execution:{execution_id}:{embedding_stage}` | repository.py:504 | ✅ |
| 11 | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | repository.py:501 | ✅ |

11/11 一致。**但 11 条枚举遗漏了第 12 条 ACTIVE 路径**（Trusted Reply-Suggestion Proxy），该路径不在冻结 11 条表内，却产生 compute charge。

---

## 7. Core API None Compatibility

`apps/compute/services.py:record_usage`（:615）：

1. `idempotency_key: str | None = None`（:631）——签名允许 None。✅ 允许
2. 默认值 `None`。
3. 空串 `""`：:681 `if idempotency_key:` falsy → 跳过幂等块；:772 `if idempotency_key is None:` False → 不打 warning → 直接 legacy 裸扣（**静默**，连 warning 都没有）。
4. whitespace：:681 truthy → 进入幂等块 → :682 `str(...).strip()` → 变空串 → 仍以空串 INSERT（partial/empty identity 风险，但无 ACTIVE consumer 产生 whitespace-only key）。
5. core 遇无 identity：走 :771-800 legacy 路径，**裸扣 + 写 `idempotency_key=NULL` 的 ComputeTransaction**（仅 `is None` 时打 warning）。
6. fallback：存在"为兼容旧调用方，无 key 时继续记账"的 legacy 路径（:771-800）。

**CORE NONE COMPATIBILITY：PRESENT**（core 技术上仍兼容 `None`/空串，走 legacy 裸扣）。属 COMPATIBILITY CONTRACT（P1 阶段 1 可选语义），未自行删除（依 §36/§37，不擅自 harden core API；future hardening opportunity）。

---

## 8. Identity Builder Audit

### 8.1 9100 共享 builder `_report_llm_usage`（reply_decision_service.py:3763-3831）
- identity 三态：`run_id+attempt_count`（Auto Reply）/ `preview_execution_id`（Preview）/ 全 None（legacy）。
- partial（一有一无）/ mixed（Auto Reply+Preview 同时）→ warning + **不构造畸形 key，退 None**（:3801-3806, :3792-3798）。
- **关键**：全 None 分支（:3811）→ `idempotency_key=None` → 经 `ComputeUsageClient.report_usage` → core legacy 裸扣。该分支由 **#12 proxy 路径**在 ACTIVE 运行中命中（见 §18 F-1）。

### 8.2 9100 共享 builder `_embed_with_usage`（repository.py:469-536）
- identity matrix 严格互斥：Ingest 三参全+Query 缺席 → Ingest key；Query 双参全+Ingest 缺席 → Query key；全缺席 → legacy None；partial/mixed → warning + None（:494-516）。
- RAG Query 复用 embedding 时 `_search_sqlite:1270 if query_embedding is None:` 才调 embed → 复用路径不计费，无 None-key 风险；re-embed 路径 `embedding_stage="fallback_embedding"` → 有效 key。
- None 分支仅在 partial/mixed/legacy 命中；ACTIVE Ingest/Query 路径组件恒全（见 §9）。

### 8.3 9000 侧直接 builder（#1/#2/#4/#8）
- 内联 f-string，identity = 持久化 PK（task.id/job.id/event.id/execution.id），commit-before-charge。无 None 可能。

### 8.4 9100 侧条件 builder（#5/#6/#9）
- `if X is not None: key else None`。X = 9000 透传的持久化 PK（run.id/generation_id/execution_id）。9000 侧 commit-before-9100-call 保证非空（见 §9）。

---

## 9. Missing Component Audit

逐 consumer 证明 ACTIVE 路径 identity 组件必然非空（None 回退不可达）：

| Consumer | identity 组件 | 持久化时点证据 | None 回退可达性 |
|----------|---------------|----------------|-----------------|
| #1 WeChat Task | task.id | :422/:454 `db.commit()`+`refresh` 后调 :430/:462 | 不可达 |
| #2 LAS | job.id | :184 `db.commit()` 后 `if archived:` 调 :186 | 不可达 |
| #3 Auto Reply | run_id, attempt_count | `ai_auto_reply_dry_run_service.py:380 _add_run`（commit）→ :388 suggest_reply；:359-360 透传 | 不可达（9000 必设） |
| #4 Webhook | event.id | webhook event 入站已持久化 | 不可达 |
| #5 Return Visit | return_visit_run_id | `return_visit_run_service.py:702 return_visit_run_id=run.id`（claim 前 commit） | 不可达（9000 必设） |
| #6 Daily Report | report_generation_id | `daily_report_job_service.py:383`（generation_id 持久化） | 不可达（9000 必设） |
| #7 Preview | preview_execution_id | `agents.py:311 _create_preview_execution`（durable commit）→ :312 透传→:315 suggest_reply | 不可达（PV-0） |
| #8 M05 | execution.id | :102 `db.commit()`（execution COMPLETED）→ :106 | 不可达 |
| #9 Training | execution_id(request_id) | `knowledge_training_service.py:175 execution_id=request_id`（前置持久化）→ :621 | 不可达 |
| #10 RAG Query | search_execution_id | `repository.py:929 _create_search_execution`（INSERT...RETURNING + commit :1080）→ :1152 | 不可达 |
| #11 RAG Ingest | run_id, document_id, chunk_index | :592/:753 三参透传（doc["id"] 持久化；chunk_index=enumerate≥1） | 不可达 |
| **#12 Proxy** | **（无）** | **payload :316-362 不含任何 identity 字段** | **可达 ★ ACTIVE None** |

---

## 10. Wrapper Propagation

- **re-export shim** `app/services/compute_service.py`：整文件 `from apps.compute.services import (...)` 透传，**不丢/不改/不重命名** idempotency_key。✅
- **ComputeUsageClient.report_usage**（compute_usage_client.py:199-260）：`payload["idempotency_key"] = idempotency_key`（:260）原样放入 HTTP body。✅
- **HTTP 入口 `/internal/compute/usage`**（app/routers/compute.py:459-483）：`idempotency_key=payload.idempotency_key`（:482）透传到 record_usage。✅
- ⚠️ **HTTP 入口 `/api/compute/internal/usage`**（apps/compute/routers.py:353-393）：handler 调 record_usage **未传 `idempotency_key=`**（对比 :482）→ 丢弃。仅 dev_only，无生产 caller（DORMANT，见 §18 F-2）。

---

## 11. Error / Retry Paths

- 各 `_report_*` / `_report_llm_usage` / `_embed_with_usage` 的 `except Exception`（:3830, :534, :173, :302, :576, :295, :514, :1253）**仅记日志，不再调用 report_usage**，无"异常路径补一次 None 上报"。✅
- record_usage 自身 `IntegrityError` 路径（:728-769）：以**同一** idempotency_key 重查 existing（:737），无 None 降级。✅
- ⚠️ `reply_decision_service.py:1236` retry_combined 分支：复用同一 `request`（同一 run_id+attempt_count），但 `llm_call_stage="retry_combined"` → 产生**不同 key**（`...:retry_combined`）→ 这是冻结 contract 的合法"不同 business event"，非 None。✅

---

## 12. Internal Compute Caller Inventory

`/internal/compute/usage`（#13）的所有 ACTIVE caller = 9100 `ComputeUsageClient.report_usage` 的 5 个 builder（#3/#5/#6/#7/#9/#10/#11）。这些 builder 的 identity 行为已在 §8/§9 审计。

唯一新增的 internal compute caller 风险：**#12 proxy 路径**——它不直接调 record_usage，而是经 `suggest_reply` → 9100 `_report_llm_usage`（全 None identity）→ ComputeUsageClient → #13 → record_usage(None)。这是"第 12 个真实计费调用点"，不在历史 11/11 表内。

---

## 13. PostgreSQL Ledger Audit（canonical local `auto_wechat`）

只读查询 `compute_transactions`（docker exec psql，纯 SELECT）：

| metric | value |
|--------|-------|
| total_all_txns | 0 |
| total_consume_txns | 0 |
| idempotency_key IS NULL | 0 |
| idempotency_key = '' | 0 |
| btrim(idempotency_key) = '' | 0 |
| consume_with_NULL_key | 0 |
| partial_None_token / null / unknown / missing | 0 |
| double_separator `::` / leading/trailing `:` | 0 |

schema 确认：`idempotency_key` varchar(255) `nullable=YES`；unique constraint `uk_compute_transactions_merchant_idempotency` 存在。

**canonical 本地库 ledger 为空（0 行）**：开发库未跑过计费业务。实质性 runtime identity 证据为此前独立隔离库验证（0032/0033/0034/0005 = PG_RUNTIME_VERIFIED，各自 fixture 范围 0 null/empty）。

---

## 14. Historical vs Current Rows

- canonical 本地 `auto_wechat` ledger：0 行 → 无历史、无当前。
- HISTORICAL_NONE_ROWS = 0；CURRENT_ACTIVE_NONE_ROWS = 0（本库内）。
- 注意：#12 路径若在生产被调用，将**新增** `idempotency_key=NULL` 的 CURRENT ACTIVE 行——这是 FAILED 的运行时投射，未在本库观测仅因本库未跑该业务。

---

## 15. Partial / Sentinel Identity Audit

- ACTIVE consumer 的 identity 均为 `f"{namespace}:{persisted_PK}:{stage}"` 形式，组件来自 DB PK（int）或固定 stage 字面量，f-string 不会把 `None` 拼成 `"None"` 字面量，因为：
  - 9000 直接 builder（#1/#2/#4/#8）：组件为 PK，commit 前已非空。
  - 9100 条件 builder（#3/#5/#6/#7/#9/#10/#11）：`if X is not None:` 守卫确保 None 时不构造 key（退 None 而非拼 `"None"`）。
- 全局 ledger partial/sentinel 扫描（`%:None:%`/`%:null:%`/`%unknown%`/`%::%`/`:%`/`%:`）= 0 行（§13）。
- **结论**：无 ACTIVE 路径产生 partial/sentinel identity 字符串。唯一风险形态是"全 None → 空退 None → core 裸扣 NULL"，即 #12。

---

## 16. Runtime Spot Checks

- #6/#7/#8/#10 已有独立 PG runtime 验证（0032/0033/0034/0005 = PG_RUNTIME_VERIFIED，identity NOT NULL/NOT EMPTY，0 null/empty）。
- #12 未做 PG runtime 验证；静态审计已足以判定其为 ACTIVE None 路径，**无需 spot check 即已 FAILED**（§40 命中即停）。
- 其余 ACTIVE consumer（#1/#2/#3/#4/#5/#9/#11）静态证明链完整（commit-before-charge + 持久化 PK），与已验证 consumer 同模式。

---

## 17. GN-0 ~ GN-14

| Gate | 项 | 结果 | 说明 |
|------|-----|------|------|
| GN-0 | Git / baseline | PASS | `eea9824` |
| GN-1 | Global charge call-site inventory | PASS | 15 entry 枚举完成（11 ACTIVE consumer + #12 None ACTIVE + #13 传输层 + #14 dev_only + #15 test_only） |
| GN-2 | ACTIVE classification completeness | **FAIL** | #12 被判 ACTIVE None-bearing；#14/#15 非 ACTIVE 已举证 |
| GN-3 | 11 migrated consumer reconciliation | PASS | 11/11 identity 与冻结 contract 一致 |
| GN-4 | Identity builder audit | PASS（11 条） | builder 位置/组件/stability 确认；#12 无 builder |
| GN-5 | Missing-component behavior | **FAIL** | #12 无 identity 组件，ACTIVE 路径缺失 |
| GN-6 | Wrapper propagation | PARTIAL | shim/ComputeUsageClient/#13 透传 OK；#14 handler 丢 key（dev_only） |
| GN-7 | Error/retry path audit | PASS | except 仅日志，无 None 补报；retry_combined 不同 key 合法 |
| GN-8 | Internal compute caller audit | **FAIL** | 发现 #12 为第 12 个 ACTIVE caller（经 9100 间接到 core，None） |
| GN-9 | PostgreSQL NULL/empty ledger audit | PASS | canonical 本地库 0 行；0 null/empty |
| GN-10 | Partial/sentinel ledger audit | PASS | 0 行 |
| GN-11 | Runtime spot checks | N/A | #12 静态已 FAIL，无需 spot check；0032/0033/0034/0005 已 PG_RUNTIME_VERIFIED |
| GN-12 | Historical/current classification | PASS | 本库 0 行；#12 投射风险记录 |
| GN-13 | Unknown count = 0 | **FAIL** | #12 classification = ACTIVE（或保守为 UNKNOWN——无法证明 inactive），>0 |
| GN-14 | Canonical DB no mutation | PASS | 全程只读 SELECT，未改 DB |

---

## 18. Findings

### ★ F-1（FAILED 根因）：Trusted Reply-Suggestion Proxy 是 ACTIVE None 计费路径

- **module / call site**：`app/routers/douyin_ai_cs_proxy.py:230` 路由 `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`，handler `create_reply_suggestion_proxy`（:231），`suggest_reply` 调用点 :365。
- **runtime reachability**：`app/main.py:139 app.include_router(douyin_ai_cs_proxy.router)` 生产挂载；`Depends(get_request_context_required)` + `require_permission("auto_wechat:douyin_ai_cs")`（:234, :238）鉴权可达。
- **production-intended**：handler docstring "由 9000 注入可信商户上下文后调用 9100 生成回复建议"；前端 `frontend/src/api/douyinAiCsClient.ts:757` 注释 "正式商户侧工作台必须使用 getTrustedReplySuggestion 走 9000 可信代理"。
- **identity argument**：payload（:316-362）**不含** `run_id` / `attempt_count` / `preview_execution_id`。对比 `agents.py:312` 的 Preview 路径（设 preview_execution_id，0034 已验证）。
- **missing component**：全部三个 identity 字段缺失。
- **expected contract**：ACTIVE consumer 必须生成稳定非空 Business Event Identity；该路由应复用 `ai_preview_execution` namespace（或独立 namespace）并在 9100 call 前 durable commit execution id。
- **runtime 投射**：9100 `_report_llm_usage`（reply_decision_service.py:3786-3811）读 `getattr(request, "run_id"/"attempt_count"/"preview_execution_id", None)` 全 None → `idempotency_key=None`（:3811）→ `ComputeUsageClient().report_usage(idempotency_key=None)`（:3828）→ `app/routers/compute.py:482` → `record_usage(idempotency_key=None)`（:631）→ :771-800 legacy 裸扣 → 写 `idempotency_key=NULL` 的 ComputeTransaction。
- **current caller 状态**：`getTrustedReplySuggestion` 在 `frontend/src` 仅定义+re-export（`douyinAiCsClient.ts:766`、`features/douyin-cs/api.ts:17`），**无组件实际调用**（`getTrustedReplySuggestion(` 调用点 0 处）。但路由本身注册、鉴权、生产挂载、文档标注为正式路径，满足 §7 "API 能够在正常部署中到达并产生 compute charge"。依 §3/§8，"无当前 caller"不能证明 inactive（UNKNOWN 不得静默排除）。
- **exact remediation needed（不由本窗口实施）**：
  1. 在 `douyin_ai_cs_proxy.py` handler 内、`suggest_reply` 调用前，创建 durable PreviewExecution（或复用既有 `ai_preview_execution` 命名空间），将 `preview_execution_id` 注入 payload；**或**
  2. 若该路由属"会话预览"语义，统一归入 `ai_preview_execution` namespace，与 `agents.py` 共用 `_create_preview_execution`；
  3. 若该路由实为非计费路径，需在 9100 侧 `_report_llm_usage` 增加显式 skip 条件（需独立设计，不属本窗口）；
  4. 补该路径的 PG consumer verification（类 0034）。
- **verdict impact**：依 §40，发现真正 ACTIVE None 路径 → `GLOBAL_ACTIVE_NONE_AUDIT = FAILED` → STOP → 不自修 → 提交独立返工设计/批准。

### F-2（DORMANT，记录不阻断）：dev_only `/api/compute/internal/usage` 丢 idempotency_key

- **call site**：`apps/compute/routers.py:353-393`，handler `report_usage` 调 `compute_service.record_usage(...)` 未传 `idempotency_key=payload.idempotency_key`（对比 `app/routers/compute.py:482`）。
- **runtime reachability**：仅 `apps.compute.main:app`（@9205 compute-service，`RUNTIME_ENTRYPOINTS.md` 标 `dev_only`）挂载；主 9000 生产 app 不挂载该路由。
- **caller**：唯一潜在 client `packages/clients/compute_client.py` `ComputeClient.report_usage`（:114，POST `/api/compute/internal/usage`，签名无 idempotency_key）——生产代码无 import，仅 `tests/test_compute_client.py` 引用。
- **classification**：DORMANT（dev_only + test-only client）。
- **future hardening**：若 compute-service 转生产，须先补 idempotency_key 透传 + ComputeClient 签名；属 future governance，不属本 P1 ACTIVE closure。

---

## 19. Out-of-P1 Gaps

保持原分类，**不因本审计关闭**：

```
DAILY_REPORT_REQUEST_RECOVERY_GAP
TRAINING_REQUEST_RECOVERY_GAP
RAG_INGEST_RUN_RECOVERY_GAP
RAG_INGEST_REQUEST_RECOVERY_GAP
M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP
PREVIEW_REQUEST_RECOVERY_GAP
RAG_QUERY_REQUEST_RECOVERY_GAP
```

另：9100 `xg_douyin_ai_cs` runtime principal 权限较宽 = FUTURE GOVERNANCE GAP，不属本审计。

---

## 20. Verdict

```
GLOBAL ACTIVE NONE AUDIT = FAILED

理由：发现真正 ACTIVE None 计费路径（F-1）。
  - app/routers/douyin_ai_cs_proxy.py:230 trusted reply-suggestion proxy
  - 生产挂载（main.py:139）、鉴权可达、文档标注正式路径
  - payload 不含 identity → 9100 全 None → idempotency_key=None → core legacy 裸扣 → idempotency_key=NULL ComputeTransaction

ACTIVE COMPUTE CALLERS:
  11 IDENTITY-BEARING（#1–#11）
  1 NONE-BEARING ACTIVE（#12 proxy）★

ACTIVE NONE / EMPTY / PARTIAL IDENTITY:
  1（#12）

UNKNOWN ACTIVE CALLERS:
  0（#12 已判 ACTIVE；#14/#15 已判 DORMANT/TEST_ONLY 并举证）
```

依 §40/§42，本窗口不得自行修复，不得宣称 `VERIFIED`，不得开始 Final Concurrent Closure。提交独立返工设计/批准。

---

## 21. P1 Remaining

`COMPUTE-IDEMPOTENCY-001 = OPEN`；`TECHNICAL_CLOSURE = PENDING`。

本审计 FAILED 后，须先：
1. 独立返工 F-1（Trusted Reply-Suggestion Proxy identity 迁移），经设计/批准/实施/PG 验证；
2. 重跑 Global Active None Audit（或其增量）确认 ACTIVE None = 0；
3. 通过后方可进入 Final PostgreSQL Concurrent Closure Gate。

---

## 附录：审计纪律确认

- NO BUSINESS CODE CHANGE：未改任何业务代码。
- NO MIGRATION CHANGE：未改迁移。
- READ ONLY AUDIT：canonical DB 仅 `SELECT`，未删/backfill/改 ledger/改 balance。
- 未 commit、未 push、未宣布 P1 Closed、未启动 RB-10、未启动 Final Concurrent Closure。
- 本文件为唯一新增产物（`docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT.md`）。
