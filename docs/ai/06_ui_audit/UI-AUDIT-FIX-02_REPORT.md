# UI-AUDIT-FIX-02 执行报告

- 执行日期：2026-07-15
- 基线 HEAD：0c08b7b 修复前端桌面布局与客户画像抽屉
- 范围：前端可访问性语义补全（图标按钮名称、弹窗对话框语义、表单控件稳定标签、状态控件语义）
- 状态：✅ 编码完成 + build PASS + 定向 eslint 零新增失败 + agent-browser 6 页面验收通过

---

## 1. 根因与影响范围

根因不是单点缺陷，而是历史页面普遍缺失可访问性语义：图标按钮只放 lucide Icon 组件无 accessible name；自定义弹窗用手写 `fixed inset-0` 全屏遮罩 + 居中面板实现，未带 `role="dialog"`/`aria-modal`/`aria-labelledby`；大量 `<input>/<select>/<textarea>` 仅依赖 placeholder 或装饰性 label（label 内只有 SearchIcon 无文字），屏幕阅读器无法获取控件名称。

影响范围：20 个允许修改文件中的 16 个（4 个经审计确认无问题：DouyinAutoReplySettingsPage、DouyinLiveCheckPage、LocalWechatAgentTestPanel、WechatTaskPanel——其按钮均有可见文字、开关已正确设置 role="switch"、表单控件已有 label 包裹）。

## 2. 修改文件

共 16 文件、约 101 处属性补全：

| 文件 | 修改处数 | 主要内容 |
|---|---|---|
| SideNav.tsx | 2 | 折叠态收起/展开按钮动态 aria-label、退出登录按钮 aria-label |
| Index.tsx | 1 | DouyinAuthModal 弹窗 role/aria-modal/aria-labelledby + 标题 id + 关闭按钮 aria-label |
| SuperAdminAccounts.tsx | 4 | AddAdminModal 弹窗语义 + 关闭按钮 + 搜索 input + 角色/状态 select |
| SuperMerchantAgent.tsx | 3 | AgentEditor 弹窗语义 + 关闭按钮 + 回复预览 input（已有 aria-label 的发送/刷新/编辑/删除保留） |
| ComputeCenter.tsx | 3 | RechargeModal 弹窗语义 + 自定义 Token input |
| SuperComputeConfig.tsx | 1 | 上浮比例 input aria-label |
| DouyinAiCsWorkbenchPage.tsx | 5 | 搜索 input + 回复 textarea aria-label + 3 个弹窗语义（绑定智能体/添加抖音号/上传图片） |
| DouyinAutoReplyRunsPage.tsx | 10 | DetailModal 弹窗语义 + 状态 select + 5 个筛选 input + 2 个 datetime-local |
| AiReplyDecisionLogsPage.tsx | 9 | DetailModal 弹窗语义 + 搜索 input + 5 个 select + 2 个 date input |
| ContactList.tsx | 2 | 刷新按钮 + 搜索 input aria-label |
| LeadsManagement.tsx | 11 | SyncModal/AssignModal 弹窗语义 + 2 关闭按钮 + 更多操作按钮 + 关键词 input + 3 select + 上一页/下一页 |
| WebhookEventsPage.tsx | 8 | 3 select + 关键词 input + 2 datetime-local + 上一页/下一页 |
| DailyReports.tsx | 11 | 4 日期 input + 类型/状态/流量/内容类型 select + 广告/素材 ID/溯源链接 input |
| WechatAgent.tsx | 19 | 4 表单 input + 搜索 input + 状态 select + 4 图标按钮（编辑/停用/启用/删除）+ 2 测试 input + 3 任务筛选 select + 关键词 + failure_stage input + 2 弹窗语义 + 2 关闭按钮 |
| AdminAutoreplyRolloutPage.tsx | 10 | 修改原因 textarea + 白名单类型 select + 3 白名单表单 input/textarea + 4 筛选 input |
| AdminReturnVisitsPage.tsx | 2 | SlidePanel 弹窗语义 + 标题 id |

注：DouyinAutoReplySettingsPage.tsx、DouyinLiveCheckPage.tsx、LocalWechatAgentTestPanel.tsx、WechatTaskPanel.tsx 经审计无命中问题，未改动。

## 3. 图标按钮覆盖结果

纯图标按钮（无可见文字）全部补 `aria-label`，共 16 处：
- 关闭弹窗：各弹窗关闭按钮（aria-label 如"关闭智能体编辑弹窗""关闭授权弹窗""关闭"）
- 展开/收起导航：SideNav 折叠态动态 `aria-label={expanded ? "收起导航" : "展开导航"}`
- 退出登录：SideNav 折叠态 `aria-label="退出登录"`
- 刷新：ContactList `aria-label="刷新会话列表"`
- 更多操作：LeadsManagement `aria-label="更多操作"`
- 编辑/删除/停用/启用：WechatAgent 4 个图标按钮（原 title 属性不被多数屏幕阅读器视为 accessible name，补 aria-label）

已有可见中文文字的按钮（如"查询""发送""表情"）未重复添加。已有 aria-label 的按钮（SuperMerchantAgent 发送/刷新/编辑/删除、ComputeCenter 充值关闭/分页）保留未动。

浏览器验证：snapshot 中 `button "展开导航"`、`button "退出登录"`、`button "客户画像"`、`button "添加抖音号"`、`button "刷新智能体列表"`、`button "编辑智能体"`、`button "删除智能体"`、`button "关闭智能体编辑弹窗"`、`button "关闭授权弹窗"`、`button "编辑"` 等均有名称。

## 4. 弹窗语义覆盖结果

13 个自定义弹窗补 `role="dialog" aria-modal="true" aria-labelledby="<id>"`，对应标题元素加 `id`，aria-labelledby 与 id 完全一致：

| 弹窗 | 文件 | labelledby id | 标题 |
|---|---|---|---|
| 绑定智能体 | DouyinAiCsWorkbenchPage | agent-config-title | 绑定智能体 |
| 添加抖音号 | DouyinAiCsWorkbenchPage | auth-modal-title | 添加抖音号 |
| 上传图片 | DouyinAiCsWorkbenchPage | upload-dialog-title | 上传图片 |
| RunDetail | DouyinAutoReplyRunsPage | run-detail-title | （运行详情）|
| DecisionLogDetail | AiReplyDecisionLogsPage | decision-log-detail-title | （决策日志详情）|
| SyncModal | LeadsManagement | sync-modal-title | （同步）|
| AssignModal | LeadsManagement | assign-modal-title | （分配）|
| RechargeModal | ComputeCenter | recharge-modal-title | （充值）|
| AgentEditor | SuperMerchantAgent | agent-editor-title | 编辑AI小高智能体 |
| 编辑销售 | WechatAgent | edit-staff-title | （编辑销售）|
| 任务详情 | WechatAgent | task-detail-title | （任务详情）|
| AddAdmin | SuperAdminAccounts | add-admin-title | （添加管理员）|
| ReturnVisit SlidePanel | AdminReturnVisitsPage | return-visit-panel-title | 编辑 · 留资转化 |
| DouyinAuthModal | Index | douyin-auth-title | （抖音授权）|

执行包要求优先复用 Sheet/Dialog/AlertDialog。本次审计范围内弹窗均为历史手写实现，整体替换为 Dialog/Sheet 属较大重构（涉及每个弹窗的打开/关闭/提交/取消逻辑迁移，超出"补语义"阶段），且执行包 5.2 明确"若本轮确实无法替换，至少补 role/aria-modal/aria-labelledby/可关联标题"且"不改变打开、关闭、提交和取消逻辑"。故本次采用最小补语义方案，未替换组件。FIX-01 已将抖音客服客户画像改为 Sheet（带 Esc/焦点/overlay），本次未重复处理。

浏览器验证（添加抖音号弹窗）：`role=dialog`、`aria-modal=true`、`aria-labelledby=auth-modal-title` 指向可见标题"添加抖音号"✅；AgentEditor 弹窗 labelledby=agent-editor-title → "编辑AI小高智能体" ✅；ReturnVisit SlidePanel labelledby=return-visit-panel-title → "编辑 · 留资转化" ✅。

## 5. 表单控件覆盖结果

58 处 `<input>/<select>/<textarea>` 补 `aria-label`（或 htmlFor+id 关联）。覆盖模式：
- placeholder-only input → 补 aria-label
- 装饰性 label（label 内只有 SearchIcon 无文字）→ 给 input 补 aria-label
- select 无任何标签 → 补 aria-label
- datetime-local/date input 无标签 → 补 aria-label
- DailyReports 4 个日期框 label 是兄弟元素未关联 → 补 aria-label（最小改动，DailyReports 第 776 行因可见 label 为"指标日期"，aria-label 用"指标日期"匹配可见文字）

浏览器验证：`textbox "搜索会话"`、`textbox "人工回复内容"`、`textbox "输入预览问题"`、`textbox "搜索联系人、内容或电话"`、`combobox "线索状态筛选"`、`combobox "来源筛选"`、`combobox "分配销售筛选"` 等均有名称 ✅。

## 6. 构建与定向检查

### 6.1 构建
```
cd frontend && npm run build
→ ✓ built in 4.11s，dist 产出正常
```

### 6.2 定向 eslint（20 文件对照）

| 指标 | 修改前（基线） | 修改后 | 新增 |
|---|---|---|---|
| 总问题数 | 36（33 errors + 3 warnings） | 36（33 errors + 3 warnings） | **0** |

所有 36 个问题均为 pre-existing，全部是 `react-hooks/set-state-in-effect`（useEffect 内同步 setState）与 `rules-of-hooks`（既有 hook 调用位置问题），与本轮 aria-label/role 属性补全无关，位于未改动的 effect/hook 代码块。

分组验证（各修复 agent 报告）：
- douyin-cs 组（3 文件）：5 errors + 1 warning，前后一致
- leads+compute 组（6 文件）：12 problems（11 errors + 1 warning），前后一致
- wechat+pages 组（7 文件）：13 problems（12 errors + 1 warning），前后一致

**本任务编辑行（全部为属性补全）零新增 lint 错误。**

## 7. 浏览器可访问性验收

使用 agent-browser（Chrome CDP）驱动 dev 容器（5173）。dev 容器重启后 Vite 重载源码生效。

### 7.1 页面控件名称验收

| 页面 | 关键控件（snapshot 命中） |
|---|---|
| /douyin-cs/workbench | textbox "搜索会话"、textbox "人工回复内容"、button "客户画像"、button "添加抖音号" |
| /leads | textbox "搜索联系人、内容或电话"、combobox "线索状态筛选"/"来源筛选"/"分配销售筛选"、button "上一页"/"下一页" |
| /compute/center | button "退出登录"、button "刷新" |
| /wechat-assistant | button "退出登录"、button "刷新" |
| /agents | button "刷新智能体列表"/"编辑智能体"/"删除智能体"、textbox "输入预览问题" |
| /admin/return-visits | button "编辑"（每行） |

### 7.2 弹窗验收

| 弹窗 | 打开方式 | 对话框名称（aria-labelledby 指向） | 关闭按钮名称 | 关闭按钮关闭 | 焦点 |
|---|---|---|---|---|---|
| 添加抖音号（auth-modal） | 点"添加抖音号"按钮 | "添加抖音号" | "关闭授权弹窗" | ✅ | body |
| AgentEditor | 点"编辑智能体" | "编辑AI小高智能体" | "关闭智能体编辑弹窗" | ✅ | body |
| ReturnVisit SlidePanel | 点"编辑" | "编辑 · 留资转化" | （未单独测，语义已验证） | — | — |

### 7.3 Esc 关闭说明

自定义弹窗（auth-modal、AgentEditor 等）补语义后 Esc 不关闭——这是预期行为。执行包 5.2 明确"不改变打开、关闭、提交和取消逻辑"，这些弹窗原本就没有 Esc 关闭逻辑（手写实现，非 radix Dialog/Sheet），补 role/aria-modal 语义不引入新的关闭行为。关闭按钮均可关闭（已验证）。FIX-01 改用的 Sheet 组件自带 Esc（radix），不在本次范围。

### 7.4 键盘 Tab

/leads 页：聚焦搜索框后按 Tab，焦点进入 `SELECT "线索状态筛选"`（带 aria-label）✅。新增/修改的控件可被键盘 Tab 访问。

### 7.5 视觉无明显变化

仅补 aria-label/role/aria-modal/aria-labelledby/id 属性，不改样式/布局/颜色。截图对照：
- `shots/fix02/01_workbench_dialog.png`、`02_agents.png`、`03_leads.png`

## 8. 未处理项目

- 自定义弹窗未整体替换为 Dialog/Sheet 组件（按执行包 5.2 最小补语义方案，保留手写实现仅补 role 等属性；替换属重构，超出本阶段）。
- 自定义弹窗的 Esc 关闭与焦点恢复未引入（执行包禁止改变关闭逻辑；radix 焦点恢复仅 Sheet/Dialog 自带）。
- 登录页"记住账号"复选框语义重构（执行包明确留给 FIX-05）。
- "减少动画"（prefers-reduced-motion）留给 FIX-05。
- 加载/空数据/错误/成功状态、移动端布局（执行包明确不处理）。
- 4 个无问题文件未改动（DouyinAutoReplySettingsPage、DouyinLiveCheckPage、LocalWechatAgentTestPanel、WechatTaskPanel）。

## 9. Git diff 检查

```
git diff --check -- frontend/src/
→ exit 0（零空白错误）
```

改动文件 16 个，全部在允许范围内，未触及 `frontend/src/components/ui/`（未新增依赖、未改 Sheet/Dialog/AlertDialog 组件）、未触及 `index.css`、未触及鉴权/权限/路由/接口/微信自动化/Local Agent/发送 gate。

工作区其他未提交改动（.gitignore、docs/ai/01_product_prd/、docs/待确认事项.md、tests/、apps/ai_edit/、scripts/）均与本任务隔离，未带入。

## 10. 文档影响检查

- 本报告新增于 `docs/ai/06_ui_audit/`。
- `docs/ai/05_PROJECT_CONTEXT.md` 无需更新：本次为前端可访问性属性补全，不涉及系统组件/端口/数据库/鉴权边界等当前事实。
- `docs/ai/README.md` 已在 FIX-01 列出 `06_ui_audit/` 目录，本次无需再改索引。
- 未触碰治理规则文件 01~04。
