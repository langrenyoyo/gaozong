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

## 10. P3-D4 runtime shadow read scaffolding 落地记录

任务：`P3-D4-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-READ-SCAFFOLDING-DEFAULT-OFF-1`

P3-D4 已新增默认关闭的运行态 PostgreSQL shadow read 脚手架：

```text
app/services/leads_tasks_pg_shadow.py
app/services/leads_tasks_shadow_compare.py
tests/test_leads_tasks_pg_shadow_runtime.py
```

新增配置项默认全部关闭或保守：

```text
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_POOL_TIMEOUT=3
LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS=1500
LEADS_TASKS_PG_SHADOW_TIMEOUT_MS=800
```

本轮只接入两个低风险只读点：

1. `GET /staff`：`sales_staff` list read-only shadow。
2. `GET /wechat-tasks`：`wechat_tasks` history read-only shadow。

运行语义：

1. SQLite 仍是唯一用户响应源。
2. PostgreSQL 只做 shadow read，不参与返回值生成。
3. shadow read 只有在 `LEADS_TASKS_PG_PILOT_ENABLED=true`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=true` 且 `LEADS_TASKS_PG_DATABASE_URL` 为 `postgresql+asyncpg://` 时才允许执行。
4. 默认配置下不初始化 PG engine、不连接 PostgreSQL。
5. shadow read 异常或超时只记录 warning，不影响主请求。
6. URL 日志只允许脱敏展示。
7. `LEADS_TASKS_PG_WRITE_ENABLED` 本阶段不被任何业务写路径消费。

本轮明确未接入：

1. `douyin_leads` runtime hook。
2. `douyin_webhook_events` runtime hook。
3. `GET /wechat-tasks/pending`。
4. `POST /wechat-tasks/{task_id}/result`。
5. webhook write。
6. 任何 PostgreSQL write。

后续建议：P3-D5 可继续扩展到 `douyin_leads` list/detail shadow read，或先进入智能体 / 账号绑定 PostgreSQL schema batch；仍不得切换默认 `DATABASE_URL`。

## 11. P3-D5 douyin_leads runtime shadow read 与观测

任务：`P3-D5-DB-9000-LEADS-RUNTIME-SHADOW-READ-AND-OBSERVABILITY-1`

P3-D5 在 P3-D4 默认关闭脚手架基础上，新增 `douyin_leads` list/detail read-only shadow，并补充结构化日志与轻量内存指标：

```text
GET /leads             -> douyin_leads list shadow read
GET /leads/{lead_id}   -> douyin_leads detail shadow read
```

当前已接入 shadow 的范围：

1. `sales_staff` list。
2. `wechat_tasks` history。
3. `douyin_leads` list。
4. `douyin_leads` detail。

当前未接入：

1. `douyin_webhook_events` runtime hook。
2. webhook write。
3. `GET /wechat-tasks/pending` pending task。
4. `POST /wechat-tasks/{task_id}/result` task result write。
5. `notify_sales` / `detect_reply` write。
6. 任何 PostgreSQL write。

运行语义保持不变：

1. SQLite 仍是唯一接口响应源。
2. PG shadow 默认关闭，只有 `LEADS_TASKS_PG_PILOT_ENABLED=true`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=true` 且 `LEADS_TASKS_PG_DATABASE_URL=postgresql+asyncpg://...` 时才允许只读查询。
3. `douyin_leads` shadow 查询必须带 `merchant_id`；缺失时跳过，不做无隔离查询。
4. mismatch、异常或 timeout 只进入结构化日志和内存指标，不影响用户响应。
5. 日志只记录 count/key/status/duration/warnings_count 等摘要，不记录手机号、微信号、客户名等 PII。
6. 当前仍不能切换默认 `DATABASE_URL`，也不能默认开启 PG pilot。

下一步建议：P3-D6 可接入 `douyin_webhook_events` read-only shadow，并评估是否新增受限的 admin/debug metrics endpoint；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。

## 12. P3-D6 douyin_webhook_events shadow read 与 metrics endpoint

任务：`P3-D6-DB-9000-WEBHOOK-EVENTS-SHADOW-READ-AND-METRICS-ENDPOINT-1`

P3-D6 在 P3-D4/P3-D5 默认关闭的 leads/tasks PG shadow read 基础上，补齐 `douyin_webhook_events` 只读 shadow，并新增受限 metrics debug endpoint：

```text
GET /webhook-events -> douyin_webhook_events list shadow read
GET /admin/debug/leads-tasks-pg-shadow/metrics -> shadow metrics snapshot
```

webhook events read path 审计摘要：

1. `GET /webhook-events` 位于 `app/routers/webhook_events.py`，通过 `Depends(get_db)` 使用同步 SQLAlchemy session。
2. 列表查询由 `app/services/webhook_event_service.py` 的 `list_webhook_events()` 承载，返回源仍是 SQLite。
3. 当前列表过滤覆盖 `event`、`lead_action`、`is_duplicate`、`start_time`、`end_time`、`keyword`、`open_id`、`conversation_short_id`、`lead_id`、分页。
4. `lead_action` 和部分 `open_id` 语义依赖 SQLite 读取后的 Python post-filter；PG shadow 本轮只做结构化字段近似对照，不比较 raw body。
5. webhook 入库、幂等、lead capture/upsert、自动回复调度和私信发送上下文本轮均未接入 shadow。

当前已接入 read-only shadow 范围：

1. `GET /staff`：`sales_staff` list。
2. `GET /wechat-tasks`：`wechat_tasks` history。
3. `GET /leads`：`douyin_leads` list。
4. `GET /leads/{lead_id}`：`douyin_leads` detail。
5. `GET /webhook-events`：`douyin_webhook_events` list。

metrics endpoint 边界：

1. endpoint 仅 `super_admin` 或具备 admin 权限上下文可访问，普通 merchant 和未登录请求不可访问。
2. endpoint 只返回 `get_shadow_metrics_snapshot()` 只读快照，不初始化 PG engine，不触发 shadow read。
3. 返回内容不包含 raw body、完整手机号、微信号、客户名、nickname 或 PostgreSQL URL 密码。
4. `reset_shadow_metrics_for_tests()` 仍只在测试中使用，运行态不暴露 reset endpoint。

当前仍未接入范围：

1. webhook write。
2. `GET /wechat-tasks/pending` pending task。
3. `POST /wechat-tasks/{task_id}/result` task result write。
4. `notify_sales` / `detect_reply` write。
5. 任何 PostgreSQL write。

运行边界保持不变：SQLite 仍是唯一响应源；PG shadow 默认关闭；当前仍不能切换默认 `DATABASE_URL`，不能默认开启 PG pilot，不能启用 `LEADS_TASKS_PG_WRITE_ENABLED` 写入链路。

下一步建议：P3-D7 做本地 synthetic runtime shadow smoke + 全量 shadow 覆盖回归；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。

## 13. P3-D7 runtime shadow synthetic smoke 与回归

任务：`P3-D7-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-SYNTHETIC-SMOKE-AND-REGRESSION-1`

P3-D7 已为 P3-D4/P3-D5/P3-D6 接入的 leads/tasks runtime PostgreSQL read-only shadow 增加 dev/synthetic smoke 与回归测试：

```text
scripts/smoke_leads_tasks_runtime_shadow_dev.py
tests/test_leads_tasks_runtime_shadow_smoke.py
tests/test_leads_tasks_pg_shadow_runtime.py
```

当前 P0 四表 read-only shadow 覆盖：

1. `sales_staff list`
2. `wechat_tasks history`
3. `douyin_leads list`
4. `douyin_leads detail`
5. `douyin_webhook_events list`

runtime smoke 语义：

1. 默认关闭时不初始化 PG engine，不连接 PostgreSQL，metrics 不增长。
2. dev/synthetic 开启时必须显式设置 `LEADS_TASKS_PG_PILOT_ENABLED=true`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=true`、`LEADS_TASKS_PG_DATABASE_URL=postgresql+asyncpg://...`，并保持 `LEADS_TASKS_PG_WRITE_ENABLED=false`。
3. SQLite synthetic fixture 仍是接口响应语义来源，PG 只做 shadow read 对照。
4. `total_shadow_reads` 和 `by_operation` 必须覆盖上述五个 operation。
5. mismatch、PG error、timeout 只进入 metrics / warning，不改变 SQLite 主响应。
6. metrics endpoint 只读取内存 snapshot，不触发额外 PG 初始化，不暴露 PII。
7. 本阶段仍不接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` write。

边界确认：

1. 当前仍不能切换默认 `DATABASE_URL`。
2. 当前仍不能默认开启 PG pilot。
3. 当前仍未启用 PG write。
4. 当前未连接宝塔生产，未读取生产 SQLite，未执行 production apply。
5. dev/synthetic shadow smoke 通过不代表可以 production 切库，也不代表 QPS600 已达标。

下一步建议：

1. `P3-D8`：本地 QPS baseline + shadow overhead 压测。
2. 或进入 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 14. P3-D8 shadow QPS baseline 与 overhead 压测

任务：`P3-D8-DB-9000-LEADS-TASKS-QPS-BASELINE-AND-SHADOW-OVERHEAD-1`

P3-D8 在 P3-D4/P3-D5/P3-D6/P3-D7 已完成的 read-only shadow 覆盖上，新增本地/dev synthetic benchmark：

```text
scripts/benchmark_leads_tasks_shadow_overhead_dev.py
tests/test_leads_tasks_shadow_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_QPS_BENCHMARK_GUIDE.md
```

当前 benchmark 覆盖五个 read-only operation：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

压测模型：

1. 仅限本地/dev synthetic 数据。
2. 自动创建 synthetic SQLite fixture。
3. 通过 P3-D2 migration helper 把 synthetic rows 写入 dev PostgreSQL。
4. 运行态仍以 SQLite synthetic rows 作为响应源。
5. PostgreSQL 只做 read-only shadow read。
6. 对比 shadow off baseline 与 shadow on overhead。
7. 输出 p50 / p95 / p99 / max / avg / error_rate / throughput_rps / per_endpoint / overhead delta / shadow metrics。

边界保持不变：

1. 当前 benchmark 不代表 production QPS600 达标。
2. 当前仍不能切换默认 `DATABASE_URL`。
3. 当前仍不能默认开启 PG pilot。
4. 当前仍未启用 PG write。
5. 当前不连接宝塔生产，不读取生产 SQLite，不执行 production apply。
6. 当前不接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。

下一步建议：

1. `P3-D9`：async session / connection pool runtime design hardening。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 15. P3-D9 async engine / pool 生命周期加固

任务：`P3-D9-DB-9000-LEADS-TASKS-ASYNC-ENGINE-POOL-HARDENING-1`

P3-D8 暴露的性能问题：

1. P3-D8 shadow off baseline：`throughput_rps=15089.898`、`p50=0.881ms`、`p95=1.357ms`、`p99=1.634ms`。
2. P3-D8 shadow on：`throughput_rps=39.301`、`p50=536.994ms`、`p95=734.568ms`、`p99=909.916ms`。
3. 根因是为规避跨 event loop 复用 async engine，P3-D7 将 engine 创建 / dispose 收窄到每次 shadow query，导致开销随请求线性放大。

P3-D9 已新增：

```text
app/services/leads_tasks_pg_engine.py
tests/test_leads_tasks_pg_engine_manager.py
```

engine manager 语义：

1. 默认关闭、URL 为空时不创建 engine。
2. 只允许 `postgresql+asyncpg://`，拒绝 SQLite URL。
3. 按 event loop 缓存 async engine，同一 loop 复用，不同 loop 不复用。
4. URL、`pool_size`、`max_overflow`、`pool_timeout` 变化时重建 engine。
5. 提供 `dispose_shadow_engines()`、`get_engine_manager_snapshot()` 和测试重置 helper。
6. snapshot 只输出脱敏 URL。

shadow service 调整：

1. `app/services/leads_tasks_pg_shadow.py` 不再每次 query 创建 / dispose engine。
2. 同步 router 中的 shadow read 通过后台 event loop 执行 async 查询，避免每次 `asyncio.run()` 创建独立 event loop。
3. SQLite 仍是唯一响应源。
4. PG shadow 仍只读，异常、timeout、mismatch 不影响主响应。
5. `LEADS_TASKS_PG_WRITE_ENABLED` 仍未被业务写路径消费。

P3-D9 本地/dev synthetic benchmark：

| 指标 | P3-D8 shadow on | P3-D9 shadow on | 改善 |
|---|---:|---:|---:|
| throughput_rps | 39.301 | 441.390 | +402.089 rps，约 11.23 倍 |
| p50 | 536.994ms | 33.621ms | 降低 503.373ms，约 93.74% |
| p95 | 734.568ms | 155.103ms | 降低 579.465ms，约 78.89% |
| p99 | 909.916ms | 170.014ms | 降低 739.902ms，约 81.32% |

D9 engine manager snapshot：

```text
engine_count=1
loop_count=1
created_count=1
disposed_count=0
cache_hit_count=183
cache_miss_count=1
```

边界确认：

1. P3-D9 仍不切换默认 `DATABASE_URL`。
2. P3-D9 仍不默认开启 PG pilot。
3. P3-D9 仍不启用 PG write。
4. P3-D9 未连接宝塔生产，未读取生产 SQLite，未执行 production apply。
5. P3-D9 benchmark 仍是 dev/synthetic，不代表 production QPS600 达标。

下一步建议：

1. `P3-D10`：真实 Uvicorn / HTTP benchmark 脚手架，继续默认关闭 PG pilot。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 16. P3-D10 HTTP benchmark scaffold

任务：`P3-D10-DB-9000-LEADS-TASKS-REAL-HTTP-BENCHMARK-SCAFFOLD-1`

P3-D10 已在默认关闭的 read-only shadow pilot 基础上新增真实 Uvicorn/HTTP benchmark 脚手架：

```text
scripts/benchmark_leads_tasks_shadow_http_dev.py
tests/test_leads_tasks_shadow_http_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_HTTP_BENCHMARK_GUIDE.md
```

设计结论：

1. 默认仍不切换 `DATABASE_URL`。
2. 默认仍不启用 `LEADS_TASKS_PG_PILOT_ENABLED`。
3. `--start-server` 模式使用临时 SQLite fixture 启动本地 Uvicorn，并分别启动 shadow off / shadow on 子进程。
4. `--base-url` 模式只允许本地 dev 服务，且无法由脚本切换服务环境，因此只作为人工已启动服务的辅助压测入口。
5. PostgreSQL 只做 read-only shadow；`LEADS_TASKS_PG_WRITE_ENABLED=false`。
6. metrics endpoint 增加 engine manager snapshot，只读、不触发 PG 初始化、不包含 PII 或数据库密码。

QPS600 影响：

1. P3-D10 比 P3-D8/P3-D9 service-level benchmark 更接近真实接口链路。
2. P3-D10 仍是本地/dev synthetic，不代表宝塔 staging 或 production QPS600 达标。
3. 下一步建议进入 `P3-D11`：Uvicorn multi-worker benchmark / connection pool sizing；或进入 `P3-E1`：智能体 / 抖音账号绑定 schema batch。
