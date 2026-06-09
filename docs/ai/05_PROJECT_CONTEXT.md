# 05_PROJECT_CONTEXT.md

> 本文档是 AI Coding Agent 的项目上下文。
>
> 优先级低于阅读规范，高于执行规范、测试规范、输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 1. 项目名称

抖音线索销售确认回复检测系统

## 2. 项目阶段

MVP 验证阶段（已完成后端闭环 + 微信 UI 读取模块）

## 3. 项目目标

**核心业务**：检测销售在收到抖音线索后，是否在规定时间内向**主机微信**发送了确认消息。

> **重要澄清**：本系统不是检测"销售是否回复客户微信"，而是检测"销售是否向主机微信回复了确认消息"。

### 3.1 主机微信的角色

- **主机微信**是一个专用微信号，由运营方统一管理。
- 主机微信用于接收销售处理线索后的确认消息。
- 所有销售的确认回复都发往主机微信（不是发给客户）。
- 系统通过读取主机微信的聊天消息来检测销售的确认动作。

### 3.2 当前 MVP 只做一件事

> **销售收到线索 → 向主机微信回复"收到 / 已添加微信" → 系统检测是否按时完成**

- **做**：检测销售 → 主机微信的确认回复
- **不做**：检测销售与客户之间的任何聊天内容

### 3.3 核心流程

```text
抖音线索产生
    ↓
小猫AI员工分配线索给销售
    ↓
记录线索分配时间
    ↓
销售添加客户微信
    ↓
销售向主机微信回复确认消息（"收到" / "已添加微信" / "收到，已添加微信"）
    ↓
系统读取主机微信窗口消息
    ↓
判断是否为指定销售的有效确认回复
    ↓
判断是否在超时时限内
    ↓
保存检测结果（PASS / TIMEOUT）
    ↓
输出报表
```

------

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
| uiautomation | 微信 PC 窗口 UI 控件读取 |
| threading | 定时任务调度（轻量后台线程） |

------

## 6. 当前 MVP 已完成

以下功能均已实现且通过测试：

- FastAPI 项目骨架（`app/main.py`）
- SQLite 数据库 + ORM 模型（4 张表）
- 销售人员管理（增删改查）
- 抖音线索管理（创建、查询、分配）
- 线索分配（手动分配 + 自动轮询分配）
- 手动回复录入（模拟销售确认）
- 回复有效性分析（关键词 + 长度规则）
- 超时检测（定时扫描 + 手动触发）
- 汇总报表（全局统计 + 分销售统计）
- 定时任务调度器（后台线程）
- 微信 UI 窗口定位（多策略容错）
- 微信消息列表读取
- 消息发送方识别（多策略级联 + 兜底模式）
- 消息内容提取（过滤非文本、时间、系统消息）
- 微信 UI 自动检测编排服务
- 调试诊断脚本（窗口探测 + 消息控件结构分析）
- 期望回复文本配置（`expected_reply_text`，优先精确/包含匹配）
- 兜底模式严格匹配（`strict_mode`，必须命中关键词或期望回复文本）
- 检测结果人工复核标记（`confirmed_required`，兜底模式时为 true）
- 检测结果警告信息（`warning`，兜底模式时提示需人工确认）
- Demo 数据脚本
- 端到端自动化测试（19 个用例）

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
│   │   ├── replies.py          #   手动回复 / 微信检测 API
│   │   ├── checks.py           #   回复检测 API
│   │   └── reports.py          #   报表统计 API
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── staff_service.py    #   销售服务
│   │   ├── lead_service.py     #   线索服务
│   │   ├── assign_service.py   #   分配服务
│   │   ├── reply_analyzer.py   #   回复有效性分析
│   │   ├── reply_checker.py    #   回复检测服务
│   │   ├── report_service.py   #   报表服务
│   │   └── wechat_ui_reply_service.py  # 微信 UI 自动检测编排
│   ├── wechat_ui/              # 微信 UI 自动化模块
│   │   ├── __init__.py
│   │   ├── window_locator.py   #   微信窗口定位（多策略）
│   │   ├── current_chat_reader.py  # 当前聊天消息读取
│   │   ├── message_parser.py   #   发送方识别 + 内容提取
│   │   ├── reply_detector.py   #   销售确认回复检测
│   │   └── exceptions.py       #   UI 异常定义
│   └── scheduler/
│       ├── __init__.py
│       └── check_scheduler.py  # 定时检测调度器
├── scripts/
│   ├── init_db.py              # 初始化数据库
│   ├── seed_demo_data.py       # 插入演示数据
│   ├── run_demo_flow.py        # 端到端演示脚本
│   ├── debug_windows.py        # 窗口探测诊断脚本
│   └── debug_wechat_messages.py # 消息控件结构诊断脚本
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
| wechat_id | String(100) | 销售微信号（用于匹配主机微信中的发送方） |
| wechat_nickname | String(100) | 销售微信昵称 |
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
| assigned_at | DateTime | 分配时间（超时计算的起点） |
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
| reply_deadline | DateTime | 要求回复截止时间（assigned_at + reply_timeout_minutes） |
| actual_reply_at | DateTime | 实际确认回复时间（从主机微信读取） |
| reply_content | Text | 销售发送的确认消息内容 |
| is_effective | Integer | 是否有效确认：0 / 1 |
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
| reply_deadline_minutes | 30 | 确认回复截止时间（分钟），销售收到线索后需在此时间内向主机微信确认 |
| check_interval_minutes | 5 | 定时检测间隔（分钟） |
| effective_reply_min_length | 2 | 有效回复最小长度 |
| effective_keywords | 收到,已添加微信,已添加 | 有效确认关键词 |
| invalid_keywords | 不知道,不清楚,等下再说,没空,无法处理 | 无效关键词 |
| expected_reply_text | 收到，已添加微信 | 期望回复文本，优先精确/包含匹配 |

------

## 9. 业务状态机

### 9.1 线索状态流转

```text
pending（待分配）
    ↓ 分配销售
assigned（已分配，等待销售确认）
    ↓ 销售向主机微信发送有效确认      ↓ 超时未确认
replied（已确认）               timeout（超时未确认）
```

说明：

- **pending**：线索已创建，等待分配给销售
- **assigned**：已分配给销售，等待销售向主机微信回复确认
- **replied**：在主机微信中检测到销售的有效确认消息
- **timeout**：超过截止时间，主机微信中仍未检测到销售的有效确认消息

### 9.2 检测记录状态流转

```text
pending（等待销售确认）
    ↓ 检测到有效确认         ↓ 检测到无效回复         ↓ 超时
replied（已确认）       invalid（无效回复）     timeout（超时）
```

------

## 10. 有效确认回复判定规则

### 10.1 业务定义

销售收到线索后，需要向主机微信发送确认消息。**有效确认消息**必须包含以下关键词之一：

| 有效确认关键词 | 含义 |
|----------------|------|
| `收到` | 销售确认已收到线索 |
| `已添加微信` | 销售确认已添加客户微信 |
| `收到，已添加微信` | 销售确认既收到线索又添加了客户微信 |

### 10.2 允许的格式差异

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

### 10.3 判定规则

判定顺序（优先级从高到低）：

1. 回复内容为空 → **无效**
2. 命中无效关键词（如"不知道"、"没空"等）→ **无效**
3. 精确匹配 `expected_reply_text` → **有效**
4. 包含 `expected_reply_text` → **有效**
5. 命中有效确认关键词 且 长度 ≥ 配置值 → **有效**
6. 命中有效确认关键词 但 长度 < 配置值 → **无效**
7. 兜底模式（`strict_mode=True`）时：到此为止 → **无效**
8. 精确模式（`strict_mode=False`）时：未命中关键词 但 长度 ≥ 配置值 → **有效**（默认有效）
9. 未命中任何关键词 且 长度 < 配置值 → **无效**

> 以上规则均可通过 `check_configs` 表动态配置，无需改代码。
>
> 兜底模式下 `strict_mode=True`，必须命中 `expected_reply_text` 或有效关键词才算有效。

### 10.4 超时规则

配置项：`reply_deadline_minutes`（默认 30 分钟）

```text
截止时间 = 线索分配时间（assigned_at）+ reply_timeout_minutes

示例：
  线索 14:00 分配给销售A
  reply_timeout_minutes = 10
  → 销售A 必须在 14:10 前向主机微信发送有效确认消息
  → 14:10 后仍未检测到 → 标记为 timeout
```

------

## 11. 微信 UI 检测核心逻辑

### 11.1 检测目标

系统读取的是**主机微信**窗口的消息，不是客户的微信。

检测链路：

```text
定位主机微信窗口
    ↓
定位当前聊天消息列表
    ↓
读取最近 N 条消息
    ↓
识别每条消息的发送方（区分"自己发的"和"别人发的"）
    ↓
筛选出销售发送的消息（通过发送方识别 + 销售身份匹配）
    ↓
检查消息内容是否命中有效确认关键词
    ↓
检查消息时间是否在超时时限内
    ↓
判定结果：PASS（有效确认）或 TIMEOUT（超时）
    ↓
结果落库（更新 reply_checks + douyin_leads）
```

### 11.2 窗口定位策略（多策略容错）

文件：`app/wechat_ui/window_locator.py`

| 策略 | 方法 | 说明 |
|------|------|------|
| 策略 1 | `ctypes.FindWindowW` | 按窗口标题精确查找（"Weixin"、"微信"、"WeChat"） |
| 策略 2 | Desktop 遍历 | 遍历所有顶层窗口，按 `ClassName` 模糊匹配 |
| 策略 3 | 多候选排序 | 优先选择有消息列表控件、非离屏、面积最大的 |

### 11.3 发送方识别（多策略级联）

文件：`app/wechat_ui/message_parser.py`

| 优先级 | 策略 | 原理 |
|--------|------|------|
| 1 | 系统消息过滤 | 时间分割线、系统提示 → 标记为 `system` |
| 2 | **消息气泡位置（主力）** | 自己发的消息靠右，对方消息靠左（边缘距离阈值 80px） |
| 3 | 头像控件位置 | `ButtonControl`/`ImageControl` 头像在中线左/右侧 |
| 4 | 文本位置辅助 | `TextControl` 的中心 X 坐标偏向判断 |
| 5 | 兜底 `unknown` | 记录调试日志，便于后续优化 |

### 11.4 兜底机制

当 UI 无法区分发送方时（`self` 消息数为 0），启用**兜底模式**：

> 业务前提：当前窗口就是主机微信 + 销售聊天窗口

兜底模式下，将所有非系统消息、有文本内容的消息作为候选分析对象，确保不遗漏。

兜底模式安全护栏：
- `strict_mode=True`：必须命中 `expected_reply_text` 或有效关键词才算有效，不允许仅靠长度判有效
- `warning`：返回警告信息，提示"当前无法区分发送方，建议人工确认"
- `confirmed_required=true`：标记检测结果需要人工复核

### 11.5 核心前提

> 当前电脑登录的微信账号就是主机微信。因此 `self`（自己发的）消息是主机微信发的，`friend`（对方发的）消息才是销售发的。

**销售的确认消息在主机微信中表现为"对方发的消息"（`friend`）。**

------

## 12. API 接口清单

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
| POST | `/replies/current-wechat-detect` | 通过主机微信 UI 自动检测当前聊天窗口的销售确认回复 |
| GET | `/replies/debug/windows` | 调试：列出所有疑似微信窗口 |
| POST | `/checks/run` | 手动触发一次超时检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |
| GET | `/replies/debug/messages` | 调试：返回消息控件结构 |

### 12.1 WechatDetectResponse 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 检测是否成功执行 |
| message | str | 检测结果描述 |
| chat_title | str? | 当前聊天窗口标题 |
| messages_read | int | 读取到的消息总数 |
| self_messages_count | int | sender=self 的消息数 |
| detection_mode | str? | 检测模式：`self_only` / `fallback_current_window_text` |
| warning | str? | 兜底模式时返回警告信息 |
| confirmed_required | bool | 是否需要人工复核（兜底模式时为 true） |
| is_effective | int | 是否有效回复 0/1 |
| effectiveness_reason | str? | 判定原因 |
| matched_content | str? | 匹配到的有效回复内容 |
| check_status | str | 检测状态 |

------

## 13. 调用链

### 13.1 标准请求调用链

```text
API（routers/）
    ↓ Depends(get_db)
Service（services/）
    ↓ SQLAlchemy ORM
Database（SQLite）
```

### 13.2 线索分配调用链

```text
POST /leads/{id}/assign
    ↓
assign_service.assign_lead()
    ↓ 更新 douyin_leads 状态为 assigned，记录 assigned_at
    ↓ 创建 reply_checks 记录（pending）
    ↓ 计算 reply_deadline = assigned_at + reply_timeout_minutes
Database
```

### 13.3 手动确认录入调用链

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

### 13.4 微信 UI 自动检测调用链

```text
POST /replies/current-wechat-detect
    ↓
wechat_ui_reply_service.detect_reply_from_wechat()
    ↓ window_locator.find_wechat_window()        定位主机微信窗口
    ↓ current_chat_reader.read_recent_messages()  读取主机微信消息
    ↓ reply_detector.find_self_messages()          筛选销售发送的消息
    ↓ reply_detector.find_effective_reply()        关键词匹配 + 超时判断
    ↓ _update_check_as_replied()                   更新 reply_checks + douyin_leads
Database
```

### 13.5 超时检测调用链

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

## 14. MVP 成功标准

### 14.1 PASS 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  主机微信在 14:00 ~ 14:10 期间收到了销售A发送的"收到，已添加微信"

预期结果：
  检测结果 = PASS
  reply_checks.check_status = "replied"
  reply_checks.is_effective = 1
  douyin_leads.status = "replied"
```

### 14.2 TIMEOUT 场景

```text
给定：
  sales_id = 销售A
  assigned_time = 14:00
  reply_timeout_minutes = 10

条件：
  14:10 后主机微信仍未收到销售A的有效确认消息

预期结果：
  检测结果 = TIMEOUT
  reply_checks.check_status = "timeout"
  douyin_leads.status = "timeout"
```

------

## 15. 当前阶段不关注

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
- 自动发送消息
- 微信数据库读取/解密
- 企业微信 DLL 注入
- 小猫AI员工集成
- 权限系统
- 多租户
- 前端 UI

------

## 16. 重要约束

任何后续开发必须遵守：

1. **优先复用**现有 FastAPI、数据库、服务层代码
2. **禁止推翻**现有 MVP 重构
3. **禁止重新设计**数据库
4. **禁止引入**复杂架构
5. **遵循**先验证业务闭环，再接入真实微信，最后扩展 AI 能力

------

## 17. 开发原则

- 先做最小验证，不做大而全
- 优先跑通一条线索的完整检测链路
- 规则判断优先，AI 判断后置
- 先保证可解释，再追求自动化程度
- 所有外部软件交互都要封装，避免业务逻辑散落
- 每一步都要保留日志

------

## 18. 禁止事项

- 禁止反编译 `.pyd` 文件
- 禁止修改小猫AI员工安装目录
- 禁止把 MVP 写成完整 CRM
- 禁止一开始就接复杂大模型 Agent
- 禁止没有证据就输出确定性结论
- 禁止绕过微信/企业微信安全机制
- 禁止做骚扰、群发、自动营销能力
