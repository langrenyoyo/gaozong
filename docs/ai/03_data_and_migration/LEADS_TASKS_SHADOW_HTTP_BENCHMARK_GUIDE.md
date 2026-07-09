# Leads/Tasks Shadow HTTP Benchmark Guide

任务：`P3-D10-DB-9000-LEADS-TASKS-REAL-HTTP-BENCHMARK-SCAFFOLD-1`

本文记录 9000 leads/tasks PostgreSQL read-only shadow 的本地/dev 真实 HTTP benchmark 脚手架。该脚手架通过 Uvicorn/HTTP 路径对比 shadow off 与 shadow on，但仍只使用 synthetic 数据，不是生产 QPS600 达标证明。

## 1. 当前定位

P3-D10 覆盖当前已接入 read-only shadow 的 5 个接口：

1. `GET /staff` -> `sales_staff.list`
2. `GET /wechat-tasks` -> `wechat_tasks.history`
3. `GET /leads` -> `douyin_leads.list`
4. `GET /leads/{lead_id}` -> `douyin_leads.detail`
5. `GET /webhook-events` -> `douyin_webhook_events.list`

同时读取：

```text
GET /admin/debug/leads-tasks-pg-shadow/metrics
```

脚本为：

```text
scripts/benchmark_leads_tasks_shadow_http_dev.py
```

该脚本比 P3-D8/P3-D9 的 service-level benchmark 更接近真实链路，因为请求会经过 Uvicorn、HTTP 解析、FastAPI 路由、NewCar mock auth、同步 SQLite 查询、PG shadow read 与 metrics endpoint。但它仍不包含 Nginx、宝塔反代、真实网络、生产数据分布、多 worker 和生产 PostgreSQL 资源竞争。

## 2. 运行方式

启动本地 dev PostgreSQL：

```powershell
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
```

设置 dev PG URL。只允许 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL`，不允许隐式使用 `DATABASE_URL`：

```powershell
$env:BENCHMARK_DATABASE_URL="postgresql+asyncpg://auto_wechat:<PASSWORD>@127.0.0.1:5432/auto_wechat"
```

推荐使用自动启动本地 Uvicorn：

```powershell
python scripts/benchmark_leads_tasks_shadow_http_dev.py --start-server --requests 200 --concurrency 20 --warmup 20 --strict
```

也可以连接已启动的本地 dev 9000 服务：

```powershell
python scripts/benchmark_leads_tasks_shadow_http_dev.py --base-url http://127.0.0.1:9000 --requests 200 --concurrency 20 --warmup 20
```

注意：`--base-url` 模式无法由脚本切换目标服务的环境变量，因此必须人工确认该服务已使用 synthetic/dev SQLite 与显式 PG shadow 配置。需要严格对比 shadow off/on 时，优先使用 `--start-server`。

可选写出 JSON：

```powershell
python scripts/benchmark_leads_tasks_shadow_http_dev.py --start-server --requests 200 --concurrency 20 --warmup 20 --output-json reports/leads_tasks_shadow_http_benchmark.json
```

收尾：

```powershell
Remove-Item Env:\BENCHMARK_DATABASE_URL
docker compose -f docker-compose.dev.yml stop postgres
```

## 3. Synthetic 数据

脚本自动创建临时 SQLite fixture，不读取生产 SQLite，不修改 `.env`。`--start-server` 模式会用临时环境变量把 Uvicorn 子进程的 `DATABASE_URL` 指向该临时 SQLite。

脚本也会把同一批 synthetic rows 写入 dev PostgreSQL，用于 read-only shadow 对照。写入仅用于 benchmark setup，结束后按 synthetic ID 范围清理 PG 行，不 drop 表、不 truncate 表、不清 volume。

mock auth 使用本地 NewCar mock：

```text
NEWCAR_AUTH_ENABLED=false
NEWCAR_AUTH_MOCK_ENABLED=true
```

synthetic merchant 使用 `dev-merchant`，与本地 mock auth 默认商户一致。

## 4. 指标解释

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

1. `shadow_metrics`
2. `engine_manager_snapshot`

overhead 输出：

1. `p50_delta_ms`
2. `p95_delta_ms`
3. `p99_delta_ms`
4. `avg_delta_ms`
5. `throughput_delta_percent`
6. `error_rate_delta`

## 5. 与 P3-D8/P3-D9 的差异

P3-D8/P3-D9 是 service-level synthetic benchmark，主要验证 shadow service、engine manager 与连接池生命周期。P3-D10 是 HTTP 层 benchmark，会覆盖真实 FastAPI 路由和本地 Uvicorn HTTP 开销。

P3-D9 已证明每请求 create/dispose engine 的开销明显下降，但 P3-D9 不包含真实 HTTP 栈。P3-D10 补齐这个观测角度，但仍不包含生产反代和多 worker。

## 6. Strict 判定

`--strict` 下以下情况会失败：

1. baseline 或 shadow on `error_rate > 0`。
2. `total_shadow_error > 0`。
3. `total_shadow_timeout > 0`。
4. `total_shadow_failed > 0`。
5. expected read-only operation 覆盖不完整。
6. engine manager snapshot 显示 engine 数随请求线性增长。

非 strict 下会输出 warning，不应被解读为 production ready。

## 7. QPS600 后续准入

QPS600 仍需要后续验证：

1. Uvicorn / Gunicorn 多 worker 模式 benchmark。
2. Nginx / 宝塔反代 / 容器网络链路 benchmark。
3. worker 数、每 worker pool size、max overflow、PostgreSQL 总连接数核算。
4. PostgreSQL 慢查询日志与 statement timeout。
5. 高频 SQL 的 `EXPLAIN` / `EXPLAIN ANALYZE`。
6. staging 灰度与回滚演练。
7. 写入链路的事务、幂等和失败回滚。

## 8. 禁止事项

1. 不在宝塔 production 运行本脚本。
2. 不读取 production SQLite。
3. 不使用 production PostgreSQL。
4. 不使用隐式 `DATABASE_URL` 作为 benchmark PG URL。
5. 不开启 PG write。
6. 不执行 production apply。
7. 不把本地 HTTP benchmark 当作 QPS600 达标证明。
8. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

## 9. P3-D11 worker/pool sizing 补充

P3-D11 在本文 P3-D10 HTTP benchmark 脚手架上新增 worker/pool sizing benchmark：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_WORKER_POOL_SIZING_GUIDE.md
```

新增能力：

1. 支持 `--workers`、`--pool-sizes`、`--max-overflows` 矩阵。
2. 支持 `--shadow-max-concurrency` 与 `--shadow-sample-rates` 实验。
3. 输出 `estimated_pg_connections = workers * (pool_size + max_overflow)`。
4. 输出每组 HTTP 指标、shadow metrics 和 engine manager snapshot。
5. 仍只允许本地/dev synthetic，不代表 production QPS600。

边界保持不变：不切换默认 `DATABASE_URL`，不默认开启 PG pilot，不启用 PG write，不连接宝塔 production。

## 10. P3-D12 sampling / concurrency tuning 补充

P3-D12 在 P3-D11 worker/pool sizing 基础上继续调优 `shadow_sample_rate` 与 `shadow_max_concurrency`：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py --quick-tuning
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_SAMPLING_TUNING_REPORT.md
```

本地/dev synthetic quick-tuning 推荐灰度候选：

```text
workers=2
pool_size=5
max_overflow=5
shadow_max_concurrency=10
shadow_sample_rate=0.1
estimated_pg_connections=20
```

本轮最佳 synthetic 结果为 `throughput_rps=570.102`、`p95=52.178ms`、`p99=59.518ms`、`error_rate=0`，距离 QPS600 仍差约 `29.898 rps`。该结果不包含宝塔反代、真实 production 数据和 production PostgreSQL，因此仍不能作为 production QPS600 证明。
