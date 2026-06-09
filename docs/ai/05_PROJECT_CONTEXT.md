# 05_PROJECT_CONTEXT.md

> 本文档是 AI Coding Agent 的项目上下文。
>
> 优先级低于阅读规范，高于执行规范、测试规范、输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 1. 项目名称

抖音线索销售微信回复检测系统

## 2. 项目阶段

MVP 验证阶段（已完成 MVP 闭环）

## 3. 项目目标

验证销售人员在接收到抖音分配线索后，是否在规定时间内通过微信进行了有效回复。

核心流程：

```text
抖音线索 → 分配销售 → 销售微信处理 → 系统检测是否有效回复 → 超时统计 → 报表统计
```

## 4. 项目定位

本项目是一个**独立项目**，运行于 `E:\work\project\auto_wechat`。

**不依赖**以下任何外部系统或模块：

- 小猫AI员工
- `core/*.pyd`
- `wxauto.pyd`
- 企业微信 DLL 注入
- MCP 工具接口

------

## 5. 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| FastAPI + Uvicorn | Web 框架，端口 9000 |
| SQLAlchemy 2.x | ORM |
| SQLite | 本地数据库 `data/auto_wechat.db` |
| Pydantic 2.x | 数据校验 |
| threading | 定时任务调度（轻量后台线程） |

------

## 6. 当前 MVP 已完成

以下功能均已实现且通过测试：

- FastAPI 项目骨架（`app/main.py`）
- SQLite 数据库 + ORM 模型（4 张表）
- 销售人员管理（增删改查）
- 抖音线索管理（创建、查询、分配）
- 线索分配（手动分配 + 自动轮询分配）
- 手动回复录入
- 回复有效性分析（关键词 + 长度规则）
- 超时检测（定时扫描 + 手动触发）
- 汇总报表（全局统计 + 分销售统计）
- 定时任务调度器（后台线程）
- Demo 数据脚本
- 端到端自动化测试

------

## 7. 实际项目结构

```text
auto_wechat/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 项目配置
│   ├── database.py             # 数据库连接与会话管理
│   ├── models.py               # ORM 模型（4 张表）
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── routers/                # API 路由
│   │   ├── __init__.py
│   │   ├── staff.py            #   销售管理 API
│   │   ├── leads.py            #   线索管理 API
│   │   ├── replies.py          #   手动回复 API
│   │   ├── checks.py           #   回复检测 API
│   │   └── reports.py          #   报表统计 API
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── staff_service.py    #   销售服务
│   │   ├── lead_service.py     #   线索服务
│   │   ├── assign_service.py   #   分配服务
│   │   ├── reply_analyzer.py   #   回复有效性分析
│   │   ├── reply_checker.py    #   回复检测服务
│   │   └── report_service.py   #   报表服务
│   └── scheduler/
│       ├── __init__.py
│       └── check_scheduler.py  # 定时检测调度器
├── scripts/
│   ├── init_db.py              # 初始化数据库
│   ├── seed_demo_data.py       # 插入演示数据
│   └── run_demo_flow.py        # 端到端演示脚本
├── tests/
│   └── test_demo_flow.py       # 端到端自动化测试
├── data/
│   └── auto_wechat.db          # SQLite 数据库（运行后生成）
├── docs/
│   ├── Phase0/
│   │   └── 流程图.png
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

## 8. 核心数据库表

### 8.1 sales_staff（销售人员）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| name | String(50) | 销售姓名 |
| wechat_id | String(100) | 微信号 |
| wechat_nickname | String(100) | 微信昵称 |
| phone | String(20) | 手机号 |
| status | String(20) | 状态：active / inactive |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 8.2 douyin_leads（抖音线索）

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
| assigned_at | DateTime | 分配时间 |
| status | String(20) | 状态：pending / assigned / replied / timeout / closed |
| raw_data | Text | 原始数据JSON |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### 8.3 reply_checks（回复检测记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| lead_id | Integer FK | 线索ID |
| staff_id | Integer FK | 销售ID |
| reply_deadline | DateTime | 要求回复截止时间 |
| actual_reply_at | DateTime | 实际回复时间 |
| reply_content | Text | 回复内容 |
| is_effective | Integer | 是否有效回复：0 / 1 |
| effectiveness_reason | String(200) | 判定原因 |
| check_status | String(20) | 检测状态：pending / replied / timeout / invalid |
| checked_at | DateTime | 检测时间 |
| created_at | DateTime | 创建时间 |

### 8.4 check_configs（检测配置）

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
| reply_deadline_minutes | 30 | 回复截止时间（分钟） |
| check_interval_minutes | 5 | 定时检测间隔（分钟） |
| effective_reply_min_length | 2 | 有效回复最小长度 |
| effective_keywords | 收到,已添加,已联系,已通过,通过了,OK,好的,正在处理 | 有效关键词 |
| invalid_keywords | 不知道,不清楚,等下再说,没空,无法处理 | 无效关键词 |

------

## 9. 业务状态机

### 9.1 线索状态流转

```text
pending（待分配）
    ↓ 分配销售
assigned（已分配）
    ↓ 有效回复           ↓ 超时
replied（已回复）    timeout（超时未回复）
```

说明：

- **pending**：线索已创建，等待分配
- **assigned**：已分配给销售，等待回复
- **replied**：检测到有效回复
- **timeout**：超过截止时间未回复

### 9.2 检测记录状态流转

```text
pending（等待回复）
    ↓ 有效回复           ↓ 无效回复           ↓ 超时
replied（已回复）   invalid（无效回复）   timeout（超时）
```

------

## 10. 有效回复判定规则

判定顺序：

1. 回复内容为空 → **无效**（原因：回复内容为空）
2. 命中无效关键词 → **无效**（原因：命中无效关键词: xxx）
3. 命中有效关键词 且 长度 ≥ 配置值 → **有效**
4. 命中有效关键词 但 长度 < 配置值 → **无效**
5. 未命中任何关键词 且 长度 ≥ 配置值 → **有效**（原因：默认有效）
6. 未命中任何关键词 且 长度 < 配置值 → **无效**

### 10.1 有效关键词

```text
收到、已添加、已联系、已通过、通过了、OK、好的、正在处理
```

### 10.2 无效关键词

```text
不知道、不清楚、等下再说、没空、无法处理
```

### 10.3 默认最小回复长度

2 个字符

> 以上规则均可通过 `check_configs` 表动态配置。

------

## 11. API 接口清单

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
| POST | `/replies/manual` | 手动录入回复 |
| POST | `/checks/run` | 手动触发一次回复检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |

------

## 12. 调用链

### 12.1 标准请求调用链

```text
API（routers/）
    ↓ Depends(get_db)
Service（services/）
    ↓ SQLAlchemy ORM
Database（SQLite）
```

### 12.2 线索分配调用链

```text
POST /leads/{id}/assign
    ↓
assign_service.assign_lead()
    ↓ 更新 douyin_leads 状态为 assigned
    ↓ 创建 reply_checks 记录（pending）
    ↓ 计算 reply_deadline
Database
```

### 12.3 回复录入调用链

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

### 12.4 超时检测调用链

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

------

## 13. 下一阶段开发方向

### 13.1 重点工作：微信 UI 图形自动化检测

采用方案：**Windows UI Automation**

不采用方案：
- ~~读取微信数据库~~
- ~~解密微信数据库~~

### 13.2 第一版范围

1. 人工打开微信 PC 客户端
2. 人工进入目标客户聊天窗口
3. 系统通过 UI Automation 读取当前聊天窗口最近消息
4. 检测销售是否发送有效回复
5. 同步更新 `reply_checks` 表
6. 同步更新 `douyin_leads` 表状态

### 13.3 暂不实现

- 自动搜索联系人
- 自动切换会话
- 自动发送消息
- AI 自动回复
- 企业微信支持

------

## 14. 当前阶段不关注

以下能力在当前阶段明确**不做**：

- AI 自动回复
- Agent
- RAG
- 自动发送消息
- 微信数据库读取/解密
- 企业微信 DLL 注入
- 小猫AI员工集成
- 权限系统
- 多租户
- 前端 UI

------

## 15. 重要约束

任何后续开发必须遵守：

1. **优先复用**现有 FastAPI、数据库、服务层代码
2. **禁止推翻**现有 MVP 重构
3. **禁止重新设计**数据库
4. **禁止引入**复杂架构
5. **遵循**先验证业务闭环，再接入真实微信，最后扩展 AI 能力

------

## 16. 开发原则

- 先做最小验证，不做大而全
- 优先跑通一条线索的完整检测链路
- 规则判断优先，AI 判断后置
- 先保证可解释，再追求自动化程度
- 所有外部软件交互都要封装，避免业务逻辑散落
- 每一步都要保留日志

------

## 17. 禁止事项

- 禁止反编译 `.pyd` 文件
- 禁止修改小猫AI员工安装目录
- 禁止把 MVP 写成完整 CRM
- 禁止一开始就接复杂大模型 Agent
- 禁止没有证据就输出确定性结论
- 禁止绕过微信/企业微信安全机制
- 禁止做骚扰、群发、自动营销能力
