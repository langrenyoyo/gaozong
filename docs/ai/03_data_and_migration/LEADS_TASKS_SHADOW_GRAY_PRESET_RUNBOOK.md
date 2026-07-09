# leads/tasks shadow gray preset and runbook

任务：`P3-D13-DB-9000-LEADS-TASKS-SHADOW-GRAY-PRESET-AND-RUNBOOK-1`

本文基于 P3-D12 本地/dev synthetic sample/concurrency tuning 结果，沉淀 9000 leads/tasks PostgreSQL read-only shadow 的灰度参数预设、启停 Runbook 和上线前准入检查。本轮只做文档和配置示例，不连接宝塔生产，不读取 production SQLite，不切换默认 `DATABASE_URL`，不启用 PG write。

关键词口径：`LEADS_TASKS_PG_PILOT_ENABLED`；`LEADS_TASKS_PG_READ_SHADOW_ENABLED`；`LEADS_TASKS_PG_WRITE_ENABLED=false`；`LEADS_TASKS_PG_SHADOW_SAMPLE_RATE`；`LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY`；`DATABASE_URL`；`QPS600`；不切换默认数据库。

## 1. 当前状态

P0 四表 read-only shadow 已完成运行态覆盖：

1. `sales_staff list`：`GET /staff`。
2. `wechat_tasks history`：`GET /wechat-tasks`。
3. `douyin_leads list/detail`：`GET /leads`、`GET /leads/{lead_id}`。
4. `douyin_webhook_events list`：`GET /webhook-events`。

当前运行边界：

1. 默认仍关闭：`LEADS_TASKS_PG_PILOT_ENABLED=false`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=false`。
2. 当前未接入 PG write，`LEADS_TASKS_PG_WRITE_ENABLED=false` 仍不得被开启。
3. SQLite 仍是用户响应源，PostgreSQL 只做 shadow read 对照。
4. 当前未切换默认 `DATABASE_URL`。
5. 当前未接 webhook write、task pending 拉取、task result 回写、`notify_sales` / `detect_reply` 写链路。
6. P3-D12 结果来自本地/dev synthetic benchmark，不是 production QPS600 证明。

## 2. P3-D12 推荐候选

P3-D12 quick-tuning 推荐灰度候选：

| 指标 | 值 |
|---|---:|
| workers | 2 |
| pool_size | 5 |
| max_overflow | 5 |
| shadow_max_concurrency | 10 |
| shadow_sample_rate | 0.1 |
| estimated_pg_connections | 20 |
| throughput_rps | 570.102 |
| p95_ms | 52.178 |
| p99_ms | 59.518 |
| error_rate | 0 |

该结果只说明本地/dev synthetic 下的 read-only shadow 降载候选，不说明宝塔 staging、production 或 QPS600 已达标。

## 3. 灰度参数预设

### 3.1 dev recommended

用途：本地/dev synthetic smoke、benchmark、开发者验证。

```env
LEADS_TASKS_PG_PILOT_ENABLED=true
LEADS_TASKS_PG_READ_SHADOW_ENABLED=true
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=postgresql+asyncpg://auto_wechat:<PASSWORD>@127.0.0.1:5432/auto_wechat
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_POOL_TIMEOUT=3
LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS=1500
LEADS_TASKS_PG_SHADOW_TIMEOUT_MS=800
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=10
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=0.1
```

说明：

1. dev 可以按 P3-D12 推荐值启动 read-only shadow。
2. `LEADS_TASKS_PG_DATABASE_URL` 必须使用 dev PostgreSQL，URL 记录时必须脱敏。
3. `LEADS_TASKS_PG_WRITE_ENABLED` 必须保持 `false`。

### 3.2 staging cautious

用途：宝塔 staging 灰度观察。该档需要人工审批和执行窗口，不能自动套用 dev 结论。

```env
LEADS_TASKS_PG_PILOT_ENABLED=true
LEADS_TASKS_PG_READ_SHADOW_ENABLED=true
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=postgresql+asyncpg://auto_wechat:<PASSWORD>@<POSTGRES_HOST>:5432/auto_wechat
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_POOL_TIMEOUT=3
LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS=1500
LEADS_TASKS_PG_SHADOW_TIMEOUT_MS=800
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=5
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=0.05
```

说明：

1. staging 初始采样建议低于 dev，先观察错误、timeout、mismatch 和 PostgreSQL 连接数。
2. 如果 30 分钟观察窗口内 `total_shadow_error=0`、`total_shadow_timeout=0` 且业务接口 p95 无明显恶化，可审批提升到 dev recommended 的 `shadow_sample_rate=0.1`、`shadow_max_concurrency=10`。
3. staging 不允许启用 PG write，不允许切换默认 `DATABASE_URL`。

### 3.3 production current / not approved

当前 production 状态：`not approved / not executed`。

production 当前必须保持关闭：

```env
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=
```

如后续另有 production shadow read 审批，建议从只读低采样候选开始，且必须重新形成独立审批和执行记录：

```env
LEADS_TASKS_PG_PILOT_ENABLED=true
LEADS_TASKS_PG_READ_SHADOW_ENABLED=true
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=postgresql+asyncpg://auto_wechat:<PASSWORD>@<POSTGRES_HOST>:5432/auto_wechat
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=3
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=0.01
```

该候选不是批准项。未完成 production 审批前，不得在 production 设置为 true。

## 4. 开启前置条件

开启任何非 dev 环境 shadow 前必须确认：

1. 当前代码 commit hash 已记录，工作区无非本轮待提交变更。
2. PostgreSQL schema 至少包含 P3-D1 四表 revision：`0003_create_leads_tasks_core_tables`。
3. P3-D2 四表迁移 dry-run / dev apply smoke 已通过。
4. P3-D7 runtime shadow synthetic smoke 已通过。
5. P3-D12 tuning 结果仅作为候选，不被当作 production QPS600 证明。
6. `LEADS_TASKS_PG_DATABASE_URL` 指向目标环境 PostgreSQL，记录时脱敏。
7. 默认 `DATABASE_URL` 仍指向现有 SQLite 或保持当前默认，不切到 PostgreSQL。
8. `LEADS_TASKS_PG_WRITE_ENABLED=false`。
9. 未开启 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
10. 监控人、回滚负责人、观察窗口和熔断阈值已确认。

## 5. 开启 Runbook

以下命令是模板，必须替换占位符，不得写入真实密码。

### 5.1 记录基线

```powershell
cd <CODE_DIR>
git rev-parse HEAD
git status --short
git diff --check
```

记录当前 SQLite 主路径响应、metrics 快照和 PostgreSQL 连接数：

```powershell
curl <BASE_URL>/admin/debug/leads-tasks-pg-shadow/metrics
```

### 5.2 注入 shadow read 环境变量

staging 示例：

```env
LEADS_TASKS_PG_PILOT_ENABLED=true
LEADS_TASKS_PG_READ_SHADOW_ENABLED=true
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=<POSTGRES_URL>
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=5
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=0.05
```

要求：

1. 只注入 staging / 审批目标容器。
2. 不修改默认 `DATABASE_URL`。
3. 不在文档、工单、提交记录中写真实 URI、token 或 password。
4. 不把 `LEADS_TASKS_PG_WRITE_ENABLED` 设为 true。

### 5.3 启动后 smoke

启动后只调用已覆盖的只读接口：

```text
GET /staff
GET /wechat-tasks
GET /leads
GET /leads/{lead_id}
GET /webhook-events
GET /admin/debug/leads-tasks-pg-shadow/metrics
```

预期：

1. 用户响应仍来自 SQLite。
2. `total_shadow_reads` 增长。
3. `total_shadow_error=0`。
4. `total_shadow_timeout=0`。
5. `LEADS_TASKS_PG_WRITE_ENABLED=false`。

## 6. 关闭和回滚 Runbook

默认回滚是关闭 read-only shadow，而不是清理 PostgreSQL 数据或修改业务库。

关闭配置：

```env
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_DATABASE_URL=
```

回滚步骤：

1. 将目标环境 shadow 开关全部恢复为 false / 空 URL。
2. 重启或重新加载目标 9000 容器配置。
3. 调用 `GET /staff`、`GET /leads`、`GET /webhook-events` 验证 SQLite 主响应正常。
4. 查询 metrics，确认后续请求不再增加 shadow read。
5. 记录回滚时间、原因、执行人和验证结果。

禁止：

1. 不 drop PostgreSQL 表。
2. 不清空 volume。
3. 不切换 `DATABASE_URL`。
4. 不开启 PG write。
5. 不修改 SQLite 查询结果。

## 7. 监控指标

应用侧需要观察：

1. `total_shadow_reads`
2. `total_shadow_pass`
3. `total_shadow_warn`
4. `total_shadow_failed`
5. `total_shadow_timeout`
6. `total_shadow_error`
7. `total_shadow_sampled_out`
8. `total_shadow_concurrency_limited`
9. `current_shadow_inflight`
10. `max_shadow_inflight_seen`
11. `total_mismatch_count`
12. `by_operation`
13. `engine_manager_snapshot.engine_count`
14. `engine_manager_snapshot.cache_hit_count / cache_miss_count`

接口侧需要观察：

1. p50 / p95 / p99。
2. HTTP 4xx / 5xx。
3. `/staff`、`/wechat-tasks`、`/leads`、`/webhook-events` 分接口耗时。

PostgreSQL 侧需要观察：

1. 当前连接数和空闲连接数。
2. 慢查询日志。
3. `statement_timeout` 次数。
4. 锁等待。
5. CPU / IO / memory。

安全侧需要观察：

1. 日志中不得出现完整 PostgreSQL URL。
2. 日志中不得出现手机号、微信号、客户名、raw body、token、cookie 或 password。
3. metrics endpoint 仅限 admin / super_admin 访问。

## 8. 熔断条件

满足任一条件应立即关闭 shadow read 并记录：

1. HTTP 5xx 增加。
2. `total_shadow_error` 持续增长。
3. `total_shadow_timeout` 持续增长。
4. `total_mismatch_count` 持续增长且无法解释。
5. p95 / p99 相比开启前明显恶化。
6. PostgreSQL 连接数接近预算上限。
7. 慢查询或锁等待影响业务。
8. 日志出现敏感信息泄露迹象。
9. 出现任何写 PostgreSQL 迹象。

熔断后只允许回到 SQLite 主响应 + shadow off 状态，不允许现场临时开启 PG write。

## 9. 上线前准入检查

进入 staging shadow 前：

| 检查项 | 结论 |
|---|---|
| P3-D1 schema 已存在 | 待填写 |
| P3-D2 migration smoke 已通过 | 待填写 |
| P3-D7 runtime shadow smoke 已通过 | 待填写 |
| P3-D12 本地/dev tuning 已记录 | 待填写 |
| staging PostgreSQL URL 已脱敏记录 | 待填写 |
| 默认 `DATABASE_URL` 未切换 | 待填写 |
| `LEADS_TASKS_PG_WRITE_ENABLED=false` | 待填写 |
| 观察窗口和回滚负责人已确认 | 待填写 |

进入 production shadow 前：

| 检查项 | 结论 |
|---|---|
| production shadow 审批已批准 | 待填写 |
| staging shadow 记录通过 | 待填写 |
| production PostgreSQL schema 与数据状态已确认 | 待填写 |
| production 连接池总连接数预算已确认 | 待填写 |
| production 监控和熔断阈值已确认 | 待填写 |
| 未审批 PG write | 待填写 |
| 未审批切换 `DATABASE_URL` | 待填写 |

当前 production 结论：`not approved / not executed`。

## 10. 人工审批区

| 字段 | 填写 |
|---|---|
| 环境 | dev / staging / production |
| 申请人 |  |
| 审批人 |  |
| 执行人 |  |
| 执行窗口 |  |
| commit hash |  |
| PostgreSQL URL 脱敏 |  |
| 是否只读 shadow | 是 / 否 |
| 是否确认不启用 PG write | 是 / 否 |
| 是否确认不切换 `DATABASE_URL` | 是 / 否 |
| 是否确认可按 Runbook 熔断 | 是 / 否 |
| 审批结论 | 批准 / 拒绝 / 暂缓 |
| 备注 |  |

## 11. 禁止事项

1. 不连接宝塔生产。
2. 不读取 production SQLite。
3. 不执行 production apply。
4. 不切换默认 `DATABASE_URL`。
5. 不默认开启 PG pilot。
6. 不启用 PG write。
7. 不修改业务接口代码。
8. 不修改 SQLite 查询结果。
9. 不接 webhook write。
10. 不接 task pending 拉取。
11. 不接 task result 回写。
12. 不接 `notify_sales` / `detect_reply` 写链路。
13. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
14. 不改 9100 / Milvus / RAG。

## 12. 后续建议

1. P3-D14：宝塔 staging read-only shadow 人工审批模板与执行记录。
2. P3-D15：宝塔 staging shadow 真实观察记录。
3. P3-D16：若 staging 通过，再生成 production shadow 审批模板。
4. P3-E：继续推进下一组 P0 表 PostgreSQL schema / migration，不能把 read-only shadow 预设视为默认切库完成。
