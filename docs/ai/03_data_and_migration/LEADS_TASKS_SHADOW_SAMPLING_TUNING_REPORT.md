# Leads/Tasks Shadow Sampling Tuning Report

任务：`P3-D12-DB-9000-LEADS-TASKS-SHADOW-SAMPLING-CONCURRENCY-TUNING-1`

本文记录 leads/tasks PostgreSQL read-only shadow 的 sample rate 与 shadow max concurrency 本地/dev synthetic 调优结果。本轮不连接宝塔生产，不读取 production SQLite，不切换默认 `DATABASE_URL`，不启用 PG write。

## 1. P3-D11 baseline

P3-D11 最佳 dev synthetic 结果：

| 指标 | 值 |
|---|---:|
| workers | 2 |
| pool_size | 10 |
| max_overflow | 5 |
| shadow_max_concurrency | 5 |
| shadow_sample_rate | 1.0 |
| estimated_pg_connections | 30 |
| throughput_rps | 276.231 |
| p95_ms | 116.622 |
| p99_ms | 130.031 |
| QPS600 覆盖率 | 46.04% |
| QPS600 差距倍数 | 约 2.17x |

P3-D11 保守近似配置：

| 指标 | 值 |
|---|---:|
| workers | 2 |
| pool_size | 5 |
| max_overflow | 5 |
| shadow_max_concurrency | 5 |
| estimated_pg_connections | 20 |
| throughput_rps | 271.125 |
| p95_ms | 117.794 |

## 2. P3-D12 tuning 目标

P3-D12 只调优 read-only shadow 的降载策略：

1. 评估 `LEADS_TASKS_PG_SHADOW_SAMPLE_RATE` 降低后对 throughput、p95、p99、shadow coverage 的影响。
2. 评估 `LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY` 对 `concurrency_limited` 和延迟的影响。
3. 输出下一阶段灰度候选参数。
4. 明确当前仍不是 production QPS600 证明。

## 3. Benchmark 参数矩阵

执行命令：

```powershell
$env:BENCHMARK_DATABASE_URL="postgresql+asyncpg://auto_wechat:<PASSWORD>@127.0.0.1:5432/auto_wechat"
python scripts/benchmark_leads_tasks_shadow_workers_dev.py --quick-tuning --requests 100 --concurrency 20 --warmup 20 --strict
Remove-Item Env:\BENCHMARK_DATABASE_URL
```

`--quick-tuning` 展开为：

| 参数 | 矩阵 |
|---|---|
| workers | `2` |
| pool_size | `5,10` |
| max_overflow | `5` |
| shadow_sample_rate | `1.0,0.5,0.2,0.1` |
| shadow_max_concurrency | `1,3,5,10` |
| 总组合数 | 32 |

## 4. 本地/dev synthetic 结果

执行结果：

```text
SAMPLING_TUNING_PASS: leads/tasks shadow sampling concurrency tuning ready
synthetic_rows={'sales_staff': 2, 'douyin_leads': 2, 'douyin_webhook_events': 2, 'wechat_tasks': 2}
synthetic PG cleanup: done
```

shadow off baseline：

| 指标 | 值 |
|---|---:|
| workers | 2 |
| throughput_rps | 519.983 |
| p50_ms | 36.269 |
| p95_ms | 53.847 |
| p99_ms | 62.247 |
| error_rate | 0 |

代表性结果表：

| 类型 | workers | pool_size | max_overflow | shadow_max_concurrency | sample_rate | estimated_pg_connections | throughput_rps | p95_ms | p99_ms | error_rate | total_shadow_reads | total_shadow_pass | sampled_out | concurrency_limited | shadow_coverage_ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| best_throughput / recommended_gray_config | 2 | 5 | 5 | 10 | 0.1 | 20 | 570.102 | 52.178 | 59.518 | 0 | 55 | 5 | 50 | 0 | 0.654762 |
| top_candidate_2 | 2 | 10 | 5 | 1 | 0.2 | 30 | 527.123 | 54.612 | 64.290 | 0 | 56 | 6 | 45 | 5 | 0.666667 |
| top_candidate_3 | 2 | 10 | 5 | 3 | 0.1 | 30 | 326.752 | 55.477 | 174.392 | 0 | 50 | 3 | 47 | 0 | 0.595238 |
| full_shadow_reference | 2 | 10 | 5 | 10 | 1.0 | 30 | 351.609 | 89.177 | 93.426 | 0 | 46 | 46 | 0 | 0 | 0.547619 |

说明：

1. `shadow_coverage_ratio = total_shadow_reads / theoretical_shadow_attempts`，按脚本公式输出。
2. 当前多 worker metrics endpoint 返回命中 worker 的内存快照，不是跨 worker 聚合；因此 coverage ratio 只适合本地调优观察。
3. `sample_rate=0.1` 明显减少实际 PG read 数量，保留抽样对照能力，但覆盖率低于全量 shadow。

## 5. 推荐灰度参数

当前 recommended gray config：

```text
workers=2
pool_size=5
max_overflow=5
shadow_max_concurrency=10
shadow_sample_rate=0.1
estimated_pg_connections=20
```

推荐理由：

1. 本地/dev synthetic 中 throughput_rps = 570.102，是本轮 32 组中最高。
2. p95_ms = 52.178，p99_ms = 59.518，低于本轮 p95 150ms 的观察阈值。
3. estimated_pg_connections = 20，低于 P3-D11 最佳吞吐配置的 30。
4. shadow_error = 0，shadow_timeout = 0，HTTP error_rate = 0。

灰度约束：

1. 该配置只允许作为 P3-D13 环境变量 preset 候选，不得默认启用。
2. 该配置不启用 `LEADS_TASKS_PG_WRITE_ENABLED`。
3. SQLite 仍是主响应源，PG 仍只做 read-only shadow。
4. 若进入 staging，必须重新跑 staging synthetic / 真实数据审批后的 contrast，不得直接套用本地结果。

## 6. QPS600 差距说明

本轮最佳本地/dev synthetic：

```text
best_throughput_rps=570.102
target_qps=600
best_throughput_ratio=0.950170
remaining_rps=29.898
required_multiplier=1.052443
```

结论：

1. P3-D12 相比 P3-D11 的 276.231 rps 有明显改善。
2. 当前最佳结果仍低于 QPS600，约差 29.898 rps。
3. 当前结果不包含宝塔反代、生产网络、生产数据分布、PostgreSQL 慢查询、锁等待和跨 worker metrics 聚合。
4. 因此不能宣称 QPS600 已达标。

## 7. 风险说明

1. dev/synthetic 不等于 production。
2. sample_rate 降低会减少对照覆盖率，可能延迟发现 SQLite / PG 语义不一致。
3. 低 shadow_max_concurrency 会带来 `concurrency_limited`，降低实际 shadow 覆盖。
4. 多 worker metrics endpoint 当前不是跨进程聚合。
5. 本轮没有验证 PG write、webhook write、pending task polling、task result write、`notify_sales` / `detect_reply` 写链路。

## 8. 禁止事项

1. 不用于 production 压测结论。
2. 不在宝塔 production 运行本 benchmark。
3. 不读取 production SQLite。
4. 不使用 production PostgreSQL。
5. 不开启 PG write。
6. 不切换默认 `DATABASE_URL`。
7. 不默认开启 PG pilot。
8. 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

## 9. 后续建议

1. `P3-D13` 已新增 runtime shadow gray config preset 与启停 Runbook：`docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_GRAY_PRESET_RUNBOOK.md`。
2. P3-D13 只沉淀 dev / staging / production 三档 read-only shadow 参数，默认仍关闭，production 当前 `not approved / not executed`。
3. 后续可进入 `P3-D14` 宝塔 staging read-only shadow 审批模板与执行记录，或进入 `P3-E1` 智能体 / 抖音账号绑定 schema batch。
