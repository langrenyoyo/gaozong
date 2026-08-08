# P1 Daily Report Generation Identity 技术设计（Stage 5C-3）

> 状态：TECHNICAL_DESIGN（只设计不实施）
> 前置：Stage 5C-2 已验真 DailyReportJob.id 是 1:N parent（结论 B）
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #10
> 范围：设计 generation identity，回答"什么动作创造一个新的、应单独收费的 Daily Report generation"

## 钉死的一句话

**一个 generation = 一次成功的 LLM summary 计费事件。** 任何导致 summary LLM 被重新调用并成功计费的 NEW generation attempt（首次生成 / 用户 regenerate）产生新 generation identity；技术性失败（LLM timeout/network/格式错误）**不计费不产 generation**；进程崩溃在计费前→恢复时复用同一 generation identity（不新建）。

核心判定锚点：**`_report_usage`（`daily_report_summary_service.py:193`）只在 LLM `chat` 成功后执行**。因此"是否产生新收费"= "LLM chat 是否成功"，与 claim/lease 无关。

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

**A 答**：`_claim_generating` 的 `db.commit()`（`:220`）在 LLM 调用（`:574`→`:177`）和计费点（`:193`）之前。**当前 generation_token 此时已持久化**——但它不满足 C（finalize 后清空）。

generation identity 必须**在 `_claim_generating` commit 时生成并持久化**，这样计费点（`:193`）执行时 identity 已存在且稳定。

---

## B. 什么动作产生新 Generation（每动作明确 NEW / REUSE）

核心规则：**只有"会成功调用 LLM 并计费"的 NEW attempt 才产新 generation identity。** 计费失败（LLM 没成功）→ 不计费 → 不产 generation（或复用上一次未消费的 generation，见 E）。

| 动作 | 新 Generation？ | 代码证据 |
|---|---|---|
| 首次 generate | **NEW** | `_get_or_create_job` 新建行（`:186`）+ `_claim_generating` 新 token（`:204`）→ LLM 调用 |
| 用户 regenerate | **NEW** | `regenerate_job`（`:400`）→ `generate_one`（`:415`）→ 同一 job 行，但新 `_claim_generating` 新 token（`:204`）+ 重新 LLM 调用。每次 regenerate 是独立合法 LLM 消费 |
| 技术性 retry（LLM timeout/network error） | **REUSE** | 9100 `summarize_daily_sales_feedback` chat 失败抛 `LLMRequestError`（`llm/client.py:143/148`）→ 9000 `daily_report_service.py:575` catch → 计为 `daily_summary_llm_failed` 诊断，**不调 `_report_usage`（计费点 `:193` 未执行）** → 不计费。9100/LLM client **均无自动 retry**（`llm/client.py:_post_json` 无重试；`xg_douyin_ai_cs_client.py:217 _post_json` 无重试）。失败直接返回，不会重发同一 summary |
| Process recovery（restart 重新 claim） | **REUSE**（若已计费）/ **NEW**（若未计费重做） | 见下文 E。当前 scheduler/reconcile **不会自动重新 claim 崩溃的 generating**（`daily_report_scheduler.py:189` 已有同键则 skip；`reconcile_job_deliveries` 只对账投递不重生报表）。stale generating（>30min）只能被用户主动 regenerate 触发（`_claim_generating:209-213`） |
| Response lost + consumer retry | **REUSE**（同 generation） | 9100 LLM 成功并计费（`:193`）后，若响应在传回 9000 途中丢失（9000→9100 HTTP 超时，`xg_douyin_ai_cs_client.py:232`），9000 catch 异常计 `llm_failed`。但 9100 侧计费已发生 → 重试时若复用同一 generation identity → replay（不重复计费）；若用新 identity → 重复计费。**必须 REUSE 才正确** |
| Manual retry（用户点"重试"按钮） | **NEW** | 等同 regenerate：router `regenerate_daily_report`（`:455`）→ `regenerate_job`。用户主动触发的重做是独立合法消费 |

**技术性 retry 是新消费还是 replay？答：replay（REUSE）。** 因为：
1. LLM client 和 HTTP client 均无自动 retry → 不存在"同一次 attempt 内多次调 LLM"
2. LLM 失败时 `_report_usage` 未执行 → 未计费 → 无需 generation
3. 只有成功的 LLM 调用才计费；而"成功后响应丢失"时计费已发生，重试必须复用 identity 才不重复扣费

---

## C. Generation identity 是否永久保留

**必须 YES。** 当前 `generation_token`（`_claim_generating:204`，`secrets.token_hex(16)`）是**临时租约令牌**，`_finalize_success`（`:247`）和 `_finalize_failure`（`:278`）后置 None 清空 → **不满足**。

理由（为什么必须永久保留）：
1. **Response lost 场景（B 第 5 行）**：9100 已计费但 9000 未收到响应；9000 重试时需读取原 generation identity 才能 replay（不重复计费）。若 identity 已清空 → 无法 replay → 重复计费
2. **审计回溯**：需将 ComputeTransaction 与具体 generation 对账

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
  - generation identity 已持久化（C 要求）
  - 但无自动恢复 → job 留在 generating 直到超时 → 用户 regenerate 触发 NEW generation
  - **问题**：若崩溃在"9100 已计费、响应未回到 9000"（response lost），9000 侧认为失败，用户 regenerate 会产生 NEW generation → **重复计费**
- **设计要求**：恢复时若发现 generation identity 已存在且对应 ComputeTransaction 已记录（计费已发生）→ 应复用该 identity（replay），不新建。这需要 generation identity 可被恢复逻辑读取并与计费记录对账

**是否会创建新 generation 而非恢复？** 当前会（因为 regenerate 总是新建 token）。设计需让"已计费的 generation"可识别并被恢复逻辑复用。

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

**只有 LLM `chat` 成功后才计费**（`daily_report_summary_service.py:193`，`_report_usage` 在 `client.chat` `:177` 之后）。LLM 失败/超时/格式错误 → 不计费 → 不产 generation。这简化了 generation 生命周期：**generation identity 对应一次成功的 LLM 计费**。

---

## 最终 key 形态（方向，不冻结实现）

```
event_namespace = daily_report_job（稳定合同）
business_event_id = {job.id}:{generation_identity}:summary
idempotency_key = f"daily_report_job:{job_id}:{generation_identity}:summary"
```

---

## 实现方向（只列方向，不冻结）

### 方案 A：字段
- DailyReportJob 加 `generation_attempt` 字段（持久化 + 不可清空 + 每次 NEW generation 递增）
- `_claim_generating` 递增 `generation_attempt`（与 generation_token 同事务 commit）
- finalize **不清空** `generation_attempt`（只清 generation_token）
- 优点：改动小（一个字段 + claim/finalize 调整）
- 风险：历史 generation 信息只存 ComputeTransaction（job 行只保留最新 attempt 序号）

### 方案 B：子表
- 新建 `DailyReportGeneration`（id / job_id / generation_no / status / created_at / 计费标记）
- 每次 `_claim_generating` INSERT 一行
- 优点：身份更明确，可记录每次 generation 状态与计费对账
- 风险：侵入更大（新表 + 迁移 + claim/finalize 改写）

### 跨进程透传（两方案都需要）
- payload（`daily_report_service.py:555`）当前只含 merchant_id/report_day/summaries
- 需加 `report_job_id` + `generation_attempt`（方案 A）或 `generation_id`（方案 B）传到 9100
- 9100 `DailySalesSummaryRequest` schema 加对应字段，`_report_usage` 构造 idempotency_key
- 类比 M01 Stage 4B / Return Visit Stage 5C-1 的 9000→9100 透传模式

---

## 现在不二选一，只冻结的硬约束

1. **系统必须拥有持久、不可重用、可恢复的 per-generation identity**
2. **generation identity 在 `_claim_generating` commit 时生成（计费点之前）**
3. **generation identity finalize 后不清空（永久保留）**
4. **generation identity 每次新 generation 唯一（并发不撞同值）**
5. **lease identity（generation_token）≠ billing identity（generation identity）**
6. **只有 LLM 成功才计费（`_report_usage` 在 chat 成功后）→ 技术性失败不产 generation**
7. **response lost 时重试必须复用原 generation identity（replay，不重复计费）**

---

## 待审批决策点

1. 方案 A（字段）vs 方案 B（子表）二选一
2. response lost 恢复策略：如何让"已计费 generation"可被恢复逻辑识别并复用（方案 B 的计费标记更天然；方案 A 需查 ComputeTransaction）
3. 是否在本轮实施，或继续标 DESIGN_GAP 处理 M05/Training/RAG
