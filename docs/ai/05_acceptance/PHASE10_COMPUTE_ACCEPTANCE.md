# Phase 10 小高算力模拟验收（DONE_WITH_CONCERNS）

> 验收日期：2026-07-15
> 执行包：`docs/superpowers/plans/2026-07-14-phase10-compute-execution-package.md`
> 起点：`265d719`（Phase 9 总验收 FIX1）→ 终点：`ba7d7fb`（Task 6 前端闭环）
> 验收范围：本地模拟闭环，**未启动服务、未连宝塔、未真实迁移、未真实 AI/抖音验证**

---

## 1. 提交链与文件范围

| 提交 | Task | 说明 |
|---|---|---|
| `332e697` | Task 0-1 | 冻结红灯数据合同（schema 5 failed/2 passed/10 skipped + PG 1 failed/15 skipped） |
| `e6d20ee` | Task 2 | ORM 加 ComputeTransaction 3 列 + ComputeMarkupRatio + SQLite 0031 + PG 0012 |
| `a273019` | Task 2-FIX | 0031 精确列集守卫（pragma_table_info）+ 越序降级守卫 |
| `1f13970` | Task 2-FIX2 | 改 pragma_table_xinfo（含生成列）+ hidden=0 列名守卫 |
| `fce206a` | Task 3 | calculate_billed_tokens（ceil 上浮/BIGINT 天花板）+ record_usage 严格合同 + with_for_update 行锁 |
| `8db606c` | Task 4 | 六能力上浮管理 API + 精确权限 `auto_wechat:admin:compute_config` |
| `eeaba0f` | Task 5 | 9100 按字符计量 + 全部现有 AI 埋点（reply_decision/daily_report/return_visit/knowledge_ask/embedding） |
| `556742a` | Task 3-5-FIX | 5 偏差闭合（daily_report 映射/client strip/conversation_id/并发建账/负余额告警） |
| `e5cadac` | Task 3-5-FIX2 | 5 门禁闭合（BIGINT 区间/网络哨兵/空白 merchant_id/真实并发建账/retry 分别计量） |
| `57faa52` | FIX3 | 删全局 conftest + 哨兵限 Phase 10 + 计数 yield 断言 |
| `ba7d7fb` | Task 6 | 商户流水 + 超管上浮配置前端闭环（8 文件 +465 行） |

**Task 7 额外改动**（修复静态门禁 #4）：`reply_decision_service.py` + `daily_report_summary_service.py` 注释措辞调整（"usage.total_tokens" → "provider 返回的 token 用量"），让 `rg total_tokens` 零命中，语义不变。

---

## 2. 计费合同（§0.2，甲方已批准）

- **字符计量**：`count_chat_characters`（messages 内容 + reply_text，不 strip）+ `count_embedding_characters`（Python len）。供应商 `usage.total_tokens` **不参与计费**（4 个 service 文件 `rg total_tokens` 零命中）。
- **上浮比例**：六能力 `douyin-cs/leads/agents/wechat-assistant/compute/knowledge`，`markup_basis_points`（基点，3300=33%），`calculate_billed_tokens = ceil(actual × (1 + markup/10000))`，超 BIGINT 整笔拒绝。
- **快照三列**：`ComputeTransaction.actual_tokens`（实际字符量）/ `capability_key` / `markup_basis_points`，写入时冻结，历史行 NULL 不伪造。
- **能力映射**：reply_decision=douyin-cs、daily_report/return_visit=wechat-assistant、knowledge_ask/_embed_with_usage=knowledge。
- **权限**：上浮配置 GET/PUT `/admin/compute/markup-ratios` 需 `auto_wechat:admin:compute_config` / super_admin；普通商户不可越权。
- **并发建账**：`get_or_create_account` SAVEPOINT + IntegrityError 恢复；`record_usage` 顶层单 commit（账户+流水原子）。
- **负余额**：不阻断，写 `stage=negative_balance` 结构化 warning；前端风险提示不写"服务已停用"。
- **前端字符串转基点**：`parseInt(intPart + paddedFrac, 10)` 纯字符串拼接，零浮点（`"33.5"→"33"+"50"→3350`）。

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
- **真实网络**：0（Phase 10 哨兵计数 + yield 断言强制零真实网络；`http://9000.test` 为虚构 URL 被 fake_urlopen 拦截）。

---

## 5. Phase 10 状态

- **Phase 10 代码与模拟闭环**：`DONE`。
- **Phase 10 总状态**：`DONE_WITH_CONCERNS`。
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
- [x] usage 强制可信 merchant、六能力、model、实际字符量；供应商 token 不参与计费。
- [x] 上浮向上取整，流水同时保存实际、比例快照和计费值；历史流水不伪造能力。
- [x] 余额不足不阻断，技术溢出不产生半写入（BIGINT 整笔拒绝 + SAVEPOINT）。
- [x] 当前五类 AI 操作全部埋点，重试逐次计量，Mock/失败不扣费。
- [x] 上浮配置仅精确权限或超管可改；普通商户不能越权。
- [x] 商户和超管页面完成真实 API 闭环，支付仍为 mock。
- [x] SQLite/PG 合同、后端、AI 相邻回归、前端合同/类型/构建全部通过（pre-existing 失败已起点对照）。
- [x] 全部测试真实外部网络调用为 0；宝塔验证保持未启动。

---

## 8. 最终硬暂停

不启动服务、不连接宝塔、不执行真实迁移、不进入任何真实 AI/抖音验证。等待审批窗口制定下一有效阶段执行包。
