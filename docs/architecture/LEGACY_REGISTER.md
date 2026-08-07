# Legacy 登记簿

> 基于 1A.1 SYSTEM_MAP + 1A.2 CODE_INDEX + 1A.3 RUNTIME_ENTRYPOINTS + 1A.4 DEPENDENCY_MATRIX 四份已冻结事实（commit c26ec227e70d）。
> 1A.5 是定性而非重新探索。每项有运行证据（不只 grep 命名）。
> 本登记簿不改代码、不删代码，只记录定性结论与删除前置。

## 两个独立维度

### Lifecycle（未来还要不要）
判断代码在未来架构中的去留定性，与"能不能删"是**两个独立维度**：

| 标签 | 含义 |
|---|---|
| ACTIVE | 当前正式业务，生产默认启用 |
| COMPAT | 正式兼容路径，暂时不能删（如旧 webhook 路径 GMP 已配置） |
| LEGACY | 已被新方案替代，但仍存在调用/env 开关控制，默认关 |
| DEAD_CANDIDATE | 初步认为无人使用，等待证据后删除 |
| UNKNOWN | 仍无法判断，需补充证据 |

**Lifecycle ≠ Deletion Eligibility**：Lifecycle 是"未来还要不要"，Deletion Eligibility 是"现在能不能删"。COMPAT 不得在普通业务任务中顺手删除。状态机：`UNKNOWN → LEGACY/COMPAT/ACTIVE → DEAD_CANDIDATE → DELETION_READY → REMOVED`，当前最多 DEAD_CANDIDATE（尚无 DELETION_READY）。

### quality_flags（实现质量标签，不改变 lifecycle）
TECH_DEBT / CONFIG_BYPASS 等是质量标签，**不作为生命周期**。标了 TECH_DEBT 的项仍是 ACTIVE 正式运行能力，只是实现方式需治理。不要因在 LEGACY_REGISTER 里就让 VibeCoding 误判可淘汰。

## UNKNOWN 规则

证据不足时 **UNKNOWN 优先于推测**。禁止删除/重构/改为 LEGACY/假设无人使用，直到补充证据。

---

## 15 个 Legacy 项

---

## LEGACY-001 leads_internal_webhook_fallback

- **能力**：webhook 转发到 9202 internal leads 服务的回退路径
- **代码位置**：`app/config.py:316` `LEADS_WEBHOOK_INTERNAL_ENABLED`；`app/routers/integrations.py:453` 分支判断
- **当前状态**：LEGACY
- **新方案**：9000 本地直收 webhook（`_process_webhook_locally`），internal 模式非生产主线
- **启用条件**：env `LEADS_WEBHOOK_INTERNAL_ENABLED=true`
- **生产默认**：关
- **运行证据**：
  - 1A.3：env 开关默认 false；true 时调 `LeadsClient.from_env().create_internal_webhook_event`
  - 1A.4：M02 webhook 入口，internal 模式时事件在 9202 而非 9000 本地
  - 1A.1：标 leads_internal_webhook
- **是否允许删除**：待证据
- **删除前置**：确认所有环境（含 staging）均用本地直收；9202 leads-service 确认无生产流量；env 模板移除该变量

## LEGACY-002 旧微信自动检测调度器

- **能力**：9000 进程内定时轮询微信回复检测（旧链路）
- **代码位置**：`app/config.py:349` `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT`；`app/main.py:197-208`；`app/scheduler/wechat_auto_detect_scheduler.py:43`
- **当前状态**：LEGACY
- **新方案**：19000 Local Agent（小高AI微信助手.exe）poll-and-detect，宿主机运行
- **启用条件**：env `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1`
- **生产默认**：关
- **运行证据**：
  - 1A.3：scheduler runtime_state=disabled_by_default，lifecycle=LEGACY，新主线走 19000
  - 1A.4：M04 模块，被 CODE_INDEX 标 legacy_candidates
  - 1A.1：标旧微信自动检测
- **是否允许删除**：待证据
- **删除前置**：确认 19000 Local Agent poll-and-detect 在所有生产环境稳定运行；旧 scheduler 代码无其他调用方

## LEGACY-003 douyinAPI 8081

- **能力**：douyinAPI（8081）作为 demo/参考实现/历史沉淀
- **代码位置**：`app/config.py:217` `DOUYIN_API_BASE_URL` 默认 `http://127.0.0.1:8081`；`app/integrations/douyin_api_client.py:34`
- **当前状态**：DEAD_CANDIDATE
- **新方案**：9000 直收 webhook + OpenAPI 签名调用（DY_OPENAPI_BASE_URL）
- **启用条件**：无 env 开关，仅作为 `DOUYIN_API_BASE_URL` 默认值保留
- **生产默认**：未启用（生产用 GMP webhook + OpenAPI，不调 8081）
- **运行证据**：
  - 1A.1：标 demo/参考实现非生产依赖
  - 1A.4：外部系统表中 lifecycle=UNKNOWN，无模块实际调用 8081 生产链路
  - 1A.3：无 8081 端口的 Docker command 或启动入口
- **是否允许删除**：满足删除前置后允许删除（当前 DEAD_CANDIDATE，未到 DELETION_READY）
- **删除前置**：grep 确认 `DOUYIN_API_BASE_URL` 无生产调用方；`douyin_api_client.py` 确认无 import；移除默认值和 client 文件

## LEGACY-004 callback.misanduo.com 硬编码域名

- **能力**：生产 webhook/任务回写域名 + OAuth 前端回跳默认 origin
- **代码位置**：`app/routers/integrations.py:877`（注释）；`app/routers/douyin_live_check.py:56` `AUTH_REDIRECT_DEFAULT_ORIGIN`；`app/local_agent_main.py:121`；`app/local_agent_exe_entry.py:85`
- **当前状态**：COMPAT
- **新方案**：无（当前生产地址，GMP 已配置）
- **启用条件**：无开关，硬编码默认值（可被 env 覆盖）
- **生产默认**：开（生产实际使用）
- **运行证据**：
  - 1A.1：标 callback.misanduo.com/douyinapi.misanduo.com 硬编码
  - 1A.3：External Callback 表，callback.misanduo.com 是生产 webhook 兼容路径域名，douyinapi.misanduo.com 是 OAuth 前端回跳默认 origin
  - 1A.4：M02/M04 外部系统依赖
- **是否允许删除**：否
- **删除前置**：域名迁移到环境变量配置（非硬编码）；确认 GMP 回调地址、OAuth redirect、Local Agent server-url 均改读 env；宝塔反代配置同步更新

## LEGACY-005 旧拉取链路 sync-leads

- **能力**：从 douyinAPI 8081 主动拉取线索的旧链路
- **代码位置**：`app/routers/integrations.py:595` `@router.post("/sync-leads")`；`app/services/douyin_sync_service.py:142` `preview_sync_leads`
- **当前状态**：LEGACY
- **新方案**：9000 直收 webhook（webhook 直收→入库→分配）
- **启用条件**：路由无条件注册，但 `auto_notify=True` 已显式禁用（`integrations.py:605-614` 抛 `LEGACY_AUTO_NOTIFY_DISABLED`）
- **生产默认**：关（auto_notify 链路禁用，preview-only 仍可用但非生产主线）
- **运行证据**：
  - 1A.1：标 sync-leads，auto_notify 已禁用
  - 1A.3：FastAPI router 注册（/integrations/douyin），但 auto_notify 守卫阻断
  - 1A.4：CODE_INDEX lifecycle_candidates M02
- **是否允许删除**：待证据
- **删除前置**：确认 preview_sync_leads 无生产调用；确认前端无"同步抖音线索"按钮调用该路由；移除路由 + douyin_sync_service

## LEGACY-006 兼容 webhook 旧路径 /webhook/douyin

- **能力**：GMP 已配置的抖音 webhook 回调兼容路径
- **代码位置**：`app/routers/integrations.py:45` `legacy_webhook_router`；`integrations.py:867` `@legacy_webhook_router.post("/douyin")`；`app/main.py:130` 注册
- **当前状态**：COMPAT
- **新方案**：无（与正式入口 `/integrations/douyin/webhook` 共享 `_handle_douyin_webhook`，行为一致）
- **启用条件**：无条件注册
- **生产默认**：开（GMP 配置 `callback.misanduo.com/webhook/douyin` 宝塔反代到 9000）
- **运行证据**：
  - 1A.3：transport_entrypoint=2, business_handler=1，兼容路径是 2 入口之一
  - 1A.4：M02 webhook 入口
  - 1A.1：标 legacy_webhook_router 兼容路径
- **是否允许删除**：否
- **删除前置**：GMP 回调地址改为 `/integrations/douyin/webhook` 正式路径；宝塔反代配置同步；确认无遗漏的旧回调配置

## LEGACY-007 LEGACY_WECHAT_DEBUG_ENDPOINTS

- **能力**：旧微信 debug 端点群（replies.py 内多个调试接口）
- **代码位置**：`app/config.py:329-331` `LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED`；`app/routers/replies.py:28,33,36,37,73,183,207,419,567` `_require_legacy_wechat_debug_enabled` 守卫
- **当前状态**：LEGACY
- **新方案**：19000 Local Agent 诊断端点（/agent/wechat/search-debug 等）
- **启用条件**：env `LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED=true`
- **生产默认**：关
- **运行证据**：
  - 1A.3：env 开关默认 false，lifecycle=LEGACY
  - 1A.4：CODE_INDEX lifecycle_candidates M04
  - 1A.1：标 LEGACY_WECHAT_DEBUG_ENDPOINTS
- **是否允许删除**：待证据
- **删除前置**：确认 19000 Local Agent 诊断端点覆盖所有旧 debug 场景；确认无生产环境依赖这些端点

## LEGACY-008 DY_BASE_URL_LEGACY

- **能力**：OpenAPI base_url 回退到 legacy 值
- **代码位置**：`app/config.py:228-229` `DY_BASE_URL_LEGACY` / `DY_BASE_URL`
- **当前状态**：COMPAT
- **新方案**：无（当前 OpenAPI 调用链路的一部分，legacy 值作回退）
- **启用条件**：无开关，`DY_BASE_URL` 回退到 `DY_BASE_URL_LEGACY` 或 openapi 组合
- **生产默认**：开（生产用 `DY_OPENAPI_BASE_URL` 组合，legacy 仅回退）
- **运行证据**：
  - 1A.1：标 DY_BASE_URL_LEGACY
  - 1A.3：无独立入口，是 config 层回退逻辑
  - 1A.4：`douyin_openapi_client.py` legacy_base_url_used/present 调试字段
- **是否允许删除**：待证据
- **删除前置**：确认生产 `DY_OPENAPI_BASE_URL` 永远有值不走回退；移除 legacy 回退逻辑 + 调试字段

## LEGACY-009 auth_mode="legacy" Local Agent 旧未认证回退

- **能力**：Local Agent 旧未认证回退模式
- **代码位置**：`app/auth/local_agent_auth.py:62,67` `auth_mode="legacy"`
- **当前状态**：LEGACY
- **新方案**：`LOCAL_AGENT_AUTH_REQUIRED` + `LOCAL_AGENT_TOKEN` 正式鉴权
- **启用条件**：`LOCAL_AGENT_AUTH_REQUIRED=false`（默认）时走 legacy 未认证
- **生产默认**：关（生产应设 `LOCAL_AGENT_AUTH_REQUIRED=true`）
- **运行证据**：
  - 1A.1：标 auth_mode=legacy
  - 1A.3：env 开关 `LOCAL_AGENT_AUTH_REQUIRED` config.py:324 默认 false
  - 1A.4：CODE_INDEX lifecycle_candidates M04
- **是否允许删除**：待证据
- **删除前置**：确认所有生产 Local Agent 部署均设 `LOCAL_AGENT_AUTH_REQUIRED=true`；移除 legacy 回退分支

## LEGACY-010 legacy_foreground_ok/diag 微信前台旧诊断

- **能力**：微信前台置顶旧实现诊断字段
- **代码位置**：`app/wechat_ui/contact_searcher.py:2573,2574,2597,2598,2638,2639,2643-2648,3507,3508`
- **当前状态**：UNKNOWN
- **新方案**：未知（需确认是否被 19000 Local Agent 前台逻辑替代）
- **启用条件**：无独立开关，是 contact_searcher 内部诊断字段
- **生产默认**：未知
- **运行证据**：
  - 1A.1：标 legacy_foreground_ok/diag
  - 1A.3：无独立入口，是 19000 Local Agent 内部字段
  - 缺什么证据：需确认 contact_searcher 的前台逻辑是否被 19000 新前台 guard 替代；需确认这些字段是否仍被诊断端点返回
- **是否允许删除**：待证据
- **删除前置**：确认前台 guard 逻辑已迁移；确认诊断端点不依赖这些字段

## LEGACY-011 token 计量 legacy_characters 兼容枚举

- **能力**：历史 AI 消费按字符计量的兼容标记
- **代码位置**：`app/models.py:951` CheckConstraint 允许值；`app/schemas.py:1395` `Literal[...]`
- **当前状态**：COMPAT
- **新方案**：按供应商真实 Token 计量（Phase 10 升级）
- **启用条件**：无开关，是计量方式的兼容枚举值
- **生产默认**：开（历史数据标记为 `legacy_characters`）
- **运行证据**：
  - 1A.1：标 legacy_characters
  - 1A.4：M07 算力模块，历史 AI 消费标记
  - 1A.3：无独立入口，是 model/schema 层兼容枚举
- **是否允许删除**：否
- **删除前置**：历史 `legacy_characters` 记录全部迁移或归档；CheckConstraint 和 Literal 移除该值；确认无历史数据查询依赖

## LEGACY-012 算力 service 兼容入口

- **能力**：compute_service.py 作为兼容入口，实际实现迁移到 apps/compute/services/
- **代码位置**：`app/services/compute_service.py:1-4`（文档串 "Phase 3-B 起业务实现收敛到 apps.compute.services"）
- **当前状态**：COMPAT
- **新方案**：直接 import `apps.compute.services`
- **启用条件**：无开关，兼容入口 re-export
- **生产默认**：开（被 M06 ai_edit_las_service 调用）
- **运行证据**：
  - 1A.1：标算力 service 兼容入口
  - 1A.4：E11 M06→M07，ai_edit_las_service.py:735 调 `compute_service.record_usage`
  - 1A.2：CODE_INDEX lifecycle_candidates M07
- **是否允许删除**：待证据
- **删除前置**：所有调用方改直接 import `apps.compute.services`；确认无遗漏；移除兼容入口

## LEGACY-013 一键过审 CANCELLED_BY_CUSTOMER

- **能力**：巨量一键过审（AdReview 三表保留不回退）
- **代码位置**：`app/models.py:1432` AdReviewOAuthAccount / `:1451` AdReviewSuggestion / `:1475` AdReviewAdoptTask
- **当前状态**：DEAD_CANDIDATE
- **新方案**：无（2026-07-13 被客户取消，不再是一期范围）
- **启用条件**：无（代码保留不回退，无路由/调度器激活）
- **生产默认**：关
- **运行证据**：
  - 1A.1：标 CANCELLED_BY_CUSTOMER，不删除历史记录不回退已落地代码
  - 1A.3：无 AdReview 路由注册（grep main.py 无 ad_review router）
  - 1A.4：无模块依赖 AdReview 表
- **是否允许删除**：满足删除前置后允许删除（当前 DEAD_CANDIDATE，未到 DELETION_READY）
- **删除前置**：确认无任何路由/前端引用 AdReview 三表；移除三表 model + 迁移降级脚本；CLAUDE.md 同步移除"一键过审"条目

## LEGACY-014 CONTACT_INVALID_FOLLOWUP_ENABLED CONFIG_BYPASS

- **能力**：空号追问调度器开关直接读 os.environ 未进 config.py
- **代码位置**：`app/main.py:236` `os.environ.get("CONTACT_INVALID_FOLLOWUP_ENABLED", "false")`；`app/services/contact_invalid_followup_service.py:46`
- **当前状态**：ACTIVE
- **quality_flags**：CONFIG_BYPASS / CONFIG_DRIFT
- **新方案**：无（功能是主线，配置方式需治理）
- **启用条件**：env `CONTACT_INVALID_FOLLOWUP_ENABLED=true`
- **生产默认**：关
- **运行证据**：
  - 1A.3：CONFIG_BYPASS，唯一直接读 os.environ 的调度器开关（其他都走 config.py）
  - 1A.4：M01/M02 shared worker，contact_invalid_followup_service.py:130
  - 1A.2：CODE_INDEX config 项
- **是否允许删除**：否（功能保留，配置方式需治理）
- **删除前置**：不删功能；需把 `os.environ.get` 改为 `config.py` 统一读取（CONFIG_DRIFT 治理，非本阶段）

## LEGACY-015 @app.on_event 非 lifespan TECH_DEBT

- **能力**：FastAPI 已废弃的 startup/shutdown API
- **代码位置**：`app/main.py:171` `@app.on_event("startup")`；`app/main.py:240` `@app.on_event("shutdown")`
- **当前状态**：ACTIVE
- **quality_flags**：TECH_DEBT
- **新方案**：迁移到 `lifespan` / `asynccontextmanager`
- **启用条件**：无开关，启动即触发
- **生产默认**：开
- **运行证据**：
  - 1A.3：TECH_DEBT 标注，10 个启动项 + 8 个关闭项均挂在此
  - 1A.4：公共底座调度器全部依赖此启动钩子
  - docs 中多处误称 lifespan（SYSTEM_MAP.md:69）
- **是否允许删除**：否（TECH_DEBT，不影响功能但需迁移）
- **删除前置**：迁移到 lifespan asynccontextmanager（非本阶段）；确认所有启动/关闭项正确搬入

---

## 统计

| 状态 | 数量 | 项 |
|---|---|---|
| LEGACY | 5 | 001/002/005/007/009 |
| COMPAT | 5 | 004/006/008/011/012 |
| DEAD_CANDIDATE | 2 | 003/013 |
| ACTIVE | 2 | 014(quality_flags=CONFIG_BYPASS) / 015(quality_flags=TECH_DEBT) |
| UNKNOWN | 1 | 010 |
| 合计 | 15 | |

**是否允许删除（Deletion Eligibility，独立于 Lifecycle）**：
- 否（不可删）：004/006/011/014/015
- 待证据：001/002/005/007/008/009/010/012
- 满足删除前置后允许删除（当前 DEAD_CANDIDATE，未到 DELETION_READY）：003/013

**DEAD_CANDIDATE 删除前置**：
- LEGACY-003（douyinAPI 8081）：grep 确认无生产调用方 → 移除默认值和 client 文件
- LEGACY-013（一键过审）：确认无路由/前端引用 → 移除三表 model + 迁移降级

**UNKNOWN 缺什么证据**：
- LEGACY-010（legacy_foreground_ok/diag）：需确认 contact_searcher 前台逻辑是否被 19000 新前台 guard 替代；需确认诊断端点是否仍返回这些字段
