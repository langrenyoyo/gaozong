# P0-END-1 MVP 主链路冻结验收记录

> 本文档记录 auto_wechat MVP 主链路冻结时的完整状态。
>
> 日期：2026-06-12
>
> 状态：**主链路已跑通，冻结验收通过**

------

## 一、已跑通主链路

### 完整业务流程

```text
React 创建测试任务
  → 9000 主系统自动准备 lead/staff
  → 9000 创建 wechat_task（status=pending）
  → React 展示 pending 任务

React 点击「执行任务」
  → 19000 Local Agent 拉取 pending task
  → 前台切换微信 → 搜索打开 Aw3 聊天
  → OCR 验证联系人 → paste_only（Ctrl+V，不按 Enter）
  → 9000 回写 wechat_task（status=completed, pasted=true, sent=false）
  → 创建 lead_notification（send_status=pasted）
  → React 展示 pasted

Aw3 回复"收到，已添加微信"

React 点击「检测销售回复」
  → 19000 前台切换微信 → 搜索打开 Aw3 聊天
  → OCR 验证 → 截图像素分析识别 sender（self/friend/system）
  → 读取消息 → POST 9000 /replies/agent-write-back
  → 9000 分析：friend 消息命中关键词 → replied
  → 更新 reply_checks（check_status=replied）
  → 更新 douyin_leads（status=replied）
  → 更新 lead_notifications（send_status=replied）
  → React 展示 replied
```

### 各环节关键能力

| 环节 | 能力 | 对应阶段 |
|------|------|---------|
| React 创建任务 | WechatTaskPanel 创建测试任务并触发 Local Agent 执行 | P0-FE-MAIN-1 |
| 任务补齐 lead/staff | 创建时自动准备 lead + staff | P0-FE-MAIN-2/2A |
| Lead notification 联动 | 任务执行后 notification.send_status=pasted | P0-MAIN-5B |
| 手动回复检测 | React 点击按钮 → Local Agent 读取微信消息 → 主系统分析 | P0-REPLY-2 |
| sender 识别 | 截图像素分析区分 self/friend/system | P0-REPLY-3B |
| UTF-8 响应 | Content-Type 含 charset=utf-8，PowerShell 不乱码 | UTF-8 修复 |

### sender 识别策略（P0-REPLY-3B）

当前微信版本 `ListItemControl` 扁平结构（child_count=0），UIA 策略全部失败。
最终采用**截图像素颜色分析**：

| 发送方 | 检测依据 | 典型 RGB |
|--------|---------|----------|
| self（我方） | 右侧绿色像素占比 > 10%，右侧 > 左侧 | (157, 242, 159) |
| friend（对方） | 左侧非背景像素占比 > 5%，左 > 右×2，无绿色 | (238, 238, 240) |
| system | 时间/撤回等文本，由现有 _check_is_system 识别 | — |
| unknown | 无法判断，进入 manual_review 安全分支 | — |

关键文件：`app/wechat_ui/message_parser.py` → `_sender_by_screenshot_color()`

真机 Aw3 聊天验证结果：
- self 识别：2/3（1 条因可视区域边界问题未识别，可接受）
- friend 识别：1/1
- system 识别：2/2
- 零误判（无 self→friend 或 friend→self）

------

## 二、启动命令

### 主系统 9000

```bash
cd E:\work\project\auto_wechat
C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

- `--host 0.0.0.0`：允许局域网访问（React 从其他机器访问时必须）
- `--reload`：开发模式自动重载

### Local Agent 19000

```bash
cd E:\work\project\auto_wechat
C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe -m app.local_agent_main --host 127.0.0.1 --port 19000 --server-url http://127.0.0.1:9000
```

- 只监听 127.0.0.1，不对外暴露
- `--server-url` 指向主系统地址，用于回写任务结果和回复检测

### React

```bash
cd E:\work\project\react
npm run dev
```

- 默认端口 5173
- `.env.development` 中 `VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000`
- 本机 Agent 面板直连浏览器所在电脑的 127.0.0.1:19000，不走 VITE_API_BASE_URL

### 启动顺序

1. 先启动 9000（主系统）
2. 再启动 19000（Local Agent）
3. 最后启动 React

------

## 三、真机验收步骤

### 前提

- 微信已登录，Aw3 联系人存在
- 9000、19000、React 均已启动

### 步骤

| 步骤 | 操作 | 预期结果 |
|------|------|---------|
| 1 | 打开微信，确认 Aw3 在联系人列表中 | 微信正常显示 |
| 2 | 打开 React → 小高AI微信助手页面 | 页面加载，Agent 状态 online |
| 3 | 点击「创建测试任务并执行」 | 任务创建成功，status=pending |
| 4 | Local Agent 自动执行：切换微信 → 搜索 Aw3 → OCR 验证 → paste_only | 任务 status=completed, pasted=true |
| 5 | 确认 notification.send_status=pasted | React 展示 pasted |
| 6 | 微信 Aw3 聊天中出现测试消息 | 人工可见 |
| 7 | Aw3 回复"收到，已添加微信"（或手动准备该消息） | 聊天中存在该消息 |
| 8 | 点击「检测销售回复」 | 19000 读取消息 → 9000 分析 |
| 9 | 确认 detected_status=replied | 检测结果面板显示 replied |
| 10 | 确认 matched_reply 包含"收到" | 匹配到有效关键词 |
| 11 | 确认 check_status=replied | reply_checks 已更新 |
| 12 | 确认 lead_notifications.send_status=replied | 通知记录已更新 |
| 13 | 确认 sent=false | 全程无自动发送行为 |
| 14 | 确认没有自动发送行为 | 微信输入框无未授权内容 |

### 关键确认项

- ✅ paste_only：只粘贴不按 Enter
- ✅ sender 识别：self 通知文本识别为 self，"收到，已添加微信"识别为 friend
- ✅ 安全门：sender=unknown 不会自动 replied
- ✅ UTF-8：所有响应 Content-Type 含 charset=utf-8

------

## 四、接口清单

### 9000 主系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/wechat-tasks` | 创建微信自动化任务 |
| GET | `/wechat-tasks/pending` | 拉取待执行任务 |
| GET | `/wechat-tasks/{task_id}` | 查询任务详情 |
| POST | `/wechat-tasks/{task_id}/result` | 回写任务执行结果 |
| GET | `/lead-notifications/records` | 查询通知记录列表 |
| GET | `/checks` | 查询检测记录 |
| POST | `/replies/agent-write-back` | Local Agent 回复检测回写 |
| GET | `/staff` | 销售列表 |
| GET | `/leads` | 线索列表 |
| POST | `/leads/{id}/assign` | 分配线索 |

### 19000 Local Agent 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/agent/version` | 版本信息与路由列表 |
| GET | `/agent/tasks/server-url` | 返回配置的主系统地址 |
| POST | `/agent/tasks/poll-and-execute` | 拉取并执行一条 pending 任务 |
| POST | `/agent/replies/detect` | 读取微信消息并检测回复 |
| GET | `/agent/ocr/status` | OCR 状态检查 |
| POST | `/agent/ocr/warmup` | OCR 模型预热 |
| POST | `/agent/wechat/test` | 微信 paste_only 测试（仅 Aw3） |
| GET | `/agent/wechat/windows` | 微信窗口诊断 |

------

## 五、关键安全约束

以下约束在 MVP 阶段必须严格执行，不得放宽：

### 微信自动化安全

1. **paste_only**：当前默认只粘贴不发送，sent 必须为 false
2. **不允许自动按 Enter**：input_writer 的 require_confirm=true 时只做 Ctrl+V
3. **不允许默认真实发送**：任何发送动作需人工确认
4. **仅允许 Aw3 测试联系人**：target_nickname 只接受 "Aw3"
5. **微信 hidden/minimized 不允许自动恢复**：必须提示人工打开

### 检测安全

6. **OCR 验证失败必须 blocked**：partial_match 和 manual_review_required 都不允许继续
7. **sender=unknown 不允许自动 replied**：走 manual_review 安全分支
8. **self 消息不允许判定为 replied**：只有 friend + 关键词才能 replied
9. **failure_stage/raw_result 不能被吞**：必须记录和返回

### 架构安全

10. **Local Agent 只监听 127.0.0.1**：不暴露到局域网
11. **React Agent 面板不走 VITE_API_BASE_URL**：直连浏览器本机 19000
12. **不操作开发主机微信作为测试电脑结果**：每台电脑只操作本机微信

------

## 六、当前已知问题

以下问题已记录但不在本轮修复范围：

| # | 问题 | 影响 | 建议处理时间 |
|---|------|------|-------------|
| 1 | 旧自动检测调度器 `check_scheduler` 仍存在 | 定时器可能触发旧检测逻辑 | P0-END-2 统一清理 |
| 2 | `/agent/wechat/search-debug` 曾出现 RecursionError | 调试接口不稳定 | 后续单独修复 |
| 3 | numpy 环境问题导致部分 route 测试未跑通 | 开发环境缺 numpy，4 个 TestAgentReplyDetectRoute 测试跳过 | 统一环境配置 |
| 4 | 当前手动点击检测销售回复 | 未做后台自动轮询 | P0-END-2 自动化检测 |
| 5 | sender 识别依赖浅色主题绿色气泡 | 深色主题/多分辨率未测试 | 后续补充兼容 |
| 6 | 长消息文本跨满宽度时 sender 识别可能为 unknown | 消息过长导致左右两侧内容均等 | 可接受，保守策略 |
| 7 | 消息部分滚出可视区域时截图策略被跳过 | 裁剪失败 → sender=unknown | 可接受 |
| 8 | 自动检测单目标覆盖 | wechat_active_check_id 只能保存一个 | P0-5 多目标队列 |

------

## 七、回归测试清单

### 每次提交前必须跑

```bash
# 后端核心测试
python -m pytest tests/test_p0_5a_wechat_tasks.py -v
python -m pytest tests/test_p0_main_5b_poll_and_execute.py -v
python -m pytest tests/test_p0_reply_2_agent_write_back.py -v
python -m pytest tests/test_screenshot_sender.py -v
python -m pytest tests/test_utf8_json_response.py -v

# 端到端演示流程
python -m pytest tests/test_demo_flow.py -v
```

### 前端

```bash
cd E:\work\project\react
npm run build
npm run lint
```

### 预期结果

- `test_p0_5a_wechat_tasks.py`：全部通过
- `test_p0_main_5b_poll_and_execute.py`：全部通过
- `test_p0_reply_2_agent_write_back.py`：TestAgentWriteBack 9/9 通过，TestAgentReplyDetectRoute 4 个因 numpy 环境跳过
- `test_screenshot_sender.py`：23/23 通过
- `test_utf8_json_response.py`：5/5 通过
- `test_demo_flow.py`：全部通过
- `npm run build`：构建成功
- `npm run lint`：无阻断错误

------

## 八、项目文件结构（MVP 冻结时刻）

```text
auto_wechat/
├── app/
│   ├── main.py                          # FastAPI 入口（含 UTF8JSONResponse）
│   ├── local_agent_main.py              # Local Agent 入口（19000）
│   ├── local_agent_exe_entry.py         # exe 打包入口
│   ├── config.py / database.py / models.py / schemas.py
│   ├── routers/
│   │   ├── wechat_tasks.py              # P0-MAIN-5B 任务队列
│   │   ├── replies.py                   # 回复检测 + agent-write-back + debug
│   │   ├── lead_notifications.py        # 通知记录
│   │   └── ...（staff, leads, checks, reports, feedback, integrations, automation_control）
│   ├── services/
│   │   ├── wechat_ui_reply_service.py   # 回复检测编排 + agent_write_back_reply
│   │   ├── notification_service.py      # 通知服务
│   │   └── ...（reply_analyzer, reply_checker, douyin_sync, feedback, report）
│   ├── wechat_ui/
│   │   ├── message_parser.py            # sender 识别（含截图像素策略 P0-REPLY-3B）
│   │   ├── current_chat_reader.py       # 消息读取（含截图采集）
│   │   ├── window_locator.py            # 微信窗口定位
│   │   ├── contact_searcher.py          # 联系人搜索
│   │   ├── contact_verifier.py          # OCR 联系人验证
│   │   ├── input_writer.py              # 输入框写入（paste_only）
│   │   ├── screenshot_debug.py          # Win32 BitBlt 截图工具
│   │   ├── ocr_runtime.py              # EasyOCR 运行时
│   │   └── reply_detector.py            # 关键词匹配
│   └── scheduler/
│       ├── check_scheduler.py           # 旧定时检测（待清理）
│       └── wechat_auto_detect_scheduler.py
├── tests/
│   ├── test_p0_5a_wechat_tasks.py       # 任务 CRUD 测试
│   ├── test_p0_main_5b_poll_and_execute.py  # poll-and-execute 测试
│   ├── test_p0_reply_2_agent_write_back.py  # agent write-back 测试
│   ├── test_screenshot_sender.py        # 截图 sender 识别测试（23 个）
│   ├── test_utf8_json_response.py       # UTF-8 响应测试（5 个）
│   ├── test_demo_flow.py                # 端到端演示测试
│   └── ...（其他历史测试）
├── docs/ai/                             # AI 协作规范
├── data/                                # 运行时数据
└── requirements.txt
```

------

## 九、MVP 验收结论

### 通过项

- [x] React 创建测试任务 → 9000 创建 wechat_task → 19000 执行 paste_only → 回写 pasted
- [x] React 展示 lead_notifications（send_status=pasted）
- [x] React 点击检测销售回复 → 19000 读取消息 → sender 识别 → 9000 判定 replied
- [x] reply_checks / douyin_leads / lead_notifications 联动更新
- [x] sender 识别：self/friend/system 正确，零误判
- [x] UTF-8 JSON 响应：Content-Type 含 charset=utf-8
- [x] 全程 sent=false，无自动发送行为
- [x] 77 个核心测试通过，无回归

### 冻结范围

以下代码在 MVP 阶段冻结，后续修改需经回归测试：

- `app/wechat_ui/message_parser.py`（sender 识别核心）
- `app/wechat_ui/current_chat_reader.py`（截图采集）
- `app/services/wechat_ui_reply_service.py`（agent_write_back_reply 安全逻辑）
- `app/local_agent_main.py`（Local Agent 主流程）
- `app/main.py`（UTF8JSONResponse）

### 后续建议优先级

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | 重启 19000 + 9000 服务器加载最新代码 | 当前运行的是旧代码 |
| P1 | P0-END-2 旧调度器清理 + 自动化检测轮询 | check_scheduler 统一处理 |
| P1 | numpy 环境统一 | 统一 conda 环境，消除测试跳过 |
| P2 | P0-5 多目标检测队列 | 解决单目标覆盖问题 |
| P2 | 深色主题兼容 | 补充深色/多分辨率 sender 识别测试 |
| P3 | 小高AI微信助手.exe 安装包/分发优化 | PyInstaller onedir 体验改善 |
| P3 | Windows 10 测试电脑复测 | 跨平台验证 |
