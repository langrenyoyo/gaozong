# P1-CAR-PROJECT-KNOWLEDGE-TRAIN-QDRANT-AUDIT

## 1. 目标与边界

本轮只读审计 `E:\work\project\car-porject-main` 中 Qdrant、direct_9100、向量库状态展示、collection 展示、训练 API 调用点，为下一步把 `car-porject-main` 统一改为调用 auto_wechat 9000 `/knowledge-training/*` 做准备。

边界：

- 不修改 `car-porject-main`。
- 不修改 auto_wechat 业务代码。
- 不触发训练。
- 不调用 auto_wechat 9000。
- 不调用 9100。
- 不连接 Milvus / Qdrant。
- 不调用 LLM。
- 不调用抖音发送上游。
- 不新增 `/merchant/rag/*`。
- 不把 `/admin/rag/*` 作为当前主路径。

正确目标方向：

```text
car-porject-main 前端
-> car-porject-main 后端
-> auto_wechat 9000 /knowledge-training/*
-> auto_wechat 9100
-> Milvus
```

## 2. 项目状态

auto_wechat：

- `git status --short`：空输出，工作区干净。
- 9000 `/knowledge-training/*` 已具备 internal token gate。
- 9000 -> 9100 -> Milvus synthetic 闭环已在前序任务验证通过。

car-porject-main：

- `git status --short`：空输出，工作区干净。
- 是 git repo，不是 `fatal: not a git repository`。
- 后端入口集中在 `backend/app.py`。
- 前端为静态单页，入口为 `frontend/index.html`，主要逻辑集中在 `frontend/assets/app.js`。
- 当前知识库 / RAG 旧链路仍以 Qdrant 为核心。

## 3. Qdrant / vector / direct_9100 命中清单

按运行相关文件扫描：`backend`、`frontend/assets/app.js`、`frontend/assets/app.css`、`tools`、`docker-compose.yml`、`README.md`。

| 关键词 | 命中次数 | 主要文件 | 类型 | 摘要 | 后续建议 |
|---|---:|---|---|---|---|
| qdrant | 203 | `backend/app.py`、`backend/rag_qdrant.py`、`frontend/assets/app.js`、`docker-compose.yml`、`tools/*rag*`、`README.md` | 后端 / 前端 / 配置 / 脚本 / 文档 | 后端直接创建 Qdrant client、upsert、retrieve、scroll、search；前端展示 Qdrant 状态；docker 启动 Qdrant。 | 后端调用路径替换为 9000；前端隐藏；配置和脚本删除或降级为历史说明。 |
| direct_9100 | 7 | `backend/app.py`、`README.md` | 后端 / 文档 | `douyin_cs_training` 默认 `direct_9100`，可切 `gateway_9000`。 | 默认改为调用 auto_wechat 9000；停用 direct_9100。 |
| gateway_9000 | 3 | `backend/app.py`、`README.md` | 后端 / 文档 | 已有网关模式雏形，但鉴权仍是旧配置形态。 | 复用思路，但改为 `/knowledge-training/*` internal token gate。 |
| 9100 | 35 | `backend/app.py`、`tools/start-gaozong-local.*`、`README.md` | 后端 / 脚本 / 文档 | 本地联调会启动或直连 9100。 | 后续 car-porject-main 不直连 9100。 |
| collection | 78 | `backend/rag_qdrant.py`、`backend/app.py`、`frontend/assets/app.js`、`README.md` | 后端 / 前端 / 文档 | Qdrant collection 名称、状态、点数均参与响应和展示。 | 页面不得展示底层 collection；后端不再关心向量库 collection。 |
| vector | 57 | `backend/rag_qdrant.py`、`backend/ai_config.example.json`、`docker-compose.yml` | 后端 / 配置 | 本地 embedding 向量、维度、Qdrant vector size。 | 交给 auto_wechat 9100 / Milvus 处理。 |
| embedding | 91 | `backend/rag_qdrant.py`、`backend/app.py`、`backend/ai_config.example.json` | 后端 / 配置 | 支持 local / openai / ark embedding。 | 从 car-porject-main 删除训练侧 embedding 能力。 |
| knowledge-base | 4 | `backend/app.py`、`frontend/assets/app.js` | 后端 / 前端 | 当前知识库页面接口。 | 保留页面交互骨架，后端适配到 9000 `/knowledge-training/*`。 |
| douyin-cs-training | 5 | `backend/app.py`、`frontend/assets/app.js` | 后端 / 前端 | 抖音客服训练问答 / 反馈代理接口。 | 可作为历史代理参考，不作为统一知识库主接口。 |

敏感配置风险：

- `backend/ai_config.example.json` 中存在形似真实密钥的示例值。本审计文档不记录该值。下一轮建议将示例值替换为空字符串或占位符。

## 4. 配置审计

### Qdrant 配置项

`.env` 中存在以下配置名，本轮未读取真实值：

- `AI_DIRECTOR_RAG_ENABLED`
- `AI_DIRECTOR_RAG_EMBEDDING_PROVIDER`
- `AI_DIRECTOR_STATUS_QDRANT_TIMEOUT`
- `AI_DIRECTOR_TRACE_ENABLED`
- `OPERATION_PLAN_RAG_COLLECTION`
- `QDRANT_COLLECTION`
- `QDRANT_URL`

`docker-compose.yml` 中存在：

- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `OPERATION_PLAN_RAG_COLLECTION`
- `AI_DIRECTOR_RAG_EMBEDDING_PROVIDER`
- `AI_DIRECTOR_RAG_TOP_K`
- `AI_DIRECTOR_RAG_MIN_SCORE`
- `AI_DIRECTOR_STATUS_QDRANT_TIMEOUT`
- `qdrant` service

`tools/start-backend-rag.*`、`tools/start-local-dev-rag.cmd` 中存在：

- 启动 Qdrant 的本地脚本。
- 设置 `QDRANT_URL` 和多个 `*_RAG_COLLECTION`。
- 设置 embedding provider。

### direct_9100 配置项

`backend/app.py` 的 `douyin_cs_training_settings()` 读取：

- `mode`，默认 `direct_9100`。
- `gateway_base_url`，默认指向 9000。
- `service_base_url`，默认指向 9100。
- `service_token`。
- `gateway_auth_type` / `gateway_auth_value` / `gateway_cookie_name`。
- `fixed_tenant_id` / `fixed_merchant_id` / `default_douyin_account_id`。

`README.md` 明确写到本地默认直连 9100。

### auto_wechat base URL / internal token

当前未发现专门面向 auto_wechat 9000 `/knowledge-training/*` 的配置名。建议下一轮新增：

- `AUTO_WECHAT_KNOWLEDGE_TRAINING_BASE_URL`
- `AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN`
- `AUTO_WECHAT_KNOWLEDGE_TRAINING_OPERATOR_SOURCE=car-project-main`

要求：

- internal token 只存在 car-porject-main 后端环境。
- 前端不得接触 internal token。
- 不向前端返回 token、9000 内部错误、9100 内部错误、Milvus / Qdrant 细节。

## 5. 后端 API 审计

### 后端框架和入口

- 后端入口：`backend/app.py`。
- 使用 Python 标准库 HTTP server 风格路由分发，不是 FastAPI / Flask。
- 静态前端和 API 由同一服务承载。

### 当前知识库相关路由

| 当前接口 | 方法 | 位置 | 当前行为 | 后续建议 |
|---|---|---|---|---|
| `/api/knowledge-base` | GET | `backend/app.py` | 查询本地 SQLite 知识表，同时连接 Qdrant 获取 collection info、points_count、payload，并返回 `qdrant` 字段。 | 替换为代理 auto_wechat 9000 `GET /knowledge-training/documents`；返回训练端需要的业务字段，不返回 Qdrant。 |
| `/api/knowledge-base/requeue` | POST | `backend/app.py` | 对 failed / skipped 知识重新入 Qdrant，可 force。 | 替换为 9000 训练 / 重训接口，或删除“重新入库 / 强制入库”底层语义。 |
| `/api/douyin-cs-training/ask` | POST | `backend/app.py` | 调用外部 `/knowledge-training/ask`，默认 direct_9100，可配置 gateway_9000。 | 不作为统一知识库训练主路径；如保留，应统一走 9000。 |
| `/api/douyin-cs-training/feedback` | POST | `backend/app.py` | 调用外部 `/knowledge-training/{training_id}/feedback`。 | 不作为统一知识库训练主路径；如保留，应统一走 9000。 |

### 当前 Qdrant 直接调用点

`backend/rag_qdrant.py`：

- `RagQdrantConfig.from_env_and_ai()`：读取 Qdrant / embedding 配置。
- `QdrantRagClient.collection_info()`：读取 collection 状态。
- `QdrantRagClient.ensure_collection()`：不存在时创建 collection。
- `QdrantRagClient.upsert()`：写入向量点。
- `QdrantRagClient.retrieve()`：按点位读取 payload。
- `QdrantRagClient.scroll()`：滚动读取点位。
- `QdrantRagClient.search()`：向量检索。

`backend/app.py`：

- `director_rag_client()`、`operation_plan_rag_client()`、`account_position_rag_client()`、`benchmark_account_rag_client()` 创建 Qdrant client。
- `knowledge_qdrant_upsert()` 写 Qdrant。
- `shared_knowledge_items_from_qdrant()` 从 Qdrant 读取共享知识。
- `index_*_knowledge()` 将各模块知识入 Qdrant。
- `sync_*_knowledge_feedback_to_qdrant()` 将反馈同步到 Qdrant。
- `requeue_*_knowledge()` 重新排队入库。
- 多个 RAG search 函数将 Qdrant 召回结果注入 AI 上下文。

### 是否保存文档

当前项目保存的是训练端本地 SQLite 业务知识表，不是统一知识库文档模型：

- `ai_director_knowledge`
- `operation_plan_knowledge`
- `account_position_knowledge`
- `benchmark_account_knowledge`
- `douyin_cs_training_feedbacks`

下一轮如果接入 auto_wechat 9000，应避免继续把“统一知识库文档”同时拆成本地旧表 + 9000 文档两套权威来源。

## 6. 前端页面审计

### 页面路由 / 菜单入口

`frontend/assets/app.js`：

- `KNOWLEDGE_TRAIN_MODULES` 定义训练端导航：
  - `ai_director`
  - `douyin_cs_training`
  - `account_positioning`
  - `benchmark_account`
  - `full_plan`
  - `knowledge`
- `knowledgeTrainNav()` 渲染训练模块导航。
- `mountKnowledgeTrainShell()` 挂载训练端页面。

### API client

`frontend/assets/app.js`：

- `api(path, options)` 使用当前站点相对路径。
- 本地静态页面场景会 fallback 到 `http://127.0.0.1:8788`。
- 前端目前不直连 9000 / 9100 / Qdrant，但会调用 car-porject-main 后端 `/api/knowledge-base` 和 `/api/douyin-cs-training/*`。

### 知识库页面

`frontend/assets/app.js`：

- `loadKnowledgeBase()` 调用 `/api/knowledge-base`。
- `knowledgeBaseMarkup()` 展示：
  - SQLite 记录数量。
  - 已进入知识库。
  - Qdrant 点数。
  - Qdrant 错误。
  - 知识模块筛选。
  - 商户筛选。
  - 状态筛选。
  - 关键词 / 标签。
- `knowledgeCard()` 展示：
  - `qdrant_present` 时显示“Qdrant 已命中”。
  - `point_id` 虽未直接展示，但后端响应中存在。
  - failed / skipped 时显示“重新入库 / 强制入库”。
- `requeueKnowledgeItem()` 调用 `/api/knowledge-base/requeue`。

### AI 链路展示

`renderDirectorTracePanel()` 展示：

- provider 文案 `Qdrant`。
- 知识状态中拼接“Qdrant 已命中”。
- Qdrant 正常 / 未连接 / RAG 未启用。
- Qdrant 点数。
- Qdrant 错误。

设置页存在：

- “AI 链路展示”说明中写到 Qdrant 入库。

### 抖音客服训练页面

`renderDouyinTrainingWorkspace()` 和相关绑定函数：

- 前端调用 `/api/douyin-cs-training/ask`。
- 前端调用 `/api/douyin-cs-training/feedback`。
- 页面文案说明“固定外部商户身份调用小高知识库训练接口，默认 merchant_id=1”。

后续需要改为：

- 不向页面暴露可信 tenant_id / merchant_id。
- operator / actor 信息由 car-porject-main 后端基于当前管理员上下文生成，仅用于审计。
- 统一知识库上下文由 auto_wechat 9000 固定或受控决定。

## 7. 当前数据流

### Qdrant 自学习链路

```text
car-porject-main 前端
-> /api/knowledge-base 或各训练模块保存反馈
-> car-porject-main backend/app.py
-> 本地 SQLite 旧知识表
-> backend/rag_qdrant.py
-> Qdrant collection
```

### 抖音客服训练链路

```text
car-porject-main 前端
-> POST /api/douyin-cs-training/ask
-> car-porject-main backend/app.py
-> direct_9100: 9100 /knowledge-training/ask
   或 gateway_9000: 9000 /knowledge-training/ask
-> car-porject-main 本地聊天记录 / 反馈表
```

当前问题：

- 默认 direct_9100 会绕过 auto_wechat 9000 gate。
- Qdrant 是 car-porject-main 的直接依赖。
- 页面展示 Qdrant 状态、点数、异常。
- 后端响应包含 Qdrant URL / collection 等底层字段。

## 8. 目标数据流

```text
car-porject-main 前端
-> car-porject-main 后端
-> auto_wechat 9000 /knowledge-training/*
-> auto_wechat 9100
-> Milvus
```

目标约束：

- car-porject-main 前端不直接调用 auto_wechat 9000。
- car-porject-main 后端调用 auto_wechat 9000。
- car-porject-main 不直连 9100。
- car-porject-main 不直连 Milvus。
- car-porject-main 不再使用 Qdrant。
- actor 信息只用于审计。
- internal token 只在后端配置，不能进入前端、日志、响应。
- 前端不展示 Milvus / Qdrant / collection / vector_id / point_id。

## 9. 可复用与不可复用清单

### 可复用

- 训练端单页导航结构。
- 知识库列表布局。
- 文档 / 知识条目卡片布局。
- 筛选、搜索、空状态、错误提示外壳。
- 训练按钮和状态展示交互。
- 抖音客服训练问答 / 反馈的聊天式交互框架。
- `api()` 当前站点相对路径调用模式。

### 必须删除 / 替换 / 隐藏

- Qdrant 状态卡片。
- Qdrant 点数。
- Qdrant 错误明细。
- collection 名称。
- `qdrant_present` 展示。
- `point_id` / vector 相关字段。
- “重新入库 / 强制入库”这类底层向量库动作。
- direct_9100 默认模式。
- 前端文案中的固定外部 merchant_id。
- Qdrant / embedding / collection 配置展示。

### 待确认

- 旧四个模块自学习知识表是否继续保留为训练端历史数据。
- 旧 AI 编导 / 全案策划 / 账号定位 / 对标账号训练是否与“统一知识库训练”合并，还是作为独立产品能力继续存在。
- 旧 `douyin_cs_training` 问答反馈是否并入统一知识库文档训练，还是保留为独立训练工具。

## 10. 当前接口到 auto_wechat 9000 的映射草案

| 当前 car-porject-main 接口 | 当前用途 | 未来 auto_wechat 9000 接口 | 建议 |
|---|---|---|---|
| `GET /api/knowledge-base` | 展示旧知识库和 Qdrant 状态 | `GET /knowledge-training/documents` | 后端适配字段；页面隐藏 Qdrant。 |
| `POST /api/knowledge-base/requeue` | 重新入 Qdrant / 强制入库 | `POST /knowledge-training/documents/{document_id}/train` | 改成“训练 / 重训”，不再叫入库。 |
| 无当前等价接口 | 创建统一知识库文档 | `POST /knowledge-training/documents` | 新增 car-porject-main 后端代理接口。 |
| 无当前等价接口 | 查看训练 run | `GET /knowledge-training/training-runs/{run_id}` | 新增后端代理接口或嵌入训练状态轮询。 |
| 无当前等价接口 | 删除统一知识库文档 | `DELETE /knowledge-training/documents/{document_id}` | 新增后端代理接口，必须提示影响统一知识库。 |
| 无当前等价接口 | 检索预览 | `POST /knowledge-training/search-preview` | 新增后端代理接口；只做检索预览，不做 LLM 问答。 |
| `POST /api/douyin-cs-training/ask` | 训练问答 | 非统一知识库主路径 | 如保留，统一走 9000，不再 direct_9100。 |
| `POST /api/douyin-cs-training/feedback` | 训练反馈 | 非统一知识库主路径 | 如保留，统一走 9000，不再 direct_9100。 |
| 当前 Qdrant status | 底层状态展示 | 删除或替换为训练服务健康状态 | 不展示 collection / vector。 |

## 11. 风险清单

1. Qdrant client 遗留导致训练仍写旧库。
2. Qdrant status / collection / points_count 泄露底层信息。
3. direct_9100 绕过 9000 gate。
4. internal token 如果放进前端，会导致知识训练接口被绕过调用。
5. 前端传 tenant_id / merchant_id 被误信任，导致统一知识库上下文错乱。
6. car-porject-main 后端错误透出 auto_wechat、9100、Milvus、Qdrant 内部异常。
7. 训练按钮可能触发多次重复训练。
8. 删除文档后旧向量残留。
9. search-preview 被误做成 LLM 问答，扩大能力边界。
10. 页面错误提示暴露 Milvus / 9100 / token / 内部路径细节。
11. 没有 request_id 导致跨 8788 -> 9000 -> 9100 排查困难。
12. 没有 actor 审计导致管理员操作不可追踪。
13. 示例配置文件存在形似真实密钥的示例值，存在误提交和复制传播风险。

## 12. 下一步 wiring 建议

建议下一任务：

```text
P1-CAR-PROJECT-KNOWLEDGE-TRAIN-AUTO-WECHAT-9000-WIRE-1
```

任务目标：

1. car-porject-main 后端新增 auto_wechat 9000 knowledge-training client。
2. 移除 / 停用 Qdrant client 调用路径。
3. 移除 direct_9100 默认路径。
4. 前端原 API 尽量不大改，由后端适配到 auto_wechat 9000。
5. internal token 仅后端使用。
6. actor headers 从当前管理员上下文生成，仅用于审计。
7. 统一错误脱敏。
8. 页面隐藏 Qdrant / collection / vector / point_id 相关展示。
9. 新增请求幂等和训练中状态保护，避免重复训练。
10. 增加 request_id，贯穿 car-porject-main、auto_wechat 9000、9100。

建议新增后端配置名：

```text
AUTO_WECHAT_KNOWLEDGE_TRAINING_BASE_URL=
AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN=
AUTO_WECHAT_KNOWLEDGE_TRAINING_OPERATOR_SOURCE=car-project-main
```

默认必须安全：

- base URL 为空时不调用。
- internal token 为空时不调用真实 9000。
- 不 fallback 到 direct_9100。
- 不 fallback 到 Qdrant。

## 13. 未改内容

- 未修改 `car-porject-main`。
- 未修改 auto_wechat 业务代码。
- 未实现 wiring。
- 未新增接口。
- 未触发训练。
- 未调用 auto_wechat 9000。
- 未调用 9100。
- 未连接 Milvus。
- 未连接 Qdrant。
- 未调用 LLM。
- 未调用抖音发送。
- 未触发私信发送。
- 未修改自动回复 gate。
- 未提交 token / cookie / secret / password / Milvus / Qdrant 凭据。
