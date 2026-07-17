# COMPUTE-OPT-03 管理员算力配置接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有管理员算力配置能力接入统一入口 `/admin/compute-config`，并把套餐、计费比例、商户充值与套餐发放统一收口到超级管理员或精确权限 `auto_wechat:admin:compute_config`。

**Architecture:** 复用现有 `SuperComputeConfig`、前端算力接口与 `apps.compute.services`，不新建页面、不改数据库和计费语义。9000 与独立算力服务只统一管理员权限依赖和结构化操作日志；前端把旧的商户能力子路由迁移为管理员单入口，并在页面内部以三个切换视图承载现有功能。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、pytest、React 19、TypeScript、React Router、Vite。

---

## 0. 执行身份与硬边界

### 0.1 执行包身份

- Task-ID：`COMPUTE-OPT-03`
- Plan-Revision：`R2`
- Execution-Package-ID：`COMPUTE-OPT-03-R2-ADMIN-CONFIG-20260717`
- 业务代码起点：`1b4c755f5150b70936b3957f7acc9fa4088eff5e`
- 执行基线：以审批窗口随本计划下发的 `PLAN_APPROVED` 完整提交哈希为准；该提交只能比业务代码起点多本计划文件。
- 目标分支：`master`
- 风险等级：`L3`（算力写入 + 管理员权限）

### 0.2 当前事实

1. `SuperComputeConfig` 已实现套餐管理、计费比例、商户充值和套餐发放，但真实管理员侧栏、管理员路由与 `Index.tsx` 管理员分发均未接入。
2. 9000 与独立算力服务的计费比例接口已允许精确权限；套餐、充值和发放仍只允许超级管理员。
3. 独立算力服务 `get_gateway_context()` 当前要求商户编号或超级管理员标记，导致“仅有精确算力配置权限且无商户编号”的管理员在权限判断前被 401 阻断。
4. `/compute/packages` 与 `/compute/markup-ratios` 仍属于商户能力路由，不符合管理员单入口设计。
5. 执行窗口 R1 预检时曾观察到主工作区 `.gitignore` 并发改动；当前状态可能继续变化，施工前必须以实际 `git status --short` 建立禁止提交清单，不得触碰任何非本任务改动。

### 0.3 允许修改文件

```text
app/routers/compute.py
apps/compute/dependencies.py
apps/compute/routers.py
tests/test_compute_router.py
tests/test_compute_app.py
tests/test_phase10_compute_markup_api.py

frontend/src/App.tsx
frontend/src/newcarRedirect.ts
frontend/src/components/SideNav.tsx
frontend/src/features/capabilities.ts
frontend/src/features/routes.ts
frontend/src/features/compute/routes.ts
frontend/src/pages/Index.tsx
frontend/src/features/compute/pages/SuperComputeConfig.tsx
frontend/scripts/check-phase10-compute-contract.mjs

docs/ai/05_PROJECT_CONTEXT.md
docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md
docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
```

### 0.4 禁止事项

- 不修改 `app/models.py`、`app/schemas.py`、`apps/compute/services.py`、迁移、数据库结构或种子数据。
- 不修改计费公式、余额、流水、真实 Token 计量、商户流水七字段合同或充值订单状态。
- 不接真实支付，不新增退款、删除数据或余额不足拦截。
- 不接受前端正文、查询参数或普通浏览器请求提供可信权限。
- 不把“任意 `auto_wechat:admin:*` 权限”视为算力配置权限。
- 不让前端持有内部令牌，不直连 9100、9205 或 Milvus。
- 不提前实施 `COMPUTE-OPT-04` 的提示词、重试或模型调用优化。
- 不修改、暂存、删除或提交主工作区 `.gitignore` 及其他并发改动。
- 不推送、不部署、不连接生产 PostgreSQL、不调用付费模型。

### 0.5 工作区门禁

- [ ] 在独立 worktree 和独立任务分支中执行。
- [ ] `git rev-parse HEAD` 必须精确等于审批窗口下发的执行基线。
- [ ] `git diff --name-only <业务代码起点>..HEAD` 在施工前只能出现本计划文件。
- [ ] 记录主工作区 `git status --short`，把所有既有改动列入禁止提交清单。
- [ ] 任一代码事实与本计划冲突时返回 `PLAN_GAP`，不得自行扩大白名单。

---

## 1. 冻结业务合同

### 1.1 管理员页面合同

- 唯一主入口：`/admin/compute-config`
- 导航编号：`admin-compute-config`
- 导航名称：`算力配置`
- 页面内视图：
  - `ratios`：计费比例，默认视图
  - `packages`：套餐管理
  - `merchant-grant`：商户发放
- 旧地址兼容：
  - `/compute/packages` → `/admin/compute-config?view=packages`
  - `/compute/markup-ratios` → `/admin/compute-config?view=ratios`

### 1.2 权限合同

下列主体允许访问所有管理员算力配置接口：

1. `super_admin=true`
2. 精确权限 `auto_wechat:admin:compute_config`
3. 9000 开发 mock 上下文（沿用 `RequestContext.has_permission()` 现有行为）

下列主体必须拒绝：

1. 普通商户权限 `auto_wechat:compute`
2. 其他管理员权限，例如 `auto_wechat:admin:accounts`
3. 无权限上下文
4. 独立算力服务缺少可信网关上下文

不得使用 `isAdminLike`、权限前缀或任意管理员权限替代精确权限判断。

### 1.3 受保护接口

9000：

```text
GET  /admin/compute/packages
POST /admin/compute/packages
PUT  /admin/compute/packages/{package_id}
POST /admin/merchants/{merchant_id}/compute/recharge
POST /admin/compute/accounts/{merchant_id}/recharge
POST /admin/merchants/{merchant_id}/compute/grant-package
POST /admin/compute/accounts/{merchant_id}/grant-package
GET  /admin/compute/markup-ratios
PUT  /admin/compute/markup-ratios/{capability_key}
```

独立算力服务：

```text
GET    /api/compute/admin/packages
POST   /api/compute/admin/packages
PUT    /api/compute/admin/packages/{package_id}
DELETE /api/compute/admin/packages/{package_id}
POST   /api/compute/admin/accounts/{merchant_id}/recharge
POST   /api/compute/admin/accounts/{merchant_id}/grant-package
GET    /api/compute/admin/markup-ratios
PUT    /api/compute/admin/markup-ratios/{capability_key}
```

### 1.4 写操作日志合同

使用 Python 标准日志，不新增审计表或迁移。每次进入写接口后必须记录成功或失败，字段固定为：

```text
compute_admin_action operation=<操作> operator_id=<操作人> target=<脱敏目标摘要> status=<success|failed> failure_stage=<阶段|none> error_type=<异常类型|none>
```

操作名固定为：

```text
create_package
update_package
disable_package
recharge_merchant
grant_package
update_markup_ratio
```

目标摘要只允许套餐编号/名称、商户编号、算力点数、能力名称和被修改字段名。不得记录 Authorization、内部令牌、完整请求头、充值备注全文、数据库连接信息或异常正文。

---

## 2. Task 1：9000 权限矩阵与日志红灯

**Files:**
- Modify: `tests/test_compute_router.py`
- Modify: `tests/test_phase10_compute_markup_api.py`
- Later modify: `app/routers/compute.py`

- [ ] **Step 1：增加精确权限测试常量**

```python
CONFIG_PERMISSION = "auto_wechat:admin:compute_config"
```

- [ ] **Step 2：把旧“仅超级管理员”测试改为冻结拒绝矩阵**

```python
@pytest.mark.parametrize(
    "permission_codes",
    [
        ["auto_wechat:compute"],
        ["auto_wechat:admin:accounts"],
        [],
    ],
)
def test_compute_config_rejects_unrelated_permissions(permission_codes):
    client = _client(_context(super_admin=False, permission_codes=permission_codes))
    response = client.get("/admin/compute/packages")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
```

- [ ] **Step 3：增加精确权限完整操作测试**

测试必须用 `super_admin=False` 和仅 `CONFIG_PERMISSION` 的上下文依次完成：

```python
def test_compute_config_permission_manages_packages_and_merchant_points():
    admin = _client(_context(super_admin=False, permission_codes=[CONFIG_PERMISSION]))
    created = admin.post(
        "/admin/compute/packages",
        json={"name": "标准版", "price_yuan": 299, "token_amount": 350000},
    )
    assert created.status_code == 200
    package_id = created.json()["data"]["id"]
    assert admin.get("/admin/compute/packages").status_code == 200
    assert admin.put(
        f"/admin/compute/packages/{package_id}",
        json={"price_yuan": 399, "enabled": True},
    ).status_code == 200
    assert admin.post(
        "/admin/merchants/merchant-a/compute/recharge",
        json={"tokens": 1000, "remark": "审批备注"},
    ).status_code == 200
    assert admin.post(
        "/admin/merchants/merchant-a/compute/grant-package",
        json={"package_id": package_id},
    ).status_code == 200
```

- [ ] **Step 4：增加日志红灯**

使用 `caplog` 验证：

```python
def test_compute_config_write_logs_are_structured_and_do_not_leak_remark(caplog):
    caplog.set_level("INFO", logger="app.routers.compute")
    admin = _client(_context(
        user_id="admin-log",
        super_admin=False,
        permission_codes=[CONFIG_PERMISSION],
    ))
    response = admin.post(
        "/admin/merchants/merchant-a/compute/recharge",
        json={"tokens": 1000, "remark": "secret-remark-must-not-appear"},
    )
    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records]
    assert any("compute_admin_action" in message for message in messages)
    assert any("operation=recharge_merchant" in message for message in messages)
    assert any("operator_id=admin-log" in message for message in messages)
    assert any("status=success" in message for message in messages)
    assert all("secret-remark-must-not-appear" not in message for message in messages)
```

再用不存在的套餐编号验证 `status=failed`、`failure_stage=update_package` 和 `error_type` 存在。

在 `tests/test_phase10_compute_markup_api.py` 增加 9000 比例更新日志断言：精确权限更新 `douyin-cs` 后必须出现 `operation=update_markup_ratio`、`target=capability=douyin-cs`、`status=success`，日志不得出现请求头或内部令牌。

- [ ] **Step 5：运行红灯**

```powershell
$env:XG_DOUYIN_AI_CS_SERVICE_TOKEN=""
python -m pytest tests/test_compute_router.py tests/test_phase10_compute_markup_api.py -q
```

预期：精确权限访问套餐/充值/发放失败，日志断言失败；不得以导入错误或语法错误作为红灯。

---

## 3. Task 2：9000 最小实现

**Files:**
- Modify: `app/routers/compute.py`
- Test: `tests/test_compute_router.py`
- Test: `tests/test_phase10_compute_markup_api.py`

- [ ] **Step 1：统一权限函数**

删除只允许超级管理员的 `_require_admin()`，保留一个权限函数：

```python
COMPUTE_CONFIG_PERMISSION = "auto_wechat:admin:compute_config"


def _require_compute_config_admin(context: RequestContext) -> RequestContext:
    if not context.has_permission(COMPUTE_CONFIG_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少算力配置权限"},
        )
    return context
```

套餐列表、套餐写入、充值、发放和比例接口全部调用此函数。不得检查任意管理员权限前缀。

- [ ] **Step 2：增加本地结构化日志上下文**

```python
import logging
from contextlib import contextmanager
from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _safe_log_value(value: object) -> str:
    return " ".join(str(value).split())[:128] or "-"


@contextmanager
def _admin_compute_action(
    context: RequestContext,
    *,
    operation: str,
    target: str,
) -> Iterator[None]:
    operator_id = _safe_log_value(context.user_id)
    safe_target = _safe_log_value(target)
    try:
        yield
    except Exception as exc:
        logger.warning(
            "compute_admin_action operation=%s operator_id=%s target=%s "
            "status=failed failure_stage=%s error_type=%s",
            operation,
            operator_id,
            safe_target,
            operation,
            type(exc).__name__,
        )
        raise
    logger.info(
        "compute_admin_action operation=%s operator_id=%s target=%s "
        "status=success failure_stage=none error_type=none",
        operation,
        operator_id,
        safe_target,
    )
```

- [ ] **Step 3：包裹全部写操作**

权限校验必须位于上下文管理器内部，使权限失败也留下失败阶段。目标摘要固定为：

```text
create_package: package_name=<名称>
update_package: package_id=<编号>,fields=<显式字段名>
recharge_merchant: merchant_id=<编号>,points=<数量>
grant_package: merchant_id=<编号>,package_id=<编号>
update_markup_ratio: capability=<能力名>
```

不得把 `payload.remark` 放进日志。

- [ ] **Step 4：运行绿灯**

```powershell
python -m pytest tests/test_compute_router.py tests/test_phase10_compute_markup_api.py -q
```

预期：全部通过，既有超级管理员测试保持通过。

---

## 4. Task 3：独立算力服务权限与日志

**Files:**
- Modify: `apps/compute/dependencies.py`
- Modify: `apps/compute/routers.py`
- Modify: `tests/test_compute_app.py`
- Modify: `tests/test_phase10_compute_markup_api.py`

- [ ] **Step 1：增加独立服务精确权限客户端**

在 `tests/test_compute_app.py` 新增与 `_admin_client()` 相同的测试客户端，但上下文固定为：

```python
{
    "merchant_id": None,
    "tenant_id": "tenant-a",
    "user_id": "config-admin",
    "super_admin": False,
    "permission_codes": ["auto_wechat:admin:compute_config"],
}
```

测试该客户端可创建、查询、更新和禁用套餐，并可充值、发放套餐、读写比例。

- [ ] **Step 2：增加真实网关上下文红灯**

直接调用 `get_gateway_context()`：

```python
def test_gateway_context_allows_compute_config_admin_without_merchant():
    context = get_gateway_context(
        x_gateway_merchant_id=None,
        x_gateway_tenant_id="tenant-a",
        x_gateway_user_id="config-admin",
        x_gateway_permissions="auto_wechat:admin:compute_config",
        x_gateway_super_admin=None,
    )
    assert context["merchant_id"] is None
    assert context["super_admin"] is False
    assert context["permission_codes"] == ["auto_wechat:admin:compute_config"]
```

仅 `auto_wechat:compute` 且无商户编号仍必须返回 `401 GATEWAY_CONTEXT_REQUIRED`。

- [ ] **Step 3：运行红灯**

```powershell
python -m pytest tests/test_compute_app.py tests/test_phase10_compute_markup_api.py -q
```

预期：精确权限管理员被现有 `require_super_admin` 或前置商户编号检查拒绝。

- [ ] **Step 4：修正可信上下文解析顺序**

把 `COMPUTE_CONFIG_PERMISSION` 移到 `get_gateway_context()` 之前定义；在函数中先解析 `permission_codes`，再执行上下文存在性检查：

```python
permission_codes = [
    item.strip()
    for item in (x_gateway_permissions or "").split(",")
    if item.strip()
]
is_compute_config_admin = COMPUTE_CONFIG_PERMISSION in permission_codes
if (
    not x_gateway_merchant_id
    and x_gateway_super_admin != "true"
    and not is_compute_config_admin
):
    raise HTTPException(...)
```

这只信任网关注入的 `X-Gateway-Permissions`，不增加正文或查询参数信任入口。

- [ ] **Step 5：统一路由权限**

在 `apps/compute/routers.py` 中，以下接口全部从 `require_super_admin(context)` 改为 `require_compute_config_admin(context)`：

```text
admin_list_packages
admin_create_package
admin_update_package
admin_disable_package
admin_recharge_merchant
admin_grant_package
```

删除路由文件中不再使用的 `require_super_admin` 导入。`apps/compute/dependencies.py` 中可删除不再使用的函数，但不得改其他权限函数。

- [ ] **Step 6：按 Task 2 相同字段合同增加本地日志上下文**

日志名称为 `apps.compute.routers`，操作人取 `context.get("user_id")`。独立服务额外覆盖 `disable_package`。不得抽取跨服务公共模块。

在 `tests/test_phase10_compute_markup_api.py` 增加独立算力服务比例更新日志断言，字段与 9000 完全一致；在 `tests/test_compute_app.py` 用 `caplog` 覆盖 `disable_package` 成功和无权限写入失败，确认不记录请求头或内部令牌。

- [ ] **Step 7：运行绿灯**

```powershell
python -m pytest tests/test_compute_app.py tests/test_phase10_compute_markup_api.py -q
```

---

## 5. Checkpoint A：后端候选提交

- [ ] 执行：

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_phase10_compute_markup_api.py -q
git diff --check -- app/routers/compute.py apps/compute/dependencies.py apps/compute/routers.py tests/test_compute_router.py tests/test_compute_app.py tests/test_phase10_compute_markup_api.py
```

- [ ] 只暂存以下文件：

```text
app/routers/compute.py
apps/compute/dependencies.py
apps/compute/routers.py
tests/test_compute_router.py
tests/test_compute_app.py
tests/test_phase10_compute_markup_api.py
```

- [ ] 提交信息：

```text
统一管理员算力配置接口权限
```

- [ ] 记录完整提交哈希，不推送。

---

## 6. Task 4：前端统一入口静态红灯

**Files:**
- Modify: `frontend/scripts/check-phase10-compute-contract.mjs`
- Later modify: 前端白名单文件

- [ ] **Step 1：扩展静态合同读取范围**

增加读取：

```text
src/App.tsx
src/newcarRedirect.ts
src/components/SideNav.tsx
src/features/capabilities.ts
src/features/routes.ts
src/features/compute/routes.ts
src/pages/Index.tsx
```

- [ ] **Step 2：增加冻结断言**

静态检查必须验证：

```javascript
if (!app.includes('path: "/admin/compute-config"')) throw new Error('缺少管理员算力配置路由');
if (!app.includes('PERMISSIONS.adminComputeConfig')) throw new Error('管理员路由未绑定精确权限');
if (!sideNav.includes('id: "admin-compute-config"')) throw new Error('管理员侧栏缺少算力配置');
if (!indexPage.includes('superActiveNav === "admin-compute-config"')) throw new Error('Index 缺少管理员算力配置分发');
if (capabilities.includes('id: "compute-packages"')) throw new Error('普通算力导航仍包含套餐配置');
if (capabilities.includes('id: "compute-markup-ratios"')) throw new Error('普通算力导航仍包含计费比例');
if (!legacyRoutes.includes('{ from: "/compute/packages", to: "/admin/compute-config?view=packages" }')) throw new Error('套餐旧地址未兼容跳转');
if (!legacyRoutes.includes('{ from: "/compute/markup-ratios", to: "/admin/compute-config?view=ratios" }')) throw new Error('比例旧地址未兼容跳转');
for (const label of ['计费比例', '套餐管理', '商户发放']) {
  if (!superConfig.includes(label)) throw new Error(`算力配置缺少视图：${label}`);
}
if (superConfig.includes('<ModuleTabs')) throw new Error('算力配置仍使用路由式二级导航');
if (superConfig.includes('/admin/compute/markup-ratios')) throw new Error('页面显示内部接口路径');
if (superConfig.includes('seed')) throw new Error('页面显示内部初始化术语');
```

保留现有商户流水七字段、内部令牌和内部服务直连门禁。

- [ ] **Step 3：运行红灯**

```powershell
cd frontend
npm run phase10-compute:check
```

预期：管理员入口或三个视图断言失败。

---

## 7. Task 5：前端路由、导航与权限分发

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/newcarRedirect.ts`
- Modify: `frontend/src/components/SideNav.tsx`
- Modify: `frontend/src/features/capabilities.ts`
- Modify: `frontend/src/features/routes.ts`
- Modify: `frontend/src/features/compute/routes.ts`
- Modify: `frontend/src/pages/Index.tsx`

- [ ] **Step 1：注册管理员路由**

在 `adminRoutes` 增加：

```typescript
{
  path: "/admin/compute-config",
  navId: "admin-compute-config",
  permission: PERMISSIONS.adminComputeConfig,
},
```

在 `defaultPathForUser()` 中增加精确权限默认落点；顺序放在已有本地管理员功能之后、NewCar 归属占位页之前：

```typescript
if (hasPermission(user, PERMISSIONS.adminComputeConfig)) return "/admin/compute-config";
```

在 `canAccessPath()` 增加相同精确权限判断。

- [ ] **Step 2：让旧跳转支持目标查询参数**

修改 `LegacyRedirect`，兼容 `to` 自带查询参数且保留来源查询和 hash：

```typescript
function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  const sourceQuery = location.search.startsWith("?") ? location.search.slice(1) : location.search;
  const separator = to.includes("?") ? "&" : "?";
  const destination = sourceQuery ? `${to}${separator}${sourceQuery}` : to;
  return <Navigate to={`${destination}${location.hash || ""}`} replace />;
}
```

不得改变无查询参数旧路由的既有结果。

- [ ] **Step 3：迁移旧算力管理地址**

从 `computeRoutes` 删除 `/compute/packages`、`/compute/markup-ratios`。从 `capabilityNavCenters` 的普通算力中心删除对应两个 children。

在 `legacyRouteRedirects` 增加：

```typescript
{ from: "/compute/packages", to: "/admin/compute-config?view=packages" },
{ from: "/compute/markup-ratios", to: "/admin/compute-config?view=ratios" },
```

- [ ] **Step 4：管理员侧栏**

在 `adminItems` 增加：

```typescript
{
  id: "admin-compute-config",
  label: "算力",
  expandedLabel: "算力配置",
  path: "/admin/compute-config",
  permission: PERMISSIONS.adminComputeConfig,
},
```

在 `adminIcons` 中复用 `CoinsIcon`。

- [ ] **Step 5：管理员内容分发**

`isAdminRouteNav()` 已识别 `admin-` 前缀，无需新增特例。在管理员内容分发中增加：

```tsx
superActiveNav === "admin-compute-config" ? (
  <SuperComputeConfig />
) :
```

删除商户内容区 `isComputeConfigNav` 及其 `SuperComputeConfig` 分支。商户 `ComputeCenter` 保持不变。

- [ ] **Step 6：登录重定向白名单**

在 `ALLOWED_REDIRECT_PATH_PREFIXES` 增加：

```typescript
"/admin/compute-config",
```

---

## 8. Task 6：页面内三个切换视图

**Files:**
- Modify: `frontend/src/features/compute/pages/SuperComputeConfig.tsx`

- [ ] **Step 1：移除路由式 ModuleTabs**

删除 `ModuleTabs`、`ModuleTabItem`、`DEFAULT_COMPUTE_CONFIG_TABS` 和组件 `tabs` 参数。增加：

```typescript
import { useSearchParams } from "react-router-dom";

type ComputeConfigView = "ratios" | "packages" | "merchant-grant";

const CONFIG_VIEWS: Array<{ id: ComputeConfigView; label: string }> = [
  { id: "ratios", label: "计费比例" },
  { id: "packages", label: "套餐管理" },
  { id: "merchant-grant", label: "商户发放" },
];

function normalizeConfigView(value: string | null): ComputeConfigView {
  return CONFIG_VIEWS.some((item) => item.id === value)
    ? (value as ComputeConfigView)
    : "ratios";
}
```

组件内使用：

```typescript
const [searchParams, setSearchParams] = useSearchParams();
const activeView = normalizeConfigView(searchParams.get("view"));
const selectView = (view: ComputeConfigView) => {
  setSearchParams({ view }, { replace: true });
};
```

- [ ] **Step 2：按当前视图加载**

替换两个无条件加载 effect：

```typescript
useEffect(() => {
  if (activeView === "ratios") {
    void loadRatios();
  } else {
    void loadPackages();
  }
}, [activeView, loadPackages, loadRatios]);
```

顶部刷新按钮按 `activeView` 调用 `loadRatios()` 或 `loadPackages()`，禁用态同步当前加载状态。

- [ ] **Step 3：增加页面内切换控件**

标题改为“算力配置”，标题下使用：

```tsx
<nav aria-label="算力配置视图" className="mt-3 inline-flex rounded-lg border border-[#e4e8f0] bg-[#f8fafc] p-0.5 text-xs font-semibold">
  {CONFIG_VIEWS.map((item) => (
    <button
      key={item.id}
      type="button"
      aria-pressed={activeView === item.id}
      onClick={() => selectView(item.id)}
      className={`rounded-md px-4 py-1.5 transition ${
        activeView === item.id
          ? "bg-white text-[#2563eb] shadow-sm"
          : "text-[#8b95a6] hover:text-[#475467]"
      }`}
    >
      {item.label}
    </button>
  ))}
</nav>
```

- [ ] **Step 4：条件渲染现有区域**

- `activeView === "packages"`：只渲染套餐列表和套餐编辑区。
- `activeView === "ratios"`：只渲染能力上浮比例区。
- `activeView === "merchant-grant"`：只渲染非真实支付提示、商户充值和套餐发放区。

不得复制已有表单或状态；使用同一份 JSX 和 state。

- [ ] **Step 5：收敛本页可见文案**

必须删除或替换：

```text
“来源：GET/PUT /admin/compute/markup-ratios · 权限：算力配置”
→ “设置各项 AI 能力的计费加成比例”

“暂无上浮比例配置（配置漂移请联系管理员重新初始化六能力 seed）。”
→ “算力比例配置异常，请联系管理员处理。”

“算力点数 数量”
→ “算力点数数量”
```

保留加载、空数据、错误重试、成功提示和减少动画偏好支持。

- [ ] **Step 6：运行前端绿灯**

```powershell
cd frontend
npm run phase10-compute:check
npm run build
npx eslint src/App.tsx src/newcarRedirect.ts src/components/SideNav.tsx src/features/capabilities.ts src/features/routes.ts src/features/compute/routes.ts src/pages/Index.tsx src/features/compute/pages/SuperComputeConfig.tsx scripts/check-phase10-compute-contract.mjs
```

记录每条命令真实退出码。代码检查存在既有失败时，必须在业务代码起点 `1b4c755f5150b70936b3957f7acc9fa4088eff5e` 的独立 worktree 中运行同命令对照，证明零新增。

---

## 9. Checkpoint B：前端候选提交

- [ ] 执行：

```powershell
cd frontend
npm run phase10-compute:check
npm run build
cd ..
git diff --check -- frontend
```

- [ ] 只暂存以下文件：

```text
frontend/src/App.tsx
frontend/src/newcarRedirect.ts
frontend/src/components/SideNav.tsx
frontend/src/features/capabilities.ts
frontend/src/features/routes.ts
frontend/src/features/compute/routes.ts
frontend/src/pages/Index.tsx
frontend/src/features/compute/pages/SuperComputeConfig.tsx
frontend/scripts/check-phase10-compute-contract.mjs
```

- [ ] 提交信息：

```text
接通管理员算力配置统一入口
```

- [ ] 不得暂存构建产物或 `.gitignore`，记录完整提交哈希，不推送。

---

## 10. Task 7：浏览器验收

在非生产本地环境执行，禁止连接生产数据库。

### 10.1 视口矩阵

```text
1024 × 768
1440 × 900
```

### 10.2 必验路径

1. `/admin/compute-config` 默认显示“计费比例”。
2. 三个视图可点击切换，URL 分别为 `view=ratios/packages/merchant-grant`。
3. `/compute/packages` 跳转至统一入口的套餐管理视图。
4. `/compute/markup-ratios` 跳转至统一入口的计费比例视图。
5. 管理员侧栏存在带图标的“算力配置”。
6. 1024 和 1440 下无横向页面溢出，按钮和输入框不重叠。
7. 加载、空数据、错误重试和成功反馈仍可见。
8. 普通商户直接访问 `/admin/compute-config` 显示权限拒绝。

无法构造精确权限登录态时，必须标记 `BLOCKED_ENVIRONMENT` 并保留为残余风险；静态代码证据不能写成浏览器通过。

---

## 11. Task 8：完整回归

- [ ] 后端专项：

```powershell
$env:XG_DOUYIN_AI_CS_SERVICE_TOKEN=""
python -m pytest tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_models.py tests/test_compute_client.py tests/test_compute_usage_client.py tests/test_phase10_compute_markup_api.py tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py tests/test_phase10_compute_no_network.py -q
```

- [ ] 前端：

```powershell
cd frontend
npm run phase10-compute:check
npm run build
npx eslint src/App.tsx src/newcarRedirect.ts src/components/SideNav.tsx src/features/capabilities.ts src/features/routes.ts src/features/compute/routes.ts src/pages/Index.tsx src/features/compute/pages/SuperComputeConfig.tsx scripts/check-phase10-compute-contract.mjs
cd ..
```

- [ ] 差异检查：

```powershell
git diff --check
git status --short
git log --oneline --decorate -5
```

- [ ] 明确报告外网、生产 PostgreSQL、宝塔和真实付费模型调用次数，预期均为 0。

---

## 12. Task 9：文档原位更新

**Files:**
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md`
- Modify: `docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md`

- [ ] 以代码、测试和浏览器证据原位更新事实，不追加日期流水账。
- [ ] `05_PROJECT_CONTEXT.md` 明确管理员单入口、三个内部视图和精确权限。
- [ ] 验收文档记录 Checkpoint A/B 完整提交哈希、测试数量、未覆盖浏览器场景和残余风险。
- [ ] 总设计把阶段三状态改为“候选实现完成、待独立测试”；不得提前写成已发布或生产验证完成。
- [ ] 治理规则文件无影响，不修改 `01`～`04`。

只暂存三份文档并提交：

```text
更新管理员算力配置接入事实
```

记录完整提交哈希，不推送。

---

## 13. 候选提交边界

最终候选必须是连续三个本地提交：

```text
提交 A：统一管理员算力配置接口权限
  app/routers/compute.py
  apps/compute/dependencies.py
  apps/compute/routers.py
  tests/test_compute_router.py
  tests/test_compute_app.py
  tests/test_phase10_compute_markup_api.py

提交 B：接通管理员算力配置统一入口
  frontend/src/App.tsx
  frontend/src/newcarRedirect.ts
  frontend/src/components/SideNav.tsx
  frontend/src/features/capabilities.ts
  frontend/src/features/routes.ts
  frontend/src/features/compute/routes.ts
  frontend/src/pages/Index.tsx
  frontend/src/features/compute/pages/SuperComputeConfig.tsx
  frontend/scripts/check-phase10-compute-contract.mjs

提交 C：更新管理员算力配置接入事实
  docs/ai/05_PROJECT_CONTEXT.md
  docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md
  docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
```

禁止 `git add .`、amend、rebase、squash、reset、force push、普通 push 和部署。

---

## 14. 执行窗口回传格式

```text
EXECUTION_REPORT
Task-ID / Plan-Revision / Execution-Package-ID
执行基线 / 实际起始 HEAD / Candidate-Commit
三个候选提交的完整哈希与文件清单
红灯命令、失败原因和退出码
权限矩阵（9000 + 独立算力服务）
写操作日志字段、成功/失败证据和脱敏结果
后端测试命令、通过/失败数量和退出码
前端合同、构建、定向代码检查结果和退出码
浏览器 1024/1440 矩阵、截图路径与环境阻塞
git show --check（三个提交）
git status --short
外网/生产数据库/宝塔/付费模型调用次数
未覆盖场景和残余风险
是否触碰禁止范围
未推送、未部署确认
```

执行结束后硬暂停，不得通知测试窗口自行开测；等待审批窗口审查并下发绑定完整候选哈希的 `APPROVE_TEST`。
