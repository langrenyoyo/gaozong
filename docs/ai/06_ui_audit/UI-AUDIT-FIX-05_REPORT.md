# UI-AUDIT-FIX-05 减少动画偏好与语义复选框执行报告

## 1. 阶段目标与严格边界

**目标**：处理全站减少动画偏好（`prefers-reduced-motion`），并将现有非语义复选框补齐为可被键盘和屏幕阅读器识别的复选框。只修复可访问性和动画降级，不改变业务逻辑、接口和品牌视觉。

**已遵守的边界**：
- ✅ 只修改 `frontend/src/index.css` 与本报告文件
- ✅ 未修改后端、数据库、接口、迁移
- ✅ 未修改鉴权、权限、路由（含 `frontend/src/features/routes.ts` 等无关改动未触碰）
- ✅ 未修改微信自动化、Local Agent、发送 gate
- ✅ 未修改表单提交逻辑、业务状态字段和请求参数
- ✅ 未修改 `package.json`、锁文件和依赖
- ✅ 未修改当前工作区其他未提交改动
- ✅ 未使用 `git add .`
- ✅ 未自行提交

## 2. 执行前工作区状态

执行时实际 `git status --short`：

```
 M .gitignore
 M "docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md"
 M "docs/待确认事项.md"
 M frontend/src/features/routes.ts
 M tests/test_phase8b_local_agent_downloader.py
?? -i
?? frontend/scripts/check-phase12-ai-edit-contract.mjs
?? frontend/src/features/ai-edit/
?? scripts/generate_phase8_visual_samples.py
```

与本任务无关、未纳入本阶段的改动：`.gitignore`、`docs/` 文档、`tests/` 测试、`-i`、`frontend/scripts/check-phase12-ai-edit-contract.mjs`、`frontend/src/features/ai-edit/`、`scripts/generate_phase8_visual_samples.py`、`frontend/src/features/routes.ts`。

本阶段仅触碰：`frontend/src/index.css` 与本报告文件。

## 3. 动画类和关键帧扫描结果

### 自定义动画类（`frontend/src/index.css`）
| 类/关键帧 | 定义 | 实际使用位置 | 性质 |
|----------|------|-------------|------|
| `.status-dot-pulse` + `@keyframes statusPulse` | 在线状态点脉冲 | `features/leads/components/ChatPanel.tsx:52` | 装饰性运动 |
| `.shimmer` + `@keyframes shimmer` | 骨架屏微光 | 仅 css 定义，0 组件引用 | 死规则（仍降级） |
| `.transition-smooth` | `transition: all 0.22s` | 侧边栏/按钮等多处 | 焦点/悬停反馈，保留 |

### Tailwind 内置动画类（`animate-spin`）
| 使用位置 | 上下文 | 旁置文本 |
|---------|--------|---------|
| `AdminAutoreplyRolloutPage.tsx:404,492` | 刷新/保存加载 | 有按钮文字 |
| `AdminReturnVisitsPage.tsx:279,549,598` | 加载状态 | "加载中…" |
| `Index.tsx:570` | 授权中 | "授权中" |
| `LeadsManagement.tsx` 等 | 列表加载 | "加载中..." |
| `DailyReports.tsx:378` | 生成报表 | "生成中" |
| `ComputeCenter.tsx` 等 | 刷新 | 多数有按钮文字 |
| `SuperMerchantAgent.tsx:508` 等 | 图标按钮刷新 | 无旁置文字，靠 `aria-label` + `disabled` |

### `motion-safe` / `motion-reduce` 内联使用
- 扫描结果：**0 处**。全站未使用 Tailwind 的 `motion-safe:`/`motion-reduce:` 变体，需通过全局 media query 统一降级。

## 4. 复选框审计清单

| 文件 | 行 | 实现 | label 关联 | 键盘/空格 | 屏读名称 | 是否需修复 |
|------|----|------|-----------|----------|---------|-----------|
| `WechatAgent.tsx` | 845-884 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否（已语义正确） |
| `WechatAgent.tsx` | 1384-1423 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `DailyReports.tsx` | 344-352 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `DailyReports.tsx` | 576-578 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `AdminAutoreplyRolloutPage.tsx` | 136-144 | `ToggleInput` 原生 checkbox + `<label>` | 隐式 | ✅ | ✅ | 否 |
| `AdminReturnVisitsPage.tsx` | 409-417 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `SuperMerchantAgent.tsx` | 249-260 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `SuperComputeConfig.tsx` | 555-563 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `SuperComputeConfig.tsx` | 657-667 | 原生 checkbox + `<label>` 包裹 | 隐式 | ✅ | ✅ | 否 |
| `DouyinAutoReplySettingsPage.tsx` | 388-402 | `role="switch"` 开关 | — | ✅ | ✅ | 否（开关非复选框，规范禁止误改） |
| `DouyinAiCsWorkbenchPage.tsx` | 2906-2912 | 原生 radio + `<label>` | 隐式 | ✅ | ✅ | 否（单选非复选框） |

**结论**：全站复选框均已采用原生 `<input type="checkbox">` 并以 `<label>` 包裹（隐式 label 关联），键盘 Tab 可聚焦、空格可切换、屏幕阅读器可获名称、checked/disabled 与业务状态同步。**无任何 div/纯点击区域模拟的复选框需要修复。** 按规范"如果扫描确认某文件已经使用原生复选框或现有 Checkbox，不要为制造修改而改动"，本阶段不对复选框做任何改动。

仓库已有 shadcn `Checkbox` 组件（`components/ui/checkbox.tsx`，基于 `@radix-ui/react-checkbox`），但现有业务复选框均为原生控件且语义正确，无需替换。

## 5. 实际修改文件

仅 1 个文件：

- `frontend/src/index.css` — 在 `@layer utilities` 末尾追加 `@media (prefers-reduced-motion: reduce)` 降级块

## 6. 减少动画规则修改说明

在 `frontend/src/index.css` 的 `@layer utilities` 内、`.nav-item-active` 之后追加：

```css
/* 减少动画偏好：仅停用装饰性/非必要运动，保留加载图标与文本、焦点和状态反馈 */
@media (prefers-reduced-motion: reduce) {
  .status-dot-pulse,
  .shimmer {
    animation: none;
  }
  /* 旋转加载图标停用动画，但保留图标本体与旁置加载文本 */
  .animate-spin {
    animation: none;
  }
}
```

### 设计依据
- `.status-dot-pulse`：在线状态点脉冲，纯装饰性运动 → 停用
- `.shimmer`：骨架屏微光，装饰性 → 停用（且 0 组件引用）
- `.animate-spin`：加载旋转图标 → 停用旋转，但保留图标本体。多数加载场景有旁置文字；部分图标按钮（如 `SuperMerchantAgent.tsx:508` 刷新按钮）无旁置文字，通过 `aria-label` 可访问名称、`disabled` 禁用状态和既有页面上下文表达加载状态。减少动画模式仅停用旋转，不移除图标、按钮名称或加载状态逻辑
- `.transition-smooth` 及其他 `transition-*`：**保留**，属焦点/悬停/状态变化反馈，规范要求保留
- 未全局删除所有过渡；未影响加载状态可见性；未改变加载/成功/失败状态逻辑

## 7. 每个复选框的语义修复说明

**无复选框被修改。** 见 §4 审计清单，所有复选框均已语义正确，按最小修改原则不改动。

## 8. 键盘与屏幕阅读器验证结果

由于未修改任何复选框，此项为既有状态确认：
- 所有现有原生 checkbox 通过 `<label>` 包裹获得可访问名称
- 原生 checkbox 默认支持 Tab 聚焦、空格切换
- `checked`/`disabled` 与 React 受控状态同步

本阶段未对复选框做任何改动，无回归风险。

## 9. reduce / no-preference 验证结果

| 模式 | 动画行为 | 加载状态 |
|------|---------|---------|
| `prefers-reduced-motion: no-preference` | `.status-dot-pulse` 脉冲、`.shimmer` 微光、`.animate-spin` 旋转均正常 | 旋转图标 + 多数有旁置文字 |
| `prefers-reduced-motion: reduce` | 上述装饰性/旋转动画全部停用 | 图标本体保留；多数场景旁置文字保留，图标按钮靠 `aria-label` + `disabled` 表达加载 |

> 注：多数加载场景有旁置文字；部分图标按钮（如 `SuperMerchantAgent.tsx:508`）通过 `aria-label` 可访问名称、`disabled` 禁用状态和既有页面上下文表达加载状态。减少动画模式仅停用旋转，不移除图标、按钮名称或加载状态逻辑。此项为基于 CSS 规则的静态等价验证（见 §14 残余风险），未执行真实浏览器偏好切换截图。

## 10. 1024/1440 页面验收结果

本阶段代码修改仅追加一段 CSS media query，不影响布局、不改变颜色、不增删 DOM 节点，无布局跳动或水平溢出风险。

由于无可见布局变化且无法稳定切换系统减少动画偏好，本阶段采用静态等价验证，未生成 1024/1440 矩阵正式验收截图（见 §14 残余风险）。

## 11. build、lint、diff 检查结果

### Build
```
npm run build → ✓ 成功（1917 modules transformed, built in 3.63s）
```
- CSS 产物 140.92 KB → 141.48 KB（+0.56 KB，降级规则增量）
- 无新增错误

### Lint
```
npm run lint → 43 errors, 9 warnings（全部为预存问题）
```
- 新增 lint 问题：**0**
- 所有 error 均来自 `.d.ts`/`.tsx` 文件（`@typescript-eslint/no-empty-object-type`、`react-hooks/set-state-in-effect` 等），与本任务 CSS 改动无关（CSS 不参与 eslint ts/tsx 规则）
- `npx eslint frontend/src/index.css`：CSS 不在 eslint 检查范围，无输出

### Git diff
```
git diff --check
```
- `frontend/src/index.css`：无空白错误
- 输出中的 trailing whitespace 报错全部来自 `docs/待确认事项.md`（预存改动，非本任务范围，未触碰）

## 12. 截图清单

截图目录：`docs/ai/06_ui_audit/shots/fix05/`（已创建，当前为空）

本阶段未生成正式浏览器验收截图（理由见 §14 残余风险）。规范建议的三张截图（`01_reduced_motion.png`、`02_checkbox_keyboard.png`、`03_checkbox_form.png`）未产出，因：
1. 无法稳定切换系统 `prefers-reduced-motion` 偏好；
2. 本阶段未修改任何复选框，无键盘交互变化可供截图。

## 13. 文档影响检查

无文档影响。本次仅追加 CSS 减少动画降级规则，不改变任何可见业务行为或系统边界。

## 14. 未解决问题和残余风险

### 残余风险
1. **未执行真实浏览器 `prefers-reduced-motion` 切换验证**：浏览器无法稳定切换系统减少动画偏好，本阶段降级规则基于 CSS 规范静态编写，未在真实 reduce 模式下截图验证。规范明确要求此类情况必须记录为残余风险，不得声称已完成真实浏览器验证。**本报告不声称已完成真实浏览器矩阵验证。**
2. **复选框键盘交互未真实浏览器验证**：本阶段未修改复选框，既有原生控件语义正确，但未在浏览器中实际执行 Tab/空格操作截图。

### 未纳入本阶段（按规范）
- 加载/空数据/错误/成功状态的视觉样式重构 — 留给后续阶段
- 弹窗 Esc、焦点恢复等交互语义 — 留给后续阶段

### 关于 `.shimmer` 死规则
`.shimmer` 在 `index.css` 定义但 0 组件引用，属死规则。本阶段仅对其降级（最小影响），未删除（删除属清理，超出本阶段"减少动画"范围，避免扩大改动面）。

## 15. 未触碰范围确认

- ✅ 未触碰业务逻辑
- ✅ 未触碰鉴权、权限、路由
- ✅ 未触碰接口和请求参数
- ✅ 未触碰微信自动化、Local Agent、发送 gate
- ✅ 未触碰 package.json 和依赖
- ✅ 未触碰当前工作区其他未提交改动（含 `routes.ts`、`features/ai-edit/` 等）

## 16. 结论

**修改摘要**：在 `frontend/src/index.css` 追加 `@media (prefers-reduced-motion: reduce)` 降级规则，停用装饰性动画（`.status-dot-pulse`、`.shimmer`）和加载旋转（`.animate-spin`），保留图标本体、按钮可访问名称、加载状态逻辑与焦点/悬停过渡反馈。复选框审计确认全站已语义正确，无需修改。

**修改文件清单**：
- `frontend/src/index.css`

**动画降级清单**：
- `.status-dot-pulse` → `animation: none`（装饰性脉冲）
- `.shimmer` → `animation: none`（装饰性微光，0 引用）
- `.animate-spin` → `animation: none`（加载旋转，保留图标与文字）
- `.transition-smooth` 等过渡 → 保留（焦点/悬停反馈）

**复选框语义修复清单**：无。全站复选框均已为原生 `<input type="checkbox">` + `<label>`，语义正确。

**验证结果**：build ✓，lint 0 新增问题，index.css diff 无空白错误。

**截图路径**：`docs/ai/06_ui_audit/shots/fix05/`（空目录，未生成正式截图，见残余风险）

**未解决问题**：未执行真实浏览器 `prefers-reduced-motion` 切换验证（残余风险）。

**是否提交**：未提交，等待审批。
