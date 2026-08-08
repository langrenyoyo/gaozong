# P1 COMPUTE-IDEMPOTENCY-001 治理检查点（9/11 MIGRATED）

> 冻结日期：2026-08-09
> 检查点提交：`fe91a05`（HEAD，已推送 origin/master）
> tag：`p1-checkpoint-9-of-11`
> 状态：OPEN / PARTIAL_REMEDIATION_VERIFIED
> 前置检查点：`P1_CHECKPOINT_8_OF_11.md`（`42cc7dc`，8/11）
> 下一步：Stage 5G-1 Preview Execution Identity 技术设计（只设计，不实施）

---

## Charge Path Register（11 TOTAL / 9 MIGRATED / 2 OPEN）

### 已迁移（9）

| # | Charge Path | Commit | idempotency_key | Evidence Level | PG Verification |
|---|---|---|---|---|---|
| 1 | M04 WeChat Task | `8c73b1e` | `wechat_task:{task.id}:result_usage` | E2E_VERIFIED_FIXED_FOR_M04 | M07 PG Core Gate PASS |
| 2 | M06 LAS Archive | `7845e26` | `las_job:{job.id}:archive_usage` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 3 | M01 Auto Reply | `7b2b6d7` | `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 4 | M02 Webhook Lead | `06fb4f2` | `webhook_event:{event.id}:lead_usage` | MIGRATED | M07 PG Core Gate PASS |
| 5 | Return Visit Judge | `01a60c1` | `return_visit_run:{run_id}:judge` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 6 | Daily Report Summary | `91afaef` | `daily_report_generation:{generation_id}:summary` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（7 Gate 实跑 + 约束）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0030→0032 待 auto_wechat 库 Alembic 基线修复）|
| 7 | Training Knowledge | `cb14ff9` | `knowledge_training_execution:{execution_id}:ask` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（TR-1~3/6 实跑，TR-4/5A/5B CODE_VERIFIED）| **PG_VERIFIED_MIDPOINT**（0004 upgrade + schema + lifecycle + RI-0/6B 事务边界已验）|
| 8 | RAG Ingest Chunk Embedding | `0fee74a` | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（RI-1~5 实跑，RI-0/6A/6B **已升级为真实 PG 运行证据**）| **PG_VERIFIED_MIDPOINT**（RI-0 durable commit + RI-6B PG 失败 finalize 已验）|
| 9 | M05 Material Analysis | `fe91a05` | `material_analysis_execution:{execution_id}:ark_analysis` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（MA-1/2/3/6 实跑，MA-0/4/5 CODE_VERIFIED inspect）| **BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（0033 待 auto_wechat 库 Alembic 基线修复）|

### 开放（2）

| # | Charge Path | Status | Cardinality | 阻塞 |
|---|---|---|---|---|
| #7 | M01 Preview | CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP | 1:N(2) primary+retry_combined | 需新建 PreviewExecution 持久实体 + stage 维度；POLICY_PENDING 不阻塞 identity 设计 |
| #10a | RAG Query Embedding | EXECUTION_IDENTITY_DESIGN_GAP / CARDINALITY_VERIFIED | 1:1 normal + 1:2 timeout 边界 | 需新建 SearchExecution + stage(primary/fallback_embedding) + daemon timeout 边界处理 |

---

## 证据等级说明

- **E2E / runtime 实跑**：真实执行 `record_usage`，断言 created/replay/2-charge/None=0
- **CODE_VERIFIED / inspect**：`inspect.getsource` 代码结构确认（非 runtime mock）
- **★ inspect PASS ≠ runtime/E2E PASS**：CODE_VERIFIED 路径最终 PG Closure 前需补 runtime 证据
- **PG_VERIFIED_MIDPOINT**：已在本地开发 PG 验证迁移 + 事务语义（非最终 Closure Gate）

### M05 evidence 明细（本轮新增）

- **MA-1/2/3/6**：runtime 实跑（created/replay/2-charge/None=0）
- **MA-0**（durable before ark）/ **MA-4**（ark failure FAILED）/ **MA-5**（C1 红线：ark success→COMPLETED 先于 usage report + usage fail 不降级）：CODE_VERIFIED inspect
- ★ 10/10 test PASS ≠ 10/10 runtime/E2E PASS

### C1 红线（M05 本轮核心）

```
Ark succeeds → Execution COMPLETED + commit → usage report（而非 usage fail → FAILED → rerun Ark）
Ark execution outcome 与 billing-report outcome 已正确解耦
```

---

## PG Verification 状态

| 路径 | 迁移 | PG 状态 |
|---|---|---|
| M07 Core | 0030 | PG_VERIFIED（PG Core Gate）|
| Training | 0004（9100 xg_douyin_ai_cs）| PG_VERIFIED_MIDPOINT（upgrade + schema + lifecycle）|
| RAG Ingest | 无新迁移（事务边界）| PG_VERIFIED_MIDPOINT（RI-0 durable commit + RI-6B PG 失败 finalize）|
| Daily Report | 0032（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH（待 DB-BL 基线修复）|
| M05 | 0033（auto_wechat）| BLOCKED_BY_SCHEMA_BASELINE_MISMATCH（待 DB-BL 基线修复）|

### DB-BL 支线（独立，不阻塞 P1 主线）

- `auto_wechat` 开发 PG 库：57 表 + 无 `alembic_version`（create_all 建表，无 Alembic 跟踪）
- DB-BL-1 诊断完成：`SCHEMA_BASELINE_MISMATCH VERIFIED`
- DB-BL-2（深度 diff + 修复）：DEFERRED，Final PG Closure 前必须解决
- ★ Repository contains continuous Alembic revision history from 0001 onward，但不等于"能从空库构建完整 schema"（0001_empty_baseline 提示可能是已有 schema 上建迁移历史）
- 禁止盲目 stamp / 手改 alembic_version / DROP 重建

---

## Reliability Gap 登记（均 OUT_OF_P1，不阻塞 Compute Idempotency 迁移）

| Gap | 场景 | 类型 | 状态 |
|---|---|---|---|
| DAILY_REPORT_REQUEST_RECOVERY_GAP | full 9000→9100 response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| TRAINING_REQUEST_RECOVERY_GAP | Training ask full-request response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_RUN_RECOVERY_GAP | durable TrainingRun created → crash before finalize → running 孤儿行 | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_REQUEST_RECOVERY_GAP | train_document/train_scope HTTP 失败/响应丢失 → 重新提交建新 Run | RELIABILITY | OPEN / OUT_OF_P1 |
| M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP | Ark completed → usage report failed/response-lost → 无自动 billing-report recovery | RELIABILITY | OPEN / OUT_OF_P1 |

★ RUN_RECOVERY ≠ REQUEST_RECOVERY，不合并。
★ same execution replay → P1 保护；full request retry → 未保证 → P1 不解决。

---

## PG Closure Gate 三态（冻结）

```
PASS
  所有 active charge-producing paths 满足以下之一：
    A. stable idempotency identity migrated → charge path None = 0
    B. formally approved non-chargeable policy → charge-producing call removed
  + Global charge path audit clean
  + PG final concurrency closure gate PASS（含 0032/0033 待 DB-BL 修复后验证）
  + required PG migrations verified
  → COMPUTE-IDEMPOTENCY-001 可申报 E2E_VERIFIED_FIXED / CLOSED

FAIL
  仍存在未批准的 active None charge path
  或 PG 验证失败

WAIVED_WITH_ACCEPTED_RESIDUAL_RISK
  管理层正式接受剩余风险并允许阶段退出
  但 COMPUTE-IDEMPOTENCY-001 不得标记 E2E_VERIFIED_FIXED（WAIVED ≠ PASS）
```

当前 2 条 None 路径仍 OPEN，PG Closure Gate = **FAIL**（未达 PASS 条件；未申请 WAIVED；DB-BL 待修复）。

---

## 仓库同步状态

- 本地 HEAD：`fe91a05`（9/11 MIGRATED）
- 远端 origin/master：`fe91a05`（**已同步**，fast-forward push 完成）
- 同步方式：纯 fast-forward（无 force push / rebase / squash）

---

## 下一步优先级

1. **Stage 5G-1**：M01 Preview Execution Identity 技术设计（只设计，不实施）——需解决 7 个工程问题（PreviewExecution 放 9000/9100 / 哪库拥有 / LLM 前 durable commit / primary+retry_combined 共享 execution_id / 不影响 Auto Reply 合同 / 失败成功 lifecycle / 保持 CHARGEABLE）
2. **Stage 5G-2**：Preview 实施授权（待 5G-1 审批）
3. **RAG Query**：最后一条 Open 路径（daemon timeout 边界，设计风险最高）
4. **DB-BL-2**：auto_wechat Alembic 基线修复（Final PG Closure 前必须解决，解锁 0032/0033 PG 验证）
