# P1 M05 Material Analysis Execution Identity 生命周期技术设计（Stage 5F-2）

> 状态：TECHNICAL_DESIGN_IN_PROGRESS（只设计，不实施）
> 前置：Register #8 M05 Material Analysis 当前 = EXECUTION_IDENTITY_DESIGN_GAP / NOT MIGRATED
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #8
> 范围：设计 M05 ark 分析计费点的稳定幂等身份，回答"什么构成一次 Material Analysis 的独立计费身份"
> 下一步：审查通过后决定方案 A/B，再授权实施（不在本 Stage 实施）

## 硬需求（开篇）

**P1 需要在 M05 ark 分析计费点构造稳定幂等身份。**

- 当前 `AiEditMaterialProcess` 表 schema present 但**无运行时 writer**（dormant），ark 路径完全绕过它。
- 当前 `AiEditMaterialAnalysis` 表按 `source_sha256` 去重复用同一行（re-analysis UPDATE 同行，id 不变）→ 无法区分重新分析 → 不能作 billing identity。
- 需新建独立持久 Execution 实体（**方案 B preferred**），不依赖 dormant 五阶段旧表。
- billing truth 仍只归 M07 committed ComputeTransaction；Execution 无 is_billed。

## 当前事实（已验证，file:line）

追踪 `app/services/material_analysis.py::analyze_material_async`（L20）完整顺序：

```
analyze_material_async(material_id, presigned_url) L20
  material.analysis_status = "analyzing" L41
  db.commit() L42                          # status 持久化（非 identity）
  result = _analyze_via_ark(...) L45       # ★ ark 外部 API 调用（计费源）
  if result is None: L46                   # ark 失败 → failed，不计费
    material.analysis_status = "failed"; db.commit(); return L47-50
  # 写/更新 AiEditMaterialAnalysis（按 source_sha256 去重）
  analysis = query(AiEditMaterialAnalysis).filter(source_sha256==...).first() L58-62
  if analysis is None: INSERT L70-80       # 首次：新建行
  else: UPDATE transcript_json L81-83      # re-analysis：复用同行（id 不变）
  material.analysis_status = "analyzed" L85
  db.commit() L86
  _report_analysis_usage(db, merchant_id, ...) L89   # ★ 计费点（idempotency_key 未传）
```

关键事实：

| 事实 | 证据 | 设计含义 |
|---|---|---|
| Analysis 行按 source_sha256 复用 | L58-62 query + L81-83 UPDATE 同行 | re-analysis id 不变 → 不能作 billing identity |
| 计费点在 ark 成功后 | `_report_analysis_usage` L89，仅 result 非 None 路径 | identity 必须在 L89 前已持久 |
| ark 失败不计费 | result is None → return（L46-50，不调 _report） | Execution 失败态承载，不污染 Analysis |
| ark 无 retry | `_analyze_via_ark` L130 单次调用，失败返回 None | 1:1 候选（YAGNI 不引入 attempt_count） |
| AiEditMaterialProcess dormant | schema present（L1699）但 ark 路径无 writer | 不激活旧五阶段模型 |
| _report_analysis_usage 无 key | L264-266 DESIGN_GAP 注释 | 待迁移 |

计费点 = `_report_analysis_usage`（L229 def / L89 call），`capability_key="ai_edit"`、`source="llm"`、`remark="AI剪辑素材分析（方舟多模态）"`，当前无 `idempotency_key`。

---

## 核心合同（冻结）

1. **persistent Analysis Execution must be durably committed before Ark external API call**（identity 前置持久化，先于 ark 计费副作用）
2. **explicit first analysis → NEW Execution**
3. **explicit re-analysis → NEW Execution**（每次显式 re-analysis 是独立合法消费）
4. **same Execution billing replay → SAME Execution identity → IDEMPOTENT_REPLAY**（M07 保护）
5. **shared Analysis row → result model only**（按 source_sha256 复用，Analysis 是结果存储不是 billing identity）
6. **Execution status ≠ billing truth**
7. **M07 committed ComputeTransaction → sole authoritative ledger**

---

## A. 方案 A vs 方案 B 完整比较

### 方案 A — Activate dormant AiEditMaterialProcess

激活 `AiEditMaterialProcess`（L1699）作 billing identity：五阶段表（media_probe/transcript/content_analysis/stability/cloud_upload）有 `UniqueConstraint(material_id, source_sha256, stage)` + `attempt_count` + `status` lifecycle。

**必须证明的前置条件**：旧 Task 12 五阶段模型（stage/attempt_count/status/lifecycle）与当前 Ark Material Analysis 语义一致。

**当前事实否决**：
- Ark 路径是**单次多模态分析**（`_analyze_via_ark` 一次 API 调用，L130），**不是**五阶段流水线。
- 五阶段（media_probe/transcript/content_analysis/stability/cloud_upload）是 Task 12 旧架构（19000 本地执行面，已随 AI 剪辑冻结删除），与当前 LAS/Ark 单次分析语义**不一致**。
- `attempt_count` 用于处理状态不是计费身份（DESIGN_GAP 注释已记录）。

**代价**：若强行激活，需把单次 ark 分析硬塞进五阶段模型（语义错配）→ 产生**概念债务**。仅为少建一张表激活旧模型，不值。

**结论**：方案 A 否决——旧五阶段模型与当前 ark 单次分析语义不一致，激活产生概念债务。

### 方案 B — 新建 AiEditMaterialAnalysisExecution（preferred）

新建独立持久 Execution 实体，与 Training（`KnowledgeTrainingExecution`）/ DailyReport（`DailyReportGeneration`）/ RAG Ingest（run+chunk）同构。

```
analyze_material_async(material_id, presigned_url)
  execution = AiEditMaterialAnalysisExecution(
      material_id, source_sha256, lifecycle_status="running",
  )
  db.add(execution); db.commit()           # ★ durable commit（before ark call）
  result = _analyze_via_ark(...)            # ark 外部 API（计费源）
  if result is None:
      execution.lifecycle_status = "failed"; db.commit(); return
  # 写/更新 shared Analysis（result model only，按 source_sha256 复用，不变）
  analysis = query/insert/update AiEditMaterialAnalysis L58-83
  execution.lifecycle_status = "completed"; db.commit()
  _report_analysis_usage(db, merchant_id, ..., execution_id=execution.id)  # ★ 计费点
```

**职责分离**：
- `AiEditMaterialAnalysisExecution` = billing identity（每次显式分析新建一行，持久不可清空）
- `AiEditMaterialAnalysis` = shared result（按 source_sha256 复用，result model only）

**candidate key**（设计候选，非最终 contract）：
```
event_namespace = material_analysis_execution
business_event_id = {execution_id}:ark_analysis
idempotency_key = f"material_analysis_execution:{execution_id}:ark_analysis"
```

**收益**：
- 与已迁移路径同构（Training/DailyReport/RAG Ingest），模式一致
- Analysis 表不变（source_sha256 复用语义保持）
- Execution 在 ark 调用前 durable commit，满足核心合同 1
- dormant Process 表不激活，不产生概念债务

---

## B. shared Analysis row 与 billing identity 的关系（合同 5）

**Analysis 行 = result model only**。

- `AiEditMaterialAnalysis` 按 `source_sha256` 去重（L58-62）：同 material re-analysis 复用同一行（UPDATE transcript_json，id 不变）。
- 这是**结果存储**的合理行为：相同内容应有相同分析结果，结果行复用避免冗余。
- 但 **id 不变 → 不能作 billing identity**：re-analysis 是独立合法消费（新 ark API 调用），若用 analysis.id 做 key 会误去重为 replay，漏扣合法 re-analysis。
- **职责分离**：Execution（billing identity，每次新建）/ Analysis（shared result，复用）。两者解耦，互不影响。

---

## C. Execution durability 时序（合同 1）

```
analyze_material_async L20
  # ★ 新增：identity 层（durable commit before ark call）
  execution = AiEditMaterialAnalysisExecution(material_id, source_sha256, lifecycle="running")
  db.add(execution); db.commit()           # ★ execution.id 持久化（先于 ark 调用）

  result = _analyze_via_ark(presigned_url, api_key) L45   # ark 外部 API（计费源）
  if result is None: L46                                   # ark 失败
    execution.lifecycle_status = "failed"; db.commit(); return   # Execution failed（不计费）
  # 写 shared Analysis（不变）L58-83
  execution.lifecycle_status = "completed"; db.commit()
  _report_analysis_usage(db, merchant_id, ..., execution_id=execution.id) L89  # ★ 计费点（identity 已存在）
```

**C 答**：execution 在 `_analyze_via_ark`（L45，ark 外部 API 计费源）前已创建并 commit。满足核心合同 1：persistent Analysis Execution durably committed before Ark external API call。

> **ordering 选择注记**：execution 创建必须在 ark call 前（合同 1 明确要求 before Ark external API call）。当前 `material.analysis_status="analyzing"` + commit（L41-42）只持久化 status，不含 identity——Execution 是新增层，与 status 持久化可合并到同一 commit 或独立 commit（实施期决策，不冻结）。

---

## D. LLM/ark 失败时 Execution 如何结束（合同 6）

- ark 失败（result is None，L46）→ 不计费（`_report_analysis_usage` 不在失败路径）→ Execution lifecycle="failed"（未计费）
- ark 成功 + `_report_analysis_usage` 成功 → ComputeTransaction 提交 → Execution lifecycle="completed"（billed，账务真相以 M07 ComputeTransaction 为准）
- ark 成功 + `_report_analysis_usage` 失败 → ComputeTransaction 未提交 → Execution 仍 running/unbilled → retry 复用同一 Execution identity

**D 答**：ark 失败由 Execution 层承载 failed 状态，**不污染 Analysis 业务模型**（Analysis 只在 result 非 None 时写/更新）。**Execution status ≠ billing truth**（合同 6），committed ComputeTransaction 是唯一账本。

---

## E. explicit re-analysis 是否必然 new Execution（合同 3）

**答：是。** 重新触发 `analyze_material_async`（同 material）→ 新 Execution 行 → 新 execution_id → 新 key。即使 `source_sha256` 相同（Analysis 行复用），Execution 是新建的。

1 explicit re-analysis = 1 new Execution = 1 new ark API 消费 = 合法新 charge（非 defect）。与 RAG Ingest RI-4（same chunk new run → different key）同语义。

---

## F. 是否保持 1 Execution : 1 ark charge（YAGNI）

**答：是。** 当前 `_analyze_via_ark` 单次调用（L130），无 retry。1 Execution : 1 ark charge 成立。

- **不引入 attempt_count**（YAGNI）：当前无 retry/recovery 机制。
- 未来若新增 ark retry / process recovery，再判断 REUSE（同 Execution）或 NEW（新 Execution）——届时类比已迁移路径的 NEW/REUSE 规则。

---

## G. billing truth 归 M07（合同 6/7）

**答：确认。**
- Execution 可有执行生命周期（running/completed/failed）用于执行编排。
- **但不得新增 `execution.is_billed` 成为账务真相**（合同 6）。
- **committed ComputeTransaction 是唯一 billing truth**（合同 7）。
- Execution 上的 billing-related 状态只能是派生/缓存/可恢复辅助状态。
- 类比 DailyReportGeneration / KnowledgeTrainingExecution 实施约束。

---

## 不变式（3 条，与已迁移路径一致）

1. **same Execution billing replay → same key → REPLAY**：execution_id 不变 → 同一 idempotency_key → M07 IDEMPOTENT_REPLAY
2. **explicit re-analysis → NEW Execution → NEW key（合法新消费，非 defect）**：每次 re-analysis 新建 Execution → 新 execution_id → 新合法消费
3. **same material re-analysis → UPDATE same shared Analysis row（result 复用，不影响 billing identity）**：Analysis 按 source_sha256 复用（id 不变），但 Execution 是新建的——billing identity 与 result storage 解耦

---

## 边界注明

### 不激活 dormant Process 表
- `AiEditMaterialProcess`（L1699）五阶段模型与当前 ark 单次分析语义不一致（方案 A 否决）。
- 不为 P1 激活旧五阶段模型，避免概念债务。

### billing truth 归 M07
- 本设计只构造 idempotency_key，不改 M07 core / `record_usage`。
- committed ComputeTransaction 是唯一 billing truth；Execution 不持有 billing 状态。

### 不宣称跨进程请求级幂等
- M05 ark 分析是 9000 后台任务（BackgroundTask），进程内调用 ark API → `record_usage`（进程内，非 HTTP）。
- 不宣称解决 full request response-lost 级恢复（若有，登记独立 Reliability Gap，OUT_OF_P1）。

### candidate key 非最终 contract
- `material_analysis_execution:{execution_id}:ark_analysis` 是设计候选，审查通过后授权实施时才登记为最终 contract。

---

## 硬约束（冻结）

1. **persistent Execution durably committed before Ark external API call**（合同 1）
2. **execution_id finalize 后不清空（永久保留）**（支持 replay，类比已迁移路径）
3. **explicit first analysis / re-analysis → NEW Execution**（合同 2/3）
4. **same Execution billing replay → REUSE same identity**（合同 4，未来若引入 retry）
5. **billing truth = committed ComputeTransaction**；Execution 无 is_billed（合同 6/7）
6. **不引入 attempt_count**（YAGNI，当前 1:1）
7. **不激活 dormant Process 表**（方案 B preferred，不产生概念债务）
8. **shared Analysis row = result model only**，按 source_sha256 复用，不影响 billing identity（合同 5）

---

## 待审批决策点

1. ~~方案 A vs 方案 B~~ → **方案 B 已冻结 APPROVED**（Stage 5F-3 已实施；方案 A 否决：旧五阶段模型语义不一致）
2. execution 创建 ordering（ark call 前单 commit / 与 status=analyzing 合并 commit）→ **实施决策：ark call 前单 commit**（MA-0，status=analyzing commit 在前，execution 创建+commit 在后，先于 ark call）
3. ~~candidate key `material_analysis_execution:{execution_id}:ark_analysis`~~ → **冻结为最终 contract**（Stage 5F-3 已实施）
4. ~~审查通过后授权实施~~ → **Stage 5F-3 已实施**（migration 0033 + model + analyze_material_async 改造 + _report_analysis_usage 传 execution_id + 7 Gate PASS）

## Stage 5F-3 实施落记

- **方案 B 已实施**：migration `0033_material_analysis_executions.py` + ORM model `AiEditMaterialAnalysisExecution`
- **execution 在 ark call 前 durable commit**（MA-0，合同 1）
- **C1 红线落地**：ark 成功 → execution COMPLETED 先于 usage report；ark 失败 → FAILED（不计费）；usage report 失败不降级 Execution、不重跑 Ark
- **lifecycle 三态**：running / completed / failed
- **C2 Gap 登记**：**M05_ANALYSIS_USAGE_REPORT_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1**——Ark completed → usage report failed/response-lost → 无自动 billing-report recovery。★ same Execution usage report replay → P1 保护（同 key → IDEMPOTENT_REPLAY）；★ 但不保证失败的 usage report 一定被自动重试。不并入 #8 迁移状态。
- **7 Gate PASS**：MA-0~MA-6（`tests/test_material_analysis_compute_idempotency_migration.py`），含 MA-5 关键 Gate
- **None count**：M05 正式链 idempotency_key≠None = 0
- **0033 PG = PENDING_PG_VERIFICATION / BLOCKED_BY_SCHEMA_BASELINE_MISMATCH**（未验证不得 deploy）
- **COMPUTE-IDEMPOTENCY-001 仍 OPEN**（2/11 剩余：Preview / RAG Query）
