# auto_wechat / 小高AI微信助手 第一版产品化代码修改计划

版本：P0-CODEPLAN-1 / P0-CODEPLAN-1A  
日期：2026-06-15  
范围：本轮只输出代码修改计划，不修改业务代码、不修改数据库模型、不新增接口、不改测试代码、不改依赖、不改配置默认值、不启动服务、不执行迁移。

## 0. 文档依据

本计划基于以下已冻结或已完成文档：

1. `docs/ai/06_PRD_AUTO_WECHAT.md`
2. `docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
3. `docs/ai/08_DATA_MODEL_AUTO_WECHAT.md`
4. `docs/ai/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`
5. `docs/ai/10_WEBHOOK_AUTH_MIGRATION.md`

同时基于当前代码只读探索结果。当前代码仍是 demo / 验收链路逐步演进后的实现，不等同于第一版产品化完成状态。

## 1. 当前真实调用链摘要

### 1.1 服务启动与路由装配

`app/main.py` 中 `create_app()` 创建 FastAPI 应用，并在启动前调用：

```text
Base.metadata.create_all(bind=engine)
```

当前没有发现 Alembic 迁移体系，数据库结构主要依赖 SQLAlchemy `create_all` 初始化。`create_all` 不会自动给已有 SQLite 表补字段，因此后续任何字段新增都不能只改 `app/models.py`，必须配套迁移或兼容脚本。

当前 9000 主服务装配的核心路由包括：

```text
/staff
/leads
/checks
/reports
/integrations/douyin
/webhook
/wechat-auto-detect
/automation
/wechat-tasks
/replies
/feedback
/lead-notifications
```

Windows 专用路由在非 Windows 环境可能跳过导入，这是当前项目既有兼容逻辑。

### 1.2 Webhook 入口

当前两个 webhook 入口都在 `app/routers/integrations.py`：

```text
POST /integrations/douyin/webhook
POST /webhook/douyin
```

两个入口均读取 `request.body()` 原始请求体，然后调用共享函数：

```text
_handle_douyin_webhook()
```

`/webhook/douyin` 是正式 callback 兼容路径，用于承接：

```text
callback.misanduo.com/webhook/douyin
```

`/integrations/douyin/webhook` 是内部 / 新路径入口，当前行为与正式路径共用处理逻辑。

### 1.3 Webhook 验签调用链

当前验签函数在：

```text
app/integrations/douyin_webhook.py
```

函数：

```text
verify_signature(body, timestamp_str, signature)
```

当前算法已经符合 PRD / OpenApi 规则：

```text
sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

当前配置读取位置：

```text
app/config.py
DY_SECRET_KEY = os.getenv("DY_SECRET_KEY", "")
DOUYIN_WEBHOOK_AUTH_REQUIRED = os.getenv("DOUYIN_WEBHOOK_AUTH_REQUIRED", "false").lower() == "true"
```

`.env.example` 当前也示例为：

```text
DY_SECRET_KEY=
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

当前行为：

1. `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 时，`_handle_douyin_webhook()` 完全跳过 `verify_signature()`。
2. `DOUYIN_WEBHOOK_AUTH_REQUIRED=true` 时，缺少 `X-Auth-Timestamp` 或 `Authorization` 会返回 401。
3. timestamp 非法 / 过期会返回 401。
4. 签名错误会返回 401。
5. `DY_SECRET_KEY` 缺失时当前 `verify_signature()` 抛出 500。
6. 当前缺少生产环境强制验签保护，`false` 默认值存在被带入生产的风险。

### 1.4 原始事件写入调用链

当前 webhook 业务处理函数：

```text
app/integrations/douyin_webhook.py
process_webhook_event()
```

核心流程：

```text
payload
  -> build_event_key()
  -> find_existing_event()
  -> im_receive_msg 时 upsert_lead_from_webhook()
  -> persist_webhook_event()
  -> douyin_webhook_events
```

当前原始事件物理表为：

```text
douyin_webhook_events
```

当前字段较少：

```text
id
event
from_user_id
to_user_id
event_key
is_duplicate
lead_id
raw_body
created_at
```

PRD 目标语义域是 `lead_source_events`。第一版代码改造应先保留 `douyin_webhook_events` 表名，由它语义承接 `lead_source_events`，再逐步补字段。

### 1.5 douyin_leads upsert 调用链

当前 `im_receive_msg` 会进入：

```text
upsert_lead_from_webhook()
```

当前查找线索的依据：

```text
source = "douyin"
source_id = from_user_id
```

当前创建线索时：

```text
status = "pending"
customer_contact = None
content = normalize_message_text(content)
raw_data = webhook_payload + parsed_content
```

当前冲突点：

1. 当前所有 `im_receive_msg` 都可能创建 / 更新 `douyin_leads`。
2. 当前没有以手机号 / 微信号提取结果作为有效线索门槛。
3. 当前没有独立 `raw_message_text`、`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`contact_extract_status`、`contact_extract_reason` 字段。
4. 当前 `source_id` 主要承担外部用户 ID / 去重字段，不等同于 PRD 的 `external_lead_id`、`dedupe_key`、`open_id + account_open_id` 组合。

### 1.6 联系方式提取现状

当前没有发现独立的手机号 / 微信号提取服务。`normalize_message_text()` 只负责从 `content` 中取文本：

```text
text
content
title
message
```

当前没有发现针对以下规则的实现：

```text
中国大陆 11 位手机号
微信 / wx / vx / v / 加我 后面的账号
多个联系方式全部保存，主字段取第一个
```

### 1.7 当前主要数据表

当前 `app/models.py` 已有主要表：

```text
sales_staff
douyin_leads
reply_checks
check_configs
feedback_records
lead_notifications
wechat_tasks
douyin_webhook_events
```

当前未发现：

```text
customers
douyin_accounts
lead_source_events
lead_assignments
lead_timeouts
manual_actions
callback_logs
export_tasks
agent_clients
agent_task_runs
```

当前主要业务表没有统一 `customer_id` / `external_customer_id` 字段，仍偏单客户 demo / 本地验收形态。

### 1.8 分配、任务、回复检测链路

当前手动分配入口：

```text
POST /leads/{lead_id}/assign
  -> app/services/assign_service.py
  -> assign_lead()
  -> douyin_leads.status = assigned
  -> 创建 reply_checks.pending
```

当前自动分配：

```text
auto_assign_next()
```

它按活跃销售的当前分配数量做简单选择，不是 PRD 要求的“按客户销售列表顺序轮流分配 + 排序 + 避免连续过多 + 非工作时间 delay_assign”完整规则。

当前微信任务：

```text
POST /wechat-tasks
GET /wechat-tasks/pending
POST /wechat-tasks/{task_id}/result
```

当前任务类型：

```text
notify_sales
detect_reply
```

当前安全门禁：

1. `notify_sales` 只允许 `target_nickname=Aw3`，只允许 `mode=paste_only`。
2. `detect_reply` 允许 `read_only` / `paste_only`，但检测链路说明为不写入。
3. 结果回写中 `sent=true` 会被拒绝。
4. `verified=false` / `partial_match=true` / `manual_review_required=true` 会阻断。
5. `notify_sales` pasted 成功后会尝试创建 `detect_reply` 任务。

这些门禁是现有 Local Agent 安全边界的重要回归点，后续产品化不能无意放宽。

### 1.9 Local Agent 19000 现状

当前 Local Agent 在 `app/local_agent_main.py`，主要接口包括：

```text
GET /health
GET /agent/version
POST /agent/tasks/poll-and-execute
POST /agent/tasks/poll-and-detect
POST /agent/replies/detect
POST /agent/wechat/test
POST /agent/wechat/search-debug
```

当前 `poll-and-execute` / `poll-and-detect` 已存在，并有对应回归测试。第一版产品化应保持：

1. 9000 主服务不直接操作客户微信。
2. 19000 只监听 `127.0.0.1`。
3. `poll-and-execute` 只处理通知任务。
4. `poll-and-detect` 只处理检测任务。
5. 发送和检测互斥。
6. 检测任务不得粘贴、不得发送、不得按 Enter。
7. `sent` 仍必须保持 `false`，除非后续用户明确批准产品化放开发送。

## 2. 冲突清单

### 2.1 Webhook 生产验签冲突

PRD 要求生产 webhook 必须按 OpenApi 签名规则验签。当前默认：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

且 `.env.example` 也给出 false 示例。当前代码没有生产环境保护，存在生产误关验签风险。

### 2.2 有效线索生成规则冲突

PRD 要求：

```text
从用户私信纯文本中提取手机号 / 微信号
手机号或微信号任一存在才进入有效线索
无联系方式只记录原始事件
invalid 进入前端列表和导出，但不参与分配、不回调
```

当前代码：

```text
im_receive_msg -> upsert_lead_from_webhook() -> douyin_leads
```

当前缺少联系方式提取门槛，可能把所有 `im_receive_msg` 当作线索。

### 2.3 原始事件表名与字段冲突

PRD 目标域：

```text
lead_source_events
```

当前物理表：

```text
douyin_webhook_events
```

当前字段不足以保存验签状态、消息文本、联系方式提取状态、`server_message_id`、`conversation_short_id`、`external_lead_id`、`process_status` 等目标字段。

### 2.4 多商户数据边界冲突

PRD 要求所有核心域预留：

```text
customer_id
external_customer_id
```

当前主要业务表没有统一 `customer_id`。这会影响 webhook secret 维度、销售列表、分配轮询、任务队列、导出、状态回调和 NewCarProject 接入。

### 2.5 状态集冲突

PRD 内部状态：

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

当前 demo 状态主要是：

```text
pending
assigned
replied
timeout
closed
```

任务状态还包含：

```text
pending
running
pasted
failed
blocked
cancelled
completed
```

需要产品化状态映射层，不能把任务状态、线索状态、回调状态混用。

### 2.6 invalid 线索展示与导出冲突

PRD 要求 invalid 进入前端列表和 Excel 导出，但不参与分配、不回调。当前代码没有清晰 invalid 线索创建 / 展示 / 导出链路，`list_leads()` 也没有分页。

### 2.7 数据库迁移冲突

当前依赖 `create_all`，没有 Alembic。新增字段 / 新增表如果只修改 ORM，对已有 SQLite 数据库不会自动生效。后续代码执行前必须确认迁移策略、备份策略和数据清洗策略。

### 2.8 Local Agent 产品化边界冲突

当前已有大量 debug / 验收安全逻辑，部分历史测试和模块会生成调试截图路径或临时截图文件。PRD 产品化数据规则要求：

```text
截图不保存
截图不入库
```

后续需要区分“历史调试工具”与“第一版生产业务链路”，不能把调试截图写入业务表或导出。

### 2.9 douyinAPI 依赖冲突

当前仍有：

```text
POST /integrations/douyin/sync-leads
app/integrations/douyin_api_client.py
```

它从 douyinAPI 拉取线索。PRD 已冻结 douyinAPI 只是 demo / 参考实现 / 历史代码沉淀，不能作为长期正式生产依赖。该旧链路只能保留为开发 / 兼容路径，并需要可关闭策略。

## 3. 推荐代码改造阶段

### 阶段 A：Webhook 验签生产安全改造

目标：

1. 保留开发 / 联调免验签能力。
2. 生产环境强制验签。
3. 不破坏 `/webhook/douyin` 与 `/integrations/douyin/webhook` 的共用处理。
4. 复用当前 `verify_signature()`，不复制 douyinAPI 代码。

计划：

1. 在 `app/config.py` 增加环境识别配置，例如 `APP_ENV` 或 `DEPLOY_ENV`，但具体命名需先确认。
2. 增加生产配置校验函数，明确生产环境不得 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`。
3. 生产环境缺少 `DY_SECRET_KEY` 时拒绝启动或拒绝请求，具体策略需确认。
4. `app/routers/integrations.py` 保持两个入口共用 `_handle_douyin_webhook()`。
5. 在启动日志和 webhook 请求日志中记录验签开启状态、入口路径、request_id，但不打印 `SECRET_KEY`。
6. `Authorization` 只允许脱敏或 hash 后记录。
7. 保持原始 `body` 参与签名，禁止 JSON 重序列化后验签。

涉及文件：

```text
app/config.py
app/main.py
app/routers/integrations.py
app/integrations/douyin_webhook.py
tests/test_douyin_webhook.py
```

风险：

1. 生产真实回调如果暂时不带签名，会出现 401。
2. SECRET_KEY 配错会导致全量 webhook 拒收。
3. 环境变量命名不统一会造成误判。

本阶段执行前必须由用户确认生产环境验签切换窗口和回滚方案。

### 阶段 B：Webhook 原始事件与幂等补强

目标：

1. 第一版保留 `douyin_webhook_events` 物理表名。
2. 语义上承接 `lead_source_events`。
3. 补齐原始事件、验签状态、解析状态、幂等命中结果。
4. 重复事件返回 200，不重复创建线索。

计划：

1. 确认采用数据模型文档推荐策略 A / C：保留旧表名，语义升级。
2. 为 `douyin_webhook_events` 设计字段补充迁移：`customer_id`、`source_platform`、`external_event_id`、`external_lead_id`、`server_message_id`、`conversation_short_id`、`message_text`、`lead_action`、`signature_valid`、`auth_required`、`auth_passed`、`auth_error`、`timestamp_header`、`signature_checked_at`、`process_status`、`error_message` 等。
3. 如果短期不做物理字段新增，可先把新增结构写入 `raw_body` 中的标准子对象，但这只能作为过渡，不作为长期目标。
4. 补充 `event_key` 生成规则中的字段空值策略，避免不同空字段事件误合并。
5. 重复事件当前直接返回既有 event，不新插 duplicate 记录；后续如要记录重复命中，需要新增独立日志字段或 duplicate event 记录策略。

涉及文件：

```text
app/models.py
app/integrations/douyin_webhook.py
app/routers/integrations.py
tests/test_douyin_webhook.py
```

数据库注意：

当前没有 Alembic。新增字段前必须先确认迁移方式，不能只改 ORM。

### 阶段 C：联系方式提取服务

目标：

1. 从用户私信纯文本提取手机号 / 微信号。
2. 不依赖顶层 `phone` / `wechat`。
3. 不依赖 `retain_consult_card`。
4. 不接入 LLM。
5. 多联系方式全部保存，主字段取第一个。

建议新增文件：

```text
app/services/contact_extractor.py
```

建议输出结构：

```text
raw_message_text
extracted_phone
extracted_wechat
all_extracted_contacts
contact_extract_status
contact_extract_reason
```

规则：

```text
手机号：中国大陆 11 位手机号
微信号：识别 “微信 / wx / vx / v / 加我” 后面的账号
```

测试重点：

1. 纯手机号。
2. `微信 xxx`。
3. `wx xxx`。
4. `vx xxx`。
5. `v xxx` 的误识别控制。
6. `加我 xxx`。
7. 多手机号 / 多微信号。
8. 空文本。
9. 非法 JSON / 非文本 content。
10. 联系方式和模板文本混在一起。

风险：

正则可能误识别短英文、车牌、订单号。第一版必须保留 `contact_extract_reason`，并允许后续人工处理。

### 阶段 D：有效线索生成规则改造

目标：

1. 只有提取到手机号或微信号才创建 / 更新有效线索。
2. 无联系方式事件只记录原始事件。
3. invalid 进入前端列表和导出。
4. invalid 不参与分配、不回调。
5. 同一 `open_id + account_open_id` 更新原线索。

计划：

1. 调整 `process_webhook_event()`，先解析消息文本并调用联系方式提取，再决定 `lead_action`。
2. 修改 `upsert_lead_from_webhook()` 或拆分为更清晰的 `build_lead_from_event()` / `upsert_valid_lead()`。
3. `phone` / `wechat` 来源改为提取结果。当前表无 `phone` / `wechat` 字段，可短期映射到 `customer_contact`，但产品化应新增目标字段。
4. `content` 可继续保存展示文本，但必须新增或兼容保存 `raw_message_text`。
5. 未提取到联系方式时，不自动进入分配；是否创建 `douyin_leads.status=invalid` 需要与“所有 invalid 进入前端列表”规则对齐。
6. 当前 `find_lead_by_source_id()` 只按 `from_user_id` 查找，需要迁移到 `customer_id + dedupe_key` 或 `customer_id + open_id + account_open_id`。

涉及文件：

```text
app/integrations/douyin_webhook.py
app/services/contact_extractor.py
app/services/lead_service.py
app/models.py
app/schemas.py
tests/test_douyin_webhook.py
```

### 阶段 E：状态流转补强

目标状态集：

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

计划：

1. 新增状态常量模块，例如 `app/services/lead_status.py` 或 `app/core/status.py`。
2. 避免把 `wechat_tasks.status`、`reply_checks.check_status` 与 `douyin_leads.status` 混用。
3. `pending` 逐步迁移为 `pending_assign`，但需要兼容旧数据。
4. 非工作时间进入 `delay_assign`。
5. 人工关闭进入 `closed`，第一版不允许恢复。
6. `manual_required` 用于超过重分配次数、Agent 安全门禁失败、无法确认联系人等需要人工处理的场景。
7. 对外状态映射保持只有：

```text
未分配
已分配
已回复
超时未回复
```

不回调状态：

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

涉及文件：

```text
app/models.py
app/schemas.py
app/services/lead_service.py
app/services/assign_service.py
app/services/wechat_task_service.py
app/services/reply_checker.py
app/services/report_service.py
app/routers/leads.py
app/routers/reports.py
```

### 阶段 F：customer_id / external_customer_id 预留

目标：

1. auto_wechat 本地生成 `customer_id`。
2. NewCarProject 商户 ID 保存为 `external_customer_id`。
3. 当前 NewCarProject token / cookie / roles / merchant_id 字段结构未确认，先做预留。
4. 不破坏当前单客户 demo。

计划：

1. 新增 `customers` 表或等价客户表。
2. 当前单客户环境生成默认客户记录，例如 `default`，但具体 ID 格式需确认。
3. 给核心业务表补 `customer_id` 字段，并对旧数据回填默认客户。
4. `DY_SECRET_KEY` 从全局配置逐步迁移为客户维度配置；迁移期可保留全局 fallback，但生产多客户不得长期依赖全局密钥。
5. `sales_staff` 按 `customer_id + wechat_nickname` 唯一。
6. 所有列表、分配、任务、导出、回调查询必须带客户边界。

涉及文件：

```text
app/models.py
app/schemas.py
app/config.py
app/services/staff_service.py
app/services/lead_service.py
app/services/assign_service.py
app/services/wechat_task_service.py
app/routers/staff.py
app/routers/leads.py
```

用户确认项：

```text
NewCarProject token / cookie / roles / merchant_id 的具体字段结构
默认 customer_id 命名和回填策略
是否新增 customers 表及迁移方式
```

### 阶段 G：Local Agent 与任务链路回归

目标：

1. 保持现有 Local Agent 可用。
2. 不破坏 `poll-and-execute`。
3. 不破坏 `poll-and-detect`。
4. 保持发送和检测互斥。
5. 失败必须回写。

计划：

1. 保留 19000 只监听 `127.0.0.1`。
2. 保留 `poll-and-execute` 只领取 `notify_sales`。
3. 保留 `poll-and-detect` 只领取 `detect_reply`。
4. 补齐 9000 侧 `/agent/heartbeat`、`/agent/status` 时，必须确保只是服务端状态接口，不让 9000 操作微信。
5. 为 `agent_client_id`、任务互斥锁、忙碌返回 `agent_busy` 设计落库字段或内存兼容策略。
6. 现有 `sent=true` 拒绝逻辑必须保留，除非用户后续明确批准真实发送产品化。
7. 检测任务不得调用粘贴、发送、Enter。
8. 截图调试工具不得进入第一版业务数据保存和导出。

涉及文件：

```text
app/local_agent_main.py
app/routers/wechat_tasks.py
app/services/wechat_task_service.py
app/models.py
app/schemas.py
tests/test_p0_main_5b_poll_and_execute.py
tests/test_p1_auto_1c_poll_and_detect.py
tests/test_p1_auto_1d_fix4_safe_json.py
```

### 阶段 H：前端接口与导出补齐

目标：

1. 前端能查看线索、状态、提取结果、任务、回复、超时、失败。
2. 支持 Excel 导出。
3. invalid 进入列表和导出。
4. 第一版导出不脱敏。

计划：

1. `GET /leads` 增加分页、时间范围、状态、客户边界过滤。
2. `GET /reports/summary` 从 demo 汇总升级为产品化汇总。
3. 新增导出接口前，先输出接口实现方案并确认文件保存路径和清理策略。
4. 导出任务建议落 `export_tasks`，但本计划阶段不执行建表。
5. invalid 线索必须包含提取失败原因。
6. 对前端展示的状态使用对外状态映射，不直接暴露所有内部状态，除非后台运维视图需要。

涉及文件：

```text
app/routers/leads.py
app/routers/reports.py
app/services/report_service.py
app/schemas.py
app/models.py
```

## 4. 文件级修改范围

### app/config.py

计划：新增环境识别、生产验签强制校验、客户维度 SECRET_KEY 迁移预留。  
风险：错误环境识别会导致生产拒收 webhook 或开发无法联调。  
测试：配置矩阵测试覆盖开发关闭验签、生产关闭验签、生产缺密钥、生产正确密钥。  
是否必须本阶段修改：阶段 A 必须。

### .env.example

计划：后续代码阶段需要调整示例和注释，明确 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 仅限开发 / 联调，生产必须 true。  
风险：示例改动可能影响现有联调人员理解。  
测试：人工审查配置说明。  
是否必须本阶段修改：阶段 A 需要，但本轮不修改。

### app/integrations/douyin_webhook.py

计划：保留 `verify_signature()` 算法；补强事件解析、联系方式提取调用、有效线索判断、幂等字段解析、原始事件保存。  
风险：这是 webhook 主链路，高风险。  
测试：`tests/test_douyin_webhook.py` 扩展覆盖签名、重复、无联系方式、多个联系方式、非线索事件。  
是否必须本阶段修改：阶段 A/B/C/D 必须。

### app/routers/integrations.py

计划：保持两个 webhook 入口共用 `_handle_douyin_webhook()`；补日志、request_id、验签状态传递、错误响应一致性。  
风险：两个路径行为不一致会造成线上难排查。  
测试：两个路径同 payload 行为一致测试。  
是否必须本阶段修改：阶段 A/B 必须。

### app/services/contact_extractor.py

计划：新增联系方式提取服务，封装手机号 / 微信号规则和结果结构。  
风险：误识别影响线索有效性。  
测试：独立单元测试覆盖正例、反例、多联系方式、空文本。  
是否必须本阶段修改：阶段 C 必须。

### app/services/lead_service.py

计划：增加产品化线索状态更新、查询分页、invalid 处理、客户边界过滤。  
风险：影响 `/leads` 列表和分配入口。  
测试：线索列表、状态过滤、invalid 展示、分页。  
是否必须本阶段修改：阶段 D/E/H 必须。

### app/services/assign_service.py

计划：从简单最少数量分配升级为按客户销售列表顺序轮流分配；补 `delay_assign`、重分配次数、排除原销售。  
风险：分配公平性和旧数据兼容。  
测试：无销售、单销售、多销售、非工作时间、重分配排除原销售、最多 5 次。  
是否必须本阶段修改：阶段 E/F 后再改。

### app/services/staff_service.py

当前未发现独立 `staff_service.py` 复杂实现，销售逻辑主要在 router / model。  
计划：如后续补齐 Excel 导入、排序、重复昵称覆盖，建议新增或扩展 `staff_service.py`，避免路由层堆业务。  
风险：导入覆盖规则影响现有销售数据。  
测试：模板、必填、部分成功、重复昵称覆盖、错误行号。  
是否必须本阶段修改：销售导入阶段必须。

### app/services/wechat_task_service.py

计划：保留现有安全门禁；补 `agent_client_id`、任务互斥、幂等回写、任务状态与线索状态映射。  
风险：破坏 Local Agent 真实链路。  
测试：现有 P0/P1 Local Agent 回归必须全跑。  
是否必须本阶段修改：阶段 G 必须。

### app/services/reply_checker.py

计划：把当前 timeout 扫描升级为客户维度、状态流转、超时重分配、人工处理入口前置。  
风险：误把有效线索置为 timeout。  
测试：未超时、已超时、已回复不超时、重分配次数上限。  
是否必须本阶段修改：阶段 E/G 必须。

### app/services/reply_analyzer.py

计划：保持第一版关键词 / 规则判断，不接入 LLM；增加客户配置关键词读取和提示约束。  
风险：关键词过宽导致误判已回复。  
测试：命中关键词、未命中、模板文本重复、过短关键词。  
是否必须本阶段修改：回复检测产品化阶段需要。

### app/models.py

计划：按数据模型文档补字段 / 新表，但必须配套迁移策略。  
风险：只改 ORM 不会更新已有 SQLite 表；字段默认值可能破坏旧查询。  
测试：迁移前后数据完整性、旧接口兼容。  
是否必须本阶段修改：阶段 B/D/F/G/H 分批需要。

### app/schemas.py

计划：补产品化响应字段、分页响应、联系方式提取字段、客户边界字段、任务状态字段。  
风险：前端字段兼容。  
测试：FastAPI response_model 校验和前端契约测试。  
是否必须本阶段修改：随接口阶段分批。

### app/database.py

计划：保留连接方式；如新增迁移体系，需要在文档确认后引入，不在业务改造里顺手加。  
风险：数据库初始化和迁移冲突。  
测试：空库初始化、旧库迁移。  
是否必须本阶段修改：除非确认迁移体系，否则不改。

### tests/test_douyin_webhook.py

计划：扩展为产品化 webhook 主测试矩阵。  
风险：旧测试默认免验签，需要按开发 / 生产环境拆分。  
测试：见第 6 节测试计划摘要。  
是否必须本阶段修改：阶段 A-D 必须。

### Local Agent 回归测试

必须保留并扩展：

```text
tests/test_p0_main_5b_poll_and_execute.py
tests/test_p1_auto_1c_poll_and_detect.py
tests/test_p1_auto_1d_fix4_safe_json.py
tests/test_p0_5a_wechat_tasks.py
```

计划：新增任务互斥、`agent_busy`、失败回写、`sent=true` 拒绝等测试。  
风险：真实微信链路无法完全自动化，需要保留 mock 与真机验收分层。  
是否必须本阶段修改：阶段 G 必须。

### docs

计划：后续每个代码阶段完成后同步更新 `docs/ai/05_PROJECT_CONTEXT.md` 和相关验收文档。  
风险：文档与代码再次漂移。  
测试：人工 checklist 审核。  
是否必须本阶段修改：每阶段完成后必须。

## 5. 数据库改动策略

当前事实：

```text
没有发现 Alembic
app/main.py 使用 Base.metadata.create_all(bind=engine)
SQLite 数据库位于 data/auto_wechat.db
```

必须遵守：

1. 本轮不修改数据库模型。
2. 后续代码执行前必须先确认迁移策略。
3. 不能只改 `app/models.py` 就认为已有库字段已补齐。
4. 生产 / 演示库迁移前必须备份 SQLite 文件。
5. 迁移前需要扫描旧数据是否存在重复 `event_key`、重复 `source_id`、空 `from_user_id` 等风险。

建议迁移路线：

1. 先做只追加字段的兼容迁移，不删除旧字段。
2. 第一版保留 `douyin_webhook_events` 表名，语义承接 `lead_source_events`。
3. `douyin_leads` 先补产品化字段，旧字段保留兼容前端和旧测试。
4. 新增 `customers` 后，为旧数据回填默认 `customer_id`。
5. 新增索引和唯一约束前先做数据清洗报告。
6. 稳定后再评估 Alembic 或独立 SQLite 迁移脚本。

可能需要新增字段：

```text
customer_id
external_customer_id
external_lead_id
dedupe_key
open_id
account_open_id
conversation_short_id
server_message_id
raw_message_text
extracted_phone
extracted_wechat
all_extracted_contacts
contact_extract_status
contact_extract_reason
agent_client_id
task_status / status 兼容字段
```

可能需要新增表：

```text
customers
douyin_accounts
lead_assignments
lead_timeouts
manual_actions
callback_logs
export_tasks
agent_clients
agent_task_runs
```

必须用户确认后才能执行：

1. 是否引入 Alembic。
2. 是否使用手写 SQLite 迁移脚本。
3. 默认 `customer_id` 值。
4. 是否在第一批迁移中新增全部表，还是按阶段逐步新增。
5. 是否立刻给 `douyin_webhook_events.event_key` 之外的字段加唯一约束。

## 6. 测试计划摘要

后续代码阶段至少覆盖以下测试矩阵：

1. Webhook 正确签名，返回 200。
2. Webhook 错误签名，返回 401。
3. Webhook 缺签名头，生产验签开启时返回 401。
4. timestamp 过期，返回 401。
5. 开发环境关闭验签，允许合法 payload 进入处理。
6. 生产环境关闭验签，被启动校验或请求校验拒绝。
7. 文本含中国大陆 11 位手机号，提取成功。
8. 文本含微信号关键词，提取成功。
9. 文本无联系方式，只记录原始事件，线索为 invalid 或不进入有效分配。
10. 多联系方式全部保存，主字段取第一个。
11. 重复事件返回 200，不重复创建线索。
12. `im_send_msg` 不生成有效线索。
13. 非工作时间进入 `delay_assign`。
14. `closed` 后不允许恢复。
15. Local Agent `poll-and-execute` 只领取通知任务。
16. Local Agent `poll-and-detect` 只领取检测任务。
17. Local Agent 失败必须回写 `failure_stage` / 原因。
18. 导出包含 invalid。
19. 旧路径 `/integrations/douyin/webhook` 兼容。
20. 正式路径 `/webhook/douyin` 正常。
21. `sent=true` 继续被拒绝。
22. 检测任务不粘贴、不发送、不按 Enter。
23. `customer_id` 过滤不串商户数据。
24. SECRET_KEY 缺失场景在生产不得静默放行。
25. 字段迁移后旧数据仍可列表展示。

建议分层：

```text
单元测试：联系方式提取、签名计算、状态映射
接口测试：webhook、leads、wechat-tasks、replies、reports
迁移测试：空库、旧库、重复数据
回归测试：Local Agent poll-and-execute / poll-and-detect
真机验收：只在明确阶段进行，不作为普通单元测试前提
```

## 7. 风险评估

### 7.1 验签开启导致线上回调全量 401

规避：先在 staging / 联调环境打开验签；生产切换前确认抖音侧签名头是否真实存在；准备回滚配置和观测日志。

### 7.2 SECRET_KEY 配置错误

规避：增加启动校验、脱敏日志、配置检查命令；切换前用固定 payload 生成签名做端到端验证。

### 7.3 原始 body 读取方式错误

规避：验签必须使用 `request.body()` 原始 bytes；测试中加入空格、字段顺序、中文字符 payload，证明不能重序列化。

### 7.4 联系方式误识别

规避：先独立服务 + 单元测试；微信号规则限制关键词上下文；保存提取原因；允许人工处理。

### 7.5 当前表结构不足导致数据无法保存

规避：先出迁移方案；过渡期可把扩展结构写入 JSON，但不能长期依赖 JSON 兜底。

### 7.6 没有 Alembic 导致迁移风险

规避：先备份 SQLite；写可重复执行的迁移脚本或正式引入 Alembic；迁移后校验表结构和行数。

### 7.7 customer_id 改造影响旧数据

规避：默认客户回填；查询层兼容空 customer_id；上线前跑数据清洗。

### 7.8 状态集扩展影响前端

规避：后端提供对外状态映射；前端先只消费四个对外状态；内部状态用于详情和运维。

### 7.9 Local Agent 真机链路回归风险

规避：先跑现有 mock 回归；真机只验证最小链路；保持 19000 localhost、任务互斥、`sent=false` 门禁。

### 7.10 两个 webhook 路径行为不一致

规避：共享 `_handle_douyin_webhook()` 不拆；所有测试同时覆盖两个路径。

### 7.11 douyinAPI 被误用为生产依赖

规避：旧同步链路加明确开关和文档标记；产品化链路以 webhook 直收为验收口径。

### 7.12 截图保存与 PRD 冲突

规避：第一版业务链路不保存截图、不入库；历史 debug 截图工具单独归档，不进入产品数据模型和导出。

### 7.13 日志模板直接复制风险

只读探索 `D:\zws\ask_next_Project\log-template` 后确认，该模板只有 `logging_config.py` 和 `logging_config.py 使用说明.md` 两个文件，提供标准库 logging 初始化、彩色控制台输出、按天轮转文件、ERROR 单独文件、模块级 logger 缓存和 `LOG_LEVEL` 环境变量读取。

该模板适合后续作为基础日志配置参考，但不适合未经适配直接复制到 auto_wechat，原因：

1. 当前格式为纯文本：`时间 - logger 名称 - level - filename:lineno - message`，尚不包含 `request_id`、`trace_id`、`customer_id`、`lead_id`、`task_id`、`agent_client_id`、`source_path`、`failure_stage` 等 auto_wechat 诊断字段。
2. 当前没有 request / trace 上下文传播机制，没有 `contextvars`、FastAPI middleware 或响应头回传设计。
3. 当前没有敏感信息脱敏过滤器，不能直接用于 webhook、token、cookie、手机号、微信号、Authorization、SECRET_KEY 等场景。
4. 当前异常日志依赖调用方使用 `logger.exception()` / `exc_info=True`，模板本身没有全局异常处理或 FastAPI exception handler 接入。
5. 当前通过 `python-dotenv` 读取 `.env`，auto_wechat 后续若复用必须先确认项目已有依赖和配置加载方式，不能为日志小补丁单独引入新依赖。
6. 当前日志目录固定推导为模板文件上级目录的 `log/`，迁入 auto_wechat 前必须确认主服务、Local Agent exe、Windows 客户端运行目录和日志落盘目录。
7. 当前日志轮转为午夜轮转、保留 7 天；第一版业务数据保留 180 天，但运行日志保留周期需单独确认，不能混同业务数据保留策略。

P0-CODEPLAN-1A 只补充日志要求和执行前决策，不复制日志代码、不修改业务代码、不改配置默认值、不引入依赖。

## 8. 推荐实施顺序

推荐顺序：

```text
1. Webhook 验签生产安全改造
2. 日志基础设施适配设计
3. 联系方式提取 service + 单元测试
4. webhook 原始事件与有效线索生成规则改造
5. douyin_leads 字段兼容 / 数据模型补齐
6. 状态流转补强
7. customer_id / external_customer_id 预留
8. Local Agent 回归与任务幂等补强
9. 前端接口和导出补齐
10. 全链路测试
```

原因：

1. 验签是入口安全，必须先解决生产默认值风险。
2. 日志基础设施应在入口安全改造后、核心业务改造前明确，否则后续 webhook、线索、任务、Local Agent 问题仍难以远程诊断。
3. 联系方式提取是有效线索判断前置条件。
4. 原始事件和有效线索规则改造会影响后续分配、任务、导出。
5. 数据库字段和 `customer_id` 是接口与多商户隔离的基础。
6. Local Agent 已有真实链路风险，应该在核心数据规则稳定后集中回归。
7. 导出和前端补齐放在数据字段稳定之后。

### 8.1 日志基础设施适配要求

后续正式执行日志改造前，至少需要满足以下要求：

1. 初始化方式：在 FastAPI 主服务入口和 Local Agent 入口分别只初始化一次，禁止重复添加 handler；保留已有 logger 行为，避免第三方库日志被误放大。
2. 日志格式：基础字段至少包含时间、级别、logger 名称、文件名、行号、消息；业务诊断字段通过结构化 extra 或统一格式补充，包含 `request_id`、`trace_id`、`customer_id`、`lead_id`、`task_id`、`agent_client_id`、`source_path`、`stage`、`failure_stage`。
3. 日志分级：`DEBUG` 用于本地调试，`INFO` 用于关键业务阶段，`WARNING` 用于可恢复异常，`ERROR` 用于业务失败或外部依赖失败，`CRITICAL` 只用于服务不可用级别问题。
4. 日志轮转：可以参考模板的 `TimedRotatingFileHandler` 按天轮转和错误日志单独落盘，但保留天数、目录、exe 环境写权限必须执行前确认。
5. request_id / trace_id：FastAPI 入口必须生成或透传 request_id，写入响应头和日志上下文；Local Agent 调用主服务时应透传 task_id / request_id，形成跨进程排查链路。
6. 异常日志：webhook、任务执行、回复检测、导出、Local Agent 自动化失败必须使用带堆栈的异常日志，并保留结构化失败原因，禁止只记录“失败了”。
7. 敏感信息脱敏：必须统一脱敏 Authorization、cookie、token、SECRET_KEY、手机号、微信号、open_id、server_message_id、原始 body 中的联系方式；SECRET_KEY 禁止打印，Authorization 只能 hash 或局部掩码。
8. FastAPI 接入：需要单独设计 middleware / exception handler / request state 或 contextvars，不能只在入口调用 `setup_logging()`。
9. 依赖约束：不得因为日志模板引入新依赖；如使用 `python-dotenv`，必须确认项目已有依赖和配置加载边界。
10. 兼容约束：日志改造不得改变接口响应、数据库模型、配置默认值、业务状态流转和任务执行门禁。

## 9. 需要用户确认后才能执行的事项

1. 生产环境是否已经具备 `Authorization` 和 `X-Auth-Timestamp` 签名头。
2. 生产验签切换时间窗口和失败回滚策略。
3. 环境变量命名采用 `APP_ENV`、`ENV` 还是 `DEPLOY_ENV`。
4. 生产环境缺少 `DY_SECRET_KEY` 时采用启动失败还是请求拒绝。
5. 是否引入 Alembic，还是先使用手写 SQLite 迁移脚本。
6. 默认 `customer_id` 值和旧数据回填策略。
7. NewCarProject token / cookie / roles / merchant_id 字段结构。
8. invalid 线索在物理上是否进入 `douyin_leads.status=invalid`，还是只在原始事件列表中展示。
9. 是否第一版就新增 `customers`、`callback_logs`、`export_tasks` 等全部目标表。
10. 是否继续保留 `/integrations/douyin/sync-leads` 旧 douyinAPI 同步入口，以及是否增加关闭开关。
11. 第一版是否继续保持 `sent=false`，只粘贴不发送；如要真实发送，需要单独安全评审。
12. 历史 debug 截图文件是否需要单独清理 / 归档计划。
13. 日志目录采用项目根目录 `log/`、实例目录、还是 Windows 用户数据目录；Local Agent exe 是否与主服务分开落盘。
14. 运行日志保留周期采用 7 天、30 天还是按客户要求另定；错误日志是否单独保留更久。
15. request_id / trace_id 字段名、生成规则、响应头名称，以及是否兼容上游传入的 `X-Request-ID`。
16. 手机号、微信号、open_id、server_message_id 的脱敏规则和允许排查人员范围。
17. 是否采用纯文本日志、JSON Lines 结构化日志，还是第一版先纯文本加固定 key-value 字段。
18. FastAPI 全局异常处理是否纳入第一轮日志改造，还是先只做 webhook / Local Agent 关键链路日志。

## 10. 本轮只读探索记录 / 未修改说明

本轮只读查看了以下范围：

```text
app/main.py
app/config.py
.env.example
app/models.py
app/schemas.py
app/database.py
app/routers/
app/services/
app/integrations/
tests/
```

重点确认了：

1. 两个 webhook 入口共用 `_handle_douyin_webhook()`。
2. `verify_signature()` 位于 `app/integrations/douyin_webhook.py`。
3. `DOUYIN_WEBHOOK_AUTH_REQUIRED` 和 `DY_SECRET_KEY` 位于 `app/config.py`。
4. 当前原始事件写入 `douyin_webhook_events`。
5. 当前 `im_receive_msg` 会直接 upsert `douyin_leads`。
6. 当前未发现产品化联系方式提取服务。
7. 当前主要业务表未统一 `customer_id`。
8. 当前数据库依赖 `Base.metadata.create_all(bind=engine)`，未发现 Alembic。
9. 当前 Local Agent / WechatTask 已有若干安全门禁和回归测试，后续不能放宽。

本轮没有修改：

```text
业务代码
数据库模型
接口实现
测试代码
依赖
配置默认值
.env.example
```

本轮没有启动服务，没有执行数据库迁移。

### 10.1 P0-CODEPLAN-1A log-template 只读探索记录

只读探索路径：

```text
D:\zws\ask_next_Project\log-template
```

目录结构：

```text
log-template/
├── logging_config.py
└── logging_config.py 使用说明.md
```

能力摘要：

1. 初始化方式：入口调用 `setup_logging()`，根 logger 无 handler 时添加控制台、常规文件、错误文件 handler；`get_module_logger()` 可按模块名获取缓存 logger。
2. 日志格式：`%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s`，日期格式为 `%Y-%m-%d %H:%M:%S`。
3. 日志分级：支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`，默认 `INFO`，通过 `LOG_LEVEL` 环境变量控制。
4. 日志轮转：`TimedRotatingFileHandler` 每天午夜轮转，默认保留 7 天；常规日志写入 `app.log`，错误日志写入 `app_error.log`。
5. request_id / trace_id：模板未提供内置支持。
6. 异常日志：模板只提供 logger 配置，异常堆栈需要调用方使用 `logger.exception()` 或 `exc_info=True`。
7. 敏感信息脱敏：模板未提供脱敏 filter 或 formatter。
8. FastAPI 接入方式：说明文档给出 Flask 示例，提到 Flask/FastAPI 场景可在入口初始化，但未提供 FastAPI middleware、exception handler、request state 或 contextvars 实现。

适配判断：适合作为 auto_wechat 后续日志基础设施参考，不适合直接复制。后续应先设计 request_id / trace_id、脱敏、异常处理、FastAPI middleware、Local Agent exe 日志目录和轮转策略，再做代码迁移。
