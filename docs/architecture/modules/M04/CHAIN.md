# M04 AI小高微信助手 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M04 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 微信自动化（Local Agent，19000「小高AI微信助手.exe」）：微信任务派发/claim/lease、UI 自动化发送、回复检测、日报生成与投递、自动化控制/紧急停止。
- **边界红线**：不读取微信数据库、不 DLL 注入、不协议逆向；只操作客户本机微信；默认监听 127.0.0.1:19000；真实发送必须经联系人验证/前台焦点/违禁词替换/人工接管/限频/失败回写/幂等/紧急停止 gate。
- "Local Agent"（19000 微信进程）≠ "智能体 Agent"（M03 LLM 客服配置）。

## 2. User Entrypoints
- 5173 前端「微信助手」：WechatAgent、DailyReports、WechatTaskPanel、LocalWechatAgentTestPanel。
- 本机 19000：小高AI微信助手.exe 面板（必须调用本机 127.0.0.1:19000，不走 VITE_API_BASE_URL）。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/wechat-assistant/`（WechatAgent、DailyReports、WechatTaskPanel、LocalWechatAgentTestPanel、api.ts）。
- 页面：WechatAgent、DailyReports。
- API clients：wechat、wechatTasks、wechatAutoDetect、dailyReports、automation、checks、localWechatAgent。
- 共享组件：WechatTaskPanel、LocalWechatAgentTestPanel。

## 4. Backend API Entrypoints
- 9000：`app/routers/wechat_tasks.py`（派单/回写）、`automation_control.py`（控制/紧急停止）、`replies.py`（回复检测回写）、`wechat_auto_detect.py`、`daily_reports.py`、`daily_report_deliveries.py`、`checks.py`。
- 19000（app/local_agent_main.py + local_agent_exe_entry.py）：~20 endpoint 的 Local Agent 主服务。
- phase12_test_launcher.py / local_agent_phase12_test.spec：DEV_ONLY 测试启动器。

## 5. Core Services
- 9000 services：wechat_task_service（claim/lease/token，P2 M04 closure 36fe68a）、reply_analyzer、reply_checker、wechat_ui_reply_service、daily_report_service/data/delivery/excel/job/storage、automation_control、hotkey_listener、desktop_overlay。
- 19000 UI 自动化：app/wechat_ui/（UI 自动化基座）、debug 脚本、easyocr 模型准备、local_agent.spec（exe 打包）。

## 6. Data Ownership
- 9000 库表：wechat_tasks（含 claim/lease/attempt token/uncertain，migration 0035 additive）、daily_reports、daily_report_deliveries、notification 派单结果。
- 被其他模块读写：M02 产生通知任务（lead_wechat_notify_eligibility）→ M04 消费发送并回写；M02 回访任务 → M04 发送。

## 7. Async / Worker Chain
- M02 通知/回访任务 → 9000 派单（wechat_tasks，atomic claim）→ 19000 拉取（claim_token）→ UI 自动化发送（gate 校验）→ 回写状态（CAS callback）→ uncertain 处理（lease 过期不 blind resend，at-most-once）。
- 日报：scheduler（PLATFORM-SCHED）→ daily_report_job_service → 聚合 → daily_report_delivery_service（claim/lease）→ 投递（文件/Excel，phase8b file attachment）。

## 8. External Dependencies
- 微信客户端（客户本机）：UI Automation / 视觉识别 / OCR（easyocr）；禁止数据库/注入/协议逆向。
- 19000：本机 HTTP 127.0.0.1（9000 不直操作微信；react 面板直连本机）。
- 定时调度：PLATFORM-SCHED 触发器。
- NewCarProject：权限（`auto_wechat:wechat` 等）。

## 9. Cross-Module Calls
- CALLS：M02（通知/回访任务消费并回写）、M01（违禁词替换复用 PLATFORM-GATE；客服回复结果写回）。
- PROVIDES：发送结果/失败原因回写（M02 消费）；日报数据来自 M02 报表。
- AUTHORIZES：经 PLATFORM-AUTH；发送 gate 经 PLATFORM-GATE。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:wechat`（工作台）、`auto_wechat:automation`（控制）等。
- 19000 鉴权：本地 token（lazy 生成，phase8b）；仅监听 127.0.0.1（0.0.0.0 禁止）。
- merchant 隔离：通知任务归属校验（PLATFORM-ISO）。

## 11. Compatibility Layer
- apps/wechat_assistant 旧子应用：COMPAT，META 被 capability_gateway 引用。
- 旧自动化控制路径（旧 gate 硬门禁）：已废止为真实发送 gate 体系（兼容字段保留）。

## 12. Legacy Candidates
- apps/wechat_assistant 内部旧逻辑：LEGACY 候选（登记 ≠ 可删除）。
- 旧 19000 独立 exe（萌猫微信助手命名）：禁止使用，正式名为小高AI微信助手.exe。

## 13. Known Unknowns
- U-005（与 M02 共用）：通知/回访真实发送端到端未在 staging 双 19000 复核（Gate2 为 HTTP 模拟）。
- 日报投递文件消息控件行为（phase8b probe）：部分未定论，见 probe_phase8b 脚本登记。
- 19000 在非开发主机（测试电脑/虚拟机）无源码可运行性：验收约束（不得要求 python 命令验收）。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：派单→claim→lease→token→回写→uncertain 全链路（at-most-once）；真实发送 gate（联系人验证/前台焦点/违禁词/人工接管/限频/幂等/紧急停止）；失败回写不伪造成功；日报生成→投递→文件附件；紧急停止即时生效；127.0.0.1 监听。G1 阶段不展开。
