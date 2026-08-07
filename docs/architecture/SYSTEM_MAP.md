# auto_wechat 系统现实地图

> 本文档基于代码事实（2026-08-07 探索），非旧文档推断。是治理主线 1A 系列的第一步——Index First, Move Later。
> Legacy/Compat/Unknown 只标记已知，不正式定性（定性见 1A.5）。

---

## 一、运行组件

区分三类：进程/服务（auto_wechat 自己启动）、数据基础设施、外部运行依赖。

### 进程/服务

| 组件 | 端口 | 数据库 | 职责 | 边界 |
|---|---|---|---|---|
| React 前端 | 5173 | 无 | React + TS + Vite，所有页面 | `frontend/`；vite 默认端口（无显式 server.port）；代理 `/api`→9000、`/ai-cs-api`→9100（`vite.config.ts:17-41`） |
| auto_wechat 主服务 | 9000 | `auto_wechat`（`DATABASE_URL`，`app/config.py:166`） | FastAPI 业务 API、webhook 直收、NewCar 鉴权门面、9100 可信代理、自动回复 gate、报表、回访 | 注册 40+ router（`app/main.py:125-164`）；`SERVER_PORT=9000`（`app/config.py:199`）；SQLite 默认回退 `data/auto_wechat.db` |
| 抖音AI小高客服 | 9100 | `xg_douyin_ai_cs`（`RAG_DATABASE_URL`，`apps/.../config.py:36-44`） | RAG 检索、LLM 回复、知识库 metadata、独立 FastAPI 子应用 | `apps/xg_douyin_ai_cs/main.py:89`；默认 `127.0.0.1:9100`（`constants.py:5-6`）；9 个 router；CORS 仅 5173 |
| Local Agent（小高AI微信助手.exe） | 19000 | 无独立库（只连 9000） | 微信 UI 自动化（通知/检测），运行在微信所在 Windows 电脑，不容器化 | `app/local_agent_main.py:66-67`；默认 `127.0.0.1:19000`；不监听 0.0.0.0 |

### 数据基础设施

| 组件 | 说明 |
|---|---|
| PostgreSQL | 生产唯一数据库实例，方案 A 一个实例两个 database：`auto_wechat`（9000 主库，`DATABASE_URL`）与 `xg_douyin_ai_cs`（9100 RAG 库，`RAG_DATABASE_URL`）；dev 回退 SQLite（非生产）。9000 用 SQLAlchemy ORM（`app/database.py`、`app/models.py` 54 表），9100 用原生 SQL 建表（`apps/.../rag/database.py` 7 表）。 |

### 外部运行依赖（External runtime dependencies）

非 auto_wechat 自己托管的业务服务，生产为外部依赖：

| 外部服务 | 职责 | 集成 | 配置项 |
|---|---|---|---|
| Milvus | embedding + 向量检索副本（非 metadata 真源） | 9100 通过 pymilvus 连接 | `MILVUS_URI`（`apps/.../config.py:78-79`）；**不存在 `MILVUS_HOST`/`MILVUS_PORT`**，用单一 URI |
| NewCarProject | 商户/账号/权限/菜单/套餐权威 | 9000 HTTP 代理（登录/改密/退出/切换） | `NEWCAR_AUTH_BASE_URL`（`config.py:262`，注意非 `NEWCAR_BASE_URL`） |
| 抖音 GMP | webhook 回调 + OpenAPI（签名下载/解码） | 9000 webhook 直收 + 签名调用 | `DY_GMP_SECRET_KEY`/`DY_OPENAPI_BASE_URL`（`config.py:225-226`，默认 `https://gmp.bytedanceapi.com`） |
| LAS（火山引擎） | AI 剪辑云端混剪 | 9000 组装参数→submit→轮询→存产物 | `LAS_API_KEY`/`LAS_BASE_URL`（`config.py:392-393`） |
| TOS（火山引擎对象存储） | LAS 产物预签名上传/下载 | 9000 预签名 | `TOS_ACCESS_KEY`/`TOS_SECRET_KEY`/`TOS_BUCKET`/`TOS_REGION`/`TOS_ENDPOINT`（`config.py:401-405`） |

**Milvus 说明**：生产为外部运行依赖（非 auto_wechat 自托管业务服务），仅作向量检索副本；documents/chunks/feedback/training_run 与状态字段的 metadata 真源是 `xg_douyin_ai_cs` 库。本地图第三节"外部系统"仍保留 Milvus 条目，两处标注一致。

---

## 二、7 个业务模块

| 模块 | 前端 nav id / 路由 | 前端 feature 目录 | 后端 router | 后端 service / 子应用 | 一句话职责 |
|---|---|---|---|---|---|
| AI小高智能体 | `ai-agents` `/agents` | `features/agents/` | `routers/agents.py:44` | `ai_agent_service.py`/`agent_status_service.py` | 抖音企业号绑定的 LLM 客服配置 |
| 抖音AI小高客服 | `douyin-ai-cs` `/douyin-cs/workbench` + `douyin-auto-reply-diagnostics` | `features/douyin-cs/` | `routers/douyin_ai_cs_proxy.py:40` + `douyin_autoreply_settings.py:38` | `douyin_workbench_conversation_service.py` 等 + 独立子应用 `apps/xg_douyin_ai_cs/` | 私信工作台 + RAG/LLM 回复 + AI 托管自动回复闭环 |
| AI小高线索 | `leads` `/leads` + `chat` | `features/leads/` | `routers/leads.py:20` + `routers/integrations.py:42`(webhook) | `lead_management_service.py` + `integrations/douyin_webhook.py` | 抖音私信线索 webhook 直收→入库→分配→微信通知→回复检测→回访 |
| AI小高微信助手 | `ai-agent`/`wechat-config`/`wechat-tasks`/`wechat-download-test`/`wechat-daily-reports` | `features/wechat-assistant/` | `routers/wechat_tasks.py:25` | `wechat_ui_reply_service.py`/`wechat_task_service.py` + `local_agent_main.py` | 本机微信 UI 自动化（通知/检测），小高AI微信助手.exe |
| 小高素材库 | `ai-edit-materials` `/ai-edit/materials` | `features/ai-edit/`（与剪辑共享） | `routers/ai_edit.py:25`（与剪辑共享） | `ai_edit_service.py`/`ai_edit_storage.py`/`material_analysis.py` | AI 剪辑素材管理与分析 |
| AI小高剪辑 | `ai-edit-editor` `/ai-edit/editor` | `features/ai-edit/`（与素材库共享） | `routers/ai_edit.py`（与素材库共享） | `ai_edit_las_service.py`/`las_client.py`/`las_tos_uploader.py` | LAS 云端混剪（火山 `las_video_remix` `speech_auto`） |
| AI小高算力 | `compute`/`compute-token-transactions`/`compute-recharge-orders` | `features/compute/` | `routers/compute.py:99` | `compute_service.py`（兼容入口，实现收敛到 `apps/compute/services/`） | 商户算力套餐/消耗/计费展示 |

**注意**：素材库与剪辑共用 router 和 feature 目录，靠 nav id 区分；算力 service 是兼容入口，实现已迁移到 `apps/compute/services/`。

---

## 三、公共能力

### 平台公共底座（跨所有业务模块的基础设施）

| 能力 | 代码位置 | 说明 |
|---|---|---|
| auth / RBAC | `app/auth/`（context/dependencies/newcar_client/local_agent_auth/external_merchant_binding_service） + `routers/auth.py` | NewCar 外部鉴权门面；`auth.py` 无前缀和 `/api` 双挂载 |
| 数据库底座 | `app/database.py` | engine/SessionLocal/Base/get_db；SQLite WAL/PG statement_timeout |
| 发送 gate | `app/services/douyin_autoreply_gate_service.py` | 自动回复闸门（限频/违禁词/人工接管/幂等/紧急停止） |
| outbox | `app/services/ai_auto_reply_outbox_service.py` | 发件箱持久化任务调度（claim/lease/恢复）；`main.py:228-229` 启动 |
| 调度器 | `app/scheduler/*` + `main.py` lifespan | check_scheduler / wechat_auto_detect_scheduler / daily_report_scheduler / return_visit_silent_scan_scheduler / outbox / contact_invalid_followup |
| 商户隔离 | `app/services/douyin_merchant_isolation.py` | 账号归属校验、可信商户过滤 |

### 领域共享能力（客户/线索领域共享，非平台基础设施）

| 能力 | 代码位置 | 说明 |
|---|---|---|
| 联系方式提取 | `app/services/contact_extractor.py` + `contact_state_service.py` + `customer_profile_service.py` + `contact_completion_resolver.py` + `contact_validity_analyzer.py` + `contact_invalid_followup_service.py` + `douyin_customer_profile_deriver.py` | 线索识别引擎（清洗/号段/置信度/状态机/空号追问）；属客户/线索领域共享，不是平台级基础设施 |

---

## 四、外部系统

| 外部服务 | 集成方式 | 配置项 |
|---|---|---|
| 抖音 GMP | webhook 回调（9000 直收）+ OpenAPI 签名调用 | `DY_SECRET_KEY`/`DY_GMP_SECRET_KEY`（`config.py:224-225`）、`DY_OPENAPI_BASE_URL`（默认 `https://gmp.bytedanceapi.com`，`config.py:226`） |
| Milvus | 9100 通过 pymilvus 连接 | `MILVUS_URI`/`MILVUS_USERNAME`/`MILVUS_PASSWORD`/`MILVUS_COLLECTION`/`MILVUS_DIMENSION=2048`（9100 侧 `apps/.../config.py`） |
| NewCarProject | 9000 HTTP 代理（登录/改密/退出/切换） | `NEWCAR_AUTH_ENABLED`（默认 False）/`NEWCAR_AUTH_MOCK_ENABLED`（默认 True）/`NEWCAR_AUTH_BASE_URL`（`config.py:260-262`） |
| LAS（火山引擎） | 9000 组装参数→submit→轮询→存产物 | `LAS_API_KEY`/`LAS_BASE_URL`（默认 `https://operator.las.cn-beijing.volces.com`，`config.py:392-393`） |
| TOS（火山引擎对象存储） | LAS 产物预签名上传/下载 | `TOS_ACCESS_KEY`/`TOS_SECRET_KEY`/`TOS_BUCKET`/`TOS_REGION`/`TOS_ENDPOINT`（`config.py:401-405`） |
| douyinAPI（8081） | **demo/参考实现**，非生产依赖 | `DOUYIN_API_BASE_URL`（默认 `http://127.0.0.1:8081`，`config.py:217`，仍硬编码默认值） |

---

## 五、一级数据域

### auto_wechat 库（`app/models.py`，54 表）

| 域 | 表数 | 主要表 |
|---|---|---|
| webhook_events | 1 | DouyinWebhookEvent |
| leads | 9 | DouyinLead/LeadFollowupRecord/ReplyCheck/CheckConfig/FeedbackRecord/LeadNotification/LeadReportAttribution/SalesLeadFeedback/SalesLeadUpdate |
| agents | 4 | AiAgent/AgentKnowledgeCategory/KnowledgeCategory/DouyinAccountAgentBinding |
| ai_auto_reply | 11 | AiAutoReplyRun/AiReplyDecisionLog/DouyinPrivateMessageSend/DouyinAccountAutoreplySetting/AutoReplyRolloutConfig/AutoReplyWhitelistEntry/AutoReplyAdminAuditLog/ConversationAutopilotState/DouyinConversationReadState/DouyinMessageResourceDownload/DouyinImageUpload |
| customer_profiles | 2 | CustomerProfile/ContactInvalidFollowupTask |
| compute | 4 | ComputeAccount/ComputeTransaction/ComputePackage/ComputeMarkupRatio |
| ai_edit | 7 | AiEditJob/AiEditJobArtifact/AiEditMaterial/AiEditMaterialAnalysis/AiEditMaterialProcess/AiEditTemplate/AiEditJobMaterial |
| 其他 | 16 | 授权账号(OAuth)/微信任务/日报报表/回访/禁用词/员工外部商户绑定/广告审核 |

### xg_douyin_ai_cs 库（`apps/.../rag/database.py`，7 表，原生 SQL 建表非 ORM）

| 表 | 说明 |
|---|---|
| knowledge_categories | 知识分类 |
| knowledge_documents | 知识文档 |
| knowledge_chunks | 文档分块（外键 knowledge_documents） |
| rag_training_runs | 训练运行 |
| llm_call_logs | LLM 调用日志 |
| knowledge_training_sessions | 训练会话 |
| knowledge_training_feedbacks | 训练反馈 |

---

## 六、模块依赖（粗粒度）

```
                        ┌─────────────────────────────────────┐
                        │  抖音 GMP（webhook + OpenAPI）        │
                        └──────────┬──────────────────────────┘
                                   │ webhook 直收
                        ┌──────────▼──────────────────────────┐
                        │  AI小高线索（9000 webhook/leads）     │
                        │  → 线索入库 → 分配 → 通知 → 回写     │
                        └──┬───────────────┬──────────────────┘
                           │               │ 通知任务
                  ┌────────▼─────┐   ┌────▼────────────────────┐
                  │ AI小高微信助手 │   │ AI小高智能体（agents）  │
                  │（19000 Local  │   │ 抖音企业号 LLM 客服配置  │
                  │  Agent）      │   └────────┬────────────────┘
                  └──────┬───────┘            │ 绑定
                         │ 回写检测结果        │
                         │              ┌─────▼──────────────────────┐
                         │              │ 抖音AI小高客服（9100）     │
                         │              │ RAG/LLM 回复 + 自动回复闭环 │
                         │              └─────┬──────────────────────┘
                         │                    │ HTTP（9000→9100 可信代理）
                         │                    │
                  ┌──────▼────────────────────▼──────────────┐
                  │  公共底座：auth/RBAC、数据库、发送 gate、     │
                  │  outbox、调度器、商户隔离、联系方式提取       │
                  └──────────────────────────────────────────────┘

  小高素材库 + AI小高剪辑（ai_edit router 共享）   ←─ 独立于线索链路，走 LAS/TOS
  AI小高算力（compute）                          ←─ 独立于线索链路，走 apps/compute
```

**关键依赖**：
- 线索→微信助手：线索分配后创建微信通知任务，19000 执行
- 线索→客服：webhook 入站消息触发 9100 LLM 自动回复（经 9000 gate）
- 智能体→客服：企业号绑定智能体，9100 消费 agent_config
- 所有模块→公共底座：auth/数据库/gate/outbox/商户隔离

---

## 七、已知 Legacy / Compat / Unknown（只标记，不正式定性）

| 标记 | 位置 | 现状 |
|---|---|---|
| leads_internal_webhook | `LEADS_WEBHOOK_INTERNAL_ENABLED`（`config.py:316`） | env 开关默认 false；true 时 webhook 转发 9202 internal |
| 旧微信自动检测 | `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT`（`config.py:349`） | env 开关默认 "0"；`main.py:193-207` 受保护启动 |
| douyinAPI 8081 | `DOUYIN_API_BASE_URL`（`config.py:217`） | 默认值仍 `http://127.0.0.1:8081`，未删；demo/参考实现非生产依赖 |
| callback.misanduo.com / douyinapi.misanduo.com | `local_agent_main.py:121`/`local_agent_exe_entry.py:85`/`douyin_live_check.py:56`/`integrations.py:877` | 硬编码域名（GMP 回调地址、OAuth redirect 默认 origin） |
| 旧拉取链路 sync-leads | `routers/integrations.py:595` | 路由保留；`auto_notify=True` 已显式禁用（`LEGACY_AUTO_NOTIFY_DISABLED`） |
| 兼容 webhook 旧路径 /webhook/douyin | `routers/integrations.py:45,867` | GMP 已配置的回调地址，保留兼容 |
| LEGACY_WECHAT_DEBUG_ENDPOINTS | `config.py:329-330` | env 开关默认关；`routers/replies.py` 多处守卫旧微信 debug 接口 |
| DY_BASE_URL_LEGACY | `config.py:228-229` | OpenAPI base_url 回退 legacy 值 |
| auth_mode="legacy" | `auth/local_agent_auth.py:62,67` | Local Agent 旧未认证回退 |
| legacy_foreground_ok/diag | `wechat_ui/contact_searcher.py` | 微信前台置顶旧实现诊断字段 |
| token 计量 legacy_characters | `models.py:951`/`schemas.py:1395` | 历史 AI 消费标记兼容枚举 |
| 算力 service 兼容入口 | `services/compute_service.py:1-4` | Phase 3-B 起实现收敛到 `apps/compute/services/`，入口保留兼容 |
| 一键过审（CANCELLED_BY_CUSTOMER） | `models.py` AdReview* 三表 | 2026-07-13 客户取消，代码保留不回退 |

**未发现** `deprecated`/`FROZEN` 关键字在 `app/` 代码注释中（Legacy 普遍以 `legacy_` 前缀 + env 开关形式存在，默认关闭）。

---

## 探索范围说明

本地图覆盖：运行组件、7 业务模块、公共能力、外部系统、一级数据域、模块依赖、已知 Legacy 标记。
**不包含**：完整 CODE_INDEX（1A.2）、Legacy 正式定性（1A.5）、解耦方案、代码修改。
