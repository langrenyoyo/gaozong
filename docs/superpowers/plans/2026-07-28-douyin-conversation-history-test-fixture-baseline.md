# 抖音自动回复会话历史测试夹具基线返修实施计划

> **执行窗口：** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans` 按任务逐项执行。本项目固定原地执行，不创建 worktree、不新建分支；本计划使用复选框跟踪。

**目标：** 修正 dry-run 测试夹具缺失的事件商户归属，闭合 `conversation_history` 空数组导致的长期 `IndexError` 基线，同时保持普通商户不可见 NULL 归属历史事件的安全合同。

**架构：** 不改任何业务实现。仅扩展测试文件内 `_insert_event()` 的可选归属参数，并只在目标历史用例显式写入与有效绑定一致的 `merchant-1/tenant-1`。测试先断言历史长度，再验证既有两条历史消息合同。

**技术栈：** Python 3、pytest、SQLAlchemy、内存 SQLite、现有本地 FakeAiCsClient。

---

## 0. 执行合同

- Task-ID：`DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1`
- Plan-Revision：`R1`
- Specification-Commit：`dc6c9f47311e8d61448ab247ac54d1356a188abf`
- Execution-Base：`dc6c9f47311e8d61448ab247ac54d1356a188abf`
- 风险等级：`LOW`
- 业务候选允许文件：`tests/test_ai_auto_reply_dry_run.py`
- 治理计划文件：本文件可暂存但不得进入业务候选；提交实现时必须使用 `git commit --only`。

禁止修改：

- `app/**`、数据库迁移、模型、Docker/Compose、环境模板、前端、9100、Local Agent。
- `merchant_id=NULL` 历史事件的隔离语义。
- webhook 签名头相关代码或测试。
- 生产、staging、真实 PostgreSQL、真实 LLM、9100、抖音、微信和真实发送。
- 外部 TODO、活动文档和历史规格/计划。

候选冻结前不得推送、部署、迁移或真实发送；不得 amend、rebase、squash、merge、cherry-pick 或 force push。

## 1. 文件结构

| 文件 | 责任 | 本次操作 |
|---|---|---|
| `tests/test_ai_auto_reply_dry_run.py` | dry-run 事件夹具和自动回复上下文合同 | 业务候选唯一允许修改文件 |
| `docs/superpowers/plans/2026-07-28-douyin-conversation-history-test-fixture-baseline.md` | 本实施合同 | 暂存治理文件，不进入业务候选 |

不创建其他文件。

### Task 1：预检与红灯证据

**Files：**
- Read: `tests/test_ai_auto_reply_dry_run.py:49-93`
- Read: `tests/test_ai_auto_reply_dry_run.py:542-603`
- Read: `tests/test_douyin_workbench_tenant_isolation_r2.py:679-708`

- [ ] **Step 1：确认基线与治理文件隔离**

运行：

```powershell
git rev-parse HEAD
git merge-base --is-ancestor dc6c9f47311e8d61448ab247ac54d1356a188abf HEAD
git status --short
git diff --check
```

预期：HEAD 精确等于 `dc6c9f47311e8d61448ab247ac54d1356a188abf`；祖先检查退出码为 0；工作区至多只有本计划文件暂存；无空白错误。

- [ ] **Step 2：运行当前失败用例，保存红灯证据**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log -q --tb=long
```

预期：失败节点精确为该测试；异常为 `IndexError: list index out of range`，发生在对空 `conversation_history` 使用下标的期望值表达式。

- [ ] **Step 3：确认安全对照已存在且本任务不改业务过滤**

运行：

```powershell
python -m pytest tests/test_douyin_workbench_tenant_isolation_r2.py::test_null_merchant_history_events_invisible_to_normal_merchant -q
```

预期：通过；该结果是后续回归保护，证明不能在查询层兼容 NULL 商户归属。

### Task 2：最小化修正测试夹具并获得目标绿灯

**Files：**
- Modify: `tests/test_ai_auto_reply_dry_run.py:49-93`
- Modify: `tests/test_ai_auto_reply_dry_run.py:542-589`

- [ ] **Step 1：给本地夹具增加显式可选归属参数**

将 `_insert_event()` 的签名和 ORM 构造调整为以下内容，默认值必须保持 `None`：

```python
def _insert_event(
    *,
    event: str = "im_receive_msg",
    account_open_id: str = "account-open-1",
    customer_open_id: str = "customer-open-1",
    conversation_short_id: str = "conv-1",
    text: str = "你好，想了解一下A6",
    event_key: str = "event-key-1",
    server_message_id: str = "server-msg-1",
    is_duplicate: bool = False,
    merchant_id: str | None = None,
    tenant_id: str | None = None,
    created_at: datetime | None = None,
) -> int:
```

在 `DouyinWebhookEvent(...)` 构造中，与现有 `event`、`from_user_id`、`to_user_id` 等字段同级加入：

```python
merchant_id=merchant_id,
tenant_id=tenant_id,
```

不得改变其他字段、默认参数或提交行为。

- [ ] **Step 2：只为目标历史用例的三条事件写入可信归属**

在 `test_active_binding_calls_9100_with_history_and_records_decision_log()` 的每一次 `_insert_event()` 调用中，分别加入：

```python
merchant_id="merchant-1",
tenant_id="tenant-1",
```

三处都必须加入：历史客户消息、历史客服消息、当前触发消息。不得把这两个值改成 `_insert_event()` 的默认值，也不得扩散到本文件其他测试。

- [ ] **Step 3：让失败信息直接表达历史数量合同**

在取得请求载荷之后、当前完整列表相等断言之前加入：

```python
assert len(payload["conversation_history"]) == 2
```

保留现有两条字典期望值，继续校验角色、正文、时间和消息 ID；不要删除这些断言。

- [ ] **Step 4：运行目标绿灯与 NULL 隔离回归**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log -q
python -m pytest tests/test_douyin_workbench_tenant_isolation_r2.py::test_null_merchant_history_events_invisible_to_normal_merchant -q
```

预期：两项通过。第一项中 FakeAiCsClient 仅有一次本地请求，历史精确为两条；第二项继续证明 NULL 归属历史不可见。

### Task 3：相邻回归、静态检查与候选冻结

**Files：**
- Modify: `tests/test_ai_auto_reply_dry_run.py`

- [ ] **Step 1：运行 dry-run、会话历史、代理和商户隔离回归**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_dry_run.py tests/test_douyin_conversation_history_service.py tests/test_douyin_ai_cs_proxy.py tests/test_douyin_workbench_tenant_isolation_r2.py -q
```

预期：0 failed；不调用真实 9100、LLM、抖音或微信。

- [ ] **Step 2：运行原基线组合回归**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py -q
```

预期：0 failed；原 `test_active_binding_calls_9100_with_history_and_records_decision_log` 不再失败，Candidate 新增失败为 0。

- [ ] **Step 3：编译和范围检查**

运行：

```powershell
python -m py_compile tests/test_ai_auto_reply_dry_run.py
git diff --check
git diff --name-status
```

预期：编译通过、差异检查干净；未提交差异只包含测试文件与暂存的治理计划文件。

- [ ] **Step 4：提交唯一业务候选**

运行：

```powershell
git add -- tests/test_ai_auto_reply_dry_run.py
git diff --cached --check
git commit --only tests/test_ai_auto_reply_dry_run.py -m "测试：修正自动回复历史事件商户归属夹具"
```

预期：产生一个单父提交；本计划文件仍保持暂存但未进入候选提交。

- [ ] **Step 5：冻结并报告候选**

运行：

```powershell
$candidate = git rev-parse HEAD
git merge-base --is-ancestor dc6c9f47311e8d61448ab247ac54d1356a188abf $candidate
git rev-list --parents dc6c9f47311e8d61448ab247ac54d1356a188abf..$candidate
git diff --check dc6c9f47311e8d61448ab247ac54d1356a188abf..$candidate
git diff --name-status dc6c9f47311e8d61448ab247ac54d1356a188abf..$candidate
git status --short
```

预期：

```text
Base..Candidate 只有：
M  tests/test_ai_auto_reply_dry_run.py

提交链只有一个业务单父提交。
工作区只保留：
A  docs/superpowers/plans/2026-07-28-douyin-conversation-history-test-fixture-baseline.md
```

回传 `CANDIDATE_READY` 时必须包含：Task-ID、Plan-Revision、Plan SHA256、Execution-Base、Candidate、直接父提交、完整测试命令与结果、红灯与绿灯证据、范围核验、未执行生产操作和暂存治理文件状态。不得自行请求推送或执行推送。

## 2. 独立测试窗口验收

独立测试窗口必须在不修改文件的情况下复验以下内容：

1. Candidate 与当前 HEAD 精确一致；Execution-Base 是祖先；候选单父线性。
2. Candidate 差异只有 `tests/test_ai_auto_reply_dry_run.py`；治理计划不进入候选。
3. 目标测试先前的 `IndexError` 已消失，历史长度为 2。
4. NULL 商户归属历史对普通商户不可见。
5. Task 3 的两组相邻回归均为 0 failed。
6. 编译、`git diff --check`、范围和工作区状态均通过。
7. 未连接生产、未真实调用外部服务、未真实发送、未部署。

独立测试 PASS 后，审批窗口才可授权以下普通快进操作：

```powershell
$candidate = git rev-parse HEAD
git push origin "${candidate}:refs/heads/master"
```

推送后另开文档闭环，原位修正活动文档中的错误根因，并最后单独同步外部 TODO。
