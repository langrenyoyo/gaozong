# Cross-Module Risk Register（阶段 2B 闭环产出）

> 基于 7 模块 Current Reality + Controlled E2E 验真（commit c26ec227e70d ~ 8e0777e）
> 风险按生产安全排序（非模块编号）
> 阶段 2A/2B 正式闭环，阶段 2C External Gate Closure 持续开放

---

## 1. HIGH 风险汇总（4 个独立，不合并）

| ID | 风险 | Owner | E2E 证据 | 影响域 |
|---|---|---|---|---|
| HIGH-01 | Compute Financial Idempotency（record_usage 无幂等键） | M07 | E2E_VERIFIED（Gate A: balance delta = 2 × charge） | M04 E2E_VERIFIED_IMPACTED / M06 CODE_VERIFIED_EXPOSED / M01/M02/M05 CALL_SITE_IDENTIFIED |
| HIGH-02 | M04 Duplicate Task Execution（无 atomic claim/lease） | M04 | E2E_VERIFIED（Gate 2: 两 Agent 拿同一 Task） | 同商户多 Agent 重复执行微信任务 |
| HIGH-03 | M05 Temporary URL Durability（临时 presigned URL 持久化 DB） | M05→M06 | CODE_VERIFIED + dependency VERIFIED（ai_edit.py:301,326 直接存 presigned URL；M06 LAS 消费该 URL 路径已确认） | LAS submit 可能因 URL 过期失败 |
| HIGH-04 | M05 Active Material Reference Integrity（soft_delete 引用检查类型不匹配） | M05 | E2E_VERIFIED（Gate G: active job 引用素材未阻断） | Manual/AiEditJobMaterial-backed jobs 素材可被误删 |

> M05 两个 HIGH 不合并——根因/修复/验收/回滚/数据修复都不同。

---

## 2. 跨模块根因映射

```
COMPUTE-IDEMPOTENCY-001（M07 ROOT CAUSE — HIGH-01）
  ├── M04 ISSUE-M04-002（LINKED_TO_ROOT_CAUSE, E2E_VERIFIED_IMPACTED — Gate F 证明 double charge）
  ├── M06 ISSUE-M06-003（CODE_VERIFIED_EXPOSED — 静态暴露，无 LAS E2E）
  ├── M01 compute_usage_client（CALL_SITE_IDENTIFIED — HTTP 上报，调用点已确认，未 E2E 证明重复扣费）
  ├── M02 douyin_webhook leads（CALL_SITE_IDENTIFIED — 进程内调用，调用点已确认，未 E2E 证明重复扣费）
  └── M05 material_analysis（CALL_SITE_IDENTIFIED — 进程内调用，调用点已确认，未 E2E 证明重复扣费）
```

### Consumer 证据四级

| 级别 | 含义 | 当前归属 |
|---|---|---|
| E2E_VERIFIED_IMPACTED | E2E 证明同一业务事件重复触发产生重复扣费 | M04（Gate F） |
| CODE_VERIFIED_EXPOSED | 静态代码确认调用点暴露但未 E2E 证明重复扣费 | M06 |
| CALL_SITE_IDENTIFIED | 调用点已确认但未证明重复扣费 | M01/M02/M05 |
| NOT_VERIFIED | 未验证 | — |

> 不把"存在 record_usage 调用"自动翻译成"E2E 证明重复扣费"。

> **P1 consumer 迁移状态（2026-08）**：11 TOTAL charge path / 7 MIGRATED（M04 / M06 / M01 Auto Reply / M02 / Return Visit Judge / Daily Report / Training）/ 4 OPEN。Open 路径：#7 Preview（CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP）/ #8 M05（EXECUTION_IDENTITY_DESIGN_GAP）/ #10a RAG Query Embedding（EXECUTION_IDENTITY_DESIGN_GAP）/ #10b RAG Ingest Chunk Embedding（CHILD_EXECUTION_IDENTITY_DESIGN_GAP，Parent Training Run.id VERIFIED）。原 #10 RAG Embedding 已按 query/ingest 拆为 #10a/#10b。详见 `docs/architecture/remediation/P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path Migration Register（Stage 5D-R1 冻结版 + 5D-2 Training 迁移）。
> **Open 路径统一风险描述**：所有 4 条 Open 路径 `idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；重复扣费暴露证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE，未经受控 E2E 复现）。不得把"存在 record_usage 调用"夸大为 E2E 证明重复扣费。
> **可靠性差距分离（防根因混淆）**：**DAILY_REPORT_REQUEST_RECOVERY_GAP** 与 **TRAINING_REQUEST_RECOVERY_GAP** 均 = OPEN / RELIABILITY / OUT_OF_P1——full 9000→9100 request response-lost（9100 已完成 LLM + M07 已 commit，但 9000 未收到响应 → 重跑 LLM 可能不同 usage → M07 IDEMPOTENCY_CONFLICT 兜底）。此 Gap 属可靠性范畴，**不是** COMPUTE-IDEMPOTENCY-001 财务幂等未完成的证据，不得据此判定根因仍 OPEN 或与 consumer 迁移状态合并。P1 不虚假宣称已解决跨进程请求级幂等。

---

## 3. STRUCTURAL PRIORITIES（单独队列，不进 HIGH）

| ID | 结构风险 | 涉及模块 | 状态 |
|---|---|---|---|
| S1 | Lead Identity Contract（无统一身份，聚合键双轨制） | M02 | POLICY_PENDING / CONTRACT_GAP |
| S2 | Agent Runtime Config Contract（agent_config 三处重复组装） | M03/M01 | LOW 解耦候选 |
| S3 | M01 → M02 direct data write（DATA_COUPLING） | M01→M02 | ARCHITECTURE_OBSERVATION |
| S4 | M04 → M02 direct data write（DATA_COUPLING） | M04→M02 | ARCHITECTURE_OBSERVATION |
| S5 | M05/M06 shared implementation coupling（共用 router/feature） | M05/M06 | S 解耦候选 |

---

## 4. Open Gate Records

| 环境 | 模块 | Gate 数 | 共享 Readiness |
|---|---|---|---|
| Staging | M01（8 Gate）/ M02（4 Gate）/ M03（3 Gate）/ M07（1 Gate Concurrent） | 16 | STAGING_E2E_READINESS.md |
| Windows | M04（W01-W06） | 6 | WINDOWS_E2E_READINESS.md |
| External | M05（TOS/Ark 3 Gate）/ M06（LAS 3 Gate D/E/F） | 6 | PENDING_EXTERNAL_INTEGRATION |

> 26 个 Open Gate Records（存在证据复用，实际工作量小于总数）

---

## 5. 阶段 3 结构

### PHASE 3A — Production Safety Stabilization（HIGH Root Risks）

| 优先级 | 风险 | Remediation direction（不冻结具体实现） |
|---|---|---|
| P1 | COMPUTE-IDEMPOTENCY-001（HIGH-01） | business idempotency identity + DB uniqueness + atomic deduplication |
| P2 | M04-001 DUPLICATE_EXECUTION（HIGH-02） | atomic claim/lease |
| P3a | M05-005 ACTIVE_REFERENCE_INTEGRITY（HIGH-04） | reference check type correction |
| P3b | M05-004 TEMPORARY_URL_DURABILITY（HIGH-03） | stable key storage + dynamic presign |

> 修复方向不冻结具体实现（"先查询再插入"等属于技术设计审批内容；claim 归属/lease 时长/崩溃恢复属于技术设计审批）。

### PHASE 3B — Contract Stabilization（Structural Risks）

| 优先级 | 风险 |
|---|---|
| S1 | Lead Identity Contract |
| S2 | Agent Runtime Config Contract |
| S3 | M01 → M02 direct data write |
| S4 | M04 → M02 direct data write |
| S5 | M05/M06 shared implementation coupling |

### PHASE 3C — Implementation Decoupling

- shared implementation 清理
- compat legacy 清理
- 目录职责调整

---

## 6. 7 模块 BASELINE_CANDIDATE 统一状态

| 模块 | 状态 | 环境 Gate |
|---|---|---|
| M01 抖音AI客服 | BASELINE_CANDIDATE_PENDING_STAGING | 8 Gate（staging） |
| M02 AI小高线索 | BASELINE_CANDIDATE_PENDING_STAGING | 4 Gate（staging） |
| M03 AI小高智能体 | BASELINE_CANDIDATE_PENDING_STAGING | 3 Gate（staging） |
| M04 AI小高微信助手 | BASELINE_CANDIDATE_PENDING_WINDOWS | 6 Gate（Windows 19000） |
| M05 小高素材库 | BASELINE_CANDIDATE_PENDING_EXTERNAL | 3 Gate（TOS/Ark 凭证） |
| M06 AI小高剪辑 | BASELINE_CANDIDATE_PENDING_EXTERNAL | 3 Gate（LAS 凭证） |
| M07 AI小高算力 | BASELINE_CANDIDATE_PENDING_STAGING | 1 Gate（PG concurrent） |
