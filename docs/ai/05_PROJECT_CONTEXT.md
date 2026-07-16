# auto_wechat 当前项目上下文

> 本文档是 AI Coding Agent 的当前项目事实文档。
>
> 优先级低于阅读规范，高于执行规范、测试规范和输出规范。
>
> 任何 AI 开始任务前必须先阅读本文档。

------

## 1. 文档定位与更新时间

- 定位：**只保存当前有效上下文**，不记录里程碑流水账，不按日期追加任务完成记录。
- 更新时间：2026-07-17（Phase 12 基础 MVP Task 0-10 + Task 10-FIX1~FIX6 已完成，检查点 A/B/C 均 PASS；Task 11 单入口 EXE 状态 `BUILT_FOR_CUSTOMER_TEST`，SHA-256 `13A05B75EC3AF7E247EA86FDA26AA88AB2A81C9E4E23380EF4233B42C4BB6681`，新包待干净虚拟机复测。Task 12“素材库真实闭环增强”设计与逐任务执行包已就绪，状态 `READY_FOR_EXECUTION`、实施未开始，目标闭合回收站、自动分析、宝塔受控云端上传和素材库三栏/移动端界面；Phase 13 完成前不得启动宝塔生产验证）。
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

1. AI剪辑纳入一期；Phase 12 基础 MVP Task 0-10 + Task 10-FIX1~FIX6 已完成，Task 11 单入口 EXE 当前 `BUILT_FOR_CUSTOMER_TEST`（API 基址含 `/api`，公网前端 GET/DELETE CORS/PNA、严格回环鉴权、单 token 商户绑定、Worker 凭据隔离、单 App 启动和离线 EasyOCR 运行时/模型均已验证，SHA-256 `13A05B75EC3AF7E247EA86FDA26AA88AB2A81C9E4E23380EF4233B42C4BB6681`）。Task 12“素材库真实闭环增强”设计与执行包已就绪，状态 `READY_FOR_EXECUTION`、实施未开始，目标闭合回收站、导入后自动分析、9000 宝塔受控云端上传及素材库三栏/移动端界面；本地操作仍保持前端→19000→9000，浏览器不直连 9100。正式安装包和宝塔生产验证均未启动。
2. **一键过审已于 2026-07-13 被客户取消（CANCELLED_BY_CUSTOMER）**，不再是一期交付范围；不删除历史记录、不回退已落地代码和兼容字段。注意与历史 Phase 8 Task 11（日报样本对齐，已 VERIFIED）重名但无关。
3. `auto_wechat:ai_edit` 是 AI剪辑入口权限，不新增 `auto_wechat:ai_video` / `auto_wechat:ad_review`。
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

- 登录委托 NewCarProject：前端 → 9000 `exchange-code` / `me`；9000 是鉴权门面。
- 代码默认值是开发态：`NEWCAR_AUTH_ENABLED` 默认 `False`、`NEWCAR_AUTH_MOCK_ENABLED` 默认 `True`（`app/config.py`）。本地真实鉴权联调必须显式 `NEWCAR_AUTH_ENABLED=true` + `NEWCAR_AUTH_MOCK_ENABLED=false`；生产模板已固定真实鉴权。
- 退出登录必须走 `POST /auth/logout`（`app/routers/auth.py`），由 9000 调 NewCarProject `POST /api/external-auth/logout`；不能只清前端本地 token。
- token 不自动刷新；权限码识别 admin；1 商户 = 1 账号。

### 5.2 商户隔离

- `merchant_id` 来自 RequestContext（服务端解析），**不来自前端**；非 super_admin 按当前商户过滤，super_admin 可跨商户（`app/routers/leads.py` 等）。
- 线索/会话隔离、`sales_staff.merchant_id`、外部商户绑定已通过迁移落地（SQLite 0011 / 0021 / 0023）。
- AI 回复记录按 `RequestContext.merchant_id` 隔离，且不返回 `raw_response_json`。
- 抖音企业号绑定 open_id、线索会话商户隔离、工作台商户上下文（智能体列表走 9000 代理）均已闭合。

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
| PostgreSQL Alembic（9000） | `migrations/postgres/auto_wechat/`（版本 0001~0013） | 覆盖主服务运行表；0011/0012/0013 分别为回访、算力、AI剪辑 |
| PostgreSQL Alembic（9100） | `migrations/postgres/xg_douyin_ai_cs/`（0001 空基线 + 0002 RAG metadata 7 表） | |

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

### 8.2 真实发送 gate（现已落地的组件）

配置默认全关（`app/config.py`）：`DOUYIN_AUTO_REPLY_ENABLED` / `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` 默认 False。**一期已放开自动发送灰度**：`ALLOW_FULL_ROLLOUT` 与账号/客户/会话 env 白名单、数据库灰度门禁（`evaluate_db_rollout_gate`）不再阻断自动发送——是否允许自动发送只由上述两个 env 开关决定，数据库灰度配置仅保留为诊断快照；超管后台"自动回复灰度"入口已在前端隐藏。账号级 `settings.send_enabled` 默认仍为 OFF。

gate 链（`app/services/douyin_autoreply_gate_service.py` 等）：

1. pre-LLM gate：人工接管（manual_takeover）阻断、每小时会话限频。
2. real-send gate：env 总开关（`DOUYIN_AUTO_REPLY_ENABLED` + `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`）、账号级 `send_enabled`、绑定智能体、账号级客户/会话白名单（可选收窄）、每日会话上限（real_send_limits）。
3. 发送前违禁词替换（`replace_forbidden_words`；违禁词→安全词逐词映射，**替换不拦截**）。
4. 幂等去重（`already_sent`）；人工发送后标记 manual_takeover。
5. 紧急停止（`POST /automation/emergency-stop`）。

- 切换为“AI 托管”时会写入完整的直接模型回复启用策略，并清空历史意图白名单和风险白名单；切换为人工接管只关闭账号真实回复，不删除其他配置。
- 9000 完成绑定校验后注入的 `agent_config` 是可信上下文，9100 不再因未命中知识而把它视为降级配置。模型返回的 `auto_send` 永远不直接控制发送，值为 true 时仅记录 `llm_requested_auto_send_ignored`；最终候选仍由账号策略、安全后处理和 9000 gate 计算。

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
- 旧"Aw3 唯一联系人 / sent=false"Demo 硬门禁已收缩到 Local Agent 调试端点（`run_local_wechat_test` 的 `ONLY_ALLOWED_NICKNAME="Aw3"`）；业务发送靠 gate 组合保护，不再靠 Aw3 硬编码。
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
- TS 配置约束（稳定约束，禁止改动）：`ignoreDeprecations: "5.0"`（TS 5.9.3 不支持 "6.0"）、`composite: true`、`emitDeclarationOnly: true`（不与 noEmit 组合）；禁止自动升级或重构 TS 配置。
- 离线提示文案："未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手"。Local Agent 名称为**小高AI微信助手**，禁止使用"萌猫微信助手"。

------

## 11. 当前已完成能力（提炼）

- 微信助手主链路：webhook 直收 + 线索入库 + 商户隔离 + 销售分配 + 微信通知 + 回复检测回写闭环（P1-END-1 冻结验收：`docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md`；webhook 接分配通知 FIX-1 已完成）。
- 抖音AI客服：多账号工作台、企业号授权、Agent 绑定（9000 权威源）、分类知识库 RAG、结构化回复与决策日志、AI 回复记录商户只读页。
- 自动回复 gate 体系：灰度门禁已放开（仅 env 总开关决定是否自动发送）、限频/违禁词替换/人工接管/幂等/每日上限/紧急停止（env 与账号级开关默认全关）。
- 统一知识库训练链路（8788 → 9000 → 9100 → Milvus 副本）。
- 小高算力：Phase 10 本地模拟闭环和三方复审已完成；聊天模型计量已升级为优先使用供应商真实 Token，缺失有效用量时才估算，历史 AI 消费标记为 `legacy_characters`，每次模型重试独立入账并记录调用阶段。六能力上浮、计费快照、前端与权限闭环已落地，支付仍为 mock；生产迁移与真实扣费验证仍为 `baota_production_compute_not_verified`。
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
| Phase 12 AI剪辑 | 基础 MVP Task 0-10 + Task 10-FIX1~FIX6 已完成；Task 11 单入口 EXE 为 `BUILT_FOR_CUSTOMER_TEST`，新包待干净虚拟机复测。Task 12“素材库真实闭环增强”设计与执行包已就绪，状态 `READY_FOR_EXECUTION`、实施未开始；自动分析、宝塔云端上传、新回收站和新素材库界面不得提前写成已完成。宝塔生产验证必须等 Phase 13 完成后统一执行 |
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
| Phase 12 AI剪辑本地 MVP 设计 | `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md` |
| Phase 12 Task 12 素材库真实闭环增强设计 | `docs/superpowers/specs/2026-07-16-phase12-task12-ai-edit-material-library-closed-loop-design.md` |
| Phase 12 Task 12 素材库真实闭环增强执行包 | `docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md` |
| 历史里程碑流水账（追溯） | `docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md` |

专题目录按需读取，禁止默认遍历整个 `docs/ai`。
