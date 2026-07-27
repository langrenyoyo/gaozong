# 抖音 Webhook 原子幂等实现计划

> **供执行智能体使用：** REQUIRED SUB-SKILL：使用 `superpowers:executing-plans` 按任务逐项施工；本项目按 `CLAUDE.md` 固定偏好在当前工作区原地执行，不新建 worktree 或分支。步骤使用复选框跟踪。

**目标：** 在不改变 R2 业务实现的前提下，闭合 Webhook 原子幂等的旧测试合同、混合并发可信度、整体回滚/归属证据和候选文档，使完整指定回归集达到 0 failed 后再进入独立测试。

**架构：** 冻结 R2 业务候选 `c237534560fd61b3ad0c91a1aed567fd2258eaf5`。R3 只更新测试、过期注释和候选状态文档：把旧“后置异常返回 200”测试改为异常传播和整体回滚合同；把全局 patch 移出并发 worker；补齐人工接管回滚、9202 日志、跟进记录和四类归属场景。若新增测试失败且需要业务代码修改，R3 立即停止并回传审批窗口重新定界。

**技术栈：** Python 3、FastAPI、SQLAlchemy 2、SQLite、PostgreSQL、pytest、线程并发测试。

---

## 1. 治理与冻结信息

```text
State: PLAN_APPROVED
Task-ID: DY-CS-WEBHOOK-ATOMIC-IDEMPOTENCY-1
Plan-Revision: R3
Base-Commit: c519827b574ea9315bb26569998ea39e3197e87a
R1-Candidate: f79578d71f6269bd7af9979b89bfed91f25d033b
R2-Candidate: c237534560fd61b3ad0c91a1aed567fd2258eaf5
Repair-Base: c237534560fd61b3ad0c91a1aed567fd2258eaf5
Frozen-Previous-Candidate: c237534560fd61b3ad0c91a1aed567fd2258eaf5
Target-Branch: master
Risk-Level: L2
Workflow-Mode: light-three-authority
Activation-Reasons: 新增回归测试失败；并发测试全局 patch 风险；A1-A14 证据缺口；候选文档映射不一致
Owner-Constraints: 原地执行、不新建 worktree/分支；禁止生产连接、真实发送、推送、合并和发布；返修只能在 Repair-Base 上追加提交；禁止 amend/rebase/squash
```

L2 采用轻量三权的理由：R3 不修改业务实现、数据库结构或生产配置；补偿措施是冻结 R2 候选、修正真实回归合同、三类 20 路线程竞争重复测试、完整指定回归集和独立测试审批。

R3 只闭合审批审查发现的测试与文档问题。执行前 `HEAD` 必须精确等于 `Repair-Base`；R1/R2 候选必须保持可解析且哈希不变。计划文件是治理工件，不进入候选提交；不得擅自 reset、unstage、删除或提交。

## 2. 当前事实与根因

1. 9000 的 `process_webhook_event()` 先调用 `find_existing_event()`，随后创建或更新线索，最后才调用 `persist_webhook_event()`。
2. 9202 的 `process_internal_webhook_event()` 采用相同的“先查、先处理业务、最后插入事件”顺序。
3. `douyin_webhook_events.event_key` 在 ORM 和 PostgreSQL Alembic 0003 中已有唯一约束，不需要新增表或迁移。
4. 两个请求同时通过前置查询后，都可能执行线索副作用；唯一约束只能让后插入者在末尾失败，不能保护此前副作用。
5. 9000 只有在处理结果 `is_duplicate=false` 时才调度自动回复后台任务，因此只要数据库占位结果可靠，现有调度门禁可以继续复用。
6. 现有重复事件合同要求保留独立审计行：真实 `event_key` 只属于一条 `is_duplicate=false` 事件，重复到达使用 `原键:dup:UUID` 保存 `is_duplicate=true` 记录。
7. 前序候选 `f79578d71f6269bd7af9979b89bfed91f25d033b` 已完成原子占位，但 Webhook 派单调用链会进入 `assign_service.assign_lead()` 的内部 `db.commit()`，在事件 `lead_id` 回写前提前提交。
8. `mark_manual_takeover()` 同样内部提交；`im_send_msg` 胜出链路不是请求边界单次提交。
9. 前序 9202 占位值把 `merchant_id/tenant_id` 固定为 `NULL`，且使用独立业务处理器；共享唯一键后，入口胜负会改变事件归属和副作用。
10. 前序 A8 测试传入 `background_tasks=None` 且未注入调度函数，是确定性假阳性；A10 由测试自身回滚，没有验证请求边界。
11. R2 候选 `c237534560fd61b3ad0c91a1aed567fd2258eaf5` 已统一业务处理核心和事务边界，但指定回归集新增 `test_webhook_im_send_msg_post_process_error_does_not_affect_response` 失败；这是旧测试合同未同步，不能作为基线失败放行。
12. R2 混合 20 路测试仍在线程 worker 内 patch 全局 `_dispatch_lead_after_create`，违反 R2 计划并存在退出顺序恢复错误和漏计风险。
13. R2 缺少人工接管写入后异常整体回滚、9202 结构化日志、跟进记录回滚及四类归属场景的直接证据。
14. R2 回传沿用旧 A1-A14 编号，和最终 R2 矩阵不一致；文档同时写“A1-A14 全部通过”和“1 failed”，结论冲突。
15. R2 文档无法在包含自身的同一提交中引用自身哈希。R3 必须先提交测试闭合，再以单独文档提交引用前一测试候选完整哈希，禁止自引用。

## 3. R3 文件范围

**允许修改：**

- `tests/test_douyin_webhook.py`：把旧“后置异常不影响响应”用例原位改为异常传播、HTTP 500/抛出和数据库整体回滚合同。
- `tests/test_douyin_webhook_atomic_idempotency.py`：修正并发 patch，补齐 A1-A14 缺失证据并统一编号。
- `app/integrations/douyin_webhook.py`：仅允许修正 `_dispatch_lead_after_create` 和 `im_send_msg` 后置处理的过期注释/文档字符串；禁止修改可执行逻辑。
- `docs/ai/05_PROJECT_CONTEXT.md`：原位记录 R3 测试候选完整哈希、实际数字和待独立测试状态。
- `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`：原位同步 A1-A14 证据映射和实际数字。

**只运行回归、禁止修改：**

- `tests/test_webhook_events.py`
- `tests/test_leads_internal_webhook_app.py`
- `tests/test_douyin_webhook_internal_cutover.py`
- `tests/test_douyin_workbench_tenant_isolation_r2.py`
- `tests/test_phase7_fix2_assign_atomic_timezone.py`
- `tests/test_staff_merchant_crud.py`
- `tests/test_sales_followup.py`
- `tests/test_conversation_autopilot_state_service.py`

**禁止修改：**

- 除上述注释外的全部 `app/**` 和 `apps/**` 可执行逻辑。
- `app/models.py`、`migrations/**`、`frontend/**`、配置、Docker、部署脚本和生产环境。
- 模型调用、发送、gate、outbox、补偿扫描、租约、重试状态机、消息游标、SSE/WebSocket、LLM 上下文和违禁词逻辑。
- 本计划文件（执行窗口只读）。

若 R3 新增或修正后的测试在 `c237534560fd61b3ad0c91a1aed567fd2258eaf5` 上暴露业务实现缺陷，执行窗口必须停止并回传 `R3_BLOCKED`，不得修改禁止文件或放宽断言。

## 4. 冻结合同

1. `event_key` 生成算法不变。
2. 验签顺序不变：必须先验签和解析 JSON，之后才能进入数据库占位。
3. 9000 与 9202 必须调用同一个核心业务处理器；同一 payload 从任一入口胜出，原事件字段、商户/租户归属、线索、派单和 `im_send_msg` 后置处理结果一致。
4. 9000 gateway 仍是自动回复后台任务的唯一调度边界；9202 不直接调度 dry-run。internal 返回重复时，9000 不调度且不回退本地处理。
5. Webhook 胜出事务内不得出现嵌套 `commit()`。占位、线索、派单、ReplyCheck、跟进记录、人工接管状态和事件 `lead_id` 必须由请求边界一次提交。
6. `assign_lead()`、`auto_assign_next()` 和 `mark_manual_takeover()` 的新增参数默认值保持现有调用方自动提交行为；仅 Webhook 路径显式传 `commit=False`。
7. 已知业务跳过可以返回诊断；数据库、编程或未知异常必须上抛，由请求边界回滚并记录结构化日志。
8. 竞争失败者不得执行线索、派单、人工接管或自动回复副作用；必须继承胜出原事件的非空 `lead_id`、`merchant_id`、`tenant_id`，归属不明则保持 `NULL`。
9. 日志只能记录 `stage`、数据库方言、事件类型、截断后的 `event_key` 和 `failure_stage`，不得记录原始 body、手机号、微信号、完整 open_id 或密钥。
10. 不支持的数据库方言必须显式失败；不新增数据库对象，不将 SQLite 结果表述为 PostgreSQL 生产验证。

## 5. 验收矩阵

| ID | 场景 | 预期 |
|---|---|---|
| A1 | PostgreSQL/SQLite 占位 SQL | 两方言均为 `ON CONFLICT (event_key) DO NOTHING RETURNING`；PostgreSQL JSONB CAST 存在；无 `INSERT OR IGNORE` |
| A2 | 派单默认事务兼容 | 未传参数的现有调用仍提交；`commit=False` 只 flush、不 commit |
| A3 | 人工接管默认事务兼容 | 未传参数仍提交；`commit=False` 只 flush、不 commit |
| A4 | 胜出者派单后异常 | 9000 边界整体回滚，事件、线索、ReplyCheck、跟进和派单均不残留 |
| A5 | 胜出者人工接管后异常 | `im_send_msg` 的事件与人工接管状态整体回滚 |
| A6 | 9000 20 路并发 | 20 个处理均成功；1 有效、19 重复、1 线索；胜出者副作用一次 |
| A7 | 9202 20 路并发 | 与 A6 相同，且商户/租户归属与 9000 一致 |
| A8 | 9000+9202 混合 20 路 | 10+10 同事件并发；入口胜负不改变最终归属、`lead_id` 或副作用次数 |
| A9 | 重复响应继承 | 有活跃销售时 19 个重复结果和审计行均继承胜出事件的非空 `lead_id` |
| A10 | 自动回复调度 | 使用真实 `BackgroundTasks` 或可观察 fake；首次一次、重复零次；internal 重复不回退本地 |
| A11 | 外层异常回滚日志 | 9000 和 9202 均实际调用 `rollback()`；日志含 `stage`/`failure_stage`，不伪造成功 |
| A12 | 商户隔离 | 非空 merchant/tenant 继承；归属不明保持 NULL；歧义绑定不猜测 |
| A13 | 顺序重复与非线索事件 | HTTP/响应合同保持成功；不重复更新线索；非线索不创建线索 |
| A14 | 范围与回归 | 仅允许文件有差异；模型、迁移、前端、配置、发送和 outbox 无差异 |

---

## 6. R3 测试与文档闭合任务（执行窗口只执行本节）

### R3-1：原位更新 im_send_msg 后置异常测试合同

**文件：**

- 修改：`tests/test_douyin_webhook.py:1295`

- [ ] **步骤 1：复现冻结红灯**

```powershell
python -m pytest tests/test_douyin_webhook.py::test_webhook_im_send_msg_post_process_error_does_not_affect_response -q
```

预期：FAIL 或抛出 `RuntimeError("matcher failed")`；不得把它登记为 Base 历史失败。

- [ ] **步骤 2：把旧测试原位改为整体回滚合同**

在测试文件顶部增加：

```python
import logging

import pytest
```

测试重命名为：

```python
def test_webhook_im_send_msg_post_process_error_rolls_back_event_and_state(caplog):
```

保留现有 payload 和配置 patch，把请求及断言改为：

```python
with caplog.at_level(logging.ERROR, logger="integrations_router"):
    with pytest.raises(RuntimeError, match="matcher failed"):
        client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

db = _db()
try:
    assert db.query(DouyinWebhookEvent).filter(
        DouyinWebhookEvent.to_user_id == "error_customer_001",
    ).count() == 0
    assert db.query(ConversationAutopilotState).count() == 0
finally:
    db.close()

log_text = " ".join(record.getMessage() for record in caplog.records)
assert "stage=local_process" in log_text
assert "failure_stage=transaction_failed" in log_text
```

不得把业务实现改回吞异常或 HTTP 200。

- [ ] **步骤 3：运行绿灯并提交**

```powershell
python -m pytest tests/test_douyin_webhook.py::test_webhook_im_send_msg_post_process_error_rolls_back_event_and_state -q
git add -- tests/test_douyin_webhook.py
git commit --only -m "测试：同步 webhook 后置异常整体回滚合同" -- tests/test_douyin_webhook.py
```

预期 1 passed。

### R3-2：修复全局 patch 并补齐整体回滚证据

**文件：**

- 修改：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：把两个全局 patch 移出 worker**

`test_local_dispatch_called_at_most_once` 和 `test_mixed_local_internal_twenty_concurrent_is_winner_independent` 都使用以下结构：

```python
with patch.object(dw_module, "_dispatch_lead_after_create", _counting_dispatch):
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, index) for index in range(20)]
        for future in futures:
            future.result(timeout=60)
```

worker 内不得再出现 `patch.object(dw_module, "_dispatch_lead_after_create", ...)`。

- [ ] **步骤 2：让派单后异常测试发生在写入完成之后**

导入 `LeadFollowupRecord`，将现有本地回滚测试的异常注入点改为派单执行后的 `_post_process_im_send_msg`：

```python
with patch(
    "app.integrations.douyin_webhook._post_process_im_send_msg",
    side_effect=RuntimeError("forced after dispatch"),
):
    with pytest.raises(RuntimeError, match="forced after dispatch"):
        _process_webhook_locally(db, payload)

assert db2.query(DouyinWebhookEvent).count() == 0
assert db2.query(DouyinLead).count() == 0
assert db2.query(ReplyCheck).count() == 0
assert db2.query(LeadFollowupRecord).count() == 0
```

该测试必须预置同商户活跃销售，确保 ReplyCheck 和跟进记录在异常前已 flush。

- [ ] **步骤 3：增加人工接管写入后整体回滚测试**

```python
def test_takeover_state_rolls_back_when_failure_occurs_after_mark(concurrent_database):
    from app.integrations import douyin_webhook as dw_module
    from app.routers.integrations import _process_webhook_locally

    engine, Session = concurrent_database
    _setup_account_and_staff(Session)
    payload = _make_payload(event="im_send_msg", from_user_id="test_account_atomic")
    original_mark = dw_module.mark_manual_takeover

    def _mark_then_fail(*args, **kwargs):
        original_mark(*args, **kwargs)
        raise RuntimeError("forced after takeover")

    db = Session()
    try:
        with patch.object(dw_module, "mark_manual_takeover", _mark_then_fail):
            with pytest.raises(RuntimeError, match="forced after takeover"):
                _process_webhook_locally(db, payload)
    finally:
        db.close()

    db2 = Session()
    try:
        assert db2.query(DouyinWebhookEvent).count() == 0
        assert db2.query(ConversationAutopilotState).count() == 0
    finally:
        db2.close()
```

- [ ] **步骤 4：增加 9202 回滚日志断言**

新增 `test_internal_boundary_rollback_logs_stage_and_failure_stage`，实际调用 `create_internal_webhook_event()`，用 `caplog.at_level(logging.ERROR, logger="leads_internal_webhook_service")` 捕获并断言：

```python
assert "stage=internal_process" in log_text
assert "failure_stage=transaction_failed" in log_text
```

- [ ] **步骤 5：运行回滚与并发专项**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "rollback or takeover or dispatch or mixed" -q
```

预期全部通过；若失败原因指向业务实现而非测试夹具，停止并回传 `R3_BLOCKED`。

### R3-3：补齐归属矩阵并统一 A1-A14 映射

**文件：**

- 修改：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：增加四类归属测试**

增加以下具名测试：

```text
test_scope_same_merchant_same_tenant_is_inherited_by_duplicate
test_scope_same_merchant_all_tenant_null_keeps_tenant_null
test_scope_empty_and_nonempty_tenant_is_ambiguous_null
test_scope_empty_and_nonempty_merchant_stays_null_without_lead
test_scope_unbound_account_stays_null_without_lead
```

每项同时断言有效原事件、重复审计行和返回结果；归属不明/歧义场景必须断言 `DouyinLead.count() == 0`。不得仅用 `None == None` 证明继承。

- [ ] **步骤 2：按最终矩阵整理测试注释**

文件章节必须对应：A1 SQL、A2 派单事务、A3 人工接管事务、A4 派单后回滚、A5 人工接管后回滚、A6/A7/A8 三类并发、A9 重复继承、A10 调度、A11 两入口日志、A12 归属矩阵、A13 顺序重复/非线索、A14 范围与回归。

测试函数名不必包含编号，但执行窗口回传表必须使用上述映射，禁止沿用 R1 编号。

- [ ] **步骤 3：运行完整专项并提交测试闭合候选**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -q
git add -- tests/test_douyin_webhook_atomic_idempotency.py
git commit --only -m "测试：闭合 webhook 原子幂等 A1-A14 证据" -- tests/test_douyin_webhook_atomic_idempotency.py
git rev-parse HEAD
```

记录该哈希为 `R3-Test-Candidate`。专项必须多于 R2 的 21 项且 0 failed。

### R3-4：修正过期源码注释

**文件：**

- 修改：`app/integrations/douyin_webhook.py:528-625`

- [ ] **步骤 1：只更新两处注释**

将“分配/建任务异常不阻断主链路”改为“已知业务跳过不阻断；未知异常上抛并由请求边界整体回滚”。将“auto_assign_next 内部已 commit”改为“auto_assign_next(commit=False) 已 flush，提交由请求边界负责”。

禁止修改任何可执行语句、函数签名、日志参数或控制流。

- [ ] **步骤 2：核对并提交注释**

```powershell
git diff -- app/integrations/douyin_webhook.py
git diff --check
git add -- app/integrations/douyin_webhook.py
git commit --only -m "文档：同步 webhook 事务边界源码注释" -- app/integrations/douyin_webhook.py
```

差异必须只有注释/文档字符串。

### R3-5：运行完整回归与稳定性验证

- [ ] **步骤 1：运行三类 20 路竞争各 10 次**

```powershell
1..10 | ForEach-Object {
  python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "local_twenty_concurrent or internal_twenty_concurrent or mixed_local_internal_twenty_concurrent" -q
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

- [ ] **步骤 2：运行指定完整回归集**

```powershell
python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py tests/test_leads_internal_webhook_app.py tests/test_douyin_webhook_internal_cutover.py tests/test_douyin_workbench_tenant_isolation_r2.py tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_staff_merchant_crud.py tests/test_sales_followup.py tests/test_conversation_autopilot_state_service.py -q
```

预期严格 0 failed；不再允许保留 `test_webhook_im_send_msg_post_process_error_does_not_affect_response` 旧节点或任何新增失败。

- [ ] **步骤 3：运行语法和范围检查**

```powershell
python -m py_compile app/integrations/douyin_webhook.py tests/test_douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py
git diff --check c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git diff --name-status c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git diff --name-status c237534560fd61b3ad0c91a1aed567fd2258eaf5..HEAD
```

R3 增量只能包含两份测试和 `douyin_webhook.py` 的注释。若需要修改业务实现，停止并回传 `R3_BLOCKED`。

- [ ] **步骤 4：冻结测试父候选**

确认所有测试通过后执行 `git rev-parse HEAD`，记录为 `Parent-Tested-Candidate`。后续文档提交必须引用这个完整 40 位哈希。

### R3-6：原位更新文档并创建最终候选

**文件：**

- 修改：`docs/ai/05_PROJECT_CONTEXT.md`
- 修改：`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

- [ ] **步骤 1：删除冲突和悬空表述**

删除“A1-A14 全部通过但仍有 1 failed”和“新候选待提交后回传完整哈希”。改为记录 `Parent-Tested-Candidate` 完整哈希、准确测试数字、三类并发 10 轮结果及“待独立测试确认”。

- [ ] **步骤 2：按最终 A1-A14 原位更新**

明确旧 im_send_msg 测试已改为异常传播/整体回滚合同；混合 patch 已移出 worker；人工接管回滚、9202 日志、跟进记录和四类归属矩阵均有测试证据。不得追加“最新补充”。

- [ ] **步骤 3：提交独立文档候选**

```powershell
git add -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git commit --only -m "文档：记录 webhook 原子幂等 R3 测试候选" -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git rev-parse HEAD
```

最终候选哈希与 `Parent-Tested-Candidate` 不同是正常的；文档引用父测试候选，禁止尝试引用自身哈希。

- [ ] **步骤 4：核对线性历史并回传**

```powershell
git merge-base --is-ancestor c237534560fd61b3ad0c91a1aed567fd2258eaf5 HEAD
git log --oneline c237534560fd61b3ad0c91a1aed567fd2258eaf5..HEAD
git rev-list --parents c237534560fd61b3ad0c91a1aed567fd2258eaf5..HEAD
git status --short
```

只回传 `CANDIDATE_READY <完整 40 位哈希>`，同时提供 `Parent-Tested-Candidate`。不得自行发出 `TEST_REQUEST`、批准测试、推送或发布。

## 7. R2 历史任务（已由 c237534 完成，R3 执行窗口禁止重复执行）

以下 R2 内容保留为设计追溯证据；凡与 R3 第 1-6 节冲突，以 R3 为准。

### R2-1：建立事务、调度和混合入口红灯测试

**文件：**

- 修改：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：替换 A8 假阳性测试**

使用真实 `BackgroundTasks`，不得定义未注入的 `fake_run`：

```python
from fastapi import BackgroundTasks


def test_auto_reply_schedule_once_for_winner_and_zero_for_duplicate():
    from app.routers.integrations import maybe_schedule_ai_auto_reply

    winner_tasks = BackgroundTasks()
    maybe_schedule_ai_auto_reply(
        background_tasks=winner_tasks,
        event_id=101,
        payload={"event": "im_receive_msg", "to_user_id": "account"},
        is_duplicate=False,
        source_path="/douyin/webhook",
    )
    assert len(winner_tasks.tasks) == 1
    assert winner_tasks.tasks[0].args == (101,)

    duplicate_tasks = BackgroundTasks()
    maybe_schedule_ai_auto_reply(
        background_tasks=duplicate_tasks,
        event_id=102,
        payload={"event": "im_receive_msg", "to_user_id": "account"},
        is_duplicate=True,
        source_path="/douyin/webhook",
    )
    assert duplicate_tasks.tasks == []
```

- [ ] **步骤 2：增加 internal 重复不回退测试**

在测试文件定义带 `create_internal_webhook_event()` 的 `FakeLeadsClient`，让其返回完整重复响应；patch `_process_webhook_locally` 为 `pytest.fail()`，然后调用 `_process_webhook_with_internal()` 并断言 `is_duplicate is True`。不得只检查源码字符串。

- [ ] **步骤 3：增加具名事务与混合入口测试**

必须增加：

```text
test_webhook_dispatch_path_does_not_commit_before_request_boundary
test_webhook_takeover_path_does_not_commit_before_request_boundary
test_local_boundary_rolls_back_after_dispatch_side_effect_failure
test_internal_boundary_rolls_back_after_business_failure
test_mixed_local_internal_twenty_concurrent_is_winner_independent
test_duplicate_results_inherit_non_null_lead_and_scope
```

派单测试预置同商户活跃销售并使用含联系方式消息。混合用例使用同一个 `threading.Barrier(20)` 和 20 个独立 Session：10 个调用 `process_webhook_event()`，10 个调用 `process_internal_webhook_event()`。全局 patch 必须包在线程启动器外层，禁止每个 worker 各自 patch 同一个函数。

- [ ] **步骤 4：运行红灯测试**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -q
```

预期至少因派单/人工接管嵌套提交、9202 归属不一致和旧 A8 测试替换而失败；不得放宽断言。

- [ ] **步骤 5：提交红灯测试**

```powershell
git add -- tests/test_douyin_webhook_atomic_idempotency.py
git commit --only -m "测试：补全 webhook 原子事务与混合入口红灯用例" -- tests/test_douyin_webhook_atomic_idempotency.py
```

### R2-2：消除派单和人工接管的嵌套提交

**文件：**

- 修改：`app/services/assign_service.py`
- 修改：`app/services/conversation_autopilot_state_service.py`
- 修改：`app/integrations/douyin_webhook.py`
- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：为派单增加默认兼容事务参数**

`assign_lead()` 增加 keyword-only `commit: bool = True`。现有对象更新和跟进记录创建后固定执行：

```python
db.flush()
if commit:
    db.commit()
db.refresh(lead)
return lead
```

`auto_assign_next()` 签名改为：

```python
def auto_assign_next(db: Session, lead_id: int, *, commit: bool = True) -> DouyinLead:
```

其最终调用必须为：

```python
return assign_lead(db, lead_id, min_staff_id, commit=commit)
```

Webhook `_dispatch_lead_after_create()` 调用 `auto_assign_next(db, lead.id, commit=False)`。已知 `ValueError` 继续映射业务诊断；未知 `Exception` 记录安全日志后必须重新抛出。

- [ ] **步骤 2：为人工接管增加默认兼容事务参数**

`mark_manual_takeover()` 增加 `commit: bool = True`，状态更新后的固定尾部为：

```python
db.flush()
if commit:
    db.commit()
db.refresh(state)
return state
```

Webhook `_post_process_im_send_msg()` 必须传 `commit=False`。预期跳过分支继续返回；未知异常记录安全日志后重新抛出。

- [ ] **步骤 3：删除胜出路径吞异常外壳**

`process_webhook_event()` 不得捕获并吞掉 `_dispatch_lead_after_create()` 的未知异常。请求边界继续负责 `rollback()`、结构化日志和重新抛出。

- [ ] **步骤 4：运行事务专项与兼容回归**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "commit or rollback or dispatch or takeover" -q
python -m pytest tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_staff_merchant_crud.py tests/test_sales_followup.py tests/test_conversation_autopilot_state_service.py -q
```

预期全部通过；默认调用方仍提交，Webhook 路径无请求边界前提交。

- [ ] **步骤 5：提交事务修复**

```powershell
git add -- app/services/assign_service.py app/services/conversation_autopilot_state_service.py app/integrations/douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py
git commit --only -m "安全：统一 webhook 胜出者事务提交边界" -- app/services/assign_service.py app/services/conversation_autopilot_state_service.py app/integrations/douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py
```

### R2-3：统一 9000 与 9202 胜出者处理核心

**文件：**

- 修改：`apps/leads/webhook_events.py`
- 修改：`apps/leads/services.py`
- 修改：`app/integrations/douyin_webhook.py`
- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：让 9202 委托同一处理器**

`apps/leads/webhook_events.py` 的生产入口改为：

```python
from app.integrations.douyin_webhook import process_webhook_event


def process_internal_webhook_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """处理已由 9000 gateway 验签的 internal webhook，不直接调度 dry-run。"""
    return process_webhook_event(db, payload)
```

旧公开辅助函数若仍有测试或调用方引用可以保留，但不得形成第二条生产处理路径；删除因此产生的未使用占位 import。

- [ ] **步骤 2：保持请求边界单次提交**

`_process_webhook_locally()` 和 `create_internal_webhook_event()` 成功路径各只允许一次 `commit()`；异常路径各调用一次 `rollback()`、记录安全的 `stage`/`failure_stage` 并重新抛出。

- [ ] **步骤 3：验证入口胜负无关**

混合 20 路至少断言：

```python
assert sum(not item["is_duplicate"] for item in results) == 1
assert sum(item["is_duplicate"] for item in results) == 19
assert valid_event.merchant_id == "merchant_atomic"
assert valid_event.tenant_id == "tenant_atomic"
assert valid_event.lead_id is not None
assert {item["lead_id"] for item in results} == {valid_event.lead_id}
assert dispatch_call_count == 1
```

另加两个顺序测试：9202 先胜出后 9000 重复、9000 先胜出后 9202 重复；两者最终数据库事实一致。

- [ ] **步骤 4：运行双入口专项**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "internal or mixed or scope or duplicate" -q
python -m pytest tests/test_leads_internal_webhook_app.py tests/test_douyin_webhook_internal_cutover.py -q
```

- [ ] **步骤 5：提交双入口修复**

```powershell
git add -- apps/leads/webhook_events.py apps/leads/services.py app/integrations/douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py
git commit --only -m "安全：统一 9000 与 9202 webhook 胜出者处理" -- apps/leads/webhook_events.py apps/leads/services.py app/integrations/douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py
```

### R2-4：闭合真实调度、回滚和归属测试

**文件：**

- 修改：`app/routers/integrations.py`
- 修改：`apps/leads/services.py`
- 修改：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：验证真实请求边界回滚**

9000 测试调用 `_process_webhook_locally()`，9202 测试调用 `create_internal_webhook_event()`。使用可观察 Session 或 mock 断言异常时 `rollback.call_count == 1`、`commit.call_count == 0`，并以 `caplog` 断言：

```text
stage=local_process failure_stage=transaction_failed
stage=internal_process failure_stage=transaction_failed
```

- [ ] **步骤 2：验证真实数据库整体回滚**

预置有效账号、同商户活跃销售和含联系方式消息，在派单与事件 `lead_id` 已 flush 后注入未知异常。通过新 Session 断言原事件、线索、ReplyCheck、跟进记录均不存在；不得由测试代码手动回滚后把结果算作边界通过。

- [ ] **步骤 3：验证商户/租户继承与 NULL 语义**

至少覆盖：唯一 merchant+tenant；唯一 merchant 且 tenant 全空；merchant 或 tenant 空值与非空混合；无有效绑定。前两类重复审计必须继承原值，歧义和无绑定必须保持 NULL 且不创建商户线索。

- [ ] **步骤 4：运行完整专项并提交**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -q
git add -- app/routers/integrations.py apps/leads/services.py tests/test_douyin_webhook_atomic_idempotency.py
git commit --only -m "测试：闭合 webhook 调度回滚与归属合同" -- app/routers/integrations.py apps/leads/services.py tests/test_douyin_webhook_atomic_idempotency.py
```

预期专项测试数高于前序候选的 12 项，且 0 failed。

### R2-5：专项回归、稳定性和范围核对

- [ ] **步骤 1：重复三类 20 路竞争各 10 次**

```powershell
1..10 | ForEach-Object {
  python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "local_twenty_concurrent or internal_twenty_concurrent or mixed_local_internal_twenty_concurrent" -q
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

预期无 `database is locked`、线程残留、临时文件残留或 500。

- [ ] **步骤 2：运行完整回归**

```powershell
python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py tests/test_leads_internal_webhook_app.py tests/test_douyin_webhook_internal_cutover.py tests/test_douyin_workbench_tenant_isolation_r2.py tests/test_phase7_fix2_assign_atomic_timezone.py tests/test_staff_merchant_crud.py tests/test_sales_followup.py tests/test_conversation_autopilot_state_service.py -q
```

预期 0 failed。历史失败必须在原始 Base 使用同一命令复现并比较节点和错误正文。

- [ ] **步骤 3：运行语法和范围检查**

```powershell
python -m py_compile app/services/douyin_webhook_idempotency_service.py app/services/assign_service.py app/services/conversation_autopilot_state_service.py app/integrations/douyin_webhook.py app/routers/integrations.py apps/leads/webhook_events.py apps/leads/services.py
git diff --check c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git diff --name-status c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git diff --name-status f79578d71f6269bd7af9979b89bfed91f25d033b..HEAD
```

全量差异只能落在 R1 的 8 个文件加 R2 新增允许的两个服务文件。记录未连接真实 PostgreSQL、未做生产并发、未触发真实发送、未运行全仓测试。

### R2-6：原位更新文档并创建追加式候选

**文件：**

- 修改：`docs/ai/05_PROJECT_CONTEXT.md`
- 修改：`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

- [ ] **步骤 1：修正文档证据强度**

只能写“R2 候选已实现，执行窗口自测通过，待独立测试确认”，并记录前序候选、新候选完整哈希、实际测试数字及未验证项。不得写“独立测试通过”“已上线”“已部署”“生产验证通过”或“全仓测试全绿”。

- [ ] **步骤 2：原位更新 A1-A14**

明确嵌套提交已消除、9202 复用同一核心、混合 20 路、真实调度门禁、外层回滚和非空归属继承；不得追加“最新补充”。

- [ ] **步骤 3：只暂存允许文件并提交**

```powershell
git add -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git diff --cached --name-status
git commit --only -m "文档：记录 webhook 原子幂等 R2 候选状态" -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
```

计划治理文件和候选外用户改动不得进入提交。R2 所有提交都必须使用上面的 `git commit --only` 路径清单；禁止执行不带 pathspec 的普通 `git commit`。

- [ ] **步骤 4：核对追加历史并回传**

```powershell
git rev-parse HEAD
git merge-base --is-ancestor f79578d71f6269bd7af9979b89bfed91f25d033b HEAD
git log --oneline f79578d71f6269bd7af9979b89bfed91f25d033b..HEAD
git rev-list --parents f79578d71f6269bd7af9979b89bfed91f25d033b..HEAD
git status --short
```

只回传 `CANDIDATE_READY <完整 40 位哈希>`；不得自行发出 `TEST_REQUEST`、批准测试、推送或发布。

## 8. R1 历史任务（已由 f79578d 完成，R3 执行窗口禁止重复执行）

以下内容保留为 R1 设计和追溯证据。凡与 R2 第 1-6 节冲突，以 R2 为准。

### R1 历史任务 1：先建立原子占位红灯测试

**文件：**

- 新增：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：建立文件型 SQLite 并发夹具**

使用独立临时数据库、每线程独立 Session、WAL 和 30 秒忙等待，禁止用 `StaticPool` 共享同一连接伪装并发：

```python
@pytest.fixture
def concurrent_database(tmp_path):
    database_path = tmp_path / "webhook_atomic.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=20,
        max_overflow=0,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield engine, session_factory
    engine.dispose()
```

- [ ] **步骤 2：建立固定 20 路同步启动器**

```python
def _run_twenty_workers(worker):
    barrier = threading.Barrier(20)

    def _run(index):
        barrier.wait(timeout=10)
        return worker(index)

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_run, index) for index in range(20)]
        return [future.result(timeout=60) for future in futures]
```

- [ ] **步骤 3：添加 PostgreSQL/SQLite SQL 合同红灯测试**

```python
def test_claim_statement_uses_postgresql_on_conflict_returning():
    statement = build_webhook_claim_statement("postgresql", _claim_values())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING douyin_webhook_events.id" in sql
    assert "CAST(" in sql and "AS JSONB" in sql


def test_claim_statement_uses_sqlite_on_conflict_returning_without_insert_or_ignore():
    statement = build_webhook_claim_statement("sqlite", _claim_values())
    sql = str(statement.compile(dialect=sqlite.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING id" in sql
    assert "INSERT OR IGNORE" not in sql
```

- [ ] **步骤 4：添加 9000 与 9202 的 20 路并发红灯测试**

测试分别调用 `process_webhook_event()` 和 `process_internal_webhook_event()`，每个 worker 自建 Session、调用处理函数并 `commit()`；最终断言：

```python
assert len(results) == 20
assert sum(result["is_duplicate"] is False for result in results) == 1
assert sum(result["is_duplicate"] is True for result in results) == 19
assert session.query(DouyinWebhookEvent).filter_by(is_duplicate=False).count() == 1
assert session.query(DouyinWebhookEvent).filter_by(is_duplicate=True).count() == 19
assert session.query(DouyinLead).count() == 1
```

9000 用例用线程锁统计 `_dispatch_lead_after_create` 调用次数并断言为 1；另保留路由级测试，断言首次事件调用一次 `run_ai_auto_reply_dry_run`，19 个重复结果不调用。

- [ ] **步骤 5：运行红灯测试**

运行：

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -q
```

预期：因 `douyin_webhook_idempotency_service` 和原子占位函数尚不存在，测试收集或对应断言失败；不得出现误通过。

- [ ] **步骤 6：提交红灯测试**

```powershell
git add -- tests/test_douyin_webhook_atomic_idempotency.py
git commit -m "测试：增加抖音 webhook 原子幂等并发红灯用例"
```

---

### R1 历史任务 2：实现共享的跨方言原子占位服务

**文件：**

- 新增：`app/services/douyin_webhook_idempotency_service.py`
- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：定义占位结果和方言语句构造函数**

```python
@dataclass
class WebhookEventClaim:
    event: DouyinWebhookEvent
    won: bool


def build_webhook_claim_statement(dialect_name: str, values: dict[str, Any]):
    table = DouyinWebhookEvent.__table__
    if dialect_name == "postgresql":
        postgres_values = dict(values)
        postgres_values["raw_body"] = cast(values["raw_body"], JSONB)
        if values.get("parsed_content_json") is not None:
            postgres_values["parsed_content_json"] = cast(values["parsed_content_json"], JSONB)
        return (
            postgresql_insert(table)
            .values(**postgres_values)
            .on_conflict_do_nothing(index_elements=[table.c.event_key])
            .returning(table.c.id)
        )
    if dialect_name == "sqlite":
        return (
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[table.c.event_key])
            .returning(table.c.id)
        )
    raise RuntimeError(f"不支持 webhook 原子幂等的数据库方言: {dialect_name}")
```

PostgreSQL 的两个显式 JSONB `CAST` 是必需的：当前 ORM 仍把 `raw_body`/`parsed_content_json` 声明为 Text，而 Alembic 0003 的真实列为 JSONB；本任务只确保新增占位 SQL 符合现有 PostgreSQL schema，不顺便修改 ORM 或迁移。

- [ ] **步骤 2：实现占位并读取胜出/原始事件**

```python
def claim_webhook_event(db: Session, *, values: dict[str, Any]) -> WebhookEventClaim:
    dialect_name = db.get_bind().dialect.name
    statement = build_webhook_claim_statement(dialect_name, values)
    event_id = db.execute(statement).scalar_one_or_none()
    if event_id is not None:
        event = db.get(DouyinWebhookEvent, event_id)
        if event is None:
            raise RuntimeError("webhook 占位成功但无法读取事件")
        logger.info(
            "webhook_idempotency stage=claim action=won backend=%s event_key=%s",
            dialect_name,
            str(values["event_key"])[:12],
        )
        return WebhookEventClaim(event=event, won=True)

    event = (
        db.query(DouyinWebhookEvent)
        .filter(
            DouyinWebhookEvent.event_key == values["event_key"],
            DouyinWebhookEvent.is_duplicate.is_(False),
        )
        .one_or_none()
    )
    if event is None:
        raise RuntimeError("webhook 幂等竞争结束后无法读取胜出事件")
    logger.info(
        "webhook_idempotency stage=claim action=duplicate backend=%s event_key=%s",
        dialect_name,
        str(values["event_key"])[:12],
    )
    return WebhookEventClaim(event=event, won=False)
```

- [ ] **步骤 3：运行 SQL 合同测试**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "claim_statement" -q
```

预期：2 passed。

- [ ] **步骤 4：提交共享服务**

```powershell
git add -- app/services/douyin_webhook_idempotency_service.py tests/test_douyin_webhook_atomic_idempotency.py
git commit -m "安全：增加 webhook 跨方言原子占位服务"
```

---

### R1 历史任务 3：将 9000 本地处理改为先占位后副作用

**文件：**

- 修改：`app/integrations/douyin_webhook.py:250-820`
- 修改：`app/routers/integrations.py:121-125`
- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：把现有首次事件构造改成纯值构造**

将 `persist_webhook_event()` 改为不写数据库的 `_build_webhook_event_values()`，完整保留当前归一化字段：

```python
def _build_webhook_event_values(
    payload: dict[str, Any],
    event_key: str,
    *,
    merchant_id: str | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    normalized = parse_douyin_callback_event(payload)
    return {
        "event": payload.get("event"),
        "from_user_id": payload.get("from_user_id"),
        "to_user_id": payload.get("to_user_id"),
        **normalized,
        "event_key": event_key,
        "is_duplicate": False,
        "lead_id": None,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "raw_body": json.dumps(payload, ensure_ascii=False),
        "created_at": datetime.now(),
    }
```

- [ ] **步骤 2：在任何写入和副作用前完成只读解析与占位**

`process_webhook_event()` 的固定顺序：

```text
build_event_key
-> parse content / resolve merchant scope（只读）
-> claim_webhook_event
-> 未胜出：persist_duplicate_webhook_event + 直接返回
-> 胜出：线索 upsert / 派单 / im_send_msg 后置处理
-> event.lead_id = lead_id
-> flush
```

竞争失败分支必须使用 `claim.event` 的 `lead_id`、`merchant_id`、`tenant_id`，禁止按当前绑定重新推测历史归属。

- [ ] **步骤 3：保持自动回复只由胜出结果调度**

不修改 `maybe_schedule_ai_auto_reply()` 的条件。新增路由测试明确断言：20 个结果中只有一个 `is_duplicate=false`，因此 `run_ai_auto_reply_dry_run` 只收到胜出事件 ID 一次。

- [ ] **步骤 4：为本地事务补充显式回滚日志**

```python
def _process_webhook_locally(db: Session, payload: dict) -> dict:
    try:
        result = process_webhook_event(db, payload)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception(
            "webhook_transaction stage=local_process failure_stage=transaction_failed error_type=%s",
            type(exc).__name__,
        )
        raise
    return _normalize_webhook_result(result)
```

- [ ] **步骤 5：运行 9000 并发和既有重复合同测试**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "local or schedule" -q
python -m pytest tests/test_douyin_webhook.py -k "duplicate or idempotent or background_task" -q
```

预期：全部通过，且并发用例无 `IntegrityError`、无 `database is locked`、无 500。

- [ ] **步骤 6：提交 9000 改造**

```powershell
git add -- app/integrations/douyin_webhook.py app/routers/integrations.py tests/test_douyin_webhook_atomic_idempotency.py
git commit -m "安全：收敛 9000 webhook 原子幂等处理"
```

---

### R1 历史任务 4：将 9202 internal 处理接入相同占位服务

**文件：**

- 修改：`apps/leads/webhook_events.py:138-370`
- 修改：`apps/leads/services.py:92-113`
- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：将 9202 首次事件构造改成纯值构造**

使用与 9000 相同字段合同，但保持 9202 当前行为：不在本任务补写新的商户/租户事件字段，也不触发 dry-run。

- [ ] **步骤 2：调用共享 `claim_webhook_event()`**

固定顺序与 9000 一致：只读解析和绑定检查 -> 原子占位 -> 失败者重复审计并返回 -> 胜出者线索处理 -> 回写 `lead_id`。

- [ ] **步骤 3：为 internal 事务补充显式回滚日志**

```python
def create_internal_webhook_event(db: Session, request: InternalWebhookEventRequest) -> InternalWebhookEventResponse:
    if not request.signature_verified:
        raise HTTPException(
            status_code=400,
            detail={"code": "WEBHOOK_SIGNATURE_NOT_VERIFIED", "message": "webhook 尚未由网关验签"},
        )
    try:
        result = process_internal_webhook_event(db, request.payload)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception(
            "webhook_transaction stage=internal_process failure_stage=transaction_failed error_type=%s",
            type(exc).__name__,
        )
        raise
    return InternalWebhookEventResponse(
        event_id=result.get("event_id"),
        lead_id=result.get("lead_id"),
        is_new_lead=bool(result.get("is_new_lead")),
        is_duplicate=bool(result.get("is_duplicate")),
        lead_action=str(result.get("lead_action") or "not_lead_event"),
    )
```

- [ ] **步骤 4：运行 internal 并发和切流合同测试**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "internal" -q
python -m pytest tests/test_leads_internal_webhook_app.py tests/test_douyin_webhook_internal_cutover.py -q
```

预期：全部通过；20 路 internal 请求均成功且仅一条有效事件、一条线索。

- [ ] **步骤 5：提交 9202 改造**

```powershell
git add -- apps/leads/webhook_events.py apps/leads/services.py tests/test_douyin_webhook_atomic_idempotency.py
git commit -m "安全：统一 9202 webhook 原子幂等处理"
```

---

### R1 历史任务 5：完成专项回归、稳定性重复和范围核对

**文件：**

- 测试：`tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **步骤 1：运行原子幂等专项测试**

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -q
```

预期：全部通过，0 failed。

- [ ] **步骤 2：重复运行两个 20 路竞争用例 10 次**

```powershell
1..10 | ForEach-Object { python -m pytest tests/test_douyin_webhook_atomic_idempotency.py -k "twenty_concurrent" -q; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

预期：10 轮全部通过；无 SQLite locked、线程残留或临时文件残留。

- [ ] **步骤 3：运行 Webhook 与商户隔离回归集**

```powershell
python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py tests/test_leads_internal_webhook_app.py tests/test_douyin_webhook_internal_cutover.py tests/test_douyin_workbench_tenant_isolation_r2.py -q
```

预期：0 failed；若出现历史失败，必须在 Base 上用完全相同命令复现并证明节点和错误正文一致，不能直接标记通过。

- [ ] **步骤 4：运行语法和差异检查**

```powershell
python -m py_compile app/services/douyin_webhook_idempotency_service.py app/integrations/douyin_webhook.py app/routers/integrations.py apps/leads/webhook_events.py apps/leads/services.py
git diff --check
git status --short
```

预期：语法检查成功；无空白错误；受控改动只在 Allowed-Files。

- [ ] **步骤 5：记录未执行项**

必须如实记录：未连接真实 PostgreSQL、未进行生产 20 路并发、未触发真实私信/自动回复/微信发送、未运行全仓测试。

---

### R1 历史任务 6：原位更新文档并创建冻结候选

**文件：**

- 修改：`docs/ai/05_PROJECT_CONTEXT.md`
- 修改：`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

- [ ] **步骤 1：更新当前事实**

在 `05_PROJECT_CONTEXT.md` 第 9.1 节原位加入本任务候选事实，措辞必须是“候选已实现，待独立测试确认”，并保留：未推送、未合并、未发布、未验证真实 PostgreSQL/生产并发/真实发送。

- [ ] **步骤 2：更新验收合同**

在 `12_TEST_PLAN_AUTO_WECHAT.md` 第 9 节原位增加：20 路并发、仅一名胜出者执行副作用、9000/9202 一致、重复请求 HTTP 200、PostgreSQL `ON CONFLICT DO NOTHING RETURNING`。不得追加“最新补充”。

- [ ] **步骤 3：执行文档一致性检查**

```powershell
rg -n "待独立测试确认|20 路|ON CONFLICT DO NOTHING RETURNING|9202" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
rg -n "已上线|已部署|生产验证通过|全仓测试全绿" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git diff --check
```

预期：必需文本存在；禁止文本无新增命中；差异检查通过。

- [ ] **步骤 4：只暂存允许文件并核对**

```powershell
git add -- app/services/douyin_webhook_idempotency_service.py app/integrations/douyin_webhook.py app/routers/integrations.py apps/leads/webhook_events.py apps/leads/services.py tests/test_douyin_webhook_atomic_idempotency.py docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git diff --cached --name-status
```

预期：严格等于上述 8 个文件；不得包含权威待办文件、其他外部文件、缓存、日志、数据库或构建产物。

- [ ] **步骤 5：创建本地候选提交**

```powershell
git commit -m "安全：实现抖音 webhook 原子幂等"
git rev-parse HEAD
git merge-base --is-ancestor c519827b574ea9315bb26569998ea39e3197e87a HEAD
git log --oneline c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git rev-list --parents c519827b574ea9315bb26569998ea39e3197e87a..HEAD
git status --short
```

预期：候选继承冻结 Base、提交线性、工作区干净。执行窗口只回传 `CANDIDATE_READY <完整哈希>`，不得自行发出测试请求、推送或发布。

## 9. 回滚方案

1. 前序候选未推送，保持 `f79578d71f6269bd7af9979b89bfed91f25d033b` 和 `c237534560fd61b3ad0c91a1aed567fd2258eaf5` 不变；R3 返工必须从 R2 候选追加新提交。
2. 推送前发现问题，由审批窗口继续发出追加式返修；禁止 amend、rebase、squash 或强推。
3. 本批无迁移和新表，代码回滚不需要数据库降级；已有有效事件、重复审计行和线索数据保持可读。
4. 若未来真实 PostgreSQL 验证失败，停止生产发布，保留旧代码版本运行；不得退回“先查再插”作为静默降级。

## 10. 独立测试最低要求

测试窗口必须从 R3 最终候选重新设计并执行 A1-A14，不能复用执行窗口结论。至少包括 9000、9202、9000+9202 混合三类 20 路竞争各重复 10 次、两个入口胜负顺序、活跃销售非空 `lead_id` 继承、派单后跟进记录整体回滚、人工接管整体回滚、真实 `BackgroundTasks` 调度、9000/9202 外层 rollback 日志、四类归属矩阵、完整指定回归集、语法和 Git 范围检查。

SQLite 并发通过不能替代 PostgreSQL 生产验证；缺少真实 PostgreSQL 环境可作为明确残余风险，但 PostgreSQL `ON CONFLICT ... RETURNING` 和 JSONB CAST 编译失败属于阻塞失败，不能条件通过。
