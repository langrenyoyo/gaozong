# M02 数据模型

> source_baseline: c26ec227e70d

## DouyinLead（OWNER: M02，3 个写入入口）

定义：`app/models.py:140`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| source | String(20) default "douyin" | |
| lead_type | String(32) | lead/comment/chat |
| customer_name | String(100) | |
| customer_contact | String(100) | 联系方式 |
| content | Text | 线索内容 |
| source_id | String(100) | 客户 open_id（不再作聚合主键） |
| merchant_id | String(128) index | 可信商户 ID |
| account_open_id | String(255) index | 企业号 open_id |
| conversation_short_id | String(255) index | 会话短 ID（聚合主键） |
| assigned_staff_id | FK sales_staff.id | |
| assigned_at | DateTime | |
| status | String(20) default "pending" | pending/assigned/replied/timeout/closed（**自由字符串无约束**） |
| raw_data | _JSONStringJSONB | |
| raw_message_text / extracted_phone / extracted_wechat / all_extracted_contacts | Text/JSONB | 联系方式 |
| contact_extract_status / contact_extract_reason | Text | |
| reassign_count | Integer default 0 | **存在但从未自增** |
| customer_id / external_customer_id | Text | 预留 |
| created_at / updated_at | DateTime | |

**唯一约束**：`(account_open_id, conversation_short_id)` — `models.py:145-148`（不含 merchant_id，靠 account_open_id 天然隔离）

### Lead Identity 三个概念（不混用）

| 概念 | 含义 | 证据 |
|---|---|---|
| Database identity | Lead 主键（id 自增） | models.py:151 |
| Webhook aggregation identity | (account_open_id, conversation_short_id) | douyin_webhook.py:604-608 find_lead_by_session |
| Legacy sync identity | source_id | douyin_sync_service.py:52 _find_existing_lead |
| Manual create | **当前无业务归并键** | lead_service.py:8 create_lead 无归并 |

> **结论**：Webhook 路径以账号+会话作为聚合身份，但 M02 整体尚无统一 Lead Identity Contract。

**无 phone/wechat 独立列**（存于 extracted_phone/extracted_wechat/customer_contact）。无 tenant_id（merchant_id 承担）。

## 写入入口（3 个，聚合键不一致）

| 入口 | 聚合键 | lifecycle |
|---|---|---|
| webhook upsert_lead_from_webhook | (account_open_id, conversation_short_id) | ACTIVE |
| sync-leads _execute_create | source_id | COMPAT（仍可写库） |
| 手工 lead_service.create_lead | 无归并 | ACTIVE（绕过会话归并，潜在风险） |

## 相关表

| 表 | 模型 | OWNER | 说明 |
|---|---|---|---|
| SalesStaff | models.py:94 | M02 | name/wechat_id/status/merchant_id + enable_lead_assignment 等 5 布尔规则 |
| LeadFollowupRecord | models.py:271 | M02 | lead_id/staff_id/record_type(assign/reassign/reply_check/notification/feedback/manual_note) |
| ReplyCheck | models.py:184 | M02 | lead_id/staff_id/reply_deadline/is_effective/check_status |
| LeadNotification | models.py:238 | M02 | lead_id/send_status/sent_at/error_message |
| SalesLeadFeedback | models.py:1181 | M02 | feedback_no/lead_id/staff_id/intention_level/parse_status；唯一(merchant_id, feedback_no) |
| SalesLeadUpdate | models.py:1214 | M02 | feedback_no/visit_status/deal_status/parse_status |
| SalesDailySummary | models.py:1236 | M02 | staff_id/summary_date |

## CustomerProfile（与 Lead 无 FK 关系、无自动合并）

定义：`models.py:1748`，唯一约束 `(merchant_id, account_open_id, customer_open_id)`
- webhook 流程不写 CustomerProfile，也不读它做归并
- 独立 P-0-C 客户档案表，与 DouyinLead 无 FK 关系

## 商户隔离

- DouyinLead：find_lead_by_session 强制 merchant_id 过滤（:607）；_detect_tenant_scope_conflict + IntegrityError 分支阻断跨商户
- 查询层：leads.py:55 super_admin 传 None 跳过过滤，否则 context.merchant_id
- 分配：assign_service.py:41-46 校验 staff.merchant_id == lead.merchant_id
- 销售数据范围：全部（商户内），非仅本人（assigned_staff_id 可选过滤，无强制"只看本人"）
