# Leads/Tasks Shadow QPS Benchmark Guide

任务：`P3-D8-DB-9000-LEADS-TASKS-QPS-BASELINE-AND-SHADOW-OVERHEAD-1`

本文记录 9000 leads/tasks runtime PostgreSQL read-only shadow 的本地/dev synthetic 压测方法。该压测只用于建立 shadow off baseline 与 shadow on overhead 的早期量化基线，不是生产压测，不是 QPS600 达标证明。

## 1. 当前定位

本轮只覆盖 P3-D4/P3-D5/P3-D6/P3-D7 已接入的 read-only shadow 范围：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

压测脚本为：

```text
scripts/benchmark_leads_tasks_shadow_overhead_dev.py
```

压测模型是 service-level synthetic rows：

1. 自动创建 synthetic SQLite fixture。
2. 使用 P3-D2 migration helper 将 synthetic rows 写入 dev PostgreSQL。
3. SQLite synthetic rows 仍作为响应源。
4. PostgreSQL 只做 read-only shadow 对照。
5. benchmark 结束后清理 synthetic PG 数据。

该模型不等同于真实 Nginx + Uvicorn + 网络链路，也不等同于宝塔 production 数据路径。

## 2. 运行方式

启动本地 dev PostgreSQL：

```powershell
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
```

设置 dev PG URL。只允许 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL`，不允许隐式使用 `DATABASE_URL`：

```powershell
$env:BENCHMARK_DATABASE_URL="postgresql+asyncpg://auto_wechat:<PASSWORD>@127.0.0.1:5432/auto_wechat"
```

执行 benchmark：

```powershell
python scripts/benchmark_leads_tasks_shadow_overhead_dev.py --requests 200 --concurrency 20 --warmup 20 --strict
```

可选写出 JSON：

```powershell
python scripts/benchmark_leads_tasks_shadow_overhead_dev.py --requests 200 --concurrency 20 --warmup 20 --output-json reports/leads_tasks_shadow_benchmark.json
```

按 profile 只压测部分读路径：

```powershell
python scripts/benchmark_leads_tasks_shadow_overhead_dev.py --profile leads --requests 200 --concurrency 20 --warmup 20
```

收尾：

```powershell
Remove-Item Env:\BENCHMARK_DATABASE_URL
docker compose -f docker-compose.dev.yml stop postgres
```

## 3. 输出指标

每轮输出：

1. `total_requests`
2. `successful_requests`
3. `failed_requests`
4. `error_rate`
5. `throughput_rps`
6. `p50_ms`
7. `p95_ms`
8. `p99_ms`
9. `max_ms`
10. `min_ms`
11. `avg_ms`
12. `per_endpoint`

shadow on 额外输出：

1. `total_shadow_reads`
2. `total_shadow_pass`
3. `total_shadow_warn`
4. `total_shadow_failed`
5. `total_shadow_timeout`
6. `total_shadow_error`
7. `by_operation`

overhead 输出：

1. `p50_delta_ms`
2. `p95_delta_ms`
3. `p99_delta_ms`
4. `avg_delta_ms`
5. `throughput_delta_percent`
6. `error_rate_delta`

## 4. Shadow Off / Shadow On 对照

shadow off baseline：

```text
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
```

shadow on overhead：

```text
LEADS_TASKS_PG_PILOT_ENABLED=true
LEADS_TASKS_PG_READ_SHADOW_ENABLED=true
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_DATABASE_URL=<dev PG URL>
```

脚本通过显式 settings 执行，不修改默认 `.env`，不切换默认 `DATABASE_URL`，不启用 PG write。

## 5. Strict 判定

`--strict` 下以下情况会失败：

1. baseline 或 shadow on `error_rate > 0`。
2. `total_shadow_error > 0`。
3. `total_shadow_timeout > 0`。
4. `total_shadow_failed > 0`。
5. expected read-only operation 覆盖不完整。

非 strict 下会输出 warning，但不会误报 `BENCHMARK_PASS`；有 warning 时输出 `BENCHMARK_WARN`。

## 6. QPS600 后续准入

当前 benchmark 只给本地/dev synthetic 基线。后续 QPS600 仍需要：

1. 真实接口压测，而不是只看 service-level synthetic rows。
2. worker 数、每 worker connection pool、总连接数、PG `max_connections` 规划。
3. `statement_timeout` 与慢查询日志。
4. 高频字段索引和执行计划验证。
5. webhook 幂等键、task polling 分页和锁策略。
6. asyncpg / SQLAlchemy async session 全链路替换方案。
7. staging 灰度与生产压测审批。

## 7. 风险

1. TestClient / ASGITransport / service-level 模型不等同于真实 Nginx + Uvicorn + 网络链路。
2. synthetic 数据不等同于真实业务数据分布。
3. 当前 shadow 查询仍是过渡期 read-only 对照，不是最终 async repository。
4. 本轮 benchmark 不证明生产 QPS600。
5. 本轮 benchmark 不证明可以切换默认数据库。

## 8. 禁止事项

1. 不在宝塔 production 运行本脚本。
2. 不读取 production SQLite。
3. 不使用 production PostgreSQL。
4. 不使用隐式 `DATABASE_URL`。
5. 不开启 PG write。
6. 不执行 production apply。
7. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
