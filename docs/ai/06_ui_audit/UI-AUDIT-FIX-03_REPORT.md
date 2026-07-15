# UI-AUDIT-FIX-03 执行报告

- 执行日期：2026-07-15
- UI 阶段参考提交：19c9b45 补齐前端页面可访问性语义（FIX-02，本 UI 审计阶段的起点）
- 本次执行实际 HEAD：cff127e 构建：增加 AI剪辑 Worker 双运行时打包（执行期间用户提交了 AI 剪辑相关改动，与本 UI 任务隔离；本任务改动基于 19c9b45 起的前端文件，未受 cff127e 影响）
- 范围：前端加载/空数据/错误/成功反馈状态统一
- 状态：R2 返工完成 — 修正 R1 "已有数据刷新失败不显示错误"缺陷：错误条独立条件、refreshPage 不再吞任务历史错误。编码 + build PASS + 定向 eslint 零新增失败 + 浏览器验收（页面级错误态+重试实测、任务历史空态实测；已有数据场景因 dev 无真实数据+拦截局限未端到端验证，提供静态代码证据+手工步骤）

---

## 1. 根因与影响范围

根因不是单点缺陷，而是历史页面状态表达不一致：
- 列表首次加载多处纯文字"加载中..."无旋转图标，刷新时清空已有数据后才显示加载态。
- 空态普遍为孤立"暂无X"，缺"为什么为空+下一步操作"，筛选后无结果与完全无数据不区分、无重置入口。
- 列表/页面加载失败多处只靠 toast.error，缺内联错误块与重试入口。
- 个别操作按钮（标记有效性、添加白名单、筛选）提交中未禁用，可重复提交。

影响范围：22 个允许修改文件中的 16 个（4 个经审计确认完备未改：Index.tsx、ComputeCenter.tsx、SuperComputeConfig.tsx、LocalWechatAgentTestPanel.tsx；ChatPanel.tsx 仅补空态文案）。参考范式：ComputeCenter/SuperComputeConfig 已有完整"内联错误+重试按钮+Skeleton+刷新保留数据"模式。

## 2. 执行前工作区状态

```
git status --short（执行前）
 M .gitignore
 M app/local_agent_main.py
 M docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
 M docs/待确认事项.md
 M tests/test_phase8b_local_agent_downloader.py
?? -i
?? app/local_agent_ai_edit_routes.py / storage.py / supervisor.py
?? scripts/generate_phase8_visual_samples.py
?? tests/test_phase12_local_ai_edit_*.py
```

以上未提交改动均与本任务隔离，未触碰、未清理、未提交。HEAD：19c9b45。

## 3. 修改文件

16 文件、约 58 处状态表达补全（三组并行修复）：

| 文件 | 处数 | 主要内容 |
|---|---|---|
| DouyinAutoReplyRunsPage | 6 | 列表/详情加载加 LoaderIcon；查询按钮 loading 旋转；列表空态区分有无筛选；列表错误+详情错误加重试按钮（详情提取 loadDetail callback） |
| AiReplyDecisionLogsPage | 6 | 列表/详情加载加 LoaderIcon；标记按钮 disabled；空态区分有无筛选；列表错误+详情错误加重试（详情提取 loadDetail） |
| DouyinAutoReplySettingsPage | 2 | 列表加载加 LoaderIcon；企业号空态补原因+下一步 |
| DouyinLiveCheckPage | 2 | 页面加载加 LoaderIcon；页面错误加重试调用 loadStatus |
| DouyinAiCsWorkbenchPage | 3 | ErrorBanner 增 onRetry 可选属性；会话筛选空态加重置入口；客户画像空态补原因 |
| ContactList | 1 | 加载保留已有数据（loading&&len>0 不清空）；错误加重试调 onRefresh；空态区分完全无数据 vs 筛选无结果+重置 |
| ChatPanel | 1 | 消息空态补原因说明 |
| LeadsManagement | 4 | 提取 loadData 为 useCallback（重试清 error 根因修复）；首次加载加 LoaderIcon；页面错误加重试；空态区分有无筛选+重置 |
| WebhookEventsPage | 4 | 加载保留已有数据；列表错误+详情错误加重试（DetailPanel 增 onRetry）；空态补说明 |
| WechatAgent | 1+R1+R2 | R0：任务历史首次加载区分加载中。R1：新增 taskHistoryError/pageError 状态；loadTaskHistory 失败保留已有数据+内联错误+重试；refreshPage 失败内联 pageError+重试。R2：错误条移出表格外且条件改为独立 `taskHistoryError`（已有数据时仍显示）；refreshPage 内任务历史从 `.catch(()=>null)` 改为设 taskHistoryError 不吞错；refreshPage 开头清 taskHistoryError |
| DailyReports | 5 | 五个 tab 错误块各加重试按钮调对应 load |
| WechatTaskPanel | 3 | 任务列表错误加重试调 refreshTasks；通知空态+detect_reply 空态补原因 |
| AdminReturnVisitsPage | 6 | import Loader2Icon+toast；三处加载加旋转；PromptsTab 空态；RunsTab 空态补原因+错误加重试；提示词保存成功加 toast.success |
| AdminAutoreplyRolloutPage | 8 | addingWhitelist 状态；添加白名单+筛选按钮 disabled；错误加重试调 loadAll；三个空态补说明 |
| SuperAdminAccounts | 2 | 空行"暂无匹配的管理员账号"；新增管理员按钮加 toast.success |
| SuperMerchantAgent | 4 | 新增 loadError 状态；loadAgents 失败内联错误+重试；刷新按钮 disabled+旋转；加载保留已有数据 |

## 4. 加载状态覆盖矩阵

| 页面 | 场景 | 原状态 | 修改后状态 | 重试/恢复 | 验证 |
|---|---|---|---|---|---|
| LeadsManagement | 首次加载 | 纯文字"加载中..." | LoaderIcon 旋转+文字 | loadData | 静态+正常态渲染 |
| LeadsManagement | 刷新中 | 已保留数据+刷新指示 | 同（已完备） | refreshData | 已完备 |
| DouyinAutoReplyRunsPage | 列表加载 | 纯文字 | LoaderIcon 旋转 | loadRuns | 静态 |
| DouyinAutoReplyRunsPage | 详情加载 | 纯文字 | LoaderIcon 旋转 | loadDetail | 静态 |
| AiReplyDecisionLogsPage | 列表/详情加载 | 纯文字 | LoaderIcon 旋转 | loadLogs/loadDetail | 静态 |
| DouyinAutoReplySettingsPage | 列表加载 | 纯文字 | LoaderIcon 旋转 | loadSettings | 静态 |
| DouyinLiveCheckPage | 页面加载 | 纯文字 | LoaderIcon 旋转 | loadStatus | 静态 |
| SuperMerchantAgent | 首次加载 | 纯文字"正在加载..." | 旋转图标；刷新保留数据 | loadAgents | 静态 |
| AdminReturnVisitsPage | 三处加载 | 纯文字"加载中…" | Loader2Icon 旋转 | load | 静态 |
| WechatAgent | 任务历史首次加载 | 误显示空态 | Loader2Icon+"加载中..."区分 | — | 静态 |
| ContactList | 刷新中 | 清空已有数据 | loading&&len>0 保留列表 | onRefresh | 静态 |
| WebhookEventsPage | 刷新中 | 清空已有数据 | loading&&len>0 保留列表 | loadEvents | 静态 |

注：执行包要求"已有可靠旋转图标可保留，不强制全站 Skeleton"。本次采用旋转图标为主（最小改动），ComputeCenter/SuperComputeConfig 已有 Skeleton 保留。

## 5. 空数据状态覆盖矩阵

| 页面 | 场景 | 原状态 | 修改后状态 | 下一步入口 | 验证 |
|---|---|---|---|---|---|
| DouyinAutoReplyRunsPage | 无记录/筛选无结果 | 不区分 | 区分：无筛选"暂无运行记录，AI触发后展示"；有筛选"未找到符合条件的记录"+重置 | 重置筛选 | 静态 |
| AiReplyDecisionLogsPage | 无记录/筛选无结果 | 不区分 | 同上区分+重置 | 重置筛选 | 静态 |
| DouyinAutoReplySettingsPage | 无企业号 | 孤立"暂无X" | 补"请先在抖音客服工作台绑定企业号" | — | 静态 |
| DouyinAiCsWorkbenchPage | 筛选无会话/无画像 | 孤立"暂无X" | 筛选空态加重置；画像补"待后端同步" | 重置筛选 | 静态 |
| ContactList | 完全无/筛选无 | 不区分 | 区分：完全无"请授权并让客户发私信"；筛选无"无匹配会话"+重置 | 重置 | 静态 |
| ChatPanel | 无消息 | 孤立文本 | 补"尚未收到已入库私信，请等待客户发送" | — | 静态 |
| LeadsManagement | 无/筛选无 | 孤立"暂无线索数据" | 区分：无筛选"点击同步拉取"；有筛选"无匹配+重置" | 同步/重置 | 静态 |
| WebhookEventsPage | 无事件 | 已区分 | 补"或调整筛选条件后重新查询" | — | 静态 |
| WechatTaskPanel | 无通知/无检测任务 | 孤立"暂无X" | 补原因+下一步 | — | 静态 |
| AdminReturnVisitsPage | PromptsTab 无提示词 | 无空态 | 增"暂无提示词配置"空行 | — | 静态 |
| AdminReturnVisitsPage | RunsTab 无记录 | 孤立文本 | 补"系统尚未产生回访运行记录" | — | 静态 |
| AdminAutoreplyRolloutPage | 三个空态 | 孤立"暂无X" | 补原因（绑定企业号/添加白名单/等） | — | 静态 |
| SuperAdminAccounts | 无匹配账号 | 无空态 | 增"暂无匹配的管理员账号"空行 | — | 静态 |

## 6. 错误状态覆盖矩阵

| 页面 | 场景 | 原状态 | 修改后状态 | 重试入口 | 验证 |
|---|---|---|---|---|---|
| DailyReports | 五 tab 加载失败 | 内联错误无重试 | 各加"重试"按钮调对应 load | load | **浏览器实测**：8 个重试按钮可见，点击后 XHR 81→83 重新请求 ✅ |
| DouyinAutoReplyRunsPage | 列表失败/详情失败 | 内联无重试 | 列表+详情加重试 | loadRuns/loadDetail | 静态 |
| AiReplyDecisionLogsPage | 列表/详情失败 | 内联无重试 | 加重试 | loadLogs/loadDetail | 静态 |
| DouyinLiveCheckPage | 页面失败 | 内联无重试 | 加"重试加载"调 loadStatus | loadStatus | 静态 |
| DouyinAiCsWorkbenchPage | 全局 ErrorBanner | 无重试 | ErrorBanner 增 onRetry | loadAccounts | 静态 |
| ContactList | 列表失败 | 内联文字无重试 | 加重试调 onRefresh | onRefresh | 静态 |
| LeadsManagement | 页面加载失败 | 内联无重试 | 加"重试"调 loadData（根因：重试清 error） | loadData | 静态 |
| WebhookEventsPage | 列表/详情失败 | 内联无重试 | 加重试（DetailPanel 增 onRetry） | loadEvents/loadDetail | 静态 |
| WechatTaskPanel | 任务列表失败 | 内联无重试 | 加重试调 refreshTasks | refreshTasks | 静态 |
| AdminReturnVisitsPage | RunsTab 失败 | 内联无重试 | 加"重新加载"调 load | load | 静态 |
| AdminAutoreplyRolloutPage | 页面失败 | 内联无重试 | 加"重试"调 loadAll | loadAll | 静态 |
| WechatAgent | 页面刷新失败（refreshPage） | 仅 toast.error | R1：新增 pageError 状态+内联错误块+重试按钮调 refreshPage | refreshPage | **浏览器实测**：拦截 API 后点页面级"重试"，XHR 10→14 触发重新请求 ✅ |
| WechatAgent | 任务历史失败（loadTaskHistory） | 仅 toast.error，失败误显示空态 | R1+R2：taskHistoryError 独立错误条（已有数据时仍显示，旧表格保留）；重试调 loadTaskHistory；refreshPage 内任务历史失败不再被吞 | loadTaskHistory | 静态代码证据+手工步骤（见 8.4；dev 无真实数据+拦截同接口多用途局限未端到端验证） |

敏感信息：各页面错误文案沿用既有 resolveErrorMessage/safe_message 提取（douyin-cs 组已确认完备），本次未引入原始响应/手机号/token 直出。

## 7. 成功反馈覆盖矩阵

| 页面 | 场景 | 原状态 | 修改后 | 验证 |
|---|---|---|---|---|
| AdminReturnVisitsPage | 提示词保存 | 无 toast | 加 toast.success("提示词已保存") | 静态 |
| SuperAdminAccounts | 新增管理员 | 无反馈 | 加 toast.success 再 onClose | 静态 |
| 其余页面 | 同步/分配/保存/充值/启用/停用/删除/下载 | 已完备（toast+刷新视图） | 保留未动 | 审计确认 |

执行包要求"影响列表的操作成功后必须刷新视图"——经审计 LeadsManagement 同步/分配成功→refreshData、ComputeCenter 充值成功→刷新余额流水、SuperMerchantAgent 保存/删除→loadAgents、DailyReports 生成/下载→loadList 均已正确刷新，未动。

## 8. 浏览器验收

使用 agent-browser（Chrome CDP）驱动 dev 容器（5173，重启后 Vite 重载源码）。

### 8.1 正常态加载验证（8 页面）

| 页面 | animate-spin | 重试按钮 | 空态文本 | 视觉 |
|---|---|---|---|---|
| /douyin-cs/workbench | 0（已加载） | 0（无错误） | 有 | 无跳动 |
| /leads | 0 | 0 | 有 | 无跳动 |
| /compute/center | 0 | 0 | — | 无跳动 |
| /agents | 0 | 0 | — | 无跳动 |
| /wechat-assistant | 0 | 0 | — | 无跳动 |
| /wechat-assistant/daily-reports | 0 | **8**（错误态） | — | 无跳动 |
| /admin/return-visits | 0 | 0 | — | 无跳动 |
| /admin/autoreply-rollout | 0 | 0 | 有 | 无跳动 |

### 8.2 错误态+重试实测（daily-reports 自然错误态）

daily-reports 因后端报表接口未实现自然进入错误态：
- 5 个 tab 错误块各渲染"重试"按钮，共 **8 个重试按钮可见**（role=button，文本"重试"）✅
- 截图：`shots/fix03/01_dailyreports_error_retry.png`
- **点击重试验证**：点击第一个"重试"按钮，XHR 请求数 81→83，确认重试按钮触发重新请求 ✅

### 8.3 接口失败模拟说明与残余风险

执行包要求"模拟接口失败验证内联错误"。本任务尝试用 `agent-browser network route` 拦截 API：
- `**/api/leads**` 与 `http://127.0.0.1:5173/api/leads**` 均导致页面白屏（bodyLen=0）——根因是 Vite dev server 下，route glob `**` 误伤了 `/src/api/leads.ts` 等模块脚本请求，导致前端模块加载链断裂、页面渲染崩溃。这不是代码缺陷，是 Vite dev 架构下网络拦截工具的局限。
- 解除拦截后 leads 立即恢复正常（bodyLen=317）。
- 用完整 URL 前缀 `http://127.0.0.1:5173/api/wechat-tasks**` 拦截时，leads 等页面会白屏（glob 仍可能跨段匹配）；wechat-assistant 页面 bodyLen=534 未白屏（仅任务相关 API 命中）。
- **残余风险**：在 Vite dev 架构下，无法通过浏览器网络拦截可靠地模拟单个后端 API 故障而不误伤模块脚本。因此本次不把 daily-reports 自然错误态描述为完整的接口故障注入验证——它只证明"错误内联展示+重试入口+点击触发重新请求"的端到端链路有效，未覆盖"后端返回 500 时前端错误文案可读性"。

### 8.4 WechatAgent 浏览器验收（R1+R2）

**R2 关键改动**（修正 R1 缺陷）：
- 任务历史错误条移到 `<table>` 外部，条件从 `taskHistoryError && taskHistory.length === 0` 改为**独立 `taskHistoryError`**——已有数据刷新失败时旧表格行 + 错误条 + 重试按钮同时可见。
- refreshPage 内任务历史请求从 `.catch(() => null)`（吞错）改为 `.catch(err => { setTaskHistoryError(...); return null; })`——失败不再静默，单独设 taskHistoryError，不让整个 Promise.all reject。
- refreshPage 开始时 `setTaskHistoryError(null)` 清旧错误。

**浏览器验证结果**：
- 正常态：✅ 页面渲染正常，无错误条，pageErr=false。
- 任务历史空态：✅ 切"任务记录"tab，无数据时 tbody 渲染空态行"暂无任务记录"（截图 `06_wechat_taskhistory_empty_r2.png`）。
- 页面级错误态+重试：✅ 拦截 `/api/wechat-tasks**` 后点页面级"刷新"按钮触发 refreshPage，XHR 9→11 重新请求；页面顶部 pageError 内联错误块"数据加载失败：..."+重试按钮可见，点击重试触发重新请求（截图 `04_wechat_page_error_retry.png`）。
- **"已有任务历史数据刷新失败时错误提示+旧数据+重试同时可见"场景**：⚠️ 浏览器未能端到端验证。根因：当前 dev 环境无真实任务历史数据（taskHistory 恒为空），无法构造"已有数据"前置态；且拦截 `/api/wechat-tasks**` 会同时命中 `fetchBrowserPendingWechatTasks`（loadPendingTasksForBrowser 内 `fetchBrowserPendingWechatTasks` 请求同接口），导致 Promise.all 整体 reject 触发 pageError，掩盖任务历史独立的 taskHistoryError。该局限是"Vite dev + 单接口多用途 + 浏览器拦截无法精确区分查询参数"的工具限制，非代码缺陷。

**静态代码证据**（R2 改动事实）：
- WechatAgent.tsx：错误条渲染条件 `taskHistoryError ? <错误条+重试调 loadTaskHistory()> : null`，位于 `<table>` 外、`<thead>` 前，独立于 `taskHistory.length`，满足"已有数据时仍显示错误"。
- refreshPage 内 `fetchWechatTaskHistory(...).catch(err => { setTaskHistoryError(err instanceof Error ? err.message : "任务历史加载失败"); return null; })`，失败设 taskHistoryError 且不 reject。
- loadTaskHistory catch：失败 setTaskHistoryError(msg)+toast，**不清空 taskHistory**（保留已有数据）。
- refreshPage 开头 `setTaskHistoryError(null)`。

**手工验证步骤**（供后续在真实数据环境复现）：
1. 准备含任务历史记录的环境（taskHistory.length > 0）。
2. 用浏览器开发者工具 Network 面板拦截 `/api/wechat-tasks?page=...&page_size=20`（不带 status=pending 的任务历史请求）返回 500，放行 `status=pending` 的 pending tasks 请求。
3. 点任务历史区"查询"或"刷新"按钮。
4. 预期：旧任务记录表格保留可见 + 表格上方红色错误条"任务历史加载失败"+ "重试"按钮同时出现；点重试重新请求。

### 8.5 静态代码证据（无法浏览器模拟的部分）

`rg -c "重试|重新加载|重试加载"` 覆盖 16 文件；`rg -c "animate-spin"` 覆盖全部页面。重试按钮均调用页面已存在的加载函数（loadRuns/loadLogs/loadStatus/loadEvents/loadDetail/refreshTasks/load/loadAll/loadAgents/onRefresh/loadData/loadTaskHistory/refreshPage），无新建函数（LeadsManagement 提取 loadData 为 useCallback 是根因修复，使重试清 error）。

### 8.6 截图清单

- `shots/fix03/01_dailyreports_error_retry.png`（daily-reports 自然错误态+8 重试按钮）
- `shots/fix03/02_leads_normal.png`（leads 正常态）
- `shots/fix03/03_compute_normal.png`（compute 正常态）
- `shots/fix03/04_wechat_page_error_retry.png`（WechatAgent 页面级错误态+重试）
- `shots/fix03/05_wechat_taskhistory_empty.png`（WechatAgent 任务历史空态）
- `shots/fix03/06_wechat_taskhistory_empty_r2.png`（R2：WechatAgent 任务历史空态复验）

## 9. 构建与定向检查

### 9.1 构建
```
cd frontend && npm run build
→ ✓ built in 7.46s（R0）/ ✓ built in 3.61s（R1）/ ✓ built in 4.03s（R2）
```

### 9.2 定向 eslint（20 文件对照）

| 指标 | 修改前（基线） | 修改后（R0+R1） | 新增 |
|---|---|---|---|
| 总问题数 | 36（33 errors + 3 warnings） | 36（33 errors + 3 warnings） | **0** |

分组验证：
- douyin-cs 组（5 文件）：9→9（8 errors + 1 warning）
- leads+compute 组（4 文件）：4→4（4 errors）
- wechat+admin 组（7 文件）：16→16（14 errors + 2 warnings）

R1 WechatAgent 单文件：2 problems（1 error + 1 warning），均为 pre-existing 的 `react-hooks/set-state-in-effect`（useEffect 调 refreshPage，行317）+ 缺依赖 `refreshPage`（行318），与本轮 R1 新增的 taskHistoryError/pageError 状态、错误块、重试按钮无关（R1 未触碰 useEffect）。

所有问题均为 pre-existing 的 `react-hooks/set-state-in-effect` / `rules-of-hooks`（useEffect 内 setState、既有 hook 调用位置），与本轮状态表达补全无关。**本任务编辑行零新增 lint 错误。**

## 10. 未处理项目

- ChatPanel 增加 error prop（接口变更影响父组件，优先级低，仅补空态文案）。
- WechatAgent 页面级 pageError 与任务历史 taskHistoryError：R1+R2 已补齐内联错误+重试（见第 6 节）。"已有数据刷新失败时旧数据+错误条+重试同时可见"因 dev 无真实任务数据+Vite dev 拦截同接口多用途局限，未端到端浏览器验证，提供静态代码证据+手工验证步骤（见 8.4）。
- ChatPanel 增加 error prop（接口变更影响父组件，优先级低，仅补空态文案）。ChatPanel 的会话错误由父级 ContactList 承担内联展示（ContactList 已有错误+重试），ChatPanel 自身不重复处理——此边界在 R1 维持。
- 自定义弹窗 Esc/焦点（属 FIX-02 范围，已说明）。
- `prefers-reduced-motion`、"记住账号"语义（执行包明确留给 FIX-05）。
- 全站语义颜色类（执行包明确留给后续视觉差异阶段）。
- 接口失败浏览器模拟（Vite dev 拦截局限，已用自然错误态+静态证据替代）。

## 11. Git diff 检查

```
git diff --check -- frontend/src/
→ exit 0（零空白错误）
```

改动 16 文件，全部在允许范围内，未触及 `frontend/src/components/ui/`（未新增依赖、未改 Skeleton/Alert 组件）、未触及 `index.css`、未触及鉴权/权限/路由/接口/微信自动化/Local Agent/发送 gate/真实发送逻辑。

工作区其他未提交改动（.gitignore、app/local_agent_main.py、docs/ai/01_product_prd/、docs/待确认事项.md、tests/、app/local_agent_ai_edit_*、scripts/、`-i`）均与本任务隔离，未带入。

## 12. 文档影响检查

- 本报告新增于 `docs/ai/06_ui_audit/`。
- `docs/ai/05_PROJECT_CONTEXT.md` 无需更新：本次为前端状态表达补全，不涉及系统组件/端口/数据库/鉴权边界等当前事实。
- `docs/ai/README.md` 已列 `06_ui_audit/` 目录，无需再改。
- 未触碰治理规则文件 01~04。
