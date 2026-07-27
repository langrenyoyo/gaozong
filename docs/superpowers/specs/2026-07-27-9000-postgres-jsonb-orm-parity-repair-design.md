# 9000 PostgreSQL JSONB / ORM 一致性首批返修设计

## 1. 元数据

- Task-ID：`P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1`
- Design-Revision：`D1`
- Risk-Level：`L3 / HIGH`
- Implementation-Base：`f3944a1c7368f3ae2ce529a718cd905e345d736c`
- 审批状态：已批准
- 执行边界：本规格只定义首批高优先级返修；业务实现与独立测试必须在其他窗口执行。

## 2. 背景与当前事实

9000 PostgreSQL 迁移当前共有 31 个 JSONB 列。主线已完成 4 个字段的一致性处理，剩余 27 个 ORM `Text` 与 PostgreSQL JSONB 不一致字段：

- 高优先级运行链路 10 列：webhook 2 列、发送流水 2 列、决策日志 6 列。
- 其他活跃运行链路 11 列：本规格不修改，进入第二批独立返修。
- 冻结或取消模块 6 列：只登记风险，不修改。

现有 `AiAutoReplyRun.gate_results_json` 已通过 `_GateResultsJSON` 保持以下合同：

- PostgreSQL 底层使用 JSONB。
- SQLite 底层使用 TEXT。
- ORM 对外保持 `str | None`。
- PostgreSQL 写入前把 JSON 字符串解析为原生 JSON 值，读回后重新序列化为字符串。
- `None` 写为 SQL NULL。
- 非法 JSON 不得静默改写或双重编码。

旧审计建议的 `JSON(...).with_variant(JSONB(...))` 会改变现有字符串 JSON 合同，不适用于本任务。

除字段映射错误外，当前调用链还有两个必须同时闭合的问题：

1. webhook 原子占位对两个字段执行手工 JSONB CAST，存在 JSON 字符串被再次编码为 JSONB 字符串标量的风险。
2. 多个服务直接对真实 PostgreSQL JSONB 列执行 `LIKE`，会触发 PostgreSQL 运算符类型错误。

## 3. 目标

首批返修必须同时完成：

1. 修复高优先级 10 列的 ORM / PostgreSQL 类型一致性。
2. 保持现有业务层 `str | None` 与 `json.dumps` / `json.loads` 合同。
3. 消除 webhook 原子占位的双重编码风险，同时保留原子幂等语义。
4. 使现有 JSON 文本筛选在 PostgreSQL 和 SQLite 下继续工作。
5. 使用真实本地 PostgreSQL 验证 ORM 写入、读取、筛选、并发占位和清理。
6. 保持发送安全、权限、事务、幂等、API 和 SQLite 现有行为不变。

## 4. 非目标与禁止事项

本任务禁止：

- 修改任何 `migrations/**`。
- 修改第二批 11 个活跃字段。
- 修改冻结或取消模块 6 个字段。
- 修改发送门禁、权限校验、幂等状态机或 API 合同。
- 修改 Docker、Compose、环境模板、生产配置、前端、9100、Milvus 或微信 Local Agent。
- 在 PostgreSQL 下调用 `create_all`。
- 连接 staging、production 或其他非本地专用数据库。
- 调用真实 LLM、9100、抖音或微信接口，或发送真实消息。
- 新增依赖、批量抽象或顺便重构无关 JSON 字段。

## 5. 共享类型设计

将 `_GateResultsJSON` 原位泛化并重命名为内部共享类型 `_JSONStringJSONB`。

### 5.1 类型合同

- `impl = Text`
- `cache_ok = True`
- PostgreSQL：`JSONB(none_as_null=True)`
- SQLite：`Text()`
- ORM 对外：`str | None`

### 5.2 写入合同

- `None` 返回 `None`，由数据库写为 SQL NULL。
- PostgreSQL 下对非空值执行 `json.loads`，将合法对象、数组或标量交给 JSONB 驱动。
- 非法 JSON 在绑定阶段抛 `JSONDecodeError`，不得降级为 `{}`、`[]`、字符串标量或 JSON `null`。
- SQLite 下保持现有字符串直存行为，不扩大本任务的兼容性变化。

### 5.3 读取合同

- PostgreSQL JSONB 值使用 `json.dumps(value, ensure_ascii=False)` 转回字符串。
- SQLite 原样返回。
- PostgreSQL 不承诺保留原字符串的空格和对象键顺序；调用方只能依赖解析后的 JSON 语义。

## 6. 首批字段范围

以下 10 个待修字段改用 `_JSONStringJSONB`：

### 6.1 webhook

- `DouyinWebhookEvent.raw_body`
- `DouyinWebhookEvent.parsed_content_json`

### 6.2 发送流水

- `DouyinPrivateMessageSend.request_body_json`
- `DouyinPrivateMessageSend.response_body_json`

### 6.3 决策日志

- `AiReplyDecisionLog.risk_flags_json`
- `AiReplyDecisionLog.tags_json`
- `AiReplyDecisionLog.rag_sources_json`
- `AiReplyDecisionLog.source_chunks_json`
- `AiReplyDecisionLog.allowed_category_keys_json`
- `AiReplyDecisionLog.raw_response_json`

现有 `AiAutoReplyRun.gate_results_json` 同时改用重命名后的共享类型，行为不得变化。

`ReturnVisitRun.gate_results_json` 的 PostgreSQL 迁移类型是 TEXT，不属于本任务。

## 7. webhook 原子占位设计

`build_webhook_claim_statement()` 必须继续保留：

- PostgreSQL `INSERT ... ON CONFLICT DO NOTHING RETURNING`。
- SQLite 对应的原子占位语句。
- 不支持方言显式失败。
- 胜出、重复、事务和副作用边界不变。

删除 `raw_body` 与 `parsed_content_json` 的手工 JSONB CAST。Core INSERT 直接使用表列类型，由 `_JSONStringJSONB` 完成参数绑定。

真实 PostgreSQL 必须证明：

- `jsonb_typeof(raw_body) = 'object'`。
- `parsed_content_json` 非空时 `jsonb_typeof(parsed_content_json) = 'object'`。
- ORM 读回值仍为 JSON 字符串。
- 重复 webhook 不产生第二条有效业务事件。

## 8. JSON 文本筛选设计

不得直接对 PostgreSQL JSONB 列执行 `LIKE`。以下现有查询改为显式：

```python
cast(json_column, Text).like(pattern)
```

覆盖范围：

- `webhook_event_service.py`：关键字、会话和 open_id 筛选。
- `douyin_merchant_isolation.py`：客户 open_id 归属兜底。
- `douyin_workbench_conversation_service.py`：工作台会话兼容查询。
- `ai_reply_decision_log_query_service.py`：风险标记筛选。

显式转换必须同时兼容 PostgreSQL 和 SQLite。不得在本任务中改用 JSONPath、包含运算符或新增索引。

## 9. 调用链与兼容性

### 9.1 webhook

```text
payload dict
→ 现有 json.dumps
→ claim_webhook_event
→ _JSONStringJSONB 绑定处理
→ PostgreSQL JSONB 原生对象
→ ORM 读取为 JSON 字符串
→ 现有 json.loads 消费
```

事件幂等键、事务提交点、胜出者判定、商户归属和重复事件处理不得改变。

### 9.2 发送流水

发送服务继续先生成脱敏后的 JSON 字符串，再写入 request/response 两列。只修 ORM 类型，不改变上游调用时机、真实发送保护、失败回写或自动回复状态机。

### 9.3 决策日志

决策服务继续由现有 `_json_dumps` 生成字符串。六个字段读回后仍为字符串，API 列表、详情、脱敏及筛选结构不变。

### 9.4 失败处理

- PostgreSQL 非法 JSON 在绑定阶段失败，由现有事务边界回滚。
- 不新增捕获后继续写入的降级路径。
- 不记录原始 payload、完整上游响应、令牌、密码或完整数据库连接串。
- 历史 PostgreSQL JSONB 数据不需要清洗或重写。

## 10. PostgreSQL 测试环境

复用现有本地专用数据库 `auto_wechat_outbox_test` 和既有 `SMOKE_DATABASE_URL` 安全校验，不新建重复测试基础设施。

必须满足：

- 驱动为 `postgresql+psycopg`。
- 主机仅允许 `127.0.0.1` 或 `localhost`。
- 端口为 5432。
- 数据库名精确为 `auto_wechat_outbox_test`。
- 禁止 query 和 fragment。
- Alembic 当前版本为 0016。
- PostgreSQL 初始化只能使用 Alembic，禁止 `create_all`。

每个用例使用唯一 `jsonb_parity_<uuid>` 命名空间，结束时按依赖顺序清理，并断言残留为 0。

## 11. 验收矩阵

| ID | 验收要求 |
|---|---|
| J1 | 共享类型在 PostgreSQL 编译为 JSONB，在 SQLite 编译为 TEXT |
| J2 | 原 gate 字段 1 个及本批 10 个字段全部使用共享类型 |
| J3 | `None` 双方言均为 SQL NULL；合法对象、数组和标量可往返；PostgreSQL 非法 JSON 明确失败 |
| J4 | 真实 PostgreSQL ORM 写入和读取本批 10 个字段成功，读回仍为 `str | None` |
| J5 | `jsonb_typeof` 证明对象、数组按原生 JSONB 保存，不是双重编码字符串 |
| J6 | webhook 原子语句保留 `ON CONFLICT DO NOTHING RETURNING`，不再包含手工 JSONB CAST |
| J7 | 真实 PostgreSQL 20 路 webhook 占位竞争仅一个胜出，连续 10 轮通过 |
| J8 | webhook 重复事件不产生第二个有效业务事件，原有幂等、归属和事务语义不变 |
| J9 | 发送服务使用替身上游写入 request/response 流水；网络调用和真实发送均为 0 |
| J10 | 决策日志六字段写入、读取及风险标记筛选正确 |
| J11 | webhook 事件、商户归属和工作台会话的 JSON 文本筛选在 PostgreSQL 正常执行并准确命中 |
| J12 | SQLite webhook、发送流水、决策日志及 outbox 现有专项无回归 |
| J13 | PostgreSQL 用例使用唯一命名空间，结束后相关记录残留为 0 |
| J14 | Alembic head 保持 0016，PostgreSQL 测试未调用 `create_all` |
| J15 | 指定相邻回归 Candidate 0 个新增失败；范围外基线必须由 Base/Candidate 同环境对照确认 |
| J16 | 编译、`git diff --check`、允许文件、单父线性、工作区和治理文件隔离全部通过 |

真实 PostgreSQL 独立测试必须达到：

- `0 failed`、`0 skipped`。
- 20 路竞争连续 10 轮全部通过。
- 无超时、无数据库锁错误、无遗留线程或子进程。
- 无真实 LLM、9100、抖音或微信调用。
- 日志不包含数据库密码或完整连接串。

## 12. 首批允许文件

```text
app/models.py
app/services/douyin_webhook_idempotency_service.py
app/services/webhook_event_service.py
app/services/douyin_merchant_isolation.py
app/services/douyin_workbench_conversation_service.py
app/services/ai_reply_decision_log_query_service.py
tests/test_douyin_webhook_atomic_idempotency.py
tests/test_9000_postgres_jsonb_orm_parity.py
```

最后一个文件为新增真实 PostgreSQL 专项测试。执行过程中若出现范围外独立缺陷，必须停止并回传审批窗口，不得自行扩大允许范围。

## 13. 建议提交序列

1. `修复：统一高优先级 JSONB ORM 映射`
2. `修复：消除 webhook JSONB 双重编码`
3. `修复：兼容 JSONB 字段文本筛选`
4. `测试：补齐 PostgreSQL JSONB 一致性验证`

提交必须单父线性；禁止 amend、rebase、squash、merge、cherry-pick。执行窗口使用 `git commit --only -- <allowed-files>`，不得携带既有暂存治理文件。

## 14. 候选与三权分离流程

```text
执行窗口回传 CANDIDATE_READY
→ 审批窗口代码审查
→ 独立测试窗口
→ PASS 后审批普通快进推送
→ 独立文档闭环
→ 外部今日 TODO 单独同步
→ 进入第二批 11 字段
```

旧候选不得替代最终候选进入独立测试。未经审批不得推送、部署、发布或执行生产操作。

## 15. 回退与残余风险

- 本批无数据库迁移，代码回退不要求数据回迁。
- `CAST(JSONB AS TEXT) LIKE` 只保留当前兼容筛选，不解决索引优化；数据量增长后另立任务设计 JSONB 查询和索引。
- 首批完成后仍有 11 个活跃字段和 6 个冻结字段未修。
- SQLite 对非法 JSON 继续比 PostgreSQL 宽松，这是明确保留的兼容差异。
- 本地 PostgreSQL 不能替代生产迁移、生产调度和生产恢复验证。

## 16. 文档闭环

当前设计和计划阶段不更新活动事实文档。代码候选通过独立测试并快进推送后，原位更新：

- `docs/ai/05_PROJECT_CONTEXT.md`
- `docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md`
- `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

最后单独同步外部 `E:\work\2026-07-22 auto_wechat 今日 TODO.md`。在独立测试和推送完成前，不得写成已完成、已部署或生产验证通过。
