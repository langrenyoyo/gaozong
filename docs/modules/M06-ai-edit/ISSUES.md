# M06 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## TECH_DEBT / LOW

### ISSUE-M06-001 无 status CHECK 约束（TECH_DEBT / APPLICATION_VALIDATION_PENDING）

- **位置**：models.py:1510（status）/ :1520（stage）/ :1545（delivery_status）/ :1550（delete_status）
- **事实**：4 个状态字段均为自由 String，无 DB CHECK 约束；迁移 0045 也未加 CHECK
- **影响**：DB constraint ABSENT ≠ 业务缺陷——需 E2E 证明 API 可写非法状态才升级
- **建议**：E2E Gate E（Terminal Processing）验证后定性

### ISSUE-M06-002 process_las_job 无持久化恢复（拆分）

- **位置**：ai_edit_las_service.py:119-194（BackgroundTask + wait_for_terminal 阻塞轮询）
- **Automatic durable worker recovery**: ABSENT（BackgroundTask 非持久化，进程崩溃轮询中断）
- **Process restart recovery**: 需 Gate I 查是否有启动恢复/补偿脚本
- **Manual/ops recovery**: 需 Gate I 查是否有 archive 补偿脚本
- **不写"完全无恢复"**——此前项目可能存在 LAS 归档补偿脚本

## LOW

### ISSUE-M06-003 Compute 幂等 → CODE_VERIFIED_EXPOSED（不标 E2E impacted）

- **Owner verification**: M07（COMPUTE-IDEMPOTENCY-001）
- **M06 侧状态**: CODE_VERIFIED_EXPOSED（静态暴露——ai_edit_las_service.py:737-746 调 record_usage，无 LAS E2E 证明 double charge）
- **不标 E2E impacted**——LAS 链路需外部凭证才能 E2E
- **archived 幂等 gate** 仅正常路径有效，异常重入绕过

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
| MEDIUM | 0 |
| TECH_DEBT / LOW | 3（无 status CHECK APPLICATION_VALIDATION_PENDING / process_las_job 无持久化恢复三层拆分 / 下载 token 可重放） |
| CROSS_MODULE | 1（CROSS_MODULE_COMPUTE_IDEMPOTENCY_GAP，owner=M07） |
| ARCHITECTURE_OBSERVATION | 1（LAS 任务对素材无强引用） |
