# P1 Daily Report Generation Identity 技术设计（Stage 5C-3）

> 状态：TECHNICAL_DESIGN_APPROVED + OPTION_B_APPROVED + RESPONSE_LOST_OPTION_C_APPROVED（Stage 5C-3R2 收口后）
> 前置：Stage 5C-2 已验真 DailyReportJob.id 是 1:N parent（结论 B）
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #10
> 范围：设计 generation identity，回答"什么动作创造一个新的、应单独收费的 Daily Report generation"
> 下一步：审查通过后授权 Stage 5C-4 实施

## 钉死的一句话

**一个 Generation = 一次逻辑上的 Daily Report Summary Generation Execution。**

- Generation 在 LLM 调用前创建并持久化；它**最多产生一次 Compute charge**。
- LLM/执行失败时，Generation **仍然存在**，但处于 `unbilled`/`failed` 状态；只有成功进入计费路径时才产生 ComputeTransaction。
- 技术性 retry / process recovery / response-lost retry **复用同一 Generation identity**（无论是否已计费）；只有**显式业务动作**（首次 generate / 用户 regenerate / manual retry）才创建新 Generation。

**核心账务不变量：One Generation → at most one summary Compute charge.**

计费判定锚点：Billing truth = **committed ComputeTransaction**（已提交的计费流水），而非仅仅 `client.chat` 成功。`_report_usage`（`daily_report_summary_service.py:193`）在 LLM `chat` 成功后执行，但其本身仍可能失败（9000↔9100 网络异常）——计费以 ComputeTransaction 是否提交为准。

---

## A. Generation 什么时候创建（identity 必须在 summary LLM 调用前已稳定持久化）

追踪完整顺序（`daily_report_job_service.py:315 generate_one`）：

```
阶段一（短事务一）：
  _get_or_create_job (:176)        # create-or-get DailyReportJob 行
  _claim_generating (:202)         # 生成 generation_token（临时租约令牌）+ status=generating
  db.commit() (:220)               # ★ job.id + generation_token 已持久化
阶段二（事务外）：
  build_daily_report (:332)
    → _build_daily_sales_feedback_report (:451)
      → summary_client.summarize_daily_sales_feedback(payload) (:574)
        → 9000 _post_json → 9100 summarize_daily_sales_feedback (:163)
          → client.chat(messages) (:177)   # LLM 调用
          → _report_usage (:193)            # ★ 计费点（仅 chat 成功后）
```

**A 答**：`_claim_generating` 的 `db.commit()`（`:220`）在 LLM 调用（`:574`→`:177`）之前。Generation identity **必须在 `_claim_generating` commit 时创建并持久化**——即在 LLM 调用前已存在。这样无论 LLM 成功/失败、计费成功/失败，identity 始终存在并可被 retry 恢复。

当前 `generation_token` 此时已持久化——但它不满足 C（finalize 后清空）。设计要求新增独立的持久 Generation identity（方案 B）。

---

## B. 什么动作产生新 Generation（每动作明确 NEW / REUSE）

核心规则：**只有显式业务动作（首次 generate / 用户 regenerate / manual retry）才创建新 Generation；所有 internal technical retry / process recovery / response-lost retry 严格复用同一 Generation identity，无论计费是否已提交。**

| 动作 | 新 Generation？ | 代码证据 |
|---|---|---|
| 首次 generate | **NEW** | `_get_or_create_job` 新建行（`:186`）+ `_claim_generating` 新 token（`:204`）→ LLM 调用 |
| 用户 regenerate | **NEW** | `regenerate_job`（`:400`）→ `generate_one`（`:415`）→ 同一 job 行，但新 `_claim_generating` 新 token（`:204`）+ 重新 LLM 调用。每次 regenerate 是独立合法 LLM 消费 |
| 技术性 retry（LLM timeout/network error） | **REUSE** | 9100 `summarize_daily_sales_feedback` chat 失败抛 `LLMRequestError`（`llm/client.py:143/148`）→ 9000 `daily_report_service.py:575` catch → 计为 `daily_summary_llm_failed` 诊断。9100/LLM client **均无自动 retry**（`llm/client.py:_post_json` 无重试；`xg_douyin_ai_cs_client.py:217 _post_json` 无重试）。Generation 仍存在（unbilled/failed 状态），后续 retry 复用同一 identity |
| Process recovery（restart 重新 claim） | **REUSE**（始终） | Technical retry / process recovery of the same logical generation → **always REUSE same Generation identity, regardless of whether billing already committed.** 已计费 → REUSE → M07 replay；未计费 → REUSE → retry execution → eventual first charge。**不创建新 Generation。** 当前 scheduler/reconcile 不自动重新 claim 崩溃的 generating（`daily_report_scheduler.py:189` 已有同键则 skip；`reconcile_job_deliveries` 只对账投递不重生报表）；stale generating（>30min）只能被用户主动 regenerate 触发 |
| Response lost + consumer retry | **REUSE**（同 generation，始终） | 9100 LLM 成功并计费（`:193`）后，若响应在传回 9000 途中丢失（9000→9100 HTTP 超时，`xg_douyin_ai_cs_client.py:232`），9000 catch 异常计 `llm_failed`。但 9100 侧计费可能已发生（ComputeTransaction 已提交）→ 重试必须复用同一 generation identity → replay（不重复计费）。**必须 REUSE 才正确** |
| Manual retry（显式业务动作） | **NEW** | **Explicit manual regeneration/retry = NEW**（与 internal technical retry / process recovery / response-lost retry 严格分开）。等同 regenerate：router `regenerate_daily_report`（`:455`）→ `regenerate_job`。用户主动触发的重做是独立合法消费 |

**技术性 retry 是新消费还是 replay？答：replay（REUSE）。** 因为：
1. LLM client 和 HTTP client 均无自动 retry → 不存在"同一次 attempt 内多次调 LLM"
2. Generation 在 LLM 调用前已持久化（unbilled 状态）；LLM 失败 → Generation 仍存在，后续 retry 复用同一 identity
3. response lost 时计费可能已发生，重试必须复用 identity 才不重复扣费

### claim count ≠ generation count（长期实现约束）

> **claim 次数不等于 Generation 数量。** `_claim_generating` 每次成功调用创建 NEW Generation，因为它绑定的是**显式 claim 动作**（首次 generate / regenerate / manual retry）；但**技术性 retry / process recovery / response-lost retry 不得再调 `_claim_generating` 重建 Generation**——它们必须通过 `job.current_generation_id` 确定性引用复用既有 Generation identity（已计费→M07 replay，未计费→重试执行→首次计费）。
>
> 此约束防止未来 full-request recovery（9000→9100 响应丢失后重跑）误把每次 claim / 重试都建 NEW Generation，导致同一逻辑生成被拆成多个 billing identity、绕过 M07 幂等重放。Generation 数量 = 显式业务动作数，不是 claim 调用数，也不是 LLM 调用数。
>
> 代码锚点：`daily_report_job_service.py::_claim_generating` docstring 已落地同一约束。

### Failure Boundary：LLM 成功 + Compute report 失败

**LLM success + Compute reporting failure（`_report_usage` 本身失败，如 9000↔9100 网络异常）→ does not create a new Generation → retry billing/report reuses same Generation identity.**

- Billing truth = **committed ComputeTransaction**，not merely successful `client.chat`
- LLM 成功但 ComputeTransaction 未提交 → Generation 处于 unbilled；retry 时复用同一 Generation → 首次成功提交计费
- LLM 成功且 ComputeTransaction 已提交 → Generation 处于 billed；retry 时复用同一 Generation → M07 replay
- 无论哪种情况，都不因"报告失败"而创建新 Generation

---

## C. Generation identity 是否永久保留

**必须 YES。** 当前 `generation_token`（`_claim_generating:204`，`secrets.token_hex(16)`）是**临时租约令牌**，`_finalize_success`（`:247`）和 `_finalize_failure`（`:278`）后置 None 清空 → **不满足**。

理由（为什么必须永久保留）：
1. **Response lost 场景（B 第 5 行）**：9100 已计费但 9000 未收到响应；9000 重试时需读取原 generation identity 才能 replay（不重复计费）。若 identity 已清空 → 无法 replay → 重复计费
2. **LLM 成功 + Compute report 失败**：Generation 处于 unbilled，retry 需复用同一 identity 完成首次计费
3. **LLM 失败**：Generation 仍存在（failed/unbilled），后续 technical retry 复用同一 identity，不创建新 Generation
4. **审计回溯**：需将 ComputeTransaction 与具体 generation 对账

**设计要求（不冻结字段名）**：generation identity 在 `_claim_generating` commit 时生成，**finalize 后不清空**，永久保留。

---

## D. 并发 Regenerate 怎么办

两个请求同时 regenerate 同一 Job：

**当前代码阻止并发都获得新 generation：**
- `_claim_generating`（`:202`）是原子条件 UPDATE（`:207`）：`WHERE id=job.id AND (status != generating OR started_at < stale_threshold)`，`rowcount=1` 才算 claim 成功（`:221`），`rowcount=0` 抛 `ClaimConflictError`（`:222`）
- router 捕获 `ClaimConflictError` 转 409（`daily_reports.py:481-487`）
- scheduler 同样捕获（`daily_report_scheduler.py:218`）

**但语义上**：若两个请求都成功 claim（例如 A claim 后 stale 超时被 B 抢占，或不同 worker 节点），应产生**两个不同 generation identity**，不能撞同值。

**设计要求**：generation identity 每次 `_claim_generating` 生成唯一值（如递增序号 + 随机，或 UUID），即使 job.id 相同也保证不同 generation 之间 identity 不撞。job.id（parent）+ generation identity（child）共同唯一确定一次计费事件。

---

## E. Retry 如何恢复原 Generation

Process restart 后恢复场景分析：

**当前无自动崩溃恢复**（与 ReturnVisitRun 不同）：
- `daily_report_scheduler.py:189`：已有同键任务（含 generating）一律 skip，不自动重新 claim
- `reconcile_job_deliveries`（`daily_report_delivery_service.py:181`）：只对账投递状态，不重生报表
- stale generating（`generation_started_at` 超 30min，`_claim_generating:209-213`）只能被**用户主动 regenerate** 触发新一轮 claim

**恢复时读到的 generation identity 是否一致？**
- 若崩溃在 `_claim_generating` commit 后、LLM 计费前：
  - Generation identity 已持久化（C 要求，方案 B 的 DailyReportGeneration 行已 INSERT）
  - 无自动恢复 → job 留在 generating 直到超时 → 用户 regenerate 触发 NEW Generation
  - 但**技术性 retry / process recovery 复用同一 Generation identity**（REQUIRED-2）：已计费 → M07 replay；未计费 → retry execution → eventual first charge
- **response lost 场景（P1 范围内）**：9100 已完成 `client.chat` + M07 已 commit ComputeTransaction，但 9000 未收到 9100 的 HTTP 响应。
  - **P1 解决的部分（DR-5 缩窄）**：同一 Generation + 同一 usage report 再次到达 M07 → M07 UniqueConstraint + payload_evidence replay。这是 **billing-report replay**，M07 已完全可以保护，不重复扣费。
  - **P1 不解决的部分（SEPARATE_REQUEST_RECOVERY_GAP）**：9000 重新执行 LLM（`client.chat` 再调一次）可能产生不同 usage evidence；若用 same Generation key + different payload → M07 返回 IDEMPOTENCY_CONFLICT（正确行为，不重复扣费）。这是 full 9000→9100 请求级响应丢失，属于 Daily Report 可靠性 Gap，**不属于 P1 财务幂等职责**，登记为独立 Gap 后续处理。

**是否会创建新 generation 而非恢复？** 技术性 retry / process recovery **不会**（REQUIRED-2：always REUSE same Generation identity）。只有显式业务动作（manual regenerate）才 NEW——而 manual regenerate 是用户明知"重来一次"的显式选择，产生新合法 charge。

---

## 关键边界（冻结）

### Lease identity ≠ Billing event identity

| | Lease identity（当前 generation_token） | Billing event identity（待设计） |
|---|---|---|
| 用途 | claim 抢占/防并发（`_claim_generating`） | 计费幂等（`_report_usage` idempotency_key） |
| 生命周期 | 临时，finalize 后清空 | 永久，不可清空 |
| 唯一性 | 每次 claim 随机 | 每次 NEW generation 唯一 + 永久 |
| 当前问题 | ✅ 适合 lease | ❌ 不适合 billing（被清空） |

**两者必须分离。** 不能用 generation_token 做计费幂等键（会被清空导致 response lost 重复计费）。

### 计费判定锚点（冻结）

**Billing truth = committed ComputeTransaction**（已提交的计费流水），而非仅仅 `client.chat` 成功。`_report_usage`（`daily_report_summary_service.py:193`）在 LLM `chat` 成功后执行，但其本身仍可能失败（9000↔9100 网络异常）。

- LLM 失败 → 不计费 → Generation 处于 unbilled/failed（但**仍存在**，不消失）
- LLM 成功 + `_report_usage` 成功 → ComputeTransaction 提交 → Generation 概念上处于 billed（账务真相以 M07 ComputeTransaction 为准，非 Generation 字段）
- LLM 成功 + `_report_usage` 失败 → ComputeTransaction 未提交 → Generation 概念上处于 unbilled → retry 复用同一 Generation

**Generation identity 在 LLM 调用前已持久化（计费点之前）**，因此无论计费成功与否，identity 始终存在并可恢复。这与"Generation 最多产生一次 charge"的账务不变量一致。

### Response-Lost 语义收口（Stage 5C-3R2 冻结方案 C）

**核心问题**：当 9100 已完成 LLM 并且 M07 已 commit ComputeTransaction，但 9000 没收到 HTTP 响应时，下一次调用如何处理？

**三选一决策（冻结方案 C）：**

| 方案 | 描述 | 结论 |
|---|---|---|
| A | Persist/reuse original generation result（请求级幂等，持久化 summary result + billing evidence，response-lost 后 find completed result 不重跑 LLM） | ❌ 侵入明显大于当前设计，需 summary result 持久化机制，扩大 P1 范围 |
| B | Re-run LLM but suppress billing（恢复时重新 `client.chat`，不再调 `report_usage`） | ❌ 第二次真实模型调用有供应商成本但不计费，Billing Policy 不明；summary 内容可能与第一次不同 |
| **C** | **P1 不解决 full-request response loss（推荐）** | ✅ **冻结 APPROVED** |

**冻结方案 C 理由：**
1. P1 解决的是 **Compute Idempotency / Financial Integrity**，不是重构 Daily Report 完整的跨进程请求级幂等系统
2. 当前无现成 summary result persistence，硬上方案 A 会明显扩大范围
3. 选 C 后 Stage 5C-4 保持最小（DailyReportGeneration 实体 + 9000→9100 透传 + billing-report replay），风险最低
4. 不虚假宣称 P1 已解决跨进程请求级幂等

**方案 C 冻结内容：**

#### DR-5（缩窄后）：Billing Report Response-Lost

- **same Generation + same usage report → replay**（M07 已完全可以保护）
- 9100 侧 `_report_usage` 重发同一 idempotency_key + 同一 payload_evidence → M07 IDEMPOTENT_REPLAY，不重复扣费
- 这是 P1 财务幂等的职责边界

#### SEPARATE_REQUEST_RECOVERY_GAP（新登记）

- **Full 9000→9100 response-lost after completed LLM**：9000 未收到 9100 响应 → 重新执行 LLM → 可能产生不同 usage
- M07 行为：same Generation key + different payload → **IDEMPOTENCY_CONFLICT**（正确行为，不重复扣费，发出警报）
- **不属于 P1 财务幂等职责** → 登记为 Daily Report 可靠性 Gap，后续独立处理
- P1 不虚假宣称已解决跨进程请求级幂等

---

## 最终 key 形态（方向，不冻结实现）

```
event_namespace = daily_report_job（稳定合同）
business_event_id = {job.id}:{generation_identity}:summary
idempotency_key = f"daily_report_job:{job_id}:{generation_identity}:summary"
```

---

## 实现方向（方案 B 已冻结 APPROVED）

### OPTION B APPROVED：独立持久 DailyReportGeneration 实体

职责分工（三层 identity 严格分离）：
- **DailyReportJob** = 哪份日报（parent identity，1:N）
- **DailyReportGeneration** = 哪次合法生成（billing identity，持久不可清空）
- **generation_token** = 当前执行权（lease，临时，finalize 后清空）

### DailyReportGeneration 最小字段（不冻结具体名）

| 字段 | 用途 |
|---|---|
| persistent id | 持久主键（billing identity 来源） |
| job_id | 指向 DailyReportJob（parent） |
| lifecycle/status | 支持 `generating` / `unbilled` / `billed` / `failed` 等状态 |
| created_at | 创建时间 |

每次 `_claim_generating` INSERT 一行新 DailyReportGeneration（与 generation_token 同事务 commit）。finalize **不清空** generation 行（只清 generation_token）。

> **注意**：Generation 可有执行生命周期状态（pending/running/failed/succeeded）用于执行编排，但**不得**让 `generation.is_billed` 成为账务真相。committed ComputeTransaction 是唯一 billing truth；Generation 上的 billed/unbilled 标记只是派生/缓存辅助状态，用于恢复决策，恢复时仍需以 M07 ComputeTransaction 为准（见实施约束 3）。

**不借 P1 重写 Daily Report 架构**：DailyReportJob 现有 claim/finalize 逻辑保留，DailyReportGeneration 只作为 billing identity 层叠加。

### 实施约束（3 条，Stage 5C-4 必须遵守）

**约束 1：Generation 创建与 claim 原子绑定**
- successful `_claim_generating` + create DailyReportGeneration → **same DB transaction**（与 generation_token 同 commit，`:220`）
- DailyReportGeneration 行的 INSERT 必须在 `_claim_generating` 的 commit 内完成，不能是独立事务
- DR-7 实施时必须断言：**NEW DailyReportGeneration rows = 1**（不只断言一个 409；要断言 claim 成功恰好创建 1 行 Generation）

**约束 2：恢复时确定性引用 Generation（不猜恢复对象）**
- **禁止** `ORDER BY id DESC` 取最新行猜测恢复对象
- Stage 5C-4 必须存在明确、持久的关联方式，使 restart/recovery → deterministic same generation：
  - Job 上持有 current/active generation reference，或
  - generation 状态上的唯一活动约束（同一 job 至多一个 active generation），或
  - 调用方显式携带 generation_id
- 恢复逻辑通过该确定性引用找到正确 Generation，而非按时间/序号猜

**约束 3：Billing truth 仍只属于 M07**
- Generation 可有执行生命周期（pending/running/failed/succeeded），用于执行编排
- **但不得新增 `generation.is_billed` 成为账务真相**
- **committed ComputeTransaction 仍是唯一 billing truth**
- Generation 里的 billing-related 状态（如 billed/unbilled）只能是**派生/缓存/可恢复辅助状态**，用于恢复决策，不作为账务权威

### 跨进程透传
- payload（`daily_report_service.py:555`）当前只含 merchant_id/report_day/summaries
- 需加 `report_job_id` + `generation_id`（DailyReportGeneration 持久 id）传到 9100
- 9100 `DailySalesSummaryRequest` schema 加对应字段，`_report_usage` 构造 `idempotency_key`
- 类比 M01 Stage 4B / Return Visit Stage 5C-1 的 9000→9100 透传模式

---

## 现在不二选一，只冻结的硬约束

1. **系统必须拥有持久、不可重用、可恢复的 per-generation identity**
2. **generation identity 在 `_claim_generating` commit 时生成（计费点之前）**
3. **generation identity finalize 后不清空（永久保留）**
4. **generation identity 每次新 generation 唯一（并发不撞同值）**
5. **lease identity（generation_token）≠ billing identity（generation identity）**
6. **Generation 在 LLM 调用前已持久化（计费点之前）；LLM/执行失败时 Generation 仍存在（unbilled/failed），不产新 Generation**
7. **Billing truth = committed ComputeTransaction（不只 `client.chat` 成功）；LLM 成功 + report 失败 → retry 复用同一 Generation**
8. **billing-report response-lost（same Generation + same usage report）→ M07 replay（P1 职责）；full 9000→9100 request-lost after completed LLM → SEPARATE_REQUEST_RECOVERY_GAP（非 P1 职责，M07 IDEMPOTENCY_CONFLICT 兜底）**
9. **Technical retry / process recovery / response-lost retry → always REUSE same Generation identity（无论是否已计费）；只有显式业务动作（首次/regenerate/manual retry）才 NEW**
10. **Stage 5C-4 实施约束**：(a) Generation 创建与 `_claim_generating` 同事务原子绑定；(b) 恢复时确定性引用 Generation，禁止 `ORDER BY id DESC` 猜测；(c) billing truth 只属于 M07 committed ComputeTransaction，Generation 不得新增 `is_billed` 成为账务真相，billing 状态仅作派生辅助

---

## 验收 Gate（7 个，Stage 5C-4 实施时验证）

| Gate | 场景 | 预期 |
|---|---|---|
| DR-1 | Initial Generate | G1 persistent / 1 txn / 1 debit |
| DR-2 | Same Generation Replay | report twice → 1 txn / replay |
| DR-3 | Explicit Regenerate | G1≠G2 / 2 txn / 2 charges |
| DR-4 | LLM Failure | G3 identity 仍持久 / 0 txn / 0 debit |
| DR-5 | **Billing Report Response-Lost**（缩窄） | same Generation + same usage report 重发 → M07 replay / 1 txn（commit 后 response-lost，billing-report replay；full-request recovery 见 SEPARATE_REQUEST_RECOVERY_GAP） |
| DR-6 | **Compute Report Failure**（与 DR-5 分开） | LLM success + report fail（**commit 前**）→ retry same G5 → 新 txn 首次成功计费（DR-6 是 commit 前 retry → 新 txn；DR-5 是 commit 后 response-lost → replay） |
| DR-7 | Concurrent Generate | 409 阻止并发 / only one NEW Generation（断言 NEW Generation rows = 1） |

---

## 待审批决策点

1. ~~方案 A vs 方案 B~~ → **方案 B 已冻结 APPROVED**
2. ~~response lost 恢复策略~~ → **方案 C 已冻结 APPROVED**：DR-5 缩窄为 billing-report replay（M07 保护）；full-request response-lost 登记 SEPARATE_REQUEST_RECOVERY_GAP（非 P1 职责，IDEMPOTENCY_CONFLICT 兜底）
3. 审查通过后授权 Stage 5C-4 实施（DailyReportGeneration 实体 + 9000→9100 透传 + 7 Gate + 3 实施约束）
