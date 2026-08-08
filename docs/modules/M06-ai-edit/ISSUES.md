# M06 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## MEDIUM

### ISSUE-M06-001 无 status CHECK 约束

- **位置**：models.py:1510（status）/ :1520（stage）/ :1545（delivery_status）/ :1550（delete_status）
- **事实**：4 个状态字段均为自由 String，无 DB CHECK 约束；迁移 0045 也未加 CHECK
- **影响**：可写入任意字符串状态值，无数据库级枚举保护
- **建议**：加 CHECK 约束或代码层枚举校验（与 M02 ISSUE-M02-004 同类）

### ISSUE-M06-002 process_las_job 单点轮询无恢复

- **位置**：ai_edit_las_service.py:119-194（BackgroundTask + wait_for_terminal 阻塞轮询）
- **事实**：无任务队列/重试调度，进程崩溃则轮询中断且无自动恢复
- **影响**：需人工查 las_task_id 重跑
- **建议**：考虑引入持久化任务调度（与 M01 outbox 模式类比）

## LOW

### ISSUE-M06-003 算力上报无幂等键（与 ISSUE-M04-002 同源）

- **位置**：ai_edit_las_service.py:723-748 _report_las_compute_usage → apps/compute/services.py:537-611 record_usage
- **事实**：record_usage 无 idempotency/jti/dedup；正常路径靠 archived 幂等 gate 避免重复；异常重入路径存在理论重复风险
- **影响**：异常重入可能重复扣算力
- **建议**：加 job 级幂等键（与 ISSUE-M04-002 同源治理，留 M07）

### ISSUE-M06-004 下载 token 可重放（自认 tradeoff）

- **位置**：ai_edit_las_service.py:666-668 注释
- **事实**：TTL 120s 内 token 可被历史/日志/Referer 重放，未引入 Redis jti 一次性消费
- **影响**：低风险（短 TTL + 需获取 secret 才能伪造）
- **建议**：如需强化安全可引入一次性 jti

## ARCHITECTURE_OBSERVATION

### ARCH-M06-001 LAS 任务对素材无强引用

- **位置**：create_las_job 用 video_urls 预签名 URL，不写 AiEditJobMaterial
- **事实**：LAS 任务不关联 AiEditMaterial 行，soft_delete_material 活动引用检查不影响 LAS 任务
- **影响**：删素材后 LAS 任务仍可运行（其用预签名 URL 已脱离素材表）；但预签名 URL 可能过期
- **处理**：登记为架构观察，非遗漏（LAS 链路设计为 URL 驱动非素材驱动）

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 0 |
| MEDIUM | 2（无 status CHECK / process_las_job 单点轮询无恢复） |
| LOW | 2（算力无幂等 / 下载 token 可重放） |
| ARCHITECTURE_OBSERVATION | 1（LAS 任务对素材无强引用） |
