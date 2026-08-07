# M02 运行时依赖

> source_baseline: c26ec227e70d

## M01 → M02（data writes，直接 DB 操作）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M01→M02 writes | D | direct DB | webhook upsert DouyinLead + recover_contact_valid（douyin_webhook.py:678,1194） |
| M01→M02 reads | D | service call | 客服工作台读 customer_profiles（douyin_workbench_conversation_service.py:28） |

> **架构耦合**：M01 直接操作 M02 ORM/table（douyin_webhook.py 直接 `DouyinLead(...)` + `db.add`），不经正式 M02 service。这是 DATA_COUPLING。

## M02 → M04（data writes，task 投递）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M02→M04 writes | D | task | webhook 建 notify_sales WechatTask（douyin_webhook.py:929；当前 auto_notify_disabled）；手动 lead_notification_actions.py:120 |

## M04 → M02（data writes，回写）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M04→M02 writes | D | direct DB | agent_write_back_reply / record_manual_reply 更新 ReplyCheck + DouyinLead（wechat_ui_reply_service.py:332; reply_checker.py:15） |

## M02 → M03（runtime，读智能体配置）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M02→M03 | R | service call | 线索/客服读智能体配置（webhook 解析绑定智能体） |

## M02 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth/RBAC | auto_wechat:leads 权限（leads.py） |
| 数据库 | DouyinLead + 6 附属表 ORM |
| 商户隔离 | find_lead_by_session + assign_service + require_lead_ownership |
| 联系方式提取 | contact_extractor + contact_state_service（领域共享） |

## M02 → 外部系统

| 外部系统 | 集成方式 |
|---|---|
| 抖音 GMP | webhook 直收（M01 入口，写 M02 Lead） |

## Legacy / Compat 交叉引用

| 项 | 与 M02 关系 | 状态 | 引用 |
|---|---|---|---|
| sync-leads | 仍可写库，聚合键 source_id 不一致 | COMPAT | LEGACY_REGISTER LEGACY-005 |
| auto_notify 旧链路 | 已禁用（LEGACY_AUTO_NOTIFY_DISABLED） | LEGACY/DISABLED | LEGACY_REGISTER LEGACY-005 |
| webhook 兼容路径 | 与正式入口共享 _handle_douyin_webhook | COMPAT | LEGACY_REGISTER LEGACY-006 |
