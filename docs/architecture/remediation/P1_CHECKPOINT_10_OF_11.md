# P1 COMPUTE-IDEMPOTENCY-001 治理检查点（10/11 MIGRATED）

> 冻结日期：2026-08-10
> 检查点提交：`3eddc84`（HEAD，已推送 origin/master）
> tag：`p1-checkpoint-10-of-11`
> 状态：OPEN / PARTIAL_REMEDIATION_VERIFIED
> 前置检查点：`P1_CHECKPOINT_9_OF_11.md`（`63fd4f0`，9/11）
> 下一步：Stage 5H-1 RAG Query Embedding Execution Identity 技术设计（最后一条，只设计，不实施）

---

## Charge Path Register（11 TOTAL / 10 MIGRATED / 1 OPEN）

### 已迁移（10）

| # | Charge Path | Commit | idempotency_key | Evidence Level | PG Verification |
|---|---|---|---|---|---|
| 1 | M04 WeChat Task | `8c73b1e` | `wechat_task:{task.id}:result_usage` | E2E_VERIFIED_FIXED_FOR_M04 | M07 PG Core Gate PASS |
| 2 | M06 LAS Archive | `7845e26` | `las_job:{job.id}:archive_usage` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 3 | M01 Auto Reply | `7b2b6d7` | `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 4 | M02 Webhook Lead | `06fb4f2` | `webhook_event:{event.id}:lead_usage` | MIGRATED | M07 PG Core Gate PASS |
| 5 | Return Visit Judge | `01a60c1` | `return_visit_run:{run_id}:judge` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 6 | Daily Report Summary | `91afaef` | `daily_report_generation:{generation_id}:summary` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（7 Gate 实跑 + 约束）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0032 待 DB-BL 修复）|
| 7 | Training Knowledge | `cb14ff9` | `knowledge_training_execution:{execution_id}:ask` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（TR-1~3/6 实跑，TR-4/5A/5B CODE_VERIFIED）| **PG_VERIFIED_MIDPOINT**（0004）|
| 8 | RAG Ingest Chunk Embedding | `0fee74a` | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（RI-1~5 实跑，RI-0/6B **PG 运行证据**）| **PG_VERIFIED_MIDPOINT**（事务边界）|
| 9 | M05 Material Analysis | `fe91a05` | `material_analysis_execution:{execution_id}:ark_analysis` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（MA-1/2/3/6 实跑，MA-0/4/5 CODE_VERIFIED）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0033 待 DB-BL 修复）|
| 10 | M01 Preview | `3eddc84` | `ai_preview_execution:{preview_execution_id}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（PV-1/2/3/4 实跑，PV-0/5 CODE_VERIFIED，PV-6 mixed）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0034 待 DB-BL 修复）|

### 开放（1）

| # | Charge Path | Status | Cardinality | 阻塞 |
|---|---|---|---|---|
| #10a | RAG Query Embedding | EXECUTION_IDENTITY_DESIGN_GAP / CARDINALITY_VERIFIED | 1:1 normal + 1:2 timeout 边界 | 需新建 SearchExecution + stage(primary/fallback_embedding) + daemon timeout 边界处理（设计风险最高）|

---

## Preview evidence 明细（本轮新增）

- **PV-1/2/3/4**：runtime 实跑（created/replay/2-charge/new-preview）
- **PV-0**（durable before 9100）/ **PV-5**（C1 lifecycle=整次请求结果，非 stage 状态）：CODE_VERIFIED inspect
- **PV-6**：runtime + inspect mixed（Auto Reply key 不变 + mixed identity warning + Preview None=0）
- ★ 10/10 test PASS ≠ 10/10 runtime/E2E PASS

### C1 红线（Preview 本轮核心）

```
AiPreviewExecution.status = 整次 Preview 请求结果（非 primary/retry stage 影子状态机）
primary 成功 + retry 失败但 9100 正常返回 → completed
9100 不回连 auto_wechat DB 修改 PreviewExecution（C2，DB ownership 仅 9000）
Auto Reply ai_auto_reply_run 合同零变化（C4，独立 namespace + mixed identity warning）
```

---

## PG Verification 状态

| 路径 | 迁移 | PG 状态 |
|---|---|---|
| M07 Core | 0030 | PG_VERIFIED（PG Core Gate）|
| Training | 0004（9100 xg_douyin_ai_cs）| PG_VERIFIED_MIDPOINT（upgrade + schema + lifecycle）|
| RAG Ingest | 无新迁移（事务边界）| PG_VERIFIED_MIDPOINT（RI-0 durable commit + RI-6B PG 失败 finalize）|
| Daily Report | 0032（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH（待 DB-BL 修复）|
| M05 | 0033（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH（待 DB-BL 修复）|
| Preview | 0034（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH（待 DB-BL 修复）|

### DB-BL 支线（独立，不阻塞 P1 主线）

- `auto_wechat` 开发 PG 库：57 表 + 无 `alembic_version`（create_all 建表，无 Alembic 跟踪）
- DB-BL-1 诊断完成：`SCHEMA_BASELINE_MISMATCH VERIFIED`
- DB-BL-2（深度 diff + 修复）：DEFERRED，Final PG Closure 前必须解决（解锁 0032/0033/0034 PG 验证）
- 禁止盲目 stamp / 手改 alembic_version / DROP 重建

---

## Reliability Gap 登记（均 OUT_OF_P1，不阻塞 Compute Idempotency 迁移）

| Gap | 场景 | 类型 | 状态 |
|---|---|---|---|
| DAILY_REPORT_REQUEST_RECOVERY_GAP | full 9000→9100 response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| TRAINING_REQUEST_RECOVERY_GAP | Training ask full-request response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_RUN_RECOVERY_GAP | durable TrainingRun → crash → running 孤儿行 | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_REQUEST_RECOVERY_GAP | train_document/train_scope HTTP 失败 → 重新提交建新 Run | RELIABILITY | OPEN / OUT_OF_P1 |
| M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP | Ark completed → usage report failed → 无自动 recovery | RELIABILITY | OPEN / OUT_OF_P1 |
| PREVIEW_REQUEST_RECOVERY_GAP | full 9000→9100 preview response-lost → 重发 → 新 execution | RELIABILITY | OPEN / OUT_OF_P1 |

★ same execution replay → P1 保护；full request retry → 未保证 → P1 不解决。

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

当前 1 条 None 路径仍 OPEN，PG Closure Gate = **FAIL**（未达 PASS；DB-BL 待修复）。

★ 11/11 Consumer Migration Complete ≠ COMPUTE-IDEMPOTENCY-001 E2E_VERIFIED_FIXED。还需 DB-BL 修复 + 0032/0033/0034 PG 验证 + Global None Audit + PG Closure Gate。

---

## 仓库同步状态

- 本地 HEAD：`3eddc84`（10/11 MIGRATED）
- 远端 origin/master：`3eddc84`（**已同步**，fast-forward push）
- tag `p1-checkpoint-10-of-11`（待建）

---

## 下一步

1. **Stage 5H-1**：RAG Query Embedding Execution Identity 技术设计（最后一条，只设计不实施）——需解决 8 个问题（SearchExecution owner 9100 vs 上游 / 统一 search 入口避免 fallback 误建第二 Execution / primary daemon 前 durable commit / primary+fallback 复用 search_execution_id / timeout 后 primary 晚完成 usage report / lifecycle=整次搜索 / RAG_QUERY_REQUEST_RECOVERY_GAP / Query None=0 不影响 Ingest）
2. **Stage 5H-2**：RAG Query 实施（待 5H-1 审批，11/11 Consumer Migration Complete）
3. **DB-BL-2**：auto_wechat Alembic 基线修复（Final PG Closure 前必须，解锁 0032/0033/0034 PG 验证）
4. **Final PG Closure Gate**：Global None Audit + PG Closure（11/11 + DB-BL 修复后）
