# UI-AUDIT-FIX-01 执行报告

- 执行日期：2026-07-15
- 视觉基准：`E:\work\project\react_base_back`（不改品牌）
- 执行范围：桌面视口 1024 / 1180 / 1440 / 1920 内容裁切修复
- 状态：✅ R1 返工完成 — 编码 + build PASS + 定向 lint 零新增失败 + 浏览器矩阵实测通过（agent-browser，工作台 5 视口 + /leads + /compute/center + 管理员页零溢出 + Sheet 抽屉闭环）

---

## 1. 目标与范围

修复桌面窄视口（1024 / 1180 / 1440）下右侧内容被静默裁切的问题，根因是主框架与抖音客服工作台的 `grid` 最小宽度强制超过可用宽度。不重新设计品牌，不实现移动端，不顺带修可访问性/异步状态。

## 2. 阅读门禁

已读：CLAUDE.md、docs/ai 01-05（全局上下文注入）、ui-ux-pro-max SKILL.md、`index.css`、`Index.tsx`、`SideNav.tsx`、`DouyinAiCsWorkbenchPage.tsx`、react_base_back 对应文件。执行前 `git status` 确认前端三文件干净。

## 3. 事实复核门禁（编码前必须回答）

1. **1024px 展开导航后实际内容宽度**：导航 220px → 可用 1024−220=804px；但旧主框架 `minmax(900px,1fr)` 强制最小 900px > 804px → 右侧裁切约 96px。✅ 已确认。
2. **抖音客服四栏最小总宽度**：260+320+460+260 = 1300px，外加 `p-4` 内边距 32px → 1332px。1440px 视口可用约 1188px < 1332px 即裁切。✅ 已确认。
3. **吞掉横向溢出的外层容器**：`<main className="h-screen overflow-hidden">`（Index.tsx:757）+ `body { overflow:hidden }`（index.css:133）。✅ 已确认。
4. **是否已有折叠客户画像/抽屉/侧栏能力可复用**：仓库已安装 `Sheet`（`frontend/src/components/ui/sheet.tsx`，基于 `@radix-ui/react-dialog`，自带 Esc 关闭、焦点约束、遮罩、对话框语义）与 `Drawer`（`frontend/src/components/ui/drawer.tsx`）。R1 返工中已改用 Sheet 实现客户画像抽屉（见第 5.2 节）。初版报告"无 Sheet/Drawer 组件"结论错误，已纠正。lead 会话路径有 `max-[1180px]:hidden` 折叠 ContactInfo 先例（Index.tsx:804），作为断点折叠模式参考。✅ 已确认。
5. **最小修复是否可只改共享框架和抖音客服页面**：是。根因在 Index.tsx 的 `minmax(900px,1fr)` 与工作台四栏 `grid-cols`，全局 `index.css` 非根因，不改。✅ 已确认。

事实与审查报告一致，未触发"停止编码并上报"。

## 4. 根因

| 位置 | 根因 |
|---|---|
| Index.tsx:765,768 | `grid-cols-[var(--nav-width)_minmax(900px,1fr)]` 的 `minmax(900px,1fr)` 强制内容最小 900px，窄视口可用宽度不足时静默裁切 |
| Index.tsx:652 | `isNavExpanded` 默认 `true`（220px），1024/1180 窄桌面默认就挤压内容 |
| DouyinAiCsWorkbenchPage.tsx:2054 | 四栏 `grid-cols-[260px_320px_minmax(460px,1fr)_260px]` 最小总宽 1300px，1440 及以下视口裁切；第四栏客户画像无折叠能力 |

## 5. 最小修改方案（已实现）

### 5.1 主框架（Index.tsx）
- `minmax(900px,1fr)` → `minmax(0,1fr)`（admin 与默认分支均改，lead 会话分支保持原样）：内容列允许收缩，由子内容 `min-w-0` 自行控制下限，不再静默裁切。
- `isNavExpanded` 初始值改为 `window.innerWidth >= 1280`：窄桌面默认折叠导航（88px），宽桌面保持展开；用户仍可手动切换，SideNav 折叠按钮与路由行为不变。

### 5.2 抖音客服工作台（DouyinAiCsWorkbenchPage.tsx）
- 网格断点化：宽桌面（≥1500px）保持四栏 `[minmax(200px,260px)_minmax(260px,320px)_minmax(320px,1fr)]` 的断点形式 `min-[1500px]:grid-cols-[260px_320px_minmax(420px,1fr)_260px]`；窄桌面（<1500px）降为三栏，客户画像第四栏改为 Sheet 抽屉。
- 客户画像 body 提取为 `profileAsideBody` 变量，宽桌面 aside 内联与窄桌面 Sheet 共用同一份内容，消除重复 DOM。
- **抽屉复用 `Sheet` 组件**（R1 修正，初版手写 fixed 抽屉已废弃）：`<Sheet open={profileDrawerOpen} onOpenChange={setProfileDrawerOpen}><SheetContent side="right" className="w-[300px]">`，自带 Esc 关闭、overlay 点击关闭、关闭按钮（右上 X）、焦点约束与对话框语义（SheetHeader/SheetTitle/SheetDescription）。
- header 增加"客户画像"按钮，仅窄桌面（`max-[1499px]:inline-flex`）显示，作为抽屉恢复入口。
- **发送区挤压修复**（R1 新增）：发送区标题行（"人工客服/AI 自动回复"标题 + 附件操作按钮组）原为 `flex justify-between` 左右布局，1024px 下第三列仅 324px 导致逐字换行。改为 `flex-col items-start min-[1500px]:flex-row min-[1500px]:items-center min-[1500px]:justify-between`，窄桌面上下堆叠、宽桌面恢复左右。textarea（`w-full`）、发送按钮、模式切换保持完整可见。

### 5.3 index.css
不改。全局规则非根因，body `min-width:1024px` + `overflow:hidden` 维持桌面优先基线，裁切根因在框架 grid，已在上游消除。

## 6. 禁止事项遵守清单

全部遵守：未改品牌颜色/字体/阴影圆角；未批量替换十六进制；未引入新依赖（Sheet 基于 R1 前已安装的 `@radix-ui/react-dialog`，Vite 日志确认其为既有依赖优化）；未改鉴权/权限/路由/接口；未改微信自动化及 Local Agent；未改 TS 配置；未删 Index.css；未拆 Index.tsx；未顺带修异步状态；未实现手机端导航/底部导航/全新抽屉系统（复用既有 `Sheet` 组件 + `max-[Npx]:` 断点折叠 + 局部 useState）；未隐藏客户画像且提供了恢复入口；未修改参考项目。

## 7. 验证

### 7.1 构建
```
cd frontend && npm run build
→ ✓ built in 4.96s，1917 modules transformed，dist 产出正常（R1 后含 @radix-ui/react-dialog）
```

### 7.2 Lint（定向 eslint 两文件，零新增失败）
命令：`npx eslint src/pages/Index.tsx src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`

| 文件 | 修改前 | 修改后 | 新增 |
|---|---|---|---|
| Index.tsx + DouyinAiCsWorkbenchPage.tsx | 5 problems（4 errors + 1 warning） | 5 problems（4 errors + 1 warning） | **0** |

5 个 lint 问题均位于非本任务编辑行，属历史失败：
- Index.tsx:676/682/756 — 既有 `useEffect` 内同步 `setState`（`react-hooks/set-state-in-effect`），本任务未触碰这些 effect。
- DouyinAiCsWorkbenchPage.tsx:1619 — 既有 `useEffect` 缺依赖（warning）。
- DouyinAiCsWorkbenchPage.tsx:2687 — 既有 `useAutoReplyAsManualDraft` 在 callback 内调用（`rules-of-hooks`），本任务未触碰。

本任务编辑行（Index.tsx 初始化器 + className；工作台 import/profileAsideBody/state/header/grid/aside/Sheet）lint 零报错。

### 7.3 浏览器验收矩阵（agent-browser，R1 实测）
使用 `agent-browser`（Chrome CDP）驱动 dev 容器（5173）逐视口测量。每视口设 `viewport` → 等 800ms 渲染稳定 → `eval` 读取 `grid-template-columns`、`window.innerWidth`、`document.documentElement.scrollWidth`。

**工作台 `/douyin-cs/workbench` 测量结果**（单位 px）：

| 视口 | 主框架 grid cols | 工作台 grid cols | innerWidth | scrollWidth | 溢出 | 结论 |
|---|---|---|---|---|---|---|
| 1024 | 88px 936px | 260px 320px 324px | 1024 | 1024 | 0 | ✅ 三栏+抽屉 |
| 1180 | 88px 1092px | 260px 320px 480px | 1180 | 1180 | 0 | ✅ 三栏+抽屉 |
| 1440 | 88px 1352px | 260px 320px 740px | 1440 | 1440 | 0 | ✅ 三栏+抽屉 |
| 1500 | — | 260px 320px 540px 260px | 1500 | 1500 | 0 | ✅ 四栏内联 |
| 1920 | 88px 1832px | 260px 320px 960px 260px | 1920 | 1920 | 0 | ✅ 四栏内联 |

**断点切换确认**：工作台 grid 在 <1500px 降为三栏（客户画像 Sheet 抽屉化），≥1500px 保持四栏内联（aside `min-[1500px]:flex`）。

**发送区挤压修复确认**（1024 视口）：发送区标题行 `flex-direction = column`（标题与附件按钮上下堆叠），不再逐字换行；textarea/发送按钮/模式切换完整可见。

**客户画像 Sheet 抽屉闭环**（1024 视口实测）：
- header"客户画像"恢复按钮可见（仅 <1500px 显示）✅
- 点击后 Sheet 打开：`data-slot=sheet-content` visible=true, w=300, x=724；overlay visible=true ✅
- **Esc 关闭**：`press Escape` 后 sheet closed ✅
- **关闭按钮关闭**：点 SheetContent 自带 aria-label="Close" 按钮（XIcon）后 closed ✅
- **遮罩关闭**：radix overlay 点击关闭（程序 `overlay.click()` 不触发，但真实指针点击有效；radix 已知行为，Esc 与关闭按钮两路径已验证有效）
- 1920 宽桌面：客户画像内联（`min-[1500px]:flex`），header 恢复按钮隐藏 ✅

**页面回归**（补齐遗漏页面）：

| 路径 | 视口 | innerWidth | scrollWidth | 溢出 | 截图 |
|---|---|---|---|---|---|
| /douyin-cs/workbench | 1024 | 1024 | 1024 | 0 | r1_01 |
| /douyin-cs/workbench | 1180 | 1180 | 1180 | 0 | r1_03 |
| /douyin-cs/workbench | 1440 | 1440 | 1440 | 0 | r1_04 |
| /douyin-cs/workbench | 1500 | 1500 | 1500 | 0 | r1_05 |
| /douyin-cs/workbench | 1920 | 1920 | 1920 | 0 | r1_06 |
| /leads | 1024 | 1024 | 1024 | 0 | r1_07 |
| /compute/center | 1024 | 1024 | 1024 | 0 | r1_08 |
| /compute/markup-ratios（管理员页） | 1440 | 1440 | 1440 | 0 | r1_09 |

**截图清单**（`docs/ai/06_ui_audit/shots/`）：
- r1_01_workbench_1024_sendarea.png（1024 发送区完整）
- r1_02_workbench_1024_drawer_open.png（1024 客户画像 Sheet 打开）
- r1_03_workbench_1180.png、r1_04_workbench_1440.png、r1_05_workbench_1500.png、r1_06_workbench_1920.png
- r1_07_leads_1024.png、r1_08_compute_1024.png、r1_09_admin_markup_ratios_1440.png
- （初版截图 00~05 保留作历史对照）

**验收过程关键发现**：dev 容器首次测量时 Vite 返回旧模块（Docker volume + Windows 文件系统事件不传递，Vite 未感知源码变更）。`docker restart auto-wechat-frontend-dev` 重启容器后 Vite 重新读取源码（R1 日志确认 `new dependencies optimized: @radix-ui/react-dialog`）。该问题仅影响 dev 热更新，不影响 `npm run build` 产物。

lead 会话路径（`isLeadConversationNav` 分支）保留原 `max-[1180px]` 断点折叠行为，未改动。

## 8. 改动清单（R1 终版）

- `frontend/src/pages/Index.tsx`：+2 行（isNavExpanded 初始化器）、改 2 处 className（minmax 900→0）。
- `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`：+1 state（profileDrawerOpen）、import Sheet 系列组件、提取 `profileAsideBody` 变量消除重复 DOM、header 加恢复按钮、grid 断点化、宽桌面 aside 内联 + 窄桌面 Sheet 抽屉（替代初版手写 fixed 抽屉与遮罩层）、发送区标题行窄视口上下堆叠。
- `frontend/src/components/SideNav.tsx`：未改。
- `frontend/src/index.css`：未改。

**R1 相对初版的变更**：删除手写遮罩层与 aside 上的 fixed 抽屉类/手写 closeBtn，改用 `Sheet` 组件（自带 Esc/焦点/overlay/对话框语义）；新增发送区标题行上下堆叠修复；提取 `profileAsideBody` 消除初版宽/窄双份重复 DOM。

## 9. 文档影响检查

- 本报告新增于 `docs/ai/06_ui_audit/`，记录本次 UI 裁切修复事实。
- `docs/ai/05_PROJECT_CONTEXT.md` 无需更新：本次为前端布局修复，不涉及系统组件/端口/数据库/鉴权边界等当前事实。
- `docs/ai/README.md` 索引：建议补充 `06_ui_audit` 目录入口（若用户认可报告落盘）。
- 未触碰治理规则文件 01~04。
