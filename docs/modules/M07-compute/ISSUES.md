# M07 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## HIGH

### ISSUE-M07-001 CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP

- **位置**：apps/compute/services.py:537-622 record_usage；app/models.py:927-993 ComputeTransaction（无 UniqueConstraint）
- **Duplicate charge behavior**: CODE_VERIFIED（静态代码确认无幂等键/无去重）
- **E2E double charge**: PENDING M07.2（需实际验证 balance delta = 2 × charge）
- **不提前写 E2E_VERIFIED**
- **一次 usage**：一次 record_usage 调用 = 查比例→算计费量→写一条 consume 流水→扣余额→顶层一次 commit
- **重复 report**：每次调用都写新流水+重复扣余额
- **transaction 唯一性**：无（无 UniqueConstraint，仅普通索引+CheckConstraint）
- **失败重试**：commit 成功后重试必重复扣；commit 失败回滚不落库但调用方重试成功时重复扣
- **Observed consumers**：
  - M04 result path（wechat_task_service.py:430,462）— ISSUE-M04-002
  - M06 LAS archive path（ai_edit_las_service.py:186）— ISSUE-M06-003
  - M02 leads path（douyin_webhook.py:1240）
  - M05 material analysis（material_analysis.py:251）
  - M01 9100 HTTP（compute_usage_client.py:199 → compute.py:467）
- **所有调用方均无去重 gate**（M06 有 archived 幂等 gate 但仅正常路径有效，异常重入绕过）
- **测试缺失**：全 tests/ 无 record_usage 重复调用去重测试
- **建议**：加 idempotency_key 参数 + ComputeTransaction 唯一约束 + record_usage 去重查询

## DEFERRED_CAPABILITY

### ISSUE-M07-002 支付 mock

- **位置**：apps/compute/services.py:669-719 create_mock_recharge_order
- **Payment runtime state**: MOCK_ONLY（docstring 标注 mock，route 注释 "当前仍是 mock"，create_mock_recharge_order 生成 mock 订单）
- **实现与 docstring 矛盾**：docstring 说不改余额，实现实际改余额（写 recharge 流水+commit）
- **若生产正在使用 Mock → HIGH/BLOCKER；若未上线/deferred → DEFERRED_CAPABILITY**
- **当前定性**：DEFERRED_CAPABILITY（支付 mock 为一期设计，非生产支付缺陷；1A.1 "支付仍为 mock"）

## COMPAT / TECH_DEBT

### ISSUE-M07-003 LEGACY-012 兼容入口未迁移（COMPAT / MIGRATION_INCOMPLETE）

- **位置**：app/services/compute_service.py（re-export 壳）；4 调用方仍 import 兼容入口
- **事实**：douyin_webhook.py:1240 / wechat_task_service.py:497 / material_analysis.py:251 / ai_edit_las_service.py:735
- **状态**：COMPAT / MIGRATION_INCOMPLETE（引用 LEGACY_REGISTER LEGACY-012）
- **影响**：LEGACY-012 不可删除（删除前置未满足）
- **建议**：4 调用方改直接 import apps.compute.services

## CURRENT_BEHAVIOR + POLICY_PENDING

### ISSUE-M07-004 负余额行为

- **位置**：apps/compute/services.py:189-197
- **NEGATIVE_BALANCE_BEHAVIOR**: CODE_VERIFIED（余额为负时写 warning 不阻断扣减）
- **E2E**: pending M07.2（需实际验证 balance < required charge 时的行为）
- **PRODUCT_POLICY**: POLICY_PENDING（Prepaid 拒绝 vs Postpaid 允许？需产品确认）

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 1（CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP, CODE_VERIFIED + E2E pending） |
| DEFERRED_CAPABILITY | 1（支付 mock MOCK_ONLY，实现与 docstring 矛盾） |
| COMPAT / TECH_DEBT | 1（LEGACY-012 兼容入口 MIGRATION_INCOMPLETE） |
| CURRENT_BEHAVIOR + POLICY_PENDING | 1（负余额 CODE_VERIFIED + 产品策略待定） |
