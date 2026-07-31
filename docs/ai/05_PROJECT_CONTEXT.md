# auto_wechat 当前项目上下文

> 本文档是 AI Coding Agent 的当前项目事实文档。
>
> 优先级低于阅读规范，高于执行规范、测试规范和输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 1. 文档定位与更新时间

- 定位：**只保存当前有效上下文**，不记录里程碑流水账，不按日期追加任务完成记录。
- 更新时间：2026-07-30（自动回复门禁简化 + 固定提示词模板 V2.0 + LLM 上下文迁移 + 违禁词改造 + RAG 修复均已生产验证。**门禁简化**：`douyin_autoreply_gate_service.py` risk_flags 默认放行发安全替代回复，移除 manual_required/fallback_reason/rag 阻断，新增 `manual_review_risk_flags_json` 转人工黑名单（迁移 0018），9100 生成安全替代回复后 `auto_send=True`；**固定提示词模板 V2.0**：9100 `_build_fixed_prompt_template` 用甲方确认的 12 节完整模板替换旧 `_SYSTEM_PREFIX`，10 个商家变量从 `ai_agents` 表（迁移 0019 新增 11 字段）注入，前端智能体编辑改为傻瓜式表单；**旧安全后处理覆盖移除**：`_apply_safety_postprocess` 不再用 `_build_safe_direct_reply`/`sanitize_direct_llm_reply_text` 覆盖 LLM 回复，合并纠正 fallback 也不覆盖，信任 V2.0 模板；**预览与自动回复统一**：预览路由补传 `direct_llm_policy` + `forbidden_words`，两条路径走同一 9100 `build_reply_suggestion` → `build_llm_messages` → `_build_fixed_prompt_template`；**RAG 修复**：检索时使用小高统一知识库 scope（`tenant_id=xiaogao_system`/`merchant_id=xiaogao_base`/`douyin_account_id=0`），而非请求中的真实值，匹配知识库入库数据；**第五节违禁词改造**：9100 生成后确定性检查 `_check_forbidden_words`，命中阻断转人工，人工发送/回访保留旧替换逻辑；生产验证 `rag_used=true`/`rag_sources_count=5`/自动回复发送成功。**2026-07-30 自动回复误阻断修复**：9100 `_parse_structured_llm_decision` 的 `manual_required` 默认值 True→False（LLM 漏填该字段时默认放行，减少空配置智能体下普通问句误转人工）；新增账号级开关 `allow_release_manual_required`（迁移 0020，默认关），开启后豁免 manual_required 阻断，让需人工确认的回复也发送，但仍走完整发送 gate，不豁免 prompt_injection 等风险阻断，前端客服工作台自动回复设置抽屉提供开关；前序已闭合：抖音会话增量协议（计划一 Task 1-8）、webhook 原子幂等、outbox 持久化、跨商户隔离、已读协议、mark-read 刷屏修复；NewCar 商户自助改密四态分流保持有效；**2026-07-31 AI剪辑恢复**：甲方书面授权解除 `FROZEN_BY_CUSTOMER`，放弃原 FFmpeg/9100规划/19000本地执行面三段架构，改为纯 LAS 云端方案（火山 LAS `las_video_remix` 算子 `speech_auto` 模式）：9000 组装参数→LAS submit→后台轮询→存产物；旧冻结代码（worker/pipeline/stabilizer/9100规划/19000执行面/旧 AiVideoEditor/Task 11 测试包）已删除，数据模型 7 表+迁移保留复用，新增 LAS 字段迁移 0022/0042，算力 capability_key 加 `ai_edit`，前端新工作台 LasRemixWorkbench；生产验证另行审批）。
- 同一事实只保留一份当前结论；旧结论失效时必须原位替换或删除，禁止追加"最新补充"覆盖旧结论。维护规则见 `docs/ai/01_READING_RULES.md`"AI 文档自治维护规则"。
- 2026-07-14 之前的历史里程碑、阶段定义、逐任务迁移记录见冻结快照：`docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md`（仅追溯用，不是当前事实）。

------

## 2. 当前项目目标与一期范围

### 2.1 产品定位

auto_wechat / 小高AI系统属于 NewCarProject 外部客户系统下的一组商户可售卖子功能系统。当前建设主链路：

- `AI小高线索 → 小高AI微信助手`：抖音私信线索 webhook 直收 → 线索入库 → 销售分配 → 微信通知 → 回复检测 → 回访。
- `抖音AI小高客服（9100）`：私信客服工作台 + RAG/LLM 回复 + AI 托管自动回复闭环。

### 2.2 小高AI系统一期范围（2026-07-10 确认，2026-07-13 勘误）

以 `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md` 为一期需求权威文档；与旧文档冲突时以该文档及本节为准。

1. **AI剪辑已于 2026-07-31 按甲方书面授权恢复开发（原 2026-07-18 FROZEN_BY_CUSTOMER 已解除）**。已放弃原 FFmpeg/9100规划/19000本地执行面三段架构，改为纯 LAS 云端方案（火山 LAS `las_video_remix` 算子 `speech_auto` 模式）：9000 组装参数→LAS submit→后台轮询→存产物；前端新工作台 LasRemixWorkbench。旧冻结代码（worker/pipeline/stabilizer/9100规划/19000执行面/旧 AiVideoEditor/Task 11 测试包）已删除，数据模型 7 表+迁移保留复用，新增 LAS 字段迁移 0022/0042，算力 capability_key 加 `ai_edit`。设计文档 `docs/superpowers/plans/2026-07-31-ai-edit-las-remix-redesign.md`。生产验证仍需另行审批；TOS/LAS 凭证从环境变量注入，前端不持有 LAS_API_KEY。
2. **一键过审已于 2026-07-13 被客户取消（CANCELLED_BY_CUSTOMER）**，不再是一期交付范围；不删除历史记录、不回退已落地代码和兼容字段。注意与历史 Phase 8 Task 11（日报样本对齐，已 VERIFIED）重名但无关。
3. `auto_wechat:ai_edit` 为 AI剪辑入口权限（2026-07-31 已恢复，承载 LAS 混剪工作台 + 素材库）；仍不新增 `auto_wechat:ai_video` / `auto_wechat:ad_review`。
4. 微信助手规则字段为 5 项：线索分配、短视频/直播留资管理表、每日线索销售反馈表、线索溯源表、销售单车成本表。
5. 留资口径：`extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在即为已留资。
6. 旧的"只建议不实发""只粘贴不实发"硬门禁已废止；抖音侧与微信侧真实发送必须经后端 gate（见第 8、9 节）。
7. 商户管理、管理员账号、登录、功能授权仍归 NewCarProject / used-car。
8. 微信 UI 自动化底线继续有效：不读取微信数据库、不 DLL 注入、不微信协议逆向。
9. 线索状态机采用一期五态 STATUS_LABELS 映射（内部状态 → 五个展示态）；跟进记录用 `LeadFollowupRecord`。
10. 登录委托 NewCarProject；权限码识别 admin；1 商户 = 1 账号；token 不自动刷新。
11. 小高算力不是子功能系统，是商户查看套餐和消耗的展示能力；支付一期 mock。

------

## 3. 当前系统组件与服务边界

| 组件 | 端口 | 说明 |
|---|---|---|
| auto_wechat 主服务 | 9000 | FastAPI（`app/main.py`）。业务 API、webhook 直收、NewCar 鉴权门面、9100 可信代理、自动回复 gate、报表、回访 |
| 抖音AI小高客服 | 9100 | FastAPI（`apps/xg_douyin_ai_cs/`）。RAG 检索、LLM 回复、知识库 metadata；默认监听 127.0.0.1 |
| Local Agent（小高AI微信助手.exe） | 19000 | `app/local_agent_main.py`，**默认只监听 127.0.0.1:19000**，运行在微信所在 Windows 电脑，不容器化 |
| React 前端 | 5173 | `frontend/`（原独立项目 `E:\work\project\react` 已并入，历史提交 2c85433），`npm run dev:lan` 提供局域网访问 |
| car-porject-main | 8788 | 外部训练入口，知识训练调用经 9000 代理转发，不直连 9100 |
| Milvus | 外部 | 仅向量检索副本，不是 metadata 真源 |
| douyinAPI | 8081 | **demo / 参考实现 / 历史沉淀**，不是生产运行依赖。webhook 事件已由 9000 直收；仅剩旧链路 `/integrations/douyin/sync-leads` 保留待处置 |
| NewCarProject / used-car | 外部 | 商户、账号、权限、菜单、套餐、消耗管理的权威系统 |

职责红线：

- 9000 是抖音企业号 / Agent / 分类绑定的**权威数据源**；`agent_config`、`allowed_category_keys` 只能由 9000 注入，不信任前端传入。
- 前端不得持有 internal token，不得直连 9100 / Milvus；前端传入的 `tenant_id` / `merchant_id` / `douyin_account_id` 一律不可信。
- Local Agent 只操作客户本机微信；9000 不直接操作微信。React 本机 Agent 面板必须调用浏览器所在电脑的 `127.0.0.1:19000`，不走 `VITE_API_BASE_URL`。
- "Local Agent" 指 19000 微信自动化进程；"智能体（Agent）"指 9100 绑定的 LLM 客服配置。两者概念不同，禁止混用。

------

## 4. 当前环境与部署边界

### 4.1 Compose 三文件（职责互斥）

| 文件 | 职责 |
|---|---|
| `docker-compose.yml` | **唯一 production 主入口**（PostgreSQL 16 + 外部 Milvus + 真实 NewCar）。postgres 服务用 `docker/postgres/init-prod` 首启建 `xg_douyin_ai_cs` 第二库。宝塔生产即用本文件 + `.env.production.local`（必须 `APP_ENV=production`） |
| `docker-compose.staging.yml` | staging 覆盖文件，**禁止单独运行**，只能与 `docker-compose.yml` 组合。用 `!override`（不是 `!reset`）完全替换 ports/volumes/env_file；独立 project `auto_wechat_staging`、端口 29000/29100/5180/25432、库 `auto_wechat_staging` / `xg_douyin_ai_cs_staging`；禁止 SQLite fallback |
| `docker-compose.dev.yml` | 本地开发**独立完整编排**（不是 override，禁止与生产主文件组合）。SQLite + Mock 鉴权 + 热更新；9000 + 9100 + frontend + 能力中心 9201-9206 + 可选 postgres profile；19000 必须宿主机运行 |

`docker/` 目录下无其他 compose 入口（旧 `auto-wechat.yml` 已移除）。

### 4.2 环境模板

- `.env.development.example` / `.env.lan.example` / `.env.production.example` 三份根模板（前端 `VITE_*` 已合并入内）。
- production 模板要点：`APP_ENV=production`、`DATABASE_URL=postgresql+psycopg://...@postgres:5432/auto_wechat`、`RAG_DATABASE_URL=postgresql+psycopg://...@postgres:5432/xg_douyin_ai_cs`、`RAG_VECTOR_BACKEND=milvus` 固定、`NEWCAR_AUTH_ENABLED=true` + `NEWCAR_AUTH_MOCK_ENABLED=false`。
- production 不允许缺 `DATABASE_URL` 回退 SQLite（仅 dev 允许回退）。

### 4.3 LAN 演示

- 9000：`uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload`；前端：`npm run dev:lan`。
- `VITE_AUTO_WECHAT_API_BASE_URL` 必须用开发主机局域网 IP（如 `http://192.168.110.113:9000`），不能用 `127.0.0.1`（局域网访问者的 127.0.0.1 是访问者自己）。
- CORS 允许 `192.168.110.113:5173` / `DESKTOP-T0HA3GO:5173` / `localhost:5173` / `127.0.0.1:5173`；防火墙放行 TCP 9000、5173。

### 4.4 机器角色

- 开发主机（192.168.110.113）：源码、React 页面、打包。
- 测试电脑 / 虚拟机：**无源码**，只运行小高AI微信助手.exe；不得以"运行 python 命令"作为验收前提。
- 微信自动化只能发生在运行小高AI微信助手.exe 的那台 Windows 电脑上。

------

## 5. 当前鉴权、权限与商户隔离

### 5.1 NewCar 外部鉴权链路

- 登录委托 NewCarProject：浏览器直接调用 NewCarProject `exchange-code` 换取 external token，再调用 9000 `/auth/me` 获取 auto_wechat 可信用户与权限上下文；9000 是业务鉴权门面。
- 代码默认值是开发态：`NEWCAR_AUTH_ENABLED` 默认 `False`、`NEWCAR_AUTH_MOCK_ENABLED` 默认 `True`（`app/config.py`）。本地真实鉴权联调必须显式 `NEWCAR_AUTH_ENABLED=true` + `NEWCAR_AUTH_MOCK_ENABLED=false`；生产模板已固定真实鉴权。
- 侧栏底部动作按 `isAdminLike(user)`（`super_admin` 或任一 `auto_wechat:admin:*` 权限）互斥：管理员显示“切换到 NewCar”和“退出登录”两个动作；普通商户显示“修改密码”和“退出登录”两个动作。管理员不显示商户改密，普通商户不显示切换到 NewCar。
- 管理员“切换到 NewCar”：浏览器直接携带 external Bearer token 调 NewCarProject `POST /api/external-auth/switch-to-internal`，校验上游 `redirect_url` 仅为 HTTP(S) 后跳转。切换失败保持当前 URL、页面和登录态；切换过程不清 external token、NewCar 回跳状态或 Local Agent token。
- 管理员“退出登录”（退出当前浏览器全部登录态）：浏览器直调 NewCarProject `POST /api/external-auth/logout-current-browser`，携带 `credentials: include` 与 Bearer；上游撤销当前 external 与同用户 internal session、删除两个内部 Cookie、返回 `redirect_url?logged_out=1`。9000 无法读 NewCar 域 Cookie，故管理员退出禁止走 9000 `/auth/logout` 或 9000 代理该接口；不等价于全设备退出。退出开始抑制 401、卸载受保护页，token 只存页面内存 ref；成功校验 redirect_url 后 `window.location.replace()` 跳转；失败清本地持久状态并停留当前 URL 提示重试，不跳错系统。
- 普通商户“修改密码”：浏览器调 9000 `POST /auth/password`（`app/routers/auth.py`），由 9000 代理 NewCarProject `POST /api/external-auth/password`；请求体只允许 `old_password`/`new_password`，不接受或转发 `user_id`/`merchant_id`，9000 不保存密码、不在日志或响应记录密码/token。`OLD_PASSWORD_INVALID`/`PASSWORD_TOO_SHORT`/`PASSWORD_UNCHANGED` 映射 400，`ACCOUNT_TYPE_NOT_ALLOWED`/`ACCOUNT_DISABLED` 映射 403，token 类映射 401，上游 5xx/超时映射 502（`NEWCAR_PASSWORD_UNAVAILABLE`）；失败只返回本地固定脱敏文案，不透传上游 message。停用账号在 external 鉴权入口统一返回 401（Owner 2026-07-21 接受），9000 仍兼容把可达的 `ACCOUNT_DISABLED` 映射 403。前端改密结果按四态分流（取代旧布尔 `passwordReloginView`）：`business`（400/403）保留登录态、恢复 401 跳转、弹窗内重试；`success`/`relogin`(401)/`unknown`（超时/网络/5xx/异常 JSON/2xx 非白名单）一律清本地持久状态、卸载受保护页、进入对应结果状态页且不恢复旧会话；只有 `success`（严格匹配 `ok===true && relogin_required===true && revoked_session_scope==="all"`）能展示「密码已修改」，`relogin` 展示「登录已失效」，`unknown` 展示「结果未知」、不得声称成功或失败；`handleRelogin` 将结果状态恢复为 `null`。
- 普通商户“退出登录”：走 9000 `POST /auth/logout`，由 9000 调 NewCarProject `POST /api/external-auth/logout`，仅撤销当前 external 会话；前端直接 `fetch`，并在退出开始到退出结果页期间抑制其它在途请求触发的全局 401 NewCar 跳转，只有用户主动“重新登录”前才恢复该跳转。无论注销成功或失败，前端都卸载受保护页并清理 Query 缓存、external token、NewCar 回跳状态、Local Agent token 和当前用户，保持当前 URL 且不自动跳 NewCar；失败 token 只保留在当前页面 `useRef` 内存中供“重试退出”，不得持久化、写入 URL 或日志。改密、管理员退出与普通退出共用 `setNewCarAuthRedirectSuppressed()` 抑制门禁；改密业务失败（400/403）恢复 401 跳转，`success`/`relogin`(401)/`unknown` 保持抑制直到结果状态页/显式重新登录（`handleRelogin` 将结果状态恢复为 `null`）。
- token 不自动刷新；权限码识别 admin；1 商户 = 1 账号。

### 5.2 商户隔离

- `merchant_id` 来自 RequestContext（服务端解析），**不来自前端**；非 super_admin 按当前商户过滤，super_admin / mock 开发态可跨商户只读。
- 线索/会话隔离、`sales_staff.merchant_id`、外部商户绑定已通过迁移落地（SQLite 0011 / 0021 / 0023 / 0035）。
- AI 回复记录按 `RequestContext.merchant_id` 隔离，且不返回 `raw_response_json`。
- 抖音企业号绑定 open_id、线索会话商户隔离、工作台商户上下文（智能体列表走 9000 代理）均已闭合。
- **抖音AI客服读取链路商户隔离（DY-CS-TENANT-ISOLATION-READ-1/R2）候选 `9072bc8d365de6cc5bcbfe21ceae0472d476b00b` 已通过独立测试**（2026-07-22，A1-A14 验收通过，任务级结论为 PASS）：
  - `DouyinWebhookEvent` 落库 `merchant_id`/`tenant_id`（SQLite 迁移 0035；PostgreSQL 已有可空字段，仅对齐 ORM 与写入契约），webhook 入库按事件方向解析有效绑定账号固化可信商户归属，有效绑定集合把空值纳入歧义判断（任一空值且存在非空记录→NULL、多商户→NULL、商户唯一但 tenant 空与非空混杂→tenant NULL），归属不明保持 NULL，重复事件只继承已确认归属；历史事件 merchant_id 为 NULL，禁止猜测回填。
  - 工作台会话/消息/画像/未读/已读查询均先经 `require_owned_account` 校验账号存在 + `bind_status==1` + merchant_id 匹配，再按 `event.merchant_id` 过滤；账号转移或历史重复账号下，他商户历史事件对当前商户不可见。
  - `DouyinLead` 查询在数据库条件中加入 `merchant_id`；`mark_conversation_read` 派生字段严格一致，不一致统一 404 且不创建/修改状态。
  - 普通商户发送记录只允许 `upstream_msg_id` 精确匹配，禁止按内容跨历史兜底。
  - **所属商户 HTTP 响应（last_message/消息正文/画像 customer_contact/webhook message_text/customer_contact）完整展示手机号和微信号，不脱敏**；非管理员 webhook `raw_body` 始终为 null，super_admin 保留原始详情。
  - **只有发送给 LLM 的回复上下文（`build_reply_conversation_context` 及 LLM 请求载荷）独立脱敏手机号和微信号**；ReplyConversationContext 整体满足“不含完整手机号或微信号”后置条件；LLM 脱敏失败阻断，不得把原文发送给模型。
  - `im_send_msg` 后置人工接管无法确认商户归属时跳过写入并记录 `failure_stage=merchant_unresolved`，不伪造 `unknown_merchant`。
  - 独立测试窗口已确认：Base 与候选 `9072bc8` 的 `tests/test_douyin_workbench_conversations.py` 11 项失败节点和错误正文完全一致，仍为待处理基线问题（与本任务隔离改动无关，非本任务引入）。
  - 候选尚未推送、合并或发布；未验证真实 PostgreSQL、生产环境、真实私信和自动回复。
  - 不改变 webhook 验签、自动回复决策、发送保护和消息增量协议；生产真实 PG 运行契约与真实消息/自动回复验证仍待独立生产窗口确认。
- **抖音客服会话已读协议（DY-CS-CONVERSATION-READ-PROTOCOL-1）候选 `8e69adc36a7df35c054774f6b482bac2887c0123` 已通过独立测试**（2026-07-23，Test-Revision T1，A1-A14 全部验收通过，任务级结论 PASS，指定集 241 passed + IntegrityError 竞争重复 10 次 + Barrier 双线程竞争重复 10 次 = 合计 261 passed, 0 failed）：
  - `mark-read` 请求新增必填正整数 `last_seen_event_id`；缺失或非法返回 422，且无状态写入。
  - 服务端在可信商户、有效绑定账号和指定会话范围内验证该事件；不可见或不属于该会话的事件统一返回防枚举 404，且无状态写入。目标事件必须为私信事件（`im_receive_msg`/`im_send_msg`），非私信事件拒绝推进；`created_at` 为空时返回防枚举 404 且不写状态。
  - 水位精确推进到 `last_seen_event_id`，不得取服务器当前最新事件替代；已读水位使用 `(created_at, event_id)` 单调前进；相同时间戳使用 `event_id` 区分。
  - 并发保护落在数据库条件更新（`UPDATE ... WHERE (created_at, event_id) < new`）和唯一约束竞争处理（`IntegrityError` → `rollback` → 条件更新恢复）上，禁止仅做应用层先读后比。
  - 重复或旧请求返回 200 和当前水位，不得回退。
  - 未读计算继续只统计 `im_receive_msg`，并按 `(created_at, event_id)` 判断。
  - 前端仅在当前详情请求成功并完成 React 状态提交后提交已读，凭据绑定 `account_open_id`、`conversation_id`、`request_seq` 和 `max_event_id`；`raw_event_id` 缺失或非法时不得猜测、不得提交已读；缓存消息不得作为本次详情成功的证据。
  - 删除前端乐观清零链路（`applyReadWatermarks`/`readWatermarksRef`/`markConversationReadLocally`），不再在 mark-read 成功前用缺少 `event_id` 的本地水位覆盖服务端未读；mark-read 成功后刷新服务端权威未读。
  - mark-read 失败保持未读可见，清除已消费凭据使后续轮询产生新凭据重试；当前会话仍有未读时按既有 8 秒轮询重新加载详情并重试，不新增立即无限重试或新定时器。
  - 功能代码、独立测试结论和文档闭环已合入远端 `master@64b22280d57128d0b7124a0bd24119d7930ae09b`；尚未部署或发布；未验证真实 PostgreSQL；未验证生产环境、真实私信和自动回复；未运行全仓测试；前端行为主要通过静态源码合同测试验证；SQLite 竞争测试不能替代 PostgreSQL 生产验证。

------

## 6. 当前数据库与迁移状态

### 6.1 总体：双轨运行

- **SQLite 仍是 9000/9100 代码默认运行库**（`DATABASE_URL` 缺省回退 `data/auto_wechat.db`；9100 回退 `apps/xg_douyin_ai_cs/data/xg_douyin_ai_cs.db`），定位为开发和过渡数据库。
- **PostgreSQL 是生产目标库，方案 A**：一个 PG 实例、两个 database——`auto_wechat`（9000，`DATABASE_URL`）与 `xg_douyin_ai_cs`（9100，`RAG_DATABASE_URL`）。
- 新增代码不得继续扩散 SQLite 专属写法；跨方言仓储写法为准。

### 6.2 迁移体系（两套并存）

| 轨道 | 位置 | 说明 |
|---|---|---|
| SQLite 顺序迁移 | `migrations/migrate_sqlite.py` + `migrations/versions/0001~0029+.sql` | 开发/过渡库 |
| PostgreSQL Alembic（9000） | `migrations/postgres/auto_wechat/`（版本 0001~0024） | 覆盖主服务运行表；0014 为算力用量计量，0015 为 AI剪辑素材库历史迁移，0016 为 AI 自动回复 outbox 持久化任务字段，0017 为 `douyin_webhook_events` 商户账号复合索引，0018 为 `douyin_account_autoreply_settings.manual_review_risk_flags_json`（风险转人工黑名单），0019 为 `ai_agents` 11 个商家可配置变量字段（固定提示词模板 V2.0），0020 为 `douyin_account_autoreply_settings.allow_release_manual_required`（账号级放行需人工确认回复开关），0021 为回访动态场景配置 + ReturnVisitFollowupTask 表，0022 为 `ai_edit_jobs`/`ai_edit_materials` LAS 字段，0023 为 `compute_markup_ratios` 补 ai_edit 行，0024 为 `compute_markup_ratios` 加消耗模式 consumption_mode/fixed_tokens_per_call；冻结不回退已落地迁移 |
| PostgreSQL Alembic（9100） | `migrations/postgres/xg_douyin_ai_cs/`（0001 空基线 + 0002 RAG metadata 7 表 + 0003 `llm_call_logs.conversation_id` 列 bigint→varchar(255)） | |

注意：`wechat_tasks` 是历史遗留——SQLite 主线库由 ORM create_all 建、不在 0001-0028 中（0029 用 `CREATE TABLE IF NOT EXISTS` 壳统一）；PG 由 0003 建。

### 6.3 切换（cutover）当前进度

- **9000 PG cutover**：dev 全链路实测通过（alembic smoke + cutover 脚本 + PG DATABASE_URL 真启动 + HTTP/DB 冒烟，即 Z3-Z5）；**staging 12 步演练通过**（P3-E-9100-STAGING-DRILL-FASTTRACK-1，修复 8 个生产阻塞：库名/空串/varchar/datetime/bool/bigint/jsonb/tz）；**production 执行包就绪**（提交 fb34144：10 个 `scripts/production_pg_*.sh` + `docs/ai/05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md` + `.env.production.pg.example`），状态 `READY_FOR_BAOTA_EXECUTION`，**待人工在宝塔执行，未切换**。
- **9100 PG 迁移**：schema、repository/service 跨方言改写、迁移脚本（7 表安全门）、生产 compose 已切 `RAG_DATABASE_URL`、真实 PG smoke 通过；production 切换同样待人工审批执行。
- cutover 一次性迁移脚本默认 dry-run，apply 在 production 有放行门。
- knowledge_categories 单表先行迁移：production dry-run 执行记录结论为 `SKIPPED_NO_SOURCE_ROWS`（生产源表无数据，无需 apply）。

### 6.4 强制注意事项

1. **PG 模式禁止 create_all**：9000 在 PostgreSQL 下必须先 Alembic 初始化，启动跳过 create_all（SQLite 才走 create_all）。
2. **asyncpg + Windows**：本机连 PG 必须用 `127.0.0.1`，`localhost` 会解析 IPv6 导致 ConnectionReset；psycopg 不受影响。
3. **连接池三组配置互斥**：`DB_POOL_*`（9000 PG）/ `SQLALCHEMY_*`（SQLite）/ `RAG_DB_POOL_*`（9100 RAG PG）。判断是否生效必须追到 `create_database_engine` / `create_rag_engine` 实际分支，不能靠 grep 局部命中。
4. **dev 库 schema 漂移**：`data/auto_wechat.db` 可能缺新字段（曾缺 SalesStaff 5 字段），用全局 engine 的测试会 OperationalError；用内存库的同类测试不受影响。
5. WAL 模式下 SQLite 文件 hash 不能作为"数据未变化"的证据。
6. shadow read（leads/tasks 五接口只读对照）默认全关，仅灰度观测用。
7. **ORM / 迁移 / 代码写入契约三者必须一致**：新增或修改字段时，`app/models.py` ORM 类型、对应 Alembic `create_table`/`alter_column` 声明类型、service 写入值类型三者必须对齐。SQLite→PG 一次性迁移脚本（如 `scripts/migrate_agents_accounts_core_sqlite_to_postgres.py` 的 `json_fields`/`datetime_fields` 分类）是契约真源。典型反面：ORM `String`/`Text` + service 写 `str`/`json.dumps()`，但迁移建成 `TIMESTAMPTZ`/`JSONB`，PG 拒绝 text→jsonb 隐式转换抛 `ProgrammingError`。`DouyinAuthorizedAccount` 的 `bind_time`/`unbind_time`/`source_created_at`/`raw_body_json` 已于 2026-07-20 候选实现收敛为 `DateTime(timezone=True)` + `JSON`，写入用 aware datetime + dict（无时区上游时间按 `Asia/Shanghai` 解释转 UTC，见 `parse_upstream_datetime`）。**2026-07-28 生产 hotfix 闭合同类 jsonb 漏用：`DouyinAccountAutoreplySetting` 5 列（allowed_intents_json 等）、`DouyinMessageResourceDownload`/`DouyinImageUpload` 各 request/response_body_json、`WechatTask.raw_result` 共 4 表 10 列 ORM `Column(Text)` 改为 `_JSONStringJSONB()`（提交 `a65912b`），对应 PG 列本就是 jsonb，SQLite 列是 TEXT，schema 不变无需迁移，service 层 `json.dumps()` 写 str 合同不变**。排查方法：模型 `Column(Text)` 且列名含 `_json`/`_ids`/`raw_` 的列，对照 `migrations/postgres/auto_wechat/versions/*.py` 是否 `postgresql.JSONB`；`ReturnVisitRun`/`DailyReportJob` 迁移为 `sa.Text()` 非 jsonb，不属漏用；`DouyinLead.raw_data`/`DouyinWebhookEvent.raw_body`/`DouyinPrivateMessageSend` 已用 `_JSONStringJSONB`；AdReview/AiEdit 域受冻结约束不动。

------

## 7. 当前 RAG 与知识库边界

- 统一小高知识库训练与检索 scope：`tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`、`category_key=base`。其中 tenant/merchant 是 **env 可覆盖的默认值**（`KNOWLEDGE_TRAINING_DEFAULT_*`），检索侧固定 `category_keys=["base"]`；文档表述不得写成"硬编码"。
- Milvus 仅是 embedding + 向量检索副本；documents、chunks、feedback、training_run 与状态字段的真源是 `RAG_DATABASE_URL` 指向的 metadata 库（SQLite / PostgreSQL）。
- `RAG_VECTOR_BACKEND` 代码默认 `sqlite`，生产固定 `milvus`；Milvus 不可达时 readiness 503，**不回退 SQLite**；embedding 维度三方一致性校验失败（`MILVUS_DIMENSION_MISMATCH`）直接启动失败。
- Milvus 模式下 `ask` 不得因 SQLite active count 为 0 跳过检索；`search-preview` 能命中 Milvus 时 `ask` 也必须执行 Milvus RAG。
- RAG query 只用 question 本身，不拼 prompt/人设/历史。
- feedback 自动入库幂等键：`training_id + answer_hash`。
- 训练入口：car-porject-main（8788）→ 9000 代理 → 9100；前端与外部系统不直连 9100。

------

## 8. 当前抖音客服与自动回复边界

### 8.1 服务边界

- 9100 负责 RAG 检索、LLM 回复生成（OpenRouter）、结构化输出与决策日志；9000 负责账号授权、Agent 绑定权威源、发送 gate 与真实发送。
- 一期口径：从“回复建议”收束为 **AI 托管自动回复闭环**；自动回复只走“绑定智能体 + 开关”，`reply_suggestion` 一期移除。
- 客服工作台从 9000 本地 `douyin_webhook_events` 聚合会话，不在进入页面时向抖音补拉历史；会话列表不再按 7 天截断，默认读取最近 2000 条本地事件并可按需扩至 20000，返回页面先展示当前登录会话内缓存再后台更新。
- 9000 向 9100 发起回复决策时固定携带最近 10 条脱敏对话，并从当前消息、已保存客户画像和更早客户消息构造可信 `customer_memory`，字段优先级为“当前消息 > 已保存画像 > 历史消息”。记忆字段包括意向车型、年份、预算、城市和脱敏联系方式状态；完整手机号、微信号不得进入 9000→9100 请求或 LLM 请求。
- 新客户查询成功但历史为空、或去掉当前重复消息后历史为空，均属于正常上下文并继续回复；数据库读取失败、消息解析失败等异常必须阻断手工建议与自动回复，不得静默降级为空历史。
- 商户添加抖音号时，`DY_AUTH_REDIRECT_URL` 必须回到创建 OAuth state 的同一套 9000；当前生产值为 `https://merchant.xiaogaoai.cn/api/integrations/douyin/live-check/auth-redirect`，不得指向不同服务器上的 `callback.misanduo.com`。`oauth-callback` 仅为观察接口，不写授权账号。前端授权状态只认本次 OAuth `state` 与可信当前商户，历史账号或进程内上次回调不得判定本次成功；仅当本次账号已进入当前商户正式账号列表后才能自动关闭弹窗。事件 webhook 地址保持独立，不随 OAuth 回跳迁移。
- OAuth state 过期判断必须同时兼容 SQLite 无时区时间和 PostgreSQL `TIMESTAMPTZ`；禁止直接比较无时区与带时区的 `datetime`。

### 8.2 真实发送 gate（现已落地的组件）

配置默认全关（`app/config.py`）：`DOUYIN_AUTO_REPLY_ENABLED` / `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` 默认 False。**一期已放开自动发送灰度**：`ALLOW_FULL_ROLLOUT` 与账号/客户/会话 env 白名单、数据库灰度门禁（`evaluate_db_rollout_gate`）不再阻断自动发送——是否允许自动发送只由上述两个 env 开关决定，数据库灰度配置仅保留为诊断快照；超管后台"自动回复灰度"入口已在前端隐藏。账号级 `settings.send_enabled` 默认仍为 OFF。

gate 链（`app/services/douyin_autoreply_gate_service.py` 等）：

1. pre-LLM gate：人工接管（manual_takeover）阻断、每小时会话限频。
2. real-send gate：env 总开关（`DOUYIN_AUTO_REPLY_ENABLED` + `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`）、账号级 `send_enabled`、绑定智能体、账号级客户/会话白名单（可选收窄）、每日会话上限（real_send_limits）。
3. **post-LLM gate（2026-07-29 简化后，2026-07-30 增放行开关）**：risk_flags 默认放行发安全替代回复，不再硬阻断；`manual_review_risk_flags`（转人工黑名单，空=全放行）控制哪些风险转人工；移除了 `fallback_reason`/`rag_not_used`/`rag_sources_empty` 阻断；保留 `manual_required`（9100 明确人工信号）、`confidence_low`、`empty_reply_text`、`intent_not_allowed`。**2026-07-30**：`manual_required` 阻断可被账号级开关 `allow_release_manual_required`（迁移 0020，默认关）豁免——开启后需人工确认的回复也发送，但仍走完整发送 gate，不豁免 prompt_injection 等风险阻断；9100 `_parse_structured_llm_decision` 的 `manual_required` 默认值由 True 改为 False（LLM 漏填该字段时默认放行，减少误阻断）。
4. 发送前违禁词处理（2026-07-29 改造后）：自动回复（`auto_send=True`）不在 9000 侧替换，9100 生成后确定性检查 `_check_forbidden_words`，命中阻断转人工；人工发送/回访保留旧 `replace_forbidden_words` 替换逻辑。
5. 幂等去重（`already_sent`）；人工发送后标记 manual_takeover。
6. 紧急停止（`POST /automation/emergency-stop`）。

### 8.3 固定提示词模板 V2.0（2026-07-29 落地）

- 9100 系统提示词使用甲方确认的固定模板 V2.0（12 节完整规则：身份目标、知识库使用、回复原则、联系方式用语、留资引导、敏感业务处理、对话流程、常见场景、回复风格、严禁内容、输出要求），模板内容固定不可改（第一版不支持管理员自定义）。
- 10 个商家可配置变量从 `ai_agents` 表注入（迁移 0019 新增字段）：门店地址、门店联系方式、门店微信号、门店营业时间、销售城市范围、销售汽车品牌、收车城市范围、收车汽车品牌、销售下班留资回复、顾客问车况回复、评估师下班留资回复。
- 前端智能体编辑（`SuperMerchantAgent.tsx`）改为傻瓜式表单：11 个简单输入框替代旧的大 textarea，商户只需填内容不需写提示词。
- 旧 `_SYSTEM_PREFIX` 与仅被它引用的 `CONVERSATION_HISTORY_POLICY` 已删除（2026-07-31 P0 Batch A 清理失效死代码，原注释称"位于 system 首部"与实现不符）；`_build_fixed_prompt_template` 是唯一主系统提示词。
- 旧安全后处理覆盖已移除：`_apply_safety_postprocess` 不再用 `_build_safe_direct_reply`/`sanitize_direct_llm_reply_text` 覆盖 LLM 回复；合并纠正 fallback 也不覆盖。信任 V2.0 模板生成的回复。
- 预览与自动回复使用同一 9100 入口 `build_reply_suggestion` → `build_llm_messages` → `_build_fixed_prompt_template`，预览补传 `direct_llm_policy` + `forbidden_words` 与自动回复统一。
- **2026-07-31 P0 Batch A（回复质量与留资判断）**：① 训练端 `ask` 不再追加"不要输出 JSON"纯文本 Prompt，统一用 V2.0 结构化 JSON 输出契约，内部解析后提取 `reply_text` 供训练页面展示（根因 R1：两端输出协议不一致；训练端保持通用知识库问答定位，不注入商户变量/真实会话历史/客户记忆/生产联系方式状态，两端基础 Prompt 与结构化输出合同一致，实际话术允许因业务上下文不同而合理差异）；② 新增联系方式确定性状态机 `analyze_contact_state`（五态 NONE/PARTIAL/VALID/INVALID/AMBIGUOUS，含分隔符/区号规范化、号段校验、脱敏、原因码，9000 判定 9100 消费，不把号码合法性交 LLM）；③ 分段联系方式合并改为受控（`_combine_recent_customer_text` + `_collect_recent_customer_fragments`：仅 PARTIAL/补全状态、同会话同客户、中间无客服回复、可配时间窗 `DOUYIN_CONTACT_FRAGMENT_WINDOW_SECONDS=300`、可配片段数 `DOUYIN_CONTACT_FRAGMENT_MAX_MESSAGES=3`、合并后必须过完整校验），旧无条件拼最近 5 条已替换，并修复了旧局部 import `normalize_message_text` 的潜伏 ImportError；④ **跨 AI 回复补全闭环（R1 返工）**：新增 `app/services/contact_completion_resolver.py` 事件溯源等价机制（**不新增数据库迁移**），以 `douyin_webhook_events` 事件为补全状态锚点——当前消息紧前为 AI 补全回复、其紧前为客户 PARTIAL 消息时，将补发片段与前序部分号码合并并重新完整校验，仅 VALID 才采用；严格事件序列天然满足所有清理条件（补全成功后/切话题后/超时后/片段超限均不误拼），不跨客户/会话/账号/商户合并，webhook `_combine_recent_customer_text` 在连续合并失败后回退到该 resolver；⑤ **ContactState 单一可信源（R1 返工 + R2 异常降级修正）**：`ReplySuggestionRequest` 新增可选 `contact_state`/`contact_action`/`contact_state_source`，9000 `_build_request_contact_state` 用共享状态机+resolver 计算后注入（仅脱敏值），9100 `_resolve_contact_state_with_source` 优先消费 request 状态（`request`/`local_fallback`/`training_default` 三态），不被本地文本覆盖；**9000 ContactState 构建异常时不伪装为可信 request**（返回空 dict 省略全部 contact 字段，不传 `contact_state_source=request`），由 9100 用共享状态机执行 `local_fallback` 恢复，异常只记录安全上下文（脱敏标识，不含完整手机号/微信号/客户原文）不阻断自动回复主链路；⑥ `missing_phone_goal` 改为读 `contact_state`：仅 NONE+场景适合+未拒绝+遗漏留资才触发，VALID/PARTIAL/INVALID/AMBIGUOUS 一律不重新索要手机号（主调与 retry 后两处均修复）；⑦ 生成后联系方式语义校验（PARTIAL/INVALID/AMBIGUOUS 不得说"已收到"，VALID 不得重复索要），命中最多一次 LLM 纠正，禁止第三次调用；⑧ 轻量可观测字段：`prompt_version`/`prompt_template_hash`/`rag_policy_version`/`llm_call_count`/`reply_char_count`/`reply_sentence_count`/`reply_question_count`/`llm_primary_ms`/`llm_retry_ms`/`reply_suggestion_total_ms`（不记录完整 Prompt/手机号/微信号/历史/审核轨迹）。**未改 `manual_required`/`allow_release_manual_required`/post-LLM gate/真实发送 gate/人工审核红点/决策日志 schema/无人工审核数据库迁移**。

### 8.4 RAG 检索 scope（2026-07-29 修复）

- 9100 RAG 检索使用小高统一知识库 scope：`tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`（`UNIFIED_KB_DOUYIN_ACCOUNT_ID`）。
- **不得**使用请求中的真实 `tenant_id`/`merchant_id`/`douyin_account_id` 构造 RAG 检索——知识库数据入库时使用统一 scope，用请求值会导致 Milvus 三重不匹配返回空。
- 知识库数据（120 chunks + 120 documents）入库 scope 为 `xiaogao_system`/`xiaogao_base`/`0`/`base`，RAG 检索必须匹配此 scope。

- 切换为“AI 托管”时会写入完整的直接模型回复启用策略，并清空历史意图白名单和风险白名单；切换为人工接管只关闭账号真实回复，不删除其他配置。
- 9000 完成绑定校验后注入的 `agent_config` 是可信上下文，9100 不再因未命中知识而把它视为降级配置。模型返回的 `auto_send` 永远不直接控制发送，值为 true 时仅记录 `llm_requested_auto_send_ignored`；最终候选仍由账号策略、安全后处理和 9000 gate 计算。
- **AI 自动回复 outbox / 持久化任务（DY-CS-AUTO-REPLY-OUTBOX-1/R2 第七次返修）最终候选 `a245e231ad03e153d6b605801ded60ddbd2da1d3`（父候选 `8e987642cd4fbd90057771cd47c2a0ffb4b10be3`）已通过独立测试 Test-Revision R2-T1（A1-A16 全部验收通过，任务级结论 PASS），并已通过普通快进推送集成至 `master@a245e231ad03e153d6b605801ded60ddbd2da1d3`**（2026-07-25）：复用 `AiAutoReplyRun` 表作为 outbox 任务真源，新增 `lease_owner`/`lease_expires_at`/`attempt_count`/`next_attempt_at`/`last_failure_stage` 字段（SQLite 迁移 0036 + PG Alembic 0016）；webhook 胜出者同事务 enqueue pending run（仅 flush，拒绝空 `account_open_id`）；claim 使用条件 UPDATE 原子租约（300 秒，线程唯一 lease_owner + commit 后返回 + 退避时间条件）。R2 第七次返修闭合检查点后跳过路径的 gate_results 写入：`_mark_send_skipped_after_checkpoint` 增加 `gate_results_json` 参数，8 个检查点后跳过路径（outbound_after_trigger / latest_message_not_customer / latest_message_changed / send_context_unavailable / send_context_message_changed / send_context_account_mismatch / send_context_customer_mismatch / context_expired）全部传入当前局部累积 gate_json，由单条原子 guarded UPDATE 同时写状态/原因/gate_results 并清租约，保留 send_gate_passed 与 manual_takeover 诊断，未恢复对 `run.gate_results_json` 的赋值。前序返修已落地：`_merge_gate_results` 纯函数局部 dict 累积不碰 ORM；`_finish_run`/`_add_run`/`_handle_llm_failure` 终态原子清租约，dry-run decided 不进发送补 else 分支清租约，仅 real_send_candidate decided 持有租约；`_run_with_session_for_outbox`/`_process_one` 强制非空 lease_owner 失败关闭；`_terminal` 单条原子 guarded UPDATE；send 第一个写库动作前先取得 guarded 检查点 `decided → send_processing`（内容规范化合并进该 UPDATE）；`_add_run` outbox 路径原子条件 UPDATE（`expected_status=processing` + 原始 owner + 未过期租约 + `rowcount`）；`send_ai_auto_reply_for_run` 增加 `lease_owner` 显式参数；`run_outbox_cycle` 在 try 内创建 Session，构造失败时释放单飞锁。并发安全设计不变：guarded 原语 + lease 上下文 + cycle 单飞锁下沉至 outbox service（强制 `run_id`/`expected_status`/原始 owner/`lease_expires_at>now`/`rowcount==1`）；`recover_expired_leases` 原子 `EXISTS`/`NOT EXISTS` UPDATE 且 `recovered` 仅累计实际 rowcount；`manual_retry` 将 `NOT EXISTS` 发送流水折叠进同一原子 UPDATE（消除 TOCTOU）；scheduler 与 webhook wake 共用 cycle 单飞锁。LLM 失败自动重试（`retry_wait` + 60s/300s 退避，超限 → `failed`）；send 失败分类（`upstream_business_error` → `failed`；其余 → `send_unknown`）；compensate 补偿（保存点隔离）；调度器默认关闭（`AI_AUTO_REPLY_OUTBOX_ENABLED=false`），10 个变量在三个 env 模板登记且默认值与 `config.py` 一致。执行窗口自测：专项、新增并发/租约回归与 outbox 状态机直接相关测试 0 failed（258 passed，含新增检查点后跳过路径原子写 gate_results + 清租约 + 不调用真实发送断言，及前序终态原子清租约/dry-run decided 清租约/并发回归——第一检查点成功+局部累积 gate_results→另一 Session 接管换 owner/gate_results→旧 Worker 第二检查点 rowcount=0→commit 后状态/owner/租约/gate_results 全保持新 Worker 值）；指定回归 0 个新增失败。独立测试 Test-Revision R2-T1（A1-A16 全部验收通过，任务级结论 PASS）：主专项 258 passed、迁移/API/合同 49 passed、并发热点 10 轮 40 passed，合计 347 passed；另有 2 个经 Base（8e98764）/ Candidate（a245e23）同环境对照确认的范围外基线失败——① `tests/test_ai_auto_reply_dry_run.py::test_active_binding_calls_9100_with_history_and_records_decision_log`（IndexError，conversation_history 为空；后续确认根因是旧 dry-run 测试夹具未写事件 `merchant_id/tenant_id`，不是 `douyin_conversation_history_service.py` 业务服务缺陷，已由 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的 R1-T1 闭合；该历史报告当时仅能判为范围外基线，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）；② env `test_all_code_variables_are_classified`（未登记变量均为 AI_EDIT 冻结模块 / DAILY_REPORT / LOCAL_AGENT / NEWCAR_AUTH，不在本任务 Allowed-Files），Candidate 0 个新增失败。已通过普通快进推送集成至 `master@a245e231ad03e153d6b605801ded60ddbd2da1d3`；本地跨进程 SQLite 测试不能替代 PostgreSQL MVCC 与生产恢复验证（PostgreSQL/MVCC 验证见下条 DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1），未验证生产调度、迁移和恢复，未连接生产环境，未发送真实私信、自动回复或微信消息，未运行全仓测试，尚未部署或发布。

- **AI 自动回复 outbox 重启恢复测试（DY-CS-AUTO-REPLY-OUTBOX-RESTART-RECOVERY-1/R1）最终候选 `a7f924d02712fd942a1b9f069bf4b9c40bf6c8fe`（父候选 `e18b3524b4d51dc3f51b03bb387510355f92ab1b`）已通过独立测试 Test-Revision R1-T1，R1-R11 全部通过，任务级结论 PASS，并已通过普通快进推送集成至 `master@a7f924d02712fd942a1b9f069bf4b9c40bf6c8fe`**（2026-07-25）：pytest 父进程编排全新 Python 子进程共享 `tmp_path` 临时文件 SQLite，验证 outbox 仅依赖已提交数据库状态完成恢复、领取、对账和去重，全程禁止真实外部动作；子进程在 `import app.database` 前绑定临时 `DATABASE_URL`、剥离继承的 TOKEN/SECRET/PASSWORD/API_KEY、关闭自动回复与真实发送开关，安全处理器用真实 guarded UPDATE 推进到 `blocked` 终态并清租约，LLM/9100/抖音/微信/socket 全部 patch 为"调用即失败"；R1 进程隔离落盘、R2/R3/R4/R5 各状态恢复且只处理一次、R6/R7 `send_authorized` 按发送流水对账不重发、R8 连续两次重启不重复、R9 调度器关闭不领取、R10 空 `lease_owner` 失败关闭（`stage=process_one`/`failure_stage=missing_lease_owner`）、R11 外部调用为零（`_run_safe_cycle` 强制断言 `calls["count"]==0`，R3/R4/R5/R8 断言 `external_calls==0`）；独立测试数字：专项 `11 passed, 0 failed`、连续 10 轮共 `110 passed, 0 failed`、完整指定回归 `248 passed` 且 1 个范围外基线失败（`test_active_binding_calls_9100_with_history_and_records_decision_log`，后续确认根因是旧 dry-run 测试夹具未写事件 `merchant_id/tenant_id`，不是 `douyin_conversation_history_service.py` 业务服务缺陷，已由 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的 R1-T1 闭合；该历史报告当时仅能判为范围外基线，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域），Candidate 0 个新增失败；本地跨进程 SQLite 重启恢复测试已在专用 PostgreSQL 数据库补齐 MVCC 验证（见下条 DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1，P1-P9、C1-C4 全部 PASS），未验证生产调度、迁移和恢复，未连接生产环境，未发送真实私信、自动回复或微信消息，未运行全仓测试，尚未部署或发布。

- **AI 自动回复 outbox PostgreSQL/MVCC 恢复测试（DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1/R1）最终候选 `df8644d828680a75ff955db59c546d4ba1caa729`（Implementation-Base `70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d`，直接父提交 `08ccdac9dd3128784d150b691eb52437ae28b169`，含 R1-REPAIR-1/R1-REPAIR-2A 返修及 R2/R3 测试加固）已通过独立测试 Test-Revision R1-T1，P1-P9、C1-C4 全部 PASS，任务级结论 PASS，并已通过普通快进推送集成至 `master@df8644d828680a75ff955db59c546d4ba1caa729`**（2026-07-27）：在本地专用 PostgreSQL 测试库 `auto_wechat_outbox_test`（Alembic 0016 head）验证 outbox 跨进程可见性、20 路 MVCC 领取竞争、租约恢复、发送对账与旧 Worker 防覆盖语义，全程禁止真实外部动作。R1-REPAIR-1 修复 0016 迁移链断裂（`down_revision` 从错误缩写 `"0015"` 修正为真实前驱 `"0015_ai_edit_material_library"`，迁移图唯一 head=0016）；R1-REPAIR-2A 对齐 `AiAutoReplyRun.gate_results_json` 方言感知类型——自定义 `TypeDecorator`（`impl=Text`，PostgreSQL 用 `JSONB(none_as_null=True)`、SQLite 用 `Text()`），PostgreSQL 写入前 `json.loads` 解析为对象/数组避免双重编码、读回后 `json.dumps` 重新序列化为字符串，对外保持 `str|None` 契约，`None` 写为 SQL NULL，非法 JSON 字符串在 PostgreSQL 写入前抛 `JSONDecodeError`；不修 `ReturnVisitRun.gate_results_json`（其 PG 迁移本就是 Text，一致）；R2/R3 为测试加固（P7 sent 流水夹具 Core insert 省略范围外 JSONB 列、P8 新租约与新 Worker 诊断值防覆盖断言）。验收矩阵：P1 安全门合同、P2 Alembic 0016 schema（jsonb/tz 字段/索引/`alembic_version=0016`）、P3 跨进程提交可见性、P4 20 路子进程文件门禁 claim 连续 10 轮单胜（`attempt_count=1`/`lease_owner` 非空）、P5 `os._exit(23)` 后租约未过期不领取/过期恢复一次（`recovered_failure_stage=lease_expired`）、P6 `retry_wait` 到期边界、P7 `send_authorized` 有/无 sent 流水对账（`sent`/`send_unknown`）、P8 旧 owner `guarded-block-once` `rowcount=0` 不覆盖新 owner/新租约/新诊断值（`block_reason='pg_new_owner_state'` 保持）、P9 `external_calls=0`/意外流水 0/namespace 残留 0/日志无明文凭据；C1 `_GateResultsJSON` PostgreSQL/SQLite 类型及字符串合同（后续第 30 节泛化为共享类型 `_JSONStringJSONB`）、C2 SQLite 重启恢复 R1-R11 无回归、C3 outbox/send/dry-run/webhook 相邻回归无 Candidate 新增失败、C4 编译/范围/线性/工作区和差异检查；`_claim_test_webhook_event` 注释合同（helper 规避 ORM Text→JSONB 类型错误，不声称已存为对象）单独记录。独立测试数字：schema 合同 `11 passed`、PostgreSQL 专项 `22 passed, 0 skipped`、连续 10 轮共 `220 passed`、SQLite 重启恢复 `11 passed`、状态机回归 `149 passed + 1` 个范围外基线（`test_active_binding_calls_9100_with_history_and_records_decision_log`，后续确认根因是旧 dry-run 测试夹具未写事件 `merchant_id/tenant_id`，不是 `douyin_conversation_history_service.py` 业务服务缺陷，已由 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的 R1-T1 闭合；该历史报告当时仅能判为范围外基线，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）、webhook 回归 `89 passed`，Candidate 0 个新增失败；`external_calls=0`、意外流水=0、namespace 残留=0、遗留子进程=0。已通过普通快进推送集成至 `master@df8644d828680a75ff955db59c546d4ba1caa729`；只验证本地专用 PostgreSQL 数据库，不等于生产验证，未验证生产调度、生产迁移和生产恢复，未连接 staging/production，未真实发送，未运行全仓测试，尚未部署或发布。

- **9000 PostgreSQL JSONB/ORM 一致性首批返修（P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1/R1）最终候选 `9a2f1aabb7725de6e12822ce194c1d8ad15c2904`（Base `1042a07ab3b4267586ea5b9fc5e69ceed9f1099a`，7 个单父线性提交，8 个允许实现/测试文件）已通过独立测试 R1，J1-J16、B1-B8 全部 PASS，任务级结论 PASS，`9a2f1aa` 已进入远端 `master@020ab730bae8ac2c570ce4e0e185f203b62b08e4` 的线性历史**（2026-07-27）：在本地专用 PostgreSQL 测试库 `auto_wechat_outbox_test`（Alembic 0016 head）闭合原 gate 字段 1 个 + 本批高优先级字段 10 个（webhook 2、发送流水 2、决策日志 6），合计 11 个 JSON 字符串字段的 ORM 映射与文本筛选。`_GateResultsJSON` 泛化为共享类型 `_JSONStringJSONB`（`impl=Text`，PostgreSQL 用 `JSONB(none_as_null=True)`、SQLite 用 `Text()`，PG 写入前 `json.loads` 解析避免双重编码、读回 `json.dumps` 重新序列化为字符串，对外保持 `str|None` 契约，JSON 文本 `"null"` 含空白形式跨方言统一映射为 SQL NULL，非法 JSON 在 PG 写入前抛 `JSONDecodeError`）；映射首批 11 个 JSON 字符串字段（`AiAutoReplyRun.gate_results_json`、`DouyinWebhookEvent.raw_body`/`parsed_content_json`、`DouyinPrivateMessageSend.request_body_json`/`response_body_json`、`AiReplyDecisionLog` 的 `risk_flags_json`/`tags_json`/`rag_sources_json`/`source_chunks_json`/`allowed_category_keys_json`/`raw_response_json`）；新增 `_IntegerBoolean`（`impl=Integer`，PG 编译 BOOLEAN、SQLite 编译 INTEGER，绑定时 0/1 转 False/True，读回仍为严格 int 0/1，损坏值抛 `ValueError`，`None` 写 SQL NULL），映射 7 个整数布尔字段（`DouyinPrivateMessageSend.manual_confirmed`/`auto_send`、`AiReplyDecisionLog.manual_required`/`llm_used`/`rag_used`/`upstream_auto_send`/`final_auto_send`），`is_effective` 保持普通 `Boolean`；webhook 原子占位移除手工 `cast(JSONB)`，由列类型完成 JSONB 参数绑定；JSONB 文本筛选显式 `cast(column, Text).like(...)`（webhook_event_service / douyin_merchant_isolation / douyin_workbench_conversation_service / ai_reply_decision_log_query_service）；`_pg_url()` 严格限制 `postgresql+psycopg`/`127.0.0.1`|`localhost`/`5432`/`auto_wechat_outbox_test`/无 query fragment。独立测试数字：PostgreSQL 专项 `38 passed, 0 skipped`（J7 内部 20 路×10 轮单胜，专项另连续 3 轮通过）、webhook/atomic/workbench `157 passed`、outbox/send/dry-run `149 passed + 1` 个范围外基线失败（`test_active_binding_calls_9100_with_history_and_records_decision_log`，IndexError 行 580，Base/Candidate 同环境一致）、PostgreSQL MVCC `22 passed`、SQLite 重启恢复 `11 passed`，Candidate 0 个新增失败。其中 `test_active_binding_calls_9100_with_history_and_records_decision_log` 基线已由后续测试夹具返修 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的独立测试 R1-T1 闭合；该后续任务未倒改本段独立测试当时的 `149 passed + 1` 结果。`020ab730bae8ac2c570ce4e0e185f203b62b08e4` 将 `DouyinLead.raw_data`/`all_extracted_contacts` 改用 `_JSONStringJSONB`，该提交不属于 `9a2f1aa` 的 R1 独立测试报告覆盖范围，不继承 38 passed 结论。只验证本地专用 PostgreSQL 数据库，不等于生产验证，未验证生产调度、生产迁移和生产恢复，未连接 staging/production，未真实发送，未运行全仓测试，尚未部署或发布。

- **会话历史测试夹具基线返修（DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1/R1）候选 `7011828ee73a2aa0bab88cb9c75c823a2336ec84`（父提交 `dc6c9f47311e8d61448ab247ac54d1356a188abf`）已通过独立测试 R1-T1 并快进集成至远端 `master@7011828ee73a2aa0bab88cb9c75c823a2336ec84`**（2026-07-28）：修复对象仅为 `tests/test_ai_auto_reply_dry_run.py` 的旧夹具；三条历史事件显式写入 `merchant-1/tenant-1`，夹具默认值仍为 `None`，未修改任何业务服务或商户过滤。此前 IndexError 的根因是 `merchant_id=NULL` 事件被正确隔离而历史为空，随后测试下标访问失败，不是会话历史服务缺陷。独立测试：目标历史用例 `1 passed`、NULL 商户历史隔离 `1 passed`、dry-run/会话历史/代理/商户隔离相邻回归 `138 passed, 0 failed`、outbox/send/dry-run 组合 `149 passed, 0 failed`、`py_compile` 通过；未连接 PostgreSQL/staging/production，未调用真实 LLM/9100/抖音/微信，未真实发送，未运行全仓测试。

- **抖音客服会话增量协议（DY-CS-CONVERSATION-INCREMENTAL-PROTOCOL-1）实施中**（2026-07-28）：基于 `DouyinWebhookEvent.id` 的会话/消息增量协议、账号水位与历史消息分页。Task 1（`43c20ef`）路由合同与 422 互斥校验；Task 2（`ee294e8`+`41751e1`）共享事件页与消息游标（`_build_message_rows_statement`/`_query_message_row_page`/`_load_message_page`，坏事件推进水位不形成消息，初始受限页 `next_after_event_id` 回会话 `latest_event_id`）；Task 3（`ebe6ab2`）账号级 `latest_event_id` 与会话摘要增量页（`get_account_latest_event_ids` 与 `get_account_unread_counts` 并列调用，权威未读不从页求和，`after_event_id` 与 `event_limit` 互斥 422 `DOUYIN_CONVERSATION_CURSOR_CONFLICT`）；Task 4（`69c0138`+`42737ce`）PostgreSQL 5 万行执行计划门禁已通过——新增 0017 索引 `(merchant_id,to_user_id,id)`/`(merchant_id,from_user_id,id)`（CONCURRENTLY + `autocommit_block` 跳出事务），`_query_message_row_page` 用 `union_all` 双单侧子查询 + Python 按 id 去重消除 OR 条件导致的 Seq Scan，门禁验证改为捕获生产真实 SQL 而非手写捷径；后端三件套（Task 2/3/4）已闭合。前端 Task 5-7（API 类型/纯 TS 增量模块/页面全账号同步）待实施；前端已有 mark-read 高频刷屏（~160ms，useEffect 级联）属 Task 7 重写范围。治理约束：执行窗口协作纪律四条（禁止范围外发散/文档影响同步/不确认即停/任务展开先复述）已写入 CLAUDE.md/AGENTS.md 第 11 条（`a8f4c8b`）。

- **2026-07-28 生产 hotfix 与自动回复上生产验证**：四组生产 500/异常已逐层修复并推送部署验证——① settings 等多表 JSON 列 ORM 漏用 `Column(Text)` 触发 jsonb 500（`a65912b`，4 表 10 列改 `_JSONStringJSONB`）；② 发送上下文过期判断 `_is_context_expired` naive/aware datetime 相减 TypeError（`a40eccf`，按对端时区取同基准 now，人工+自动回复双链路共享函数一处修复）；③ 9100 `llm_call_logs.conversation_id` bigint 拒收抖音 base64 会话 ID 致 9100 返回 500 丢弃已成功 LLM 结果（`1026f67`，9100 迁移 0003 列改 varchar(255)，ROW_COUNT=0 无数据兼容风险）；④ outbox 积压告警 `alert_backlog` 同类时区 TypeError（`7d863da`）。outbox 调度器经 `AI_AUTO_REPLY_OUTBOX_ENABLED=true` 启用后 pending run 得以 claim 推进。生产验证自动回复真实发送成功（run_id=68：webhook 入站→outbox claim→智能体绑定→9100 LLM 生成→发送 gate 通过→抖音 `/send_msg` 真实发送，`real_send_enabled=true`/`send_gate_passed=true`/`final_auto_send=true`）；该账号 `send_enabled=true`/`dry_run_enabled=false` 为真实发送模式。
- **抖音会话增量协议前端 Task 5-7 已落地并生产验证**（2026-07-28）：Task 5（`4fa38dd`）前端 API 类型与请求合同（游标字段 `latest_event_id`/`after_event_id`/`before_event_id` 等）；Task 6（`34723ea`）纯 TS 增量模块 + 无依赖行为检查（`mergeMessagesByEventId`/`mergeConversationSummaries`/`advanceEventCursor`/`retryDelayMs`/`runWithConcurrency`/`createCoalescedRunner`）；Task 7（`9a537c4`+`f130ae8`）页面全账号单飞合并同步 + 恢复触发（visibilitychange/focus/online）+ 8s 定时器 + 历史消息分页（before_event_id + 滚动锚点）+ 同步状态显示；**mark-read 高频刷屏已修复**（`5a26d30`）：根因是 mark-read 去重键含 `request_seq`，增量同步每次递增 seq 致去重失效高频重复提交，改为按 `(account, conversation, max_event_id)` 去重，生产验证刷屏消除（2 分钟 20+ 次 → 3 次）。前端部署后 mark-read 频率降到事件触发级，不写 localStorage/sessionStorage，不上 SSE/WebSocket。计划一 DY-CS-CONVERSATION-INCREMENTAL-PROTOCOL-1 候选 `5a26d30` 已推送远端并部署验证。

### 8.3 回访（Phase 9，DONE_WITH_CONCERNS）

- 回访提示词驱动"微信销售反馈 → 抖音回访"闭环已落地（配置/运行记录/审计接口 + 分层崩溃恢复 + 安全阻断）。
- 拒答/注入等安全阻断**不进兜底**；关键词判定归 9100；沉默客户唤醒由销售微信反馈触发，一期不做基于抖音会话时间的自动扫描。
- 遗留关注项：`baota_production_send_not_verified`（宝塔生产环境真实发送未验证）。

------

## 9. 当前线索与微信助手边界

### 9.1 线索链路（webhook 直收）

```text
GMP/抖音私信 → callback.misanduo.com/webhook/douyin → 宝塔反代 → 9000
  → 双入口 /webhook/douyin 与 /integrations/douyin/webhook 共用 _handle_douyin_webhook()
  → 验签 sha256Hex(SECRET_KEY + body + "-" + timestamp)，event_key 幂等
  → im_receive_msg → contact_extractor → douyin_leads
  → 分配销售 → 创建微信通知任务 → Local Agent 通知 → 回复检测回写（FIX-1 已接通）
```

- 验签环境策略：`APP_ENV=production` 强制验签（缺 `DY_SECRET_KEY` 拒绝请求）；development 允许 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 仅用于本地联调。
- **抖音 Webhook 原子幂等（DY-CS-WEBHOOK-ATOMIC-IDEMPOTENCY-1）最终候选 `96a764e25defda5978d9c2d593e168ff411193c0` 已通过独立测试（R3-T1，A1-A14 全部验收通过，任务级结论 PASS）**（2026-07-24）：9000 与 9202 共用同一处理核心 `process_webhook_event`，处理顺序为"只读解析 → 原子占位 → 胜出者副作用"；PostgreSQL 使用 `ON CONFLICT DO NOTHING RETURNING` + 2 个 JSONB CAST（raw_body + parsed_content_json），SQLite 使用同语义方言语句；嵌套提交已消除（`assign_lead`/`auto_assign_next`/`mark_manual_takeover` 支持 `commit=False`，commit 计数器验证默认 1 次、commit=False 0 次），统一由请求边界提交；非预期派单或后置处理异常上抛并整体回滚；A4 在异常前断言事件/线索/ReplyCheck/LeadFollowupRecord 均已进入事务，异常后监视外层 rollback 并断言四类数据全部为 0；A5 监视人工接管异常路径 rollback 实际调用；19 个重复返回继承非空 lead_id，19 条重复审计行继承 lead_id、merchant_id、tenant_id；独立测试：专项 28 passed、三类 20 路并发各重复 10 轮共 30 passed、完整指定回归 163 passed，合计 221 passed, 0 failed；已通过普通快进推送集成至 `master@96a764e25defda5978d9c2d593e168ff411193c0`；尚未部署或发布，未验证真实 PostgreSQL、PostgreSQL MVCC 并发、生产环境、生产迁移和真实私信/自动回复/微信发送，未运行全仓测试。
- `/leads` 只展示有效线索；原始/invalid 事件走 `GET /webhook-events`（只读）。
- 旧拉取链路 `/integrations/douyin/sync-leads` 保留但已非事件回调归属，处置待定（见第 12 节）。

### 9.2 Local Agent 与微信自动化

- 任务模型：`poll-and-execute` 只处理 `notify_sales`，`poll-and-detect` 只处理 `detect_reply`，两者互斥；必须按 `task_id` 指定执行，禁止依赖旧 pending 队列顺序。
- 旧的 9000 直操自动检测调度器默认禁用（需 `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1`）。
- 发送硬性保护（除非用户明确批准不得放宽）：
  1. foreground guard 失败必须停止；hidden/minimized 微信禁止自动恢复后继续；业务路径禁用 ESC。
  2. 不允许绕过 search_focus guard / search_text_verified；未经联系人验证不得粘贴或发送；partial_match、manual_review_required 必须阻断并回写原因。
  3. OCR/截图失败不能伪造成功；检测链路保持只读。
  4. 真实派单发送必须有：联系人验证、前台焦点、违禁词替换、人工接管、限频、失败回写、幂等、紧急停止（Alt+Q + `/automation/emergency-stop`）。
  5. 诊断接口（search-debug 等）不得返回原始 UIA 对象，必须安全 JSON 序列化。
- Local Agent 调试端点 `run_local_wechat_test` 已取消 Aw3 唯一联系人限制，接受任意非空联系人昵称；测试仍固定仅粘贴不发送，并继续执行搜索焦点、搜索文字、联系人验证、前台焦点和紧急停止门禁。业务发送同样不依赖 Aw3 硬编码，靠 gate 组合保护。
- 发送方识别技术结论（长期有效）：纯 UIA 无法可靠读取 Qt 微信标题/气泡归属；采用截图像素分析识别 sender（self/friend/system），真机验证零误判。
- 有效确认回复判定规则（关键词/长度/超时，`check_configs` 可配）与微信 UI 检测逻辑（窗口定位、发送方级联识别、兜底模式需人工复核）见专题文档：`docs/ai/10_local_agent_wechat/WECHAT_REPLY_DETECTION_RULES.md`。

### 9.3 报表（Phase 8）

- Phase 8-A 每日自动报表（4 类 Excel、后台管理、安全下载、定时生成）：**DONE**（sample_alignment 甲方 2026-07-13 确认 VERIFIED）。
- Phase 8-B 日报 Excel 附件微信真实分发：**PARTIAL_BLOCKED_DEFERRED**——投递服务/状态机/灰度开关已落地，但 Qt UIA 未暴露文件气泡控件，真机附件发送验证转 `verify_pending` 人工审计方案。
- 微信侧通知限频：固定 10 秒窗口 + 已 sent 幂等去重。

------

## 10. 当前前端与菜单能力

- 位置：`auto_wechat/frontend`（React + TypeScript 5.9 + Vite）。**不存在独立的 `E:\work\project\react` 项目**；不要新建第二套前端。
- 主要页面：线索/销售/检测/报表、微信助手（WechatAgent）、本机 Agent 面板、抖音AI客服工作台（DouyinAiCsWorkbenchPage）、抖音直播间检测、webhook 事件、超管后台系列（商户、账号、AI 回复记录、算力配置、跟进话术、违禁词、商户 Agent 绑定）、回访配置与运行记录、日报管理、能力中心（ComputeCenter 可作支付 mock 参考）。其中违禁词管理页已挂载并接通真实后端 API（`/admin/forbidden-words`，复用 `auto_wechat:admin:forbidden_words` 权限）；"自动回复灰度"入口已在超管侧栏隐藏，页面/路由/权限码保留不删。
- 侧栏底部动作按 `isAdminLike(user)` 互斥：管理员显示“切换到 NewCar”和“退出登录”两个动作；普通商户显示“修改密码”和“退出登录”两个动作。切换由浏览器直调 NewCar，不改变 401 跳转门禁；管理员退出浏览器直调 NewCar `logout-current-browser`（`credentials: include`）；普通退出由 9000 `/auth/logout` 注销门面处理，改密由 9000 `/auth/password` 门面处理。三者均在请求开始到结果页持续抑制在途请求的全局 401 跳转，保留当前 URL，失败重试 token 仅存页面内存，主动重新登录前恢复正常跳转。**退出（管理员退出与普通退出）无论成功或失败都清理本地持久状态**；**改密单独按四态分流**：`business`（400/403）保留登录态并恢复 401 跳转，`success`/`relogin`(401)/`unknown`（超时/网络/5xx/异常 JSON/2xx 非白名单）清本地持久状态进入结果状态页且不恢复旧会话，只有 `success`（严格匹配 `ok===true && relogin_required===true && revoked_session_scope==="all"`）能展示「密码已修改」，`relogin` 展示「登录已失效」，`unknown` 展示「结果未知」、不得声称成功或失败；`handleRelogin` 将结果状态恢复为 `null`。
- TS 配置约束（稳定约束，禁止改动）：`ignoreDeprecations: "5.0"`（TS 5.9.3 不支持 "6.0"）、`composite: true`、`emitDeclarationOnly: true`（不与 noEmit 组合）；禁止自动升级或重构 TS 配置。
- 离线提示文案："未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手"。Local Agent 名称为**小高AI微信助手**，禁止使用"萌猫微信助手"。
- 微信助手页面与侧栏底部“小高AI系统测试版”共享同一份本机状态和版本：只以浏览器所在电脑 `127.0.0.1:19000` 的 `/health` 与运行状态接口为准，每 5 秒及窗口重新聚焦时刷新；本机离线时两处都显示“离线”，版本显示 `-`。9000 `/agent/status` 的心跳只用于诊断，不得回退为当前电脑在线判定。

------

## 11. 当前已完成能力（提炼）

- 微信助手主链路：webhook 直收 + 线索入库 + 商户隔离 + 销售分配 + 微信通知 + 回复检测回写闭环（P1-END-1 冻结验收：`docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md`；webhook 接分配通知 FIX-1 已完成）。
- 抖音AI客服：多账号工作台、企业号授权、Agent 绑定（9000 权威源）、分类知识库 RAG、结构化回复与决策日志、AI 回复记录商户只读页。
- 自动回复 gate 体系：灰度门禁已放开（仅 env 总开关决定是否自动发送）、限频/违禁词替换/人工接管/幂等/每日上限/紧急停止（env 与账号级开关默认全关）。
- 统一知识库训练链路（8788 → 9000 → 9100 → Milvus 副本）。
- 小高算力：Phase 10 本地模拟闭环和三方复审已完成；聊天模型计量已升级为优先使用供应商真实 Token，缺失有效用量时才估算，历史 AI 消费标记为 `legacy_characters`，每次模型重试独立入账并记录调用阶段。六能力上浮、计费快照、前端与权限闭环已落地，支付仍为 mock；生产迁移与真实扣费验证仍为 `baota_production_compute_not_verified`。商户流水接口和页面只返回类型、中文使用场景、算力点数变动、变动后余额和时间；模型、能力编码、计量明细、智能体、会话和内部备注仅保留在内部账本，不向普通商户公开。管理员算力配置接入**已完成独立测试并已推送**：已收敛为单入口 `/admin/compute-config`，内含三个视图——计费比例（`?view=ratios`）、套餐管理（`?view=packages`）、商户发放（`?view=merchant-grant`），默认进入计费比例；旧地址 `/compute/packages`、`/compute/markup-ratios` 重定向到对应视图。9000 与独立算力服务的管理接口使用统一权限守卫：超级管理员或精确权限 `auto_wechat:admin:compute_config` 可访问；普通商户权限和其他管理员权限不得访问；权限上下文不接受前端正文或查询参数。管理写入操作均产出结构化审计日志（`compute_admin_action operation/operator_id/target/status/failure_stage/error_type`），日志不回显备注等敏感字段。9000 与独立算力服务的权限和日志闭环已通过独立测试验证，最终合并提交为 `417d68c0bda167a945f45279ec62a5eb1a950941`（已推送 master）；宝塔生产算力验证仍为 `baota_production_compute_not_verified`。
- Phase 8-A 日报（DONE）；Phase 8-B 附件投递服务侧（真机验证 deferred）。
- Phase 9 回访闭环（DONE_WITH_CONCERNS）。
- 数据库：PG 方案 A schema 全量（9000 约 30 表 / 9100 7 表）、双 Alembic 轨道、cutover 脚本与 Runbook、staging 演练通过、production 执行包就绪。
- 巨量一键过审真实联调曾全链路打通（2026-07-10），**随后被客户取消**，代码保留不回退。

------

## 12. 当前未完成事项

| 事项 | 状态 |
|---|---|
| 9000/9100 PostgreSQL **production 切换** | 执行包就绪（READY_FOR_BAOTA_EXECUTION），待人工在宝塔执行 Runbook |
| Phase 8-B 真机 Excel 附件发送验证 | PARTIAL_BLOCKED_DEFERRED，转 verify_pending 人工审计 |
| Phase 9 宝塔生产真实发送验证 | DONE_WITH_CONCERNS 遗留项（baota_production_send_not_verified） |
| 小高算力宝塔生产验证 | Phase 10 DONE_WITH_CONCERNS 遗留项（baota_production_compute_not_verified），不阻塞 Phase 12/13；生产验证前需确认：权限码 `auto_wechat:compute` 登记 / `COMPUTE_INTERNAL_TOKEN` 配置 / super_admin 口径 |
| `/integrations/douyin/sync-leads` 旧链路处置 | 保留中，待决策移除或归档 |
| webhook 验签历史矛盾收敛 | 生产强制验签已实现；历史文档曾写"不允许改回强制鉴权"，已废弃，以 `APP_ENV=production` 强制验签为准；线上实际 env 值需在生产窗口确认 |
| douyinAPI 旧 `/auth/callback` 授权能力迁移 | 待排期 |
| QPS600 目标 | 基准与灰度工具已就绪，未经生产验证 |
| AI剪辑 LAS 重做 | 2026-07-31 恢复（原 2026-07-18 FROZEN_BY_CUSTOMER 已解除）。纯 LAS 云端方案：9000→LAS submit→轮询→存产物；旧 FFmpeg/9100规划/19000执行面已删除，数据模型 7 表保留复用，新增 LAS 字段迁移 0022/0042，算力 capability_key=ai_edit，前端新工作台 LasRemixWorkbench。生产验证另行审批 |
| init-prod 脚本 `--username` 显式化同类 bug | staging 已修，生产窗口需复核 |

------

## 13. 当前风险与强制注意事项

### 13.1 生产部署

1. 宝塔生产用根目录 `docker-compose.yml`（dev 镜像形态）+ `.env.production.local`，必须 `APP_ENV=production`。
2. PG 切换必须走 Runbook（备份 → preflight → ensure-databases → alembic → dry-run → apply → switch → smoke → 可回滚），禁止跳步。
3. staging 覆盖文件禁止单独运行；`!override` 不是 `!reset`。

### 13.2 测试与回归

1. 全量 pytest 必须 `--ignore=dist --ignore=dist_backup_20260616_130831`（PyInstaller 产物会污染 collection；该约定目前无仓库配置载体，仅此处记录）。
2. 本地 `.env` 若 `NEWCAR_AUTH_ENABLED=true`，不 override auth 的测试会批量 401；回归诊断先设 `NEWCAR_AUTH_ENABLED=false` 或用 worktree 对照。
3. proxy env 组合（`.env.lan.local` 被 `app.config` 加载）会让 proxy+llm 组合测试大面积失败（pre-existing）；含 proxy 的回归失败先隔离验证。
4. 存在 pre-existing 失败基线（auth/ocr/utf8/9100 等）；判断回归用 git stash / worktree 对比零新增放行，不要求历史全绿。

### 13.3 安全与合规红线（长期有效）

1. 微信自动化三禁：不读微信数据库、不 DLL 注入、不协议逆向；优先 UI Automation / 视觉识别 / OCR。
2. Local Agent 默认只监听 `127.0.0.1:19000`，不得监听 `0.0.0.0`。
3. 第 8、9 节的发送 gate 与阻断规则，除非用户明确批准不得放宽。
4. 高风险区域（Docker/Nginx/环境变量/迁移/鉴权/RBAC/存储/Worker/部署/CI）必须先风险分析再修改。
5. Bug 修复必须先探索根因（调用链/根因/影响面），禁止仅凭现象编写修复；高风险逻辑必须写含 `stage`、输入摘要、`failure_stage` 的诊断日志。
6. 日志与诊断输出必须脱敏（token、SECRET_KEY、手机号、微信号、open_id、原始 body 等）。

------

## 14. 后续执行窗口的推荐入口

| 场景 | 入口 |
|---|---|
| 一期需求权威文档 | `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md` |
| 产品边界（历史 PRD） | `docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md` |
| 系统架构 | `docs/ai/02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md` |
| 数据模型 / PG 迁移路线 | `docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md`、`POSTGRESQL_MIGRATION_NOTES.md` |
| PG 生产切换 Runbook | `docs/ai/05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md` |
| 接口契约 / Webhook 鉴权 | `docs/ai/04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`、`10_WEBHOOK_AUTH_MIGRATION.md` |
| 微信自动化验收基线 | `docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md`（改微信自动化前必读） |
| RAG / Milvus / 统一知识库 | `docs/ai/06_rag/` |
| 自动回复 gate / rollout | `docs/ai/07_autoreply/` |
| NewCar 权限 | `docs/ai/08_newcar/P1_AUTH_PERMISSION_ROUTE_MATRIX.md` |
| Local Agent / 微信自动化专题 | `docs/ai/10_local_agent_wechat/` |
| 部署 / Docker | `docs/ai/11_deployment_ops/LOCAL_DOCKER_DEV.md` |
| 一期路线图与阶段状态 | `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` |
| Phase 12 AI剪辑本地 MVP 历史设计 | `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`（历史设计，2026-07-31 已被 LAS 云端方案替代，旧 FFmpeg 代码已删除） |
| Phase 12 Task 12 私有素材闭环冻结规格 | `docs/superpowers/specs/2026-07-16-phase12-task12-ai-edit-material-library-closed-loop-design.md`（不可执行） |
| Phase 12 Task 12 新执行包 | 冻结期间不得生成；恢复必须等待甲方新的书面指示并重新审批 |
| Phase 12 Task 12 旧执行包冻结快照 | `docs/ai/archive/2026-07-17_Phase12_Task12_平台公共与回收站旧执行包_冻结快照.md`（非当前事实，不得执行） |
| 历史里程碑流水账（追溯） | `docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md` |

专题目录按需读取，禁止默认遍历整个 `docs/ai`。
