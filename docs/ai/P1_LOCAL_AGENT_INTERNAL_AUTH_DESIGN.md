# P1-LOCAL-AGENT-INTERNAL-AUTH-DESIGN-1

## 1. 背景和范围

本轮任务是只读审计和安全设计，不改业务代码，不改 19000 exe 链路，不直接给 `/agent/*` 或任务回写接口加鉴权。

当前 Local Agent 链路分为两类：

1. 浏览器用户链路：前端通过 NewCar 登录态访问 9000，用于创建任务、查看任务、查看状态。
2. Local Agent 机器链路：19000 小高AI微信助手代表商户本地 Windows 机器调用 9000，拉取任务、回写执行结果和心跳。

Local Agent 不是浏览器用户，不能直接套 NewCar 用户 token。后续应使用 agent token 或 agent key 映射可信 `merchant_id`，并把任务拉取和回写限制在该商户 / 机器范围内。

本轮不改内容：

1. 不改 19000 exe。
2. 不改现有任务状态机。
3. 不改 `notify_sales` / `detect_reply` 业务语义。
4. 不改 NewCar 登录。
5. 不恢复 `/auth/callback`。
6. 不改 RAG / 知识库。
7. 不改自动发送。
8. 不改前端正式菜单。
9. 不改数据库 migration。
10. 不提交实现代码。

## 2. 审计范围

已扫描模块：

| 范围 | 文件 / 模块 |
| --- | --- |
| 9000 路由 | `app/main.py`、`app/routers/agent.py`、`app/routers/wechat_tasks.py`、`app/routers/replies.py`、`app/routers/lead_notification_actions.py`、`app/routers/lead_notification_records.py`、`app/routers/lead_notifications.py` |
| 9000 服务 | `app/services/agent_status_service.py`、`app/services/wechat_task_service.py`、`app/services/wechat_ui_reply_service.py` |
| 数据模型 / schema | `app/models.py`、`app/schemas.py` |
| 19000 Local Agent | `app/local_agent_main.py`、`app/local_agent_exe_entry.py` |
| 打包 / 配置 | `scripts/build_local_agent_exe.ps1`、`scripts/stop_local_agent.ps1`、`.env.example`、`frontend/.env.example`、`docker-compose.dev.yml` |
| 前端 | `frontend/src/api/localWechatAgent.ts`、`frontend/src/api/agent.ts`、`frontend/src/api/wechatTasks.ts`、`frontend/src/features/wechat-assistant/*` |
| 测试 | `tests/test_agent_status.py`、`tests/test_p0_5a_wechat_tasks.py`、`tests/test_p0_reply_2_agent_write_back.py`、`tests/test_p0_main_5b_poll_and_execute.py`、`tests/test_p1_auto_1c_poll_and_detect.py`、`tests/test_wechat_task_history_api.py` |
| 文档 | `docs/ai/LOCAL_AGENT_FRONTEND_CAPABILITY_REVIEW.md`、`docs/ai/P1_AUTH_PERMISSION_ROUTE_MATRIX.md`、`docs/ai/05_PROJECT_CONTEXT.md`、`docs/ai/P1_END_1_ACCEPTANCE.md` |

## 3. 当前真实调用链

### 3.1 浏览器创建和查看任务

```text
React 微信助手页面
  -> 9000 POST /lead-notifications/send-to-staff
  -> 9000 校验 NewCar RequestContext + auto_wechat:leads + auto_wechat:agent
  -> 创建 wechat_tasks notify_sales
  -> React 调浏览器本机 127.0.0.1:19000 /agent/tasks/poll-and-execute
```

```text
React 任务记录页面
  -> 9000 GET /wechat-tasks
  -> 9000 校验 NewCar RequestContext + auto_wechat:agent
  -> 按 lead/staff 的 merchant_id 过滤任务
```

### 3.2 Local Agent 执行任务

```text
19000 POST /agent/tasks/poll-and-execute
  -> 19000 GET 9000 /wechat-tasks/{task_id} 或 /wechat-tasks/pending
  -> 19000 本机微信 UI 自动化
  -> 19000 POST 9000 /wechat-tasks/{task_id}/result
```

```text
19000 POST /agent/tasks/poll-and-detect
  -> 19000 GET 9000 /wechat-tasks/{task_id} 或 /wechat-tasks/pending
  -> 19000 只读读取微信消息
  -> 19000 POST 9000 /replies/agent-write-back
  -> 19000 POST 9000 /wechat-tasks/{task_id}/result
```

### 3.3 Local Agent 心跳

```text
19000 heartbeat daemon
  -> POST 9000 /agent/heartbeat
  -> 9000 内存保存最新心跳
  -> 浏览器 GET 9000 /agent/status 查看聚合状态
```

## 4. 当前接口清单

### 4.1 9000 相关接口

| Method | Path | 文件 | 调用方 | 被调用方 | 浏览器调用 | Local Agent 调用 | 当前认证 | 风险等级 | 后续建议 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/agent/status` | `app/routers/agent.py` | React | 9000 | 是 | 否 | 无 NewCar 依赖 | 中 | 浏览器状态接口，建议补 NewCar `auto_wechat:agent` 或确认只读公开策略 |
| POST | `/agent/heartbeat` | `app/routers/agent.py` | 19000 | 9000 | 否 | 是 | 无 agent auth | 高 | 后续加 Local Agent 内部认证，不套 NewCar |
| POST | `/wechat-tasks` | `app/routers/wechat_tasks.py` | React / 测试 | 9000 | 是 | 否 | 当前无依赖 | 高 | 浏览器创建任务应走 NewCar `auto_wechat:agent`；既有 `send-to-staff` 已有权限，裸创建需单独收口 |
| GET | `/wechat-tasks` | `app/routers/wechat_tasks.py` | React | 9000 | 是 | 否 | NewCar required + `auto_wechat:agent` | 中 | 保持浏览器权限和 merchant 过滤 |
| GET | `/wechat-tasks/pending` | `app/routers/wechat_tasks.py` | React / 19000 | 9000 | 是 | 是 | 无认证，无 merchant 过滤 | 高 | 拆分浏览器读取和 Agent 拉取语义；Agent 拉取必须按 agent merchant 过滤 |
| GET | `/wechat-tasks/{task_id}` | `app/routers/wechat_tasks.py` | React / 19000 | 9000 | 是 | 是 | NewCar required + `auto_wechat:agent` | 高 | 19000 当前若无 NewCar token 会在强认证后断链；后续需支持 agent auth 分支 |
| POST | `/wechat-tasks/{task_id}/result` | `app/routers/wechat_tasks.py` | 19000 | 9000 | 否 | 是 | 无 agent auth | 高 | 加 agent auth，并校验 task 属于 agent merchant |
| POST | `/replies/agent-write-back` | `app/routers/replies.py` | 19000 | 9000 | 否 | 是 | 无 agent auth | 高 | 加 agent auth，并校验 task_id / lead_id / staff_id 同属 agent merchant |
| POST | `/lead-notifications/send-to-staff` | `app/routers/lead_notification_actions.py` | React | 9000 | 是 | 否 | NewCar required + `auto_wechat:leads` + `auto_wechat:agent` | 中 | 保持浏览器权限，不属于 agent 内部认证 |
| GET | `/lead-notifications/records` | `app/routers/lead_notification_records.py` | React | 9000 | 是 | 否 | NewCar required + `auto_wechat:leads` | 低 | 保持浏览器权限和 merchant 过滤 |
| POST | `/replies/manual` | `app/routers/replies.py` | 历史 / 测试 | 9000 | 不明确 | 否 | 无认证 | 高 | 历史写入口，后续下线或补浏览器权限 + 归属校验 |
| POST | `/replies/current-wechat-detect` | `app/routers/replies.py` | 历史前端封装 | 9000 | 可能 | 否 | 无认证 | 高 | 与 19000 边界冲突，建议下线或仅内部调试 |
| `/replies/debug/*` | `app/routers/replies.py` | 调试 | 9000 | 不明确 | 否 | 无认证 | 高 | 开发开关 / 内网白名单 / 下线候选 |

说明：`app/main.py` 总是注册 `agent.router`、`wechat_tasks.router`、`replies.router`、`lead_notification_actions.router` 和 `lead_notification_records.router`。Windows 专用旧 `lead_notifications.router` 仅在导入成功时注册，里面含直接操作 9000 所在机器微信的旧接口，当前主线不应依赖。

### 4.2 19000 本地接口

| Method | Path | 文件 | 调用方 | 是否触发微信动作 | 当前认证 | 风险等级 | 后续建议 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/health` | `app/local_agent_main.py` | 浏览器本机 | 否 | 无 | 低 | 保持本机健康检查，默认 127.0.0.1 |
| GET | `/agent/version` | `app/local_agent_main.py` | 浏览器本机 / 打包烟测 | 否 | 无 | 中 | 诊断用；避免公网暴露 |
| GET | `/runtime/status` | `app/local_agent_main.py` | 浏览器本机 | 否 | 无 | 中 | 本机 UI 状态，可保留 |
| POST | `/runtime/enable-task-polling` | `app/local_agent_main.py` | 浏览器本机 | 会开启后台轮询 | 无 | 高 | 后续如启用，应至少要求本机确认和 agent auth 配置就绪 |
| POST | `/runtime/disable-task-polling` | `app/local_agent_main.py` | 浏览器本机 | 停止轮询 | 无 | 中 | 可保留 |
| GET | `/agent/ocr/status` | `app/local_agent_main.py` | 浏览器本机 | 否 | 无 | 低 | 保持诊断 |
| POST | `/agent/ocr/warmup` | `app/local_agent_main.py` | 浏览器本机 | 否，仅 OCR 预热 | 无 | 中 | 保持诊断，避免公网暴露 |
| GET | `/agent/wechat/windows` | `app/local_agent_main.py` | 浏览器本机 | 否，仅窗口枚举 | 无 | 中 | 可能暴露窗口信息，保持 127.0.0.1 |
| POST | `/agent/wechat/foreground-debug` | `app/local_agent_main.py` | 浏览器本机 | 会切前台 | 无 | 高 | 调试入口，后续内部化或本机确认 |
| POST | `/agent/wechat/search-debug` | `app/local_agent_main.py` | 浏览器本机 | 会操作搜索框诊断 | 无 | 高 | 调试入口，保持 safe JSON，后续内部化 |
| POST | `/agent/wechat/search-calibration/start` | `app/local_agent_main.py` | 浏览器本机 | 校准搜索框 | 无 | 高 | 调试入口，后续内部化 |
| POST | `/agent/wechat/search-result-debug` | `app/local_agent_main.py` | 浏览器本机 | 会搜索诊断 | 无 | 高 | 调试入口，保持 safe JSON，后续内部化 |
| POST | `/agent/wechat/mouse-debug` | `app/local_agent_main.py` | 浏览器本机 | 移动鼠标，不点击 | 无 | 中 | 诊断入口，后续内部化 |
| POST | `/agent/wechat/test` | `app/local_agent_main.py` | 浏览器本机 | Aw3 测试 / paste_only | 无 | 高 | 不改；后续本机确认 + 开发开关 |
| GET | `/agent/tasks/server-url` | `app/local_agent_main.py` | 浏览器本机 | 否 | 无 | 中 | 会暴露 9000 地址，避免公网暴露 |
| POST | `/agent/tasks/poll-and-execute` | `app/local_agent_main.py` | 浏览器本机 / runtime loop | 会执行 notify_sales | 无 | 高 | 19000 本机入口仍靠 127.0.0.1；9000 侧必须加 agent auth |
| POST | `/agent/tasks/poll-and-detect` | `app/local_agent_main.py` | 浏览器本机 / runtime loop | 只读 detect_reply | 无 | 高 | 9000 侧必须加 agent auth |
| POST | `/agent/replies/detect` | `app/local_agent_main.py` | 浏览器本机 | 只读消息并回写 9000 | 无 | 高 | 旧兼容入口，后续建议迁到 poll-and-detect 或加同等 agent auth |

## 5. 数据模型清单

| 对象 | 当前字段 / 事实 | 安全含义 |
| --- | --- | --- |
| `WechatTask` / `wechat_tasks` | `task_type`、`lead_id`、`staff_id`、`reply_check_id`、`target_nickname`、`message`、`mode`、`status`、`failure_stage`、`raw_result`、`agent_hostname`、`agent_pid` | 任务没有 `merchant_id`、`agent_id`、`machine_id` 字段；归属只能通过关联 lead/staff 推导 |
| `LeadNotification` | `lead_id`、`staff_id`、`check_id`、`send_status`、`send_mode`、`notification_text`、`chat_title`、`error_message` | 通知记录也不直接保存 agent 归属 |
| `ReplyCheck` | `lead_id`、`staff_id`、`check_status`、`reply_content`、`is_effective` | `agent-write-back` 会按 lead/staff 查 pending check 并可能更新 lead 状态 |
| `DouyinLead` | 有 `merchant_id`、`assigned_staff_id` | 可作为任务归属的主要 merchant 来源 |
| `SalesStaff` | 有 `merchant_id`、`wechat_nickname` | 可作为任务归属的辅助 merchant 来源 |
| Local Agent 心跳 | 只在 `agent_status_service` 内存 `_latest_heartbeat` 保存 | 不持久化，不支持多 agent，不支持 merchant 绑定 |
| Local Agent 配置 | `AUTO_WECHAT_AGENT_CLIENT_ID`、`AUTO_WECHAT_AGENT_NAME`、`AUTO_WECHAT_SERVER_URL`、`LOCAL_AGENT_HOST`、`LOCAL_AGENT_PORT` | 只有客户端 ID / 名称和服务地址，没有 secret |

当前没有 `local_agents` 表，没有 agent 与 merchant 的绑定关系，也没有 token 版本、吊销状态、允许 IP 或最后心跳持久化字段。

## 6. 当前认证现状

事实：

1. 19000 默认监听 `127.0.0.1:19000`，不进入 Docker。
2. `app/local_agent_exe_entry.py` 默认 `LOCAL_AGENT_HOST=127.0.0.1`，打包脚本也写入 `LOCAL_AGENT_HOST=127.0.0.1`。
3. 19000 调 9000 的 `_http_get` / `_http_post_json` 当前没有携带 agent token。
4. 9000 `/agent/heartbeat`、`/wechat-tasks/pending`、`/wechat-tasks/{task_id}/result`、`/replies/agent-write-back` 当前没有 agent auth。
5. 浏览器侧 `GET /wechat-tasks` 和 `GET /wechat-tasks/{task_id}` 已有 NewCar + `auto_wechat:agent`，但同一路径也被 19000 指定 task_id 拉取复用。
6. `GET /wechat-tasks/pending` 同时被浏览器和 19000 使用，当前无认证也无 merchant 过滤。

结论：当前 Local Agent 内部链路主要依赖“19000 只监听本机”和“9000 不主动暴露给陌生调用方”的环境假设，没有机器身份认证。

## 7. 风险分析

| 风险 | 当前判断 | 证据 | 等级 | 建议 |
| --- | --- | --- | --- | --- |
| 伪造心跳 | 存在 | `POST /agent/heartbeat` 无认证，只写内存 | 高 | agent token / key |
| 任意拉取 pending 任务 | 存在 | `GET /wechat-tasks/pending` 无认证，无 merchant 过滤 | 高 | Agent 认证后按 agent merchant 过滤 |
| 任意回写任务完成 | 存在 | `POST /wechat-tasks/{task_id}/result` 无认证 | 高 | Agent 认证 + task 归属校验 |
| 跨 merchant 拉任务 | 存在设计缺口 | 任务表无 `merchant_id` / `agent_id`，pending 查询未 join 过滤 | 高 | 使用 agent identity 映射 merchant 后过滤 lead/staff |
| 伪造 detect_reply 更新线索 | 存在 | `/replies/agent-write-back` 无认证，可按 lead_id/staff_id 写状态 | 高 | Agent 认证 + task/lead/staff 同属校验 |
| debug 接口触发微信动作 | 存在 | 19000 `/agent/wechat/*` 本机无认证，部分会前台/搜索/粘贴 | 高 | 保持 127.0.0.1，后续本机 UI 确认 / debug 开关 |
| 只靠局域网信任 | 部分存在 | 9000 被 19000 调用入口无 token；若 9000 在反代或公网可达，风险扩大 | 高 | 不依赖 IP，至少 token |
| 公网反代暴露 | 需部署确认 | 当前代码不区分反代路径；9000 主服务可能经宝塔暴露 | 高 | 文档和 Nginx 层禁止暴露 agent 内部入口，代码侧仍需认证 |
| 日志泄露敏感信息 | 部分存在 | raw_result、notification_text、消息内容可能入库或日志摘要 | 中 | token 不入日志，消息内容按必要脱敏 |
| 旧接口绕开任务队列 | 存在 | `/replies/current-wechat-detect`、旧 `lead_notifications.py` 会在 9000 侧直接操作微信 | 高 | 下线候选或内部白名单，不包装成正式浏览器能力 |

## 8. 方案对比

### 方案 1：静态 Agent Token

每个 Local Agent 配置固定 token。19000 调 9000 时携带：

```text
Authorization: Bearer <agent_token>
```

或：

```text
X-Local-Agent-Token: <agent_token>
```

9000 校验 token 后得到 agent identity 和 merchant_id，再允许 heartbeat / poll / result submit。

优点：

1. 最小改造，适合现有 exe 灰度。
2. 与现有 9100 `X-Internal-Service-Token` 思路接近，开发和部署成本低。
3. 便于先做兼容模式，不立即打断现场。

缺点：

1. token 泄露后可复用。
2. 防重放能力弱。
3. 多 agent / 多商户扩展需要表化或 token 版本管理。

### 方案 2：Agent Key + Secret + HMAC 签名

每个 Local Agent 有 `agent_key` / `agent_secret`。请求头：

```text
X-Agent-Key
X-Agent-Timestamp
X-Agent-Nonce
X-Agent-Signature
```

签名内容：

```text
method + path + body_sha256 + timestamp + nonce
```

9000 校验 key、secret、timestamp、nonce 和 agent 状态，再映射 merchant_id。

优点：

1. 可防重放。
2. 更适合公网或复杂反代环境。
3. 支持禁用、轮换、审计和多 agent。

缺点：

1. 19000 exe 和 9000 都要改，现场升级成本更高。
2. 需要 nonce 存储或缓存，涉及新表 / 缓存。
3. 不适合作为第一步强切。

### 方案 3：内网 IP 白名单 + Agent Token

9000 先限制来源 IP，再校验 agent token。

优点：

1. 对宝塔 / LAN 场景有额外保护。
2. 适合作为过渡期外层防线。

缺点：

1. 不能只依赖 IP，NAT、代理、X-Forwarded-For 都可能导致误判或绕过。
2. 客户 Windows 环境 IP 可能变化，运维成本较高。

## 9. 推荐方案

推荐分阶段方案：先静态 token 兼容灰度，再表化，再升级 HMAC。

### Phase A：只读观测

目标：不拦截现有请求，只记录缺失 agent auth 的来源。

建议：

1. 在 9000 内部 agent 入口记录来源 IP、User-Agent、路径、是否携带 agent auth。
2. 不记录 token 明文。
3. 不改变响应。

适用接口：

- `/agent/heartbeat`
- `/wechat-tasks/pending`
- `/wechat-tasks/{task_id}/result`
- `/replies/agent-write-back`

### Phase B：兼容鉴权

目标：新增 token 校验但不强制。

配置建议：

```text
LOCAL_AGENT_AUTH_REQUIRED=false
LOCAL_AGENT_SHARED_TOKEN=<非空随机值，生产必须配置>
LOCAL_AGENT_AUTH_OBSERVE_ONLY=true
```

行为：

1. 有 token 时校验并记录 agent identity。
2. 无 token 时兼容放行但 warning。
3. 错 token 记录 warning；是否拒绝由灰度开关控制。
4. token 不进入前端 `VITE_*`。

### Phase C：灰度强制

目标：指定 merchant / agent 强制 token。

配置建议：

```text
LOCAL_AGENT_AUTH_REQUIRED=false
LOCAL_AGENT_AUTH_ENFORCED_AGENT_KEYS=agent-a,agent-b
LOCAL_AGENT_AUTH_ENFORCED_MERCHANT_IDS=merchant-a
```

行为：

1. 灰度名单内无 token / 错 token 拒绝。
2. 灰度名单外兼容放行并 warning。

### Phase D：全量强制

目标：所有 Local Agent 内部入口必须通过 agent auth。

配置：

```text
LOCAL_AGENT_AUTH_REQUIRED=true
```

行为：

1. 无 token 返回 401。
2. token 错误返回 401。
3. token 合法但 agent disabled / merchant 不匹配返回 403。
4. 任务不属于 agent merchant 返回 404 或 403，建议对外用 404 避免暴露任务存在性。

### Phase E：HMAC 升级

目标：在 token 方案稳定后，引入 `agent_key + secret + HMAC`。

行为：

1. `agent_key` 映射 `local_agents` 记录。
2. `agent_secret_hash` 不明文落库。
3. `timestamp` 超时拒绝。
4. `nonce` 重放拒绝。
5. 支持 token / HMAC 双栈过渡。

## 10. 推荐数据结构

### 10.1 最小兼容版

第一步可不新增表，仅使用环境变量：

```text
LOCAL_AGENT_SHARED_TOKEN
LOCAL_AGENT_AUTH_REQUIRED
LOCAL_AGENT_AUTH_OBSERVE_ONLY
```

缺点是无法区分商户和机器，不足以解决跨 merchant 风险，只能作为短期过渡。

### 10.2 推荐表化版

后续建议新增 `local_agents`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `merchant_id` | 可信商户 ID |
| `agent_key` | Agent 公开标识 |
| `agent_secret_hash` | secret 哈希，不存明文 |
| `display_name` | 展示名 |
| `machine_fingerprint` | 机器指纹摘要 |
| `allowed_ip_cidrs` | 可选来源网段 |
| `status` | `active/disabled/revoked/deleted` |
| `last_heartbeat_at` | 最近心跳 |
| `last_ip` | 最近来源 IP |
| `token_version` | 轮换版本 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `revoked_at` | 吊销时间 |

HMAC 版本需要 `local_agent_nonces` 或缓存：

| 字段 | 说明 |
| --- | --- |
| `agent_key` | Agent 公开标识 |
| `nonce` | 请求随机串 |
| `expires_at` | 过期时间 |

### 10.3 任务归属增强建议

最小实现可通过 `WechatTask.lead.merchant_id` 或 `WechatTask.staff.merchant_id` 判断归属。

中期建议给 `wechat_tasks` 增加：

| 字段 | 说明 |
| --- | --- |
| `merchant_id` | 创建任务时写入可信 merchant |
| `local_agent_id` | 分配给哪个 Local Agent，可为空表示未绑定 |
| `claimed_at` | 被 Agent 拉取时间 |

本轮不做 migration，只记录设计建议。

## 11. 接口认证矩阵

| 接口 | 调用方 | 当前认证 | 推荐认证 | 是否需 merchant 绑定 | 灰度策略 |
| --- | --- | --- | --- | --- | --- |
| `GET /agent/status` | 浏览器 | 无 | NewCar `auto_wechat:agent` 或确认只读公开 | 是，若展示商户状态 | 可先不拦截，仅文档确认 |
| `POST /agent/heartbeat` | 19000 | 无 | Agent Token，后续 HMAC | 是 | A 观测、B 兼容、C/D 强制 |
| `GET /wechat-tasks/pending` | 浏览器 / 19000 | 无 | 浏览器用 NewCar；Agent 用 Agent Token | 是 | 先增加 agent 分支，不破坏浏览器 |
| `GET /wechat-tasks/{task_id}` | 浏览器 / 19000 | NewCar | 浏览器 NewCar；Agent Token 兼容分支 | 是 | 先允许 NewCar 或 Agent 二选一 |
| `POST /wechat-tasks/{task_id}/result` | 19000 | 无 | Agent Token，校验任务归属 | 是 | A/B 观测兼容，C/D 强制 |
| `POST /replies/agent-write-back` | 19000 | 无 | Agent Token，校验 task/lead/staff 归属 | 是 | A/B 观测兼容，C/D 强制 |
| `POST /lead-notifications/send-to-staff` | 浏览器 | NewCar + `leads` + `agent` | 保持 NewCar | 是 | 不纳入 agent auth |
| `GET /lead-notifications/records` | 浏览器 | NewCar + `leads` | 保持 NewCar | 是 | 不纳入 agent auth |
| `POST /replies/current-wechat-detect` | 历史浏览器 / 调试 | 无 | 下线或内部白名单 | 是 | 单独任务确认 |
| `/replies/debug/*` | 调试 | 无 | 开发开关 / 内网白名单 / 下线 | 否 | 单独任务确认 |
| `19000 /agent/tasks/poll-and-execute` | 浏览器本机 | 无 | 维持本机边界；后续本机 UI 确认 | 不直接绑定 | 不从 9000 强制 NewCar |
| `19000 /agent/tasks/poll-and-detect` | 浏览器本机 | 无 | 维持本机边界；后续本机 UI 确认 | 不直接绑定 | 不从 9000 强制 NewCar |
| `19000 /runtime/enable-task-polling` | 浏览器本机 | 无 | 后续加本机确认 / 开关 | 不直接绑定 | 暂不强改 |

## 12. 与 NewCar 权限关系

1. 浏览器用户接口继续使用 NewCar RequestContext + permission_codes。
2. Local Agent 接口不使用 NewCar 用户 token。
3. Local Agent 代表商户机器身份，不代表某个浏览器用户。
4. 9000 必须通过 agent token / agent key 映射 merchant_id。
5. 任务拉取必须限制在该 merchant_id 范围内。
6. 不能允许请求体伪造 merchant_id。
7. 任务回写必须校验任务属于该 agent / merchant。
8. 浏览器创建任务和 Local Agent 拉任务应分清入口语义，不能因为同一路径复用就把 NewCar required 强套给 19000。

## 13. 安全规则

后续实现必须遵守：

1. token / secret 不进入前端 `VITE_*`。
2. token / secret 不进入日志。
3. 错误响应不回显 token。
4. 支持 token 轮换。
5. 支持禁用 / 吊销 Agent。
6. 支持最后心跳时间记录。
7. 支持异常来源 IP 记录。
8. `detect_reply` 回写必须绑定任务 id。
9. `notify_sales` 完成回写必须绑定任务 id。
10. 不能通过任意接口直接触发真实微信发送。
11. `paste_only` / `manual_confirmed` 安全边界保持不变。
12. 19000 本地 UI 不暴露 secret 明文。
13. 9000 的公网反代配置不应暴露未保护的 agent 内部入口；即使反代限制存在，代码仍应有认证。

## 14. 错误码建议

| 场景 | HTTP | code |
| --- | --- | --- |
| 缺少 agent token | 401 | `LOCAL_AGENT_TOKEN_MISSING` |
| agent token 错误 | 401 | `LOCAL_AGENT_TOKEN_INVALID` |
| agent 已禁用 / 吊销 | 403 | `LOCAL_AGENT_DISABLED` |
| agent 未绑定商户 | 403 | `LOCAL_AGENT_MERCHANT_NOT_BOUND` |
| 任务不属于 agent merchant | 404 或 403 | `WECHAT_TASK_NOT_FOUND` / `LOCAL_AGENT_TASK_FORBIDDEN` |
| task_id 缺失但接口必须绑定任务 | 400 | `WECHAT_TASK_ID_REQUIRED` |
| HMAC timestamp 过期 | 401 | `LOCAL_AGENT_SIGNATURE_EXPIRED` |
| nonce 重放 | 401 | `LOCAL_AGENT_NONCE_REPLAYED` |

建议对外任务不存在性使用 404，内部审计日志记录真实原因。

## 15. 测试计划

后续实现时至少覆盖：

| 场景 | 类型 | 输入 / 操作 | 预期结果 |
| --- | --- | --- | --- |
| 无 token 心跳 | 接口 | `POST /agent/heartbeat` 无 token | 兼容期 200 + warning；强制期 401 |
| 错 token 心跳 | 接口 | 错误 token | 401 |
| 正确 token 心跳 | 接口 | 正确 token | 200，记录 agent identity |
| Agent A 拉 pending | 接口 | Agent A token 调 `/wechat-tasks/pending` | 只返回 Merchant A 任务 |
| 请求体伪造 merchant_id | 安全 | body/query 带 Merchant B | 不生效 |
| revoked agent 拉任务 | 接口 | revoked token | 403 |
| result submit 越权 | 接口 | Agent A 回写 Merchant B task | 404/403，不改状态 |
| agent-write-back 越权 | 接口 | Agent A 带 B 的 lead/staff/task | 404/403，不改 ReplyCheck |
| HMAC 超时 | 安全 | 过期 timestamp | 401 |
| nonce 重放 | 安全 | 重复 nonce | 401 |
| debug 绕过 | 安全 | 调 debug 入口 | 不能绕过 agent auth 或必须内部化 |
| 浏览器状态查询 | 回归 | `GET /agent/status` | 仍按 NewCar 或已确认策略返回 |
| 任务记录页面 | 回归 | `GET /wechat-tasks` | 仍按 merchant 隔离 |
| 19000 安全门禁 | 回归 | poll-and-detect | `action.sent=false`、`action.pasted=false` |
| notify_sales 安全门禁 | 回归 | poll-and-execute paste_only | 不绕过现有联系人验证和发送边界 |

建议后续实现阶段运行：

```bash
python -m pytest tests/test_agent_status.py -q
python -m pytest tests/test_p0_5a_wechat_tasks.py -q
python -m pytest tests/test_p0_reply_2_agent_write_back.py -q
python -m pytest tests/test_p0_main_5b_poll_and_execute.py -q
python -m pytest tests/test_p1_auto_1c_poll_and_detect.py -q
python -m pytest tests/test_wechat_task_history_api.py -q
```

本轮只新增设计文档，不需要跑 pytest。

## 16. 待确认事项

1. 生产部署中 9000 的 `/agent/*`、`/wechat-tasks/*`、`/replies/agent-write-back` 是否会经宝塔公网反代暴露。
2. 首期是否允许一个商户多个 Local Agent；当前 PRD 多处写第一版一个商户一台，但后续提到每商户 20 个销售微信。
3. Agent token 是每商户一个、每机器一个，还是每 Windows 用户一个。
4. token 首次下发方式：人工写入 exe 同目录 `.env`，还是后台生成后离线分发。
5. 任务是否需要显式绑定 `local_agent_id`，还是只按 `merchant_id` 池化拉取。
6. `GET /wechat-tasks/pending` 是否继续给浏览器显示 pending 列表；若继续，需要补 NewCar 过滤并给 Agent 单独兼容分支。
7. `POST /wechat-tasks` 裸创建接口是否仍允许测试使用；若正式商户只能走 `/lead-notifications/send-to-staff`，建议后续锁定。
8. `/replies/current-wechat-detect` 和 `/replies/debug/*` 是否可以下线或仅开发环境启用。
9. 19000 `/runtime/enable-task-polling` 是否允许商户前端一键开启后台轮询，还是需要管理员 / 本机确认。
10. HMAC 升级是否需要持久化 nonce，还是可用短期缓存。

## 17. 推荐下一步任务名

1. `P1-LOCAL-AGENT-AUTH-OBSERVABILITY-1`
   - 只加观测日志，不拦截请求。
   - 记录缺失 agent auth 的内部入口调用来源。

2. `P1-LOCAL-AGENT-TOKEN-COMPAT-GATE-1`
   - 增加兼容模式 agent token 校验。
   - `LOCAL_AGENT_AUTH_REQUIRED=false` 默认不打断现场。

3. `P1-WECHAT-TASK-AGENT-MERCHANT-SCOPE-FIX-1`
   - 拆清浏览器任务查询和 Agent 拉取语义。
   - Agent 拉取 / 回写按 agent merchant 限制。

4. `P1-LEGACY-WECHAT-DEBUG-ENDPOINTS-LOCKDOWN-1`
   - 收口 `/replies/current-wechat-detect`、`/replies/debug/*` 和旧 9000 直操微信入口。

