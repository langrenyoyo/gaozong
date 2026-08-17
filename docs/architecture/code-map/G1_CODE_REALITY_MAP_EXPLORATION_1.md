# G1 CODE REALITY MAP — EXPLORATION 1

> 本报告基于 auto_wechat 当前真实代码（G0_CANDIDATE_SHA=`88235b5bba363fd0dec4945b8e38aba1e82e2d9b`）与已冻结治理文档（SYSTEM_MAP / CODE_INDEX.yaml / LEGACY_REGISTER）交叉核实而成。
> 本轮为 **REPOSITORY REALITY EXPLORATION**，源码只读，不实施任何重构 / 删除 / 修改。
> 事实来源标记：`[代码]`=真实代码核实、`[治理]`=已冻结治理文档、`[代理]`=并行只读探索代理、`[待补]`=G1 后续执行窗口需补齐。
>
> **修订记录（v2，2026-08-13）**：Owner 已批准 Option A（M01–M07 七模块方向），G1 Scope Freeze 暂缓执行。本版合并 frontend / 9000 / 9100 / 19000 四个探索面证据（四代理被停，由主线以只读方式补齐）：修正 9000 Router 数量（38→41）、BC-05 定性（Windows 平台条件注册）、Alembic 区分 REPOSITORY_HEAD 与 production/runtime revision、每模块 confidence 明确（5 HIGH + 2 MEDIUM）、新增前端 legacy 路由重定向 COMPAT 层。

---

## 1. Executive Verdict

```text
G1_EXPLORATION
= EXPLORATION_COMPLETE_READY_FOR_G1_SCOPE_FREEZE
```

**判定理由**：

1. 七模块边界从真实代码**自然形成**，无需硬凑：
   - 前端有 6 个独立 feature 目录（`agents` / `douyin-cs` / `leads` / `wechat-assistant` / `ai-edit` / `compute`），其中 `ai-edit` 靠 nav id（`ai-edit-materials` / `ai-edit-editor`）区分素材库与剪辑两个模块；路由由 6 个 feature routes 合并（`frontend/src/features/routes.ts:9-16`）；
   - 后端 41 个 router（跨平台 39 + Windows 专用 2，`app/main.py:125-169`）与 83 个 service 的归属映射清晰；
   - 数据库 54 表按数据域归属明确（leads 9 表 / agents 4 表 / ai_auto_reply 11 表 / compute 4 表 / ai_edit 7 表等）；
   - 既有 `CODE_INDEX.yaml` 的 **M01–M07 稳定 ID** 已被 P1/P2 治理文档大量引用（M01 Auto Reply、M02 leads、M04 claim/lease、M05 material_analysis、M06 record_usage、M07 compute），与真实代码一致。
2. M05/M06 实现层共置（共用 `ai_edit.py` router 与 `features/ai-edit/` 目录）已登记为 BC-02 解耦候选；**Option A（M01–M07 七模块）已获 Owner 批准**（2026-08-13），不再作为待拍板项。
3. 发现 **8 项 Boundary Conflict / 文档漂移**（见 §6），其中 2 项影响 G1 后续执行（BC-03 CODE_INDEX baseline 滞后、BC-04 9100 已接入 Alembic 但 SYSTEM_MAP 仍称原生 SQL）。

```text
MODULE_TAXONOMY
= PROPOSED（M01-M07，见 §4）

PLATFORM_BOUNDARY
= PROPOSED（见 §3）

CODE_INDEX_SCHEMA
= PROPOSED（文件级 schema，见 §8 + code_index.schema.yaml DRAFT）

MODULE_CHAIN_TEMPLATE
= PROPOSED（见 §9 + module_chain_template.md DRAFT）

FULL_CODE_MAP
= NOT YET GENERATED

G2 LEGACY CONSOLIDATION
= NOT AUTHORIZED
G3 SEVEN-MODULE VERIFICATION
= NOT AUTHORIZED
G4 CONTROLLED DECOUPLING
= NOT AUTHORIZED
```

---

## 2. Repository Reality Summary

| 资产 | 数量 | 说明 |
|---|---|---|
| Frontend feature 目录 | 6 | `agents`/`douyin-cs`/`leads`/`wechat-assistant`/`ai-edit`/`compute` |
| Frontend api 客户端 | 30 | `frontend/src/api/*.ts`，含 `localWechatAgent.ts`（前端→19000 直连） |
| Frontend pages | ~30 | `frontend/src/pages/*.tsx`（含较新页面落于 pages 而非 features，如 `AiReplyDecisionLogsPage`） |
| 9000 Router 注册 | 41 | 跨平台 39 个（`app/main.py:125-164`，auth 双挂载无前缀+`/api`）+ Windows 专用 2 个（feedback/lead_notifications，`main.py:167-169` 平台条件注册，见 BC-05） |
| 9100 Router | 9 | `health`/`categories`/`accounts`/`conversations`/`ai_reply`/`rag`/`knowledge_training`/`daily_reports`/`return_visits`（`apps/xg_douyin_ai_cs/main.py:52-60`） |
| 19000 Local Agent endpoint | ~20 | `/runtime/*`×3、`/agent/version`、`/health`、`/agent/ocr/*`×2、`/agent/wechat/*`×9、`/agent/tasks/poll-and-*`×3、`/agent/replies/detect`（`app/local_agent_main.py:1642-2672`） |
| 前端路由 | 6 feature routes 合并 | `frontend/src/features/routes.ts:9-16`：douyin-cs/leads/agents/wechat-assistant/compute/ai-edit |
| 前端 legacy 路由重定向 | 21 | `routes.ts:18-41`：`/douyin-ai-cs*`、`/leads/list|board|detail`、`/ai-agent`、`/compute`、`/knowledge-*` 等旧路径 → 新路径（前端 COMPAT 层，见 BC-08） |
| app/services | 83 | 无 `legacy_` 前缀文件；Legacy 以 env 开关 + 分支形式存在 |
| 子应用 | 2 | `apps/xg_douyin_ai_cs/`（9100）、`apps/compute/services/`（算力实现） |
| Scheduler | 5 | check / wechat_auto_detect（默认关）/ daily_report / return_visit_silent_scan / contact_invalid_followup |
| Outbox | 1 | `ai_auto_reply_outbox_service.py`（claim/lease/恢复） |
| 数据表（auto_wechat 库） | 54 | ORM（`app/models.py`），按域分组见 §7 |
| 数据表（xg_douyin_ai_cs 库） | 7+ | 原生 SQL 建表，**已接入 Alembic**（0002-0005，见 BC-04） |
| Alembic 迁移（REPOSITORY_HEAD） | 0035 | auto_wechat 迁移文件最高=`0035_wechat_task_claim_lease`（0031 跳号不存在）；9100=`0005_rag_search_executions`。**REPOSITORY_HEAD ≠ production/runtime revision**，见下方专项说明 |
| 外部集成 | 7 | NewCarProject / 抖音 GMP / Milvus / LLM(ARK) / LAS / TOS / douyinAPI(8081 demo) + Local Agent(19000) |
| 测试文件 | 280 | `tests/*.py` 顶层（分类见 §10） |
| 治理文档 | 6 份齐备 | SYSTEM_MAP / CODE_INDEX.yaml / RUNTIME_ENTRYPOINTS / DEPENDENCY_MATRIX / LEGACY_REGISTER / CROSS_MODULE_RISK_REGISTER |
| 执行包 | 44 | `docs/superpowers/plans/`（phase0~phase13 等，历史施工事实） |
| Legacy 登记 | 15 项 | `LEGACY_REGISTER.md` 已冻结（见 §11） |
| 部署脚本 | 1 canonical | `scripts/release_9000_s10b.py`（G0 唯一生产部署入口） |

> 数量说明：测试文件 280 为顶层 glob 命中数（含分类样本），router/service 数量为代码核实值，不追求虚构精确。

### 2.1 Alembic：REPOSITORY_HEAD 与 production/runtime revision 必须区分

> 硬约束：**不得把 repo head 当作 production release identity**。以下 revision 为两类独立事实。

| 维度 | auto_wechat（9000 主库） | xg_douyin_ai_cs（9100 RAG 库） | 来源 |
|---|---|---|---|
| **REPOSITORY_HEAD**（repo 中最新迁移文件） | `0035_wechat_task_claim_lease`（P2 M04；0031 跳号不存在） | `0005_rag_search_executions` | `[代码]` `git ls-files migrations/postgres/*/versions/` |
| **production/runtime revision**（已部署实例实际 `alembic_version`） | 生产 `merchant.xiaogaoai.cn` = **0034**（Attempt3 发布 2026-08-13 目标；R1 事故恢复后 9000=4b4f96fc/0034）；旧实例 `callback.misanduo.com` = SQLite/0033（2026-08-12 只读核实，历史） | 生产 = **0003**（Attempt3 全程冻结，零影响）；本地 dev 9100 若临时连 SQLite 另计 | `[治理]` 05_PROJECT_CONTEXT / G0 执行链 / production-dual-instance-reality |
| **本地 dev PG** | canonical alembic baseline@`0034`（DB-BL-2D 重建，`/ready` PG HTTP200） | dev 临时库 | `[治理]` |
| **0035 状态** | **仅 REPOSITORY_HEAD，未在任何 production/runtime 验证**（P2 M04 closure commit 36fe68a 未 push，Cutover Gate=CUTOVER_NOT_READY） | — | `[治理]` |

**关键结论**：G1 报告与 Code Map 的 `alembic_version` 字段必须分列 REPOSITORY_HEAD / PRODUCTION_REVISION，release identity 只认后者（G0 P10/P12 契约即按 release env expected revision + DB actual revision 三方 gate，与 repo head 无关）。

---

## 3. Platform Baseline Proposal

> 标准：只有跨所有业务模块的公共能力才能归 PLATFORM；每个条目必须回答「为什么不是某业务模块的能力 / 被哪些模块复用 / 谁拥有公共合同」。

| PLATFORM-ID | 职责 | 主要路径 | 当前调用者 | 为什么属于公共底座 |
|---|---|---|---|---|
| PLATFORM-AUTH | 认证 + RBAC + NewCar 外部鉴权门面 + Local Agent 鉴权 + 商户/外部绑定 | `app/auth/`（context/dependencies/newcar_client/local_agent_auth/external_merchant_binding_service）+ `app/routers/auth.py`（无前缀与 `/api` 双挂载） | 所有业务 router | 登录/鉴权/权限是跨模块统一合同；`/auth/me` 权限上下文被全部受保护路由消费 |
| PLATFORM-DB | 数据库底座：engine / Session / Base / get_db / URL 解析 / 就绪检查 | `app/database.py` + `app/database_url.py` + `app/db_readiness.py` | 所有模块 + alembic + 维护脚本 | 连接/事务/池化是统一基础设施；SQLite↔PG 回退策略全仓唯一事实源 |
| PLATFORM-GATE | 抖音自动回复发送闸门（限频/违禁词/人工接管/幂等/紧急停止） | `app/services/douyin_autoreply_gate_service.py` | M01 自动回复、人工接管 | 发送安全底线是平台级横切约束，不属于单一业务模块 |
| PLATFORM-OUTBOX | 发件箱持久化任务调度（claim/lease/恢复） | `app/services/ai_auto_reply_outbox_service.py` + `main.py` lifespan | M01 自动回复（当前唯一消费）；架构上可扩展给其他异步发送 | 任务持久化/幂等/恢复是通用异步基础设施 |
| PLATFORM-SCHED | 调度器聚合与启动 | `app/scheduler/*` + `app/main.py` lifespan | M01/M02/M04 的定时任务 | 调度生命周期统一由 lifespan 管理 |
| PLATFORM-ISO | 商户隔离 / 账号归属校验 / 可信商户过滤 | `app/services/douyin_merchant_isolation.py` | M01/M02/M04 全部数据路径 | 商户边界是跨模块数据安全红线 |
| PLATFORM-RELEASE | 发布/部署治理（G0 硬化） | `scripts/release_9000_s10b.py` + preflight + release identity env | 生产部署唯一入口 | 部署身份校验是平台级治理，不属于业务模块 |

**领域共享能力（domain_shared，非平台基础设施）**：`contact_extraction` 系列（`contact_extractor.py` / `contact_state_service.py` / `customer_profile_service.py` / `contact_completion_resolver.py` / `contact_validity_analyzer.py` / `contact_invalid_followup_service.py` / `douyin_customer_profile_deriver.py`）——属于客户/线索领域共享，有明确领域 owner（M02），不归 PLATFORM。

**「共享但未必平台」专项结论**：`[代码]` 全仓无 `app/utils|common|helpers|shared|client|manager` 目录，未发现"被错误放进 common 的业务代码"；共享能力均已落位平台层或领域共享层（Q2 核心结论）。

---

## 4. Seven-Module Taxonomy Proposal

> 模块稳定 ID 沿用既有 `CODE_INDEX.yaml`（M01-M07），与 P1/P2 治理文档引用一致，不重新分类。

| Module ID | 名称 | 核心职责 | 主要入口 | 数据 Owner | Confidence |
|---|---|---|---|---|---|
| M01 | 抖音AI小高客服 | 私信工作台 + RAG/LLM 回复 + AI 托管自动回复闭环 + 9100 子应用 | 前端 `/douyin-cs/workbench`；后端 `douyin_ai_cs_proxy`/`douyin_autoreply_settings`/`ai_auto_reply_runs`/`ai_reply_decision_logs`/`admin_autoreply_rollout`；9100 子应用 9 routers | ai_auto_reply_runs 等 12 表 + xg_douyin_ai_cs 库 | HIGH |
| M02 | AI小高线索 | 抖音私信线索 webhook 直收→入库→分配→通知→回复检测→回访；联系方式提取领域 | 前端 `/leads`/`/chat`；后端 `leads`/`integrations`(webhook)/`webhook_events`/`lead_notifications`/`sales_feedback` | douyin_leads 等 13 表 + customer_profiles + contact_invalid_followup_tasks | HIGH |
| M03 | AI小高智能体 | 抖音企业号绑定 LLM 客服配置 + 知识分类/训练入口 | 前端 `/agents`；后端 `agents`/`agent`/`knowledge_categories`/`knowledge_training` | ai_agents 等 4 表 | HIGH |
| M04 | AI小高微信助手 | 本机微信 UI 自动化（通知/检测/回复回写）+ 日报/回访 + 19000 Local Agent | 前端 `/wechat/*`；后端 `wechat_tasks`/`wechat_auto_detect`/`replies`/`checks`/`daily_reports` | wechat_tasks 等 6 表 | HIGH |
| M05 | 小高素材库 | AI 剪辑素材管理 + 素材分析 | 前端 `/ai-edit/materials`；后端 `ai_edit`（与 M06 共置） | ai_edit_materials 等 5 表 | MEDIUM（与 M06 共享实现，见 BC-02） |
| M06 | AI小高剪辑 | LAS 云端混剪（火山 `las_video_remix` 三模式 `marketing_headtalk`/`long_real_shot`/`real_shot_headtalk`）+ 产物交付 + 算力记录 | 前端 `/ai-edit/editor`；后端 `ai_edit`（与 M05 共置） | ai_edit_jobs + ai_edit_job_artifacts | MEDIUM（与 M05 共享实现，见 BC-02） |
| M07 | AI小高算力 | 商户算力套餐/消耗/计费展示（兼容入口→`apps/compute/services/`） | 前端 `/compute`；后端 `compute`(+admin+internal) | compute_accounts 等 4 表 | HIGH |

**Confidence 汇总（M01–M07 每模块明确）**：`5 HIGH + 2 MEDIUM`。
- HIGH：M01 客服（9100 完整独立子应用 + 12 表）、M02 线索（webhook 直收 + 13 表）、M03 智能体（4 表 + 知识分类/训练）、M04 微信助手（19000 完整契约 ~20 endpoint + wechat_ui 16 文件 + 日报/回访）、M07 算力（compute + admin + internal + apps/compute/services）
- MEDIUM：M05 素材库 / M06 剪辑（边界清晰但 **M05/M06 共用 `ai_edit.py` router 与 `features/ai-edit/` 目录**，见 BC-02；MEDIUM 仅因实现层共置，不因边界本身存疑）

**七模块边界判定依据**（每模块满足：独立业务能力 + 明确数据/行为 owner + 可独立描述链路 + 未来可独立验收）：
- 前端 6 feature 目录 + 9100 子应用 + 菜单 nav id 一一对应；
- 后端 router / service / 表归属清晰，`CODE_INDEX.yaml` 已按模块登记 entrypoints / tables / config / tests / dependencies；
- P1 算力幂等（M01/M02/M05/M06/M07 各 charge path）+ P2 M04 claim/lease 均按模块 ID 推进并闭环。

---

## 5. Alternative Taxonomy

| Option | 切法 | 说明 |
|---|---|---|
| A（推荐） | **7 模块（现状）** | M05/M06 逻辑边界清晰（数据表、服务、前端 nav、验收均分离），仅 router/feature 目录共置；保持 7 模块利于独立验收与算力计费分开归属 |
| B | **6 模块**：M05+M06 合并为「AI 剪辑域」 | 合并后共享 router/feature 目录实现层天然对齐，但算力计费（M06 record_usage）与素材分析（M05 material_analysis）会并入同一验收边界，且与既有治理文档 M05/M06 拆分引用冲突 |

**推荐 A**：合并收益（少一个模块）< 独立验收收益（素材库与剪辑生命周期、外部依赖 TOS vs LAS+TOS、测试/审批均不同）。**该决策已获 Owner 批准（2026-08-13）：Option A（M01–M07 七模块）为最终方向**，本节仅保留 Option B 作为对照记录，不再作为待决策项。

---

## 6. Boundary Conflicts

> 只登记事实，本轮不整改。

| 编号 | 冲突 | 证据 | 影响 |
|---|---|---|---|
| BC-01 | SYSTEM_MAP 表格展示顺序（agents 在前）≠ CODE_INDEX 稳定 ID（M01=抖音AI小高客服） | `SYSTEM_MAP.md:44-53` vs `CODE_INDEX.yaml:37` | 模块 ID 以 CODE_INDEX.yaml 为准；SYSTEM_MAP 表格顺序易误导，建议后续统一 |
| BC-02 | M05/M06 代码共置 | 共用 `app/routers/ai_edit.py` 与 `features/ai-edit/`；CODE_INDEX 标 `shared_implementation/co_located`（`CODE_INDEX.yaml:346,389`） | 解耦候选；新 VibeCoding 窗口需靠 nav id + 服务名区分归属 |
| BC-03 | CODE_INDEX baseline 滞后 G0 | `CODE_INDEX.yaml:17` source_commit=`c26ec227e70d`（2026-08-07）vs G0=`88235b5`；其间 **121 commits / 213 files / +107050 行**（P1 算力幂等 11 consumer、P2 M04、DB-BL 基线、S10-B、G0） | G1 后续执行窗口必须刷新 baseline；七模块纵向边界未变，但新增执行实体与迁移需登记 |
| BC-04 | SYSTEM_MAP 称 9100 原生 SQL 建表，实际已接入 Alembic | `SYSTEM_MAP.md:25` vs `migrations/postgres/xg_douyin_ai_cs/versions/0002-0005` | 文档漂移；9100 库已有 alembic 链（0005 head） |
| BC-05 | 9000 router **平台条件注册**（已定性） | `app/main.py:59-65` try/except ImportError 导入 `feedback`/`lead_notifications`（依赖 comtypes/uiautomation），`main.py:167-169` 仅 `_WINDOWS_ROUTERS_AVAILABLE` 为 True 时注册 | 条件 = **平台**（Windows vs Linux/Docker），非 env 开关；Code Map 须将这两个 router 标记 `WINDOWS_ONLY`，避免误标「恒现役」 |
| BC-06 | 算力 service 兼容入口 | `app/services/compute_service.py`（兼容入口）vs `apps/compute/services/`（实现收敛） | 已登记 LEGACY-012；新代码应直接走 apps/compute/services |
| BC-07 | `integrations.py` 多职责 | webhook 主入口 + legacy_webhook 兼容路径 + sync-leads 旧拉取链路并存（`CODE_INDEX.yaml:118,196` lifecycle_candidates UNKNOWN） | 需拆分登记（webhook=ACTIVE、legacy 路径=COMPAT、sync-leads=LEGACY_CANDIDATE） |
| BC-08 | 前端 legacy 路由重定向层 | `frontend/src/features/routes.ts:18-41` 共 21 条旧路径重定向（`/douyin-ai-cs*`、`/leads/list|board|detail`、`/ai-agent`、`/compute`、`/knowledge-*` 等） | 前端 COMPAT 层（历史路由 → 新路由），Code Map 应登记为 COMPATIBILITY 而非 LEGACY_CANDIDATE（仍有合法用户书签/历史入口） |

---

## 7. Platform / Module / Compatibility / Legacy / Unknown Matrix

| 资产类型 | 归属 | 主要成员 |
|---|---|---|
| PLATFORM | 公共底座 | auth/RBAC、database 底座、发送 gate、outbox、schedulers、商户隔离、release 治理（§3 7 项） |
| PLATFORM-domain | 领域共享（非平台） | contact_extraction 系列（7 文件） |
| MODULE M01 | 客服 | douyin_ai_cs_proxy / autoreply 系列 router + 9100 子应用（9 routers）+ ai_auto_reply* 12 表 |
| MODULE M02 | 线索 | leads / integrations / webhook_events / lead_notifications / sales_feedback + 13 表 |
| MODULE M03 | 智能体 | agents / agent / knowledge_categories / knowledge_training + 4 表 |
| MODULE M04 | 微信助手 | wechat_tasks / wechat_auto_detect / replies / checks / daily_reports + 6 表 + 19000 |
| MODULE M05 | 素材库 | ai_edit（共置）+ 素材/分析 5 表 |
| MODULE M06 | 剪辑 | ai_edit（共置）+ LAS/TOS + jobs/artifacts 2 表 |
| MODULE M07 | 算力 | compute(+admin+internal) + 4 表 + apps/compute/services |
| COMPATIBILITY | 兼容层 | 见 §12（5 项 COMPAT + legacy_webhook 等） |
| LEGACY | Legacy Candidate | 见 §11（LEGACY_REGISTER 15 项） |
| UNKNOWN | 待定 | 见 §13 Unknown Registry |

---

## 8. Machine-Readable Index Schema Proposal

**分层原则**（不取代、不合并）：

1. **模块级索引（既有，唯一事实源）**：`docs/architecture/CODE_INDEX.yaml`（schema v2，427 行）——描述「模块边界 + 模块级依赖」，`scripts/generate_code_index.py` 生成 `.md` 派生视图，禁止手工编辑派生文件。
2. **文件级 Code Map（G1 新增，DRAFT）**：`docs/architecture/code-map/code_index.schema.yaml` + 待生成 `code_index.yaml`——描述「每个代码资产的文件级归属」，通过 `module` 字段关联模块级索引。

**文件级 entries 字段**（已落盘 DRAFT `code_index.schema.yaml`）：

```yaml
schema_version: "0.1.0-draft"
project: { source_commit, generated_at, last_verified_at, generator_script }
entries:
  - id: "ENT-000001"
    path: "app/routers/leads.py"
    artifact_type: "ROUTER"        # FRONTEND_PAGE/COMPONENT/API_CLIENT/ROUTER/SERVICE/MODEL/TABLE/WORKER/SCHEDULER/INTEGRATION/CONFIG/AUTH/SCRIPT/MIGRATION/TEST/DOC/OTHER
    owner_type: "MODULE"           # PLATFORM / MODULE / COMPATIBILITY / UNKNOWN
    owner_id: "M02"                # 关联模块级 CODE_INDEX.yaml 的 modules 键
    module: "M02"
    status: "ACTIVE"               # ACTIVE/PLATFORM/COMPATIBILITY/LEGACY_CANDIDATE/DEV_ONLY/TEST/UNKNOWN
    runtime_role: "HTTP_API"       # HTTP_API/WORKER/SCHEDULER/STARTUP/SUBAPP/SCRIPT/NONE
    entrypoints: []
    data_owned: []                 # 写/拥有的表
    data_read: []                  # 只读的表
    dependencies: []               # type: module/service/table/external
    depended_by: []                # 反向依赖（生成器计算，不人工双写）
    external_dependencies: []
    compatibility: { comp_for, purpose, removal_prerequisite }
    legacy: { legacy_id, historical_purpose, evidence, risk }
    evidence: []                   # 文件:行号 / 运行证据
    notes: ""
```

**关键设计决策**：`owner_type=UNKNOWN` 是合法状态（目标 `UNKNOWN = EXPLICIT + FINITE + TRACEABLE`，不是 0）；`status=LEGACY_CANDIDATE ≠ SAFE_TO_DELETE`；本文件是 DERIVED GOVERNANCE ARTIFACT，**禁止被应用启动读取**。

---

## 9. Module Chain Template Proposal

已落盘 DRAFT `docs/architecture/code-map/module_chain_template.md`，14 节骨架：1 Responsibility / 2 User Entrypoints / 3 Frontend Entrypoints / 4 Backend API Entrypoints / 5 Core Services / 6 Data Ownership / 7 Async-Worker Chain / 8 External Dependencies / 9 Cross-Module Calls / 10 Auth-Merchant Boundary / 11 Compatibility Layer / 12 Legacy Candidates / 13 Known Unknowns / 14 Future G3 Acceptance Boundary。

G1 只建立骨架与初步事实，不做完整 G3 验收。

---

## 10. Test Ownership Map

> 基于 `[代理]`（tests/ 顶层 280 文件，样本 100 分类）+ `[治理]` 交叉。

| 归属 | 测试数（样本） | 代表性文件 | 类型 |
|---|---|---|---|
| M01 客服 | ~24 | test_xg_douyin_ai_cs_*、test_douyin_ai_cs_binding_service、test_douyin_autoreply_settings_service、test_conversation_autopilot_state_service、test_knowledge_* | UNIT/INTEGRATION/CONTRACT |
| M02 线索 | ~17 | test_douyin_leads_session_isolation、test_leads_app、test_douyin_customer_profile_deriver、test_douyin_sync、test_lead_notification_records_route | INTEGRATION/UNIT/CONTRACT |
| M03 智能体 | ~8 | test_agent_status、test_douyin_account_agent_binding_service、test_agents_client | UNIT |
| M04 微信助手 | ~7 | test_wechat_auto_detect、test_automation_control、test_screenshot_sender、test_local_agent_heartbeat、test_wechat_task_history_api | REGRESSION/UNIT |
| M05/M06 素材/剪辑 | 待补 | （样本中未出现，按 plans 推断存在 phase12 ai-edit 系列） | UNKNOWN |
| M07 算力 | ~4 | test_compute_models、test_db_migration_0010_compute、test_9000_postgres_compute_core_schema | UNIT/INTEGRATION |
| PLATFORM | ~19 | test_utf8_json_response、test_scheduler、test_checks_permissions、test_db_migration_runner、test_database_url_config、test_9000_async_pg_*、test_alembic_postgres_skeleton、test_newcar_merchant_auto_provision | UNIT/INTEGRATION/REGRESSION |
| RELEASE/GOVERNANCE | ~22 | test_p0/p1/p7 系列（REGRESSION）+ test_release_g0_hardening.py + test_auth_fail_closed.py + test_capability_service_boundaries | REGRESSION/RELEASE_GOVERNANCE |

> 注：release 治理仅 `test_release_g0_hardening.py` 单点 + `test_auth_fail_closed.py`；`[待补]` M05/M06 与剩余 180 个未枚举文件的完整映射留给 G1 Full Mapping。

---

## 11. Legacy Candidates（登记 ≠ 可删除）

来源：`LEGACY_REGISTER.md`（15 项已冻结，baseline c26ec227e70d）。

| 状态 | 数量 | 条目 |
|---|---|---|
| LEGACY | 5 | 001 leads_internal_webhook_fallback / 002 旧微信自动检测调度器 / 005 sync-leads 旧拉取 / 007 LEGACY_WECHAT_DEBUG_ENDPOINTS / 009 auth_mode="legacy" Local Agent |
| COMPAT | 5 | 004 callback.misanduo.com 硬编码 / 006 兼容 webhook 旧路径 /webhook/douyin / 008 DY_BASE_URL_LEGACY / 011 legacy_characters 兼容枚举 / 012 算力 service 兼容入口 |
| DEAD_CANDIDATE | 2 | 003 douyinAPI(8081) / 013 一键过审 CANCELLED_BY_CUSTOMER |
| ACTIVE(quality) | 2 | 014 CONTACT_INVALID_FOLLOWUP_ENABLED（CONFIG_BYPASS）/ 015 @app.on_event 非 lifespan（TECH_DEBT） |
| UNKNOWN | 1 | 010 legacy_foreground_ok/diag 微信前台旧诊断 |

**删除资格**：不可删 5 项（004/006/011/014/015）；待证据 8 项；DEAD_CANDIDATE 满足前置可删 2 项（003/013）。**本轮不删除任何项。**

---

## 12. Compatibility Candidates

| COMPAT | path | purpose | current caller | replacement | removal prerequisite |
|---|---|---|---|---|---|
| C-001 | `app/routers/integrations.py:45,867` legacy_webhook_router | GMP 已配置的旧回调地址兼容 | 抖音 GMP 回调 | 主 webhook 路径 | GMP 侧回调地址切换后 |
| C-002 | `LEGACY_REGISTER 004` callback.misanduo.com 硬编码 | 历史回调/OAuth redirect 默认 origin | local_agent_main / local_agent_exe_entry / douyin_live_check / integrations | env 化 origin | 域名迁移后 |
| C-003 | `LEGACY_REGISTER 006` /webhook/douyin 旧路径 | 旧回调兼容 | 抖音 GMP 已配置 | 统一 webhook 入口 | GMP 重配置 |
| C-004 | `LEGACY_REGISTER 008` DY_BASE_URL_LEGACY | OpenAPI base_url 回退 | config 层 | 统一 base_url | 确认无旧环境依赖 |
| C-005 | `LEGACY_REGISTER 011` legacy_characters 枚举 | 历史 AI 消费标记兼容 | models/schemas 枚举 | 新计量口径 | 历史数据回写完成 |
| C-006 | `LEGACY_REGISTER 012` compute_service 兼容入口 | 历史调用方兼容 | 前端/旧调用 | apps/compute/services | 全部调用方迁移 |

---

## 13. Unknown Registry

> `UNKNOWN = EXPLICIT + FINITE + TRACEABLE`，不是目标清零。

| UNKNOWN_ID | path | question | missing evidence | recommended next verification |
|---|---|---|---|---|
| U-001 | `CODE_INDEX.yaml` 各模块 lifecycle_candidates | sync-leads / legacy webhook / DOUYIN_API_BASE_URL 8081 的 lifecycle 定性 | 当前是否有真实调用方 | G1 Full Mapping 阶段逐项查调用链 |
| U-002 | `app/services/*.py`（83 个） | 文件级 owner 逐个归属 | 文件级 Code Map 未填充 | G1 Full Mapping 分模块填充 |
| U-003 | ~~`app/main.py:125-130,168-169`~~ | **已解决**：条件注册 = Windows 平台条件（try/except ImportError，`main.py:59-65,167-169`），非 env 开关 | 已核实 `[代码]` | 关闭（归入 BC-05 登记） |
| U-004 | M05/M06 共置 | 合并后独立验收边界如何定义 | G3 验收设计 | Option A 已批准；G3 阶段按模块独立验收（router 共置不阻碍） |
| U-005 | 19000 契约全量 | 9000↔19000 / Frontend↔19000 完整契约 | 已核实 ~20 endpoint（`local_agent_main.py:1642-2672`）+ `frontend/src/api/localWechatAgent.ts` + `local_agent_auth.py`；task/claim_token 细节留 G1 Full Mapping | 主要已登记；心跳/轮询/claim 细节补扫 |
| U-006 | 9100 9 routers 文件级详情 | 每个 9100 router 与 9000 代理的对应 | 已核实 9 router 注册 + 目录结构（`apps/xg_douyin_ai_cs/main.py:52-60`）；9000 代理逐接口映射留 G1 Full Mapping | 主要已登记 |
| U-007 | tests 剩余 180 文件 | M05/M06 与未分类测试归属 | 全量映射未做 | G1 Full Mapping 阶段补全 |

---

## 14. G1 Full Mapping Execution Proposal

> 只设计下一步如何把正式 Code Map 填完整，本轮不实施。

| 阶段 | 内容 | 产出 |
|---|---|---|
| G1-M1 | 刷新模块级 baseline：CODE_INDEX.yaml source_commit `c26ec227e70d` → `88235b5`，登记 G0 后新增执行实体与迁移（P1 11 consumer / P2 M04 / DB-BL / S10-B） | CODE_INDEX.yaml v2.1 |
| G1-M2 | 文件级 Code Map 填充（分模块并行）：按本 schema 逐文件登记 entries | code-map/code_index.yaml |
| G1-M3 | 反向依赖生成 + 依赖方向核对（CALLS/READS/WRITES/PUBLISHES/CONSUMES/AUTHORIZES/WRAPS/COMPAT_FOR） | code_index.yaml 反向依赖 + CROSS_MODULE_DATA_ACCESS 标记 |
| G1-M4 | 测试映射补全（剩余 180 文件 → 模块/平台/类型） | §10 完整版 |
| G1-M5 | 条件注册、lifecycle_candidates、U-001~U-007 逐项验证并定稿 | Unknown Registry 收敛 |
| G1-M6 | schema v0.1-draft → v0.2 定稿（含 generate_code_index.py 家族扩展，若需） | code_index.schema.yaml 定稿 |

---

## 附 A：本轮三个核心问题结论

> **Q1：auto_wechat 当前真实的七个业务模块到底应该是哪七个？**
> **A1：** M01 抖音AI小高客服 / M02 AI小高线索 / M03 AI小高智能体 / M04 AI小高微信助手 / M05 小高素材库 / M06 AI小高剪辑 / M07 AI小高算力。从真实代码自然形成（前端 6 feature 目录 + 9100 独立子应用 + 19000 完整契约 + 后端 router/表归属），与既有 CODE_INDEX.yaml 稳定 ID 及 P1/P2 治理引用一致。**Option A（七模块）已获 Owner 批准**。Confidence：5 HIGH（M01/M02/M03/M04/M07）+ 2 MEDIUM（M05/M06 因共享实现，BC-02）；新证据未实质否定任何模块边界，**不触发 MODULE_TAXONOMY_DECISION_REQUIRED**。

> **Q2：哪些能力是真正 PLATFORM，而不是被错误放进 common/utils 的业务代码？**
> **A2：** 全仓无 common/utils 垃圾桶目录。真正平台能力 = auth/RBAC、database 底座、发送 gate、outbox、schedulers、商户隔离、release 治理（7 项，§3）。客户/线索领域共享（contact_extraction 系列）是带明确 owner 的领域能力，**不**归 PLATFORM。未发现被误放共享目录的业务代码。

> **Q3：如果明天一个新的 VibeCoding 窗口要修改某个需求，它能否仅通过 Code Map 判断"该读什么、能改什么、会影响谁"？**
> **A3：** **接近达标，尚未完全**。模块级 CODE_INDEX.yaml 已能回答"该模块读哪些 router/service/表/测试、主动依赖谁"；缺口在于：(a) 文件级归属未填充（U-002）；(b) 反向依赖由生成器计算但未持久化到文件；(c) CODE_INDEX baseline 滞后 G0（BC-03），G0 后新增的执行实体（如 AiPreviewExecution、RagSearchExecution 等 P1 实体）不在索引中；(d) lifecycle_candidates（U-001）未定稿。~~条件注册 router（BC-05）~~ 已解决（Windows 平台条件，`main.py:59-65,167-169`）；Alembic revision 须按 §2.1 区分 REPOSITORY_HEAD 与 production/runtime revision。补齐 G1-M1~M6 后即可达标。

---

## 附 B：本轮写入清单

- 新增 `docs/architecture/code-map/G1_CODE_REALITY_MAP_EXPLORATION_1.md`（本报告，EXPLORATION 产物）
- 新增 `docs/architecture/code-map/code_index.schema.yaml`（DRAFT）
- 新增 `docs/architecture/code-map/module_chain_template.md`（DRAFT）

**未修改任何业务代码 / 未删除任何文件 / 未跑任何生产命令。**

---

## 附 C：探索范围与完成状态

```text
SOURCE_CODE_MUTATION      = NOT AUTHORIZED → 遵守（0 修改）
PRODUCTION_MUTATION       = NOT AUTHORIZED → 遵守
G2 LEGACY CONSOLIDATION   = NOT AUTHORIZED → 遵守（仅登记 15 项）
G3 SEVEN-MODULE VERIFY    = NOT AUTHORIZED → 遵守（仅提 G3 验收边界模板）
G4 CONTROLLED DECOUPLING  = NOT AUTHORIZED → 遵守（M05/M06 仅登记解耦候选）
G1_EXPLORATION            = COMPLETE
MODULE_TAXONOMY           = PROPOSED（M01-M07，置信度见 §4）
PLATFORM_BOUNDARY         = PROPOSED
CODE_INDEX_SCHEMA         = PROPOSED（DRAFT schema 已落盘）
MODULE_CHAIN_TEMPLATE     = PROPOSED（DRAFT 模板已落盘）
FULL_CODE_MAP             = NOT YET GENERATED
```

**待 Owner 拍板事项**（进入 G1 scope freeze 前）：
1. ~~§5 Option A vs Option B~~ —— **已批准：Option A（M01–M07 七模块）为最终方向**；
2. G1 后续执行窗口是否按 §14 G1-M1~M6 推进 Full Code Map 填充（本轮不实施，`FULL_CODE_MAP_BUILD = NOT AUTHORIZED`）。
