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

当前阶段：P3 Completed（反馈发送模块已完成）

当前聚焦：P4 上游线索对接（douyinAPI → auto_wechat）

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
React UI（客户运营后台前端原型，纯 Mock）
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

当前状态：

- 纯前端原型
- 无 API
- 所有数据均为 Mock
- 用于产品演示

------

# Development Strategy

当前阶段：P4

目标：douyinAPI → auto_wechat 线索同步

原则：

1. HTTP API 对接
2. 不共享数据库
3. 不直读 SQLite
4. 不修改 douyinAPI
5. 本地测试优先

------

# Frontend Strategy

重要结论：

React 项目（`E:\work\project\react`）是最终交付界面。

不要新建第二套前端。

未来开发方式：

React 页面逐步替换 Mock 数据，接入 auto_wechat 和 douyinAPI 真实接口。

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
