# M02 AI小高线索

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-07

## M02 是什么

M02 是抖音私信线索的全生命周期管理模块，承担线索创建→去重归并→分配→跟进→反馈→状态变更的完整链路，以及与 M01（webhook 写入）和 M04（微信通知/销售反馈）的双向数据交互。

## 正式用户能力

| 能力 | 入口 | 状态 |
|---|---|---|
| 线索列表 | GET /leads | ACTIVE |
| 线索详情 | GET /leads/{id} | ACTIVE |
| 手工创建线索 | POST /leads | ACTIVE（但不做会话归并） |
| 分配/转派 | POST /leads/{id}/assign | ACTIVE |
| 自动分配 | webhook 内 auto_assign_next | ACTIVE |
| 微信通知销售 | POST /lead-notifications/send-to-staff | ACTIVE（手动） |
| webhook 自动通知 | webhook _dispatch_lead_after_create | CONFIG_DISABLED（auto_notify_disabled） |
| 销售反馈解析 | POST /sales-feedback/parse | ACTIVE |
| 旧拉取链路 | POST /sync-leads | COMPAT（仍可写库，聚合键不一致） |

## 数据 Owner

- **DouyinLead**：OWNER = webhook 主入口（`douyin_webhook.py:678` upsert_lead_from_webhook）；但 sync-leads 和手工 create 也写
- **CustomerProfile**：与 Lead 无 FK 关系、无自动合并（独立 P-0-C 客户档案表）
- **SalesStaff / LeadFollowupRecord / ReplyCheck / LeadNotification**：M02 附属表

## 主要入口

- webhook：`douyin_webhook.py:678` upsert_lead_from_webhook（会话归并，主入口）
- API：`app/routers/leads.py`（CRUD + assign）
- 旧链路：`app/routers/integrations.py:595` sync-leads（COMPAT）

## 主要依赖

- ← M01（data writes）：webhook upsert DouyinLead + recover_contact_valid
- → M04（data writes）：webhook 建 notify_sales WechatTask（当前 auto_notify_disabled）
- ← M04（data writes）：agent_write_back_reply 更新 ReplyCheck+DouyinLead
- → M03（runtime）：线索/客服读智能体配置
- → 公共底座：auth/数据库/商户隔离/联系方式提取

## 当前状态

ACTIVE。CRUD+分配+转派+反馈解析完整。**关键缺口**：聚合键双轨制（webhook 会话归并 vs sync source_id）、手工 create 绕过归并、同客户多会话=多条 Lead、无手机号归并、无 CustomerProfile 自动合并、自动通知已禁用、回收/每日上限/权重/优先级 NOT_IMPLEMENTED、状态自由字符串无约束、状态变更无显式审计。
