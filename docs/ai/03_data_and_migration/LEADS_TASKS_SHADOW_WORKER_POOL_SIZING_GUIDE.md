# Leads/Tasks Shadow Worker Pool Sizing Guide

任务：`P3-D11-DB-9000-LEADS-TASKS-UVICORN-MULTI-WORKER-POOL-SIZING-1`

本文记录 9000 leads/tasks PostgreSQL read-only shadow 的本地/dev worker/pool sizing benchmark。该 benchmark 只使用 synthetic SQLite 与 synthetic dev PostgreSQL，用于探索 Uvicorn worker 数、PG 连接池和 shadow 限流参数，不是生产 QPS600 证明。

## 1. 当前定位

P3-D11 在 P3-D10 HTTP benchmark 基础上新增：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
tests/test_leads_tasks_shadow_worker_benchmark.py
```

运行态仍保持：

1. SQLite 是 HTTP 主响应源。
2. PostgreSQL 只做 read-only shadow。
3. `LEADS_TASKS_PG_WRITE_ENABLED=false`。
4. 默认不切换 `DATABASE_URL`。
5. 默认不启用 `LEADS_TASKS_PG_PILOT_ENABLED`。
6. benchmark 只允许本地/dev synthetic，不连接宝塔 production。

## 2. 参数说明

| 参数 | 含义 |
|---|---|
| `--workers` | Uvicorn worker 数矩阵，默认 `1,2,4` |
| `--pool-sizes` | 每个 worker 的 PG `pool_size` 矩阵，默认 `5,10,20` |
| `--max-overflows` | 每个 worker 的 PG `max_overflow` 矩阵，默认 `5,10` |
| `--shadow-max-concurrency` | 每个 worker 内 shadow read 最大并发矩阵，默认 `5,10,20` |
| `--shadow-sample-rates` | shadow read 采样率矩阵，默认 `1.0` |
| `--requests` | 每组请求数，默认 `500` |
| `--concurrency` | HTTP 并发数，默认 `50` |
| `--warmup` | 每组预热请求数，默认 `50` |

估算 PG 最大连接数：

```text
estimated_pg_connections = workers * (pool_size + max_overflow)
```

注意：Uvicorn 多 worker 是多进程模型，当前 metrics endpoint 返回的是响应该请求的单个 worker 内存快照，不是跨 worker 聚合。worker/pool sizing 需要结合 PostgreSQL 端连接数观测再确认。

## 3. Shadow 控制项

P3-D11 新增默认保守配置：

```text
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=10
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=1.0
```

语义：

1. PG pilot/read shadow 未开启时不生效。
2. `shadow_sample_rate` 只决定是否执行 shadow read，不影响 SQLite 主响应。
3. `sampled_out` 不视为 error，并记录 `total_shadow_sampled_out`。
4. `shadow_max_concurrency` 只限制 shadow read，不限制主请求。
5. 超过并发上限时不排队，直接跳过 shadow read，并记录 `concurrency_limited`。
6. sampled_out / concurrency_limited 都不会连接 PostgreSQL。

## 4. 如何运行

启动本地 dev PostgreSQL：

```powershell
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
```

设置 dev PG URL。只能使用 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL`，不得使用隐式 `DATABASE_URL`：

```powershell
$env:BENCHMARK_DATABASE_URL="postgresql+asyncpg://auto_wechat:<PASSWORD>@127.0.0.1:5432/auto_wechat"
```

推荐先执行小矩阵 smoke：

```powershell
python scripts/benchmark_leads_tasks_shadow_workers_dev.py --workers 1,2 --pool-sizes 5,10 --max-overflows 5 --shadow-max-concurrency 5,10 --shadow-sample-rates 1.0 --requests 100 --concurrency 20 --warmup 20 --strict
```

可选写出 JSON：

```powershell
python scripts/benchmark_leads_tasks_shadow_workers_dev.py --workers 1,2 --pool-sizes 5 --max-overflows 5 --shadow-max-concurrency 5 --shadow-sample-rates 1.0 --requests 100 --concurrency 20 --warmup 20 --output-json reports/leads_tasks_shadow_workers.json
```

收尾：

```powershell
Remove-Item Env:\BENCHMARK_DATABASE_URL
docker compose -f docker-compose.dev.yml stop postgres
```

## 5. 如何解读结果

每组输出：

1. `workers`
2. `pool_size`
3. `max_overflow`
4. `shadow_max_concurrency`
5. `shadow_sample_rate`
6. `estimated_pg_connections`
7. `throughput_rps`
8. `p50_ms`
9. `p95_ms`
10. `p99_ms`
11. `error_rate`
12. `shadow_error`
13. `shadow_timeout`
14. `sampled_out`
15. `concurrency_limited`
16. `engine_manager_snapshot`

优先关注：

1. `error_rate` 必须为 0。
2. `shadow_error` / `shadow_timeout` 必须为 0。
3. `p95_ms` / `p99_ms` 不应随 worker 或连接池放大而失控。
4. `estimated_pg_connections` 不得超过 PostgreSQL 可承受连接预算。
5. `sampled_out` 和 `concurrency_limited` 是主动降载信号，不是业务错误。

## 6. QPS600 初步估算

粗略估算方法：

```text
目标 worker 数 = ceil(600 / 单 worker 稳定 rps)
PG 最大连接预算 = worker 数 * (pool_size + max_overflow)
```

如果 shadow on 明显拖慢主接口，可以通过：

1. 降低 `shadow_sample_rate`。
2. 降低 `shadow_max_concurrency`。
3. 减小 `pool_size + max_overflow`。
4. 优先优化 p95 / p99 最差的 SQL。

该估算不能替代 staging / production 压测。QPS600 必须同时通过真实 HTTP 链路、Nginx/宝塔反代、PostgreSQL 连接数、慢查询、锁等待、错误率和回滚演练证明。

## 7. 风险

1. 本地/dev 不等于宝塔 production。
2. synthetic 数据不等于真实业务数据分布。
3. Uvicorn worker 不等于 Nginx + 公网链路。
4. SQLite 仍是主响应源，不代表 PostgreSQL 主库切换完成。
5. metrics endpoint 当前不是跨 worker 聚合。
6. 本轮没有验证 PG write、pending task、task result write、webhook write。

## 8. 禁止事项

1. 不在宝塔 production 运行本脚本。
2. 不读取 production SQLite。
3. 不使用 production PostgreSQL。
4. 不使用隐式 `DATABASE_URL`。
5. 不开启 PG write。
6. 不执行 production apply。
7. 不把本地 worker benchmark 当作 QPS600 达标证明。
8. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

## 9. P3-D12 sampling / concurrency tuning 补充

任务：`P3-D12-DB-9000-LEADS-TASKS-SHADOW-SAMPLING-CONCURRENCY-TUNING-1`

P3-D12 在本文 D11 worker/pool sizing benchmark 基础上增加快速调优模式：

```powershell
python scripts/benchmark_leads_tasks_shadow_workers_dev.py --quick-tuning --requests 100 --concurrency 20 --warmup 20 --strict
```

`--quick-tuning` 固定展开：

```text
workers=2
pool_size=5,10
max_overflow=5
shadow_sample_rate=1.0,0.5,0.2,0.1
shadow_max_concurrency=1,3,5,10
```

新增输出字段：

1. `theoretical_shadow_attempts`
2. `total_shadow_reads`
3. `total_shadow_pass`
4. `total_shadow_sampled_out`
5. `total_shadow_concurrency_limited`
6. `shadow_coverage_ratio`
7. `tuning_summary`

本地/dev synthetic 结果记录见：

```text
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_SAMPLING_TUNING_REPORT.md
```

当前 recommended gray config：

```text
workers=2
pool_size=5
max_overflow=5
shadow_max_concurrency=10
shadow_sample_rate=0.1
estimated_pg_connections=20
```

该配置只作为后续灰度候选，不得默认启用；当前仍不切换默认 `DATABASE_URL`，不启用 PG write，也不能作为 production QPS600 证明。
