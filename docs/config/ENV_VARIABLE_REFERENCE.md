# 环境变量参考

本文档是 auto_wechat 全部环境变量的参考清单，按类别整理。

- 三个模板（`.env.development.example` / `.env.lan.example` / `.env.production.example`）只收录「启动必需、安全关键、环境间必须区分、实际经常配置、开启核心功能必填」的变量。
- 低频调优、历史兼容、灰度、测试专用变量**不进入模板**，只在本文档登记。
- 新增 `os.getenv` / `os.environ.get` 读取的变量时，必须同时在本文档登记分类，否则 `tests/test_env_profile_templates.py` 会失败。

列含义：变量 | 读取服务 | 代码默认值 | 是否在模板 | 类别 | 用途
服务缩写：9000=主服务 / 9100=AI客服 / 19000=Local Agent / FE=前端 / compose=容器编排。

---

## 1. 模板部署变量

### Runtime 与数据库

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `APP_ENV` | 9000/9100 | development | 是 | runtime | 运行环境，production 强制 webhook 验签 |
| `PYTHONUNBUFFERED` | compose | 1 | 是 | runtime | 容器日志不缓冲 |
| `DATABASE_URL` | 9000 | sqlite:///data/auto_wechat.db | 是 | database | 9000 主库连接 URL |
| `RAG_DATABASE_URL` | 9100 | sqlite:///<>/xg_douyin_ai_cs.db | 是 | database | 9100 RAG metadata 库 URL |
| `RAG_VECTOR_BACKEND` | 9100 | prod=milvus / dev=sqlite | 是 | database | 向量库后端；production 固定 milvus（外部服务，不回退 sqlite） |
| `SQLALCHEMY_POOL_SIZE` | 9000 | 10 | dev/lan | database | 9000 **SQLite** engine 连接池大小（`database.py:211`） |
| `SQLALCHEMY_MAX_OVERFLOW` | 9000 | 20 | dev/lan | database | 9000 SQLite engine 溢出（`database.py:212`） |
| `SQLALCHEMY_POOL_TIMEOUT` | 9000 | 30 | dev/lan | database | 9000 SQLite engine 获取超时秒（`database.py:213`） |
| `SQLALCHEMY_POOL_PRE_PING` | 9000 | true | dev/lan | database | 9000 SQLite engine 预检（`database.py:214`） |
| `DB_POOL_SIZE` | 9000 | 20 | prod | database | 9000 **PostgreSQL** engine 连接池大小（`database.py:195`） |
| `DB_MAX_OVERFLOW` | 9000 | 40 | prod | database | 9000 PG engine 溢出（`database.py:196`） |
| `DB_POOL_TIMEOUT` | 9000 | 30 | prod | database | 9000 PG engine 获取超时秒（`database.py:197`） |
| `DB_POOL_RECYCLE` | 9000 | 1800 | prod | database | 9000 PG engine 连接回收秒（`database.py:198`） |
| `DB_STATEMENT_TIMEOUT_MS` | 9000 | 5000 | prod | database | 9000 PG `SET statement_timeout` 毫秒（`database.py:247`） |
| `RAG_DB_POOL_SIZE` | 9100 | 20 | prod | database | 9100 RAG **PostgreSQL** engine 连接池大小（`rag/database.py:83`） |
| `RAG_DB_MAX_OVERFLOW` | 9100 | 40 | prod | database | 9100 RAG PG engine 溢出（`rag/database.py:84`） |
| `RAG_DB_POOL_TIMEOUT` | 9100 | 30 | prod | database | 9100 RAG PG engine 获取超时秒（`rag/database.py:85`） |
| `RAG_DB_POOL_RECYCLE` | 9100 | 1800 | prod | database | 9100 RAG PG engine 连接回收秒（`rag/database.py:86`） |
| `RAG_DB_STATEMENT_TIMEOUT_MS` | 9100 | 5000 | prod | database | 9100 RAG PG `SET statement_timeout` 毫秒（`rag/database.py:93`） |
| `EXPECTED_DATABASE_NAME` | 9000 | 空 | prod | database | 9000 健康检查期望库名 |
| `RAG_EXPECTED_DATABASE_NAME` | 9100 | 空 | prod | database | 9100 健康检查期望库名 |
| `PG_USER` / `PG_PASSWORD` / `PG_DB` | compose | 空 | prod | database | docker-compose 初始化 PG 容器 |

### NewCar 鉴权

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `NEWCAR_AUTH_ENABLED` | 9000 | false | 是 | auth | 启用真实 NewCar 登录态校验 |
| `NEWCAR_AUTH_MOCK_ENABLED` | 9000 | true | 是 | auth | 本地 mock 开关 |
| `NEWCAR_AUTH_BASE_URL` | 9000 | 空 | 是 | auth | NewCar 外部认证根地址 |
| `NEWCAR_AUTH_EXCHANGE_CODE_URL` | 9000 | 空 | 是 | auth | 覆盖 exchange-code 完整地址 |
| `NEWCAR_AUTH_ME_URL` | 9000 | 空 | 是 | auth | 覆盖 external-auth/me 完整地址 |
| `NEWCAR_AUTH_LOGOUT_URL` | 9000 | 空 | 是 | auth | 覆盖 logout 完整地址 |
| `NEWCAR_AUTH_LOGIN_URL` | 9000 | 空 | 是 | auth | 前端登录页跳转地址 |
| `NEWCAR_AUTH_SERVICE_TOKEN` | 9000 | 空 | 是 | auth | 服务间令牌（X-NewCar-Service-Token） |
| `NEWCAR_AUTH_TIMEOUT_SECONDS` | 9000 | 5 | 是 | auth | 调用 NewCar 超时 |

### 抖音 GMP / OpenAPI / webhook

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `DY_SECRET_KEY` | 9000 | 空 | 是 | security | webhook 验签密钥 |
| `DY_GMP_SECRET_KEY` | 9000 | 空 | 是 | security | OpenAPI 请求签名密钥 |
| `DY_OPENAPI_BASE_URL` | 9000 | gmp.bytedanceapi.com | 是 | douyin | OpenAPI 域名 |
| `DY_OPENAPI_PREFIX` | 9000 | /ai_chat_agent_api/v1/openapi | 是 | douyin | OpenAPI 路径前缀 |
| `DY_MAIN_ACCOUNT_ID` | 9000 | 0 | 是 | douyin | 主账户 ID |
| `DY_ACCOUNT_NAME` | 9000 | 空 | 是 | douyin | 主账户展示名 |
| `DY_HTTP_TIMEOUT_SECONDS` | 9000 | 20 | 是 | douyin | OpenAPI 请求超时 |
| `DY_ALLOWED_DRIFT_SECONDS` | 9000 | 300 | 是 | douyin | webhook 时间戳漂移窗口 |
| `DY_OAUTH_STATE_TTL_SECONDS` | 9000 | 900 | 是 | security | OAuth state 有效期 |
| `DOUYIN_WEBHOOK_AUTH_REQUIRED` | 9000 | false | 是 | security | 入站 webhook 强制验签 |
| `DOUYIN_RESOURCE_ALLOWED_HOSTS` | 9000 | 空 | dev/lan/prod | security | live-check 资源下载 SSRF 白名单 |
| `PUBLIC_BASE_URL` | 9000 | 空 | 是 | douyin | 9000 对外可访问地址 |
| `DY_AUTH_REDIRECT_URL` | 9000 | 空 | 是 | douyin | OAuth 回跳地址，必须指向 `/integrations/douyin/live-check/auth-redirect`；`oauth-callback` 仅观察不写库 |
| `DY_AUTH_REDIRECT_FRONTEND_URL` | 9000 | 空 | 是 | douyin | 授权完成后跳回前端地址 |
| `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` | 9000 | 空 | 是 | security | OAuth 前端 origin 白名单 |
| `DY_CALLBACK_URL` | 9000 | 空 | 是 | douyin | 抖音事件回调地址 |
| `DY_CALLBACK_EVENTS` | 9000 | 空 | 是 | douyin | 订阅回调事件 |
| `DY_LIVE_CHECK_ENABLED` | 9000 | false | 是 | security | 现场观察模式开关 |
| `DY_LIVE_CHECK_FORWARD_TO_FORMAL` | 9000 | false | 是 | security | 观察事件转入正式 pipeline |

### 服务间与内部安全

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `DOUYIN_API_BASE_URL` | 9000 | 127.0.0.1:8081 | 是 | upstream | douyinAPI 上游地址 |
| `DOUYIN_API_TIMEOUT_SECONDS` | 9000 | 10 | 是 | upstream | 上游请求超时 |
| `DOUYIN_SYNC_DEFAULT_LIMIT` | 9000 | 50 | 是 | upstream | 同步拉取上限 |
| `XG_DOUYIN_AI_CS_BASE_URL` | 9000 | localhost:9100 | 是 | internal | 9000 调 9100 代理地址 |
| `XG_DOUYIN_AI_CS_SERVICE_TOKEN` | 9000/9100 | 空 | 是 | security | 9100 内部服务令牌 |
| `XG_DOUYIN_AI_CS_TIMEOUT_SECONDS` | 9000 | 75 | 是 | internal | 9000 调 9100 超时 |
| `AUTO_WECHAT_9000_BASE_URL` | 9100 | 空 | 是 | internal | 9100 上报算力到 9000 的地址 |
| `COMPUTE_INTERNAL_TOKEN` | 9000/9100 | 空 | 是 | security | 算力上报内部令牌 |
| `COMPUTE_USAGE_TIMEOUT_SECONDS` | 9100 | 20 | 是 | internal | 算力上报超时 |
| `LEADS_SERVICE_BASE_URL` | 9000 | 127.0.0.1:9202 | 是 | internal | 9202 内部线索服务地址 |
| `LEADS_INTERNAL_TOKEN` | 9000 | 空 | 是 | security | 9000 调 9202 令牌 |
| `LEADS_CLIENT_TIMEOUT_SECONDS` | 9000 | 5 | 是 | internal | 9000 调 9202 超时 |
| `LEADS_WEBHOOK_INTERNAL_ENABLED` | 9000 | false | 是 | routing | 9202 internal webhook 总开关 |
| `LEADS_WEBHOOK_FALLBACK_LOCAL` | 9000 | true | 是 | routing | 9202 不可用时回退本地 |

### 知识库训练与自动回复门禁

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `KNOWLEDGE_TRAINING_IP_WHITELIST` | 9000 | 127.0.0.1,::1,localhost | 是 | security | 训练接口 IP 白名单 |
| `KNOWLEDGE_TRAINING_INTERNAL_TOKENS` | 9000 | 空 | 是 | security | 训练服务间 token |
| `KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID` | 9000 | xiaogao_system | 是 | internal | 训练固定租户 |
| `KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID` | 9000 | xiaogao_base | 是 | internal | 训练固定商户 |
| `KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS` | 9000 | false | 是 | security | 是否信任 X-Forwarded-For |
| `DOUYIN_AUTO_REPLY_ENABLED` | 9000 | false | 是 | safety | 自动回复总开关 |
| `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` | 9000 | false | 是 | safety | 真实发送总开关 |
| `DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT` | 9000 | false | 是 | safety | 全量放开开关 |
| `DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST` | 9000 | 空 | 是 | safety | 允许自动回复的企业号白名单 |
| `DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST` | 9000 | 空 | 是 | safety | 允许自动回复的客户白名单 |
| `DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST` | 9000 | 空 | 是 | safety | 允许自动回复的会话白名单 |

### Local Agent 与前端

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `LOCAL_AGENT_AUTH_REQUIRED` | 9000 | false | 是 | security | 强制 Local Agent token 校验 |
| `LOCAL_AGENT_TOKENS` | 9000 | 空 | 是 | security | merchant_id:token 列表 |
| `LOCAL_AGENT_HOST` | 19000 | 127.0.0.1 | dev/lan | local-agent | Agent 监听地址（prod 不入模板） |
| `LOCAL_AGENT_PORT` | 19000 | 19000 | dev/lan | local-agent | Agent 监听端口（prod 不入模板） |
| `AUTO_WECHAT_SERVER_URL` | 19000 | 空 | dev/lan | local-agent | Agent 拉任务/回写主系统地址（prod 不入模板） |
| `LOCAL_AGENT_LOG_FILE` | 19000 | logs/local_agent.log | dev/lan | local-agent | Agent 日志路径（prod 不入模板） |
| `AUTO_WECHAT_AGENT_CLIENT_ID` | 19000 | local-agent-default | dev/lan | local-agent | Agent 客户端 ID（prod 不入模板） |
| `AUTO_WECHAT_AGENT_NAME` | 19000 | 小高AI微信助手 | dev/lan | local-agent | Agent 展示名（prod 不入模板） |
| `LOCAL_AGENT_TASK_POLL_INTERVAL_SECONDS` | 19000 | 5.0 | dev/lan | local-agent | 任务轮询间隔（prod 不入模板） |
| `VITE_API_BASE_URL` | FE | /api | 是 | frontend | 浏览器访问 9000 的基础路径 |
| `VITE_AUTO_WECHAT_API_BASE_URL` | FE | /api | 是 | frontend | 浏览器访问 9000 的 API 地址 |
| `VITE_DOUYIN_AI_CS_API_BASE_URL` | FE | /ai-cs-api | 是 | frontend | 浏览器访问 9100 的地址 |
| `VITE_NEWCAR_AUTH_BASE_URL` | FE | 空 | 是 | frontend | 浏览器直连 NewCar 换 token |
| `VITE_NEWCAR_LOGIN_URL` | FE | 空 | 是 | frontend | 前端登录失效跳转 |
| `VITE_LOCAL_WECHAT_AGENT_BASE_URL` | FE | 空 | 是 | frontend | 浏览器所在电脑本机 Agent 地址（默认 http://127.0.0.1:19000）。前端按三层优先级真实读取：`localStorage.local_wechat_agent_url`（页面手动设置，最高）> `VITE_LOCAL_WECHAT_AGENT_BASE_URL`（Vite 构建）> 硬编码 127.0.0.1:19000（兜底）。该地址指向销售电脑而非宝塔服务器 |
| `VITE_DEV_API_PROXY_TARGET` | FE | 空 | 是 | frontend | vite dev proxy 目标 9000 |
| `VITE_DEV_DOUYIN_AI_CS_PROXY_TARGET` | FE | 空 | 是 | frontend | vite dev proxy 目标 9100 |

### 9100 LLM / Embedding / 其他开关

| 变量 | 服务 | 默认值 | 模板 | 类别 | 用途 |
|---|---|---|---|---|---|
| `XG_DOUYIN_AI_LLM_BASE_URL` | 9100 | api.openai.com/v1 | 是 | llm | LLM 兼容接口地址 |
| `XG_DOUYIN_AI_LLM_API_KEY` | 9100 | 空 | 是 | llm | LLM API key |
| `XG_DOUYIN_AI_LLM_CHAT_MODEL` | 9100 | gpt-4o-mini | 是 | llm | 对话模型名 |
| `XG_DOUYIN_AI_LLM_TIMEOUT_SECONDS` | 9100 | 20 | 是 | llm | LLM 请求超时 |
| `XG_DOUYIN_AI_LLM_TEMPERATURE` | 9100 | 0.2 | 是 | llm | 采样温度 |
| `XG_DOUYIN_AI_EMBEDDING_ENABLED` | 9100 | false | 是 | embedding | embedding 总开关 |
| `XG_DOUYIN_AI_EMBEDDING_PROVIDER` | 9100 | ark | 是 | embedding | embedding 提供方 |
| `XG_DOUYIN_AI_EMBEDDING_API_KEY` | 9100 | 空 | 是 | embedding | embedding API key |
| `XG_DOUYIN_AI_EMBEDDING_BASE_URL` | 9100 | ark.cn-beijing.volces.com/api/v3 | 是 | embedding | embedding 服务地址 |
| `XG_DOUYIN_AI_EMBEDDING_ENDPOINT` | 9100 | /embeddings/multimodal | 是 | embedding | embedding 端点路径 |
| `XG_DOUYIN_AI_EMBEDDING_MODEL` | 9100 | doubao-embedding-vision-250615 | 是 | embedding | embedding 模型名 |
| `XG_DOUYIN_AI_EMBEDDING_DIMENSIONS` | 9100 | 空 | 是 | embedding | 向量维度（须与向量库一致） |
| `XG_DOUYIN_AI_EMBEDDING_ENCODING_FORMAT` | 9100 | float | 是 | embedding | 编码格式 |
| `XG_DOUYIN_AI_EMBEDDING_SPARSE_ENABLED` | 9100 | false | 是 | embedding | 稀疏向量开关 |
| `XG_DOUYIN_AI_EMBEDDING_TIMEOUT_SECONDS` | 9100 | 120 | 是 | embedding | embedding 请求超时 |
| `XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED` | 9100 | false | 是 | llm | Agent runtime 预留开关 |
| `LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED` | 9000 | false | 是 | safety | 旧微信调试接口开关 |
| `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT` | 9000 | 0 | 是 | safety | 旧自动检测调度器开关 |
| `CORS_ORIGINS` | 9000 | 6 个默认来源 | 是 | security | 跨域来源白名单 |

### 抖音客服工作台（DOUYIN_WORKBENCH_*）

P3-CONFIG-ENV-VARIABLE-COVERAGE-FIX-1 后从「高级调优」升级为模板部署变量，三个 example 均收录。

| 变量 | 服务 | 默认值 | 模板 | 用途 |
|---|---|---|---|---|
| `DOUYIN_WORKBENCH_CONVERSATION_EVENT_LIMIT` | 9000 | 2000 | 是 | 会话列表首次事件窗口；可按需扩至 20000 |
| `DOUYIN_WORKBENCH_CONVERSATION_LOOKBACK_DAYS` | 9000 | 7 | 是 | 账号未读统计回看天数，不限制会话列表日期 |
| `DOUYIN_WORKBENCH_MESSAGE_LIMIT` | 9000 | 200 | 是 | 工作台消息上限 |
| `DOUYIN_WORKBENCH_UNREAD_EVENT_LIMIT` | 9000 | 5000 | 是 | 未读事件上限 |

读取点：`app/services/douyin_workbench_conversation_service.py:43-46`（`os.getenv` + `max()` 下限保护）。

### 向量后端（外部 Milvus，production/LAN 必填）

P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1：production 固定使用外部 Milvus（不由 Compose 部署），LAN 联调同样使用外部 Milvus（独立 collection）；dev 默认 SQLite 向量副本便于单机轻量开发。production 不得回退 SQLite 向量后端。

| 变量 | 服务 | 默认值 | prod/LAN 模板 | 用途 |
|---|---|---|---|---|
| `MILVUS_URI` | 9100 | 空 | 是（占位符） | 外部 Milvus 连接地址（`http://host:19530`） |
| `MILVUS_USERNAME` | 9100 | 空 | 是（占位符） | Milvus 用户名 |
| `MILVUS_PASSWORD` | 9100 | 空 | 是（占位符） | Milvus 密码 |
| `MILVUS_DB_NAME` | 9100 | 空 | 是（占位符） | Milvus database 名 |
| `MILVUS_COLLECTION` | 9100 | 空 | 是（占位符） | Milvus collection 名（prod 不得与 dev/LAN 共用） |
| `MILVUS_DIMENSION` | 9100 | 空 | 是（2048） | 向量维度，必须与 `XG_DOUYIN_AI_EMBEDDING_DIMENSIONS` 和 collection 实际维度一致 |
| `MILVUS_TIMEOUT_SECONDS` | 9100 | 5 | 是 | Milvus 请求超时 |
| `MILVUS_INDEX_TYPE` | 9100 | AUTOINDEX | 是 | 索引类型 |
| `MILVUS_METRIC_TYPE` | 9100 | COSINE | 是 | 度量类型 |
| `MILVUS_CONNECT_STRATEGY` | 9100 | orm | 是 | 连接策略 |

读取点：`apps/xg_douyin_ai_cs/config.py:74-129`、`apps/xg_douyin_ai_cs/llm/client.py:162-163`。

**dimension 一致性三层校验**（`run_milvus_readiness`）：
1. `XG_DOUYIN_AI_EMBEDDING_DIMENSIONS` 必须存在（backend=milvus 时）
2. `MILVUS_DIMENSION` 必须存在
3. 两者必须相等，且等于 collection 实际维度（`_validate_collection_schema` 比对）
不一致 → `MILVUS_DIMENSION_MISMATCH`，启动/readiness 失败，不静默修正、不回退 SQLite。

---

## 2. 高级调优变量（不进入模板）

无。`DOUYIN_WORKBENCH_*` 已在 P3-CONFIG-ENV-VARIABLE-COVERAGE-FIX-1 升级为模板部署变量，见第 1 节「抖音客服工作台」。

---

## 3. 可选组件变量（不进入模板）

无。`MILVUS_*` 已在 P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1 升级为 production/LAN 必填模板变量，见第 1 节「向量后端（外部 Milvus）」。

---

## 4. 历史兼容变量（不进入模板）

| 变量 | 服务 | 默认值 | 状态 | 用途 |
|---|---|---|---|---|
| `XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED` | 9100 | true | 兼容回退 | 旧 embedding 开关，新 `XG_DOUYIN_AI_EMBEDDING_ENABLED` 未设置时回退读取 |
| `XG_DOUYIN_AI_LLM_EMBEDDING_MODEL` | 9100 | text-embedding-3-small | 兼容 | 旧 embedding 模型名（`llm/config.py`） |
| `XG_DOUYIN_AI_CS_DB_PATH` | 9100 | 空 | 兼容 | 旧 SQLite 路径，`RAG_DATABASE_URL` 优先 |
| `DY_BASE_URL` | 9000 | 空 | 兼容 | 旧完整 base url 降级变量 |
| `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | compose | 空 | 可选 profile | `docker-compose.dev.yml` 的 `profiles:[postgres]` 专用，默认不启动 |

新部署**不得**使用兼容变量作为主配置。

---

## 5. 灰度变量（不进入模板）

以下 `LEADS_TASKS_PG_*` 由 `app/config.py` 读取，对应 leads/tasks PostgreSQL read-only shadow 灰度（P3-D13）。默认全关闭，未审批不得开启。详见 `docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_GRAY_PRESET_RUNBOOK.md`。

| 变量 | 默认值 | 用途 |
|---|---|---|
| `LEADS_TASKS_PG_PILOT_ENABLED` | false | 试点总开关 |
| `LEADS_TASKS_PG_READ_SHADOW_ENABLED` | false | 只读 shadow 开关 |
| `LEADS_TASKS_PG_WRITE_ENABLED` | false | PG write 开关 |
| `LEADS_TASKS_PG_STRICT_CONTRAST` | false | 严格对比开关 |
| `LEADS_TASKS_PG_DATABASE_URL` | 空 | shadow PG 连接 URL |
| `LEADS_TASKS_PG_POOL_SIZE` | 5 | shadow 连接池大小 |
| `LEADS_TASKS_PG_MAX_OVERFLOW` | 5 | shadow 溢出 |
| `LEADS_TASKS_PG_POOL_TIMEOUT` | 3 | shadow 获取超时 |
| `LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS` | 1500 | shadow 语句超时 |
| `LEADS_TASKS_PG_SHADOW_TIMEOUT_MS` | 800 | shadow 查询超时 |
| `LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY` | 10 | shadow 最大并发 |
| `LEADS_TASKS_PG_SHADOW_SAMPLE_RATE` | 1.0 | shadow 采样率 |
| `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | false | 知识分类 async PG 试点 |

---

## 6. 数据库连接池 backend 边界与调用链

**三组连接池变量分别控制不同 backend 的 engine，均实际生效，无一是预留或废弃：**

```text
DB_POOL_*：
9000 PostgreSQL 同步 engine 实际配置（app/database.py:192-200 PG 分支 + :247 statement_timeout）。

SQLALCHEMY_*：
9000 SQLite engine 实际配置（app/database.py:205-215 SQLite 分支），仅 dev/lan。

RAG_DB_POOL_*：
9100 RAG metadata PostgreSQL engine 实际配置（apps/xg_douyin_ai_cs/rag/database.py:80-96）。
```

### 真实调用链

```text
.env.production.local（DB_POOL_*）
→ app/config.py 读取
→ app/database.py create_database_engine() PostgreSQL 分支（line 192-200）
→ SQLAlchemy create_engine(postgresql+psycopg://, pool_size=DB_POOL_SIZE, ...)
→ 9000 PostgreSQL engine
```

```text
.env.development.local / .env.lan.local（SQLALCHEMY_*）
→ app/database.py create_database_engine() SQLite 分支（line 205-215）
→ SQLAlchemy create_engine(sqlite:///, pool_size=SQLALCHEMY_POOL_SIZE, ...)
→ 9000 SQLite engine
```

```text
.env.production.local（RAG_DB_POOL_*）
→ apps/xg_douyin_ai_cs/config.py settings.rag_db_*
→ apps/xg_douyin_ai_cs/rag/database.py create_rag_engine() PG 分支（line 80-96）
→ 9100 RAG PostgreSQL engine
```

### backend 互斥说明

dev/lan 当前用 SQLite，模板只配 `SQLALCHEMY_*`；production 用 PostgreSQL，模板只配 `DB_POOL_*` / `RAG_DB_POOL_*`。同一 profile 不同时展示两套互斥连接池配置。若未来 dev/lan 切到 PostgreSQL，需改用 `DB_POOL_*`，届时单独评估，当前不要混配。

### 防止局部 grep 误判（重要）

判断一个环境变量是否生效，必须追踪到**实际 backend 分支和 engine 创建调用**，不能只根据单个 grep 命中或局部代码片段下结论。同一个 factory（如 `create_database_engine`）可能对 PostgreSQL、SQLite、async 路径使用完全不同的变量集合。

> 本文档早期版本曾因只 grep 到 SQLite 分支的 `SQLALCHEMY_*`（line 211-214）就误判 `DB_POOL_*` 不生效，导致生产模板错配。修正依据是完整阅读 `create_database_engine` 的 PG 分支（line 192-200）和 9100 `create_rag_engine`（line 80-96）。现已通过分类覆盖测试 `test_connection_pool_profile_boundary` 约束，防止再次错配。

### 总连接数评估

`DB_POOL_*` 与 `RAG_DB_POOL_*` 的 `pool_size + max_overflow` 是单个服务进程的潜在连接数上限。生产部署须结合 PostgreSQL `max_connections`、9000/9100 进程数和 uvicorn worker 数评估总连接，避免耗尽 PG 连接。`pool_recycle` 单位为秒，`statement_timeout` 单位为毫秒，单位以代码实现为准。

---

## 7. 测试 / 工具专用变量（不进入模板）

| 变量 | 出现位置 | 用途 |
|---|---|---|
| `AUTO_WECHAT_ENV_FILE` | `app/config.py` | 显式指定 env 文件路径（调试/测试） |
| `AUTO_WECHAT_ENV_PROFILE` | `app/config.py` | 显式指定 profile（调试/测试） |
| `EASYOCR_MODULE_PATH` | `app/wechat_ui/ocr_runtime.py` | OCR 模型本地路径（打包/本地） |

---

## 维护规则

1. 新增 `os.getenv` / `os.environ.get` 读取的变量后，必须在本文档登记分类。
2. `tests/test_env_profile_templates.py` 会扫描代码读取点，未分类变量会导致测试失败。
3. 模板只收录第 1 节「模板部署变量」中标记「是」的变量，且须遵守 profile 边界（prod 不含 Local Agent 进程变量、不含 SQLite 主库 URL、不含真实密钥）。
4. 历史兼容 / 灰度 / 废弃变量**永远不重新进入模板**。
