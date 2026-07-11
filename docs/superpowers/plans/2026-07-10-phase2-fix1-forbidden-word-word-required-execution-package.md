# Phase 2-FIX1 违禁词 word 空白校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 Phase 2 超管违禁词接口对空白 `word` 的拒绝校验，并清理替换服务中的无用上下文字段常量。

**Architecture:** 本修复只收敛 Phase 2 审批发现的两个小问题：`POST/PUT /admin/forbidden-words` 对空白 `word` 返回 `WORD_REQUIRED`，以及删除 `app/services/forbidden_word_service.py` 未实际使用的 `_ALLOWED_CONTEXT_KEYS`。不改发送链路、不改数据库结构、不新增权限码、不碰微信 UI 自动化。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy ORM、pytest。

---

## 阶段定位

阶段名称：`Phase 2-FIX1 违禁词 word 空白校验`

执行窗口：独立执行窗口 / 子代理。

审批窗口：当前窗口只接收结果并审批，不直接编码。

风险等级：`MEDIUM`

原因：本阶段涉及超管接口输入校验和数据库写入前置保护，但不改数据库结构、不接真实发送、不改权限体系。

## 已知当前状态

Phase 2 已完成 3 个提交：

```text
4ca348e feat: 增加违禁词统一替换服务
2e81b17 feat: 增加违禁词超管接口
1e09133 feat: 接入消息发送违禁词替换
```

Phase 2 审批结论为“有条件通过”，条件如下：

1. `app/routers/forbidden_words.py` 中 `create_word()` 和 `update_word()` 对 `word` 做了 `strip()`，但没有拒绝全空白 `word`。
2. `app/services/forbidden_word_service.py` 中 `_ALLOWED_CONTEXT_KEYS` 未实际使用。

当前已知关联回归风险：

```text
tests/test_lead_notifications.py 当前有 8 个既有失败，主因是真实 SQLite 缺少 Phase 1 字段 sales_staff.enable_lead_assignment。
该问题不属于 Phase 2-FIX1，不得在本阶段修复。
```

执行窗口开始前必须运行：

```bash
git status --short --branch
git log --oneline -6
```

如发现除计划文档外还有未提交业务代码，必须停止并回传 `NEEDS_CONTEXT`。

## 本阶段目标

1. `POST /admin/forbidden-words` 收到空白 `word` 时返回 400。
2. `PUT /admin/forbidden-words/{word_id}` 收到空白 `word` 时返回 400。
3. 错误码统一为 `WORD_REQUIRED`。
4. 空白 `safe_word` 现有 `SAFE_WORD_REQUIRED` 行为保持不变。
5. 删除 `_ALLOWED_CONTEXT_KEYS` 未使用常量，避免后续误判为已过滤上下文。
6. 只新增最小回归测试，不改发送链路。

## 允许范围

本阶段允许修改：

```text
app/routers/forbidden_words.py
app/services/forbidden_word_service.py
tests/test_forbidden_words_api.py
```

本阶段允许只读参考：

```text
docs/superpowers/plans/2026-07-10-phase2-forbidden-word-replacement-execution-package.md
app/models.py
app/auth/context.py
app/auth/dependencies.py
tests/test_forbidden_word_service.py
tests/test_forbidden_word_send_integration.py
```

如确需修改其他文件，必须停止并回传 `NEEDS_CONTEXT`。

## 禁止事项

1. 禁止新增数据库迁移。
2. 禁止新增权限码。
3. 禁止新增依赖。
4. 禁止启动 9000 / 9100 / 19000 / 前端服务。
5. 禁止连接 production 数据库、读取 production SQLite、连接 production PostgreSQL。
6. 禁止触发抖音 OpenAPI、巨量接口、LLM、Milvus、微信客户端、支付、短信、邮件等外部资源。
7. 禁止修改 `input_writer`、`contact_searcher`、`local_agent_main`、Local Agent 或微信 UI 自动化底层。
8. 禁止修复 `tests/test_lead_notifications.py` 的 8 个既有失败；该问题单独开测试环境修复执行包。
9. 禁止改发送链路、违禁词替换算法、命中日志结构、hit_count 规则。
10. 禁止改 Phase 2 三个既有提交的历史内容，除非执行窗口明确使用新提交修复；不要 rebase 改写已经审批过的提交。

## 停止门禁

出现以下任一情况，执行窗口必须停止并回传 `NEEDS_CONTEXT`：

1. `app/routers/forbidden_words.py` 中接口结构已与本执行包描述不一致。
2. `tests/test_forbidden_words_api.py` 无法使用现有测试夹具新增用例。
3. 修复需要新增 schema、迁移或权限码。
4. 修复需要改发送链路或微信 UI 自动化。
5. Phase 2 新增测试出现与本修复无关的大面积失败。

## 预期行为

创建接口：

```http
POST /admin/forbidden-words
```

输入：

```json
{
  "library_key": "used_car_sales_base",
  "word": "   ",
  "safe_word": "安全词"
}
```

预期：

```json
{
  "detail": {
    "code": "WORD_REQUIRED",
    "message": "违禁词不能为空"
  }
}
```

更新接口：

```http
PUT /admin/forbidden-words/{word_id}
```

输入：

```json
{
  "word": "   "
}
```

预期：

```json
{
  "detail": {
    "code": "WORD_REQUIRED",
    "message": "违禁词不能为空"
  }
}
```

## TDD 任务拆分

### Task 1: 补空白 word 红灯测试

**Files:**

- Modify: `tests/test_forbidden_words_api.py`

- [ ] **Step 1: 新增创建接口空白 word 测试**

在 `tests/test_forbidden_words_api.py` 中增加：

```python
def test_admin_create_word_rejects_blank_word():
    client = _client(_context())
    _seed_libraries()

    resp = client.post(
        "/admin/forbidden-words",
        json={
            "library_key": "used_car_sales_base",
            "word": "   ",
            "safe_word": "安全词",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "WORD_REQUIRED"
```

- [ ] **Step 2: 新增更新接口空白 word 测试**

在同一文件增加：

```python
def test_admin_update_word_rejects_blank_word():
    client = _client(_context())
    _seed_libraries()

    created = client.post(
        "/admin/forbidden-words",
        json={
            "library_key": "used_car_sales_base",
            "word": "现车很多",
            "safe_word": "可到店详询",
        },
    )
    word_id = created.json()["data"]["id"]

    resp = client.put(
        f"/admin/forbidden-words/{word_id}",
        json={"word": "   "},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "WORD_REQUIRED"
```

如果现有测试 helper 名称不是 `_seed_libraries()`，必须复用文件里已有的实际 seed helper，不得新建第二套重复夹具。

- [ ] **Step 3: 运行红灯**

Run:

```bash
python -m pytest tests/test_forbidden_words_api.py::test_admin_create_word_rejects_blank_word tests/test_forbidden_words_api.py::test_admin_update_word_rejects_blank_word -v
```

Expected:

```text
FAIL
当前接口未拒绝空白 word；至少一个断言不是 400 WORD_REQUIRED。
```

### Task 2: 实现最小接口校验与常量清理

**Files:**

- Modify: `app/routers/forbidden_words.py`
- Modify: `app/services/forbidden_word_service.py`
- Test: `tests/test_forbidden_words_api.py`

- [ ] **Step 1: 在 router 中增加 WORD_REQUIRED 错误**

在 `app/routers/forbidden_words.py` 中增加局部 helper：

```python
def _validate_word_required(value: str) -> str:
    word = value.strip()
    if not word:
        raise _bad_request("WORD_REQUIRED", "违禁词不能为空")
    return word
```

- [ ] **Step 2: 创建接口使用 helper**

把 `create_word()` 中：

```python
word = payload.word.strip()
```

改为：

```python
word = _validate_word_required(payload.word)
```

`safe_word` 原有校验保持不变。

- [ ] **Step 3: 更新接口使用 helper**

把 `update_word()` 中处理 `word` 的逻辑改为：

```python
if "word" in data and data["word"] is not None:
    new_word = _validate_word_required(data["word"])
    if new_word != record.word:
        if _has_casefold_duplicate(db, record.library_id, new_word, exclude_id=record.id):
            raise _bad_request("WORD_DUPLICATED", "同一词库已存在相同违禁词")
        record.word = new_word
```

- [ ] **Step 4: 删除无用常量**

从 `app/services/forbidden_word_service.py` 删除未使用的：

```python
_ALLOWED_CONTEXT_KEYS = (
    "context_type",
    "context_id",
    "conversation_short_id",
    "lead_id",
    "record_id",
    "task_id",
)
```

同时删除紧邻该常量且只解释该常量的注释。不得改替换算法、日志写入、摘要脱敏逻辑。

- [ ] **Step 5: 运行 fix 测试**

Run:

```bash
python -m pytest tests/test_forbidden_words_api.py::test_admin_create_word_rejects_blank_word tests/test_forbidden_words_api.py::test_admin_update_word_rejects_blank_word -v
```

Expected:

```text
2 passed
```

- [ ] **Step 6: 运行 API 全文件回归**

Run:

```bash
python -m pytest tests/test_forbidden_words_api.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 7: 提交**

```bash
git add app/routers/forbidden_words.py app/services/forbidden_word_service.py tests/test_forbidden_words_api.py
git commit -m "fix: 补齐违禁词空白词校验"
```

### Task 3: 阶段总验证

**Files:**

- No code change unless tests expose a Phase 2-FIX1 defect.

- [ ] **Step 1: 跑 Phase 2 / Fix1 相关测试**

Run:

```bash
python -m pytest tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_forbidden_word_send_integration.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 2: 跑最小关联回归**

Run:

```bash
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_admin_autoreply_rollout_api.py tests/test_xiaogao_phase1_schema.py -v
```

Expected:

```text
PASS
```

说明：本阶段不跑 `tests/test_lead_notifications.py` 作为通过门禁，因为该文件已有 8 个与真实 SQLite 迁移状态相关的既有失败。可选运行时必须如实报告结果，不得把既有失败记为本阶段新增失败。

- [ ] **Step 3: 静态检查**

Run:

```bash
rg -n "_ALLOWED_CONTEXT_KEYS|WORD_REQUIRED" app/routers/forbidden_words.py app/services/forbidden_word_service.py tests/test_forbidden_words_api.py
rg -n "input_writer|contact_searcher|local_agent_main" app/routers/forbidden_words.py app/services/forbidden_word_service.py tests/test_forbidden_words_api.py
git diff --check
git status --short --branch
```

Expected:

```text
第 1 条：只允许 WORD_REQUIRED 命中；_ALLOWED_CONTEXT_KEYS 不得命中。
第 2 条：无输出。
git diff --check：无输出。
git status：本阶段业务代码必须已提交；只允许计划文档残留。
```

## 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 创建空白 word | Integration | `word="   "` | 400 `WORD_REQUIRED` | `test_admin_create_word_rejects_blank_word` |
| 更新空白 word | Integration | `PUT word="   "` | 400 `WORD_REQUIRED` | `test_admin_update_word_rejects_blank_word` |
| 现有 safe_word 空白 | Regression | `safe_word="   "` | 400 `SAFE_WORD_REQUIRED` | 既有 API 测试保持通过 |
| 正常创建词条 | Regression | 有效 `word/safe_word` | 创建成功 | `tests/test_forbidden_words_api.py` |
| 发送接入 | Regression | Phase 2 发送接入测试 | 替换行为不变 | `tests/test_forbidden_word_send_integration.py` |

## 回滚方案

如需回滚：

1. 回滚本阶段提交 `fix: 补齐违禁词空白词校验`。
2. 不涉及数据库迁移，无需回滚表结构。
3. 已有 Phase 2 功能保持不变。

## Spec Reviewer 清单

Spec Reviewer 只看需求符合度，必须逐项回答：

1. 是否补齐创建接口空白 `word` 拒绝。
2. 是否补齐更新接口空白 `word` 拒绝。
3. 是否错误码为 `WORD_REQUIRED`。
4. 是否没有改变 `SAFE_WORD_REQUIRED` 现有行为。
5. 是否删除 `_ALLOWED_CONTEXT_KEYS` 未使用常量或证明其已被使用。
6. 是否没有修改发送链路。
7. 是否没有新增迁移、权限码、依赖。
8. 是否没有修 `tests/test_lead_notifications.py` 既有失败。

Spec Reviewer 结论只能是：

```text
Approved
Approved with Conditions
Rejected
```

## Code Quality Reviewer 清单

Code Quality Reviewer 只看实现质量和回归风险，必须逐项回答：

1. 校验 helper 是否足够小且只服务本 router。
2. `create_word()` 和 `update_word()` 是否共用同一校验逻辑。
3. `safe_word` 校验是否未被弱化。
4. 重复词大小写等价检查是否保持不变。
5. 是否没有新增抽象层。
6. 是否没有新增依赖。
7. Phase 2 三组测试是否仍通过。
8. 静态检查是否没有误触微信底层。

Code Quality Reviewer 结论只能是：

```text
Approved
Approved with Conditions
Rejected
```

## 执行窗口回传格式

执行完成后，回传必须使用以下结构：

```text
阶段：Phase 2-FIX1 违禁词 word 空白校验
状态：DONE / BLOCKED

提交：
- <hash> fix: 补齐违禁词空白词校验

变更文件：
- app/routers/forbidden_words.py
- app/services/forbidden_word_service.py
- tests/test_forbidden_words_api.py

数据库迁移：无
新增权限码：无
新增依赖：无
服务启动 / 真实请求：无
未触碰：input_writer、contact_searcher、local_agent_main、Local Agent、前端页面、发送链路

测试命令与结果：
- python -m pytest tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_forbidden_word_send_integration.py -v：<结果>
- python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_admin_autoreply_rollout_api.py tests/test_xiaogao_phase1_schema.py -v：<结果>
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

1. 是否只修改 3 个允许文件。
2. 是否只有 1 个中文提交。
3. 是否没有迁移、权限码、依赖。
4. 是否没有改发送链路。
5. 是否没有触碰微信 UI 自动化底层。
6. 是否新增并通过空白 `word` 创建/更新测试。
7. 是否 Phase 2 三组测试仍通过。
8. 是否最小关联回归通过。
9. 是否 `git diff --check` 通过。
10. 是否可以把 Phase 2 从“有条件通过”更新为“通过”。

审批结论只能是：

```text
通过
有条件通过
不通过
```

## 下一阶段

Phase 2-FIX1 通过后，才进入：

```text
Phase 3 抖音AI客服自动回复闭环执行包制定
```
