# auto_wechat 桌面客户端 EXE 设计

> Task-ID：`DESKTOP-EXE-SPEC-20260718`
>
> Plan-Revision：`SPEC-R2`
>
> Base-Commit：`700557d77c3daa57105cb182062396897fd50429`
>
> 业务探索基线：`a01077c108bb24a1d2689838d836a2b72aed1ce0`
>
> 目标分支：`master`
>
> 风险等级：`L3`
>
> 状态：`SPEC_APPROVED`
>
> 日期：2026-07-18
>
> 书面批准日期：2026-07-20

本设计替代被退回的 `SPEC-R1`。它只冻结正式桌面客户端的产品、架构、安全和验收合同，不授权实现、构建正式包、连接生产环境或真实发送。

AI剪辑已按甲方要求进入 `FROZEN_BY_CUSTOMER`。本设计固定为“线上管理端 + 本机微信助手”，不包含 AI剪辑能力、Worker、素材目录、媒体工具、模型、任务、打包资源或验收合同；既有 AI剪辑代码、迁移、数据、测试和历史材料继续保留，不删除、不回退、不访问。

------

## 1. 需求冻结

### 1.1 任务目标

向客户交付单文件 Windows 客户端 `小高AI系统.exe`：

- 桌面窗口直接承载线上小高AI系统管理端；
- 登录且 9000 确认具有微信助手权限后，自动启动本机 `小高AI微信助手` Local Agent；
- 自动启动 Agent 不等于开启微信任务轮询；轮询默认关闭且只能由用户手动开启；
- 9000、9100、Milvus 和业务数据库继续运行在服务器；
- 客户电脑不需要源码、Python、命令行或手工填写内部令牌；
- 本机能力失败时线上管理端仍可用，但必须显示明确状态、`failure_stage`、重试入口和日志入口。

### 1.2 当前已知事实

- 当前 `app/local_agent_exe_entry.py` 只是 Local Agent 入口，不是桌面壳；项目尚无正式 pywebview 启动器、原生桥或完整优雅关闭链路。
- 当前 `local_agent.spec` 生成 onedir 产物；正式单文件桌面包不能只复制其中的入口 EXE。
- 当前 Local Agent 通过静态 `LOCAL_AGENT_TOKEN(S)` 访问 9000；正式桌面主路径尚无有状态短期机器会话。
- 当前浏览器访问 19000 不携带本机控制令牌；正式桌面托管模式必须增加严格入站鉴权，并与普通浏览器兼容模式隔离。
- 当前 Agent 启动时 `task_polling_enabled=false`，前端已有手动“开始接收任务/暂停接收任务”控件，可复用该业务语义。
- 当前 Local Agent 仍注册 AI剪辑路由并包含 Worker 协调代码；正式桌面内部产物必须使用微信单能力入口或显式冻结门，不能靠缺少 Worker 形成运行时失败。

### 1.3 允许范围

规格获批且取得独立执行包后，允许分阶段实现：

- 9000 短命准备、单次激活和有状态桌面会话的数据合同、迁移、接口、鉴权与审计；
- React 的受信桌面探测、激活钩子、本机控制令牌内存态和状态展示；
- pywebview 启动器、窄原生桥、单实例、WebView2 检查和进程树管理；
- Local Agent 微信单能力托管模式、本机控制鉴权、短期上游令牌轮换和可控停机；
- 仅包含微信能力所需资源的构建、签名、静态检查和独立干净机测试。

### 1.4 禁止事项

- 不实现、复测、重建、升级、分发或生产验证任何 AI剪辑能力；不注册 `ai_edit` capability，不启动或打包 Worker。
- 不删除或回退既有 AI剪辑代码、迁移、数据、测试、素材和历史目录。
- 不新增自定义 HMAC/JWT 令牌格式，不新增 `DESKTOP_AGENT_TOKEN_SECRET`，不把长期静态 Local Agent token 作为新桌面主路径。
- 浏览器不得接触上游机器会话令牌、启动器原始校验值、数据库地址或生产秘密。
- 不信任前端传入的商户、用户、权限或 capability；只能使用 9000 的可信 `RequestContext`。
- 不代理业务 API，不直连 9100，不拦截或改写 NewCar OAuth 回调。
- 不做托盘、隐藏后台、Windows 服务或自动更新。
- 19000 被未知进程占用时不复用、不杀进程、不发送任何凭据。
- 不修改或绕过联系人验证、前台焦点、搜索文字验证、违禁词替换、人工接管、限频、失败回写、幂等、紧急停止和 `task_id` 指定执行机制。
- 未取得阶段执行包前不改业务代码、配置或迁移；未取得独立测试与人工 Owner 批准前不连接生产或称为正式客户包。

### 1.5 总体验收标准

- 登录、Agent、微信、轮询和活动任务状态彼此独立、真实可见，不静默降级。
- 有可信微信权限时 Agent 自动启动，但人工开启轮询前任务领取、输入、粘贴和发送次数全部为 0。
- 60 秒准备/单次激活和 15 分钟有状态会话完成防置换、防重放、可撤销、可过期、商户隔离和秘密脱敏。
- 正式包、进程树、路由清单、能力清单和物料清单均不含 AI剪辑能力或资源。
- 无源码、无 Python 的干净 Windows 电脑可完成登录、Agent 启动、人工轮询控制、关闭与恢复测试。
- 任一真实发送路径继续满足既有全部安全 gate；环境阻塞不得替代功能通过。

------

## 2. 系统组件与职责

| 组件 | 职责 | 禁止事项 |
|---|---|---|
| 桌面启动器 | 单实例、WebView2/pywebview、原生桥、激活兑换、私有管道、Local Agent 与 Job Object 生命周期 | 不处理业务数据，不代理业务 API，不持久化业务或机器令牌 |
| 线上 React 前端 | NewCar 登录、权限路由、绑定短命准备、显示本机状态和人工轮询开关 | 不生成原始 verifier，不接收上游 session token，不自报可信商户或能力 |
| 9000 | 可信上下文校验、准备/激活/会话、Local Agent 微信机器 API | 不接受前端商户上下文，不向浏览器返回机器 session token |
| Local Agent 19000 | 微信 UI 自动化、任务轮询、只读检测、短期凭据持有和结果回写 | 只监听 `127.0.0.1:19000`；托管模式不回退无鉴权；不读取微信数据库 |
| 9100 / Milvus | 保持既有服务器职责 | 浏览器、启动器和 Local Agent 不因本设计新增直连 |

线上前端继续兼容普通浏览器。只有检测到受信 pywebview 原生桥时才进入桌面托管模式；普通浏览器仍调用浏览器所在电脑的 `127.0.0.1:19000` 兼容链路。两种模式必须显式分支，桌面托管模式不得回落为普通浏览器的无本机控制令牌路径。

桌面托管模式固定使用 `http://127.0.0.1:19000`，不得读取 `localStorage.local_wechat_agent_url` 或用户可编辑地址。

------

## 3. 总体调用链

```text
用户启动 小高AI系统.exe
  -> 单实例、WebView2 与固定生产地址检查
  -> pywebview 加载 https://merchant.xiaogaoai.cn/
  -> 前端调用现有 9000 /auth/me，取得可信 merchant_id 与精确 auto_wechat:agent 权限结论
  -> 只有该结论通过后，前端请求准备微信能力，启动器以无上游凭据方式启动 bootstrap Agent
  -> 启动器核对 19000 TCP owner PID 与带启动 nonce 的本机握手
  -> 本机归属确认后，启动器生成 verifier 并直连 9000 创建 60 秒 preparation
  -> 原生桥只把本机 handle + preparation_id 暴露给前端
  -> 前端用 NewCar 登录态把 preparation 绑定为 60 秒单次 activation
  -> 前端把 activation_id + activation_code 交回窄原生桥
  -> 启动器用 code + verifier 向 9000 兑换 15 分钟 session
  -> session token 通过私有管道一次性交给已验证 Local Agent
  -> 原生桥只向前端返回状态、过期时间和本机 control token
  -> Agent 在线但 task_polling_enabled=false
  -> 用户手动点击“开始接收任务”后才允许领取微信任务
```

未登录、`/auth/me` 无可信商户或缺少正式 `auto_wechat:agent` 权限时，前端不得调用 preparation，因而不创建 bootstrap Agent。activation 会再次校验同一可信权限，以闭合权限撤销竞态；二次校验失败时不签发 session，并立即关闭尚未获得上游凭据的 bootstrap Agent。只有历史 `auto_wechat:ai_edit`、`auto_wechat:wechat_assistant` 或 `auto_wechat:wechat_agent` 权限时不得签发新桌面会话。

------

## 4. 桌面激活与短期会话合同

### 4.1 随机值、编码与设备标识

启动器首次运行生成随机 UUID `device_id`，写入 `%LOCALAPPDATA%\XiaogaoAI\device.json`。它不是秘密，不含账号、商户、机器名或硬件指纹；文件只允许当前 Windows 用户读写。

`launcher_verifier`、`activation_code` 和 `session_token` 均由各自生成方使用系统密码学随机源生成 32 字节随机值，再以无填充 base64url 编码。禁止 UUID、时间戳、可读短码、trim 或大小写归一化。

哈希统一针对解码后的 32 字节原始值计算 SHA-256，存储为 64 位小写十六进制。禁止混用编码字符串和原始字节：

- 原始 verifier 只存在于启动器内存；
- 原始 code 只在 React 临时局部内存和启动器内存存活至一次兑换；
- 原始 session token 只存在于启动器和 Local Agent 内存；
- 9000 只保存三者 SHA-256，不保存原文。

### 4.2 启动器创建短命 preparation

`prepare_wechat_activation()` 无调用方输入，正常 UX 只能在当前 `/auth/me` 已返回可信商户和精确 `auto_wechat:agent` 权限后调用。初次激活时，启动器先按第 6 节完成无上游凭据 bootstrap Agent 的 Job 绑定、TCP owner PID 和本机握手；归属确认后才生成 verifier 并调用固定 HTTPS 端点。续期时必须复用同一启动器、Job、匿名管道和已验证 Agent PID，只生成新 verifier/preparation，绝不创建第二个 Agent 进程；归属已变化则续期失败并关闭轮询。activation 仍由 9000 二次校验权限，不能把前端判断作为签发依据：

```text
POST /agent/desktop-activation-preparations
Cache-Control: no-store
```

请求严格包含 verifier SHA-256、device ID 和桌面版本。该端点无 Cookie/NewCar/Local-Agent token，不开放 CORS，拒绝 redirect、`Origin` 和浏览器 Fetch Metadata，并按可信入口解析的来源、设备和版本限频。不得信任任意 `X-Forwarded-For`；仅接受部署配置中明确受信反向代理提供的客户端来源。

9000 创建 TTL 60 秒的 pending preparation，返回非秘密 `preparation_id`。启动器以不可猜测的本机 `activation_handle` 关联 verifier 和 preparation；一期最多一个 pending handle。handle/verifier 在 60 秒超时、导航离开可信 origin、关闭、登出、成功或失败时清除。

原生桥只向可信顶层页面返回 handle、preparation ID、device ID 和桌面版本，不返回 verifier 或其哈希，避免浏览器置换 verifier 后把机器 session 兑换到远端。

### 4.3 浏览器绑定 60 秒单次 activation

```text
POST /agent/desktop-activations
Authorization: Bearer <现有 NewCar token>
Cache-Control: no-store
```

请求模型启用 `extra=forbid`，只允许：

```json
{"preparation_id": "随机标识"}
```

不接受 Cookie 回退，也不得包含 `merchant_id`、`user_id`、device、verifier、capability 或服务器地址。9000 必须：

1. 从可信 `RequestContext` 取得用户和商户，要求非空可信 `merchant_id`；无绑定商户的 super admin 也拒绝。
2. 要求可信权限列表明确包含正式权限 `auto_wechat:agent`，能力固定为单值 `wechat`。
3. 校验 preparation 未过期/未绑定、设备版本有效，并与可信入口解析的同一客户端来源匹配。
4. 桌面版本低于 `DESKTOP_MIN_SUPPORTED_VERSION` 时返回 426 和固定 HTTPS 下载地址，不创建 activation。
5. 生成 32 字节随机 code，TTL 固定 60 秒；同一用户、商户、设备的新 activation 使旧 pending activation 失效，但不提前撤销当前 session。

响应只包含 activation ID、仅返回一次的 code、服务端 `expires_at`、`expires_in=60`、`capability=wechat` 和最低桌面版本。code 不得写入 URL、全局状态、Redux、service worker、session/localStorage、日志、异常或埋点；成功/失败后立即清理，敏感 POST 禁止通用自动重试。

### 4.4 启动器原子兑换

前端立即调用：

```text
complete_wechat_activation(activation_handle, activation_id, activation_code)
```

桥不接受 verifier、商户、能力或服务器地址。启动器用 handle 找回原始 verifier，并在确认 19000 归属后调用：

```text
POST /agent/desktop-activations/{activation_id}/redeem
Cache-Control: no-store
```

请求模型严格包含 code、verifier、device ID 和桌面版本；无 Cookie/NewCar/Local-Agent token，不开放 CORS，拒绝 redirect、`Origin` 和浏览器 Fetch Metadata。9000 必须在单个数据库事务中：

1. 校验 preparation、activation、用户、商户、设备、版本、来源、`capability=wechat` 和服务端 TTL。
2. 对 verifier/code 原始字节计算 SHA-256并做常量时间比较。
3. 条件消费 activation；并发双兑只能一个成功。
4. 创建 15 分钟有状态 session，并撤销同用户、商户、设备、能力的旧 active session。

过期、已消费、错误 code/verifier/device/source 统一受控失败，不泄露命中状态。事务提交后 code 永久消费；响应丢失不得重放或返还原 token，只能重新准备和激活，下一次成功兑换会撤销孤儿 session。

redeem 响应只向原生启动器返回 session ID、32 字节不透明 token、`expires_at`、`expires_in=900` 和 `capability=wechat`。桥最终只向 JS 返回受控状态、过期时间和本机 control token，绝不返回 verifier、上游 session token 或其哈希。

### 4.5 服务端状态与迁移

最小有状态数据模型：

| 记录 | 必要字段 |
|---|---|
| `desktop_agent_activation_preparations` | ID、verifier SHA-256、可信来源摘要、device ID、桌面版本、创建/过期/失效时间 |
| `desktop_agent_activations` | ID、preparation 唯一外键、code SHA-256 唯一键、source system、用户、商户、设备、版本、固定 `capability=wechat`、创建/过期/消费/失效时间 |
| `desktop_agent_sessions` | ID、activation 唯一外键、token SHA-256 唯一键、source system、用户、商户、设备、版本、固定 `capability=wechat`、签发/过期/撤销/最近使用时间 |
| `wechat_task_send_intents` | ID、task ID 唯一外键、可信 merchant/session/attempt、nonce SHA-256 唯一键、创建时间、`send_nonce_expires_at`（创建后 15 秒）、`result_deadline_at`（创建后 120 秒）、`consumed_at`、`manual_review_at`、`terminal_outcome`、`terminal_at`；不保存消息正文或联系人原文 |

`wechat_task_send_intents.terminal_outcome` 是不可变结果分类，只允许 `sent_confirmed`、`not_sent_confirmed`、`outcome_unknown`；它不是可反复推进的可变 status。`terminal_outcome` 与 `terminal_at` 必须成对为空或成对非空；每个 task 只能形成一个终态。状态由上述时间戳和终态推导，不额外保存容易漂移的 status。不得保存 NewCar token 或 verifier/code/session 原文；审计也不得记录秘密哈希、请求 body/header。

9000 生产迁移固定接在当前唯一 PostgreSQL Alembic head `0015_ai_edit_material_library` 后，形成 `0016`；开发 SQLite 固定接在 `0034_ai_edit_material_library.sql` 后，形成 `0035`。两条迁移覆盖同一 preparation/activation/session/send-intent 合同。降级只允许在上述四张新表全部为空时执行；任一表存在记录都必须在任何 DROP/ALTER 前 fail-closed，且数据、结构和迁移版本号保持不变，不得自动删除、归档或合并。禁止生产 `create_all`，禁止用 SQLite 专属写法扩散到 PostgreSQL 主线。

一期每次机器请求直接查询数据库会话状态，以换取即时撤销和最小实现；这是明确的低频查询上限。数据库异常返回 503 并 fail-closed，不得回落静态 token 或无鉴权。未来若引入缓存，必须先证明撤销能立即使缓存失效。

### 4.6 鉴权上下文与路由边界

统一 Local Agent 鉴权上下文至少包含：

```text
credential_kind
session_id
source_system
user_id
merchant_id
device_id
capability
```

请求 payload 中的 agent client ID、device ID 或 merchant ID 不得覆盖会话上下文；不一致时拒绝或由服务端可信值覆盖。

每个 9000 机器路由必须显式声明允许的 credential kind 和 capability，未声明的新路由默认拒绝。`desktop_session + capability=wechat` 的白名单固定为：

```text
POST /agent/heartbeat
GET  /wechat-tasks/pending
GET  /wechat-tasks/agent/{task_id}
POST /wechat-tasks/{task_id}/send-intent
POST /wechat-tasks/{task_id}/result
POST /replies/agent-write-back
GET  /daily-report-deliveries/agent/pending
GET  /daily-report-deliveries/agent/tasks/{task_id}
POST /daily-report-deliveries/agent/tasks/{task_id}/claim
GET  /daily-report-deliveries/agent/tasks/{task_id}/attachment
POST /daily-report-deliveries/agent/tasks/{task_id}/send-intent
POST /daily-report-deliveries/agent/tasks/{task_id}/result
POST /agent/desktop-sessions/current/check
POST /agent/desktop-sessions/current/revoke
```

`/agent/status`、`/replies/debug/*`、通用管理路由、activation 控制面和 `/ai-edit/*` 均不在机器业务白名单。preparation/activation/redeem 只按第 4.2~4.4 节独立凭据合同访问。

鉴权必须区分 `desktop_session` 与 `legacy_static`：

- `LOCAL_AGENT_AUTH_REQUIRED=false` 不影响新桌面路径；
- 旧 `LOCAL_AGENT_TOKENS` 只保留原配置和显式旧路由，不迁移、不删除，也不自动获得 `wechat` capability；
- 旧 token 不得调用 preparation、activation、redeem、rotation 或 revoke 控制面；
- 新 session 不得调用 AI剪辑路由，也不得回落到静态/无 token 路径。

`POST /agent/desktop-sessions/current/check` 是无副作用会话复验端点，只接受 `desktop_session`，返回当前 session ID、capability 和服务端过期时间。Local Agent 必须在任务领取/指定 claim 前调用。发送路径只能先完成不写入业务内容的联系人导航、只读验证和全部前置 gate；最后一次复验必须紧邻且发生在 send-intent 之前，send-intent 成功后才允许执行与该 task/attempt 绑定的一次正文或附件写入、粘贴和 Enter 序列。上述复验发生 401/403/503、超时或响应不匹配时均 fail-closed，不得向聊天输入区写入或粘贴业务内容，也不得 Enter。send-intent 已成功提交后不得再次用 `current/check` 否定该已线性化的单次发送序列；此时只能由原 nonce、15 秒窗口、明确 task ID 和全部既有发送 gate 决定是否允许写入、粘贴和 Enter。

唯一的已撤销/过期凭据例外只用于已先提交 send-intent 的终态回写：当 send-intent 已在其 desktop session 撤销或过期前完成线性化提交时，仅 `POST /wechat-tasks/{task_id}/result` 或 `POST /daily-report-deliveries/agent/tasks/{task_id}/result` 可在 `result_deadline_at` 前接收原 session token + raw nonce。9000 必须对原 token 和 nonce 分别计算 SHA-256，并与已存 session token hash、intent 绑定的 session/merchant/task、nonce hash、未决终态和 deadline 全量匹配后才允许幂等写入终态。该窄例外不得放行 `current/check`、claim、send-intent 或任何其他路由，也不得恢复 session capability；缺少可信回写时仍按第 6.6 节转人工复核。

### 4.7 私有交付与本机控制令牌

启动器在启动 Local Agent 前创建一组 Windows 双向匿名管道。只允许目标 child 所需的读/写 handle 继承，父端及其他所有 handle 均设为不可继承，并通过扩展启动信息的显式 handle allowlist 限定继承集合。启动 nonce、本机 control token 和上游 session token 均通过该管道交付：

- 不进入 argv、环境变量、文件、注册表、日志、异常或崩溃信息；
- Local Agent 读取后立即清理临时缓冲区；
- 句柄白名单、继承边界、读写或 child 确认失败时启动失败；
- 上游 token 只有在 OS TCP owner PID 和本机握手均验证后才允许兑换和交付；
- 新 token 交付失败时启动器立即撤销新 session，不恢复已撤销的旧 token。

本机 control token 由启动器生成 32 字节随机值。经归属验证后，原生桥把它返回前端，只保存在当前页面模块内存。桌面托管模式访问 19000 的状态、轮询和业务路由统一携带：

```text
X-Desktop-Control-Token: <本机 control token>
```

上游 session token 与本机 control token严格分离，任何方向不得复用。浏览器可以持有本机 control token，但永远不能持有上游 session token。

### 4.8 续期、过期与撤销

- 15 分钟 session 不允许 Local Agent 自行 extend/refresh。
- 前端仍处于有效登录态且正式权限存在时，在剩余 5 分钟重新执行 preparation -> activation -> redeem；每次使用新 verifier。
- redeem 事务提交时新 session 生效且旧 session立即撤销；随后若新 token 管道交付失败，启动器再撤销新 session，最终不存在 active session，且不得恢复旧 token。redeem 事务提交前的续期失败不影响旧 session 在原有效期内工作，也不得自动重试敏感兑换。
- 同一桌面进程、Agent、用户、商户、设备且没有过期间隙的成功续期，可以保持用户已手动开启的轮询状态。
- 会话实际过期、撤销、权限拒绝或设备不匹配时，立即停止 pending claim、业务心跳更新和新的 send-intent，并把轮询置为关闭。第 6.6 节已在撤销事务前完成线性化提交的有效 send-intent，仅允许在 15 秒 `send_nonce_expires_at` 前完成与该 task/attempt 绑定的一次正文或附件写入、粘贴和 Enter 序列；与该 intent 绑定的两个 result 路由可按第 4.6 节窄例外独立持续到 120 秒 `result_deadline_at` 完成终态回写，不受 15 秒发送窗口限制。除此之外禁止任何其他新微信 UI 副作用。
- 每个可能触发发送的阶段都必须在创建 send-intent 前重新确认 session 有效，并继续校验既有 task ID、execution token 与全部 gate；send-intent 提交后的 Enter 授权严格以第 6.6 节的线性化顺序、send nonce 和 15 秒窗口为准。
- 已触发 Enter 后无法回滚且终态回写失败时，以第 6.6 节 9000 已持久化 send-intent 为真源，等待服务端转人工复核；不得在本地新建业务 outbox，不得重新授权后自动重发或伪造成功。
- 重新激活、网络/权限恢复、微信恢复或 Agent 重启后不得自动续发，也不得自动恢复轮询。

NewCar 权限变更无推送时，已签发 session 最多残留 15 分钟，这是一期已知上限；续期必须重新校验权限。未来即时撤权的升级点是由可信权限变更事件批量撤销相关 session。

显式退出登录的客户端顺序固定为：进入 draining 并停止领取新任务；无活动任务时直接继续，有活动任务时按用户确认完成安全取消和终态回写；启动器幂等 revoke-current；前端再调用现有 `POST /auth/logout`；最后无条件清理本机秘密、管道和 Job。任一步网络失败都不能跳过后续本机清理。

9000 处理 `POST /auth/logout` 时，必须先用 Bearer 解析可信 `RequestContext`，并提交撤销该用户/商户全部已绑定 activation、通过外键关联的 preparation 和 active desktop session，再通知 NewCar；不得信任请求体里的 device、merchant 或 session。尚未绑定用户的 preparation 无法按用户撤销，启动器只清本机 handle/verifier，由服务端在 60 秒 TTL 到期后拒绝和清理。NewCar logout 失败不回滚本地撤销。

上述启动器撤销步骤使用当前 desktop session 调用幂等：

```text
POST /agent/desktop-sessions/current/revoke
X-Local-Agent-Token: <当前 session token>
```

该端点只接受 `credential_kind=desktop_session`。本地撤销失败和 NewCar logout 失败必须分别记录固定、脱敏的 `failure_stage`；任何网络失败都不能阻止清理内存、关闭轮询和结束 Job。服务端残余权限最多到 15 分钟自然过期。

全局 NewCar 401、跳转登录、可信 origin 导航离开和显式 logout 均触发本机 stop/revoke。普通关闭与 logout 语义分开，但普通关闭也撤销当前 desktop session。

------

## 5. pywebview 原生桥与浏览器边界

原生桥只允许：

```text
get_desktop_info()
prepare_wechat_activation()
complete_wechat_activation(handle, activation_id, activation_code)
get_local_status()
stop_wechat_agent()
open_log_directory()
```

- `prepare_wechat_activation()` 无输入，按第 4.2 节创建 preparation。
- `complete_wechat_activation(...)` 只接受固定格式/长度字段；返回状态、过期时间和本机 control token，不返回上游秘密。
- `stop_wechat_agent()` 只停止本次桌面进程拥有的 Agent，不接受 PID、路径或命令。
- `open_log_directory()` 只打开固定日志目录，不接受任意路径。

每次桥调用都由 native 侧读取当前顶层 URL 并同时校验：scheme 精确为 `https`、host 精确为 `merchant.xiaogaoai.cn`、无端口/用户名密码、非子 frame、非导航中状态。输入采用 `extra=forbid`、固定枚举、长度和字符集；桥异常只返回固定错误码。

WebView 导航到 NewCar 登录页、抖音授权页或其他外域时，原生桥全部拒绝。普通外链交给系统浏览器；必须在壳内完成的授权页使用单独明确允许列表，仍不能调用原生桥。

原生桥禁止任意文件读写、命令执行、任意 URL 请求、环境变量读取或通用脚本执行。production 关闭开发者工具和远程调试。下载使用 WebView2 标准保存流程，完成后不自动执行。

生产前端必须使用不含第三方活动脚本的严格内容安全策略：`script-src` 收敛到本源，`frame-ancestors 'none'`、`object-src 'none'`，`frame-src` 只允许现有抖音/NewCar 授权所需固定域名，`connect-src` 只允许既有服务和 `127.0.0.1:19000`。该策略及桥权限只能降低同源脚本失陷概率，不能替代输入校验、preparation 绑定或发送安全 gate。

------

## 6. Local Agent 启动、归属与轮询

### 6.1 单实例与端口归属

- 启动器使用 Windows 命名互斥锁保证单实例；重复启动只激活已有窗口。
- Local Agent 固定监听 `127.0.0.1:19000`。
- 端口已占用时不得假定是可信助手，不杀进程、不复用、不发送 preparation/code/verifier/control/session 秘密；线上管理端继续可用并显示端口冲突。
- 启动器先创建带 `KILL_ON_JOB_CLOSE` 的 Job Object，再用 `CREATE_SUSPENDED` 创建 Local Agent，绑定 Job 成功后才 resume。
- 绑定失败立即终止本次子进程并关闭 Job，不能留下绑定窗口期或孤儿进程。

### 6.2 启动参数与私有启动数据

非秘密参数固定为：

```text
host=127.0.0.1
port=19000
server_url=https://merchant.xiaogaoai.cn/api
allowed_origin=https://merchant.xiaogaoai.cn
device_id=<当前随机 UUID>
desktop_mode=true
```

生产服务地址构建期固定，不提供用户可编辑配置。实现时以非秘密固定配置 `LOCAL_AGENT_DESKTOP_MODE=true` 进入严格托管分支；nonce、control token 和上游 session token 只走第 4.7 节私有管道。

### 6.3 归属握手

启动器必须依次验证：

1. Windows TCP owner PID 显示 19000 由本次 Local Agent 子进程持有；Agent 自报 PID 不能替代 OS 证据。
2. 归属确认后才通过私有管道发送启动 nonce 与 control token。
3. 启动器以无 `Origin` 请求调用 `GET /desktop/handshake`，并携带 `X-Desktop-Control-Token`；响应返回本次 nonce、device ID、Agent 版本、PID、`capabilities=["wechat"]` 和托管模式标志。
4. 任一不符时终止进程树并清除内存；按固定时序此时尚未创建服务端 preparation/activation/session，不得伪造撤销成功。

未鉴权 `/health` 只能返回最小存活信息，不能作为进程归属或业务可用证据。只有完成上述归属确认后，启动器才可 redeem 并交付上游 session token。

### 6.4 自动启动不自动轮询

- `/auth/me` 确认可信商户和正式微信权限后，前端才自动请求启动 bootstrap Agent；无权限时保持纯线上管理模式。
- 桌面激活钩子必须读取 `/auth/me` 返回的原始权限集合并精确匹配 `auto_wechat:agent`，不得复用当前会把 `auto_wechat:wechat_assistant`、`auto_wechat:wechat_agent` 当作等价权限的 alias-aware `hasPermission(PERMISSIONS.agent)`。
- `/auth/me` 仅是正常 UX 前置，不是安全边界。同源脚本绕过前置直接调用无输入桥时，最多启动无上游凭据 bootstrap Agent；9000 activation 必须 403，不产生 session 或业务副作用，并立即清理 bootstrap 进程。
- 上游 session 交付前，bootstrap Agent 只允许本机握手、版本和 readiness 检查，不发起上游心跳或业务请求；交付后才允许心跳和无微信副作用的只读检测。
- 初始 `task_polling_enabled=false`；用户点击“开始接收任务”前，不启动领取循环，不 claim 任务，不写输入框，不粘贴，不发送。
- 轮询只能由用户手动开启。应用启动、重新登录、Agent 重启、微信重新出现、权限/网络恢复或重新激活均不得自动开启。
- 用户手动关闭轮询后立即停止领取新任务；已领取任务按既有 gate 完成。需要立即中断时使用独立紧急停止。
- Agent 崩溃、微信隐藏/最小化/消失、系统锁定、权限撤销或会话实际过期时停止领取并转为轮询关闭；恢复后仍需人工开启。

### 6.5 托管模式入站鉴权与跨源

- 19000 只允许精确来源 `https://merchant.xiaogaoai.cn`，保留浏览器 Private Network Access 预检。
- 禁止 `*`、任意 localhost 正则、反射 Origin 或用户配置来源。
- CORS 方法只允许 `GET`、`POST`、`OPTIONS`，请求头只允许 `Content-Type`、`X-Desktop-Control-Token`；不得沿用素材删除遗留的 `DELETE` 或 `allow_headers=["*"]`。
- 只有最小 `/health` 可匿名。ownership handshake、状态、轮询和业务路由全部要求 `X-Desktop-Control-Token`；handshake 额外拒绝带 `Origin` 的浏览器请求。
- 托管模式不接受无 token、静态 token 或普通浏览器兼容回退。
- capability 固定为 `wechat`；路由清单不得出现 `/agent/ai-edit/*`，不得创建 AI剪辑 Supervisor 或媒体子进程。
- CORS `allow_credentials=false`；PNA 预检只允许浏览器协议所需头，并精确返回 `Access-Control-Allow-Private-Network: true`。

### 6.6 不可逆发送与服务端恢复

桌面客户端不新增本地业务 outbox。所有可能触发 Enter 的路径必须在副作用前使用 9000 持久化 send-intent；send-intent 事务是 session 撤销与 Enter 授权之间唯一的数据库线性化点：

1. Agent 先完成联系人导航、只读验证和不写入业务内容的前置 gate，再调用 `current/check`，随后以明确 `task_id` 调用对应 send-intent；send-intent 成功前禁止向聊天输入区写入或粘贴正文/附件。
2. 9000 的 send-intent 事务与 revoke 事务锁定同一 session 行，并在同一事务内确认 session 仍 active、任务属于可信商户和 attempt、且不存在未决或终态意图；成功后创建唯一发送意图和随机 send nonce，固定 `send_nonce_expires_at=created_at+15 秒`、`result_deadline_at=created_at+120 秒`。该提交是撤销与整段业务内容写入、粘贴、Enter 授权之间的唯一线性化点。
3. 若 revoke 事务先提交，后续 send-intent 必须拒绝；除可已发生的联系人只读导航/验证外，Agent 的业务正文/附件写入、粘贴和 Enter 次数必须为 0。若 send-intent 事务先提交，随后 revoke 不撤销该已线性化意图，Agent 只可在 `send_nonce_expires_at` 前按该 nonce 完成与 task/attempt 绑定的一次写入、粘贴和 Enter 序列。
4. 领取接口不得再次返回已有未决 send-intent 的任务。
5. Agent 收到 nonce 后继续校验 nonce、task ID、联系人和全部既有 gate，并在写入/粘贴前及 Enter 前确认当前时间未超过服务端返回的 `send_nonce_expires_at`；超过 15 秒禁止继续该发送序列，且不得重新创建意图或自动重发。
6. 终态 result 必须携带 nonce；9000 可在 `result_deadline_at` 前幂等消费 nonce 并写入唯一终态。`send_nonce_expires_at` 只限制触发 Enter，不得错误阻断已经发生 Enter 后的可信终态回写；即使 intent 绑定的 desktop session 随后 revoked/expired，也只能按第 4.6 节窄例外凭原 session token + raw nonce 完成对应文本任务或日报任务的 result 回写，其他机器路由继续拒绝。
7. `result_deadline_at` 按 9000 服务端时间判定。相关文本任务和日报任务的领取、详情、send-intent 与 result 入口必须先执行同一到期收敛：首次在 deadline 当时或之后触达且仍无可信终态时，原子写入 intent 的 `terminal_outcome=outcome_unknown`、`terminal_at` 与 `manual_review_at`。普通文本任务同时写 `WechatTask.status=blocked`；日报任务同时写 `WechatTask.status=verify_pending` 和 `DailyReportDelivery.status=verify_pending`；两类任务统一写 `failure_stage=send_outcome_unknown_manual_review_required`。逻辑终态从 deadline 起即为结果未知，持久化投影允许在下一次服务端触达时惰性收敛；不得依赖 Agent 本地时钟或新增后台扫描。收敛后禁止自动重新领取、自动重发或伪造 sent。

现有日报附件只复用既有端点、前置门禁和结果语义。`desktop_session` 分支必须改用 `wechat_task_send_intents` 作为唯一发送意图真源，并执行本节“先 send-intent，后写入/粘贴/Enter”的新顺序；不得继续把 `WechatTask.send_nonce_*` 当作桌面会话真源。`legacy_static` 分支保留历史兼容行为，但不得获得 desktop capability、撤销后继续发送或过期/撤销 session 的窄终态回写例外。普通微信文本任务当前缺少等价服务端意图门，D2 必须按同一合同补齐；完成前该路径在桌面托管模式不得触发 Enter。断网、关窗或强退后，恢复只读取服务端终态并提示人工复核，不重放微信 UI 动作。

------

## 7. 用户可见状态与关闭语义

状态不得压缩成单一互斥枚举，前端至少分别展示：

| 维度 | 必要状态 |
|---|---|
| 登录 | 未登录、已登录、登录过期 |
| Agent | 未授权、启动中、在线、端口冲突、凭据过期、版本不兼容、启动失败 |
| 微信 | 未运行、隐藏/最小化、未就绪、就绪 |
| 轮询 | 关闭、开启、正在停止 |
| 当前任务 | 空闲、执行中、安全取消中、结果未知/人工复核、失败 |

纯管理模式只表示没有正式微信权限。有权限但 Agent 启动失败时，必须显示“管理端可用 + 微信助手失败”，不得伪装成纯管理。

普通浏览器未检测到 Agent 时继续使用规定文案：

```text
未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手
```

桌面壳自动启动失败时显示具体 `failure_stage`、重试和日志入口。

关闭规则：

- 轮询关闭且无活动任务：直接退出并撤销当前 desktop session。
- 轮询开启但空闲：确认“关闭将停止微信轮询”；取消关闭后所有状态不变。
- 存在微信任务：明确提示会中断当前任务；确认后停止领取，并最多等待 15 秒完成安全取消和终态回写。超时后关闭 Job Object；若已有 send-intent 但无可信终态，界面显示“结果未知，需人工复核”，由 9000 在 120 秒到期后冻结任务，禁止自动重发。
- 用户取消关闭：不得改变轮询、任务、凭据或进程状态。
- 强退或崩溃：Job Object 清理本次子进程；下次启动不得自动续发、自动恢复轮询或绕过 `task_id`。
- 关闭窗口但未退出登录：可保留 WebView 登录态；再次打开后有权限则自动启动 Agent，但轮询仍为关闭。
- 退出登录：执行第 4.8 节 logout/revoke 和本机无条件清理；接口失败不能阻止关闭轮询、清理令牌和结束 Agent。

------

## 8. 本地数据与日志

桌面客户端不保存服务器业务数据库，只产生：

| 数据 | 位置 | 规则 |
|---|---|---|
| 设备 ID | `%LOCALAPPDATA%\XiaogaoAI\device.json` | 非秘密，当前用户 ACL |
| 桌面与 Agent 日志 | `%LOCALAPPDATA%\XiaogaoAI\logs\` | 按大小轮转，最多保留 7 天 |
| WebView2 用户数据 | `%LOCALAPPDATA%\XiaogaoAI\WebView2\` | 当前用户 ACL；退出登录清理业务会话 |
| 诊断证据 | `%LOCALAPPDATA%\XiaogaoAI\diagnostics\` | 仅明确诊断/失败取证时生成，最多 7 天，不自动上传 |

不得读取、迁移、清理或写入历史 `%USERPROFILE%\.auto_wechat\ai_edit\` 及其他 AI剪辑目录。

日志允许记录 `event`、`stage`、`failure_stage`、状态码、耗时、版本、PID、可信用户/商户、能力和脱敏设备 ID。日志、反向代理与 APM 禁止记录：

- NewCar token、preparation 内部值、activation code、verifier、上游 session token、本机 control token及其哈希；
- 敏感端点的请求 body/header、OAuth code、Cookie、Authorization 或完整 URL 查询；
- 手机号、微信号、open_id、原始 webhook body；
- 业务正文、截图内容或本机绝对文件路径。

preparation、activation、redeem、session 和桥响应统一 `Cache-Control: no-store`。秘密哨兵必须覆盖日志、异常、前端存储、argv、环境变量、缓存、诊断包和构建归档。

------

## 9. 正式打包设计

最终只向客户交付：

```text
小高AI系统.exe
```

外层 onefile 仅包含：

- 桌面启动器与锁定版本的 pywebview；
- 完整 onedir 形式的微信单能力 Local Agent 内部目录；外层 onefile 收集整个目录，内层禁止再用 onefile；
- 微信联系人验证所需的 `easyocr`、`torch`、`torchvision`、`Pillow`、`OpenCV` 运行时，以及 `craft_mlt_25k.pth`、`zh_sim_g2.pth` 两份离线模型；
- 微软 WebView2 官方 bootstrapper；
- 必要许可证、版本、路由和物料清单。

不得包含 React `dist`、AI剪辑 Worker、AI剪辑路由、FFmpeg/ffprobe、剪辑模型、字体、素材、9100 凭据、NewCar 账号密码、生产 token、数据库地址或签名密钥。

正式构建必须：

- 固定 Python、PyInstaller、pywebview 和全部直接/传递依赖版本与哈希；不得动态安装未锁版本依赖。
- 内部 Agent 固定为完整 onedir。启动器最初创建的入口 PID 必须同时等于 19000 owner PID 和握手 PID，并位于本次 Job；不能把 onedir 的单个入口 EXE 当作自包含产物，也不能改成会再生运行子进程的内层 onefile。
- 外层 onefile 解压后，两份 OCR 模型必须位于内部 Local Agent EXE 同级的 `models/easyocr/`；缺失、路径错误或模型哈希不符立即失败。
- 正式包不得显示现有“复制完整 dist 目录”提示；资源损坏时只提示重新下载经签名的完整正式包。
- 生成微信单能力路由清单；发现 `ai_edit` 路由、模块启动项、资源或 `DESKTOP_AGENT_TOKEN_SECRET` 字符串立即失败。
- 校验所有输入二进制来源、版本和 SHA-256；发现生产秘密或真实用户 token 立即失败。
- 内部 Local Agent 与最终外层 EXE 均完成 Authenticode 签名和时间戳。
- 校验 WebView2 bootstrapper 的微软发布者签名和固定哈希。
- 生成内部物料清单、许可证清单、最终 SHA-256 和完整 Git 提交哈希。

WebView2 缺失时显示可见安装流程，说明联网和系统权限需求；取消、失败和断网均提供重试与退出。禁止静默运行 bootstrapper 或忽略签名校验。

------

## 10. 阶段门禁与执行顺序

本任务拆成独立阶段，不得混写：

| 阶段 | 目标 | 禁止事项 |
|---|---|---|
| D1 合同、迁移与红灯测试 | 冻结 preparation/activation/session、微信 send-intent、权限、默认拒绝路由和失败语义 | 不编写桌面壳，不构建包，不连生产 |
| D2 认证与进程闭环 | 完成测试环境下 9000、React、启动器和微信单能力 Agent 闭环 | 不纳入正式资源，不发布 |
| D3 正式资源与打包 | 纳入微信 OCR、WebView2、签名、路由和物料清单 | 不跳过干净机，不连接生产业务 |
| D4 独立测试与发布裁决 | 测试窗口绑定完整候选哈希执行干净机矩阵 | 执行窗口不得自证通过 |

进入 D1/D2 必须先批准本规格和各自独立执行包，只能使用隔离测试服务、测试账号和 Mock。D3 不依赖已冻结的 Task 11/12，不得复用其测试 EXE、Worker 或媒体资源。

D4 前必须确认线上前端已按冻结裁决隐藏 AI剪辑入口；该前置只允许执行已批准的冻结措施，不授权恢复或修改 AI剪辑执行链路。

任何阶段失败只返工当前阶段，不得顺便实现后续能力。当前规格通过后也只能先编制 D1 执行包。

------

## 11. 自动化测试矩阵

| 场景 | 类型 | 预期结果 |
|---|---|---|
| 无登录、无可信商户或缺正式微信权限绑定 activation | 权限 | 401/403，不创建 activation、不启动 19000 |
| 同源脚本绕过 `/auth/me` 直接调用 prepare | 威胁模型 | 最多启动无上游 bootstrap；activation 403、session/业务副作用为 0，并立即清理进程 |
| 仅历史微信别名或 `auto_wechat:ai_edit` 权限 | 权限/冻结 | 不签发桌面 session，不启动 Agent |
| `auto_wechat:agent + auto_wechat:ai_edit` | 权限/冻结 | 只签 `wechat`；AI 路由、进程和资源为 0 |
| 正式微信权限与历史微信别名并存 | 权限 | 只按原始正式权限处理，不扩大 capability |
| 桌面激活钩子权限判断 | 前端静态 | 精确匹配原始 `auto_wechat:agent`，不调用 alias-aware helper |
| 请求伪造 merchant/user/device/capability | 安全 | 400 或忽略；只使用可信上下文和 preparation |
| preparation 被不同来源/设备绑定或并发双 bind | 安全 | 拒绝置换；并发只有一个成功 |
| 任意 `X-Forwarded-For` 伪造可信来源 | 安全 | 被忽略或拒绝，只信配置内反向代理 |
| activation 仅 Cookie 鉴权或携带额外 verifier/device 字段 | 安全 | 拒绝且不绑定 preparation |
| 60 秒边界、错 verifier、错 code/设备/来源、已消费 | 安全 | 统一失败，不泄露命中状态 |
| 同一 activation 并发 redeem | 并发/数据库 | 只有一个事务成功，其余不返回 token |
| redeem 响应丢失后重放 | 安全 | 拒绝；重新申请后撤销孤儿 session |
| token 篡改、过期、撤销、错 capability 或 DB 故障 | 安全 | 401/403/503 fail-closed，不回落旧鉴权 |
| session 续期 | 集成 | 复用同一 Job/Agent/PID；新 preparation/verifier；redeem 提交后旧 token 立即拒绝 |
| 轮询关闭/开启时分别续期 | 业务 | 关闭时续期后仍关闭且零领取/输入/发送；仅已人工开启时可保持开启 |
| 新 token 匿名管道交付/child 确认失败 | 安全 | 新 session 撤销，不恢复旧 token |
| 新旧凭据双向越权及未分类机器路由 | 鉴权 | 默认拒绝，互不回退 |
| 无已提交有效 send-intent 时，current/check 在 claim 或最后一次发送前复验失败 | 安全 | 当前阶段 fail-closed；除联系人只读导航/验证外，业务正文/附件写入、粘贴和 Enter 为 0 |
| `/auth/logout` 的 NewCar 200/401/502 与本地撤销失败分支 | 集成 | 本地撤销不回滚，本机始终清理，失败状态可区分 |
| 未绑定 preparation 后退出 | 生命周期 | 清本机 handle；服务端 60 秒后拒绝，不宣称按用户撤销 |
| revoke-current 重复调用 | 幂等 | 均返回受控成功，不恢复或延长 session |
| redeem 带 Origin/Fetch Metadata 或发生 redirect | 安全 | 拒绝且不消费 activation |
| 桥被外域、iframe、导航中状态或错误输入调用 | 安全 | 拒绝，不执行本机操作 |
| 19000 抢占、错误 owner PID/nonce/匿名管道句柄继承 | 安全 | 零秘密泄露、撤销状态、无孤儿进程 |
| Job 创建/绑定或 suspended 启动失败 | 进程 | 子进程被终止，无绑定窗口期 |
| ownership handshake 匿名、带 Origin 或 control token 错误 | 安全 | 全部拒绝；正确 native 请求才返回握手 |
| 托管模式无 control token 或错误 Origin | 安全 | 401/403，不能回落兼容模式 |
| CORS/PNA 允许与拒绝预检 | 安全 | 仅精确 origin/method/header 成功且返回 PNA；DELETE、通配头、凭据模式失败 |
| 有权限自动启动 Agent | 业务 | Agent 在线且轮询关闭；领取、输入、粘贴、发送均为 0 |
| 手动开关轮询 | 业务 | 开启后才领取；关闭后不领新任务，当前任务按 gate 完成 |
| 重启/重登/Agent、微信、网络或权限恢复 | 业务 | 轮询保持关闭，不自动续发 |
| session 撤销与 send-intent 并发 | 并发/安全 | revoke 先提交则意图拒绝，除联系人只读导航/验证外业务正文/附件写入、粘贴和 Enter 为 0；意图先提交则仅允许 15 秒内按原 nonce 完成一次绑定 task/attempt 的写入、粘贴和 Enter 序列 |
| intent 先提交后 session revoked/expired 的终态回写 | 鉴权/幂等 | 仅两个 result 路由可在 120 秒 deadline 前凭匹配的原 token + raw nonce 幂等写终态；current/check、claim、send-intent 和其他路由仍拒绝，错 token/nonce/merchant/task 或超时均失败并转人工 |
| send nonce 超过 15 秒 | 安全 | 禁止 Enter，不重新创建意图、不自动重发；终态处理仍受 120 秒 `result_deadline_at` 约束 |
| session 过期或撤销且无先提交有效 send-intent | 安全 | 新 claim、send-intent 均拒绝；除联系人只读导航/验证外，业务正文/附件写入、粘贴和 Enter 为 0 |
| send-intent 重复、断网、缺终态 result | 幂等 | 单 task 只有一个意图；nonce 15 秒失效，120 秒无可信终态转人工复核，永不自动重发 |
| 关闭、取消关闭、强退 | 生命周期 | 符合第 7 节，无孤儿进程或自动恢复 |
| 微信任务执行 | 回归 | 保留 task ID、联系人、前台、搜索文字、违禁词、人工接管、限频、幂等和紧急停止 gate |
| 全链路秘密哨兵 | 安全 | DB 仅 hash；响应、桥、存储、argv/env、日志、诊断和归档无原文 |
| PostgreSQL/SQLite 迁移 | 数据库 | PG `0015 -> 新 head -> downgrade -> upgrade` 与 SQLite 对应顺序迁移在四张新表为空时通过；存在任一新表记录时 downgrade 在 DDL 前拒绝且数据/结构/revision 不变；既有微信任务数据不变，唯一、并发和事务回滚有效 |
| 构建资源缺失、哈希错误或冻结模块出现 | 构建 | 立即失败，不形成候选包 |
| OCR 两模型和完整运行时 | 构建/离线 | 缺任一模型/包构建失败；断网 status/warmup 成功且 `download_enabled=false` |
| 内部完整 onedir | 打包/进程 | 外层包含全目录；初始 PID=19000 owner PID=握手 PID，均在 Job 中 |
| pywebview 下载与授权跳转 | 桌面 | Excel 下载可用；外部授权与普通链接符合允许边界 |

运行时 `assert` 只能作为开发辅助，不能作为自动化测试或客户验收依据。

------

## 12. 独立干净机验收

测试环境必须是无源码、无 Python、无需命令行的干净 Win10/Win11 电脑或虚拟机，仅运行候选 `小高AI系统.exe`。至少覆盖：

1. 首次启动、WebView2 缺失、安装取消、断网、重试、重复双击和版本过低。
2. 未登录、无微信权限、仅正式微信权限、仅历史微信别名、仅历史 `ai_edit`、`agent+ai_edit`、`agent+历史别名` 及无可信商户的管理员上下文；混合权限只产生 `wechat`。
3. preparation/activation/redeem/续期/撤销/过期；续期复用同一 Agent PID，轮询关闭时保持关闭，只有此前人工开启时才可保持开启；浏览器、存储、日志和网络响应不出现上游 token 或原始 verifier。
4. 有正式微信权限自动启动 Agent；人工开启轮询前领取、输入、粘贴和发送次数全部为 0。
5. 首次启动、应用重启、退出重登、Agent 崩溃恢复、微信关闭重开、权限或网络恢复后轮询均为关闭。
6. 无微信、微信隐藏/最小化、系统锁定、19000 未知占用和 Agent 版本不兼容。
7. 手动开启/关闭轮询、活动任务、安全取消、紧急停止、凭据失效和失败回写；send-intent 缺终态时 120 秒转人工复核且重启不重发。
8. 使用专用测试任务验证 `task_id` 和全部发送 gate；真实发送必须另获书面测试授权，未授权时 dry-run/只读结果不得冒充真实发送通过。
9. 关闭窗口、取消关闭、退出登录、强退、再次启动后的撤销、任务终态、进程树和轮询状态；活动任务关闭最多等待 15 秒，超时明确进入人工复核而非自动续发。
10. 普通浏览器兼容模式与桌面托管模式互不混用；ownership handshake、CORS/PNA、本机 control token 和严格内容安全策略符合合同。
11. Excel 下载、NewCar/抖音外部授权跳转、系统浏览器外链和日志目录入口。
12. 包内文件、路由、能力、进程树和物料清单均不存在 `ai_edit`、Worker、FFmpeg 或剪辑资源，且未访问/修改历史 AI剪辑目录。
13. 断网环境下 OCR status/warmup 成功、`download_enabled=false`，两份模型位于内部 Agent 同级 `models/easyocr/`。
14. 最终 EXE、内部 Agent、WebView2 bootstrapper 的哈希、发布者签名、时间戳和物料清单一致。

验收按用户任务结果判定，不得以窗口出现、进程存在、`/health` 返回、运行时断言或环境阻塞替代功能通过。

------

## 13. 发布裁决

- D1-D3 每个候选都绑定 Task-ID、Plan-Revision、Base-Commit、完整 Candidate-Commit 和干净工作区证据。
- 审批窗口核对范围、差异、接口、迁移、权限、商户隔离、静默降级和测试缺口后，才可输出 `APPROVE_TEST <完整提交哈希>`。
- 测试窗口只依据冻结需求、验收标准和独立矩阵，不接收执行窗口“已经修好”的主观结论。
- amend、rebase、squash、merge、冲突修复或任何代码变化都会使原测试结论失效。
- 本任务为 L3。正式发布最终只能输出 `OWNER_APPROVAL_REQUIRED <完整提交哈希>`，再由人工 Owner 决定。
- 未经独立测试和 Owner 批准，不得称为正式客户包或推送生产。

------

## 14. 文档影响

- 本规格获批只代表设计冻结，不改变当前运行事实。
- 每阶段完成后检查并原位更新受影响的当前事实；D2 候选形成前不把桌面客户端写成已实现。
- 技术验证包只能记录测试状态，不得写成正式完成。
- 正式包经独立测试和人工 Owner 批准后，更新 `docs/ai/05_PROJECT_CONTEXT.md`、Local Agent/微信专题和对应验收文档。
- AI剪辑专题继续保持 `FROZEN_BY_CUSTOMER`，不得因桌面交付改写为恢复或完成。

------

## 15. 当前审批边界

当前结论：`SPEC_APPROVED`。用户已于 2026-07-20 书面批准 `SPEC-R2`。

本轮只允许提交本设计文档，并基于该完整规格提交哈希单独编制 D1 执行包。D1 执行包另行批准前：

- 不得编写或修改业务代码、迁移和生产配置；
- 不得构建、复测或分发 EXE；
- 不得生成尚未绑定候选提交的测试窗口指令；
- 不得连接生产 NewCar、9000、9100 或真实微信发送链路；
- 不得以本规格恢复任何 AI剪辑工作；
- 不得直接进入 D2-D4。
