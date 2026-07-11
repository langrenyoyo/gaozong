# Phase 7-FIX1 微信派单与销售反馈完整性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐微信真实派单的销售分配开关和固定限频 gate，并收紧销售反馈的商户上下文、编号、日期、失败落库与事务边界，使派单和回复检测在异常场景下仍保持幂等、隔离和核心状态可提交。

**Architecture:** 复用现有 `evaluate_lead_wechat_notify_eligibility()` 作为派单资格唯一入口，复用 `SalesStaff` 现有开关和 `WechatTask.created_at/status` 实现固定 10 秒限频，不新增配置、字段或迁移。销售反馈继续复用三张 Phase 1 业务表和 `build_feedback_no()`，但只允许可信商户上下文和成功解析写库；回复检测先提交核心 `replied` 状态，再在独立事务中解析反馈。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、Python 标准库 `datetime`、pytest、SQLite 临时测试库、PostgreSQL 行锁语义。

---

## 审批窗口结论

Phase 7 执行回传暂不直接进入 Phase 8，先完成本 FIX1。当前审批窗口只制定执行包，不修改业务代码、不提交、不启动服务、不执行真实请求。

执行方式固定为 **Subagent-Driven**：每个实现任务由独立 Implementer 完成，随后依次经过 Spec Reviewer 和 Code Quality Reviewer；上一个任务通过后才进入下一个任务。

## 根因结论

本执行包只处理已确认的 7 个根因：

1. 微信真实派单资格判断没有限频 gate。
2. `SalesStaff.enable_lead_assignment` 只被透出，未进入手动分配、自动分配和派单资格判断。
3. `/sales-feedback/parse` 信任请求中的 `lead_id/staff_id`，未验证可信商户归属。
4. 请求中的 `feedback_no` 未绑定当前 `lead_id/staff_id`，可能覆盖错误反馈。
5. 非法日期仍会返回成功，并在持久化时回退为当前日期。
6. `parse_and_persist_sales_feedback()` 内部 `commit()` 嵌入回复状态事务；数据库异常后未可靠 rollback。
7. `failed` 解析会写业务表，并可能覆盖已有成功记录的原文和解析状态。

不在本阶段顺手清理兼容 helper，不重构整个任务状态机，不新增审计表。

## 阶段验收口径

### 派单与分配

1. `enable_lead_assignment=false` 时，销售不能被手动分配、不能被自动分配，也不能为其新建真实 `notify_sales` 任务。
2. 同一商户、同一销售在 10 秒内最多创建一个有效 `notify_sales` 任务。
3. 有效状态固定为 `pending`、`running`、`pasted`、`sent`；`failed`、`blocked`、`cancelled` 不计入限频。
4. 限频必须按商户隔离；`WechatTask` 没有 `merchant_id`，必须通过 `WechatTask JOIN DouyinLead` 判断商户。
5. 同一线索已有 pending/running/pasted 或已发送任务时，沿用现有幂等响应，优先于开关和限频判断。
6. 新建任务命中限频时，POST 返回 HTTP `429` 并包含 `Retry-After` 响应头；只读状态接口返回稳定原因和剩余秒数。
7. PostgreSQL 新建任务路径必须锁定销售行，使“检查限频 -> 创建任务 -> 提交”处于同一事务；GET 状态接口不得加锁。

### 销售反馈

1. 清洗后第一行必须精确等于 `【线索反馈】`、`【线索更新】` 或 `【每日线索总结】`，正文中仅包含模板头不算模板。
2. 线索反馈/更新要求 `lead_id`、`staff_id` 均存在且属于当前可信 `context.merchant_id`。
3. 线索反馈/更新要求存在相同 `lead_id + staff_id` 的历史 `notify_sales` 任务；不要求销售仍是当前负责人，以兼容改派后的迟到反馈。
4. 每日总结只要求 `staff_id` 属于可信商户，不要求 `lead_id` 或派单历史。
5. 单线索反馈编号先匹配 `^XGF-\d+-\d+$`，再严格等于 `build_feedback_no(lead_id, staff_id)`。
6. 每日总结日期只接受 `%Y-%m-%d`；非法日期和带时间内容均返回 `failed`，不得回退当前日期。
7. 所有 `failed/skipped` 不写三张销售反馈业务表，不覆盖既有成功数据，只允许写脱敏日志。
8. API 成功解析后由路由提交；异常必须 rollback 并返回受控错误。
9. 回复检测先提交任务、检测记录和通知的 `replied` 核心状态，再独立解析；解析失败 rollback，但不得回滚已提交的核心状态。

## 允许修改范围

后端：

- Modify: `app/services/lead_wechat_notify_eligibility_service.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/routers/leads.py`
- Modify: `app/services/assign_service.py`
- Modify: `app/schemas.py`
- Modify: `app/services/sales_feedback_parser.py`
- Modify: `app/routers/sales_feedback.py`
- Modify: `app/services/wechat_task_service.py`

测试：

- Modify: `tests/test_lead_wechat_notify_eligibility_service.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_staff_merchant_crud.py`
- Modify: `tests/test_sales_feedback_parser.py`
- Modify: `tests/test_sales_feedback_api.py`

只读参考：

- Read-only: `app/models.py`
- Read-only: `app/database.py`
- Read-only: `app/services/notification_template.py`
- Read-only: `app/routers/wechat_tasks.py`
- Read-only: `tests/test_p0_5a_wechat_tasks.py`
- Read-only: `tests/test_lead_notifications.py`
- Read-only: `tests/test_forbidden_word_send_integration.py`

## 禁止事项

1. 不修改 `app/models.py`，不新增或修改迁移。
2. 不新增权限码、依赖、环境变量、配置项或 10 秒限频开关。
3. 不修改前端。
4. 不修改 `app/local_agent_main.py`、`app/local_agent_exe_entry.py`、`app/wechat_ui/input_writer.py`、`app/wechat_ui/contact_searcher.py` 或其他微信 UI 自动化底层。
5. 不修改 `apps/xg_douyin_ai_cs/*`、RAG、Milvus、LLM、抖音发送链路或底层微信发送服务。
6. 不实现 Phase 8 日报、Excel、LLM 摘要，亦不实现 Phase 9 回访。
7. 不启动 9000、9100、19000 或前端服务，不触发真实微信、抖音、LLM、Milvus 请求。
8. 不连接、迁移、删除或改写现有 `data/auto_wechat.db`。
9. 不清理、不提交、不回滚执行窗口开始前已有的用户修改。
10. 不用 Python 脚本批量改源码；人工修改使用 `apply_patch`。

## 停止门禁

执行窗口遇到以下任一情况必须停止并回传审批窗口：

1. 当前 HEAD 不包含 Phase 7 最后一个业务提交 `b3da7de`。
2. 允许文件外出现执行窗口无法归因的新修改，且会影响本阶段实现或验证。
3. 需要新增数据库表、字段、索引、配置或依赖才能完成验收。
4. 无法通过现有 `WechatTask` 和 `DouyinLead` 关联实现商户隔离限频。
5. PostgreSQL 行锁要求迫使修改数据库基础设施或引入分布式锁。
6. 销售反馈可信上下文校验必须修改鉴权中间件或 NewCarProject。
7. 测试必须连接真实数据库、启动服务或触发真实发送才能验证。
8. 发现 Phase 7 已审批的联系人验证、前台焦点、违禁词、人工接管、失败回写、幂等、紧急停止 gate 被破坏。

## 已确认调用链

```text
POST /lead-notifications/send-to-staff
  -> evaluate_lead_wechat_notify_eligibility()
  -> create_wechat_task()
  -> commit

GET /leads/{lead_id}/wechat-notify-status
  -> evaluate_lead_wechat_notify_eligibility()
  -> 只读状态，不加锁
```

```text
POST /sales-feedback/parse
  -> 商户上下文校验
  -> parse_and_persist_sales_feedback()
  -> 成功时路由 commit / 异常时 rollback
```

```text
detect_reply 回写
  -> _submit_detect_reply_result()
  -> 更新 WechatTask / ReplyCheck / LeadNotification
  -> commit 核心 replied 状态
  -> _try_parse_sales_feedback_from_reply()
  -> 独立解析事务 commit 或 rollback
```

## 实现约束

### 固定限频算法

限频窗口固定为 10 秒，不新增配置：

```python
NOTIFY_SALES_RATE_LIMIT_SECONDS = 10
ACTIVE_NOTIFY_TASK_STATUSES = {"pending", "running", "pasted", "sent"}
```

查询必须同时满足：

```text
WechatTask.task_type == "notify_sales"
WechatTask.staff_id == 当前销售
WechatTask.status in 有效状态
WechatTask.created_at >= 当前时间 - 10 秒
DouyinLead.merchant_id == 当前可信商户
WechatTask.lead_id == DouyinLead.id
```

剩余秒数使用向上取整并钳制到 `1..10`。SQLite 开发测试只能验证顺序语义；PostgreSQL 的销售行 `FOR UPDATE` 并发保护必须在部署前用两个事务做一次集成验证，本执行窗口不得连接生产数据库。

### 判断顺序

资格判断顺序必须保持：

```text
可信权限/商户 -> 线索 -> 已分配销售 -> 线索/销售状态 -> 微信昵称/联系方式
-> 同线索 already_sent -> 同线索 existing_pending
-> enable_lead_assignment -> 同商户同销售 10 秒限频 -> OK
```

这样既保留已有幂等返回，又阻止新任务。

### 反馈失败原则

`failed` 和 `skipped` 是解析结果，不是业务记录。不得为失败生成 `ERR-*` 编号，不得写入或 upsert 三张业务表。删除 `_error_feedback_no()` 及其专用 `hashlib` import；日志不得输出完整客户消息、手机号或微信号。

---

## Task 0: 阶段起点与工作区边界

**Files:**
- Read-only: Git metadata

- [ ] **Step 1: 记录起点**

Run:

```powershell
git rev-parse HEAD
git log -1 --oneline
git merge-base --is-ancestor b3da7de HEAD
```

Expected: 最后一个命令退出码为 `0`。回传报告写明第一条命令输出的完整阶段起点，不得用 `HEAD~N` 猜测起点。

- [ ] **Step 2: 记录用户残留**

Run:

```powershell
git status --short --branch
```

Expected: 只记录，不清理、不 stash、不提交。若存在修改，保存文件清单供每次提交前做精确 diff 对照。

- [ ] **Step 3: 建立任务级评审节奏**

执行顺序固定为：

```text
Task 1 红灯 -> Task 2 实现 -> Spec Reviewer -> Code Quality Reviewer -> 提交
Task 3 红灯 -> Task 4 实现 -> Spec Reviewer -> Code Quality Reviewer -> 提交
Task 5 红灯与实现 -> Spec Reviewer -> Code Quality Reviewer -> 提交
Task 6 全阶段验证 -> 最终双评审 -> 回传
```

Expected: 未得到审批窗口授权前不执行代码任务。

---

## Task 1: 派单限频与分配开关红灯测试

**Files:**
- Modify: `tests/test_lead_wechat_notify_eligibility_service.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_staff_merchant_crud.py`

- [ ] **Step 1: 为资格服务补开关和限频红灯**

在现有 fixture/helper 上最小扩展，不另建测试框架。至少覆盖：

```python
def test_eligibility_rejects_staff_with_lead_assignment_disabled():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        staff.enable_lead_assignment = False
        lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.commit()

        decision = _decision(db, lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.STAFF_LEAD_ASSIGNMENT_DISABLED
    finally:
        db.close()


def test_eligibility_rate_limits_same_merchant_and_staff():
    db = TestSession()
    try:
        staff = _seed_staff(db)
        first_lead = _seed_lead(db, assigned_staff_id=staff.id)
        second_lead = _seed_lead(db, assigned_staff_id=staff.id)
        db.add(WechatTask(
            task_type="notify_sales",
            lead_id=first_lead.id,
            staff_id=staff.id,
            status="pending",
            mode="single_send",
        ))
        db.commit()

        decision = _decision(db, second_lead.id)

        assert decision.allowed is False
        assert decision.reason == LeadWechatNotifyReason.RATE_LIMITED
        assert 1 <= decision.retry_after_seconds <= 10
    finally:
        db.close()
```

同文件用参数测试确认 `failed/blocked/cancelled` 不触发限频，并分别确认不同销售、不同商户不互相限频。另建 `created_at=datetime.now() - timedelta(seconds=11)` 的有效任务，断言窗口外允许创建；禁止使用 `sleep()` 制造时间边界。

- [ ] **Step 2: 固化幂等优先级**

补两个场景：同线索已存在 pending/running/pasted 时仍返回 `EXISTING_PENDING_TASK`；同线索已发送时仍返回 `ALREADY_SENT`，即使销售开关关闭或最近 10 秒存在任务也不能改成新原因。

- [ ] **Step 3: 为 POST 429 和只读状态补红灯**

在 `tests/test_manual_notify_sales_task.py` 复用现有商户、销售、线索和鉴权 helper：

新增 `test_send_to_staff_returns_429_with_retry_after_for_rate_limit`：用现有 helper 为同一商户和销售创建第一条有效任务，再请求第二条已分配线索，精确断言：

```python
assert response.status_code == 429
assert 1 <= int(response.headers["Retry-After"]) <= 10
assert response.json()["detail"]["code"] == "RATE_LIMITED"
```

状态接口断言 `reason/status` 与 `retry_after_seconds` 稳定透出；按当前响应结构调整字段位置，但不得只断言 429。

- [ ] **Step 4: 为手动/自动分配补红灯**

在 `tests/test_staff_merchant_crud.py` 复用已有分配测试：

新增 `test_manual_assign_rejects_staff_with_lead_assignment_disabled`：请求 `/leads/{lead.id}/assign` 指向关闭开关的销售，断言 HTTP 400 且线索未分配给该销售。

新增 `test_auto_assign_skips_staff_with_lead_assignment_disabled`：同商户同时存在一名关闭和一名开启开关的 active 销售，调用 `auto_assign_next()` 后断言 `assigned_staff_id == enabled_staff.id`。

- [ ] **Step 5: 运行红灯**

Run:

```powershell
python -m pytest tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_staff_merchant_crud.py -v
```

Expected: 新增开关、限频、429、重试秒数测试失败；Phase 7 既有幂等测试继续通过。若既有幂等测试失败，先停止说明，不进入实现。

---

## Task 2: 实现派单限频和分配开关

**Files:**
- Modify: `app/services/lead_wechat_notify_eligibility_service.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/routers/leads.py`
- Modify: `app/services/assign_service.py`
- Modify: `app/schemas.py`
- Modify: `tests/test_lead_wechat_notify_eligibility_service.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_staff_merchant_crud.py`

- [ ] **Step 1: 扩展资格决策，不复制资格逻辑**

在现有类型中增加：

```python
class LeadWechatNotifyReason:
    STAFF_LEAD_ASSIGNMENT_DISABLED = "STAFF_LEAD_ASSIGNMENT_DISABLED"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class LeadWechatNotifyDecision:
    # 保留现有字段
    retry_after_seconds: int | None = None
```

同步扩展现有 `_blocked()` 的可选参数并透传 `retry_after_seconds`；所有非限频原因保持 `None`，不得在路由重新计算。

给资格函数增加默认不加锁的参数：

```python
def evaluate_lead_wechat_notify_eligibility(
    *,
    db: Session,
    context: RequestContext,
    lead_id: int,
    staff_id: int | None = None,
    lock_staff: bool = False,
) -> LeadWechatNotifyDecision:
```

在现有销售查询上按需加锁，不新增方言分支：

```python
staff_query = db.query(SalesStaff).filter(
    SalesStaff.id == lead.assigned_staff_id,
    SalesStaff.merchant_id == context.merchant_id,
)
if lock_staff:
    staff_query = staff_query.with_for_update()
staff = staff_query.first()
```

该锁在确定销售后、后续状态/幂等/限频检查前取得。PostgreSQL 会锁销售行，SQLite 会按 SQLAlchemy 既有方言语义忽略 `FOR UPDATE`；不得在 GET 调用中传 `lock_staff=True`。

- [ ] **Step 2: 在共享资格函数实现固定限频**

沿用模型 `created_at = datetime.now` 的现有时间口径，并用 `math.ceil()` 计算剩余秒数；若驱动返回带时区的 `created_at`，计算时使用相同 `tzinfo`，不得混算 naive/aware datetime。限频查询必须 JOIN `DouyinLead` 并按 `context.merchant_id` 过滤，不得只按 `staff_id` 查询。

同时把同线索既有任务查询的幂等状态从当前 `pending/running` 补齐为 `pending/running/pasted`；该查询仍在开关和跨线索限频之前，且不得把 `failed/blocked/cancelled` 视为待执行任务。

不要新增 repository/helper 文件；这段查询只在资格服务使用一次，保留为局部私有函数即可。

- [ ] **Step 3: POST 使用锁和 429**

`lead_notification_actions.py` 的创建入口传 `lock_staff=True`。扩展现有错误转换：

```python
if decision.reason == LeadWechatNotifyReason.RATE_LIMITED:
    retry_after = str(decision.retry_after_seconds or 1)
    raise HTTPException(
        status_code=429,
        detail={"code": decision.reason, "message": decision.message},
        headers={"Retry-After": retry_after},
    )
```

不得在路由重复查询最近任务；从 decision 取结果。

- [ ] **Step 4: GET 状态透出稳定原因**

在 `LeadWechatNotifyStatus` 增加可选 `retry_after_seconds`，并由 `_to_wechat_notify_status()` 直接透传。`app/routers/leads.py` 的既有映射固定增加：

```text
STAFF_LEAD_ASSIGNMENT_DISABLED -> status="staff_assignment_disabled"，message="该销售已关闭线索分配"
RATE_LIMITED -> status="rate_limited"，message 包含 decision.retry_after_seconds
```

把 `_notify_status_and_message()` 改为接收完整 decision 与 context，避免只传 reason 后再次查询或计算秒数。

- [ ] **Step 5: 手动和自动分配复用现有字段**

`assign_lead()` 在销售存在、商户归属和 active 检查后拒绝 `enable_lead_assignment=False`；`auto_assign_next()` 的候选 SQL 增加 `SalesStaff.enable_lead_assignment.is_(True)`。不新增第二套开关 helper。

- [ ] **Step 6: 运行绿灯**

Run:

```powershell
python -m pytest tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_staff_merchant_crud.py -v
```

Expected: 全部通过。确认测试同时覆盖不同商户、不同销售、无效状态立即重试和幂等优先级。

- [ ] **Step 7: 双评审**

Spec Reviewer 必须确认：开关覆盖三条入口、限频按商户隔离、429 带 `Retry-After`、GET 不加锁、幂等优先级不变。

Code Quality Reviewer 必须确认：没有路由侧重复资格逻辑；时间计算不会返回 0 或超过 10；JOIN 条件不会把其他商户任务计入；`lock_staff` 只控制现有查询是否附加 `with_for_update()`，没有新增数据库方言分支。

- [ ] **Step 8: 提交 Task 2**

```powershell
git add app/services/lead_wechat_notify_eligibility_service.py app/routers/lead_notification_actions.py app/routers/leads.py app/services/assign_service.py app/schemas.py tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_staff_merchant_crud.py
git commit -m "修复：补齐微信派单限频和分配开关"
git rev-parse HEAD
```

Expected: 仅上述允许文件进入提交；记录输出 hash。

---

## Task 3: 销售反馈可信上下文与失败语义红灯测试

**Files:**
- Modify: `tests/test_sales_feedback_parser.py`
- Modify: `tests/test_sales_feedback_api.py`

- [ ] **Step 1: 重建 API 测试可信数据**

现有 API 测试不得继续传不存在的 `lead_id=10/staff_id=3`。复用测试数据库 fixture，创建：

```text
当前商户的 SalesStaff
当前商户的 DouyinLead
lead_id + staff_id 对应的历史 WechatTask(task_type="notify_sales")
```

另建第二商户的 lead/staff 用于越权测试。不要修改生产模型或全局数据库。

现有 `test_detect_reply_replied_persists_sales_feedback_and_updates_notification` 也必须补一条同 `lead_id + staff_id` 的历史 `WechatTask(task_type="notify_sales")`；`detect_reply` 任务本身不能冒充派单历史。

- [ ] **Step 2: 固化模板头精确匹配**

在 parser 测试中增加：

```python
@pytest.mark.parametrize("raw_text", [
    "说明文字\n【线索反馈】\n反馈编号：XGF-1-2",
    "备注：【线索更新】\n反馈编号：XGF-1-2",
    "前缀【每日线索总结】\n日期：2026-07-11",
])
def test_template_header_must_be_exact_first_line(raw_text, db):
    result = parse_and_persist_sales_feedback(db, merchant_id="m1", raw_text=raw_text)
    assert result.parse_status == "skipped"
```

按当前返回类型使用实际属性名，但语义不可弱化为包含匹配。

- [ ] **Step 3: 固化编号、日期和不落库规则**

至少新增以下测试，并按测试名表达唯一行为：

- `test_invalid_feedback_no_fails_without_business_row`
- `test_feedback_no_must_match_lead_and_staff`
- `test_invalid_daily_summary_date_fails_without_business_row`
- `test_datetime_text_is_not_accepted_as_summary_date`
- `test_failed_parse_does_not_overwrite_existing_success`
- `test_skipped_text_does_not_write_business_tables`

每个失败场景都查询 `SalesLeadFeedback`、`SalesLeadUpdate`、`SalesDailySummary`，断言计数不增加；已有成功记录场景还要断言 `raw_text/parse_status/parse_error` 未变化。

- [ ] **Step 4: 固化可信商户和派单历史**

API 测试至少新增：

- `test_parse_rejects_cross_merchant_lead`
- `test_parse_rejects_cross_merchant_staff`
- `test_parse_rejects_feedback_without_notify_sales_history`
- `test_parse_allows_original_staff_feedback_after_reassignment`
- `test_daily_summary_only_requires_merchant_owned_staff`

可信上下文或解析字段失败统一返回 HTTP `400` 和通用 `SALES_FEEDBACK_PARSE_FAILED`，不得通过 403/404 泄露另一个商户的 lead/staff 是否存在；关键门禁是“不写库”和“响应不回显跨商户对象信息”。非模板 `skipped` 继续返回 200。

- [ ] **Step 5: 运行红灯**

Run:

```powershell
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py -v
```

Expected: 第一行精确匹配、严格日期、跨商户、错误编号、无派单历史和失败不落库测试失败；Phase 7 正常模板测试继续通过。

---

## Task 4: 实现可信上下文、严格日期和失败不落库

**Files:**
- Modify: `app/services/sales_feedback_parser.py`
- Modify: `app/routers/sales_feedback.py`
- Modify: `tests/test_sales_feedback_parser.py`
- Modify: `tests/test_sales_feedback_api.py`

- [ ] **Step 1: 收紧模板识别和日期解析**

先对文本做现有清洗，再取第一行：

```python
normalized_text = (text or "").strip()
header = normalized_text.splitlines()[0].strip() if normalized_text else ""
```

只按三个精确 header 分派。每日总结日期固定：

```python
summary_date_text = fields_raw.get("日期", "").strip()
try:
    summary_date = datetime.strptime(summary_date_text, "%Y-%m-%d")
except ValueError:
    return SalesFeedbackParseResult(
        kind="daily_summary",
        parse_status="failed",
        parse_error="日期必须使用 YYYY-MM-DD 格式",
    )
```

`summary_date` 对应现有 `DateTime` 列，保持当天 `00:00:00`；不得保留 `datetime.now()` fallback，不接受 ISO 时间戳或带时间内容。若 parse result 继续保留日期字符串，`_upsert_daily_summary()` 也必须使用 `datetime.strptime(summary_date_text, "%Y-%m-%d")`，不得再次宽松解析。

- [ ] **Step 2: 失败结果不调用 upsert**

纯解析流程先完成模板、必填字段、枚举、编号格式和日期校验；线索反馈/更新在提取编号后使用标准库 `re.fullmatch(r"XGF-\d+-\d+", feedback_no)`，格式错误直接返回 `failed`。只有 `parse_status == "success"` 才进入对应 `_upsert_*`。删除 `_error_feedback_no()` 和专用 `hashlib` import。

`failed/skipped` 只返回结果并通过现有日志设施写脱敏摘要；不得新增失败业务记录表。

- [ ] **Step 3: 在共享 parser 路径校验可信上下文**

`parse_and_persist_sales_feedback()` 有 API 和回复检测两个调用方，校验必须放在该共享服务中，不能只补 API 路由。解析出模板种类后、任何 upsert 前按以下规则查询：

```text
线索反馈/更新：
  lead_id 和 staff_id 必填
  DouyinLead.id + merchant_id 存在
  SalesStaff.id + merchant_id 存在
  存在 WechatTask(task_type="notify_sales", lead_id=lead_id, staff_id=staff_id)
  feedback_no == build_feedback_no(lead_id, staff_id)

每日总结：
  staff_id 必填
  SalesStaff.id + merchant_id 存在
  不要求 lead_id 或 notify_sales 历史
```

编号格式已由纯 parser 统一检查；持久化上下文只负责把编号与可信 lead/staff 绑定。编号生成直接复用 `notification_template.build_feedback_no()`，不得复制格式化算法。任一校验失败，把 result 置为 `failed` 并在写库分支前返回；错误信息保持通用，不暴露跨商户对象。

- [ ] **Step 4: API 只提供可信 merchant 并映射失败响应**

在 `sales_feedback.py` 使用后端鉴权解析出的 `context.merchant_id`，不可采信请求中的 merchant 字段。调用共享 parser 后：

```python
if result.parse_status == "failed":
    db.rollback()
    raise HTTPException(
        status_code=400,
        detail={"code": "SALES_FEEDBACK_PARSE_FAILED", "message": "销售反馈格式或上下文无效"},
    )
```

`skipped` 继续返回 200 且不 commit；`success` 的 commit 在 Task 5 统一收口。路由不得自行重复查询 lead/staff/task。

- [ ] **Step 5: 保留改派后迟到反馈**

历史派单校验不能附加 `DouyinLead.assigned_staff_id == staff_id`。只要历史 `notify_sales` 任务证明这名销售曾收到该线索，就允许提交更新。

- [ ] **Step 6: 运行绿灯**

Run:

```powershell
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py -v
```

Expected: 全部通过；确认失败/跳过计数为零、已有成功行未被覆盖。

- [ ] **Step 7: 双评审**

Spec Reviewer 必须确认：三模板首行精确匹配、单线索上下文和派单历史完整、每日总结无额外 lead 要求、编号复用现有 helper、严格日期、失败不落库。

Code Quality Reviewer 必须确认：可信 merchant 只来自后端 context；共享 parser 同时保护 API 和回复检测；查询均带 merchant 过滤；路由未复制查询；没有完整原文日志；没有重复编号算法；没有当前日期 fallback 和失败 upsert 旁路。

- [ ] **Step 8: 提交 Task 4**

```powershell
git add app/services/sales_feedback_parser.py app/routers/sales_feedback.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py
git commit -m "修复：收紧销售反馈上下文和日期校验"
git rev-parse HEAD
```

Expected: 仅上述 4 个允许文件进入提交；记录输出 hash。

---

## Task 5: 隔离销售反馈解析事务

**Files:**
- Modify: `app/services/sales_feedback_parser.py`
- Modify: `app/routers/sales_feedback.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `tests/test_sales_feedback_api.py`

- [ ] **Step 1: 先写数据库异常红灯**

用 monkeypatch 模拟 parser 在 `flush()` 或业务写入阶段抛 `SQLAlchemyError`，不得连接真实数据库。至少新增：

- `test_sales_feedback_api_rolls_back_on_persistence_error`：调用 API 后断言受控 500 和 `SALES_FEEDBACK_PERSIST_FAILED`；用新 session 查询不到半成品。
- `test_reply_state_survives_feedback_parser_failure`：提交 `detected_status="replied"` 并模拟反馈解析异常；用新 session 断言 task 已 completed、ReplyCheck 和 LeadNotification 已 replied。
- `test_reply_parser_failure_rolls_back_session`：异常处理返回后，用同一 session 执行 `db.query(WechatTask).count()` 并断言查询成功。

不要以“函数没有抛异常”代替数据库状态断言。

- [ ] **Step 2: parser 移除隐藏 commit**

`parse_and_persist_sales_feedback()` 只负责解析、构建/upsert 和必要的 `flush()`，不调用 `db.commit()`。事务所有权交给调用方。失败/跳过仍不写库，因此不需要提交。

- [ ] **Step 3: API 显式管理事务**

`sales_feedback.py` 明确拥有事务：`success` 时 `db.commit()`；`skipped` 时 `db.rollback()` 后正常返回；`failed` 沿用 Task 4 的 400。数据库写入/提交异常固定处理为：

```python
from sqlalchemy.exc import SQLAlchemyError

try:
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id=context.merchant_id,
        raw_text=payload.raw_text,
        lead_id=payload.lead_id,
        staff_id=payload.staff_id,
    )
    if result.parse_status == "failed":
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"code": "SALES_FEEDBACK_PARSE_FAILED", "message": "销售反馈格式或上下文无效"},
        )
    if result.parse_status == "success":
        db.commit()
    else:
        db.rollback()
except HTTPException:
    raise
except SQLAlchemyError as exc:
    db.rollback()
    logger.error("sales_feedback_persist stage=failed error_type=%s", type(exc).__name__)
    raise HTTPException(
        status_code=500,
        detail={"code": "SALES_FEEDBACK_PERSIST_FAILED", "message": "销售反馈保存失败"},
    ) from None
```

日志不得使用 `logger.exception` 输出可能携带 SQL 参数的异常正文，不得带 `raw_text`；响应不得返回底层 SQL、表名、客户原文或 token。

- [ ] **Step 4: 回复检测先提交核心状态**

从 `_update_check_and_notification_on_replied()` 移除 parser 调用。`_submit_detect_reply_result()` 的 replied 分支按以下顺序执行：

```python
_update_check_and_notification_on_replied(db, task)
db.commit()
db.refresh(task)
reply_text = _extract_reply_from_raw(task.raw_result)
_try_parse_sales_feedback_from_reply(db, task, reply_text)
```

`_try_parse_sales_feedback_from_reply()`：结果为 `success` 时 commit；结果为 `failed/skipped` 时 rollback 结束解析事务；完成日志只记录 `task_id/kind/parse_status`，不记录 `parse_error/raw_text`。任何异常也必须 `db.rollback()`，并且只记录 `task_id` 与异常类型，不使用 `logger.exception` 输出 SQL 参数，不再向上抛出以破坏已提交核心状态。

不得把整个检测流程包回同一个事务，也不得为此新增 session 工厂。

- [ ] **Step 5: 运行专项绿灯**

Run:

```powershell
python -m pytest tests/test_sales_feedback_api.py tests/test_manual_notify_sales_task.py -v
```

Expected: API 异常 rollback、回复状态保留、session 可继续查询；既有 sent/replied 状态测试全部通过。

- [ ] **Step 6: 运行反馈全量绿灯**

Run:

```powershell
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_manual_notify_sales_task.py -v
```

Expected: 全部通过。

- [ ] **Step 7: 双评审**

Spec Reviewer 必须确认：parser 零 commit；API 和回复检测均有明确 commit/rollback；解析异常不回滚核心 replied 状态；failed/skipped 不写表。

Code Quality Reviewer 必须确认：没有重复 commit 导致部分提交；异常后 session 已 rollback；日志已脱敏；测试从新 session 验证真实持久化边界。

- [ ] **Step 8: 提交 Task 5**

```powershell
git add app/services/sales_feedback_parser.py app/routers/sales_feedback.py app/services/wechat_task_service.py tests/test_sales_feedback_api.py
git commit -m "修复：隔离销售反馈解析事务"
git rev-parse HEAD
```

Expected: 仅上述允许文件进入提交；记录输出 hash。

---

## Task 6: 全阶段验证、评审和固定回传

**Files:**
- Verify only: 本执行包全部允许文件

- [ ] **Step 1: 运行三组专项测试**

```powershell
python -m pytest tests/test_lead_wechat_notify_eligibility_service.py tests/test_manual_notify_sales_task.py tests/test_staff_merchant_crud.py -v
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py -v
python -m pytest tests/test_forbidden_word_send_integration.py -v
```

Expected: 全部通过。任何新增失败都必须修复或停止回传，不得标记为 pre-existing 后直接通过。

- [ ] **Step 2: 用临时 SQLite 运行旧全局 SessionLocal 回归**

`tests/test_p0_5a_wechat_tasks.py` 和 `tests/test_lead_notifications.py` 会在导入时读取 `DATABASE_URL`，必须在新的 PowerShell/Python 进程中指定临时库；不得触碰现有 `data/auto_wechat.db`。

```powershell
$tempDb = Join-Path $env:TEMP "auto_wechat_phase7_fix1_$PID.db"
$env:DATABASE_URL = "sqlite:///$($tempDb -replace '\\','/')"
$env:NEWCAR_AUTH_ENABLED = "false"
$env:NEWCAR_AUTH_MOCK_ENABLED = "true"
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_lead_notifications.py tests/test_forbidden_word_send_integration.py -v
$testExit = $LASTEXITCODE
if (Test-Path -LiteralPath $tempDb) { Remove-Item -LiteralPath $tempDb -Force }
exit $testExit
```

Expected: 测试进程结束后再删除临时文件；命令退出码为 `0`。若测试框架实际使用不同的 SQLite URL 解析规则，执行窗口只能按 `app/database.py` 现有规则调整临时路径，不得改生产配置或旧数据库。

- [ ] **Step 3: 检查阶段精确 diff**

```powershell
$subjects = @(
    "修复：补齐微信派单限频和分配开关",
    "修复：收紧销售反馈上下文和日期校验",
    "修复：隔离销售反馈解析事务"
)
$history = @(git log --format="%H%x09%s" b3da7de..HEAD)
$phaseCommits = foreach ($subject in $subjects) {
    $matches = @($history | Where-Object { ($_ -split "`t", 2)[1] -eq $subject })
    if ($matches.Count -ne 1) {
        throw "提交标题 [$subject] 命中 $($matches.Count) 次，必须根据 Task 回传 hash 人工消歧"
    }
    ($matches[0] -split "`t", 2)[0]
}
$phaseFiles = foreach ($commit in $phaseCommits) {
    git show --pretty=format: --name-only $commit
}
$phaseFiles = $phaseFiles | Where-Object { $_ } | Sort-Object -Unique
$phaseFiles
$allowedFiles = @(
    "app/services/lead_wechat_notify_eligibility_service.py",
    "app/routers/lead_notification_actions.py",
    "app/routers/leads.py",
    "app/services/assign_service.py",
    "app/schemas.py",
    "app/services/sales_feedback_parser.py",
    "app/routers/sales_feedback.py",
    "app/services/wechat_task_service.py",
    "tests/test_lead_wechat_notify_eligibility_service.py",
    "tests/test_manual_notify_sales_task.py",
    "tests/test_staff_merchant_crud.py",
    "tests/test_sales_feedback_parser.py",
    "tests/test_sales_feedback_api.py"
)
$unexpectedFiles = @($phaseFiles | Where-Object { $_ -notin $allowedFiles })
if ($unexpectedFiles) {
    throw "Phase 7-FIX1 越界文件: $($unexpectedFiles -join ', ')"
}
foreach ($commit in $phaseCommits) {
    git diff --check "${commit}^..${commit}"
    if ($LASTEXITCODE -ne 0) { throw "提交 $commit 存在空白错误" }
}
git log --oneline b3da7de..HEAD
git status --short --branch
git diff --name-only
git diff --cached --name-only
```

Expected: `$phaseFiles` 是本执行包 13 个允许文件的子集且无禁区；三个精确提交的 `git diff --check` 均无输出。起点后的其他提交和工作区残留单独列为用户修改，不合并进 FIX1 文件统计，也不得清理。

- [ ] **Step 4: 检查禁区和越界**

```powershell
$phaseFiles | rg "^(app/models.py|migrations/|frontend/|apps/xg_douyin_ai_cs/|app/local_agent|app/wechat_ui/|app/services/(ai_auto_reply_send_service|douyin_private_message_send_service)|app/services/(daily_report|return_visit|ad_review|ai_edit))"
```

Expected: 无输出。

- [ ] **Step 5: 静态检查根因残留**

```powershell
rg -n "_error_feedback_no|hashlib|datetime\.now\(\).*feedback|datetime\.now\(\).*summary|if .*【线索反馈】.* in |if .*【线索更新】.* in |if .*【每日线索总结】.* in " app/services/sales_feedback_parser.py
rg -n "db\.commit\(" app/services/sales_feedback_parser.py
rg -n "auto_wechat:[a-zA-Z0-9_:.-]+" app/services/lead_wechat_notify_eligibility_service.py app/routers/lead_notification_actions.py app/routers/leads.py app/services/assign_service.py app/services/sales_feedback_parser.py app/routers/sales_feedback.py app/services/wechat_task_service.py
```

Expected:

- 第一条无输出。
- 第二条无输出。
- 第三条只能命中阶段起点已存在且本阶段复用的权限码，不得出现新增权限码。

- [ ] **Step 6: 检查无新依赖、配置和迁移**

```powershell
$phaseFiles | rg "(^|/)(requirements.*\.txt|pyproject\.toml|package.json|package-lock.json|\.env[^/]*|docker-compose.*|migrations/)"
```

Expected: 无输出。

- [ ] **Step 7: 最终 Spec Reviewer**

逐项给出 `Approved/Rejected` 和证据：

1. `enable_lead_assignment=false` 同时阻止手动分配、自动分配、新派单任务。
2. 同线索幂等原因优先于开关和限频。
3. 限频固定 10 秒、按商户和销售隔离，只统计 4 个有效状态。
4. POST 为 429 + `Retry-After`；GET 只读且透出剩余秒数。
5. PostgreSQL 创建路径锁销售行；SQLite 限制已如实说明。
6. 三模板只按清洗后第一行精确匹配。
7. 单线索反馈验证可信商户、历史派单和稳定编号。
8. 改派后原销售迟到反馈仍允许；每日总结只要求销售商户归属。
9. 日期严格 `%Y-%m-%d`，无当前日期 fallback。
10. failed/skipped 不写业务表、不覆盖 success。
11. parser 无隐藏 commit；API 异常 rollback。
12. 回复核心状态先提交，解析异常不破坏 replied。
13. 未新增迁移、权限码、依赖、配置，未触碰禁区和 Phase 8/9。

任一项 Rejected，阶段状态必须为 `BLOCKED`，不得进入 Code Quality Reviewer。

- [ ] **Step 8: 最终 Code Quality Reviewer**

在 Spec Reviewer 全部 Approved 后检查：

1. 资格规则只集中在共享 service，路由没有复制查询。
2. 限频 JOIN 包含 `DouyinLead.merchant_id`，剩余秒数钳制正确。
3. 锁只用于 POST 创建路径，不用于 GET。
4. 分配查询直接复用现有布尔字段，无新增抽象或配置。
5. 反馈编号直接复用 `build_feedback_no()`。
6. 失败解析没有 `ERR-*` 业务记录和敏感原文日志。
7. commit/rollback 所有权清晰，异常后的 session 可继续使用。
8. 测试验证数据库最终状态，不只验证返回值。
9. 修改范围最小，无无关重构和兼容代码清理。

任一高风险问题未解决，阶段状态不得为 DONE。

- [ ] **Step 9: 固定格式回传**

```text
阶段：Phase 7-FIX1 微信派单与销售反馈完整性修复
状态：DONE / BLOCKED

阶段起点：
- <完整 commit hash>

提交：
- <hash> 修复：补齐微信派单限频和分配开关
- <hash> 修复：收紧销售反馈上下文和日期校验
- <hash> 修复：隔离销售反馈解析事务

变更文件：
- <逐项列出>

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：models.py、migrations、前端、9100、Local Agent、微信 UI 自动化、底层发送、Phase 8/9

测试命令与结果：
- <专项派单/分配>
- <专项反馈>
- <违禁词回归>
- <临时 SQLite 全局 SessionLocal 回归>
- git diff --check：<结果>

限频验证：
- 同商户同销售 10 秒：<结果>
- 不同销售 / 不同商户：<结果>
- failed / blocked / cancelled：<结果>
- 429 + Retry-After：<结果>
- PostgreSQL 行锁：代码审查通过；部署前并发集成验证待执行

反馈完整性验证：
- 商户 / 派单历史 / 编号：<结果>
- 严格日期：<结果>
- failed/skipped 不落库：<结果>
- replied 核心状态与解析事务隔离：<结果>

自审结论：
- Spec Reviewer：Approved / Rejected
- Code Quality Reviewer：Approved / Rejected

用户既有工作区残留：
- <如有，按 Task 0 清单列出，说明未清理>

剩余风险：
- SQLite 不提供 PostgreSQL 同等行锁并发语义；部署前需在非生产 PG 环境验证两个并发事务。
- <其他真实风险；没有则写无>

需要审批窗口裁定：
- 是否确认 Phase 7-FIX1 通过？
- 是否把 Phase 7 从 DONE_WITH_CONCERNS 更新为通过？
- 是否进入 Phase 8 执行包制定？
```

---

## 回滚方案

1. 三个提交保持独立；若任一任务失败，只 `git revert <对应提交>`，禁止 rebase 改写已审批历史。
2. 回滚派单限频提交后，恢复 Phase 7 原资格判断和分配行为；不涉及数据迁移。
3. 回滚反馈上下文提交后，恢复 Phase 7 原 parser/API；已成功业务记录不删除。
4. 回滚事务隔离提交后，恢复原事务边界；不得通过手工 SQL 清理生产数据。
5. 临时 SQLite 仅用于测试，Python 进程结束后删除；现有 `data/auto_wechat.db` 始终不操作。

## 本窗口审批清单

执行回传后，审批窗口按以下顺序裁定：

1. 三个提交是否都基于包含 `b3da7de` 的起点。
2. 阶段 diff 是否只包含 13 个允许文件。
3. 是否真正阻止关闭分配开关的三条入口。
4. 是否实现 10 秒商户级隔离限频、429、`Retry-After` 和幂等优先级。
5. 是否验证可信反馈上下文、历史派单、编号和严格日期。
6. 是否彻底取消 failed/skipped 业务表写入和成功记录覆盖。
7. 是否通过真实数据库状态证明事务隔离。
8. 是否使用临时 SQLite 消除旧开发库 schema 漂移干扰，且未触碰现有数据库。
9. Spec Reviewer 和 Code Quality Reviewer 是否均为 Approved。
10. 若全部通过：Phase 7-FIX1 判定“通过”，Phase 7 更新为“通过”，允许制定 Phase 8 执行包。
