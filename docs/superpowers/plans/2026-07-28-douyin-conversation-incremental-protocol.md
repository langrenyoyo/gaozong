# 抖音客服会话增量协议实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务执行本计划并用复选框跟踪。项目已声明原地执行，不创建 worktree、不新建分支、不切换目录。

**Goal:** 在不改变 webhook 验签、已读语义和发送链路的前提下，为抖音客服工作台补齐基于 `DouyinWebhookEvent.id` 的会话与消息增量协议、全账号恢复同步和历史消息分页。

**Architecture:** 后端复用一套受商户、账号、会话、事件类型和重复标记约束的事件查询构造器，在其上提供有界的 `after_event_id` / `before_event_id` 页面；前端复用现有 8 秒轮询入口，通过纯 TypeScript 辅助函数管理水位、合并、退避和单飞同步。PostgreSQL 查询先在专用本地库完成 5 万行执行计划门禁，索引不足时停止本任务并拆分 `0017` 迁移，不在本候选内改迁移。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.x、PostgreSQL 15、SQLite 测试、pytest、React 19、TypeScript 5.9、TanStack Query、无依赖 Node 行为检查。

---

## 计划元数据与硬边界

- Task-ID：`DY-CS-CONVERSATION-INCREMENTAL-PROTOCOL-1`
- Plan-Revision：`R1`
- Execution-Base：`b464abbef3663f8948e929d18ab314bd02c5f1fb`
- 设计规格：`docs/superpowers/specs/2026-07-28-douyin-conversation-incremental-protocol-design.md`
- 设计规格 SHA256：`EC6287EB1253F67862EE17551B6BAF869CDD37E2EA93FF9513B80FD3B5EE2B3C`
- 风险等级：`MEDIUM`；如 PostgreSQL 门禁要求新索引，则迁移子任务升级为 `HIGH`。
- 执行方式：当前工作区原地执行，单父线性追加；不得 amend、rebase、squash、merge、cherry-pick。
- 当前两份既有治理计划保持暂存，不修改、不取消暂存、不纳入业务提交。
- 业务候选独立测试并推送前，不更新活动文档和外部待办完成状态。

## 文件职责与允许范围

**允许修改：**

- `app/services/douyin_workbench_conversation_service.py`：共享事件查询、消息页面、会话摘要水位、账号水位。
- `app/routers/integrations.py`：两个消息入口和会话列表入口的游标参数及 `422` 合同。
- `app/routers/douyin_accounts.py`：企业号列表增加账号级 `latest_event_id`。
- `frontend/src/api/douyinAiCsClient.ts`：响应类型、游标参数和字段规范化。
- `frontend/src/features/douyin-cs/douyinConversationIncremental.ts`：新增纯函数，负责消息/会话合并、水位和退避。
- `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`：全账号同步、恢复触发、历史消息和同步状态。
- `frontend/scripts/check-douyin-workbench-incremental.mjs`：新增无依赖行为检查。
- `frontend/package.json`：只新增上述检查脚本入口，不增依赖。
- `tests/test_douyin_workbench_conversations.py`：消息与会话游标协议、兼容性和静态前端合同。
- `tests/test_douyin_accounts_router.py`：账号水位及商户隔离。
- `tests/test_douyin_workbench_tenant_isolation_r2.py`：跨商户游标、防枚举和 `merchant_id=NULL` 隔离。
- `tests/test_9000_postgres_douyin_conversation_incremental.py`：新增专用 PostgreSQL 执行计划门禁。

**明确禁止：**

- 不修改 `app/models.py`、`migrations/**`、环境模板、Docker、活动文档或外部待办。
- 不修改 webhook 签名头/验签、已读模型或 mark-read 写入语义。
- 不修改人工发送、自动回复、outbox、违禁词、9100 或任何真实发送保护。
- 不新增 SSE/WebSocket、前端依赖、localStorage/sessionStorage 游标。
- 不连接 staging/production，不运行生产迁移，不调用真实抖音、9100、LLM、微信或发送接口。

## 验收编号覆盖

- Task 1～3：A1～A11。
- Task 4：A12 及查询安全门。
- Task 5～7：F1～F10。
- Task 8：完整回归、三轮稳定性、范围和候选冻结。

### Task 1：建立消息游标与路由校验红灯合同

**Files:**
- Modify: `tests/test_douyin_workbench_conversations.py`
- Modify: `tests/test_douyin_workbench_tenant_isolation_r2.py`
- Modify: `app/routers/integrations.py`

- [ ] **Step 1：记录执行前 Git 基线且保护既有暂存文件**

Run:

```powershell
git rev-parse HEAD
git status --short
git diff --cached --name-only
git merge-base --is-ancestor b464abbef3663f8948e929d18ab314bd02c5f1fb HEAD
```

Expected:

```text
HEAD = b464abbef3663f8948e929d18ab314bd02c5f1fb
仅两份既有治理计划和本计划处于暂存状态
祖先检查退出码 0
```

如果 HEAD 或暂存范围不同，停止并回传 `REPAIR_REQUIRED`，不得自动恢复或重排用户改动。

- [ ] **Step 2：在现有测试夹具中补充重复标记和原始坏事件能力**

将 `_insert_event()` 增加两个可选参数，并原位写入模型：

```python
def _insert_event(
    *,
    event: str = "im_receive_msg",
    open_id: str = "customer_001",
    account_open_id: str = "account_001",
    text: str = "hello",
    conversation_short_id: str | None = None,
    event_key: str = "event_001",
    server_message_id: str = "msg_001",
    created_at: datetime | None = None,
    lead_id: int | None = None,
    is_duplicate: bool = False,
    raw_body: str | None = None,
) -> int:
    db = TestSession()
    try:
        payload = _payload(
            event=event,
            open_id=open_id,
            account_open_id=account_open_id,
            text=text,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
        )
        item = DouyinWebhookEvent(
            event=event,
            from_user_id=payload["from_user_id"],
            to_user_id=payload["to_user_id"],
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            event_key=event_key,
            is_duplicate=is_duplicate,
            lead_id=lead_id,
            raw_body=raw_body if raw_body is not None else json.dumps(payload, ensure_ascii=False),
            created_at=created_at or datetime.now(),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()
```

- [ ] **Step 3：写消息游标、多页、排序和坏事件推进红灯测试**

在 `tests/test_douyin_workbench_conversations.py` 增加下列合同；测试数据使用唯一账号/会话，避免与本文件其他用例相互污染：

```python
def test_message_after_cursor_pages_without_duplicates_and_advances_over_bad_event():
    account = "account_cursor_after"
    conversation = "conv_cursor_after"
    first = _insert_event(
        account_open_id=account,
        open_id="customer_cursor_after",
        conversation_short_id=conversation,
        event_key="cursor-after-1",
        text="第一条",
    )
    bad = _insert_event(
        account_open_id=account,
        open_id="customer_cursor_after",
        conversation_short_id=conversation,
        event_key="cursor-after-bad",
        raw_body="not-json",
    )
    third = _insert_event(
        account_open_id=account,
        open_id="customer_cursor_after",
        conversation_short_id=conversation,
        event_key="cursor-after-3",
        text="第三条",
    )

    client = _client()
    page1 = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation,
            "account_open_id": account,
            "after_event_id": 0,
            "limit": 2,
        },
    ).json()
    page2 = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation,
            "account_open_id": account,
            "after_event_id": page1["next_after_event_id"],
            "limit": 2,
        },
    ).json()

    assert [item["raw_event_id"] for item in page1["items"]] == [first]
    assert page1["next_after_event_id"] == bad
    assert page1["has_more"] is True
    assert [item["raw_event_id"] for item in page2["items"]] == [third]
    assert page2["next_after_event_id"] == third
    assert page2["has_more"] is False


def test_message_before_cursor_loads_more_than_200_and_keeps_stable_display_order():
    account = "account_cursor_before"
    conversation = "conv_cursor_before"
    event_ids = [
        _insert_event(
            account_open_id=account,
            open_id="customer_cursor_before",
            conversation_short_id=conversation,
            event_key=f"cursor-before-{index}",
            server_message_id=f"cursor-before-msg-{index}",
            text=f"消息 {index}",
            created_at=datetime(2026, 7, 28, 10, index % 2),
        )
        for index in range(205)
    ]
    client = _client()
    newest = client.get(
        "/integrations/douyin/conversation-messages",
        params={"conversation_key": conversation, "account_open_id": account, "limit": 100},
    ).json()
    older1 = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation,
            "account_open_id": account,
            "before_event_id": newest["next_before_event_id"],
            "limit": 100,
        },
    ).json()
    older2 = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation,
            "account_open_id": account,
            "before_event_id": older1["next_before_event_id"],
            "limit": 100,
        },
    ).json()
    merged = newest["items"] + older1["items"] + older2["items"]

    assert {item["raw_event_id"] for item in merged} == set(event_ids)
    assert len(merged) == 205
    for page in (newest, older1, older2):
        assert [
            (item["created_at"], item["raw_event_id"]) for item in page["items"]
        ] == sorted((item["created_at"], item["raw_event_id"]) for item in page["items"])


def test_after_cursor_includes_late_insert_with_older_created_at():
    account = "account_late_cursor"
    conversation = "conv_late_cursor"
    first = _insert_event(
        account_open_id=account,
        open_id="customer_late_cursor",
        conversation_short_id=conversation,
        event_key="late-cursor-first",
        created_at=datetime(2026, 7, 28, 12, 0),
    )
    late = _insert_event(
        account_open_id=account,
        open_id="customer_late_cursor",
        conversation_short_id=conversation,
        event_key="late-cursor-second",
        created_at=datetime(2026, 7, 28, 11, 0),
    )
    data = _client().get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": conversation,
            "account_open_id": account,
            "after_event_id": first,
            "limit": 100,
        },
    ).json()

    assert [item["raw_event_id"] for item in data["items"]] == [late]
    assert data["next_after_event_id"] == late
```

- [ ] **Step 4：写参数校验、空页兼容和路径/查询双入口一致性红灯测试**

```python
def test_message_cursor_validation_and_empty_page_contract():
    account = "account_cursor_validation"
    conversation = "conv_cursor_validation"
    event_id = _insert_event(
        account_open_id=account,
        open_id="customer_cursor_validation",
        conversation_short_id=conversation,
        event_key="cursor-validation-event",
    )
    client = _client()
    base = {"conversation_key": conversation, "account_open_id": account}

    for params in (
        {**base, "after_event_id": -1},
        {**base, "before_event_id": -1},
        {**base, "after_event_id": 0, "before_event_id": event_id},
        {**base, "after_event_id": "x"},
        {**base, "limit": 201},
    ):
        assert client.get("/integrations/douyin/conversation-messages", params=params).status_code == 422

    query_page = client.get(
        "/integrations/douyin/conversation-messages",
        params={**base, "after_event_id": event_id, "limit": 20},
    )
    path_page = client.get(
        f"/integrations/douyin/conversations/{conversation}/messages",
        params={"account_open_id": account, "after_event_id": event_id, "limit": 20},
    )
    assert query_page.status_code == path_page.status_code == 200
    assert query_page.json() == path_page.json()
    assert query_page.json()["items"] == []
    assert query_page.json()["next_after_event_id"] == event_id
    assert query_page.json()["has_more"] is False
```

在租户隔离文件增加一个合法空页/不存在会话对照，并传入另一个商户的真实事件 ID：

```python
def test_other_merchant_event_cursor_is_only_a_boundary_and_cannot_bypass_scope():
    _insert_account("acc_cursor_owner", merchant_id="merchant-1")
    own = _insert_event(
        account_open_id="acc_cursor_owner",
        customer_open_id="cust_cursor_owner",
        event_key="cursor-owner-event",
        merchant_id="merchant-1",
    )
    foreign = _insert_event(
        account_open_id="acc_cursor_foreign",
        customer_open_id="cust_cursor_foreign",
        event_key="cursor-foreign-event",
        merchant_id="merchant-2",
    )
    client = _client(_context("merchant-1"))

    empty = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": "acc_cursor_owner:cust_cursor_owner",
            "account_open_id": "acc_cursor_owner",
            "after_event_id": foreign.id,
        },
    )
    missing = client.get(
        "/integrations/douyin/conversation-messages",
        params={
            "conversation_key": "acc_cursor_owner:not-found",
            "account_open_id": "acc_cursor_owner",
            "after_event_id": own.id,
        },
    )

    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert missing.status_code == 404
```

- [ ] **Step 5：运行红灯并保存准确失败原因**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py -k "cursor or late_insert" -q
pytest tests/test_douyin_workbench_tenant_isolation_r2.py -k "event_cursor" -q
```

Expected: FAIL；失败原因应为路由尚不接受游标、响应缺少页面字段或合法空页仍错误返回 `404`。若测试在夹具阶段失败，先修测试数据，不进入实现。

- [ ] **Step 6：只增加 FastAPI 参数边界和互斥校验**

在 `app/routers/integrations.py` 导入 `Query`，并为两个消息路由使用同一参数合同：

```python
from fastapi import APIRouter, Depends, HTTPException, Query


def _validate_message_cursor_pair(after_event_id: int | None, before_event_id: int | None) -> None:
    if after_event_id is not None and before_event_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"code": "DOUYIN_MESSAGE_CURSOR_CONFLICT", "message": "after_event_id 与 before_event_id 不能同时使用"},
        )
```

两个入口均声明并透传：

```python
after_event_id: int | None = Query(default=None, ge=0),
before_event_id: int | None = Query(default=None, ge=0),
limit: int | None = Query(default=None, ge=1, le=200),
```

调用服务前执行 `_validate_message_cursor_pair()`；调用 `list_conversation_messages()` 时透传三个参数。路径形式和查询形式必须调用同一个服务函数，禁止复制服务逻辑。

- [ ] **Step 7：运行参数测试，确认只剩服务字段红灯**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py::test_message_cursor_validation_and_empty_page_contract -q
```

Expected: `422` 参数断言通过；页面字段或空页语义仍 FAIL。

- [ ] **Step 8：提交路由合同和红灯测试**

```powershell
git add app/routers/integrations.py tests/test_douyin_workbench_conversations.py tests/test_douyin_workbench_tenant_isolation_r2.py
git commit --only app/routers/integrations.py tests/test_douyin_workbench_conversations.py tests/test_douyin_workbench_tenant_isolation_r2.py -m "测试：建立抖音会话消息游标合同"
```

### Task 2：实现共享事件页与消息游标

**Files:**
- Modify: `app/services/douyin_workbench_conversation_service.py`
- Test: `tests/test_douyin_workbench_conversations.py`
- Test: `tests/test_douyin_workbench_tenant_isolation_r2.py`

- [ ] **Step 1：增加有界页面类型和常量**

在 `WorkbenchMessage` 后增加：

```python
WORKBENCH_CURSOR_DEFAULT_LIMIT = 100
WORKBENCH_CURSOR_MAX_LIMIT = 200


@dataclass(frozen=True)
class WorkbenchEventRowPage:
    rows: list[SimpleNamespace]
    scanned_event_ids: list[int]
    has_more: bool


@dataclass(frozen=True)
class WorkbenchMessagePage:
    messages: list[WorkbenchMessage]
    scanned_event_ids: list[int]
    has_more: bool
```

- [ ] **Step 2：提取共享 SQL 构造器，不改变旧调用排序**

把 `_query_message_rows()` 中 `select(...).where(...)` 到 `lookback_days` 的过滤原位提取为：

```python
def _build_message_rows_statement(
    *,
    account_open_id: str | None,
    account_open_ids: list[str] | None,
    conversation_key: str | None,
    events: set[str],
    lookback_days: int | None,
    merchant_id: str | None,
):
    stmt = (
        select(
            DouyinWebhookEvent.id,
            DouyinWebhookEvent.event,
            DouyinWebhookEvent.from_user_id,
            DouyinWebhookEvent.to_user_id,
            DouyinWebhookEvent.conversation_short_id,
            DouyinWebhookEvent.server_message_id,
            DouyinWebhookEvent.message_type,
            DouyinWebhookEvent.parsed_content_json,
            DouyinWebhookEvent.lead_id,
            DouyinWebhookEvent.raw_body,
            DouyinWebhookEvent.created_at,
        )
        .where(DouyinWebhookEvent.event.in_(events))
        .where(DouyinWebhookEvent.is_duplicate.is_(False))
    )
    if merchant_id:
        stmt = stmt.where(DouyinWebhookEvent.merchant_id == merchant_id)
    account_values = [
        item
        for item in ([account_open_id] if account_open_id else []) + (account_open_ids or [])
        if item
    ]
    if account_values:
        stmt = stmt.where(
            or_(
                DouyinWebhookEvent.to_user_id.in_(account_values),
                DouyinWebhookEvent.from_user_id.in_(account_values),
            )
        )
    if conversation_key:
        pair_account, pair_customer = _conversation_pair_from_key(conversation_key, account_open_id)
        if pair_account and pair_customer:
            stmt = stmt.where(
                or_(
                    DouyinWebhookEvent.conversation_short_id == conversation_key,
                    cast(DouyinWebhookEvent.raw_body, Text).like(f"%{conversation_key}%"),
                    (DouyinWebhookEvent.from_user_id == pair_customer)
                    & (DouyinWebhookEvent.to_user_id == pair_account),
                    (DouyinWebhookEvent.from_user_id == pair_account)
                    & (DouyinWebhookEvent.to_user_id == pair_customer),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    DouyinWebhookEvent.conversation_short_id == conversation_key,
                    cast(DouyinWebhookEvent.raw_body, Text).like(f"%{conversation_key}%"),
                )
            )
    if lookback_days:
        stmt = stmt.where(DouyinWebhookEvent.created_at >= datetime.now() - timedelta(days=lookback_days))
    return stmt
```

旧 `_query_message_rows()` 继续对该语句使用 `(created_at DESC, id DESC)`、旧 `limit` 和结果反转，确保 A1 无游标行为不漂移。

- [ ] **Step 3：增加按事件 ID 扫描的共享页函数**

```python
def _query_message_row_page(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str | None,
    merchant_id: str | None,
    after_event_id: int | None,
    before_event_id: int | None,
    limit: int,
) -> WorkbenchEventRowPage:
    stmt = _build_message_rows_statement(
        account_open_id=account_open_id,
        account_open_ids=None,
        conversation_key=conversation_key,
        events=PRIVATE_MESSAGE_EVENTS,
        lookback_days=None,
        merchant_id=merchant_id,
    )
    descending = before_event_id is not None or (after_event_id is None and before_event_id is None)
    if after_event_id is not None:
        stmt = stmt.where(DouyinWebhookEvent.id > after_event_id)
    if before_event_id is not None:
        stmt = stmt.where(DouyinWebhookEvent.id < before_event_id)
    order = DouyinWebhookEvent.id.desc() if descending else DouyinWebhookEvent.id.asc()
    rows = db.execute(stmt.order_by(order).limit(limit + 1)).mappings().all()
    db.rollback()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    if descending:
        page_rows.reverse()
    normalized = [SimpleNamespace(**dict(row)) for row in page_rows]
    return WorkbenchEventRowPage(
        rows=normalized,
        scanned_event_ids=[int(row.id) for row in normalized],
        has_more=has_more,
    )
```

额外一行只判断 `has_more`，不得进入 `scanned_event_ids`，否则游标会跳过未返回事件。

- [ ] **Step 4：解析事件页并保留坏事件扫描水位**

```python
def _load_message_page(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
    merchant_id: str | None,
    after_event_id: int | None,
    before_event_id: int | None,
    limit: int,
) -> WorkbenchMessagePage:
    row_page = _query_message_row_page(
        db,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        merchant_id=merchant_id,
        after_event_id=after_event_id,
        before_event_id=before_event_id,
        limit=limit,
    )
    messages = []
    for row in row_page.rows:
        message = _row_to_message(db, row)
        if message is not None and message.account_open_id == account_open_id and message.conversation_key == conversation_key:
            messages.append(message)
    return WorkbenchMessagePage(
        messages=_attach_message_send_records(db, messages, merchant_id=merchant_id),
        scanned_event_ids=row_page.scanned_event_ids,
        has_more=row_page.has_more,
    )
```

- [ ] **Step 5：增加不受游标影响的会话存在性和最大水位查询**

```python
def _conversation_exists(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
    merchant_id: str | None,
) -> bool:
    stmt = _build_message_rows_statement(
        account_open_id=account_open_id,
        account_open_ids=None,
        conversation_key=conversation_key,
        events=PRIVATE_MESSAGE_EVENTS,
        lookback_days=None,
        merchant_id=merchant_id,
    ).with_only_columns(DouyinWebhookEvent.id).limit(1)
    exists = db.execute(stmt).scalar_one_or_none() is not None
    db.rollback()
    return exists


def _latest_visible_event_id(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str | None,
    merchant_id: str | None,
) -> int:
    stmt = _build_message_rows_statement(
        account_open_id=account_open_id,
        account_open_ids=None,
        conversation_key=conversation_key,
        events=PRIVATE_MESSAGE_EVENTS,
        lookback_days=None,
        merchant_id=merchant_id,
    ).with_only_columns(func.max(DouyinWebhookEvent.id))
    value = db.execute(stmt).scalar_one_or_none()
    db.rollback()
    return int(value or 0)
```

- [ ] **Step 6：扩展消息响应且保持无游标最近 200 条兼容**

将 `list_conversation_messages()` 签名增加三个可选参数。无游标且无 `limit` 时仍走现有 `_load_messages(... limit=WORKBENCH_MESSAGE_LIMIT)`；其他情况走 `_load_message_page()`。服务层的核心返回逻辑必须等价于：

```python
resolved_limit = min(limit or WORKBENCH_CURSOR_DEFAULT_LIMIT, WORKBENCH_CURSOR_MAX_LIMIT)
cursor_mode = after_event_id is not None or before_event_id is not None or limit is not None
if not cursor_mode:
    messages = _load_messages(
        db,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        limit=WORKBENCH_MESSAGE_LIMIT,
        operation="list_conversation_messages",
        merchant_id=merchant_id,
    )
    scanned_ids = [item.event_id for item in messages]
    page_has_more = False
else:
    page = _load_message_page(
        db,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        merchant_id=merchant_id,
        after_event_id=after_event_id,
        before_event_id=before_event_id,
        limit=resolved_limit,
    )
    messages = page.messages
    scanned_ids = page.scanned_event_ids
    page_has_more = page.has_more

if merchant_id and not messages and not _conversation_exists(
    db,
    account_open_id=account_open_id,
    conversation_key=conversation_key,
    merchant_id=merchant_id,
):
    raise ConversationNotFoundError("conversation_not_found")

result = _conversation_messages_payload(messages, conversation_key=conversation_key)
latest_event_id = _latest_visible_event_id(
    db,
    account_open_id=account_open_id,
    conversation_key=conversation_key,
    merchant_id=merchant_id,
)
result.update(
    {
        "latest_event_id": latest_event_id,
        "next_after_event_id": max(scanned_ids, default=after_event_id or latest_event_id),
        "next_before_event_id": min(scanned_ids, default=before_event_id or latest_event_id or 0),
        "has_more": page_has_more,
    }
)
```

对初始受限页，`next_after_event_id` 必须是会话当前 `latest_event_id`，不是该页最老事件；`next_before_event_id` 是本页最老扫描事件。实现时针对这一点单独分支，避免未来补拉从错误水位开始。

- [ ] **Step 7：让详情消息复用扩展载荷但不增加详情游标**

`get_conversation_detail()` 仍只接收原参数；其 `messages` 调用 `_conversation_messages_payload()` 后补齐：

```python
message_ids = [item.event_id for item in messages]
result["messages"].update(
    {
        "latest_event_id": max(message_ids, default=0),
        "next_after_event_id": max(message_ids, default=0),
        "next_before_event_id": min(message_ids, default=0),
        "has_more": len(messages) >= WORKBENCH_MESSAGE_LIMIT,
    }
)
```

不得给 `/conversation-detail` 增加查询参数；后续补拉只走消息接口。

- [ ] **Step 8：运行消息协议与隔离绿灯**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py -k "cursor or late_insert or messages_are_sorted or conversation_detail" -q
pytest tests/test_douyin_workbench_tenant_isolation_r2.py -k "event_cursor or nonexistent_conversation or null_merchant" -q
```

Expected: 全部 PASS；合法空页 `200`、不存在会话 `404`、坏事件推进水位、跨商户事件不可见。

- [ ] **Step 9：提交共享事件页实现**

```powershell
git add app/services/douyin_workbench_conversation_service.py tests/test_douyin_workbench_conversations.py tests/test_douyin_workbench_tenant_isolation_r2.py
git commit --only app/services/douyin_workbench_conversation_service.py tests/test_douyin_workbench_conversations.py tests/test_douyin_workbench_tenant_isolation_r2.py -m "功能：实现抖音会话消息事件游标"
```

### Task 3：增加账号水位与会话摘要增量

**Files:**
- Modify: `app/services/douyin_workbench_conversation_service.py`
- Modify: `app/routers/integrations.py`
- Modify: `app/routers/douyin_accounts.py`
- Test: `tests/test_douyin_workbench_conversations.py`
- Test: `tests/test_douyin_accounts_router.py`
- Test: `tests/test_douyin_workbench_tenant_isolation_r2.py`

- [ ] **Step 1：写账号级 latest_event_id 隔离红灯测试**

在 `tests/test_douyin_accounts_router.py` 增加：

```python
def test_list_accounts_latest_event_id_uses_current_merchant_non_duplicate_events_only():
    _insert_account(open_id="account-current", merchant_id="merchant-1")
    first = _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-current",
        customer_open_id="customer-current",
        event_key="latest-current",
        merchant_id="merchant-1",
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-current",
        customer_open_id="customer-duplicate",
        event_key="latest-duplicate",
        merchant_id="merchant-1",
        is_duplicate=True,
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-current",
        customer_open_id="customer-null",
        event_key="latest-null",
        merchant_id=None,
    )
    _insert_webhook_event(
        event="im_receive_msg",
        account_open_id="account-current",
        customer_open_id="customer-other",
        event_key="latest-other",
        merchant_id="merchant-2",
    )

    item = _client(_context("merchant-1")).get("/integrations/douyin/accounts").json()["data"]["items"][0]
    assert item["latest_event_id"] == first.id
```

另加无事件账号断言 `latest_event_id == 0`。先运行两个用例，Expected: FAIL，字段不存在。

- [ ] **Step 2：写会话摘要水位与增量页红灯测试**

```python
def test_conversation_incremental_page_returns_changed_summaries_and_authoritative_unread():
    account = "account_conversation_delta"
    first = _insert_event(
        account_open_id=account,
        open_id="customer-a",
        conversation_short_id="conv-delta-a",
        event_key="conversation-delta-a-1",
    )
    _insert_event(
        account_open_id=account,
        open_id="customer-b",
        conversation_short_id="conv-delta-b",
        event_key="conversation-delta-b-1",
    )
    changed = _insert_event(
        account_open_id=account,
        open_id="customer-a",
        conversation_short_id="conv-delta-a",
        event_key="conversation-delta-a-2",
    )
    data = _client().get(
        f"/integrations/douyin/accounts/{account}/conversations",
        params={"account_open_id": account, "after_event_id": first, "limit": 1},
    ).json()

    assert [item["conversation_key"] for item in data["items"]] == ["conv-delta-b"]
    assert data["items"][0]["latest_event_id"] > first
    assert data["next_after_event_id"] > first
    assert data["latest_event_id"] == changed
    assert data["account_unread_count"] == 3
    assert data["has_more"] is True
```

再增加空增量断言：`items=[]`、`next_after_event_id` 保持请求值、`has_more=false`；增加 `after_event_id` 与 `event_limit` 同时传入返回 `422`，`limit=501` 返回 `422`。

- [ ] **Step 3：抽取单会话摘要构造器并给旧列表补 stable latest_event_id**

从 `list_account_conversations()` 的 `items.append({...})` 抽成：

```python
def _conversation_summary_item(
    db: Session,
    *,
    account_open_id: str,
    messages: list[WorkbenchMessage],
    read_state: DouyinConversationReadState | None,
    merchant_id: str | None,
) -> dict[str, Any]:
    ordered = _sort_messages(messages)
    first = ordered[0]
    latest = ordered[-1]
    return {
        "id": first.conversation_key,
        "conversation_id": first.conversation_key,
        "conversation_key": first.conversation_key,
        "conversation_short_id": first.conversation_short_id,
        "account_id": account_open_id,
        "account_open_id": first.account_open_id,
        "open_id": first.open_id,
        "nickname": first.nick_name or first.open_id,
        "avatar": first.avatar,
        "last_message": latest.content,
        "last_message_at": latest.created_at,
        "latest_event_id": max(item.event_id for item in ordered),
        "unread_count": _unread_count_for_messages(ordered, read_state),
        "lead_status": _lead_status(ordered),
        "tags": build_conversation_tags(db, ordered, merchant_id=merchant_id),
    }
```

旧无游标列表只改为调用该函数，其 `event_limit/has_more/next_event_limit` 行为保持不变。

同时给无游标响应补充兼容扩展字段，旧字段和值不变：

```python
latest_event_id = _latest_visible_event_id(
    db,
    account_open_id=account_open_id,
    conversation_key=None,
    merchant_id=merchant_id,
)
return {
    "items": items,
    "event_limit": resolved_limit,
    "latest_event_id": latest_event_id,
    "next_after_event_id": latest_event_id,
    "account_unread_count": get_account_unread_counts(
        db,
        account_open_ids=[account_open_id],
        merchant_id=merchant_id,
    ).get(account_open_id, 0),
    "has_more": has_more,
    "next_event_limit": min(
        resolved_limit + WORKBENCH_CONVERSATION_EVENT_LIMIT,
        WORKBENCH_CONVERSATION_MAX_EVENT_LIMIT,
    ) if has_more else None,
}
```

无游标和增量模式都使用权威 `get_account_unread_counts()`；不得从可能截断的会话页或增量页求和。

- [ ] **Step 4：实现账号级水位批量查询**

在现有 SQLAlchemy 导入中增加 `case` 和 `func`，不新增依赖：

```python
from sqlalchemy import Text, case, cast, func, or_, select
```

```python
def get_account_latest_event_ids(
    db: Session,
    *,
    account_open_ids: list[str],
    merchant_id: str,
) -> dict[str, int]:
    requested = {str(item) for item in account_open_ids if item}
    result = {item: 0 for item in requested}
    if not requested:
        return result
    rows = db.execute(
        select(
            case(
                (DouyinWebhookEvent.event == "im_receive_msg", DouyinWebhookEvent.to_user_id),
                else_=DouyinWebhookEvent.from_user_id,
            ).label("account_open_id"),
            func.max(DouyinWebhookEvent.id).label("latest_event_id"),
        )
        .where(DouyinWebhookEvent.merchant_id == merchant_id)
        .where(DouyinWebhookEvent.event.in_(PRIVATE_MESSAGE_EVENTS))
        .where(DouyinWebhookEvent.is_duplicate.is_(False))
        .where(
            or_(
                DouyinWebhookEvent.to_user_id.in_(requested),
                DouyinWebhookEvent.from_user_id.in_(requested),
            )
        )
        .group_by("account_open_id")
    ).all()
    db.rollback()
    for account_open_id, latest_event_id in rows:
        if account_open_id in requested:
            result[str(account_open_id)] = int(latest_event_id or 0)
    return result
```

在 `douyin_accounts.py` 与 `get_account_unread_counts()` 并列调用，并给每个有效绑定账号返回 `latest_event_id`。不得从 event fallback 账号扩展授权范围。

- [ ] **Step 5：实现有界会话增量页**

扩展 `list_account_conversations()` 参数：

```python
after_event_id: int | None = None,
limit: int | None = None,
```

有 `after_event_id` 时：

1. 调 `_query_message_row_page(... conversation_key=None, after_event_id=..., limit=resolved_limit)`。
2. 从本页可解析消息收集唯一 `conversation_key`；游标仍以全部扫描行 ID 推进。
3. 每个变化会话使用 `_load_messages(... conversation_key=key, limit=WORKBENCH_MESSAGE_LIMIT)` 取当前摘要，复用 `_conversation_summary_item()`。
4. `latest_event_id` 调 `_latest_visible_event_id(... conversation_key=None)`。
5. `account_unread_count` 调 `get_account_unread_counts()`，不从不完整增量页推算。

返回结构：

```python
return {
    "items": items,
    "latest_event_id": latest_event_id,
    "next_after_event_id": max(page.scanned_event_ids, default=after_event_id),
    "account_unread_count": get_account_unread_counts(
        db,
        account_open_ids=[account_open_id],
        merchant_id=merchant_id,
    ).get(account_open_id, 0),
    "has_more": page.has_more,
}
```

坏事件不得形成摘要，但必须推进 `next_after_event_id`。增量路径禁止调用逐步扩大的 `event_limit`。

- [ ] **Step 6：扩展会话路由参数并拒绝旧窗口/新游标混用**

`get_douyin_account_conversations()` 参数改为：

```python
event_limit: int | None = Query(default=None),
after_event_id: int | None = Query(default=None, ge=0),
limit: int | None = Query(default=None, ge=1, le=500),
```

若 `after_event_id is not None and event_limit is not None`，返回 `422` 和稳定错误码 `DOUYIN_CONVERSATION_CURSOR_CONFLICT`；否则把新参数透传服务。

- [ ] **Step 7：运行 A1～A11 定向绿灯**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py -q
pytest tests/test_douyin_accounts_router.py -q
pytest tests/test_douyin_workbench_tenant_isolation_r2.py -q
```

Expected: 全部 PASS；旧无游标测试不需改期望，新增字段只做兼容扩展。

- [ ] **Step 8：提交账号和会话摘要增量**

```powershell
git add app/services/douyin_workbench_conversation_service.py app/routers/integrations.py app/routers/douyin_accounts.py tests/test_douyin_workbench_conversations.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_tenant_isolation_r2.py
git commit --only app/services/douyin_workbench_conversation_service.py app/routers/integrations.py app/routers/douyin_accounts.py tests/test_douyin_workbench_conversations.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_tenant_isolation_r2.py -m "功能：增加抖音账号与会话增量水位"
```

### Task 4：执行 PostgreSQL 有界查询与索引决策门禁

**Files:**
- Create: `tests/test_9000_postgres_douyin_conversation_incremental.py`
- Modify only if a query bug is proven: `app/services/douyin_workbench_conversation_service.py`

- [ ] **Step 1：建立独立 PostgreSQL URL 安全门和清理夹具**

新测试文件必须复制严格边界，不复用 worker 宽松校验器：

```python
import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _pg_url() -> str:
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    parsed = make_url(raw)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail(f"SMOKE_DATABASE_URL 必须使用 postgresql+psycopg，实际: {parsed.drivername}")
    if parsed.host not in ("127.0.0.1", "localhost"):
        pytest.fail(f"SMOKE_DATABASE_URL host 必须为 127.0.0.1 或 localhost，实际: {parsed.host}")
    if parsed.port != 5432:
        pytest.fail(f"SMOKE_DATABASE_URL port 必须为 5432，实际: {parsed.port}")
    if parsed.database != "auto_wechat_outbox_test":
        pytest.fail(f"SMOKE_DATABASE_URL database 必须为 auto_wechat_outbox_test，实际: {parsed.database}")
    if parsed.query:
        pytest.fail("SMOKE_DATABASE_URL 禁止 query")
    if "#" in raw:
        pytest.fail("SMOKE_DATABASE_URL 禁止 fragment")
    return raw


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_pg_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
    yield engine
    engine.dispose()


@pytest.fixture
def pg_namespace(pg_engine):
    namespace = f"conversation_incremental_{uuid.uuid4().hex}"
    try:
        yield namespace
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
                {"prefix": f"{namespace}%"},
            )
            conn.execute(
                text("DELETE FROM douyin_authorized_accounts WHERE open_id LIKE :prefix"),
                {"prefix": f"{namespace}%"},
            )
        with pg_engine.connect() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
                {"prefix": f"{namespace}%"},
            ).scalar_one() == 0
```

- [ ] **Step 2：一次性构造至少 5 万行独立 namespace 数据**

使用 PostgreSQL `generate_series`，不要 Python 单行循环：

```python
def _seed_plan_rows(pg_engine, namespace: str) -> tuple[str, str]:
    target_account = f"{namespace}_target"
    noise_account = f"{namespace}_noise"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO douyin_authorized_accounts "
                "(main_account_id, open_id, account_name, bind_status, merchant_id, created_at, updated_at) "
                "VALUES (1, :account, :account, 1, :merchant, now(), now())"
            ),
            {"account": target_account, "merchant": namespace},
        )
        conn.execute(
            text(
                "INSERT INTO douyin_webhook_events "
                "(event, from_user_id, to_user_id, event_key, is_duplicate, raw_body, "
                "parsed_content_json, merchant_id, created_at) "
                "SELECT 'im_receive_msg', :customer_prefix || gs::text, "
                "CASE WHEN gs % 100 = 0 THEN :target ELSE :noise END, "
                ":event_prefix || gs::text, false, "
                "jsonb_build_object('event', 'im_receive_msg', 'content', "
                "jsonb_build_object('text', 'plan', 'account_open_id', "
                "CASE WHEN gs % 100 = 0 THEN :target ELSE :noise END, "
                "'open_id', :customer_prefix || gs::text)), "
                "jsonb_build_object('text', 'plan'), :merchant, now() "
                "FROM generate_series(1, 50000) AS gs"
            ),
            {
                "customer_prefix": f"{namespace}_customer_",
                "target": target_account,
                "noise": noise_account,
                "event_prefix": f"{namespace}_event_",
                "merchant": namespace,
            },
        )
    return target_account, noise_account
```

目标账号恰好 500 行并均匀分布在 50000 行 namespace 中，避免“目标行都在开头”导致执行计划门禁假阳性；不得污染其他任务数据。

- [ ] **Step 3：记录真实服务查询的 EXPLAIN JSON**

在测试文件导入模型、PostgreSQL 方言和真实服务查询构造器：

```python
from sqlalchemy.dialects import postgresql

from app.models import DouyinWebhookEvent
from app.services.douyin_workbench_conversation_service import (
    PRIVATE_MESSAGE_EVENTS,
    _build_message_rows_statement,
)
```

测试对真实构造器生成的 `after_event_id` 查询增加 `id > cursor`、`ORDER BY id ASC`、`LIMIT 101`；从目标账号最小事件 ID 建立游标，并用 PostgreSQL 方言安全地把本测试生成的值编译为字面量：

```python
with pg_engine.connect() as conn:
    cursor = conn.execute(
        text(
            "SELECT min(id) FROM douyin_webhook_events "
            "WHERE merchant_id = :merchant AND to_user_id = :account"
        ),
        {"merchant": namespace, "account": target_account},
    ).scalar_one()
    stmt = (
        _build_message_rows_statement(
            account_open_id=target_account,
            account_open_ids=None,
            conversation_key=None,
            events=PRIVATE_MESSAGE_EVENTS,
            lookback_days=None,
            merchant_id=namespace,
        )
        .where(DouyinWebhookEvent.id > int(cursor or 0))
        .order_by(DouyinWebhookEvent.id.asc())
        .limit(101)
    )
    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    raw_plan = conn.execute(
        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")
    ).scalar_one()
    plan = raw_plan[0]
```

递归检查计划节点：

```python
def _plan_nodes(node: dict):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


nodes = list(_plan_nodes(plan["Plan"]))
event_nodes = [node for node in nodes if node.get("Relation Name") == "douyin_webhook_events"]
assert event_nodes
assert all(node.get("Node Type") != "Seq Scan" for node in event_nodes)
assert max(int(node.get("Rows Removed by Filter", 0)) for node in event_nodes) <= 5000
```

测试输出用 `json.dumps(plan, ensure_ascii=False)` 写入 pytest 失败信息即可，不在仓库生成计划产物文件。

- [ ] **Step 4：运行 PostgreSQL 专项并执行硬停止裁决**

Run:

```powershell
pytest tests/test_9000_postgres_douyin_conversation_incremental.py -q -rs
```

Expected: 专用库已设置时 `0 failed, 0 skipped`，Alembic head=`0016`，事件表无 `Seq Scan`，`Rows Removed by Filter <= 5000`，清理后残留 0。

如果出现 `Seq Scan` 或过滤移除行超过 5000：

1. 不修改 `migrations/**`。
2. 不提交 Task 4 的失败测试或半成品查询调整。
3. 回传 `REPAIR_REQUIRED`，附原始节点、行数和 SQL 摘要。
4. 申请独立 `0017` 索引迁移任务，候选索引仅登记 `(merchant_id, to_user_id, id)`、`(merchant_id, from_user_id, id)`、`(merchant_id, conversation_short_id, id)`。

- [ ] **Step 5：门禁通过后提交 PostgreSQL 专项**

```powershell
git add tests/test_9000_postgres_douyin_conversation_incremental.py app/services/douyin_workbench_conversation_service.py
git commit --only tests/test_9000_postgres_douyin_conversation_incremental.py app/services/douyin_workbench_conversation_service.py -m "测试：增加抖音会话增量查询计划门禁"
```

### Task 5：扩展前端 API 类型与请求合同

**Files:**
- Modify: `frontend/src/api/douyinAiCsClient.ts`
- Test: `tests/test_douyin_workbench_conversations.py`

- [ ] **Step 1：先写前端 API 静态红灯合同**

在 `tests/test_douyin_workbench_conversations.py` 增加：

```python
def test_frontend_incremental_api_exposes_numeric_event_cursor_contract():
    source = Path("frontend/src/api/douyinAiCsClient.ts").read_text(encoding="utf-8")

    assert "latest_event_id?: number" in source
    assert "next_after_event_id?: number" in source
    assert "next_before_event_id?: number" in source
    assert "account_unread_count?: number" in source
    assert "after_event_id?: number" in source
    assert "before_event_id?: number" in source
    assert "event_limit: params?.event_limit" in source
    assert "after_event_id: params?.after_event_id" in source
    assert "before_event_id: params?.before_event_id" in source
```

文件顶部补 `from pathlib import Path`。运行该用例，Expected: FAIL，缺少游标字段。

- [ ] **Step 2：扩展账号、会话和消息响应类型**

原位增加字段：

```typescript
export interface DouyinAccountItem {
  // 保留现有字段
  latest_event_id?: number;
}

export interface DouyinConversationItem {
  // 保留现有字段
  latest_event_id?: number;
}

export interface DouyinConversationListResponse {
  items: DouyinConversationItem[];
  event_limit?: number;
  latest_event_id?: number;
  next_after_event_id?: number;
  account_unread_count?: number;
  has_more?: boolean;
  next_event_limit?: number | null;
}

export interface DouyinMessageListResponse {
  items: DouyinMessageItem[];
  latest_event_id?: number;
  next_after_event_id?: number;
  next_before_event_id?: number;
  has_more?: boolean;
}
```

`normalizeDouyinAccount()` 把水位归一为非负整数：

```typescript
latest_event_id: Math.max(0, Number(item.latest_event_id) || 0),
```

- [ ] **Step 3：扩展请求参数但保留旧调用**

```typescript
export async function getDouyinAccountConversations(
  accountId: string | number,
  params?: {
    account_open_id?: string;
    event_limit?: number;
    after_event_id?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<DouyinConversationListResponse> {
  return apiClient.get(
    `/integrations/douyin/accounts/${encodeURIComponent(String(accountId))}/conversations`,
    {
      params: {
        account_open_id: params?.account_open_id,
        event_limit: params?.event_limit,
        after_event_id: params?.after_event_id,
        limit: params?.limit,
      },
      signal: params?.signal,
    },
  ) as unknown as Promise<DouyinConversationListResponse>;
}


export async function getDouyinConversationMessages(
  conversationId: string | number,
  params?: {
    account_open_id?: string;
    after_event_id?: number;
    before_event_id?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<DouyinMessageListResponse> {
  return apiClient.get(
    "/integrations/douyin/conversation-messages",
    {
      params: {
        conversation_key: String(conversationId),
        account_open_id: params?.account_open_id,
        after_event_id: params?.after_event_id,
        before_event_id: params?.before_event_id,
        limit: params?.limit,
      },
      signal: params?.signal,
    },
  ) as unknown as Promise<DouyinMessageListResponse>;
}
```

不得删除 `event_limit`，旧“加载更早会话”入口在本任务内保持兼容；增量同步不会使用它。

- [ ] **Step 4：运行静态合同与 TypeScript 编译**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py::test_frontend_incremental_api_exposes_numeric_event_cursor_contract -q
cd frontend
npx.cmd tsc --noEmit -p tsconfig.app.json --tsBuildInfoFile $env:TEMP\auto_wechat_incremental_api.tsbuildinfo
```

Expected: 测试 PASS，TypeScript 退出码 0。

- [ ] **Step 5：提交 API 合同**

```powershell
git add frontend/src/api/douyinAiCsClient.ts tests/test_douyin_workbench_conversations.py
git commit --only frontend/src/api/douyinAiCsClient.ts tests/test_douyin_workbench_conversations.py -m "功能：扩展抖音会话增量接口类型"
```

### Task 6：增加纯 TypeScript 增量辅助模块和无依赖行为检查

**Files:**
- Create: `frontend/src/features/douyin-cs/douyinConversationIncremental.ts`
- Create: `frontend/scripts/check-douyin-workbench-incremental.mjs`
- Modify: `frontend/package.json`

- [ ] **Step 1：先创建行为检查脚本并确认模块缺失红灯**

创建 `frontend/scripts/check-douyin-workbench-incremental.mjs`；脚本使用已安装的 TypeScript 编译器把纯模块转译到系统临时目录，不向仓库写生成物：

```javascript
import assert from "node:assert/strict";
import { readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const sourcePath = new URL("../src/features/douyin-cs/douyinConversationIncremental.ts", import.meta.url);
const outputPath = join(tmpdir(), `douyin-conversation-incremental-${process.pid}.mjs`);

try {
  const source = await readFile(sourcePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      strict: true,
    },
  }).outputText;
  await writeFile(outputPath, output, "utf8");
  const mod = await import(`${pathToFileURL(outputPath).href}?v=${Date.now()}`);

  const oldMessage = { id: 10, raw_event_id: 10, created_at: "2026-07-28T12:00:00Z", content: "新时间" };
  const lateMessage = { id: 11, raw_event_id: 11, created_at: "2026-07-28T11:00:00Z", content: "迟到入库" };
  const merged = mod.mergeMessagesByEventId([oldMessage], [oldMessage, lateMessage]);
  assert.deepEqual(merged.map((item) => item.raw_event_id), [11, 10]);
  assert.equal(mod.advanceEventCursor(20, 19), 20);
  assert.equal(mod.advanceEventCursor(20, 21), 21);
  assert.equal(mod.retryDelayMs(1, 0), 8000);
  assert.equal(mod.retryDelayMs(2, 0), 16000);
  assert.equal(mod.retryDelayMs(8, 0), 60000);

  let active = 0;
  let maxActive = 0;
  await mod.runWithConcurrency([1, 2, 3, 4, 5], 3, async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
  });
  assert.equal(maxActive, 3);

  let runs = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const trigger = mod.createCoalescedRunner(async () => {
    runs += 1;
    if (runs === 1) await gate;
  });
  const first = trigger();
  const second = trigger();
  const third = trigger();
  release();
  await Promise.all([first, second, third]);
  assert.equal(runs, 2);

  console.log("DOUYIN_WORKBENCH_INCREMENTAL_CHECK_OK");
} finally {
  await rm(outputPath, { force: true });
}
```

Run:

```powershell
cd frontend
node scripts/check-douyin-workbench-incremental.mjs
```

Expected: FAIL，源模块不存在。

- [ ] **Step 2：实现消息与会话的事件 ID 合并纯函数**

创建 `frontend/src/features/douyin-cs/douyinConversationIncremental.ts`：

```typescript
export interface EventMessageLike {
  id: string | number;
  raw_event_id?: number;
  created_at: string;
}

export interface ConversationSummaryLike {
  id: string | number;
  conversation_key?: string;
  last_message_at: string;
}

function eventId(item: EventMessageLike): number {
  return Number(item.raw_event_id ?? item.id) || 0;
}

function timeValue(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function mergeMessagesByEventId<T extends EventMessageLike>(current: T[], incoming: T[]): T[] {
  const merged = new Map<string, T>();
  for (const item of [...current, ...incoming]) merged.set(String(eventId(item)), item);
  return [...merged.values()].sort(
    (left, right) => timeValue(left.created_at) - timeValue(right.created_at) || eventId(left) - eventId(right),
  );
}

export function mergeConversationSummaries<T extends ConversationSummaryLike>(current: T[], incoming: T[]): T[] {
  const merged = new Map(current.map((item) => [String(item.conversation_key ?? item.id), item]));
  for (const item of incoming) merged.set(String(item.conversation_key ?? item.id), item);
  return [...merged.values()].sort(
    (left, right) => timeValue(right.last_message_at) - timeValue(left.last_message_at),
  );
}

export function advanceEventCursor(current: number, candidate: number | null | undefined): number {
  return Math.max(current, Number(candidate) || 0);
}
```

- [ ] **Step 3：实现退避、有限并发和合并触发纯函数**

继续追加同一文件：

```typescript
export function retryDelayMs(failureCount: number, jitterMs = Math.floor(Math.random() * 1001) - 500): number {
  const delays = [8000, 16000, 32000, 60000];
  const base = delays[Math.min(Math.max(failureCount, 1), delays.length) - 1];
  return Math.max(0, base + Math.max(-1000, Math.min(1000, jitterMs)));
}

export async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(Math.max(1, limit), queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      if (item !== undefined) await worker(item);
    }
  });
  await Promise.all(workers);
}

export function createCoalescedRunner(run: () => Promise<void>): () => Promise<void> {
  let active: Promise<void> | null = null;
  let pending = false;
  return async () => {
    if (active) {
      pending = true;
      return active;
    }
    active = (async () => {
      do {
        pending = false;
        await run();
      } while (pending);
    })();
    try {
      await active;
    } finally {
      active = null;
    }
  };
}
```

- [ ] **Step 4：增加脚本入口并运行绿灯**

在 `frontend/package.json` 的 scripts 中增加：

```json
"douyin-workbench-incremental:check": "node scripts/check-douyin-workbench-incremental.mjs"
```

Run:

```powershell
cd frontend
npm.cmd run douyin-workbench-incremental:check
npx.cmd tsc --noEmit -p tsconfig.app.json --tsBuildInfoFile $env:TEMP\auto_wechat_incremental_helpers.tsbuildinfo
```

Expected: 输出 `DOUYIN_WORKBENCH_INCREMENTAL_CHECK_OK`，TypeScript 退出码 0。

- [ ] **Step 5：提交纯函数和行为检查**

```powershell
git add frontend/src/features/douyin-cs/douyinConversationIncremental.ts frontend/scripts/check-douyin-workbench-incremental.mjs frontend/package.json
git commit --only frontend/src/features/douyin-cs/douyinConversationIncremental.ts frontend/scripts/check-douyin-workbench-incremental.mjs frontend/package.json -m "测试：增加抖音会话增量行为检查"
```

### Task 7：接入全账号同步、恢复触发与历史消息分页

**Files:**
- Modify: `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
- Modify: `tests/test_douyin_workbench_conversations.py`
- Test: `frontend/scripts/check-douyin-workbench-incremental.mjs`

- [ ] **Step 1：写页面静态合同红灯测试**

在 `tests/test_douyin_workbench_conversations.py` 增加：

```python
def test_frontend_workbench_uses_one_coalesced_all_account_sync_entry():
    source = Path("frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx").read_text(encoding="utf-8")

    assert "createCoalescedRunner" in source
    assert "runWithConcurrency(activeAccounts, 3" in source
    assert "after_event_id: cursor" in source
    assert 'window.addEventListener("focus"' in source
    assert 'window.addEventListener("online"' in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert "window.setInterval" in source
    assert "8000" in source
    assert "EventSource" not in source
    assert "WebSocket" not in source


def test_frontend_workbench_incremental_read_and_history_safety_contracts():
    source = Path("frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx").read_text(encoding="utf-8")

    assert "mergeMessagesByEventId" in source
    assert "before_event_id" in source
    assert "scrollHeight - previousScrollHeight" in source
    assert "detailSuccessCredentialRef.current" in source
    assert "selectedAccountOpenIdRef.current" in source
    assert "selectedConversationIdRef.current" in source
    assert "lastSuccessfulSyncAt" in source
```

运行两个用例，Expected: FAIL，恢复监听和全账号入口尚不存在。

- [ ] **Step 2：扩展查询缓存与同步状态，不写浏览器持久存储**

导入辅助函数及消息 API：

```typescript
import {
  advanceEventCursor,
  createCoalescedRunner,
  mergeConversationSummaries,
  mergeMessagesByEventId,
  retryDelayMs,
  runWithConcurrency,
} from "../douyinConversationIncremental";
```

从 API 导入 `getDouyinConversationMessages`。新增状态类型：

```typescript
interface AccountIncrementalState {
  latestEventId: number;
  lastSuccessAt: number | null;
  failureCount: number;
  nextRetryAt: number;
  error: string | null;
}

interface ConversationIncrementalState {
  newestEventId: number;
  oldestEventId: number;
  hasMoreBefore: boolean;
  incrementalError: string | null;
  historyError: string | null;
}
```

给 `WorkbenchPageCache` 增加：

```typescript
accountIncremental: Record<string, AccountIncrementalState>;
conversationIncremental: Record<string, ConversationIncrementalState>;
lastSuccessfulSyncAt: number | null;
```

组件内增加对应 refs/state：

```typescript
const accountIncrementalRef = useRef<Record<string, AccountIncrementalState>>(
  cachedWorkbench?.accountIncremental || {},
);
const conversationIncrementalRef = useRef<Record<string, ConversationIncrementalState>>(
  cachedWorkbench?.conversationIncremental || {},
);
const lastSuccessfulSyncAtRef = useRef<number | null>(cachedWorkbench?.lastSuccessfulSyncAt || null);
const [lastSuccessfulSyncAt, setLastSuccessfulSyncAt] = useState<number | null>(
  cachedWorkbench?.lastSuccessfulSyncAt || null,
);
```

现有 `queryClient.setQueryData<WorkbenchPageCache>()` 调用同步增加：

```typescript
accountIncremental: accountIncrementalRef.current,
conversationIncremental: conversationIncrementalRef.current,
lastSuccessfulSyncAt,
```

这些状态只进入现有 TanStack Query 页面缓存，不调用 `localStorage` 或 `sessionStorage`。

同时增加两个只驻留内存的调度标记：

```typescript
const forceNextSyncRef = useRef(false);
const syncContinuationRequestedRef = useRef(false);
```

- [ ] **Step 3：账号列表成功后建立所有有效账号基线**

在 `loadAccounts()` 成功分支中，在更新 `accountsCacheRef` 后执行：

```typescript
for (const account of mapped) {
  const accountOpenId = account.account_open_id;
  const current = accountIncrementalRef.current[accountOpenId];
  accountIncrementalRef.current[accountOpenId] = current || {
    latestEventId: Math.max(0, Number(account.latest_event_id) || 0),
    lastSuccessAt: null,
    failureCount: 0,
    nextRetryAt: 0,
    error: null,
  };
}
```

账号列表失败时不得覆盖既有状态、缓存或红点。

- [ ] **Step 4：详情成功后建立当前会话的新旧水位**

在 `loadConversationDetail()` 成功分支、写入消息缓存后，使用详情扩展字段：

```typescript
conversationIncrementalRef.current[cacheKey] = {
  newestEventId: Math.max(0, Number(detail.messages.next_after_event_id) || 0),
  oldestEventId: Math.max(0, Number(detail.messages.next_before_event_id) || 0),
  hasMoreBefore: Boolean(detail.messages.has_more),
  incrementalError: null,
  historyError: null,
};
```

保留现有 `detailSuccessCredentialRef`；只有详情请求仍匹配账号、会话和请求序号，且消息已写入 React 状态后，才生成 mark-read 成功凭据。

- [ ] **Step 5：实现当前会话消息补拉，迟到响应不得覆盖选择**

新增 callback：

```typescript
const syncSelectedConversationMessages = useCallback(async (
  accountOpenId: string,
  conversationId: string | number,
) => {
  const cacheKey = conversationCacheKey(accountOpenId, conversationId);
  const state = conversationIncrementalRef.current[cacheKey];
  if (!cacheKey || !state) return;
  const requestSeq = detailRequestSeqRef.current + 1;
  detailRequestSeqRef.current = requestSeq;
  const data = await getDouyinConversationMessages(conversationId, {
    account_open_id: accountOpenId,
    after_event_id: state.newestEventId,
    limit: 100,
  });
  if (
    detailRequestSeqRef.current !== requestSeq
    || selectedAccountOpenIdRef.current !== accountOpenId
    || selectedConversationIdRef.current !== conversationId
  ) return;
  const merged = mergeMessagesByEventId(messagesCacheRef.current[cacheKey] || [], data.items);
  messagesCacheRef.current[cacheKey] = merged;
  conversationIncrementalRef.current[cacheKey] = {
    ...state,
    newestEventId: advanceEventCursor(state.newestEventId, data.next_after_event_id),
    incrementalError: null,
  };
  setMessages(merged);
  const maxEventId = merged.reduce(
    (maximum, item) => Math.max(maximum, Number(item.raw_event_id ?? item.id) || 0),
    0,
  );
  detailSuccessCredentialRef.current = {
    account_open_id: accountOpenId,
    conversation_id: conversationId,
    request_seq: requestSeq,
    max_event_id: maxEventId || null,
  };
  setDetailSuccessSeq((current) => current + 1);
}, []);
```

若消息请求失败，只写 `incrementalError`，不得推进 `newestEventId`、清缓存或生成已读凭据。

- [ ] **Step 6：实现单账号会话增量，多页有限预算**

新增 `syncAccountConversations(account, forceRetry)`，每轮最多 5 页，每页 `limit=100`；恢复事件只允许越过退避一次：

```typescript
const syncAccountConversations = useCallback(async (account: DouyinAccountItem, forceRetry: boolean) => {
  const accountOpenId = account.account_open_id;
  const state = accountIncrementalRef.current[accountOpenId];
  if (!state || (!forceRetry && Date.now() < state.nextRetryAt)) return false;
  let cursor = state.latestEventId;
  try {
    for (let page = 0; page < 5; page += 1) {
      const data = await getDouyinAccountConversations(account.id, {
        account_open_id: accountOpenId,
        after_event_id: cursor,
        limit: 100,
      });
      const merged = mergeConversationSummaries(
        conversationsCacheRef.current[accountOpenId] || [],
        data.items,
      );
      conversationsCacheRef.current[accountOpenId] = merged;
      cursor = advanceEventCursor(cursor, data.next_after_event_id);
      const currentState = accountIncrementalRef.current[accountOpenId] || state;
      accountIncrementalRef.current[accountOpenId] = {
        ...currentState,
        latestEventId: cursor,
        error: null,
      };
      setAccounts((current) => current.map((item) =>
        item.account_open_id === accountOpenId
          ? { ...item, unread_count: Number(data.account_unread_count ?? item.unread_count ?? 0), latest_event_id: cursor }
          : item,
      ));
      if (selectedAccountOpenIdRef.current === accountOpenId) setConversations(merged);
      const currentConversationId = selectedConversationIdRef.current;
      if (
        currentConversationId !== null
        && selectedAccountOpenIdRef.current === accountOpenId
        && data.items.some((item) => item.id === currentConversationId)
      ) {
        await syncSelectedConversationMessages(accountOpenId, currentConversationId);
      }
      if (!data.has_more) {
        const completedAt = Date.now();
        accountIncrementalRef.current[accountOpenId] = {
          ...(accountIncrementalRef.current[accountOpenId] || state),
          latestEventId: cursor,
          lastSuccessAt: completedAt,
          failureCount: 0,
          nextRetryAt: 0,
          error: null,
        };
        return true;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    }
    syncContinuationRequestedRef.current = true;
    return false;
  } catch (err) {
    const currentState = accountIncrementalRef.current[accountOpenId] || state;
    const failures = currentState.failureCount + 1;
    accountIncrementalRef.current[accountOpenId] = {
      ...currentState,
      latestEventId: cursor,
      failureCount: failures,
      nextRetryAt: Date.now() + retryDelayMs(failures),
      error: userFacingError(err, "会话增量同步失败"),
    };
    return false;
  }
}, [syncSelectedConversationMessages]);
```

若 5 页预算耗尽且仍 `has_more=true`，返回 `false` 并通过合并触发器排队下一轮；已经成功扫描的页可保留前进水位。

- [ ] **Step 7：用唯一入口同步全部有效授权账号并正确更新时间**

```typescript
const syncAllAccountsRef = useRef<() => Promise<void>>(async () => undefined);

const syncAllAccountsRun = useCallback(async () => {
  const activeAccounts = accountsCacheRef.current.filter(
    (account) => account.is_authorized !== false && account.bind_status !== 0,
  );
  if (!activeAccounts.length) return;
  const forceRetry = forceNextSyncRef.current;
  forceNextSyncRef.current = false;
  syncContinuationRequestedRef.current = false;
  const results = new Map<string, boolean>();
  await runWithConcurrency(activeAccounts, 3, async (account) => {
    results.set(account.account_open_id, await syncAccountConversations(account, forceRetry));
  });
  if (activeAccounts.every((account) => results.get(account.account_open_id) === true)) {
    const completedAt = Date.now();
    lastSuccessfulSyncAtRef.current = completedAt;
    setLastSuccessfulSyncAt(completedAt);
  }
  if (syncContinuationRequestedRef.current) {
    window.setTimeout(() => { void syncAllAccountsRef.current(); }, 0);
  }
}, [syncAccountConversations]);

useEffect(() => {
  syncAllAccountsRef.current = createCoalescedRunner(syncAllAccountsRun);
}, [syncAllAccountsRun]);
```

账号单独成功更新账号成功时间；页面级时间只有全部应同步账号成功才更新。

- [ ] **Step 8：替换旧当前账号整批轮询并增加恢复触发**

删除原来只对 `selectedAccount` 调 `loadConversations()` 的 8 秒 poll effect，保留自动回复状态的独立 4 秒 effect。新增：

```typescript
useEffect(() => {
  const trigger = () => { void syncAllAccountsRef.current(); };
  const onVisibilityChange = () => {
    if (document.visibilityState === "visible") {
      forceNextSyncRef.current = true;
      trigger();
    }
  };
  const onFocus = () => {
    forceNextSyncRef.current = true;
    trigger();
  };
  const onOnline = () => {
    forceNextSyncRef.current = true;
    trigger();
  };
  const timer = window.setInterval(trigger, 8000);
  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("focus", onFocus);
  window.addEventListener("online", onOnline);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("focus", onFocus);
    window.removeEventListener("online", onOnline);
  };
}, []);
```

多个恢复事件同时触发时由 `createCoalescedRunner()` 合并；不得再保留第二个工作台会话同步定时器。

- [ ] **Step 9：实现历史消息分页和滚动锚点**

增加 `messageListRef`、`loadingOlderMessages` 和 callback：

```typescript
const loadOlderMessages = useCallback(async () => {
  const accountOpenId = selectedAccountOpenIdRef.current;
  const conversationId = selectedConversationIdRef.current;
  const cacheKey = conversationCacheKey(accountOpenId, conversationId);
  const state = conversationIncrementalRef.current[cacheKey];
  const container = messageListRef.current;
  if (!accountOpenId || conversationId === null || !state?.hasMoreBefore || loadingOlderMessages) return;
  const previousScrollHeight = container?.scrollHeight || 0;
  setLoadingOlderMessages(true);
  try {
    const data = await getDouyinConversationMessages(conversationId, {
      account_open_id: accountOpenId,
      before_event_id: state.oldestEventId,
      limit: 100,
    });
    if (
      selectedAccountOpenIdRef.current !== accountOpenId
      || selectedConversationIdRef.current !== conversationId
    ) return;
    const merged = mergeMessagesByEventId(messagesCacheRef.current[cacheKey] || [], data.items);
    messagesCacheRef.current[cacheKey] = merged;
    conversationIncrementalRef.current[cacheKey] = {
      ...state,
      oldestEventId: Number(data.next_before_event_id ?? state.oldestEventId),
      hasMoreBefore: Boolean(data.has_more),
      historyError: null,
    };
    setMessages(merged);
    window.requestAnimationFrame(() => {
      if (container) container.scrollTop += container.scrollHeight - previousScrollHeight;
    });
  } catch (err) {
    conversationIncrementalRef.current[cacheKey] = {
      ...state,
      historyError: userFacingError(err, "更早消息加载失败"),
    };
  } finally {
    setLoadingOlderMessages(false);
  }
}, [loadingOlderMessages]);
```

给现有消息滚动容器绑定 `ref={messageListRef}`；在消息顶部仅当 `hasMoreBefore` 时显示“加载更早消息”按钮。历史分页成功不得创建 mark-read 凭据。

- [ ] **Step 10：显示同步状态与独立重试动作**

在工作台标题附近显示：

```tsx
<span className="text-xs text-slate-500">
  {lastSuccessfulSyncAt ? `最后同步 ${formatTime(new Date(lastSuccessfulSyncAt).toISOString())}` : "尚未完成全账号同步"}
</span>
```

账号增量错误、当前会话增量错误和历史分页错误分别使用现有 `ErrorBanner`/按钮触发 `syncAllAccountsRef.current()`、`syncSelectedConversationMessages()`、`loadOlderMessages()`。失败时不得清空缓存、红点或游标。

- [ ] **Step 11：运行前端行为、静态合同、编译和定向 lint**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py -k "frontend_workbench" -q
cd frontend
npm.cmd run douyin-workbench-incremental:check
npx.cmd tsc --noEmit -p tsconfig.app.json --tsBuildInfoFile $env:TEMP\auto_wechat_incremental_page.tsbuildinfo
npx.cmd eslint src/api/douyinAiCsClient.ts src/features/douyin-cs/douyinConversationIncremental.ts src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx scripts/check-douyin-workbench-incremental.mjs
```

Expected: 全部退出码 0；不得运行 `eslint --fix`。

- [ ] **Step 12：提交页面接入**

```powershell
git add frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx tests/test_douyin_workbench_conversations.py
git commit --only frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx tests/test_douyin_workbench_conversations.py -m "功能：接入抖音会话全账号增量同步"
```

### Task 8：完整回归、稳定性、范围检查和候选冻结

**Files:**
- Verify only: all 12 allowed files
- Do not modify: `docs/ai/**`, `migrations/**`, 外部待办

- [ ] **Step 1：编译所有触及的 Python 文件**

Run:

```powershell
python -m py_compile app/services/douyin_workbench_conversation_service.py app/routers/integrations.py app/routers/douyin_accounts.py tests/test_douyin_workbench_conversations.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_tenant_isolation_r2.py tests/test_9000_postgres_douyin_conversation_incremental.py
```

Expected: 无输出，退出码 0。

- [ ] **Step 2：运行后端协议、隔离和相邻只读回归**

Run:

```powershell
pytest tests/test_douyin_workbench_conversations.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_tenant_isolation_r2.py -q
pytest tests/test_douyin_conversation_read_state.py tests/test_douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py -q
pytest tests/test_ai_auto_reply_dry_run.py tests/test_ai_auto_reply_outbox_service.py -q
```

Expected: `0 failed`。这些测试不得调用真实抖音、9100、LLM、微信或发送接口。

- [ ] **Step 3：运行 PostgreSQL 专项三轮稳定性**

Run three times:

```powershell
pytest tests/test_9000_postgres_douyin_conversation_incremental.py -q -rs
```

Expected: 每轮 `0 failed, 0 skipped`；5 万行 namespace 清理后残留 0；事件表无 `Seq Scan`，过滤移除行门禁保持通过。任一轮失败即停止，不用重跑掩盖不稳定。

- [ ] **Step 4：运行前端行为、构建、编码和定向 lint**

Run:

```powershell
cd frontend
npm.cmd run douyin-workbench-incremental:check
npm.cmd run encoding:check
npx.cmd tsc --noEmit -p tsconfig.app.json --tsBuildInfoFile $env:TEMP\auto_wechat_incremental_final.tsbuildinfo
npx.cmd eslint src/api/douyinAiCsClient.ts src/features/douyin-cs/douyinConversationIncremental.ts src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx scripts/check-douyin-workbench-incremental.mjs
npm.cmd run build
```

Expected: 行为检查输出 `DOUYIN_WORKBENCH_INCREMENTAL_CHECK_OK`，其余退出码 0。构建生成物若被 Git 跟踪或产生行尾漂移，恢复生成物本身，不得改业务文件掩盖问题。

- [ ] **Step 5：检查 A1～A12 和 F1～F10 对应证据**

逐项记录：

```text
A1 旧无游标兼容
A2 after 多页
A3 before 超过 200 条
A4 迟到旧时间
A5 同时间戳稳定排序
A6 422 参数边界
A7 空页 200 / 防枚举 404
A8 商户、账号、NULL 隔离
A9 重复排除与坏事件推进
A10 账号水位和权威红点
A11 id 边界 + limit + 不扩大 event_limit
A12 PostgreSQL 执行计划
F1 去重与水位不倒退
F2 online 补拉
F3 恢复触发合并
F4 全授权账号红点
F5 后台不标已读
F6 失败不清状态
F7 迟到响应保护
F8 历史滚动锚点
F9 成功时间语义
F10 无 SSE/WebSocket，8 秒未缩短
```

任何编号没有可运行证据时，不得回传 `CANDIDATE_READY`。

- [ ] **Step 6：检查差异范围、线性历史和空白**

Run:

```powershell
git diff --check b464abbef3663f8948e929d18ab314bd02c5f1fb..HEAD
git diff --name-status b464abbef3663f8948e929d18ab314bd02c5f1fb..HEAD
git rev-list --parents --reverse b464abbef3663f8948e929d18ab314bd02c5f1fb..HEAD
git status --short
rg -n "EventSource|WebSocket|setInterval\([^,]+,\s*[0-7][0-9]{3}\)" frontend/src/features/douyin-cs frontend/src/api/douyinAiCsClient.ts
```

Expected:

- 差异仅 12 个允许文件。
- 所有实现提交单父线性。
- `git diff --check` 干净。
- 工作区只保留三份治理计划暂存，无业务残留。
- SSE/WebSocket 和短于 8 秒的新增会话轮询零命中；既有自动回复 4 秒轮询不属于会话同步，不得误删。

- [ ] **Step 7：执行文档影响检查但不提前闭环**

结论应为：本任务会使 `docs/ai/05_PROJECT_CONTEXT.md`、`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` 和外部待办中的“仍待增量协议”状态过期，但按治理边界，本业务候选阶段不修改它们。候选独立测试并推送后另开文档闭环与外部待办同步任务。

- [ ] **Step 8：冻结候选并回传证据**

回传必须包含：

```text
CANDIDATE_READY
Task-ID / Plan-Revision / Plan SHA256
Execution-Base / Candidate-Commit / 单父提交链
12 个允许文件 name-status
A1-A12 / F1-F10 逐项结果
PostgreSQL 三轮执行计划与清理结果
前端行为检查、编译、lint、build 结果
相邻回归结果与 Candidate 新增失败数
无外部调用、无生产连接、无真实发送
未推送、未部署、未修改活动文档或外部待办
```

候选冻结后不得自行发起独立测试、推送、文档闭环或外部待办同步。
