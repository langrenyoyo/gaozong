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

## E2E 验收清单（待 2-M07.2）

### DOCKER_TESTABLE
1. record_usage 基本扣费+余额
2. 充值（mock 订单→余额增加）
3. 六能力上浮比例配置
4. 商户隔离（跨商户不可见）
5. 重复 record_usage 调用→验证重复扣减（确认 CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP）

### NOT_APPLICABLE
6. Windows 19000 / 真实微信 / staging webhook — M07 不依赖
