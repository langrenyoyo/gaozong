# leads/tasks core async PG pilot 方案

任务：`P3-D3-DB-9000-LEADS-TASKS-API-CONTRAST-AND-ASYNC-PG-PILOT-1`

本文记录 9000 四张 leads/tasks core 表的 SQLite vs PostgreSQL contrast 框架与 async PostgreSQL pilot 方案。本轮只做 synthetic/dev 级别对照框架、dev smoke 和方案文档，不切换默认 `DATABASE_URL`，不默认开启 PG pilot，不连接宝塔生产，不读取生产 SQLite，不执行 production apply。

关键词口径：`douyin_leads`、`douyin_webhook_events`、`sales_staff`、`wechat_tasks`、SQLite vs PostgreSQL contrast、asyncpg、SQLAlchemy async、connection pool、`LEADS_TASKS_PG_PILOT_ENABLED=false`、`DATABASE_URL`、不切换默认数据库。

## 1. 当前阶段结论

1. P3-D1 已完成四表 PostgreSQL schema：`douyin_leads`、`douyin_webhook_events`、`sales_staff`、`wechat_tasks`。
2. P3-D2 已完成四表 SQLite -> PostgreSQL 数据迁移 dry-run 脚本与 dev apply smoke。
3. P3-D3 已新增 SQLite vs PostgreSQL contrast 框架：
   - `scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py`
   - `tests/test_contrast_leads_tasks_core_sqlite_vs_postgres.py`
4. P3-D3 已新增 dev synthetic contrast smoke：
   - `scripts/smoke_contrast_leads_tasks_core_dev.py`
5. 当前仍不能切换默认 `DATABASE_URL` 到 PostgreSQL。
6. 当前仍不能默认开启 PG pilot。
7. 当前 contrast 只证明四表 synthetic/dev 对照框架可用，不代表宝塔真实数据对照完成，也不代表 QPS600 达标。

## 2. 四表 API 审计摘要

### 2.1 sales_staff

| 项 | 结论 |
|---|---|
| 主要路由 / service | `app/routers/staff.py`；`app/services/staff_service.py`；分配链路还会经 `assign_service`、`notification_service`、`lead_wechat_notify_eligibility_service` 读取 |
| 当前 DB session 来源 | `Depends(get_db)`，底层来自 `app/database.py` 的同步 `SessionLocal` |
| 当前是否同步 SQLAlchemy | 是，`staff_service` 使用同步 `db.query()` / `db.add()` / `db.commit()` |
| async route 中同步 DB 阻塞风险 | 中。当前 staff 路由是同步函数，但未来若挂到 async route 或被 async 工作流直接调用，会阻塞事件循环 |
| 高频查询字段 | `merchant_id`、`status`、`wechat_nickname`、`wechat_id`、`id` |
| 推荐第一批 shadow read 顺序 | 第一批。读路径轻、商户隔离明确、列表语义稳定，适合先做 read-only PG shadow |

### 2.2 wechat_tasks

| 项 | 结论 |
|---|---|
| 主要路由 / service | `app/routers/wechat_tasks.py`；`app/services/wechat_task_service.py` |
| 当前 DB session 来源 | `Depends(get_db)`；Local Agent pending / result 路径也通过同步 Session |
| 当前是否同步 SQLAlchemy | 是，pending 查询、历史列表、详情、结果回写均使用同步 SQLAlchemy |
| async route 中同步 DB 阻塞风险 | 高。`GET /wechat-tasks/pending` 与 `POST /wechat-tasks/{task_id}/result` 是 Local Agent 高频路径 |
| 高频查询字段 | `task_type`、`status`、`created_at`、`lead_id`、`staff_id`、`merchant_id`、`mode`、`failure_stage` |
| 推荐第一批 shadow read 顺序 | 第二批先做 history read-only；pending polling 和 result write 最后灰度 |

### 2.3 douyin_leads

| 项 | 结论 |
|---|---|
| 主要路由 / service | `app/routers/leads.py`；`app/services/lead_management_service.py`；`lead_service.py`；`assign_service.py`；webhook 写入经 `app/integrations/douyin_webhook.py` |
| 当前 DB session 来源 | `Depends(get_db)`；webhook service 接收同步 `Session` |
| 当前是否同步 SQLAlchemy | 是，列表、详情、统计、分配、webhook upsert 都是同步 SQLAlchemy |
| async route 中同步 DB 阻塞风险 | 高。线索列表 / 详情是运营台核心读路径，webhook upsert 是写入主链路 |
| 高频查询字段 | `merchant_id`、`status`、`created_at`、`updated_at`、`assigned_staff_id`、`account_open_id`、`conversation_short_id`、`source_id` |
| 推荐第一批 shadow read 顺序 | 第三批。先做 list/detail read-only shadow，再考虑分配和 webhook 写入 |

### 2.4 douyin_webhook_events

| 项 | 结论 |
|---|---|
| 主要路由 / service | `app/routers/webhook_events.py`；`app/services/webhook_event_service.py`；写入经 `app/integrations/douyin_webhook.py` |
| 当前 DB session 来源 | `Depends(get_db)`；webhook 处理使用同步 `Session` |
| 当前是否同步 SQLAlchemy | 是，事件列表、详情、event_key 幂等查询、事件落库均为同步 SQLAlchemy |
| async route 中同步 DB 阻塞风险 | 高。webhook 写入和事件列表都可能高频，且原始事件量增长快 |
| 高频查询字段 | `event_key`、`event`、`lead_action`、`is_duplicate`、`created_at`、`open_id`、`conversation_short_id`、`lead_id`、`account_open_id` |
| 推荐第一批 shadow read 顺序 | 第四批。先做 read-only 事件列表 / 详情对照，最后才考虑 webhook write |

## 3. 推荐 pilot 顺序

先只读，后写入；先低风险、轻查询，后高频写链路：

1. `sales_staff` read-only shadow。
2. `wechat_tasks` history read-only shadow。
3. `douyin_leads` list/detail read-only shadow。
4. `douyin_webhook_events` read-only shadow。
5. 最后才考虑 webhook write / task result write。

不建议第一批直接改 `POST /integrations/douyin/webhook`、`GET /wechat-tasks/pending` 或 `POST /wechat-tasks/{task_id}/result`，这些路径牵涉幂等、事务、锁、外部动作和状态回写。

## 4. 开关设计

默认全部 false，不进入运行路径：

```text
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
```

| 开关 | 默认值 | 语义 |
|---|---|---|
| `LEADS_TASKS_PG_PILOT_ENABLED` | `false` | 总开关；关闭时不初始化四表 PG pilot runtime |
| `LEADS_TASKS_PG_READ_SHADOW_ENABLED` | `false` | 开启 read-only shadow read；SQLite 仍是返回源 |
| `LEADS_TASKS_PG_WRITE_ENABLED` | `false` | 后续写入开关；本阶段禁止启用 |
| `LEADS_TASKS_PG_STRICT_CONTRAST` | `false` | strict contrast 时 warning 也视为失败；默认只记录 |

## 5. 双读策略

1. SQLite 仍是用户响应返回源。
2. PostgreSQL 只做 shadow read。
3. shadow read 结果只用于日志、metric 或人工 contrast，不影响用户响应。
4. mismatch 只记录日志，不影响用户。
5. shadow read 严禁触发写入。
6. shadow read 严禁默认启用。
7. PostgreSQL URL 必须脱敏输出，不打印真实密码。
8. synthetic/dev contrast 可以使用 `scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py`；宝塔真实数据 contrast 必须另走人工审批和执行记录。

## 6. 写入策略

1. 本阶段不启用 PG 写入。
2. 后续写入必须先完成幂等、事务、失败回滚和回放策略。
3. webhook write 必须最后灰度，因为它同时影响 `douyin_webhook_events` 与 `douyin_leads`。
4. `wechat_tasks` result write 必须最后灰度，因为它会影响任务状态、通知联动、回复检测和后续 detect task。
5. 写入灰度必须先完成 dev synthetic、staging dry-run、API contrast 和人工审批。
6. 不允许通过隐式 `DATABASE_URL` 开启写入；必须显式开关和明确目标环境。

## 7. QPS600 准备项

1. PostgreSQL runtime 使用 `asyncpg` 或 SQLAlchemy `AsyncSession`，禁止在 async route 中直接使用同步 SQLAlchemy session。
2. 连接池需明确 `pool_size`、`max_overflow`、`pool_timeout`、`pool_recycle`。
3. 总连接数计算：

```text
单 worker 最大连接 = pool_size + max_overflow
理论最大连接 = worker 数 * 单 worker 最大连接
PostgreSQL max_connections >= 理论最大连接 + 运维/迁移/监控预留连接
```

4. 设置 `statement_timeout`，避免慢查询拖垮 worker。
5. 开启慢查询日志并按接口维度记录耗时。
6. 高频字段索引继续围绕 `merchant_id`、`status`、`created_at`、`updated_at`、`event_key`、`account_open_id`、`conversation_short_id`、`task_type`、`lead_id`、`staff_id` 验证。
7. webhook 必须有幂等键，当前 schema 起点是 `douyin_webhook_events.event_key`。
8. `wechat_tasks` pending polling 后续需要分页和锁策略，PostgreSQL 方向可评估 `FOR UPDATE SKIP LOCKED`。
9. 写入链路需要清晰事务边界，不让外部 HTTP、LLM、Milvus 或微信自动化动作处于长事务内。
10. QPS600 必须通过 API 压测、连接池观测、PostgreSQL 慢查询、锁等待和错误率共同证明。

## 8. 风险

1. 当前业务接口仍走 SQLite。
2. contrast 目前是 synthetic/dev 级别，未经过宝塔真实数据 contrast。
3. P3-D2 dev apply smoke 不代表 production 迁移完成。
4. PG runtime 抽象尚未接入四表业务接口。
5. 现有大量 route / service 仍使用同步 SQLAlchemy session。
6. `wechat_tasks` 与 webhook 写入链路牵涉状态流转，不能直接 shadow write。
7. QPS600 未经过压测证明。
8. 不允许将四表 contrast 框架解读为默认 `DATABASE_URL` 可切换。

## 9. 后续拆分

1. P3-D4：runtime shadow read scaffolding，默认关闭。
2. P3-D5：sales_staff read-only shadow 对照。
3. P3-D6：wechat_tasks history read-only shadow 对照。
4. P3-D7：douyin_leads list/detail read-only shadow 对照。
5. P3-D8：douyin_webhook_events read-only shadow 对照。
6. 后续写入灰度单独审批，不在 P3-D3 内启用。
