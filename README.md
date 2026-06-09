# 抖音线索销售微信回复检测系统 MVP

## 项目定位

独立项目，实现"抖音线索 → 分配销售 → 微信回复检测 → 超时判断 → 报表统计"的 MVP 闭环。

**不依赖** 小猫AI员工的任何闭源 `.pyd` 模块。

## 技术栈

- Python 3.10+
- FastAPI + Uvicorn
- SQLAlchemy 2.x + SQLite
- Pydantic 2.x
- uiautomation（Windows UI 自动化）

## 快速开始

### 1. 安装依赖

```bash
cd E:\work\project\auto_wechat
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
python scripts/init_db.py
```

### 3. 插入演示数据

```bash
python scripts/seed_demo_data.py
```

### 4. 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```

打开浏览器访问: http://127.0.0.1:9000/docs 查看 API 文档。

### 5. 运行端到端演示

```bash
python scripts/run_demo_flow.py
```

### 6. 运行测试

```bash
python -m pytest tests/ -v
```

## API 接口一览

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
| POST | `/replies/current-wechat-detect` | **微信 UI 自动化检测当前聊天窗口回复** |
| POST | `/checks/run` | 手动触发超时检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |

## 微信 UI 自动化检测

### 使用方式

```bash
curl -X POST http://127.0.0.1:9000/replies/current-wechat-detect \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "staff_id": 1, "max_messages": 20}'
```

### 操作步骤

1. 打开微信 PC 客户端并登录
2. 手动进入目标客户的聊天窗口
3. 确保聊天窗口中有销售回复（如"收到，已添加微信"）
4. 调用 `/replies/current-wechat-detect` 接口
5. 系统读取当前聊天窗口最近消息，判断是否存在有效回复

### 检测逻辑

1. 定位微信窗口（标题 `Weixin`，类名 `mmui::MainWindow`）
2. 查找消息列表（`ListControl Name='消息'`）
3. 读取最近 N 条消息
4. 尝试通过头像位置判断发送方（右侧=self=销售，左侧=friend=客户）
5. **优先分析 self 消息**；若 self 消息为空，**启用兜底模式**分析所有非 system 文本消息
6. 使用关键词 + 长度判断有效性
7. 有效回复时更新 `reply_checks` 和 `douyin_leads` 状态

### 检测模式说明

| 模式 | 说明 |
|------|------|
| `self_only` | 成功区分 self/friend，只分析 self 消息（精确模式） |
| `fallback_current_window_text` | 无法区分发送方，基于业务前提分析所有非 system 文本消息（兜底模式） |

兜底模式的前提：当前电脑登录的是销售微信，且已打开目标客户聊天窗口。
在此前提下，窗口中的有效回复文本可作为销售已处理线索的 MVP 证据。

### ⚠️ 当前限制（必须了解）

1. **仅支持 Windows** 10/11
2. **当前电脑登录的微信账号必须就是对应销售人员的账号**
3. **需要人工先打开目标客户的聊天窗口**
4. 第一版**不搜索联系人**
5. 第一版**不切换会话**
6. 第一版**不自动发送消息**
7. **微信 UI 结构可能随版本变化失效**
8. 当前能力**只用于 MVP 验证**，非生产级别
9. 依赖 `uiautomation` 库（Windows UI Automation 的 Python 封装）
10. **当前微信版本无法通过 UI 控件区分 self/friend 发送方**，MVP 使用窗口文本兜底检测
11. 兜底模式下，聊天窗口中**所有非 system 文本**都参与分析，**可能包含客户发送的内容**，仅限 MVP 场景使用

## 项目结构

```
auto_wechat/
├── app/
│   ├── main.py                      # FastAPI 入口
│   ├── config.py                    # 配置
│   ├── database.py                  # 数据库连接
│   ├── models.py                    # ORM 模型（4张表）
│   ├── schemas.py                   # Pydantic 模型
│   ├── routers/                     # API 路由
│   │   ├── staff.py                 #   销售管理
│   │   ├── leads.py                 #   线索管理
│   │   ├── replies.py               #   回复管理（手动 + 微信UI检测）
│   │   ├── checks.py                #   超时检测
│   │   └── reports.py               #   报表统计
│   ├── services/                    # 业务逻辑
│   │   ├── staff_service.py         #   销售服务
│   │   ├── lead_service.py          #   线索服务
│   │   ├── assign_service.py        #   分配服务
│   │   ├── reply_analyzer.py        #   回复有效性分析
│   │   ├── reply_checker.py         #   回复检测（手动 + 超时）
│   │   ├── wechat_ui_reply_service.py # 微信UI检测编排
│   │   └── report_service.py        #   报表服务
│   ├── wechat_ui/                   # 微信 UI 自动化（与业务解耦）
│   │   ├── exceptions.py            #   UI 异常定义
│   │   ├── window_locator.py        #   微信窗口定位
│   │   ├── current_chat_reader.py   #   当前聊天消息读取
│   │   ├── message_parser.py        #   消息解析（发送方+内容）
│   │   └── reply_detector.py        #   销售有效回复检测
│   └── scheduler/
│       └── check_scheduler.py       # 定时超时检测调度器
├── scripts/
│   ├── init_db.py                   # 初始化数据库
│   ├── seed_demo_data.py            # 插入演示数据
│   └── run_demo_flow.py             # 端到端演示
├── tests/
│   └── test_demo_flow.py            # 自动化测试
├── data/
│   └── auto_wechat.db               # SQLite 数据库（运行后生成）
├── requirements.txt
├── .gitignore
└── README.md
```

## 数据库表结构

- **sales_staff** — 销售人员（姓名、微信号、状态）
- **douyin_leads** — 抖音线索（来源、内容、分配状态）
- **reply_checks** — 回复检测记录（截止时间、回复内容、有效性判定）
- **check_configs** — 检测配置（回复时限、关键词等）

## 业务规则

1. 线索创建 → 状态 `pending`
2. 线索分配 → 状态 `assigned`，同时生成 `reply_checks` 记录
3. 销售通过 `/replies/manual` 手动录入回复
4. 或通过 `/replies/current-wechat-detect` 自动检测微信聊天窗口
5. 回复命中有效关键词且长度达标 → 有效 → 状态 `replied`
6. 回复命中无效关键词 → 无效
7. 超过截止时间未回复 → 超时 → 状态 `timeout`
