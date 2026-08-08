# Cross-Module Risk Register（阶段 2B 闭环产出）

> 基于 7 模块 Current Reality + Controlled E2E 验真（commit c26ec227e70d ~ 8e0777e）
> 风险按生产安全排序（非模块编号）
> PHASE 2A（Current Reality）✅ COMPLETE
> PHASE 2B（Controlled E2E + Candidate）✅ COMPLETE
> PHASE 2C（External Gate）⏸ OPEN

---

## 1. HIGH 风险汇总（按生产安全排序）

| ID | 风险 | Owner | E2E 证据 | 影响域 |
|---|---|---|---|---|
| HIGH-01 | Compute Financial Idempotency（record_usage 无幂等键） | M07 | E2E_VERIFIED（Gate A: balance delta = 2 × charge） | M04 E2E impacted / M06 CODE_VERIFIED exposed / M01/M02/M05 按调用事实 |
| HIGH-02 | M04 Duplicate Execution（无 atomic claim/lease） | M04 | E2E_VERIFIED（Gate 2: 两 Agent 拿同一 Task） | 同商户多 Agent 重复执行微信任务 |
| HIGH-03 | M05 Temporary URL Durability（临时 presigned URL 持久化 DB） | M05 | CODE_VERIFIED（ai_edit.py:301,326 直接存 presigned URL） | M06 LAS 消费该 URL，过期后 LAS submit 可能失败 |
| HIGH-04 | M05 Active Material Reference Integrity（soft_delete 引用检查类型不匹配） | M05 | E2E_VERIFIED（Gate G: active job 引用素材未阻断） | Manual/AiEditJobMaterial-backed jobs 素材可被误删 |

---

## 2. 跨模块根因映射

```
COMPUTE-IDEMPOTENCY-001（M07 ROOT CAUSE — HIGH-01）
  ├── M04 ISSUE-M04-002（LINKED_TO_ROOT_CAUSE, E2E_VERIFIED_IMPACTED — Gate F 证明 double charge）
  ├── M06 ISSUE-M06-003（CODE_VERIFIED_EXPOSED — 静态暴露，无 LAS E2E）
  ├── M01 compute_usage_client（按调用事实登记 — HTTP 上报，无幂等）
  ├── M02 douyin_webhook leads（按调用事实登记 — 进程内调用）
  └── M05 material_analysis（按调用事实登记 — 进程内调用）
```

---

## 3. 开放环境 Gate 汇总

| 环境 | 模块 | Gate 数 | 共享 Readiness |
|---|---|---|---|
| Staging | M01（8 Gate）/ M02（4 Gate）/ M03（3 Gate）/ M07（1 Gate Concurrent） | 16 | STAGING_E2E_READINESS.md |
| Windows | M04（W01-W06） | 6 | WINDOWS_E2E_READINESS.md |
| External | M05（TOS/Ark 3 Gate）/ M06（LAS 3 Gate D/E/F） | 6 | PENDING_EXTERNAL_INTEGRATION |

---

## 4. Contract Gap 汇总

| Gap | 涉及模块 | 状态 |
|---|---|---|
| Lead Identity Contract（无统一身份，聚合键双轨制） | M02 | POLICY_PENDING / CONTRACT_GAP |
| agent_config 三处重复组装 | M03/M01 | LOW 解耦候选 |
| M01/M04 直接写 M02 数据（DATA_COUPLING） | M01/M04→M02 | ARCHITECTURE_OBSERVATION |
| M05/M06 shared implementation（共用 router/feature） | M05/M06 | S 解耦候选 |
| M05 tos_presigned_url 临时 URL 持久化（非 stable key） | M05→M06 | HIGH-03（已列入风险汇总） |
| M05 soft_delete 引用检查类型不匹配 | M05 | HIGH-04（已列入风险汇总） |

---

## 5. 阶段 3 优先级建议（按生产安全排序）

| 优先级 | 风险 | 建议动作 | 预期影响 |
|---|---|---|---|
| P1 | HIGH-01 Compute Financial Idempotency | 加 idempotency_key 参数 + ComputeTransaction UniqueConstraint + record_usage 去重查询 | 财务完整性，防止重复扣费 |
| P2 | HIGH-02 M04 Duplicate Execution | 加 atomic claim/lease（条件 UPDATE SET status=processing WHERE status=pending RETURNING） | 防止多 Agent 重复执行微信任务 |
| P3 | HIGH-03+04 M05 URL + Reference | 存 cloud_storage_key（stable TOS path）替代 presigned URL + 修正 soft_delete 引用检查类型 | 数据完整性，防止素材误删 + LAS URL 过期 |
| P4 | Contract Gap | Lead Identity 统一 / agent_config 提取共享 / DATA_COUPLING 评估 | 架构治理，非紧急 |

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
