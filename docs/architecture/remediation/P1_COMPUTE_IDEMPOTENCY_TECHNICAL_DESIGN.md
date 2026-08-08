# P1 COMPUTE-IDEMPOTENCY-001 技术方案设计

> 状态：TECHNICAL_DESIGN_PENDING_APPROVAL（只设计不实施）
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

### 各消费者的业务身份候选

| Consumer | 调用点 | 业务事件 | 候选 identity | 不稳定/不安全候选 |
|---|---|---|---|---|
| M04 WechatTask | wechat_task_service.py:430,462 | 一个 WechatTask 到达 sent/pasted 终态 | `wechat_task:{task.id}` | ❌ conversation_id+model（同一会话两次真实消费会被误去重） |
| M06 LAS | ai_edit_las_service.py:186 | 一个 LAS job 归档成功 | `las_job:{job.id}` | ❌ merchant+script_hash（同脚本重跑是不同消费） |
| M01 LLM | reply_decision_service.py _report_llm_usage | 一次 LLM 调用成功 | `llm_call:{conversation_id}:{llm_call_count}` | ❌ conversation_id 单独（同一会话多次 LLM 是不同消费） |
| M02 Leads | douyin_webhook.py:1242 | 一条 im_receive_msg webhook 事件入库 | `webhook_event:{event.id}` | ❌ merchant+conversation（同会话多消息是不同消费） |
| M05 Material | material_analysis.py:251 | 一次素材分析完成 | `material_analysis:{material.id}:{analysis_version}` | ❌ material_id 单独（重新分析是不同消费） |

### 关键约束

> **兼容陷阱**：`idempotency_key = merchant + conversation_id + model` → 同一会话第 1 次和第 2 次真实 LLM 消费会被错误去重。
>
> **idempotency identity 必须对应具体业务事件，不是业务上下文。** conversation_id 是上下文不是事件；task.id / job.id / event.id / llm_call_count 才是事件级标识。

### 设计结论

每个 consumer 传入一个 **business_event_id**（字符串），代表"这一笔只允许扣一次"的业务事件唯一标识。M07 不派生，由 consumer 生成（consumer 最清楚自己的业务事件边界）。

---

## B. 幂等键由谁生成

### 方案：Consumer 生成 + M07 存储

| 层 | 职责 |
|---|---|
| Consumer | 生成 `idempotency_key`（基于自己的业务事件 ID） |
| M07 | 存储 `idempotency_key` 到 ComputeTransaction，DB 唯一约束兜底 |

### Consumer 生成规则

```
idempotency_key = f"{source}:{business_event_id}"
```

- `source` = consumer 标识（wechat_task / las_job / llm_call / webhook_event / material_analysis）
- `business_event_id` = consumer 侧的业务事件唯一 ID（task.id / job.id / event.id / conversation_id+call_count / material.id+version）
- **不用时间戳/随机 request_id**（每次 retry 变新 key = 无幂等）

### 为什么不由 M07 派生

M07 不知道 consumer 的业务事件边界（conversation_id 是上下文不是事件）。consumer 最清楚"什么是一次消费"。

---

## C. 幂等作用域

### 方案：merchant_id + idempotency_key

```
UniqueConstraint(merchant_id, idempotency_key)
```

- **不跨商户误判重复**：不同 merchant 相同 idempotency_key 各自独立（与 SHA-256 去重 scope 一致）
- **不跨 source 误判重复**：source 前缀确保不同 consumer 的 event_id 不冲突
- **不跨业务事件误判重复**：同一会话两次真实 LLM 消费有不同的 llm_call_count

### 不需要的字段

- 不需要 `source` 参与唯一约束（已在 idempotency_key 前缀中）
- 不需要 `capability_key` 参与唯一约束（同一事件不会跨 capability）

---

## D. DB 原子性

### 方案：DB 约束兜底 + 单事务原子单元

```
record_usage(db, merchant_id, tokens, *, idempotency_key, ...):
  1. INSERT INTO compute_transactions (..., idempotency_key=...)
     ON CONFLICT (merchant_id, idempotency_key) DO NOTHING RETURNING id
  2. 若 RETURNING 有行 → 写流水成功 → 继续扣余额（同一事务）
     若 RETURNING 无行 → 已存在 → 幂等返回
  3. UPDATE compute_accounts SET balance_tokens = balance_tokens - billed_tokens
     WHERE merchant_id = ? (with_for_update)
  4. COMMIT
```

### 关键约束

- **transaction insert + balance update 必须作为一个账务原子单元**（同一 DB 事务）
- **由数据库约束兜底**（非 Python 先 SELECT 再 INSERT 的 race-prone 逻辑）
- ON CONFLICT 是 PostgreSQL 原生语法；SQLite 需 INSERT OR IGNORE + 查询验证（已有跨方言先例：webhook 幂等 claim_webhook_event）

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
- 返回值与首次成功调用一致（ComputeAccount 或 ComputeTransaction）

### 内部 HTTP 上报（M01 9100 → 9000）

- 重复 POST `/internal/compute/usage` → 200 + 原结果
- ComputeUsageClient 已"绝不抛异常"（compute_usage_client.py:216），幂等后更安全

---

## F. 失败边界

### 必须保证的账本不变量

1. **同一 idempotency_key 最多一笔 transaction**（DB UniqueConstraint 兜底）
2. **同一 idempotency_key 最多一次余额修改**（transaction + balance 在同一事务）
3. **balance_tokens == initial + sum(delta_tokens)**（ledger invariant，Gate C 已验证 sequential）

### 不可能场景

| 场景 | 是否可能 | 原因 |
|---|---|---|
| 重复 transaction 无余额修改 | ❌ 不可能 | 同一事务原子 |
| 余额修改无 transaction | ❌ 不可能 | 同一事务原子 |
| 重复 transaction + 重复余额修改 | ❌ 不可能（修复后） | ON CONFLICT DO NOTHING |

### 残留风险

- **commit 成功 + response 丢失 + consumer retry**：幂等返回，不重复扣 ✓
- **commit 失败 + consumer retry**：事务回滚，下次 INSERT 不冲突，正常扣一次 ✓
- **并发同 idempotency_key**：DB ON CONFLICT 保证只有一个 INSERT 成功，另一个 DO NOTHING ✓

---

## G. 老消费者兼容

### 兼容窗口 + 迁移计划

| 阶段 | 行为 | 风险 |
|---|---|---|
| 阶段 1：idempotency_key 可选 | `idempotency_key=None` 时走旧逻辑（无去重，裸扣） | 旧 consumer 不报错，但无幂等保护 |
| 阶段 2：逐个迁移 consumer | 每个 consumer 改为传入 idempotency_key | 迁移一个保护一个 |
| 阶段 3：idempotency_key 必填 | `idempotency_key=None` → raise ValueError | 所有 consumer 必须已迁移 |

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
| 3 Two legitimate usages | 不同 idempotency_key | 2 条 transaction，balance delta = 2 × charge |
| 4 Ledger invariant | balance == initial + sum(delta) | PASS |
| 5 M04 duplicate result → compute | 重复 _report_wechat_task_compute_usage | 1 条 transaction（ISSUE-M04-002 CLOSED） |
| 6 M06 exposed path | 重复 _report_las_compute_usage | 1 条 transaction |
| 7 Merchant isolation | A 不能读写 B | PASS |
| 8 Failed-retry | commit 失败 + retry | 1 条 transaction |
| 9 Old consumer (idempotency_key=None) | 阶段 1 兼容 | 旧逻辑不报错（无去重） |

### 防止误去重

> **关键验收**：同一 conversation_id 的两次真实 LLM 消费（不同 llm_call_count）必须产生两条 transaction。如果 idempotency_key 误用 conversation_id 而非 llm_call:{conversation_id}:{call_count}，第二次合法消费会被错误去重。

### Cross-module Regression

- M04：_report_wechat_task_compute_usage 重复调用 → 1 条（ISSUE-M04-002 CLOSED）
- M06：_report_las_compute_usage 重复调用 → 1 条（ISSUE-M06-003 CLOSED）
- M01：compute_usage_client HTTP retry → 1 条
- M02：webhook event 重复 → 1 条
- M05：material re-analysis → 不同 version 不同 transaction

---

## Migration Impact

### DB Migration

- `compute_transactions` 加 `idempotency_key` 列（String(255), nullable=True）
- 加 `UniqueConstraint(merchant_id, idempotency_key)`（nullable 时 NULL 不参与唯一约束，兼容阶段 1）
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

## Rollback Strategy

| 阶段 | 回滚方式 |
|---|---|
| DB migration | `idempotency_key` 列 nullable，可安全 DROP COLUMN |
| API 签名 | `idempotency_key=None` 默认值，移除参数不影响旧调用 |
| Consumer 迁移 | 每个 consumer 独立迁移，可单独回滚 |

---

## 不冻结的实现细节

以下留给实施审批：
- 具体字段名（`idempotency_key` vs `dedup_key` vs `business_event_id`）
- 具体 SQL 语法（ON CONFLICT vs INSERT OR IGNORE + 查询）
- idempotency_key 的具体格式（`source:event_id` vs `source:event_id:version`）
- 迁移文件编号
- 测试文件结构

---

## 总结

| 问题 | 回答 |
|---|---|
| A. 一次消费的业务身份 | consumer 侧具体业务事件 ID（task.id / job.id / event.id / conversation_id+call_count / material.id+version） |
| B. 幂等键由谁生成 | Consumer 生成 `idempotency_key = f"{source}:{business_event_id}"` |
| C. 幂等作用域 | `UniqueConstraint(merchant_id, idempotency_key)` |
| D. DB 原子性 | ON CONFLICT DO NOTHING RETURNING + balance UPDATE 同一事务 |
| E. 重复调用返回什么 | 200 + 原交易结果（不 409 不 duplicated=true） |
| F. 失败边界 | 同一事务原子；commit 失败回滚可重试；commit 成功 retry 幂等 |
| G. 老消费者兼容 | 阶段 1 可选 → 阶段 2 逐个迁移 → 阶段 3 必填 |
| H. 回归验收 | 9 个 Acceptance Gate + 防误去重关键验收 |
