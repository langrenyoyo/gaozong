# PostgreSQL switch readiness and QPS600 roadmap

任务：`P3-D0-DB-9000-POSTGRESQL-SWITCH-READINESS-AND-QPS600-ROADMAP-1`

本文基于 `knowledge_categories` 单表闭环结果，评估 9000 从 SQLite 切换到 PostgreSQL 的整体 readiness，并制定 QPS600 异步化路线。本轮只做文档和只读代码审计，不改业务代码，不执行迁移，不连接宝塔，不读取 SQLite，不切换 `DATABASE_URL`。

关键词口径：`knowledge_categories`；`SKIPPED_NO_SOURCE_ROWS`；`PostgreSQL switch readiness`；`QPS600`；`asyncpg`；`SQLAlchemy async`；`connection pool`；`DATABASE_URL`；`KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`；不切换默认数据库。

## 1. 当前结论

1. `knowledge_categories` 已完成单表 PostgreSQL 迁移验证链路：schema migration、dry-run-only 迁移脚本、受控 dev apply smoke、SQLite / PG API contrast、Baota staging schema init、Baota staging dry-run、production dry-run。
2. production dry-run 已通过，结果为 `DRY_RUN_PASS`。
3. production apply 建议为 `SKIPPED_NO_SOURCE_ROWS`，原因是 production SQLite `knowledge_categories` source rows = 0，dry-run insert/update/skip/error = 0/0/0/0。
4. 当前只能证明单表迁移闭环可行，不能把 `knowledge_categories` 的结论推广为全系统切库完成。
5. 当前不能切换宝塔默认 `DATABASE_URL` 到 PostgreSQL。
6. 当前不能把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
7. QPS600 还未通过压测证明，必须在 async 数据访问、连接池、索引、事务、幂等和压测全部完成后再确认。

## 2. PostgreSQL switch readiness 准入条件

切换 9000 默认 `DATABASE_URL` 到 PostgreSQL 前，至少需要满足以下条件：

| 类别 | 准入条件 | 当前状态 |
|---|---|---|
| schema | 核心业务表均完成 PostgreSQL Alembic schema | 仅 `knowledge_categories` 已完成 |
| 数据迁移 | 核心业务表完成 SQLite -> PostgreSQL dry-run / apply / verify | 仅 `knowledge_categories` 链路完成，且 source rows = 0 |
| 接口对照 | 核心接口完成 SQLite / PG API contrast | 仅 GET `/knowledge-categories` 已完成 |
| 写入链路 | 写入接口完成事务边界和幂等保护 | 未系统完成 |
| staging | 宝塔 staging 完成灰度验证和回滚演练 | 单表 dry-run 完成，未做全系统灰度 |
| 回滚 | 关闭 PG 路径、恢复 SQLite 默认路径、数据回滚方案已验证 | 单表文档化，未全系统验证 |
| 连接池 | worker 数、pool_size、max_overflow、pool_timeout、总连接数已确认 | 已有配置入口，未压测定型 |
| 索引 | 高频 WHERE / JOIN / ORDER BY 均有 PostgreSQL 索引验证 | 未完成全表审计和 explain 验证 |
| 压测 | 关键接口达到 QPS600 且错误率、延迟、数据库连接数可控 | 未执行 |

结论：当前不具备默认切库条件。

## 3. 9000 核心表分级

### 3.1 P0 必须迁移

这些表承载主链路、授权、任务、智能体绑定和算力账户，是默认切库前必须完成 PostgreSQL schema、数据迁移和接口对照的核心表：

| 表 | 原因 | 主要关注点 |
|---|---|---|
| `douyin_leads` | 线索主表，列表、详情、分配、webhook 留资都依赖 | merchant/account/conversation 唯一性、状态流转、分页索引 |
| `douyin_webhook_events` | 抖音 webhook 原始事件和幂等真源 | `event_key` 唯一约束、按账号/会话/时间查询 |
| `wechat_tasks` | Local Agent 任务队列 | pending polling、状态抢占、结果回写幂等 |
| `sales_staff` | 销售分配基础表 | merchant 隔离、active 查询、分配顺序 |
| `douyin_authorized_accounts` | 抖音企业号授权与商户映射 | open_id/main_account 唯一性、bind_status 索引 |
| `douyin_account_agent_bindings` | 企业号与智能体绑定 | merchant/account/agent 组合查询和默认绑定唯一性 |
| `ai_agents` | 智能体基础配置 | merchant/status 查询、训练和绑定引用 |
| `agent_knowledge_categories` | 智能体知识分类绑定 | agent/category 关系和去重 |
| `compute_accounts` | 算力账户余额 | merchant 唯一账户、并发扣减事务 |
| `compute_transactions` | 算力流水 | 幂等流水号、账户流水分页、审计不可丢 |

### 3.2 P1 迁移

这些表支撑工作台、自动回复、资源处理和通知记录，建议在 P0 主链路完成后紧接迁移：

| 表 | 原因 | 主要关注点 |
|---|---|---|
| `douyin_conversation_read_states` | 工作台会话已读状态 | merchant/account/conversation 唯一性 |
| `conversation_autopilot_states` | 自动回复会话状态 | manual takeover、状态幂等 |
| `douyin_private_message_sends` | 私信发送记录 | 发送幂等、人工/AI 来源区分 |
| `douyin_image_uploads` | 图片上传记录 | resource key、状态回写 |
| `douyin_message_resource_downloads` | 消息资源下载记录 | event/message/resource 去重 |
| `lead_notifications` | 微信通知记录 | lead/staff/check 关联和发送状态 |
| `lead_followup_records` | 线索跟进记录 | lead 时间线分页 |
| `ai_auto_reply_runs` | 自动回复运行记录 | conversation/account/time 查询 |
| `ai_reply_decision_logs` | AI 回复决策日志 | run/log 查询、审计保留 |

### 3.3 P2 可后置

这些表或数据域可在核心切库后按风险拆分迁移：

1. audit logs。
2. `feedback_records`。
3. rollout / whitelist config。
4. 临时或低频配置表。
5. debug、观察、历史兼容类低频表。

P2 表后置不代表可以遗忘；只代表它们不应阻塞第一轮默认切库 readiness，但仍需要独立 schema、迁移、回滚和验证计划。

## 4. 推荐迁移顺序

1. `P3-D1`：表盘点与读写路径审计，输出每张表的 router / service / repository / scheduler 访问矩阵。
2. `P3-D2`：核心基础表 schema 设计，先覆盖 `sales_staff`、`douyin_authorized_accounts`、`ai_agents`、`agent_knowledge_categories`。
3. `P3-D3`：线索链路 PostgreSQL schema + migration，覆盖 `douyin_leads`、`douyin_webhook_events` 和 webhook 幂等。
4. `P3-D4`：Local Agent task 链路 PostgreSQL schema + migration，覆盖 `wechat_tasks`、`lead_notifications`、`reply_checks`、跟进记录。
5. `P3-D5`：智能体 / 账号绑定 PostgreSQL schema + migration，覆盖账号绑定、自动回复设置、对话状态。
6. `P3-D6`：算力账户 / 流水 PostgreSQL schema + migration，覆盖账户余额、流水幂等和并发扣减。
7. `P3-D7`：核心接口 SQLite / PG contrast，覆盖 GET/POST 写读闭环，不只对照列表接口。
8. `P3-D8`：staging 灰度切换，显式开关、临时环境变量、可关闭回退。
9. `P3-D9`：production dry-run / apply / contrast，按审批执行，不自动进入 apply。
10. `P3-E`：默认 `DATABASE_URL` 切换预案，包含连接池、worker、回滚、压测和监控门槛。

## 5. QPS600 异步化路线

### 5.1 数据访问原则

1. 禁止在 async route 中直接使用同步 SQLAlchemy session。
2. PostgreSQL 访问统一使用 `asyncpg` 或 SQLAlchemy async engine / async session。
3. `app/database.py` 已有 async runtime 入口，但当前只有 `knowledge_categories` 试点路径使用；全系统仍大量依赖同步 `get_db` / `SessionLocal`。
4. service 层不应判断数据库方言；数据库差异应收口到 repository / data access 层。
5. 高并发路径先改读接口，再改写接口；写接口必须同步设计事务和幂等。

### 5.2 连接池和 worker 计算

建议后续统一记录并压测以下配置：

```text
workers = <uvicorn 或 gunicorn worker 数>
pool_size = DB_POOL_SIZE
max_overflow = DB_MAX_OVERFLOW
单 worker 最大连接 = pool_size + max_overflow
理论最大连接 = workers * (pool_size + max_overflow)
数据库预留连接 = maintenance / migration / psql / monitoring
PostgreSQL max_connections >= 理论最大连接 + 数据库预留连接
```

当前已有配置入口：`DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`DB_POOL_RECYCLE`、`DB_STATEMENT_TIMEOUT_MS`。切库前必须结合宝塔容器 worker 数和 PostgreSQL `max_connections` 做容量核算，不能只调大连接池。

### 5.3 statement_timeout 和慢查询

1. 在 PostgreSQL session 或连接初始化阶段设置 `statement_timeout`。
2. 对 webhook、task polling、列表分页、报表聚合配置慢查询日志。
3. 慢查询阈值先按接口 SLA 倒推，例如 200ms / 500ms 两档观察。
4. 压测期间必须同时记录接口延迟、数据库慢查询、连接池等待和错误率。

### 5.4 高频字段索引

初始索引优先覆盖以下查询模式：

| 链路 | 高频字段 |
|---|---|
| 线索列表 | `merchant_id`、`status`、`created_at`、`assigned_staff_id`、`account_open_id`、`conversation_short_id` |
| webhook 幂等 | `event_key`、`to_user_id`、`conversation_short_id`、`server_message_id`、`message_create_time` |
| 任务 polling | `task_type`、`status`、`created_at`、`agent_hostname`、`lead_id`、`staff_id` |
| 销售分配 | `merchant_id`、`status`、`id` |
| 授权账号 | `merchant_id`、`open_id`、`main_account_id`、`bind_status` |
| 智能体绑定 | `merchant_id`、`account_open_id`、`agent_id`、`status`、`is_default` |
| 算力账户 | `merchant_id`、`status` |
| 算力流水 | `merchant_id`、`account_id`、`transaction_type`、`created_at`、幂等键 |
| 自动回复 | `merchant_id`、`account_open_id`、`conversation_short_id`、`created_at`、`status` |

索引必须通过 PostgreSQL `EXPLAIN` / `EXPLAIN ANALYZE` 和压测确认，不能只凭 SQLite 查询表现判断。

### 5.5 幂等和事务

1. webhook 写入必须以 `event_key` 或等价业务键做唯一约束，重复事件只能产生可解释结果。
2. 线索归并建议继续以 `account_open_id + conversation_short_id` 作为核心唯一依据。
3. task polling 需要分页和抢占策略，PostgreSQL 方向建议评估 `FOR UPDATE SKIP LOCKED`，避免多 worker 重复领取。
4. 算力扣减必须在同一事务内完成账户余额更新和流水插入，流水幂等键必须唯一。
5. 私信发送、微信通知、自动回复 gate 都需要先落库状态，再执行外部动作，并保证失败可重试、重复不重发。
6. 不建议长事务等待外部 HTTP、Milvus、LLM 或微信自动化结果。

### 5.6 API 压测计划

QPS600 不能只压一个接口，至少拆分以下场景：

| 场景 | 接口 |
|---|---|
| 健康与轻量读 | GET `/health` 或等价健康接口 |
| 线索列表 | GET `/leads` |
| 线索详情 | GET `/leads/{lead_id}` |
| webhook 写入 | POST `/integrations/douyin/webhook` |
| webhook 事件列表 | GET `/webhook-events` |
| 任务拉取 | GET `/wechat-tasks/pending` |
| 任务回写 | POST `/wechat-tasks/{task_id}/result` |
| 销售列表 | GET `/staff` |
| 授权账号 / 会话 | GET `/integrations/accounts/{account_id}/conversations` |
| 算力摘要 | GET `/compute/summary` |
| 自动回复记录 | GET `/ai-auto-reply-runs`、GET `/ai-reply-decision-logs` |
| knowledge pilot | GET `/knowledge-categories` |

压测通过口径建议包含：QPS、P50/P95/P99、HTTP 5xx、数据库连接池等待、PostgreSQL CPU/IO、慢查询数量、锁等待、错误重试率。

## 6. 只读代码审计摘要

### 6.1 当前同步 DB session 使用点

只读扫描显示，同步 SQLAlchemy session 仍是主路径：

1. `app/database.py` 暴露 `engine`、`SessionLocal`、`get_db`，默认 SQLite；`create_database_engine()` 当前识别 PostgreSQL 但明确拒绝启用。
2. 大量 routers 使用 `Depends(get_db)`，包括 leads、staff、reports、wechat_tasks、webhook_events、compute、agents、douyin_accounts、admin_autoreply_rollout 等。
3. 大量 services 使用 `db.query()`、`db.add()`、`db.commit()`、`db.execute()`，包括 lead、webhook、task、notification、compute、agent binding、autoreply 等链路。
4. scheduler 中仍直接使用 `SessionLocal()`，包括 `check_scheduler.py` 和 `wechat_auto_detect_scheduler.py`。
5. `knowledge_categories` 已有 async PG pilot，但开关默认 false，不能代表全系统 async 化完成。

### 6.2 需要优先 async 改造的高频接口

优先级建议：

1. POST `/integrations/douyin/webhook`：外部事件入口，涉及幂等、事件落库、线索 upsert、后置状态。
2. GET `/leads` 与 GET `/leads/{lead_id}`：运营台核心读路径，列表分页和详情聚合容易成为高频查询。
3. GET `/wechat-tasks/pending` 与 POST `/wechat-tasks/{task_id}/result`：Local Agent polling / 回写路径，QPS 和并发 worker 风险集中。
4. GET `/staff`：分配和运营基础数据，高频读但逻辑较轻，适合作为早期 async 改造对象。
5. GET `/webhook-events`：审计列表，可能按时间和状态分页。
6. GET `/compute/summary`、GET `/compute/transactions`：涉及账户和流水，后续需防止聚合阻塞。
7. GET `/integrations/accounts/{account_id}/conversations`、GET `/integrations/conversation-messages`：工作台高频列表/消息读取。
8. 自动回复记录类接口：GET `/ai-auto-reply-runs`、GET `/ai-reply-decision-logs`。

### 6.3 需要优先加索引的查询

只读审计结合现有模型和服务路径，优先索引方向为：

1. `douyin_leads(merchant_id, status, created_at)`：线索列表分页和状态过滤。
2. `douyin_leads(account_open_id, conversation_short_id)`：webhook 会话归并唯一键。
3. `douyin_webhook_events(event_key)`：webhook 幂等。
4. `douyin_webhook_events(to_user_id, conversation_short_id, message_create_time)`：会话消息读取和工作台查询。
5. `wechat_tasks(task_type, status, created_at)`：pending polling。
6. `wechat_tasks(lead_id, staff_id, task_type)`：任务去重和详情关联。
7. `sales_staff(merchant_id, status, id)`：商户内 active 销售分配。
8. `douyin_authorized_accounts(open_id, bind_status)` 和 `(merchant_id, bind_status)`：账号解析和账号列表。
9. `douyin_account_agent_bindings(merchant_id, account_open_id, status)`：账号智能体绑定查询。
10. `compute_transactions(account_id, created_at)` 与 `(merchant_id, created_at)`：流水分页和审计。

### 6.4 需要幂等保护的写入链路

1. 抖音 webhook 事件写入：重复回调必须通过唯一业务键识别。
2. 线索 upsert：同一企业号同一会话不能重复生成多条活跃线索。
3. 微信任务创建：同一 lead/staff/task_type 的 pending / pasted / sent 任务不能重复创建。
4. 任务结果回写：重复回写不能把 sent、failed、blocked 等状态来回覆盖。
5. 销售通知记录：同一 lead/staff/check 的发送记录需要去重或明确多次发送语义。
6. 算力扣减：账户余额和流水必须事务一致，重复请求不能重复扣费。
7. 抖音私信发送：外部发送动作必须先有本地幂等记录，防止重试重复发送。
8. 自动回复 gate：AI 回复记录、人工接管状态和发送状态需要严格防重入。

### 6.5 需要压测的接口清单

1. GET `/leads`。
2. GET `/leads/{lead_id}`。
3. POST `/integrations/douyin/webhook`。
4. GET `/webhook-events`。
5. GET `/wechat-tasks/pending`。
6. POST `/wechat-tasks/{task_id}/result`。
7. GET `/staff`。
8. GET `/reports/summary`。
9. GET `/compute/summary`。
10. GET `/compute/transactions`。
11. GET `/integrations/accounts/{account_id}/conversations`。
12. GET `/integrations/conversation-messages`。
13. GET `/ai-auto-reply-runs`。
14. GET `/ai-reply-decision-logs`。
15. GET `/knowledge-categories`。

## 7. 当前风险

1. 只完成 `knowledge_categories`，覆盖面不足。
2. production 源数据为 0，未验证真实业务数据迁移。
3. 当前宝塔 PostgreSQL 来自 dev profile，正式生产 PostgreSQL 运行方式还需定稿。
4. 生产镜像默认不包含 `scripts/` 和 `migrations/`，执行迁移依赖挂载或宿主机代码目录。
5. 默认同步 SQLite / SQLAlchemy session 访问仍广泛存在，async route 中的同步 DB 访问可能阻塞事件循环。
6. 写入链路尚未系统完成 PostgreSQL 事务、锁和幂等设计。
7. 高频查询的 PostgreSQL 索引还未通过 explain 和压测验证。
8. 连接池总连接数还未按 worker 数和 PostgreSQL `max_connections` 核算。
9. QPS600 未通过压测证明。
10. 9100 / Milvus / RAG 不在本轮切库范围内，不能被 9000 单表结论覆盖。

## 8. 切换前禁止事项

1. 现在禁止切换宝塔默认 `DATABASE_URL` 到 PostgreSQL。
2. 现在禁止把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
3. 现在禁止删除 SQLite。
4. 现在禁止清空 PostgreSQL volume。
5. 现在禁止把 `knowledge_categories` 的结论推广到全表。
6. 未完成核心表 schema / 数据迁移 / API contrast 前，禁止宣布 9000 已完成 PostgreSQL 切库。
7. 未完成压测前，禁止宣称 QPS600 达标。
8. 禁止为了验证 apply 而在 staging 或 production 手工制造真实业务数据。
9. 禁止把 production dry-run 通过自动升级为 production apply。

## 9. 后续建议

1. P3-D1 先做全表读写路径审计，输出每张表的接口、服务、scheduler、外部动作和迁移优先级。
2. P3-D2 开始补 PostgreSQL schema，不要一次性全量迁移所有表。
3. 每个表组都沿用 `knowledge_categories` 的闭环：schema -> dry-run -> dev smoke -> API contrast -> staging dry-run -> production dry-run -> 是否 apply 判断。
4. QPS600 路线与切库路线并行推进，但 QPS600 结论只能由压测和数据库观测数据确认。
5. `knowledge_categories` 链路可阶段性关闭；后续除非出现源数据，否则 P3-C12 production apply 建议保持 `SKIPPED_NO_SOURCE_ROWS`。

## 10. P3-D1 线索与任务核心 schema batch

任务：`P3-D1-DB-9000-POSTGRESQL-LEADS-TASKS-CORE-SCHEMA-BATCH-1`

P3-D1 从单表试点进入业务域批量 PostgreSQL schema。当前 batch 只覆盖 4 张 P0 核心表：

1. `douyin_leads`
2. `douyin_webhook_events`
3. `sales_staff`
4. `wechat_tasks`

新增 PostgreSQL revision：

```text
migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py
```

新增 dev schema smoke：

```text
scripts/smoke_auto_wechat_alembic_leads_tasks_core.py
```

新增静态测试：

```text
tests/test_9000_postgres_leads_tasks_core_schema.py
```

### 10.1 只读审计摘要

1. `DouyinLead` 当前承担线索列表、线索详情、报表统计、webhook 会话归并和销售分配主路径。
2. `DouyinWebhookEvent` 当前承担 webhook 原始事件、解析字段、`event_key` 幂等去重、重复事件记录和会话消息读取。
3. `SalesStaff` 当前承担销售配置、商户内 active 销售过滤、微信昵称/微信号检索和分配候选。
4. `WechatTask` 当前承担 `notify_sales` / `detect_reply` Local Agent 任务创建、pending 拉取、结果回写和后续检测任务生成。
5. 现有主路径仍使用同步 SQLAlchemy session；P3-D1 只补 PostgreSQL schema，不做 async 改造。

### 10.2 索引与幂等落地

1. `douyin_webhook_events.event_key` 建唯一约束，作为 webhook 幂等保护的 schema 起点。
2. `douyin_leads(account_open_id, conversation_short_id)` 保留唯一约束，延续会话维度线索归并口径。
3. `douyin_leads` 增加 `merchant_id + updated_at`、`merchant_id + status + updated_at`、`merchant_id + account_open_id + conversation_short_id`、`assigned_staff_id + status` 索引。
4. `sales_staff` 增加 `merchant_id + status`、`merchant_id + wechat_nickname`、`merchant_id + wechat_id` 索引，不破坏同商户多销售逻辑。
5. `wechat_tasks` 增加 `merchant_id + status + created_at`、`task_type + status + created_at`、`lead_id + task_type`、`staff_id + status` 索引。

### 10.3 边界确认

1. P3-D1 只建立 PostgreSQL schema batch。
2. 本轮不迁移 SQLite 数据。
3. 本轮不执行 apply。
4. 本轮不切换 `DATABASE_URL`。
5. 本轮不改业务接口默认数据库。
6. 本轮不连接宝塔生产。
7. 本轮不改 9100 / Milvus / RAG。
8. 本轮不触发 LLM、抖音发送、私信发送或自动回复 gate。

后续仍需为该 batch 增加 SQLite -> PostgreSQL 数据迁移 dry-run、dev apply smoke、核心接口 SQLite / PG API contrast、staging dry-run 与 production dry-run 记录。P3-D1 不能被解读为 9000 已可切换默认数据库。
