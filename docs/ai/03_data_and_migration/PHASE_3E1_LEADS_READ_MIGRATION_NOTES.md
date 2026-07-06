# Phase 3-E1 AI小高线索只读后端能力迁移说明

## 1. 本轮目标

本轮只迁移 AI小高线索的低风险只读能力到独立 `apps/leads` 服务：

- `GET /api/leads`
- `GET /api/leads/{lead_id}`
- `GET /api/leads/reports/summary`

9202 leads 服务当前定位为 dev/internal-only 过渡服务，可以独立启动，并继续共享现有 SQLite、`app.database` 和 `app.models`。这不是最终拆库形态。

## 2. 当前实现边界

9202 复用 9000 既有只读逻辑：

- 列表、详情、分页、评分、时间线：`app.services.lead_management_service`
- 单条读取：`app.services.lead_service.get_lead`
- 报表统计：`app.services.report_service`
- DTO：`app.schemas.LeadOut`、`LeadListResponse`、`ReportSummary`

新服务不信任前端传入的 `merchant_id` / `tenant_id`。业务接口只读取 9000 gateway 注入的 `X-Gateway-*` 可信 header，并构造 `RequestContext` 后复用既有商户隔离逻辑。

## 3. 旧接口兼容

9000 旧接口继续保留，未改为 HTTP 转发：

- `GET /leads`
- `GET /leads/{lead_id}`
- `GET /reports/summary`

前端现有调用不需要变化。后续如果将 9000 gateway 切换为调用 9202，应通过 `packages/clients/leads_client.py` 完成，不要复制接口函数。

## 4. 本轮未迁移范围

以下能力明确未迁移：

- `/webhook/douyin`
- `/integrations/douyin/webhook`
- `/integrations/douyin/sync-leads`
- `POST /leads`
- `POST /leads/{lead_id}/assign`
- 线索创建、同步、自动分配、自动通知
- 微信任务、通知销售、回复检测联动
- 19000 Local Agent、`input_writer`、微信 UI 自动化

## 5. 安全边界

本轮未修改：

- DB model、表名、字段、索引、默认值
- migration
- webhook 验签
- `app/integrations/douyin_webhook.py`
- 抖音私信发送
- `manual_confirmed=true`
- `auto_send=false`
- 19000 Local Agent
- `input_writer`
- 真实支付或算力扣费语义
- NewCarProject 登录/权限门面

## 6. 生产前待补

9202 当前仍是共享 DB / 共享模型过渡态。生产前至少需要补齐：

- 服务间鉴权与 internal token 校验
- gateway 到 9202 的转发策略和故障降级
- 多商户线上数据隔离复核
- 只读接口流量、超时和日志策略
- 后续写路径迁移计划，尤其是 webhook、sync、分配和微信任务联动

## 7. 验证范围

本轮新增测试覆盖：

- 9202 `/`、`/health`、`/openapi.json`
- 9202 `/api/leads`
- 9202 `/api/leads/{lead_id}`
- 9202 `/api/leads/reports/summary`
- 商户隔离与越权详情 404
- 前端伪造 `merchant_id` 不覆盖可信上下文
- `packages.clients.leads_client` header、超时、HTTP 错误、网络错误、JSON 错误映射
- leads 能力服务不直接 import douyin-cs / wechat-assistant 业务 service
