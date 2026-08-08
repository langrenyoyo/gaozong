# M07 运行时依赖

> source_baseline: c26ec227e70d

## M07 是纯 Provider/被消费模块

M07 无主动上游依赖（dependencies 为空）。它被以下模块消费：

### M01 → M07（runtime HTTP）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M01→M07 | R | HTTP | 9100 compute_usage_client.report_usage → 9000 /internal/compute/usage → record_usage（compute_usage_client.py:199; compute.py:467） |

### M06 → M07（data service call）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M06→M07 | D | service call | _report_las_compute_usage → record_usage（ai_edit_las_service.py:737-746）; capability_key=ai_edit |

### M04 → M07（data service call）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M04→M07 | D | service call | _report_wechat_task_compute_usage → record_usage（wechat_task_service.py:497-508）; capability_key=wechat-assistant |

### M05 → M07（data service call）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M05→M07 | D | service call | material_analysis.py:251-264 → record_usage; capability_key=ai_edit |

### M02 → M07（data service call）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M02→M07 | D | service call | douyin_webhook.py:1240-1253 → record_usage; capability_key=leads |

## M07 反向耦合

**无实质反向耦合**。apps/compute/ 无 import 任何业务模块（douyin/las/agent/wechat）。仅有受控字典常量（COMPUTE_CAPABILITY_KEYS 含业务标识符字符串）和中文场景标签映射。M07 不反向依赖 M01/M03/M04/M06 业务代码。

## CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP

```
结论: 确认成立

record_usage 无幂等键:
  - 签名无 idempotency_key/transaction_key/jti 参数 (apps/compute/services.py:537-553)
  - ComputeTransaction 表无 UniqueConstraint (models.py:927-993)
  - _write_transaction 无去重查询 (apps/compute/services.py:148-228)
  - 迁移 0005 无唯一约束
  - 测试显式断言无幂等唯一键 (test_9000_postgres_compute_core_schema.py:113)

一次 usage = 一次 record_usage 调用 = 查比例→算计费量→写一条 consume 流水→扣余额→顶层一次 commit
重复 report = 每次调用都写新流水+重复扣余额
transaction 唯一性 = 无（无 UniqueConstraint）
失败重试 = commit 成功后重试必重复扣；commit 失败回滚不落库但调用方重试成功时重复扣

Observed consumers:
  - M04 result path (wechat_task_service.py:430,462) — ISSUE-M04-002
  - M06 LAS archive path (ai_edit_las_service.py:186) — ISSUE-M06-003
  - M02 leads path (douyin_webhook.py:1240)
  - M05 material analysis (material_analysis.py:251)
  - M01 9100 HTTP (compute_usage_client.py:199 → compute.py:467)

所有调用方均无去重 gate（M06 有 archived 幂等 gate 但仅正常路径有效，异常重入绕过）
```

## 兼容入口（LEGACY-012）

| 项 | 状态 | 引用 |
|---|---|---|
| app/services/compute_service.py re-export | COMPAT（活跃，4 调用方仍用旧路径） | LEGACY_REGISTER LEGACY-012 |
| 调用方迁移 | 未迁移（douyin_webhook/wechat_task_service/material_analysis/ai_edit_las_service 仍 import 兼容入口） | 删除前置未满足 |
