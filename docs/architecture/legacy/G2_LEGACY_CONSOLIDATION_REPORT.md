# G2 Legacy Consolidation Report（G2-LEGACY-CONSOLIDATION-1）

```text
TASK
= G2-LEGACY-CONSOLIDATION-1

TYPE
= GOVERNANCE_LEGACY_DISCOVERY_CLASSIFICATION

MODE
= AUDIT_CLASSIFY_DOCUMENT_VERIFY

BASE_SHA
= f582740d611d6791106a3eddcbf86ae6358f331d

HEAD_BEFORE
= f582740d611d6791106a3eddcbf86ae6358f331d（任务开始时即 BASE_SHA，工作区 clean）

DISCOVERY_METHOD
= G1 Code Reality Map 为主要入口（code_index.yaml 965 entries / 100% mapped）
+ G1 LEGACY_REGISTER 15 项逐项复核
+ code_index 非 ACTIVE 状态全量提取（57 LEGACY + 44 COMPAT + 1 LEGACY_CANDIDATE + 2 MIXED）
+ 命名层扫描（legacy/old/deprecated/compat/backup 文件名模式）
+ 代码标记扫描（legacy/旧版/兼容旧/历史遗留/TODO remove/deprecated 关键词）
+ 配置/env 别名扫描（.env.*.example 与 app/config.py 全量对照）
+ 接口/实现层依赖追踪（import / route 注册 / service 调用 / 前端调用 / 测试 / compose / 文档契约）
+ 6 个区域子代理并行只读审计（app 后端 / apps 旧子应用 / migrations+scripts / frontend / 9100+compute+LocalAgent / docker+specs+tests）
+ 主代理交叉验证（前端 shim、KernelMode、douyin_api_client 依赖链、legacy_foreground 诊断字段等关键证据亲自复核）
+ Git 历史仅作辅助解释，分类以当前 HEAD 代码事实为准
```

## 一、总账

```text
LEGACY_CANDIDATES = 62
CLASSIFIED_TOTAL  = 62

ACTIVE            = 15
COMPATIBILITY     = 21
LEGACY_KEEP       = 15
LEGACY_MIGRATE    = 2
DELETE_CANDIDATE  = 9

UNKNOWN_LEGACY    = 0
OWNER_CONFLICT    = 0
INVALID_CLASSIFICATION = 0
MISSING_REASON    = 0
MISSING_DELETION_CONDITION = 0
MISSING_SOURCE_FILE = 0
BUSINESS_CODE_DELTA = 0
```

## 二、Owner 分布（为 G3/G4 提供现实地图）

| Owner | 候选数 | ACTIVE | COMPATIBILITY | LEGACY_KEEP | LEGACY_MIGRATE | DELETE_CANDIDATE |
|---|---|---|---|---|---|---|
| PLATFORM | 18 | 2 | 8 | 3 | 1 | 4 |
| PLATFORM-RELEASE | 6 | 1 | 2 | 1 | 1 | 1 |
| M01 | 11 | 4 | 4 | 3 | 0 | 0 |
| M02 | 14 | 2 | 5 | 5 | 1 | 1 |
| M03 | 3 | 1 | 1 | 1 | 0 | 0 |
| M04 | 6 | 2 | 1 | 3 | 0 | 0 |
| M05 | 0 | 0 | 0 | 0 | 0 | 0 |
| M06 | 1 | 0 | 0 | 1 | 0 | 0 |
| M07 | 3 | 1 | 2 | 0 | 0 | 0 |
| DOMAIN_SHARED | 0 | 0 | 0 | 0 | 0 | 0 |

> M05 无候选（素材库为当前正式实现）；M06 仅 fix_ai_edit_jobs.py 登记项（LAS 混剪本身 ACTIVE，无遗留）；DOMAIN_SHARED 不单独设记录：contact_extraction 域归 M02（LEGACY-048/049 承载旧字段兼容读取）。

## 三、非 Legacy 事项确认

```text
HIGH_03       = NOT_LEGACY / unchanged（LAS long queued video_urls expire >7 天 = M06 known risk）
BC_02         = NOT_LEGACY / unchanged（M05/M06 物理边界耦合 = boundary coupling，留给 G4）
RG_FOLLOWUP_01 = NOT_LEGACY / unchanged
RG_FOLLOWUP_02 = NOT_LEGACY / unchanged
```

G2 审计过程中登记（不顺手修）的 2 处 release-governance 漂移：
1. `scripts/production_pg_alembic_upgrade.sh:31-32` 目标 revision 仍是 0007/0002，落后仓库 head（0035/0005）——cutover 执行前必须更新（独立 release 任务）。
2. code_index.yaml 头部 production revision 声称与 docs/ai/05_PROJECT_CONTEXT.md 存在出入——按 Source of Truth 层级以运行事实为准，登记不修改。

## 四、输出物

```text
REGISTRY = docs/architecture/LEGACY_REGISTER.md（G2 唯一 SSOT，扩展现有 G1 正式登记簿，50 条记录）
REPORT   = docs/architecture/legacy/G2_LEGACY_CONSOLIDATION_REPORT.md（本文件）
VALIDATION = scripts/validate_g2_legacy_registry.py（机器验收，G2_VALIDATION=PASS）
```

### 机器验收输出

```text
$ python scripts/validate_g2_legacy_registry.py
LEGACY_CANDIDATES      = 62
CLASSIFIED_TOTAL       = 62
ACTIVE                 = 15
COMPATIBILITY          = 21
LEGACY_KEEP            = 15
LEGACY_MIGRATE         = 2
DELETE_CANDIDATE       = 9
UNKNOWN_LEGACY         = 0
OWNER_CONFLICT         = 0
CODE_INDEX_OWNER_MATCH = 66/66 文件级匹配（R1 规则）
OWNER_WAIVED_FILES     = 24（R2/R3/R4 豁免，规则见下）
G2_VALIDATION = PASS
```

### Owner 交叉核验规则（与 LEGACY_REGISTER 一致披露）

- R1：G1 owner_type=MODULE 的文件 → G1 owner_id 必须等于记录 owner（模块归属矛盾，不可豁免）——56/56 全部匹配
- R2：记录 owner ∈ {PLATFORM, PLATFORM-RELEASE, DOMAIN_SHARED} 的平台级治理记录可引用 MODULE 文件作为证据（豁免，披露）
- R3：G1 owner_type=PLATFORM（含 PLATFORM-* 子类）文件豁免（平台公共/底座文件承载多模块能力，G1 文件级归属与 G2 能力级 owner 维度不同）
- R4：G1 owner_type=COMPATIBILITY（COMPAT-*）文件豁免（兼容层无模块归属）
- R5：G1 未收录文件（如 frontend/src/data/ mock 群）不判冲突

## 五、摘要表（ID | Classification | Owner | Name | Replacement | Deletion Condition）

| ID | Classification | Owner | Name | Replacement | Deletion Condition |
|---|---|---|---|---|---|
| LEGACY-001 | LEGACY_KEEP | M02 | leads_internal_webhook_fallback | 9000 本地直收 | 所有环境本地直收 + 9202 无生产流量 + env 模板移除变量 |
| LEGACY-002 | LEGACY_KEEP | M04 | 旧微信自动检测调度器 | 19000 poll-and-detect | 19000 生产稳定 + 前端移除调用 + env 模板移除变量 |
| LEGACY-003 | LEGACY_KEEP | M02 | douyinAPI 8081 demo 客户端 | webhook 直收 + OpenAPI | sync-leads 链路整体移除后无 import 残留 |
| LEGACY-004 | COMPATIBILITY | PLATFORM | callback.misanduo.com 硬编码域名 | NONE（GMP 已配置） | 域名迁移 env 化 + GMP/宝塔/Agent 同步 |
| LEGACY-005 | LEGACY_KEEP | M02 | sync-leads 旧拉取链路 | webhook 直收 | 前端移除 syncDouyinLeads 调用 + release window 零调用 |
| LEGACY-006 | COMPATIBILITY | M02 | 兼容 webhook 旧路径 /webhook/douyin | 正式入口 /integrations/douyin/webhook | GMP 回调地址切换 + 宝塔反代同步 |
| LEGACY-007 | LEGACY_KEEP | M04 | LEGACY_WECHAT_DEBUG_ENDPOINTS | 19000 诊断端点 | 19000 覆盖 + 无生产依赖 + env 模板移除 |
| LEGACY-008 | COMPATIBILITY | PLATFORM | DY_BASE_URL_LEGACY | DY_OPENAPI_BASE_URL+PREFIX | 所有环境新配置有值 + 移除回退逻辑 |
| LEGACY-009 | COMPATIBILITY | M04 | auth_mode="legacy" 未认证回退 | LOCAL_AGENT_AUTH_REQUIRED=true + TOKENS | 生产均 true + 移除 legacy 分支 |
| LEGACY-010 | ACTIVE | M04 | legacy_foreground_ok/diag 诊断字段 | NONE | NONE（当前正式诊断输出） |
| LEGACY-011 | COMPATIBILITY | M07 | legacy_characters 兼容枚举 | provider_tokens/estimated_tokens | 历史数据迁移 + 约束移除该值 |
| LEGACY-012 | COMPATIBILITY | M07 | 算力 service 兼容入口 | 直接 import apps.compute.services | 全部调用方迁移（当前 5 处） |
| LEGACY-013 | DELETE_CANDIDATE | PLATFORM | 一键过审 CANCELLED_BY_CUSTOMER | NONE（业务取消） | 无引用确认 + 数据归档后经独立审批 |
| LEGACY-014 | ACTIVE | M02 | CONTACT_INVALID_FOLLOWUP CONFIG_BYPASS | NONE | NONE（CONFIG_DRIFT 治理，非删除） |
| LEGACY-015 | ACTIVE | PLATFORM | @app.on_event TECH_DEBT | lifespan | NONE（迁移后关闭登记项） |
| LEGACY-016 | COMPATIBILITY | PLATFORM | 前端 legacy 路由重定向（22 条） | NONE（新路由体系） | 代码内引用清零 + 测试更新 + 生产日志零命中 |
| LEGACY-017 | COMPATIBILITY | PLATFORM | 前端权限码别名 | NONE（正式码 auto_wechat:agent） | NewCar 确认永不签发旧码 |
| LEGACY-018 | DELETE_CANDIDATE | PLATFORM | 前端 re-export 死 shim 群（20 文件） | NONE（features/ 实现） | 已满足（零引用零测试依赖） |
| LEGACY-019 | DELETE_CANDIDATE | PLATFORM | 前端死页面/死组件群（10 文件） | NONE | 已满足（零引用无路由；3 个需同步改测试） |
| LEGACY-020 | LEGACY_MIGRATE | M02 | 线索会话三组件不可达分支 | NONE（表格页取代） | 移除 Index.tsx 不可达分支与 import |
| LEGACY-021 | COMPATIBILITY | PLATFORM | 前端兼容占位层（navigation/api shim） | NONE | 测试断言更新后删除 |
| LEGACY-022 | DELETE_CANDIDATE | PLATFORM | 前端假数据 mock 群（data/ 7 组） | NONE（真实 API 已接入） | 已满足（零引用） |
| LEGACY-023 | ACTIVE | M01 | KernelMode 三模式（LEGACY/SHADOW/ENABLED） | NONE（当前正式机制） | NONE |
| LEGACY-024 | ACTIVE | M01 | Schema 2.0 Legacy 字段透传 | NONE（当前正式契约） | NONE |
| LEGACY-025 | COMPATIBILITY | M01 | P1 计费幂等 key None 兼容退路 | 显式 identity | P1 consumer 全部迁移 + 零 None 触发 |
| LEGACY-026 | COMPATIBILITY | M01 | dry-run 兼容调用名 | outbox 链路 | 无业务调用方 + 测试同步 |
| LEGACY-027 | ACTIVE | M03 | agents/knowledge service 实现层 | NONE（当前正式实现） | NONE |
| LEGACY-028 | LEGACY_KEEP | M03 | agents/knowledge dev 服务入口（9203/9206） | 9000 统一服务 | dev 能力中心退役 |
| LEGACY-029 | COMPATIBILITY | M02 | leads 子应用 META + 9202 兼容服务 | 9000 本地直收 | LEGACY-001 退役 + META 迁移 |
| LEGACY-030 | LEGACY_KEEP | M01 | douyin_cs 子应用 META + dev 入口（9201） | 9000 services | META 迁移 + dev 9201 移除 |
| LEGACY-031 | LEGACY_KEEP | M04 | wechat_assistant 子应用 META + dev 入口（9204） | 9000 services | META 迁移 + dev 9204 移除 |
| LEGACY-032 | DELETE_CANDIDATE | PLATFORM | 旧子应用单数 schema.py（5 文件） | 复数 schemas.py | 已满足（零 import） |
| LEGACY-033 | DELETE_CANDIDATE | M02 | leads webhook_events 死辅助函数 | douyin_webhook 实现 | 已满足（辅助函数零调用） |
| LEGACY-034 | ACTIVE | PLATFORM | SQLite 迁移轨道（versions 0001~0045） | PG Alembic 轨道 | PG cutover 完成后退役评估 |
| LEGACY-035 | LEGACY_KEEP | PLATFORM | SQLite 迁移降级脚本（downgrades） | NONE（历史资产） | SQLite 轨道退役时归档 |
| LEGACY-036 | COMPATIBILITY | PLATFORM-RELEASE | SQLite→PG cutover 脚本组（6+10 个） | NONE（一次性工具） | cutover 完成并验证后退役 |
| LEGACY-037 | LEGACY_KEEP | PLATFORM | 历史运维/验证脚本组 | NONE | 逐脚本确认无引用后审批 |
| LEGACY-038 | DELETE_CANDIDATE | PLATFORM-RELEASE | 根 Dockerfile（DEPRECATED SQLite-only） | 专用 Dockerfile 三件套 | 已满足（无 build 引用 + 拒启动） |
| LEGACY-039 | LEGACY_MIGRATE | PLATFORM-RELEASE | ai_edit_worker.spec 引用残留 | 移除 worker 打包分支 | 打包脚本修正引用并验证打包成功 |
| LEGACY-040 | LEGACY_KEEP | PLATFORM-RELEASE | Local Agent 打包 spec 资产组 | local_agent.spec | 被替代 spec 确认无引用后清理 |
| LEGACY-041 | DELETE_CANDIDATE | PLATFORM-RELEASE | env 模板死配置（LAN_* 三键） | NONE | 已满足（零引用零插值） |
| LEGACY-042 | DELETE_CANDIDATE | PLATFORM | packages/clients 死客户端（3 个） | NONE | 已满足（生产零引用；同步删测试） |
| LEGACY-043 | COMPATIBILITY | PLATFORM | legacy 兼容能力支持测试组 | NONE（随能力生命周期） | 对应兼容能力退役时同步移除 |
| LEGACY-044 | ACTIVE | M02 | douyin_webhook.py 主实现 | NONE（正式实现） | NONE |
| LEGACY-045 | COMPATIBILITY | M03 | knowledge_category_service re-export | 直接 import apps.knowledge.services | 调用方迁移后移除 |
| LEGACY-046 | COMPATIBILITY | M02 | GET /leads 默认数组响应 | 分页格式 | 前端数组路径迁移后改默认 |
| LEGACY-047 | LEGACY_KEEP | M02 | lead_notifications 410 封堵入口 | /send-to-staff 受控链路 | 410 命中归零 + 调试被替代 |
| LEGACY-048 | COMPATIBILITY | M02 | 线索展示旧字段兼容读取 | 权威列口径 | 历史数据迁移完成 |
| LEGACY-049 | COMPATIBILITY | M02 | contact_state 历史裸字符串兼容 | 标准 JSON 格式 | 历史数据迁移/归档 |
| LEGACY-050 | COMPATIBILITY | M01 | conversation_history 旧调用名 | build_reply_conversation_context | 测试迁移后删除 |
| LEGACY-051 | LEGACY_KEEP | M01 | admin-autoreply-rollout 隐藏入口 | env 开关 | 产品/运维确认永久退役 + 同步契约后审批 |
| LEGACY-052 | ACTIVE | M07 | apps/compute 独立服务入口（dev 9205） | NONE（正式部署形态） | NONE |
| LEGACY-053 | LEGACY_KEEP | M01 | milvus_export.py 运维导出脚本 | NONE | Milvus 备份迁移能力迁移到其他工具 |
| LEGACY-054 | ACTIVE | M01 | reply_hard_rules 旧私有名 re-export | NONE（单一权威正式方案） | NONE（别名整理属纯重构） |
| LEGACY-055 | COMPATIBILITY | M01 | embedding 旧 env 变量回退 | XG_DOUYIN_AI_EMBEDDING_ENABLED | dev compose/.env 更新为新变量后 |
| LEGACY-056 | ACTIVE | M02 | apps/leads service META（网关生产消费） | NONE | NONE |
| LEGACY-057 | ACTIVE | M01 | apps/douyin_cs service META（网关生产消费） | NONE | NONE |
| LEGACY-058 | ACTIVE | M04 | apps/wechat_assistant service META（网关生产消费） | NONE | NONE |
| LEGACY-059 | ACTIVE | PLATFORM | db_bl_2c 迁移链审计工具组（P1 验证权威） | NONE | NONE（基线永久冻结时评估） |
| LEGACY-060 | LEGACY_KEEP | M06 | fix_ai_edit_jobs.py 历史任务修复脚本 | NONE | 历史任务全部修复归档 + CHAIN 登记移除 |
| LEGACY-061 | COMPATIBILITY | PLATFORM | leads/tasks PG shadow 双轨对照工具组（11 脚本） | NONE（pilot 验证工具） | pilot 落地或废弃 + 依赖脚本/测试清理 |
| LEGACY-062 | ACTIVE | PLATFORM-RELEASE | 平台发布/构建资产审计确认组（compose/Dockerfile/env/pg-init/spec） | NONE（正式资产） | NONE |

## 六、执行边界确认

```text
BUSINESS_CODE_DELTA = 0（未修改任何业务/测试/迁移/路由/前端源码）
LEGACY_DELETE       = NOT EXECUTED（9 个 DELETE_CANDIDATE 仅登记，删除进入后续独立审批）
LEGACY_MIGRATION    = NOT EXECUTED（2 个 LEGACY_MIGRATE 仅登记迁移目标与条件）
PRODUCTION_CHANGE   = NOT EXECUTED
NEW_REGRESSION      = 0（无代码改动，无回归面）
```

## 七、文件清单

```text
MODIFIED_FILES =
  docs/architecture/LEGACY_REGISTER.md              （G1 15 项原位升级为 G2 唯一 SSOT，50 条记录 + 统计 + G1 修正清单）
  docs/architecture/legacy/G2_LEGACY_CONSOLIDATION_REPORT.md（本报告，新增）
  scripts/validate_g2_legacy_registry.py             （机器验收 validator，新增）
```

## 八、Git 边界

```text
COMMIT_SHA = 待提交（docs: 建立G2 Legacy分类总账）
GIT_STATUS = clean（提交后）
PUSH       = NOT EXECUTED
```

```text
G2_RESULT
= COMPLETE
```

**STOP。不得自动进入 G3 Seven-Module Verification。**
