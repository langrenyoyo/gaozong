# Legacy 登记簿（G2 唯一 SSOT）

> **版本**：G2（G2-LEGACY-CONSOLIDATION-1，BASE_SHA=f582740d611d6791106a3eddcbf86ae6358f331d）
> **前身**：G1 1A.5 定性登记簿（c67a52d 创建 / d924e01 修正，15 项 LEGACY-001~015），本文件已原位升级为 G2 唯一 Legacy Registry。
> **机器验收**：`python scripts/validate_g2_legacy_registry.py`（G2_VALIDATION=PASS 要求）。
> **性质**：只登记、不改代码、不删代码。分类与删除前置是给后续 G3/G4 及独立删除审批的现实地图。

## G2 五分类（冻结）

| 分类 | 含义 |
|---|---|
| ACTIVE | 看起来像旧代码/旧接口/旧路径，但审计后确认它仍是当前正式实现，不应继续被当作 Legacy 债务 |
| COMPATIBILITY | 为兼容旧 API、旧配置、旧数据、旧调用方或升级路径而主动保留；当前仍有明确兼容职责 |
| LEGACY_KEEP | 确属 Legacy，但当前有明确现实原因必须保留；暂无迁移/删除计划 |
| LEGACY_MIGRATE | 已确认应该迁往当前正式实现，但迁移尚未执行 |
| DELETE_CANDIDATE | 已有充分证据表明未来可以删除，但 G2 本身绝不执行删除 |

禁止 UNKNOWN / MAYBE / PENDING / TEMP / OLD 作为最终分类：`UNKNOWN_LEGACY = 0`。

## G1 标签 → G2 分类映射说明

G1 登记簿使用 ACTIVE / COMPAT / LEGACY / DEAD_CANDIDATE / UNKNOWN 五标签（Lifecycle 维度）；G2 改为上述五分类（审计结论维度）。每条记录保留 `g1_status` 追溯字段。

---

## LEGACY-001 leads_internal_webhook_fallback

- **name**: leads_internal_webhook_fallback
- **classification**: LEGACY_KEEP
- **owner**: M02
- **g1_status**: LEGACY
- **evidence**: `app/config.py:316` `LEADS_WEBHOOK_INTERNAL_ENABLED` 默认 false；`app/routers/integrations.py:38` import `packages/clients/leads_client.py`（LeadsClient）；`app/routers/integrations.py:453` 分支判断 internal 模式；`LEADS_WEBHOOK_FALLBACK_LOCAL`（config.py:317）默认 true；docker-compose.dev.yml 9202 leads-service 能力中心仍存在
- **reason**: 历史架构中 9000 webhook 转发 9202 internal leads 服务；9000 本地直收（`_process_webhook_locally`）已是新主线，internal 模式保留为 dev 能力中心与回退路径
- **current_role**: env `LEADS_WEBHOOK_INTERNAL_ENABLED=true` 时 webhook 事件转发 9202；默认关闭，生产走本地直收
- **current_dependencies**: `app/routers/integrations.py`（webhook 分支）；`packages/clients/leads_client.py`；docker-compose.dev.yml 9202 服务；`LEADS_SERVICE_BASE_URL`/`LEADS_INTERNAL_TOKEN`/`LEADS_CLIENT_TIMEOUT_SECONDS`（config.py:318-320）；tests（test_douyin_webhook_internal_cutover.py、test_douyin_webhook_atomic_idempotency.py）
- **replacement**: 9000 本地直收（`_process_webhook_locally`）
- **deletion_condition**: 确认所有环境（含 staging）均用本地直收；9202 leads-service 确认无生产流量；`.env.*.example` 移除 `LEADS_WEBHOOK_INTERNAL_ENABLED`/`LEADS_SERVICE_BASE_URL`/`LEADS_INTERNAL_TOKEN` 变量；移除 `packages/clients/leads_client.py` 后无 import 残留
- **risk_if_removed**: 若仍有环境配置 internal 模式，webhook 事件将无法转发 9202（但生产已本地直收，风险低）
- **source_files**:
  - app/config.py
  - app/routers/integrations.py
  - packages/clients/leads_client.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-002 旧微信自动检测调度器

- **name**: legacy_wechat_auto_detect_scheduler
- **classification**: LEGACY_KEEP
- **owner**: M04
- **g1_status**: LEGACY
- **evidence**: `app/config.py:379` `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT` 默认 "0"；`app/main.py:200-212` 受保护启动；`app/scheduler/wechat_auto_detect_scheduler.py:43`；`app/routers/wechat_auto_detect.py`；tests/test_p0_end_2a_legacy_scheduler_disable.py 验证默认禁用与 env=1 恢复
- **reason**: 旧链路为 9000 进程内定时轮询微信回复检测；新主线为 19000 Local Agent poll-and-detect；旧调度器保留为开发调试/回退
- **current_role**: env `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1` 时在 9000 进程内启动旧检测调度器；生产默认关闭
- **current_dependencies**: `app/main.py`（on_event startup 条件启动）；`app/routers/wechat_auto_detect.py` 路由；`.env.*.example` 模板含该变量；tests/test_p0_end_2a_legacy_scheduler_disable.py
- **replacement**: 19000 Local Agent（小高AI微信助手.exe）poll-and-detect
- **deletion_condition**: 确认 19000 poll-and-detect 在所有生产环境稳定运行；旧 scheduler/路由无其他调用方；`.env.*.example` 移除变量后经一个 release window 无回退需求
- **risk_if_removed**: 若 19000 不可用，失去回退能力（发送安全底线要求检测链路只读，删除前必须确认替代链路完整）
- **source_files**:
  - app/config.py
  - app/main.py
  - app/scheduler/wechat_auto_detect_scheduler.py
  - app/routers/wechat_auto_detect.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-003 douyinAPI 8081 demo 客户端

- **name**: douyin_api_8081_client
- **classification**: LEGACY_KEEP
- **owner**: M02
- **g1_status**: DEAD_CANDIDATE（G2 修正：存在 import 链，不能判 DELETE_CANDIDATE）
- **evidence**: `app/config.py:217` `DOUYIN_API_BASE_URL` 默认 `http://127.0.0.1:8081`；`app/integrations/douyin_api_client.py` 被 `app/services/douyin_sync_service.py:20` import（fetch_leads/DouyinApiError）；douyin_sync_service 被 `app/routers/integrations.py` sync-leads 路由使用（LEGACY-005）；tests/test_douyin_sync.py 引用 DouyinApiError
- **reason**: douyinAPI（8081）定位 demo/参考实现/历史沉淀，非生产依赖；但 client 代码仍被 sync-leads 旧拉取链路 import，不是"无调用方"死代码
- **current_role**: sync-leads 旧拉取链路的 HTTP 客户端；生产默认不调用 8081
- **current_dependencies**: `app/services/douyin_sync_service.py`（import）；`app/routers/integrations.py` sync-leads 路由；tests/test_douyin_sync.py
- **replacement**: 9000 直收 webhook + OpenAPI 签名调用（DY_OPENAPI_BASE_URL）
- **deletion_condition**: sync-leads 链路（LEGACY-005）整体移除后，grep 确认无 `douyin_api_client` import 残留；移除 config.py `DOUYIN_API_BASE_URL` 默认值与 client 文件
- **risk_if_removed**: 若 sync-leads preview 功能仍需 8081 demo 数据，移除后该功能不可用（当前生产不依赖）
- **source_files**:
  - app/integrations/douyin_api_client.py
  - app/config.py
  - app/services/douyin_sync_service.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-004 callback.misanduo.com 硬编码域名

- **name**: misanduo_hardcoded_domains
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: COMPAT
- **evidence**: `app/routers/integrations.py:877`（GMP 已配置回调地址注释）；`app/routers/douyin_live_check.py:56` `AUTH_REDIRECT_DEFAULT_ORIGIN = "https://douyinapi.misanduo.com"`；`app/local_agent_main.py:121` server-url 默认 `https://douyinapi.misanduo.com`；`app/local_agent_exe_entry.py:85` help 文本
- **reason**: 生产 webhook/任务回写域名（callback.misanduo.com）与 OAuth 前端回跳默认 origin（douyinapi.misanduo.com）是 GMP 已配置的现网地址
- **current_role**: 生产 webhook 回调地址与 OAuth 回跳默认 origin；Local Agent server-url 默认值
- **current_dependencies**: GMP 回调配置；宝塔反代；`DY_AUTH_REDIRECT_URL`（生产显式配置覆盖）；19000 部署
- **replacement**: NONE（当前生产地址，GMP 已配置）
- **deletion_condition**: 域名迁移到环境变量配置（非硬编码）后：GMP 回调地址、OAuth redirect、Local Agent server-url 均改读 env；宝塔反代配置同步更新
- **risk_if_removed**: 硬编码移除但 env 未配置时 OAuth 回跳与 webhook 回调断链
- **source_files**:
  - app/routers/integrations.py
  - app/routers/douyin_live_check.py
  - app/local_agent_main.py
  - app/local_agent_exe_entry.py
- **related_module**: PLATFORM（M02/M04 边界）
- **status**: VERIFIED

---

## LEGACY-005 sync-leads 旧拉取链路

- **name**: sync_leads_legacy_pull
- **classification**: LEGACY_KEEP
- **owner**: M02
- **g1_status**: LEGACY
- **evidence**: `app/routers/integrations.py:595` `@router.post("/sync-leads")`；`app/services/douyin_sync_service.py:142` preview_sync_leads；`app/routers/integrations.py:605-614` auto_notify=true 抛 `LEGACY_AUTO_NOTIFY_DISABLED`；tests/test_p8_3_auto_notify.py / test_phase7_fix2_dispatch_trust_boundary.py 验证禁用行为
- **reason**: 从 douyinAPI 8081 主动拉取线索的旧链路；webhook 直收已是新主线；路由保留（preview 仍可用），auto_notify 显式禁用
- **current_role**: sync-leads 路由（preview-only）；auto_notify 链路硬禁用（400 LEGACY_AUTO_NOTIFY_DISABLED）
- **current_dependencies**: `app/services/douyin_sync_service.py`；`app/integrations/douyin_api_client.py`；`DOUYIN_API_BASE_URL`/`DOUYIN_SYNC_DEFAULT_LIMIT`（config.py:217-219）；**前端仍在调用**：`frontend/src/features/leads/pages/LeadsManagement.tsx:1350,1366` syncDouyinLeads({dryRun:true/false})、`frontend/src/api/integrations.ts:24-32` POST /integrations/douyin/sync-leads；tests（test_p8_3_auto_notify.py、test_p0_5a_task_creation_flow.py）
- **replacement**: 9000 直收 webhook（webhook 直收→入库→分配）
- **deletion_condition**: 前端 LeadsManagement.tsx 移除 syncDouyinLeads 调用（handleSyncPreview/handleSyncConfirm）且确认无其他调用方后；生产日志一个 release window 无 /integrations/douyin/sync-leads 调用；移除路由 + douyin_sync_service + douyin_api_client
- **risk_if_removed**: 若仍有外部工具调用 sync-leads preview，移除后 404（非生产主线）
- **source_files**:
  - app/routers/integrations.py
  - app/services/douyin_sync_service.py
  - app/integrations/douyin_api_client.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-006 兼容 webhook 旧路径 /webhook/douyin

- **name**: legacy_webhook_router
- **classification**: COMPATIBILITY
- **owner**: M02
- **g1_status**: COMPAT
- **evidence**: `app/routers/integrations.py:44-45` `legacy_webhook_router = APIRouter(prefix="/webhook")`；`:867` `@legacy_webhook_router.post("/douyin")`；`app/main.py:130` include_router；与正式入口共享 `_handle_douyin_webhook`；tests/test_douyin_webhook.py（test_webhook_legacy_and_main_path_idempotent_no_auth 等）验证两路径幂等一致
- **reason**: GMP 已配置的回调地址 `callback.misanduo.com/webhook/douyin` 宝塔反代到 9000，为兼容旧回调路径主动保留
- **current_role**: 抖音 webhook 兼容回调路径（与正式入口行为一致）
- **current_dependencies**: GMP 回调配置；宝塔反代；tests/test_douyin_webhook.py
- **replacement**: 正式入口 `POST /integrations/douyin/webhook`
- **deletion_condition**: GMP 回调地址改为 `/integrations/douyin/webhook` 正式路径；宝塔反代配置同步；确认无遗漏旧回调配置后经一个 release window
- **risk_if_removed**: GMP 仍指向旧路径时 webhook 事件断收（线索/自动回复全断）
- **source_files**:
  - app/routers/integrations.py
  - app/main.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-007 LEGACY_WECHAT_DEBUG_ENDPOINTS

- **name**: legacy_wechat_debug_endpoints
- **classification**: LEGACY_KEEP
- **owner**: M04
- **g1_status**: LEGACY
- **evidence**: `app/config.py:329-331` `LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED` 默认 false；`app/routers/replies.py:28,33,36,37,73,183,207,419,567` `_require_legacy_wechat_debug_enabled` 守卫；tests/test_legacy_wechat_debug_lockdown.py（production 始终关闭、agent-write-back 不受锁定）
- **reason**: 旧微信 debug 端点群（replies.py 内多个调试接口），本地排查时显式开启；production 始终关闭
- **current_role**: env 开启时提供旧微信调试端点（本地排查用）
- **current_dependencies**: `app/routers/replies.py`；`.env.*.example` 模板变量；tests/test_legacy_wechat_debug_lockdown.py
- **replacement**: 19000 Local Agent 诊断端点（/agent/wechat/search-debug 等）
- **deletion_condition**: 确认 19000 诊断端点覆盖所有旧 debug 场景；确认无生产环境依赖；`.env.*.example` 移除变量
- **risk_if_removed**: 本地排查微信问题时失去旧调试入口（19000 已覆盖大部分）
- **source_files**:
  - app/config.py
  - app/routers/replies.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-008 DY_BASE_URL_LEGACY

- **name**: dy_base_url_legacy_fallback
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: COMPAT
- **evidence**: `app/config.py:228-229` `DY_BASE_URL_LEGACY`/`DY_BASE_URL`；`app/services/douyin_openapi_client.py:57-89` legacy_base_url_used/present 回退逻辑；tests/test_douyin_live_check.py（test_openapi_endpoint_config_falls_back_to_legacy_base_url_when_new_config_missing 等）
- **reason**: OpenAPI base_url 配置兼容旧 `DY_BASE_URL` 环境变量，新配置 `DY_OPENAPI_BASE_URL`+`DY_OPENAPI_PREFIX` 缺失时回退
- **current_role**: config 层回退；legacy_base_url_used/present 调试字段
- **current_dependencies**: `app/services/douyin_openapi_client.py`；`app/services/douyin_live_check_service.py:294-295` 透传调试字段；tests/test_douyin_live_check.py
- **replacement**: `DY_OPENAPI_BASE_URL` + `DY_OPENAPI_PREFIX`（生产模板已固定）
- **deletion_condition**: 确认所有环境 `DY_OPENAPI_BASE_URL` 有值不走回退；移除 `DY_BASE_URL_LEGACY` 回退逻辑与调试字段后全量测试通过
- **risk_if_removed**: 若某环境仍只配 DY_BASE_URL，OpenAPI 调用断链
- **source_files**:
  - app/config.py
  - app/services/douyin_openapi_client.py
  - app/services/douyin_live_check_service.py
- **related_module**: PLATFORM（M01 边界）
- **status**: VERIFIED

---

## LEGACY-009 auth_mode="legacy" Local Agent 旧未认证回退

- **name**: local_agent_legacy_unauthenticated
- **classification**: COMPATIBILITY
- **owner**: M04
- **g1_status**: LEGACY
- **evidence**: `app/auth/local_agent_auth.py:62,67` auth_mode="legacy" 未认证回退；`app/config.py:324` `LOCAL_AGENT_AUTH_REQUIRED` 默认 false；`.env.production.example` 已设 `LOCAL_AGENT_AUTH_REQUIRED=true`；tests/test_local_agent_auth.py（test_compat_mode_without_token_allows_legacy_heartbeat_and_logs_warning）；Local Agent 设计文档明确分阶段兼容（默认不强制拦截无 token 的旧 19000 请求，避免现场 Agent 掉线）
- **reason**: 兼容旧 19000 现场 Agent 的分阶段鉴权过渡路径；正式方案是 `LOCAL_AGENT_AUTH_REQUIRED=true` + `LOCAL_AGENT_TOKENS`；生产模板已切正式鉴权，代码默认 false 为本地/过渡默认可达（fail-open，建议后续治理 fail-closed）
- **current_role**: LOCAL_AGENT_AUTH_REQUIRED=false 时 Local Agent 请求走未认证 legacy 模式并记录 warning；生产显式 true 时强制 token 鉴权
- **current_dependencies**: `app/local_agent_main.py`（19000 心跳/任务轮询）；`LOCAL_AGENT_AUTH_REQUIRED`/`LOCAL_AGENT_TOKENS`（config.py:324-325）；`.env.*.example` 模板；tests/test_local_agent_auth.py
- **replacement**: `LOCAL_AGENT_AUTH_REQUIRED=true` + `LOCAL_AGENT_TOKENS` 正式鉴权
- **deletion_condition**: 确认所有生产 Local Agent 部署均设 `LOCAL_AGENT_AUTH_REQUIRED=true`（生产模板已含）；本地/过渡联调无依赖未认证路径；移除 legacy 回退分支后全量测试通过
- **risk_if_removed**: 未升级 token 的现场 Agent 掉线（生产模板已 true，风险受控）
- **source_files**:
  - app/auth/local_agent_auth.py
  - app/config.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-010 legacy_foreground_ok/diag 微信前台旧诊断字段

- **name**: legacy_foreground_debug_fields
- **classification**: ACTIVE
- **owner**: M04
- **g1_status**: UNKNOWN（G2 已解决：确认仍是当前正式诊断输出的一部分）
- **evidence**: `app/wechat_ui/contact_searcher.py:2573-2648,3507-3508` legacy_foreground_ok/diag 参数与 debug dict 填充；`run_search_box_debug` 当前诊断链路正式返回这些字段；`app/local_agent_main.py` 诊断端点（/agent/wechat/foreground-debug、search-debug 等）返回 debug 字段；tests/test_p0_4a_local_agent.py:1048-1049,1151-1152,1559-1560 断言 `debug["legacy_foreground_ok"]`/`legacy_foreground_diag` 仍被返回
- **reason**: 微信前台置顶旧实现的诊断字段，虽然命名带 legacy_ 前缀，但审计确认它仍是当前诊断端点正式返回的字段（有真实运行时消费方：诊断端点 + 测试断言），不是已废弃残留——按 G2 规则归 ACTIVE（"看起来像旧代码但审计后确认是当前正式实现"）
- **current_role**: 前台诊断响应中的诊断字段（legacy_foreground_ok/diag），与 19000 新前台 guard 并存
- **current_dependencies**: `app/local_agent_main.py` 诊断端点（foreground-debug/click_debug）；tests/test_p0_4a_local_agent.py
- **replacement**: NONE（诊断字段，无正式替代；新前台 guard 是功能替代）
- **deletion_condition**: NONE（当前正式诊断输出；未来若 19000 前台 guard 完全替代旧 `_ensure_wechat_foreground` 且诊断端点不再返回，需独立评估后移除）
- **risk_if_removed**: 诊断能力降级（不影响发送主链路，但排障信息减少）
- **source_files**:
  - app/wechat_ui/contact_searcher.py
  - app/local_agent_main.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-011 token 计量 legacy_characters 兼容枚举

- **name**: legacy_characters_enum
- **classification**: COMPATIBILITY
- **owner**: M07
- **g1_status**: COMPAT
- **evidence**: `app/models.py:951` CheckConstraint 允许值 `('provider_tokens', 'estimated_tokens', 'legacy_characters')`；`app/schemas.py:1395-1401` Literal；`apps/compute/services.py:34,666`；tests/test_compute_service.py:419-429（test_record_usage_defaults_old_payload_to_legacy_characters）、test_compute_usage_measurement_postgres_contract.py、test_compute_usage_measurement_sqlite_migration.py
- **reason**: 历史 AI 消费按字符计量的兼容标记；新计量按供应商真实 Token（provider_tokens/estimated_tokens）
- **current_role**: 历史数据 `usage_measurement_method=legacy_characters` 的兼容枚举值；旧 payload 默认回退 legacy_characters
- **current_dependencies**: `app/models.py` CheckConstraint；`app/schemas.py` Literal；`apps/compute/services.py`；迁移 0033（compute_usage_measurement）；tests（test_compute_service.py 等）
- **replacement**: provider_tokens / estimated_tokens（真实 Token 计量）
- **deletion_condition**: 历史 `legacy_characters` 记录全部迁移或归档；CheckConstraint 与 Literal 移除该值；确认无历史数据查询依赖（一个 release window 无 legacy_characters 写入）
- **risk_if_removed**: 历史消费记录读取/展示缺值（枚举约束校验失败）
- **source_files**:
  - app/models.py
  - app/schemas.py
  - apps/compute/services.py
- **related_module**: M07
- **status**: VERIFIED

---

## LEGACY-012 算力 service 兼容入口

- **name**: compute_service_compat_entry
- **classification**: COMPATIBILITY
- **owner**: M07
- **g1_status**: COMPAT
- **evidence**: `app/services/compute_service.py:1-4` 文档串（实现收敛到 apps.compute.services 的兼容 re-export）；`app/services/ai_edit_las_service.py:735` 调 `compute_service.record_usage`；DEPENDENCY_MATRIX E11（M06→M07 service call）；docs/architecture/modules/M07/CHAIN.md COMPAT-012
- **reason**: 历史调用方兼容入口；实际实现已迁移 `apps/compute/services/`；调用方仍走兼容入口
- **current_role**: compute 服务的 re-export 兼容入口（被 M06 等调用）
- **current_dependencies**: `app/services/ai_edit_las_service.py`（record_usage）；其他 compute 调用方；tests（test_compute_service.py 等）
- **replacement**: 直接 import `apps.compute.services`
- **deletion_condition**: 全部调用方改直接 import `apps.compute.services`；grep 确认无 `app.services.compute_service` import 残留；移除兼容入口文件
- **risk_if_removed**: 未迁移的调用方 ImportError（record_usage 计费中断）
- **source_files**:
  - app/services/compute_service.py
- **related_module**: M07
- **status**: VERIFIED

---

## LEGACY-013 一键过审 CANCELLED_BY_CUSTOMER

- **name**: ad_review_cancelled
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: DEAD_CANDIDATE
- **evidence**: `app/models.py:1432` AdReviewOAuthAccount / `:1451` AdReviewSuggestion / `:1475` AdReviewAdoptTask 三表；main.py 无 ad_review router 注册；无前端引用（grep 确认）；DEPENDENCY_MATRIX 无模块依赖 AdReview 表；2026-07-13 客户取消（CANCELLED_BY_CUSTOMER）
- **reason**: 一键过审被客户取消，不再是一期范围；代码保留不回退（不删除历史记录）
- **current_role**: 无（无路由/调度器激活，仅模型定义与历史数据表保留）
- **current_dependencies**: 无运行时依赖；历史数据（若有）与迁移链（SQLite 版本表）
- **replacement**: NONE（业务取消）
- **deletion_condition**: 确认无任何路由/前端/脚本引用 AdReview 三表；确认无历史数据恢复职责（或数据已归档）；移除三表 model + 迁移降级脚本；CLAUDE.md/AGENTS.md 同步移除"一键过审"条目（该步骤需单独删除审批任务执行）
- **risk_if_removed**: 历史数据丢失（若未归档）；ORM 引用的历史查询失败
- **source_files**:
  - app/models.py
- **related_module**: PLATFORM（业务域已取消）
- **status**: VERIFIED

---

## LEGACY-014 CONTACT_INVALID_FOLLOWUP_ENABLED CONFIG_BYPASS

- **name**: contact_invalid_followup_config_bypass
- **classification**: ACTIVE
- **owner**: M02
- **g1_status**: ACTIVE（quality_flags=CONFIG_BYPASS / CONFIG_DRIFT）
- **evidence**: `app/main.py:236` `os.environ.get("CONTACT_INVALID_FOLLOWUP_ENABLED", "false")` 直接读 env 未进 config.py；`app/services/contact_invalid_followup_service.py:46,130`；RUNTIME_ENTRYPOINTS 环境变量表（CONFIG_BYPASS / CONFIG_DRIFT 标注）
- **reason**: 空号追问功能是当前主线（M01/M02 shared worker），但配置方式绕过 config.py——这是质量标签（CONFIG_BYPASS），不是 lifecycle 问题
- **current_role**: 空号追问调度器开关（env 控制，默认关）
- **current_dependencies**: `app/main.py`（startup 条件启动）；`app/services/contact_invalid_followup_service.py`；`CONTACT_INVALID_FOLLOWUP_ENABLED` env
- **replacement**: NONE（功能保留；配置方式需治理为 config.py 统一读取）
- **deletion_condition**: NONE（不删功能；CONFIG_DRIFT 治理为 config.py 统一读取后关闭 quality_flags，非本阶段）
- **risk_if_removed**: 空号追问功能中断（不删除功能，仅登记）
- **source_files**:
  - app/main.py
  - app/services/contact_invalid_followup_service.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-015 @app.on_event 非 lifespan TECH_DEBT

- **name**: app_on_event_startup_shutdown
- **classification**: ACTIVE
- **owner**: PLATFORM
- **g1_status**: ACTIVE（quality_flags=TECH_DEBT）
- **evidence**: `app/main.py:171` `@app.on_event("startup")`；`app/main.py:240` `@app.on_event("shutdown")`；RUNTIME_ENTRYPOINTS 六、Startup Hook（10 个启动项 + 8 个关闭项均挂在此）；SYSTEM_MAP.md:69 曾误称 lifespan（G1 已记录文档 drift）
- **reason**: FastAPI 已废弃的 startup/shutdown API，但当前仍是全部调度器/启动项的实际挂载点——这是 TECH_DEBT 质量标签，不是可删除 Legacy
- **current_role**: 9000 启动/关闭钩子（调度器、outbox、回访恢复、hotkey、overlay 等全部依赖）
- **current_dependencies**: `app/main.py`；全部 scheduler 与启动项（check/daily_report/wechat_auto_detect/outbox/return_visit/contact_invalid_followup/reconcile/hotkey/overlay）
- **replacement**: lifespan / asynccontextmanager（FastAPI 推荐）
- **deletion_condition**: NONE（TECH_DEBT 迁移到 lifespan 后本登记项关闭；迁移需独立任务，非本阶段）
- **risk_if_removed**: 启动/关闭逻辑丢失导致调度器不启动
- **source_files**:
  - app/main.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-016 前端 legacy 路由重定向层（22 条）

- **name**: frontend_legacy_route_redirects
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: ACTIVE（routes.ts 机制本身 ACTIVE；重定向为 BC-08 兼容层）
- **evidence**: `frontend/src/features/routes.ts:18-40` 22 条 legacyRouteRedirects；`frontend/src/App.tsx:163-166,184-190,755-757` LegacyRedirect 渲染与 canAccessPath 递归校验；`features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx:236` 生成 `/douyin-ai-cs?${params}` href 依赖重定向；tests/test_frontend_capability_navigation.py:27-34 强制 6 条；docs/ai/05_PROJECT_CONTEXT.md:331,345 文档契约
- **reason**: 历史菜单/书签/页面迁移的 URL 兼容层（BC-08）：`/douyin-ai-cs*`、`/leads/list|board|detail`、`/ai-agent`、`/compute`、`/knowledge-*` 等旧路径 → 新路径；仍有代码内活引用与旧书签用户
- **current_role**: 旧 URL 前端重定向 + 权限递归校验（无对应后端旧路由残留）
- **current_dependencies**: `App.tsx`（渲染+鉴权）；`features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx:236`；tests/test_frontend_capability_navigation.py；docs/ai/05_PROJECT_CONTEXT.md 契约
- **replacement**: NONE（新路由体系）
- **deletion_condition**: ① 代码内引用清零（先改 DouyinAutoReplyRunsPage.tsx:236）；② 更新 tests/test_frontend_capability_navigation.py 断言；③ 生产访问日志确认旧路径连续两个 release window 零命中（需生产侧确认，本审计只读无法验证）
- **risk_if_removed**: 高——旧书签/旧菜单用户直接 404 落回 defaultPath，且 6 条被测试强制
- **source_files**:
  - frontend/src/features/routes.ts
  - frontend/src/App.tsx
  - frontend/src/features/types.ts
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-017 前端权限码别名（legacyPermissionAliases）

- **name**: frontend_legacy_permission_aliases
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: ACTIVE（capabilities.ts 机制 ACTIVE）
- **evidence**: `frontend/src/features/capabilities.ts:20-22` `[PERMISSIONS.agent]: ["auto_wechat:wechat_assistant", "auto_wechat:wechat_agent"]`；消费点 `hasPermission`（capabilities.ts:133）；`app/auth/newcar_client.py:359-360` dev mock 仍签发旧码；tests/test_auth_context.py:220 使用旧码；docs/ai/08_newcar/P1_AUTH_PERMISSION_ROUTE_MATRIX.md:40、P1_NEWCAR_PERMISSION_CODES_ALIGNMENT.md:80-83,241-246（NewCar 是否按新语义返回旧码未取得真实列表）
- **reason**: 权限码演进期（agent 语义拆分）的历史别名兼容，等待 NewCar 上游权限字典收口；桌面 exe 设计文档（docs/superpowers/specs/2026-07-18-desktop-client-exe-design.md:383）要求精确匹配正式码，alias 仅为浏览器 UI 兼容
- **current_role**: 让持有旧权限码（auto_wechat:wechat_assistant / auto_wechat:wechat_agent）的历史商户仍可进入微信助手/智能体
- **current_dependencies**: `hasPermission`/`hasAnyPermission`（capabilities.ts:133,140）；App.tsx/SideNav 权限门禁；app/auth/newcar_client.py mock 签发
- **replacement**: NONE（正式码 `auto_wechat:agent`）
- **deletion_condition**: NewCarProject 确认永不签发两旧码（含历史商户存量权限）后移除；同步后端 mock 与测试
- **risk_if_removed**: 高——历史商户若仍持旧码将失去微信助手/智能体入口
- **source_files**:
  - frontend/src/features/capabilities.ts
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-018 前端旧路径 re-export shim 群（components/pages 死 shim）

- **name**: frontend_reexport_shim_group
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: G1_COMPAT_TRIO=COMPAT；其余 ACTIVE（G1 status drift，见 G2 报告）
- **evidence**: 全部为单行 `export { default } from "../features/..."` 或 `export * from "../features/..."`；全 frontend/src 零 importers；真实调用方全部直连 features 路径（如 `pages/Index.tsx:30-43`）；tests/ 无引用（成员文件分属 M01/M02/M04/M05/M07，组级治理归 PLATFORM）
- **reason**: features 化重构后遗留的旧导入路径兼容垫片，重构后调用方全部改为 features 路径，shim 失去消费者
- **current_role**: 无（纯 re-export 转发，零消费）
- **current_dependencies**: 无（零 importers；tests 零依赖）
- **replacement**: NONE（真实实现位于 features/ 下）
- **deletion_condition**: 已满足（零引用 + 无路由 + 测试零依赖）；删除前再确认无旧构建入口/外部脚本引用即可进入删除审批
- **risk_if_removed**: 极低（仅影响不存在的旧 import 路径）
- **source_files**:
  - frontend/src/components/ChatPanel.tsx
  - frontend/src/components/ContactInfo.tsx
  - frontend/src/components/ContactList.tsx
  - frontend/src/components/WechatTaskPanel.tsx
  - frontend/src/components/LocalWechatAgentTestPanel.tsx
  - frontend/src/components/douyin-ai-cs/ReplyDecisionPanel.tsx
  - frontend/src/pages/AiReplyDecisionLogsPage.tsx
  - frontend/src/pages/DailyReports.tsx
  - frontend/src/pages/DouyinAutoReplyRunsPage.tsx
  - frontend/src/pages/DouyinAiCsWorkbenchPage.tsx
  - frontend/src/pages/DouyinAutoReplySettingsPage.tsx
  - frontend/src/pages/ComputeCenter.tsx
  - frontend/src/pages/DouyinLiveCheckPage.tsx
  - frontend/src/pages/LasRemixWorkbench.tsx
  - frontend/src/pages/LeadsManagement.tsx
  - frontend/src/pages/LeadsModulePage.tsx
  - frontend/src/pages/SuperComputeConfig.tsx
  - frontend/src/pages/SuperMerchantAgent.tsx
  - frontend/src/pages/WebhookEventsPage.tsx
  - frontend/src/pages/WechatAgent.tsx
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-019 前端死页面/死组件群（含不可达渲染分支）

- **name**: frontend_dead_pages_group
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: ACTIVE（G1 status drift；其中 LEADS_CHAT_TRIO 由 G2 单独登记为 LEGACY-020）
- **evidence**: 全 frontend/src 零渲染点或仅被死 shim 引用；无路由注册（capabilityRoutes/adminRoutes 无对应 navId）；功能已被替代（成员文件分属 M01/M02/M03/M04/M05/M07，组级治理归 PLATFORM）：WebhookEventsPage 被 /leads 收敛取代、DouyinAutoReplySettingsPage/DouyinLiveCheckPage 被工作台 ModuleTabs 取代、ReplyDecisionPanel 被工作台内联实现取代、WechatTaskPanel 被 WechatAgent tasks tab 取代、SuperMerchantManagement/SuperAdminAccounts 被 NewCarProject 上游接管（App.tsx:47 /admin/newcar-owned 占位）、NotFound.tsx 被 App.tsx:758 `path="*"` Navigate 兜底取代、MaterialLibrary/SuperFollowUpPrompts 占位页无真实功能且无路由
- **reason**: 早期页面/组件被新形态（表格页/工作台 tab/上游系统/兜底路由）取代后遗留
- **current_role**: 无（无渲染点、无路由注册）
- **current_dependencies**: 仅 tests/test_frontend_capability_navigation.py 对部分文件做读文件断言（WECHAT_TASK_PANEL 断言含 fetchBrowserPendingWechatTasks；删除前须同步更新测试）
- **replacement**: NONE（或未来按真实需求重建于 features/）
- **deletion_condition**: 已满足（零引用 + 无路由注册）；3 个受测试断言约束的（WechatTaskPanel、navigation 占位、api/douyinCs shim）删除前先更新 tests/test_frontend_capability_navigation.py 断言
- **risk_if_removed**: 低（上游已接管/无入口；LeadsModulePage 等若未来复用需重建）
- **source_files**:
  - frontend/src/features/leads/pages/WebhookEventsPage.tsx
  - frontend/src/features/douyin-cs/pages/DouyinAutoReplySettingsPage.tsx
  - frontend/src/features/douyin-cs/pages/DouyinLiveCheckPage.tsx
  - frontend/src/features/douyin-cs/components/ReplyDecisionPanel.tsx
  - frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx
  - frontend/src/pages/SuperMerchantManagement.tsx
  - frontend/src/pages/SuperAdminAccounts.tsx
  - frontend/src/pages/NotFound.tsx
  - frontend/src/pages/MaterialLibrary.tsx
  - frontend/src/pages/SuperFollowUpPrompts.tsx
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-020 前端线索会话三组件（LEADS_CHAT_TRIO 不可达分支）

- **name**: frontend_leads_chat_trio_unreachable
- **classification**: LEGACY_MIGRATE
- **owner**: M02
- **g1_status**: ACTIVE
- **evidence**: `frontend/src/pages/Index.tsx:9-11` 静态 import ChatPanel/ContactInfo/ContactList；`Index.tsx:761,887-899` `isLeadConversationNav`（activeNav === "chat"）分支渲染；但 "chat" navId 无任何来源（capabilityRoutes/capabilityNavCenters/adminRoutes 均无 id="chat"；App.tsx:719-721 恒传 route.navId，Index.tsx:656 默认值 "chat" 永不生效）
- **reason**: 旧版单页会话 UI（线索对话三栏布局）被 /leads 表格页（LeadsModulePage/LeadsManagement）替代后，渲染分支未随路由重构移除
- **current_role**: 被静态 import 并打包，但运行分支不可达
- **current_dependencies**: `pages/Index.tsx`（import + 不可达分支）；构建产物（包体积）
- **replacement**: NONE（会话 UI 已被 LeadsModulePage/LeadsManagement 取代）
- **deletion_condition**: 移除 Index.tsx 中 isLeadConversationNav 分支（:761,:885-900）与静态 import 后，三组件即可删除
- **risk_if_removed**: 中——移除前必须确认无任何未来路由计划复用 "chat" 布局；保留现状无害但持续增加包体积
- **source_files**:
  - frontend/src/features/leads/components/ChatPanel.tsx
  - frontend/src/features/leads/components/ContactInfo.tsx
  - frontend/src/features/leads/components/ContactList.tsx
  - frontend/src/pages/Index.tsx
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-021 前端兼容占位层（navigation/api 目录 + 在用中转 shim）

- **name**: frontend_compat_placeholder_layer
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: ACTIVE
- **evidence**: `frontend/src/navigation/capabilityRoutes.ts:1-2` = `export * from "../features/routes"`；`navigation/capabilityNav.ts:1-2` = `export * from "../features/capabilities"`；`frontend/src/api/douyinCs.ts:1-2` = `export * from "../features/douyin-cs/api"`；全 frontend/src 零 importers；tests/test_frontend_capability_navigation.py:83-91 强制断言其"存在但不被消费"（`'./navigation/capabilityRoutes' not in app_source`、`'../navigation/capabilityNav' not in sidenav_source`、douyinCs.ts 内容为 re-export 且 features 版不含 /rag/ 与 createRagDocument/trainRag）；`pages/SuperAiReplyRecords.tsx` 为在用 3 行中转（Index.tsx:40 lazy import + :869 渲染，navId "ai-reply-records"）
- **reason**: 导航/API 迁移至 features/ 后的旧目录占位，测试锁定其"存在但不被消费"状态；SuperAiReplyRecords 是仍在用的超管 AI 回复记录中转层
- **current_role**: navigation/ 与 api/douyinCs.ts：无（兼容占位，防旧路径 import 断裂）；SuperAiReplyRecords：在用 re-export 中转
- **current_dependencies**: tests/test_frontend_capability_navigation.py（断言锁定）；pages/Index.tsx（SuperAiReplyRecords 唯一消费者）
- **replacement**: NONE（直接 import features 路径；SuperAiReplyRecords 可改 Index.tsx:40 直连 AiReplyDecisionLogsPage）
- **deletion_condition**: navigation/ 与 api/douyinCs.ts：先更新 tests/test_frontend_capability_navigation.py:83-91 断言，再删除；SuperAiReplyRecords：替换 Index.tsx:40 import 后删除
- **risk_if_removed**: 低（需同步改测试，否则 CI 失败）
- **source_files**:
  - frontend/src/navigation/capabilityRoutes.ts
  - frontend/src/navigation/capabilityNav.ts
  - frontend/src/api/douyinCs.ts
  - frontend/src/pages/SuperAiReplyRecords.tsx
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-022 前端假数据 mock 群（data/）

- **name**: frontend_mock_data_group
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: 未收录（G1 code_index.yaml 无此 7 组条目）
- **evidence**: `frontend/src/data/` 下 7 组假数据（chatData/leadsData/materialLibraryData/videoEditData/superConfigData/superComputeConfigData/wechatAgentData 及其 .d.ts）；全 frontend/src grep `from "…/data/…"` 零命中；真实 API 客户端（api/*、features/*/api）已接入
- **reason**: 早期假数据/mock，真实 API 接入后废弃
- **current_role**: 无
- **current_dependencies**: 无
- **replacement**: NONE（真实 API 客户端已存在）
- **deletion_condition**: 已满足（零引用）；G1 从未收录，删除不影响索引一致性
- **risk_if_removed**: 极低
- **source_files**:
  - frontend/src/data/chatData.ts
  - frontend/src/data/leadsData.ts
  - frontend/src/data/materialLibraryData.ts
  - frontend/src/data/videoEditData.ts
  - frontend/src/data/superConfigData.ts
  - frontend/src/data/superComputeConfigData.ts
  - frontend/src/data/wechatAgentData.ts
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-023 9100 回复内核 KernelMode 三模式（LEGACY/SHADOW/ENABLED）

- **name**: reply_kernel_three_modes
- **classification**: ACTIVE
- **owner**: M01
- **g1_status**: ACTIVE（G1 未将其列为 legacy 候选，G2 审计确认）
- **evidence**: `apps/xg_douyin_ai_cs/services/reply_kernel/mode.py:15-18` KernelMode 枚举 + `load_kernel_runtime_settings` 启动校验（9100 main.py:37-39 非法组合 raise）；`.env.*.example` 三模板均有 `DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED`/`DOUYIN_REPLY_KERNEL_SHADOW`；`_dispatch_reply_with_kernel_mode` 被 `build_reply_suggestion` 的 RAG 与直连两条路径调用，最终经 9000 `xg_douyin_ai_cs_client.py:65` 接入生产自动回复主链路；tests/test_reply_kernel.py、test_legacy_reply_features.py（P0-B 重构保护基线）
- **reason**: P0-B 统一回复内核的三模式运行开关——LEGACY=内核关闭直接走 `_build_llm_reply` 旧链、SHADOW=影子对比、ENABLED=正式启用；**生产当前就是 LEGACY 模式**（"legacy 链"`_build_llm_reply` 是当前生产正式实现），不是遗留债务
- **current_role**: 9100 自动回复主链路的模式分流机制（默认 LEGACY）
- **current_dependencies**: `apps/xg_douyin_ai_cs/main.py`（启动校验）；`reply_decision_service.py` `_dispatch_reply_with_kernel_mode`；9000 `xg_douyin_ai_cs_client.py`；env 模板；tests（test_reply_kernel.py、test_legacy_reply_features.py、test_p0a_false_contact_hotfix.py、test_p0_2_history_origin_contact_trust.py）
- **replacement**: NONE（当前正式机制）
- **deletion_condition**: NONE（当前正式实现；未来若 LEGACY 模式退役需独立评估）
- **risk_if_removed**: 自动回复主链路失效
- **source_files**:
  - apps/xg_douyin_ai_cs/services/reply_kernel/mode.py
  - apps/xg_douyin_ai_cs/services/reply_decision_service.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-024 9100 Schema 2.0 Legacy 字段兼容透传

- **name**: reply_schema_v2_legacy_field_passthrough
- **classification**: ACTIVE
- **owner**: M01
- **g1_status**: ACTIVE（G2 审计确认非 legacy 债务）
- **evidence**: `apps/xg_douyin_ai_cs/schemas.py:436` ContactAction.LEGACY_DELEGATED、`:491-540` ReplySuggestionResponseV2 含完整 Legacy 字段供 9000 兼容消费；`reply_decision_service.py:467-538` `_build_v2_response_from_legacy`、`:433-450` legacy_response/legacy_hard 参数；`routers/ai_reply.py:15-16` 联合响应模型（V2 优先匹配，Legacy 对象自动降级）；tests/test_reply_schema_v2.py、test_legacy_reply_features.py
- **reason**: P0-B Schema 2.0 升级时保留的字段级兼容——V2 响应必须携带全部 Legacy 字段，9000 兼容消费；`LEGACY_DELEGATED` 是 contact_action 的正式枚举值（policy 关闭时的委托语义）
- **current_role**: 9100→9000 响应契约的一部分（Schema 2.0 与 Legacy 并存消费）
- **current_dependencies**: 9000 `xg_douyin_ai_cs_client.py`（消费 Legacy 字段）；`reply_decision_service.py`；schemas.py；tests
- **replacement**: NONE（当前正式响应契约）
- **deletion_condition**: NONE（当前正式契约；未来 9000/9100 同步升级移除 Legacy 字段时独立评估）
- **risk_if_removed**: 9000 响应解析断裂（回复决策/自动回复主链路失败）
- **source_files**:
  - apps/xg_douyin_ai_cs/schemas.py
  - apps/xg_douyin_ai_cs/services/reply_decision_service.py
  - apps/xg_douyin_ai_cs/routers/ai_reply.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-025 P1 计费幂等 key None 兼容退路（9100 同族 4 处）

- **name**: compute_idempotency_none_compat_path
- **classification**: COMPATIBILITY
- **owner**: M01
- **g1_status**: ACTIVE（G2 审计登记）
- **evidence**: `apps/xg_douyin_ai_cs/rag/repository.py:490-507` legacy 兼容路径（run_id/attempt_count/preview_execution_id 全缺席 → key=None 不构造 key）；`reply_decision_service.py:3811`（run_id=None AND attempt_count=None AND preview_execution_id=None → legacy 兼容路径）；daily_report/return_visit/knowledge_training 同族 4 处；P1 Global Active None Audit-2（15 call-site 全分类，12 ACTIVE identity-bearing + 2 COMPATIBILITY legacy None 退路 + 1 DORMANT）；tests/test_rag_ingest_compute_idempotency_migration.py
- **reason**: P1 计费幂等改造保留的 None 兼容退路：当前全部 ACTIVE 调用方均携带 identity（run_id/attempt_count/preview_execution_id），None 路径无 ACTIVE 触发，但保留以兼容未迁移调用方
- **current_role**: 幂等 key 构造的 None 兼容退路（当前无 ACTIVE 触发）
- **current_dependencies**: 9100 计费上报链路（compute_usage_client）；9000 `/internal/compute/usage`（app/routers/compute.py）；P1 consumer 契约（0011/0014/0016/0025/0030/0031/0033/0034/0005 迁移）
- **replacement**: 显式 identity（run_id/attempt_count/preview_execution_id）
- **deletion_condition**: 确认全部 consumer 已迁移至显式 identity（P1 已 11/11 COMPLETE）；`idempotency_key=None` 路径无任何调用方；移除 None 退路分支后全量计费测试通过
- **risk_if_removed**: 未迁移调用方将裸扣费（重复计费风险）——删除前必须确认零 ACTIVE None 触发
- **source_files**:
  - apps/xg_douyin_ai_cs/rag/repository.py
  - apps/xg_douyin_ai_cs/services/reply_decision_service.py
- **related_module**: M07
- **status**: VERIFIED

---

## LEGACY-026 9100 dry-run 兼容调用名（run_ai_auto_reply_dry_run）

- **name**: ai_auto_reply_dry_run_compat
- **classification**: COMPATIBILITY
- **owner**: M01
- **g1_status**: ACTIVE
- **evidence**: `app/services/ai_auto_reply_dry_run_service.py:93` 兼容旧调用名（"兼容旧调用名；实际执行受控自动回复任务"）；webhook 链路已改 outbox（AI_AUTO_REPLY_OUTBOX_ENABLED）；当前仅测试使用
- **reason**: 受控 dry-run 自动回复的旧调用名兼容保留
- **current_role**: dry-run 兼容调用入口（当前仅测试消费）
- **current_dependencies**: tests（dry-run 相关测试）
- **replacement**: outbox 持久化任务链路
- **deletion_condition**: 确认无任何业务调用方使用 dry-run 旧调用名；移除后相关测试同步
- **risk_if_removed**: 低（仅测试使用；若未来需要 dry-run 能力需保留等价入口）
- **source_files**:
  - app/services/ai_auto_reply_dry_run_service.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-027 apps/agents+knowledge 旧子应用 service 实现层

- **name**: legacy_subapp_service_impl_m03
- **classification**: ACTIVE
- **owner**: M03
- **g1_status**: COMPAT（G1 全标 COMPAT 系过期标记，G2 修正：service 实现层实为 ACTIVE）
- **evidence**: `app/routers/capability_gateway.py:5-9` import `apps.agents.service.META`/`apps.knowledge.service.META`；`app/services/ai_agent_service.py:3`、`agent_knowledge_category_service.py:3` import `apps.agents.services`；`app/repositories/knowledge_categories_async_repository.py:8` import `apps.knowledge.services`；`app/services/knowledge_category_service.py:6` re-export `apps.knowledge.services`；tests（test_agents_app.py、test_knowledge_app.py 等）
- **reason**: 旧独立子应用的 service 实现层被 9000 正式代码 import，是当前正式实现（物理位置在 apps/，归属 M03）
- **current_role**: 9000 智能体/知识分类服务的正式实现层
- **current_dependencies**: capability_gateway、ai_agent_service、agent_knowledge_category_service、knowledge_category_service（re-export）、knowledge_categories_async_repository
- **replacement**: NONE（当前正式实现）
- **deletion_condition**: NONE（当前正式实现；未来若 9000 实现迁移到 app/ 内需独立评估）
- **risk_if_removed**: 9000 智能体/知识分类功能中断
- **source_files**:
  - apps/agents/service.py
  - apps/agents/services.py
  - apps/agents/schemas.py
  - apps/knowledge/service.py
  - apps/knowledge/services.py
- **related_module**: M03
- **status**: VERIFIED

---

## LEGACY-028 apps/agents+knowledge 旧子应用独立服务入口（dev 能力中心）

- **name**: legacy_subapp_dev_entry_m03
- **classification**: LEGACY_KEEP
- **owner**: M03
- **g1_status**: COMPAT
- **evidence**: `docker-compose.dev.yml:246,303` agents-service（9203）/knowledge-service（9206）dev 能力中心服务；`apps/agents/main.py`/`apps/knowledge/main.py` create_app 仅被 dev compose 与 tests（test_agents_app.py:28-29、test_knowledge_app.py:28-29）引用；docker-compose.yml（生产）不引用；RUNTIME_ENTRYPOINTS dev_only 标注
- **reason**: 独立子应用入口（main/router/dependencies）是 dev 能力中心形态（9201-9206），生产不运行；因 dev compose 与测试仍使用而保留
- **current_role**: dev 环境能力中心独立服务入口（9203/9206）
- **current_dependencies**: docker-compose.dev.yml；tests（test_agents_app.py、test_knowledge_app.py）
- **replacement**: 9000 统一服务（能力中心 dev 形态可整体退役）
- **deletion_condition**: dev 能力中心形态退役（dev compose 移除 9203/9206 服务）后，确认 create_app 无测试引用；移除入口文件
- **risk_if_removed**: dev 能力中心入口不可用（仅 dev）
- **source_files**:
  - apps/agents/main.py
  - apps/agents/router.py
  - apps/agents/routers.py
  - apps/agents/dependencies.py
  - apps/knowledge/main.py
  - apps/knowledge/router.py
  - apps/knowledge/routers.py
  - apps/knowledge/dependencies.py
  - apps/knowledge/schemas.py
- **related_module**: M03
- **status**: VERIFIED

---

## LEGACY-029 apps/leads 旧子应用 9202 兼容服务与 dev 入口

- **name**: legacy_subapp_leads_9202_m02
- **classification**: COMPATIBILITY
- **owner**: M02
- **g1_status**: COMPAT
- **evidence**: `apps/leads/services.py:16-17` import schemas+webhook_events、`:99-125` create_internal_webhook_event；`apps/leads/webhook_events.py:330-337` process_internal_webhook_event 委托 `app.integrations.douyin_webhook.process_webhook_event`（与 9000 共用处理核心，douyin_webhook_idempotency_service.py:3 明示"9000 和 9202 共用同一占位逻辑"；注意方向：9000→9202 走 HTTP 非 import）；调用链：`app/routers/integrations.py:566-569`（LEADS_WEBHOOK_INTERNAL_ENABLED=true）→ LeadsClient.from_env().create_internal_webhook_event（packages/clients/leads_client.py:38 默认 127.0.0.1:9202、:167-191）→ apps/leads/routers.py:33-42 → services.py:110；config.py:316-320；`.env.production.example:361-376` 文档化（9202 是唯一被生产配置模板引用的 920x）；docker-compose.dev.yml:229 leads-service（9202）；tests（test_douyin_webhook_atomic_idempotency.py、test_leads_internal_webhook_app.py、test_douyin_webhook_internal_cutover.py、test_leads_app.py、test_capability_service_boundaries.py:7）
- **reason**: env 开关可切换的 9202 internal webhook 兼容路径（cutover 未闭合）；leads service META 被 9000 生产消费（见 LEGACY-056），此处登记 9202 兼容服务层与独立服务入口
- **current_role**: 9202 线索 internal webhook 处理（复用 9000 核心）+ 9202 能力中心服务入口（/api/leads 业务 + /api/leads/internal/webhook-events）
- **current_dependencies**: integrations.py（LEADS_WEBHOOK_INTERNAL_ENABLED）；packages/clients/leads_client.py；docker-compose.dev.yml 9202；`.env.production.example` LEADS_* 变量；5 个测试文件；docs（PHASE_3E3C_WEBHOOK_INTERNAL_CUTOVER_PLAN.md、10_WEBHOOK_AUTH_MIGRATION.md）
- **replacement**: 9000 本地直收 `_process_webhook_locally`（LEADS_WEBHOOK_INTERNAL_ENABLED=false 默认路径）
- **deletion_condition**: 按 LEGACY-001 删除前置联动：① 确认所有环境（含 staging）均本地直收且 LEADS_WEBHOOK_INTERNAL_ENABLED 永不为 true；② 9202 确认无流量；③ 移除 .env.*.example 的 LEADS_* 变量并同步 config.py:314-320 与 integrations.py:566-569 分支；④ 迁移/删除相关测试；⑤ 同步 PHASE_3E3C 文档
- **risk_if_removed**: 若仍有环境开 internal 模式→webhook 处理失败（fallback 关闭时 503）；dev compose/测试破坏
- **source_files**:
  - apps/leads/services.py
  - apps/leads/schemas.py
  - apps/leads/webhook_events.py
  - apps/leads/main.py
  - apps/leads/router.py
  - apps/leads/routers.py
  - apps/leads/dependencies.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-030 apps/douyin_cs 旧子应用 dev 入口（9201）

- **name**: legacy_subapp_douyin_cs_entry_m01
- **classification**: LEGACY_KEEP
- **owner**: M01
- **g1_status**: COMPAT
- **evidence**: `docker-compose.dev.yml:208` douyin-cs-service（9201）；`apps/douyin_cs/main.py`/`router.py` create_app 仅被 dev compose 与 tests/test_capability_service_boundaries.py:6 引用；`apps/douyin_cs/router.py:1-5` 仅 create_capability_router(META)（无任何业务端点，纯健康检查骨架）；service META 被生产消费（见 LEGACY-057）；生产 compose/staging 均无 9201
- **reason**: 无业务端点的能力中心骨架，仅 dev compose 与边界测试引用；抖音AI客服真实业务在 9100/9000
- **current_role**: dev 9201 健康检查服务
- **current_dependencies**: docker-compose.dev.yml 9201；tests/test_capability_service_boundaries.py:6
- **replacement**: 9000（抖音AI客服真实业务在 9100/9000）
- **deletion_condition**: ① dev compose 移除 douyin-cs-service；② test_capability_service_boundaries.py:6 移除断言；③ G1 code_index 同步
- **risk_if_removed**: dev compose/测试破坏；生产无影响
- **source_files**:
  - apps/douyin_cs/main.py
  - apps/douyin_cs/router.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-031 apps/wechat_assistant 旧子应用 dev 入口（9204）

- **name**: legacy_subapp_wechat_assistant_entry_m04
- **classification**: LEGACY_KEEP
- **owner**: M04
- **g1_status**: COMPAT
- **evidence**: `docker-compose.dev.yml:265` wechat-assistant-service（9204）；`apps/wechat_assistant/main.py`/`router.py` create_app 仅被 dev compose 与 tests/test_capability_service_boundaries.py:9 引用；`apps/wechat_assistant/router.py:1-5` 仅 create_capability_router(META)（无业务端点）；service META 被生产消费（见 LEGACY-058）；旧自动化控制硬门禁已废止为真实发送 gate 体系（兼容字段保留，M04 CHAIN.md:56）
- **reason**: 无业务端点的能力中心骨架，仅 dev compose 与边界测试引用
- **current_role**: dev 9204 健康检查服务
- **current_dependencies**: docker-compose.dev.yml 9204；tests/test_capability_service_boundaries.py:9
- **replacement**: 19000 Local Agent / 9000 wechat_tasks 路由
- **deletion_condition**: ① dev compose 移除 wechat-assistant-service；② test_capability_service_boundaries.py:9 移除断言；③ G1 code_index 同步
- **risk_if_removed**: dev compose/测试破坏；生产无影响
- **source_files**:
  - apps/wechat_assistant/main.py
  - apps/wechat_assistant/router.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-056 apps/leads service META（能力网关生产消费）

- **name**: leads_subapp_service_meta
- **classification**: ACTIVE
- **owner**: M02
- **g1_status**: COMPAT（G1 漂移，应为 ACTIVE）
- **evidence**: `app/routers/capability_gateway.py:9` `from apps.leads.service import META`（9000 生产挂载 /api/leads/health）；`apps/leads/service.py:9` 副作用 import apps.leads.services（9202 链路）；`apps/leads/main.py`/`router.py` 消费 META
- **reason**: META 被能力网关生产路由消费（9000 启动期即 import，删除会破坏启动）——"看起来像旧子应用但审计后确认是当前正式实现的一部分"
- **current_role**: 9202 能力元信息 + 兼容导出
- **current_dependencies**: capability_gateway（生产路由）；leads/router.py；leads/main.py
- **replacement**: NONE（当前正式实现）
- **deletion_condition**: NONE（当前正式实现；capability_gateway META 机制迁移时独立评估）
- **risk_if_removed**: 9000 启动失败（capability_gateway import 链断裂）
- **source_files**:
  - apps/leads/service.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-057 apps/douyin_cs service META（能力网关生产消费）

- **name**: douyin_cs_subapp_service_meta
- **classification**: ACTIVE
- **owner**: M01
- **g1_status**: COMPAT（G1 漂移，应为 ACTIVE）
- **evidence**: `app/routers/capability_gateway.py:7` `from apps.douyin_cs.service import META`（9000 生产挂载 /api/douyin-cs/health）
- **reason**: META 被能力网关生产路由消费（9000 启动期即 import）
- **current_role**: 9201 能力元信息
- **current_dependencies**: capability_gateway（生产路由）；douyin_cs/router.py；douyin_cs/main.py
- **replacement**: NONE（当前正式实现）
- **deletion_condition**: NONE（当前正式实现；capability_gateway META 机制迁移时独立评估）
- **risk_if_removed**: 9000 启动失败
- **source_files**:
  - apps/douyin_cs/service.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-058 apps/wechat_assistant service META（能力网关生产消费）

- **name**: wechat_assistant_subapp_service_meta
- **classification**: ACTIVE
- **owner**: M04
- **g1_status**: COMPAT（G1 漂移，应为 ACTIVE）
- **evidence**: `app/routers/capability_gateway.py:10` `from apps.wechat_assistant.service import META`（9000 生产挂载 /api/wechat-assistant/health）
- **reason**: META 被能力网关生产路由消费（9000 启动期即 import）
- **current_role**: 9204 能力元信息
- **current_dependencies**: capability_gateway（生产路由）；wechat_assistant/router.py；wechat_assistant/main.py
- **replacement**: NONE（当前正式实现）
- **deletion_condition**: NONE（当前正式实现；capability_gateway META 机制迁移时独立评估）
- **risk_if_removed**: 9000 启动失败
- **source_files**:
  - apps/wechat_assistant/service.py
- **related_module**: M04
- **status**: VERIFIED

---

## LEGACY-032 apps 旧子应用单数 schema.py 死文件群

- **name**: legacy_subapp_singular_schema_group
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: COMPAT
- **evidence**: 5 个单数 schema.py（agents/schema.py、knowledge/schema.py、douyin_cs/schema.py、leads/schema.py、wechat_assistant/schema.py）全仓库精确 grep 零 import；与各子应用复数 schemas.py 并存（复数为在用）
- **reason**: 早期 schema 定义文件，被复数 schemas.py 取代后遗留
- **current_role**: 无（零 import）
- **current_dependencies**: 无
- **replacement**: 各子应用 schemas.py
- **deletion_condition**: 已满足（全仓库零 import）；删除前再确认无动态 import/外部脚本引用
- **risk_if_removed**: 极低
- **source_files**:
  - apps/agents/schema.py
  - apps/knowledge/schema.py
  - apps/douyin_cs/schema.py
  - apps/leads/schema.py
  - apps/wechat_assistant/schema.py
- **related_module**: PLATFORM（旧子应用治理）
- **status**: VERIFIED

---

## LEGACY-033 apps/leads webhook_events 内部重复实现死函数

- **name**: leads_webhook_events_dead_helpers
- **classification**: DELETE_CANDIDATE
- **owner**: M02
- **g1_status**: COMPAT
- **evidence**: `apps/leads/webhook_events.py` 仅 `process_internal_webhook_event` 被使用（apps/leads/services.py:17,110）；其余约 18 个辅助函数是 `app/integrations/douyin_webhook.py` 的重复实现且零调用（精确 grep 确认）
- **reason**: 9202 internal 服务早期独立实现 webhook 处理，9000 本地直收实现完成后成为重复死代码
- **current_role**: 无（死辅助函数）
- **current_dependencies**: 无（process_internal_webhook_event 仍被 services.py 使用，删除仅限辅助函数）
- **replacement**: app/integrations/douyin_webhook.py 实现
- **deletion_condition**: 已满足（辅助函数零调用）；删除前确认 process_internal_webhook_event 依赖不涉及被删函数
- **risk_if_removed**: 极低（函数级清理，不删文件）
- **source_files**:
  - apps/leads/webhook_events.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-034 SQLite 迁移轨道（migrate_sqlite.py + versions 0001~0045）

- **name**: sqlite_migration_track
- **classification**: ACTIVE
- **owner**: PLATFORM
- **g1_status**: LEGACY（G1 标 LEGACY 系过期标记，G2 修正：SQLite 仍是开发/过渡默认库）
- **evidence**: `docker-compose.dev.yml:50-70` auto-wechat-sqlite-migrate 服务执行 `python migrations/migrate_sqlite.py --db-path ... --startup`，9000 与 9201-9206 全部 depends_on 它；`app/config.py:166` `DATABASE_URL` 默认回退 `sqlite:///data/auto_wechat.db`；`app/db_readiness.py:106` 运行时 import 做 /ready 校验；docs/ai/05_PROJECT_CONTEXT.md:151,159 明示 SQLite 仍是默认运行库
- **reason**: SQLite 是当前开发/过渡默认库的正式迁移轨道（PostgreSQL 目标切换完成前继续使用）；G1 标 LEGACY 与事实冲突
- **current_role**: dev 环境 SQLite 库的正式迁移执行器（--startup）+ 迁移历史资产
- **current_dependencies**: docker-compose.dev.yml；app/config.py（DATABASE_URL 回退）；app/db_readiness.py；本地开发流程；tests（test_migrate_* 系列）
- **replacement**: PostgreSQL Alembic 轨道（migrations/postgres/）
- **deletion_condition**: PG cutover 全部完成（生产切换 + 开发默认库切 PG）后，SQLite 轨道进入退役评估；downgrades 与 versions 作为 DATABASE HISTORY 归档
- **risk_if_removed**: dev 环境 SQLite 库无法迁移/初始化
- **source_files**:
  - migrations/migrate_sqlite.py
  - migrations/versions/0001_prd_base_fields.sql
  - migrations/versions/0002_douyin_authorized_accounts.sql
  - migrations/versions/0003_douyin_webhook_event_parsed_fields.sql
  - migrations/versions/0004_douyin_private_message_sends.sql
  - migrations/versions/0005_douyin_message_resource_downloads.sql
  - migrations/versions/0006_douyin_image_uploads.sql
  - migrations/versions/0007_ai_agents.sql
  - migrations/versions/0008_douyin_account_agent_bindings.sql
  - migrations/versions/0009_lead_followup_records.sql
  - migrations/versions/0010_compute.sql
  - migrations/versions/0011_leads_session_isolation.sql
  - migrations/versions/0012_agent_knowledge_categories.sql
  - migrations/versions/0013_knowledge_categories.sql
  - migrations/versions/0014_ai_reply_decision_logs.sql
  - migrations/versions/0015_ai_auto_reply_runs.sql
  - migrations/versions/0016_douyin_account_autoreply_settings.sql
  - migrations/versions/0017_conversation_autopilot_state.sql
  - migrations/versions/0018_auto_reply_send_links.sql
  - migrations/versions/0019_autoreply_settings_whitelist_limits.sql
  - migrations/versions/0020_direct_llm_policy_json.sql
  - migrations/versions/0021_sales_staff_merchant_id.sql
  - migrations/versions/0022_douyin_conversation_read_states.sql
  - migrations/versions/0023_external_merchant_bindings.sql
  - migrations/versions/0024_douyin_oauth_states.sql
  - migrations/versions/0025_autoreply_admin_rollout.sql
  - migrations/versions/0026_external_merchant_bindings_unique_active_user.sql
  - migrations/versions/0027_xiaogao_phase1_core.sql
  - migrations/versions/0028_daily_automatic_reports.sql
  - migrations/versions/0029_daily_report_deliveries.sql
  - migrations/versions/0030_return_visit_phase9.sql
  - migrations/versions/0031_compute_billing.sql
  - migrations/versions/0032_ai_edit_local_mvp.sql
  - migrations/versions/0033_compute_usage_measurement.sql
  - migrations/versions/0034_ai_edit_material_library.sql
  - migrations/versions/0035_douyin_webhook_event_merchant_scope.sql
  - migrations/versions/0036_ai_auto_reply_outbox.sql
  - migrations/versions/0037_douyin_webhook_events_merchant_account_index.sql
  - migrations/versions/0038_autoreply_settings_manual_review_risk_flags.sql
  - migrations/versions/0039_ai_agents_store_config_fields.sql
  - migrations/versions/0040_autoreply_settings_allow_release_manual_required.sql
  - migrations/versions/0041_return_visit_dynamic_scene_and_followup.sql
  - migrations/versions/0042_ai_edit_las_fields.sql
  - migrations/versions/0043_compute_markup_ai_edit.sql
  - migrations/versions/0044_compute_markup_consumption_mode.sql
  - migrations/versions/0045_ai_edit_result_delivery.sql
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-035 SQLite 迁移降级脚本（downgrades/）

- **name**: sqlite_migration_downgrades
- **classification**: LEGACY_KEEP
- **owner**: PLATFORM
- **g1_status**: LEGACY
- **evidence**: `migrations/downgrades/0030~0034_*.sql` 5 个降级脚本；migrate_sqlite.py 无 `--downgrade` 参数支持（A3 审计确认）；仅测试与历史 plan 引用（DATABASE HISTORY）
- **reason**: 历史迁移降级脚本，属于数据库历史资产（DATABASE HISTORY），按 G2 规则不作为 DELETE_CANDIDATE
- **current_role**: 历史降级 SQL 资产（无运行时执行入口）
- **current_dependencies**: 无运行时依赖（历史追溯）
- **replacement**: NONE（历史资产）
- **deletion_condition**: SQLite 轨道退役（LEGACY-034 条件满足）时随版本历史归档；无归档需求时保持只读
- **risk_if_removed**: 历史降级能力丢失（SQLite 轨道退役前不得删）
- **source_files**:
  - migrations/downgrades/0030_return_visit_phase9.sql
  - migrations/downgrades/0031_compute_billing.sql
  - migrations/downgrades/0032_ai_edit_local_mvp.sql
  - migrations/downgrades/0033_compute_usage_measurement.sql
  - migrations/downgrades/0034_ai_edit_material_library.sql
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-036 SQLite→PG 一次性 cutover 脚本组

- **name**: sqlite_to_postgres_cutover_scripts
- **classification**: COMPATIBILITY
- **owner**: PLATFORM-RELEASE
- **g1_status**: LEGACY（G2 修正：cutover 未完成，脚本仍是一次性执行包的一部分）
- **evidence**: `docs/ai/05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md` 步骤 5-19 逐一调用 6 个 cutover 脚本；docs/ai/05_PROJECT_CONTEXT.md 6.3：9000 cutover `READY_FOR_BAOTA_EXECUTION` 待人工执行未切换、9100 待人工审批执行；scripts/production_pg_*.sh（10 个）为同一执行包；tests（test_migrate_*_sqlite_to_postgres.py 系列）
- **reason**: SQLite→PostgreSQL 生产切换的一次性迁移执行包，cutover 尚未完成，脚本仍有现实执行职责
- **current_role**: 生产 PG cutover 的一次性迁移工具（默认 dry-run，apply 有放行门）
- **current_dependencies**: 宝塔 runbook（人工执行）；production_pg_*.sh；docs/ai/05_acceptance/ 执行记录
- **replacement**: NONE（一次性工具；完成后即退役）
- **deletion_condition**: 生产 PG cutover 全部完成并验证后，脚本进入退役评估（不再有执行需求）；runbook 归档
- **risk_if_removed**: cutover 未完成时移除将无法执行生产切换
- **source_files**:
  - scripts/migrate_9000_sqlite_to_postgres_cutover.py
  - scripts/migrate_9100_sqlite_to_postgres_cutover.py
  - scripts/migrate_agents_accounts_core_sqlite_to_postgres.py
  - scripts/migrate_compute_core_sqlite_to_postgres.py
  - scripts/migrate_knowledge_categories_sqlite_to_postgres.py
  - scripts/migrate_leads_tasks_core_sqlite_to_postgres.py
  - scripts/production_pg_alembic_upgrade.sh
  - scripts/production_pg_backup.sh
  - scripts/production_pg_cutover_apply.sh
  - scripts/production_pg_cutover_dry_run.sh
  - scripts/production_pg_ensure_databases.sh
  - scripts/production_pg_preflight.sh
  - scripts/production_pg_rollback.sh
  - scripts/production_pg_smoke.sh
  - scripts/production_pg_sqlite_freeze_check.sh
  - scripts/production_pg_switch_and_verify.sh
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-037 历史运维/验证脚本组（scripts/ 残留）

- **name**: legacy_ops_scripts_group
- **classification**: LEGACY_KEEP
- **owner**: PLATFORM
- **g1_status**: ACTIVE/UNKNOWN（G1 对调试探针标 UNKNOWN）
- **evidence**: `scripts/verify_phase8_sqlite_backup_restore.py`、`scripts/p0_c_deployment_verify.py` 等运维/验证脚本仍登记在 RUNTIME_ENTRYPOINTS 七、CLI（smoke_test/maintenance）；`scripts/staging_milvus_smoke.sh` 无任何引用（无引用 ≠ 可删，缺删除证据）；`scripts/db_bl_2c_resume_snapshot.py` 等 DB_BL 快照工具为治理历史资产；`scripts/production_pg_backup.sh` 属 production_pg 执行包（LEGACY-036）
- **reason**: 历史运维/验证/调试脚本，部分仍有 runbook/治理文档引用；无确证 DELETE_CANDIDATE（按任务书"证据不足优先 LEGACY_KEEP"）
- **current_role**: 运维验证工具（smoke/maintenance/dev_tool），人工执行
- **current_dependencies**: RUNTIME_ENTRYPOINTS CLI 登记；治理文档（DB_BL 系列、验收记录）；tests（repair_douyin_cs_training_feedback_documents.py 有活跃测试 import）
- **replacement**: NONE（各类工具独立）
- **deletion_condition**: 逐脚本确认无 runbook/文档/测试引用后单独进入删除审批；staging_milvus_smoke.sh 需补充"无引用且无未来使用计划"证据
- **risk_if_removed**: 运维排查能力缺失（低，人工工具）
- **source_files**:
  - scripts/verify_phase8_sqlite_backup_restore.py
  - scripts/p0_c_deployment_verify.py
  - scripts/staging_milvus_smoke.sh
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-038 根 Dockerfile（DEPRECATED SQLite-only）

- **name**: root_dockerfile_deprecated
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM-RELEASE
- **g1_status**: ACTIVE（G1 status drift，RUNTIME_ENTRYPOINTS.md:290 已标 DEAD_CANDIDATE/unreachable）
- **evidence**: 根 Dockerfile 无任何 compose `build:` 引用（docker-compose.yml/dev/staging 全部 build Dockerfile.backend.dev / frontend.dev / frontend.prod）；`.env.production.example:73` 明示"无独立 Dockerfile"；Dockerfile 自身 :2-15 标 DEPRECATED、:54 APP_ENV=production 拒启动（SQLite-only）；RUNTIME_ENTRYPOINTS 八、Docker Command 标 unreachable/DEAD_CANDIDATE
- **reason**: 早期 SQLite-only 部署镜像配置，生产已改 compose + 专用 Dockerfile，根 Dockerfile 无引用且生产拒启动
- **current_role**: 无（无构建引用）
- **current_dependencies**: 无（compose 均不 build 它）
- **replacement**: Dockerfile.backend.dev / Dockerfile.frontend.dev / Dockerfile.frontend.prod
- **deletion_condition**: 已满足（无 build 引用 + 自身标 DEPRECATED + production 拒启动）；删除前 grep 确认无脚本/CI 引用
- **risk_if_removed**: 极低（若有旧脚本 build 它则会失败，正好暴露）
- **source_files**:
  - Dockerfile
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-039 ai_edit_worker.spec 引用残留（打包链路断链）

- **name**: ai_edit_worker_spec_missing_ref
- **classification**: LEGACY_MIGRATE
- **owner**: PLATFORM-RELEASE
- **g1_status**: ACTIVE（G2 审计发现）
- **evidence**: `ai_edit_worker.spec` 已在 0fbe0da（2026-07-31 LAS 重构，commit message 明示"worker 已删"）删除；但 `scripts/build_local_agent_exe.ps1`（默认 `-BuildWorker:$true`）+ `scripts/build_phase12_single_test_exe.ps1` + `scripts/build_ai_edit_worker_exe.ps1` 仍引用该 spec → **默认 Local Agent 打包会抛"Worker spec 缺失"失败**
- **reason**: LAS 重构删除旧 worker 后，打包脚本引用未同步清理——这是需要迁移修复的断链（非业务代码）
- **current_role**: 打包脚本中的失效引用（当前会导致默认打包失败）
- **current_dependencies**: build_local_agent_exe.ps1（默认路径）；build_phase12_single_test_exe.ps1；build_ai_edit_worker_exe.ps1
- **replacement**: 移除 worker 打包分支（LAS 方案无本地 worker）
- **deletion_condition**: 打包脚本移除/修正 ai_edit_worker.spec 引用（-BuildWorker 默认改 false 或删除分支）后验证 Local Agent 打包成功
- **risk_if_removed**: 不修则默认打包持续失败（迁移修复是正收益）
- **source_files**:
  - scripts/build_local_agent_exe.ps1
  - scripts/build_phase12_single_test_exe.ps1
  - scripts/build_ai_edit_worker_exe.ps1
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-040 Local Agent 打包 spec 资产组

- **name**: local_agent_spec_assets
- **classification**: LEGACY_KEEP
- **owner**: PLATFORM-RELEASE
- **g1_status**: ACTIVE（local_agent.spec）；其余未收录
- **evidence**: `local_agent.spec` 是唯一 tracked 正式打包配置（build_local_agent_exe.ps1 使用，ACTIVE）；`小高AI微信助手.spec` 未 tracked（.gitignore 忽略）被 local_agent.spec 替代；`local_agent_phase12_test.spec` + `phase12_test_launcher.spec` 是 Phase12 Task11 测试 exe 资产，仍被 tracked 脚本引用
- **reason**: PyInstaller 打包配置多版本并存：正式版 + 测试版 + 被替代版
- **current_role**: local_agent.spec=正式打包；phase12 两个 spec=测试 exe 打包；小高AI微信助手.spec=被替代（本地残留）
- **current_dependencies**: build_local_agent_exe.ps1；build_phase12_single_test_exe.ps1
- **replacement**: local_agent.spec（正式唯一）
- **deletion_condition**: 小高AI微信助手.spec：确认无打包流程引用后清理本地文件（未 tracked）；phase12 spec：Phase12 测试 exe 需求退役后移除脚本引用
- **risk_if_removed**: 测试 exe 打包不可用（Phase12 资产）
- **source_files**:
  - local_agent.spec
  - 小高AI微信助手.spec
  - local_agent_phase12_test.spec
  - phase12_test_launcher.spec
  - scripts/build_phase12_single_test_exe.ps1
  - scripts/smoke_phase12_task11_real.py
  - scripts/smoke_phase12_task11_delete_cors.py
  - scripts/smoke_phase12_task11_ocr.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-041 env 模板死配置（LAN_FRONTEND_HOST 等三键）

- **name**: env_template_dead_lan_keys
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM-RELEASE
- **g1_status**: ACTIVE
- **evidence**: `.env.lan.example` 中 `LAN_FRONTEND_HOST`/`LAN_API_HOST`/`LAN_AUTH_HOST` 三键：模板内地址全硬编码 IP（零插值）、全仓库零引用（app/config.py 无对应读取、ENV_VARIABLE_REFERENCE 无条目）
- **reason**: LAN 演示模板早期设计的宿主变量，实际使用硬编码 IP 后成为死配置
- **current_role**: 无（零引用零插值）
- **current_dependencies**: 无
- **replacement**: NONE（硬编码 IP 方案）
- **deletion_condition**: 已满足（零引用零插值）；删除前确认无外部部署脚本读取
- **risk_if_removed**: 极低
- **source_files**:
  - .env.lan.example
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-042 packages/clients 死客户端组（agents/compute/knowledge）

- **name**: packages_clients_dead_group
- **classification**: DELETE_CANDIDATE
- **owner**: PLATFORM
- **g1_status**: ACTIVE（G1 收录，owner 与审计一致）
- **evidence**: `packages/clients/agents_client.py`/`compute_client.py`/`knowledge_client.py` 生产代码（app/、apps/）零引用；仅单元测试引用（tests/test_agents_client.py、test_compute_client.py、test_knowledge_client.py）；`packages/clients/leads_client.py` 例外——被 app/routers/integrations.py:38 使用（LEGACY-001，ACTIVE）
- **reason**: 早期"能力中心 HTTP 客户端"设计，9201-9206 能力中心形态（LEGACY-028~031）未实际消费它们，仅测试保留
- **current_role**: 无（仅测试消费）
- **current_dependencies**: tests（test_agents_client.py、test_compute_client.py、test_knowledge_client.py）
- **replacement**: NONE（能力中心形态未实际使用；如需 HTTP 客户端按需重建）
- **deletion_condition**: 已满足（生产零引用）；删除时同步移除对应单元测试
- **risk_if_removed**: 低（仅测试依赖）
- **source_files**:
  - packages/clients/agents_client.py
  - packages/clients/compute_client.py
  - packages/clients/knowledge_client.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-043 legacy 兼容能力支持测试组（ACTIVE SUPPORT）

- **name**: legacy_compat_support_tests
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: TEST
- **evidence**: tests/test_legacy_reply_features.py（P0-B 重构保护基线，断言目标 `_build_llm_reply` Legacy 路径仍存在）、test_legacy_wechat_debug_lockdown.py（断言 `_require_legacy_wechat_debug_enabled` 守卫与 production 始终关闭）、test_p0_end_2a_legacy_scheduler_disable.py（断言 `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT` 默认禁用行为）、test_p8_3_auto_notify.py（LEGACY_AUTO_NOTIFY_DISABLED）、test_phase7_fix2_dispatch_trust_boundary.py（LEGACY_WECHAT_SEND_DISABLED）等——断言目标全部仍存在于当前代码
- **reason**: 兼容能力（LEGACY-002/005/007/009/023 等）仍活跃，其测试是 ACTIVE SUPPORT FOR COMPATIBILITY，按 G2 规则不得因测试目标 Legacy 而删
- **current_role**: 兼容/旧链路行为的回归保护测试
- **current_dependencies**: 对应兼容能力代码（LEGACY-002/005/007/009/023 等）
- **replacement**: NONE（随兼容能力生命周期走）
- **deletion_condition**: 对应兼容能力（LEGACY-002/005/007/009 等）退役删除时，测试同步移除
- **risk_if_removed**: 提前删除则兼容行为回归无保护
- **source_files**:
  - tests/test_legacy_reply_features.py
  - tests/test_legacy_wechat_debug_lockdown.py
  - tests/test_p0_end_2a_legacy_scheduler_disable.py
  - tests/test_p8_3_auto_notify.py
  - tests/test_phase7_fix2_dispatch_trust_boundary.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-044 app/integrations/douyin_webhook.py（webhook 直收主实现）

- **name**: douyin_webhook_main_impl
- **classification**: ACTIVE
- **owner**: M02
- **g1_status**: COMPAT（G1 status drift，G2 修正为 ACTIVE：该文件就是当前 webhook 直收主实现）
- **evidence**: `app/routers/integrations.py:15-19` import `process_webhook_event, verify_signature, WebhookSignatureError`；`:192-204` `_process_webhook_locally` 调用 `process_webhook_event(db, payload)`（当前本地主处理路径，默认走此分支）；`integrations.py:1043` `process_webhook_event` 完整主流程（原子占位→胜出者副作用→线索 upsert→派单→outbox enqueue→compute usage）；`app/routers/douyin_live_check.py:586` callback 转发复用；tests/test_douyin_webhook.py 全文件直接测 process_webhook_event
- **reason**: 9000 直收 webhook 的主实现（douyinAPI 8081 已被 webhook 直收取代）；G1 标 COMPAT 属于历史残余标记
- **current_role**: 抖音 GMP 私信事件直收的唯一主实现：验签、解析、幂等占位、线索 upsert、留资派单、人工接管后置、outbox 调度、算力上报
- **current_dependencies**: integrations.py 两个 webhook 入口；douyin_live_check.py callback 转发；outbox/contact_completion 等服务；tests/test_douyin_webhook.py（数百断言）
- **replacement**: NONE（本身就是正式实现）
- **deletion_condition**: NONE（当前正式实现）
- **risk_if_removed**: webhook 主链路整体瘫痪
- **source_files**:
  - app/integrations/douyin_webhook.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-045 app/services/knowledge_category_service.py re-export 兼容入口

- **name**: knowledge_category_service_reexport
- **classification**: COMPATIBILITY
- **owner**: M03
- **g1_status**: ACTIVE（G1 status drift，文件自身 docstring 声明兼容 re-export，G2 修正为 COMPATIBILITY）
- **evidence**: `app/services/knowledge_category_service.py:1-4` docstring"Phase 3-C 后真实实现迁入 apps.knowledge.services，旧导入路径保留 re-export"；`:6-22` 从 `apps.knowledge.services` re-export；调用方：app/routers/knowledge_categories.py 及其调用链、tests
- **reason**: 与 compute_service 同型的阶段迁移兼容入口（Phase 3-C 迁移残留）
- **current_role**: 知识库分类服务的兼容 re-export 入口
- **current_dependencies**: app/routers/knowledge_categories.py 调用链；tests
- **replacement**: 直接 import `apps.knowledge.services`
- **deletion_condition**: 所有调用方迁移到 apps.knowledge.services 后移除（与 LEGACY-012 compute_service 同型处理）
- **risk_if_removed**: 破坏知识分类 API 调用方
- **source_files**:
  - app/services/knowledge_category_service.py
- **related_module**: M03
- **status**: VERIFIED

---

## LEGACY-046 GET /leads 默认数组响应兼容

- **name**: leads_array_response_compat
- **classification**: COMPATIBILITY
- **owner**: M02
- **g1_status**: ACTIVE
- **evidence**: `app/routers/leads.py:41` `response_model=list[LeadOut] | LeadListResponse`；`:53` 注释"默认返回数组以兼容旧前端"；`:84-95` 仅 `response_format=="page"` 时返回分页对象；前端 `frontend/src/api/leads.ts:24-27` fetchLeads 用数组、`:30-37` fetchLeadsPage 用 page；`frontend/src/pages/Index.tsx:795` 仍调 fetchLeads()（数组）；`features/leads/pages/LeadsManagement.tsx:1179` 用 fetchLeadsPage（page）
- **reason**: 新前端分页格式已通过 response_format=page 提供，数组返回保留给旧前端（Index.tsx:795 仍在使用数组格式）
- **current_role**: GET /leads 默认返回数组（旧前端兼容），page 参数返回分页（新前端）
- **current_dependencies**: 前端 Index.tsx:795（数组）、LeadsManagement.tsx:1179（page）；tests（test_leads_management.py 等）
- **replacement**: 分页格式（response_format=page）为正式格式
- **deletion_condition**: 前端 Index.tsx:795 fetchLeads（数组路径）迁移到 fetchLeadsPage 后，将默认返回改为分页并移除数组兼容分支
- **risk_if_removed**: 旧前端页面（Index.tsx 线索模块）解析失败
- **source_files**:
  - app/routers/leads.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-047 lead_notifications 旧直发入口 410 封堵

- **name**: lead_notifications_legacy_send_gate
- **classification**: LEGACY_KEEP
- **owner**: M02
- **g1_status**: ACTIVE（runtime_role=WINDOWS_ONLY）
- **evidence**: `app/routers/lead_notifications.py:97-106` `send_pending_assigned_disabled` → 410 `LEGACY_WECHAT_SEND_DISABLED`（"旧批量发送入口已停用，请通过微信任务队列受控链路发送"）；`:72-94` /open-chat 调试搜索保留；docstring"旧 UI 直发入口已停用"；main.py:169 注册（Windows 平台）；tests/test_lead_notifications.py:47、test_phase7_fix2_dispatch_trust_boundary.py:184,194、test_p8_3_auto_notify.py:64-82 断言 410；正式发送链路为 lead_notification_actions.py /send-to-staff + wechat_task_service
- **reason**: Phase 7-FIX2 封堵旧直发入口：旧 /send-pending-assigned 直发微信的链路被 410 冻结，正式发送迁移到 WechatTask 队列受控链路
- **current_role**: 410 封堵旧入口（对旧调用方显式报 LEGACY_WECHAT_SEND_DISABLED）+ 保留 /open-chat 调试搜索
- **current_dependencies**: main.py:169（Windows 平台注册）；tests 三个文件断言 410；无前端调用本文件端点
- **replacement**: lead_notification_actions.py /send-to-staff + wechat_task_service 任务队列
- **deletion_condition**: 确认旧客户端/脚本不再请求 /send-pending-assigned（410 命中监控归零）且 /open-chat 调试被 19000 能力替代后，可删 410 端点与 open-chat
- **risk_if_removed**: 旧客户端静默失败（无 410 提示）；调试搜索能力丢失
- **source_files**:
  - app/routers/lead_notifications.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-048 线索展示旧字段兼容读取（raw_data.contact_extract/customer_contact）

- **name**: lead_display_legacy_field_compat
- **classification**: COMPATIBILITY
- **owner**: M02
- **g1_status**: ACTIVE
- **evidence**: `app/services/lead_management_service.py:122-131` `_contact_values`："展示口径：在权威列基础上兼容旧 raw_data.contact_extract 与 customer_contact"；`:178-190` `_lead_contact_payload` 同样 fallback 到旧字段；`:113-119` `_authoritative_contact_values`（新权威口径：extracted_phone/wechat/all_extracted_contacts）；调用方：app/routers/leads.py:70,124,158 build_lead_payload、reports/daily_reports 展示链路；tests/test_leads_contact_fields.py（test_leads_contact_fields_tolerate_legacy_raw_data_without_contact_extract）
- **reason**: webhook 新链路写入独立提取列，旧 raw_data.contact_extract 与 customer_contact 是历史遗留字段；展示层保留兼容读取避免旧线索显示缺字段
- **current_role**: 线索展示的兼容 fallback：权威列优先，旧字段兜底
- **current_dependencies**: leads.py:70/124/158；reports/日报展示链路；tests（test_leads_contact_fields.py、test_leads_management.py）
- **replacement**: 权威列口径（_authoritative_contact_values）
- **deletion_condition**: 历史线索数据迁移完成（raw_data.contact_extract/customer_contact 不再作为展示来源）后移除兼容分支
- **risk_if_removed**: 历史线索联系方式展示缺失（旧数据无独立列）
- **source_files**:
  - app/services/lead_management_service.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-049 contact_state 历史裸字符串格式兼容

- **name**: contact_state_legacy_format_compat
- **classification**: COMPATIBILITY
- **owner**: M02
- **g1_status**: ACTIVE（runtime_role=DOMAIN_SHARED）
- **evidence**: `app/services/contact_state_service.py:112-180` `_validate_lead_contact_list`：`:117` 注释"历史遗留格式：裸字符串（非 JSON）"；`:131-134` 裸字符串解析分支（仅完整手机号采用，记 unknown_format_count）；`:34-41` `_CONTACT_ACTION_BY_STATE` 注释"旧映射（仅用于 Legacy Payload 兼容，不代表 P0-B Kernel 已启用 policy）"；服务本身是正式公共实现（build_request_contact_state 被 ai_auto_reply_dry_run_service.py:1087 与工作台共用）；tests（test_contact_state_* 系列）
- **reason**: 历史线索 all_extracted_contacts 曾有裸字符串存储格式，读取时保留兼容解析；contact_action 旧映射仅为旧 payload 兼容
- **current_role**: 正式 contact_state 服务内的历史格式兼容分支（裸字符串解析 + 旧 action 映射）
- **current_dependencies**: ai_auto_reply_dry_run_service.py:1087；douyin_workbench 会话链路；tests
- **replacement**: 标准 JSON 格式（phones/wechats/all 结构）
- **deletion_condition**: 历史裸字符串数据全部迁移/归档后移除兼容分支；contact_action 旧映射在 9100 不再消费 Legacy 值后移除
- **risk_if_removed**: 历史线索 contact_state 解析为空导致留资误判
- **source_files**:
  - app/services/contact_state_service.py
- **related_module**: M02
- **status**: VERIFIED

---

## LEGACY-050 conversation_history 旧调用名兼容

- **name**: conversation_history_legacy_call
- **classification**: COMPATIBILITY
- **owner**: M01
- **g1_status**: ACTIVE
- **evidence**: `app/services/douyin_conversation_history_service.py:120-142` `build_conversation_history` docstring"兼容旧调用；新回复链路应使用 build_reply_conversation_context"；新正式入口 `:35-117` `build_reply_conversation_context`（被 ai_auto_reply_dry_run_service.py:29,266 调用）；生产调用方 grep 仅测试（tests/test_douyin_conversation_history_service.py:19,174-210）
- **reason**: 旧回复链路上下文函数名保留给测试与旧分支；新链路统一走 build_reply_conversation_context
- **current_role**: 兼容旧调用名的薄包装（转调 build_reply_conversation_context 取 conversation_history）
- **current_dependencies**: tests/test_douyin_conversation_history_service.py（仅测试引用，无生产调用方）
- **replacement**: build_reply_conversation_context（正式入口）
- **deletion_condition**: 测试迁移到 build_reply_conversation_context 后删除本函数
- **risk_if_removed**: 仅测试引用受影响；生产无风险
- **source_files**:
  - app/services/douyin_conversation_history_service.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-051 前端 admin-autoreply-rollout 隐藏入口

- **name**: admin_autoreply_rollout_hidden_entry
- **classification**: LEGACY_KEEP
- **owner**: M01
- **g1_status**: ACTIVE（与审计一致）
- **evidence**: `frontend/src/App.tsx:41` adminRoutes 注册 `/admin/autoreply-rollout`（navId "admin-autoreply-rollout"，permission `auto_wechat:admin:autoreply`）；`App.tsx:144-146` canAccessPath 仍放行持权限者；`App.tsx:117` 注释"自动回复灰度入口已隐藏：是否自动发送只由 env 开关决定，不再跳转灰度控制台"；`SideNav.tsx` adminItems 无 autoreply-rollout（已隐藏）；`pages/Index.tsx:41,870-871` 仍挂渲染 `AdminAutoreplyRolloutPage`（850 行真实页面）；docs/ai/05_PROJECT_CONTEXT.md:331 契约"自动回复灰度入口已在超管侧栏隐藏，页面/路由/权限码保留不删"
- **reason**: 灰度控制台被 env 开关方案取代，但按契约保留直连 URL 可达的页面/路由/权限码（不删）
- **current_role**: 隐藏但可直连的管理页面（env 开关时代的遗留控制台）
- **current_dependencies**: pages/Index.tsx（渲染）；App.tsx adminRoutes（路由+权限）；`auto_wechat:admin:autoreply` 权限码
- **replacement**: env 开关（自动发送由后端 env 决定）
- **deletion_condition**: 需产品/运维确认灰度控制台永久退役且无存量直连用户，并同步 docs/ai/05_PROJECT_CONTEXT.md:331 契约后删除（经独立审批）
- **risk_if_removed**: 中——存在持 admin:autoreply 权限的历史直连入口
- **source_files**:
  - frontend/src/pages/AdminAutoreplyRolloutPage.tsx
  - frontend/src/App.tsx
  - frontend/src/pages/Index.tsx
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-052 apps/compute 独立服务入口（dev 能力中心 9205）

- **name**: compute_subapp_dev_entry_m07
- **classification**: ACTIVE
- **owner**: M07
- **g1_status**: ACTIVE（apps/compute/main.py G1 标 ACTIVE，runtime_role=SUBAPP）
- **evidence**: `docker-compose.dev.yml:270-286` compute-service（9205）命令 `uvicorn apps.compute.main:app`；apps/compute/main.py/router.py 独立入口仅被 dev compose 9205 引用（prod/staging/frontend-prod compose 均不引用，已逐一核对）；`apps/compute/services.py` 是当前唯一正式实现层（被 9000 引用，LEGACY-027 同型）；apps/compute 目录与能力中心标准模式同构（main/router/service/services）
- **reason**: apps/compute 是**当前正式模块**（M07 实现层），其 dev 能力中心独立入口是正式部署形态之一（与 5 个旧子应用"语义已被 9000 吸收"不同——compute 的 services 是唯一实现，非被替代残留）；审计确认后归 ACTIVE
- **current_role**: dev 环境算力能力中心独立服务入口（9205）；生产由 9000 内嵌 compute router + capability_gateway 提供
- **current_dependencies**: docker-compose.dev.yml 9205；dev 联调流程；packages.common.capability 公共底座
- **replacement**: NONE（能力服务标准模式）
- **deletion_condition**: NONE（当前正式部署形态；未来若 dev 能力中心整体退役需独立评估）
- **risk_if_removed**: dev 独立算力服务不可用（9000 内嵌能力不受影响）
- **source_files**:
  - apps/compute/main.py
  - apps/compute/router.py
  - apps/compute/routers.py
  - apps/compute/dependencies.py
- **related_module**: M07
- **status**: VERIFIED

---

## LEGACY-053 apps/xg_douyin_ai_cs/scripts/milvus_export.py 运维导出脚本

- **name**: milvus_export_ops_script
- **classification**: LEGACY_KEEP
- **owner**: M01
- **g1_status**: DEV_ONLY（runtime_role=SCRIPT）
- **evidence**: `apps/xg_douyin_ai_cs/scripts/milvus_export.py:1-70` Milvus collection 全量导出 JSONL（备份/迁移/交付，复用 Settings 不硬编码凭据）；无生产运行依赖、无运行时调用方；被治理文档引用为运维手段（docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md:1611-1612 等）；同目录 milvus_canary_e2e.py / milvus_collection_check.py 为当前巡检工具
- **reason**: 运维工具（Milvus 数据备份/迁移手段），非运行链路，保留价值 = Milvus 备份与迁移能力（向量副本可重建，导出工具是兜底手段）
- **current_role**: 运维导出脚本（容器内人工执行，--no-embeddings/--batch-size 可配）
- **current_dependencies**: 无运行时依赖（仅人工运维）；治理文档引用
- **replacement**: NONE（无替代工具接入）
- **deletion_condition**: Milvus 备份迁移能力迁移到其他工具后（经独立评估）
- **risk_if_removed**: 失去 Milvus 数据备份/迁移手段
- **source_files**:
  - apps/xg_douyin_ai_cs/scripts/milvus_export.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-054 reply_hard_rules 旧私有名 re-export（P0-A 单一权威）

- **name**: reply_hard_rules_private_name_reexport
- **classification**: ACTIVE
- **owner**: M01
- **g1_status**: ACTIVE（G2 审计确认非 legacy 债务）
- **evidence**: `apps/xg_douyin_ai_cs/services/reply_decision_service.py:2745-2756` 注释"旧测试依赖的私有名在此重新导出，不保留第二套实现"（_FALSE_CONFIRM_KEYWORDS/_contact_reply_violation 等别名）；这些别名当前模块代码活跃使用（:1203,1205,1207,1269-1282,1321-1350,2852）；`reply_kernel/validator.py:11-14` 直接 import reply_hard_rules；`reply_hard_rules.py` 是 P0-A 检测器单一权威（无第二套实现）；tests（test_p0a_false_contact_hotfix.py、test_reply_kernel.py:89-101）校验单一权威
- **reason**: P0-A 移动后旧私有名在同一模块内重新导出；re-export 既服务旧测试也服务当前模块内引用——"看起来像兼容 shim 但审计后确认是当前正式实现的一部分"
- **current_role**: Hard 违规检测单一权威来源 + 模块内别名引用
- **current_dependencies**: reply_decision_service（_build_llm_reply 检测器）；reply_kernel.validator；tests
- **replacement**: NONE（单一权威是正式方案）
- **deletion_condition**: NONE（当前正式实现；模块内别名可整理为直接引用属纯重构，非删除）
- **risk_if_removed**: Hard 违规检测失效（P0-A 安全门禁）
- **source_files**:
  - apps/xg_douyin_ai_cs/services/reply_hard_rules.py
  - apps/xg_douyin_ai_cs/services/reply_decision_service.py
  - apps/xg_douyin_ai_cs/services/reply_kernel/validator.py
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-055 9100 embedding 旧 env 变量回退（XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED）

- **name**: embedding_legacy_env_fallback
- **classification**: COMPATIBILITY
- **owner**: M01
- **g1_status**: ACTIVE（G2 审计发现）
- **evidence**: `apps/xg_douyin_ai_cs/llm/embedding_config.py:7-8,57-67` 注释"新变量未设置时回退旧变量 XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED，平滑过渡"；`docker-compose.dev.yml:167` 已写死旧变量 `XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED`；新变量 `XG_DOUYIN_AI_EMBEDDING_ENABLED` 在三份 env 模板中
- **reason**: embedding 开关变量改名（LLM_ 前缀 → EMBEDDING_）后的旧变量兼容回退，避免 dev compose/.env 已写死旧变量的环境失效
- **current_role**: enabled 开关解析的旧变量回退（新变量优先，未设置时回退旧变量）
- **current_dependencies**: docker-compose.dev.yml:167（旧变量）；9100 embedding 启动链路
- **replacement**: 新变量 `XG_DOUYIN_AI_EMBEDDING_ENABLED`（env 模板已用）
- **deletion_condition**: dev compose/.env 更新为新变量后移除回退分支（确认无环境仍写死旧变量）
- **risk_if_removed**: 仍写死旧变量的 dev 环境 embedding 开关失效（默认关）
- **source_files**:
  - apps/xg_douyin_ai_cs/llm/embedding_config.py
  - docker-compose.dev.yml
- **related_module**: M01
- **status**: VERIFIED

---

## LEGACY-059 db_bl_2c 迁移链审计工具组（P1 验证权威）

- **name**: db_bl_2c_audit_tools
- **classification**: ACTIVE
- **owner**: PLATFORM
- **g1_status**: DEV_ONLY（G2 审计确认：保留为 frozen verification authority）
- **evidence**: `docs/architecture/remediation/DB_BL_2D_IMPLEMENTATION_REPORT.md:200,205,374` 将 db_bl_2c_resume_snapshot.py 列为 frozen canonical verification 工具；DB_BL_2D_IMPLEMENTATION_APPROVAL.md:70,300-301；DB_BL_2C_R1_APPROVAL.md:28-29（审批窗口亲自运行 chain/temporal audit）；DB_BL_2C_RESUME_APPROVAL.md:83；P1 TECHNICAL_CLOSURE=VERIFIED 后 2D 文档仍指定其为未来 schema 基线复验工具
- **reason**: 迁移链缺陷（0025 file_size_bytes 重复列等）的静态/时序/快照审计工具；P1 收口后使命基本完成，但被 2D 文档明确保留为 schema 基线复验的 verification authority——"看起来像历史工具但审计后确认仍是正式验证机制的一部分"
- **current_role**: PG migration 链静态审计（chain_audit）、时序审计（temporal_audit）、catalog snapshot/diff（resume_snapshot）
- **current_dependencies**: DB_BL_2D 系列审批/报告文档引用；无生产/CI 调用
- **replacement**: NONE（本身即 verification helper）
- **deletion_condition**: NONE（当前验证机制；schema baseline 永久冻结且不再需复跑审计时独立评估）
- **risk_if_removed**: 未来 schema 基线漂移复验失去工具；审批文档引用悬空
- **source_files**:
  - scripts/db_bl_2c_chain_audit.py
  - scripts/db_bl_2c_resume_snapshot.py
  - scripts/db_bl_2c_temporal_audit.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-060 scripts/fix_ai_edit_jobs.py（AI 剪辑历史任务修复脚本）

- **name**: fix_ai_edit_jobs_script
- **classification**: LEGACY_KEEP
- **owner**: M06
- **g1_status**: DEV_ONLY
- **evidence**: docs/architecture/modules/M06/CHAIN.md:26,56 登记"DEV_ONLY 一次性任务修复脚本"；脚本头"AI 剪辑历史任务修复脚本：标题补全 + 视频归档"；RUNTIME_ENTRYPOINTS.md:248 fix_*.py 归 maintenance ACTIVE 组；无 runbook 当前调用
- **reason**: AI 剪辑旧执行面（本地 FFmpeg/worker）历史任务的数据修复通道；LAS 云端方案上线后旧任务仍需修复手段
- **current_role**: AI 剪辑历史任务修复运维工具（archive-videos/backfill-titles），人工执行
- **current_dependencies**: 无当前调用方（M06 CHAIN 登记）
- **replacement**: NONE
- **deletion_condition**: 历史 AI 剪辑任务全部修复归档完毕 + M06 CHAIN 登记移除
- **risk_if_removed**: 历史任务修复通道丢失（低）
- **source_files**:
  - scripts/fix_ai_edit_jobs.py
- **related_module**: M06
- **status**: VERIFIED

---

## LEGACY-061 leads/tasks PG shadow 双轨对照工具组（11 个 dev 脚本）

- **name**: leads_tasks_shadow_pilot_tools
- **classification**: COMPATIBILITY
- **owner**: PLATFORM
- **g1_status**: DEV_ONLY
- **evidence**: `app/config.py:179-182` LEADS_TASKS_PG_PILOT_ENABLED/READ_SHADOW/WRITE/STRICT 默认全 False；互引用链：smoke_leads_tasks_runtime_shadow_dev.py:26、smoke_migrate_leads_tasks_core_dev_apply.py:18、smoke_contrast_leads_tasks_core_dev.py:15、contrast_leads_tasks_core_sqlite_vs_postgres.py:21、benchmark_*_dev.py:32-38 全部 import migrate_leads_tasks_core_sqlite_to_postgres（LEGACY-036 组）；smoke_knowledge_categories_sqlite_pg_api_contrast.py:41；引用文档仅 archive + RUNTIME_ENTRYPOINTS.md:246-247（dev_tool）
- **reason**: P3-D 系列 SQLite↔PG 双写/对照验证工具（leads/tasks shadow 试点 + knowledge_categories API 对照）；试点默认关，工具是试点验证手段（PG cutover 过渡期兼容验证）
- **current_role**: dev shadow/对照验证工具（pilot 开启时使用）
- **current_dependencies**: 互引（底层 core 迁移脚本）；无生产调用；tests（test_migrate_*_core 等）
- **replacement**: NONE（pilot 验证工具）
- **deletion_condition**: leads/tasks shadow pilot 正式落地或废弃 + 相关 smoke/contrast/benchmark 脚本及其测试一并清理
- **risk_if_removed**: pilot 验证手段缺失；相关测试受影响（低）
- **source_files**:
  - scripts/smoke_migrate_leads_tasks_core_dev_apply.py
  - scripts/smoke_migrate_compute_core_dev_apply.py
  - scripts/smoke_migrate_agents_accounts_core_dev_apply.py
  - scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py
  - scripts/contrast_agents_accounts_core_sqlite_vs_postgres.py
  - scripts/benchmark_leads_tasks_shadow_http_dev.py
  - scripts/benchmark_leads_tasks_shadow_overhead_dev.py
  - scripts/benchmark_leads_tasks_shadow_workers_dev.py
  - scripts/smoke_knowledge_categories_sqlite_pg_api_contrast.py
  - scripts/smoke_knowledge_categories_sqlite_pg_contrast.py
  - scripts/smoke_leads_tasks_runtime_shadow_dev.py
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## LEGACY-062 平台发布/构建资产审计确认组（compose/Dockerfile/env 模板/pg-init/local_agent.spec）

- **name**: platform_release_assets_audited
- **classification**: ACTIVE
- **owner**: PLATFORM-RELEASE
- **g1_status**: 各文件 ACTIVE / DEV_ONLY（G1 与审计一致）
- **evidence**: docker-compose.yml=唯一生产主入口（05_PROJECT_CONTEXT.md:75；release_9000_s10b.py:53 唯一引用）；docker-compose.staging.yml=staging 覆盖（禁单独运行）；docker-compose.dev.yml=本地独立编排（能力中心 9201-9206）；docker-compose.frontend-prod.yml=G0-R3 前端不可变镜像 override（44c5914 引入，release_frontend_immutable.py:17,33 引用）；Dockerfile.backend.dev=9000/9100 共享后端镜像（三个 compose 全部 build 它）；Dockerfile.frontend.dev/prod=dev/prod 前端分工；.env.*.example=三环境模板（VITE_* 已并入）；docker/postgres/init*/=三态 PG 初始化（各自 compose 挂载）；local_agent.spec=正式 Local Agent 打包（build_local_agent_exe.ps1:18-19,118 唯一调用方，.gitignore 白名单 tracked）
- **reason**: 平台发布/构建/环境资产经 A6 区域审计全部确认 ACTIVE（无 legacy 嫌疑），按 G2"ACTIVE 参与候选总数"口径登记为审计确认组（LEGACY GROUP）
- **current_role**: 生产/staging/dev 部署、构建、环境模板、PG 初始化、Local Agent 打包的正式资产
- **current_dependencies**: release runner（release_9000_s10b.py、release_frontend_immutable.py）；compose 组合；部署流程；tests（test_release_g0_r3_frontend_immutable.py 等）
- **replacement**: NONE（当前正式资产）
- **deletion_condition**: NONE（正式资产）
- **risk_if_removed**: 部署/构建链路全断
- **source_files**:
  - docker-compose.yml
  - docker-compose.staging.yml
  - docker-compose.dev.yml
  - docker-compose.frontend-prod.yml
  - Dockerfile.backend.dev
  - Dockerfile.frontend.dev
  - Dockerfile.frontend.prod
  - .env.development.example
  - .env.lan.example
  - .env.production.example
  - docker/postgres/init/001_create_databases.sql
  - docker/postgres/init-prod/010_create_rag_database.sh
  - docker/postgres/init-staging/010_create_rag_database.sh
  - local_agent.spec
- **related_module**: PLATFORM
- **status**: VERIFIED

---

## G2 统计（G2-LEGACY-CONSOLIDATION-1，BASE_SHA=f582740d611d6791106a3eddcbf86ae6358f331d）

### 分类统计

| 分类 | 数量 | 项 |
|---|---|---|
| ACTIVE | 15 | 010/014/015/023/024/027/034/044/052/054/056/057/058/059/062 |
| COMPATIBILITY | 21 | 004/006/008/009/011/012/016/017/021/025/026/029/036/043/045/046/048/049/050/055/061 |
| LEGACY_KEEP | 15 | 001/002/003/005/007/028/030/031/035/037/040/047/051/053/060 |
| LEGACY_MIGRATE | 2 | 020/039 |
| DELETE_CANDIDATE | 9 | 013/018/019/022/032/033/038/041/042 |
| UNKNOWN_LEGACY | 0 | — |
| **合计** | **62** | LEGACY_CANDIDATES = CLASSIFIED_TOTAL = 62 |

### Owner 分布（G2 记录 owner）

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

> 说明：M05 无 Legacy 候选（素材库为当前正式实现）；M06 仅 fix_ai_edit_jobs.py 登记项（LAS 混剪本身 ACTIVE，无遗留）；DOMAIN_SHARED 无独立记录（contact_extraction 域归 M02，见 LEGACY-048/049）。

### 机器验收

```text
python scripts/validate_g2_legacy_registry.py
G2_VALIDATION = PASS
LEGACY_CANDIDATES = 62 / CLASSIFIED_TOTAL = 62 / UNKNOWN_LEGACY = 0 / OWNER_CONFLICT = 0
CODE_INDEX_OWNER_MATCH = 66/66（R1 规则）；OWNER_WAIVED_FILES = 24+（R2/R3/R4 豁免，见 G2 报告）
```

### G1 事实修正清单（G1 factual correction during G2）

G2 审计发现以下 G1 标记与当前代码事实不符（仅登记修正建议；不直接改 code_index.yaml——其由生成器维护，最小修正需经生成器或独立治理窗口）：

| 文件 | G1 标记 | G2 结论 | 依据 |
|---|---|---|---|
| app/integrations/douyin_webhook.py | COMPAT | ACTIVE（当前 webhook 直收主实现） | LEGACY-044 |
| app/services/knowledge_category_service.py | ACTIVE | COMPATIBILITY（re-export 兼容入口） | LEGACY-045 |
| migrations/migrate_sqlite.py + versions 0001~0045 | LEGACY | ACTIVE（SQLite 仍是 dev 默认库迁移轨道） | LEGACY-034 |
| migrations/downgrades/* | LEGACY | LEGACY_KEEP（DATABASE HISTORY） | LEGACY-035 |
| scripts/migrate_*_sqlite_to_postgres*.py | LEGACY | COMPATIBILITY（cutover 未完成仍有执行职责） | LEGACY-036 |
| app/wechat_ui/contact_searcher.py（LEGACY-010） | UNKNOWN | ACTIVE（诊断字段仍被正式返回） | LEGACY-010 |
| 前端 pages/、components/、navigation/、api/douyinCs.ts 等 | ACTIVE | DELETE_CANDIDATE / COMPATIBILITY（死 shim/死页面） | LEGACY-018/019/021 |
| apps/{agents,leads,knowledge,douyin_cs,wechat_assistant} | 全 COMPAT | 分层：service 实现层 ACTIVE / dev 入口 LEGACY_KEEP / 死 schema DELETE_CANDIDATE | LEGACY-027~033 |
| 根 Dockerfile | ACTIVE | DELETE_CANDIDATE（无 build 引用、DEPRECATED） | LEGACY-038 |
| 前端 3 组件 shim（ChatPanel/ContactInfo/ContactList） | COMPAT | DELETE_CANDIDATE（零引用） | LEGACY-018 |

### 非 Legacy 事项确认（任务书第十二条）

- **BC-02**（M05/M06 物理边界耦合）= NOT_LEGACY，属 boundary coupling，留给 G4
- **HIGH-03**（LAS long queued video_urls expire >7 天）= NOT_LEGACY，属 M06 known risk
- **RG-FOLLOWUP-01/02**（PLATFORM release-governance follow-up）= NOT_LEGACY；G2 审计发现的 2 处漂移登记在案（不顺手修）：① `scripts/production_pg_alembic_upgrade.sh:31-32` 目标 revision 仍是 0007/0002，落后 head 0035/0005，cutover 执行前必须更新（属 release-governance 修复，不在 G2 范围内执行）；② code_index.yaml 头部 production revision 声称与 05_PROJECT_CONTEXT 存在出入（按 Source of Truth 层级以运行事实为准，登记不修改）
