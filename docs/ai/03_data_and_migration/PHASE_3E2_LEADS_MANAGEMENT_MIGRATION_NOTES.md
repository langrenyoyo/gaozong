# Phase 3-E2 AI小高线索管理能力迁移说明

更新时间：2026-06-22

## 1. 本轮目标

Phase 3-E2 在 Phase 3-E1 只读查询与统计能力基础上，继续把 AI小高线索的中风险管理能力收敛到 `apps/leads`：

1. 创建有效线索：`POST /api/leads`
2. 分配有效线索：`POST /api/leads/{lead_id}/assign`
3. 分配备注 / 跟进记录：沿用现有 `LeadFollowupRecord` 写入链路，由分配动作生成 `assign` / `reassign` 时间线记录。

9202 `apps/leads` 当前仍是共享 DB / 共享模型过渡态，复用 9000 既有 `DouyinLead`、`SalesStaff`、`ReplyCheck`、`LeadFollowupRecord` 模型与 service。生产前仍需补齐 gateway 到能力服务之间的服务间鉴权、调用超时、审计日志和部署隔离策略。

## 2. 接口兼容

新增能力服务路径：

```text
POST /api/leads
POST /api/leads/{lead_id}/assign
```

旧 9000 接口继续保留兼容：

```text
POST /leads
POST /leads/{lead_id}/assign
```

本轮不强制把 9000 旧接口改为 HTTP 转发到 9202。低风险过渡策略是：旧 router 保留，9202 复用同一套 service，后续 gateway 化时再切换调用路径。

## 3. 有效线索边界

AI小高线索商户端主对象仍是有效线索 `douyin_leads`。

本轮不把以下对象并入商户端 AI小高线索主列表、主导航或能力服务管理接口：

1. 原始 webhook 事件
2. `unbound_account`
3. invalid event
4. webhook 技术状态
5. 调试记录

`webhook_events` 继续作为内部审计 / 调试能力保留，不作为商户端页面入口。`unbound_account` 仍然不是有效线索，不能进入商户端 AI小高线索列表。

## 4. 商户隔离

创建线索时：

1. `merchant_id` 只来自可信 `RequestContext` 或 gateway 注入上下文。
2. 前端或调用方传入的 `merchant_id` / `tenant_id` 不得覆盖可信上下文。
3. 9202 和旧 9000 创建接口均按上述规则写入 `douyin_leads.merchant_id`。

分配线索时：

1. 先校验 lead 属于当前商户。
2. 跨商户 `lead_id` 返回 404，不泄露线索存在性。
3. legacy NULL `merchant_id` 策略保持原有保护行为，非 super_admin 不扩大可见范围。
4. 销售人员模型当前没有 `merchant_id` 字段，本轮保持既有销售校验约束，不新增 DB 字段、不放宽 active 校验。

## 5. 微信任务联动边界

本轮分配仍复用 `assign_service.assign_lead` 的既有行为：

1. 更新线索分配状态。
2. 创建 `ReplyCheck`。
3. 写入 `LeadFollowupRecord` 分配备注。

本轮未新增任何自动通知能力，未调用 19000，未调用 `input_writer`，未创建 `WechatTask`，未触发真实微信发送，也未修改通知销售链路。sync-leads 中已有的可选微信任务创建逻辑不属于本轮迁移范围。

## 6. 明确未迁移内容

本轮未迁移、未修改：

1. `/webhook/douyin`
2. `/integrations/douyin/webhook`
3. webhook 验签
4. 授权企业号绑定保护
5. `/integrations/douyin/sync-leads`
6. `douyin_sync_service.py`
7. 微信任务联动
8. 19000 Local Agent
9. `input_writer` / 微信 UI 自动化
10. 抖音私信发送
11. `manual_confirmed=true`
12. `auto_send=false`
13. DB model / migration

## 7. 测试覆盖

本轮补充 / 更新测试覆盖：

1. 9202 创建有效线索时使用 gateway merchant 上下文，忽略伪造 scope。
2. 9202 分配当前商户有效线索，并写入分配跟进记录。
3. 9202 阻止跨商户 lead 分配。
4. 旧 9000 `POST /leads` 保持兼容，并使用可信 RequestContext merchant。
5. `packages/clients/leads_client.py` 支持创建和分配 client 方法。

## 8. 后续事项

1. 生产前补齐服务间鉴权，避免 9202 被绕过 gateway 直接调用。
2. 如后续新增人工跟进记录独立接口，应继续保持有效线索边界和商户隔离，不接入 webhook 原始事件。
3. 如后续切换 9000 旧接口为 HTTP 转发，需要补充 gateway 转发测试和超时 / 降级策略。
