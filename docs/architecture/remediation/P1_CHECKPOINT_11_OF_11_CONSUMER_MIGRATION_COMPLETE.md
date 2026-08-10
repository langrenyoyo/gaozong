# P1 COMPUTE-IDEMPOTENCY-001 — Consumer Migration Complete 里程碑检查点（11/11）

> 冻结日期：2026-08-10
> 检查点提交：`67eb1f9`（HEAD，已推送 origin/master）
> tag：`p1-checkpoint-11-of-11-consumer-migration-complete`
> 状态：**CONSUMER_MIGRATION=COMPLETE / TECHNICAL_CLOSURE=PENDING**
> COMPUTE-IDEMPOTENCY-001：仍 OPEN
> ★ Consumer Migration Complete ≠ Technical Closure Complete（≠ E2E_VERIFIED_FIXED）

---

## Charge Path Matrix（11/11 MIGRATED / 0 OPEN）

| # | Charge Path | Commit | identity contract | Evidence Level | PG Verification |
|---|---|---|---|---|---|
| 1 | M04 WeChat Task | `8c73b1e` | `wechat_task:{task.id}:result_usage` | E2E_VERIFIED_FIXED_FOR_M04 | M07 PG Core Gate PASS |
| 2 | M06 LAS Archive | `7845e26` | `las_job:{job.id}:archive_usage` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 3 | M01 Auto Reply | `7b2b6d7` | `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 4 | M02 Webhook Lead | `06fb4f2` | `webhook_event:{event.id}:lead_usage` | MIGRATED | M07 PG Core Gate PASS |
| 5 | Return Visit Judge | `01a60c1` | `return_visit_run:{run_id}:judge` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 6 | Daily Report Summary | `91afaef` | `daily_report_generation:{generation_id}:summary` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（7 Gate 实跑）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0032 待 DB-BL-2）|
| 7 | Training Knowledge | `cb14ff9` | `knowledge_training_execution:{execution_id}:ask` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（TR-1~3/6 实跑，TR-4/5 CODE_VERIFIED）| **PG_VERIFIED_MIDPOINT**（0004）|
| 8 | RAG Ingest Chunk Embedding | `0fee74a` | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（RI-1~5 实跑，RI-0/6B PG 运行证据）| **PG_VERIFIED_MIDPOINT**（事务边界）|
| 9 | M05 Material Analysis | `fe91a05` | `material_analysis_execution:{execution_id}:ark_analysis` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（MA-1/2/3/6 实跑，MA-0/4/5 CODE_VERIFIED）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0033 待 DB-BL-2）|
| 10 | M01 Preview | `3eddc84` | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（PV-1~4 实跑，PV-0/5 CODE_VERIFIED）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0034 待 DB-BL-2）|
| 11 | RAG Query Embedding | `67eb1f9` | `rag_search_execution:{search_execution_id}:{embedding_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（RQ-1/4/5 实跑，RQ-0/2/3/6 CODE_VERIFIED）| **PENDING_PG_VERIFICATION / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT**（0005 待 Docker 恢复）|

---

## 证据等级说明

- **runtime 实跑**：真实执行 `record_usage`，断言 created/replay/2-charge/None=0
- **CODE_VERIFIED / inspect**：`inspect.getsource` 代码结构确认（非 runtime mock）
- **PG_VERIFIED_MIDPOINT**：已在本地开发 PG 验证迁移 + 事务语义（非最终 Closure Gate）
- ★ test PASS ≠ runtime/E2E PASS（CODE_VERIFIED 路径最终 PG Closure 前需补 runtime 证据）

### 核心设计原则（全部 11 条一致）

```
Business Event Identity 必须在计费副作用前持久化（durable commit before charge）
Same Key + Same Stable Inputs → IDEMPOTENT_REPLAY
Same Key + Different Stable Inputs → IDEMPOTENCY_CONFLICT
Execution.status ≠ Billing truth（M07 committed ComputeTransaction = sole ledger）
```

### 已拦截的误去重风险（治理有效性证明）

- M01 run_id 缺 attempt → 会误去重 retry
- M05 material_id + ark_v1 → 会误去重 re-analysis
- DailyReportJob.id → 会误去重 regenerate
- RAG chunk_hash → 会撞相同内容不同 occurrence
- RAG Query _search_sqlite 函数名 → 会把 SQLite-only 误标 fallback

---

## PG Verification 状态

| 路径 | 迁移 | PG 状态 |
|---|---|---|
| M07 Core | 0030（auto_wechat）| PG_VERIFIED（PG Core Gate）|
| Training | 0004（xg_douyin_ai_cs）| PG_VERIFIED_MIDPOINT |
| RAG Ingest | 无新迁移（事务边界）| PG_VERIFIED_MIDPOINT（RI-0/6B）|
| RAG Query | 0005（xg_douyin_ai_cs）| PENDING_PG_VERIFICATION / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT |
| Daily Report | 0032（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH |
| M05 | 0033（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH |
| Preview | 0034（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH |

---

## Technical Closure Blockers（4 项）

### Blocker A — auto_wechat schema baseline（DB-BL-2，Critical Path）

- `auto_wechat` 开发 PG 库：57 表 + 无 `alembic_version`（create_all 建表，无 Alembic 跟踪）
- 解锁 0032/0033/0034 PG 验证
- DB-BL-2 优先 5 个问题：0001_empty_baseline 假设 / 空库 alembic upgrade head 能否构建完整 schema / create_all 运行路径 / 开发库是否有保留数据 / 最终治理模型（Alembic 唯一 authority vs create_all baseline + Alembic incremental）
- 顺序：DB-BL-2A migration-chain completeness → 2B schema ownership audit → 2C exact reconciliation → 2D repair strategy

### Blocker B — RAG Query 0005 PG（Docker 环境依赖）

- xg_douyin_ai_cs 库有可信 Alembic 基线（Training 0004 PG_VERIFIED_MIDPOINT）
- 待 Docker Desktop 恢复后独立补：0004→0005 upgrade + table/PK/CHECK/索引 + SearchExecution lifecycle
- 不依赖 DB-BL-2，独立完成

### Blocker C — Global Active None Audit

- 重新全局搜索所有 charge-producing 路径（`record_usage` / `report_usage` 调用点），确认 `idempotency_key=None` 的 active 生产路径 = 0
- 不能只信 11 条 Register（P1 期间代码可能新增调用点）

### Blocker D — Final PG Concurrent Closure Gate

- duplicate same business event / same payload / different payload conflict / consumer identity preservation
- 最终 PG 并发闭环验证

---

## Reliability Gap 登记（7 个，均 OUT_OF_P1）

| Gap | 场景 |
|---|---|
| DAILY_REPORT_REQUEST_RECOVERY_GAP | full 9000→9100 response-lost |
| TRAINING_REQUEST_RECOVERY_GAP | Training ask full-request response-lost |
| RAG_INGEST_RUN_RECOVERY_GAP | durable TrainingRun → crash → running 孤儿行 |
| RAG_INGEST_REQUEST_RECOVERY_GAP | train_document/train_scope HTTP 失败 → 重新提交建新 Run |
| M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP | Ark completed → usage report failed → 无自动 recovery |
| PREVIEW_REQUEST_RECOVERY_GAP | full 9000→9100 preview response-lost → 重发 → 新 execution |
| RAG_QUERY_REQUEST_RECOVERY_GAP | whole search request retry → 新 Execution → 新 charge |

★ same execution replay → P1 保护；full request retry → 未保证 → P1 不解决。
★ Reliability Gap 不阻止 Consumer Migration Complete，也不得偷偷改成"已解决"。

---

## PG Closure Gate 三态（冻结）

```
PASS
  所有 active charge-producing paths：A. migrated None=0 或 B. non-chargeable policy
  + Global charge path audit clean + PG final gates PASS + required PG migrations verified
  → COMPUTE-IDEMPOTENCY-001 可申报 E2E_VERIFIED_FIXED / CLOSED

FAIL
  仍存在未批准 active None charge path 或 PG 验证失败

WAIVED_WITH_ACCEPTED_RESIDUAL_RISK
  管理层接受剩余风险，但不得标 E2E_VERIFIED_FIXED（WAIVED ≠ PASS）
```

当前 PG Closure Gate = **FAIL**（4 项 Technical Closure Blockers 未闭环）。

---

## 仓库同步状态

- 本地 HEAD：`67eb1f9`（11/11 Consumer Migration Complete）
- 远端 origin/master：`67eb1f9`（**已同步**，fast-forward push）
- tag `p1-checkpoint-11-of-11-consumer-migration-complete`（待建）

---

## 下一阶段：P1 Technical Closure

Consumer 层工作完成。下一阶段性质变化：

```
之前：find None path → establish business identity → migrate consumer
现在：schema baseline → PG evidence → global audit → concurrency closure
```

不再顺手优化 11 条 Consumer，不"顺便统一 Execution 模型"。冻结 Consumer 实现，进入 Closure。

### 主线

1. **DB-BL-2** auto_wechat PostgreSQL Baseline Reconciliation Technical Design（只读探索 + 设计，不直接 stamp/repair/rebuild）
2. **0005 PG**（Docker 恢复后独立补）
3. **Global Active None Audit**（重新全局搜索）
4. **Final PG Concurrent Closure Gate**
5. → COMPUTE-IDEMPOTENCY-001 E2E_VERIFIED_FIXED / CLOSED
