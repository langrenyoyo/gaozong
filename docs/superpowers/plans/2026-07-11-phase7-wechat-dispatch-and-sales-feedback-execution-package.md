# Phase 7 微信助手真实派单与销售反馈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 放开微信助手主线 `single_send` 真实派单回写，补齐派单模板中的反馈编号和销售反馈填写模板，并把销售微信回复中的三类固定模板解析后持久化到 Phase 1 已有 SQL 表。

**Architecture:** 9000 继续只创建和回写 `WechatTask`，不直接操作微信 UI；19000 Local Agent 继续在客户本机执行联系人验证、前台焦点和发送动作。本阶段复用 Phase 1 已有 `sales_lead_feedbacks`、`sales_lead_updates`、`sales_daily_summaries` 和 `sales_staff` 5 个规则字段，不新增迁移；销售反馈解析使用固定字段和枚举，不接 LLM、不生成 Excel、不做日报发送。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 内存测试库、React + TypeScript + Vite、现有 Local Agent 任务回写协议、现有违禁词替换服务。

---

## 审批窗口结论

Phase 6 执行回传已通过本窗口审批，可进入 Phase 7。当前窗口只制定执行包，不参与编码。

## 阶段目标

1. 保持 `/lead-notifications/send-to-staff` 为微信派单主入口：创建 `WechatTask(mode="single_send")` 和 `LeadNotification(send_status="pending")`，不直接操作微信 UI。
2. 派单文本统一由 `notification_template` 生成，包含稳定反馈编号和 `【线索反馈】` 模板。
3. 派单主入口创建任务前必须走 `replace_forbidden_words(source="wechat_dispatch")`，并把替换后的文本写入 `WechatTask.message` 和 `LeadNotification.notification_text`。
4. `sent=true + verified=true` 继续按真实发送成功回写 `task.status="sent"`、`LeadNotification.send_status="sent"`、`sent_at`，并自动创建后续检测任务。
5. `manual_review_required`、`partial_match`、`verified=false`、`success=false`、紧急停止、失败回写、幂等保护继续阻断或失败，不得放宽。
6. 清理本阶段触点中的旧“sent=false / 只粘贴不发送 / 禁止自动发送”硬门禁文案，保留对 `pasted=true && sent=false` 状态组合的客观说明。
7. 新增销售反馈固定模板解析服务：`【线索反馈】`、`【线索更新】`、`【每日线索总结】`。
8. 回复检测命中销售回复后尝试解析反馈模板并写入 SQL；解析失败只记录日志或失败解析记录，不影响原有“销售已回复”状态。
9. 销售管理 API 和微信助手前端同步 Phase 1 已有 5 个规则布尔字段。
10. 不实现 Phase 8 日报 Excel、LLM 摘要、日报发送；不实现 Phase 9 回访闭环。

## 允许修改范围

后端允许文件：

- Modify: `app/services/notification_template.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/wechat_tasks.py`
- Modify: `app/schemas.py`
- Modify: `app/services/staff_service.py`
- Modify: `app/routers/staff.py`
- Create: `app/services/sales_feedback_parser.py`
- Create: `app/routers/sales_feedback.py`
- Modify: `app/main.py`
- Modify: `tests/test_p0_5a_wechat_tasks.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Create: `tests/test_sales_feedback_parser.py`
- Create: `tests/test_sales_feedback_api.py`
- Modify: `tests/test_staff_merchant_crud.py`
- Modify: `tests/test_forbidden_word_send_integration.py`

前端允许文件：

- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/staff.ts`
- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Modify: `frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx`

只读参考文件：

- Read-only: `app/models.py`
- Read-only: `app/services/notification_service.py`
- Read-only: `app/services/forbidden_word_service.py`
- Read-only: `app/services/lead_wechat_notify_eligibility_service.py`
- Read-only: `app/local_agent_main.py`
- Read-only: `app/wechat_ui/input_writer.py`
- Read-only: `app/wechat_ui/contact_searcher.py`
- Read-only: `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`

## 禁止事项

1. 不新增数据库迁移，不修改 `app/models.py` 或 `migrations/*`。
2. 不新增权限码、依赖、环境变量。
3. 不修改 `app/local_agent_main.py`、`app/local_agent_exe_entry.py`、`input_writer.py`、`contact_searcher.py`。
4. 不修改 `apps/xg_douyin_ai_cs/*`、抖音 AI 客服、RAG、Milvus、LLM 链路。
5. 不触发真实微信发送、抖音私信发送、巨量广告请求、LLM 请求或 Milvus 请求。
6. 不启动 9000 / 9100 / 19000 / 前端 dev server。
7. 不清理、不提交、不回滚执行窗口开始前已有的用户残留。
8. 不实现 Phase 8 日报 Excel、LLM 汇总、日报发送。
9. 不实现 Phase 9 回访提示词和抖音回访闭环。
10. 不把销售反馈解析做成自由文本猜测；只识别明确模板头和固定字段。

## 停止门禁

执行窗口遇到以下任一情况必须停止回传，不得自行扩大范围：

1. 发现 `SalesLeadFeedback`、`SalesLeadUpdate`、`SalesDailySummary` 或 `SalesStaff` 5 个规则字段在当前模型中不存在。
2. 完成销售反馈持久化必须新增表或新增字段。
3. 完成主线派单违禁词替换必须修改 Local Agent 或微信 UI 自动化底层。
4. 销售反馈解析需要 LLM 才能满足本阶段目标。
5. 测试必须连接真实数据库、启动服务、操作真实微信、调用抖音或调用 LLM 才能通过。
6. `app/schemas.py` 附近出现与本阶段无关的结构损坏或历史冲突，且无法只改本阶段字段。

## 当前事实

1. `SalesLeadFeedback` 已有唯一约束 `merchant_id + feedback_no`，适合按反馈编号幂等 upsert。
2. `SalesLeadUpdate` 没有唯一约束；本阶段用 `merchant_id + feedback_no + staff_id + raw_text` 做应用层去重。
3. `SalesDailySummary` 已有唯一约束 `merchant_id + staff_id + summary_date`，适合每天每销售 upsert 一条。
4. `SalesStaff` 已有 5 个布尔字段：`enable_lead_assignment`、`enable_short_video_live_lead_report`、`enable_daily_sales_feedback_report`、`enable_lead_trace_report`、`enable_sales_unit_cost_report`。
5. `/lead-notifications/send-to-staff` 当前创建 `WechatTask(mode="single_send")`，但该主入口还没有显式接入 `replace_forbidden_words(source="wechat_dispatch")`。
6. `wechat_task_service.submit_wechat_task_result()` 已有 `sent and verified` 分支，会把 task 和 notification 回写为已发送，并创建 `detect_reply`。
7. `wechat_task_service._update_check_and_notification_on_replied()` 是检测到销售回复后的联动点，可在这里尝试解析销售反馈。
8. `notification_template.compose_notification_text()` 是纯文本模板生成模块，适合加入反馈编号和填写模板。
9. 前端 `WechatAgent.tsx` 和 `WechatTaskPanel.tsx` 仍有旧 `sent=false / paste_only only` 文案。

## 调用链

```text
商户点击发送线索给销售
  -> POST /lead-notifications/send-to-staff
  -> app/routers/lead_notification_actions.py
  -> compose_notification_text(lead, feedback_no)
  -> replace_forbidden_words(source="wechat_dispatch")
  -> create_wechat_task(mode="single_send")
  -> LeadNotification(send_status="pending")
  -> 19000 Local Agent 按 task_id 执行
  -> POST /wechat-tasks/{task_id}/result
  -> wechat_task_service.submit_wechat_task_result()
  -> sent=true + verified=true 回写 sent 并创建 detect_reply
```

```text
销售在微信回复固定模板
  -> 19000 poll-and-detect 只读检测
  -> POST /wechat-tasks/{task_id}/result
  -> _submit_detect_reply_result()
  -> _update_check_and_notification_on_replied()
  -> _extract_reply_from_raw(task.raw_result)
  -> sales_feedback_parser.parse_and_persist_sales_feedback()
  -> sales_lead_feedbacks / sales_lead_updates / sales_daily_summaries
```

```text
销售配置页面
  -> WechatAgent.tsx
  -> frontend/src/api/staff.ts
  -> /staff
  -> app/routers/staff.py
  -> app/services/staff_service.py
  -> sales_staff 5 个规则字段
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `notification_template.py` | 生成微信派单文本、反馈编号、三类销售模板文本 |
| `lead_notification_actions.py` | 主线任务创建、可信商户过滤、违禁词替换、幂等复用 |
| `wechat_task_service.py` | Local Agent 结果回写、发送成功状态流转、回复检测后解析反馈 |
| `sales_feedback_parser.py` | 固定字段解析、枚举校验、幂等持久化、失败解析记录 |
| `sales_feedback.py` | 提供后台调试/人工补录用解析接口，不新增权限码 |
| `staff_service.py` / `staff.py` | 透出 5 个销售规则字段 |
| `WechatAgent.tsx` | 销售 5 个配置开关、旧门禁文案清理 |
| `WechatTaskPanel.tsx` | 测试任务面板旧门禁文案清理，不改 Local Agent 协议 |

---

## Task 0: 阶段起点与边界确认

**Files:**
- Read-only: `git status`
- Read-only: `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`

- [ ] **Step 1: 记录阶段起点**

Run:

```bash
git rev-parse HEAD
```

Expected: 输出完整 commit hash。回传报告必须写明 Phase 7 起点。

- [ ] **Step 2: 查看工作区残留但不处理**

Run:

```bash
git status --short --branch
```

Expected: 允许看到用户已有 9100、部署脚本、计划文档、测试文件等残留。不得清理、回滚或提交这些残留。

- [ ] **Step 3: 复述阶段边界**

执行窗口开始实现前，向审批窗口复述：

```text
本阶段只做 Phase 7 微信助手真实派单与销售反馈。
主线仍由 9000 创建任务、19000 本机执行；9000 不直接操作微信。
真实发送只接受 sent=true + verified=true 的安全回写；manual_review_required、partial_match、verified=false、失败和紧急停止仍阻断。
销售反馈只解析固定模板并写入 Phase 1 已有表，不新增迁移、不接 LLM、不做 Excel 日报。
本阶段不修改 Local Agent、微信 UI 自动化底层、9100、RAG、抖音发送和回访闭环。
```

Expected: 获得审批窗口继续许可后再进入 Task 1。

---

## Task 1: 微信派单红灯测试

**Files:**
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_p0_5a_wechat_tasks.py`
- Modify: `tests/test_forbidden_word_send_integration.py`

- [ ] **Step 1: 派单文本包含反馈编号和线索反馈模板**

在 `tests/test_manual_notify_sales_task.py` 中扩展 `test_assigned_lead_creates_notify_sales_task_and_notification_record`：

```python
assert "反馈编号：XGF-" in task.message
assert "【线索反馈】" in task.message
assert "微信：待添加/已发送申请/已通过/客户拒绝/无法添加/联系方式错误" in task.message
assert "意向：高意向/中意向/低意向/无意向/待判断" in task.message
assert task.message == notification.notification_text
```

当前实现预期失败：模板没有反馈编号和线索反馈字段。

- [ ] **Step 2: 主线 send-to-staff 走违禁词替换**

在 `tests/test_forbidden_word_send_integration.py` 中新增或扩展主线测试，断言 `/lead-notifications/send-to-staff` 创建的 `WechatTask.message` 和 `LeadNotification.notification_text` 都是替换后文本：

```python
def test_send_to_staff_task_message_uses_forbidden_word_replacement():
    # 复用本文件已有词库、lead、staff helper；若 helper 名称不同，按现有测试风格调整。
    # 线索 content 中放入违禁词，safe_word 配置为“安全表达”。
    response = client.post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})
    assert response.status_code == 200

    db = TestSession()
    try:
        task = db.query(WechatTask).filter_by(id=response.json()["task_id"]).one()
        notification = db.query(LeadNotification).filter_by(id=response.json()["notification_id"]).one()
        assert "违禁词原文" not in task.message
        assert "安全表达" in task.message
        assert notification.notification_text == task.message
    finally:
        db.close()
```

Expected: 当前主入口未显式替换时失败。

- [ ] **Step 3: 保留真实发送回写正向测试**

在 `tests/test_p0_5a_wechat_tasks.py` 中确认或补充：

```python
def test_submit_result_sent_true_verified_marks_task_and_notification_sent():
    response = client.post(
        f"/wechat-tasks/{task_id}/result",
        json={
            "success": True,
            "verified": True,
            "sent": True,
            "pasted": True,
            "raw_result": {"contact_verified": True, "sent": True},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
```

Expected: 已有实现应通过；若失败，说明 Phase 7 前置真实发送回写被破坏，必须先停下说明。

- [ ] **Step 4: 保留阻断门禁测试**

在同一测试文件确认以下场景仍为 blocked 或 failed：

```python
@pytest.mark.parametrize(
    "payload,expected_failure_stage",
    [
        ({"success": True, "verified": True, "partial_match": True}, "partial_match_blocked"),
        ({"success": True, "verified": True, "manual_review_required": True}, "manual_review_required_blocked"),
        ({"success": True, "verified": False}, "verified_false_blocked"),
        ({"success": False, "failure_stage": "emergency_stopped"}, "emergency_stopped"),
    ],
)
def test_submit_result_keeps_safety_blocks(payload, expected_failure_stage):
    response = client.post(f"/wechat-tasks/{task_id}/result", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"blocked", "failed"}
    assert body["failure_stage"] == expected_failure_stage
```

Expected: PASS。

- [ ] **Step 5: 旧硬门禁文案红灯检查**

Run:

```bash
rg -n "当前安全门禁保持|只粘贴消息，不会自动发送|执行模式：paste_only，仅粘贴，不发送|sent 必须为 false|仅允许 Aw3 联系人、仅 paste_only 模式、禁止自动发送" frontend/src/features/wechat-assistant app/schemas.py app/routers/wechat_tasks.py app/services/wechat_task_service.py
```

Expected: 当前会命中旧文案；Task 2/6 清理后应无输出。允许保留 `pasted=true && sent=false` 这种状态组合说明。

- [ ] **Step 6: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_manual_notify_sales_task.py tests/test_p0_5a_wechat_tasks.py tests/test_forbidden_word_send_integration.py -v
```

Expected: 模板和主线违禁词替换相关新断言失败；真实发送回写和阻断门禁测试应通过。

---

## Task 2: 派单模板、反馈编号、违禁词替换与旧注释修正

**Files:**
- Modify: `app/services/notification_template.py`
- Modify: `app/routers/lead_notification_actions.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/wechat_tasks.py`
- Modify: `app/schemas.py`
- Modify: `tests/test_manual_notify_sales_task.py`
- Modify: `tests/test_forbidden_word_send_integration.py`

- [ ] **Step 1: 增加稳定反馈编号 helper**

在 `notification_template.py` 增加：

```python
def build_feedback_no(lead_id: int | None, staff_id: int | None) -> str:
    """生成同一线索同一销售稳定复用的反馈编号。"""
    lead_part = lead_id if lead_id is not None else 0
    staff_part = staff_id if staff_id is not None else 0
    return f"XGF-{lead_part}-{staff_part}"
```

说明：本阶段最小实现只要求同一 lead/staff 重试稳定；一条线索多轮反馈编号策略如需升级，另开阶段。

- [ ] **Step 2: 增加三类模板常量**

在 `notification_template.py` 增加：

```python
LEAD_FEEDBACK_TEMPLATE = """【线索反馈】
反馈编号：{feedback_no}
微信：待添加/已发送申请/已通过/客户拒绝/无法添加/联系方式错误
开口：未开口/已开口/仅通过未回复
方式：全款/分期/全款或分期均可/未确定
车型：请填写
匹配：展厅有车/可推荐同类车/需要找车/车型未明确/不匹配
预算：请填写或填未知
精准：精准/不精准/待判断
不精准原因：无或选择原因
意向：高意向/中意向/低意向/无意向/待判断
无意向原因：无或选择原因
地区：请填写或填未知
备注：请填写"""

LEAD_UPDATE_TEMPLATE = """【线索更新】
反馈编号：{feedback_no}
到店：未预约/已预约/已到店/爽约/取消预约
到店时间：时间或无
成交：未成交/跟进中/已成交/成交失败/已流失
成交时间：时间或无
备注：请填写"""

DAILY_SUMMARY_TEMPLATE = """【每日线索总结】
日期：YYYY-MM-DD
销售：请填写
整体质量：很好/较好/一般/较差/很差
主要问题：请填写
车型情况：请填写
预算情况：请填写
客户配合度：请填写
今日建议：请填写
补充反馈：请填写"""
```

`DAILY_SUMMARY_TEMPLATE` 本阶段只作为可复用常量，不自动拼入每条派单消息，避免增加销售单条填写压力。

- [ ] **Step 3: 扩展派单文本生成函数**

把 `compose_notification_text` 改为：

```python
def compose_notification_text(lead: DouyinLead, feedback_no: str | None = None) -> str:
    """根据线索生成通知文本（纯函数，不发送、不调用微信自动化）。"""
    resolved_feedback_no = feedback_no or build_feedback_no(lead.id, lead.assigned_staff_id)
    return DEFAULT_TEMPLATE.format(
        customer_name=lead.customer_name or "未知客户",
        source=lead.source or "未知来源",
        content=lead.content or "（无内容）",
        customer_contact=lead.customer_contact or "（未提供）",
        feedback_no=resolved_feedback_no,
        lead_feedback_template=LEAD_FEEDBACK_TEMPLATE.format(feedback_no=resolved_feedback_no),
    )
```

并把 `DEFAULT_TEMPLATE` 改为包含模板：

```python
DEFAULT_TEMPLATE = """【新线索分配】
客户：{customer_name}
来源：{source}
内容：{content}
联系方式：{customer_contact}
反馈编号：{feedback_no}

请尽快联系客户，并按下方模板反馈处理结果。

{lead_feedback_template}"""
```

- [ ] **Step 4: 主线创建任务前接入违禁词替换**

在 `lead_notification_actions.py` 导入：

```python
from app.services.forbidden_word_service import replace_forbidden_words
from app.services.notification_template import build_feedback_no, compose_notification_text
```

在生成 `notification_text` 后、创建任务前加入：

```python
feedback_no = build_feedback_no(lead.id, staff.id)
notification_text = (request.message or "").strip() or compose_notification_text(lead, feedback_no=feedback_no)
replacement = replace_forbidden_words(
    db,
    merchant_id=merchant_id,
    source="wechat_dispatch",
    content=notification_text,
    context={
        "lead_id": lead.id,
        "staff_id": staff.id,
        "feedback_no": feedback_no,
        "entry": "lead_notifications.send_to_staff",
    },
)
notification_text = replacement.final_content
```

如果 `ForbiddenWordReplacement` 的字段名与上面不同，按 `app/services/forbidden_word_service.py` 的真实返回结构使用；不得改服务返回结构来迎合本阶段。

- [ ] **Step 5: 复用 existing pending 任务时补齐新模板**

在 `_compatible_decision_response()` 中，只有当历史 task 缺少通知记录时才新建通知。保留已有幂等行为；不要因为模板升级而重复创建新 task。

如果 `task.message` 已存在，继续使用历史 message：

```python
notification_text=task.message or compose_notification_text(task.lead)
```

Expected: 不破坏“已有待执行任务复用”测试。

- [ ] **Step 6: 修正旧 sent=true 拒绝注释和 schema 描述**

把 `wechat_task_service.submit_wechat_task_result()` docstring 中旧内容：

```text
sent=true → 必须拒绝（P0 安全约束）
```

改为：

```text
sent=true + verified=true → status=sent；安全门禁失败仍 blocked/failed。
```

把 `app/routers/wechat_tasks.py` result docstring 中旧 “sent=true 会被拒绝” 改为：

```text
sent=true && verified=true → status=sent
```

把 `app/schemas.py` 中 `WechatTaskResultRequest.sent` 的旧 “必须为 false” 描述改为：

```text
是否已真实发送；notify_sales 在 verified=true 且安全门禁通过时可为 true，detect_reply 必须为 false
```

- [ ] **Step 7: 跑派单专项测试**

Run:

```bash
python -m pytest tests/test_manual_notify_sales_task.py tests/test_p0_5a_wechat_tasks.py tests/test_forbidden_word_send_integration.py -v
```

Expected: PASS。若 `test_lead_notifications.py` 出现既有真实库/鉴权失败，不在本命令内处理；后续全阶段回归需要起点对照。

- [ ] **Step 8: 提交**

Commit:

```bash
git add app/services/notification_template.py app/routers/lead_notification_actions.py app/services/wechat_task_service.py app/routers/wechat_tasks.py app/schemas.py tests/test_manual_notify_sales_task.py tests/test_p0_5a_wechat_tasks.py tests/test_forbidden_word_send_integration.py
git commit -m "feat: 微信派单补齐反馈模板和安全发送口径"
```

---

## Task 3: 销售反馈解析红灯测试

**Files:**
- Create: `tests/test_sales_feedback_parser.py`

- [ ] **Step 1: 写线索反馈解析测试**

新增测试文件并写入：

```python
from app.services.sales_feedback_parser import parse_sales_feedback_text


def test_parse_lead_feedback_template():
    text = """【线索反馈】
反馈编号：XGF-10-3
微信：已通过
开口：已开口
方式：全款或分期均可
车型：奥迪A6
匹配：展厅有车
预算：20万
精准：精准
不精准原因：无
意向：高意向
无意向原因：无
地区：杭州
备注：客户下午方便电话"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_feedback"
    assert result.parse_status == "success"
    assert result.feedback_no == "XGF-10-3"
    assert result.fields["wechat_status"] == "已通过"
    assert result.fields["opening_status"] == "已开口"
    assert result.fields["payment_method"] == "全款或分期均可"
    assert result.fields["car_model"] == "奥迪A6"
    assert result.fields["match_status"] == "展厅有车"
    assert result.fields["budget_text"] == "20万"
    assert result.fields["precision_status"] == "精准"
    assert result.fields["intention_level"] == "高意向"
    assert result.fields["region_text"] == "杭州"
```

- [ ] **Step 2: 写线索更新解析测试**

```python
def test_parse_lead_update_template():
    text = """【线索更新】
反馈编号：XGF-10-3
到店：已到店
到店时间：2026-07-11 14:00
成交：已成交
成交时间：2026-07-11 16:30
备注：已交定金"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_update"
    assert result.parse_status == "success"
    assert result.feedback_no == "XGF-10-3"
    assert result.fields["visit_status"] == "已到店"
    assert result.fields["deal_status"] == "已成交"
```

- [ ] **Step 3: 写每日总结解析测试**

```python
def test_parse_daily_summary_template():
    text = """【每日线索总结】
日期：2026-07-10
销售：张三
整体质量：一般
主要问题：无效联系方式较多
车型情况：找SUV客户较多，展厅现车匹配一般
预算情况：多数客户预算在8-12万
客户配合度：一般
今日建议：优化投流车型和价格信息
补充反馈：部分客户误以为广告价格是车辆最终售价。"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "daily_summary"
    assert result.parse_status == "success"
    assert result.feedback_no is None
    assert result.fields["summary_date"] == "2026-07-10"
    assert result.fields["sales_name"] == "张三"
    assert result.fields["overall_quality"] == "一般"
    assert result.fields["main_problem"] == "无效联系方式较多"
```

- [ ] **Step 4: 写异常解析测试**

```python
def test_parse_rejects_invalid_enum_without_success_fields():
    text = """【线索反馈】
反馈编号：XGF-10-3
微信：已经加上了
开口：已开口
方式：全款
车型：奥迪A6
匹配：展厅有车
预算：20万
精准：精准
不精准原因：无
意向：高意向
无意向原因：无
地区：杭州
备注：客户下午方便电话"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_feedback"
    assert result.parse_status == "failed"
    assert "微信" in result.parse_error
    assert result.fields == {}


def test_parse_lead_feedback_missing_feedback_no_failed():
    result = parse_sales_feedback_text("【线索反馈】\n微信：已通过")

    assert result.kind == "lead_feedback"
    assert result.parse_status == "failed"
    assert result.feedback_no is None
    assert "反馈编号" in result.parse_error


def test_parse_non_template_is_skipped():
    result = parse_sales_feedback_text("收到，今天联系客户")

    assert result.kind == "none"
    assert result.parse_status == "skipped"
```

- [ ] **Step 5: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_sales_feedback_parser.py -v
```

Expected: FAIL，`app.services.sales_feedback_parser` 尚不存在。

---

## Task 4: 解析服务、持久化服务和 API

**Files:**
- Create: `app/services/sales_feedback_parser.py`
- Create: `app/routers/sales_feedback.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Create: `tests/test_sales_feedback_api.py`
- Modify: `tests/test_sales_feedback_parser.py`

- [ ] **Step 1: 定义解析结果 dataclass 和枚举**

在 `sales_feedback_parser.py` 中新增：

```python
from dataclasses import dataclass, field
from datetime import datetime
import hashlib

from sqlalchemy.orm import Session

from app.models import SalesDailySummary, SalesLeadFeedback, SalesLeadUpdate


LEAD_FEEDBACK_WECHAT = {"待添加", "已发送申请", "已通过", "客户拒绝", "无法添加", "联系方式错误"}
LEAD_FEEDBACK_OPENING = {"未开口", "已开口", "仅通过未回复"}
LEAD_FEEDBACK_PAYMENT = {"全款", "分期", "全款或分期均可", "未确定"}
LEAD_FEEDBACK_MATCH = {"展厅有车", "可推荐同类车", "需要找车", "车型未明确", "不匹配"}
LEAD_FEEDBACK_PRECISION = {"精准", "不精准", "待判断"}
LEAD_FEEDBACK_INTENTION = {"高意向", "中意向", "低意向", "无意向", "待判断"}
LEAD_UPDATE_VISIT = {"未预约", "已预约", "已到店", "爽约", "取消预约"}
LEAD_UPDATE_DEAL = {"未成交", "跟进中", "已成交", "成交失败", "已流失"}
DAILY_QUALITY = {"很好", "较好", "一般", "较差", "很差"}


@dataclass
class SalesFeedbackParseResult:
    kind: str
    parse_status: str
    feedback_no: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    parse_error: str | None = None
```

- [ ] **Step 2: 实现固定字段提取**

新增：

```python
def _extract_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("【"):
            continue
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        fields[key.strip()] = value.strip()
    return fields
```

说明：只按中文全角冒号解析一期模板；半角冒号兼容如果需要可在本函数中加一行替换，不要做自由文本猜测。

- [ ] **Step 3: 实现解析入口**

新增：

```python
def parse_sales_feedback_text(text: str) -> SalesFeedbackParseResult:
    raw = (text or "").strip()
    if "【线索反馈】" in raw:
        return _parse_lead_feedback(raw)
    if "【线索更新】" in raw:
        return _parse_lead_update(raw)
    if "【每日线索总结】" in raw:
        return _parse_daily_summary(raw)
    return SalesFeedbackParseResult(kind="none", parse_status="skipped")
```

`_parse_lead_feedback()`、`_parse_lead_update()`、`_parse_daily_summary()` 必须：

```python
def _require_enum(label: str, value: str | None, allowed: set[str]) -> str:
    if not value:
        raise ValueError(f"{label}不能为空")
    if value not in allowed:
        raise ValueError(f"{label}不在允许范围内: {value}")
    return value
```

解析失败返回 `parse_status="failed"`、`fields={}`、`parse_error=str(exc)`。

- [ ] **Step 4: 实现失败反馈编号 helper**

新增：

```python
def _error_feedback_no(raw_text: str) -> str:
    digest = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:16].upper()
    return f"ERR-{digest}"
```

说明：`SalesLeadFeedback.feedback_no` 非空且有唯一约束；缺失反馈编号的异常记录使用稳定 `ERR-<hash>`，只用于 `parse_status=failed` 排查，不作为销售模板编号。

- [ ] **Step 5: 实现持久化入口**

新增：

```python
def parse_and_persist_sales_feedback(
    db: Session,
    *,
    merchant_id: str,
    raw_text: str,
    lead_id: int | None = None,
    staff_id: int | None = None,
) -> SalesFeedbackParseResult:
    result = parse_sales_feedback_text(raw_text)
    if result.kind == "none":
        return result
    if result.kind == "lead_feedback":
        _upsert_lead_feedback(db, merchant_id=merchant_id, raw_text=raw_text, lead_id=lead_id, staff_id=staff_id, result=result)
    elif result.kind == "lead_update":
        _upsert_lead_update(db, merchant_id=merchant_id, raw_text=raw_text, lead_id=lead_id, staff_id=staff_id, result=result)
    elif result.kind == "daily_summary":
        if staff_id is None:
            result.parse_status = "failed"
            result.parse_error = "每日线索总结缺少 staff_id"
            return result
        _upsert_daily_summary(db, merchant_id=merchant_id, raw_text=raw_text, staff_id=staff_id, result=result)
    db.commit()
    return result
```

- [ ] **Step 6: 实现三类 upsert**

`SalesLeadFeedback` 按 `merchant_id + feedback_no` upsert：

```python
feedback_no = result.feedback_no or _error_feedback_no(raw_text)
row = db.query(SalesLeadFeedback).filter_by(merchant_id=merchant_id, feedback_no=feedback_no).first()
if row is None:
    row = SalesLeadFeedback(merchant_id=merchant_id, feedback_no=feedback_no)
    db.add(row)
row.lead_id = lead_id
row.staff_id = staff_id
row.raw_text = raw_text
row.parse_status = result.parse_status
row.parse_error = result.parse_error
row.feedback_date = datetime.now()
if result.parse_status == "success":
    for key, value in result.fields.items():
        setattr(row, key, value)
```

`SalesLeadUpdate` 按 `merchant_id + feedback_no + staff_id + raw_text` 查重：

```python
row = db.query(SalesLeadUpdate).filter_by(
    merchant_id=merchant_id,
    feedback_no=result.feedback_no,
    staff_id=staff_id,
    raw_text=raw_text,
).first()
if row is None:
    row = SalesLeadUpdate(merchant_id=merchant_id, feedback_no=result.feedback_no, staff_id=staff_id, raw_text=raw_text)
    db.add(row)
row.lead_id = lead_id
row.parse_status = result.parse_status
row.parse_error = result.parse_error
if result.parse_status == "success":
    for key, value in result.fields.items():
        setattr(row, key, value)
```

`SalesDailySummary` 按 `merchant_id + staff_id + summary_date` upsert；`summary_date` 用 `datetime.fromisoformat(result.fields["summary_date"])`，只保留日期当天 00:00。

- [ ] **Step 7: 新增 API schema**

在 `app/schemas.py` 增加：

```python
class SalesFeedbackParseRequest(BaseModel):
    raw_text: str = Field(..., min_length=1, max_length=5000)
    lead_id: Optional[int] = None
    staff_id: Optional[int] = None


class SalesFeedbackParseResponseData(BaseModel):
    kind: str
    parse_status: str
    feedback_no: Optional[str] = None
    fields: dict[str, str] = Field(default_factory=dict)
    parse_error: Optional[str] = None


class SalesFeedbackParseResponse(BaseModel):
    success: bool = True
    data: SalesFeedbackParseResponseData
    message: str = "success"
```

- [ ] **Step 8: 新增 router**

`app/routers/sales_feedback.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.schemas import SalesFeedbackParseRequest, SalesFeedbackParseResponse
from app.services.sales_feedback_parser import parse_and_persist_sales_feedback

router = APIRouter(prefix="/sales-feedback", tags=["销售反馈"])


@router.post("/parse", response_model=SalesFeedbackParseResponse)
def parse_sales_feedback(
    payload: SalesFeedbackParseRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    require_permission("auto_wechat:agent")(context)
    if not context.merchant_id:
        raise HTTPException(status_code=403, detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"})
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id=context.merchant_id,
        raw_text=payload.raw_text,
        lead_id=payload.lead_id,
        staff_id=payload.staff_id,
    )
    return {"success": True, "data": result.__dict__, "message": "success"}
```

在 `app/main.py` 按现有 router 注册风格挂载。

- [ ] **Step 9: 写 API 集成测试**

`tests/test_sales_feedback_api.py` 覆盖：

```python
def test_parse_api_persists_lead_feedback_with_trusted_merchant():
    response = _client().post("/sales-feedback/parse", json={"raw_text": LEAD_FEEDBACK_TEXT, "lead_id": 10, "staff_id": 3})
    assert response.status_code == 200
    assert response.json()["data"]["parse_status"] == "success"
    db = TestSession()
    try:
        row = db.query(SalesLeadFeedback).filter_by(merchant_id="merchant-a", feedback_no="XGF-10-3").one()
        assert row.lead_id == 10
        assert row.staff_id == 3
        assert row.wechat_status == "已通过"
    finally:
        db.close()
```

再覆盖每日总结 upsert 和缺权限 403。

- [ ] **Step 10: 运行测试**

Run:

```bash
python -m pytest tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py -v
```

Expected: PASS。

- [ ] **Step 11: 提交**

Commit:

```bash
git add app/services/sales_feedback_parser.py app/routers/sales_feedback.py app/schemas.py app/main.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py
git commit -m "feat: 增加销售反馈模板解析持久化"
```

---

## Task 5: 回复检测接入销售反馈解析

**Files:**
- Modify: `app/services/wechat_task_service.py`
- Modify: `tests/test_sales_feedback_api.py`

- [ ] **Step 1: 写检测联动测试**

在 `tests/test_sales_feedback_api.py` 或新增同文件集成测试中构造 `detect_reply` 任务回写：

```python
def test_detect_reply_persists_sales_feedback_without_breaking_replied_status():
    # 准备 merchant-a 的 lead、staff、reply_check、notify_sales、detect_reply task
    reply_text = LEAD_FEEDBACK_TEXT
    response = client.post(
        f"/wechat-tasks/{detect_task_id}/result",
        json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "raw_result": {"matched_reply": reply_text},
        },
    )
    assert response.status_code == 200

    db = TestSession()
    try:
        feedback = db.query(SalesLeadFeedback).filter_by(feedback_no="XGF-10-3").one()
        assert feedback.parse_status == "success"
        notification = db.query(LeadNotification).filter_by(lead_id=lead_id, staff_id=staff_id).one()
        assert notification.send_status == "replied"
    finally:
        db.close()
```

Expected: 当前实现不会持久化反馈，测试失败。

- [ ] **Step 2: 在联动点调用解析服务**

在 `wechat_task_service.py` 导入：

```python
from app.models import DouyinLead
from app.services.sales_feedback_parser import parse_and_persist_sales_feedback
```

在 `_update_check_and_notification_on_replied()` 中，提取回复后调用：

```python
reply_text = _extract_reply_from_raw(task.raw_result)
if check and check.check_status == "pending":
    check.check_status = "replied"
    check.reply_content = reply_text

_try_parse_sales_feedback_from_reply(db, task, reply_text)
```

新增 helper：

```python
def _try_parse_sales_feedback_from_reply(db: Session, task: WechatTask, reply_text: str | None) -> None:
    if not reply_text or "【" not in reply_text:
        return
    try:
        lead = db.query(DouyinLead).filter(DouyinLead.id == task.lead_id).first() if task.lead_id else None
        merchant_id = lead.merchant_id if lead and lead.merchant_id else None
        if not merchant_id:
            logger.warning("sales_feedback_parse stage=skipped reason=merchant_missing task_id=%s", task.id)
            return
        result = parse_and_persist_sales_feedback(
            db,
            merchant_id=merchant_id,
            raw_text=reply_text,
            lead_id=task.lead_id,
            staff_id=task.staff_id,
        )
        logger.info(
            "sales_feedback_parse stage=done task_id=%s kind=%s status=%s error=%s",
            task.id,
            result.kind,
            result.parse_status,
            result.parse_error,
        )
    except Exception as exc:
        logger.exception("sales_feedback_parse stage=failed task_id=%s error=%s", task.id, exc)
```

说明：解析失败不抛异常，不影响 task、ReplyCheck、LeadNotification 原有状态流转。

- [ ] **Step 3: 跑联动测试**

Run:

```bash
python -m pytest tests/test_sales_feedback_api.py tests/test_p0_5a_wechat_tasks.py -v
```

Expected: PASS。

- [ ] **Step 4: 提交**

Commit:

```bash
git add app/services/wechat_task_service.py tests/test_sales_feedback_api.py
git commit -m "feat: 销售回复检测后解析反馈模板"
```

---

## Task 6: 销售 5 个规则字段 API 与前端同步

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/services/staff_service.py`
- Modify: `app/routers/staff.py`
- Modify: `tests/test_staff_merchant_crud.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/staff.ts`
- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Modify: `frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx`

- [ ] **Step 1: 后端 staff 红灯测试**

在 `tests/test_staff_merchant_crud.py` 新增：

```python
def test_staff_crud_exposes_xiaogao_report_rule_fields():
    client = _client("merchant-a")
    response = client.post(
        "/staff",
        json={
            "name": "规则销售",
            "wechat_nickname": "Aw3",
            "enable_lead_assignment": False,
            "enable_short_video_live_lead_report": True,
            "enable_daily_sales_feedback_report": True,
            "enable_lead_trace_report": True,
            "enable_sales_unit_cost_report": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enable_lead_assignment"] is False
    assert body["enable_short_video_live_lead_report"] is True
    assert body["enable_daily_sales_feedback_report"] is True
    assert body["enable_lead_trace_report"] is True
    assert body["enable_sales_unit_cost_report"] is True

    updated = client.put(
        f"/staff/{body['id']}",
        json={"enable_lead_assignment": True, "enable_sales_unit_cost_report": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enable_lead_assignment"] is True
    assert updated.json()["enable_sales_unit_cost_report"] is False
```

Expected: 当前 schema 不接收/不返回这些字段，测试失败。

- [ ] **Step 2: 扩展 StaffCreate / StaffUpdate / StaffOut**

在 `app/schemas.py` 的 `StaffCreate` 增加：

```python
enable_lead_assignment: bool = True
enable_short_video_live_lead_report: bool = False
enable_daily_sales_feedback_report: bool = False
enable_lead_trace_report: bool = False
enable_sales_unit_cost_report: bool = False
```

在 `StaffUpdate` 增加同名 `Optional[bool] = None` 字段。

在 `StaffOut` 增加同名布尔字段，默认值与模型一致。

- [ ] **Step 3: staff_service create 支持字段**

把 `create_staff()` 增加参数：

```python
enable_lead_assignment: bool = True,
enable_short_video_live_lead_report: bool = False,
enable_daily_sales_feedback_report: bool = False,
enable_lead_trace_report: bool = False,
enable_sales_unit_cost_report: bool = False,
```

创建 `SalesStaff` 时写入对应字段。`update_staff()` 已用 `hasattr` 过滤，可继续复用。

- [ ] **Step 4: staff router 传字段**

`create_staff()` 路由调用服务时传入：

```python
enable_lead_assignment=data.enable_lead_assignment,
enable_short_video_live_lead_report=data.enable_short_video_live_lead_report,
enable_daily_sales_feedback_report=data.enable_daily_sales_feedback_report,
enable_lead_trace_report=data.enable_lead_trace_report,
enable_sales_unit_cost_report=data.enable_sales_unit_cost_report,
```

- [ ] **Step 5: 前端类型和 payload 同步**

`frontend/src/api/types.ts` 的 `Staff` 增加：

```ts
enable_lead_assignment: boolean;
enable_short_video_live_lead_report: boolean;
enable_daily_sales_feedback_report: boolean;
enable_lead_trace_report: boolean;
enable_sales_unit_cost_report: boolean;
```

`frontend/src/api/staff.ts` 的 `StaffPayload` 增加可选字段：

```ts
enable_lead_assignment?: boolean;
enable_short_video_live_lead_report?: boolean;
enable_daily_sales_feedback_report?: boolean;
enable_lead_trace_report?: boolean;
enable_sales_unit_cost_report?: boolean;
```

- [ ] **Step 6: WechatAgent 新增/编辑表单增加 5 个开关**

在 `staffForm` 和 `editStaffForm` 初始状态中增加：

```ts
enable_lead_assignment: true,
enable_short_video_live_lead_report: false,
enable_daily_sales_feedback_report: false,
enable_lead_trace_report: false,
enable_sales_unit_cost_report: false,
```

提交 payload 增加 5 个字段。

打开编辑弹窗时从 `staff` 写入：

```ts
enable_lead_assignment: staff.enable_lead_assignment ?? true,
enable_short_video_live_lead_report: staff.enable_short_video_live_lead_report ?? false,
enable_daily_sales_feedback_report: staff.enable_daily_sales_feedback_report ?? false,
enable_lead_trace_report: staff.enable_lead_trace_report ?? false,
enable_sales_unit_cost_report: staff.enable_sales_unit_cost_report ?? false,
```

UI 使用 checkbox 或 toggle，文案必须是：

```text
线索分配
短视频/直播留资管理表
每日线索销售反馈表
线索溯源表
销售单车成本表
```

不得出现旧文案：

```text
销售盈亏表
客户溯源表
总表
```

- [ ] **Step 7: 清理微信助手旧硬门禁文案**

`WechatAgent.tsx` 中把：

```text
当前安全门禁保持 sent=false
本次测试只粘贴消息，不会自动发送
执行模式：paste_only，仅粘贴，不发送
```

改为表达当前测试任务性质，不再说平台禁止发送：

```text
测试任务已由本机 Agent 执行，请查看任务结果确认 pasted / sent 状态。
执行测试会操作本机微信窗口，请确保微信已登录且窗口可见。
执行模式由任务 mode 决定；真实派单任务需通过联系人验证、前台焦点和安全门禁。
```

`WechatTaskPanel.tsx` 顶部注释和页面提示改为：

```text
测试面板用于创建本机 Agent 任务并查看回写结果；真实派单发送由任务 mode 与安全门禁共同决定。
```

保留 `paste_only` 测试任务本身，不改 Local Agent 调用协议。

- [ ] **Step 8: 静态文案检查**

Run:

```bash
rg -n "销售盈亏表|客户溯源表|总表|当前安全门禁保持|只粘贴消息，不会自动发送|执行模式：paste_only，仅粘贴，不发送|sent 必须为 false|仅允许 Aw3 联系人、仅 paste_only 模式、禁止自动发送" frontend/src/features/wechat-assistant app/schemas.py app/routers/wechat_tasks.py app/services/wechat_task_service.py
```

Expected: 无输出。若命中 `pasted=true && sent=false` 状态组合说明，不属于旧硬门禁，可在回传中说明。

- [ ] **Step 9: 跑测试和构建**

Run:

```bash
python -m pytest tests/test_staff_merchant_crud.py -v
cd frontend
npm run build
```

Expected: PASS。前端只允许既有 chunk size warning，不允许 TypeScript 错误。

- [ ] **Step 10: 提交**

Commit:

```bash
git add app/schemas.py app/services/staff_service.py app/routers/staff.py tests/test_staff_merchant_crud.py frontend/src/api/types.ts frontend/src/api/staff.ts frontend/src/features/wechat-assistant/pages/WechatAgent.tsx frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx
git commit -m "feat: 同步销售报表规则字段"
```

---

## Task 7: 全阶段验证与越界检查

**Files:**
- Read-only: all changed files

- [ ] **Step 1: 后端专项测试**

Run:

```bash
python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_manual_notify_sales_task.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_staff_merchant_crud.py -v
```

Expected: PASS。

- [ ] **Step 2: 关联回归**

Run:

```bash
python -m pytest tests/test_forbidden_word_send_integration.py tests/test_lead_notifications.py -v
```

Expected: PASS。若 `tests/test_lead_notifications.py` 出现既有真实库/鉴权失败，必须用阶段起点对照运行证明零新增回归，并列出失败测试名、失败原因、对照证据。

- [ ] **Step 3: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS。仅允许既有 chunk size warning。

- [ ] **Step 4: 空白检查**

使用 Task 0 记录的阶段起点：

```bash
git diff --check <phase7_start_commit>..HEAD -- app/services/notification_template.py app/routers/lead_notification_actions.py app/services/wechat_task_service.py app/routers/wechat_tasks.py app/schemas.py app/services/staff_service.py app/routers/staff.py app/services/sales_feedback_parser.py app/routers/sales_feedback.py app/main.py tests/test_p0_5a_wechat_tasks.py tests/test_manual_notify_sales_task.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_staff_merchant_crud.py tests/test_forbidden_word_send_integration.py frontend/src/api/types.ts frontend/src/api/staff.ts frontend/src/features/wechat-assistant/pages/WechatAgent.tsx frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx
```

Expected: 无输出。

- [ ] **Step 5: 阶段 diff 文件检查**

Run:

```bash
git diff --name-only <phase7_start_commit>..HEAD
```

Expected: 只允许出现本执行包允许文件。若用户在执行期间插入其他提交，必须改用 Phase 7 实际提交 hash 精确验证。

- [ ] **Step 6: 禁区文件检查**

Run:

```bash
git diff --name-only <phase7_start_commit>..HEAD | rg "app/models.py|migrations/|apps/xg_douyin_ai_cs|app/local_agent_main.py|app/local_agent_exe_entry.py|app/wechat_ui/input_writer.py|app/wechat_ui/contact_searcher.py|ai_auto_reply_send_service|douyin_private_message_send_service|return_visit|ad_review|ai_edit"
```

Expected: 无输出。若出现任何禁区文件，必须停止并回退本阶段越界改动。

- [ ] **Step 7: 旧硬门禁文案检查**

Run:

```bash
rg -n "sent=false|sent 必须为 false|不会自动发送|禁止自动发送|当前安全门禁保持|只建议不实发|只粘贴不实发|仅 paste_only|仅粘贴，不发送" frontend/src/features/wechat-assistant app/schemas.py app/routers/wechat_tasks.py app/services/wechat_task_service.py tests/test_p0_5a_wechat_tasks.py
```

Expected: 只允许描述 `pasted=true && sent=false -> pasted` 这种状态组合的测试或注释；不允许“平台禁止真实发送”的硬门禁语义残留。回传中需列出命中和判定。

- [ ] **Step 8: Phase 8/9 越界检查**

Run:

```bash
git diff --name-only <phase7_start_commit>..HEAD | rg "daily_report|daily_reports|excel|xlsx|llm|return_visit|ad_review|ai_edit"
```

Expected: 无输出。`DailyReportJobOut` 既有 schema 不应出现在本阶段 diff；如因 `app/schemas.py` 上下文命中，回传中说明未改日报字段。

- [ ] **Step 9: 工作区残留说明**

Run:

```bash
git status --short --branch
```

Expected: 本阶段代码文件已提交。若仍有用户残留，逐项说明“不属于 Phase 7 引入”，不得清理。

---

## Task 8: 自审与回传

**Files:**
- Read-only: all changed files

- [ ] **Step 1: Spec Reviewer 自审**

逐项确认：

```text
1. /lead-notifications/send-to-staff 仍是主线派单入口，9000 不直接操作微信。
2. 派单任务 mode 为 single_send，真实发送只由 Local Agent 执行并回写。
3. 派单文本包含稳定反馈编号和【线索反馈】模板。
4. 主线派单文本进入 WechatTask 和 LeadNotification 前已走违禁词替换。
5. sent=true + verified=true 回写 sent，manual_review_required / partial_match / verified=false / failed 仍阻断。
6. 旧“sent=false / 只粘贴不发送 / 禁止自动发送”硬门禁文案已从本阶段触点清理。
7. 【线索反馈】按反馈编号 upsert 到 sales_lead_feedbacks。
8. 【线索更新】按应用层去重写入 sales_lead_updates。
9. 【每日线索总结】按 merchant_id + staff_id + summary_date upsert 到 sales_daily_summaries。
10. 非模板回复不影响原有 replied 状态。
11. 解析失败不填充成功业务字段，且不影响 ReplyCheck / LeadNotification 原有状态流转。
12. staff API 和前端透出 5 个规则字段，文案为确认后的 5 项。
13. 未新增迁移、权限码、依赖、环境变量。
14. 未触碰 Local Agent、微信 UI 自动化底层、9100、Phase 8 日报、Phase 9 回访。
```

- [ ] **Step 2: Code Quality Reviewer 自审**

逐项确认：

```text
1. 反馈编号生成集中在 notification_template.py，不在路由里散落字符串拼接。
2. 销售反馈解析集中在 sales_feedback_parser.py，路由和 wechat_task_service 不复制解析规则。
3. 枚举校验失败返回 failed，不靠模糊文本猜测。
4. 持久化复用现有唯一约束和应用层去重，不新增表结构。
5. wechat_task_service 中解析失败只记录日志，不破坏原事务和状态流转。
6. 派单违禁词替换后，task.message 和 notification.notification_text 保持一致。
7. staff_service 只透传 5 个已有字段，没有改变销售软删除、启停、商户隔离。
8. 前端没有新增依赖、全局状态或大范围重构。
9. 测试覆盖模板、替换、发送回写、阻断门禁、解析成功、解析失败、API 持久化和 staff 字段。
```

- [ ] **Step 3: 固定回传格式**

回传审批窗口时使用：

```text
阶段：Phase 7 微信助手真实派单与销售反馈
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED

阶段起点：
- <phase7_start_commit>

提交：
- <hash> feat: 微信派单补齐反馈模板和安全发送口径
- <hash> feat: 增加销售反馈模板解析持久化
- <hash> feat: 销售回复检测后解析反馈模板
- <hash> feat: 同步销售报表规则字段

变更文件：
- app/services/notification_template.py
- app/routers/lead_notification_actions.py
- app/services/wechat_task_service.py
- app/routers/wechat_tasks.py
- app/schemas.py
- app/services/staff_service.py
- app/routers/staff.py
- app/services/sales_feedback_parser.py
- app/routers/sales_feedback.py
- app/main.py
- tests/test_p0_5a_wechat_tasks.py
- tests/test_manual_notify_sales_task.py
- tests/test_sales_feedback_parser.py
- tests/test_sales_feedback_api.py
- tests/test_staff_merchant_crud.py
- tests/test_forbidden_word_send_integration.py
- frontend/src/api/types.ts
- frontend/src/api/staff.ts
- frontend/src/features/wechat-assistant/pages/WechatAgent.tsx
- frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：app/models.py、migrations、apps/xg_douyin_ai_cs、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化、Phase 8 日报、Phase 9 回访、Phase 11 一键过审、Phase 12 AI剪辑

测试命令与结果：
- python -m pytest tests/test_p0_5a_wechat_tasks.py tests/test_manual_notify_sales_task.py tests/test_sales_feedback_parser.py tests/test_sales_feedback_api.py tests/test_staff_merchant_crud.py -v：<实际结果>
- python -m pytest tests/test_forbidden_word_send_integration.py tests/test_lead_notifications.py -v：<实际结果>
- cd frontend && npm run build：<实际结果>
- git diff --check <phase7_start_commit>..HEAD：<实际结果>
- 阶段 diff 文件检查：<实际结果>
- 禁区文件检查：<实际结果>
- 旧硬门禁文案检查：<实际结果>
- Phase 8/9 越界检查：<实际结果>

自审结论：
- Spec Reviewer：Approved / Needs Fix
- Code Quality Reviewer：Approved / Needs Fix

剩余风险：
- <如实填写；无则写“无”>

需要本窗口审批的问题：
- 是否确认 Phase 7 通过？
- 是否可以进入 Phase 8 执行包制定？
```

## 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 主线派单模板 | 集成 | `/lead-notifications/send-to-staff` | task/notification 文本包含反馈编号和【线索反馈】模板 | `tests/test_manual_notify_sales_task.py` |
| 主线违禁词替换 | 集成 | 线索内容含违禁词 | task/notification 均为替换后文本 | `tests/test_forbidden_word_send_integration.py` |
| 真实发送回写 | 状态流转 | `sent=true + verified=true` | task sent、notification sent、创建 detect_reply | `tests/test_p0_5a_wechat_tasks.py` |
| 安全阻断 | 状态流转 | partial/manual/verified false/failure | blocked 或 failed，写 failure_stage | `tests/test_p0_5a_wechat_tasks.py` |
| 线索反馈解析 | 单元 | `【线索反馈】` | 字段映射成功 | `tests/test_sales_feedback_parser.py` |
| 线索更新解析 | 单元 | `【线索更新】` | 到店/成交字段映射成功 | `tests/test_sales_feedback_parser.py` |
| 每日总结解析 | 单元 | `【每日线索总结】` | 每日整体字段映射成功 | `tests/test_sales_feedback_parser.py` |
| 解析异常 | 单元 | 非法枚举/缺反馈编号 | parse_status failed，不填成功字段 | `tests/test_sales_feedback_parser.py` |
| 解析持久化 | 集成 | `/sales-feedback/parse` | 写入对应 Phase 1 表 | `tests/test_sales_feedback_api.py` |
| 回复检测联动 | 集成 | detect_reply matched_reply 是模板 | 原 replied 状态不受影响，反馈表落库 | `tests/test_sales_feedback_api.py` |
| 销售规则字段 | API / 前端 | 创建/更新销售 5 个开关 | API 返回字段，前端构建通过 | `tests/test_staff_merchant_crud.py` + `npm run build` |
| 旧文案清理 | 静态 | 扫描微信助手触点 | 无旧硬门禁文案 | `rg` |

## 回滚方案

若需要回滚，只回滚 Phase 7 的提交，不回滚用户工作区残留，不使用 `git reset --hard`。

推荐顺序：

```bash
git revert <销售规则字段_commit_hash>
git revert <回复检测解析_commit_hash>
git revert <解析持久化_commit_hash>
git revert <派单模板_commit_hash>
```

回滚影响：

1. 派单文本恢复旧模板，主线 `single_send` 回写逻辑仍按 Phase 7 前状态存在。
2. 销售反馈模板不再解析入库，已有解析数据保留。
3. 销售 5 个规则字段仍保留在数据库模型中，但 API/前端透出回退。
4. 不影响 Phase 2 违禁词服务本身，不影响 Phase 3/4 抖音 AI 客服。

## 本窗口审批清单

审批窗口收到执行回传后只判断：

1. Phase 7 是否完成微信助手真实派单与销售反馈结构化目标。
2. 是否存在越界修改，尤其是 Local Agent、微信 UI 自动化底层、9100、迁移、日报、回访。
3. 是否存在未解释测试失败。
4. 是否保留用户残留且未清理/提交。
5. 是否允许进入 Phase 8 执行包制定。

审批结论只能是：

```text
通过
有条件通过
不通过
```
