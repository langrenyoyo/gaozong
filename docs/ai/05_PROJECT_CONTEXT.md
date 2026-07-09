# 05_PROJECT_CONTEXT.md

> 本文档是 AI Coding Agent 的项目上下文。
>
> 优先级低于阅读规范，高于执行规范、测试规范和输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 0. P0-DOC-PRD-1 最终 PRD 冻结同步

更新时间：2026-06-15

最新冻结 PRD：`docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md`

### 0.0a 文档归档结构

`docs/ai` 根目录只保留 AI 入口规则和当前项目上下文：

```text
01_READING_RULES.md
02_EXECUTION_RULES.md
03_TESTING_RULES.md
04_OUTPUT_RULES.md
05_PROJECT_CONTEXT.md
README.md
```

专题文档已按阶段和业务域归档，完整索引见：

```text
docs/ai/README.md
```

常用目录：

```text
01_product_prd/          PRD 与需求差距
02_architecture/         架构与阶段迁移总方案
03_data_and_migration/   数据模型与迁移
04_interface_contracts/  接口契约与外部系统契约
05_acceptance/           测试计划、验收与检查清单
06_rag/                  RAG、Milvus、统一知识库
07_autoreply/            自动回复 gate、rollout、白名单
08_newcar/               NewCarProject 登录与权限
09_car_project/          car-porject-main 对接
10_local_agent_wechat/   Local Agent 与微信自动化
11_deployment_ops/       Docker、部署、OpenAPI、live-check
12_legacy_research/      历史计划与探索资料
```

### 0.0b 2026-07 当前上下文更新：PostgreSQL / RAG / NewCar

本节用于防止后续任务继续基于旧 SQLite-only、旧 RAG scope 或旧 NewCar 退出假设修改代码。

#### 当前服务结构

```text
9000 auto_wechat 主后端
  - 负责主业务 API、NewCar 鉴权门面、9000 可信代理、微信助手主链路、自动回复 gate。

9100 xg_douyin_ai_cs
  - 负责抖音 AI 客服、RAG、统一知识库 metadata、训练反馈自动入库、LLM 回复建议。

8788 car-porject-main 知识训练入口
  - 作为 AI 抖音客服训练页面和知识训练入口，经 9000 可信代理访问统一知识库能力。

19000 Local Agent
  - 运行在客户 Windows 本机，只负责本机微信 UI 自动化、只读检测和 paste_only 任务。

Milvus
  - 外部向量库，只负责 embedding + 向量检索副本。
```

#### 数据库路线

当前 SQLite 只是开发和早期部署过渡库，不是最终生产数据库。

PostgreSQL 目标方案已确认采用方案 A：一个 PostgreSQL 实例，两个 database。

```text
auto_wechat
  - 9000 主服务数据库
  - 未来使用 DATABASE_URL

xg_douyin_ai_cs
  - 9100 RAG / AI 客服 metadata 数据库
  - 未来使用 RAG_DATABASE_URL
```

Milvus 不替代 metadata。documents、chunks、feedback、training_run、状态字段的真源仍是 SQLite / PostgreSQL metadata；Milvus 只是检索副本。详细迁移规则见：

```text
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
```

P2-A-DB-DATABASE-URL-CONFIG-ABSTRACTION-1 已引入数据库 URL 配置抽象，但没有切换数据库：

```text
9000:
  - 新增 DATABASE_URL。
  - 未配置时仍默认 sqlite:///data/auto_wechat.db 对应的当前 SQLite 文件。

9100:
  - 新增 RAG_DATABASE_URL。
  - 未配置时仍默认 apps/xg_douyin_ai_cs/data/xg_douyin_ai_cs.db，Docker 运行仍按部署环境映射到 /data/xg_douyin_ai_cs.db。

PostgreSQL:
  - 未来由 Docker Compose 容器服务提供，不是外部托管数据库。
  - 推荐后续示例使用 postgresql+asyncpg://...@postgres:5432/auto_wechat 和 postgresql+asyncpg://...@postgres:5432/xg_douyin_ai_cs。
  - 本轮不启用 PostgreSQL、不创建连接池、不改业务 SQL、不跑迁移。
```

后续数据库演进顺序：P2-B / P2-C 建立 database factory、异步连接池和 repository 收口；P2-D 再增加 PostgreSQL docker-compose dev profile。

P2-B-DB-9000-DATABASE-FACTORY-1 已建立 9000 最小 database factory：

```text
app/database.py
  - 继续作为 9000 唯一中心数据库入口。
  - 对外保留 engine、SessionLocal、Base、get_db。
  - 新增 get_database_runtime / get_sqlite_path / create_database_engine。
  - SQLite 默认行为保持不变。
  - PostgreSQL backend 仅识别并脱敏展示；本轮创建连接会明确报未启用。
```

本轮仍未启用 PostgreSQL、未创建 async pool、未改业务 SQL、未改表结构。9000 后续 PostgreSQL 仍对应 `auto_wechat` database。

后续新增数据库代码应避免继续扩散 SQLite 专属写法，尤其不要在业务 service 中直接依赖 `sqlite3.connect`、`PRAGMA table_info`、`INSERT OR REPLACE`、`INSERT OR IGNORE`、`rowid` 或 SQLite 布尔 0/1 隐式语义。

#### RAG / 训练反馈最新状态

训练反馈自动入库已完成：

1. `useful` 自动入库 AI answer。
2. `corrected_answer` 自动入库 corrected answer。
3. `normal` / `wrong` 无修正不入库。
4. `training_id + answer_hash` 幂等。
5. 自动创建 `knowledge_document` 并训练 / upsert Milvus。

统一小高知识库 scope 已固定：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
douyin_account_id=0
category_key=base
```

训练 `ask`、`search-preview`、feedback auto-ingest 都必须按该统一 scope 检索或写入。前端传入的 `tenant_id` / `merchant_id` / `douyin_account_id` 不能作为可信上下文。

Milvus skip 问题已修复并作为后续规则固化：

```text
RAG_VECTOR_BACKEND=milvus 时，ask 不能因为 SQLite active count=0 跳过 Milvus RAG。
search-preview 能命中 Milvus 时，ask 也必须执行 Milvus RAG。
```

`ask` 的 RAG embedding/search query 只能使用 question 或极短清洗后的 question，不得把 prompt、智能体人设、知识库提示词、系统提示词或完整 session history 拼进 RAG query。prompt 只能进入 LLM 生成阶段。

#### NewCar 最新状态

NewCar 鉴权当前链路：

```text
前端 NewCar 登录跳转 / code
  -> 9000 exchange-code / callback
  -> NewCar external-auth/me
  -> 9000 建立当前用户上下文
```

本地真实 NewCar 登录必须显式配置：

```text
NEWCAR_AUTH_ENABLED=true
NEWCAR_AUTH_MOCK_ENABLED=false
```

退出登录不能只清理前端本地 token。当前要求：

```text
前端点击退出
  -> 9000 POST /auth/logout
  -> NewCarProject POST /api/external-auth/logout
  -> 前端清理本地 token 并跳回 NewCar 登录页
```

#### 安全边界

1. 不触发抖音真实发送。
2. 不触发私信真实发送。
3. 不改自动回复真实发送 gate。
4. 前端不得持有 internal token。
5. 前端不得直连 9100 / Milvus。
6. 不打印 token、URI、password、secret、cookie、完整客户消息或完整 chunk_text。
7. Milvus URI、token、数据库连接串只允许在运行环境中配置，不得进入文档示例的真实值或 git diff。

### 0.0 阶段最终目标与边界总控（2026-06-15 追加）

当前阶段状态：

```text
P0 与 DB-MIG 文档阶段已完成。
P2-A 迁移脚本骨架与副本 dry-run / apply 验证已完成（13 测试通过，748 全量回归通过，未改 models.py、未碰主线库结构）。
P2-A-END WAL/hash 验收口径修正已完成。
当前下一步应进入 P2-C：开发测试主线库正式迁移（先迁库，再补 models.py）。
P2-C 前必须遵守阶段目标总控。
当前 data/auto_wechat.db 是开发测试库，不是生产库。
迁移体系按准生产规范设计，方便未来真实客户数据上线后沿用。
```

阶段总控要求：

1. 每个阶段开始前必须复述本阶段目标、允许修改范围、禁止事项、验收标准、是否需要用户确认。
2. 每个阶段结束后必须检查是否达成本阶段最终目标、是否越界修改、是否提前实现后续阶段能力。
3. 禁止把方案设计、迁移脚本、模型字段、业务状态机、导出、前端等多个阶段混在同一轮完成。
4. 发现后续问题只能记录到风险 / 后续计划，不能擅自开发。
5. 如果当前阶段需要做后续阶段内容才能继续，必须停止并说明阻塞。

本轮同步只更新项目定位与 PRD 边界，不代表已完成技术方案、数据库模型、接口契约或业务代码变更。

### 0.1 最新项目定位

auto_wechat / 小高AI微信助手属于 NewCarProject 外部客户系统下的一组商户可售卖子功能系统。

整体结构：

```text
NewCarProject
  ↓
外部客户系统 / React 商户端
  ↓
多个可售卖子功能系统
```

NewCarProject 负责商户、账号、权限、菜单、套餐、消耗管理。外部客户系统是商户入口。

子功能系统包括：

1. 抖音AI小高客服
2. AI小高线索
3. 小高AI微信助手
4. AI小高剪辑
5. 小高素材库
6. 小高算力

其中小高算力不是子功能系统，是商户查看套餐和消耗的展示能力。

### 0.2 当前重点建设链路

当前重点建设链路：

```text
AI小高线索 → 小高AI微信助手
```

AI小高线索负责抖音扫码鉴权、获取抖音私信、识别线索来源、记录原始线索事件、从用户私信纯文本中提取手机号 / 微信号并生成有效线索。

小高AI微信助手负责获取有效线索、分配销售、创建微信通知任务、调用 Local Agent 操作客户本地微信、通知销售、检测销售是否回复、判断已回复 / 超时未回复、支持超时重分配、失败记录、人工处理和 Excel 数据导出。

### 0.3 子功能边界

AI小高线索、小高AI微信助手、AI小高剪辑是需要具备独立运行能力的子功能服务，必须预留独立启动、独立部署、独立配置、独立健康检查、独立日志、独立异常处理能力。

巨量一键过审属于 AI小高剪辑，不属于小高AI微信助手。巨量一键过审需要巨量服务扫码鉴权，后续单独出 PRD，不混入 auto_wechat 第一版。

douyinAPI 当前定位为：

```text
demo / 参考实现 / 历史代码沉淀
```

后续产品化时，不应直接把 douyinAPI 作为长期正式依赖，而应按子功能边界拆分、验证和迁移：

```text
抖音扫码鉴权、抖音私信线索 → AI小高线索
巨量扫码鉴权、巨量一键过审 → AI小高剪辑
线索分配、微信通知、回复检测 → 小高AI微信助手
```

### 0.4 Webhook 与线索接入冻结规则

第一版正式验收链路为：

```text
webhook 直收
```

正式地址继续使用：

```text
callback.misanduo.com/webhook/douyin
```

Webhook 验签规则按《抖音私信能力对外 OpenApi》：

```text
signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

Header：

```text
Authorization: signature
X-Auth-Timestamp: timestamp
```

`body` 为请求体原始字符串，`timestamp` 为秒级时间戳，`SECRET_KEY` 第一版按客户 / 商户维度配置。后续如果每个抖音账号需要不同 `SECRET_KEY`，再扩展到账号维度。

所有 webhook 事件进入 `lead_source_events`。有效线索进入 `douyin_leads`。第一版从用户发出的私信纯文本中用正则 / 规则提取手机号或微信号，不依赖顶层 `phone` / `wechat` 字段，不依赖 `retain_consult_card` 留资卡片，不接入 LLM。

### 0.5 第一版关键业务规则

有效线索规则：

1. 手机号或微信号任一存在，即视为有效线索。
2. 无联系方式的事件只记录原始事件，不进入有效线索分配。
3. invalid 进入前端列表并参与数据导出，不需要回调。
4. 一个消息中多个手机号 / 微信号全部保存，主字段取第一个。

幂等规则：

1. 优先使用数据源 `id` 作为 `external_lead_id`。
2. 如果 `id` 缺失，使用 `open_id + account_open_id`。
3. `conversation_short_id` 用于会话级辅助去重。
4. `server_message_id` 用于事件级幂等。
5. `event_key` 用于 webhook 事件幂等。
6. 重复事件返回成功并记录幂等命中结果。

状态规则：

1. 内部建议状态包括 `received`、`invalid`、`delay_assign`、`pending_assign`、`assigned`、`notified`、`waiting_reply`、`replied`、`timeout`、`reassigned`、`manual_required`、`failed`、`closed`。
2. 对外状态只包括：未分配、已分配、已回复、超时未回复。
3. `callback_success` 仅作为内部 `callback_logs.status = success`，不作为对外业务状态。

### 0.6 NewCarProject 对接预留

NewCarProject 跳转 auto_wechat 使用：

```text
token + cookie
```

auto_wechat 需要支持识别 token 和 cookie。

后续待确认项：

```text
NewCarProject token / cookie / roles / merchant_id 的具体字段结构，后续需要与 NewCarProject 同事确认。
```

customer_id 映射规则：

1. auto_wechat 本地生成 `customer_id`。
2. NewCarProject 的商户 ID 保存为 `external_customer_id`。
3. 后续 NewCarProject 正式接入时，通过 `external_customer_id` 建立映射。

### 0.7 Local Agent 安全边界

每个客户第一版只考虑一台电脑运行 Local Agent，不支持客户多台 Local Agent，不支持多个账号。同一电脑、同一微信窗口、同一 `agent_client_id` 同一时间只允许执行一个任务。

发送任务和检测任务必须互斥，`poll-and-execute` 与 `poll-and-detect` 必须互斥。忙碌时返回 `agent_busy`。微信异常、未确认联系人、微信窗口不可用、搜索框焦点未确认时必须停止操作并回写失败原因。禁止并发操作微信，高风险操作必须有日志。

exe 名称统一为：

```text
小高AI微信助手
```

### 0.8 第一版明确不做

1. 不修改业务代码时不得顺手实现 PRD 内容。
2. 不把 douyinAPI 写成正式生产依赖。
3. 不把 AI小高线索、小高AI微信助手、AI小高剪辑混成一个服务。
4. 不把巨量一键过审放入小高AI微信助手。
5. 不把 LLM 写入第一版需求。
6. 不把截图保存写入第一版需求。
7. 第一版截图不保存、不入库。
8. 第一版业务数据保存 180 天，不做数据归档。

### 0.9 P0-ARCH-1 架构设计完成记录

更新时间：2026-06-15

架构文档：`docs/ai/02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md`

关键结论：第一版产品化设计上拆分 AI小高线索与小高AI微信助手，生产环境 webhook 必须按 OpenApi 签名规则验签；旧 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 只能作为开发 / 联调兼容，不作为正式验收口径。

### 0.10 P0-DATA-1 数据模型设计完成记录

更新时间：2026-06-15

数据模型文档：`docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md`

关键结论：第一版推荐保留 `douyin_webhook_events` 物理表名，语义上承接 `lead_source_events` 原始事件域，后续产品化稳定后再单独做物理表名迁移；所有核心业务域需预留 `customer_id`，并补齐联系方式提取、幂等、分配历史、Local Agent、回调、导出和人工处理等数据边界。

### 0.11 P0-API-1 接口契约设计完成记录

更新时间：2026-06-15

接口契约文档：`docs/ai/04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`

关键结论：第一版保留正式 webhook 入口 `/webhook/douyin`，反向代理继续承接 `callback.misanduo.com/webhook/douyin`；AI小高线索到小高AI微信助手推荐先采用拉取式边界或服务层模拟，降低拆分风险；Local Agent 第一版兼容现有 `poll-and-execute` / `poll-and-detect` 任务接口，同时标记心跳、商户后台、NewCarProject 入口、导出和状态回调等目标接口为后续契约实现范围。

### 0.12 P0-WEBHOOK-AUTH-1 Webhook 验签迁移技术方案完成记录

更新时间：2026-06-15

技术方案文档：`docs/ai/04_interface_contracts/10_WEBHOOK_AUTH_MIGRATION.md`

关键结论：douyinAPI 已实现与 PRD 一致的 `sha256Hex(SECRET_KEY + body + "-" + timestamp)` 签名计算、原始 body 读取、timestamp 过期窗口和本地签名测试脚本，可作为参考；auto_wechat 当前已有更严格的 `verify_signature()`，但默认 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 只能保留为开发 / 联调兼容，生产环境必须通过后续代码方案引入环境识别并强制验签，且不得把 douyinAPI 作为正式运行时依赖。

### 0.13 P0-CODEPLAN-1 产品化代码修改计划完成记录

更新时间：2026-06-15

代码修改计划文档：`docs/ai/12_legacy_research/11_CODE_PLAN_AUTO_WECHAT.md`

关键结论：第一版产品化建议按 Webhook 生产验签、联系方式提取、原始事件与有效线索规则、数据模型补齐、状态流转、customer_id 预留、Local Agent 回归、前端接口与导出补齐的顺序渐进实施；当前真实代码仍存在 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 默认值、`im_receive_msg` 直接 upsert `douyin_leads`、`douyin_webhook_events` 字段不足、缺少 `customer_id` 和未引入迁移体系等冲突，后续执行前必须先确认生产验签切换和数据库迁移策略。

### 0.14 P0-CODEPLAN-1A 日志模板只读探索补充

更新时间：2026-06-15

只读探索路径：`D:\zws\ask_next_Project\log-template`

探索对象：

```text
log-template/
├── logging_config.py
└── logging_config.py 使用说明.md
```

日志模板结论：

1. 模板提供 `setup_logging()` 和 `get_module_logger()`，支持根 logger 初始化、模块 logger 缓存、彩色控制台输出、常规日志文件和 ERROR 独立日志文件。
2. 日志格式为 `时间 - logger 名称 - 级别 - filename:lineno - message`，适合基础文本日志，但不是结构化日志。
3. 日志级别支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`，默认从 `LOG_LEVEL` 环境变量读取，未配置时为 `INFO`。
4. 日志轮转使用 `TimedRotatingFileHandler`，每天午夜轮转，默认保留 7 天。
5. 模板没有内置 `request_id` / `trace_id`，没有 FastAPI middleware、exception handler、contextvars 或响应头回传。
6. 模板没有敏感信息脱敏 filter，不能直接用于记录 webhook、token、cookie、手机号、微信号、Authorization、SECRET_KEY 或原始请求体。
7. 模板没有全局异常接入，异常堆栈依赖调用方显式使用 `logger.exception()` 或 `exc_info=True`。

是否适合复用：适合作为后续 auto_wechat 日志基础设施的参考，不适合未经适配直接复制。后续正式执行前，必须先确认日志目录、运行日志保留周期、request_id / trace_id 生成与透传规则、敏感字段脱敏规则、FastAPI 接入方式、Local Agent exe 落盘位置，以及是否采用纯文本 key-value 还是 JSON Lines。

P0-CODEPLAN-1A 只补充日志要求和执行前决策；没有修改业务代码、配置默认值、接口、数据库模型、测试、依赖，没有复制日志代码，没有启动服务或执行迁移。

### 0.15 P0-TESTPLAN-1 测试验收计划完成记录

更新时间：2026-06-15

测试验收计划文档：`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

关键结论：第一版产品化测试验收必须以生产强制 Webhook 验签、原始 body 签名一致性、私信纯文本联系方式提取、有效线索生成、invalid 展示与导出、状态流转、销售分配、超时重分配、Local Agent 发送 / 检测互斥、失败回写、日志脱敏、数据迁移兼容、前端接口和导出为主线。正式验收不以免验签为通过口径，Local Agent 真机验收必须保持 `sent=false`、检测只读、不粘贴、不发送、不按 Enter。

### 0.16 P0-DEV-A1 Webhook 验签生产安全改造完成记录

更新时间：2026-06-15

本轮只执行 Webhook 验签生产安全小补丁：

1. 增加 `APP_ENV` 环境识别，默认 `development`。
2. 保留 `APP_ENV=development` 且 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 的本地开发 / 联调免验签能力。
3. `APP_ENV=production` 时强制 webhook 验签，即使 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 也不得静默放行。
4. `APP_ENV=production` 且 `DY_SECRET_KEY` 缺失时，webhook 请求拒绝，不进入业务事件处理。
5. `/webhook/douyin` 与 `/integrations/douyin/webhook` 继续复用 `_handle_douyin_webhook()` 和同一套验签判断。
6. 签名算法保持不变：`sha256Hex(SECRET_KEY + body + "-" + timestamp)`。
7. `.env.example` 已明确 `production must set DOUYIN_WEBHOOK_AUTH_REQUIRED=true` 和 `production must set DY_SECRET_KEY`。

本轮未修改数据库模型、未执行迁移、未修改 Local Agent 自动化逻辑、未引入新依赖、未实现联系方式提取、未改有效线索生成规则、未新增接口。

### 0.17 P0-DY-AI-CS-RAG-LLM 本地联调完成记录

本节用于固化 9100 抖音AI小高客服 RAG/LLM MVP 的当前事实，后续新窗口继续开发时必须以这里的服务边界和安全边界为准。

#### 服务边界

- `9000`：AI小高线索主后端，负责抖音线索、webhook、线索分配、销售微信回复检测、状态回调和报表等主业务能力。
- `9100`：抖音AI小高客服独立服务，负责 SQLite RAG 知识库、OpenAI-compatible LLM 智能回复建议和抖音私信客服相关后续能力。
- `19000`：小高AI微信助手 Local Agent，负责 Windows 微信 UI 自动化，依赖微信窗口、UIA、剪贴板、前台窗口、OCR 和本机 GUI 自动化，必须在 Windows 宿主机运行，不进入 Docker。
- `frontend`：React 前端已并入 `auto_wechat/frontend`，当前提供 `/douyin-ai-cs-test` 作为 9100 RAG/LLM 内部联调测试面板。

#### 本地开发启动方式

Docker 本地开发环境负责启动 `9000 + 9100 + frontend`：

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

`19000` 不容器化，需要在 Windows 宿主机单独启动：

```bash
python -m app.local_agent_main --host 127.0.0.1 --port 19000 --server-url http://127.0.0.1:9000
```

#### 9100 RAG/LLM 当前能力

9100 已实现 SQLite RAG MVP，支持知识文档创建、训练、检索和智能回复建议。当前核心接口包括：

```text
GET  /health
POST /rag/documents
POST /rag/train
POST /rag/search
POST /douyin/conversations/{conversation_id}/reply-suggestion
```

前端内部测试面板路径：

```text
/douyin-ai-cs-test
```

#### OpenRouter 当前状态

当前真实 chat 联调使用 OpenRouter：

```text
base_url: https://openrouter.ai/api/v1
chat endpoint: /chat/completions
chat model: google/gemini-3-flash-preview
verified result: llm_used=true
```

项目文档和代码中不得写入真实 API Key。真实 Key 只允许放在本地 `.env` 或运行环境变量中。

#### embedding 当前策略

OpenRouter 当前只作为 chat provider 使用，不默认作为 embedding provider。当前建议配置：

```env
XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED=false
```

在该策略下，`/rag/train` 使用本地 `mock_for_test_only` embedding，`reply-suggestion` 仍可使用真实 OpenRouter chat 生成回复建议。

NewCarPorject 的 `rag_qdrant.py` 默认 embedding 是基于 `blake2b` 的 hash 伪向量，不是真实语义 embedding 模型，只能作为历史方案参考，不能直接照搬。auto_wechat 当前 SQLite RAG 已实现 `tenant_id + merchant_id + douyin_account_id` 隔离，后续不能退回到缺少该隔离维度的检索方式。

#### 安全边界

- 9100 当前只生成回复建议。
- `auto_send` 必须保持为 `false`。
- 当前不自动发送抖音私信。
- 后续接入正式抖音AI客服页面时，仍必须由人工确认后再发送。

#### 后续职责边界

测试面板能力融合进“抖音AI小高客服”正式页面，是当前系统自己的 P1 功能。重点是会话消息、RAG 命中、AI 回复建议、人工确认和复制，不自动发送。

商户知识库管理页面属于管理员/同事侧功能，不由当前抖音AI客服页面直接承载。当前 auto_wechat / 9100 侧后续负责补齐商户知识库管理 API 和接口文档，提供给管理员前端或同事对接。

后续规划按以下边界执行：

- P1：将 `/douyin-ai-cs-test` 的能力融合进正式抖音AI小高客服页面，重点覆盖会话消息、RAG 命中、AI 回复建议、人工确认/复制，不自动发送。
- P2：补齐商户知识库管理 API 和接口文档，交给管理员前端/同事对接。当前 9100 已有 create/train/search，但管理员知识库管理可能还需要 list/detail/update/disable/delete/training-runs 等接口。
- P2/P3：后续再考虑拆分 chat provider 与 embedding provider、真实 embedding 模型、权限和生产部署。

#### 关键里程碑提交

```text
5f1c8d4 feat: add embedding enable switch for Douyin AI CS
33a0e95 fix: pass LLM env vars through local Docker compose
```

## 0.18 P1-DY-AI-CS-WORKBENCH 抖音AI客服工作台正式化完成记录

更新时间：2026-06-18

0.17 节曾将「抖音AI客服工作台正式化」列为 P1 待办，代码已实质完成。本节固化当前事实，供后续新窗口对齐。

### 工作进展（对应提交）

| 提交 | 内容 |
|------|------|
| `65c2e35` | 新增抖音AI小高客服多账号工作台（DouyinAiCsWorkbenchPage） |
| `c73ac2c` | 整合抖音AI客服工作台导航入口 |
| `2c18fc1` | 融合线索会话交互到抖音AI小高客服 |
| `4b08635` | 为 AI 客服工作台新增应用内抖音账号授权 |
| `6963aa1` | 工作台展示已授权抖音账号 |
| `05d21a0` | 抖音AI客服账号 Agent 绑定功能 |
| `bb5576d` | 接入真实抖音私信会话到 AI 客服工作台 |
| `44416be` | 从真实私信事件兜底生成抖音客服账号 |
| `8ff9376` | 修复 conversation_key 含编码 %2F 时路由匹配失败 |
| `082448c` | 显式读取 DY_CALLBACK_URL 和 DY_AUTH_REDIRECT_URL |
| `394760d` | 修复抖音 OpenAPI 授权签名与配置读取 |

### 当前事实

1. **工作台已正式化**：`DouyinAiCsWorkbenchPage` 已上线；原 `/douyin-ai-cs-test` 测试面板（`DouyinAiCsTestPage`）保留为内部联调面板。
2. **真实私信会话已接入**：工作台接入真实抖音私信会话流（提交 `bb5576d`），由 `app/services/douyin_workbench_conversation_service.py` 承载。
3. **应用内抖音账号授权已实现**：账号授权、展示、Agent 绑定均已落地（9100 `routers/accounts.py` + `app/services/douyin_live_check_service.py`）。
4. **抖音 OpenAPI 授权已修复**：`DY_CALLBACK_URL` / `DY_AUTH_REDIRECT_URL` 从环境变量显式读取（`app/config.py:95-96`），授权签名与配置读取已修复。

### 安全边界（已核实，未放宽）

- AI 回复建议 `auto_send` **恒为 false**：`apps/xg_douyin_ai_cs/services/reply_decision_service.py` 全部路径（8 处）`auto_send=False`，`schemas.py:120` 有 `auto_send: bool` 字段。
- 工作台接入的是真实私信会话**只读流 + 人工确认回复**，不自动发送抖音私信。
- 9100 是独立 FastAPI 应用（`apps/xg_douyin_ai_cs/main.py:32` 注释明确「P0 不导入 9000/19000/微信 UI/数据库/队列模块」）。

### 9100 服务结构（apps/xg_douyin_ai_cs）

```text
apps/xg_douyin_ai_cs/
├── main.py / config.py / constants.py / schemas.py
├── llm/       — LLM 客户端（OpenRouter chat）
├── rag/       — SQLite RAG（chunker/database/models/repository）
├── routers/   — health / categories / accounts / conversations / ai_reply / rag（6 个）
└── services/  — category_service / mock_workbench_service / reply_decision_service（3 个）
```

### 授权链路澄清（重要，避免与 §28.4 混淆）

本节抖音授权（`douyin_live_check_service` + `accounts`）是**抖音直播间 / 客服账号 OpenAPI 授权**，与 §28.4 提到的 **douyinAPI 旧私信 `/auth/callback` 迁移**是**两条不同链路**：

- ✅ 已实现：抖音客服账号应用内授权、抖音 OpenAPI 授权签名（本节）
- ⬜ 仍未确认：douyinAPI 旧私信 `/auth/callback` 是否迁移到 auto_wechat（§28.4 / §28.9 待办保持不变）

### 后续（0.17 节 P2/P3 仍适用）

- 商户知识库管理 API 补齐（list/detail/update/disable/delete/training-runs）
- chat provider 与 embedding provider 拆分、真实 embedding 模型
- 权限与生产部署

## 1. 项目名称

主机微信线索分发与销售跟进检测系统

## 2. 项目阶段

**P1-END-1 自动检测单次闭环演示版冻结（已完成）**

已完成阶段：P0 → P1 → P2 → P2.5 → P3 → P4 → P5 → P6 → P7 → P8 → P0-2 → P0-3 → P0-4 → P0-REPLY-2 → P0-REPLY-3B → P0-END-1 → P1-AUTO-1A/B → P1-AUTO-1AB-FIX2 → P1-AUTO-1C → P1-AUTO-1D → P1-END-1

当前聚焦：**P1-END-1 文档冻结，自动检测单次闭环演示版已通过真机验收**

最近完成：
- P1-AUTO-1D-FIX2：poll-and-execute 支持 task_id 指定执行
- P1-AUTO-1D-FIX3：poll-and-detect 支持 task_id 指定执行，避免旧 pending 队列阻塞
- P1-AUTO-1D-FIX4：search-debug 安全序列化防止 500 RecursionError
- P1-END-1：自动检测单次闭环演示版冻结（验收文档见 docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md）

下一步（2026-06-18 更新）：
- 抖音AI客服线：商户知识库管理 API 补齐、chat/embedding provider 拆分、权限与生产部署（详见 0.17 / 0.18）
- 微信助手线：P1-END-2 修复前端 pasted 展示字段、P1-END-3 清理/归档旧 pending 任务策略
- 产品化主线（P0-DEV-PLAN-1）：P2-C 主线库正式迁移 → P2-B models.py 字段补齐 → webhook 幂等/验签规范化 → 状态机重构 → 销售导入/重分配/人工处理/导出
- 历史自动检测计划项：后台定时轮询检测（旧编号 P2-A，后续按新的阶段总控重新排期）

## 3. 项目目标

通过主机微信（B）实现抖音线索的接收、分发、销售跟进检测、结果反馈的完整闭环。

------

## 4. 系统整体架构

当前系统由三个独立项目组成：

```text
抖音平台
    ↓ Webhook
douyinAPI（上游数据源，端口 8081）
    ↓ HTTP API
auto_wechat（中间业务执行层，端口 9000）
    ↓ UI Automation
主机微信 B
    ↓ 微信消息
销售微信 C
    ↓ 回复检测
主机微信 B → 反馈给 douyinAPI
    ↓
React UI（客户运营后台，端口 5173）
```

三系统定位：

| 系统 | 定位 | 路径 | 当前状态 |
|------|------|------|----------|
| auto_wechat（9000） | 中间业务执行层（AI小高线索 + 小高AI微信助手） | `E:\work\project\auto_wechat` | P1-END-1 闭环验收，webhook 直收已上线 |
| 抖音AI小高客服（9100） | 私信客服 + RAG/LLM 回复建议 | `apps/xg_douyin_ai_cs` | 多账号工作台已正式化（详见 0.18） |
| 小高AI微信助手（19000） | 本地 Agent exe | PyInstaller onedir 打包 | 监听 127.0.0.1:19000，操作本机微信，不容器化 |
| 前端 | 客户运营后台 | `E:\work\project\auto_wechat\frontend` | 已并入（原 `E:\work\project\react`），多页面接入真实 API |
| douyinAPI（8081） | 旧上游 / demo / 参考 | `E:\work\project\douyinAPI` | webhook 事件回调已由 9000 直收，旧同步链路保留 |

### 4.1 机器角色

| 角色 | IP | 说明 |
|------|-----|------|
| 开发主机 | 192.168.110.113 | 提供 React 页面（5173）、源码开发、打包。auto_wechat 路径：E:\work\project\auto_wechat |
| Windows 11 虚拟机 | — | 无源码、无 conda，只运行小高AI微信助手.exe。hostname: DESKTOP-TQHE53J。验证无源码闭环 |
| Windows 10 测试电脑 | — | 真实物理 Agent 测试机，后续复制同一份 exe 验证 |

关键约束：
- 微信自动化必须运行在微信所在的那台 Windows 电脑上
- 虚拟机/测试电脑默认没有项目代码，不能以"运行 Python 命令"作为验收前提
- React 的本机 Agent 测试按钮直连浏览器所在电脑的 127.0.0.1:19000，不走 VITE_API_BASE_URL

------

## 5. douyinAPI 探索结论

项目路径：`E:\work\project\douyinAPI`

项目定位：抖音私信线索接收系统（旧中间层，逐步退出主线）。

核心能力：

- `POST /webhook/douyin` — 接收抖音 Webhook（旧路径，原由 douyinAPI 处理）
- `leads` — 线索管理
- `conversations` — 会话管理
- `messages` — 消息管理

数据库：SQLite

关键表：

- `lead_contacts` — 线索联系人
- `conversations` — 会话记录
- `messages` — 消息记录

> ⚠️ **路径归属说明（2026-06-13 更新）**：
>
> 客户/GMP 已配置的回调地址 `https://callback.misanduo.com/webhook/douyin` 现已由 **auto_wechat** 处理（宝塔整站反代到 9000）。auto_wechat 新增了同名兼容路径 `POST /webhook/douyin`，复用自身的 `_handle_douyin_webhook` 逻辑。
>
> 因此当前实际链路为：GMP → callback.misanduo.com → 宝塔 → auto_wechat:9000/webhook/douyin → 入库。
>
> douyinAPI（8081）仍保留作为旧同步链路（`/integrations/douyin/sync-leads`），但已不再是事件回调的归属系统。详见 [第 28 节：GMP Webhook 直连接入现状](#28-gmp-webhook-直连接入现状)。

------

## 6. React UI 探索结论

项目路径：`E:\work\project\auto_wechat\frontend`（原 `E:\work\project\react`，已并入提交 `2c85433`）

项目定位：小高AI系统运营后台前端。

技术栈：

- React 19
- TypeScript
- Vite
- Tailwind
- shadcn/ui

### P5 集成进展（2026-06-09 更新）

API 基础层已完成：

| 文件 | 说明 |
|------|------|
| `src/api/client.ts` | axios 实例，baseURL 从 `VITE_AUTO_WECHAT_API_BASE_URL` 读取 |
| `src/api/types.ts` | TypeScript 类型定义（Lead, Staff, ReportSummary, DouyinSyncResponse 等） |
| `src/api/leads.ts` | `fetchLeads()`, `fetchLead(id)` |
| `src/api/staff.ts` | `fetchStaffList()` |
| `src/api/reports.ts` | `fetchSummary()` |
| `src/api/integrations.ts` | `syncDouyinLeads({ dryRun, autoAssign })` |

环境变量：

| 文件 | 内容 |
|------|------|
| `.env.development` | `VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000` |

LeadsManagement 页面状态：

- ✅ 线索列表：从 `GET /leads` 拉取真实数据
- ✅ 统计卡片：从 `GET /reports/summary` 拉取真实数据
- ✅ 销售下拉：从 `GET /staff?status=active` 拉取真实数据
- ✅ 同步按钮：`POST /integrations/douyin/sync-leads`（dry_run 预览 → 二次确认 → 写库）
- ✅ 线索详情面板：只读展示（重新分配、对话跟进按钮暂 disabled）
- ⬜ （历史）P5 时期其余页面仍为 Mock 数据

结论（2026-06-18 更新）：

- 前端已并入 `auto_wechat/frontend`（提交 `2c85433`），不再独立位于 `E:\work\project\react`
- 多页面已接入真实 API：线索、销售、检测、报表、微信助手、抖音客服工作台、webhook 事件、超管后台系列
- API 层已扩展至 17 个模块（详见 CLAUDE.md 前端章节）
- P5 时期 LeadsManagement 单页接入记录保留为历史里程碑

------

## 6.1 React UI Known Issues

### TypeScript 5.9 配置约束

详见 CLAUDE.md。

历史问题：

- 2026-06-09
- 多次出现 baseUrl 弃用提示
- 多次出现 composite 缺失提示
- 已确认最终稳定配置

验证结论（2026-06-09）：

- VSCode 提示 `ignoreDeprecations: "6.0"` 可消除 baseUrl 弃用警告
- 但项目 TypeScript 5.9.3 不支持 `"6.0"`，使用会导致 TS5103 构建失败
- 正确值：`ignoreDeprecations: "5.0"`，构建通过
- VSCode 中的弃用提示是语言服务版本差异导致，不影响构建
- 升级 TS 7.x 时需重新评估路径别名方案

后续开发禁止修改 TS 配置结构。

------

## 7. 系统角色

### 7.1 数据源微信 A

| 属性 | 说明 |
|------|------|
| 职责 | 抖音线索入口；向主机微信发送线索；接收跟进结果反馈 |
| 当前状态 | 未接入数据库；未结构化；暂时通过微信消息传递 |
| 未来规划 | 数据结构化；标准消息模板 |

### 7.2 主机微信 B（系统运行主体）

| 属性 | 说明 |
|------|------|
| 职责 | 线索入库；销售分配；跟进检测；状态回传给数据源微信 A |
| 当前 MVP 已实现 | 数据库闭环；微信 UI 检测；兜底检测；`expected_reply_text`；`risk_level`；P2.5 实验结论 |
| P3 已实现 | 自动向数据源微信 A 反馈检测结果 |

### 7.3 销售微信 C

| 属性 | 说明 |
|------|------|
| 职责 | 接收线索通知；添加客户微信；向主机微信 B 回复确认 |
| 有效回复示例 | `收到` / `已添加微信` / `收到，已添加微信` |

------

## 8. 核心业务流程

```text
抖音线索产生
    ↓
douyinAPI 接收并存储线索
    ↓
auto_wechat 从 douyinAPI 拉取线索（P4 已完成）
    ↓
auto_wechat 线索入库 + 自动分配（P4 已完成）
    ↓
主机微信 B 搜索销售昵称，打开销售聊天窗口（P7 目标）
    ↓
主机微信 B 自动发送线索通知给销售 C（P7 目标）
    ↓
销售人员 C 在指定时间内给主机微信 B 回复确认消息
    ↓
主机微信 B 通过 UI 自动化检测销售是否跟进
    · 读取当前聊天窗口消息
    · 识别发送方
    · 匹配有效确认关键词
    · 判断是否超时
    ↓
检测结果入库
    ↓
主机微信 B 向数据源微信 A 反馈检测结果
```

### 8.1 当前完整业务闭环

P8 已验证闭环：

```text
douyinAPI 测试线索生成
    ↓
React 自动同步派单
    ↓
auto_wechat 同步入库
    ↓
auto_wechat 自动分配销售
    ↓
auto_wechat 搜索 sales_staff.wechat_nickname
    ↓
主机微信发送线索通知
    ↓
lead_notifications 记录 sent
    ↓
设置 wechat_active_check_id
    ↓
销售回复"收到，已添加微信"
    ↓
wechat_auto_detect_scheduler 自动检测
    ↓
reply_checks.check_status=replied
    ↓
douyin_leads.status=replied
    ↓
React 显示"已跟进"
```

### 8.2 本地 Agent 架构流程（P0-4 目标）

```text
开发主机提供 React 页面
    ↓
测试电脑浏览器访问 http://192.168.110.113:5173
    ↓
测试电脑运行 小高AI微信助手.exe（监听 127.0.0.1:19000）
    ↓
React 检测到本机 Agent online
    ↓
用户点击「启动微信测试」
    ↓
React 直连测试电脑 127.0.0.1:19000（不走开发主机）
    ↓
小高AI微信助手.exe 操作测试电脑本机微信
    ↓
操作的是测试电脑的微信，不是开发主机的微信
```

------

## 9. 项目定位

本项目是一个**独立项目**，运行于 `E:\work\project\auto_wechat`。

**不依赖**以下任何外部系统或模块：

- 小猫AI员工
- `core/*.pyd`
- `wxauto.pyd`
- 企业微信 DLL 注入
- MCP 工具接口

------

## 10. 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| FastAPI + Uvicorn | Web 框架，端口 9000 |
| SQLAlchemy 2.x | ORM |
| SQLite | 本地数据库 `data/auto_wechat.db` |
| Pydantic 2.x | 数据校验 |
| uiautomation | 微信 PC 窗口 UI 控件读取 |
| threading | 定时任务调度（轻量后台线程） |
| React 19 + TypeScript + Vite | 前端框架，端口 5173 |
| axios | 前端 HTTP 客户端 |

------

## 11. MVP 范围

### 11.1 已完成 ✓

- 线索入库
- 销售分配（手动 + 自动轮询）
- 回复检测（手动录入 + 微信 UI 自动检测）
- 超时检测（定时扫描 + 手动触发）
- 微信 UI 当前窗口检测（多策略定位 + 消息读取 + 发送方识别）
- 期望回复文本配置（`expected_reply_text`，支持 `|` 分隔多值，优先精确/包含匹配）
- 兜底模式严格匹配（`strict_mode`，必须命中关键词或期望回复文本）
- 检测结果人工复核标记（`confirmed_required`，兜底模式时为 true）
- 检测结果警告信息（`warning`，兜底模式时提示需人工确认）
- 聊天窗口人工确认（`confirm_current_chat`，降低误操作风险）
- 检测结果可信度（`risk_level`，low / medium / high / none）
- 汇总报表（全局统计 + 分销售统计）
- 调试诊断脚本（窗口探测 + 消息控件结构分析）
- P2.5 发送方精确识别实验（UIA 深层探测 + 截图像素分析 + 实验报告）
- 调试接口：`GET /replies/debug/raw-tree`、`POST /replies/debug/sender-experiment`
- P3 反馈发送：根据 replied 线索生成反馈文本 → 写入微信输入框 → 记录入库可追溯
- P3 反馈模板：`feedback_template` 可配置，支持变量替换
- P3 安全机制：`require_confirm`（只粘贴不回车）、`confirm_chat_title`（防误发）
- P4-1 douyinAPI 线索同步基础设施：HTTP 客户端、字段映射、dry_run 预览
- P4-2 douyinAPI 线索同步入库：create/update/skip 写库
- P4-3 同步后自动分配联动：auto_assign=true 对新建线索自动分配，异常不回滚整批
- P4-4 定时同步调度器：check_scheduler.py 后台守护线程定时检测超时
- P4-5 端到端验证：douyinAPI → auto_wechat → 入库 → 分配 → 检测 完整链路验证
- P5-2A auto_wechat CORS 配置：允许 React 开发服务器（5173）跨域访问
- P5-2B React API 基础层：axios 客户端 + TypeScript 类型定义 + 5 个 API 模块
- P5-2C LeadsManagement 只读接入：线索列表 + 销售下拉 + 统计卡片 均从真实 API 拉取
- P5-2D 同步按钮：dry_run 预览 → 二次确认 → 写库 → 刷新（详见下方 P5 章节）
- 端到端自动化测试（66 个用例）
- P5-3 线索分配 UI 集成（Lead Assignment）
- P5-4 检测记录展示（Check Records）
- P5-5 微信状态检测与局域网访问
- P6 微信回复检测闭环：主机微信窗口识别、置顶/移动、消息读取、关键词命中、reply_check 入库、自动检测目标 wechat_active_check_id、wechat_auto_detect_scheduler 每 10 秒自动检测
- P7 销售派单 Demo：微信联系人搜索（contact_searcher.py）、自动打开销售聊天窗口、自动发送线索通知、lead_notifications 记录、发送后设置自动检测目标、销售回复后自动检测
- P7-BUG-1 自触发误判修复：通知模板去除关键词、发送后静默期、exclude_text_list 排除系统通知文本
- P7-STOP-1 紧急停止机制：/automation/status、/automation/emergency-stop、/automation/resume、6 个自动化入口 guard、前端停止按钮
- P8-1 WechatAgent 添加销售配置接入 POST /staff
- P8-2 douyinAPI 开发测试线索自动生成器（/dev/test-leads/start/stop/status）
- P8-3 React 自动同步派单 + 后端 auto_notify
- P8-4 Alt+Q 全局紧急停止（hotkey_listener.py + RegisterHotKey）+ 桌面自动化状态浮层（desktop_overlay.py）
- P8-5 微信固定左侧布局（activate_wechat_window(position="left")）
- P0-1 局域网访问修复（React dev:lan + CORS + 防火墙）
- P0-2 微信自动化稳定化（前台焦点守卫、白屏/灰屏诊断、Esc 隐藏修复、联系人确认策略、剪贴板修复）
- P0-3A Render Ready 诊断（debug_wechat_render_state.py）
- P0-3B 前台焦点守卫（ensure_wechat_foreground，keyboard 前检查）
- P0-3C hidden/minimized 禁止恢复（业务路径禁止自动恢复后继续）
- P0-3D 剪贴板修复（pyperclip 优先 + Win32 fallback 64 位句柄）
- P0-3E 联系人确认真实验证（UIA 不可用，转向 OCR）
- P0-3F 截图链路修复（Win32 64 位 GDI 句柄，100 次压力测试通过）
- P0-3G OCR 最小实测（EasyOCR + Aw3 识别成功）
- P0-3H OCR 接入联系人验证（ocr_matcher.py + contact_ocr_verifier.py，Aw3 5/5 verified）
- P0-3I Aw3 单条发送复测（debug 单发成功，业务自动发送仍未放开）
- P0-4A 初版 local agent（local_agent_main.py，127.0.0.1:19000）
- P0-4A 修正版 exe（PyInstaller onedir，小高AI微信助手.exe）
- P0-4A-1 微信窗口发现诊断（GET /agent/wechat/windows）
- P0-4A-2 前台焦点交接诊断（POST /agent/wechat/foreground-debug）
- React LocalWechatAgentTestPanel（本机 Agent 测试面板）
- React 按钮直连 127.0.0.1:19000（不走 VITE_API_BASE_URL）
- P1-AUTO-1A/B detect_reply task + 检测结果回写（detected_status / detect_count）
- P1-AUTO-1AB-FIX2 notify_sales pasted 后自动创建 detect_reply task + ReplyCheck 绑定 + LeadNotification 回填
- P1-AUTO-1C 19000 /agent/tasks/poll-and-detect 端点 + read_only 只读检测 + 与 poll-and-execute 共享运行锁
- P1-AUTO-1C-UTF8 19000 响应 charset=utf-8 修复 PowerShell 中文乱码
- P1-AUTO-1D React 自动回复检测面板 + 按钮触发 poll-and-detect
- P1-AUTO-1D-FIX2 poll-and-execute 支持 task_id 指定执行
- P1-AUTO-1D-FIX3 poll-and-detect 支持 task_id 指定执行，避免旧 pending 队列阻塞
- P1-AUTO-1D-FIX4 search-debug/search-result-debug 安全 JSON 序列化防止 500 RecursionError

### 11.2 未完成 □

- 数据源微信 A 自动发送线索给主机微信 B
- 数据源微信 A 自动接收反馈
- 线索结构化解析（从微信消息文本中提取线索字段）
- 发送方精确识别（P2.5 结论：当前微信版本 UIA 不可行，保持兜底模式，截图/OCR 作为后续预研方向）
- P1-END-2：修复前端 pasted 展示字段取错
- P1-END-3：清理/归档旧 pending 任务策略
- 历史自动检测计划项：后台定时轮询检测（旧编号 P2-A，从手动触发升级为自动，后续按新的阶段总控重新排期）
- 历史自动检测计划项：客户配置化关键词/工作时间/销售（旧编号 P2-B，后续按新的阶段总控重新排期）
- 历史自动检测计划项：多客户隔离（旧编号 P2-C，后续按新的阶段总控重新排期）
- 历史自动检测计划项：报表与超时策略（旧编号 P2-D，后续按新的阶段总控重新排期）
- P0-5 多目标检测队列（wechat_active_check_id 升级为多目标）
- 业务自动派单发送小流量复测

------

## 12. 项目阶段定义

### P0-P3：已完成

- P0：项目初始化、数据库设计
- P1：线索入库、销售分配、回复检测
- P2：微信 UI 自动化检测
- P3：反馈发送（主机微信 B → 数据源 A）

### P4：douyinAPI 上游线索同步（已完成）

#### P4-1 同步基础设施

- `app/integrations/douyin_api_client.py` — HTTP 客户端
- `app/services/douyin_sync_service.py` — 同步服务
- `app/routers/integrations.py` — API 路由
- `POST /integrations/douyin/sync-leads` — dry_run=true 预览
- 字段映射：open_id → source_id, display_name → customer_name 等

#### P4-2 线索入库

- dry_run=false 时执行写库
- create：本地不存在 → 新建 DouyinLead（status=pending）
- update：本地存在且 pending → 更新 customer_name/content/customer_contact/lead_type/raw_data
- skip：本地存在且非 pending → 跳过，不覆盖

#### P4-3 自动分配联动

- auto_assign=true 时，仅对本次 create 的新线索调用 assign_service.auto_assign_next()
- update/skip 不触发自动分配
- 无活跃销售时线索保持 pending，reason 标记 no_active_staff
- 分配异常不回滚整批同步

#### P4-4 定时检测调度器

- `app/scheduler/check_scheduler.py` — 后台守护线程
- 定期扫描 pending 状态的 reply_checks，将超时未回复的标记为 timeout
- 检测间隔从数据库 `check_configs` 读取（默认 5 分钟）
- 应用启动时自动启动，关闭时自动停止

#### P4-5 端到端验证

- douyinAPI → auto_wechat 拉取 → 入库 → 自动分配 → reply_check 创建 → 完整链路验证通过
- 66 个自动化测试全部通过

### P5：React UI 接入真实 API（已完成 ✅）

目标：

逐步替换 React UI 中的 Mock 数据，接入 auto_wechat 真实接口。

接入方向：

- auto_wechat：线索管理、销售管理、检测记录、报表统计
- douyinAPI：线索详情、会话消息（通过 auto_wechat 代理）

#### P5-2A CORS 配置 ✅

- `app/main.py`：CORSMiddleware 配置
- 允许 `http://127.0.0.1:5173` 和 `http://localhost:5173` 跨域访问
- 允许方法：GET, POST, PUT, DELETE, OPTIONS

#### P5-2B React API 基础层 ✅

- `react/src/api/client.ts`：axios 实例，baseURL 从 `VITE_AUTO_WECHAT_API_BASE_URL` 读取
- `react/src/api/types.ts`：TypeScript 类型定义（Lead, Staff, ReportSummary, DouyinSyncResponse 等）
- `react/src/api/leads.ts`：线索 API
- `react/src/api/staff.ts`：销售 API
- `react/src/api/reports.ts`：报表 API
- `react/src/api/integrations.ts`：同步 API
- `react/.env.development`：`VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000`

#### P5-2C LeadsManagement 只读接入 ✅

- 线索列表：`fetchLeads()` → `GET /leads`，渲染为表格
- 统计卡片：`fetchSummary()` → `GET /reports/summary`，渲染累计线索/已分配/已回复/已超时
- 销售下拉：`fetchStaffList("active")` → `GET /staff?status=active`，用于显示分配销售名称
- 线索详情面板：只读展示客户信息、状态、线索内容等
- 前端筛选：关键词搜索 + 状态筛选 + 分页（前端过滤，非服务端）

#### P5-2D 同步按钮 ✅

LeadsManagement 新增「同步 douyinAPI 测试环境线索」按钮：

流程：

1. 点击按钮 → `syncDouyinLeads({ dryRun: true, autoAssign: false })` 预览
2. 弹窗展示 fetched / mapped / created / updated / skipped / assigned 统计
3. 展示前 5 条线索预览（客户名、source_id、action、reason）
4. 用户点击「确认同步（写入数据库）」
5. `syncDouyinLeads({ dryRun: false, autoAssign: false })` 实际写库
6. 成功后刷新线索列表、销售列表、统计数据

安全限制：

- 不直接调用 douyinAPI（通过 auto_wechat 的 integrations 路由代理）
- 不默认写库（默认 dry_run=true 预览）
- 不自动分配（autoAssign=false）
- dry_run=false 必须二次确认

#### P5-3 Lead Assignment UI Integration ✅

- 「重新分配」功能接入 `POST /leads/{id}/assign`
- 使用已有 active staff 列表（`fetchStaffList("active")`）
- 分配弹窗选择销售，调用接口
- 成功后刷新线索列表和统计

#### P5-4 检测记录展示 ✅

- 检测记录列表接入真实 API
- 微信状态检测功能
- 局域网访问配置

#### P5-5 微信状态检测与局域网访问 ✅

- 微信窗口状态检测 API
- 局域网访问配置（Vite 允许外部 IP）

### P6：微信回复检测闭环（已完成 ✅）

目标：实现从微信消息读取到自动检测销售回复的完整闭环。

#### P6-1 主机微信窗口识别 ✅

- 微信窗口定位（多策略：窗口标题、类名、控件树）
- 窗口置顶/移动（activate_wechat_window）

#### P6-2 当前微信窗口消息读取 ✅

- 读取当前聊天窗口最近消息
- 消息解析（发送方识别、内容提取）

#### P6-3 关键词命中检测 ✅

- 命中"收到，已添加微信"等关键词
- reply_check 入库
- lead.status 更新为 replied
- 前端显示"已跟进"

#### P6-4 自动检测目标 ✅

- wechat_active_check_id：设置当前自动检测目标
- wechat_auto_detect_scheduler：每 10 秒自动检测
- 命中关键词后自动更新状态

### P7：Sales Dispatch Demo（已完成 ✅）

目标：补齐"通知销售"环节，实现完整业务闭环。

P7 目标闭环：

```text
douyinAPI → auto_wechat sync → assign staff
    → open sales WeChat chat by nickname
    → send lead notification
    → sales replies
    → auto detect reply
    → mark lead as replied
    → React shows 已跟进
```

#### P7-0 参考软件探索 ✅

##### 小猫AI员工探索结论

- PyInstaller + Cython .pyd
- wxauto 核心 .pyd 不可读
- 可读部分显示其发送机制本质是剪贴板 + Ctrl+V + Enter
- 消息读取使用 UIAutomation 消息列表解析
- 有任务调度数据库，但不是销售线索分配业务
- 当前微信版本存在 wxauto 不兼容问题
- 不建议直接复用 wxauto / DLL / wecom 注入方案
- 可参考任务调度、状态记录、UIAutomation 思路

##### ai-bot-pc 探索结论

- Electron 38 + Vue 3 + TypeScript
- 本地只是瘦客户端
- 业务逻辑在服务端
- 本地无微信自动化能力
- 无任务分发、无销售/线索概念、无本地数据库
- 对 P7 设计不产生改变

结论：auto_wechat 继续使用 uiautomation + input_writer 方案。

#### P7-1 微信联系人搜索 ✅

- contact_searcher.py
- `open_chat_by_nickname(nickname)`
- 通过微信搜索框输入 sales_staff.wechat_nickname
- 点击第一个搜索结果
- 返回 chat_title 和结果

#### P7-2 线索通知发送 ✅

- lead_notifications 表记录
- 生成通知文本
- 调用 input_writer 写入微信输入框
- Demo 允许 auto_send=true
- 保留 require_confirm 降级方案

#### P7-3 同步/分配后自动通知 ✅

- sync auto_assign 成功后 auto_notify=true
- notification_service.auto_notify_assigned_lead
- send-pending-assigned 接口
- 通知失败不回滚线索入库和分配

#### P7-4 发送后自动监听回复 ✅

- 发送成功后设置 wechat_active_check_id
- wechat_auto_detect_scheduler 自动检测
- 命中关键词后状态变 replied
- React 显示已跟进

#### P7-BUG-1 自触发误判修复 ✅

- 通知模板去除关键词
- 发送后静默期
- exclude_text_list 排除系统通知文本

#### P7-STOP-1 紧急停止机制 ✅

- `GET /automation/status` — 查询自动化运行状态
- `POST /automation/emergency-stop` — 紧急停止所有自动化
- `POST /automation/resume` — 恢复自动化
- 6 个自动化入口 guard 检查
- 前端停止按钮

#### P7 风险

1. 自动搜索销售昵称可能匹配错误联系人
2. 自动发送可能误发
3. 微信 UI 变化会导致搜索失败
4. 当前 Demo 可使用 auto_send，但生产默认应 require_confirm=true
5. 若搜索失败，必须降级为当前窗口发送
6. 任何通知发送都不能代表已跟进，只有销售回复命中关键词后才算已跟进
7. 发送动作必须有记录，不能静默执行

#### 微信窗口布局策略

微信窗口默认应移动到左侧。

原因：React 右侧详情区域包含核心按钮（设为自动检测目标、检测微信回复、发送线索给销售），微信放右侧会遮挡操作按钮。

推荐工作台布局：

```text
微信窗口（左侧）  |  React 后台（右侧）
```

当前 activate_wechat_window 已支持窗口移动。后续默认应从右上角改为左侧布局。

未来可设计：

```json
POST /feedback/debug/activate-wechat-window
{
  "position": "left" | "right",
  "width": 880,
  "height": 700
}
```

Demo 可先默认 left。

### P8：Demo Hardening（主要功能已完成 ✅）

目标：让连续演示稳定可靠，不新增业务功能。

P8 完整业务链路：

```text
douyinAPI 自动生成测试线索
    ↓
React 自动同步派单
    ↓
auto_wechat 同步入库
    ↓
auto_wechat 自动分配销售
    ↓
auto_wechat 搜索 sales_staff.wechat_nickname
    ↓
主机微信发送线索通知
    ↓
lead_notifications 记录 sent
    ↓
设置 wechat_active_check_id
    ↓
销售回复"收到，已添加微信"
    ↓
wechat_auto_detect_scheduler 自动检测
    ↓
reply_checks.check_status=replied
    ↓
douyin_leads.status=replied
    ↓
React 显示"已跟进"
```

#### P8 已完成能力

1. **WechatAgent 添加销售配置** → POST /staff
2. **douyinAPI 测试线索生成器**：
   - `POST /dev/test-leads/start`
   - `POST /dev/test-leads/stop`
   - `GET /dev/test-leads/status`
3. **微信固定左侧布局**：
   - `activate_wechat_window(position="left")`
   - contact_searcher 搜索前固定窗口
4. **Alt+Q 紧急停止**：
   - `hotkey_listener.py`
   - `RegisterHotKey` 全局热键
   - `request_emergency_stop`
5. **桌面浮层**：
   - `desktop_overlay.py`
   - 自动化运行中 / 已停止提示
6. **自动同步派单**：
   - `sync-leads auto_notify=true`
   - `notification_service.auto_notify_assigned_lead`
   - `send-pending-assigned`
7. **P7-BUG-1 修复**：
   - 通知模板去关键词
   - 静默期
   - exclude_text_list

#### P8 真实验证结果

- 线索同步：7/7
- 自动分配：7/7
- 自动通知：7/7
- 联系人搜索：4/4
- 用户确认收到微信通知
- 紧急停止机制生效
- 桌面浮层和 Alt+Q 已运行
- 自动检测：13/28 replied，存在单目标覆盖限制
- 结论：可以演示，但需说明当前检测是单目标监听，P9 支持队列化

### P0：风险修复（P0-1~P0-3 已完成，P0-4 进行中）

#### P0-1 局域网访问修复 ✅

修复点：

1. React API baseURL 不能是 127.0.0.1
2. 新增 `npm run dev:lan`，加载 `.env.lan`
3. `.env.lan` 指向 `http://192.168.110.113:9000`
4. CORS 增加 `http://DESKTOP-T0HA3GO:5173`
5. 防火墙需开放 TCP 9000 和 TCP 5173

局域网访问地址：

- React: `http://192.168.110.113:5173`
- API docs: `http://192.168.110.113:9000/docs`
- automation status: `http://192.168.110.113:9000/automation/status`

#### P0-2 微信自动化稳定化 ✅

子阶段进展：

| 子阶段 | 内容 | 状态 |
|--------|------|------|
| P0-2A~2D | 搜索框/输入框稳定化 | ✅ 已完成 |
| P0-2E | 联系人二次确认（策略 A/B/C、send_to_staff guard） | ✅ 已完成 |
| P0-2F | 白屏根因隔离 | ✅ 已完成（17/40 白屏是窗口隐藏 + 截桌面误判） |
| P0-2G | 窗口隐藏与白屏误判修复 | ⚠️ 部分修复（Esc 隐藏已修复，灰屏现象仍存在） |

灰屏问题说明：窗口 visible=True 但客户区灰色/空白、UI 内容不渲染。与窗口隐藏是不同问题。P0-3 通过 OCR 截图链路绕过了此问题。

#### P0-3 本机微信自动化稳定性与安全门禁 ✅

P0-3 主要解决本机微信自动化稳定性和安全门禁。

| 子阶段 | 内容 | 结果 |
|--------|------|------|
| P0-3A | Render Ready 诊断 | 发现前台焦点丢失、hidden 恢复导致灰屏等问题 |
| P0-3B | 前台焦点守卫 | ensure_wechat_foreground，keyboard 前检查，失败不继续 |
| P0-3C | hidden/minimized 禁止恢复 | 业务路径禁止自动恢复，必须提示人工打开 |
| P0-3D | 剪贴板修复 | pyperclip 优先 + Win32 fallback 64 位句柄修复 |
| P0-3E | 联系人确认真实验证 | open_chat_by_nickname 能打开聊天，但纯 UIA 无法可靠读取 Qt5 标题 |
| P0-3F | 截图链路修复 | Win32 64 位 GDI 句柄修复，100 次截图压力测试通过 |
| P0-3G | OCR 最小实测 | EasyOCR 安装，Aw3 OCR 成功，啊东、只能识别主体 |
| P0-3H | OCR 接入联系人验证 | ocr_matcher.py + contact_ocr_verifier.py，Aw3 5/5 verified |
| P0-3I | Aw3 单条发送复测 | debug 单发成功（paste-only + single_send），但业务自动发送仍未放开 |

P0-3 关键结论：
- UIA 无法可靠读取 Qt5 微信标题/资料卡，转向 OCR 方案
- Aw3 是唯一允许自动验证和 debug 测试的联系人（OCR 5/5 verified）
- 啊东、只能 partial_match，不允许自动发送
- P0-3I 证明 debug 单发链路可用，不代表业务自动发送已放开

#### P0-4 本地 Agent / exe 架构验证（进行中）

P0-4 目标：验证测试电脑无源码运行小高AI微信助手.exe，由 React 页面调用测试电脑本机 127.0.0.1:19000 操作本机微信。

本地 Agent 命名：**小高AI微信助手**（exe：小高AI微信助手.exe）

##### P0-4A 初版 local agent ✅

- `app/local_agent_main.py`：监听 127.0.0.1:19000
- 接口：`GET /health`、`POST /agent/wechat/test`
- React 新增 `LocalWechatAgentTestPanel`
- React 按钮直连 127.0.0.1:19000，不走 VITE_API_BASE_URL

##### P0-4A 修正版 exe ✅

- `app/local_agent_exe_entry.py`
- `scripts/build_local_agent_exe.ps1`（PyInstaller onedir）
- 输出：`E:\work\project\auto_wechat\dist\小高AI微信助手\小高AI微信助手.exe`
- 开发机 /health smoke test 通过

##### P0-4A-1 微信窗口发现诊断 ✅

- `GET /agent/wechat/windows`
- `find_wechat_window` 增强 Win32 枚举（title / class / process_name 多策略）
- 排除小高AI微信助手自身窗口、资源管理器目录窗口、Edge 等误识别
- 开发机 smoke 能检测 Weixin.exe

##### P0-4A-2 前台焦点交接诊断 ✅

- `POST /agent/wechat/foreground-debug`
- `ensure_wechat_foreground` 增强：SetForegroundWindow + BringWindowToTop + AttachThreadInput + Alt wakeup + SetWindowPos(HWND_TOP)
- 仍禁止 hidden/minimized 自动恢复后继续
- 仍禁止 Esc
- 开发机 exe smoke 通过

##### Windows 11 虚拟机真实状态

| 步骤 | 结果 |
|------|------|
| 访问开发主机 React（http://192.168.110.113:5173） | ✅ 成功 |
| 运行小高AI微信助手.exe | ✅ 成功 |
| React 检测虚拟机本机 Agent online | ✅ online=true，hostname: DESKTOP-TQHE53J |
| 诊断微信窗口 | ✅ 成功 |
| 前台焦点诊断 | ✅ 成功 |
| 点击「启动微信测试」→ 自动切换到 Aw3 | ❌ 未切换（提示：联系人验证需要人工复核，禁止发送） |
| 虚拟机 Aw3 输入框出现测试消息 | ❌ 未出现 |

当前真实阻塞：/agent/wechat/test 只验证当前聊天窗口，没有自动执行 open_chat_by_nickname("Aw3")。

##### P0-4A-3（下一步 — 当前阻塞点）

目标：让 /agent/wechat/test 在小高AI微信助手.exe 中执行：

```text
readiness
    → foreground
    → open_chat_by_nickname("Aw3")
    → verify_current_chat_contact("Aw3")（OCR verified=true）
    → paste_only
    → sent=false
```

验收标准：
1. Windows 11 虚拟机无源码，仅运行小高AI微信助手.exe
2. React 点击「启动微信测试」后自动打开 Aw3
3. OCR verified=true
4. paste_only 成功
5. sent=false
6. 操作的是虚拟机本机微信
7. 开发主机微信不被操作

P0-4A-3 通过后，才能判定 P0-4A 完成。

##### P0-4 后续

- **P0-4B**：小高AI微信助手.exe 安装包/分发优化
- **P0-4C**：Windows 10 测试电脑复测

#### 当前 P0 风险排序

| 优先级 | 风险 | 状态 |
|--------|------|------|
| P0-1 | 局域网访问 | ✅ 已完成 |
| P0-2 | 微信自动化稳定化 | ✅ 已完成 |
| P0-3 | 本机自动化稳定性与安全门禁 | ✅ 已完成 |
| P0-4A-3 | 本地 Agent 自动打开 Aw3 + OCR + paste_only | ❌ 当前阻塞 |
| P0-4B | exe 安装包/分发 | 待做 |
| P0-4C | Windows 10 测试电脑复测 | 待做 |
| P0-5 | 多目标检测队列 | 待做 |
| P1-1 | 桌面常驻状态中心 | 待做 |
| P2-1 | 业务发送链路小流量复测 | 待做（P0-4A-3 通过后才考虑） |

### 跨机器架构说明

局域网其他机器可以访问 React 和 API，但微信自动化执行在运行小高AI微信助手.exe 的那台机器。

```text
机器 A（开发主机）提供 React 页面
机器 B（测试电脑）运行 小高AI微信助手.exe → 只能控制机器 B 的微信
机器 B 浏览器访问机器 A React → 点击按钮 → 调用机器 B 本机 127.0.0.1:19000
```

核心原则：
- 谁打开 React 页面，谁点击按钮，127.0.0.1 就是谁的电脑，微信自动化也发生在谁的电脑
- 虚拟机/测试电脑默认没有项目代码，不能以"运行 Python 命令"作为验收前提
- 不能操作开发主机微信作为测试电脑结果

未来产品化目标：中心后台 + 多 Windows Agent（每个 Agent 控制本机微信）。

### Current Safety Gates（当前活跃安全约束）

以下约束在 P1-END-1 后必须严格执行：

1. **业务自动派单发送仍禁止**（sent 必须为 false）
2. **Aw3 是唯一允许自动验证和 debug 测试的联系人**
3. 啊东、只能 partial_match，不允许自动发送
4. partial_match 不允许 verified=true
5. manual_review_required=true 不允许粘贴或发送
6. hidden/minimized 微信不允许自动恢复后继续
7. ESC 不允许业务路径使用后继续
8. foreground guard 失败必须停止
9. OCR/截图失败不能伪造成功
10. 小高AI微信助手.exe 不应监听 0.0.0.0，默认只监听 127.0.0.1:19000
11. React 本机 Agent 面板不能使用 VITE_API_BASE_URL
12. 不能操作开发主机微信作为测试电脑结果
13. **poll-and-execute 必须只处理 notify_sales**
14. **poll-and-detect 必须只处理 detect_reply**
15. **detect_reply 必须 action.sent=false、action.pasted=false**
16. **新建任务后必须按 task_id 执行当前任务，禁止依赖旧 pending 队列头部**
17. **诊断接口不得返回原始 UIA 对象，必须安全 JSON 序列化**
18. **旧 wechat_auto_detect_scheduler 默认禁用，启用需显式设置 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1**

### 真实测试联系人

| 联系人 | OCR 表现 | verified 率 | 允许操作 |
|--------|----------|-------------|----------|
| Aw3 | OCR 可稳定识别为 AW3 | 5/5 verified | debug 测试 + paste_only |
| 啊东、 | OCR 只能识别主体"啊东"，顿号缺失 | 5/5 partial_match | 不允许自动发送，只能人工确认兜底 |
| 文件传输助手 | — | — | 辅助低风险验证，不作为主要验收 |

------

## 13. 已验证能力

以下能力已在代码中实现并通过测试验证：

| # | 能力 | 验证方式 |
|---|------|----------|
| 1 | douyinAPI → auto_wechat 线索拉取 | HTTP 客户端 + dry_run 预览 |
| 2 | 线索自动去重（source_id 唯一） | create/update/skip 逻辑 |
| 3 | 新建线索自动分配 | auto_assign_next() 联动 |
| 4 | reply_check 自动创建 | assign_lead() 内部创建 |
| 5 | 反馈模块（主机 B → 数据源 A） | feedback_service + input_writer |
| 6 | 微信 UI 检测（兜底模式） | wechat_ui_reply_service |
| 7 | 定时超时检测 | check_scheduler 后台线程 |
| 8 | React 真实数据展示 | LeadsManagement 页面接入 /leads, /staff, /reports/summary |
| 9 | React 同步按钮 | dry_run 预览 → 二次确认 → 写库 → 刷新 |
| 10 | React 线索分配 UI | 分配弹窗 + POST /leads/{id}/assign |
| 11 | React 检测记录展示 | 检测记录列表接入真实 API |
| 12 | 微信窗口置顶/移动 | activate_wechat_window |
| 13 | 关键词命中自动检测 | wechat_auto_detect_scheduler + wechat_active_check_id |
| 14 | 微信联系人搜索 | contact_searcher.open_chat_by_nickname |
| 15 | 线索通知自动发送 | notification_service + lead_notifications |
| 16 | 自动同步派单 | sync-leads auto_notify=true |
| 17 | 紧急停止机制 | Alt+Q + /automation/emergency-stop + 前端按钮 |
| 18 | 局域网访问 | dev:lan + 0.0.0.0 绑定 + CORS + 防火墙 |
| 19 | 前台焦点守卫 | ensure_wechat_foreground，keyboard 前检查 |
| 20 | hidden/minimized 禁止恢复 | 业务路径不自动恢复，提示人工 |
| 21 | 剪贴板修复 | pyperclip + Win32 fallback 64 位句柄 |
| 22 | OCR 联系人验证 | ocr_matcher + contact_ocr_verifier，Aw3 5/5 verified |
| 23 | 本地 Agent exe | 小高AI微信助手.exe，PyInstaller onedir，/health 通过 |
| 24 | 微信窗口发现诊断 | GET /agent/wechat/windows，Win32 多策略枚举 |
| 25 | 前台焦点交接诊断 | POST /agent/wechat/foreground-debug |
| 26 | 虚拟机 Agent 在线检测 | React 检测 127.0.0.1:19000 online，显示 hostname |

------

## 14. 当前技术状态

### 14.1 微信发送方识别

**状态**：P2.5 实验已完成，结论已写入

**当前正式方案**：`fallback_current_window_text`（兜底模式）

- 检测当前聊天窗口中是否存在有效回复文本（如"收到，已添加微信"）
- `strict_mode=True`：必须命中 `expected_reply_text` 或 `effective_keywords`，不允许仅靠长度判定
- 配合 `risk_level` / `confirmed_required` / `confirm_current_chat` 标记可信度

**当前返回**：

```text
detection_mode    = fallback_current_window_text
confirmed_required = true
warning           ≠ null
risk_level        = medium / high
```

**当前结论**：

- ✅ 系统能够识别：当前聊天窗口是否存在有效回复文本
- ❌ 系统暂不能可靠识别：该文本是否由销售 C 发送（UIA 控件树不可行）

### 14.2 发送方精确识别专项实验（P2.5）—— 已完成

**目标**：稳定区分 `friend`（销售）和 `self`（主机）

**实验方法与结论**：

| 方向 | 结论 | 说明 |
|------|------|------|
| 1. UIA 深层控件树 | ❌ 不可行 | `GetChildren()` 返回 0 子控件；`WalkControl()` / `FindAll()` 均无子孙 |
| 2. ControlFromPoint | ❌ 不可行 | 左/中/右三点点采样均命中 ListItemControl 自身，未命中更深层控件 |
| 3. 截图 + 像素分析 | ⚠️ 待验证 | 理论可行（绿色靠右=主机，白色靠左=销售），但依赖微信渲染一致性 |
| 4. 气泡颜色识别 | ⚠️ 同上 | 截图方案的子方向，需 numpy 依赖 |
| 5. OCR 辅助识别 | ⚠️ 预研方向 | 作为后续视觉识别方案，不进入当前主线 |

**关键发现**：

- 当前微信版本消息 `ListItemControl` 为**扁平结构**：文本存在 `Name` 属性，无子控件
- 消息 item 的 `BoundingRectangle` 占满列表全宽，无法通过位置区分发送方
- `ButtonControl` / `ImageControl` / `TextControl` 在 `searchDepth=2` 下均不存在

**正式方案决定**：

- ✅ **保留 `fallback_current_window_text` 作为当前 MVP 正式检测方案**
- 截图/像素/OCR 作为后续视觉识别预研，不进入当前主线
- 微信大版本更新后可重新运行 `scripts/debug_wechat_raw_tree.py` 验证是否有新控件结构

**保留的调试资源**：

| 资源 | 说明 |
|------|------|
| `scripts/debug_wechat_raw_tree.py` | UIA 深层控件树探测脚本 |
| `scripts/debug_wechat_screenshot.py` | 截图 + 像素分析脚本 |
| `GET /replies/debug/raw-tree` | UIA 深层探测 API 端点 |
| `POST /replies/debug/sender-experiment` | 发送方方案实验 API 端点 |
| `docs/experiment_report_sender_identification.md` | 完整实验报告 |

------

## 15. 实际项目结构

```text
auto_wechat/
├── app/                        # 9000 主后端（AI小高线索 + 小高AI微信助手）
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 项目配置（含 APP_ENV / DY_CALLBACK_URL / DY_AUTH_REDIRECT_URL）
│   ├── database.py             # 数据库连接与会话管理
│   ├── models.py               # ORM 模型
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── local_agent_main.py     # 19000 Local Agent 入口
│   ├── local_agent_exe_entry.py# Local Agent exe 打包入口
│   ├── local_agent_build_info.py
│   ├── routers/                # API 路由（15 个）
│   │   ├── staff.py / leads.py / replies.py / feedback.py
│   │   ├── integrations.py     #   douyinAPI 同步 + webhook 双入口（第 28 章）
│   │   ├── checks.py / reports.py
│   │   ├── agent.py            #   Local Agent 任务（poll-and-execute / poll-and-detect）
│   │   ├── automation_control.py
│   │   ├── douyin_live_check.py#   抖音直播间检测 / OpenAPI 授权
│   │   ├── lead_notifications.py
│   │   ├── webhook_events.py   #   原始事件只读查询（P0-DEV-E1）
│   │   ├── wechat_auto_detect.py
│   │   └── wechat_tasks.py
│   ├── integrations/           # 外部系统集成
│   │   ├── douyin_api_client.py#   douyinAPI HTTP 客户端（只读）
│   │   └── douyin_webhook.py   #   GMP webhook 主处理
│   ├── services/               # 业务逻辑层（20 个）
│   │   ├── staff_service / lead_service / assign_service
│   │   ├── reply_analyzer / reply_checker / report_service
│   │   ├── douyin_sync_service.py        # douyinAPI 线索同步
│   │   ├── douyin_workbench_conversation_service.py  # 抖音客服工作台会话
│   │   ├── douyin_live_check_service.py  # 抖音直播间检测 / 授权
│   │   ├── notification_service.py       # 线索通知
│   │   ├── wechat_task_service.py        # 微信任务编排
│   │   ├── wechat_ui_reply_service.py    # 微信 UI 自动检测
│   │   ├── contact_extractor.py          # 联系方式提取
│   │   ├── webhook_event_service.py
│   │   ├── agent_status_service.py / automation_control.py
│   │   ├── desktop_overlay.py / hotkey_listener.py  # Alt+Q / 桌面浮层
│   │   └── feedback_service.py
│   ├── wechat_ui/              # 微信 UI 自动化模块（window_locator / current_chat_reader / message_parser / reply_detector / input_writer / exceptions）
│   └── scheduler/              # 定时检测调度器（check_scheduler）
├── apps/
│   └── xg_douyin_ai_cs/        # 抖音AI小高客服 9100 独立服务（详见 0.18）
│       ├── main.py / config.py / constants.py / schemas.py
│       ├── llm/                # LLM 客户端（OpenRouter chat）
│       ├── rag/                # SQLite RAG（chunker/database/models/repository）
│       ├── routers/            # health / categories / accounts / conversations / ai_reply / rag（6 个）
│       └── services/           # category_service / mock_workbench_service / reply_decision_service（3 个）
├── frontend/                   # React 前端（已并入，原 E:\work\project\react，提交 2c85433）
│   └── src/                    # api(17) / pages(21) / components / hooks / lib / data
├── migrations/                 # DB-MIG 迁移体系（P2-A 已建）
│   ├── migrate_sqlite.py
│   └── versions/0001_prd_base_fields.sql
├── scripts/                    # 初始化 / 演示 / 调试诊断 / exe 打包脚本
├── tests/                      # 自动化测试（端到端 / douyin 同步 / 迁移 等）
├── data/                       # SQLite 数据（auto_wechat.db，开发测试库，非生产库）
├── docs/ai/                    # AI 协作规范入口与分阶段归档文档（见 docs/ai/README.md）
├── docker-compose.dev.yml      # 本地 Docker 开发（9000 + 9100 + frontend，19000 不容器化）
├── Dockerfile.backend.dev / Dockerfile.frontend.dev
├── requirements.txt / requirements-docker.txt
├── .gitignore / .dockerignore
├── CLAUDE.md
└── README.md
```

> 说明：本结构图为 2026-06-18 重新核对版本，与 `app/routers`（15）、`app/services`（20）、`apps/xg_douyin_ai_cs`、`migrations/`、`frontend/` 实际目录一致。早期 P0–P5 时期的精简结构图（仅 8 router / 8 service）已废弃。

------

## 16. 核心数据库表

### 16.1 sales_staff（销售人员）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| name | String(50) | 销售姓名 |
| wechat_id | String(100) | 销售微信号（用于匹配主机微信中的发送方） |
| wechat_nickname | String(100) | 销售微信昵称 |
| phone | String(20) | 手机号 |
| status | String(20) | 状态：active / inactive |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 16.2 douyin_leads（抖音线索）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| source | String(20) | 来源平台，默认 douyin |
| lead_type | String(20) | 线索类型：lead / comment / chat |
| customer_name | String(100) | 客户名称/昵称 |
| customer_contact | String(100) | 联系方式 |
| content | Text | 线索内容 |
| source_url | String(500) | 来源链接 |
| source_id | String(100) | 来源平台ID |
| assigned_staff_id | Integer FK | 分配的销售ID |
| assigned_at | DateTime | 分配时间（超时计算的起点） |
| status | String(20) | 状态：pending / assigned / replied / timeout / closed |
| raw_data | Text | 原始数据JSON |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 16.3 reply_checks（回复检测记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| lead_id | Integer FK | 线索ID |
| staff_id | Integer FK | 销售ID |
| reply_deadline | DateTime | 要求回复截止时间（assigned_at + reply_timeout_minutes） |
| actual_reply_at | DateTime | 实际确认回复时间（从主机微信读取） |
| reply_content | Text | 销售发送的确认消息内容 |
| is_effective | Integer | 是否有效确认：0 / 1 |
| effectiveness_reason | String(200) | 判定原因 |
| check_status | String(20) | 检测状态：pending / replied / timeout / invalid |
| checked_at | DateTime | 检测时间 |
| created_at | DateTime | 创建时间 |

### 16.4 check_configs（检测配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| config_key | String(100) UNIQUE | 配置键 |
| config_value | Text | 配置值 |
| description | String(200) | 说明 |
| updated_at | DateTime | 更新时间 |

默认配置项：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| reply_deadline_minutes | 30 | 确认回复截止时间（分钟），销售收到线索后需在此时间内向主机微信确认 |
| check_interval_minutes | 5 | 定时检测间隔（分钟） |
| effective_reply_min_length | 2 | 有效回复最小长度 |
| effective_keywords | 收到,已添加微信,已添加 | 有效确认关键词 |
| invalid_keywords | 不知道,不清楚,等下再说,没空,无法处理 | 无效关键词 |
| expected_reply_text | 收到，已添加微信\|收到，已添加\|已添加微信 | 期望回复文本（`\|` 分隔多值），优先精确/包含匹配 |

------

## 17. 业务状态机

### 17.1 线索状态流转

```text
pending（待分配）
    ↓ 分配销售
assigned（已分配，等待销售向主机微信确认）
    ↓ 检测到有效确认              ↓ 超时未确认
replied（已确认）              timeout（超时未确认）
```

说明：

- **pending**：线索已创建，等待分配给销售
- **assigned**：已分配给销售，等待销售向主机微信 B 回复确认
- **replied**：在主机微信 B 中检测到销售的有效确认消息
- **timeout**：超过截止时间，主机微信 B 中仍未检测到销售的有效确认消息

### 17.2 检测记录状态流转

```text
pending（等待销售确认）
    ↓ 检测到有效确认         ↓ 检测到无效回复         ↓ 超时
replied（已确认）       invalid（无效回复）     timeout（超时）
```

------

## 18. 有效确认回复判定规则

### 18.1 业务定义

销售收到线索后，需要向主机微信 B 发送确认消息。**有效确认消息**必须包含以下关键词之一：

| 有效确认关键词 | 含义 |
|----------------|------|
| `收到` | 销售确认已收到线索 |
| `已添加微信` | 销售确认已添加客户微信 |
| `收到，已添加微信` | 销售确认既收到线索又添加了客户微信 |

### 18.2 允许的格式差异

系统对标点和空格有一定容错：

```text
收到           → 有效
收到。         → 有效
收到，已添加微信 → 有效
收到，已添加微信。→ 有效
收到 已添加微信  → 有效
已添加微信      → 有效
已添加微信。    → 有效
```

### 18.3 判定规则

判定顺序（优先级从高到低）：

1. 回复内容为空 → **无效**
2. 命中无效关键词（如"不知道"、"没空"等）→ **无效**
3. 匹配 `expected_reply_text`（精确或包含）→ **有效**（最高优先级）
4. 命中有效确认关键词 且 长度 ≥ 配置值 → **有效**
5. 命中有效确认关键词 但 长度 < 配置值 → **无效**
6. 未命中任何关键词 且 长度 ≥ 配置值 → **有效**（默认有效，仅非 strict_mode 时）
7. 未命中任何关键词 且 长度 < 配置值 → **无效**

> 以上规则均可通过 `check_configs` 表动态配置，无需改代码。

### 18.4 超时规则

配置项：`reply_deadline_minutes`（默认 30 分钟）

```text
截止时间 = 线索分配时间（assigned_at）+ reply_timeout_minutes

示例：
  线索 14:00 分配给销售A
  reply_timeout_minutes = 10
  → 销售A 必须在 14:10 前向主机微信 B 发送有效确认消息
  → 14:10 后仍未检测到 → 标记为 timeout
```

------

## 19. 微信 UI 检测核心逻辑

### 19.1 检测目标

系统读取的是**主机微信 B** 窗口的消息，不是客户微信，也不是销售微信。

检测链路：

```text
定位主机微信 B 窗口
    ↓
定位当前聊天消息列表
    ↓
读取最近 N 条消息
    ↓
识别每条消息的发送方（区分 self=B主机 / friend=C销售）
    ↓
筛选出销售 C 发送的消息
    ↓
检查消息内容是否命中有效确认关键词
    ↓
检查消息时间是否在超时时限内
    ↓
判定结果：PASS（有效确认）或 TIMEOUT（超时）
    ↓
结果落库（更新 reply_checks + douyin_leads）
```

### 19.2 窗口定位策略（多策略容错）

文件：`app/wechat_ui/window_locator.py`

| 策略 | 方法 | 说明 |
|------|------|------|
| 策略 1 | `ctypes.FindWindowW` | 按窗口标题精确查找（"Weixin"、"微信"、"WeChat"） |
| 策略 2 | Desktop 遍历 | 遍历所有顶层窗口，按 `ClassName` 模糊匹配 |
| 策略 3 | 多候选排序 | 优先选择有消息列表控件、非离屏、面积最大的 |

### 19.3 发送方识别（多策略级联）

文件：`app/wechat_ui/message_parser.py`

| 优先级 | 策略 | 原理 |
|--------|------|------|
| 1 | 系统消息过滤 | 时间分割线、系统提示 → 标记为 `system` |
| 2 | **消息气泡位置（主力）** | 自己发的消息靠右，对方消息靠左（边缘距离阈值 80px） |
| 3 | 头像控件位置 | `ButtonControl`/`ImageControl` 头像在中线左/右侧 |
| 4 | 文本位置辅助 | `TextControl` 的中心 X 坐标偏向判断 |
| 5 | 兜底 `unknown` | 记录调试日志，便于后续优化 |

### 19.4 核心前提

> 当前电脑登录的微信账号就是**主机微信 B**。
>
> 因此 `self`（自己发的）消息是主机微信 B 发的，`friend`（对方发的）消息才是销售 C 发的。
>
> **销售的确认消息在主机微信 B 中表现为"对方发的消息"（`friend`）。**

### 19.5 兜底机制

当 UI 无法区分发送方时（`self` 消息数为 0），启用**兜底模式**：

> 业务前提：当前窗口就是主机微信 B + 销售 C 的聊天窗口

兜底模式下，将所有非系统消息、有文本内容的消息作为候选分析对象。

兜底模式检测结果会标记：

```text
detection_mode    = fallback_current_window_text
confirmed_required = true     # 需要人工复核
warning           ≠ null      # 提示需人工确认
risk_level        = medium / high  # 中高风险
```

------

## 20. API 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/staff` | 创建销售人员 |
| GET | `/staff` | 获取销售列表 |
| GET | `/staff/{id}` | 获取单个销售 |
| PUT | `/staff/{id}` | 更新销售信息 |
| POST | `/leads` | 创建线索 |
| GET | `/leads` | 获取线索列表 |
| GET | `/leads/{id}` | 获取单条线索 |
| POST | `/leads/{id}/assign` | 分配线索给销售 |
| POST | `/replies/manual` | 手动录入销售确认回复 |
| POST | `/replies/current-wechat-detect` | 通过主机微信 B 的 UI 自动检测当前聊天窗口 |
| GET | `/replies/debug/windows` | 调试：列出所有疑似微信窗口 |
| GET | `/replies/debug/messages` | 调试：返回消息原始控件结构 |
| GET | `/replies/debug/raw-tree` | P2.5 实验：UIA 深层控件树探测 |
| POST | `/replies/debug/sender-experiment` | P2.5 实验：发送方识别方案验证 |
| POST | `/feedback/compose` | P3：生成反馈文本（主机 B → 数据源 A） |
| POST | `/feedback/send-current-chat` | P3：将反馈文本写入当前微信聊天窗口 |
| GET | `/feedback/records` | P3：查询反馈发送记录 |
| POST | `/integrations/douyin/sync-leads` | P4：从 douyinAPI 拉取线索并同步（dry_run 预览 + 写库） |
| POST | `/integrations/douyin/webhook` | GMP 私信事件回调（内部/新路径入口，鉴权可配置） |
| POST | `/webhook/douyin` | GMP 私信事件回调（**客户旧路径兼容入口**，宝塔整站反代目标） |
| POST | `/checks/run` | 手动触发一次超时检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |

------

## 21. 调用链

### 21.1 标准请求调用链

```text
API（routers/）
    ↓ Depends(get_db)
Service（services/）
    ↓ SQLAlchemy ORM
Database（SQLite）
```

### 21.2 线索分配调用链

```text
POST /leads/{id}/assign
    ↓
assign_service.assign_lead()
    ↓ 更新 douyin_leads 状态为 assigned，记录 assigned_at
    ↓ 创建 reply_checks 记录（pending）
    ↓ 计算 reply_deadline = assigned_at + reply_timeout_minutes
Database
```

### 21.3 手动确认录入调用链

```text
POST /replies/manual
    ↓
reply_checker.record_manual_reply()
    ↓ 查找/创建 reply_checks 记录
    ↓ reply_analyzer.analyze_reply() 判定有效性
    ↓ 更新 reply_checks（is_effective, check_status）
    ↓ 同步更新 douyin_leads 状态
Database
```

### 21.4 微信 UI 自动检测调用链

```text
POST /replies/current-wechat-detect
    ↓
wechat_ui_reply_service.detect_reply_from_wechat()
    ↓ window_locator.find_wechat_window()            定位主机微信 B 窗口
    ↓ current_chat_reader.read_recent_messages()      读取主机微信 B 消息
    ↓ reply_detector.find_self_messages()              筛选销售 C 消息
    ↓ reply_detector.find_effective_reply()            关键词匹配 + 超时判断
    ↓ _update_check_as_replied()                       更新 reply_checks + douyin_leads
Database
```

### 21.5 超时检测调用链

```text
定时调度器（scheduler/check_scheduler.py）或 POST /checks/run
    ↓
reply_checker.run_checks()
    ↓ 查询所有 pending 状态的 reply_checks
    ↓ 检查 now > reply_deadline
    ↓ 更新为 timeout
    ↓ 同步更新 douyin_leads 状态
Database
```

### 21.6 React 线索同步调用链

```text
React LeadsManagement「同步」按钮
    ↓ syncDouyinLeads({ dryRun: true })
    ↓ axios POST /integrations/douyin/sync-leads
    ↓
auto_wechat integrations.py
    ↓ douyin_sync_service.preview_sync_leads()
    ↓ douyin_api_client.fetch_leads()
    ↓
douyinAPI GET /leads
    ↓
返回 SyncResponse（预览 or 写库）
    ↓
React 刷新列表（fetchLeads + fetchStaffList + fetchSummary）
```

------

## 22. MVP 成功标准

### 22.1 PASS 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  主机微信 B 在 14:00 ~ 14:10 期间收到了销售A发送的"收到，已添加微信"

预期结果：
  检测结果 = PASS
  reply_checks.check_status = "replied"
  reply_checks.is_effective = 1
  douyin_leads.status = "replied"
```

### 22.2 TIMEOUT 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  14:10 后主机微信 B 仍未收到销售A的有效确认消息

预期结果：
  检测结果 = TIMEOUT
  reply_checks.check_status = "timeout"
  douyin_leads.status = "timeout"
```

------

## 23. 当前阶段不关注

以下能力在当前阶段明确**不做**：

- **不检测销售和客户的聊天记录**
- **不判断客户是否回复**
- **不分析销售对客户的沟通质量**
- **不自动给客户发消息**
- 不做群发
- 不做复杂 CRM
- 不反编译或修改小猫AI员工闭源代码
- AI 自动回复
- Agent
- RAG
- 微信数据库读取/解密
- 企业微信 DLL 注入
- 小猫AI员工集成
- 权限系统
- 多租户

------

## 24. 重要约束

任何后续开发必须遵守：

1. **优先复用**现有 FastAPI、数据库、服务层代码
2. **禁止推翻**现有 MVP 重构
3. **禁止重新设计**数据库
4. **禁止引入**复杂架构
5. **遵循**先验证业务闭环，再接入真实微信，最后扩展 AI 能力
6. **禁止使用**：微信数据库解密、DLL 注入、微信协议逆向
7. **优先使用**：UI Automation、视觉识别、OCR

------

## 25. 开发原则

- 先做最小验证，不做大而全
- 优先跑通一条线索的完整检测链路
- 规则判断优先，AI 判断后置
- 先保证可解释，再追求自动化程度
- 所有外部软件交互都要封装，避免业务逻辑散落
- 每一步都要保留日志

### 上游系统原则

禁止：

- SQLite 文件共享
- 数据库直读
- 人工同步数据库

必须：

- HTTP API 通信

### 本地测试原则

开发阶段：

不得连接生产 douyinAPI。

必须支持：

- Mock 数据
- dry_run
- 本地 SQLite

### 前端策略

React 项目（`E:\work\project\react`）是最终交付界面。

不要新建第二套前端。

开发方式：React 页面逐步替换 Mock 数据，接入 auto_wechat 和 douyinAPI 真实接口。

当前进展：LeadsManagement 页面已完成真实 API 接入，不再使用 Mock 数据。API 层架构稳定，后续页面可复用。

------

### 经验教训

#### P0-4A 调试经验（2026-06）

P0-4A / P0-5A 调试暴露出以下问题，已固化为项目规则：

```text
1. 旧 exe 未更新导致现象与代码不一致
   → 修复前必须确认运行的是最新代码/exe

2. 前端新版调用 Agent 旧版接口
   → 修复前必须确认前后端版本一致

3. 搜索框验证误判（UIA 控件定位不稳定）
   → 修复前必须确认真实调用链和失败层级

4. 真实调用链不清导致修复方向偏移
   → 修复前必须先做代码探索，确认完整调用链

5. 日志不足导致无法远程诊断 exe 问题
   → 高风险逻辑必须写充足日志

6. 假设旧代码有 bug 而不加验证
   → 修复前必须确认现象来自真实代码逻辑
```

已固化规则（详见 02_EXECUTION_RULES.md）：
- **#17 BUG 修复前置探索原则**：修复 bug 前必须先探索代码，确认真实调用链、失败层级、失败输入输出、是否来自旧版本/缓存
- **#18 修复计划审查前置条件**：修复计划执行前必须澄清修改范围、是否引入新 bug、是否导致回归、需要哪些测试和安全门禁
- **#19 高风险代码日志原则**：微信自动化、OCR、前台焦点、联系人验证、粘贴/发送门禁等高风险逻辑必须强制写日志，包含 stage、输入摘要、failure_stage

测试规则补充（详见 03_TESTING_RULES.md）：
- **#18 BUG 修复回归测试原则**：修复 Bug 必须补充回归测试或明确说明无法自动测试
- **#19 高风险逻辑日志验证原则**：高风险场景代码修改必须验证日志输出

------

## 26. 禁止事项

- 禁止反编译 `.pyd` 文件
- 禁止修改小猫AI员工安装目录
- 禁止把 MVP 写成完整 CRM
- 禁止一开始就接复杂大模型 Agent
- 禁止没有证据就输出确定性结论
- 禁止绕过微信/企业微信安全机制
- 禁止做骚扰、群发、自动营销能力

------

## 27. 已知环境问题

### React TypeScript 配置

时间：2026-06-09

现象：

VSCode 提示：

Option 'baseUrl' is deprecated.

并建议：

ignoreDeprecations = 6.0

实际情况：

项目 TypeScript 编译器不支持 6.0。

正确配置：

ignoreDeprecations = 5.0

验证方式：

npm run build

如 build 成功则配置正确。

禁止根据 VSCode 提示自动修改为 6.0。

### React tsconfig.json 修改记录

时间：2026-06-09

文件：`E:\work\project\react\tsconfig.json`

用户手动修改（非 AI 修改）：

- 添加了 `ignoreDeprecations = 6.0`
- 注：AI 不应修改此文件，保持用户手动配置

### 局域网访问配置

时间：2026-06-09

后端启动：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

前端启动：

```bash
cp .env.lan .env.development   # 临时切换为局域网地址
npm run dev -- --host 0.0.0.0 --port 5173
```

局域网 IP：`192.168.110.113`

CORS 已包含局域网地址（`app/main.py`）。

注意：`.env.development` 已恢复为本地地址 `http://127.0.0.1:9000`。局域网访问需手动切换为 `.env.lan` 内容。

### 本地 Agent 配置

时间：2026-06-10

本地 Agent 名称：**小高AI微信助手**（禁止使用"萌猫微信助手"）

exe 路径：`E:\work\project\auto_wechat\dist\小高AI微信助手\小高AI微信助手.exe`

监听地址：`127.0.0.1:19000`（不应监听 0.0.0.0）

打包脚本：`scripts/build_local_agent_exe.ps1`（PyInstaller onedir）

React 本机 Agent 面板直连 `127.0.0.1:19000`，不走 VITE_API_BASE_URL。

React 离线提示："未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手"

虚拟机/测试电脑默认无源码，不能以"运行 python 命令"作为验收前提。

---

## 28. GMP Webhook 直连接入现状

时间：2026-06-13

auto_wechat 已具备直接接收抖音/GMP 私信事件回调的能力，不再强依赖 douyinAPI 作为中间层。本章记录当前线上联调确认的最终链路、鉴权策略与事件处理规则。

### 28.1 当前最终链路

```text
抖音平台 / GMP 私信事件
    ↓
https://callback.misanduo.com/webhook/douyin
    ↓
宝塔整站反代（callback.misanduo.com → http://127.0.0.1:9000）
    ↓
http://127.0.0.1:9000/webhook/douyin
    ↓
auto_wechat 旧路径兼容路由（douyin_webhook_legacy）
    ↓
_handle_douyin_webhook（共享处理函数）
    ↓
process_webhook_event
    ↓
douyin_webhook_events（事件日志） + DouyinLead（线索入库）
```

### 28.2 正式 callback_url（保持不变）

事件回调链接保持：

```text
https://callback.misanduo.com/webhook/douyin
```

**禁止改成**：

- ❌ `https://callback.misanduo.com/integrations/douyin/webhook`
- ❌ `https://douyinapi.misanduo.com/...`
- ❌ `http://127.0.0.1:9000/...`

客户原地址 `https://callback.misanduo.com/webhook/douyin` 必须保持不变，由 auto_wechat 的 `/webhook/douyin` 兼容入口承接。

### 28.3 双入口说明

| 路径 | 角色 | 说明 |
|------|------|------|
| `POST /webhook/douyin` | 客户旧路径兼容入口 | GMP 实际推送目标，宝塔整站反代到此 |
| `POST /integrations/douyin/webhook` | 内部/新路径入口 | 内部联调与测试用，行为与旧路径完全一致 |

两个入口复用同一个 `_handle_douyin_webhook()` 共享函数，验签、解析、幂等、线索写入行为完全一致。日志通过 `source_path` 区分入口。

### 28.4 授权返回链接（与事件回调无关）

授权流程使用的返回链接：

```text
https://douyinapi.misanduo.com/auth/callback
```

这是授权流程的 redirect/callback，**不等同于事件回调 webhook**。本次修复只确认了事件回调链路，不代表 `/auth/callback` 已经迁移到 auto_wechat。后续如涉及重新授权、换号、重新生成二维码，需要单独探索并迁移授权回调逻辑。

### 28.5 鉴权策略说明

**当前配置**：

```env
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

| 值 | 含义 |
|----|------|
| `false`（默认） | 入站 webhook 不强制签名校验，符合当前 GMP 私信事件回调业务确认 |
| `true` | 启用 `X-Auth-Timestamp` + `Authorization` 签名校验，主要用于兼容测试或未来安全策略调整 |

**必须遵守**：

1. 入站 webhook（GMP 推送到 callback_url）默认 `false`，不强制鉴权。
2. 文档中的鉴权章节（`X-Auth-Timestamp` + `Authorization`）适用于**外部系统主动调用 GMP OpenAPI**，**不允许**套用到 GMP 推送 callback_url 的入站 webhook 上。
3. `verify_signature` 逻辑保留，但通过 `DOUYIN_WEBHOOK_AUTH_REQUIRED` 开关控制，不删除。
4. 不允许后续再把入站 webhook 默认改回强制鉴权，除非有明确的安全策略变更审批。

### 28.6 事件处理规则

| 事件类型 | 行为 |
|----------|------|
| `im_receive_msg` | 创建/更新 `DouyinLead`（pending 更新，非 pending 跳过） |
| `im_send_msg` | 记录到 `douyin_webhook_events`，但不创建线索（`lead_action=not_lead_event`） |
| `im_enter_direct_msg` | 记录到 `douyin_webhook_events`，但不创建线索 |
| 重复事件 | 通过 `event_key`（SHA256 幂等键）去重，不重复创建线索，返回原始 event_id |

**日志规范**：

- 所有日志包含 `source_path` 和 `webhook_auth_required=true/false`
- 不打印 secret
- `from_user_id` 只打印前 8 字符 + `...`
- 不打印完整敏感 payload

### 28.7 已验证结果（线上联调）

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | `POST /webhook/douyin` 已部署到 OpenAPI | ✅ |
| 2 | `https://callback.misanduo.com/webhook/douyin` 保持客户原地址不变 | ✅ |
| 3 | 宝塔整站反代 `callback.misanduo.com → http://127.0.0.1:9000` | ✅ |
| 4 | `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 生效 | ✅ |
| 5 | 真实/有效 payload 返回 200 | ✅ |
| 6 | `im_receive_msg` 已创建 `DouyinLead`（lead_id=4, customer_name=正本清源, lead_action=created） | ✅ |
| 7 | `im_send_msg` / `im_enter_direct_msg` 记录事件但不创建线索 | ✅ |
| 8 | 无效空 body 返回 400（正常行为，非鉴权问题） | ✅ |

**日志示例结论**：

```text
webhook 鉴权已关闭: source_path=/webhook/douyin, webhook_auth_required=false
webhook 接收成功: event=im_receive_msg
webhook 新建线索: lead_id=4, customer_name=正本清源
POST /webhook/douyin HTTP/1.1 200 OK
```

### 28.8 dev 阶段遗漏问题复盘

**问题**：

dev 阶段误将文档中的鉴权章节理解为入站 webhook 也必须强制鉴权，导致 auto_wechat 初版对 `/webhook/douyin` 和 `/integrations/douyin/webhook` 强制要求 `X-Auth-Timestamp` 与 `Authorization`。

**影响**：

如果 GMP 真实回调不带签名头，auto_wechat 会返回 401，导致真实私信事件无法入库。

**原因**：

未提前确认文档鉴权适用范围，没有区分：

- 外部系统主动调用 GMP API（需要鉴权）
- GMP 主动推送事件到 callback_url（不需要鉴权）

**修复**：

新增 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`，默认关闭入站 webhook 强制鉴权；保留 `true` 模式用于测试和未来兼容。

**当前状态**：已修复并通过线上日志验证。

### 28.9 后续待办

| 优先级 | 待办 | 说明 |
|--------|------|------|
| P1 | 观察真实私信回调稳定性 | 持续观察 webhook event 与 DouyinLead 入库情况 |
| P1 | 服务器 `.env` 显式保留 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` | 防止误改回强制鉴权 |
| P2 | 处理旧 8081 douyinAPI 残留同步链路 | `/integrations/douyin/sync-leads` 仍调用 `http://127.0.0.1:8081/leads`；若 douyinAPI 废弃需禁用该入口（建议新增 `DOUYIN_SYNC_LEGACY_API_ENABLED=false`，关闭时返回 410） |
| P2 | 授权返回链接 `/auth/callback` 迁移 | 指 douyinAPI 旧私信授权回调，**与 0.18 抖音客服账号 OpenAPI 授权是不同链路**；是否迁移到 auto_wechat 后续单独探索，不与本次事件回调混淆 |

------

# P0-DEV-E1 原始事件 / invalid 只读查询接口完成记录

更新时间：2026-06-15

完成状态：P0-DEV-E1 已完成。

已新增只读接口：

1. `GET /webhook-events`
2. `GET /webhook-events/{event_id}`

关键结论：

1. 数据来源为现有 `douyin_webhook_events`。
2. 当前不新增字段、不迁移数据库。
3. 当前通过解析 `raw_body` 和现有字段推导事件展示状态：
   - `duplicate_event`
   - `valid_lead`
   - `non_lead_event`
   - `invalid_content`
   - `non_text_message`
   - `invalid_contact`
   - `unknown`
4. `/leads` 保持只展示有效线索。
5. invalid / 原始事件通过 `/webhook-events` 单独展示。
6. 全量测试结果：`722 passed, 149 warnings`。
7. warnings 为既有 deprecation warnings。
8. 本轮未修改 webhook 验签、webhook 写入、contact_extractor、有效线索生成规则、Local Agent、数据库模型、依赖。

------

# P0-DOC-GAP-1 / P0-DEV-PLAN-1 最终 PRD 冻结后项目状态同步

更新时间：2026-06-15

本轮为第一阶段（只读盘点 + 文档落盘），未修改任何业务代码、数据库模型、配置、测试、前端或 Local Agent。

本轮交付：

1. 新增 `docs/ai/01_product_prd/PRD_GAP_ANALYSIS.md` — PRD 差距分析（✅ / ⚠️ / ❌ / ⛔ 四级 + HIGH/MEDIUM/LOW 风险）。
2. 新增 `docs/ai/02_architecture/P0_DEV_PLAN.md` — 第一版分阶段开发计划（P0~P12 + DB-MIG 前置阶段）。
3. 本节（追加到 05_PROJECT_CONTEXT.md）。

### A. 当前真实调用链总结

#### A.1 Webhook 主线（已部署线上）

```text
抖音 GMP 私信事件
  ↓ https://callback.misanduo.com/webhook/douyin
  ↓ 宝塔整站反代 → http://127.0.0.1:9000
POST /webhook/douyin （routers/integrations.py 的 legacy_webhook_router）
  ↓ _handle_douyin_webhook()
  ↓ verify_signature()  ← 受 APP_ENV + DOUYIN_WEBHOOK_AUTH_REQUIRED 控制，线上为 false
  ↓ douyin_webhook.process_webhook_event(db, payload)
      ├─ build_event_key() → event_key 幂等键
      ├─ find_existing_event() → 重复事件：写 is_duplicate=1，返回 success
      └─ im_receive_msg：
           ├─ normalize_message_text() 取私信文本
           ├─ is_text_message() 过滤非文本
           ├─ contact_extractor.extract_contacts_from_text() 提取手机号/微信号
           ├─ matched → upsert_lead_from_webhook() → douyin_leads（status=pending）
           └─ not_matched → 仅写 douyin_webhook_events（invalid）
  ↓ 返回 200
```

证据：`app/integrations/douyin_webhook.py:328-438`、`app/routers/integrations.py`。

#### A.2 分配 → 通知 → 检测（Local Agent 主线，P1-AUTO-1）

```text
assign_lead() / auto_assign_next()
  → douyin_leads.status=assigned + 创建 reply_checks(pending)
  ↓
create_wechat_task(notify_sales, target=Aw3, mode=paste_only)
  ↓ React → 127.0.0.1:19000/agent/tasks/poll-and-execute (task_id 指定)
  ↓ 小高AI微信助手.exe：open_chat_by_nickname → OCR verify → paste_only（sent=false）
  ↓ submit_wechat_task_result(pasted=true)
  ↓ _auto_create_detect_reply_task() → 自动建 detect_reply task
  ↓ React → poll-and-detect (task_id 指定) → read_recent_messages → 关键词命中
  ↓ submit_wechat_task_result(detected_status=replied)
  ↓ _update_check_and_notification_on_replied() → reply_checks.replied + lead.replied
```

#### A.3 超时

```text
check_scheduler（后台线程，间隔 check_interval_minutes 默认 5min）
  ↓ reply_checker.run_checks() → pending reply_checks 超 reply_deadline → timeout
  ↓ douyin_leads.status=timeout
```

注意：当前只有"标记 timeout"，无任何重分配逻辑。

#### A.4 微信操作发生位置

9000（auto_wechat）不直接操作微信；所有微信 UI 自动化发生在客户机本地 127.0.0.1:19000（小高AI微信助手.exe）。`AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT` 默认 0，旧 9000 直操微信的调度器已禁用。

### B. 当前最大阻塞点

1. **数据库迁移体系（HIGH，P2-A 已完成、P2-B/C 待确认执行）**：当前使用 `Base.metadata.create_all`，对已存在表不会自动 ALTER；已有数据的主库新增字段会导致旧库缺列报错。
   - **已完成**：DB-MIG 迁移方案（`docs/ai/03_data_and_migration/14_DB_MIGRATION_PLAN.md`）；P2-A 迁移脚本骨架（`migrations/migrate_sqlite.py` + `versions/0001_prd_base_fields.sql`），已用 `sqlite3 backup()` 生成副本并完成 dry-run / apply / 幂等验证，13 项迁移测试通过，全量回归 748 passed，未改 `models.py`、未碰主线库结构。
   - **待确认（执行顺序已调整）**：先 **P2-C**（主线 `data/auto_wechat.db` 正式迁移，需 `--allow-mainline`），再 **P2-B**（`models.py` 字段补齐）。
   - **顺序说明（2026-06-15 调整）**：P2-C 先于 P2-B。原因：若先改 `models.py` 而主线库未迁移，SQLAlchemy 模型会认为新字段已存在但实际表无此列，运行接口 / 查询时缺列报错。先迁移主线库落出新列，再补 `models.py`，确保数据库结构与模型同步、不领先。
   - **验收口径（WAL 模式，重要）**：`data/auto_wechat.db` 是开发测试库（非生产库），SQLite 处于 WAL 模式。`.db` 文件 hash / mtime **不能**作为「主线未变化」的唯一证据——WAL checkpoint 会把历史 `-wal` 帧合并进主 `.db`，导致 hash 变化但业务数据 / 结构完全不变（P2-A 实测确认，详见 `docs/ai/03_data_and_migration/14_DB_MIGRATION_PLAN.md` §0c-1、`docs/ai/02_architecture/P0_DEV_PLAN.md` §1.5）。后续 P2-C 验收**必须以结构对比 + 数据语义对比为主**（`PRAGMA table_info` / 行数 / 关键字段抽样 / `reassign_count` 默认值 / 新增列存在性），文件 hash 仅作辅助参考。P2-C 前如需收缩 WAL，单独确认后再执行 checkpoint，迁移阶段不主动 checkpoint。

2. **生产验签切换（HIGH）**：线上 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`，且 `APP_ENV` 实际值、GMP 真实回调是否带签名头需复核（第 28 章历史结论：线上不带签名头）。切换 production + DY_SECRET_KEY 前必须确认，否则会导致线上 401、事件不入库。

3. **状态机重构风险（HIGH）**：`douyin_leads.status` 当前注释仅 `pending/assigned/replied/timeout/closed`，PRD §10 要求 13 个内部状态 + 4 个对外状态映射。重构影响 webhook 写入、assign、scheduler、wechat_task、reports、前端展示多处硬编码，回归面大。

4. **NewCarProject 字段待确认（MEDIUM）**：token / cookie / roles / merchant_id 的具体字段结构需与 NewCarProject 同事确认。第一版只能预留骨架与字段，不能实现完整识别逻辑。

### C. 命名映射说明（重要）

PRD 第 7 节使用概念名 `lead_source_events` 指代"原始线索事件域"。

当前真实代码中承担该职责的物理表是 `douyin_webhook_events`。

两者是同一职责域的不同命名。

第一版结论：

1. 第一版**不重命名** `douyin_webhook_events` 为 `lead_source_events`。
2. 重命名属于表结构变更，会引入不必要的数据库迁移和历史数据风险。
3. 在文档、接口注释、状态映射中统一用「`douyin_webhook_events`（语义承接 PRD 的 `lead_source_events` 原始事件域）」表述。
4. 后续产品化稳定后，若确有必要做物理表名迁移，必须单独出迁移技术方案，经确认后再执行。

该结论与本节 0.10、`docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md` 既有结论保持一致。

### D. 下一阶段节奏（用户已批准）

```text
P0 文档落盘（本轮，已完成）
  ↓
数据库迁移体系方案设计（DB-MIG，独立前置阶段）
  ↓
P2 models 字段补齐
  ↓
webhook 幂等和验签规范化
  ↓
状态机重构
  ↓
销售导入 / 重分配 / 人工处理 / 导出
```

在 DB-MIG 方案未确认前，以下全部暂不批准：

- 数据库字段修改
- 状态机重构
- Webhook 改造
- Excel 导出
- 前端开发
- Local Agent 改造

------

# P0-DOC-AGENT-BOUNDARY-1 三服务边界与一期需求差距固化

更新时间：2026-06-18

本节基于《小高AI系统需求文档（一期）》与现有 `auto_wechat` 代码只读探索结果补充。当前只是文档固化，不代表进入业务代码开发阶段。

## 1. 当前 auto_wechat 三服务边界

```text
9000 主服务（auto_wechat）
  职责：抖音 webhook、原始事件、有效线索、销售、微信任务、回复检测、后台业务 API
  边界：不直接执行本机微信 UI 自动化；不承载未来 LangChain / Agent Tools 编排

19000 Local Agent（小高AI微信助手）
  职责：运行在客户 Windows 本机，执行本机微信 UI 自动化、任务轮询、只读回复检测、paste_only 任务执行
  边界：只负责本地微信检测 / 任务执行；不是 LLM Agent，不负责 RAG、LLM 回复建议或工具编排

9100 apps/xg_douyin_ai_cs
  职责：抖音AI客服、抖音会话聚合、RAG、LLM 回复建议
  边界：未来 LangChain / Agent Tools / Agent Runtime 的推荐落点；不操作微信；不直接承担 9000 主业务数据库职责
```

必须明确区分：

1. `Local Agent` 不是 LLM Agent。
2. `19000` 的 Agent 是本地微信执行代理，核心能力是 Windows 微信 UI 自动化。
3. `9100` 的 Agent Runtime 才是未来 LangChain / tools 编排位置。
4. 如果 `9000` 后续需要 AI 回复能力，应通过 HTTP 调用 `9100`，不直接依赖 LangChain 或 9100 内部实现。

## 2. 当前一期需求差距记录

| 模块 | 当前判断 | 说明 |
|------|----------|------|
| 登录 / 权限 / 商户隔离 | 部分偏缺失 | 已有部分商户、账号、绑定概念和后台页面，但未形成完整 NewCarProject 登录、权限、菜单、角色、商户隔离闭环。 |
| 抖音AI客服 | 部分具备 | `9100 apps/xg_douyin_ai_cs` 已具备抖音会话、RAG、LLM 回复建议、人工确认工作台雏形；自动发送仍关闭。 |
| AI小高线索 | 部分具备 | `9000` 已有抖音 webhook、原始事件、有效线索、联系方式提取、线索列表；完整扫码授权、商户级生产化仍不足。 |
| 抖音企业号管理 | 部分具备 | 已有抖音账号授权、账号 Agent 绑定、工作台能力；完整企业号管理、权限隔离、续授权、异常处理仍不足。 |
| AI小高助手 | 部分具备 | 已有线索分配、微信任务、Local Agent、销售回复检测闭环；生产级多任务队列、配置化策略、稳定重分配仍不足。 |
| AI小高智能体 / 知识库 | 部分具备 | 9100 已有 RAG、商户提示词、账号 Agent 绑定雏形；智能体 CRUD、知识库管理、embedding 管理、商户隔离仍需补齐。 |
| 小高算力 | 缺失 | 当前仅有少量后台占位或配置雏形，未形成套餐、消耗、充值、账单、算力展示闭环。 |
| 后台管理 | 大多缺失 | 商户、管理员、禁用词、回访提示词、套餐等多为页面或粗粒度能力，尚未形成完整管理闭环。 |

## 3. 已验证主链路必须保留

以下链路是当前系统已形成价值的基础能力，后续一期 / 二期开发不得误删或以新架构替代掉：

```text
抖音 webhook
  → douyin_webhook_events 原始事件
  → douyin_leads 有效线索

抖音会话聚合
  → 9100 RAG / LLM
  → AI 回复建议
  → 人工确认

线索分配
  → 微信任务
  → 19000 小高AI微信助手 Local Agent
  → 检测销售微信回复
  → 9000 回写

React
  → 9000
  → 19000
  → 微信
  → 9000
  → React
```

其中 `9100` 抖音AI客服链路与 `19000` 微信 Local Agent 链路是两个不同方向的能力：前者是 AI 回复建议与未来 Agent Tools 编排，后者是客户本机微信执行代理。

## P1-DY-ACCOUNT-AGENT 一期完成记录

更新时间：2026-06-18

### 1. 阶段结论

`P1-DY-ACCOUNT-AGENT` 一期链路已完成并验收通过：

```text
前端企业号绑定控件
  → 9000 权威绑定表
  → 9000 读取真实 AiAgent
  → 9100 使用真实 agent_config 生成回复建议
```

### 2. 核心提交

- `d33620d78520ba743c4eeee3ef4158a27fa98513`：实现抖音企业号绑定智能体后端基础能力
- `9dc3b2a2318cf890788ee44673ca6f16ac977d31`：接入抖音企业号绑定智能体前端控件
- `8d4fc40f57b51121a5b86dcfa4195dbc138045b4`：解除 9100 正式回复建议对 mock 绑定依赖
- `fc8c1bebc23901767bf3662c2d68e5787c716d63`：9000 代理注入真实智能体配置到 9100

### 3. 关键边界

- 9000 是绑定权威源。
- 9000 负责校验企业号归属、授权状态、Agent 归属、Agent active 状态与绑定关系。
- 9000 不信任前端传入的 `merchant_id`。
- 9000 不信任前端传入的 `agent_config`。
- 9000 校验通过后读取真实 `AiAgent`，再注入可信 `agent_config` 给 9100。
- 9100 不直接读取 9000 数据库。
- 9100 不再用 mock `ACCOUNT_AGENT_BINDINGS` 拦截正式链路。
- 9100 仅消费 9000 注入的可信 `agent_id` / `agent_config`。
- `mock_workbench_service` 仅保留 demo 用途。

### 4. 安全边界

- `auto_send=false`，9000 和 9100 双保险。
- 不自动发送微信。
- 不自动发送抖音私信。
- 不引入 LangChain。
- 不接 Agent tools。
- 取消授权、删除企业号、Agent disabled 或 deleted 后不得继续生成建议。

### 5. 后置项

- 真实上游取消授权仍未接入，当前 `upstream_cancel_supported=false`。
- RAG scope 当前仍偏 `tenant_id + merchant_id + douyin_account_id`，后续可升级为 `merchant_id + account_open_id + agent_id`。
- 真实联调仍需要有效授权企业号、真实 `AiAgent`、真实会话数据。
- 一期不建议继续扩展 LangChain、Agent tools 或自动发送。

------

# P1-REQ-GAP-1 一期需求差异探索与 P0 风险复核

更新时间：2026-06-18

正式差异报告已固化到：`docs/ai/01_product_prd/P1_REQUIREMENT_GAP_ANALYSIS.md`。

本轮只做文档固化和 P0 技术方案复核，不修改业务代码、不执行数据库迁移、不启动真实微信/抖音发送、不调用真实 LLM/Embedding、不接真实支付。

## 1. 当前结论摘要

1. `9000` 主后端已经具备线索、销售分配、微信任务、回复检测、抖音企业号绑定智能体、小高算力后端和 NewCarProject 鉴权门面的部分能力。
2. `9100` 抖音 AI 客服已经具备 RAG/LLM 回复建议和多账号工作台底座，但 `auto_send=false` 必须保持，不是自动发送私信系统。
3. `19000` 小高AI微信助手是 Windows 本地微信 UI 辅助与只读检测代理，不是完整规则引擎，也不是 LLM Agent。
4. `frontend` 已有主要页面，但登录、路由级权限、小高算力前端、超管多数页面仍未形成真实闭环。

## 2. P0 风险

1. 登录与权限未完全真实接入 NewCarProject：`app/auth/newcar_client.py` 当前是门面和 mock，上游字段、token/cookie 规则、权限字典和过期时间仍待外部契约确认。
2. 前端路由级权限隔离不足：`frontend/src/App.tsx` 只注册少量路由，多数页面仍依赖 `Index.tsx` 内部 `activeNav` 切换，`SideNav.tsx` 主要按本地 `role` 控制菜单。
3. `douyin_leads` 缺 `merchant_id` / `tenant_id`：线索列表、详情、分配和报表无法形成强多商户隔离。相关设计必须先完成，不得直接写 migration。
4. 小高算力后端已具备一期接口，但 `frontend/src/pages/ComputeCenter.tsx` 与 `frontend/src/pages/SuperComputeConfig.tsx` 仍是“真实接口暂未接入”占位。
5. 超管功能多数未落后端：商户管理、禁用词、回访提示词、管理员账号等页面不能按页面存在判断为已实现。

## 3. 当前安全边界

1. 抖音 AI 客服继续保持 `auto_send=false`，所有 AI 回复只作为建议或人工确认来源。
2. 微信链路继续保持 `sent=false`、`paste_only`、`read_only`、`task_id` 指定执行和人工确认边界。
3. 小高算力继续不做真实支付；`/compute/recharge-orders` 当前只是 mock 订单，不实际到账。
4. 9000 继续作为抖音企业号绑定和智能体配置的可信来源，不信任前端传入 `agent_config`。
5. 生产 webhook、认证、权限、数据库迁移均属于高风险区，后续开工前必须先确认契约、迁移和回滚方案。

------

# P4-E / P5-E 抖音AI客服 RAG 分类知识库闭环验收与部署检查

更新时间：2026-06-20

验收文档：

1. `docs/ai/05_acceptance/P4_DY_AI_CS_RAG_KNOWLEDGE_ACCEPTANCE.md`
2. `docs/ai/05_acceptance/P4_DY_AI_CS_RAG_DEPLOY_CHECKLIST.md`
3. `docs/ai/05_acceptance/P5_DY_AI_CS_RAG_E2E_ACCEPTANCE.md`

## 1. 当前完成结论

1. `9100` RAG 已完成真实向量检索：query embedding + `knowledge_chunks.embedding_json` 余弦相似度排序，lexical fallback 保留。
2. `9100` 已具备 `knowledge_categories`、`knowledge_documents.category_key`、`knowledge_chunks.category_key` 分类数据模型。
3. `9100` `/rag/search` 已支持 `category_ids` / `category_keys`，并在 SQL 候选读取层过滤。
4. `9000` 已具备 `agent_knowledge_categories` 绑定模型和服务层能力。
5. `9000` reply-suggestion 代理已可信注入 `agent_config.allowed_category_keys`，默认包含 `base`。
6. `9100` reply-suggestion 已消费 `allowed_category_keys`，并用于 `RagSearchRequest(category_keys=...)`。
7. `9000` 已提供 Agent 分类绑定 API：`GET /knowledge-categories`、`GET/PUT /agents/{agent_id}/knowledge-categories`。
8. 前端 Agent 编辑页已支持知识分类多选，base 默认启用且不可取消。
9. `9000` 已提供 RAG 文档创建和训练可信代理：`POST /integrations/douyin-ai-cs/rag/documents`、`POST /integrations/douyin-ai-cs/rag/train`。
10. 前端 RAG 文档创建和训练已改走 9000 可信代理，不再提交 `tenant_id` / `merchant_id` / `douyin_account_id`。
11. `9000` 已提供 `knowledge_categories` 主表，`GET /knowledge-categories` 返回 base + 当前商户 active 分类，`POST /knowledge-categories` 支持创建 merchant 分类。
12. 前端已新增“知识分类”页面，支持列表展示和创建 merchant 分类。
13. 前端已新增“知识库”页面，支持创建知识文档和手动训练当前分类；暂不支持文档列表、编辑、删除。
14. Phase 5-E-F 运行态 E2E 已通过：创建/复用分类、写入文档、训练、Agent 绑定分类、reply-suggestion 分类召回、`auto_send=false` 均已确认。

## 2. 当前真实闭环

```text
前端 Agent 分类多选
  -> 9000 agent_knowledge_categories
  -> 9000 reply-suggestion 注入 allowed_category_keys
  -> 9100 reply-suggestion
  -> RagSearchRequest(category_keys=...)
  -> 9100 SQL 层过滤 knowledge_chunks.category_key
  -> 向量检索 / lexical fallback
  -> RAG context 注入 LLM
  -> 返回 AI 回复建议 auto_send=false
```

```text
前端 RAG 文档创建 / 训练
  -> 9000 可信代理
  -> 9000 校验 RequestContext.merchant_id、account_open_id 归属、category_key 可见性
  -> 9000 显式构造 scope payload
  -> 9100 /rag/documents 或 /rag/train
  -> documents/chunks 写入 category_key
```

## 3. 当前边界

1. `9000` 是企业号、Agent、商户、Agent 分类绑定的权威源。
2. `9100` 只负责 RAG/LLM，不反查 9000 数据库。
3. `9000` 不直连或反查 9100 SQLite。
4. 前端不向 reply-suggestion 传 `allowed_category_keys`。
5. 前端不向 RAG documents/train 传可信 scope 字段。
6. `searchRag()` 如仍直连 9100，只能作为内部调试能力，不是正式产品入口。
7. `19000` 小高AI微信助手不参与本链路。
8. `auto_send=false` 必须保持，当前不是自动发送私信系统。

## 4. 尚未完成 / 后续增强

1. 文档列表、详情、编辑、删除仍暂缓。
2. chunk 展示和正式搜索入口仍暂缓。
3. `p5_blocked_test` 负向分类边界运行态验收未单独执行。
4. `9000` / `9100` conversation_id 数字型契约差异待后续收敛；字符串会话触发 reply-suggestion 时 9100 会返回 422，改用数字型 `conversation_id=1` 已通过。
5. NewCarProject 菜单、权限、套餐消耗与知识库管理入口的最终契约未完成。

## 5. 部署前必读

部署前必须按 `docs/ai/05_acceptance/P4_DY_AI_CS_RAG_DEPLOY_CHECKLIST.md` 检查：

1. 9000 / 9100 数据库迁移是否已执行。
2. 9000 / 9100 / frontend 配置是否指向正确环境。
3. 分类、账号归属、Agent 绑定、文档写入、训练、回复建议是否完成端到端验收。
4. 前端是否仍不传可信 scope 字段。
5. `auto_send=false` 是否在 9000 和 9100 双侧保持。

------

# P6-G 抖音AI客服结构化回复建议闭环验收

更新时间：2026-06-19

验收文档：

1. `docs/ai/05_acceptance/P6_DY_AI_CS_STRUCTURED_REPLY_ACCEPTANCE.md`

## 1. 当前完成结论

Phase 6 已完成“结构化智能回复建议 + 人工确认发送”闭环：

1. Phase 6-A 完成 LLM + RAG 智能客服自动回复能力落地前只读审计，确认当前不适合直接自动发送。
2. Phase 6-B 在 9100 实现 RAG + LLM 结构化回复决策，新增 `intent`、`lead_level`、`tags`、`manual_required_reason`、`risk_flags`、`rag_sources`、`decision_version` 等字段。
3. Phase 6-C 在 9000 reply-suggestion 可信代理透传结构化字段，并继续强制 `auto_send=false`。
4. Phase 6-D 在前端工作台展示结构化智能回复决策，保留复制回复和人工确认发送。
5. Phase 6-E 完成托管模式 / 自动发送安全门禁只读审计，结论是不建议直接进入真实自动发送。
6. Phase 6-F-B 新增 `ai_reply_decision_logs`，记录 9100 原始响应、9000 最终安全后处理、RAG 来源、风险标记和 Agent 分类权限。

当前产品定位：

```text
结构化智能回复建议 + 人工确认发送
```

当前不是自动发送系统，`auto_send=false` 仍是强制安全边界。

## 2. 当前真实调用链

```text
前端工作台 DouyinAiCsWorkbenchPage
  -> 9000 reply-suggestion proxy
  -> 9000 校验权限、商户上下文、企业号和 Agent 绑定
  -> 9000 读取真实 AiAgent
  -> 9000 注入真实 agent_config / allowed_category_keys
  -> 9100 RAG + LLM
  -> 9100 结构化回复决策
  -> 9100 强制 auto_send=false
  -> 9000 强制 auto_send=false
  -> 9000 写 ai_reply_decision_logs
  -> 前端展示结构化回复建议
  -> 客服复制回复或人工确认发送
```

## 3. 当前结构化字段

reply-suggestion 当前可返回：

- `reply_text`
- `intent`
- `lead_level`
- `tags`
- `detected_vehicle`
- `detected_contacts`
- `manual_required`
- `manual_required_reason`
- `risk_flags`
- `rag_sources`
- `decision_version`
- `llm_used`
- `rag_used`
- `auto_send=false`

旧字段继续兼容：`confidence`、`source_chunks`、`warnings`、`agent_id`、`agent_name`、`agent_category` 等。

## 4. 当前安全边界

1. `9100` 只提供结构化建议，不决定真实自动发送。
2. `9000` 是可信代理和最终安全边界，最终响应必须强制 `auto_send=false`。
3. 前端不向 reply-suggestion 传 `auto_send`。
4. 前端不向 reply-suggestion 传 `allowed_category_keys`。
5. `allowed_category_keys` 只能由 9000 根据 Agent 分类绑定注入。
6. `agent_config` 只能由 9000 基于真实 `AiAgent` 构造。
7. 人工发送必须继续要求 `manual_confirmed=true`。
8. AI 回复决策日志写入失败不影响主链路返回。
9. 当前没有托管自动发送路径，没有自动发送按钮，没有自动发送接口放开。

## 5. AI 回复决策日志

`ai_reply_decision_logs` 用于后续 AI 回复记录查询、托管 dry-run、审计追溯和问题排查。

日志记录重点：

1. 9100 原始响应副本，便于追溯上游是否曾返回 `auto_send=true`。
2. 9000 最终安全后处理结果，最终 `final_auto_send=false`。
3. RAG 来源、风险标记、标签、人工确认原因和结构化决策版本。
4. `allowed_category_keys_json`，来源于 9000 注入值，不来自前端或 9100 response。

日志失败只能写 warning，不得污染用户响应。

## 6. 后续路线

建议后续按以下节奏推进：

1. Phase 7-A：AI 回复记录查询 API。
2. Phase 7-B：超级管理员 AI 回复记录页面。
3. Phase 7-C：托管配置表只读审计。
4. Phase 7-D：托管 dry-run，只记录将要发送的决策，不真实发送。
5. Phase 7-E：极小范围自动发送试点，暂缓。

后续在完成托管配置、dry-run、审计查询、频控、发送前二次读取最新消息、灰度和回滚机制前，不建议进入真实自动发送。

------

# P7-D 抖音AI客服 AI 回复记录闭环验收

更新时间：2026-06-20

验收文档：

1. `docs/ai/05_acceptance/P7_DY_AI_CS_REPLY_RECORDS_ACCEPTANCE.md`

## 1. 当前完成结论

Phase 7 已完成“AI 回复记录查询与商户侧只读页面”闭环：

1. Phase 7-A 完成 AI 回复记录查询 API 落地前只读审计，确认 `ai_reply_decision_logs` 现有字段足够支撑第一版商户侧查询。
2. Phase 7-B 在 9000 新增商户侧 AI 回复记录查询 API：`GET /ai-reply-decision-logs` 和 `GET /ai-reply-decision-logs/{log_id}`。
3. Phase 7-B 查询 API 已覆盖权限校验、商户隔离、分页、筛选、关键词查询、时间范围、JSON 容错和基础脱敏。
4. Phase 7-C-A 完成前端商户侧 AI 回复记录页面落地前只读审计，确定页面只读、挂在抖音AI客服模块附近。
5. Phase 7-C-B 新增商户侧 `AI回复记录` 页面，展示 AI 回复建议日志列表和详情，不提供任何发送入口。
6. Phase 7-D 完成闭环验收文档收口，归档 Phase 7-A 到 7-C-B 的 API、前端页面和安全边界。

当前产品定位：

```text
结构化智能回复建议 + AI 回复记录审计 + 人工确认发送
```

当前仍不是自动发送系统，`auto_send=false` 继续作为强制安全边界。

## 2. 当前真实调用链

```text
前端 AI回复记录页面
  -> 9000 GET /ai-reply-decision-logs
  -> 9000 校验 auto_wechat:douyin_ai_cs 权限
  -> 9000 使用 RequestContext.merchant_id 做商户隔离
  -> 查询 ai_reply_decision_logs
  -> 返回脱敏摘要列表
  -> 前端只读展示

前端 AI回复记录详情
  -> 9000 GET /ai-reply-decision-logs/{log_id}
  -> 9000 校验权限和 merchant_id 隔离
  -> 查询单条 ai_reply_decision_logs
  -> 返回脱敏详情，不返回 raw_response_json
  -> 前端只读详情弹窗
```

## 3. API 与页面边界

商户侧 API：

1. `GET /ai-reply-decision-logs`：列表查询，支持分页、关键词、`manual_required`、`intent`、`lead_level`、`rag_used`、`llm_used`、`risk_flag`、时间范围等筛选。
2. `GET /ai-reply-decision-logs/{log_id}`：详情查询，返回 `latest_message`、`reply_text`、结构化字段、RAG 来源、分类权限等审计信息。
3. 列表和详情均不返回 `raw_response_json` 给普通商户。
4. 前端传入的 `merchant_id` 被忽略，后端只使用 `RequestContext.merchant_id`。

商户侧页面：

1. 页面路由为 `/douyin-ai-cs/reply-records`，导航 key 为 `douyin-ai-cs-reply-records`。
2. 菜单名称为 `AI回复记录`，放在抖音AI小高客服附近。
3. 页面只读展示列表、筛选、分页和详情弹窗。
4. 详情弹窗只允许关闭类操作，不提供“发送”“使用该回复”“重新发送”“自动发送”等按钮。

## 4. 当前安全边界

1. 前端 AI 回复记录查询不传 `merchant_id`。
2. 前端 AI 回复记录查询不传 `auto_send`。
3. 前端 AI 回复记录查询不传 `allowed_category_keys`。
4. 9000 查询 API 始终按 `RequestContext.merchant_id` 过滤，商户不能查看其他商户日志。
5. 普通商户列表和详情均不展示 `raw_response_json`。
6. AI 回复记录页面只读，不修改日志，不触发发送。
7. 当前没有托管自动发送路径，没有自动发送按钮，没有自动发送 API 放开。
8. 抖音AI客服回复建议链路仍保持 `auto_send=false`，人工发送仍必须走人工确认边界。

## 5. 后续路线

建议后续按以下顺序推进：

1. 超管侧 AI 回复记录查询 API 和页面后置，避免第一版扩大权限面。
2. AI 回复记录导出、有效/无效标记、人工反馈等增强后置。
3. 托管 dry-run 后置，只记录“如果托管会如何决策”，不真实发送。
4. 自动发送继续暂缓；只有在完成托管配置、频控、审计、灰度、回滚和发送前二次读取最新消息门禁后，才允许进入极小范围试点。
# P2-C 9100 database factory 当前状态补充

任务：`P2-C-DB-9100-DATABASE-FACTORY-1`

当前已为 9100 `xg_douyin_ai_cs` 建立最小 database factory / runtime 抽象：

```text
apps/xg_douyin_ai_cs/rag/database.py
  - 继续作为 9100 RAG metadata 中心数据库入口。
  - 对外保留 database_path / connect / init_db。
  - 新增 get_database_runtime，从 RAG_DATABASE_URL 识别 backend 并脱敏展示。
  - SQLite 默认行为保持不变。
  - 未配置 RAG_DATABASE_URL 时继续兼容 XG_DOUYIN_AI_CS_DB_PATH。
  - PostgreSQL backend 仅识别、不连接；本轮不创建 async pool。
```

本轮仍未启用 PostgreSQL、未改 RAG 检索、未改 Milvus upsert / search、未改业务 SQL、未改表结构、未跑迁移、未改 9000。9100 后续 PostgreSQL 仍对应 `xg_douyin_ai_cs` database，未来通过 `RAG_DATABASE_URL` 接入；async pool 留到后续任务。

最终生产目标补充：

1. 宝塔部署最终不再使用 SQLite。
2. 9000 / 9100 metadata 全部使用 Docker Compose 中的 PostgreSQL 容器。
3. 一个 PostgreSQL 容器实例，两个 database：`auto_wechat`、`xg_douyin_ai_cs`。
4. 数据库访问最终需要支持 QPS600。
5. 后续必须走 async PostgreSQL driver、连接池、事务、索引和压测验证。
6. P2-C 仍不启用 PostgreSQL，但新增抽象不得阻碍后续 asyncpg / SQLAlchemy async engine 接入。

# P2-D 前置数据库路线同步

任务：`P2-D-PRE-DOCS-PROJECT-CONTEXT-DB-ROADMAP-SYNC-1`

本节只同步当前数据库迁移路线状态，不代表已启用 PostgreSQL，不修改业务代码、配置、docker-compose 或迁移脚本。

当前路线进度：

1. P1-DB-SQLITE-SPECIFIC-USAGE-AUDIT-GUARD-1 已完成：已新增 SQLite 专属写法审计守门，当前 guard 结果为 `errors=0, warnings=77`。
2. P2-A-DB-DATABASE-URL-CONFIG-ABSTRACTION-1 已完成：9000 支持 `DATABASE_URL`，9100 支持 `RAG_DATABASE_URL`，默认仍是 SQLite，并已支持 `postgresql+asyncpg://` URL 识别和脱敏展示。
3. P2-B-DB-9000-DATABASE-FACTORY-1 已完成：9000 database factory 已收口到 `app/database.py`，PostgreSQL 仅识别、不连接，SQLite 默认行为不变。
4. P2-C-DB-9100-DATABASE-FACTORY-1 已完成：9100 metadata DB factory 已收口到 `apps/xg_douyin_ai_cs/rag/database.py`，`RAG_DATABASE_URL` 已进入 runtime 抽象，`XG_DOUYIN_AI_CS_DB_PATH` 仍兼容，PostgreSQL 仅识别、不连接，未改 Milvus / RAG 检索 / 业务 SQL。

最终生产目标：

1. 宝塔生产部署最终不再使用 SQLite。
2. PostgreSQL 使用 Docker Compose 容器，不是外部托管数据库。
3. 一个 PostgreSQL 容器实例，两个 database：
   - `auto_wechat`：9000 主服务数据库，通过 `DATABASE_URL` 接入。
   - `xg_douyin_ai_cs`：9100 RAG metadata 数据库，通过 `RAG_DATABASE_URL` 接入。
4. Milvus 继续作为向量检索库，只做 embedding / 向量检索副本，不是 documents、chunks、feedback、training_run 或状态字段的 metadata 真源。
5. 系统目标需要支持 QPS600。
6. 后续数据库访问必须考虑 asyncpg / SQLAlchemy async engine、连接池、startup 初始化 pool、shutdown 关闭 pool、事务边界、幂等约束、多租户隔离字段、高频查询索引和压测验证。

后续路线：

1. P2-D：增加 PostgreSQL docker-compose dev profile，初始化 `auto_wechat` 和 `xg_douyin_ai_cs` 两个 database。
2. P2-D 边界：可以新增 PostgreSQL dev profile 和初始化脚本，但不要立即把 9000 / 9100 生产运行切到 PostgreSQL；运行路径切换应放到后续任务。
3. P2-E：设计异步连接池与并发配置，包括 `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`RAG_DB_POOL_SIZE`、`RAG_DB_MAX_OVERFLOW`、`RAG_DB_POOL_TIMEOUT`。
4. P3：引入 Alembic / PostgreSQL migration，补齐 status、dry-run、apply、verify 和 rollback plan。
5. P4：围绕 QPS600 做压测与调优，验证连接池、事务、索引、RAG metadata 查询和关键接口延迟。

QPS600 注意事项：

1. 不允许在高频 async 请求链路继续扩散阻塞式 DB 调用。
2. 不允许每个请求创建 engine / pool。
3. PostgreSQL pool 参数后续必须可配置。
4. RAG / LLM / Milvus / 抖音发送不得阻塞主请求链路。
5. `RAG_VECTOR_BACKEND=milvus` 时，`ask` 仍不能因为 SQLite 或 PostgreSQL active count 不可靠为 0 就跳过 Milvus 检索。

# P2-D PostgreSQL dev profile 当前状态补充

任务：`P2-D-DB-POSTGRES-DEV-PROFILE-1`

当前已为本地开发增加 PostgreSQL Docker Compose dev profile，但系统默认运行路径仍是 SQLite。

本轮状态：

1. `docker-compose.dev.yml` 新增可选 `postgres` service，使用 `postgres:16-alpine`。
2. `postgres` service 放入 `profiles: ["postgres"]`，默认 compose 启动不会强制启动 PostgreSQL。
3. 使用 named volume `postgres_data` 持久化数据。
4. 初始化脚本位于 `docker/postgres/init/001_create_databases.sql`。
5. 初始化两个 database：
   - `auto_wechat`：未来给 9000 主服务使用，对应 `DATABASE_URL`。
   - `xg_douyin_ai_cs`：未来给 9100 RAG metadata 使用，对应 `RAG_DATABASE_URL`。

启动 PostgreSQL dev profile 示例：

```bash
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
```

当前边界：

1. 本轮不切换 9000 到 PostgreSQL。
2. 本轮不切换 9100 到 PostgreSQL。
3. 本轮不跑业务迁移，不引入 Alembic，不改业务 SQL，不改表结构。
4. `DATABASE_URL` / `RAG_DATABASE_URL` 的 PostgreSQL 示例只作为后续切换任务的占位说明。
5. 后续 P2-E / P3 再处理 asyncpg / SQLAlchemy async engine、连接池、Alembic 和表结构迁移。
6. 宝塔生产最终目标仍是不再使用 SQLite，并通过 Docker Compose 中的 PostgreSQL 容器承载 `auto_wechat` 与 `xg_douyin_ai_cs` 两个 database。

# P2-E async pool 并发配置当前状态补充
任务：`P2-E-DB-ASYNC-POOL-QPS600-CONCURRENCY-CONFIG-1`

当前已为后续 PostgreSQL + asyncpg / SQLAlchemy async engine + QPS600 增加连接池配置预留，但仍未创建真实连接池，未连接 PostgreSQL，未切换 9000 / 9100 当前 SQLite 默认运行路径。

9000 新增配置：
```text
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_STATEMENT_TIMEOUT_MS=5000
```

9100 新增配置：
```text
RAG_DB_POOL_SIZE=20
RAG_DB_MAX_OVERFLOW=40
RAG_DB_POOL_TIMEOUT=30
RAG_DB_POOL_RECYCLE=1800
RAG_DB_STATEMENT_TIMEOUT_MS=5000
```

边界确认：

1. 默认值只适合开发和占位说明，不代表最终生产值。
2. QPS600 必须通过压测、慢查询分析、索引设计、事务边界、幂等约束和后台队列共同验证。
3. 后续 PostgreSQL pool 必须在 FastAPI startup 初始化，在 shutdown 关闭。
4. 禁止每个请求创建 engine / pool。
5. 高频 async 请求链路不应继续扩散阻塞式数据库调用。
6. 本轮未改业务 SQL，未引入 Alembic，未连接 PostgreSQL，未改 Milvus / RAG 检索。

# P2-F 9000 async PostgreSQL 试点设计当前状态补充

任务：`P2-F-DB-9000-ASYNC-PG-PILOT-DESIGN-1`

本节只同步 9000 async PostgreSQL 接入设计和第一个低风险试点模块选择，不代表已连接 PostgreSQL，不切换 9000 当前 SQLite 默认运行路径，不修改业务 SQL，不修改表结构。

当前已新增设计文档：

```text
docs/ai/03_data_and_migration/9000_ASYNC_POSTGRES_PILOT_DESIGN.md
```

设计结论：

1. 9000 当前数据库入口仍是 `app/database.py`，主请求链路仍以同步 SQLAlchemy `SessionLocal` / `get_db` 为主。
2. 后续 async PostgreSQL 推荐使用 `asyncpg` 或 SQLAlchemy async engine。
3. PostgreSQL pool 必须在 FastAPI startup 初始化，在 shutdown 关闭。
4. 禁止每个请求创建 engine / pool。
5. QPS600 仍需要后续连接池、事务、索引、慢查询、后台队列和压测共同验证。

第一个试点模块选择：

```text
GET /knowledge-categories
```

选择理由：

1. 它是真实数据库查询，涉及 `knowledge_categories` 表。
2. 查询简单，只读，已有 SQLite 测试覆盖。
3. 可按 `RequestContext.merchant_id` 做商户隔离对照。
4. 不触发抖音发送、私信发送、自动回复 gate、Local Agent、RAG 检索或 Milvus。
5. 后续便于做 SQLite / PostgreSQL 响应结构、排序、权限和商户隔离对照测试。

明确不选择：

1. 抖音发送 / 私信发送 / 自动回复 gate 链路。
2. Local Agent / 微信任务执行链路。
3. NewCar 登录、me、logout 鉴权主链路。
4. RAG / Milvus 链路。
5. `/reports/summary` 这类聚合较多、可能存在 N+1 风险的报表接口。
6. `/compute` 这类同文件混有充值、管理员写入和内部 usage 上报的模块。

后续拆分：

1. P2-F2：新增 async PG engine / pool skeleton，只做 startup / shutdown 生命周期，不切全量链路。
2. P2-F3：为 `GET /knowledge-categories` 增加试点 repository。
3. P2-F4：为试点接口增加显式开关，默认仍走 SQLite。
4. P2-F5：做 SQLite / PostgreSQL 对照测试。

当前边界：

1. 本轮不连接 PostgreSQL。
2. 本轮不切换 9000 到 PostgreSQL。
3. 本轮不修改业务 SQL。
4. 本轮不修改 docker-compose。
5. 本轮不改 9100、不改 Milvus。
6. 本轮不触发 LLM、抖音发送、私信发送或自动回复 gate。

# P2-F2 9000 async PG engine / pool skeleton 当前状态补充

任务：`P2-F2-DB-9000-ASYNC-PG-ENGINE-POOL-SKELETON-1`

当前已为 9000 主服务新增 async PostgreSQL engine / session / lifecycle 骨架，但系统默认运行路径仍是 SQLite，且未把任何业务接口切换到 PostgreSQL。

新增能力：

1. `app/database.py` 新增 `AsyncDatabaseRuntime`，用于描述 async PG runtime 是否启用、脱敏 URL、engine 和 session factory。
2. `create_async_pg_engine()` 只接受 `postgresql+asyncpg://`，使用 `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`DB_POOL_RECYCLE`。
3. `DB_STATEMENT_TIMEOUT_MS` 已在 async engine 创建处保留设置位置，后续再通过连接事件或 startup 初始化 SQL 接入。
4. `init_async_database_runtime()` 在 SQLite 默认环境下返回 disabled runtime，不创建 engine / pool。
5. `close_async_database_runtime()` 可重复调用，已初始化时关闭 engine，未初始化时不报错。
6. `get_async_sessionmaker()` 未初始化时会明确报错，避免业务链路误用空 runtime。

边界确认：

1. 本轮未连接 PostgreSQL。
2. 本轮未切换 `GET /knowledge-categories`。
3. 本轮未改业务 SQL、未改表结构、未跑迁移、未引入 Alembic。
4. 本轮未接入 FastAPI startup / shutdown；后续接入时仍必须保证 SQLite 默认启动不初始化 PG engine。
5. 本轮未改 9100、未改 docker-compose、未改 Milvus。
6. 后续 P2-F3 才实现 `GET /knowledge-categories` 试点 repository，P2-F4 才增加显式接口开关，P2-F5 再做 SQLite / PostgreSQL 对照测试。
# P2-F3 GET /knowledge-categories async repository 试点当前状态
任务：`P2-F3-DB-9000-KNOWLEDGE-CATEGORIES-ASYNC-REPOSITORY-PILOT-1`

当前已为 9000 `GET /knowledge-categories` 增加 async PostgreSQL repository 试点代码，但系统默认运行路径仍是 SQLite。

新增内容：
1. `app/repositories/knowledge_categories_async_repository.py` 新增只读 async repository。
2. `app/config.py` 新增显式开关 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=false`。
3. `app/routers/knowledge_categories.py` 仅在开关为 true 时尝试走 async repository；开关默认 false 时继续走现有 `apps.knowledge.services.list_visible_knowledge_categories()` 同步路径。
4. async repository 查询仍只信任后端 `RequestContext.merchant_id`，不信任前端传入的 `merchant_id`。
5. runtime 未初始化时返回清晰错误，不静默伪装为成功。

边界确认：
1. 默认未切换 `GET /knowledge-categories` 流量。
2. 本轮未连接 PostgreSQL，未创建真实连接池，未运行迁移。
3. 本轮未改 `POST /knowledge-categories`、Agent 分类写接口、表结构或业务 SQL。
4. 本轮未改 9100、Milvus、RAG、LLM、抖音发送、私信发送或自动回复 gate。
5. 后续 P2-F4 才做试点运行开关验证；P2-F5 再做 SQLite / PostgreSQL 对照测试。

# P2-F4 9000 async PG 生命周期接入当前状态

任务：`P2-F4-DB-9000-KNOWLEDGE-CATEGORIES-ASYNC-PG-SWITCH-LIFECYCLE-1`

当前已将 9000 async PostgreSQL runtime 接入 `app/main.py` startup / shutdown 生命周期，用于后续 `GET /knowledge-categories` 试点运行验证。

当前行为：

1. `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=false` 时，startup 不初始化 async PG runtime，默认仍走 SQLite 同步路径。
2. 开关为 true 但 `DATABASE_URL` 仍为 SQLite 时，startup 跳过 async PG 初始化，不创建 engine / pool。
3. 开关为 true 且 `DATABASE_URL=postgresql+asyncpg://...` 时，startup 才初始化 async PG runtime。
4. `postgresql://` 和 `postgresql+psycopg://` 不作为 9000 async PG runtime 初始化入口。
5. shutdown 会调用 `close_async_database_runtime()`，支持重复调用。
6. `GET /knowledge-categories` 开关开启但 runtime 不可用时，返回 `KNOWLEDGE_CATEGORIES_ASYNC_PG_RUNTIME_UNAVAILABLE`。

边界：

1. 本轮不连接真实 PostgreSQL。
2. 本轮不切默认 `DATABASE_URL`，不切默认流量。
3. 本轮不创建 PostgreSQL 业务表，不改表结构，不跑 Alembic，不做 SQLite / PostgreSQL 数据对照。
4. 本轮不改 9100、Milvus、RAG、LLM、抖音发送、私信发送或自动回复 gate。
5. P2-F5 才做 SQLite / PostgreSQL 对照验证；QPS600 仍需后续压测与索引、事务、连接池参数调优。

# P2-F5 GET /knowledge-categories SQLite / PostgreSQL 对照 smoke 当前状态

任务：`P2-F5-DB-9000-KNOWLEDGE-CATEGORIES-SQLITE-PG-CONTRAST-SMOKE-1`

当前已为 9000 `GET /knowledge-categories` 建立最小 SQLite / PostgreSQL 对照 smoke，但默认运行路径仍是 SQLite。

新增能力：

1. `scripts/smoke_knowledge_categories_sqlite_pg_contrast.py` 只针对 `GET /knowledge-categories` 做对照验证。
2. SQLite 侧使用临时 SQLite 数据库和 synthetic 分类数据，通过 FastAPI `TestClient` 调用 GET 路由。
3. PostgreSQL 侧使用 dev profile 的 `auto_wechat` database，只创建临时 `knowledge_categories` smoke 表和 synthetic 数据。
4. smoke 验证 base 分类、当前 merchant 分类、inactive / deleted 过滤、其它 merchant 隔离、`sort_order ASC, id ASC` 排序和响应 schema。
5. PostgreSQL URL 通过 `SMOKE_POSTGRES_DATABASE_URL` 或 `DATABASE_URL` 读取，输出时必须脱敏，不写入 `.env`。

边界确认：

1. smoke 仅覆盖 `GET /knowledge-categories`，不改 POST / DELETE / Agent 写接口。
2. PostgreSQL smoke 表是临时验证表，不是正式 migration，也不是生产 schema。
3. 本轮不切默认 `DATABASE_URL`，不迁移真实业务数据，不引入 Alembic。
4. 正式 PostgreSQL 表结构、索引、唯一约束、历史数据迁移和回滚方案仍留给 P3。
5. QPS600 仍需后续连接池、索引、慢查询、事务边界、后台队列和压测验证，本 smoke 不证明性能达标。

运行方式：

```bash
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
python scripts/smoke_knowledge_categories_sqlite_pg_contrast.py
docker compose -f docker-compose.dev.yml stop postgres
```

# P3-A Alembic / PostgreSQL migration 方案设计当前状态

任务：`P3-A-DB-ALEMBIC-POSTGRESQL-MIGRATION-DESIGN-1`

当前已完成 Alembic / PostgreSQL migration 方案设计，但尚未引入 Alembic，尚未创建 migration skeleton，尚未连接 PostgreSQL，尚未跑迁移。

新增设计文档：

```text
docs/ai/03_data_and_migration/ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md
```

设计结论：

1. 宝塔生产最终仍是不再使用 SQLite。
2. PostgreSQL 仍使用 Docker Compose 容器，不是外部托管数据库。
3. 目标架构仍是一个 PostgreSQL 容器实例，两个 database：
   - `auto_wechat`：9000 主服务，通过 `DATABASE_URL` 接入。
   - `xg_douyin_ai_cs`：9100 RAG metadata，通过 `RAG_DATABASE_URL` 接入。
4. 9000 和 9100 应使用两个独立 Alembic migration 环境：
   - `migrations/postgres/auto_wechat/`
   - `migrations/postgres/xg_douyin_ai_cs/`
5. 两个 database 分别维护自己的 `alembic_version` 表，避免 9000 / 9100 服务边界、发布节奏和回滚半径混在一起。
6. Milvus 不参与 Alembic migration；Milvus 不是 metadata 真源，只是 embedding / 向量检索副本。

当前 migration 审计结论：

1. 9000 当前正式迁移体系仍是 `migrations/migrate_sqlite.py` + `migrations/versions/*.sql` + `schema_migrations`。
2. 9000 当前表结构还来自 `app/models.py` 和 `Base.metadata.create_all()`。
3. 9100 当前 metadata 表结构来自 `apps/xg_douyin_ai_cs/rag/database.py` 的 SQLite bootstrap。
4. P2-F5 PostgreSQL smoke 表只是临时对照表，不是正式 migration，也不是生产 schema。

后续路线：

1. P3-B：创建两个 Alembic skeleton，不建业务表。
2. P3-C：9000 PostgreSQL 初始 schema，优先低风险表和 `knowledge_categories` 试点。
3. P3-D：9100 PostgreSQL 初始 schema，覆盖 RAG / AI 客服 metadata。
4. P3-E：SQLite -> PostgreSQL 数据迁移脚本，包含 backup、dry-run、apply、verify、rollback plan。
5. P3-F：试点接口切 PG 对照。
6. P3-G：宝塔灰度切换。
7. P3-H：关闭 SQLite 生产路径。

边界确认：

1. 当前 P3-A 不引入 Alembic。
2. 当前 P3-A 不创建 PostgreSQL 表，不连接 PostgreSQL，不跑迁移。
3. 当前 P3-A 不切默认数据库，不改业务 SQL，不改 docker-compose。
4. 后续任何生产切换都不得直接全量切库，必须先灰度试点接口。
5. QPS600 仍需 asyncpg / SQLAlchemy async engine、连接池、事务、索引、慢查询和压测验证。

# P3-B Alembic skeleton 当前状态

任务：`P3-B-DB-ALEMBIC-SKELETON-NO-BUSINESS-TABLES-1`

当前已为 PostgreSQL migration 建立 Alembic skeleton，但仍未创建业务表、未创建 index、未连接 PostgreSQL、未执行 migration。

新增骨架：

```text
migrations/postgres/auto_wechat/
  alembic.ini
  env.py
  versions/0001_empty_baseline.py

migrations/postgres/xg_douyin_ai_cs/
  alembic.ini
  env.py
  versions/0001_empty_baseline.py
```

当前行为：

1. `auto_wechat` Alembic 环境读取 `DATABASE_URL`。
2. `xg_douyin_ai_cs` Alembic 环境读取 `RAG_DATABASE_URL`。
3. 两个环境独立管理，各自维护自己的 `alembic_version`。
4. SQLite URL 不允许作为 PostgreSQL migration 目标。
5. `0001_empty_baseline.py` 是空基线，`upgrade()` / `downgrade()` 均为空。

未来命令示例：

```bash
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini current
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head

python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini current
python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head
```

边界确认：

1. 本轮未切换 9000 / 9100 到 PostgreSQL。
2. 本轮未跑 migration。
3. 本轮未改 `app/models.py`。
4. 本轮未改 9100 metadata bootstrap。
5. 本轮未改 docker-compose、Milvus、RAG 或业务 SQL。
6. P3-C 才开始 9000 PostgreSQL 初始 schema；P3-D 才开始 9100 PostgreSQL 初始 schema。

# P3-C 9000 knowledge_categories PostgreSQL schema 当前状态

任务：`P3-C-DB-9000-POSTGRES-KNOWLEDGE-CATEGORIES-SCHEMA-1`

当前已在 9000 `auto_wechat` Alembic 环境创建第一张正式 PostgreSQL 业务表 revision：

```text
migrations/postgres/auto_wechat/versions/0002_create_knowledge_categories.py
```

当前 schema 范围：

1. 只创建 `knowledge_categories`。
2. 不创建其它 9000 业务表。
3. 不修改 `migrations/postgres/xg_douyin_ai_cs/`。
4. 不修改 `app/models.py`、业务接口、RAG、Milvus 或 docker-compose。

字段和索引要点：

1. `id` 使用 PostgreSQL `BIGSERIAL` 语义。
2. `created_at`、`updated_at`、`deleted_at` 使用 `TIMESTAMPTZ`。
3. 当前 9000 代码依赖 `category_key`，正式表保留该字段。
4. 为兼容 P2-F5 smoke 和任务中的 `key` 语义，正式表同时保留 `"key"`，并通过 check constraint 保证 `"key" = category_key`。
5. `GET /knowledge-categories` 查询索引覆盖 `merchant_id + scope_type + status + deleted_at + sort_order`。
6. 同 scope / merchant / key 唯一约束用于后续数据迁移幂等与商户隔离。

边界确认：

1. 当前默认运行仍是 SQLite。
2. 本轮未连接 PostgreSQL，未执行 Alembic migration，未跑 SQLite -> PostgreSQL 数据迁移。
3. 本轮未切换 `GET /knowledge-categories` 默认流量。
4. P3-C 后续可以单独做 dev postgres migration smoke，但必须另起受控任务。
5. QPS600 仍需后续索引验证、慢查询分析、连接池配置和压测确认。

# P3-C2 auto_wechat knowledge_categories migration smoke 当前状态

任务：`P3-C2-DB-9000-KNOWLEDGE-CATEGORIES-PG-MIGRATION-SMOKE-1`

当前已为 `auto_wechat` Alembic migration 增加 dev PostgreSQL smoke 验证入口：

```text
scripts/smoke_auto_wechat_alembic_knowledge_categories.py
```

当前能力：

1. smoke 只针对 `auto_wechat` database，不触碰 `xg_douyin_ai_cs`。
2. 读取 `SMOKE_DATABASE_URL` 或 `DATABASE_URL`，拒绝 SQLite URL。
3. 通过 `migrations/postgres/auto_wechat/alembic.ini` 执行 `upgrade head`。
4. 验证 `alembic_version` 到 `0002_create_knowledge_categories`。
5. 验证 `knowledge_categories` 表、关键字段、索引、唯一约束和 check constraint。
6. URL 输出必须脱敏，不打印 password。

P3-C2-FIX 已修复唯一约束 inspect 误判：smoke 现在以 `pg_constraint`
作为唯一约束真源，要求 `uk_knowledge_categories_scope_merchant_key`
存在且 `contype='u'`，并把 `pg_get_constraintdef(oid)` 与 `pg_indexes`
作为失败诊断输出。本修复不修改 `0002_create_knowledge_categories.py`，
不改变 schema，只修 dev smoke 检查逻辑。

为支持 dev profile 推荐的 `postgresql+asyncpg` URL，`migrations/postgres/auto_wechat/env.py` 已增加 asyncpg Alembic 在线迁移分支；这只属于 migration smoke 能力，不代表 9000 默认运行路径切换。

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮不切换 9000 默认 `DATABASE_URL`。
3. 本轮不迁移真实 SQLite 数据。
4. 本轮不插入真实业务数据。
5. 本轮不改业务接口、不改 9100、不改 Milvus / RAG。
6. P3-C3 / P3 后续才处理正式数据迁移、更多表和生产灰度切换。

# P3-C3 knowledge_categories SQLite -> PostgreSQL 数据迁移设计当前状态

任务：`P3-C3-DB-9000-KNOWLEDGE-CATEGORIES-DATA-MIGRATION-DESIGN-1`

当前已新增 9000 `knowledge_categories` 最小数据迁移设计文档：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_SQLITE_TO_POSTGRES_MIGRATION_DESIGN.md
```

当前状态：

1. P3-C3 只设计 `knowledge_categories` 数据迁移，不实现迁移脚本。
2. 本轮不连接 PostgreSQL，不读取真实 SQLite，不迁移真实数据。
3. 迁移目标仍是 `auto_wechat` database 中 revision `0002_create_knowledge_categories` 或更高版本的 `knowledge_categories` 表。
4. 当前 SQLite 字段以 `category_key` 为稳定标识；PostgreSQL 目标需要同时写 `"key"` 和 `category_key`，并满足 `key = category_key`。
5. `base` 分类仍由服务层虚拟补充；最小迁移不主动生成新的 base system 行，已有真实 base 行按普通历史行保留。
6. 幂等策略使用 `scope_type + merchant_id + key` 唯一约束，未来脚本推荐 `ON CONFLICT (scope_type, merchant_id, key) DO UPDATE`。
7. 未来脚本必须默认 `--dry-run`，只有显式 `--apply` 或 `--yes` 才允许真实写入。

后续拆分：

1. P3-C4：实现 dry-run-only 迁移脚本骨架。
2. P3-C5：实现 dev PG apply smoke。
3. P3-C6：接入 `GET /knowledge-categories` PG 数据对照。
4. P3-C7：宝塔 staging / 灰度迁移预案。

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮未改业务代码。
3. 本轮未改 Alembic revision。
4. 本轮未改 docker-compose。
5. 本轮未改 9100 / Milvus / RAG。
6. 本轮未触发 LLM、抖音发送、私信发送或自动回复 gate。

# P3-C4 knowledge_categories dry-run-only 迁移脚本骨架当前状态

任务：`P3-C4-DB-9000-KNOWLEDGE-CATEGORIES-MIGRATION-DRY-RUN-SKELETON-1`

当前已新增 9000 `knowledge_categories` SQLite -> PostgreSQL dry-run-only 迁移脚本骨架：

```text
scripts/migrate_knowledge_categories_sqlite_to_postgres.py
```

当前能力：

1. 默认只支持 dry-run，不写 PostgreSQL。
2. `--sqlite-db-path` 必须显式传入，不猜测宝塔路径或生产 SQLite 路径。
3. `--postgres-url` 可显式传入；未传时读取 `SMOKE_DATABASE_URL` 或 `DATABASE_URL`。
4. PostgreSQL URL 只允许 `postgresql://`、`postgresql+asyncpg://`、`postgresql+psycopg://`，输出时脱敏。
5. 支持 `--merchant-id` 和 `--limit` 缩小 dry-run 范围。
6. PostgreSQL 只读检查包含 `alembic_version`、`knowledge_categories` 表存在性，以及已有唯一键 `scope_type + merchant_id + key`。
7. dry-run 统计预计 insert / update / skip、异常行数量和字段映射预览。
8. `--apply` / `--yes` 当前会明确失败：`apply mode is not implemented in P3-C4`。

字段映射：

1. SQLite `category_key` 同时映射到 PostgreSQL `"key"` 和 `category_key`，保证 `key = category_key`。
2. SQLite `is_base` 0/1 显式转换为 boolean 语义。
3. 缺失 `description` 为 `None`。
4. 缺失 `scope_type` 默认为 `merchant`。
5. 缺失 `status` 默认为 `active`。
6. 缺失 `sort_order` 默认为 `0`。
7. 脚本不会主动生成新的 `base` system 行。

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮不支持 apply 成功。
3. 本轮不写 PostgreSQL，不迁移真实业务数据。
4. 本轮不改 Alembic revision，不改业务接口，不改 9100 / Milvus / RAG。
5. P3-C5 才在单独任务中实现 dev PG apply smoke。
6. 生产迁移仍未开始。

# P3-C5 knowledge_categories 受控 dev apply smoke 当前状态

任务：`P3-C5-DB-9000-KNOWLEDGE-CATEGORIES-DEV-PG-APPLY-SMOKE-1`

当前已为 9000 `knowledge_categories` SQLite -> PostgreSQL 迁移脚本增加受控 dev apply 能力，但默认运行路径仍是 SQLite，生产迁移仍未开始。

新增能力：

1. `scripts/migrate_knowledge_categories_sqlite_to_postgres.py` 默认仍 dry-run，不传 `--apply` 不写 PostgreSQL。
2. apply 必须同时传入 `--apply` 与 `--yes`。
3. apply 只能使用 `--postgres-url` 或 `SMOKE_DATABASE_URL`，不能隐式使用 `DATABASE_URL`。
4. apply host 只允许 `localhost`、`127.0.0.1` 或 `postgres`。
5. 目标 database 必须是 `auto_wechat`。
6. schema 检查必须确认 Alembic revision 至少为 `0002_create_knowledge_categories`，且 `knowledge_categories` 表存在。
7. 写入只覆盖 `knowledge_categories`，使用 `ON CONFLICT (scope_type, merchant_id, "key") DO UPDATE` 做幂等 upsert。
8. `key = category_key`，`disabled/deleted` 状态与 `deleted_at` 不会被默认 active 复活。
9. 脚本提供 synthetic SQLite helper，用于 dev smoke 临时测试库，不读取真实生产 SQLite。

边界确认：

1. 本轮不迁移真实生产数据。
2. 本轮不切换 9000 默认 `DATABASE_URL`。
3. 本轮不改 Alembic revision、不改业务接口、不改 docker-compose。
4. 本轮不改 9100 / Milvus / RAG。
5. 本轮不触发 LLM、抖音发送、私信发送或自动回复 gate。
6. P3-C6 才做 `GET /knowledge-categories` SQLite / PostgreSQL 数据对照；P3-C7 才做宝塔 staging / 灰度迁移预案。

# P3-C6 knowledge_categories SQLite / PostgreSQL API 对照当前状态

任务：`P3-C6-DB-9000-KNOWLEDGE-CATEGORIES-SQLITE-PG-API-CONTRAST-1`

当前已为 9000 `GET /knowledge-categories` 建立接口层 SQLite / PostgreSQL 响应语义对照 smoke，但默认运行路径仍是 SQLite。

新增能力：

1. 新增 `scripts/smoke_knowledge_categories_sqlite_pg_api_contrast.py`。
2. smoke 使用 synthetic / 本地测试数据，不读取或迁移真实生产 SQLite。
3. smoke 会复用 P3-C5 迁移脚本，把同一批 synthetic SQLite 数据 apply 到 dev PostgreSQL。
4. SQLite probe 通过 FastAPI 路由调用默认同步路径。
5. PostgreSQL probe 显式开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=true`，并用 `postgresql+asyncpg://` 初始化 async PG runtime 后调用同一接口。
6. normalize 会忽略自增 `id` 差异，时间字段只比较存在性，并比较 base 虚拟分类、active 过滤、disabled/deleted 过滤、商户隔离、排序和公开响应 schema。
7. smoke 结束后只清理 synthetic merchant_id 范围内的 PostgreSQL 数据，不 drop 表、不清 volume。

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮未切换 9000 默认 `DATABASE_URL`。
3. 本轮未把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
4. 本轮未迁移真实生产数据。
5. 本轮未改 Alembic revision、未改业务接口契约、未改 docker-compose。
6. 本轮未改 9100 / Milvus / RAG。
7. 本轮未触发 LLM、抖音发送、私信发送或自动回复 gate。
8. 下一步才进入宝塔 staging / 灰度迁移预案。

# P3-C7 knowledge_categories 宝塔 staging / 灰度迁移预案当前状态

任务：`P3-C7-DB-9000-KNOWLEDGE-CATEGORIES-BAOTA-STAGING-GRAY-MIGRATION-PLAN-1`

当前已新增预案文档：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_GRAY_MIGRATION_PLAN.md
```

当前阶段定位：

1. P3-C7 只做 Baota staging / gray migration 文档预案。
2. 目标只覆盖 9000 `knowledge_categories`，不迁移全量 9000 表。
3. Baota staging dry-run 后续必须记录 git commit hash、Docker Compose 状态、9000 健康、SQLite DB 路径、SQLite backup、PostgreSQL 容器、`auto_wechat` database、`0002_create_knowledge_categories` revision、SQLite / PG 行数、PG pilot 开关和默认 `DATABASE_URL` 状态。
4. Baota staging apply 后续必须显式 `--apply --yes`，必须使用受控 `<POSTGRES_URL>`，不允许隐式 `DATABASE_URL` apply。
5. API contrast 灰度验证必须对比 SQLite 默认路径与 PostgreSQL pilot 路径，且不把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
6. rollback 默认关闭 PG pilot，恢复 SQLite 默认路径，不默认 drop `knowledge_categories` 表。
7. production dry-run、production apply、默认 `DATABASE_URL` 切换都必须另起审批任务。

边界确认：

1. 本轮不执行宝塔命令。
2. 本轮不连接生产数据库。
3. 本轮不迁移真实数据。
4. 本轮不切换默认数据库。
5. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose、`.env` / `.env.example`。
6. 本轮不改 9100 / Milvus / RAG，不触发 LLM、抖音发送、私信发送或自动回复 gate。

# P3-C8 knowledge_categories 宝塔 staging dry-run 人工 Runbook 当前状态

任务：`P3-C8-BAOTA-STAGING-DRY-RUN-MANUAL-RUNBOOK-1`

当前已新增人工 Runbook 与执行记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_DRY_RUN_RECORD.md
```

当前阶段定位：

1. P3-C8 不由本机 VibeCoding 直接执行宝塔命令。
2. 本机只生成 Baota staging dry-run 人工执行 Runbook，并记录人工贴回结果。
3. dry-run 必须显式传入 `--sqlite-db-path` 和 `--postgres-url`，不得依赖隐式 `DATABASE_URL`。
4. P3-C8 不执行 `scripts/smoke_auto_wechat_alembic_knowledge_categories.py` 作为默认步骤，因为该脚本会执行 Alembic `upgrade head`。
5. P3-C8B schema 初始化已完成后，人工已执行 P3-C8 dry-run 并贴回结果。

P3-C8 人工 dry-run 结果：

1. SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
2. SQLite 已备份到 `backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
3. SQLite `knowledge_categories` 表存在，SQLite 源行数: 0。
4. PostgreSQL 目标表存在: True。
5. Alembic revision: `0002_create_knowledge_categories`。
6. Alembic revision 至少为 `0002_create_knowledge_categories`: True。
7. 过滤后待处理行数: 0。
8. 预计 insert / update / skip 均为 0。
9. 异常行数量: 0。
10. 字段映射预览: `[]`。
11. PostgreSQL 写入: disabled。
12. 最终输出：`DRY_RUN_PASS`。

说明：当前 SQLite 源行数为 0，所以 dry-run 计划为 0/0/0；本次 dry-run 未写 PostgreSQL 业务数据，不代表生产数据迁移已完成。

边界确认：

1. 本轮只改文档。
2. 本轮不执行宝塔命令。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取宝塔 SQLite。
5. 本轮不写 PostgreSQL。
6. 本轮不执行 `--apply` 或 `--yes`。
7. 本轮不切换 `DATABASE_URL`。
8. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
9. 本轮不重启 9000。
10. 本轮不改 `.env`、docker-compose、业务代码、迁移脚本或 Alembic revision。
11. 本轮不迁移真实数据，不触发 LLM、抖音发送、私信发送或自动回复 gate。

# P3-C8B knowledge_categories 宝塔 staging PostgreSQL schema 初始化 Runbook 当前状态

任务：`P3-C8B-BAOTA-STAGING-POSTGRES-SCHEMA-INIT-MANUAL-RUNBOOK-1`

当前已新增人工 Runbook 与人工执行记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_SCHEMA_INIT_RUNBOOK.md
```

P3-C8 历史 blocked 摘要：

1. 宝塔 staging SQLite 路径已确认：`docker-data/auto_wechat_9000/auto_wechat.db`。
2. SQLite `knowledge_categories` 表存在，当前 `knowledge_categories_count = 0`。
3. SQLite 已备份到 `backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
4. PostgreSQL dev 容器可启动且 healthy。
5. PostgreSQL `auto_wechat` database 存在。
6. `auto_wechat` database 当前无表，`alembic_version` 不存在。
7. P3-C8 dry-run 被 PG schema 未初始化阻塞。
8. PostgreSQL 容器已停止。

该 blocked 状态已通过 P3-C8B schema 初始化解除。

P3-C8B 执行结果：

1. 人工已使用一次性 `auto-wechat-api` 容器和临时 `DATABASE_URL` 执行 schema 初始化。
2. 执行命令为 `alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0002_create_knowledge_categories`。
3. `alembic_version` 表存在。
4. `knowledge_categories` 表存在。
5. `alembic_version = 0002_create_knowledge_categories`。
6. `uk_knowledge_categories_scope_merchant_key` UNIQUE 约束存在。
7. `ck_knowledge_categories_key_matches_category_key` CHECK 约束存在。
8. PG `knowledge_categories` 行数为 0。
9. schema 初始化写入 PostgreSQL schema，但未迁移 SQLite 业务数据，未写 PG 业务数据。
10. P3-C9 才讨论 Baota staging apply + API contrast；不能自动执行 production apply 或真实生产数据迁移。

边界确认：

1. 本轮只改文档。
2. 本轮不执行宝塔命令。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取宝塔 SQLite。
5. 本轮不迁移 SQLite 业务数据。
6. 本轮不切换 9000 默认 `DATABASE_URL`。
7. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
8. 本轮不重启 9000。
9. 本轮不改 `.env`、docker-compose、业务代码、迁移脚本或 Alembic revision。
10. 本轮不操作 9100 / Milvus / RAG，不触发 LLM、抖音发送、私信发送或自动回复 gate。

收尾确认：

1. `POSTGRES_URL` 已 unset。
2. PostgreSQL dev 容器已停止。
3. `ps postgres` 无运行容器。
4. 未执行 `--apply` / `--yes`。
5. 未切换 `DATABASE_URL`。
6. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

结论：P3-C8B 已执行通过，P3-C8 已从 blocked 更新为 dry-run passed。可以进入 P3-C9 前的人工审批，但 P3-C9 不应自动执行 production apply，也不应自动迁移真实生产数据。

# P3-C9-PRECHECK knowledge_categories 宝塔 staging apply 必要性判断当前状态

任务：`P3-C9-PRECHECK-DB-9000-KNOWLEDGE-CATEGORIES-STAGING-APPLY-NECESSITY-1`

当前已新增 P3-C9 apply 前置判断记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_APPLY_PRECHECK.md
```

判断依据：

1. P3-C8B schema 初始化已通过，`alembic_version = 0002_create_knowledge_categories`。
2. PG `knowledge_categories` 表、唯一约束和 check constraint 已存在。
3. PG `knowledge_categories` 行数 = 0。
4. P3-C8 dry-run 已通过，最终输出 `DRY_RUN_PASS`。
5. SQLite 源行数 = 0。
6. 过滤后待处理行数 = 0。
7. dry-run insert/update/skip/error = 0/0/0/0。
8. PostgreSQL 写入: disabled。

建议结论：

```text
P3-C9 staging apply: SKIPPED_NO_SOURCE_ROWS
```

当前 staging 没有 `knowledge_categories` 源业务行需要迁移，执行 `--apply --yes` 不会产生业务价值。为避免无意义写操作和误操作风险，建议跳过 P3-C9 staging apply。

后续触发 apply 的条件：

1. 后续 staging 出现 `knowledge_categories` 源数据。
2. 重新执行 P3-C8 dry-run。
3. dry-run 显示 `insert > 0` 或 `update > 0`。
4. dry-run 显示 `error = 0`。
5. PostgreSQL schema 仍至少为 `0002_create_knowledge_categories`。
6. 人工重新审批 P3-C9 apply。

边界确认：

1. 本轮只改文档。
2. 本轮不执行宝塔命令。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取 SQLite。
5. 本轮不执行 `--apply` / `--yes`。
6. 本轮不写 PostgreSQL 业务数据。
7. 本轮不迁移数据。
8. 本轮不切换 `DATABASE_URL`。
9. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
10. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

# P3-C10 knowledge_categories production dry-run 审批模板当前状态

任务：`P3-C10-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-APPROVAL-TEMPLATE-1`

当前已新增 production dry-run 审批模板：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_APPROVAL_TEMPLATE.md
```

输入依据：

1. P3-C8B Baota staging PostgreSQL schema 初始化已通过。
2. P3-C8 Baota staging dry-run 已通过。
3. P3-C9-PRECHECK 已确认 staging apply 建议跳过。
4. 跳过原因：`SKIPPED_NO_SOURCE_ROWS`。
5. SQLite 源行数 = 0。
6. dry-run insert/update/skip/error = 0/0/0/0。

P3-C10 审批范围：

1. 只审批 production dry-run。
2. 只针对 9000 `knowledge_categories`。
3. 不审批 `--apply` / `--yes`。
4. 不审批切换默认 `DATABASE_URL`。
5. 不审批开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 不涉及 9100 / Milvus / RAG。

边界确认：

1. 本轮只改文档。
2. 本轮不执行生产命令。
3. 本轮不连接生产数据库。
4. 本轮不读取生产 SQLite。
5. 本轮不执行 production dry-run。
6. 本轮不执行 `--apply` / `--yes`。
7. 本轮不写 PostgreSQL。
8. 本轮不迁移数据。
9. 本轮不切换 `DATABASE_URL`。
10. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
11. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

后续：P3-C10 审批通过后，仍只能由人工/运维执行 production dry-run，并在 P3-C11 形成执行记录；production apply 必须另走 P3-C12 审批模板。

# P3-C11 knowledge_categories production dry-run 人工 Runbook 当前状态

任务：`P3-C11-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-MANUAL-RUNBOOK-1`

当前已新增 production dry-run Runbook：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_RUNBOOK.md
```

P3-C11 目标：

1. 为 production 环境 `knowledge_categories` SQLite -> PostgreSQL dry-run 生成正式人工执行 Runbook 和执行记录模板。
2. 只覆盖 9000 `knowledge_categories`。
3. 只允许 production dry-run。
4. 不允许 apply。
5. 不允许切换默认 `DATABASE_URL`。
6. 不允许开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
7. 不涉及 9100 / Milvus / RAG。

Runbook 关键要求：

1. production 操作必须由人工/运维执行。
2. 执行前必须引用 P3-C10 approval 结果。
3. 执行前检查必须覆盖 commit hash、`git status --short`、`git diff --check`、Compose services、运行容器、`<API_SERVICE>`、`<SQLITE_DB_PATH>` 和 `<POSTGRES_URL>`。
4. 依赖检查必须确认容器内 `asyncpg` / `alembic` 和脚本可见性；不得在生产宿主机全局安装依赖。
5. SQLite 读取前必须备份，并只读查询 `knowledge_categories` 表和行数。
6. PostgreSQL 只读连接检查必须脱敏记录 URL，并确认 database 为 `auto_wechat`。
7. PG schema 必须至少到 `0002_create_knowledge_categories`，且 `knowledge_categories` 表、唯一约束、check constraint 存在。
8. schema 缺失时不能在 P3-C11 内执行 Alembic upgrade，必须转独立 schema-init 审批。
9. dry-run 命令必须显式传 `--sqlite-db-path`、`--postgres-url`、`--dry-run`，不得携带 `--apply` 或 `--yes`。
10. 输出记录必须包含 SQLite 源行数、过滤后待处理行数、PG 表状态、Alembic revision、insert/update/skip/error、字段映射预览、异常行、PostgreSQL 写入 disabled 和最终状态。

失败处理：

1. 依赖失败：停止，记录，不改宿主机。
2. PG 连接失败：停止，记录。
3. schema 缺失：停止，转 schema-init 独立审批。
4. `error > 0`：停止，不 apply。
5. 出现写入迹象：立即停止并升级事故排查。
6. 不现场临时修 production 配置。

边界确认：

1. 本轮只改文档。
2. 本轮不执行 production 命令。
3. 本轮不连接 production 数据库。
4. 本轮不读取 production SQLite。
5. 本轮不执行 production dry-run。
6. 本轮不执行 `--apply` / `--yes`。
7. 本轮不写 PostgreSQL。
8. 本轮不迁移数据。
9. 本轮不切换 `DATABASE_URL`。
10. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
11. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

后续：production dry-run 通过不等于允许 apply。若 source rows = 0，可记录 `SKIPPED_NO_SOURCE_ROWS`；若 insert/update > 0 且 error = 0，才进入 P3-C12 production apply 审批模板。不允许自动进入 apply。

# P3-C11 knowledge_categories production dry-run 执行记录当前状态

任务：`P3-C11-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-EXECUTION-RECORD-1`

当前已新增 production dry-run 执行记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_EXECUTION_RECORD.md
```

人工执行结果：

1. P3-C11 production dry-run：`PASS`。
2. commit hash：`26f4762763e71f25f66efba8d83015ff7ff8b633`。
3. `.env` PGSQL 变量仍为注释状态。
4. 未切换默认 `DATABASE_URL`。
5. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. PostgreSQL `alembic_version = 0002_create_knowledge_categories`。
7. PostgreSQL `knowledge_categories` 表存在，PG `knowledge_categories_count = 0`。
8. SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
9. SQLite `knowledge_categories` 表存在，SQLite 源行数：0。
10. SQLite 备份存在：`backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
11. production dry-run 输出：`DRY_RUN_PASS`。
12. insert/update/skip/error = 0/0/0/0。
13. PostgreSQL 写入：disabled。
14. 未执行 `--apply / --yes`。
15. 未写 PostgreSQL 业务数据。
16. 未修改 SQLite。
17. 未修改 `.env`。
18. 未切换 `DATABASE_URL`。
19. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
20. PostgreSQL 容器已停止。

本地未跟踪操作文件说明：

1. `.venv-p3c8/` 是服务器本地操作环境文件，不应提交。
2. `backups/` 是服务器本地备份目录，不应提交。

结论：

```text
P3-C11 production dry-run: PASS
P3-C12 production apply: SKIPPED_NO_SOURCE_ROWS
```

原因是 production SQLite `knowledge_categories` 源行数 = 0，dry-run insert/update/skip/error = 0/0/0/0，执行 apply 没有业务价值。后续不能自动进入 apply；如未来出现源数据，必须重新 dry-run 并另走 P3-C12 production apply 审批。

# P3-D0 PostgreSQL switch readiness 与 QPS600 路线当前状态

任务：`P3-D0-DB-9000-POSTGRESQL-SWITCH-READINESS-AND-QPS600-ROADMAP-1`

当前已新增 readiness 路线文档：

```text
docs/ai/03_data_and_migration/POSTGRESQL_SWITCH_READINESS_AND_QPS600_ROADMAP.md
```

当前结论：

1. `knowledge_categories` 单表 PostgreSQL 链路已阶段性关闭。
2. production dry-run 已通过。
3. production apply 建议为 `SKIPPED_NO_SOURCE_ROWS`，原因是 production SQLite `knowledge_categories` source rows = 0。
4. 该结论只证明单表迁移闭环可行，不能视为 9000 全系统 PostgreSQL 切库完成。
5. 当前仍不能切换宝塔默认 `DATABASE_URL` 到 PostgreSQL。
6. 当前仍不能把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
7. 下一阶段进入 P3-D：全系统 PostgreSQL readiness 与 QPS600 异步化路线。

只读审计摘要：

1. `app/database.py` 当前同步 `engine` / `SessionLocal` / `get_db` 仍是主路径，默认 SQLite；PostgreSQL backend 已识别但默认同步 engine 路径仍拒绝启用。
2. `knowledge_categories` 已有 async PG pilot，但不能代表全系统 async 化完成。
3. 多数 routers / services / schedulers 仍使用同步 SQLAlchemy session、`db.query()`、`db.commit()` 和 `SessionLocal()`。
4. 高频 async 改造候选包括 webhook、leads、wechat_tasks、staff、webhook_events、compute、conversation 和自动回复记录接口。
5. QPS600 需要 asyncpg / SQLAlchemy async、connection pool、statement_timeout、慢查询日志、高频索引、幂等键、任务锁策略、事务边界和压测共同验证。

后续阶段：

1. P3-D1：表盘点与读写路径审计。
2. P3-D2：核心基础表 schema 设计。
3. P3-D3：线索链路 PG schema + migration。
4. P3-D4：Local Agent task 链路 PG schema + migration。
5. P3-D5：智能体 / 账号绑定 PG schema + migration。
6. P3-D6：算力账户 / 流水 PG schema + migration。
7. P3-D7：核心接口 SQLite / PG contrast。
8. P3-D8 / P3-D9：staging 与 production 灰度、dry-run、apply 判断。
9. P3-E：默认 `DATABASE_URL` 切换预案。

边界确认：

1. 本轮只做文档和只读代码审计。
2. 本轮不改业务代码、迁移脚本或 Alembic revision。
3. 本轮不执行宝塔命令。
4. 本轮不连接数据库。
5. 本轮不读取 SQLite。
6. 本轮不执行 dry-run / apply。
7. 本轮不切换 `DATABASE_URL`。
8. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
9. 本轮不提交 `.venv-p3c8/`、`backups/`、`docs/superpowers/` 等非本轮文件。

# P3-D1 leads/tasks core PostgreSQL schema batch 当前状态

任务：`P3-D1-DB-9000-POSTGRESQL-LEADS-TASKS-CORE-SCHEMA-BATCH-1`

当前已从 `knowledge_categories` 单表链路进入 9000 业务域批量 PostgreSQL schema。本批只覆盖 4 张 P0 核心表：

1. `douyin_leads`
2. `douyin_webhook_events`
3. `sales_staff`
4. `wechat_tasks`

新增文件：

```text
migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py
tests/test_9000_postgres_leads_tasks_core_schema.py
scripts/smoke_auto_wechat_alembic_leads_tasks_core.py
```

审计摘要：

1. `DouyinLead` 当前用于线索列表、详情、报表统计、销售分配、webhook 会话归并和留资字段回填。
2. `DouyinWebhookEvent` 当前用于 webhook 原始事件落库、`event_key` 幂等、重复事件记录、解析字段保存和会话消息读取。
3. `SalesStaff` 当前用于销售配置、商户隔离、active 销售过滤、微信昵称/微信号检索和分配候选。
4. `WechatTask` 当前用于 `notify_sales` / `detect_reply` 任务创建、pending 拉取、结果回写、检测次数和后续检测任务生成。

schema 摘要：

1. revision 为 `0003_leads_tasks_core`，接在 `0002_create_knowledge_categories` 后。
2. 4 张表主键使用 PostgreSQL `BigInteger` 自增。
3. 时间字段使用 `DateTime(timezone=True)`。
4. JSON 类字段使用 PostgreSQL `JSONB`。
5. webhook 幂等字段 `event_key` 建唯一约束。
6. 线索会话归并字段 `account_open_id + conversation_short_id` 保留唯一约束。
7. `douyin_leads`、`douyin_webhook_events`、`sales_staff`、`wechat_tasks` 均已补核心查询索引，作为 QPS600 索引落地起点。

dev smoke 摘要：

1. `scripts/smoke_auto_wechat_alembic_leads_tasks_core.py` 只从 `SMOKE_DATABASE_URL` 读取 PostgreSQL URL。
2. smoke 拒绝 SQLite URL，并脱敏输出 URL。
3. smoke 执行 auto_wechat Alembic `upgrade head`。
4. smoke 只读验证 revision、4 张表、关键字段、索引和约束。
5. smoke 不写业务数据，不迁移 SQLite 数据，不执行 apply。

边界确认：

1. 本轮允许新增 PostgreSQL Alembic migration、schema 静态测试、dev PostgreSQL migration smoke 和文档。
2. 本轮不迁移 SQLite 数据。
3. 本轮不执行 apply。
4. 本轮不切换 `DATABASE_URL`。
5. 本轮不改业务接口默认数据库。
6. 本轮不连接宝塔生产。
7. 本轮不改 9100 / Milvus / RAG。
8. 本轮不触发 LLM、抖音发送、私信发送或自动回复 gate。
9. 本轮不提交 `.venv-p3c8/`、`backups/`、`docs/superpowers/` 等非本轮文件。

后续：P3-D1 只是线索与任务核心链路的 PostgreSQL schema 起点。后续还需要本批表的数据迁移 dry-run、受控 dev apply smoke、SQLite / PG API contrast、staging dry-run、production dry-run 和是否 apply 的人工判断；当前仍不能切换 9000 默认 `DATABASE_URL` 到 PostgreSQL。

# P3-D2 leads/tasks core 数据迁移 dry-run 与 dev apply 当前状态

任务：`P3-D2-DB-9000-POSTGRESQL-LEADS-TASKS-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

当前已为 P3-D1 的 4 张 P0 核心表新增 SQLite -> PostgreSQL 数据迁移脚本、dry-run 统计、静态测试和 dev apply smoke：

```text
scripts/migrate_leads_tasks_core_sqlite_to_postgres.py
scripts/smoke_migrate_leads_tasks_core_dev_apply.py
tests/test_migrate_leads_tasks_core_sqlite_to_postgres.py
```

覆盖表：

1. `sales_staff`
2. `douyin_leads`
3. `douyin_webhook_events`
4. `wechat_tasks`

默认迁移顺序：

```text
sales_staff -> douyin_leads -> douyin_webhook_events -> wechat_tasks
```

说明：该顺序按 P3-D1 PostgreSQL schema 外键依赖确定，避免 `douyin_webhook_events.lead_id` 先于 `douyin_leads.id` 写入造成外键失败。

脚本能力：

1. 默认 dry-run，PostgreSQL 写入为 `disabled`。
2. 支持 `--sqlite-db-path`、`--postgres-url`、`--dry-run`、`--apply`、`--yes`、`--tables`。
3. PostgreSQL URL 必须脱敏输出。
4. apply 必须显式 `--apply --yes`。
5. apply 只允许 dev/local host，目标 database 必须是 `auto_wechat`。
6. `APP_ENV=production` 时拒绝 apply。
7. JSON 字段解析失败记录 warning 并保留原始字符串。
8. datetime 字段解析失败进入 error_rows。
9. mapping preview 会脱敏手机号、微信号等联系方式。

upsert / 幂等策略：

1. `sales_staff` 按 `id` 主键 upsert。
2. `douyin_leads` 按 `account_open_id + conversation_short_id` upsert。
3. `douyin_webhook_events` 按 `event_key` upsert。
4. `wechat_tasks` 按 `id` 主键 upsert。
5. 不删除 PostgreSQL 既有数据，不 truncate，不 drop 表。

dev smoke 摘要：

1. `scripts/smoke_migrate_leads_tasks_core_dev_apply.py` 只从 `SMOKE_DATABASE_URL` 读取 PostgreSQL URL。
2. smoke 自动创建临时 synthetic SQLite fixture，不读取真实生产 SQLite。
3. smoke 每表至少写入 2 行 synthetic 数据。
4. smoke 执行 Alembic `upgrade head` 后，先 dry-run，再 apply，再二次 dry-run 验证幂等。
5. 成功输出：`SMOKE_PASS: leads/tasks core data migration dev apply ready`。

边界确认：

1. 本轮未连接宝塔生产。
2. 本轮未读取宝塔生产 SQLite。
3. 本轮未执行 production apply。
4. 本轮未切换默认 `DATABASE_URL`。
5. 本轮未修改业务接口默认数据库。
6. 本轮未改 9000 runtime DB 逻辑。
7. 本轮未改 9100 / Milvus / RAG。
8. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
9. 当前仍不能切换宝塔 SQLite 到 PostgreSQL。

后续：P3-D3 建议进入四表 API contrast 与 async PG pilot 方案；P3-D2 dev apply smoke 不能被解读为 production 迁移完成或默认数据库可切换。

# P3-D3 leads/tasks core API contrast 与 async PG pilot 当前状态

任务：`P3-D3-DB-9000-LEADS-TASKS-API-CONTRAST-AND-ASYNC-PG-PILOT-1`

当前已新增四表 SQLite vs PostgreSQL contrast 框架：

```text
scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py
tests/test_contrast_leads_tasks_core_sqlite_vs_postgres.py
```

当前已新增 dev synthetic contrast smoke：

```text
scripts/smoke_contrast_leads_tasks_core_dev.py
```

当前已新增 async PG pilot 方案文档：

```text
docs/ai/03_data_and_migration/LEADS_TASKS_ASYNC_PG_PILOT_PLAN.md
```

覆盖表：

1. `sales_staff`
2. `douyin_leads`
3. `douyin_webhook_events`
4. `wechat_tasks`

contrast 语义：

1. 默认只读。
2. PostgreSQL 写入为 `disabled`。
3. 对照 SQLite / PostgreSQL 行数、业务 key、必要字段、JSON parseability、datetime parseability。
4. mismatch_count 聚焦 key 层面的缺失 / 多出。
5. JSON / datetime 解析异常在非 strict 下作为 warning。
6. strict 模式下 warning 可升级为失败。

async PG pilot 方案：

1. 默认不切换 `DATABASE_URL`。
2. 默认不启用 PG pilot。
3. 后续开关默认全部 false：`LEADS_TASKS_PG_PILOT_ENABLED=false`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=false`、`LEADS_TASKS_PG_WRITE_ENABLED=false`、`LEADS_TASKS_PG_STRICT_CONTRAST=false`。
4. 推荐顺序：`sales_staff` read-only -> `wechat_tasks` history read-only -> `douyin_leads` list/detail read-only -> `douyin_webhook_events` read-only -> webhook write / task result write。
5. SQLite 仍是返回源，PostgreSQL 只做 shadow read，mismatch 只记录日志，不影响用户。

边界确认：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前未连接宝塔生产。
4. 当前未读取生产 SQLite。
5. 当前未执行 production apply。
6. 当前未改业务接口默认数据库。
7. 当前未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

下一步：P3-D4 进入 runtime shadow read scaffolding，默认关闭。
