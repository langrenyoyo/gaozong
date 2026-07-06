# Phase 3-B 小高算力后端能力迁移说明

> 阶段：Phase 3-B  
> 范围：仅迁移 `compute` 后端能力服务边界  
> 状态：保留 9000 旧接口兼容，新增 9205 `apps/compute` 独立能力服务。

## 1. 本轮完成内容

1. `apps/compute` 已具备独立 FastAPI app、业务 router、service、schema、dependencies。
2. 新能力路径挂载在 `/api/compute/*`：
   - `/api/compute/summary`
   - `/api/compute/transactions`
   - `/api/compute/packages`
   - `/api/compute/recharge-orders`
   - `/api/compute/admin/packages`
   - `/api/compute/admin/packages/{package_id}`
   - `/api/compute/admin/accounts/{merchant_id}/recharge`
   - `/api/compute/admin/accounts/{merchant_id}/grant-package`
   - `/api/compute/internal/usage`
3. 9000 旧接口继续保留：
   - `/compute/*`
   - `/admin/compute/*`
   - `/admin/merchants/{merchant_id}/compute/*`
   - `/internal/compute/usage`
4. 9000 兼容补充 `/admin/compute/accounts/{merchant_id}/recharge` 与 `/admin/compute/accounts/{merchant_id}/grant-package`，不删除旧 `/admin/merchants/{merchant_id}/compute/*`。
5. 新增 `packages/clients/compute_client.py`，供后续 gateway HTTP 转发使用。本轮不强制 9000 旧接口改为 HTTP 转发。

## 2. 过渡态说明

1. 本轮仍共享现有 SQLite 数据库。
2. 本轮仍共享 `app.models` 中的 `ComputeAccount`、`ComputeTransaction`、`ComputePackage`。
3. 本轮不新增 migration，不修改 `Compute*` 模型字段、表名、索引或默认值。
4. `apps/compute/schemas.py` 当前与 9000 旧 DTO 保持兼容，旧 `app.schemas` 不删除。
5. `app/services/compute_service.py` 保留为兼容 re-export，真实实现已收敛到 `apps.compute.services`。

## 3. 安全边界

1. `/compute/recharge-orders` 仍是 mock 订单，只返回 `mock_pending`，不真实支付、不真实入账。
2. `/api/compute/internal/usage` 与旧 `/internal/compute/usage` 保持一期扣费语义：记录消耗、余额可为负、不做余额不足拦截。
3. 9205 当前是 dev/internal-only 过渡服务。生产前必须补齐服务间鉴权，不能允许前端直连并伪造 gateway header。
4. 本轮未修改 webhook 验签、抖音私信发送、`manual_confirmed=true`、`auto_send=false`、19000 Local Agent、`input_writer` 或微信 UI 自动化路径。

## 4. 后续建议

1. Phase 3-B 后续小步将 9000 compute 旧 router 改为通过 `packages.clients.compute_client` 调用 9205。
2. 改为 HTTP 转发前，先补 gateway 注入 header 的签名或 internal token 鉴权。
3. 真实支付、支付回调、扣费拦截、拆库和模型迁移均不属于 Phase 3-B。
