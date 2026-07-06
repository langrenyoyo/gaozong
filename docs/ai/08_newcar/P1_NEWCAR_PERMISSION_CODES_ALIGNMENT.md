# P1-NEWCAR-PERMISSION-CODES-ALIGNMENT-1

## 1. 背景和范围

本轮只做 NewCarProject 权限码对齐调查，不改代码、不改权限映射、不改后端门禁。

目标是确认以下三层是否一致：

- NewCarProject `/auth/me` 返回的 `permission_codes`
- auto_wechat 前端能力中心的路由权限映射
- `/wechat-assistant` 页面初始化 API 的后端权限门禁

重点现象：

- `/douyin-cs`、`/leads`、`/compute` 可进入。
- `/agents` 可进入，对应 AI 小高智能体。
- `/wechat-assistant` 暂不可进入。
- 之前调查未拿到有效登录态下的真实 `permission_codes`。

## 2. 本轮运行态证据

### 2.1 工作区状态

执行 `git status --short` 时工作区为空，调查开始时没有未提交改动。

### 2.2 前端运行环境

`frontend/.env` 当前关键配置：

| 配置项 | 当前值 | 判断 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://192.168.110.113:9000` | 主 API 指向开发主机 9000 |
| `VITE_AUTO_WECHAT_API_BASE_URL` | `http://192.168.110.113:9000` | 主 API 备用值同样指向开发主机 9000 |
| `VITE_LOCAL_WECHAT_AGENT_BASE_URL` | `http://127.0.0.1:19000` | 符合本机 Agent 设计 |
| `VITE_NEWCAR_AUTH_BASE_URL` | `http://192.168.110.19:8790` | NewCar 授权服务 |
| `VITE_NEWCAR_LOGIN_URL` | `http://192.168.110.19:5174/login` | NewCar 登录页 |

未发现主 API 运行态配置指向 `127.0.0.1:9000` 的证据。

### 2.3 9000 与 19000 可达性

无 token 访问以下接口均返回 401，符合当前 NewCar 鉴权预期：

- `GET http://127.0.0.1:9000/auth/me`
- `GET http://192.168.110.113:9000/auth/me`

本机 Agent 健康检查正常：

- `GET http://127.0.0.1:19000/health`
- 返回在线，服务名为 `auto_wechat_local_agent`，端口为 `19000`。

### 2.4 真实登录态证据缺口

本轮未能自动采集浏览器 `external_token` 和 Network 响应：

- 本机没有可用的 Playwright 依赖。
- 已打开的 Edge 窗口没有远程调试端口，不能安全读取 sessionStorage/localStorage。
- 因此没有拿到有效 token 下的真实 `/auth/me` 响应。

结论：`/wechat-assistant` 不可进入的最终根因仍需要人工补充真实 `/auth/me.permission_codes` 后确认。

## 3. 前端权限映射

来源文件：

- `frontend/src/features/capabilities.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/SideNav.tsx`

前端权限常量：

| 能力 | 路由 | 前端权限要求 |
|---|---|---|
| 抖音AI小高客服 | `/douyin-cs/workbench` | `auto_wechat:douyin_ai_cs` |
| AI小高线索 | `/leads` | `auto_wechat:leads` |
| AI小高智能体 | `/agents` | `auto_wechat:agent` |
| 小高AI微信助手 | `/wechat-assistant` | `auto_wechat:agent` |
| 小高算力 | `/compute/center` | `auto_wechat:compute` |

前端对 `auto_wechat:agent` 有历史别名兼容：

- `auto_wechat:wechat_assistant`
- `auto_wechat:wechat_agent`
- `auto_wechat:ai_agents`

因此，只从前端路由层看：

- `/agents` 和 `/wechat-assistant` 使用同一组 `auto_wechat:agent` 权限。
- 如果用户能进入 `/agents`，理论上前端路由层也应允许 `/wechat-assistant`。
- 若运行态 `/agents` 可进而 `/wechat-assistant` 不可进，需要继续检查运行态版本、真实用户权限、路由跳转状态、页面初始化 API 和浏览器缓存。

## 4. 后端 API 门禁

来源文件：

- `app/auth/context.py`
- `app/auth/dependencies.py`
- `app/routers/agent.py`
- `app/routers/wechat_tasks.py`
- `app/routers/staff.py`
- `app/routers/agents.py`
- `app/routers/compute.py`
- `app/routers/douyin_ai_cs_proxy.py`

后端 `RequestContext.has_permission()` 只认精确权限码或 `super_admin`，没有前端的 alias 逻辑。

| API | 用途 | 当前门禁 |
|---|---|---|
| `GET /agent/status` | 读取 Agent 状态 | 当前无 NewCar 门禁，公开只读 |
| `GET /staff` | 微信助手销售配置 | 需要登录态 + `auto_wechat:agent` |
| `GET /wechat-tasks` | 微信任务历史 | 需要登录态 + `auto_wechat:agent` |
| `GET /wechat-tasks/pending` | Local Agent pending 队列 | Local Agent 兼容 token gate，不要求浏览器 NewCar token |
| `GET /agents` 等 | AI 小高智能体 | `auto_wechat:ai_agents` 或 `auto_wechat:agent` |
| `GET /compute/*` | 小高算力商户侧 | `auto_wechat:compute` 或过渡兼容 `auto_wechat:agent` |
| `POST /integrations/douyin-ai-cs/*` | 抖音AI客服代理 | `auto_wechat:douyin_ai_cs` |

## 5. /wechat-assistant 页面初始化 API

来源文件：`frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`

页面初始化会并行请求：

| API | 端口 | 鉴权/门禁 | 失败影响 |
|---|---|---|---|
| `GET /agent/status` | 9000 | 无 NewCar 门禁 | 单独 catch，失败不阻断页面 |
| `GET /staff` | 9000 | `auto_wechat:agent` | 未单独 catch，401/403 会进入整体错误提示 |
| `GET /wechat-tasks/pending` | 9000 | Local Agent 兼容 token gate | 未单独 catch |
| `GET /wechat-tasks` | 9000 | `auto_wechat:agent` | 单独 catch，失败不阻断其它数据 |
| `GET /health` | 19000 | 本机 Agent | 单独 catch，失败不阻断页面 |
| `GET /runtime/status` | 19000 | 本机 Agent | 单独 catch，失败不阻断页面 |

因此，如果前端路由允许进入但页面加载失败，最需要看：

- `GET /staff` 是否返回 403 `PERMISSION_DENIED`
- `GET /wechat-tasks/pending` 是否因 Local Agent token gate 或其它异常失败
- `GET /wechat-tasks` 是否返回 403 `PERMISSION_DENIED`

## 6. 对齐表

| 功能 | 路由 | 前端权限要求 | `/auth/me` 是否返回 | 页面内 API | API 状态 | 判断 |
|---|---|---|---|---|---|---|
| 抖音AI小高客服 | `/douyin-cs/workbench` | `auto_wechat:douyin_ai_cs` | 未取得真实列表 | `/integrations/douyin-ai-cs/*` | 代码要求同权限 | 已知运行态可进入，需用真实 `/auth/me` 复核 |
| AI小高线索 | `/leads` | `auto_wechat:leads` | 未取得真实列表 | `/leads/*` | 需结合具体接口复核 | 已知运行态可进入，需用真实 `/auth/me` 复核 |
| AI小高智能体 | `/agents` | `auto_wechat:agent`，前端兼容 `auto_wechat:ai_agents` 等别名 | 未取得真实列表 | `/agents/*` | 后端允许 `auto_wechat:ai_agents` 或 `auto_wechat:agent` | 若只返回 `auto_wechat:ai_agents`，智能体可进是符合代码的 |
| 小高AI微信助手 | `/wechat-assistant` | `auto_wechat:agent`，前端兼容 `auto_wechat:wechat_assistant`、`auto_wechat:wechat_agent`、`auto_wechat:ai_agents` | 未取得真实列表 | `/staff`、`/wechat-tasks`、`/wechat-tasks/pending`、`/agent/status` | `/staff` 和 `/wechat-tasks` 只认 `auto_wechat:agent` | 存在前后端 alias 不一致风险 |
| 小高算力 | `/compute/center` | `auto_wechat:compute` | 未取得真实列表 | `/compute/*` | 后端允许 `auto_wechat:compute` 或 `auto_wechat:agent` | 已知运行态可进入，需用真实 `/auth/me` 复核 |

## 7. 已确认的不一致风险

### 7.1 前端 alias 与后端精确门禁不一致

前端把以下权限都视为 `auto_wechat:agent`：

- `auto_wechat:agent`
- `auto_wechat:wechat_assistant`
- `auto_wechat:wechat_agent`
- `auto_wechat:ai_agents`

后端 `/staff` 和 `/wechat-tasks` 只认：

- `auto_wechat:agent`

这会导致一种可复现的风险形态：

- 如果 NewCarProject 只返回 `auto_wechat:ai_agents`，用户可能能进入 `/agents`。
- 前端也可能允许进入 `/wechat-assistant`。
- 但 `/wechat-assistant` 初始化时的 `/staff`、`/wechat-tasks` 会被后端 403。

### 7.2 `/agents` 与 `/wechat-assistant` 业务含义被同一前端权限覆盖

当前 `/agents` 和 `/wechat-assistant` 都使用前端 `PERMISSIONS.agent`。

但后端注释已经提示：

- AI 小高智能体正式权限应为 `auto_wechat:ai_agents`。
- 微信助手/微信代理后续应使用独立权限，例如 `auto_wechat:wechat_agent`。

这说明两个产品能力需要进一步拆分权限语义。当前共用 `auto_wechat:agent` 属于过渡状态。

## 8. 需要人工补充的真实证据

请在浏览器真实登录后，从 Network 里采集 `GET /auth/me` 响应摘要。不要记录 token。

建议记录字段：

- `merchant_id`
- `source_system`
- `external_user_id` 或 `user_id`
- `external_account` 或 `username`，需脱敏
- `permission_codes` 完整列表

同时访问以下路由并记录：

| 路由 | 是否进入 | 菜单是否显示 | 是否权限不足 | 是否跳转 |
|---|---|---|---|---|
| `/douyin-cs/workbench` | 待人工复核 | 待人工复核 | 待人工复核 | 待人工复核 |
| `/leads` | 待人工复核 | 待人工复核 | 待人工复核 | 待人工复核 |
| `/compute/center` | 待人工复核 | 待人工复核 | 待人工复核 | 待人工复核 |
| `/agents` | 待人工复核 | 待人工复核 | 待人工复核 | 待人工复核 |
| `/wechat-assistant` | 待人工复核 | 待人工复核 | 待人工复核 | 待人工复核 |

在 `/wechat-assistant` 页面 Network 里重点记录：

| API | method | status | 错误码 | 备注 |
|---|---|---|---|---|
| `/api/agent/status` 或 `/agent/status` | GET | 待人工复核 | 待人工复核 | 只读状态 |
| `/api/staff` 或 `/staff` | GET | 待人工复核 | 待人工复核 | 最关键，要求 `auto_wechat:agent` |
| `/api/wechat-tasks/pending` 或 `/wechat-tasks/pending` | GET | 待人工复核 | 待人工复核 | Local Agent 兼容路径 |
| `/api/wechat-tasks` 或 `/wechat-tasks` | GET | 待人工复核 | 待人工复核 | 要求 `auto_wechat:agent` |
| `http://127.0.0.1:19000/health` | GET | 待人工复核 | 待人工复核 | 本机 Agent |
| `http://127.0.0.1:19000/runtime/status` | GET | 待人工复核 | 待人工复核 | 本机 Agent |

## 9. 判断分支

拿到真实 `permission_codes` 后按以下规则判断：

1. 如果包含 `auto_wechat:agent`：
   - 前端 `/agents` 和 `/wechat-assistant` 都应允许。
   - 后端 `/staff` 和 `/wechat-tasks` 都应允许。
   - 若仍不可进入，优先查运行态前端版本、浏览器缓存、redirect 状态、实际 API baseURL 和页面初始化错误。

2. 如果只包含 `auto_wechat:ai_agents`：
   - `/agents` 后端允许。
   - 前端可能也放行 `/wechat-assistant`。
   - `/wechat-assistant` 的 `/staff`、`/wechat-tasks` 会 403。
   - 这是前端 alias 与后端门禁不一致。

3. 如果只包含 `auto_wechat:wechat_assistant` 或 `auto_wechat:wechat_agent`：
   - 前端可能放行 `/wechat-assistant`。
   - 后端 `/staff`、`/wechat-tasks` 会 403。
   - 这是后端未兼容微信助手权限码，或 NewCarProject 权限码尚未按后端当前口径返回。

4. 如果不包含上述任一 agent 相关权限：
   - 前端应拒绝 `/wechat-assistant`。
   - 若测试商户业务上应有权限，需要 NewCarProject 补齐权限码。

## 10. NewCarProject 需对齐项

待真实 `/auth/me.permission_codes` 确认后决定：

- 若目标是让测试商户使用当前后端门禁，NewCarProject 至少需要返回 `auto_wechat:agent`。
- 若 NewCarProject 已按新语义返回 `auto_wechat:ai_agents`、`auto_wechat:wechat_agent` 或 `auto_wechat:wechat_assistant`，则需要 auto_wechat 决定是否同步后端门禁和前端映射。
- 建议后续明确拆分：
  - AI 小高智能体：`auto_wechat:ai_agents`
  - 小高AI微信助手：`auto_wechat:wechat_agent` 或 `auto_wechat:wechat_assistant`
  - 过渡兼容：`auto_wechat:agent`

## 11. auto_wechat 可修复项

本轮不修复，只记录候选：

- 统一前端和后端对 agent 相关权限别名的口径。
- `/wechat-assistant` 页面初始化中，给 `/staff`、`/wechat-tasks/pending` 增加更明确的错误态展示，区分权限不足、未登录、本机 Agent 离线。
- 如果产品决定拆分权限，将 `/agents` 和 `/wechat-assistant` 从同一个 `PERMISSIONS.agent` 拆开。
- 增加一条只读诊断页或脚本，显示当前用户脱敏后的 `permission_codes` 和当前路由所需权限，便于人工排查。

## 12. 不建议立即修复的点

在没有真实 `/auth/me.permission_codes` 前，不建议直接修改：

- NewCar exchange-code 协议。
- `/auth/callback`。
- 9000 `/auth/me`。
- 前端权限映射。
- 后端权限门禁。
- Local Agent token gate。
- 19000。
- 自动发送链路。

## 13. 推荐后续任务

- `P1-NEWCAR-PERMISSION-RUNTIME-EVIDENCE-COLLECT-1`：由人工登录后补齐真实 `/auth/me.permission_codes`、路由访问和 `/wechat-assistant` Network 证据。
- `P1-NEWCAR-FRONTEND-BACKEND-AGENT-PERMISSION-ALIAS-DECISION-1`：根据真实权限码决定 alias 兼容策略。
- `P1-NEWCAR-WECHAT-ASSISTANT-PERMISSION-CODE-FIX-1`：若确认是微信助手权限码不一致，再做最小修复。
