# M07 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| calculate_billed_tokens 计费 | COVERED | test_compute_service.py:57-91（6 case） |
| record_usage 扣费+快照 | COVERED | test_compute_service.py:365-571 |
| record_usage 单次顶层 commit | COVERED | test_compute_service.py:653 |
| 并发建账竞争恢复 | COVERED | test_compute_service.py:683,790 |
| BIGINT 边界 | COVERED | test_compute_service.py:739,757 |
| 余额/流水/套餐/充值/发放 | COVERED | test_compute_service.py:94-364 |
| 商户流水投影脱敏 | COVERED | test_compute_service.py:155-265 |
| **record_usage 幂等/重复上报去重** | **MISSING** | 全 tests/ 无重复调用去重测试 |
| 9100 compute_usage_client | COVERED | test_compute_usage_client.py:103-205 |
| 9000/9205 路由 | COVERED | test_compute_router.py / test_compute_app.py |
| 计量字段迁移 | COVERED | test_compute_usage_measurement_*.py |
| schema 契约（无幂等键） | COVERED | test_9000_postgres_compute_core_schema.py:112-113（断言无唯一键） |
| M04/M06→M07 联动上报 | MISSING | 无跨模块 record_usage 联动测试 |
| 支付 mock（实现矛盾） | PARTIAL | test_compute_service.py:612 断言"不改变余额"但实现实际改余额 |

## E2E 验真结果（2-M07.2 Docker，2026-08-08）

环境：docker compose dev（9000 + SQLite）

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| A Sequential Duplicate Usage | **PASS → COMPUTE-IDEMPOTENCY-001 E2E_VERIFIED** | 同一业务输入执行两次→balance delta=200=2×100（charge=100, basis_points=0, billed=100），2 条 consume 流水→**FINANCIAL_INTEGRITY E2E 证明** |
| B Concurrent Duplicate | STAGING_PENDING | SQLite 并发锁限制，需 PG 验证真实并发 |
| C Ledger Invariant | **PASS** | balance=9800 == initial(0) + sum_delta(9800)，每条 balance_after 一致 |
| D Fee/Ratio Calculation | **PASS** | tokens=100, basis_points=0, billed=100, mode=actual |
| E Negative Balance | **CODE_VERIFIED** | balance=-100000（负值允许不阻断，warning 写但不拒绝） |
| F Duplicate M04 Result → Compute | **PASS → M04_VERIFIED_IMPACTED** | 重复调 _report_wechat_task_compute_usage 两次→2 条 wechat-assistant 流水→**M04 是 impacted consumer（double charge E2E 证明）** |
| G Consumer Identity | **PASS** | transaction 含 capability_key/source/model/agent_id/conversation_id/merchant_id/remark |
| H Merchant Isolation | **PASS** | other-merchant txns=0 |

### 关键结论

| ISSUE | 变化 | 原因 |
|---|---|---|
| COMPUTE-IDEMPOTENCY-001 (ISSUE-M07-001) | CODE_VERIFIED → **E2E_VERIFIED FINANCIAL_INTEGRITY** | Gate A 证明 balance delta = 2 × charge |
| ISSUE-M04-002 | 保持 MEDIUM → **M04_VERIFIED_IMPACTED** | Gate F 证明 M04 重复调用 _report_wechat_task_compute_usage 产生 double charge |

### 仍 STAGING_PENDING

- Gate B Concurrent（需 PG 验证真实并发 + lost update/race）

**E2E 状态：`M07_DOCKER_E2E_VERIFIED_PENDING_BASELINE`**（无 BLOCKER，Gate A/C/D/E/F/G/H PASS + B STAGING_PENDING，COMPUTE-IDEMPOTENCY-001 E2E_VERIFIED FINANCIAL_INTEGRITY）

## E2E 验收清单（待 2-M07.2 补验证）

### DOCKER_TESTABLE
1. record_usage 基本扣费+余额
2. 充值（mock 订单→余额增加）
3. 六能力上浮比例配置
4. 商户隔离（跨商户不可见）
5. 重复 record_usage 调用→验证重复扣减（确认 CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP）

### NOT_APPLICABLE
6. Windows 19000 / 真实微信 / staging webhook — M07 不依赖
