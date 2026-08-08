# M07 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## HIGH

### ISSUE-M07-001 CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP 确认成立

- **位置**：apps/compute/services.py:537-622 record_usage；app/models.py:927-993 ComputeTransaction（无 UniqueConstraint）
- **结论**：record_usage 无幂等键（参数无、表无、迁移无、_write_transaction 无去重查询）
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

## MEDIUM

### ISSUE-M07-002 支付 mock 实现与 docstring 矛盾

- **位置**：apps/compute/services.py:669-719 create_mock_recharge_order
- **事实**：docstring（:6-7）说"不实际到账、不改余额"，但实现（:697-705）实际写 recharge 流水+commit→余额立即增加
- **测试矛盾**：test_compute_service.py:612 断言"不改变余额"但实现改了
- **影响**：测试可能与实现不同步（或测试失败被忽略）
- **建议**：确认 docstring vs 实现哪个是期望行为，同步测试

## LOW

### ISSUE-M07-003 LEGACY-012 兼容入口 4 调用方未迁移

- **位置**：app/services/compute_service.py（re-export 壳）；4 调用方仍 import 兼容入口
- **事实**：douyin_webhook.py:1240 / wechat_task_service.py:497 / material_analysis.py:251 / ai_edit_las_service.py:735
- **影响**：LEGACY-012 不可删除（删除前置未满足）
- **建议**：4 调用方改直接 import apps.compute.services

### ISSUE-M07-004 负余额允许（warning 不阻断）

- **位置**：apps/compute/services.py:189-197
- **事实**：余额为负时写结构化 warning 但不阻断扣减
- **影响**：商户可透支（设计决策非 Bug，但需确认是否符合业务预期）
- **建议**：如需硬阻断加阈值检查

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 1（CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP 确认成立） |
| MEDIUM | 1（支付 mock 实现与 docstring 矛盾） |
| LOW | 2（兼容入口未迁移 / 负余额允许） |
