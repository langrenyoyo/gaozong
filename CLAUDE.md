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