# 05_PROJECT_CONTEXT.md

> 本文档是 AI Coding Agent 的项目上下文。
>
> 优先级低于阅读规范，高于执行规范、测试规范和输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 1. 项目名称

主机微信线索分发与销售跟进检测系统

## 2. 项目阶段

**P5 React UI Integration（进行中）**

已完成阶段：P0 → P1 → P2 → P2.5 → P3 → P4

当前聚焦：P5-4 检测记录展示已完成，局域网访问已配置

## 3. 项目目标

通过主机微信（B）实现抖音线索的接收、分发、销售跟进检测、结果反馈的完整闭环。

------

## 4. 系统整体架构

当前系统由三个独立项目组成：

```text
抖音平台
    ↓ Webhook
douyinAPI（上游数据源，端口 8081）
    ↓ HTTP API
auto_wechat（中间业务执行层，端口 9000）
    ↓ UI Automation
主机微信 B
    ↓ 微信消息
销售微信 C
    ↓ 回复检测
主机微信 B → 反馈给 douyinAPI
    ↓
React UI（客户运营后台，端口 5173）
```

三系统定位：

| 系统 | 定位 | 路径 | 当前状态 |
|------|------|------|----------|
| douyinAPI | 上游数据源 | `E:\work\project\douyinAPI` | 已部署，接收抖音私信 |
| auto_wechat | 中间业务执行层 | `E:\work\project\auto_wechat` | P4 完成，P5 进行中 |
| React UI | 客户运营后台 | `E:\work\project\react` | LeadsManagement 已接入真实 API，其余页面仍为 Mock |

------

## 5. douyinAPI 探索结论

项目路径：`E:\work\project\douyinAPI`

项目定位：抖音私信线索接收系统。

核心能力：

- `POST /webhook/douyin` — 接收抖音 Webhook
- `leads` — 线索管理
- `conversations` — 会话管理
- `messages` — 消息管理

数据库：SQLite

关键表：

- `lead_contacts` — 线索联系人
- `conversations` — 会话记录
- `messages` — 消息记录

已确认：auto_wechat 的上游数据源就是 douyinAPI。

------

## 6. React UI 探索结论

项目路径：`E:\work\project\react`

项目定位：小高AI系统运营后台前端。

技术栈：

- React 19
- TypeScript
- Vite
- Tailwind
- shadcn/ui

### P5 集成进展（2026-06-09 更新）

API 基础层已完成：

| 文件 | 说明 |
|------|------|
| `src/api/client.ts` | axios 实例，baseURL 从 `VITE_AUTO_WECHAT_API_BASE_URL` 读取 |
| `src/api/types.ts` | TypeScript 类型定义（Lead, Staff, ReportSummary, DouyinSyncResponse 等） |
| `src/api/leads.ts` | `fetchLeads()`, `fetchLead(id)` |
| `src/api/staff.ts` | `fetchStaffList()` |
| `src/api/reports.ts` | `fetchSummary()` |
| `src/api/integrations.ts` | `syncDouyinLeads({ dryRun, autoAssign })` |

环境变量：

| 文件 | 内容 |
|------|------|
| `.env.development` | `VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000` |

LeadsManagement 页面状态：

- ✅ 线索列表：从 `GET /leads` 拉取真实数据
- ✅ 统计卡片：从 `GET /reports/summary` 拉取真实数据
- ✅ 销售下拉：从 `GET /staff?status=active` 拉取真实数据
- ✅ 同步按钮：`POST /integrations/douyin/sync-leads`（dry_run 预览 → 二次确认 → 写库）
- ✅ 线索详情面板：只读展示（重新分配、对话跟进按钮暂 disabled）
- ⬜ 其余页面仍为 Mock 数据

结论：

- LeadsManagement 页面已完成真实 API 接入，不再使用 Mock 数据
- API 层架构稳定，后续页面可复用
- 未来逐步将其余页面接入真实 API

------

## 6.1 React UI Known Issues

### TypeScript 5.9 配置约束

详见 CLAUDE.md。

历史问题：

- 2026-06-09
- 多次出现 baseUrl 弃用提示
- 多次出现 composite 缺失提示
- 已确认最终稳定配置

验证结论（2026-06-09）：

- VSCode 提示 `ignoreDeprecations: "6.0"` 可消除 baseUrl 弃用警告
- 但项目 TypeScript 5.9.3 不支持 `"6.0"`，使用会导致 TS5103 构建失败
- 正确值：`ignoreDeprecations: "5.0"`，构建通过
- VSCode 中的弃用提示是语言服务版本差异导致，不影响构建
- 升级 TS 7.x 时需重新评估路径别名方案

后续开发禁止修改 TS 配置结构。

------

## 7. 系统角色

### 7.1 数据源微信 A

| 属性 | 说明 |
|------|------|
| 职责 | 抖音线索入口；向主机微信发送线索；接收跟进结果反馈 |
| 当前状态 | 未接入数据库；未结构化；暂时通过微信消息传递 |
| 未来规划 | 数据结构化；标准消息模板 |

### 7.2 主机微信 B（系统运行主体）

| 属性 | 说明 |
|------|------|
| 职责 | 线索入库；销售分配；跟进检测；状态回传给数据源微信 A |
| 当前 MVP 已实现 | 数据库闭环；微信 UI 检测；兜底检测；`expected_reply_text`；`risk_level`；P2.5 实验结论 |
| P3 已实现 | 自动向数据源微信 A 反馈检测结果 |

### 7.3 销售微信 C

| 属性 | 说明 |
|------|------|
| 职责 | 接收线索通知；添加客户微信；向主机微信 B 回复确认 |
| 有效回复示例 | `收到` / `已添加微信` / `收到，已添加微信` |

------

## 8. 核心业务流程

```text
抖音线索产生
    ↓
douyinAPI 接收并存储线索
    ↓
auto_wechat 从 douyinAPI 拉取线索（P4 已完成）
    ↓
auto_wechat 线索入库 + 自动分配（P4 已完成）
    ↓
主机微信 B 通知销售 C
    ↓
销售人员 C 在指定时间内给主机微信 B 回复确认消息
    ↓
主机微信 B 通过 UI 自动化检测销售是否跟进
    · 读取当前聊天窗口消息
    · 识别发送方
    · 匹配有效确认关键词
    · 判断是否超时
    ↓
检测结果入库
    ↓
主机微信 B 向数据源微信 A 反馈检测结果
```

------

## 9. 项目定位

本项目是一个**独立项目**，运行于 `E:\work\project\auto_wechat`。

**不依赖**以下任何外部系统或模块：

- 小猫AI员工
- `core/*.pyd`
- `wxauto.pyd`
- 企业微信 DLL 注入
- MCP 工具接口

------

## 10. 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| FastAPI + Uvicorn | Web 框架，端口 9000 |
| SQLAlchemy 2.x | ORM |
| SQLite | 本地数据库 `data/auto_wechat.db` |
| Pydantic 2.x | 数据校验 |
| uiautomation | 微信 PC 窗口 UI 控件读取 |
| threading | 定时任务调度（轻量后台线程） |
| React 19 + TypeScript + Vite | 前端框架，端口 5173 |
| axios | 前端 HTTP 客户端 |

------

## 11. MVP 范围

### 11.1 已完成 ✓

- 线索入库
- 销售分配（手动 + 自动轮询）
- 回复检测（手动录入 + 微信 UI 自动检测）
- 超时检测（定时扫描 + 手动触发）
- 微信 UI 当前窗口检测（多策略定位 + 消息读取 + 发送方识别）
- 期望回复文本配置（`expected_reply_text`，支持 `|` 分隔多值，优先精确/包含匹配）
- 兜底模式严格匹配（`strict_mode`，必须命中关键词或期望回复文本）
- 检测结果人工复核标记（`confirmed_required`，兜底模式时为 true）
- 检测结果警告信息（`warning`，兜底模式时提示需人工确认）
- 聊天窗口人工确认（`confirm_current_chat`，降低误操作风险）
- 检测结果可信度（`risk_level`，low / medium / high / none）
- 汇总报表（全局统计 + 分销售统计）
- 调试诊断脚本（窗口探测 + 消息控件结构分析）
- P2.5 发送方精确识别实验（UIA 深层探测 + 截图像素分析 + 实验报告）
- 调试接口：`GET /replies/debug/raw-tree`、`POST /replies/debug/sender-experiment`
- P3 反馈发送：根据 replied 线索生成反馈文本 → 写入微信输入框 → 记录入库可追溯
- P3 反馈模板：`feedback_template` 可配置，支持变量替换
- P3 安全机制：`require_confirm`（只粘贴不回车）、`confirm_chat_title`（防误发）
- P4-1 douyinAPI 线索同步基础设施：HTTP 客户端、字段映射、dry_run 预览
- P4-2 douyinAPI 线索同步入库：create/update/skip 写库
- P4-3 同步后自动分配联动：auto_assign=true 对新建线索自动分配，异常不回滚整批
- P4-4 定时同步调度器：check_scheduler.py 后台守护线程定时检测超时
- P4-5 端到端验证：douyinAPI → auto_wechat → 入库 → 分配 → 检测 完整链路验证
- P5-2A auto_wechat CORS 配置：允许 React 开发服务器（5173）跨域访问
- P5-2B React API 基础层：axios 客户端 + TypeScript 类型定义 + 5 个 API 模块
- P5-2C LeadsManagement 只读接入：线索列表 + 销售下拉 + 统计卡片 均从真实 API 拉取
- P5-2D 同步按钮：dry_run 预览 → 二次确认 → 写库 → 刷新（详见下方 P5 章节）
- 端到端自动化测试（66 个用例）

### 11.2 未完成 □

- 数据源微信 A 自动发送线索给主机微信 B
- 数据源微信 A 自动接收反馈
- 线索结构化解析（从微信消息文本中提取线索字段）
- 主机微信自动切换会话（从销售 C 切换到销售 D）
- 销售聊天窗口自动定位（自动找到对应销售的聊天窗口）
- 发送方精确识别（P2.5 结论：当前微信版本 UIA 不可行，保持兜底模式，截图/OCR 作为后续预研方向）
- P5-3 线索分配 UI 集成（Lead Assignment）
- P5-4 报表看板（Report Dashboard）
- P5-5 检测记录（Check Records）
- P5-6 线索详情增强（Lead Detail Enhancement）
- P5-7 对话跟进集成（Chat Integration）

------

## 12. 项目阶段定义

### P0-P3：已完成

- P0：项目初始化、数据库设计
- P1：线索入库、销售分配、回复检测
- P2：微信 UI 自动化检测
- P3：反馈发送（主机微信 B → 数据源 A）

### P4：douyinAPI 上游线索同步（已完成）

#### P4-1 同步基础设施

- `app/integrations/douyin_api_client.py` — HTTP 客户端
- `app/services/douyin_sync_service.py` — 同步服务
- `app/routers/integrations.py` — API 路由
- `POST /integrations/douyin/sync-leads` — dry_run=true 预览
- 字段映射：open_id → source_id, display_name → customer_name 等

#### P4-2 线索入库

- dry_run=false 时执行写库
- create：本地不存在 → 新建 DouyinLead（status=pending）
- update：本地存在且 pending → 更新 customer_name/content/customer_contact/lead_type/raw_data
- skip：本地存在且非 pending → 跳过，不覆盖

#### P4-3 自动分配联动

- auto_assign=true 时，仅对本次 create 的新线索调用 assign_service.auto_assign_next()
- update/skip 不触发自动分配
- 无活跃销售时线索保持 pending，reason 标记 no_active_staff
- 分配异常不回滚整批同步

#### P4-4 定时检测调度器

- `app/scheduler/check_scheduler.py` — 后台守护线程
- 定期扫描 pending 状态的 reply_checks，将超时未回复的标记为 timeout
- 检测间隔从数据库 `check_configs` 读取（默认 5 分钟）
- 应用启动时自动启动，关闭时自动停止

#### P4-5 端到端验证

- douyinAPI → auto_wechat 拉取 → 入库 → 自动分配 → reply_check 创建 → 完整链路验证通过
- 66 个自动化测试全部通过

### P5：React UI 接入真实 API（进行中）

目标：

逐步替换 React UI 中的 Mock 数据，接入 auto_wechat 真实接口。

接入方向：

- auto_wechat：线索管理、销售管理、检测记录、报表统计
- douyinAPI：线索详情、会话消息（通过 auto_wechat 代理）

#### P5-2A CORS 配置 ✅

- `app/main.py`：CORSMiddleware 配置
- 允许 `http://127.0.0.1:5173` 和 `http://localhost:5173` 跨域访问
- 允许方法：GET, POST, PUT, DELETE, OPTIONS

#### P5-2B React API 基础层 ✅

- `react/src/api/client.ts`：axios 实例，baseURL 从 `VITE_AUTO_WECHAT_API_BASE_URL` 读取
- `react/src/api/types.ts`：TypeScript 类型定义（Lead, Staff, ReportSummary, DouyinSyncResponse 等）
- `react/src/api/leads.ts`：线索 API
- `react/src/api/staff.ts`：销售 API
- `react/src/api/reports.ts`：报表 API
- `react/src/api/integrations.ts`：同步 API
- `react/.env.development`：`VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000`

#### P5-2C LeadsManagement 只读接入 ✅

- 线索列表：`fetchLeads()` → `GET /leads`，渲染为表格
- 统计卡片：`fetchSummary()` → `GET /reports/summary`，渲染累计线索/已分配/已回复/已超时
- 销售下拉：`fetchStaffList("active")` → `GET /staff?status=active`，用于显示分配销售名称
- 线索详情面板：只读展示客户信息、状态、线索内容等
- 前端筛选：关键词搜索 + 状态筛选 + 分页（前端过滤，非服务端）

#### P5-2D 同步按钮 ✅

LeadsManagement 新增「同步 douyinAPI 测试环境线索」按钮：

流程：

1. 点击按钮 → `syncDouyinLeads({ dryRun: true, autoAssign: false })` 预览
2. 弹窗展示 fetched / mapped / created / updated / skipped / assigned 统计
3. 展示前 5 条线索预览（客户名、source_id、action、reason）
4. 用户点击「确认同步（写入数据库）」
5. `syncDouyinLeads({ dryRun: false, autoAssign: false })` 实际写库
6. 成功后刷新线索列表、销售列表、统计数据

安全限制：

- 不直接调用 douyinAPI（通过 auto_wechat 的 integrations 路由代理）
- 不默认写库（默认 dry_run=true 预览）
- 不自动分配（autoAssign=false）
- dry_run=false 必须二次确认

#### P5-3 Lead Assignment UI Integration（下一步）

目标：把 LeadsManagement 中 disabled 的「重新分配」功能接入 `POST /leads/{id}/assign`

预计内容：

1. 使用已有 active staff 列表（`fetchStaffList("active")`）
2. 打开分配弹窗，选择销售
3. 调用 `POST /leads/{id}/assign` 分配线索
4. 成功后刷新线索列表和统计
5. 失败时 toast/error 提示

#### P5-4~P5-7 待规划

- P5-4：Report Dashboard（报表看板）
- P5-5：Check Records（检测记录）
- P5-6：Lead Detail Enhancement（线索详情增强）
- P5-7：Chat Integration（对话跟进集成）

------

## 13. 已验证能力

以下能力已在代码中实现并通过测试验证：

| # | 能力 | 验证方式 |
|---|------|----------|
| 1 | douyinAPI → auto_wechat 线索拉取 | HTTP 客户端 + dry_run 预览 |
| 2 | 线索自动去重（source_id 唯一） | create/update/skip 逻辑 |
| 3 | 新建线索自动分配 | auto_assign_next() 联动 |
| 4 | reply_check 自动创建 | assign_lead() 内部创建 |
| 5 | 反馈模块（主机 B → 数据源 A） | feedback_service + input_writer |
| 6 | 微信 UI 检测（兜底模式） | wechat_ui_reply_service |
| 7 | 定时超时检测 | check_scheduler 后台线程 |
| 8 | React 真实数据展示 | LeadsManagement 页面接入 /leads, /staff, /reports/summary |
| 9 | React 同步按钮 | dry_run 预览 → 二次确认 → 写库 → 刷新 |

------

## 14. 当前技术状态

### 14.1 微信发送方识别

**状态**：P2.5 实验已完成，结论已写入

**当前正式方案**：`fallback_current_window_text`（兜底模式）

- 检测当前聊天窗口中是否存在有效回复文本（如"收到，已添加微信"）
- `strict_mode=True`：必须命中 `expected_reply_text` 或 `effective_keywords`，不允许仅靠长度判定
- 配合 `risk_level` / `confirmed_required` / `confirm_current_chat` 标记可信度

**当前返回**：

```text
detection_mode    = fallback_current_window_text
confirmed_required = true
warning           ≠ null
risk_level        = medium / high
```

**当前结论**：

- ✅ 系统能够识别：当前聊天窗口是否存在有效回复文本
- ❌ 系统暂不能可靠识别：该文本是否由销售 C 发送（UIA 控件树不可行）

### 14.2 发送方精确识别专项实验（P2.5）—— 已完成

**目标**：稳定区分 `friend`（销售）和 `self`（主机）

**实验方法与结论**：

| 方向 | 结论 | 说明 |
|------|------|------|
| 1. UIA 深层控件树 | ❌ 不可行 | `GetChildren()` 返回 0 子控件；`WalkControl()` / `FindAll()` 均无子孙 |
| 2. ControlFromPoint | ❌ 不可行 | 左/中/右三点点采样均命中 ListItemControl 自身，未命中更深层控件 |
| 3. 截图 + 像素分析 | ⚠️ 待验证 | 理论可行（绿色靠右=主机，白色靠左=销售），但依赖微信渲染一致性 |
| 4. 气泡颜色识别 | ⚠️ 同上 | 截图方案的子方向，需 numpy 依赖 |
| 5. OCR 辅助识别 | ⚠️ 预研方向 | 作为后续视觉识别方案，不进入当前主线 |

**关键发现**：

- 当前微信版本消息 `ListItemControl` 为**扁平结构**：文本存在 `Name` 属性，无子控件
- 消息 item 的 `BoundingRectangle` 占满列表全宽，无法通过位置区分发送方
- `ButtonControl` / `ImageControl` / `TextControl` 在 `searchDepth=2` 下均不存在

**正式方案决定**：

- ✅ **保留 `fallback_current_window_text` 作为当前 MVP 正式检测方案**
- 截图/像素/OCR 作为后续视觉识别预研，不进入当前主线
- 微信大版本更新后可重新运行 `scripts/debug_wechat_raw_tree.py` 验证是否有新控件结构

**保留的调试资源**：

| 资源 | 说明 |
|------|------|
| `scripts/debug_wechat_raw_tree.py` | UIA 深层控件树探测脚本 |
| `scripts/debug_wechat_screenshot.py` | 截图 + 像素分析脚本 |
| `GET /replies/debug/raw-tree` | UIA 深层探测 API 端点 |
| `POST /replies/debug/sender-experiment` | 发送方方案实验 API 端点 |
| `docs/experiment_report_sender_identification.md` | 完整实验报告 |

------

## 15. 实际项目结构

```text
auto_wechat/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 项目配置
│   ├── database.py             # 数据库连接与会话管理
│   ├── models.py               # ORM 模型（5 张表）
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── routers/                # API 路由
│   │   ├── __init__.py
│   │   ├── staff.py            #   销售管理 API
│   │   ├── leads.py            #   线索管理 API
│   │   ├── replies.py          #   手动回复 / 微信检测 API
│   │   ├── feedback.py         #   P3 反馈管理 API（compose / send / records）
│   │   ├── integrations.py     #   P4 外部系统集成 API（douyinAPI 同步）
│   │   ├── checks.py           #   回复检测 API
│   │   └── reports.py          #   报表统计 API
│   ├── integrations/           # 外部系统集成
│   │   ├── __init__.py
│   │   └── douyin_api_client.py #  P4 douyinAPI HTTP 客户端（只读）
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── staff_service.py    #   销售服务
│   │   ├── lead_service.py     #   线索服务
│   │   ├── assign_service.py   #   分配服务
│   │   ├── reply_analyzer.py   #   回复有效性分析
│   │   ├── reply_checker.py    #   回复检测服务
│   │   ├── douyin_sync_service.py # P4 douyinAPI 线索同步服务
│   │   ├── report_service.py   #   报表服务
│   │   ├── wechat_ui_reply_service.py  # 微信 UI 自动检测编排
│   │   └── feedback_service.py #   P3 反馈文本生成+发送服务
│   ├── wechat_ui/              # 微信 UI 自动化模块
│   │   ├── __init__.py
│   │   ├── window_locator.py   #   微信窗口定位（多策略）
│   │   ├── current_chat_reader.py  # 当前聊天消息读取
│   │   ├── message_parser.py   #   发送方识别 + 内容提取
│   │   ├── reply_detector.py   #   销售确认回复检测
│   │   ├── input_writer.py     #   P3 微信输入框写入
│   │   └── exceptions.py       #   UI 异常定义
│   └── scheduler/
│       ├── __init__.py
│       └── check_scheduler.py  # 定时检测调度器
├── scripts/
│   ├── init_db.py              # 初始化数据库
│   ├── seed_demo_data.py       # 插入演示数据
│   ├── run_demo_flow.py        # 端到端演示脚本
│   ├── debug_windows.py        # 窗口探测诊断脚本
│   ├── debug_wechat_messages.py # 消息控件结构诊断脚本
│   ├── debug_wechat_raw_tree.py # P2.5: UIA 深层控件树探测实验
│   └── debug_wechat_screenshot.py # P2.5: 截图 + 像素分析实验
├── tests/
│   ├── test_demo_flow.py       # 端到端自动化测试
│   └── test_douyin_sync.py     # P4 douyinAPI 同步测试（dry_run + 写库）
├── data/
│   └── auto_wechat.db          # SQLite 数据库（运行后生成）
├── docs/
│   ├── Phase0/
│   │   └── 流程图.png
│   ├── experiment_report_sender_identification.md # P2.5 实验报告
│   └── ai/
│       ├── 01_READING_RULES.md
│       ├── 02_EXECUTION_RULES.md
│       ├── 03_TESTING_RULES.md
│       ├── 04_OUTPUT_RULES.md
│       └── 05_PROJECT_CONTEXT.md
├── requirements.txt
├── .gitignore
├── CLAUDE.md
└── README.md
```

------

## 16. 核心数据库表

### 16.1 sales_staff（销售人员）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| name | String(50) | 销售姓名 |
| wechat_id | String(100) | 销售微信号（用于匹配主机微信中的发送方） |
| wechat_nickname | String(100) | 销售微信昵称 |
| phone | String(20) | 手机号 |
| status | String(20) | 状态：active / inactive |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 16.2 douyin_leads（抖音线索）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| source | String(20) | 来源平台，默认 douyin |
| lead_type | String(20) | 线索类型：lead / comment / chat |
| customer_name | String(100) | 客户名称/昵称 |
| customer_contact | String(100) | 联系方式 |
| content | Text | 线索内容 |
| source_url | String(500) | 来源链接 |
| source_id | String(100) | 来源平台ID |
| assigned_staff_id | Integer FK | 分配的销售ID |
| assigned_at | DateTime | 分配时间（超时计算的起点） |
| status | String(20) | 状态：pending / assigned / replied / timeout / closed |
| raw_data | Text | 原始数据JSON |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 16.3 reply_checks（回复检测记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| lead_id | Integer FK | 线索ID |
| staff_id | Integer FK | 销售ID |
| reply_deadline | DateTime | 要求回复截止时间（assigned_at + reply_timeout_minutes） |
| actual_reply_at | DateTime | 实际确认回复时间（从主机微信读取） |
| reply_content | Text | 销售发送的确认消息内容 |
| is_effective | Integer | 是否有效确认：0 / 1 |
| effectiveness_reason | String(200) | 判定原因 |
| check_status | String(20) | 检测状态：pending / replied / timeout / invalid |
| checked_at | DateTime | 检测时间 |
| created_at | DateTime | 创建时间 |

### 16.4 check_configs（检测配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| config_key | String(100) UNIQUE | 配置键 |
| config_value | Text | 配置值 |
| description | String(200) | 说明 |
| updated_at | DateTime | 更新时间 |

默认配置项：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| reply_deadline_minutes | 30 | 确认回复截止时间（分钟），销售收到线索后需在此时间内向主机微信确认 |
| check_interval_minutes | 5 | 定时检测间隔（分钟） |
| effective_reply_min_length | 2 | 有效回复最小长度 |
| effective_keywords | 收到,已添加微信,已添加 | 有效确认关键词 |
| invalid_keywords | 不知道,不清楚,等下再说,没空,无法处理 | 无效关键词 |
| expected_reply_text | 收到，已添加微信\|收到，已添加\|已添加微信 | 期望回复文本（`\|` 分隔多值），优先精确/包含匹配 |

------

## 17. 业务状态机

### 17.1 线索状态流转

```text
pending（待分配）
    ↓ 分配销售
assigned（已分配，等待销售向主机微信确认）
    ↓ 检测到有效确认              ↓ 超时未确认
replied（已确认）              timeout（超时未确认）
```

说明：

- **pending**：线索已创建，等待分配给销售
- **assigned**：已分配给销售，等待销售向主机微信 B 回复确认
- **replied**：在主机微信 B 中检测到销售的有效确认消息
- **timeout**：超过截止时间，主机微信 B 中仍未检测到销售的有效确认消息

### 17.2 检测记录状态流转

```text
pending（等待销售确认）
    ↓ 检测到有效确认         ↓ 检测到无效回复         ↓ 超时
replied（已确认）       invalid（无效回复）     timeout（超时）
```

------

## 18. 有效确认回复判定规则

### 18.1 业务定义

销售收到线索后，需要向主机微信 B 发送确认消息。**有效确认消息**必须包含以下关键词之一：

| 有效确认关键词 | 含义 |
|----------------|------|
| `收到` | 销售确认已收到线索 |
| `已添加微信` | 销售确认已添加客户微信 |
| `收到，已添加微信` | 销售确认既收到线索又添加了客户微信 |

### 18.2 允许的格式差异

系统对标点和空格有一定容错：

```text
收到           → 有效
收到。         → 有效
收到，已添加微信 → 有效
收到，已添加微信。→ 有效
收到 已添加微信  → 有效
已添加微信      → 有效
已添加微信。    → 有效
```

### 18.3 判定规则

判定顺序（优先级从高到低）：

1. 回复内容为空 → **无效**
2. 命中无效关键词（如"不知道"、"没空"等）→ **无效**
3. 匹配 `expected_reply_text`（精确或包含）→ **有效**（最高优先级）
4. 命中有效确认关键词 且 长度 ≥ 配置值 → **有效**
5. 命中有效确认关键词 但 长度 < 配置值 → **无效**
6. 未命中任何关键词 且 长度 ≥ 配置值 → **有效**（默认有效，仅非 strict_mode 时）
7. 未命中任何关键词 且 长度 < 配置值 → **无效**

> 以上规则均可通过 `check_configs` 表动态配置，无需改代码。

### 18.4 超时规则

配置项：`reply_deadline_minutes`（默认 30 分钟）

```text
截止时间 = 线索分配时间（assigned_at）+ reply_timeout_minutes

示例：
  线索 14:00 分配给销售A
  reply_timeout_minutes = 10
  → 销售A 必须在 14:10 前向主机微信 B 发送有效确认消息
  → 14:10 后仍未检测到 → 标记为 timeout
```

------

## 19. 微信 UI 检测核心逻辑

### 19.1 检测目标

系统读取的是**主机微信 B** 窗口的消息，不是客户微信，也不是销售微信。

检测链路：

```text
定位主机微信 B 窗口
    ↓
定位当前聊天消息列表
    ↓
读取最近 N 条消息
    ↓
识别每条消息的发送方（区分 self=B主机 / friend=C销售）
    ↓
筛选出销售 C 发送的消息
    ↓
检查消息内容是否命中有效确认关键词
    ↓
检查消息时间是否在超时时限内
    ↓
判定结果：PASS（有效确认）或 TIMEOUT（超时）
    ↓
结果落库（更新 reply_checks + douyin_leads）
```

### 19.2 窗口定位策略（多策略容错）

文件：`app/wechat_ui/window_locator.py`

| 策略 | 方法 | 说明 |
|------|------|------|
| 策略 1 | `ctypes.FindWindowW` | 按窗口标题精确查找（"Weixin"、"微信"、"WeChat"） |
| 策略 2 | Desktop 遍历 | 遍历所有顶层窗口，按 `ClassName` 模糊匹配 |
| 策略 3 | 多候选排序 | 优先选择有消息列表控件、非离屏、面积最大的 |

### 19.3 发送方识别（多策略级联）

文件：`app/wechat_ui/message_parser.py`

| 优先级 | 策略 | 原理 |
|--------|------|------|
| 1 | 系统消息过滤 | 时间分割线、系统提示 → 标记为 `system` |
| 2 | **消息气泡位置（主力）** | 自己发的消息靠右，对方消息靠左（边缘距离阈值 80px） |
| 3 | 头像控件位置 | `ButtonControl`/`ImageControl` 头像在中线左/右侧 |
| 4 | 文本位置辅助 | `TextControl` 的中心 X 坐标偏向判断 |
| 5 | 兜底 `unknown` | 记录调试日志，便于后续优化 |

### 19.4 核心前提

> 当前电脑登录的微信账号就是**主机微信 B**。
>
> 因此 `self`（自己发的）消息是主机微信 B 发的，`friend`（对方发的）消息才是销售 C 发的。
>
> **销售的确认消息在主机微信 B 中表现为"对方发的消息"（`friend`）。**

### 19.5 兜底机制

当 UI 无法区分发送方时（`self` 消息数为 0），启用**兜底模式**：

> 业务前提：当前窗口就是主机微信 B + 销售 C 的聊天窗口

兜底模式下，将所有非系统消息、有文本内容的消息作为候选分析对象。

兜底模式检测结果会标记：

```text
detection_mode    = fallback_current_window_text
confirmed_required = true     # 需要人工复核
warning           ≠ null      # 提示需人工确认
risk_level        = medium / high  # 中高风险
```

------

## 20. API 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/staff` | 创建销售人员 |
| GET | `/staff` | 获取销售列表 |
| GET | `/staff/{id}` | 获取单个销售 |
| PUT | `/staff/{id}` | 更新销售信息 |
| POST | `/leads` | 创建线索 |
| GET | `/leads` | 获取线索列表 |
| GET | `/leads/{id}` | 获取单条线索 |
| POST | `/leads/{id}/assign` | 分配线索给销售 |
| POST | `/replies/manual` | 手动录入销售确认回复 |
| POST | `/replies/current-wechat-detect` | 通过主机微信 B 的 UI 自动检测当前聊天窗口 |
| GET | `/replies/debug/windows` | 调试：列出所有疑似微信窗口 |
| GET | `/replies/debug/messages` | 调试：返回消息原始控件结构 |
| GET | `/replies/debug/raw-tree` | P2.5 实验：UIA 深层控件树探测 |
| POST | `/replies/debug/sender-experiment` | P2.5 实验：发送方识别方案验证 |
| POST | `/feedback/compose` | P3：生成反馈文本（主机 B → 数据源 A） |
| POST | `/feedback/send-current-chat` | P3：将反馈文本写入当前微信聊天窗口 |
| GET | `/feedback/records` | P3：查询反馈发送记录 |
| POST | `/integrations/douyin/sync-leads` | P4：从 douyinAPI 拉取线索并同步（dry_run 预览 + 写库） |
| POST | `/checks/run` | 手动触发一次超时检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |

------

## 21. 调用链

### 21.1 标准请求调用链

```text
API（routers/）
    ↓ Depends(get_db)
Service（services/）
    ↓ SQLAlchemy ORM
Database（SQLite）
```

### 21.2 线索分配调用链

```text
POST /leads/{id}/assign
    ↓
assign_service.assign_lead()
    ↓ 更新 douyin_leads 状态为 assigned，记录 assigned_at
    ↓ 创建 reply_checks 记录（pending）
    ↓ 计算 reply_deadline = assigned_at + reply_timeout_minutes
Database
```

### 21.3 手动确认录入调用链

```text
POST /replies/manual
    ↓
reply_checker.record_manual_reply()
    ↓ 查找/创建 reply_checks 记录
    ↓ reply_analyzer.analyze_reply() 判定有效性
    ↓ 更新 reply_checks（is_effective, check_status）
    ↓ 同步更新 douyin_leads 状态
Database
```

### 21.4 微信 UI 自动检测调用链

```text
POST /replies/current-wechat-detect
    ↓
wechat_ui_reply_service.detect_reply_from_wechat()
    ↓ window_locator.find_wechat_window()            定位主机微信 B 窗口
    ↓ current_chat_reader.read_recent_messages()      读取主机微信 B 消息
    ↓ reply_detector.find_self_messages()              筛选销售 C 消息
    ↓ reply_detector.find_effective_reply()            关键词匹配 + 超时判断
    ↓ _update_check_as_replied()                       更新 reply_checks + douyin_leads
Database
```

### 21.5 超时检测调用链

```text
定时调度器（scheduler/check_scheduler.py）或 POST /checks/run
    ↓
reply_checker.run_checks()
    ↓ 查询所有 pending 状态的 reply_checks
    ↓ 检查 now > reply_deadline
    ↓ 更新为 timeout
    ↓ 同步更新 douyin_leads 状态
Database
```

### 21.6 React 线索同步调用链

```text
React LeadsManagement「同步」按钮
    ↓ syncDouyinLeads({ dryRun: true })
    ↓ axios POST /integrations/douyin/sync-leads
    ↓
auto_wechat integrations.py
    ↓ douyin_sync_service.preview_sync_leads()
    ↓ douyin_api_client.fetch_leads()
    ↓
douyinAPI GET /leads
    ↓
返回 SyncResponse（预览 or 写库）
    ↓
React 刷新列表（fetchLeads + fetchStaffList + fetchSummary）
```

------

## 22. MVP 成功标准

### 22.1 PASS 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  主机微信 B 在 14:00 ~ 14:10 期间收到了销售A发送的"收到，已添加微信"

预期结果：
  检测结果 = PASS
  reply_checks.check_status = "replied"
  reply_checks.is_effective = 1
  douyin_leads.status = "replied"
```

### 22.2 TIMEOUT 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  14:10 后主机微信 B 仍未收到销售A的有效确认消息

预期结果：
  检测结果 = TIMEOUT
  reply_checks.check_status = "timeout"
  douyin_leads.status = "timeout"
```

------

## 23. 当前阶段不关注

以下能力在当前阶段明确**不做**：

- **不检测销售和客户的聊天记录**
- **不判断客户是否回复**
- **不分析销售对客户的沟通质量**
- **不自动给客户发消息**
- 不做群发
- 不做复杂 CRM
- 不反编译或修改小猫AI员工闭源代码
- AI 自动回复
- Agent
- RAG
- 微信数据库读取/解密
- 企业微信 DLL 注入
- 小猫AI员工集成
- 权限系统
- 多租户

------

## 24. 重要约束

任何后续开发必须遵守：

1. **优先复用**现有 FastAPI、数据库、服务层代码
2. **禁止推翻**现有 MVP 重构
3. **禁止重新设计**数据库
4. **禁止引入**复杂架构
5. **遵循**先验证业务闭环，再接入真实微信，最后扩展 AI 能力
6. **禁止使用**：微信数据库解密、DLL 注入、微信协议逆向
7. **优先使用**：UI Automation、视觉识别、OCR

------

## 25. 开发原则

- 先做最小验证，不做大而全
- 优先跑通一条线索的完整检测链路
- 规则判断优先，AI 判断后置
- 先保证可解释，再追求自动化程度
- 所有外部软件交互都要封装，避免业务逻辑散落
- 每一步都要保留日志

### 上游系统原则

禁止：

- SQLite 文件共享
- 数据库直读
- 人工同步数据库

必须：

- HTTP API 通信

### 本地测试原则

开发阶段：

不得连接生产 douyinAPI。

必须支持：

- Mock 数据
- dry_run
- 本地 SQLite

### 前端策略

React 项目（`E:\work\project\react`）是最终交付界面。

不要新建第二套前端。

开发方式：React 页面逐步替换 Mock 数据，接入 auto_wechat 和 douyinAPI 真实接口。

当前进展：LeadsManagement 页面已完成真实 API 接入，不再使用 Mock 数据。API 层架构稳定，后续页面可复用。

------

## 26. 禁止事项

- 禁止反编译 `.pyd` 文件
- 禁止修改小猫AI员工安装目录
- 禁止把 MVP 写成完整 CRM
- 禁止一开始就接复杂大模型 Agent
- 禁止没有证据就输出确定性结论
- 禁止绕过微信/企业微信安全机制
- 禁止做骚扰、群发、自动营销能力

------

## 27. 已知环境问题

### React TypeScript 配置

时间：2026-06-09

现象：

VSCode 提示：

Option 'baseUrl' is deprecated.

并建议：

ignoreDeprecations = 6.0

实际情况：

项目 TypeScript 编译器不支持 6.0。

正确配置：

ignoreDeprecations = 5.0

验证方式：

npm run build

如 build 成功则配置正确。

禁止根据 VSCode 提示自动修改为 6.0。

### React tsconfig.json 修改记录

时间：2026-06-09

文件：`E:\work\project\react\tsconfig.json`

用户手动修改（非 AI 修改）：

- 添加了 `ignoreDeprecations = 6.0`
- 注：AI 不应修改此文件，保持用户手动配置

### 局域网访问配置

时间：2026-06-09

后端启动：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

前端启动：

```bash
cp .env.lan .env.development   # 临时切换为局域网地址
npm run dev -- --host 0.0.0.0 --port 5173
```

局域网 IP：`192.168.110.113`

CORS 已包含局域网地址（`app/main.py`）。

注意：`.env.development` 已恢复为本地地址 `http://127.0.0.1:9000`。局域网访问需手动切换为 `.env.lan` 内容。
