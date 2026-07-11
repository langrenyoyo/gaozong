# Phase 5-FIX1 留资权威口径收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把“已留资”的统计、标签和评分权威口径收敛为只看 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在，同时保留旧联系方式展示兼容。

**Architecture:** 后端拆分“权威留资 helper”和“展示联系方式 helper”，让 `/reports/summary`、线索评分和高意向判断只依赖权威 helper，线索列表 / 详情仍可展示 `raw_data.contact_extract` 与 `customer_contact` 旧数据。前端同步拆分运营标签判断与联系方式展示，避免把 `customer_contact` 误标为已留资。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic、SQLite 测试库、React、TypeScript、Vite。

---

## 审批窗口结论

Phase 5 主体有条件通过，但暂不进入 Phase 6。执行窗口必须先完成本 FIX1：

1. `customer_contact` 只能作为旧数据展示兜底，不能参与“已留资”判断、报表统计、运营标签或线索评分。
2. `raw_data.contact_extract` 只能作为旧数据展示兜底；一期权威留资判断只看三个独立列：`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`。
3. 不清理、不提交、不回滚当前工作区中用户已有残留。

## 阶段目标

1. 后端 `has_retained_contact()` 只看 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts`。
2. 后端 `_lead_contact_payload()` 继续展示旧 `raw_data.contact_extract` 和 `customer_contact`，保持历史线索可读。
3. `lead_score()`、`is_high_intent()` 自动跟随新的 `has_retained_contact()`，仅有 `customer_contact` 的线索不加留资分、不算高意向。
4. `/reports/summary` 中 `retained_contact_count`、`retained_contact_rate` 使用权威口径。
5. 前端运营标签 `已留资` 只看后端返回的 `phone`、`wechat`、`all_extracted_contacts`，不看 `customer_contact`。
6. 前端联系方式展示仍可显示 `customer_contact` 作为旧数据兜底。
7. 顺手修正 Phase 5 遗留的两处文案：表头“联系电话”改“联系方式”；跳转缺字段提示“客户 open_id”改“客户身份标识”。

## 允许修改范围

- Modify: `app/services/lead_management_service.py`
- Modify: `tests/test_leads_management.py`
- Modify: `frontend/src/features/leads/pages/LeadsManagement.tsx`
- Optional Modify: `tests/test_leads_contact_fields.py`

只有在执行窗口发现展示兼容断言必须补充说明时，才允许修改 `tests/test_leads_contact_fields.py`。本 FIX1 不应修改 `app/schemas.py`。

## 禁止事项

1. 不新增数据库迁移，不修改 `app/models.py`。
2. 不新增权限码、依赖、环境变量。
3. 不修改发送链路：`ai_auto_reply_send_service.py`、`douyin_private_message_send_service.py`、`lead_notifications.py`、`notification_service.py` 均不得触碰。
4. 不修改 `apps/xg_douyin_ai_cs/*`、9100 RAG / AI 客服逻辑。
5. 不修改 `input_writer`、`contact_searcher`、`local_agent_main`、Local Agent、微信 UI 自动化。
6. 不进入 Phase 6 企业号管理、智能体绑定、日报、销售反馈模板、AI 剪辑、一键过审。
7. 不启动 9000 / 9100 / 19000 / 前端 dev server。
8. 不触发真实 LLM、Milvus、抖音 OpenAPI、微信发送或私信发送。
9. 不清理、不提交、不回滚执行窗口开始前已有的用户工作区残留。

## 当前事实

1. `app/services/lead_management_service.py` 当前 `_contact_values(lead)` 同时读取三个独立列、`raw_data.contact_extract` 和 `lead.customer_contact`。
2. `has_retained_contact(lead)` 当前直接 `return bool(_contact_values(lead))`，因此仅有 `customer_contact` 的旧线索会被算作“已留资”。
3. `_lead_contact_payload(lead)` 当前使用 `_contact_values(lead)` 给 `all_extracted_contacts`，这适合作为展示兼容，但不适合作为权威统计口径。
4. `frontend/src/features/leads/pages/LeadsManagement.tsx` 当前 `getLeadContactValues(lead)` 读取 `lead.customer_contact`，`hasRetainedContact(lead)` 又直接复用它，因此前端“已留资”标签也会误判。
5. `tests/test_leads_contact_fields.py` 已覆盖仅有 `customer_contact="legacy_contact"` 时详情接口仍展示 `all_extracted_contacts == ["legacy_contact"]`，这条展示兼容应保留。

## 调用链

```text
/reports/summary
  -> app/routers/reports.py
  -> app/services/report_service.py:get_summary
  -> app/services/lead_management_service.py:summary
  -> has_retained_contact(lead)
```

```text
/leads 和 /leads/{id}
  -> app/routers/leads.py
  -> app/services/lead_management_service.py:build_lead_payload
  -> _lead_contact_payload(lead)
  -> phone / wechat / all_extracted_contacts 展示字段
```

```text
线索列表运营标签
  -> frontend/src/features/leads/pages/LeadsManagement.tsx
  -> deriveOperationalTags()
  -> hasRetainedContact()
```

---

## Task 0: 阶段起点与边界确认

**Files:**
- Read-only: `git status`
- Read-only: `app/services/lead_management_service.py`
- Read-only: `frontend/src/features/leads/pages/LeadsManagement.tsx`

- [ ] **Step 1: 记录阶段起点**

Run:

```bash
git rev-parse HEAD
```

Expected: 输出完整 commit hash。回传报告中写明 Phase 5-FIX1 起点。

- [ ] **Step 2: 查看工作区残留但不处理**

Run:

```bash
git status --short --branch
```

Expected: 允许看到用户已有 `.env*`、`apps/xg_douyin_ai_cs/*`、docker、脚本、`docs/config/`、历史计划文档等残留。不得清理、回滚或提交这些残留。

- [ ] **Step 3: 复述阶段边界**

执行窗口开始实现前，向审批窗口复述：

```text
本阶段只修 Phase 5 留资权威口径错配。
统计、标签、评分的“已留资”只看 extracted_phone / extracted_wechat / all_extracted_contacts。
customer_contact 和 raw_data.contact_extract 只保留展示兼容，不参与权威留资判断。
本阶段不改迁移、模型、发送链路、9100、Local Agent、企业号管理、日报。
```

Expected: 获得审批窗口继续许可后再进入 Task 1。

---

## Task 1: 后端红灯回归测试

**Files:**
- Modify: `tests/test_leads_management.py`

- [ ] **Step 1: 新增“仅 customer_contact 不算已留资”的报表测试**

在 `tests/test_leads_management.py` 的 `test_reports_summary_uses_extracted_contact_columns_not_replied_status` 后新增：

```python
def test_customer_contact_alone_does_not_count_as_retained_contact():
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="旧字段客户",
            customer_contact="legacy_contact",
            content="旧线索只有 customer_contact，没有提取字段",
            source_id="customer-contact-only",
            merchant_id="merchant-a",
            status="pending",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    summary_response = _client().get("/reports/summary")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_leads"] == 1
    assert summary["retained_contact_count"] == 0
    assert summary["retained_contact_rate"] == 0.0
    assert summary["high_intent_count"] == 0

    detail_response = _client().get(f"/leads/{lead_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["customer_contact"] == "legacy_contact"
    assert detail["all_extracted_contacts"] == ["legacy_contact"]
```

Expected: 当前实现下 `retained_contact_count` 会返回 1，测试应失败。

- [ ] **Step 2: 新增“仅 raw_data.contact_extract 不算权威留资，但仍可展示”的测试**

在同一文件继续新增：

```python
def test_legacy_raw_contact_extract_does_not_count_as_retained_contact():
    raw_data = json.dumps(
        {
            "contact_extract": {
                "phone": "13900001111",
                "wechat": "wx_legacy",
                "all_contacts": ["13900001111", "wx_legacy"],
                "status": "matched",
            }
        },
        ensure_ascii=False,
    )
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="旧 raw 客户",
            customer_contact=None,
            content="旧 raw_data 里有联系方式",
            source_id="legacy-raw-contact-only",
            merchant_id="merchant-a",
            raw_data=raw_data,
            status="pending",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    summary_response = _client().get("/reports/summary")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_leads"] == 1
    assert summary["retained_contact_count"] == 0
    assert summary["retained_contact_rate"] == 0.0

    detail_response = _client().get(f"/leads/{lead_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["phone"] == "13900001111"
    assert detail["wechat"] == "wx_legacy"
    assert detail["all_extracted_contacts"] == ["13900001111", "wx_legacy"]
```

Expected: 当前实现下 `retained_contact_count` 会返回 1，测试应失败。

- [ ] **Step 3: 新增“权威列存在才算留资”的正向保护测试**

在同一文件继续新增：

```python
def test_authoritative_contact_columns_count_as_retained_contact():
    db = TestSession()
    try:
        db.add_all(
            [
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="手机号客户",
                    content="客户留了手机号",
                    source_id="auth-phone",
                    merchant_id="merchant-a",
                    extracted_phone="13800001111",
                    status="pending",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="微信客户",
                    content="客户留了微信",
                    source_id="auth-wechat",
                    merchant_id="merchant-a",
                    extracted_wechat="wx_auth",
                    status="pending",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="全部联系方式客户",
                    content="客户留了其他联系方式",
                    source_id="auth-all",
                    merchant_id="merchant-a",
                    all_extracted_contacts=json.dumps({"all": ["wx_all"]}, ensure_ascii=False),
                    status="pending",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 3
    assert data["retained_contact_count"] == 3
    assert data["retained_contact_rate"] == 100.0
```

Expected: 当前实现通常已通过；它用于防止 FIX1 把正向权威列弄丢。

- [ ] **Step 4: 运行红灯测试**

Run:

```bash
python -m pytest tests/test_leads_management.py::test_customer_contact_alone_does_not_count_as_retained_contact tests/test_leads_management.py::test_legacy_raw_contact_extract_does_not_count_as_retained_contact tests/test_leads_management.py::test_authoritative_contact_columns_count_as_retained_contact -v
```

Expected: 前两个测试失败，第三个测试通过。

---

## Task 2: 后端权威 helper 与展示 helper 拆分

**Files:**
- Modify: `app/services/lead_management_service.py`
- Test: `tests/test_leads_management.py`
- Optional Test: `tests/test_leads_contact_fields.py`

- [ ] **Step 1: 拆分权威联系方式 helper**

在 `app/services/lead_management_service.py` 中，将当前 `_contact_values()` 拆成两个 helper。保留 `_contact_values()` 作为展示 helper，新加 `_authoritative_contact_values()`：

```python
def _authoritative_contact_values(lead: DouyinLead) -> list[str]:
    values: list[str] = []
    _append_contact_value(values, getattr(lead, "extracted_phone", None))
    _append_contact_value(values, getattr(lead, "extracted_wechat", None))
    _append_all_contact_values(values, getattr(lead, "all_extracted_contacts", None))
    return values


def _contact_values(lead: DouyinLead) -> list[str]:
    values = _authoritative_contact_values(lead)

    extract = _contact_extract(lead)
    for key in ("phone", "wechat"):
        _append_contact_value(values, extract.get(key))
    _append_all_contact_values(values, extract.get("all_contacts"))
    _append_contact_value(values, lead.customer_contact)
    return values
```

Expected: 展示 helper 仍能显示旧数据；权威 helper 不读取 `raw_data` 或 `customer_contact`。

- [ ] **Step 2: 收敛 `has_retained_contact()`**

把 `has_retained_contact()` 改为：

```python
def has_retained_contact(lead: DouyinLead) -> bool:
    """判断线索是否已留资；只以提取后的独立列为权威口径。"""
    return bool(_authoritative_contact_values(lead))
```

Expected: `lead_score()`、`is_high_intent()`、`summary()` 自动使用权威口径。

- [ ] **Step 3: 确认 `_lead_contact_payload()` 继续使用展示 helper**

保持 `_lead_contact_payload()` 中：

```python
values = _contact_values(lead)
```

不要改成 `_authoritative_contact_values(lead)`。这是有意保留旧线索展示兼容。

- [ ] **Step 4: 运行后端专项测试**

Run:

```bash
python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py -v
```

Expected: 全部通过。若 `tests/test_leads_contact_fields.py` 的旧展示兼容测试失败，只能调整展示 helper 或测试说明，不得把 `customer_contact` 放回权威 helper。

- [ ] **Step 5: 后端静态口径检查**

Run:

```bash
rg -n "def _authoritative_contact_values|def _contact_values|def has_retained_contact|customer_contact|raw_data|contact_extract" app/services/lead_management_service.py
```

Expected:

```text
_authoritative_contact_values 只读取 extracted_phone / extracted_wechat / all_extracted_contacts
has_retained_contact 只调用 _authoritative_contact_values
customer_contact / raw_data / contact_extract 只出现在展示 helper、搜索、payload 或文本拼接位置
```

- [ ] **Step 6: 提交后端改动**

Run:

```bash
git add app/services/lead_management_service.py tests/test_leads_management.py tests/test_leads_contact_fields.py
git diff --cached --name-only
git commit -m "fix: 收敛线索留资权威口径"
```

Expected: 提交只包含本任务实际变更文件。若 `tests/test_leads_contact_fields.py` 未改动，不要强行 `git add`。

---

## Task 3: 前端运营标签口径与文案同步

**Files:**
- Modify: `frontend/src/features/leads/pages/LeadsManagement.tsx`

- [ ] **Step 1: 新增前端权威联系方式 helper**

在 `getLeadContactValues()` 下方新增：

```ts
function getAuthoritativeContactValues(lead: Lead): string[] {
  return uniqueStrings([lead.phone, lead.wechat, ...(lead.all_extracted_contacts || [])]);
}
```

Expected: 该 helper 不读取 `lead.customer_contact`。

- [ ] **Step 2: 优化展示联系方式 helper**

把当前 `getLeadContactValues()` 改为：

```ts
function getLeadContactValues(lead: Lead): string[] {
  return uniqueStrings([lead.phone, lead.wechat, ...(lead.all_extracted_contacts || []), lead.customer_contact]);
}
```

Expected: 展示仍可兜底显示 `customer_contact`，并统一 trim / 去重。

- [ ] **Step 3: 收敛前端 `hasRetainedContact()`**

把当前：

```ts
function hasRetainedContact(lead: Lead): boolean {
  return getLeadContactValues(lead).length > 0;
}
```

改为：

```ts
function hasRetainedContact(lead: Lead): boolean {
  return getAuthoritativeContactValues(lead).length > 0;
}
```

Expected: 运营标签“已留资”和人工复核判断不再把 `customer_contact` 算作权威留资。

- [ ] **Step 4: 修正表头文案**

把：

```tsx
<th className="w-[14%] px-4 py-3 font-semibold">联系电话</th>
```

改为：

```tsx
<th className="w-[14%] px-4 py-3 font-semibold">联系方式</th>
```

- [ ] **Step 5: 修正会话跳转缺字段文案**

把：

```ts
if (!lead.source_id) missing.push("客户 open_id");
```

改为：

```ts
if (!lead.source_id) missing.push("客户身份标识");
```

- [ ] **Step 6: 前端构建验证**

Run:

```bash
cd frontend
npm run build
```

Expected: 构建成功。允许既有 chunk size warning；不允许 TypeScript 错误。

- [ ] **Step 7: 前端静态口径检查**

Run:

```bash
rg -n "getAuthoritativeContactValues|function hasRetainedContact|customer_contact|联系电话|客户 open_id" frontend/src/features/leads/pages/LeadsManagement.tsx
```

Expected:

```text
getAuthoritativeContactValues 存在且不包含 customer_contact
hasRetainedContact 调用 getAuthoritativeContactValues
customer_contact 只出现在展示联系方式 helper 或详情展示相关逻辑
联系电话 无输出
客户 open_id 无输出
```

- [ ] **Step 8: 提交前端改动**

Run:

```bash
git add frontend/src/features/leads/pages/LeadsManagement.tsx
git diff --cached --name-only
git commit -m "fix: 同步线索留资前端口径"
```

Expected: 只提交 `frontend/src/features/leads/pages/LeadsManagement.tsx`。

---

## Task 4: 全阶段验证与越界检查

**Files:**
- Read-only: all changed files

- [ ] **Step 1: 后端专项回归**

Run:

```bash
python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py -v
```

Expected: 全部通过。

- [ ] **Step 2: 前端构建**

Run:

```bash
cd frontend
npm run build
```

Expected: 构建成功。只允许既有 warning，不允许构建失败。

- [ ] **Step 3: 空白检查**

Run:

```bash
git diff --check HEAD~2..HEAD
```

Expected: 无输出。若执行窗口合并为 1 个提交，则使用 `HEAD~1..HEAD`。

- [ ] **Step 4: 阶段 diff 文件检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD
```

Expected: 只允许出现：

```text
app/services/lead_management_service.py
tests/test_leads_management.py
tests/test_leads_contact_fields.py
frontend/src/features/leads/pages/LeadsManagement.tsx
```

若执行窗口只产生 1 个提交，则使用 `HEAD~1..HEAD`。`tests/test_leads_contact_fields.py` 可以不出现。

- [ ] **Step 5: 禁区文件检查**

Run:

```bash
git diff --name-only HEAD~2..HEAD | rg "input_writer|contact_searcher|local_agent_main|apps/xg_douyin_ai_cs|ai_auto_reply_send_service|douyin_private_message_send_service|lead_notifications|notification_service|douyin_ai_cs_proxy|agents|douyin_accounts|models.py|schemas.py"
```

Expected: 无输出。若出现 `app/schemas.py`、`app/models.py` 或发送链路文件，本阶段越界，必须停止并回退 FIX1 自己的越界改动。

- [ ] **Step 6: 后端权威口径静态检查**

Run:

```bash
rg -n "def _authoritative_contact_values|def has_retained_contact|customer_contact|contact_extract|raw_data" app/services/lead_management_service.py
```

Expected: `has_retained_contact` 只调用 `_authoritative_contact_values`；`customer_contact`、`contact_extract`、`raw_data` 不出现在 `_authoritative_contact_values` 内。

- [ ] **Step 7: 前端权威口径静态检查**

Run:

```bash
rg -n "getAuthoritativeContactValues|function hasRetainedContact|customer_contact|联系电话|客户 open_id" frontend/src/features/leads/pages/LeadsManagement.tsx
```

Expected: `hasRetainedContact` 调用 `getAuthoritativeContactValues`；`联系电话` 与 `客户 open_id` 无输出；`customer_contact` 只在展示路径出现。

- [ ] **Step 8: 工作区残留说明**

Run:

```bash
git status --short --branch
```

Expected: 除本阶段已提交内容外，可能仍有用户残留。回传报告必须明确哪些残留不是本阶段引入，不得清理。

---

## Task 5: 自审与回传

**Files:**
- Read-only: all changed files

- [ ] **Step 1: Spec Reviewer 自审**

逐项确认：

```text
1. extracted_phone 非空算已留资。
2. extracted_wechat 非空算已留资。
3. all_extracted_contacts 非空算已留资。
4. 仅 customer_contact 不算已留资。
5. 仅 raw_data.contact_extract 不算已留资。
6. customer_contact 仍可在详情 / 列表展示为旧联系方式。
7. raw_data.contact_extract 仍可展示旧 phone / wechat / all_extracted_contacts。
8. /reports/summary 使用权威口径。
9. 前端“已留资”标签使用权威口径。
10. 前端联系方式展示仍有旧数据兜底。
11. 未修改迁移、模型、发送链路、9100、Local Agent、企业号管理、日报。
```

- [ ] **Step 2: Code Quality Reviewer 自审**

逐项确认：

```text
1. 后端权威判断集中在 _authoritative_contact_values + has_retained_contact。
2. 展示兼容集中在 _contact_values + _lead_contact_payload。
3. 没有在 report_service、router 或前端复制后端统计规则。
4. all_extracted_contacts 解析仍 trim、去重、兼容 JSON 字符串 / dict / list。
5. 前端没有新增依赖、全局状态或路由结构。
6. 没有修改 TypeScript 配置。
7. 提交不包含用户残留。
```

- [ ] **Step 3: 固定回传格式**

回传审批窗口时使用：

```text
阶段：Phase 5-FIX1 留资权威口径收敛
状态：DONE / BLOCKED

提交：
- <hash> fix: 收敛线索留资权威口径
- <hash> fix: 同步线索留资前端口径

变更文件：
- app/services/lead_management_service.py
- tests/test_leads_management.py
- frontend/src/features/leads/pages/LeadsManagement.tsx
- tests/test_leads_contact_fields.py（如实际修改才列）

数据库迁移：无
新增权限码：无
新增依赖：无
新增环境变量：无
服务启动 / 真实请求：无
未触碰：app/models.py、app/schemas.py、发送链路、apps/xg_douyin_ai_cs、input_writer、contact_searcher、local_agent_main、Local Agent、微信 UI 自动化、Phase 6 企业号管理、日报

测试命令与结果：
- python -m pytest tests/test_leads_management.py tests/test_leads_contact_fields.py -v：<实际结果>
- cd frontend && npm run build：<实际结果>
- git diff --check HEAD~2..HEAD：<实际结果>
- 阶段 diff 文件检查：<实际结果>
- 禁区文件检查：<实际结果>
- 后端权威口径静态检查：<实际结果>
- 前端权威口径静态检查：<实际结果>

自审结论：
- Spec Reviewer：Approved / Blocked
- Code Quality Reviewer：Approved / Blocked

剩余风险：
- <如实填写；无则写“无”>

需要本窗口审批的问题：
- 是否确认 Phase 5-FIX1 通过，并把 Phase 5 从“有条件通过”更新为“通过”？
- 是否可以进入 Phase 6 执行包制定？
```

## 验收标准

1. 仅 `customer_contact` 的线索在 `/reports/summary` 中 `retained_contact_count == 0`。
2. 仅 `raw_data.contact_extract` 的线索在 `/reports/summary` 中 `retained_contact_count == 0`。
3. 三个独立列任一存在时仍算已留资。
4. 旧 `customer_contact` 和 `raw_data.contact_extract` 仍能在详情 / 列表展示，不丢历史可读性。
5. 前端“已留资”运营标签不再由 `customer_contact` 触发。
6. 前端“联系方式”展示仍可用 `customer_contact` 兜底。
7. 本阶段没有触碰迁移、模型、发送链路、9100、Local Agent、企业号管理、日报。

## 回滚方案

若需要回滚，只回滚 Phase 5-FIX1 的提交，不回滚 Phase 5 主体，也不回滚用户已有工作区残留。

推荐顺序：

```bash
git revert <前端_FIX1_commit_hash>
git revert <后端_FIX1_commit_hash>
```

不得使用 `git reset --hard`。不得清理用户未提交文件。
