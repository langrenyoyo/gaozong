# auto_wechat AI 文档索引

本目录用于保存 AI 协作规则、产品上下文、架构设计、验收记录和专题任务文档。

开始任何任务前，仍必须先按根目录入口文件要求阅读：

```text
CLAUDE.md
docs/ai/01_READING_RULES.md
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/02_EXECUTION_RULES.md
docs/ai/03_TESTING_RULES.md
docs/ai/04_OUTPUT_RULES.md
```

`docs/ai` 根目录只保留入口规则和项目上下文，专题文档按阶段和业务域归档。

## 根目录入口

| 文件 | 用途 |
|---|---|
| `01_READING_RULES.md` | 阅读和理解项目的强制规则 + AI 文档自治维护规则（第 18 节） |
| `02_EXECUTION_RULES.md` | 执行、风险、日志、安全边界 |
| `03_TESTING_RULES.md` | 测试和验收规则 |
| `04_OUTPUT_RULES.md` | 汇报格式和风险说明 |
| `05_PROJECT_CONTEXT.md` | **当前项目事实文档**（只保存当前有效上下文，不记录里程碑流水账） |

## 分阶段归档

| 目录 | 内容 |
|---|---|
| `00_rules/` | 预留规则扩展目录 |
| `01_product_prd/` | PRD、需求差距、需求对齐 |
| `02_architecture/` | 架构、运行时设计、阶段迁移总方案 |
| `03_data_and_migration/` | 数据模型、迁移、内部 webhook 和能力迁移记录 |
| `04_interface_contracts/` | 接口契约、Webhook 鉴权、外部系统契约 |
| `05_acceptance/` | 验收、测试计划、部署检查清单 |
| `06_rag/` | RAG、Milvus、统一知识库训练链路 |
| `07_autoreply/` | 自动回复、真实发送 gate、rollout 和白名单 |
| `08_newcar/` | NewCarProject 权限、登录、商户自动开通 |
| `09_car_project/` | car-porject-main 对接、8788 到 9000 链路 |
| `10_local_agent_wechat/` | Local Agent、微信自动化、安全边界和探索报告 |
| `11_deployment_ops/` | Docker、本地/宝塔部署、OpenAPI、live-check 安全清单 |
| `12_legacy_research/` | 历史代码计划、旧探索和低频参考资料 |
| `13_ai_edit/` | AI剪辑、小高素材库、冻结设计与外部能力迁入评估 |
| `archive/` | 冻结历史快照（非当前事实，仅追溯用） |

## 当前常用入口

| 场景 | 推荐阅读 |
|---|---|
| 一期需求权威文档 | `01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md` |
| 产品边界（历史 PRD） | `01_product_prd/06_PRD_AUTO_WECHAT.md` |
| 系统架构 | `02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md` |
| 数据模型 | `03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md` |
| PostgreSQL 迁移路线（含 schema batch、数据迁移、对照记录） | `03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md` |
| PostgreSQL 切库 readiness / cutover 审计 / 灰度 | `03_data_and_migration/POSTGRESQL_SWITCH_READINESS_AND_QPS600_ROADMAP.md`、`POSTGRESQL_CUTOVER_GAP_AUDIT.md`、`LEADS_TASKS_SHADOW_GRAY_PRESET_RUNBOOK.md` |
| PostgreSQL 生产切换 Runbook | `05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md` |
| 接口契约 | `04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md` |
| Webhook 鉴权 | `04_interface_contracts/10_WEBHOOK_AUTH_MIGRATION.md` |
| 测试计划 | `05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` |
| P1-END-1 验收（改微信自动化前必读） | `05_acceptance/P1_END_1_ACCEPTANCE.md` |
| 微信回复检测规则 | `10_local_agent_wechat/WECHAT_REPLY_DETECTION_RULES.md` |
| RAG / Milvus | `06_rag/P1_RAG_MILVUS_ARCHITECTURE_DESIGN.md` |
| 统一知识库训练 | `06_rag/P1_RAG_UNIFIED_KB_TRAINING_API_CONTRACT_FOR_CAR_PROJECT.md` |
| 自动回复 rollout | `07_autoreply/P1_AUTOREPLY_ADMIN_ROLLOUT_CONSOLE_DESIGN.md` |
| NewCar 权限 | `08_newcar/P1_AUTH_PERMISSION_ROUTE_MATRIX.md` |
| car-porject-main 对接 | `09_car_project/P1_CAR_PROJECT_DOUYIN_CS_TRAINING_CONVERSATION_LINK_AUDIT.md` |
| 本地 Docker | `11_deployment_ops/LOCAL_DOCKER_DEV.md` |
| AI剪辑 Phase 12 迁入准备 | `13_ai_edit/auto_edit_Phase12_AI剪辑迁入准备审计报告.md` |
| 小高素材库 / 视频增稳 | `13_ai_edit/BrollStudio_空镜素材复用与视频增稳评估报告.md` |
| Phase 12 AI剪辑本地 MVP 冻结设计 | `13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md` |

## 历史追溯 / 归档入口

以下文件**不是当前项目事实**，普通任务不得默认读取；仅在追溯历史决策或旧结论来源时按需读取：

| 内容 | 文件 |
|---|---|
| 2026-07-14 基线重构前的历史里程碑流水账（旧 05_PROJECT_CONTEXT 冻结快照） | `archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md` |

## 归档规则

1. 新文档优先写入对应专题目录，不再堆到 `docs/ai` 根目录。
2. 规则类文档继续保留在根目录，避免入口路径频繁变化。
3. 历史任务文档保留原文件名，通过目录表达归属。
4. 移动文档时必须同步更新 `CLAUDE.md`、`AGENTS.md`、根 `README.md` 和 `05_PROJECT_CONTEXT.md` 的关键链接。
