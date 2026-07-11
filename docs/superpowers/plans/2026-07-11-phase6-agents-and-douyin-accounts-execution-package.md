# Phase 6 智能体与企业号管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 AI小高智能体与抖音企业号管理的一期边界：智能体归属抖音 AI 客服权限，删除按硬删除执行且 active 企业号绑定时禁止删除；企业号管理保持 auto_wechat 本地授权管理语义。

**Architecture:** 继续使用现有 `AiAgent`、`DouyinAuthorizedAccount`、`DouyinAccountAgentBinding` 三张表，不新增迁移。9000 `/agents` 与独立 `apps/agents` 能力入口共用 `apps/agents/services.py` 的删除与绑定校验；企业号账号删除/取消授权继续走本地状态更新和绑定停用，不调用真实抖音上游授权管理。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 内存测试库、React、TypeScript、Vite、现有 NewCar 权限上下文。

---

## 审批窗口结论

Phase 5-FIX1 已由用户确认通过，可进入 Phase 6。当前窗口只制定执行包，不参与编码。

## 阶段目标

1. AI小高智能体入口和后端接口使用 `auto_wechat:douyin_ai_cs`，不再用微信助手权限 `auto_wechat:agent` 放行。
2. 不新增权限码，不新增 `auto_wechat:ai_agents` 的新用法。
3. 智能体无 active 企业号绑定时按需求硬删除：物理删除 `ai_agents` 当前行，并清理该智能体的知识分类绑定。
4. 智能体有 active 企业号绑定时删除返回 409，提示先解绑，不改智能体与绑定记录。
5. 企业号删除保持本地软删：`douyin_authorized_accounts.bind_status = 4`，active 绑定置为 `deleted`。
6. 企业号取消授权保持本地状态更新：`bind_status = 0`，active 绑定置为 `invalid`，响应继续声明 `upstream_cancel_supported=false`。
7. 抖音企业号管理前端补齐本地管理文案，隐藏 `main_account_id` 数字 ID，避免给用户“真实抖音上游授权管理”的误导。
8. 不修改 9100 RAG / LLM / AI 客服决策逻辑，不触碰发送链路、Local Agent 或微信 UI 自动化。

## 允许修改范围

后端允许文件：

- Modify: `apps/agents/services.py`
- Modify: `apps/agents/routers.py`
- Modify: `apps/agents/dependencies.py`
- Modify: `apps/agents/service.py`
- Modify: `app/services/ai_agent_service.py`
- Modify: `app/routers/agents.py`
- Modify: `app/routers/knowledge_categories.py`
- Modify: `tests/test_ai_agents.py`
- Modify: `tests/test_agents_app.py`
- Modify: `tests/test_knowledge_categories_api.py`
- Modify: `tests/test_douyin_accounts_router.py`
- Modify: `tests/test_douyin_account_agent_binding_service.py`

前端允许文件：

- Modify: `frontend/src/features/capabilities.ts`
- Modify: `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`

只读参考文件：

- Read-only: `app/models.py`
- Read-only: `app/services/douyin_account_agent_binding_service.py`
- Read-only: `frontend/src/api/aiAgents.ts`
- Read-only: `frontend/src/api/douyinAiCsClient.ts`
- Read-only: `frontend/src/features/agents/pages/SuperMerchantAgent.tsx`

## 禁止事项

1. 不新增数据库迁移，不修改 `app/models.py`、`app/schemas.py`。
2. 不新增权限码、依赖、环境变量。
3. 不修改 `app/auth/newcar_client.py` 默认权限清单，除非审批窗口另行授权；本阶段只修能力入口和接口校验。
4. 不修改 `apps/xg_douyin_ai_cs/*`、9100 RAG / LLM / AI 客服决策代码。
5. 不修改发送链路：`app/services/ai_auto_reply_send_service.py`、`app/services/douyin_private_message_send_service.py`、`app/services/notification_service.py`、`app/routers/lead_notifications.py` 均不得触碰。
6. 不修改 `input_writer`、`contact_searcher`、`local_agent_main`、Local Agent、微信 UI 自动化。
7. 不调用真实抖音 OpenAPI，不触发私信发送、微信发送、巨量广告采纳、LLM 或 Milvus 请求。
8. 不启动 9000 / 9100 / 19000 / 前端 dev server。
9. 不清理、不提交、不回滚执行窗口开始前已有的用户工作区残留。
10. 不提前实现 Phase 7 微信真实派单、Phase 8 日报、Phase 9 回访、Phase 11 一键过审、Phase 12 AI剪辑。

## 当前事实

1. `app/routers/agents.py` 当前 `_auth()` 使用 `require_any_permission(["auto_wechat:ai_agents", "auto_wechat:agent"])`。
2. `apps/agents/dependencies.py` 当前 `require_agents_context()` 同样使用 `auto_wechat:ai_agents` / `auto_wechat:agent`。
3. `app/routers/knowledge_categories.py` 当前复用旧智能体权限，导致智能体页面若切到 `auto_wechat:douyin_ai_cs` 后，知识分类接口会被 403。
4. `apps/agents/services.py` 当前 `soft_delete_agent()` 只把 `AiAgent.status` 改为 `deleted`，不是硬删除。
5. `DouyinAccountAgentBinding` 通过 `agent_id` 字符串关联智能体，active 绑定判断应按同商户、同 agent、`status="active"`、`deleted_at is None` 判断，不只看 `is_default`。
6. `app/routers/douyin_accounts.py` 当前企业号取消授权和删除已经是本地状态变更，未调用抖音上游取消授权 API。
7. `frontend/src/features/capabilities.ts` 当前 `agents-center` 使用 `PERMISSIONS.agent`，且 `PERMISSIONS.agent` 的旧别名包含 `auto_wechat:ai_agents`。
8. `DouyinAiCsWorkbenchPage.tsx` 当前企业号列表展示 `account.main_account_id || account.account_open_id`，会暴露数字 ID。

## 调用链

```text
智能体页面
  -> frontend/src/features/capabilities.ts
  -> frontend/src/features/agents/pages/SuperMerchantAgent.tsx
  -> frontend/src/api/aiAgents.ts
  -> GET/POST/PUT/DELETE /agents
  -> app/routers/agents.py
  -> app/services/ai_agent_service.py
  -> apps/agents/services.py
  -> ai_agents / agent_knowledge_categories / douyin_account_agent_bindings
```

```text
独立智能体服务兼容入口
  -> /api/agents
  -> apps/agents/routers.py
  -> apps/agents/dependencies.py:require_agents_context
  -> apps/agents/services.py
```

```text
抖音企业号绑定
  -> DouyinAiCsWorkbenchPage.tsx
  -> frontend/src/api/douyinAiCsClient.ts
  -> /integrations/douyin/accounts
  -> app/routers/douyin_accounts.py
  -> app/services/douyin_account_agent_binding_service.py
  -> douyin_authorized_accounts / douyin_account_agent_bindings
```

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

Expected: 输出完整 commit hash。回传报告中写明 Phase 6 起点。

- [ ] **Step 2: 查看工作区残留但不处理**

Run:

```bash
git status --short --branch
```

Expected: 允许看到用户已有 `apps/xg_douyin_ai_cs/*`、docker、部署脚本、环境模板、历史计划文档等残留。不得清理、回滚或提交这些残留。

- [ ] **Step 3: 复述阶段边界**

执行窗口开始实现前，向审批窗口复述：

```text
本阶段只修 Phase 6 智能体与企业号管理边界。
AI小高智能体归属 auto_wechat:douyin_ai_cs。
智能体 active 企业号绑定时禁止删除；无 active 绑定时硬删除。
企业号取消授权和删除仍是 auto_wechat 本地状态管理，不调用抖音上游授权管理 API。
本阶段不改迁移、模型、schema、9100、发送链路、Local Agent、微信 UI 自动化。
```

Expected: 获得审批窗口继续许可后再进入 Task 1。

---

## Task 1: 后端红灯测试

**Files:**
- Modify: `tests/test_ai_agents.py`
- Modify: `tests/test_agents_app.py`
- Modify: `tests/test_knowledge_categories_api.py`
- Modify: `tests/test_douyin_accounts_router.py`
- Modify: `tests/test_douyin_account_agent_binding_service.py`

- [ ] **Step 1: 让 9000 智能体测试默认使用抖音 AI 客服权限**

在 `tests/test_ai_agents.py` 中导入绑定相关模型：

```python
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount  # noqa: F401
```

把 `_context()` 默认权限从：

```python
permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:ai_agents"],
```

改为：

```python
permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:douyin_ai_cs"],
```

Expected: 现有正向测试表达新权限归属。

- [ ] **Step 2: 新增 9000 权限收敛测试**

替换旧 `test_legacy_agent_permission_is_temporarily_allowed` 为：

```python
def test_agent_permission_no_longer_allows_ai_agent_management():
    client = _client(_context(permission_codes=["auto_wechat:agent"]))

    response = client.get("/agents")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_legacy_ai_agents_permission_no_longer_allows_ai_agent_management():
    client = _client(_context(permission_codes=["auto_wechat:ai_agents"]))

    response = client.get("/agents")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
```

当前实现会失败：旧 `agent` / `ai_agents` 权限仍会放行。

- [ ] **Step 3: 新增 9000 智能体硬删除测试 helper**

在 `tests/test_ai_agents.py` 中新增：

```python
def _insert_account_and_binding(
    *,
    account_open_id: str,
    agent_id: str,
    merchant_id: str = "merchant-a",
    binding_status: str = "active",
    deleted_at=None,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id=account_open_id,
                merchant_id=merchant_id,
                bind_status=1,
                account_name=f"account {account_open_id}",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                agent_id=agent_id,
                is_default=True,
                status=binding_status,
                deleted_at=deleted_at,
                created_by="user-1",
                updated_by="user-1",
            )
        )
        db.commit()
    finally:
        db.close()
```

- [ ] **Step 4: 新增无 active 绑定时硬删除测试**

在 `tests/test_ai_agents.py` 中新增：

```python
def test_delete_agent_without_active_binding_hard_deletes_row():
    client = _client(_context())
    agent = _create_agent(client)

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 200
    assert response.json()["data"]["agent_id"] == agent["agent_id"]
    listed = client.get("/agents")
    assert listed.status_code == 200
    assert listed.json()["data"] == []

    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).first() is None
    finally:
        db.close()
```

当前实现会失败：数据库中仍有 `status="deleted"` 的智能体行。

- [ ] **Step 5: 新增 active 企业号绑定禁止删除测试**

在 `tests/test_ai_agents.py` 中新增：

```python
def test_delete_agent_with_active_douyin_account_binding_returns_409():
    client = _client(_context())
    agent = _create_agent(client)
    _insert_account_and_binding(account_open_id="account-open-1", agent_id=agent["agent_id"])

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AI_AGENT_ACTIVE_BINDING_EXISTS"

    db = TestSession()
    try:
        row = db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).one()
        assert row.status == "active"
    finally:
        db.close()
```

当前实现会失败：旧逻辑会软删。

- [ ] **Step 6: 新增非 active 历史绑定不阻塞硬删除测试**

在 `tests/test_ai_agents.py` 中新增：

```python
def test_delete_agent_ignores_inactive_douyin_account_binding():
    client = _client(_context())
    agent = _create_agent(client)
    _insert_account_and_binding(
        account_open_id="account-open-1",
        agent_id=agent["agent_id"],
        binding_status="unbound",
    )

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 200
    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).first() is None
        binding = db.query(DouyinAccountAgentBinding).filter_by(agent_id=agent["agent_id"]).one()
        assert binding.status == "unbound"
    finally:
        db.close()
```

Expected: 历史绑定保留审计，不阻塞删除。

- [ ] **Step 7: 独立 `apps/agents` 测试同步**

在 `tests/test_agents_app.py` 中把 `_client()` 默认权限改为：

```python
"permission_codes": permissions or ["auto_wechat:douyin_ai_cs"],
```

把旧 `test_agents_app_rejects_missing_permission_and_keeps_legacy_agent_permission` 改为：

```python
def test_agents_app_rejects_missing_and_legacy_agent_permission():
    denied = _client(permissions=["auto_wechat:leads"]).get("/api/agents")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    legacy_agent = _client(permissions=["auto_wechat:agent"]).get("/api/agents")
    assert legacy_agent.status_code == 403
    assert legacy_agent.json()["detail"]["code"] == "PERMISSION_DENIED"

    legacy_ai_agents = _client(permissions=["auto_wechat:ai_agents"]).get("/api/agents")
    assert legacy_ai_agents.status_code == 403
    assert legacy_ai_agents.json()["detail"]["code"] == "PERMISSION_DENIED"

    allowed = _client(permissions=["auto_wechat:douyin_ai_cs"]).get("/api/agents")
    assert allowed.status_code == 200
```

并在 `test_agents_app_root_health_openapi_and_crud_use_gateway_context` 的删除断言后补充数据库硬删除断言：

```python
    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=created["agent_id"]).first() is None
    finally:
        db.close()
```

当前实现会失败：旧权限仍放行，删除仍是软删。

- [ ] **Step 8: 知识分类接口权限同步测试**

在 `tests/test_knowledge_categories_api.py` 中把 `_context()` 默认权限改为：

```python
permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:douyin_ai_cs"],
```

新增：

```python
def test_get_knowledge_categories_requires_douyin_ai_cs_permission():
    denied = _client(_context(merchant_id="merchant-a", permission_codes=["auto_wechat:agent"])).get(
        "/knowledge-categories"
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    allowed = _client(_context(merchant_id="merchant-a", permission_codes=["auto_wechat:douyin_ai_cs"])).get(
        "/knowledge-categories"
    )
    assert allowed.status_code == 200
```

当前实现会失败：`auto_wechat:douyin_ai_cs` 不能访问知识分类，`agent` 会被放行。

- [ ] **Step 9: 企业号本地删除和取消授权保护测试**

`tests/test_douyin_accounts_router.py` 已有以下保护测试，执行窗口只需补充一个“无上游取消能力”字段回归，若现有断言已覆盖可只保留：

```python
def test_cancel_authorization_declares_upstream_cancel_not_supported():
    _insert_account()
    _insert_agent()
    _bind_account()
    client = _client()

    response = client.post("/integrations/douyin/accounts/account-open-1/cancel-authorization")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["upstream_cancel_supported"] is False
    assert data["authorization_status"] == "unauthorized"
    assert data["binding_status"] == "invalid"
```

Expected: 该保护测试应通过；若失败，必须先确认是否被本阶段改坏。

- [ ] **Step 10: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py -v
```

Expected: 新增权限和硬删除测试失败，现有企业号保护测试不在本红灯命令中强制失败。

---

## Task 2: 智能体硬删除和 active 绑定保护实现

**Files:**
- Modify: `apps/agents/services.py`
- Modify: `apps/agents/routers.py`
- Modify: `apps/agents/service.py`
- Modify: `app/services/ai_agent_service.py`
- Modify: `app/routers/agents.py`

- [ ] **Step 1: 在共享服务中增加 active 企业号绑定判断**

在 `apps/agents/services.py` 中导入：

```python
from typing import Any

from app.models import AgentKnowledgeCategory, AiAgent, DouyinAccountAgentBinding, KnowledgeCategory
```

新增：

```python
ACTIVE_ACCOUNT_BINDING_STATUS = "active"
ACTIVE_BINDING_BLOCK_DELETE_ERROR = "AI_AGENT_ACTIVE_BINDING_EXISTS"
```

新增 helper：

```python
def has_active_douyin_account_binding(db: Session, *, merchant_id: str, agent_id: str) -> bool:
    """判断智能体是否仍被抖音企业号 active 绑定。"""
    return (
        db.query(DouyinAccountAgentBinding.id)
        .filter(
            DouyinAccountAgentBinding.merchant_id == merchant_id,
            DouyinAccountAgentBinding.agent_id == agent_id,
            DouyinAccountAgentBinding.status == ACTIVE_ACCOUNT_BINDING_STATUS,
            DouyinAccountAgentBinding.deleted_at.is_(None),
        )
        .first()
        is not None
    )
```

注意：不要加 `is_default=True` 作为阻断条件；需求是“绑定时禁止删除”，任何 active 绑定都应阻断。

- [ ] **Step 2: 新增硬删除函数**

在 `apps/agents/services.py` 中新增：

```python
def hard_delete_agent(db: Session, agent: AiAgent) -> dict[str, Any]:
    """硬删除未被企业号 active 绑定的智能体。"""
    if has_active_douyin_account_binding(db, merchant_id=agent.merchant_id, agent_id=agent.agent_id):
        raise ValueError(ACTIVE_BINDING_BLOCK_DELETE_ERROR)

    payload = {column.name: getattr(agent, column.name) for column in AiAgent.__table__.columns}
    db.query(AgentKnowledgeCategory).filter(
        AgentKnowledgeCategory.merchant_id == agent.merchant_id,
        AgentKnowledgeCategory.agent_id == agent.agent_id,
    ).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()
    return payload
```

说明：本阶段只物理删除智能体和该智能体知识分类绑定；不删除历史 `douyin_account_agent_bindings` 审计行。active 绑定已在删除前阻断。

- [ ] **Step 3: 保留兼容导出但不再让路由调用软删除**

在 `apps/agents/services.py` 中保留旧 `soft_delete_agent()` 作为兼容包装：

```python
def soft_delete_agent(db: Session, agent: AiAgent) -> dict[str, Any]:
    """兼容旧导出；一期智能体删除已改为硬删除。"""
    return hard_delete_agent(db, agent)
```

Expected: 旧导入不崩，但所有路由都应改为调用 `hard_delete_agent()`。

- [ ] **Step 4: 更新兼容导出**

在 `app/services/ai_agent_service.py` 和 `apps/agents/service.py` 的导入与 `__all__` 中增加：

```python
ACTIVE_BINDING_BLOCK_DELETE_ERROR,
hard_delete_agent,
has_active_douyin_account_binding,
```

保留 `soft_delete_agent` 兼容导出，但执行窗口的路由不得继续调用它。

- [ ] **Step 5: 9000 路由把绑定冲突映射为 409**

在 `app/routers/agents.py` 中新增：

```python
def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})
```

把 `delete_agent()` 中删除调用改为：

```python
    try:
        deleted = ai_agent_service.hard_delete_agent(db, agent)
    except ValueError as exc:
        if str(exc) == ai_agent_service.ACTIVE_BINDING_BLOCK_DELETE_ERROR:
            raise _conflict(str(exc), "智能体已绑定抖音企业号，请先解绑后再删除") from exc
        raise _bad_request(str(exc), "智能体删除失败") from exc
    return {"success": True, "data": deleted, "message": "success"}
```

- [ ] **Step 6: 独立 `apps/agents` 路由同步 409 映射**

在 `apps/agents/routers.py` 中新增同等 `_conflict()`，并将删除逻辑改为：

```python
    try:
        deleted = agents_service.hard_delete_agent(db, agent)
    except ValueError as exc:
        if str(exc) == agents_service.ACTIVE_BINDING_BLOCK_DELETE_ERROR:
            raise _conflict(str(exc), "智能体已绑定抖音企业号，请先解绑后再删除") from exc
        raise _bad_request(str(exc), "智能体删除失败") from exc
    return {"success": True, "data": deleted, "message": "success"}
```

- [ ] **Step 7: 运行智能体删除专项测试**

Run:

```bash
python -m pytest tests/test_ai_agents.py tests/test_agents_app.py -v
```

Expected: 硬删除和 409 测试通过；权限测试仍可能失败，留给 Task 3。

- [ ] **Step 8: 提交智能体删除改动**

Run:

```bash
git add apps/agents/services.py apps/agents/routers.py apps/agents/service.py app/services/ai_agent_service.py app/routers/agents.py tests/test_ai_agents.py tests/test_agents_app.py
git commit -m "fix: 智能体删除改为绑定保护硬删除"
```

---

## Task 3: 权限入口统一到抖音 AI 客服权限

**Files:**
- Modify: `app/routers/agents.py`
- Modify: `apps/agents/dependencies.py`
- Modify: `app/routers/knowledge_categories.py`
- Modify: `frontend/src/features/capabilities.ts`
- Modify: `tests/test_ai_agents.py`
- Modify: `tests/test_agents_app.py`
- Modify: `tests/test_knowledge_categories_api.py`

- [ ] **Step 1: 9000 智能体路由改用 `auto_wechat:douyin_ai_cs`**

在 `app/routers/agents.py` 中把导入：

```python
from app.auth.dependencies import get_request_context_required, require_any_permission
```

改为：

```python
from app.auth.dependencies import get_request_context_required, require_permission
```

把 `_auth()` 改为：

```python
def _auth(context: RequestContext) -> RequestContext:
    """校验 AI小高智能体权限；智能体归属抖音 AI 客服闭环。"""
    return require_permission("auto_wechat:douyin_ai_cs")(context)
```

- [ ] **Step 2: 独立 `apps/agents` 权限依赖同步**

在 `apps/agents/dependencies.py` 中把：

```python
if not _has_any_permission(context, ["auto_wechat:ai_agents", "auto_wechat:agent"]):
```

改为：

```python
if not _has_any_permission(context, ["auto_wechat:douyin_ai_cs"]):
```

错误消息保留“缺少 AI小高智能体权限”即可。

- [ ] **Step 3: 知识分类接口跟随智能体权限**

在 `app/routers/knowledge_categories.py` 中把导入：

```python
from app.auth.dependencies import get_request_context_required, require_any_permission
```

改为：

```python
from app.auth.dependencies import get_request_context_required, require_permission
```

把 `_auth()` 改为：

```python
def _auth(context: RequestContext) -> RequestContext:
    """知识分类当前服务于 AI小高智能体配置，跟随抖音 AI 客服权限。"""
    return require_permission("auto_wechat:douyin_ai_cs")(context)
```

- [ ] **Step 4: 前端能力入口改到抖音 AI 客服权限**

在 `frontend/src/features/capabilities.ts` 中把 `agents-center` 的权限改为：

```ts
permissionCodes: [PERMISSIONS.douyinAiCs],
```

把旧别名：

```ts
[PERMISSIONS.agent]: ["auto_wechat:wechat_assistant", "auto_wechat:wechat_agent", "auto_wechat:ai_agents"],
```

改为：

```ts
[PERMISSIONS.agent]: ["auto_wechat:wechat_assistant", "auto_wechat:wechat_agent"],
```

Expected: AI小高智能体不再借用微信助手权限，旧 `auto_wechat:ai_agents` 也不再让用户看到微信助手入口。

- [ ] **Step 5: 运行权限专项测试**

Run:

```bash
python -m pytest tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py -v
```

Expected: 全部通过。

- [ ] **Step 6: 前端能力静态检查**

Run:

```bash
rg -n "agents-center|permissionCodes: \\[PERMISSIONS\\.douyinAiCs\\]|auto_wechat:ai_agents|PERMISSIONS\\.agent" frontend/src/features/capabilities.ts
```

Expected:

```text
agents-center 附近出现 permissionCodes: [PERMISSIONS.douyinAiCs]
legacyPermissionAliases[PERMISSIONS.agent] 中不再包含 auto_wechat:ai_agents
```

- [ ] **Step 7: 提交权限改动**

Run:

```bash
git add app/routers/agents.py apps/agents/dependencies.py app/routers/knowledge_categories.py frontend/src/features/capabilities.ts tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py
git commit -m "fix: 统一智能体入口权限"
```

---

## Task 4: 企业号本地管理语义与前端展示字段

**Files:**
- Modify: `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
- Modify: `tests/test_douyin_accounts_router.py`
- Modify: `tests/test_douyin_account_agent_binding_service.py`

- [ ] **Step 1: 确认企业号删除和取消授权保护测试**

Run:

```bash
python -m pytest tests/test_douyin_accounts_router.py tests/test_douyin_account_agent_binding_service.py -v
```

Expected: 企业号删除软删、取消授权本地置无效、绑定停用、跨商户拒绝等现有测试通过。若失败，不得改企业号语义去迎合失败，先确认是否是本阶段前序改动破坏。

- [ ] **Step 2: 前端增加账号标识展示 helper**

在 `DouyinAiCsWorkbenchPage.tsx` 的 `compactOpenId()` 附近新增：

```ts
function accountIdentityText(account: DouyinAccountItem): string {
  return account.account_open_id ? `账号标识 ${compactOpenId(account.account_open_id)}` : "账号标识 -";
}
```

Expected: 不再展示 `main_account_id`。

- [ ] **Step 3: 企业号列表副标题改为本地管理语义**

把：

```tsx
{accountListSource ? "正式企业号绑定" : "企业号绑定"}
```

改为：

```tsx
商户本地授权管理
```

如果 TypeScript 要求 JSX 字符串，写成：

```tsx
{"商户本地授权管理"}
```

- [ ] **Step 4: 企业号列表隐藏 `main_account_id`**

把列表中：

```tsx
{account.main_account_id || account.account_open_id}
```

改为：

```tsx
{accountIdentityText(account)}
```

- [ ] **Step 5: 空列表提示收敛为本地管理**

把：

```tsx
<EmptyState text="暂无抖音号：未发现授权账号或历史私信事件，请扫码授权。" />
```

改为：

```tsx
<EmptyState text="暂无抖音号：请在商户本地授权管理中添加抖音号。" />
```

- [ ] **Step 6: 企业号前端静态检查**

Run:

```bash
rg -n "正式企业号绑定|account\\.main_account_id|真实上游授权|抖音上游授权" frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx
```

Expected: 无输出。

Run:

```bash
rg -n "商户本地授权管理|accountIdentityText" frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx
```

Expected: 能看到新 helper 和本地管理文案。

- [ ] **Step 7: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: 构建成功。允许既有 chunk size warning；不允许 TypeScript 错误。

- [ ] **Step 8: 提交企业号前端展示改动**

Run:

```bash
git add frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx tests/test_douyin_accounts_router.py tests/test_douyin_account_agent_binding_service.py
git commit -m "fix: 收敛企业号本地管理展示"
```

如果两个企业号测试文件未实际修改，不要强行 `git add`。

---

## Task 5: 全阶段验证与越界检查

**Files:**
- Read-only: all changed files

- [ ] **Step 1: 后端专项回归**

Run:

```bash
python -m pytest tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py tests/test_douyin_accounts_router.py tests/test_douyin_account_agent_binding_service.py -v
```

Expected: 全部通过。

- [ ] **Step 2: 关联回归**

Run:

```bash
python -m pytest tests/test_douyin_ai_cs_proxy.py tests/test_douyin_autoreply_settings_api.py tests/test_admin_autoreply_rollout_api.py -v
```

Expected: 全部通过。若失败，必须做阶段起点对照，证明是否为既有失败；不能带未解释失败回传。

- [ ] **Step 3: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: 构建成功。仅允许既有 warning。

- [ ] **Step 4: 空白检查**

使用 Task 0 记录的阶段起点：

```bash
git diff --check <phase6_start_commit>..HEAD -- apps/agents/services.py apps/agents/routers.py apps/agents/dependencies.py apps/agents/service.py app/services/ai_agent_service.py app/routers/agents.py app/routers/knowledge_categories.py frontend/src/features/capabilities.ts frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py tests/test_douyin_accounts_router.py tests/test_douyin_account_agent_binding_service.py
```

Expected: 无输出。

- [ ] **Step 5: 阶段 diff 文件检查**

Run:

```bash
git diff --name-only <phase6_start_commit>..HEAD
```

Expected: 只允许出现：

```text
app/routers/agents.py
app/routers/knowledge_categories.py
app/services/ai_agent_service.py
apps/agents/dependencies.py
apps/agents/routers.py
apps/agents/service.py
apps/agents/services.py
frontend/src/features/capabilities.ts
frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx
tests/test_ai_agents.py
tests/test_agents_app.py
tests/test_knowledge_categories_api.py
tests/test_douyin_accounts_router.py
tests/test_douyin_account_agent_binding_service.py
```

`tests/test_douyin_accounts_router.py`、`tests/test_douyin_account_agent_binding_service.py` 如果未改动可以不出现。

- [ ] **Step 6: 禁区文件检查**

Run:

```bash
git diff --name-only <phase6_start_commit>..HEAD | rg "app/models.py|app/schemas.py|migrations/|apps/xg_douyin_ai_cs|ai_auto_reply_send_service|douyin_private_message_send_service|notification_service|lead_notifications|input_writer|contact_searcher|local_agent_main|local_agent_exe_entry"
```

Expected: 无输出。若出现任何禁区文件，必须停止并回退本阶段越界改动。

- [ ] **Step 7: 权限静态检查**

Run:

```bash
rg -n "require_any_permission\\(\\[\"auto_wechat:ai_agents\"|require_any_permission\\(\\[\"auto_wechat:ai_agents\", \"auto_wechat:agent\"\\]|soft_delete_agent\\(" app/routers/agents.py apps/agents app/routers/knowledge_categories.py
```

Expected: 无输出。`soft_delete_agent` 可以作为兼容函数定义存在于 `apps/agents/services.py`，但路由中不得调用。若该命令命中兼容函数定义，回传中说明只保留兼容导出，且路由调用已改为 `hard_delete_agent`。

- [ ] **Step 8: 企业号本地管理静态检查**

Run:

```bash
rg -n "account\\.main_account_id|正式企业号绑定|upstream_cancel_supported.*true|requests\\.|httpx\\.|aiohttp" app/routers/douyin_accounts.py frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx
```

Expected: 不应出现前端 `account.main_account_id` 或“正式企业号绑定”；`app/routers/douyin_accounts.py` 不应新增网络请求库调用；`upstream_cancel_supported` 只能为 `False`。

- [ ] **Step 9: 工作区残留说明**

Run:

```bash
git status --short --branch
```

Expected: 本阶段代码文件已提交。若仍有用户残留，逐项说明“不属于 Phase 6 引入”，不得清理。

---

## Task 6: 自审与回传

**Files:**
- Read-only: all changed files

- [ ] **Step 1: Spec Reviewer 自审**

逐项确认：

```text
1. AI小高智能体 9000 /agents 接口需要 auto_wechat:douyin_ai_cs。
2. 独立 apps/agents /api/agents 入口需要 auto_wechat:douyin_ai_cs。
3. 知识分类接口跟随智能体页面权限，持 douyin_ai_cs 可用。
4. auto_wechat:agent 不再放行 AI小高智能体管理。
5. auto_wechat:ai_agents 不再作为 AI小高智能体入口权限。
6. 智能体无 active 企业号绑定时物理删除 ai_agents 行。
7. 智能体 active 企业号绑定时删除返回 409，并提示先解绑。
8. 非 active 历史企业号绑定不阻止智能体硬删除。
9. 企业号取消授权仍是本地 bind_status=0，active 绑定 invalid，upstream_cancel_supported=false。
10. 企业号删除仍是本地 bind_status=4，active 绑定 deleted。
11. 企业号列表不展示 main_account_id，文案表达为商户本地授权管理。
12. 未新增迁移、权限码、依赖、环境变量。
13. 未触碰 9100、发送链路、Local Agent、微信 UI 自动化。
```

- [ ] **Step 2: Code Quality Reviewer 自审**

逐项确认：

```text
1. active 绑定判断集中在 apps/agents/services.py，不在两个路由里重复查询。
2. 硬删除先检查 active 绑定，再删除 agent_knowledge_categories 和 ai_agents，事务边界清晰。
3. 历史 douyin_account_agent_bindings 不被物理删除，保留审计。
4. 409 错误码和消息在 9000 /agents 与 apps/agents /api/agents 中一致。
5. 权限修改没有改 NewCar 鉴权解析或默认 mock 权限。
6. 前端没有新增依赖、全局状态或新路由。
7. 企业号前端只改展示和提示，没有改发送、授权轮询或会话工作台逻辑。
8. 测试覆盖权限、硬删除、绑定阻断、企业号本地状态。
```

- [ ] **Step 3: 固定回传格式**

回传审批窗口时使用：

```text
阶段：Phase 6 智能体与企业号管理
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED

阶段起点：
- <phase6_start_commit>

提交：
- <hash> fix: 智能体删除改为绑定保护硬删除
- <hash> fix: 统一智能体入口权限
- <hash> fix: 收敛企业号本地管理展示

变更文件：
- apps/agents/services.py
- apps/agents/routers.py
- apps/agents/dependencies.py
- apps/agents/service.py
- app/services/ai_agent_service.py
- app/routers/agents.py
- app/routers/knowledge_categories.py
- frontend/src/features/capabilities.ts
- frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx
- tests/test_ai_agents.py
- tests/test_agents_app.py
- tests/test_knowledge_categories_api.py
- tests/test_douyin_accounts_router.py（如实际修改才列）
- tests/test_douyin_account_agent_binding_service.py（如实际修改才列）

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：app/models.py、app/schemas.py、migrations、apps/xg_douyin_ai_cs、发送链路、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化

测试命令与结果：
- python -m pytest tests/test_ai_agents.py tests/test_agents_app.py tests/test_knowledge_categories_api.py tests/test_douyin_accounts_router.py tests/test_douyin_account_agent_binding_service.py -v：<实际结果>
- python -m pytest tests/test_douyin_ai_cs_proxy.py tests/test_douyin_autoreply_settings_api.py tests/test_admin_autoreply_rollout_api.py -v：<实际结果>
- cd frontend && npm run build：<实际结果>
- git diff --check <phase6_start_commit>..HEAD：<实际结果>
- 阶段 diff 文件检查：<实际结果>
- 禁区文件检查：<实际结果>
- 权限静态检查：<实际结果>
- 企业号本地管理静态检查：<实际结果>

自审结论：
- Spec Reviewer：Approved / Needs Fix
- Code Quality Reviewer：Approved / Needs Fix

剩余风险：
- <如实填写；无则写“无”>

需要本窗口审批的问题：
- 是否确认 Phase 6 通过？
- 是否可以进入 Phase 7 执行包制定？
```

## 验收标准

1. `/agents` 与 `/api/agents` 持 `auto_wechat:douyin_ai_cs` 可访问，持 `auto_wechat:agent` 不可访问。
2. 智能体无 active 企业号绑定时，删除后 `ai_agents` 查不到该 `agent_id`。
3. 智能体有 active 企业号绑定时，删除接口返回 409 `AI_AGENT_ACTIVE_BINDING_EXISTS`，数据不变。
4. 非 active 历史绑定不阻止智能体硬删除。
5. 企业号取消授权仍为本地状态更新，响应 `upstream_cancel_supported=false`。
6. 企业号删除仍为软删并停用 active 绑定。
7. 前端 AI小高智能体能力中心使用 `PERMISSIONS.douyinAiCs`。
8. 前端企业号列表不展示 `main_account_id`，页面文案表达“商户本地授权管理”。
9. 本阶段没有新增迁移、权限码、依赖、环境变量，没有触碰 9100、发送链路或 Local Agent。

## 回滚方案

若需要回滚，只回滚 Phase 6 的提交，不回滚用户工作区残留，不使用 `git reset --hard`。

推荐顺序：

```bash
git revert <企业号前端展示_commit_hash>
git revert <权限统一_commit_hash>
git revert <智能体硬删除_commit_hash>
```

回滚影响：

1. 智能体删除会恢复为旧软删除语义。
2. 智能体入口会恢复旧 `ai_agents/agent` 权限兼容。
3. 企业号前端会恢复旧展示文案。

不得回滚 Phase 5 / Phase 5-FIX1，也不得清理用户未提交文件。
