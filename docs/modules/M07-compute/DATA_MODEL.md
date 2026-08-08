# M07 数据模型

> source_baseline: c26ec227e70d

## M07 拥有的表

### ComputeAccount（OWNER: M07）
定义：`app/models.py:906-924`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| merchant_id | String(128), 唯一 | 一商户一行 |
| balance_tokens | BigInteger | 当前余额（可为负，warning 不阻断） |
| total_consumed_tokens | BigInteger | 累计消费 |
| total_recharged_tokens | BigInteger | 累计充值 |
| tenant_id | String(128) | 预留（无租户隔离逻辑） |
| created_at / updated_at | DateTime | |

### ComputeTransaction（OWNER: M07，无幂等键）
定义：`app/models.py:927-993`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| merchant_id | String(128) | 商户隔离 |
| delta_tokens | BigInteger | +/-（consume 负/recharge 正/grant 正/admin_adjust） |
| balance_after_tokens | BigInteger | 快照 |
| transaction_type | String(32) | consume/recharge/grant/admin_adjust |
| capability_key | String(64) | douyin-cs/leads/agents/wechat-assistant/ai_edit/compute |
| source | String(32) | llm/other |
| model | String(128) | |
| usage_measurement_method | String(32) | estimated_tokens/legacy_characters/actual_tokens |
| agent_id | String(255) | |
| conversation_id | String(255) | |
| remark | Text | |
| created_at | DateTime | |

**无 UniqueConstraint**——仅普通索引（merchant_id+created_at）+ CheckConstraint（delta_tokens != 0）。迁移 0005 也无唯一约束。测试显式断言无幂等唯一键（test_9000_postgres_compute_core_schema.py:113）。

### ComputePackage（OWNER: M07）
定义：`models.py:996-1012`。套餐定义（name/tokens/price/status），无约束。

### ComputeMarkupRatio（OWNER: M07）
定义：`models.py:1408-1429`。UniqueConstraint(capability_key)，六能力每能力一行。consumption_mode(actual/custom) + fixed_tokens_per_call。

## 迁移版本

| 版本 | 内容 |
|---|---|
| 0005 | compute_accounts + compute_transactions 核心表 |
| 0012 | compute_billing |
| 0014 | compute_usage_measurement |
| 0023 | compute_markup_ai_edit（加 ai_edit 行） |
| 0024 | compute_markup_consumption_mode（加 consumption_mode/fixed_tokens_per_call） |

## 商户隔离

- merchant_id 列（所有表）
- get_or_create_account 按 merchant_id 查/创建（apps/compute/services.py:118-122）
- 路由层 require_merchant_context 从 X-Gateway-Merchant-Id 提取
- 管理员 require_compute_config_admin 校验 auto_wechat:admin:compute_config 或 super_admin
- 内部上报 _require_internal 校验 X-Internal-Token（生产 fail-closed）
