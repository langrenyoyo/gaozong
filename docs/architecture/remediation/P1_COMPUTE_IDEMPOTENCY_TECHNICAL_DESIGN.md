# P1 COMPUTE-IDEMPOTENCY-001 技术方案设计

> 状态：TECHNICAL_DESIGN_APPROVED + IMPLEMENTATION_SCOPE_APPROVED + PHASE_3A_P1_IMPLEMENTATION_READY（设计阶段正式结束，进入实施）
> 代码基线：c26ec227e70d
> 风险等级：HIGH — FINANCIAL_INTEGRITY
> E2E 证据：Gate A（balance delta = 2 × charge）+ Gate F（M04 double charge E2E_VERIFIED_IMPACTED）

---

## 问题陈述

`record_usage`（apps/compute/services.py:537）无幂等键：
- 签名无 `idempotency_key` / `transaction_key` / `jti` 参数
- `ComputeTransaction` 表无 UniqueConstraint（models.py:927-993）
- `_write_transaction` 无去重查询（apps/compute/services.py:148-228）
- 每次 `record_usage` 调用都写一条新 consume 流水 + 扣余额 + 顶层一次 commit
- 重复调用（异常重入/HTTP retry）必然重复扣费

---

## A. 什么是"一次消费"的业务身份

### 定义

**一次消费 = 一个具体业务事件产生的一次算力计费。** idempotency identity 必须对应具体业务事件，不是业务上下文。

### 硬规则：Business Event ID 必须预先持久化

> **Business Event ID 必须在计费副作用发生之前已经稳定存在。**
> retry / process restart / duplicate delivery 必须复用同一个 ID。
> 优先使用已有持久化业务实体（AiAutoReplyRun.id / WebhookEvent.id / WechatTask.id / AiEditJob.id / MaterialAnalysis.id+version）。
> **不允许使用运行时计算序号（如 call_count）——进程重启/重试后序号不稳定。**

### Consumer Business Event Identity Matrix（正式合同表）

| Consumer | Charge Event | 稳定身份 | Retry 复用 | 多次合法收费 | Cardinality |
|---|---|---|---|---|---|
| M04 | Task result usage | WechatTask.id + operation（paste/sent） | 必须 | 通常 1 次 | 1:1（冻结：一个 WechatTask + 一个具体 charge operation → 最多一笔该类型 Compute usage；如存在多个合法收费阶段，event identity 必须包含 operation，不得只有 task id） |
| M06 | LAS archive usage | AiEditJob.id + archive operation | 必须 | 通常 1 次 | 1:1 |
| M01 | LLM usage | **待确认**：需绑定持久化 run/event（AiAutoReplyRun.id 是否可作为 LLM usage 的稳定 event identity？待确认） | 必须 | 同 conversation 可多次合法 | 1:N |
| M02 | webhook event charge | WebhookEvent.id + operation | 必须 | 按事实 | 1:1 |
| M05 | Material analysis | Material.id + analysis_version | 必须 | re-analysis 是新事件 | 1:N |

### M01 LLM Business Event Identity 正式标注

```
STATUS: DESIGN_OPEN_ITEM
Candidate: AiAutoReplyRun.id
Requirement: 必须在迁移 M01 consumer 之前用 Current Reality 事实确认：
  一个 AiAutoReplyRun 到底是否唯一对应一次 chargeable LLM event
不阻止 P1 开始实施，但限制实施范围：
  M01 不能在 identity 未确认时迁移
```

> **从正式方案中删除 `llm_call:{conversation_id}:{call_count}`**（运行时计算序号不稳定，进程重启/重试后无法复用）。
>
> 替换为需绑定持久化 run/event ID 的设计方向。
>
> 待确认项：
> - 如果 AiAutoReplyRun 每次 LLM 调用都有独立行 → `ai_auto_reply_run:{run.id}` 可用
> - 如果一个 run 内有 retry（多次 LLM 调用）→ 需确认 retry 是否产生新 run 行或需子序号
> - 如果是 preview（非 auto-reply run）→ 需确认是否有持久化实体可绑定
> - **不强行指定方案，待确认后补入**

### 关键约束

> **兼容陷阱**：`idempotency_key = merchant + conversation_id + model` → 同一会话第 1 次和第 2 次真实 LLM 消费会被错误去重。
>
> **idempotency identity 必须对应具体业务事件，不是业务上下文。** conversation_id 是上下文不是事件。

### 设计结论

每个 consumer 传入一个 **business_event_id**（字符串），代表"这一笔只允许扣一次"的业务事件唯一标识。M07 不派生，由 consumer 生成（consumer 最清楚自己的业务事件边界）。Business Event ID 必须预先持久化。

---

## B. 幂等键由谁生成

### 方案：Consumer 生成 + M07 存储

| 层 | 职责 |
|---|---|
| Consumer | 生成 `idempotency_key`（基于自己的持久化业务事件 ID） |
| M07 | 存储 `idempotency_key` 到 ComputeTransaction，DB 唯一约束兜底 |

### 幂等 namespace 与可变 source 分离

```
idempotency_key = f"{event_namespace}:{business_event_id}"
```

- **event_namespace** = 稳定合同标识符（参与幂等身份，**不得随 source 重命名/模块调整而改变**）
- **business_event_id** = 稳定事件身份（预先持久化的业务实体 ID）
- **source** = 运营归因（observability，**不参与幂等身份**）

> **REQUIRED-4 硬规则**：event_namespace 是幂等合同的一部分，source 只是运维标签。如果未来 source 从 "wechat-assistant" 改为 "m04_task"，event_namespace 不变。

### 为什么不由 M07 派生

M07 不知道 consumer 的业务事件边界（conversation_id 是上下文不是事件）。consumer 最清楚"什么是一次消费"。

---

## C. 幂等作用域

### 方案：merchant_id + idempotency_key

```
UniqueConstraint(merchant_id, idempotency_key)
```

- **不跨商户误判重复**：不同 merchant 相同 idempotency_key 各自独立
- **不跨 event_namespace 误判重复**：namespace 前缀确保不同 consumer 的 event_id 不冲突
- **不跨业务事件误判重复**：同一 conversation 的两次合法 LLM 消费有不同 business_event_id

### 不需要的字段

- 不需要 `source` 参与唯一约束（event_namespace 已在 idempotency_key 中）
- 不需要 `capability_key` 参与唯一约束（同一事件不会跨 capability）

---

## D. DB 原子性

### 冻结正式 invariant（REQUIRED-3）

```
首次调用：
  INSERT transaction → 成功 → 获得 ownership → UPDATE balance → COMMIT → 返回 transaction

重复调用：
  INSERT transaction → UNIQUE CONFLICT → 读取已存在 transaction → 校验 payload 一致
    → DO NOT UPDATE balance → 返回原 transaction
```

> **关键不变量：只有成功创建幂等流水的那个事务拥有修改余额的权利。**
> **绝不能 INSERT ON CONFLICT 后不管是否成功都继续 UPDATE balance。**

### Idempotency Payload Evidence Invariant

> **对于每一笔带 idempotency identity 的成功 ComputeTransaction，M07 必须持久化足够的 immutable consistency evidence，使任何未来 retry 都能够判断：**
>
> - A. Same Key + Same Stable Semantic Billing Inputs → IDEMPOTENT_REPLAY
> - B. Same Key + Different Stable Semantic Billing Inputs → IDEMPOTENCY_CONFLICT
>
> 具体实现留给实施窗口选择（canonical payload fingerprint / DB 保存 stable input fields / 两者结合）。
> 不冻结字段名、hash 算法、JSON 结构。
> **但"必须有可持久化的 Payload 一致性证据"是正式设计合同。**

### DB 约束兜底 + 单事务原子单元

```
record_usage(db, merchant_id, tokens, *, idempotency_key, ...):
  1. INSERT INTO compute_transactions (..., idempotency_key=...)
     ON CONFLICT (merchant_id, idempotency_key) DO NOTHING RETURNING id
  2. 若 RETURNING 有行 → 获得 ownership → 继续扣余额（同一事务）
     若 RETURNING 无行 → 已存在 → 校验 payload 一致 → 幂等返回（不扣余额）
  3. UPDATE compute_accounts SET balance_tokens = balance_tokens - billed_tokens
     WHERE merchant_id = ? (with_for_update)
  4. COMMIT
```

### Idempotency Payload Consistency Contract（REQUIRED-2 + 最终修正）

#### 应参与一致性判断（stable business billing inputs）

- `capability_key` / charge type
- model identity（如果该消费按 model 区分）
- raw usage quantity（tokens）
- usage unit/type（usage_measurement_method）
- consumer-defined business operation（event_namespace + business_event_id 的语义等价性）

> 具体按现有 `record_usage` 合同填写。

#### 不应参与一致性判断（mutable/derived pricing state）

- 计费比例（ratio / basis_points）
- 重新计算后的 billed amount
- 当前配置变化后的价格

#### 核心原则

> **Idempotency payload consistency 应比较稳定的业务事件输入，不是 retry 时基于当前配置重新计算的可变派生价格。**
>
> 首次交易成功后，duplicate replay 返回原 transaction + 原 billed amount + 原 balance_after。
> **不重新定价。**

#### 行为冻结

| 场景 | 行为 |
|---|---|
| Same Key + Same Stable Business Billing Inputs | **IDEMPOTENT_REPLAY**（即使 pricing config 已变化） |
| Same Key + Different Stable Business Billing Inputs | **IDEMPOTENCY_CONFLICT**（不扣费，不覆盖原流水，记录异常/告警） |

> 具体 payload fingerprint 比较留给实施设计，但行为现在冻结。

### 失败场景分析

| 场景 | 行为 |
|---|---|
| INSERT 成功 + balance UPDATE 成功 + commit 成功 | 正常，一次扣费 |
| INSERT 成功 + balance UPDATE 失败 → rollback | 事务回滚，INSERT 也回滚，下次重试可重新 INSERT |
| INSERT 成功 + balance UPDATE 成功 + commit 失败 → rollback | 同上 |
| INSERT 成功 + commit 成功 + HTTP response 丢失 + consumer retry | ON CONFLICT DO NOTHING → 幂等返回，不重复扣 |

---

## E. 重复调用返回什么

### 方案：200 + 原交易结果

```
重复调用 → 返回已有的 ComputeTransaction（不抛异常、不写新流水、不扣余额）
```

- **不返回 409**（幂等 API 应把重复视为"已成功完成的同一请求"）
- **不返回 duplicated=true**（consumer 不需要区分首次/重复，只需知道"这次消费已记账"）
- 返回值与首次成功调用一致

### Observability 补充

> 重复调用内部区分 `created` vs `idempotent_replay`（不一定暴露给 API 响应，但运维可追踪）。

### 内部 HTTP 上报（M01 9100 → 9000）

- 重复 POST `/internal/compute/usage` → 200 + 原结果
- ComputeUsageClient 已"绝不抛异常"（compute_usage_client.py:216），幂等后更安全

---

## F. 失败边界

### 必须保证的账本不变量

1. **同一 idempotency_key 最多一笔 transaction**（DB UniqueConstraint 兜底）
2. **同一 idempotency_key 最多一次余额修改**（只有获得 ownership 的事务才扣余额）
3. **balance_tokens == initial + sum(delta_tokens)**（ledger invariant，Gate C 已验证 sequential）

### 不可能场景

| 场景 | 是否可能 | 原因 |
|---|---|---|
| 重复 transaction 无余额修改 | ❌ 不可能 | 只有获得 ownership 的事务才扣余额 |
| 余额修改无 transaction | ❌ 不可能 | 同一事务原子 |
| 重复 transaction + 重复余额修改 | ❌ 不可能（修复后） | ON CONFLICT DO NOTHING，未获得 ownership 不扣余额 |

### 残留风险

- **commit 成功 + response 丢失 + consumer retry**：幂等返回，不重复扣 ✓
- **commit 失败 + consumer retry**：事务回滚，下次 INSERT 不冲突，正常扣一次 ✓
- **并发同 idempotency_key**：DB ON CONFLICT 保证只有一个 INSERT 成功，另一个 DO NOTHING ✓

---

## G. 老消费者兼容

### 兼容窗口 + 迁移计划 + Closure Gate（REQUIRED-5）

| 阶段 | 行为 | 风险 | Closure |
|---|---|---|---|
| 阶段 1：idempotency_key 可选 | `idempotency_key=None` 时走旧逻辑（无去重，裸扣） | 旧 consumer 不报错，但无幂等保护 | None 调用必须可计数/可追踪到 consumer |
| 阶段 2：逐个迁移 consumer | 每个 consumer 改为传入 idempotency_key | 迁移一个保护一个 | — |
| 阶段 3：idempotency_key 必填 | `idempotency_key=None` → raise ValueError | 所有 consumer 必须已迁移 | **production charge-producing consumers using None = 0** |

> **COMPUTE-IDEMPOTENCY-001 在 Phase 1/2 期间仍然 OPEN**（None 调用仍可重复扣费）。
> **Required enforcement 必须落实到 M07 核心 service contract（record_usage），不能只在 HTTP API。**

### 迁移顺序（按 E2E_IMPACTED 优先）

1. M04 `_report_wechat_task_compute_usage`（E2E_VERIFIED_IMPACTED，最高优先）
2. M06 `_report_las_compute_usage`（CODE_VERIFIED_EXPOSED）
3. M01 `compute_usage_client.report_usage`（CALL_SITE_IDENTIFIED，HTTP 入口）
4. M02 `douyin_webhook` leads（CALL_SITE_IDENTIFIED）
5. M05 `material_analysis`（CALL_SITE_IDENTIFIED）

### 不能做的事

- ❌ 不能直接新增 required 参数导致所有旧 consumer 瞬间报错
- ❌ 不能无限期允许 `idempotency_key=None` 继续裸扣
- ✅ 阶段 1 兼容 + 阶段 2 逐个迁移 + 阶段 3 必填

---

## H. 回归与验收

### Must-Preserve Behavior（修复后不能破坏的行为）

1. 正常两次不同业务消费 → 两条 transaction + 两次扣余额（不能误去重）
2. 同一 business_event retry → 一条 transaction + 一次扣余额（幂等）
3. Ledger invariant：balance == initial + sum(delta)
4. Merchant isolation：A 不能读/写 B 的 transaction/balance
5. 负余额行为不变（CODE_VERIFIED，POLICY_PENDING）
6. Fee/ratio 计算不变（sampled path verified）

### Acceptance Gates

| Gate | 场景 | 预期 |
|---|---|---|
| 1 Sequential duplicate | 同一 idempotency_key 调用两次 | 1 条 transaction，balance delta = 1 × charge |
| 2 Concurrent duplicate | 并发同一 idempotency_key | 1 条 transaction，无 lost update |
| 3 Two legitimate usages | 不同 idempotency_key（同 context 不同 event） | 2 条 transaction，balance delta = 2 × charge |
| 4 Ledger invariant | balance == initial + sum(delta) | PASS |
| 5 M04 duplicate result → compute | 重复 _report_wechat_task_compute_usage | 1 条 transaction（ISSUE-M04-002 CLOSED） |
| 6 M06 exposed path | 重复 _report_las_compute_usage | 1 条 transaction |
| 7 Merchant isolation | A 不能读写 B | PASS |
| 8 Failed-retry | commit 失败 + retry | 1 条 transaction |
| 9 Old consumer (idempotency_key=None) | 阶段 1 兼容 | 旧逻辑不报错（无去重） |
| **10** | **Same Key + Different Stable Payload** | E1 stable payload A → commit / same E1 key stable payload B → retry → **IDEMPOTENCY_CONFLICT** / transaction count = 1 / balance unchanged / original transaction unchanged / original payload evidence unchanged（不被第二次请求覆盖）/ conflict observable |
| **11** | **Same Context + Two Legitimate Events** | **two keys / two transactions / two legitimate charges** |
| **12** | **Retry After Pricing Configuration Change** | business event E1 usage=100 price V1 → charge 100 → commit；修改计费比例到 V2；同 E1 retry → **仍 IDEMPOTENT_REPLAY** / transactions 仍 1 条 / balance 不再变化 / 返回第一次结果 / 不二次扣费 / 不报 IDEMPOTENCY_CONFLICT |

### P1 CLOSURE MANDATORY GATE（REQUIRED-6）

> **PostgreSQL Concurrent Duplicate Gate = REQUIRED FOR P1 CLOSURE**
>
> 两请求 same merchant + same business event + same idempotency identity 并发进入。
> 结果：transaction +1 / balance 只扣一次 / 两请求获得同一结果 / ledger invariant 成立。
> **SQLite 不能替代。**

> **既有失败基线（PG Closure 验收时区分 baseline 噪声 vs P1 回归，不得笼统记为"10 existing failures"）**：
> PG Closure 前后端专项存在既定红灯集，非 P1 引入，closure 验收须按"零新增回归"放行而非"历史全绿"。保留具体测试集合引用：
> - `tests/test_phase10_compute_schema.py`（SQLite schema 合同断言，如 `test_phase10_sqlite_migration_files_exist` / `test_sqlite_0031_rebuilds_only_two_compute_tables`）
> - `tests/test_phase10_compute_no_network.py`（组合跑 401 鉴权中间件污染，单独跑 PASSED；见 `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md`）
> - SQLite 迁移 `migrations/versions/0031_compute_billing.sql`（0031 compute billing，与 PG Alembic `0030` / `0032` 分属 SQLite-SQL / PG-Alembic 两套迁移系统，编号相近易误读）
> 这些是 PG Closure 前的 baseline 红灯，不得与 P1 幂等回归混计。

### PG CORE RELEASE GATE（新增）

> **在 M07 Core 实现完成后、Consumer 迁移前，至少跑一次 PostgreSQL：**
>
> same merchant + same idempotency identity + two concurrent requests
> 结果：1 transaction / 1 balance mutation
>
> **通过后才允许幂等能力进入生产 Consumer。**
>
> 即：PG concurrency = core rollout safety gate + final P1 closure gate（两次验证）。

### PG Closure Gate 三态冻结（REQUIRED，Stage 5D 冻结）

PG Closure Gate 最终结果为以下三态之一：

**PASS**
- 所有 active charge-producing paths 满足以下之一：
  - A. stable idempotency identity migrated → charge path `idempotency_key=None` = 0
  - B. formally approved non-chargeable policy → charge-producing call removed
- + Global charge path audit clean
- + PG final concurrency closure gate PASS
- + required PG migrations verified（含 `0030→0032` alembic upgrade + FK/约束 + DR-7 PG 并发语义）

**FAIL**
- 仍存在未批准的 active `None` charge path
- 或 PG 验证失败

**WAIVED_WITH_ACCEPTED_RESIDUAL_RISK**
- 管理层正式接受剩余风险并允许阶段退出
- 但 COMPUTE-IDEMPOTENCY-001 **不得**标记 E2E_VERIFIED_FIXED（技术事实不被治理语言掩盖）

> **关键：Risk Acceptance 可结束项目动作，但不能把技术 Gate 从 FAIL 变 PASS。** 治理语言（"接受剩余风险"）不等于技术修复（"charge-producing + None = 0"）；WAIVED 态下根因仍技术性 OPEN，仅被管理层有条件豁免。

### 防止误去重

> **关键验收**：同一 conversation_id 的两次真实 LLM 消费（不同 business_event_id）必须产生两条 transaction。如果 idempotency_key 误用 conversation_id 而非持久化事件 ID，第二次合法消费会被错误去重。

### Cross-module Regression

- M04：_report_wechat_task_compute_usage 重复调用 → 1 条（ISSUE-M04-002 CLOSED）
- M06：_report_las_compute_usage 重复调用 → 1 条（ISSUE-M06-003 CLOSED）
- M01：compute_usage_client HTTP retry → 1 条
- M02：webhook event 重复 → 1 条
- M05：material re-analysis → 不同 version 不同 transaction

---

## Migration Impact

### DB Migration

`compute_transactions` 新增：
- `idempotency_key`（幂等身份，String, nullable=True 阶段 1）
- **persisted semantic consistency evidence**（stable payload 一致性证据，实现留给实施审批）
- `UniqueConstraint(merchant_id, idempotency_key)`（nullable 时 NULL 不参与唯一约束，兼容阶段 1）
- 阶段 3 必填后可加 NOT NULL（但需确保所有历史行已回填或接受 NULL）

### API Migration

- `record_usage` 签名加 `idempotency_key: str | None = None`（阶段 1 可选）
- `/internal/compute/usage` HTTP 入口加 `idempotency_key` 字段（阶段 1 可选）
- ComputeUsageClient.report_usage 加 `idempotency_key` 参数（阶段 1 可选）

### Consumer Migration

- 5 个 consumer 逐个改为传入 `idempotency_key`
- 每个 consumer 迁移后立即获得幂等保护

---

## Backward Compatibility

| 场景 | 阶段 1（可选） | 阶段 3（必填） |
|---|---|---|
| 旧 consumer 不传 idempotency_key | ✓ 走旧逻辑（裸扣，无去重） | ❌ raise ValueError |
| 新 consumer 传 idempotency_key | ✓ 幂等保护 | ✓ 幂等保护 |
| 旧 HTTP 上报不传 idempotency_key | ✓ 走旧逻辑 | ❌ 400 |

---

## Rollback Strategy（REQUIRED-7：code-first / schema-last）

| 阶段 | 回滚方式 |
|---|---|
| Consumer rollback | 先回滚 consumer 代码（不再传 idempotency_key → 走旧逻辑） |
| M07 application rollback | 回滚 record_usage 代码（移除 idempotency_key 参数 → 旧逻辑） |
| 确认旧代码不依赖新字段 | 验证旧代码不引用 `idempotency_key` 列 |
| Schema rollback（最后才考虑） | nullable 字段和 unique index 通常不需要第一时间删除；如需删除才 DROP |

> **不把 DROP 列作为首选安全回滚策略。** 新增 nullable 字段和 unique index 通常不需要第一时间删除。

---

## 不冻结的实现细节

以下留给实施审批：
- 具体字段名（`idempotency_key` vs `dedup_key` vs `business_event_id`）
- 具体 SQL 语法（ON CONFLICT vs INSERT OR IGNORE + 查询）
- idempotency_key 的具体格式（`event_namespace:event_id` 的具体拼接方式）
- payload fingerprint 比较的具体实现
- 迁移文件编号
- 测试文件结构
- M01 LLM event identity 的具体方案（待确认 AiAutoReplyRun.id 后补入）

---

## 总结

| 问题 | 回答 |
|---|---|
| A. 一次消费的业务身份 | consumer 侧持久化业务实体 ID；M01 LLM 待确认 AiAutoReplyRun.id；运行时序号不可用 |
| B. 幂等键由谁生成 | Consumer 生成 `idempotency_key = f"{event_namespace}:{business_event_id}"`；event_namespace 稳定不随 source 变 |
| C. 幂等作用域 | `UniqueConstraint(merchant_id, idempotency_key)` |
| D. DB 原子性 | ON CONFLICT DO NOTHING RETURNING 获得 ownership → 只有 owner 扣余额；Same Key + Same Stable Inputs = IDEMPOTENT_REPLAY（不重新定价）；Same Key + Different Stable Inputs = IDEMPOTENCY_CONFLICT |
| E. 重复调用返回什么 | 200 + 原交易结果（原 billed amount + 原 balance_after，不重新定价）；内部区分 created vs idempotent_replay |
| F. 失败边界 | 只有获得 ownership 的事务才扣余额；commit 失败回滚可重试；commit 成功 retry 幂等 |
| G. 老消费者兼容 | 阶段 1 可选（None 可追踪）→ 阶段 2 逐个迁移 → 阶段 3 必填（None=0 closure gate） |
| H. 回归验收 | 12 个 Acceptance Gate + PG Concurrent Mandatory Gate + 防误去重 + Payload Consistency + Retry After Pricing Change |

---

## Charge Path Migration Register（全局审计 + 身份验真，Stage 5D-R1 冻结版）

> 完整 11 条 charge-producing 路径审计（原 #10 RAG Embedding 按 query/ingest 两条调用链拆为 #10a/#10b）。Identity Readiness 枚举：IDENTITY_VERIFIED / IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED / CANDIDATE_IDENTITY_VERIFIED / EXECUTION_IDENTITY_DESIGN_GAP / CHILD_EXECUTION_IDENTITY_DESIGN_GAP / LIFECYCLE_ORDERING_CHANGE_REQUIRED / TECHNICAL_DESIGN_AUTHORIZED / CHARGEABLE / POLICY_PENDING。多维度复合标签用 `/` 分隔（身份候选 / 计费状态 / 产品策略 / 生命周期）。

| # | Charge Path | 调用点 | Charging | Identity | Billing Semantics | Identity Readiness | idempotency_key | Migration |
|---|---|---|---|---|---|---|---|---|
| 1 | M04 WeChat Task | `wechat_task_service.py:503` | ACTIVE | WechatTask.id + operation | one task + one charge op = one charge | IDENTITY_VERIFIED | `wechat_task:{task.id}:result_usage` | ✅ MIGRATED |
| 2 | M06 LAS Archive | `ai_edit_las_service.py:740` | ACTIVE | AiEditJob.id + operation | one job + archive = one charge | IDENTITY_VERIFIED | `las_job:{job.id}:archive_usage` | ✅ MIGRATED |
| 3 | M01 Auto Reply | `reply_decision_service.py:3801` | ACTIVE | Run.id + attempt_count + stage | 1 Run : N attempts × 2 stages | IDENTITY_VERIFIED | `ai_auto_reply_run:{run_id}:{attempt}:{stage}` | ✅ MIGRATED |
| 4 | M02 Webhook Lead | `douyin_webhook.py:1242` | ACTIVE | WebhookEvent.id + operation | one event = one lead charge | IDENTITY_VERIFIED | `webhook_event:{event.id}:lead_usage` | ✅ MIGRATED |
| 5 | Return Visit Judge | `return_visit_judge_service.py:274` | ACTIVE | ReturnVisitRun.id | ReturnVisitRun 有 UniqueConstraint(idempotency_key)；run.id 在 judge 前已 flush；1:1 cardinality（一个 run = 一次 judge） | IDENTITY_VERIFIED | `return_visit_run:{run.id}:judge` | ✅ MIGRATED |
| 6 | Daily Report Summary | `daily_report_summary_service.py:146` | ACTIVE | DailyReportGeneration.id（独立 billing identity，方案 B） | DailyReportJob.id 是 1:N parent；每次 claim 创建独立 DailyReportGeneration 行作 billing identity（持久不可清空，finalize 只更新 lifecycle 不删行）；billing-report replay only（full-request response-lost 登记为 DAILY_REPORT_REQUEST_RECOVERY_GAP） | IDENTITY_VERIFIED | `daily_report_generation:{generation_id}:summary` | ✅ IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED（Stage 5C-4） |
| 7 | M01 Preview | `reply_decision_service.py:3801` | ACTIVE | 无 Run | conversation_id="agent-preview" 共用 | CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP | None | ⏸ 需 Preview execution identity 设计（POLICY_PENDING 不停止 identity 设计，现在就应设计） |
| 8 | M05 Material Analysis | `material_analysis.py:253` | ACTIVE | 无 per-execution identity | ark_v1 固定分析器版本；re-analysis 更新同一行 id 不变 | EXECUTION_IDENTITY_DESIGN_GAP | None | ⏸ NOT MIGRATED；方向：不破坏共享行模型新增 per-execution 层（不称"永续"） |
| 9 | Training Knowledge | `knowledge_training_service.py:481` | ACTIVE | training_id 后置（候选 key `knowledge_training:{training_id}:ask`） | training_id 在 _report_usage 之后才生成+commit | CANDIDATE_IDENTITY_VERIFIED / LIFECYCLE_ORDERING_CHANGE_REQUIRED / TECHNICAL_DESIGN_AUTHORIZED | None | ⏸ 不升级 READY_TO_MIGRATE，等 5D-1 钉死 retry cardinality |
| 10a | RAG Query Embedding | `rag/repository.py:441`（search path） | ACTIVE | 无 per-query execution identity | Milvus path → fallback SQLite path；MINOR VERIFICATION：确认同一逻辑 Search Request 内是否再次进入 query embedding helper（1:1→search_request_id 可行；多次→需 operation/attempt 维度） | EXECUTION_IDENTITY_DESIGN_GAP | None | ⏸ 需 scope 决策 |
| 10b | RAG Ingest Chunk Embedding | `rag/repository.py:546,692`（ingest path） | ACTIVE | 无 stable per-chunk execution discriminator | Parent: Training Run.id VERIFIED（embedding 前持久化）；1 Run : N chunk charges；缺 per-chunk discriminator（same chunk retry→same id / different chunk→different id / new run→different id） | CHILD_EXECUTION_IDENTITY_DESIGN_GAP | None | ⏸ 需 per-chunk identity 设计（不预设必须 embedding 前 INSERT chunk row，先检查更小稳定 discriminator：run_id + document identity + deterministic chunk ordinal/hash） |

**汇总：6/11 MIGRATED / 5/11 OPEN（#7 Preview / #8 M05 / #9 Training / #10a RAG Query / #10b RAG Ingest）。**

> **Open 路径统一风险描述（C4/C5，Stage 5D-R1 冻结）**：所有 5 条 Open 路径 `idempotency_key=None` → **无 M07 业务事件幂等保护**（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）。重复扣费暴露证据等级 = **CODE_VERIFIED_EXPOSED**（非 E2E_VERIFIED_DOUBLE_CHARGE，未经受控 E2E 复现）。不得把"存在 record_usage 调用"夸大为 E2E 证明重复扣费。

### Stage 5B 身份验真详情

#### RAG Query Embedding（#10a — EXECUTION_IDENTITY_DESIGN_GAP）

- **触发动作**：search path 一次 query embedding API 调用（`repository.py:441`）；Milvus path → fallback SQLite path
- **持久实体**：无 per-query execution identity（search request 非持久化）
- **retry**：无 retry 机制（embedding 失败 → 空 embedding → 词法检索降级）
- **MINOR VERIFICATION ITEM**：确认同一逻辑 Search Request 内是否再次进入 query embedding helper（1:1 → `search_request_id` 可行；多次 → 需 operation/attempt 维度）
- **结论**：query embedding 无前置持久 identity → **EXECUTION_IDENTITY_DESIGN_GAP / ⏸ 需 scope 决策**
- **设计方向**：若 1:1 则 `search_request_id` 可行；若多次则需 operation/attempt 维度
- **重复扣费暴露**：`idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE）

#### RAG Ingest Chunk Embedding（#10b — CHILD_EXECUTION_IDENTITY_DESIGN_GAP）

- **触发动作**：ingest path 每 chunk 一次 embedding API 调用（`repository.py:546,692`）
- **Parent**：Training Run.id VERIFIED（embedding 前已持久化）；charge cardinality = 1 Run : N chunk charges
- **缺失**：stable per-chunk execution discriminator（knowledge_chunks 表有 `id` + `document_id` + `chunk_index`，但 `_embed_with_usage` 调用时 chunk 行尚未 INSERT → embedding 在 INSERT 前）
- **re-embedding**：重新训练时删除旧 chunks 重新 ingest → 新 chunk 行 → 新 id
- **结论**：parent identity 已验证但 child per-chunk identity 缺失 → **CHILD_EXECUTION_IDENTITY_DESIGN_GAP**
- **设计方向（未冻结）**：不预设"必须 embedding 前 INSERT chunk row"，先检查更小稳定 per-chunk discriminator（`run_id` + document identity + deterministic chunk ordinal/hash），需满足：same logical chunk retry→same identity / different chunk→different identity / new run→different identity
- **重复扣费暴露**：`idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE）

#### Return Visit Judge（IDENTITY_VERIFIED — MIGRATED，Stage 5C-1）

- **触发动作**：一次 ReturnVisitRun → `_judge_via_9100` → 9100 `_report_usage`
- **持久实体**：`ReturnVisitRun.id`（`models.py:1113`），有 `UniqueConstraint(idempotency_key)`
- **run.id 在 judge 前已 flush**：`return_visit_run_service.py:306` `db.flush()` 后才调 `process_return_visit_run`（line 442），judge 在 `_process_run_with_session` 内
- **retry**：复用同一 run.id（idempotency_key 去重）
- **cardinality**：1:1（一个 run = 一次 judge 调用）
- **结论**：**IDENTITY_VERIFIED — MIGRATED**（Stage 5C-1）
- **迁移实现**：9000 `_judge_via_9100` 传 `return_visit_run_id=run.id`（claim 前 commit 持久化快照）→ 9100 `ReturnVisitJudgeRequest.return_visit_run_id` → `_report_usage` 构造 `return_visit_run:{run_id}:judge`。getattr 兼容测试双打（与 M01 `_report_llm_usage` run_id/attempt_count 同模式）。

#### Daily Report Summary（Stage 5C-2 验真结论 B + Stage 5C-4 迁移 MIGRATED）

**Stage 5C-2 验真问题与证据（file:line）：**

**Q1：DailyReportJob.id 是否在 summary LLM 调用前稳定持久化？**
- 三阶段生成（`daily_report_job_service.py:315 generate_one`）：阶段一 `_get_or_create_job`（`:176`）create-or-get + `_claim_generating`（`:202`，`db.commit()` at `:220`）→ 阶段二事务外 `_build_daily_report` → 调 9100 summary（`daily_report_service.py:574`）
- **Q1 答**：✅ 是。`_claim_generating` 在 `_post_json` 调用 9100 前已 `db.commit()`（`:220`），job.id 已持久化。满足前置持久化条件。

**Q2：Retry 是否复用 Job.id？**
- `_get_or_create_job`（`:176-199`）按 `(merchant_id, report_day, report_type, report_variant)` 查 existing，存在则返回既有行（`:184-185`）。`UniqueConstraint("merchant_id","report_day","report_type","report_variant")`（`models.py:1280`）阻止同键新建。
- 任何 retry/regenerate（`regenerate_job` `:400` → `generate_one` `:415`）走同一 `_get_or_create_job`，**复用同一 job.id**（不变）。
- **Q2 答**：✅ 是。所有 retry/regenerate 复用 same job.id；UniqueConstraint 阻止同键新建。

**Q3：一个 Job 是否可能合法收费多次？**
- regenerate 语义：同一 Job 生命周期内，summary LLM 可被合法调用多次（first generate + 失败后 regenerate + 日常重新生成）。每次都是真实合法 LLM 消费（`summarize_daily_sales_feedback` 每次都调 `_report_usage` `:193`）。
- 若用 `daily_report_job:{job.id}:summary`，则 regenerate（同 job.id）会被误去重为 replay，**漏扣合法重新生成的 LLM 消费**。
- **Q3 答**：✅ 是。1 Job : N 次合法 summary 计费事件。job.id 只能做 parent identity，不能做 chargeable event identity。

**Q4：合法重新生成是更新同一 Job 还是新建？**
- `_get_or_create_job` 复用同一行（`:184-185`）；`_finalize_success`/`_finalize_failure` 是条件 UPDATE（按 `job_id + generation_token`，`:236-251`/`:271-281`），**不新建行**。
- 每次生成有独立 `generation_token`（`secrets.token_hex(16)`，`:204`），但生成结束即清空（finalize 后置 None，`:247`/`:278`）→ **generation_token 是租约令牌不是持久化身份**，生成后丢失，不可做幂等维度。
- **无持久化 generation/attempt/version 字段**：DailyReportJob 字段（`models.py:1288+`）只有 id/merchant_id/report_day/report_type/report_variant/status/file_*/generated_at 等，无 attempt_count 或 generation 序号。`generation_version`（`:218`）是固定常量 `"daily_report_v1"`（`:68`），非 per-execution identity。
- **Q4 答**：复用同一 Job（不新建）。无持久化 generation 维度，无法区分同 job 的多次合法生成。

**结论 B：1:N（Job 是 parent，多个合法 generation）**

- DailyReportJob.id 满足 Q1（前置持久化）+ Q2（retry 复用），但 **Q3 判定它是 parent 不是 chargeable event**——一个 Job 生命周期内可被合法收费 N 次（regenerate/重试），job.id 单独做 key 会误去重。
- 需 generation 维度身份才能安全迁移（类似 M01 的 attempt_count），但当前**无持久化 generation/attempt 字段**（generation_token 是临时租约令牌，生成后清空）。
- **当前迁移状态：DESIGN_GAP（等价 Stage 5C-2 前），但身份候选已找到（job.id 作 parent），只差 generation 维度**
- **设计方向（不实施）**：
  1. 引入持久化 `generation_attempt` 字段（每次 `_claim_generating` 递增，finalize 保留不清空），或
  2. 用独立 `daily_report_generation` 子表记录每次生成（job_id + attempt + started_at + 持久化 token）
  3. 迁移 key 形态：`daily_report_job:{job.id}:{attempt}:summary`（类比 M01 `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}`）
- **跨进程透传**：除 generation 维度外，还需 9000→9100 透传（payload `daily_report_service.py:555` 当前只含 merchant_id/report_day/summaries，不含 job_id → 需加 report_job_id + generation_attempt，类似 M01 Stage 4B）

**Stage 5C-4 迁移实施（MIGRATED）：**
- **方案 B 冻结**：新建 `DailyReportGeneration` 独立持久实体（`models.py`），每次 `_claim_generating` 同事务创建一行作 billing identity（持久不可清空，finalize 只更新 lifecycle 不删行）
- **Identity 合同**：`daily_report_generation:{generation_id}:summary`（event_namespace=`daily_report_generation`，business_event_id=`{generation_id}:summary`）
- **三层 identity 严格分离**：DailyReportJob(parent) / DailyReportGeneration(billing) / generation_token(lease 临时)
- **3 实施约束已落地**：(1) Generation 创建与 claim 同事务原子绑定；(2) `job.current_generation_id` 确定性引用（禁 `ORDER BY id DESC` 猜测）；(3) Generation 无 is_billed 字段，billing truth 只属于 M07 committed ComputeTransaction
- **billing-report replay only**：full 9000→9100 request response-lost 登记为 DAILY_REPORT_REQUEST_RECOVERY_GAP（非 P1 职责，M07 IDEMPOTENCY_CONFLICT 兜底）
- **7 Gate PASS**：DR-1~DR-7（见 `P1_DAILY_REPORT_GENERATION_DESIGN.md`）
- **migration**：`0032_daily_report_generations.py`（revision 0032，backward-compatible nullable）

> **PENDING_PG_VERIFICATION（Stage 5C-4）**：functional migration COMPLETE，但 PostgreSQL schema application 仍未验证。
> 最终 P1 closure 前必须验证：`alembic upgrade 0030 → 0032` 在生产 PG 上成功 apply，`daily_report_generations` 表 + FK + `ck_daily_report_generations_status` CHECK 约束 + `daily_report_jobs.current_generation_id` 列真实存在且语义有效；并复跑 DR-7 并发语义（原子 claim + NEW Generation rows=1）确认在 PG 行级锁下成立。
> **SQLite / 单进程测试不替代 PG 证据**（P1 CLOSURE MANDATORY GATE 明确要求 PostgreSQL Concurrent Duplicate）。当前 5C-4 验收基于 SQLite + 单进程，PG 级证据留待 PG Closure Gate 闭环时补齐。

> **Reliability Gap 分离登记（防根因混淆）**：
> - Daily Report charge path consumer 迁移状态 = **IDEMPOTENCY_CONTRACT_MIGRATED_AND_VERIFIED**（P1 财务幂等职责已完成）。
> - **DAILY_REPORT_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1**：full 9000→9100 request response-lost（9100 已完成 LLM + M07 已 commit ComputeTransaction，但 9000 未收到 HTTP 响应 → 重跑 LLM 可能产生不同 usage）。M07 行为 = same Generation key + different payload → IDEMPOTENCY_CONFLICT（正确，不重复扣费，发出警报）。
> - 两者**严格分离**：consumer 迁移状态（财务幂等）≠ 请求级响应丢失可靠性差距。不得把 DAILY_REPORT_REQUEST_RECOVERY_GAP 并入 P1 consumer 迁移状态，也不得据此判定 COMPUTE-IDEMPOTENCY-001 仍 OPEN——该 Gap 属可靠性范畴（OUT_OF_P1），由独立可靠性工作流处理，P1 不虚假宣称已解决跨进程请求级幂等。

#### M05 Material Analysis（#8 — EXECUTION_IDENTITY_DESIGN_GAP / NOT MIGRATED）

- `ark_v1` 固定分析器版本；re-analysis 更新同一 AiEditMaterialAnalysis 行（id 不变）
- 无 per-execution identity（Analysis.id 是行 id 不是执行 id；AiEditMaterialProcess 表有 attempt_count 但用于处理状态不是计费身份）
- **设计方向**：不破坏共享行模型，新增 per-execution 层（不称"永续"）；可新建 AiEditMaterialAnalysis 行而非更新（version 递增），或引入 analysis_execution_id
- **重复扣费暴露**：`idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE）

#### Training（#9 — CANDIDATE_IDENTITY_VERIFIED / LIFECYCLE_ORDERING_CHANGE_REQUIRED / TECHNICAL_DESIGN_AUTHORIZED）

- 候选 key：`knowledge_training:{training_id}:ask`
- `training_id` 在 `_build_answer`（含 `_report_usage`）之后才生成+commit → 候选 identity 已验证但生命周期顺序需调整（前置 training_id 生成）
- **不升级 READY_TO_MIGRATE**：等 Stage 5D-1 钉死 retry cardinality
- **设计方向**：将 training_id 生成提前到 `_build_answer` 前
- **重复扣费暴露**：`idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE）

#### Preview（#7 — CHARGEABLE / POLICY_PENDING / EXECUTION_IDENTITY_DESIGN_GAP）

- 无 Run 持久化，`conversation_id="agent-preview"` 共用
- 当前计费且无 identity（CHARGEABLE）
- **产品决策待定**（POLICY_PENDING）：免费 → 不计费；收费 → 需 preview request record
- **POLICY_PENDING 不停止 identity 设计**：现在就应设计 Preview execution identity（不等产品策略）
- **设计方向**：先产品决策收费策略；若保持收费，则需 per-preview identity（preview request record）
- **重复扣费暴露**：`idempotency_key=None` → 无 M07 业务事件幂等保护（call#1→txn#1，call#2→txn#2，无 REPLAY，无 IDEMPOTENCY_CONFLICT）；证据 = CODE_VERIFIED_EXPOSED（非 E2E_VERIFIED_DOUBLE_CHARGE）
