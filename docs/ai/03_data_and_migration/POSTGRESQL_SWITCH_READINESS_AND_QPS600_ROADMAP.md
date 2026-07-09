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

## 11. P3-D2 线索与任务核心数据迁移脚本

任务：`P3-D2-DB-9000-POSTGRESQL-LEADS-TASKS-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

P3-D2 在 P3-D1 schema batch 基础上补齐 4 张表的 SQLite -> PostgreSQL 数据迁移脚本、dry-run 统计、静态测试与本地/dev apply smoke。

新增文件：

```text
scripts/migrate_leads_tasks_core_sqlite_to_postgres.py
scripts/smoke_migrate_leads_tasks_core_dev_apply.py
tests/test_migrate_leads_tasks_core_sqlite_to_postgres.py
```

### 11.1 迁移顺序与字段映射

默认迁移顺序：

```text
sales_staff -> douyin_leads -> douyin_webhook_events -> wechat_tasks
```

该顺序按 P3-D1 PostgreSQL 外键依赖确定：`douyin_leads.assigned_staff_id` 依赖 `sales_staff.id`，`douyin_webhook_events.lead_id` 依赖 `douyin_leads.id`，`wechat_tasks.lead_id/staff_id` 依赖 `douyin_leads.id` 与 `sales_staff.id`。

字段映射采用显式白名单：

1. `sales_staff` 覆盖销售 ID、商户、微信号/昵称、手机号、状态、排序、备注和时间字段。
2. `douyin_leads` 覆盖线索来源、客户信息、商户隔离、账号/会话归并、销售分配、状态、联系方式提取字段、JSON 原始数据和时间字段。
3. `douyin_webhook_events` 覆盖 webhook 原始事件、账号/会话、消息 ID、解析字段、`event_key`、重复标记、关联线索和 raw body。
4. `wechat_tasks` 覆盖任务类型、线索/销售/检测关联、目标昵称、消息、执行模式、状态、Agent 结果和时间字段。
5. SQLite 有但 PostgreSQL 无的字段记录为 `ignored_fields`；PostgreSQL 有但 SQLite 无且可默认/可空的字段记录为 `defaulted_fields`。

### 11.2 幂等与 apply 安全门

upsert key：

1. `sales_staff`：`id`。
2. `douyin_leads`：`account_open_id + conversation_short_id`。
3. `douyin_webhook_events`：`event_key`。
4. `wechat_tasks`：`id`。

安全门：

1. 默认 dry-run，PostgreSQL 写入为 `disabled`。
2. apply 必须显式 `--apply --yes`。
3. apply 只允许本地/dev host：`localhost`、`127.0.0.1`、`postgres`、`auto-wechat-postgres-dev`。
4. apply 目标 database 必须是 `auto_wechat`。
5. `APP_ENV=production` 时拒绝 apply。
6. 不允许隐式 `DATABASE_URL` 触发 apply。
7. 不允许 `delete`、`truncate`、`drop` 作为迁移策略。

### 11.3 阶段结论

1. P3-D2 只证明 4 表数据迁移脚本 dry-run 与本地/dev apply smoke 路径可用。
2. 本轮未连接宝塔生产，未读取生产 SQLite，未执行 production apply。
3. 本轮未切换默认 `DATABASE_URL`，未修改 9000 runtime DB 逻辑。
4. 本轮未改 9100 / Milvus / RAG，未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
5. 当前仍不能切换宝塔 SQLite 到 PostgreSQL。
6. 下一步建议 P3-D3：四表 API contrast 与 async PG pilot 方案。

## 12. P3-D3 四表 API contrast 与 async PG pilot 方案

任务：`P3-D3-DB-9000-LEADS-TASKS-API-CONTRAST-AND-ASYNC-PG-PILOT-1`

P3-D3 已新增四表 SQLite vs PostgreSQL contrast 框架、dev synthetic contrast smoke，以及 async PG pilot 方案文档：

```text
scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py
scripts/smoke_contrast_leads_tasks_core_dev.py
tests/test_contrast_leads_tasks_core_sqlite_vs_postgres.py
docs/ai/03_data_and_migration/LEADS_TASKS_ASYNC_PG_PILOT_PLAN.md
```

当前阶段结论：

1. P3-D1 已完成 `douyin_leads`、`douyin_webhook_events`、`sales_staff`、`wechat_tasks` 四表 PostgreSQL schema。
2. P3-D2 已完成四表数据迁移 dry-run 与 dev apply smoke。
3. P3-D3 已完成 synthetic/dev 级别 contrast 框架，包含行数、业务 key、必要字段、JSON / datetime warning 和 strict 模式。
4. 当前仍不能切换默认 `DATABASE_URL`。
5. 当前不默认开启 PG pilot。
6. 下一步是 P3-D4 runtime shadow read scaffolding，默认关闭。

pilot 顺序建议：

1. `sales_staff` read-only shadow。
2. `wechat_tasks` history read-only shadow。
3. `douyin_leads` list/detail read-only shadow。
4. `douyin_webhook_events` read-only shadow。
5. webhook write / task result write 最后灰度。

QPS600 准备项继续保持：

1. 使用 `asyncpg` 或 SQLAlchemy async / `AsyncSession`。
2. 明确 connection pool 与 worker 总连接数计算。
3. 设置 `statement_timeout` 和慢查询日志。
4. 验证高频索引。
5. webhook 幂等键和 `wechat_tasks` pending polling 锁策略必须落地。

边界确认：P3-D3 不迁移生产数据，不执行 production apply，不切换默认数据库，不默认开启 PG pilot。

## 13. P3-D4 runtime shadow read scaffolding 当前状态

任务：`P3-D4-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-READ-SCAFFOLDING-DEFAULT-OFF-1`

P3-D4 已把 P3-D3 的 async PG pilot 方案推进到最小运行态脚手架，但默认仍全部关闭，不能视为默认数据库切换。

已落地点：

1. 新增 leads/tasks PG shadow read 配置项，默认 false / 空 URL / 保守连接池参数。
2. 新增 `app/services/leads_tasks_pg_shadow.py`，负责 lazy async engine、只读 SELECT、timeout 隔离、异常 warning 和 URL 脱敏。
3. 新增 `app/services/leads_tasks_shadow_compare.py`，负责 count/key 轻量对照和 PII 脱敏摘要。
4. 接入 `GET /staff` 的 `sales_staff` list read-only shadow。
5. 接入 `GET /wechat-tasks` 的 `wechat_tasks` history read-only shadow。
6. 新增 `tests/test_leads_tasks_pg_shadow_runtime.py` 覆盖默认关闭、不开 engine、不连 PG、响应不变、异常吞掉、只读 SQL 和无 PG write。

仍未落地点：

1. `douyin_leads` runtime shadow hook。
2. `douyin_webhook_events` runtime shadow hook。
3. `wechat_tasks` pending polling shadow。
4. `wechat_tasks` result write。
5. webhook write。
6. 任何 PostgreSQL 写入。

readiness 影响：

1. 这一步只证明默认关闭的 shadow read 脚手架可以安全挂入两个低风险读接口。
2. SQLite 仍是唯一用户响应源。
3. `DATABASE_URL` 仍不能切换到 PostgreSQL。
4. `LEADS_TASKS_PG_PILOT_ENABLED` 和 `LEADS_TASKS_PG_READ_SHADOW_ENABLED` 不得默认开启。
5. QPS600 仍需要后续 async repository、连接池容量核算、真实索引 explain 和压测证明。

## 14. P3-D5 douyin_leads shadow read 与观测当前状态

任务：`P3-D5-DB-9000-LEADS-RUNTIME-SHADOW-READ-AND-OBSERVABILITY-1`

P3-D5 已把 read-only shadow 从 `sales_staff` 和 `wechat_tasks` 扩展到线索核心读路径：

1. `GET /leads`：`douyin_leads` list shadow read。
2. `GET /leads/{lead_id}`：`douyin_leads` detail shadow read。
3. 新增 `app/services/leads_tasks_shadow_observability.py`，提供结构化日志和轻量内存指标。

readiness 影响：

1. 当前已覆盖 `sales_staff list`、`wechat_tasks history`、`douyin_leads list`、`douyin_leads detail` 四个只读 shadow 点。
2. SQLite 仍是唯一响应源，PG shadow 不改变接口返回结构。
3. PG shadow 默认关闭；仍不得默认开启 `LEADS_TASKS_PG_PILOT_ENABLED` 或 `LEADS_TASKS_PG_READ_SHADOW_ENABLED`。
4. `douyin_leads` shadow 查询必须带 `merchant_id`，缺失时跳过，避免跨商户无隔离查询。
5. mismatch 现在可进入结构化日志和内存指标，但这不是 QPS600 观测的最终形态；后续仍需要进程级指标、慢查询、连接池、压测与告警体系。

仍未完成：

1. `douyin_webhook_events` runtime shadow hook。
2. webhook write / task result write。
3. pending polling 锁策略。
4. async repository / `AsyncSession` 全链路替换。
5. 宝塔真实数据 contrast。
6. QPS600 压测证明。

边界确认：P3-D5 不迁移生产数据，不执行 production apply，不切换默认数据库，不默认开启 PG pilot，不启用任何 PostgreSQL write。

## 15. P3-D6 webhook events shadow read 与 metrics 当前状态

任务：`P3-D6-DB-9000-WEBHOOK-EVENTS-SHADOW-READ-AND-METRICS-ENDPOINT-1`

P3-D6 已把 read-only shadow 覆盖扩展到 webhook 原始事件列表，并补充受限 metrics debug endpoint：

1. `GET /webhook-events`：`douyin_webhook_events` list shadow read。
2. `GET /admin/debug/leads-tasks-pg-shadow/metrics`：只读 metrics snapshot。

readiness 影响：

1. 当前 read-only shadow 覆盖 `sales_staff list`、`wechat_tasks history`、`douyin_leads list/detail`、`douyin_webhook_events list`。
2. SQLite 仍是唯一响应源，PG shadow 不改变接口返回结构。
3. `douyin_webhook_events` shadow 查询必须带 `merchant_id`；缺失时跳过，避免跨商户无隔离查询。
4. metrics endpoint 仅 admin / super_admin 可访问，不触发 PG 连接，不包含 PII。
5. 当前 observability 仍是进程内轻量指标，不等于 QPS600 的最终指标体系；后续仍需连接池、慢查询、压测、错误率和告警体系。

仍未完成：

1. webhook write。
2. task result write。
3. pending polling 锁策略。
4. async repository / `AsyncSession` 全链路替换。
5. 宝塔真实数据 contrast。
6. QPS600 压测证明。

边界确认：P3-D6 不迁移生产数据，不执行 production apply，不切换默认数据库，不默认开启 PG pilot，不启用任何 PostgreSQL write。

## 16. P3-D7 runtime shadow synthetic smoke 与回归当前状态

任务：`P3-D7-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-SYNTHETIC-SMOKE-AND-REGRESSION-1`

P3-D7 已为当前 P0 四表 read-only shadow 覆盖增加本地/dev synthetic smoke 与回归测试。新增脚本 `scripts/smoke_leads_tasks_runtime_shadow_dev.py` 使用 synthetic SQLite fixture 和 dev PostgreSQL URL，在显式 shadow 开关开启时验证五个 read-only operation；新增 `tests/test_leads_tasks_runtime_shadow_smoke.py` 覆盖默认关闭、开启记录 metrics、mismatch/error/timeout 隔离和 PG write 禁止。

当前 read-only shadow 覆盖：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

readiness 影响：

1. P3-D7 证明默认关闭场景不初始化 PG engine，shadow 不影响 SQLite 主响应。
2. P3-D7 证明 dev/synthetic 开启场景可以记录五类 operation 的 metrics。
3. P3-D7 证明 mismatch、PG error、timeout 不改变接口主响应。
4. P3-D7 证明 metrics endpoint 可读取快照且不触发额外 PG 连接。
5. P3-D7 仍不证明 production 切库可行，也不证明 QPS600 达标。

仍未完成：

1. webhook write。
2. `GET /wechat-tasks/pending` pending polling 与锁策略。
3. `POST /wechat-tasks/{task_id}/result` result write。
4. `notify_sales` / `detect_reply` 写链路。
5. async repository / `AsyncSession` 全链路替换。
6. 宝塔真实数据 contrast。
7. QPS600 baseline 与 shadow overhead 压测。

边界确认：P3-D7 不迁移生产数据，不执行 production apply，不切换默认数据库，不默认开启 PG pilot，不启用任何 PostgreSQL write。

下一步建议：P3-D8 进入本地 QPS baseline + shadow overhead 压测；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。

## 17. P3-D8 shadow QPS baseline 与 overhead 当前状态

任务：`P3-D8-DB-9000-LEADS-TASKS-QPS-BASELINE-AND-SHADOW-OVERHEAD-1`

P3-D8 已为 leads/tasks runtime read-only shadow 增加本地/dev synthetic benchmark 骨架，用于建立 shadow off baseline 与 shadow on overhead 的早期量化基线。

新增内容：

1. `scripts/benchmark_leads_tasks_shadow_overhead_dev.py`
2. `tests/test_leads_tasks_shadow_benchmark.py`
3. `docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_QPS_BENCHMARK_GUIDE.md`

benchmark 覆盖当前五个 read-only shadow operation：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

压测输出指标：

1. shadow off baseline：`total_requests`、`successful_requests`、`failed_requests`、`error_rate`、`throughput_rps`、`p50_ms`、`p95_ms`、`p99_ms`、`max_ms`、`min_ms`、`avg_ms`、`per_endpoint`。
2. shadow on overhead：同 baseline 指标，加上 shadow metrics。
3. overhead delta：`p50_delta_ms`、`p95_delta_ms`、`p99_delta_ms`、`avg_delta_ms`、`throughput_delta_percent`、`error_rate_delta`。
4. shadow metrics：`total_shadow_reads`、`total_shadow_pass`、`total_shadow_warn`、`total_shadow_failed`、`total_shadow_timeout`、`total_shadow_error`、`by_operation`。

readiness 影响：

1. P3-D8 只提供本地/dev synthetic baseline，不是 production 压测。
2. P3-D8 不证明 QPS600 已达标。
3. P3-D8 不改变 `DATABASE_URL` 切换准入条件。
4. 当前仍需 async repository、连接池容量核算、真实接口压测、慢查询日志、PostgreSQL 连接数和锁等待观测。

边界确认：

1. 不连接宝塔生产。
2. 不读取生产 SQLite。
3. 不执行 production apply。
4. 不切换默认 `DATABASE_URL`。
5. 不默认开启 PG pilot。
6. 不启用 PG write。
7. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

下一步建议：

1. `P3-D9`：async session / connection pool runtime design hardening。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 18. P3-D9 async engine / pool hardening 当前状态

任务：`P3-D9-DB-9000-LEADS-TASKS-ASYNC-ENGINE-POOL-HARDENING-1`

P3-D9 已针对 P3-D8 暴露的 shadow read engine 生命周期问题做运行时加固：

1. 新增 `app/services/leads_tasks_pg_engine.py`，按 event loop 缓存 async engine。
2. 同一 event loop 复用 engine，不同 event loop 不复用 engine，避免 D7 已修过的跨 loop 风险回归。
3. 默认关闭、URL 为空、SQLite URL、非 `postgresql+asyncpg://` URL 均不创建 engine。
4. `app/services/leads_tasks_pg_shadow.py` 改为复用 engine manager，不再每次 shadow query create/dispose。
5. benchmark 输出 engine manager snapshot，并在收尾显式 dispose。

P3-D8 到 P3-D9 的 dev/synthetic 对比：

| 指标 | P3-D8 shadow on | P3-D9 shadow on | 改善 |
|---|---:|---:|---:|
| throughput_rps | 39.301 | 441.390 | +402.089 rps，约 11.23 倍 |
| p50 | 536.994ms | 33.621ms | 降低 503.373ms，约 93.74% |
| p95 | 734.568ms | 155.103ms | 降低 579.465ms，约 78.89% |
| p99 | 909.916ms | 170.014ms | 降低 739.902ms，约 81.32% |

P3-D9 benchmark snapshot：

```text
BENCHMARK_PASS
engine_count=1
loop_count=1
created_count=1
disposed_count=0
cache_hit_count=183
cache_miss_count=1
total_shadow_error=0
total_shadow_timeout=0
```

readiness 影响：

1. P3-D9 证明每请求创建 engine / pool 的开销已经明显下降。
2. P3-D9 仍只是 read-only shadow 生命周期加固，不是 async repository 全链路替换。
3. P3-D9 benchmark 仍是 service-level dev/synthetic，不是真实 Nginx + Uvicorn + 网络链路。
4. `shadow_on throughput_rps=441.390` 仍不能宣称 QPS600 达标。
5. 当前仍不能切换默认 `DATABASE_URL`，不能默认开启 PG pilot，不能启用 PG write。

仍未完成：

1. 真实 Uvicorn / HTTP benchmark。
2. async repository / `AsyncSession` 全链路替换。
3. `GET /wechat-tasks/pending` pending polling 与锁策略。
4. `POST /wechat-tasks/{task_id}/result` result write。
5. webhook write 幂等、事务和回滚。
6. 宝塔真实数据 contrast。
7. production QPS600 压测证明。

边界确认：P3-D9 不迁移生产数据，不执行 production apply，不切换默认数据库，不默认开启 PG pilot，不启用任何 PostgreSQL write。

下一步建议：

1. `P3-D10`：真实 Uvicorn / HTTP benchmark 脚手架，继续默认关闭 PG pilot。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 19. P3-D10 HTTP benchmark scaffold 当前状态

任务：`P3-D10-DB-9000-LEADS-TASKS-REAL-HTTP-BENCHMARK-SCAFFOLD-1`

P3-D10 已为 leads/tasks read-only shadow 新增本地/dev 真实 HTTP benchmark 脚手架：

```text
scripts/benchmark_leads_tasks_shadow_http_dev.py
tests/test_leads_tasks_shadow_http_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_HTTP_BENCHMARK_GUIDE.md
```

覆盖接口：

1. `GET /staff`
2. `GET /wechat-tasks`
3. `GET /leads`
4. `GET /leads/{lead_id}`
5. `GET /webhook-events`
6. `GET /admin/debug/leads-tasks-pg-shadow/metrics`

readiness 影响：

1. P3-D10 补齐了真实 Uvicorn/HTTP 层 benchmark scaffold，比 P3-D8/P3-D9 service-level benchmark 更接近接口链路。
2. `--start-server` 模式可以用临时 SQLite fixture 分别启动 shadow off / shadow on 本地服务。
3. metrics endpoint 现在返回 `engine_manager_snapshot`，用于观察 engine 是否随请求线性增长。
4. P3-D10 仍只使用本地/dev synthetic 数据，不包含 Nginx、宝塔反代、多 worker、真实生产数据和真实生产 PostgreSQL。
5. P3-D10 不能作为 production QPS600 达标证明。
6. 当前仍不能切换默认 `DATABASE_URL`，不能默认开启 PG pilot，不能启用 PG write。

仍未完成：

1. Uvicorn / Gunicorn multi-worker benchmark。
2. Nginx / 宝塔反代链路 benchmark。
3. worker 数与 PostgreSQL pool 总连接数 sizing。
4. async repository / `AsyncSession` 全链路替换。
5. pending polling 锁策略和写入链路事务幂等。
6. staging / production 压测审批与执行记录。

下一步建议：

1. `P3-D11`：Uvicorn multi-worker benchmark / connection pool sizing。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 20. P3-D11 worker/pool sizing 当前状态

任务：`P3-D11-DB-9000-LEADS-TASKS-UVICORN-MULTI-WORKER-POOL-SIZING-1`

P3-D11 已在 P3-D10 HTTP benchmark 基础上新增本地/dev worker/pool sizing scaffold：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
tests/test_leads_tasks_shadow_worker_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_WORKER_POOL_SIZING_GUIDE.md
```

readiness 影响：

1. 开始量化 Uvicorn worker 数、每 worker PG pool、shadow 并发限制和采样率对吞吐 / p95 / p99 的影响。
2. 新增 `estimated_pg_connections = workers * (pool_size + max_overflow)`，用于 PostgreSQL 连接数预算。
3. 新增 shadow 降载指标：`sampled_out`、`concurrency_limited`、`current_shadow_inflight`、`max_shadow_inflight_seen`。
4. 采样和并发限制只影响 PG read-only shadow，不影响 SQLite 主响应。
5. 当前仍是本地/dev synthetic，不包含宝塔反代、真实 production 数据、真实 production PostgreSQL 和跨 worker metrics 聚合。

当前仍未完成：

1. 宝塔 staging / production 真实 HTTP 压测审批与记录。
2. Nginx / 宝塔反代链路 benchmark。
3. PostgreSQL 端实际连接数、慢查询、锁等待观测。
4. async repository / `AsyncSession` 全链路替换。
5. pending polling、task result write、webhook write 的事务和幂等设计。
6. production QPS600 证明。

边界确认：

1. P3-D11 不能作为 production QPS600 达标证明。
2. 当前仍不能切换默认 `DATABASE_URL`。
3. 当前仍不能默认开启 PG pilot。
4. 当前仍未启用 PG write。

下一步建议：

1. `P3-D12`：shadow sampling / max concurrency 策略调优。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。
