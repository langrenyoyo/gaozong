# Phase 2 违禁词统一替换服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 9000 主服务内建立统一违禁词替换服务，让 AI 消息和人工消息在进入抖音私信、微信反馈、微信通知写入前共用同一套“命中后替换为安全词并继续”的规则。

**Architecture:** 本阶段复用 Phase 1 已落地的 `forbidden_word_libraries`、`forbidden_words`、`forbidden_word_hit_logs` 三张表，不新增迁移和权限码。核心能力放在 `app/services/forbidden_word_service.py`，管理接口放在 `app/routers/forbidden_words.py`，发送链路只做最窄接入：抖音私信中心 helper、旧微信反馈服务、现有微信通知路由/服务在写入前调用替换服务；不改 Local Agent、`input_writer`、`contact_searcher` 或上游调用开关。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、Python 标准库 `re`、pytest 临时 SQLite 测试库。

---

## 阶段定位

阶段名称：`Phase 2 违禁词统一替换服务`

执行窗口：独立执行窗口 / 子代理。

审批窗口：当前窗口只接收结果并审批，不直接编码。

风险等级：`HIGH`

原因：本阶段涉及数据库写入、权限接口、抖音私信和微信消息写入前置处理。虽然不新增表、不执行迁移、不主动调用外部服务，但任何遗漏都可能导致后续实发阶段绕过替换规则。

## 已知当前状态

正式仓库：

```text
路径：E:\work\project\auto_wechat
分支：master
当前已知状态：master...origin/master [ahead 25]
当前已知未提交项：
 M docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
?? docs/superpowers/plans/2026-07-10-phase1-data-migration-skeleton-execution-package.md
```

执行窗口开始前必须重新运行：

```bash
git status --short --branch
git log --oneline -5
```

如发现除上述计划文档以外还有未提交业务代码，必须停止并回传 `NEEDS_CONTEXT`。

Phase 1 已存在结构：

```text
app.models.ForbiddenWordLibrary
app.models.ForbiddenWord
app.models.ForbiddenWordHitLog
app.schemas.ForbiddenWordLibraryOut
app.schemas.ForbiddenWordOut
app.schemas.ForbiddenWordHitLogOut
```

已存在权限码：

```text
auto_wechat:admin:forbidden_words
```

不得新增权限码。

## 本阶段目标

1. 新增统一替换服务，读取启用的全局词库和启用词条。
2. 命中违禁词后替换为每个词条配置的 `safe_word`，继续后续发送流程，不把命中作为拦截理由。
3. 记录命中日志到 `forbidden_word_hit_logs`，只保存脱敏摘要和上下文，不保存完整客户消息、完整 LLM 响应、token、cookie、secret。
4. 更新 `forbidden_words.hit_count`，同词多次命中按实际出现次数累计。
5. 增加超管管理 API，使用既有权限码 `auto_wechat:admin:forbidden_words`。
6. 抖音 AI 自动回复和抖音工作台人工发送通过同一个 `_send_private_message_with_context` 接入替换。
7. 平台内已有微信反馈和微信通知写入前也调用同一个替换服务，但不改微信 UI 自动化底层。
8. 提供单元测试、API 权限测试、受控发送接入测试，所有外部发送和微信写入都必须 mock。

## 允许范围

本阶段允许创建：

```text
app/services/forbidden_word_service.py
app/routers/forbidden_words.py
tests/test_forbidden_word_service.py
tests/test_forbidden_words_api.py
tests/test_forbidden_word_send_integration.py
```

本阶段允许修改：

```text
app/main.py
app/services/douyin_private_message_send_service.py
app/services/feedback_service.py
app/routers/lead_notifications.py
app/services/notification_service.py
```

本阶段只读参考：

```text
CLAUDE.md
docs/ai/01_READING_RULES.md
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/02_EXECUTION_RULES.md
docs/ai/03_TESTING_RULES.md
docs/ai/04_OUTPUT_RULES.md
docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md
docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
docs/superpowers/plans/2026-07-10-phase1-data-migration-skeleton-execution-package.md
app/models.py
app/schemas.py
app/auth/dependencies.py
app/auth/context.py
app/routers/admin_autoreply_rollout.py
app/services/ai_auto_reply_send_service.py
tests/test_ai_auto_reply_send_service.py
tests/test_lead_notifications.py
tests/test_admin_autoreply_rollout_api.py
```

`app/services/ai_auto_reply_send_service.py` 原则上不需要修改，因为它已调用 `app.services.douyin_private_message_send_service._send_private_message_with_context`。只有执行测试证明中心 helper 接入无法覆盖 AI 自动回复时，才允许停止回传并申请扩大修改范围。

## 禁止事项

1. 禁止新增或修改数据库迁移文件。
2. 禁止新增权限码。
3. 禁止新增依赖。
4. 禁止启动 9000 / 9100 / 19000 / 前端服务。
5. 禁止连接 production 数据库、读取 production SQLite、连接 production PostgreSQL。
6. 禁止调用抖音 OpenAPI、巨量接口、LLM、Milvus、微信客户端、支付、短信、邮件等外部资源；测试必须 mock。
7. 禁止修改 `app/wechat_ui/input_writer.py`、`app/wechat_ui/contact_searcher.py`、`app/local_agent_main.py`、微信 UI 自动化底层逻辑。
8. 禁止改变联系人验证、前台焦点、人工接管、限频、失败回写、幂等、紧急停止等 gate。
9. 禁止把违禁词命中改成拦截、人工降级或失败；一期规则是替换安全词后继续。
10. 禁止在日志、接口响应、测试快照中保存完整客户消息、完整 LLM 原始响应、Authorization、cookie、secret、真实连接串。
11. 禁止顺手实现 Phase 3 抖音 AI 自动回复闭环扩大、Phase 7 微信派单实发改造、Phase 13 前端页面。

## 停止门禁

出现以下任一情况，执行窗口必须停止并回传 `NEEDS_CONTEXT`：

1. Phase 1 三张违禁词表不存在或字段名与本执行包不一致。
2. `auto_wechat:admin:forbidden_words` 不存在于现有能力配置或 mock 权限中。
3. 需要新增迁移才能完成。
4. 需要修改 `input_writer`、`contact_searcher`、Local Agent 或微信 UI 自动化底层。
5. 需要启动服务、连接生产库、发起真实外部请求才能验证。
6. 抖音 AI 自动回复没有经过 `_send_private_message_with_context`，中心 helper 无法覆盖。
7. 发现同一发送路径已有旧违禁词拦截逻辑，且会与“替换后继续”冲突。
8. 需要修改未列入允许范围的业务文件。

## 统一替换规则

### 活跃词定义

只加载同时满足以下条件的词条：

```text
ForbiddenWordLibrary.enabled == true
ForbiddenWordLibrary.scope == "global"
ForbiddenWord.enabled == true
ForbiddenWord.word 非空
ForbiddenWord.safe_word 非空
```

一期为全局词库，不按商户隔离词库；`merchant_id` 只用于命中日志的归属和后续统计。

### 匹配和替换

1. 使用 Python 标准库 `re`，不新增依赖。
2. 中文按原文子串匹配。
3. 英文和大小写混合内容按 `casefold()` 做等价判断，正则使用 `re.IGNORECASE`。
4. 多词命中时按违禁词长度降序构建单个正则，保证“现车很多”先于“现车”。
5. 单次正则替换完成，不对替换后的安全词再次进行二次替换。
6. 同一个词多次命中，返回命中次数，`ForbiddenWord.hit_count` 累加实际次数。
7. 同一次调用中，命中日志按唯一词条记录一行，避免一条长消息刷出大量日志。
8. 空内容、空白内容、无启用词时直接返回原文，`changed=false`，不写命中日志。
9. API 创建和更新时禁止启用 `safe_word` 为空的词条。
10. API 创建和更新时禁止同一词库下出现大小写等价的重复 `word`。

### 返回结构

服务函数签名固定为：

```python
def replace_forbidden_words(
    db: Session,
    *,
    merchant_id: str,
    source: str,
    content: str,
    context: dict[str, object] | None = None,
) -> ForbiddenWordReplacementResult:
    ...
```

返回对象字段固定为：

```python
@dataclass(frozen=True)
class ForbiddenWordHit:
    library_key: str
    word: str
    safe_word: str
    count: int


@dataclass(frozen=True)
class ForbiddenWordReplacementResult:
    original_content: str
    final_content: str
    changed: bool
    hits: list[ForbiddenWordHit]
    audit_ids: list[int]

    @property
    def audit_id(self) -> int | None:
        return self.audit_ids[0] if self.audit_ids else None
```

`context` 支持但不信任任意前端字段，只允许从后端已校验上下文传入：

```text
context_type
context_id
conversation_short_id
lead_id
record_id
task_id
```

写入 `ForbiddenWordHitLog` 时仅使用：

```text
merchant_id
library_key
word
safe_word
source
context_type
context_id
before_text_summary
after_text_summary
```

### 摘要脱敏规则

摘要函数固定行为：

1. 折叠连续空白为单个空格。
2. 摘要最长 160 个字符，超长尾部追加 `...`。
3. 手机号 `1[3-9]\d{9}` 脱敏为前三后四：`138****8000`。
4. `微信`、`微信号`、`wx`、`wechat` 后跟随的账号值脱敏为 `微信号[masked]`。
5. 不记录 `Authorization`、`cookie`、`token`、`secret`、`password`、完整 open_id、完整 server_message_id。

## 超管 API 契约

路由文件：

```text
app/routers/forbidden_words.py
```

路由前缀：

```text
/admin
```

权限函数：

```python
def _require_admin(context: RequestContext) -> RequestContext:
    if not context.has_permission("auto_wechat:admin:forbidden_words"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:forbidden_words"},
        )
    return context
```

接口范围：

```text
GET  /admin/forbidden-word-libraries
GET  /admin/forbidden-words
POST /admin/forbidden-words
PUT  /admin/forbidden-words/{word_id}
POST /admin/forbidden-words/{word_id}/toggle
```

不在本阶段新增命中日志查询接口；测试直接查数据库验证日志。

### 请求结构

请求模型可以定义在 `app/routers/forbidden_words.py` 内，避免扩散 `app/schemas.py`：

```python
class ForbiddenWordCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    library_key: str = Field(..., min_length=1, max_length=64)
    word: str = Field(..., min_length=1, max_length=100)
    safe_word: str = Field(..., min_length=1, max_length=100)
    severity: str | None = Field(None, max_length=32)
    enabled: bool = True


class ForbiddenWordUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    word: str | None = Field(None, min_length=1, max_length=100)
    safe_word: str | None = Field(None, min_length=1, max_length=100)
    severity: str | None = Field(None, max_length=32)
    enabled: bool | None = None


class ForbiddenWordToggleRequest(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool
```

### 响应结构

统一返回：

```python
{"success": True, "data": ..., "message": "success"}
```

错误响应：

```python
{"detail": {"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:forbidden_words"}}
{"detail": {"code": "LIBRARY_NOT_FOUND", "message": "违禁词库不存在"}}
{"detail": {"code": "WORD_DUPLICATED", "message": "同一词库已存在相同违禁词"}}
{"detail": {"code": "SAFE_WORD_REQUIRED", "message": "安全替换词不能为空"}}
{"detail": {"code": "WORD_NOT_FOUND", "message": "违禁词不存在"}}
```

## 发送链路接入点

### 抖音私信中心 helper

文件：

```text
app/services/douyin_private_message_send_service.py
```

位置：

```text
_send_private_message_with_context()
```

要求：

1. 在 `sanitize_ai_reply_content()` 后、`request_payload` 构造前调用 `replace_forbidden_words()`。
2. `content_text` 必须替换为 `replacement.final_content`。
3. `DouyinPrivateMessageSend.content` 保存替换后的最终内容。
4. `request_body_json.content` 保存替换后的最终内容。
5. `send_source="manual"` 时 `source` 写 `douyin_manual`。
6. `send_source="ai_auto"` 时 `source` 写 `douyin_ai_auto`。
7. `context_type` 写 `douyin_conversation`。
8. `context_id` 优先写 `conversation_short_id`。
9. 不改变人工确认、AI 托管、人工接管、限频、幂等、失败回写等 gate。

### 微信反馈服务

文件：

```text
app/services/feedback_service.py
```

位置：

```text
send_feedback_current_chat()
```

要求：

1. 在调用 `write_text_to_input()` 前替换 `record.feedback_text`。
2. 传入 `source="wechat_feedback"`。
3. `context_type="feedback_record"`，`context_id=str(record.id)`。
4. 替换后仅用于本次写入，不在本阶段新增字段保存原文。
5. 不修改 `write_text_to_input()`，不改变 `require_confirm` 行为。

### 微信通知路由和自动通知服务

文件：

```text
app/routers/lead_notifications.py
app/services/notification_service.py
```

要求：

1. 在调用 `write_text_to_input()` 前替换 `notification_text`。
2. 传入 `source="wechat_dispatch"`。
3. 手动路由 `context_type="lead_notification"`，`context_id` 优先使用 `lead.id`，创建记录后仍用替换后的文本入库。
4. 自动通知服务同样使用替换后的文本创建 `LeadNotification`。
5. 不修改联系人搜索、OCR 验证、前台焦点、紧急停止、写入动作。

## TDD 任务拆分

### Task 1: 替换服务红灯测试

**Files:**

- Create: `tests/test_forbidden_word_service.py`

- [ ] **Step 1: 写失败测试**

必须包含以下测试函数：

```python
def test_replace_forbidden_words_replaces_and_logs_hit():
    ...


def test_replace_forbidden_words_prefers_longest_word():
    ...


def test_replace_forbidden_words_is_case_insensitive_for_latin_text():
    ...


def test_replace_forbidden_words_counts_repeated_hits_once_per_log_row():
    ...


def test_replace_forbidden_words_ignores_disabled_library_and_word():
    ...


def test_replace_forbidden_words_skips_blank_safe_word():
    ...


def test_replace_forbidden_words_masks_summary_sensitive_values():
    ...


def test_replace_forbidden_words_empty_content_is_noop():
    ...
```

核心断言：

```python
result = replace_forbidden_words(
    db,
    merchant_id="merchant-1",
    source="douyin_ai_auto",
    content="我们现车很多，微信13800138000可以聊",
    context={"context_type": "douyin_conversation", "context_id": "conv-1"},
)

assert result.changed is True
assert result.final_content == "我们可到店详询，联系方式可以聊"
assert [hit.word for hit in result.hits] == ["现车很多", "微信13800138000"]
assert db.query(ForbiddenWordHitLog).count() == 2
assert "13800138000" not in db.query(ForbiddenWordHitLog).first().before_text_summary
```

最长词测试必须证明：

```python
content = "现车很多"
word="现车", safe_word="可咨询"
word="现车很多", safe_word="可到店详询"
assert result.final_content == "可到店详询"
```

- [ ] **Step 2: 运行红灯**

Run:

```bash
python -m pytest tests/test_forbidden_word_service.py -v
```

Expected:

```text
FAIL
ImportError 或 NameError: forbidden_word_service / replace_forbidden_words 尚不存在
```

- [ ] **Step 3: 停止提交**

红灯通过后不要提交，只进入 Task 2。

### Task 2: 实现最小替换服务

**Files:**

- Create: `app/services/forbidden_word_service.py`

- [ ] **Step 1: 实现数据结构和服务函数**

必须提供：

```python
ForbiddenWordHit
ForbiddenWordReplacementResult
replace_forbidden_words
summarize_replacement_text
```

实现约束：

1. 不新增 repository 层。
2. 不缓存词库；本阶段以最小可验证实现为准。
3. 用 SQLAlchemy ORM 查询 `ForbiddenWordLibrary` 与 `ForbiddenWord`。
4. 替换和日志写入在调用方传入的 `db` 事务内完成，服务内部允许 `flush()`，不主动 `commit()`。
5. `hit_count` 递增后由调用方最终提交。

- [ ] **Step 2: 运行服务测试**

Run:

```bash
python -m pytest tests/test_forbidden_word_service.py -v
```

Expected:

```text
8 passed
```

- [ ] **Step 3: 提交**

```bash
git add app/services/forbidden_word_service.py tests/test_forbidden_word_service.py
git commit -m "feat: 增加违禁词统一替换服务"
```

### Task 3: 超管 API 红灯测试

**Files:**

- Create: `tests/test_forbidden_words_api.py`

- [ ] **Step 1: 写失败测试**

必须包含以下测试函数：

```python
def test_admin_forbidden_word_api_requires_login():
    ...


def test_admin_forbidden_word_api_requires_permission():
    ...


def test_admin_lists_libraries():
    ...


def test_admin_creates_word_under_library_key():
    ...


def test_admin_rejects_duplicate_word_case_insensitive():
    ...


def test_admin_updates_word_and_safe_word():
    ...


def test_admin_toggles_word_enabled():
    ...


def test_admin_lists_words_with_filters():
    ...
```

权限断言：

```python
client = _client(_context(super_admin=False, permission_codes=["auto_wechat:admin:ai_reply_records"]))
resp = client.get("/admin/forbidden-word-libraries")
assert resp.status_code == 403
assert resp.json()["detail"]["code"] == "PERMISSION_DENIED"
```

创建断言：

```python
resp = client.post(
    "/admin/forbidden-words",
    json={
        "library_key": "used_car_sales_base",
        "word": "现车很多",
        "safe_word": "可到店详询",
        "severity": "medium",
        "enabled": True,
    },
)
assert resp.status_code == 200
assert resp.json()["data"]["word"] == "现车很多"
```

- [ ] **Step 2: 运行红灯**

Run:

```bash
python -m pytest tests/test_forbidden_words_api.py -v
```

Expected:

```text
FAIL
404 Not Found 或 ImportError: app.routers.forbidden_words 尚不存在
```

### Task 4: 实现超管 API 并注册路由

**Files:**

- Create: `app/routers/forbidden_words.py`
- Modify: `app/main.py`
- Test: `tests/test_forbidden_words_api.py`

- [ ] **Step 1: 实现 router**

实现接口：

```text
GET  /admin/forbidden-word-libraries
GET  /admin/forbidden-words
POST /admin/forbidden-words
PUT  /admin/forbidden-words/{word_id}
POST /admin/forbidden-words/{word_id}/toggle
```

校验规则：

1. 所有接口必须依赖 `get_request_context_required`。
2. 所有接口必须调用 `_require_admin(context)`。
3. 写接口必须 `.strip()` `word` 和 `safe_word`。
4. `safe_word` 为空返回 `SAFE_WORD_REQUIRED`。
5. `library_key` 不存在返回 `LIBRARY_NOT_FOUND`。
6. 同一词库大小写等价重复返回 `WORD_DUPLICATED`。
7. `word_id` 不存在返回 `WORD_NOT_FOUND`。

- [ ] **Step 2: 在 `app/main.py` 注册 router**

要求：

```python
from app.routers import forbidden_words
...
app.include_router(forbidden_words.router)
```

注册位置放在其他 admin router 附近，保持现有风格。

- [ ] **Step 3: 运行 API 测试**

Run:

```bash
python -m pytest tests/test_forbidden_words_api.py -v
```

Expected:

```text
8 passed
```

- [ ] **Step 4: 提交**

```bash
git add app/routers/forbidden_words.py app/main.py tests/test_forbidden_words_api.py
git commit -m "feat: 增加违禁词超管接口"
```

### Task 5: 发送接入红灯测试

**Files:**

- Create: `tests/test_forbidden_word_send_integration.py`

- [ ] **Step 1: 写失败测试**

必须覆盖：

```python
def test_douyin_manual_send_replaces_forbidden_words_before_upstream_call():
    ...


def test_douyin_ai_auto_send_reuses_private_message_replacement():
    ...


def test_wechat_feedback_replaces_forbidden_words_before_write_text():
    ...


def test_lead_notification_route_replaces_forbidden_words_before_write_text():
    ...


def test_notification_service_replaces_forbidden_words_before_write_text():
    ...
```

抖音人工发送测试要 mock：

```python
with patch("app.services.douyin_private_message_send_service.call_douyin_openapi") as upstream:
    upstream.return_value = {"payload": {"data": {"msg_id": "upstream-msg-1"}}}
```

核心断言：

```python
request_payload = upstream.call_args.args[1]
assert request_payload["content"] == "可到店详询"
record = db.query(DouyinPrivateMessageSend).one()
assert record.content == "可到店详询"
assert db.query(ForbiddenWordHitLog).filter_by(source="douyin_manual").count() == 1
```

AI 自动回复测试不直接调用上游，优先调用 `send_ai_auto_reply_for_run()`，并 mock `call_douyin_openapi`。断言：

```python
assert request_payload["content"] == "可到店详询"
assert record.send_source == "ai_auto"
assert db.query(ForbiddenWordHitLog).filter_by(source="douyin_ai_auto").count() == 1
```

微信相关测试必须 mock：

```python
patch("app.services.feedback_service.find_wechat_window")
patch("app.services.feedback_service.find_current_chat_title")
patch("app.wechat_ui.input_writer.write_text_to_input")
patch("app.routers.lead_notifications.write_text_to_input")
patch("app.services.notification_service.write_text_to_input")
```

断言 `write_text_to_input` 收到的是替换后的文本。

- [ ] **Step 2: 运行红灯**

Run:

```bash
python -m pytest tests/test_forbidden_word_send_integration.py -v
```

Expected:

```text
FAIL
断言上游 payload 或 write_text_to_input 参数仍包含原违禁词
```

### Task 6: 接入发送链路

**Files:**

- Modify: `app/services/douyin_private_message_send_service.py`
- Modify: `app/services/feedback_service.py`
- Modify: `app/routers/lead_notifications.py`
- Modify: `app/services/notification_service.py`
- Test: `tests/test_forbidden_word_send_integration.py`

- [ ] **Step 1: 接入抖音私信 helper**

在 `_send_private_message_with_context()` 中：

```python
replacement = replace_forbidden_words(
    db,
    merchant_id=_resolve_merchant_id_for_account(db, context["account_open_id"]) or "unknown_merchant",
    source="douyin_ai_auto" if send_source == "ai_auto" else "douyin_manual",
    content=content_text,
    context={
        "context_type": "douyin_conversation",
        "context_id": context.get("conversation_short_id"),
        "conversation_short_id": context.get("conversation_short_id"),
    },
)
content_text = replacement.final_content
```

注意：

1. 这里允许使用现有 `_resolve_merchant_id_for_account()`。
2. 如果解析不到商户，使用 `"unknown_merchant"`，不要阻断发送。
3. 不要在替换服务内部 `commit()`；保留当前函数原有成功/失败提交语义。

- [ ] **Step 2: 接入微信反馈服务**

在 `send_feedback_current_chat()` 调用 `write_text_to_input()` 前替换：

```python
replacement = replace_forbidden_words(
    db,
    merchant_id=_resolve_feedback_merchant_id(record),
    source="wechat_feedback",
    content=record.feedback_text,
    context={"context_type": "feedback_record", "context_id": str(record.id)},
)
feedback_text = replacement.final_content
```

若 `FeedbackRecord` 无法直接拿到 `merchant_id`，通过 `record.lead_id -> DouyinLead.merchant_id` 解析；解析不到使用 `"unknown_merchant"`。

- [ ] **Step 3: 接入微信通知路由**

在 `app/routers/lead_notifications.py` 生成 `notification_text` 后、写入前替换，并用替换后文本创建通知记录。

```python
replacement = replace_forbidden_words(
    db,
    merchant_id=lead.merchant_id or "unknown_merchant",
    source="wechat_dispatch",
    content=notification_text,
    context={"context_type": "lead_notification", "context_id": str(lead.id)},
)
notification_text = replacement.final_content
```

- [ ] **Step 4: 接入自动通知服务**

在 `app/services/notification_service.py` 同样处理 `notification_text`，保持和路由路径一致。

- [ ] **Step 5: 运行发送接入测试**

Run:

```bash
python -m pytest tests/test_forbidden_word_send_integration.py -v
```

Expected:

```text
5 passed
```

- [ ] **Step 6: 运行相邻回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_lead_notifications.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 7: 提交**

```bash
git add app/services/douyin_private_message_send_service.py app/services/feedback_service.py app/routers/lead_notifications.py app/services/notification_service.py tests/test_forbidden_word_send_integration.py
git commit -m "feat: 接入消息发送违禁词替换"
```

### Task 7: 阶段总验证

**Files:**

- No code change unless tests expose a Phase 2 defect.

- [ ] **Step 1: 跑 Phase 2 全量测试**

Run:

```bash
python -m pytest tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_forbidden_word_send_integration.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 2: 跑关联回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_lead_notifications.py tests/test_admin_autoreply_rollout_api.py tests/test_xiaogao_phase1_schema.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 3: 静态边界检查**

Run:

```bash
rg -n "auto_wechat:admin:ai_video|auto_wechat:admin:ad_review|auto_wechat:ai_video|auto_wechat:ad_review" app tests frontend docs/superpowers/plans
rg -n "[T]ODO|[T]BD|占[位]" app/services/forbidden_word_service.py app/routers/forbidden_words.py tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_forbidden_word_send_integration.py
rg -n "input_writer|contact_searcher|local_agent_main" app/services/forbidden_word_service.py app/routers/forbidden_words.py
git diff --check
git status --short --branch
```

Expected:

```text
第 1 条：无新增权限码命中；历史文档如已有命中需在回传中列明不是本阶段新增。
第 2 条：无输出。
第 3 条：无输出。
git diff --check：无输出。
git status：只允许本阶段已提交后的既有计划文档残留；不得有未提交业务代码。
```

- [ ] **Step 4: 最终提交检查**

Run:

```bash
git log --oneline -5
```

Expected:

```text
至少包含本阶段 3 个中文提交：
feat: 增加违禁词统一替换服务
feat: 增加违禁词超管接口
feat: 接入消息发送违禁词替换
```

## 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 单词命中 | Unit | `现车很多` | 替换为对应安全词 | `test_replace_forbidden_words_replaces_and_logs_hit` |
| 长短词重叠 | Unit | `现车` 与 `现车很多` 同时启用 | 长词优先 | `test_replace_forbidden_words_prefers_longest_word` |
| 英文大小写 | Unit | `Loan` 命中 `loan` | 替换成功 | `test_replace_forbidden_words_is_case_insensitive_for_latin_text` |
| 重复命中 | Unit | 同词出现 3 次 | `hit_count += 3`，日志 1 行 | `test_replace_forbidden_words_counts_repeated_hits_once_per_log_row` |
| 禁用词库 | Unit | library disabled | 不替换、不写日志 | `test_replace_forbidden_words_ignores_disabled_library_and_word` |
| 空安全词 | Unit | `safe_word` 为空 | 不参与替换 | `test_replace_forbidden_words_skips_blank_safe_word` |
| 摘要脱敏 | Unit | 内容含手机号/微信号 | 摘要不含明文 | `test_replace_forbidden_words_masks_summary_sensitive_values` |
| API 权限 | Integration | 缺少 `auto_wechat:admin:forbidden_words` | 403 | `test_admin_forbidden_word_api_requires_permission` |
| API 创建 | Integration | 创建词条 | 返回词条，数据库写入 | `test_admin_creates_word_under_library_key` |
| API 重复 | Integration | 大小写等价重复词 | 400 `WORD_DUPLICATED` | `test_admin_rejects_duplicate_word_case_insensitive` |
| 抖音人工消息 | Integration | 工作台人工发送含违禁词 | 上游 payload 已替换 | `test_douyin_manual_send_replaces_forbidden_words_before_upstream_call` |
| 抖音 AI 消息 | Integration | AI 自动回复 run 含违禁词 | `DouyinPrivateMessageSend.content` 已替换 | `test_douyin_ai_auto_send_reuses_private_message_replacement` |
| 微信反馈 | Integration | feedback 文本含违禁词 | `write_text_to_input` 收到安全词文本 | `test_wechat_feedback_replaces_forbidden_words_before_write_text` |
| 微信通知路由 | Integration | 通知模板含违禁词 | 写入前替换 | `test_lead_notification_route_replaces_forbidden_words_before_write_text` |
| 自动通知服务 | Integration | 自动通知文本含违禁词 | 写入前替换 | `test_notification_service_replaces_forbidden_words_before_write_text` |

## 回滚方案

如 Phase 2 需要回滚：

1. 回滚本阶段 3 个提交。
2. 不需要回滚数据库迁移，因为本阶段不新增表结构。
3. 已写入的 `forbidden_word_hit_logs` 可保留，属于审计记录；若必须清理，应由审批窗口另开数据清理执行包。
4. 如仅某词误替换，可通过超管 API 禁用该词条或词库，无需回滚代码。

## Spec Reviewer 清单

Spec Reviewer 只看需求符合度，必须逐项回答：

1. 是否使用 Phase 1 已有三张违禁词表，没有新增迁移。
2. 是否复用既有权限码 `auto_wechat:admin:forbidden_words`，没有新增权限码。
3. 是否实现“命中后替换安全词并继续”，没有改成拦截、失败或人工降级。
4. 是否覆盖 AI 消息和人工消息。
5. 是否覆盖抖音私信中心 helper，从而覆盖人工发送和 AI 自动回复。
6. 是否覆盖平台内现有微信反馈和微信通知写入前替换。
7. 是否没有修改 Local Agent、`input_writer`、`contact_searcher`、微信 UI 自动化底层。
8. 是否命中日志只保存脱敏摘要和后端可信上下文。
9. 是否超管 API 有后端权限校验，前端隐藏不作为权限依据。
10. 是否没有提前实现 Phase 3、Phase 7、Phase 13。

Spec Reviewer 结论只能是：

```text
Approved
Approved with Conditions
Rejected
```

## Code Quality Reviewer 清单

Code Quality Reviewer 只看实现质量和回归风险，必须逐项回答：

1. 替换算法是否单次正则替换，能处理长短词重叠。
2. 同词多次命中是否累计 `hit_count`，日志是否避免爆量。
3. 服务函数是否不主动 `commit()`，保留调用方事务语义。
4. API 输入是否 `.strip()`，是否拒绝空 `word` / 空 `safe_word`。
5. API 是否拒绝同一词库大小写等价重复词。
6. 抖音接入是否发生在 `request_payload` 构造前。
7. 微信接入是否发生在 `write_text_to_input` 前。
8. 是否没有新增依赖、没有新增配置项。
9. 日志和测试输出是否不泄露手机号、微信号、token、cookie、secret、完整 open_id。
10. 关联回归是否使用 `python -m pytest` 并通过。

Code Quality Reviewer 结论只能是：

```text
Approved
Approved with Conditions
Rejected
```

## 执行窗口回传格式

执行完成后，回传必须使用以下结构：

```text
阶段：Phase 2 违禁词统一替换服务
状态：DONE / BLOCKED

提交：
- <hash> feat: 增加违禁词统一替换服务
- <hash> feat: 增加违禁词超管接口
- <hash> feat: 接入消息发送违禁词替换

变更文件：
- app/services/forbidden_word_service.py
- app/routers/forbidden_words.py
- app/main.py
- app/services/douyin_private_message_send_service.py
- app/services/feedback_service.py
- app/routers/lead_notifications.py
- app/services/notification_service.py
- tests/test_forbidden_word_service.py
- tests/test_forbidden_words_api.py
- tests/test_forbidden_word_send_integration.py

数据库迁移：无
新增权限码：无
新增依赖：无
服务启动 / 真实请求：无
未触碰：app/wechat_ui/input_writer.py、app/wechat_ui/contact_searcher.py、app/local_agent_main.py、19000 Local Agent、前端页面

测试命令与结果：
- python -m pytest tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_forbidden_word_send_integration.py -v：<结果>
- python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_lead_notifications.py tests/test_admin_autoreply_rollout_api.py tests/test_xiaogao_phase1_schema.py -v：<结果>
- git diff --check：<结果>

自审结论：
- Spec Reviewer：Approved / Approved with Conditions / Rejected
- Code Quality Reviewer：Approved / Approved with Conditions / Rejected

剩余风险：
- <逐条列出，没有则写“无”>
```

如果状态为 `BLOCKED`，必须补充：

```text
阻塞点：
已完成只读探索：
需要审批窗口决定：
```

## 本窗口审批清单

审批窗口收到执行结果后，只做以下检查：

1. 是否只修改允许范围内文件。
2. 是否没有数据库迁移。
3. 是否没有新增权限码。
4. 是否没有新增依赖。
5. 是否没有启动服务或触发外部请求。
6. 是否未触碰 `input_writer`、`contact_searcher`、Local Agent。
7. 是否 Phase 2 三组测试和关联回归通过。
8. 是否 `DouyinPrivateMessageSend.content` 保存替换后文本。
9. 是否微信写入 mock 收到替换后文本。
10. 是否命中日志脱敏。
11. 是否 Spec Reviewer 和 Code Quality Reviewer 都不为 `Rejected`。
12. 是否可以进入 Phase 3 执行包制定。

审批结论只能是：

```text
通过
有条件通过
不通过
```

## 下一阶段

Phase 2 通过后，才允许制定：

```text
Phase 3 抖音AI客服自动回复闭环执行包
```

Phase 3 才能处理 AI 托管触发、账号绑定智能体、自动回复 run 编排和上游发送开关收束；Phase 2 不替 Phase 3 放大业务链路。
