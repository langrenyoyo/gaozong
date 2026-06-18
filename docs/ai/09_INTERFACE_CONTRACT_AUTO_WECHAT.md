# auto_wechat / 小高AI微信助手 第一版产品化接口契约

版本：P0-API-1
依据：`docs/ai/06_PRD_AUTO_WECHAT.md`、`docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`、`docs/ai/08_DATA_MODEL_AUTO_WECHAT.md`
范围：接口契约设计与当前接口兼容关系说明。本文不修改业务代码、不新增接口实现、不修改现有接口实现、不修改配置默认值。

------

## 1. 接口总览

第一版产品化接口按调用方分类。

| 调用方 | 接口类别 | 第一版要求 | 说明 |
|---|---|---|---|
| 外部平台 / 火山 / 抖音 → auto_wechat | webhook 入站 | 必须实现 | 正式验收链路为 `callback.misanduo.com/webhook/douyin` |
| AI小高线索 → 小高AI微信助手 | 有效线索交付 | 必须预留，建议第一版服务层模拟 | 两个子功能独立售卖、独立启动，后续通过 HTTP API 拆分 |
| 商户前端 / React → auto_wechat | 商户后台 API | 必须实现核心页面 | 覆盖首页、线索、销售、配置、任务、检测、人工处理、导出 |
| Local Agent → auto_wechat | 任务拉取、任务回写、心跳 | 必须实现任务链路，心跳可预留 | 当前已有 19000 本地 Agent 和 9000 任务回写接口 |
| NewCarProject → auto_wechat | 跳转 / 登录 / 权限预留 | 预留 | `token / cookie / roles / merchant_id` 结构待确认 |
| auto_wechat → 外部状态同步方 | 状态同步 / 回调 | 预留或按客户启用 | 对外状态只有四类 |
| 运维 / 健康检查 | 服务健康检查 | 必须预留 | 支持后续独立启动、独立部署、独立健康检查 |

当前代码已存在的主要接口：

1. `POST /webhook/douyin`
2. `POST /integrations/douyin/webhook`
3. `POST /integrations/douyin/sync-leads`
4. `GET /leads`、`GET /leads/{lead_id}`、`POST /leads`、`POST /leads/{lead_id}/assign`
5. `GET /staff`、`GET /staff/{staff_id}`、`POST /staff`、`PUT /staff/{staff_id}`
6. `GET /checks`、`POST /checks/run`
7. `GET /reports/summary`
8. `POST /wechat-tasks`、`GET /wechat-tasks/pending`、`GET /wechat-tasks/{task_id}`、`POST /wechat-tasks/{task_id}/result`
9. `POST /replies/manual`、`POST /replies/agent-write-back`
10. 19000 Local Agent：`GET /health`、`GET /agent/version`、`POST /agent/tasks/poll-and-execute`、`POST /agent/tasks/poll-and-detect`

当前未发现但第一版目标需要设计或预留：

1. `GET /dashboard/summary`
2. `GET /agent/status`
3. `POST /agent/heartbeat`
4. `GET /health`、`GET /health/webhook`、`GET /health/agent` 作为 9000 主服务健康检查
5. `POST /auth/newcar/verify`、`GET /auth/newcar/entry`
6. `POST /auth/change-password`
7. `POST /exports` 等导出任务接口
8. `POST /callbacks/status` 或外部状态回调配置接口

------

## 2. 通用接口规范

### 2.1 普通业务 API 响应

普通业务 API 建议统一成功响应：

```json
{
  "success": true,
  "data": {},
  "message": "success",
  "request_id": "xxx"
}
```

普通业务 API 建议统一失败响应：

```json
{
  "success": false,
  "error_code": "INVALID_ARGUMENT",
  "message": "参数错误",
  "request_id": "xxx"
}
```

说明：

1. 普通业务 API 使用 `success / data / error_code / message / request_id`。
2. 当前代码仍有多种响应结构，例如 Pydantic 模型直接返回、列表直接返回、`success/message` 混合返回。
3. 后续代码方案需要分阶段兼容旧响应，不应一次性破坏 React 已接入页面。

### 2.2 Webhook 响应

Webhook 入站接口必须兼容 OpenAPI 文档建议：

```json
{
  "code": 0,
  "msg": "success"
}
```

说明：

1. Webhook 入站接口不使用普通业务 API 响应结构。
2. 当前 `WebhookResponse` 已包含 `code / msg / event_id / lead_id / is_new_lead / is_duplicate / lead_action`。
3. 对外正式响应建议仅保证 `code=0` 和 `msg=success` 稳定，调试字段可保留但不作为第三方依赖。

### 2.3 分页

分页接口统一使用：

```text
page
page_size
total
items
```

建议响应：

```json
{
  "success": true,
  "data": {
    "page": 1,
    "page_size": 20,
    "total": 100,
    "items": []
  },
  "message": "success",
  "request_id": "xxx"
}
```

当前代码差异：

1. `GET /leads` 当前直接返回 `list[LeadOut]`，只支持 `status` 过滤，无分页。
2. `GET /staff` 当前直接返回 `list[StaffOut]`，无分页。
3. `GET /checks` 当前直接返回 `list[CheckOut]`，无分页。
4. `GET /lead-notifications/records` 当前有 `total / records`，但分页只使用 `limit`。

### 2.4 时间字段

时间字段建议使用 ISO8601 字符串。

当前代码现状：

1. 多数 Pydantic 响应直接返回 `datetime`，FastAPI 会序列化为 ISO 风格字符串。
2. 部分接口手动调用 `.isoformat()`，例如通知记录。

后续统一规则：

```text
created_at
updated_at
received_at
processed_at
assigned_at
checked_at
timeout_at
finished_at
```

全部输出为 ISO8601。请求查询参数 `start_time / end_time` 也使用 ISO8601，除非接口明确兼容历史毫秒时间戳。

### 2.5 request_id 与幂等

规则：

1. 所有写接口需要记录 `request_id` 或具备可追踪日志。
2. 所有涉及 webhook / task / callback 的接口必须幂等。
3. `request_id` 可由调用方传入 header `X-Request-Id`，未传时由服务端生成。
4. 当前代码尚未统一实现 `request_id`，本轮只定义契约。

幂等重点：

1. Webhook：`event_key`、`server_message_id`。
2. 线索消费：`customer_id + external_lead_id` 或 `customer_id + dedupe_key`。
3. 微信任务：`task_id`、任务状态机。
4. 任务回写：同一 `task_id + result_version` 或同一最终状态不可重复推进。
5. 状态回调：`lead_id + internal_status + callback_url`。

------

## 3. Webhook 入站接口

### 3.1 路径

PRD 目标路径：

```text
POST /webhook/douyin
```

当前真实已有路径：

```text
POST /webhook/douyin
POST /integrations/douyin/webhook
```

当前代码位置：

```text
app/routers/integrations.py
```

当前两个入口复用 `_handle_douyin_webhook()`。

正式域名反代关系：

```text
callback.misanduo.com/webhook/douyin
  ↓
auto_wechat:9000/webhook/douyin
```

兼容建议：

1. `/webhook/douyin` 作为正式对外路径保留。
2. `/integrations/douyin/webhook` 可作为内部联调路径保留，但正式验收不依赖它。
3. 两个入口行为必须一致，包括验签、幂等、日志、响应结构。

### 3.2 请求 Header

生产环境必须包含：

```text
Authorization: signature
X-Auth-Timestamp: timestamp
Content-Type: application/json
```

说明：

1. `Authorization` 保存签名值。
2. `X-Auth-Timestamp` 为秒级时间戳。
3. `Content-Type` 为 `application/json`。
4. 开发环境可配置关闭验签，但必须记录验签关闭状态。

### 3.3 验签规则

```text
signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

要求：

1. `body` 必须使用原始请求体。
2. 不允许使用 JSON 重新序列化后的 body 验签。
3. `timestamp` 为秒级时间戳。
4. `SECRET_KEY` 第一版按客户 / 商户维度配置。
5. 生产环境必须强制验签。
6. 开发环境可配置关闭验签。
7. 未配置 `SECRET_KEY` 时，生产环境不得静默放行。

当前代码现状：

1. `app/routers/integrations.py` 使用 `await request.body()`，符合原始 body 要求。
2. `app/integrations/douyin_webhook.py::verify_signature()` 已按 `DY_SECRET_KEY + body + "-" + timestamp` 计算。
3. 当前 `DY_SECRET_KEY` 来自全局环境变量，尚不是客户 / 商户维度。
4. 当前 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 默认关闭，与新 PRD 生产强制验签冲突。

### 3.4 请求体

已知外层字段示例：

```json
{
  "event": "im_receive_msg",
  "from_user_id": "xxx",
  "to_user_id": "xxx",
  "client_key": "xxx",
  "content": "{\"conversation_short_id\":\"xxx\",\"server_message_id\":\"xxx\"}"
}
```

说明：

1. `content` 是字符串化 JSON，需要二次解析。
2. 用户私信纯文本字段需要从 `content` 内部解析。
3. 当前代码 `parse_content()` 兼容字符串 JSON 和对象。
4. 当前代码 `normalize_message_text()` 从 `text / content / title / message` 中取消息文本。
5. 第一版从私信纯文本提取手机号 / 微信号。
6. 第一版不依赖顶层 `phone / wechat`。
7. 第一版不依赖 `retain_consult_card`。
8. 第一版不接入 LLM。

### 3.5 响应规则

| 场景 | HTTP 状态码 | 响应 |
|---|---:|---|
| 成功接收 | 200 | `{"code":0,"msg":"success"}` |
| 重复事件 | 200 | `{"code":0,"msg":"success"}` |
| 非线索事件 | 200 | `{"code":0,"msg":"success"}` |
| 无效线索 | 200 | `{"code":0,"msg":"success"}` |
| 请求格式错误 | 400 | 错误信息 |
| 签名失败 | 401 | 错误信息 |
| 过期请求 | 401 | 错误信息 |
| 系统异常 | 500 | 错误信息 |

成功响应：

```json
{
  "code": 0,
  "msg": "success"
}
```

### 3.6 幂等规则

必须支持：

1. `event_key` 幂等。
2. `server_message_id` 幂等。
3. 建议唯一：`customer_id + server_message_id`。
4. 重复事件不重复创建线索。
5. 重复事件仍返回成功。

当前代码现状：

1. `build_event_key()` 基于 `event / from_user_id / to_user_id / conversation_short_id / server_message_id / create_time` 计算 SHA256。
2. `douyin_webhook_events.event_key` 当前是唯一索引。
3. 当前重复事件返回已有 `event_id`，不插入新事件。

后续改造建议：

1. 重复事件需要记录幂等命中结果，可通过原事件字段或单独日志表达。
2. 引入 `customer_id` 后，幂等键需要纳入商户维度。
3. `server_message_id` 应从 `content` 中结构化保存。

------

## 4. AI小高线索 → 小高AI微信助手接口边界

AI小高线索与小高AI微信助手是独立售卖、独立启动的服务。第一版可在当前单仓库内用服务层模拟边界，但契约上必须预留为 HTTP 服务间接口。

### 4.1 方案 A：小高AI微信助手主动拉取有效线索

示例接口：

```text
GET /internal/leads/pending?customer_id=xxx&limit=50
POST /internal/leads/{lead_id}/consume-result
```

`GET /internal/leads/pending` 返回示例：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "lead_id": "xxx",
        "customer_id": "xxx",
        "external_lead_id": "xxx",
        "dedupe_key": "xxx",
        "douyin_display_name": "客户昵称",
        "phone": "13800000000",
        "wechat": "wxid_xxx",
        "all_extracted_contacts": [],
        "raw_message_text": "加我微信 wxid_xxx",
        "latest_active_time": "2026-06-15T10:00:00"
      }
    ]
  },
  "message": "success",
  "request_id": "xxx"
}
```

`POST /internal/leads/{lead_id}/consume-result` 请求示例：

```json
{
  "customer_id": "xxx",
  "consume_status": "accepted",
  "assistant_lead_id": 123,
  "reason": ""
}
```

优点：

1. AI小高线索故障时，小高AI微信助手可继续处理已拉取任务。
2. 小高AI微信助手故障时，AI小高线索仍可保存线索。
3. 不需要消息队列。
4. 后续服务拆分更平滑。

### 4.2 方案 B：AI小高线索推送有效线索

示例接口：

```text
POST /internal/wechat-assistant/leads
```

请求示例：

```json
{
  "customer_id": "xxx",
  "external_lead_id": "xxx",
  "dedupe_key": "xxx",
  "open_id": "xxx",
  "account_open_id": "xxx",
  "phone": "13800000000",
  "wechat": "wxid_xxx",
  "raw_message_text": "加我微信 wxid_xxx",
  "all_extracted_contacts": []
}
```

优点：

1. 实时性更好。
2. 链路更短。

缺点：

1. 对小高AI微信助手可用性要求更高。
2. 失败重试和幂等更复杂。
3. 如果小高AI微信助手故障，AI小高线索需要维护重试队列。

### 4.3 推荐方案

第一版推荐：

```text
优先采用方案 A：小高AI微信助手主动拉取有效线索，或在当前单仓库内用服务层模拟拉取边界。
```

推荐理由：

1. 符合服务故障隔离目标。
2. 不需要第一版引入消息队列。
3. 与当前 `POST /integrations/douyin/sync-leads` 的拉取式历史模式更接近，迁移更平滑。
4. 后续服务拆分时，只需把服务层边界替换为 HTTP API。

------

## 5. 商户前端接口

商户前端接口面向外部客户系统 / React 商户端。目标接口需要统一多商户、分页、状态映射和响应结构。

### 5.1 首页概览

目标接口：

```text
GET /dashboard/summary
```

第一版：必须实现。

返回字段：

```text
today_leads_count
pending_assign_count
assigned_count
replied_count
timeout_count
agent_status
wechat_status
douyin_auth_status
latest_webhook_status
```

当前兼容：

1. 当前已有 `GET /reports/summary`，返回 `total_leads / assigned_count / replied_count / timeout_count / pending_count / staff_stats`。
2. 后续可先由 `/dashboard/summary` 复用 `report_service`，再补 Agent、授权、webhook 状态。

### 5.2 线索列表

目标接口：

```text
GET /leads
```

查询参数：

```text
page
page_size
status
keyword
start_time
end_time
staff_id
contact_extract_status
```

返回字段至少包括：

```text
lead_id
customer_id
douyin_display_name
phone
wechat
all_extracted_contacts
status
assigned_staff_name
latest_event
latest_active_time
created_at
updated_at
```

当前兼容：

1. 当前 `GET /leads` 已存在，但只支持 `status`，无分页。
2. 当前返回旧字段 `customer_name / customer_contact / content / source_id`。
3. 后续需要兼容旧字段，同时逐步补充目标字段。

### 5.3 线索详情

目标接口：

```text
GET /leads/{lead_id}
```

返回：

1. 线索基础信息。
2. 原始私信文本。
3. 联系方式提取结果。
4. 分配记录。
5. 微信任务记录。
6. 回复检测记录。
7. 超时记录。
8. 人工处理记录。

当前兼容：

1. 当前 `GET /leads/{lead_id}` 已存在，只返回 `LeadOut`。
2. 后续需要扩展详情响应，不建议直接破坏现有 `LeadOut`；可新增详情 schema 或在 `data` 中扩展。

### 5.4 销售列表

目标接口：

```text
GET /staff
POST /staff
PUT /staff/{staff_id}
DELETE /staff/{staff_id}
```

规则：

1. 删除建议软删除或停用。
2. 微信昵称必填。
3. `customer_id + wechat_nickname` 唯一。

当前兼容：

1. 当前已有 `GET /staff`、`POST /staff`、`GET /staff/{staff_id}`、`PUT /staff/{staff_id}`。
2. 当前没有 `DELETE /staff/{staff_id}`。
3. 当前 `StaffCreate.name` 必填，`wechat_nickname` 可空；目标规则需要改为微信昵称必填。
4. 当前没有 `customer_id` 和唯一约束。

### 5.5 销售 Excel 导入

目标接口：

```text
GET /staff/import-template
POST /staff/import
```

第一版：必须实现。

要求：

1. 模板下载。
2. 微信昵称必填。
3. 销售姓名、手机号、备注可空。
4. 重复微信昵称覆盖。
5. 支持部分成功。
6. 返回错误行号和原因。

当前兼容：

当前未发现销售导入接口。

### 5.6 关键词配置

目标接口：

```text
GET /settings/reply-keywords
PUT /settings/reply-keywords
```

规则：

1. 不要与线索模板内容重复。
2. 不要设置过短关键词。
3. 不要设置过宽泛关键词。
4. 应配置明确表达已处理意图的关键词。

当前兼容：

1. 当前关键词保存在 `check_configs.effective_keywords`。
2. 当前未发现配置管理接口。
3. 后续需升级为客户维度配置。

### 5.7 工作时间配置

目标接口：

```text
GET /settings/work-time
PUT /settings/work-time
```

要求：

1. 客户统一工作时间。
2. 非工作时间有效线索进入 `delay_assign`。
3. `delay_assign` 对外映射为“未分配”。

当前兼容：

当前未发现工作时间配置接口，也未发现 `delay_assign` 状态落地。

### 5.8 超时 / 重分配配置

目标接口：

```text
GET /settings/timeout
PUT /settings/timeout
```

要求：

1. 默认超时时间 30 分钟。
2. 最大重分配次数 5。
3. 重分配排除原销售。

当前兼容：

1. 当前超时时间通过 `check_configs.reply_deadline_minutes` 读取。
2. 当前未发现配置 API。
3. 当前未发现最大重分配次数配置和重分配排除逻辑。

### 5.9 Local Agent 状态

目标接口：

```text
GET /agent/status
```

返回：

```text
agent_client_id
agent_status
wechat_status
last_heartbeat_at
current_task_id
current_task_type
```

当前兼容：

1. 19000 Local Agent 当前有 `GET /health` 和 `GET /agent/version`。
2. 9000 主服务当前未发现 `GET /agent/status`。
3. 当前主库未发现 `agent_clients` 表。

### 5.10 微信任务列表

目标接口：

```text
GET /wechat-tasks
GET /wechat-tasks/{task_id}
```

筛选：

```text
task_type
task_status
staff_id
lead_id
start_time
end_time
```

当前兼容：

1. 当前已有 `GET /wechat-tasks/pending` 和 `GET /wechat-tasks/{task_id}`。
2. 当前没有通用 `GET /wechat-tasks` 列表接口。
3. 当前 `pending` 支持 `task_type / staff_id / limit`。

### 5.11 回复检测列表

目标接口：

```text
GET /reply-checks
```

筛选：

```text
lead_id
staff_id
check_status
start_time
end_time
matched_keyword
```

当前兼容：

1. 当前已有 `GET /checks`，只支持 `status`。
2. 后续可保留 `/checks` 兼容旧前端，同时新增或重命名为 `/reply-checks`。

### 5.12 超时列表

目标接口：

```text
GET /timeouts
```

当前兼容：

当前未发现独立超时列表接口。当前超时记录混在 `reply_checks` 与 `douyin_leads.status=timeout` 中。

### 5.13 人工处理

目标接口：

```text
POST /leads/{lead_id}/manual-reassign
POST /leads/{lead_id}/manual-reply
POST /leads/{lead_id}/manual-close
```

规则：

1. `manual_reassign` 后进入未分配或分配流程。
2. `manual_reply` 后可进入已回复。
3. `manual_close` 后进入 `closed`。
4. 第一版 `closed` 后不允许恢复。

当前兼容：

1. 当前已有 `POST /replies/manual`。
2. 当前未发现 `manual-reassign`、`manual-close`。
3. 当前未发现 `manual_actions` 审计表。

### 5.14 数据导出

目标接口：

```text
POST /exports
GET /exports
GET /exports/{export_id}
GET /exports/{export_id}/download
```

要求：

1. 导出 Excel。
2. 支持按时间范围。
3. 导出不脱敏。
4. 导出不改变业务状态。

当前兼容：

当前未发现导出接口或 `export_tasks` 表。

------

## 6. Local Agent 接口契约

Local Agent 分为两侧：

1. 19000 本地 Agent 接口：运行在客户电脑，只监听 `127.0.0.1:19000`。
2. 9000 主服务接口：提供任务查询、任务回写、回复分析。

### 6.1 心跳

目标主服务接口：

```text
POST /agent/heartbeat
```

第一版：建议实现。

请求字段：

```text
agent_client_id
agent_name
host_name
wechat_status
agent_status
current_task_id
version
```

响应：

```json
{
  "success": true,
  "data": {
    "server_time": "2026-06-15T10:00:00",
    "next_heartbeat_seconds": 30
  },
  "message": "success",
  "request_id": "xxx"
}
```

当前兼容：

1. 当前 19000 有 `GET /health`，但它只返回本地 Agent 状态。
2. 当前 9000 未发现 `POST /agent/heartbeat`。
3. 当前主库未发现 `agent_clients` 表。

### 6.2 拉取发送任务

当前真实 Local Agent 路径：

```text
POST /agent/tasks/poll-and-execute
```

目标语义：

1. 同一 `agent_client_id` 同一时间只允许一个任务。
2. 忙碌返回 `agent_busy`。
3. 任务类型目标命名为 `send_notice`。
4. 当前兼容任务类型为 `notify_sales`。
5. 失败必须回写。

当前代码事实：

1. 19000 `poll-and-execute` 会拉取 9000 `/wechat-tasks/{task_id}` 或 `/wechat-tasks/pending?task_type=notify_sales&limit=1`。
2. 只处理 `notify_sales`。
3. 当前只允许 `target_nickname=Aw3`。
4. 当前只允许 `mode=paste_only`。
5. 当前运行锁 `_wechat_task_lock` 与检测任务共享。

### 6.3 拉取检测任务

当前真实 Local Agent 路径：

```text
POST /agent/tasks/poll-and-detect
```

目标语义：

1. 与发送任务互斥。
2. 严格只读。
3. 不允许粘贴。
4. 不允许发送。
5. 任务类型为 `detect_reply`。

当前代码事实：

1. 19000 `poll-and-detect` 支持 `task_id` 指定执行。
2. 无 `task_id` 时拉取 `/wechat-tasks/pending?task_type=detect_reply&limit=1`。
3. 返回 `action.sent=false`、`action.pasted=false`。
4. 使用共享运行锁避免并发操作微信。

### 6.4 任务结果回写

当前真实主服务接口：

```text
POST /wechat-tasks/{task_id}/result
POST /replies/agent-write-back
```

说明：

1. `/wechat-tasks/{task_id}/result` 用于任务执行结果回写和任务状态推进。
2. `/replies/agent-write-back` 用于 Local Agent 把读取到的微信消息交给 9000 分析有效回复。
3. 当前两个接口均已存在。

目标回写字段：

```text
task_id
agent_client_id
status
failure_stage
failure_reason
manual_required
pasted
sent
detect_count
matched_keyword
message_text
result_json
```

当前兼容字段：

```text
success
verified
partial_match
manual_review_required
pasted
sent
failure_stage
agent_hostname
agent_pid
raw_result
detected_status
detect_count
```

兼容建议：

1. 保留 `/wechat-tasks/{task_id}/result` 作为任务状态回写入口。
2. 保留 `/replies/agent-write-back` 作为回复分析入口，后续可收敛为任务结果的一部分，但不在第一版强行合并。
3. 补充 `agent_client_id`，不要只依赖 `agent_hostname / agent_pid`。
4. 任务回写必须幂等，同一最终状态重复回写不得重复创建检测记录或通知记录。

------

## 7. NewCarProject 对接预留接口

当前状态：

```text
NewCarProject 同事暂时不能继续推进 token / cookie / roles / merchant_id 具体字段结构。
```

因此本轮只做预留契约。

### 7.1 跳转入口

预留路径：

```text
GET /auth/newcar/entry
```

预留参数：

```text
token
merchant_id
redirect
```

Cookie：

```text
NewCarProject 具体 cookie 名称待确认
```

规则：

1. auto_wechat 需要支持识别 token 和 cookie。
2. 商户进入 auto_wechat 后，不允许由 auto_wechat 跳转其他子功能。
3. 非商户角色的多子功能菜单由 NewCarProject 负责。

### 7.2 token 校验

预留路径：

```text
POST /auth/newcar/verify
```

预留返回：

```json
{
  "user_id": "xxx",
  "merchant_id": "xxx",
  "roles": [],
  "permissions": [],
  "expired_at": "xxx"
}
```

必须说明：

1. 具体字段结构待 NewCarProject 同事确认。
2. auto_wechat 本地生成 `customer_id`。
3. NewCarProject 商户 ID 保存为 `external_customer_id`。
4. 后续正式对接不得破坏本地 `customer_id`。
5. `roles / permissions` 只用于 auto_wechat 子系统内权限，不负责其他子功能跳转。

------

## 8. 修改密码接口

目标接口：

```text
POST /auth/change-password
```

请求字段：

```text
old_password
new_password
confirm_password
```

规则：

1. 需要旧密码。
2. 新密码最少 8 位。
3. 建议数字 + 字母。
4. 修改后强制重新登录。
5. 第一版不支持重置密码。

当前兼容：

当前未发现认证、登录、修改密码相关接口。后续需要与 NewCarProject 对接预留一起设计。

------

## 9. 状态同步 / 回调接口

第一版如果需要对外状态同步，有两种形式：

1. auto_wechat 调用客户配置的外部 URL。
2. 外部系统调用 auto_wechat 查询状态。

建议优先采用 auto_wechat 调用外部 URL，并记录 `callback_logs`。

预留入站配置或测试路径：

```text
POST /callbacks/status
```

对外状态只包括：

```text
未分配
已分配
已回复
超时未回复
```

内部映射：

```text
pending_assign → 未分配
delay_assign → 未分配
reassigned → 未分配
assigned → 已分配
replied → 已回复
timeout → 超时未回复
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

1. `callback_success` 只是内部日志状态。
2. `invalid` 不回调。
3. `closed` 不回调。
4. `failed / manual_required` 不回调。
5. 当前 `feedback_records` 是旧微信反馈记录，不等同于目标 `callback_logs`。

当前兼容：

当前未发现目标状态同步接口或 `callback_logs` 表。

------

## 10. 健康检查接口

目标接口：

```text
GET /health
GET /health/webhook
GET /health/agent
```

要求：

1. 可用于服务独立启动检查。
2. 可用于后续拆服务器部署。
3. 不涉及智能路由。
4. 返回服务名、版本、状态、时间。

建议响应：

```json
{
  "success": true,
  "data": {
    "service": "auto_wechat",
    "version": "0.1.0",
    "status": "ok",
    "time": "2026-06-15T10:00:00"
  },
  "message": "success",
  "request_id": "xxx"
}
```

当前兼容：

1. 9000 当前只有 `GET /` 根路径。
2. 19000 Local Agent 当前已有 `GET /health`。
3. 9000 未发现 `GET /health`、`GET /health/webhook`、`GET /health/agent`。

------

## 11. 错误码设计

第一版错误码建议：

```text
INVALID_ARGUMENT
UNAUTHORIZED
SIGNATURE_MISMATCH
REQUEST_EXPIRED
SECRET_KEY_MISSING
DUPLICATE_EVENT
EVENT_NOT_LEAD
CONTACT_NOT_FOUND
CONTACT_EXTRACT_FAILED
AGENT_BUSY
WECHAT_UNAVAILABLE
WECHAT_FOCUS_UNVERIFIED
TASK_NOT_FOUND
TASK_ALREADY_DONE
LEAD_NOT_FOUND
STAFF_NOT_FOUND
EXPORT_FAILED
INTERNAL_ERROR
```

适用范围：

| 错误码 | Webhook | 普通业务 API | Local Agent | 说明 |
|---|---|---|---|---|
| `INVALID_ARGUMENT` | 是 | 是 | 是 | 参数错误、JSON 格式错误 |
| `UNAUTHORIZED` | 是 | 是 | 否 | 未认证或无权限 |
| `SIGNATURE_MISMATCH` | 是 | 否 | 否 | webhook 签名不匹配 |
| `REQUEST_EXPIRED` | 是 | 否 | 否 | timestamp 过期 |
| `SECRET_KEY_MISSING` | 是 | 否 | 否 | 生产密钥缺失 |
| `DUPLICATE_EVENT` | 是 | 否 | 否 | 重复事件，HTTP 仍返回 200 |
| `EVENT_NOT_LEAD` | 是 | 否 | 否 | 非线索事件，HTTP 仍返回 200 |
| `CONTACT_NOT_FOUND` | 是 | 是 | 否 | 未提取到联系方式 |
| `CONTACT_EXTRACT_FAILED` | 是 | 是 | 否 | 联系方式提取失败 |
| `AGENT_BUSY` | 否 | 是 | 是 | Local Agent 正忙 |
| `WECHAT_UNAVAILABLE` | 否 | 是 | 是 | 微信窗口不可用 |
| `WECHAT_FOCUS_UNVERIFIED` | 否 | 是 | 是 | 搜索框或焦点未确认 |
| `TASK_NOT_FOUND` | 否 | 是 | 是 | 任务不存在 |
| `TASK_ALREADY_DONE` | 否 | 是 | 是 | 任务已结束 |
| `LEAD_NOT_FOUND` | 否 | 是 | 否 | 线索不存在 |
| `STAFF_NOT_FOUND` | 否 | 是 | 否 | 销售不存在 |
| `EXPORT_FAILED` | 否 | 是 | 否 | 导出失败 |
| `INTERNAL_ERROR` | 是 | 是 | 是 | 系统异常 |

Webhook 注意：

1. `DUPLICATE_EVENT / EVENT_NOT_LEAD / CONTACT_NOT_FOUND` 属于业务结果，HTTP 仍返回 200。
2. `SIGNATURE_MISMATCH / REQUEST_EXPIRED` 返回 401。
3. `SECRET_KEY_MISSING` 在生产环境不得静默放行，建议返回 500 或启动时阻断，具体由验签迁移技术方案确定。

------

## 12. 当前接口与目标接口兼容策略

### 12.1 当前已有接口列表

9000 主服务当前已有：

| 方法 | 路径 | 当前用途 |
|---|---|---|
| `GET` | `/` | 根路径信息 |
| `POST` | `/webhook/douyin` | 抖音 webhook 兼容入口 |
| `POST` | `/integrations/douyin/webhook` | 抖音 webhook 内部入口 |
| `POST` | `/integrations/douyin/sync-leads` | 旧 douyinAPI 拉取同步 |
| `GET/POST` | `/leads` | 线索列表 / 创建 |
| `GET` | `/leads/{lead_id}` | 线索详情 |
| `POST` | `/leads/{lead_id}/assign` | 分配线索 |
| `GET/POST` | `/staff` | 销售列表 / 创建 |
| `GET/PUT` | `/staff/{staff_id}` | 销售详情 / 更新 |
| `GET` | `/checks` | 回复检测列表 |
| `POST` | `/checks/run` | 手动超时检测 |
| `GET` | `/reports/summary` | 汇总报表 |
| `POST` | `/replies/manual` | 手动录入回复 |
| `POST` | `/replies/current-wechat-detect` | 旧当前窗口检测 |
| `POST` | `/replies/agent-write-back` | Local Agent 回复分析回写 |
| `POST` | `/wechat-tasks` | 创建微信任务 |
| `GET` | `/wechat-tasks/pending` | 查询 pending 任务 |
| `GET` | `/wechat-tasks/{task_id}` | 查询任务详情 |
| `POST` | `/wechat-tasks/{task_id}/result` | 任务结果回写 |
| `GET/POST` | `/wechat-auto-detect/*` | 旧自动检测目标 |
| `GET/POST` | `/automation/*` | 紧急停止 / 恢复 |
| `POST/GET` | `/feedback/*` | 旧微信反馈链路 |
| `POST/GET` | `/lead-notifications/*` | 旧线索通知链路 |

19000 Local Agent 当前已有：

| 方法 | 路径 | 当前用途 |
|---|---|---|
| `GET` | `/health` | Local Agent 健康检查 |
| `GET` | `/agent/version` | 版本和路由诊断 |
| `GET` | `/agent/tasks/server-url` | 主服务地址诊断 |
| `POST` | `/agent/tasks/poll-and-execute` | 拉取并执行 notify_sales |
| `POST` | `/agent/tasks/poll-and-detect` | 拉取并执行 detect_reply |
| `POST` | `/agent/replies/detect` | 旧回复检测入口 |
| `GET/POST` | `/agent/wechat/*` | 微信窗口诊断 / 测试 |
| `GET/POST` | `/agent/ocr/*` | OCR 状态 / 预热 |

### 12.2 当前接口与目标接口映射

| 目标接口 | 当前接口 | 策略 |
|---|---|---|
| `POST /webhook/douyin` | 已存在 | 保留正式路径，补生产验签和字段处理 |
| `GET /dashboard/summary` | `/reports/summary` | 新增目标路径或由前端过渡使用旧路径 |
| `GET /leads` | 已存在 | 复用路径，补分页和目标字段 |
| `GET /leads/{lead_id}` | 已存在 | 复用路径，扩展详情响应 |
| `GET/POST/PUT/DELETE /staff` | 部分存在 | 补软删除、导入、微信昵称必填 |
| `GET /reply-checks` | `/checks` | 保留旧路径，新增目标语义或兼容别名 |
| `GET /wechat-tasks` | `/wechat-tasks/pending` 部分覆盖 | 新增通用列表 |
| `POST /agent/heartbeat` | 未发现 | 新增 |
| `GET /agent/status` | 未发现 | 新增主服务视角状态 |
| `POST /wechat-tasks/{task_id}/result` | 已存在 | 复用并补幂等和 `agent_client_id` |
| `POST /replies/agent-write-back` | 已存在 | 复用，后续收敛职责 |
| `GET /health` | 9000 未发现，19000 已有 | 9000 新增，19000 保留 |
| `POST /auth/newcar/verify` | 未发现 | 预留 |
| `POST /auth/change-password` | 未发现 | 新增 |
| `POST /exports` | 未发现 | 新增 |
| 状态同步回调 | `/feedback/*` 旧链路不同 | 新增 `callback_logs` 相关能力 |

### 12.3 可复用接口

1. `/webhook/douyin`
2. `/integrations/douyin/webhook`
3. `/leads`
4. `/leads/{lead_id}`
5. `/staff`
6. `/staff/{staff_id}`
7. `/wechat-tasks/{task_id}`
8. `/wechat-tasks/{task_id}/result`
9. `/replies/agent-write-back`
10. 19000 `/agent/tasks/poll-and-execute`
11. 19000 `/agent/tasks/poll-and-detect`

### 12.4 需要新增接口

1. `/dashboard/summary`
2. `/staff/import-template`
3. `/staff/import`
4. `/settings/reply-keywords`
5. `/settings/work-time`
6. `/settings/timeout`
7. `/agent/heartbeat`
8. `/agent/status`
9. `/wechat-tasks`
10. `/reply-checks`
11. `/timeouts`
12. `/leads/{lead_id}/manual-reassign`
13. `/leads/{lead_id}/manual-reply`
14. `/leads/{lead_id}/manual-close`
15. `/exports`
16. `/auth/newcar/entry`
17. `/auth/newcar/verify`
18. `/auth/change-password`
19. `/health`
20. `/health/webhook`
21. `/health/agent`

### 12.5 需要改造接口

1. `/webhook/douyin`：生产强制验签、商户级 `SECRET_KEY`、联系方式提取、无效线索处理。
2. `/leads`：分页、多商户、目标字段、联系方式提取字段。
3. `/staff`：微信昵称必填、客户维度唯一、软删除。
4. `/checks`：筛选字段、命名语义与 `/reply-checks` 对齐。
5. `/wechat-tasks/pending`：补 `agent_client_id`、任务类型命名兼容、幂等拉取。
6. `/wechat-tasks/{task_id}/result`：补幂等、`agent_client_id`、`failure_reason`、最终状态保护。
7. `/reports/summary`：升级为 `/dashboard/summary` 所需数据源。

### 12.6 需要兼容旧路径

1. `/webhook/douyin` 必须保留。
2. `/integrations/douyin/webhook` 可保留为内部联调路径。
3. `/checks` 可保留，目标语义迁移到 `/reply-checks`。
4. `/reports/summary` 可保留，目标语义迁移到 `/dashboard/summary`。
5. `/lead-notifications/*` 和 `/feedback/*` 是旧演示链路，产品化接口需谨慎收敛，不直接删除。

### 12.7 涉及破坏性变更的地方

1. `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 迁移为生产强制验签。
2. `LeadOut` 从旧字段升级到目标字段。
3. `StaffCreate` 从 `name` 必填变为 `wechat_nickname` 必填。
4. 线索状态从 `pending` 升级为 `pending_assign` 等目标状态。
5. 任务类型从 `notify_sales` 命名迁移到 `send_notice`。

后续代码方案必须分阶段处理，避免一次性破坏现有 React 和 Local Agent 链路。

------

## 13. 安全与日志要求

必须遵守：

1. Webhook 验签必须记录开启状态。
2. 签名失败不能记录 `SECRET_KEY`。
3. `Authorization` 建议脱敏或 hash 后记录。
4. Local Agent 高风险操作必须有日志。
5. 搜索框焦点未确认时禁止粘贴。
6. 微信窗口不可用时禁止继续操作。
7. 所有任务失败必须有 `failure_stage` 和 `failure_reason`。
8. 所有回写接口必须具备幂等能力。
9. 19000 Local Agent 默认只监听 `127.0.0.1`。
10. 9000 主服务不直接操作微信。
11. 第一版不保存截图、不入库截图。
12. 第一版不接入 LLM。

当前代码事实：

1. 19000 `poll-and-execute` 与 `poll-and-detect` 已共享运行锁。
2. `poll-and-detect` 已要求只读，不粘贴、不发送。
3. 当前演示阶段仍限制 `target_nickname=Aw3`。
4. 当前 `wechat_task_service` 会拒绝 `sent=true`。
5. 当前 webhook 日志会记录 `webhook_auth_required` 和 `source_path`。

------

## 14. 后续依赖文档

P0-API-1 完成后，后续文档顺序：

1. Webhook 验签迁移技术方案
2. 代码修改计划
3. 测试验收计划
4. VibeCoding 分阶段执行计划

后续文档必须遵守：

1. 不把 `douyinAPI` 写成正式生产依赖。
2. 不设计智能路由。
3. 不把 LLM 写入第一版接口契约。
4. 不直接修改 `DOUYIN_WEBHOOK_AUTH_REQUIRED` 默认值，必须先出迁移技术方案。
5. 不绕过 Local Agent 安全边界。
6. 不删除旧接口，先做兼容和迁移。

------

## 15. 本轮只读探索记录

已阅读：

1. `docs/ai/01_READING_RULES.md`
2. `docs/ai/05_PROJECT_CONTEXT.md`
3. `docs/ai/06_PRD_AUTO_WECHAT.md`
4. `docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
5. `docs/ai/08_DATA_MODEL_AUTO_WECHAT.md`
6. `docs/ai/02_EXECUTION_RULES.md`
7. `docs/ai/03_TESTING_RULES.md`
8. `docs/ai/04_OUTPUT_RULES.md`
9. `CLAUDE.md`
10. `docs/ai/P1_END_1_ACCEPTANCE.md`
11. `app/main.py`
12. `app/local_agent_main.py`
13. `app/routers/`
14. `app/services/`
15. `app/integrations/`
16. `app/models.py`
17. `app/schemas.py`
18. `app/config.py`
19. `.env.example`

已确认存在：

1. `app/routers/`
2. `app/services/`
3. `app/integrations/`

当前未发现：

1. `app/api/`
2. `app/core/`
3. 9000 主服务 `GET /health`
4. 9000 主服务 `POST /agent/heartbeat`
5. 9000 主服务 `GET /agent/status`
6. `GET /dashboard/summary`
7. 导出接口
8. NewCarProject 认证接口

本轮只做接口契约设计，不修改业务代码、数据库模型、接口实现、测试代码、依赖或配置默认值。

------

## 16. P1-DY-ACCOUNT-AGENT 接口契约落地记录

更新时间：2026-06-18

### 16.1 阶段结论

`P1-DY-ACCOUNT-AGENT` 一期接口链路已完成：

```text
前端企业号绑定控件
  → 9000 企业号列表与绑定接口
  → 9000 绑定校验与 AiAgent 读取
  → 9000 代理注入 agent_config
  → 9100 回复建议
```

### 16.2 企业号与绑定接口

#### `GET /integrations/douyin/accounts`

返回当前商户可见的抖音企业号列表。

关键字段：

- `account_open_id`
- `account_name`
- `avatar_url`
- `bind_status`
- `authorization_status`
- `bound_agent_id`
- `bound_agent_name`
- `bound_agent_status`
- `binding_status`

#### `PUT /integrations/douyin/accounts/{account_open_id}/agent-binding`

为指定企业号保存默认绑定智能体。

请求体：

```json
{
  "agent_id": "agent_xxx"
}
```

9000 必须按可信请求上下文校验企业号归属、授权状态、Agent 归属、Agent active 状态。

#### `DELETE /integrations/douyin/accounts/{account_open_id}/agent-binding`

解绑指定企业号的默认智能体。

解绑后，回复建议不得继续使用旧绑定。

#### `POST /integrations/douyin/accounts/{account_open_id}/cancel-authorization`

本地取消企业号授权。

一期暂未接入真实上游取消授权能力，当前 `upstream_cancel_supported=false`。

成功后：

1. 企业号 `bind_status=0`。
2. 对应 binding 标记为 `invalid`。
3. `invalid_reason=account_unauthorized`。
4. 不得继续生成回复建议。

#### `DELETE /integrations/douyin/accounts/{account_open_id}`

本地软删除企业号。

成功后：

1. 企业号 `bind_status=4`。
2. 对应 binding 标记为 `deleted`。
3. `invalid_reason=account_deleted`。
4. 不得继续生成回复建议。

### 16.3 回复建议接口

#### `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`

前端生成回复建议时调用 9000，不直接调用 9100 正式链路。

9000 处理要求：

1. 不信任前端传入的 `merchant_id`。
2. 不信任前端传入的 `agent_config`。
3. 校验企业号归属、授权状态、Agent 归属、Agent active 状态和 active 绑定关系。
4. 校验通过后读取真实 `AiAgent`。
5. 转发 9100 时注入可信 `agent_config`。
6. `auto_send=false`。

9000 注入给 9100 的 `agent_config` 语义：

```json
{
  "agent_id": "agent_xxx",
  "agent_name": "小高客服",
  "system_prompt": "智能体提示词",
  "knowledge_base_text": "可选知识库上下文",
  "status": "active"
}
```

9100 处理要求：

1. 不直接读取 9000 数据库。
2. 不使用 mock `ACCOUNT_AGENT_BINDINGS` 拦截正式链路。
3. 只消费 9000 注入的可信 `agent_id` / `agent_config`。
4. 收到 `agent_config` 后使用真实 `agent_name`、`system_prompt`、`knowledge_base_text`。
5. 只有 `agent_id` 但没有 `agent_config` 时，保留 `agent_config_missing_fallback` 提示。
6. 未传 `agent_id` 的 demo 路径可继续使用 mock fallback。
7. `auto_send=false`。

### 16.4 错误与安全约束

以下状态不得生成回复建议：

1. 企业号不存在。
2. 企业号不属于当前商户。
3. 企业号已取消授权。
4. 企业号已软删除。
5. Agent 不存在。
6. Agent 不属于当前商户。
7. Agent disabled 或 deleted。
8. active 绑定关系不存在。

一期继续禁止：

1. 自动发送微信。
2. 自动发送抖音私信。
3. 引入 LangChain。
4. 接 Agent tools。
5. 让 9100 mock binding 成为正式绑定依据。

------

## 17. P1-REQ-GAP-1 接口契约待补齐点

更新时间：2026-06-18

本节基于 `docs/ai/P1_REQUIREMENT_GAP_ANALYSIS.md` 补充一期需求差异探索后的接口契约风险。以下内容是后续开发前置约束，不代表已经实现。

### 17.1 NewCarProject 登录与权限契约

当前 `app/auth/newcar_client.py` 只是 NewCarProject 登录态校验门面，`/auth/me` 和 `/auth/callback` 仍用于调试和占位。

正式开工 `P1-GAP-LOGIN-1` 前，必须由 NewCarProject 明确以下字段和规则：

1. `user_id`
2. `username`
3. `role` 或 `role_codes`
4. `merchant_ids`
5. 权限字典，至少覆盖 `auto_wechat` 相关功能码。
6. token / cookie 名称、传递方式、过期时间和刷新规则。
7. 商户禁用、套餐过期、无权限时的错误码。

不得在 auto_wechat 中写死 NewCarProject 返回结构。后续应通过 adapter 将外部响应转换为 `RequestContext`。

### 17.2 权限菜单与路由隔离契约

当前前端 `SideNav.tsx` 主要按本地 `role` 控制菜单，`App.tsx` 只注册少量路由，不能作为完整权限边界。

后续契约要求：

1. `/auth/me` 稳定返回 `permission_codes`、`role_codes`、`merchant_ids`、`super_admin`。
2. 前端菜单和路由守卫基于权限字典，不基于写死账号或本地 role 推断。
3. 后端接口必须以 `RequestContext` 为准二次校验，前端隐藏菜单不能作为权限控制。
4. 涉及商户数据的接口必须从可信上下文取 `merchant_id`，不得信任请求体或查询参数中的商户归属。

### 17.3 线索商户隔离接口契约

当前 `/leads` 已接入 `RequestContext`，但 `douyin_leads` 数据模型缺少商户字段，导致接口无法强制按商户隔离。

后续契约要求：

1. `GET /leads`、`GET /leads/{id}`、`POST /leads/{id}/assign` 等接口必须按 `RequestContext.merchant_id` 过滤。
2. webhook 生成线索时必须能确定可信 `merchant_id`，推荐通过抖音企业号 `account_open_id` 映射 `douyin_authorized_accounts`。
3. 无法确认商户归属的事件不得进入普通商户线索列表，应进入隔离区、invalid 原始事件或人工处理清单。
4. super_admin 跨商户查看必须有明确权限和商户筛选参数。

### 17.4 小高算力接口与前端接入边界

当前后端已提供一期小高算力接口：

1. 商户侧：`GET /compute/summary`、`GET /compute/transactions`、`GET /compute/packages`、`POST /compute/recharge-orders`。
2. 管理员侧：`GET/POST/PUT /admin/compute/packages`、`POST /admin/merchants/{merchant_id}/compute/recharge`、`POST /admin/merchants/{merchant_id}/compute/grant-package`。
3. 内部记账：`POST /internal/compute/usage`。

当前前端 `ComputeCenter.tsx` 和 `SuperComputeConfig.tsx` 仍显示真实接口未接入。后续 `P1-GAP-COMPUTE-FE-1` 可以优先做前端接入，但必须保留：

1. `POST /compute/recharge-orders` 仍是 mock 订单，不真实支付、不实际到账、不写流水。
2. `/internal/compute/usage` 一期不做余额不足拦截。
3. 管理员接口仅允许 `super_admin`。
4. 生产环境内部 usage 必须配置 `COMPUTE_INTERNAL_TOKEN`，避免外部滥用。
