# auto_wechat / 小高AI微信助手 第一版产品化架构设计

版本：P0-ARCH-1
依据：`docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md`
范围：架构设计与 Webhook 验签迁移说明。本文不修改业务代码、不定义最终数据库模型、不新增接口契约、不作为迁移脚本。

------

## 1. 架构总览

第一版产品化架构以 NewCarProject 为商户与权限入口，以外部客户系统 / React 商户端为商户使用入口，以多个独立子功能系统承载可售卖能力。

```text
NewCarProject
  ↓
外部客户系统 / React 商户端
  ↓
多个独立子功能系统
  ├─ AI小高线索
  ├─ 小高AI微信助手 / auto_wechat
  ├─ AI小高剪辑
  └─ 其他子功能
```

边界结论：

1. NewCarProject 管商户、账号、权限、菜单、套餐、消耗。
2. AI小高线索负责抖音扫码鉴权、私信获取、联系方式提取、有效线索生成。
3. 小高AI微信助手负责销售分配、微信通知、回复检测、超时处理、人工处理、Excel 导出。
4. AI小高剪辑负责剪辑相关能力，巨量一键过审归 AI小高剪辑，不进入 auto_wechat 第一版。
5. douyinAPI 只是 demo / 参考实现 / 历史代码沉淀，不作为正式生产依赖。

当前代码现状需要单独标记：当前仓库中 `app/routers/integrations.py` 已同时承担旧 douyinAPI 同步和 webhook 直收入口；`app/integrations/douyin_webhook.py` 已有验签、事件幂等、线索写入基础能力；`app/models.py` 当前表名为 `douyin_webhook_events`，PRD 目标域名为 `lead_source_events`。后续数据模型设计需决定是迁移命名、兼容旧表，还是新建目标表。

------

## 2. 服务边界设计

### 2.1 AI小高线索服务

AI小高线索是独立子功能服务，不是小高AI微信助手的内部页面。

职责：

1. 抖音扫码鉴权。
2. 保存授权状态。
3. 接收 / 获取抖音私信事件。
4. webhook 验签。
5. 原始事件记录。
6. 私信纯文本解析。
7. 手机号 / 微信号提取。
8. 有效线索生成。
9. 向小高AI微信助手提供有效线索。

第一版设计上应把“线索来源处理”与“微信助手业务执行”隔离。当前仓库可渐进承接 webhook 直收，但后续产品化拆分时，AI小高线索应拥有独立配置、独立健康检查和独立异常处理能力。

### 2.2 小高AI微信助手服务

小高AI微信助手 / auto_wechat 是线索消费与微信执行编排服务。

职责：

1. 获取有效线索。
2. 管理销售。
3. 分配线索。
4. 创建微信通知任务。
5. 管理 Local Agent 任务。
6. 检测销售回复。
7. 超时重分配。
8. 人工处理。
9. Excel 导出。

当前代码现状中，`app/main.py` 注册 `staff`、`leads`、`checks`、`reports`、`integrations`、`wechat_tasks` 等路由；`app/services/wechat_task_service.py` 已承担 `notify_sales` / `detect_reply` 任务创建与回写联动；`app/local_agent_main.py` 作为 19000 本地执行端。

### 2.3 Local Agent

Local Agent 是客户电脑本地执行端，exe 名称统一为：

```text
小高AI微信助手
```

职责：

1. 连接 auto_wechat 服务。
2. 心跳。
3. 拉取微信通知任务。
4. 拉取回复检测任务。
5. 操作本机微信。
6. 回写执行结果。

限制：

1. 同一微信窗口同一时间只允许一个任务。
2. 发送和检测互斥。
3. 不支持多 Local Agent。
4. 不支持多个账号。
5. 不允许未确认联系人发送。
6. 不允许搜索框焦点未确认时粘贴。
7. 不允许微信窗口不可用时继续操作。

当前代码现状中，`app/local_agent_main.py` 使用 `_wechat_task_lock` 保证本地微信任务互斥；`poll-and-execute` 和 `poll-and-detect` 按 `task_id` 指定执行；检测链路要求只读，不粘贴、不发送、不按 Enter。

------

## 3. 服务拆分与隔离设计

架构原则：

1. AI小高线索与小高AI微信助手逻辑边界独立。
2. 第一版可以按当前仓库现实做渐进式拆分，但设计上必须预留独立部署。
3. 服务地址、端口、健康检查地址必须可配置。
4. 一个服务异常不能影响另一个服务已有任务继续运行。
5. AI小高线索故障时，小高AI微信助手仍可处理已获取线索和已创建任务。
6. 小高AI微信助手故障时，AI小高线索仍可继续接收 / 保存线索。
7. 第一版不设计智能路由。
8. 后续服务器不够时，可以把服务迁移到不同服务器。

建议的逻辑拆分：

```text
AI小高线索服务
  - auth: 抖音扫码鉴权与授权状态
  - webhook: 验签、原始事件、文本解析、联系方式提取
  - leads: 有效线索生成与对外提供

小高AI微信助手服务
  - sales: 销售管理
  - assignment: 销售分配与重分配
  - tasks: 微信通知任务与检测任务
  - agent: Local Agent 心跳、拉取、回写
  - reply: 回复检测、超时、人工处理
  - export: Excel 导出
```

第一版通信边界：

1. 服务之间通过 HTTP API 或明确接口通信，禁止数据库直读和 SQLite 文件共享。
2. 服务地址从配置读取，不允许写死。
3. 健康检查地址必须在接口契约阶段明确。
4. AI小高线索写入原始事件失败时，应返回明确失败并记录日志；不应影响小高AI微信助手处理历史线索。
5. 小高AI微信助手不可用时，AI小高线索应保留事件和有效线索，等待后续补偿或拉取。

------

## 4. Webhook 数据流设计

第一版正式验收链路为 webhook 直收：

```text
抖音 / 火山服务
  ↓ callback.misanduo.com/webhook/douyin
Webhook 接收层
  ↓ 验签
原始事件入库 lead_source_events
  ↓ 解析 content
提取 message_text
  ↓ 正则 / 规则提取手机号、微信号
有效线索判断
  ↓
douyin_leads
  ↓
销售分配
  ↓
wechat_tasks
  ↓
Local Agent
  ↓
微信通知销售
  ↓
回复检测
  ↓
状态更新
```

数据流分层：

1. 接收层：保留原始请求体，用于验签和原始事件保存。
2. 安全层：基于 `Authorization` 和 `X-Auth-Timestamp` 做签名校验和过期校验。
3. 事件层：所有合法事件写入原始事件域，重复事件也要可追踪幂等命中。
4. 提取层：从用户私信纯文本中提取 `message_text`、手机号、微信号。
5. 线索层：手机号或微信号任一存在即创建 / 更新有效线索；无联系方式进入 invalid 或仅保留原始事件。
6. 分配层：按客户销售列表顺序轮流分配，非工作时间进入 `delay_assign`。
7. 任务层：分配后创建微信通知任务，Local Agent 串行拉取并执行。
8. 检测层：销售回复检测采用关键词 / 规则判断，不接入 LLM。
9. 状态层：内部状态转为对外状态，必要时后续回调状态同步。

当前实现差距：

1. 当前模型存在 `DouyinWebhookEvent` / `douyin_webhook_events`，PRD 目标为 `lead_source_events`。
2. 当前 `process_webhook_event` 对 `im_receive_msg` 会直接 upsert 到 `DouyinLead`，尚未按 PRD 完成手机号 / 微信号提取后再判定有效线索。
3. 当前 `DouyinLead.status` 仍使用 `pending/assigned/replied/timeout/closed` 等旧状态，未覆盖 PRD 状态全集。
4. 当前 Local Agent 调试端点与业务任务均使用请求或任务携带的非空联系人昵称；取消 `Aw3` 硬编码后，搜索焦点、搜索文字、联系人验证和前台焦点仍是强制安全门禁。

------

## 5. Webhook 验签架构

PRD 冻结签名规则：

```text
signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

Header：

```text
Authorization: signature
X-Auth-Timestamp: timestamp
```

设计要求：

1. `body` 必须使用原始请求体，不能使用 JSON 重新序列化后的内容。
2. `timestamp` 为秒级时间戳。
3. `SECRET_KEY` 第一版按客户 / 商户维度配置。
4. 后续如每个抖音账号不同，再扩展到账号维度。
5. 需要 timestamp 过期窗口。
6. 签名失败返回 401。
7. 请求过期返回 401。
8. 参数错误返回 400。
9. 系统异常返回 500。
10. 成功、重复、非线索、无效线索均返回 200。

当前代码现状：

1. `app/routers/integrations.py` 使用 `await request.body()` 获取原始 body，符合原始请求体验签要求。
2. `app/integrations/douyin_webhook.py::verify_signature()` 已按 `DY_SECRET_KEY + body + "-" + timestamp` 计算 SHA256。
3. 当前 `DY_SECRET_KEY` 从环境变量读取，尚不是客户 / 商户维度配置。
4. 当前 `DY_ALLOWED_DRIFT_SECONDS` 已作为 timestamp 过期窗口配置。
5. 当前未配置 `DY_SECRET_KEY` 时，`verify_signature()` 返回 500 风格错误；架构目标中生产环境应在启动或请求入口明确拒绝并记录配置错误，不得静默放行。

------

## 6. Webhook 验签迁移 / 兼容说明

旧实现 / 旧上下文曾记录：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

新 PRD 冻结为：

```text
Webhook 必须按 OpenApi 签名规则验签。
```

迁移策略：

1. 开发环境可以通过配置关闭验签，便于本地调试。
2. 生产环境必须开启验签。
3. 配置项必须明确区分环境，不允许生产默认关闭。
4. 日志必须记录验签开启状态。
5. 未配置 `SECRET_KEY` 时，生产环境不得静默放行。
6. 旧的免验签链路只能作为开发 / 联调兼容，不作为正式验收口径。
7. 后续技术方案必须明确如何从旧默认值迁移到新默认值。
8. 测试计划必须覆盖验签开启、验签关闭、签名错误、timestamp 过期、`SECRET_KEY` 缺失等场景。

建议的目标配置语义：

```text
APP_ENV=development | staging | production
DOUYIN_WEBHOOK_AUTH_REQUIRED=true | false
DY_SECRET_KEY=...
DY_ALLOWED_DRIFT_SECONDS=300
```

规则：

1. `APP_ENV=production` 时，`DOUYIN_WEBHOOK_AUTH_REQUIRED` 必须为 `true`。
2. `APP_ENV=production` 且 `DY_SECRET_KEY` 为空时，webhook 接收层必须拒绝请求并输出高优先级日志。
3. `APP_ENV=development` 时允许关闭验签，但日志必须打印 `webhook_auth_required=false` 和 `source_path`。
4. 迁移阶段可以保留 `/webhook/douyin` 与 `/integrations/douyin/webhook` 双入口，但行为必须一致。
5. 正式验收只认可 `callback.misanduo.com/webhook/douyin` 加验签成功链路。

迁移步骤建议：

1. 技术方案阶段先补充环境区分与配置校验方案。
2. 测试环境开启验签，使用固定 `DY_SECRET_KEY` 和真实原始 body 生成签名。
3. 与外部平台确认生产推送是否携带签名头；如果现网尚未携带，需要先完成平台侧配置。
4. 生产发布前将 `.env` 显式设置为验签开启。
5. 发布后观察签名失败、过期请求、重复事件、成功事件日志。

------

## 7. 联系方式提取架构

设计前提：

1. 用户留下资料时，联系方式通常在用户发出的私信纯文本中。
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

需要保存：

```text
raw_message_text
extracted_phone
extracted_wechat
all_extracted_contacts
contact_extract_status
contact_extract_reason
```

架构分层：

1. `message_text` 归一化：只从用户发出的私信纯文本提取。
2. 手机号提取：识别中国大陆 11 位手机号。
3. 微信号提取：识别指定关键词后的账号。
4. 提取结果归档：保存原始文本、主字段、全量联系方式、提取状态和失败原因。
5. 有效性判定：手机号或微信号任一存在即进入有效线索。
6. invalid 处理：无联系方式事件记录原因，进入前端列表与导出，不进入分配，不回调。

当前代码差距：

1. `normalize_message_text()` 已可从 content 中取文本。
2. 当前 webhook upsert 未做 PRD 要求的正则 / 规则联系方式提取。
3. 当前 `DouyinLead.customer_contact` 是单字段，后续数据模型需要补足提取结果域。

------

## 8. 状态流转架构

内部状态必须覆盖：

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

对外状态只包括：

```text
未分配
已分配
已回复
超时未回复
```

映射：

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

状态流转建议：

```text
received
  ├─ invalid
  └─ pending_assign / delay_assign
       ↓
     assigned
       ↓
     notified
       ↓
     waiting_reply
       ├─ replied
       ├─ timeout → reassigned → pending_assign / assigned
       └─ failed / manual_required
              ↓
            closed
```

当前代码差距：

1. `DouyinLead.status` 当前注释为 `pending/assigned/replied/timeout/closed`。
2. `WechatTask.status` 当前含 `pending/running/pasted/failed/blocked/cancelled/completed` 等任务状态，不等同于线索业务状态。
3. 后续数据模型设计必须区分线索业务状态、任务执行状态、回调日志状态。

------

## 9. NewCarProject 对接预留架构

当前 NewCarProject 同事暂时不能继续推进 `token / cookie / roles / merchant_id` 字段结构。

第一版先做预留设计，但必须标注后续确认。

预留原则：

1. auto_wechat 本地生成 `customer_id`。
2. NewCarProject 商户 ID 保存为 `external_customer_id`。
3. `token + cookie` 入口预留。
4. roles 结构预留。
5. 权限码预留。
6. 后续正式对接时不得破坏现有 `customer_id`。
7. 必须在后续接口契约阶段列为待确认项。

权限边界：

1. NewCarProject 决定商户是否有入口权限。
2. auto_wechat 只负责本子系统内的使用权限。
3. 商户进入 auto_wechat 后，不允许由 auto_wechat 跳转其他子功能。
4. 非商户角色的多子功能菜单跳转由 NewCarProject 负责。

当前代码差距：

1. 当前模型未发现 `customer_id` / `external_customer_id` / roles 相关字段。
2. 当前架构文档只做预留，不要求本轮改模型或认证逻辑。

------

## 10. 数据边界设计

后续数据模型设计需要覆盖以下数据域，但本架构文档不定义最终字段和迁移脚本。

1. customer / merchant 映射域：`customer_id`、`external_customer_id`、商户配置、套餐入口映射。
2. webhook 原始事件域：原始 body、header、验签结果、事件幂等键、处理状态、失败原因。
3. 有效线索域：有效线索主表、去重键、来源账号、原始事件关联、业务状态。
4. 联系方式提取域：原始文本、主手机号、主微信号、全量联系方式、提取状态、失败原因。
5. 销售管理域：销售姓名、微信昵称、手机号、排序、状态、备注。
6. 分配记录域：分配时间、销售、分配原因、轮询位置、重分配次数。
7. 微信任务域：通知任务、检测任务、任务状态、执行模式、失败阶段、原始回写结果。
8. 回复检测域：关键词配置、检测结果、命中内容、检测次数、回复时间。
9. 超时 / 重分配域：超时时间、超时记录、排除原销售、最大重分配次数。
10. 人工处理域：人工重新分配、人工补录回复、人工关闭、不可恢复关闭记录。
11. 导出域：按时间范围导出线索、分配、任务、检测、超时、回调失败、人工处理。
12. 回调 / 状态同步域：对外状态映射、回调 payload、重试次数、失败原因。
13. Local Agent 心跳与任务执行域：agent_client_id、机器信息、版本、心跳、当前任务、忙碌状态。

数据边界原则：

1. 禁止直接共享 SQLite 文件。
2. 禁止跨服务直读数据库。
3. 原始事件和有效线索必须可追溯。
4. 任务回写、状态更新、webhook 接收必须幂等。
5. 截图不保存、不入库。
6. 业务数据保存 180 天，第一版不做归档。

------

## 11. 后续文档依赖关系

P0-ARCH-1 完成后，后续文档顺序如下：

1. 数据模型设计文档
2. 接口契约文档
3. Webhook 验签迁移技术方案
4. 代码修改计划
5. 测试验收计划
6. VibeCoding 分阶段执行计划

每个后续文档必须遵守本文边界：

1. 不把 douyinAPI 作为正式生产依赖。
2. 不把 AI小高线索、小高AI微信助手、AI小高剪辑混成一个服务。
3. 不把 LLM 写入第一版架构。
4. 不设计智能路由。
5. 不绕过 Local Agent 安全门禁。
6. 不在生产环境默认关闭 webhook 验签。

------

## 12. 本轮只读代码探索记录

已确认存在：

1. `app/main.py`
2. `app/local_agent_main.py`
3. `app/models.py`
4. `app/schemas.py`
5. `app/database.py`
6. `app/routers/`
7. `app/services/`
8. `.env.development.example` / `.env.lan.example` / `.env.production.example`
9. `app/routers/integrations.py`
10. `app/integrations/douyin_webhook.py`
11. `app/routers/replies.py`
12. `app/routers/wechat_tasks.py`
13. `app/services/douyin_sync_service.py`
14. `app/services/wechat_task_service.py`

未发现路径：

1. `app/api/`
2. `app/core/`

本轮未修改上述代码文件。
