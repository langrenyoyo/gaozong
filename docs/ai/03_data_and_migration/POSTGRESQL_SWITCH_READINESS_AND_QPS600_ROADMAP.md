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

## 21. P3-D12 sampling / concurrency tuning 当前状态

任务：`P3-D12-DB-9000-LEADS-TASKS-SHADOW-SAMPLING-CONCURRENCY-TUNING-1`

P3-D12 已完成本地/dev synthetic sample rate 与 shadow max concurrency 调优：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py --quick-tuning
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_SAMPLING_TUNING_REPORT.md
```

readiness 影响：

1. benchmark 已覆盖 `shadow_sample_rate=1.0,0.5,0.2,0.1` 和 `shadow_max_concurrency=1,3,5,10`。
2. 输出 `theoretical_shadow_attempts`、`shadow_coverage_ratio` 和 `tuning_summary`。
3. 当前 recommended gray config 为 `workers=2`、`pool_size=5`、`max_overflow=5`、`shadow_max_concurrency=10`、`shadow_sample_rate=0.1`。
4. 本地/dev synthetic 最佳 `throughput_rps=570.102`、`p95=52.178ms`、`p99=59.518ms`，距离 QPS600 仍差约 `29.898 rps`。
5. sample rate 降低减少了实际 PG shadow read 覆盖，适合灰度降载，不适合替代全量 contrast。

当前仍未完成：

1. 宝塔 staging / production 真实 HTTP 压测审批与记录。
2. Nginx / 宝塔反代链路 benchmark。
3. PostgreSQL 端实际连接数、慢查询、锁等待观测。
4. async repository / `AsyncSession` 全链路替换。
5. pending polling、task result write、webhook write 的事务和幂等设计。
6. production QPS600 证明。

边界确认：

1. P3-D12 不能作为 production QPS600 达标证明。
2. 当前仍不能切换默认 `DATABASE_URL`。
3. 当前仍不能默认开启 PG pilot。
4. 当前仍未启用 PG write。

下一步建议：

1. `P3-D13`：runtime shadow gray config preset 与环境变量文档，默认关闭。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 22. P3-D13 shadow gray preset 当前状态

任务：`P3-D13-DB-9000-LEADS-TASKS-SHADOW-GRAY-PRESET-AND-RUNBOOK-1`

P3-D13 已新增 read-only shadow 灰度预设、启停 Runbook 和上线前准入检查：

```text
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_GRAY_PRESET_RUNBOOK.md
```

readiness 影响：

1. P3-D13 只把 P3-D12 的本地/dev synthetic 推荐值沉淀为 dev / staging / production 三档参数预设。
2. dev 推荐值沿用 `workers=2`、`pool_size=5`、`max_overflow=5`、`shadow_max_concurrency=10`、`shadow_sample_rate=0.1`。
3. staging 建议更保守，从 `shadow_sample_rate=0.05`、`shadow_max_concurrency=5` 开始，并要求人工审批、观察窗口和回滚负责人。
4. production 当前状态为 `not approved / not executed`，不得开启 PG pilot。
5. `.env.example` 只新增默认关闭的注释示例，不改变默认行为。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 `LEADS_TASKS_PG_PILOT_ENABLED` 或 `LEADS_TASKS_PG_READ_SHADOW_ENABLED`。
3. 当前仍不能启用 `LEADS_TASKS_PG_WRITE_ENABLED`。
4. read-only shadow preset 不等于 async repository 全链路替换完成。
5. read-only shadow preset 不等于 production QPS600 达标。

后续建议：

1. P3-D14：宝塔 staging read-only shadow 审批模板和执行记录。
2. P3-D15：宝塔 staging shadow 观察结果。
3. P3-E：继续按表组推进 PostgreSQL schema / migration / contrast，不能因为 shadow preset 直接切库。
## 23. P3-E1 agents/accounts schema batch 当前状态

任务：`P3-E1-DB-9000-POSTGRESQL-AGENTS-ACCOUNTS-SCHEMA-BATCH-1`

P3-E1 已开始第二批 P0 核心基础 schema，覆盖：

1. `ai_agents`
2. `douyin_authorized_accounts`
3. `douyin_account_agent_bindings`
4. `agent_knowledge_categories`

readiness 影响：

1. 9000 PostgreSQL Alembic 链路从 `0003_leads_tasks_core` 延伸到 `0004_agents_accounts_core`。
2. 智能体、授权账号、账号-Agent 绑定、Agent-知识分类绑定的 PG schema、关键索引和唯一约束开始落地。
3. `douyin_account_agent_bindings` 和 `agent_knowledge_categories` 使用局部唯一索引保护 active 业务语义。
4. 本批只是 schema batch，不迁移 SQLite 数据，不执行 apply，不启用 PG write。
5. 本批不改变 leads/tasks shadow gray preset 的状态；leads/tasks shadow 仍未 production 执行。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. 单表和局部表组 schema 验证不等于全系统切库完成。
5. production QPS600 仍需要真实 HTTP benchmark、连接池观测、慢查询和回滚演练证明。

后续建议：

1. `P3-E2`：agents/accounts 数据迁移 dry-run + dev apply smoke。
2. `P3-E3`：agents/accounts API contrast。
3. `P3-D14`：leads/tasks 宝塔 staging read-only shadow 人工审批与执行记录。

## 24. P3-E2 agents/accounts data migration dry-run / dev apply 当前状态

任务：`P3-E2-DB-9000-POSTGRESQL-AGENTS-ACCOUNTS-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

P3-E2 已为 agents/accounts 四表建立 SQLite -> PostgreSQL 数据迁移脚本和本地/dev synthetic apply smoke：

```text
scripts/migrate_agents_accounts_core_sqlite_to_postgres.py
scripts/smoke_migrate_agents_accounts_core_dev_apply.py
tests/test_migrate_agents_accounts_core_sqlite_to_postgres.py
```

readiness 影响：

1. 第二批 P0 核心域已从 schema batch 进入数据迁移 dry-run / dev apply smoke 验证。
2. 四表迁移顺序固定为 `ai_agents` -> `douyin_authorized_accounts` -> `douyin_account_agent_bindings` -> `agent_knowledge_categories`。
3. dry-run 输出 per-table `sqlite_source_rows`、`estimated_insert/update/skip`、`error_rows`、`ignored_fields`、`defaulted_fields`、`upsert_key`、脱敏 `mapping_preview` 和 warnings。
4. dev apply smoke 使用临时 synthetic SQLite，不读取 production SQLite，不迁移真实业务数据。
5. dev apply smoke 已验证第一次 insert=8，第二次 dry-run insert=0/update=8，说明本地/dev synthetic 幂等闭环可用。
6. `douyin_account_agent_bindings` 和 `agent_knowledge_categories` 的 active 局部唯一语义在迁移脚本中增加源数据冲突拦截。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. agents/accounts dev apply smoke 不等于 production apply 审批通过。
5. agents/accounts dev apply smoke 不等于全系统数据迁移完成。
6. production QPS600 仍需要真实 HTTP benchmark、连接池观测、慢查询和回滚演练证明。

后续建议：

1. `P3-E3`：agents/accounts API contrast，验证 SQLite / PG 响应语义。
2. `P3-E4`：agents/accounts runtime shadow read 方案，视接口复杂度决定。
3. `P3-D14`：leads/tasks 宝塔 staging read-only shadow 人工审批与执行记录。

## 25. P3-E3 agents/accounts contrast 当前状态

任务：`P3-E3-DB-9000-AGENTS-ACCOUNTS-API-CONTRAST-1`

P3-E3 已为 agents/accounts 四表新增离线 SQLite / PostgreSQL contrast 框架：

```text
scripts/contrast_agents_accounts_core_sqlite_vs_postgres.py
scripts/smoke_contrast_agents_accounts_core_dev.py
tests/test_contrast_agents_accounts_core_sqlite_vs_postgres.py
```

readiness 影响：

1. 第二批 P0 核心域已从 schema batch、data migration dry-run/dev apply 进入 SQLite vs PostgreSQL contrast 阶段。
2. contrast 覆盖 `ai_agents`、`douyin_authorized_accounts`、`douyin_account_agent_bindings`、`agent_knowledge_categories`。
3. 对照规则覆盖 count、key、必要列、JSON parse warning、datetime parse warning、nullable/default compatibility 与 `mismatch_count`。
4. key 规则与 P3-E2 迁移 upsert key 保持一致，避免 contrast 与迁移口径分叉。
5. dev synthetic smoke 会复用 P3-E2 helper apply synthetic SQLite 数据，再执行 strict contrast，并在结束时清理 synthetic PG 数据。
6. 敏感字段和 URL 继续脱敏，`open_id`、token、secret、raw JSON 不完整明文输出。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. P3-E3 仍是本地/dev synthetic contrast，不代表宝塔真实数据 contrast。
5. P3-E3 未接 runtime shadow，不改变线上接口响应源。
6. production QPS600 仍需要真实 HTTP benchmark、连接池观测、慢查询和回滚演练证明。

后续建议：

1. `P3-E4`：agents/accounts runtime shadow read 方案，默认关闭。
2. 或 `P3-F1`：`compute_accounts` / `compute_transactions` schema batch。
3. `P3-D14`：leads/tasks 宝塔 staging read-only shadow 人工审批与执行记录。

## 26. P3-F1 compute schema batch 当前状态

任务：`P3-F1-DB-9000-POSTGRESQL-COMPUTE-SCHEMA-BATCH-1`

P3-F1 已为 P0 核心算力域新增 PostgreSQL schema batch：

```text
migrations/postgres/auto_wechat/versions/0005_create_compute_core_tables.py
scripts/smoke_auto_wechat_alembic_compute_core.py
tests/test_9000_postgres_compute_core_schema.py
```

覆盖表：

1. `compute_accounts`
2. `compute_transactions`

readiness 影响：

1. 9000 PostgreSQL Alembic 链路从 `0004_agents_accounts_core` 延伸到 `0005_compute_core`。
2. `compute_accounts` 已落地商户唯一账户约束 `uk_compute_accounts_merchant`。
3. `compute_transactions` 已落地流水分页和类型筛选索引：`merchant_id + created_at`、`merchant_id + transaction_type + created_at`、`source + created_at`。
4. token 余额、流水变动和余额快照使用 `BIGINT`，延续当前整数 Token 口径，避免 Float 精度风险。
5. 当前模型没有 `account_id`、`transaction_id`、`idempotency_key` 和流水 `status`，P3-F1 不提前新增这些字段，不改变支付 / 扣费 / 充值逻辑。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. P3-F1 只是 compute 两表 schema batch，不迁移 SQLite 数据，不代表 compute 迁移完成。
5. 算力扣减并发事务、幂等键、余额不足策略和真实支付仍需后续独立设计与验证。
6. production QPS600 仍需要真实 HTTP benchmark、连接池观测、慢查询和回滚演练证明。

后续建议：

1. `P3-F2`：compute 数据迁移 dry-run + dev apply smoke。
2. `P3-F3`：compute API contrast，确认 `/compute/summary` 与 `/compute/transactions` 语义一致。
3. 不得因为 compute schema 已建就跳过 staging / production dry-run 审批。

## 27. P3-F2 compute data migration 当前状态

任务：`P3-F2-DB-9000-POSTGRESQL-COMPUTE-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

P3-F2 已为 compute 两表新增 SQLite -> PostgreSQL 数据迁移 dry-run / 受控 dev apply 工具链：

```text
scripts/migrate_compute_core_sqlite_to_postgres.py
scripts/smoke_migrate_compute_core_dev_apply.py
tests/test_migrate_compute_core_sqlite_to_postgres.py
```

readiness 影响：

1. 第三批 P0 核心域已从 schema batch 进入 data migration dry-run/dev apply 阶段。
2. 迁移顺序固定为 `compute_accounts` -> `compute_transactions`。
3. `compute_accounts` 按 `merchant_id` upsert；`compute_transactions` 按 SQLite id -> PostgreSQL id upsert。
4. token 余额、流水变动和余额快照继续保持整数，不引入 Float。
5. `delta_tokens = 0`、非整数 token 字段、datetime 解析失败都会进入异常行并阻断 apply。
6. 本轮仍不新增 `transaction_id`、`idempotency_key`、流水 `status`，不改变扣费 / 充值 / 套餐发放语义。

切库 readiness 结论不变：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. P3-F2 只是本地/dev synthetic 数据迁移闭环，不代表宝塔真实数据迁移完成。
5. 算力扣减并发事务、幂等键、余额不足策略和真实支付仍需后续独立设计与验证。
6. production QPS600 仍需要真实 HTTP benchmark、连接池观测、慢查询和回滚演练证明。

后续建议：

1. `P3-F3`：compute SQLite vs PostgreSQL contrast。
2. `P3-G0`：P1 表分级决策，继续按业务域推进，不跳过 dry-run / contrast / staging 审批。

## 28. P3-Z0 cutover gap audit 当前状态

任务：`P3-Z0-DB-9000-POSTGRESQL-CUTOVER-GAP-AUDIT-1`

P3-Z0 已新增 9000 SQLite -> PostgreSQL 默认切库缺口审计：

```text
docs/ai/03_data_and_migration/POSTGRESQL_CUTOVER_GAP_AUDIT.md
```

readiness 影响：

1. 现在仍不能切换 production `DATABASE_URL` 到 PostgreSQL。
2. 当前不建议继续对 leads/tasks 做更深的单表优化；应转入 cutover gap closure。
3. 切库第一硬阻塞是 9000 同步主数据库入口仍拒绝 PostgreSQL backend，且启动阶段仍调用 `Base.metadata.create_all(bind=engine)`。
4. PostgreSQL 已覆盖 11 张表，但 9000 ORM/runtime 仍有多张会被当前路由、service 或 scheduler 访问的表没有 PG schema。
5. 缺失表中，`external_merchant_bindings` 会影响真实 NewCar 登录 / 商户绑定；`reply_checks`、`check_configs`、`lead_notifications`、`lead_followup_records`、`feedback_records` 会影响线索、微信助手和任务回写；自动回复/工作台相关表会影响抖音 AI 客服与管理员页面；`compute_packages` 会影响算力套餐页。

切库最短路径更新为：

1. `P3-Z1`：补齐 PG runtime 缺失表 schema，并让 9000 支持受控 PostgreSQL staging 启动路径。
2. `P3-Z2`：补齐 cutover 必需表数据迁移脚本。
3. `P3-Z3`：staging PG `DATABASE_URL` 启动 smoke。
4. `P3-Z4`：production dry-run + apply 计划。
5. `P3-Z5`：production `DATABASE_URL` 切换窗口。

QPS600 结论不变：

1. P3-Z0 不证明 QPS600 达标。
2. 最短 cutover 可以先做同步 PostgreSQL staging 启动 smoke，但 production QPS600 仍必须通过 async repository、连接池、慢查询、锁等待和真实 HTTP 压测证明。
3. 当前仍不能默认开启 PG pilot，不能启用 PG write，不能宣称全系统 PostgreSQL ready。

## 29. P3-Z1 runtime gap schema batch 当前状态

任务：`P3-Z1-DB-9000-POSTGRESQL-RUNTIME-CUTOVER-GAP-SCHEMA-1`

P3-Z1 已新增 `0006_runtime_cutover_gap` Alembic revision，补齐 Z0 审计中缺失的 19 张 runtime 表：

```text
external_merchant_bindings
reply_checks
check_configs
lead_notifications
lead_followup_records
feedback_records
douyin_oauth_states
douyin_account_autoreply_settings
conversation_autopilot_states
douyin_conversation_read_states
douyin_private_message_sends
ai_reply_decision_logs
ai_auto_reply_runs
douyin_message_resource_downloads
douyin_image_uploads
autoreply_rollout_configs
autoreply_whitelist_entries
autoreply_admin_audit_logs
compute_packages
```

readiness 影响：

1. 9000 PostgreSQL schema 覆盖面从 11 张表扩展到 30 张 runtime 表。
2. NewCar 绑定、微信助手回写、抖音 AI 客服工作台、自动回复 rollout、资源记录和算力套餐的 runtime 表缺失风险已在 schema 层收敛。
3. 当前仍只完成 schema，不代表数据迁移完成。
4. 当前仍未处理 `app/database.py` PostgreSQL 同步主 engine 启动路径，也未处理 production 禁用自动 `Base.metadata.create_all` 的切换策略。

切库 readiness 结论不变：

1. 当前仍不能切换 production `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍不能启用 PG write。
4. P3-Z1 不迁移 SQLite 数据，不执行 production apply，不连接宝塔 production。
5. 下一步最短路径应进入 `P3-Z2` cutover 必需表数据迁移脚本，并在后续 staging `DATABASE_URL` smoke 中验证 9000 能以 PostgreSQL 启动。

## 30. P3-Z2 cutover 统一迁移脚本当前状态

任务：`P3-Z2-DB-9000-POSTGRESQL-CUTOVER-DATA-MIGRATION-1`

P3-Z2 已新增 9000 cutover 一次性迁移脚本：

```text
scripts/migrate_9000_sqlite_to_postgres_cutover.py
tests/test_cutover_sqlite_to_postgres_migration.py
```

readiness 影响：

1. 30 张 runtime 表已有统一 dry-run / apply 骨架。
2. 脚本默认 dry-run，apply 必须显式 `--apply --yes`。
3. apply 拒绝 `APP_ENV=production`，拒绝隐式 `DATABASE_URL`，只允许 dev/staging host 和 `auto_wechat` database。
4. 当前仍未在宝塔 staging 执行真实 SQLite -> PostgreSQL apply。
5. 当前仍不能切换 production `DATABASE_URL`。

下一步最短路径：

1. `P3-Z3`：在 staging 使用 PostgreSQL `DATABASE_URL` 启动 9000 smoke。
2. 该 smoke 必须先解决 `app/database.py` PostgreSQL 主 engine 启动路径和 production 禁用自动 `Base.metadata.create_all` 策略。

## 31. P3-Z3 PostgreSQL DATABASE_URL startup smoke scaffold 当前状态

任务：`P3-Z3-DB-9000-POSTGRESQL-DATABASE-URL-STARTUP-SMOKE-1`

P3-Z3 已完成最小 runtime 接入：

1. 9000 主同步 engine 支持 PostgreSQL backend。
2. `postgresql+asyncpg://` 会为同步主 engine 派生 `postgresql+psycopg://`，避免把 asyncpg 塞进同步 `SessionLocal`。
3. PostgreSQL 下不执行 `Base.metadata.create_all`，schema readiness 交给 Alembic。
4. 新增 startup smoke 脚本，验证 PostgreSQL `DATABASE_URL` 下 app 可创建。
5. 新增 `psycopg[binary]` 依赖，供 staging / production 同步主 runtime 使用。

readiness 影响：

1. 切库第一硬阻塞已从“代码直接拒绝 PostgreSQL engine”推进到“需要 staging 实库 smoke 验证”。
2. 当前仍不能切换 production `DATABASE_URL`。
3. 当前仍未证明 QPS600，最短 cutover 仍只是让同步 PostgreSQL runtime 可在 staging 启动。
4. production 前仍必须完成核心页面 / 核心接口 smoke、人工审批和回滚演练。

下一步最短路径：

1. `P3-Z4`：staging 核心页面 / 核心接口 smoke。
2. `P3-Z5`：production dry-run / apply / `DATABASE_URL` 切换 Runbook。

### 31.1 P3-Z3 实库验证记录（2026-07-09 dev 本地）

本轮在 dev 本地 PostgreSQL 容器（`auto-wechat-postgres-dev`，postgres:16-alpine，非 staging / production）完成 Z3 实库收尾，证明 9000 在 PostgreSQL 下可启动 + 数据可迁移 + 幂等可重跑。

实库验证证据链：

1. alembic smoke `SMOKE_PASS`：`scripts/smoke_auto_wechat_alembic_runtime_cutover_gap.py` 跑通 `alembic upgrade head` + asyncpg inspect，19 张 0006 表的字段 / 索引 / 约束全部对齐 `EXPECTED_TABLES`，FK 自动命名存在（`lead_notifications_*_fkey`、`ai_auto_reply_runs_trigger_event_id_fkey` 等）。
2. cutover dry-run `DRY_RUN_PASS`：`scripts/migrate_9000_sqlite_to_postgres_cutover.py` 扫描 30 张 runtime 表，0 error，0 warning，SQLite 源库基本空（仅 `compute_accounts` 1 行）。
3. cutover apply `APPLY_PASS`：`compute_accounts` 1 行落 PG，datetime 字段正确从 SQLite ISO 字符串转 PostgreSQL `timestamptz`。
4. 幂等性验证：重跑 apply，`compute_accounts` `insert=0 update=1`，count 仍为 1，`ON CONFLICT (id) DO UPDATE` 幂等机制正确。
5. 9000 真启动冒烟 `REAL_STARTUP_PASS`：`DATABASE_URL=postgresql+psycopg://...` 下 `TestClient` 进入 lifespan 正常，`GET /` 返回 200，同步 engine 直查 PG 得 `compute_accounts=1`、`alembic_version=0006_runtime_cutover_gap`。真启动时 patch 掉 `scheduler` / `hotkey_listener` / `desktop_overlay` 避免本机副作用。

关键环境发现：

- Windows 下 asyncpg 连本地 PG 必须用 `127.0.0.1`。`localhost` 优先解析到 IPv6 `::1`，asyncpg 走 IPv6 socket 在握手阶段 `ConnectionResetError [WinError 10054]`；`ssl=False`、`ssl='disable'`、`WindowsSelectorEventLoopPolicy`、`statement_cache_size=0` 均无效。psycopg 同步引擎连 `localhost` 不受影响。cutover / alembic smoke 都 `import asyncpg`，本机直连 URL 固定 `postgresql+asyncpg://auto_wechat:change_me@127.0.0.1:5432/auto_wechat`（host 在 `ALLOWED_APPLY_HOSTS` / `ALLOWED_DEV_HOSTS` 白名单内）。

审查 Major 处置：

- Maj-1（startup smoke 只验构建不验启动）：已补真启动冒烟，lifespan + engine 查 PG 闭环验证。
- Maj-3（`coerce_json` 坏数据只产 warning 不计 error）：dry-run 0 warning，SQLite 源数据干净，本轮不改 `coerce_json`；若 staging 数据出现 JSON warning 再升级为 error。
- Maj-5（0006 FK `ondelete` 与 ORM 一致性）：全链一致——`app/models.py` 14 个 FK 全不带 `ondelete`，0001-0006 migration 全链无任何 `ondelete`，都默认 NO ACTION，行为一致。前序 Minor：0003 `wechat_tasks.reply_check_id` 列存在但未建 FK 约束（ORM 有 FK），语义仍一致，留待后续严格对齐。
- Maj-2（cutover `ON CONFLICT (id)` 对 seed 表 unique violation 风险）、Maj-4（`read_postgres_snapshot` 全量 id 进内存）：本轮未改代码，留 P3-Z5 Runbook 约束（cutover 必须在 seed 之前；大表 snapshot 需评估行数）。

本轮仍未完成（保持 readiness 边界）：

1. 仍未在宝塔 staging 执行真实 SQLite -> PostgreSQL apply（本轮只 dev 本地）。
2. 仍未切换 production `DATABASE_URL`。
3. 仍未证明 QPS600（本轮只验证启动 + 迁移管道，未跑 HTTP 压测）。
4. SQLite 源库基本空（仅 1 行），cutover 对大数据量 / 多样数据的 mapping / coercion 路径未充分验证，P3-Z4 staging 冒烟需补充合成数据。
5. production 前仍必须完成核心页面 / 核心接口 smoke、人工审批和回滚演练。

## 32. P3-Z4 核心页面 / 接口冒烟当前状态

任务：`P3-Z4-DB-9000-POSTGRESQL-CORE-PAGE-SMOKE-1`

### 32.1 dev 本地冒烟结果（2026-07-09）

dev 本地 PG 容器（`auto-wechat-postgres-dev`，DATABASE_URL=`postgresql+psycopg://auto_wechat:change_me@127.0.0.1:5432/auto_wechat`）下完成两层冒烟：

1. HTTP 只读接口矩阵（`TestClient` 真启动，patch 掉 scheduler / hotkey / desktop_overlay 副作用）：12 个接口全部返回 401（NewCar auth 中间件拦截，TestClient 未带 token），**0 个 500 / ERR**，证明 8 模块路由全部注册可达 + 中间件链正常 + app 在 PG 下无 DB 崩溃。

   | 模块 | 接口 | 状态 |
   |------|------|------|
   | 抖音AI客服工作台 | `/ai-reply-decision-logs`, `/ai-auto-reply-runs` | 401 |
   | AI小高线索 | `/leads`, `/webhook-events` | 401 |
   | AI小高智能体 | `/agents` | 401 |
   | 抖音企业号管理 | `/integrations/douyin/accounts` | 401 |
   | 小高AI微信助手 | `/wechat-tasks`, `/checks` | 401 |
   | 小高算力 | `/compute/summary`, `/compute/packages` | 401 |
   | 管理员基础页面 | `/admin/autoreply/rollout/summary` | 401 |
   | NewCar 登录绑定 | `/auth/me` | 401 |

2. DB 层表 count 矩阵（同步 engine 直查 PG）：16 张核心表全部可读，无异常，`compute_accounts=1`（apply 迁移数据），其余空表。

结论：dev 环境下 9000 在 PostgreSQL 运行模式的"app 启动 + 路由 + 中间件 + DB 表可读"四层全部可用。

### 32.2 dev 冒烟局限

1. HTTP 401 在业务 handler 之前拦截，未触发 handler 内 ORM 查询。
2. SQLite 源库基本空（仅 `compute_accounts` 1 行），handler 深度查询返回空列表，验证价值有限。
3. 抖音AI客服工作台的 9100 代理路径（`douyin_ai_cs_proxy`）不在本轮 9000 PG 迁移范围（9100 独立服务，未来用 `RAG_DATABASE_URL`）。

handler 内 ORM 查询的深度验证 + 真实数据渲染留 P3-Z4 staging 阶段（带 auth token + 真实数据）。

### 32.3 staging 冒烟 Runbook（人工执行，禁止自动）

staging / production 属于宝塔环境，只写 Runbook，必须人工审批后执行。

前置条件：

1. staging PostgreSQL 实例已就绪，`alembic upgrade head` 到 `0006_runtime_cutover_gap`，30 张 runtime 表 schema 齐全（用 `scripts/smoke_auto_wechat_alembic_runtime_cutover_gap.py` + `SMOKE_DATABASE_URL=staging` 验证，注意 asyncpg 在 Windows 用 127.0.0.1，staging Linux 不受此限制）。
2. staging SQLite 现有数据已备份（`cp data/auto_wechat.db data/auto_wechat.db.pre-cutover`）。
3. staging `DATABASE_URL` 当前仍指向 SQLite（回滚基线）。

操作步骤：

1. 在 staging 跑 cutover dry-run：`python scripts/migrate_9000_sqlite_to_postgres_cutover.py --sqlite-db-path data/auto_wechat.db --postgres-url <staging-pg-url>`，确认 `DRY_RUN_PASS` 且 `error=0`。若出现 JSON / datetime warning，记录并评估是否阻塞（见 Maj-3）。
2. 在 staging 跑 cutover apply：加 `--apply --yes`，确认 `APPLY_PASS`。apply 前确认 staging PG 为 alembic upgrade head 后的空库或 cutover-before-seed 顺序（见 Maj-2）。
3. 切 staging `DATABASE_URL` 指向 PostgreSQL（`postgresql+psycopg://...`），保留原 SQLite URL 为 `SQLITE_DATABASE_URL_ROLLBACK` 备用。
4. 重启 9000 staging，观察启动日志出现 `db_schema stage=startup_skip_create_all backend=postgresql`。
5. 带 staging auth token 对 8 模块 12 接口跑 GET，预期全部 200 且返回真实数据结构（非空）。
6. 前端连 staging，人工核对 8 个核心页面（抖音AI客服工作台 / AI小高线索 / AI小高智能体 / 抖音企业号管理 / 小高AI微信助手 / 小高算力 / 管理员基础页面 / NewCar 登录外部账号绑定）渲染正常。
7. 观察 staging 24h，确认无异常日志、无 500、无连接池耗尽。

通过标准：12 接口 200 + 8 页面正常 + 24h 无异常。

回滚（出现任何异常立即执行）：

1. staging `DATABASE_URL` 切回原 SQLite URL。
2. 重启 9000 staging，确认日志 `backend=sqlite` + `Base.metadata.create_all`。
3. 确认业务恢复正常（SQLite 数据未动，只是 PG 导入了一份副本）。
4. 排查异常后，重新走 dry-run → apply → 切换流程。

边界（Z4 staging 不得越界）：

1. 不得直接操作 production `DATABASE_URL`（production 切换属 P3-Z5，需独立审批）。
2. 不得启用 PostgreSQL 写入灰度（runtime shadow read 仍默认关闭）。
3. 不得触发抖音发送 / 微信发送 / 私信发送 / 自动回复闸门（冒烟只读）。
4. 不得改支付 / 扣费 / 充值 / 套餐发放业务逻辑。

## 33. P3-Z5 production cutover Runbook

任务：`P3-Z5-DB-9000-POSTGRESQL-PRODUCTION-CUTOVER-RUNBOOK-1`

P3-Z5 只输出生产切换 Runbook，禁止自动执行。宝塔 production 的任何 `DATABASE_URL` 切换、cutover apply、重启都必须人工审批后手动执行。

### 33.1 审批窗口（硬约束）

1. production 切换必须预留人工审批窗口，禁止脚本化一键切换。
2. 审批需明确：变更时间（避开业务高峰）、执行人、回滚负责人、观察时长、通知干系人。
3. 审批通过前不得在 production 执行 cutover apply 或 `DATABASE_URL` 切换。

### 33.2 前置就绪（Z1-Z4 全部通过方可进入 Z5）

1. `0006_runtime_cutover_gap` 已在 production PG `alembic upgrade head` 完成，30 表 schema 齐全。
2. cutover 脚本 dry-run / apply / 幂等已在 dev 或 staging 验证通过（见节 31.1、32.1）。
3. 核心页面 / 接口 staging 冒烟通过（见节 32.3）。
4. 回滚预案已在 staging 演练一次。

### 33.3 生产切换步骤

1. 备份 production SQLite：`cp data/auto_wechat.db data/auto_wechat.db.pre-cutover-<date>`，确认备份可读。
2. 确认 production PG `alembic_version` 为 `0006_runtime_cutover_gap`，30 表存在。
3. production cutover dry-run：`python scripts/migrate_9000_sqlite_to_postgres_cutover.py --sqlite-db-path data/auto_wechat.db --postgres-url <production-pg-url>`（注意 production apply 被脚本闸门拒绝 `APP_ENV=production`，dry-run 只读安全）。确认 `DRY_RUN_PASS` 且 `error=0`，评估大表行数（见 33.6 Maj-4）。
4. 审批二次确认后，在 production PG 执行 apply（需临时以非 production 环境变量跑，或由 DBA 手工执行等价 upsert，全程留审计日志）。
5. **compose PG 化**（宝塔生产用 `docker-compose.yml`，当前 9000 服务 `auto-wechat-api` 是 SQLite-only，必须改才能切 PG；C-D2/C-E6）：
   - 5.1 `docker-compose.yml` 已内置 `postgres` 服务（方案 a，`postgres:16-alpine` + 独立 volume `./docker-data/postgres` + healthcheck）+ 9000 `environment.DATABASE_URL` 指向 `postgres:5432`（用 `${PG_USER:-auto_wechat}`/`${PG_PASSWORD}`/`${PG_DB:-auto_wechat}` 拼接）。`.env` 必须设 `PG_PASSWORD=<强密码>`（postgres 镜像拒绝空密码，会 fail-fast）；可选 `PG_USER`（默认 `auto_wechat`）、`PG_DB`（默认 `auto_wechat`）。回滚无需 `SQLITE_DATABASE_URL_ROLLBACK`（注释 compose 的 `DATABASE_URL` 行即回 config 默认 `sqlite:///`，见 33.4）。
   - 5.2 `docker-compose.yml` 已加 9000 `depends_on: postgres (condition: service_healthy)`，PG 就绪后才起 9000。9100 服务（`xg-douyin-ai-cs`）保持 SQLite 不动（未来走 `RAG_DATABASE_URL`，C-E5）；前端服务不动。
   - 5.3 9000 服务的 SQLite 卷 `./docker-data/auto_wechat_9000:/workspace/data` 保留挂载，过渡期作为回滚备份（切 PG 后 9000 不再写 SQLite，但回滚需要）。
   - 5.4 核对 `.env` 的 `APP_ENV=production`、`DY_SECRET_KEY` 非空且与上游一致（否则 development 模式下 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 静默放行 webhook，P0-DEV-A1 生产强制验签失效；C-D1/C-E3）。
   - 5.5 **镜像脚本/迁移（C-E6，已完成）**：`Dockerfile.backend.dev` 已补 `COPY scripts/` + `COPY migrations/`（含 `migrations/postgres/auto_wechat/alembic.ini`，`script_location=%(here)s`）。Z5 执行前需 `docker compose -f docker-compose.yml build --no-cache auto-wechat-api`（或 `up -d --build`）让新 COPY 生效；生效后容器内可直接跑 `python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head` 与 cutover 脚本。env.py 仅依赖 `app.database_url` + `DATABASE_URL` 环境变量，依赖齐全。
6. 重启 9000 production（`docker compose -f docker-compose.yml up -d --build`），并执行切换后核验（确保切干净，新数据不再进 SQLite）：
   - 6.1 启动日志出现 `db_schema stage=startup_skip_create_all backend=postgresql`（确认没回退 `create_all`）。
   - 6.2 `docker compose exec auto-wechat-api python -c "from app.database import DATABASE_RUNTIME; print(DATABASE_RUNTIME.backend, DATABASE_RUNTIME.safe_url)"` 必须输出 `postgresql ...`（非 `sqlite`）。
   - 6.3 `docker compose exec auto-wechat-api ls -la /workspace/data/auto_wechat.db*`：切 PG 后该文件应冻结（mtime 不再更新，`-wal`/`-shm`/`-journal` 不增长）= 新数据已不走 SQLite。
   - 6.4 若 6.2 输出 `sqlite` 或 6.3 文件仍增长 → 切换未生效，立即按 33.4 回滚，排查 `.env` 的 `DATABASE_URL` 是否漏配（风险 A：默认回 `sqlite:///`）。
7. 带 production auth token 对 8 模块 12 接口跑 GET，预期全部 200 且数据非空。
8. 前端核对 8 个核心页面渲染正常。
9. 观察 ≥ 48h（含完整业务周期），记录接口延迟、5xx、连接池、慢查询。

通过标准：12 接口 200 + 8 页面正常 + 48h 无异常 + 无 5xx 突增。

### 33.4 回滚手册

触发条件：任何 5xx 突增 / 页面异常 / 数据不一致 / 业务中断。

1. 注释 `docker-compose.yml` 里 9000 服务的 `DATABASE_URL` 行与 `depends_on` 段（让 `config.py` 默认值 `sqlite:///data/auto_wechat.db` 生效）。
2. `docker compose -f docker-compose.yml up -d --build auto-wechat-api`（**不重启 postgres**，保留 PG 数据），确认 9000 日志 `backend=sqlite` + `Base.metadata.create_all`。
3. 确认业务恢复正常（SQLite 数据未动，PG 只是多了一份副本）。
4. **不删** SQLite 文件，**不清** PG volume（PG 副本保留供排查）。
5. 排查问题后，重新走 33.3 流程。

### 33.5 运行参数建议（验收 #8）

起点值取自节 21 P3-D12 dev synthetic 调优结论，production 需结合节 5.2 公式和实际压测核算：

| 参数 | dev 起点值 | 生产核算要求 |
|------|-----------|--------------|
| `workers`（uvicorn/gunicorn） | 2 | 按 CPU 核数和压测调整；`理论最大连接 = workers * (pool_size + max_overflow)` |
| `DB_POOL_SIZE` | 5 | 单 worker 最大连接 = `pool_size + max_overflow` |
| `DB_MAX_OVERFLOW` | 5 | 突发流量缓冲 |
| PostgreSQL `max_connections` | — | `>= workers * (pool_size + max_overflow) + 预留（maintenance/migration/psql/monitoring ≥ 10）` |
| `DB_STATEMENT_TIMEOUT_MS` | 200-500 | 节 5.3 按 SLA 倒推，webhook / polling / 分页 / 报表建议 200ms，慢路径放宽到 500ms |
| `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | 现有配置 | 按节 5.2 配置入口保留 |
| shadow `sample_rate` / `max_concurrency` | 默认关闭 | 灰度时 `0.1 / 10`（节 21）；切换期建议关闭 runtime shadow read |

重要边界：节 21 dev synthetic `throughput_rps=570.102 / p95=52ms / p99=59ms` **不是 production QPS600 证明**，距 QPS600 仍差约 30 rps。production QPS600 达标必须在独立压测环境按节 5.6 场景跑 HTTP 基准测试（不在宝塔生产跑），审批后另行记录。

### 33.6 Maj-2 / Maj-4 约束

- **Maj-2（cutover 必须在 seed 之前）**：production PG 在 `alembic upgrade head` 后应为空库，cutover 完成后再执行业务 seed（`compute_packages` 套餐、`autoreply_rollout_configs` global scope 等）。若 PG 已有 seed 且 id 与 SQLite 错位，cutover 的 `ON CONFLICT (id) DO UPDATE` 不触发，业务唯一键冲突会 `unique_violation` 导致单事务整批回滚。有 uk 的敏感表：`autoreply_rollout_configs`、`autoreply_whitelist_entries`、`douyin_account_autoreply_settings`、`conversation_autopilot_states`、`douyin_conversation_read_states`、`douyin_oauth_states`、`douyin_private_message_sends(auto_reply_run_id)`、`check_configs`、`ai_auto_reply_runs`。
- **Maj-4（snapshot 全量 id 进内存）**：`read_postgres_snapshot` 对每表 `SELECT id FROM "<table>"` 全量拉内存。生产大表（`douyin_webhook_events` / `ai_reply_decision_logs` / `ai_auto_reply_runs` / `douyin_private_message_sends` 可能百万行）迁移前必须评估行数；超阈值（建议 10 万行）需改 snapshot 策略（临时表 anti-join 或按 id 分批），当前脚本未实现分批。

### 33.7 不越界

1. 不改 9100 / Milvus / RAG（独立服务，未来用 `RAG_DATABASE_URL`）。
2. 不触发 LLM / 抖音发送 / 微信发送 / 私信发送 / 自动回复闸门。
3. 不改支付 / 扣费 / 充值 / 套餐发放业务逻辑。
4. 不启用 PostgreSQL 写入灰度（runtime shadow read 默认关闭）。
5. 不在宝塔生产环境跑 HTTP 压测。
6. 不把 dev / staging 的合成 QPS 当作 production QPS600 证明。

### 33.8 Z5 交付边界

本轮 Z5 只输出 Runbook，不执行任何 production 操作。production 切换需另起审批窗口，由人工按 33.1-33.3 执行，按 33.4 回滚预案保障。

## 34. P3-E-9100 production cutover Runbook

任务：`P3-E-9100-RAG-POSTGRESQL-PRODUCTION-CUTOVER-RUNBOOK-1`

P3-E-9100 覆盖 9100（apps/xg_douyin_ai_cs）RAG metadata 7 表从 SQLite 切 PostgreSQL（方案 A 第二个 database `xg_douyin_ai_cs` via `RAG_DATABASE_URL`）。本轮 P3-E 第 2 步已落地生产 `docker-compose.yml` 改动（postgres 挂载 init-prod + 9100 切 RAG_DATABASE_URL + depends_on + 移除 SQLite 路径），compose 文件层面已就绪；Z5 的 production `alembic upgrade` + cutover apply + compose up 仍需审批窗口人工执行，禁止脚本化一键切换。Milvus 是向量检索副本，embedding_json 平移到 PG metadata DB，不动 Milvus。

### 34.1 审批窗口（硬约束）

1. production 切换必须预留人工审批窗口，禁止脚本化一键切换。
2. 审批需明确：变更时间、执行人、回滚负责人、观察时长、通知干系人。
3. 审批通过前不得在 production 执行 cutover apply 或 `RAG_DATABASE_URL` 生效的 `compose up`。

### 34.2 前置就绪（P3-D/D2/D3 + dev smoke 全部通过方可进入 Z5）

1. P3-D/D2/D3 已完成：alembic `0002_create_rag_metadata`（7 表 PG schema）+ `database.py` `get_rag_engine()` factory + `repository.py` / `knowledge_training_service.py` 跨方言改写（见 POSTGRESQL_MIGRATION_NOTES.md 节 58）。
2. production PG 第二个 database `xg_douyin_ai_cs` 已由 `docker/postgres/init-prod/010_create_rag_database.sh` 在 postgres 首次启动时创建（幂等；**已有数据卷时 init 脚本不运行，需手动 `docker compose exec postgres createdb --owner ${PG_USER:-auto_wechat} xg_douyin_ai_cs`**）。
3. 9100 production PG `alembic upgrade head` 完成，revision = `0002_create_rag_metadata`，7 表齐全（`docker compose exec xg-douyin-ai-cs python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head`）。
4. cutover 脚本 `scripts/migrate_9100_sqlite_to_postgres_cutover.py` dry-run / apply / 静态结构测试在 dev 验证通过（见 `tests/test_9100_cutover_sqlite_to_postgres_migration.py` 10 测试）。
5. dev 真实 PG smoke 通过（`scripts/smoke_9100_rag_pg_runtime.py` 连本地 docker PG，alembic upgrade + 8 表 inspect）。
6. 回滚预案已在 staging 演练一次。

### 34.3 生产切换步骤

1. 备份 production SQLite：`cp data/xg_douyin_ai_cs.db data/xg_douyin_ai_cs.db.pre-cutover-<date>`（宝塔宿主机 `./docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db`，切 PG 前 9100 仍写此文件），确认备份可读。
2. 确认 production PG `xg_douyin_ai_cs` 库存在且 `alembic_version` = `0002_create_rag_metadata`，7 表存在。
3. production cutover dry-run（只读安全，production apply 被脚本闸门拒绝）：
   ```
   python scripts/migrate_9100_sqlite_to_postgres_cutover.py \
     --sqlite-db-path ./docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db \
     --postgres-url <production-rag-pg-url>
   ```
   确认 `DRY_RUN_PASS` 且 `error=0`，评估 chunks 表行数（见 34.6 embedding_json 平移开销）。
4. 审批二次确认后，在 production PG 执行 apply（脚本拒绝 `APP_ENV=production`，需临时以非 production 环境变量跑，或由 DBA 手工执行等价 upsert，全程留审计日志）：
   ```
   APP_ENV=staging python scripts/migrate_9100_sqlite_to_postgres_cutover.py \
     --sqlite-db-path ./docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db \
     --postgres-url <production-rag-pg-url> --apply --yes
   ```
   注意 apply 不允许隐式 `RAG_DATABASE_URL`，必须显式 `--postgres-url` 且 host 在 `localhost/127.0.0.1/postgres/auto-wechat-postgres-dev`，database 必须是 `xg_douyin_ai_cs`。
5. **compose 已就绪（本轮 P3-E 第 2 步已落地）**：`docker-compose.yml` 9100 服务已内置 `RAG_DATABASE_URL: postgresql+psycopg://${PG_USER:-auto_wechat}:${PG_PASSWORD}@postgres:5432/xg_douyin_ai_cs` + `depends_on: postgres (condition: service_healthy)` + 移除 `XG_DOUYIN_AI_CS_DB_PATH`；postgres 服务已挂载 `./docker/postgres/init-prod:/docker-entrypoint-initdb.d:ro`（首次启动建第二个 database）。Z5 执行只需 `docker compose -f docker-compose.yml build --no-cache xg-douyin-ai-cs` + `up -d xg-douyin-ai-cs` 让新配置生效（镜像 `Dockerfile.backend.dev` 的 `COPY migrations/` 递归含 `xg_douyin_ai_cs/` 子目录，alembic 可用）。
6. 重启 9100 production，执行切换后核验（确保切干净，新 RAG 写入不再进 SQLite）：
   - 6.1 启动日志 / `/health` 反映 backend=postgresql（9100 `get_database_runtime(settings.rag_database_url).backend`）。
   - 6.2 `docker compose exec xg-douyin-ai-cs python -c "from apps.xg_douyin_ai_cs.rag.database import get_database_runtime; print(get_database_runtime().backend, get_database_runtime().safe_url)"` 必须输出 `postgresql ...`（非 `sqlite`）。
   - 6.3 `docker compose exec xg-douyin-ai-cs ls -la /data/xg_douyin_ai_cs.db*`：切 PG 后该文件应冻结（mtime 不再更新）= 新 RAG 写入已不走 SQLite。
   - 6.4 若 6.2 输出 `sqlite` 或 6.3 文件仍增长 → 切换未生效，立即按 34.4 回滚，排查 `.env` 或 compose 的 `RAG_DATABASE_URL` 是否漏配。
7. 工作台冒烟：RAG 检索 / 回复建议 / 知识训练查询返回正常数据（`tenant_id=xiaogao_system` scope 命中），反馈摄入写入 PG metadata。
8. 观察 ≥ 48h，记录 RAG 检索延迟、9100 5xx、连接池、慢查询。

通过标准：6.2 postgresql + 工作台 RAG 正常 + 48h 无异常 + 无 5xx 突增。

### 34.4 回滚手册

触发条件：9100 5xx 突增 / RAG 检索异常 / 知识训练写入失败 / 数据不一致。

1. 在 `docker-compose.yml` 9100 服务注释 `RAG_DATABASE_URL` 与 `depends_on` 段，恢复 `XG_DOUYIN_AI_CS_DB_PATH: /data/xg_douyin_ai_cs.db`（让 `config.py` 的 `settings.rag_database_url` property 回退 SQLite）。
2. `docker compose -f docker-compose.yml up -d --build xg-douyin-ai-cs`（**不重启 postgres**，保留 PG 数据），确认 9100 日志 backend=sqlite。
3. 确认工作台 RAG 恢复正常（SQLite 数据未动，PG 只是多了一份副本）。
4. **不删** SQLite 文件，**不清** PG volume（PG 副本保留供排查）。
5. 排查问题后，重新走 34.3 流程。

### 34.5 运行参数建议

9100 PG engine 运行参数取自 `apps/xg_douyin_ai_cs/config.py`（`rag_db_pool_size` / `rag_db_max_overflow` / `rag_db_pool_timeout` / `rag_db_pool_recycle` / `rag_db_statement_timeout_ms`），production 需结合实际压测核算：

| 参数 | dev 起点值 | 生产核算要求 |
|------|-----------|--------------|
| `workers`（9100 uvicorn） | 1-2 | 9100 是 RAG + LLM 回复建议，并发低于 9000；按 CPU 核数调整 |
| `RAG_DB_POOL_SIZE` | 配置默认 | 单 worker 最大连接 = `pool_size + max_overflow` |
| `RAG_DB_MAX_OVERFLOW` | 配置默认 | 突发流量缓冲 |
| PostgreSQL `max_connections` | — | 9100 与 9000 共享同一 PG 实例，`>= 9000 连接 + 9100 连接 + 预留` |
| `RAG_DB_STATEMENT_TIMEOUT_MS` | 配置默认 | RAG 检索 / 向量平移查询建议宽松（embedding_json 是大 TEXT）|

### 34.6 chunks 大表约束（embedding_json 平移开销）

- `knowledge_chunks` 每行含 `embedding_json`（1536 维向量 JSON 字符串，约 15-30 KB/行），chunks 行数 = documents × 切片数，可能数千～数万行。
- cutover `apply_postgres_rows` 对每行 `embedding_json` 走 `coerce_json`（json.loads + json.dumps 重新序列化），CPU 开销 = 行数 × 单行 JSON 解析开销。数万行级迁移需评估 apply 耗时（建议先 dry-run 看行数，超 1 万行考虑分批或低峰执行）。
- `read_postgres_snapshot` 对每表全量拉主键进内存：9100 主键 id 是 int（sessions 是 training_id 字符串），内存占用远小于 9000 业务大表，但仍需评估 chunks 行数。
- Milvus 不动：embedding_json 平移到 PG 是 metadata 副本，Milvus 向量索引独立保留。

### 34.7 不越界

1. 不改 9100 RAG / Milvus 检索逻辑、训练写入 / 反馈摄入业务逻辑、auto_send gate。
2. 不触发 LLM / 抖音发送 / 私信发送 / 自动回复闸门。
3. 不改 9000 主库（独立切 PG，9100 只用第二个 database）。
4. 不把前端 tenant_id / merchant_id / douyin_account_id 当可信上下文。
5. 不在 .env.example 写真实 URI / token / password。

### 34.8 Z5 交付边界

本轮 P3-E（第 1-4 步）交付：迁移脚本 + 静态测试 + 生产 compose 改动 + Z5 Runbook + dev 真实 PG smoke。compose 文件层面已就绪，但 production 的 `alembic upgrade` + cutover apply + `compose up` 仍需另起审批窗口由人工按 34.1-34.3 执行，按 34.4 回滚预案保障。

### 34.9 staging 预发布演练（production 前置硬门禁，17 步）

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / B2。本节是 34.2.6 所述"staging 演练"的完整流程。production cutover（34.3）前必须在独立 staging 环境完整跑通一次"切换 + 回滚 + 再前进"，签字归档后方可进入 34.1 审批窗口。staging 禁止共享 production PG 实例或直连生产 SQLite。

1. staging 独立环境：独立 PG 实例（不共享 dev / production volume），`.env` 设 `APP_ENV=staging`、`PG_PASSWORD` 非空、`RAG_DATABASE_URL` 指向 staging PG。
2. staging 数据准备：从 production SQLite 副本复制（`cp data/xg_douyin_ai_cs.db` 到 staging 宿主机），禁止 staging 直连生产文件或生产 PG。
3. staging postgres 首启：`docker compose up -d postgres`，确认 `init-prod/010_create_rag_database.sh` 建出第二个 database `xg_douyin_ai_cs`（`docker compose exec postgres psql -U ${PG_USER} -l` 可见）。
4. staging 9100 alembic upgrade：`docker compose exec xg-douyin-ai-cs python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head`，确认 `alembic_version` = `0002_create_rag_metadata`，7 表齐全。
5. staging cutover dry-run：`python scripts/migrate_9100_sqlite_to_postgres_cutover.py --sqlite-db-path <staging-sqlite> --postgres-url <staging-pg>`，确认 `DRY_RUN_PASS` 且 `error=0`，记录 chunks 行数（评估 34.6 开销）。
6. staging cutover apply：`APP_ENV=staging python scripts/migrate_9100_sqlite_to_postgres_cutover.py --sqlite-db-path <staging-sqlite> --postgres-url <staging-pg> --apply --yes`，记录耗时。
7. staging 9100 compose up（`RAG_DATABASE_URL` 指向 staging PG + `depends_on: postgres`），容器 healthy。
8. staging `/ready` 验证：返回 200 且 checks 全 pass（backend=postgresql + database_name=xg_douyin_ai_cs + alembic_revision=head + critical_tables knowledge_documents/knowledge_chunks pass）。
9. staging 工作台冒烟：RAG 检索 / 回复建议 / 知识训练查询命中 `tenant_id=xiaogao_system` scope 数据。
10. staging 反馈摄入：触发一次反馈写入，确认落 PG metadata（`SELECT` 验证）；同时确认 SQLite 文件 mtime 冻结（新写入不走 SQLite）。
11. staging 回滚演练：注释 compose `RAG_DATABASE_URL` + 恢复 `XG_DOUYIN_AI_CS_DB_PATH` + `up -d --build xg-douyin-ai-cs`，确认 9100 回到 SQLite backend + 工作台 RAG 恢复。
12. staging 回滚后再前进：重新 `--apply`（幂等 `ON CONFLICT DO UPDATE ... RETURNING xmax=0`）+ `up`，确认 PG 恢复正常，验证幂等性。
13. staging 观察 ≥ 24h：记录 RAG 检索延迟、9100 5xx、连接池、慢查询。
14. staging 全量测试：`pytest tests/test_9100_cutover_sqlite_to_postgres_migration.py` + `python scripts/smoke_9100_rag_pg_runtime.py --database-url <staging-pg>` 通过。
15. staging 演练归档：耗时、坑、回滚/再前进验证记录写入交付物。
16. staging 签字门禁：执行人 + 审批人 + DBA 三方签字后方可进入 34.1 production 审批窗口。
17. 演练有效期：staging 演练到 production 切换间隔 ≤ 7 天；超期或中间有代码 / 迁移变更须重跑演练（避免环境漂移）。

通过标准：步骤 5-10 全 pass + 步骤 11-12 回滚/再前进验证通过 + 步骤 16 三方签字。

### 34.10 生产环境控制矩阵

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / B2。本节细化 34.1 审批窗口与 34.4 回滚的生产控制项，作为 Z5 执行的硬约束清单（与 34.3 切换步骤、34.4 回滚手册配套使用）。

| 控制项 | 约束 |
|--------|------|
| 维护窗口 | 低峰期（建议 02:00–05:00），窗口 ≥ 2h；提前 ≥ 24h 通知业务方 + 客服（9100 工作台可能短暂不可用）。 |
| 执行人 | 1 人主执行 + 1 人复核；主执行须能直接操作宝塔宿主机与 `docker compose`。 |
| 审批人 | 1 人审批（技术负责人），签字归档；审批人不得兼任执行人。 |
| DBA | 34.3 步骤 4（production PG apply）须 DBA 在场复核生产 PG 写入。 |
| 最大故障窗口 | 从 cutover apply 到 `/ready` 200 或回滚完成 ≤ 30 分钟；超时立即按 34.4 回滚。 |
| 回滚触发条件 | 任一：9100 5xx 突增 / RAG 检索异常 / 知识训练写入失败 / 数据不一致 / `/ready` 持续 503 超 5 分钟。 |
| 割接失败恢复（apply 中途报错） | apply 终止 → 不执行 `compose up`，9100 继续跑旧 SQLite（在线未断）；保留 apply 日志排查；回滚 = 不切换。 |
| migration 成功但 cutover 失败 | alembic 已 upgrade 但 apply 中途失败 → PG 已有部分数据，SQLite 仍完整；回滚 = compose 恢复 `XG_DOUYIN_AI_CS_DB_PATH`，PG 部分数据保留供排查，**不删** volume。 |
| PG 新数据回滚丢失 | 切 PG 后产生的 RAG 新写入（反馈 / 训练会话）回滚到 SQLite 时会丢失（SQLite 无这些写）；回滚决策须权衡丢失量，低峰 + 短观察窗降低丢失。 |
| 旧 SQLite 归档 | cutover 成功 + 观察 48h 通过后，`cp data/xg_douyin_ai_cs.db data/archive/xg_douyin_ai_cs.db.cutover-<date>`，保留 ≥ 30 天；归档校验（`sqlite3 .tables`）通过前不删原文件。 |
| 观察期 | 切换后 ≥ 48h 监控：9100 `/ready`、5xx、RAG 延迟、连接池、慢查询；观察期内不部署其他 9100 变更。 |
| 回滚窗口 | 切换后 48h 内可快速回滚（SQLite 文件未动）；48h 后回滚须重新评估 PG 新数据丢失量。 |

通过标准：切换后 `/ready` 200 + 工作台 RAG 正常 + 48h 无异常 + 无 5xx 突增 + 三方签字归档。

### 34.11 向量后端策略（生产人工确认，不自动切换）

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / B3。9100 向量检索后端由 `RAG_VECTOR_BACKEND` 决定（sqlite / milvus）。metadata 真源恒为 PG（chunks.embedding_json），向量后端只是检索副本/机制。本轮不自动切换，生产选择需人工确认。

**两选项机制**（见 `apps/xg_douyin_ai_cs/services/vector_store.py` + `rag/repository.py`）：

| 维度 | sqlite（默认） | milvus |
|------|---------------|--------|
| 检索 | `repository.search` 读 PG `embedding_json` + Python `cosine_similarity` 全量计算（O(active chunks)） | `MilvusVectorStore.search` ANN 索引 |
| 训练写入 | 直插 PG `embedding_json`（SQLite 模式 `upsert_chunks` 为 NotImplementedError，不走） | 双写：PG `embedding_json` + `store.upsert_chunks(milvus_chunks)`（repository.py:514-520, 698-705） |
| 额外服务 | 无 | 需独立 Milvus 实例（生产 `docker-compose.yml` 当前未含 Milvus service，须外部提供或新增 service） |
| 数据真源 | PG metadata（chunks.embedding_json） | PG metadata 是真源，Milvus 是检索副本 |

**约束矩阵**：

| 维度 | sqlite | milvus |
|------|--------|--------|
| volume 路径 | PG volume（`./docker-data/postgres`） | PG volume + Milvus data volume（独立，路径由 Milvus 实例决定） |
| 恢复 | PG 恢复即恢复（无独立副本） | PG 恢复后须从 metadata 重建 Milvus collection（全量 upsert） |
| 多实例 | 多 9100 共享 PG 连接池，无副本竞争 | 多 9100 共享同一 Milvus collection（连接别名 `xg_douyin_ai_cs_milvus`） |
| 不一致重建 | 无副本，不存在不一致 | 从 PG metadata 全量重建：遍历 active chunks → `ensure_collection(create_if_missing=True)` → `upsert_chunks` |
| 回滚影响（PG cutover） | 向量后端随 PG cutover（无独立切换） | Milvus 数据不随 PG cutover 变化；metadata `chunk_id`/`document_id` 平移后 id 一致，Milvus 无需重建 |
| smoke 验证 | `repository.search` 命中 + RAG 检索返回正常 | `milvus_collection_check.py` + `milvus_canary_e2e.py` 通过 + `health_check` connected=True + collection_exists=True |

**生产决策（人工确认，本轮不定）**：

1. 生产 active chunks 行数量级 —— 决定 sqlite 全表扫描 + Python 余弦是否可接受（数百级可接受，数千级须压测，超万级不建议 sqlite）。
2. 是否已有可用 Milvus 实例 —— 无则须新增 `docker-compose` service 或外部托管（成本 + 运维）。
3. sqlite 模式 —— 生产前必须压测 `repository.search` 在生产数据量下的延迟与内存（全量 embedding_json 拉内存，~15-30 KB/chunk）。
4. milvus 模式 —— 必须验证训练双写链路（PG + Milvus upsert）+ `milvus_collection_check.py` / `milvus_canary_e2e.py` 在 staging 通过。

**默认与边界**：
- 未确认前生产保持 `RAG_VECTOR_BACKEND=sqlite`（与 dev 一致），在低规模下运行。
- 本轮不修改 `config.py` 默认值（`rag_vector_backend` 默认 sqlite），不自动切换。
- `/ready` 不校验向量后端 —— 向量后端是检索性能优化，非接收业务流量的硬前提；向量后端异常不应导致 9100 标记 not_ready，由 `MilvusVectorStore.health_check` 单独诊断（见 `services/vector_store.py`）。
- 切换向量后端（sqlite ↔ milvus）须独立审批窗口，不与 PG cutover 窗口同时切换，避免叠加风险。
