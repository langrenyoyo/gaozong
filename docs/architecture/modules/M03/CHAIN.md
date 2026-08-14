# M03 AI小高智能体 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M03 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 智能体（LLM 客服配置）管理：agent 配置、状态、抖音账号↔agent 绑定、知识分类与知识训练。
- **边界红线**：不负责客服运行主体（归 M01）；不负责 RAG 检索执行（9100 M01 子应用执行，但训练/知识域配置归 M03）；"智能体 Agent"（9100 LLM 客服配置）≠ "Local Agent"（19000 微信进程，M04）。

## 2. User Entrypoints
- 5173 前端「超级商户/智能体」：agent 管理、知识分类、知识训练（SuperMerchantAgent、SuperMerchantManagement）。
- 9000 API：agent / agents / knowledge_categories / knowledge_training / capability_gateway（能力中心聚合展示）。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/agents/`（SuperMerchantAgent、api.ts、routes.ts、types.ts）。
- 页面：SuperMerchantAgent、SuperMerchantManagement。
- API clients：agent、aiAgents。
- 能力中心：navigation/capabilityNav + capabilityRoutes + features/capabilities.ts（PLATFORM，聚合 6 子应用 META）。

## 4. Backend API Entrypoints
- `app/routers/agent.py`、`agents.py`、`knowledge_categories.py`、`knowledge_training.py`、`capability_gateway.py`（PLATFORM 网关，聚合 M01..M07 META）。
- 旧子应用 service（apps/agents、apps/knowledge）：被 9000 services 引用（COMPAT）。

## 5. Core Services
- `app/services/`：ai_agent_service、agent_status_service、agent_knowledge_category_service、knowledge_category_service、douyin_account_agent_binding_service。
- `app/repositories/knowledge_categories_async_repository.py`：异步仓储（9000/9100 共享）。
- 旧子应用：apps/agents/（agent 服务）、apps/knowledge/（知识服务，COMPAT）。

## 6. Data Ownership
- 9000 库表：ai_agents、agent_status、knowledge_categories、allowed_category_keys（9000 唯一注入）、douyin_account_agent_bindings。
- 被其他模块读写：M01 读取 agent 配置判定自动回复；M02 读取 agent 归属；9100 消费 knowledge_categories。

## 7. Async / Worker Chain
- 知识训练：9000 knowledge_training router → 9100 knowledge_training_service（RAG ingest）→ 训练反馈自动入库（M01 库）；训练 run 计费（M07 幂等，identity=rag_training_run:{id}）。
- 能力中心：capability_gateway 聚合各子应用 META（静态 import，无运行 worker）。

## 8. External Dependencies
- NewCarProject：商户/功能授权权威（`auto_wechat:ai_agent` 等权限码）。
- 9100（M01 子应用）：知识训练/RAG 执行（HTTP，经 9000 proxy 或内部 client）。
- Milvus：知识向量副本（训练写入与检索，metadata 真源=PG）。

## 9. Cross-Module Calls
- CALLS：M01（知识训练 RAG、客服 agent 配置消费）、M07（训练/检索计费上报）。
- AUTHORIZES：agent 相关权限码经 PLATFORM-AUTH。
- COMPAT_FOR：apps/agents、apps/knowledge（旧子应用 META/service 被 9000 引用）。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:ai_agent`、`auto_wechat:knowledge` 等；SuperMerchant 域含 NewCar 商户管理授权（SuperMerchantManagement，NewCar 权威）。
- merchant/tenant：allowed_category_keys 只能由 9000 注入（agent_config 权威源）。
- 统一知识 scope：tenant_id=xiaogao_system、merchant_id=xiaogao_base、douyin_account_id=0、category_key=base（env 可覆盖）。

## 11. Compatibility Layer
- apps/agents、apps/knowledge 旧子应用：COMPAT，META/service 被 capability_gateway 与 9000 services 引用。removal_prerequisite：全部引用迁移到 9000 services / packages/clients。

## 12. Legacy Candidates
- apps/agents、apps/knowledge 内部旧逻辑：LEGACY 候选（登记 ≠ 可删除；capability_gateway import 仍存在）。
- knowledge 旧子应用 SQLite 迁移残留：已由 PG 迁移链替代（migrate_knowledge_categories，LEGACY 脚本）。

## 13. Known Unknowns
- U-002（与 M01 共用）：Agent 绑定→Auto Reply / 事实隔离 / Training 隔离三个关键门未在 staging 补测（m03-baseline-candidate-status）。
- U-006：capability_gateway 对 6 子应用 META 的运行时可达性未逐一验证（子应用 main 未挂载，META 静态可达）。
- 知识训练 PG 事务边界 = PG_VERIFIED_MIDPOINT（training 0004），生产 RUNTIME_UNKNOWN。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：agent 配置→绑定→自动回复启用的隔离门；知识分类/训练→RAG 检索的 scope 隔离；allowed_category_keys 仅 9000 注入；训练/检索 M07 计费幂等；capability_gateway META 可达性。G1 阶段不展开。
