# Phase 10 小高算力模拟验收（DONE_WITH_CONCERNS）

> 验收日期：2026-07-15
> 执行包：`docs/superpowers/plans/2026-07-14-phase10-compute-execution-package.md`
> 对照基线：`265d719`（Phase 9 总验收 FIX1，仅用于起点对照）；Phase 10 实现起点：`332e697`（Task 0-1 数据合同）→ 终点：`47884ba`（Task 7 验收固化）
> 验收范围：本地模拟闭环，**未启动服务、未连宝塔、未真实迁移、未真实 AI/抖音验证**

---

## 1. 提交链与文件范围

| 提交 | Task | 说明 |
|---|---|---|
| `332e697` | Task 0-1 | 冻结红灯数据合同（schema 5 failed/2 passed/10 skipped + PG 1 failed/15 skipped） |
| `e6d20ee` | Task 2 | ORM 加 ComputeTransaction 3 列 + ComputeMarkupRatio + SQLite 0031 + PG 0012 |
| `a273019` | Task 2-FIX | 0031 精确列集守卫（pragma_table_info）+ 越序降级守卫 |
| `1f13970` | Task 2-FIX2 | 改 pragma_table_xinfo（含生成列）+ hidden=0 列名守卫 |
| `b3bc6b6` | Task 2-DOC | 将 Phase 10 算力执行包纳入 master-plan 路线图 |
| `fce206a` | Task 3 | calculate_billed_tokens（ceil 上浮/BIGINT 天花板）+ record_usage 严格合同 + with_for_update 行锁 |
| `8db606c` | Task 4 | 六能力上浮管理 API + 精确权限 `auto_wechat:admin:compute_config` |
| `eeaba0f` | Task 5 | 9100 按字符计量 + 全部现有 AI 埋点（reply_decision/daily_report/return_visit/knowledge_ask/embedding） |
| `556742a` | Task 3-5-FIX | 5 偏差闭合（daily_report 映射/client strip/conversation_id/并发建账/负余额告警） |
| `e5cadac` | Task 3-5-FIX2 | 5 门禁闭合（BIGINT 区间/网络哨兵/空白 merchant_id/真实并发建账/retry 分别计量） |
| `57faa52` | FIX3 | 删全局 conftest + 哨兵限 Phase 10 + 计数 yield 断言 |
| `ba7d7fb` | Task 6 | 商户流水 + 超管上浮配置前端闭环（8 文件 +465 行） |
| `47884ba` | Task 7 | 本地模拟总验收 + PHASE10_COMPUTE_ACCEPTANCE.md 验收文档 + 静态门禁 #4 注释措辞 |
| `0821759` | Task 7-FIX1 | 闭合三方评审 5 个 Must-Fix（fail-closed + BIGINT_MIN 守卫 + 验收文档提交链/起点/网络措辞补正） |
| `8ffa4f3` | Task 7-FIX1 收尾 | 补 Task 7-FIX1 提交号到验收文档 |
| `8d37efb` | Task 7-FIX2 | 接入超管上浮比例配置页 SuperComputeConfig（路由+导航+渲染，3 文件 +5 行） |

> **当前合同说明（2026-07-16）：** 上表中的 `eeaba0f` 记录的是 Phase 10 当时落地的字符计量历史事实。后续 `COMPUTE-OPT-01` 已将聊天模型计量升级为供应商真实 Token 优先、缺失时估算；历史流水通过 `legacy_characters` 与新流水区分。本节提交链不改写历史，当前合同以第 2 节为准。

**Task 7 额外改动**（修复静态门禁 #4）：`reply_decision_service.py` + `daily_report_summary_service.py` 注释措辞调整（"usage.total_tokens" → "provider 返回的 token 用量"），让 `rg total_tokens` 零命中，语义不变。

**Task 7-FIX1 改动**（三方评审 BLOCKED 后闭合 5 个 Must-Fix，提交 `0821759`）：
- Must-Fix 1（高危 fail-open）：`app/routers/compute.py` + `apps/compute/routers.py` 的 `_require_internal` 改 fail-closed（生产 `APP_ENV=production` 空配置 → 500 `INTERNAL_TOKEN_NOT_CONFIGURED`，dev 仍放行）；补 9000/9205 production fail-closed 测试。
- Must-Fix 2（高危 BIGINT_MIN）：`0031_compute_billing.sql` + `0012_compute_billing.py` 在 abs 回填前加 `delta_tokens < -9223372036854775807` 守卫（BIGINT_MIN 行 abs 溢出 BIGINT_MAX，存在则迁移阻断）；补 SQLite + PG 双数据库守卫测试。
- Must-Fix 3/4/5：本验收文档提交链加 `b3bc6b6`/`47884ba` + 起点/终点调整；后端/迁移 1 failed 补起点 `265d719` 同命令证据；完成定义改"目标专项通过、扩展回归零新增失败"；网络零调用措辞收窄为"专项测试哨兵"。

**Task 7-FIX2 改动**（用户本地验证发现 SuperComputeConfig 孤儿页面，提交 `8d37efb`）：
- 根因：Task 6 实现了 `SuperComputeConfig.tsx`（超管六能力上浮比例配置，821 行）但遗漏三处接入——`compute/routes.ts` 无路由、`capabilities.ts` compute-center children 无导航项、`Index.tsx` 无渲染分支。页面代码存在但用户无法通过菜单访问（`ComputeCenter` 4 个 navId 全部渲染商户侧，`SuperComputeConfig` 全仓库零 import）。
- 修复：`compute/routes.ts` 加 `/compute/markup-ratios` 路由；`capabilities.ts` compute-center children 加"上浮比例"导航项（需 `auto_wechat:admin:compute_config`）；`Index.tsx` import + 渲染分支加 `activeNav === "compute-markup-ratios" ? <SuperComputeConfig />`。3 文件 +5 行。
- 验证：phase10-compute:check PASS + tsc -b 退出码 0 + build ✓ built（chunk size 警告 pre-existing）。
- 教训：Task 6 验收记录"超管上浮配置前端闭环"但未验证页面可达性，三方复审只读代码未发现孤儿。后续前端验收应补"菜单入口可达性"检查。

---

## 2. 当前计费合同（2026-07-16）

- **聊天模型计量**：优先使用供应商 `usage.total_tokens`；缺少总量但输入和输出 Token 均有效时使用两者之和；供应商没有有效用量时才估算，并标记 `estimated_tokens`。
- **历史与 embedding**：历史 AI 消费标记 `legacy_characters`，不伪造输入、输出或缓存 Token；embedding 暂按输入字符数估算并标记 `estimated_tokens`，mock embedding 不计费。
- **上浮比例**：六能力 `douyin-cs/leads/agents/wechat-assistant/compute/knowledge`，`markup_basis_points`（基点，3300=33%），`calculate_billed_tokens = ceil(actual × (1 + markup/10000))`，超 BIGINT 整笔拒绝。
- **计费快照**：`actual_tokens` 保存上浮前基础用量；`capability_key`、`markup_basis_points` 保存能力和比例；`usage_measurement_method`、`prompt_tokens`、`completion_tokens`、`cached_tokens`、`llm_call_stage` 保存计量来源和单次模型调用明细。
- **重试计费**：抖音首轮、已知客户信息纠正、手机号目标纠正分别记录为 `primary`、`retry_known_customer`、`retry_phone_goal`，每次成功模型调用独立入账。
- **能力映射**：reply_decision=douyin-cs、daily_report/return_visit=wechat-assistant、knowledge_ask/_embed_with_usage=knowledge。
- **权限**：上浮配置 GET/PUT `/admin/compute/markup-ratios` 需 `auto_wechat:admin:compute_config` / super_admin；普通商户不可越权。
- **并发建账**：`get_or_create_account` SAVEPOINT + IntegrityError 恢复；`record_usage` 顶层单 commit（账户+流水原子）。
- **负余额**：不阻断，写 `stage=negative_balance` 结构化 warning；前端风险提示不写"服务已停用"。
- **前端字符串转基点**：`parseInt(intPart + paddedFrac, 10)` 纯字符串拼接，零浮点（`"33.5"→"33"+"50"→3350`）。
- **商户公开流水**：内部账本继续保存真实 Token、计量方式、调用阶段和诊断字段；商户公开流水是独立 7 字段投影（`id`/`type`/`type_label`/`business_scene`/`points_change`/`balance_after`/`created_at`），由 `list_merchant_transactions` 在服务层投影，9000 与独立算力服务商户路由共同调用，不承担内部计量诊断职责。

---

## 3. 测试数量与起点对照

### 3.1 后端专项（11 文件）

```
python -m pytest tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py \
  tests/test_phase10_compute_markup_api.py tests/test_phase10_compute_metering.py \
  tests/test_phase10_compute_no_network.py tests/test_compute_models.py tests/test_compute_service.py \
  tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py \
  tests/test_compute_usage_client.py -q
```

结果：**147 passed, 1 failed**。

- 唯一 failed：`test_phase10_compute_no_network.py::test_daily_report_happy_path_no_network`（401）。
- 根因：组合跑时其他测试文件先 import `app.main` 加载 `.env.lan.local`，污染 9100 `create_app` 的鉴权中间件；**单独跑该测试 PASSED**（`pytest tests/test_phase10_compute_no_network.py::test_daily_report_happy_path_no_network -v` → 1 passed）。
- 属 pre-existing 测试隔离问题（[[newcar-auth-env-breaks-tests]] / [[proxy-env-pollutes-llm-tests]] 同类），非 Phase 10 计费逻辑问题。
- **起点对照（Task 7-FIX1 补）**：起点 `265d719` 的 `test_compute_*` 6 文件（Phase 10 新增的 `test_phase10_compute_*` 在起点不存在）= **48 passed / 5 failed**（5 个 `internal_usage` / `transactions_after_recharge` failed，已被 Phase 10 修复为 passed）。当前后端专项 147p/1f，唯一 failed 为 Phase 10 新增测试 `test_daily_report_happy_path_no_network` 的组合跑 401（单独跑 PASSED）。**Phase 10 改进了后端，未新增破坏。**

### 3.2 AI 相邻回归（12 文件）+ 起点对照

```
python -m pytest tests/test_xg_douyin_ai_cs_app.py tests/test_xg_douyin_ai_cs_daily_report_summary.py \
  tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_internal_api.py \
  tests/test_phase9_return_visit_no_network.py tests/test_xg_douyin_ai_cs_rag.py \
  tests/test_xg_douyin_ai_cs_rag_workflow.py tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py \
  tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_xg_douyin_ai_cs_embedding_ark.py \
  tests/test_douyin_ai_cs_proxy.py -q
```

| 版本 | passed | failed | 命令 |
|---|---|---|---|
| 起点 `265d719`（Phase 9 终点） | 190 | 63 | 同上 |
| 当前 `ba7d7fb`（Phase 10 终点） | 191 | 62 | 同上 |

**结论**：当前比起点少 1 failed、多 1 passed，**Phase 10 零新增破坏**。failed 集中在 training_feedback / knowledge_training_ask_latency / embedding_ark / proxy，均为 pre-existing（proxy env 污染 + dev DB schema 漂移，见 [[proxy-env-pollutes-llm-tests]] / [[dev-db-schema-drift]]）。

### 3.3 迁移回归（5 文件）

```
python -m pytest tests/test_db_migration_0010_compute.py tests/test_xiaogao_phase1_schema.py \
  tests/test_phase9_return_visit_schema.py tests/test_db_migration_runner.py \
  tests/test_sqlite_specific_usage_guard.py -q
```

结果：**66 passed, 1 failed**。

- 唯一 failed：`test_db_migration_0010_compute.py::test_apply_does_not_touch_existing_tables`（`sqlite3.IntegrityError: NOT NULL constraint failed: sales_staff.enable_lead_assignment`）。
- 根因：dev 库 `data/auto_wechat.db` schema 漂移（[[dev-db-schema-drift]]），Phase 10 Task 2 时已 stash 验证非 Phase 10 引入（[[compute-pipeline-status]] 记录）。
- **起点对照（Task 7-FIX1 补）**：起点 `265d719` 同命令 = **66 passed / 1 failed**（同一 `test_apply_does_not_touch_existing_tables`，同一 `sales_staff.enable_lead_assignment` NOT NULL），与当前完全一致，确认 pre-existing。

### 3.4 前端复验

```
cd frontend
npm run phase10-compute:check   # Phase 10 算力前端合同：PASS
npm run encoding:check          # 207 文件无 PUA 乱码
npx tsc -b                      # 退出码 0，零类型错误
npm run build                   # ✓ built（chunk size 警告 pre-existing，不影响）
```

### 3.5 静态硬门禁（5 条）

1. `git diff --check`（工作区）：仅 `docs/待确认事项.md` pre-existing whitespace + LF/CRLF 警告，Phase 10 代码零空白错误。
2. `git diff --check 265d719..HEAD`：退出码 0，Phase 10 全链无空白错误。
3. `rg "https?://|OPENAI_API_KEY|ARK_API_KEY" tests/test_phase10_compute_*.py`：唯一命中 `http://9000.test`（fake_urlopen 虚构 URL，允许），无真实域名/密钥。
4. `rg "usage\.total_tokens|total_tokens" apps/xg_douyin_ai_cs/services/{reply_decision,daily_report_summary,return_visit_judge,knowledge_training}_service.py`：**零命中**（注释改措辞后）。
5. `git diff --unified=0 265d719..HEAD -- app/models.py app/schemas.py apps/compute apps/xg_douyin_ai_cs frontend/src/features/compute | grep 'ad_review|ai_edit|input_writer|poll-and-send-report'`：**零命中**，Phase 10 未越界引入其他 Phase 代码。

---

## 4. 真实外部调用 = 0

- **真实 LLM**：0（所有测试用 stub `_FakeLLM` / `fake_chat`）。
- **真实 Embedding**：0（mock embedding `model=mock_for_test_only` 不上报；真实 embedding 测试用 `_RealEmbed` 本地桩）。
- **真实抖音**：0（webhook/私信不触发，9100 回复建议走 mock chat）。
- **真实宝塔/生产数据库**：0（全部本地 SQLite / 内存库 / 临时 PG 合同测试，未连宝塔）。
- **真实网络**：0（**仅 Phase 10 专项测试** `test_phase10_compute_no_network.py` + `test_phase10_compute_metering.py` 的文件级哨兵计数 + yield 断言强制零真实网络；非专项测试未覆盖哨兵，不据此夸大为"全部测试零网络"；`http://9000.test` 为虚构 URL 被 fake_urlopen 拦截）。

---

## 5. Phase 10 状态

- **Phase 10 代码与模拟闭环**：`DONE`。
- **Phase 10 总状态**：`DONE_WITH_CONCERNS`。
- **三方复审**：2026-07-15 Spec/Code Quality/Security 三方 PASS（首轮 BLOCKED 5 个 Must-Fix 由 Task 7-FIX1 `0821759` 闭合后复审放行；复审范围 `47884ba..0821759`，本地 75 passed，扩展回归失败按起点对照认定为既有问题）。
- **唯一 concern**：`baota_production_compute_not_verified`（宝塔生产环境算力链路未验证）。
- **concern 影响**：不阻塞 Phase 12/13；统一宝塔验证只能在 Phase 13 完成后另开执行包。

---

## 6. 其他阶段状态（保持不变，未改写）

- Phase 9（回访）：`DONE_WITH_CONCERNS(baota_production_send_not_verified)` — 状态 0.1，不改写。
- Phase 8-B（微信附件）：`PARTIAL_BLOCKED_DEFERRED`（Qt UIA 文件气泡转 verify_pending 人工审计）— 状态 0.1，不改写。
- Phase 11（一键过审）：`CANCELLED_BY_CUSTOMER`（2026-07-13）— 状态 0.1，不改写。
- 日报真实分发：状态 0.1，不改写。

---

## 7. 完成定义核对（执行包 §8）

- [x] 三套餐和六能力 seed 经临时库验证幂等。
- [x] usage 强制可信 merchant、六能力和 model；聊天优先使用供应商真实 Token，缺失时估算，旧客户端保持兼容。
- [x] 上浮向上取整，流水同时保存基础用量、计量方式、供应商明细、调用阶段、比例快照和计费值；历史流水不伪造能力或 Token 明细。
- [x] 余额不足不阻断，技术溢出不产生半写入（BIGINT 整笔拒绝 + SAVEPOINT）。
- [x] 当前五类 AI 操作全部埋点，重试逐次计量，Mock/失败不扣费。
- [x] 上浮配置仅精确权限或超管可改；普通商户不能越权。
- [x] 商户和超管页面完成真实 API 闭环，支付仍为 mock。
- [x] SQLite/PG 合同、后端、AI 相邻回归、前端合同/类型/构建：**目标专项通过、扩展回归零新增失败**（pre-existing 失败已起点对照，不强制全绿）。
- [x] Phase 10 专项测试哨兵强制零真实网络（非专项测试未覆盖哨兵，不夸大为"全部测试零网络"）；宝塔验证保持未启动。

---

## 8. 最终硬暂停

不启动服务、不连接宝塔、不执行真实迁移、不进入任何真实 AI/抖音验证。等待审批窗口制定下一有效阶段执行包。

---

## 9. COMPUTE-OPT-03 管理员算力配置接入（候选实现完成、待独立测试）

> 执行包：`docs/superpowers/plans/2026-07-17-compute-opt-03-admin-compute-config-implementation-plan.md`
> 计划哈希：`50cec9a34b1cf80b891b42a04e2da7c7d5903aa3`
> 对照基线：`e2d439e`（HEAD 必须精确等于此提交，已预检通过）
> 范围：把管理员算力配置收敛为单入口 `/admin/compute-config`，9000 与独立计算服务统一精确权限码 `auto_wechat:admin:compute_config`，管理写入产出结构化审计日志且不回显敏感字段。

### 9.1 候选提交链

| 提交 | 边界 | 说明 |
|---|---|---|
| `4aa3e44` | 提交 A | 统一管理员算力配置接口权限（9000 `app/routers/compute.py` + 独立服务 `apps/compute/dependencies.py`、`apps/compute/routers.py` + 三份测试） |
| `397e7c2` | 提交 B | 接通管理员算力配置统一入口（9 个前端文件：App.tsx / newcarRedirect.ts / SideNav.tsx / capabilities.ts / routes.ts / compute/routes.ts / Index.tsx / SuperComputeConfig.tsx / check-phase10-compute-contract.mjs） |
| 待定 | 提交 C | 文档原位更新（本节 + 05_PROJECT_CONTEXT.md + 总设计阶段三状态） |

### 9.2 当前合同增量

- **统一单入口**：`/admin/compute-config` 默认进入"计费比例"，内含三个视图——计费比例 `?view=ratios`、套餐管理 `?view=packages`、商户发放 `?view=merchant-grant`，通过 `useSearchParams` 切换（非 ModuleTabs）。
- **旧地址兼容**：`/compute/packages` → `/admin/compute-config?view=packages`，`/compute/markup-ratios` → `/admin/compute-config?view=ratios`（`legacyRouteRedirects`）。
- **导航与权限分发**：管理员侧栏新增带 `CoinsIcon` 的"算力"项（`admin-compute-config`，需 `auto_wechat:admin:compute_config`）；`defaultPathForUser` 与 `canAccessPath` 按精确权限分发；普通商户直访 `/admin/compute-config` 走权限拒绝分支。
- **精确权限**：9000 `_require_compute_config_admin` 与独立服务 `require_compute_config_admin` / 网关上下文统一 `auto_wechat:admin:compute_config`，拒绝 `auto_wechat:compute`、其他管理员权限、无上下文、缺失网关上下文；独立服务网关上下文只读 `X-Gateway-*` 头，不信任前端正文或查询参数。
- **结构化审计日志**：所有管理写入（创建/更新/禁用套餐、商户充值、发放套餐、上浮比例更新）经 `_admin_compute_action` 上下文管理器产出 `compute_admin_action operation=<op> operator_id=<id> target=<sanitized> status=<success|failed> failure_stage=<stage|none> error_type=<exc|none>`；`_safe_log_value` 脱敏，备注等敏感字段不入日志。

### 9.3 测试数量

- **后端 compute 冻结集（11 文件）**：`179 passed, 1 failed`。唯一 failed 为 `test_phase10_compute_markup_api.py::test_9000_update_affects_new_usage_not_old_snapshot`（`KeyError: 'markup_basis_points'`），属 COMPUTE-OPT-02 将 `/compute/transactions` 收敛为 7 字段公开投影的既有残留，基线 `e2d439e` stash 对照零新增，超出 COMPUTE-OPT-03 边界不可触碰。
- **前端**：`npm run phase10-compute:check` PASS；`npm run build` ✓ built（chunk size 警告 pre-existing）；`npx tsc --noEmit -p tsconfig.app.json` 退出码 0。

### 9.4 未覆盖浏览器场景（BLOCKED_ENVIRONMENT）

Task 7 浏览器视口矩阵在执行窗口未运行：无测试窗口、无运行态前端栈、无法构造精确管理员权限登录态。按执行包 §10.2 规则，静态代码证据不写成浏览器通过。下列路径仅静态核验结构成立，运行时验证留给测试窗口：

1. `/admin/compute-config` 默认显示"计费比例"——静态：`normalizeConfigView` 默认 `ratios`。
2. 三视图可点击切换且 URL 分别为 `view=ratios/packages/merchant-grant`——静态：`CONFIG_VIEWS` + `selectView` 调 `setSearchParams`。
3. `/compute/packages` 跳转套餐管理视图——静态：`legacyRouteRedirects`。
4. `/compute/markup-ratios` 跳转计费比例视图——静态：`legacyRouteRedirects`。
5. 管理员侧栏存在带图标"算力配置"——静态：`SideNav.adminItems` + `adminIcons`。
6. 1024/1440 视口无横向溢出、按钮输入框不重叠——**运行时未验**。
7. 加载/空数据/错误重试/成功反馈可见——**运行时未验**。
8. 普通商户直访 `/admin/compute-config` 显示权限拒绝——静态：`canAccessPath` 校验 `adminComputeConfig`，未通过走拒绝分支；运行时未验。

### 9.5 残余风险

- `baota_production_compute_not_verified`：未变，宝塔生产算力链路仍待 Phase 13 后统一验证。
- `markup_basis_points` 既有测试失败：COMPUTE-OPT-02 公开投影残留，不在本包范围。
- `react-hooks/set-state-in-effect` eslint 错误：基线 `e2d439e` 本就红（Index.tsx 3 处、SuperComputeConfig.tsx 2 处，共 5 处），本包改动将 SuperComputeConfig 两处 effect 合并为一处、删除 Index.tsx `isComputeConfigNav` effect，错误数较基线减少；属基线前端技术债，非本包引入，修复需重构数据获取架构（超出本包边界，有行为风险）。
- 浏览器矩阵：`BLOCKED_ENVIRONMENT`，待测试窗口在运行态补验。

### 9.6 真实外部调用 = 0

执行窗口未启动服务、未连宝塔/生产 PG、未触发真实付费模型调用、未进入测试窗口。
