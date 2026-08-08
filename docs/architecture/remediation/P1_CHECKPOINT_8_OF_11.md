# P1 COMPUTE-IDEMPOTENCY-001 治理检查点（8/11 MIGRATED）

> 冻结日期：2026-08-08
> 检查点提交：`0fee74a`（HEAD）/ tag `p1-checkpoint-8-of-11`
> 远端同步：已完成（origin/master = `42cc7dc`，fast-forward，tag 已推）
> 状态：OPEN / PARTIAL_REMEDIATION_VERIFIED
> PG Midpoint Verification：2026-08-08 执行完毕（PG-MID-2/3 PASS，PG-MID-1 BLOCKED）
> 下一步优先级：① auto_wechat 库 Alembic 基线修复（解锁 PG-MID-1）② M05 identity 设计 ③ Preview / RAG Query

---

## Charge Path Register（11 TOTAL / 8 MIGRATED / 3 OPEN）

### 已迁移（8）

| # | Charge Path | Commit | idempotency_key | Evidence Level | PG Verification |
|---|---|---|---|---|---|
| 1 | M04 WeChat Task | `8c73b1e`（Stage 2）| `wechat_task:{task.id}:result_usage` | E2E_VERIFIED_FIXED_FOR_M04 | M07 PG Core Gate PASS |
| 2 | M06 LAS Archive | `7845e26`（Stage 3）| `las_job:{job.id}:archive_usage` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 3 | M01 Auto Reply | `7b2b6d7`（Stage 4B）| `ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 4 | M02 Webhook Lead | `06fb4f2`（Stage 5A）| `webhook_event:{event.id}:lead_usage` | MIGRATED | M07 PG Core Gate PASS |
| 5 | Return Visit Judge | `01a60c1` | `return_visit_run:{run_id}:judge` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED | M07 PG Core Gate PASS |
| 6 | Daily Report Summary | `91afaef` | `daily_report_generation:{generation_id}:summary` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（7 Gate 实跑 + 约束）| **PENDING_PG_VERIFICATION**（0030→0032 alembic upgrade + FK/CHECK/索引 + DR-7 PG 并发）|
| 7 | Training Knowledge | `cb14ff9` | `knowledge_training_execution:{execution_id}:ask` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（TR-1~3/6 实跑，TR-4/5A/5B CODE_VERIFIED inspect）| **PENDING_PG_VERIFICATION**（9100 0003→0004 alembic + 表/PK/CHECK/索引 + lifecycle + 并发）|
| 8 | RAG Ingest Chunk Embedding | `0fee74a` | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（RI-1~5 实跑，RI-0/6A/6B CODE_VERIFIED inspect）| **PENDING_PG_VERIFICATION**（选项 A durable commit + PG 失败 finalize RI-6B fresh transaction 在 PG 下成立）|

### 开放（3）

| # | Charge Path | Status | Cardinality | 阻塞 |
|---|---|---|---|---|
| #7 | M01 Preview | CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP | 1:N(2) primary+retry_combined | 需新建 PreviewExecution 持久实体 |
| #8 | M05 Material Analysis | EXECUTION_IDENTITY_DESIGN_GAP / EXISTING_ENTITY_CANDIDATE_FOUND | 1:1 | 复用 AiEditMaterialProcess.content_analysis stage 行，需 ark 路径接入 |
| #10a | RAG Query Embedding | EXECUTION_IDENTITY_DESIGN_GAP / CARDINALITY_VERIFIED | 1:1 normal + 1:2 timeout 边界 | 需新建 SearchExecution + stage(primary/fallback_embedding) |

---

## 证据等级说明

- **E2E / runtime 实跑**：真实执行 `record_usage`，断言 created/replay/2-charge/None=0
- **CODE_VERIFIED / inspect**：`inspect.getsource` 代码结构确认（非 runtime mock）
- **★ inspect PASS ≠ runtime/E2E PASS**：CODE_VERIFIED 路径最终 PG Closure 前需补 runtime 证据

### 各路径 evidence 明细

- **Daily Report**：DR-1~DR-7 实跑（NEW Generation rows=1 实跑断言）+ 3 约束
- **Training**：TR-1/2/3/6 runtime 实跑；TR-4（LLM fallback）/TR-5A（billing 前失败）/TR-5B（billing 后失败）CODE_VERIFIED inspect
- **RAG Ingest**：RI-1/2/3/4/5 SQLite runtime 实跑；RI-0（durable commit）/RI-6B（PG tx unusable）**已升级为真实 PG 运行证据**（PG-MID-3 验证）；RI-6A（workflow failure）仍 CODE_VERIFIED inspect

---

## PG Midpoint Verification 结果（2026-08-08 执行）

验证目标：本地 Docker 开发 PG（`127.0.0.1:5432`，容器 `auto-wechat-postgres-dev`，非生产）。使用显式临时 DSN，未修改 `.env.lan.local`（应用仍跑 SQLite）。

### PG-MID-1 Daily Report 0032（auto_wechat 库）— BLOCKED

- **状态**：`BLOCKED_BY_SCHEMA_BASELINE_MISMATCH`
- **pre-state**：`alembic_version` 表不存在（auto_wechat 库由 `Base.metadata.create_all()` 建表，从未建立 Alembic 迁移跟踪）
- M07 Core 0030 列（idempotency_key/payload_evidence/唯一约束）已由 create_all 存在（ORM 模型含）
- 0032 目标表 `daily_report_generations` 不存在 / `daily_report_jobs.current_generation_id` 不存在（create_all 旧快照不含）
- **按指令禁止 stamp / 手改 alembic_version / DROP 重建**
- **解锁条件**：auto_wechat 库需先建立正式 Alembic 基线（独立数据库基线修复任务，非 PG Midpoint 范围）；基线建立后方可 upgrade 0030→0032 + 验证表/约束/DR-7 并发

### PG-MID-2 Training 0004（xg_douyin_ai_cs 库）— ✅ PG_VERIFIED_MIDPOINT

- **pre-state**：alembic_version current=`0003`, heads=`0004`（Pre-state PASS）
- **upgrade**：BEFORE `0003` → AFTER `0004 (head)` ✅
- **schema 验证**：
  - 表 `knowledge_training_executions` 存在 ✅
  - 10 列（execution_id/tenant_id/merchant_id/douyin_account_id/question/lifecycle_status/outcome/error_type/created_at/completed_at）✅
  - PK `knowledge_training_executions_pkey` ✅
  - 索引 `idx_knowledge_training_executions_scope` ✅
  - CHECK `ck_knowledge_training_executions_status` ✅
- **lifecycle 验证**：create RUNNING ✅ / finalize COMPLETED ✅ / COMPLETED_FALLBACK ✅

### PG-MID-3 RAG Ingest 事务边界（xg_douyin_ai_cs 库）— ✅ PG_VERIFIED_MIDPOINT

- **RI-0 Parent Durable Before Charge**：
  - create Run + COMMIT → fresh connection SELECT 可见（`row visible in fresh transaction = True`）✅
  - 证明选项 A durable commit 在 PG 下 run_id 真正持久化，跨事务/连接可见可恢复
- **RI-6B DB Transaction Unusable**（★核心证据）：
  - 故意 SQL 错误（INSERT nonexistent_table）→ 事务进入 aborted state（`InFailedSqlTransaction`，后续 SQL 被拒）✅
  - rollback 失败工作事务 ✅
  - fresh connection UPDATE durable Run→status='failed' → commit ✅
  - durable Run 仍存在 + status=failed ✅
  - 证明 PG 失败 finalize（rollback→fresh conn→UPDATE failed→commit）在真实 PG 事务语义下成立

> RI-0 / RI-6B 此前为 CODE_VERIFIED（inspect），现升级为真实 PostgreSQL 运行证据。
> RI-1~RI-5 仍为 SQLite runtime 实跑（PG 下未重跑，非本次 Midpoint 范围，留待最终 Closure）。

### 应用环境状态

- `APPLICATION_CONFIG_ENVIRONMENT_GATE = FAIL / NOT_PG`（`.env.lan.local` DATABASE_URL/RAG_DATABASE_URL 均指向 SQLite）
- `PG_VERIFICATION_TARGET_GATE = PASS`（本地 Docker 开发 PG `127.0.0.1:5432` 已就绪，auto_wechat + xg_douyin_ai_cs 库存在）
- PG Midpoint 验证的是迁移兼容性与事务合同证据，**不是环境切换**（应用仍跑 SQLite）

> M07 Core 已有 PG_CORE_GATE PASS（Stage 1），但后续 consumer/schema 不能借用该证据。PG-MID-2/3 已补真实 PG 证据；PG-MID-1 待 auto_wechat 库 Alembic 基线修复后补。

---

## Reliability Gap 登记（均 OUT_OF_P1，不阻塞 Compute Idempotency 迁移）

| Gap | 场景 | 类型 | 状态 |
|---|---|---|---|
| DAILY_REPORT_REQUEST_RECOVERY_GAP | full 9000→9100 response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| TRAINING_REQUEST_RECOVERY_GAP | Training ask full-request response-lost | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_RUN_RECOVERY_GAP | durable TrainingRun created → crash before finalize → running 孤儿行 | RELIABILITY | OPEN / OUT_OF_P1 |
| RAG_INGEST_REQUEST_RECOVERY_GAP | train_document/train_scope HTTP 失败/响应丢失 → 重新提交建新 Run | RELIABILITY | OPEN / OUT_OF_P1 |

★ 持久孤儿 Run ≠ 未来 retry 复用该 Run；same Run replay→P1 保护 / full request retry→未保证→P1 不解决。
★ RUN_RECOVERY ≠ REQUEST_RECOVERY，不合并。

---

## PG Closure Gate 三态（冻结）

```
PASS
  所有 active charge-producing paths 满足以下之一：
    A. stable idempotency identity migrated → charge path None = 0
    B. formally approved non-chargeable policy → charge-producing call removed
  + Global charge path audit clean
  + PG final concurrency closure gate PASS（含 0030→0032 + 0003→0004 alembic upgrade + FK/约束 + 并发语义）
  + required PG migrations verified
  → COMPUTE-IDEMPOTENCY-001 可申报 E2E_VERIFIED_FIXED / CLOSED

FAIL
  仍存在未批准的 active None charge path
  或 PG 验证失败

WAIVED_WITH_ACCEPTED_RESIDUAL_RISK
  管理层正式接受剩余风险并允许阶段退出
  但 COMPUTE-IDEMPOTENCY-001 不得标记 E2E_VERIFIED_FIXED（WAIVED ≠ PASS）
```

当前 3 条 None 路径仍 OPEN，PG Closure Gate = **FAIL**（未达 PASS 条件；未申请 WAIVED）。

---

## 仓库同步状态

- 本地 HEAD：`42cc7dc`（8/11 检查点）
- 远端 origin/master：`42cc7dc`（**已同步**，fast-forward push 完成，`f453f44..42cc7dc`）
- tag `p1-checkpoint-8-of-11` 已推远端（指向 `42cc7dc`）
- 同步方式：纯 fast-forward（远端无独有提交，无 force push / rebase / squash）

---

## 提交链完整性（91afaef^..0fee74a，12 提交）

```
0fee74a feat(P1 5E-3): RAG Ingest chunk embedding 幂等迁移（8/11 MIGRATED）
244d792 设计修正：P1 Stage 5E-2R1 RAG Ingest TrainingRun durability + failure lifecycle
898906f 设计：P1 Stage 5E-2 RAG Ingest Chunk Embedding 幂等技术设计
1c7bcaa 文档纠正：P1 5D-2 TR-4/TR-5 证据等级 + TR-5 语义拆分 + PG 0004 验证挂起
cb14ff9 feat(P1 5D-2): KnowledgeTrainingExecution 实体 + Training 幂等迁移（7/11 MIGRATED）
1cf88ff 设计：P1 Stage 5D-1 Training Ask Execution Identity 生命周期技术设计
7437b30 文档冻结：P1 Stage 5D-R1 RAG 拆分 + PG Closure 三态 + None 路径措辞纠正
e479dbd 文档冻结：P1 Stage 5D-R1 RAG 拆分 + PG Closure 三态口径
743c73a 文档落地：P1 5C-4 四项长期 follow-up
4e6bbe4 文档修正：CLAUDE/AGENTS 6 consumer 补 Daily Report + README 治理索引
fe258e3 文档同步：P1 5C-4 MIGRATED 后治理入口文档
91afaef feat(P1 5C-4): DailyReportGeneration 实体 + Daily Report 幂等迁移
```

22 文件触及，全部在 P1 COMPUTE-IDEMPOTENCY-001 范围内，无范围外混入（未触及微信自动化/发送 gate/NewCar 鉴权/抖音 webhook 业务逻辑）。

---

## 下一步优先级

1. ✅ ~~远端同步检查点~~（已完成，origin/master = `42cc7dc` + tag）
2. ✅ ~~P1 Midpoint PostgreSQL Verification~~（PG-MID-2/3 PASS，PG-MID-1 BLOCKED）
3. **auto_wechat 库 Alembic 基线修复**：解锁 PG-MID-1（Daily Report 0032），需独立数据库基线任务
4. **M05 identity 技术设计**（复用 AiEditMaterialProcess.content_analysis，需先钉死 6 个生命周期问题）
5. **Preview identity 设计**（需新建 PreviewExecution）
6. **RAG Query identity 设计**（需新建 SearchExecution + stage，设计风险最高）
