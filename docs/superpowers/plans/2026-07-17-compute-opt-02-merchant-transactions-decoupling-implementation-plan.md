# COMPUTE-OPT-02 商户算力流水解耦实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将商户算力流水接口和页面收敛为面向业务的 7 字段公开合同，彻底隐藏模型、计量、智能体、会话和内部备注等诊断字段。

**Architecture:** 保留 `list_transactions()` 作为账本内部原始查询，新增 `list_merchant_transactions()` 在服务层完成稳定类型和中文业务场景投影；9000 与独立算力服务的商户路由共同调用该投影。前端只声明和展示公开合同，不新增表、不改计费、不改鉴权、不把安全边界寄托在前端隐藏列上。

**Tech Stack:** Python 3、FastAPI、Pydantic、SQLAlchemy、pytest、React 19、TypeScript、Vite。

---

## 0. 阶段边界、决策与工作区保护

### 0.1 已确认方案

采用“后端独立商户投影”，不采用以下两种方案：

1. **不采用前端隐藏字段：** 网络响应仍会泄露内部模型、能力编码、原始用量、智能体编号、会话编号和备注，不构成解耦。
2. **不直接改写 `list_transactions()`：** 该函数是账本内部原始查询，既有计费测试依赖 ORM 字段；直接替换会混淆内部合同和商户合同。

商户接口公开字段固定为：

```text
id
type
type_label
business_scene
points_change
balance_after
created_at
```

### 0.2 允许范围

- 新增商户流水投影函数和中文场景映射。
- 调整 9000 `/compute/transactions` 与独立算力服务 `/api/compute/transactions` 的响应模型和调用函数。
- 调整商户前端类型、流水表格和 Phase 10 前端静态合同。
- 增加商户隔离、字段白名单、场景映射和前端防泄漏测试。
- 原位更新算力当前事实与阶段二实施状态。

### 0.3 禁止范围

- 不改 `compute_transactions` 表、ORM 列或任何迁移。
- 不改 `record_usage()`、上浮比例、余额、充值、套餐发放和计费逻辑。
- 不改商户鉴权来源；`merchant_id` 继续只取可信请求上下文。
- 不新增管理员流水诊断接口，不提前实施 `COMPUTE-OPT-03`。
- 不改管理员导航、管理员算力配置权限或页面。
- 不改抖音提示词、历史窗口和重试逻辑，不提前实施 `COMPUTE-OPT-04`。
- 不修改或提交执行时出现的其他窗口并发改动。

### 0.4 风险等级与回滚

- 风险等级：**P1，中风险公开接口合同变更**。前后端必须同批发布，否则旧前端读取旧字段会显示空值。
- 数据库风险：无 schema 变更，不执行 Alembic、不连接生产数据库。
- 权限风险：只复用现有可信商户上下文，不改 RBAC。
- 回滚：回滚本阶段后端与前端两个功能提交即可；账本数据不需要回滚。

### 0.5 基线与选择性提交门禁

- [ ] **Step 1：记录基线和脏工作区**

```powershell
git rev-parse --short HEAD
git status --short
git merge-base --is-ancestor eb23367 HEAD
if ($LASTEXITCODE -ne 0) { throw "HEAD 未包含 COMPUTE-OPT-01 收尾提交 eb23367" }
```

预期：记录实际 `HEAD`；允许工作区存在其他任务改动，但必须建立禁止提交清单。

- [ ] **Step 2：运行修改前基线**

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py -q
Push-Location frontend
npm run phase10-compute:check
npm run build
Pop-Location
```

预期：基线通过。若失败，先在未修改代码上保存失败文件和用例，不得把无关失败带入本阶段修复。

---

## Task 1：建立商户专用流水投影

**Files:**

- Modify: `apps/compute/services.py`
- Modify: `app/services/compute_service.py`
- Test: `tests/test_compute_service.py`

- [ ] **Step 1：先写商户投影红灯测试**

在 `tests/test_compute_service.py` 的流水分页测试之后增加：

```python
def test_list_merchant_transactions_projects_public_business_contract(db):
    _seed_ratio(db)
    compute_service.recharge_merchant(
        db, "m_public", 1000, remark="内部充值备注", operator_id="admin-secret"
    )
    compute_service.record_usage(
        db,
        "m_public",
        18,
        capability_key="douyin-cs",
        source="llm",
        model="internal-model",
        agent_id="internal-agent",
        conversation_id=42,
        remark="douyin_ai_reply",
        usage_measurement_method="provider_tokens",
        prompt_tokens=12,
        completion_tokens=6,
        llm_call_stage="primary",
    )

    result = compute_service.list_merchant_transactions(db, "m_public")

    assert result["total"] == 2
    consume, recharge = result["items"]
    assert set(consume) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert consume["type"] == "consume"
    assert consume["type_label"] == "消耗"
    assert consume["business_scene"] == "抖音自动回复"
    assert consume["points_change"] == -18
    assert consume["balance_after"] == 982
    assert recharge["type"] == "recharge"
    assert recharge["type_label"] == "充值"
    assert recharge["business_scene"] == "算力充值"
    assert recharge["points_change"] == 1000
```

再增加未知历史来源不泄露内部编码的测试：

```python
def test_list_merchant_transactions_hides_unknown_internal_codes(db):
    db.add(
        ComputeTransaction(
            merchant_id="m_legacy",
            transaction_type="legacy_internal_type",
            delta_tokens=-3,
            balance_after_tokens=7,
            source="secret_source",
            remark="secret_remark",
            model="secret_model",
            agent_id="secret_agent",
            conversation_id=99,
            capability_key="secret_capability",
        )
    )
    db.commit()

    item = compute_service.list_merchant_transactions(db, "m_legacy")["items"][0]

    assert item["type"] == "other"
    assert item["type_label"] == "其他"
    assert item["business_scene"] == "AI 服务"
    assert "secret" not in repr(item)
```

补齐所有当前真实调用方和能力兜底的场景映射测试：

```python
@pytest.mark.parametrize(
    ("remark", "capability_key", "expected_scene"),
    [
        ("douyin_ai_reply", "douyin-cs", "抖音自动回复"),
        ("daily_sales_summary", "wechat-assistant", "每日销售报表"),
        ("return_visit_judge", "wechat-assistant", "客户回访"),
        ("knowledge_training_ask", "knowledge", "知识问答"),
        ("knowledge_training_ingest", "knowledge", "知识库训练"),
        ("knowledge_search", "knowledge", "知识库检索"),
        ("ai_edit_plan", "compute", "AI小高剪辑"),
        (None, "douyin-cs", "抖音客服"),
        (None, "wechat-assistant", "AI小高微信助手"),
        (None, "agents", "智能体服务"),
        (None, "leads", "线索服务"),
    ],
)
def test_list_merchant_transactions_maps_current_business_scenes(
    db, remark, capability_key, expected_scene
):
    db.add(
        ComputeTransaction(
            merchant_id="m_scene",
            transaction_type="consume",
            delta_tokens=-1,
            balance_after_tokens=9,
            source="llm",
            remark=remark,
            model="internal-model",
            capability_key=capability_key,
        )
    )
    db.commit()

    item = compute_service.list_merchant_transactions(db, "m_scene")["items"][0]

    assert item["business_scene"] == expected_scene
```

- [ ] **Step 2：运行红灯并确认失败原因正确**

```powershell
python -m pytest tests/test_compute_service.py -k "merchant_transactions" -q
```

预期：仅因 `list_merchant_transactions` 尚不存在而失败。

- [ ] **Step 3：在共享服务中实现稳定投影**

在 `apps/compute/services.py` 的计量常量之后增加：

```python
MERCHANT_TRANSACTION_TYPE_LABELS = {
    "recharge": "充值",
    "grant_package": "套餐发放",
    "consume": "消耗",
}

MERCHANT_TRANSACTION_SCENES = {
    "recharge": "算力充值",
    "grant_package": "套餐发放",
}

MERCHANT_REMARK_SCENES = {
    "douyin_ai_reply": "抖音自动回复",
    "daily_sales_summary": "每日销售报表",
    "return_visit_judge": "客户回访",
    "knowledge_training_ask": "知识问答",
    "knowledge_training_ingest": "知识库训练",
    "knowledge_search": "知识库检索",
    "ai_edit_plan": "AI小高剪辑",
}

MERCHANT_CAPABILITY_SCENES = {
    "douyin-cs": "抖音客服",
    "leads": "线索服务",
    "agents": "智能体服务",
    "wechat-assistant": "AI小高微信助手",
    "compute": "AI小高剪辑",
    "knowledge": "知识库服务",
}
```

紧跟现有 `list_transactions()` 增加：

```python
def _merchant_business_scene(transaction: ComputeTransaction) -> str:
    """把内部来源收敛为商户可理解的中文使用场景，未知值不回显内部编码。"""
    fixed_scene = MERCHANT_TRANSACTION_SCENES.get(transaction.transaction_type)
    if fixed_scene:
        return fixed_scene
    if transaction.transaction_type != CONSUME_TYPE:
        return "AI 服务"
    return (
        MERCHANT_REMARK_SCENES.get(str(transaction.remark or ""))
        or MERCHANT_CAPABILITY_SCENES.get(str(transaction.capability_key or ""))
        or "AI 服务"
    )


def _project_merchant_transaction(transaction: ComputeTransaction) -> dict:
    """生成商户公开流水；只能在此白名单中增加字段。"""
    public_type = (
        transaction.transaction_type
        if transaction.transaction_type in MERCHANT_TRANSACTION_TYPE_LABELS
        else "other"
    )
    return {
        "id": transaction.id,
        "type": public_type,
        "type_label": MERCHANT_TRANSACTION_TYPE_LABELS.get(public_type, "其他"),
        "business_scene": _merchant_business_scene(transaction),
        "points_change": transaction.delta_tokens,
        "balance_after": transaction.balance_after_tokens,
        "created_at": transaction.created_at,
    }


def list_merchant_transactions(
    db: Session,
    merchant_id: str,
    transaction_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页返回商户公开流水投影，不暴露账本内部诊断字段。"""
    result = list_transactions(
        db,
        merchant_id,
        transaction_type=transaction_type,
        page=page,
        page_size=page_size,
    )
    return {
        **result,
        "items": [_project_merchant_transaction(item) for item in result["items"]],
    }
```

实现约束：

- 场景判断只使用服务端持久化字段，不接受前端传入场景。
- 未知 `transaction_type` 归一为 `other`，未知场景固定为“AI 服务”。
- 不在投影中加入 `merchant_id`、`tenant_id`、`source`、`remark`、`model`、`agent_id`、`conversation_id`、`actual_tokens`、`capability_key`、`markup_basis_points` 或真实 Token 明细。

- [ ] **Step 4：从 9000 兼容入口导出新函数**

在 `app/services/compute_service.py` 的导入列表和 `__all__` 中各增加：

```python
list_merchant_transactions,
```

- [ ] **Step 5：运行服务层绿灯和原始合同回归**

```powershell
python -m pytest tests/test_compute_service.py -q
```

预期：全部通过；既有 `list_transactions()` 测试仍返回 ORM，不得为了新投影修改原断言。

- [ ] **Step 6：选择性提交后端投影**

```powershell
git add -- apps/compute/services.py app/services/compute_service.py tests/test_compute_service.py
git diff --cached --check
git commit -m "新增商户算力流水公开投影"
```

---

## Task 2：让两个商户路由只返回公开合同

**Files:**

- Modify: `app/schemas.py`
- Modify: `app/routers/compute.py`
- Modify: `apps/compute/routers.py`
- Test: `tests/test_compute_router.py`
- Test: `tests/test_compute_app.py`

- [ ] **Step 1：先写 9000 接口字段白名单红灯**

先在 `tests/test_compute_router.py::test_transactions_after_recharge_and_consume` 的内部用量上报请求中增加真实生产调用使用的备注：

```python
            "remark": "douyin_ai_reply",
```

完整请求体应为：

```python
        json={
            "merchant_id": "merchant-a",
            "tokens": 300,
            "capability_key": "douyin-cs",
            "source": "llm",
            "model": "gpt-4o-mini",
            "remark": "douyin_ai_reply",
        },
```

然后在取得 `data` 后增加：

```python
    item = data["items"][0]
    assert set(item) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert item["business_scene"] == "抖音自动回复"
    assert item["points_change"] == -300
    assert item["balance_after"] == 700
```

强化商户隔离测试，给 B 商户写入带辨识度的内部数据后断言 A 响应既没有 B 流水，也没有任何内部字段：

```python
    a_items = client_a.get("/compute/transactions").json()["data"]["items"]
    assert len(a_items) == 1
    assert all(set(item) == {
        "id", "type", "type_label", "business_scene",
        "points_change", "balance_after", "created_at",
    } for item in a_items)
```

- [ ] **Step 2：先写独立算力服务字段白名单红灯**

在 `tests/test_compute_app.py` 增加：

```python
def test_compute_app_transactions_use_merchant_public_contract():
    admin = _admin_client()
    admin.post(
        "/api/compute/admin/accounts/merchant-a/recharge",
        json={"tokens": 1000, "remark": "internal-secret"},
    )

    response = _client().get("/api/compute/transactions")

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert set(item) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert item["business_scene"] == "算力充值"
    assert "internal-secret" not in repr(item)
```

- [ ] **Step 3：运行路由红灯**

```powershell
python -m pytest tests/test_compute_router.py tests/test_compute_app.py -k "transactions" -q
```

预期：旧响应字段与 7 字段白名单不一致，测试失败。

- [ ] **Step 4：把响应模型改为商户公开字段**

用以下定义替换 `app/schemas.py` 的 `ComputeTransactionOut`，类名保持不变以兼容 `apps/compute/schemas.py` 的共享导入：

```python
class ComputeTransactionOut(BaseModel):
    """商户可见的算力点数流水，不包含内部计量与诊断字段。"""

    id: int
    type: str = Field(..., description="稳定流水类型：recharge / grant_package / consume / other")
    type_label: str = Field(..., description="流水类型中文名称")
    business_scene: str = Field(..., description="商户可理解的中文使用场景")
    points_change: int = Field(..., description="算力点数变动，正数为增加、负数为消耗")
    balance_after: int = Field(..., description="变动后的算力点数余额")
    created_at: Optional[datetime]
```

`created_at` 是“字段必填、值可空”：投影固定输出该键，历史异常数据允许值为 `None`，不得写成带默认值的可选字段。

同时把 `ComputeTransactionListData`、`ComputeTransactionListResponse` 的文档字符串从“Token 明细”改为“商户算力点数流水”，不改分页字段。

- [ ] **Step 5：两个商户路由共同调用公开投影**

在以下两个函数中只替换服务调用名，参数保持原样：

```python
data = compute_service.list_merchant_transactions(
    db,
    merchant_id,
    transaction_type=transaction_type,
    page=page,
    page_size=page_size,
)
```

修改位置：

- `app/routers/compute.py::list_transactions`
- `apps/compute/routers.py::list_transactions`

同时把两个路由文档字符串改为“商户算力点数流水分页”。不得修改 `_require_merchant()`、`require_merchant_context()` 或查询参数。

- [ ] **Step 6：运行接口绿灯与权限回归**

```powershell
python -m pytest tests/test_compute_router.py tests/test_compute_app.py -q
```

预期：全部通过，商户隔离和既有权限测试不变。

- [ ] **Step 7：检查 OpenAPI 不再公开内部字段**

在 `tests/test_compute_router.py` 增加：

```python
def test_compute_transaction_openapi_hides_internal_fields():
    schema = _client(_context()).get("/openapi.json").json()
    transaction_schema = schema["components"]["schemas"]["ComputeTransactionOut"]
    properties = transaction_schema["properties"]
    assert set(properties) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert set(transaction_schema["required"]) == set(properties)
```

运行：

```powershell
python -m pytest tests/test_compute_router.py::test_compute_transaction_openapi_hides_internal_fields -q
```

预期：PASS。

- [ ] **Step 8：选择性提交接口合同**

```powershell
git add -- app/schemas.py app/routers/compute.py apps/compute/routers.py tests/test_compute_router.py tests/test_compute_app.py
git diff --cached --check
git commit -m "收敛商户算力流水接口合同"
```

---

## Task 3：收敛商户流水前端类型与表格

**Files:**

- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/compute/pages/ComputeCenter.tsx`
- Modify: `frontend/scripts/check-phase10-compute-contract.mjs`

说明：`frontend/**/*.d.ts` 是忽略的生成产物，不得手工编辑或提交。

- [ ] **Step 1：先把静态门禁改成新公开合同并运行红灯**

先把脚本顶部说明改为：商户流水只允许 7 个公开字段；管理员上浮配置类型继续保留；算力前端不得持有内部令牌或直连内部服务。

在 `frontend/scripts/check-phase10-compute-contract.mjs` 中增加接口正文提取函数：

```javascript
function readInterface(source, name) {
  const match = source.match(new RegExp(`export interface ${name} \\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`types.ts 缺少 ${name} 接口`);
  return match[1];
}
```

删除旧的“三快照字段存在于 `ComputeTransaction`”循环和“商户页展示实际量与计费量”检查，用以下检查替换；`ComputeMarkupRatio`、`ComputeCapabilityKey` 与管理员六能力比例检查保持不变：

```javascript
const merchantTransactionType = readInterface(typesTs, 'ComputeTransaction');
const PUBLIC_FIELDS = [
  'id',
  'type',
  'type_label',
  'business_scene',
  'points_change',
  'balance_after',
  'created_at',
];
for (const field of PUBLIC_FIELDS) {
  if (!merchantTransactionType.includes(`${field}:`)) {
    throw new Error(`ComputeTransaction 缺少商户公开字段：${field}`);
  }
}

const declaredFields = [
  ...merchantTransactionType.matchAll(/^\s*([A-Za-z_][A-Za-z0-9_]*)\??:/gm),
].map((match) => match[1]);
const missingFields = PUBLIC_FIELDS.filter((field) => !declaredFields.includes(field));
const extraFields = declaredFields.filter((field) => !PUBLIC_FIELDS.includes(field));
if (missingFields.length || extraFields.length) {
  throw new Error(
    `ComputeTransaction 字段必须精确等于 7 个公开字段；缺少：${missingFields.join(',') || '无'}；多余：${extraFields.join(',') || '无'}`,
  );
}

const INTERNAL_FIELDS = [
  'merchant_id',
  'tenant_id',
  'transaction_type',
  'delta_tokens',
  'balance_after_tokens',
  'source',
  'remark',
  'model',
  'agent_id',
  'conversation_id',
  'actual_tokens',
  'capability_key',
  'markup_basis_points',
  'usage_measurement_method',
  'prompt_tokens',
  'completion_tokens',
  'cached_tokens',
  'llm_call_stage',
];
for (const access of INTERNAL_FIELDS.map((field) => `tx.${field}`)) {
  if (computeCenter.includes(access)) {
    throw new Error(`ComputeCenter 不得读取内部字段：${access}`);
  }
}
for (const heading of ['类型', '使用场景', '算力点数变动', '变动后余额', '时间']) {
  if (!computeCenter.includes(`>${heading}<`)) {
    throw new Error(`ComputeCenter 缺少商户流水列：${heading}`);
  }
}
```

运行：

```powershell
Push-Location frontend
npm run phase10-compute:check
Pop-Location
```

预期：旧 `ComputeTransaction` 仍含内部字段，检查失败。

- [ ] **Step 2：替换前端商户流水类型**

用以下定义替换 `frontend/src/api/types.ts` 中现有 `ComputeTransaction`：

```typescript
/** 商户可见的算力点数流水。 */
export interface ComputeTransaction {
  id: number;
  /** 稳定流水类型 */
  type: "recharge" | "grant_package" | "consume" | "other";
  /** 流水类型中文名称 */
  type_label: string;
  /** 中文业务使用场景 */
  business_scene: string;
  /** 算力点数变动，正数为增加、负数为消耗 */
  points_change: number;
  /** 变动后余额 */
  balance_after: number;
  created_at: string | null;
}
```

`created_at` 必须保持 required nullable，与后端固定输出 7 个键的合同一致；不得把静态检查放宽为同时接受可选字段。

保留 `ComputeCapabilityKey` 和管理员上浮比例类型；商户类型收敛不等于删除管理员内部配置类型。

- [ ] **Step 3：删除页面内部映射和旧字段读取**

从 `ComputeCenter.tsx` 删除：

```typescript
const TRANSACTION_TYPE_LABELS = { ... };
const CAPABILITY_LABELS = { ... };
function capabilityLabel(...) { ... }
```

保留 `formatTokenChange()`，但调用参数改为 `tx.points_change`。

- [ ] **Step 4：用五列业务表格替换旧六列表格**

用以下结构替换“算力点数明细”的 `<table>`；分页、加载、空数据和错误状态保持原样：

```tsx
<table className="w-full min-w-[720px] text-left text-xs">
  <thead>
    <tr className="border-b border-[#e4e8f0] text-[#8b95a6]">
      <th className="px-4 py-2.5 font-semibold">类型</th>
      <th className="px-4 py-2.5 font-semibold">使用场景</th>
      <th className="px-4 py-2.5 font-semibold">算力点数变动</th>
      <th className="px-4 py-2.5 font-semibold">变动后余额</th>
      <th className="px-4 py-2.5 font-semibold">时间</th>
    </tr>
  </thead>
  <tbody>
    {transactions.map((tx) => {
      const income = tx.points_change > 0;
      return (
        <tr key={tx.id} className="border-b border-[#f1f5f9] last:border-0">
          <td className="px-4 py-2.5 text-[#1a1f2e]">{tx.type_label}</td>
          <td className="px-4 py-2.5 text-[#475467]">{tx.business_scene}</td>
          <td
            className={`px-4 py-2.5 font-semibold ${
              income ? "text-emerald-600" : "text-[#475467]"
            }`}
          >
            {formatTokenChange(tx.points_change)}
          </td>
          <td className="px-4 py-2.5 text-[#475467]">{tx.balance_after}</td>
          <td className="px-4 py-2.5 text-[#8b95a6]">
            {formatDateTimeLocal(tx.created_at)}
          </td>
        </tr>
      );
    })}
  </tbody>
</table>
```

不得显示或通过 tooltip、`title`、折叠详情、开发态 JSON 等方式重新暴露内部字段。

- [ ] **Step 5：运行前端静态合同和构建**

```powershell
Push-Location frontend
npm run phase10-compute:check
npm run build
npx eslint src/api/types.ts src/features/compute/pages/ComputeCenter.tsx scripts/check-phase10-compute-contract.mjs
Pop-Location
```

预期：静态合同和构建通过；定向 lint 不新增问题。若存在修改前就有的 lint 问题，必须提供同命令前后对照，不能笼统标记为历史问题。

- [ ] **Step 6：执行前端内部字段静态泄漏扫描**

```powershell
rg -n "tx\.(merchant_id|transaction_type|delta_tokens|balance_after_tokens|source|remark|model|agent_id|conversation_id|actual_tokens|capability_key|markup_basis_points)" frontend/src/features/compute/pages/ComputeCenter.tsx
```

预期：零命中。

- [ ] **Step 7：选择性提交前端**

```powershell
git add -- frontend/src/api/types.ts frontend/src/features/compute/pages/ComputeCenter.tsx frontend/scripts/check-phase10-compute-contract.mjs
git diff --cached --check
git commit -m "收敛商户算力流水页面展示"
```

---

## Task 4：全链路回归与浏览器验收

**Files:**

- No source changes expected.
- Optional evidence only: `docs/ai/14_compute/shots/compute-opt-02/`

- [ ] **Step 1：运行后端专项回归**

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_models.py tests/test_compute_client.py tests/test_compute_usage_client.py tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py tests/test_phase10_compute_no_network.py -q
```

预期：全部通过；证明商户投影未改变计费、迁移、内部上报和客户端合同。

- [ ] **Step 2：运行前端回归**

```powershell
Push-Location frontend
npm run phase10-compute:check
npm run build
Pop-Location
```

预期：全部通过。

- [ ] **Step 3：浏览器验收商户流水**

在可进入业务页面的本地或测试环境验收 `/compute/token-transactions`：

1. 至少准备充值、套餐发放、抖音自动回复三类流水。
2. 1024、1440 两个视口确认页面横向溢出为 0。
3. 表头只能是：类型、使用场景、算力点数变动、变动后余额、时间。
4. 正数显示 `+`，消耗保持负号；余额与接口一致。
5. 刷新、分页、加载、空数据、错误重试状态均可用。
6. 浏览器网络响应中每条 `items` 只能有 7 个公开字段。
7. 页面和响应中不得出现模型名、能力编码、内部备注、智能体编号、会话编号或基础 Token 明细。

若鉴权或后端环境阻断浏览器进入业务页，必须标记 `BLOCKED_ENVIRONMENT`，以接口测试、OpenAPI 测试和静态门禁作为替代证据，不得声称完成浏览器验收。

- [ ] **Step 4：确认无数据库与后续阶段越界**

```powershell
git diff --name-only eb23367..HEAD | rg "migrations|models.py|SuperComputeConfig|SideNav|App.tsx|reply_decision_service"
```

预期：本阶段提交零命中。若基线之后已有其他任务命中，必须用本阶段三个提交的精确范围复核，不得把并发提交算作本阶段越界。

---

## Task 5：原位更新文档事实并独立提交

**Files:**

- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md`
- Modify: `docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md`

- [ ] **Step 1：更新当前事实，不追加流水账**

`docs/ai/05_PROJECT_CONTEXT.md` 的“小高算力”当前事实原位补充：

```text
商户流水接口和页面只返回类型、中文使用场景、算力点数变动、变动后余额和时间；模型、能力编码、计量明细、智能体、会话和内部备注仅保留在内部账本，不向普通商户公开。
```

不得改动同期其他任务写入的 AI 剪辑、微信或自动回复事实。

- [ ] **Step 2：更新专题合同**

在 `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md` 当前计费合同中明确区分：

```text
内部账本继续保存真实 Token、计量方式、调用阶段和诊断字段；商户公开流水是独立 7 字段投影，不承担内部计量诊断职责。
```

将 `docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md` 的实施状态原位改为：阶段一、阶段二已完成；阶段三、阶段四待实施。不要新增按日期堆叠的“最新补充”。

- [ ] **Step 3：文档自检**

```powershell
rg -n "阶段二.*待实施|商户.*实际字符|商户.*模型|商户.*capability_key" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
git diff --check -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
```

预期：没有把阶段二继续写成待实施；历史提交说明若提到旧展示，必须明确是历史事实，不得误改历史。

- [ ] **Step 4：选择性提交文档**

```powershell
git add -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
git diff --cached --check
git commit -m "更新商户算力流水展示合同"
```

如果 `05_PROJECT_CONTEXT.md` 同时存在其他窗口改动，必须只暂存本阶段对应 hunk；禁止整文件暂存带入并发内容。

---

## 6. 最终审批门禁

执行窗口在申请提交或发布审批前必须返回：

1. 实际基线 `HEAD`、本阶段全部提交哈希和每个提交的精确文件清单。
2. 9000 与独立算力服务各一份商户流水响应样例，逐项证明每条只有 7 个公开字段。
3. 充值、套餐发放、抖音自动回复、知识问答、微信助手、未知历史来源的中文场景映射结果。
4. 商户 A/B 隔离测试、OpenAPI 字段白名单测试和未知编码不泄露测试结果。
5. 后端专项测试、前端静态合同、构建和定向 lint 的完整数量与退出码。
6. 1024、1440 浏览器验收结果；无法进入时必须写明 `BLOCKED_ENVIRONMENT` 和替代证据。
7. `git diff --check`、`git status --short` 与本阶段越界扫描结果。
8. 明确确认未修改数据库、迁移、计费、鉴权、管理员入口、提示词、重试和真实发送门禁。
9. 文档影响检查结果和并发工作区隔离清单。

审批结论规则：

- `PASS`：接口、页面、测试、浏览器和文档全部通过，且无越界。
- `CONDITIONAL_PASS`：仅浏览器业务页因鉴权/后端环境阻塞，接口、OpenAPI、静态门禁、构建和后端测试全部通过，并有明确替代证据。
- `FAIL`：响应仍出现任一内部字段、商户隔离失败、未知编码被回显、前后端字段不一致、计费/权限被改动，或测试存在本阶段新增失败。

执行窗口不得自行提交修复范围外文件；每个提交都使用精确 `git add -- <白名单>`，禁止 `git add .`。
