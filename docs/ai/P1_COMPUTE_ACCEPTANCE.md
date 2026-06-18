# 小高算力一期验收报告

## 1. 验收结论摘要

1. 商户端 `/compute` 已接入真实后端接口。
2. 超管端算力配置页已接入真实后端接口。
3. 商户端支持余额、今日/昨日/累计消耗、Token 明细、套餐列表和 mock 充值订单。
4. 超管端支持套餐列表、新增、编辑、启用/禁用、给商户后台充值和发放套餐。
5. 当前真实支付未接入。
6. 商户端充值订单状态保持 `mock_pending`。
7. 后台充值/发放属于管理操作，不等于真实支付。
8. 本期保留“真实支付未接入”的安全边界，不做付款码、回调和轮询。

## 2. 提交记录

| commit | 任务 | 文件范围 | 说明 |
| ------ | -- | ---- | -- |
| `60ebeca` | 接入小高算力商户页面真实接口 | `frontend/src/pages/ComputeCenter.tsx`、`frontend/src/api/compute.ts`、`frontend/src/api/types.ts`、`frontend/src/components/SideNav.tsx`、`frontend/src/pages/Index.tsx` | 商户端算力页面接入真实接口，保留 mock 充值订单安全边界 |
| `88ea1e5` | 接入超管算力配置真实接口 | `frontend/src/pages/SuperComputeConfig.tsx`、`frontend/src/api/compute.ts`、`frontend/src/components/SideNav.tsx`、`frontend/src/pages/Index.tsx` | 超管端算力配置页接入真实接口，支持套餐管理与后台充值/发放 |

## 3. 商户端能力验收

| 需求点 | 当前状态 | 接口 | 页面 | 备注 |
| --- | ---- | -- | -- | -- |
| 算力余额 | 已实现 | `GET /compute/summary` | `/compute` | 显示当前 Token 余额 |
| 今日消耗 | 已实现 | `GET /compute/summary` | `/compute` | 来自后端汇总 |
| 昨日消耗 | 已实现 | `GET /compute/summary` | `/compute` | 来自后端汇总 |
| 累计消耗 | 已实现 | `GET /compute/summary` | `/compute` | 来自后端汇总 |
| Token 明细 | 已实现 | `GET /compute/transactions` | `/compute` | 支持分页展示 |
| 套餐列表 | 已实现 | `GET /compute/packages` | `/compute` | 仅展示启用套餐 |
| 套餐充值 | 已实现 | `POST /compute/recharge-orders` | `/compute` | 仅创建 mock 订单 |
| 自定义金额 | 已实现 | `POST /compute/recharge-orders` | `/compute` | 与套餐充值二选一 |
| mock 充值订单 | 已实现 | `POST /compute/recharge-orders` | `/compute` | 状态为 `mock_pending` |
| 真实支付未接入提示 | 已实现 | 无 | `/compute` | 页面明确提示不接真实支付 |

## 4. 超管端能力验收

| 需求点 | 当前状态 | 接口 | 页面 | 备注 |
| --- | ---- | -- | -- | -- |
| 套餐列表 | 已实现 | `GET /admin/compute/packages` | `/admin-compute` | 可查看全部套餐 |
| 新增套餐 | 已实现 | `POST /admin/compute/packages` | `/admin-compute` | 支持填写名称、价格、Token 数量 |
| 编辑套餐 | 已实现 | `PUT /admin/compute/packages/{id}` | `/admin-compute` | 按后端现有能力更新 |
| 启用/禁用套餐 | 已实现 | `PUT /admin/compute/packages/{id}` | `/admin-compute` | 通过 `enabled` 切换 |
| 给商户后台充值 Token | 已实现 | `POST /admin/merchants/{merchant_id}/compute/recharge` | `/admin-compute` | 以管理操作方式入账 |
| 给商户发放套餐 | 已实现 | `POST /admin/merchants/{merchant_id}/compute/grant-package` | `/admin-compute` | 以管理操作方式入账 |
| 操作结果展示 | 已实现 | 上述接口 | `/admin-compute` | 返回余额摘要 |
| 安全提示 | 已实现 | 无 | `/admin-compute` | 明确不是真实支付 |

## 5. 当前接口清单

### 商户端

* `GET /compute/summary`
* `GET /compute/transactions`
* `GET /compute/packages`
* `POST /compute/recharge-orders`

### 超管端

* `GET /admin/compute/packages`
* `POST /admin/compute/packages`
* `PUT /admin/compute/packages/{id}`
* `POST /admin/merchants/{merchant_id}/compute/recharge`
* `POST /admin/merchants/{merchant_id}/compute/grant-package`

## 6. 安全边界

1. 不接真实支付。
2. 不调用微信支付或支付宝。
3. 商户端充值订单状态为 `mock_pending`。
4. 商户端不假装充值立即到账。
5. 余额以后台入账或测试 `usage` / `recharge` 为准。
6. 超管后台充值/发放是管理操作，不代表真实支付。
7. 当前不做支付回调。
8. 当前不做二维码付款码。
9. 当前不做支付状态轮询。

## 7. 验证记录

* `python -m pytest tests/test_compute_models.py tests/test_compute_service.py tests/test_compute_router.py -q`：通过
* `cd frontend && npm run build`：通过
* 构建提示仅保留既有字体解析警告和 chunk 体积警告

## 8. 剩余缺口

1. 真实支付未接入。
2. 支付二维码 / 付款码未接入。
3. 支付回调未接入。
4. 超管端商户选择目前仍可先手动输入 `merchant_id`，后续可接商户列表。
5. 余额不足拦截如果未统一覆盖所有消耗点，后续仍需补齐。
6. 发票与支付流水不属于本期范围。

## 9. 下一步建议

* `P1-COMPUTE-MERCHANT-PICKER-1`：超管端商户选择器接真实商户列表。
* `P1-COMPUTE-USAGE-GUARD-1`：统一算力余额不足拦截。
* `P2-COMPUTE-PAYMENT-DESIGN-1`：真实支付方案设计。
* `P2-COMPUTE-REPORT-1`：算力消耗报表增强。
