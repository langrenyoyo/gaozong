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
| GET | `/replies/debug/windows` | 调试：列出所有疑似微信窗口 |
| GET | `/replies/debug/messages` | 调试：返回消息原始控件结构 |
| GET | `/replies/debug/raw-tree` | P2.5 实验：UIA 深层控件树探测 |
| POST | `/replies/debug/sender-experiment` | P2.5 实验：发送方识别方案验证 |
| POST | `/feedback/compose` | **生成反馈文本（主机微信 B → 数据源微信 A）** |
| POST | `/feedback/send-current-chat` | **将反馈文本写入当前微信聊天窗口** |
| GET | `/feedback/records` | 查询反馈发送记录 |
| GET | `/feedback/debug/current-chat` | 调试：探测当前聊天窗口标题、候选控件、输入框状态 |
| POST | `/checks/run` | 手动触发超时检测 |
| GET | `/checks` | 查看检测记录 |
| GET | `/reports/summary` | 汇总报表 |
| POST | `/integrations/douyin/sync-leads` | **P4：从 douyinAPI 拉取线索并同步（支持 dry_run 预览）** |
| POST | `/integrations/douyin/webhook` | **GMP 私信事件回调（内部/新路径入口，鉴权可配置）** |
| POST | `/webhook/douyin` | **GMP 私信事件回调（客户旧路径兼容入口，宝塔整站反代目标）** |

## 微信 UI 自动化检测

### 使用方式

```bash
# 基本调用
curl -X POST http://127.0.0.1:9000/replies/current-wechat-detect \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "staff_id": 1, "max_messages": 20}'

# 确认当前聊天窗口（降低 risk_level）
curl -X POST http://127.0.0.1:9000/replies/current-wechat-detect \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "staff_id": 1, "max_messages": 20, "confirm_current_chat": true}'
```

### 操作步骤

1. 打开微信 PC 客户端并登录（主机微信）
2. 手动进入目标客户的聊天窗口
3. 确保聊天窗口中有销售回复（如"收到，已添加微信"）
4. 调用 `/replies/current-wechat-detect` 接口
5. 系统读取当前聊天窗口最近消息，判断是否存在有效回复

### 检测逻辑

1. 定位微信窗口（标题 `Weixin`，类名 `mmui::MainWindow`）
2. 查找消息列表（`ListControl Name='消息'`）
3. 读取最近 N 条消息
4. 尝试通过头像位置判断发送方（右侧=self=主机微信，左侧=friend=销售）
5. **优先分析 friend 消息**（销售回复）；若无法区分发送方，**启用兜底模式**分析所有非 system 文本消息
6. 匹配优先级：**期望回复文本**（`expected_reply_text`）→ **有效关键词** → 长度
7. 兜底模式下必须命中期望回复文本或有效关键词，不允许仅靠长度判有效
8. 有效回复时更新 `reply_checks` 和 `douyin_leads` 状态

### 检测模式说明

| 模式 | 说明 |
|------|------|
| `self_only` | 成功区分 self/friend，只分析 friend 消息（即销售回复，精确模式） |
| `fallback_current_window_text` | 无法区分发送方，基于业务前提分析所有非 system 文本消息（兜底模式，必须命中关键词） |

兜底模式的前提：当前电脑登录的是**主机微信**，且已打开目标客户聊天窗口。
在此前提下，窗口中的有效回复文本可作为销售已处理线索的 MVP 证据。
**兜底模式结果建议人工复核**（接口返回 `confirmed_required = true`）。

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `lead_id` | int | 是 | 线索 ID |
| `staff_id` | int | 是 | 销售 ID |
| `max_messages` | int | 否 | 最多读取消息条数（默认 20） |
| `confirm_current_chat` | bool | 否 | 确认当前微信窗口已打开目标销售聊天窗口（默认 false） |

### risk_level 可信度

| 值 | 含义 |
|----|------|
| `low` | 精确模式（self_only）检测到有效回复 |
| `medium` | 兜底模式检测到有效回复，且 `confirm_current_chat=true` |
| `high` | 兜底模式检测到有效回复，且 `confirm_current_chat=false`（**建议人工确认**） |
| `none` | 未检测到有效回复或检测失败 |

### 可配置项

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `expected_reply_text` | 收到，已添加微信\|收到，已添加\|已添加微信 | 期望回复文本（`\|` 分隔多值），优先精确/包含匹配 |
| `effective_keywords` | 收到,已添加,已联系,... | 有效关键词列表 |
| `invalid_keywords` | 不知道,不清楚,... | 无效关键词列表 |
| `reply_deadline_minutes` | 30 | 回复截止时间（分钟） |
| `effective_reply_min_length` | 2 | 有效回复最小长度 |

> 以上配置存储在 `check_configs` 表中，可通过数据库动态修改，无需改代码。

### ⚠️ 当前限制（必须了解）

1. **仅支持 Windows** 10/11
2. **当前电脑登录的是主机微信**（不是销售微信）
3. **需要人工先打开目标客户的聊天窗口**
4. 第一版**不搜索联系人**
5. 第一版**不切换会话**
6. 第一版**不自动发送消息**
7. **微信 UI 结构可能随版本变化失效**
8. 当前能力**只用于 MVP 验证**，非生产级别
9. 依赖 `uiautomation` 库（Windows UI Automation 的 Python 封装）
10. **当前微信版本无法通过 UI 控件区分 self/friend 发送方**（P2.5 实验证实：`ListItemControl` child_count=0，无头像/气泡子控件），MVP 使用窗口文本兜底检测
11. 兜底模式下，聊天窗口中**所有非 system 文本**都参与分析，**可能包含主机或客户发送的内容**，仅限 MVP 场景使用
12. `confirmed_required` 和 `risk_level` 为检测响应字段，**暂不落库**，无法通过报表永久统计

### P2.5 发送方精确识别实验结论

| 方向 | 结论 | 说明 |
|------|------|------|
| UIA 深层控件树 | ❌ 不可行 | `GetChildren()` / `WalkControl()` / `FindAll()` 均无子孙控件 |
| ControlFromPoint | ❌ 不可行 | 左/中/右采样均命中 ListItemControl 自身 |
| 截图 + 像素分析 | ⚠️ 后续预研 | 理论可行，但不进入当前主线 |

**正式方案**：保持 `fallback_current_window_text` + `strict_mode` 作为 MVP 检测方案。

详细实验报告见 [docs/experiment_report_sender_identification.md](docs/experiment_report_sender_identification.md)。

## 反馈发送（P3：主机微信 B → 数据源微信 A）

### 使用方式

```bash
# 第一步：生成反馈文本（dry_run 预览）
curl -X POST http://127.0.0.1:9000/feedback/compose \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "dry_run": true}'

# 第二步：确认后生成并入库
curl -X POST http://127.0.0.1:9000/feedback/compose \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "dry_run": false, "require_confirm": true}'

# 第三步：写入当前微信聊天窗口（require_confirm=true 只粘贴不发送）
curl -X POST http://127.0.0.1:9000/feedback/send-current-chat \
  -H "Content-Type: application/json" \
  -d '{"record_id": 1, "require_confirm": true, "confirm_chat_title": "数据源A"}'

# 查询反馈记录
curl http://127.0.0.1:9000/feedback/records
```

### 操作步骤

1. 确认销售已有效回复（线索状态为 `replied`）
2. 人工打开微信中**数据源微信 A** 的聊天窗口
3. 调用 `/feedback/compose` 生成反馈文本
4. 确认文本内容无误后，调用 `/feedback/send-current-chat` 写入输入框
5. `require_confirm=true`（默认）：文本粘贴到输入框，人工目视确认后手动回车发送
6. `require_confirm=false`：粘贴后自动回车发送（**高风险**）

### send-current-chat 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `record_id` | int | 是 | 反馈记录 ID（由 compose 返回） |
| `require_confirm` | bool | 否 | 只粘贴不回车（默认 true） |
| `confirm_chat_title` | string | 否 | 预期聊天窗口标题，不匹配则拒绝写入（防误发） |

### 安全机制

- **`require_confirm=true`（默认）**：文本只粘贴到输入框，**不自动回车**，需人工确认后手动发送
- **`require_confirm=false`**：粘贴后自动回车发送，**高风险，建议仅在可信环境使用**
- **`confirm_chat_title`**：校验当前聊天窗口标题是否匹配，不匹配则拒绝写入，防止发错窗口
- **状态校验**：只有 `composed` 状态的记录才能发送，避免重复发送
- **标题获取失败时**的行为：
  - 传了 `confirm_chat_title` 但标题获取失败 → **拒绝写入**
  - 未传 `confirm_chat_title` + `require_confirm=true` + 标题获取失败 → **允许粘贴**，但返回 warning 提醒人工确认窗口
  - 未传 `confirm_chat_title` + `require_confirm=false` + 标题获取失败 → **拒绝自动发送**

### 调试标题获取

如果 `send-current-chat` 返回标题为 null，可用调试接口排查：

```bash
curl http://127.0.0.1:9000/feedback/debug/current-chat
```

返回 `title`（探测到的标题）、`candidate_titles`（所有候选控件）、`message_list_found`、`input_box_found`。

### 默认反馈模板

```text
线索已跟进：
客户：{customer_name}
销售：{staff_name}
回复：{reply_content}
时间：{actual_reply_at}
```

> 模板可通过 `check_configs` 表的 `feedback_template` 配置动态修改。

## douyinAPI 线索同步（P4：上游线索对接）

### 使用方式

```bash
# 第一步：预览（dry_run=true，不写库）
curl -X POST http://127.0.0.1:9000/integrations/douyin/sync-leads \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "limit": 50, "lead_status": "pending"}'

# 第二步：确认后执行写库
curl -X POST http://127.0.0.1:9000/integrations/douyin/sync-leads \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false, "limit": 50, "lead_status": "pending"}'
```

### 请求参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dry_run` | bool | `true` | 预览模式（不写库）；设为 `false` 执行写库 |
| `limit` | int | 50 | 拉取数量上限（1-200） |
| `lead_status` | string | `"pending"` | 过滤线索状态 |
| `start_time` | int | null | 起始时间（毫秒时间戳） |
| `auto_assign` | bool | `false` | 自动分配（**P4-3 已支持**，仅新建线索触发） |

### 同步规则

| 场景 | 条件 | 动作 |
|------|------|------|
| 新建 | 本地不存在该 `source_id` | 创建 `DouyinLead`（status=pending） |
| 更新 | 本地存在且 `status=pending` | 更新 `customer_name`/`content`/`customer_contact`/`lead_type`/`raw_data` |
| 跳过 | 本地存在且 `status≠pending`（assigned/replied/timeout/closed） | 不覆盖 |

> **安全约束**：update 时不会修改 `id`、`source`、`source_id`、`assigned_staff_id`、`assigned_at`、`status`。

### 自动分配规则（auto_assign=true）

| 条件 | 行为 |
|------|------|
| 新建线索（create） | 自动调用 `assign_service.auto_assign_next()` 分配给当前负载最低的活跃销售 |
| 已存在 pending（update） | 不触发自动分配 |
| 已存在非 pending（skip） | 不触发自动分配 |
| 无活跃销售 | 线索保持 `pending`，reason 标记 `no_active_staff` |
| 分配异常 | 线索保持 `pending`，reason 标记 `assign_failed`，不影响其他线索 |
| dry_run=true | 不执行分配，reason 标记 `dry_run 未执行自动分配` |

### 字段映射

| douyinAPI 字段 | auto_wechat 字段 | 说明 |
|----------------|-----------------|------|
| `open_id` | `source_id` | 抖音用户唯一标识 |
| `display_name` | `customer_name` | 空值用"未命名客户" |
| `last_interaction_record` | `content` | 空值用空字符串 |
| `phone` | `customer_contact` | 可为 null |
| `lead_type` | `lead_type` | 空值用"私信" |
| 固定 `"douyin"` | `source` | 来源平台 |

### 前置条件

douyinAPI 开发容器需先启动：

```bash
cd E:\work\project\douyinAPI
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d --build
```

详见 [douyinAPI/README_DEV.md](../douyinAPI/README_DEV.md)。

## 抖音 GMP Webhook 直连接入

auto_wechat 可直接接收抖音/GMP 私信事件回调，不再强依赖 douyinAPI 中间层。

### 当前链路

```text
抖音平台 / GMP 私信事件
    ↓
https://callback.misanduo.com/webhook/douyin
    ↓
宝塔整站反代（callback.misanduo.com → http://127.0.0.1:9000）
    ↓
http://127.0.0.1:9000/webhook/douyin
    ↓
auto_wechat → douyin_webhook_events + DouyinLead
```

### 双入口

| 路径 | 角色 |
|------|------|
| `POST /webhook/douyin` | 客户旧路径兼容入口（GMP 实际推送目标） |
| `POST /integrations/douyin/webhook` | 内部/新路径入口（联调测试用） |

两个入口复用同一处理函数，行为完全一致。

### 正式 callback_url（保持不变）

```text
https://callback.misanduo.com/webhook/douyin
```

禁止改为 `/integrations/douyin/webhook`、`douyinapi.misanduo.com`、`127.0.0.1:9000` 等地址。

### 鉴权策略

```env
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

| 值 | 含义 |
|----|------|
| `false`（默认） | 入站 webhook 不强制签名校验，符合 GMP 私信事件回调业务确认 |
| `true` | 启用 `X-Auth-Timestamp` + `Authorization` 签名校验（调试/审计用） |

**关键约束**：

- GMP 文档鉴权章节适用于外部系统主动调用 GMP OpenAPI，**不适用**于 GMP 推送 callback_url 的入站 webhook
- 不允许默认改回强制鉴权
- `verify_signature` 逻辑保留，通过开关控制

### 事件处理规则

| 事件类型 | 行为 |
|----------|------|
| `im_receive_msg` | 创建/更新 DouyinLead |
| `im_send_msg` | 记录事件，不创建线索 |
| `im_enter_direct_msg` | 记录事件，不创建线索 |
| 重复事件 | event_key 幂等去重，不重复创建线索 |

> 详见 [docs/ai/P1_END_2_WEBHOOK_ACCEPTANCE.md](docs/ai/P1_END_2_WEBHOOK_ACCEPTANCE.md)。

## 项目结构

```
auto_wechat/
├── app/
│   ├── main.py                      # FastAPI 入口
│   ├── config.py                    # 配置
│   ├── database.py                  # 数据库连接
│   ├── models.py                    # ORM 模型（5张表）
│   ├── schemas.py                   # Pydantic 模型
│   ├── routers/                     # API 路由
│   │   ├── staff.py                 #   销售管理
│   │   ├── leads.py                 #   线索管理
│   │   ├── replies.py               #   回复管理（手动 + 微信UI检测）
│   │   ├── feedback.py              #   反馈管理（P3：主机→数据源）
│   │   ├── integrations.py          #   外部系统集成（P4：douyinAPI 同步）
│   │   ├── checks.py                #   超时检测
│   │   └── reports.py               #   报表统计
│   ├── integrations/                # 外部系统集成
│   │   └── douyin_api_client.py     #   douyinAPI HTTP 客户端（只读）
│   ├── services/                    # 业务逻辑
│   │   ├── staff_service.py         #   销售服务
│   │   ├── lead_service.py          #   线索服务
│   │   ├── assign_service.py        #   分配服务
│   │   ├── reply_analyzer.py        #   回复有效性分析
│   │   ├── reply_checker.py         #   回复检测（手动 + 超时）
│   │   ├── douyin_sync_service.py   #   P4 douyinAPI 线索同步服务
│   │   ├── wechat_ui_reply_service.py # 微信UI检测编排
│   │   ├── feedback_service.py        #   反馈文本生成+发送服务
│   │   └── report_service.py        #   报表服务
│   ├── wechat_ui/                   # 微信 UI 自动化（与业务解耦）
│   │   ├── exceptions.py            #   UI 异常定义
│   │   ├── window_locator.py        #   微信窗口定位
│   │   ├── current_chat_reader.py   #   当前聊天消息读取
│   │   ├── message_parser.py        #   消息解析（发送方+内容）
│   │   ├── reply_detector.py        #   销售有效回复检测
│   │   └── input_writer.py          #   P3: 微信输入框写入
│   └── scheduler/
│       └── check_scheduler.py       # 定时超时检测调度器
├── scripts/
│   ├── init_db.py                   # 初始化数据库
│   ├── seed_demo_data.py            # 插入演示数据
│   ├── run_demo_flow.py             # 端到端演示
│   ├── debug_wechat_raw_tree.py     # P2.5: UIA 深层控件树探测
│   └── debug_wechat_screenshot.py   # P2.5: 截图 + 像素分析
├── tests/
│   ├── test_demo_flow.py            # 端到端自动化测试
│   └── test_douyin_sync.py          # P4 douyinAPI 同步测试
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
- **feedback_records** — 反馈发送记录（P3：主机微信 B 向数据源微信 A 的反馈，可追溯）

## 业务规则

1. 线索创建 → 状态 `pending`
2. 线索分配 → 状态 `assigned`，同时生成 `reply_checks` 记录
3. 销售通过 `/replies/manual` 手动录入回复
4. 或通过 `/replies/current-wechat-detect` 自动检测微信聊天窗口
5. 回复命中有效关键词且长度达标 → 有效 → 状态 `replied`
6. 回复命中无效关键词 → 无效
7. 超过截止时间未回复 → 超时 → 状态 `timeout`
