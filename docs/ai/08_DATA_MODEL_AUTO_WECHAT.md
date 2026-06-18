# auto_wechat / 小高AI微信助手 第一版产品化数据模型设计

版本：P0-DATA-1
依据：`docs/ai/06_PRD_AUTO_WECHAT.md`、`docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
范围：数据模型设计与兼容 / 迁移边界说明。本文不修改业务代码、不修改 ORM 模型、不新增迁移脚本、不执行数据库迁移。

------

## 1. 当前数据模型现状探索

本节基于当前代码只读探索结果。

### 1.1 当前已有主要表

当前 `app/models.py` 已定义以下 ORM 表：

1. `sales_staff`：销售人员表，对应 `SalesStaff`。
2. `douyin_leads`：抖音线索表，对应 `DouyinLead`。
3. `reply_checks`：回复检测记录表，对应 `ReplyCheck`。
4. `check_configs`：检测配置表，对应 `CheckConfig`。
5. `feedback_records`：主机微信 B 向数据源微信 A 反馈记录，对应 `FeedbackRecord`。
6. `lead_notifications`：线索通知销售记录，对应 `LeadNotification`。
7. `wechat_tasks`：Local Agent 微信任务队列，对应 `WechatTask`。
8. `douyin_webhook_events`：抖音 GMP webhook 原始事件日志，对应 `DouyinWebhookEvent`。

当前 webhook 原始事件表真实表名是：

```text
douyin_webhook_events
```

PRD 目标域名是：

```text
lead_source_events
```

当前代码尚未定义物理表 `lead_source_events`。

### 1.2 当前模型与 PRD 目标差异

当前 `douyin_leads` 已存在，但字段仍是演示版线索模型：

```text
source
lead_type
customer_name
customer_contact
content
source_url
source_id
assigned_staff_id
assigned_at
status
raw_data
created_at
updated_at
```

与 PRD 目标差异：

1. 未发现 `customer_id`、`tenant_id`、`external_customer_id` 等多商户字段。
2. 未发现 `external_lead_id`、`dedupe_key`、`open_id`、`account_open_id`、`conversation_short_id`、`server_message_id` 等目标幂等字段。
3. 未发现 `raw_message_text`、`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`contact_extract_status`、`contact_extract_reason` 等联系方式提取字段。
4. 当前 `customer_contact` 是单字段，无法表达多个手机号 / 微信号和提取失败原因。
5. 当前 `status` 注释为 `pending/assigned/replied/timeout/closed`，未覆盖 PRD 状态全集。
6. 当前 `raw_data` 保存原始 JSON，但未区分 `raw_payload`、`cleaned_payload`、解析结果和提取结果。

当前 `douyin_webhook_events` 字段较少：

```text
event
from_user_id
to_user_id
event_key
is_duplicate
lead_id
raw_body
created_at
```

与 PRD 目标差异：

1. 未发现 `customer_id`、`tenant_id`。
2. 未发现 `external_event_id`、`external_lead_id`、`server_message_id`、`conversation_short_id`。
3. 未发现 `message_text`、`lead_action`、`process_status`、`processed_at`、`error_message`。
4. 未发现验签审计字段：`auth_required`、`auth_passed`、`auth_error`、`signature_header`、`timestamp_header`、`signature_checked_at`。
5. 当前重复事件不会新增重复记录，只返回已有 `event_id`，因此 `is_duplicate` 字段在现有实现中不承担完整重复命中审计能力。

### 1.3 当前相关表存在性

当前已存在：

1. `douyin_leads`
2. `sales_staff`
3. `reply_checks`
4. `wechat_tasks`
5. `lead_notifications`
6. `feedback_records`
7. `check_configs`
8. `douyin_webhook_events`

当前未发现：

1. `customers`
2. `douyin_accounts`
3. `lead_source_events`
4. `lead_assignments`
5. `agent_clients`
6. `agent_task_runs`
7. `lead_timeouts`
8. `manual_actions`
9. `callback_logs`
10. `export_tasks`

### 1.4 当前调用和数据写入现状

当前 webhook 入口：

1. `POST /integrations/douyin/webhook`
2. `POST /webhook/douyin`

两个入口均在 `app/routers/integrations.py` 中复用 `_handle_douyin_webhook()`。

当前处理链路：

```text
request.body()
  ↓
可选 verify_signature()
  ↓
json.loads()
  ↓
process_webhook_event()
  ↓
DouyinWebhookEvent / douyin_webhook_events
  ↓
DouyinLead / douyin_leads
```

当前 `app/integrations/douyin_webhook.py` 已有：

1. 原始 body 验签函数 `verify_signature()`。
2. `build_event_key()` 生成 webhook 幂等键。
3. `persist_webhook_event()` 写入 `douyin_webhook_events`。
4. `upsert_lead_from_webhook()` 直接基于 `from_user_id` 创建 / 更新 `douyin_leads`。

当前差异：现实现对 `im_receive_msg` 会直接创建 / 更新线索，尚未按 PRD 要求“先从私信纯文本提取手机号 / 微信号，再判断是否进入有效线索”。

### 1.5 当前数据库初始化 / 迁移现状

当前 `app/main.py` 在 `create_app()` 中调用：

```text
Base.metadata.create_all(bind=engine)
```

当前 `app/database.py` 使用 SQLite：

```text
data/auto_wechat.db
```

并设置：

1. `check_same_thread=False`
2. `timeout=30`
3. SQLite WAL 模式

只读探索中未发现 Alembic 目录、`alembic.ini`、迁移版本目录或 SQL 迁移脚本。当前数据库结构管理更接近 SQLAlchemy `create_all` 模式。

### 1.6 当前配置冲突

当前 `app/config.py` 与 `.env.example` 中：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

旧上下文第 28 节记录该默认值用于当前 GMP webhook 联调。

新 PRD / 架构已冻结为：

```text
生产环境 webhook 必须按 OpenApi 签名规则验签。
```

本数据模型文档只记录冲突和字段预留，不修改配置默认值。

------

## 2. 数据域总览

第一版产品化数据模型按以下业务域拆分：

1. customer / merchant 映射域
2. 抖音授权 / SECRET_KEY 配置域
3. webhook 原始事件域
4. 私信文本解析与联系方式提取域
5. 有效线索域
6. 销售管理域
7. 分配记录域
8. 微信任务域
9. Local Agent 心跳与任务执行域
10. 回复检测域
11. 超时 / 重分配域
12. 人工处理域
13. 回调 / 状态同步域
14. 导出记录域
15. 系统配置域

边界原则：

1. `customer_id` 是 auto_wechat 本地商户主键，后续所有业务表必须预留。
2. webhook 原始事件和有效线索必须可追溯。
3. 联系方式提取结果必须结构化保存，不能只写入单个文本字段。
4. 线索业务状态、微信任务状态、回复检测状态、回调日志状态必须分离。
5. 截图不保存、不入库。
6. 本轮只做设计，不做模型修改，不做迁移。

------

## 3. customer / merchant 映射设计

NewCarProject 对接规则：

1. auto_wechat 本地生成 `customer_id`。
2. NewCarProject 的商户 ID 保存为 `external_customer_id`。
3. 后续 NewCarProject 正式接入时，通过 `external_customer_id` 建立映射。
4. 当前 NewCarProject `token / cookie / roles / merchant_id` 字段结构仍待后续确认。
5. 第一版数据表必须为多商户预留 `customer_id`。
6. 可选预留 `tenant_id`，但不能强依赖 NewCarProject 当前未确认字段。

建议表：

```text
customers
```

建议字段：

```text
id
customer_id
external_customer_id
customer_name
status
secret_key
secret_key_scope
created_at
updated_at
```

字段说明：

1. `id`：本地自增主键。
2. `customer_id`：auto_wechat 本地生成的商户标识，业务表使用该字段关联。
3. `external_customer_id`：NewCarProject 商户 ID。
4. `customer_name`：商户名称。
5. `status`：商户状态，例如 `active / inactive`。
6. `secret_key`：第一版商户级 webhook 验签密钥。落库方式需要在技术方案阶段明确加密或密文保存策略。
7. `secret_key_scope`：第一版为 `merchant`，后续可扩展为 `douyin_account`。

约束建议：

```text
customers.customer_id 唯一
customers.external_customer_id 可空唯一
```

安全要求：

1. 不在事件表保存 `SECRET_KEY` 原文。
2. `secret_key` 的密文 / 明文保存方式必须在后续 Webhook 验签迁移技术方案中单独确认。

------

## 4. 抖音授权 / SECRET_KEY 配置域

第一版需要支持：

1. `SECRET_KEY` 按客户 / 商户维度配置。
2. 后续如果每个抖音账号需要不同 `SECRET_KEY`，再扩展到账号维度。
3. 商户完成抖音扫码鉴权后，才可以使用 AI小高线索获取对应抖音私信。
4. 需要保存授权状态。
5. 需要保存绑定抖音账号信息。

建议表：

```text
douyin_accounts
```

建议字段：

```text
id
customer_id
main_account_id
account_name
open_id
union_id
avatar_url
bind_status
bind_time
unbind_time
account_type
auth_status
auth_redirect_url
callback_url
created_at
updated_at
```

设计说明：

1. `customer_id` 关联本地商户。
2. `main_account_id` 对应抖音 / 巨量侧主账号标识。
3. `open_id`、`union_id` 保存绑定账号身份。
4. `bind_status` 表示绑定状态，例如 `bound / unbound`。
5. `auth_status` 表示授权状态，例如 `pending / authorized / expired / revoked`。
6. `callback_url` 保存当前配置的 webhook 地址，正式地址继续使用 `callback.misanduo.com/webhook/douyin`。

当前第一版如暂不实现完整授权表，也必须在后续数据模型落地时至少预留 `customer_id` 与账号维度扩展点，避免把全局 `DY_SECRET_KEY` 固化为长期结构。

------

## 5. webhook 原始事件域兼容策略

PRD 目标域：

```text
lead_source_events
```

当前旧实现真实表：

```text
douyin_webhook_events
```

可选策略：

### 5.1 策略 A：保留旧表名，语义升级

1. 继续使用 `douyin_webhook_events` 作为第一版真实表。
2. 文档中声明它承担 `lead_source_events` 的职责。
3. 后续再迁移为标准表名。
4. 优点：风险低，不破坏现有代码。
5. 缺点：表名与 PRD 目标域不一致。

### 5.2 策略 B：新增 `lead_source_events`，旧表只读保留

1. 新增标准表 `lead_source_events`。
2. 新 webhook 事件写入 `lead_source_events`。
3. 旧表数据保留，不直接删除。
4. 需要迁移计划。
5. 优点：符合 PRD。
6. 缺点：代码改动和迁移成本更高。

### 5.3 策略 C：数据库视图 / 兼容层

1. 保留旧表。
2. 新增模型或服务层适配 `lead_source_events` 语义。
3. 后续再物理迁移。
4. 优点：兼容性较好。
5. 缺点：实现复杂度中等。

### 5.4 推荐方案

第一版推荐采用策略 A + 轻量策略 C：

```text
第一版保留 douyin_webhook_events 物理表名，明确其语义等价于 lead_source_events；
在服务层和文档层使用 lead_source_events 作为业务域名称；
后续产品化稳定后，再单独做物理表名迁移。
```

推荐理由：

1. 当前代码已依赖 `DouyinWebhookEvent` / `douyin_webhook_events`。
2. 本轮禁止删除旧表，也禁止直接改名。
3. 当前项目未发现迁移系统，直接引入物理迁移风险高。
4. 原始事件域是 webhook 幂等和审计核心，第一版应优先保证兼容与可追溯。

后续如果做物理迁移，必须先完成：

1. 历史数据重复检查。
2. `event_key` 唯一性清洗。
3. 新旧表字段映射确认。
4. 迁移脚本和回滚脚本。
5. 双写或停机迁移策略。

------

## 6. lead_source_events / douyin_webhook_events 字段设计

第一版目标字段：

```text
id
customer_id
tenant_id
source_platform
event_key
external_event_id
external_lead_id
server_message_id
conversation_short_id
open_id
account_open_id
event_type
latest_event
latest_scene
message_type
raw_content
message_text
lead_action
is_duplicate
signature_valid
contact_extract_status
contact_extract_reason
raw_payload
received_at
processed_at
process_status
error_message
```

验签相关补充字段：

```text
auth_required
auth_passed
auth_error
signature_header
timestamp_header
signature_checked_at
```

字段说明：

1. `customer_id`：商户维度，后续所有查询和导出必须带商户边界。
2. `tenant_id`：可选预留，不强依赖 NewCarProject 未确认字段。
3. `source_platform`：第一版为 `douyin`。
4. `event_key`：webhook 事件幂等键。
5. `external_event_id`：外部事件 ID，如 payload 中有明确事件 ID 则保存。
6. `external_lead_id`：数据源线索 ID，优先使用数据源 `id`。
7. `server_message_id`：消息级幂等字段。
8. `conversation_short_id`：会话级辅助去重字段。
9. `open_id`：用户 open_id。
10. `account_open_id`：接收方 / 商户抖音账号 open_id。
11. `event_type`：例如 `im_receive_msg`。
12. `message_text`：从私信 content 中解析出的纯文本。
13. `lead_action`：例如 `created / updated / skipped / invalid / not_lead_event`。
14. `is_duplicate`：是否命中幂等。
15. `signature_valid`：验签是否通过。
16. `process_status`：事件处理状态，例如 `received / processed / failed`。
17. `raw_payload`：原始 payload JSON。

安全注意：

```text
不保存 SECRET_KEY 原文到事件表。
signature_header 是否保存全文由技术方案决定；默认建议只保存脱敏值或 hash。
```

当前兼容落地方式：

1. 物理表可先继续叫 `douyin_webhook_events`。
2. 字段扩展在后续代码方案 / 迁移方案中执行。
3. 文档和服务命名使用 `lead_source_events` 语义。

------

## 7. 私信文本解析与联系方式提取字段

第一版规则：

1. 用户留下资料时，联系方式通常出现在用户发出的私信纯文本中。
2. 第一版不依赖顶层 `phone` / `wechat` 字段。
3. 第一版不依赖 `retain_consult_card`。
4. 第一版不接入 LLM。
5. 第一版采用正则 / 规则提取。

提取规则：

```text
手机号：中国大陆 11 位手机号
微信号：识别 “微信 / wx / vx / v / 加我” 后面的账号
多个联系方式：全部保存，主字段取第一个
```

建议字段：

```text
raw_message_text
extracted_phone
extracted_wechat
all_extracted_contacts
contact_extract_status
contact_extract_reason
```

`contact_extract_status` 建议值：

```text
not_checked
matched
not_matched
parse_failed
```

保存规则：

1. `raw_message_text` 保存完整用户私信文本。
2. `extracted_phone` 保存第一个手机号。
3. `extracted_wechat` 保存第一个微信号。
4. `all_extracted_contacts` 保存全部提取结果，建议 JSON 数组。
5. `contact_extract_reason` 保存提取失败或跳过原因。
6. 无联系方式事件需要记录 `not_matched`，不进入销售分配。

------

## 8. 有效线索 douyin_leads 设计

有效线索进入：

```text
douyin_leads
```

建议字段：

```text
id
customer_id
tenant_id
external_lead_id
dedupe_key
open_id
account_open_id
conversation_short_id
server_message_id
douyin_display_name
avatar_url
phone
wechat
all_extracted_contacts
raw_message_text
contact_extract_status
contact_extract_reason
lead_channel
lead_type
latest_event
latest_scene
first_active_time
latest_active_time
source_lead_status
tags_json
last_interaction_record_json
assigned_staff_id
status
raw_payload
cleaned_payload
created_at
updated_at
closed_at
```

设计说明：

1. `phone` / `wechat` 来自私信文本提取。
2. `all_extracted_contacts` 保存全部提取结果。
3. 主字段取第一个联系方式。
4. `raw_message_text` 保存原始私信文本。
5. `external_lead_id` 优先使用数据源 `id`。
6. 如果 `id` 缺失，使用 `open_id + account_open_id` 作为兜底。
7. 同一 `open_id + account_open_id` 多次触发时更新原线索。
8. 同一用户不同会话，视为同一用户线索更新。
9. `assigned_staff_id` 只保存当前分配销售，完整分配历史进入 `lead_assignments`。
10. `raw_payload` 保存原始外部数据，`cleaned_payload` 保存清洗后的业务数据。

当前兼容建议：

1. 当前 `source_id` 可视为旧版 `open_id` / `dedupe_key` 兼容字段。
2. 当前 `customer_contact` 可作为旧展示字段保留，但不应作为第一版唯一联系方式来源。
3. 当前 `content` 可作为旧版消息文本展示字段保留，后续应补充 `raw_message_text`。

------

## 9. 幂等与唯一约束设计

必须设计以下幂等键：

1. `event_key`：webhook 事件幂等。
2. `server_message_id`：消息级幂等。
3. `conversation_short_id`：会话级辅助去重。
4. `external_lead_id`：外部线索 ID。
5. `dedupe_key`：内部线索去重键。
6. `customer_id + open_id + account_open_id`：同一商户同一用户线索更新。

建议唯一约束：

```text
lead_source_events.event_key
lead_source_events.customer_id + server_message_id
douyin_leads.customer_id + dedupe_key
douyin_leads.customer_id + open_id + account_open_id
```

当前兼容说明：

1. 当前 `douyin_webhook_events.event_key` 已设置唯一和索引。
2. 当前 `douyin_leads` 未发现唯一约束。
3. 当前 `find_lead_by_source_id()` 使用 `source= douyin + source_id` 查询，但数据库层未定义唯一约束。
4. 如果当前数据已存在重复 `source_id` 或重复 `event_key` 风险，后续迁移前需要先做数据清洗。

重复触发处理：

1. 重复事件不重复创建线索。
2. 重复事件返回 HTTP 200。
3. 重复事件需要记录幂等命中结果。
4. 同一用户多次发联系方式时更新原线索，并保存最新事件与最新提取结果。

------

## 10. 线索状态字段设计

`douyin_leads.status` 必须覆盖：

```text
received
invalid
delay_assign
pending_assign
assigned
notified
waiting_reply
replied
timeout
reassigned
manual_required
failed
closed
```

规则：

1. webhook 接收后可先进入 `received`。
2. 无联系方式进入 `invalid`。
3. 非工作时间有效线索进入 `delay_assign`。
4. `delay_assign` 对外映射为“未分配”。
5. 可分配线索进入 `pending_assign`。
6. 分配成功进入 `assigned`。
7. 微信通知后进入 `notified` 或 `waiting_reply`。
8. 回复检测命中进入 `replied`。
9. 超时未回复进入 `timeout`。
10. 超时重分配后进入 `reassigned` 或重新进入分配流程。
11. 失败且需要人工介入进入 `manual_required`。
12. 人工关闭进入 `closed`。
13. 第一版 `closed` 后不允许恢复。
14. `closed` 不对外回调。

当前兼容说明：

当前代码使用 `pending / assigned / replied / timeout / closed`。后续状态迁移需要在代码方案中明确旧状态映射：

```text
pending → pending_assign
assigned → assigned 或 waiting_reply
replied → replied
timeout → timeout
closed → closed
```

------

## 11. 销售管理 staff 设计

当前表为：

```text
sales_staff
```

目标可继续复用该表，补充多商户和排序字段。

建议字段：

```text
id
customer_id
wechat_nickname
staff_name
phone
remark
sort_order
status
created_at
updated_at
```

当前字段兼容：

1. 当前 `name` 可映射为 `staff_name`。
2. 当前 `wechat_nickname` 可复用。
3. 当前 `phone` 可复用。
4. 当前缺少 `customer_id`、`remark`、`sort_order`。

导入规则：

1. 微信昵称必填。
2. 销售姓名可空。
3. 手机号可空。
4. 备注可空。
5. 排序自动生成。
6. 重复微信昵称时覆盖。
7. 导入失败返回错误行号和原因。
8. 支持部分成功。
9. 提供模板下载。

建议唯一约束：

```text
customer_id + wechat_nickname
```

------

## 12. 分配记录设计

建议新增表：

```text
lead_assignments
```

建议字段：

```text
id
customer_id
lead_id
staff_id
assign_round
assign_reason
previous_staff_id
status
assigned_at
created_at
updated_at
```

必须支持：

1. 自动分配。
2. 重新分配。
3. 超时重分配。
4. 排除原销售。
5. 最多重分配 5 次。
6. 销售列表为空时进入未分配。

当前兼容说明：

1. 当前 `assign_service.assign_lead()` 直接更新 `douyin_leads.assigned_staff_id` 和 `assigned_at`，并创建 `reply_checks`。
2. 当前没有独立分配历史表。
3. 后续落地时应保留 `douyin_leads.assigned_staff_id` 作为当前销售，同时用 `lead_assignments` 保存完整历史。

------

## 13. 微信任务设计

当前表：

```text
wechat_tasks
```

建议目标字段：

```text
id
customer_id
lead_id
assignment_id
staff_id
agent_client_id
task_type
task_status
payload_json
result_json
failure_stage
failure_reason
manual_required
pasted
sent
detect_count
created_at
pulled_at
started_at
finished_at
updated_at
```

任务类型：

```text
send_notice
detect_reply
```

任务状态：

```text
pending
pulled
running
success
failed
manual_required
cancelled
```

当前兼容说明：

1. 当前 `task_type` 使用 `notify_sales / detect_reply`。
2. 当前 `status` 使用 `pending / running / pasted / failed / blocked / cancelled`，`detect_reply` 还可能进入 `completed`。
3. 当前有 `raw_result`、`failure_stage`、`agent_hostname`、`agent_pid`。
4. 当前缺少 `customer_id`、`assignment_id`、`agent_client_id`、`payload_json`、`result_json`、`pulled_at`、`started_at`、`finished_at`。

第一版要求：

1. 发送任务和检测任务互斥。
2. 同一 `agent_client_id` 同一时间只允许一个任务。
3. Local Agent 失败必须回写。
4. 截图不保存，不入库。
5. 任务状态不等同于线索业务状态。

------

## 14. Local Agent 心跳与执行记录设计

建议新增表：

```text
agent_clients
agent_task_runs
```

`agent_clients` 字段：

```text
id
customer_id
agent_client_id
agent_name
host_name
wechat_status
agent_status
last_heartbeat_at
created_at
updated_at
```

`agent_task_runs` 字段：

```text
id
customer_id
agent_client_id
task_id
task_type
status
started_at
finished_at
result_json
error_message
created_at
```

设计说明：

1. 第一版每个客户只考虑一台 Local Agent。
2. 不支持多 Local Agent。
3. 不支持多个账号。
4. 后续可通过 `agent_client_id` 扩展。
5. `agent_clients` 表示当前 Agent 在线状态和微信可用状态。
6. `agent_task_runs` 表示每次执行尝试，便于失败追踪。

当前兼容说明：

1. 当前 `app/local_agent_main.py` 有 `/health`、`/agent/version`、`poll-and-execute`、`poll-and-detect` 等本地接口。
2. 当前主库未发现 `agent_clients` 或 `agent_task_runs`。
3. 当前任务执行机器信息主要写入 `wechat_tasks.agent_hostname` 和 `agent_pid`。

------

## 15. 回复检测设计

当前表：

```text
reply_checks
```

建议目标字段：

```text
id
customer_id
lead_id
staff_id
task_id
check_status
matched_keyword
message_text
message_time
confidence
raw_messages_json
checked_at
created_at
updated_at
```

第一版规则：

1. 第一版不接入 LLM。
2. 采用关键词 / 规则检测。
3. 命中有效关键词进入 `replied`。
4. 未命中继续等待或超时。
5. 有效回复关键词由客户配置。

当前兼容说明：

1. 当前 `reply_checks` 已有 `lead_id`、`staff_id`、`reply_deadline`、`actual_reply_at`、`reply_content`、`is_effective`、`effectiveness_reason`、`check_status`、`checked_at`、`created_at`。
2. 当前缺少 `customer_id`、`task_id`、`matched_keyword`、`message_time`、`confidence`、`raw_messages_json`、`updated_at`。
3. 当前 `check_configs.effective_keywords` 保存全局关键词配置，后续需升级为客户维度配置。

------

## 16. 超时与重分配设计

建议新增表：

```text
lead_timeouts
```

建议字段：

```text
id
customer_id
lead_id
staff_id
assignment_id
timeout_at
timeout_minutes
reassign_count
status
created_at
updated_at
```

规则：

1. 默认超时时间 30 分钟。
2. 客户可配置。
3. 最多重分配 5 次。
4. 重分配排除原销售。
5. 超过次数进入人工处理或失败记录。

当前兼容说明：

1. 当前超时逻辑主要在 `reply_checker.run_checks()` 中扫描 `reply_checks.check_status=pending`。
2. 当前超时后直接更新 `reply_checks.check_status=timeout` 和 `douyin_leads.status=timeout`。
3. 当前没有独立超时记录表，也没有重分配次数记录。

------

## 17. 人工处理设计

建议新增表：

```text
manual_actions
```

建议字段：

```text
id
customer_id
lead_id
action_type
operator_id
operator_name
before_status
after_status
remark
created_at
```

动作类型：

```text
manual_reassign
manual_reply
manual_close
```

规则：

1. 人工重新分配后进入未分配或分配流程。
2. 人工补录销售回复后可进入已回复。
3. 人工关闭后进入 `closed`。
4. `closed` 第一版不允许恢复。

当前兼容说明：

1. 当前有 `POST /replies/manual` 和 `reply_checker.record_manual_reply()`，但没有独立人工处理审计表。
2. 当前人工关闭能力未形成独立数据域。
3. 后续人工操作必须保留操作人、前后状态和备注。

------

## 18. 回调 / 状态同步设计

建议新增表：

```text
callback_logs
```

建议字段：

```text
id
customer_id
lead_id
external_status
internal_status
callback_url
request_payload
response_payload
http_status
status
error_message
created_at
updated_at
```

对外状态只有：

```text
未分配
已分配
已回复
超时未回复
```

不对外回调状态：

```text
received
invalid
agent_pulled
notified
send_failed
manual_required
failed
closed
callback_success
```

说明：

1. `callback_success` 只作为内部 `callback_logs.status = success`，不作为业务状态。
2. `callback_logs.status` 建议值为 `pending / success / failed / skipped`。
3. 回调失败记录参与第一版导出。

当前兼容说明：

1. 当前存在 `feedback_records`，用于主机微信 B 向数据源微信 A 反馈检测结果，不等同于对外状态同步回调日志。
2. 当前未发现 `callback_logs`。

------

## 19. 导出记录设计

建议新增表：

```text
export_tasks
```

建议字段：

```text
id
customer_id
export_type
filter_json
file_path
status
created_by
created_at
finished_at
error_message
```

规则：

1. 第一版导出 Excel。
2. 支持按时间范围导出。
3. 导出线索列表。
4. 导出分配记录。
5. 导出微信通知任务。
6. 导出回复检测结果。
7. 导出超时记录。
8. 导出回调失败记录。
9. 导出人工处理记录。
10. 第一版导出不脱敏。
11. 导出不改变业务状态。

当前兼容说明：

当前未发现独立导出任务表。后续接口契约阶段需要确认导出是同步返回文件，还是异步任务生成文件。

------

## 20. 数据保存周期

业务数据保存：

```text
180 天
```

包括：

1. 原始事件。
2. 有效线索。
3. 分配记录。
4. 微信任务。
5. 回复检测。
6. 超时记录。
7. 回调失败记录。
8. 人工处理记录。

截图规则：

1. 截图不保存。
2. 截图不入库。

数据归档：

1. 第一版不做数据归档。
2. 客户如需历史数据，自行导出。

设计说明：

1. 当前演示阶段代码中存在调试截图能力，产品化数据模型不得将截图纳入业务表。
2. 180 天清理任务的触发方式、清理范围和审计策略放入后续代码方案，不在本轮执行。

------

## 21. 索引建议

至少需要以下字段索引：

```text
customer_id
external_customer_id
external_lead_id
dedupe_key
open_id
account_open_id
event_key
server_message_id
conversation_short_id
status
created_at
updated_at
assigned_staff_id
agent_client_id
task_status
task_type
```

建议组合索引：

```text
customers.external_customer_id
douyin_accounts.customer_id + open_id
lead_source_events.customer_id + event_key
lead_source_events.customer_id + server_message_id
lead_source_events.customer_id + received_at
douyin_leads.customer_id + status + created_at
douyin_leads.customer_id + assigned_staff_id + status
douyin_leads.customer_id + open_id + account_open_id
sales_staff.customer_id + wechat_nickname
lead_assignments.customer_id + lead_id + assign_round
wechat_tasks.customer_id + task_status + task_type + created_at
wechat_tasks.customer_id + agent_client_id + task_status
reply_checks.customer_id + check_status + checked_at
lead_timeouts.customer_id + status + timeout_at
callback_logs.customer_id + status + created_at
export_tasks.customer_id + status + created_at
```

设计理由：

1. 查询接口需要分页。
2. 导出接口需要按时间范围。
3. webhook 接收需要幂等索引。
4. 任务轮询需要任务状态索引。
5. 回复检测和超时扫描需要状态 + 时间索引。
6. 多商户场景下所有核心查询必须带 `customer_id`。

------

## 22. 与当前代码兼容策略

### 22.1 当前已有表与目标表关系

| 当前表 | 目标域 | 建议 |
|---|---|---|
| `douyin_webhook_events` | `lead_source_events` | 保留物理表名，语义升级，后续再物理迁移 |
| `douyin_leads` | 有效线索域 | 复用并补字段 |
| `sales_staff` | 销售管理域 | 复用并补 `customer_id / sort_order / remark` |
| `reply_checks` | 回复检测域 | 复用并补客户、任务、命中明细字段 |
| `wechat_tasks` | 微信任务域 | 复用并补 Agent、状态、时间字段 |
| `lead_notifications` | 微信通知记录域 | 可作为通知历史保留，后续与 `wechat_tasks` 关系需收敛 |
| `feedback_records` | 旧反馈记录域 | 保留旧链路记录，不等同于 `callback_logs` |
| `check_configs` | 系统配置域 | 可复用，但需升级为客户维度配置 |

### 22.2 可以复用的表

1. `douyin_webhook_events`
2. `douyin_leads`
3. `sales_staff`
4. `reply_checks`
5. `wechat_tasks`
6. `lead_notifications`
7. `check_configs`
8. `feedback_records`

### 22.3 需要新增的表

1. `customers`
2. `douyin_accounts`
3. `lead_assignments`
4. `agent_clients`
5. `agent_task_runs`
6. `lead_timeouts`
7. `manual_actions`
8. `callback_logs`
9. `export_tasks`

### 22.4 需要补充的关键字段

跨域通用：

```text
customer_id
tenant_id
created_at
updated_at
```

原始事件域：

```text
server_message_id
conversation_short_id
message_text
auth_required
auth_passed
signature_checked_at
process_status
```

线索域：

```text
external_lead_id
dedupe_key
open_id
account_open_id
raw_message_text
phone
wechat
all_extracted_contacts
contact_extract_status
contact_extract_reason
```

任务域：

```text
agent_client_id
assignment_id
task_status
payload_json
result_json
pulled_at
started_at
finished_at
```

### 22.5 `douyin_webhook_events` 与 `lead_source_events` 推荐处理方式

推荐：

```text
第一版不直接把 douyin_webhook_events 改名为 lead_source_events；
先保留旧表名，明确它承担 lead_source_events 职责；
在服务层逐步按 lead_source_events 语义补充字段；
产品化稳定后单独出迁移方案做物理表名迁移。
```

### 22.6 是否需要迁移脚本

后续真正补字段、新增表、增加唯一约束时需要迁移脚本。

当前项目未发现 Alembic 迁移系统，后续代码方案必须先明确：

1. 是否引入迁移系统。
2. 如何从 `create_all` 过渡到可控迁移。
3. 历史 SQLite 数据如何升级。
4. 迁移失败如何回滚。

本轮不新增 Alembic，不新增迁移脚本。

### 22.7 是否需要数据清洗

后续迁移前需要数据清洗检查：

1. `douyin_webhook_events.event_key` 是否有重复或空值。
2. `douyin_leads.source_id` 是否有重复。
3. `douyin_leads.status` 是否存在目标状态集外的历史值。
4. `wechat_tasks.status` 是否存在历史演示状态。
5. `sales_staff.wechat_nickname` 是否为空或重复。

### 22.8 后续代码方案边界

以下属于后续代码方案，不在本轮执行：

1. 新增 ORM 模型。
2. 修改 `app/models.py`。
3. 修改 `app/schemas.py`。
4. 新增迁移脚本。
5. 修改 webhook 验签默认值。
6. 实现联系方式提取。
7. 改造状态流转。
8. 新增导入 / 导出接口。
9. 新增回调接口。
10. 新增 Agent 心跳接口。

本轮只做设计，不做模型修改，不做迁移。

------

## 23. 后续依赖文档

P0-DATA-1 完成后，后续文档顺序：

1. 接口契约文档
2. Webhook 验签迁移技术方案
3. 代码修改计划
4. 测试验收计划
5. VibeCoding 分阶段执行计划

后续文档必须遵守本文约束：

1. 不把 `douyinAPI` 作为正式生产依赖。
2. 不把 AI小高线索、小高AI微信助手、AI小高剪辑混成一个服务。
3. 不把 LLM 写入第一版。
4. 不保存截图、不入库截图。
5. 不直接删除旧表。
6. 不直接把 `douyin_webhook_events` 改名为 `lead_source_events`。
7. 不在生产环境默认关闭 webhook 验签。

------

## 24. 本轮只读探索记录

已阅读：

1. `docs/ai/01_READING_RULES.md`
2. `docs/ai/05_PROJECT_CONTEXT.md`
3. `docs/ai/06_PRD_AUTO_WECHAT.md`
4. `docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
5. `docs/ai/02_EXECUTION_RULES.md`
6. `docs/ai/03_TESTING_RULES.md`
7. `docs/ai/04_OUTPUT_RULES.md`
8. `CLAUDE.md`
9. `app/models.py`
10. `app/schemas.py`
11. `app/database.py`
12. `app/config.py`
13. `app/main.py`
14. `app/routers/`
15. `app/services/`
16. `app/integrations/`
17. `app/routers/integrations.py`
18. `app/integrations/douyin_webhook.py`
19. `app/services/assign_service.py`
20. `app/services/wechat_task_service.py`
21. `app/local_agent_main.py`
22. `.env.example`

探索结论：

1. `app/routers/` 存在。
2. `app/services/` 存在。
3. `app/integrations/` 存在。
4. 当前未发现 Alembic 或 SQL 迁移脚本。
5. 当前依赖 `Base.metadata.create_all(bind=engine)` 创建表。
6. 当前未修改任何业务代码、数据库模型、接口、测试代码、依赖或配置默认值。

------

## 25. P1-DY-ACCOUNT-AGENT 数据模型落地记录

更新时间：2026-06-18

### 25.1 阶段结论

`P1-DY-ACCOUNT-AGENT` 一期已完成“一个抖音企业号绑定一个默认智能体”的正式数据闭环。

正式链路为：

```text
douyin_authorized_accounts
  → douyin_account_agent_bindings
  → ai_agents
  → 9000 注入 agent_config
  → 9100 生成回复建议
```

### 25.2 正式绑定表

`douyin_account_agent_bindings` 是抖音企业号绑定 AI 智能体的正式绑定表。

一期行为：

1. 一个企业号同一时间只有一个 `active` 默认智能体。
2. 绑定关系由 9000 负责创建、更新、失效和删除标记。
3. 9100 不直接读取该表，也不把 mock `ACCOUNT_AGENT_BINDINGS` 作为正式绑定依据。

### 25.3 企业号归属字段

`douyin_authorized_accounts.merchant_id` 与 `douyin_authorized_accounts.tenant_id` 用于确认抖音企业号归属。

正式校验必须使用可信请求上下文中的商户信息，不信任前端传入的 `merchant_id`。

### 25.4 授权与删除状态

`douyin_authorized_accounts.bind_status` 当前语义：

| 值 | 语义 |
|----|------|
| `1` | 授权有效 |
| `0` | 本地取消授权 |
| `4` | 本地软删除 |

取消授权后，对应 binding 标记为 `invalid`，`invalid_reason=account_unauthorized`。

删除企业号后，对应 binding 标记为 `deleted`，`invalid_reason=account_deleted`。

### 25.5 Agent 状态约束

生成回复建议前，9000 必须确认：

1. 企业号属于当前商户。
2. 企业号授权仍有效。
3. `AiAgent` 属于当前商户。
4. `AiAgent` 状态为 active。
5. `douyin_account_agent_bindings` 存在 active 绑定关系。

Agent disabled 或 deleted 后不得继续生成回复建议。

------

## 26. P1-REQ-GAP-1 数据模型风险补充

更新时间：2026-06-18

本节基于 `docs/ai/P1_REQUIREMENT_GAP_ANALYSIS.md` 的一期需求差异探索结果补充，只记录设计风险，不代表已经批准数据库迁移。

### 26.1 已具备商户字段的模型

当前以下模型已经具备可信商户字段或预留租户字段：

1. `douyin_authorized_accounts.merchant_id` / `tenant_id`：用于确认抖音企业号归属。
2. `douyin_account_agent_bindings.merchant_id` / `tenant_id`：用于确认企业号与智能体绑定归属。
3. `ai_agents.merchant_id`：用于确认智能体归属。
4. `compute_accounts.merchant_id` / `tenant_id`：用于商户算力账户隔离。
5. `compute_transactions.merchant_id` / `tenant_id`：用于算力流水隔离。

### 26.2 P0 数据模型缺口

`douyin_leads` 当前缺少 `merchant_id` / `tenant_id`，导致线索列表、线索详情、分配、重分配、报表和微信任务链路无法在数据库层形成强多商户隔离。

`douyin_webhook_events` 当前也缺少明确商户归属字段，导致原始事件与有效线索之间的商户归属无法稳定追踪。

### 26.3 建议设计方向

后续 `P1-GAP-LEADS-TENANT-1` 必须先做设计，不要直接写 migration。建议设计项：

1. 为 `douyin_leads` 补充 `merchant_id`、`tenant_id` 字段和按商户查询的组合索引。
2. 为 `douyin_webhook_events` 补充 `merchant_id`，用于原始事件归属和排查。
3. webhook 入库时优先通过抖音企业号 `account_open_id` 匹配 `douyin_authorized_accounts.open_id`，再取得可信 `merchant_id`。
4. 历史数据回填必须区分可确定归属、开发演示归属和未知归属，不得默认把所有旧线索静默归给同一商户。
5. 迁移前必须提供 dry-run、备份、回滚和多商户隔离测试。

### 26.4 明确禁止

1. 不得直接信任前端传入的 `merchant_id` 作为线索归属。
2. 不得在未确认上游事件字段和 NewCarProject 商户映射前直接执行生产迁移。
3. 不得把 `douyin_webhook_events` 物理表名强行重命名为 `lead_source_events`，该命名差异继续按既有文档解释处理。
