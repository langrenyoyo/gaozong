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

## 9. P3-D9 engine / pool hardening 补充

任务：`P3-D9-DB-9000-LEADS-TASKS-ASYNC-ENGINE-POOL-HARDENING-1`

P3-D8 暴露的问题：

| 指标 | P3-D8 shadow off | P3-D8 shadow on | P3-D8 overhead |
|---|---:|---:|---:|
| throughput_rps | 15089.898 | 39.301 | -99.74% |
| p50 | 0.881ms | 536.994ms | +536.113ms |
| p95 | 1.357ms | 734.568ms | +733.211ms |
| p99 | 1.634ms | 909.916ms | +908.282ms |

原因：P3-D7 为避免 async engine 跨 `asyncio.run()` event loop 复用，把 engine 生命周期收窄到单次 shadow query。该方案安全，但每个请求 create/dispose engine，导致 shadow overhead 很大。

P3-D9 新增 event-loop-safe engine manager：

1. `app/services/leads_tasks_pg_engine.py` 按 event loop 缓存 async engine。
2. 同一 event loop 内复用 engine，不同 event loop 不复用 engine。
3. 默认关闭或 URL 为空时不创建 engine。
4. SQLite URL 和非 `postgresql+asyncpg://` URL 会被拒绝。
5. URL、`pool_size`、`max_overflow`、`pool_timeout` 变化时重建 engine，并 dispose 旧 engine。
6. benchmark 结束时显式调用 `dispose_shadow_engines()`。
7. URL 输出仍脱敏。

P3-D9 benchmark 额外输出 `engine_manager_snapshot`：

1. `engine_count`
2. `loop_count`
3. `created_count`
4. `disposed_count`
5. `cache_hit_count`
6. `cache_miss_count`
7. 脱敏后的 engine URL 与 pool 参数

`--strict` 额外校验：

1. `engine_count` 或 `created_count` 不得随 requests 线性增长。
2. requests > 1 时 `cache_hit_count` 不应为 0。

P3-D9 本地/dev synthetic benchmark 结果：

```text
命令：python scripts/benchmark_leads_tasks_shadow_overhead_dev.py --requests 200 --concurrency 20 --warmup 20 --strict
模型：service-level synthetic rows；SQLite response source；PostgreSQL read-only shadow
结果：BENCHMARK_PASS
```

| 指标 | P3-D9 shadow off | P3-D9 shadow on | P3-D9 overhead |
|---|---:|---:|---:|
| throughput_rps | 12613.203 | 441.390 | -96.501% |
| p50 | 0.971ms | 33.621ms | +32.650ms |
| p95 | 3.234ms | 155.103ms | +151.869ms |
| p99 | 3.683ms | 170.014ms | +166.331ms |

相对 P3-D8 shadow on 的改善：

| 指标 | 改善 |
|---|---:|
| p50 | 降低 503.373ms，约 93.74% |
| p95 | 降低 579.465ms，约 78.89% |
| p99 | 降低 739.902ms，约 81.32% |
| throughput | 提升 402.089 rps，约 11.23 倍 |

P3-D9 engine manager snapshot：

```text
engine_count=1
loop_count=1
created_count=1
disposed_count=0
cache_hit_count=183
cache_miss_count=1
pool_size=5
max_overflow=5
pool_timeout=3
```

说明：snapshot 是 dispose 前的 benchmark 观测值；脚本 finally 已输出 `shadow engine cleanup: done`。

边界：

1. P3-D9 benchmark 仍是 dev/synthetic，不代表 production QPS600 达标。
2. `shadow_on throughput_rps=441.390` 仍低于 QPS600 目标。
3. P3-D9 不切换默认 `DATABASE_URL`。
4. P3-D9 不默认开启 PG pilot。
5. P3-D9 不启用 PG write。

## 10. P3-D10 HTTP benchmark scaffold 补充

任务：`P3-D10-DB-9000-LEADS-TASKS-REAL-HTTP-BENCHMARK-SCAFFOLD-1`

P3-D10 在 P3-D8/P3-D9 service-level benchmark 基础上新增真实 Uvicorn/HTTP 层 benchmark 脚手架：

```text
scripts/benchmark_leads_tasks_shadow_http_dev.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_HTTP_BENCHMARK_GUIDE.md
```

新增脚手架能力：

1. 支持 `--start-server` 自动启动本地 Uvicorn，使用临时 SQLite fixture。
2. 支持 `--base-url http://127.0.0.1:9000` 连接已启动的本地 dev 服务；该模式无法由脚本切换目标服务环境，结果会标记 warning。
3. 只从 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL` 读取 dev PostgreSQL URL。
4. 拒绝 SQLite URL、拒绝隐式 `DATABASE_URL`、拒绝非本地 base-url。
5. 覆盖 `GET /staff`、`GET /wechat-tasks`、`GET /leads`、`GET /leads/{lead_id}`、`GET /webhook-events` 和 metrics endpoint。
6. 输出 HTTP 层 p50 / p95 / p99 / avg / max / error_rate / throughput / per-endpoint / overhead delta。
7. metrics endpoint 额外返回 `engine_manager_snapshot`，只读、不触发 PG 初始化、不包含密码。

边界：

1. P3-D10 仍只使用本地/dev synthetic 数据。
2. P3-D10 不代表 production QPS600 达标。
3. P3-D10 不切换默认 `DATABASE_URL`。
4. P3-D10 不默认开启 PG pilot。
5. P3-D10 不启用 PG write。
6. P3-D10 不连接宝塔生产，不读取生产 SQLite，不执行 production apply。

## 11. P3-D11 worker/pool sizing benchmark 补充

任务：`P3-D11-DB-9000-LEADS-TASKS-UVICORN-MULTI-WORKER-POOL-SIZING-1`

P3-D11 新增本地/dev worker/pool sizing benchmark：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
tests/test_leads_tasks_shadow_worker_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_WORKER_POOL_SIZING_GUIDE.md
```

相比 P3-D8/P3-D9 service-level benchmark 和 P3-D10 单进程 HTTP benchmark，P3-D11 增加：

1. Uvicorn worker 数矩阵。
2. 每 worker `pool_size` / `max_overflow` 矩阵。
3. `LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY` 非阻塞 shadow 并发限制。
4. `LEADS_TASKS_PG_SHADOW_SAMPLE_RATE` shadow 采样率。
5. `estimated_pg_connections` 估算，用于连接数预算。

新增 shadow 降载指标：

1. `total_shadow_sampled_out`
2. `total_shadow_concurrency_limited`
3. `current_shadow_inflight`
4. `max_shadow_inflight_seen`

边界：

1. P3-D11 仍是本地/dev synthetic，不代表 production QPS600 达标。
2. P3-D11 不切换默认 `DATABASE_URL`。
3. P3-D11 不默认开启 PG pilot。
4. P3-D11 不启用 PG write。
5. P3-D11 不连接宝塔 production，不读取 production SQLite，不执行 production apply。

## 12. P3-D12 sampling / concurrency tuning 补充

任务：`P3-D12-DB-9000-LEADS-TASKS-SHADOW-SAMPLING-CONCURRENCY-TUNING-1`

P3-D12 已扩展 worker benchmark，新增：

1. `--quick-tuning` 快速矩阵。
2. `shadow_sample_rate=1.0,0.5,0.2,0.1`。
3. `shadow_max_concurrency=1,3,5,10`。
4. `theoretical_shadow_attempts`。
5. `shadow_coverage_ratio`。
6. `tuning_summary.recommended_gray_config`。

本地/dev synthetic quick-tuning 结果：

| 指标 | 值 |
|---|---:|
| status | `SAMPLING_TUNING_PASS` |
| recommended workers | 2 |
| recommended pool_size | 5 |
| recommended max_overflow | 5 |
| recommended shadow_max_concurrency | 10 |
| recommended shadow_sample_rate | 0.1 |
| estimated_pg_connections | 20 |
| throughput_rps | 570.102 |
| p95_ms | 52.178 |
| p99_ms | 59.518 |
| QPS600 remaining_rps | 29.898 |

结论：P3-D12 只形成 read-only shadow 灰度候选参数；当前仍不能切换默认 `DATABASE_URL`，仍未启用 PG write，也仍不是 production QPS600 证明。
