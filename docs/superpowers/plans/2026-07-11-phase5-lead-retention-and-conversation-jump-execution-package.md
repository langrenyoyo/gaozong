# Phase 5 线索留资与对话跳转 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 AI小高线索的留资判定口径，并修复线索列表 / 详情到抖音客服工作台的会话跳转。

**Architecture:** 本阶段不新增表、不新增字段、不跑迁移；只消费 Phase 1 已存在的 `DouyinLead.extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 字段，并兼容旧 `raw_data.contact_extract` 与 `customer_contact`。后端把留资判断收口到 `app/services/lead_management_service.py` 的共享 helper，前端只使用接口返回的标准字段展示和跳转，不自行把 `status=replied` 当留资。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 内存测试库、React、TypeScript、Vite、现有 NewCar 请求上下文。

---

## 审批窗口结论

Phase 4-FIX1 审批通过：

1. “发送流水粒度 vs 决策日志粒度错配”已消除。
2. Phase 4 可从“不通过”更新为“通过”。
3. 用户已确认当前工作区残留是用户自己的修改，Phase 5 执行窗口不得清理、回滚或提交这些残留。
4. 允许进入 Phase 5。

## 阶段目标

1. 已留资权威口径统一为：`extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在即为已留资。
2. 旧数据继续兼容：`raw_data.contact_extract.phone/wechat/all_contacts` 和 `customer_contact` 仍可作为历史兜底。
3. `lead.status == "replied"` 不再代表已留资，只代表销售 / 检测链路已有回复。
4. `/leads`、`/leads/{id}`、`/reports/summary` 使用同一留资 helper。
5. 前端线索列表和详情展示联系方式时优先使用后端标准字段，不用状态推导留资。
6. 线索跳转到真实抖音客服工作台路由 `/douyin-cs/workbench`，参数必须包含 `account_open_id`、`conversation_short_id`、`open_id`。
7. 缺少会话定位字段时，页面给出明确不可跳转原因，不隐藏按钮后让用户无感，也不跳旧假页面。

## 允许修改范围

后端允许文件：

- Modify: `tests/test_leads_management.py`
- Modify: `tests/test_leads_contact_fields.py`
- Modify: `app/services/lead_management_service.py`
- Modify: `app/schemas.py`

前端允许文件：

- Modify: `frontend/src/features/leads/pages/LeadsManagement.tsx`
- Modify: `frontend/src/api/types.ts`

只读核验文件：

- Read-only: `app/models.py`
- Read-only: `app/routers/leads.py`
- Read-only: `app/routers/reports.py`
- Read-only: `app/services/report_service.py`
- Read-only: `app/integrations/douyin_webhook.py`
- Read-only: `apps/leads/webhook_events.py`
- Read-only: `frontend/src/features/routes.ts`
- Read-only: `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
- Read-only: `tests/test_douyin_webhook.py`
- Read-only: `tests/test_douyin_workbench_conversations.py`

## 禁止事项

1. 不新增数据库迁移，不修改 `app/models.py`。
2. 不新增权限码、依赖、环境变量。
3. 不修改发送链路：`app/services/ai_auto_reply_send_service.py`、`app/services/douyin_private_message_send_service.py`、微信通知发送、微信派单发送均不得触碰。
4. 不修改 `apps/xg_douyin_ai_cs/*`，不修改 9100 RAG / AI 客服决策逻辑。
5. 不修改 Local Agent、微信 UI 自动化、`input_writer`、`contact_searcher`、`local_agent_main`。
6. 不进入 Phase 6 智能体与企业号管理，不改商户抖音号授权 CRUD。
7. 不进入日报、销售反馈模板、Excel 发送、AI剪辑、一键过审。
8. 不启动 9000 / 9100 / 19000 / 前端 dev server。
9. 不触发真实 LLM、Milvus、抖音 OpenAPI、微信、巨量广告请求。
10. 不清理、提交或回滚执行窗口开始前已有的用户工作区残留。

## 当前事实

1. `DouyinLead` 已有 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`account_open_id`、`conversation_short_id`、`source_id` 字段。
2. `app/integrations/douyin_webhook.py` 新建线索时已经写入 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts`；本阶段不需要改 webhook 入库。
3. `app/services/lead_management_service.py` 已有 `_contact_values()` 和 `has_retained_contact()`，但当前主要读取旧 `raw_data.contact_extract` 和 `customer_contact`。
4. `report_service.get_summary()` 已通过 `lead_management_service.summary()` 获取 `retained_contact_count`，只要共享 helper 正确，报表统计可同步修复。
5. `LeadOut` 当前会从 `raw_data.contact_extract` 派生 `phone`、`wechat`、`all_extracted_contacts`，但对 ORM 独立列直接返回的兼容不足。
6. 前端 `LeadsManagement.tsx` 当前跳转 URL 为 `/douyin-ai-cs?...`，真实能力路由是 `/douyin-cs/workbench`。
7. `DouyinAiCsWorkbenchPage.tsx` 已能读取 query：`account_open_id`、`conversation_short_id`、`open_id`，并尝试定位会话。

## 调用链

```text
线索列表 / 详情
  -> frontend/src/features/leads/pages/LeadsManagement.tsx
  -> frontend/src/api/leads.ts
  -> GET /leads 或 GET /leads/{id}
  -> app/routers/leads.py
  -> app/services/lead_management_service.py:build_lead_payload
  -> DouyinLead
```

```text
报表汇总
  -> GET /reports/summary
  -> app/routers/reports.py
  -> app/services/report_service.py:get_summary
  -> app/services/lead_management_service.py:summary
  -> has_retained_contact(lead)
```

```text
线索跳转抖音会话
  -> LeadsManagement.tsx 构造 /douyin-cs/workbench query
  -> DouyinAiCsWorkbenchPage.tsx:readConversationJumpParams
  -> account_open_id 定位账号
  -> conversation_short_id + open_id 定位客户会话
```

---

## Task 0: 阶段起点与边界确认

**Files:**
- Read-only: `git status`
- Read-only: `docs/superpowers/plans/2026-07-11-phase5-lead-retention-and-conversation-jump-execution-package.md`

- [ ] **Step 1: 记录阶段起点**

Run:

```bash
git rev-parse HEAD
```

Expected: 输出一个完整 commit hash。把它记录为 Phase 5 起点，回传报告里必须写明。

- [ ] **Step 2: 查看工作区残留但不处理**

Run:

```bash
git status --short --branch
```

Expected: 允许看到用户已有 `.env*`、`tests/test_env_profile_templates.py`、`docs/config/`、历史计划文档残留。不得清理、回滚、提交这些残留。

- [ ] **Step 3: 复述阶段边界**

在执行窗口开始实现前，向审批窗口复述：

```text
本阶段只做线索留资口径、状态展示和对话跳转。
本阶段不做数据库迁移、不做发送链路、不做企业号管理、不做 9100、不做微信自动化。
```

Expected: 得到审批窗口“继续”后再进入 Task 1。

---

## Task 1: 后端红灯测试

**Files:**
- Modify: `tests/test_leads_management.py`
- Modify: `tests/test_leads_contact_fields.py`

- [ ] **Step 1: 增加“独立列算留资，replied 不算留资”的报表测试**

在 `tests/test_leads_management.py` 中 `test_reports_summary_returns_retained_and_high_intent_counts` 后新增：

```python
def test_reports_summary_uses_extracted_contact_columns_not_replied_status():
    db = TestSession()
    try:
        db.add_all(
            [
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="独立手机号",
                    content="想看车，预算十万",
                    source_id="retained-phone",
                    merchant_id="merchant-a",
                    status="pending",
                    extracted_phone="13800001111",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="独立微信",
                    content="问价格",
                    source_id="retained-wechat",
                    merchant_id="merchant-a",
                    status="assigned",
                    extracted_wechat="wx_phase5",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="全部联系方式",
                    content="普通咨询",
                    source_id="retained-all",
                    merchant_id="merchant-a",
                    status="pending",
                    all_extracted_contacts=json.dumps(
                        {"phones": [], "wechats": ["wx_all"], "all": ["wx_all"]},
                        ensure_ascii=False,
                    ),
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="仅销售回复",
                    content="销售回复过但客户未留联系方式",
                    source_id="replied-no-contact",
                    merchant_id="merchant-a",
                    status="replied",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 4
    assert data["retained_contact_count"] == 3
    assert data["replied_count"] == 1
    assert data["retained_contact_rate"] == 75.0
```

当前实现预期失败：`retained_contact_count` 会漏算只存在独立列的线索。

- [ ] **Step 2: 增加 `/leads/{id}` 返回独立列联系方式的测试**

在 `tests/test_leads_contact_fields.py` 中 `test_get_lead_returns_same_contact_extract_fields` 后新增：

```python
def test_get_lead_returns_contact_fields_from_extracted_columns():
    db = TestSession()
    lead = DouyinLead(
        source="douyin",
        lead_type="私信",
        customer_name="新字段客户",
        customer_contact=None,
        content="客户把联系方式发在上游提取字段",
        source_id="column_user_001",
        merchant_id=MERCHANT_ID,
        account_open_id="account_001",
        conversation_short_id="column_conv_001",
        raw_message_text="电话 13900001111 微信 wx_column",
        extracted_phone="13900001111",
        extracted_wechat="wx_column",
        all_extracted_contacts=json.dumps(
            {"phones": ["13900001111"], "wechats": ["wx_column"], "all": ["13900001111", "wx_column"]},
            ensure_ascii=False,
        ),
        contact_extract_status="matched",
        status="pending",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    resp = _client().get(f"/leads/{lead_id}")

    assert resp.status_code == 200
    item = resp.json()
    assert item["phone"] == "13900001111"
    assert item["wechat"] == "wx_column"
    assert item["all_extracted_contacts"] == ["13900001111", "wx_column"]
    assert item["contact_extract_status"] == "matched"
    assert item["original_message_text"] == "电话 13900001111 微信 wx_column"
```

当前实现预期失败：响应仍主要从 `raw_data.contact_extract` 派生字段。

- [ ] **Step 3: 增加 `replied` 状态展示不叫已留资的测试**

在 `tests/test_leads_management.py` 中新增：

```python
def test_replied_status_label_does_not_mean_retained_contact():
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="销售已回复客户",
            content="未留联系方式",
            source_id="status-replied-no-contact",
            merchant_id="merchant-a",
            status="replied",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    response = _client().get(f"/leads/{lead_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status_label"] == "销售已回复"
    assert data["all_extracted_contacts"] == []
```

当前实现预期失败：后端 `STATUS_LABELS["replied"]` 仍是 `已留资`。

- [ ] **Step 4: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_leads_management.py::test_reports_summary_uses_extracted_contact_columns_not_replied_status tests/test_leads_contact_fields.py::test_get_lead_returns_contact_fields_from_extracted_columns tests/test_leads_management.py::test_replied_status_label_does_not_mean_retained_contact -v
```

Expected: 3 个测试至少有 2 个失败，失败点对应留资 helper、响应字段派生或状态标签。

---

## Task 2: 后端统一留资 helper 与响应字段

**Files:**
- Modify: `app/services/lead_management_service.py`
- Modify: `app/schemas.py`
- Test: `tests/test_leads_management.py`
- Test: `tests/test_leads_contact_fields.py`

- [ ] **Step 1: 在 `lead_management_service.py` 增加联系方式规范化 helper**

在 `_contact_extract()` 后、`_contact_values()` 前加入：

```python
def _append_contact_value(values: list[str], value: Any) -> None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized and normalized not in values:
            values.append(normalized)


def _append_all_contact_values(values: list[str], all_contacts: Any) -> None:
    if isinstance(all_contacts, str):
        stripped = all_contacts.strip()
        if not stripped:
            return
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            _append_contact_value(values, stripped)
            return
        _append_all_contact_values(values, parsed)
        return
    if isinstance(all_contacts, dict):
        for key in ("all", "phones", "wechats", "values"):
            _append_all_contact_values(values, all_contacts.get(key))
        return
    if isinstance(all_contacts, list):
        for item in all_contacts:
            if isinstance(item, dict):
                _append_contact_value(values, item.get("value"))
            else:
                _append_contact_value(values, item)
```

- [ ] **Step 2: 改造 `_contact_values()` 和 `has_retained_contact()`**

把现有 `_contact_values()` 与 `has_retained_contact()` 替换为：

```python
def _contact_values(lead: DouyinLead) -> list[str]:
    values: list[str] = []
    _append_contact_value(values, getattr(lead, "extracted_phone", None))
    _append_contact_value(values, getattr(lead, "extracted_wechat", None))
    _append_all_contact_values(values, getattr(lead, "all_extracted_contacts", None))

    extract = _contact_extract(lead)
    for key in ("phone", "wechat"):
        _append_contact_value(values, extract.get(key))
    _append_all_contact_values(values, extract.get("all_contacts"))
    _append_contact_value(values, lead.customer_contact)
    return values


def has_retained_contact(lead: DouyinLead) -> bool:
    """判断线索是否已留资；状态字段不能作为留资依据。"""
    return bool(_contact_values(lead))
```

- [ ] **Step 3: 增加响应字段 helper**

在 `lead_score()` 后新增：

```python
def _lead_contact_payload(lead: DouyinLead) -> dict[str, Any]:
    extract = _contact_extract(lead)
    values = _contact_values(lead)
    phone = getattr(lead, "extracted_phone", None) or extract.get("phone")
    wechat = getattr(lead, "extracted_wechat", None) or extract.get("wechat")
    raw_data = _safe_raw_data(lead)
    return {
        "phone": phone,
        "wechat": wechat,
        "all_extracted_contacts": values,
        "contact_extract_status": getattr(lead, "contact_extract_status", None) or extract.get("status"),
        "original_message_text": getattr(lead, "raw_message_text", None) or raw_data.get("raw_message_text") or lead.content,
    }
```

- [ ] **Step 4: 把 `build_lead_payload()` 接入联系方式字段并修状态文案**

把 `STATUS_LABELS` 中：

```python
"replied": "已留资",
```

改为：

```python
"replied": "销售已回复",
```

在 `build_lead_payload()` 的 `payload` 字典内加入以下字段，放在 `customer_contact` 和 `content` 附近：

```python
        **_lead_contact_payload(lead),
```

Expected: `build_lead_payload()` 返回 dict 时，`LeadOut` 不再只能依赖 `raw_data` 派生联系方式。

- [ ] **Step 5: 补齐 `LeadOut` ORM 兼容**

修改 `app/schemas.py` 的 `_extract_contact_values()`，让它能兼容 JSON 字符串与 dict：

```python
def _extract_contact_values(all_contacts: Any) -> list[str]:
    values: list[str] = []
    if isinstance(all_contacts, str):
        stripped = all_contacts.strip()
        if not stripped:
            return values
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return [stripped]
        return _extract_contact_values(parsed)
    if isinstance(all_contacts, dict):
        for key in ("all", "phones", "wechats", "values"):
            for item in _extract_contact_values(all_contacts.get(key)):
                if item not in values:
                    values.append(item)
        return values
    if not isinstance(all_contacts, list):
        return values
    for item in all_contacts:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return values
```

在 `LeadOut.derive_contact_extract_fields()` 的 ORM 分支 `data` 字典中补入：

```python
                "phone": getattr(value, "extracted_phone", None),
                "wechat": getattr(value, "extracted_wechat", None),
                "all_extracted_contacts": _extract_contact_values(getattr(value, "all_extracted_contacts", None)),
                "contact_extract_status": getattr(value, "contact_extract_status", None),
                "original_message_text": getattr(value, "raw_message_text", None),
```

把后续 raw_data 派生逻辑从 `setdefault` 改成“独立列为空才兜底”：

```python
        data["phone"] = data.get("phone") or contact_extract.get("phone")
        data["wechat"] = data.get("wechat") or contact_extract.get("wechat")
```

并把联系方式集合合并为：

```python
        contact_values = _extract_contact_values(data.get("all_extracted_contacts"))
        for item in _extract_contact_values(contact_extract.get("all_contacts")):
            if item not in contact_values:
                contact_values.append(item)
        for item in (data.get("phone"), data.get("wechat"), data.get("customer_contact")):
            if isinstance(item, str) and item.strip() and item.strip() not in contact_values:
                contact_values.append(item.strip())
        data["all_extracted_contacts"] = contact_values
```

- [ ] **Step 6: 运行后端绿灯测试**

Run:

```bash
python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py -v
```

Expected: 全部通过。

- [ ] **Step 7: 提交后端改动**

Run:

```bash
git add app/services/lead_management_service.py app/schemas.py tests/test_leads_management.py tests/test_leads_contact_fields.py
git commit -m "fix: 统一线索留资判断口径"
```

Expected: 生成 1 个中文提交；不要提交用户已有残留。

---

## Task 3: 前端状态展示与会话跳转

**Files:**
- Modify: `frontend/src/features/leads/pages/LeadsManagement.tsx`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: 修正前端本地状态兜底文案**

在 `LeadsManagement.tsx` 中把：

```ts
replied: "已回复",
```

改为：

```ts
replied: "销售已回复",
```

Expected: 即使后端没有返回 `status_label`，前端也不会把 `replied` 展示成留资含义。

- [ ] **Step 2: 把跳转 helper 改为返回 URL 或明确原因**

把现有 `buildDouyinConversationUrl()` 替换为：

```ts
function buildDouyinConversationJump(lead: Lead): { href: string | null; disabledReason: string | null } {
  const missing: string[] = [];
  if (!lead.account_open_id) missing.push("企业号");
  if (!lead.conversation_short_id) missing.push("会话标识");
  if (!lead.source_id) missing.push("客户 open_id");
  if (missing.length) {
    return {
      href: null,
      disabledReason: `缺少${missing.join("、")}，无法打开抖音会话`,
    };
  }
  const params = new URLSearchParams({
    account_open_id: lead.account_open_id,
    conversation_short_id: lead.conversation_short_id,
    open_id: lead.source_id,
  });
  return { href: `/douyin-cs/workbench?${params.toString()}`, disabledReason: null };
}
```

- [ ] **Step 3: 更新详情页跳转区域**

把详情组件里：

```ts
const conversationUrl = buildDouyinConversationUrl(lead);
```

改为：

```ts
const conversationJump = buildDouyinConversationJump(lead);
```

把详情页链接判断改为：

```tsx
{conversationJump.href ? (
  <a
    href={conversationJump.href}
    className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 text-xs font-semibold text-blue-700 hover:bg-blue-100"
  >
    <MessageCircleIcon size={14} />
    查看抖音会话
  </a>
) : (
  <button
    type="button"
    disabled
    title={conversationJump.disabledReason || "无法打开抖音会话"}
    className="inline-flex h-9 w-full cursor-not-allowed items-center justify-center gap-2 rounded-xl border border-dashed border-[#e4e8f0] bg-[#f8fafc] text-xs font-semibold text-[#8b95a6]"
  >
    <MessageCircleIcon size={14} />
    {conversationJump.disabledReason || "无法打开抖音会话"}
  </button>
)}
```

- [ ] **Step 4: 更新列表行操作区**

在列表渲染中把：

```ts
const conversationUrl = buildDouyinConversationUrl(lead);
```

改为：

```ts
const conversationJump = buildDouyinConversationJump(lead);
```

把操作区只在有 URL 时显示链接的逻辑，改为始终显示“查看抖音会话”入口：

```tsx
{conversationJump.href ? (
  <a
    href={conversationJump.href}
    onClick={(event) => event.stopPropagation()}
    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5 text-[11px] font-semibold text-blue-700 hover:bg-blue-100"
  >
    查看抖音会话
  </a>
) : (
  <button
    type="button"
    title={conversationJump.disabledReason || "无法打开抖音会话"}
    onClick={(event) => {
      event.stopPropagation();
      toast.warning(conversationJump.disabledReason || "无法打开抖音会话");
    }}
    className="inline-flex items-center gap-1 rounded-lg border border-dashed border-[#e4e8f0] bg-[#f8fafc] px-2 py-1.5 text-[11px] font-semibold text-[#8b95a6]"
  >
    查看抖音会话
  </button>
)}
```

Expected: 缺字段时有明确提示；不再静默隐藏入口。

- [ ] **Step 5: 确认类型不需要前端伪造留资**

检查 `frontend/src/api/types.ts` 的 `Lead` 已包含：

```ts
phone?: string | null;
wechat?: string | null;
all_extracted_contacts?: string[];
account_open_id?: string | null;
conversation_short_id?: string | null;
source_id: string | null;
```

如果已存在，仅保留；不要新增重复类型。若 `source_id` 在当前文件不是可空类型，保持现状不做无关调整。

- [ ] **Step 6: 前端构建验证**

在 `frontend` 目录运行：

```bash
npm run build
```

Expected: 构建成功。允许报告既有 chunk size warning；不允许 TypeScript 错误。

- [ ] **Step 7: 提交前端改动**

Run:

```bash
git add frontend/src/features/leads/pages/LeadsManagement.tsx frontend/src/api/types.ts
git commit -m "fix: 修复线索会话跳转入口"
```

Expected: 生成第 2 个中文提交；如果 `frontend/src/api/types.ts` 未实际变化，不要强行提交它。

---

## Task 4: 关联回归与静态边界检查

**Files:**
- Read-only: `tests/test_douyin_webhook.py`
- Read-only: `tests/test_douyin_workbench_conversations.py`
- Read-only: `frontend`

- [ ] **Step 1: 跑 Phase 5 后端专项与关联回归**

Run:

```bash
python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py tests/test_douyin_webhook.py tests/test_douyin_workbench_conversations.py -v
```

Expected: 全部通过。如出现 pre-existing 失败，必须先用阶段起点 diff 证明 Phase 5 未触碰失败文件和失败链路，再交回审批窗口，不得擅自扩大范围修。

- [ ] **Step 2: 跑前端构建**

在 `frontend` 目录运行：

```bash
npm run build
```

Expected: 构建成功。chunk size warning 可如实记录为既有构建提示。

- [ ] **Step 3: 空白检查**

Run:

```bash
git diff --check HEAD~2..HEAD
```

Expected: 无输出。

- [ ] **Step 4: 阶段文件范围检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD
```

Expected: 只允许出现下列文件：

```text
app/services/lead_management_service.py
app/schemas.py
tests/test_leads_management.py
tests/test_leads_contact_fields.py
frontend/src/features/leads/pages/LeadsManagement.tsx
frontend/src/api/types.ts
```

如果 `frontend/src/api/types.ts` 没有实际变化，可不出现。

- [ ] **Step 5: 禁区文件检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD | rg "input_writer|contact_searcher|local_agent_main|apps/xg_douyin_ai_cs|ai_auto_reply_send_service|douyin_private_message_send_service|lead_notifications|notification_service|douyin_ai_cs_proxy|agents|douyin_accounts"
```

Expected: 无输出。若有输出，本阶段越界，必须停止并回滚 Phase 5 自己的越界改动。

- [ ] **Step 6: 旧跳转路径检查**

Run:

```bash
rg -n "/douyin-ai-cs\\?|buildDouyinConversationUrl|href=\\{conversationUrl\\}" frontend/src/features/leads/pages/LeadsManagement.tsx
```

Expected: 无输出。注意 `frontend/src/features/routes.ts` 可以继续保留旧路由重定向，不属于本阶段清理范围。

- [ ] **Step 7: 留资口径静态检查**

Run:

```bash
rg -n "replied.*留资|已留资.*replied|status.*retained|retained.*status" app/services/lead_management_service.py frontend/src/features/leads/pages/LeadsManagement.tsx tests/test_leads_management.py
```

Expected: 无输出，或仅出现测试名 / 注释中表达“replied 不等于留资”的断言说明。若业务代码命中，必须修正。

---

## Task 5: 自审与回传格式

**Files:**
- Read-only: all changed files

- [ ] **Step 1: Spec Reviewer 自审**

逐项确认：

```text
1. extracted_phone 非空算留资。
2. extracted_wechat 非空算留资。
3. all_extracted_contacts 非空算留资。
4. raw_data.contact_extract 与 customer_contact 旧数据仍兼容。
5. status=replied 不算留资。
6. /reports/summary 使用统一 helper。
7. /leads 和 /leads/{id} 返回 phone/wechat/all_extracted_contacts。
8. replied 展示为“销售已回复”，不展示为“已留资”。
9. 跳转路径为 /douyin-cs/workbench。
10. 跳转 query 包含 account_open_id、conversation_short_id、open_id。
11. 缺字段时有明确提示，不跳假页面。
12. 未触碰发送链路、9100、Local Agent、企业号管理、日报、迁移。
```

- [ ] **Step 2: Code Quality Reviewer 自审**

逐项确认：

```text
1. 留资判断只收口在共享 helper，没有在报表、路由、前端各写一套后端口径。
2. JSON 字段解析失败时不会抛 500，字符串旧值仍可兜底。
3. all_extracted_contacts 去重且过滤空字符串。
4. build_lead_payload 返回结构与 LeadOut 类型一致。
5. 前端不新增依赖、不新增全局状态。
6. 前端禁用跳转按钮有 title 和 toast 提示。
7. 没有修改 TypeScript 配置。
```

- [ ] **Step 3: 固定回传报告**

回传审批窗口时使用：

```text
阶段：Phase 5 线索留资与对话跳转
状态：DONE / BLOCKED

提交：
- 写实际后端提交 hash 与中文提交标题
- 写实际前端提交 hash 与中文提交标题

变更文件：
- 逐行列出实际变更文件

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：发送链路、apps/xg_douyin_ai_cs、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化、Phase 6 企业号管理、日报

测试命令与结果：
- python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py tests/test_douyin_webhook.py tests/test_douyin_workbench_conversations.py -v：写实际通过 / 失败数量
- frontend 目录 npm run build：写实际构建结果
- git diff --check HEAD~2..HEAD：写实际输出
- 禁区文件检查：写实际输出
- 旧跳转路径检查：写实际输出

自审结论：
- Spec Reviewer：Approved / Blocked
- Code Quality Reviewer：Approved / Blocked

剩余风险：
- 写实际剩余风险；无风险时写“无”

需要本窗口审批的问题：
- 是否确认 Phase 5 通过并进入 Phase 6 执行包制定？
```

## 验收标准

1. 后端测试证明三个独立留资字段均能被统计和返回。
2. 后端测试证明 `status=replied` 无联系方式时不算留资。
3. 报表 `retained_contact_count` 与 `retained_contact_rate` 使用新口径。
4. 列表 / 详情接口返回 `phone`、`wechat`、`all_extracted_contacts`。
5. 前端构建通过。
6. 前端跳转到 `/douyin-cs/workbench`，不再生成 `/douyin-ai-cs?...`。
7. 缺少 `account_open_id`、`conversation_short_id` 或 `source_id` 时显示明确原因，不跳转。
8. 阶段 diff 不触碰禁区文件。
9. 不清理、不提交、不回滚用户已有工作区残留。

## 回滚方案

如 Phase 5 执行后需要回滚，只回滚本阶段两个提交。先回滚前端提交，再回滚后端提交，提交 hash 以执行窗口回传报告中的实际 hash 为准。

不得使用 `git reset --hard`，不得回滚用户已有工作区残留。
