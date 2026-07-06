# P0-LOCAL-AGENT-FRONTEND-CAPABILITY-REVIEW-1

任务名：P0-LOCAL-AGENT-FRONTEND-CAPABILITY-REVIEW-1

核对日期：2026-06-22

核对范围：前端“小高AI微信助手”相关页面/API/组件、9000 主后端 Local Agent 与任务接口、19000 Local Agent 源码能力、打包脚本与测试覆盖。

本轮边界：先完成代码、接口、文档级核对；随后按确认后的最小补齐方案修复构建前阻塞缺口，并在用户确认后进入受控构建与启动层、任务级验收。已构建 exe；未改 DB migration；未改 9100；未改自动发送策略；真实微信任务验收仅限 Aw3、`paste_only` 与 `read_only`，全程保持 `sent=false`。

补齐记录（2026-06-22）：

- 19000 Local Agent 心跳不再固定上报 `wechat_status=unknown`，已改为与 `/agent/wechat/windows` 同源的轻量微信窗口诊断：仅当检测到可用微信主窗口时上报 `ready`，微信最小化/隐藏/未找到时上报 `unavailable`，探测异常上报 `unknown` 并记录 warning。
- 心跳探测不触发 OCR、不切换前台、不搜索联系人、不粘贴、不发送。
- 前端“小高AI微信助手”页补充“构建与分发说明”，明确当前页面不提供在线下载，验收使用 `dist/local-agent/小高AI微信助手.exe` 完整目录或人工分发包。
- 自动发送安全边界保持不变：`notify_sales` 只允许 `paste_only`，`detect_reply` 只读检测，`sent=false`。

本轮验证结果（2026-06-22）：

- `python -m py_compile app/local_agent_main.py`：通过。
- `python -m pytest tests/test_local_agent_heartbeat.py tests/test_agent_status.py -v`：2026-06-22 为 18 passed；2026-06-23 心跳口径修复后，`tests/test_local_agent_heartbeat.py` 为 11 passed，`tests/test_agent_status.py` 为 8 passed。
- `python -m pytest tests/test_p0_main_5b_poll_and_execute.py -v`：37 passed，1 warning。
- `python -m pytest tests/test_p1_auto_1c_poll_and_detect.py tests/test_p1_auto_1d_fix4_safe_json.py -v`：43 passed，1 warning。
- `cd frontend && npm run build`：通过；保留既有 `/fonts/Barlow-Regular_2.ttf` 运行时解析警告和 chunk 大小警告。

未执行项：

- 2026-06-23 用户确认后已进入受控构建并构建 exe。
- 已短暂启动 19000 做 `/health`、`/agent/version`、`/agent/wechat/windows`、9000 心跳验收；验收后需停止临时进程。
- 已执行受控真实微信任务验收：Aw3 `notify_sales paste_only` 与 `detect_reply read_only`，未触发自动发送。
- 未做虚拟机 / Windows 10 真机验收。

最终受控构建结果（2026-06-23 00:44:18）：

- 构建命令：`powershell -ExecutionPolicy Bypass -File scripts/build_local_agent_exe.ps1 -PythonExe "C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe" -ServerUrl "http://192.168.110.113:9000"`。
- 构建成功，产物：`dist/local-agent/小高AI微信助手.exe`。
- 构建版本：`P0-LOCAL-AGENT-EXE-1`。
- 构建时间：`2026-06-23 00:44:18`。
- 构建 commit：`aa8a3f1`。
- SHA256：`F440B6B400F710213CECA316025069E2E462A1CCE78CF5E252EA2CEBDA033950`。
- 构建脚本内置烟测通过：`/health` OK，`/agent/version` OK。
- 产物 `.env` 已写入 `AUTO_WECHAT_SERVER_URL=http://192.168.110.113:9000`。
- 产物包含 `models/easyocr`、`logs/`、`停止小高AI微信助手.ps1`。

最终受控构建后基础运行验收（2026-06-23 00:47）：

- 手动启动构建后的 exe 后，`GET http://127.0.0.1:19000/health` 返回 `success=true`、`wechat_agent=true`，进程 PID 为 `35836`。
- `GET http://127.0.0.1:19000/agent/version` 返回 `build_time=2026-06-23 00:44:18`、`git_commit=aa8a3f1`，路由包含 `/agent/version`。
- `dist/local-agent/_internal/base_library.zip` 存在，大小 `880880` 字节。
- `dist/local-agent/logs/local_agent.log` 已生成，并记录 `local agent starting`、`Application startup complete`、`GET /health`、`GET /agent/version`。
- `GET http://127.0.0.1:19000/agent/wechat/windows` 返回 `wechat_detected=false`，候选中真实 `Weixin.exe` 主窗口为 `iconic=true` 且坐标为 `-32000`，说明微信主窗口处于最小化/托盘状态。
- 等待心跳后，9000 `GET /agent/status` 返回 `agent_online=true`、`wechat_status=unavailable`、`wechat_available=unavailable`、`can_run_wechat_action=false`、`disabled_reason=WeChat is not available`，符合安全门禁预期。
- 当前不得执行 `poll-and-execute` 或 `poll-and-detect` 真实微信任务，必须先由人工打开微信主窗口并确认可见。

启动失败排查记录（2026-06-23）：

- 用户反馈双击后显示“无法启动 python 嵌入式启动器”。
- 复查旧 `dist/local-agent` 时发现 `_internal/base_library.zip` 缺失，而 `build/local_agent/base_library.zip` 存在；旧 `dist/local-agent/小高AI微信助手.exe` 时间为 `00:03:28`，`build/local_agent/小高AI微信助手.exe` 时间为 `00:11:35`，说明旧 dist 目录存在混合/不完整产物风险。
- 旧产物启动后曾出现进程存活但不监听 `127.0.0.1:19000`、不生成 `logs/local_agent.log` 的现象，卡点位于入口导入或 PyInstaller 运行时初始化阶段之前/附近。
- 源码对照验证通过：`C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe -c "import app.local_agent_main"` 可正常导入，依赖 `easyocr/torch/cv2` 可正常导入。因此根因指向 PyInstaller onedir 产物不完整，而不是源码入口或依赖环境本身。
- 处理方式：重新执行完整构建脚本，由 PyInstaller 重新生成 `dist/local-agent`，避免手工补单个文件。
- 重构建后 `_internal/base_library.zip` 已存在，构建脚本烟测和手动 `/health`、`/agent/version` 验收均通过。
- 后续分发必须复制完整 `dist/local-agent` 目录，不允许只复制 `小高AI微信助手.exe`，也不建议在旧 dist 目录中手工补文件作为正式验收产物。
- 额外风险：启动日志中轻量窗口探测曾把 `Xshell.exe` 窗口识别为微信窗口。该问题不影响本次“python 嵌入式启动器”启动失败根因，但会影响后续 `wechat_status=ready` 的可信度，真实微信任务验收前应先调用 `/agent/wechat/windows` 核对窗口诊断结果。

窗口识别与心跳口径修复记录（2026-06-23）：

- 真实现象：旧窗口识别逻辑把标题包含 `/www/wwwroot/auto_wechat` 的 `Xshell.exe` 窗口误判为微信候选，导致 9000 状态卡显示 `wechat_status=ready`。
- 已新增回归测试：`tests/test_p0_4a_1_window_discovery.py::test_find_wechat_window_excludes_xshell_auto_wechat_title`，先失败后修复。
- 已修复：`app/wechat_ui/window_locator.py` 将 `auto_wechat` 加入窗口标题排除关键字，避免项目路径中的 `wechat` 子串触发误判。
- 真实现象：修复 Xshell 误识别后，`find_wechat_window()` 仍可能通过 FindWindowW 找到最小化微信句柄，导致心跳误报 `ready`。
- 已新增回归测试：`tests/test_local_agent_heartbeat.py::test_heartbeat_payload_reports_unavailable_when_wechat_window_minimized`，先失败后修复。
- 已修复：`app/local_agent_main.py` 的心跳探测改为复用 `collect_wechat_window_diagnostics()`，与 `/agent/wechat/windows` 同源；微信最小化/隐藏/未找到时心跳上报 `unavailable`。
- 验证结果：`tests/test_p0_4a_1_window_discovery.py` 20 passed；`tests/test_local_agent_heartbeat.py` 11 passed；`tests/test_agent_status.py` 8 passed；`tests/test_p0_main_5b_poll_and_execute.py` 37 passed；`tests/test_p1_auto_1c_poll_and_detect.py tests/test_p1_auto_1d_fix4_safe_json.py` 43 passed。

恢复审计补充（2026-06-23）：

- 恢复检查时，构建产物 `dist/local-agent/小高AI微信助手.exe` 仍存在，`.env` 仍指向 `http://192.168.110.113:9000`。
- 初始状态下 19000 未监听，9000 `/agent/status` 显示 `agent_online=false`、`status_source=heartbeat_expired`，符合 Agent 未启动后的心跳过期表现。
- 短暂启动构建后的 exe 后，`/health` 返回 `success=true`、`wechat_agent=true`，`/agent/tasks/server-url` 返回 `server_url=http://192.168.110.113:9000`、`configured=true`。
- 等待最终修复版心跳后，9000 `/agent/status` 为 `agent_online=true`、`wechat_status=unavailable`、`wechat_available=unavailable`、`can_run_wechat_action=false`、`status_source=heartbeat`；原因是微信主窗口当前最小化，安全门禁生效。
- 恢复审计后已停止临时 exe 进程，`127.0.0.1:19000` 未继续监听。

真实任务验收前置检查（2026-06-23）：

- 当前构建产物仍存在：`dist/local-agent/小高AI微信助手.exe`，最新 SHA256 为 `F440B6B400F710213CECA316025069E2E462A1CCE78CF5E252EA2CEBDA033950`。
- 当前 `.env` 仍存在，大小 `241` 字节，主系统地址为 `http://192.168.110.113:9000`。
- 当前 OCR 模型存在：`craft_mlt_25k.pth`、`zh_sim_g2.pth`。
- 当前 19000 可启动并通过 `/health`；进入真实任务验收前需要保持 `小高AI微信助手.exe` 运行。
- 当前微信主窗口处于最小化/托盘状态，`/agent/wechat/windows` 返回 `wechat_detected=false`；进入真实任务验收前需要人工打开微信主窗口。
- 9000 OpenAPI 已确认存在任务与心跳接口：`/agent/status`、`/agent/heartbeat`、`/wechat-tasks`、`/wechat-tasks/pending`、`/wechat-tasks/{task_id}`、`/wechat-tasks/{task_id}/result`。
- 本次检查未创建任务、未执行 `poll-and-execute`、未执行 `poll-and-detect`，未触发微信自动化；原因是安全门禁已确认 `can_run_wechat_action=false`。

任务级受控验收补充记录（2026-06-23 01:18）：

- 新构建 exe 运行版本：`build_time=2026-06-23 01:05:07`、`git_commit=9554d2e`、`sha256=72678118E07C06077ADBF8F2F2DF42297AF471B67769E029A63172DFEC42E3BB`、PID `6872`。
- 启动器问题复核：当前 `dist/local-agent/_internal/base_library.zip` 与 `python310.dll` 均存在，`/health`、`/agent/version` 可访问。若测试机仍提示“无法启动 python 嵌入式启动器”，结论仍是分发包不完整，必须复制完整 `dist/local-agent` 目录，不能只复制 exe。
- `notify_sales` 真机任务 `task_id=4` 已完成 Aw3 `paste_only`：9000 任务状态 `pasted`，`raw_result.pasted=true`，`raw_result.sent=false`，`sent_at=null`，自动绑定/创建 `detect_reply task`。
- 旧 `detect_reply task_id=5` 在旧 exe 下失败于 `message_list_not_found`；已补右侧聊天区消息列表 fallback，并通过测试 `tests/test_p0_4a_1_window_discovery.py`。
- 新 exe 执行 `detect_reply task_id=6` 时已读到 `messages_read=2`，说明消息列表 fallback 生效；但 9000 Docker 运行态当时未注册 `/replies/agent-write-back`，导致 `server_request_failed`。
- 已将 9000 的 `/replies/agent-write-back` 从 Windows 专用路由中拆出：Docker 9000 不再因为 `feedback/lead_notifications` 或 UI 自动化依赖缺失而跳过纯回写接口。重启 `auto-wechat-api-dev` 后 OpenAPI 已出现 `/replies/agent-write-back`。
- 新建 `detect_reply task_id=7` 后，19000 `/agent/tasks/poll-and-detect` 指定执行成功：`success=true`，`detected_status=pending`，`messages_read=2`，`write_back.ok=true`，`task_result_write_back.ok=true`，`action.sent=false`，`action.pasted=false`。
- 当前 `pending` 不是自动化失败，含义是当前 Aw3 聊天窗口未读到可判定为销售有效回复的 `friend` 消息。要完成最终 `replied` 闭环，需要人工在 Aw3 对话中回复“收到，已添加微信”后，再新建或复用 pending 检测任务按 `task_id` 执行。
- 契约瑕疵：`detect_reply pending` 分支当前会复用 `wechat_tasks.pasted_at` 记录“最后检测时间”，前端又展示该字段，容易让只读检测看起来像发生过粘贴。当前 `action.pasted=false`、`sent_at=null` 可证明安全边界未破，但建议后续单独修复为 `last_detected_at` 或前端按任务类型区分展示。
- 2026-06-23 08:09 复用 `task_id=7` 再次检测时，任务失败于 `foreground_guard_failed`，9000 已回写失败且 `action.sent=false`、`action.pasted=false`。`/agent/wechat/foreground-debug` 显示微信窗口可见且未最小化，但当前前台窗口为 `选择 auto_wechat`（`ConsoleWindowClass`），`SetForegroundWindow`、`BringWindowToTop`、`AttachThreadInput`、`Alt wakeup` 均未能把微信切到前台。该失败是安全门禁生效，不应通过绕过 foreground guard 继续检测；需人工点击微信 Aw3 聊天窗口到前台后再创建新的 `detect_reply` 任务复测。
- 2026-06-23 08:13 前台焦点诊断恢复成功：`foreground_success=true`，`foreground_after_title=微信`，`foreground_after_process_name=Weixin.exe`。随后新建 `detect_reply task_id=8` 并读取消息成功，但由于仍绑定旧 `reply_check_id=5`，而该检测记录已于 `2026-06-22T17:32:33` 超时，9000 正确回写 `failure_stage=check_already_timeout`。该结果说明必须使用新的 pending `ReplyCheck` 进行最终验收，不能复用旧超时 check。
- 2026-06-23 08:16 通过正常 9000 API 新建干净验收线索 `lead_id=17`，分配给 Aw3 后系统创建 `reply_check_id=6`，状态 `pending`，截止时间 `2026-06-23T00:46:41`。随后新建 `detect_reply task_id=9` 并由 19000 指定执行：`success=true`，`detected_status=pending`，`messages_read=2`，`write_back.ok=true`，`task_result_write_back.ok=true`，`action.sent=false`，`action.pasted=false`，9000 任务仍为 `pending` 且 `sent_at=null`。这证明新构建 exe 已能在干净 pending 检测记录上完成只读检测与结果回写；当前未达到 `replied` 的唯一原因是 Aw3 聊天窗口内尚无可判定为销售有效回复的 `friend` 消息。
- 2026-06-23 08:21 当前态复核：`GET /health` 与 `/agent/version` 正常，19000 运行 PID 仍为 `6872`；`/agent/wechat/windows` 返回 `wechat_detected=true`，真实微信主窗口 `visible=true`、`iconic=false`；9000 `/agent/status` 返回 `agent_online=true`、`wechat_status=ready`、`can_run_wechat_action=true`；OpenAPI 已包含 `/replies/agent-write-back`。
- 2026-06-23 08:21 前台守卫复核：`POST /agent/wechat/foreground-debug` 返回 `foreground_success=true`、`foreground_after_process_name=Weixin.exe`，OCR 状态 `ocr_initialized=true`、`model_ready=true`。
- 2026-06-23 08:21 再次按 `task_id=9` 执行只读检测：`success=true`，`detected_status=pending`，`matched_reply=null`，`messages_read=2`，`write_back.ok=true`，`task_result_write_back.ok=true`，`action.sent=false`，`action.pasted=false`。9000 `reply_check_id=6` 仍为 `pending`。结论保持不变：执行链路、回写链路和安全边界可验收；最终 `replied` 样本仍缺少一条可被 sender 识别为 `friend` 且命中有效回复关键词的 Aw3 消息。
- 2026-06-23 08:26 复测：当前系统时间为 `2026-06-23T08:26:14+08:00`，未超过 `reply_check_id=6` 的截止时间 `2026-06-23T00:46:41`；`/agent/wechat/foreground-debug` 仍返回 `foreground_success=true`，微信前台窗口为 `Weixin.exe`；再次按 `task_id=9` 执行只读检测后，返回 `success=true`、`detected_status=pending`、`matched_reply=null`、`messages_read=2`、`write_back.ok=true`、`task_result_write_back.ok=true`、`action.sent=false`、`action.pasted=false`。9000 任务 `detect_count` 已更新为 `3`，`sent_at=null`。结论仍是缺少可识别的 Aw3 `friend` 有效回复样本，而非链路或回写能力缺口。
- 2026-06-23 08:29 只读状态复查：未再次触发微信自动化，仅查询 9000 状态。`task_id=9` 仍为 `pending`，`detect_count=3`，`sent_at=null`；`reply_check_id=6` 仍为 `pending`，`actual_reply_at=null`，`reply_content=null`；`checks?status=replied` 仅返回历史旧样本 `check_id=1`，不是本轮 exe 闭环验收数据；9000 `/agent/status` 仍为 `agent_online=true`、`wechat_status=ready`。同一阻塞条件连续复现：缺少人工产生的 Aw3 有效销售回复消息。
- 2026-06-23 09:02 只读状态复查：未触发微信自动化，仅查询 9000 状态。`checks?status=pending` 已为空；全量 `GET /checks` 显示 `reply_check_id=6` 已转为 `timeout`，`effectiveness_reason=超时未回复，截止时间 00:46:41`，`actual_reply_at=null`，`reply_content=null`。`task_id=9` 仍保留 `status=pending`、`detect_count=3`、`sent_at=null`，但它绑定的 `reply_check_id=6` 已不再是干净 pending 验收对象。后续最终 `replied` 验收必须重新创建新的 pending `ReplyCheck` 和新的 `detect_reply task_id`，不能继续复用 `task_id=9`。
- 2026-06-23 09:14 按正常 9000 API 重新创建干净验收对象：`lead_id=18`，分配给 Aw3 后生成 `reply_check_id=7`，`check_status=pending`，`reply_deadline=2026-06-23T01:44:06.017707`；随后创建新的 `detect_reply task_id=10`，`task_status=pending`，`mode=read_only`，`target_nickname=Aw3`。本次未复用 `task_id=9` 或 `reply_check_id=6`。
- 2026-06-23 09:16 执行新的 `task_id=10`：19000 `/agent/tasks/poll-and-detect` 返回 `success=true`、`detected_status=replied`、`matched_reply=收到，已添加微信`、`messages_read=3`、`write_back.ok=true`、`task_result_write_back.ok=true`、`action.sent=false`、`action.pasted=false`、`failure_stage=null`。这证明 exe 的 `detect_reply` 只读检测、有效回复识别、安全边界和 9000 回写链路已经跑通。
- 2026-06-23 09:16 9000 回查结果：`reply_check_id=7` 已更新为 `check_status=replied`、`is_effective=1`、`reply_content=收到，已添加微信`、`actual_reply_at=2026-06-23T01:16:17.978704`；`lead_id=18` 已更新为 `status=replied`，时间线包含 `reply_check` 记录。`wechat_task_id=10` 已更新为 `status=completed`、`sent_at=null`、`pasted_at=null`、`raw_result.detect_result.detected_status=replied`。
- 契约瑕疵补充：`wechat_task_id=10` 虽为 `status=completed`，但 9000 任务详情中的 `failure_stage` 为 `check_already_replied`。根因推测是 19000 先通过 `/replies/agent-write-back` 将 `ReplyCheck` 更新为 replied，随后 `/wechat-tasks/{task_id}/result` 再做任务结果联动时发现 check 已是 replied，于是保留了该提示。该问题不影响本次能力闭环，但前端若直接展示非空 `failure_stage`，可能把成功任务误导为异常，建议后续单独修正显示口径或后端结果字段。
- 前端展示口径补充：`WechatTaskPanel` 已将 `failure_stage` 的展示按任务状态区分，`failed`、`blocked`、`timeout` 显示为“失败原因”，`completed`、`pasted`、`replied` 等非失败状态显示为“系统提示”。因此 `task_id=10` 的 `check_already_replied` 不再按失败原因展示，避免成功任务被误读为失败。
- 前端构建验证补充：`cd frontend && npm run build` 已通过；保留既有 `/fonts/Barlow-Regular_2.ttf` 运行时解析警告和 chunk 大小警告。
- React 任务页渲染验收补充：`http://127.0.0.1:5173/wechat-assistant/tasks` 已完成无头 Edge 浏览器级验收。页面实际渲染 `WechatTaskPanel`，正文包含“微信任务队列”“创建测试任务并执行”“自动回复检测”，并展示 `check #7 已回复`、`回复内容: 收到，已添加微信`；CDP 未捕获 `Runtime.exceptionThrown`。截图路径：`C:\Users\A\AppData\Local\Temp\wechat_assistant_tasks_5173_task_panel.png`。

完成审计补充（2026-06-23 09:49）：

- 当前 19000 exe 运行态验证：`GET http://127.0.0.1:19000/health` 返回 `success=true`、`wechat_agent=true`，运行进程来自 `dist/local-agent/小高AI微信助手.exe`，PID `6872`。
- 当前 19000 版本验证：`GET http://127.0.0.1:19000/agent/version` 返回 `exe_mode=true`、`build_time=2026-06-23 01:05:07`、`git_commit=9554d2e`，路由包含 `/agent/tasks/poll-and-execute` 与 `/agent/tasks/poll-and-detect`。
- 当前 19000 服务地址验证：`GET http://127.0.0.1:19000/agent/tasks/server-url` 返回 `server_url=http://192.168.110.113:9000`、`configured=true`。
- 当前 9000 心跳状态验证：经前端 `/api/agent/status` 代理查询，返回 `agent_online=true`、`wechat_status=ready`、`can_run_wechat_action=true`、`status_source=heartbeat`。
- 当前 9000 任务回写验证：`GET /wechat-tasks/10` 返回 `task_type=detect_reply`、`status=completed`、`raw_result.detect_result.detected_status=replied`、`matched_reply=收到，已添加微信`、`sent_at=null`、`pasted_at=null`。
- 当前 9000 回复检测回写验证：`GET /checks` 中 `reply_check_id=7` 为 `check_status=replied`、`is_effective=1`、`reply_content=收到，已添加微信`。
- 当前 9000 线索状态验证：`GET /leads/18` 返回 `status=replied`，时间线包含 `reply_check` 记录。
- 当前 React 任务页验证：无头 Edge 打开 `/wechat-assistant/tasks` 后，正文包含 `状态 在线`、`微信任务队列`、`check #7`、`已回复`、`回复内容: 收到，已添加微信`，且 CDP 未捕获 `Runtime.exceptionThrown`。
- 当前自动化测试补跑：`python -m py_compile app/local_agent_main.py` 通过；`tests/test_local_agent_heartbeat.py tests/test_agent_status.py` 为 19 passed、5 warnings；`tests/test_p0_main_5b_poll_and_execute.py` 为 37 passed、1 warning；`tests/test_p1_auto_1c_poll_and_detect.py tests/test_p1_auto_1d_fix4_safe_json.py` 为 43 passed、1 warning。

仍未执行项：

- 已执行真实 `poll-and-execute` 微信粘贴任务，结果为 Aw3 `paste_only` 成功且 `sent=false`。
- 已执行真实 `poll-and-detect` 微信只读检测任务，先验证过 `pending` 回写成功，随后在新的干净验收对象 `task_id=10` / `reply_check_id=7` 上完成 `replied` 回写成功，且 `action.sent=false`、`action.pasted=false`。
- 已完成 React 页面真实渲染验收：`/wechat-assistant/tasks` 已确认进入任务面板而非旧总览页，页面可展示最新 `ReplyCheck` 的 `replied` 结果和回复内容；未再次触发微信自动化按钮。
- 未在 Windows 11 虚拟机 / Windows 10 测试电脑做跨机器验收。

构建前审计结果（2026-06-22）：

- `scripts/build_local_agent_exe.ps1` 默认 `ServerUrl=https://callback.misanduo.com`，局域网验收必须显式传入 `-ServerUrl "http://192.168.110.113:9000"`。
- 构建脚本会写入 `app/local_agent_build_info.py`，因此实际构建会产生源码区生成文件变更。
- 构建脚本会调用 PyInstaller，并启动构建后的 exe 做 `/health` 与 `/agent/version` 烟测；这会短暂启动 19000，但不会触发微信任务执行。
- 构建脚本会复制 `resources/easyocr_models` 到 `dist/local-agent/models/easyocr`，当前模型目录存在且包含模型文件。
- 默认 `python` 环境缺少 `easyocr`，不能直接用于构建。
- `C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe` 已验证具备构建依赖：PyInstaller 6.20.0、easyocr 1.7.2、torch 2.12.0+cpu、cv2 4.13.0。
- exe 入口会读取工作目录或 exe 同目录 `.env`，构建脚本写入的 `AUTO_WECHAT_SERVER_URL` 会成为心跳、任务拉取和结果回写的默认主系统地址。

## 一、当前前端功能清单

### 1. 页面入口

前端能力中心已存在“小高AI微信助手”入口，相关路由来源包括：

- `frontend/src/features/capabilities.ts`
- `frontend/src/features/wechat-assistant/routes.ts`
- `frontend/src/pages/Index.tsx`

当前可见入口：

| 入口名称 | 路径 | 当前渲染情况 |
|---|---|---|
| Local Agent状态 | `/wechat-assistant` | 渲染 `WechatAgent` |
| 微信配置 | `/wechat-assistant/config` | 当前仍渲染 `WechatAgent` |
| 任务记录 | `/wechat-assistant/tasks` | 当前仍渲染 `WechatAgent` |
| 下载/测试 | `/wechat-assistant/download-test` | 当前仍渲染 `WechatAgent` |

结论：前端已经有“下载/测试”导航入口，但未发现真实下载 exe 的按钮、下载接口或构建产物版本列表入口。

### 2. 页面与组件

已核对的核心文件：

- `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- `frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx`
- `frontend/src/features/wechat-assistant/components/LocalWechatAgentTestPanel.tsx`
- `frontend/src/api/localWechatAgent.ts`
- `frontend/src/api/agent.ts`
- `frontend/src/api/wechatTasks.ts`

### 3. 状态卡片与状态依赖

前端同时使用两个状态来源：

| 状态来源 | 接口 | 用途 |
|---|---|---|
| 9000 主后端 Agent 状态 | `GET /agent/status` | 展示 Agent/微信/自动化/紧急停止/当前任务状态 |
| 浏览器所在电脑 19000 本地 Agent | `GET http://127.0.0.1:19000/health` | 判断当前电脑是否启动“小高AI微信助手” |

前端离线提示文案已符合当前规范：

```text
未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手
```

重要状态字段依赖：

- `agent_online`
- `agent_status`
- `wechat_available`
- `wechat_status`
- `automation_enabled`
- `emergency_stopped`
- `action_in_progress`
- `current_task_id`
- `current_task_type`
- `last_heartbeat_at`
- `can_run_wechat_action`
- `disabled_reason`
- `status_source`

已补齐：19000 心跳已从固定 `unknown` 改为轻量微信窗口状态上报。找到微信窗口时上报 `ready`，9000 可据此把 `wechat_available` 归一为 `available`，从而支撑前端状态卡展示“Agent 在线 / 微信自动化可用”的一期验收口径。

剩余风险：该状态仅代表“发现微信窗口”，不代表 OCR、联系人搜索、粘贴和回复检测全部可用；这些能力仍应通过 `/agent/wechat/windows`、`/agent/ocr/status`、`poll-and-execute`、`poll-and-detect` 分别验收。

### 4. 按钮与前端动作

当前前端实际动作包括：

| 功能 | 前端调用 | 说明 |
|---|---|---|
| 查看主后端 Agent 状态 | `GET /agent/status` | 9000 状态卡片 |
| 查看本机 Agent 健康状态 | `GET /health` | 19000，本机浏览器直连 |
| 查看本机 Agent 版本 | `GET /agent/version` | 19000 |
| 查看任务服务地址 | `GET /agent/tasks/server-url` | 19000 |
| 查看 OCR 状态 | `GET /agent/ocr/status` | 19000 |
| 预热 OCR | `POST /agent/ocr/warmup` | 19000 |
| 诊断微信窗口 | `GET /agent/wechat/windows` | 19000 |
| 前台焦点诊断 | `POST /agent/wechat/foreground-debug` | 19000 |
| 搜索诊断 | `POST /agent/wechat/search-debug` | 19000 |
| 搜索校准 | `POST /agent/wechat/search-calibration/start` | 19000 |
| 搜索结果诊断 | `POST /agent/wechat/search-result-debug` | 19000 |
| 启动微信测试 | `POST /agent/wechat/test` | 19000，Aw3、paste_only、sent=false |
| 查询销售 | `GET /staff` | 9000 |
| 新建销售 | `POST /staff` | 9000 |
| 创建微信任务 | `POST /wechat-tasks` | 9000 |
| 查询待执行任务 | `GET /wechat-tasks/pending` | 9000 |
| 查询任务详情 | `GET /wechat-tasks/{id}` | 9000 |
| 执行通知销售任务 | `POST /agent/tasks/poll-and-execute` | 19000，支持 `task_id` |
| 执行回复检测任务 | `POST /agent/tasks/poll-and-detect` | 19000，支持 `task_id` |
| 旧回复检测入口 | `POST /agent/replies/detect` | 19000，兼容旧入口 |

### 5. 请求参数

前端依赖的主要请求参数：

| 接口 | 参数 |
|---|---|
| `POST /wechat-tasks` | `task_type`、`target_nickname`、`message`、`mode`、`lead_id`、`staff_id` |
| `GET /wechat-tasks/pending` | `task_type`、`limit` |
| `POST /agent/tasks/poll-and-execute` | `task_id` |
| `POST /agent/tasks/poll-and-detect` | `task_id`、`max_messages` |
| `POST /agent/wechat/test` | 测试消息/目标联系人，当前按 Aw3 安全边界执行 |

前端当前重点依赖的任务类型：

- `notify_sales`
- `detect_reply`

前端当前重点依赖的安全模式：

- `paste_only`
- `read_only`
- `sent=false`

### 6. 响应字段与错误提示

前端依赖响应中的通用字段：

- `ok` / `success`
- `message`
- `error_code`
- `failure_stage`
- `task_id`
- `task_type`
- `status`
- `pasted`
- `sent`
- `detected_status`
- `detect_count`
- `manual_review_required`

前端错误提示主要来自接口返回的 `message`、`error_code`、`failure_stage`，Local Agent 诊断类接口还依赖可安全序列化的 JSON 响应。

### 7. 是否有下载 exe 入口

结论：有“下载/测试”导航入口；补齐后页面已明确展示构建产物路径、局域网构建参数和人工分发边界。

当前未实现在线下载 exe 服务。本期按“构建产物或人工分发完整目录”验收，不把前端下载服务作为一期阻塞。

### 8. 是否依赖任务状态

依赖。前端需要：

- 创建任务后按 `task_id` 执行当前任务
- 查询 `/wechat-tasks/{task_id}` 展示任务状态
- 查询 pending `notify_sales` 与 `detect_reply`
- 依赖任务结果中的 `pasted`、`sent`、`detected_status`、`detect_count`

### 9. 是否依赖销售微信在线状态

部分依赖。当前前端通过 9000 `/agent/status` 展示 `wechat_available`、`wechat_status`、`can_run_wechat_action`，通过 19000 诊断接口判断本机微信窗口、前台焦点、OCR、搜索能力。

但 19000 心跳当前没有真实上报微信 ready 状态，9000 状态卡与本机诊断结果之间尚未完全统一。

## 二、9000 接口清单

### 1. 已有接口

从代码与运行态 OpenAPI 核对，9000 已有相关接口：

| 路径 | 方法 | 用途 | 前端是否调用 |
|---|---|---|---|
| `/agent/status` | GET | 查询 Agent 聚合状态 | 是 |
| `/agent/heartbeat` | POST | Local Agent 心跳上报 | 前端不直接调，19000 调 |
| `/wechat-tasks` | POST | 创建微信任务 | 是 |
| `/wechat-tasks/pending` | GET | 查询待执行任务 | 是 |
| `/wechat-tasks/{task_id}` | GET | 查询任务详情 | 是 |
| `/wechat-tasks/{task_id}/result` | POST | 任务结果回写 | 前端不直接调，19000 调 |
| `/wechat-auto-detect/status` | GET | 自动检测状态 | 非本轮核心 |
| `/wechat-auto-detect/target` | POST | 设置自动检测目标 | 非本轮核心 |
| `/wechat-auto-detect/clear` | POST | 清理自动检测目标 | 非本轮核心 |

涉及文件：

- `app/routers/agent.py`
- `app/routers/wechat_tasks.py`
- `app/services/agent_status_service.py`
- `app/services/wechat_task_service.py`
- `app/schemas.py`
- `app/main.py`

### 2. 请求参数

#### `POST /agent/heartbeat`

Local Agent 上报字段包括：

- `agent_status`
- `wechat_status`
- `automation_enabled`
- `emergency_stopped`
- `action_in_progress`
- `current_task_id`
- `current_task_type`
- `hostname`
- `version`

心跳 TTL 当前为 30 秒，建议心跳间隔为 10 秒。

#### `GET /agent/status`

无请求体。返回 9000 内存态 Agent 状态。

#### `POST /wechat-tasks`

主要字段：

- `task_type`
- `target_nickname`
- `message`
- `mode`
- `lead_id`
- `staff_id`

当前强约束：

- `target_nickname` 只允许 `Aw3`
- `notify_sales` 只允许 `mode=paste_only`
- `detect_reply` 允许 `mode=read_only`，兼容部分 `paste_only`
- `sent=true` 全局拒绝

#### `GET /wechat-tasks/pending`

查询参数：

- `task_type`
- `limit`

#### `POST /wechat-tasks/{task_id}/result`

19000 回写字段包括：

- `status`
- `pasted`
- `sent`
- `error_code`
- `error_message`
- `failure_stage`
- `detected_status`
- `detect_count`
- `result_payload`

### 3. 响应字段

#### `/agent/status`

返回字段：

- `agent_online`
- `agent_status`
- `wechat_available`
- `wechat_status`
- `automation_enabled`
- `emergency_stopped`
- `action_in_progress`
- `current_task_id`
- `current_task_type`
- `last_heartbeat_at`
- `can_run_wechat_action`
- `disabled_reason`
- `status_source`

#### `/wechat-tasks`

任务响应包括：

- `id`
- `task_type`
- `target_nickname`
- `message`
- `mode`
- `status`
- `lead_id`
- `staff_id`
- `created_at`
- `updated_at`
- `pasted`
- `sent`
- `detected_status`
- `detect_count`
- `error_code`
- `error_message`
- `failure_stage`

### 4. 权限/商户隔离

当前代码层面未看到 `/agent/status`、`/agent/heartbeat`、`/wechat-tasks` 的认证、商户隔离或 Agent 绑定校验。当前实现更接近单机、单商户、演示版状态。

结论：

- 单机演示验收：可接受。
- 多客户生产版或多 Agent 分发：不可接受，需要补商户/Agent 绑定/权限边界。

### 5. 前端是否已调用

已调用：

- `/agent/status`
- `/wechat-tasks`
- `/wechat-tasks/pending`
- `/wechat-tasks/{task_id}`
- `/staff`

未由前端直接调用，但被 19000 调用：

- `/agent/heartbeat`
- `/wechat-tasks/{task_id}/result`

### 6. 测试覆盖情况

已发现相关测试：

- `tests/test_agent_status.py`
  - 覆盖 `/agent/status`、`/agent/heartbeat`
- `tests/test_local_agent_heartbeat.py`
  - 覆盖 Local Agent 心跳 payload、server_url 缺失跳过、启动心跳线程
- `tests/test_p0_main_5b_poll_and_execute.py`
  - 覆盖 `poll-and-execute`、`task_id`、`notify_sales`、Aw3 限制、paste_only、sent=false、错误回写
- `tests/test_p1_auto_1c_poll_and_detect.py`
  - 覆盖 `poll-and-detect`、`task_id`、`detect_reply`、read_only、detect_count、agent_busy、sent/pasted=false
- `tests/test_p1_auto_1d_fix4_safe_json.py`
  - 覆盖 search-debug/search-result-debug 安全 JSON 序列化
- `tests/test_p0_4a_local_agent.py`
  - 覆盖 `/agent/wechat/test`、窗口/前台/搜索/OCR 相关路由
- `tests/test_p0_4a_6b_2_version_and_routes.py`
  - 覆盖 `/agent/version` 和关键路由注册

注意：本轮未运行完整测试，只做代码与接口核对。

## 三、19000 Local Agent 能力清单

### 1. 源码、入口与打包文件

已核对文件：

- `app/local_agent_main.py`
- `app/local_agent_exe_entry.py`
- `scripts/build_local_agent_exe.ps1`
- `local_agent.spec`

19000 默认监听：

```text
127.0.0.1:19000
```

这符合“浏览器所在电脑直连本机 Local Agent”的架构要求。

### 2. 已有路由能力

| 路径 | 方法 | 能力 |
|---|---|---|
| `/health` | GET | 本地健康检查 |
| `/agent/version` | GET | 查询版本与构建信息 |
| `/agent/ocr/status` | GET | 查询 OCR 状态 |
| `/agent/ocr/warmup` | POST | 预热 OCR |
| `/agent/wechat/test` | POST | Aw3 测试链路，自动定位 Aw3，verify OCR，paste_only，sent=false |
| `/agent/wechat/windows` | GET | 枚举/诊断微信窗口 |
| `/agent/wechat/foreground-debug` | POST | 前台焦点诊断 |
| `/agent/wechat/search-debug` | POST | 搜索框诊断 |
| `/agent/wechat/search-calibration/start` | POST | 搜索校准 |
| `/agent/wechat/search-result-debug` | POST | 搜索结果诊断 |
| `/agent/wechat/mouse-debug` | POST | 鼠标调试 |
| `/agent/tasks/server-url` | GET | 查询 9000 服务地址 |
| `/agent/tasks/poll-and-execute` | POST | 拉取/执行 `notify_sales` 任务 |
| `/agent/tasks/poll-and-detect` | POST | 拉取/执行 `detect_reply` 任务 |
| `/agent/replies/detect` | POST | 旧直接回复检测入口 |

### 3. 能力逐项核对

| 能力 | 19000 是否支持 | 说明 |
|---|---|---|
| 本地健康检查 | 支持 | `GET /health` |
| 向 9000 心跳 | 支持 | 后台线程调用 `POST /agent/heartbeat` |
| 轮询 `notify_sales` 任务 | 支持 | `/agent/tasks/poll-and-execute` |
| 轮询 `detect_reply` 任务 | 支持 | `/agent/tasks/poll-and-detect` |
| 识别微信窗口 | 支持 | `/agent/wechat/windows` 与任务执行前 readiness |
| 定位销售微信 | 支持但当前仅 Aw3 安全通过 | `open_chat_by_nickname` + OCR 验证 |
| 粘贴消息 | 支持 | `write_text_to_input(require_confirm=True)` |
| 只粘贴不自动发送 | 支持 | `paste_only`，成功时 `pasted=true`、`sent=false` |
| 检测销售是否回复 | 支持 | `detect_reply` 只读读取消息 |
| 任务成功/失败回传 | 支持 | 回写 `/wechat-tasks/{task_id}/result` |
| 错误码/错误信息 | 支持 | 返回/回写 `error_code`、`failure_stage`、`message` |
| 本地配置文件 | 支持 | exe `.env`、`AUTO_WECHAT_SERVER_URL` 等 |
| 日志目录 | 支持 | 默认 `logs/local_agent.log` |
| 打包脚本 | 支持 | `scripts/build_local_agent_exe.ps1` + `local_agent.spec` |

### 4. `poll-and-execute` 契约

支持请求体：

```json
{
  "task_id": 123
}
```

无 `task_id` 时会拉取：

```text
GET {server_url}/wechat-tasks/pending?task_type=notify_sales&limit=1
```

当前执行约束：

- 只处理 `task_type=notify_sales`
- 只允许 `target_nickname=Aw3`
- 只允许 `mode=paste_only`
- 前置 OCR 就绪检查
- 前置微信窗口就绪检查
- 前置 foreground guard
- 执行 `open_chat_by_nickname`
- 执行 `verify_current_chat_contact`
- 只粘贴，不发送
- 成功回写 `pasted=true`、`sent=false`

### 5. `poll-and-detect` 契约

支持请求体：

```json
{
  "task_id": 123,
  "max_messages": 20
}
```

无 `task_id` 时会拉取：

```text
GET {server_url}/wechat-tasks/pending?task_type=detect_reply&limit=1
```

当前执行约束：

- 只处理 `task_type=detect_reply`
- 只允许 `target_nickname=Aw3`
- 只读读取消息
- 不调用输入粘贴
- 不发送
- 回写 `detected_status`、`detect_count`
- 响应中固定 `sent=false`、`pasted=false`

### 6. 心跳能力风险

19000 支持向 9000 心跳，当前 `wechat_status` 已最小补齐为轻量窗口状态：

- `ready`：找到微信窗口。
- `unavailable`：未找到微信窗口。
- `unknown`：窗口探测异常。

边界：

- 不调用 OCR。
- 不切换前台。
- 不搜索联系人。
- 不粘贴。
- 不发送。

影响：9000 `/agent/status` 与前端状态卡已具备更一致的一期在线/可用展示口径；但 `ready` 仍不等于完整自动化链路可执行，构建后仍需跑任务级验收。

### 7. 打包脚本状态

已有打包脚本：

```powershell
scripts/build_local_agent_exe.ps1
```

已有 spec：

```text
local_agent.spec
```

预期产物路径：

```text
dist/local-agent/小高AI微信助手.exe
```

脚本能力：

- 复制 OCR 模型到 `dist/local-agent/models/easyocr`
- 生成 `.env`
- 默认写入 `AUTO_WECHAT_SERVER_URL`
- 复制停止脚本
- 做 `/health` 与 `/agent/version` 烟测
- 写入 `app/local_agent_build_info.py`

注意：打包脚本会修改 `app/local_agent_build_info.py`，本轮明确禁止构建，因此未执行。

当前默认 ServerUrl 风险：

```text
https://callback.misanduo.com
```

局域网验收通常应显式传入：

```text
http://192.168.110.113:9000
```

或按实际验收环境传入对应 9000 地址。

## 四、功能契约差异表

| 前端功能 | 前端接口 | 9000 是否支持 | 19000 是否支持 | 测试是否覆盖 | 是否阻塞构建 | 备注 |
|---|---|---|---|---|---|---|
| 本机 Agent 在线检测 | 19000 `/health` | 不涉及 | 支持 | 有 | 否 | 浏览器直连 127.0.0.1:19000 |
| 主后端 Agent 状态卡 | 9000 `/agent/status` | 支持 | 通过心跳间接支持 | 有 | 否 | 心跳已最小补齐窗口状态：ready/unavailable/unknown |
| Local Agent 心跳 | 19000 → 9000 `/agent/heartbeat` | 支持 | 支持 | 有 | 否 | 单机演示可用 |
| 创建通知销售任务 | 9000 `/wechat-tasks` | 支持 | 不涉及 | 有 | 否 | 只允许 Aw3 + paste_only |
| 执行通知销售任务 | 19000 `/agent/tasks/poll-and-execute` | 支持任务查询/回写 | 支持 | 有 | 否 | 支持 `task_id`，sent=false |
| 创建/执行回复检测任务 | 9000 `/wechat-tasks` + 19000 `/agent/tasks/poll-and-detect` + 9000 `/replies/agent-write-back` | 支持；Docker 运行态已补注册 `/replies/agent-write-back` | 支持 | 有 | 否 | read_only，`task_id=10` 已验证 `detected_status=replied`，`action.sent=false`，`action.pasted=false` |
| 查询任务详情 | 9000 `/wechat-tasks/{task_id}` | 支持 | 不涉及 | 有 | 否 | 前端依赖任务状态 |
| 查询 pending 任务 | 9000 `/wechat-tasks/pending` | 支持 | 19000 也会调用 | 有 | 否 | 兼容无 task_id 拉取 |
| 微信窗口诊断 | 19000 `/agent/wechat/windows` | 不涉及 | 支持 | 有 | 否 | 不触发发送 |
| 前台焦点诊断 | 19000 `/agent/wechat/foreground-debug` | 不涉及 | 支持 | 有 | 否 | 用于定位焦点问题 |
| 搜索诊断 | 19000 `/agent/wechat/search-debug` | 不涉及 | 支持 | 有 | 否 | 已有安全 JSON 序列化测试 |
| OCR 状态/预热 | 19000 `/agent/ocr/status`、`/agent/ocr/warmup` | 不涉及 | 支持 | 有 | 否 | exe 需携带模型 |
| Aw3 测试链路 | 19000 `/agent/wechat/test` | 不涉及 | 支持 | 有 | 否 | 当前已自动定位 Aw3 + paste_only + sent=false |
| 下载 exe | 前端“下载/测试”入口 | 未提供下载接口 | 有打包产物路径，前端已展示人工分发契约 | 前端构建验证 | 否，按人工分发验收 | 当前不做在线下载服务 |
| 商户/权限隔离 | 状态与任务接口 | 未支持 | 未支持 | 未见 | 生产阻塞，演示非阻塞 | 多客户产品化前必须补 |
| 错误回传 | 任务 result | 支持 | 支持 | 有 | 否 | 有 `error_code`、`failure_stage`、`message` |
| 检测任务时间字段 | 任务详情 `pasted_at` | 支持但字段语义复用 | 不涉及 | 部分 | 否 | `detect_reply pending` 会用 `pasted_at` 记录最后检测时间，前端展示时可能误导；安全边界以 `action.pasted=false`、`sent_at=null` 为准 |
| 日志路径 | 前端不直接依赖 | 不涉及 | 支持 | 部分 | 否 | 默认 `logs/local_agent.log` |
| 打包脚本 | 前端不直接依赖 | 不涉及 | 支持 | 脚本含烟测 | 部分阻塞 | 需显式 ServerUrl，且脚本会修改 build_info |

## 五、构建前阻塞项

### 阻塞项 1：前端有“下载/测试”入口，但无真实下载 exe 能力（已降级为非阻塞）

当前存在 `/wechat-assistant/download-test` 导航入口，但实际仍渲染同一个 `WechatAgent` 页面，未发现：

- 下载 exe 按钮
- 下载接口
- 版本包列表
- 构建产物路径展示
- 安装/运行前置条件说明

补齐后当前口径：本期不提供在线下载服务，页面明确说明使用构建产物或人工分发完整目录。因此该项不再阻塞一期 exe 构建验收。

### 阻塞项 2：9000 状态卡与 19000 本机能力状态口径不统一（已最小补齐）

19000 能向 9000 心跳，且已上报轻量微信窗口状态。9000 `/agent/status` 可据此展示 `wechat_available=available` 与 `can_run_wechat_action=true`。

剩余边界：该状态只证明本机可发现微信窗口，不证明 OCR、联系人验证、粘贴和回复检测全部成功。

### 阻塞项 3：构建脚本默认 ServerUrl 不适合局域网验收

打包脚本默认 ServerUrl 为：

```text
https://callback.misanduo.com
```

而局域网验收通常需要：

```text
http://192.168.110.113:9000
```

构建前必须明确传参，避免 exe 打出来后心跳和任务轮询指向错误服务。

### 阻塞项 4：打包脚本会修改构建信息文件

脚本会写入：

```text
app/local_agent_build_info.py
```

这不是业务逻辑问题，但构建前需要接受该生成文件行为。本轮禁止构建，因此未执行。

### 阻塞项 5：生产级商户/权限隔离缺失

9000 `/agent/status`、`/agent/heartbeat`、`/wechat-tasks` 当前未见认证、商户隔离、Agent 绑定校验。

结论：

- 单机演示版：不是构建阻塞。
- 多客户生产版：是构建阻塞。

## 六、建议的最小修复顺序

1. 明确 exe 构建验收是否要求“前端下载”
   - 如果要求：先补前端下载/版本/产物说明入口，或明确改为“人工分发 exe，不从前端下载”。
   - 如果不要求：把 `/wechat-assistant/download-test` 当前能力定义为“测试与诊断入口”，避免误导。

2. 统一 9000 `/agent/status` 与 19000 本机状态口径
   - 最小方案：19000 心跳上报更明确的 `wechat_status`，至少区分 `unknown`、`ready`、`not_found`、`blocked`。
   - 保持安全边界：不要因为心跳变 ready 就放宽发送策略，`sent` 仍必须为 false。

3. 固化构建命令参数
   - 局域网验收必须显式传入 9000 地址。
   - 不使用脚本默认的公网 callback 地址做本地验收。

4. 构建前确认 OCR 模型与日志目录
   - 确认 `dist/local-agent/models/easyocr` 会被复制。
   - 确认 `logs/local_agent.log` 可写。

5. 构建后只做非发送验收
   - `/health`
   - `/agent/version`
   - `/agent/tasks/server-url`
   - `/agent/ocr/status`
   - `/agent/wechat/windows`
   - Aw3 `paste_only`
   - `detect_reply` read_only
   - 全程确认 `sent=false`

6. 多客户生产化前再补权限/商户隔离
   - Agent 绑定商户
   - 任务按商户隔离
   - 心跳按 Agent 实例隔离
   - 前端状态按当前商户/当前 Agent 查询

## 七、是否建议开始构建 exe

结论：已可以并已进入 Local Agent exe 受控构建；当前产物已完成一期核心任务级闭环验收，包括 `notify_sales paste_only` 与 `detect_reply replied`。React 5173 任务页展示验收已通过；但尚不建议宣称完整跨机器分发验收已收口，因为 Windows 11 虚拟机 / Windows 10 测试电脑分发复测仍未完成。

原因：

1. 前端下载/测试入口已明确人工分发边界，不再要求在线下载。
2. 19000 心跳状态已最小补齐，可支撑 9000 状态卡展示。
3. 已用局域网 ServerUrl 构建出可启动 exe，`/health`、`/agent/version`、心跳、Aw3 `notify_sales paste_only`、`detect_reply pending` 回写均有当前证据。
4. 最终 `replied` 验收已在新建干净对象 `lead_id=18`、`reply_check_id=7`、`task_id=10` 上完成：`detected_status=replied`、`matched_reply=收到，已添加微信`、9000 `ReplyCheck.check_status=replied`、`Lead.status=replied`，并确认 `action.sent=false`、`action.pasted=false`。
5. React 页面真实展示验收已完成：无头 Edge 打开 `/wechat-assistant/tasks` 后确认渲染 `WechatTaskPanel`，页面展示 `check #7 已回复` 与回复内容，且没有运行时异常。
6. 剩余未完成项是跨机器分发验收，以及 `status=completed` 但 `failure_stage=check_already_replied` 的非阻塞后端契约瑕疵。

可以进入的下一步：

- 保留当前构建产物并按完整 `dist/local-agent` 目录分发，不只复制 exe。
- React 页面已在开发机 5173 完成任务页渲染验收；后续跨机器验收时仍需在测试机浏览器中复测同一页面，确认浏览器直连的是测试机本机 `127.0.0.1:19000`。
- 将完整 `dist/local-agent` 目录分发到 Windows 11 虚拟机 / Windows 10 测试电脑复测，确认不是只在开发机可用。
- 后续单独修正或解释 `status=completed` 但 `failure_stage=check_already_replied` 的前端展示口径，避免成功任务被误读为失败。

已使用的构建命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_local_agent_exe.ps1 -PythonExe "C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe" -ServerUrl "http://192.168.110.113:9000"
```

当前产物：

```text
dist/local-agent/小高AI微信助手.exe
```

运行前置条件：

- 运行机器为需要操作微信的 Windows 电脑。
- 微信已由人工打开，且不处于 hidden/minimized 后自动恢复状态。
- 19000 仅监听 `127.0.0.1:19000`。
- 能访问 9000 主后端地址。
- OCR 模型存在且可加载。
- 日志目录 `logs/` 可写。
- 当前安全边界保持 Aw3、paste_only、read_only、sent=false。

建议验收步骤：

1. 启动 `小高AI微信助手.exe`。
2. 浏览器访问 React 页面。
3. 前端确认 19000 `/health` 在线。
4. 前端确认 `/agent/version` 与 `/agent/tasks/server-url` 正确。
5. 前端执行微信窗口诊断，不发送消息。
6. 创建 Aw3 `notify_sales` + `paste_only` 任务。
7. 使用 `task_id` 调用 `poll-and-execute`。
8. 验证任务结果 `pasted=true`、`sent=false`。
9. 创建/执行 `detect_reply` 任务。
10. 验证结果回写 `detected_status`、`detect_count`，且 `sent=false`、`pasted=false`。

### 受控构建与验收清单

构建前门禁：

1. 确认当前轮允许构建 exe，并接受脚本写入 `app/local_agent_build_info.py`。
2. 确认 9000 主后端将使用局域网地址 `http://192.168.110.113:9000`，而不是默认公网 callback。
3. 确认当前机器没有旧的 `小高AI微信助手.exe` 占用 `127.0.0.1:19000`。
4. 确认构建解释器使用 `C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe`。
5. 确认 `resources/easyocr_models` 存在，且构建后必须复制完整 `dist/local-agent` 目录，不允许只复制 exe。

构建后产物检查：

1. `dist/local-agent/小高AI微信助手.exe` 存在。
2. `dist/local-agent/.env` 中 `AUTO_WECHAT_SERVER_URL=http://192.168.110.113:9000`。
3. `dist/local-agent/models/easyocr` 存在模型文件。
4. `dist/local-agent/logs` 存在且可写。
5. `dist/local-agent/停止小高AI微信助手.ps1` 存在。
6. 构建脚本输出 SHA256，可记录到验收结果。

非发送运行验收：

1. 启动 exe 后调用 `GET http://127.0.0.1:19000/health`，预期 `success=true`、`wechat_agent=true`。
2. 调用 `GET http://127.0.0.1:19000/agent/version`，预期路由包含 `/agent/tasks/poll-and-execute`、`/agent/tasks/poll-and-detect`、`/agent/wechat/search-result-debug`。
3. 调用 `GET http://127.0.0.1:19000/agent/tasks/server-url`，预期 server_url 指向 `http://192.168.110.113:9000`。
4. 等待至少一次心跳后，调用 9000 `GET /agent/status`，预期 `agent_online=true`；微信窗口可见时 `wechat_status=ready`。
5. 在 React 页面确认 Local Agent 在线；若前端显示离线，先检查浏览器所在电脑是否就是 exe 所在电脑。

任务闭环验收：

1. 通过前端创建 Aw3 `notify_sales` + `paste_only` 任务。
2. 前端必须把新建任务的 `task_id` 传给 19000 `/agent/tasks/poll-and-execute`。
3. 验证执行结果写回 9000：`pasted=true`、`sent=false`。
4. 验证 9000 自动创建或绑定 `detect_reply` 任务。
5. 通过前端按 `task_id` 调用 19000 `/agent/tasks/poll-and-detect`。
6. 验证检测链路只读：`action.sent=false`、`action.pasted=false`。
7. 销售回复后验证 `detected_status`、`detect_count` 回写，前端展示成功或明确失败原因。

失败排查顺序：

1. `/health` 不通：检查 exe 是否启动、19000 是否被旧进程占用、日志 `logs/local_agent.log`。
2. 9000 未收到心跳：检查 `.env` 的 `AUTO_WECHAT_SERVER_URL`、局域网访问、防火墙和 9000 是否启动。
3. 前端显示离线：确认 React 页面调用的是浏览器所在电脑的 `127.0.0.1:19000`。
4. `wechat_status=unavailable`：确认微信由人工打开、未最小化、未托盘隐藏，并与 exe 权限一致。
5. `poll-and-execute` 失败：优先看 `failure_stage`，确认任务类型为 `notify_sales`、目标为 Aw3、模式为 `paste_only`。
6. `poll-and-detect` 失败：确认任务类型为 `detect_reply`，且检测链路没有调用输入框或发送动作。
7. 任何结果出现 `sent=true`：立即停止验收并回滚，不允许作为一期通过结果。

## 附：文档陈旧点

核对过程中发现部分历史文档仍可能记录“9000 未发现 `/agent/status`、`/agent/heartbeat`”之类旧状态。当前代码和 OpenAPI 已存在上述接口。后续整理接口契约文档时建议同步修正，避免误判 Local Agent 能力。
