# Phase 4-FIX1 AI实发记录一致性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Phase 4 审批发现的 AI实发记录审计一致性问题：列表、详情、有效性标记必须使用同一业务粒度，并补齐筛选、时间展示、原因校验和脱敏。

**Architecture:** 本修复不新增迁移，继续使用现有 `AiReplyDecisionLog.is_effective` / `effectiveness_reason` 字段，因此页面与接口统一为“每条 AI 决策日志展示其最新一条关联实发流水”的粒度。查询仍必须从 `DouyinPrivateMessageSend JOIN AiReplyDecisionLog` 读取，确保只有真实进入发送流水的 AI 相关记录进入页面；同一决策日志的历史多次发送不在本阶段单独展开，后续如需“每次发送单独标记有效性”必须另开带迁移的阶段。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 内存测试库、React + TypeScript + Vite、现有 NewCar 权限上下文。

---

## 阶段目标

1. 修复列表与详情粒度不一致：列表每个 `AiReplyDecisionLog.id` 只出现一行，展示该决策最新关联发送流水。
2. 详情继续按 `log_id` 打开，但必须返回与列表一致的最新发送流水，不允许点旧行看到另一条发送内容的错配。
3. 有效性标记继续写入 `AiReplyDecisionLog` 既有字段，语义明确为“标记该 AI 决策对应回复是否有效”，不伪装成每条发送流水独立标记。
4. 后端列表路由接入 `send_status` / `is_effective` 查询参数，避免前端 API 参数被静默忽略。
5. 标记原因后端强制非空，且入库、审计、返回都必须脱敏手机号和常见微信号。
6. 列表和详情主时间展示实发时间：优先 `sent_at`，其次发送流水 `created_at`，最后才回退决策日志 `created_at`。

## 允许修改范围

后端允许文件：

- Modify: `tests/test_ai_reply_decision_logs_api.py`
- Modify: `app/services/ai_reply_decision_log_query_service.py`
- Modify: `app/routers/ai_reply_decision_logs.py`
- Modify: `app/schemas.py`

前端允许文件：

- Modify: `frontend/src/api/aiReplyDecisionLogs.ts`
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`

可读但不允许修改：

- Read-only: `app/models.py`
- Read-only: `app/services/autoreply_admin_rollout_service.py`
- Read-only: `frontend/src/features/douyin-cs/api.ts`
- Read-only: `frontend/src/features/douyin-cs/types.ts`
- Read-only: `frontend/src/pages/SuperAiReplyRecords.tsx`

## 禁止事项

1. 不新增数据库迁移，不新增字段，不修改 `app/models.py`。
2. 不新增权限码、依赖、环境变量。
3. 不修改 `app/services/ai_auto_reply_send_service.py`、`app/services/douyin_private_message_send_service.py`。
4. 不修改 `apps/xg_douyin_ai_cs/*`、Local Agent、微信 UI 自动化、`input_writer`、`contact_searcher`、`local_agent_main`。
5. 不启动 9000 / 9100 / 19000 / 前端服务。
6. 不触发真实 LLM、Milvus、抖音 OpenAPI、微信、巨量广告请求。
7. 不做全站 Phase 13 旧文案清理；侧边栏旧文案本阶段不处理，除非审批窗口另行授权。
8. 不把有效性标记迁到发送流水粒度；这需要数据库字段或关联表，必须另开迁移阶段。

## 根因确认

事实：

1. `list_ai_reply_decision_logs()` 当前从 `DouyinPrivateMessageSend JOIN AiReplyDecisionLog` 返回发送流水行，`_build_list_item()` 同时返回 `id=decision.id` 与 `send_record_id=send.id`。
2. 前端行 key 使用 `item.send_record_id || item.id`，说明列表实际允许同一 `decision_log_id` 多条发送流水。
3. `get_ai_reply_decision_log_detail()` 按 `AiReplyDecisionLog.id == log_id` 查询，再按发送时间倒序取第一条。
4. 前端点击“查看”传 `item.id`，即决策日志 ID，不传 `send_record_id`。
5. PATCH 路由也按 `log_id` 更新 `AiReplyDecisionLog.is_effective` / `effectiveness_reason`。

根因：

```text
列表是发送流水粒度；
详情和有效性字段是决策日志粒度；
两种粒度混用导致同一决策日志存在多条发送流水时，列表行与详情内容可能错配。
```

本阶段选择的修复方向：

```text
不新增迁移，保持有效性字段在 AiReplyDecisionLog；
因此把列表也收敛为决策日志粒度；
每个决策日志只展示最新一条关联发送流水作为实发代表。
```

## 调用链

```text
React /admin/ai-reply-records
  -> AiReplyDecisionLogsPage.tsx
  -> frontend/src/api/aiReplyDecisionLogs.ts
  -> GET /ai-reply-decision-logs
  -> app/routers/ai_reply_decision_logs.py:list_logs
  -> app/services/ai_reply_decision_log_query_service.py:list_ai_reply_decision_logs
  -> 最新 DouyinPrivateMessageSend JOIN AiReplyDecisionLog
```

```text
查看详情 / 标记有效性
  -> GET /ai-reply-decision-logs/{log_id}
  -> PATCH /ai-reply-decision-logs/{log_id}/effectiveness
  -> 同一最新发送流水口径校验存在
  -> 更新 AiReplyDecisionLog.is_effective / effectiveness_reason
  -> record_admin_audit(...)
```

---

## Task 1: 后端红灯测试

**Files:**
- Modify: `tests/test_ai_reply_decision_logs_api.py`

- [ ] **Step 1: 添加“同一决策多条发送只展示最新一条”的失败测试**

在 `test_detail_returns_send_content_and_effectiveness_fields` 附近新增：

```python
def test_list_and_detail_use_latest_send_record_per_decision_log():
    log_id = _insert_log(
        merchant_id="merchant-a",
        conversation_id="conv-multi-send",
        reply_text="模型原始回复",
    )
    old_send_id = _insert_send_record(
        decision_log_id=log_id,
        content="旧实发内容13812345678",
        status="failed",
        sent_at=datetime(2026, 7, 10, 9, 0, 0),
        created_at=datetime(2026, 7, 10, 9, 0, 0),
    )
    latest_send_id = _insert_send_record(
        decision_log_id=log_id,
        content="最新实发内容wxid_abcd1234",
        status="sent",
        sent_at=datetime(2026, 7, 10, 10, 0, 0),
        created_at=datetime(2026, 7, 10, 10, 0, 0),
    )

    list_response = _client().get("/ai-reply-decision-logs")
    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert list_data["total"] == 1
    item = list_data["items"][0]
    assert item["id"] == log_id
    assert item["send_record_id"] == latest_send_id
    assert item["send_record_id"] != old_send_id
    assert item["send_status"] == "sent"
    assert item["sent_content_summary"] == "最新实发内容wxid***"

    detail_response = _client().get(f"/ai-reply-decision-logs/{log_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["id"] == log_id
    assert detail["send_record_id"] == latest_send_id
    assert detail["sent_content"] == "最新实发内容wxid***"
```

当前实现会失败：列表会返回同一决策日志的两条发送流水，`total == 2`。

- [ ] **Step 2: 添加 `send_status` 与 `is_effective` 路由筛选失败测试**

新增：

```python
def test_list_logs_filters_by_send_status_and_effectiveness():
    effective_log = _insert_log(merchant_id="merchant-a", conversation_id="effective")
    pending_log = _insert_log(merchant_id="merchant-a", conversation_id="pending")
    db = TestSession()
    try:
        row = db.get(AiReplyDecisionLog, effective_log)
        row.is_effective = True
        db.commit()
    finally:
        db.close()
    _insert_send_record(decision_log_id=effective_log, status="sent")
    _insert_send_record(decision_log_id=pending_log, status="failed")

    response = _client().get(
        "/ai-reply-decision-logs",
        params={"send_status": "sent", "is_effective": True},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["conversation_id"] == "effective"
    assert data["items"][0]["send_status"] == "sent"
    assert data["items"][0]["is_effective"] is True
```

当前实现会失败：路由未声明 `send_status` / `is_effective`，服务层筛选不会收到参数。

- [ ] **Step 3: 添加空白原因失败测试**

扩展 `test_patch_effectiveness_rejects_empty_payload_and_unsent_decision`，在 unsent 断言前增加：

```python
    sent_log_id = _insert_log(merchant_id="merchant-a", conversation_id="sent-log")
    _insert_send_record(decision_log_id=sent_log_id)

    blank_reason = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{sent_log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": "   "},
    )
    assert blank_reason.status_code == 400
    assert blank_reason.json()["detail"]["code"] == "EFFECTIVENESS_REASON_REQUIRED"
```

当前实现会失败：后端会把空字符串当作合法原因写入。

- [ ] **Step 4: 添加原因脱敏失败测试**

新增：

```python
def test_patch_effectiveness_masks_sensitive_reason_in_record_and_audit():
    log_id = _insert_log(merchant_id="merchant-a")
    _insert_send_record(decision_log_id=log_id)
    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )

    response = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={
            "is_effective": False,
            "effectiveness_reason": "客户手机号13812345678，微信wxid_abcd1234，回复偏离需求",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["effectiveness_reason"] == "客户手机号138****5678，微信wxid***，回复偏离需求"

    db = TestSession()
    try:
        row = db.get(AiReplyDecisionLog, log_id)
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert row.effectiveness_reason == "客户手机号138****5678，微信wxid***，回复偏离需求"
        assert audit.reason == "客户手机号138****5678，微信wxid***，回复偏离需求"
        assert "13812345678" not in audit.reason
        assert "wxid_abcd1234" not in audit.reason
        assert "13812345678" not in (audit.after_json or "")
        assert "wxid_abcd1234" not in (audit.after_json or "")
    finally:
        db.close()
```

当前实现会失败：`reason` 原样写入。

- [ ] **Step 5: 添加实发时间字段测试**

在多发送测试或新增测试中断言：

```python
    assert item["sent_at"] == "2026-07-10T10:00:00"
    assert item["send_created_at"] == "2026-07-10T10:00:00"
```

如果 JSON 序列化带秒或无时区格式不同，可按当前测试客户端实际格式调整为 `startswith("2026-07-10T10:00:00")`，但必须验证字段来自发送流水时间。

- [ ] **Step 6: 运行红灯**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected:

```text
新增测试失败，至少包含：
- 同一 decision_log_id 多发送记录 total 不是 1
- send_status / is_effective 筛选无效
- 空白 effectiveness_reason 未被拒绝
- reason 未脱敏
```

不得跳过红灯截图 / 输出摘要。

---

## Task 2: 后端查询服务收敛为决策日志粒度

**Files:**
- Modify: `app/services/ai_reply_decision_log_query_service.py`
- Modify: `app/schemas.py`

- [ ] **Step 1: schema 增加发送创建时间**

在 `AiReplyDecisionLogListItem` 增加：

```python
send_created_at: Optional[datetime] = None
```

保留现有 `created_at` 为决策日志创建时间，避免破坏旧调用方；前端展示实发时间时使用 `sent_at || send_created_at || created_at`。

- [ ] **Step 2: 导入聚合函数**

在查询服务导入中增加：

```python
from sqlalchemy import func, or_
```

如果已有 `or_`，只补 `func`。

- [ ] **Step 3: 用最新发送流水子查询替换基础查询**

将 `_sent_records_query` 改为每个 `decision_log_id` 只保留最新发送流水。为避免不同数据库对 `NULLS LAST` 聚合差异，本阶段按发送流水自增 `id` 取最新；这是与当前发送记录创建顺序一致的最小修复。

```python
def _sent_records_query(db: Session) -> Query:
    """基础联表查询：每条 AI 决策只取最新一条关联发送流水。

    有效性字段存储在 AiReplyDecisionLog 上，因此列表/详情必须与决策日志粒度一致。
    """
    latest_send_ids = (
        db.query(
            DouyinPrivateMessageSend.decision_log_id.label("decision_log_id"),
            func.max(DouyinPrivateMessageSend.id).label("send_record_id"),
        )
        .filter(DouyinPrivateMessageSend.decision_log_id.isnot(None))
        .filter(
            or_(
                DouyinPrivateMessageSend.send_source == "ai_auto",
                DouyinPrivateMessageSend.decision_log_id.isnot(None),
            )
        )
        .group_by(DouyinPrivateMessageSend.decision_log_id)
        .subquery()
    )
    return (
        db.query(DouyinPrivateMessageSend, AiReplyDecisionLog)
        .join(latest_send_ids, DouyinPrivateMessageSend.id == latest_send_ids.c.send_record_id)
        .join(
            AiReplyDecisionLog,
            DouyinPrivateMessageSend.decision_log_id == AiReplyDecisionLog.id,
        )
    )
```

注意：如果执行窗口认为必须严格按 `sent_at` 最新而不是 `id` 最新，应先在同一测试内证明现有数据存在 `id` 与 `sent_at` 逆序风险；否则保持最小实现。

- [ ] **Step 4: 列表和详情无需再用发送流水去重**

保留现有排序：

```python
DouyinPrivateMessageSend.sent_at.desc().nullslast(),
DouyinPrivateMessageSend.created_at.desc(),
DouyinPrivateMessageSend.id.desc(),
```

因为基础查询已保证每个决策日志只有一条发送流水。

- [ ] **Step 5: `_build_list_item` 返回 `send_created_at` 并脱敏 reason**

修改返回字段：

```python
"send_created_at": send.created_at,
"effectiveness_reason": _mask_sensitive_text(decision.effectiveness_reason),
```

保留：

```python
"sent_at": send.sent_at,
"created_at": decision.created_at,
```

- [ ] **Step 6: 暴露统一脱敏函数给路由复用**

在查询服务中增加公共函数：

```python
def mask_ai_reply_sensitive_text(value: str | None) -> str | None:
    """脱敏 AI 回复记录中允许展示或审计的自由文本。"""
    return _mask_sensitive_text(value)
```

不要把 `_mask_sensitive_text` 复制到路由里，避免两套规则分叉。

- [ ] **Step 7: 运行后端测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected: 多发送列表/详情测试通过；筛选和 PATCH 安全测试仍可能失败，留给 Task 3。

---

## Task 3: 后端路由接入筛选、原因校验与审计脱敏

**Files:**
- Modify: `app/routers/ai_reply_decision_logs.py`
- Modify: `tests/test_ai_reply_decision_logs_api.py`（只允许因红灯断言格式做小调整）

- [ ] **Step 1: 导入脱敏函数**

从查询服务导入增加：

```python
mask_ai_reply_sensitive_text,
```

- [ ] **Step 2: 列表路由声明 `send_status` / `is_effective`**

在 `list_logs(...)` 参数中加入：

```python
send_status: str | None = None,
is_effective: bool | None = None,
```

创建 `AiReplyDecisionLogQuery` 时传入：

```python
send_status=send_status,
is_effective=is_effective,
```

- [ ] **Step 3: PATCH 强制原因非空**

替换现有 reason 处理逻辑为：

```python
reason = (
    payload.effectiveness_reason.strip()
    if payload.effectiveness_reason is not None
    else None
)
if has_reason and not reason:
    raise HTTPException(
        status_code=400,
        detail={
            "code": "EFFECTIVENESS_REASON_REQUIRED",
            "message": "有效性原因不能为空",
        },
    )
if has_is_effective and reason is None:
    raise HTTPException(
        status_code=400,
        detail={
            "code": "EFFECTIVENESS_REASON_REQUIRED",
            "message": "标记有效性必须填写原因",
        },
    )
if reason is not None and len(reason) > 500:
    raise HTTPException(
        status_code=400,
        detail={
            "code": "EFFECTIVENESS_REASON_TOO_LONG",
            "message": "有效性原因不能超过 500 字",
        },
    )
masked_reason = mask_ai_reply_sensitive_text(reason) if reason is not None else None
```

说明：本阶段把“标记有效 / 无效”定义为必须有原因，前端本来已经这样要求；后端补齐信任边界。

- [ ] **Step 4: PATCH 入库和审计使用脱敏原因**

将写入字段改为：

```python
if has_reason:
    row.effectiveness_reason = masked_reason
```

审计调用改为：

```python
reason=masked_reason,
```

`after` 应在 `db.flush()` 后从 `row.effectiveness_reason` 读取，确保 `after_json` 也不含敏感明文。

- [ ] **Step 5: PATCH 查找已发送记录仍保持决策粒度**

保留“必须存在关联发送流水”的校验，但要确认它与 `_sent_records_query` 口径一致：`decision_log_id` 非空且能 join 到 `AiReplyDecisionLog`。本阶段不需要把 PATCH path 改成 `send_record_id`。

- [ ] **Step 6: 运行后端专项测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected:

```text
全部通过。
```

- [ ] **Step 7: 提交后端修复**

Commit:

```bash
git add app/services/ai_reply_decision_log_query_service.py app/routers/ai_reply_decision_logs.py app/schemas.py tests/test_ai_reply_decision_logs_api.py
git commit -m "fix: 修复AI实发记录审计粒度"
```

---

## Task 4: 前端展示实发时间并避免误导性行粒度

**Files:**
- Modify: `frontend/src/api/aiReplyDecisionLogs.ts`
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`

- [ ] **Step 1: 前端类型增加 `send_created_at`**

在 `AiReplyDecisionLogListItem` 中增加：

```ts
send_created_at?: string | null;
```

- [ ] **Step 2: 增加显示时间 helper**

在页面 helper 区域增加：

```ts
function displaySendTime(item: { sent_at?: string | null; send_created_at?: string | null; created_at?: string | null }) {
  return item.sent_at || item.send_created_at || item.created_at || null;
}
```

- [ ] **Step 3: 列表时间改为实发时间**

将列表第一列或时间位置从：

```tsx
{formatDateTimeLocal(item.created_at)}
```

改为：

```tsx
{formatDateTimeLocal(displaySendTime(item))}
```

如果 `formatDateTimeLocal` 不接受 `null`，则使用：

```tsx
{displaySendTime(item) ? formatDateTimeLocal(displaySendTime(item)) : "-"}
```

- [ ] **Step 4: 详情时间改为实发时间**

将详情中的：

```tsx
<div>创建时间：{formatDateTimeLocal(detail.created_at)}</div>
```

改为：

```tsx
<div>实发时间：{displaySendTime(detail) ? formatDateTimeLocal(displaySendTime(detail)) : "-"}</div>
```

可另保留一行“决策时间”，但不要只展示决策创建时间。

- [ ] **Step 5: 行 key 改回决策日志粒度**

由于后端已保证每个决策日志只有一行，行 key 使用：

```tsx
<tr key={item.id} ...>
```

不要再用 `send_record_id || id` 暗示列表是发送流水粒度。

- [ ] **Step 6: 查看按钮继续传 `item.id`**

保留：

```tsx
onClick={() => setDetailId(item.id)}
```

这与本阶段决策日志粒度一致。

- [ ] **Step 7: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected:

```text
构建成功。仅允许既有字体未解析和 chunk size 提示。
```

- [ ] **Step 8: 提交前端修复**

Commit:

```bash
git add frontend/src/api/aiReplyDecisionLogs.ts frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx
git commit -m "fix: AI实发记录展示实发时间"
```

---

## Task 5: 阶段总验证与边界检查

**Files:**
- No new files

- [ ] **Step 1: 后端专项测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected:

```text
全部通过。
```

- [ ] **Step 2: 后端关联回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_runs_api.py tests/test_admin_autoreply_rollout_api.py -v
```

Expected:

```text
全部通过。
```

若失败，必须执行对照验证证明是否为既有失败；不得把未解释失败带入审批。

- [ ] **Step 3: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected:

```text
构建成功。
```

- [ ] **Step 4: 越界文件检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD
```

Expected 只包含：

```text
app/routers/ai_reply_decision_logs.py
app/schemas.py
app/services/ai_reply_decision_log_query_service.py
frontend/src/api/aiReplyDecisionLogs.ts
frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx
tests/test_ai_reply_decision_logs_api.py
```

如果提交数量不是 2 个，以 Phase 4-FIX1 起始 commit 到 HEAD 为准检查。

- [ ] **Step 5: 禁区文件检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD | rg "input_writer|contact_searcher|local_agent_main|apps/xg_douyin_ai_cs|ai_auto_reply_send_service|douyin_private_message_send_service"
```

Expected:

```text
无输出。
```

- [ ] **Step 6: 空白与旧口径检查**

Run:

```bash
git diff --check -- app/services/ai_reply_decision_log_query_service.py app/routers/ai_reply_decision_logs.py app/schemas.py tests/test_ai_reply_decision_logs_api.py frontend/src/api/aiReplyDecisionLogs.ts frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx
```

Expected:

```text
无输出。
```

Run:

```bash
rg -n "仅记录 AI 回复建议|不会自动发送|auto_send=false|AI建议回复|垃圾回复|查看商户智能体回复质量" frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx frontend/src/pages/SuperAiReplyRecords.tsx
```

Expected:

```text
无输出。
```

- [ ] **Step 7: 工作区检查**

Run:

```bash
git status --short --branch
```

Expected:

```text
只允许既有 docs/superpowers/plans 计划文档残留；本阶段代码文件必须已提交。
```

---

## 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 同一决策多次发送 | 回归 / 集成 | 一个 `decision_log_id` 两条 send record | 列表只返回 1 行，详情展示最新 send | `test_list_and_detail_use_latest_send_record_per_decision_log` |
| 发送状态筛选 | 集成 | `send_status=sent` | 只返回最新发送状态为 sent 的记录 | `test_list_logs_filters_by_send_status_and_effectiveness` |
| 有效性筛选 | 集成 | `is_effective=true` | 只返回已标有效记录 | 同上 |
| 空白原因 | 安全 / 边界 | PATCH reason 为纯空白 | 400 `EFFECTIVENESS_REASON_REQUIRED` | `test_patch_effectiveness_rejects_empty_payload_and_unsent_decision` |
| 原因脱敏 | 安全 | PATCH reason 含手机号和微信号 | 入库、审计、响应均脱敏 | `test_patch_effectiveness_masks_sensitive_reason_in_record_and_audit` |
| 时间展示 | 前端 / 构建 | 列表和详情字段存在 `sent_at` / `send_created_at` | 页面使用实发时间而非决策时间 | `npm run build` + 代码审查 |
| 权限保持 | 权限 | 商户读、超管读、非超管 PATCH | 原 Phase 4 权限测试继续通过 | `tests/test_ai_reply_decision_logs_api.py` |

## 回滚方案

1. 回退后端 FIX1 提交：恢复 Phase 4 行为；不涉及数据库结构回滚。
2. 回退前端 FIX1 提交：页面时间展示回到 Phase 4；不影响发送链路。
3. 若上线后发现“每个决策只展示最新发送”不满足审计需求，不要在热修中补迁移；另开 Phase 4-FIX2 或后续阶段，为发送流水增加独立有效性字段或关联审核表。

## 执行窗口回传格式

```text
阶段：Phase 4-FIX1 AI实发记录一致性修复
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED

提交：
- <commit> <message>

变更文件：
- ...

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：app/models.py、app/services/ai_auto_reply_send_service.py、app/services/douyin_private_message_send_service.py、apps/xg_douyin_ai_cs、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化

测试命令与结果：
- python -m pytest tests/test_ai_reply_decision_logs_api.py -v：...
- python -m pytest tests/test_ai_auto_reply_runs_api.py tests/test_admin_autoreply_rollout_api.py -v：...
- cd frontend && npm run build：...
- git diff --check ...：...
- 禁区文件检查：...

自审结论：
- Spec Reviewer：Approved / Needs Fix
- Code Quality Reviewer：Approved / Needs Fix

剩余风险：
- ...

需要本窗口审批的问题：
- ...
```

## Spec Reviewer 清单

1. 列表是否每个 `AiReplyDecisionLog.id` 只返回一行。
2. 详情是否与列表展示同一最新发送流水。
3. 是否仍然要求存在关联发送流水，未发送决策不进入 AI实发记录。
4. `send_status` / `is_effective` 查询参数是否真正传到服务层。
5. 有效性标记是否仍仅 `auto_wechat:admin:ai_reply_records` 可写。
6. 空白原因是否由后端拒绝。
7. 原因中的手机号、微信号是否在入库、审计、响应中脱敏。
8. 前端是否展示实发时间，而不是只展示决策创建时间。
9. 是否没有新增迁移、权限码、依赖、环境变量。
10. 是否没有触碰发送链路、9100、Local Agent 或微信自动化。

## Code Quality Reviewer 清单

1. 聚合查询是否避免 Python 侧分页后去重；`count()` 必须与列表行数一致。
2. 最新发送流水选择逻辑是否清晰，并有多发送测试覆盖。
3. 脱敏函数是否复用同一规则，避免查询服务和路由各写一套。
4. PATCH 是否在一个事务中更新字段并写审计。
5. 返回结构是否不暴露 `request_body_json`、`response_body_json`、`raw_response_json`。
6. 前端是否没有引入新全局状态或新依赖。
7. 前端构建是否通过。

## 本窗口审批清单

审批窗口收到执行回传后只判断：

1. Phase 4 阻塞项“发送流水粒度 vs 决策日志粒度错配”是否已消除。
2. Phase 4-FIX1 是否只修改允许文件。
3. 是否存在未解释测试失败。
4. 是否存在业务代码未提交。
5. 是否可以把 Phase 4 从“不通过”更新为“通过”，并进入 Phase 5 执行包制定。

审批结论只能是：

```text
通过
有条件通过
不通过
```
