# 抖音自动回复会话历史测试夹具基线文档闭环设计

## 1. 元数据

- Task-ID：`DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1-DOC-CLOSE-1`
- Design-Revision：`D1`
- Design-Base：`7011828ee73a2aa0bab88cb9c75c823a2336ec84`
- 关联业务任务：`DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1 / R1-T1`
- 风险等级：`LOW`
- 任务类型：活动文档事实纠正
- 执行方式：原地执行，不创建 worktree、不新建分支

## 2. 已核实事实

1. 业务候选 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的直接父提交为 `dc6c9f47311e8d61448ab247ac54d1356a188abf`，仅修改 `tests/test_ai_auto_reply_dry_run.py`。
2. 独立测试 `R1-T1` 结论为 PASS：目标历史用例 `1 passed`，NULL 商户历史隔离合同 `1 passed`，相邻回归 `138 passed`，原 outbox/send/dry-run 组合 `149 passed`，均为 0 failed。
3. 红灯根因是旧测试夹具创建的三条 `DouyinWebhookEvent` 未写入 `merchant_id/tenant_id`；商户隔离查询正确排除了 `merchant_id=NULL` 事件，测试随后对空历史使用下标而抛 `IndexError`。
4. 修复只给测试夹具增加默认 `None` 的可选归属参数，并仅在目标历史用例的三条事件中显式写入 `merchant-1/tenant-1`；未修改任何 `app/**` 业务代码。
5. `merchant_id=NULL` 历史事件对普通商户不可见的安全合同保持有效。
6. 远端 `master` 已精确等于 `7011828ee73a2aa0bab88cb9c75c823a2336ec84`。
7. 未部署、未连接 PostgreSQL/staging/production、未调用真实 LLM/9100/抖音/微信、未真实发送、未运行全仓测试。

## 3. 目标

1. 原位纠正活动文档中将该失败归因于 `douyin_conversation_history_service.py` 的错误结论。
2. 保留各历史独立测试在当时确实出现失败的数字，不倒改历史测试报告。
3. 明确记录该历史基线后来由测试夹具候选 `7011828...` 闭合。
4. 在当前事实和测试计划中记录本次独立测试范围、结果和安全边界。
5. 仓库文档闭环独立测试并推送后，再单独同步外部 TODO。

## 4. 允许范围

文档候选仅允许修改：

- `docs/ai/05_PROJECT_CONTEXT.md`
- `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

治理计划 `docs/superpowers/plans/2026-07-28-douyin-conversation-history-test-fixture-baseline.md` 保持暂存，不得进入文档候选。

## 5. 详细设计

### 5.1 `05_PROJECT_CONTEXT.md`

1. 更新时间由 `2026-07-27` 改为 `2026-07-28`。
2. 顶部摘要加入：会话历史测试夹具基线候选 `7011828...` 已通过独立测试 R1-T1，并快进集成至远端 master。
3. 原位纠正 outbox 持久化、SQLite 重启恢复、PostgreSQL/MVCC 三段中的旧根因：
   - 保留当时的失败数量和“范围外基线”历史事实。
   - 删除“根因在 `douyin_conversation_history_service.py`”结论。
   - 替换为“后续确认根因是旧测试夹具未写事件 `merchant_id/tenant_id`，不是会话历史业务服务缺陷；已由 `7011828...` 闭合”。
4. JSONB/ORM 段保留当时 `149 passed + 1` 的测试数字，并注明该基线后来闭合；不得把历史数字改为 `150 passed`。
5. 在自动回复当前事实区域新增本任务当前结论，记录单测试文件范围、R1-T1、`1/1/138/149 passed`、NULL 隔离合同及无业务代码变更。

### 5.2 `12_TEST_PLAN_AUTO_WECHAT.md`

1. 原位纠正第 27、28、29 节对应行中的错误根因，同时保留当时的测试数字。
2. 第 30 节保留 JSONB/ORM 独立测试当时的 `149 passed + 1`，增加后续闭合引用。
3. 新增独立验收小节，至少记录：
   - Task-ID、Execution-Base、Candidate 和直接父提交。
   - 红灯复现为 `IndexError`，真实根因是测试夹具缺少商户/租户归属。
   - 业务候选仅修改一个测试文件，不修改业务服务。
   - 目标历史用例 `1 passed`、NULL 隔离 `1 passed`、相邻回归 `138 passed`、原组合回归 `149 passed`、编译通过。
   - 无真实外部调用、无生产连接、无真实发送、未运行全仓测试。

## 6. 禁止事项

- 不修改 `POSTGRESQL_MIGRATION_NOTES.md`，本任务不涉及 schema、ORM 或迁移。
- 不修改任何代码、测试、迁移、配置或治理规则。
- 不回写已完成的历史规格和实施计划。
- 不修改 webhook 签名头结论。
- 不把历史独立测试数字改写成当时已经通过。
- 不声称已上线、已部署、生产验证通过、全仓测试全绿或全部测试通过。
- 不在仓库文档候选中修改外部 TODO。
- 不推送、部署、连接生产或真实发送。

## 7. 验收矩阵

| ID | 验收要求 |
|---|---|
| D1 | HEAD 等于批准的文档 Execution-Base，工作区仅保留既有治理计划暂存 |
| D2 | Base..Candidate 只修改两份允许活动文档 |
| D3 | `05_PROJECT_CONTEXT.md` 更新时间为 2026-07-28，顶部摘要含完整业务候选和 R1-T1 |
| D4 | 两份文档中三处错误的服务根因均已原位纠正 |
| D5 | JSONB/ORM 历史 `149 passed + 1` 数字保留，并明确后续闭合 |
| D6 | 新验收记录含 Base、Candidate、单测试文件范围和真实根因 |
| D7 | `1 passed`、`1 passed`、`138 passed`、`149 passed` 与独立报告一致 |
| D8 | NULL 商户历史不可见合同和无业务代码修改事实完整 |
| D9 | 生产限制、无外部调用、无真实发送和未运行全仓测试完整 |
| D10 | 禁止表述、过期错误归因、治理计划和外部 TODO 均未进入候选 |
| D11 | `git diff --check`、允许范围、单父线性和工作区检查通过 |

## 8. 文档测试

文档执行窗口必须使用只读 Git 和文本检查验证：

1. 完整业务候选 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 在两份文档均存在。
2. 新增/current 段落中“根因在 `douyin_conversation_history_service.py`”零命中；历史类名若用于否定句“不是该服务缺陷”必须人工判定语义。
3. 两份文档中的测试数字与 R1-T1 报告一致。
4. 禁止表述零命中。
5. `git diff --check` 干净，name-status 精确为两份允许文档。
6. 不运行业务测试、webhook 签名头测试或生产验证。

## 9. 提交、独立测试与外部 TODO

1. 文档执行窗口使用中文 Commit Message，只提交两份允许文档。
2. 候选冻结后回传 `CANDIDATE_READY`，不得自行推送。
3. 独立文档测试 PASS 后，由审批窗口单独授权普通快进推送。
4. 仓库文档闭环推送完成后，才允许修改外部 TODO。
5. 外部 TODO 修改前必须校验 SHA256 精确为 `D0B2F6971D8E4F541AAFE42C53B0AB242684D952AE4DB56C4F0F07D3528ACC7E`；不匹配即停止。
6. TODO 需原位纠正第 121 行错误归因，并新增该测试夹具基线闭合事实；保留其他任务数字与生产限制。
