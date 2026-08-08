# M07 AI小高算力

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-08

## M07 是什么

M07 是算力计量与计费模块，承担 record_usage（消费记账）→ 余额扣减 → 充值/发放 → 套餐/上浮比例配置的完整链路。它是纯 Provider/被消费模块，不反向耦合业务。

## 正式用户能力

| 能力 | 入口 | 状态 |
|---|---|---|
| 算力概览/流水/充值订单 | GET /compute/*（商户侧） | ACTIVE |
| 超管算力配置 | /admin/compute-config（套餐/上浮比例/充值/发放） | ACTIVE |
| 内部算力上报 | POST /internal/compute/usage（9100/19000 调） | ACTIVE（X-Internal-Token fail-closed） |
| 充值 | create_mock_recharge_order | ACTIVE（mock，立即到账改余额） |

## Data Owner

| 表 | OWNER | 说明 |
|---|---|---|
| ComputeAccount | M07 | 商户账户（一商户一行，UniqueConstraint merchant_id） |
| ComputeTransaction | M07 | 流水（consume/recharge/grant/admin_adjust），**无 UniqueConstraint 无幂等键** |
| ComputePackage | M07 | 套餐定义 |
| ComputeMarkupRatio | M07 | 六能力上浮比例（UniqueConstraint capability_key） |

## 主要依赖

- ← M01（runtime HTTP）：9100 compute_usage_client → 9000 /internal/compute/usage
- ← M06（data service call）：_report_las_compute_usage → record_usage
- ← M04（data service call）：_report_wechat_task_compute_usage → record_usage
- → 公共底座：auth（X-Internal-Token）/数据库

## 当前状态

ACTIVE。record_usage/余额扣减/充值/套餐/上浮比例链路完整。**CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP 确认成立**——无幂等键，异常重入重复扣。支付仍为 mock（但实现与 docstring 矛盾——mock 订单实际立即到账改余额）。
