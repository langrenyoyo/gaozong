# 抖音自动回复会话历史测试夹具基线返修设计

## 1. 元数据

- Task-ID：`DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1`
- Design-Revision：`D1`
- Design-Base：`d078a826f30a002657b7f563aaae82c17eb0ddd4`
- 风险等级：`LOW`
- 任务类型：测试基线夹具返修
- 实施方式：原地执行，不创建 worktree、不新建分支

> 本规格提交完成后，以规格提交哈希作为后续实施计划的实际 Execution-Base。业务候选不得包含本规格之外的治理文件改动。

## 2. 问题陈述

`tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log`
长期稳定失败，表现为测试在读取 `payload["conversation_history"][0]` 时抛出
`IndexError: list index out of range`。该失败曾在多个独立测试报告中被登记为范围外基线，
并被错误归因为 `douyin_conversation_history_service.py`。

本任务只闭合该测试基线，不改变自动回复、会话查询或商户隔离业务语义。

## 3. 根因与证据

### 3.1 直接原因

目标测试通过本文件内的 `_insert_event()` 插入三条 `DouyinWebhookEvent`：

1. 历史客户消息；
2. 历史客服消息；
3. 当前触发消息。

该测试夹具创建于商户隔离改造之前，没有写入 `merchant_id` 或 `tenant_id`。

### 3.2 数据流

当前真实调用链为：

```text
测试事件
→ run_ai_auto_reply_dry_run(event_id)
→ 从有效账号/智能体绑定取得 merchant_id=merchant-1
→ build_reply_conversation_context(..., merchant_id="merchant-1")
→ get_conversation_detail(..., merchant_id="merchant-1")
→ _query_message_rows()
→ DouyinWebhookEvent.merchant_id == "merchant-1"
```

三条夹具事件的 `merchant_id` 为 `NULL`，因此被正确的商户隔离条件排除，历史数组为空。
测试随后直接访问下标，才出现 `IndexError`。

### 3.3 生产路径对照

真实 webhook 入口 `process_webhook_event()` 会在原子占位前：

1. 按事件方向解析企业号；
2. 通过有效绑定解析可信商户和租户；
3. 将解析结果写入 `_build_webhook_event_values()`；
4. 由 `claim_webhook_event()` 原子写入事件。

现有会话历史服务专项测试同样显式给事件写入 `merchant_id`。另有独立安全合同证明：
`merchant_id=NULL` 的历史事件对普通商户必须不可见。

### 3.4 最小实验

在不修改仓库文件的内存实验中，仅给目标测试创建的三条事件补写
`merchant_id="merchant-1"`、`tenant_id="tenant-1"`，原失败用例立即通过，输出
`HYPOTHESIS_CONFIRMED`。

结论：真实根因是测试夹具缺少商户归属，不是生产会话历史服务缺陷。

## 4. 设计目标

1. 让目标测试数据符合当前真实 webhook 事件归属语义。
2. 保持商户隔离条件和 NULL 历史事件不可见合同不变。
3. 将失败诊断从数组越界改为明确的历史数量断言。
4. 只修改一个测试文件，不产生业务行为变化。
5. 关闭长期范围外基线，使后续回归不再反复做 Base/Candidate 对照。

## 5. 允许范围与禁止事项

### 5.1 业务候选允许文件

- `tests/test_ai_auto_reply_dry_run.py`

### 5.2 禁止事项

- 不修改 `app/services/douyin_conversation_history_service.py`。
- 不修改任何 `app/**` 业务代码。
- 不修改会话查询、商户过滤、webhook 入库、自动回复状态机或发送逻辑。
- 不允许 `merchant_id=NULL` 的历史事件对普通商户可见。
- 不连接 PostgreSQL、staging 或 production。
- 不调用真实 9100、LLM、抖音或微信。
- 不复测或修改 webhook 签名头。
- 不部署、不迁移、不真实发送。
- 不顺带处理消息游标、LLM 上下文压缩、违禁词或其他范围外任务。
- 业务候选不修改活动文档、外部 TODO 或已完成的历史治理计划。

## 6. 详细设计

### 6.1 测试夹具参数

给 `_insert_event()` 增加两个可选关键字参数：

```python
merchant_id: str | None = None
tenant_id: str | None = None
```

创建 `DouyinWebhookEvent` 时原样写入这两个字段。默认值保持 `None`，避免改变本文件
其他测试的历史前置条件。

### 6.2 目标测试数据

目标测试创建的三条事件均显式传入：

```python
merchant_id="merchant-1"
tenant_id="tenant-1"
```

账号、客户、会话、事件键、消息 ID、时间顺序和正文保持不变。

### 6.3 失败诊断

在构造完整历史期望值前先断言：

```python
assert len(payload["conversation_history"]) == 2
```

后续若事件归属或查询逻辑回归，失败信息直接指向历史数量，不再由期望值表达式自身触发
`IndexError`。

### 6.4 明确不采用的方案

1. 不把 `_insert_event()` 的商户/租户默认值改为固定值，避免悄然改变几十个测试。
2. 不改为通过 `process_webhook_event()` 建夹具，避免引入幂等、线索和 outbox 副作用。
3. 不在查询层兼容 `merchant_id=NULL`，该做法会破坏已批准的跨商户隔离合同。

## 7. 验收矩阵

| ID | 验收要求 |
|---|---|
| A1 | 执行前 HEAD 等于批准的 Execution-Base，工作区满足执行合同 |
| A2 | 业务候选仅修改 `tests/test_ai_auto_reply_dry_run.py` |
| A3 | 目标测试从稳定失败变为通过 |
| A4 | 目标测试三条事件均显式带 `merchant-1/tenant-1` |
| A5 | `conversation_history` 精确为两条，顺序、角色、正文和消息 ID 不变 |
| A6 | `merchant_id=NULL` 历史事件对普通商户不可见的既有测试继续通过 |
| A7 | dry-run 全文件及会话历史、代理、商户隔离相邻回归无失败 |
| A8 | outbox/send/dry-run 原基线组合不再出现该失败，Candidate 新增失败为 0 |
| A9 | 无业务文件差异、无外部调用、无真实发送、无生产连接 |
| A10 | `py_compile`、`git diff --check`、单父线性、允许范围和工作区检查通过 |

## 8. 验证方案

### 8.1 红灯证据

修改前运行：

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log -q --tb=long
```

预期：稳定出现当前 `IndexError`，保留节点、异常类型和行号证据。

### 8.2 目标与安全合同

修改后运行：

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log -q
python -m pytest tests/test_douyin_workbench_tenant_isolation_r2.py::test_null_merchant_history_events_invisible_to_normal_merchant -q
```

预期：两项均通过。

### 8.3 相邻回归

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py tests/test_douyin_conversation_history_service.py tests/test_douyin_ai_cs_proxy.py tests/test_douyin_workbench_tenant_isolation_r2.py -q
python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py -q
```

预期：0 failed，原 `conversation_history` 基线不再出现，Candidate 新增失败为 0。
测试数量以执行窗口实际收集结果为准，不在规格阶段预填。

### 8.4 静态与 Git 门禁

```powershell
python -m py_compile tests/test_ai_auto_reply_dry_run.py
git diff --check HEAD^..HEAD
git diff --name-status HEAD^..HEAD
git rev-list --parents HEAD^..HEAD
git status --short
```

预期：编译通过、差异干净、候选只有一个允许文件、提交单父线性、工作区符合合同。

## 9. 提交与三权分离

1. 实施窗口按测试驱动顺序保存红灯、完成最小修改并执行验证。
2. Commit Message 使用中文，建议：`测试：修正自动回复历史事件商户归属夹具`。
3. 实施窗口冻结候选并回传 `CANDIDATE_READY`，不得自行推送。
4. 独立测试窗口按本规格 A1-A10 复验，确认 PASS 后由审批窗口单独授权快进推送。
5. 不允许 amend、rebase、squash、merge 或 force push。

## 10. 文档影响与后续闭环

业务候选独立测试并推送后，另开独立文档闭环任务：

1. 原位纠正 `docs/ai/05_PROJECT_CONTEXT.md` 中三处错误归因。
2. 原位纠正 `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` 中相关历史记录。
3. 保留历史测试当时确实失败的数字，但注明后续已确认根因是测试夹具缺少事件商户归属，
   不是 `douyin_conversation_history_service.py` 缺陷，并记录最终候选、独立测试和集成哈希。
4. 已完成的历史 `docs/superpowers/plans` 和 `docs/superpowers/specs` 不回写，避免改写审批记录。
5. 仓库文档闭环并推送后，最后单独同步外部文件
   `E:\work\2026-07-22 auto_wechat 今日 TODO.md`。

文档闭环同样不得声称已上线、已部署、生产验证通过、全仓测试全绿或全部测试通过。
