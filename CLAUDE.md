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

当前阶段：P5 React UI Integration

已完成：
- P0 项目初始化、数据库设计
- P1 线索入库、销售分配、回复检测
- P2 微信 UI 自动化检测
- P2.5 发送方识别实验（结论：保留兜底模式，截图/OCR 作为后续预研方向）
- P3 反馈发送（主机微信 B → 数据源 A）
- P4 douyinAPI 线索同步与自动分配
- P5-2A auto_wechat CORS 配置（允许 5173 跨域）
- P5-2B React API 基础层（axios 客户端 + 类型定义 + 5 个 API 模块）
- P5-2C LeadsManagement 只读接入真实 API（线索列表 + 销售下拉 + 统计卡片）
- P5-2D LeadsManagement 增加 douyinAPI 测试环境同步按钮（dry_run 预览 → 二次确认 → 写库）

下一步：P5-3 Lead Assignment UI Integration

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

当前阶段：P5 React UI Integration

目标：React UI 逐步替换 Mock 数据，接入 auto_wechat 真实接口

原则：

1. HTTP API 对接
2. 不共享数据库
3. 不直读 SQLite
4. 不修改 douyinAPI
5. 本地测试优先

## React UI 集成进度

已完成：

- P5-2A：auto_wechat CORS 配置
- P5-2B：React API 基础层（axios 客户端 + 类型定义 + 5 个 API 模块）
- P5-2C：LeadsManagement 只读接入真实 API
- P5-2D：LeadsManagement 增加 douyinAPI 测试环境同步按钮

下一步：

- P5-3：Lead Assignment UI Integration（线索分配 UI）

待规划：

- P5-4：Report Dashboard（报表看板）
- P5-5：Check Records（检测记录）
- P5-6：Lead Detail Enhancement（线索详情增强）
- P5-7：Chat Integration（对话跟进集成）

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

# React TypeScript 配置约束

React 项目（`E:\work\project\react`）使用 TypeScript 5.9 + Vite 项目模板。

以下约束经 2026-06-09 确认为最终稳定配置，禁止后续开发修改。

### Constraint 1 — ignoreDeprecations

所有三个 TS 配置文件必须保留：

```json
{
  "ignoreDeprecations": "5.0"
}
```

禁止移除。移除后会出现 `baseUrl` 弃用提示。

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

1. ignoreDeprecations 是否保留为 5.0
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
