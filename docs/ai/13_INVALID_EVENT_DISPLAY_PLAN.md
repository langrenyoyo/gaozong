# P0-DEV-D1 原始事件 / invalid 展示与数据兼容方案

## 1. 本轮结论

本轮只做探索和方案设计，不修改业务代码、不修改数据库模型、不新增接口、不执行迁移。

推荐第一版采用方案 A：

```text
/leads 继续只展示有效线索 douyin_leads。
invalid / 原始 webhook 事件在单独的“原始事件 / 无效事件”列表展示。
```

数据兼容判断选择：

```text
判断 B：暂不迁移，但查询时解析 raw_body。
```

原因：

1. 当前 `douyin_webhook_events` 已保存原始 payload，足以支撑第一版基础详情展示。
2. 当前表缺少 `lead_action`、`contact_extract_status`、`message_text`、`customer_contact`、`failure_reason` 等结构化字段，筛选能力需要从 `raw_body` 和处理规则推导。
3. 本轮禁止迁移和模型修改；第一版可先用只读查询 + JSON 解析实现，后续再按查询性能和筛选需求补字段。

## 2. 当前真实结构

### 2.1 `douyin_webhook_events` 模型字段

位置：`app/models.py`，模型：`DouyinWebhookEvent`，表名：`douyin_webhook_events`。

真实字段：

| 字段 | 类型/约束 | 说明 |
| --- | --- | --- |
| `id` | `Integer`, primary key, autoincrement | 事件记录 ID |
| `event` | `String(128)` | 事件类型，如 `im_receive_msg` / `im_send_msg` / `im_enter_direct_msg` |
| `from_user_id` | `String(255)` | 发送者 open_id |
| `to_user_id` | `String(255)` | 接收者 open_id |
| `event_key` | `String(128)`, unique, index | 幂等去重键 |
| `is_duplicate` | `Integer`, default `0`, not null | 是否重复事件，当前重复事件不插入新行，因此落库行通常为 `0` |
| `lead_id` | `Integer`, nullable | 关联的 `douyin_leads.id`，invalid / 非线索事件为空 |
| `raw_body` | `Text`, not null | 原始 payload JSON |
| `created_at` | `DateTime`, default `datetime.now` | 创建时间 |

### 2.2 当前写入调用链

真实调用链：

```text
POST /integrations/douyin/webhook 或 POST /webhook/douyin
-> app/routers/integrations.py
-> process_webhook_event(db, payload)
-> build_event_key(payload)
-> find_existing_event(db, event_key)
-> 根据 event/content/contact_result 决定 lead_action
-> 必要时 upsert_lead_from_webhook(...)
-> persist_webhook_event(db, payload, event_key, lead_id)
-> 返回 WebhookResponse
```

关键事实：

1. `persist_webhook_event()` 将 `payload` 直接 `json.dumps(..., ensure_ascii=False)` 写入 `raw_body`。
2. `persist_webhook_event()` 只接收 `payload`、`event_key`、`lead_id`，不会写入 `lead_action`。
3. `lead_action` 只存在于 `process_webhook_event()` 返回结果和日志中，不是 `douyin_webhook_events` 的字段。
4. `server_message_id`、`conversation_short_id`、`create_time` 来自 payload 的 `content`，也参与 `event_key` 计算，但没有独立字段。

## 3. P0-DEV-C1 后 invalid 当前如何落库

### 3.1 无联系方式 `im_receive_msg`

当前规则：

1. `event == "im_receive_msg"` 时解析 `content`。
2. 如果是文本消息，则调用 `extract_contacts_from_text(message_text)`。
3. 如果没有提取到手机号或微信号，则：
   - 返回 `lead_action="invalid_contact"`。
   - 不调用 `upsert_lead_from_webhook()`。
   - 不创建 `DouyinLead`。
   - `persist_webhook_event(..., lead_id=None)` 写入 `DouyinWebhookEvent`。

测试已覆盖：

```text
tests/test_douyin_webhook.py::test_process_webhook_invalid_contact_writes_event_without_lead
```

断言包括：

```text
result["lead_action"] == "invalid_contact"
result["lead_id"] is None
DouyinLead 不存在
DouyinWebhookEvent 存在
event.lead_id is None
```

### 3.2 其他 invalid 场景

测试中已覆盖并确认不会创建 `douyin_leads`：

1. `content` 非法 JSON：`lead_action="invalid_contact"`，事件落库，`lead_id=None`。
2. 非文本消息：`message_type != "text"`，`lead_action="invalid_contact"`，事件落库，`lead_id=None`。
3. 顶层 `phone` / `wechat` 有值但私信文本无联系方式：不生成线索。
4. `retain_consult_card` 有联系方式但私信文本无联系方式：不生成线索。
5. 空联系方式文本：不生成线索。

### 3.3 `non_lead_event`

`event != "im_receive_msg"` 默认 `lead_action="not_lead_event"`。

例如 `im_send_msg`：

1. 不创建 `DouyinLead`。
2. 写入 `DouyinWebhookEvent`。
3. `lead_id=None`。
4. 返回 `lead_action="not_lead_event"`。

### 3.4 `duplicated_event`

当前重复事件处理：

1. `find_existing_event(db, event_key)` 命中已有首条事件。
2. 直接返回已有 `event_id` 和 `lead_id`。
3. 返回 `is_duplicate=True`。
4. 不插入新的 `DouyinWebhookEvent` 行。
5. 已落库的首条事件 `is_duplicate` 仍为 `0`。

因此，当前数据库无法列出“每一次重复请求记录”。只能在接口响应当次知道 `is_duplicate=True`，或从已有唯一事件推断幂等命中。

### 3.5 当前可区分能力

| 类型 | 当前是否可区分 | 依据 | 缺口 |
| --- | --- | --- | --- |
| `valid_lead` | 可以 | `douyin_webhook_events.lead_id` 非空，并可关联 `douyin_leads` | 无 |
| `invalid_contact` | 部分可以 | `event="im_receive_msg"` 且 `lead_id is null`，再解析 `raw_body.content` 判断文本/联系方式 | 没有独立 `lead_action`、`failure_reason`、`contact_extract_status` 字段 |
| `non_lead_event` | 可以 | `event != "im_receive_msg"` 且 `lead_id is null` | 无结构化 `lead_action` 字段 |
| `invalid_content` | 部分可以 | `raw_body.content` 非法 JSON 或解析后为空 | 没有独立失败原因字段 |
| `duplicated_event` | 当前无法作为列表行展示 | 重复事件不插入新行 | 若要审计每次重复请求，需要改变落库策略或新增审计表/字段 |

## 4. 当前是否已有原始事件查询接口

当前没有发现原始事件查询接口。

已确认：

1. `app/routers/` 下没有 `webhook_events.py`。
2. `app/services/` 下没有 webhook event 查询 service。
3. `app/schemas.py` 仅有 `WebhookResponse`，没有 webhook event 列表/详情 schema。
4. `app/main.py` 没有注册 `/webhook-events` 类 router。

当前 `/leads` 查询：

```text
app/routers/leads.py
-> lead_service.list_leads(db, status=status)
-> db.query(DouyinLead)
```

即 `/leads` 只查 `douyin_leads`，不会包含 invalid 事件。

当前 `/reports/summary`：

```text
app/routers/reports.py
-> report_service.get_summary(db)
-> 基于 DouyinLead / ReplyCheck / SalesStaff 统计
```

没有发现导出接口。

## 5. invalid 是否进入 `douyin_leads`

当前代码符合已确认规则：

```text
invalid 不进入 douyin_leads。
invalid 只进入 douyin_webhook_events / lead_source_events 语义域。
invalid 不参与分配。
invalid 不创建微信通知任务。
invalid 不对外回调。
```

原因：

1. `invalid_contact` 场景不调用 `upsert_lead_from_webhook()`。
2. `lead_id=None` 写入 `douyin_webhook_events`。
3. 分配、通知、回复检测等链路均围绕 `DouyinLead` / `lead_id` 工作。

## 6. 前端展示策略

### 6.1 方案 A：线索列表只展示有效线索

```text
/leads 只查 douyin_leads。
invalid 在单独“原始事件 / 无效事件”列表展示。
```

优点：

1. 不污染有效线索列表。
2. 不破坏现有分配链路。
3. 符合 invalid 不进入 `douyin_leads` 的规则。
4. 可以清晰区分“业务线索”和“来源事件”两个语义域。

缺点：

1. 前端需要新增原始事件列表入口。

### 6.2 方案 B：线索列表混合展示有效线索和 invalid

```text
/leads 聚合 douyin_leads + douyin_webhook_events。
```

优点：

1. 前端入口少。

缺点：

1. 查询复杂。
2. 状态语义容易混乱。
3. 容易让 invalid 误参与分配。
4. 会模糊 `lead_id` 为空事件与真实线索之间的边界。

### 6.3 推荐

第一版推荐方案 A：

```text
有效线索列表与原始/无效事件列表分离。
```

## 7. 后端接口建议

本轮只设计，不实现。

建议新增只读接口：

```text
GET /webhook-events
GET /webhook-events/{event_id}
```

建议筛选参数：

| 参数 | 说明 | 第一版来源 |
| --- | --- | --- |
| `event` | 事件类型 | 表字段 `event` |
| `lead_action` | `valid_lead` / `invalid_contact` / `non_lead_event` 等推导值 | 从 `event`、`lead_id`、`raw_body` 解析推导 |
| `has_contact` | 是否解析到联系方式 | 从 `raw_body.content` 的文本重新执行 contact extractor |
| `is_duplicate` | 是否重复事件 | 表字段 `is_duplicate`，但当前重复事件不插新行，价值有限 |
| `start_time` | 起始创建时间 | 表字段 `created_at` |
| `end_time` | 结束创建时间 | 表字段 `created_at` |
| `keyword` | 关键词 | 第一版从解析后的 message_text 过滤 |
| `page` | 页码 | 查询参数 |
| `page_size` | 每页数量 | 查询参数 |

建议返回字段：

| 返回字段 | 第一版来源 | 是否建议未来补字段 |
| --- | --- | --- |
| `event_id` | 表字段 `id` | 否 |
| `event` | 表字段 `event` | 否 |
| `lead_action` | 推导：`lead_id` / `event` / `raw_body` | 是 |
| `lead_id` | 表字段 `lead_id` | 否 |
| `server_message_id` | `raw_body.content.server_message_id` | 是 |
| `conversation_short_id` | `raw_body.content.conversation_short_id` | 是 |
| `message_text` | `raw_body.content.text/content/title/message` | 是 |
| `contact_extract_status` | 查询时重新提取并推导 | 是 |
| `customer_contact` | 查询时重新提取 `phone or wechat`，有效线索可从 `douyin_leads.customer_contact` 补充 | 是 |
| `created_at` | 表字段 `created_at` | 否 |
| `is_duplicate` | 表字段 `is_duplicate` | 否，但当前不记录重复请求行 |
| `failure_reason` | 查询时根据解析结果推导 | 是 |

第一版推导建议：

```text
lead_id 非空 -> valid_lead
event != im_receive_msg -> non_lead_event
event == im_receive_msg 且 content 非法/空 -> invalid_content
event == im_receive_msg 且无联系方式 -> invalid_contact
```

注意：当前无法从表字段直接拿到处理当时的 contact extractor 原始结果；只能基于 `raw_body` 的原始 payload 重放解析逻辑。

## 8. 导出策略

本轮只设计，不实现。

建议：

1. 有效线索导出来自 `douyin_leads`。
2. invalid / 原始事件导出来自 `douyin_webhook_events`。
3. 第一版导出不脱敏。
4. 导出不改变业务状态。
5. 当前未发现导出接口，后续单独做 P0-DEV-H。
6. 导出字段应与列表字段保持一致，但详情导出可额外包含 `raw_body`。

## 9. 数据字段兼容判断

选择判断 B：

```text
现有字段不完全够，但可以短期从 raw_body 解析。
后续再补字段优化查询。
```

第一版无需立即迁移，原因：

1. 基础列表可以直接查询 `douyin_webhook_events`。
2. 详情页可以展示 `raw_body` 和解析后的消息字段。
3. `invalid_contact` 可以通过 `event="im_receive_msg"`、`lead_id is null`、解析文本无联系方式推导。
4. 迁移会扩大本轮范围，且当前用户已明确禁止执行迁移和修改模型。

建议未来补字段：

```text
lead_action
contact_extract_status
message_text
customer_contact
server_message_id
conversation_short_id
is_duplicate
failure_reason
```

补字段收益：

1. 避免列表查询时逐行 JSON 解析。
2. 支持数据库层筛选和排序。
3. 固化处理当时的判断结果，避免后续规则变化导致历史事件展示结果漂移。
4. 支持失败原因统计。

## 10. SQLite 迁移策略

本轮不执行迁移，仅保留方案。

如后续决定补字段，当前项目仍使用 SQLite，且未发现 Alembic，建议第一版采用手写 SQLite 迁移脚本。

迁移要求：

1. 迁移前备份数据库文件。
2. 使用 `PRAGMA table_info(douyin_webhook_events)` 检查字段是否已存在。
3. 幂等执行：已存在字段跳过。
4. 在事务中执行 `ALTER TABLE ... ADD COLUMN ...`。
5. 失败时回滚事务，并保留备份。
6. 不删除旧字段。
7. 不重写 `raw_body`。
8. 不破坏旧数据。
9. 迁移后可选执行一次只读校验：统计行数、抽样解析 `raw_body`、确认新增字段初始为空。

建议新增字段类型：

| 字段 | SQLite 类型建议 | 说明 |
| --- | --- | --- |
| `lead_action` | `VARCHAR(32)` | `created` / `updated` / `skipped` / `not_lead_event` / `invalid_contact` |
| `contact_extract_status` | `VARCHAR(32)` | `matched` / `not_matched` / `empty_text` / `parse_failed` |
| `message_text` | `TEXT` | 解析后的私信文本 |
| `customer_contact` | `VARCHAR(255)` | 第一联系方式 |
| `server_message_id` | `VARCHAR(128)` | 抖音消息 ID |
| `conversation_short_id` | `VARCHAR(128)` | 会话短 ID |
| `failure_reason` | `VARCHAR(255)` | invalid 原因 |

`is_duplicate` 已存在，不建议重复新增。

## 11. 下一轮最小实现建议

下一轮建议做 P0-DEV-D2，只实现只读查询能力：

1. 新增 `app/services/webhook_event_service.py`：
   - 查询 `DouyinWebhookEvent`。
   - 解析 `raw_body`。
   - 复用现有 `parse_content()`、`normalize_message_text()`、`extract_contacts_from_text()`。
   - 推导 `lead_action`、`contact_extract_status`、`failure_reason`。
2. 新增 schema：
   - `WebhookEventListItem`
   - `WebhookEventDetail`
   - `WebhookEventListResponse`
3. 新增 router：
   - `GET /webhook-events`
   - `GET /webhook-events/{event_id}`
4. 注册 router。
5. 新增单元/API 测试：
   - 有效线索事件展示。
   - invalid_contact 展示。
   - non_lead_event 展示。
   - 非法 content 展示。
   - 分页和基础筛选。
6. 不修改 `/leads`。
7. 不修改 `douyin_leads` 生成规则。
8. 不执行迁移。
9. 不做前端和导出实现。

## 12. 本轮未做事项

本轮没有：

1. 修改业务代码。
2. 修改数据库模型。
3. 新增接口实现。
4. 修改测试代码。
5. 修改依赖。
6. 启动服务。
7. 执行数据库迁移。
8. 修改 webhook 验签逻辑。
9. 修改 contact_extractor。
10. 修改有效线索生成规则。
11. 修改 Local Agent 或微信 UI 自动化。
