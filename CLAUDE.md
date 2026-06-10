# 项目语言规范

请严格遵守以下规则：
1. 所有对话、解释、建议必须使用**简体中文**。
2. 代码注释必须使用中文。
3. 生成的 Commit Message 必须使用中文。
4. 严禁出现大段未翻译的英文技术名词。

# Project AI Entry Protocol

你正在参与一个真实项目开发。

本项目遵循分层 AI 协作规范。

开始任何任务前必须先阅读项目规范。

------

# Rule Priority

优先级如下：

P0 Reading Rules
P1 Project Context
P2 Execution Rules
P3 Testing Rules
P4 Output Rules

发生冲突时：

Reading Rules
>
Project Context
>
Execution Rules
>
Testing Rules
>
Output Rules

------

# Current Project Status

项目名称：主机微信线索分发与销售跟进检测系统

当前阶段：P8 Demo Hardening / P0 Risk Fixes

已完成：
- P0 项目初始化、数据库设计
- P1 线索入库、销售分配、回复检测
- P2 微信 UI 自动化检测
- P2.5 发送方识别实验（结论：保留兜底模式，截图/OCR 作为后续预研方向）
- P3 反馈发送（主机微信 B → 数据源 A）
- P4 douyinAPI 线索同步与自动分配
- P5 React UI Integration（线索列表、详情、同步、分配、检测记录、微信状态检测、局域网访问）
- P6 微信回复检测闭环（窗口识别、消息读取、关键词命中、自动检测调度器）
- P7 销售派单 Demo（联系人搜索、自动通知、自触发误判修复、紧急停止机制）
- P8 Demo 稳定化主要功能（AI小高助手配置、测试线索生成器、微信固定左侧、Alt+Q 紧急停止、桌面浮层、自动同步派单）
- P0-1 局域网访问修复
- P0-2E 联系人二次确认（策略 A/B/C、send_to_staff guard）
- P0-2F 白屏根因隔离（结论：17/40 白屏是 Esc 导致窗口隐藏 + 截桌面背景误判；但灰屏现象仍存在）
- P0-2G 微信窗口隐藏与白屏误判修复 — ⚠️ **部分修复**
  - ✅ 已解决：Esc 导致窗口隐藏、截桌面背景误判白屏、ensure_wechat_visible 恢复、搜索流程 Esc 清理
  - ❌ 未解决：窗口 visible=True 但客户区灰色/空白、UI 内容不渲染

进行中：
- P0-2 微信自动化稳定化

下一步聚焦：
- **P0-2H 内容渲染验证**：定位窗口可见但内容未渲染的原因；每个关键步骤后截图验证；检测灰屏比例；确认聊天列表/消息列表存在后才继续自动化
- 联系人确认/发送复测（P0-2H 渲染验证通过后才能继续）
- 多目标检测队列
- 跨机器 / VM 运行验证

业务架构：

```text
抖音平台
    ↓ Webhook
douyinAPI（数据源系统 A，端口 8081）
    ↓ HTTP API
auto_wechat（副系统，端口 9000）
    ↓ UI Automation
主机微信 B
    ↓ 微信消息
销售微信 C
    ↓ 回复检测
主机微信 B → 反馈给数据源 A
```

前端架构：

```text
React UI（端口 5173）
    ↓ axios API
auto_wechat（端口 9000）
    ↓ HTTP API
douyinAPI 测试环境（端口 8081）
```

auto_wechat 的职责：

1. 接收上游线索（从 douyinAPI 拉取）
2. 线索入库
3. 销售分配
4. 主机微信 B 通知销售 C
5. 检测销售 C 是否在指定时间内回复主机微信 B
6. 检测结果入库
7. 主机微信 B 将跟进结果反馈给数据源 A

auto_wechat 不负责：

- 抖音 Webhook 接收
- 抖音账号授权
- 抖音私信管理
- 抖音消息存储

这些属于 douyinAPI。

技术约束：

```text
禁止使用：
  - 微信数据库解密
  - DLL 注入
  - 微信协议逆向

优先使用：
  - UI Automation
  - 视觉识别
  - OCR
```

------

# Upstream System Constraints

auto_wechat 不是线索源系统。

线索来源于上游系统 douyinAPI。

## 对接原则

优先通过 HTTP API 对接上游系统。

禁止：

- 数据库直读
- SQLite 文件共享
- 手工复制数据库

第一原则：系统之间通过 API 通信。

## 上游接口（douyinAPI）

拉取线索：

```text
GET http://douyinapi-host:8081/leads?lead_status=pending&page_size=50
GET http://douyinapi-host:8081/leads/export
```

字段映射（douyinAPI → auto_wechat）：

| douyinAPI 字段 | auto_wechat 字段 | 说明 |
|----------------|-----------------|------|
| open_id | source_id | 抖音用户唯一标识 |
| display_name | customer_name | 客户昵称 |
| last_interaction_record | content | 最近交互内容 |
| "douyin" | source | 来源平台 |
| "私信" | lead_type | 线索类型 |

## 本地开发原则

任何开发和测试：

不得修改生产 douyinAPI 数据。

必须支持：

- 本地 Mock 数据
- dry_run
- 本地 SQLite 测试库

禁止：

开发阶段直接连接生产数据库。

------

# System Architecture (2026-06)

当前系统由三个独立项目组成，各有明确职责边界：

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

## douyinAPI

路径：`E:\work\project\douyinAPI`

负责：

- 抖音 Webhook 接收
- 抖音私信会话管理
- 线索沉淀与存储
- 抖音授权管理

不负责：

- 销售分配
- 微信自动化
- 回复检测
- 主机微信反馈

## auto_wechat

路径：`E:\work\project\auto_wechat`

负责：

- 上游线索同步（从 douyinAPI 拉取）
- 销售分配
- 回复检测
- 超时检测
- 主机微信反馈
- 微信 UI 自动化

## React UI

路径：`E:\work\project\react`

负责：

- 客户运营后台展示
- 线索管理界面
- 销售管理界面
- 微信助手界面
- AI 剪辑界面
- 商户管理界面

当前状态（2026-06-09 更新）：

- LeadsManagement 页面已接入真实 API（线索列表、统计卡片、销售下拉）
- 已集成 douyinAPI 测试环境同步按钮（dry_run 预览 + 二次确认写库）
- API 基础层已完成（`src/api/`：client.ts、types.ts、leads.ts、staff.ts、reports.ts、integrations.ts）
- 环境变量已配置（`.env.development`：`VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000`）
- 其余页面仍为 Mock 数据
- 正在逐步替换 Mock 数据，接入真实 API

------

# Development Strategy

当前阶段：P8 Demo Hardening / P0 Risk Fixes

目标：让连续演示稳定可靠，修复产品化验证风险

原则：

1. HTTP API 对接
2. 不共享数据库
3. 不直读 SQLite
4. 不修改 douyinAPI
5. 本地测试优先
6. Demo 优先验证，生产化后置
7. 不新增业务功能，专注稳定化

## 已完成阶段

- P4：douyinAPI Integration（线索同步、入库、自动/手动分配）
- P5：React UI Integration（线索列表、详情、同步、分配、检测记录、微信状态检测、局域网访问）
- P6：WeChat Reply Detection（窗口识别、消息读取、关键词命中、自动检测调度器）
- P7：Sales Dispatch Demo（联系人搜索、自动通知、自触发误判修复、紧急停止机制）

## P8 实施路线

- P8-1：WechatAgent 添加销售配置接入 POST /staff（已完成 ✅）
- P8-2：douyinAPI 开发测试线索自动生成器（已完成 ✅）
- P8-3：React 自动同步派单 + 后端 auto_notify（已完成 ✅）
- P8-4：Alt+Q 全局紧急停止 + 桌面提示浮层（已完成 ✅）
- P8-5：微信固定左侧布局（已完成 ✅）

## P0 风险修复

- P0-1：局域网访问修复（已完成 ✅）
- P0-2：微信自动化稳定化（进行中）
- P0-3：多目标检测队列（待做）

------

# Frontend Strategy

重要结论：

React 项目（`E:\work\project\react`）是最终交付界面。

不要新建第二套前端。

开发方式：

React 页面逐步替换 Mock 数据，接入 auto_wechat 和 douyinAPI 真实接口。

当前进展：

LeadsManagement 页面已完成真实 API 接入，不再使用 Mock 数据。

API 层架构：

```text
src/api/client.ts        — axios 实例（baseURL 从环境变量读取）
src/api/types.ts         — TypeScript 类型定义（与 auto_wechat schemas 对齐）
src/api/leads.ts         — 线索 API（GET /leads, GET /leads/{id}）
src/api/staff.ts         — 销售 API（GET /staff）
src/api/reports.ts       — 报表 API（GET /reports/summary）
src/api/integrations.ts  — 同步 API（POST /integrations/douyin/sync-leads）
```

------

# P7 Sales Dispatch Demo（已完成 ✅）

P7 已完成"通知销售"环节。

完整业务链路：

```text
douyinAPI → auto_wechat sync → assign staff
    → open sales WeChat chat by nickname
    → send lead notification
    → sales replies
    → auto detect reply
    → mark lead as replied
    → React shows 已跟进
```

P7 已完成：

- P7-0：探索小猫AI员工与 ai-bot-pc（结论：继续使用 uiautomation + input_writer）
- P7-1：微信联系人搜索（contact_searcher.py）
- P7-2：线索通知发送（notification_service + lead_notifications 记录）
- P7-3：发送后设置自动检测目标
- P7-4：销售回复后自动检测并更新已跟进
- P7-BUG-1：自触发误判修复（通知模板去关键词、静默期、exclude_text_list）
- P7-STOP-1：紧急停止机制（/automation/status、/emergency-stop、/resume、6 个自动化入口 guard、前端停止按钮）

## P7 安全边界

- 禁止读取微信数据库
- 禁止使用微信协议
- 禁止 DLL 注入
- Demo 可使用 UI 自动化
- 自动搜索联系人存在误发风险
- 如果自动搜索失败，必须降级为"用户手动打开销售窗口 → 系统发送当前窗口"
- auto_send 只用于 Demo 验证，后续生产应默认 require_confirm=true
- 所有发送动作必须记录 lead_notifications 或等效日志

------

# P8 Demo Hardening（主要功能已完成 ✅）

P8 目标不是新增业务功能，而是让连续演示稳定可靠。

P8 完整业务链路：

```text
douyinAPI 自动生成测试线索
    → React 自动同步派单
    → auto_wechat 同步入库
    → 自动分配销售
    → 自动搜索销售微信昵称
    → 自动发送线索通知
    → 自动设置检测目标
    → 销售回复
    → 自动检测
    → lead.status=replied
    → React 显示已跟进
```

P8 已完成：

1. WechatAgent 添加销售配置接入 POST /staff
2. douyinAPI /dev/test-leads/start/stop/status
3. 微信窗口固定左侧布局
4. Alt+Q 全局紧急停止
5. 桌面自动化状态浮层
6. 自动同步派单 auto_notify
7. P7 自触发误判修复
8. 局域网访问修复

P8 真实验证结果：

- 线索同步：7/7 新建成功
- 自动分配：7/7
- 自动通知：7/7
- 联系人搜索：4/4 成功
- 用户确认收到微信通知
- 紧急停止机制生效
- 桌面浮层和 Alt+Q 已运行
- 自动检测存在单目标覆盖问题，检测成功率约 13/28（46%）

------

# LAN Access Rules

局域网演示必须使用：

auto_wechat：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

React：

```bash
npm run dev:lan
```

React LAN 环境变量：

```text
VITE_AUTO_WECHAT_API_BASE_URL=http://192.168.110.113:9000
```

不能使用：

```text
VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000
```

因为局域网其他机器访问 React 时，127.0.0.1 指向访问者自己的机器。

CORS 必须允许：

- `http://192.168.110.113:5173`
- `http://DESKTOP-T0HA3GO:5173`
- `http://localhost:5173`
- `http://127.0.0.1:5173`

防火墙规则：TCP 9000、TCP 5173

------

# Current Known Risks

## P0 — 必须修复

1. **微信自动化定位不稳定**：鼠标移动、窗口焦点变化、坐标漂移可能导致搜索框/输入框定位失败。当前正在 P0-2 修复。

2. **自动检测单目标覆盖**：wechat_active_check_id 只能保存一个 check。多条线索连续发送时，后发目标会覆盖前一个目标。P0-3 / P9 需要升级为多目标检测队列。

3. **跨机器运行尚未验证**：当前已验证局域网访问页面和 API。但微信自动化只能控制 Agent 所在机器的微信。产品化需要验证 Windows 电脑 / Windows VM 上运行 Agent。

## P1 — 产品化优化

1. 桌面浮层需要改为更明显的常驻控制中心
2. 演示数据需要清理，避免无 wechat_nickname 的销售导致 failed
3. 自动同步派单耗时较长，当前是串行搜索+发送

------

# Product Architecture Clarification

当前 Demo 架构不是"远程控制任意电脑微信"。

微信自动化只能发生在运行 auto_wechat Agent 的 Windows 机器上。

```text
机器 A 运行 auto_wechat → 只能控制机器 A 的微信
机器 B 浏览器访问机器 A → 只能看到页面并触发机器 A 的微信自动化，不能控制机器 B 的微信
```

未来产品化方向：

```text
中心服务 / 管理后台
    → 多个 Windows Agent
    → 每个 Agent 控制本机微信
```

## P7 参考软件探索结论（P7-0 已完成）

### 小猫AI员工

- PyInstaller + Cython .pyd
- wxauto 核心 .pyd 不可读
- 可读部分显示其发送机制本质是剪贴板 + Ctrl+V + Enter
- 消息读取使用 UIAutomation 消息列表解析
- 有任务调度数据库，但不是销售线索分配业务
- 当前微信版本存在 wxauto 不兼容问题
- 不建议直接复用 wxauto / DLL / wecom 注入方案
- 可参考任务调度、状态记录、UIAutomation 思路

### ai-bot-pc

- Electron 38 + Vue 3 + TypeScript
- 本地只是瘦客户端
- 业务逻辑在服务端
- 本地无微信自动化能力
- 无任务分发、无销售/线索概念、无本地数据库
- 对 P7 设计不产生改变

结论：auto_wechat 继续使用 uiautomation + input_writer 方案。

## 微信窗口布局策略

微信窗口默认应移动到左侧。

原因：React 右侧详情区域包含核心按钮（设为自动检测目标、检测微信回复、发送线索给销售），微信放右侧会遮挡操作按钮。

推荐工作台布局：

```text
微信窗口（左侧）  |  React 后台（右侧）
```

当前 activate_wechat_window 已支持窗口移动。后续默认应从右上角改为左侧布局。

Demo 可先默认 left。

------

# React TypeScript 配置约束

React 项目（`E:\work\project\react`）使用 TypeScript 5.9 + Vite 项目模板。

以下约束经 2026-06-09 确认为最终稳定配置，禁止后续开发修改。

### Constraint 1 — ignoreDeprecations

所有 TS 配置文件必须保留：

```json
{
  "ignoreDeprecations": "5.0"
}
```

**版本兼容说明（2026-06-09 验证）：**

- 项目 TypeScript 版本：5.9.3
- `"5.0"` 是当前 TS 5.9.3 支持的正确值，构建通过
- `"6.0"` 尚未被 TS 5.9.3 支持，会导致 `TS5103: Invalid value for '--ignoreDeprecations'` 构建失败
- VSCode 可能使用更高版本的 TypeScript 语言服务，提示使用 `"6.0"`，但项目构建器不支持
- 结论：保持 `"5.0"`，忽略 VSCode 中该提示；升级 TS 7.x 时需重新评估

### Constraint 2 — composite

tsconfig.json 使用 project references：

```json
{
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

因此：

tsconfig.app.json 必须包含：

```json
{
  "composite": true
}
```

tsconfig.node.json 必须包含：

```json
{
  "composite": true
}
```

否则 VSCode 会提示：`Referenced project must have setting "composite": true`

### Constraint 3 — emitDeclarationOnly

不要使用 `noEmit: true` 与 `composite` 组合。

当前项目必须使用：

```json
{
  "emitDeclarationOnly": true
}
```

避免：`Referenced project may not disable emit`

### Development Rule

未来任何 React 项目开发任务，涉及以下文件：

- tsconfig.json
- tsconfig.app.json
- tsconfig.node.json

修改前必须检查：

1. ignoreDeprecations 是否保留为 5.0（当前 TS 5.9.3 仅支持 "5.0"，不支持 "6.0"）
2. composite 是否保留为 true
3. emitDeclarationOnly 是否保留
4. @ 路径别名是否正常
5. vite.config.ts 中 alias 是否正常

禁止自动升级或重构 TS 配置。

------

# Mandatory Workflow

任何任务必须遵循：

理解需求
↓
阅读项目
↓
建立上下文
↓
分析影响面
↓
输出方案
↓
获得确认（如果需要）
↓
实现
↓
测试
↓
总结

禁止跳过阅读阶段直接编码。

------

# Required Reading Order

开始任务后按顺序阅读：

1. 
docs/ai/01_READING_RULES.md

1. 

docs/ai/05_PROJECT_CONTEXT.md

1. 

docs/ai/02_EXECUTION_RULES.md

1. 

docs/ai/03_TESTING_RULES.md

1. 

docs/ai/04_OUTPUT_RULES.md

------

# Reading Completion Gate

在完成以下问题之前禁止编码：

1. 当前需求属于哪个模块？
2. 当前调用链是什么？
3. 当前数据从哪里来？
4. 当前数据写到哪里去？
5. 当前权限在哪里校验？
6. 当前影响哪些模块？
7. 当前风险等级是什么？
8. 最小修改方案是什么？

如果无法回答：

继续阅读。

------

# High Risk Areas

以下区域属于高风险：

- Docker
- Docker Compose
- Nginx
- Environment Variables
- Database Migration
- Authentication
- RBAC
- File Storage
- Background Worker
- Deployment Scripts
- CI/CD

涉及以上区域：

必须先完成风险分析。

禁止直接修改。

------

# Coding Entry Condition

只有满足以下条件才能编码：

- 已完成项目阅读
- 已完成调用链分析
- 已完成影响面分析
- 已完成方案设计
- 已明确验证方案

否则继续阅读。

------

# Project Philosophy

AI 的首要职责不是写代码。

AI 的首要职责是理解项目。

理解错误：

后续全部错误。

理解正确：

编码只是执行。

因此：
Reading First.
Coding Later.
