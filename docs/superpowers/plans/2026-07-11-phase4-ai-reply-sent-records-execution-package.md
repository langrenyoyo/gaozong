# Phase 4 AI回复记录改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将超管 AI回复记录从“AI 回复建议/决策日志”改为“AI 实发记录”，展示 `DouyinPrivateMessageSend.content` 中违禁词替换后的最终实发内容，并支持超管标记有效性。

**Architecture:** 9000 继续作为唯一可信查询与审核入口；查询服务从 `douyin_private_message_sends` 联表 `ai_reply_decision_logs` 读取实发记录，前端只调用 9000 `/ai-reply-decision-logs`。本阶段不改 9100 决策、不改发送链路、不新增迁移，只复用 Phase 1 已落库的 `is_effective`、`effectiveness_reason`、`model` 字段和现有 `autoreply_admin_audit_logs` 审计表。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 内存测试库、React + TypeScript + Vite、现有 NewCar 权限上下文。

---

## 阶段边界

### 本阶段目标

1. AI回复记录列表只展示已经进入发送流水的 AI 相关记录。
2. AI 实发内容以 `DouyinPrivateMessageSend.content` 为准，不再以 `AiReplyDecisionLog.reply_text` 冒充实发。
3. 普通人工发送不进入 AI回复记录：`send_source="manual"` 且 `decision_log_id is None` 必须被过滤。
4. 保留商户隔离：商户侧只能看自己的记录；超管可看全部并按 `merchant_id` 筛选。
5. 新增有效性标记接口：仅超管权限可写，写入审计日志。
6. 超管入口 `/admin/ai-reply-records` 必须使用真实 API 数据，不再保留本地假数据。

### 本阶段允许修改范围

后端允许文件：

- Modify: `tests/test_ai_reply_decision_logs_api.py`
- Modify: `app/services/ai_reply_decision_log_query_service.py`
- Modify: `app/routers/ai_reply_decision_logs.py`
- Modify: `app/schemas.py`

前端允许文件：

- Modify: `frontend/src/api/aiReplyDecisionLogs.ts`
- Modify: `frontend/src/features/douyin-cs/api.ts`
- Modify: `frontend/src/features/douyin-cs/types.ts`
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`
- Modify: `frontend/src/pages/SuperAiReplyRecords.tsx`

只读参考文件：

- Read-only: `app/models.py`
- Read-only: `app/services/autoreply_admin_rollout_service.py`
- Read-only: `tests/test_ai_auto_reply_runs_api.py`
- Read-only: `frontend/src/pages/Index.tsx`
- Read-only: `frontend/src/App.tsx`

### 本阶段禁止事项

1. 不新增数据库迁移。
2. 不新增权限码。
3. 不新增依赖或环境变量。
4. 不修改 `app/services/ai_auto_reply_send_service.py`。
5. 不修改 `app/services/douyin_private_message_send_service.py`。
6. 不修改 `apps/xg_douyin_ai_cs/*`。
7. 不触碰微信 UI 自动化、Local Agent、`input_writer`、`contact_searcher`。
8. 不启动 9000 / 9100 / 19000 / 前端服务。
9. 不触发真实 LLM、Milvus、抖音 OpenAPI、微信或巨量广告请求。
10. 不做 Phase 13 全站旧文案清理；只清理本页和实际入口中的旧口径。

### 停止门禁

执行窗口遇到以下任一情况必须停止回传，不得自行扩大范围：

1. 发现 `ai_reply_decision_logs` 缺少 `is_effective`、`effectiveness_reason`、`model` 字段。
2. 发现 `douyin_private_message_sends` 缺少 `decision_log_id`、`send_source`、`content`、`status` 字段。
3. 有效性标记需要新增权限码才能完成。
4. 前端真实入口不是 `/admin/ai-reply-records`，且需要改全局路由体系才能接入。
5. 测试必须连接真实数据库或启动服务才能通过。

---

## 当前事实

1. `app/routers/ai_reply_decision_logs.py` 当前 prefix 为 `/ai-reply-decision-logs`，只校验 `auto_wechat:douyin_ai_cs`，且忽略 query 中的 `merchant_id`。
2. `app/services/ai_reply_decision_log_query_service.py` 当前直接查询 `AiReplyDecisionLog`，会展示未发送的建议记录。
3. `DouyinPrivateMessageSend.content` 是发送流水里的最终内容；Phase 2 已将违禁词替换接入发送链路。
4. `AiReplyDecisionLog` 已有 `is_effective`、`effectiveness_reason`、`model` 字段，不需要迁移。
5. `app/schemas.py` 已有 `AiReplyDecisionEffectivenessPatch`，但路由还没有 PATCH 接口。
6. `record_admin_audit(...)` 已存在于 `app/services/autoreply_admin_rollout_service.py`，可复用写 `autoreply_admin_audit_logs`。
7. 前端 `/admin/ai-reply-records` 当前实际渲染 `frontend/src/pages/SuperAiReplyRecords.tsx`，该文件包含 `initialRecords` 假数据。
8. `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx` 已接真实 API，但仍有“仅记录 AI 回复建议”“不会自动发送”“auto_send=false”等旧文案。

---

## 调用链

### 读取链路

```text
/admin/ai-reply-records
  -> Index.tsx superActiveNav = "ai-reply-records"
  -> SuperAiReplyRecords.tsx
  -> AiReplyDecisionLogsPage.tsx
  -> frontend/src/api/aiReplyDecisionLogs.ts
  -> GET /ai-reply-decision-logs
  -> app/routers/ai_reply_decision_logs.py
  -> app/services/ai_reply_decision_log_query_service.py
  -> DouyinPrivateMessageSend JOIN AiReplyDecisionLog
```

### 有效性标记链路

```text
AiReplyDecisionLogsPage 标记有效 / 无效
  -> PATCH /ai-reply-decision-logs/{decision_log_id}/effectiveness
  -> 校验 auto_wechat:admin:ai_reply_records
  -> 更新 AiReplyDecisionLog.is_effective / effectiveness_reason
  -> record_admin_audit(action="mark_ai_reply_effectiveness")
  -> 返回更新后的详情
```

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `tests/test_ai_reply_decision_logs_api.py` | 先用失败测试锁定 AI 实发记录查询、商户隔离、超管筛选、有效性标记和审计 |
| `app/services/ai_reply_decision_log_query_service.py` | 查询服务联表发送流水和决策日志，统一脱敏、分页、筛选、详情 |
| `app/routers/ai_reply_decision_logs.py` | 处理读权限范围、PATCH 写权限、HTTP 错误码和响应模型 |
| `app/schemas.py` | 扩展列表/详情响应字段，复用有效性 Patch 请求结构 |
| `frontend/src/api/aiReplyDecisionLogs.ts` | 扩展类型和新增 PATCH API 函数 |
| `frontend/src/features/douyin-cs/api.ts` | 导出 PATCH API 函数 |
| `frontend/src/features/douyin-cs/types.ts` | 导出新增前端类型 |
| `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx` | 展示 AI 实发记录、发送状态、模型、有效性标记；清理本页旧口径 |
| `frontend/src/pages/SuperAiReplyRecords.tsx` | 改为复用真实页面，移除本地假数据 |

---

## Task 1: 后端红灯测试

**Files:**
- Modify: `tests/test_ai_reply_decision_logs_api.py`

- [ ] **Step 1: 引入发送流水模型和审计模型**

在测试文件顶部调整 import：

```python
from app.models import (
    AiReplyDecisionLog,
    AutoReplyAdminAuditLog,
    DouyinPrivateMessageSend,
)
```

- [ ] **Step 2: 扩展测试上下文 helper**

把 `_context` 扩展为支持超管和管理员权限：

```python
def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
):
    return RequestContext(
        user_id="user-1",
        username="admin-user",
        display_name="审核员",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:douyin_ai_cs"],
        super_admin=super_admin,
    )
```

- [ ] **Step 3: 增加发送流水 helper**

在 `_insert_log` 后添加：

```python
def _insert_send_record(
    *,
    decision_log_id: int | None,
    send_source: str = "ai_auto",
    merchant_account_open_id: str = "account-1",
    conversation_short_id: str = "conv-1",
    customer_open_id: str = "customer-1",
    content: str = "违禁词替换后的最终实发内容 13812345678",
    status: str = "sent",
    auto_send: int = 1,
    manual_confirmed: int = 0,
    auto_reply_run_id: int | None = None,
    sent_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        row = DouyinPrivateMessageSend(
            main_account_id=123,
            conversation_short_id=conversation_short_id,
            server_message_id=f"server-send-{datetime.now().timestamp()}",
            from_user_id=merchant_account_open_id,
            to_user_id=customer_open_id,
            customer_open_id=customer_open_id,
            account_open_id=merchant_account_open_id,
            content=content,
            status=status,
            upstream_msg_id="upstream-1" if status == "sent" else None,
            manual_confirmed=manual_confirmed,
            auto_send=auto_send,
            send_source=send_source,
            auto_reply_run_id=auto_reply_run_id,
            decision_log_id=decision_log_id,
            sent_at=sent_at or datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()
```

- [ ] **Step 4: 写“只返回 AI 实发记录”的失败测试**

新增测试：

```python
def test_list_logs_returns_only_ai_sent_records_and_uses_send_content():
    sent_log_id = _insert_log(
        merchant_id="merchant-a",
        conversation_id="conv-sent",
        reply_text="旧建议回复，不应作为实发内容",
        final_auto_send=1,
    )
    _insert_send_record(
        decision_log_id=sent_log_id,
        content="最终实发内容，手机号13812345678已脱敏展示",
        status="sent",
        send_source="ai_auto",
    )
    _insert_log(merchant_id="merchant-a", conversation_id="conv-decision-only")
    _insert_send_record(
        decision_log_id=None,
        content="普通人工发送不应进入 AI 回复记录",
        send_source="manual",
        auto_send=0,
        manual_confirmed=1,
    )

    response = _client().get("/ai-reply-decision-logs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["id"] == sent_log_id
    assert item["send_record_id"] is not None
    assert item["conversation_id"] == "conv-sent"
    assert item["send_status"] == "sent"
    assert item["send_source"] == "ai_auto"
    assert item["sent_content_summary"] == "最终实发内容，手机号138****5678已脱敏展示"
    assert item["reply_text_summary"] != item["sent_content_summary"]
```

- [ ] **Step 5: 写超管筛选和商户隔离失败测试**

新增测试：

```python
def test_admin_can_filter_by_merchant_but_merchant_user_cannot_forge_scope():
    log_a = _insert_log(merchant_id="merchant-a", conversation_id="conv-a")
    _insert_send_record(decision_log_id=log_a, content="商户A实发")
    log_b = _insert_log(merchant_id="merchant-b", conversation_id="conv-b")
    _insert_send_record(decision_log_id=log_b, content="商户B实发")

    merchant_response = _client().get(
        "/ai-reply-decision-logs",
        params={"merchant_id": "merchant-b"},
    )
    assert merchant_response.status_code == 200
    merchant_data = merchant_response.json()["data"]
    assert merchant_data["total"] == 1
    assert merchant_data["items"][0]["merchant_id"] == "merchant-a"

    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )
    admin_response = _client(admin_context).get(
        "/ai-reply-decision-logs",
        params={"merchant_id": "merchant-b"},
    )
    assert admin_response.status_code == 200
    admin_data = admin_response.json()["data"]
    assert admin_data["total"] == 1
    assert admin_data["items"][0]["merchant_id"] == "merchant-b"
```

- [ ] **Step 6: 写详情读取失败测试**

新增测试：

```python
def test_detail_returns_send_content_and_effectiveness_fields():
    log_id = _insert_log(
        merchant_id="merchant-a",
        latest_message="客户手机号13812345678，问A6",
        reply_text="模型原始建议回复",
    )
    send_id = _insert_send_record(
        decision_log_id=log_id,
        content="最终实发内容13812345678",
        status="sent",
    )

    response = _client().get(f"/ai-reply-decision-logs/{log_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == log_id
    assert data["send_record_id"] == send_id
    assert data["sent_content"] == "最终实发内容138****5678"
    assert data["reply_text"] == "模型原始建议回复"
    assert data["is_effective"] is None
    assert data["effectiveness_reason"] is None
    assert "request_body_json" not in data
    assert "response_body_json" not in data
```

- [ ] **Step 7: 写有效性标记失败测试**

新增测试：

```python
def test_patch_effectiveness_requires_admin_and_writes_audit_log():
    log_id = _insert_log(merchant_id="merchant-a")
    _insert_send_record(decision_log_id=log_id)

    denied = _client().patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": "回复促成留资"},
    )
    assert denied.status_code == 403

    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )
    response = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": True, "effectiveness_reason": " 回复促成留资 "},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_effective"] is True
    assert data["effectiveness_reason"] == "回复促成留资"

    db = TestSession()
    try:
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert audit.action == "mark_ai_reply_effectiveness"
        assert audit.target_type == "ai_reply_decision_log"
        assert audit.target_id == str(log_id)
        assert audit.reason == "回复促成留资"
        assert "13812345678" not in (audit.after_json or "")
    finally:
        db.close()
```

- [ ] **Step 8: 写非法 patch 失败测试**

新增测试：

```python
def test_patch_effectiveness_rejects_empty_payload_and_unsent_decision():
    log_id = _insert_log(merchant_id="merchant-a")
    admin_context = _context(
        merchant_id=None,
        permission_codes=["auto_wechat:admin:ai_reply_records"],
        super_admin=True,
    )

    empty_payload = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={},
    )
    assert empty_payload.status_code == 400
    assert empty_payload.json()["detail"]["code"] == "NO_FIELDS_TO_UPDATE"

    unsent = _client(admin_context).patch(
        f"/ai-reply-decision-logs/{log_id}/effectiveness",
        json={"is_effective": False, "effectiveness_reason": "未发送不能标记"},
    )
    assert unsent.status_code == 404
    assert unsent.json()["detail"]["code"] == "AI_REPLY_DECISION_LOG_NOT_FOUND"
```

- [ ] **Step 9: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected: 新增测试失败，失败原因应指向当前查询源仍是 `AiReplyDecisionLog`、缺少发送字段、缺少 PATCH 路由。

---

## Task 2: 后端查询服务最小实现

**Files:**
- Modify: `app/services/ai_reply_decision_log_query_service.py`
- Modify: `app/schemas.py`

- [ ] **Step 1: 扩展 schema 字段**

在 `AiReplyDecisionLogListItem` 增加字段：

```python
send_record_id: Optional[int] = None
sent_content_summary: Optional[str] = None
send_status: Optional[str] = None
send_source: Optional[str] = None
auto_send: bool = False
manual_confirmed: bool = False
upstream_msg_id: Optional[str] = None
sent_at: Optional[datetime] = None
model: Optional[str] = None
is_effective: Optional[bool] = None
effectiveness_reason: Optional[str] = None
```

在 `AiReplyDecisionLogDetail` 增加字段：

```python
sent_content: Optional[str] = None
```

- [ ] **Step 2: 修改 query dataclass**

把 `merchant_id` 改为可空，并增加发送状态和有效性筛选：

```python
@dataclass
class AiReplyDecisionLogQuery:
    merchant_id: str | None = None
    page: int = 1
    page_size: int = 20
    account_open_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    manual_required: bool | None = None
    intent: str | None = None
    lead_level: str | None = None
    risk_flag: str | None = None
    rag_used: bool | None = None
    llm_used: bool | None = None
    send_status: str | None = None
    is_effective: bool | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    keyword: str | None = None
```

- [ ] **Step 3: 联表查询发送流水**

导入发送模型：

```python
from app.models import AiReplyDecisionLog, DouyinPrivateMessageSend
```

新增基础查询函数：

```python
def _sent_records_query(db: Session) -> Query:
    return (
        db.query(DouyinPrivateMessageSend, AiReplyDecisionLog)
        .join(AiReplyDecisionLog, DouyinPrivateMessageSend.decision_log_id == AiReplyDecisionLog.id)
        .filter(
            or_(
                DouyinPrivateMessageSend.send_source == "ai_auto",
                DouyinPrivateMessageSend.decision_log_id.isnot(None),
            )
        )
    )
```

说明：普通人工发送 `send_source="manual"` 且 `decision_log_id is None` 会被过滤；如果人工确认发送的是 AI 决策内容且写入 `decision_log_id`，仍作为 AI 回复记录展示。

- [ ] **Step 4: 更新列表查询**

将列表查询改为：

```python
def list_ai_reply_decision_logs(db: Session, query: AiReplyDecisionLogQuery) -> dict[str, Any]:
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), PAGE_SIZE_LIMIT)
    base_query = _apply_filters(_sent_records_query(db), query)

    total = base_query.count()
    rows = (
        base_query.order_by(
            DouyinPrivateMessageSend.sent_at.desc().nullslast(),
            DouyinPrivateMessageSend.created_at.desc(),
            DouyinPrivateMessageSend.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_build_list_item(send, decision) for send, decision in rows],
    }
```

- [ ] **Step 5: 更新详情查询**

详情必须按 `AiReplyDecisionLog.id` 查，但也必须存在关联发送流水：

```python
row = (
    _apply_filters(_sent_records_query(db), AiReplyDecisionLogQuery(merchant_id=merchant_id))
    .filter(AiReplyDecisionLog.id == log_id)
    .order_by(
        DouyinPrivateMessageSend.sent_at.desc().nullslast(),
        DouyinPrivateMessageSend.created_at.desc(),
        DouyinPrivateMessageSend.id.desc(),
    )
    .first()
)
if row is None:
    return None
send, decision = row
data = _build_list_item(send, decision)
```

如果 `merchant_id is None`，代表超管查询全部商户；普通商户调用时必须传可信商户 ID。

- [ ] **Step 6: 更新筛选逻辑**

`_apply_filters` 要改为对联表字段筛选：

```python
def _apply_filters(query: Query, params: AiReplyDecisionLogQuery) -> Query:
    if params.merchant_id:
        query = query.filter(AiReplyDecisionLog.merchant_id == params.merchant_id)
    if params.account_open_id:
        query = query.filter(AiReplyDecisionLog.account_open_id == params.account_open_id)
    if params.conversation_id:
        query = query.filter(AiReplyDecisionLog.conversation_id == params.conversation_id)
    if params.agent_id:
        query = query.filter(AiReplyDecisionLog.agent_id == params.agent_id)
    if params.manual_required is not None:
        query = query.filter(AiReplyDecisionLog.manual_required == _bool_to_int(params.manual_required))
    if params.intent:
        query = query.filter(AiReplyDecisionLog.intent == params.intent)
    if params.lead_level:
        query = query.filter(AiReplyDecisionLog.lead_level == params.lead_level)
    if params.risk_flag:
        escaped = params.risk_flag.replace("%", r"\%").replace("_", r"\_")
        query = query.filter(AiReplyDecisionLog.risk_flags_json.like(f'%"{escaped}"%', escape="\\"))
    if params.rag_used is not None:
        query = query.filter(AiReplyDecisionLog.rag_used == _bool_to_int(params.rag_used))
    if params.llm_used is not None:
        query = query.filter(AiReplyDecisionLog.llm_used == _bool_to_int(params.llm_used))
    if params.send_status:
        query = query.filter(DouyinPrivateMessageSend.status == params.send_status)
    if params.is_effective is not None:
        query = query.filter(AiReplyDecisionLog.is_effective.is_(params.is_effective))
    if params.date_from is not None:
        query = query.filter(DouyinPrivateMessageSend.created_at >= params.date_from)
    if params.date_to is not None:
        query = query.filter(DouyinPrivateMessageSend.created_at <= params.date_to)
    if params.keyword:
        keyword = params.keyword.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                AiReplyDecisionLog.latest_message.like(pattern, escape="\\"),
                AiReplyDecisionLog.reply_text.like(pattern, escape="\\"),
                DouyinPrivateMessageSend.content.like(pattern, escape="\\"),
            )
        )
    return query
```

- [ ] **Step 7: 更新 list item 构造**

把 `_build_list_item(row)` 改为：

```python
def _build_list_item(send: DouyinPrivateMessageSend, decision: AiReplyDecisionLog) -> dict[str, Any]:
    return {
        "id": decision.id,
        "send_record_id": send.id,
        "merchant_id": decision.merchant_id,
        "account_open_id": decision.account_open_id,
        "conversation_id": decision.conversation_id,
        "agent_id": decision.agent_id,
        "agent_name": decision.agent_name,
        "latest_message_summary": _summary(decision.latest_message),
        "reply_text_summary": _summary(decision.reply_text),
        "sent_content_summary": _summary(send.content),
        "send_status": send.status,
        "send_source": send.send_source,
        "auto_send": bool(send.auto_send),
        "manual_confirmed": bool(send.manual_confirmed),
        "upstream_msg_id": send.upstream_msg_id,
        "sent_at": send.sent_at,
        "intent": decision.intent,
        "lead_level": decision.lead_level,
        "confidence": decision.confidence,
        "manual_required": bool(decision.manual_required),
        "manual_required_reason": decision.manual_required_reason,
        "risk_flags": _json_list(decision.risk_flags_json),
        "tags": _json_list(decision.tags_json),
        "rag_used": bool(decision.rag_used),
        "llm_used": bool(decision.llm_used),
        "upstream_auto_send": bool(decision.upstream_auto_send),
        "final_auto_send": bool(decision.final_auto_send),
        "decision_version": decision.decision_version,
        "model": decision.model,
        "is_effective": decision.is_effective,
        "effectiveness_reason": decision.effectiveness_reason,
        "created_at": decision.created_at,
    }
```

- [ ] **Step 8: 扩展脱敏规则**

把 `_mask_sensitive_text` 改为同时处理手机号和微信号：

```python
def _mask_sensitive_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
    return re.sub(r"\b(wxid|wx|wechat)[A-Za-z0-9_\-]{4,}\b", r"\1***", text, flags=re.IGNORECASE)
```

- [ ] **Step 9: 跑后端查询测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected: 查询相关测试通过；PATCH 相关测试仍失败。

- [ ] **Step 10: 提交**

Commit:

```bash
git add tests/test_ai_reply_decision_logs_api.py app/services/ai_reply_decision_log_query_service.py app/schemas.py
git commit -m "feat: AI回复记录改为查询实发流水"
```

---

## Task 3: 有效性标记接口和审计

**Files:**
- Modify: `app/routers/ai_reply_decision_logs.py`
- Modify: `app/services/ai_reply_decision_log_query_service.py`

- [ ] **Step 1: 路由导入 patch schema 和审计函数**

在路由文件导入：

```python
from app.schemas import (
    AiReplyDecisionEffectivenessPatch,
    AiReplyDecisionLogDetailResponse,
    AiReplyDecisionLogListResponse,
)
from app.services.autoreply_admin_rollout_service import record_admin_audit
```

- [ ] **Step 2: 增加权限范围 helper**

替换旧 `_require_douyin_ai_cs_merchant`，改为读写分离：

```python
ADMIN_AI_REPLY_RECORDS_PERMISSION = "auto_wechat:admin:ai_reply_records"
MERCHANT_DOUYIN_AI_CS_PERMISSION = "auto_wechat:douyin_ai_cs"


def _resolve_read_merchant_scope(context: RequestContext, requested_merchant_id: str | None) -> str | None:
    """返回查询商户范围；None 表示超管查询全部商户。"""
    if context.has_permission(ADMIN_AI_REPLY_RECORDS_PERMISSION):
        return str(requested_merchant_id or "").strip() or None
    if not context.has_permission(MERCHANT_DOUYIN_AI_CS_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少 AI 回复记录查看权限"},
        )
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _require_admin_ai_reply_records(context: RequestContext) -> RequestContext:
    """AI 回复有效性标记仅允许超管记录权限。"""
    if not context.has_permission(ADMIN_AI_REPLY_RECORDS_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:ai_reply_records"},
        )
    return context
```

- [ ] **Step 3: 列表路由接入商户范围**

保留 query `merchant_id`，但只允许 admin 使用：

```python
trusted_merchant_id = _resolve_read_merchant_scope(context, merchant_id)
```

`AiReplyDecisionLogQuery(merchant_id=trusted_merchant_id, ...)` 继续传入。

- [ ] **Step 4: 详情路由兼容超管全部范围**

详情路由可增加可选 query：

```python
def get_log_detail(
    log_id: int,
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    trusted_merchant_id = _resolve_read_merchant_scope(context, merchant_id)
```

然后调用 `get_ai_reply_decision_log_detail(db, merchant_id=trusted_merchant_id, log_id=log_id)`。

- [ ] **Step 5: 查询服务 detail 函数允许 merchant_id 可空**

函数签名改为：

```python
def get_ai_reply_decision_log_detail(
    db: Session,
    *,
    merchant_id: str | None,
    log_id: int,
) -> dict[str, Any] | None:
```

当 `merchant_id is None` 时不加商户过滤，代表超管查询。

- [ ] **Step 6: 新增 patch 路由**

在路由文件新增：

```python
@router.patch("/{log_id}/effectiveness", response_model=AiReplyDecisionLogDetailResponse)
def patch_log_effectiveness(
    log_id: int,
    payload: AiReplyDecisionEffectivenessPatch,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """超管人工标记 AI 实发回复是否有效。"""
    _require_admin_ai_reply_records(context)
    has_is_effective = payload.is_effective is not None
    has_reason = payload.effectiveness_reason is not None
    if not has_is_effective and not has_reason:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_FIELDS_TO_UPDATE", "message": "至少需要提交 is_effective 或 effectiveness_reason"},
        )

    reason = payload.effectiveness_reason.strip() if payload.effectiveness_reason is not None else None
    if reason is not None and len(reason) > 500:
        raise HTTPException(
            status_code=400,
            detail={"code": "EFFECTIVENESS_REASON_TOO_LONG", "message": "有效性原因不能超过 500 字"},
        )

    row = (
        db.query(AiReplyDecisionLog)
        .join(DouyinPrivateMessageSend, DouyinPrivateMessageSend.decision_log_id == AiReplyDecisionLog.id)
        .filter(AiReplyDecisionLog.id == log_id)
        .filter(
            or_(
                DouyinPrivateMessageSend.send_source == "ai_auto",
                DouyinPrivateMessageSend.decision_log_id.isnot(None),
            )
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AI_REPLY_DECISION_LOG_NOT_FOUND", "message": "AI 回复记录不存在"},
        )

    before = {
        "is_effective": row.is_effective,
        "effectiveness_reason": row.effectiveness_reason,
    }
    if has_is_effective:
        row.is_effective = payload.is_effective
    if has_reason:
        row.effectiveness_reason = reason
    db.flush()
    after = {
        "is_effective": row.is_effective,
        "effectiveness_reason": row.effectiveness_reason,
    }
    record_admin_audit(
        db,
        action="mark_ai_reply_effectiveness",
        merchant_id=row.merchant_id,
        account_open_id=row.account_open_id,
        target_type="ai_reply_decision_log",
        target_id=str(row.id),
        before=before,
        after=after,
        reason=reason,
        operator_id=context.user_id,
        operator_name=context.display_name or context.username,
        commit=False,
    )
    db.commit()

    data = get_ai_reply_decision_log_detail(db, merchant_id=None, log_id=log_id)
    return {"success": True, "data": data, "message": "success"}
```

如果 lint 指出 `or_`、`AiReplyDecisionLog`、`DouyinPrivateMessageSend` 未导入，按现有风格从 SQLAlchemy 和 models 引入。

- [ ] **Step 7: 跑接口测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected: PASS。

- [ ] **Step 8: 跑关联后端回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_runs_api.py tests/test_admin_autoreply_rollout_api.py -v
```

Expected: PASS。若出现既有失败，必须用未修改本阶段文件的对照运行证明零新增回归，并在回传中列出失败测试名和证据。

- [ ] **Step 9: 提交**

Commit:

```bash
git add app/routers/ai_reply_decision_logs.py app/services/ai_reply_decision_log_query_service.py tests/test_ai_reply_decision_logs_api.py
git commit -m "feat: 增加AI回复有效性标记接口"
```

---

## Task 4: 前端 API 类型和真实入口接入

**Files:**
- Modify: `frontend/src/api/aiReplyDecisionLogs.ts`
- Modify: `frontend/src/features/douyin-cs/api.ts`
- Modify: `frontend/src/features/douyin-cs/types.ts`
- Modify: `frontend/src/pages/SuperAiReplyRecords.tsx`

- [ ] **Step 1: 扩展前端类型**

在 `AiReplyDecisionLogListItem` 增加字段：

```ts
send_record_id?: number | null;
sent_content_summary?: string | null;
send_status?: string | null;
send_source?: string | null;
auto_send?: boolean;
manual_confirmed?: boolean;
upstream_msg_id?: string | null;
sent_at?: string | null;
model?: string | null;
is_effective?: boolean | null;
effectiveness_reason?: string | null;
```

在 `AiReplyDecisionLogDetail` 增加字段：

```ts
sent_content?: string | null;
```

增加 patch 类型：

```ts
export interface AiReplyDecisionEffectivenessPatch {
  is_effective?: boolean | null;
  effectiveness_reason?: string | null;
}
```

- [ ] **Step 2: 扩展查询参数**

在 `AiReplyDecisionLogQueryParams` 增加：

```ts
merchant_id?: string;
send_status?: string;
is_effective?: boolean | null;
```

并在 `buildQueryParams` 增加：

```ts
appendString(params, "merchant_id", query.merchant_id);
appendString(params, "send_status", query.send_status);
appendBoolean(params, "is_effective", query.is_effective);
```

- [ ] **Step 3: 新增 patch API**

在 `frontend/src/api/aiReplyDecisionLogs.ts` 增加：

```ts
export async function patchAiReplyDecisionLogEffectiveness(
  id: number | string,
  payload: AiReplyDecisionEffectivenessPatch,
): Promise<AiReplyDecisionLogDetail> {
  const response = (await apiClient.patch(
    `/ai-reply-decision-logs/${encodeURIComponent(String(id))}/effectiveness`,
    payload,
  )) as unknown as ApiResponse<AiReplyDecisionLogDetail>;
  return response.data;
}
```

- [ ] **Step 4: 导出 API 和类型**

在 `frontend/src/features/douyin-cs/api.ts` 导出 `patchAiReplyDecisionLogEffectiveness`。

在 `frontend/src/features/douyin-cs/types.ts` 导出 `AiReplyDecisionEffectivenessPatch`。

- [ ] **Step 5: 替换超管假数据入口**

将 `frontend/src/pages/SuperAiReplyRecords.tsx` 简化为：

```tsx
export { default } from "../features/douyin-cs/pages/AiReplyDecisionLogsPage";
```

这一步必须删除本文件中的 `initialRecords`、`ReplyRecord`、本地审核状态和假商户数据。

- [ ] **Step 6: 前端类型检查**

Run:

```bash
cd frontend
npm run build
```

Expected: 如果页面尚未改造，可能因为新增字段未使用仍能通过；继续 Task 5。

---

## Task 5: 前端页面改为 AI 实发记录

**Files:**
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`

- [ ] **Step 1: 调整导入**

从 `../api` 增加导入：

```ts
patchAiReplyDecisionLogEffectiveness,
```

- [ ] **Step 2: 清理旧文案**

替换页面可见文案：

| 旧文案 | 新文案 |
|---|---|
| `AI回复记录` | `AI实发记录` |
| `AI回复记录详情` | `AI实发记录详情` |
| `仅记录 AI 回复建议，不代表自动发送` | `展示 AI 自动回复和 AI 辅助发送的最终实发内容` |
| `仅记录 AI 回复建议，不会自动发送` | `内容来自发送流水，已包含发送前统一处理结果` |
| `系统最终保持 auto_send=false` | 删除 |
| `AI建议回复` | `AI实发内容` |
| `不会自动发送` | `已发送` / `发送失败` / `待发送` |

- [ ] **Step 3: 增加状态文案 helper**

在页面 helper 区域增加：

```ts
function sendStatusLabel(status?: string | null): string {
  if (status === "sent") return "已发送";
  if (status === "failed") return "发送失败";
  if (status === "pending") return "待发送";
  return status || "未知";
}

function sendStatusTone(status?: string | null): "slate" | "amber" | "red" | "emerald" {
  if (status === "sent") return "emerald";
  if (status === "failed") return "red";
  if (status === "pending") return "amber";
  return "slate";
}

function effectivenessLabel(value?: boolean | null): string {
  if (value === true) return "有效";
  if (value === false) return "无效";
  return "未标记";
}
```

- [ ] **Step 4: 详情弹窗展示实发内容**

详情弹窗中将右侧文本块改为：

```tsx
<section className="rounded-xl border border-[#e4e8f0] bg-white p-4">
  <h3 className="text-xs font-bold text-[#1a1f2e]">AI实发内容</h3>
  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-[#475467]">
    {detail.sent_content || "-"}
  </p>
</section>
```

保留 `reply_text` 作为“模型原始回复”或“决策回复”小字段，不再作为主内容。

- [ ] **Step 5: 增加有效性标记动作**

在页面组件中增加函数：

```ts
const markEffectiveness = async (id: number, isEffective: boolean) => {
  const reason = window.prompt(isEffective ? "请输入标记为有效的原因" : "请输入标记为无效的原因");
  if (reason === null) return;
  const text = reason.trim();
  if (!text) {
    setDetailError("请填写标记原因");
    return;
  }
  setDetailLoading(true);
  setDetailError(null);
  try {
    const updated = await patchAiReplyDecisionLogEffectiveness(id, {
      is_effective: isEffective,
      effectiveness_reason: text,
    });
    setDetail(updated);
    await loadLogs();
  } catch (err) {
    setDetailError(resolveErrorMessage(err));
  } finally {
    setDetailLoading(false);
  }
};
```

在详情弹窗 footer 增加两个按钮：

```tsx
{detail ? (
  <>
    <button
      onClick={() => void markEffectiveness(detail.id, true)}
      className="h-9 rounded-xl bg-emerald-600 px-4 text-xs font-semibold text-white hover:bg-emerald-700"
    >
      标记有效
    </button>
    <button
      onClick={() => void markEffectiveness(detail.id, false)}
      className="h-9 rounded-xl bg-red-600 px-4 text-xs font-semibold text-white hover:bg-red-700"
    >
      标记无效
    </button>
  </>
) : null}
```

如果 TypeScript 作用域要求 `markEffectiveness` 传入弹窗组件，则把函数作为 `DetailModal` prop 传入，不要引入全局状态库。

- [ ] **Step 6: 列表表格改用发送字段**

列表中把第二列改为 `AI实发内容`，使用：

```tsx
{item.sent_content_summary || "-"}
```

状态列使用：

```tsx
<Chip tone={sendStatusTone(item.send_status)}>{sendStatusLabel(item.send_status)}</Chip>
<div className="text-[10px] text-[#8b95a6]">
  模型 {item.model || "-"} / {effectivenessLabel(item.is_effective)}
</div>
```

行 key 使用发送流水，避免同一决策日志重复发送时 key 冲突：

```tsx
<tr key={item.send_record_id || item.id} ...>
```

- [ ] **Step 7: 页面静态旧口径检查**

Run:

```bash
rg -n "initialRecords|仅记录 AI 回复建议|不会自动发送|auto_send=false|AI建议回复|垃圾回复|查看商户智能体回复质量" frontend/src/pages/SuperAiReplyRecords.tsx frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx
```

Expected: 无输出。

- [ ] **Step 8: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS。

- [ ] **Step 9: 提交**

Commit:

```bash
git add frontend/src/api/aiReplyDecisionLogs.ts frontend/src/features/douyin-cs/api.ts frontend/src/features/douyin-cs/types.ts frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx frontend/src/pages/SuperAiReplyRecords.tsx
git commit -m "feat: AI回复记录前端展示实发内容"
```

---

## Task 6: 阶段总验证与边界检查

**Files:**
- No new files

- [ ] **Step 1: 后端专项测试**

Run:

```bash
python -m pytest tests/test_ai_reply_decision_logs_api.py -v
```

Expected: PASS。

- [ ] **Step 2: 后端关联回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_runs_api.py tests/test_admin_autoreply_rollout_api.py -v
```

Expected: PASS。若失败，必须提供对照证据证明是否 pre-existing。

- [ ] **Step 3: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS。

- [ ] **Step 4: 禁止越界静态检查**

Run:

```bash
git diff --name-only HEAD~3..HEAD
```

Expected: 只包含本执行包允许文件。若提交数量不是 3 个，改用本阶段起始 commit 到 HEAD 的范围检查。

Run:

```bash
git diff --check -- app/services/ai_reply_decision_log_query_service.py app/routers/ai_reply_decision_logs.py app/schemas.py tests/test_ai_reply_decision_logs_api.py frontend/src/api/aiReplyDecisionLogs.ts frontend/src/features/douyin-cs/api.ts frontend/src/features/douyin-cs/types.ts frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx frontend/src/pages/SuperAiReplyRecords.tsx
```

Expected: 无输出。

Run:

```bash
rg -n "input_writer|contact_searcher|local_agent_main|apps/xg_douyin_ai_cs|ai_auto_reply_send_service|douyin_private_message_send_service" -- app frontend tests
```

Expected: 本阶段 diff 不应触碰这些文件。若 `rg` 命中历史引用，只看 `git diff --name-only`，不得把历史命中当成本阶段越界。

Run:

```bash
rg -n "initialRecords|仅记录 AI 回复建议|不会自动发送|auto_send=false|AI建议回复|垃圾回复|查看商户智能体回复质量" frontend/src/pages/SuperAiReplyRecords.tsx frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx
```

Expected: 无输出。

- [ ] **Step 5: 最终状态检查**

Run:

```bash
git status --short --branch
```

Expected: 只允许出现已知计划文档残留；本阶段代码文件必须已提交或明确列入回传。

---

## 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| AI 自动发送记录列表 | 集成 | decision log + `send_source=ai_auto` send record | 列表返回 1 条，内容来自 send.content | `tests/test_ai_reply_decision_logs_api.py` |
| 决策未发送 | 集成 | 只有 `AiReplyDecisionLog` 无 send record | 不进入 AI 实发记录 | 同上 |
| 普通人工发送 | 集成 | `send_source=manual` 且 `decision_log_id=None` | 不进入 AI 实发记录 | 同上 |
| 商户隔离 | 权限 | 商户 A 请求携带 `merchant_id=merchant-b` | 仍只返回商户 A | 同上 |
| 超管筛选 | 权限 | `auto_wechat:admin:ai_reply_records` + `merchant_id=merchant-b` | 返回商户 B | 同上 |
| 详情脱敏 | 集成 | 实发内容含手机号 | 返回 `138****5678`，不返回 request/response raw | 同上 |
| 有效性标记 | 权限 / 状态 | 超管 PATCH | 更新字段并写审计 | 同上 |
| 非超管标记 | 权限 | 商户侧 PATCH | 403 | 同上 |
| 前端真实入口 | 构建 / 静态 | `/admin/ai-reply-records` 对应页面 | 不再保留本地假数据 | `rg` + `npm run build` |
| 旧口径清理 | 静态 | 扫描本页旧文案 | 无旧“建议/不会发送/auto_send=false”文案 | `rg` |

---

## 回滚方案

1. 后端查询改造回滚：回退本阶段后端提交，`GET /ai-reply-decision-logs` 恢复旧决策日志查询；不涉及数据库结构回滚。
2. PATCH 接口回滚：回退本阶段接口提交，保留数据库字段不变；已写入的 `is_effective` 和审计日志可继续留存。
3. 前端入口回滚：回退前端提交，页面恢复旧展示；不影响发送链路。
4. 如果只需要临时停止有效性标记，可只回滚或隐藏前端按钮；后端 PATCH 接口仍受 `auto_wechat:admin:ai_reply_records` 权限保护。

---

## 执行窗口回传格式

```text
阶段：Phase 4 AI回复记录改造
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
未触碰：app/services/ai_auto_reply_send_service.py、app/services/douyin_private_message_send_service.py、apps/xg_douyin_ai_cs、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化

测试命令与结果：
- python -m pytest tests/test_ai_reply_decision_logs_api.py -v：...
- python -m pytest tests/test_ai_auto_reply_runs_api.py tests/test_admin_autoreply_rollout_api.py -v：...
- cd frontend && npm run build：...
- git diff --check ...：...
- rg 旧口径检查：...

自审结论：
- Spec Reviewer：Approved / Needs Fix
- Code Quality Reviewer：Approved / Needs Fix

剩余风险：
- ...

需要本窗口审批的问题：
- ...
```

---

## Spec Reviewer 清单

1. 是否只展示 `DouyinPrivateMessageSend JOIN AiReplyDecisionLog` 的 AI 相关发送记录。
2. 是否以 `DouyinPrivateMessageSend.content` 作为 AI 实发内容。
3. 是否过滤普通人工发送。
4. 商户侧是否不能通过 query `merchant_id` 越权。
5. 超管是否能按 `merchant_id` 筛选。
6. 有效性标记是否仅 `auto_wechat:admin:ai_reply_records` 可写。
7. PATCH 是否写审计日志，且审计不包含完整客户消息、手机号、微信号、token、cookie、secret。
8. 前端实际入口 `/admin/ai-reply-records` 是否不再使用假数据。
9. 是否没有提前清理全站 Phase 13 旧文案。
10. 是否没有新增迁移、权限码、依赖、环境变量。

## Code Quality Reviewer 清单

1. 查询服务是否避免 N+1 查询，列表使用一次联表分页。
2. `count()` 是否和列表筛选条件一致。
3. 详情是否要求存在关联发送流水，避免未发送决策被当成实发记录。
4. 返回结构是否不暴露 `request_body_json`、`response_body_json`、`raw_response_json`。
5. 脱敏是否覆盖手机号和常见微信号格式。
6. PATCH 是否校验空 payload、空 reason、过长 reason。
7. PATCH 是否在一个事务内完成字段更新和审计写入。
8. 前端是否没有保留本地假数据和批量假审核逻辑。
9. 前端构建是否通过，且没有引入新的全局状态或依赖。
10. 是否未触碰发送服务、9100、微信自动化和 Local Agent。

## 本窗口审批清单

审批窗口收到执行回传后只判断：

1. Phase 4 是否完成“AI 实发记录”目标。
2. 是否存在越界修改。
3. 是否存在未解释的测试失败。
4. 是否保留已知计划文档残留但无业务未提交改动。
5. 是否允许进入 Phase 5 执行包制定。

审批结论只能是：

```text
通过
有条件通过
不通过
```
